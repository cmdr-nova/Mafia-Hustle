import base64
import hashlib
import json
from urllib.parse import parse_qs, urlsplit

import dns.resolver
import pytest
import responses
from flask.testing import FlaskClient
from joserfc import jwt
from joserfc.jwk import ECKey

from mafia_hustle.extensions import db
from mafia_hustle.models import User
from mafia_hustle.oauth import atproto

LOCAL = "http://127.0.0.1:5000"
HANDLE = "vito.mkultra.social"
DID = "did:plc:vito123"
PDS = "https://pds.mkultra.social"


class FakeAuthServer:
    """Just enough of an atproto authorization server to run the login flow against, and to
    check that we sign every request with DPoP and the same key throughout."""

    def __init__(self, rsps, issuer=PDS, sub=DID):
        self.issuer, self.sub = issuer, sub
        self.nonce = "nonce-1"
        self.par = None
        self.dpop_jwk = None
        self.revoked = []
        rsps.get(
            f"{issuer}/.well-known/oauth-authorization-server",
            json={
                "issuer": issuer,
                "authorization_endpoint": f"{issuer}/oauth/authorize",
                "token_endpoint": f"{issuer}/oauth/token",
                "pushed_authorization_request_endpoint": f"{issuer}/oauth/par",
                "revocation_endpoint": f"{issuer}/oauth/revoke",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": ["none", "private_key_jwt"],
                "scopes_supported": ["atproto", "transition:generic"],
                "dpop_signing_alg_values_supported": ["ES256"],
                "authorization_response_iss_parameter_supported": True,
                "require_pushed_authorization_requests": True,
                "client_id_metadata_document_supported": True,
            },
        )
        rsps.add_callback(responses.POST, f"{issuer}/oauth/par", callback=self.handle_par)
        rsps.add_callback(responses.POST, f"{issuer}/oauth/token", callback=self.handle_token)
        rsps.add_callback(responses.POST, f"{issuer}/oauth/revoke", callback=self.handle_revoke)

    def check_dpop(self, request):
        proof = request.headers["DPoP"]
        header = jwt.decode(proof, ECKey.import_key(json.loads(_b64(proof.split(".")[0]))["jwk"]))
        assert header.header["typ"] == "dpop+jwt"
        assert header.claims["htm"] == "POST"
        assert header.claims["htu"] == request.url
        if self.dpop_jwk is None:
            self.dpop_jwk = header.header["jwk"]
        assert header.header["jwk"] == self.dpop_jwk, "DPoP key changed mid-login"
        return header.claims.get("nonce") == self.nonce

    def nonce_error(self):
        return (400, {"DPoP-Nonce": self.nonce}, json.dumps({"error": "use_dpop_nonce"}))

    def handle_par(self, request):
        if not self.check_dpop(request):
            return self.nonce_error()
        self.par = {k: v[0] for k, v in parse_qs(request.body).items()}
        return (201, {"DPoP-Nonce": self.nonce}, json.dumps({"request_uri": "urn:par:1"}))

    def handle_token(self, request):
        if not self.check_dpop(request):
            return self.nonce_error()
        body = {k: v[0] for k, v in parse_qs(request.body).items()}
        assert body["grant_type"] == "authorization_code"
        assert body["code"] == "the-code"
        assert body["redirect_uri"] == self.par["redirect_uri"]
        assert body["client_id"] == self.par["client_id"]
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(body["code_verifier"].encode()).digest()
        ).rstrip(b"=")
        assert challenge.decode() == self.par["code_challenge"], "PKCE mismatch"
        tokens = {
            "access_token": "at",
            "refresh_token": "rt",
            "token_type": "DPoP",
            "scope": "atproto",
            "sub": self.sub,
        }
        return (200, {}, json.dumps(tokens))

    def handle_revoke(self, request):
        self.check_dpop(request)
        self.revoked.append(parse_qs(request.body)["token"][0])
        return (200, {}, "{}")


def _b64(segment):
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def did_doc(did=DID, handle=HANDLE, pds=PDS):
    return {
        "id": did,
        "alsoKnownAs": [f"at://{handle}"],
        "service": [
            {"id": "#atproto_pds", "type": "AtprotoPersonalDataServer", "serviceEndpoint": pds}
        ],
    }


@pytest.fixture(autouse=True)
def no_dns(monkeypatch):
    def fail(*args, **kwargs):
        raise dns.resolver.NXDOMAIN

    monkeypatch.setattr(atproto.dns.resolver, "resolve", fail)


@pytest.fixture
def local_client(app):
    class LocalClient(FlaskClient):
        """Browses the game at http://127.0.0.1:5000, like local development does."""

        def open(self, *args, **kwargs):
            kwargs.setdefault("base_url", LOCAL)
            return super().open(*args, **kwargs)

    return LocalClient(app, app.response_class, use_cookies=True)


def mock_identity(rsps, did=DID, handle=HANDLE, pds=PDS, authserver=PDS):
    rsps.get(f"https://{handle}/.well-known/atproto-did", body=did)
    rsps.get(f"https://plc.directory/{did}", json=did_doc(did, handle, pds))
    rsps.get(
        f"{pds}/.well-known/oauth-protected-resource", json={"authorization_servers": [authserver]}
    )
    rsps.get(
        "https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile",
        json={"did": did, "displayName": "Vito", "avatar": "https://cdn.bsky.app/vito.jpg"},
    )


