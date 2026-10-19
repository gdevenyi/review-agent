# PR review tools: adopt or build

Date of research: 2026-10-19.

## Goal

The user wants a tool that:

- takes an OpenAI-compatible endpoint and API key,
- posts PR reviews **as the user's own GitHub account**,
- runs **on demand** against any PR on GitHub, including repos the user does not own and cannot install an Action or App in.

This file compares three tools and lists the GitHub API facts for a build-from-scratch option. It states facts and trade-offs. It does not make the decision.

## Method

- Sources are primary only: repo source, READMEs, docs in the repos, GitHub API data (`gh api`, `gh repo view`, `gh release list`), PyPI JSON, and docs.github.com.
- Each repo was cloned with `--depth 1` and read only. No code from them was installed or run.
- Code citations are permalinks at these commits:

| Repo | Commit read | Commit date |
|---|---|---|
| kodustech/kodus-ai | [`266466b`](https://github.com/kodustech/kodus-ai/commit/266466b4784185342262ff61673f807e40c51827) | 2026-10-18 |
| The-PR-Agent/pr-agent | [`5963824`](https://github.com/The-PR-Agent/pr-agent/commit/59638246e41d37caf1d95435e00718859e35b69b) | 2026-10-19 |
| hackertron/selfreview | [`2eef1d5`](https://github.com/hackertron/selfreview/commit/2eef1d589d2b90eff08bdeb06761bead4156061d) | 2026-10-13 |

- "Unconfirmed" means no primary source was found for the fact.
- docs.github.com text was read through a summarizing fetch. The key sentences in sections 4.2 and 4.3 were then checked against the raw page HTML with `curl` + `grep`. Other docs.github.com wording can differ slightly from the page.

Permalink prefixes used below:

- K = `https://github.com/kodustech/kodus-ai/blob/266466b4784185342262ff61673f807e40c51827`
- P = `https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b`
- S = `https://github.com/hackertron/selfreview/blob/2eef1d589d2b90eff08bdeb06761bead4156061d`

---

## 1. kodustech/kodus-ai (Kodus)

### 1.1 Review as the user's own account via PAT

**Yes, with conditions.** Kodus supports a GitHub token mode beside its GitHub App / OAuth mode.

- Auth modes are `oauth`, `token`, `basic` ([libs/platform/domain/platformIntegrations/enums/codeManagement/authMode.enum.ts#L1-L5](https://github.com/kodustech/kodus-ai/blob/266466b4784185342262ff61673f807e40c51827/libs/platform/domain/platformIntegrations/enums/codeManagement/authMode.enum.ts#L1-L5)).
- Token mode calls `authenticateWithToken`, encrypts the PAT, and stores it with `org: accountLogin` ([github.service.ts#L520-L523](https://github.com/kodustech/kodus-ai/blob/266466b4784185342262ff61673f807e40c51827/libs/platform/infrastructure/adapters/services/github/github.service.ts#L520-L523), [#L640-L656](https://github.com/kodustech/kodus-ai/blob/266466b4784185342262ff61673f807e40c51827/libs/platform/infrastructure/adapters/services/github/github.service.ts#L640-L656)).
- The docs say: "With a token, reviews are published under your GitHub profile instead of Kody's, and GitHub Checks / PR status aren't available." ([docs/en/how_to_use/code_review/general_config/github_pat.mdx#L72](https://github.com/kodustech/kodus-ai/blob/266466b4784185342262ff61673f807e40c51827/docs/en/how_to_use/code_review/general_config/github_pat.mdx#L72)).
- How to configure: paste a **fine-grained PAT** in the web UI (onboarding "Connect via token", or Repositories > Github > Token tab) ([github_pat.mdx#L65-L70](https://github.com/kodustech/kodus-ai/blob/266466b4784185342262ff61673f807e40c51827/docs/en/how_to_use/code_review/general_config/github_pat.mdx#L65-L70)).
- Required FGPAT permissions include **Contents: read/write, Pull requests: read/write, Webhooks: read/write**, and Organization Members: read. The resource owner must be the organization ([github_pat.mdx#L42-L59](https://github.com/kodustech/kodus-ai/blob/266466b4784185342262ff61673f807e40c51827/docs/en/how_to_use/code_review/general_config/github_pat.mdx#L42-L59)).

### 1.2 On demand against an arbitrary PR URL

**No, not for repos the user does not own.**

- Reviews are driven by repository webhooks. In token mode Kodus creates a webhook on each selected repo with `octokit.repos.createWebhook` ([github.service.ts#L5841](https://github.com/kodustech/kodus-ai/blob/266466b4784185342262ff61673f807e40c51827/libs/platform/infrastructure/adapters/services/github/github.service.ts#L5841)). The PAT docs require "Webhooks: Read and write" with the organization as resource owner ([github_pat.mdx#L46](https://github.com/kodustech/kodus-ai/blob/266466b4784185342262ff61673f807e40c51827/docs/en/how_to_use/code_review/general_config/github_pat.mdx#L46), [#L57](https://github.com/kodustech/kodus-ai/blob/266466b4784185342262ff61673f807e40c51827/docs/en/how_to_use/code_review/general_config/github_pat.mdx#L57)). A user cannot get such a token for an org or repo they do not control, so third-party repos are out of reach in token mode. (That webhook creation needs repo admin is general GitHub behavior, not cited here.)
- Manual trigger is a PR comment `@kody start-review` ([docs/en/how_to_use/code_review/flow.mdx#L16](https://github.com/kodustech/kodus-ai/blob/266466b4784185342262ff61673f807e40c51827/docs/en/how_to_use/code_review/flow.mdx#L16)). This also arrives by webhook.
- Reviews post to `owner: githubAuthDetail?.org` ([github.service.ts#L4971-L4977](https://github.com/kodustech/kodus-ai/blob/266466b4784185342262ff61673f807e40c51827/libs/platform/infrastructure/adapters/services/github/github.service.ts#L4971-L4977)), i.e. the owner tied to the integration, not an arbitrary owner from a URL.
- The `kodus` CLI (`@kodus/cli` 0.4.21) is a client of the Kodus API. Default API is `https://api.kodus.io` ([apps/cli/src/constants.ts#L6](https://github.com/kodustech/kodus-ai/blob/266466b4784185342262ff61673f807e40c51827/apps/cli/src/constants.ts#L6)). `kodus review` reviews **local** diffs (working tree, staged, branch) ([apps/cli/README.md#L48-L56](https://github.com/kodustech/kodus-ai/blob/266466b4784185342262ff61673f807e40c51827/apps/cli/README.md#L48-L56)). `kodus pr suggestions --pr-url` only **fetches** existing suggestions ([apps/cli/src/features/pr/command.ts#L56-L59](https://github.com/kodustech/kodus-ai/blob/266466b4784185342262ff61673f807e40c51827/apps/cli/src/features/pr/command.ts#L56-L59)). No CLI command that reviews a PR URL and posts to GitHub was found.
- Trial mode without an account: 5 reviews/day, 10 files, 500 lines per file ([apps/cli/README.md#L549-L551](https://github.com/kodustech/kodus-ai/blob/266466b4784185342262ff61673f807e40c51827/apps/cli/README.md#L549-L551)).

### 1.3 Custom OpenAI-compatible base URL + key

**Yes.**

- Self-hosted env mode: `API_OPEN_AI_API_KEY`, `API_OPENAI_FORCE_BASE_URL`, `API_LLM_PROVIDER_MODEL` ([.env.schema#L404](https://github.com/kodustech/kodus-ai/blob/266466b4784185342262ff61673f807e40c51827/.env.schema#L404), [#L409](https://github.com/kodustech/kodus-ai/blob/266466b4784185342262ff61673f807e40c51827/.env.schema#L409), [#L423](https://github.com/kodustech/kodus-ai/blob/266466b4784185342262ff61673f807e40c51827/.env.schema#L423); example in [docs/en/how_to_deploy/deploy_kodus/generic_vm.mdx#L33-L34](https://github.com/kodustech/kodus-ai/blob/266466b4784185342262ff61673f807e40c51827/docs/en/how_to_deploy/deploy_kodus/generic_vm.mdx#L33-L34)).
- BYOK in the UI: "OpenAI-compatible" provider asks for base URL, key, and model ID ([docs/en/how_to_use/byok.mdx#L261-L266](https://github.com/kodustech/kodus-ai/blob/266466b4784185342262ff61673f807e40c51827/docs/en/how_to_use/byok.mdx#L261-L266)). Arbitrary model IDs are accepted; Kodus sends a 1-token test call to validate ([byok.mdx#L80](https://github.com/kodustech/kodus-ai/blob/266466b4784185342262ff61673f807e40c51827/docs/en/how_to_use/byok.mdx#L80)).

### 1.4 Inline comments and drafts

- Inline: **yes**. Line comments use `pulls.createReviewComment` one at a time ([github.service.ts#L4353](https://github.com/kodustech/kodus-ai/blob/266466b4784185342262ff61673f807e40c51827/libs/platform/infrastructure/adapters/services/github/github.service.ts#L4353)). The overall comment uses `pulls.createReview` with `event: 'COMMENT'` ([#L4971-L4977](https://github.com/kodustech/kodus-ai/blob/266466b4784185342262ff61673f807e40c51827/libs/platform/infrastructure/adapters/services/github/github.service.ts#L4971-L4977)). The code can also `APPROVE` ([#L6450-L6454](https://github.com/kodustech/kodus-ai/blob/266466b4784185342262ff61673f807e40c51827/libs/platform/infrastructure/adapters/services/github/github.service.ts#L6450-L6454)) and `REQUEST_CHANGES` ([#L6574-L6578](https://github.com/kodustech/kodus-ai/blob/266466b4784185342262ff61673f807e40c51827/libs/platform/infrastructure/adapters/services/github/github.service.ts#L6574-L6578)).
- Draft / pending review for human confirmation: **not found** (unconfirmed). The CLI `--prompt-only` gives structured local output for local diffs only.

### 1.5 Weight and runtime dependencies

**Heavy platform.**

- Self-hosted prod compose runs `api`, `worker`, `worker-analytics`, `webhooks`, `web`, `db_postgres` (pgvector/pg16), `db_mongodb` (mongo 8.2.11) ([docker-compose.prod.yml#L17-L150](https://github.com/kodustech/kodus-ai/blob/266466b4784185342262ff61673f807e40c51827/docker-compose.prod.yml#L17-L150)).
- "RabbitMQ is required in 2.0" ([generic_vm.mdx#L75-L77](https://github.com/kodustech/kodus-ai/blob/266466b4784185342262ff61673f807e40c51827/docs/en/how_to_deploy/deploy_kodus/generic_vm.mdx#L75-L77)). RabbitMQ is **not** a service in `docker-compose.prod.yml` at this commit. How it is provisioned is unconfirmed.
- Minimum VM: 2 CPU cores, 8 GB RAM, 60 GB disk ([README.md#L170-L176](https://github.com/kodustech/kodus-ai/blob/266466b4784185342262ff61673f807e40c51827/README.md#L170-L176)).
- Needs a public URL for webhooks. Stack: NestJS / TypeScript monorepo (pnpm).

### 1.6 License and maintenance

- License: dual. Non-EE code is AGPL-3.0; files with `.ee.` or paths with `ee/` are under a commercial Kodus Enterprise License ([license.md#L1-L12](https://github.com/kodustech/kodus-ai/blob/266466b4784185342262ff61673f807e40c51827/license.md#L1-L12), [license_ee.md](https://github.com/kodustech/kodus-ai/blob/266466b4784185342262ff61673f807e40c51827/license_ee.md)). The text says "AGPL-3.0" without `-only` or `-or-later`. GitHub API returns SPDX `NOASSERTION`. Exact SPDX id: unconfirmed.
- `KODUS_LICENSE_KEY` "Unlocks enterprise features" ([.env.schema#L90-L95](https://github.com/kodustech/kodus-ai/blob/266466b4784185342262ff61673f807e40c51827/.env.schema#L90-L95)). The README self-host box also says "Request a trial license" while the plan table lists Community self-hosting as free ([README.md#L170-L181](https://github.com/kodustech/kodus-ai/blob/266466b4784185342262ff61673f807e40c51827/README.md#L170-L181), [#L252-L256](https://github.com/kodustech/kodus-ai/blob/266466b4784185342262ff61673f807e40c51827/README.md#L252-L256)). Community plan limits: 10 Kody Rules, 3 active plugins.
- Telemetry: self-hosted instances send one anonymous heartbeat per day; opt out with `KODUS_TELEMETRY_DISABLED=true` ([README.md#L51](https://github.com/kodustech/kodus-ai/blob/266466b4784185342262ff61673f807e40c51827/README.md#L51)).
- Activity (GitHub API, 2026-10-19): created 2025-03-28; last push 2026-10-19; latest release `web-1.2.7` (2026-10-06); `selfhosted-2.2.5` (2026-10-05); 1502 stars, 176 forks; 134 open issues; 70 issues opened in the last 30 days. Not a fork. No rename history found.

---

## 2. The-PR-Agent/pr-agent (PR-Agent)

### 2.1 Review as the user's own account via PAT

**Yes. This is the default deployment type.**

- `[github] deployment_type = "user"` is the default ([pr_agent/settings/configuration.toml#L315-L317](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/pr_agent/settings/configuration.toml#L315-L317)).
- Token key: `[github] user_token = ""  # A GitHub personal access token with 'repo' scope.` ([pr_agent/settings/.secrets_template.toml#L67-L70](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/pr_agent/settings/.secrets_template.toml#L67-L70)). Env var form: `GITHUB__USER_TOKEN` ([docs/docs/installation/locally.md#L22](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/docs/docs/installation/locally.md#L22)).
- Code: user mode reads `github.user_token` and uses `Auth.Token(token)` ([pr_agent/git_providers/github_provider.py#L1888-L1895](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/pr_agent/git_providers/github_provider.py#L1888-L1895)). All posts are therefore made by the token's owner.
- For third-party public repos, the template says `repo` scope; `public_repo` should be enough for public repos (see section 4.2). The tool docs do not test this. Unconfirmed in the tool.

### 2.2 On demand against an arbitrary PR URL

**Yes.**

- CLI: `pr-agent --pr_url <pr_url> review` (also `describe`, `improve`, `ask`) ([locally.md#L177-L183](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/docs/docs/installation/locally.md#L177-L183); argparse usage in [pr_agent/cli.py#L109-L116](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/pr_agent/cli.py#L109-L116)).
- Docker one-shot: `docker run --rm -it -e OPENAI__KEY=... -e GITHUB__USER_TOKEN=... pragent/pr-agent:latest --pr_url <pr_url> review` ([locally.md#L22](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/docs/docs/installation/locally.md#L22)).
- pip: `pip install "pr-agent[github]"` ([locally.md#L105](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/docs/docs/installation/locally.md#L105)).
- No Action or App install is needed on the target repo. The only gate is what the PAT may write (section 4.2).
- Side effect on foreign repos: `/review` adds labels by default (`enable_review_labels_security=true`, `enable_review_labels_effort=true`, [configuration.toml#L204-L205](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/pr_agent/settings/configuration.toml#L204-L205)). A label failure is caught and logged as a warning, not raised ([github_provider.py#L2022-L2028](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/pr_agent/git_providers/github_provider.py#L2022-L2028)). Whether a non-collaborator gets a 403 on labels was not tested.

### 2.3 Custom OpenAI-compatible base URL + key

**Yes, via LiteLLM.**

- Keys: `[openai] api_base`, plus the key, or env `OPENAI__API_BASE` and `OPENAI__KEY` ([docs/docs/usage-guide/changing_a_model.md#L34-L49](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/docs/docs/usage-guide/changing_a_model.md#L34-L49)).
- Key name inconsistency: that doc shows `api_key` in TOML (L42), but the template uses `key` ([.secrets_template.toml#L9-L10](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/pr_agent/settings/.secrets_template.toml#L9-L10)) and the code reads `OPENAI.KEY` ([pr_agent/algo/ai_handlers/litellm_ai_handler.py#L722](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/pr_agent/algo/ai_handlers/litellm_ai_handler.py#L722)). Use `key` / `OPENAI__KEY`.
- Arbitrary model names: set `[config] model = "openai/<model-id>"` (the `openai/` prefix routes through LiteLLM's OpenAI-compatible path) and `[config] custom_model_max_tokens` because unlisted names are not in the max-tokens table ([changing_a_model.md#L773-L797](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/docs/docs/usage-guide/changing_a_model.md#L773-L797)). `fallback_models` is also a list key there.
- Provider auth and endpoint settings are rejected as CLI arguments; set them in config or env ([docs/docs/usage-guide/automations_and_usage.md#L29](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/docs/docs/usage-guide/automations_and_usage.md#L29)).

### 2.4 Inline comments and drafts

- Default `/review` output is one summary comment on the PR conversation. The reviewer publishes it with `publish_persistent_comment` / `publish_persistent_comment_full` ([pr_agent/tools/pr_reviewer.py#L419-L450](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/pr_agent/tools/pr_reviewer.py#L419-L450)), and `persistent_comment=true` edits it in place on re-runs ([configuration.toml#L190](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/pr_agent/settings/configuration.toml#L190)). The GitHub body of `publish_persistent_comment` ([github_provider.py#L607](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/pr_agent/git_providers/github_provider.py#L607)) was not traced to the exact API call. Progress and status comments use `publish_comment` → `create_issue_comment` ([github_provider.py#L890-L904](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/pr_agent/git_providers/github_provider.py#L890-L904)).
- Inline findings are **opt-in**: `[pr_reviewer] inline_key_issues=false` by default ([configuration.toml#L199](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/pr_agent/settings/configuration.toml#L199)). When on, they go through the Reviews API as one batch: `self.pr.create_review(commit=..., event="COMMENT", comments=comments)` ([github_provider.py#L997](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/pr_agent/git_providers/github_provider.py#L997), [#L1238](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/pr_agent/git_providers/github_provider.py#L1238)). Default `num_max_findings = 3` ([configuration.toml#L201](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/pr_agent/settings/configuration.toml#L201)).
- `/improve` can publish committable suggestions (`committable_code_suggestions = false` by default, [configuration.toml#L257-L259](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/pr_agent/settings/configuration.toml#L257-L259)).
- Pending reviews: the code creates a pending review **only to validate** one comment, then deletes it (`_verify_code_comment`, [github_provider.py#L1274-L1291](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/pr_agent/git_providers/github_provider.py#L1274-L1291)). No "leave pending for a human" option was found.
- Local draft output: **yes**.
  - `[config] publish_output=false` with `verbosity_level=2` prints results locally and publishes nothing ([automations_and_usage.md#L31-L39](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/docs/docs/usage-guide/automations_and_usage.md#L31-L39)).
  - `pr-agent --pr_url ... --json-output review.json review` writes the parsed review to JSON ([docs/docs/tools/review.md#L41-L44](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/docs/docs/tools/review.md#L41-L44)).
  - A human then needs a separate step to post. PR-Agent has no "post this saved draft" command (unconfirmed; none found).

### 2.5 Weight and runtime dependencies

**Light: one CLI, pip package, or Docker one-shot. No DB, no queue for CLI use.**

- Python `>=3.12` ([pyproject.toml#L20](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/pyproject.toml#L20)).
- Base deps include `litellm==1.105.1`, `openai`, `anthropic`, `dynaconf`, `fastapi`, `uvicorn`, `gunicorn`, `GitPython`, `tiktoken`, `langfuse`, `opentelemetry-*`, `prometheus-client`, `pydantic`, `Jinja2` ([pyproject.toml#L32-L74](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/pyproject.toml#L32-L74)). GitHub support is the extra `github = ["PyGithub>=2.10,<3"]` ([pyproject.toml#L92-L94](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/pyproject.toml#L92-L94)). The dependency tree is large even though the runtime is one process.
- Server modes (webhook app, polling) exist but are optional.

### 2.6 License and maintenance

- License: MIT (GitHub API `mit`; PyPI 0.48.0 license text MIT, "Copyright (c) 2026 The PR Agent").
- Activity (2026-10-19): last commit 2026-10-19; latest release [v0.48.0](https://github.com/The-PR-Agent/pr-agent/releases/tag/v0.48.0) (2026-10-16); releases about every 1–2 weeks (v0.44.0 2026-08-30 to v0.48.0); PyPI `pr-agent` 0.48.0; 13454 stars; 11 open issues; 139 issues opened in the last 30 days.
- History:
  - Repo id 662766482 is the same for `Codium-ai/pr-agent`, `qodo-ai/pr-agent`, and `The-PR-Agent/pr-agent` (`gh api` follows the redirect). So this is the same repo, renamed and transferred, not a fork.
  - README: "Qodo has donated PR-Agent to the open-source community"; "community-maintained legacy project of Qodo"; Qodo Merge became Qodo 2.0; first external maintainer is @naorpeled; "in the process of being donated to an open-source foundation" ([README.md#L25-L27](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/README.md#L25-L27), [#L218-L234](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/README.md#L218-L234)). Qodo is listed as Gold sponsor.
  - Docker Hub moved from `codiumai/pr-agent` (frozen at v0.31) to `pragent/pr-agent` from 0.34.2 ([README.md#L62](https://github.com/The-PR-Agent/pr-agent/blob/59638246e41d37caf1d95435e00718859e35b69b/README.md#L62)).
  - Docs moved to docs.pr-agent.ai.

---

## 3. hackertron/selfreview (Selfreview)

### 3.1 Review as the user's own account via PAT

**No.** GitHub auth is GitHub App only.

- Client signs an App JWT, then uses installation tokens ([src/github/client.ts#L1-L48](https://github.com/hackertron/selfreview/blob/2eef1d589d2b90eff08bdeb06761bead4156061d/src/github/client.ts#L1-L48)). The review identity is `<slug>[bot]` ([client.ts#L38-L40](https://github.com/hackertron/selfreview/blob/2eef1d589d2b90eff08bdeb06761bead4156061d/src/github/client.ts#L38-L40); used in [src/pipeline/run.ts#L62-L63](https://github.com/hackertron/selfreview/blob/2eef1d589d2b90eff08bdeb06761bead4156061d/src/pipeline/run.ts#L62-L63)).
- No PAT setting exists in the env schema ([src/config.ts#L5-L65](https://github.com/hackertron/selfreview/blob/2eef1d589d2b90eff08bdeb06761bead4156061d/src/config.ts#L5-L65)).

### 3.2 On demand against an arbitrary PR URL

**No.**

- Triggers are webhooks from an installed GitHub App, plus a `/selfreview` PR comment ([README.md#L26-L28](https://github.com/hackertron/selfreview/blob/2eef1d589d2b90eff08bdeb06761bead4156061d/README.md#L26-L28), [#L89](https://github.com/hackertron/selfreview/blob/2eef1d589d2b90eff08bdeb06761bead4156061d/README.md#L89)).
- Only the App owner's repos and `ALLOWED_ACCOUNTS` are reviewed ([README.md#L74](https://github.com/hackertron/selfreview/blob/2eef1d589d2b90eff08bdeb06761bead4156061d/README.md#L74), [#L95-L103](https://github.com/hackertron/selfreview/blob/2eef1d589d2b90eff08bdeb06761bead4156061d/README.md#L95-L103)).
- No CLI entry point found. `package.json` scripts are `start`, `migrate`, `test`, `typecheck` ([package.json](https://github.com/hackertron/selfreview/blob/2eef1d589d2b90eff08bdeb06761bead4156061d/package.json)).

### 3.3 Custom OpenAI-compatible base URL + key

**Yes.**

- Keys: `OPENAI_COMPATIBLE_API_KEY`, `OPENAI_COMPATIBLE_BASE_URL` ([src/config.ts#L24-L25](https://github.com/hackertron/selfreview/blob/2eef1d589d2b90eff08bdeb06761bead4156061d/src/config.ts#L24-L25)). Model chosen as `MODEL_SMALL` / `MODEL_LARGE` = `openai-compatible:<model>` ([config.ts#L26-L27](https://github.com/hackertron/selfreview/blob/2eef1d589d2b90eff08bdeb06761bead4156061d/src/config.ts#L26-L27); provider wiring [src/llm/models.ts#L59-L62](https://github.com/hackertron/selfreview/blob/2eef1d589d2b90eff08bdeb06761bead4156061d/src/llm/models.ts#L59-L62)). Arbitrary model names are accepted.
- Catch: an `openai-compatible:` model with no price is **skipped**. You must set `MODEL_PRICES` (use 0 for self-hosted) ([models.ts#L108-L113](https://github.com/hackertron/selfreview/blob/2eef1d589d2b90eff08bdeb06761bead4156061d/src/llm/models.ts#L108-L113), [README.md#L67](https://github.com/hackertron/selfreview/blob/2eef1d589d2b90eff08bdeb06761bead4156061d/README.md#L67)).

### 3.4 Inline comments and drafts

- Inline: **yes**, via the Reviews API with `line` / `side: "RIGHT"` / `start_line`, and `event: "COMMENT", // never APPROVE or REQUEST_CHANGES` ([src/pipeline/publish.ts#L45-L58](https://github.com/hackertron/selfreview/blob/2eef1d589d2b90eff08bdeb06761bead4156061d/src/pipeline/publish.ts#L45-L58)). Plus one summary comment edited in place ([README.md#L13](https://github.com/hackertron/selfreview/blob/2eef1d589d2b90eff08bdeb06761bead4156061d/README.md#L13)).
- Draft / pending review: not found (unconfirmed).

### 3.5 Weight and runtime dependencies

**Small service, not a CLI.**

- One Docker image (Bun 1.3.14) runs as three services `api`, `worker`, `cron`, with Postgres as both queue (pg-boss) and DB ([README.md#L44](https://github.com/hackertron/selfreview/blob/2eef1d589d2b90eff08bdeb06761bead4156061d/README.md#L44), [Dockerfile](https://github.com/hackertron/selfreview/blob/2eef1d589d2b90eff08bdeb06761bead4156061d/Dockerfile)). Targets Railway.
- Deps: `@anthropic-ai/sdk`, `@octokit/rest`, `hono`, `openai`, `pg`, `pg-boss`, `yaml`, `zod` ([package.json](https://github.com/hackertron/selfreview/blob/2eef1d589d2b90eff08bdeb06761bead4156061d/package.json)).
- Needs `DATABASE_URL` and a public URL for webhooks ([config.ts#L7](https://github.com/hackertron/selfreview/blob/2eef1d589d2b90eff08bdeb06761bead4156061d/src/config.ts#L7), [#L15-L17](https://github.com/hackertron/selfreview/blob/2eef1d589d2b90eff08bdeb06761bead4156061d/src/config.ts#L15-L17)).

### 3.6 License and maintenance

- License: MIT ([LICENSE](https://github.com/hackertron/selfreview/blob/2eef1d589d2b90eff08bdeb06761bead4156061d/LICENSE); GitHub API `mit`).
- Activity: created 2026-10-08; last commit 2026-10-13; no releases; 0 stars, 0 forks, 0 issues. Package version `0.0.0`. Very new; one contributor seen in the shallow clone. Not a fork.
- The code is small and readable, so it is a useful reference for a build (idempotent posting, incremental review, budget cap).

---

## 4. Build from scratch: GitHub API facts

### 4.1 REST Pull Request Reviews API

Source: [docs.github.com/en/rest/pulls/reviews](https://docs.github.com/en/rest/pulls/reviews) and [docs.github.com/en/rest/pulls/comments](https://docs.github.com/en/rest/pulls/comments).

- **Create a review:** `POST /repos/{owner}/{repo}/pulls/{pull_number}/reviews`. Body fields include `commit_id`, `body`, `event`, `comments[]`.
- **`event`:** "Can be one of: `APPROVE`, `REQUEST_CHANGES`, `COMMENT`". `body` is "Required when using REQUEST_CHANGES or COMMENT".
- **Pending review:** "By leaving this blank, you set the review action state to PENDING, which means you will need to submit the pull request review when you are ready." The pending review is visible only to its author until submitted (general GitHub behavior; not quoted from this page, so treat as unconfirmed here).
- **Submit a pending review:** `POST /repos/{owner}/{repo}/pulls/{pull_number}/reviews/{review_id}/events` with required `event` (`APPROVE`, `REQUEST_CHANGES`, `COMMENT`). A blank `event` returns 422 and the review stays PENDING.
- **Inline `comments[]` fields:** `path` (required), `body` (required), `position`, `line`, `side`, `start_line`, `start_side`. The reviews page lists `line`/`side`/`start_line`/`start_side` without descriptions. The review-comments page defines them:
  - `line`: "The line of the blob in the pull request diff that the comment applies to."
  - `side`: "LEFT or RIGHT".
  - `start_line` / `start_side`: first line and side of a multi-line comment.
  - `position`: "This parameter is closing down. Use line instead."
  - `subject_type`: `line` or `file` (on the single-comment endpoint).
- **Limits:** "Creating content too quickly using this endpoint may result in secondary rate limiting." 422 can mean "the endpoint has been spammed". A maximum number of comments per review is **not stated** in the docs (unconfirmed).
- Whether a user can APPROVE or REQUEST_CHANGES on their own PR is **not stated** on the page (unconfirmed here).
- Note from Selfreview's code: the per-review comment list endpoint can return `line: null` (only legacy `position`) ([S/src/pipeline/publish.ts#L22](https://github.com/hackertron/selfreview/blob/2eef1d589d2b90eff08bdeb06761bead4156061d/src/pipeline/publish.ts#L22)). This is a third-party observation, not GitHub docs.

### 4.2 Token type for reviewing public repos you do not own

This is the key decision point.

From [Managing your personal access tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens):

- Fine-grained PAT known limitations include: "Using fine-grained personal access token to contribute to public repos where the user is not a member" and "to contribute to repositories where the user is an outside or repository collaborator."
- "**Only personal access tokens (classic) have write access for public repositories that are not owned by you or an organization that you are not a member of.**" (verified in page HTML)
- "Outside collaborators can only use personal access tokens (classic) to access organization repositories".
- A fine-grained token "will only be able to access resources owned by the selected resource owner" and "Tokens always include read-only access to all public repositories on GitHub."
- "These feature gaps are not permanent - GitHub is working to close them."

From [Permissions required for fine-grained PATs](https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens): under "Pull requests", **write** access is listed for all three endpoints: `POST .../pulls/{pull_number}/reviews`, `POST .../reviews/{review_id}/events`, `POST .../pulls/{pull_number}/comments` (table columns: Endpoint | Access | Tokens | Additional Permissions; Additional Permissions = ✗, so no extra permission).

From [Scopes for OAuth apps](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/scopes-for-oauth-apps):

- `public_repo`: "Limits access to public repositories. That includes read/write access to code, commit statuses, repository projects, collaborators, and deployment statuses for public repositories and organizations."
- `repo`: "Grants full access to public and private repositories ..." (also webhooks and org resources).

**Result:**

- A fine-grained PAT cannot post reviews on a public repo the user does not own and is not a member of.
- A classic PAT is needed. `public_repo` is the narrowest classic scope for public repos. `repo` is needed for private repos and grants much more.
- Pull-request review is not named in the `public_repo` text. That `public_repo` is sufficient to create a review on a third-party public PR is not stated verbatim (unconfirmed from docs; test it).
- A classic PAT with `public_repo` can write to **every** public repo the user can write to. It cannot be limited per repo.

### 4.3 `workflow_dispatch` with inputs and a PAT secret

Sources: [Events that trigger workflows: workflow_dispatch](https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#workflow_dispatch), [Create a workflow dispatch event](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event), [Using secrets in GitHub Actions](https://docs.github.com/en/actions/security-for-github-actions/security-guides/using-secrets-in-github-actions), [Automatic token authentication](https://docs.github.com/en/actions/security-for-github-actions/security-guides/automatic-token-authentication).

- "This event will only trigger a workflow run if the workflow file exists on the default branch."
- Inputs are defined in the workflow file (types shown include `choice`, `boolean`, `environment`; `string` is also used). Max 25 top-level input properties; max 65,535 characters of input payload.
- CLI: `gh workflow run run-tests.yml -f logLevel=warning -f tags=false -f environment=staging`.
- REST: `POST /repos/{owner}/{repo}/actions/workflows/{workflow_id}/dispatches`, `ref` required, `inputs` optional (max 25 properties). Classic PAT needs `repo` scope; the page metadata lists fine-grained "Actions" repository permission: write. At fetch time the page listed status 200 "Response including the workflow run ID and URLs" (verified in page HTML).
- Secrets: set with `gh secret set`; read with `${{ secrets.NAME }}`. Secrets other than `GITHUB_TOKEN` are not passed to workflows triggered from forks.
- To get permissions that `GITHUB_TOKEN` lacks, docs say: "create a personal access token, store it as a secret in your repository."
- Pattern: the workflow lives in the **user's own repo**, takes `pr_url` as input, and uses a classic PAT secret to post to the third-party PR. The target repo needs nothing installed. The identity of `GITHUB_TOKEN` actions (`github-actions[bot]`) was not confirmed from the fetched page.

---

## 5. Comparison

| Criterion | kodus-ai | pr-agent | selfreview |
|---|---|---|---|
| Post as user's own account | Yes, FGPAT token mode (UI) | Yes, `github.user_token` (default `deployment_type="user"`) | No, GitHub App bot only |
| On demand, any PR URL, no install on target | No (webhooks + integration owner) | Yes, `pr-agent --pr_url <url> review` | No (App webhooks only) |
| OpenAI-compatible base URL + key | Yes: `API_OPENAI_FORCE_BASE_URL`, `API_OPEN_AI_API_KEY`, `API_LLM_PROVIDER_MODEL`, or UI BYOK | Yes: `OPENAI__API_BASE`, `OPENAI__KEY`, `config.model="openai/<id>"`, `custom_model_max_tokens` | Yes: `OPENAI_COMPATIBLE_BASE_URL`, `OPENAI_COMPATIBLE_API_KEY`, `MODEL_*="openai-compatible:<id>"`, plus `MODEL_PRICES` |
| Inline comments via Reviews API | Yes (single review comments + COMMENT review) | Opt-in (`inline_key_issues`), batched `create_review` COMMENT; default is one issue comment | Yes, batched `createReview` COMMENT |
| Draft before posting | Not found | Local only: `publish_output=false`, `--json-output` | Not found |
| Leave GitHub pending review | Not found | No (pending used only for validation, then deleted) | Not found |
| Weight | Platform: 5 app containers, Postgres, MongoDB, RabbitMQ, 8 GB RAM | One CLI / pip / Docker one-shot; large Python dep tree | 3 services from 1 image + Postgres |
| License | AGPL-3.0 + proprietary EE parts (SPDX unconfirmed) | MIT | MIT |
| Activity | Very active; 134 open issues | Very active; weekly-ish releases; 11 open issues | 6 days old, 0 issues, no releases |

Trade-offs to weigh:

- **pr-agent** is the only tool that meets the identity and on-demand needs today. Gaps: inline comments are off by default; no GitHub pending-review mode; labels are added by default; large dependency tree; frequent config changes in a fast-moving project.
- **kodus-ai** is a full platform designed around repos you control. It does not fit third-party repos.
- **selfreview** is a GitHub App bot. It does not fit the identity need. Its code is a small, clear reference for a build.
- **Build** needs: diff fetch, prompt, OpenAI-compatible call, line mapping, and one `POST .../reviews` call (optionally pending, then a human submits in the GitHub UI or via `.../events`). All three tools must deal with the same classic-PAT constraint in section 4.2.

## 6. Open questions

1. Does a classic PAT with only `public_repo` succeed on `POST .../pulls/{n}/reviews` for a public repo where the user is not a collaborator? The docs imply yes but do not say it verbatim. Test once.
2. Max inline comments per review, and the exact secondary rate limits for review creation: not in the docs (unconfirmed).
3. Can a user APPROVE or REQUEST_CHANGES on their own PR? The reviews page is silent.
4. Can only one pending review exist per user per PR? Not confirmed from the fetched docs. It matters if a pending draft is left for the user.
5. pr-agent: does label publishing on a foreign repo return 403, and does the review still post? The code logs and continues; not tested. Should `enable_review_labels_*` be set to false for this use?
6. pr-agent: 139 issues opened in 30 days against 11 open. The number is high; the reason was not checked.
7. pr-agent: is `inline_key_issues=true` stable on GitHub in user mode on third-party repos? Not tested.
8. kodus-ai: does Community self-hosting need a license key? `KODUS_LICENSE_KEY` is documented as EE-only, but the README asks self-hosters to "Request a trial license".
9. kodus-ai: how is RabbitMQ provisioned, given that it is required but absent from `docker-compose.prod.yml`?
10. kodus-ai: exact repo permissions checked by `checkRepositoryPermissions` in token mode: not traced (unconfirmed).
11. kodus-ai: exact SPDX id (`AGPL-3.0-only` or `AGPL-3.0-or-later`): unconfirmed.
12. Workflow route: confirm the identity of `GITHUB_TOKEN` actions and that a PAT secret in the user's own repo is the only setup needed to post on third-party PRs.
