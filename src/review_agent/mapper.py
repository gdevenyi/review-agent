"""ReviewMapper: raw Review JSON from the engine -> the Review to post.

No network. The steps of `ReviewMapper.map`:

1. Drop Findings on paths that match the skip globs.
2. Sort by severity: `issue (blocking)` > `suggestion` > `question` > `nit`.
3. Check each inline anchor against the hunks of the GitHub diff (the rule of
   `report.py` on branch `prototype/engine-bakeoff`). A Finding that fails
   goes under "General" in the Review body.
4. Keep at most `finding_limit` inline comments, the most severe first.
5. Start each comment with its Conventional Comments label; a `suggestion`
   becomes a GitHub suggestion block (RIGHT side only).
6. End the body with the AI Disclosure.

The output filter comes in #16.
"""

from __future__ import annotations

import fnmatch
import json
import logging
import re
from dataclasses import dataclass, field

import jsonschema

from review_agent.config import DEFAULT_FINDING_LIMIT
from review_agent.errors import ReviewAgentError
from review_agent.schema import REVIEW_SCHEMA

log = logging.getLogger("review_agent")


class InvalidReviewJSON(ReviewAgentError):
    """The engine output is not JSON, or does not match the Review schema."""


@dataclass(frozen=True)
class InlineComment:
    """One inline comment, in the shape of GitHub's review comment payload."""

    path: str
    line: int
    side: str
    body: str
    start_line: int | None = None
    start_side: str | None = None

    def to_payload(self) -> dict:
        out: dict = {
            "path": self.path,
            "line": self.line,
            "side": self.side,
            "body": self.body,
        }
        if self.start_line is not None:
            out["start_line"] = self.start_line
            out["start_side"] = self.start_side or self.side
        return out


@dataclass(frozen=True)
class MappedReview:
    """The final Review: what the Publisher writes (dry run) or posts."""

    commit_id: str
    summary: str
    body: str  # the Review body: summary, General Findings, AI Disclosure
    comments: list[InlineComment] = field(default_factory=list)
    general: list[dict] = field(default_factory=list)  # General Findings

    def to_payload(self) -> dict:
        """The body of `POST /repos/{o}/{r}/pulls/{n}/reviews` for a pending
        review (no `event`)."""
        return {
            "commit_id": self.commit_id,
            "body": self.body,
            "comments": [c.to_payload() for c in self.comments],
        }


def parse_review(raw: str) -> dict:
    """Parse and validate engine output. Raises InvalidReviewJSON."""
    text = raw.strip()
    if text.startswith("```"):
        # A fenced block: drop the first and the last fence lines.
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
    try:
        review = json.loads(text)
    except ValueError as e:
        raise InvalidReviewJSON(f"The engine output is not valid JSON: {e}") from None
    try:
        jsonschema.validate(review, REVIEW_SCHEMA)
    except jsonschema.ValidationError as e:
        where = "/".join(str(p) for p in e.absolute_path) or "(top level)"
        # Name the rule, not the value: the value is Review content.
        raise InvalidReviewJSON(
            f"The engine output does not match the Review schema at {where} "
            f"(the {e.validator!r} rule fails)."
        ) from None
    return review


_HUNK = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

Hunks = dict[str, dict[str, set[int]]]


def hunk_lines(diff: str) -> Hunks:
    """Map path -> {"RIGHT": lines, "LEFT": lines} for the lines inside the
    hunks of a GitHub diff. GitHub accepts an inline comment only on these.

    RIGHT holds added and context lines (new file numbers); LEFT holds deleted
    and context lines (old file numbers), as `hunk_lines()` in the bake-off
    `report.py`. The counts in each hunk header tell where the hunk ends, so a
    line such as `+++ x` inside a hunk is an added line, not a file header.
    """
    lines: Hunks = {}
    old_path: str | None = None
    path: str | None = None
    old = new = old_left = new_left = 0
    for row in diff.splitlines():
        if old_left > 0 or new_left > 0:
            tag = row[:1]
            if tag == "\\":  # "\ No newline at end of file"
                continue
            if tag == "+" and path is not None:
                lines[path]["RIGHT"].add(new)
                new, new_left = new + 1, new_left - 1
                continue
            if tag == "-" and path is not None:
                lines[path]["LEFT"].add(old)
                old, old_left = old + 1, old_left - 1
                continue
            if tag in (" ", "") and path is not None:
                lines[path]["RIGHT"].add(new)
                lines[path]["LEFT"].add(old)
                old, new = old + 1, new + 1
                old_left, new_left = old_left - 1, new_left - 1
                continue
            old_left = new_left = 0  # the hunk is shorter than its header says
        if row.startswith("diff --git "):
            old_path = path = None
        elif row.startswith("--- "):
            old_path = _diff_path(row[4:], "a/")
        elif row.startswith("+++ "):
            # A deleted file has "+++ /dev/null": its LEFT lines use the old path.
            path = _diff_path(row[4:], "b/") or old_path
            if path is not None:
                lines.setdefault(path, {"RIGHT": set(), "LEFT": set()})
        elif m := _HUNK.match(row):
            old, new = int(m[1]), int(m[3])
            old_left = int(m[2]) if m[2] is not None else 1
            new_left = int(m[4]) if m[4] is not None else 1
    return lines


def _diff_path(text: str, prefix: str) -> str | None:
    text = text.rstrip("\t")
    if text == "/dev/null":
        return None
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        # Git quotes a path with special characters, with C-style escapes.
        raw = text[1:-1].encode("utf-8").decode("unicode_escape")
        text = raw.encode("latin-1", "replace").decode("utf-8", "replace")
    return text[len(prefix) :] if text.startswith(prefix) else text


