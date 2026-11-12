"""Module woob Mon Petit Placement (`patches/0003-monpetitplacement.patch`).

Réponses de l'API reconstituées d'après une sonde réelle (`scripts/probe_monpetitplacement.py`,
novembre 2026) : mêmes champs et mêmes types, valeurs inventées.
"""

from decimal import Decimal
from pathlib import Path

import pytest

MODULES = Path(__file__).resolve().parent.parent / "vendor" / "woob-modules"

ACCOUNT = "/v1/user_investment_accounts/acc-1"
FUND_A = "/v1/products/prod-a"
FUND_B = "/v1/products/prod-b"

API = {
    "/v1/me": {
        "@type": "MeOutput",
        "userInvestmentAccounts": [ACCOUNT, "/v1/user_investment_accounts/hidden"],
        "proxyUserInvestmentAccounts": [],
    },
    ACCOUNT: {
        "@type": "UserInvestmentAccount",
        "id": "acc-1",
        "status": "active",
        "hidden": False,
        "providerContractId": "51000123",
        "effectiveDate": "2022-04-05T00:00:00+02:00",
        "subscriptionDate": "2022-04-01T00:00:00+02:00",
        "provider": "/v1/providers/apicil",
        "providerContractType": "/v1/provider_contract_types/liberalys",
    },
    "/v1/user_investment_accounts/hidden": {"id": "hidden", "status": "active", "hidden": True},
    "/v1/providers/apicil": {"name": "Apicil"},
    "/v1/provider_contract_types/liberalys": {
        "name": "Liberalys Vie",
        "investmentWrapper": "life-insurance",
    },
    f"{ACCOUNT}/investment_compartments": {
        "hydra:member": [{"name": "default", "investmentCompartment": "default", "amount": 1500.25}]
    },
    f"{ACCOUNT}/products_current_values": {
        "hydra:member": [
            {
                "amount": 1000.5,
                "investedAmount": 900.0,
                "securityUnits": 4.0,
                "averageAcquisitionAmount": 225.0,
                "performance": 11.17,
                "date": "2026-11-10T00:00:00+01:00",
                "product": {"@id": FUND_A, "name": "Comgest • Monde", "slug": "comgest-monde-eur-c"},
            },
            {
                "amount": 499.75,
                "investedAmount": 500,
                "securityUnits": 10.0,
                "averageAcquisitionAmount": 50.0,
                "performance": -0.05,
                "date": "2026-11-10T00:00:00+01:00",
                "product": {"@id": FUND_B, "name": "Fonds sans ISIN", "slug": "sans-isin"},
            },
        ]
    },
    FUND_A: {"name": "Comgest • Monde", "isin": "FR0000284689", "uc": True},
    FUND_B: {"name": "Fonds sans ISIN", "isin": "", "uc": True},
    f"{ACCOUNT}/invest_orders": {
        "hydra:member": [
            {
                "id": "ord-1",
                "type": "buy",
                "subType": "initial-investment",
                "status": "completed",
                "amountOrdered": 1000,
                "amountDebited": 1000,
                "createdAt": "2022-04-01T10:00:00+02:00",
                "processedAt": "2022-04-04T10:00:00+02:00",
                "valuatedAt": "2022-04-05T00:00:00+02:00",
                "investOrderDetails": [
                    {
                        "type": "buy",
                        "amountDebited": 1000.0,
                        "securityUnitReceived": "5.0",
                        "securityUnitValue": 200.0,
                        "product": {"name": "Comgest • Monde", "isin": "FR0000284689"},
                    }
                ],
            },
            {
                "id": "ord-2",
                "type": "buy",
                "subType": "monthly-investment",
                "status": "accepted",
                "amountOrdered": 100,
                "amountDebited": 0,
                "createdAt": "2026-11-05T10:00:00+01:00",
                "processedAt": "2026-11-06T10:00:00+01:00",
                "valuatedAt": "2026-11-07T00:00:00+01:00",
                "investOrderDetails": [],
            },
            {
                "id": "ord-3",
                "type": "exchange",
                "subType": "exchange",
                "status": "completed",
                "amountOrdered": 300,
                "amountDebited": 300,
                "valuatedAt": "2024-01-10T00:00:00+01:00",
                "investOrderDetails": [],
            },
        ]
    },
    f"{ACCOUNT}/investment_bills": {
        "hydra:member": [
            {
                "id": "bill-1",
                "status": "generated",
                "totalIncludingTax": 12.5,
                "startAt": "2025-01-01T00:00:00+01:00",
                "endAt": "2025-12-31T00:00:00+01:00",
            },
            {"id": "bill-0", "status": "generated", "totalIncludingTax": 0, "endAt": "2024-12-31T00:00:00+01:00"},
        ]
    },
}