def start(client, handle=HANDLE):
    response = client.post("/login/bluesky", data={"handle": handle})
    assert response.status_code == 302, response.data
    return response.headers["Location"]


def finish(client, server, iss=None):
    return client.get(
        "/login/bluesky/callback",
        query_string={
            "code": "the-code",
            "state": server.par["state"],
            "iss": iss or server.issuer,
        },
    )


@responses.activate
def test_full_login_with_handle(local_client):
    mock_identity(responses)
    server = FakeAuthServer(responses)

    location = urlsplit(start(local_client, "@Vito.MKULTRA.social"))
    assert f"{location.scheme}://{location.netloc}{location.path}" == f"{PDS}/oauth/authorize"
    assert parse_qs(location.query)["request_uri"] == ["urn:par:1"]
    assert server.par["scope"] == "atproto"
    assert server.par["login_hint"] == HANDLE
    assert server.par["redirect_uri"] == f"{LOCAL}/login/bluesky/callback"
    assert server.par["client_id"].startswith("http://localhost?")

    response = finish(local_client, server)
    assert response.headers["Location"] == "/"

    user = db.session.scalar(db.select(User))
    assert (user.provider, user.subject, user.username) == ("bluesky", DID, HANDLE)
    assert user.display_name == "Vito"
    assert user.avatar_url == "https://cdn.bsky.app/vito.jpg"
    assert sorted(server.revoked) == ["at", "rt"]
    assert local_client.get("/").status_code == 200


@responses.activate
def test_blank_handle_starts_at_bsky_social(local_client):
    mock_identity(
        responses, pds="https://morel.us-east.host.bsky.network", authserver="https://bsky.social"
    )
    server = FakeAuthServer(responses, issuer="https://bsky.social")

    assert start(local_client, "").startswith("https://bsky.social/oauth/authorize?")
    assert "login_hint" not in server.par
    assert finish(local_client, server).headers["Location"] == "/"
    assert db.session.scalar(db.select(User)).subject == DID


@responses.activate
def test_server_that_doesnt_own_the_account_is_rejected(local_client):
    # Started from bsky.social, but the account that came back lives on a PDS that uses a
    # different authorization server. bsky.social can't vouch for it.
    mock_identity(responses, authserver=PDS)
    server = FakeAuthServer(responses, issuer="https://bsky.social")
    start(local_client, "")
    response = finish(local_client, server)
    assert response.headers["Location"] == "/login"
    assert db.session.scalar(db.select(User)) is None


@responses.activate
def test_different_account_than_requested_is_rejected(local_client):
    mock_identity(responses)
    mock_identity(responses, did="did:plc:sonny", handle="sonny.mkultra.social")
    server = FakeAuthServer(responses, sub="did:plc:sonny")
    start(local_client)
    assert finish(local_client, server).headers["Location"] == "/login"
    assert db.session.scalar(db.select(User)) is None


@responses.activate
def test_wrong_issuer_is_rejected(local_client):
    mock_identity(responses)
    server = FakeAuthServer(responses)
    start(local_client)
    assert (
        finish(local_client, server, iss="https://evil.example.org").headers["Location"] == "/login"
    )
    assert db.session.scalar(db.select(User)) is None


@responses.activate
def test_handle_that_doesnt_match_its_did_is_rejected(local_client):
    responses.get(f"https://{HANDLE}/.well-known/atproto-did", body=DID)
    responses.get(f"https://plc.directory/{DID}", json=did_doc(handle="someone-else.example.com"))
    response = local_client.post("/login/bluesky", data={"handle": HANDLE}, follow_redirects=True)
    assert b"doesn&#39;t match its account" in response.data


def test_local_login_needs_127_0_0_1(client):
    response = client.post("/login/bluesky", data={"handle": HANDLE}, follow_redirects=True)
    assert b"127.0.0.1" in response.data


def test_client_metadata_only_served_with_public_url(app, client):
    assert client.get("/oauth/client-metadata.json").status_code == 404

    app.config["PUBLIC_URL"] = "https://hustle.mkultra.monster"
    meta = client.get("/oauth/client-metadata.json").get_json()
    assert meta["client_id"] == "https://hustle.mkultra.monster/oauth/client-metadata.json"
    assert meta["redirect_uris"] == ["https://hustle.mkultra.monster/login/bluesky/callback"]
    assert meta["scope"] == "atproto"
    assert meta["token_endpoint_auth_method"] == "none"
    assert meta["dpop_bound_access_tokens"] is True


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("@Vito.Bsky.Social", "vito.bsky.social"),
        ("vito.bsky.social‬", "vito.bsky.social"),
        (DID, DID),
    ],
)
def test_clean_identifier(raw, expected):
    assert atproto.clean_identifier(raw) == expected


def test_authserver_metadata_must_support_public_clients():
    meta = {
        "issuer": PDS,
        "token_endpoint_auth_methods_supported": ["private_key_jwt"],
    }
    with pytest.raises(atproto.AtprotoError):
        atproto.check_authserver_meta(meta, PDS)
