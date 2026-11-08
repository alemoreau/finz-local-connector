"""Exceptions de woob → type d'erreur envoyé à Finz (spec §5.5).

Finz ne reçoit que le type et le nom de la classe, jamais le message ni la trace : ils peuvent
contenir des données personnelles et restent dans le journal local.
"""

from __future__ import annotations

import requests
from woob import exceptions as w

# Ordre important : une sous-classe avant sa classe mère (BrowserUserBanned hérite de
# BrowserIncorrectPassword, ScrapingBlocked et BrowserSSLError de BrowserUnavailable).
_KINDS: list[tuple[type[BaseException], str]] = [
    (w.BrowserUserBanned, "blocked"),
    (w.BrowserForbidden, "blocked"),
    (w.BrowserIncorrectPassword, "credentials"),
    (w.BrowserPasswordExpired, "credentials"),
    (w.CaptchaQuestion, "captcha"),
    (w.NeedInteractive, "sca"),
    (w.BrowserQuestion, "sca"),
    (w.DecoupledValidation, "sca"),
    (w.AppValidationError, "sca"),
    (w.ActionNeeded, "action_needed"),
    (w.BrowserRedirect, "action_needed"),
    (w.BrowserUnavailable, "unavailable"),
    (requests.exceptions.ConnectionError, "unavailable"),
    (requests.exceptions.Timeout, "unavailable"),
]


def kind(error: BaseException) -> str:
    """Type d'erreur de la spec : credentials, blocked, sca, captcha, action_needed,
    unavailable ou connector (tout le reste : site changé, bogue de module)."""
    for cls, name in _KINDS:
        if isinstance(error, cls):
            return name
    return "connector"


def describe(error: BaseException) -> dict[str, str]:
    """Erreur telle qu'envoyée à Finz : type et classe, sans message."""
    return {"kind": kind(error), "exception": type(error).__name__}


class ConnectorError(Exception):
    """Erreur du connecteur lui-même, montrée telle quelle à l'utilisateur (en français)."""
