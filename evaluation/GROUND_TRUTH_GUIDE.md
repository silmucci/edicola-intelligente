# Valutazione con Ground Truth — Edicola Digitale Intelligente

Questo modulo è **separato dall'interfaccia Streamlit**. Non modifica l'archivio,
il codice dei generatori, i PDF, gli embedding o i dati personali.
Non contiene Ground Truth precompilata: la inserirai tu dopo aver letto gli
articoli originali. Gli esempi nei test Python sono **sintetici**, non risultati
di qualità dell'applicazione.

## 1. Che cosa valuterai

| Dimensione | Metodo | Richiede Ground Truth? |
|---|---|---|
| Precision@K | Recupero dei chunk pertinenti nei primi K | Sì, annotazioni di rilevanza |
| Recall@K | Quota dei chunk pertinenti recuperati | Sì, annotazioni esaustive |
| MRR@K | Posizione del primo risultato pertinente | Sì, o giudizi sufficienti per determinare il rango |
| Copertura dei PDF | Conteggio dei documenti diversi recuperati | No, ma misura diversità, non pertinenza |
| Tempi, errori API, tentativi | Misure dell'esecuzione reale | No |
| Gestione delle domande senza risposta | Confronto con etichetta umana di rispondibilità | Sì |
| Faithfulness, completezza, pertinenza, qualità delle citazioni | LLM-as-a-Judge facoltativo | Sì, punti attesi compilati |
| Correttezza, fedeltà, qualità Podcast e altri editoriali | Schede umane 0–4 | Sì, verifica delle fonti e ascolto del WAV |

Il giudice AI **non costruisce e non cambia** la Ground Truth; valuta un
risultato già generato e validato, confrontandolo con i punti attesi. I suoi
voti sono tenuti separati da quelli dei valutatori umani. Una citazione
letterale verificata dal programma non garantisce che la notizia sia vera
o che la risposta ne rappresenti correttamente il significato.

## 2. Preparare il dataset (nessuna chiamata API)

Dalla radice del repository, con Python attivo:

```bash
python -m edicola.evaluation snapshot --out evaluation/work/snapshot.json
python -m edicola.evaluation init --snapshot evaluation/work/snapshot.json --out evaluation/work/annotations
```

Il secondo comando crea, fra gli altri, `dataset.json`: questo è il file della
tua **Ground Truth**. Contiene una domanda vuota `q01` da duplicare.

Compila in ogni oggetto:

- `id`: ad esempio `q01`, `q02`, ...;
- `question`: domanda con cui testerai la ricerca;
- `annotator`: pseudonimo di chi ha annotato;
- `answerability`: `answerable`, `unanswerable` oppure `null` finché non giudicata;
- `relevant_chunks`: ID, PDF e pagina copiati da `annotation-catalog.json`;
- `nonrelevant_chunk_ids`: chunk letti e giudicati non pertinenti;
- `judgments_complete`: `true` **solo dopo** aver esaminato tutti i chunk dello snapshot;
- `expected_points`: fatti che una risposta corretta dovrebbe riportare, scritti da te;
- `reference_answer`: risposta di riferimento facoltativa, scritta da te;
- `annotation_notes`: motivi, ambiguità, eventuali limiti.

Non inserire ID di fantasia: gli identificativi devono corrispondere ai
chunk realmente presenti nello snapshot e al PDF/pagina indicato. Nessun
campo di verità viene compilato automaticamente.

```bash
python -m edicola.evaluation validate --snapshot evaluation/work/snapshot.json --dataset evaluation/work/annotations/dataset.json
```

Con Ground Truth incompleta il software emette avvisi e lascia alcune
metriche **mancanti**; non converte le etichette mancanti in errori o zeri.
Per il Recall@K la rilevanza deve essere completamente annotata, in
coerenza con il perimetro di documenti realmente indicizzati.

## 3. Eseguire retrieval e RAG (con chiamate esplicite a Gemini)

```bash
python -m edicola.evaluation benchmark --snapshot evaluation/work/snapshot.json --dataset evaluation/work/annotations/dataset.json --mode retrieval --k 3 --limit 5 --authorize-external --out evaluation/results/retrieval-01

python -m edicola.evaluation benchmark --snapshot evaluation/work/snapshot.json --dataset evaluation/work/annotations/dataset.json --mode rag --k 3 --limit 5 --authorize-external --out evaluation/results/rag-01
```

