"""Token selection: which GitHub token to use for the owner of the Target PR.

`[auth.tokens]` maps an owner to the name of an environment variable. An owner
that is not in the map uses the default token (`[auth] github_token_var`).

The tool refuses the GitHub Actions `GITHUB_TOKEN`: a Review posted with it
shows as `github-actions[bot]`, not as the Reviewer.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from review_agent.config import AuthSettings, read_secret
from review_agent.errors import ReviewAgentError

log = logging.getLogger(__name__)

# Warn when the token expires in this time or less.
EXPIRY_WARNING = timedelta(days=14)

ACTIONS_TOKEN_VAR = "GITHUB_TOKEN"
# Server-to-server tokens (GitHub App installations, which include the Actions
# GITHUB_TOKEN) start with this prefix. They never act as a person.
APP_TOKEN_PREFIX = "ghs_"


class ActionsTokenRefused(ReviewAgentError):
    """The selected token is the Actions GITHUB_TOKEN or another bot token."""


def select_token(
    auth: AuthSettings, owner: str, env: Mapping[str, str]
) -> tuple[str, str]:
    """Return (variable name, token) for this owner. Make no request."""
    var = auth.token_var_for(owner)
    if var == ACTIONS_TOKEN_VAR:
        raise _refused(var, "The config names GITHUB_TOKEN as the token variable.")
    token = read_secret(env, var, f"GitHub token for {owner}")
    actions_token = env.get(ACTIONS_TOKEN_VAR, "").strip()
    if actions_token and token == actions_token:
        raise _refused(var, f"{var} has the same value as GITHUB_TOKEN.")
    if token.startswith(APP_TOKEN_PREFIX):
        raise _refused(
            var, f"The token in {var} is a GitHub App token (it starts with ghs_)."
        )
    return var, token


def _refused(var: str, why: str) -> ActionsTokenRefused:
    return ActionsTokenRefused(
        f"{why} The tool does not post with the GitHub Actions GITHUB_TOKEN or "
        "another bot token, because the Review must show as the Reviewer. Put "
        f"the Reviewer's personal access token in {var} (in the Action: a repo "
        "secret of the runner repo). Nothing was sent to GitHub."
    )


def expiry_warnings(
    expiration: datetime | None, var: str, now: datetime | None = None
) -> list[str]:
    """A warning when the token expires in 14 days or less; else nothing.
    `expiration` comes from the `github-authentication-token-expiration`
    header; None means the token does not expire."""
    if expiration is None:
        log.info("The token in %s has no expiry date", var)
        return []
    left = expiration - (now or datetime.now(UTC))
    log.info("The token in %s expires %s", var, f"{expiration:%Y-%m-%d %H:%M %Z}")
    if left > EXPIRY_WARNING:
        return []
    days = max(0, round(left / timedelta(days=1)))
    msg = (
        f"The GitHub token in {var} expires in {days} days "
        f"({expiration:%Y-%m-%d}). Make a new token and update {var} (and the "
        "Action secret, if you use the Action). See docs/rotate-keys.md."
    )
    log.warning("%s", msg)
    return [msg]
