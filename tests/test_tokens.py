"""Seam 1: token selection and GitHub access errors (ticket #18)."""

from datetime import UTC, datetime, timedelta

from harness import GITHUB_TOKEN, LOGIN, review_json
from test_run_review import assert_failed_with_nothing_written

TOKEN_MAP_CONFIG = f"""\
[auth]
login = "{LOGIN}"

[auth.tokens]
Octo = "GH_TOKEN_OCTO"
"""


def bearer_tokens(world) -> set[str]:
    return {r.headers["authorization"] for r in world.github.requests}


def test_owner_in_the_token_map_uses_its_own_token(world):
    world.write_config(TOKEN_MAP_CONFIG)
    world.env["GH_TOKEN_OCTO"] = "octo-org-token"
    world.engine.respond(review_json())

    result = world.run()

    assert result.ok, result.error
    assert bearer_tokens(world) == {"Bearer octo-org-token"}


def test_owner_not_in_the_token_map_uses_the_default_token(world):
    world.write_config(TOKEN_MAP_CONFIG.replace("Octo =", "other-org ="))
    world.env["GH_TOKEN_OCTO"] = "octo-org-token"
    world.engine.respond(review_json())

    result = world.run()

    assert result.ok, result.error
    assert bearer_tokens(world) == {f"Bearer {GITHUB_TOKEN}"}


def test_mapped_token_variable_not_set_names_the_variable(world):
    world.write_config(TOKEN_MAP_CONFIG)
    world.engine.respond(review_json())

    result = world.run()

    assert_failed_with_nothing_written(world, result)
    assert "GH_TOKEN_OCTO" in result.error
    assert world.github.requests == []
    assert world.engine.calls == []


def test_token_map_value_must_be_a_variable_name(world):
    world.write_config(TOKEN_MAP_CONFIG.replace('"GH_TOKEN_OCTO"', "3"))
    world.engine.respond(review_json())

    result = world.run()

    assert_failed_with_nothing_written(world, result)
    assert "[auth.tokens]" in result.error
    assert world.github.requests == []


def assert_refused_before_any_request(world, result, secret: str):
    assert_failed_with_nothing_written(world, result)
    assert "GITHUB_TOKEN" in result.error
    assert world.github.requests == []
    assert world.engine.calls == []
    assert secret not in result.error
    assert secret not in result.log_path.read_text()


def test_config_that_names_github_token_is_refused(world):
    world.write_config(
        f'[auth]\nlogin = "{LOGIN}"\ngithub_token_var = "GITHUB_TOKEN"\n'
    )
    world.env["GITHUB_TOKEN"] = "ghs_actions-token"
    world.engine.respond(review_json())

    result = world.run()

    assert_refused_before_any_request(world, result, "ghs_actions-token")


def test_token_with_the_same_value_as_github_token_is_refused(world):
    # The leak in a workflow: REVIEW_AGENT_GITHUB_TOKEN: ${{ github.token }}
    world.env["GITHUB_TOKEN"] = "actions-token-value"
    world.env["REVIEW_AGENT_GITHUB_TOKEN"] = "actions-token-value"
    world.engine.respond(review_json())

    result = world.run()

    assert_refused_before_any_request(world, result, "actions-token-value")


def test_app_installation_token_is_refused(world):
    world.env["REVIEW_AGENT_GITHUB_TOKEN"] = "ghs_installation-token"
    world.engine.respond(review_json())

    result = world.run()

    assert_refused_before_any_request(world, result, "ghs_installation-token")


def test_github_token_in_the_environment_is_ignored(world):
    world.env["GITHUB_TOKEN"] = "ghs_actions-token"
    world.engine.respond(review_json())

    result = world.run()

    assert result.ok, result.error
    assert bearer_tokens(world) == {f"Bearer {GITHUB_TOKEN}"}


PULL = "/repos/octo/widgets/pulls/7"
SSO_URL = "https://github.com/orgs/octo/sso?authorization_request=abc123"


def test_sso_block_shows_the_authorization_url_and_stops(world):
    world.github.route(
        "GET",
        PULL,
        status=403,
        headers={"X-GitHub-SSO": f"required; url={SSO_URL}"},
        json={"message": "Resource protected by organization SAML enforcement."},
    )
    world.engine.respond(review_json())

    result = world.run()

    assert_failed_with_nothing_written(world, result)
    assert SSO_URL in result.error
    assert "REVIEW_AGENT_GITHUB_TOKEN" in result.error
    assert world.engine.calls == []


def test_not_found_names_the_token_variable_and_stops(world):
    world.write_config(TOKEN_MAP_CONFIG)
    world.env["GH_TOKEN_OCTO"] = "octo-org-token"
    world.github.route("GET", PULL, status=404, json={"message": "Not Found"})
    world.engine.respond(review_json())

    result = world.run()

    assert_failed_with_nothing_written(world, result)
    assert "GH_TOKEN_OCTO" in result.error
    assert "cannot see" in result.error and "octo/widgets" in result.error
    assert world.engine.calls == []


def test_bad_credentials_name_the_token_variable(world):
    world.github.route("GET", "/user", status=401, json={"message": "Bad credentials"})
    world.engine.respond(review_json())

    result = world.run()

    assert_failed_with_nothing_written(world, result)
    assert "REVIEW_AGENT_GITHUB_TOKEN" in result.error
    assert world.engine.calls == []


def expiry_in(days: float) -> str:
    when = datetime.now(UTC) + timedelta(days=days)
    return when.strftime("%Y-%m-%d %H:%M:%S UTC")


EXPIRY = "github-authentication-token-expiration"


def test_token_that_expires_in_14_days_or_less_gives_a_warning(world):
    world.user_headers[EXPIRY] = expiry_in(10)
    world.engine.respond(review_json())

    result = world.run()

    assert result.ok, result.error
    [warning] = result.warnings
    assert "REVIEW_AGENT_GITHUB_TOKEN" in warning
    assert "expires" in warning and "10 days" in warning
    assert warning in result.log_path.read_text()


def test_token_that_expires_later_gives_no_warning(world):
    world.user_headers[EXPIRY] = expiry_in(30)
    world.engine.respond(review_json())

    result = world.run()

    assert result.ok, result.error
    assert result.warnings == []


def test_token_with_no_expiry_gives_no_warning(world):
    world.engine.respond(review_json())

    result = world.run()

    assert result.ok, result.error
    assert result.warnings == []


def test_expiry_header_with_an_unknown_format_does_not_stop_the_run(world):
    world.user_headers[EXPIRY] = "soon"
    world.engine.respond(review_json())

    result = world.run()

    assert result.ok, result.error
    assert result.warnings == []
