"""Log in with Bluesky, or any AT Protocol account (including a self-hosted PDS).

atproto OAuth is regular OAuth 2 with a few required extras (https://atproto.com/specs/oauth):
- PAR: we POST the login request to the server first, then send the player there with a
  short reference to it
- PKCE: proves the code coming back belongs to the login we started
- DPoP: every token request is signed with a throwaway key made for this one login
- the app's "client_id" is a URL to a JSON file describing the app (see client_metadata())

We're a "public" client (no long-term signing key to manage) and only ask for the base
"atproto" scope, which proves who you are and grants nothing else. Once we know the account's
DID we throw the tokens away.

Approach based on Bluesky's Python OAuth example:
https://github.com/bluesky-social/cookbook/tree/main/python-oauth-web-app
"""

import base64
import hashlib
import json
import re
import secrets
import time
import urllib.request
from urllib.parse import urlencode

import dns.exception
import dns.resolver
from joserfc import jwt
from joserfc.jwk import ECKey

from . import safe_http

SCOPE = "atproto"
DEFAULT_ENTRYWAY = "https://bsky.social"
PLC_DIRECTORY = "https://plc.directory"
PUBLIC_APPVIEW = "https://public.api.bsky.app"

HANDLE_RE = re.compile(
    r"^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]([a-z0-9-]{0,61}[a-z0-9])?$", re.IGNORECASE
)
DID_RE = re.compile(r"^did:[a-z]+:[a-zA-Z0-9._:%-]*[a-zA-Z0-9._-]$")


class AtprotoError(Exception):
    pass


# ---------------------------------------------------------------------------------------------
# Identity: handle <-> DID <-> DID document
# ---------------------------------------------------------------------------------------------


def is_valid_handle(value):
    return isinstance(value, str) and len(value) <= 253 and HANDLE_RE.match(value) is not None


def is_valid_did(value):
    return isinstance(value, str) and len(value) <= 2048 and DID_RE.match(value) is not None


def clean_identifier(raw):
    """Strip whitespace, invisible characters from copy-paste, and a leading @."""
    value = "".join(ch for ch in (raw or "") if ch.isprintable()).strip()
    value = value.removeprefix("@")
    return value.lower() if is_valid_handle(value.lower()) else value


def resolve_handle(handle):
    """Handle -> DID, via DNS TXT record or the /.well-known/atproto-did file."""
    try:
        answers = dns.resolver.resolve(f"_atproto.{handle}", "TXT", lifetime=3)
        for record in answers:
            value = b"".join(record.strings).decode(errors="replace")
            if value.startswith("did=") and is_valid_did(value[4:]):
                return value[4:]
    except dns.exception.DNSException:
        pass

    try:
        response = safe_http.request("GET", f"https://{handle}/.well-known/atproto-did")
    except Exception:
        return None
    if response.status_code != 200:
        return None
    lines = response.text.split()
    did = lines[0] if lines else ""
    return did if is_valid_did(did) else None


def resolve_did(did):
    """DID -> DID document."""
    if did.startswith("did:plc:"):
        doc = safe_http.get_json(f"{PLC_DIRECTORY}/{did}")
    elif did.startswith("did:web:"):
        domain = did.removeprefix("did:web:")
        # Only plain hostnames: did:web with ports or paths isn't used for atproto accounts.
        if not is_valid_handle(domain):
            raise AtprotoError("Unsupported did:web.")
        doc = safe_http.get_json(f"https://{domain}/.well-known/did.json")
    else:
        raise AtprotoError("Unsupported DID type.")
    if doc.get("id") != did:
        raise AtprotoError("DID document doesn't match the DID.")
    return doc


def handle_from_doc(doc):
    for aka in doc.get("alsoKnownAs") or []:
        if isinstance(aka, str) and aka.startswith("at://"):
            handle = aka.removeprefix("at://").lower()
            if is_valid_handle(handle):
                return handle
    return None


def pds_from_doc(doc):
    for service in doc.get("service") or []:
        if (
            isinstance(service, dict)
            and service.get("id") in ("#atproto_pds", f"{doc.get('id')}#atproto_pds")
            and service.get("type") == "AtprotoPersonalDataServer"
            and isinstance(service.get("serviceEndpoint"), str)
        ):
            return service["serviceEndpoint"].rstrip("/")
    raise AtprotoError("This account doesn't list a PDS.")


