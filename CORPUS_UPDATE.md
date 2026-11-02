# Aggiornamento incrementale del corpus

Per il flusso guidato locale con doppio clic, batch persistenti, ripresa e
preparazione dello snapshot usare [GESTIONE_ARCHIVIO.md](GESTIONE_ARCHIVIO.md).
I comandi sotto rimangono strumenti tecnici; non avviarli in parallelo alla gestione.

Procedura locale senza chiamate automatiche a Gemini, senza modificare login,
Supabase, Secrets, consensi o validatori RAG. Nessuna pubblicazione implicita.

## Stato verificato il 30 ottobre 2026

| Misura | Prima | Dopo l’acquisizione locale |
|---|---:|---:|
| PDF presenti | 5 | 12 |
| Contenuti SHA-256 distinti | 5 | 12 |
| Pagine dei PDF presenti | — | 449 |
| Chunk attivi | 597 | 1.407 |
| Chunk con embedding corrente | 360 | 360 |
| Chunk ancora da indicizzare | 237 | 1.047 |

Sono stati acquisiti sette PDF nuovi, con 810 chunk nuovi. Nessun PDF precedente
risulta modificato o rimosso. Tutti i dodici documenti hanno stato di estrazione
`ok`. Il confronto con la copia preventiva del registro conferma che i 597 chunk
precedenti e le cinque associazioni nome/SHA sono invariati. Il controllo
`PRAGMA integrity_check` del registro restituisce `ok`.

I 360 vettori esistenti sono ancora coerenti con i chunk attivi. Nessun vettore
è stato inserito, aggiornato o cancellato durante l’aggiornamento. Il dry-run
conferma modello `gemini-embedding-2`, dimensione 768, zero aggiornamenti dei
metadati Chroma e zero vettori obsoleti.

La distribuzione dei chunk mancanti è riportata nel report privato, per PDF:
810 appartengono ai nuovi quotidiani e 237 alle edizioni precedenti. Tre PDF
precedenti sono interamente indicizzati, uno è parziale e uno non ha ancora
embedding. Nessuno dei sette nuovi PDF ha ancora embedding.

## Metadati editoriali

Mancava `data/editions.json`. È stato creato localmente per tutte le dodici
edizioni, verificando la testata sulle copertine renderizzate con PDFium e le
date nelle diciture originali **Edizione del …** di pagina 1. Le prove e gli SHA
sono conservati in `data/corpus_updates/editorial-metadata-evidence.json`.
Non è stata assegnata una classificazione nazionale/internazionale.

I metadati restano esclusi da Git come gli altri dati del corpus. Per edizioni
future verificare manualmente la testata, la data nel documento e l’eventuale
licenza: nome del file, ordine dei PDF e date degli eventi non sono prove della
data di pubblicazione. Il nuovo audit segnala metadati mancanti, date non valide,
contrasti con l’intestazione e voci senza un PDF presente. Non inventa valori e
non promuove automaticamente una data trovata nel testo a metadato curato.

## Comandi di manutenzione senza API

Dalla radice del progetto, usando l’ambiente virtuale già installato:

```powershell
.\.venv\Scripts\python.exe -m edicola.corpus_update --report data/corpus_updates/latest.json
```

Il comando legge hash, registro, stato Chroma, metadati e cache; non acquisisce,
non modifica l’indice e non richiede una chiave Gemini. Il report contiene nomi
dei PDF e conteggi, non il testo completo. Rimane nell’area privata ignorata da Git.

Per acquisire ulteriori PDF aggiunti in `data/incoming`:

```powershell
.\.venv\Scripts\python.exe -m edicola.corpus_update --refresh --report data/corpus_updates/latest.json
```

`--refresh` crea prima una copia SQLite consistente in `data/corpus_updates`,
poi usa le funzioni esistenti di acquisizione e chunking: riuso per SHA-256 e
configurazione, compresi duplicati ed esiti negativi. Non cambia l’algoritmo di
pulizia, la versione della pipeline o gli ID. Le estrazioni storiche restano nel
registro. Un file modificato con lo stesso nome ha un nuovo SHA e nuovi chunk;
per mantenere consultabile anche la vecchia edizione, conservarla in incoming
con un nome distinto prima di sostituire il file.

