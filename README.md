# site-factory

## Start a new site

Set up the factory's [GitHub App](#one-time-github-app-setup) before your first run.

1. Create a public repository under `mamachanko` in GitHub Mobile or your browser. Use a lowercase name like `my-site`. Leave it empty or use a template with `main` as its default branch.
2. Open **site-factory → Actions → Workflows → Furnish site**. Tap **Run workflow**, enter the repository name, and submit. [Open Furnish site in your browser](https://github.com/mamachanko/site-factory/actions/workflows/furnish-site.yml).
3. Open the finished run and give Codex the repository link from the summary. Ask Codex to build in `site/` and open a pull request. Merging to `main` deploys the update at the Pages link in the summary.

Furnish site adds `site/index.html` and `.github/workflows/deploy.yml` where missing, enables GitHub Pages, and protects `main`. You can merge your own pull requests. The ruleset blocks branch deletion and force pushes.

If setup stops, check the failed step and rerun Furnish site after fixing the problem. An existing deployment workflow must match the factory template. An existing Pages site must already use GitHub Actions as its source.

## One-time GitHub App setup

If the factory App is installed, open its configuration and select **All repositories**. This gives the App installation access to current and future repositories on the account. Each workflow run requests a short-lived token for the named repository. [Manage installed GitHub Apps](https://github.com/settings/installations)

To install the App for the first time:

1. In the `mamachanko` account, open **Settings → Developer settings → GitHub Apps → New GitHub App**. Set the homepage to this repository. Turn off webhooks and limit installation to this account.
2. Grant read and write access for **Administration**, **Contents**, **Workflows**, **Pages**, and **Actions**. GitHub grants read access to **Metadata** automatically.
3. Install the App on `mamachanko` and select **All repositories**. Generate a private key and keep the PEM private.
4. In this repository, set the Actions variable `SITE_FACTORY_APP_ID` to the App's numeric ID. Create the `site-factory-live` environment and restrict its deployment branches and tags to the branch `main`. Add the private key as the environment secret `SITE_FACTORY_APP_PRIVATE_KEY`.

Furnish site runs from `main` in `mamachanko/site-factory` when triggered by `mamachanko`. Keep `main` protected to control which code can use the App key.

## Use your own domain

A custom domain on the account's GitHub Pages user site also applies to project sites. For example, a project named `my-site` can appear at `https://mamachanko.com/my-site/`. [GitHub Pages custom domains](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/about-custom-domains-and-github-pages#using-a-custom-domain-across-multiple-repositories)

To give one project a different hostname, verify the domain on GitHub, then configure the project's **Settings → Pages** and its DNS. Furnish site preserves existing Pages domains under `mamachanko.com` and `maxbrauer.com`. [Configure a Pages custom domain](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site)

## Develop site-factory

The factory runs `scripts/factory.py` on GitHub Actions. It copies the two files in `templates/` into each site repository. Each site's deployment workflow publishes `site/` with its own `GITHUB_TOKEN`.

Use Python 3.12+, Git, and GitHub CLI to work on the factory. Tests use mocked GitHub responses and local bare Git repositories.

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements-dev.txt
python3 -m unittest discover -s tests -v
actionlint .github/workflows/*.yml templates/deploy.yml
```

The workflows pin actions to full upstream commit SHAs. The comments identify the major versions.
