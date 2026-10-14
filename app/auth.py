"""Access control through the SSO server (OAuth2, "backend for frontend" model).

The browser only ever holds an opaque session cookie. Tokens, the client secret
and the revocation registry stay here, in a small SQLite file:

- login: Authorization Code + PKCE + state, identity read from /api/userinfo;
- on every protected request: session revoked by back-channel logout? access
  token to renew? A refused renewal closes the session (fail-closed);
- POST /auth/backchannel-logout: the SSO server tells us a user must go.

Authentication is off when OAUTH_SERVER_URL is not set, so the app still runs
as a plain local tool.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlsplit

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

COOKIE = "ytdl_session"
SESSION_LIFETIME = 7 * 24 * 3600
# A login left half-way (no user yet) is only kept this long: /auth/login is
# public, so these rows must not pile up.
PENDING_LIFETIME = 10 * 60
LOGOUT_EVENT = "http://schemas.openid.net/event/backchannel-logout"


@dataclass(frozen=True)
class Config:
    server_url: str  # as seen by the browser: /authorize, /logout
    client_id: str
    client_secret: str
    app_url: str
    public_key: str
    issuer: str
    state_db: Path
    # Server-to-server calls (/token, /api/userinfo). Differs from server_url
    # when both run in Docker: e.g. http://php:8080 on the shared network.
    internal_url: str = ""

    @property
    def backend_url(self) -> str:
        return self.internal_url or self.server_url

    @property
    def redirect_uri(self) -> str:
        return f"{self.app_url}/auth/callback"

    @property
    def secure_cookie(self) -> bool:
        return self.app_url.startswith("https://")


def load_config() -> Config | None:
    server_url = os.environ.get("OAUTH_SERVER_URL", "").rstrip("/")
    if not server_url:
        return None
    return Config(
        server_url=server_url,
        client_id=os.environ["OAUTH_CLIENT_ID"],
        client_secret=_secret("OAUTH_CLIENT_SECRET"),
        app_url=os.environ["APP_URL"].rstrip("/"),
        public_key=Path(os.environ["OAUTH_PUBLIC_KEY_FILE"]).read_text(),
        issuer=os.environ.get("OAUTH_ISSUER", server_url),
        state_db=Path(os.environ.get("OAUTH_STATE_DB", "var/oauth_state.sqlite3")),
        internal_url=os.environ.get("OAUTH_INTERNAL_URL", "").rstrip("/"),
    )


def _secret(name: str) -> str:
    """NAME, or the content of the file NAME_FILE (Docker secrets)."""
    path = os.environ.get(f"{name}_FILE")
    return Path(path).read_text().strip() if path else os.environ[name]


def auth_required() -> bool:
    """REQUIRE_LOGIN=1 forbids running without the SSO server (fail closed)."""
    return os.environ.get("REQUIRE_LOGIN", "").lower() in ("1", "true", "yes")


CONFIG = load_config()


class OAuthError(Exception):
    """The SSO server refused (invalid code, access removed, account blocked…)."""


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _db() -> sqlite3.Connection:
    CONFIG.state_db.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(CONFIG.state_db, timeout=15, isolation_level=None)
    db.execute("CREATE TABLE IF NOT EXISTS sessions (key TEXT PRIMARY KEY, data TEXT, updated_at REAL)")
    db.execute("CREATE INDEX IF NOT EXISTS sessions_updated_at ON sessions (updated_at)")
    db.execute("CREATE TABLE IF NOT EXISTS revocations (uid INTEGER PRIMARY KEY, revoked_at REAL)")
    db.execute("CREATE TABLE IF NOT EXISTS refreshes (old_token TEXT PRIMARY KEY, tokens TEXT, created_at REAL)")
    return db


# --- Server-side sessions: the cookie is a random id, only its hash is stored ---


def _key(session_id: str) -> str:
    return hashlib.sha256(session_id.encode()).hexdigest()


def load_session(session_id: str | None) -> dict | None:
    if not session_id:
        return None
    db = _db()
    now = time.time()
    row = db.execute(
        "SELECT data FROM sessions WHERE key = ? AND updated_at > ?"
        " AND (json_extract(data, '$.user') IS NOT NULL OR updated_at > ?)",
        (_key(session_id), now - SESSION_LIFETIME, now - PENDING_LIFETIME),
    ).fetchone()
    db.close()
    return json.loads(row[0]) if row else None


def save_session(session_id: str, data: dict) -> None:
    db = _db()
    db.execute("INSERT OR REPLACE INTO sessions VALUES (?, ?, ?)", (_key(session_id), json.dumps(data), time.time()))
    now = time.time()
    db.execute(
        "DELETE FROM sessions WHERE updated_at < ?"
        " OR (json_extract(data, '$.user') IS NULL AND updated_at < ?)",
        (now - SESSION_LIFETIME, now - PENDING_LIFETIME),
    )
    db.close()


def delete_session(session_id: str | None) -> None:
    if not session_id:
        return
    db = _db()
    db.execute("DELETE FROM sessions WHERE key = ?", (_key(session_id),))
    db.close()


def _set_cookie(response: Response, session_id: str) -> None:
    response.set_cookie(
        COOKIE, session_id, max_age=SESSION_LIFETIME, httponly=True,
        secure=CONFIG.secure_cookie, samesite="lax",
    )


# --- Login ---


def authorization_request() -> tuple[str, dict]:
    """URL of /authorize and the values to keep until the user comes back (state, PKCE)."""
    pending = {"state": _b64url(secrets.token_bytes(16)), "verifier": _b64url(secrets.token_bytes(48))}
    url = f"{CONFIG.server_url}/authorize?" + urlencode({
        "response_type": "code",
        "client_id": CONFIG.client_id,
        "redirect_uri": CONFIG.redirect_uri,
        "scope": "profile email",
        "state": pending["state"],
        "code_challenge": _b64url(hashlib.sha256(pending["verifier"].encode()).digest()),
        "code_challenge_method": "S256",
    })
    return url, pending


def _token_request(**params) -> dict:
    response = httpx.post(
        f"{CONFIG.backend_url}/token", timeout=10,
        data={"client_id": CONFIG.client_id, "client_secret": CONFIG.client_secret, **params},
    )
    if response.status_code in (400, 401):
        raise OAuthError(response.json().get("error", "refused"))
    response.raise_for_status()
    return response.json()


def finish_login(query: dict, pending: dict | None) -> tuple[dict, dict]:
    """Handle the redirect back: returns (user, tokens to keep server-side)."""
    if "error" in query:
        raise OAuthError(query["error"])
    if not pending or not secrets.compare_digest(query.get("state", ""), pending["state"]):
        raise OAuthError("invalid state")
    tokens = _token_request(
        grant_type="authorization_code", code=query.get("code", ""),
        redirect_uri=CONFIG.redirect_uri, code_verifier=pending["verifier"],
    )
    response = httpx.get(
        f"{CONFIG.backend_url}/api/userinfo", timeout=10,
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    if response.status_code != 200:
        raise OAuthError("userinfo refused")
    user = response.json()
    return {"id": user["id"], "name": user.get("name")}, _for_session(tokens)


def _for_session(tokens: dict) -> dict:
    lifetime = tokens["expires_in"]
    return {
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        # renew 30 s before expiry (at half-life for very short tokens)
        "refresh_at": time.time() + max(lifetime - 30, lifetime / 2),
    }


def first_name(name: str | None) -> str | None:
    """The SSO server only has a display name: its first word stands for the first name."""
    word = (name or "").split(maxsplit=1)
    return word[0][:1].upper() + word[0][1:] if word else None


# --- Layer 1: token renewal ---


def fresh_tokens(tokens: dict) -> dict:
    """Valid tokens, renewed when needed. OAuthError when the server refuses.

    A refresh token works only once: concurrent requests (tabs, the progress
    stream, a probe) share one renewal through a SQLite write lock.
    """
    if time.time() < tokens["refresh_at"]:
        return tokens
    old = tokens["refresh_token"]
    db = _db()
    try:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT tokens FROM refreshes WHERE old_token = ?", (old,)).fetchone()
        if row:
            new = json.loads(row[0])
        else:
            new = _for_session(_token_request(grant_type="refresh_token", refresh_token=old))
            db.execute("INSERT INTO refreshes VALUES (?, ?, ?)", (old, json.dumps(new), time.time()))
            db.execute("DELETE FROM refreshes WHERE created_at < ?", (time.time() - 60,))
        db.execute("COMMIT")
        return new
    except Exception:
        db.execute("ROLLBACK")
        raise
    finally:
        db.close()


# --- Layer 3: back-channel logout ---


def verify_logout_token(logout_token: str) -> int:
    """Check a logout token (OpenID Connect Back-Channel Logout 1.0), return the user's uid."""
    claims = jwt.decode(
        logout_token, CONFIG.public_key, algorithms=["RS256"], audience=CONFIG.client_id,
        issuer=CONFIG.issuer, leeway=60,
        options={"require": ["iss", "aud", "iat", "exp", "jti", "events", "uid"]},
    )
    events = claims["events"]
    if not isinstance(events, dict) or not isinstance(events.get(LOGOUT_EVENT), dict) or "nonce" in claims:
        raise jwt.InvalidTokenError("not a logout token")
    if abs(time.time() - claims["iat"]) > 300:
        raise jwt.InvalidTokenError("token too old")
    return int(claims["uid"])


