#!/usr/bin/env python3
"""Furnish an existing personal repository using the stored GitHub CLI login."""
import argparse
import html
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

import factory

WORKFLOW = ".github/workflows/deploy.yml"
RULESET_NAME = "site-factory-main"
SHA = re.compile(r"[0-9a-f]{40}")


def parse_repository(value):
    if value.startswith("https://github.com/"):
        value = value[len("https://github.com/"):].removesuffix("/").removesuffix(".git")
    if "/" in value:
        owner, value = value.split("/", 1)
        if owner != factory.OWNER:
            raise factory.FactoryError(f"Repository must belong to {factory.OWNER}.")
    return factory.Site(value)


def stored_token():
    env = {k: v for k, v in os.environ.items()
           if k not in {"GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN", "GH_HOST"}}
    env["GH_PROMPT_DISABLED"] = "1"
    try:
        result = subprocess.run(["gh", "auth", "token", "--hostname", "github.com"],
                                env=env, check=True, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        raise factory.FactoryError("A stored github.com login is required; run gh auth login first.") from None
    token = result.stdout.strip()
    if not token or any(c.isspace() for c in token):
        raise factory.FactoryError("GitHub CLI did not return a usable stored login.")
    return token


def starter_files(site):
    directory = factory.ROOT / "templates"
    return {"site/index.html": (directory / "index.html").read_text().replace("__SITE_NAME__", html.escape(site.name)),
            WORKFLOW: (directory / "deploy.yml").read_text()}


def target_repository(api, site, repository_id=None, *, require_main=True):
    repo = api.request("GET", f"/repos/{site.repository}")
    if (repo.get("full_name") != site.repository or repo.get("owner", {}).get("login") != factory.OWNER
            or repo.get("owner", {}).get("type") != "User" or repo.get("private") is not False
            or repo.get("archived") is not False or repo.get("disabled") is not False
            or repo.get("permissions", {}).get("admin") is not True
            or not isinstance(repo.get("id"), int)
            or (repository_id is not None and repo["id"] != repository_id)):
        raise factory.FactoryError("Repository must be public, active, admin-accessible, and owned by mamachanko; identity must remain unchanged.")
    if require_main and repo.get("default_branch") != "main":
        raise factory.FactoryError("The existing repository default branch must be main.")
    return repo


def ruleset_payload():
    return {"name": RULESET_NAME, "target": "branch", "enforcement": "active", "bypass_actors": [],
            "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
            "rules": [{"type": "deletion"}, {"type": "non_fast_forward"},
                      {"type": "pull_request", "parameters": {
                          "allowed_merge_methods": ["merge", "squash", "rebase"],
                          "require_extra_approval_for_unattributed_changes": False,
                          "required_approving_review_count": 0, "dismiss_stale_reviews_on_push": False,
                          "require_code_owner_review": False, "require_last_push_approval": False,
                          "required_review_thread_resolution": False}}]}


def compatible_ruleset(value):
    expected = ruleset_payload()
    if any(value.get(key) != expected[key] for key in ("name", "target", "enforcement", "conditions", "bypass_actors")):
        return False
    rules = value.get("rules", [])
    if len(rules) != len(expected["rules"]):
        return False
    for wanted in expected["rules"]:
        matches = [rule for rule in rules if rule.get("type") == wanted["type"]]
        if len(matches) != 1:
            return False
        actual = matches[0].get("parameters", {})
        required = wanted.get("parameters", {})
        if any((sorted(actual.get(key, [])) != sorted(val) if key == "allowed_merge_methods"
                else actual.get(key) != val) for key, val in required.items()):
            return False
        # REST may add empty/default fields to a rule created by this controller.
        if any(val not in (False, None, [], {}) for key, val in actual.items() if key not in required):
            return False
    return True


def existing_ruleset(api, base):
    found = []
    for page in range(1, 101):
        items = api.request("GET", f"{base}/rulesets?includes_parents=false&per_page=100&page={page}")
        found.extend(item for item in items if item.get("name") == RULESET_NAME)
        if len(items) < 100:
            break
    else:
        raise factory.FactoryError("Too many rulesets to safely inspect.")
    if len(found) > 1:
        raise factory.FactoryError("Multiple site-factory-main rulesets exist; inspect before continuing.")
    if not found:
        return None
    rule = api.request("GET", f"{base}/rulesets/{found[0]['id']}")
    if not compatible_ruleset(rule):
        raise factory.FactoryError("Existing site-factory-main ruleset is incompatible; nothing will overwrite it.")
    return rule


def allowed_url(value):
    if not isinstance(value, str):
        raise factory.FactoryError("Pages did not report a usable HTTPS URL.")
    parts = urllib.parse.urlsplit(value)
    if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
            or parts.port is not None or parts.query or parts.fragment or any(c.isspace() for c in value)):
        raise factory.FactoryError("Pages URL must be HTTPS on an allowed host.")
    if parts.hostname != f"{factory.OWNER}.github.io":
        factory.Site("pages-check", domain=parts.hostname)
    return value


