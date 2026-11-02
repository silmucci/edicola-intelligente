# Semplificazione dell’interfaccia

Questo intervento riguarda esclusivamente la presentazione. Prima di modificare
i file sono stati letti AGENTS.md e README, controllati git status e git diff,
ed esaminati i punti di ingresso delle sezioni. Non sono stati eseguiti test,
avviata l’app, effettuate chiamate esterne o ripetute le prove editoriali.

## Già presente prima di questo intervento

- Briefing era già l’unico generatore editoriale generale nella UI. Dossier
  e Infografiche non erano presenti nelle destinazioni né nei pulsanti di
  generazione. Dossier restava soltanto nella compatibilità dei risultati.
- Erano già presenti un selettore nativo compatto, Timeline verticale,
  scelta nominativa del concetto nella mappa e fonti con quotidiano/data/pagina.
- I contatori dell’archivio, gli identificativi e la diagnostica erano già
  protetti dalla configurazione di sviluppo. Non è stato aggiunto un nuovo
  interruttore per il lettore e gli strumenti interni non sono stati cancellati.
- Il repository conteneva modifiche non committate a ricerca, validatori,
  interfaccia e test, oltre alle cancellazioni/accessi negati sotto
  `deployment/seed/`: il lavoro preesistente è stato conservato.

## Modifiche di questo intervento

- Logo su una riga propria, con Profilo e Cerca sotto, allineati a sinistra,
  senza le precedenti colonne laterali dell’intestazione.
- Unico menu Profilo nell’intestazione, con il richiamo ai controlli nativi
  esistenti per Google. Rimossi i controlli duplicati dalle pagine profilo e
  il profilo dalle opzioni del selettore editoriale e dai risultati di ricerca
  delle sezioni. La destinazione interna rimane accessibile dal menu Profilo.
- Rimosse dalla Home le card che duplicavano tutte le destinazioni. Restano
  copertine, estratti, rassegna, consigli e l’azione che apre Briefing con la
  selezione corrente, senza generare.
- Rimossi i selettori «Edizioni dal/fino al» e l’avviso sull’intervallo. Vecchi
  valori di questi due filtri vengono eliminati dalla sola sessione affinché
  non agiscano come filtri nascosti. Restano tema, singole edizioni, ambito e
  scelta delle più recenti. La struttura dei filtri storici non cambia.
- Eliminato l’espansore «Informazioni su questa edicola dimostrativa».
  Le informazioni su privacy, autorizzazioni e natura condivisa del profilo
  dimostrativo restano nelle rispettive aree.
- I titoli storici che iniziano con il nome del vecchio prodotto vengono
  presentati come «Approfondimento» nelle scelte di lettura e ascolto.
  Nessun titolo o testo persistente viene riscritto e nessuna citazione cambia.
- Opzioni qualitative per la quantità di letture da mostrare; Podcast senza
  conteggio di parole/sezioni, con durata stimata e avviso quando è un estratto.
  Ridotte le spiegazioni ripetute nella Home e nella mappa e il linguaggio
  tecnico nella Timeline e nello stato di apertura dell’archivio.

## File modificati in questo intervento

| File | Modifica |
| --- | --- |
| `app.py` | Rimozione espansore informativo e testo di caricamento |
| `edicola/header_ui.py` | Intestazione a sinistra, profilo unico, ricerca |
| `edicola/product_navigation.py` | Selettore editoriale separato dalla rotta profilo |
| `edicola/press_review_ui.py` | Rimozione intervallo date, etichette delle letture |
| `edicola/experience_ui.py` | Home senza card di navigazione duplicate |
| `edicola/account_ui.py` | Rimozione accesso Google duplicato |
| `edicola/personalization_ui.py` | Rimozione controlli account duplicati e titoli storici |
| `edicola/design.py` | Etichetta di presentazione dei titoli storici |
| `edicola/reading_ui.py` | Uso dell’etichetta nelle letture salvate |
| `edicola/podcast_ui.py` | Etichette storiche e indicazioni di ascolto più semplici |
| `edicola/knowledge_views.py` | Testi più brevi per Timeline e dettagli della mappa |
| `README.md` | Descrizione aggiornata dell’interfaccia |
| `UI_SIMPLIFICATION.md` | Questo resoconto |

## Compatibilità e limiti della verifica

Restano i lettori delle cache storiche, i risultati Dossier salvati, la relativa
rotta di sessione reindirizzata a Briefing, la struttura dei filtri con date e
i componenti interni non montati nella Home. Nessuna migrazione o cancellazione.
Il componente condiviso delle card continua a servire gli estratti in evidenza.
I controlli di sviluppo restano accessibili soltanto nella modalità già prevista.

Fonti, PDF, citazioni, consensi, autenticazione, corpus, indicizzazione,
embedding, modelli e logiche RAG non sono stati modificati in questo intervento.
Le precedenti modifiche funzionali presenti nel diff non sono attribuibili a
questa semplificazione.

La verifica svolta è una lettura statica dei file e dei diff. **Non sono stati
eseguiti test né verifiche visive o interattive**. Restano da controllare su
desktop e smartphone l’allineamento reale dell’intestazione, il passaggio fra
Profilo e sezioni, il flusso Google, la ripresa delle bozze e delle letture
storiche e l’apertura dei PDF. I test preesistenti legati ai vecchi controlli
o alle card non sono stati aggiornati né eseguiti in questo intervento.
Nessun commit, push o deploy.
