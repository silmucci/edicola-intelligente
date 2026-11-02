# Edicola Digitale Intelligente

Leggi i quotidiani disponibili, esplora le notizie e ritrova le pagine originali.

La navigazione usa un selettore compatto delle sezioni editoriali. Logo, menu
**Profilo** e ricerca sono in alto a sinistra. Il profilo e l’accesso Google
sono disponibili soltanto dal menu Profilo; la Home apre direttamente sulle
edizioni e sulle letture. I filtri per intervallo di date non sono presenti:
puoi scegliere le singole edizioni e limitarti alle più recenti della selezione.
[Resoconto della semplificazione dell’interfaccia](UI_SIMPLIFICATION.md).
Nelle mappe, **Esplora un concetto** mostra i
collegamenti del concetto scelto senza generare nuovi contenuti. Le fonti
riportano quotidiano, data dell’edizione e pagina. Le date relative nella
Timeline vengono completate soltanto con riferimenti non ambigui e metadati
verificati; gli altri sviluppi rimangono in **Senza data**.
[Correzioni funzionali e stato delle verifiche](FUNCTIONAL_FIXES.md).

## Le sezioni

- **Rassegna stampa**: copertine, estratti e letture. Filtra per parole chiave,
  edizioni, date e ambito; porta la selezione nel Briefing senza avviare generazioni.
- **Archivio PDF**: sfoglia i quotidiani, ingrandisci le pagine e scarica gli originali.
- **Chat AI**: fai domande sulle edizioni disponibili e consulta le fonti delle risposte.
- **Briefing**: scegli un tema e le fonti per ottenere una lettura organizzata per notizie,
  con citazioni e collegamenti alle pagine PDF. In **Letture già disponibili** puoi
  consultare anche gli approfondimenti salvati in precedenza. I filtri non modificano
  una lettura già preparata: serve un nuovo invio per aggiornarla.
- **Timeline**: segui una sequenza verticale di eventi con data verificata.
  Gli sviluppi senza data verificabile sono raccolti in fondo in **Senza data**,
  nell’ordine dei passaggi recuperati. Le sintesi lunghe sono espandibili;
  dettagli temporali e testi originali sono disponibili su richiesta.
- **Mappe concettuali**: esplora fino a dieci concetti nel grafo o usa l’Elenco.
  Apri il controllo con il nome del concetto per leggere dettagli, collegamenti
  e fonti. I temi comuni sono distinti dalle relazioni fattuali; i nodi del
  grafico non simulano collegamenti cliccabili.
- **Podcast**: ascolta estratti delle letture già disponibili, compresi gli
  approfondimenti precedenti. Puoi consultare il testo letto e le fonti.
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

Il Podcast conserva le fonti delle sezioni lette dal Briefing, senza cercare nuove
notizie. I risultati precedenti restano consultabili: per applicare il nuovo
criterio serve un nuovo invio esplicito. [Dettagli e verifiche](CORPUS_CONTEXT.md).

Le generazioni richiedono un invio esplicito e l’autorizzazione prevista.
Navigare, leggere un risultato esistente o aprire una fonte non avvia generazioni.
Le autorizzazioni per testi, briefing personali e audio restano separate.
Il salvataggio delle chat nell’account è facoltativo; le chat degli ospiti
rimangono temporanee. Le letture generali sono condivise, i dati del profilo
sono riservati all’account. Nella modalità dimostrativa locale le preferenze
sono condivise su quella installazione, come indicato nell’app.

## Verifica dell’interfaccia

Usare risultati già disponibili senza nuovi invii:

1. Dalla Rassegna impostare i filtri e premere **Prepara il briefing della selezione**:
   si apre il Briefing con gli stessi filtri, senza generare contenuti.
2. Aprire una lettura precedente, anche un approfondimento, e controllare citazioni,
   passaggi originali e pagina PDF. Cambiare sezione e tornare.
3. Provare Timeline, Mappe ed Elenco, un concetto collegato e uno isolato.
4. Aprire un ascolto già disponibile e controllare testo e fonti.
5. Ripetere a 1440, 768, 390 e 320 px: testi a capo, pulsanti da tastiera e touch,
   espansioni, navigazione e lettore PDF. Verificare i flussi di errore senza
   esporre dettagli tecnici o attribuire all’utente problemi del servizio.

## Documentazione del progetto

Per sviluppo e manutenzione consultare [il diario tecnico](DEVELOPMENT_HISTORY.md),
[la guida archivio](GESTIONE_ARCHIVIO.md), [gli account](ACCOUNTS.md),
[la cronologia chat](CHAT_HISTORY.md), [il deployment](DEPLOYMENT.md)
e [la valutazione sperimentale](evaluation/README.md).
Il [resoconto dell’unificazione](CONSUMER_APP.md) confronta i prodotti,
indica i file e i test pertinenti e descrive la compatibilità dei risultati salvati.
Nessun aggiornamento dei dati o pubblicazione avviene tramite queste istruzioni.
