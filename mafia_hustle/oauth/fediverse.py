"""Log in with any server that speaks the Mastodon API: Mastodon, GoToSocial, Akkoma, Pleroma, ...

The flow (standard OAuth 2 authorization code):
1. Register an app on the player's instance (once per instance, then reuse it).
2. Send the player to the instance's /oauth/authorize page.
3. The instance sends them back with a code, which we swap for an access token.
4. Ask /api/v1/accounts/verify_credentials who the token belongs to.
5. Revoke the token. We only needed to know who they are, so we never store it.
"""

import base64
import contextlib
import hashlib
import secrets
from urllib.parse import urlencode

from . import safe_http

SCOPES = "read:accounts"
APP_NAME = "Mafia Hustle"
APP_WEBSITE = "https://github.com/cmdr-nova/Mafia-Hustle"


class FediverseError(Exception):
    pass


def normalize_instance(raw):
    """Turn whatever the player typed into a bare domain.

    Accepts "mkultra.social", "https://mkultra.social/", "@vito@mkultra.social", or
    "vito@mkultra.social".
    """
    value = (raw or "").strip().lower()
    for prefix in ("https://", "http://"):
        value = value.removeprefix(prefix)
    value = value.split("/", 1)[0]
    if "@" in value:
        value = value.rsplit("@", 1)[1]
    if not safe_http.is_public_hostname(value):
        raise FediverseError("That doesn't look like a fediverse server address.")
    return value


def pkce_pair():
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def register_app(domain, redirect_uri):
    response = safe_http.request(
        "POST",
        f"https://{domain}/api/v1/apps",
        json={
            "client_name": APP_NAME,
            "redirect_uris": redirect_uri,
            "scopes": SCOPES,
            "website": APP_WEBSITE,
        },
    )
    if response.status_code != 200:
        raise FediverseError(f"{domain} refused to register the app (HTTP {response.status_code}).")
    data = safe_http.parse_json(response)
    client_id, client_secret = data.get("client_id"), data.get("client_secret")
    if not isinstance(client_id, str) or not isinstance(client_secret, str):
        raise FediverseError(f"{domain} sent back an unexpected app registration.")
    return client_id, client_secret


def authorize_url(domain, client_id, redirect_uri, state, code_challenge):
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": SCOPES,
            "state": state,
            # PKCE: servers that support it (Mastodon 4.3+) check it, older ones ignore it.
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"https://{domain}/oauth/authorize?{query}"


def exchange_code(domain, client_id, client_secret, redirect_uri, code, code_verifier):
    response = safe_http.request(
        "POST",
        f"https://{domain}/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "scope": SCOPES,
            "code_verifier": code_verifier,
        },
    )
    if response.status_code != 200:
        raise FediverseError(f"{domain} wouldn't hand over a token (HTTP {response.status_code}).")
    token = safe_http.parse_json(response).get("access_token")
    if not isinstance(token, str) or not token:
        raise FediverseError(f"{domain} sent back an unexpected token response.")
    return token


def verify_credentials(domain, token):
    response = safe_http.request(
        "GET",
        f"https://{domain}/api/v1/accounts/verify_credentials",
        headers={"Authorization": f"Bearer {token}"},
    )
    if response.status_code != 200:
        raise FediverseError(
            f"{domain} wouldn't tell us who you are (HTTP {response.status_code})."
        )
    account = safe_http.parse_json(response)
    account_id, username = account.get("id"), account.get("username")
    if not isinstance(account_id, str) or not account_id or not isinstance(username, str):
        raise FediverseError(f"{domain} sent back an unexpected account.")

    avatar = account.get("avatar")
    display_name = account.get("display_name")
    return {
        "subject": f"{domain}:{account_id}",
        "username": f"@{username}@{domain}",
        "display_name": display_name[:200] if isinstance(display_name, str) else None,
        "avatar_url": avatar if isinstance(avatar, str) and avatar.startswith("https://") else None,
    }


def revoke_token(domain, client_id, client_secret, token):
    """Best effort. If it fails the token is still never stored anywhere."""
    with contextlib.suppress(Exception):
        safe_http.request(
            "POST",
            f"https://{domain}/oauth/revoke",
            data={"client_id": client_id, "client_secret": client_secret, "token": token},
        )
