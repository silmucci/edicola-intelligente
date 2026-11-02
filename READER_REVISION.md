# Rassegna, Timeline e Mappe: revisione funzionale

## Problemi accertati nel codice

- La Rassegna filtrava con `all(term in chunk.text...)`: richiedeva tutte le
  parole nello stesso passaggio, senza ranking delle varianti linguistiche.
  La Home montava controlli di fonte, ambito, copertura e raggruppamento.
- Le finestre di pertinenza delle mappe erano limitate a 180 caratteri per lato:
  potevano perdere l’argomento in una frase lunga che collegava autore e proposta.
  Le entità mancanti dall’output AI non potevano entrare nel completamento degli
  archi, che lavorava soltanto fra nodi già presenti.
- Il calendario riconosceva un insieme ristretto di verbi al passato e non
  gestiva «il giorno precedente» con riferimento esplicito all’edizione. Il
  deduplicatore richiedeva anche descrizioni identiche. Nel prompt era poco
  chiaro il ruolo del completamento temporale affidato a Python.
- Il catalogo prodotto da `archive.read_active_chunks` non fornisce identità
  articolo o titoli verificati. La continuità di pagina non può sostituirli.
- I test della UI comprendevano ancora aspettative Graphviz e menu a tendina
  precedenti ai componenti grafici già presenti nel lavoro locale.

Questi sono limiti verificati nel codice, non una dimostrazione che spieghino
integralmente ogni astensione di Gemini o ogni relazione omessa nelle prove reali.
Non sono state ripetute generazioni remote.

## Correzioni

### Intestazione e Rassegna

Profilo, logo e ricerca condividono un contenitore orizzontale adattabile, con
Profilo a sinistra e ricerca generale a destra. Il flusso Google è invariato.
Restano le sette card editoriali, senza duplicazione nella Home.

La Rassegna ha un solo campo di ricerca in un form, con Invio/Cerca. La bozza
non modifica i risultati fino all’invio. I vecchi filtri della Rassegna vengono
rimossi dalla sessione; il Briefing mantiene i propri controlli espliciti.

Ranking locale con normalizzazione di maiuscole/accenti, alias lessicali già
disponibili, peso dei titoli verificati e alternanza fra edizioni pertinenti.
Non è più necessario trovare tutte le parole nello stesso passaggio. Quando
esiste già un consenso valido, il solo invio esplicito può richiamare la ricerca
semantica esistente; senza consenso la ricerca resta locale. Nessuna generazione
LLM o richiesta per singolo PDF. Il ranking accetta hit semantici solo se ID e
testo corrispondono al catalogo corrente e la distanza è sufficientemente forte.
Bozza e navigazione non chiamano servizi. Un errore del percorso approfondito è
segnalato lasciando disponibili i risultati locali, senza riavviare la ricerca
al rerun. Gli hit sono conservati soltanto nella sessione privata corrente.

I risultati mostrano anteprima, quotidiano, data e apertura della pagina PDF.
In mancanza di un titolo affidabile viene usata un’etichetta neutra, non un titolo
inventato. I passaggi vengono raggruppati soltanto se esistono identità articolo,
hash PDF e configurazione concordanti. **Nel catalogo attuale questi metadati
articolo non sono disponibili:** i risultati restano estratti e possono contenere
parti di più notizie. Le copertine e la consultazione degli originali restano.

### Timeline

- Una domanda con intervallo esplicito come «dal 24 al 29 ottobre 2026» delimita
  le edizioni con date curate, senza attribuire tali date agli eventi.
- Ranking tematico anche per Timeline: parole operative della domanda e mesi non
  sostituiscono il tema. Il controllo della città resta distinto dal tipo di evento.
- Prompt coerente con il completamento Python: prova temporale focalizzata sullo
  stesso evento, anno omesso e riferimenti relativi affidati al calendario verificato.
- Ampliate le forme di svolgimento al passato; annunci e convocazioni restano
  distinti. «Il giorno precedente» viene completato solo se il referente è
  esplicitamente la pubblicazione/edizione. Un referente mancante resta incerto.
- Deduplicazione di eventi con stessa data, stato, titolo e prova letterale breve
  condivisa, anche con parafrasi diverse della sintesi. Numeri, negazioni e modalità
  diverse impediscono l’accorpamento. La sola città non identifica un evento.
- Asse continuo e marker conservati. Titoli completi, senza troncamento imposto
  dalla card. Senza eventi datati si dichiara che non è ricostruibile una cronologia,
  con fonti accessibili e sviluppi secondari chiusi inizialmente.

### Mappe

- La pertinenza può usare la frase intera del riferimento, entro un limite,
  senza attraversare confini di frase per attribuire il tema a un altro articolo.
