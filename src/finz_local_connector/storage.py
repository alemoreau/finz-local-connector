"""Stockage woob d'une banque (cookies de session, état du navigateur), chiffré (spec §5.3).

Implémente `woob.tools.storage.IStorage` comme `StandardStorage`, mais dans un fichier
`sessions/<bank_id>.enc` chiffré par une clé rangée dans les secrets (`session-key`). Garder la
session évite de redemander une validation (2FA) à chaque synchro.
"""

from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from woob.tools.storage import IStorage


class EncryptedStorage(IStorage):
    def __init__(self, path: Path, key: bytes):
        self.path = path
        self._fernet = Fernet(key)
        self.values: dict = self._read()

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self._fernet.decrypt(self.path.read_bytes()))
        except (InvalidToken, ValueError):
            # Session illisible (clé changée) : on repart d'une session vide.
            return {}

    def load(self, what, name, default={}):  # noqa: B006 (signature de IStorage)
        section = self.values.setdefault(what, {})
        current = section.get(name, {})
        section[name] = deepcopy(default)
        section[name].update(current)

    def save(self, what, name):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        token = self._fernet.encrypt(json.dumps(self.values, default=str).encode())
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".session.")
        with os.fdopen(fd, "wb") as handle:
            handle.write(token)
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def set(self, what, name, *args):
        *keys, value = args
        node = self.values.setdefault(what, {}).setdefault(name, {})
        for key in keys[:-1]:
            node = node.setdefault(key, {})
        node[keys[-1]] = value

    def delete(self, what, name, *args):
        node = self.values.get(what, {}).get(name)
        if node is None:
            return
        if not args:
            self.values[what].pop(name, None)
            return
        for key in args[:-1]:
            node = node.get(key, {})
        node.pop(args[-1], None)

    def get(self, what, name, *args, **kwargs):
        default = kwargs.get("default")
        node = self.values.get(what, {}).get(name, default if not args else {})
        for key in args:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node
