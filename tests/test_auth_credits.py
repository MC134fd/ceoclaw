"""
Phase 5 — Auth + Credits test suite.

Coverage:
1) Auth tests: missing / invalid / expired token handling
2) Ownership tests: user A cannot access user B's session
3) Credits tests: deduct success, insufficient block, ledger row
4) Integration tests: session linked to user, list filtered by user
"""

import time
import sys
from pathlib import Path

import jwt
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TEST_JWT_SECRET = "test-jwt-secret-for-auth-unit-tests-only"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token(
    user_id: str,
    email: str,
    exp_offset: int = 3600,
    secret: str = TEST_JWT_SECRET,
    audience: str = "authenticated",
) -> str:
    """Produce a minimal Supabase-style HS256 JWT."""
    now = int(time.time())
    payload = {
        "sub": user_id,
        "email": email,
        "aud": audience,
        "iat": now,
        "exp": now + exp_offset,
        "user_metadata": {"full_name": "Test User"},
        "app_metadata": {"provider": "google"},
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Each test gets a fresh DB and auth-enabled settings.

    load_dotenv(override=True) in Settings.__init__ would clobber monkeypatched
    env vars, so we patch the settings attributes directly after construction.
    """
    import config.settings as cs

    # Build a fresh settings object, then override the attributes we care about
    # so that dotenv values in .env cannot win over our test values.
    new_settings = cs.Settings()
    new_settings.database_path = str(tmp_path / "auth_test.db")
    new_settings.auth_required = True
    new_settings.credits_enforced = True
    new_settings.supabase_jwt_secret = TEST_JWT_SECRET
    new_settings.free_tier_credits = 5
    cs.settings = new_settings

    from data.database import init_db
    init_db()
    yield

    # Reset to a clean anonymous settings so other test suites are unaffected
    reset_settings = cs.Settings()
    reset_settings.auth_required = False
    reset_settings.credits_enforced = False
    cs.settings = reset_settings


@pytest.fixture()
def client():
    from api.server import app
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1) Auth tests
# ---------------------------------------------------------------------------


class TestAuthRejection:
    def test_missing_token_rejected_on_builder_sessions(self, client):
        """No token → 401 when AUTH_REQUIRED=true."""
        resp = client.get("/builder/sessions")
        assert resp.status_code == 401

    def test_missing_token_rejected_on_account_me(self, client):
        resp = client.get("/account/me")
        assert resp.status_code == 401

    def test_invalid_token_rejected(self, client):
        resp = client.get("/builder/sessions", headers={"Authorization": "Bearer not.a.real.token"})
        assert resp.status_code == 401

    def test_wrong_secret_rejected(self, client):
        token = _make_token("uid-1", "a@b.com", secret="wrong-secret")
        resp = client.get("/builder/sessions", headers=_auth(token))
        assert resp.status_code == 401

    def test_expired_token_rejected(self, client):
        token = _make_token("uid-1", "a@b.com", exp_offset=-10)
        resp = client.get("/builder/sessions", headers=_auth(token))
        assert resp.status_code == 401

    def test_wrong_audience_rejected(self, client):
        token = _make_token("uid-1", "a@b.com", audience="service_role")
        resp = client.get("/builder/sessions", headers=_auth(token))
        assert resp.status_code == 401

    def test_valid_token_accepted(self, client):
        token = _make_token("uid-good", "good@test.com")
        resp = client.get("/builder/sessions", headers=_auth(token))
        assert resp.status_code == 200

    def test_valid_token_upserts_user(self, client):
        """A valid JWT causes the user row to be created in the local DB."""
        from data.database import get_user_by_id
        token = _make_token("uid-upsert", "upsert@test.com")
        client.get("/builder/sessions", headers=_auth(token))
        user = get_user_by_id("uid-upsert")
        assert user is not None
        assert user["email"] == "upsert@test.com"

    def test_valid_token_seeds_credits(self, client):
        """First sign-in gives the user their free credit allocation."""
        from data.database import get_user_credits
        token = _make_token("uid-credits", "credits@test.com")
        client.get("/builder/sessions", headers=_auth(token))
        credits = get_user_credits("uid-credits")
        assert credits["balance"] == 5  # FREE_TIER_CREDITS=5 in fixture


# ---------------------------------------------------------------------------
# 2) Ownership tests
# ---------------------------------------------------------------------------


class TestSessionOwnership:
    def _create_session_for_user(self, user_id: str, email: str) -> str:
        """Insert a session owned by user_id directly in the DB."""
        from data.database import upsert_chat_session, upsert_user, ensure_default_subscription_and_credits
        import uuid
        upsert_user(user_id, email)
        ensure_default_subscription_and_credits(user_id, free_credits=10)
        session_id = str(uuid.uuid4())
        upsert_chat_session(session_id, slug="test-slug", owner_user_id=user_id)
        return session_id

    def test_owner_can_read_session_messages(self, client):
        session_id = self._create_session_for_user("owner-uid", "owner@test.com")
        token = _make_token("owner-uid", "owner@test.com")
        resp = client.get(
            f"/builder/sessions/{session_id}/messages", headers=_auth(token)
        )
        assert resp.status_code == 200

    def test_other_user_cannot_read_session_messages(self, client):
        session_id = self._create_session_for_user("owner-uid2", "owner2@test.com")
        token = _make_token("attacker-uid", "attacker@test.com")
        resp = client.get(
            f"/builder/sessions/{session_id}/messages", headers=_auth(token)
        )
        assert resp.status_code == 403

    def test_other_user_cannot_delete_session(self, client):
        session_id = self._create_session_for_user("owner-uid3", "owner3@test.com")
        token = _make_token("attacker-uid2", "attacker2@test.com")
        resp = client.delete(
            f"/builder/sessions/{session_id}", headers=_auth(token)
        )
        assert resp.status_code == 403

    def test_other_user_cannot_list_versions(self, client):
        session_id = self._create_session_for_user("owner-uid4", "owner4@test.com")
        token = _make_token("attacker-uid3", "attacker3@test.com")
        resp = client.get(
            f"/builder/sessions/{session_id}/versions", headers=_auth(token)
        )
        assert resp.status_code == 403

    def test_session_list_filtered_by_user(self, client):
        """GET /builder/sessions returns only the requesting user's sessions."""
        s1 = self._create_session_for_user("user-a", "a@test.com")
        _s2 = self._create_session_for_user("user-b", "b@test.com")

        token_a = _make_token("user-a", "a@test.com")
        resp = client.get("/builder/sessions", headers=_auth(token_a))
        assert resp.status_code == 200
        ids = [s["session_id"] for s in resp.json()]
        assert s1 in ids
        assert _s2 not in ids


# ---------------------------------------------------------------------------
# 3) Credits tests (unit — directly via DB helpers)
# ---------------------------------------------------------------------------


class TestCreditsLogic:
    def _seed_user(self, user_id: str, balance: int) -> None:
        from data.database import ensure_default_subscription_and_credits, upsert_user
        from data.database import get_connection
        upsert_user(user_id, f"{user_id}@test.com")
        ensure_default_subscription_and_credits(user_id, free_credits=balance)

    def test_deduct_success(self):
        from data.database import deduct_credits, get_user_credits
        self._seed_user("deduct-ok", 5)
        result = deduct_credits("deduct-ok", 1, "generate_request", "sess-x")
        assert result["ok"] is True
        assert result["balance_before"] == 5
        assert result["balance_after"] == 4
        # Verify DB was updated
        assert get_user_credits("deduct-ok")["balance"] == 4

    def test_deduct_insufficient(self):
        from data.database import deduct_credits
        self._seed_user("deduct-fail", 0)
        result = deduct_credits("deduct-fail", 1, "generate_request")
        assert result["ok"] is False
        assert result["balance"] == 0
        assert result["required"] == 1

    def test_deduct_writes_ledger_row(self):
        from data.database import deduct_credits, get_credit_ledger
        self._seed_user("ledger-user", 5)
        deduct_credits("ledger-user", 1, "generate_request", "my-session")
        ledger = get_credit_ledger("ledger-user")
        usage = [e for e in ledger if e["delta"] < 0]
        assert len(usage) == 1
        assert usage[0]["delta"] == -1
        assert usage[0]["reason"] == "generate_request"
        assert usage[0]["ref_session_id"] == "my-session"

    def test_initial_grant_in_ledger(self):
        """ensure_default_subscription_and_credits writes an initial_grant row."""
        from data.database import get_credit_ledger
        self._seed_user("grant-user", 5)
        ledger = get_credit_ledger("grant-user")
        grants = [e for e in ledger if e["reason"] == "initial_grant"]
        assert len(grants) == 1
        assert grants[0]["delta"] == 5

    def test_deduct_idempotent_no_double_deduct(self):
        """Two concurrent-style calls: only the second fails if balance = 1."""
        from data.database import deduct_credits
        self._seed_user("race-user", 1)
        r1 = deduct_credits("race-user", 1, "generate_request")
        r2 = deduct_credits("race-user", 1, "generate_request")
        assert r1["ok"] is True
        assert r2["ok"] is False


# ---------------------------------------------------------------------------
# 4) Credits enforcement via API
# ---------------------------------------------------------------------------


class TestCreditsEnforcement:
    def test_credits_enforced_returns_402(self, client):
        """With CREDITS_ENFORCED=true and balance=0, generation returns 402."""
        from data.database import upsert_user, ensure_default_subscription_and_credits
        upsert_user("broke-user", "broke@test.com")
        ensure_default_subscription_and_credits("broke-user", free_credits=0)

        token = _make_token("broke-user", "broke@test.com")
        resp = client.post(
            "/builder/generate",
            json={"session_id": "sess-broke", "message": "build me something", "mock_mode": True},
            headers=_auth(token),
        )
        assert resp.status_code == 402
        body = resp.json()
        assert body["detail"]["error"] == "insufficient_credits"

    def test_credits_decremented_on_successful_generate(self, client):
        """Successful /builder/generate start decrements balance by 1."""
        from data.database import upsert_user, ensure_default_subscription_and_credits, get_user_credits
        upsert_user("rich-user", "rich@test.com")
        ensure_default_subscription_and_credits("rich-user", free_credits=5)

        token = _make_token("rich-user", "rich@test.com")
        resp = client.post(
            "/builder/generate",
            json={"session_id": "sess-rich", "message": "build me something", "mock_mode": True},
            headers=_auth(token),
        )
        # Either job started (200) or clarification needed (200) — not 402
        assert resp.status_code == 200
        credits = get_user_credits("rich-user")
        assert credits["balance"] == 4  # 1 credit consumed

    def test_generate_response_includes_credits_meta(self, client):
        """Job start response includes credits_before, credits_after, cost, tier."""
        from data.database import upsert_user, ensure_default_subscription_and_credits
        upsert_user("meta-user", "meta@test.com")
        ensure_default_subscription_and_credits("meta-user", free_credits=5)

        token = _make_token("meta-user", "meta@test.com")
        resp = client.post(
            "/builder/generate",
            json={"session_id": "sess-meta", "message": "build me something", "mock_mode": True},
            headers=_auth(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        # Clarification check may return early without credits field
        if "credits" in body:
            c = body["credits"]
            assert "credits_before" in c
            assert "credits_after" in c
            assert c["cost"] == 1
            assert c["tier"] == "free"


# ---------------------------------------------------------------------------
# 5) Account endpoints
# ---------------------------------------------------------------------------


class TestAccountEndpoints:
    def test_account_me_returns_user(self, client):
        token = _make_token("me-user", "me@test.com")
        resp = client.get("/account/me", headers=_auth(token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["email"] == "me@test.com"
        assert "tier" in body

    def test_account_credits_returns_balance(self, client):
        token = _make_token("cred-user", "cred@test.com")
        # Trigger user creation via /account/me first
        client.get("/account/me", headers=_auth(token))
        resp = client.get("/account/credits", headers=_auth(token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["balance"] == 5  # FREE_TIER_CREDITS=5
        assert body["cost_per_generation"] == 1

    def test_account_subscription_returns_tier(self, client):
        token = _make_token("sub-user", "sub@test.com")
        client.get("/account/me", headers=_auth(token))
        resp = client.get("/account/subscription", headers=_auth(token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["tier"] == "free"
        assert body["status"] == "active"
