"""Publisher: the last step. It posts the Review, or writes it to files.

- Default: one `POST .../reviews` with no `event`. GitHub keeps it as a
  pending review: a Draft Review that only the Reviewer can see.
- Publish: the same single POST with `event: COMMENT` (a Published Review).
  It is one request, not create-then-submit, so a failure never leaves a
  Draft Review behind. No other event can be sent: the tool never approves
  and never requests changes (see `GitHubClient.create_review`).
- The payload is always `MappedReview.to_payload()` of the filtered Review.

A dry run writes two files and posts nothing:

- `<owner>-<repo>-<number>.review.json`: the exact pending-review payload that
  a post would send (`commit_id`, `body`, `comments`; never `event`).
- `<owner>-<repo>-<number>.review.md`: the same Review as markdown to read.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from review_agent.github import GitHubClient, PullRef
from review_agent.mapper import MappedReview


@dataclass(frozen=True)
class Posted:
    review_id: int | None
    state: str | None  # PENDING (Draft Review) or COMMENTED (Published Review)
    published: bool


class Publisher:
    def __init__(self, pr: PullRef):
        self.pr = pr

    def post(self, gh: GitHubClient, review: MappedReview, *, publish: bool) -> Posted:
        data = gh.create_review(self.pr, review.to_payload(), publish=publish)
        return Posted(data.get("id"), data.get("state"), publish)

    def dry_run(self, review: MappedReview, out_dir: Path) -> list[Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = f"{self.pr.owner}-{self.pr.repo}-{self.pr.number}.review"
        json_path = out_dir / f"{stem}.json"
        md_path = out_dir / f"{stem}.md"
        _write(json_path, json.dumps(review.to_payload(), indent=2) + "\n")
        _write(md_path, self.markdown(review))
        return [json_path, md_path]

    def markdown(self, review: MappedReview) -> str:
        parts = [
            f"# Review of {self.pr}",
            "",
            f"PR: {self.pr.url}  ",
            f"Commit: `{review.commit_id}`",
            "",
            "## Review body",
            "",
            review.body.strip(),
            "",
            f"## Inline comments ({len(review.comments)})",
        ]
        for c in review.comments:
            lines = (
                f"{c.start_line}-{c.line}" if c.start_line is not None else f"{c.line}"
            )
            parts += ["", f"### `{c.path}` line {lines} ({c.side})", "", c.body.strip()]
        return "\n".join(parts) + "\n"


def _write(path: Path, text: str) -> None:
    # The Review can quote private code: keep the files private to the user.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