def _anchored(f: dict, hunks: Hunks) -> bool:
    """True when each line of the Finding's range is inside a hunk on its side.

    The rule of `classify()` in the bake-off `report.py`, plus one more check:
    a range that ends before it starts is not anchored.
    """
    side = f["side"] or "RIGHT"
    first = f["start_line"] if f["start_line"] is not None else f["line"]
    if f["path"] not in hunks or first > f["line"]:
        return False
    return all(n in hunks[f["path"]][side] for n in range(first, f["line"] + 1))


@dataclass
class ReviewMapper:
    """Maps a validated Review to the Review to post.

    `diff` is the GitHub diff of the Target PR: an inline Finding must be
    inside its hunks. `engine_name` and `model` go in the AI Disclosure.
    `finding_limit` is the most inline comments; the most severe stay.
    """

    commit_id: str
    diff: str
    engine_name: str
    model: str
    finding_limit: int = DEFAULT_FINDING_LIMIT
    skip_globs: tuple[str, ...] = ()  # added to DEFAULT_SKIP_GLOBS

    @property
    def disclosure(self) -> str:
        """The AI Disclosure. It says that an AI helped draft the Review; it
        never says that the Reviewer reviewed the change."""
        return f"Drafted with AI assistance ({self.engine_name} · {self.model})."

    def map(self, review: dict) -> MappedReview:
        hunks = hunk_lines(self.diff)
        inline: list[dict] = []
        general: list[dict] = []
        globs = DEFAULT_SKIP_GLOBS + tuple(self.skip_globs)
        for f in _by_severity(review["findings"]):
            if f["path"] and _skipped(f["path"], globs):
                log.info("Skip glob: one Finding dropped")
                continue
            if not f["path"] or f["line"] is None or not _anchored(f, hunks):
                general.append(f)
            else:
                inline.append(f)
        if len(inline) > self.finding_limit:
            log.info(
                "Finding limit %d: %d inline Findings dropped",
                self.finding_limit,
                len(inline) - self.finding_limit,
            )
            inline = inline[: self.finding_limit]
        comments: list[InlineComment] = []
        for f in inline:
            side = f["side"] or "RIGHT"
            start = f["start_line"] if f["start_line"] != f["line"] else None
            comments.append(
                InlineComment(
                    path=f["path"],
                    line=f["line"],
                    side=side,
                    body=_text(f, suggestion_block=side == "RIGHT"),
                    start_line=start,
                    start_side=side if start is not None else None,
                )
            )
        body = review["summary"].strip()
        if general:
            body += "\n\n## General\n\n" + "\n\n".join(
                _general_text(g) for g in general
            )
        body += "\n\n---\n\n" + self.disclosure
        return MappedReview(
            commit_id=self.commit_id,
            summary=review["summary"],
            body=body,
            comments=comments,
            general=general,
        )


# Findings on these paths are dropped: lockfiles, generated files and
# vendored files. `[review] skip_globs` adds more.
DEFAULT_SKIP_GLOBS: tuple[str, ...] = (
    # lockfiles
    "*.lock",
    "*.lockb",
    "package-lock.json",
    "npm-shrinkwrap.json",
    "pnpm-lock.yaml",
    "go.sum",
    # generated
    "*.min.js",
    "*.min.css",
    "*.map",
    "*_pb2.py",
    "*_pb2.pyi",
    "*_pb2_grpc.py",
    "*.pb.go",
    "*.generated.*",
    # vendored
    "vendor/*",
    "*/vendor/*",
    "node_modules/*",
    "*/node_modules/*",
    "third_party/*",
    "*/third_party/*",
)


def _skipped(path: str, globs: tuple[str, ...]) -> bool:
    """fnmatch rules (`*` also matches `/`). A glob with no `/` also matches
    the last part of the path, so `*.lock` matches `web/yarn.lock`."""
    name = path.rsplit("/", 1)[-1]
    return any(
        fnmatch.fnmatchcase(path, g) or ("/" not in g and fnmatch.fnmatchcase(name, g))
        for g in globs
    )


# Most severe first. The schema allows only these labels.
SEVERITY = ("issue (blocking)", "suggestion", "question", "nit")


def _by_severity(findings: list[dict]) -> list[dict]:
    """Most severe first; the engine's order stays within one label."""
    return sorted(findings, key=lambda f: SEVERITY.index(f["label"]))


def _where(f: dict) -> str:
    """Where a General Finding points, for the reader: `path` line N."""
    if not f["path"]:
        return ""
    if f["line"] is None:
        return f"`{f['path']}`"
    start = f["start_line"]
    lines = (
        f"lines {start}-{f['line']}"
        if start is not None and start != f["line"]
        else f"line {f['line']}"
    )
    side = " (old file)" if f["side"] == "LEFT" else ""
    return f"`{f['path']}` {lines}{side}"


def _general_text(f: dict) -> str:
    where = _where(f)
    return _text(f, suggestion_block=False, where=where)


def _text(f: dict, *, suggestion_block: bool, where: str = "") -> str:
    """The Finding as markdown: its Conventional Comments label first, then
    the body, then the suggestion. A GitHub suggestion block works only in an
    inline comment on the RIGHT side; elsewhere it is a plain code block."""
    text = f"**{f['label']}:** " + (f"{where}: " if where else "") + f["body"].strip()
    if f["suggestion"] is not None:
        code = f["suggestion"].removesuffix("\n")
        longest = max((len(m) for m in re.findall(r"`+", code)), default=0)
        fence = "`" * max(3, longest + 1)
        info = "suggestion" if suggestion_block else ""
        text += f"\n\n{fence}{info}\n{code}\n{fence}"
    return text