def pages_state(api, base):
    try:
        pages = api.request("GET", base + "/pages")
    except factory.APIError as error:
        if error.status == 404:
            return None
        raise
    if pages.get("build_type") != "workflow":
        raise factory.FactoryError("Existing Pages must already use GitHub Actions; refusing to replace its source.")
    if pages.get("cname"):
        factory.Site("pages-check", domain=pages["cname"])
    allowed_url(pages.get("html_url"))
    return pages


def seed_repository(site, files, token, *, remote=None, check=lambda: None, require_main_only=False):
    """Add missing blobs using a temporary Git index; never check out remote content."""
    env = {key: val for key, val in os.environ.items() if not key.startswith(("GIT_", "GH_", "GITHUB_"))}
    env.update(GH_TOKEN=token, GH_HOST="github.com", GH_PROMPT_DISABLED="1", GIT_TERMINAL_PROMPT="0",
               GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_AUTHOR_NAME="site-factory", GIT_AUTHOR_EMAIL="site-factory@users.noreply.github.com",
               GIT_COMMITTER_NAME="site-factory", GIT_COMMITTER_EMAIL="site-factory@users.noreply.github.com")
    with tempfile.TemporaryDirectory(prefix="site-factory-furnish-") as directory:
        def git(*args, content=None):
            try:
                return subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "credential.helper=",
                                       "-c", "http.followRedirects=false",
                                       "-c", "credential.helper=!gh auth git-credential", *args],
                                      cwd=directory, env=env, input=content, check=True,
                                      capture_output=True, timeout=90).stdout
            except (OSError, subprocess.SubprocessError):
                raise factory.FactoryError("Git furnishing failed; inspect the repository before retrying. No force push was attempted.") from None
        git("init", "--template=", "--initial-branch=main")
        git("remote", "add", "origin", remote or f"https://github.com/{site.repository}.git")
        def remote_refs():
            return dict(line.split(b"\t", 1)[::-1] for line in git("ls-remote", "--refs", "origin").splitlines())
        refs = remote_refs()
        if require_main_only and refs.keys() - {b"refs/heads/main"}:
            raise factory.FactoryError("The existing repository default branch must be main.")
        parent = refs.get(b"refs/heads/main")
        if refs and not parent:
            raise factory.FactoryError("Nonempty repository has no main branch; refusing to initialize it.")
        entries = {}
        if parent:
            if not SHA.fullmatch(parent.decode()):
                raise factory.FactoryError("Remote returned an invalid main SHA.")
            git("fetch", "--no-tags", "origin", parent.decode())
            git("read-tree", parent.decode())
            for entry in git("ls-tree", "-rz", parent.decode()).split(b"\0"):
                if entry:
                    info, path = entry.split(b"\t", 1)
                    entries[path.decode("utf-8", errors="surrogateescape")] = info.split()
        else:
            git("read-tree", "--empty")
        changed = False
        for path, content in files.items():
            pieces = Path(path).parts
            if any("/".join(pieces[:index]) in entries for index in range(1, len(pieces))):
                raise factory.FactoryError(f"A file or symlink blocks starter path {path}.")
            if path in entries:
                mode, kind, blob = entries[path]
                if mode not in (b"100644", b"100755") or kind != b"blob":
                    raise factory.FactoryError(f"Existing {path} must be a regular file.")
                if path == WORKFLOW and git("cat-file", "blob", blob.decode()) != content.encode():
                    raise factory.FactoryError("Existing deploy.yml is unknown; refusing to overwrite or dispatch it.")
                continue
            if any(existing.startswith(path + "/") for existing in entries):
                raise factory.FactoryError(f"A directory blocks starter path {path}.")
            blob = git("hash-object", "-w", "--stdin", content=content.encode()).decode().strip()
            git("update-index", "--add", "--cacheinfo", f"100644,{blob},{path}")
            changed = True
        check()
        if remote_refs() != refs:
            raise factory.FactoryError("Remote refs changed during preparation; retry after inspecting the repository.")
        if not changed:
            return parent.decode()
        tree = git("write-tree").decode().strip()
        args = ["commit-tree", tree]
        if parent:
            args.extend(["-p", parent.decode()])
        commit = git(*args, content=b"Furnish website [skip ci]\n").decode().strip()
        git("push", "origin", f"{commit}:refs/heads/main")
        if remote_refs().get(b"refs/heads/main") != commit.encode():
            raise factory.FactoryError("Pushed main was not confirmed; inspect GitHub before continuing.")
        return commit


