"""Sign-in routes. Players log in with a fediverse or Bluesky account, so this app never sees or
stores a password. All we keep is which account they are (see models.User)."""

import secrets
from datetime import timedelta

import requests
from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import login_required, login_user, logout_user

from .extensions import db, limiter
from .models import FediverseApp, PendingLogin, User, utcnow
from .oauth import atproto, fediverse, safe_http

bp = Blueprint("auth", __name__)

PENDING_LOGIN_TTL = timedelta(minutes=10)
# Starting a login makes our server contact the player's server, so cap how often that happens.
LOGIN_LIMIT = "10 per minute"
LOGIN_ERRORS = (
    fediverse.FediverseError,
    atproto.AtprotoError,
    safe_http.UnsafeURL,
    requests.RequestException,
    ValueError,
)


@bp.get("/login")
def login():
    return render_template("login.html")


@bp.post("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("auth.login"))


# --- Fediverse ---------------------------------------------------------------------------------


@bp.post("/login/fediverse")
@limiter.limit(LOGIN_LIMIT)
def fediverse_start():
    try:
        domain = fediverse.normalize_instance(request.form.get("instance"))
        redirect_uri = external_url("auth.fediverse_callback")
        app = fediverse_app(domain, redirect_uri)
        state = secrets.token_urlsafe(32)
        verifier, challenge = fediverse.pkce_pair()
        save_pending(state, "fediverse", {"domain": domain, "pkce_verifier": verifier})
        return redirect(
            fediverse.authorize_url(domain, app.client_id, redirect_uri, state, challenge)
        )
    except LOGIN_ERRORS as err:
        return login_failed(err)


@bp.get("/login/fediverse/callback")
def fediverse_callback():
    pending = take_pending("fediverse")
    try:
        domain = pending["domain"]
        app = db.session.get(FediverseApp, domain)
        code = request.args.get("code")
        if app is None or not code:
            raise fediverse.FediverseError("The login didn't finish. Try again.")
        token = fediverse.exchange_code(
            domain,
            app.client_id,
            app.client_secret,
            app.redirect_uri,
            code,
            pending["pkce_verifier"],
        )
        try:
            profile = fediverse.verify_credentials(domain, token)
        finally:
            fediverse.revoke_token(domain, app.client_id, app.client_secret, token)
    except LOGIN_ERRORS as err:
        return login_failed(err)
    return sign_in("fediverse", profile)


def fediverse_app(domain, redirect_uri):
    app = db.session.get(FediverseApp, domain)
    if app is None or app.redirect_uri != redirect_uri:
        client_id, client_secret = fediverse.register_app(domain, redirect_uri)
        app = app or FediverseApp(domain=domain)
        app.redirect_uri, app.client_id, app.client_secret = redirect_uri, client_id, client_secret
        db.session.add(app)
        db.session.commit()
    return app


# --- Bluesky / AT Protocol ---------------------------------------------------------------------


@bp.post("/login/bluesky")
@limiter.limit(LOGIN_LIMIT)
def bluesky_start():
    try:
        client_id, redirect_uri = bluesky_client()
        identifier = atproto.clean_identifier(request.form.get("handle"))
        auth_url, pending = atproto.start_login(identifier, client_id, redirect_uri)
        save_pending(pending["state"], "bluesky", pending)
        return redirect(auth_url)
    except LOGIN_ERRORS as err:
        return login_failed(err)


@bp.get("/login/bluesky/callback")
def bluesky_callback():
    pending = take_pending("bluesky")
    try:
        code, issuer = request.args.get("code"), request.args.get("iss")
        if not code or not issuer:
            raise atproto.AtprotoError("The login didn't finish. Try again.")
        client_id, redirect_uri = bluesky_client()
        profile = atproto.finish_login(pending, code, issuer, client_id, redirect_uri)
    except LOGIN_ERRORS as err:
        return login_failed(err)
    return sign_in("bluesky", profile)


@bp.get("/oauth/client-metadata.json")
def bluesky_client_metadata():
    """atproto servers fetch this to learn about the app. Its URL is our client_id."""
    if not public_url():
        abort(404)
    client_id, redirect_uri = bluesky_client()
    return jsonify(atproto.client_metadata(client_id, redirect_uri, public_url()))


def bluesky_client():
    """Returns (client_id, redirect_uri).

    In production (PUBLIC_URL set) the client_id is the URL of our metadata file. In local
    development the atproto spec allows a special http://localhost client_id instead, as long
    as the redirect goes to 127.0.0.1.
    """
    base = public_url()
    if base:
        return base + url_for("auth.bluesky_client_metadata"), external_url("auth.bluesky_callback")
    if request.host.split(":")[0] != "127.0.0.1":
        raise atproto.AtprotoError(
            "For local Bluesky logins, open the game at http://127.0.0.1 instead of localhost, "
            "or set PUBLIC_URL."
        )
    redirect_uri = f"http://{request.host}{url_for('auth.bluesky_callback')}"
    return atproto.localhost_client_id(redirect_uri), redirect_uri


# --- Shared helpers ----------------------------------------------------------------------------


def public_url():
    return (current_app.config.get("PUBLIC_URL") or "").rstrip("/")


def external_url(endpoint):
    base = public_url()
    return base + url_for(endpoint) if base else url_for(endpoint, _external=True)


def save_pending(state, provider, data):
    db.session.execute(
        db.delete(PendingLogin).where(PendingLogin.created_at < utcnow() - PENDING_LOGIN_TTL)
    )
    db.session.add(PendingLogin(state=state, provider=provider, data=data))
    db.session.commit()
    # Tie the login to this browser, so nobody can trick you into finishing *their* login.
    session["login_state"] = state


def take_pending(provider):
    """Look up and delete the pending login the callback refers to, or bail out."""
    if request.args.get("error"):
        session.pop("login_state", None)
        flash("Login was cancelled.", "warning")
        abort(redirect(url_for("auth.login")))

    state = request.args.get("state")
    expected = session.pop("login_state", None)
    pending = db.session.get(PendingLogin, state) if state else None
    if pending is not None:
        db.session.delete(pending)
        db.session.commit()
    if (
        pending is None
        or not expected
        or not secrets.compare_digest(state, expected)
        or pending.provider != provider
        or pending.created_at < utcnow() - PENDING_LOGIN_TTL
    ):
        flash("That login link expired or wasn't yours. Try again.", "danger")
        abort(redirect(url_for("auth.login")))
    return pending.data


def sign_in(provider, profile):
    user = db.session.scalar(
        db.select(User).filter_by(provider=provider, subject=profile["subject"])
    )
    if user is None:
        user = User(provider=provider, subject=profile["subject"])
        db.session.add(user)
    user.username = profile["username"]
    user.display_name = profile.get("display_name")
    user.avatar_url = profile.get("avatar_url")
    db.session.commit()
    login_user(user)
    return redirect(url_for("game.index"))


def login_failed(err):
    current_app.logger.info("Login failed: %s", err)
    if isinstance(err, fediverse.FediverseError | atproto.AtprotoError):
        message = str(err)
    else:
        message = "Couldn't reach that server. Check the address and try again."
    flash(message, "danger")
    return redirect(url_for("auth.login"))
