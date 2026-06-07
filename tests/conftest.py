import os
from typing import Optional
import pytest
import httpx
from tests.mock_backend import app

try:
    from starlette.testclient import TestClient
except ImportError:
    TestClient = None

@pytest.fixture(scope="session")
def base_url() -> Optional[str]:
    return os.environ.get("BASE_URL")

@pytest.fixture
def client(base_url):
    if base_url:
        # E2E test against live backend
        with httpx.Client(base_url=base_url) as client:
            yield client
    else:
        # Test against mock backend locally via Starlette TestClient
        with TestClient(app, base_url="http://testserver") as client:
            yield client

@pytest.fixture(autouse=True)
def clean_database(base_url, client):
    # Reset database state before each test to guarantee test isolation
    if base_url:
        try:
            client.post("/api/admin/reset")
        except Exception:
            pass
    else:
        # Reset local mock database directly
        db_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "mock_db.json"))
        if os.path.exists(db_file):
            try:
                os.remove(db_file)
            except Exception:
                pass
        # Re-initialize DB
        from tests.mock_backend import save_db
        save_db({"entries": {}, "idempotency_keys": {}})
        
        # Clean up storage dir
        storage_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "storage"))
        if os.path.exists(storage_dir):
            for f in os.listdir(storage_dir):
                try:
                    os.remove(os.path.join(storage_dir, f))
                except Exception:
                    pass
    yield
