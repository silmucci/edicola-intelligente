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

## 9. Riprendere i soli giudizi Groq falliti

Per ripetere esclusivamente i giudizi delle risposte RAG già registrati con
`status: "judge_error"` (senza ricalcolare la rilevanza dei chunk o modificare
giudizi validi, astensioni e altri stati), usare `--solo-giudizi-falliti` insieme
a `--valuta-risposte`. Il file `--out` esistente deve appartenere alla stessa run,
modello e provider. La ripresa non riprova automaticamente gli errori: ogni
invocazione è esplicita, richiede `--autorizza-api` e rispetta la pausa Groq
configurata. Una risposta che non supera parsing o validazione resta `judge_error`.

Esempio per `llm_gt100_parte2_risposte.json`:

```powershell
python evaluation/llm_relevance_judge.py --run evaluation/results/rag_gt100_parte2_01/run.json --dataset evaluation/work/annotations/dataset_gt100_parte2.json --snapshot evaluation/work/snapshot.json --out evaluation/results/llm_gt100_parte2_risposte.json --limit 50 --valuta-risposte --solo-giudizi-falliti --autorizza-api
```

Le nuove righe `judge_error` registrano un codice diagnostico stabile e, per
errori di validazione, il criterio coinvolto; i testi grezzi delle risposte Groq
e le eccezioni SDK non vengono salvati.

## 10. Esperimento di completezza del prompt RAG

Il benchmark usa `SYSTEM_INSTRUCTION` e invia domanda e fonti con
`build_prompt`; nello scenario registrato recupera K=3 chunk. Il suo schema
ammette al massimo 8 claim e `rag_assessment` applica la validazione stretta
dell'intera risposta. La Chat usa `CHAT_INSTRUCTION`, che aggiunge regole
temporali, confronti fra fonti e profondita editoriale; ammette fino a 12 claim,
seleziona fino a 64 candidati e li adatta al budget del contesto. Inoltre
`validate_chat_response` puo conservare claim validi quando altri sono respinti.
Quindi una differenza osservata fra benchmark e Chat non identifica da sola un
effetto del prompt: retrieval, ampiezza del contesto, schema e validazione
differiscono.

Cause plausibili di incompletezza da distinguere nella revisione sono:

- **Informazione non recuperata o esclusa:** con K=3 un fatto richiesto puo
  trovarsi in un altro chunk indicizzato, non nei tre inviati. Se manca dal
  contesto, un prompt piu esplicito non puo documentarlo. Controllare anche
  estrazione e confini dei chunk prima di attribuire la lacuna alla generazione.
- **Informazione presente ma non usata:** se il passaggio contiene il fatto e
  una citazione verificabile ma la risposta omette una parte della domanda, e
  plausibile una copertura incompleta dei claim. L'istruzione originale chiede
  una risposta breve e coerente e prove per ogni claim, ma non guida
  esplicitamente la scomposizione delle domande multi-parte.

La revisione va fatta domanda per domanda, confrontando i punti attesi con i
chunk effettivamente inviati. Le metriche aggregate, da sole, non dimostrano
quale delle due cause abbia operato.

L'esperimento isolato `completeness-v1` non modifica `ask_question`, il prompt
originale, il benchmark standard, la Ground Truth o le run gia salvate. Aggiunge
solo istruzioni per scomporre la domanda, coprire i fatti pertinenti disponibili,
non omettere qualificazioni e dichiarare i limiti delle fonti. Riusa per ogni
domanda gli stessi chunk recuperati, nello stesso ordine; mantiene modello,
schema di risposta, temperatura e validatore del benchmark. Non esegue retrieval
o embedding. Invia nuovamente a Gemini domanda e chunk solo con autorizzazione
esplicita; non invia `expected_points` o `reference_answer`.

La run sperimentale viene salvata in una directory separata che deve non esistere.
Per ciascuna coppia di run, usare il dataset esatto e collegato agli hash originali:

```bash
python -m edicola.prompt_experiment \
  --snapshot evaluation/work/snapshot.json \
  --dataset evaluation/work/annotations/dataset_gt100_parte2.json \
  --baseline-run evaluation/results/rag_gt100_parte2_01/run.json \
  --out evaluation/results/prompt-completeness-gt100-parte2 \
  --authorize-external
```

