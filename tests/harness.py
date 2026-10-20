"""Seam 1 test harness: run `run_review` with a fake GitHub and a fake Engine.

The two replaced boundaries:

- GitHub: `FakeGitHub`, an `httpx.MockTransport` with a route table. It serves a
  canned `/user`, PR metadata and diff, and records every request.
- Engine: `FakeEngine`, which returns queued Review JSON (or raises queued
  exceptions) and records each call.

The PR head is a real local git repo, served to `Workspace` by a `file://` URL
as `base.repo.clone_url`, with the head commit at `refs/pull/<n>/head`.

Typical test:

    def test_something(world):
        world.engine.respond(review_json(findings=[...]))
        result = world.run()
        assert result.ok
        assert world.output_json()["comments"][0]["line"] == 3

Extend a case by changing `world` before `world.run()`:

- `world.github.route("GET", "/repos/o/r/contents/X", status=..., json=...)`
  adds or replaces a route (a handler callable is also allowed).
- `world.github.user_headers[...] = ...` adds headers to `GET /user`.
- `world.write_config(...)` rewrites the config file; `world.env` is the
  environment that `run_review` sees.
- `world.pr` is the canned PR JSON; `world.diff` is the canned diff text.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from review_agent import Options, RunResult, run_review

OWNER = "octo"
REPO = "widgets"
NUMBER = 7
LOGIN = "reviewer"
PR_URL = f"https://github.com/{OWNER}/{REPO}/pull/{NUMBER}"
GITHUB_TOKEN = "test-github-token"
ENGINE_KEY = "test-engine-key"

DIFF_MEDIA_TYPE = "application/vnd.github.diff"
REVIEW_ID = 4242
REVIEWS_PATH = f"/repos/{OWNER}/{REPO}/pulls/{NUMBER}/reviews"

# The head commit changes `calc.py` from BASE_FILES to HEAD_FILES.
BASE_FILES = {
    "calc.py": "def add(a, b):\n    return a + b\n",
    "README.md": "# widgets\n",
}
HEAD_FILES = {
    "calc.py": (
        "def add(a, b):\n    return a + b\n\n\ndef div(a, b):\n    return a / b\n"
    ),
    "README.md": "# widgets\n",
}
DIFF = """\
diff --git a/calc.py b/calc.py
index 1111111..2222222 100644
--- a/calc.py
+++ b/calc.py
@@ -1,2 +1,6 @@
 def add(a, b):
     return a + b
