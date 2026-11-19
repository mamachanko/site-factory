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
from factory import (APIError, FactoryError, GitHub, Site, create_repository, dispatch,
                     dns_instructions, finish_repository, main, render, seed_repository)


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
    def test_create_public_repository_after_404(self):
        api = Mock()
        api.request.side_effect = [APIError('GET', '/repos/mamachanko/puzzles', 404),
                                   {'id': 42, 'full_name': 'mamachanko/puzzles', 'private': False}]
        self.assertEqual(create_repository(api, Site('puzzles', 'Games')), 42)
        method, path, payload = api.request.call_args.args
        self.assertEqual((method, path), ('POST', '/user/repos'))
        self.assertEqual(payload['private'], False)
        self.assertEqual(payload['auto_init'], False)

    def test_existing_repository_is_never_modified(self):
        api = Mock()
        api.request.return_value = {'id': 42}
        with self.assertRaisesRegex(FactoryError, 'already exists'):
            create_repository(api, Site('puzzles'))
        self.assertEqual(api.request.call_count, 1)

    def test_preflight_permission_or_server_errors_abort(self):
        for status in (401, 403, 429, 500):
            api = Mock()
            api.request.side_effect = APIError('GET', '/repos/mamachanko/puzzles', status)
            with self.subTest(status=status), self.assertRaises(APIError):
                create_repository(api, Site('puzzles'))
            self.assertEqual(api.request.call_count, 1)

    def test_creation_race_or_hidden_existing_repository_is_not_retried(self):
        api = Mock()
        api.request.side_effect = [APIError('GET', '/repos/mamachanko/puzzles', 404), APIError('POST', '/user/repos', 422)]
        with self.assertRaises(APIError):
            create_repository(api, Site('puzzles'))
        self.assertEqual(api.request.call_count, 2)

    def test_finish_configures_domain_before_dispatch(self):
        api = Mock()
        api.request.side_effect = [
            {'id': 42, 'full_name': 'mamachanko/puzzles', 'private': False}, None, {}, None,
            {'cname': 'puzzles.mamachanko.com', 'build_type': 'workflow'}, None]
        seed = Mock()
        finish_repository(api, Site('puzzles', domain='puzzles.mamachanko.com'), 42, {}, seed=seed)
        seed.assert_called_once()
        calls = [call.args for call in api.request.call_args_list]
        self.assertEqual(calls[2], ('POST', '/repos/mamachanko/puzzles/pages', {'build_type': 'workflow'}))
        self.assertEqual(calls[3][2]['cname'], 'puzzles.mamachanko.com')
        self.assertTrue(calls[-1][1].endswith('/deploy.yml/dispatches'))

    def test_default_domain_does_not_set_cname(self):
        api = Mock()
        api.request.side_effect = [{'id': 42, 'full_name': 'mamachanko/puzzles', 'private': False}, None, {}, None]
        finish_repository(api, Site('puzzles'), 42, {}, seed=Mock())
        self.assertFalse(any(call.args[0] == 'PUT' for call in api.request.call_args_list))

    def test_receipt_identity_mismatch_never_pushes(self):
        api = Mock()
        api.request.return_value = {'id': 43, 'full_name': 'mamachanko/puzzles', 'private': False}
        seed = Mock()
        with self.assertRaisesRegex(FactoryError, 'identity'):
            finish_repository(api, Site('puzzles'), 42, {}, seed=seed)
        seed.assert_not_called()

    def test_pages_domain_failure_never_dispatches(self):
        for response in (APIError('PUT', '/pages', 422), {'cname': None, 'build_type': 'workflow'}):
            api = Mock()
            api.request.side_effect = [{'id': 42, 'full_name': 'mamachanko/puzzles', 'private': False},
                                       None, {}, response] if isinstance(response, APIError) else [
                                           {'id': 42, 'full_name': 'mamachanko/puzzles', 'private': False}, None, {}, None, response]
            with self.assertRaises(FactoryError):
                finish_repository(api, Site('puzzles', domain='puzzles.mamachanko.com'), 42, {}, seed=Mock())
            self.assertFalse(any('dispatches' in call.args[1] for call in api.request.call_args_list))

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

    def test_git_seed_pushes_single_main_commit_without_credentials_in_remote(self):
        original_run = subprocess.run
        with tempfile.TemporaryDirectory() as directory:
            bare = Path(directory) / 'remote.git'
            original_run(['git', 'init', '--bare', str(bare)], check=True, capture_output=True)
            calls = []
            def run(command, **kwargs):
                calls.append((command, kwargs.get('env', {})))
                # Redirect the only remote to a local bare repo; no network calls.
                if command[:4] == ['git', 'remote', 'add', 'origin']:
                    command = [*command[:4], str(bare)]
                return original_run(command, **kwargs)
            with patch.dict(os.environ, {'GH_TOKEN': 'secret-test-token', 'GIT_TRACE': '1'}), patch('factory.subprocess.run', side_effect=run):
                seed_repository(Site('puzzles'), render(Site('puzzles')))
            count = original_run(['git', '--git-dir', str(bare), 'rev-list', '--count', 'main'], capture_output=True, text=True, check=True)
            self.assertEqual(count.stdout.strip(), '1')
            tree = original_run(['git', '--git-dir', str(bare), 'ls-tree', '-r', '--name-only', 'main'], capture_output=True, text=True, check=True)
            self.assertIn('.github/workflows/deploy.yml', tree.stdout)
            for command, env in calls:
                self.assertNotIn('secret-test-token', ' '.join(command))
                self.assertNotIn('GIT_TRACE', env)
                self.assertNotIn('--force', command)
            # A second attempt must refuse the populated remote.
            with patch('factory.subprocess.run', side_effect=run), self.assertRaisesRegex(FactoryError, 'no longer empty'):
                seed_repository(Site('puzzles'), render(Site('puzzles')))


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
        self.assertIn('Repository availability is not checked', output)
        self.assertIn('| CNAME | puzzles | mamachanko.github.io |', output)
        api.assert_not_called()
        run.assert_not_called()

    def test_invalid_input_fails_before_credentials(self):
        with patch('factory.GitHub') as api:
            result, output = self.run_cli(['create', '--state', '/unused'], {'REPOSITORY_NAME': '../oops'})
        self.assertEqual(result, 1)
        self.assertIn('Validation', output)
        api.assert_not_called()

    def test_create_receipt_contains_identity_without_credentials(self):
        with tempfile.TemporaryDirectory() as directory, patch('factory.GitHub') as github:
            path = Path(directory) / 'state.json'
            github.return_value.request.side_effect = [APIError('GET', '/repo', 404),
                {'id': 42, 'full_name': 'mamachanko/puzzles', 'private': False}]
            result, _ = self.run_cli(['create', '--state', str(path)], {'REPOSITORY_NAME': 'puzzles', 'GH_TOKEN': 'secret'})
            self.assertEqual(result, 0)
            self.assertEqual(json.loads(path.read_text())['repository_id'], 42)
            self.assertNotIn('secret', path.read_text())
            github.return_value.reset_mock()
            result, _ = self.run_cli(['create', '--state', str(path)], {'REPOSITORY_NAME': 'puzzles'})
            self.assertEqual(result, 1)
            github.return_value.request.assert_not_called()

    def test_mismatched_receipt_refuses_finish(self):
        with tempfile.TemporaryDirectory() as directory, patch('factory.GitHub') as github:
            path = Path(directory) / 'state.json'
            path.write_text(json.dumps({'site': {'name': 'other'}, 'repository_id': 42}))
            result, output = self.run_cli(['finish', '--state', str(path)], {'REPOSITORY_NAME': 'puzzles'})
            self.assertEqual(result, 1)
            self.assertIn('does not match', output)
            github.return_value.request.assert_not_called()

    def test_failure_is_nonzero_and_written_to_summary_without_secrets(self):
        with tempfile.TemporaryDirectory() as directory, patch('factory.GitHub') as github:
            summary = Path(directory) / 'summary.md'
            github.return_value.request.side_effect = APIError('GET', '/repos/mamachanko/puzzles', 403)
            result, output = self.run_cli(['create', '--state', str(Path(directory) / 'state.json')],
                {'REPOSITORY_NAME': 'puzzles', 'GITHUB_STEP_SUMMARY': str(summary), 'GH_TOKEN': 'secret'})
            self.assertEqual(result, 1)
            self.assertIn('HTTP 403', summary.read_text())
            self.assertIn('No automatic rollback', output)
            self.assertNotIn('secret', output)

    def test_create_http_failure_reports_only_safe_diagnostics(self):
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
                self.assert_create_http_failure(failure, category, request_id)

    def test_create_http_failure_rejects_unsafe_request_ids_and_preserves_unreadable_status(self):
        for request_id in ('secret-test-token', 'ABCD:123456:ABCDEF:123456:ABCDEF12\nsecret-test-token',
                           '<script>secret-test-token</script>', 'ABCD1234', 'A:B:C:D:E:F', 'A:' + 'B' * 200):
            with self.subTest(request_id=request_id):
                failure = urllib.error.HTTPError('https://api.github.com/user/repos', 403, 'secret-test-token',
                    {'X-GitHub-Request-Id': request_id}, io.BytesIO(b'{"message":"Rate Limit Exceeded"}'))
                self.assert_create_http_failure(failure, 'rate limited', None)
        unreadable = Mock()
        unreadable.read.side_effect = OSError('secret-test-token')
        failure = urllib.error.HTTPError('https://api.github.com/user/repos', 403, 'secret-test-token',
            {'X-RateLimit-Remaining': '0'}, unreadable)
        self.assert_create_http_failure(failure, 'rate limited', None)
        deeply_nested = io.BytesIO(b'[' * 16000 + b']' * 16000)
        request_id = 'CFF6:2A1BFD:91E587C:DB831B4:6AFEE42D'
        failure = urllib.error.HTTPError('https://api.github.com/user/repos', 403, 'secret-test-token',
            {'X-GitHub-Request-Id': request_id}, deeply_nested)
        self.assert_create_http_failure(failure, None, request_id)

    def assert_create_http_failure(self, failure, category, request_id):
        with tempfile.TemporaryDirectory() as directory, patch('factory.urllib.request.build_opener') as build_opener:
            opener = build_opener.return_value
            opener.open.side_effect = [urllib.error.HTTPError('https://api.github.com/repos/mamachanko/puzzles',
                404, 'secret-test-token', {}, io.BytesIO(b'{}')), failure]
            summary = Path(directory) / 'summary.md'
            result, output = self.run_cli(['create', '--state', str(Path(directory) / 'state.json')],
                {'REPOSITORY_NAME': 'puzzles', 'GITHUB_STEP_SUMMARY': str(summary), 'GH_TOKEN': 'secret-test-token'})
            self.assertEqual(result, 1)
            self.assertEqual(opener.open.call_count, 2)
            self.assertEqual([call.args[0].method for call in opener.open.call_args_list], ['GET', 'POST'])
            self.assertEqual(opener.open.call_args.args[0].full_url, 'https://api.github.com/user/repos')
            for report in (output, summary.read_text()):
                self.assertIn(f'GitHub POST /user/repos failed (HTTP {failure.code}).', report)
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


if __name__ == '__main__':
    unittest.main()
