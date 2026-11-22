#!/usr/bin/env python3
"""Validate or furnish an owner-created repository from the trusted App workflow."""
import argparse
from dataclasses import dataclass
import http.client
import json
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

OWNER = "mamachanko"
DOMAINS = ("mamachanko.com", "maxbrauer.com")
DEFAULT_PAGES_HOST = "gh.mamachanko.com"
ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ".github/workflows/deploy.yml"
RULESET_NAME = "site-factory-main"
INTEGRITY_RULESET_NAME = "site-factory-main-integrity"
REPOSITORY_DEFAULTS = {
    "allow_merge_commit": False, "allow_squash_merge": False, "allow_rebase_merge": True,
    "allow_auto_merge": False, "delete_branch_on_merge": True,
    "has_issues": True, "has_wiki": False, "has_projects": False, "has_discussions": False,
    "default_branch": "main",
}
WORKFLOW_PERMISSIONS = {"default_workflow_permissions": "read", "can_approve_pull_request_reviews": True}
SHA = re.compile(r"[0-9a-f]{40}")


class FactoryError(Exception):
    pass


class APIError(FactoryError):
    def __init__(self, method, path, status, *, category=None, request_id=None):
        self.status = status
        detail = f"GitHub {method} {path} failed (HTTP {status})."
        if category:
            detail += f" Category: {category}."
        if request_id:
            detail += f" GitHub request ID: {request_id}."
        super().__init__(detail)


def validate_domain(domain):
    if not isinstance(domain, str):
        raise FactoryError("Domain must be a lowercase DNS hostname, without scheme, port, path, or wildcard.")
    labels = domain.split(".")
    if len(domain) > 253 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", x) for x in labels):
        raise FactoryError("Domain must be a lowercase DNS hostname, without scheme, port, path, or wildcard.")
    if not any(domain == d or domain.endswith("." + d) for d in DOMAINS):
        raise FactoryError("Domain must be mamachanko.com, maxbrauer.com, or one of their subdomains.")


@dataclass(frozen=True)
class Site:
    name: str

    def __post_init__(self):
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", self.name) or len(self.name) > 63:
            raise FactoryError("Repository name must be 1–63 lowercase letters/digits, separated by single hyphens.")
        if self.name == "site-factory":
            raise FactoryError("The factory repository name is reserved.")

    @property
    def repository(self):
        return f"{OWNER}/{self.name}"

    @property
    def default_pages_url(self):
        return f"https://{DEFAULT_PAGES_HOST}/{self.name}/"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHub:
    def __init__(self):
        self.token = os.environ.get("GH_TOKEN")
        if not self.token:
            raise FactoryError("GH_TOKEN is required for live operations; use the GitHub App workflow.")
        self.opener = urllib.request.build_opener(NoRedirect)

    def request(self, method, path, payload=None):
        if not path.startswith("/") or path.startswith("//"):
            raise FactoryError("Invalid API path.")
        req = urllib.request.Request("https://api.github.com" + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            method=method, headers={"Authorization": "Bearer " + self.token,
                "Accept": "application/vnd.github+json", "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2026-03-10", "User-Agent": "mamachanko-site-factory"})
        try:
            with self.opener.open(req, timeout=30) as response:
                body = response.read()
                return json.loads(body) if body else None
        except urllib.error.HTTPError as error:
            headers = error.headers or {}
            request_id = headers.get("X-GitHub-Request-Id", "")
            if not isinstance(request_id, str) or not re.fullmatch(r"[0-9A-Fa-f]{1,8}(?::[0-9A-Fa-f]{1,8}){4}", request_id):
                request_id = None
            category = "rate limited" if error.code == 429 else None
            if error.code == 403:
                message = ""
                try:
                    body = json.loads(error.read(65536))
                    if isinstance(body, dict) and isinstance(body.get("message"), str):
                        message = body["message"].casefold()
                except (OSError, ValueError, RecursionError, http.client.HTTPException):
                    pass
                if (headers.get("X-RateLimit-Remaining") == "0" or headers.get("Retry-After") is not None
                        or message == "rate limit exceeded"
                        or message.startswith(("api rate limit exceeded", "you have exceeded a secondary rate limit"))):
                    category = "rate limited"
                elif message in ("resource not accessible by integration", "resource not accessible by personal access token"):
                    category = "access denied"
            raise APIError(method, path, error.code, category=category, request_id=request_id) from None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            raise FactoryError(f"GitHub {method} {path} had a transport/response error; inspect GitHub before retrying mutations.") from None


