# test_health.py
import sys
import os
import types

# Ensure service folder on path
ROOT = os.path.abspath(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ---- Robust pyodbc stub: returns a connection-like object with cursor()/commit()/close() ----
class _MockCursor:
    def execute(self, *args, **kwargs):
        # no-op
        return None

    def fetchone(self):
        # return a single-row tuple to be indexable by application code
        return (0,)

    def fetchall(self):
        # return list of row tuples
        return [(0,)]

    def close(self):
        return None

class _MockConnection:
    def __init__(self):
        self._cursor = _MockCursor()

    def cursor(self):
        return self._cursor

    def commit(self):
        return None

    def close(self):
        return None

# Install stub into sys.modules before importing application
sys.modules["pyodbc"] = types.SimpleNamespace(connect=lambda *a, **k: _MockConnection())

# Now import the Flask app
from app import app


def test_health():
    app.config["TESTING"] = True
    client = app.test_client()
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json().get("status") == "ok"