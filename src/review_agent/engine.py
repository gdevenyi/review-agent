"""The Engine seam and its one adapter, ClaudeCodeEngine.

See ADR 0001 (the engine gets no shell) and ADR 0002 (the engine runs in
bubblewrap, Linux only).
"""

import contextlib
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Literal, Protocol

from review_agent.schema import REVIEW_SCHEMA_TEXT

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.z.ai/api/anthropic"
DEFAULT_MODEL = "glm-5.3-flash"
DEFAULT_TIMEOUT = 20 * 60

# Fixed paths inside the sandbox. The host layout does not leak in.
SANDBOX_CLONE = "/repo"
SANDBOX_CLAUDE_DIR = "/opt/claude"
SANDBOX_HOME = "/home/engine"
SANDBOX_PATH = "/usr/local/bin:/usr/bin:/bin"

# Files in /etc that DNS, TLS and the dynamic loader need. Nothing else of
# /etc goes into the sandbox.
ETC_FILES = (
    "/etc/resolv.conf",
    "/etc/hosts",
    "/etc/host.conf",
    "/etc/gai.conf",
    "/etc/nsswitch.conf",
    "/etc/passwd",
    "/etc/group",
    "/etc/localtime",
    "/etc/ld.so.cache",
    "/etc/ld.so.conf",
    "/etc/ld.so.conf.d",
    "/etc/ssl",
    "/etc/ca-certificates",
    "/etc/pki",
    "/etc/alternatives",
)
# Top-level dirs that are symlinks into /usr on merged-/usr systems.
USR_LINKS = ("/bin", "/sbin", "/lib", "/lib32", "/lib64")

SandboxMode = Literal["require", "warn"]


class EngineError(Exception):
    """The engine run failed."""


class EngineUnavailable(EngineError):
    """The engine cannot run on this machine."""


class SandboxUnavailable(EngineUnavailable):
    """bubblewrap is present but cannot make a sandbox here."""


class EngineTimeout(EngineError):
    """The engine did not finish in time. Its process tree was killed."""


class Engine(Protocol):
    """Takes a prompt and a clone path, and returns raw Review JSON text."""

    name: str
    model: str

    def review(self, prompt: str, clone_dir: Path) -> str: ...


