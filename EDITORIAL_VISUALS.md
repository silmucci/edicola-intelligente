# Presentazione editoriale di Timeline e Mappe

Intervento limitato al rendering dei risultati già disponibili, dopo lettura
di AGENTS.md, README, stato Git e diff. Le precedenti modifiche di navigazione
sono già presenti nella versione corrente. Le cancellazioni/accessi negati sotto
`deployment/seed/` sono preesistenti e non sono stati toccati.

## Timeline

- Un unico componente rende la sequenza cronologica con asse verticale continuo,
  marker e card: data verificata, titolo, sintesi ed etichette delle fonti PDF.
- Le fonti nelle card aprono il lettore esistente. Il server verifica indici
  dell’azione, appartenenza all’archivio, pagina e riferimento al passaggio;
  l’apertura riusa anche i controlli esistenti sul PDF originale.
- Sintesi complete e dettagli sono disponibili su richiesta. Tutti i testi dei
  documenti nel componente sono inseriti come testo, mai come HTML attivo.
- Gli sviluppi privi di data verificata restano distinti dall’asse, nell’area
  espandibile **Altri sviluppi**, ordinati come prima. Se non ci sono eventi
  datati, l’area è aperta per rendere subito consultabile il contenuto disponibile.
  Non viene introdotto un legame fra eventi diversi né attribuita una data.
- Rimossi «Richiesta originale» e l’intestazione principale «Senza data».
  «Leggi la fonte» sostituisce «Passaggi originali». Il riepilogo delle edizioni
  è disponibile nel popover **Fonti consultate**.

## Mappe

- Componente locale con nodi come pulsanti reali e archi SVG. Nessuna nuova
  libreria, CDN, query o chiamata AI. Colori tenui e forma/etichetta distinguono
  i tipi già validati. Le denominazioni non sono troncate con ellissi.
- Il layout segue i componenti connessi e i loro livelli, con dimensioni proprie
  e scorrimento interno su schermi piccoli. Non si aggiungono archi per disporre
  i nodi. I concetti isolati sono conservati e la vista resta limitata a dieci nodi.
- Frecce per le relazioni documentate, tratteggio senza freccia per temi comuni.
  Le etichette derivano esclusivamente dagli archi già presenti e validati;
  nessuna riscrittura automatica in «sostiene», «critica» o altri predicati.
- Il clic su un nodo invia un indice verificato lato server e apre un pannello
  sotto il grafo con denominazione completa, tipo, relazioni e fonti. Il grafo
  resta visibile per orientarsi. L’Elenco offre controlli nominativi alternativi.
- Se le fonti del risultato non contengono relazioni validate, i concetti restano
  senza archi, con una spiegazione breve. Migliorare la grafica non può recuperare
  relazioni mancanti dal risultato né autorizza a inventarle.

## File modificati

- `edicola/knowledge_components.py`: nuovo componente della sequenza Timeline;
  conservata la card singola per sviluppi secondari e chiamanti esistenti.
- `edicola/knowledge_views.py`: integrazione, azioni PDF, pannelli dei nodi,
  dettagli facoltativi e nuove etichette.
- `edicola/map_component.py` (nuovo): grafo interattivo locale con eventi verificati.
- `edicola/chat_sources.py`: parametro facoltativo per il riepilogo compatto;
  Chat, Briefing e altri chiamanti conservano il comportamento precedente.
- `README.md` e `EDITORIAL_VISUALS.md`: documentazione della nuova presentazione.

## Compatibilità e limiti

Invariati schemi dei risultati, date e ordinamento, selezione dei nodi, validatori,
retrieval, modelli, consensi, autenticazione, corpus e indicizzazione. Nessuna
modifica o invalidazione delle cache e dei dati persistenti. Restano i renderer
e gli helper precedenti per compatibilità interna, il lettore PDF con i suoi
controlli, la vista Elenco, le prove complete e la diagnostica di sviluppo.
Le chiavi dei nuovi componenti distinguono risultati diversi soltanto nella UI.
La selezione di un nodo o di un dettaglio non genera nuovi contenuti.

**Non sono stati eseguiti test, chiamate esterne o collaudi visivi/interattivi**,
come richiesto. Il controllo effettuato riguarda lettura statica di codice e
diff, inclusi i percorsi dei callback. Restano da verificare nell’app il rendering
dei componenti, eventuali sovrapposizioni di etichette in grafi densi, scorrimento
su smartphone, tastiera, selezione dei nodi e apertura dei PDF. I test legati
alla precedente struttura della UI non sono stati eseguiti o aggiornati.
Nessun commit, push o deploy.
