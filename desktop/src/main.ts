// Fenêtre du connecteur local : relier à Finz, banques, ajout, questions de la banque,
// réglages. Toute la logique est dans le connecteur Python (`serve --stdio`) ; cette fenêtre
// affiche et transmet. Les identifiants saisis ne passent que par l'entrée standard du
// connecteur.

import { listen } from "@tauri-apps/api/event";
import { disable, enable, isEnabled } from "@tauri-apps/plugin-autostart";
import { isPermissionGranted, requestPermission, sendNotification } from "@tauri-apps/plugin-notification";
import { relaunch } from "@tauri-apps/plugin-process";
import { Command, type Child } from "@tauri-apps/plugin-shell";
import { check } from "@tauri-apps/plugin-updater";
import { type ConnectorEvent, type Field, Protocol, type Status } from "./protocol";
import { bankState, escape, outcomeText } from "./texts";

type Screen =
  | { name: "loading" }
  | { name: "link"; error?: string }
  | { name: "banks"; message?: string }
  | { name: "modules"; modules: { name: string; description: string }[]; search: string }
  | { name: "form"; module: string; description: string; fields: Field[]; bankId?: string; error?: string }
  | { name: "question"; request: number; field?: { id: string; label: string; masked: boolean }; message?: string }
  | { name: "settings"; confirmUnlink?: boolean }
  | { name: "fatal"; message: string };

const FINZ_URL = "https://app.finz.alemoreau.fr";
const app = document.getElementById("app")!;
let child: Child | null = null;
let protocol: Protocol;
let status: Status | null = null;
let screen: Screen = { name: "loading" };
let busy = false;

// --- Connecteur ---------------------------------------------------------------------------

async function start(): Promise<void> {
  const command = Command.sidecar("binaries/finz-local-connector", ["serve", "--stdio"]);
  protocol = new Protocol(async (line) => {
    await child?.write(line);
  });
  command.stdout.on("data", (line) => protocol.receiveLine(line));
  command.on("close", () => {
    protocol.close();
    show({ name: "fatal", message: "Le connecteur s'est arrêté. Relancez l'application." });
  });
  protocol.onEvent(onEvent);
  child = await command.spawn();
  await refresh();
}

function call<T>(method: string, params: Record<string, unknown> = {}) {
  return protocol.call<T>(method, params);
}

async function refresh(message?: string): Promise<void> {
  status = await call<Status>("status").result;
  show(status.linked ? { name: "banks", message } : { name: "link" });
}

async function onEvent(event: ConnectorEvent): Promise<void> {
  if (event.event === "question") {
    show({ name: "question", request: event.request, field: event.field });
  } else if (event.event === "validation") {
    show({ name: "question", request: event.request, message: event.message });
  } else if (event.event === "status") {
    status = event.result;
    if (screen.name === "banks") render();
  } else if (event.event === "synced" && event.outcome !== "ok" && !busy) {
    await notify(outcomeText(event.outcome));
  }
}

async function notify(body: string): Promise<void> {
  let granted = await isPermissionGranted();
  if (!granted) granted = (await requestPermission()) === "granted";
  if (granted) sendNotification({ title: "Finz Connecteur local", body });
}

async function run<T>(work: () => Promise<T>): Promise<T | undefined> {
  busy = true;
  render();
  try {
    return await work();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (screen.name === "link") show({ name: "link", error: message });
    else if (screen.name === "form" || screen.name === "question") show({ name: "banks", message });
    else show({ name: "banks", message });
    return undefined;
  } finally {
    busy = false;
    render();
  }
}

// --- Écrans -------------------------------------------------------------------------------

function show(next: Screen): void {
  screen = next;
  render();
}

function render(): void {
  app.innerHTML = view();
  app.querySelector<HTMLElement>("[autofocus]")?.focus();
}

function header(title: string, back = false): string {
  return `<header class="bar">
    ${back ? `<button class="ghost" data-action="back" aria-label="Retour">←</button>` : `<span class="logo">F</span>`}
    <h1>${escape(title)}</h1>
    ${status?.linked && !back ? `<button class="ghost" data-action="settings" aria-label="Réglages">⚙</button>` : ""}
  </header>`;
}

