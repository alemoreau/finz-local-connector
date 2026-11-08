"""Lecture d'une banque avec woob (spec §5.4, §5.6).

`read_bank/…` construit le backend du module dans un `WoobBase` (modules figés, stockage
chiffré), lit comptes, opérations, positions et ordres, et rend les objets au format JSON de
woob (`WoobEncoder`), sans les interpréter : Finz les convertit.

Synchro interactive (`interactive=True`, terminal ou fenêtre) : `request_information` reçoit
`{}` ; une `BrowserQuestion` est posée par `ask(champ)` et sa réponse renseignée dans la
configuration ; une `DecoupledValidation` (validation dans l'application de la banque) est
annoncée par `notify(message)` puis `resume` passe à vrai ; l'appel est relancé. C'est le
mécanisme du client `woob` lui-même (`woob/tools/application/repl.py`). Synchro planifiée :
aucune question, l'exception remonte (type `sca`).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime

from woob.capabilities.bank import CapBank
from woob.capabilities.bank.wealth import CapBankWealth
from woob.capabilities.base import empty
from woob.core import WoobBase
from woob.exceptions import BrowserInteraction, BrowserQuestion, DecoupledValidation, NeedInteractive
from woob.tools.json import WoobEncoder

from . import errors
from .errors import ConnectorError

log = logging.getLogger(__name__)

MAX_ROUNDS = 6
# Comptes dont on lit positions et ordres (types woob : marché, assurance-vie, épargne
# salariale et retraite, PEA, capitalisation, immobilier, crowdlending).
WEALTH_TYPES = {5, 8, 9, 10, 11, 12, 13, 14, 15, 16, 20, 21, 22}
# Opérations plus anciennes que `since` tolérées d'affilée avant d'arrêter la lecture (les
# banques ne trient pas toujours parfaitement).
OLDER_STREAK = 20


@dataclass
class Reading:
    accounts: list = field(default_factory=list)
    history: dict = field(default_factory=dict)
    investments: dict = field(default_factory=dict)
    market_orders: dict = field(default_factory=dict)
    account_errors: dict = field(default_factory=dict)


def _plain(objects) -> list:
    return json.loads(json.dumps(list(objects), cls=WoobEncoder))


def _day(value) -> date | None:
    if empty(value) or value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _history(backend, account, since: date | None) -> list:
    kept, older = [], 0
    for transaction in backend.iter_history(account):
        day = _day(getattr(transaction, "date", None))
        if since and day and day < since:
            older += 1
            if older >= OLDER_STREAK:
                break
            continue
        older = 0
        kept.append(transaction)
    return kept


def _optional(call: Callable[[], object]) -> list:
    try:
        return list(call())
    except NotImplementedError:
        return []


def _read(backend, since: date | None) -> Reading:
    reading = Reading()
    accounts = list(backend.iter_accounts())
    reading.accounts = _plain(accounts)
    wealth = backend.has_caps(CapBankWealth)

    for account in accounts:
        # Appel direct du backend (sans `woob.do`) : `backend` n'est pas renseigné sur les
        # objets, l'identifiant sérialisé est celui de la banque.
        key = account.id
        try:
            reading.history[key] = _plain(_history(backend, account, since))
            if wealth and getattr(account, "type", None) in WEALTH_TYPES:
                reading.investments[key] = _plain(
                    _optional(lambda a=account: backend.iter_investment(a))
                )
                reading.market_orders[key] = _plain(
                    _optional(lambda a=account: backend.iter_market_orders(a))
                )
        except (BrowserInteraction, NeedInteractive):
            raise
        except Exception as error:  # un compte illisible n'empêche pas les autres
            reading.account_errors[key] = errors.kind(error)
            log.warning("compte illisible : %s", type(error).__name__)
    return reading


def read_bank(
    module: str,
    bank_id: str,
    params: dict[str, str],
    storage,
    modules_path: str,
    since: date | None = None,
    interactive: bool = False,
    ask: Callable | None = None,
    notify: Callable[[str], None] | None = None,
) -> Reading:
    woob = WoobBase(modules_path=modules_path)
    backend = woob.build_backend(module, params=params, storage=storage, name=bank_id)
    if not backend.has_caps(CapBank):
        raise ConnectorError(f"{module} n'est pas un module bancaire.")

    if interactive and "request_information" in backend.config:
        backend.config["request_information"].set({})

    try:
        for _round in range(MAX_ROUNDS):
            try:
                return _read(backend, since)
            except BrowserQuestion as question:
                if not interactive or ask is None:
                    raise
                for value in question.fields:
                    backend.config[value.id].set(ask(value))
            except DecoupledValidation as validation:
                if not interactive or "resume" not in backend.config:
                    raise
                if notify:
                    notify(getattr(validation, "message", None) or "Validez dans l'application de votre banque.")
                backend.config["resume"].set(True)
        raise ConnectorError("La banque a posé trop de questions : réessayez plus tard.")
    finally:
        try:
            backend.deinit()
        except Exception:
            log.warning("session non enregistrée")
