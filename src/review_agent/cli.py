"""The `review` command: `review <pr-url> [--publish | --dry-run] [--config PATH]`.

- Default: post a Draft Review (a pending review only the Reviewer can see).
- `--publish`: post a Published Review, always as COMMENT.
- `--dry-run`: write the Review to files; post nothing.

It prints progress, the PR URL and file paths, never Review content (story 55).

`--actions` is for the reusable GitHub Actions workflow:
- If the runner blocks bubblewrap, the engine runs without a sandbox, with a
  warning (ADR 0002). Without `--actions` the tool refuses to run.
- The clone goes in `$RUNNER_TEMP`.
- Annotations and the job summary: see actions.py.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from review_agent import actions
from review_agent.github import parse_pr_url
from review_agent.publisher import Publisher
from review_agent.run import Options, RunMode, RunResult, run_review


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
    p.add_argument(
        "--review-copy",
        type=Path,
        default=None,
        metavar="PATH",
        help="after a successful run, also write the Review as markdown to "
        "PATH (mode 600). The Action uses it to copy the Review to an issue",
    )
    p.add_argument(
        "--actions",
        action="store_true",
        help="GitHub Actions mode: run the engine without a sandbox (with a "
        "warning) if the runner blocks bubblewrap, and write a job summary",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    progress = logging.StreamHandler(sys.stderr)
    progress.setLevel(logging.INFO)
    if args.actions:
        progress.setFormatter(actions.ActionsFormatter())
        progress.addFilter(_no_engine_detail)
    else:
        progress.setFormatter(logging.Formatter("review: %(message)s"))
    logged_warnings = actions.WarningCollector()
    logger = logging.getLogger("review_agent")
    logger.addHandler(progress)
    logger.addHandler(logged_warnings)
    # The progress handler shows INFO (for example the live engine progress
    # of review_agent.engine), also when there is no run log to set a level.
    if logger.level == logging.NOTSET or logger.level > logging.INFO:
        logger.setLevel(logging.INFO)
    if args.dry_run:
        mode = RunMode.DRY_RUN
    elif args.publish:
        mode = RunMode.PUBLISH
    else:
        mode = RunMode.DRAFT
    try:
        result = run_review(
            args.pr_url,
            Options(
                config_path=args.config,
                mode=mode,
                out_dir=args.out_dir,
                tmp_root=_tmp_root(args.actions),
                sandbox="warn" if args.actions else "require",
            ),
        )
    finally:
        logger.removeHandler(progress)
        logger.removeHandler(logged_warnings)
    if args.actions:
        actions.report(result, logged_warnings.messages)
    else:
        for w in result.warnings:
            print(f"review: warning: {w}", file=sys.stderr)
    if not result.ok:
        # In Actions mode the error is already an annotation; do not show it
        # twice.
        if not args.actions:
            print(f"review: error: {result.error}", file=sys.stderr)
        if result.log_path:
            print(f"review: run log: {result.log_path}", file=sys.stderr)
        return 1
    if args.review_copy is not None and result.review is not None:
        write_review_copy(result, args.review_copy)
    print(result.status)
    for f in result.files:
        print(f"  {f}")
    return 0


def write_review_copy(result: RunResult, path: Path) -> None:
    """Write the filtered Review that the run posted as markdown, with the
    run status first. Only the user can read the file. It never goes to the
    job log."""
    pr = parse_pr_url(result.pr_url)
    text = f"{result.status}\n\n" + Publisher(pr).markdown(result.review)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)


def _no_engine_detail(record: logging.LogRecord) -> bool:
    """Actions mode: keep the engine error detail out of the job log. It goes
    only to the run log file (see actions.py)."""
    return not getattr(record, "engine_detail", False)


def _tmp_root(actions: bool) -> Path | None:
    runner_temp = os.environ.get("RUNNER_TEMP")
    if actions and runner_temp:
        return Path(runner_temp)
    # Clones go to disk, not to a /tmp RAM disk.
    return Path("/var/tmp") if os.path.isdir("/var/tmp") else None


if __name__ == "__main__":
    sys.exit(main())
