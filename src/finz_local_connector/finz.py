"""Client HTTP de Finz (`/api/local-connector/v1`, doc Finz `docs/connecteur-local-api.md`)."""

from __future__ import annotations

import gzip
import json
from typing import Any
from urllib.parse import urlparse

import requests

from . import __version__
from .errors import ConnectorError

API = "/api/local-connector/v1"
TIMEOUT = 60


class FinzError(ConnectorError):
    def __init__(self, status: int, code: str | None):
        super().__init__(f"Finz a refusé la demande ({status} {code or ''})".strip())
        self.status = status
        self.code = code


MESSAGES = {
    "invalid_code": "Code refusé : il est inconnu, expiré ou déjà utilisé. Affichez-en un nouveau dans Finz.",
    "unauthorized": "Ce connecteur n'est plus relié à Finz : reliez-le à nouveau (`link`).",
    "version_too_old": "Mise à jour requise : cette version du connecteur n'est plus acceptée par Finz.",
    "bank_revoked": "Cette banque a été retirée dans Finz.",
    "bank_taken": "Cette banque est déjà déclarée par un autre connecteur.",
}


def check_url(url: str) -> str:
    """HTTPS obligatoire, sauf `localhost` pour le développement (spec §6)."""
    parsed = urlparse(url.strip().rstrip("/"))
    local = parsed.hostname in ("localhost", "127.0.0.1", "::1")
    if parsed.scheme != "https" and not (local and parsed.scheme == "http"):
        raise ConnectorError("L'adresse de Finz doit commencer par https://")
    if not parsed.hostname:
        raise ConnectorError("Adresse de Finz invalide.")
    return parsed.geturl()


class FinzClient:
    def __init__(self, base_url: str, token: str | None = None, session=None):
        self.base_url = check_url(base_url)
        self.token = token
        self.session = session or requests.Session()

    def _headers(self) -> dict[str, str]:
        headers = {
            "accept": "application/json",
            "x-finz-connector-version": __version__,
            "user-agent": f"finz-local-connector/{__version__}",
        }
        if self.token:
            headers["authorization"] = f"Bearer {self.token}"
        return headers

    def _call(self, method: str, path: str, **kwargs) -> Any:
        headers = {**self._headers(), **kwargs.pop("headers", {})}
        try:
            response = self.session.request(
                method, self.base_url + API + path, headers=headers, timeout=TIMEOUT, **kwargs
            )
        except requests.RequestException as error:
            raise ConnectorError(f"Finz injoignable ({type(error).__name__}).") from error

        if response.status_code >= 400:
            try:
                code = response.json().get("error")
            except ValueError:
                code = None
            error = FinzError(response.status_code, code)
            if code in MESSAGES:
                error.args = (MESSAGES[code],)
            raise error
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def pair(self, code: str, device_name: str, platform: str) -> dict:
        body = {"code": code, "device_name": device_name, "platform": platform, "version": __version__}
        return self._call("POST", "/pair", json=body)

    def status(self) -> dict:
        return self._call("GET", "/status")

    def add_bank(self, bank_id: str, module: str, institution_name: str) -> dict:
        body = {"bank_id": bank_id, "module": module, "institution_name": institution_name}
        return self._call("POST", "/banks", json=body)

    def remove_bank(self, bank_id: str) -> None:
        self._call("DELETE", f"/banks/{bank_id}")

    def push(self, bank_id: str, payload: dict) -> dict:
        body = gzip.compress(json.dumps(payload, ensure_ascii=False).encode())
        headers = {"content-type": "application/octet-stream", "content-encoding": "gzip"}
        return self._call("POST", f"/banks/{bank_id}/sync", data=body, headers=headers)