Per una run selettiva passare gli ID con `--only-ids` e il CSV Ground Truth.
Prima di creare la directory il comando verifica che ogni ID sia incompleto
nella baseline, abbia retrieval e chunk disponibili, non sia `Non rispondibile`
e non abbia gia una risposta `answered` in una run indicata con
`--exclude-validated-run`. I chunk esatti della baseline vengono riusati e,
in questa modalita, si effettua una sola generazione per domanda:

```bash
python -m edicola.prompt_experiment \
  --snapshot evaluation/work/snapshot.json \
  --dataset evaluation/work/annotations/dataset_gt100_parte2.json \
  --baseline-run evaluation/results/rag_gt100_parte2_01/run.json \
  --out evaluation/results/prompt-completeness-recupero9-v2 \
  --authorize-external \
  --ground-truth-csv evaluation/data/Ground_Truth_Edicola_150_domande.csv \
  --exclude-validated-run evaluation/results/prompt-completeness-gt100-parte2/run.json \
  --exclude-validated-run evaluation/results/prompt-completeness-recupero9/run.json \
  --only-ids GT-103,GT-104,GT-105,GT-106,GT-113,GT-118,GT-120,GT-121,GT-136
```

Si puo ripetere `--exclude-validated-run` per controllare piu esperimenti.
`--only-ids` e `--retry-errors` sono mutuamente esclusivi. La selezione non
modifica run, Ground Truth o giudizi precedenti; ogni risposta resta soggetta
alla validazione RAG normale.

Il comando sopra e un protocollo da eseguire in seguito, non e stato avviato.
Eseguire una volta per ogni run/coorte, cambiando dataset, baseline e destinazione.
Nel checkout e disponibile anche la coppia `dataset_gt50_sviluppo.json` /
`rag_gt50_completo_01/run.json`. Non e invece presente il dataset esatto della
run `rag_gt100_parte1_v2` (hash `50169bd7...`); il sottoinsieme di
`dataset_gt100_finale.json` ha un hash diverso, quindi non va usato come
sostituto. Per una comparazione completa delle 150 domande occorre ripristinare
quel JSON originale. Non fondere run con dataset diversi e non rietichettare
annotazioni.

Comandi selettivi per i candidati attualmente rimasti (non eseguiti):

```bash
python -m edicola.prompt_experiment \
  --snapshot evaluation/work/snapshot.json \
  --dataset evaluation/work/annotations/dataset_gt50_sviluppo.json \
  --baseline-run evaluation/results/rag_gt50_completo_01/run.json \
  --out evaluation/results/prompt-completeness-recupero-gt50 \
  --authorize-external \
  --ground-truth-csv evaluation/data/Ground_Truth_Edicola_150_domande.csv \
  --only-ids GT-002,GT-011,GT-012,GT-041

python -m edicola.prompt_experiment \
  --snapshot evaluation/work/snapshot.json \
  --dataset evaluation/work/annotations/dataset_gt100_parte1_originale.json \
  --baseline-run evaluation/results/rag_gt100_parte1_v2/run.json \
  --out evaluation/results/prompt-completeness-recupero-gt100-parte1 \
  --authorize-external \
  --ground-truth-csv evaluation/data/Ground_Truth_Edicola_150_domande.csv \
  --only-ids GT-070,GT-076,GT-080,GT-100

python -m edicola.prompt_experiment \
  --snapshot evaluation/work/snapshot.json \
  --dataset evaluation/work/annotations/dataset_gt100_parte2.json \
  --baseline-run evaluation/results/rag_gt100_parte2_01/run.json \
  --out evaluation/results/prompt-completeness-recupero-gt100-parte2 \
  --authorize-external \
  --ground-truth-csv evaluation/data/Ground_Truth_Edicola_150_domande.csv \
  --exclude-validated-run evaluation/results/prompt-completeness-gt100-parte2/run.json \
  --exclude-validated-run evaluation/results/prompt-completeness-recupero9/run.json \
  --only-ids GT-103,GT-104,GT-105,GT-106,GT-113,GT-118,GT-120,GT-121,GT-136
```

Il secondo comando e pronto solo dopo aver ripristinato il dataset originale
esatto, non presente nel checkout; `dataset_gt100_finale.json` non e un
sostituto valido. Le tre destinazioni sono nuove e mantengono intatti tutti i
risultati precedenti.

