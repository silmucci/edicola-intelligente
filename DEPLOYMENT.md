# Deployment dimostrativo su Streamlit Community Cloud

**Task 12.2:** prima di aggiornare l'app applicare manualmente anche
[`004_chat_history.sql`](migrations/004_chat_history.sql), dopo 001/002/003.
Nessun nuovo Secret; cronologia su PostgreSQL soltanto con scelta dell'utente.
[Configurazione e prova con due account](CHAT_HISTORY.md).

**Task 12:** il rilascio del nuovo sistema di autorizzazioni richiede prima la
migrazione additiva [`003_ai_consents.sql`](migrations/003_ai_consents.sql).
Non modificare 001/002 già applicate. Procedura, limiti e checklist visuale in
[UX_TASK12.md](UX_TASK12.md). Nessun nuovo Secret o deployment automatico.

**Aggiornamento Task 11A:** l'archivio usa ancora lo snapshot di questa guida;
gli account personali richiedono anche [ACCOUNTS.md](ACCOUNTS.md). Il vecchio profilo
demo condiviso non viene esposto nel cloud.

L'app è già pubblicata dal gestore; questa guida descrive preparazione e aggiornamenti
manuali. Nessun deployment automatico, caricamento di chiavi, PDF o dati personali
è stato effettuato durante questo intervento.

## Compatibilità verificata e limiti della verifica

- Ambiente di sviluppo: Windows, Python 3.14.4, SQLite 3.50.4.
- Le dipendenze dirette sono fissate alle versioni installate e provate in
  `requirements.txt`. Non ci sono dipendenze applicative esclusivamente Windows
  né percorsi assoluti Windows nel codice applicativo. I percorsi sono costruiti con `Path`.
- Il vincolo `server.address = "127.0.0.1"` è stato rimosso dalla configurazione:
  il servizio cloud può configurare indirizzo e porta.
- Il visualizzatore usa PDFium locale e componenti Streamlit, senza CDN. Non
  richiede Poppler, un browser installato sul server o il comando di sistema `dot`.
  PDFium dispone di pacchetti precompilati per Linux; verificare l'installazione
  della versione fissata nei log del primo build.
- Chroma richiede SQLite >= 3.35. L'app mostra un errore se il runtime è troppo
  vecchio; non installa automaticamente sostituti SQLite o modelli locali.
- La suite è stata eseguita **su Windows**. La matrice GitHub Actions predisposta
  prova Linux con Python 3.12 e 3.14, ma qui non è stata eseguita. Scegliere
  **Python 3.14** nel deployment per allinearsi all'ambiente locale verificato.
  Prima della pubblicazione verificare il job Linux e l'installazione delle wheel.
  Le dipendenze transitive sono risolte da pip: non è un lock completo dell'ambiente.

## Dati distribuibili e dati da escludere

Si possono pubblicare codice, test sintetici, requirements, documentazione,
`.streamlit/config.toml`, `.env.example`, `editions.example.json` e
`deployment/secrets.example.toml`: questi esempi non contengono credenziali.

**Non pubblicare** `.env`, `.streamlit/secrets.toml`, ambienti virtuali, l'intera
cartella `data/`, database locali, indice Chroma nativo, cache editoriali/audio,
profili, valutazioni/esportazioni private, chiavi, backup e log. `.gitignore`
li esclude; non impedisce però il caricamento manuale o l'aggiunta forzata.
Questa cartella non è ancora un repository Git: non esiste una cronologia locale
da verificare. Prima del push controllare anche eventuale cronologia del repository
di destinazione e l'elenco esatto dei file in staging. Il controllo dei sorgenti
candidati non ha rilevato firme di chiavi Google/GitHub o chiavi private; non
costituisce una scansione universale di credenziali e non ha letto `.env`.

I PDF commerciali **non sono dati demo liberamente distribuibili**. Per un'app
pubblica occorre autorizzazione alla consultazione e al download via web, oltre
all'eventuale invio a Gemini. Anche testi estratti, chunk, embeddings e metadati
possono essere soggetti a restrizioni: verificarne i diritti. Un repository privato
non rende privati i documenti offerti da un'app pubblica.

Per la demo preferire quotidiani sintetici propri o documenti con licenza che
consenta espressamente questo utilizzo. Non sono stati creati né selezionati
automaticamente PDF distribuibili. Senza uno snapshot autorizzato il deployment
demo si arresta, senza avviare estrazione, preprocessing o indicizzazione API.