@pytest.fixture
def browser():
    if not (MODULES / "monpetitplacement").is_dir():
        pytest.skip("modules woob absents : scripts/fetch-modules.sh")
    from woob.core import WoobBase

    backend = WoobBase(modules_path=str(MODULES)).build_backend(
        "monpetitplacement", params={"login": "moi@example.org", "password": "x"}, name="test"
    )
    browser = backend.browser
    browser.access_token = "jeton"
    browser.token_expires_at = float("inf")
    browser.get_json = lambda path, params=None: API[path]
    return browser


def test_compte_assurance_vie_avec_numero_de_contrat_et_solde(browser):
    from woob.capabilities.bank import Account

    accounts = list(browser.iter_accounts())
    assert len(accounts) == 1  # le contrat masqué est ignoré
    account = accounts[0]
    assert account.id == "51000123"
    assert account.number == "51000123"
    assert account.label == "Liberalys Vie (Apicil)"
    assert account.type == Account.TYPE_LIFE_INSURANCE
    assert account.balance == Decimal("1500.25")
    assert account.currency == "EUR"
    assert str(account.opening_date) == "2022-04-05"


def test_supports_avec_isin_lu_sur_la_fiche_du_fonds(browser):
    account = list(browser.iter_accounts())[0]
    fund_a, fund_b = browser.iter_investment(account)

    assert fund_a.label == "Comgest • Monde"
    assert (fund_a.code, fund_a.code_type) == ("FR0000284689", "ISIN")
    assert fund_a.valuation == Decimal("1000.5")
    assert fund_a.quantity == Decimal("4.0")
    assert fund_a.unitprice == Decimal("225.0")
    assert fund_a.unitvalue == Decimal("250.1250")
    assert fund_a.diff_ratio == Decimal("0.1117")
    assert str(fund_a.vdate) == "2026-11-10"
    assert not fund_b.code


def test_historique_versements_et_commission_sans_arbitrages(browser):
    from woob.capabilities.bank import Transaction

    account = list(browser.iter_accounts())[0]
    history = browser.iter_history(account)

    assert [tr.id for tr in history] == ["bill-1", "ord-1"]
    bill, deposit = history
    assert (bill.type, bill.amount, str(bill.date)) == (Transaction.TYPE_BANK, Decimal("-12.5"), "2025-12-31")
    assert (deposit.type, deposit.amount, deposit.label) == (
        Transaction.TYPE_DEPOSIT,
        Decimal("1000"),
        "Versement initial",
    )
    assert str(deposit.date) == "2022-04-05"
    assert deposit.investments[0].code == "FR0000284689"


def test_versement_programme_en_cours_a_venir(browser):
    account = list(browser.iter_accounts())[0]
    (coming,) = browser.iter_coming(account)
    assert coming.id == "ord-2"
    assert coming.amount == Decimal("100")  # montant ordonné, rien encore débité
    assert coming.coming is True


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        ({"error": "invalid_grant", "error_description": "Invalid user credentials"}, "BrowserIncorrectPassword"),
        ({"error": "invalid_grant", "error_description": "Account disabled"}, "ActionNeeded"),
        ({"error": "unauthorized_client"}, "BrowserUnavailable"),
    ],
)
def test_erreurs_de_connexion(browser, payload, error):
    import woob.exceptions

    class Response:
        status_code = 401

        def json(self):
            return payload

    with pytest.raises(getattr(woob.exceptions, error)):
        browser.raise_login_error(Response())
