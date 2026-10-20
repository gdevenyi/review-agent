# review-agent

A tool that writes pull-request reviews with an LLM and posts them under the Reviewer's own GitHub identity, on any pull request the Reviewer asks for.

## Language

**Reviewer**:
The human GitHub user whose identity every Review carries. There is exactly one Reviewer per installation.
_Avoid_: bot, agent, user account

**Review**:
A GitHub pull-request review, with a summary and inline comments, that shows the Reviewer's name and avatar.
_Avoid_: comment, feedback, report

**Draft Review**:
A Review left pending on GitHub, visible only to the Reviewer until the Reviewer edits and submits it. This is the default outcome.
_Avoid_: preview, draft file

**Published Review**:
A Review the tool submits directly, visible to everyone. Only on explicit request, and never as an approval.
_Avoid_: auto-review

**Dry Run**:
A run that writes the Review to local files and posts nothing to GitHub. It is not a Draft Review: nothing is left on the Target PR.
_Avoid_: preview, test run

**Finding**:
One problem, suggestion, or question the Review raises. It carries a Conventional Comments label (`issue (blocking)`, `suggestion`, `question`, `nit`). A Finding tied to a diff line becomes an inline comment; any other Finding goes under "General" in the Review summary.
_Avoid_: issue, item, P1

**Reviewer Instructions**:
The Reviewer's standing preferences for every Review (priorities, tone, language, what to skip, the Finding limit), plus optional per-repository notes added after them.
_Avoid_: prompt, system prompt, persona

**Repo Guidance**:
The Target repository's own conventions for contributors and agents (such as `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`), always taken from the base branch, never from the Target PR. It wins over Reviewer Instructions on code conventions; Reviewer Instructions win on tone and format.
_Avoid_: repo rules, project prompt

**AI Disclosure**:
The footer on every Review that says an AI helped draft it.
_Avoid_: watermark, signature

**Target PR**:
The pull request the Reviewer asks the tool to review. It can be in any repository the Reviewer can reach, owned by anyone.
_Avoid_: PR under review, subject
