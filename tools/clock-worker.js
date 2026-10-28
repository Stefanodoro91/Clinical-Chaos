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
  // L'indirizzo pubblico del Worker non avvia niente: dice solo che l'orologio esiste.
  async fetch() {
    return new Response("Orologio del bot Clinical Research Chaos: attivo.", { status: 200 });
  },
};