Se una run sperimentale contiene errori di generazione, si possono ritentare
soltanto quei record indicando la directory gia esistente e `--retry-errors`.
Prima dell'invio il comando verifica la baseline, il dataset, lo snapshot, il
prompt, il modello e i chunk conservati nella run. Ogni risposta riuscita viene
salvata atomicamente; gli errori mantengono il record precedente e i record gia
riusciti non vengono rigenerati. Non crea una nuova directory.

Per recuperare esclusivamente gli errori della parte 2 (non eseguito):

```bash
python -m edicola.prompt_experiment \
  --snapshot evaluation/work/snapshot.json \
  --dataset evaluation/work/annotations/dataset_gt100_parte2.json \
  --baseline-run evaluation/results/rag_gt100_parte2_01/run.json \
  --out evaluation/results/prompt-completeness-gt100-parte2 \
  --authorize-external \
  --retry-errors
```

Le run disponibili hanno 50 record e condividono snapshot, modello
`gemini-3.5-flash-lite` e K=3, ma dataset diversi per coorte. Il file
`dataset_gt100_finale.json` non sostituisce il dataset mancante della parte 1:
il suo hash, anche filtrandolo sui 50 ID della relativa run, non coincide con
l'hash registrato nel baseline.

Quando si valuteranno i nuovi output, usare file di giudizio distinti anche
per la baseline, così i risultati storici restano immutati. Esempio futuro
per la coppia disponibile di parte 2 (non eseguire durante la preparazione):

```bash
python evaluation/llm_relevance_judge.py \
  --run evaluation/results/rag_gt100_parte2_01/run.json \
  --dataset evaluation/work/annotations/dataset_gt100_parte2.json \
  --snapshot evaluation/work/snapshot.json \
  --out evaluation/results/prompt-completeness-gt100-parte2-baseline-judge.json \
  --limit 50 --solo-risposte --valuta-risposte --autorizza-api

python evaluation/llm_relevance_judge.py \
  --run evaluation/results/prompt-completeness-gt100-parte2/run.json \
  --dataset evaluation/work/annotations/dataset_gt100_parte2.json \
  --snapshot evaluation/work/snapshot.json \
  --out evaluation/results/prompt-completeness-gt100-parte2-experiment-judge.json \
  --limit 50 --solo-risposte --valuta-risposte --autorizza-api
```

Il primo comando rivaluta la baseline in un file nuovo; non riutilizzare come
output il JSON originale. Entrambi usano la configurazione predefinita dello
stesso giudice Groq. Eseguire i comandi solo dopo approvazione esplicita: sono
valutazioni reali, non parte dei test mock.

Le chiamate API sono seriali, contate e senza fallback a un altro modello. Il
percorso integrale conserva il retry gia previsto per citazioni letterali non
valide; la selezione `--only-ids` non ripete la generazione dopo un esito di
validazione. I retry tecnici restano disponibili con `--retry-errors`, solo
dopo un'azione esplicita. Il risultato `run.json` conserva `source_run_id`, gli hash di
snapshot/dataset, il modello e la versione/hash del prompt. I chunk e il loro
numero effettivo per domanda provengono dal baseline; `retrieval_seconds` resta
mancante e `generation_seconds` misura solo la generazione sperimentale. Report
e scheda umana sono separati dai risultati storici.

Per un confronto scientifico:

1. Verificare che gli hash di snapshot e dataset, le domande e l'ordine coincidano;
   confermare `top_k`, modello Gemini e numero effettivo di chunk per domanda.
   Gli stessi chunk sono riusati, non solo lo stesso K.
2. Confrontare le risposte in coppia per domanda. Per la completezza, usare la
   stessa rubrica e lo stesso valutatore/modello-giudice su entrambe le versioni,
   con ordine e identita A/B mascherati. Tenere separati i risultati del nuovo
   giudizio dalle valutazioni storiche.
3. Riportare la differenza per coppia e la numerosita effettiva; per la scala
   ordinale 0-4 riportare distribuzione e mediana delle differenze, con intervallo
   di confidenza bootstrap appaiato o test di Wilcoxon. Le ripetizioni dello
   stesso quesito non sono nuove domande indipendenti.
