"""PROTOTYPE, throwaway: run review engines on sample Target PRs and save raw output.

Usage: python run.py <odc-src clone> <worktree dir prefix> <codex home> <out dir>
Needs ZAI_API_KEY in the environment. Posts nothing to GitHub.
"""

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).parent
SRC, WT, CODEX_HOME, OUT = (Path(a) for a in sys.argv[1:5])
PRS = {
    1818: "fix(web): stop the record array upload parser truncating values",
    1806: "fix(instrument-bundler): bundle files with upper-case extensions",
    1810: "fix(web): scope email template languages to active languages",
}
SCHEMA = HERE / "review.schema.json"
JSON_ONLY = (
    "\n\nWhen you are done, reply with only the JSON object for the schema below, no other text.\n\n"
    + SCHEMA.read_text()
)
KEY = os.environ["ZAI_API_KEY"]
MODEL = os.environ.get("MODEL", "glm-5.3")


def git(*args, cwd):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def prompt_for(pr):
    wt = Path(f"{WT}-{pr}")
    base = git("merge-base", "main", "HEAD", cwd=wt).strip()
    guidance = "\n\n".join(
        f"### {name}\n\n{git('show', f'{base}:{name}', cwd=wt)}"
        for name in ("AGENTS.md", "CONTRIBUTING.md")
    )
    text = (HERE / "prompt.md").read_text()
    return base, text.replace("{BASE}", base).replace("{TITLE}", PRS[pr]).replace(
        "{GUIDANCE}", guidance
    )


def codex_cmd(mode, base, prompt, out_file, wt):
    # -C points Codex at the checkout; the process itself runs outside it so pnpm never reads the PR's config
    cmd = ["pnpm", "dlx", "@openai/codex", "exec", "-C", str(wt), "-m", MODEL]
    if mode == "review":
        cmd += [
            "review"
        ]  # --base cannot be combined with a custom prompt; the prompt names the base
    # project_doc_max_bytes=0 stops Codex auto-loading AGENTS.md from the PR head
    cmd += ["--ephemeral", "-c", "project_doc_max_bytes=0", "-o", str(out_file)]
    if mode == "json":
        # --output-schema made glm-5.3 answer at once with no tool use, so ask for JSON in the prompt instead
        prompt += (
            "\n\nWhen you are done, reply with only the JSON object for the schema below, no other text.\n\n"
            + SCHEMA.read_text()
        )
    else:
        cmd += ["--output-schema", str(SCHEMA)]
    return cmd + [prompt], {"CODEX_HOME": str(CODEX_HOME)}


def claude_cmd(prompt):
    cmd = [
        "claude", "-p", prompt, "--bare", "--model", MODEL,
        "--tools", "Read,Grep,Glob,Bash",
        "--allowedTools", "Read,Grep,Glob,Bash(git diff:*),Bash(git log:*),Bash(git show:*)",
        "--permission-mode", "dontAsk", "--strict-mcp-config", "--disable-slash-commands",
        "--json-schema", SCHEMA.read_text(), "--output-format", "json",
    ]  # fmt: skip
    env = {
        "ANTHROPIC_BASE_URL": "https://api.z.ai/api/anthropic",
        "ANTHROPIC_API_KEY": KEY,
        "CLAUDE_CONFIG_DIR": str(OUT / "claude-home"),
    }
    return cmd, env


def opencode_cmd(prompt):
    home = OUT / "opencode-home"
    cfg = {
        "provider": {"zai-coding-plan": {"options": {"apiKey": "{env:ZAI_API_KEY}"}}},
        "permission": {
            "edit": "deny",
            "webfetch": "deny",
            "bash": {
                "*": "deny",
                "git diff*": "allow",
                "git log*": "allow",
                "git show*": "allow",
            },
        },
    }
    env = {
        f"XDG_{d}_HOME": str(home / d.lower())
        for d in ("CONFIG", "DATA", "STATE", "CACHE")
    }
    env["OPENCODE_CONFIG_CONTENT"] = json.dumps(cfg)
    cmd = [
        "opencode",
        "run",
        "--standalone",
        "-m",
        f"zai-coding-plan/{MODEL}",
        "--auto",
        prompt + JSON_ONLY,
    ]
    return cmd, env


