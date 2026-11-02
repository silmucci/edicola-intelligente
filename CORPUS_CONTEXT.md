# Contesto comune dai PDF indicizzati

## Regola applicata ai nuovi invii

I prodotti considerano l’intero corpus corrente e indicizzato, nei limiti degli
eventuali filtri espliciti. Nessuna estrazione, indicizzazione o modifica di PDF,
chunk, vettori, credenziali, consensi o account. Il Podcast deriva dalla lettura
già disponibile e non cerca fonti nuove.

Il numero di passaggi inviati non è più fermato a 3 nella Chat, 5 in Timeline/Mappe,
8 nel Briefing o 6/10/12 nel briefing personale. Si ordinano i candidati pertinenti,
si alternano i PDF e si inseriscono passaggi originali **interi** finché rientrano
nel budget complessivo. Un passaggio troppo grande viene saltato, senza perdere
automaticamente quelli successivi. Identiche notizie di edizioni diverse restano
prove distinte; nella selezione comune non si usa una somiglianza fra testi per
eliminare possibili differenze, negazioni o contraddizioni.

Non si garantisce la presenza di tutti i PDF nell’output: pertinenza, budget,
validazione e limiti editoriali del prodotto prevalgono sulla rappresentanza.
L’output conserva le forme esistenti: fino a otto notizie nel Briefing, date
verificate nella Timeline, dieci nodi nella vista della Mappa, sezioni complete
e brevi nel Podcast. I validatori delle affermazioni, delle date e delle relazioni
sono invariati. Le istruzioni chiedono di attribuire conferme, differenze e
contraddizioni alle rispettive prove, senza inferire legami da un tema comune.

## Percorsi

| Prodotto | Recupero dei candidati | Limite del contesto |
| --- | --- | --- |
| Chat AI | Nuova ricerca per ogni domanda, una embedding condivisa dalla ricerca sull’intero corpus; lo storico interpreta il tema, non fornisce prove | Istruzioni, domanda, storico limitato, metadati inclusi e passaggi entro 14.000 caratteri predefiniti |
| Timeline e Mappe | Stessa ricerca estesa, con il filtro locale di pertinenza esistente delle mappe e soli vicini già indicizzati e contigui | Budget testuale esistente, 12.000 caratteri predefiniti, senza tagliare i passaggi |
| Briefing | Tutto il catalogo filtrato, ranking tematico e alternanza delle edizioni; nessuna embedding aggiuntiva | Budget testuale esistente di 14.000 caratteri e massimo complessivo di 8.000 caratteri delle fonti |
| Briefing personale | Tutte le corrispondenze locali agli interessi attivi e ai feedback, distinte per PDF | Budget testuale esistente di 14.000 caratteri, inclusa la consegna sul tempo di lettura |
| Rassegna e consigli | Filtri su tutto il catalogo corrente, contributi di PDF distinti conservati | Le schede sono un campione di presentazione, espandibile nella Rassegna; nessuna chiamata AI |
| Podcast | Solo fonti delle sezioni effettivamente lette del prodotto originario | Stessi limiti estrattivi e controlli del copione, senza nuova ricerca o nuovi fatti |

I budget sono i limiti testuali di istruzioni e payload, con un ulteriore limite
complessivo delle fonti nel Briefing; non sono una misura dei token fatturati.
Le vecchie opzioni top-k rimangono compatibili per gli strumenti di ricerca e
valutazione, ma non impongono un tetto globale ai prodotti in modalità corpus.
Non sono stati modificati file di configurazione. Il budget della Chat è
configurabile internamente tramite `GEMINI_RAG_MAX_PROMPT_CHARS` (4.000–40.000),
senza controlli tecnici aggiunti all’interfaccia cliente.

## Ricerca locale e pertinenza

`semantic_search(..., corpus_wide=True)` crea una sola embedding della richiesta,
poi legge a blocchi i vettori già presenti e calcola localmente le distanze cosine
di **tutti** i candidati ammessi. Non si usa un top-k globale o una richiesta AI
per ogni documento. Esclusi i passaggi mancanti, obsoleti o incoerenti con il testo
e la fingerprint correnti. Filtri per filename e ID ammessi sono applicati prima
della lettura dei vettori e dell’embedding; una selezione vuota non invia nulla.

