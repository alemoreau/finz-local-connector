// Dialogue avec le connecteur (`finz-local-connector serve --stdio`) : une ligne JSON par
// requête, réponse ou événement. Indépendant de Tauri, pour être testé seul.

export type ConnectorEvent =
  | { event: "question"; request: number; field: { id: string; label: string; masked: boolean } }
  | { event: "validation"; request: number; message: string }
  | { event: "synced"; bank_id: string; outcome: string }
  | { event: "status"; result: Status };

export interface Bank {
  bank_id: string;
  module: string;
  label: string;
  paused: boolean;
  next_sync_at: number;
}

export interface Status {
  version: string;
  linked: boolean;
  finz_url: string | null;
  household_name: string | null;
  interval_hours: number;
  banks: Bank[];
}

export interface Field {
  id: string;
  label: string;
  masked: boolean;
  required: boolean;
  choices: Record<string, string> | null;
  default: string | null;
}

export class ConnectorError extends Error {}

type Pending = { resolve: (value: unknown) => void; reject: (error: Error) => void };

export class Protocol {
  private nextId = 1;
  private pending = new Map<number, Pending>();
  private buffer = "";
  private listeners: Array<(event: ConnectorEvent) => void> = [];

  constructor(private write: (line: string) => Promise<void> | void) {}

  onEvent(listener: (event: ConnectorEvent) => void): void {
    this.listeners.push(listener);
  }

  /** Une ligne complète (le plugin shell de Tauri livre la sortie ligne par ligne). */
  receiveLine(line: string): void {
    this.handle(line.trim());
  }

  /** Flux brut, éventuellement coupé au milieu d'une ligne : mis en tampon. */
  receive(data: string): void {
    this.buffer += data;
    const lines = this.buffer.split("\n");
    this.buffer = lines.pop() ?? "";
    for (const line of lines) this.handle(line.trim());
  }

  call<T>(method: string, params: Record<string, unknown> = {}): { id: number; result: Promise<T> } {
    const id = this.nextId++;
    const result = new Promise<T>((resolve, reject) => {
      this.pending.set(id, { resolve: resolve as (value: unknown) => void, reject });
    });
    void this.write(JSON.stringify({ id, method, params }) + "\n");
    return { id, result };
  }

  /** Le connecteur s'est arrêté : toutes les requêtes en cours échouent. */
  close(message = "Le connecteur s'est arrêté."): void {
    for (const pending of this.pending.values()) pending.reject(new ConnectorError(message));
    this.pending.clear();
  }

  private handle(line: string): void {
    if (!line) return;
    let message: Record<string, unknown>;
    try {
      message = JSON.parse(line);
    } catch {
      return;
    }
    if (typeof message.event === "string") {
      for (const listener of this.listeners) listener(message as unknown as ConnectorEvent);
      return;
    }
    const pending = typeof message.id === "number" ? this.pending.get(message.id) : undefined;
    if (!pending) return;
    this.pending.delete(message.id as number);
    if (message.error) {
      const error = message.error as { message?: string };
      pending.reject(new ConnectorError(error.message ?? "Erreur du connecteur."));
    } else {
      pending.resolve(message.result);
    }
  }
}
