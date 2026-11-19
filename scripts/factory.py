#!/usr/bin/env python3
"""Small, stdlib-only website factory. Credentials stay in the environment."""
import argparse
from dataclasses import dataclass
import html
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
import urllib.request

OWNER = "mamachanko"
DOMAINS = ("mamachanko.com", "maxbrauer.com")
ROOT = Path(__file__).resolve().parents[1]
TOKEN = re.compile(r"__SITE_[A-Z_]+__")


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


@dataclass(frozen=True)
class Site:
    name: str
    description: str = ""
    domain: str = ""

    def __post_init__(self):
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", self.name) or len(self.name) > 63:
            raise FactoryError("Repository name must be 1–63 lowercase letters/digits, separated by single hyphens.")
        if self.name == "site-factory":
            raise FactoryError("The factory repository name is reserved.")
        if len(self.description) > 350 or any(ord(c) < 32 or ord(c) == 127 for c in self.description):
            raise FactoryError("Description must be one line, at most 350 characters, without control characters.")
        if self.domain:
            labels = self.domain.split(".")
            if len(self.domain) > 253 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", x) for x in labels):
                raise FactoryError("Domain must be a lowercase DNS hostname, without scheme, port, path, or wildcard.")
            if not any(self.domain == d or self.domain.endswith("." + d) for d in DOMAINS):
                raise FactoryError("Domain must be mamachanko.com, maxbrauer.com, or one of their subdomains.")

    @property
    def repository(self):
        return f"{OWNER}/{self.name}"

    @property
    def url(self):
        return f"https://{self.domain}/" if self.domain else f"https://{OWNER}.github.io/{self.name}/"


def render(site, source=ROOT / "starter", *, raw=False):
    """Return the complete independent repository, without writing into a checkout."""
    values = {
        "__SITE_NAME__": site.name,
        "__SITE_DESCRIPTION__": html.escape(site.description or "A little space for your next puzzle.", quote=True),
        "__SITE_URL__": site.url,
    }
    files = {}
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise FactoryError("Starter symlinks are not supported.")
        if path.is_file():
            relative = path.relative_to(source).as_posix()
            if any(part in {".git", "__pycache__", "node_modules"} for part in path.relative_to(source).parts):
                raise FactoryError(f"Unexpected generated directory in starter: {relative}")
            content = path.read_bytes().decode("utf-8")
            unknown = set(TOKEN.findall(content)) - values.keys()
            if unknown:
                raise FactoryError(f"Unknown starter placeholder in {relative}.")
            # One substitution pass: user text cannot introduce another template expansion.
            files[relative] = content if raw else TOKEN.sub(lambda m: values[m.group()], content)
    if "site/index.html" not in files or ".github/workflows/deploy.yml" not in files:
        raise FactoryError("Starter is incomplete.")
    return files


def dns_instructions(site):
    if not site.domain:
        return "No DNS changes required."
    zone = next(d for d in DOMAINS if site.domain == d or site.domain.endswith("." + d))
    host = site.domain[:-(len(zone) + 1)] if site.domain != zone else "@"
    records = [("CNAME", host, f"{OWNER}.github.io")] if host != "@" else [
        ("A", "@", ip) for ip in ("185.199.108.153", "185.199.109.153", "185.199.110.153", "185.199.111.153")
    ]
    rows = "\n".join(f"| {kind} | {label} | {value} | Automatic |" for kind, label, value in records)
    return (f"Namecheap → Domain List → {zone} → Manage → Advanced DNS → Host Records.\n\n"
            "| Type | Host | Value | TTL |\n| --- | --- | --- | --- |\n" + rows +
            "\n\nReview and replace conflicting records at this exact host. Do not add wildcard records. "
            "Use your authoritative DNS provider if Namecheap is only the registrar. "
            "Allow up to 24 hours for DNS, then enable Enforce HTTPS in repository Settings → Pages when the certificate is ready.")


def plan(site, count):
    return (f"## Plan: {site.repository}\n\n"
            f"1. Inspect existing public personal-account repository https://github.com/{site.repository}.\n"
            "2. Admit only an empty repository, the exact bundled starter on main, or its exact rendering.\n"
            "3. Check Pages for conflicting source or domain settings before changing source.\n"
            f"4. Furnish {count} rendered starter files on main, preserving template history; skip an exact rendering.\n"
            "5. Set main as default and enable missing workflow Pages settings.\n"
            f"6. Confirm {'Pages custom domain ' + site.domain if site.domain else 'the default Pages domain'} and dispatch deploy.yml.\n"
            f"7. Report the expected deployment URL: {site.url}\n\n"
            "### Planned manual DNS (only after successful Pages configuration)\n\n" + dns_instructions(site))


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


