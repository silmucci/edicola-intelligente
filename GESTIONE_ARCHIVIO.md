# Gestione incrementale dell’archivio

## Aprire la gestione locale

Nella cartella del progetto fare doppio clic su **Gestione archivio.cmd**.
Si apre una console con sei scelte; digitare il numero e premere Invio.
Non occorre scrivere comandi Python. Serve l’ambiente `.venv` già usato dal progetto.

Questa è una procedura riservata a chi ha accesso al computer e ai file locali.
Il login Google nell’app non attribuisce privilegi amministrativi. La gestione
non è una pagina pubblica Streamlit e non è richiamabile da una sua sessione.
Il launcher seleziona il corpus locale **solo nel proprio processo**, anche quando
la configurazione del progetto usa la demo cloud: non modifica `.env` o Secrets.
Proteggere quindi l’accesso al computer e alla cartella del progetto.

Per evitare scritture da processi esterni, chiudere l’app locale e non avviare
contemporaneamente vecchi comandi di indexing durante preparazione, batch o
esportazione. Il lock impedisce due operazioni della nuova gestione contemporanee;
non può bloccare un altro programma che scrive direttamente nei database.

## 1 — Stato ed edizioni

Mostra PDF, testata e data curate, pagine, chunk, stato del documento e numero di
passaggi indicizzati/mancanti. Riporta copie identiche, pagine escluse e metadati
da verificare, oltre agli ultimi batch e agli errori riconoscibili.
Questa consultazione non chiama Gemini e non acquisisce o rielabora i documenti.

Punto di partenza del presente lavoro:

| Dato | Quantità |
|---|---:|
| PDF acquisiti | 12 |
| Pagine | 449 |
| Chunk preparati | 1.407 |
| Chunk indicizzati da conservare | 360 |
| Chunk mancanti | 1.047 |

I 1.047 mancanti comprendono 810 chunk dei sette nuovi PDF e 237 delle edizioni
precedenti. **Non è stata eseguita l’indicizzazione reale di questi chunk.**
Durante questo lavoro non sono state ripetute acquisizione o preparazione dei
dodici PDF, né ricostruito l’indice. Sono stati eseguiti solo stato e anteprima
sul corpus reale; le operazioni di scrittura e le API sono state provate su dati
sintetici nei test.

## 2 — Aggiungere e preparare nuove edizioni

1. Aprire `data/incoming` con Esplora file.
2. Copiare i nuovi PDF, usando nomi distinti per ogni edizione. **Non sostituire
   il file di un’edizione da conservare.** Nessun upload è necessario o disponibile.
3. Nella console scegliere **1** per controllare i nuovi file.
4. Scegliere **2** e digitare **PREPARA** per acquisizione e chunking locali.
5. Tornare a **1** e controllare anomalie e passaggi mancanti.

La gestione riusa i moduli esistenti per SHA-256 e configurazione. Se tutto è già
preparato, non richiama nemmeno acquisizione/chunking. Una copia identica riusa
estrazione e ID senza creare embedding duplicati; gli esiti negativi sono anch’essi
persistenti. I PDF non elaborabili restano segnalati, senza OCR o servizi alternativi.
Prima di una preparazione necessaria viene salvata una copia coerente del registro.

Un PDF modificato con lo stesso nome viene riconosciuto dal nuovo hash. Le vecchie
estrazioni e i vettori storici non vengono eliminati; tuttavia, se il gestore ha
sovrascritto il PDF originale, il programma non può ricostruirne i byte. Per poter
consultare entrambe le edizioni servono entrambi i PDF con nomi distinti.

## 4 — Verificare testata e data

1. Scegliere **4**, poi il numero dell’edizione indicato nell’elenco.
2. Aprire il PDF originale da `data/incoming` e verificare la testata e la data
   dell’edizione. La data di una notizia non è la data di pubblicazione del giornale.
3. Inserire i valori verificati; per la data usare `AAAA-MM-GG`, per esempio
   `2026-10-30`. Lasciare vuoto un valore che non è possibile determinare.
4. Digitare **CONFERMO METADATI** soltanto dopo la verifica nel PDF.

La modifica riguarda una sola edizione, conserva gli altri campi e le altre voci,
crea un backup e sostituisce atomicamente il JSON. Una data impossibile o in
contrasto con una dicitura riconosciuta **Edizione del …** viene rifiutata.
Il programma non inventa testate, date o classificazioni geografiche.

## 3 — Controllare e autorizzare un batch

1. Scegliere **3** e una dimensione: **10**, **20** o **50** chunk.
2. Premere Invio per tutte le edizioni oppure indicare il nome esatto di un PDF.
3. Leggere il riepilogo: totali, indicizzati, mancanti e quantità del prossimo
   batch. L’elenco mostra file, pagina e lunghezza di ciascun passaggio.
