import time
import uuid
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app import auth
from app.main import app

PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUBLIC_PEM = PRIVATE_KEY.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
).decode()
TOKENS = {"access_token": "a1", "refresh_token": "r1", "expires_in": 900}


@pytest.fixture(autouse=True)
def config(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "CONFIG", auth.Config(
        server_url="http://sso.test", client_id="yt-dl", client_secret="s3cret",
        app_url="http://app.test", public_key=PUBLIC_PEM, issuer="http://sso.test",
        state_db=tmp_path / "state.sqlite3",
    ))


@pytest.fixture
def client():
    return TestClient(app, base_url="http://app.test", follow_redirects=False)


def sign_in(client, monkeypatch, name="florent vasseur", uid=2, next="/", expires_in=900):
    monkeypatch.setattr(auth, "_token_request", lambda **_: {**TOKENS, "expires_in": expires_in})
    monkeypatch.setattr(auth.httpx, "get", lambda *a, **k: type("R", (), {
        "status_code": 200, "json": lambda self: {"id": uid, "name": name, "sub": "f@mail.com"}})())
    login = client.get("/auth/login", params={"next": next})
    state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]
    return client.get("/auth/callback", params={"code": "c", "state": state})


def logout_token(**overrides):
    claims = {
        "iss": "http://sso.test", "aud": "yt-dl", "iat": int(time.time()), "exp": int(time.time()) + 120,
        "jti": uuid.uuid4().hex, "sub": "f@mail.com", "uid": 2,
        "events": {auth.LOGOUT_EVENT: {}}, **overrides,
    }
    return jwt.encode(claims, PRIVATE_KEY, algorithm="RS256", headers={"typ": "logout+jwt"})


def test_api_requires_a_session(client):
    assert client.post("/api/probe", json={"url": "https://youtu.be/x"}).status_code == 401
    assert client.get("/api/me").status_code == 401


def test_health_and_pwa_files_stay_public(client):
    assert client.get("/api/health").status_code == 200
    assert client.get("/manifest.webmanifest").status_code == 200


def test_page_redirects_to_login_keeping_the_shared_link(client):
    response = client.get("/?url=https://youtu.be/x")
    assert response.status_code == 303
    assert response.headers["location"] == "/auth/login?next=%2F%3Furl%3Dhttps%3A%2F%2Fyoutu.be%2Fx"


def test_login_redirects_with_pkce_and_state(client):
    response = client.get("/auth/login")
    url = urlparse(response.headers["location"])
    query = parse_qs(url.query)
    assert url.netloc == "sso.test" and url.path == "/authorize"
    assert query["client_id"] == ["yt-dl"]
    assert query["redirect_uri"] == ["http://app.test/auth/callback"]
    assert query["code_challenge_method"] == ["S256"]
    assert "state" in query
    assert "httponly" in response.headers["set-cookie"].lower()


def test_login_ignores_an_external_next(client, monkeypatch):
    response = sign_in(client, monkeypatch, next="//evil.test/")
    assert response.headers["location"] == "/"


def test_callback_rejects_a_wrong_state(client):
    client.get("/auth/login")
    assert client.get("/auth/callback", params={"code": "c", "state": "forged"}).status_code == 400


def test_signed_in_user_gets_the_page_and_first_name(client, monkeypatch):
    response = sign_in(client, monkeypatch, next="/?url=x")
    assert response.headers["location"] == "/?url=x"
    assert client.get("/").status_code == 200
    assert client.get("/api/me").json() == {"first_name": "Florent"}


def test_session_id_changes_at_login(client, monkeypatch):
    client.get("/auth/login")
    before = client.cookies[auth.COOKIE]
    sign_in(client, monkeypatch)
    assert client.cookies[auth.COOKIE] != before


def test_expired_access_token_is_renewed(client, monkeypatch):
    sign_in(client, monkeypatch, expires_in=0)  # already due for renewal
    calls = []
    monkeypatch.setattr(auth, "_token_request", lambda **params: calls.append(params) or dict(TOKENS))
    assert client.get("/api/me").status_code == 200
    assert calls[0]["grant_type"] == "refresh_token"


