import os
import pathlib
import sys
import tempfile

# Configure the app for tests BEFORE importing it.
_TMP_DB = pathlib.Path(tempfile.gettempdir()) / "sales_fastapi_test.db"
if _TMP_DB.exists():
    _TMP_DB.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"
os.environ["SECRET_KEY"] = "test-secret-key-that-is-long-enough-for-hs256"
os.environ["AUTH_DEV_MODE"] = "true"
os.environ["GOOGLE_CLIENT_ID"] = ""
os.environ["ENV"] = "test"

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from sales_fastapi.database import Base, engine, init_db  # noqa: E402
from sales_fastapi.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _prepare_db():
    init_db()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def _clean_tables():
    yield
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def auth_headers(client):
    resp = client.post("/api/auth/google", json={"id_token": "dev:tester@kalisoftai.com"})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
