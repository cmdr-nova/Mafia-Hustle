from urllib.parse import parse_qs, urlsplit

import pytest
import responses

from mafia_hustle.extensions import db
from mafia_hustle.models import FediverseApp, User
from mafia_hustle.oauth import fediverse

INSTANCE = "https://fedi.example.org"


@pytest.mark.parametrize(
    "raw",
    [
        "fedi.example.org",
        "https://fedi.example.org/",
        "@vito@fedi.example.org",
        " Vito@FEDI.Example.ORG ",
    ],
)
def test_normalize_instance(raw):
    assert fediverse.normalize_instance(raw) == "fedi.example.org"


@pytest.mark.parametrize("raw", ["", "localhost", "127.0.0.1", "10.0.0.1", "intranet", "a b.com"])
def test_normalize_instance_rejects_junk(raw):
    with pytest.raises(fediverse.FediverseError):
        fediverse.normalize_instance(raw)


def mock_instance(rsps, account_id="109", username="vito"):
    rsps.post(
        f"{INSTANCE}/api/v1/apps",
        json={"client_id": "cid", "client_secret": "csecret"},
    )
    rsps.post(f"{INSTANCE}/oauth/token", json={"access_token": "tok", "token_type": "Bearer"})
    rsps.get(
        f"{INSTANCE}/api/v1/accounts/verify_credentials",
        json={
            "id": account_id,
            "username": username,
            "display_name": "Vito",
            "avatar": f"{INSTANCE}/avatars/vito.png",
        },
        match=[responses.matchers.header_matcher({"Authorization": "Bearer tok"})],
    )
    rsps.post(f"{INSTANCE}/oauth/revoke", json={})


def start(client, instance="@vito@fedi.example.org"):
    response = client.post("/login/fediverse", data={"instance": instance})
    assert response.status_code == 302
    location = urlsplit(response.headers["Location"])
    assert f"{location.scheme}://{location.netloc}" == INSTANCE
    assert location.path == "/oauth/authorize"
    return parse_qs(location.query)


@responses.activate
def test_full_login(client):
    mock_instance(responses)
    query = start(client)
    assert query["scope"] == ["read:accounts"]
    assert query["code_challenge_method"] == ["S256"]

    response = client.get(
        "/login/fediverse/callback", query_string={"code": "abc", "state": query["state"][0]}
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/"

    user = db.session.scalar(db.select(User))
    assert user.provider == "fediverse"
    assert user.subject == "fedi.example.org:109"
    assert user.username == "@vito@fedi.example.org"
    assert user.avatar_url == f"{INSTANCE}/avatars/vito.png"
    assert client.get("/").status_code == 200

    token_call = next(c for c in responses.calls if c.request.url.endswith("/oauth/token"))
    body = parse_qs(token_call.request.body)
    assert body["code"] == ["abc"]
    assert body["client_secret"] == ["csecret"]
    assert "code_verifier" in body
    # We only needed the token to learn who you are, so it gets revoked straight away.
    assert any(c.request.url.endswith("/oauth/revoke") for c in responses.calls)


@responses.activate
def test_second_login_reuses_app_and_same_account(client):
    mock_instance(responses)
    for _ in range(2):
        query = start(client)
        client.get(
            "/login/fediverse/callback", query_string={"code": "abc", "state": query["state"][0]}
        )
        client.post("/logout")
    registrations = [c for c in responses.calls if c.request.url.endswith("/api/v1/apps")]
    assert len(registrations) == 1
    assert db.session.scalar(db.select(db.func.count(User.id))) == 1
    assert db.session.get(FediverseApp, "fedi.example.org").client_id == "cid"


@responses.activate
def test_state_from_another_browser_is_rejected(app, client):
    mock_instance(responses)
    query = start(client)
    other_browser = app.test_client()
    response = other_browser.get(
        "/login/fediverse/callback", query_string={"code": "abc", "state": query["state"][0]}
    )
    assert response.headers["Location"] == "/login"
    assert db.session.scalar(db.select(User)) is None


def test_unknown_state_is_rejected(client):
    response = client.get("/login/fediverse/callback", query_string={"code": "x", "state": "nope"})
    assert response.headers["Location"] == "/login"


@responses.activate
def test_cancelled_login(client):
    mock_instance(responses)
    start(client)
    response = client.get("/login/fediverse/callback", query_string={"error": "access_denied"})
    assert response.headers["Location"] == "/login"
    assert db.session.scalar(db.select(User)) is None


@responses.activate
def test_unreachable_instance_shows_error(client):
    responses.post(f"{INSTANCE}/api/v1/apps", status=500)
    response = client.post(
        "/login/fediverse", data={"instance": "fedi.example.org"}, follow_redirects=True
    )
    assert b"refused to register" in response.data


def test_private_address_is_refused_without_any_request(client):
    with responses.RequestsMock() as rsps:  # fails if any HTTP request is attempted
        response = client.post(
            "/login/fediverse", data={"instance": "192.168.1.1"}, follow_redirects=True
        )
        assert len(rsps.calls) == 0
    assert b"fediverse server address" in response.data
