import gzip
import json
from pathlib import Path

import pytest

from finz_local_connector.vault import FileVault, generate_key

MODULES = str(Path(__file__).parent / "modules")


class FakeResponse:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body
        self.content = b"" if body is None else json.dumps(body).encode()

    def json(self):
        if self._body is None:
            raise ValueError("vide")
        return self._body


class FakeFinz:
    """Faux Finz : routes du connecteur, envois décompressés et gardés pour les assertions."""

    def __init__(self):
        self.banks = {}
        self.pushes = []
        self.requests = []
        self.min_version = "0.1.0"
        self.sync_requested = set()
        self.since = {}

    def request(self, method, url, headers=None, timeout=None, json=None, data=None):
        path = url.split("/api/local-connector/v1", 1)[1]
        self.requests.append((method, path, headers or {}))
        if path == "/pair":
            if json["code"] != "ABCD-EFGH":
                return FakeResponse(400, {"error": "invalid_code"})
            return FakeResponse(200, {"local_connector_id": "lc-1", "token": "finz_jeton", "household_name": "Foyer test"})
        if (headers or {}).get("authorization") != "Bearer finz_jeton":
            return FakeResponse(401, {"error": "unauthorized"})
        if path == "/status":
            banks = [
                {"connection_id": c, "bank_id": b, "since": self.since.get(b), "sync_requested": b in self.sync_requested}
                for b, c in self.banks.items()
            ]
            return FakeResponse(200, {"min_version": self.min_version, "poll_seconds": 300, "banks": banks})
        if path == "/banks" and method == "POST":
            self.banks[json["bank_id"]] = "conn-" + json["bank_id"][:8]
            return FakeResponse(201, {"connection_id": self.banks[json["bank_id"]]})
        if path.startswith("/banks/") and path.endswith("/sync"):
            assert headers["content-encoding"] == "gzip"
            payload = __import__("json").loads(gzip.decompress(data))
            self.pushes.append((path.split("/")[2], payload))
            self.sync_requested.discard(path.split("/")[2])
            return FakeResponse(202, {"event_id": "ev-%d" % len(self.pushes)})
        if path.startswith("/banks/") and method == "DELETE":
            self.banks.pop(path.split("/")[2], None)
            return FakeResponse(204)
        return FakeResponse(404, {"error": "not_found"})


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FINZ_LOCAL_CONNECTOR_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("FINZ_WOOB_MODULES", MODULES)
    monkeypatch.setenv("FINZ_LOCAL_CONNECTOR_KEY", generate_key())
    monkeypatch.delenv("FINZ_LOCAL_CONNECTOR_SECRETS", raising=False)
    return tmp_path


@pytest.fixture
def finz(monkeypatch):
    fake = FakeFinz()
    import requests

    monkeypatch.setattr(requests, "Session", lambda: fake)
    return fake


@pytest.fixture
def vault(tmp_path):
    return FileVault(tmp_path / "secrets.enc", generate_key().encode())
