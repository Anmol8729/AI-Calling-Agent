from backend.services import email as email_mod


class _FakeSMTP:
    """Records what the mailer did, so the TLS decision can be asserted without a
    real server. Doubles as SMTP and SMTP_SSL — which one was constructed is itself
    the thing under test."""

    instances: list = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host = host
        self.port = port
        self.context = context
        self.starttls_called = False
        self.logged_in_as = None
        self.sent = []
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        self.starttls_called = True

    def login(self, user, password):
        self.logged_in_as = user

    def send_message(self, msg):
        self.sent.append(msg)


def _patch(monkeypatch, **settings_values):
    _FakeSMTP.instances = []
    defaults = {
        "SMTP_HOST": "smtp.example.com",
        "SMTP_PORT": 587,
        "SMTP_USER": "mailer@example.com",
        "SMTP_PASSWORD": "secret",
        "SMTP_FROM": "Clarivo <no-reply@example.com>",
        "SMTP_TLS": True,
    }
    defaults.update(settings_values)
    for key, value in defaults.items():
        monkeypatch.setattr(email_mod.settings, key, value)
    monkeypatch.setattr(email_mod.smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setattr(email_mod.smtplib, "SMTP_SSL", _FakeSMTP)


def test_email_mock_mode_returns_false(monkeypatch):
    # With no SMTP host configured, send_email must not attempt delivery.
    monkeypatch.setattr(email_mod.settings, "SMTP_HOST", "")
    assert email_mod.send_email("recipient", "Subject", "Body") is False


def test_port_587_upgrades_with_starttls(monkeypatch):
    _patch(monkeypatch, SMTP_PORT=587)
    assert email_mod.send_email("to@example.com", "S", "B") is True
    conn = _FakeSMTP.instances[0]
    assert conn.starttls_called is True
    assert conn.logged_in_as == "mailer@example.com"
    assert len(conn.sent) == 1


def test_port_465_uses_implicit_tls_and_never_calls_starttls(monkeypatch):
    """465 is SMTPS: the socket is TLS from byte one. The old code always used
    smtplib.SMTP + starttls(), so a provider on 465 failed with an opaque error and
    the operator saw only "failed to send email"."""
    _patch(monkeypatch, SMTP_PORT=465)
    assert email_mod.send_email("to@example.com", "S", "B") is True
    conn = _FakeSMTP.instances[0]
    assert conn.starttls_called is False, "starttls on an SMTPS port breaks the session"
    assert conn.context is not None, "implicit TLS needs an SSL context"


def test_tls_can_be_turned_off_for_a_local_relay(monkeypatch):
    _patch(monkeypatch, SMTP_PORT=25, SMTP_TLS=False, SMTP_USER="", SMTP_PASSWORD="")
    assert email_mod.send_email("to@example.com", "S", "B") is True
    conn = _FakeSMTP.instances[0]
    assert conn.starttls_called is False
    assert conn.logged_in_as is None, "no credentials means no login attempt"


def test_from_header_prefers_smtp_from(monkeypatch):
    _patch(monkeypatch, SMTP_FROM="Clarivo <hello@clinic.example>")
    email_mod.send_email("to@example.com", "S", "B")
    assert _FakeSMTP.instances[0].sent[0]["From"] == "Clarivo <hello@clinic.example>"


def test_a_send_failure_is_swallowed_not_raised(monkeypatch):
    """A failed reset email must not turn into a 500 on the request that triggered it."""
    _patch(monkeypatch)

    def _boom(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(email_mod.smtplib, "SMTP", _boom)
    assert email_mod.send_email("to@example.com", "S", "B") is False


def test_describe_config_never_leaks_the_password(monkeypatch):
    """This line is logged at startup and on every failure, so it must be safe."""
    _patch(monkeypatch, SMTP_PASSWORD="super-secret-value")
    described = email_mod.describe_config()
    assert "super-secret-value" not in described
    assert "smtp.example.com" in described and "587" in described

    monkeypatch.setattr(email_mod.settings, "SMTP_HOST", "")
    assert "not configured" in email_mod.describe_config()
