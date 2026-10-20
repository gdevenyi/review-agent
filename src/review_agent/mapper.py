"""ReviewMapper: raw Review JSON from the engine -> the Review to post.

No network. Now: schema validation and a plain mapping of Findings to inline
comments and General Findings. Later tickets add the anchor check against the
diff hunks, skip globs, the Finding limit, label and suggestion formatting,
the AI Disclosure (#15) and the output filter (#16).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import jsonschema

from review_agent.errors import ReviewAgentError
from review_agent.schema import REVIEW_SCHEMA


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


@dataclass
class ReviewMapper:
    """Maps a validated Review to the Review to post.

    `diff` is the GitHub diff of the Target PR (for the anchor check, #15).
    `engine_name` and `model` are for the AI Disclosure (#15).
    """

    commit_id: str
    diff: str
    engine_name: str
    model: str

    def map(self, review: dict) -> MappedReview:
        comments: list[InlineComment] = []
        general: list[dict] = []
        for f in review["findings"]:
            if f["path"] and f["line"] is not None:
                side = f["side"] or "RIGHT"
                comments.append(
                    InlineComment(
                        path=f["path"],
                        line=f["line"],
                        side=side,
                        body=f["body"],
                        start_line=f["start_line"],
                        start_side=side if f["start_line"] is not None else None,
                    )
                )
            else:
                general.append(f)
        body = review["summary"].strip()
        if general:
            body += "\n\n## General\n\n" + "\n\n".join(
                f"- {g['body'].strip()}" for g in general
            )
        return MappedReview(
            commit_id=self.commit_id,
            summary=review["summary"],
            body=body,
            comments=comments,
            general=general,
        )
