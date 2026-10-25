# Mappe pertinenti e compatte — Task 14.3

## Cause identificate nel codice

1. `compact_map` conservava soltanto gli estremi degli archi appena ne esisteva
   uno valido. Un collegamento fuori tema poteva quindi nascondere tutti i
   concetti isolati utili alla domanda. Anche il nodo evidenziato privilegiava
   il numero di collegamenti.
2. La selezione forzava la diversificazione fra PDF. `semantic_search` produceva
   risultati validi come vettori, ma mancava un filtro distinto di pertinenza per
   destinatari/tema. Il numero limitato di fonti e la rotazione fra edizioni
   potevano lasciare spazio a un problema genericamente simile, in un altro settore.
3. Il prompt chiedeva di privilegiare piccoli gruppi collegati rispetto a
   concetti isolati. La verifica letterale delle citazioni e dei predicati non
   risolve da sola la pertinenza alla domanda.
4. Graphviz era renderizzato con `width="stretch"` e un'altezza fissa di 300/380
   pixel. Questa impostazione adattava anche grafi minuscoli al grande contenitore;
   ridurre le dimensioni nominali nel DOT non risolveva l'ingrandimento iniziale.

Non sono state trovate cache locali della mappa sul carburante. Non è possibile
ricostruire i singoli risultati semantici o candidati della risposta reale senza
una nuova richiesta, che non è stata eseguita. Il problema di eliminazione degli
isolati è invece direttamente riproducibile nel codice con dati simulati.

## Selezione e pertinenza

`knowledge_relevance.py` è un modulo locale, senza servizi o dipendenze nuovi.
Riconosce destinatari e luoghi espliciti nelle formulazioni supportate della
domanda. Normalizza flessioni semplici e un piccolo vocabolario esplicito di
termini equivalenti di più settori (non soltanto pesca). Il vocabolario serve
solo alla selezione, mai a rendere letterale una citazione o a inventare relazioni.

Per le mappe rimane una sola chiamata a `semantic_search`, senza rotazione
obbligatoria fra PDF. I suoi risultati vengono confrontati localmente con i chunk
già presenti nel catalogo indicizzato. Il ranking pesa i termini secondo la
frequenza nel catalogo e usa l'ordine semantico come spareggio. Un passaggio utile
omesso dal primo campione può così rientrare senza un'altra embedding della
domanda. Con richieste prive di termini discriminanti non si espande alla cieca
sull'intero catalogo. I duplicati testuali esatti sono esclusi dal campione.

Restano al massimo cinque passaggi principali (`KNOWLEDGE_CHUNKS`) e i vicini
configurati, con chunk interi entro il budget esistente. I vicini richiedono le
verifiche precedenti di documento, pagina, versione, offset e overlap. Nessuna
lettura di PDF non indicizzati per completare la mappa, nuova indicizzazione o
modifica del motore semantico condiviso con il chatbot.

Dopo `validate_map`, un controllo separato valuta la pertinenza delle prove di
ciascun nodo, attorno alle occorrenze della sua denominazione, in un contesto
locale limitato da fine frase. Una citazione molto ampia non assegna automaticamente
il tema di un'altra frase a ogni entità del chunk. Le prove di una relazione già
validata possono fornire contesto agli estremi; un contesto su due chunk richiede
anche le citazioni contigue verificate. Non basta la co-occorrenza.

Le proposte/misure pertinenti hanno priorità nelle domande sulle misure; segue
il punteggio di pertinenza. Il grado del nodo non elimina gli isolati. Gli archi
fuori tema sono esclusi. Predicati verificati ma generici, per esempio «chiede al»,
restano nei dettagli con le prove originali, senza diventare il collegamento
principale. Non si completano oggetti o azioni mancanti.

Per la Timeline il controllo è limitato ai destinatari/luoghi espliciti: esclude
eventi fuori contesto mantenendo intatti date, provenienza e classificazione.
Non cambia il prompt temporale né i validatori delle date.

## Rendering, cache e diagnostica

- Nodi pertinenti collegati e isolati possono convivere nello stesso grafo.
  Nessun arco sintetico per collegarli. Legenda breve quando serve.
- Grafo centrato in un contenitore limitato, `width="content"` e
  `height="content"`, senza un viewport forzato. Font nodi 12 e relazioni 11,
  etichette brevi e tooltip completi; disposizione verticale per grafi più grandi.
- Massimo dieci nodi nel grafo, tutti i concetti conservati nell'Elenco e nei
  dettagli; Grafo/Elenco alternativi. Testate e pagine cliccabili riutilizzano
  gli stessi controlli di sicurezza PDF.
