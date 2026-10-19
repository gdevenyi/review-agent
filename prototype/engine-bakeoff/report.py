"""PROTOTYPE, throwaway: build one HTML page that compares engine output per Target PR.

Usage: python report.py <worktree dir prefix> <out dir> <report.html>
For each Finding it checks whether (path, line, side) falls inside a diff hunk,
which is what the GitHub Reviews API needs for an inline comment.
"""

import html
import json
import re
import subprocess
import sys
from pathlib import Path

WT, REPORT = sys.argv[1], Path(sys.argv[2])
RUNS = [
    (lbl, Path(d)) for lbl, d in (a.split("=", 1) for a in sys.argv[3:])
]  # "label=outdir"
PRS = [1818, 1806, 1810]
ENGINES = ["codex-review", "codex-exec", "codex-json", "claude", "opencode", "cline"]
REPO = "DouglasNeuroInformatics/OpenDataCapture"


def hunk_lines(pr, base):
    """Map path -> {"RIGHT": set(lines), "LEFT": set(lines)} for lines inside diff hunks."""
    diff = subprocess.run(
        [
            "git",
            "--no-pager",
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--no-color",
            "-U3",
            f"{base}...HEAD",
        ],
        cwd=f"{WT}-{pr}",
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    lines, path, old, new = {}, None, 0, 0
    for row in diff.splitlines():
        if row.startswith("+++ "):
            path = row[6:] if row.startswith("+++ b/") else None
            lines.setdefault(path, {"RIGHT": set(), "LEFT": set()})
        elif m := re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)", row):
            old, new = int(m[1]), int(m[2])
        elif path and row[:1] in "+- " and not row.startswith(("---", "+++")):
            if row[:1] == "+":
                lines[path]["RIGHT"].add(new)
                new += 1
            elif row[:1] == "-":
                lines[path]["LEFT"].add(old)
                old += 1
            else:
                lines[path]["RIGHT"].add(new)
                lines[path]["LEFT"].add(old)
                old, new = old + 1, new + 1
    return lines


def classify(f, hunks):
    if not f.get("path") or f.get("line") is None:
        return "general"
    side = f.get("side") or "RIGHT"
    rng = range(f.get("start_line") or f["line"], f["line"] + 1)
    ok = f["path"] in hunks and all(n in hunks[f["path"]][side] for n in rng)
    return "anchored" if ok else "outside-diff"


def load(pr, engine, out):
    stem = out / f"{pr}-{engine}"
    meta = (
        json.loads(stem.with_suffix(".meta.json").read_text())
        if stem.with_suffix(".meta.json").exists()
        else {}
    )
    review, err = None, None
    try:
        review = json.loads(stem.with_suffix(".json").read_text())
    except Exception as e:  # noqa: BLE001 - prototype: show any failure in the page
        if stem.with_suffix(
            ".json"
        ).exists():  # codex review ignores the schema and writes its own text
            err = (
                "Not JSON (engine ignored the schema). Raw output:\n\n"
                + stem.with_suffix(".json").read_text()
            )
        else:
            tail = (
                stem.with_suffix(".stderr").read_text()[-800:]
                if stem.with_suffix(".stderr").exists()
                else ""
            )
            err = f"{type(e).__name__}: {e}\n{tail}"
    return meta, review, err


def esc(s):
    return html.escape(str(s or ""))


def card(pr, engine, hunks, lbl, out):
    meta, review, err = load(pr, engine, out)
    if not meta and review is None:
        return ""
    head = f"<h3>{engine} · {lbl}</h3><p class=meta>exit {meta.get('exit', '?')} · {meta.get('seconds', '?')} s</p>"
    if review is None:
        return f"<div class=card>{head}<pre class=err>{esc(err)}</pre></div>"
    rows, counts = [], {"anchored": 0, "outside-diff": 0, "general": 0}
    for f in review.get("findings", []):
        k = classify(f, hunks)
        counts[k] += 1
        where = (
            "General"
            if k == "general"
            else f"{f['path']}:{f.get('start_line') or ''}{'-' if f.get('start_line') else ''}{f['line']} {f.get('side') or ''}"
        )
        sug = (
            f"<pre class=sug>{esc(f['suggestion'])}</pre>"
            if f.get("suggestion")
            else ""
        )
        rows.append(
            f"<li class={k}><span class=lab>{esc(f['label'])}</span> <code>{esc(where)}</code> <span class=tag>{k}</span>"
            f"<p>{esc(f['body'])}</p>{sug}</li>"
        )
    stats = " · ".join(f"{v} {k}" for k, v in counts.items())
    return (
        f"<div class=card>{head}<p class=meta>{len(review.get('findings', []))} findings: {stats}</p>"
        f"<p class=summary>{esc(review.get('summary'))}</p><ol>{''.join(rows)}</ol></div>"
    )


sections = []
for pr in PRS:
    meta = next((m for _, o in RUNS for e in ENGINES if (m := load(pr, e, o)[0])), {})
    hunks = hunk_lines(pr, meta["base"]) if meta.get("base") else {}
    url = f"https://github.com/{REPO}/pull/{pr}"
    sections.append(
        f"<section><h2><a href='{url}'>PR {pr}</a></h2><div class=grid>"
        + "".join(card(pr, e, hunks, lbl, o) for e in ENGINES for lbl, o in RUNS)
        + "</div></section>"
    )

REPORT.write_text(f"""<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Engine Bake-off</title>
<style>
:root{{--bg:#fbfbfa;--fg:#1d1d1b;--muted:#6b6b66;--card:#fff;--line:#e3e2dd;--ok:#2f7d4f;--warn:#b5651d;--info:#3a6ea5;--code:#f2f1ec}}
@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{--bg:#161615;--fg:#e8e7e2;--muted:#9a9993;--card:#1f1f1d;--line:#33332f;--ok:#6cc495;--warn:#e0a060;--info:#7fb0e6;--code:#2a2a27}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;margin:0;padding:16px}}
h1{{font-size:1.4rem}} h2 a{{color:var(--fg)}} .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px;min-width:0}}
.meta{{color:var(--muted);font-size:.85rem;margin:.2rem 0}} .summary{{font-style:italic}}
ol{{padding-left:1.2rem}} li{{margin:.6rem 0}} li p{{margin:.3rem 0}} code,pre{{background:var(--code);border-radius:4px;font-size:.82rem}}
pre{{padding:6px;white-space:pre-wrap;overflow-wrap:anywhere}} code{{padding:0 3px;overflow-wrap:anywhere}}
.lab{{font-weight:600}} .tag{{font-size:.75rem;color:var(--muted)}}
li.anchored .tag{{color:var(--ok)}} li.outside-diff .tag{{color:var(--warn)}} li.general .tag{{color:var(--info)}} .err{{color:var(--warn)}}
</style></head><body><h1>Engine bake-off: Codex vs Claude Code on Z.AI (glm-5.3 and glm-5.3-flash)</h1>
<p class=meta>PROTOTYPE. Same prompt and schema for every engine. "anchored" = the line range is inside a diff hunk on that side, so GitHub accepts it as an inline comment; "outside-diff" would be rejected; "general" goes in the summary.</p>
{"".join(sections)}</body></html>""")
print(REPORT)
