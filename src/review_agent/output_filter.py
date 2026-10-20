"""The output filter: the last check before a Review leaves the tool (#16).

A hostile Target PR can try to make the engine write text that the Reviewer
did not intend (ADR 0002). `filter_review` runs after `ReviewMapper.map` and
before the Publisher, on all the text that leaves the tool: the Review body
and the body of each inline comment.

1. Secrets: a secret pattern (or the value of a secret that this run holds)
   anywhere stops the run. The error names the kind and the place, never
   the value.
2. Length: each comment is cut to a limit.
3. Outside code (fenced blocks and inline code spans), so that quoted code
   and suggestions stay as they are:
   - images and raw HTML are removed;
   - links stay only when they point to the Target repo; other links and
     bare URLs become plain text that GitHub does not make into a link;
   - `@mentions` are put in code spans, so they do not ping;
   - references to another repo (`owner/repo#N`, `owner/repo@sha`) are put
     in code spans, so GitHub does not link them or add a cross-reference
     event to the other repo. References to the Target repo stay.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import replace

from review_agent.errors import ReviewAgentError
from review_agent.github import PullRef
from review_agent.mapper import MappedReview

MAX_COMMENT_CHARS = 4000  # each inline comment
MAX_BODY_CHARS = 16000  # the Review body: summary, General Findings, footer
_MIN_LITERAL_SECRET = 8  # shorter values give false alarms

SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("a GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}")),
    ("a GitHub token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{80,}")),
    # The Z.AI (Zhipu) format: <32 hex>.<16 alphanumerics>.
    ("a Z.AI key", re.compile(r"\b[0-9a-f]{32}\.[A-Za-z0-9]{16}\b")),
    ("an AWS access key", re.compile(r"\b(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}\b")),
    (
        "an AWS secret key",
        re.compile(r"(?i)aws_secret_access_key\s*[=:]\s*['\"]?[A-Za-z0-9/+=]{40}"),
    ),
    ("a private key", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY( BLOCK)?-----")),
]


class SecretInReview(ReviewAgentError):
    """The Review contains text that looks like a secret."""


def filter_review(
    mapped: MappedReview, *, target: PullRef, secrets: Iterable[str] = ()
) -> MappedReview:
    """Return the filtered Review. Raises SecretInReview."""
    literals = [s for s in secrets if s and len(s) >= _MIN_LITERAL_SECRET]
    _check_secrets(mapped.body, "the Review body", literals)
    for i, c in enumerate(mapped.comments, 1):
        _check_secrets(c.body, f"inline comment {i} on {c.path}", literals)
        _check_secrets(c.path, f"the path of inline comment {i}", literals)

    return replace(
        mapped,
        body=_clean_body(mapped.body, target),
        comments=[
            replace(c, body=_clean(c.body, target, MAX_COMMENT_CHARS))
            for c in mapped.comments
        ],
    )


def _check_secrets(text: str, where: str, literals: list[str]) -> None:
    for s in literals:
        if s in text:
            raise SecretInReview(
                f"The Review contains a secret that this run uses, in {where}. "
                "Nothing was written or posted."
            )
    for kind, pattern in SECRET_PATTERNS:
        if pattern.search(text):
            raise SecretInReview(
                f"The Review contains text that looks like a secret ({kind}) "
                f"in {where}. Nothing was written or posted."
            )


_FOOTER_SEP = "\n\n---\n\n"
_MAX_FOOTER_CHARS = 500


def _clean_body(body: str, target: PullRef) -> str:
    """The Review body ends with the AI Disclosure after a `---` line. A cut
    for length must not remove it: cut the text before it."""
    head, sep, footer = body.rpartition(_FOOTER_SEP)
    if not sep or len(footer) > _MAX_FOOTER_CHARS or "\n\n" in footer.strip():
        return _clean(body, target, MAX_BODY_CHARS)
    tail = sep + _sanitize(footer, target)
    return _clean(head, target, MAX_BODY_CHARS - len(tail)) + tail


def _clean(text: str, target: PullRef, limit: int) -> str:
    out = _sanitize(text, target)
    if len(out) <= limit:
        return out
    marker = f"\n\n(Cut: this text was longer than {limit} characters.)"
    cut = limit - len(marker)
    while True:
        part = text[: max(cut, 0)]
        open_at = _segments(part)[1]
        if open_at is not None:
            part = part[:open_at]  # never keep part of a code block
        out = _sanitize(part, target).rstrip()
        excess = len(out) + len(marker) - limit
        if excess <= 0:
            return out + marker
        cut = len(part) - excess  # the rules can make text longer: cut more


def _sanitize(text: str, target: PullRef) -> str:
    parts, _ = _segments(text)
    return "".join(seg if code else _clean_prose(seg, target) for code, seg in parts)


# --- code and prose ----------------------------------------------------------

_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
# A code span ends at a blank line, as on GitHub.
# A backslash before the opening backtick escapes it (no span).
_CODE_SPAN = re.compile(r"(?<![`\\])(`+)(?!`)(?:(?!\n[ \t]*\n).)+?(?<!`)\1(?!`)", re.S)


def _segments(text: str) -> tuple[list[tuple[bool, str]], int | None]:
    """Split markdown into (is_code, text) parts: fenced blocks and inline
    code spans are code; the rest is prose. An unclosed fence runs to the end
    (as on GitHub); the second value is its start offset, else None."""
    out: list[tuple[bool, str]] = []
    prose: list[str] = []
    fence: str | None = None
    block: list[str] = []
    for line in text.splitlines(keepends=True):
        if fence is None:
            m = _FENCE.match(line)
            if m:
                fence = m.group(1)
                block = [line]
            else:
                prose.append(line)
            continue
        block.append(line)
        stripped = line.strip()
        if stripped and set(stripped) == {fence[0]} and len(stripped) >= len(fence):
            out += _split_spans("".join(prose))
            out.append((True, "".join(block)))
            prose, block, fence = [], [], None
    out += _split_spans("".join(prose))
    open_at = None
    if block:
        tail = "".join(block)
        out.append((True, tail))
        open_at = len(text) - len(tail)
    return [(c, s) for c, s in out if s], open_at


def _split_spans(text: str) -> list[tuple[bool, str]]:
    out: list[tuple[bool, str]] = []
    pos = 0
    for m in _CODE_SPAN.finditer(text):
        out.append((False, text[pos : m.start()]))
        out.append((True, m.group(0)))
        pos = m.end()
    out.append((False, text[pos:]))
    return out


# --- prose rules -------------------------------------------------------------

_MENTION = r"(?<![\w@/])@[A-Za-z0-9][A-Za-z0-9-]*(?:/[A-Za-z0-9][A-Za-z0-9_-]*)?"

# `owner/repo#N` and `owner/repo@sha`, which GitHub links across repos.
_XREF = (
    r"(?<![\w/.@-])(?P<xowner>[A-Za-z0-9][A-Za-z0-9-]*)/(?P<xrepo>[\w.-]+)"
    r"(?:#\d+|@[0-9a-fA-F]{7,40})\b"
)

_BARE_URL = (
    r"(?<![\w/@.])(?i:https?://|www\.)"
    r"[^\s<>()\[\]`'\"]*[^\s<>()\[\]`'\".,;:!?*_~]"
)

_PROSE = re.compile(
    "|".join(
        [
            r"(?P<comment><!--.*?(?:-->|\Z))",
            r"(?P<image>!\[[^\]]*\](?:\([^)]*\)|\[[^\]]*\]))",
            r"(?P<auto><(?P<aurl>(?i:https?://|www\.)[^\s<>]+)>)",
            r"(?P<link>\[(?P<ltext>[^\]]*)\]"
            r"\(\s*<?(?P<lurl>[^)\s>]*)>?(?:\s+\"[^\"]*\")?\s*\))",
            r"(?P<refdef>^ {0,3}\[[^\]]+\]:[ \t]*<?(?P<rurl>[^\s>]+)>?[^\n]*\n?)",
            r"(?P<html></?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?/?>)",
            r"(?P<url>" + _BARE_URL + r")",
            r"(?P<xref>" + _XREF + r")",
            r"(?P<mention>" + _MENTION + r")",
        ]
    ),
    re.S | re.M,
)
_TARGET_URL = re.compile(r"https://github\.com/([^/?#]+)/([^/?#]+)(?:[/?#].*)?", re.I)


def _is_target(url: str, target: PullRef) -> bool:
    m = _TARGET_URL.fullmatch(url)
    if not m or ".." in url or "\\" in url or "%2e" in url.lower():
        return False
    return (m.group(1).lower(), m.group(2).lower()) == (
        target.owner.lower(),
        target.repo.lower(),
    )


def _plain_url(url: str, target: PullRef) -> str:
    """A bare URL as text: GitHub links it, so a foreign one goes in a code
    span, where GitHub does not."""
    return url if _is_target(url, target) else f"`{url}`"


# An `@` that GitHub renders from an entity or an escape still pings.
_AT_FORMS = re.compile(r"&#0*64;|&#[xX]0*40;|&commat;|\\+@")
# A backtick in prose has no partner (code spans are split off before): escape
# it, so that it cannot pair with the backticks that this filter adds.
_STRAY_BACKTICK = re.compile(r"(?<!\\)((?:\\\\)*)`")


def _clean_prose(text: str, target: PullRef) -> str:
    text = _AT_FORMS.sub("@", text)
    text = _STRAY_BACKTICK.sub(r"\1\\`", text)

    def sub(m: re.Match[str]) -> str:
        if m.group("comment") or m.group("image") or m.group("html"):
            return ""
        if m.group("auto"):
            return _plain_url(m.group("aurl"), target)
        if m.group("link") is not None:
            url, text = m.group("lurl"), _clean_prose(m.group("ltext"), target)
            if _is_target(url, target):
                return f"[{text}]({url})"
            return text if text.strip() else f"`{url}`"
        if m.group("refdef"):
            return m.group(0) if _is_target(m.group("rurl"), target) else ""
        if m.group("url"):
            return _plain_url(m.group("url"), target)
        if m.group("xref"):
            same = (m.group("xowner").lower(), m.group("xrepo").lower()) == (
                target.owner.lower(),
                target.repo.lower(),
            )
            return m.group(0) if same else f"`{m.group(0)}`"
        if m.group("mention"):
            return f"`{m.group('mention')}`"
        return m.group(0)

    return _PROSE.sub(sub, text)
