"""Correctifs locaux des modules woob (`patches/`), vérifiés sur les modules figés."""

from pathlib import Path
from types import SimpleNamespace

import lxml.html
import pytest

MODULES = Path(__file__).resolve().parent.parent / "vendor" / "woob-modules"

# Page d'attente anti-robot de BoursoBank (novembre 2026) : un titre, aucun formulaire.
STUB = """<!DOCTYPE html><html><head><title>Espace Client BoursoBank</title>
<script type="text/javascript">document.cookie="__brs_mit=0123abcd; domain=." + window.location.hostname + "; path=/; ";
window.location.reload();</script></head><body></body></html>"""
LOGIN = """<html><head><title>Espace Client BoursoBank</title></head>
<body><form name="form"><input name="form[clientNumber]"></form></body></html>"""


@pytest.fixture(scope="module")
def boursorama_pages():
    if not (MODULES / "boursorama").is_dir():
        pytest.skip("modules woob absents : scripts/fetch-modules.sh")
    from woob.core import WoobBase

    WoobBase(modules_path=str(MODULES)).modules_loader.get_or_load_module("boursorama")
    from woob_modules.boursorama import pages

    return pages


def test_boursorama_page_d_attente_anti_robot_pas_encore_chargee(boursorama_pages):
    page = SimpleNamespace(doc=lxml.html.fromstring(STUB))
    assert boursorama_pages.PasswordPage.is_html_loaded(page) is False
    assert boursorama_pages.PasswordPage.get_document_cookie(page) == ("__brs_mit", "0123abcd")


def test_boursorama_page_de_connexion_chargee(boursorama_pages):
    page = SimpleNamespace(doc=lxml.html.fromstring(LOGIN))
    assert boursorama_pages.PasswordPage.is_html_loaded(page) is True


def test_boursorama_page_d_un_compte_courant_reconnue(boursorama_pages):
    # Woob 3.7 n'attendait que `/compte/cav/<id>/mouvements` : l'adresse d'un compte sans
    # `/mouvements` ne donnait aucune page (AttributeError sur `fill_account`).
    from woob.core import WoobBase

    backend = WoobBase(modules_path=str(MODULES)).build_backend(
        "boursorama", params={"login": "0", "password": "0"}, name="test"
    )
    browser = backend.browser
    assert browser.history.match(browser.BASEURL + "/compte/cav/0123abcd/")


def test_boursorama_historique_d_un_pea_lu_comme_un_compte_titres(boursorama_pages):
    # Woob ne route vers la lecture des comptes titres que marché, assurance-vie et PER : la
    # page « mouvements » d'un PEA, lue comme celle d'un compte courant, levait AttributeError.
    import inspect

    from woob.capabilities.bank import Account
    from woob.core import WoobBase

    backend = WoobBase(modules_path=str(MODULES)).build_backend(
        "boursorama", params={"login": "0", "password": "0"}, name="test"
    )
    browser = backend.browser
    browser.get_invest_transactions = lambda account, coming: ["lecture compte titres"]
    browser.get_regular_transactions = lambda account, coming: ["lecture compte courant"]
    get_history = inspect.unwrap(type(browser).get_history)

    pea = Account(id="PEA01", url=browser.BASEURL + "/compte/pea/0123abcd/")
    pea.type, pea.label = Account.TYPE_PEA, "PEA"
    assert list(get_history(browser, pea)) == ["lecture compte titres"]