def installation_repository(api, site):
    installation = api.request("GET", "/installation/repositories?per_page=2")
    if not isinstance(installation, dict):
        raise FactoryError("The App token must cover exactly the requested repository.")
    repositories = installation.get("repositories")
    if (type(installation.get("total_count")) is not int or installation["total_count"] != 1
            or not isinstance(repositories, list) or len(repositories) != 1
            or not isinstance(repositories[0], dict)
            or repositories[0].get("full_name") != site.repository
            or type(repositories[0].get("id")) is not int or repositories[0]["id"] <= 0):
        raise FactoryError("The App token must cover exactly the requested repository.")
    return repositories[0]["id"]


def starter_files(site, pages_url=None):
    directory = ROOT / "templates"
    if directory.is_symlink() or not directory.is_dir():
        raise FactoryError("Starter templates must be a regular directory.")
    files = {}
    replacements = {"__SITE_NAME__": site.name, "__SITE_URL__": pages_url or site.default_pages_url}
    for source in sorted(directory.rglob("*")):
        path = source.relative_to(directory).as_posix()
        validate_starter_path(path)
        if source.is_symlink() or not (source.is_dir() or source.is_file()):
            raise FactoryError(f"Template {path} must be a regular file or directory.")
        if source.is_file():
            content = source.read_bytes().decode("utf-8")
            files[path] = re.sub(r"__SITE_NAME__|__SITE_URL__", lambda match: replacements[match[0]], content)
    if WORKFLOW not in files or "site/index.html" not in files:
        raise FactoryError("Starter templates must include the deployment workflow and site/index.html.")
    return files


def validate_starter_path(path):
    if (not isinstance(path, str) or not path or path.startswith("/") or "\\" in path
            or any(ord(char) < 32 or ord(char) == 127 for char in path)
            or any(piece in ("", ".", "..") or piece.casefold() == ".git" for piece in path.split("/"))):
        raise FactoryError("Starter paths must be safe relative repository paths.")


def owned_automation(path):
    return path == ".github" or path.startswith(".github/") or path == "renovate.json"


def target_repository(api, site, repository_id, *, require_main=True):
    repo = api.request("GET", f"/repos/{site.repository}")
    if (not isinstance(repo, dict) or not isinstance(repo.get("owner"), dict)
            or repo.get("full_name") != site.repository or repo["owner"].get("login") != OWNER
            or repo["owner"].get("type") != "User" or repo.get("private") is not False
            or repo.get("archived") is not False or repo.get("disabled") is not False
            or type(repo.get("id")) is not int or repo["id"] <= 0
            or repo["id"] != repository_id):
        raise FactoryError("Repository must be public, active, and owned by mamachanko; its ID must match the scoped App token.")
    if require_main and repo.get("default_branch") != "main":
        raise FactoryError("The existing repository default branch must be main.")
    return repo


def ruleset_payload(name=RULESET_NAME):
    common = {"name": name, "target": "branch", "enforcement": "active", "bypass_actors": [],
            "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
            "rules": []}
    if name == INTEGRITY_RULESET_NAME:
        common["rules"] = [{"type": "deletion"}, {"type": "non_fast_forward"}, {"type": "required_linear_history"}]
    elif name == RULESET_NAME:
        common["bypass_actors"] = [{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}]
        common["rules"] = [{"type": "pull_request", "parameters": {
                          "allowed_merge_methods": ["rebase"],
                          "require_extra_approval_for_unattributed_changes": False,
                          "required_approving_review_count": 0, "dismiss_stale_reviews_on_push": False,
                          "require_code_owner_review": False, "require_last_push_approval": False,
                          "required_review_thread_resolution": False}},
                          {"type": "required_status_checks", "parameters": {
                              "required_status_checks": [{"context": "Check site", "integration_id": 15368}],
                              "strict_required_status_checks_policy": False,
                              "do_not_enforce_on_create": False}}]
    else:
        raise FactoryError("Unknown managed ruleset.")
    return common