+
+
+def div(a, b):
+    return a / b
"""

GIT_ENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
    "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
}


def review_json(summary: str = "The change adds div().", findings=None) -> str:
    """Review JSON text in the schema shape."""
    return json.dumps({"summary": summary, "findings": findings or []})


def finding(
    body: str = "Division by zero is not handled.",
    *,
    label: str = "issue (blocking)",
    path: str | None = "calc.py",
    line: int | None = 6,
    start_line: int | None = None,
    side: str | None = "RIGHT",
    suggestion: str | None = None,
) -> dict:
    """One Finding in the schema shape. Defaults anchor to an added line."""
    return {
        "label": label,
        "path": path,
        "start_line": start_line,
        "line": line,
        "side": side,
        "body": body,
        "suggestion": suggestion,
    }


# --- fake GitHub -------------------------------------------------------------


@dataclass
class Recorded:
    method: str
    path: str
    params: dict[str, str]
    headers: dict[str, str]
    body: Any

    @property
    def accept(self) -> str:
        return self.headers.get("accept", "")


Handler = Callable[[httpx.Request], httpx.Response]


class FakeGitHub:
    """A route table behind `httpx.MockTransport`. Records every request."""

    def __init__(self) -> None:
        self.requests: list[Recorded] = []
        # (method, path, accept or None) -> handler
        self._routes: dict[tuple[str, str, str | None], Handler] = {}
        self.transport = httpx.MockTransport(self._handle)

    def route(
        self,
        method: str,
        path: str,
        *,
        accept: str | None = None,
        status: int = 200,
        json: Any = None,
        text: str | None = None,
        headers: dict[str, str] | None = None,
        handler: Handler | None = None,
    ) -> None:
        """Add or replace a route. `accept` limits it to one Accept header."""
        if handler is None:

            def handler(request: httpx.Request) -> httpx.Response:
                if text is not None:
                    return httpx.Response(status, text=text, headers=headers)
                return httpx.Response(status, json=json, headers=headers)

        self._routes[(method.upper(), path, accept)] = handler

    def _handle(self, request: httpx.Request) -> httpx.Response:
        body: Any = request.content.decode() if request.content else None
        if body:
            with contextlib.suppress(ValueError):
                body = json.loads(body)
        rec = Recorded(
            method=request.method,
            path=request.url.path,
            params=dict(request.url.params),
            headers={k.lower(): v for k, v in request.headers.items()},
            body=body,
        )
        self.requests.append(rec)
        key = (request.method, request.url.path)
        handler = self._routes.get((*key, rec.accept)) or self._routes.get((*key, None))
        if handler is None:
            return httpx.Response(404, json={"message": "Not Found (no fake route)"})
        return handler(request)

    # Helpers for assertions.
    def calls(self, method: str | None = None, path: str | None = None):
        return [
            r
            for r in self.requests
            if (method is None or r.method == method)
            and (path is None or r.path == path)
        ]

    @property
    def writes(self) -> list[Recorded]:
        return [r for r in self.requests if r.method not in ("GET", "HEAD")]


# --- fake engine -------------------------------------------------------------


@dataclass
class EngineCall:
    prompt: str
    clone_dir: Path
    clone_files: dict[str, str]  # the clone's files at call time, path -> text


class FakeEngine:
    """Returns queued responses in order. An Exception in the queue is raised."""

    name = "Claude Code"

    def __init__(self, model: str = "glm-test") -> None:
        self.model = model
        self.calls: list[EngineCall] = []
        self.api_key: str | None = None  # set by the engine factory
        self.settings = None  # the EngineSettings that run_review passed
        self._queue: list[str | BaseException] = []

    def respond(self, *responses: str | BaseException) -> FakeEngine:
        self._queue.extend(responses)
        return self

    def review(self, prompt: str, clone_dir: Path) -> str:
        clone_dir = Path(clone_dir)
        files = {
            str(p.relative_to(clone_dir)): p.read_text(errors="replace")
            for p in sorted(clone_dir.rglob("*"))
            if p.is_file() and ".git" not in p.relative_to(clone_dir).parts
        }
        self.calls.append(EngineCall(prompt, clone_dir, files))
        if not self._queue:
            raise AssertionError("FakeEngine called with no queued response")
        item = self._queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


# --- the world ---------------------------------------------------------------


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=GIT_ENV,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def make_origin(root: Path, number: int = NUMBER) -> tuple[Path, str, str]:
    """A bare repo with a base commit on `main` and the PR head at
    `refs/pull/<number>/head`. Returns (bare path, base sha, head sha)."""
    work = root / "origin-work"
    work.mkdir(parents=True)
    _git("init", "-q", "-b", "main", cwd=work)
    for name, text in BASE_FILES.items():
        (work / name).write_text(text)
    _git("add", "-A", cwd=work)
    _git("commit", "-q", "-m", "base", cwd=work)
    base_sha = _git("rev-parse", "HEAD", cwd=work)
    _git("checkout", "-q", "-b", "feature", cwd=work)
    for name, text in HEAD_FILES.items():
        (work / name).write_text(text)
    _git("add", "-A", cwd=work)
    _git("commit", "-q", "-m", "head", cwd=work)
    head_sha = _git("rev-parse", "HEAD", cwd=work)
    bare = root / "origin.git"
    _git("clone", "-q", "--bare", str(work), str(bare), cwd=root)
    _git("update-ref", f"refs/pull/{number}/head", head_sha, cwd=bare)
    return bare, base_sha, head_sha


@dataclass
class World:
    root: Path
    github: FakeGitHub
    engine: FakeEngine
    env: dict[str, str]
    config_path: Path
    out_dir: Path
    log_dir: Path
    tmp_root: Path
    pr: dict
    diff: str
    login: str = LOGIN
    user_headers: dict[str, str] = field(default_factory=dict)
    pr_url: str = PR_URL
    # The reviews that `GET .../pulls/<n>/reviews` returns (one page).
    reviews: list[dict] = field(default_factory=list)

    def write_config(self, text: str, path: Path | None = None) -> Path:
        path = path or self.config_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def options(self, **overrides) -> Options:
        kw = dict(
            config_path=self.config_path,
            dry_run=True,
            out_dir=self.out_dir,
            log_dir=self.log_dir,
            tmp_root=self.tmp_root,
            env=self.env,
            engine_factory=self._make_engine,
            http_transport=self.github.transport,
        )
        kw.update(overrides)
        return Options(**kw)

    def run(self, pr_url: str | None = None, **overrides) -> RunResult:
        return run_review(pr_url or self.pr_url, self.options(**overrides))

    def _make_engine(self, settings, api_key: str) -> FakeEngine:
        self.engine.settings = settings
        self.engine.api_key = api_key
        return self.engine

    def install_default_routes(self) -> None:
        """Install the canned routes. Handlers read `pr`, `diff`, `login` and
        `user_headers` at request time, so a test can change those fields.
        `github.route(...)` with the same method, path and accept replaces one."""
        gh = self.github
        repo_path = f"/repos/{OWNER}/{REPO}/pulls/{NUMBER}"
        gh.route(
            "GET",
            "/user",
            handler=lambda r: httpx.Response(
                200, json={"login": self.login}, headers=self.user_headers
            ),
        )
        gh.route("GET", repo_path, handler=lambda r: httpx.Response(200, json=self.pr))
        gh.route(
            "GET",
            repo_path,
            accept=DIFF_MEDIA_TYPE,
            handler=lambda r: httpx.Response(200, text=self.diff),
        )
        gh.route(
            "GET",
            f"{repo_path}/reviews",
            handler=lambda r: httpx.Response(200, json=self.reviews),
        )
        gh.route("POST", f"{repo_path}/reviews", handler=self._create_review)

    def _create_review(self, request: httpx.Request) -> httpx.Response:
        """Like GitHub: no `event` gives a PENDING review; COMMENT submits it."""
        body = json.loads(request.content)
        state = {None: "PENDING", "COMMENT": "COMMENTED"}.get(body.get("event"))
        if state is None:
            return httpx.Response(422, json={"message": "Unprocessable Entity"})
        return httpx.Response(
            200,
            json={
                "id": REVIEW_ID,
                "state": state,
                "user": {"login": self.login},
                "html_url": f"{PR_URL}#pullrequestreview-{REVIEW_ID}",
            },
        )

    # Outputs.
    def output_files(self) -> list[Path]:
        if not self.out_dir.exists():
            return []
        return sorted(p for p in self.out_dir.iterdir() if p.is_file())

    def output_json(self) -> dict:
        (path,) = [p for p in self.output_files() if p.suffix == ".json"]
        return json.loads(path.read_text())

    def output_markdown(self) -> str:
        (path,) = [p for p in self.output_files() if p.suffix == ".md"]
        return path.read_text()

    def clones_left(self) -> list[Path]:
        return [p for p in self.tmp_root.iterdir()] if self.tmp_root.exists() else []


DEFAULT_CONFIG = f"""\
[auth]
login = "{LOGIN}"

