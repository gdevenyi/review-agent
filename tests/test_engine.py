"""Seam: Engine.review(prompt, clone_dir) on ClaudeCodeEngine.

These tests replace `claude` with a fake script. Tests that need a working
bubblewrap run the real `bwrap`, so they check the real sandbox.
"""

import json
import logging
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from review_agent.engine import (
    ClaudeCodeEngine,
    EngineError,
    EngineTimeout,
    EngineUnavailable,
    SandboxUnavailable,
)
from review_agent.schema import REVIEW_SCHEMA


def make_bin(dir_: Path, name: str, script: str) -> Path:
    dir_.mkdir(parents=True, exist_ok=True)
    path = dir_ / name
    path.write_text(script)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def engine(**kw) -> ClaudeCodeEngine:
    kw.setdefault("base_url", "https://example.invalid/anthropic")
    kw.setdefault("api_key", "test-engine-key")
    return ClaudeCodeEngine(**kw)


def test_missing_claude_gives_clear_error(tmp_path, monkeypatch):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    bwrap = shutil.which("bwrap") or "/usr/bin/bwrap"
    (bin_ / "bwrap").symlink_to(bwrap)
    monkeypatch.setenv("PATH", str(bin_))
    with pytest.raises(EngineUnavailable, match="`claude` is not on PATH"):
        engine().review("prompt", tmp_path)


def test_missing_bwrap_gives_clear_error(tmp_path, monkeypatch):
    bin_ = tmp_path / "bin"
    make_bin(bin_, "claude", "#!/bin/sh\nexit 0\n")
    monkeypatch.setenv("PATH", str(bin_))
    with pytest.raises(EngineUnavailable, match="`bwrap` is not on PATH"):
        engine().review("prompt", tmp_path)


def test_platform_other_than_linux_gives_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    with pytest.raises(EngineUnavailable, match="supports only Linux"):
        engine().review("prompt", tmp_path)


# A fake `claude` that reports what it can see, as Claude Code's
# `--output-format json` result with the report as `structured_output`.
REPORTER = r"""#!/usr/bin/env python3
import json, os, sys

def can_write(d):
    try:
        with open(os.path.join(d, "probe"), "w") as f:
            f.write("x")
        return True
    except OSError:
        return False

def can_read(p):
    try:
        with open(p) as f:
            return f.read()
    except OSError:
        return None

report = {
    "cwd": os.getcwd(),
    "env": dict(os.environ),
    "argv": sys.argv[1:],
    "prompt": sys.stdin.read(),
    "real_home_exists": os.path.exists(REAL_HOME),
    "canary": can_read(CANARY),
    "clone_file": can_read("hello.py"),
    "clone_writable": can_write("."),
    "home_writable": can_write(os.environ.get("HOME", "/nonexistent")),
    "tmpdir_writable": can_write(os.environ.get("TMPDIR", "/nonexistent")),
}
print(json.dumps({"type": "result", "is_error": False, "result": "",
                  "structured_output": report}))
"""