## Preparare lo snapshot autorizzato (azione manuale)

Chiudere l'app locale e gli eventuali comandi di indexing prima dell'esportazione,
così che SQLite e Chroma rappresentino la stessa versione dell'archivio. Verificare
prima diritti e autorizzazione di **ciascun** PDF. Dalla radice del progetto:

```powershell
python -m edicola.cloud --export deployment/seed --pdf "documento-autorizzato.pdf" --authorize-distribution
```

Sostituire il nome di esempio con un PDF già acquisito; ripetere `--pdf "altro.pdf"`
per ciascun altro documento autorizzato. Il flag attesta l'autorizzazione alla
distribuzione anche dei dati derivati. Il comando **non pubblica nulla** e non
chiama Gemini. La destinazione deve essere nuova; non sovrascrive snapshot esistenti.

Lo snapshot contiene soltanto:

- PDF nominati esplicitamente;
- un nuovo `data/archive.sqlite3` con sole estrazioni e chunk di quei PDF,
  senza documenti storici esclusi;
- metadati di edizione delle sole fonti incluse;
- `vectors.json`: soltanto embeddings già presenti e coerenti con quei chunk;
- `manifest.json`: conteggi, configurazione della collezione e SHA-256 dei file.

Non include chiavi, profili o cache. Un archivio parziale resta parziale: nessun
chunk mancante viene indicizzato per completarlo. Lo snapshot può avere zero
embeddings; in tal caso le funzionalità semantiche non avranno fonti disponibili.

Verifica offline, senza API:

```powershell
python -m edicola.cloud
```

Esaminare localmente tutti i file di `deployment/seed/`, inclusi i testi derivati.
Lo snapshot è ignorato da Git per default. **Soltanto dopo l'approvazione dei
contenuti**, aggiungere intenzionalmente lo snapshot al repository destinato alla
demo (`git add -f -- deployment/seed`), verificando prima che sia proprio la
cartella prodotta dal comando e non una copia indiscriminata di `data/`.
Non usare `git add -f data` o forzare l'aggiunta di `.env`.

I file nativi HNSW di Windows non vengono trasferiti. Con `EDICOLA_CLOUD_DEMO="1"`
l'app verifica lo snapshot e ne crea una copia di lavoro sotto
`.cloud-runtime/<hash-manifest>/`. Al primo avvio ricostruisce **solo l'indice ANN
locale dai vettori esportati**, fornendoli esplicitamente a Chroma, con embedding
function disabilitata. Non estrae i PDF di nuovo, non modifica il chunking, non
invoca Gemini e non esegue il comando di indexing. Ai rerun riusa questa copia.
Se il ripristino viene interrotto, gli upsert degli stessi ID permettono di riprenderlo.
Non cambia l'archivio di sviluppo in `data/`.

## Secrets e modelli

Usare il template `deployment/secrets.example.toml` nei **Secrets** del servizio,
non commetterne una copia con valori reali. I valori devono stare al livello
principale TOML, senza intestazione `[gemini]`. Configurare:

```toml
EDICOLA_CLOUD_DEMO = "1"
EDICOLA_ARCHIVE_DIAGNOSTICS = "0"
GEMINI_API_KEY = "LA_PROPRIA_CHIAVE_SOLO_NEI_SECRETS"
GEMINI_RAG_MODEL = "IL_MODELLO_GIA_VERIFICATO_NEL_PROPRIO_ENV"
GEMINI_RAG_TOP_K = "3"
GEMINI_TTS_MODEL = "IL_MODELLO_TTS_GIA_VERIFICATO_NEL_PROPRIO_ENV"
GEMINI_TTS_VOICE = "Kore"
```

Sostituire tutti i segnaposto. I modelli del `.env` **non vengono cambiati**.
Streamlit espone i Secrets principali anche nell'ambiente; la chiave viene letta
in ordine da ambiente, Secrets, `.env` locale. `.env` continua a funzionare per
l'esecuzione sul PC; nel cloud lo snapshot non lo contiene.
Non attivare fatturazione: verificare nel proprio account che i modelli scelti
siano disponibili senza pagamento e nei limiti di quota. Le chiamate restano
legate ai pulsanti e ai consensi esistenti, mai all'avvio. In un'app pubblica
visitatori diversi possono consumare la stessa quota della chiave del gestore.