- Dopo una risposta JSON valida, estrazione nominale delimitata nelle frasi con
  almeno un nodo già validato: persone introdotte da qualifiche, istituzioni,
  partiti e provvedimenti esplicitamente nominati. Nessuna identità dedotta dal
  luogo, dalla co-occorrenza o da conoscenze esterne. Tutti i candidati ripassano
  per controllo delle citazioni, relazioni e pertinenza.
- Predicati letterali aggiuntivi, comprese forme attive e passive, presentazione,
  sostegno, esame e oggetto esplicito. Nessun collegamento precompilato per i tribunali.
- Sigle normalizzabili soltanto con equivalenza parentetica esplicita nelle prove.
  Non si accorpano automaticamente cognomi o sigle presunte; non si sacrifica un
  arco valido per normalizzare il nome.
- La vista limitata a dieci nodi mantiene i ponti documentati fra concetti
  prioritari quando possibile. Gli isolati restano nel risultato e nell’Elenco;
  non vengono aggiunti archi di layout o relazioni per migliorare la figura.
- Senza archi validati si mostrano spiegazione ed entità con fonti, anziché un
  grafo presentato come riuscito. Clic, dettagli e colori conservati; selezione
  evidenzia nodi/archi collegati e lo spazio fra righe considera le etichette.

«Leggi la fonte» sostituisce anche il vecchio controllo degli originali nelle
altre letture. L’avviso di selezione/copertura è unico per ciascuna lettura.

## Cache e dati

Versioni aggiornate: `press-review-v2`, `knowledge-relevance-v3`,
`timeline-dates-v3`, `timeline-developments-v4`, `concept-map-v7`.
I nuovi invii usano identità diverse; nessuna cancellazione di cache storiche.
Anche i risultati RAM precedenti restano consultabili con un avviso: non vengono
scartati al cambio di versione né prima che una nuova generazione riesca.
Nessuna rigenerazione su navigazione o scelta di un nodo. Invariati acquisizione,
corpus, database, embedding configurati, modelli, autenticazione e consensi.
Le scritture delle prove riguardano soltanto fixture temporanee isolate.

## File modificati in questa revisione

- Intestazione: `edicola/header_ui.py`, `design_tokens.py`.
- Rassegna: `edicola/press_review.py`, `press_review_ui.py`, `experience_ui.py`;
  `product_navigation.py` conserva la nuova bozza tra le sezioni.
- Orchestrazione/pertinenza: `edicola/knowledge.py`, `knowledge_relevance.py`,
  nuovo `knowledge_scope.py`.
- Timeline: `edicola/timeline_dates.py`, `timeline_events.py`,
  `knowledge_presentation.py`, `knowledge_validation.py`, `knowledge_components.py`.
- Mappe: `edicola/map_literal.py`, `map_relations.py`, `map_exploration.py`,
  nuovo `map_aliases.py`, componente locale preesistente `map_component.py`.
- Lettura: `edicola/knowledge_views.py`, `chat_sources.py`, `reading_ui.py`,
  `personalization_ui.py`, `account_ui.py`.
- Test: nuovo `tests/test_reader_revision.py`, aggiornato
  `tests/test_knowledge_relevance.py` per le aspettative superate della UI.
- Documentazione: `README.md`, questo resoconto.

I componenti grafici e le modifiche locali precedenti sono stati conservati;
le cancellazioni/accessi negati preesistenti sotto `deployment/seed/` sono intatti.

## Verifiche e limiti

Eseguite regressioni offline con esempi sintetici, mock SDK e directory di fixture
dedicate, senza invii Gemini. Coperti ricerca sanità senza tutte le parole,
invio esplicito del form, filtri nascosti, calendario, annunci, deduplicazione,
passive/attive, sigle esplicite, rifiuto di archi inventati, nodi intermedi,
versioni cache e navigazione senza chiamate AI. Il primo tentativo aveva errori
di permessi nella cartella temporanea predefinita: risolti usando directory nuove
dedicate sotto `.private-runtime/`. Non sono stati letti o modificati indici reali.

Risultato finale: **221 test superati**, con due avvisi di deprecazione delle
dipendenze esistenti. Eseguiti `test_reader_revision.py`, `test_timeline_dates.py`,
`test_concept_map.py`, `test_map_context.py`, `test_knowledge.py`,
`test_knowledge_relevance.py`, `test_editorial.py`, `test_corpus_context.py`.
Non è stata eseguita la suite completa. Nessun collaudo visivo desktop/mobile e nessuna nuova
risposta reale di Gemini: non si certificano ancora completezza delle cronologie,
estrazione reale di tutte le relazioni o assenza di sovrapposizioni nei grafi densi.
I riferimenti relativi ambigui restano senza data; la somiglianza tematica non
diventa una relazione. Nessun commit, push o deploy.
