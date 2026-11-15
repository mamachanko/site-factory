# Development guide

This is an independent, vanilla HTML/CSS/JavaScript website. No build or install is needed to serve it. Published files live in `site/`; keep private files, tests, scripts, and credentials outside it.

## Work locally

Run `python3 -m http.server 8000 --directory site` and open http://localhost:8000. Use relative asset URLs (`./styles.css`) so both repository-path Pages URLs and custom domains work. JavaScript uses browser ES modules. Keep game rules as pure exported functions and wire DOM interactions separately in `site/app.mjs`.

## Verify changes

Use Python 3.12+ and Node.js 24+ (only for tests):

```sh
python3 scripts/check_site.py
node --check site/app.mjs
node --test tests/*.test.mjs
```

Add meaningful tests for game rules and changed interactions. The static checker catches broken local links/assets, missing landmarks, duplicate IDs, and unlabeled fields; it is not a full HTML validator or accessibility audit. Manually check keyboard operation, focus, feedback announcements, and narrow/mobile layouts. CI runs these same checks on PRs; deployment repeats checks before upload.

## Extend the game

Preserve semantic landmarks, visible labels, native buttons, keyboard access, and live status feedback. Do not rely on color alone. Use `textContent` for user-provided text. Keep touch targets at least 44px and honor reduced motion if adding animations. Do not introduce a framework or mandatory build without a concrete need. Document any new tooling and testing steps here and in README.

## Deploy

Pushes to `main` and manual dispatch run `.github/workflows/deploy.yml`. It publishes only `site/` through official Pages actions. No deployment secrets are needed. Never add factory credentials or a `CNAME` file: custom domains belong in Settings → Pages. Do not change DNS automatically.
