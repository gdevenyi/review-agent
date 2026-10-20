"""run_review(pr_url, options): the one entry point for the CLI and the Action.

The steps, in order. A failure at any step stops the run; nothing is written
or posted, and the result carries the error and the run log path.

1. Load the config. Read the GitHub token for the PR owner (refuse the Actions
   GITHUB_TOKEN) and the engine key from the env.
2. Preflight: `GET /user` must return the `[auth] login`; warn when the token
   expires in 14 days or less. 401, 403 SSO and 404 stop the run. Stop if
   the Reviewer already has a pending review on the PR (a dry run posts
   nothing, so it skips this check).
3. Read the PR metadata, the diff and the Repo Guidance (base commit).
4. Clone the PR head (Workspace).
5. Build the prompt; run the engine (one retry on invalid Review JSON).
6. Map the Review (ReviewMapper), then filter it (output_filter; a secret
   pattern stops the run).
7. Publish: post one pending review (a Draft Review), or with `publish` a
   COMMENT review. A dry run writes files and posts nothing.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

import httpx

from review_agent.config import (
    Config,
    EngineSettings,
    load_config,
    read_secret,
)
from review_agent.engine import (
    DEFAULT_TIMEOUT,
    ClaudeCodeEngine,
    Engine,
    EngineError,
    SandboxMode,
)
from review_agent.errors import ReviewAgentError
from review_agent.github import API_URL, GitHubClient, PullRef, parse_pr_url
from review_agent.guidance import fetch_repo_guidance, load_instructions
from review_agent.mapper import (
    InvalidReviewJSON,
    MappedReview,
    ReviewMapper,
    parse_review,
)
from review_agent.output_filter import filter_review
from review_agent.prompt import PromptBuilder
from review_agent.publisher import Publisher
from review_agent.tokens import expiry_warnings, select_token
from review_agent.workspace import Workspace

log = logging.getLogger("review_agent")

# Engine time for one run, all attempts together (story 12).
ENGINE_BUDGET = DEFAULT_TIMEOUT
# Do not start a retry with less time than this.
MIN_RETRY = 2 * 60

EngineFactory = Callable[[EngineSettings, str], Engine]


class LoginMismatch(ReviewAgentError):
    """The token does not belong to the configured Reviewer."""


def default_engine_factory(sandbox: SandboxMode) -> EngineFactory:
    def make(settings: EngineSettings, api_key: str) -> Engine:
        return ClaudeCodeEngine(
            api_key=api_key,
            base_url=settings.base_url,
            model=settings.model,
            sandbox=sandbox,
        )

    return make


class RunMode(Enum):
    """What a run does with the Review."""

    DRAFT = "draft"  # post a Draft Review (the default)
    PUBLISH = "publish"  # post a Published Review (COMMENT)
    DRY_RUN = "dry-run"  # write files; post nothing


@dataclass
class Options:
    """How to run one Review. Every field has a default for the CLI."""

    config_path: Path | str | None = None
    mode: RunMode = RunMode.DRAFT
    out_dir: Path | None = None  # dry-run files; default: the current dir
    log_dir: Path | None = None  # default: $XDG_STATE_HOME/review-agent/runs
    tmp_root: Path | None = None  # parent dir of the clone; default: tempfile's
    env: Mapping[str, str] | None = None  # default: os.environ
    sandbox: SandboxMode = "require"
    # Test seams: the engine and the GitHub HTTP transport.
    engine_factory: EngineFactory | None = None
    http_transport: httpx.BaseTransport | None = None
    api_url: str = API_URL
    clock: Callable[[], float] = time.monotonic


@dataclass
class RunResult:
    ok: bool
    pr_url: str
    log_path: Path | None
    error: str | None = None
    files: list[Path] = field(default_factory=list)
    review: MappedReview | None = None
    # Warnings for the Reviewer, for example a token that expires soon.
    warnings: list[str] = field(default_factory=list)
    mode: RunMode = RunMode.DRAFT
    # The engine failed. Its error text can quote model output, so the Action
    # shows a generic message (actions.py).
    engine_failed: bool = False

    @property
    def posted(self) -> bool:
        """A Review is on GitHub (Draft or Published)."""
        return self.ok and self.mode is not RunMode.DRY_RUN

    @property
    def published(self) -> bool:
        """The Review was submitted as COMMENT."""
        return self.ok and self.mode is RunMode.PUBLISH

    @property
    def status(self) -> str:
        """One line for the Reviewer: what the run did. No Review content."""
        if not self.ok:
            return "The run failed. Nothing was posted."
        if self.published:
            return f"A Published Review (COMMENT) is on {self.pr_url}."
        if self.posted:
            return (
                f"A Draft Review is waiting for you on {self.pr_url}. Open the "
                "PR, check and edit the Review, then submit it."
            )
        return f"Dry run for {self.pr_url}: nothing was posted."


@dataclass
class _Outcome:
    review: MappedReview
    files: list[Path] = field(default_factory=list)


def run_review(pr_url: str, options: Options | None = None) -> RunResult:
    options = options or Options()
    env = os.environ if options.env is None else options.env
    log_path, handler = _start_log(pr_url, options, env)
    log.info("Review of %s started", pr_url)
    warnings: list[str] = []
    try:
        outcome = _run(pr_url, options, env, warnings)
    except (ReviewAgentError, EngineError) as e:
        engine_failed = isinstance(e, EngineError)
        # `engine_detail`: the text can quote model output; the Action keeps
        # this record out of its job log (cli.py, actions.py).
        log.error("Run failed: %s", e, extra={"engine_detail": engine_failed})
        return RunResult(
            False,
            pr_url,
            log_path,
            error=str(e),
            warnings=warnings,
            mode=options.mode,
            engine_failed=engine_failed,
        )
    except Exception as e:  # report every failure the same way
        log.exception("Run failed with an unexpected error")
        return RunResult(
            False,
            pr_url,
            log_path,
            error=f"Unexpected error: {type(e).__name__}: {e}",
            warnings=warnings,
            mode=options.mode,
        )
    finally:
        _stop_log(handler)
    return RunResult(
        True,
        pr_url,
        log_path,
        files=outcome.files,
        review=outcome.review,
        warnings=warnings,
        mode=options.mode,
    )


def _run(
    pr_url: str, options: Options, env: Mapping[str, str], warnings: list[str]
) -> _Outcome:
    pr = parse_pr_url(pr_url)
    config = load_config(options.config_path, env)
    log.info("Config: %s", config.path)
    token_var, token = select_token(config.auth, pr.owner, env)
    log.info("GitHub token for %s: %s", pr.owner, token_var)
    engine_key = read_secret(env, config.auth.engine_key_var, "engine key")

    with GitHubClient(
        token,
        token_var=token_var,
        base_url=options.api_url,
        transport=options.http_transport,
    ) as gh:
        _preflight(gh, config)
        warnings.extend(expiry_warnings(gh.token_expiration, token_var))
        if options.mode is not RunMode.DRY_RUN:
            _check_no_pending_review(gh, pr, config.auth.login)
        meta = gh.get_pull(pr)
        diff = gh.get_diff(pr)
        guidance = fetch_repo_guidance(gh, pr, meta["base"]["sha"])
        log.info("PR %s: head %s, diff %d bytes", pr, meta["head"]["sha"], len(diff))

        factory = options.engine_factory or default_engine_factory(options.sandbox)
        engine = factory(config.engine, engine_key)
        prompt = PromptBuilder(
            title=meta.get("title") or "",
            body=meta.get("body") or "",
            diff=diff,
            repo_guidance=guidance,
            instructions=load_instructions(config.dir, pr),
            language=config.review.language,
            finding_limit=config.review.finding_limit,
        ).build()

        with Workspace(
            meta["base"]["repo"]["clone_url"],
            pr.number,
            token=token,
            tmp_root=options.tmp_root,
        ) as ws:
            review = _review_with_retry(engine, prompt, ws.path, options.clock)

        mapped = ReviewMapper(
            commit_id=meta["head"]["sha"],
            diff=diff,
            engine_name=engine.name,
            model=engine.model,
            finding_limit=config.review.finding_limit,
            skip_globs=config.review.skip_globs,
        ).map(review)
        mapped = filter_review(mapped, target=pr, secrets=(token, engine_key))
        publisher = Publisher(pr)
        if options.mode is RunMode.DRY_RUN:
            files = publisher.dry_run(mapped, options.out_dir or Path.cwd())
            for f in files:
                log.info("Wrote %s", f)
            return _Outcome(mapped, files=files)
        posted = publisher.post(gh, mapped, publish=options.mode is RunMode.PUBLISH)
        log.info(
            "Posted review %s (%s) with %d inline comments",
            posted.review_id,
            posted.state,
            len(mapped.comments),
        )
        return _Outcome(mapped)


def _preflight(gh: GitHubClient, config: Config) -> None:
    login = gh.get_user().get("login")
    if login != config.auth.login:
        raise LoginMismatch(
            f"The GitHub token in {gh.token_var} belongs to "
            f"{login!r}, not to the configured Reviewer {config.auth.login!r}. "
            "The engine did not run."
        )
    log.info("Token belongs to %s", login)


class PendingReviewExists(ReviewAgentError):
    """The Reviewer already has a pending review on the Target PR."""


def _check_no_pending_review(gh: GitHubClient, pr: PullRef, login: str) -> None:
    """GitHub allows one pending review per user and PR. Stop before the
    engine runs, with a message the Reviewer can act on."""
    for r in gh.list_reviews(pr):
        if r.get("state") == "PENDING" and (r.get("user") or {}).get("login") == login:
            raise PendingReviewExists(
                f"{login} already has a pending review on {pr.url}. Open the PR, "
                "then submit or delete that pending review, and run the review "
                "again. The engine did not run."
            )
    log.info("No pending review by %s on %s", login, pr)


def _review_with_retry(
    engine: Engine, prompt: str, clone: Path, clock: Callable[[], float]
) -> dict:
    """Run the engine; one retry on invalid Review JSON. All attempts share
    one budget of ENGINE_BUDGET seconds (story 12): the retry gets only the
    time that is left, and there is no retry if less than MIN_RETRY is left."""
    attempts = 2
    deadline = clock() + ENGINE_BUDGET
    for attempt in range(1, attempts + 1):
        left = deadline - clock()
        log.info(
            "Engine run %d of %d (%s, %s), %.0f s left",
            attempt,
            attempts,
            engine.name,
            engine.model,
            left,
        )
        start = clock()
        raw = engine.review(prompt, clone, timeout=left)
        log.info("Engine run %d took %.0f s", attempt, clock() - start)
        try:
            return parse_review(raw)
        except InvalidReviewJSON as e:
            # Never the output itself: it can quote private code or secrets.
            log.warning(
                "Engine run %d: %s (the output has %d characters)",
                attempt,
                e,
                len(raw),
            )
            if attempt == attempts:
                raise InvalidReviewJSON(
                    f"The engine returned invalid Review JSON {attempts} times. "
                    f"Last error: {e}"
                ) from None
            if deadline - clock() < MIN_RETRY:
                raise InvalidReviewJSON(
                    "The engine returned invalid Review JSON, and too little of "
                    f"the {ENGINE_BUDGET / 60:g} minutes of engine time is left "
                    f"for a retry. Error: {e}"
                ) from None
    raise AssertionError("unreachable")


def _default_log_dir(env: Mapping[str, str]) -> Path:
    state = env.get("XDG_STATE_HOME")
    base = (
        Path(state)
        if state
        else Path(env.get("HOME", str(Path.home()))) / (".local/state")
    )
    return base / "review-agent" / "runs"


def _start_log(
    pr_url: str, options: Options, env: Mapping[str, str]
) -> tuple[Path | None, logging.Handler | None]:
    log_dir = options.log_dir or _default_log_dir(env)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    try:
        slug = str(parse_pr_url(pr_url)).replace("/", "-").replace("#", "-")
    except ReviewAgentError:
        slug = "invalid-url"
    path = log_dir / f"{stamp}-{slug}.log"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        # Only the user can read the run log: it can name private repos.
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        handler = logging.FileHandler(path, mode="a", encoding="utf-8")
    except OSError:
        return None, None
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    log.addHandler(handler)
    if log.level == logging.NOTSET or log.level > logging.DEBUG:
        log.setLevel(logging.DEBUG)
    return path, handler


def _stop_log(handler: logging.Handler | None) -> None:
    if handler is not None:
        log.removeHandler(handler)
        handler.close()
