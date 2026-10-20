"""Seam 1: post the Draft Review, or the Published Review (ticket #19)."""

from pathlib import Path

import httpx
import pytest
from harness import (
    GITHUB_TOKEN,
    LOGIN,
    NUMBER,
    OWNER,
    PR_URL,
    REPO,
    REVIEWS_PATH,
    finding,
    review_json,
)
from test_run_review import assert_failed_with_nothing_written

import review_agent
from review_agent.engine import EngineTimeout
from review_agent.github import GitHubClient, PullRef
from review_agent.mapper import MappedReview


def post(world, **overrides):
    """Run without --dry-run: the Review goes to (fake) GitHub."""
    return world.run(dry_run=False, **overrides)


def test_default_run_posts_one_pending_review_with_inline_comments(world):
    world.engine.respond(
        review_json(
            summary="The change adds div().",
            findings=[finding("Division by zero is not handled.", line=6)],
        )
    )

    result = post(world)

    assert result.ok, result.error
    [write] = world.github.writes
    assert (write.method, write.path) == ("POST", REVIEWS_PATH)
    assert "event" not in write.body
    assert write.body == result.review.to_payload()
    assert write.body["commit_id"] == world.pr["head"]["sha"]
    [comment] = write.body["comments"]
    assert (comment["path"], comment["line"], comment["side"]) == (
        "calc.py",
        6,
        "RIGHT",
    )
    assert "Division by zero is not handled." in comment["body"]
    assert "Drafted with AI assistance" in write.body["body"]
    assert world.output_files() == []
    assert result.posted and not result.published
    assert result.pr_url == PR_URL


def test_publish_posts_one_review_with_event_comment(world):
    world.engine.respond(review_json(findings=[finding(line=6)]))

    result = post(world, publish=True)

    assert result.ok, result.error
    [write] = world.github.writes
    assert (write.method, write.path) == ("POST", REVIEWS_PATH)
    assert write.body["event"] == "COMMENT"
    without_event = {k: v for k, v in write.body.items() if k != "event"}
    assert without_event == result.review.to_payload()
    assert result.posted and result.published


def test_dry_run_and_publish_together_are_refused(world):
    world.engine.respond(review_json())

    result = world.run(dry_run=True, publish=True)

    assert not result.ok
    assert "--dry-run" in result.error and "--publish" in result.error
    assert world.github.requests == []
    assert world.engine.calls == []


def test_an_existing_pending_review_stops_the_run_before_the_engine(world):
    world.reviews = [
        {"id": 1, "state": "COMMENTED", "user": {"login": LOGIN}},
        {"id": 2, "state": "PENDING", "user": {"login": LOGIN}},
    ]
    world.engine.respond(review_json())

    result = post(world)

    assert_failed_with_nothing_written(world, result)
    assert "pending review" in result.error
    assert PR_URL in result.error
    assert world.engine.calls == []
    # Stopped before the diff and the clone, too.
    assert all(r.path != "/repos/octo/widgets/pulls/7" for r in world.github.requests)


def test_reviews_by_others_or_already_submitted_do_not_stop_the_run(world):
    world.reviews = [
        {"id": 1, "state": "COMMENTED", "user": {"login": LOGIN}},
        {"id": 2, "state": "PENDING", "user": {"login": "someone-else"}},
        {"id": 3, "state": "APPROVED", "user": None},
    ]
    world.engine.respond(review_json())

    result = post(world)

    assert result.ok, result.error
    assert len(world.github.writes) == 1


def test_pending_review_on_a_later_page_is_found(world):
    page2 = f"https://api.github.com{REVIEWS_PATH}?per_page=100&page=2"

    def reviews(request):
        if request.url.params.get("page") == "2":
            return httpx.Response(
                200, json=[{"id": 9, "state": "PENDING", "user": {"login": LOGIN}}]
            )
        return httpx.Response(
            200,
            json=[{"id": 1, "state": "COMMENTED", "user": {"login": LOGIN}}],
            headers={"Link": f'<{page2}>; rel="next"'},
        )

    world.github.route("GET", REVIEWS_PATH, handler=reviews)
    world.engine.respond(review_json())

    result = post(world)

    assert_failed_with_nothing_written(world, result)
    assert world.engine.calls == []