Controllo del piano di indicizzazione, sempre senza API:

```powershell
.\.venv\Scripts\python.exe -m edicola.indexing --dry-run --limit 50 --keep-stale
```

`already_indexed` conta anche i chunk che richiedono soltanto aggiornamenti
locali dei metadati, senza nuovi embedding. Il flag `--keep-stale` conserva
eventuali vettori storici non più attivi: la ricerca continua a escluderli usando
ID e fingerprint correnti. Senza il flag resta il comportamento precedente di
riconciliazione dell’indice; per aggiornamenti conservativi usare il flag.

## Indicizzazione: solo dopo autorizzazione esplicita

Il seguente comando **non è stato eseguito**. Invia testi a Gemini e richiede
che il gestore autorizzi consapevolmente l’operazione e il relativo consumo:

```powershell
.\.venv\Scripts\python.exe -m edicola.indexing --limit 50 --authorize-external --keep-stale
```

Processa al massimo 50 chunk ancora mancanti/modificati. Gli embedding salvati
con successo sono persistenti: il comando successivo li salta. Il limite è sui
chunk, non sul numero di tentativi HTTP in caso dei retry già previsti dal client.
Prima di ogni batch controllare il dry-run e dopo aggiornare il report. Si può
limitare l’invio a un PDF con `--pdf "nome-esatto.pdf"`, ripetendo l’opzione.
Non occorre reindicizzare le 360 fonti già coerenti.

Non completare automaticamente il corpus per consumare tutta la quota: in questo
intervento restano deliberatamente 1.047 chunk senza embedding. Nessun modello
locale, OCR o servizio alternativo è stato introdotto.

## Prodotti e cache

Rassegna, briefing, dossier, mappe, timeline, infografiche e Chat AI utilizzano
soltanto chunk realmente indicizzati e correnti. I nuovi PDF sono già sfogliabili
nell’Archivio PDF, ma **non entrano ancora nei prodotti basati sul catalogo**:
prima servono gli embedding autorizzati. Dopo il completamento incrementale:

1. **Rassegna / Briefing**: selezionare la nuova edizione nei filtri fonti,
   cercare keyword, esplorare gruppi dei vettori già presenti e generare
   esplicitamente la sintesi della selezione.
2. **Dossier**: inviare un tema pertinente e controllare edizioni citate e PDF.
3. **Podcast**: generare prima un briefing/dossier che citi le nuove fonti,
   poi selezionarlo nella biblioteca e autorizzare separatamente l’audio.
4. **Mappa**: inviare un tema e controllare concetti/prove; focus e cambio vista
   restano locali, senza ulteriori embedding o nuove relazioni.
5. **Timeline**: inviare un tema; distinguere eventi datati e sviluppi senza data.
   Le date di pubblicazione curate non sostituiscono le date degli eventi.
6. **Infografica**: usare Briefing → Infografica e creare esplicitamente un quadro
   per keyword. L’elaborazione è locale, ma le fonti sono comunque indicizzate.
7. **Chat AI**: inviare una nuova domanda e controllare i PDF citati. Lo storico
   non si rigenera automaticamente e le azioni Prepara aprono soltanto bozze.

L’audit locale ha rilevato due prodotti editoriali, cinque cache mappe/timeline
e due manifest audio con copertura precedente, **senza fonti obsolete**. Sono
stati conservati tutti. Le chiavi esistenti dei generatori includono catalogo,
copertura e configurazione: l’aggiunta di fonti/metadati li esclude logicamente
dai risultati del nuovo corpus, senza svuotare SQLite o le directory delle cache.
Il podcast resta legato al prodotto scelto e al relativo copione, non viene
aggiornato automaticamente. I risultati RAM con un totale di chunk diverso da
quello dell’archivio corrente mostrano un avviso di copertura precedente.

