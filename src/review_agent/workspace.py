"""Workspace: a fresh shallow clone of the Target PR head, removed after use.

The clone is made in three git steps (init, fetch of `refs/pull/<n>/head` from
the base repo at depth 1, checkout). This works for PRs from forks, and also
when the fork is deleted. After the checkout, no git command runs in the
clone. The clone has no symlinks (`core.symlinks=false`), no submodules and no
LFS content. The user's global and system git config are not read.
"""

from __future__ import annotations

import base64
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from review_agent.errors import ReviewAgentError

log = logging.getLogger(__name__)

CLONE_TIMEOUT = 10 * 60


class WorkspaceError(ReviewAgentError):
    """The clone of the Target PR failed."""


class Workspace:
    """Use as a context manager. `path` is the clone while the block runs.

    `token`, when given, authenticates the fetch from github.com through an
    environment variable (never argv or `.git/config`). Only for HTTPS
    URLs on github.com.
    """

    def __init__(
        self,
        clone_url: str,
        number: int,
        *,
        token: str | None = None,
        tmp_root: Path | str | None = None,
    ):
        self.clone_url = clone_url
        self.number = number
        self._token = token
        self._tmp_root = Path(tmp_root) if tmp_root else None
        self._dir: Path | None = None
        self.path: Path | None = None

    def __enter__(self) -> Workspace:
        if self._tmp_root is not None:
            self._tmp_root.mkdir(parents=True, exist_ok=True)
        self._dir = Path(
            tempfile.mkdtemp(prefix="review-agent-clone-", dir=self._tmp_root)
        )
        try:
            self.path = self._dir / "repo"
            self._clone(self.path)
        except BaseException:
            self._remove()
            raise
        return self

    def __exit__(self, *exc) -> None:
        self._remove()

    def _remove(self) -> None:
        if self._dir is not None:
            shutil.rmtree(self._dir, ignore_errors=True)
            self._dir = None

    def _env(self) -> dict[str, str]:
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(self._dir),
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_LFS_SKIP_SMUDGE": "1",
            "GIT_ASKPASS": "",
            "SSH_ASKPASS": "",
        }
        url = urlsplit(self.clone_url)
        if self._token and url.scheme == "https" and url.hostname == "github.com":
            basic = base64.b64encode(f"x-access-token:{self._token}".encode()).decode()
            env |= {
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
                "GIT_CONFIG_VALUE_0": f"Authorization: Basic {basic}",
            }
        return env

    def _clone(self, dest: Path) -> None:
        env = self._env()
        ref = f"refs/pull/{self.number}/head"
        no_symlinks = ["-c", "core.symlinks=false"]
        self._git(["init", "-q", "--template=", str(dest)], env, cwd=self._dir)
        self._git([*no_symlinks, "config", "core.symlinks", "false"], env, cwd=dest)
        self._git(
            [
                *no_symlinks,
                "fetch",
                "-q",
                "--depth",
                "1",
                "--no-tags",
                "--no-recurse-submodules",
                self.clone_url,
                ref,
            ],
            env,
            cwd=dest,
        )
        self._git([*no_symlinks, "checkout", "-q", "FETCH_HEAD"], env, cwd=dest)
        log.info("Cloned %s %s (depth 1) into %s", self.clone_url, ref, dest)

    def _git(self, args: list[str], env: dict[str, str], *, cwd: Path) -> None:
        try:
            p = subprocess.run(
                ["git", *args],
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                timeout=CLONE_TIMEOUT,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            raise WorkspaceError(f"git {args[0]} failed: {e}") from None
        if p.returncode != 0:
            raise WorkspaceError(
                f"The clone of the PR head failed (git exit code {p.returncode}): "
                f"{p.stderr.strip()[-500:]}"
            )