def test_engine_failure_posts_nothing(world):
    world.engine.respond(EngineTimeout("The engine did not finish in 1200 seconds."))

    result = post(world, publish=True)

    assert_failed_with_nothing_written(world, result)


def test_secret_in_the_review_posts_nothing(world):
    world.engine.respond(review_json(findings=[finding("key: ghp_" + "x1" * 18)]))

    result = post(world)

    assert_failed_with_nothing_written(world, result)


@pytest.mark.parametrize(
    ("status", "headers", "words"),
    [
        (401, None, "REVIEW_AGENT_GITHUB_TOKEN"),
        (
            403,
            {"X-GitHub-SSO": "required; url=https://github.com/orgs/octo/sso?x=1"},
            "https://github.com/orgs/octo/sso?x=1",
        ),
        (404, None, "REVIEW_AGENT_GITHUB_TOKEN"),
        (422, None, "HTTP 422"),
    ],
)
def test_a_refused_post_reports_the_error_and_the_run_log(
    world, status, headers, words
):
    world.github.route(
        "POST",
        REVIEWS_PATH,
        status=status,
        json={"message": "refused"},
        headers=headers,
    )
    world.engine.respond(review_json(findings=[finding(line=6)]))

    result = post(world)

    assert not result.ok
    assert words in result.error
    assert result.log_path is not None and result.log_path.is_file()
    assert not result.posted
    # One POST was tried; GitHub kept nothing. Nothing else was written.
    assert [w.path for w in world.github.writes] == [REVIEWS_PATH]
    assert world.output_files() == []
    assert world.clones_left() == []
    assert GITHUB_TOKEN not in result.error
    assert GITHUB_TOKEN not in result.log_path.read_text()


def test_no_code_path_can_send_approve_or_request_changes(world):
    # The event is fixed in GitHubClient: a payload cannot set it.
    review = MappedReview(commit_id="abc", summary="s", body="b")
    for event in ("APPROVE", "REQUEST_CHANGES", "COMMENT"):
        payload = {**review.to_payload(), "event": event}
        with (
            GitHubClient("t", transport=world.github.transport) as gh,
            pytest.raises(ValueError),
        ):
            gh.create_review(PullRef(OWNER, REPO, NUMBER), payload, publish=True)
    assert world.github.writes == []
    # No source file names the two events, so nothing can build them.
    src = Path(review_agent.__file__).parent
    for path in src.rglob("*"):
        if path.is_file():
            text = path.read_text(errors="replace")
            assert "APPROVE" not in text, path
            assert "REQUEST_CHANGES" not in text, path


# --- the CLI ------------------------------------------------------------------


def cli(world, monkeypatch, *args):
    """Run `review <args>` against the fake world. Returns the exit code."""
    from review_agent import cli as cli_mod

    def fake_run_review(url, opts):
        return review_agent.run_review(
            url, world.options(dry_run=opts.dry_run, publish=opts.publish)
        )

    monkeypatch.setattr(cli_mod, "run_review", fake_run_review)
    return cli_mod.main([*args])


def test_cli_default_says_a_draft_review_is_waiting(world, monkeypatch, capsys):
    world.engine.respond(review_json("SECRET-SUMMARY", [finding("SECRET-BODY")]))

    code = cli(world, monkeypatch, PR_URL)

    out, err = capsys.readouterr()
    assert code == 0
    assert PR_URL in out and "Draft Review" in out and "waiting" in out
    assert "SECRET-" not in out + err
    [write] = world.github.writes
    assert "event" not in write.body


def test_cli_publish_submits_as_comment(world, monkeypatch, capsys):
    world.engine.respond(review_json("SECRET-SUMMARY", [finding("SECRET-BODY")]))

    code = cli(world, monkeypatch, PR_URL, "--publish")

    out, err = capsys.readouterr()
    assert code == 0
    assert PR_URL in out and "Published Review" in out
    assert "SECRET-" not in out + err
    [write] = world.github.writes
    assert write.body["event"] == "COMMENT"


def test_cli_refuses_publish_with_dry_run(world, monkeypatch):
    with pytest.raises(SystemExit) as e:
        cli(world, monkeypatch, PR_URL, "--publish", "--dry-run")

    assert e.value.code == 2
    assert world.github.requests == []
