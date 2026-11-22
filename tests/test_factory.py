from copy import deepcopy
from email.message import Message
import json
from pathlib import Path
import io
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from factory import (APIError, FactoryError, GitHub, Site, furnish, main, page_responds,
                     INTEGRITY_RULESET_NAME, REPOSITORY_DEFAULTS, RULESET_NAME, WORKFLOW_PERMISSIONS,
                     compatible_ruleset, ruleset_payload, seed_repository, starter_files, validate_domain)


SITE = Site('my-site')
SITE_URL = f'https://mamachanko.github.io/{SITE.name}/'
REPO = f'/repos/{SITE.repository}'
REPO_URL = f'https://github.com/{SITE.repository}'
WORKFLOW = '.github/workflows/deploy.yml'
WORKFLOW_URL = f'{REPO_URL}/actions/runs/7'
SHA = 'a' * 40
STARTER_FILES = {
    WORKFLOW: 'trusted deploy\n', '.github/workflows/renovate.yml': 'trusted renovate\n',
    '.github/actions/check-site/action.yml': 'trusted action\n',
    'renovate.json': '{}\n', 'README.md': 'Starter readme\n', 'AGENTS.md': 'Starter guidance\n',
    'site/index.html': '<h1>Starter</h1>\n',
}


class FurnishTests(unittest.TestCase):
    def setUp(self):
        self.repo = {
            'id': 42, 'full_name': SITE.repository, 'private': False,
            'visibility': 'public', 'archived': False, 'disabled': False,
            'default_branch': 'main',
            'owner': {'login': 'mamachanko', 'type': 'User'},
        }
        self.installation = {'total_count': 1, 'repositories': [{'id': 42, 'full_name': SITE.repository}]}
        self.pages = None
        self.rule = None
        self.integrity_rule = None
        self.other_rules = []
        self.permissions = {'default_workflow_permissions': 'write', 'can_approve_pull_request_reviews': False}
        self.ignore_settings = False
        self.ignore_permissions = False
        self.corrupt_ruleset_readback = False
        self.conclusion = 'success'
        self.deployment_sha = SHA
        self.default_branch_update_fails = False
        self.seed = Mock(return_value=SHA)
        self.live = Mock(return_value=True)
        self.api = Mock()
        self.api.request.side_effect = self.request
        starter_patch = patch('factory.starter_files', return_value=STARTER_FILES)
        starter_patch.start()
        self.addCleanup(starter_patch.stop)

    def request(self, method, path, payload=None):
        if method == 'GET' and path == '/installation/repositories?per_page=2':
            return deepcopy(self.installation)
        path = path.partition('?')[0]
        if method == 'GET' and path == REPO:
            return deepcopy(self.repo)
        if method == 'PATCH' and path == REPO:
            self.assertTrue(payload)
            self.assertTrue(set(payload) <= REPOSITORY_DEFAULTS.keys())
            if self.default_branch_update_fails:
                raise APIError(method, path, 500)
            if not self.ignore_settings:
                self.repo.update(payload)
            return self.repo
        if method == 'GET' and path == REPO + '/actions/permissions/workflow':
            return deepcopy(self.permissions)
        if method == 'PUT' and path == REPO + '/actions/permissions/workflow':
            self.assertEqual(payload, WORKFLOW_PERMISSIONS)
            if not self.ignore_permissions:
                self.permissions.update(payload)
            return None
        if method == 'GET' and path == REPO + '/pages':
            if self.pages is None:
                raise APIError(method, path, 404)
            return self.pages
        if method == 'POST' and path == REPO + '/pages':
            self.assertEqual(payload, {'build_type': 'workflow'})
            self.pages = {**payload, 'html_url': SITE_URL, 'cname': None, 'public': True, 'status': 'built'}
            return self.pages
        if method == 'GET' and path == REPO + '/rulesets':
            return [deepcopy(rule) for rule in [self.rule, self.integrity_rule, *self.other_rules] if rule]
        if method == 'POST' and path == REPO + '/rulesets':
            rule = {**deepcopy(payload), 'id': 9 if payload['name'] == RULESET_NAME else 10}
            if payload['name'] == RULESET_NAME:
                self.rule = rule
            else:
                self.integrity_rule = rule
            return deepcopy(rule)
        if method == 'GET' and path in (REPO + '/rulesets/9', REPO + '/rulesets/10'):
            rule = deepcopy(self.rule if path.endswith('/9') else self.integrity_rule)
            if self.corrupt_ruleset_readback:
                rule['enforcement'] = 'disabled'
            return rule
        if method == 'GET' and path == REPO + '/actions/workflows/deploy.yml':
            return {'path': WORKFLOW, 'state': 'active'}
        if method == 'POST' and path == REPO + '/actions/workflows/deploy.yml/dispatches':
            self.assertIsNotNone(self.pages)
            self.assertIsNotNone(self.integrity_rule)
            self.assertEqual(payload, {'ref': 'main'})
            return {'workflow_run_id': 7, 'html_url': WORKFLOW_URL}
        if method == 'GET' and path == REPO + '/actions/runs/7':
            return {
                'id': 7, 'path': WORKFLOW, 'status': 'completed', 'conclusion': self.conclusion,
                'head_sha': self.deployment_sha, 'head_branch': 'main', 'event': 'workflow_dispatch',
                'html_url': WORKFLOW_URL,
            }
        self.fail(f'Unexpected GitHub request {method} {path}')

    def run_furnish(self):
        return furnish(self.api, SITE, token='unused-test-token', seed=self.seed,
                       sleep=Mock(), live=self.live, progress=Mock())

    def test_configures_existing_repository_and_checks_publication(self):
        result = self.run_furnish()
        self.assertEqual(result, (SITE_URL, WORKFLOW_URL))
        self.assertEqual(self.rule['target'], 'branch')
        self.assertEqual(self.rule['enforcement'], 'active')
        self.assertEqual(self.rule['conditions']['ref_name']['include'], ['refs/heads/main'])
        self.assertEqual(self.rule['bypass_actors'],
                         [{'actor_id': 5, 'actor_type': 'RepositoryRole', 'bypass_mode': 'always'}])
        rules = {rule['type']: rule for rule in self.rule['rules']}
        self.assertEqual(set(rules), {'pull_request', 'required_status_checks'})
        self.assertEqual(rules['pull_request']['parameters']['required_approving_review_count'], 0)
        self.assertEqual(rules['pull_request']['parameters']['allowed_merge_methods'], ['rebase'])
        self.assertEqual(rules['required_status_checks']['parameters'], {
            'required_status_checks': [{'context': 'Check site', 'integration_id': 15368}],
            'strict_required_status_checks_policy': False, 'do_not_enforce_on_create': False})
        self.assertEqual(self.integrity_rule['bypass_actors'], [])
        self.assertEqual({rule['type'] for rule in self.integrity_rule['rules']},
                         {'deletion', 'non_fast_forward', 'required_linear_history'})
        self.assertEqual(self.seed.call_args.args[1], STARTER_FILES)
        self.assertEqual({key: self.repo[key] for key in REPOSITORY_DEFAULTS}, REPOSITORY_DEFAULTS)
        self.assertEqual(self.permissions, WORKFLOW_PERMISSIONS)
        self.live.assert_called_once_with(SITE_URL)

    def test_rerun_reuses_pages_and_ruleset(self):
        self.run_furnish()
        self.api.reset_mock()
        self.run_furnish()
        writes = [(method, path) for method, path, *_ in
                  [call.args for call in self.api.request.call_args_list] if method != 'GET']
        self.assertEqual(writes, [('POST', REPO + '/actions/workflows/deploy.yml/dispatches')])

    def test_reuses_compatible_rulesets_and_preserves_unrelated_settings_and_rules(self):
        self.rule = {**ruleset_payload(), 'id': 9}
        self.integrity_rule = {**ruleset_payload(INTEGRITY_RULESET_NAME), 'id': 10}
        self.other_rules = [{'id': 50, 'name': 'owner-policy', 'rules': [{'type': 'creation'}]}]
        self.repo.update(REPOSITORY_DEFAULTS, description='Owner description', homepage='https://example.com')
        self.repo['has_issues'] = False
        self.run_furnish()
        patches = [call.args[2] for call in self.api.request.call_args_list if call.args[0] == 'PATCH']
        self.assertEqual(patches, [{'has_issues': True}])
        self.assertEqual(self.repo['description'], 'Owner description')
        self.assertEqual(self.other_rules, [{'id': 50, 'name': 'owner-policy', 'rules': [{'type': 'creation'}]}])
        self.assertFalse(any(call.args[:2] == ('POST', REPO + '/rulesets') for call in self.api.request.call_args_list))

    def test_legacy_managed_ruleset_is_rejected_before_any_mutation(self):
        legacy = ruleset_payload()
        legacy['bypass_actors'] = []
        legacy['rules'] = [{'type': 'deletion'}, {'type': 'non_fast_forward'},
                           deepcopy(legacy['rules'][0])]
        legacy['rules'][2]['parameters']['allowed_merge_methods'] = ['merge', 'squash', 'rebase']
        self.rule = {**legacy, 'id': 9}
        with self.assertRaisesRegex(FactoryError, 'site-factory-main ruleset is incompatible'):
            self.run_furnish()
        self.seed.assert_not_called()
        self.assertTrue(all(call.args[0] == 'GET' for call in self.api.request.call_args_list))

    def test_incompatible_integrity_ruleset_stops_before_seed(self):
        self.integrity_rule = {**ruleset_payload(INTEGRITY_RULESET_NAME), 'id': 10, 'bypass_actors': [
            {'actor_id': 5, 'actor_type': 'RepositoryRole', 'bypass_mode': 'always'}]}
        with self.assertRaisesRegex(FactoryError, 'integrity ruleset is incompatible'):
            self.run_furnish()
        self.seed.assert_not_called()
        self.assertTrue(all(call.args[0] == 'GET' for call in self.api.request.call_args_list))

    def test_required_check_installed_only_after_verified_success_and_read_back(self):
        self.run_furnish()
        calls = [call.args for call in self.api.request.call_args_list]
        run_index = calls.index(('GET', REPO + '/actions/runs/7'))
        main_index = next(index for index, call in enumerate(calls)
                          if call[:2] == ('POST', REPO + '/rulesets') and call[2]['name'] == RULESET_NAME)
        self.assertLess(run_index, main_index)
        self.assertEqual(calls[main_index + 1], ('GET', REPO + '/rulesets/9'))

    def test_failed_bootstrap_retry_finishes_rules_after_success(self):
        self.conclusion = 'failure'
        with self.assertRaisesRegex(FactoryError, 'Deployment failed'):
            self.run_furnish()
        self.assertIsNone(self.rule)
        self.assertIsNotNone(self.integrity_rule)
        self.conclusion = 'success'
        self.api.reset_mock()
        self.run_furnish()
        writes = [call.args for call in self.api.request.call_args_list if call.args[0] != 'GET']
        self.assertEqual([call[:2] for call in writes], [
            ('POST', REPO + '/actions/workflows/deploy.yml/dispatches'), ('POST', REPO + '/rulesets')])
        self.assertEqual(writes[-1][2]['name'], RULESET_NAME)

    def assert_unconfirmed_stops_before_dispatch(self, expected):
        with self.assertRaisesRegex(FactoryError, expected):
            self.run_furnish()
        self.live.assert_not_called()
        self.assertFalse(any(call.args[:2] == ('POST', REPO + '/actions/workflows/deploy.yml/dispatches')
                             for call in self.api.request.call_args_list))

    def test_unconfirmed_repository_settings_stop_before_dispatch(self):
        self.ignore_settings = True
        self.assert_unconfirmed_stops_before_dispatch('Repository defaults')

    def test_unconfirmed_permissions_stop_before_dispatch(self):
        self.ignore_permissions = True
        self.assert_unconfirmed_stops_before_dispatch('Workflow token permissions')

    def test_unconfirmed_integrity_rules_stop_before_dispatch(self):
        self.corrupt_ruleset_readback = True
        self.assert_unconfirmed_stops_before_dispatch('ruleset was not confirmed')

    def test_rerun_after_failed_default_branch_update(self):
        self.repo['default_branch'] = 'master'
        self.default_branch_update_fails = True
        with self.assertRaises(APIError):
            self.run_furnish()
        self.assertIsNone(self.pages)

        self.default_branch_update_fails = False
        self.assertEqual(self.run_furnish(), (SITE_URL, WORKFLOW_URL))
        self.assertTrue(self.seed.call_args.kwargs['require_main_only'])
        self.assertEqual(self.repo['default_branch'], 'main')

    def test_conflicting_pages_or_ruleset_stops_before_seed(self):
        for pages, rule in (({'build_type': 'legacy'}, None),
                            (None, {**ruleset_payload(), 'id': 9, 'enforcement': 'disabled'})):
            with self.subTest(pages=pages, rule=rule):
                self.pages, self.rule = pages, rule
                self.api.reset_mock()
                with self.assertRaises(FactoryError):
                    self.run_furnish()
                self.seed.assert_not_called()
                self.assertTrue(all(call.args[0] == 'GET' for call in self.api.request.call_args_list))

    def test_token_scope_must_bind_exactly_one_requested_repository(self):
        invalid = [None, {}, {'total_count': 0, 'repositories': []},
                   {'total_count': 2, 'repositories': self.installation['repositories']},
                   {'total_count': True, 'repositories': self.installation['repositories']},
                   {'total_count': 1, 'repositories': []},
                   {'total_count': 1, 'repositories': [None]},
                   {'total_count': 1, 'repositories': [{'full_name': 'mamachanko/other', 'id': 42}]},
                   {'total_count': 1, 'repositories': [{'full_name': SITE.repository, 'id': True}]},
                   {'total_count': 1, 'repositories': [{'full_name': SITE.repository, 'id': 0}]},
                   {'total_count': 1, 'repositories': [{'full_name': SITE.repository, 'id': '42'}]},
                   {'total_count': 1, 'repositories': [{'full_name': SITE.repository, 'id': 43}]}]
        for installation in invalid:
            with self.subTest(installation=installation):
                self.installation = installation
                self.api.reset_mock()
                with self.assertRaises(FactoryError):
                    self.run_furnish()
                self.seed.assert_not_called()
                self.assertTrue(all(call.args[0] == 'GET' for call in self.api.request.call_args_list))

    def test_target_identity_and_active_public_owner_are_required(self):
        original = deepcopy(self.repo)
        for changes in ({'full_name': 'mamachanko/other'}, {'id': True}, {'id': 43},
                        {'owner': {'login': 'someone', 'type': 'User'}},
                        {'owner': {'login': 'mamachanko', 'type': 'Organization'}},
                        {'private': True}, {'archived': True}, {'disabled': True}):
            with self.subTest(changes=changes):
                self.repo = {**original, **changes}
                self.api.reset_mock()
                with self.assertRaises(FactoryError):
                    self.run_furnish()
                self.seed.assert_not_called()
                self.assertTrue(all(call.args[0] == 'GET' for call in self.api.request.call_args_list))

    def test_identity_is_checked_again_before_every_api_write(self):
        self.run_furnish()
        calls = [call.args for call in self.api.request.call_args_list]
        for index, (method, *_rest) in enumerate(calls):
            if method != 'GET':
                self.assertEqual(calls[index - 1], ('GET', REPO))
        self.assertEqual(calls[0], ('GET', '/installation/repositories?per_page=2'))
        self.assertNotIn(('GET', '/user'), calls)

    def test_identity_change_during_git_preparation_prevents_push(self):
        def changed_repository(*args, **kwargs):
            self.repo['id'] = 43
            kwargs['check']()
            self.fail('Changed repository must not pass the Git pre-push check')
        self.seed.side_effect = changed_repository
        with self.assertRaises(FactoryError):
            self.run_furnish()
        self.assertTrue(all(call.args[0] == 'GET' for call in self.api.request.call_args_list))

    def test_private_repo_is_rejected_before_seed(self):
        self.repo['private'] = True
        self.repo['visibility'] = 'private'
        with self.assertRaises(FactoryError):
            self.run_furnish()
        self.seed.assert_not_called()

    def test_existing_custom_pages_url_is_verified(self):
        url = 'https://maxbrauer.com/my-site/'
        self.pages = {'build_type': 'workflow', 'html_url': url, 'cname': None}
        result = self.run_furnish()
        self.assertEqual(result, (url, WORKFLOW_URL))
        self.live.assert_called_once_with(url)

    def test_successful_workflow_with_unreachable_page_fails(self):
        self.live.return_value = False
        with self.assertRaisesRegex(FactoryError, 'not live'):
            self.run_furnish()

    def test_failed_deployment_never_reports_a_live_url(self):
        self.conclusion = 'failure'
        with self.assertRaisesRegex(FactoryError, 'Deployment failed'):
            self.run_furnish()
        self.live.assert_not_called()

    def test_wrong_deployment_sha_never_reports_a_live_url(self):
        self.deployment_sha = 'b' * 40
        with self.assertRaisesRegex(FactoryError, 'Deployment run identity changed'):
            self.run_furnish()
        self.live.assert_not_called()

    def test_off_allowlist_redirect_is_rejected_before_fetching_its_target(self):
        opener = Mock()
        opener.open.side_effect = urllib.error.HTTPError(
            SITE_URL, 302, 'Found', {'Location': 'https://example.org/'}, None)
        with patch('factory.urllib.request.build_opener', return_value=opener):
            with self.assertRaises(FactoryError):
                page_responds(SITE_URL)
        opener.open.assert_called_once()
        self.assertEqual(opener.open.call_args.args[0].full_url, SITE_URL)


class RunnerCommandTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name) / 'output'
        self.summary = Path(temporary.name) / 'summary'
        self.environment = {'REPOSITORY_NAME': SITE.name, 'GITHUB_OUTPUT': str(self.output),
                            'GITHUB_STEP_SUMMARY': str(self.summary), 'GH_TOKEN': 'secret-test-token'}

    def run_command(self, command, environment=None):
        env = {**os.environ, **self.environment, 'GH_TOKEN': ''}
        if environment:
            env.update(environment)
        return subprocess.run([sys.executable, str(ROOT / 'scripts/factory.py'), command],
                              env=env, capture_output=True, text=True)

    def test_script_validation_works_without_credentials(self):
        result = self.run_command('validate')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.output.read_text(), 'repository_name=my-site\n')
        self.assertFalse(self.summary.exists())

    def test_script_furnish_without_token_fails_without_success_summary(self):
        result = self.run_command('furnish')
        self.assertEqual(result.returncode, 1)
        self.assertIn('GH_TOKEN is required', result.stderr)
        self.assertFalse(self.summary.exists())
        self.assertNotIn('Live:', result.stdout)

    def test_retired_commands_are_not_available(self):
        for command in ('plan', 'create', 'finish'):
            with self.subTest(command=command):
                result = self.run_command(command)
                self.assertEqual(result.returncode, 2)
                self.assertIn('invalid choice', result.stderr)
                self.assertFalse(self.output.exists())
                self.assertFalse(self.summary.exists())

    def test_validation_exports_only_the_canonical_name_without_authentication(self):
        with patch.dict(os.environ, self.environment, clear=True), patch('factory.GitHub') as api:
            self.assertEqual(main(['validate']), 0)
        self.assertEqual(self.output.read_text(), 'repository_name=my-site\n')
        self.assertFalse(self.summary.exists())
        api.assert_not_called()

    def test_invalid_input_never_produces_action_output_or_requests_credentials(self):
        for value in ('site,other', 'site\nrepository_name=other', SITE.repository, REPO_URL, ''):
            with self.subTest(value=value), patch.dict(os.environ, {**self.environment, 'REPOSITORY_NAME': value}, clear=True), \
                    patch('factory.GitHub') as api, patch('sys.stderr', new_callable=io.StringIO):
                self.assertEqual(main(['validate']), 1)
                self.assertFalse(self.output.exists())
                api.assert_not_called()

    def test_furnish_uses_environment_app_token_and_reports_verified_result(self):
        result = (SITE_URL, WORKFLOW_URL)
        with patch.dict(os.environ, self.environment, clear=True), patch('factory.furnish', return_value=result) as run, \
                patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(main(['furnish']), 0)
        self.assertEqual(run.call_args.args[0].token, 'secret-test-token')
        self.assertEqual(run.call_args.args[2], 'secret-test-token')
        self.assertEqual(self.summary.read_text(), f'Repository: {REPO_URL}\n\nLive: {SITE_URL}\n')
        self.assertNotIn('secret-test-token', output.getvalue() + self.summary.read_text())

    def test_failure_and_missing_token_never_report_success_links(self):
        for token in ('secret-test-token', ''):
            with self.subTest(token=token), patch.dict(os.environ, {**self.environment, 'GH_TOKEN': token}, clear=True), \
                    patch('factory.furnish', side_effect=FactoryError('Deployment failed')), \
                    patch('sys.stderr', new_callable=io.StringIO) as output:
                self.assertEqual(main(['furnish']), 1)
                self.assertFalse(self.summary.exists())
                self.assertNotIn('secret-test-token', output.getvalue())


class SeedTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.remote = Path(temporary.name) / 'remote.git'
        self.git('init', '--bare', '--initial-branch=main', str(self.remote), repository=False)
        self.files = {WORKFLOW: 'deployment workflow\n', 'site/index.html': '<h1>Starter</h1>\n'}

    def git(self, *args, repository=True):
        command = ['git', '--git-dir', str(self.remote)] if repository else ['git']
        return subprocess.run([*command, *args], check=True, capture_output=True, text=True).stdout

    def seed(self, files):
        return seed_repository(SITE, files, '', remote=str(self.remote))

    def test_git_furnishing_sanitizes_credentials_and_inherited_configuration(self):
        original_run = subprocess.run
        calls = []
        def run(command, **kwargs):
            calls.append((command, kwargs.get('env', {})))
            return original_run(command, **kwargs)
        with patch.dict(os.environ, {'GH_TOKEN': 'unrelated-token', 'GH_DEBUG': 'api', 'GIT_TRACE': '1',
                                     'GITHUB_TOKEN': 'unrelated-token'}), \
                patch('factory.subprocess.run', side_effect=run):
            seed_repository(SITE, self.files, 'secret-test-token', remote=str(self.remote))
        for command, env in calls:
            self.assertNotIn('secret-test-token', ' '.join(command))
            self.assertNotIn('unrelated-token', ' '.join(command))
            self.assertNotIn('--force', command)
            self.assertNotIn('GIT_TRACE', env)
            self.assertNotIn('GH_DEBUG', env)
            self.assertNotIn('GITHUB_TOKEN', env)
            self.assertEqual(env['GH_TOKEN'], 'secret-test-token')
            self.assertIn('core.hooksPath=/dev/null', command)
            self.assertIn('http.followRedirects=false', command)

    def test_empty_repository_gets_two_files_once(self):
        original = self.seed(self.files)
        self.assertEqual(self.git('ls-tree', '-r', '--name-only', 'main').splitlines(), sorted(self.files))
        self.assertEqual(self.seed(self.files), original)
        self.assertEqual(self.git('rev-list', '--count', 'main').strip(), '1')

    def test_seed_refuses_to_replace_a_populated_alternate_default(self):
        before = self.seed({'README.md': 'Keep\n'})
        self.git('branch', 'master', before)
        self.git('symbolic-ref', 'HEAD', 'refs/heads/master')
        with self.assertRaises(FactoryError):
            seed_repository(SITE, self.files, '', remote=str(self.remote), require_main_only=True)
        self.assertEqual(self.git('rev-parse', 'main').strip(), before)

    def test_preserves_existing_content_and_rejects_conflicting_workflow(self):
        before = self.seed({'README.md': 'Keep\n', 'site/index.html': '<h1>Existing</h1>\n'})
        after = self.seed(self.files)
        self.assertEqual(self.git('rev-parse', f'{after}^').strip(), before)
        self.assertEqual(self.git('diff', '--name-only', before, after).splitlines(), [WORKFLOW])
        self.assertEqual(self.git('show', 'main:site/index.html'), '<h1>Existing</h1>\n')
        with self.assertRaises(FactoryError):
            self.seed({WORKFLOW: 'different workflow\n'})
        self.assertEqual(self.git('rev-parse', 'main').strip(), after)

    def test_preserves_owner_documents_site_and_unmanaged_github_files(self):
        owner_files = {'README.md': 'Owner readme\n', 'AGENTS.md': 'Owner instructions\n',
                       'site/index.html': 'Owner website\n', 'site/style.css': 'body {}\n',
                       '.github/CODEOWNERS': '* @mamachanko\n',
                       '.github/ISSUE_TEMPLATE/bug.md': 'Owner bug template\n'}
        before = self.seed(owner_files)
        after = self.seed(STARTER_FILES)
        self.assertNotEqual(before, after)
        for path, content in owner_files.items():
            self.assertEqual(self.git('show', 'main:' + path), content)
        for path, content in STARTER_FILES.items():
            if path not in owner_files:
                self.assertEqual(self.git('show', 'main:' + path), content)
        self.assertEqual(self.seed(STARTER_FILES), after)

    def test_rejects_every_changed_managed_automation_before_push_or_callback(self):
        for path in (WORKFLOW, '.github/workflows/renovate.yml',
                     '.github/actions/check-site/action.yml', 'renovate.json'):
            with self.subTest(path=path):
                before = self.seed(STARTER_FILES)
                callback = Mock()
                with self.assertRaisesRegex(FactoryError, 'refusing to overwrite or dispatch'):
                    seed_repository(SITE, {**STARTER_FILES, path: 'unrecognized automation\n'}, '',
                                    remote=str(self.remote), check=callback)
                callback.assert_not_called()
                self.assertEqual(self.git('rev-parse', 'main').strip(), before)

    def test_unknown_old_deployment_workflow_is_never_retrofitted(self):
        before = self.seed({WORKFLOW: 'old furnished site-test workflow\n', 'site/index.html': 'Keep\n'})
        with self.assertRaisesRegex(FactoryError, 'Existing .github/workflows/deploy.yml is unknown'):
            self.seed(STARTER_FILES)
        self.assertEqual(self.git('rev-parse', 'main').strip(), before)
        self.assertEqual(self.git('ls-tree', '-r', '--name-only', 'main').splitlines(), [WORKFLOW, 'site/index.html'])

    def test_rejects_unsafe_paths_before_git_or_remote_access(self):
        for path in ('../outside', '/absolute', 'site/../../outside', 'site//index.html', './README.md',
                     '.git/config', 'site/.GiT/config', 'site\\index.html', 'bad\nname', 'bad\x00name'):
            with self.subTest(path=path), patch('factory.subprocess.run') as run:
                with self.assertRaisesRegex(FactoryError, 'safe relative'):
                    self.seed({path: 'unsafe'})
                run.assert_not_called()

    def test_regular_file_and_directory_collisions_block_seed(self):
        before = self.seed({'site': 'blocking file\n', 'folder/nested': 'nested\n'})
        with self.assertRaisesRegex(FactoryError, 'file or symlink blocks'):
            self.seed(STARTER_FILES)
        self.assertEqual(self.git('rev-parse', 'main').strip(), before)
        with self.assertRaisesRegex(FactoryError, 'directory blocks'):
            self.seed({'folder': 'blocked\n'})
        self.assertEqual(self.git('rev-parse', 'main').strip(), before)


class StarterFileTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.templates = self.root / 'templates'
        for path, content in STARTER_FILES.items():
            file = self.templates / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(content)
        root_patch = patch('factory.ROOT', self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)

    def test_renders_complete_mirror_and_replaces_both_tokens(self):
        (self.templates / 'README.md').write_text('__SITE_NAME__ __SITE_URL__ __UNKNOWN__\n')
        files = starter_files(SITE)
        self.assertEqual(files.keys(), STARTER_FILES.keys())
        self.assertEqual(files['README.md'], f'my-site {SITE_URL} __UNKNOWN__\n')
        self.assertEqual(files[WORKFLOW], STARTER_FILES[WORKFLOW])

    def test_replacement_is_one_pass(self):
        (self.templates / 'README.md').write_text('__SITE_NAME__ __SITE_URL__')
        site = Mock(name='unused')
        site.name = '__SITE_URL__'
        self.assertEqual(starter_files(site)['README.md'],
                         '__SITE_URL__ https://mamachanko.github.io/__SITE_URL__/')

    def test_rejects_symlinks_and_git_internal_paths(self):
        for path in ('linked', '.git/config'):
            with self.subTest(path=path):
                file = self.templates / path
                file.parent.mkdir(parents=True, exist_ok=True)
                file.symlink_to('/etc/passwd')
                with self.assertRaises(FactoryError):
                    starter_files(SITE)
                file.unlink()
                if path.startswith('.git/'):
                    file.parent.rmdir()


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
        for domain in ('mamachanko.com', 'maxbrauer.com', 'puzzles.mamachanko.com',
                       'word.games.maxbrauer.com', '1-a.maxbrauer.com'):
            with self.subTest(domain=domain):
                validate_domain(domain)

    def test_invalid_domains(self):
        for domain in ('', 'evil.com', 'evilmamachanko.com', 'mamachanko.com.evil.com',
                       'https://puzzles.mamachanko.com', 'puzzles.mamachanko.com/path',
                       'puzzles.mamachanko.com:443', '*.mamachanko.com', 'puzzles.mamachanko.com.',
                       'Puzzles.mamachanko.com', 'a..mamachanko.com', '-a.mamachanko.com',
                       'a-.mamachanko.com', 'a_b.mamachanko.com', 'a' * 64 + '.mamachanko.com',
                       'a@mamachanko.com', 'mamachanko.com\n', 'é.maxbrauer.com'):
            with self.subTest(domain=domain), self.assertRaises(FactoryError):
                validate_domain(domain)


