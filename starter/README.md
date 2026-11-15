# __SITE_NAME__

__SITE_DESCRIPTION__

Website: __SITE_URL__ (available after deployment and any DNS/TLS setup).

## Local development

```sh
git clone https://github.com/mamachanko/__SITE_NAME__.git
cd __SITE_NAME__
python3 -m http.server 8000 --directory site
```

Open http://localhost:8000. Edit `site/index.html`, `site/styles.css`, and `site/app.mjs`; refresh to see changes. No dependencies, framework, or build step are required. The warm-up riddle provides a small working interaction to replace or extend.

## Checks

Python 3.12+ and Node.js 24+ are needed for checks only:

```sh
python3 scripts/check_site.py
node --check site/app.mjs
node --test tests/*.test.mjs
```

PR CI checks local links, semantic structure, labels, JavaScript syntax, game rules, and form event behavior. Also check keyboard operation and mobile layout in a browser.

## Work with coding agents

Open this repository with Codex or run Claude Code from its root. Both agents should follow [AGENTS.md](AGENTS.md); [CLAUDE.md](CLAUDE.md) points to it. For example: “Turn the warm-up into a mobile-first word game. Keep it buildless and accessible, and test the game rules.”

## Deployment

The Pages workflow checks the site, uploads only `site/`, and deploys on pushes to `main` or Actions → Deploy to GitHub Pages → Run workflow. See that workflow's environment URL for the actual deployment. The factory's initial commit skips push CI so it can configure Pages and the custom domain before explicitly dispatching the first deployment.

In Settings → Pages, the build source should be **GitHub Actions**. Custom domains are configured there through the Pages API by the factory, never through a `CNAME` file. Complete the factory's manual DNS instructions if a domain was supplied. Once DNS and the certificate are ready, enable **Enforce HTTPS**. Domain/certificate propagation may delay availability.

This repository is independent of site-factory. It needs neither factory credentials nor continued App access for deployment. Removing the App's access here does not affect deployment via `GITHUB_TOKEN`.

## Layout

```text
site/                  Public HTML, CSS, and browser JavaScript
scripts/check_site.py  Dependency-free static checks
tests/                 Node.js built-in tests
.github/workflows/     PR CI and Pages deployment
AGENTS.md              Shared coding-agent instructions
CLAUDE.md              Claude Code entry point
```
