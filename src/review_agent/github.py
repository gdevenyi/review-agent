"""GitHubClient: the GitHub REST calls, over httpx. No SDK and no `gh` CLI."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import httpx

from review_agent.errors import ReviewAgentError

log = logging.getLogger(__name__)

API_URL = "https://api.github.com"
JSON_MEDIA_TYPE = "application/vnd.github+json"
DIFF_MEDIA_TYPE = "application/vnd.github.diff"
API_VERSION = "2022-11-28"

_PR_URL = re.compile(
    r"^https?://github\.com/(?P<owner>[A-Za-z0-9._-]+)/(?P<repo>[A-Za-z0-9._-]+)"
    r"/pull/(?P<number>\d+)(?:[/?#].*)?$"
)


class GitHubError(ReviewAgentError):
    """A GitHub API call failed."""


class DiffTooLarge(GitHubError):
    """GitHub refuses to give the diff of the Target PR."""


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
    """One token, one httpx client. Use as a context manager."""

    def __init__(
        self,
        token: str,
        *,
        base_url: str = API_URL,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 60.0,
    ):
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

    def _get(self, path: str, *, accept: str | None = None) -> httpx.Response:
        headers = {"Accept": accept} if accept else None
        try:
            resp = self._http.get(path, headers=headers)
        except httpx.HTTPError as e:
            raise GitHubError(f"GET {path} failed: {e}") from None
        log.info("GET %s -> %s", path, resp.status_code)
        return resp

    def get_user(self) -> dict:
        """`GET /user`: who the token belongs to."""
        resp = self._get("/user")
        if resp.status_code != 200:
            raise GitHubError(_failure("GET /user", resp))
        return resp.json()

    def get_pull(self, pr: PullRef) -> dict:
        path = f"/repos/{pr.owner}/{pr.repo}/pulls/{pr.number}"
        resp = self._get(path)
        if resp.status_code != 200:
            raise GitHubError(_failure(f"Reading {pr}", resp))
        return resp.json()

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