function view(): string {
  switch (screen.name) {
    case "loading":
      return `<div class="center"><p class="muted">Démarrage…</p></div>`;
    case "fatal":
      return `${header("Connecteur local")}<p class="alert">${escape(screen.message)}</p>`;
    case "link":
      return `${header("Relier à Finz")}
        <p class="muted">Dans Finz, ouvrez <b>Connexions › Connecteur local › Relier un connecteur</b>, puis saisissez le code affiché.</p>
        <form data-form="link" class="stack">
          <label>Adresse de Finz<input name="finz_url" value="${escape(FINZ_URL)}" required /></label>
          <label>Code<input name="code" placeholder="ABCD-EFGH" autocomplete="off" required autofocus /></label>
          ${screen.error ? `<p class="alert">${escape(screen.error)}</p>` : ""}
          <button ${busy ? "disabled" : ""}>Relier</button>
        </form>`;
    case "banks":
      return `${header("Mes banques")}
        <p class="muted">Relié à ${escape(status?.household_name ?? status?.finz_url)}. Vos identifiants restent sur cet ordinateur.</p>
        ${screen.message ? `<p class="note">${escape(screen.message)}</p>` : ""}
        <ul class="list">${(status?.banks ?? [])
          .map(
            (b) => `<li><div><b>${escape(b.label)}</b><span class="${b.paused ? "warn" : "muted"}">${escape(bankState(b))}</span></div>
              <div class="row">
                <button class="secondary" data-action="sync" data-id="${escape(b.bank_id)}" ${busy ? "disabled" : ""}>Synchroniser</button>
                ${b.paused ? `<button class="ghost" data-action="credentials" data-id="${escape(b.bank_id)}" data-module="${escape(b.module)}">Identifiants</button>` : ""}
              </div></li>`,
          )
          .join("") || `<li class="muted">Aucune banque pour l'instant.</li>`}</ul>
        <button data-action="modules" ${busy ? "disabled" : ""}>Ajouter une banque</button>
        ${busy ? `<p class="muted">Synchronisation en cours…</p>` : ""}`;
    case "modules":
      return `${header("Ajouter une banque", true)}
        <form data-form="search"><input name="search" placeholder="Rechercher (boursorama, ing…)" value="${escape(screen.search)}" autofocus /></form>
        <ul class="list">${screen.modules
          .map((m) => `<li><button class="link" data-action="pick" data-module="${escape(m.name)}"><b>${escape(m.description)}</b><span class="muted">${escape(m.name)}</span></button></li>`)
          .join("") || `<li class="muted">${busy ? "Chargement…" : "Aucune banque trouvée."}</li>`}</ul>`;
    case "form":
      return `${header(screen.description, true)}
        <form data-form="bank" class="stack">
          ${screen.fields
            .map((f) =>
              f.choices
                ? `<label>${escape(f.label)}<select name="${escape(f.id)}">${Object.entries(f.choices)
                    .map(([k, v]) => `<option value="${escape(k)}" ${k === f.default ? "selected" : ""}>${escape(v)}</option>`)
                    .join("")}</select></label>`
                : `<label>${escape(f.label)}<input name="${escape(f.id)}" type="${f.masked ? "password" : "text"}" value="${f.masked ? "" : escape(f.default ?? "")}" ${f.required ? "required" : ""} autocomplete="off" /></label>`,
            )
            .join("")}
          ${screen.error ? `<p class="alert">${escape(screen.error)}</p>` : ""}
          <p class="muted">Rangé dans le trousseau de cet ordinateur, jamais envoyé à Finz.</p>
          <button ${busy ? "disabled" : ""}>${screen.bankId ? "Enregistrer et synchroniser" : "Tester et enregistrer"}</button>
        </form>`;
    case "question":
      return `${header("Question de la banque")}
        ${
          screen.field
            ? `<form data-form="answer" class="stack"><label>${escape(screen.field.label)}<input name="value" type="${screen.field.masked ? "password" : "text"}" autocomplete="one-time-code" autofocus required /></label><button>Valider</button></form>`
            : `<p>${escape(screen.message)}</p><p class="muted">En attente de votre validation dans l'application de votre banque…</p>`
        }`;
    case "settings":
      return `${header("Réglages", true)}
        <form data-form="settings" class="stack">
          <label>Fréquence de synchro<select name="interval_hours">${[6, 12, 24]
            .map((h) => `<option value="${h}" ${status?.interval_hours === h ? "selected" : ""}>Toutes les ${h} heures</option>`)
            .join("")}</select></label>
          <label class="check"><input type="checkbox" name="autostart" id="autostart" /> Démarrer avec l'ordinateur</label>
          <button class="secondary">Enregistrer</button>
        </form>
        <p class="muted">Version ${escape(status?.version)}</p>
        ${screen.confirmUnlink
          ? `<p class="alert">Ce connecteur oubliera Finz et vos banques sur cet ordinateur.</p><button class="danger" data-action="unlink-confirmed">Confirmer : délier</button>`
          : `<button class="danger" data-action="unlink">Délier de Finz</button>`}`;
  }
}

// --- Actions ------------------------------------------------------------------------------

app.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target as HTMLFormElement;
  const data = Object.fromEntries(new FormData(form).entries()) as Record<string, string>;

  switch (form.dataset.form) {
    case "link":
      await run(async () => {
        status = await call<Status>("link", { finz_url: data.finz_url, code: data.code }).result;
        show({ name: "banks", message: "Relié. Ajoutez votre première banque." });
      });
      break;
    case "search":
      await pickModules(data.search ?? "");
      break;
    case "bank": {
      if (screen.name !== "form") return;
      const current = screen;
      await run(async () => {
        const method = current.bankId ? "set_credentials" : "add_bank";
        const params = current.bankId
          ? { bank_id: current.bankId, values: data }
          : { module: current.module, values: data };
        const result = await call<{ outcome: string }>(method, params).result;
        await refresh(`${current.description} : ${outcomeText(result.outcome)}`);
      });
      break;
    }
    case "answer":
      if (screen.name === "question") {
        const request = screen.request;
        call("answer", { request, value: data.value });
        show({ name: "question", request, message: "Réponse envoyée à la banque…" });
      }
      break;
    case "settings":
      await run(async () => {
        status = await call<Status>("settings", { interval_hours: Number(data.interval_hours) }).result;
        if ((form.querySelector("#autostart") as HTMLInputElement).checked) await enable();
        else await disable();
        show({ name: "banks", message: "Réglages enregistrés." });
      });
      break;
  }
});

app.addEventListener("click", async (event) => {
  const target = (event.target as HTMLElement).closest<HTMLElement>("[data-action]");
  if (!target) return;
  const { action, id, module } = target.dataset;

  switch (action) {
    case "back":
      show({ name: "banks" });
      break;
    case "settings":
      show({ name: "settings" });
      setTimeout(async () => {
        const box = document.getElementById("autostart") as HTMLInputElement | null;
        if (box) box.checked = await isEnabled();
      });
      break;
    case "modules":
      await pickModules("");
      break;
    case "pick":
    case "credentials":
      await run(async () => {
        const described = await call<{ name: string; description: string; fields: Field[] }>("describe", { module }).result;
        show({ name: "form", module: described.name, description: described.description, fields: described.fields, bankId: action === "credentials" ? id : undefined });
      });
      break;
    case "sync":
      await syncAll(id);
      break;
    case "unlink":
      show({ name: "settings", confirmUnlink: true });
      break;
    case "unlink-confirmed":
      await run(async () => {
        status = await call<Status>("unlink").result;
        show({ name: "link" });
      });
      break;
  }
});

async function pickModules(search: string): Promise<void> {
  show({ name: "modules", modules: [], search });
  await run(async () => {
    const modules = await call<{ name: string; description: string }[]>("modules", { search }).result;
    show({ name: "modules", modules, search });
  });
}

async function syncAll(bankId?: string): Promise<void> {
  await run(async () => {
    const result = await call<Record<string, string>>("sync", bankId ? { bank_id: bankId } : {}).result;
    const outcomes = Object.values(result);
    await refresh(outcomes.every((o) => o === "ok") ? "Synchronisé." : outcomes.map(outcomeText).join(" "));
  });
}

// --- Mises à jour et démarrage ------------------------------------------------------------

async function checkUpdate(): Promise<void> {
  try {
    const update = await check();
    if (update && !busy) {
      await update.downloadAndInstall();
      await relaunch();
    }
  } catch {
    // Hors ligne ou dépôt injoignable : nouvel essai plus tard.
  }
}

async function firstLaunch(): Promise<void> {
  try {
    if (!localStorage.getItem("autostart-initialized")) {
      await enable();
      localStorage.setItem("autostart-initialized", "1");
    }
  } catch {
    // Préférence locale indisponible : pas bloquant.
  }
}

render();
void listen("tray-sync", () => syncAll());
start()
  .then(firstLaunch)
  .then(checkUpdate)
  .catch((error) => show({ name: "fatal", message: `Impossible de démarrer le connecteur (${String(error)}).` }));
setInterval(checkUpdate, 24 * 3600 * 1000);
