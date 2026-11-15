# site-factory

Launch an independent, public GitHub Pages website in `mamachanko`'s personal account from one manual workflow. Supply a repository name, a description, and optionally a custom domain. The factory copies a vanilla HTML/CSS/JavaScript starter, makes one initial commit on `main`, configures Pages, and dispatches deployment. There is no separate template repository, build framework, runtime dependency on this factory, or DNS integration.

**Dry run is the default.** It validates inputs, renders the starter in memory, and prints the operations, expected URLs, and exact proposed DNS records. It needs no App credentials and makes no GitHub requests, so it cannot check repository availability. This implementation's tests never create real GitHub repositories.

## How it works

```text
site-factory/
├── .github/workflows/
│   ├── create-site.yml       Manual factory, main branch only
│   └── ci.yml                Unprivileged factory tests on PRs and main
├── scripts/factory.py        Validation, rendering, REST API, safe Git push, reporting
├── starter/                  Everything copied into a new repository
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
   | Administration | Read and write | Create repositories, set the default branch, enable/configure Pages |
   | Contents | Read and write | Read repository state and push the initial commit |
   | Workflows | Read and write | Include `.github/workflows` in the initial commit |
   | Pages | Read and write | Enable workflow-based Pages and set its custom domain |
   | Actions | Read and write | Dispatch the initial deployment workflow |
   | Metadata | Read-only (automatic) | GitHub's mandatory metadata access |

   Do not grant unrelated permissions, account permissions, or a classic PAT.
4. Create the App. Copy its **App ID** and generate a **private key**. Keep the downloaded PEM private.
5. Under Install App, install it on **mamachanko**, choose **Only select repositories**, and select **site-factory**. If permissions are later changed, approve the updated installation permissions too.
6. In **site-factory → Settings → Secrets and variables → Actions**, configure:

   | Kind | Name | Value |
   | --- | --- | --- |
   | Repository variable | `SITE_FACTORY_APP_ID` | The App's numeric ID |
   | Repository secret | `SITE_FACTORY_APP_PRIVATE_KEY` | The entire PEM, including header/footer and line breaks |

7. Enable GitHub Actions in site-factory. Keep the repository's default branch as **main** and make these files available on that branch before running the workflow. Allow the official `actions/*` used here under any Actions policy. The generated repositories also need Actions and Pages allowed by account policy.

GitHub grants an App access to repositories it creates, even with a selected-repositories installation. The first token uses hardcoded `owner: mamachanko` and omits `repositories`, covering the installation so it can create a repository. After creation, a second `actions/create-github-app-token` step mints a fresh token scoped to the new repository. This avoids relying on the first token's original repository scope. Both tokens are short-lived and revoked by the action's default post-job cleanup.

The workflow runs only from `main` in `mamachanko/site-factory`. Anyone allowed to change that trusted branch can change code that receives the App credentials: restrict write access and protect main as appropriate. PR CI uses read-only `GITHUB_TOKEN` permissions and receives no App key/token; it never uses `pull_request_target`. Generated repositories receive no factory secrets. Their deployment uses their own `GITHUB_TOKEN`, with only `pages: write` and `id-token: write` in the isolated deployment job; checking/uploading has `contents: read` and `pages: read` to read Pages metadata through configure-pages.

## Verify domains before first use

In **mamachanko → personal Settings → Pages → Add a domain**, verify `mamachanko.com` and `maxbrauer.com` if you plan to use both. GitHub displays an account-specific TXT record:

```text
Type: TXT
Host: _github-pages-challenge-mamachanko
Value: <the exact verification value supplied by GitHub>
```

At Namecheap, choose the relevant domain → Manage → Advanced DNS → Host Records → Add New Record. Add GitHub's exact TXT host/value, return to GitHub, and click Verify. Keep the TXT record after verification. The value is account-specific; the factory cannot invent it. Verification of an apex also protects its immediate subdomains. For deeper hostnames, verify the relevant parent or exact domain as described in GitHub's domain verification guide.

If the domain uses third-party nameservers, edit records at the **authoritative DNS provider**, even if Namecheap is the registrar. The factory never contacts Namecheap or changes any DNS record.

## First website: puzzles.mamachanko.com

1. Open **site-factory → Actions → Create site → Run workflow** on `main`.
2. Enter:

   ```text
   repository_name: puzzles
   description: A collection of mobile-first word games
   custom_domain: puzzles.mamachanko.com
   dry_run: true
   ```

3. Run it and review the job summary. This checks local validation/generation without credentials or network requests. It does not reserve the name, check App installation, prove domain ownership, or validate GitHub settings.
4. Run the same workflow with **dry_run unchecked (`false`)**. Live execution:
   - Checks for an existing repository and refuses to overwrite one.
   - Creates **public** `mamachanko/puzzles` through `POST /user/repos`.
   - Refreshes the token and verifies the new repository ID before populating it.
   - Pushes the whole starter in a single initial commit on `main`, with `[skip ci]`. No force push is used; a nonempty remote is rejected. Skipping initial push CI prevents an early deployment before Pages/domain configuration.
   - Sets the default branch to `main` and enables Pages with `build_type: workflow`.
   - Sets and confirms `puzzles.mamachanko.com` through the Pages API, without a `CNAME` file.
   - Explicitly dispatches `.github/workflows/deploy.yml` on `main`. Registration delays are retried at most eight times with capped exponential delays (60 seconds total waiting).
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

Use a PR and let CI run. Merging to `main` automatically checks, uploads, and deploys the site; Actions → Deploy to GitHub Pages → Run workflow can redeploy manually. The site has no runtime link to site-factory. You can remove the factory App's access to the generated repo after creation; its normal deployment continues to use `GITHUB_TOKEN`.

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

The `create` and `finish` phases are for the trusted workflow, with `GH_TOKEN` supplied by the App action and a runner-local receipt via `--state`. The receipt contains only the configuration and new repository ID. Do not use a PAT or put tokens in commands, remotes, files, or commits. Git authentication uses `gh auth git-credential`, reading the token from the environment, with inherited Git tracing/configuration disabled. Git/HTTP failure reports intentionally omit raw diagnostics that might expose credentials.

Tests cover strict names/domains, DNS variants, escaped and single-pass substitution, complete generated files, a working generated site's checks and tests, dry-run isolation, existing and inaccessible repositories, creation races, identity checks, API errors, domain-before-dispatch ordering, bounded registration retries, safe failure summaries, workflow permissions/triggers, and one-commit initialization against a temporary **local bare Git repository**. No tests create a GitHub repository, dispatch a live workflow, or edit DNS. YAML parsing/security assertions complement `actionlint` when that tool is available. Static checks are sanity checks, not a comprehensive HTML/accessibility validator; manually test keyboard and mobile behavior when extending the starter.

## Troubleshoot and recover

| Symptom | What to check / next step |
| --- | --- |
| Workflow is absent or skipped | Commit it to default `main`; dispatch on `main` in `mamachanko/site-factory`. Other branches/repos are intentionally skipped. |
| App-token step fails | App ID variable, complete PEM secret, installation on the personal account, approved permissions, and selected repository access. Dry run skips these steps entirely. |
| HTTP 401/403 | Token expiry, permissions, App installation, or account Actions/Pages policy. After a create succeeded, verify App access to the new repo before manual recovery. Do not substitute a classic PAT. |
| Repository already exists / create HTTP 422 | Choose another name. A 404 preflight may hide an inaccessible private repo; GitHub's unique-name check still prevents replacement. Creation is never retried automatically. |
| Git push fails | Confirm Contents and Workflows write, App access to the new repo, an empty remote, and account push rules. The factory never force-pushes. Inspect the repository before further work. |
| Pages creation/configuration HTTP 422 | Check Pages eligibility, default branch/initial commit, account policies, domain spelling, domain ownership/verification, or whether another Pages site already claims it. Do not add pointing DNS until the intended domain is confirmed. |
| Dispatch keeps returning 404/422 | Registration retry budget expired. Confirm `main` contains `.github/workflows/deploy.yml`, Actions is enabled, and the refreshed token has Actions write. Once Pages/domain configuration is confirmed, manually dispatch Deploy to GitHub Pages in the new repo. |
| Deployment fails after factory success | Open the new repo's deployment workflow. Check tests, Pages source, environment protection/required reviewers, allowed action policy, and Pages availability. This is isolated from repository creation. |
| Domain does not resolve / certificate pending | Confirm authoritative DNS, exact Host/Value, no conflicting records, successful deployment, and Settings → Pages DNS/TLS state. Wait for propagation; enable Enforce HTTPS when available. |

Live failures are deliberately **not transactional**. The summary reports the last completed operation and failing API/status without dumping tokens, headers, or raw response bodies. It never deletes a repository or rolls back user-visible state automatically. A timeout during creation may have created the repository even if no response arrived; inspect GitHub before retrying.

If creation succeeded but a later step failed, rerunning the factory with that name will refuse to overwrite it. Inspect the new repo and complete the missing work manually: if empty, copy/render the starter and make a normal initial push on `main`; if already populated, fix the failed setting without reseeding. Set Pages source to GitHub Actions, set and confirm the custom domain if needed, then manually dispatch deployment. Only add pointing DNS after that domain confirmation. Alternatively, deliberately remove an abandoned repository yourself after reviewing it, then start a fresh run. The factory provides no destructive recovery command.

## Official references

The implementation follows GitHub's current official guidance and uses current major action releases (checkout/setup-python/setup-node v7, create-github-app-token v3; configure-pages v5, upload-pages-artifact v4, deploy-pages v4):

- [Create a repository for the authenticated user](https://docs.github.com/en/rest/repos/repos#create-a-repository-for-the-authenticated-user) — installation-token support and Administration permission.
- [Install your own GitHub App](https://docs.github.com/en/apps/using-github-apps/installing-your-own-github-app) — selected repositories and automatic access to App-created repositories.
- [Create GitHub App token action](https://github.com/actions/create-github-app-token) — owner/repository scoping, permission inputs, token cleanup.
- [Pages REST API](https://docs.github.com/en/rest/pages/pages) — `build_type: workflow`, Pages creation, and custom-domain settings.
- [Use custom workflows with Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages) — official actions, artifact, permissions, and deployment environment.
- [Manage a Pages custom domain](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site) — configure Pages before DNS, CNAME/A records, and no CNAME file for Actions publishing.
- [Verify a Pages custom domain](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/verifying-your-custom-domain-for-github-pages) — account TXT verification and wildcard risks.
- [Skip workflow runs](https://docs.github.com/en/actions/managing-workflow-runs-and-deployments/managing-workflow-runs/skipping-workflow-runs) — skip the initial push while allowing explicit workflow dispatch.

No Cloudflare, Docker, Terraform, Namecheap API, or other external deployment service is involved.