4. Verificare insieme fedelta, accuratezza, correttezza delle citazioni,
   risposte non rispondibili, astensioni, errori di validazione e tasso di
   risposte valutabili. Non concludere da una crescita della completezza se
   peggiorano supporto, citazioni o gestione delle lacune.

I punteggi originali non vanno sostituiti ne' combinati con i nuovi. Per evitare
un confronto tra giudizi prodotti in momenti o condizioni diverse, applicare la
stessa rubrica e lo stesso modello-giudice separatamente a entrambe le run, in
file di output nuovi, e confrontare solo gli `item_id` valutati in entrambe.
La run sperimentale genera una scheda umana vuota; nessun punteggio o valutazione
e prodotto automaticamente.

Test offline:

```bash
python -m pytest -q tests/test_prompt_experiment.py
```

## 11. Report offline sulle run Ground Truth 150

Per aggregare le tre run originali, i giudizi Groq già collegati tramite hash
e gli esperimenti di recupero senza nuove chiamate esterne:

```bash
python -m edicola.final_report
```

Il comando verifica ID, hash, validità dei giudizi e identità dei chunk riusati,
poi crea una nuova cartella `evaluation/results/report_finale_gt150`. Rifiuta
di sovrascrivere una destinazione esistente. I recuperi sono analizzati
separatamente e le domande sovrapposte non vengono sommate. I test sintetici
sono offline:

```bash
python -m pytest -q tests/test_final_report.py
```

## 12. Esperimento retrieval GT150 (separato dalla produzione)

L'analisi delle run originali è riproducibile offline e non chiama API:

```bash
python -m edicola.retrieval.experimental analyze
```

Il report `evaluation/results/retrieval_experiment_gt150/analisi_offline.md`
elenca i chunk N con posizione, PDF/pagina, estratto e motivazione Groq; i
giudizi sono controllati rispetto agli hash delle tre run. Sono AI-silver, non
etichette umane esaustive. La causa apparente del terzo gruppo va interpretata
con cautela: le categorie e i giudizi cambiano fra coorti; inoltre i risultati
storici su GT-051..GT-150 sono già noti, quindi non sono un holdout cieco.

Il modulo `edicola.retrieval.experimental` non cambia `semantic_search`
dell'app. Esegue solo retrieval e mantiene sempre K=3. Le strategie sono:

- `production_baseline`: percorso esistente di ricerca, per controllo appaiato;
- `cosine_all`: cosine puro su tutti i chunk correnti;
- `hybrid_rrf`: pool di 50 candidati semantici e 50 lessicali BM25, fusi con
  Reciprocal Rank Fusion;
- `hybrid_rrf_dedup`: stessa fusione, saltando quasi-duplicati soltanto
  all'interno della stessa edizione. Chunk da PDF diversi restano distinti.
- `cross_encoder_rerank`: prende i primi 10 risultati di `semantic_search`
  corpus-wide e li riordina localmente con il CrossEncoder multilingue
  `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`, poi restituisce al massimo 3
  chunk. La ricerca di produzione resta invariata; il modello ONNX viene letto
  esclusivamente da una directory locale e non viene scaricato dal programma.
  La strategia e' fissata a 10 candidati e K=3.

Sviluppo: confrontare strategie esclusivamente su GT-001..GT-050; ogni run
deve ricevere nuovi giudizi Groq. Non riutilizzare quelli storici perché il
ranking, i candidati o persino gli embedding possono essere diversi:

