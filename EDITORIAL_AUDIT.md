# Audit funzionale dei prodotti editoriali

Audit del codice e completamento funzionale del 30 ottobre 2026. Le verifiche
automatiche usano documenti sintetici e API simulate; non costituiscono una
valutazione giornalistica delle risposte sul corpus reale.

## Stato iniziale e interventi

| Prodotto | Stato iniziale | Evidenza nel codice e risultato dell’intervento |
|---|---|---|
| Rassegna stampa | Parziale | La home mostrava copertine ed estratti; `editorial.generate_product` produceva un briefing bilanciato senza filtri. Aggiunti consultazione per parole chiave/fonti, gruppi per affinità dei vettori esistenti e sintesi della selezione con cache distinta. |
| Dossier | Già implementato nella struttura richiesta | Recupero semantico diversificato per PDF, sette claims validati, introduzione, due sezioni tematiche, conclusioni e fonti originali. Aggiunti conteggio delle edizioni effettivamente citate e avviso quando ne è citata una sola. |
| Podcast | Già implementato come ascolto breve estrattivo; consultazione per tema parziale | Copioni da cache editoriale in sola lettura, sezioni complete, limiti di 240 parole/3500 caratteri, fonti fuori dalla lettura, consenso audio, WAV verificato. Aggiunta ricerca degli episodi per tema e salto delle sezioni troppo lunghe conservando quelle successive ammissibili. Corretto il riuso nella UI degli audio: il manifest deve corrispondere anche al copione corrente, al modello e alla versione, oltre a prodotto/voce. |
| Mappa | Prove, relazioni ed elenco già implementati; focus interattivo parziale | `knowledge_validation`, `map_relations` e `map_context` verificano concetti, predicati e contesto. Aggiunto filtro nominativo che mostra nodo e vicini già verificati, con ritorno a tutti i concetti, senza generazione o modifica delle cache. |
| Timeline | Già implementata nei requisiti richiesti | `timeline_dates`, `knowledge_validation`, `knowledge_relevance` e `knowledge_views` separano eventi datati e sviluppi senza data, classificano dalle prove originali, filtrano pertinenza e aprono le pagine originali. Eliminata una ripetizione nei dettagli dell’anno completato. Non modificati selezione, asse, prompt o validatori. |
| Infografica | Assente come prodotto | Aggiunto prodotto locale autonomo: quadro a blocchi di estratti letterali delimitati, fino a otto punti, deduplicazione e fonti per pagina con indicazione dei punti corrispondenti. Risultato e input distinti da briefing, dossier e mappe. Nessun grafico numerico, inferenza quantitativa o chiamata AI. |
| Chat editoriale | RAG e fonti compatte già implementati; avvio degli altri prodotti assente | Aggiunte sei azioni nell’ultima risposta sufficiente. Trasferiscono soltanto la domanda come tema modificabile; non trasferiscono evidenze, non generano e non memorizzano un invio pendente. Il podcast cerca tra prodotti già presenti. |

## Scelte e limiti editoriali

- Le nove destinazioni principali rimangono quelle condivise in
  `product_navigation.py`. **Infografica** è un prodotto con modulo, input,
  azione e risultato propri, accessibile nel selettore **Prodotto editoriale**
  dell’area **Briefing** e direttamente dalle azioni della chat.
- La rassegna cerca tutte le parole chiave nel medesimo passaggio, senza nuovi
  embedding. I gruppi tematici derivano dagli embedding già indicizzati: sono
  ausili di consultazione, non sezioni giornalistiche curate né articoli ricostruiti.
  Si esplora un gruppo alla volta con quantità di passaggi selezionabile.
- L’eventuale campo manuale `scope` di `data/editions.json` ammette
  `nazionale` o `internazionale`. Descrive l’edizione, non ogni sua notizia.
  Senza quel dato il filtro non assegna classificazioni. Nessun metadato del
  corpus è stato modificato o inventato in questo intervento.
- I filtri della sintesi fanno parte della copertura e quindi della chiave
  della cache. La copertura globale dell’indice resta visibile come parziale
  quando lo era già; la selezione locale non diventa copertura esaustiva delle
  notizie. I passaggi effettivamente inviati restano entro i limiti esistenti.
  I filtri fanno anche parte della firma dell’invio in attesa di consenso:
  cambiarli, oppure cambiare prodotto nel selettore Briefing/Infografica,
  annulla la richiesta pendente e richiede un nuovo invio.
- Il dossier integra solo le fonti recuperate; due PDF non sono necessariamente
  due fonti indipendenti. L’avviso rende esplicita una sola edizione citata.
- Il podcast mantiene l’impostazione estrattiva prescritta da AGENTS.md, non
  introduce una riscrittura narrativa con un nuovo modello. Il copione è distinto
  dal testo formattato, privo dei riferimenti letti ad alta voce, e composto da
  sezioni intere; l’anteprima dichiara estratti e copertura parziale.
- Il focus delle mappe non trova nuove relazioni: filtra quelle già validate.
  Restano il limite di dieci nodi nel grafo, le prove dei collegamenti, i dettagli
  nominativi e la vista alternativa Elenco. I concetti isolati sono consultabili.