[engine]
"""


def make_world(root: Path) -> World:
    bare, base_sha, head_sha = make_origin(root / "git")
    pr = {
        "number": NUMBER,
        "title": "Add div()",
        "body": "This PR adds a div function.",
        "html_url": PR_URL,
        "state": "open",
        "user": {"login": "contributor"},
        "base": {
            "ref": "main",
            "sha": base_sha,
            "repo": {
                "full_name": f"{OWNER}/{REPO}",
                "clone_url": f"file://{bare}",
                "private": False,
            },
        },
        "head": {
            "ref": "feature",
            "sha": head_sha,
            "repo": {
                "full_name": f"contributor/{REPO}",
                "clone_url": "https://example.invalid/never-used.git",
            },
        },
    }
    tmp_root = root / "tmp"
    tmp_root.mkdir()
    world = World(
        root=root,
        github=FakeGitHub(),
        engine=FakeEngine(),
        env={
            "REVIEW_AGENT_GITHUB_TOKEN": GITHUB_TOKEN,
            "REVIEW_AGENT_ENGINE_KEY": ENGINE_KEY,
        },
        config_path=root / "config" / "config.toml",
        out_dir=root / "out",
        log_dir=root / "logs",
        tmp_root=tmp_root,
        pr=pr,
        diff=DIFF,
    )
    world.write_config(DEFAULT_CONFIG)
    world.install_default_routes()
    return world