4. Se necessario, inserire il numero di un chunk per leggerne il testo locale.
5. Per annullare premere Invio alla richiesta di autorizzazione.
6. Solo per un invio reale consapevole, digitare esattamente **AUTORIZZO N**, dove
   `N` è il numero mostrato. Per esempio, **AUTORIZZO 10** per dieci passaggi.

L’invio reale usa **Google Gemini Embedding 2**, dimensione 768. Richiede chiave,
accesso e quota già configurati; non attiva fatturazione né fallback a servizi a
pagamento. Questa autorizzazione vale per il solo batch mostrato, non per tutti
i chunk mancanti. Se il piano cambia prima dell’avvio, viene richiesta una nuova
anteprima. Durante il batch vengono mostrati i chunk salvati progressivamente.

Alla fine si torna al menu. **Non parte automaticamente il batch successivo.**
Per continuare occorrono nuova anteprima e nuova autorizzazione. Il piano viene
ricalcolato sull’indice: i chunk coerenti già salvati vengono saltati, inclusi i
360 embedding iniziali. I metadati vengono riconciliati senza reinviare il testo;
gli eventuali vettori storici restano conservati ed esclusi dalla ricerca corrente.

## 6 — Indicizza tutti i chunk mancanti

Questa opzione evita la conferma manuale di ogni batch. Cerca i mancanti in tutte
le edizioni e mostra file coinvolti, chunk per PDF, totale, richieste previste a
Google Gemini e massimo dei tentativi inclusi i retry. Non acquisisce nuovamente
i PDF e non ricostruisce l’indice.

1. Aprire **Gestione archivio.cmd** e scegliere **6 — Indicizza tutti i chunk mancanti**.
2. Controllare il riepilogo. Con lo stato attuale sono **1.047 chunk in 9 PDF**,
   quindi **1.047 richieste previste**, fino a **3.141 tentativi** se servissero
   tutti i retry. Eventuali vettori già nella coda durevole riducono le nuove API.
3. Per annullare premere Invio. Per autorizzare l’intero piano digitare esattamente
   **AUTORIZZO TUTTI 1047**, oppure il numero aggiornato mostrato dalla console.
4. Dopo la conferma la sequenza prosegue in batch da **massimo 50**: con 1.047
   mancanti sono **21 batch**, l’ultimo di 47. Non occorre confermarli uno per uno.
5. Controllare i messaggi di avanzamento: completati dell’operazione, totale
   indicizzato nell’archivio e rimanenti. Ogni risposta riuscita viene salvata
   durevolmente e poi scritta in Chroma, senza attendere la fine del batch.
6. Per interrompere premere **Ctrl+C**. Per riprendere, anche dopo un riavvio,
   scegliere nuovamente **6** e confermare il riepilogo dei soli mancanti rimasti.

L’autorizzazione riguarda l’insieme finito mostrato, non PDF aggiunti o modificati
successivamente. Un piano cambiato viene fermato e richiede una nuova conferma.
Il lock resta attivo per l’intera sequenza. I batch condividono il diario e la
coda durevole già esistenti; non si cancellano i 360 vettori iniziali o quelli
salvati durante l’operazione. Il comando **3** resta disponibile per un singolo PDF
o un batch ridotto.

In caso di quota o errore persistente si ferma **tutta la sequenza**, senza
attendere automaticamente il ripristino della quota e senza avviare un altro
batch. Le pause del diario impediscono una ripartenza prematura. Non viene
aumentata la quota né attivato alcun servizio a pagamento: la disponibilità della
quota reale va comunque verificata dal gestore, e può impedire di completare
tutti i chunk in una sola esecuzione. Nessuna indicizzazione reale di questi
1.047 chunk è stata avviata durante l’implementazione.

### Quote, errori e interruzioni

Queste regole valgono sia per il batch singolo sia per la sequenza completa.

- Per errori temporanei il client prova al massimo **3 volte per chunk**, con
  attese di 1 e 2 secondi. Il batch ha un tetto complessivo di `3 × N` tentativi.
- Dopo un `429` persistente il batch va in pausa e blocca nuovi batch per almeno
  60 secondi. È un minimo locale, non una garanzia di disponibilità della quota.
- Per `503`, timeout e altri errori temporanei esauriti, la pausa minima è 15
  secondi. Poi serve comunque un nuovo invio del gestore.
- Errori permanenti, per esempio accesso negato o modello non disponibile, fermano
  il batch. Verificare la configurazione prima di riprovare; niente retry infinito.
- Premere `Ctrl+C` durante il batch lo interrompe. Anche chiusura improvvisa e
  riavvio mantengono i vettori già scritti. Alla riapertura scegliere **1**, poi
  **3** per controllare e autorizzare la ripresa dai soli chunk mancanti.

