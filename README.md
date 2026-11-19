# Site Factory

## Create a site

Publish a starter site at `https://mamachanko.github.io/my-site/`. Replace `my-site` with your repository name. If you haven't installed the Site Factory App, [set up the App](#set-up-the-github-app) first.

1. Create an empty public repository in the `mamachanko` account. Leave **Add README** off. Choose no `.gitignore` or license.
2. Open **Configure** for the Site Factory App. Add the new repository under **Only select repositories** and click **Save**. [Installed GitHub Apps](https://github.com/settings/installations)
3. In `site-factory`, open **Actions → Initialize site → Run workflow** on `main`. Enter the name in `repository_name`. Leave `custom_domain` blank, clear `dry_run`, and click **Run workflow**.
4. Open the deployment workflow linked in the **Initialize site** summary. When **Deploy to GitHub Pages** succeeds, open the Pages URL.
5. Open the new repository in Codex. Start with `AGENTS.md`. Pushes to `main` publish site updates.

## Preview the setup

Leave `dry_run` selected and run **Initialize site**. The summary shows the planned steps and expected Pages URL. A dry run validates inputs and renders the starter locally. The live run checks App access and Pages settings.

## Start from a template

Create the repository from a template whose root contains an exact copy of `starter/` from the factory revision you plan to run. Include dotfiles and preserve file modes. Use `main` as the sole branch and leave tags out of the template. Then follow steps 2 through 5 in [Create a site](#create-a-site). Site Factory fills in the site name and description in a new commit on `main`.

## Use a custom domain

1. In `mamachanko`'s personal **Settings → Pages**, add the site hostname or its immediate parent. Copy the TXT record GitHub shows to your DNS provider, then return to GitHub and click **Verify**. Keep the verification record. For example, verifying `mamachanko.com` covers `games.mamachanko.com`. Verify `games.mamachanko.com` or `word.games.mamachanko.com` to use `word.games.mamachanko.com`. [Verify a Pages domain](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/verifying-your-custom-domain-for-github-pages)
2. Enter the hostname in `custom_domain` when you run **Initialize site**. Confirm the hostname in the new repository's **Settings → Pages** before adding records that point to Pages.
3. Add the records from the factory summary at your authoritative DNS provider. Review existing records for the hostname before replacing them. At Namecheap, open **Domain List → Manage → Advanced DNS → Host Records**. Use the host and value from the summary. Use records for the exact hostname and avoid wildcard records.
4. When GitHub issues the certificate, enable **Enforce HTTPS** in the repository's Pages settings. [Manage a Pages custom domain](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site)

To retire the site, remove the records that point to Pages before detaching the domain.

## Work on a site locally

Clone the site repository and run `python3 -m http.server 8000 --directory site` from its root. Open `http://localhost:8000`. The site's `AGENTS.md` lists the checks to run before opening a pull request.

To publish an update, merge to `main`. To redeploy the current version, run **Actions → Deploy to GitHub Pages → Run workflow** in the site repository. After initialization succeeds, you can remove the site's App grant. The site deploys with its own `GITHUB_TOKEN`.

## Set up the GitHub App

For an existing App installation, grant access to each new site in **Installed GitHub Apps**. Use the existing App ID and environment secret.

1. In `mamachanko`'s personal settings, open **Developer settings → GitHub Apps → New GitHub App**. Use a name such as `mamachanko-site-factory` and set the homepage to the `site-factory` repository URL.
2. Clear **Webhook → Active**. Set installation availability to **Only on this account**. Leave callback URLs, account permissions, and organization permissions unset.
3. Set these repository permissions.

   | Permission | Level | Purpose |
   | --- | --- | --- |
   | Administration | Read and write | Set the default branch and configure Pages |
   | Contents | Read and write | Read Git state and push starter commits |
   | Workflows | Read and write | Add the starter's workflow files |
   | Pages | Read and write | Enable Pages and set its custom domain |
   | Actions | Read and write | Start the first deployment |
   | Metadata | Read-only, automatic | Read repository metadata |

4. Create the App. Copy its numeric **App ID** and generate a private key.
5. Open **Install App** and install the App on `mamachanko`. Choose **Only select repositories** and select `site-factory`. Approve any future permission changes in the installation settings. [Install a GitHub App](https://docs.github.com/en/apps/using-github-apps/installing-your-own-github-app)
6. In `site-factory`, open **Settings → Environments** and create `site-factory-live`. Under **Deployment branches and tags**, choose **Selected branches and tags**. Add a **Branch** rule for `main`.
7. Add the complete downloaded PEM to that environment as `SITE_FACTORY_APP_PRIVATE_KEY`. Include its header, footer, and line breaks. If you moved the secret from the repository to the environment, remove the repository copy.
8. Open **Settings → Secrets and variables → Actions → Variables**. Add the numeric App ID as `SITE_FACTORY_APP_ID`.
9. Enable GitHub Actions and set the factory's default branch to `main`. Check that your account policy permits Actions and Pages on the site repositories and allows the Actions used by the factory and starter.

## Troubleshoot and recover

| Symptom | What to check |
| --- | --- |
| **Initialize site** is absent or skipped | Open **Actions** in `mamachanko/site-factory` and run the workflow on `main`. |
| The App token step fails | Check the App ID, the PEM in `site-factory-live`, the approved permissions, and the target repository's App grant. |
| GitHub returns `401` or `403` | Read the error category and GitHub request ID in the summary if present. Check App access and account Actions or Pages policy. |
| The target is ineligible | Confirm that the repository is public and belongs to `mamachanko`. Check its refs and files against the [eligible targets](#eligible-targets). |
| The Git push fails | Check Contents and Workflows write permissions, the App grant, push rules, and concurrent edits. |
| Pages returns `422` | Check Pages eligibility, `main`, domain verification, and whether another site uses the domain. |
| Dispatch returns `404` or `422` after retrying | Check that deployment is enabled and `main` contains `.github/workflows/deploy.yml`. Confirm Pages settings, then run **Deploy to GitHub Pages** manually. |
| The site fails to publish | Open the site's **Deploy to GitHub Pages** run. Check its tests, Pages source, and environment rules. |
| The domain or certificate is pending | Check the authoritative DNS records and the site's **Settings → Pages**. Enable **Enforce HTTPS** when the certificate is ready. |

Inspect the target and the failed step. To resume, select **Re-run all jobs** on the original factory run. GitHub uses the same factory revision and inputs. If someone has edited the site, finish the remaining settings or deployment steps in the site repository. A retry after an uncertain dispatch can queue a second deploy. The site workflow runs those deployments one at a time.

## Factory inputs

| Input | Accepted values |
| --- | --- |
| `repository_name` | An existing public `mamachanko` repository. Use 1 to 63 lowercase ASCII letters or digits, with single hyphens between groups. `site-factory` is reserved. |
| `description` | Optional starter site text. Use one line of up to 350 characters without control characters. |
| `custom_domain` | Blank for the default Pages domain, or a lowercase hostname under `mamachanko.com` or `maxbrauer.com`, including either apex. Hostnames may have up to 253 characters and 63 characters per label. |
| `dry_run` | Selected by default. Clear it to initialize and dispatch the first deployment. |

The summary uses `https://mamachanko.github.io/<repository_name>/` for the default Pages URL. If the account has a Pages custom domain, check the actual URL in the site's **Settings → Pages** or deployment run.

For a subdomain, the factory reports a CNAME to `mamachanko.github.io`. For `word.games.maxbrauer.com`, the Namecheap host is `word.games` in the `maxbrauer.com` zone. For an apex, it reports four A records at `@`. The values are `185.199.108.153`, `185.199.109.153`, `185.199.110.153`, and `185.199.111.153`. The suggested TTL is **Automatic**.

## How initialization works

[Initialize site](.github/workflows/initialize-site.yml) runs in `mamachanko/site-factory` on `main`. The plan job runs without App credentials. After planning succeeds, the live job uses `site-factory-live` to mint one token scoped to the target. The App action revokes the token at the end of the job. The factory runs at most one initialization per target at a time. Restrict write access and protect `main` to control which code can use the App credentials.

### Eligible targets

The factory accepts a public repository in `mamachanko` with one of these Git states:

- An empty repository.
- The exact bundled `starter/` tree on `main`.
- The exact rendered starter on `main` for the same factory revision and inputs.

For an initialized target, `main` must be the sole ref. The factory compares paths, contents, and modes before writing to Git. It refuses a legacy Pages source or a configured custom domain that differs from the requested domain. A blank domain request conflicts with an existing custom domain.

### Setup and deployment

[`scripts/factory.py`](scripts/factory.py) checks identity, Git refs, and Pages settings. It adds a starter commit for an empty or template repository. An exact rendered starter proceeds directly to settings. Pushes use Git's normal protections. The starter commit uses `[skip ci]` so the factory can turn on Pages before deployment. Avoid edits to the target during initialization. Git refs and Pages settings have separate update operations.

The factory sets `main` as the default branch where needed, enables Pages with `build_type: workflow`, and confirms the requested domain. It dispatches `.github/workflows/deploy.yml` on `main` and prints a link to the site's workflow. A successful factory run means GitHub accepted the dispatch. Check the site's deploy job for publication. The factory reports DNS records for you to apply.

The [starter files](starter/) include the buildless site, `AGENTS.md`, a local development guide, checks, and workflows. The deploy workflow tests the site and uploads `site/`. It uses `contents: read` and `pages: read` for checks, then `pages: write` and `id-token: write` for deployment.

## Develop and test the factory

Use Python 3.12 or later, Node.js 24 or later, Git, and `gh`. The factory uses the Python standard library. Workflow tests use PyYAML.

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements-dev.txt
python3 -m unittest discover -s tests -v
python3 starter/scripts/check_site.py
node --check starter/site/app.mjs
node --test starter/tests/*.test.mjs
```

Run an offline plan with `REPOSITORY_NAME=my-site python3 scripts/factory.py plan`. The live job runs `python3 scripts/factory.py initialize` with `GH_TOKEN` from the App action. Git uses `gh auth git-credential`, with inherited Git configuration and tracing disabled. Keep credentials in the job environment.

Tests use mocked GitHub responses and temporary local Git repositories. Use `actionlint` to check workflow syntax when available. Verify a live App grant and Pages publication with a public test repo before relying on the workflow. Use keyboard and mobile checks when extending the site starter.
