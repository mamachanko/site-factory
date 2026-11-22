import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / 'templates'
DEPLOY = TEMPLATES / '.github/workflows/deploy.yml'
RENOVATE = TEMPLATES / '.github/workflows/renovate.yml'


def load(path):
    # BaseLoader preserves YAML's `on` key instead of treating it as YAML 1.1 true.
    return yaml.load(path.read_text(), Loader=yaml.BaseLoader)


class WorkflowTests(unittest.TestCase):
    def test_all_workflows_parse_and_have_minimal_default_permissions(self):
        paths = list(ROOT.glob('.github/workflows/*.yml'))
        self.assertEqual({path.name for path in paths}, {'ci.yml', 'furnish-site.yml'})
        paths.extend(TEMPLATES.glob('.github/workflows/*.yml'))
        for path in paths:
            with self.subTest(path=path):
                workflow = load(path)
                self.assertIn('on', workflow)
                self.assertEqual(workflow['permissions'], {'contents': 'read'})
                for job in workflow['jobs'].values():
                    self.assertIn('runs-on', job)
                    for step in job['steps']:
                        if action := step.get('uses'):
                            if path.is_relative_to(TEMPLATES):
                                self.assertTrue(action.startswith('./.github/actions/'), action)
                                self.assertTrue((TEMPLATES / action / 'action.yml').is_file())
                            else:
                                self.assertRegex(action, r'^[^@]+@[a-f0-9]{40}$')
                        if step.get('uses', '').startswith('actions/checkout@'):
                            self.assertEqual(step['with']['persist-credentials'], 'false')

    def test_furnish_uses_one_mobile_input_and_mints_a_token_for_that_repo(self):
        workflow = load(ROOT / '.github/workflows/furnish-site.yml')
        self.assertEqual(workflow['name'], 'Furnish site')
        self.assertEqual(list(workflow['on']), ['workflow_dispatch'])
        inputs = workflow['on']['workflow_dispatch']['inputs']
        self.assertEqual(set(inputs), {'repository_name'})
        self.assertEqual(inputs['repository_name']['required'], 'true')
        self.assertEqual(inputs['repository_name']['type'], 'string')
        job, = workflow['jobs'].values()
        self.assertEqual(job['environment'], 'site-factory-live')
        for condition in ("github.repository == 'mamachanko/site-factory'",
                          "github.ref == 'refs/heads/main'", "github.actor == 'mamachanko'",
                          "github.triggering_actor == 'mamachanko'"):
            self.assertIn(condition, job['if'])
        steps = job['steps']
        validate, = [step for step in steps if step.get('run') == 'python3 scripts/factory.py validate']
        token, = [step for step in steps if 'create-github-app-token' in step.get('uses', '')]
        provision, = [step for step in steps if step.get('run') == 'python3 scripts/factory.py furnish']
        self.assertLess(steps.index(validate), steps.index(token))
        self.assertLess(steps.index(token), steps.index(provision))
        repository = '${{ steps.' + validate['id'] + '.outputs.repository_name }}'
        self.assertEqual(validate['env']['REPOSITORY_NAME'], '${{ inputs.repository_name }}')
        self.assertEqual(token['with']['owner'], 'mamachanko')
        self.assertEqual(token['with']['repositories'], repository)
        self.assertEqual({key: value for key, value in token['with'].items() if key.startswith('permission-')},
                         {'permission-' + name: 'write' for name in
                          ('administration', 'contents', 'workflows', 'pages', 'actions')})
        self.assertEqual(provision['env'], {
            'REPOSITORY_NAME': repository,
            'GH_TOKEN': '${{ steps.' + token['id'] + '.outputs.token }}',
        })
        self.assertTrue(all('${{' not in step.get('run', '') for step in steps))

    def test_deployment_requires_the_same_check_for_prs_and_main_publication(self):
        workflow = load(DEPLOY)
        self.assertEqual(workflow['name'], 'Deploy to GitHub Pages')
        self.assertEqual(set(workflow['on']), {'pull_request', 'push', 'workflow_dispatch'})
        self.assertEqual(workflow['on']['push']['branches'], ['main'])
        self.assertEqual(workflow['on']['pull_request']['branches'], ['main'])
        jobs = workflow['jobs']
        self.assertEqual(set(jobs), {'check', 'upload', 'deploy'})
        check = jobs['check']
        self.assertEqual(check['name'], 'Check site')
        self.assertNotIn('if', check)
        self.assertNotIn('needs', check)
        self.assertEqual(check['steps'][-1]['run'], 'bash scripts/check-site.sh')
        self.assertEqual(jobs['upload']['needs'], 'check')
        self.assertEqual(set(jobs['deploy']['needs']), {'check', 'upload'})
        for name in ('upload', 'deploy'):
            self.assertEqual(jobs[name]['if'],
                             "github.event_name != 'pull_request' && github.ref == 'refs/heads/main'")
        self.assertEqual(jobs['deploy']['permissions'], {'pages': 'write', 'id-token': 'write'})
        self.assertEqual(jobs['deploy']['environment']['name'], 'github-pages')
        self.assertEqual(jobs['deploy']['environment']['url'], '${{ steps.deployment.outputs.page_url }}')
        self.assertEqual(jobs['upload']['permissions'], {'contents': 'read', 'pages': 'read'})
        self.assertEqual(jobs['upload']['steps'][-2]['run'], 'bash scripts/check-site.sh')
        self.assertEqual(jobs['upload']['steps'][-1]['uses'], './.github/actions/upload-site')
        self.assertEqual(jobs['deploy']['steps'][-1]['uses'], './.github/actions/deploy-site')
        group = workflow['concurrency']['group']
        self.assertIn("github.event_name == 'pull_request'", group)
        self.assertIn('github.event.pull_request.number', group)
        self.assertIn('github.ref', group)
        self.assertEqual(workflow['concurrency']['cancel-in-progress'], 'false')
        self.assertNotIn('secrets.', DEPLOY.read_text())
        self.assertNotIn('enablement: true', DEPLOY.read_text())

    def test_upstream_actions_are_pinned_in_renovate_reachable_composites(self):
        expected = {'actions/configure-pages', 'actions/upload-pages-artifact',
                    'actions/deploy-pages', 'renovatebot/github-action'}
        found = set()
        for path in TEMPLATES.glob('.github/actions/*/action.yml'):
            action = load(path)
            self.assertEqual(action['runs']['using'], 'composite')
            for step in action['runs']['steps']:
                reference = step['uses']
                self.assertRegex(reference, r'^[^@]+@[a-f0-9]{40}$')
                found.add(reference.partition('@')[0])
        self.assertEqual(found, expected)
        upload = load(TEMPLATES / '.github/actions/upload-site/action.yml')
        self.assertEqual(upload['runs']['steps'][-1]['with']['path'], 'site')
        deploy = load(TEMPLATES / '.github/actions/deploy-site/action.yml')
        self.assertEqual(deploy['outputs']['page_url']['value'], '${{ steps.deployment.outputs.page_url }}')
        self.assertEqual(deploy['runs']['steps'][0]['id'], 'deployment')

    def test_renovate_is_daily_and_manual_with_only_repository_token_permissions(self):
        workflow = load(RENOVATE)
        self.assertEqual(set(workflow['on']), {'schedule', 'workflow_dispatch'})
        self.assertEqual(len(workflow['on']['schedule']), 1)
        self.assertRegex(workflow['on']['schedule'][0]['cron'], r'^\d+ \d+ \* \* \*$')
        job, = workflow['jobs'].values()
        self.assertEqual(job['if'], "github.ref == 'refs/heads/main' && (github.event_name == 'schedule' || github.event_name == 'workflow_dispatch')")
        self.assertEqual(job['permissions'], {'contents': 'write', 'issues': 'write', 'pull-requests': 'write'})
        invocation = job['steps'][-1]
        self.assertEqual(invocation['uses'], './.github/actions/renovate')
        self.assertEqual(invocation['with'], {'token': '${{ github.token }}'})
        self.assertNotIn('secrets.', RENOVATE.read_text())
        action = load(TEMPLATES / '.github/actions/renovate/action.yml')
        step, = action['runs']['steps']
        self.assertTrue(step['uses'].startswith('renovatebot/github-action@'))
        self.assertEqual(step['with']['token'], '${{ inputs.token }}')
        self.assertRegex(step['with']['renovate-version'], r'^\d+\.\d+\.\d+$')
        self.assertEqual(step['env']['RENOVATE_REPOSITORIES'], '${{ github.repository }}')
        self.assertEqual(step['env']['RENOVATE_AUTODISCOVER'], 'false')
        self.assertEqual(step['env']['RENOVATE_ONBOARDING'], 'false')
        self.assertEqual(step['env']['RENOVATE_USERNAME'], 'github-actions[bot]')
        config = json.loads((TEMPLATES / 'renovate.json').read_text())
        self.assertEqual(config['enabledManagers'], ['github-actions', 'npm'])
        self.assertIs(config['automerge'], False)
        self.assertIs(config['pinDigests'], True)

    def test_public_checkout_fetches_the_exact_event_commit_without_credentials(self):
        jobs = [*load(DEPLOY)['jobs'].values(), *load(RENOVATE)['jobs'].values()]
        scripts = [job['steps'][0]['run'] for job in jobs]
        self.assertEqual(len(set(scripts)), 1)
        script = scripts[0]
        self.assertIn('"$GITHUB_SHA"', script)
        self.assertIn('https://github.com/${GITHUB_REPOSITORY}.git', script)
        for forbidden in ('github.token', 'secrets.', 'GITHUB_TOKEN', 'refs/heads/', 'git remote'):
            self.assertNotIn(forbidden, script)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source'
            source.mkdir()
            def git(*args):
                return subprocess.run(['git', *args], cwd=source, check=True,
                                      capture_output=True, text=True).stdout.strip()
            git('init', '--initial-branch=main')
            git('config', 'user.name', 'Fixture')
            git('config', 'user.email', 'fixture@example.org')
            (source / 'index.html').write_text('event commit')
            git('add', '.')
            git('commit', '-m', 'Event commit')
            event_sha = git('rev-parse', 'HEAD')
            (source / 'index.html').write_text('later main commit')
            git('commit', '-am', 'Advance main')
            destination = root / 'checkout'
            destination.mkdir()
            env = {**os.environ, 'GITHUB_SHA': event_sha, 'GITHUB_REPOSITORY': 'owner/repo',
                   'FIXTURE_REMOTE': str(source)}
            local_script = script.replace('"https://github.com/${GITHUB_REPOSITORY}.git"', '"$FIXTURE_REMOTE"')
            result = subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', local_script],
                                    cwd=destination, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((destination / 'index.html').read_text(), 'event commit')
            configuration = (destination / '.git/config').read_text()
            self.assertNotIn('extraheader', configuration)
            self.assertNotIn('credential', configuration)
            self.assertNotIn('[remote ', configuration)

    def test_pr_workflow_has_no_privileged_credentials(self):
        path = ROOT / '.github/workflows/ci.yml'
        workflow = load(path)
        self.assertIn('pull_request', workflow['on'])
        self.assertNotIn('pull_request_target', workflow['on'])
        self.assertNotIn('secrets.', path.read_text())
        self.assertNotIn('create-github-app-token', path.read_text())

    def test_buildless_site_check_accepts_regular_files_and_rejects_missing_or_unsafe_paths(self):
        script = TEMPLATES / 'scripts/check-site.sh'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = root / 'site'
            def run_check():
                return subprocess.run(['bash', str(script)], cwd=root,
                                      capture_output=True, text=True)
            def rejected():
                result = run_check()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('::error::', result.stdout)
            rejected()
            site.mkdir()
            rejected()
            (site / 'index.html').mkdir()
            rejected()
            (site / 'index.html').rmdir()
            (site / 'index.html').write_text('<h1>Hello</h1>')
            regular = run_check()
            self.assertEqual(regular.returncode, 0, regular.stderr)
            outside = root / 'outside.txt'
            outside.write_text('Harmless sibling fixture')
            for target in (outside, site / 'index.html', root / 'missing'):
                with self.subTest(target=target.name):
                    link = site / 'linked.txt'
                    link.symlink_to(target)
                    rejected()
                    link.unlink()
            (site / 'nested').mkdir()
            link = site / 'nested/link'
            link.symlink_to(root, target_is_directory=True)
            rejected()
            link.unlink()
            index = site / 'index.html'
            index.unlink()
            index.symlink_to(outside)
            rejected()
            index.unlink()
            index.write_text('Valid index')
            site.rename(root / 'real-site')
            site.symlink_to(root / 'real-site', target_is_directory=True)
            rejected()


if __name__ == '__main__':
    unittest.main()
