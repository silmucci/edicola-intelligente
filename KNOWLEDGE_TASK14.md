# Timeline e mappe — Task 14

Aggiornamento: il [Task 14.1](KNOWLEDGE_TASK14_1.md) sostituisce il fallback a
solo elenco con un raggruppamento visuale senza archi e aggiorna le versioni
delle strategie a `concept-map-v4` e `timeline-developments-v3`.

## Intervento e cause individuate nel codice

Il vecchio rendering mostrava avvisi separati per copertura, date assenti e
validazione vuota; il titolo ripeteva l'intera domanda. Lo stato dell'evento veniva
calcolato dalla sola `date_evidence`: quando mancava, anche proposte e annunci
documentati rimanevano indistinti. Il prompt della timeline enfatizzava il calendario
e poteva tagliare il testo dei chunk per rientrare nel budget. Non è stata eseguita
una nuova chiamata reale per ricostruire la risposta Gemini dell'esempio dell'utente.

Ora il prompt chiede anche proposte, decisioni, richieste e programmi pertinenti,
con citazioni focalizzate. Il validatore conserva le prove letterali e ricava uno
stato conservativo da esse, anche senza una data. Proposte e annunci vengono
presentati attraverso il testo originale, evitando una parafrasi che li descriva
come fatti compiuti. Negazioni e segnali discordanti restano indeterminati.
Questo controllo locale non è una verifica semantica completa delle parafrasi.

## Retrieval, budget e prove

- Stessa `semantic_search`, singola ricerca autorizzata con diversificazione per
  PDF e `KNOWLEDGE_CHUNKS` invariato (default 5, massimo 5). Nessuna riscrittura
  remota della domanda, nuova indicizzazione o embedding dei documenti.
- La timeline ora invia soltanto chunk interi. Un campione è costruito nell'ordine
  recuperato entro `KNOWLEDGE_MAX_PROMPT_CHARS` (default 12000). I passaggi troppo
  grandi vengono saltati, conservando gli altri: niente prefissi troncati, nessun
  aumento automatico di budget o limiti di output.
- Per le mappe restano al massimo due vicini per default (`MAP_ADJACENT_CHUNKS`,
  precedente intervallo 0–4). La scelta privilegia i termini del tema senza nuove
  query; la chiave distingue hash, configurazione, nome file, pagina e posizione.
- Sono richiesti continuità di offset, ordine e overlap esatto. Un identificativo
  articolo, quando presente, deve coincidere. Ogni relazione documentata richiede
  una proposizione letterale verificabile; citazioni su due chunk devono coprire
  il confine senza testo omesso. Temi comuni richiedono prove per entrambi i nodi:
  la co-occorrenza non basta. Queste regole linguistiche non vengono allentate.
- I PDF a colonne non sono segmentati automaticamente in articoli. La sola
  vicinanza non prova che i passaggi appartengano allo stesso articolo: restano
  esclusi collegamenti che le prove non consentono di verificare. Non si recuperano
  vicini non indicizzati o informazioni esterne per completare il risultato.

## Presentazione e fonti

La **Cronologia documentata** contiene esclusivamente date evento validate, in
ordine cronologico. Data del quotidiano, anno contestuale e data evento restano
separati; le regole di calendario, giorno settimanale e cambio d'anno sono invariate.
Un evento datato non è automaticamente avvenuto: gli annunci mantengono il loro stato.

Gli elementi senza data appaiono in **Eventi e sviluppi documentati**, in ordine
di lettura dei passaggi recuperati, dichiaratamente non cronologico. Se la richiesta
è esplicitamente cronologica, un messaggio spiega il limite. Se non rimane alcun
elemento validato, compare un solo stato vuoto, comprendente l'eventuale copertura
parziale. La pubblicazione non viene mai sostituita alla data dell'evento.

Card verticali con nodi e categorie, titoli abbreviati solo nella visualizzazione,
descrizioni sintetiche e dettagli originali nel popover. CSS limitato alle classi
del componente, token Task 13, testo HTML escapato. Layout verticale anche su
smartphone, senza imporre una larghezza di grafico alla pagina.