def compatible_ruleset(value, name=RULESET_NAME):
    if not isinstance(value, dict):
        return False
    expected = ruleset_payload(name)
    if any(value.get(key) != expected[key] for key in ("name", "target", "enforcement", "conditions", "bypass_actors")):
        return False
    rules = value.get("rules", [])
    if not isinstance(rules, list) or len(rules) != len(expected["rules"]):
        return False
    for wanted in expected["rules"]:
        matches = [rule for rule in rules if isinstance(rule, dict) and rule.get("type") == wanted["type"]]
        if len(matches) != 1:
            return False
        actual = matches[0].get("parameters", {})
        required = wanted.get("parameters", {})
        if not isinstance(actual, dict):
            return False
        if not matches_settings(actual, required):
            return False
        # GitHub can return empty optional parameters such as required_reviewers.
        if any(val not in (False, None, [], {}) for key, val in actual.items() if key not in required):
            return False
    return True


def existing_ruleset(api, base, name=RULESET_NAME):
    found = []
    for page in range(1, 101):
        items = api.request("GET", f"{base}/rulesets?includes_parents=false&per_page=100&page={page}")
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise FactoryError("GitHub returned an invalid ruleset list.")
        found.extend(item for item in items if item.get("name") == name)
        if len(items) < 100:
            break
    else:
        raise FactoryError("Too many rulesets to safely inspect.")
    if len(found) > 1:
        raise FactoryError(f"Multiple {name} rulesets exist; inspect before continuing.")
    if not found:
        return None
    rule_id = found[0].get("id")
    if type(rule_id) is not int or rule_id <= 0:
        raise FactoryError("GitHub returned an invalid managed ruleset ID.")
    rule = api.request("GET", f"{base}/rulesets/{rule_id}")
    if not compatible_ruleset(rule, name):
        raise FactoryError(f"Existing {name} ruleset is incompatible; nothing will overwrite it.")
    return rule


def validate_pages_url(value):
    if not isinstance(value, str):
        raise FactoryError("Pages did not report a usable HTTPS URL.")
    parts = urllib.parse.urlsplit(value)
    if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
            or parts.port is not None or parts.query or parts.fragment or any(c.isspace() for c in value)):
        raise FactoryError("Pages URL must be HTTPS on an allowed host.")
    if parts.hostname != f"{OWNER}.github.io":
        validate_domain(parts.hostname)


def configured_pages_url(api, site):
    try:
        pages = api.request("GET", f"/repos/{site.repository}/pages")
    except APIError as error:
        if error.status == 404:
            return None
        raise
    if pages.get("build_type") != "workflow":
        raise FactoryError("Existing Pages must already use GitHub Actions; refusing to replace its source.")
    cname = pages.get("cname")
    if cname is None or cname == DEFAULT_PAGES_HOST:
        return site.default_pages_url
    validate_domain(cname)
    return f"https://{cname}/"