def cline_cmd(prompt, wt):
    home = OUT.parent / "cline-home"
    cmd = [
        "cline", "-p", "--json", "--cwd", str(wt), "-t", "1800",
        "--config", str(home / "config"), "--data-dir", str(home / "data"), prompt + JSON_ONLY,
    ]  # fmt: skip
    return cmd, {}


def extract_review(text):
    """Find the last JSON object with a "findings" key, also inside JSON-encoded event strings."""
    found = []

    def scan(s):
        dec = json.JSONDecoder()
        for i, ch in enumerate(s):
            if ch == "{":
                try:
                    obj, _ = dec.raw_decode(s, i)
                except ValueError:
                    continue
                if isinstance(obj, dict) and "findings" in obj:
                    found.append(obj)
                else:
                    walk(obj)

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str) and "findings" in o:
            scan(o)

    scan(text)
    return found[-1] if found else None


def run(pr, engine):
    base, prompt = prompt_for(pr)
    stem = OUT / f"{pr}-{engine}"
    if engine == "claude":
        cmd, extra = claude_cmd(prompt)
    elif engine == "opencode":
        cmd, extra = opencode_cmd(prompt)
    elif engine == "cline":
        cmd, extra = cline_cmd(prompt, Path(f"{WT}-{pr}"))
    else:
        cmd, extra = codex_cmd(
            engine.split("-")[1],
            base,
            prompt,
            stem.with_suffix(".json"),
            Path(f"{WT}-{pr}"),
        )
    t0 = time.monotonic()
    cwd = OUT if engine.startswith(("codex", "cline")) else f"{WT}-{pr}"
    p = subprocess.run(
        cmd,
        cwd=cwd,
        env={**os.environ, **extra},
        capture_output=True,
        text=True,
        timeout=1800,
        check=False,
    )
    secs = round(time.monotonic() - t0, 1)
    stem.with_suffix(".stdout").write_text(p.stdout)
    stem.with_suffix(".stderr").write_text(p.stderr)
    if engine == "claude" and p.returncode == 0:
        d = json.loads(p.stdout)
        out = d.get("structured_output") or d.get("result")
        stem.with_suffix(".json").write_text(
            out if isinstance(out, str) else json.dumps(out, indent=2)
        )
    if engine in ("opencode", "cline"):
        review = extract_review(p.stdout)
        if review is not None:
            stem.with_suffix(".json").write_text(json.dumps(review, indent=2))
    if engine == "codex-json" and stem.with_suffix(".json").exists():
        raw = stem.with_suffix(".json").read_text()
        stem.with_suffix(".raw.txt").write_text(raw)
        stem.with_suffix(".json").write_text(raw[raw.find("{") : raw.rfind("}") + 1])
    meta = {
        "pr": pr,
        "engine": engine,
        "model": MODEL,
        "base": base,
        "exit": p.returncode,
        "seconds": secs,
    }
    stem.with_suffix(".meta.json").write_text(json.dumps(meta))
    print(meta, flush=True)
    return meta


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "claude-home").mkdir(exist_ok=True)
    engines = [
        "codex-review",
        "codex-exec",
        "codex-json",
        "claude",
        "opencode",
        "cline",
    ]
    jobs = [(pr, e) for pr in PRS for e in engines]
    if sys.argv[5:]:  # optional "pr:engine" filters
        jobs = [(int(p), e) for p, e in (a.split(":") for a in sys.argv[5:])]
    with ThreadPoolExecutor(max_workers=3) as ex:
        list(ex.map(lambda j: run(*j), jobs))