Per le mappe resta **Graphviz**, senza dipendenze nuove. Massimo dieci nodi nella
vista, etichette brevi e tooltip completi, colori per persone/organizzazioni/luoghi/
eventi/misure/proposte/concetti. Il nodo evidenziato è scelto per numero di archi
verificati, con pertinenza lessicale al tema come spareggio: non è un concetto
aggiunto artificialmente o una causalità dedotta. Frecce per relazioni documentate,
tratteggio senza direzione per associazioni tematiche. Il selettore **Grafo/Elenco**
permette di leggere gli elementi su piccoli schermi; senza archi rimane solo l'elenco.
Controlli e zoom dipendono dal renderer nativo Streamlit: non sono simulati.

Ogni evento e relazione ha riferimenti compatti riutilizzati dalla Chat AI, con
apertura del PDF alla pagina verificata. I metadati editoriali curati sostituiscono
i nomi tecnici; gli estratti originali rimangono consultabili. Tutti i concetti e
le relative fonti, anche oltre i dieci nodi del grafo, sono nei dettagli. Nomi
tecnici e diagnostica di scarto restano nella modalità diagnostica configurata.

## Cache e isolamento delle funzionalità

La cache rimane JSON in `data/knowledge_cache/`. La timeline aggiunge la strategia
`timeline-developments-v2`, separata dalla versione delle regole di data. La mappa
passa a `concept-map-v3`. Le vecchie voci rimangono su disco, ma le chiavi obsolete
non vengono riutilizzate. Nessun database viene migrato, ripulito o modificato.

Timeline e Mappa conservano risultati separati nella sessione. Cambiare prodotto,
Grafo/Elenco, aprire fonti o consultare un risultato esistente non genera Gemini.
Modificare l'argomento non rigenera il risultato: un avviso identifica quello
precedente. Ogni nuova richiesta resta soggetta al consenso testuale e all'invio.
Modello configurato, OIDC, Supabase, chatbot e altri prodotti restano invariati.

## Prova locale

```powershell
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.venv\Scripts\python.exe -m streamlit run app.py
```

1. In **Timeline e Mappe**, scegliere Timeline e inserire il tema delle misure
   per le imprese di pesca contro il caro carburante. Avviare e autorizzare
   esplicitamente: verificare gli sviluppi senza data se le fonti li sostengono.
2. Provare «Ricostruzione cronologica delle misure per la pesca»: gli elementi
   senza data devono restare separati, con il criterio e il limite spiegati.
3. Provare un evento con date effettivamente presenti nei PDF: controllare
   calendario, stato avvenuto/annunciato e pubblicazione nei dettagli.
4. Passare a Mappa e generare esplicitamente. Verificare legenda, nodo evidenziato,
   prove dei collegamenti, lista alternativa e fallback quando non vi sono archi.
5. Aprire le fonti sotto un evento e sotto una relazione; controllare il PDF e la
   pagina, inclusi i due riferimenti di una prova su chunk adiacenti.
6. Cambiare vista/prodotto e tornare: nessuna nuova chiamata. Ripetere una richiesta
   identica per verificare il risultato dalla cache. Cambi di tema/configurazione/
   archivio possono richiedere una nuova generazione esplicita.
7. Controllare a 1440, 1024, 768, 430 e 360 px: timeline leggibile, grafico contenuto,
   alternativa Elenco e fonti raggiungibili da touch e tastiera.

Le prove automatiche usano solo API e corpus sintetici. Non sono state effettuate
chiamate Gemini reali, screenshot reali a diverse risoluzioni o verifiche sul corpus
editoriale completo. Una data o relazione assente dalle prove non viene inventata:
la qualità e copertura del risultato dipendono dai passaggi effettivamente indicizzati.

Esito finale della suite completa: **618 test superati, nessun fallimento**,
89 avvisi di deprecazione delle librerie esistenti. Inclusi date complete e
incomplete, proposte/annunci, stati vuoti, prove contigue, categorie dei nodi,
relazioni non supportate, navigazione PDF, budget senza troncamenti, versioni
delle cache, cambio prodotto senza API e regressioni delle altre funzionalità.

## File

Nuovi: `edicola/knowledge_presentation.py`, `edicola/knowledge_components.py`,
`edicola/knowledge_views.py`, `tests/test_knowledge_exploration.py`, questa guida.
Modificati: `edicola/knowledge.py`, `knowledge_ui.py`, `knowledge_validation.py`,
`map_context.py`, `map_relations.py`, `reading_ui.py`; `tests/test_app.py`,
`test_concept_map.py`, `test_pdf_viewer.py`; `README.md`, `AGENTS.md`.
I nomi senza cartella seguono il prefisso del rispettivo gruppo.
