def test_seed_and_list_templates(client, auth_headers):
    seeded = client.post("/api/templates/seed", headers=auth_headers)
    assert seeded.status_code == 200, seeded.text
    assert seeded.json()["created"] >= 10

    listed = client.get("/api/templates", headers=auth_headers)
    assert listed.status_code == 200
    assert len(listed.json()) >= 10

    meta = client.get("/api/templates/meta", headers=auth_headers)
    assert "email" in meta.json()["channels"]
    assert "cold_outreach" in meta.json()["strategies"]


def test_create_update_delete_template(client, auth_headers):
    created = client.post(
        "/api/templates",
        headers=auth_headers,
        json={
            "name": "Custom",
            "channel": "email",
            "strategy": "follow_up",
            "subject": "Hi {{name}}",
            "body": "Hello {{company}}",
        },
    )
    assert created.status_code == 201, created.text
    template = created.json()
    assert "name" in template["variables"]
    assert "company" in template["variables"]

    updated = client.patch(
        f"/api/templates/{template['id']}", headers=auth_headers, json={"subject": "New {{intent}}"}
    )
    assert updated.status_code == 200
    assert updated.json()["subject"] == "New {{intent}}"

    deleted = client.delete(f"/api/templates/{template['id']}", headers=auth_headers)
    assert deleted.status_code == 204


def test_campaign_requires_matching_contacts(client, auth_headers):
    client.post("/api/templates/seed", headers=auth_headers)
    template = client.get("/api/templates?channel=email", headers=auth_headers).json()[0]
    response = client.post(
        "/api/campaigns",
        headers=auth_headers,
        json={
            "name": "Empty",
            "channel": "email",
            "strategy": "cold_outreach",
            "template_id": template["id"],
            "filter": {"q": "no-such-company-xyz"},
        },
    )
    assert response.status_code == 400


def test_campaign_review_approve_and_linkedin_queue(client, auth_headers):
    client.post(
        "/api/contacts",
        headers=auth_headers,
        json={"email": "buyer@acme.com", "company": "Acme", "name": "Ravi"},
    )
    client.post("/api/templates/seed", headers=auth_headers)
    template = client.get("/api/templates?channel=linkedin", headers=auth_headers).json()[0]

    created = client.post(
        "/api/campaigns",
        headers=auth_headers,
        json={
            "name": "LinkedIn wave",
            "channel": "linkedin",
            "strategy": template["strategy"],
            "template_id": template["id"],
            "use_ai": False,
            "filter": {"limit": 5},
        },
    )
    assert created.status_code == 201, created.text
    campaign = created.json()
    assert campaign["status"] == "pending_review"
    assert campaign["total"] == 1
    assert campaign["messages"][0]["status"] == "pending_review"
    assert "Acme" in campaign["messages"][0]["rendered_body"]

    approved = client.post(f"/api/campaigns/{campaign['id']}/approve", headers=auth_headers)
    assert approved.status_code == 200
    assert approved.json()["messages"][0]["status"] == "approved"

    sent = client.post(f"/api/campaigns/{campaign['id']}/send", headers=auth_headers)
    assert sent.status_code == 200, sent.text
    assert sent.json()["skipped"] == 1

    detail = client.get(f"/api/campaigns/{campaign['id']}", headers=auth_headers).json()
    assert detail["messages"][0]["status"] == "queued"


def test_whatsapp_campaign_fails_when_disabled(client, auth_headers, monkeypatch):
    from sales_fastapi.config import settings

    monkeypatch.setattr(settings, "WHATSAPP_ENABLED", False)
    client.post(
        "/api/contacts",
        headers=auth_headers,
        json={"email": "wa@acme.com", "company": "Acme", "phone": "+919999999999"},
    )
    client.post("/api/templates/seed", headers=auth_headers)
    template = client.get("/api/templates?channel=whatsapp", headers=auth_headers).json()[0]

    campaign = client.post(
        "/api/campaigns",
        headers=auth_headers,
        json={
            "name": "WA",
            "channel": "whatsapp",
            "strategy": template["strategy"],
            "template_id": template["id"],
            "use_ai": False,
            "filter": {"limit": 5},
        },
    ).json()
    client.post(f"/api/campaigns/{campaign['id']}/approve", headers=auth_headers)
    result = client.post(f"/api/campaigns/{campaign['id']}/send", headers=auth_headers)
    assert result.status_code == 200
    assert result.json()["failed"] == 1

    detail = client.get(f"/api/campaigns/{campaign['id']}", headers=auth_headers).json()
    assert detail["messages"][0]["status"] == "failed"
    assert "disabled" in detail["messages"][0]["error"]
