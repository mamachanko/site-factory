import contextlib
from email.message import Message
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from factory import (APIError, FactoryError, GitHub, Site, dispatch,
                     dns_instructions, main, render)


class ValidationTests(unittest.TestCase):
    def test_valid_names(self):
        for name in ('puzzles', 'word-game', 'a', '123', 'a1-b2', 'a' * 63):
            with self.subTest(name=name):
                self.assertEqual(Site(name).name, name)

    def test_invalid_names(self):
        for name in ('', 'a' * 64, 'Puzzles', '-puzzles', 'puzzles-', 'a--b', 'a_b', '.', '..',
                     'mamachanko/puzzles', 'x.git', '.github', 'mamachanko.github.io',
                     'site-factory', ' puzzles', 'puzzles\n', 'a;echo bad', 'a$(pwd)', 'é'):
            with self.subTest(name=name), self.assertRaises(FactoryError):
                Site(name)

    def test_domain_allowlist(self):
        for domain in ('', 'mamachanko.com', 'maxbrauer.com', 'puzzles.mamachanko.com',
                       'word.games.maxbrauer.com', '1-a.maxbrauer.com'):
            with self.subTest(domain=domain):
                self.assertEqual(Site('puzzles', domain=domain).domain, domain)

    def test_invalid_domains(self):
        for domain in ('evil.com', 'evilmamachanko.com', 'mamachanko.com.evil.com',
                       'https://puzzles.mamachanko.com', 'puzzles.mamachanko.com/path',
                       'puzzles.mamachanko.com:443', '*.mamachanko.com', 'puzzles.mamachanko.com.',
                       'Puzzles.mamachanko.com', 'a..mamachanko.com', '-a.mamachanko.com',
                       'a-.mamachanko.com', 'a_b.mamachanko.com', 'a' * 64 + '.mamachanko.com',
                       'a@mamachanko.com', 'mamachanko.com\n', 'é.maxbrauer.com'):
            with self.subTest(domain=domain), self.assertRaises(FactoryError):
                Site('puzzles', domain=domain)

    def test_description_limits(self):
        Site('puzzles', description='x' * 350)
        for description in ('x' * 351, 'line\nbreak', '\x00', '\t', '\x7f'):
            with self.subTest(description=description), self.assertRaises(FactoryError):
                Site('puzzles', description=description)

    def test_dns_subdomain_nested_apex_and_default(self):
        text = dns_instructions(Site('puzzles', domain='puzzles.mamachanko.com'))
        self.assertIn('| CNAME | puzzles | mamachanko.github.io | Automatic |', text)
        self.assertIn('word.games', dns_instructions(Site('puzzles', domain='word.games.maxbrauer.com')))
        apex = dns_instructions(Site('puzzles', domain='maxbrauer.com'))
        self.assertEqual(apex.count('| A | @ |'), 4)
        self.assertNotIn('| CNAME |', apex)
        self.assertEqual(dns_instructions(Site('puzzles')), 'No DNS changes required.')


