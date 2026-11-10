# Edicola Digitale Intelligente

Leggi i quotidiani disponibili, esplora le notizie e ritrova le pagine originali.

**Anteprima frontend (branch Docker):** intestazione testuale essenziale,
barra di navigazione compatta e scorrevole, menu Streamlit ridotto e
impaginazione adatta anche al tablet. Le funzioni dei prodotti e i dati
non cambiano. Per visualizzarla online con i quotidiani del corpus gia
presente nel repository, vedi [Docker e anteprima Codespaces](DOCKER.md).


Sotto l’intestazione, tutte le sezioni mostrano le sette card dei prodotti, ciascuna
con icona, titolo e descrizione. L’intera scheda è cliccabile e quella attiva è
evidenziata in blu. La griglia si adatta agli schermi piccoli senza duplicarsi
nella Home. Il logo è a sinistra nell’intestazione; le icone di ricerca e
**Profilo** sono a destra, con disposizione adattabile agli schermi piccoli.
Il profilo e l’accesso Google
sono disponibili soltanto dal menu Profilo. La pagina iniziale ? **In edicola**:
**Sfoglia i quotidiani e scopri le edizioni disponibili.** Le copertine formano
una griglia, con le edizioni datate pi? recenti per prime; copertina e titolo
aprono il lettore originale. La griglia compare soltanto in questa sezione. Nella Rassegna basta scrivere in **Cerca una notizia o un argomento**
e premere Invio o Cerca. La ricerca avviene nelle edizioni disponibili; se hai
già autorizzato le funzioni AI, all’invio può cercare anche per significato.
Durante la digitazione non vengono inviate richieste. Il Briefing conserva la
scelta esplicita delle fonti.
[Resoconto della semplificazione dell’interfaccia](UI_SIMPLIFICATION.md).
Nelle mappe puoi selezionare direttamente un nodo per leggere collegamenti e
fonti, senza generare nuovi contenuti. Le fonti
riportano quotidiano, data dell’edizione e pagina. Le date relative nella
Timeline vengono completate soltanto con riferimenti non ambigui e metadati
verificati; gli altri sviluppi sono disponibili nell’area **Altri sviluppi**.
[Correzioni funzionali e stato delle verifiche](FUNCTIONAL_FIXES.md).

## Le sezioni

- **In edicola**: sfoglia i quotidiani, ingrandisci le pagine e scarica gli originali.
- **Rassegna stampa**: cerca una notizia o esplora le letture disponibili.
  I risultati indicano quotidiano e data e aprono il PDF alla pagina corretta.
  I titoli vengono mostrati soltanto se verificati; altrimenti trovi un estratto
  originale con un’etichetta neutra.
- **Chat AI**: fai domande sulle edizioni disponibili e consulta le fonti delle risposte.
- **Briefing**: scegli un tema e le fonti per ottenere una lettura organizzata per notizie,
  con citazioni e collegamenti alle pagine PDF. In **Letture già disponibili** puoi
  consultare anche gli approfondimenti salvati in precedenza. I filtri non modificano
  una lettura già preparata: serve un nuovo invio per aggiornarla.
- **Timeline**: segui una sequenza verticale di eventi con data verificata.
  Una linea continua e un marker accompagnano ogni evento, con data, sintesi e
  fonte apribile. Gli sviluppi senza data certa sono nell’area espandibile
  **Altri sviluppi**, separati dalla cronologia. Le sintesi lunghe sono espandibili;
  dettagli temporali e testi originali sono disponibili su richiesta.
- **Mappe concettuali**: esplora fino a dieci concetti nel grafo o usa l’Elenco.
  Seleziona un nodo per aprire dettagli, collegamenti e fonti. Gli archi mostrano
  soltanto relazioni già documentate; i temi comuni sono distinti dalle relazioni
  fattuali. La mappa si può scorrere anche sugli schermi piccoli.
- **Podcast**: premi **Genera podcast** per un episodio dalle notizie indicizzate,
  senza preparare prima un Briefing. Il campo **Di cosa vuoi ascoltare le notizie?**
  ? facoltativo: vuoto prepara una selezione generale; con un argomento cerca
  le notizie pertinenti anche per significato, nelle diverse edizioni indicizzate.
  Se mancano fonti adeguate non viene prodotto un episodio.
  Puoi ascoltarlo, scaricarlo e consultare testo e fonti. Gli episodi precedenti
  restano disponibili. Se fallisce l’audio, il copione resta pronto per un retry manuale.
- **Il mio profilo**: interessi, letture salvate, briefing personali e privacy.

## Fonti e autorizzazioni