@dataclass(frozen=True)
class TargetRepository:
    id: int
    default_branch: str


def target_repository(api, site, repository_id=None):
    repo = api.request("GET", f"/repos/{site.repository}")
    if not isinstance(repo, dict) or not isinstance(repo.get("owner"), dict):
        raise FactoryError("Target repository identity response is unsafe; refusing to continue.")
    owner = repo["owner"]
    if (type(repo.get("id")) is not int or repo["id"] <= 0
            or (repository_id is not None and repo["id"] != repository_id)
            or repo.get("full_name") != site.repository or repo.get("name") != site.name
            or owner.get("login") != OWNER or owner.get("type") != "User"
            or repo.get("private") is not False or repo.get("visibility") != "public"
            or any(repo.get(key) is not False for key in ("archived", "disabled", "fork"))
            or repo.get("mirror_url") is not None
            or not isinstance(repo.get("default_branch"), str) or not repo["default_branch"]):
        raise FactoryError("Target repository identity, visibility, or settings are unsafe; refusing to continue.")
    return TargetRepository(repo["id"], repo["default_branch"])


def pages_state(api, site):
    try:
        pages = api.request("GET", f"/repos/{site.repository}/pages")
    except APIError as error:
        if error.status == 404:
            return None
        raise
    if (not isinstance(pages, dict) or pages.get("build_type") != "workflow"
            or pages.get("cname") not in (None, "", site.domain)):
        raise FactoryError("Pages source or custom domain conflicts with this initialization; nothing will be replaced.")
    return pages


def initialize_repository(api, site, files, *, progress=lambda x: None):
    """Admit exact starter objects, then converge source and missing Pages settings."""
    target = target_repository(api, site)
    base = f"/repos/{site.repository}"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "GH_"))}
    env.update(GH_TOKEN=os.environ.get("GH_TOKEN", ""), GH_HOST="github.com",
               GH_PROMPT_DISABLED="1", GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_AUTHOR_NAME="site-factory",
               GIT_AUTHOR_EMAIL="site-factory@users.noreply.github.com",
               GIT_COMMITTER_NAME="site-factory", GIT_COMMITTER_EMAIL="site-factory@users.noreply.github.com")
    with tempfile.TemporaryDirectory(prefix="site-factory-") as directory:
        def git(*args, content=None):
            try:
                return subprocess.run(["git", "-c", "core.hooksPath=" + os.devnull,
                    "-c", "core.fsmonitor=false", "-c", "credential.helper=",
                    "-c", "credential.helper=!gh auth git-credential", *args],
                    cwd=directory, env=env, input=content, check=True,
                    capture_output=True, text=True, encoding="utf-8", timeout=90).stdout.strip()
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
                raise FactoryError("Git inspection/initialization/push failed; inspect the target and App permissions. No force push was attempted.") from None

        git("init", "--template=", "--initial-branch=main")
        git("remote", "add", "origin", f"https://github.com/{site.repository}.git")

        def refs():
            output = git("ls-remote", "--refs", "origin")
            if not output:
                return {}
            result = {}
            for line in output.splitlines():
                fields = line.split("\t")
                if len(fields) != 2 or not re.fullmatch(r"[0-9a-f]{40}", fields[0]) or fields[1] != "refs/heads/main":
                    raise FactoryError("Target has unsupported refs; only main or a repository with no refs is admissible.")
                result[fields[1]] = fields[0]
            return result

        def tree(contents):
            git("read-tree", "--empty")
            for name, content in contents.items():
                mode = "100755" if (ROOT / "starter" / name).stat().st_mode & 0o111 else "100644"
                blob = git("hash-object", "-w", "--stdin", content=content)
                git("update-index", "--add", "--cacheinfo", f"{mode},{blob},{name}")
            return git("write-tree")

        rendered_tree = tree(files)
        raw_tree = tree(render(site, raw=True))
        expected_refs = refs()
        parent = expected_refs.get("refs/heads/main")
        current_tree = None
        if parent:
            git("fetch", "--no-tags", "origin", parent)
            current_tree = git("rev-parse", parent + "^{tree}")
            if current_tree not in (raw_tree, rendered_tree):
                raise FactoryError("Target main is not the exact bundled or rendered starter; refusing to overwrite source.")
            if current_tree == raw_tree and target.default_branch != "main":
                raise FactoryError("A template target must use main as its default branch.")
        expected_default = target.default_branch

        def guard(*, allow_main=False):
            nonlocal expected_default
            current = target_repository(api, site, target.id)
            allowed_defaults = (expected_default, "main") if allow_main else (expected_default,)
            if current.default_branch not in allowed_defaults or refs() != expected_refs:
                raise FactoryError("Target identity, default branch, or main changed during initialization; refusing to continue.")
            expected_default = current.default_branch
            return pages_state(api, site)

        if current_tree != rendered_tree:
            guard()
            args = ("commit-tree", rendered_tree, "-p", parent) if parent else ("commit-tree", rendered_tree)
            commit = git(*args, content="Initialize website [skip ci]\n")
            git("push", "origin", commit + ":refs/heads/main")
            expected_refs = {"refs/heads/main": commit}
            progress("Rendered starter pushed to main")
        else:
            progress("Exact rendered starter already on main")
        pages = guard(allow_main=parent is None)
        if expected_default != "main":
            api.request("PATCH", base, {"default_branch": "main"})
            expected_default = "main"
            progress("Default branch set to main")
            pages = guard()
        if pages is None:
            api.request("POST", base + "/pages", {"build_type": "workflow"})
            progress("Pages enabled")
        pages = guard()
        if pages is None:
            raise FactoryError("Pages configuration was not confirmed; do not change DNS.")
        if site.domain and not pages.get("cname"):
            api.request("PUT", base + "/pages", {"cname": site.domain, "build_type": "workflow"})
            progress("Pages custom domain set")

        def confirm():
            pages = guard()
            if pages is None or (pages.get("cname") or "") != site.domain:
                raise FactoryError("Pages custom-domain configuration was not confirmed; do not change DNS.")
            progress("Pages source and domain confirmed")

        dispatch(api, site, check=confirm)
        progress("Initial deployment dispatched")