class GitHubTests(unittest.TestCase):
    def test_http_errors_never_echo_response_bodies_or_tokens(self):
        with patch.dict(os.environ, {'GH_TOKEN': 'secret-test-token'}, clear=True):
            api = GitHub()
            api.opener = Mock()
            api.opener.open.side_effect = urllib.error.HTTPError('https://api.github.com/installation/repositories?per_page=2', 403,
                'secret-test-token', {}, io.BytesIO(b'secret-test-token'))
            with self.assertRaises(APIError) as caught:
                api.request('GET', '/installation/repositories?per_page=2')
            self.assertNotIn('secret-test-token', str(caught.exception))
            request = api.opener.open.call_args.args[0]
            self.assertEqual(request.full_url, 'https://api.github.com/installation/repositories?per_page=2')
            self.assertEqual(request.get_header('X-github-api-version'), '2026-03-10')

    def test_furnish_http_failure_reports_only_safe_diagnostics(self):
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
                failure = urllib.error.HTTPError('https://api.github.com/installation/repositories?per_page=2', status,
                    'secret-test-token', response_headers, io.BytesIO(body))
                self.assert_furnish_http_failure(failure, category, request_id)

    def test_furnish_http_failure_rejects_unsafe_request_ids_and_preserves_unreadable_status(self):
        for request_id in ('secret-test-token', 'ABCD:123456:ABCDEF:123456:ABCDEF12\nsecret-test-token',
                           '<script>secret-test-token</script>', 'ABCD1234', 'A:B:C:D:E:F', 'A:' + 'B' * 200):
            with self.subTest(request_id=request_id):
                failure = urllib.error.HTTPError('https://api.github.com/installation/repositories?per_page=2', 403, 'secret-test-token',
                    {'X-GitHub-Request-Id': request_id}, io.BytesIO(b'{"message":"Rate Limit Exceeded"}'))
                self.assert_furnish_http_failure(failure, 'rate limited', None)
        unreadable = Mock()
        unreadable.read.side_effect = OSError('secret-test-token')
        failure = urllib.error.HTTPError('https://api.github.com/installation/repositories?per_page=2', 403, 'secret-test-token',
            {'X-RateLimit-Remaining': '0'}, unreadable)
        self.assert_furnish_http_failure(failure, 'rate limited', None)
        deeply_nested = io.BytesIO(b'[' * 16000 + b']' * 16000)
        request_id = 'CFF6:2A1BFD:91E587C:DB831B4:6AFEE42D'
        failure = urllib.error.HTTPError('https://api.github.com/installation/repositories?per_page=2', 403, 'secret-test-token',
            {'X-GitHub-Request-Id': request_id}, deeply_nested)
        self.assert_furnish_http_failure(failure, None, request_id)

    def assert_furnish_http_failure(self, failure, category, request_id):
        with patch.dict(os.environ, {'GH_TOKEN': 'secret-test-token'}, clear=True):
            api = GitHub()
        api.opener = Mock()
        api.opener.open.side_effect = failure
        with self.assertRaises(APIError) as caught:
            api.request('GET', '/installation/repositories?per_page=2')
        api.request = Mock(side_effect=caught.exception)
        with tempfile.TemporaryDirectory() as directory:
            summary = Path(directory) / 'summary.md'
            with patch.dict(os.environ, {'REPOSITORY_NAME': SITE.name, 'GH_TOKEN': 'secret-test-token',
                                         'GITHUB_STEP_SUMMARY': str(summary)}, clear=True), \
                    patch('factory.GitHub', return_value=api), \
                    patch('sys.stderr', new_callable=io.StringIO) as output:
                self.assertEqual(main(['furnish']), 1)
            self.assertFalse(summary.exists())
        self.assertEqual(api.opener.open.call_args.args[0].method, 'GET')
        self.assertEqual(api.opener.open.call_args.args[0].full_url,
                         'https://api.github.com/installation/repositories?per_page=2')
        for report in (str(caught.exception), output.getvalue()):
            self.assertIn(f'GitHub GET /installation/repositories?per_page=2 failed (HTTP {failure.code}).', report)
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
