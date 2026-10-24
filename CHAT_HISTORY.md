# Conversazioni personali — Task 12.2

File introdotti:

- `edicola/chat_data.py`, `chat_store.py`, `chat_sessions.py`,
  `chat_navigation.py`, `chat_sources.py`, `conversation_context.py`.
- `migrations/004_chat_history.sql`, questo documento.
- `tests/test_chat_history.py`, `tests/chat_fake.py`.

File aggiornati per questo task:

- `edicola/reading_ui.py`, `rag.py`, `pdf_viewer.py`, `personal_store.py`,
  `account_ui.py`, `consent.py`.
- `tests/test_chat_ui.py`, `test_app.py`, `test_personal_accounts.py`,
  `test_consent.py`, `test_experience_ui.py`, `test_pdf_viewer.py`.
- `README.md`, `AGENTS.md`, `ACCOUNTS.md`, `DEPLOYMENT.md`, `UX_TASK12.md`.

Verifica finale: **576 test superati**, 89 avvisi di deprecazione delle librerie,
con `python -m pytest -q -p no:cacheprovider`; nessuna chiamata Gemini o connessione
reale a Supabase. Sono inclusi CRUD, ownership, nuove sessioni, contesto limitato,
consensi distinti, rollback, retry del solo salvataggio, fonti/PDF e regressioni.

## Configurazione e migrazione manuale

Non cambiano Secrets, provider Google o modello Gemini. Restano quelli descritti
in [ACCOUNTS.md](ACCOUNTS.md): OIDC nativo Streamlit e connessione server-side
PostgreSQL con `edicola_app`, senza privilegi amministrativi o bypass RLS.
Non usare chiavi Supabase service-role nel browser.

1. Fare un backup PostgreSQL prima della modifica dello schema.
2. Verificare che le migrazioni 001, 002 e 003 siano già applicate nello schema
   `edicola_private`, dal proprietario dello schema. Non modificarle.
3. Controllare ed eseguire manualmente nel SQL Editor Supabase
   [004_chat_history.sql](migrations/004_chat_history.sql), come proprietario dello
   schema, non come `edicola_app`. L'app non applica migrazioni.
4. Verificare la presenza della versione 4 in `schema_migrations` e delle tabelle
   `chat_settings`, `conversations`, `chat_messages`. Tutte hanno RLS attiva e
   forzata, policy di ownership e soli privilegi CRUD al ruolo applicativo.
5. Riavviare Streamlit. Nessun embedding viene rigenerato e nessuna API chiamata.

Senza queste tabelle la chat autenticata e l'export dei dati non confermano
operazioni riuscite e mostrano un errore. Non c'è fallback a chat ospite per un
account con database non disponibile. L'Archivio resta consultabile.

## Salvataggio e privacy

Nella sidebar **Chat AI → Cronologia e privacy**, **Salva le nuove chat nel mio
account** è inizialmente disattivato. È una scelta distinta dall'autorizzazione
Gemini. Attivarla non invia richieste AI e non importa conversazioni temporanee.
Le nuove chat vengono salvate in PostgreSQL; i titoli iniziali sono ricavati
localmente dalla prima domanda e possono essere rinominati.

Ogni scambio domanda/risposta viene scritto atomicamente dopo il completamento,
con ID della richiesta per non duplicarlo se si ripete il solo salvataggio.
Anche errori, rifiuti e annullamenti al cambio chat sono associati alla domanda.
Richieste ancora in corso o interrotte dalla chiusura del processo non sono garantite
nel database. Se una scrittura fallisce, lo scambio resta nella sessione e viene
segnalato: **Riprova salvataggio** ripete soltanto la scrittura, mai Gemini.

Disattivare il salvataggio conserva le vecchie chat. Una prosecuzione di una chat
salvata diventa una copia temporanea; non modifica quella precedente. Riattivare
non importa questa copia: usare **Nuova chat** per un nuovo salvataggio.
**Elimina chat** e **Cancella tutta la cronologia** richiedono conferma. Cancellare
la cronologia non revoca da solo i consensi Gemini o la scelta di nuovi salvataggi.

In **Il mio profilo → Preferenze**, l'export JSON include `chat_history` con
conversazioni, messaggi, metadati e passaggi delle fonti; **Cancella tutti i miei
dati** elimina anche chat e scelta di salvataggio, per cascata. Backup del provider
possono avere tempi di conservazione separati. Non si memorizzano token, password
o PDF completi. Non sono introdotte cache globali di chat.

