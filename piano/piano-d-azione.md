# Piano d'azione – Clinical Research Chaos

Aggiornato al 22 ottobre 2026. Prima si rimette in moto la pubblicazione, poi si fa trovare il sito, poi si costruisce la lista email su cui poggia ogni ricavo (vedi `benchmark-monetizzazione.md`).

## Azioni di Stefano, dalla più urgente

- [ ] **Oggi – rigenerare il token di Instagram e Facebook.** Il token è stato revocato (app rimossa dalle integrazioni business): dal 22 ottobre il bot non pubblica.
  1. Graph API Explorer → stessa app → «Generate Access Token» con i permessi di prima più `instagram_manage_comments`.
  2. Access Token Debugger → «Extend Access Token».
  3. In Graph API Explorer, con il token esteso: `me/accounts` → copia l'`access_token` della Pagina.
  4. GitHub → Settings → Secrets: aggiorna `IG_ACCESS_TOKEN` e `FB_PAGE_TOKEN` con quel valore. Non incollarlo in chat.
- [ ] **Questa settimana – Google Search Console (5 minuti).**
  1. search.google.com/search-console con il tuo account Google.
  2. «Prefisso URL» → `https://clinical-chaos-dsv.pages.dev`.
  3. Verifica con «Tag HTML»: incolla in chat la riga `<meta name="google-site-verification" content="...">` (non è una password).
  4. Dopo l'inserimento: «Verifica», poi invia `sitemap.xml` dal menu «Sitemap». Dopo qualche giorno controlla «Annunci di lavoro».
- [ ] **Questa settimana – canale WhatsApp.** WhatsApp → Aggiornamenti → + → Nuovo canale, con nome e logo del progetto; manda a Claude il link del canale.
- [ ] **Questa settimana – email di GitHub.** Settings → Emails: la Gmail (indirizzo con +github) come Primary, eliminare la mail del lavoro; Notifications → Custom routing vuoto.
- [ ] **Entro una settimana – nuovo materiale di metodologia su Drive.** La coda ha circa 10 post.
- [ ] **Prima della newsletter – scegliere il servizio email** (piano gratuito di Buttondown o MailerLite) e aprire l'account con una mail del progetto, non personale.
- [ ] **Prima del primo incasso – sentire un commercialista** su posizione fiscale e vendita di prodotti digitali nell'UE.
- [ ] **Facoltativo – cancellare su Instagram** il post «1 open positions» e l'annuncio verde acqua.

## Azioni di Claude

1. Ripubblicare il bando saltato il 22 ottobre appena il token funziona.
2. Inserire il tag di Search Console e controllare che Google accetti le pagine delle posizioni.
3. Pulsante WhatsApp sul sito e messaggio settimanale pronto da incollare nel canale.
4. Fonte alternativa a EURAXESS (blocca la lettura automatica) per le posizioni europee e italiane: feed ufficiale o albi dei concorsi delle università / portale MUR.
5. Newsletter: modulo di iscrizione sul sito e digest settimanale automatico, appena è scelto il servizio.
6. Toolkit di metodologia: prima bozza dal materiale Drive, quando si decide di partire.

## Fatto di recente

- 22/10: filtri liberi nella pagina bandi; pulsante Share; una pagina per posizione con dati per Google Jobs; sitemap e robots; anteprime social; logo orizzontale e cascata ai due lati.
- 22/10: avvisi più chiari quando Instagram rifiuta un post (annotazione ed email).
