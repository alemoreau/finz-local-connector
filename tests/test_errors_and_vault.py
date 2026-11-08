import pytest
import requests
from woob import exceptions as w

from finz_local_connector import errors, vault as vault_mod
from finz_local_connector.errors import ConnectorError
from finz_local_connector.finz import check_url
from finz_local_connector.storage import EncryptedStorage
from finz_local_connector.vault import FileVault, generate_key


@pytest.mark.parametrize(
    "error, kind",
    [
        (w.BrowserIncorrectPassword(), "credentials"),
        (w.BrowserPasswordExpired(), "credentials"),
        (w.BrowserUserBanned(), "blocked"),
        (w.BrowserForbidden(), "blocked"),
        (w.NeedInteractiveFor2FA(), "sca"),
        (w.BrowserQuestion(), "sca"),
        (w.AppValidation("x"), "sca"),
        (w.CaptchaQuestion("image_captcha"), "captcha"),
        (w.ActionNeeded(), "action_needed"),
        (w.BrowserUnavailable(), "unavailable"),
        (w.ScrapingBlocked(), "unavailable"),
        (requests.exceptions.ConnectionError(), "unavailable"),
        (w.ParseError(), "connector"),
        (ValueError("page changée"), "connector"),
    ],
)
def test_types_d_erreur(error, kind):
    assert errors.kind(error) == kind


def test_finz_ne_recoit_ni_message_ni_trace():
    described = errors.describe(w.BrowserIncorrectPassword("Mot de passe de M. DURAND refusé"))
    assert described == {"kind": "credentials", "exception": "BrowserIncorrectPassword"}


def test_https_obligatoire_sauf_localhost():
    assert check_url("https://app.example.org/") == "https://app.example.org"
    assert check_url("http://localhost:4000") == "http://localhost:4000"
    with pytest.raises(ConnectorError):
        check_url("http://app.example.org")


def test_secrets_chiffres_sur_disque(tmp_path):
    store = FileVault(tmp_path / "secrets.enc", generate_key().encode())
    store.set("finz-token", "finz_jeton_secret")
    assert store.get("finz-token") == "finz_jeton_secret"
    assert b"finz_jeton_secret" not in (tmp_path / "secrets.enc").read_bytes()
    store.delete("finz-token")
    assert store.get("finz-token") is None


def test_sans_trousseau_ni_cle_un_message_clair(tmp_path, monkeypatch):
    monkeypatch.delenv("FINZ_LOCAL_CONNECTOR_KEY", raising=False)
    monkeypatch.delenv("FINZ_LOCAL_CONNECTOR_KEY_FILE", raising=False)
    monkeypatch.delenv("FINZ_LOCAL_CONNECTOR_SECRETS", raising=False)
    monkeypatch.setattr(vault_mod, "_keyring_usable", lambda: False)
    with pytest.raises(ConnectorError, match="FINZ_LOCAL_CONNECTOR_KEY"):
        vault_mod.open_vault(tmp_path)


def test_cle_lue_dans_un_fichier(tmp_path, monkeypatch):
    key_file = tmp_path / "key"
    key_file.write_text(generate_key() + "\n")
    monkeypatch.delenv("FINZ_LOCAL_CONNECTOR_KEY", raising=False)
    monkeypatch.setenv("FINZ_LOCAL_CONNECTOR_KEY_FILE", str(key_file))
    assert isinstance(vault_mod.open_vault(tmp_path), FileVault)


def test_session_chiffree_et_relue(tmp_path):
    key = generate_key().encode()
    path = tmp_path / "s.enc"
    storage = EncryptedStorage(path, key)
    storage.load("backends", "b1")
    storage.set("backends", "b1", "browser_state", {"cookies": "SESSION=abc"})
    storage.save("backends", "b1")
    assert b"SESSION=abc" not in path.read_bytes()
    again = EncryptedStorage(path, key)
    assert again.get("backends", "b1", "browser_state") == {"cookies": "SESSION=abc"}
    assert EncryptedStorage(path, generate_key().encode()).values == {}
