"""The `review` command: `review <pr-url> [--publish | --dry-run] [--config PATH]`.

- Default: post a Draft Review (a pending review only the Reviewer can see).
- `--publish`: post a Published Review, always as COMMENT.
- `--dry-run`: write the Review to files; post nothing.

It prints progress, the PR URL and file paths, never Review content (story 55).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from review_agent.run import Options, run_review


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="review",
        description="Draft a Review of a GitHub pull request as the Reviewer.",
    )
    p.add_argument("pr_url", help="https://github.com/<owner>/<repo>/pull/<number>")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--publish",
        action="store_true",
        help="submit the Review at once as a COMMENT that everyone can see "
        "(default: leave a Draft Review that only you can see)",
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="write the Review as markdown and JSON files; post nothing",
    )
    p.add_argument(
        "--config",
        type=Path,
        help="config file (default: $REVIEW_AGENT_CONFIG, else "
        "~/.config/review-agent/config.toml)",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="directory for the --dry-run files (default: the current directory)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    progress = logging.StreamHandler(sys.stderr)
    progress.setLevel(logging.INFO)
    progress.setFormatter(logging.Formatter("review: %(message)s"))
    logger = logging.getLogger("review_agent")
    logger.addHandler(progress)
    try:
        result = run_review(
            args.pr_url,
            Options(
                config_path=args.config,
                dry_run=args.dry_run,
                publish=args.publish,
                out_dir=args.out_dir,
                # Clones go to disk, not to a /tmp RAM disk.
                tmp_root=Path("/var/tmp") if os.path.isdir("/var/tmp") else None,
            ),
        )
    finally:
        logger.removeHandler(progress)
    if not result.ok:
        print(f"review: error: {result.error}", file=sys.stderr)
        if result.log_path:
            print(f"review: run log: {result.log_path}", file=sys.stderr)
        return 1
    if result.published:
        print(f"Published Review (COMMENT) posted on {result.pr_url}")
    elif result.posted:
        print(
            f"A Draft Review is waiting for you on {result.pr_url}\n"
            "Open the PR, check and edit the Review, then submit it."
        )
    else:
        print(f"Dry run for {result.pr_url}: nothing was posted. Files:")
        for f in result.files:
            print(f"  {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
