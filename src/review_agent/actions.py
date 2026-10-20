"""GitHub Actions output for `review --actions`.

- Warnings and errors become annotations (`::warning::`, `::error::`).
- The job summary (`$GITHUB_STEP_SUMMARY`) gets the status, the PR URL, the
  warnings and the error. It never gets Review content (story 55).
- An engine error shows only a generic message in the annotation and the job
  summary: the engine's stderr and result text can quote model output. The
  detail stays in the run log file.
"""

from __future__ import annotations

import logging
import os
import sys

from review_agent.run import RunResult

ENGINE_FAILED = "The engine failed. See the run log for the detail."


def escape(message: str) -> str:
    """Escape a message for a GitHub Actions workflow command."""
    return message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


class ActionsFormatter(logging.Formatter):
    """Warnings and errors become GitHub Actions annotations."""

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        if record.exc_info and record.exc_info[1] is not None:
            e = record.exc_info[1]
            message = f"{message}: {type(e).__name__}: {e}"
        if record.levelno >= logging.ERROR:
            return f"::error::{escape(message)}"
        if record.levelno >= logging.WARNING:
            return f"::warning::{escape(message)}"
        return f"review: {message}"


class WarningCollector(logging.Handler):
    """Keep the messages of WARNING records (for example: no sandbox)."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.ERROR:
            self.messages.append(record.getMessage())


def public_error(result: RunResult) -> str:
    """The error text for the annotation and the job summary."""
    return ENGINE_FAILED if result.engine_failed else str(result.error)


def report(result: RunResult, logged_warnings: list[str]) -> None:
    """Write the annotations and the job summary for a finished run."""
    for w in result.warnings:
        print(f"::warning::{escape(w)}", file=sys.stderr)
    if result.engine_failed:
        # run_review logged only a generic ERROR line; this is the annotation.
        print(f"::error::{escape(ENGINE_FAILED)}", file=sys.stderr)
    write_job_summary(result, logged_warnings + result.warnings)


def write_job_summary(result: RunResult, warnings: list[str]) -> None:
    """Write the result to the Actions job summary: the status, the PR URL,
    the warnings and the error. Never Review content (story 55)."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = ["## review-agent", "", f"Target PR: {result.pr_url}", ""]
    if not result.ok:
        lines += [f"**{result.status}**", "", "```text", public_error(result), "```"]
    else:
        lines.append(result.status)
    if warnings:
        lines += ["", "### Warnings", ""]
        lines += [f"- {w}" for w in warnings]
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
