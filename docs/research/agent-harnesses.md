# Agent harnesses for repo-checkout reviews on OpenAI-compatible endpoints

Date of research: 2026-10-19. Ticket: [#3](https://github.com/gdevenyi/review-agent/issues/3).

## Goal

The tool must review a Target PR with an agent that works over a checkout of the repository. The agent reads files, searches, and maybe runs read-only commands. It must work with **any** OpenAI-compatible base URL, API key, and model name. Some endpoints are private-network vLLM or Ollama servers. The output is a Review: one summary plus inline comments (file, line, side). Our own code posts the Review as a pending GitHub review (see `pr-review-tools.md` section 4.1 for the GitHub API facts).

This file compares harnesses that can run that agent loop. It states facts and trade-offs. It does not make the decision.

## Method

- Sources are primary only: repo source, docs inside the repos, and GitHub API data (`gh api`, `gh release list`). For vLLM and Ollama, the raw docs files in their GitHub repos (main branch, read 2026-10-19).
- Each repo was cloned with `--depth 1` and read only. No code from them was installed or run.
- "Unconfirmed" means no primary source was found for the fact.
- Line-count and effort numbers for the hand-rolled option are estimates, not facts from a source.
- Code citations are permalinks at these commits:

| Repo | Commit read | Commit date |
|---|---|---|
| The-PR-Agent/pr-agent | [`5963824`](https://github.com/The-PR-Agent/pr-agent/commit/59638246e41d37caf1d95435e00718859e35b69b) | 2026-10-19 |
| openai/openai-agents-python | [`9abc918`](https://github.com/openai/openai-agents-python/commit/9abc9182d06dbd28330af888306031269d57a175) | 2026-10-17 |
| openai/codex | [`e4568a3`](https://github.com/openai/codex/commit/e4568a3538c9cab6627d64ff8cdfc7d98b79b7db) | 2026-10-19 |
| Aider-AI/aider | [`5dc9490`](https://github.com/Aider-AI/aider/commit/5dc9490bb35f9729ef2c95d00a19ccd30c26339c) | 2026-05-22 |
| OpenHands/OpenHands | [`f3caa27`](https://github.com/OpenHands/OpenHands/commit/f3caa2778553662c22715bfb52b5eb6edf975d5b) | 2026-10-19 |
| OpenHands/software-agent-sdk | [`33d8aa2`](https://github.com/OpenHands/software-agent-sdk/commit/33d8aa29c3078d074799e2fbf5e847aeb2d71360) | 2026-10-19 |
| OpenHands/extensions | [`cc7d059`](https://github.com/OpenHands/extensions/commit/cc7d059f3b0cdb1f1d83e41d25f06e76887e905b) | 2026-10-19 |
| huggingface/smolagents | [`96f33fa`](https://github.com/huggingface/smolagents/commit/96f33faaf028479119ec8d34507b47694cf14e34) | 2026-10-06 |
| pydantic/pydantic-ai | [`ff5c666`](https://github.com/pydantic/pydantic-ai/commit/ff5c6660a01e0099611231955498a65ebb8ba6d4) | 2026-10-19 |
| SWE-agent/mini-swe-agent | [`04d809c`](https://github.com/SWE-agent/mini-swe-agent/commit/04d809ceab9df28f9adaed044884180159172930) | 2026-09-03 |

Each candidate section uses the same sub-headings: endpoint config, tool calling and fallback, file tools, sandbox and read-only, structured output, runtime, license and maintenance, fit for a Review.

Two endpoint facts matter for many rows below:

- **vLLM tool calling is a server option.** The docs start the server with `--enable-auto-tool-choice --tool-call-parser <parser>` for `tool_choice="auto"` ([vllm docs/features/tool_calling.md](https://github.com/vllm-project/vllm/blob/main/docs/features/tool_calling.md), lines 3–12). `tool_choice="required"` and named function calls use structured outputs and work "with any supported model" (same file, lines 101–103). So a private vLLM server can lack working `auto` tool calls if the operator did not set these flags.
- **Responses API on local servers.** vLLM lists `/v1/responses` as a supported endpoint ([vllm docs/serving/online_serving/openai_compatible_server.md](https://github.com/vllm-project/vllm/blob/main/docs/serving/online_serving/openai_compatible_server.md), lines 28, 195–197). Ollama supports `/v1/responses`, "Only the non-stateful flavor" ([ollama docs/api/openai-compatibility.mdx](https://github.com/ollama/ollama/blob/main/docs/api/openai-compatibility.mdx), lines 320–324). Other OpenAI-compatible servers may offer only `/v1/chat/completions` (general fact; not checked per server).

---

## 1. pr-agent (The-PR-Agent/pr-agent)

Context: `pr-review-tools.md` section 2 covers pr-agent for identity, PR URL, and posting. This section covers only repo context and agent mode.

### 1.1 Agentic or repo-checkout mode

**None in the open-source code.**

- pr-agent says it "uses a single-shot model call (no tool-use loop)" ([pr_agent/settings/configuration.toml#L598-L601](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/pr_agent/settings/configuration.toml#L598-L601)).
- The repo's own `.pr_agent.toml` lists `/agentic_review` and a `[review_agent]` section. The file header says it "is NOT read by the open-source pr-agent in this repository"; it is for Qodo's "separate, hosted, closed-source service" ([.pr_agent.toml#L1-L4](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/.pr_agent.toml#L1-L4), [#L12-L16](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/.pr_agent.toml#L12-L16)).
- `/help_docs`, the one tool that clones a repo, is disabled in code for a security fix ([pr_agent/agent/pr_agent.py#L69-L71](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/pr_agent/agent/pr_agent.py#L69-L71)).

### 1.2 Repo context without an agent

pr-agent adds static context to the single prompt:

- `repo_context_files = ["AGENTS.md"]`, capped by `repo_context_max_lines = 500` ([configuration.toml#L42](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/pr_agent/settings/configuration.toml#L42), [#L47](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/pr_agent/settings/configuration.toml#L47)).
- Dynamic context: extra lines before each hunk up to the enclosing function or class (`allow_dynamic_context=true`, `max_extra_lines_before_dynamic_context = 10`) ([configuration.toml#L64-L67](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/pr_agent/settings/configuration.toml#L64-L67)).
- Text-only skills can be injected; scripts in skills are skipped ([configuration.toml#L597-L605](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/pr_agent/settings/configuration.toml#L594-L605)).

### 1.3 Other properties

- Endpoint: `OPENAI__API_BASE`, `OPENAI__KEY`, `config.model="openai/<id>"` via LiteLLM (see `pr-review-tools.md` 2.3).
- Tool calling: not used (single shot). Model needs no tool support.
- Sandbox: not relevant; the model runs no commands.
- Structured output: no `response_format` / `json_schema` use was found in `pr_agent/algo/ai_handlers/litellm_ai_handler.py` (grep at this commit). The review is parsed from model text (unconfirmed how; see `pr-review-tools.md` 2.4 for the `--json-output` option).
- Runtime: Python `>=3.12`. License: MIT. Last commit 2026-10-19; latest release v0.48.0 (2026-10-16).

### 1.4 Fit for a Review

pr-agent can produce a diff-only review against any endpoint. It cannot let the model read other files or search the checkout. If the project wants an agent over a checkout, pr-agent is not the harness.

---

## 2. OpenAI Agents SDK (openai/openai-agents-python)

### 2.1 Endpoint config

- Custom client: `AsyncOpenAI(api_key=..., base_url=...)` and `OpenAIChatCompletionsModel(model="Model_Name", openai_client=client)` ([docs/models/index.md#L375-L390](https://github.com/openai/openai-agents-python/blob/9abc9182d06dbd28330af888306031269d57a175/docs/models/index.md#L375-L390)). Model name is a free string.
- Environment route: `OPENAI_BASE_URL` plus `set_default_openai_api("chat_completions")` ([docs/config.md#L84-L94](https://github.com/openai/openai-agents-python/blob/9abc9182d06dbd28330af888306031269d57a175/docs/config.md#L84-L94), [docs/models/index.md#L674-L675](https://github.com/openai/openai-agents-python/blob/9abc9182d06dbd28330af888306031269d57a175/docs/models/index.md#L674-L675)). The default API is Responses, not Chat Completions ([docs/config.md#L91](https://github.com/openai/openai-agents-python/blob/9abc9182d06dbd28330af888306031269d57a175/docs/config.md#L91)).
- **Tracing goes to OpenAI by default.** Without an OpenAI platform key the docs say to call `set_tracing_disabled()` ([docs/models/index.md#L379](https://github.com/openai/openai-agents-python/blob/9abc9182d06dbd28330af888306031269d57a175/docs/models/index.md#L379)). This matters for private-network use.
- LiteLLM and Any-LLM adapters exist as "best-effort, beta" ([docs/models/index.md#L734](https://github.com/openai/openai-agents-python/blob/9abc9182d06dbd28330af888306031269d57a175/docs/models/index.md#L738)).

### 2.2 Tool calling and fallback

- Tools are sent as native `tools` with `type: "function"` ([src/agents/models/chatcmpl_converter.py#L1018-L1032](https://github.com/openai/openai-agents-python/blob/9abc9182d06dbd28330af888306031269d57a175/src/agents/models/chatcmpl_converter.py#L1018-L1032)). The model must support native tool calls.
- No prompt-based fallback for models without tool calls was found.
- On Chat Completions, **only `FunctionTool` is accepted**. Any other tool type raises `UserError("Hosted tools are not supported with the ChatCompletions API ...")` ([chatcmpl_converter.py#L1034-L1037](https://github.com/openai/openai-agents-python/blob/9abc9182d06dbd28330af888306031269d57a175/src/agents/models/chatcmpl_converter.py#L1034-L1037)). Custom tool calls are also rejected ([#L274](https://github.com/openai/openai-agents-python/blob/9abc9182d06dbd28330af888306031269d57a175/src/agents/models/chatcmpl_converter.py#L274)).

### 2.3 Built-in file and shell tools

- `ShellTool`, `ApplyPatchTool`, `ComputerTool` are local runtime tools; you supply the executor ([docs/tools.md#L236-L246](https://github.com/openai/openai-agents-python/blob/9abc9182d06dbd28330af888306031269d57a175/docs/tools.md#L236-L246)). These are not `FunctionTool` subclasses, so by 2.2 they cannot be used on a Chat Completions endpoint (inference from the converter code; not tested).
- **Sandbox Agents** add a workspace with `Filesystem()`, `Shell()`, `Compaction()` capabilities ([docs/sandbox/guide.md#L189-L196](https://github.com/openai/openai-agents-python/blob/9abc9182d06dbd28330af888306031269d57a175/docs/sandbox/guide.md#L189-L196)). In code, `exec_command` is a `FunctionTool` ([src/agents/sandbox/capabilities/tools/shell_tool.py#L167](https://github.com/openai/openai-agents-python/blob/9abc9182d06dbd28330af888306031269d57a175/src/agents/sandbox/capabilities/tools/shell_tool.py#L167)), but the sandbox `apply_patch` is a `CustomTool` ([apply_patch_tool.py#L175](https://github.com/openai/openai-agents-python/blob/9abc9182d06dbd28330af888306031269d57a175/src/agents/sandbox/capabilities/tools/apply_patch_tool.py#L175)), and compaction items "are not supported for chat completions" ([chatcmpl_converter.py#L1006](https://github.com/openai/openai-agents-python/blob/9abc9182d06dbd28330af888306031269d57a175/src/agents/models/chatcmpl_converter.py#L1006)). Whether a Sandbox Agent with only `Shell()` runs on Chat Completions: unconfirmed.
- No dedicated read_file or grep `FunctionTool` ships for plain agents. On a Chat Completions endpoint you write these with `@function_tool`.

### 2.4 Sandbox and read-only

- Local `ShellTool` default is `needs_approval=False`; "SDK approval does not provide a sandbox" ([docs/tools.md#L254](https://github.com/openai/openai-agents-python/blob/9abc9182d06dbd28330af888306031269d57a175/docs/tools.md#L254)).
- `UnixLocalSandboxClient` "adds no OS-level confinement" on Linux; use Docker or hosted sandboxes for untrusted input ([docs/sandbox_agents.md#L31-L33](https://github.com/openai/openai-agents-python/blob/9abc9182d06dbd28330af888306031269d57a175/docs/sandbox_agents.md#L34-L36)).

### 2.5 Structured output

- `Agent(output_type=PydanticModel)` ([docs/agents.md#L161](https://github.com/openai/openai-agents-python/blob/9abc9182d06dbd28330af888306031269d57a175/docs/agents.md#L161)). On Chat Completions this becomes `response_format: {"type": "json_schema", ...}` ([chatcmpl_converter.py#L107-L118](https://github.com/openai/openai-agents-python/blob/9abc9182d06dbd28330af888306031269d57a175/src/agents/models/chatcmpl_converter.py#L107-L118)).
- The docs warn that some providers reject `json_schema` (`'response_format.type' : value is not one of the allowed values ['text','json_object']`) and say "We are working on a fix" ([docs/models/index.md#L716-L726](https://github.com/openai/openai-agents-python/blob/9abc9182d06dbd28330af888306031269d57a175/docs/models/index.md#L716-L726)). No prompted-JSON fallback was found.

### 2.6 Runtime, license, maintenance

- Python `>=3.10` ([pyproject.toml#L6](https://github.com/openai/openai-agents-python/blob/9abc9182d06dbd28330af888306031269d57a175/pyproject.toml#L6)). PyPI name `openai-agents`.
- License: MIT (GitHub API). Last commit 2026-10-17; latest release v0.24.0 (2026-10-15). Pre-1.0 version.

### 2.7 Fit for a Review

Good typed loop and typed output in Python. On a generic Chat Completions endpoint, the gain over a hand-rolled loop is the run loop, retries, and `output_type`; the file tools are still yours to write. Endpoints without native tool calls or without `json_schema` support fail.

---

## 3. OpenAI Codex CLI (openai/codex)

### 3.1 Endpoint config

- Custom providers are `[model_providers.<id>]` entries with `base_url`, `env_key` (name of the key env var), `wire_api`, `http_headers`, `query_params` ([codex-rs/model-provider-info/src/lib.rs#L136-L179](https://github.com/openai/codex/blob/e4568a3538c9cab6627d64ff8cdfc7d98b79b7db/codex-rs/model-provider-info/src/lib.rs#L136-L175)). Example of an inline override: `codex exec -c "model_providers.openai-proxy={ name = 'OpenAI Proxy', base_url = '.../v1', wire_api='responses' }"` ([codex-rs/responses-api-proxy/README.md#L48](https://github.com/openai/codex/blob/e4568a3538c9cab6627d64ff8cdfc7d98b79b7db/codex-rs/responses-api-proxy/README.md#L48)).
- **Responses API only.** `WireApi` has one variant, `Responses`. `wire_api = "chat"` now errors: "`wire_api = \"chat\"` is no longer supported" ([lib.rs#L100-L132](https://github.com/openai/codex/blob/e4568a3538c9cab6627d64ff8cdfc7d98b79b7db/codex-rs/model-provider-info/src/lib.rs#L100-L132)). An endpoint that has only `/v1/chat/completions` cannot be used.
- Built-in local providers: `--oss` with `--local-provider` (`ollama`, `lmstudio`) ([codex-rs/utils/cli/src/shared_options.rs#L26-L32](https://github.com/openai/codex/blob/e4568a3538c9cab6627d64ff8cdfc7d98b79b7db/codex-rs/utils/cli/src/shared_options.rs#L26-L32); [lib.rs#L654-L682](https://github.com/openai/codex/blob/e4568a3538c9cab6627d64ff8cdfc7d98b79b7db/codex-rs/model-provider-info/src/lib.rs#L654-L682)).
- Outbound calls other than the model: `model_catalog_url` "When unset, OpenAI discovery uses the Codex backend unless `base_url` overrides the inference endpoint" ([lib.rs#L145-L147](https://github.com/openai/codex/blob/e4568a3538c9cab6627d64ff8cdfc7d98b79b7db/codex-rs/model-provider-info/src/lib.rs#L142-L144)). The standalone installer downloads from `chatgpt.com` / `releases.openai.com` ([README.md#L16-L28](https://github.com/openai/codex/blob/e4568a3538c9cab6627d64ff8cdfc7d98b79b7db/README.md#L16-L28)). Other telemetry with a custom provider: unconfirmed.

### 3.2 Tool calling and fallback

- Requires native tool calls over the Responses API (follows from 3.1). No text-protocol fallback was found.

### 3.3 Built-in tools and a built-in review mode

- Shell, file search, and apply-patch exist as crates (`codex-rs/file-search`, `apply-patch`, `shell-command`; directory listing at this commit).
- **`codex exec review`** exists: "Run a code review against the current repository", with `--base <BRANCH>`, `--commit <SHA>`, `--uncommitted`, and optional custom instructions ([codex-rs/exec/src/cli.rs#L180-L181](https://github.com/openai/codex/blob/e4568a3538c9cab6627d64ff8cdfc7d98b79b7db/codex-rs/exec/src/cli.rs#L180-L181), [#L295-L327](https://github.com/openai/codex/blob/e4568a3538c9cab6627d64ff8cdfc7d98b79b7db/codex-rs/exec/src/cli.rs#L295-L327)).
- Review output type: `findings[]` with `title`, `body`, `confidence_score`, `priority`, `code_location { absolute_file_path, line_range { start, end } }`, plus `overall_correctness`, `overall_explanation` ([codex-rs/protocol/src/protocol.rs#L3622-L3662](https://github.com/openai/codex/blob/e4568a3538c9cab6627d64ff8cdfc7d98b79b7db/codex-rs/protocol/src/protocol.rs#L3622-L3662)). The rubric says "The code_location should overlap with the diff" ([codex-rs/prompts/templates/review/rubric.md#L79-L94](https://github.com/openai/codex/blob/e4568a3538c9cab6627d64ff8cdfc7d98b79b7db/codex-rs/prompts/templates/review/rubric.md#L79-L94)). There is no `side` field. Paths are absolute, so our code must make them repo-relative.

### 3.4 Sandbox and read-only

- `--sandbox` / `-s` selects `read-only`, `workspace-write`, or `danger-full-access` ([shared_options.rs#L38-L41](https://github.com/openai/codex/blob/e4568a3538c9cab6627d64ff8cdfc7d98b79b7db/codex-rs/utils/cli/src/shared_options.rs#L38-L41); [codex-rs/protocol/src/config_types.rs#L105-L113](https://github.com/openai/codex/blob/e4568a3538c9cab6627d64ff8cdfc7d98b79b7db/codex-rs/protocol/src/config_types.rs#L105-L113)).
- Linux enforcement uses bubblewrap (system `bwrap` or a bundled copy) or the legacy Landlock path; macOS uses Seatbelt ([codex-rs/core/README.md#L30-L60](https://github.com/openai/codex/blob/e4568a3538c9cab6627d64ff8cdfc7d98b79b7db/codex-rs/core/README.md#L30-L60)). This is the strongest built-in OS sandbox among the candidates.

### 3.5 Structured output

- `codex exec --output-schema FILE` ("JSON Schema file describing the model's final response shape"), `--json` (JSONL events), `-o/--output-last-message FILE`, `--ephemeral` ([exec/src/cli.rs#L39-L75](https://github.com/openai/codex/blob/e4568a3538c9cab6627d64ff8cdfc7d98b79b7db/codex-rs/exec/src/cli.rs#L39-L75)). The schema is sent in the Responses request ([codex-rs/core/src/client.rs#L1069-L1070](https://github.com/openai/codex/blob/e4568a3538c9cab6627d64ff8cdfc7d98b79b7db/codex-rs/core/src/client.rs#L1069-L1070)). Whether vLLM/Ollama honor that schema field: unconfirmed.

### 3.6 Runtime, license, maintenance

- Rust binary. Python would drive it as a subprocess. No Python library API was checked (an `app-server` crate exists; unconfirmed as a stable API).
- License: Apache-2.0 (GitHub API). Last commit 2026-10-19; latest release rust-v0.163.0 (2026-10-15). Very active.

### 3.7 Fit for a Review

Closest to a ready review agent: built-in review mode, file-and-line findings, read-only OS sandbox, JSON schema output. Limits: the endpoint must serve `/v1/responses`; no `side`; non-Python runtime; possible extra calls to OpenAI hosts.

---

## 4. aider (Aider-AI/aider)

### 4.1 Endpoint config

- `OPENAI_API_BASE=<endpoint>`, `OPENAI_API_KEY=<key>`, `aider --model openai/<model-name>` ([aider/website/docs/llms/openai-compat.md#L14-L35](https://github.com/Aider-AI/aider/blob/5dc9490bb35f9729ef2c95d00a19ccd30c26339c/aider/website/docs/llms/openai-compat.md#L14-L35)).

### 4.2 Tool calling and file access

- aider does not run a tool loop for reading files. It sends a **repo map** (tree-sitter summary of the repo) with each request ([aider/website/docs/repomap.md#L22-L26](https://github.com/Aider-AI/aider/blob/5dc9490bb35f9729ef2c95d00a19ccd30c26339c/aider/website/docs/repomap.md#L22-L26)). When the model mentions a file, aider asks the human "Add file to the chat?" ([aider/coders/base_coder.py#L1773](https://github.com/Aider-AI/aider/blob/5dc9490bb35f9729ef2c95d00a19ccd30c26339c/aider/coders/base_coder.py#L1773)).
- Native `functions` are set only in the `*_func_coder.py` edit formats; the base coder has `functions = None` ([base_coder.py#L96](https://github.com/Aider-AI/aider/blob/5dc9490bb35f9729ef2c95d00a19ccd30c26339c/aider/coders/base_coder.py#L96), [editblock_func_coder.py#L10](https://github.com/Aider-AI/aider/blob/5dc9490bb35f9729ef2c95d00a19ccd30c26339c/aider/coders/editblock_func_coder.py#L10)). So the model needs no tool-call support.
- `ask` mode: aider "will discuss your code and answer questions about it, but never make changes" ([aider/website/docs/usage/modes.md#L12](https://github.com/Aider-AI/aider/blob/5dc9490bb35f9729ef2c95d00a19ccd30c26339c/aider/website/docs/usage/modes.md#L12)). Scripting: `--message` sends one message and exits ([aider/website/docs/scripting.md](https://github.com/Aider-AI/aider/blob/5dc9490bb35f9729ef2c95d00a19ccd30c26339c/aider/website/docs/scripting.md)).

### 4.3 Sandbox, structured output

- `/run` executes shell commands chosen by the user ([aider/website/docs/usage/commands.md#L57](https://github.com/Aider-AI/aider/blob/5dc9490bb35f9729ef2c95d00a19ccd30c26339c/aider/website/docs/usage/commands.md#L57)). No sandbox feature was found.
- No structured-output option was found.

### 4.4 Runtime, license, maintenance

- Python. License: Apache-2.0 (GitHub API).
- Last commit 2026-05-22; latest release v0.86.0 (2025-08-09). No release in about 14 months.

### 4.5 Fit for a Review

aider is a human-in-the-loop pair programmer. It has no autonomous file-read or search loop and no structured output. Weak fit.

---

## 5. OpenHands (OpenHands/OpenHands, OpenHands/software-agent-sdk, OpenHands/extensions)

**Repo split.** The `OpenHands/OpenHands` repo is now "Agent Canvas", a TypeScript "self-hosted developer control center for coding agents" ([OpenHands README.md](https://github.com/OpenHands/OpenHands/blob/f3caa2778553662c22715bfb52b5eb6edf975d5b/README.md); `package.json` at root). The Python agent is in **`OpenHands/software-agent-sdk`**. This section covers the SDK.

### 5.1 Endpoint config

- `LLM(model=..., api_key=..., base_url=...)` ([examples/01_standalone_sdk/01_hello_world.py#L9-L13](https://github.com/OpenHands/software-agent-sdk/blob/33d8aa29c3078d074799e2fbf5e847aeb2d71360/examples/01_standalone_sdk/01_hello_world.py#L9-L13)). Calls go through LiteLLM (`litellm>=1.93.0,<1.106`, [openhands-sdk/pyproject.toml#L18](https://github.com/OpenHands/software-agent-sdk/blob/33d8aa29c3078d074799e2fbf5e847aeb2d71360/openhands-sdk/pyproject.toml#L18)), so an OpenAI-compatible server uses an `openai/<model>` name (LiteLLM convention; not quoted from SDK docs).

### 5.2 Tool calling and fallback

- `native_tool_calling: bool = True` ([openhands-sdk/openhands/sdk/llm/llm.py#L547-L551](https://github.com/OpenHands/software-agent-sdk/blob/33d8aa29c3078d074799e2fbf5e847aeb2d71360/openhands-sdk/openhands/sdk/llm/llm.py#L547-L551)). When false, the SDK "mock[s] function-calling via prompt": it converts tools to a text prompt and parses calls from text ([llm.py#L1453-L1460](https://github.com/OpenHands/software-agent-sdk/blob/33d8aa29c3078d074799e2fbf5e847aeb2d71360/openhands-sdk/openhands/sdk/llm/llm.py#L1453-L1460); [mixins/non_native_fc.py#L36-L48](https://github.com/OpenHands/software-agent-sdk/blob/33d8aa29c3078d074799e2fbf5e847aeb2d71360/openhands-sdk/openhands/sdk/llm/mixins/non_native_fc.py#L36-L48)). This is a real fallback for models without tool calls.

### 5.3 Built-in tools

- `openhands-tools` has `terminal`, `file_editor`, `grep`, `glob`, `apply_patch`, `task_tracker`, `delegate`, `browser_use`, and more (directory listing of [openhands-tools/openhands/tools](https://github.com/OpenHands/software-agent-sdk/tree/33d8aa29c3078d074799e2fbf5e847aeb2d71360/openhands-tools/openhands/tools)).

### 5.4 Sandbox and read-only

- Workspaces: local, `docker`, `apptainer`, `remote_api`, `cloud`, `agent_sandbox` (directory listing of [openhands-workspace/openhands/workspace](https://github.com/OpenHands/software-agent-sdk/tree/33d8aa29c3078d074799e2fbf5e847aeb2d71360/openhands-workspace/openhands/workspace)). The hello-world example runs on the host directory (`Conversation(agent=agent, workspace=cwd)`, [01_hello_world.py](https://github.com/OpenHands/software-agent-sdk/blob/33d8aa29c3078d074799e2fbf5e847aeb2d71360/examples/01_standalone_sdk/01_hello_world.py)).
- Confirmation policies `NeverConfirm` and `ConfirmRisky` ([openhands-sdk/openhands/sdk/security/confirmation_policy.py#L35-L43](https://github.com/OpenHands/software-agent-sdk/blob/33d8aa29c3078d074799e2fbf5e847aeb2d71360/openhands-sdk/openhands/sdk/security/confirmation_policy.py#L35-L43)). A read-only file-system mode for the local workspace: not found (unconfirmed).

### 5.5 Structured output

- A Pydantic `response_schema` can be attached to any tool, including `FinishTool`, so the final answer "comes back as a typed object" ([examples/01_standalone_sdk/56_structured_output.py#L1-L11](https://github.com/OpenHands/software-agent-sdk/blob/33d8aa29c3078d074799e2fbf5e847aeb2d71360/examples/01_standalone_sdk/56_structured_output.py#L1-L11)). The schema travels as tool parameters, so with mocked tool calls it is text-parsed (inference; not tested).

### 5.6 Existing PR-review plugin

- The SDK points to `OpenHands/extensions` `plugins/pr-review` for the review scripts ([examples/03_github_workflows/02_pr_review/README.md#L5](https://github.com/OpenHands/software-agent-sdk/blob/33d8aa29c3078d074799e2fbf5e847aeb2d71360/examples/03_github_workflows/02_pr_review/README.md#L5)).
- The plugin reads `LLM_BASE_URL` ([plugins/pr-review/scripts/agent_script.py#L1044](https://github.com/OpenHands/extensions/blob/cc7d059f3b0cdb1f1d83e41d25f06e76887e905b/plugins/pr-review/scripts/agent_script.py#L1044), [#L1194-L1195](https://github.com/OpenHands/extensions/blob/cc7d059f3b0cdb1f1d83e41d25f06e76887e905b/plugins/pr-review/scripts/agent_script.py#L1194-L1195)) and gives the agent `terminal` and `file_editor` ([#L1105-L1106](https://github.com/OpenHands/extensions/blob/cc7d059f3b0cdb1f1d83e41d25f06e76887e905b/plugins/pr-review/scripts/agent_script.py#L1105-L1106)).
- The **agent posts the review itself** with `gh api -X POST .../pulls/{n}/reviews`, using `side: "RIGHT"` / `"LEFT"` ([plugins/pr-review/skills/github-pr-review/SKILL.md#L29-L63](https://github.com/OpenHands/extensions/blob/cc7d059f3b0cdb1f1d83e41d25f06e76887e905b/plugins/pr-review/skills/github-pr-review/SKILL.md#L29-L63)). The skill says "If no issues: use `\"event\": \"APPROVE\"`" ([SKILL.md#L197](https://github.com/OpenHands/extensions/blob/cc7d059f3b0cdb1f1d83e41d25f06e76887e905b/plugins/pr-review/skills/github-pr-review/SKILL.md#L197)). That conflicts with the glossary: the agent would need a GitHub token, and a Published Review must never be an approval.
- Sub-agent file reviewers return a fenced JSON array of `{path, line, severity, body}` through the `finish` tool ([plugins/pr-review/scripts/prompt.py#L175-L205](https://github.com/OpenHands/extensions/blob/cc7d059f3b0cdb1f1d83e41d25f06e76887e905b/plugins/pr-review/scripts/prompt.py#L175-L205)). That pattern (agent returns data, code posts) is closer to our design.

### 5.7 Runtime, license, maintenance

- Python `>=3.12` ([openhands-sdk/pyproject.toml#L6](https://github.com/OpenHands/software-agent-sdk/blob/33d8aa29c3078d074799e2fbf5e847aeb2d71360/openhands-sdk/pyproject.toml#L6)). Uses `uv` (`uv.lock` at root).
- License: MIT for `software-agent-sdk`, `extensions`, and `OpenHands` (GitHub API).
- SDK: last commit 2026-10-19; latest release v1.56.0 (2026-10-19). Extensions: v0.31.0 (2026-10-19). Very active.

### 5.8 Fit for a Review

Has every part: OpenAI-compatible endpoint, prompt-mock fallback for no-tool models, file/grep/terminal tools, Docker workspace, typed finish output, and a reference PR-review plugin. Costs: large dependency set, LiteLLM pin, and the reference plugin's posting model differs from ours.

---

## 6. smolagents (huggingface/smolagents)

### 6.1 Endpoint config

- `OpenAIModel` ("connects to an OpenAI-compatible API server") with `model_id`, `api_base`, `api_key` ([src/smolagents/models.py#L1646-L1656](https://github.com/huggingface/smolagents/blob/96f33faaf028479119ec8d34507b47694cf14e34/src/smolagents/models.py#L1646-L1656)). `OpenAIServerModel` is an alias ([#L1796](https://github.com/huggingface/smolagents/blob/96f33faaf028479119ec8d34507b47694cf14e34/src/smolagents/models.py#L1796)). `LiteLLMModel` also takes `api_base` ([#L1205-L1241](https://github.com/huggingface/smolagents/blob/96f33faaf028479119ec8d34507b47694cf14e34/src/smolagents/models.py#L1205-L1241)).

### 6.2 Tool calling and fallback

- `ToolCallingAgent` uses native tool calls. `CodeAgent` has the model write actions as Python code in text ([README.md#L205](https://github.com/huggingface/smolagents/blob/96f33faaf028479119ec8d34507b47694cf14e34/README.md#L205), [#L252](https://github.com/huggingface/smolagents/blob/96f33faaf028479119ec8d34507b47694cf14e34/README.md#L252)). So `CodeAgent` works with models that lack tool calls.

### 6.3 Built-in tools

- Defaults are Python interpreter, final answer, user input, web search, visit webpage, Wikipedia, speech-to-text ([src/smolagents/default_tools.py](https://github.com/huggingface/smolagents/blob/96f33faaf028479119ec8d34507b47694cf14e34/src/smolagents/default_tools.py)). No read_file / grep / list_dir tool. You write them.

### 6.4 Sandbox

- `executor_type` is `local`, `blaxel`, `e2b`, `modal`, or `docker` ([src/smolagents/agents.py#L1516](https://github.com/huggingface/smolagents/blob/96f33faaf028479119ec8d34507b47694cf14e34/src/smolagents/agents.py#L1516)). Default is `local`.
- The docs say "no local python sandbox can ever be completely secure" ([docs/source/en/tutorials/secure_code_execution.md#L105](https://github.com/huggingface/smolagents/blob/96f33faaf028479119ec8d34507b47694cf14e34/docs/source/en/tutorials/secure_code_execution.md#L105)). Imports such as `os` are blocked unless added to `additional_authorized_imports` ([#L82](https://github.com/huggingface/smolagents/blob/96f33faaf028479119ec8d34507b47694cf14e34/docs/source/en/tutorials/secure_code_execution.md#L82)).

### 6.5 Structured output

- `final_answer_checks` validate the final answer ([agents.py#L287](https://github.com/huggingface/smolagents/blob/96f33faaf028479119ec8d34507b47694cf14e34/src/smolagents/agents.py#L287)). `use_structured_outputs_internally` constrains each `CodeAgent` step, not the final answer ([agents.py#L1520](https://github.com/huggingface/smolagents/blob/96f33faaf028479119ec8d34507b47694cf14e34/src/smolagents/agents.py#L1520)). A typed final-output schema option was not found.

### 6.6 Runtime, license, maintenance

- Python `>=3.10`. License: Apache-2.0 (GitHub API). Last commit 2026-10-06; latest release v1.26.0 (2026-05-29). No release in about 5 months.

### 6.7 Fit for a Review

Works with no-tool-call models through `CodeAgent`, but then the model runs generated Python, which needs a sandbox for untrusted PR content. No file tools and no typed output.

---

## 7. PydanticAI (pydantic/pydantic-ai) and Pydantic AI Harness

### 7.1 Endpoint config

- `OpenAIProvider(base_url=..., api_key=...)` or env `OPENAI_BASE_URL` / `OPENAI_API_KEY`; `OpenAIChatModel` for Chat Completions, `OpenAIResponsesModel` for Responses ([docs/models/compatible-apis.md#L360-L362](https://github.com/pydantic/pydantic-ai/blob/ff5c6660a01e0099611231955498a65ebb8ba6d4/docs/models/compatible-apis.md#L360-L362)). Model name is a free string. Separate guides exist for Ollama and others ([docs/models/ollama.md](https://github.com/pydantic/pydantic-ai/blob/ff5c6660a01e0099611231955498a65ebb8ba6d4/docs/models/ollama.md)).

### 7.2 Tool calling and fallback

- Function tools need native tool calls. No prompt-based fallback for function tools was found; `supports_tools` is checked only for output-tool mode and in the Google model ([pydantic_ai_slim/pydantic_ai/models/__init__.py#L969](https://github.com/pydantic/pydantic-ai/blob/ff5c6660a01e0099611231955498a65ebb8ba6d4/pydantic_ai_slim/pydantic_ai/models/__init__.py#L969)).
- For the final output there is a fallback (7.5).

### 7.3 Built-in file tools

- `pydantic-ai-harness` (same repo, `src/pydantic_ai_harness`) has a `FileSystem` capability with `read_file`, `list_directory`, `search_files` (regex), `find_files` (glob), `file_info`, and opt-in ripgrep `grep` / `list_files` ([docs/harness/filesystem.md#L68-L77](https://github.com/pydantic/pydantic-ai/blob/ff5c6660a01e0099611231955498a65ebb8ba6d4/docs/harness/filesystem.md#L68-L77)). Paths are resolved, symlink-checked, and filtered by allow/deny/read-only globs ([filesystem.md#L8-L11](https://github.com/pydantic/pydantic-ai/blob/ff5c6660a01e0099611231955498a65ebb8ba6d4/docs/harness/filesystem.md#L8-L11)).
- The harness is "on 0.x releases, the API may change between minor releases" ([filesystem.md#L15](https://github.com/pydantic/pydantic-ai/blob/ff5c6660a01e0099611231955498a65ebb8ba6d4/docs/harness/filesystem.md#L15)).
- A `RepoContext` capability loads `AGENTS.md` / `CLAUDE.md` files ([docs/harness/repo-context.md](https://github.com/pydantic/pydantic-ai/blob/ff5c6660a01e0099611231955498a65ebb8ba6d4/docs/harness/repo-context.md)).

### 7.4 Sandbox and read-only

- `LocalWorkspace('.', read_only=True)` lets tools "read and list files while refusing commands and changes" ([docs/workspace.md#L238-L252](https://github.com/pydantic/pydantic-ai/blob/ff5c6660a01e0099611231955498a65ebb8ba6d4/docs/workspace.md#L238-L252)).
- Harness sandboxes include bubblewrap, E2B, Modal, and others ([docs/harness/bubblewrap-sandbox.md](https://github.com/pydantic/pydantic-ai/blob/ff5c6660a01e0099611231955498a65ebb8ba6d4/docs/harness/bubblewrap-sandbox.md); directory listing of `docs/harness`).

### 7.5 Structured output

- Three modes: Tool Output (default), Native Output (`json_schema`), and Prompted Output ([docs/output.md#L321-L327](https://github.com/pydantic/pydantic-ai/blob/ff5c6660a01e0099611231955498a65ebb8ba6d4/docs/output.md#L321-L327)). Prompted Output "for models without native tool calling or structured output support ... is the only option"; it validates and retries ([output.md#L400-L404](https://github.com/pydantic/pydantic-ai/blob/ff5c6660a01e0099611231955498a65ebb8ba6d4/docs/output.md#L400-L404)).

### 7.6 Runtime, license, maintenance

- Python `>=3.11` (`pydantic_ai_slim/pyproject.toml`, `src/pydantic_ai_harness/pyproject.toml#L23`). Install docs use `uv add`.
- License: MIT (GitHub API; LICENSE file). Last commit 2026-10-19; latest release v2.57.0 (2026-10-16). Very active.

### 7.7 Fit for a Review

Strong typed output and the best-documented read-only file tools in Python. Tool loop needs native tool calls; the output alone can fall back to prompted JSON.

---

## 8. mini-swe-agent (SWE-agent/mini-swe-agent)

Added as a strong candidate found during research.

### 8.1 Endpoint config

- YAML config: `model_name: "my-local-model"`, `model_kwargs: { custom_llm_provider: "openai", api_base: "https://..." }` ([docs/models/local_models.md#L48-L55](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/docs/models/local_models.md#L44-L53)). vLLM example: `hosted_vllm/<model>` with `api_base` ([#L164-L169](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/docs/models/local_models.md#L164-L169)). Uses LiteLLM.

### 8.2 Tool calling and fallback

- One tool only: bash ([README.md#L42](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/README.md#L42)). v2 uses native tool calls by default; `litellm_textbased` / `mini -c mini_textbased.yaml` parse commands from text instead ([docs/advanced/v2_migration.md#L84-L115](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/docs/advanced/v2_migration.md#L84-L115), [#L156](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/docs/advanced/v2_migration.md#L156)).

### 8.3 File tools, sandbox

- Files are read and searched with bash (`cat`, `grep`, `find`). Each action is a separate `subprocess.run` ([README.md](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/README.md), "Executes actions with `subprocess.run`").
- Environments: local, docker/podman, singularity/apptainer, bubblewrap, contree ([README.md#L29](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/README.md#L29); `src/minisweagent/environments/extra/bubblewrap.py`). No read-only switch was found; read-only depends on the environment (for example a read-only container mount).

### 8.4 Structured output

- None. The run ends when the first output line is `COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT`; the remaining lines are the submission text ([src/minisweagent/environments/local.py#L45-L55](https://github.com/SWE-agent/mini-swe-agent/blob/04d809ceab9df28f9adaed044884180159172930/src/minisweagent/environments/local.py#L45-L55)). Our code would parse the Review from that text.

### 8.5 Runtime, license, maintenance

- Python `>=3.10`. License: MIT (GitHub API; LICENSE.md). Last commit 2026-09-03; latest release v2.4.6 (2026-07-23).

### 8.6 Fit for a Review

Very small and model-agnostic, with a text fallback. Bash-only access needs an external sandbox to be read-only, and the Review must be parsed from free text.

---

## 9. Hand-rolled minimal option

A loop over the `openai` Python client's `chat.completions.create` with three tools: `read_file(path, offset, limit)`, `grep(pattern, path_glob)`, `list_dir(path)`, plus a final `submit_review` tool or a final JSON answer.

Parts to write (all estimates):

| Part | Notes | Estimate |
|---|---|---|
| Tool loop | Send `tools=[...]`, run calls, append results, step cap, token budget | 80–150 lines |
| Three tools | Path containment under the checkout root, symlink resolution, deny `.git` and secrets files, size caps, ripgrep or Python regex | 80–150 lines |
| Final Review output | Pydantic model (summary, comments with path/line/side); try `response_format: json_schema`, else JSON in text; validate and retry | 60–120 lines |
| No-tool-call fallback | Text protocol (for example fenced `tool` blocks) parsed with regex, as OpenHands and mini-swe-agent do | 60–120 lines |
| Tests | Fake endpoint and fixture repo | 150–300 lines |

Rough total: 300–600 lines of code plus tests, about 2–4 days of work (estimate). The hazards that `FileSystem` in Pydantic AI Harness lists (path traversal, `.git`, `.env`) are the same hazards this code must handle ([docs/harness/filesystem.md#L17-L22](https://github.com/pydantic/pydantic-ai/blob/ff5c6660a01e0099611231955498a65ebb8ba6d4/docs/harness/filesystem.md#L17-L22)). With no shell tool there is no command-execution risk, so no OS sandbox is needed for the three tools.

The vLLM flags in the Method section apply here too: native tool calls with `tool_choice="auto"` need the server flags. Named or `required` tool choice uses structured outputs on vLLM (unconfirmed for other servers).

---

## 10. Comparison

| Criterion | pr-agent | OpenAI Agents SDK | Codex CLI | aider | OpenHands SDK | smolagents | PydanticAI (+Harness) | mini-swe-agent | Hand-rolled |
|---|---|---|---|---|---|---|---|---|---|
| Agent loop over checkout | No (single shot) | Yes | Yes | No (human adds files) | Yes | Yes | Yes | Yes | Yes |
| OpenAI-compatible config | `OPENAI__API_BASE`, `OPENAI__KEY`, `openai/<id>` | `AsyncOpenAI(base_url, api_key)` + `OpenAIChatCompletionsModel` | `[model_providers.x] base_url, env_key`; **Responses API only** | `OPENAI_API_BASE`, `openai/<id>` | `LLM(base_url, api_key, model)` via LiteLLM | `OpenAIModel(api_base, api_key, model_id)` | `OpenAIProvider(base_url, api_key)` + `OpenAIChatModel` | `model_kwargs.api_base` via LiteLLM | `openai` client `base_url` |
| Needs native tool calls | No | Yes | Yes | No | No (`native_tool_calling=False` mock) | No with `CodeAgent` | Yes for tools; output can be prompted | No (`litellm_textbased`) | Your choice |
| Built-in read/search tools | n/a | None on Chat Completions (write `@function_tool`) | Yes | Repo map only | `file_editor`, `grep`, `glob`, `terminal` | None | `FileSystem` (read, list, search, grep) | bash only | Write 3 tools |
| Read-only / sandbox | n/a | None built in for Chat Completions; Docker sandbox for Sandbox Agents | `--sandbox read-only` (bwrap/Landlock/Seatbelt) | None | Docker/Apptainer/remote workspaces; read-only mode not found | Remote executors; local "not completely secure" | `LocalWorkspace(read_only=True)`; bwrap sandbox | Container/bwrap environments | No shell, so containment in code |
| Structured final output | Text parsed | `output_type` → `json_schema` (fails on some providers) | `--output-schema`; built-in review findings (no `side`) | None | `response_schema` on `FinishTool` | `final_answer_checks` only | Tool / Native / Prompted output | None (free text) | Your choice |
| Built-in review mode | Yes (diff only) | No | `codex exec review` | No | Reference plugin in `extensions` | No | No | No | n/a |
| Extra outbound calls noted | None noted | Tracing to OpenAI unless disabled | Installer and model catalog defaults to OpenAI hosts | Unconfirmed | Unconfirmed | Unconfirmed | Unconfirmed | Unconfirmed | None |
| Runtime | Python ≥3.12 | Python ≥3.10 | Rust binary | Python | Python ≥3.12 | Python ≥3.10 | Python ≥3.11 | Python ≥3.10 | Python |
| License (SPDX) | MIT | MIT | Apache-2.0 | Apache-2.0 | MIT | Apache-2.0 | MIT | MIT | ours |
| Last commit | 2026-10-19 | 2026-10-17 | 2026-10-19 | 2026-05-22 | 2026-10-19 | 2026-10-06 | 2026-10-19 | 2026-09-03 | n/a |
| Latest release | v0.48.0 (2026-10-16) | v0.24.0 (2026-10-15) | rust-v0.163.0 (2026-10-15) | v0.86.0 (2025-08-09) | v1.56.0 (2026-10-19) | v1.26.0 (2026-05-29) | v2.57.0 (2026-10-16) | v2.4.6 (2026-07-23) | n/a |

## 11. Open questions

1. Which endpoints must work? If every target endpoint serves `/v1/responses` with tool calls, Codex is usable. If some serve only Chat Completions, Codex is out.
2. Must models without native tool calls be supported? If yes, only OpenHands SDK (mock mode), mini-swe-agent (text mode), smolagents (`CodeAgent`), or a hand-rolled text protocol qualify for the tool loop.
3. Is a shell tool needed at all, or are read_file / grep / list_dir enough? A shell tool needs an OS sandbox; the three tools do not.
4. Does Codex `--output-schema` work against vLLM and Ollama `/v1/responses`? Not tested.
5. Does an OpenAI Agents SDK `SandboxAgent` with only `Shell()` run on `OpenAIChatCompletionsModel`? Not tested.
6. How does the OpenHands mock tool-call mode perform with small local models? Not tested.
7. How should `side` be set? Codex and the OpenHands sub-agent format give only new-file line numbers. Our code may need to map lines to `RIGHT`/`LEFT` from the diff itself.
8. Do OpenHands SDK, smolagents, aider, PydanticAI, or mini-swe-agent send telemetry to third parties by default? Not checked.
9. Is the smolagents release gap (about 5 months) and the aider release gap (about 14 months) a sign of reduced maintenance? Not checked.
