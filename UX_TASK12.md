# Task 12 — Esperienza editoriale e autorizzazioni AI

**Aggiornamento Task 12.2:** la chat ora usa conversazioni multiple, contesto
limitato, fonti compatte e cronologia PostgreSQL opt-in. Applicare anche la
migrazione 004: [guida aggiornata](CHAT_HISTORY.md). Le descrizioni del precedente
storico RAM qui sotto documentano il Task 12 e sono sostituite dal Task 12.2.

## Analisi e design

Prima: checkbox ripetute, azioni alternative tutte visibili e preferenze mescolate
alla creazione dei contenuti. Ora: sette sezioni con scelte contestuali, tema
editoriale avorio/verde, titoli serif e testo sans-serif di sistema. Nessun font
remoto, CDN, selettore CSS del DOM Streamlit o nuova dipendenza.

- Home: edizioni reali, estratti dichiarati come tali, consigli locali e accessi rapidi.
- Archivio: copertine approvate e lettore originale conservati; aggiunto Vai a pagina.
- Chat: messaggi, fonti espandibili e larghezza di lettura contenuta; otto domande
  indipendenti in RAM, eliminate al cambio identità, senza memoria conversazionale.
- Approfondimenti e visualizzazioni: selettore compatto e una sola azione principale.
- Podcast: distinzione tra audio da creare e già disponibili, ascoltabili senza nuovi
  invii; voce nelle opzioni, testo/fonti espandibili, nessuna rigenerazione del già pronto.
- Profilo: Per te, Raccolta, I miei briefing, Preferenze, Privacy. Al primo accesso
  si apre Preferenze; generazione personale disabilitata finché mancano interessi.
- Layout nativi con wrapping, larghezza delle card contenuta e tema con contrasto
  testo/sfondo e testo/pulsante verificato almeno 4,5:1.

## Scelte AI

Il primo invio apre un dialogo non preselezionato con dati, destinatario e finalità.
«Autorizza e continua» salva la scelta e riprende una sola volta quella richiesta;
«Non ora» o la chiusura non generano contenuti. La sola revisione nel profilo non
avvia una generazione. Ogni operazione richiede comunque il pulsante di invio.

| Finalità | Dati inviati a Google Gemini | Funzioni |
| --- | --- | --- |
| `text-v2` | Domanda/tema, passaggi, PDF/pagina; domanda per embedding; breve contesto della stessa chat | Chat, dossier, briefing generale, timeline, mappe |
| `personal-text-v1` | Passaggi scelti localmente e tempo/budget di lettura | Briefing personale |
| `audio-v1` | Copione visualizzato e voce | Podcast generali e personali |

Non inviamo identità Google, identificativo proprietario, raccolta dei salvati o
storico del profilo. I passaggi personali possono rivelare indirettamente gli
interessi: il dialogo lo dichiara. I prodotti generali sono condivisi, quelli
dell'area personale sono riservati. Evitare dati riservati nelle domande e
predisporre l'informativa del gestore: questo controllo operativo non certifica
da solo adempimenti legali.

Account: scelte persistenti in PostgreSQL per proprietario/finalità, senza fallback
ospite se il database manca. Ospiti: solo Session State; nessuna importazione al
login. Login/logout e cambio identità eliminano scelte ospiti, azioni pendenti e chat.

Revoca e revisione: **Personalizzazione → Privacy → Privacy e autorizzazioni**.
Gli ospiti trovano lo stesso pannello senza login. La revoca blocca le richieste
successive, anche da un altro dispositivo; non annulla quelle già in viaggio e
non ritira dati già ricevuti. I risultati e gli audio disponibili restano consultabili.
Quando il trattamento cambia materialmente, aggiornare descrizione e versione
della sola finalità in `edicola/consent.py`: la vecchia scelta non abilita la nuova.

`consent.perform` lega l'azione all'identità corrente. `api_guard` rilegge la
scelta prima di ogni richiesta SDK, anche tra embedding e generazione e prima
dei retry. Un consenso testo non abilita il TTS. In Streamlit una chiamata senza
contesto è bloccata anche con `authorize_external=True`; i comandi CLI conservano
i propri opt-in. Non cambiano modelli, retrieval o validazione delle citazioni.

## Migrazione e rilascio manuale

1. Non modificare o rieseguire le migrazioni già applicate 001/002.
2. Prima di rilasciare il codice, eseguire integralmente
   [`migrations/003_ai_consents.sql`](migrations/003_ai_consents.sql) nel SQL Editor
   Supabase come proprietario dello schema. È transazionale e additiva, senza
   password o ALTER ROLE: nuova tabella `edicola_private.ai_consents`, grant CRUD
   a `edicola_app`, RLS forzata e policy USING/WITH CHECK sul contesto esistente.
3. Verificare ruolo, grant e policy `own_ai_consent`: nessun accesso per
   PUBLIC/anon/authenticated, proprietario diverso da `edicola_app`, RLS e FORCE
   RLS vere. Rispetto all'audit 001/002 ci sono ora cinque tabelle (versioni incluse)
   e quattro policy personali. La versione 3 deve risultare registrata.
4. Non servono nuovi Secrets. Provare localmente con la configurazione esistente,
   quindi rilasciare soltanto con un'azione manuale del gestore.

