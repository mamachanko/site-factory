# Working on site-factory

Read README.md before changing authentication, repository initialization, DNS instructions, or workflows. Keep owner and domain restrictions in `scripts/factory.py`. Keep generated projects independent and buildless. Never create actual site repositories or modify DNS in tests.

Run `python3 -m pip install -r requirements-dev.txt`, then `python3 -m unittest discover -s tests -v`, `python3 starter/scripts/check_site.py`, and `node --test starter/tests/*.test.mjs`. Use Python 3.12+ and Node.js 24+. The factory runtime uses only Python's standard library, Git, and gh. PyYAML is a test-only dependency. Read `starter/AGENTS.md` when editing starter files.

The manual workflow runs only on main in mamachanko/site-factory. Never expose App keys/tokens in PR workflows. Preserve the credential-free plan, one target-scoped App token after successful planning, no-force pushes, and partial-failure reporting. Keep `initialize-site.yml` as the only manual entry point and `site-factory-live` restricted to main. Accept only empty targets or the exact raw/rendered starter from the same factory revision and inputs. Do not restore repository creation, owner-wide tokens, or local receipts. Do not automatically delete or overwrite repositories to recover from a failure.