Il lock del sistema operativo viene liberato anche dopo un crash. Il diario in
`data/corpus_updates/manager.sqlite3` conserva stato, conteggi, ID e tentativi,
senza chiavi, richieste complete o errori SDK grezzi. Prima dell’upsert Chroma,
il vettore ricevuto viene salvato in una coda privata: se la scrittura fallisce,
la ripresa lo riutilizza senza una seconda API. Un crash fra commit Chroma e
aggiornamento del diario viene riconciliato con l’indice al successivo avvio.

Resta un limite inevitabile: se il processo si arresta **prima** che una risposta
API ricevuta sia stata salvata localmente, non è possibile sapere se il servizio
abbia consumato quota. Una successiva autorizzazione può dover ripetere quel chunk.
Non cancellare il diario o la coda per tentare di ripartire da zero.

## Usare le fonti aggiornate nei sette prodotti

La disponibilità cresce a ogni batch riuscito; non serve completare tutto il
corpus. Nessun prodotto viene rigenerato dall’aggiunta di un PDF o dalla navigazione.

| Prodotto | Come utilizzare le nuove fonti |
|---|---|
| Rassegna / Briefing | Filtri per fonti, keyword, intervallo di date curate e ultima data disponibile; gruppi tematici locali. Poi invio esplicito della sintesi. |
| Dossier | Nuovo invio su un tema: fonti recuperate tra più edizioni, citazioni e limiti di copertura. |
| Podcast | Prima un briefing/dossier aggiornato in cache, poi scelta del prodotto e consenso audio distinto. Il vecchio audio non viene sostituito automaticamente. |
| Mappa | Nuovo invio per includere le nuove prove; focus e cambio Grafo/Elenco non chiamano API. |
| Timeline | Nuovo invio: cronologia solo per date evento verificate, sviluppi senza data separati. |
| Infografica | Creazione locale esplicita sui chunk indicizzati, con soli estratti documentati. |
| Chat AI | Nuova domanda, anche di confronto tra edizioni; avviso se il corpus è parzialmente indicizzato. |

Le identità deterministiche `corpus_version` e `selection_version` comprendono
chunk/fingerprint, metadati e selezione. Rilevano aggiornamenti anche a parità di
conteggi. Le cache dei generatori restano distinte per prodotto e configurazione;
una rassegna su fonti/date specifiche può riusare contenuti compatibili anche
quando cambiano edizioni esterne alla selezione. Le vecchie coperture restano
riconoscibili come storiche; non si svuotano database, directory o risultati RAM.
I prodotti precedenti senza versione vengono trattati conservativamente come
coperture storiche quando si confrontano con il catalogo versionato.

## 5 — Preparare lo snapshot Cloud autorizzato

1. Controllare i diritti di **ciascun PDF**, inclusi testi derivati, embedding,
   consultazione e download via web. Uso locale e consenso Gemini non bastano.
2. Scegliere **5** e indicare i numeri dei soli PDF distribuibili, separati da
   virgole. Includere anche le vecchie edizioni autorizzate che si vogliono mantenere.
3. Rileggere l’elenco. Digitare **AUTORIZZO DISTRIBUZIONE** solo se i diritti sono
   verificati. Premere Invio per annullare.
4. La console crea e verifica una nuova cartella privata `data/corpus_updates/snapshot-…`.
   Nessuno snapshot precedente viene sovrascritto e nessuna API viene chiamata.
5. Controllare PDF inclusi e conteggi indicizzati/mancanti; un pacchetto parziale
   resta dichiaratamente parziale. Non vengono generati vettori per completarlo.
6. Seguire **DEPLOYMENT.md** per la revisione del pacchetto, la sostituzione manuale
   di `deployment/seed`, il controllo dei file da versionare e il rilascio manuale.
   Non copiare l’intera cartella `data` nel repository.
7. Dopo il rilascio verificare online copertine, pagine/download, copertura, nuove
   fonti e isolamento degli account. Eventuali prove Gemini richiedono invio e consenso.

Lo snapshot include soltanto PDF nominati, registro selettivo, metadati e vettori
coerenti già disponibili. Esclude diario, backup, coda dei batch, chiavi, Secrets,
profili, chat e cache editoriali/audio. Nel cloud rimane il ripristino dai vettori
dello snapshot, non una nuova indicizzazione. Le verifiche esistenti del manifest
controllano hash e file ammessi; il ripristino controlla anche vettori e riferimenti.

Nessun PDF è stato esportato dal corpus reale in questo task. Nessun commit,
push, deployment o nuovo servizio cloud è stato attivato. Le cancellazioni
preesistenti nel working tree sotto `deployment/seed` non sono state modificate.

