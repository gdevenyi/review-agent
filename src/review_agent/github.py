"""GitHubClient: the GitHub REST calls, over httpx. No SDK and no `gh` CLI."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from review_agent.errors import ReviewAgentError

log = logging.getLogger(__name__)

API_URL = "https://api.github.com"
JSON_MEDIA_TYPE = "application/vnd.github+json"
DIFF_MEDIA_TYPE = "application/vnd.github.diff"
RAW_MEDIA_TYPE = "application/vnd.github.raw+json"
API_VERSION = "2022-11-28"

EXPIRATION_HEADER = "github-authentication-token-expiration"
_REPO_PATH = re.compile(r"^/repos/(?P<owner>[^/]+)/(?P<repo>[^/]+)(?:/|$)")

_PR_URL = re.compile(
    r"^https?://github\.com/(?P<owner>[A-Za-z0-9._-]+)/(?P<repo>[A-Za-z0-9._-]+)"
    r"/pull/(?P<number>\d+)(?:[/?#].*)?$"
)


class GitHubError(ReviewAgentError):
    """A GitHub API call failed."""


class DiffTooLarge(GitHubError):
    """GitHub refuses to give the diff of the Target PR."""


class BadCredentials(GitHubError):
    """HTTP 401: the token is not valid, expired or revoked."""


class SSORequired(GitHubError):
    """HTTP 403 with `X-GitHub-SSO`: the org blocks the token until it is
    authorized for SAML SSO."""


class RepoNotVisible(GitHubError):
    """HTTP 404 on a repo path: the token cannot see the repo."""


@dataclass(frozen=True)
class PullRef:
    owner: str
    repo: str
    number: int

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"

    def __str__(self) -> str:
        return f"{self.owner}/{self.repo}#{self.number}"


def parse_pr_url(url: str) -> PullRef:
    m = _PR_URL.match(url.strip())
    if m is None:
        raise ReviewAgentError(
            f"{url!r} is not a GitHub pull request URL. "
            "Use https://github.com/<owner>/<repo>/pull/<number>."
        )
    return PullRef(m["owner"], m["repo"], int(m["number"]))


class GitHubClient:
    """One token, one httpx client. Use as a context manager.

    `token_var` is the name of the environment variable that holds the token.
    Error messages name it; they never contain the token.
    """

    def __init__(
        self,
        token: str,
        *,
        token_var: str = "the token variable",
        base_url: str = API_URL,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 60.0,
    ):
        self.token_var = token_var
        self.token_expiration: datetime | None = None  # set by get_user()
        self._http = httpx.Client(
            base_url=base_url,
            transport=transport,
            timeout=timeout,
            follow_redirects=True,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": JSON_MEDIA_TYPE,
                "X-GitHub-Api-Version": API_VERSION,
                "User-Agent": "review-agent",
            },
        )

    def __enter__(self) -> GitHubClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def _get(
        self,
        path: str,
        *,
        accept: str | None = None,
        params: dict[str, str] | None = None,
        not_found_ok: bool = False,
    ) -> httpx.Response:
        """GET `path`. 401, 403 SSO and 404 raise errors that name the token
        variable; with `not_found_ok` the caller handles 404 itself."""
        headers = {"Accept": accept} if accept else None
        try:
            resp = self._http.get(path, headers=headers, params=params)
        except httpx.HTTPError as e:
            raise GitHubError(f"GET {path} failed: {e}") from None
        log.info("GET %s -> %s", path, resp.status_code)
        self._check_access(resp, path, not_found_ok)
        return resp

    def _check_access(
        self, resp: httpx.Response, path: str, not_found_ok: bool
    ) -> None:
        """Turn 401, 403 SSO and 404 into errors the Reviewer can act on."""
        var = self.token_var
        if resp.status_code == 401:
            raise BadCredentials(
                f"GitHub does not accept the token in {var} (HTTP 401: "
                f"{_message(resp)}). The token is not valid, has expired or was "
                f"revoked. Make a new token and put it in {var}."
            )
        sso = resp.headers.get("X-GitHub-SSO", "")
        if resp.status_code == 403 and sso:
            url = _sso_url(sso)
            where = f"Open {url} to authorize it" if url else "Authorize it"
            raise SSORequired(
                f"The organization uses SAML single sign-on and blocks the token "
                f"in {var}. {where}, then run the review again."
            )
        m = _REPO_PATH.match(path)
        if resp.status_code == 404 and m and not not_found_ok:
            raise RepoNotVisible(
                f"GitHub returned 404 for {m['owner']}/{m['repo']}. The token in "
                f"{var} cannot see this repo, or the repo or PR does not exist. "
                f"Give the token access to the repo, or set a token for "
                f"{m['owner']} in [auth.tokens]."
            )

    def get_user(self) -> dict:
        """`GET /user`: who the token belongs to. Also reads the token expiry
        (`github-authentication-token-expiration`) into `token_expiration`."""
        resp = self._get("/user")
        if resp.status_code != 200:
            raise GitHubError(_failure("GET /user", resp))
        self.token_expiration = parse_expiration(resp.headers.get(EXPIRATION_HEADER))
        return resp.json()

    def get_pull(self, pr: PullRef) -> dict:
        path = f"/repos/{pr.owner}/{pr.repo}/pulls/{pr.number}"
        resp = self._get(path)
        if resp.status_code != 200:
            raise GitHubError(_failure(f"Reading {pr}", resp))
        return resp.json()

    def get_contents(self, pr: PullRef, path: str, ref: str) -> str | None:
        """The text of `path` at commit `ref` in the PR's repo, or None if the
        file is not there (404). Other failures raise GitHubError."""
        resp = self._get(
            f"/repos/{pr.owner}/{pr.repo}/contents/{path}",
            accept=RAW_MEDIA_TYPE,
            params={"ref": ref},
            not_found_ok=True,
        )
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise GitHubError(_failure(f"Reading {path} at {ref[:12]}", resp))
        return resp.text

    def get_diff(self, pr: PullRef) -> str:
        path = f"/repos/{pr.owner}/{pr.repo}/pulls/{pr.number}"
        resp = self._get(path, accept=DIFF_MEDIA_TYPE)
        if resp.status_code in (406, 422) or (
            resp.status_code != 200 and "too_large" in resp.text
        ):
            raise DiffTooLarge(
                f"GitHub refuses to give the diff of {pr} "
                f"(HTTP {resp.status_code}: {_message(resp)}). The diff is "
                "probably too large. review-agent v1 cannot review this PR."
            )
        if resp.status_code != 200:
            raise GitHubError(_failure(f"Reading the diff of {pr}", resp))
        return resp.text


def _message(resp: httpx.Response) -> str:
    try:
        msg = resp.json().get("message")
    except ValueError:
        msg = None
    return str(msg) if msg else resp.reason_phrase


def _failure(what: str, resp: httpx.Response) -> str:
    return f"{what} failed: HTTP {resp.status_code} ({_message(resp)})."


def _sso_url(header: str) -> str | None:
    """The URL from `X-GitHub-SSO: required; url=<url>`."""
    for part in header.split(";"):
        key, sep, value = part.strip().partition("=")
        if sep and key.strip().lower() == "url" and value.strip():
            return value.strip()
    return None


def parse_expiration(value: str | None) -> datetime | None:
    """Parse the token expiry header, for example `2026-11-01 12:00:00 UTC`.
    Return None if the header is missing (the token does not expire) or has a
    format that is not known."""
    if not value:
        return None
    text = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S %Z", "%Y-%m-%d %H:%M:%S %z"):
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(text.replace(" UTC", "+00:00"))
    except ValueError:
        log.warning("Token expiry header has an unknown format: %r", text)
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
