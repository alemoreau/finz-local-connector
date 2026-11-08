"""Mode `serve --stdio` : le connecteur piloté par l'application de bureau (spec §5.8).

Une requête par ligne JSON sur l'entrée standard, une réponse ou un événement par ligne JSON
sur la sortie standard :

    → {"id": 1, "method": "status", "params": {}}
    ← {"id": 1, "result": {...}}
    ← {"id": 2, "error": {"message": "…"}}
    ← {"event": "question", "request": 3, "field": {"id": "code", "label": "…", "masked": false}}
    → {"id": 4, "method": "answer", "params": {"request": 3, "value": "123456"}}
    ← {"event": "validation", "request": 3, "message": "Validez dans l'application…"}
    ← {"event": "synced", "bank_id": "…", "outcome": "ok"}

Les méthodes longues (`add_bank`, `sync`) tournent dans un fil à part ; les questions de la
banque attendent la réponse `answer`. Le service planifié (`tick`) tourne aussi ici, dans un
fil, tant que l'application est ouverte. Les secrets n'arrivent que par l'entrée standard.
"""

from __future__ import annotations

import json
import queue
import sys
import threading
import time
import uuid
from dataclasses import asdict

from . import __version__, banks, config as cfg
from .errors import ConnectorError
from .finz import FinzClient
from .sync import Context, sync_bank, tick
from .vault import open_vault


