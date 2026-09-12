def test_linkedin_search_and_list(client, auth_headers):
    resp = client.post(
        "/api/social/linkedin/search",
        json={"keywords": ["procurement", "scm"], "location": "Ahmednagar"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["added"] == 2

    profiles = client.get("/api/social/linkedin/profiles", headers=auth_headers).json()
    assert len(profiles) == 2

    # idempotent
    client.post(
        "/api/social/linkedin/search",
        json={"keywords": ["procurement", "scm"]},
        headers=auth_headers,
    )
    assert len(client.get("/api/social/linkedin/profiles", headers=auth_headers).json()) == 2


def test_reddit_search(client, auth_headers):
    resp = client.post(
        "/api/social/reddit/search",
        json={"subreddits": ["jobs"], "keywords": ["hiring"]},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["added"] == 1
    posts = client.get("/api/social/reddit/posts", headers=auth_headers).json()
    assert posts[0]["subreddit"] == "jobs"


def test_whatsapp_queue(client, auth_headers):
    resp = client.post(
        "/api/social/whatsapp/messages",
        json={"phone_number": "+911234567890", "message": "Follow up with Mahindra Accelo"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "pending"


def test_cron_trigger(client, auth_headers):
    resp = client.post("/api/cron/run", headers=auth_headers)
    assert resp.status_code == 200
    assert "sync_gcs_contacts" in resp.json()["tasks"]
