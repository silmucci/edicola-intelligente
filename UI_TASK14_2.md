# Interfaccia editoriale — Task 14.2

## Navigazione

Il catalogo `edicola/product_navigation.py` è l'unica configurazione di nomi,
ordine, destinazioni, descrizioni e icone. La barra superiore, le nove card della
Rassegna stampa e la ricerca locale usano lo stesso catalogo:

1. Rassegna stampa
2. Archivio PDF
3. Chat AI
4. Briefing
5. Dossier
6. Timeline
7. Mappe concettuali
8. Podcast
9. Il mio profilo

La Rassegna stampa è la homepage. La barra usa controlli nativi `st.pills`, con
wrapping e stato attivo, invece di comprimere nove schede. Si monta soltanto la
destinazione scelta: non occorre più scegliere Briefing/Dossier o Timeline/Mappa
in una seconda sottosezione. Gli ingressi standalone dei renderer rimangono
compatibili con i test e gli usi precedenti.

Risultati editoriali distinti per prodotto nella sessione; bozze della Timeline
e della Mappa separate. Un elenco esplicito conserva i soli input necessari
quando Streamlit smonta una vista. Non si conservano pulsanti di generazione,
conferme distruttive o vecchi invii in attesa di consenso. Cambiare destinazione
annulla l'azione pendente, senza revocare la scelta di consenso. Per generare
occorre un nuovo invio. Restano i controlli di identità e pulizia dei dati privati.

I collegamenti alle fonti e il pulsante del profilo aprono direttamente le nuove
destinazioni. Le etichette obsolete nelle istruzioni di Podcast e profilo sono
state adeguate. Nessuna navigazione effettua chiamate Gemini.

## Mappe

- Titolo ricavato localmente dalla richiesta, abbreviato senza inventare un
  titolo di notizia. La richiesta completa rimane consultabile.
- Nodi con etichette corte, tooltip completi, colori sobri del design Task 13,
  massimo dieci nodi nella vista compatta.
- Grafo ed Elenco sono alternativi: nessuna tabella duplicata sotto il grafo.
- Frecce per relazioni documentate, tratteggio per temi comuni supportati;
  senza relazioni compaiono soltanto concetti raggruppati, senza archi.
- Legenda breve; fonti dei concetti in **Fonti e dettagli**, collegamenti e prove
  su richiesta. I pulsanti mostrano testata e pagina quando i metadati sono
  curati, oppure un riferimento neutro al documento, senza sigle tecniche.
- Identificativi di fonte rimangono nei dati validati, ma non nelle etichette
  del grafico. Dettagli completi e passaggi originali sono consultabili.

## Timeline

Gli eventi con data verificata mantengono l'ordine cronologico e l'asse verticale.
Gli sviluppi senza data sono card compatte separate, senza asse, in ordine delle
fonti dichiaratamente non cronologico. Ogni card abbrevia titolo e descrizione
letteralmente; non riscrive fatti o numeri. Le informazioni complete, le date di
pubblicazione e le prove rimangono nei dettagli. Fonti PDF cliccabili sotto le card.
Proposte, annunci, decisioni e fatti mantengono la classificazione verificata;
non si attribuisce una data fittizia agli sviluppi o una scadenza alla proposta.

La copertura parziale è segnalata sinteticamente. Lo stato vuoto è unico e ha una
formulazione editoriale; i conteggi che distinguono le cause restano nel backend.
Cache, validazione e algoritmo non vengono spiegati nella vista principale.
Diagnostica accessibile solo nei pannelli di sviluppo quando
`EDICOLA_ARCHIVE_DIAGNOSTICS=1` è configurato dal gestore.

## Vincoli preservati

Nessuna modifica a retrieval, generazione AI, modelli, consensi, Google OIDC,
Supabase, cache persistenti, validazione delle prove o regole temporali. In
`knowledge_validation.py` cambia soltanto il rendering DOT, non i validatori.
PDF, embeddings, ChromaDB e corpus restano invariati. Nessuna nuova dipendenza,
risorsa esterna per il design, commit, push o deployment. Nessuna API reale nei
test o durante questo intervento.

## File

Modificati: `app.py`; in `edicola/`: `product_navigation.py`, `experience_ui.py`,
`editorial_components.py`, `header_ui.py`, `pdf_viewer.py`, `reading_ui.py`,
`knowledge_views.py`, `knowledge_components.py`, `knowledge_presentation.py`,
`knowledge_validation.py`, `podcast_ui.py`, `personalization_ui.py`.

Creato `tests/test_navigation_editorial.py`; aggiornati i test esistenti di app,
Home, design editoriale, Archivio, cloud, fonti PDF, timeline e mappe per le nuove
destinazioni e il rendering semplificato. Aggiornati `README.md` e `AGENTS.md`;
creata questa guida.

## Verifica

```powershell
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.venv\Scripts\python.exe -m streamlit run app.py
```

I test simulati coprono le nove card e la barra reale dell'app, prodotto attivo,
risultati e bozze conservati, annullamento delle richieste pendenti, assenza di
API sulla navigazione, grafico/elenco alternativi, fonti PDF, date e relazioni
validate, consensi e regressioni delle funzionalità precedenti. Il contratto CSS
verifica adattamento al contenitore e assenza dell'asse nelle card senza data.

Esito della suite completa: **653 test superati**, nessun fallimento; 88 avvisi
di deprecazione delle librerie esistenti. Nessuna chiamata Gemini reale.

### Checklist browser ancora manuale

Il runtime di controllo visivo non espone browser o applicazioni. I test
Streamlit e CSS non equivalgono a screenshot o prove reali a diverse risoluzioni.

Controllare **1440, 1024, 768, 390 e 360 px**:

- Barra con etichette leggibili e wrapping, destinazione attiva riconoscibile;
  card Home e barra con gli stessi nove nomi nello stesso ordine.
- Accesso diretto a Briefing, Dossier, Timeline e Mappe, senza sottoselettori.
- Generare esplicitamente una timeline e una mappa, quindi cambiare sezione e
  tornare: risultati e bozze separati, nessuna generazione automatica.
- Grafo contenuto e leggibile; Elenco alternativo, fonti raggiungibili da touch
  e tastiera. Graphviz mantiene i soli controlli di zoom offerti da Streamlit.
- Fonti aperte al PDF e alla pagina corretti; passaggi estesi solo su richiesta.
- Timeline datata distinta dagli sviluppi senza data; nessuna cronologia
  artificiale o relazione aggiunta per riempire un risultato.
- Login/logout Google, due account Supabase distinti, revoca/consenso e Chat AI:
  completare la prova con la configurazione reale, senza invii involontari.

La qualità del contenuto dipende dalle fonti disponibili; non sono stati creati
nuovi risultati Gemini per valutare il redesign.
