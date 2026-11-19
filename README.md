# site-factory

Prepare an existing public repository in `mamachanko`'s personal account for Codex and GitHub Pages. Create the repository yourself, grant the existing factory App access, then run **Initialize site**. The factory adds a vanilla HTML/CSS/JavaScript starter, configures Pages, and dispatches deployment. Each site stays independent and buildless. The factory does not create repositories, host a template repository, or change DNS.

**Dry run is the default.** It validates inputs, renders the starter in memory, and prints the operations, expected URLs, and exact proposed DNS records. It needs no App credentials and makes no GitHub requests, so it cannot check the target repository, App access, or Pages settings. Tests never create real GitHub repositories.

## How it works

```text
site-factory/
├── .github/workflows/
│   ├── initialize-site.yml   Manual factory, main branch only
│   └── ci.yml                Unprivileged factory tests on PRs and main
├── scripts/factory.py        Validation, rendering, REST API, safe Git push, reporting
├── starter/                  Everything copied into an eligible repository
├── tests/                    Offline API mocks, local Git integration, YAML checks
└── requirements-dev.txt      PyYAML for workflow tests; no runtime packages
```

Each generated repository contains:

```text
puzzles/
├── site/
│   ├── index.html            Responsive, semantic starter with a working warm-up riddle
│   ├── styles.css            Mobile-first layout, visible focus, generous touch targets
│   └── app.mjs               Pure game logic and a small DOM adapter
├── scripts/check_site.py     Static HTML/link/asset/accessibility sanity checks
├── tests/puzzle.test.mjs     Node built-in tests for game rules and form events
├── .github/workflows/
│   ├── ci.yml                PR and main checks, no privileged credentials
│   └── deploy.yml            Check/upload job, then isolated Pages deployment job
├── AGENTS.md                 Development and testing guide for Codex and other agents
├── CLAUDE.md                 Points Claude Code to AGENTS.md
├── README.md                 Site-specific local development instructions
└── .gitignore
```

Only `site/` is uploaded to Pages. Source guidance, tests, scripts, and workflows stay out of the published artifact. Sites work at both `https://mamachanko.github.io/puzzles/` and a custom domain because assets use relative paths. Serving needs only Python's HTTP server; Node is used for tests, not a build.

## One-time GitHub App setup

1. In the **mamachanko personal account**, open Settings → Developer settings → GitHub Apps → New GitHub App. Give it a distinct name such as `mamachanko-site-factory` and set its homepage to this repository's URL.
2. Disable **Webhook → Active**; this factory does not use webhooks. No callback URL, OAuth authorization flow, user permissions, or organization permissions are needed. Set installation availability to **Only on this account**.
3. Set exactly these **Repository permissions**. The UI's “Read and write” corresponds to API permission `write`:

   | Permission | Level | Purpose |
   | --- | --- | --- |
   | Administration | Read and write | Set the default branch and configure Pages |
   | Contents | Read and write | Read repository state and push starter commits |
   | Workflows | Read and write | Write the starter `.github/workflows` files |
   | Pages | Read and write | Enable workflow-based Pages and set its custom domain |
   | Actions | Read and write | Dispatch the initial deployment workflow |
   | Metadata | Read-only (automatic) | GitHub's mandatory metadata access |

   Do not grant unrelated permissions, account permissions, or a classic PAT.
4. Create the App. Copy its **App ID** and generate a **private key**. Keep the downloaded PEM private.
5. Under Install App, install it on **mamachanko**, choose **Only select repositories**, and select **site-factory**. Before each initialization, add the target repository to this installation's selected repositories. If permissions are later changed, approve the updated installation permissions too.
6. In **site-factory → Settings → Environments**, create `site-factory-live`. Under **Deployment branches and tags**, choose **Selected branches and tags** and add a **Branch** rule for `main`. Then add an **Environment secret** named `SITE_FACTORY_APP_PRIVATE_KEY` with the entire PEM, including header/footer and line breaks. If upgrading an existing setup, remove the repository-level copy of the secret after setting up the restricted environment.
7. In **site-factory → Settings → Secrets and variables → Actions → Variables**, add the App's numeric ID as the repository variable `SITE_FACTORY_APP_ID`.

8. Enable GitHub Actions in site-factory. Keep the repository's default branch as **main** and make these files available on that branch before running the workflow. Allow the official `actions/*` used here under any Actions policy. The generated repositories also need Actions and Pages allowed by account policy.

