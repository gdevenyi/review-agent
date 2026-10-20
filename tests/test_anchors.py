"""Seam 1: Findings become a correct Review (#15).

Anchors, the Finding limit, skip globs, labels, suggestion blocks and the
AI Disclosure, as seen in the dry-run payload.
"""

from harness import DEFAULT_CONFIG, DIFF, finding, review_json


def test_anchor_outside_the_diff_goes_to_general(world):
    world.engine.respond(
        review_json(
            findings=[
                finding("Inside the hunk.", line=6),
                finding("Line 40 is not in the diff.", line=40),
            ]
        )
    )

    result = world.run()

    assert result.ok, result.error
    payload = world.output_json()
    assert [c["line"] for c in payload["comments"]] == [6]
    general = payload["body"].split("## General", 1)[1]
    assert "Line 40 is not in the diff." in general
    assert "`calc.py`" in general


# A diff with deletions: old lines 2-3 deleted, new lines 2-3 added; context
# at old 1/new 1 and old 4/new 4. A second file is deleted, and an added line
# starts with "++ ", so it reads "+++ ..." in the diff.
EDIT_DIFF = """\
diff --git a/calc.py b/calc.py
index 1111111..2222222 100644
--- a/calc.py
+++ b/calc.py
@@ -1,4 +1,4 @@
 def add(a, b):
-    # old comment
-    return a+b
+    return a + b
+++ counter

diff --git a/old.py b/old.py
deleted file mode 100644
index 3333333..0000000
--- a/old.py
+++ /dev/null
@@ -1,2 +0,0 @@
-x = 1
-y = 2
"""


LOCK_DIFF = """\
diff --git a/uv.lock b/uv.lock
index 4444444..5555555 100644
--- a/uv.lock
+++ b/uv.lock
@@ -1 +1 @@
-version = 1
+version = 2
"""


def test_left_side_anchor_on_a_deleted_line_is_inline(world):
    world.diff = EDIT_DIFF
    world.engine.respond(
        review_json(findings=[finding("Why remove this?", line=3, side="LEFT")])
    )

    assert world.run().ok
    [comment] = world.output_json()["comments"]
    assert (comment["path"], comment["line"], comment["side"]) == ("calc.py", 3, "LEFT")


def test_left_side_anchor_in_a_deleted_file_is_inline(world):
    world.diff = EDIT_DIFF
    world.engine.respond(
        review_json(
            findings=[finding("Still used?", path="old.py", line=2, side="LEFT")]
        )
    )

    assert world.run().ok
    [comment] = world.output_json()["comments"]
    assert (comment["path"], comment["line"], comment["side"]) == ("old.py", 2, "LEFT")


def test_left_side_anchor_outside_the_old_hunk_lines_goes_to_general(world):
    # Old lines in the hunk are 1-4; old line 5 is not in it.
    world.diff = EDIT_DIFF
    world.engine.respond(
        review_json(findings=[finding("Wrong side.", line=5, side="LEFT")])
    )

    assert world.run().ok
    payload = world.output_json()
    assert payload["comments"] == []
    assert "Wrong side." in payload["body"].split("## General", 1)[1]


def test_multi_line_anchor_keeps_its_range_and_side(world):
    world.engine.respond(
        review_json(findings=[finding("This block.", start_line=5, line=6)])
    )

    assert world.run().ok
    [comment] = world.output_json()["comments"]
    assert comment["start_line"] == 5
    assert comment["line"] == 6
    assert comment["side"] == "RIGHT"
    assert comment["start_side"] == "RIGHT"


def test_multi_line_left_anchor_has_left_start_side(world):
    world.diff = EDIT_DIFF
    world.engine.respond(
        review_json(findings=[finding("Old pair.", start_line=2, line=3, side="LEFT")])
    )

    assert world.run().ok
    [comment] = world.output_json()["comments"]
    assert (comment["start_line"], comment["line"]) == (2, 3)
    assert comment["side"] == comment["start_side"] == "LEFT"


def test_multi_line_anchor_that_leaves_the_hunk_goes_to_general(world):
    # The hunk is new lines 1-6; the range 5-9 runs past it.
    world.engine.respond(
        review_json(findings=[finding("Past the end.", start_line=5, line=9)])
    )

    assert world.run().ok
    payload = world.output_json()
    assert payload["comments"] == []
    assert "`calc.py` lines 5-9" in payload["body"]
    assert "Past the end." in payload["body"]


def test_reversed_range_goes_to_general(world):
    world.engine.respond(
        review_json(findings=[finding("Backwards.", start_line=6, line=3)])
    )

    assert world.run().ok
    assert world.output_json()["comments"] == []


def test_single_line_range_has_no_start_line(world):
    world.engine.respond(
        review_json(findings=[finding("One line.", start_line=6, line=6)])
    )

    assert world.run().ok
    [comment] = world.output_json()["comments"]
    assert "start_line" not in comment


