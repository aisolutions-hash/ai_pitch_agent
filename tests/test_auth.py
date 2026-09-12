def test_dev_login_and_me(client):
    resp = client.post("/api/auth/google", json={"id_token": "dev:owner@kalisoftai.com"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"]
    assert body["expires_in"] > 0

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == "owner@kalisoftai.com"
    assert me.json()["domain"] == "kalisoftai.com"


def test_dev_login_requires_email(client):
    resp = client.post("/api/auth/google", json={"id_token": "dev:"})
    assert resp.status_code == 400


def test_me_requires_token(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_rejects_bad_token(client):
    resp = client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401