## Persistenza del corpus e degli account

Community Cloud **non garantisce la persistenza dei file locali**. La soluzione
per questa demo è uno snapshot immutabile versionato, da cui ripartire senza
generare nuovi embeddings. Dopo la perdita del filesystem, il corpus autorizzato
viene ripristinato dal repository; nuovi prodotti generali e audio generati
durante l'esecuzione possono andare persi. Le cache generali evitano duplicati finché la
copia di lavoro esiste, non dopo la sua perdita.

Con il Task 11A profili, preferenze, feedback, riferimenti e briefing personali sono
memorizzati separatamente in PostgreSQL Supabase e protetti tramite identità OIDC e
ownership server-side. Seguire **ACCOUNTS.md** per configurare provider, ruolo limitato,
RLS e Secrets. Se la configurazione manca, l'area personale rimane chiusa: nessun
fallback al profilo demo. I profili del PC non entrano nello snapshot né vengono
importati. Audio personali, cache generali e storico della sessione restano temporanei;
non utilizzare il disco cloud come unica copia dei dati.

## Procedura di pubblicazione (da eseguire personalmente)

1. Preparare lo snapshot autorizzato e verificarlo come sopra. Senza autorizzazione
   usare un corpus proprio/sintetico; non caricare i quotidiani attuali per tentativi.
2. Eseguire `python -m pip install -r requirements-dev.txt`,
   `python -m pip check` e `python -m pytest -q` in un ambiente Python 3.14.
3. Creare personalmente un repository GitHub e inserirvi solo codice, configurazioni
   di esempio, test, documentazione e lo snapshot approvato. Prima del primo commit
   verificare `git status --short`, `git diff --cached --stat` e i file in staging:
   niente `.env`, Secrets reali, `data/`, `.cloud-runtime/` o profili.
4. Attendere il successo del workflow **Test senza API** su Linux. Se fallisce un
   build delle dipendenze, fermarsi: non sostituire automaticamente versioni, SQLite
   o modelli senza una nuova verifica.
5. Accedere a [Streamlit Community Cloud](https://share.streamlit.io/), collegare
   personalmente GitHub e scegliere **Create app → Yup, I have an app**.
6. Indicare repository, branch e **Main file path: `app.py`**; scegliere il sottodominio.
7. In **Advanced settings**, selezionare **Python 3.14** e incollare nei **Secrets**
   i valori reali del template, inclusa `EDICOLA_CLOUD_DEMO="1"`. Salvare.
8. Premere **Deploy**. Il servizio costruisce l'ambiente e fornisce un URL HTTPS
   del tipo `https://nome-demo.streamlit.app/`: il PC non deve restare acceso.
9. Verificare nei log installazione e SQLite, poi visualizzazione/download dei PDF
   e navigazione delle fonti. Il primo avvio non deve contenere richieste Gemini.
   Verificare login, database e isolamento come descritto in ACCOUNTS.md. Solo dopo questi controlli,
   provare volontariamente una domanda con il consenso previsto: questa prova
   reale può consumare quota. Il progetto non l'ha eseguita automaticamente.
10. Per aggiornare il corpus preparare e verificare un **nuovo** snapshot locale,
    quindi sostituire personalmente quello pubblicato. Non avviare indexing dal cloud.
    Un nuovo manifest genera una nuova copia di lavoro; nessun dato locale precedente
    viene cancellato automaticamente.

I PDF attuali (5 file, circa 33,74 MiB complessivi) e i 597 chunk / 360 embeddings
sono stati contati localmente, senza API. Questi numeri non attestano il permesso
di distribuzione. I blocchi residui sono: autorizzazione/corpus demo, snapshot non
ancora creato, repository GitHub non configurato, primo test/build Linux da eseguire
e Secrets da inserire personalmente.

## Riferimenti ufficiali

- [Deployment e scelta di Python](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy).
- [Dipendenze e ambiente cloud](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies).
- [Secrets cloud](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management).
- [Secrets principali come variabili d'ambiente](https://docs.streamlit.io/develop/concepts/connections/secrets-management).
- [Mancata garanzia di persistenza locale](https://docs.streamlit.io/develop/concepts/connections/connecting-to-data).
- [Installazione e pacchetti PDFium](https://pypdfium2.readthedocs.io/en/stable/readme.html).