# Page « Positions » d'un compte SCPI de BoursoBank (structure relevée en novembre 2026,
# valeurs inventées).
SCPI_POSITIONS = """<html><body>
<h2>Positions</h2>
<table class="c-table c-table--action c-table--full">
<thead><tr class="c-table__row ">
<th class="c-table__cell c-table__cell--header c-table__cell--left">SCPI</th>
<th class="c-table__cell c-table__cell--header c-table__cell--left">Société de gestion</th>
<th class="c-table__cell c-table__cell--header c-table__cell--center">Nombre total de parts</th>
<th class="c-table__cell c-table__cell--header c-table__cell--right">Valorisation totale (1)</th>
</tr></thead>
<tbody>
<tr class="c-table__row "><td class="c-table__cell c-table__cell--column c-table__cell--left"><div class="c-table__cell-wrapper"><div class="c-table__cell-content-wrapper"><a class="c-link c-link--animated "><span class="c-link__label ">PIERRE EXEMPLE</span></a></div><span class="c-table__mention">SC0000000001</span></div></td>
<td class="c-table__cell c-table__cell--line c-table__cell--left"><div class="c-table__cell-wrapper"><div class="c-table__cell-content-wrapper"><span class="u-ellipsis ">Gestion Exemple</span></div></div></td>
<td class="c-table__cell c-table__cell--line c-table__cell--center"><div class="c-table__cell-wrapper"><div class="c-table__cell-content-wrapper"><span class="u-ellipsis ">12</span></div></div></td>
<td class="c-table__cell c-table__cell--line c-table__cell--right"><div class="c-table__cell-wrapper"><div class="c-table__cell-content-wrapper"><span class="u-ellipsis u-color-positive">2 400,00 €</span></div></div></td></tr>
<tr class="c-table__row "><td class="c-table__cell c-table__cell--column c-table__cell--left"><div class="c-table__cell-wrapper"><div class="c-table__cell-content-wrapper"><a class="c-link c-link--animated "><span class="c-link__label ">RENDEMENT FICTIF</span></a></div><span class="c-table__mention">SC0000000002</span></div></td>
<td class="c-table__cell c-table__cell--line c-table__cell--left"><div class="c-table__cell-wrapper"><div class="c-table__cell-content-wrapper"><span class="u-ellipsis ">Autre Gestion</span></div></div></td>
<td class="c-table__cell c-table__cell--line c-table__cell--center"><div class="c-table__cell-wrapper"><div class="c-table__cell-content-wrapper"><span class="u-ellipsis ">3</span></div></div></td>
<td class="c-table__cell c-table__cell--line c-table__cell--right"><div class="c-table__cell-wrapper"><div class="c-table__cell-content-wrapper"><span class="u-ellipsis u-color-positive">1 000,50 €</span></div></div></td></tr>
</tbody></table>
<p>(1) Les SCPI sont valorisées à la valeur de retrait</p>
</body></html>"""


def _browser():
    from woob.core import WoobBase

    backend = WoobBase(modules_path=str(MODULES)).build_backend(
        "boursorama", params={"login": "0", "password": "0"}, name="test"
    )
    return backend.browser


def test_boursorama_compte_scpi_reconnu_comme_immobilier(boursorama_pages):
    # Sans type, le connecteur ne demandait pas les positions et woob lisait la page
    # « mouvements » comme un historique d'opérations (AttributeError).
    from woob.capabilities.bank import Account

    assert boursorama_pages.ACCOUNT_TYPES["scpi"] == Account.TYPE_REAL_ESTATE
    browser = _browser()
    for page in ("positions", "mouvements"):
        url = browser.BASEURL + f"/compte/scpi/0123abcd/{page}"
        assert browser.scpi.match(url)


def test_boursorama_page_scpi_avant_la_page_titres(boursorama_pages):
    # La page générique des comptes titres (`market`) attrape aussi `/compte/scpi/` : la page
    # SCPI doit être déclarée avant elle pour être choisie.
    browser = _browser()
    url = browser.BASEURL + "/compte/scpi/0123abcd/positions"
    first = next(name for name, u in browser._urls.items() if u.match(url))
    assert first == "scpi"


def test_boursorama_positions_d_une_scpi(boursorama_pages):
    from decimal import Decimal

    from woob.browser.pages import HTMLPage

    page = boursorama_pages.ScpiPage(
        _browser(),
        SimpleNamespace(
            url="https://clients.boursobank.com/compte/scpi/0123abcd/positions",
            headers={},
            encoding="utf-8",
            content=SCPI_POSITIONS.encode(),
            text=SCPI_POSITIONS,
        ),
    )
    assert isinstance(page, HTMLPage)
    lines = list(page.iter_investment())

    assert [(i.label, i.code, i.quantity, i.valuation, i.unitvalue) for i in lines] == [
        ("PIERRE EXEMPLE", "SC0000000001", Decimal("12"), Decimal("2400.00"), Decimal("200.00")),
        ("RENDEMENT FICTIF", "SC0000000002", Decimal("3"), Decimal("1000.50"), Decimal("333.50")),
    ]


def test_boursorama_pas_d_historique_pour_une_scpi(boursorama_pages):
    # « Mouvements » d'une SCPI ne liste que des souscriptions : aucun historique à lire.
    import inspect

    from woob.capabilities.bank import Account

    browser = _browser()
    get_history = inspect.unwrap(type(browser).get_history)
    scpi = Account(id="SCPI01", url=browser.BASEURL + "/compte/scpi/0123abcd")
    scpi.type, scpi.label = Account.TYPE_REAL_ESTATE, "SCPI"
    assert list(get_history(browser, scpi)) == []