For an existing installation, keep the same numeric `SITE_FACTORY_APP_ID` variable and PEM `SITE_FACTORY_APP_PRIVATE_KEY` environment secret. Grant the App access to each target repository before running initialization. The live job mints one token scoped to that target, with the repository permissions above. It never mints an owner-wide token. The action revokes the token during its default post-job cleanup.

The workflow runs only from `main` in `mamachanko/site-factory`. Credential-free planning must succeed before the live job can run in `site-factory-live`. At most one run for a target repository proceeds at a time. Restrict write access and protect `main` to control changes to code that receives App credentials. PR CI uses a read-only `GITHUB_TOKEN` and receives no App credentials. Generated sites use their own `GITHUB_TOKEN`, with `pages: write` and `id-token: write` in the deployment job and `contents: read` and `pages: read` in the check-and-upload job.

## Verify domains before first use

In **mamachanko → personal Settings → Pages → Add a domain**, verify `mamachanko.com` and `maxbrauer.com` if you plan to use both. GitHub displays an account-specific TXT record:

```text
Type: TXT
Host: _github-pages-challenge-mamachanko
Value: <the exact verification value supplied by GitHub>
```

At Namecheap, choose the relevant domain → Manage → Advanced DNS → Host Records → Add New Record. Add GitHub's exact TXT host/value, return to GitHub, and click Verify. Keep the TXT record after verification. Before pointing DNS to Pages, confirm that the exact hostname or its immediate parent is verified in your personal Pages settings. For example, `maxbrauer.com` verification covers `games.maxbrauer.com`, and `word.games.maxbrauer.com` needs verification of `games.maxbrauer.com` or the exact hostname. Remove the Pages-pointing DNS record before retiring or detaching a site, and avoid wildcard records.

If the domain uses third-party nameservers, edit records at the **authoritative DNS provider**, even if Namecheap is the registrar. The factory never contacts Namecheap or changes any DNS record.

## First website: puzzles.mamachanko.com

For a first test on the default Pages domain, leave `custom_domain` blank. Once the deployment succeeds, open `https://mamachanko.github.io/puzzles/`.

1. Create public **mamachanko/puzzles** yourself. Leave it empty, without a README, license, or `.gitignore`. Alternatively, use a template that contains an exact, unrendered copy of this factory revision's `starter/` contents at the repository root. Include all files, including dotfiles, with their original modes. The only branch must be `main`, with no tags or extra files. Do not place the files inside a `starter/` directory. This factory does not provide a hosted template.
2. In the existing factory App installation, grant access to **puzzles**. Open **site-factory → Actions → Initialize site → Run workflow** on `main`. Enter:

   ```text
   repository_name: puzzles
   description: A collection of mobile-first word games
   custom_domain: puzzles.mamachanko.com
   dry_run: true
   ```

3. Run it and review the job summary. This checks local validation and rendering without credentials or network requests. It does not inspect the target, check App access, prove domain ownership, or validate GitHub settings.
4. Run the same workflow with the same inputs and **dry_run unchecked (`false`)**. Live execution:
   - Verifies that the target exists, is public, and belongs to the `mamachanko` personal account.
   - Accepts an empty repository, the exact raw starter on `main`, or the exact rendered starter on `main` from this factory revision and these inputs. Other branches, tags, extra files, and changed files are refused.
   - Checks Pages for conflicting settings before writing source. Existing Pages must use GitHub Actions and have no custom domain or the exact requested domain. A configured domain conflicts with an empty domain request.
   - Adds rendered starter files with a normal initial or fast-forward push on `main`. Existing rendered files need no push. No force push is used. The starter commit includes `[skip ci]` to avoid deployment before Pages configuration.
   - Sets the default branch to `main`, enables Pages with `build_type: workflow` if absent, and sets and confirms the requested custom domain without a `CNAME` file.
   - Explicitly dispatches `.github/workflows/deploy.yml` on `main`. Registration delays have a bounded retry budget.
5. After success, confirm **puzzles → Settings → Pages** shows **GitHub Actions** and the intended domain. The summary reports the repository URL, expected deployment URL, workflow URL, and the following exact Namecheap record:

   ```text
   Domain: mamachanko.com
   Type: CNAME
   Host: puzzles
   Value: mamachanko.github.io
   TTL: Automatic
   ```

   In Namecheap → Domain List → mamachanko.com → Manage → Advanced DNS → Host Records, review any existing records at `puzzles`, replace conflicting records there, and add this CNAME. Do not include `https://`, `/puzzles`, or the domain suffix in the Host field. Do not create wildcard records. Configure the Pages custom domain **before** adding the pointing DNS record.
