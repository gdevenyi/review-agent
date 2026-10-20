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