class Server:
    def __init__(self, ctx: Context | None = None, out=None, scheduler: bool = True):
        self.ctx = ctx or Context(open_vault(cfg.data_dir()))
        self.out = out or sys.stdout
        self._lock = threading.Lock()
        self._answers: dict[int, queue.Queue] = {}
        self._busy = threading.Lock()
        self.scheduler = scheduler

    # --- Sortie ----------------------------------------------------------------------------

    def emit(self, message: dict) -> None:
        with self._lock:
            self.out.write(json.dumps(message, ensure_ascii=False) + "\n")
            self.out.flush()

    # --- Méthodes --------------------------------------------------------------------------

    def m_status(self, _params, _request):
        config = self.ctx.config
        return {
            "version": __version__,
            "linked": config.linked,
            "finz_url": config.finz_url,
            "household_name": config.household_name,
            "interval_hours": config.interval_hours,
            "banks": [
                {"bank_id": b.bank_id, "module": b.module, "label": b.label, "paused": b.paused,
                 "next_sync_at": b.next_sync_at}
                for b in config.banks
            ],
        }

    def m_link(self, params, _request):
        import platform
        import socket

        client = FinzClient(params["finz_url"])
        result = client.pair(
            params["code"],
            params.get("device_name") or socket.gethostname() or "Ordinateur",
            f"{platform.system().lower()}-{platform.machine().lower()}",
        )
        self.ctx.vault.set("finz-token", result["token"])
        self.ctx.config.finz_url = client.base_url
        self.ctx.config.connector_id = result["local_connector_id"]
        self.ctx.config.household_name = result.get("household_name")
        self.ctx._client = None
        self.ctx.save()
        return self.m_status({}, None)

    def m_modules(self, params, _request):
        return [
            {"name": m.name, "description": m.description}
            for m in banks.available(search=params.get("search"))
        ]

    def m_describe(self, params, _request):
        module = banks.describe(params["module"])
        return {"name": module.name, "description": module.description,
                "fields": [asdict(f) for f in module.fields]}

    def m_add_bank(self, params, request):
        module = banks.describe(params["module"])
        label = (params.get("label") or module.description)[:120]
        bank = cfg.Bank(bank_id=str(uuid.uuid4()), module=module.name, label=label)
        bank.connection_id = self.ctx.client.add_bank(bank.bank_id, module.name, label)["connection_id"]
        self.ctx.vault.set(f"bank:{bank.bank_id}", json.dumps(params.get("values") or {}))
        self.ctx.config.banks.append(bank)
        self.ctx.save()
        return {"bank_id": bank.bank_id, "outcome": self._sync(bank, request)}

    def m_set_credentials(self, params, request):
        bank = self._bank(params["bank_id"])
        self.ctx.vault.set(f"bank:{bank.bank_id}", json.dumps(params.get("values") or {}))
        return {"bank_id": bank.bank_id, "outcome": self._sync(bank, request)}

    def m_sync(self, params, request):
        targets = [self._bank(params["bank_id"])] if params.get("bank_id") else list(self.ctx.config.banks)
        return {b.bank_id: self._sync(b, request) for b in targets}

    def m_remove_bank(self, params, _request):
        bank = self._bank(params["bank_id"])
        self.ctx.client.remove_bank(bank.bank_id)
        self.ctx.vault.delete(f"bank:{bank.bank_id}")
        (cfg.data_dir() / "sessions" / f"{bank.bank_id}.enc").unlink(missing_ok=True)
        self.ctx.config.banks = [b for b in self.ctx.config.banks if b.bank_id != bank.bank_id]
        self.ctx.save()
        return self.m_status({}, None)

    def m_settings(self, params, _request):
        hours = params.get("interval_hours")
        if hours is not None:
            if hours not in cfg.INTERVALS_HOURS:
                raise ConnectorError("Fréquence possible : 6, 12 ou 24 heures.")
            self.ctx.config.interval_hours = hours
            self.ctx.save()
        return self.m_status({}, None)

    def m_unlink(self, _params, _request):
        for bank in self.ctx.config.banks:
            self.ctx.vault.delete(f"bank:{bank.bank_id}")
            (cfg.data_dir() / "sessions" / f"{bank.bank_id}.enc").unlink(missing_ok=True)
        self.ctx.vault.delete("finz-token")
        self.ctx.config = cfg.Config()
        self.ctx._client = None
        self.ctx.save()
        return self.m_status({}, None)

    def m_answer(self, params, _request):
        waiting = self._answers.get(params["request"])
        if waiting is None:
            raise ConnectorError("Aucune question en attente.")
        waiting.put(params.get("value", ""))
        return True

    # --- Outils ----------------------------------------------------------------------------

    def _bank(self, bank_id: str) -> cfg.Bank:
        bank = self.ctx.config.bank(bank_id)
        if bank is None:
            raise ConnectorError("Banque inconnue.")
        return bank

    def _sync(self, bank: cfg.Bank, request: int | None) -> str:
        def ask(value):
            answers = self._answers.setdefault(request, queue.Queue())
            self.emit({
                "event": "question",
                "request": request,
                "field": {"id": value.id, "label": value.label or value.description or value.id,
                          "masked": bool(getattr(value, "masked", False))},
            })
            return answers.get(timeout=600)

        def notify(message):
            self.emit({"event": "validation", "request": request, "message": message})

        with self._busy:
            try:
                outcome = sync_bank(self.ctx, bank, interactive=True, ask=ask, notify=notify)
            finally:
                self._answers.pop(request, None)
        self.emit({"event": "synced", "bank_id": bank.bank_id, "outcome": outcome})
        return outcome

    def _handle(self, message: dict) -> None:
        request = message.get("id")
        method = getattr(self, "m_" + str(message.get("method")), None)
        try:
            if method is None:
                raise ConnectorError("Méthode inconnue.")
            result = method(message.get("params") or {}, request)
            self.emit({"id": request, "result": result})
        except ConnectorError as error:
            self.emit({"id": request, "error": {"message": str(error), "code": getattr(error, "code", None)}})
        except Exception as error:  # jamais de trace vers l'interface : type seulement
            self.emit({"id": request, "error": {"message": f"Erreur inattendue ({type(error).__name__})."}})

    def _scheduler(self) -> None:
        while True:
            pause = 300
            if self.ctx.config.linked and self._busy.acquire(blocking=False):
                try:
                    status = tick(self.ctx)
                    pause = int(status.get("poll_seconds") or 300)
                    self.emit({"event": "status", "result": self.m_status({}, None)})
                except Exception:
                    pass
                finally:
                    self._busy.release()
            time.sleep(max(pause, 60))

    def serve(self, stream=None) -> None:
        if self.scheduler:
            threading.Thread(target=self._scheduler, daemon=True).start()
        for line in stream or sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                self.emit({"error": {"message": "Ligne illisible."}})
                continue
            if message.get("method") in ("answer", "status", "modules", "describe", "settings"):
                self._handle(message)
            else:
                threading.Thread(target=self._handle, args=(message,), daemon=True).start()