L’audit distingue `historical_coverage`, `obsolete_sources`, `current_sources`
e `unreadable`. Se in futuro cambia o viene rimosso un PDF, le chiavi e i controlli
del lettore impediscono il riuso corrente dei riferimenti obsoleti; il report
permette di individuare i soli prodotti interessati, senza cancellare quelli validi.
L’audit di copertura non ricalcola la validazione giornalistica o tutte le
versioni dei prompt: restano i controlli esistenti di ciascun generatore.

## Nuovo snapshot per Streamlit Cloud: preparazione manuale

Non è stato esportato o pubblicato alcun PDF. L’autorizzazione all’uso locale
o a Gemini non equivale al permesso di consultazione e download pubblici.

1. Identificare i singoli PDF distribuibili e autorizzare espressamente anche
   testi estratti, chunk, metadati e vettori. Non assumere autorizzati gli altri.
2. Completare solo l’indicizzazione necessaria, poi rieseguire audit e dry-run.
3. Chiudere l’app e gli altri processi che scrivono registro/Chroma.
4. Esportare in una **nuova** directory, elencando soltanto i file autorizzati:

```powershell
.\.venv\Scripts\python.exe -m edicola.cloud --export data/corpus_updates/seed-approved --pdf "nome-autorizzato.pdf" --authorize-distribution
```

Ripetere `--pdf` per ciascuna edizione precedente o nuova da includere. Se si
vogliono mantenere le vecchie edizioni anche nel cloud, occorre includerle
esplicitamente ed averne autorizzato la distribuzione. Il comando riusa solo i
vettori coerenti già esistenti e non completa un indice parziale via API.

Verificare il nuovo snapshot senza sostituire quello di deployment:

```powershell
.\.venv\Scripts\python.exe -m edicola.cloud --validate data/corpus_updates/seed-approved
```

La verifica controlla manifest, hash, file ammessi e registro; il ripristino
cloud controlla anche corrispondenza e dimensione dei vettori. Il pacchetto non
include profili, chat, cache generali/audio, backup, report, `.env` o Secrets.
La sostituzione dello snapshot di deployment, la revisione dei file da versionare,
i controlli Linux, commit/push e pubblicazione restano azioni manuali del gestore,
secondo DEPLOYMENT.md. Nessuna migrazione SQL o modifica di Secrets è richiesta
da questo aggiornamento. Le cancellazioni preesistenti nel working tree sotto
`deployment/seed` non sono state ripristinate o modificate da questo intervento.

## File di codice e verifiche

Creati `edicola/corpus_update.py`, `edicola/corpus_cache.py`,
`tests/test_corpus_update.py` e questa guida. Modificati `edicola/indexing.py`
(`--keep-stale`, conteggio corretto dei chunk già indicizzati), `edicola/cloud.py`
(`--validate` su directory nuova) e i quattro renderer dei risultati per l’avviso
di copertura storica: `reading_ui.py`, `knowledge_views.py`, `infographic_ui.py`,
`podcast_ui.py`. Aggiornati README e DEPLOYMENT. Nessuna migrazione SQL nuova.

I nuovi test usano PDF sintetici e Chroma temporaneo, con Gemini simulato:
acquisizione dei soli nuovi testi, idempotenza, preservazione dei vettori,
esclusione dei vettori storici dalla ricerca, metadati discordanti, audit senza
chiavi, riuso delle cache, ingresso di vecchie e nuove fonti in tutti e sette
i prodotti, esportazione limitata ai PDF autorizzati e verifica offline.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Risultato finale: **716 test superati**, nessun errore; 128 avvisi di deprecazione
delle dipendenze. Il test integrato usa vecchie e nuove fonti per tutti e sette
i prodotti, inclusi generazione testuale e WAV simulati. Il dry-run sul corpus
reale e il controllo delle differenze hanno avuto esito positivo.
