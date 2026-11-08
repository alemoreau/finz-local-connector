import io
import json
import threading
import time

from finz_local_connector import config as cfg
from finz_local_connector.serve import Server
from finz_local_connector.sync import Context
from finz_local_connector.vault import open_vault


class Out(io.StringIO):
    def messages(self):
        return [json.loads(line) for line in self.getvalue().splitlines() if line]


def server(env):
    out = Out()
    return Server(Context(open_vault(cfg.data_dir())), out=out, scheduler=False), out


def call(srv, request, method, params=None):
    srv._handle({"id": request, "method": method, "params": params or {}})
    return next(m for m in reversed(srv.out.messages()) if m.get("id") == request)


def test_liaison_puis_etat(env, finz):
    srv, _ = server(env)
    reply = call(srv, 1, "link", {"finz_url": "https://finz.example.org", "code": "ABCD-EFGH"})
    assert reply["result"]["linked"] is True
    assert reply["result"]["household_name"] == "Foyer test"

    bad = call(srv, 2, "link", {"finz_url": "https://finz.example.org", "code": "ZZZZ-ZZZZ"})
    assert "Code refusé" in bad["error"]["message"]


def test_formulaire_d_un_module(env):
    srv, _ = server(env)
    reply = call(srv, 1, "describe", {"module": "fakebank"})
    assert [f["id"] for f in reply["result"]["fields"]] == ["login", "password", "scenario"]
    assert reply["result"]["fields"][1]["masked"] is True


def test_question_de_la_banque_posee_a_l_interface(env, finz):
    srv, out = server(env)
    call(srv, 1, "link", {"finz_url": "https://finz.example.org", "code": "ABCD-EFGH"})
    params = {"module": "fakebank", "values": {"login": "42", "password": "mdp-fakebank-7f3a", "scenario": "otp"}}
    worker = threading.Thread(target=srv._handle, args=({"id": 2, "method": "add_bank", "params": params},))
    worker.start()

    deadline = time.time() + 10
    while not any(m.get("event") == "question" for m in out.messages()):
        assert time.time() < deadline, out.getvalue()
        time.sleep(0.05)

    question = next(m for m in out.messages() if m.get("event") == "question")
    assert question["field"]["id"] == "code" and question["request"] == 2
    srv._handle({"id": 3, "method": "answer", "params": {"request": 2, "value": "123456"}})
    worker.join(10)

    reply = next(m for m in out.messages() if m.get("id") == 2)
    assert reply["result"]["outcome"] == "ok"
    assert len(finz.pushes) == 1
    assert "mdp-fakebank-7f3a" not in out.getvalue()


def test_erreur_inattendue_sans_trace(env):
    srv, _ = server(env)
    reply = call(srv, 1, "remove_bank", {"bank_id": "inconnue"})
    assert reply["error"]["message"] == "Banque inconnue."
    assert "Traceback" not in srv.out.getvalue()
