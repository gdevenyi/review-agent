"""The Engine seam and its one adapter, ClaudeCodeEngine.

See ADR 0001 (the engine gets no shell) and ADR 0002 (the engine runs in
bubblewrap, Linux only).
"""

import contextlib
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Literal, Protocol

from review_agent.schema import REVIEW_SCHEMA_TEXT

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.z.ai/api/anthropic"
DEFAULT_MODEL = "glm-5.3-flash"
DEFAULT_TIMEOUT = 45 * 60
DEFAULT_HEARTBEAT = 30  # seconds between "Engine running" log lines

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

    def review(
        self, prompt: str, clone_dir: Path, *, timeout: float | None = None
    ) -> str:
        """`timeout`: seconds for this call (default: the engine's own)."""
        ...


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
        heartbeat: float = DEFAULT_HEARTBEAT,
    ):
        if sandbox not in ("require", "warn"):
            raise ValueError(f"sandbox must be 'require' or 'warn', not {sandbox!r}")
        self._api_key = api_key
        self.base_url = base_url
        self.model = model
        self.sandbox = sandbox
        self.timeout = timeout
        self.heartbeat = heartbeat

    def __repr__(self) -> str:  # never show the key
        return f"ClaudeCodeEngine(model={self.model!r}, sandbox={self.sandbox!r})"

    def review(
        self, prompt: str, clone_dir: Path, *, timeout: float | None = None
    ) -> str:
        timeout = self.timeout if timeout is None else timeout
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
            Path(home, "tmp").mkdir()  # TMPDIR of the engine
            if bwrap is not None:
                err = _probe_sandbox(bwrap)
            else:
                err = "`bwrap` is not on PATH"
            if err is None:
                return self._run_sandboxed(
                    bwrap, claude_real, prompt, clone_dir, home, timeout
                )
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
            return self._run_unsandboxed(claude_real, prompt, clone_dir, home, timeout)

    def _claude_args(self) -> list[str]:
        return [
            # No --bare: in claude 2.1.30x it removes the Grep and Glob tools.
            # --restricted ignores the clone's settings files (so its hooks),
            # and the env below turns off CLAUDE.md and memory loading.
            "-p",
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
            # stream-json gives one event per line while the engine runs, so
            # the progress can go to the log live. It needs --verbose.
            "--output-format",
            "stream-json",
            "--verbose",
        ]

    def _env(self, home: str) -> dict[str, str]:
        return {
            "HOME": home,
            "TMPDIR": f"{home}/tmp",
            "PATH": SANDBOX_PATH,
            "ANTHROPIC_BASE_URL": self.base_url,
            "ANTHROPIC_API_KEY": self._api_key,
            "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1",
            "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
        }

    def _run_sandboxed(
        self,
        bwrap: str,
        claude: Path,
        prompt: str,
        clone: Path,
        home: str,
        timeout: float,
    ) -> str:
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
            return self._run(
                args,
                prompt,
                cwd=None,
                env={},
                pass_fds=(r,),
                timeout=timeout,
                root=SANDBOX_CLONE,
            )
        finally:
            os.close(r)

    def _run_unsandboxed(
        self, claude: Path, prompt: str, clone: Path, home: str, timeout: float
    ) -> str:
        args = [str(claude), *self._claude_args()]
        return self._run(
            args,
            prompt,
            cwd=clone,
            env=self._env(home),
            pass_fds=(),
            timeout=timeout,
            root=str(clone),
        )

    def _run(
        self,
        args: list[str],
        prompt: str,
        *,
        cwd: Path | None,
        env: dict[str, str],
        pass_fds: tuple[int, ...],
        timeout: float,
        root: str,
    ) -> str:
        """Run the engine and read its stream-json events as they arrive.

        Progress goes to the log live. The return value comes from the
        final `result` event."""
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
            encoding="utf-8",
            errors="replace",
        )
        progress = _Progress(root)
        timed_out = threading.Event()
        done = threading.Event()
        err_lines: list[str] = []

        def feed() -> None:
            with contextlib.suppress(OSError):  # the engine can exit early
                proc.stdin.write(prompt)
                proc.stdin.close()

        def drain_stderr() -> None:
            err_lines.extend(proc.stderr)

        def watch() -> None:
            # Heartbeat, and the timeout: kill the whole process group.
            deadline = time.monotonic() + timeout
            next_beat = time.monotonic() + self.heartbeat
            while True:
                now = time.monotonic()
                if done.wait(max(0.0, min(deadline, next_beat) - now)):
                    return
                now = time.monotonic()
                if now >= deadline:
                    timed_out.set()
                    _kill_tree(proc)
                    return
                if now >= next_beat:
                    progress.heartbeat()
                    next_beat = now + self.heartbeat

        threads = [
            threading.Thread(target=f, daemon=True) for f in (feed, drain_stderr, watch)
        ]
        for t in threads:
            t.start()
        result_line = ""
        try:
            for line in proc.stdout:
                if progress.event(line):
                    result_line = line
            proc.wait()
        except BaseException:
            _kill_tree(proc)
            proc.wait()
            raise
        finally:
            done.set()
            for t in threads:
                t.join(timeout=5)
        if timed_out.is_set():
            raise EngineTimeout(
                f"The engine did not finish in {timeout:.0f} seconds. "
                "Its processes were stopped."
            )
        return _parse_output(proc.returncode, result_line, "".join(err_lines))