def seed_repository(site, files, token, *, remote=None, check=lambda: None, require_main_only=False):
    """Add missing blobs using a temporary Git index; never check out remote content."""
    for path in files:
        validate_starter_path(path)
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
                raise FactoryError("Git furnishing failed; inspect the repository before retrying. No force push was attempted.") from None
        git("init", "--template=", "--initial-branch=main")
        git("remote", "add", "origin", remote or f"https://github.com/{site.repository}.git")
        def remote_refs():
            return dict(line.split(b"\t", 1)[::-1] for line in git("ls-remote", "--refs", "origin").splitlines())
        refs = remote_refs()
        if require_main_only and refs.keys() - {b"refs/heads/main"}:
            raise FactoryError("The existing repository default branch must be main.")
        parent = refs.get(b"refs/heads/main")
        if refs and not parent:
            raise FactoryError("Nonempty repository has no main branch; refusing to initialize it.")
        entries = {}
        if parent:
            if not SHA.fullmatch(parent.decode()):
                raise FactoryError("Remote returned an invalid main SHA.")
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
                raise FactoryError(f"A file or symlink blocks starter path {path}.")
            if path in entries:
                mode, kind, blob = entries[path]
                if mode not in (b"100644", b"100755") or kind != b"blob":
                    raise FactoryError(f"Existing {path} must be a regular file.")
                if owned_automation(path) and git("cat-file", "blob", blob.decode()) != content.encode():
                    raise FactoryError(f"Existing {path} is unknown; refusing to overwrite or dispatch automation.")
                continue
            if any(existing.startswith(path + "/") for existing in entries):
                raise FactoryError(f"A directory blocks starter path {path}.")
            blob = git("hash-object", "-w", "--stdin", content=content.encode()).decode().strip()
            git("update-index", "--add", "--cacheinfo", f"100644,{blob},{path}")
            changed = True
        check()
        if remote_refs() != refs:
            raise FactoryError("Remote refs changed during preparation; retry after inspecting the repository.")
        if not changed:
            return parent.decode()
        tree = git("write-tree").decode().strip()
        args = ["commit-tree", tree]
        if parent:
            args.extend(["-p", parent.decode()])
        commit = git(*args, content=b"Furnish website [skip ci]\n").decode().strip()
        git("push", "origin", f"{commit}:refs/heads/main")
        if remote_refs().get(b"refs/heads/main") != commit.encode():
            raise FactoryError("Pushed main was not confirmed; inspect GitHub before continuing.")
        return commit


def page_responds(url):
    """Fetch Pages without credentials, checking every redirect target."""
    opener = urllib.request.build_opener(NoRedirect)
    for _ in range(6):
        validate_pages_url(url)
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
    raise FactoryError("Pages redirected too many times.")


def matches_settings(actual, desired):
    return (isinstance(actual, dict)
            and all(type(actual.get(key)) is type(value) and actual[key] == value for key, value in desired.items()))


def configure_defaults(api, site, repository_id):
    base = f"/repos/{site.repository}"
    repo = target_repository(api, site, repository_id, require_main=False)
    changes = {key: value for key, value in REPOSITORY_DEFAULTS.items()
               if not matches_settings(repo, {key: value})}
    if changes:
        target_repository(api, site, repository_id, require_main=False)
        api.request("PATCH", base, changes)
    if not matches_settings(target_repository(api, site, repository_id), REPOSITORY_DEFAULTS):
        raise FactoryError("Repository defaults were not confirmed; inspect GitHub settings.")
    path = base + "/actions/permissions/workflow"
    permissions = api.request("GET", path)
    if not matches_settings(permissions, WORKFLOW_PERMISSIONS):
        target_repository(api, site, repository_id)
        api.request("PUT", path, WORKFLOW_PERMISSIONS)
        if not matches_settings(api.request("GET", path), WORKFLOW_PERMISSIONS):
            raise FactoryError("Workflow token permissions were not confirmed; inspect GitHub settings.")


def ensure_ruleset(api, site, repository_id, existing, name):
    if existing is not None:
        return
    base = f"/repos/{site.repository}"
    target_repository(api, site, repository_id)
    created = api.request("POST", base + "/rulesets", ruleset_payload(name))
    rule_id = created.get("id") if isinstance(created, dict) else None
    if type(rule_id) is not int or rule_id <= 0:
        raise FactoryError(f"Created {name} ruleset returned no ID; inspect GitHub.")
    readback = api.request("GET", f"{base}/rulesets/{rule_id}")
    if not compatible_ruleset(readback, name):
        raise FactoryError(f"Created {name} ruleset was not confirmed; inspect GitHub.")


