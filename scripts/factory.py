#!/usr/bin/env python3
"""Small, stdlib-only website factory. Credentials stay in the environment."""
import argparse
from dataclasses import asdict, dataclass
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


def render(site, source=ROOT / "starter"):
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
            content = path.read_text(encoding="utf-8")
            unknown = set(TOKEN.findall(content)) - values.keys()
            if unknown:
                raise FactoryError(f"Unknown starter placeholder in {relative}.")
            # One substitution pass: user text cannot introduce another template expansion.
            files[relative] = TOKEN.sub(lambda m: values[m.group()], content)
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
            f"1. Check that https://github.com/{site.repository} does not exist; abort if it does.\n"
            "2. Create a public personal-account repository using an installation token.\n"
            f"3. Refresh the token; push {count} rendered starter files in one initial commit on main.\n"
            "4. Set main as default and enable Pages with build_type=workflow.\n"
            f"5. {'Configure Pages custom domain: ' + site.domain if site.domain else 'Keep the default Pages domain'}.\n"
            "6. Dispatch deploy.yml on main (bounded retries for registration).\n"
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


def create_repository(api, site):
    try:
        api.request("GET", f"/repos/{site.repository}")
    except APIError as error:
        if error.status != 404:
            raise
    else:
        raise FactoryError("Repository already exists; nothing was changed. Choose a new name.")
    # Never retry creation: 404 can also mean an inaccessible existing private repository.
    # GitHub's atomic name uniqueness check is the final guard against races/hidden repos.
    repo = api.request("POST", "/user/repos", {"name": site.name, "description": site.description,
        "private": False, "auto_init": False, "has_wiki": False, "has_projects": False})
    if repo.get("full_name") != site.repository or repo.get("private") is not False:
        raise FactoryError("Created repository identity/visibility mismatch; inspect GitHub before proceeding.")
    return repo["id"]


def seed_repository(site, files):
    """Push without tokens in arguments, remotes, files, or captured diagnostics."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "GH_"))}
    env.update(GH_TOKEN=os.environ.get("GH_TOKEN", ""), GH_HOST="github.com",
               GH_PROMPT_DISABLED="1", GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_AUTHOR_NAME="site-factory",
               GIT_AUTHOR_EMAIL="site-factory@users.noreply.github.com",
               GIT_COMMITTER_NAME="site-factory", GIT_COMMITTER_EMAIL="site-factory@users.noreply.github.com")
    with tempfile.TemporaryDirectory(prefix="site-factory-") as directory:
        root = Path(directory)
        for relative, content in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        def git(*args):
            try:
                return subprocess.run(["git", *args], cwd=root, env=env, check=True,
                    capture_output=True, text=True, timeout=90).stdout
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
                raise FactoryError("Git initialization/push failed; inspect the new repository and App permissions. No force push was attempted.") from None
        git("init", "--initial-branch=main")
        git("add", ".")
        git("-c", "commit.gpgsign=false", "commit", "-m", "Initialize website [skip ci]")
        git("remote", "add", "origin", f"https://github.com/{site.repository}.git")
        auth = ("-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential")
        if git(*auth, "ls-remote", "origin").strip():
            raise FactoryError("New repository is no longer empty; refusing to populate it.")
        git(*auth, "push", "origin", "main:refs/heads/main")


def dispatch(api, site, sleep=time.sleep, attempts=8):
    path = f"/repos/{site.repository}/actions/workflows/deploy.yml/dispatches"
    for attempt in range(attempts):
        try:
            api.request("POST", path, {"ref": "main"})
            return
        except APIError as error:
            if error.status not in (404, 422) or attempt == attempts - 1:
                raise
            sleep(min(2 ** attempt, 15))


def finish_repository(api, site, repository_id, files, seed=seed_repository, progress=lambda x: None):
    base = f"/repos/{site.repository}"
    repo = api.request("GET", base)
    if repo.get("id") != repository_id or repo.get("full_name") != site.repository or repo.get("private") is not False:
        raise FactoryError("New repository identity/visibility changed; refusing to continue.")
    seed(site, files)
    progress("Initial commit pushed to main")
    api.request("PATCH", base, {"default_branch": "main"})
    api.request("POST", base + "/pages", {"build_type": "workflow"})
    progress("Pages enabled")
    if site.domain:
        api.request("PUT", base + "/pages", {"cname": site.domain, "build_type": "workflow"})
        pages = api.request("GET", base + "/pages")
        if pages.get("cname") != site.domain or pages.get("build_type") != "workflow":
            raise FactoryError("Pages custom-domain configuration was not confirmed; do not change DNS.")
        progress("Pages custom domain confirmed")
    dispatch(api, site)
    progress("Initial deployment dispatched")


def report(message):
    print(message)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write(message + "\n\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("plan", "create", "finish"), nargs="?", default="plan")
    parser.add_argument("--state", type=Path, help="Runner-local receipt; contains no credentials")
    args = parser.parse_args(argv)
    stage = "Validation"
    try:
        site = Site(os.environ.get("REPOSITORY_NAME", ""), os.environ.get("SITE_DESCRIPTION", ""), os.environ.get("CUSTOM_DOMAIN", ""))
        files = render(site)
        if args.phase == "plan":
            report("**DRY RUN — no GitHub requests, credentials, or mutations. Repository availability is not checked.**\n\n" + plan(site, len(files)))
            return 0
        if not args.state:
            raise FactoryError("Live phases require --state.")
        api = GitHub()
        if args.phase == "create":
            stage = "Repository creation (inspect GitHub if the result is uncertain)"
            # Reserve receipt before any mutation; never reuse a previous attempt.
            with args.state.open("x", encoding="utf-8") as receipt:
                repo_id = create_repository(api, site)
                json.dump({"site": asdict(site), "repository_id": repo_id}, receipt)
            report(f"Created https://github.com/{site.repository}. Next: refresh the App token and populate it.")
        else:
            stage = "Loading creation receipt"
            state = json.loads(args.state.read_text(encoding="utf-8"))
            if state["site"] != asdict(site):
                raise FactoryError("Creation receipt does not match the requested site.")
            stage = "Populating the newly created repository"
            def progress(message):
                nonlocal stage
                stage = message + "; next operation"
                report(message + ".")
            finish_repository(api, site, state["repository_id"], files, progress=progress)
            report(f"## Site created\n\nRepository: https://github.com/{site.repository}\n\n"
                   f"Expected deployment URL: {site.url}\n\n"
                   f"Deployment queued; follow https://github.com/{site.repository}/actions/workflows/deploy.yml . "
                   "This factory does not wait for deployment success or DNS/TLS readiness.\n\n" + dns_instructions(site))
        return 0
    except (FactoryError, OSError, ValueError, KeyError) as error:
        # OSError/JSON details may include local data; keep them out of CI logs.
        detail = str(error) if isinstance(error, FactoryError) else "Local state or file operation failed."
        report(f"## Factory failed\n\nStage: {stage}. {detail}\n\n"
               "No automatic rollback or overwrite is performed. Inspect any newly created repository and its Pages settings. "
               "Do not add DNS until the Pages custom domain is confirmed. See README troubleshooting.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
