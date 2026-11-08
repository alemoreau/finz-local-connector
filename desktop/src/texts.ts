// Textes de l'interface (vouvoiement, comme Finz).

export const OUTCOMES: Record<string, string> = {
  ok: "À jour",
  credentials: "Identifiants refusés : corrigez-les.",
  blocked: "Accès bloqué par la banque.",
  sca: "La banque demande une validation : synchronisez depuis cette fenêtre.",
  captcha: "Connectez-vous une fois sur le site de la banque, puis réessayez.",
  action_needed: "La banque demande une action sur son site.",
  unavailable: "Banque momentanément indisponible, nouvel essai plus tard.",
  connector: "Lecture impossible : une mise à jour du connecteur est nécessaire.",
};

export function outcomeText(outcome: string): string {
  return OUTCOMES[outcome] ?? OUTCOMES.connector;
}

export function bankState(bank: { paused: boolean; next_sync_at: number }, now = Date.now()): string {
  if (bank.paused) return "Action requise";
  if (!bank.next_sync_at) return "Synchro à la prochaine occasion";
  const at = new Date(bank.next_sync_at * 1000);
  if (at.getTime() <= now) return "Synchro imminente";
  const time = at.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
  const sameDay = at.toDateString() === new Date(now).toDateString();
  return sameDay ? `Prochaine synchro à ${time}` : `Prochaine synchro le ${at.toLocaleDateString("fr-FR")} à ${time}`;
}

/** Échappement HTML de tout texte venu du connecteur ou de la banque. */
export function escape(value: unknown): string {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