def mark_revoked(uid: int) -> None:
    """Every session of this user opened before now becomes invalid."""
    db = _db()
    db.execute("INSERT OR REPLACE INTO revocations VALUES (?, ?)", (uid, time.time()))
    db.close()


def is_revoked(uid: int, logged_in_at: float) -> bool:
    db = _db()
    row = db.execute("SELECT revoked_at FROM revocations WHERE uid = ?", (uid,)).fetchone()
    db.close()
    return bool(row) and logged_in_at <= row[0]


# --- The check run on every protected request ---


def require_user(request: Request) -> dict | None:
    """The signed-in user, or 401. None when authentication is off."""
    if CONFIG is None:
        return None
    session_id = request.cookies.get(COOKIE)
    session = load_session(session_id)
    user = session.get("user") if session else None
    if not user:
        raise HTTPException(status_code=401, detail="Not signed in.")
    if is_revoked(user["id"], session["logged_in_at"]):
        delete_session(session_id)
        raise HTTPException(status_code=401, detail="Signed out by the authentication server.")
    try:
        tokens = fresh_tokens(session["tokens"])
    except Exception:
        delete_session(session_id)
        raise HTTPException(status_code=401, detail="Session closed by the authentication server.")
    if tokens is not session["tokens"]:
        save_session(session_id, {**session, "tokens": tokens})
    return user


