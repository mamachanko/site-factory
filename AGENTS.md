# Work on Site Factory

## Before you edit

- Read `README.md` before changing App authentication, initialization, DNS instructions, or workflows.
- Read `starter/AGENTS.md` before editing the starter. Keep generated sites buildless and independent of the factory.

## Preserve the setup rules

- Keep repository owner and domain validation in `scripts/factory.py`.
- Keep `initialize-site.yml` as the manual entry point on `main` in `mamachanko/site-factory`. Restrict `site-factory-live` to `main` and keep App credentials out of pull request jobs.
- Plan without credentials. After planning succeeds, mint one token scoped to the repository the owner created and granted to the App.
- Accept only an empty repository or the exact raw or rendered starter from the matching factory revision. Use normal Git pushes. Report the stage where setup stops. Recover from Git and Pages state, and leave deletion or overwrite decisions to the repository owner.

## Run the checks

Use Python 3.12 or later and Node.js 24 or later. The factory uses the Python standard library, Git, and `gh`. PyYAML is for tests.

```sh
python3 -m pip install -r requirements-dev.txt
python3 -m unittest discover -s tests -v
python3 starter/scripts/check_site.py
node --test starter/tests/*.test.mjs
```

Test with mocked GitHub responses and temporary local Git repositories. Keep live repositories and DNS out of tests.
