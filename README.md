# review-agent

`review <pr-url>` drafts a Review of a GitHub pull request with an AI engine
and leaves it as a **Draft Review**: a pending review under your own name that
only you can see. You check it, edit it and submit it. With `--publish`, the
tool submits the Review at once, always as a COMMENT. The tool never approves
and never requests changes.

The engine is Claude Code on Z.AI `glm-5.3-flash`. It runs in a bubblewrap
sandbox and can only read the clone of the PR (ADR 0001, ADR 0002).

review-agent supports only Linux.

## Install the CLI

You need:

- Linux, with `bwrap` (bubblewrap) on PATH. For example:
  `sudo apt-get install bubblewrap`.
- `claude` (Claude Code) on PATH.
- `uv`.

1. Install the tool:

   ```sh
   uv tool install git+https://github.com/gdevenyi/review-agent
   ```

2. Make the config file `~/.config/review-agent/config.toml`:

   ```toml
   [auth]
   login = "<your GitHub login>"
   # Optional: other names for the secret variables.
   # github_token_var = "GH_PR_AGENT"
   # engine_key_var = "ZAI_API_KEY"
   # Optional: one token for each organization.
   # [auth.tokens]
   # SomeOrg = "GH_PR_AGENT_SOMEORG"

   [engine]
   base_url = "https://api.z.ai/api/anthropic"
   model = "glm-5.3-flash"

   [review]
   finding_limit = 10
   ```

   Optional: write your priorities and tone in
   `~/.config/review-agent/instructions.md`, and notes for one repo in
   `~/.config/review-agent/repos/<owner>/<repo>.md`.

3. Put your secrets in environment variables. The default names are
   `REVIEW_AGENT_GITHUB_TOKEN` (a classic personal access token with the
   `public_repo` scope) and `REVIEW_AGENT_ENGINE_KEY` (the Z.AI API key). Keep
   them in a file with mode 600 and load it in your shell. The tool does not
   use the `gh` CLI token.

4. Run a Review:

   ```sh
   review https://github.com/<owner>/<repo>/pull/<number>            # Draft Review
   review https://github.com/<owner>/<repo>/pull/<number> --dry-run  # files only
   review https://github.com/<owner>/<repo>/pull/<number> --publish  # COMMENT
   ```

To rotate your keys, see [docs/rotate-keys.md](docs/rotate-keys.md).

## Use the Action

The Action runs the same code from a **private** runner repo that you own.
Use a private repo, because the run logs of a public repo are public. You
start a Review from the GitHub UI (Actions tab, "Run workflow") or with
`gh workflow run`.

1. Make a private repo, for example `<you>/review-runner`:

   ```sh
   gh repo create <you>/review-runner --private --add-readme
   ```

2. Add your config file to the runner repo as `review-agent/config.toml`.
   Use [docs/examples/review-runner/review-agent/config.toml](docs/examples/review-runner/review-agent/config.toml)
   as a start. Keep the default variable names: the workflow puts the secrets
   in `REVIEW_AGENT_GITHUB_TOKEN` and `REVIEW_AGENT_ENGINE_KEY`. Optional: add
   `review-agent/instructions.md` and `review-agent/repos/<owner>/<repo>.md`.

3. Add two repo secrets to the runner repo. `gh` asks for each value; do not
   put a value on the command line:

   ```sh
   gh secret set GH_PR_AGENT --repo <you>/review-runner   # your GitHub token
   gh secret set ZAI_API_KEY --repo <you>/review-runner   # your engine key
   ```

   Optional: per-organization tokens. In the config, map each owner to a
   variable name in `[auth.tokens]` (for example
   `SomeOrg = "GH_PR_AGENT_SOMEORG"`). Then put all these tokens in one more
   secret, one `NAME=value` line for each token. Write the lines in a file
   with mode 600, give the file to `gh`, then delete the file:

   ```sh
   # extra-tokens.txt holds lines such as: GH_PR_AGENT_SOMEORG=<token>
   gh secret set EXTRA_TOKENS --repo <you>/review-runner < extra-tokens.txt
   rm extra-tokens.txt
   ```

   The workflow masks each value in the log and makes each `NAME` an
   environment variable of the review step. It refuses reserved names (for
   example `GITHUB_*`, `PATH` and `REVIEW_AGENT_*`).

4. Copy
   [docs/examples/review-runner/.github/workflows/review.yml](docs/examples/review-runner/.github/workflows/review.yml)
   to `.github/workflows/review.yml` in the runner repo. It calls the reusable
   workflow `gdevenyi/review-agent/.github/workflows/review.yml`. Use the same
   review-agent ref in `uses:` and in the `ref` input.

5. Start a Review:

   ```sh
   gh workflow run review.yml --repo <you>/review-runner \
     -f pr_url=https://github.com/<owner>/<repo>/pull/<number>
   ```

   Add `-f publish=true` to publish the Review at once as a COMMENT.

### Start a Review from an issue

You can also start a Review when you open an issue in the runner repo:

1. Copy these two files to the same paths in the runner repo:
   - [docs/examples/review-runner/.github/ISSUE_TEMPLATE/review.yml](docs/examples/review-runner/.github/ISSUE_TEMPLATE/review.yml):
     the "Review a PR" issue form.
   - [docs/examples/review-runner/.github/workflows/review-from-issue.yml](docs/examples/review-runner/.github/workflows/review-from-issue.yml):
     the workflow that reads the form.

2. Make the label that the form adds:

   ```sh
   gh label create review-request --repo <you>/review-runner
   ```

3. Open a new issue in the runner repo, select "Review a PR", paste the PR
   URL and submit. From the terminal, give the same body that the form makes:

   ```sh
   gh issue create --repo <you>/review-runner --label review-request \
     --title "Review: <owner>/<repo>#<number>" \
     --body "### PR URL

   https://github.com/<owner>/<repo>/pull/<number>"
   ```

   To publish at once, add these lines to the body:
   `### Publish` and `- [X] Publish the Review at once (COMMENT)`.

The workflow starts only for issues that the repo owner opens with the
`review-request` label. After a successful run, it posts a copy of the Review
on the issue: the summary, and each inline comment with its file and line.
Then it comments with the result and a link to the run, and it closes the
issue. If the Review fails, the issue stays open and gets no copy.

- The copy is read-only. To change the Review, edit and submit it on the PR.
- The copy holds Review content, so the workflow posts it only when the
  runner repo is private. The job log never shows it.

The reusable workflow:

- installs bubblewrap, Claude Code at a pinned version (input
  `claude_version`) and review-agent at the `ref` input.
- allows unprivileged user namespaces on the runner, so that bubblewrap can
  make a sandbox. GitHub's `ubuntu-24.04` runners block them by default. If
  the sandbox still does not work, the engine runs without it and the log
  shows a warning.
- writes the result, the PR URL and the warnings to the job summary. It never
  writes Review content to the log or to the job summary, and it uploads no
  artifacts.
- refuses the Actions `GITHUB_TOKEN`. The Review must show as you, not as
  `github-actions[bot]`.
- stops after 60 minutes. The engine has 45 minutes for one run, retry
  included.
- shows only "The engine failed" when the engine fails. The detail can
  quote model output, so it goes only to the run log file.

Limit of the Action in v1: the run log file stays on the runner and is lost
when the job ends.
