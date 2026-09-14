"""Tests for user authentication, password hashing, session tokens, and dashboard routing."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from orderorder.web.api import create_app
from orderorder.web.security import (
    SESSION_COOKIE_NAME,
    hash_password,
    validate_password_strength,
    verify_password,
)


@pytest.fixture
def client(corpus):
    # The chambers surface -- landing, sign-in, guarded dashboard -- is off by default; these
    # tests turn it on, so every route and the guard keep being exercised even while the default
    # surface serves the working tool directly at /.
    with TestClient(create_app(session_factory=corpus, chambers_auth=True)) as c:
        yield c


def test_password_hashing_and_verification():
    raw = "AdvocatePassword123!"
    hashed = hash_password(raw)
    assert hashed.startswith("scrypt$16384$8$1$")
    assert verify_password(raw, hashed)
    assert not verify_password("WrongPassword123!", hashed)
    assert not verify_password("", hashed)


def test_password_strength():
    assert validate_password_strength("short") is not None
    assert validate_password_strength("validpassword123") is None


def test_register_and_login_flow(client: TestClient):
    # 1. Register account
    reg_resp = client.post(
        "/api/auth/register",
        json={
            "email": "advocate.sharma@chambers.in",
            "password": "SecurePassword123!",
            "full_name": "Adv. Priya Sharma",
        },
    )
    assert reg_resp.status_code == 200
    reg_data = reg_resp.json()
    assert reg_data["ok"] is True
    assert reg_data["user"]["email"] == "advocate.sharma@chambers.in"
    assert reg_data["user"]["full_name"] == "Adv. Priya Sharma"
    assert SESSION_COOKIE_NAME in reg_resp.cookies

    # 2. Check /api/auth/me with active session
    me_resp = client.get("/api/auth/me")
    assert me_resp.status_code == 200
    assert me_resp.json()["user"]["email"] == "advocate.sharma@chambers.in"

    # 3. Access /dashboard while authenticated
    dash_resp = client.get("/dashboard", follow_redirects=False)
    assert dash_resp.status_code == 200

    # 4. Logout
    logout_resp = client.post("/api/auth/logout")
    assert logout_resp.status_code == 200

    # 5. Check /api/auth/me after logout
    unauthed_me = client.get("/api/auth/me")
    assert unauthed_me.status_code == 401

    # 6. Check /dashboard redirects to login after logout
    redir_resp = client.get("/dashboard", follow_redirects=False)
    assert redir_resp.status_code == 303
    assert "/login?next=/dashboard" in redir_resp.headers["location"]

    # 7. Login again with registered credentials
    login_resp = client.post(
        "/api/auth/login",
        json={
            "email": "advocate.sharma@chambers.in",
            "password": "SecurePassword123!",
        },
    )
    assert login_resp.status_code == 200
    assert login_resp.json()["ok"] is True
    assert SESSION_COOKIE_NAME in login_resp.cookies

    # 8. Login with invalid password
    bad_login = client.post(
        "/api/auth/login",
        json={
            "email": "advocate.sharma@chambers.in",
            "password": "WrongPassword999!",
        },
    )
    assert bad_login.status_code == 401


def test_landing_and_login_pages_served(client: TestClient):
    landing_resp = client.get("/")
    assert landing_resp.status_code == 200
    assert "text/html" in landing_resp.headers["content-type"]
    assert "Ruchi" in landing_resp.text

    login_resp = client.get("/login")
    assert login_resp.status_code == 200
    assert "text/html" in login_resp.headers["content-type"]
    assert "Sign In" in login_resp.text

    # Static assets for landing and login
    for asset in ("/landing.css", "/landing.js", "/login.css", "/login.js"):
        resp = client.get(asset)
        assert resp.status_code == 200, asset
