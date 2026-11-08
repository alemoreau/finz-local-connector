"""Modules bancaires disponibles (woob figé, `scripts/fetch-modules.sh`) et leurs champs."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from woob.capabilities.bank import CapBank
from woob.core import WoobBase
from woob.tools.value import ValueTransient

from .errors import ConnectorError

log = logging.getLogger(__name__)


def modules_path() -> str:
    """Dossier des modules : `FINZ_WOOB_MODULES`, sinon `vendor/woob-modules` du dépôt."""
    configured = os.environ.get("FINZ_WOOB_MODULES")
    candidates = [Path(configured)] if configured else []
    candidates.append(Path(__file__).resolve().parents[2] / "vendor" / "woob-modules")
    for candidate in candidates:
        if (candidate / "__init__.py").exists() or candidate.is_dir():
            return str(candidate)
    raise ConnectorError(
        "Modules bancaires introuvables : lancez `scripts/fetch-modules.sh` ou définissez "
        "FINZ_WOOB_MODULES."
    )


@dataclass(frozen=True)
class Field:
    id: str
    label: str
    masked: bool
    required: bool
    choices: dict[str, str] | None
    default: str | None


@dataclass(frozen=True)
class BankModule:
    name: str
    description: str
    fields: tuple[Field, ...]


def _fields(module) -> tuple[Field, ...]:
    fields = []
    for value in module.config.values():
        if isinstance(value, ValueTransient):
            continue
        choices = getattr(value, "choices", None)
        fields.append(
            Field(
                id=value.id,
                label=value.label or value.id,
                masked=bool(getattr(value, "masked", False)),
                required=bool(getattr(value, "required", True)),
                choices={str(k): str(v) for k, v in choices.items()} if choices else None,
                default=None if value.default in (None, "") else str(value.default),
            )
        )
    return tuple(fields)


def describe(name: str, path: str | None = None) -> BankModule:
    woob = WoobBase(modules_path=path or modules_path())
    try:
        module = woob.modules_loader.get_or_load_module(name)
    except Exception as error:
        raise ConnectorError(f"Module bancaire inconnu : {name}") from error
    if not module.has_caps(CapBank):
        raise ConnectorError(f"{name} n'est pas un module bancaire.")
    return BankModule(name=module.name, description=module.description, fields=_fields(module))


def available(path: str | None = None, search: str | None = None) -> list[BankModule]:
    """Modules bancaires (CapBank), par nom. Un module qui ne se charge pas est ignoré."""
    root = Path(path or modules_path())
    result = []
    for entry in sorted(root.iterdir()):
        if not (entry / "module.py").exists() and not (entry / "__init__.py").exists():
            continue
        if search and search.lower() not in entry.name.lower():
            continue
        try:
            result.append(describe(entry.name, str(root)))
        except ConnectorError:
            continue
        except Exception:  # module cassé ou dépendance absente
            log.debug("module ignoré : %s", entry.name)
    return result
