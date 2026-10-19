---
status: accepted
---

# The wrapper supplies the diff; the review engine gets no shell

The review engine (Claude Code on Z.AI `glm-5.3-flash`, see gdevenyi/review-agent#6) reads a checkout of a Target PR that anyone can write, and its Review carries the Reviewer's name. So our code takes the diff from GitHub's API (`application/vnd.github.diff`), puts it in the prompt, and gives the engine only Read, Grep and Glob over a `--depth 1` clone of the PR head: no Bash, no `git`. Most review agents run `git diff` themselves; we do not, because it removes the shell as an attack surface for hostile PRs, checks inline-comment anchors against the same diff GitHub validates, and stops the engine inheriting the Reviewer's git config (an external diff tool broke our bake-off).

## Consequences

- The engine cannot run tests, linters or other commands. A Finding that needs one is out of reach by design.
- We depend on GitHub's diff endpoint and its size limit; very large PRs need a separate answer.
- Repo Guidance comes from the base commit through the contents API, never from the clone.
