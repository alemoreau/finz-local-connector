"""Secrets du connecteur (spec §5.3) : jeton Finz, champs secrets des banques, clé des sessions.

- Trousseau du système (`keyring`) quand il est utilisable : Trousseau macOS, Gestionnaire
  d'identification Windows, Secret Service sous Linux.
- Sinon (serveur, Docker) : fichier `secrets.enc` chiffré (Fernet) avec une clé fournie par
  `FINZ_LOCAL_CONNECTOR_KEY` ou par le fichier `FINZ_LOCAL_CONNECTOR_KEY_FILE` (secret Docker,
  credentials systemd). `finz-local-connector key` en génère une.

Choix automatique, forçable par `FINZ_LOCAL_CONNECTOR_SECRETS=keyring|file`. Les secrets ne
passent jamais par les arguments, l'environnement d'un sous-processus ou les journaux.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Protocol

from cryptography.fernet import Fernet, InvalidToken

from .errors import ConnectorError

SERVICE = "finz-local-connector"


class Vault(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...
    def delete(self, key: str) -> None: ...


class KeyringVault:
    def __init__(self, backend=None):
        import keyring

        self._keyring = backend or keyring

    def get(self, key: str) -> str | None:
        return self._keyring.get_password(SERVICE, key)

    def set(self, key: str, value: str) -> None:
        self._keyring.set_password(SERVICE, key, value)

    def delete(self, key: str) -> None:
        try:
            self._keyring.delete_password(SERVICE, key)
        except Exception:  # absent : rien à supprimer
            pass


class FileVault:
    def __init__(self, path: Path, key: bytes):
        self.path = path
        try:
            self._fernet = Fernet(key)
        except (ValueError, TypeError) as error:
            raise ConnectorError(
                "Clé de chiffrement invalide : générez-en une avec `finz-local-connector key`."
            ) from error

    def _read(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self._fernet.decrypt(self.path.read_bytes()))
        except InvalidToken as error:
            raise ConnectorError(
                "Impossible de déchiffrer les secrets : la clé a changé ?"
            ) from error

    def _write(self, data: dict[str, str]) -> None:
        token = self._fernet.encrypt(json.dumps(data).encode())
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".secrets.")
        with os.fdopen(fd, "wb") as handle:
            handle.write(token)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def get(self, key: str) -> str | None:
        return self._read().get(key)

    def set(self, key: str, value: str) -> None:
        data = self._read()
        data[key] = value
        self._write(data)

    def delete(self, key: str) -> None:
        data = self._read()
        if data.pop(key, None) is not None:
            self._write(data)


def generate_key() -> str:
    return Fernet.generate_key().decode()


def _file_key() -> bytes | None:
    if value := os.environ.get("FINZ_LOCAL_CONNECTOR_KEY"):
        return value.strip().encode()
    if file := os.environ.get("FINZ_LOCAL_CONNECTOR_KEY_FILE"):
        return Path(file).read_text(encoding="utf-8").strip().encode()
    return None


def _keyring_usable() -> bool:
    try:
        import keyring
        from keyring.backends import fail

        return not isinstance(keyring.get_keyring(), fail.Keyring)
    except Exception:
        return False


def open_vault(data_dir: Path) -> Vault:
    mode = os.environ.get("FINZ_LOCAL_CONNECTOR_SECRETS")
    key = _file_key()

    if mode == "file" or (mode is None and key is not None):
        if key is None:
            raise ConnectorError(
                "FINZ_LOCAL_CONNECTOR_KEY (ou FINZ_LOCAL_CONNECTOR_KEY_FILE) est requise pour "
                "chiffrer les secrets. Générez-la avec `finz-local-connector key`."
            )
        return FileVault(data_dir / "secrets.enc", key)

    if mode == "keyring" or _keyring_usable():
        return KeyringVault()

    raise ConnectorError(
        "Aucun trousseau disponible sur cette machine : définissez FINZ_LOCAL_CONNECTOR_KEY "
        "(générée par `finz-local-connector key`) pour chiffrer les secrets dans un fichier."
    )
