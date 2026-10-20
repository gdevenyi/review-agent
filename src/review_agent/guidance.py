"""Reviewer Instructions (local prose) and Repo Guidance (from the base commit).

Reviewer Instructions: `instructions.md` next to the config file, then the
per-repo notes `repos/<owner>/<repo>.md` for the Target repo. A missing file
is fine.

Repo Guidance: the Target repo's own guidance files, read with the contents
API at the base commit. Never from the clone or the PR head, so a Target PR
cannot change the rules it is reviewed by. A missing file is fine.
"""

from __future__ import annotations

import logging
from pathlib import Path

from review_agent.github import GitHubClient, PullRef

log = logging.getLogger(__name__)

INSTRUCTIONS_FILE = "instructions.md"
REPO_GUIDANCE_FILES = (
    "AGENTS.md",
    "CLAUDE.md",
    "CONTRIBUTING.md",
    ".github/copilot-instructions.md",
)


def load_instructions(config_dir: Path, pr: PullRef) -> str:
    """The global prose, then the per-repo notes for `pr`'s repo."""
    paths = [
        config_dir / INSTRUCTIONS_FILE,
        config_dir / "repos" / pr.owner / f"{pr.repo}.md",
    ]
    parts = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            continue
        log.info("Reviewer Instructions: %s", path)
        if text:
            parts.append(text)
    return "\n\n".join(parts)


def fetch_repo_guidance(gh: GitHubClient, pr: PullRef, base_sha: str) -> dict[str, str]:
    """File name -> text for each Repo Guidance file at the base commit."""
    found = {}
    for name in REPO_GUIDANCE_FILES:
        text = gh.get_contents(pr, name, base_sha)
        if text is not None and text.strip():
            found[name] = text
    log.info("Repo Guidance at %s: %s", base_sha[:12], ", ".join(found) or "none")
    return found