def test_added_line_that_looks_like_a_file_header_is_inline(world):
    world.diff = EDIT_DIFF
    world.engine.respond(review_json(findings=[finding("Odd line.", line=3)]))

    assert world.run().ok
    [comment] = world.output_json()["comments"]
    assert (comment["line"], comment["side"]) == (3, "RIGHT")


def test_path_not_in_the_diff_goes_to_general(world):
    world.engine.respond(
        review_json(findings=[finding("Other file.", path="README.md", line=1)])
    )

    assert world.run().ok
    assert world.output_json()["comments"] == []


# --- labels and suggestion blocks --------------------------------------------


def test_each_comment_starts_with_its_conventional_comments_label(world):
    world.engine.respond(
        review_json(
            findings=[
                finding("Guard b == 0.", label="issue (blocking)", line=6),
                finding("Name it divide.", label="nit", line=5),
            ]
        )
    )

    assert world.run().ok
    bodies = {c["line"]: c["body"] for c in world.output_json()["comments"]}
    assert bodies[6] == "**issue (blocking):** Guard b == 0."
    assert bodies[5] == "**nit:** Name it divide."


def test_general_finding_has_its_label(world):
    world.engine.respond(
        review_json(
            findings=[finding("Add tests.", label="question", path=None, line=None)]
        )
    )

    assert world.run().ok
    general = world.output_json()["body"].split("## General", 1)[1]
    assert "**question:** Add tests." in general


def test_suggestion_becomes_a_github_suggestion_block(world):
    world.engine.respond(
        review_json(
            findings=[
                finding(
                    "Guard b == 0.",
                    start_line=5,
                    line=6,
                    suggestion="def div(a, b):\n    return a / b if b else None\n",
                )
            ]
        )
    )

    assert world.run().ok
    [comment] = world.output_json()["comments"]
    assert comment["body"] == (
        "**issue (blocking):** Guard b == 0.\n"
        "\n"
        "```suggestion\n"
        "def div(a, b):\n"
        "    return a / b if b else None\n"
        "```"
    )


def test_suggestion_of_5_lines_is_a_suggestion_block_6_lines_is_not(world):
    five = "".join(f"x{i} = {i}\n" for i in range(5))
    six = "".join(f"y{i} = {i}\n" for i in range(6))
    world.engine.respond(
        review_json(
            findings=[
                finding("Five.", start_line=3, line=6, suggestion=five),
                finding("Six.", start_line=3, line=6, suggestion=six),
            ]
        )
    )

    assert world.run().ok
    five_body, six_body = (c["body"] for c in world.output_json()["comments"])
    assert "```suggestion\nx0 = 0\n" in five_body
    # Too large to apply with one click: a plain code block.
    assert "```suggestion" not in six_body
    assert "```\ny0 = 0\n" in six_body and "y5 = 5\n```" in six_body


def test_suggestion_with_a_code_fence_gets_a_longer_fence(world):
    world.engine.respond(
        review_json(findings=[finding("Doc.", line=6, suggestion='x = """\n```\n"""')])
    )

    assert world.run().ok
    [comment] = world.output_json()["comments"]
    assert comment["body"].endswith('````suggestion\nx = """\n```\n"""\n````')


def test_suggestion_on_a_left_side_or_general_finding_is_a_plain_code_block(world):
    world.diff = EDIT_DIFF
    world.engine.respond(
        review_json(
            findings=[
                finding("Keep it.", line=3, side="LEFT", suggestion="y = 1"),
                finding("Elsewhere.", path=None, line=None, suggestion="z = 2"),
            ]
        )
    )

    assert world.run().ok
    payload = world.output_json()
    [comment] = payload["comments"]
    assert "```suggestion" not in comment["body"]
    assert "```\ny = 1\n```" in comment["body"]
    assert "```suggestion" not in payload["body"]
    assert "```\nz = 2\n```" in payload["body"]


# --- AI Disclosure -----------------------------------------------------------

DISCLOSURE = "Drafted with AI assistance (Claude Code · glm-test)."


def test_review_with_no_findings_has_the_summary_and_the_disclosure(world):
    world.engine.respond(review_json(summary="Looks fine.", findings=[]))

    assert world.run().ok
    payload = world.output_json()
    assert payload["comments"] == []
    assert payload["body"].startswith("Looks fine.")
    assert payload["body"].endswith(DISCLOSURE)
    assert "## General" not in payload["body"]
    assert DISCLOSURE in world.output_markdown()


def test_disclosure_comes_after_the_general_findings(world):
    world.engine.respond(
        review_json(findings=[finding("Add tests.", path=None, line=None)])
    )

    assert world.run().ok
    body = world.output_json()["body"]
    assert body.index("Add tests.") < body.index(DISCLOSURE)
    assert body.endswith(DISCLOSURE)
    assert body.count(DISCLOSURE) == 1


def test_disclosure_names_the_configured_model(world):
    world.engine.model = "glm-5.3-flash"
    world.engine.respond(review_json())

    assert world.run().ok
    assert world.output_json()["body"].endswith(
        "Drafted with AI assistance (Claude Code · glm-5.3-flash)."
    )


