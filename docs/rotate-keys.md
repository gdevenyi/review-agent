# Rotate your keys

review-agent uses two types of secret:

- **GitHub tokens.** One default token (a classic personal access token with
  the `public_repo` scope). Optional: one fine-grained token for each
  organization in `[auth.tokens]`, with `Pull requests: write`.
- **The engine key.** The key for the model endpoint (for example the Z.AI
  API key).

The tool reads each secret only from an environment variable. The config file
holds only the names of the variables. The default names are
`REVIEW_AGENT_GITHUB_TOKEN` and `REVIEW_AGENT_ENGINE_KEY`.

## When to rotate

- **GitHub tokens:** give each token a 90-day expiry. When 14 days or fewer
  remain, the tool shows a warning at the start of each run. Rotate the token
  then.
- **Engine key:** the Z.AI key does not expire. Rotate it immediately if you
  think that it leaked (for example, it is in a log, a commit or a chat).
- **Any secret:** rotate it immediately if you think that it leaked.

## Rotate a GitHub token

1. On GitHub, open **Settings > Developer settings > Personal access tokens**.
2. Make a new token with the same scopes as the old token:
   - Default token: classic, scope `public_repo`, expiry 90 days.
   - Organization token: fine-grained, resource owner is the organization,
     repository permission `Pull requests: Read and write`, expiry 90 days.
3. If the organization uses SAML single sign-on, authorize the new token for
   the organization (**Configure SSO** next to the token). If you do not do
   this, the tool stops with the authorization URL.
4. Put the new token in the environment variable that the config names (for
   example in your env file, mode 600).
5. If you use the Action, update the repo secret in the private runner repo:

   ```sh
   gh secret set REVIEW_AGENT_GITHUB_TOKEN --repo <you>/review-runner
   ```

   Use the name of the secret that your workflow reads. `gh` asks for the
   value; do not put the value on the command line. For an organization
   token, update its `NAME=value` line in the `EXTRA_TOKENS` secret: write all
   the lines in a file with mode 600, run
   `gh secret set EXTRA_TOKENS --repo <you>/review-runner < <file>`, then
   delete the file.
6. Do a test run: `review <pr-url> --dry-run`. The tool checks that the token
   belongs to your `[auth] login` and that it can read the PR. Nothing is
   posted.
7. Delete the old token on GitHub.

## Rotate the engine key

1. In the Z.AI console, make a new API key.
2. Put the new key in the environment variable that the config names.
3. If you use the Action, update the repo secret in the runner repo with
   `gh secret set <name> --repo <you>/review-runner`.
4. Do a test run with `--dry-run`.
5. Delete the old key in the Z.AI console.

## Do not use these tokens

- **The Actions `GITHUB_TOKEN`.** The tool refuses it, because a Review posted
  with it shows as `github-actions[bot]` and not as you. The tool also refuses
  other GitHub App tokens (they start with `ghs_`).
- **The `gh` CLI token.** The tool never reads it. Its scopes are too broad.
