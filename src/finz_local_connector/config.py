"""Réglages sans secret (spec §5.3) : adresse de Finz, banques, fréquence, échéances.

Fichier `config.json` dans le dossier de données : `FINZ_LOCAL_CONNECTOR_DATA`, sinon le
dossier de l'utilisateur (`platformdirs`). Les secrets sont ailleurs (`secrets.py`).
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

import platformdirs

INTERVALS_HOURS = (6, 12, 24)


def data_dir() -> Path:
    path = os.environ.get("FINZ_LOCAL_CONNECTOR_DATA") or platformdirs.user_data_dir(
        "finz-local-connector", appauthor=False
    )
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    try:
        directory.chmod(0o700)
    except OSError:
        pass
    return directory


@dataclass
class Bank:
    bank_id: str
    module: str
    label: str
    connection_id: str | None = None
    next_sync_at: float = 0.0
    paused: bool = False
    failures: int = 0


@dataclass
class Config:
    finz_url: str | None = None
    connector_id: str | None = None
    household_name: str | None = None
    interval_hours: int = 12
    banks: list[Bank] = field(default_factory=list)

    @property
    def linked(self) -> bool:
        return bool(self.finz_url and self.connector_id)

    def bank(self, key: str) -> Bank | None:
        for bank in self.banks:
            if key in (bank.bank_id, bank.module, bank.label):
                return bank
        return None


def path() -> Path:
    return data_dir() / "config.json"


def load() -> Config:
    file = path()
    if not file.exists():
        return Config()
    raw = json.loads(file.read_text(encoding="utf-8"))
    banks = [Bank(**b) for b in raw.pop("banks", [])]
    return Config(**raw, banks=banks)


def save(config: Config) -> None:
    file = path()
    data = json.dumps(asdict(config), ensure_ascii=False, indent=2)
    # Écriture atomique : un arrêt brutal ne laisse pas un fichier tronqué.
    fd, tmp = tempfile.mkstemp(dir=file.parent, prefix=".config.")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(data)
    os.replace(tmp, file)
