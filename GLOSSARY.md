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
_Avoid_: preview, dry run

**Published Review**:
A Review the tool submits directly, visible to everyone. Only on explicit request, and never as an approval.
_Avoid_: auto-review

**Target PR**:
The pull request the Reviewer asks the tool to review. It can be in any repository the Reviewer can reach, owned by anyone.
_Avoid_: PR under review, subject
