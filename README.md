# site-factory

## Start a new site

Set up the factory's [GitHub App](#one-time-github-app-setup) before your first run.

1. Create a public repository under `mamachanko` in the GitHub app or browser. Use a lowercase name like `my-site`. Leave it empty or use a template with `main` as its default branch.
2. In GitHub Mobile, open **site-factory → Actions → Workflows → Furnish site**. Tap **Run workflow**, enter the repository name, and submit. You can also open [Furnish site in your browser](https://github.com/mamachanko/site-factory/actions/workflows/furnish-site.yml).
3. Open the finished run for your repository. Copy the repo link from the summary and give it to Codex. Ask Codex to build in `site/` and open a pull request. Merging to `main` deploys the update at the Pages link in the summary.

**Furnish site** adds `site/index.html` and `.github/workflows/deploy.yml` where missing. It preserves existing files, enables GitHub Actions as the Pages source, and puts a ruleset on `main`. You can merge your own pull requests. The ruleset blocks branch deletion and force pushes.

If Furnish site stops, open the failed step and rerun it after fixing the reported problem. An existing deployment workflow must match the Furnish site template. An existing Pages site must already use GitHub Actions as its source.

### Existing App installation

Open the factory App's configuration and select **All repositories** once. This gives the App installation access to future repositories on the account. Each Furnish site run requests an expiring token for the public repository you enter. [Manage installed GitHub Apps](https://github.com/settings/installations)

## One-time GitHub App setup

1. In the **mamachanko personal account**, open Settings → Developer settings → GitHub Apps → New GitHub App. Give it a distinct name such as `mamachanko-site-factory` and set its homepage to this repository's URL.
2. Disable **Webhook → Active**; this factory does not use webhooks. No callback URL, OAuth authorization flow, user permissions, or organization permissions are needed. Set installation availability to **Only on this account**.
3. Set exactly these **Repository permissions**. The UI's “Read and write” corresponds to API permission `write`:

   | Permission | Level | Purpose |
   | --- | --- | --- |
   | Administration | Read and write | Create repositories, set the default branch, configure Pages and rulesets |
   | Contents | Read and write | Read repository state and push the initial commit |
   | Workflows | Read and write | Include `.github/workflows` in the initial commit |
   | Pages | Read and write | Enable workflow-based Pages and set its custom domain |
   | Actions | Read and write | Dispatch the initial deployment workflow |
   | Metadata | Read-only (automatic) | GitHub's mandatory metadata access |

   Do not grant unrelated permissions, account permissions, or a classic PAT.
4. Create the App. Copy its **App ID** and generate a **private key**. Keep the downloaded PEM private.
5. Under **Install App**, install it on **mamachanko** and choose **All repositories**. This includes repositories you create later. If App permissions change, approve the update in the installation.
6. In **site-factory → Settings → Environments**, create `site-factory-live`. Under **Deployment branches and tags**, choose **Selected branches and tags** and add a **Branch** rule for `main`. Then add an **Environment secret** named `SITE_FACTORY_APP_PRIVATE_KEY` with the entire PEM, including header/footer and line breaks. If upgrading an existing setup, remove the repository-level copy of the secret after setting up the restricted environment.
7. In **site-factory → Settings → Secrets and variables → Actions → Variables**, add the App's numeric ID as the repository variable `SITE_FACTORY_APP_ID`.

8. Enable GitHub Actions in site-factory. Keep the repository's default branch as **main** and make these files available on that branch before running the workflow. Allow the official `actions/*` used here under any Actions policy. The generated repositories also need Actions and Pages allowed by account policy.

Both workflows use the `site-factory-live` environment on `main`. Protect `main` and restrict write access to control which code can use the App key. PR CI uses a read-only `GITHUB_TOKEN`. Published sites deploy with their own `GITHUB_TOKEN`.

## Create site workflow

**Create site** creates the repository for you. Its full starter includes a puzzle, CI, tests, and repository instructions. It accepts an optional custom domain. The workflow first requests Administration write access across the App installation. After creation, it requests a token scoped to the new repository for setup and deployment.

**Dry run is the default.** It validates inputs and shows the proposed repo, starter, and DNS records. It runs without App credentials or network requests.

### Verify a custom domain

In **mamachanko → personal Settings → Pages → Add a domain**, verify `mamachanko.com` and `maxbrauer.com` if you plan to use both. GitHub displays an account-specific TXT record:

```text
Type: TXT
Host: _github-pages-challenge-mamachanko
Value: <the exact verification value supplied by GitHub>
```

At Namecheap, choose the relevant domain → Manage → Advanced DNS → Host Records → Add New Record. Add GitHub's exact TXT host/value, return to GitHub, and click Verify. Keep the TXT record after verification. Before pointing DNS to Pages, confirm that the exact hostname or its immediate parent is verified in your personal Pages settings. For example, `maxbrauer.com` verification covers `games.maxbrauer.com`, and `word.games.maxbrauer.com` needs verification of `games.maxbrauer.com` or the exact hostname. Remove the Pages-pointing DNS record before retiring or detaching a site, and avoid wildcard records.

If the domain uses third-party nameservers, edit records at the **authoritative DNS provider**, even if Namecheap is the registrar. The factory never contacts Namecheap or changes any DNS record.

### Run Create site

1. Open **Actions → Create site → Run workflow** on `main`.
2. Enter the repository name. The description and custom domain are optional.
3. Run with **dry_run** selected to preview the changes. Clear **dry_run** and run again to create the repository.
4. Follow **Actions → Deploy to GitHub Pages** in the new repository. If you entered a custom domain, add the DNS record from the factory's job summary after it confirms the domain in Pages settings.

### Input rules and DNS variants

- Names are deliberately stricter than GitHub's general naming rules: 1–63 lowercase ASCII letters/digits, with single hyphens between groups. No uppercase, underscores, dots, slashes, whitespace, shell syntax, or leading/trailing/repeated hyphens. `site-factory` is reserved. There is no owner input.
- Descriptions are optional, one line, at most 350 characters, without control characters. Values travel through environment variables, never interpolated shell commands. Rendered description text is HTML-escaped and never inserted into workflows or JavaScript.
- Domains must be lowercase ASCII DNS hostnames, at most 253 characters and 63 per label. Only `mamachanko.com`, `maxbrauer.com`, and dot-separated subdomains of those exact domains are accepted. URLs, paths, ports, wildcards, trailing dots, malformed labels, and suffix tricks are rejected.
- `word.games.maxbrauer.com` produces a CNAME with Namecheap Host `word.games` and Value `mamachanko.github.io` in zone `maxbrauer.com`.
- Either allowed apex produces four separate **A** records, Host **@**, TTL **Automatic**, with values **185.199.108.153**, **185.199.109.153**, **185.199.110.153**, and **185.199.111.153**. Review existing apex records before replacing them. The factory does not add `www`, wildcard records, or optional IPv6 records. Subdomains use a CNAME, not these A records.

### Work on the Create site starter

```sh
git clone https://github.com/mamachanko/puzzles.git
cd puzzles
python3 -m http.server 8000 --directory site
```

Open http://localhost:8000. Start Codex in this repository, or run Claude Code from its root. `AGENTS.md` supplies the shared instructions and `CLAUDE.md` points to it. A useful first task is: “Replace the warm-up with a mobile-first word game. Keep the site buildless, preserve keyboard access and status feedback, and add tests for the game rules.”

Use a PR and let CI run. Merging to `main` automatically checks, uploads, and deploys the site; Actions → Deploy to GitHub Pages → Run workflow can redeploy manually. The new repository deploys on its own using `GITHUB_TOKEN`.

### Troubleshoot Create site

| Symptom | What to check / next step |
| --- | --- |
| Workflow is absent or skipped | Commit it to default `main`; dispatch on `main` in `mamachanko/site-factory`. Other branches/repos are intentionally skipped. |
| App-token step fails | App ID variable, complete PEM in the `site-factory-live` environment, installation on the personal account, approved permissions, and access to the repository. |
| HTTP 401/403 | Token expiry, permissions, App installation, or account Actions/Pages policy. After a create succeeded, verify App access to the new repo before manual recovery. Do not substitute a classic PAT. |
| Repository already exists / create HTTP 422 | Choose another name. A 404 preflight may hide an inaccessible private repo; GitHub's unique-name check still prevents replacement. Creation is never retried automatically. |
| Git push fails | Confirm Contents and Workflows write, App access to the new repo, an empty remote, and account push rules. The factory never force-pushes. Inspect the repository before further work. |
| Pages creation/configuration HTTP 422 | Check Pages eligibility, default branch/initial commit, account policies, domain spelling, domain ownership/verification, or whether another Pages site already claims it. Do not add pointing DNS until the intended domain is confirmed. |
| Dispatch keeps returning 404/422 | Registration retry budget expired. Confirm `main` contains `.github/workflows/deploy.yml`, Actions is enabled, and the refreshed token has Actions write. Once Pages/domain configuration is confirmed, manually dispatch Deploy to GitHub Pages in the new repo. |
| Deployment fails after factory success | Open the new repo's deployment workflow. Check tests, Pages source, environment protection/required reviewers, allowed action policy, and Pages availability. This is isolated from repository creation. |
| Domain does not resolve / certificate pending | Confirm authoritative DNS, exact Host/Value, no conflicting records, successful deployment, and Settings → Pages DNS/TLS state. Wait for propagation; enable Enforce HTTPS when available. |

Live failures are deliberately **not transactional**. The summary reports the last completed operation and failing API/status without dumping tokens, headers, or raw response bodies. It never deletes a repository or rolls back user-visible state automatically. A timeout during creation may have created the repository even if no response arrived; inspect GitHub before retrying.

If creation succeeded but a later step failed, rerunning the factory with that name will refuse to overwrite it. Inspect the new repo and complete the missing work manually: if empty, copy/render the starter and make a normal initial push on `main`; if already populated, fix the failed setting without reseeding. Set Pages source to GitHub Actions, set and confirm the custom domain if needed, then manually dispatch deployment. Only add pointing DNS after that domain confirmation. Alternatively, deliberately remove an abandoned repository yourself after reviewing it, then start a fresh run. The factory provides no destructive recovery command.

## Develop and test site-factory

Furnish site uses `scripts/controller.py` and `templates/`. Create site uses `scripts/factory.py` and `starter/`. The workflows share repository and domain validation.

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

Tests use mocked GitHub responses and local bare Git repositories. They cover both workflows, site creation and furnishing, deployment results, and retry behavior. Run `actionlint .github/workflows/*.yml starter/.github/workflows/*.yml templates/deploy.yml` to lint the workflow files and the Furnish site template.

## Official references

The workflows pin actions to full upstream commit SHAs. The comments beside each pin identify the major release line. Review the upstream release when updating a pin.

- [Create a repository for the authenticated user](https://docs.github.com/en/rest/repos/repos#create-a-repository-for-the-authenticated-user) — installation-token support and Administration permission.
- [Install your own GitHub App](https://docs.github.com/en/apps/using-github-apps/installing-your-own-github-app) — selected repositories and automatic access to App-created repositories.
- [Create GitHub App token action](https://github.com/actions/create-github-app-token) — owner/repository scoping, permission inputs, token cleanup.
- [Pages REST API](https://docs.github.com/en/rest/pages/pages) — `build_type: workflow`, Pages creation, and custom-domain settings.
- [Use custom workflows with Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages) — official actions, artifact, permissions, and deployment environment.
- [Manage a Pages custom domain](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site) — configure Pages before DNS, CNAME/A records, and no CNAME file for Actions publishing.
- [Verify a Pages custom domain](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/verifying-your-custom-domain-for-github-pages) — account TXT verification and wildcard risks.
- [Skip workflow runs](https://docs.github.com/en/actions/managing-workflow-runs-and-deployments/managing-workflow-runs/skipping-workflow-runs) — skip the initial push while allowing explicit workflow dispatch.