`--limit` è obbligatorio: limita il numero di domande da inviare a Gemini.
La run crea `run.json`, `report.md`, `metrics.csv`, `summary.csv` e i
grafici. I risultati riportano la versione del codice, i parametri e
il collegamento esatto allo snapshot/dataset. Non sono benchmark
dell'interfaccia Streamlit o del processo di caricamento dei PDF.

## 4. Giudice LLM facoltativo, quando avrai la Ground Truth

Usa una run RAG esistente e un modello **abilitato nel tuo progetto Gemini**:

```bash
python -m edicola.evaluation judge --snapshot evaluation/work/snapshot.json --dataset evaluation/work/annotations/dataset.json --run evaluation/results/rag-01/run.json --model gemini-3.5-flash-lite --limit 5 --authorize-external --out evaluation/results/judge-01
```

Il nome del modello è un **esempio di configurazione**, non una garanzia
di quota gratuita: verifica disponibilità e limiti in Google AI Studio.
Nessun fallback non richiesto, nessun modello a pagamento attivato,
nessun retry automatico del giudice e nessuna chiave duplicata.

Il giudice riceve la domanda, la risposta RAG verificata, i passaggi
recuperati e la Ground Truth manuale; non riceve altre edizioni e
non può aggiungere informazioni esterne. Assegna 0–4 (oppure NA) a
`faithfulness`, `completeness`, `answer_relevance` e
`citation_correctness`, motivando il voto. Per faithfulness e citazioni
deve anche indicare una prova letterale presente nei passaggi.
Citazioni inventate, strutture errate e risultati interrotti vengono
scartati: **non vengono trattati come punteggio zero**.

Quando `expected_points` è vuoto, la domanda non è etichettata
`answerable`, oppure il RAG non ha fornito una risposta validata,
il giudice NON viene invocato: il risultato viene segnato come
`missing_ground_truth`, `not_validated_answer` o altro stato
esplicito. Nessuna qualità viene inventata.

Output: `judge.json` con esiti e singoli voti, più il consueto report
con le metriche `llm_judge:rag:*`. I voti sono **giudizi di modello**,
non Ground Truth, e vanno verificati con un campione umano.

### Ricalcolo completamente offline

```bash
python -m edicola.evaluation score --snapshot evaluation/work/snapshot.json --dataset evaluation/work/annotations/dataset.json --run evaluation/results/rag-01/run.json --judge-results evaluation/results/judge-01/judge.json --out evaluation/results/rag-01-giudicato
```

Non occorrono nuove API; la provenienza dei giudizi viene controllata
con gli hash di run, snapshot e dataset. Se cambi la Ground Truth,
crea una nuova run coerente invece di riutilizzare o rietichettare
punteggi riferiti a un dataset diverso.

## 5. Briefing, Podcast, Timeline e Mappe

Le schede `prepare-review` già esistenti permettono la revisione umana
dei prodotti editoriali salvati. Esempio:

```bash
python -m edicola.evaluation prepare-review --kind briefing --item-id CHIAVE_REALE --origin real --out evaluation/work/review-briefing
```

Non genera prodotti nuovi e non modifica le cache. Per il Podcast
valuta separatamente accuratezza del copione e qualità del WAV.
Non applicare automaticamente i voti RAG ai prodotti editoriali:
hanno struttura e obiettivi diversi.

## 6. Indicazioni metodologiche per la tesi

Definisci prima categorie di domande (fattuali, multi-edizione,
temporali, senza risposta), criteri e numero di campioni. Evita di
costruire la Ground Truth dalle risposte del sistema che stai misurando.
Conserva una parte di test finale distinta dai casi usati per
ottimizzare i prompt. Se possibile, richiedi un secondo annotatore
e documenta come vengono risolti i disaccordi.

Confronta i modelli a parità di snapshot, Ground Truth e configurazione.
Distingui sempre **metriche deterministiche**, **LLM-as-a-Judge** e
**valutazioni umane**. Usa i risultati simulati soltanto per dimostrare
il corretto funzionamento del codice di valutazione.
