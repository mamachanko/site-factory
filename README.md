# site-factory

## Start a new site

Set up the factory's [GitHub App](#one-time-github-app-setup) before your first run.

1. Create a public repository under `mamachanko` in GitHub Mobile or your browser. Use a lowercase name like `my-site`. Leave it empty or use a template with `main` as its default branch.
2. Open **site-factory → Actions → Workflows → Furnish site**. Tap **Run workflow**, enter the repository name, and submit. [Open Furnish site in your browser](https://github.com/mamachanko/site-factory/actions/workflows/furnish-site.yml).
3. Open the finished run and give Codex the repository link from the summary. Ask Codex to build in `site/` and open a pull request. Merging to `main` deploys the update at the Pages link in the summary.

Furnish site adds a starter page, README, `AGENTS.md`, and workflows for checks, Pages, and Renovate. Existing README and `AGENTS.md` files stay in place.

Pull requests use rebase merges. **Check site** is required, and you can merge your own PRs. Repository administrators can push directly to `main` or bypass PR checks. Every deployment waits for **Check site**. Separate branch rules prevent force pushes and deletion of `main`.

Issues stay on. Wiki, Projects, and Discussions are off. GitHub deletes merged branches.

Renovate runs daily and on demand in each site repo. It opens PRs for npm dependencies and GitHub Action pins in local composite actions. Approve the workflow run on a Renovate PR to start its checks, then merge when green. [GitHub workflow approval](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow#triggering-a-workflow-from-a-workflow)

Furnish site applies these defaults to newly furnished repositories. If initial setup stops, open the failed step and rerun after fixing the problem. Existing Pages must already use GitHub Actions as its source.

## One-time GitHub App setup

If the factory App is installed, open its configuration and select **All repositories**. This gives the App installation access to current and future repositories on the account. Each workflow run requests a short-lived token for the named repository. [Manage installed GitHub Apps](https://github.com/settings/installations)

To install the App for the first time:

1. In the `mamachanko` account, open **Settings → Developer settings → GitHub Apps → New GitHub App**. Set the homepage to this repository. Turn off webhooks and limit installation to this account.
2. Grant read and write access for **Administration**, **Contents**, **Workflows**, **Pages**, and **Actions**. GitHub grants read access to **Metadata** automatically.
3. Install the App on `mamachanko` and select **All repositories**. Generate a private key and keep the PEM private.
4. In this repository, set the Actions variable `SITE_FACTORY_APP_ID` to the App's numeric ID. Create the `site-factory-live` environment and restrict its deployment branches and tags to the branch `main`. Add the private key as the environment secret `SITE_FACTORY_APP_PRIVATE_KEY`.

Furnish site runs from `main` in `mamachanko/site-factory` when triggered by `mamachanko`. Keep `main` protected to control which code can use the App key.

## Site URLs

GitHub Pages serves project sites at `https://gh.mamachanko.com/<repo>/` through the account's user site. Furnish site uses that URL in the starter README and checks it over HTTPS before reporting it in the run summary. [GitHub Pages shared domains](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/about-custom-domains-and-github-pages#using-a-custom-domain-across-multiple-repositories)

If a repo already has its own Pages domain under `mamachanko.com` or `maxbrauer.com`, Furnish site uses that domain for its link and HTTPS check. [GitHub Pages custom domains](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site)

## Develop site-factory

The factory runs `scripts/factory.py` on GitHub Actions. The files in `templates/` mirror their paths in each site repository. Each site's deployment workflow publishes `site/` with its own `GITHUB_TOKEN`.

Use Python 3.12+, Git, and GitHub CLI to work on the factory. Tests use mocked GitHub responses and local bare Git repositories.

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements-dev.txt
python3 -m unittest discover -s tests -v
actionlint .github/workflows/*.yml templates/.github/workflows/*.yml
```

The workflows pin actions to full upstream commit SHAs. The comments identify the major versions.