# --- Finding limit -------------------------------------------------------------


def _labels(world) -> list[str]:
    return [c["body"].split(":**", 1)[0][2:] for c in world.output_json()["comments"]]


def test_default_limit_keeps_ten_inline_comments_most_severe_first(world):
    findings = (
        [finding(f"nit {i}", label="nit", line=1 + i % 6) for i in range(4)]
        + [finding(f"q {i}", label="question", line=1 + i % 6) for i in range(4)]
        + [finding(f"s {i}", label="suggestion", line=1 + i % 6) for i in range(4)]
        + [finding(f"b {i}", label="issue (blocking)", line=6) for i in range(2)]
    )
    world.engine.respond(review_json(findings=findings))

    assert world.run().ok
    assert _labels(world) == (
        ["issue (blocking)"] * 2 + ["suggestion"] * 4 + ["question"] * 4
    )
    bodies = [c["body"] for c in world.output_json()["comments"]]
    # Same label: the engine's order stays.
    assert [b.split(":** ")[1] for b in bodies[2:6]] == ["s 0", "s 1", "s 2", "s 3"]
    assert "nit 0" not in world.output_json()["body"]


def test_configured_limit_cuts_by_severity(world):
    world.write_config(DEFAULT_CONFIG + "\n[review]\nfinding_limit = 2\n")
    world.engine.respond(
        review_json(
            findings=[
                finding("a nit", label="nit", line=5),
                finding("a question", label="question", line=5),
                finding("a blocker", label="issue (blocking)", line=6),
                finding("a suggestion", label="suggestion", line=6),
            ]
        )
    )

    assert world.run().ok
    assert _labels(world) == ["issue (blocking)", "suggestion"]


def test_limit_counts_inline_comments_only(world):
    world.write_config(DEFAULT_CONFIG + "\n[review]\nfinding_limit = 1\n")
    world.engine.respond(
        review_json(
            findings=[
                finding("general one", path=None, line=None),
                finding("general two", line=99),
                finding("inline one", line=6),
                finding("inline two", label="nit", line=5),
            ]
        )
    )

    assert world.run().ok
    payload = world.output_json()
    assert len(payload["comments"]) == 1
    assert "general one" in payload["body"] and "general two" in payload["body"]


def test_invalid_finding_limit_stops_the_run(world):
    world.write_config(DEFAULT_CONFIG + '\n[review]\nfinding_limit = "ten"\n')
    world.engine.respond(review_json())

    result = world.run()

    assert not result.ok
    assert "finding_limit" in result.error
    assert world.output_files() == []
    assert world.engine.calls == []


# --- skip globs ----------------------------------------------------------------


def _all_text(world) -> str:
    payload = world.output_json()
    return payload["body"] + "".join(c["body"] for c in payload["comments"])


def test_default_skip_globs_drop_lockfile_generated_and_vendored_findings(world):
    skipped = [
        "package-lock.json",
        "web/pnpm-lock.yaml",
        "uv.lock",
        "go.sum",
        "dist/app.min.js",
        "api/service_pb2.py",
        "vendor/github.com/x/y.go",
        "web/node_modules/left-pad/index.js",
    ]
    world.engine.respond(
        review_json(
            findings=[finding(f"about {p}", path=p, line=1) for p in skipped]
            + [finding("about calc", line=6)]
        )
    )

    assert world.run().ok
    text = _all_text(world)
    for p in skipped:
        assert f"about {p}" not in text
    assert [c["path"] for c in world.output_json()["comments"]] == ["calc.py"]


def test_configured_skip_globs_add_to_the_defaults(world):
    world.write_config(DEFAULT_CONFIG + '\n[review]\nskip_globs = ["docs/*"]\n')
    world.engine.respond(
        review_json(
            findings=[
                finding("about docs", path="docs/guide.md", line=1),
                finding("about lock", path="uv.lock", line=1),
                finding("about calc", line=6),
            ]
        )
    )

    assert world.run().ok
    text = _all_text(world)
    assert "about docs" not in text and "about lock" not in text
    assert "about calc" in text


def test_skipped_findings_do_not_use_the_limit(world):
    world.write_config(DEFAULT_CONFIG + "\n[review]\nfinding_limit = 1\n")
    world.diff = DIFF + LOCK_DIFF
    world.engine.respond(
        review_json(
            findings=[
                finding("about lock", path="uv.lock", line=1),
                finding("about calc", label="nit", line=6),
            ]
        )
    )

    assert world.run().ok
    [comment] = world.output_json()["comments"]
    assert comment["path"] == "calc.py"


def test_invalid_skip_globs_stop_the_run(world):
    world.write_config(DEFAULT_CONFIG + '\n[review]\nskip_globs = "docs/*"\n')
    world.engine.respond(review_json())

    result = world.run()

    assert not result.ok
    assert "skip_globs" in result.error
    assert world.output_files() == []
