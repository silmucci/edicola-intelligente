# Valutazione delle prestazioni e della scalabilità — tesi magistrale

Benchmark **backend** separato dall'applicazione Streamlit e dagli esperimenti di
qualità su 50 domande. Non modifica la pipeline RAG né i vettori Chroma. Utilizza
le funzioni reali di Chat, Briefing, Timeline e Mappe; il Podcast (TTS) è
**escluso per default** e richiede un flag dedicato.

## 1. Esecuzione in GitHub Codespaces

Dal terminale nella radice del repository:

```bash
python -m pytest -q tests/test_performance_benchmark.py
python evaluation/performance/benchmark.py --preview
python evaluation/performance/benchmark.py --check
```

- `--preview` produce un piano deterministico con classi, intensità, prompt e
  istanti programmati. **Non richiede PDF, indice, chiavi o connessione.**
- `--check` verifica **localmente** la presenza dell'archivio, dei PDF, dei
  vettori Chroma e della configurazione della chiave; **non invia API**.
- I PDF, `data/archive.sqlite3` e `data/chroma/` **non sono salvati su GitHub**.
  Un Codespace nuovo non li contiene. Usare il corpus locale legittimamente
  disponibile o ripristinare uno snapshot autorizzato prima del benchmark,
  senza fare commit di quotidiani, database, estrazioni o chiavi.
- La chiave `GEMINI_API_KEY` va configurata come secret/variabile d'ambiente
  o nel `.env` non versionato. Il benchmark non la stampa.

Se `--check` segnala dati mancanti, **fermarsi**: non ha senso eseguire una
prova di carico senza lo stesso archivio indicizzato utilizzato nella tesi.

## 2. Primo test reale limitato

Eseguire solo con consenso esplicito all'invio delle domande e dei passaggi
indicizzati alle API del progetto. Sono possibili consumi/quota anche in caso
di errore; i modelli di fallback configurati nell'app restano possibili.

```bash
python evaluation/performance/benchmark.py --run --authorize-external \
  --mix chat:1 --rates 1 --phase-seconds 60 --max-requests 1 \
  --max-api-attempts 4 --max-in-flight 1
```

Questo comando avvia al massimo **una richiesta di classe Chat**, con un tetto
complessivo di **quattro invocazioni SDK** incluse eventuali ripetizioni.
La prima verifica serve a controllare permessi, indice, output e condizioni API.

## 3. Flusso misto crescente (esperimento esplorativo)

```bash
python evaluation/performance/benchmark.py --preview \
  --rates 1,2,3 --phase-seconds 60 --max-requests 6

python evaluation/performance/benchmark.py --run --authorize-external \
  --rates 1,2,3 --phase-seconds 60 --max-requests 6 \
  --max-api-attempts 24 --max-in-flight 2 \
  --mix chat:2,briefing:1,timeline:1,map:1
```

Tre finestre da 60 secondi, rispettivamente 1, 2, 3 richieste/minuto;
fino a 2 richieste elaborate contemporaneamente. La frequenza è
**programmata in anticipo** e non dipende dall'istante in cui termina la
richiesta precedente. Se ci sono richieste lente, possono accumularsi.
Il mix configura pesi relativi, non quote esatte con campioni così piccoli.

È una prova **pilota**: sei richieste non sono sufficienti per sostenere
stime stabili di P95 o per dimostrare un limite massimo di scalabilità.
Si possono replicare esperimenti con numeri maggiori solo dopo aver
verificato costi, quote e stabilità. In ogni sessione restano i limiti
1–30 richieste, 1–3 concorrenti, 1–6 richieste/minuto per fase e 1–100
invocazioni SDK.

### Podcast (opzionale)

La sintesi vocale comporta chiamate TTS aggiuntive, anche per più segmenti.
Includerla **soltanto con quota adeguata e autorizzazione esplicita**:

```bash
python evaluation/performance/benchmark.py --preview --include-podcast \
  --mix chat:2,briefing:1,timeline:1,map:1,podcast:1
```

Per una prova reale, sostituire `--preview` con `--run --authorize-external`
e impostare consapevolmente `--max-requests` e `--max-api-attempts`.
La pipeline audio può richiedere più tempo della finestra di 60 secondi:
questo non significa automaticamente errore.

## 4. Risultati

Ogni esecuzione reale crea una nuova cartella ignorata da Git:

```text
evaluation/results/performance-AAAAmmgg-HHMMSS/
    requests.csv
    summary.json
    api_attempts.json
```

- `requests.csv`: classe, fase, arrivo programmato, attesa in coda,
  latenza completa backend, tempo di processamento, esito, cache hit,
  invocazioni di embedding/generazione/TTS e HTTP 429.
- `summary.json`: statistiche globali, per classe e per fase,
  tempi medio/P50/P95 e percentuale di successo.
- `api_attempts.json`: tentativi SDK osservati **inclusi retry e fallback**,
  operazione, modello, tempo, codice HTTP se disponibile; nessuna chiave
  o payload di giornali.

La latenza `end_to_end_s` include il ritardo tra arrivo programmato
e completamento del backend, dunque anche un'eventuale coda interna al test.
`processing_s` esclude l'attesa di schedulazione. Il throughput osservato
di una fase conta i completamenti realmente avvenuti in quella finestra;
una richiesta avviata nella fase precedente può terminarvi.

**Distinguere sempre:**
- risultati serviti dalla cache (`cache_hit=true`) e generazioni nuove;
- chiamate finite senza errori e risposte effettivamente informative;
- errori di quota API (429), di rete e di applicazione;
- tasso di arrivo programmato e throughput effettivamente completato.

Non svuotare automaticamente le cache: il test fotografa il comportamento
del backend nello stato corrente. Poiché il Briefing può essere riusato dalla
cache e le altre funzioni hanno strategie diverse, confrontare solo
osservazioni con condizioni dichiarate. Ripetere su un corpus/snapshot
stabile. Un confronto rigoroso richiede anche un esperimento separato a
cache controllata e un numero adeguato di repliche.

## 5. Limiti metodologici da dichiarare

Questi test invocano le stesse **funzioni backend**, ma non simulano
sessioni browser, WebSocket Streamlit, login o rendering. Misurano
l'applicazione eseguita nel **Codespace**, non le risorse della piattaforma
Streamlit Cloud. La scalabilità misurata dipende anche da
hardware del Codespace, rete, quota e prestazioni dei servizi Gemini.
Non rappresentarla come capacità certificata del deployment pubblico.

Conservare per ogni esperimento data, commit Git, modelli configurati,
dimensione del corpus, parametri del test, condizioni di cache e
limiti di quota. Non inferire da sei richieste né un numero massimo
di utenti servibili né una disponibilità garantita.

## 6. Integrazione in tesi

Nel capitolo *Risultati sperimentali*, aggiungere:
1. Ambiente di prova e perimetro backend.
2. Classi di richieste e definizione del mix.
3. Profilo crescente del tasso di arrivo.
4. Latenza P50/P95, throughput e successo per classe/fase.
5. Analisi di cache, retry, errori di quota e limiti di validità esterna.

La valutazione di correttezza del RAG (Precision, MRR, giudizio LLM)
resta una parte sperimentale **indipendente** da questi tempi e carichi.