def live_url(url):
    """Fetch Pages without credentials, checking every redirect target."""
    opener = urllib.request.build_opener(factory.NoRedirect)
    for _ in range(6):
        allowed_url(url)
        try:
            with opener.open(urllib.request.Request(url, headers={"User-Agent": "site-factory"}), timeout=20) as response:
                return response.status == 200
        except urllib.error.HTTPError as error:
            if error.code in (301, 302, 303, 307, 308) and error.headers.get("Location"):
                url = urllib.parse.urljoin(url, error.headers["Location"])
                continue
            return False
        except (urllib.error.URLError, TimeoutError):
            return False
    raise factory.FactoryError("Pages redirected too many times.")


def furnish(api, site, token, *, seed=seed_repository, sleep=time.sleep, live=live_url, progress=lambda message: None):
    user = api.request("GET", "/user")
    if user.get("login") != factory.OWNER or user.get("type") != "User":
        raise factory.FactoryError("The stored GitHub CLI login must be mamachanko's personal account.")
    base = f"/repos/{site.repository}"
    repo = target_repository(api, site, require_main=False)
    repository_id = repo["id"]
    needs_main = repo.get("default_branch") != "main"
    pages = pages_state(api, base)
    rule = existing_ruleset(api, base)
    head = seed(site, starter_files(site), token,
                check=lambda: target_repository(api, site, repository_id, require_main=not needs_main),
                require_main_only=needs_main)
    progress("Starter files ready on main")
    repo = target_repository(api, site, repository_id, require_main=not needs_main)
    if repo.get("default_branch") != "main":
        api.request("PATCH", base, {"default_branch": "main"})
        target_repository(api, site, repository_id)
    if pages is None:
        api.request("POST", base + "/pages", {"build_type": "workflow"})
        pages = pages_state(api, base)
        if pages is None:
            raise factory.FactoryError("Pages creation was not confirmed.")
    progress("GitHub Actions Pages confirmed")
    if rule is None:
        created = api.request("POST", base + "/rulesets", ruleset_payload())
        if not compatible_ruleset(created):
            raise factory.FactoryError("Created main ruleset was not confirmed; inspect GitHub.")
    progress("Main requires pull requests, with no required reviewers; deletion and force pushes blocked")
    workflow_path = base + "/actions/workflows/deploy.yml"
    for attempt in range(8):
        try:
            workflow = api.request("GET", workflow_path)
            break
        except factory.APIError as error:
            if error.status != 404 or attempt == 7:
                raise
            sleep(min(2 ** attempt, 15))
    if workflow.get("path") != WORKFLOW or workflow.get("state") != "active":
        raise factory.FactoryError("The exact deployment workflow is not active.")
    # The versioned dispatch response identifies this run directly. Never guess from a run list.
    run = api.request("POST", workflow_path + "/dispatches", {"ref": "main"})
    run_id = run.get("workflow_run_id") if isinstance(run, dict) else None
    if type(run_id) is not int or run_id <= 0:
        raise factory.FactoryError("Dispatch returned no run ID; inspect Actions before retrying.")
    run_url = f"https://github.com/{site.repository}/actions/runs/{run_id}"
    progress(f"Waiting for {run_url}")
    for attempt in range(120):
        status = api.request("GET", f"{base}/actions/runs/{run_id}")
        if (status.get("id") != run_id or status.get("head_sha") != head
                or status.get("head_branch") != "main" or status.get("event") != "workflow_dispatch"
                or status.get("path") != WORKFLOW):
            raise factory.FactoryError(f"Deployment run identity changed; inspect {run_url}.")
        if status.get("status") == "completed":
            if status.get("conclusion") != "success":
                raise factory.FactoryError(f"Deployment failed; inspect {run_url}.")
            break
        if attempt == 119:
            raise factory.FactoryError(f"Deployment is still pending; inspect {run_url}.")
        sleep(5)
    for attempt in range(60):
        pages = pages_state(api, base)
        if pages is not None and live(pages["html_url"]):
            return {"repository": site.repository, "workflow_url": run_url, "url": pages["html_url"],
                    "head_sha": head, "run_id": run_id}
        if attempt != 59:
            sleep(5)
    raise factory.FactoryError(f"Deployment succeeded but the Pages URL is not live yet; inspect {run_url} and Pages settings.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("furnish",))
    parser.add_argument("repository", help="name, mamachanko/name, or GitHub URL")
    args = parser.parse_args(argv)
    stage = None
    try:
        site = parse_repository(args.repository)
        token = stored_token()
        def progress(message):
            nonlocal stage
            stage = message
            print(message, flush=True)
        result = furnish(factory.GitHub(token=token), site, token, progress=progress)
        print(f"Live: {result['url']}\nRepository: https://github.com/{result['repository']}\nDeployment: {result['workflow_url']}")
        return 0
    except (factory.FactoryError, OSError, ValueError, KeyError) as error:
        detail = str(error) if isinstance(error, factory.FactoryError) else "Local state or response validation failed."
        print(f"Furnish failed. {detail}", file=sys.stderr)
        if stage:
            print(f"Last update: {stage}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