## Upload Cloud: progettazione futura separata

Non è stato aggiunto alcun upload. Prima di proporlo servono almeno:

- ruoli amministrativi verificati dal server, collegati a issuer/subject OIDC,
  revocabili e controllati su ogni operazione; mai semplice login, email o flag client;
- storage persistente dei PDF e dei dati derivati con accessi controllati e
  isolamento dai dati personali, non il disco effimero di Community Cloud;
- una coda persistente di lavori con lock condivisi, quote, autorizzazioni per
  singolo batch, audit e ripresa tra processi/server diversi;
- controlli su dimensioni, PDF non attendibili, diritti di distribuzione, versioni
  e transizione fra corpus pubblicato e nuova versione verificata.

Questi componenti richiedono un progetto dedicato. Il lock locale e il diario
SQLite di questa console non sono un sistema amministrativo distribuito.

## Analisi del riuso e file

Già esistenti e riutilizzati: SHA-256/estrazioni persistenti (`ingestion`, `storage`),
chunking per hash/configurazione, `plan_index`/`apply_plan`, controllo del modello
e dimensione Chroma, retry Gemini limitati, retrieval dei soli chunk correnti,
generatori/validatori dei sette prodotti ed esportazione selettiva dello snapshot.

Creati in questo task:

- `Gestione archivio.cmd`, `edicola/archive_manager.py`: ingresso locale e menu;
- `edicola/incremental.py`: anteprima, autorizzazione, batch e ripresa;
- `edicola/maintenance_store.py`: lock, diario e coda durevole dei vettori;
- `edicola/maintenance_metadata.py`: conferma e salvataggio atomico dei metadati;
- `edicola/maintenance_snapshot.py`: preparazione controllata del pacchetto;
- `edicola/corpus_versions.py`: identità deterministiche;
- `tests/test_incremental_manager.py` e questa guida.

Modificati: `embeddings.py` (conteggio tentativi e controlli prima dei retry),
`corpus_update.py` (duplicati, preparazione, pagine escluse e versione),
`editorial_selection.py`, `press_review.py`, `press_review_ui.py`, `editorial.py`,
`reading_ui.py`, `product_navigation.py`, `corpus_cache.py`, README, CORPUS_UPDATE
e DEPLOYMENT. Non cambiano prompt, validator delle prove, Google Login o Supabase.
Nessuna migrazione PostgreSQL: il piccolo diario locale viene creato alla prima
operazione di batch, separato dal registro e dai database personali.

## Verifiche

I test usano PDF sintetici, Chroma temporaneo e risposte SDK simulate. Coprono
aggiunte, duplicati, modifiche, batch parziali, ripresa dopo errore/interruzione,
quota/servizio/timeout, lock, autorizzazioni, coda durevole, riconciliazione dopo
commit, fonti/pagine, cache e snapshot. Rimane il test integrato dei sette prodotti
con edizioni precedenti e nuove. I dati reali vengono controllati solo in lettura.

Risultato: **733 test superati** nella suite completa, più **58 controlli mirati
finali superati** (sottoinsieme della suite, non da sommare). I 17 nuovi casi del
gestore usano soltanto API simulate. Presenti avvisi di deprecazione delle dipendenze,
nessun errore nella suite finale.

Il confronto finale delle impronte conferma **registro SQLite identico** e **tutti
i 360 vettori, testi e metadati Chroma identici** alla baseline di questo task.
Il corpus resta di 12 PDF, 449 pagine, 1.407 chunk, 360 indicizzati e 1.047 mancanti.
Nessuna API reale, acquisizione o preprocessing del corpus già preparato. Il diario
dei batch non è stato creato nel corpus reale: verrà creato alla prima operazione
autorizzata. Riepilogo privato in `data/corpus_updates/incremental-verification.json`.

### Aggiornamento: sequenza completa dei mancanti

L’opzione 6 riusa l’esecutore dei batch, il lock e il diario esistenti. Aggiunti
`edicola/incremental_all.py` e `tests/test_incremental_all.py`; aggiornati
`incremental.py`, `archive_manager.py`, questa guida e README. I test aggiuntivi
coprono conferma/cancellazione, più di 50 chunk, arresto per errori e quota,
interruzione/ripresa, cambi del corpus e conservazione dei vettori precedenti.
Verifica finale dell’aggiornamento: **745 test superati**, inclusi 12 nuovi casi
della modalità completa. Tutte le API dei test sono simulate. Il confronto delle
impronte conferma registro e 360 vettori reali invariati: 1.407 chunk totali,
1.047 ancora mancanti. Nessuna indicizzazione reale, modifica ai Secrets,
commit, push o deployment.
