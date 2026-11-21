from copy import deepcopy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from controller import furnish, parse_repository, ruleset_payload, seed_repository
from factory import APIError, FactoryError


SITE = parse_repository('my-site')
REPO = f'/repos/{SITE.repository}'
REPO_URL = f'https://github.com/{SITE.repository}'
WORKFLOW = '.github/workflows/deploy.yml'
WORKFLOW_URL = f'{REPO_URL}/actions/runs/7'
SHA = 'a' * 40


class FurnishTests(unittest.TestCase):
    def setUp(self):
        self.repo = {
            'id': 42, 'full_name': SITE.repository, 'private': False,
            'visibility': 'public', 'archived': False, 'disabled': False,
            'default_branch': 'main', 'permissions': {'admin': True},
            'owner': {'login': 'mamachanko', 'type': 'User'},
        }
        self.pages = None
        self.rule = None
        self.conclusion = 'success'
        self.default_branch_update_fails = False
        self.seed = Mock(return_value=SHA)
        self.live = Mock(return_value=True)
        self.api = Mock()
        self.api.request.side_effect = self.request

    def request(self, method, path, payload=None):
        path = path.partition('?')[0]
        if method == 'GET' and path == '/user':
            return {'login': 'mamachanko', 'type': 'User'}
        if method == 'GET' and path == REPO:
            return deepcopy(self.repo)
        if method == 'PATCH' and path == REPO:
            self.assertEqual(payload, {'default_branch': 'main'})
            if self.default_branch_update_fails:
                raise APIError(method, path, 500)
            self.repo.update(payload)
            return self.repo
        if method == 'GET' and path == REPO + '/pages':
            if self.pages is None:
                raise APIError(method, path, 404)
            return self.pages
        if method == 'POST' and path == REPO + '/pages':
            self.assertEqual(payload, {'build_type': 'workflow'})
            self.pages = {**payload, 'html_url': SITE.url, 'cname': None, 'public': True, 'status': 'built'}
            return self.pages
        if method == 'GET' and path == REPO + '/rulesets':
            return [{'name': self.rule['name'], 'id': 9}] if self.rule else []
        if method == 'POST' and path == REPO + '/rulesets':
            self.rule = {**payload, 'id': 9}
            return self.rule
        if method == 'GET' and path == REPO + '/rulesets/9':
            return self.rule
        if method == 'GET' and path == REPO + '/actions/workflows/deploy.yml':
            return {'path': WORKFLOW, 'state': 'active'}
        if method == 'POST' and path == REPO + '/actions/workflows/deploy.yml/dispatches':
            self.assertIsNotNone(self.pages)
            self.assertIsNotNone(self.rule)
            self.assertEqual(payload, {'ref': 'main'})
            return {'workflow_run_id': 7, 'html_url': WORKFLOW_URL}
        if method == 'GET' and path == REPO + '/actions/runs/7':
            return {
                'id': 7, 'path': WORKFLOW, 'status': 'completed', 'conclusion': self.conclusion,
                'head_sha': SHA, 'head_branch': 'main', 'event': 'workflow_dispatch',
                'html_url': WORKFLOW_URL,
            }
        self.fail(f'Unexpected GitHub request {method} {path}')

    def run_furnish(self):
        return furnish(self.api, SITE, token='unused-test-token', seed=self.seed,
                       sleep=Mock(), live=self.live, progress=Mock())

    def test_configures_existing_repository_and_checks_publication(self):
        result = self.run_furnish()
        self.assertEqual(result['repository'], SITE.repository)
        self.assertEqual(result['url'], SITE.url)
        self.assertEqual(result['run_id'], 7)
        self.assertEqual(self.rule['target'], 'branch')
        self.assertEqual(self.rule['enforcement'], 'active')
        self.assertEqual(self.rule['conditions']['ref_name']['include'], ['refs/heads/main'])
        self.assertEqual(self.rule['bypass_actors'], [])
        rules = {rule['type']: rule for rule in self.rule['rules']}
        self.assertEqual(set(rules), {'pull_request', 'deletion', 'non_fast_forward'})
        self.assertEqual(rules['pull_request']['parameters']['required_approving_review_count'], 0)
        self.assertEqual(set(self.seed.call_args.args[1]), {WORKFLOW, 'site/index.html'})
        self.live.assert_called_once_with(SITE.url)

    def test_rerun_reuses_pages_and_ruleset(self):
        self.run_furnish()
        self.api.reset_mock()
        self.run_furnish()
        writes = [(method, path) for method, path, *_ in
                  [call.args for call in self.api.request.call_args_list] if method != 'GET']
        self.assertEqual(writes, [('POST', REPO + '/actions/workflows/deploy.yml/dispatches')])

    def test_rerun_after_failed_default_branch_update(self):
        self.repo['default_branch'] = 'master'
        self.default_branch_update_fails = True
        with self.assertRaises(APIError):
            self.run_furnish()
        self.assertIsNone(self.pages)

        self.default_branch_update_fails = False
        self.assertEqual(self.run_furnish()['url'], SITE.url)
        self.assertTrue(self.seed.call_args.kwargs['require_main_only'])
        self.assertEqual(self.repo['default_branch'], 'main')

    def test_conflicting_pages_or_ruleset_stops_before_seed(self):
        for pages, rule in (({'build_type': 'legacy'}, None),
                            (None, {**ruleset_payload(), 'enforcement': 'disabled'})):
            with self.subTest(pages=pages, rule=rule):
                self.pages, self.rule = pages, rule
                self.api.reset_mock()
                with self.assertRaises(FactoryError):
                    self.run_furnish()
                self.seed.assert_not_called()
                self.assertTrue(all(call.args[0] == 'GET' for call in self.api.request.call_args_list))

    def test_target_formats_and_foreign_account(self):
        self.assertEqual(parse_repository('my-site'), SITE)
        self.assertEqual(parse_repository(SITE.repository), SITE)
        self.assertEqual(parse_repository(REPO_URL), SITE)
        for value in ('someone/my-site', 'https://example.com/' + SITE.repository,
                      REPO_URL + '/settings'):
            with self.subTest(value=value), self.assertRaises(FactoryError):
                parse_repository(value)

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
        self.assertEqual(result['url'], url)
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


class WorkflowTests(unittest.TestCase):
    def test_furnished_workflow_deploys_site_on_main_and_manual_dispatch(self):
        workflow = yaml.load((ROOT / 'templates/deploy.yml').read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(set(workflow['on']), {'push', 'workflow_dispatch'})
        self.assertEqual(workflow['on']['push']['branches'], ['main'])
        self.assertEqual(workflow['permissions'], {'contents': 'read'})
        steps = [step for job in workflow['jobs'].values() for step in job['steps']]
        for step in steps:
            if action := step.get('uses'):
                self.assertRegex(action, r'^actions/[^@]+@[a-f0-9]{40}$')
        upload = next(step for step in steps if step.get('uses', '').startswith('actions/upload-pages-artifact@'))
        self.assertEqual(upload['with']['path'], 'site')
        self.assertNotIn('secrets.', str(workflow))