6. Follow **puzzles → Actions → Deploy to GitHub Pages** for actual deployment status. The factory reports a successful dispatch, not a completed deployment. DNS can take up to 24 hours, and TLS certificate provisioning can take additional time. Once available, enable **Enforce HTTPS** in Settings → Pages.

The result is `https://github.com/mamachanko/puzzles` and, after deployment/DNS/TLS, `https://puzzles.mamachanko.com/`. With an empty domain, the expected URL is `https://mamachanko.github.io/puzzles/` and no DNS work is required. An existing account-level Pages custom domain can affect GitHub's default URL/redirect behavior; Settings → Pages and the deployment environment show the actual URL.

### Input rules and DNS variants

- Names are deliberately stricter than GitHub's general naming rules: 1–63 lowercase ASCII letters/digits, with single hyphens between groups. No uppercase, underscores, dots, slashes, whitespace, shell syntax, or leading/trailing/repeated hyphens. `site-factory` is reserved. There is no owner input.
- Descriptions are optional, one line, at most 350 characters, without control characters. Values travel through environment variables, never interpolated shell commands. Rendered description text is HTML-escaped and never inserted into workflows or JavaScript.
- Domains must be lowercase ASCII DNS hostnames, at most 253 characters and 63 per label. Only `mamachanko.com`, `maxbrauer.com`, and dot-separated subdomains of those exact domains are accepted. URLs, paths, ports, wildcards, trailing dots, malformed labels, and suffix tricks are rejected.
- `word.games.maxbrauer.com` produces a CNAME with Namecheap Host `word.games` and Value `mamachanko.github.io` in zone `maxbrauer.com`.
- Either allowed apex produces four separate **A** records, Host **@**, TTL **Automatic**, with values **185.199.108.153**, **185.199.109.153**, **185.199.110.153**, and **185.199.111.153**. Review existing apex records before replacing them. The factory does not add `www`, wildcard records, or optional IPv6 records. Subdomains use a CNAME, not these A records.

## Work on the generated site

```sh
git clone https://github.com/mamachanko/puzzles.git
cd puzzles
python3 -m http.server 8000 --directory site
```

Open http://localhost:8000. Start Codex in this repository, or run Claude Code from its root. `AGENTS.md` supplies the shared instructions and `CLAUDE.md` points to it. A useful first task is: “Replace the warm-up with a mobile-first word game. Keep the site buildless, preserve keyboard access and status feedback, and add tests for the game rules.”

Use a PR and let CI run. Merging to `main` automatically checks, uploads, and deploys the site; Actions → Deploy to GitHub Pages → Run workflow can redeploy manually. The site has no runtime link to site-factory. You can remove the factory App's access to the generated repo after successful initialization; its normal deployment continues to use `GITHUB_TOKEN`.

## Develop and test this factory

