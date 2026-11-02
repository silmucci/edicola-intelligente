# In edicola e Podcast tematici

## Modifiche di questo intervento

- **In edicola** è la destinazione iniziale delle nuove sessioni e la prima
  delle sette card SVG. Le sessioni già aperte conservano la loro sezione.
  L'ID `archive` e l'alias storico `Archivio PDF` rimangono compatibili.
- I clic delle card e della ricerca nell'intestazione usano ID stabili.
  I vecchi eventi numerici delle card mantengono il loro ordine precedente.
  Icone, descrizioni, stato attivo e intera superficie cliccabile sono conservati.
- Le copertine sono in una griglia responsive soltanto nella pagina PDF.
  Le date curate più recenti precedono quelle mancanti o non valide.
  Titolo e copertina aprono il lettore esistente; una miniatura non disponibile
  lascia una card neutra. Rassegna conserva la sua ricerca e i consigli.
- Podcast offre l'argomento facoltativo richiesto. Campo vuoto: selezione generale
  bilanciata esistente. Con tema: ricerca semantica corpus-wide e ranking
  esistenti, alternanza delle edizioni pertinenti, deduplicazione conservativa
  nella stessa edizione, passaggi interi e budget invariati.
- Una sola pipeline prepara e valida il copione autonomo, senza creare Briefing.
  Il tema è un dato nel prompt, separato dalle istruzioni. Il modello deve astenersi
  quando mancano notizie pertinenti e non aggiungere altri temi per riempire l'audio.
  Introduzione e conclusione accompagnano i fatti con prove verificate.
- Cache copioni v2 distinta per tema normalizzato (Unicode, spazi e maiuscole),
  corpus corrente, configurazione, strategie e modello testo/embedding.
  Cache audio distinta anche per modello TTS e voce. Un hit evita nuove richieste.
  I copioni v1, il relativo contesto audio e gli episodi storici restano leggibili.
  Il retry esplicito usa il copione salvato, anche se il campo tema viene cambiato.
- Consensi testo e audio entrambi richiesti prima delle richieste. Nessuna API
  durante digitazione, cambio sezione o consultazione. Nessun retry automatico.

## File toccati

Applicazione: `edicola/product_navigation.py`, `edicola/editorial_components.py`,
`edicola/header_ui.py`, `edicola/experience_ui.py`, `edicola/archive_ui.py`,
`edicola/archive_components.py`, `edicola/reading_ui.py`, `edicola/podcast_ui.py`,
`edicola/podcast_draft.py`, `edicola/standalone_podcast.py`.

Test: `tests/test_edicola_topics.py` (nuovo), `tests/test_pdf_viewer.py`,
`tests/test_archive_design.py`, `tests/test_podcast_ui.py`.
Documentazione: `README.md`, `AGENTS.md`, questo resoconto.

`app.py` non richiede cambiamenti: monta già il solo prodotto attivo tramite ID.
Lettore PDF, autenticazione e Profilo a destra riutilizzati. Nessuna modifica
alle pipeline comuni di retrieval, ai modelli, al Briefing, a Timeline o Mappe.
Nessuna eliminazione di dati o migrazione. Le altre modifiche locali preesistenti,
incluse le rimozioni già segnalate da Git in `deployment/seed`, non sono state toccate.

## Verifiche

Esito: **198 casi distinti superati**. Suite principale: 196 passati; dopo
l'aggiunta dei controlli di navigazione reale e Rassegna, modulo tematico:
25 passati (23 già compresi nella suite). Solo avvisi di deprecazione delle
dipendenze. `git diff --check` sui file tracciati interessati senza errori.

Suite offline con mock SDK, corpus e PDF sintetici esclusivamente temporanei:
`test_edicola_topics`, `test_standalone_podcast`, `test_podcast`, `test_podcast_ui`,
`test_consent`, `test_editorial`, `test_pdf_viewer`, `test_archive_design`,
`test_reader_revision` e il controllo di consultazione offline dei prodotti
personali in `test_personalization`.

Verificati avvio/alias, callback delle sette card e conservazione dello stato,
ordinamento e apertura delle copertine, assenza della griglia nella Rassegna,
generale senza embedding, selezione semantica tematica da più edizioni,
cache distinte e normalizzate, assenza di fonti, retry audio senza testo/retrieval,
compatibilità v1, indipendenza dal Briefing e doppio consenso.
CSS responsive e callback verificati offline; AppTest non renderizza il browser.

Controlli manuali ancora consigliati: griglia e card a 320/390 px e desktop,
copertina/titolo e ritorno dal lettore, pagine PDF e fonti, accesso Profilo,
navigazione con bozze e risultati esistenti. Generazione reale, qualità semantica
sul corpus locale e qualità della voce non verificate: nessuna API reale usata.
Nessun commit, push, deploy o modifica del corpus/indice/credenziali.