- L’infografica non valuta l’importanza dei fatti: presenta punti letterali in
  ordine delle fonti. Esclude i bordi incompleti dei chunk, frasi troppo lunghe
  e testi privi delle parole cercate. Conserva decimali, negazioni e modalità;
  alcuni testi legittimi possono essere esclusi dal riconoscimento conservativo
  dei confini di frase. Non inventa confronti, causalità, percentuali o categorie.
- Le azioni della chat propongono la domanda precedente come bozza. Una domanda
  discorsiva va adattata alle parole chiave nei prodotti locali. Generazione
  testuale e audio richiedono sempre l’invio esplicito e il consenso previsto.
- Le fonti dei nuovi prodotti passano dal lettore PDF esistente, che controlla
  percorso, hash, pagina e chunk corrente. Nessun OCR, CDN o servizio aggiuntivo.

## File

Creati:

- `edicola/press_review.py`, `edicola/press_review_ui.py`;
- `edicola/infographic.py`, `edicola/infographic_ui.py`;
- `edicola/map_exploration.py`, `edicola/editorial_handoff.py`;
- `tests/test_editorial_audit.py`;
- `EDITORIAL_AUDIT.md`.

Modificati:

- `app.py`: accesso a Infografica nell’area Briefing;
- `edicola/editorial.py`: selezione filtrata prima del briefing e cache;
- `edicola/editorial_selection.py`: lettura del solo ambito esplicitamente curato;
- `edicola/experience_ui.py`: consultazione e sintesi della rassegna;
- `edicola/reading_ui.py`: azioni chat, filtri briefing e copertura dossier;
- `edicola/product_navigation.py`: conservazione delle sole bozze e descrizione;
- `edicola/knowledge_views.py`, `edicola/knowledge_validation.py`: focus locale;
- `edicola/podcast_ui.py`, `edicola/podcast_text.py`: ricerca episodi e copione;
- `edicola/personalization_ui.py`: controllo opzionale del copione negli audio in cache;
- `README.md`: nuovi percorsi e limiti.

Nessuna migrazione SQL nuova o applicata. Nessuna modifica a OIDC, Supabase,
RAG, embedding o algoritmo di acquisizione/chunking. Nessun commit, push,
deployment o provisioning. Le cancellazioni già presenti sotto `deployment/seed`
e i file estranei già presenti nel working tree non fanno parte dell’intervento.

## Come provare

Avviare `.\.venv\Scripts\python.exe -m streamlit run app.py` in PowerShell.
Il corpus deve essere già acquisito e indicizzato; non si avvia alcuna nuova
indicizzazione dai percorsi descritti.

1. **Rassegna stampa**: sotto le letture in evidenza usare **Consulta la rassegna**,
   scegliere parole chiave e fonti, esplorare i gruppi e aprire un PDF. Premere
   **Genera briefing** soltanto per ottenere una sintesi autorizzata della selezione.
   Gli stessi filtri sono disponibili in **Briefing**.
2. **Dossier**: indicare un tema, inviare e autorizzare. Verificare sezioni, numero
   di edizioni citate, copertura e apertura delle fonti originali.
3. **Podcast**: cercare un tema nei prodotti già salvati, scegliere un episodio,
   controllare il copione e poi usare **Genera podcast** con consenso audio.
4. **Mappe concettuali**: generare esplicitamente un tema; usare **Concentrati su
   un concetto**, passare tra Grafo/Elenco e tornare a **Tutti i concetti**.
   Queste operazioni non richiedono ulteriori chiamate API.
5. **Timeline**: generare un tema e confrontare **Cronologia documentata** con
   **Eventi e sviluppi documentati**. Gli sviluppi privi di data non hanno asse;
   dettagli e fonti restano disponibili.
6. **Infografica**: aprire **Briefing → Prodotto editoriale → Infografica**,
   inserire parole chiave e premere **Crea infografica**. Verificare i punti e le
   pagine originali. Funziona senza Gemini e non genera audio o altri prodotti.
7. **Chat AI**: dopo una risposta sufficiente premere una delle azioni
   **Prepara…**, verificare il tema nella destinazione ed eventualmente modificarlo.
   Solo il successivo invio del prodotto può effettuare chiamate esterne.

## Verifica automatica

Comando della suite: `.\.venv\Scripts\python.exe -m pytest -q`.
La nuova suite `tests/test_editorial_audit.py` controlla filtri combinati e cache
distinte, esclusione delle fonti non selezionate, infografiche letterali e bordi
incompleti, sei passaggi dalla chat senza generazione, focus/reset della mappa,
copioni con sezioni troppo grandi, audio con copione/modello obsoleti,
conservazione del risultato Infografica nella piattaforma e annullamento degli
invii pendenti quando si cambiano filtri o prodotto.
Risultato finale: **708 test superati**, inclusi 17 nuovi casi di audit, nessun
errore. Sono presenti 94 avvisi di deprecazione delle dipendenze. Anche
`git diff --check` sui file modificati e il controllo sintattico dei 71 moduli
Python dell’app e del nuovo test sono passati.
AppTest verifica flussi e stato Streamlit; non sostituisce una prova visiva nel browser.