```bash
python -m pip install -r requirements-reranker.txt

hf download cross-encoder/mmarco-mMiniLMv2-L12-H384-v1 \
  --revision 1427fd652930e4ba29e8149678df786c240d8825 \
  --local-dir "$HOME/.cache/edicola/models/mmarco-mMiniLMv2-L12-H384-v1" \
  --include tokenizer.json onnx/model.onnx

python -m edicola.retrieval.experimental run \
  --snapshot evaluation/work/snapshot.json \
  --ground-truth-csv evaluation/data/Ground_Truth_Edicola_150_domande.csv \
  --split development --strategy production_baseline \
  --out evaluation/results/retrieval_experiment_gt150/dev_baseline \
  --authorize-external

python -m edicola.retrieval.experimental run \
  --snapshot evaluation/work/snapshot.json \
  --ground-truth-csv evaluation/data/Ground_Truth_Edicola_150_domande.csv \
  --split development --strategy cross_encoder_rerank \
  --out evaluation/results/retrieval_experiment_gt150/dev_cross_encoder \
  --authorize-external

python -m edicola.retrieval.experimental run \
  --snapshot evaluation/work/snapshot.json \
  --ground-truth-csv evaluation/data/Ground_Truth_Edicola_150_domande.csv \
  --split development --strategy hybrid_rrf \
  --out evaluation/results/retrieval_experiment_gt150/dev_hybrid_rrf \
  --authorize-external

python -m edicola.retrieval.experimental run \
  --snapshot evaluation/work/snapshot.json \
  --ground-truth-csv evaluation/data/Ground_Truth_Edicola_150_domande.csv \
  --split development --strategy hybrid_rrf_dedup \
  --out evaluation/results/retrieval_experiment_gt150/dev_hybrid_rrf_dedup \
  --authorize-external

python evaluation/llm_relevance_judge.py \
  --run evaluation/results/retrieval_experiment_gt150/dev_hybrid_rrf/run.json \
  --dataset evaluation/results/retrieval_experiment_gt150/dev_hybrid_rrf/dataset.json \
  --snapshot evaluation/work/snapshot.json --limit 50 \
  --out evaluation/results/retrieval_experiment_gt150/dev_hybrid_rrf/judgments.json \
  --autorizza-api

python evaluation/llm_relevance_judge.py \
  --run evaluation/results/retrieval_experiment_gt150/dev_baseline/run.json \
  --dataset evaluation/results/retrieval_experiment_gt150/dev_baseline/dataset.json \
  --snapshot evaluation/work/snapshot.json --limit 50 \
  --out evaluation/results/retrieval_experiment_gt150/dev_baseline/judgments.json \
  --autorizza-api

python evaluation/llm_relevance_judge.py \
  --run evaluation/results/retrieval_experiment_gt150/dev_cross_encoder/run.json \
  --dataset evaluation/results/retrieval_experiment_gt150/dev_cross_encoder/dataset.json \
  --snapshot evaluation/work/snapshot.json --limit 50 \
  --out evaluation/results/retrieval_experiment_gt150/dev_cross_encoder/judgments.json \
  --autorizza-api

python -m edicola.retrieval.experimental compare \
  --snapshot evaluation/work/snapshot.json \
  --dataset evaluation/results/retrieval_experiment_gt150/dev_baseline/dataset.json \
  --baseline-run evaluation/results/retrieval_experiment_gt150/dev_baseline/run.json \
  --baseline-judgments evaluation/results/retrieval_experiment_gt150/dev_baseline/judgments.json \
  --reranked-run evaluation/results/retrieval_experiment_gt150/dev_cross_encoder/run.json \
  --reranked-judgments evaluation/results/retrieval_experiment_gt150/dev_cross_encoder/judgments.json \
  --split development \
  --out evaluation/results/retrieval_experiment_gt150/dev_comparison.json

python evaluation/llm_relevance_judge.py \
  --run evaluation/results/retrieval_experiment_gt150/dev_hybrid_rrf_dedup/run.json \
  --dataset evaluation/results/retrieval_experiment_gt150/dev_hybrid_rrf_dedup/dataset.json \
  --snapshot evaluation/work/snapshot.json --limit 50 \
  --out evaluation/results/retrieval_experiment_gt150/dev_hybrid_rrf_dedup/judgments.json \
  --autorizza-api
```

Dopo aver congelato una strategia e i suoi parametri, valutare GT-051..GT-150
una sola volta. Per confronto complessivo autorizzato su tutti i 150 quesiti,
usare la strategia congelata e produrre run nuove e separate con `--split all`
sia per la baseline sia per il reranker. I risultati storici su tutti
gli ID sono già stati consultati: il sottoinsieme GT-051..GT-150 resta separato
dallo sviluppo, ma non è un holdout cieco. I nuovi risultati Groq sono giudicati
in due blocchi senza sovrascrivere le run o i giudizi originali:

