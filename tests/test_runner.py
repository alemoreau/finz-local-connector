from datetime import date

import pytest
from woob.exceptions import BrowserIncorrectPassword, NeedInteractiveFor2FA

from finz_local_connector.runner import read_bank
from finz_local_connector.storage import EncryptedStorage
from finz_local_connector.vault import generate_key

MODULES = str(__import__('pathlib').Path(__file__).parent / 'modules')

PARAMS = {"login": "42", "password": "mdp-fakebank-7f3a"}


KEY = generate_key().encode()


@pytest.fixture
def storage(tmp_path):
    return EncryptedStorage(tmp_path / "s.enc", KEY)


def read(storage, **kwargs):
    params = {**PARAMS, **kwargs.pop("params", {})}
    return read_bank("fakebank", "banque-1", params, storage, MODULES, **kwargs)


def test_lecture_complete_au_format_woob(storage):
    reading = read(storage)
    assert [a["id"] for a in reading.accounts] == ["CC001", "PEA01"]
    assert [t["raw"] for t in reading.history["CC001"]] == [
        "CB CAFE DU COIN",
        "CB CAFE DU COIN",
        "VIR SALAIRE",
        "TRES ANCIEN",
    ]
    assert reading.history["CC001"][0]["amount"] == "-3.50"
    assert reading.history["CC001"][0]["date"] == "2026-11-05"
    assert "CC001" not in reading.investments
    assert reading.investments["PEA01"][0]["code"] == "LU1681043599"
    assert reading.market_orders["PEA01"][0]["direction"] == 1


def test_fenetre_de_reprise(storage):
    reading = read(storage, since=date(2026, 1, 1))
    assert [t["raw"] for t in reading.history["CC001"]] == [
        "CB CAFE DU COIN",
        "CB CAFE DU COIN",
        "VIR SALAIRE",
    ]


def test_un_compte_illisible_n_empeche_pas_les_autres(storage):
    reading = read(storage, params={"scenario": "pea_broken"})
    assert reading.account_errors == {"PEA01": "connector"}
    assert len(reading.history["CC001"]) == 4


def test_identifiants_refuses(storage):
    with pytest.raises(BrowserIncorrectPassword):
        read(storage, params={"password": "faux"})


def test_synchro_planifiee_ne_pose_aucune_question(storage):
    with pytest.raises(NeedInteractiveFor2FA):
        read(storage, params={"scenario": "otp"})


def test_code_par_sms_puis_session_gardee(storage, tmp_path):
    asked = []

    def ask(value):
        asked.append(value.id)
        return "123456"

    reading = read(storage, params={"scenario": "otp"}, interactive=True, ask=ask)
    assert asked == ["code"]
    assert len(reading.accounts) == 2

    # Session gardée (stockage chiffré relu depuis le disque) : la synchro planifiée suivante
    # passe sans question.
    again = EncryptedStorage(storage.path, KEY)
    assert len(read(again, params={"scenario": "otp"}).accounts) == 2


def test_validation_dans_l_application(storage):
    messages = []
    reading = read(storage, params={"scenario": "app"}, interactive=True, ask=lambda v: "", notify=messages.append)
    assert messages == ["Validez la connexion dans l'application Fakebank."]
    assert len(reading.accounts) == 2


def test_forme_de_l_adresse_sans_identifiants():
    from types import SimpleNamespace

    from finz_local_connector.runner import _page_shape

    browser = SimpleNamespace(url="https://clients.boursobank.com/compte/pea/9a8b7c6d5e4f/positions?x=1")
    assert _page_shape(SimpleNamespace(browser=browser)) == "/compte/pea/<id>/positions"
    assert _page_shape(SimpleNamespace()) == "?"
