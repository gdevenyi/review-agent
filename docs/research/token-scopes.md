# Token scopes for Draft Reviews on third-party and org PRs

Research for issue #2. Parent map: issue #1.

All pages were fetched on 2026-10-19. Quotes are verbatim from the cited page.
"Unconfirmed" means no primary source states the point.

## Question

Which GitHub token types and scopes let the Reviewer create a Draft Review
(a pending review with inline comments) and later submit it?

1. On public PRs in repos that other people own.
2. On private repos in orgs where the Reviewer is a member, with org
   fine-grained PAT policies and SAML SSO.

Is classic `public_repo` enough for case 1? What is the narrowest working setup?

## Short answer

| Case | Token type | Narrowest setup | Confidence |
| --- | --- | --- | --- |
| 1a. Public repo of another user, or of an org you are not a member of | Classic PAT only | `public_repo` (candidate). `repo` is the documented check. | `public_repo` is unconfirmed. Test once. |
| 1b. Public repo of an org you are a member of | Fine-grained PAT or classic PAT | Fine-grained: resource owner = that org, the one repo, `Pull requests: write` | Confirmed by docs, subject to org policy |
| 1c. Repo where you are an outside or repository collaborator | Classic PAT only | `public_repo` for public repos (unconfirmed), `repo` for private repos | Confirmed (classic only) |
| 2. Private repo in an org you are a member of | Fine-grained PAT (preferred) or classic PAT | Fine-grained: resource owner = org, selected repos, `Pull requests: write`. Classic: `repo`, plus SSO authorization if the org uses SAML SSO | Confirmed by docs |

## 1. API endpoints and the fine-grained permission they need

