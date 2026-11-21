# Working on site-factory

Read README.md before changing authentication, repository setup, or workflows. Keep owner, repository name, and domain validation in `scripts/factory.py`. Keep generated sites independent and buildless.

Furnish site runs on `main` in `mamachanko/site-factory`. It uses a GitHub App token scoped to the named repository. Keep App credentials out of PR workflows. Preserve existing site files, normal Git pushes, and safe retries.

Use Python 3.12+, Git, and GitHub CLI. Install test dependencies with `python3 -m pip install -r requirements-dev.txt`. Run `python3 -m unittest discover -s tests -v` and `actionlint .github/workflows/*.yml templates/deploy.yml`. Tests must use mocked GitHub responses or local Git repositories.
