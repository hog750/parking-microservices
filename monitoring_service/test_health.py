import sys
import os
import types

# Ensure service folder on path
ROOT = os.path.abspath(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Stub pyodbc to avoid system dependency during tests
sys.modules["pyodbc"] = types.SimpleNamespace(connect=lambda *a, **k: None)

from app import app


def test_health():
    app.config["TESTING"] = True
    client = app.test_client()
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json().get("status") == "ok"