The Draft Review flow uses these endpoints. Each endpoint page has a
"Fine-grained access tokens" box. Source:
[REST API endpoints for pull request reviews](https://docs.github.com/en/rest/pulls/reviews)
and [REST API endpoints for pull requests](https://docs.github.com/en/rest/pulls/pulls).

| Step | Endpoint | Fine-grained permission |
| --- | --- | --- |
| Read PR and diff | `GET /repos/{owner}/{repo}/pulls/{pull_number}` | "at least one of": `Pull requests` (read) or `Contents` (read) |
| List changed files | `GET /repos/{owner}/{repo}/pulls/{pull_number}/files` | `Pull requests` (read) |
| Create pending review with inline comments | `POST /repos/{owner}/{repo}/pulls/{pull_number}/reviews` | `Pull requests` (write) |
| Update review body | `PUT .../reviews/{review_id}` | `Pull requests` (write) |
| Delete pending review | `DELETE .../reviews/{review_id}` | `Pull requests` (write) |
| Submit review | `POST .../reviews/{review_id}/events` | `Pull requests` (write) |

- The same rows appear in the table under "Repository permissions for
  'Pull requests'" on
  [Permissions required for fine-grained personal access tokens](https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens).
  The "Additional Permissions" column is ✗ for the review endpoints.
- All review endpoints are listed on
  [Endpoints available for fine-grained personal access tokens](https://docs.github.com/en/rest/authentication/endpoints-available-for-fine-grained-personal-access-tokens).
  So a fine-grained PAT can call them, if it has access to the repo.
- The read endpoints say: "This endpoint can be used without authentication or
  the aforementioned permissions if only public resources are requested." The
  create and submit endpoints do not say this. They need write access.
- Pending state: "To create a pending review for a pull request, leave the
  event parameter blank." And: "By leaving this blank, you set the review action
  state to PENDING, which means you will need to submit the pull request review
  when you are ready." ([reviews](https://docs.github.com/en/rest/pulls/reviews#create-a-review-for-a-pull-request))
- Inline comments go in the `comments` array of the same create call
  ("the draft review comment"). No separate permission is needed.

**Consequence:** `Contents: read` is not needed for the Draft Review flow.
`Pull requests: write` covers every step above. Add `Contents: read` only if
the Reviewer must read full file bodies through the contents endpoints.

Fine-grained PATs also get the `Metadata: read` repository permission. The
permission table on
[Managing your personal access tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)
lists `metadata` (read). Whether the UI adds it automatically is not stated on
the fetched pages: unconfirmed.

## 2. Case 1: public PRs in repos owned by others

### 2.1 Fine-grained PATs cannot do it when you are not a member

From [Managing your personal access tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens),
"Fine-grained personal access tokens limitations":

- "Using fine-grained personal access token to contribute to public repos where
  the user is not a member."
- "Using fine-grained personal access token to contribute to repositories where
  the user is an outside or repository collaborator."
- "Using fine-grained personal access token to access multiple organizations at
  once."

Under "Personal access tokens (classic)" on the same page:

- "Only personal access tokens (classic) have write access for public
  repositories that are not owned by you or an organization that you are not a
  member of."
- "Outside collaborators can only use personal access tokens (classic) to access
  organization repositories that they are a collaborator on."

Other facts from the same page:

- "The token will only be able to access resources owned by the selected
  resource owner."
- "Tokens always include read-only access to all public repositories on GitHub."
  So a fine-grained PAT can read a third-party PR, but it cannot post a review.

The page says: "These feature gaps are not permanent - GitHub is working to
close them." The
[Fine-grained PATs GA changelog (2025-03-18)](https://github.blog/changelog/2025-03-18-fine-grained-pats-are-now-generally-available/)
still lists "Contributing to repositories where you're an outside collaborator
or an unaffiliated open source contributor" as a case where fine-grained PATs
"are not a suitable solution at this time". I found no later changelog entry
that closes this gap. The docs page fetched on 2026-10-19 still lists it.

### 2.2 Classic PAT: is `public_repo` enough?

From [Scopes for OAuth apps](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/scopes-for-oauth-apps):

- `repo`: "Grants full access to public and private repositories including read
  and write access to code, commit statuses, repository invitations,
  collaborators, deployment statuses, and repository webhooks."
- `public_repo` (shown indented under `repo`): "Limits access to public
  repositories. That includes read/write access to code, commit statuses,
  repository projects, collaborators, and deployment statuses for public
  repositories and organizations."
- The `admin:repo_hook` row says: "The `repo` and `public_repo` scopes grant
  full access to repositories".
- "Normalized scopes" says scopes can be "implicitly included by another
  requested scope". The only example given is `user:email` inside `user`. The
  page does not state the `repo` / `public_repo` relation in words. The table
  shows it only by indentation.
- "`X-Accepted-OAuth-Scopes` lists the scopes that the action checks for."

**Header probe (2026-10-19).** I sent POST requests to a pull request number
that does not exist (`cli/cli` PR 999999999). The API returned 404, so nothing
was created. The token was the `gh` OAuth token with `repo` scope. The response
header was:

| Endpoint | `X-Accepted-OAuth-Scopes` |
| --- | --- |
| `POST /repos/cli/cli/pulls/999999999/reviews` | `repo` |
| `POST /repos/cli/cli/pulls/999999999/reviews/1/events` | `repo` |
| `POST /repos/cli/cli/issues/999999999/comments` (for comparison) | `repo` |

The header names only the parent scope `repo`. It does not name `public_repo`.
The issue-comment endpoint shows the same value. So the header alone does not
show whether `public_repo` passes the check on a public repo.

**Result:** No primary source states that `public_repo` alone can create and
submit a review on a public repo you do not own. This is **unconfirmed**.
`public_repo` is the narrowest candidate. `repo` is the scope the API reports.

**Test to close it (for a human to run):**

1. Create a classic PAT with only `public_repo`. Give it a short expiry.
2. On a public repo you own, open a test PR from a second account, or use a
   repo where the test account is not a collaborator.
3. Call `POST .../pulls/{n}/reviews` with no `event` and one inline comment.
   Expect 200 and `"state": "PENDING"`.
4. Call `POST .../reviews/{id}/events` with `event=COMMENT`. Expect 200.
5. If either call fails with 403 or 404, use `repo`.
6. Delete the token.

Do not run this test on another person's PR.

### 2.3 Narrowest setup for case 1

- Repo owned by another user, or an org you are not a member of: classic PAT.
  Try `public_repo` first. Fall back to `repo` if the test in 2.2 fails.
- You are an outside collaborator or repository collaborator: classic PAT
  (fine-grained is not supported, see 2.1).
- Public repo of an org you are a member of: a fine-grained PAT with that org
  as resource owner, the one repo, and `Pull requests: write` is possible. The
  org policies in section 3.2 apply.
- Risk of classic tokens: "Your personal access token (classic) can access
  every repository that you can access."
  ([Managing your personal access tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens))
  You cannot limit a classic token to one repo. A `public_repo` token can write
  to every public repo where your account can write.

## 3. Case 2: private repos in an org where you are a member

### 3.1 Fine-grained PAT (preferred)

Setup:

- Resource owner: the org. "Organizations that you are a member of will not
  appear if the organization has blocked the use of fine-grained personal access
  tokens."
  ([Managing your personal access tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens))
- Repository access: only the repos to review.
- Repository permission: `Pull requests: write`. See section 1.
- One token per org. A fine-grained PAT cannot "access multiple organizations
  at once" (same page).

### 3.2 Org policies that affect fine-grained PATs

From [Setting a personal access token policy for your organization](https://docs.github.com/en/organizations/managing-programmatic-access-to-your-organization/setting-a-personal-access-token-policy-for-your-organization):

- Approval: "Require administrator approval: An organization owner must approve
  each fine-grained personal access token that can access the organization.
  Fine-grained personal access tokens created by organization owners will not
  need approval. This is the default value."
- "Fine-grained personal access tokens will still be able to read public
  resources within the organization without approval."
- "Only fine-grained personal access tokens, not personal access tokens
  (classic), are subject to approval."
- Restriction: "Restrict access via personal access tokens: Personal access
  tokens (classic) or fine-grained personal access tokens cannot access
  resources owned by the organization." The owner sets this per token type, on
  the "Fine-grained tokens" tab or the "Tokens (classic)" tab.
- "Regardless of the chosen policy, Personal access tokens will have access to
  public resources within the organization."
- Lifetime: "For fine-grained personal access tokens, the default the maximum
  lifetime policy for organizations is set to expire within 366 days. Personal
  access tokens (classic) do not have an expiration requirement." Tokens that do
  not comply "will be blocked from accessing your organization".

From [Managing your personal access tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens):

- "If you selected an organization as the resource owner and the organization
  requires approval for fine-grained personal access tokens, then your token
  will be marked as `pending` until it is reviewed by an organization
  administrator. Your token will only be able to read public resources until it
  is approved. If you are an owner of the organization, your request is
  automatically approved."
- You can enter a justification for the request when you create the token.

### 3.3 SAML SSO

From [Authenticating to the REST API](https://docs.github.com/en/rest/authentication/authenticating-to-the-rest-api#personal-access-tokens-and-saml-sso):

- "If you use a personal access token (classic) to access an organization that
  enforces SAML single sign-on (SSO) for authentication, you will need to
  authorize your token after creation. Fine-grained personal access tokens are
  authorized during token creation, before access to the organization is
  granted."
- "If you do not authorize your personal access token (classic) for SAML SSO
  before you try to use it to access a single organization that enforces SAML
  SSO, you may receive a `404 Not Found` or a `403 Forbidden` error. If you
  receive a `403 Forbidden` error, the `X-GitHub-SSO` header will include a URL
  that you can follow to authorize your token. The URL expires after one hour."

From [Authorizing a personal access token for use with single sign-on](https://docs.github.com/en/enterprise-cloud@latest/authentication/authenticating-with-single-sign-on/authorizing-a-personal-access-token-for-use-with-single-sign-on):

- Classic tokens: open the token list and click **Configure SSO**, then
  **Authorize** next to the org.
- "If you have a linked identity for an organization, you can only use
  authorized personal access tokens and SSH keys with that organization, even if
  SSO is not enforced."
- "Before you can authorize a personal access token or SSH key, you must have a
  linked external identity."
- The authorization ends if an owner revokes it, you leave the org, "the scopes
  in a personal access token are edited, or the token is regenerated", or the
  token expires.

How a fine-grained PAT gets its SSO authorization "during token creation" is not
described step by step on the fetched pages. I assume that you need an active
SSO session for the org when you create the token: unconfirmed.

### 3.4 Classic PAT alternative

- Scope: `repo`. `public_repo` "Limits access to public repositories", so it
  cannot reach private repos
  ([Scopes for OAuth apps](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/scopes-for-oauth-apps)).
- `repo` also "grants access to manage organization-owned resources including
  projects, invitations, team memberships and webhooks." (same page). It is much broader than
  the fine-grained setup.
- If the org uses SAML SSO: authorize the token for the org (section 3.3).
- If the org restricts classic PATs: "your request will fail with a 403
  response. Instead, you must use a GitHub App, OAuth app, or fine-grained
  personal access token."
  ([Managing your personal access tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens))
- No org approval step for classic PATs (section 3.2).

### 3.5 Narrowest setup for case 2

1. Fine-grained PAT. Resource owner = the org. Only the selected repos.
   `Pull requests: write`. Expiry within the org limit (default max 366 days).
2. Wait for org approval if the org requires it (the default). Until then the
   token can only read public resources.
3. If the org blocks fine-grained PATs, use a classic PAT with `repo`, and
   authorize it for SSO if the org uses SAML SSO.
4. If the org blocks both token types, a PAT cannot work. The docs point to a
   GitHub App or OAuth app instead.

## 4. Implications for the Reviewer

- The Reviewer probably needs two token kinds: a classic PAT for third-party
  public repos, and fine-grained PATs (one per org) for org repos. Fine-grained
  PATs cannot span several orgs.
- Pick the token by repo owner. Owner is an org with a configured fine-grained
  PAT: use that token. Otherwise: use the classic PAT.
- A 404 on a private org repo can mean a missing SSO authorization, not a
  missing repo ([Authenticating to the REST API](https://docs.github.com/en/rest/authentication/authenticating-to-the-rest-api#personal-access-tokens-and-saml-sso)).
  Check the `X-GitHub-SSO` header on 403 responses.

## 5. Open questions

1. Does a classic PAT with only `public_repo` succeed on
   `POST .../pulls/{n}/reviews` and `POST .../reviews/{id}/events` on a public
   repo you do not own? Docs do not say. The API header reports `repo`.
   Run the test in section 2.2.
2. Is `Metadata: read` added automatically to a fine-grained PAT? Not stated on
   the fetched pages.
3. What exact steps give a fine-grained PAT its SSO authorization at creation?
   The docs say only that it happens "during token creation".
4. Who can see a pending review before submit? Not researched here.

## Sources

- https://docs.github.com/en/rest/pulls/reviews
- https://docs.github.com/en/rest/pulls/pulls
- https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens
- https://docs.github.com/en/rest/authentication/endpoints-available-for-fine-grained-personal-access-tokens
- https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens
- https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/scopes-for-oauth-apps
- https://docs.github.com/en/organizations/managing-programmatic-access-to-your-organization/setting-a-personal-access-token-policy-for-your-organization
- https://docs.github.com/en/rest/authentication/authenticating-to-the-rest-api
- https://docs.github.com/en/enterprise-cloud@latest/authentication/authenticating-with-single-sign-on/authorizing-a-personal-access-token-for-use-with-single-sign-on
- https://github.blog/changelog/2025-03-18-fine-grained-pats-are-now-generally-available/
- API header probe, 2026-10-19 (section 2.2)