```bash
python -m edicola.retrieval.experimental run \
  --snapshot evaluation/work/snapshot.json \
  --ground-truth-csv evaluation/data/Ground_Truth_Edicola_150_domande.csv \
  --split all --strategy production_baseline \
  --out evaluation/results/retrieval_experiment_gt150/final_baseline \
  --authorize-external

python evaluation/llm_relevance_judge.py \
  --run evaluation/results/retrieval_experiment_gt150/final_baseline/run.json \
  --dataset evaluation/results/retrieval_experiment_gt150/final_baseline/dataset.json \
  --snapshot evaluation/work/snapshot.json --start 0 --limit 100 \
  --out evaluation/results/retrieval_experiment_gt150/final_baseline/judgments.json \
  --autorizza-api

python evaluation/llm_relevance_judge.py \
  --run evaluation/results/retrieval_experiment_gt150/final_baseline/run.json \
  --dataset evaluation/results/retrieval_experiment_gt150/final_baseline/dataset.json \
  --snapshot evaluation/work/snapshot.json --start 100 --limit 100 \
  --solo-mancanti \
  --out evaluation/results/retrieval_experiment_gt150/final_baseline/judgments.json \
  --autorizza-api

python -m edicola.retrieval.experimental run \
  --snapshot evaluation/work/snapshot.json \
  --ground-truth-csv evaluation/data/Ground_Truth_Edicola_150_domande.csv \
  --split all --strategy cross_encoder_rerank \
  --reranker-model "$HOME/.cache/edicola/models/mmarco-mMiniLMv2-L12-H384-v1" \
  --out evaluation/results/retrieval_experiment_gt150/final_cross_encoder \
  --authorize-external

python evaluation/llm_relevance_judge.py \
  --run evaluation/results/retrieval_experiment_gt150/final_cross_encoder/run.json \
  --dataset evaluation/results/retrieval_experiment_gt150/final_cross_encoder/dataset.json \
  --snapshot evaluation/work/snapshot.json --start 0 --limit 100 \
  --out evaluation/results/retrieval_experiment_gt150/final_cross_encoder/judgments.json \
  --autorizza-api

python evaluation/llm_relevance_judge.py \
  --run evaluation/results/retrieval_experiment_gt150/final_cross_encoder/run.json \
  --dataset evaluation/results/retrieval_experiment_gt150/final_cross_encoder/dataset.json \
  --snapshot evaluation/work/snapshot.json --start 100 --limit 100 \
  --solo-mancanti \
  --out evaluation/results/retrieval_experiment_gt150/final_cross_encoder/judgments.json \
  --autorizza-api

python -m edicola.retrieval.experimental compare \
  --snapshot evaluation/work/snapshot.json \
  --dataset evaluation/results/retrieval_experiment_gt150/final_baseline/dataset.json \
  --baseline-run evaluation/results/retrieval_experiment_gt150/final_baseline/run.json \
  --baseline-judgments evaluation/results/retrieval_experiment_gt150/final_baseline/judgments.json \
  --reranked-run evaluation/results/retrieval_experiment_gt150/final_cross_encoder/run.json \
  --reranked-judgments evaluation/results/retrieval_experiment_gt150/final_cross_encoder/judgments.json \
  --split all \
  --out evaluation/results/retrieval_experiment_gt150/final_comparison.json
```

Ogni invio a Gemini/Groq resta subordinato alla relativa autorizzazione
esplicita. Il download del modello e' un passaggio separato; l'esperimento
richiede il modello gia' presente in locale e usa ONNX Runtime su CPU, senza
scaricare pesi. La run di retrieval non invia fonti per generare risposte, non usa
modelli per PDF e non modifica corpus, indice, run originali, Ground Truth o
giudizi precedenti. Il dataset accanto alla run è un adattamento tecnico delle
sole domande CSV: non contiene etichette di rilevanza; i nuovi giudizi vengono
salvati in file distinti sia per baseline sia per reranker. Il confronto verifica
gli hash di dataset, snapshot, run e giudizi prima di calcolare Precision@3 e
MRR@3; espone separatamente sviluppo e holdout. Il reranking non garantisce un
miglioramento: solo i nuovi giudizi Groq potranno misurare l'effetto sul corpus.
I test sintetici non attestano un aumento reale:

```bash
python -m pytest -q tests/test_retrieval_experiment.py
```
