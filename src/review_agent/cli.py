"""The `review` command: `review <pr-url> [--publish | --dry-run] [--config PATH]`.

- Default: post a Draft Review (a pending review only the Reviewer can see).
- `--publish`: post a Published Review, always as COMMENT.
- `--dry-run`: write the Review to files; post nothing.

It prints progress, the PR URL and file paths, never Review content (story 55).

`--actions` is for the reusable GitHub Actions workflow:
- If the runner blocks bubblewrap, the engine runs without a sandbox, with a
  warning (ADR 0002). Without `--actions` the tool refuses to run.
- The clone goes in `$RUNNER_TEMP`.
- Warnings and errors become annotations (`::warning::`, `::error::`).
- The job summary (`$GITHUB_STEP_SUMMARY`) gets the status, the PR URL, the
  warnings and the error. It never gets Review content.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from review_agent.run import Options, RunResult, run_review


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
        progress.setFormatter(_ActionsFormatter())
    else:
        progress.setFormatter(logging.Formatter("review: %(message)s"))
    logged_warnings = _WarningCollector()
    logger = logging.getLogger("review_agent")
    logger.addHandler(progress)
    logger.addHandler(logged_warnings)
    try:
        result = run_review(
            args.pr_url,
            Options(
                config_path=args.config,
                dry_run=args.dry_run,
                publish=args.publish,
                out_dir=args.out_dir,
                tmp_root=_tmp_root(args.actions),
                sandbox="warn" if args.actions else "require",
            ),
        )
    finally:
        logger.removeHandler(progress)
        logger.removeHandler(logged_warnings)
    for w in result.warnings:
        if args.actions:
            print(f"::warning::{_escape(w)}", file=sys.stderr)
        else:
            print(f"review: warning: {w}", file=sys.stderr)
    if args.actions:
        _write_job_summary(result, logged_warnings.messages + result.warnings)
    if not result.ok:
        # In Actions mode the run log handler already showed the error as an
        # annotation; do not show it twice.
        if not args.actions:
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


def _tmp_root(actions: bool) -> Path | None:
    runner_temp = os.environ.get("RUNNER_TEMP")
    if actions and runner_temp:
        return Path(runner_temp)
    # Clones go to disk, not to a /tmp RAM disk.
    return Path("/var/tmp") if os.path.isdir("/var/tmp") else None


def _escape(message: str) -> str:
    """Escape a message for a GitHub Actions workflow command."""
    return message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


class _ActionsFormatter(logging.Formatter):
    """Warnings and errors become GitHub Actions annotations."""

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        if record.exc_info and record.exc_info[1] is not None:
            e = record.exc_info[1]
            message = f"{message}: {type(e).__name__}: {e}"
        if record.levelno >= logging.ERROR:
            return f"::error::{_escape(message)}"
        if record.levelno >= logging.WARNING:
            return f"::warning::{_escape(message)}"
        return f"review: {message}"


class _WarningCollector(logging.Handler):
    """Keep the messages of WARNING records (for example: no sandbox)."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.ERROR:
            self.messages.append(record.getMessage())


def _write_job_summary(result: RunResult, warnings: list[str]) -> None:
    """Write the result to the Actions job summary: the status, the PR URL,
    the warnings and the error. Never Review content (story 55)."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = ["## review-agent", "", f"Target PR: {result.pr_url}", ""]
    if not result.ok:
        lines += [
            "**The run failed. Nothing was posted.**",
            "",
            "```text",
            str(result.error),
            "```",
        ]
    elif result.published:
        lines.append("A Published Review (COMMENT) is on the PR.")
    elif result.posted:
        lines.append(
            "A Draft Review is waiting for you. Open the PR, check and edit "
            "the Review, then submit it."
        )
    else:
        lines.append("Dry run: nothing was posted.")
    if warnings:
        lines += ["", "### Warnings", ""]
        lines += [f"- {w}" for w in warnings]
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    sys.exit(main())
