"""Banque factice des tests : données fixes, chaque erreur à la demande (`scenario`)."""

from datetime import date
from decimal import Decimal

from woob.capabilities.bank import Account, AccountType, Transaction
from woob.capabilities.bank.wealth import CapBankWealth, Investment, MarketOrder, MarketOrderDirection
from woob.exceptions import (
    ActionNeeded,
    AppValidation,
    BrowserIncorrectPassword,
    BrowserQuestion,
    BrowserUnavailable,
    CaptchaQuestion,
    NeedInteractiveFor2FA,
)
from woob.tools.backend import BackendConfig, Module
from woob.tools.value import Value, ValueBackendPassword, ValueTransient

__all__ = ["FakebankModule"]


class FakebankModule(Module, CapBankWealth):
    NAME = "fakebank"
    DESCRIPTION = "Banque factice"
    MAINTAINER = "Finz"
    EMAIL = "tests@example.org"
    LICENSE = "LGPLv3+"

    CONFIG = BackendConfig(
        Value("login", label="Identifiant"),
        ValueBackendPassword("password", label="Mot de passe"),
        Value("scenario", label="Scénario", default="ok", required=False),
        ValueTransient("code"),
        ValueTransient("resume"),
        ValueTransient("request_information"),
    )

    def _login(self):
        if self.config["password"].get() != "mdp-fakebank-7f3a":
            raise BrowserIncorrectPassword()
        scenario = self.config["scenario"].get()
        errors = {
            "captcha": CaptchaQuestion("image_captcha"),
            "unavailable": BrowserUnavailable(),
            "action": ActionNeeded(),
            "crash": ValueError("page changée"),
        }
        if scenario in errors:
            raise errors[scenario]
        if scenario in ("otp", "app") and not self.storage.get("validated"):
            if self.config["request_information"].get() is None:
                raise NeedInteractiveFor2FA()
            if scenario == "otp":
                code = self.config["code"].get()
                if not code:
                    raise BrowserQuestion(Value("code", label="Code reçu par SMS"))
                if code != "123456":
                    raise BrowserIncorrectPassword()
            elif not self.config["resume"].get():
                raise AppValidation("Validez la connexion dans l'application Fakebank.")
            self.storage.set("validated", True)
            self.storage.save()

    def iter_accounts(self):
        self._login()
        accounts = []
        for ident, label, kind, balance in [
            ("CC001", "Compte courant", AccountType.CHECKING, "1520.40"),
            ("PEA01", "PEA", AccountType.PEA, "8400.00"),
        ]:
            account = Account(id=ident)
            account.label, account.type, account.currency = label, kind, "EUR"
            account.balance = Decimal(balance)
            accounts.append(account)
        return accounts

    def iter_history(self, account):
        if account.id == "PEA01" and self.config["scenario"].get() == "pea_broken":
            raise ValueError("historique illisible")
        for day, raw, amount in [
            (date(2026, 11, 5), "CB CAFE DU COIN", "-3.50"),
            (date(2026, 11, 5), "CB CAFE DU COIN", "-3.50"),
            (date(2026, 10, 1), "VIR SALAIRE", "2000.00"),
            (date(2025, 1, 1), "TRES ANCIEN", "-1.00"),
        ]:
            if account.id != "CC001":
                return
            t = Transaction()
            t.date, t.raw, t.amount, t.label = day, raw, Decimal(amount), raw.title()
            yield t

    def iter_investment(self, account):
        i = Investment()
        i.label, i.code, i.code_type = "AMUNDI MSCI WORLD", "LU1681043599", "ISIN"
        i.quantity, i.unitvalue, i.valuation = Decimal("12"), Decimal("450"), Decimal("5400")
        return [i]

    def iter_market_orders(self, account):
        o = MarketOrder(id="ORD1")
        o.label, o.code, o.direction = "AMUNDI MSCI WORLD", "LU1681043599", MarketOrderDirection.BUY
        o.quantity, o.unitprice, o.date, o.state = Decimal("12"), Decimal("400"), date(2026, 9, 15), "Exécuté"
        return [o]