def furnish(api, site, token, *, seed=seed_repository, sleep=time.sleep, live=page_responds, progress=lambda message: None):
    repository_id = installation_repository(api, site)
    base = f"/repos/{site.repository}"
    repo = target_repository(api, site, repository_id, require_main=False)
    needs_main = repo.get("default_branch") != "main"
    pages_url = configured_pages_url(api, site)
    rule = existing_ruleset(api, base)
    integrity_rule = existing_ruleset(api, base, INTEGRITY_RULESET_NAME)
    head = seed(site, starter_files(site, pages_url), token,
                check=lambda: target_repository(api, site, repository_id, require_main=not needs_main),
                require_main_only=needs_main)
    progress("Starter files ready on main")
    configure_defaults(api, site, repository_id)
    progress("Repository settings and workflow token permissions confirmed")
    if pages_url is None:
        target_repository(api, site, repository_id)
        api.request("POST", base + "/pages", {"build_type": "workflow"})
        pages_url = configured_pages_url(api, site)
        if pages_url is None:
            raise FactoryError("Pages creation was not confirmed.")
    progress("GitHub Actions Pages confirmed")
    ensure_ruleset(api, site, repository_id, integrity_rule, INTEGRITY_RULESET_NAME)
    progress("Main deletion, force pushes, and merge commits blocked without bypass")
    workflow_path = base + "/actions/workflows/deploy.yml"
    for attempt in range(8):
        try:
            workflow = api.request("GET", workflow_path)
            break
        except APIError as error:
            if error.status != 404 or attempt == 7:
                raise
            sleep(min(2 ** attempt, 15))
    if workflow.get("path") != WORKFLOW or workflow.get("state") != "active":
        raise FactoryError("The exact deployment workflow is not active.")
    # The versioned dispatch response identifies this run directly. Never guess from a run list.
    target_repository(api, site, repository_id)
    run = api.request("POST", workflow_path + "/dispatches", {"ref": "main"})
    run_id = run.get("workflow_run_id") if isinstance(run, dict) else None
    if type(run_id) is not int or run_id <= 0:
        raise FactoryError("Dispatch returned no run ID; inspect Actions before retrying.")
    run_url = f"https://github.com/{site.repository}/actions/runs/{run_id}"
    progress(f"Waiting for {run_url}")
    for attempt in range(120):
        status = api.request("GET", f"{base}/actions/runs/{run_id}")
        if (status.get("id") != run_id or status.get("head_sha") != head
                or status.get("head_branch") != "main" or status.get("event") != "workflow_dispatch"
                or status.get("path") != WORKFLOW):
            raise FactoryError(f"Deployment run identity changed; inspect {run_url}.")
        if status.get("status") == "completed":
            if status.get("conclusion") != "success":
                raise FactoryError(f"Deployment failed; inspect {run_url}.")
            break
        if attempt == 119:
            raise FactoryError(f"Deployment is still pending; inspect {run_url}.")
        sleep(5)
    # GitHub expects the check source to have recently reported a check run.
    ensure_ruleset(api, site, repository_id, rule, RULESET_NAME)
    progress("Main requires pull requests, rebase merges, and the GitHub Actions Check site check; only admins bypass")
    for attempt in range(60):
        pages_url = configured_pages_url(api, site)
        if pages_url is not None and live(pages_url):
            return pages_url, run_url
        if attempt != 59:
            sleep(5)
    raise FactoryError(f"Deployment succeeded but the Pages URL is not live yet; inspect {run_url} and Pages settings.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "furnish"))
    args = parser.parse_args(argv)
    stage = None
    try:
        site = Site(os.environ.get("REPOSITORY_NAME", ""))
        if args.command == "validate":
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
                output.write(f"repository_name={site.name}\n")
            return 0
        api = GitHub()
        def progress(message):
            nonlocal stage
            stage = message
            print(message, flush=True)
        pages_url, run_url = furnish(api, site, api.token, progress=progress)
        if path := os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(path, "a", encoding="utf-8") as output:
                output.write(f"Repository: https://github.com/{site.repository}\n\nLive: {pages_url}\n")
        print(f"Live: {pages_url}\nRepository: https://github.com/{site.repository}\nDeployment: {run_url}")
        return 0
    except (FactoryError, OSError, ValueError, KeyError) as error:
        detail = str(error) if isinstance(error, FactoryError) else "Local state or response validation failed."
        print(f"Furnish failed. {detail}", file=sys.stderr)
        if stage:
            print(f"Last update: {stage}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
