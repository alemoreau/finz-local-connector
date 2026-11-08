import json
import os

import pytest

from finz_local_connector import cli, config as cfg
from finz_local_connector.sync import Context, due, schedule, sync_bank, tick
from finz_local_connector.vault import open_vault


def run(*argv, inputs=()):
    answers = iter(inputs)
    return cli.main(list(argv)), answers


@pytest.fixture
def linked(env, finz, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": "ABCD-EFGH")
    assert cli.main(["link", "https://finz.example.org"]) == 0
    return finz


def add_bank(monkeypatch, password="mdp-fakebank-7f3a", scenario="ok"):
    answers = iter(["42", scenario])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr("getpass.getpass", lambda prompt="": password)
    return cli.main(["bank", "add", "fakebank"])


def test_liaison_jeton_dans_les_secrets_pas_dans_la_config(linked):
    config = cfg.load()
    assert config.connector_id == "lc-1"
    assert "finz_jeton" not in cfg.path().read_text()
    assert open_vault(cfg.data_dir()).get("finz-token") == "finz_jeton"


def test_code_refuse(env, finz, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda prompt="": "ZZZZ-ZZZZ")
    assert cli.main(["link", "https://finz.example.org"]) == 1
    assert "Code refusé" in capsys.readouterr().err


def test_ajout_d_une_banque_et_premiere_synchro(linked, monkeypatch):
    assert add_bank(monkeypatch) == 0
    [bank] = cfg.load().banks
    assert bank.module == "fakebank"
    assert bank.connection_id.startswith("conn-")
    assert "mdp-fakebank-7f3a" not in cfg.path().read_text()

    [(bank_id, payload)] = linked.pushes
    assert bank_id == bank.bank_id
    assert payload["outcome"] == "ok"
    assert payload["full_history"] is True
    assert payload["connector_version"] == "0.1.0"
    assert len(payload["accounts"]) == 2


def test_identifiants_refuses_envoyes_comme_type_seulement(linked, monkeypatch):
    assert add_bank(monkeypatch, password="faux") == 2
    [(_, payload)] = linked.pushes
    assert payload["outcome"] == "error"
    assert payload["error"] == {"kind": "credentials", "exception": "BrowserIncorrectPassword"}
    assert payload["accounts"] == []
    assert cfg.load().banks[0].paused


def test_service_synchro_due_et_demande_de_finz(linked, monkeypatch):
    add_bank(monkeypatch)
    ctx = Context(open_vault(cfg.data_dir()))
    [bank] = ctx.config.banks
    assert bank.next_sync_at > 0

    tick(ctx)
    assert len(linked.pushes) == 1  # pas encore dû

    linked.sync_requested.add(bank.bank_id)
    linked.since[bank.bank_id] = "2026-01-01"
    tick(ctx)
    assert len(linked.pushes) == 2
    payload = linked.pushes[-1][1]
    assert payload["full_history"] is False
    assert "TRES ANCIEN" not in json.dumps(payload)


def test_version_trop_ancienne_aucun_envoi(linked, monkeypatch):
    add_bank(monkeypatch)
    linked.min_version = "9.0.0"
    ctx = Context(open_vault(cfg.data_dir()))
    linked.sync_requested.add(ctx.config.banks[0].bank_id)
    tick(ctx)
    assert len(linked.pushes) == 1


def test_echeances():
    bank = cfg.Bank(bank_id="b", module="m", label="l")
    ctx = type("C", (), {"config": cfg.Config(interval_hours=12), "save": lambda self: None})()
    schedule(ctx, bank, "unavailable", now=1000)
    assert bank.next_sync_at == 1000 + 15 * 60 and not bank.paused
    schedule(ctx, bank, "unavailable", now=1000)
    assert bank.next_sync_at == 1000 + 30 * 60
    schedule(ctx, bank, "sca", now=1000)
    assert bank.paused and not due(bank, now=10**10, requested=False)
    assert due(bank, now=0, requested=True)
    schedule(ctx, bank, "ok", now=1000)
    assert not bank.paused and bank.failures == 0
    assert 1000 + 12 * 3600 <= bank.next_sync_at <= 1000 + 12 * 3600 + 300


def test_aucun_secret_ni_donnee_dans_le_journal_ni_l_environnement(linked, monkeypatch):
    add_bank(monkeypatch)
    log = (cfg.data_dir() / "logs" / "connector.log").read_text()
    for secret in ("mdp-fakebank-7f3a", "finz_jeton", "CAFE", "1520", "CC001"):
        assert secret not in log
    assert not any("mdp-fakebank-7f3a" in v for v in os.environ.values())


def test_retrait_d_une_banque(linked, monkeypatch):
    add_bank(monkeypatch)
    [bank] = cfg.load().banks
    assert cli.main(["bank", "remove", "fakebank"]) == 0
    assert cfg.load().banks == []
    assert bank.bank_id not in linked.banks
    assert open_vault(cfg.data_dir()).get(f"bank:{bank.bank_id}") is None