def dispatch(api, site, sleep=time.sleep, attempts=8, check=lambda: None):
    path = f"/repos/{site.repository}/actions/workflows/deploy.yml/dispatches"
    for attempt in range(attempts):
        check()
        try:
            api.request("POST", path, {"ref": "main"})
            return
        except APIError as error:
            if error.status not in (404, 422) or attempt == attempts - 1:
                raise
            sleep(min(2 ** attempt, 15))


def report(message):
    print(message)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write(message + "\n\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("plan", "initialize"), nargs="?", default="plan")
    args = parser.parse_args(argv)
    stage = "Validation"
    try:
        site = Site(os.environ.get("REPOSITORY_NAME", ""), os.environ.get("SITE_DESCRIPTION", ""), os.environ.get("CUSTOM_DOMAIN", ""))
        files = render(site)
        if args.phase == "plan":
            report("**DRY RUN — no GitHub requests, credentials, or mutations. Target repository and Pages settings are not checked.**\n\n" + plan(site, len(files)))
            return 0
        api = GitHub()
        stage = "Inspecting the existing target repository"
        def progress(message):
            nonlocal stage
            stage = message + "; next operation"
            report(message + ".")
        initialize_repository(api, site, files, progress=progress)
        report(f"## Site initialized\n\nRepository: https://github.com/{site.repository}\n\n"
               f"Expected deployment URL: {site.url}\n\n"
               f"Deployment queued; follow https://github.com/{site.repository}/actions/workflows/deploy.yml . "
               "This factory does not wait for deployment success or DNS/TLS readiness.\n\n" + dns_instructions(site))
        return 0
    except (FactoryError, OSError, ValueError, KeyError) as error:
        # OSError/JSON details may include local data; keep them out of CI logs.
        detail = str(error) if isinstance(error, FactoryError) else "Local state or file operation failed."
        report(f"## Factory failed\n\nStage: {stage}. {detail}\n\n"
               "No automatic rollback or overwrite is performed. Inspect the target repository and its Pages settings. Rerun with the same inputs and factory revision after resolving the failure. "
               "Do not add DNS until the Pages custom domain is confirmed. See README troubleshooting.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
