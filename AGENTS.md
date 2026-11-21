# Working on site-factory

Read README.md before changing authentication, repository creation, DNS instructions, or workflows. Keep owner and domain restrictions in `scripts/factory.py`. Keep generated projects independent and buildless. Never create actual site repositories or modify DNS in tests.

Run `python3 -m pip install -r requirements-dev.txt`, then `python3 -m unittest discover -s tests -v`, `python3 starter/scripts/check_site.py`, and `node --test starter/tests/*.test.mjs`. Use Python 3.12+ and Node.js 24+. The factory runtime uses only Python's standard library, Git, and gh. PyYAML is a test-only dependency. Read `starter/AGENTS.md` when editing starter files.

Run the manual workflows on `main` in `mamachanko/site-factory`. Furnish site starts with an owner-created repository and uses a token scoped to that repository. Create site creates the repository and refreshes the token before populating it. Keep App keys and tokens out of PR workflows. Preserve credential-free dry runs, normal Git pushes, and partial-failure reporting. Do not delete or overwrite repositories to recover from a failure.
