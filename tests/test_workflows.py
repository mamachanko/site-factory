from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    # BaseLoader preserves YAML's `on` key instead of treating it as YAML 1.1 true.
    return yaml.load(path.read_text(), Loader=yaml.BaseLoader)


class WorkflowTests(unittest.TestCase):
    def test_all_workflows_parse_and_have_minimal_default_permissions(self):
        paths = list(ROOT.glob('.github/workflows/*.yml'))
        self.assertEqual({path.name for path in paths}, {'ci.yml', 'furnish-site.yml'})
        paths.append(ROOT / 'templates/deploy.yml')
        for path in paths:
            with self.subTest(path=path):
                workflow = load(path)
                self.assertIn('on', workflow)
                self.assertEqual(workflow['permissions'], {'contents': 'read'})
                for job in workflow['jobs'].values():
                    self.assertIn('runs-on', job)
                    for step in job['steps']:
                        if action := step.get('uses'):
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

    def test_deployment_separates_unprivileged_checks_and_minimal_deploy(self):
        workflow = load(ROOT / 'templates/deploy.yml')
        self.assertEqual(workflow['on']['push']['branches'], ['main'])
        self.assertEqual(set(workflow['on']), {'push', 'workflow_dispatch'})
        deploy = workflow['jobs']['deploy']
        self.assertEqual(deploy['permissions'], {'pages': 'write', 'id-token': 'write'})
        self.assertEqual(deploy['needs'], 'upload')
        self.assertEqual(deploy['environment']['name'], 'github-pages')
        self.assertEqual(workflow['jobs']['upload']['permissions'], {'contents': 'read', 'pages': 'read'})
        steps = workflow['jobs']['upload']['steps']
        upload = next(step for step in steps if step.get('uses', '').startswith('actions/upload-pages-artifact@'))
        self.assertEqual(upload['with']['path'], 'site')
        content = (ROOT / 'templates/deploy.yml').read_text()
        self.assertNotIn('secrets.', content)
        self.assertNotIn('enablement: true', content)

    def test_pr_workflow_has_no_privileged_credentials(self):
        path = ROOT / '.github/workflows/ci.yml'
        workflow = load(path)
        self.assertIn('pull_request', workflow['on'])
        self.assertNotIn('pull_request_target', workflow['on'])
        self.assertNotIn('secrets.', path.read_text())
        self.assertNotIn('create-github-app-token', path.read_text())

    def test_pages_workflow_rejects_symlinks_before_upload(self):
        workflow = load(ROOT / 'templates/deploy.yml')
        steps = workflow['jobs']['upload']['steps']
        check, = [step for step in steps if step.get('name') == 'Check site files']
        upload = next(step for step in steps if step.get('uses', '').startswith('actions/upload-pages-artifact@'))
        self.assertLess(steps.index(check), steps.index(upload))
        self.assertEqual(check['shell'], 'bash')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = root / 'site'
            site.mkdir()
            (site / 'index.html').write_text('<h1>Hello</h1>')
            outside = root / 'outside.txt'
            outside.write_text('Harmless sibling fixture')

            def run_check():
                return subprocess.run(
                    ['bash', '-e', '-o', 'pipefail', '-c', check['run']],
                    cwd=root, capture_output=True, text=True,
                )

            regular = run_check()
            self.assertEqual(regular.returncode, 0, regular.stderr)
            for target in (outside, site / 'index.html', root / 'missing'):
                with self.subTest(target=target.name):
                    link = site / 'linked.txt'
                    link.symlink_to(target)
                    linked = run_check()
                    self.assertNotEqual(linked.returncode, 0)
                    self.assertIn('Remove symbolic links from site/', linked.stdout)
                    link.unlink()


if __name__ == '__main__':
    unittest.main()