La 003 può precedere il rilascio senza cambiare il comportamento della vecchia app.
Se manca, autorizzazioni degli account ed export che le comprende falliscono
esplicitamente, senza falsi salvataggi; i consensi non vengono simulati.
Export e cancellazione includono le scelte: la FK elimina soltanto quelle del
proprietario insieme al profilo. Nessuna migrazione è eseguita dall'app.
Nessun commit, push, deployment o invio Gemini è stato effettuato per il task.

## Verifica desktop e smartphone

Avviare `python -m streamlit run app.py`. Per il solo layout non autorizzare
invii; i test automatici usano provider/database simulati e non consumano quote.

- Desktop 1280–1440 px: Home, copertine, card, risposte; aprire PDF e citazioni,
  usare Vai a pagina, frecce, zoom, ritorno e download del documento originale.
- Smartphone reale o emulazione 360/390 px: scorrere le sette sezioni, verificare
  wrapping, leggibilità, tastiera sul campo pagina e pulsanti del dialogo interamente
  accessibili. Controllare timeline e mappe sullo schermo piccolo.
- Tastiera: Tab/Shift+Tab, focus, Invio; Escape deve chiudere il dialogo senza
  autorizzare. Controllare anche lo zoom browser 200%.
- Primo invio: niente dialoghi all'avvio; rifiuto senza generazione, poi invio
  consapevole autorizzato. Nessuna richiesta ripetuta per la scelta accettata della
  stessa finalità/versione. Audio e testi restano distinti.
- Due account/browser: interessi, salvati e consensi differenti; logout/login,
  riavvio e accesso da altro dispositivo. A non deve vedere briefing o scelte di B.
  Revocare da un dispositivo e controllare il prossimo invio sull'altro.
- Privacy: export con `ai_consents`, cancellazione del solo account corrente,
  nessuna importazione demo. Audio pronto riproducibile senza nuovi invii.

I test responsive verificano proprietà native, wrapping e geometria del lettore,
non un rendering pixel per pixel su dispositivi reali. Questa sessione non esponeva
un browser automatizzabile: checklist visiva e prova online con due account restano
manuali prima del rilascio, inclusa la persistenza reale su Supabase.

## Persistenza

Supabase: preferenze, riferimenti salvati, briefing personali e autorizzazioni.
Solo RAM: chat, bozze, richieste pendenti e scelte ospiti. Audio personali temporanei;
cache generale soggetta agli stessi limiti del filesystem cloud già documentati.
Nessuna nuova promessa di storage audio permanente.

## File e verifiche del task

Creati:

- `edicola/api_guard.py`, `edicola/consent.py`, `edicola/consent_ui.py`, `edicola/design.py`.
- `migrations/003_ai_consents.sql`, `pytest.ini`, `UX_TASK12.md`.
- `tests/test_consent.py`, `tests/test_ux_system.py`.

Modificati:

- `app.py`, `.streamlit/config.toml`.
- `edicola/account_ui.py`, `edicola/archive_components.py`, `edicola/archive_ui.py`,
  `edicola/experience_ui.py`, `edicola/personalization_ui.py`, `edicola/podcast_ui.py`,
  `edicola/reading_ui.py`.
- `edicola/identity.py`: pulizia dello stato dei consensi al cambio identità;
  configurazione e verifica OIDC invariate.
- `edicola/personal_store.py`: CRUD dei consensi, export comprensivo delle scelte;
  ownership e connessioni transazionali esistenti riutilizzate.
- `edicola/embeddings.py`, `edicola/rag.py`, `edicola/briefing.py`,
  `edicola/knowledge.py`, `edicola/podcast.py`: soltanto il controllo immediatamente
  precedente alla richiesta SDK; nessuna modifica ai modelli o ai risultati.
- `tests/test_app.py`, `tests/test_archive_design.py`, `tests/test_cloud.py`,
  `tests/test_experience_ui.py`, `tests/test_pdf_viewer.py`,
  `tests/test_personal_accounts.py`, `tests/test_personalization.py`,
  `tests/test_podcast_ui.py`: aggiornamento dei flussi alla nuova autorizzazione e
  database simulato esteso ai consensi.
- `README.md`, `ACCOUNTS.md`, `AGENTS.md`, `DEPLOYMENT.md`.

Verifica finale: `python -m pytest -q -p no:cacheprovider --tb=short`:
**514 test superati**, inclusi 16 specifici sui consensi e quattro sul nuovo layout,
onboarding e salto pagina. `python -m pip check`: nessuna dipendenza incompatibile.
Restano avvisi di deprecazione delle librerie esistenti, senza test falliti.
La raccolta pytest è limitata a `tests/`: non deve attraversare corpus, seed o
directory private; in questa sessione la cache pytest locale aveva problemi di
accesso, perciò è stato disabilitato soltanto quel plugin di cache nel comando.

Le migrazioni applicate 001/002, i Secrets, le dipendenze e il corpus non sono
stati modificati. Nessuna prova di persistenza remota è simulata come riuscita.

Riferimenti per i controlli nativi: [dialoghi Streamlit](https://docs.streamlit.io/develop/api-reference/execution-flow/st.dialog)
e [tema e colori](https://docs.streamlit.io/develop/concepts/configuration/theming-customize-colors-and-borders).
