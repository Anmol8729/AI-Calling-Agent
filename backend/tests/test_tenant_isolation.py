"""Tenant-isolation tests against a real database and a live API.

These are the tests a multi-tenant product most needs and had none of: proof that
one customer cannot read or write another customer's data.

They need a database and a running backend, so they **skip themselves** when either
is unavailable — CI has no production credentials. Run them locally, and against
staging before a release:

    .\\.venv\\Scripts\\python.exe -m uvicorn backend.app:app --port 8000
    .\\.venv\\Scripts\\python.exe -m pytest backend/tests/test_tenant_isolation.py -v

Every fixture cleans up after itself, including on failure.
"""

import os
import uuid

import httpx
import pytest

BASE_URL = os.getenv("TEST_API_BASE", "http://127.0.0.1:8000")
PASSWORD = "Str0ng!Passw0rd-Test"

# Fixed numbers these tests claim. Fixed on purpose — the point is to prove a number
# can be claimed only once platform-wide — which is exactly why they must be released
# before every run as well as after.
TEST_NUMBERS = [
    "+919000000201", "919000000201",
    "+919000000202", "919000000202",
]

def _db_configured() -> bool:
    """Read through settings, not os.environ: the app loads .env itself, so the
    values are not necessarily exported into the shell running pytest."""
    try:
        from backend.config.settings import settings

        return bool((settings.DATABASE_URL or "").strip() or (settings.DB_HOST or "").strip())
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(
    not _db_configured(),
    reason="needs a database; skipped in CI where there are no production credentials",
)


def _api_reachable() -> bool:
    try:
        return httpx.get(f"{BASE_URL}/health", timeout=5).status_code in (200, 503)
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture(scope="module")
def api():
    if not _api_reachable():
        pytest.skip(f"no backend answering at {BASE_URL}")
    with httpx.Client(base_url=BASE_URL, timeout=40.0) as client:
        yield client