def safe_next(target: str) -> str:
    """Keep a post-login target only if it is a path on this site.

    "//host" and "/\\host" both send browsers to another site, so does any
    control character they strip before parsing.
    """
    if (
        not target.startswith("/")
        or target.startswith("//")
        or "\\" in target
        or any(ord(c) < 0x20 or ord(c) == 0x7F for c in target)
    ):
        return "/"
    parts = urlsplit(target)
    return "/" if parts.scheme or parts.netloc else target


def login_redirect(request: Request) -> RedirectResponse:
    """Send a page request to the login, coming back to the same page afterwards."""
    target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    return RedirectResponse(f"/auth/login?next={quote(target, safe='')}", status_code=303)


# --- Routes ---

router = APIRouter()


def _error_page(message: str, status: int) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><meta charset=utf-8><title>yt-dl</title>"
        f"<p>{message}</p><p><a href='/auth/login'>Réessayer</a></p>",
        status_code=status,
    )


@router.get("/auth/login", include_in_schema=False)
def login(next: str = "/") -> Response:
    if CONFIG is None:
        return RedirectResponse("/", status_code=303)
    next = safe_next(next)
    url, pending = authorization_request()
    session_id = secrets.token_urlsafe(32)
    save_session(session_id, {"pending": pending, "next": next})
    response = RedirectResponse(url, status_code=303)
    _set_cookie(response, session_id)
    return response


@router.get("/auth/callback", include_in_schema=False)
def callback(request: Request) -> Response:
    if CONFIG is None:
        return RedirectResponse("/", status_code=303)
    old_id = request.cookies.get(COOKIE)
    session = load_session(old_id) or {}
    try:
        user, tokens = finish_login(dict(request.query_params), session.get("pending"))
    except (OAuthError, httpx.HTTPError):
        return _error_page("La connexion a échoué.", 400)
    # A fresh session id after login (protection against session fixation)
    delete_session(old_id)
    session_id = secrets.token_urlsafe(32)
    save_session(session_id, {"user": user, "tokens": tokens, "logged_in_at": time.time()})
    response = RedirectResponse(session.get("next", "/"), status_code=303)
    _set_cookie(response, session_id)
    return response


@router.get("/auth/logout", include_in_schema=False)
def logout(request: Request) -> Response:
    if CONFIG is None:
        return RedirectResponse("/", status_code=303)
    delete_session(request.cookies.get(COOKIE))
    url = f"{CONFIG.server_url}/logout?" + urlencode({"redirect_uri": f"{CONFIG.app_url}/"})
    response = RedirectResponse(url, status_code=303)
    response.delete_cookie(COOKIE)
    return response


@router.post("/auth/backchannel-logout", include_in_schema=False)
async def backchannel_logout(request: Request) -> Response:
    headers = {"Cache-Control": "no-store"}
    if CONFIG is None:
        return Response(status_code=404, headers=headers)
    form = parse_qs((await request.body()).decode())
    try:
        uid = verify_logout_token(form.get("logout_token", [""])[0])
    except jwt.PyJWTError as error:
        return Response(
            json.dumps({"error": "invalid_request", "error_description": str(error)}),
            status_code=400, media_type="application/json", headers=headers,
        )
    mark_revoked(uid)
    return Response("{}", media_type="application/json", headers=headers)


@router.get("/api/me")
def me(user: dict | None = Depends(require_user)) -> dict:
    return {"first_name": first_name(user["name"]) if user else None}