def resolve_identity(identifier):
    """Handle or DID -> (did, handle, doc). The handle is checked in both directions: the handle
    must point at the DID and the DID document must claim the handle back. If it doesn't, the
    handle comes back as None (the account still works, we just won't show that handle)."""
    if is_valid_handle(identifier):
        did = resolve_handle(identifier)
        if not did:
            raise AtprotoError(f"Couldn't find an account for {identifier}.")
        doc = resolve_did(did)
        if handle_from_doc(doc) != identifier:
            raise AtprotoError(f"{identifier} doesn't match its account.")
        return did, identifier, doc
    if is_valid_did(identifier):
        doc = resolve_did(identifier)
        handle = handle_from_doc(doc)
        if handle and resolve_handle(handle) != identifier:
            handle = None
        return identifier, handle, doc
    raise AtprotoError("That's not a valid handle.")


# ---------------------------------------------------------------------------------------------
# Authorization server discovery
# ---------------------------------------------------------------------------------------------


def authserver_for_pds(pds_url):
    meta = safe_http.get_json(f"{pds_url}/.well-known/oauth-protected-resource")
    servers = meta.get("authorization_servers")
    if not isinstance(servers, list) or not servers or not isinstance(servers[0], str):
        raise AtprotoError("The PDS doesn't name an authorization server.")
    return servers[0].rstrip("/")


def fetch_authserver_meta(issuer):
    meta = safe_http.get_json(f"{issuer}/.well-known/oauth-authorization-server")
    check_authserver_meta(meta, issuer)
    return meta


def check_authserver_meta(meta, issuer):
    def has(key, value):
        field = meta.get(key)
        return isinstance(field, list) and value in field

    required = [
        meta.get("issuer") == issuer,
        has("response_types_supported", "code"),
        has("grant_types_supported", "authorization_code"),
        has("code_challenge_methods_supported", "S256"),
        has("token_endpoint_auth_methods_supported", "none"),
        has("scopes_supported", SCOPE),
        has("dpop_signing_alg_values_supported", "ES256"),
        meta.get("authorization_response_iss_parameter_supported") is True,
        meta.get("require_pushed_authorization_requests") is True,
        meta.get("client_id_metadata_document_supported") is True,
    ]
    if not all(required):
        raise AtprotoError("The authorization server doesn't support atproto OAuth.")
    for key in (
        "authorization_endpoint",
        "token_endpoint",
        "pushed_authorization_request_endpoint",
    ):
        if not isinstance(meta.get(key), str):
            raise AtprotoError("The authorization server metadata is incomplete.")
        safe_http.check_url(meta[key])


# ---------------------------------------------------------------------------------------------
# Client metadata, PKCE, DPoP
# ---------------------------------------------------------------------------------------------


def client_metadata(client_id, redirect_uri, app_url):
    return {
        "client_id": client_id,
        "client_name": "Mafia Hustle",
        "client_uri": app_url,
        "application_type": "web",
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "redirect_uris": [redirect_uri],
        "scope": SCOPE,
        "token_endpoint_auth_method": "none",
        "dpop_bound_access_tokens": True,
    }


def localhost_client_id(redirect_uri):
    """For local development the spec lets a client skip hosting its metadata."""
    return "http://localhost?" + urlencode({"redirect_uri": redirect_uri, "scope": SCOPE})


def pkce_pair():
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def new_dpop_key():
    return ECKey.generate_key("P-256")


def dpop_proof(key, method, url, nonce=None):
    now = int(time.time())
    claims = {
        "jti": secrets.token_urlsafe(16),
        "htm": method,
        "htu": url.split("?", 1)[0].split("#", 1)[0],
        "iat": now,
        "exp": now + 60,
    }
    if nonce:
        claims["nonce"] = nonce
    header = {"typ": "dpop+jwt", "alg": "ES256", "jwk": key.as_dict(private=False)}
    return jwt.encode(header, claims, key)


def needs_new_nonce(response):
    if response.status_code not in (400, 401):
        return False
    challenge = response.headers.get("WWW-Authenticate", "")
    scheme, _, params = challenge.partition(" ")
    if scheme.lower() == "dpop":
        opts = urllib.request.parse_keqv_list(urllib.request.parse_http_list(params))
        if opts.get("error") == "use_dpop_nonce":
            return True
    try:
        return json.loads(response.content).get("error") == "use_dpop_nonce"
    except (ValueError, AttributeError):
        return False


def post_with_dpop(url, data, key, nonce=None):
    """POST to the authorization server, retrying once if it wants a fresh DPoP nonce.
    Returns (response, latest_nonce)."""
    response = None
    for _ in range(2):
        response = safe_http.request(
            "POST", url, data=data, headers={"DPoP": dpop_proof(key, "POST", url, nonce)}
        )
        nonce = response.headers.get("DPoP-Nonce", nonce)
        if not needs_new_nonce(response):
            break
    return response, nonce