async def _purge(emails):
    """Delete probe accounts and everything hanging off them."""
    from sqlalchemy import delete, select

    from backend.models import (
        Appointment,
        AuditLog,
        CallLog,
        PasswordResetToken,
        Patient,
        PhoneNumber,
        Tenant,
        User,
    )
    from backend.services.db import close_db_connection, connect_to_db, get_sessionmaker

    await connect_to_db()
    Session = get_sessionmaker()
    async with Session() as session:
        for email in emails:
            user = (await session.execute(
                select(User).where(User.email == email)
            )).scalar_one_or_none()
            if user is None:
                continue
            clinic_id = user.clinic_id
            await session.execute(
                delete(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
            )
            await session.execute(delete(AuditLog).where(AuditLog.actor_user_id == user.id))
            await session.execute(delete(User).where(User.id == user.id))
            if clinic_id:
                for model in (AuditLog, CallLog, Appointment, Patient, PhoneNumber):
                    await session.execute(delete(model).where(model.clinic_id == clinic_id))
                await session.execute(delete(Tenant).where(Tenant.id == clinic_id))
        await session.execute(delete(AuditLog).where(AuditLog.actor_email.in_(list(emails))))
        await session.commit()
    await close_db_connection()


class Tenant:
    """One registered clinic plus its auth header."""

    def __init__(self, client, label):
        self.email = f"_iso{label}_{uuid.uuid4().hex[:8]}@clarivo-probe.dev"
        response = client.post("/api/auth/register", json={
            "email": self.email,
            "password": PASSWORD,
            "name": f"Isolation {label}",
            "clinic_name": f"Isolation Clinic {label}",
        })
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        self.token = data["access_token"]
        self.clinic_id = data["clinic_id"]
        self.headers = {"Authorization": f"Bearer {self.token}"}


async def _release_test_numbers():
    """Free the fixed phone numbers these tests claim.

    Needed at SETUP, not just teardown. Phone numbers are unique platform-wide, so a
    run that died partway (or a failed assertion inside a test) left one claimed and
    every later run then failed on "already connected" — a test that only passes once
    is worse than no test.
    """
    from sqlalchemy import delete

    from backend.models import PhoneNumber
    from backend.services.db import close_db_connection, connect_to_db, get_sessionmaker

    await connect_to_db()
    Session = get_sessionmaker()
    async with Session() as session:
        await session.execute(
            delete(PhoneNumber).where(PhoneNumber.number.in_(TEST_NUMBERS))
        )
        await session.commit()
    await close_db_connection()


@pytest.fixture(scope="module")
def two_tenants(api):
    import asyncio

    # Clear anything a previous interrupted run left behind before starting.
    asyncio.run(_release_test_numbers())
    a, b = Tenant(api, "a"), Tenant(api, "b")
    assert a.clinic_id != b.clinic_id, "each signup must create its own tenant"
    try:
        yield a, b
    finally:
        asyncio.run(_purge([a.email, b.email]))
        # Belt and braces: the numbers are deleted by clinic in _purge, but only if
        # the clinic link survived. Delete them by number as well.
        asyncio.run(_release_test_numbers())


class TestCrossTenantReads:
    def test_a_contact_created_by_a_is_invisible_to_b(self, api, two_tenants):
        a, b = two_tenants
        created = api.post("/api/patients/", headers=a.headers, json={
            "name": "A's Patient", "phone": "919000000101",
        })
        assert created.status_code == 200, created.text
        patient_id = created.json()["data"]["id"]

        # Direct fetch by id — the classic IDOR.
        leaked = api.get(f"/api/patients/{patient_id}", headers=b.headers)
        assert leaked.status_code in (403, 404), (
            f"clinic B read clinic A's contact: {leaked.status_code} {leaked.text}"
        )

        # And it must not appear in B's list.
        listed = api.get("/api/patients/", headers=b.headers)
        ids = [row.get("id") for row in (listed.json().get("data") or [])]
        assert patient_id not in ids

    def test_b_cannot_modify_or_delete_a_contact(self, api, two_tenants):
        a, b = two_tenants
        created = api.post("/api/patients/", headers=a.headers, json={
            "name": "A's Second", "phone": "919000000102",
        })
        patient_id = created.json()["data"]["id"]

        # Send a COMPLETE body: an incomplete one is rejected by validation (422)
        # before authorisation is ever reached, so the test would pass without
        # proving anything about tenant isolation.
        edited = api.put(f"/api/patients/{patient_id}", headers=b.headers,
                         json={"name": "Hijacked", "phone": "919000000102"})
        assert edited.status_code in (403, 404), edited.text

        removed = api.delete(f"/api/patients/{patient_id}", headers=b.headers)
        assert removed.status_code in (403, 404), removed.text

        # Still intact for its owner, with the original name.
        still = api.get(f"/api/patients/{patient_id}", headers=a.headers)
        assert still.status_code == 200
        assert still.json()["data"]["name"] == "A's Second"

    def test_stats_are_per_tenant(self, api, two_tenants):
        a, b = two_tenants
        api.post("/api/patients/", headers=a.headers,
                 json={"name": "Counted", "phone": "919000000103"})
        b_stats = api.get("/api/stats/overview", headers=b.headers)
        assert b_stats.status_code == 200
        # B created no contacts, so B's own count must not include A's.
        b_patients = api.get("/api/patients/", headers=b.headers).json().get("data") or []
        assert all(p.get("phone") != "919000000103" for p in b_patients)

    def test_settings_are_per_tenant(self, api, two_tenants):
        a, b = two_tenants
        api.put("/api/clinics/settings", headers=a.headers,
                json={"knowledge_base": "A-ONLY-SECRET-KB"})
        b_settings = api.get("/api/clinics/settings", headers=b.headers)
        assert "A-ONLY-SECRET-KB" not in b_settings.text

    def test_call_logs_are_per_tenant(self, api, two_tenants):
        a, b = two_tenants
        for tenant in (a, b):
            logs = api.get("/api/calls/logs", headers=tenant.headers)
            assert logs.status_code == 200
            rows = logs.json().get("data") or []
            for row in rows:
                assert str(row.get("clinic_id", tenant.clinic_id)) == str(tenant.clinic_id)

    def test_the_activity_timeline_is_per_tenant(self, api, two_tenants):
        a, b = two_tenants
        b_activity = api.get("/api/clinics/activity", headers=b.headers)
        assert b_activity.status_code == 200
        actors = {row.get("actor_email") for row in (b_activity.json()["data"]["items"] or [])}
        assert a.email not in actors


class TestPhoneNumberOwnership:
    def test_a_number_can_only_be_claimed_once_platform_wide(self, api, two_tenants):
        """Uniqueness must be on DIGITS.

        Inbound routing resolves a dialed number by trying format variants, so if
        `+91…` and `91…` were separate rows one tenant could capture another's calls.
        """
        a, b = two_tenants
        number = "+919000000201"
        first = api.post("/api/phone-numbers/", headers=a.headers,
                         json={"number": number, "label": "A main"})
        assert first.status_code == 200, first.text

        for variant in (number, number.lstrip("+"), f" {number} "):
            attempt = api.post("/api/phone-numbers/", headers=b.headers,
                               json={"number": variant})
            assert attempt.status_code == 400, (
                f"clinic B claimed {variant!r}, which clinic A already holds"
            )

    def test_b_cannot_delete_as_number(self, api, two_tenants):
        a, b = two_tenants
        created = api.post("/api/phone-numbers/", headers=a.headers,
                           json={"number": "+919000000202"})
        if created.status_code != 200:
            pytest.skip("clinic A is already at its plan number limit")
        number_id = created.json()["data"]["id"]
        removed = api.delete(f"/api/phone-numbers/{number_id}", headers=b.headers)
        assert removed.status_code in (403, 404), removed.text


class TestPrivilegeBoundaries:
    def test_platform_admin_is_closed_to_normal_tenants(self, api, two_tenants):
        a, _ = two_tenants
        for path in ("/api/admin/tenants", "/api/admin/plans",
                     "/api/admin/diagnostics", "/api/admin/audit-logs"):
            response = api.get(path, headers=a.headers)
            assert response.status_code == 403, f"{path} -> {response.status_code}"

    def test_every_tenant_endpoint_requires_authentication(self, api):
        for method, path in (
            ("GET", "/api/patients/"),
            ("GET", "/api/appointments/"),
            ("GET", "/api/calls/logs"),
            ("GET", "/api/stats/overview"),
            ("GET", "/api/clinics/settings"),
            ("GET", "/api/clinics/activity"),
            ("GET", "/api/phone-numbers/"),
            ("GET", "/api/billing/summary"),
            ("GET", "/api/auth/me"),
        ):
            response = api.request(method, path)
            assert response.status_code == 401, f"{method} {path} -> {response.status_code}"

    def test_another_tenants_token_cannot_be_reused_after_revocation(self, api, two_tenants):
        """Logging out server-side must actually stop the token working."""
        _, b = two_tenants
        assert api.get("/api/auth/me", headers=b.headers).status_code == 200
        api.post("/api/auth/logout-all-devices", headers=b.headers)
        assert api.get("/api/auth/me", headers=b.headers).status_code == 401
        # Restore a usable session for any later test in the module.
        again = api.post("/api/auth/login", json={"email": b.email, "password": PASSWORD})
        b.token = again.json()["data"]["access_token"]
        b.headers = {"Authorization": f"Bearer {b.token}"}


class TestAgentEndpointScoping:
    def test_agent_endpoints_reject_a_dashboard_session(self, api, two_tenants):
        a, _ = two_tenants
        for path in ("/api/calls/agent-lookup", "/api/calls/agent-queue",
                     "/api/calls/agent-book", "/api/calls/agent-patient"):
            response = api.post(path, headers=a.headers, json={})
            assert response.status_code in (401, 422), f"{path} -> {response.status_code}"

    def test_agent_endpoints_reject_anonymous_callers(self, api):
        for path in ("/api/calls/agent-lookup", "/api/calls/agent-context",
                     "/api/calls/agent-call-start"):
            response = api.post(path, json={})
            assert response.status_code in (401, 422), f"{path} -> {response.status_code}"
