"""PromptBuilder: the engine prompt, with untrusted parts in delimited blocks.

Each untrusted block is `<untrusted-data id="N">` ... `</untrusted-data id="N">`
with a random id `N` per prompt, so text in the PR cannot close a block.
"""

from __future__ import annotations

import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib.resources import files

from review_agent.config import DEFAULT_LANGUAGE

STE_STYLE = " (short sentences, active voice, one instruction per sentence)"

TEMPLATE: str = files("review_agent").joinpath("prompt.md").read_text("utf-8")


@dataclass
class PromptBuilder:
    title: str
    body: str
    diff: str
    # Repo Guidance: file name -> text, from the base commit (ticket #17).
    repo_guidance: Mapping[str, str] = field(default_factory=dict)
    # Reviewer Instructions prose (global, then per-repo notes). The Reviewer
    # wrote it, so it is not in an untrusted block.
    instructions: str = ""
    language: str = DEFAULT_LANGUAGE
    nonce: str = field(default_factory=lambda: secrets.token_hex(8))

    def untrusted(self, text: str) -> str:
        return (
            f'<untrusted-data id="{self.nonce}">\n'
            f"{text.rstrip()}\n"
            f'</untrusted-data id="{self.nonce}">'
        )

    def build(self) -> str:
        # Pick a nonce that is in none of the untrusted parts first, so every
        # block in this prompt has the same id.
        parts = [self.title, self.body, self.diff, *self.repo_guidance.values()]
        while any(self.nonce in p for p in parts):
            self.nonce = secrets.token_hex(8)
        guidance = "(none)"
        if self.repo_guidance:
            guidance = "\n\n".join(
                f"### {name}\n\n{self.untrusted(text)}"
                for name, text in self.repo_guidance.items()
            )
        values = {
            "{NONCE}": self.nonce,
            "{TITLE}": self.untrusted(self.title),
            "{BODY}": self.untrusted(self.body or "(empty)"),
            "{DIFF}": self.untrusted(self.diff),
            "{GUIDANCE}": guidance,
            "{INSTRUCTIONS}": self.instructions.strip() or "(none)",
            "{LANGUAGE}": self.language
            + (STE_STYLE if self.language == DEFAULT_LANGUAGE else ""),
        }
        # One pass, so a placeholder inside PR text is not replaced.
        out, rest = [], TEMPLATE
        while rest:
            hits = [(rest.find(k), k) for k in values if k in rest]
            if not hits:
                out.append(rest)
                break
            i, key = min(hits)
            out += [rest[:i], values[key]]
            rest = rest[i + len(key) :]
        return "".join(out)
