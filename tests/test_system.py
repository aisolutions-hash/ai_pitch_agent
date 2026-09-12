def test_config_is_public(client):
    resp = client.get("/api/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["project_name"]
    assert "dev_mode" in body
    assert "google_client_secret" not in body


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert body["database"] == "ok"


def test_index_page_served(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Kalisoft AI Sales Pipeline" in resp.text


def test_integrations_requires_auth(client):
    assert client.get("/api/integrations").status_code == 401


def test_integrations_shape(client, auth_headers):
    body = client.get("/api/integrations", headers=auth_headers).json()
    assert body["gcs"]["bucket"] == "kalisoftai-datahub"
    assert "gemma_model" in body
