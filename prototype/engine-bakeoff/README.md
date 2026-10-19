# PROTOTYPE: engine bake-off (throwaway)

Answers "Bake-off: Codex exec review versus Claude Code -p on Z.AI" (gdevenyi/review-agent#6).
Not production code. The verdict lives on the issue; this branch keeps the harness as a primary source.

- `prompt.md`, `review.schema.json`: the agreed Review format given to every engine.
- `run.py`: runs Codex (`exec review`, `exec` + schema, `exec` + prompt-only JSON), Claude Code `-p --bare`,
  OpenCode `run`, Cline on local worktrees of DouglasNeuroInformatics/OpenDataCapture PRs 1818, 1806, 1810.
  Posts nothing to GitHub.
- `report.py` → `report.html`: side-by-side output per PR, engine and model, with a check that each
  Finding's (path, line, side) is inside a diff hunk.
