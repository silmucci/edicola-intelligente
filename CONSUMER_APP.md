# Esperienza cliente e prodotto editoriale unico

Aggiornamento successivo: il recupero e i vecchi campioni numerici descritti nel
confronto storico seguente sono stati superati dalla [regola comune del contesto](CORPUS_CONTEXT.md).
La navigazione e la compatibilità dei prodotti salvati restano quelle qui descritte.

## Scelta: Briefing

Confronto del codice effettivo prima dell’unificazione:

| Funzione | Briefing | Dossier |
| --- | --- | --- |
| Scelta delle fonti | Parole chiave, edizioni, ambito, intervallo di date e ultima edizione | Argomento libero; ricerca semantica con diversificazione per PDF |
| Organizzazione | Campione bilanciato tra edizioni, gruppi tematici come suggerimenti, da una a otto notizie documentate | Struttura fissa: titolo, introduzione, due sezioni tematiche, conclusioni |
| Campione predefinito | Otto passaggi | Cinque passaggi |
| Completezza | Tutto il campione selezionato entro il budget; notizie validate singolarmente, anche risultato parziale | Sette affermazioni obbligatorie; astensione se la struttura non è verificabile |
| Citazioni e PDF | Validazione esistente, pulsanti alle pagine originali | Stessi controlli e accesso alle pagine originali |
| Risultati | Sessione e cache persistente; compatibilità con Podcast | Sessione e cache persistente; compatibilità con Podcast |

Briefing conserva il flusso più completo per scegliere e leggere le fonti. Le
parole chiave consentono di concentrarsi su un tema con i filtri già esistenti;
non equivalgono alla ricerca semantica del vecchio Dossier. L’introduzione e le
conclusioni di Dossier non sono state aggiunte: avrebbero richiesto un nuovo
prompt o una seconda modalità, fuori dai vincoli. Campioni, budget, retrieval,
prompt e validatori non sono cambiati.

## Comportamento attuale

Otto destinazioni condivise tra navigazione, card e ricerca: Rassegna stampa,
Archivio PDF, Chat AI, Briefing, Timeline, Mappe concettuali, Podcast e Il mio profilo.
La Rassegna apre Briefing con i filtri correnti; non contiene più un generatore
duplicato. La chat prepara soltanto la bozza del Briefing o degli altri prodotti
ancora presenti. Il solo invio autorizzato può avviare la generazione esistente.

Il selettore **Letture già disponibili** legge la cache editoriale in sola lettura
attraverso il lettore già usato dai Podcast. Include i vecchi dossier validi e il
risultato Dossier ancora presente nella sessione. I prodotti non vengono convertiti,
risalvati o cancellati. Il backend storico Dossier rimane disponibile internamente
per compatibilità e valutazione sperimentale, senza percorso cliente di generazione.
Anche i Podcast continuano ad accettare i risultati storici.

Infografiche: eliminati i due moduli esclusivi e tutti gli ingressi nell’app.
La funzione non aveva un archivio persistente dedicato: eventuali vecchi valori
RAM non sono cancellati né reinterpretati e non riattivano alcuna vista.
Le preferenze personali di formato e le visualizzazioni condivise non dipendevano
da quei moduli e rimangono disponibili.

Citazioni rinumerate soltanto nella presentazione: i riferimenti S/chunk/hash
rimangono intatti nei risultati e nei controlli PDF. I testi originali dei PDF non
vengono riscritti. Etichette delle fonti con testata/pagina o riferimento neutro,
senza nomi tecnici dei file. Errori e copertura espressi in linguaggio naturale;
cause tecniche conservate nel backend. La diagnostica esistente rimane confinata
alla configurazione esplicita di sviluppo, senza interruttori per il cliente.

Consensi: corretta soltanto la lista dei prodotti nella descrizione testuale,
togliendo quello ritirato. Scopi, versioni, scelte, payload inviati, controlli,
account e autorizzazioni restano invariati. Nessuna migrazione o scrittura di dati.

Il precedente README, comprese le note della rifinitura Timeline/Mappe, è conservato
integralmente in `DEVELOPMENT_HISTORY.md`. `EDITORIAL_AUDIT.md` è indicato come
documento storico; il README corrente non promette funzionalità ritirate.

## File di questo intervento

- Avvio, navigazione e flussi: `app.py`, `edicola/product_navigation.py`,
  `edicola/editorial_handoff.py`, `edicola/reading_ui.py`, `edicola/experience_ui.py`.
- Presentazione condivisa e fonti: `edicola/chat_sources.py`, `edicola/design.py`,
  `edicola/header_ui.py`, `edicola/pdf_viewer.py`, `edicola/press_review_ui.py`.
- Podcast e profilo: `edicola/podcast_ui.py`, `edicola/personalization_ui.py`,
  `edicola/account_ui.py`.
- Soli testi di accesso/autorizzazione: `edicola/identity.py`, `edicola/consent.py`,
  `edicola/consent_ui.py`.
- Eliminati: `edicola/infographic.py`, `edicola/infographic_ui.py`.
- Documentazione: `AGENTS.md`, `README.md`, `DEVELOPMENT_HISTORY.md`,
  `EDITORIAL_AUDIT.md`, questo documento.
- Test: nuovo `tests/test_consumer_ui.py`; aggiornati `tests/test_app.py`,
  `tests/test_chat_history.py`, `tests/test_corpus_update.py`,
  `tests/test_editorial_audit.py`, `tests/test_editorial_design.py`,
  `tests/test_experience_ui.py`, `tests/test_navigation_editorial.py`,
  `tests/test_pdf_viewer.py`. Rimossi i casi esclusivi delle funzioni ritirate;
  mantenuti quelli del backend storico.

Le modifiche già presenti a Timeline, Mappe e ai relativi test sono conservate.
Lo stato preesistente di `deployment/seed/` non è stato modificato.

## Verifiche

Eseguiti **10 test UI con dati interamente simulati** in `test_consumer_ui.py`:
navigazione reale dell’app con acquisizione simulata, Home verso Briefing,
assenza dei controlli ritirati, consultazione dei risultati precedenti, citazioni,
PDF delegati al controllo esistente, errori pubblici e invio esplicito autorizzato.
Nessuna lettura o scrittura dei dati reali dell’app, né API o servizi esterni.
Il primo avvio dei test incontrava un permesso negato sulla cartella temporanea
di pytest; la fixture è stata resa interamente simulata senza quella dipendenza.

La suite completa non è stata eseguita: alcune fixture preparano PDF, database
e indici sintetici. Ulteriori test pertinenti, da eseguire in ambiente isolato:
`test_navigation_editorial.py`, `test_editorial_audit.py`, `test_app.py`,
`test_chat_history.py`, `test_pdf_viewer.py`, `test_editorial.py`,
`test_podcast.py`, `test_podcast_ui.py`, `test_personal_accounts.py`,
`test_personalization.py`, `test_archive_design.py` e `test_experience_ui.py`.

Verifica manuale consigliata con risultati già disponibili: otto sezioni e nessun
ingresso ritirato, filtri dalla Rassegna al Briefing, letture storiche e risultato
corrente, citazioni e pagine PDF, fonti obsolete, Podcast esistenti, navigazione
senza generazione, autorizzazioni e separazione dei dati personali. Controllare
desktop e 390/320 px, con tastiera e touch. Il collaudo visivo e i servizi reali
non sono stati esercitati. Corpus e i 76 passaggi ancora da indicizzare restano
fuori da questo intervento. Nessun commit, push o deployment.
