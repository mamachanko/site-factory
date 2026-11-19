from pathlib import Path
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    # BaseLoader preserves YAML's `on` key instead of treating it as YAML 1.1 true.
    return yaml.load(path.read_text(), Loader=yaml.BaseLoader)


class WorkflowTests(unittest.TestCase):
    def test_all_workflows_parse_and_have_minimal_default_permissions(self):
        paths = list(ROOT.glob('.github/workflows/*.yml')) + list(ROOT.glob('starter/.github/workflows/*.yml'))
        self.assertEqual(len(paths), 4)
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

    def test_initialization_is_manual_main_only_with_boolean_dry_run(self):
        workflow = load(ROOT / '.github/workflows/initialize-site.yml')
        self.assertEqual(list(workflow['on']), ['workflow_dispatch'])
        inputs = workflow['on']['workflow_dispatch']['inputs']
        self.assertEqual(set(inputs), {'repository_name', 'description', 'custom_domain', 'dry_run'})
        self.assertEqual(inputs['repository_name']['required'], 'true')
        self.assertEqual(inputs['dry_run']['default'], 'true')
        self.assertEqual(inputs['dry_run']['type'], 'boolean')
        plan = workflow['jobs']['plan']
        initialize = workflow['jobs']['initialize']
        self.assertIn("github.repository == 'mamachanko/site-factory'", plan['if'])
        self.assertIn("github.ref == 'refs/heads/main'", plan['if'])
        self.assertNotIn('environment', plan)
        self.assertNotIn('secrets.', str(plan))
        self.assertNotIn('create-github-app-token', str(plan))
        self.assertEqual([step['run'] for step in plan['steps'] if 'run' in step], ['python3 scripts/factory.py plan'])
        self.assertEqual(initialize['needs'], 'plan')
        self.assertEqual(initialize['if'], "${{ needs.plan.result == 'success' && !inputs.dry_run }}")
        self.assertEqual(initialize['environment'], 'site-factory-live')
        steps = initialize['steps']
        tokens = [step for step in steps if 'create-github-app-token' in step.get('uses', '')]
        self.assertEqual(len(tokens), 1)
        for token in tokens:
            self.assertEqual(token['with']['owner'], 'mamachanko')
            self.assertEqual(token['with']['app-id'], '${{ vars.SITE_FACTORY_APP_ID }}')
            self.assertEqual(token['with']['private-key'], '${{ secrets.SITE_FACTORY_APP_PRIVATE_KEY }}')
        self.assertEqual(tokens[0]['with']['repositories'], '${{ inputs.repository_name }}')
        self.assertEqual(
            {key: value for key, value in tokens[0]['with'].items() if key.startswith('permission-')},
            {f'permission-{name}': 'write' for name in ('administration', 'contents', 'workflows', 'pages', 'actions')},
        )
        self.assertEqual(workflow['name'], 'Initialize site')
        self.assertEqual(workflow['concurrency'], {
            'group': 'site-factory-initialize-${{ inputs.repository_name }}',
            'cancel-in-progress': 'false',
        })
        run_steps = [step for step in steps if 'run' in step and step.get('if') != 'failure()']
        self.assertEqual([step['run'] for step in run_steps], ['python3 scripts/factory.py initialize'])
        self.assertEqual(run_steps[0]['env']['GH_TOKEN'], '${{ steps.target-token.outputs.token }}')
        self.assertNotIn('FACTORY_STATE', str(workflow))
        self.assertNotIn('--state', str(workflow))
        self.assertFalse((ROOT / '.github/workflows/create-site.yml').exists())
        for step in plan['steps'] + steps:
            # User expressions belong in env/structured action inputs, never shell code.
            self.assertNotIn('${{ inputs.', step.get('run', ''))

    def test_deployment_separates_unprivileged_checks_and_minimal_deploy(self):
        workflow = load(ROOT / 'starter/.github/workflows/deploy.yml')
        self.assertEqual(workflow['on']['push']['branches'], ['main'])
        self.assertIn('workflow_dispatch', workflow['on'])
        deploy = workflow['jobs']['deploy']
        self.assertEqual(deploy['permissions'], {'pages': 'write', 'id-token': 'write'})
        self.assertEqual(deploy['needs'], 'check-and-upload')
        self.assertEqual(deploy['environment']['name'], 'github-pages')
        self.assertEqual(workflow['jobs']['check-and-upload']['permissions'], {'contents': 'read', 'pages': 'read'})
        steps = workflow['jobs']['check-and-upload']['steps']
        upload = next(step for step in steps if step.get('uses', '').startswith('actions/upload-pages-artifact@'))
        self.assertEqual(upload['with']['path'], 'site')
        content = (ROOT / 'starter/.github/workflows/deploy.yml').read_text()
        self.assertNotIn('secrets.', content)
        self.assertNotIn('enablement: true', content)

    def test_pr_workflows_have_no_privileged_credentials(self):
        for path in (ROOT / '.github/workflows/ci.yml', ROOT / 'starter/.github/workflows/ci.yml'):
            workflow = load(path)
            self.assertIn('pull_request', workflow['on'])
            self.assertNotIn('pull_request_target', workflow['on'])
            self.assertNotIn('secrets.', path.read_text())
            self.assertNotIn('create-github-app-token', path.read_text())


if __name__ == '__main__':
    unittest.main()