Le citazioni numerate rimandano a pulsanti che aprono il quotidiano alla pagina
corretta. I passaggi originali sono consultabili separatamente. Una pagina non
più disponibile nell’archivio attuale non viene sostituita con un’altra edizione.
Le date delle edizioni non diventano date degli eventi. La copertura può essere
parziale e non comprende verifiche delle notizie in tempo reale.

Per ogni nuovo invio i prodotti considerano tutto il corpus indicizzato corrente,
rispettando gli eventuali filtri sulle fonti. I contributi pertinenti delle diverse
edizioni vengono alternati e selezionati entro uno spazio complessivo: il numero
dei passaggi non è più fermato a tre, cinque o otto. Si usano passaggi interi,
senza inviare PDF completi e senza aggiungere chiamate AI per ogni giornale.
**Edizioni incluse nella lettura** distingue le fonti presenti da quelle citate;
un avviso segnala gli altri contenuti esclusi per lo spazio disponibile. Le schede
della Rassegna sono una selezione espandibile delle letture pertinenti.
Nelle Timeline e nelle Mappe questo riepilogo è nel menu discreto **Fonti
consultate**; **Leggi la fonte** apre il testo di riferimento. Il PDF resta
accessibile dal pulsante con quotidiano, data dell’edizione e pagina.
[Resoconto della presentazione editoriale](EDITORIAL_VISUALS.md).

Il Podcast prepara un copione autonomo dai passaggi selezionati del corpus e
ne conserva le fonti PDF. Preparazione e audio richiedono autorizzazioni distinte;
il consenso testuale è aggiornato per comprendere questo uso. I Podcast storici
derivati da letture restano consultabili. Navigare e ascoltare episodi già pronti
non avvia richieste AI. [Flusso Podcast e verifiche offline](PODCAST_STANDALONE.md).
[Nuova pagina iniziale e Podcast tematici](IN_EDICOLA_TOPICS.md).

Le generazioni richiedono un invio esplicito e l’autorizzazione prevista.
Navigare, leggere un risultato esistente o aprire una fonte non avvia generazioni.
Le autorizzazioni per testi, briefing personali e audio restano separate.
Il salvataggio delle chat nell’account è facoltativo; le chat degli ospiti
rimangono temporanee. Le letture generali sono condivise, i dati del profilo
sono riservati all’account. Nella modalità dimostrativa locale le preferenze
sono condivise su quella installazione, come indicato nell’app.

## Verifica dell’interfaccia

Usare risultati già disponibili senza nuovi invii:

1. Dalla Rassegna cercare un tema e premere Invio: i risultati cambiano soltanto
   all’invio. Controllare fonti e pagina PDF, poi cambiare sezione e tornare.
2. Aprire una lettura precedente, anche un approfondimento, e controllare citazioni,
   passaggi originali e pagina PDF. Cambiare sezione e tornare.
3. Provare Timeline, Mappe ed Elenco, un concetto collegato e uno isolato.
4. Aprire un ascolto già disponibile e controllare testo, fonti e download.
5. Ripetere a 1440, 768, 390 e 320 px: testi a capo, pulsanti da tastiera e touch,
   espansioni, navigazione e lettore PDF. Verificare i flussi di errore senza
   esporre dettagli tecnici o attribuire all’utente problemi del servizio.

## Acquisizione intelligente dei PDF (opzionale)

PyMuPDF migliora l'estrazione strutturata dei nuovi PDF; una CLI separata può
analizzare con Gemini Vision le prime pagine e i richiami, verificare i titoli
contro il testo originale e associare i chunk agli articoli quando possibile.
Nessuna chiamata Vision durante la navigazione; l'analisi richiede una
specifica autorizzazione da CLI. I PDF già presenti possono essere rielaborati
localmente solo con comando esplicito e backup. [Guida e comandi](PDF_INTELLIGENT_RETRIEVAL.md).

## Documentazione del progetto

Per sviluppo e manutenzione consultare [il diario tecnico](DEVELOPMENT_HISTORY.md),
[la guida archivio](GESTIONE_ARCHIVIO.md), [gli account](ACCOUNTS.md),
[la cronologia chat](CHAT_HISTORY.md), [il deployment](DEPLOYMENT.md)
e [la valutazione sperimentale](evaluation/README.md).
Per eseguire l'applicazione localmente in un container, consultare la [guida Docker](DOCKER.md).
L'avvio abituale con Streamlit rimane disponibile; Docker non include PDF, indici o segreti.
Il [resoconto dell’unificazione](CONSUMER_APP.md) confronta i prodotti,
indica i file e i test pertinenti e descrive la compatibilità dei risultati salvati.
Nessun aggiornamento dei dati o pubblicazione avviene tramite queste istruzioni.

Per l’ultima revisione funzionale e i limiti dei controlli offline consultare
[il resoconto di Rassegna, Timeline e Mappe](READER_REVISION.md).