Use Python 3.12+, Node.js 24+, Git, and `gh` (GitHub-hosted Ubuntu runners provide Git and gh). Factory runtime dependencies are Python's standard library only. PyYAML is used only for workflow tests.

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements-dev.txt
python3 -m unittest discover -s tests -v
python3 starter/scripts/check_site.py
node --check starter/site/app.mjs
node --test starter/tests/*.test.mjs
```

Try a completely offline dry run:

```sh
REPOSITORY_NAME=puzzles \
SITE_DESCRIPTION='A collection of mobile-first word games' \
CUSTOM_DOMAIN=puzzles.mamachanko.com \
python3 scripts/factory.py plan
```

The `initialize` command is for the trusted live job, with `GH_TOKEN` supplied by the target-scoped App action:

```sh
REPOSITORY_NAME=puzzles python3 scripts/factory.py initialize
```

Use the same description and domain environment variables as the plan. There is no local receipt or separate creation phase. Do not use a PAT or put tokens in commands, remotes, files, or commits. Git authentication uses `gh auth git-credential`, reading the token from the environment, with inherited Git tracing and configuration disabled. Git and HTTP failure reports omit raw diagnostics that might expose credentials.

Tests use offline API mocks and temporary local bare Git repositories. They cover validation, rendering, eligible repository states, identity and concurrency checks, Pages conflicts, retry behavior, deployment ordering, workflow scoping, and failure summaries. No test creates a GitHub repository, dispatches a live workflow, or edits DNS. YAML security assertions complement `actionlint` when available. These checks do not prove that a live App grant or account policy permits initialization. A separately authorized live run must confirm App access, Git authentication, Pages configuration, and deployment. Static site checks are sanity checks. Manually test keyboard and mobile behavior when extending the starter.

## Troubleshoot and recover

| Symptom | What to check / next step |
| --- | --- |
| Workflow is absent or skipped | Commit it to default `main`; dispatch on `main` in `mamachanko/site-factory`. Other branches/repos are intentionally skipped. |
| App-token step fails | App ID variable, complete PEM in the `site-factory-live` environment, installation on the personal account, approved permissions, and selected repository access. |
| HTTP 401/403 | Token expiry, permissions, App access to the existing target, or account Actions/Pages policy. Do not substitute a classic PAT. |
| Target not eligible | Confirm that the target is public and owned by the `mamachanko` personal account. Inspect refs and the complete tree. Only an empty repository or the exact raw/rendered starter on `main` is supported. |
| Git push fails | Confirm Contents and Workflows write, App access, account push rules, and no concurrent edits. The factory never force-pushes. Inspect the repository before retrying. |
| Pages creation/configuration HTTP 422 | Check Pages eligibility, default branch/initial commit, account policies, domain spelling, domain ownership/verification, or whether another Pages site already claims it. Do not add pointing DNS until the intended domain is confirmed. |
| Dispatch keeps returning 404/422 | Registration retry budget expired. Confirm `main` contains `.github/workflows/deploy.yml`, Actions is enabled, and the target token has Actions write. Once Pages/domain configuration is confirmed, manually dispatch Deploy to GitHub Pages in the target repo. |
| Deployment fails after factory success | Open the target repo's deployment workflow. Check tests, Pages source, environment protection/required reviewers, allowed action policy, and Pages availability. The target workflow runs independently after initialization. |
| Domain does not resolve / certificate pending | Confirm authoritative DNS, exact Host/Value, no conflicting records, successful deployment, and Settings → Pages DNS/TLS state. Wait for propagation; enable Enforce HTTPS when available. |

Live failures are **not transactional**. The summary reports the last completed operation and failing API/status without dumping credentials or raw response bodies. The factory never deletes a repository or rolls back visible changes automatically.

Inspect the target after a failure, then retry with the **same factory revision and identical inputs**. Use **Re-run all jobs** on the original live run to keep its revision and inputs. The exact rendered starter is a supported retry state when Pages settings or deployment dispatch remain incomplete. Changed files or a newer starter revision cause refusal. After the site has been edited, complete any missing Pages setup or deployment manually instead of rerunning initialization. An ambiguous dispatch can queue another deployment on retry. The target workflow serializes Pages deployments.

Avoid external edits during initialization. The factory checks refs and repository identity again before writes and uses normal Git push protections. Git refs and Pages settings cannot change atomically, so these checks cannot prevent every concurrent settings change. Do not add pointing DNS until Settings → Pages confirms the intended custom domain.

## Official references

The workflows pin actions to full upstream commit SHAs. The comments beside each pin identify the major release line. Review the upstream release when updating a pin.

- [Install your own GitHub App](https://docs.github.com/en/apps/using-github-apps/installing-your-own-github-app) — selected repository access.
- [Create GitHub App token action](https://github.com/actions/create-github-app-token) — owner/repository scoping, permission inputs, token cleanup.
- [Pages REST API](https://docs.github.com/en/rest/pages/pages) — `build_type: workflow`, Pages creation, and custom-domain settings.
- [Use custom workflows with Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages) — official actions, artifact, permissions, and deployment environment.
- [Manage a Pages custom domain](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site) — configure Pages before DNS, CNAME/A records, and no CNAME file for Actions publishing.
- [Verify a Pages custom domain](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/verifying-your-custom-domain-for-github-pages) — account TXT verification and wildcard risks.
- [Skip workflow runs](https://docs.github.com/en/actions/managing-workflow-runs-and-deployments/managing-workflow-runs/skipping-workflow-runs) — skip the initial push while allowing explicit workflow dispatch.

No Cloudflare, Docker, Terraform, Namecheap API, or other external deployment service is involved.
