"""Seam 1: Reviewer Instructions and Repo Guidance in the engine prompt."""

import httpx
from harness import review_json

CONTENTS = "/repos/octo/widgets/contents"


def _in_untrusted_block(prompt: str, text: str) -> bool:
    before, sep, _ = prompt.partition(text)
    return bool(sep) and before.rfind("<untrusted") > before.rfind("</untrusted")


def test_repo_guidance_comes_from_the_base_commit_not_the_head(world):
    base, head = world.pr["base"]["sha"], world.pr["head"]["sha"]

    def agents_md(req: httpx.Request) -> httpx.Response:
        ref = req.url.params.get("ref")
        if ref == base:
            return httpx.Response(200, text="Use tabs. BASE-GUIDANCE")
        if ref == head:
            return httpx.Response(200, text="Anything goes. HEAD-GUIDANCE")
        return httpx.Response(404, json={"message": "Not Found"})

    world.github.route("GET", f"{CONTENTS}/AGENTS.md", handler=agents_md)
    world.engine.respond(review_json())

    result = world.run()

    assert result.ok, result.error
    prompt = world.engine.calls[0].prompt
    assert _in_untrusted_block(prompt, "Use tabs. BASE-GUIDANCE")
    assert "HEAD-GUIDANCE" not in prompt
    [call] = world.github.calls("GET", f"{CONTENTS}/AGENTS.md")
    assert call.params["ref"] == base


def test_reviewer_instructions_then_per_repo_notes_for_this_repo_only(world):
    config_dir = world.config_path.parent
    (config_dir / "instructions.md").write_text("GLOBAL-PROSE: focus on bugs.\n")
    (config_dir / "repos" / "octo").mkdir(parents=True)
    (config_dir / "repos" / "octo" / "widgets.md").write_text("WIDGETS-NOTES\n")
    (config_dir / "repos" / "octo" / "gadgets.md").write_text("GADGETS-NOTES\n")
    (config_dir / "repos" / "other").mkdir()
    (config_dir / "repos" / "other" / "widgets.md").write_text("OTHER-NOTES\n")
    world.engine.respond(review_json())

    result = world.run()

    assert result.ok, result.error
    prompt = world.engine.calls[0].prompt
    assert prompt.index("GLOBAL-PROSE: focus on bugs.") < prompt.index("WIDGETS-NOTES")
    assert "GADGETS-NOTES" not in prompt
    assert "OTHER-NOTES" not in prompt
    # The Reviewer wrote the prose: it is not marked as untrusted data.
    assert not _in_untrusted_block(prompt, "GLOBAL-PROSE")


def test_per_repo_notes_without_global_prose(world):
    notes = world.config_path.parent / "repos" / "octo" / "widgets.md"
    notes.parent.mkdir(parents=True)
    notes.write_text("WIDGETS-NOTES\n")
    world.engine.respond(review_json())

    result = world.run()

    assert result.ok, result.error
    assert "WIDGETS-NOTES" in world.engine.calls[0].prompt


def test_only_the_prose_enters_the_prompt_not_the_toml_switches(world):
    world.write_config(
        '[auth]\nlogin = "reviewer"\n\n[review]\nskip_globs = ["SWITCH-GLOB-*.lock"]\n'
    )
    world.engine.respond(review_json())

    result = world.run()

    assert result.ok, result.error
    assert "SWITCH-GLOB" not in world.engine.calls[0].prompt


def test_all_guidance_files_are_read_and_missing_ones_are_fine(world):
    world.github.route(
        "GET", f"{CONTENTS}/.github/copilot-instructions.md", text="COPILOT-RULES"
    )
    world.github.route("GET", f"{CONTENTS}/CONTRIBUTING.md", text="CONTRIB-RULES")
    world.engine.respond(review_json())

    result = world.run()

    assert result.ok, result.error
    prompt = world.engine.calls[0].prompt
    assert _in_untrusted_block(prompt, "COPILOT-RULES")
    assert _in_untrusted_block(prompt, "CONTRIB-RULES")
    asked = {r.path.removeprefix(CONTENTS + "/") for r in world.github.calls("GET")}
    assert {
        "AGENTS.md",
        "CLAUDE.md",
        "CONTRIBUTING.md",
        ".github/copilot-instructions.md",
    } <= asked


def test_no_instructions_and_no_guidance_is_fine(world):
    world.engine.respond(review_json())

    result = world.run()

    assert result.ok, result.error
    assert world.output_files()


def test_guidance_read_failure_stops_the_run_with_nothing_written(world):
    world.github.route(
        "GET", f"{CONTENTS}/CLAUDE.md", status=403, json={"message": "Forbidden"}
    )
    world.engine.respond(review_json())

    result = world.run()

    assert not result.ok
    assert "CLAUDE.md" in result.error
    assert world.engine.calls == []
    assert world.output_files() == []
    assert world.github.writes == []


def test_default_language_is_simplified_technical_english(world):
    world.engine.respond(review_json())

    world.run()

    assert "ASD-STE100 Simplified Technical English" in world.engine.calls[0].prompt


def test_review_language_switch_replaces_the_default(world):
    world.write_config(
        '[auth]\nlogin = "reviewer"\n\n[review]\nlanguage = "Canadian French"\n'
    )
    world.engine.respond(review_json())

    result = world.run()

    assert result.ok, result.error
    prompt = world.engine.calls[0].prompt
    assert "in this language: Canadian French" in prompt
    assert "ASD-STE100" not in prompt


def test_prompt_states_the_precedence(world):
    world.engine.respond(review_json())

    world.run()

    prompt = world.engine.calls[0].prompt
    assert "Repo Guidance wins on code conventions" in prompt
    assert "Reviewer Instructions win on tone and format" in prompt
