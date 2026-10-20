"""The Reviewer's config file: `[auth]`, `[engine]` and `[review]`.

Path order: `--config`, then `REVIEW_AGENT_CONFIG`, then
`~/.config/review-agent/config.toml`. Secrets are never in this file: it holds
only the names of the environment variables that hold them.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from review_agent.engine import DEFAULT_BASE_URL, DEFAULT_MODEL
from review_agent.errors import ReviewAgentError

CONFIG_ENV = "REVIEW_AGENT_CONFIG"
DEFAULT_GITHUB_TOKEN_VAR = "REVIEW_AGENT_GITHUB_TOKEN"
DEFAULT_ENGINE_KEY_VAR = "REVIEW_AGENT_ENGINE_KEY"
DEFAULT_LANGUAGE = "ASD-STE100 Simplified Technical English"


class ConfigError(ReviewAgentError):
    """The config file is missing or not valid."""


@dataclass(frozen=True)
class AuthSettings:
    login: str
    github_token_var: str = DEFAULT_GITHUB_TOKEN_VAR
    engine_key_var: str = DEFAULT_ENGINE_KEY_VAR
    # Owner -> token variable name. Read by token selection (ticket #18).
    tokens: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class EngineSettings:
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL


@dataclass(frozen=True)
class ReviewSettings:
    language: str = DEFAULT_LANGUAGE  # the language of every Review
    # The whole `[review]` table as read. Typed fields come with the tickets
    # that use them (Finding limit, skip globs).
    raw: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Config:
    path: Path
    auth: AuthSettings
    engine: EngineSettings
    review: ReviewSettings

    @property
    def dir(self) -> Path:
        """The directory of the config file (Reviewer Instructions live here)."""
        return self.path.parent


def default_config_path(env: Mapping[str, str]) -> Path:
    xdg = env.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path(env.get("HOME", str(Path.home()))) / ".config"
    return base / "review-agent" / "config.toml"


def resolve_config_path(explicit: Path | str | None, env: Mapping[str, str]) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    if env.get(CONFIG_ENV):
        return Path(env[CONFIG_ENV]).expanduser()
    return default_config_path(env)


def load_config(explicit: Path | str | None, env: Mapping[str, str]) -> Config:
    path = resolve_config_path(explicit, env)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(
            f"No config file at {path}. Create it with an [auth] table that "
            'has login = "<your GitHub login>", or give another path with '
            f"--config or {CONFIG_ENV}."
        ) from None
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"The config file {path} is not valid TOML: {e}") from None

    auth = _table(data, "auth", path)
    engine = _table(data, "engine", path)
    review = _table(data, "review", path)

    login = auth.get("login")
    if not isinstance(login, str) or not login:
        raise ConfigError(
            f'Set [auth] login = "<your GitHub login>" in {path}. The tool '
            "checks that the token belongs to this login."
        )
    tokens = auth.get("tokens", {})
    if not isinstance(tokens, dict):
        raise ConfigError(f"[auth.tokens] in {path} must be a table.")
    return Config(
        path=path,
        auth=AuthSettings(
            login=login,
            github_token_var=_str(auth, "github_token_var", DEFAULT_GITHUB_TOKEN_VAR),
            engine_key_var=_str(auth, "engine_key_var", DEFAULT_ENGINE_KEY_VAR),
            tokens=dict(tokens),
        ),
        engine=EngineSettings(
            base_url=_str(engine, "base_url", DEFAULT_BASE_URL),
            model=_str(engine, "model", DEFAULT_MODEL),
        ),
        review=ReviewSettings(
            language=_str(review, "language", DEFAULT_LANGUAGE),
            raw=dict(review),
        ),
    )


def _table(data: dict, name: str, path: Path) -> dict:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"[{name}] in {path} must be a table.")
    return value


def _str(table: dict, key: str, default: str) -> str:
    value = table.get(key, default)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{key} must be a non-empty string.")
    return value


def read_secret(env: Mapping[str, str], var: str, what: str) -> str:
    """Read a secret from the environment only. No other source."""
    value = env.get(var, "")
    if not value.strip():
        raise ConfigError(
            f"The {what} is not set. Put it in the environment variable {var}."
        )
    return value.strip()
