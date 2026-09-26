import hashlib
import hmac
import json

from sales_fastapi.config import settings


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _enable_wechaty(monkeypatch, *, secret: str = ""):
    monkeypatch.setattr(settings, "WHATSAPP_ENABLED", True)
    monkeypatch.setattr(settings, "WECHATY_GATEWAY_TOKEN", "gw-token")
    monkeypatch.setattr(settings, "WECHATY_WEBHOOK_SECRET", secret)


def test_status_requires_auth(client):
    assert client.get("/api/whatsapp/status").status_code == 401


def test_status_disabled_by_default(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "WHATSAPP_ENABLED", False)
    response = client.get("/api/whatsapp/status", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False


def test_send_returns_503_when_disabled(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "WHATSAPP_ENABLED", False)
    response = client.post(
        "/api/whatsapp/send",
        headers=auth_headers,
        json={"to": "alice", "text": "hello"},
    )
    assert response.status_code == 503


def test_send_success_persists_and_returns_gateway_id(client, auth_headers, monkeypatch):
    _enable_wechaty(monkeypatch)
    monkeypatch.setattr(
        "sales_fastapi.wechaty.WechatyGateway.send_text",
        lambda self, to, text: {
            "id": "gw-123",
            "to": to,
            "text": text,
            "status": "sent",
            "provider": "mock",
        },
    )

    response = client.post(
        "/api/whatsapp/send",
        headers=auth_headers,
        json={"to": "alice", "text": "Hello from Kalisoft"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["id"] == "gw-123"

    listed = client.get("/api/whatsapp/messages", headers=auth_headers)
    assert listed.status_code == 200
    rows = listed.json()
    assert any(row["status"] == "sent" and row["message"] == "Hello from Kalisoft" for row in rows)


def test_webhook_without_secret_is_accepted(client, monkeypatch):
    monkeypatch.setattr(settings, "WECHATY_WEBHOOK_SECRET", "")
    body = json.dumps({"id": "m1", "from": "+919876543210", "text": "Need a quotation"}).encode()
    response = client.post(
        "/api/whatsapp/webhook",
        content=body,
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["ok"] is True
    assert data["intent"] == "sales"


def test_webhook_rejects_bad_signature(client, monkeypatch):
    monkeypatch.setattr(settings, "WECHATY_WEBHOOK_SECRET", "top-secret")
    body = json.dumps({"from": "+91", "text": "hi"}).encode()
    response = client.post(
        "/api/whatsapp/webhook",
        content=body,
        headers={"content-type": "application/json", "x-wechaty-signature": "sha256=deadbeef"},
    )
    assert response.status_code == 401


def test_webhook_accepts_valid_signature(client, monkeypatch):
    monkeypatch.setattr(settings, "WECHATY_WEBHOOK_SECRET", "top-secret")
    body = json.dumps({"id": "m2", "from": "+919000000000", "text": "We are hiring"}).encode()
    response = client.post(
        "/api/whatsapp/webhook",
        content=body,
        headers={
            "content-type": "application/json",
            "x-wechaty-signature": _sign("top-secret", body),
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["intent"] == "hiring"


def test_webhook_matches_existing_contact_by_phone(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "WECHATY_WEBHOOK_SECRET", "")
    client.post(
        "/api/contacts",
        headers=auth_headers,
        json={"email": "buyer@acme.com", "company": "Acme", "phone": "+919111111111"},
    )
    body = json.dumps({"from": "+919111111111", "text": "Please share pricing"}).encode()
    response = client.post(
        "/api/whatsapp/webhook",
        content=body,
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["matched_user_id"] != 0


def test_messages_require_auth(client):
    assert client.get("/api/whatsapp/messages").status_code == 401
