"""Une synchro d'une banque : lecture, envoi à Finz, échéance suivante (spec §5.2, §5.4).

L'envoi part aussi en cas d'erreur (type seulement) pour que Finz affiche le bon état. Les
données lues ne sont jamais journalisées ; seule la classe de l'erreur l'est, et la trace
reste locale.
"""

from __future__ import annotations

import json
import logging
import random
import time
from datetime import date, datetime, timezone

from woob import __version__ as woob_version

from . import __version__, config as cfg, errors
from .banks import modules_path
from .errors import ConnectorError
from .finz import FinzClient, FinzError
from .runner import read_bank
from .storage import EncryptedStorage
from .vault import generate_key

log = logging.getLogger(__name__)

# Erreurs qu'un nouvel essai automatique ne règle pas : l'utilisateur doit agir.
NEEDS_USER = {"credentials", "blocked", "sca", "captcha", "action_needed"}
BACKOFF_MIN = 15 * 60
BACKOFF_MAX = 6 * 3600


class Context:
    """Ce qu'il faut pour synchroniser : réglages, secrets, client Finz."""

    def __init__(self, vault, client: FinzClient | None = None):
        self.vault = vault
        self.config = cfg.load()
        self._client = client

    @property
    def client(self) -> FinzClient:
        if self._client is None:
            if not self.config.linked:
                raise ConnectorError("Connecteur non relié : lancez d'abord `link`.")
            token = self.vault.get("finz-token")
            if not token:
                raise ConnectorError("Jeton Finz absent : reliez le connecteur à nouveau (`link`).")
            self._client = FinzClient(self.config.finz_url, token)
        return self._client

    def save(self) -> None:
        cfg.save(self.config)

    def bank_params(self, bank: cfg.Bank) -> dict[str, str]:
        raw = self.vault.get(f"bank:{bank.bank_id}")
        if raw is None:
            raise ConnectorError(f"Identifiants de {bank.label} absents : `bank credentials {bank.module}`.")
        return json.loads(raw)

    def storage(self, bank: cfg.Bank) -> EncryptedStorage:
        key = self.vault.get("session-key")
        if key is None:
            key = generate_key()
            self.vault.set("session-key", key)
        return EncryptedStorage(cfg.data_dir() / "sessions" / f"{bank.bank_id}.enc", key.encode())


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def envelope(module: str, started_at: str, since: date | None, reading=None, error=None) -> dict:
    payload = {
        "connector_version": __version__,
        "engine_version": woob_version,
        "module": module,
        "started_at": started_at,
        "finished_at": _now_iso(),
        "full_history": since is None,
        "outcome": "ok" if error is None else "error",
        "error": error,
        "accounts": [],
        "history": {},
        "investments": {},
        "market_orders": {},
        "account_errors": {},
    }
    if reading is not None:
        payload.update(
            accounts=reading.accounts,
            history=reading.history,
            investments=reading.investments,
            market_orders=reading.market_orders,
            account_errors=reading.account_errors,
        )
    return payload


def since_for(status: dict | None, bank: cfg.Bank) -> date | None:
    for entry in (status or {}).get("banks", []):
        if entry.get("bank_id") == bank.bank_id and entry.get("since"):
            return date.fromisoformat(entry["since"])
    return None


def sync_bank(ctx: Context, bank: cfg.Bank, status: dict | None = None, interactive=False, ask=None, notify=None) -> str:
    """Synchronise une banque ; rend `"ok"` ou le type d'erreur. Met à jour l'échéance."""
    status = status if status is not None else ctx.client.status()
    since = since_for(status, bank)
    started = _now_iso()

    try:
        reading = read_bank(
            bank.module,
            bank.bank_id,
            ctx.bank_params(bank),
            ctx.storage(bank),
            modules_path(),
            since=since,
            interactive=interactive,
            ask=ask,
            notify=notify,
        )
        payload, outcome = envelope(bank.module, started, since, reading=reading), "ok"
    except ConnectorError:
        raise
    except Exception as error:
        described = errors.describe(error)
        log.warning("synchro %s : %s (%s)", bank.module, described["kind"], described["exception"], exc_info=True)
        payload, outcome = envelope(bank.module, started, since, error=described), described["kind"]

    ctx.client.push(bank.bank_id, payload)
    schedule(ctx, bank, outcome)
    return outcome


def schedule(ctx: Context, bank: cfg.Bank, outcome: str, now: float | None = None) -> None:
    now = now if now is not None else time.time()
    if outcome == "ok":
        bank.failures, bank.paused = 0, False
        jitter = random.uniform(0, 300)
        bank.next_sync_at = now + ctx.config.interval_hours * 3600 + jitter
    elif outcome in NEEDS_USER:
        # Plus de synchro planifiée tant qu'une synchro manuelle n'a pas réussi.
        bank.paused = True
    else:
        bank.failures += 1
        bank.next_sync_at = now + min(BACKOFF_MIN * 2 ** (bank.failures - 1), BACKOFF_MAX)
    ctx.save()


def due(bank: cfg.Bank, now: float, requested: bool) -> bool:
    if requested:
        return True
    return not bank.paused and now >= bank.next_sync_at


def tick(ctx: Context, now: float | None = None) -> dict:
    """Un passage du service : état Finz, puis synchro des banques dues. Rend l'état."""
    now = now if now is not None else time.time()
    status = ctx.client.status()
    if _too_old(status.get("min_version")):
        log.error("mise à jour requise (version minimale %s)", status.get("min_version"))
        return status

    requested = {b["bank_id"] for b in status.get("banks", []) if b.get("sync_requested")}
    for bank in list(ctx.config.banks):
        if due(bank, now, bank.bank_id in requested):
            try:
                sync_bank(ctx, bank, status=status)
            except FinzError as error:
                log.warning("envoi refusé pour %s : %s", bank.module, error.code)
                if error.code == "bank_revoked":
                    bank.paused = True
                    ctx.save()
            except ConnectorError as error:
                log.warning("synchro %s impossible : %s", bank.module, error)
    return status


def _too_old(minimum: str | None) -> bool:
    if not minimum:
        return False

    def parts(version: str) -> tuple[int, ...]:
        return tuple(int(p) for p in version.split(".")[:3] if p.isdigit())

    return parts(__version__) < parts(minimum)
