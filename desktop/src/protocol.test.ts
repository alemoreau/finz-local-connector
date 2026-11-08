import { describe, expect, it } from "vitest";
import { ConnectorError, Protocol } from "./protocol";
import { bankState, escape, outcomeText } from "./texts";

function setup() {
  const written: string[] = [];
  const protocol = new Protocol((line) => {
    written.push(line);
  });
  return { protocol, written };
}

describe("Protocol", () => {
  it("associe chaque réponse à sa requête", async () => {
    const { protocol, written } = setup();
    const a = protocol.call("status");
    const b = protocol.call("modules", { search: "bourso" });
    expect(JSON.parse(written[1])).toEqual({ id: 2, method: "modules", params: { search: "bourso" } });

    protocol.receive('{"id": 2, "result": [1]}\n{"id": 1, "result": {"linked": true}}\n');
    await expect(b.result).resolves.toEqual([1]);
    await expect(a.result).resolves.toEqual({ linked: true });
  });

  it("recolle une ligne coupée en deux", async () => {
    const { protocol } = setup();
    const call = protocol.call("status");
    protocol.receive('{"id": 1, "res');
    protocol.receive('ult": 42}\n');
    await expect(call.result).resolves.toBe(42);
  });

  it("transmet les erreurs et les événements", async () => {
    const { protocol } = setup();
    const events: unknown[] = [];
    protocol.onEvent((event) => events.push(event));
    const call = protocol.call("link");
    protocol.receiveLine('{"event": "question", "request": 1, "field": {"id": "code", "label": "Code", "masked": false}}');
    protocol.receiveLine('{"id": 1, "error": {"message": "Code refusé"}}');
    await expect(call.result).rejects.toThrow(new ConnectorError("Code refusé"));
    expect(events).toHaveLength(1);
  });

  it("fait échouer les requêtes en cours si le connecteur s'arrête", async () => {
    const { protocol } = setup();
    const call = protocol.call("sync");
    protocol.close();
    await expect(call.result).rejects.toThrow("Le connecteur s'est arrêté.");
  });

  it("ignore une ligne illisible", async () => {
    const { protocol } = setup();
    const call = protocol.call("status");
    protocol.receiveLine("pas du json");
    protocol.receiveLine('{"id": 1, "result": true}');
    await expect(call.result).resolves.toBe(true);
  });
});

describe("textes", () => {
  it("chaque type d'erreur a son texte, un type inconnu aussi", () => {
    expect(outcomeText("credentials")).toBe("Identifiants refusés : corrigez-les.");
    expect(outcomeText("inconnu")).toBe(outcomeText("connector"));
  });

  it("état d'une banque", () => {
    expect(bankState({ paused: true, next_sync_at: 0 })).toBe("Action requise");
    expect(bankState({ paused: false, next_sync_at: 0 })).toBe("Synchro à la prochaine occasion");
  });

  it("échappe le texte venu de l'extérieur", () => {
    expect(escape('<img src=x onerror="a">')).toBe("&lt;img src=x onerror=&quot;a&quot;&gt;");
  });
});
