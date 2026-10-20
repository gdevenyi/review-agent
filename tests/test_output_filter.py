"""Seam 1: the output filter against hostile engine output (#16).

Every fake secret here is built at run time, so the repo holds no text that
looks like a real key.
"""

from __future__ import annotations

import pytest
from harness import ENGINE_KEY, finding, review_json


def assert_failed_with_nothing_written(world, result):
    assert not result.ok
    assert result.error
    assert result.log_path is not None and result.log_path.is_file()
    assert world.output_files() == []
    assert world.github.writes == []
    assert world.clones_left() == []


FAKE_SECRETS = {
    "GitHub classic token": "ghp_" + "x1" * 18,
    "GitHub fine-grained token": "github_pat_" + "A1b2_" * 17,
    "Z.AI key": "0123456789abcdef" * 2 + "." + "AbCdEfGh" * 2,
    "AWS access key": "AKIA" + "Q7" * 8,
    "private-key header": "-----BEGIN " + "RSA PRIVATE" + " KEY-----",
    "the engine key itself": ENGINE_KEY,
}


@pytest.mark.parametrize("where", ["comment", "summary", "code"])
@pytest.mark.parametrize("kind", sorted(FAKE_SECRETS))
def test_secret_in_review_aborts_and_is_not_echoed(world, kind, where):
    fake = FAKE_SECRETS[kind]
    if where == "comment":
        world.engine.respond(review_json(findings=[finding(f"Use {fake} here.")]))
    elif where == "summary":
        world.engine.respond(review_json(summary=f"Token: {fake}"))
    else:
        world.engine.respond(
            review_json(findings=[finding(f"Look:\n\n```\nkey = '{fake}'\n```\n")])
        )

    result = world.run()

    assert_failed_with_nothing_written(world, result)
    assert "secret" in result.error
    assert fake not in result.error
    assert fake not in result.log_path.read_text()


LABEL = "**issue (blocking):** "
DISCLOSURE = "\n\n---\n\nDrafted with AI assistance (Claude Code · glm-test)."


def _run_with_comment(world, body, summary="Summary."):
    """Run with one inline Finding. Returns the comment body without its
    label and the Review body without the AI Disclosure."""
    world.engine.respond(review_json(summary=summary, findings=[finding(body)]))
    result = world.run()
    assert result.ok, result.error
    out = world.output_json()
    comment, review_body = out["comments"][0]["body"], out["body"]
    assert comment.startswith(LABEL)
    assert review_body.endswith(DISCLOSURE)
    return comment[len(LABEL) :], review_body[: -len(DISCLOSURE)]


def test_mentions_do_not_ping(world):
    comment, body = _run_with_comment(
        world,
        "Ask @octocat and @octo/core-team. Mail a@example.com.",
        summary="cc @someone",
    )

    assert comment == ("Ask `@octocat` and `@octo/core-team`. Mail a@example.com.")
    assert body == "cc `@someone`"
    assert "`@someone`" in world.output_markdown()


def test_mentions_in_code_stay_as_they_are(world):
    comment, _ = _run_with_comment(world, "Use `@decorator` or\n\n```\n@property\n```")

    assert comment == "Use `@decorator` or\n\n```\n@property\n```"


def test_images_and_raw_html_are_removed(world):
    comment, body = _run_with_comment(
        world,
        "Bad![pixel](https://evil.example/p.png) code."
        '<img src="https://evil.example/t.gif"> ![ref img][r]'
        "<details><summary>Open</summary>hidden</details>"
        "<!-- secret note -->end",
        summary='<a href="https://evil.example">Click</a> here.',
    )

    assert comment == "Bad code. Openhiddenend"
    assert body == "Click here."


def test_html_in_code_stays_as_it_is(world):
    text = "Use `List<int>` here:\n\n```suggestion\n<div>{x}</div>\n```\n"

    comment, _ = _run_with_comment(world, text)

    assert comment == text.rstrip()


def test_a_suggestion_with_html_and_mentions_stays_as_it_is(world):
    code = '<a href="https://evil.example">@octocat</a>'
    world.engine.respond(review_json(findings=[finding("Fix it.", suggestion=code)]))

    result = world.run()

    assert result.ok, result.error
    assert f"```suggestion\n{code}\n```" in world.output_json()["comments"][0]["body"]


TARGET = "https://github.com/octo/widgets"


def test_links_to_the_target_repo_stay(world):
    text = (
        f"See [calc]({TARGET}/blob/main/calc.py#L3), {TARGET}/pull/7 "
        f"and <{TARGET}/issues/1>."
    )

    comment, _ = _run_with_comment(world, text)

    assert comment == (
        f"See [calc]({TARGET}/blob/main/calc.py#L3), {TARGET}/pull/7 "
        f"and {TARGET}/issues/1."
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Read [the docs](https://evil.example/x).", "Read the docs."),
        ("Go to https://evil.example/login.", "Go to `https://evil.example/login`."),
        ("Go to www.evil.example now", "Go to `www.evil.example` now"),
        ("Go to HTTPS://evil.example/a now", "Go to `HTTPS://evil.example/a` now"),
        ("Go to <https://evil.example/a>.", "Go to `https://evil.example/a`."),
        ("[x](https://github.com/octo/widgets-evil)", "x"),
        ("[x](https://github.com/octo/widgets@evil.example)", "x"),
        ("[x](https://github.com/octo/widgets/../../evil/r)", "x"),
        ("[x](http://github.com/octo/widgets)", "x"),
        ("[x](/evil/repo)", "x"),
        ("[ref link][r]\n\n[r]: https://evil.example/\n", "[ref link][r]\n\n"),
        ("[](https://evil.example/)", "`https://evil.example/`"),
    ],
)
def test_other_links_become_plain_text(world, text, expected):
    comment, _ = _run_with_comment(world, text)

    assert comment == expected


def test_link_text_is_filtered_too(world):
    comment, _ = _run_with_comment(world, "[ping @octocat](https://evil.example/)")

    assert comment == "ping `@octocat`"


def test_each_comment_has_a_length_limit(world):
    world.engine.respond(
        review_json(
            summary="S" * 50_000,
            findings=[finding("word " * 5_000), finding("short", line=5)],
        )
    )

    result = world.run()

    assert result.ok, result.error
    out = world.output_json()
    long, short = out["comments"]
    assert len(long["body"]) <= 4000
    assert long["body"].startswith(LABEL + "word word")
    assert "longer than" in long["body"]
    assert short["body"] == LABEL + "short"
    assert len(out["body"]) <= 16000
    assert out["body"].startswith("SSS")
    assert out["body"].endswith(DISCLOSURE)


def test_a_cut_never_leaves_a_partial_suggestion(world):
    text = "Fix:\n\n```suggestion\n" + "x = 1\n" * 2000 + "```\n"

    comment, _ = _run_with_comment(world, text)

    assert "```suggestion" not in comment
    assert comment.startswith("Fix:")


def test_a_cut_never_leaves_a_mention_that_pings(world):
    text = "a" * 3970 + " @octocat " * 20

    comment, _ = _run_with_comment(world, text)

    assert len(comment) <= 4000
    assert "@" not in comment.replace("`@octocat`", "")
