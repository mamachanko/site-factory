# Working on site-factory

Read README.md before changing authentication, repository creation, DNS instructions, or workflows. Keep owner and domain restrictions in `scripts/factory.py`. Keep generated projects independent and buildless. Never create actual site repositories or modify DNS in tests.

Run `python3 -m pip install -r requirements-dev.txt`, then `python3 -m unittest discover -s tests -v`, `python3 starter/scripts/check_site.py`, and `node --test starter/tests/*.test.mjs`. Use Python 3.12+ and Node.js 24+. The factory runtime uses only Python's standard library, Git, and gh. PyYAML is a test-only dependency. Read `starter/AGENTS.md` when editing starter files.

The manual workflow runs only on main in mamachanko/site-factory. Never expose App keys/tokens in PR workflows. Preserve token refresh after creation, no-force pushes, credential-free dry runs, and partial-failure reporting. Do not automatically delete or overwrite repositories to recover from a failure.
