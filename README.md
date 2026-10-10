# Research methods bot

Trasforma il tuo materiale didattico (slide, PDF, documenti, appunti) in caroselli Instagram in inglese sulla ricerca clinica sull'uomo e sulla metodologia, e ne pubblica uno al giorno. Costo: 0 €.

## Come funziona

1. **Metti un file** nella cartella Drive **Materiale**. Formati supportati: PDF, PowerPoint, Word, Google Docs, Google Slides, file .txt/.md. Il materiale può essere anche in italiano.
2. **Il bot lo legge.** Gemini estrae i concetti, uno per post (fino a 12 per file), e li mette in coda in `queue.json`. Il file viene poi spostato in **Elaborati**. Viene letto un file nuovo al giorno, così si resta comodamente nel piano gratuito.
3. **Ogni giorno** il bot prende il prossimo post dalla coda, alternando le fonti, disegna il carosello e lo pubblica. Il carosello ha una copertina, 3-5 slide di contenuto e una slide finale con il messaggio chiave e l'invito a salvare e seguire la pagina. Questa fase non usa Gemini, quindi funziona anche se Gemini è temporaneamente fuori servizio.

**Precisione.** Gemini ha istruzioni rigide: usare solo ciò che è nel tuo materiale, non inventare numeri, studi, linee guida o riferimenti, e niente consigli clinici. Ogni post in coda riporta anche `source_hint`, cioè la parte del materiale da cui viene, così puoi verificarlo rapidamente.

**Revisione (facoltativa ma consigliata).** La coda si riempie giorni prima della pubblicazione. Su GitHub apri `queue.json` e clicca la matita per modificarlo: puoi correggere un testo, cambiare l'ordine o cancellare un post. Il bot pubblica quello che trova nel file.

## ⚠️ Privacy: cosa NON mettere nella cartella

Con il piano gratuito, Google può usare i contenuti inviati a Gemini per migliorare i suoi modelli, e possono leggerli anche revisori umani. Usa solo materiale didattico che potresti pubblicare. **Mai** dati di pazienti o partecipanti, dati di studi non pubblicati, protocolli riservati o materiale coperto da accordi di riservatezza con sponsor.

## Configurazione

Se hai già configurato AminHimalaya, è lo stesso procedimento: puoi riusare il progetto Google Cloud e lo stesso account di servizio. Servono però un **nuovo account Instagram**, una nuova pagina Facebook e un nuovo repository.

1. **Instagram:** crea l'account, passalo ad account professionale (Creator) e collegalo a una pagina Facebook.
2. **Drive:** crea la cartella **Materiale** con la sottocartella **Elaborati**. Annota gli ID (la parte dell'indirizzo dopo `/folders/`) e condividi entrambe con l'email dell'account di servizio come **Editor**.
3. **Google Cloud:** account di servizio con l'API Drive abilitata e chiave JSON (vedi la guida di AminHimalaya, punto 3).
4. **Gemini:** chiave gratuita da aistudio.google.com.
5. **Token Instagram:** stesso procedimento di AminHimalaya, punto 5, ma con la nuova pagina. Ottieni un token di pagina che non scade e l'id dell'account Instagram.
6. **GitHub:** repository **pubblico**, carica tutti i file (comprese le cartelle `.github` e `fonts`) e aggiungi i segreti:

| Segreto | Valore |
|---|---|
| `GDRIVE_SERVICE_ACCOUNT_JSON` | contenuto del file JSON dell'account di servizio |
| `GDRIVE_FOLDER_ID` | ID della cartella Materiale |
| `GDRIVE_DONE_FOLDER_ID` | ID della cartella Elaborati |
| `GEMINI_API_KEY` | chiave Gemini |
| `IG_ACCESS_TOKEN` | token della pagina |
| `IG_USER_ID` | id dell'account Instagram |

7. **Prova:** carica un file in Materiale, poi Actions → "Post giornaliero ricerca clinica" → **Run workflow** con "Solo prova" spuntato. Nell'artifact **preview** trovi le slide, la didascalia e tutta la coda generata dal file: è il momento giusto per verificare la qualità. Quando ti convince, esegui senza la spunta.

## Personalizzazione (`config.json`)

- `brand_name`, `handle`: nome della pagina e @ mostrato sulle slide. **Cambiali con i tuoi.**
- `colors`: palette delle slide (sfondo, colore d'accento, testi).
- `fixed_hashtags`: hashtag presenti in ogni post.
- `max_new_files_per_run`: file letti al giorno (1 di default, aumentalo per caricare velocemente un archivio grande).
- `max_posts_per_file`, `low_queue_warning`: numero massimo di post per file e soglia dell'avviso "coda in esaurimento".
- **Orario:** riga `cron` in `.github/workflows/daily-post.yml`, in UTC. L'impostazione predefinita è alle 12:00 UTC ogni giorno; per pubblicare solo nei giorni feriali usa `0 12 * * 1-5`.
- **Tono e regole dei testi:** `PROMPT` in `content.py`.

## Avvisi via email (issue su GitHub)
Ricevi un'email se un post fallisce, quando la coda sta finendo, quando è vuota e quando da un file non si ricava nessun post.

Font: Inter (licenza SIL Open Font License, inclusa in `fonts/`).
