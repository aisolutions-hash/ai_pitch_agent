MAHINDRA = {
    "company": "Mahindra Accelo Ltd. (Mahindra & Mahindra group) – Supa, Ahmednagar",
    "name": "Mahindra Accelo – General Enquiries",
    "email": "info@mahindraaccelo.com",
    "phone": "22 2493 5185 / 5186",
    "address": "F-221, Gat No. 167 K/2, Supa MIDC, Ahmednagar, Maharashtra 414301",
    "linkedin_profiles": [
        "Smaranika Mohapatra – Assistant Manager (Procurement & SCM)",
        "Tushar Ithape – Supply Chain Management",
    ],
    "purchase_contact_name": "Smaranika Mohapatra",
    "purchase_contact_role": "Assistant Manager (Procurement & SCM)",
    "context": "Automotive SCM procurement at Supa MIDC",
}


def test_create_contact_auto_segregates(client, auth_headers):
    resp = client.post("/api/contacts", json=MAHINDRA, headers=auth_headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["domain"] == "mahindraaccelo.com"
    assert body["intent"] == "procurement"
    assert body["linkedin_profiles"][0].startswith("Smaranika")
    assert body["source"] == "manual"


def test_duplicate_contact_rejected(client, auth_headers):
    assert client.post("/api/contacts", json=MAHINDRA, headers=auth_headers).status_code == 201
    dup = client.post("/api/contacts", json=MAHINDRA, headers=auth_headers)
    assert dup.status_code == 409


def test_list_and_filter_contacts(client, auth_headers):
    client.post("/api/contacts", json=MAHINDRA, headers=auth_headers)
    client.post(
        "/api/contacts",
        json={"company": "Sales Co", "email": "sales@vendor.com", "context": "quotation request"},
        headers=auth_headers,
    )

    all_contacts = client.get("/api/contacts", headers=auth_headers).json()
    assert len(all_contacts) == 2

    procurement = client.get("/api/contacts?intent=procurement", headers=auth_headers).json()
    assert len(procurement) == 1
    assert procurement[0]["email"] == "info@mahindraaccelo.com"

    search = client.get("/api/contacts?q=mahindra", headers=auth_headers).json()
    assert len(search) == 1


def test_stats(client, auth_headers):
    client.post("/api/contacts", json=MAHINDRA, headers=auth_headers)
    stats = client.get("/api/contacts/stats", headers=auth_headers).json()
    assert stats["total"] == 1
    assert stats["by_domain"].get("mahindraaccelo.com") == 1
    assert stats["by_intent"].get("procurement") == 1


def test_update_and_delete(client, auth_headers):
    created = client.post("/api/contacts", json=MAHINDRA, headers=auth_headers).json()
    cid = created["id"]

    patched = client.patch(
        f"/api/contacts/{cid}", json={"intent": "partnership"}, headers=auth_headers
    )
    assert patched.status_code == 200
    assert patched.json()["intent"] == "partnership"

    assert client.delete(f"/api/contacts/{cid}", headers=auth_headers).status_code == 204
    assert client.get(f"/api/contacts/{cid}", headers=auth_headers).status_code == 404


def test_contacts_are_user_scoped(client):
    a = client.post("/api/auth/google", json={"id_token": "dev:a@x.com"}).json()["access_token"]
    b = client.post("/api/auth/google", json={"id_token": "dev:b@x.com"}).json()["access_token"]
    client.post("/api/contacts", json=MAHINDRA, headers={"Authorization": f"Bearer {a}"})
    b_list = client.get("/api/contacts", headers={"Authorization": f"Bearer {b}"}).json()
    assert b_list == []


def test_contacts_require_auth(client):
    assert client.get("/api/contacts").status_code == 401