needs_bwrap = pytest.mark.skipif(
    shutil.which("bwrap") is None, reason="needs bubblewrap"
)


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A clone, a canary file next to it, and a fake `claude` on PATH."""
    clone = tmp_path / "clone"
    clone.mkdir()
    (clone / "hello.py").write_text("print('hello')\n")
    canary = tmp_path / "canary.txt"
    canary.write_text("CANARY-5f2c9a")
    script = REPORTER.replace("REAL_HOME", repr(str(Path.home()))).replace(
        "CANARY", repr(str(canary))
    )
    bin_ = tmp_path / "bin"
    make_bin(bin_, "claude", script)
    monkeypatch.setenv("PATH", f"{bin_}:/usr/bin:/bin")
    monkeypatch.setenv("REVIEW_AGENT_GITHUB_TOKEN", "ghp_must_not_leak")
    monkeypatch.setenv("GH_TOKEN", "ghp_must_not_leak")
    return clone


EXPECTED_ENV = {
    "HOME",
    "PATH",
    "TMPDIR",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_API_KEY",
    "CLAUDE_CODE_DISABLE_CLAUDE_MDS",
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY",
}


@needs_bwrap
def test_sandboxed_engine_sees_only_the_clone_and_engine_env(world):
    raw = engine(model="glm-test").review("Review this PR.", world)
    seen = json.loads(raw)

    assert seen["cwd"] == "/repo"
    assert seen["clone_file"] == "print('hello')\n"
    # bwrap sets PWD; python3 (the fake claude) sets LC_CTYPE itself.
    assert set(seen["env"]) - {"PWD", "LC_CTYPE"} == EXPECTED_ENV
    assert seen["env"]["ANTHROPIC_API_KEY"] == "test-engine-key"
    assert seen["env"]["ANTHROPIC_BASE_URL"] == "https://example.invalid/anthropic"
    assert "ghp_must_not_leak" not in raw
    assert seen["real_home_exists"] is False
    assert seen["canary"] is None
    assert seen["clone_writable"] is False
    assert seen["home_writable"] is True
    assert seen["tmpdir_writable"] is True
    assert seen["prompt"] == "Review this PR."
    # Second guard (after --restricted) against CLAUDE.md from the clone.
    assert seen["env"]["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1"
    assert seen["env"]["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"


@needs_bwrap
def test_engine_runs_claude_headless_with_read_only_tools(world):
    argv = json.loads(engine(model="glm-test").review("p", world))["argv"]

    for flag in (
        "-p",
        "--restricted",
        "--strict-mcp-config",
        "--disable-slash-commands",
    ):
        assert flag in argv
    # --bare removes the Grep and Glob tools (claude 2.1.30x).
    assert "--bare" not in argv

    def value(flag):
        return argv[argv.index(flag) + 1]

    assert value("--tools") == "Read,Grep,Glob"
    assert value("--permission-mode") == "dontAsk"
    assert value("--model") == "glm-test"
    assert value("--output-format") == "stream-json"
    assert "--verbose" in argv
    assert json.loads(value("--json-schema")) == REVIEW_SCHEMA


@pytest.fixture
def broken_bwrap(world):
    """A `bwrap` that fails like one with user namespaces blocked."""
    make_bin(
        world.parent / "bin",
        "bwrap",
        "#!/bin/sh\necho 'bwrap: No permissions to create new namespace' >&2\nexit 1\n",
    )
    return world


def test_cli_mode_refuses_to_run_without_a_working_sandbox(broken_bwrap):
    with pytest.raises(SandboxUnavailable, match="No permissions"):
        engine(sandbox="require").review("p", broken_bwrap)


def test_action_mode_warns_and_runs_without_sandbox(broken_bwrap, caplog):
    raw = engine(sandbox="warn").review("Review this PR.", broken_bwrap)
    seen = json.loads(raw)

    assert "WITHOUT a sandbox" in caplog.text
    assert Path(seen["cwd"]) == broken_bwrap.resolve()
    assert seen["prompt"] == "Review this PR."
    assert set(seen["env"]) - {"PWD", "LC_CTYPE"} == EXPECTED_ENV
    assert "ghp_must_not_leak" not in raw
    assert Path(seen["env"]["HOME"]) != Path.home()
    assert seen["home_writable"] is True


def test_engine_failure_is_an_error(broken_bwrap):
    make_bin(
        broken_bwrap.parent / "bin",
        "claude",
        "#!/bin/sh\necho 'API Error: 401' >&2\nexit 1\n",
    )
    with pytest.raises(EngineError, match="401"):
        engine(sandbox="warn").review("p", broken_bwrap)


@needs_bwrap
def test_timeout_kills_the_engine_process_tree(world):
    marker = f"{os.getpid()}{time.monotonic_ns() % 100000}"
    make_bin(
        world.parent / "bin",
        "claude",
        f"#!/bin/sh\nsleep {marker} &\nsleep {marker}\n",
    )
    errors = []

    def run():
        try:
            engine(timeout=1).review("p", world)
        except Exception as e:
            errors.append(e)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout=30)
    assert not t.is_alive(), "review() did not return after the timeout"
    assert len(errors) == 1
    assert isinstance(errors[0], EngineTimeout)
    time.sleep(0.5)
    left = subprocess.run(
        ["pgrep", "-f", f"sleep {marker}"], capture_output=True, text=True
    )
    assert left.stdout == ""


# A fake `claude` that streams `--output-format stream-json` events like the
# real CLI: init, assistant turns with text, thinking and tool calls, tool
# results, then the result event. After the tool calls it waits (up to 10 s)
# for WAIT_FOR to exist. The test makes that file when it sees the progress
# line, so the run can finish only if review() logs events while the engine
# still runs.
STREAMER = r"""#!/usr/bin/env python3
import json, os, sys, time

sys.stdin.read()
root = os.getcwd()

def emit(event):
    print(json.dumps(event), flush=True)
    time.sleep(0.05)

def assistant(*content):
    emit({"type": "assistant", "message": {"role": "assistant",
          "content": list(content)}})

def tool(name, **inp):
    return {"type": "tool_use", "id": "t-" + name, "name": name, "input": inp}

emit({"type": "system", "subtype": "init", "model": "glm-test", "cwd": root,
      "tools": ["Glob", "Grep", "Read", "StructuredOutput"]})
assistant({"type": "text", "text": "SECRET-ASSISTANT-TEXT"})
assistant({"type": "thinking", "thinking": "SECRET-THINKING"})
assistant(tool("Glob", pattern="**/*.py"))
assistant(tool("Grep", pattern="def \x1b[31madd\n", path=root + "/src"))
emit({"type": "user", "message": {"role": "user", "content": [
      {"type": "tool_result", "tool_use_id": "t-Grep",
       "content": "SECRET-TOOL-RESULT"}]},
      "tool_use_result": {"content": "SECRET-TOOL-RESULT"}})
