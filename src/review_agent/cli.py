"""The `review` command: `review <pr-url> [--dry-run] [--config PATH]`.

It prints progress and file paths, never Review content (story 55).
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
    p.add_argument(
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
    print(f"Dry run for {result.pr_url}: nothing was posted. Files:")
    for f in result.files:
        print(f"  {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