- Strategia mappa `concept-map-v5`, pertinenza `knowledge-relevance-v1` nelle
  chiavi della cache Knowledge. Nessuna cancellazione delle cache precedenti o
  invalidazione dei prodotti RAG/editoriali/audio. La versione della pertinenza
  copre anche il filtro circoscritto della Timeline, separata dalle regole di data.
- Le strategie sono controllate anche per i risultati RAM: quelli obsoleti non
  vengono mostrati o rigenerati automaticamente. Occorre un nuovo invio esplicito.
- In sviluppo, le fonti selezionate, i punteggi/motivi dei nodi, le esclusioni
  degli archi e i nodi nel grafo sono consultabili nei pannelli diagnostici.
  Nei log rimangono solo conteggi, cause e versioni, senza testi, query o chiavi.

## Verifiche reali locali e limiti

Controllo dei file SQLite in **sola lettura**, confrontando ID, fingerprint e testo
con il corpus attuale: **360 chunk indicizzati su 597**, quattro PDF, nessun avviso
di archivio. Il ranking locale della domanda di esempio seleziona cinque passaggi
da tre PDF (pagine 9, 8, 13, 13 e 9), senza API. Questo verifica la selezione locale,
non una nuova risposta Gemini né la validità di una mappa generata sul corpus reale.

La pertinenza locale è una regola spiegabile, non comprensione semantica completa.
Il vocabolario di equivalenze è limitato; formulazioni non riconosciute, pronomi
o riferimenti lontani possono produrre esclusioni conservative. Il PDF non è
segmentato automaticamente in articoli/colonne: non viene inferita appartenenza
allo stesso articolo dalla sola vicinanza. I controlli sulle prove restano necessari.

La resa browser effettiva, inclusi zoom nativo, smartphone e leggibilità, resta
da verificare manualmente. I test delle chiamate Streamlit e dei parametri DOT
non equivalgono a screenshot alle diverse risoluzioni. Nessuna chiamata Gemini
reale o modifica a database, embeddings, corpus, account o consensi.

## File dell'intervento

Creati: `edicola/knowledge_relevance.py`, `tests/test_knowledge_relevance.py`,
questa guida.

Modificati: `edicola/knowledge.py`, `knowledge_validation.py`, `knowledge_views.py`,
`map_relations.py`, `reading_ui.py`; `tests/test_knowledge.py`,
`test_concept_map.py`, `test_knowledge_functional.py`; `README.md`, `AGENTS.md`.
I nomi senza cartella seguono il prefisso del proprio gruppo.

## Prova manuale

Suite completa eseguita: **673 test superati**, nessun fallimento; 88 avvisi di
deprecazione delle librerie esistenti. I 20 nuovi casi riproducibili coprono
pertinenza/validità distinte, settori e terminologie differenti, destinatari e
luoghi, isolati, predicati generici, prove contigue, dimensioni intrinseche di
grafi con 2/3/5/10 nodi, log senza contenuti, cache persistente e risultati RAM.
Le regressioni includono fonti PDF e navigazione senza chiamate automatiche.

```powershell
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

```powershell
.venv\Scripts\python.exe -m streamlit run app.py
```

1. Aprire **Mappe concettuali**, inserire la domanda sulle misure per le imprese
   di pesca e generare solo con invio e consenso espliciti. La vecchia cache non
   deve ricomparire. Una mappa precedente in RAM deve richiedere l'aggiornamento.
2. Controllare che concetti sui trasporti non sostituiscano quelli sulla pesca,
   e che i concetti pertinenti isolati rimangano anche in presenza di archi.
   Non pretendere mutui o altre misure se le fonti recuperate non le documentano
   nel settore richiesto.
3. In **Fonti e dettagli** e **Collegamenti e prove**, aprire PDF/pagine e
   confrontare denominazioni, predicati e contesto originali.
4. Passare fra Grafo/Elenco e altre destinazioni, poi tornare: nessuna API di
   generazione o embedding deve essere richiamata dalla navigazione.
5. Controllare grafi di due o tre nodi e grafi più ricchi a 1440, 1024, 768, 390 e
   360 px. Il grafo piccolo deve conservare proporzioni naturali; Elenco rimane
   disponibile sui dispositivi stretti.
6. Provare destinatari/luoghi diversi e una Timeline sullo stesso tema: niente
   eventi estranei, date solo se verificate e sviluppi senza data separati.

Nessun commit, push o deployment.