assistant(tool("Read", file_path=root + "/src/" + "x" * 300 + ".py"))
assistant(tool("Read", file_path=root + "/src/a.py"))
deadline = time.monotonic() + 10
while not os.path.exists(WAIT_FOR):
    if time.monotonic() > deadline:
        sys.exit(3)
    time.sleep(0.05)
time.sleep(SLEEP_AT_END)
review = {"summary": "s", "findings": []}
assistant(tool("StructuredOutput", **review))
emit({"type": "result", "subtype": "success", "is_error": False,
      "num_turns": 7, "duration_ms": 12345, "total_cost_usd": 0.0225,
      "usage": {"input_tokens": 4224, "output_tokens": 236},
      "result": "SECRET-RESULT-TEXT", "structured_output": review})
"""


def streamer_script(wait_for: str, sleep_at_end: float = 0.0) -> str:
    return STREAMER.replace("WAIT_FOR", repr(wait_for)).replace(
        "SLEEP_AT_END", repr(sleep_at_end)
    )


class _Recorder(logging.Handler):
    """Records review_agent INFO messages. Makes the file `touch` when it
    sees a message that contains `trigger`."""

    def __init__(self, trigger, touch):
        super().__init__(logging.INFO)
        self.messages = []
        self.trigger, self.touch = trigger, touch

    def emit(self, record):
        msg = record.getMessage()
        self.messages.append(msg)
        if self.trigger in msg:
            Path(self.touch).touch()


@pytest.fixture
def recorder():
    made = []
    logger = logging.getLogger("review_agent")
    old = logger.level
    logger.setLevel(logging.DEBUG)

    def make(trigger, touch):
        r = _Recorder(trigger, touch)
        logger.addHandler(r)
        made.append(r)
        return r

    yield make
    for r in made:
        logger.removeHandler(r)
    logger.setLevel(old)


def test_engine_logs_progress_live_while_it_runs(broken_bwrap, recorder):
    wait_for = broken_bwrap.parent / "seen"
    make_bin(broken_bwrap.parent / "bin", "claude", streamer_script(str(wait_for)))
    rec = recorder("Engine: Read src/a.py", wait_for)

    raw = engine(sandbox="warn").review("p", broken_bwrap)

    assert json.loads(raw) == {"summary": "s", "findings": []}
    progress = [m for m in rec.messages if m.startswith("Engine")]
    assert progress[0] == "Engine session started: model glm-test"
    assert progress[1] == "Engine: Glob **/*.py"
    # Control characters (ESC, newline) are removed.
    assert progress[2] == "Engine: Grep def [31madd in src"
    assert progress[3].startswith("Engine: Read src/xxx")
    assert len(progress[3]) <= 120
    assert progress[4] == "Engine: Read src/a.py"
    assert progress[5] == "Engine: StructuredOutput"
    assert progress[6] == (
        "Engine finished: 7 turns, 5 tool calls, 12 s, "
        "cost $0.0225, 4224 input tokens, 236 output tokens"
    )
    assert "SECRET" not in "\n".join(rec.messages)


def test_engine_logs_a_heartbeat_while_it_runs(broken_bwrap, recorder):
    wait_for = broken_bwrap.parent / "seen"
    make_bin(
        broken_bwrap.parent / "bin",
        "claude",
        streamer_script(str(wait_for), sleep_at_end=0.5),
    )
    rec = recorder("Engine: Read src/a.py", wait_for)

    engine(sandbox="warn", heartbeat=0.1).review("p", broken_bwrap)

    beats = [m for m in rec.messages if m.startswith("Engine running:")]
    assert any(m.endswith(" s, 4 tool calls") for m in beats), rec.messages
    for m in beats:
        assert re.fullmatch(r"Engine running: \d+ s, \d+ tool calls", m)


@needs_bwrap
def test_sandboxed_engine_logs_paths_relative_to_the_clone(world, recorder):
    # Inside the sandbox the clone is /repo (read-only), so the fake waits
    # for a file that the test makes in the clone on the host.
    make_bin(world.parent / "bin", "claude", streamer_script("/repo/seen"))
    rec = recorder("Engine: Read src/a.py", world / "seen")

    raw = engine().review("p", world)

    assert json.loads(raw) == {"summary": "s", "findings": []}
    assert "Engine: Read src/a.py" in rec.messages
    assert "Engine: Grep def [31madd in src" in rec.messages


def test_engine_error_result_in_the_stream_is_an_error(broken_bwrap):
    make_bin(
        broken_bwrap.parent / "bin",
        "claude",
        "#!/bin/sh\ncat >/dev/null\n"
        'echo \'{"type":"system","subtype":"init","model":"m"}\'\n'
        'echo \'{"type":"result","is_error":true,"result":"API Error: 529"}\'\n',
    )
    with pytest.raises(EngineError, match="529"):
        engine(sandbox="warn").review("p", broken_bwrap)
