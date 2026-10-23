# Protocollo sperimentale — Task 8

Questo framework è separato dall'applicazione. Non modifica Streamlit, database, chunk, embeddings o profili salvati. Tutti i comandi tranne `benchmark` lavorano su dati locali. `benchmark` richiede un comando esplicito, `--limit` e `--authorize-external`; non viene eseguito da Streamlit. Non attiva fatturazione né seleziona servizi o modelli alternativi. Usa i modelli già configurati nel progetto.

Non sono presenti annotazioni sperimentali precompilate. Le fixture dei test sono sintetiche e non possono dimostrare la qualità dei quotidiani reali. I template versionati sono vuoti; i file di lavoro e i risultati sono ignorati da Git perché possono contenere testi dei giornali e valutazioni personali.

## 1. Congelare il perimetro, senza API

Eseguire dalla radice del repository, in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m edicola.evaluation snapshot --out evaluation/work/snapshot.json
.\.venv\Scripts\python.exe -m edicola.evaluation init --snapshot evaluation/work/snapshot.json --out evaluation/work/annotations
```

Lo snapshot esporta soltanto i chunk **attualmente indicizzati**, con ID, testo, PDF, pagina, metadati e copertura dell'archivio. Non ricostruisce gli articoli e non esegue embedding. L'hash collega contenuti, metadati e copertura. Se l'indice cambia, il benchmark rifiuta lo snapshot obsoleto **prima delle API**. Non aggiornare automaticamente le etichette: rivederle sul nuovo snapshot. I vecchi esperimenti restano ricalcolabili offline sul loro snapshot originale.

`init` crea `dataset.json`, `profiles.json`, `annotation-catalog.json` e `rubrics.json`. La destinazione deve essere nuova. Il catalogo consente di leggere i passaggi e copiare gli ID effettivi: non annotare ID indovinati dai nomi dei file. Confrontare anche i PDF originali per controllare eventuali errori di estrazione.

## 2. Annotare manualmente il dataset

Compilare `evaluation/work/annotations/dataset.json` e duplicare l'oggetto domanda per aggiungere casi:

- `id`: identificativo univoco della domanda, stabile nel protocollo.
- `question`: domanda reale formulata dall'annotatore; nessuna risposta viene generata dal framework per costruire il riferimento.
- `annotator`: pseudonimo del valutatore; documentare separatamente ruolo e procedura di annotazione.
- `answerability`: `"answerable"`, `"unanswerable"` oppure `null` se non ancora valutata, **rispetto allo snapshot indicizzato**, non rispetto al mondo o a tutti i PDF.
- `relevant_chunks`: oggetti con `chunk_id`, `pdf`, `page`, copiati dal catalogo e selezionati dopo lettura. Non basta una parola comune: il passaggio deve contenere informazioni utili per rispondere alla domanda.
- `nonrelevant_chunk_ids`: ID esplicitamente valutati come non pertinenti.
- `judgments_complete`: inizialmente `false`. Impostare `true` soltanto dopo revisione dell'intero snapshot per quella domanda: dichiara che tutti i rilevanti sono annotati e i restanti chunk sono negativi. Non è una proprietà che il codice può verificare da solo.
- `expected_points`: punti informativi attesi, scritti manualmente dopo lettura delle fonti, da usare per il giudizio umano di completezza. Può restare vuoto durante la preparazione; in tal caso non attribuire un punteggio di completezza senza prima definire il riferimento.
- `annotation_notes`: motivazione dei giudizi, eventuali ambiguità, perimetro della domanda e prove della sua non rispondibilità.

Per `unanswerable` servono verifica esaustiva (`judgments_complete=true`) e nessun positivo. È un'etichetta umana, non una conclusione ricavata dalla risposta del chatbot. Con giudizi incompleti non si attribuisce automaticamente rilevanza zero ai non giudicati. Il Recall@K non viene calcolato; Precision@K viene calcolata soltanto se ogni risultato è giudicato. Per MRR@K, un rango non giudicato precedente al primo positivo impedisce il calcolo.

```powershell
.\.venv\Scripts\python.exe -m edicola.evaluation validate --snapshot evaluation/work/snapshot.json --dataset evaluation/work/annotations/dataset.json
```

La validazione controlla hash dello snapshot, ID di domande/chunk, PDF/pagina, duplicati, giudizi contraddittori, annotatore e rispondibilità. Segnala annotazioni incomplete; non inventa né completa etichette.

Definire prima dell'esperimento categorie, distribuzione delle domande e criteri di rilevanza. Includere domande dirette, multi-fonte, temporali, ambigue e senza risposta quando documentabili. Evitare di scegliere soltanto domande già riuscite durante lo sviluppo. Separare casi di sviluppo e test finale; usare preferibilmente due annotatori indipendenti, annotare i disaccordi e concordare un riferimento prima di guardare i risultati del sistema. Dimensione e bilanciamento effettivi vanno riportati in tesi, non presunti dal framework.

## 3. Benchmark espliciti reali

Primo esperimento limitato al retrieval, con invio delle sole domande a Gemini:

```powershell
.\.venv\Scripts\python.exe -m edicola.evaluation benchmark --snapshot evaluation/work/snapshot.json --dataset evaluation/work/annotations/dataset.json --mode retrieval --k 3 --limit 1 --authorize-external --out evaluation/results/retrieval-01
```

Primo esperimento RAG, con invio di domande e passaggi autorizzati:

```powershell
.\.venv\Scripts\python.exe -m edicola.evaluation benchmark --snapshot evaluation/work/snapshot.json --dataset evaluation/work/annotations/dataset.json --mode rag --k 3 --limit 1 --authorize-external --out evaluation/results/rag-01
```

`--k` supporta 1–5, coerentemente con la ricerca esistente. `--limit` seleziona le prime N domande nell'ordine del dataset (massimo 100); non è campionamento casuale. `--repeat` ripete ogni domanda da 1 a 10 volte, default 1. La directory di una nuova esecuzione deve essere nuova, così non vengono sovrascritti risultati grezzi. Per confrontare K diversi usare lo stesso snapshot/dataset e directory distinte. Non confrontare direttamente indici o modelli diversi senza registrarne la variazione.

Il benchmark riutilizza `semantic_search`, `GeminiEmbedder`, prompt, generatore e validatore del RAG. Riproduce l'orchestrazione backend, **non misura il rendering Streamlit**. Non usa cache di generazione: una ripetizione reale può consumare nuove chiamate. Client SDK con un solo tentativo; si mantengono i retry applicativi esistenti, fino a tre per fase. Ogni tentativo passa dal contatore: non si stima il numero di chiamate semplicemente contando le domande. Non c'è garanzia che la quota disponibile basti: in caso di limite si registrano gli errori, senza abilitare fatturazione.

Sono raccolti:

- Tempi di retrieval (controlli locali, embedding della domanda e interrogazione Chroma), generazione LLM (inclusi retry/attese), totale backend (inclusa validazione). Preparazione, preflight dello snapshot e costruzione del client sono esclusi.
- Invocazioni SDK separate per embedding e generazione, durata del tentativo, modello, esito e codice HTTP se realmente disponibile. Gli status di successo non esposti dall'SDK restano mancanti: non si inventa HTTP 200. Gli eventi distinguono errore HTTP, trasporto e SDK/locale. Il contatore misura tentativi al confine SDK: una validazione locale può impedire l'invio HTTP; non è un conteggio certificato dal provider o una misura di fatturazione.
- Risultati ordinati con distanza, testi e fonti; risposta strutturata grezza, risposta validata e distinzione fra risposta, astensione, assenza di fonti e validazione fallita. Un output invalido non ottiene credito come astensione corretta.
- Timestamp UTC, versioni Python/librerie, impronta del codice, modello e dimensionalità, snapshot/dataset e impostazioni del benchmark. Non si salvano chiavi o eccezioni SDK grezze.

Le misure di latenza dipendono da rete, macchina, carico del servizio e cache locali: documentare sistema operativo, hardware, connessione, orario e condizioni warm/cold. Le cache locali non sono svuotate automaticamente. I tempi falliti sono analizzati separatamente. Per P95 servono almeno 20 campioni validi per la metrica; è una soglia operativa, non una dimostrazione di sufficienza statistica. Ripetere la stessa domanda non aumenta il numero di domande indipendenti nel test di qualità.

## 4. Metriche automatiche e ricalcolo offline

Per la domanda q, R è l'insieme dei chunk rilevanti annotati e L i primi K risultati:

- Precision@K = numero di rilevanti in L / K. Restituire meno di K risultati non riduce il denominatore.
- Recall@K = numero di rilevanti in L / numero di rilevanti annotati, soltanto con giudizi esaustivi e denominatore non nullo.
- MRR@K = media dei reciproci del primo rango rilevante entro K; zero se non viene trovato pur esistendo positivi annotati, mancante se il rango non è determinabile. È **troncato a K**, non MRR sull'intero indice.
- Copertura documentale della domanda = PDF distinti recuperati / PDF indicizzati nello snapshot. Si esporta anche la copertura dei PDF rilevanti, quando il riferimento è esaustivo.
- Copertura documentale globale = unione dei PDF recuperati nelle ricerche completate / PDF indicizzati. Non è la media delle coperture per domanda; è mancante se nessun retrieval è completato.

Il report espone media macro per campione domanda-esecuzione, mediana, P95 ove applicabile e conteggio di validi/mancanti. Per l'esperimento di qualità usare una singola esecuzione per domanda oppure aggregare esplicitamente le ripetizioni per domanda prima di trarre conclusioni. I risultati falliti non diventano metriche di rilevanza uguali a zero. Domande senza positivi annotati non entrano nel denominatore di Recall/MRR. Riportare sempre questi conteggi per non nascondere dati mancanti o sbilanciamenti.

```powershell
.\.venv\Scripts\python.exe -m edicola.evaluation score --snapshot evaluation/work/snapshot.json --dataset evaluation/work/annotations/dataset.json --run evaluation/results/rag-01/run.json --out evaluation/results/rag-01-ricalcolato
```

Questo comando non chiama API. Controlla il collegamento agli stessi dati e ricalcola metriche, tabelle e grafici dalle misure presenti. Una run importata deve usare lo stesso formato di `run.json`; la provenienza dichiarata dal file non viene certificata dal framework. Lo snapshot simulato non può essere etichettato come risultato reale.

## 5. Valutare il RAG con persone

`human_review.csv` contiene una riga per criterio e campione, con campi `run_id`, `item_id`, `kind`, `origin`, `reviewer`, `criterion`, `score`, `evidence`, `notes`. Gli score sono **vuoti**. Usare 0–4 con le ancore esplicite di `rubrics.json`, oppure `NA` motivato; vuoto significa non ancora valutato. Ogni punteggio richiede valutatore e prove verificabili. Per due valutatori duplicare le righe con identificativi diversi; lo stesso giudizio dello stesso valutatore non può comparire due volte.

Leggere domanda, passaggi recuperati e PDF originali collegati, punti attesi e risposta in `run.json`. Valutare separatamente accuratezza dei fatti, fedeltà semantica, citazioni a sostegno della specifica affermazione, gestione della non rispondibilità e completezza. Il controllo automatico di ID e citazioni letterali **non prova** che il testo citato implichi la conclusione, né che sia corretta o completa. Non chiamarlo factual accuracy o faithfulness.

```powershell
.\.venv\Scripts\python.exe -m edicola.evaluation score --snapshot evaluation/work/snapshot.json --dataset evaluation/work/annotations/dataset.json --run evaluation/results/rag-01/run.json --reviews evaluation/results/rag-01/human_review.csv --out evaluation/results/rag-01-valutato
```

La scheda deve riferirsi all'esatto hash di run e ai campioni valutati. Il report rigenerato non sovrascrive schede umane già compilate nella sua directory. I punteggi sono ordinali: la media è descrittiva, non una distanza psicometrica; conservare giudizi individuali, mediana e motivazioni. Un giudizio umano è un dato reale solo se il prodotto reale è stato effettivamente esaminato; non basta cambiare `origin` nel CSV.

## 6. Dossier, briefing, timeline, mappe e podcast

Non vengono generati nuovi prodotti per valutarli. Scegliere quelli già disponibili nelle rispettive cache, conservando chiave/versione, fonti, copertura, budget e copia del risultato; per i podcast conservare anche WAV, copione, modello e voce. L'identificativo sotto è un **segnaposto da sostituire** con quello del prodotto reale:

```powershell
.\.venv\Scripts\python.exe -m edicola.evaluation prepare-review --kind briefing --item-id "CHIAVE_REALE_DEL_PRODOTTO" --origin real --out evaluation/work/review-briefing
```

Tipi supportati: `dossier`, `briefing`, `timeline`, `map`, `podcast`, oltre a `rag` e `personalization`. La scheda è vuota; il framework non afferma che l'identificativo inserito esista nella cache. Allegare l'artefatto scelto e il suo riferimento alle fonti al fascicolo di valutazione.

I criteri comuni sono fedeltà, completezza rispetto a copertura/budget, duplicazioni, struttura e citazioni. Timeline e contenuti datati richiedono controllo separato di data di pubblicazione, evento, anno completato, annunci e accadimenti. Per le mappe verificare ogni relazione e non scambiare associazioni tematiche per causalità. Per il podcast ascoltare realmente il WAV e valutare intelligibilità, pronuncia, ritmo, pause e artefatti, confrontando anche il copione con il prodotto di partenza. Un estratto breve non va penalizzato per non includere contenuti fuori dal suo perimetro dichiarato.

Dopo aver compilato la scheda:

```powershell
.\.venv\Scripts\python.exe -m edicola.evaluation reviews --sheet evaluation/work/review-briefing/human_review.csv --out evaluation/results/review-briefing
```

Non viene assegnato alcun punteggio alle celle vuote o NA. Per raccogliere più prodotti/valutatori si possono unire righe con la stessa intestazione, mantenendo ID e provenienze distinti. Non unire risultati reali e simulati in un'unica media.

## 7. Personalizzazione, solo locale

Compilare almeno due profili in `evaluation/work/annotations/profiles.json`, con interessi differenti tratti dal perimetro scelto, tempo 2/5/10, formato e feedback esplicito (`1` gradito, `-1` escluso, o assenza della chiave per neutro). `saved` deve restare vuoto: non si leggono utenti o storico personali. Per studiare l'effetto del feedback mantenere identici interessi e impostazioni di base; prima viene applicato lo stesso profilo senza feedback, poi quello dichiarato.

```powershell
.\.venv\Scripts\python.exe -m edicola.evaluation personalization --snapshot evaluation/work/snapshot.json --profiles evaluation/work/annotations/profiles.json --out evaluation/results/personalization-01
```

Il comando non apre Chroma né SQLite: riutilizza `recommend` sullo snapshot. Salva profili demo, liste prima/dopo, punteggi locali e motivazioni. Misura copertura lessicale degli interessi attivi, copertura dei PDF, quota di duplicati testuali, frazione di posizioni cambiate dopo feedback e distanza di Jaccard tra i risultati dei profili (0=insiemi uguali, 1=disgiunti). Se entrambi gli insiemi sono vuoti, la distanza è mancante. Queste misure non dimostrano pertinenza semantica o soddisfazione dell'utente: completare la scheda umana. Il formato preferito è un'impostazione di fruizione, non un segnale di apprendimento del ranking; le differenze possono essere nulle e vanno riportate tali.

## 8. Materiali esportati e uso nella tesi

Ogni report comprende `metrics.csv`, `summary.csv`, `report.md`, `rubrics.json` e grafici Altair (`metrics.html`, `metrics.vl.json`). Quando applicabile comprende una scheda umana vuota. La run grezza conserva misure e fonti; lo studio personale ha `personalization.json`. L'HTML dei grafici carica Vega da CDN solo quando aperto nel browser: serve rete per il renderer, senza chiamate Gemini; CSV e report sono offline. Nessuna nuova dipendenza è necessaria: Altair è già presente con Streamlit.

In tesi possono essere usati:

- Metriche di retrieval di run reali sul dataset manualmente annotato, con K, conteggi dei giudizi, dimensione del corpus e limiti dell'indice parziale.
- Latenze, tentativi API ed errori realmente osservati, con configurazione e condizioni di esecuzione; non le durate delle API simulate.
- Valutazioni umane completate sui prodotti reali, con protocollo, numero e ruolo dei valutatori, eventuali disaccordi e limiti della scala.
- Risultati locali della personalizzazione sui profili demo dichiarati, separando corrispondenze lessicali, diversità e giudizi umani. Non presentarli come machine learning o come studio utenti senza aver svolto uno studio utenti.
- Test sintetici esclusivamente come verifica del software e della correttezza del calcolo delle metriche, chiaramente distinti dall'efficacia sperimentale.

Il framework non ha prodotto risultati sperimentali reali durante lo sviluppo. Non compilare tabelle della tesi con numeri di esempio come se fossero osservazioni. Conservare i dati mancanti e dichiarare i motivi delle esclusioni.

Test riproducibili senza API:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_evaluation.py
```
