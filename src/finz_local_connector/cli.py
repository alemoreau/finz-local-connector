"""Ligne de commande `finz-local-connector` (spec §5.2)."""

from __future__ import annotations

import argparse
import getpass
import json
import logging
import logging.handlers
import platform
import socket
import sys
import time
import uuid

from . import __version__, banks, config as cfg
from .errors import ConnectorError
from .finz import FinzClient
from .sync import Context, sync_bank, tick
from .vault import generate_key, open_vault

log = logging.getLogger("finz_local_connector")


def _setup_logging(verbose: bool) -> None:
    directory = cfg.data_dir() / "logs"
    directory.mkdir(exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        directory / "connector.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    # woob journalise des pages et des adresses en mode bavard : avertissements seulement.
    logging.getLogger("woob").setLevel(logging.WARNING)
    if verbose:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        root.addHandler(console)


def _ctx() -> Context:
    return Context(open_vault(cfg.data_dir()))


def _ask(value) -> str:
    label = getattr(value, "label", None) or getattr(value, "description", None) or value.id
    if getattr(value, "masked", False):
        return getpass.getpass(f"{label} : ")
    return input(f"{label} : ").strip()


def _notify(message: str) -> None:
    print(message)
    print("En attente de votre validation…")


# --- Commandes ---------------------------------------------------------------------------


def cmd_key(_args) -> int:
    print(generate_key())
    return 0


def cmd_link(args) -> int:
    ctx = _ctx()
    client = FinzClient(args.url)
    code = input("Code affiché par Finz : ").strip()
    device = args.name or socket.gethostname() or "Connecteur local"
    machine = f"{platform.system().lower()}-{platform.machine().lower()}"
    result = client.pair(code, device, machine)

    ctx.vault.set("finz-token", result["token"])
    ctx.config.finz_url = client.base_url
    ctx.config.connector_id = result["local_connector_id"]
    ctx.config.household_name = result.get("household_name")
    ctx.save()
    print(f"Relié à Finz ({ctx.config.household_name or client.base_url}).")
    print("Ajoutez une banque : finz-local-connector bank add <module>")
    return 0


def cmd_unlink(_args) -> int:
    ctx = _ctx()
    for bank in ctx.config.banks:
        ctx.vault.delete(f"bank:{bank.bank_id}")
        session = cfg.data_dir() / "sessions" / f"{bank.bank_id}.enc"
        session.unlink(missing_ok=True)
    ctx.vault.delete("finz-token")
    ctx.vault.delete("session-key")
    cfg.save(cfg.Config())
    print("Connecteur délié sur cette machine. Retirez-le aussi dans Finz › Connexions.")
    return 0


def cmd_modules(args) -> int:
    for module in banks.available(search=args.search):
        print(f"{module.name:<24} {module.description}")
    return 0


def _prompt_params(module: banks.BankModule) -> dict[str, str]:
    params = {}
    for f in module.fields:
        if f.choices:
            print(f"{f.label} :")
            for key, label in f.choices.items():
                print(f"  {key} : {label}")
        prompt = f"{f.label}" + (f" [{f.default}]" if f.default and not f.masked else "") + " : "
        value = getpass.getpass(prompt) if f.masked else input(prompt).strip()
        if not value and f.default is not None:
            value = f.default
        if value or f.required:
            params[f.id] = value
    return params


def cmd_bank_add(args) -> int:
    ctx = _ctx()
    module = banks.describe(args.module)
    label = (args.label or module.description)[:120]
    params = _prompt_params(module)

    bank = cfg.Bank(bank_id=str(uuid.uuid4()), module=module.name, label=label)
    bank.connection_id = ctx.client.add_bank(bank.bank_id, module.name, label)["connection_id"]
    ctx.vault.set(f"bank:{bank.bank_id}", json.dumps(params))
    ctx.config.banks.append(bank)
    ctx.save()

    print(f"{label} ajoutée. Première synchro (tout l'historique disponible)…")
    return _report(bank, sync_bank(ctx, bank, interactive=True, ask=_ask, notify=_notify))


def cmd_bank_credentials(args) -> int:
    ctx = _ctx()
    bank = _bank(ctx, args.bank)
    params = _prompt_params(banks.describe(bank.module))
    ctx.vault.set(f"bank:{bank.bank_id}", json.dumps(params))
    print("Identifiants enregistrés. Synchro…")
    return _report(bank, sync_bank(ctx, bank, interactive=True, ask=_ask, notify=_notify))


def cmd_bank_list(_args) -> int:
    ctx = _ctx()
    if not ctx.config.banks:
        print("Aucune banque.")
    for bank in ctx.config.banks:
        state = "en pause (action requise)" if bank.paused else _next(bank)
        print(f"{bank.module:<16} {bank.label:<32} {state}")
    return 0


def cmd_bank_remove(args) -> int:
    ctx = _ctx()
    bank = _bank(ctx, args.bank)
    ctx.client.remove_bank(bank.bank_id)
    ctx.vault.delete(f"bank:{bank.bank_id}")
    (cfg.data_dir() / "sessions" / f"{bank.bank_id}.enc").unlink(missing_ok=True)
    ctx.config.banks = [b for b in ctx.config.banks if b.bank_id != bank.bank_id]
    ctx.save()
    print(f"{bank.label} retirée.")
    return 0


def cmd_sync(args) -> int:
    ctx = _ctx()
    targets = [_bank(ctx, args.bank)] if args.bank else list(ctx.config.banks)
    if not targets:
        print("Aucune banque : finz-local-connector bank add <module>")
        return 1
    status = ctx.client.status()
    code = 0
    for bank in targets:
        print(f"{bank.label}…")
        code |= _report(bank, sync_bank(ctx, bank, status=status, interactive=True, ask=_ask, notify=_notify))
    return code


def cmd_run(_args) -> int:
    ctx = _ctx()
    print(f"Connecteur local {__version__} : en service.")
    while True:
        try:
            status = tick(ctx)
            pause = int(status.get("poll_seconds") or 300)
        except ConnectorError as error:
            log.warning("passage en erreur : %s", error)
            pause = 300
        time.sleep(max(pause, 60))


def cmd_serve(_args) -> int:
    """Application de bureau : requêtes et événements en lignes JSON (`serve.py`)."""
    from .serve import Server

    Server().serve()
    return 0


def cmd_status(args) -> int:
    ctx = _ctx()
    if not ctx.config.linked:
        print("Non relié à Finz.")
        # `--local` sert de contrôle de santé : non relié n'est pas une panne.
        return 0 if args.local else 1
    print(f"Relié à {ctx.config.finz_url} ({ctx.config.household_name or '—'}), version {__version__}.")
    if not args.local:
        status = ctx.client.status()
        print(f"Version minimale acceptée : {status.get('min_version')}")
    for bank in ctx.config.banks:
        print(f"  {bank.label} : {'action requise' if bank.paused else _next(bank)}")
    return 0


# --- Outils ------------------------------------------------------------------------------

MESSAGES = {
    "ok": "à jour.",
    "credentials": "identifiants refusés : `bank credentials` pour les corriger.",
    "blocked": "accès bloqué par la banque.",
    "sca": "la banque demande une validation : relancez `sync` dans un terminal.",
    "captcha": "connectez-vous une fois sur le site de la banque, puis relancez `sync`.",
    "action_needed": "la banque demande une action sur son site.",
    "unavailable": "banque momentanément indisponible, nouvel essai plus tard.",
    "connector": "lecture impossible : une mise à jour du connecteur est nécessaire.",
}


def _report(bank: cfg.Bank, outcome: str) -> int:
    print(f"  {bank.label} : {MESSAGES.get(outcome, outcome)}")
    return 0 if outcome == "ok" else 2


def _next(bank: cfg.Bank) -> str:
    if not bank.next_sync_at:
        return "synchro à la prochaine occasion"
    return "prochaine synchro " + time.strftime("%d/%m %H:%M", time.localtime(bank.next_sync_at))


def _bank(ctx: Context, key: str) -> cfg.Bank:
    bank = ctx.config.bank(key)
    if bank is None:
        raise ConnectorError(f"Banque inconnue : {key} (voir `bank list`).")
    return bank


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="finz-local-connector", description="Connecteur local de Finz.")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("-v", "--verbose", action="store_true", help="journal aussi dans le terminal")
    sub = p.add_subparsers(dest="command", required=True)

    link = sub.add_parser("link", help="relier ce connecteur à Finz avec le code affiché par Finz")
    link.add_argument("url", help="adresse de Finz, par exemple https://app.finz.alemoreau.fr")
    link.add_argument("--name", help="nom de cette machine dans Finz")
    link.set_defaults(func=cmd_link)

    sub.add_parser("unlink", help="oublier Finz et les banques sur cette machine").set_defaults(func=cmd_unlink)
    sub.add_parser("key", help="générer une clé de chiffrement pour FINZ_LOCAL_CONNECTOR_KEY").set_defaults(func=cmd_key)

    bank = sub.add_parser("bank", help="banques").add_subparsers(dest="bank_command", required=True)
    modules = bank.add_parser("modules", help="modules bancaires disponibles")
    modules.add_argument("--search")
    modules.set_defaults(func=cmd_modules)
    add = bank.add_parser("add", help="ajouter une banque")
    add.add_argument("module")
    add.add_argument("--label", help="nom affiché dans Finz")
    add.set_defaults(func=cmd_bank_add)
    creds = bank.add_parser("credentials", help="corriger les identifiants d'une banque")
    creds.add_argument("bank")
    creds.set_defaults(func=cmd_bank_credentials)
    bank.add_parser("list", help="banques ajoutées").set_defaults(func=cmd_bank_list)
    remove = bank.add_parser("remove", help="retirer une banque")
    remove.add_argument("bank")
    remove.set_defaults(func=cmd_bank_remove)

    sync = sub.add_parser("sync", help="synchroniser maintenant (questions de la banque posées ici)")
    sync.add_argument("--bank")
    sync.set_defaults(func=cmd_sync)
    sub.add_parser("run", help="service : synchro planifiée et demandes de Finz").set_defaults(func=cmd_run)
    serve = sub.add_parser("serve", help=argparse.SUPPRESS)
    serve.add_argument("--stdio", action="store_true", required=True)
    serve.set_defaults(func=cmd_serve)
    status = sub.add_parser("status", help="état du connecteur")
    status.add_argument("--local", action="store_true", help="sans appeler Finz (contrôle de santé)")
    status.set_defaults(func=cmd_status)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command != "key":
        _setup_logging(args.verbose)
    try:
        return args.func(args)
    except ConnectorError as error:
        print(f"Erreur : {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
