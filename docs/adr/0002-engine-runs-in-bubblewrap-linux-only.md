---
status: accepted
---

# The review engine runs inside a bubblewrap sandbox; Linux only

A hostile Target PR controls everything the engine reads, and the worst outcome is the Reviewer's local secrets (keys, `~/.env`, `~/.ssh`) leaking into a public Review. Claude Code's `--restricted` mode confines its file tools, but only inside the app, and our bake-off saw another engine (OpenCode) read outside its checkout despite its permission config. So the engine also runs under bubblewrap: the clone and system paths read-only, a fresh temp HOME as the only writable path, the real HOME invisible, `--clearenv` with only the Z.AI base URL and key passed in, `--die-with-parent`, a new PID namespace, network shared. bubblewrap exists only on Linux, so v1 supports Linux only.

## Consequences

- The CLI refuses to run without a working sandbox. The GitHub Action tries it and continues with a log warning if unprivileged user namespaces are blocked, because the runner VM holds only the job's secrets.
- macOS is out of scope for v1.
- Network egress is not filtered yet; the engine has no web tools, but a domain allowlist is still open.