class ClaudeCodeEngine:
    """Claude Code headless, read-only tools, inside bubblewrap.

    `sandbox="require"` (the CLI) refuses to run without a working sandbox.
    `sandbox="warn"` (the Action) logs a warning and runs without bubblewrap,
    with the same clean environment and temp HOME.
    """

    name = "Claude Code"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        sandbox: SandboxMode = "require",
        timeout: float = DEFAULT_TIMEOUT,
    ):
        if sandbox not in ("require", "warn"):
            raise ValueError(f"sandbox must be 'require' or 'warn', not {sandbox!r}")
        self._api_key = api_key
        self.base_url = base_url
        self.model = model
        self.sandbox = sandbox
        self.timeout = timeout

    def __repr__(self) -> str:  # never show the key
        return f"ClaudeCodeEngine(model={self.model!r}, sandbox={self.sandbox!r})"

    def review(self, prompt: str, clone_dir: Path) -> str:
        if not sys.platform.startswith("linux"):
            raise EngineUnavailable(
                "review-agent supports only Linux, because the engine sandbox "
                f"(bubblewrap) is Linux only. This platform is {sys.platform!r}."
            )
        claude = shutil.which("claude")
        if claude is None:
            raise EngineUnavailable(
                "`claude` is not on PATH. Install Claude Code and try again."
            )
        bwrap = shutil.which("bwrap")
        if bwrap is None and self.sandbox == "require":
            raise EngineUnavailable(
                "`bwrap` is not on PATH. Install bubblewrap and try again."
            )
        clone_dir = Path(clone_dir).resolve()
        claude_real = Path(claude).resolve()

        with tempfile.TemporaryDirectory(prefix="review-agent-home-") as home:
            if bwrap is not None:
                err = _probe_sandbox(bwrap)
            else:
                err = "`bwrap` is not on PATH"
            if err is None:
                return self._run_sandboxed(bwrap, claude_real, prompt, clone_dir, home)
            if self.sandbox == "require":
                raise SandboxUnavailable(
                    f"bubblewrap cannot make a sandbox here: {err}. "
                    "The engine does not run without a sandbox."
                )
            log.warning(
                "bubblewrap cannot make a sandbox here (%s). The engine runs "
                "WITHOUT a sandbox.",
                err,
            )
            return self._run_unsandboxed(claude_real, prompt, clone_dir, home)

    def _claude_args(self) -> list[str]:
        return [
            "-p",
            "--bare",
            "--restricted",
            "--tools",
            "Read,Grep,Glob",
            "--permission-mode",
            "dontAsk",
            "--strict-mcp-config",
            "--disable-slash-commands",
            "--model",
            self.model,
            "--json-schema",
            REVIEW_SCHEMA_TEXT,
            "--output-format",
            "json",
        ]

    def _env(self, home: str) -> dict[str, str]:
        return {
            "HOME": home,
            "TMPDIR": f"{home}/tmp",
            "PATH": SANDBOX_PATH,
            "ANTHROPIC_BASE_URL": self.base_url,
            "ANTHROPIC_API_KEY": self._api_key,
        }

    def _run_sandboxed(
        self, bwrap: str, claude: Path, prompt: str, clone: Path, home: str
    ) -> str:
        Path(home, "tmp").mkdir()
        env = self._env(SANDBOX_HOME)
        secret_env = {"ANTHROPIC_API_KEY": env.pop("ANTHROPIC_API_KEY")}
        args = [bwrap, *_namespace_args(), *_system_mounts()]
        args += ["--ro-bind", str(claude.parent), SANDBOX_CLAUDE_DIR]
        args += ["--ro-bind", str(clone), SANDBOX_CLONE]
        args += ["--bind", home, SANDBOX_HOME]
        args += ["--chdir", SANDBOX_CLONE]
        for k, v in env.items():
            args += ["--setenv", k, v]
        # The key goes through a pipe, not argv, so other local processes
        # cannot read it from /proc/<pid>/cmdline.
        r, w = os.pipe()
        try:
            with os.fdopen(w, "wb") as f:
                for k, v in secret_env.items():
                    f.write(b"--setenv\0" + k.encode() + b"\0" + v.encode() + b"\0")
            args += ["--args", str(r)]
            args += ["--", f"{SANDBOX_CLAUDE_DIR}/{claude.name}", *self._claude_args()]
            return self._run(args, prompt, cwd=None, env={}, pass_fds=(r,))
        finally:
            os.close(r)

    def _run_unsandboxed(
        self, claude: Path, prompt: str, clone: Path, home: str
    ) -> str:
        Path(home, "tmp").mkdir()
        args = [str(claude), *self._claude_args()]
        return self._run(args, prompt, cwd=clone, env=self._env(home), pass_fds=())

    def _run(
        self,
        args: list[str],
        prompt: str,
        *,
        cwd: Path | None,
        env: dict[str, str],
        pass_fds: tuple[int, ...],
    ) -> str:
        proc = subprocess.Popen(
            args,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            pass_fds=pass_fds,
            start_new_session=True,
            text=True,
        )
        try:
            out, err = proc.communicate(prompt, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            proc.communicate()
            raise EngineTimeout(
                f"The engine did not finish in {self.timeout:g} seconds. "
                "Its processes were stopped."
            ) from None
        except BaseException:
            _kill_tree(proc)
            proc.communicate()
            raise
        return _parse_output(proc.returncode, out, err)


def _kill_tree(proc: subprocess.Popen) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(proc.pid, signal.SIGKILL)


def _parse_output(returncode: int, out: str, err: str) -> str:
    tail = "\n".join(err.strip().splitlines()[-20:])
    if returncode != 0:
        raise EngineError(f"The engine stopped with exit code {returncode}.\n{tail}")
    try:
        result = json.loads(out)
    except ValueError:
        raise EngineError("The engine output is not JSON.") from None
    if not isinstance(result, dict) or result.get("is_error"):
        detail = result.get("result") if isinstance(result, dict) else None
        raise EngineError(f"The engine reported an error: {detail!r}")
    structured = result.get("structured_output")
    if structured is not None:
        return json.dumps(structured)
    text = result.get("result")
    if not isinstance(text, str) or not text.strip():
        raise EngineError("The engine returned no Review JSON.")
    return text


def _namespace_args() -> list[str]:
    # --unshare-all gives new user, PID, IPC, UTS and cgroup namespaces;
    # --share-net keeps the network so the engine can reach its endpoint.
    return [
        "--unshare-all",
        "--share-net",
        "--die-with-parent",
        "--new-session",
        "--clearenv",
    ]


def _system_mounts() -> list[str]:
    args = ["--ro-bind", "/usr", "/usr"]
    for d in USR_LINKS:
        if os.path.islink(d):
            args += ["--symlink", os.readlink(d), d]
        elif os.path.isdir(d):
            args += ["--ro-bind", d, d]
    for f in ETC_FILES:
        # Bind the target of a symlink (e.g. resolv.conf -> /run/...), since
        # the link target is not in the sandbox.
        args += ["--ro-bind-try", os.path.realpath(f), f]
    args += ["--proc", "/proc", "--dev", "/dev"]
    return args


def _probe_sandbox(bwrap: str) -> str | None:
    """Run `true` with the same namespaces and mounts. Returns an error or None."""
    true = shutil.which("true", path="/usr/bin:/bin") or "/usr/bin/true"
    try:
        p = subprocess.run(
            [bwrap, *_namespace_args(), *_system_mounts(), "--", true],
            env={},
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return str(e)
    if p.returncode != 0:
        return p.stderr.strip() or f"exit code {p.returncode}"
    return None
