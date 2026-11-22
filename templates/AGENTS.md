# Working on __SITE_NAME__

- Build in `site/` and use relative asset URLs so the site works under a GitHub Pages repository path.
- Run `bash scripts/check-site.sh` before opening a pull request. Add the relevant tests to **Check site** when you add dependencies or a build step.
- Use Conventional Commits. Open a pull request and leave the merge to a repository administrator.
- Keep versioned GitHub Action references in local composite actions under `.github/actions/` so Renovate can update them.
