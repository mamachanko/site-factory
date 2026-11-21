# Site Factory controller proposal

Create a GitHub repo on your phone. Then ask the controller to furnish it. The controller returns a repo link and a live Pages URL. You can hand the repo to an agent and ask it to build the site. A merge to `main` publishes the update.

## Proposed change

One PR from `main` adds the furnish operation. It can reuse the Git and Pages setup in [PR #4](https://github.com/mamachanko/site-factory/pull/4). PR #4 is independent and can stay open while the proposal is reviewed. The likely files are `scripts/factory.py`, the deployment workflow under `starter/`, the factory tests, and `README.md`.

- [ ] Accept one repository name or link. Use the owner's existing GitHub CLI login for the first version. Check repository ownership, access, and content before setup. The owner creates the repository in GitHub.
- [ ] Add a minimal web page and a Pages workflow where those files are missing. Preserve existing files and report collisions. Seed `main` before applying branch protection.
- [ ] Set the default branch and the agreed repository settings. Apply a ruleset to `main`. Proposed defaults require a pull request and block branch deletion and force pushes. A solo owner can merge without a second reviewer. [Rulesets API](https://docs.github.com/en/rest/repos/rules#create-a-repository-ruleset)
- [ ] Enable GitHub Actions as the Pages source, dispatch the first deployment, wait for it to succeed, and return the live URL. A repeat request should resume missing setup and preserve an existing site's content and unrelated settings. [Pages API](https://docs.github.com/en/rest/pages/pages#create-a-github-pages-site)

## Acceptance test

- [ ] Run local tests for an empty repository, existing files, and a retry after partial setup. Check that the controller refuses a target outside the intended account.
- [ ] With the owner's approved GitHub access and permission to publish, run the controller on one disposable public repo the owner creates. Use its default Pages URL for this test.
- [ ] Read back the default branch, active ruleset, and Pages source. Open the returned URL and confirm it serves the starter page.
- [ ] Open a PR with a visible page change, merge it through the ruleset, and confirm the new content appears at that same URL. The operator reviews the result before merge of the controller PR.

The live test requires a working owner login and approval to publish. The existing initializer's empty-repo test covers starter and Pages setup with mocked GitHub responses. Verify the ruleset and public deployment on GitHub during the acceptance test.
