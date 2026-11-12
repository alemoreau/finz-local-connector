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