Limiti del prototipo: 200 chat salvate, 100 scambi per chat, circa 10 MB di contenuto
dei messaggi per account (oltre a indici/overhead PostgreSQL); 20 chat temporanee
per sessione. Una sola chat salvata viene normalmente mantenuta caricata in RAM;
le scritture fallite sono preservate fino alla chiusura della sessione. Ospiti e
modalità demo locale usano solo RAM: logout/cambio identità svuota lo stato privato.

## Contesto e fonti

Ogni invio può includere gli ultimi sei messaggi della sola chat attiva: massimo
800 caratteri per messaggio, complessivamente 4000 byte UTF-8. È un limite
conservativo di input, non un conteggio preciso di token. L'output mantiene il
limite RAG già configurato. Nessuna chiamata aggiuntiva riscrive la domanda:
un contesto locale aiuta l'embedding a comprendere soggetto e argomento.

Le vecchie risposte sono indizi tematici, **mai prove**: retrieval fresco e
validatore delle citazioni rimangono obbligatori per ogni risposta. Le date del
nuovo retrieval continuano a determinare gli avvisi di copertura temporale.
Il consenso testuale passa a `text-v2`: anche chi aveva autorizzato `text-v1` deve
esprimere la nuova scelta. Audio e briefing personali non cambiano finalità.

I piccoli riferimenti sotto la risposta sono pulsanti nativi, uno per PDF/pagina;
gli ID di più citazioni della stessa pagina vengono raggruppati. Testata e data
provengono soltanto dai metadati curati; in assenza di testata, l'etichetta è
neutra e non espone il nome tecnico del PDF. La data nota è nel suggerimento.
**Mostra passaggi originali** apre un popover secondario. Tutte le fonti recuperate
restano consultabili e si distinguono dalle fonti effettivamente citate.

Il click apre **Archivio** sulla pagina verificata. Il controllo riutilizza nome
del PDF acquisito, pagina, chunk corrente e SHA-256 salvato: fonti rimosse,
sostituite, obsolete o percorsi esterni vengono rifiutati. I riferimenti non
garantiscono la disponibilità futura del corpus: la demo cloud deve continuare a
distribuire lo snapshot autorizzato. Nessuna risposta viene rigenerata se manca
un PDF. Rendering Markdown escapato, HTML disabilitato, nessun link del modello
reso attivo. Altre sezioni e relativi consensi restano invariati.

## Verifica locale e cloud

```powershell
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.venv\Scripts\python.exe -m streamlit run app.py
```

1. Come ospite, aprire **Chat AI**, inviare una domanda e verificare il consenso
   `text-v2`. Provare un seguito («E gli edifici pubblici?»), poi **Nuova chat**:
   la seconda conversazione deve iniziare vuota e senza contesto della prima.
2. Aprire una vecchia chat dalla sidebar, rinominarla ed eliminarla con conferma.
   Nessuna di queste azioni deve generare attività Gemini. Su smartphone aprire e
   richiudere la sidebar nativa; verificare composer unico e wrapping delle fonti.
3. Accedere con account A, attivare il salvataggio, creare una **Nuova chat** e
   inviare una domanda. Controllare fonti compatte, PDF alla pagina corretta e
   passaggi nel popover. Il modello è chiamato soltanto dopo consenso e invio.
4. Fare logout/login A; ripetere da un secondo browser/dispositivo. Aprire la chat
   già salvata: messaggi e fonti devono riapparire senza nuove richieste Gemini.
5. Accedere con account B: elenco, preferenze, export e chat A non devono apparire.
   Tornare ad A, disattivare il salvataggio e proseguire: la copia deve essere
   temporanea; un altro dispositivo deve vedere solo la parte salvata precedente.
6. Provare export e cancellazione di una/tutte le chat. Verificare che B non venga
   modificato. Se il database è indisponibile, non deve apparire un falso successo.

I test automatici simulano provider, database e SDK: non dimostrano da soli la
configurazione RLS effettivamente applicata su Supabase, né eseguono login reali.
La prova con due account dopo la migrazione resta obbligatoria prima del pubblico.
Non sono stati eseguiti provisioning, migrazione remota, commit, push o deployment.
Gli audio personali restano temporanei secondo la configurazione precedente.