Il filtro semantico è euristico e versionato: distanza massima 0,65 e finestra
massima di 0,20 dal candidato migliore. Non è una prova di pertinenza fattuale o
di relazione. Le mappe conservano inoltre il filtro locale esistente di destinatari,
luoghi e alias di ranking; gli alias non validano citazioni. Soglie e qualità delle
sintesi non sono state tarate o misurate con API reali durante questo intervento.

## Provenienza e compatibilità

Il prompt contiene metadati delle sole edizioni effettivamente incluse nei passaggi.
**Edizioni incluse nella lettura** distingue «Citata» da «Inclusa, non citata»;
la sola appartenenza al corpus o ai filtri non equivale a consultazione. Le omissioni
per budget sono segnalate senza conteggi tecnici nella UI cliente. I Podcast
mostrano le fonti delle sezioni del copione, conservando la provenienza originaria.

La versione `corpus-context-v1` è separata dalle versioni di citazioni, pipeline,
date e relazioni ed entra nell’identità delle nuove richieste editoriali,
personali e visuali. Le cache precedenti non vengono cancellate o riscritte;
i risultati esistenti restano consultabili e non generano API navigando.
Per applicare il criterio serve un nuovo invio esplicito autorizzato.

Il lettore delle chat accetta ora più di cinque fonti nel formato esistente,
mantenendo i limiti complessivi di messaggi/byte e tutti i controlli dei riferimenti.
Nessuna migrazione o scrittura di dati persistenti è stata eseguita per questo lavoro.

## File e verifiche

- Comune: nuovo `edicola/context_selection.py`; `edicola/search.py`.
- Generazione: `edicola/rag.py`, `edicola/briefing.py`, `edicola/editorial.py`,
  `edicola/knowledge.py`, `edicola/personalization.py`.
- Selezione: `edicola/editorial_selection.py`, `edicola/knowledge_relevance.py`,
  `edicola/experience_ui.py`.
- Presentazione e compatibilità: `edicola/chat_sources.py`, `edicola/chat_data.py`,
  `edicola/reading_ui.py`, `edicola/knowledge_views.py`, `edicola/personalization_ui.py`,
  `edicola/podcast_ui.py`, `edicola/press_review_ui.py`, `edicola/design.py`.
- Documenti: `AGENTS.md`, `README.md`, `CONSUMER_APP.md`, questo documento.
- Test: nuovo `tests/test_corpus_context.py`; aggiornati `tests/test_rag.py`,
  `tests/test_editorial.py`, `tests/test_chat_ui.py`.

Test mirati con oggetti RAM, SDK simulato e nessuna scrittura dell’archivio reale:
12–14 PDF pertinenti, filtri positivi e vuoti, passaggi obsoleti/non indicizzati,
testi lontani dal tema, una embedding per richiesta, budget di passaggi interi,
metadati e suggerimenti senza fonti escluse, briefing personale senza identità nel
prompt, recupero nuovo per ogni domanda e lettura delle chat con più di cinque fonti.
Invarianti temporali e relazionali verificati dai test esistenti; questi controlli
tecnici non misurano accuratezza giornalistica o qualità delle risposte reali.

Esito: **126 test superati** in `test_corpus_context.py`, `test_consumer_ui.py`,
`test_rag.py`, `test_timeline_dates.py` e `test_concept_map.py`; due avvisi di
deprecazione delle dipendenze esistenti. Verificata anche la sintassi dei moduli
Python e l’assenza di errori nel diff. La suite completa che prepara archivi e
indici non è stata eseguita. Le modifiche preesistenti sono conservate.

Verifica manuale consigliata, soltanto con un invio autorizzato quando occorre
generare: un tema distribuito su più di cinque edizioni, un filtro su alcune
testate, fonti che confermano o differiscono e una domanda successiva in Chat.
Controllare edizioni incluse/citate, PDF/pagine, sviluppo datato e senza data,
relazioni documentate, selezioni espandibili e Podcast dello stesso Briefing.
Provare anche un contesto con passaggi molto lunghi e controllare l’avviso delle
omissioni. Nessun invio reale è stato effettuato durante lo sviluppo.
