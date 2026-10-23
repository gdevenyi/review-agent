"""Seam 1 through the CLI: `review <pr-url> --actions` (ticket #20).

In GitHub Actions the tool writes a job summary from the RunResult, never
Review content, and the engine may run without a sandbox (with a warning).
"""

from harness import PR_URL, finding, review_json
from test_tokens import expiry_in

import review_agent


def actions(world, monkeypatch, tmp_path, *args):
    """Run `review <args> --actions` like the reusable workflow does.

    Returns (exit code, job summary text, the Options that the CLI chose)."""
    from review_agent import cli as cli_mod

    summary = tmp_path / "step-summary.md"
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("RUNNER_TEMP", str(runner_temp))
    chosen = {}

    def fake_run_review(url, opts):
        chosen["options"] = opts
        return review_agent.run_review(url, world.options(mode=opts.mode))

    monkeypatch.setattr(cli_mod, "run_review", fake_run_review)
    code = cli_mod.main([*args, "--actions"])
    text = summary.read_text() if summary.exists() else ""
    return code, text, chosen["options"], runner_temp


def test_actions_draft_review_job_summary_has_no_review_content(
    world, monkeypatch, tmp_path, capsys
):
    world.engine.respond(review_json("SECRET-SUMMARY", [finding("SECRET-BODY")]))

    code, summary, opts, runner_temp = actions(world, monkeypatch, tmp_path, PR_URL)

    out, err = capsys.readouterr()
    assert code == 0
    assert PR_URL in summary and "Draft Review" in summary
    assert "SECRET-" not in out + err + summary
    # The Action runs the engine without bubblewrap if the runner blocks it,
    # and keeps the clone in the runner's temp dir.
    assert opts.sandbox == "warn"
    assert opts.tmp_root == runner_temp
    [write] = world.github.writes
    assert "event" not in write.body


def test_actions_failure_shows_the_error_once_and_in_the_job_summary(
    world, monkeypatch, tmp_path, capsys
):
    world.login = "someone-else"

    code, summary, _, _ = actions(world, monkeypatch, tmp_path, PR_URL)

    out, err = capsys.readouterr()
    assert code == 1
    assert "failed" in summary and "someone-else" in summary
    assert "Nothing was posted" in summary
    # One error line in the log, as a GitHub annotation; not twice.
    assert (out + err).count("someone-else") == 1
    assert "::error::" in out + err
    assert world.github.writes == []


def test_actions_warnings_go_to_the_job_summary_and_annotations(
    world, monkeypatch, tmp_path, capsys
):
    world.user_headers["github-authentication-token-expiration"] = expiry_in(5)
    world.engine.respond(review_json("SECRET-SUMMARY", [finding("SECRET-BODY")]))

    code, summary, _, _ = actions(world, monkeypatch, tmp_path, PR_URL)

    out, err = capsys.readouterr()
    assert code == 0
    assert "expires" in summary
    assert "::warning::" in out + err
    assert "SECRET-" not in out + err + summary


def test_actions_publish_says_published_review(world, monkeypatch, tmp_path, capsys):
    world.engine.respond(review_json("SECRET-SUMMARY", [finding("SECRET-BODY")]))

    code, summary, _, _ = actions(world, monkeypatch, tmp_path, PR_URL, "--publish")

    out, err = capsys.readouterr()
    assert code == 0
    assert "Published Review" in summary and PR_URL in summary
    assert "SECRET-" not in out + err + summary
    [write] = world.github.writes
    assert write.body["event"] == "COMMENT"


def test_actions_engine_error_shows_a_generic_message_not_the_engine_text(
    world, monkeypatch, tmp_path, capsys
):
    from review_agent.engine import EngineError

    world.engine.respond(EngineError("exit code 1.\nSECRET-STDERR model said this"))

    code, summary, _, _ = actions(world, monkeypatch, tmp_path, PR_URL)

    out, err = capsys.readouterr()
    assert code == 1
    assert "SECRET-" not in out + err + summary
    assert "The engine failed" in summary and "Nothing was posted" in summary
    assert "::error::The engine failed" in err
    # The detail stays in the run log file.
    [log_file] = world.log_dir.iterdir()
    assert "SECRET-STDERR" in log_file.read_text()
    assert world.github.writes == []


def test_actions_engine_progress_reaches_the_job_log_without_a_run_log(
    world, monkeypatch, tmp_path, capsys
):
    # The run log cannot be made (its dir is a file). The INFO progress
    # lines of the engine must still go to the job log.
    import logging

    world.log_dir = tmp_path / "not-a-dir"
    world.log_dir.write_text("")
    world.engine.respond(review_json())
    fake_review = world.engine.review

    def review(*args, **kw):
        logging.getLogger("review_agent.engine").info("Engine: Read calc.py")
        return fake_review(*args, **kw)

    monkeypatch.setattr(world.engine, "review", review)
    logger = logging.getLogger("review_agent")
    old = logger.level
    logger.setLevel(logging.NOTSET)  # as in a new process
    try:
        code, _, _, _ = actions(world, monkeypatch, tmp_path, PR_URL)
    finally:
        logger.setLevel(old)

    _, err = capsys.readouterr()
    assert code == 0
    assert "review: Engine: Read calc.py\n" in err


def test_review_copy_writes_the_posted_review_as_a_private_file(
    world, monkeypatch, tmp_path, capsys
):
    world.engine.respond(
        review_json("COPY-SUMMARY", [finding("COPY-BODY", line=6, side="RIGHT")])
    )
    copy = tmp_path / "copy.md"

    code, _, _, _ = actions(
        world, monkeypatch, tmp_path, PR_URL, "--review-copy", str(copy)
    )

    out, err = capsys.readouterr()
    assert code == 0
    text = copy.read_text()
    assert "COPY-SUMMARY" in text and "COPY-BODY" in text
    assert "`calc.py` line 6 (RIGHT)" in text
    assert "Draft Review" in text and PR_URL in text
    assert copy.stat().st_mode & 0o777 == 0o600
    # The copy goes only to the file, never to the job log.
    assert "COPY-" not in out + err


def test_review_copy_is_not_written_when_the_run_fails(
    world, monkeypatch, tmp_path, capsys
):
    world.login = "someone-else"
    copy = tmp_path / "copy.md"

    code, _, _, _ = actions(
        world, monkeypatch, tmp_path, PR_URL, "--review-copy", str(copy)
    )

    assert code == 1
    assert not copy.exists()