def _kill_tree(proc: subprocess.Popen) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(proc.pid, signal.SIGKILL)


MAX_PROGRESS_LINE = 120
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _clean(text: str) -> str:
    """One safe log line: no control characters, at most MAX_PROGRESS_LINE."""
    text = _CONTROL.sub("", text)
    if len(text) > MAX_PROGRESS_LINE:
        text = text[: MAX_PROGRESS_LINE - 3] + "..."
    return text


class _Progress:
    """Logs engine progress from stream-json events, at INFO.

    It logs only the session start, the tool names with their path or
    pattern, a heartbeat and the final counts. Never assistant text,
    thinking, tool results or file contents: they can quote private code."""

    def __init__(self, root: str):
        self.root = root.rstrip("/") + "/"
        self.start = time.monotonic()
        self.tool_calls = 0

    def event(self, line: str) -> bool:
        """Log one event. Returns True if it is the `result` event."""
        try:
            e = json.loads(line)
        except ValueError:
            return False
        if not isinstance(e, dict):
            return False
        kind = e.get("type")
        if kind == "system" and e.get("subtype") == "init":
            log.info(_clean(f"Engine session started: model {e.get('model')}"))
        elif kind == "assistant":
            content = (e.get("message") or {}).get("content")
            for block in content if isinstance(content, list) else ():
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    self.tool_calls += 1
                    log.info(_clean(self._tool(block)))
        elif kind == "result":
            log.info(self._finished(e))
            return True
        return False

    def heartbeat(self) -> None:
        log.info(
            "Engine running: %.0f s, %d tool calls",
            time.monotonic() - self.start,
            self.tool_calls,
        )

    def _rel(self, path: object) -> str:
        path = str(path)
        if path + "/" == self.root:
            return "."
        return path.removeprefix(self.root)

    def _tool(self, block: dict) -> str:
        name = str(block.get("name"))
        inp = block.get("input")
        inp = inp if isinstance(inp, dict) else {}
        parts = [f"Engine: {name}"]
        if name == "Read" and "file_path" in inp:
            parts.append(self._rel(inp["file_path"]))
        elif name in ("Grep", "Glob"):
            if "pattern" in inp:
                parts.append(str(inp["pattern"]))
            if "path" in inp:
                parts.append(f"in {self._rel(inp['path'])}")
        return " ".join(parts)

    def _finished(self, e: dict) -> str:
        parts = [
            f"{e.get('num_turns', '?')} turns",
            f"{self.tool_calls} tool calls",
        ]
        ms = e.get("duration_ms")
        secs = ms / 1000 if isinstance(ms, int | float) else self._elapsed()
        parts.append(f"{secs:.0f} s")
        cost = e.get("total_cost_usd")
        if isinstance(cost, int | float):
            parts.append(f"cost ${cost:.4f}")
        usage = e.get("usage") if isinstance(e.get("usage"), dict) else {}
        for key, label in (
            ("input_tokens", "input tokens"),
            ("output_tokens", "output tokens"),
        ):
            if isinstance(usage.get(key), int):
                parts.append(f"{usage[key]} {label}")
        return "Engine finished: " + ", ".join(parts)

    def _elapsed(self) -> float:
        return time.monotonic() - self.start


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