def test_refused_renewal_closes_the_session(client, monkeypatch):
    sign_in(client, monkeypatch, expires_in=0)  # already due for renewal

    def refuse(**_):
        raise auth.OAuthError("invalid_grant")

    monkeypatch.setattr(auth, "_token_request", refuse)
    assert client.get("/api/me").status_code == 401
    monkeypatch.setattr(auth, "_token_request", lambda **_: dict(TOKENS))
    assert client.get("/api/me").status_code == 401


def test_backchannel_logout_closes_the_session(client, monkeypatch):
    sign_in(client, monkeypatch)
    response = client.post("/auth/backchannel-logout", data={"logout_token": logout_token()})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/api/me").status_code == 401


@pytest.mark.parametrize("overrides", [
    {"aud": "other-app"},
    {"iss": "http://evil.test"},
    {"events": {}},
    {"events": "not-a-dict"},
    {"nonce": "n"},
])
def test_backchannel_logout_rejects_bad_tokens(client, monkeypatch, overrides):
    sign_in(client, monkeypatch)
    response = client.post("/auth/backchannel-logout", data={"logout_token": logout_token(**overrides)})
    assert response.status_code == 400
    assert client.get("/api/me").status_code == 200


def test_logout_goes_through_the_sso_server(client, monkeypatch):
    sign_in(client, monkeypatch)
    session_id = client.cookies[auth.COOKIE]
    response = client.get("/auth/logout")
    assert response.headers["location"] == "http://sso.test/logout?redirect_uri=http%3A%2F%2Fapp.test%2F"
    client.cookies.set(auth.COOKIE, session_id)  # the old cookie is dead server-side
    assert client.get("/api/me").status_code == 401


@pytest.mark.parametrize("name, expected", [
    ("florent", "Florent"), ("Jean Dupont", "Jean"), ("", None), (None, None),
])
def test_first_name(name, expected):
    assert auth.first_name(name) == expected


@pytest.mark.parametrize("target", [
    "//evil.test/", "/\\evil.test", "/\\/evil.test", "https://evil.test", "/\t/evil.test", "evil",
])
def test_safe_next_refuses_other_sites(target):
    assert auth.safe_next(target) == "/"


def test_safe_next_keeps_local_paths():
    assert auth.safe_next("/?url=https://youtu.be/x") == "/?url=https://youtu.be/x"


def test_abandoned_login_expires_quickly(client, monkeypatch):
    client.get("/auth/login")
    session_id = client.cookies.get(auth.COOKIE)
    assert auth.load_session(session_id) is not None
    later = time.time() + auth.PENDING_LIFETIME + 1
    monkeypatch.setattr(auth.time, "time", lambda: later)
    assert auth.load_session(session_id) is None


def test_jobs_are_private_to_their_owner(client, monkeypatch):
    from app.jobs import registry

    sign_in(client, monkeypatch, uid=2)
    job = registry.create(owner=3)
    try:
        assert client.get(f"/api/jobs/{job.id}").status_code == 404
        mine = registry.create(owner=2)
        assert client.get(f"/api/jobs/{mine.id}").status_code == 200
        registry.remove(mine.id)
    finally:
        registry.remove(job.id)


def test_token_calls_use_the_internal_url(monkeypatch):
    monkeypatch.setattr(auth, "CONFIG", auth.Config(**{**auth.CONFIG.__dict__, "internal_url": "http://php:8080"}))
    seen = []
    monkeypatch.setattr(auth.httpx, "post", lambda url, **_: seen.append(url) or type("R", (), {
        "status_code": 200, "raise_for_status": lambda self: None, "json": lambda self: TOKENS})())
    auth._token_request(grant_type="refresh_token", refresh_token="r")
    assert seen == ["http://php:8080/token"]
    assert auth.authorization_request()[0].startswith("http://sso.test/authorize?")


def test_client_secret_can_come_from_a_file(tmp_path, monkeypatch):
    (tmp_path / "secret").write_text("from-file\n")
    monkeypatch.setenv("OAUTH_CLIENT_SECRET_FILE", str(tmp_path / "secret"))
    monkeypatch.delenv("OAUTH_CLIENT_SECRET", raising=False)
    assert auth._secret("OAUTH_CLIENT_SECRET") == "from-file"
