#!/usr/bin/env python3
"""Lecture à blanc d'une banque : même lecture que `sync`, rien n'est envoyé à Finz.

Affiche un résumé sans montant : comptes (libellé, type), nombre de supports et d'ISIN,
opérations par type, cohérence entre le solde et la somme des supports, erreurs.

Usage (depuis le dépôt) : uv run python scripts/dry_run_bank.py <module>
"""

from __future__ import annotations

import getpass
import sys
from collections import Counter
from decimal import Decimal

from woob.core import WoobBase
from woob.tools.value import ValueTransient

from finz_local_connector.banks import modules_path
from finz_local_connector.runner import read_bank


def ask_params(module: str, path: str) -> dict[str, str]:
    loaded = WoobBase(modules_path=path).modules_loader.get_or_load_module(module)
    params = {}
    for value in loaded.config.values():
        if isinstance(value, ValueTransient):
            continue
        prompt = f"{value.label or value.id} : "
        answer = getpass.getpass(prompt) if value.masked else input(prompt).strip()
        if answer:  # vide : valeur par défaut du module
            params[value.id] = answer
    return params


def decimal(value) -> Decimal | None:
    try:
        return Decimal(str(value))
    except Exception:
        return None


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("Usage : uv run python scripts/dry_run_bank.py <module>")
    module = sys.argv[1]
    path = modules_path()
    reading = read_bank(module, "dry-run", ask_params(module, path), storage=None, modules_path=path)

    print(f"\n{len(reading.accounts)} compte(s)")
    for account in reading.accounts:
        key = account["id"]
        invs = reading.investments.get(key, [])
        history = reading.history.get(key, [])
        print(f"\n- {account.get('label')} (type woob {account.get('type')}, devise {account.get('currency')})")
        if invs:
            isins = sum(1 for inv in invs if inv.get("code_type") == "ISIN")
            print(f"  supports : {len(invs)}, dont {isins} avec ISIN")
            total = sum((decimal(inv.get("valuation")) or Decimal(0) for inv in invs), Decimal(0))
            balance = decimal(account.get("balance"))
            if balance:
                print(f"  somme des supports / solde : {total / balance:.4f}")
            incomplete = [inv.get("label") for inv in invs if not inv.get("quantity") or not inv.get("unitvalue")]
            if incomplete:
                print(f"  supports sans quantité ou sans valeur de part : {incomplete}")
        kinds = Counter((tr.get("type"), tr.get("label")) for tr in history)
        print(f"  opérations : {len(history)}")
        for (kind, label), count in sorted(kinds.items(), key=lambda item: -item[1]):
            print(f"    {count:>4} × type {kind} « {label} »")
        if history:
            dates = sorted(tr.get("date") for tr in history if tr.get("date"))
            print(f"  période : {dates[0][:7]} → {dates[-1][:7]}")
    if reading.account_errors:
        print(f"\nErreurs : {reading.account_errors}")


if __name__ == "__main__":
    main()