class GenerationTests(unittest.TestCase):
    def test_starter_is_complete_independent_and_substituted(self):
        files = render(Site('puzzles', 'A collection of mobile-first word games', 'puzzles.mamachanko.com'))
        required = {'site/index.html', 'site/styles.css', 'site/app.mjs', 'AGENTS.md', 'CLAUDE.md',
                    'README.md', '.github/workflows/ci.yml', '.github/workflows/deploy.yml',
                    'scripts/check_site.py', 'tests/puzzle.test.mjs', '.gitignore'}
        self.assertEqual(set(files), required)
        self.assertIn('<title>puzzles</title>', files['site/index.html'])
        self.assertIn('A collection of mobile-first word games', files['site/index.html'])
        self.assertIn('https://puzzles.mamachanko.com/', files['README.md'])
        self.assertFalse(any('__SITE_' in content for content in files.values()))
        self.assertNotIn('CNAME', files)
        self.assertFalse(any('SITE_FACTORY_APP_' in content for content in files.values()))
        self.assertIn('AGENTS.md', files['CLAUDE.md'])

    def test_html_injection_is_escaped(self):
        attack = '\"><script>alert("x")</script> & hello'
        content = render(Site('puzzles', attack))['site/index.html']
        self.assertIn('&quot;&gt;&lt;script&gt;', content)
        self.assertNotIn('<script>alert', content)

    def test_replacement_is_not_recursive(self):
        content = render(Site('puzzles', '__SITE_NAME__'))['site/index.html']
        self.assertIn('content="__SITE_NAME__"', content)

    def test_default_url_and_description(self):
        files = render(Site('puzzles'))
        self.assertIn('https://mamachanko.github.io/puzzles/', files['README.md'])
        self.assertIn('A little space', files['site/index.html'])

    def test_unknown_placeholder_and_symlink_fail_before_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'bad').write_text('__SITE_UNKNOWN__')
            with self.assertRaisesRegex(FactoryError, 'Unknown'):
                render(Site('puzzles'), root)
            (root / 'bad').unlink()
            (root / 'link').symlink_to(ROOT / 'LICENSE')
            with self.assertRaisesRegex(FactoryError, 'symlinks'):
                render(Site('puzzles'), root)

    def test_generated_static_checks_and_syntax(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, content in render(Site('puzzles', 'A & B <puzzle>')).items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            subprocess.run([sys.executable, 'scripts/check_site.py'], cwd=root, check=True, capture_output=True)
            subprocess.run(['node', '--check', 'site/app.mjs'], cwd=root, check=True, capture_output=True)
            subprocess.run(['node', '--test', 'tests/puzzle.test.mjs'], cwd=root, check=True, capture_output=True)
            # Demonstrate the site checks fail when a referenced asset is missing.
            (root / 'site/styles.css').unlink()
            result = subprocess.run([sys.executable, 'scripts/check_site.py'], cwd=root, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('missing link target: ./styles.css', result.stderr)


class GitHubTests(unittest.TestCase):
    def test_dispatch_retries_registration_delays_and_stops(self):
        api, sleep = Mock(), Mock()
        api.request.side_effect = [APIError('POST', '/dispatches', 404), APIError('POST', '/dispatches', 422), None]
        dispatch(api, Site('puzzles'), sleep=sleep)
        self.assertEqual(api.request.call_count, 3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [1, 2])

    def test_dispatch_retry_budget_and_fatal_errors(self):
        for status, expected in ((404, 8), (422, 8), (403, 1), (500, 1)):
            api, sleep = Mock(), Mock()
            api.request.side_effect = APIError('POST', '/dispatches', status)
            with self.subTest(status=status), self.assertRaises(APIError):
                dispatch(api, Site('puzzles'), sleep=sleep)
            self.assertEqual(api.request.call_count, expected)
            self.assertLessEqual(sum(c.args[0] for c in sleep.call_args_list), 60)

    def test_http_errors_never_echo_response_bodies_or_tokens(self):
        with patch.dict(os.environ, {'GH_TOKEN': 'secret-test-token'}, clear=True):
            api = GitHub()
            api.opener = Mock()
            api.opener.open.side_effect = urllib.error.HTTPError('https://api.github.com/user/repos', 403,
                'secret-test-token', {}, io.BytesIO(b'secret-test-token'))
            with self.assertRaises(APIError) as caught:
                api.request('POST', '/user/repos', {})
            self.assertNotIn('secret-test-token', str(caught.exception))
            request = api.opener.open.call_args.args[0]
            self.assertEqual(request.full_url, 'https://api.github.com/user/repos')
            self.assertEqual(request.get_header('X-github-api-version'), '2026-03-10')


class CLITests(unittest.TestCase):
    def run_cli(self, args, env):
        output = io.StringIO()
        with patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(output):
            result = main(args)
        return result, output.getvalue()

    def test_dry_run_never_initializes_github_or_runs_git(self):
        with patch('factory.GitHub') as api, patch('factory.subprocess.run') as run:
            result, output = self.run_cli([], {'REPOSITORY_NAME': 'puzzles', 'CUSTOM_DOMAIN': 'puzzles.mamachanko.com'})
        self.assertEqual(result, 0)
        self.assertIn('DRY RUN', output)
        self.assertIn('Target repository and Pages settings are not checked', output)
        self.assertIn('| CNAME | puzzles | mamachanko.github.io |', output)
        api.assert_not_called()
        run.assert_not_called()

    def test_retired_phases_and_receipts_are_not_cli_options(self):
        for args in (['create'], ['finish'], ['initialize', '--state', '/unused']):
            with self.subTest(args=args), patch('factory.GitHub') as api, contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    main(args)
                self.assertEqual(caught.exception.code, 2)
                api.assert_not_called()

    def test_invalid_input_fails_before_credentials(self):
        with patch('factory.GitHub') as api:
            result, output = self.run_cli(['initialize'], {'REPOSITORY_NAME': '../oops'})
        self.assertEqual(result, 1)
        self.assertIn('Validation', output)
        api.assert_not_called()

    def test_failure_is_nonzero_and_written_to_summary_without_secrets(self):
        with tempfile.TemporaryDirectory() as directory, patch('factory.GitHub') as github:
            summary = Path(directory) / 'summary.md'
            github.return_value.request.side_effect = APIError('GET', '/repos/mamachanko/puzzles', 403)
            result, output = self.run_cli(['initialize'],
                {'REPOSITORY_NAME': 'puzzles', 'GITHUB_STEP_SUMMARY': str(summary), 'GH_TOKEN': 'secret'})
            self.assertEqual(result, 1)
            self.assertIn('HTTP 403', summary.read_text())
            self.assertIn('No automatic rollback', output)
            self.assertNotIn('secret', output)

    def test_initialize_http_failure_reports_only_safe_diagnostics(self):
        request_id = 'CFF6:2A1BFD:91E587C:DB831B4:6AFEE42D'
        cases = (
            (403, {}, {'message': 'Resource not accessible by integration'}, 'access denied'),
            (403, {}, {'message': 'Resource not accessible by personal access token'}, 'access denied'),
            (429, {}, {'message': 'private unknown message'}, 'rate limited'),
            (403, {'X-RateLimit-Remaining': '0'}, {}, 'rate limited'),
            (403, {'Retry-After': '60'}, {}, 'rate limited'),
            (403, {'X-RateLimit-Remaining': '4994'}, {'message': 'Rate Limit Exceeded'}, 'rate limited'),
            (403, {}, {'message': 'API rate limit exceeded for 192.0.2.1.'}, 'rate limited'),
            (403, {}, {'message': 'You have exceeded a secondary rate limit. Please wait a few minutes before you try again.'}, 'rate limited'),
            (403, {}, {'message': 'private unknown message'}, None),
            (403, {'X-RateLimit-Remaining': '4994'}, {'message': 'private unknown message'}, None),
            (403, {}, {'message': 'Resource not accessible by integration private unknown message'}, None),
            (500, {}, {'message': 'Resource not accessible by integration'}, None),
            (403, {}, {'message': ['private unknown message']}, None),
            (403, {}, ['private unknown message'], None),
            (403, {}, b'not JSON private unknown message', None),
            (403, {}, b'\xff private unknown message', None),
        )
        for status, headers, body, category in cases:
            with self.subTest(status=status, headers=headers, body=body):
                response_headers = Message()
                for key, value in {**headers, 'x-github-request-id': request_id,
                                   'X-Private-Header': 'secret-test-token'}.items():
                    response_headers[key] = value
                if not isinstance(body, bytes):
                    body = json.dumps({**body, 'private': 'secret-test-token'} if isinstance(body, dict) else body).encode()
                failure = urllib.error.HTTPError('https://api.github.com/user/repos', status,
                    'secret-test-token', response_headers, io.BytesIO(body))
                self.assert_initialize_http_failure(failure, category, request_id)

    def test_initialize_http_failure_rejects_unsafe_request_ids_and_preserves_unreadable_status(self):
        for request_id in ('secret-test-token', 'ABCD:123456:ABCDEF:123456:ABCDEF12\nsecret-test-token',
                           '<script>secret-test-token</script>', 'ABCD1234', 'A:B:C:D:E:F', 'A:' + 'B' * 200):
            with self.subTest(request_id=request_id):
                failure = urllib.error.HTTPError('https://api.github.com/user/repos', 403, 'secret-test-token',
                    {'X-GitHub-Request-Id': request_id}, io.BytesIO(b'{"message":"Rate Limit Exceeded"}'))
                self.assert_initialize_http_failure(failure, 'rate limited', None)
        unreadable = Mock()
        unreadable.read.side_effect = OSError('secret-test-token')
        failure = urllib.error.HTTPError('https://api.github.com/user/repos', 403, 'secret-test-token',
            {'X-RateLimit-Remaining': '0'}, unreadable)
        self.assert_initialize_http_failure(failure, 'rate limited', None)
        deeply_nested = io.BytesIO(b'[' * 16000 + b']' * 16000)
        request_id = 'CFF6:2A1BFD:91E587C:DB831B4:6AFEE42D'
        failure = urllib.error.HTTPError('https://api.github.com/user/repos', 403, 'secret-test-token',
            {'X-GitHub-Request-Id': request_id}, deeply_nested)
        self.assert_initialize_http_failure(failure, None, request_id)

    def assert_initialize_http_failure(self, failure, category, request_id):
        with tempfile.TemporaryDirectory() as directory, patch('factory.urllib.request.build_opener') as build_opener:
            opener = build_opener.return_value
            opener.open.side_effect = failure
            summary = Path(directory) / 'summary.md'
            result, output = self.run_cli(['initialize'],
                {'REPOSITORY_NAME': 'puzzles', 'GITHUB_STEP_SUMMARY': str(summary), 'GH_TOKEN': 'secret-test-token'})
            self.assertEqual(result, 1)
            self.assertEqual(opener.open.call_count, 1)
            self.assertEqual([call.args[0].method for call in opener.open.call_args_list], ['GET'])
            self.assertEqual(opener.open.call_args.args[0].full_url, 'https://api.github.com/repos/mamachanko/puzzles')
            for report in (output, summary.read_text()):
                self.assertIn(f'GitHub GET /repos/mamachanko/puzzles failed (HTTP {failure.code}).', report)
                if category:
                    self.assertIn(f'Category: {category}.', report)
                else:
                    self.assertNotIn('Category:', report)
                if request_id:
                    self.assertIn(f'GitHub request ID: {request_id}.', report)
                else:
                    self.assertNotIn('GitHub request ID:', report)
                for unsafe in ('secret-test-token', 'private unknown message', '<script>',
                               'X-Private-Header', 'Bearer', '192.0.2.1'):
                    self.assertNotIn(unsafe, report)


class InitializationTests(unittest.TestCase):
    run_cli = CLITests.run_cli

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.bare = self.root / 'remote.git'
        self.real_run = subprocess.run
        self.real_run(['git', 'init', '--bare', str(self.bare)], check=True, capture_output=True)
        self.repo = {'id': 42, 'name': 'puzzles', 'full_name': 'mamachanko/puzzles',
                     'owner': {'login': 'mamachanko', 'type': 'User'}, 'private': False,
                     'visibility': 'public', 'archived': False, 'disabled': False,
                     'fork': False, 'mirror_url': None, 'default_branch': 'main'}
        self.pages = None
        self.calls = []
        self.git_calls = []
        self.before_git = lambda command: None
        self.before_request = lambda method, path, payload: None
        self.after_request = lambda method, path, payload: None
        self.api = Mock()
        self.api.request.side_effect = self.request

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        self.before_request(method, path, payload)
        if path.endswith('/pages'):
            if method == 'GET':
                if self.pages is None:
                    raise APIError(method, path, 404)
                result = dict(self.pages)
            elif method == 'POST':
                self.pages = {'build_type': payload['build_type'], 'cname': None}
                result = dict(self.pages)
            elif method == 'PUT':
                self.pages.update(payload)
                result = None
            else:
                self.fail((method, path, payload))
        elif path.endswith('/dispatches'):
            self.assertEqual((method, payload), ('POST', {'ref': 'main'}))
            result = None
        elif path == '/repos/mamachanko/puzzles':
            if method == 'PATCH':
                self.repo.update(payload)
            else:
                self.assertEqual(method, 'GET')
            result = dict(self.repo)
        else:
            self.fail((method, path, payload))
        self.after_request(method, path, payload)
        return result

    def git(self, *args, cwd=None):
        return self.real_run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()

    def remote(self, *args):
        return self.git('--git-dir', str(self.bare), *args)

    def source(self, *, raw=False, files=None, modes=None):
        root = self.root / 'source'
        root.mkdir()
        self.git('init', '--template=', '--initial-branch=main', cwd=root)
        for name, content in (files if files is not None else render(Site('puzzles'), raw=raw)).items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
            if modes and name in modes:
                path.chmod(modes[name])
        self.git('add', '.', cwd=root)
        self.git('-c', 'user.name=test', '-c', 'user.email=test@example.com',
                 '-c', 'commit.gpgsign=false', 'commit', '-m', 'Original template', cwd=root)
        self.git('push', str(self.bare), 'main', cwd=root)
        return self.remote('rev-parse', 'main')

    def initialize(self, *, domain='', description=''):
        def run(command, **kwargs):
            self.git_calls.append((command, kwargs.get('env', {})))
            self.assertEqual(kwargs['timeout'], 90)
            self.before_git(command)
            if 'remote' in command and command[-4:-1] == ['remote', 'add', 'origin']:
                command = [*command[:-1], str(self.bare)]
            return self.real_run(command, **kwargs)
        with patch('factory.GitHub', return_value=self.api), patch('factory.subprocess.run', side_effect=run):
            return self.run_cli(['initialize'], {'REPOSITORY_NAME': 'puzzles', 'SITE_DESCRIPTION': description,
                'CUSTOM_DOMAIN': domain, 'GH_TOKEN': 'secret-test-token', 'GIT_TRACE': 'secret-test-token',
                'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'core.hooksPath', 'GIT_CONFIG_VALUE_0': '/unsafe'})

    def writes(self):
        return [(method, path, payload) for method, path, payload in self.calls if method != 'GET']

    def test_empty_target_gets_one_independent_commit_and_configured_pages(self):
        self.repo['default_branch'] = 'master'
        result, output = self.initialize(domain='puzzles.mamachanko.com')
        self.assertEqual((result, self.remote('rev-list', '--count', 'main')), (0, '1'), output)
        self.assertEqual(self.remote('show', 'main:site/index.html'), render(Site('puzzles', domain='puzzles.mamachanko.com'))['site/index.html'].strip())
        self.assertIn('[skip ci]', self.remote('log', '-1', '--format=%B', 'main'))
        self.assertEqual(self.repo['default_branch'], 'main')
        self.assertEqual(self.pages, {'build_type': 'workflow', 'cname': 'puzzles.mamachanko.com'})
        self.assertEqual([call[0] for call in self.writes()], ['PATCH', 'POST', 'PUT', 'POST'])
        self.assertTrue(self.writes()[-1][1].endswith('/dispatches'))
        for command, env in self.git_calls:
            self.assertNotIn('secret-test-token', ' '.join(command))
            self.assertNotIn('GIT_TRACE', env)
            self.assertNotIn('GIT_CONFIG_COUNT', env)
            self.assertNotIn('--force', command)
            self.assertNotIn('checkout', command)
            self.assertNotIn('clone', command)
        self.assertNotIn('secret-test-token', output)
        self.assertIn('Site initialized', output)
        self.assertNotIn('secret-test-token', self.remote('show', 'main:README.md'))

    def test_first_push_can_automatically_select_main_as_default(self):
        self.repo['default_branch'] = 'master'
        def auto_select(method, path, payload):
            if method == 'GET' and path == '/repos/mamachanko/puzzles' and self.remote('for-each-ref'):
                self.repo['default_branch'] = 'main'
        self.before_request = auto_select
        result, output = self.initialize()
        self.assertEqual(result, 0, output)
        self.assertEqual(self.repo['default_branch'], 'main')
        self.assertFalse(any(method == 'PATCH' for method, _, _ in self.calls))

    def test_raw_template_history_is_preserved_as_direct_parent(self):
        parent = self.source(raw=True)
        result, output = self.initialize()
        self.assertEqual(result, 0, output)
        self.assertEqual(self.remote('rev-parse', 'main^'), parent)
        self.assertEqual(self.remote('rev-list', '--count', 'main'), '2')
        self.assertEqual(self.remote('show', 'main:README.md'), render(Site('puzzles'))['README.md'].strip())
        self.assertIn('[skip ci]', self.remote('log', '-1', '--format=%B', 'main'))

    def test_exact_rendered_rerun_only_dispatches(self):
        parent = self.source()
        self.pages = {'build_type': 'workflow', 'cname': None}
        for _ in range(2):
            self.calls.clear()
            result, output = self.initialize()
            self.assertEqual(result, 0, output)
            self.assertEqual(self.remote('rev-parse', 'main'), parent)
            self.assertEqual(len(self.writes()), 1)
            self.assertTrue(self.writes()[0][1].endswith('/dispatches'))
        self.assertFalse(any('push' in call[0] for call in self.git_calls))

    def test_interrupted_pages_mutations_converge_using_fresh_state(self):
        for interrupted_method in ('POST', 'PUT'):
            with self.subTest(method=interrupted_method):
                self.pages = None
                self.calls.clear()
                def interrupt(method, path, payload):
                    if method == interrupted_method and path.endswith('/pages'):
                        self.after_request = lambda *args: None
                        raise FactoryError('Uncertain Pages response')
                self.after_request = interrupt
                result, output = self.initialize(domain='puzzles.mamachanko.com')
                self.assertEqual(result, 1, output)
                parent = self.remote('rev-parse', 'main')
                self.calls.clear()
                result, output = self.initialize(domain='puzzles.mamachanko.com')
                self.assertEqual(result, 0, output)
                self.assertEqual(self.remote('rev-parse', 'main'), parent)
                self.assertFalse(any(method == interrupted_method and path.endswith('/pages') for method, path, _ in self.writes()))

    def test_interrupted_default_branch_update_can_finish_from_rendered_state(self):
        self.repo['default_branch'] = 'master'
        def interrupt(method, path, payload):
            if method == 'PATCH':
                raise APIError(method, path, 403)
        self.before_request = interrupt
        result, output = self.initialize()
        self.assertEqual(result, 1, output)
        parent = self.remote('rev-parse', 'main')
        self.assertEqual(self.repo['default_branch'], 'master')
        self.before_request = lambda *args: None
        result, output = self.initialize()
        self.assertEqual(result, 0, output)
        self.assertEqual(self.remote('rev-parse', 'main'), parent)
        self.assertEqual(self.repo['default_branch'], 'main')

    def test_different_rendering_is_rejected_without_api_writes(self):
        parent = self.source()
        result, output = self.initialize(description='Different original inputs')
        self.assertEqual(result, 1, output)
        self.assertIn('refusing to overwrite source', output)
        self.assertEqual(self.remote('rev-parse', 'main'), parent)
        self.assertEqual(self.writes(), [])

    def test_other_source_bytes_paths_and_modes_are_rejected(self):
        files = render(Site('puzzles'))
        files['site/index.html'] += '\nUser edit\n'
        self.source(files=files)
        result, output = self.initialize()
        self.assertEqual(result, 1, output)
        self.assertEqual(self.writes(), [])
        self.assertFalse(any('push' in call[0] for call in self.git_calls))

    def test_extra_executable_mode_is_rejected(self):
        self.source(raw=True, modes={'scripts/check_site.py': 0o755})
        result, output = self.initialize()
        self.assertEqual(result, 1, output)
        self.assertEqual(self.writes(), [])

    def test_added_tracked_file_is_rejected(self):
        self.source(raw=True, files={**render(Site('puzzles'), raw=True), 'unexpected': 'extra'})
        result, output = self.initialize()
        self.assertEqual(result, 1, output)
        self.assertEqual(self.writes(), [])

    def test_other_branches_or_tags_are_rejected(self):
        parent = self.source(raw=True)
        for ref in ('refs/heads/other', 'refs/tags/v1'):
            with self.subTest(ref=ref):
                self.remote('update-ref', ref, parent)
                result, output = self.initialize()
                self.assertEqual(result, 1, output)
                self.assertIn('unsupported refs', output)
                self.assertEqual(self.writes(), [])
                self.remote('update-ref', '-d', ref)

    def test_concurrent_push_is_rejected_without_overwriting_history(self):
        parent = self.source(raw=True)
        competing = None
        def race(command):
            nonlocal competing
            if 'push' in command:
                self.before_git = lambda command: None
                source = self.root / 'source'
                self.git('-c', 'user.name=test', '-c', 'user.email=test@example.com',
                         '-c', 'commit.gpgsign=false', 'commit', '--allow-empty', '-m', 'Concurrent edit', cwd=source)
                self.git('push', str(self.bare), 'main', cwd=source)
                competing = self.remote('rev-parse', 'main')
        self.before_git = race
        result, output = self.initialize()
        self.assertEqual(result, 1, output)
        self.assertNotEqual(competing, parent)
        self.assertEqual(self.remote('rev-parse', 'main'), competing)
        self.assertEqual(self.writes(), [])
        self.assertIn('No force push was attempted', output)

    def test_target_symlink_is_rejected_without_following_it(self):
        self.source(raw=True)
        source = self.root / 'source'
        marker = self.root / 'not-published'
        marker.write_text('private local content')
        path = source / 'site/index.html'
        path.unlink()
        path.symlink_to(marker)
        self.git('add', '.', cwd=source)
        self.git('-c', 'user.name=test', '-c', 'user.email=test@example.com',
                 '-c', 'commit.gpgsign=false', 'commit', '-m', 'Symlink', cwd=source)
        self.git('push', str(self.bare), 'main', cwd=source)
        result, output = self.initialize()
        self.assertEqual(result, 1, output)
        self.assertNotIn('private local content', output)
        self.assertEqual(self.writes(), [])

    def test_raw_template_with_another_default_is_rejected(self):
        self.source(raw=True)
        self.repo['default_branch'] = 'master'
        result, output = self.initialize()
        self.assertEqual(result, 1, output)
        self.assertIn('template target must use main', output)
        self.assertEqual(self.writes(), [])

    def test_inaccessible_target_aborts_before_git(self):
        for status in (401, 403, 404, 429, 500):
            with self.subTest(status=status):
                self.api.reset_mock()
                self.api.request.side_effect = APIError('GET', '/repos/mamachanko/puzzles', status)
                result, output = self.initialize()
                self.assertEqual(result, 1, output)
                self.assertIn(f'HTTP {status}', output)
                self.assertEqual(self.api.request.call_count, 1)
                self.assertEqual(self.git_calls, [])

    def test_unsafe_metadata_is_rejected_before_git_or_writes(self):
        original = dict(self.repo)
        for changes in ({'id': 0}, {'id': True}, {'private': True}, {'visibility': 'private'},
                        {'archived': True}, {'disabled': True}, {'fork': True}, {'mirror_url': 'https://evil'},
                        {'full_name': 'other/puzzles'}, {'name': 'other'}, {'owner': {'login': 'mamachanko', 'type': 'Organization'}},
                        {'owner': {'login': 'other', 'type': 'User'}}):
            with self.subTest(changes=changes):
                self.repo = {**original, **changes}
                result, output = self.initialize()
                self.assertEqual(result, 1, output)
                self.assertEqual(self.git_calls, [])
                self.assertEqual(self.writes(), [])

    def test_pages_conflicts_abort_before_source_push(self):
        for pages, domain in (({'build_type': 'legacy', 'cname': None}, ''),
                              ({'build_type': 'workflow', 'cname': 'other.mamachanko.com'}, ''),
                              ({'build_type': 'workflow', 'cname': 'other.mamachanko.com'}, 'puzzles.mamachanko.com')):
            with self.subTest(pages=pages, domain=domain):
                self.pages = pages
                result, output = self.initialize(domain=domain)
                self.assertEqual(result, 1, output)
                self.assertIn('conflicts', output)
                self.assertEqual(self.writes(), [])
                self.assertEqual(self.remote('for-each-ref'), '')
                self.assertFalse(any('push' in call[0] for call in self.git_calls))

    def test_matching_domain_is_preserved(self):
        self.pages = {'build_type': 'workflow', 'cname': 'puzzles.mamachanko.com'}
        result, output = self.initialize(domain='puzzles.mamachanko.com')
        self.assertEqual(result, 0, output)
        self.assertEqual(len(self.writes()), 1)
        self.assertTrue(self.writes()[0][1].endswith('/dispatches'))

    def test_identity_change_before_push_is_rejected(self):
        gets = 0
        def change_identity(method, path, payload):
            nonlocal gets
            if method == 'GET' and path == '/repos/mamachanko/puzzles':
                gets += 1
                if gets == 2:
                    self.repo['id'] = 43
        self.before_request = change_identity
        result, output = self.initialize()
        self.assertEqual(result, 1, output)
        self.assertEqual(self.remote('for-each-ref'), '')
        self.assertEqual(self.writes(), [])

    def test_main_change_before_settings_prevents_settings_and_dispatch(self):
        parent = self.source(raw=True)
        def change_main(method, path, payload):
            if method == 'GET' and path == '/repos/mamachanko/puzzles' and self.remote('rev-parse', 'main') != parent:
                self.remote('update-ref', 'refs/heads/main', parent)
        self.before_request = change_main
        result, output = self.initialize()
        self.assertEqual(result, 1, output)
        self.assertIn('changed during initialization', output)
        self.assertEqual(self.writes(), [])

    def test_domain_change_before_dispatch_is_rejected(self):
        def change_domain(method, path, payload):
            if method == 'POST' and path.endswith('/pages'):
                self.pages['cname'] = 'other.mamachanko.com'
        self.after_request = change_domain
        result, output = self.initialize()
        self.assertEqual(result, 1, output)
        self.assertFalse(any(path.endswith('/dispatches') for _, path, _ in self.calls))

    def test_pages_response_must_confirm_domain_before_dispatch(self):
        def ignore_domain(method, path, payload):
            if method == 'PUT' and path.endswith('/pages'):
                self.pages['cname'] = None
        self.after_request = ignore_domain
        result, output = self.initialize(domain='puzzles.mamachanko.com')
        self.assertEqual(result, 1, output)
        self.assertIn('was not confirmed', output)
        self.assertFalse(any(path.endswith('/dispatches') for _, path, _ in self.calls))

    def test_dispatch_retries_recheck_main_and_pages(self):
        self.source()
        self.pages = {'build_type': 'workflow', 'cname': None}
        def fail_dispatch(method, path, payload):
            if path.endswith('/dispatches'):
                self.pages['cname'] = 'other.mamachanko.com'
                raise APIError(method, path, 404)
        self.before_request = fail_dispatch
        with patch('factory.dispatch', side_effect=lambda api, site, check: dispatch(api, site, sleep=Mock(), check=check)):
            result, output = self.initialize()
        self.assertEqual(result, 1, output)
        self.assertEqual(sum(path.endswith('/dispatches') for _, path, _ in self.calls), 1)
        self.assertIn('conflicts', output)

    def test_git_failure_diagnostics_hide_secrets(self):
        with patch('factory.GitHub', return_value=self.api), patch('factory.subprocess.run',
                side_effect=subprocess.CalledProcessError(1, ['git'], stderr='secret-test-token')):
            result, output = self.run_cli(['initialize'], {'REPOSITORY_NAME': 'puzzles', 'GH_TOKEN': 'secret-test-token'})
        self.assertEqual(result, 1)
        self.assertNotIn('secret-test-token', output)
        self.assertIn('No force push was attempted', output)


if __name__ == '__main__':
    unittest.main()
