// Orologio esterno del bot (Cloudflare Worker con Cron Trigger "*/10 * * * *").
// I cron di GitHub Actions ritardano di ore o saltano; quelli di Cloudflare partono puntuali. Ogni 10 minuti
// questo Worker sveglia il guardiano (watchdog.yml), che controlla il calendario e lancia ciò che manca.
// Il Worker non pubblica niente e non decide niente: avvia solo il guardiano.
//
// Secret richiesto nel Worker: GH_TOKEN = token GitHub «fine-grained» limitato al repository Clinical-Chaos,
// permesso Actions: Read and write (nient'altro). Il token non va mai nel codice, nel repository o in chat.

const URL = "https://api.github.com/repos/Stefanodoro91/Clinical-Chaos/actions/workflows/watchdog.yml/dispatches";

async function wake(env) {
  const r = await fetch(URL, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${env.GH_TOKEN}`,
      "Accept": "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "clinical-chaos-clock",
    },
    body: JSON.stringify({ ref: "main" }),
  });
  return `${r.status} ${r.status === 204 ? "guardiano avviato" : await r.text()}`;
}

export default {
  async scheduled(event, env, ctx) {
    const hour = new Date().getUTCHours();
    if (hour < 6 || hour > 21) return;        // di notte non c'è niente da recuperare
    ctx.waitUntil(wake(env).then((s) => console.log(s)));
  },
  // L'indirizzo pubblico del Worker non avvia niente. Con /check verifica il token in sola lettura
  // (legge le informazioni del workflow del guardiano) e dice se GitHub lo accetta; il token non viene mostrato.
  async fetch(request, env) {
    if (new URL(request.url).pathname !== "/check") {
      return new Response("Orologio del bot Clinical Research Chaos: attivo.", { status: 200 });
    }
    if (!env.GH_TOKEN) return new Response("GH_TOKEN mancante o vuoto nel Worker.", { status: 200 });
    const r = await fetch(URL.replace("/dispatches", ""), {
      headers: {
        "Authorization": `Bearer ${env.GH_TOKEN}`,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "clinical-chaos-clock",
      },
    });
    const msg = r.status === 200 ? "Token OK: GitHub lo accetta."
      : r.status === 401 ? "Token rifiutato (401): sbagliato, scaduto o incollato con spazi."
      : r.status === 404 ? "Token senza accesso al repository Clinical-Chaos (404)."
      : `Risposta inattesa di GitHub: ${r.status}`;
    return new Response(`${msg}\nInizio token: ${env.GH_TOKEN.slice(0, 11)}… (lunghezza ${env.GH_TOKEN.length})`,
      { status: 200, headers: { "content-type": "text/plain; charset=utf-8" } });
  },
};