# ---------------------------------------------------------------------------------------------
# The login flow
# ---------------------------------------------------------------------------------------------


def start_login(identifier, client_id, redirect_uri):
    """Returns (url to send the player to, data to keep until they come back)."""
    did = handle = None
    if identifier:
        did, handle, doc = resolve_identity(identifier)
        issuer = authserver_for_pds(pds_from_doc(doc))
    else:
        issuer = DEFAULT_ENTRYWAY
    safe_http.check_url(issuer)
    meta = fetch_authserver_meta(issuer)

    key = new_dpop_key()
    state = secrets.token_urlsafe(32)
    verifier, challenge = pkce_pair()
    par_body = {
        "client_id": client_id,
        "response_type": "code",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        "redirect_uri": redirect_uri,
        "scope": SCOPE,
    }
    if identifier:
        par_body["login_hint"] = handle or did

    response, nonce = post_with_dpop(meta["pushed_authorization_request_endpoint"], par_body, key)
    if response.status_code not in (200, 201):
        raise AtprotoError(f"The server refused the login request (HTTP {response.status_code}).")
    request_uri = safe_http.parse_json(response).get("request_uri")
    if not isinstance(request_uri, str):
        raise AtprotoError("The server sent back an unexpected login response.")

    pending = {
        "state": state,
        "issuer": issuer,
        "did": did,
        "pkce_verifier": verifier,
        "dpop_key": key.as_dict(private=True),
        "dpop_nonce": nonce,
    }
    query = urlencode({"client_id": client_id, "request_uri": request_uri})
    return f"{meta['authorization_endpoint']}?{query}", pending


def finish_login(pending, code, issuer, client_id, redirect_uri):
    """Swap the code for tokens, check they're for the right account, and return the profile."""
    if issuer != pending["issuer"]:
        raise AtprotoError("The login came back from a different server than it went to.")

    meta = fetch_authserver_meta(issuer)
    key = ECKey.import_key(pending["dpop_key"])
    response, nonce = post_with_dpop(
        meta["token_endpoint"],
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": pending["pkce_verifier"],
        },
        key,
        pending.get("dpop_nonce"),
    )
    if response.status_code != 200:
        raise AtprotoError(f"The server wouldn't hand over a token (HTTP {response.status_code}).")
    tokens = safe_http.parse_json(response)

    sub = tokens.get("sub")
    scopes = str(tokens.get("scope", "")).split()
    if str(tokens.get("token_type", "")).lower() != "dpop" or SCOPE not in scopes:
        raise AtprotoError("The server sent back an unexpected token.")
    if not is_valid_did(sub):
        raise AtprotoError("The server didn't say which account logged in.")

    # If we started from a handle, we already know which account this has to be.
    if pending.get("did") and sub != pending["did"]:
        raise AtprotoError("The server logged in a different account than you asked for.")
    did, handle, doc = resolve_identity(sub)
    if not pending.get("did") and authserver_for_pds(pds_from_doc(doc)) != issuer:
        # We started from bsky.social without a handle: make sure that server actually
        # speaks for this account.
        raise AtprotoError("That server isn't allowed to log in this account.")

    revoke_tokens(meta, tokens, client_id, key, nonce)
    return {"subject": did, "username": handle or did, **fetch_profile(did)}


def revoke_tokens(meta, tokens, client_id, key, nonce):
    """Best effort: we never store the tokens, this just shortens their life."""
    url = meta.get("revocation_endpoint")
    if not isinstance(url, str):
        return
    for kind in ("refresh_token", "access_token"):
        if isinstance(tokens.get(kind), str):
            try:
                _, nonce = post_with_dpop(
                    url, {"token": tokens[kind], "client_id": client_id}, key, nonce
                )
            except Exception:  # noqa: S112 - revocation failing doesn't affect login
                continue


def fetch_profile(did):
    """Display name and avatar from the public Bluesky API. Optional: accounts that haven't
    used Bluesky just won't have them."""
    try:
        profile = safe_http.get_json(
            f"{PUBLIC_APPVIEW}/xrpc/app.bsky.actor.getProfile?{urlencode({'actor': did})}"
        )
    except Exception:
        return {"display_name": None, "avatar_url": None}
    name, avatar = profile.get("displayName"), profile.get("avatar")
    return {
        "display_name": name[:200] if isinstance(name, str) and name else None,
        "avatar_url": avatar if isinstance(avatar, str) and avatar.startswith("https://") else None,
    }
