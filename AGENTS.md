# Regole del progetto

- Mappe Task 14.4: rifiniture di sola presentazione, senza nuova selezione o AI.
  Etichette nominali compresse conservativamente, mai troncamenti con ellissi:
  preservare date, importi, beneficiari, negazioni e modalità; nomi propri e
  formulazioni non riconosciute completi a capo. Originale sempre nei dettagli.
  Gruppi visuali soltanto per tipi validati presenti, senza archi sintetici o
  invisibili. Ogni concetto ha un controllo nominativo per dettagli e fonte PDF
  verificata. Grafo/Elenco alternativi; usare anche cache esistenti senza nuove
  generazioni o invalidazioni per il solo rendering.

- Timeline Task 14: distinguere cronologia con data evento verificata da sviluppi
  senza data, ordinati esplicitamente per passaggi recuperati. Annunci, decisioni
  e proposte si classificano dalle prove originali, mai dalla pubblicazione o
  soltanto dalla parafrasi AI. Stato vuoto unico; dettagli temporali secondari.
  Budget invariato e chunk interi anche per timeline; saltare i passaggi troppo
  grandi senza perdere automaticamente quelli successivi. Strategie di cache
  temporale/editoriale e mappa versionate separatamente. Viste e risultati RAM
  separati per prodotto, nessuna API al cambio vista. Mappe con massimo dieci nodi,
  nodo evidenziato per pertinenza editoriale, legenda ed elenco alternativo;
  senza archi, raggruppamento visuale dei soli concetti verificati con argomento
  dichiaratamente navigazionale e nessun collegamento fattuale. Elenchi nominali
  di proposte estratti solo da frasi complete nei passaggi selezionati, con prove
  letterali rivalidate; mai mascherare errori API/formato con il recupero locale.
  Scadenze di misure non diventano date dell'evento che le propone;
  nuove categorie non allentano citazioni o predicati. Vicini distinti anche per
  file/pagina/configurazione e articolo quando identificato, senza inferire che
  continuità di pagina implichi appartenenza allo stesso articolo.

- Mappe Task 14.3: validità delle prove e pertinenza sono controlli separati.
  Selezione locale dai soli chunk indicizzati, destinatari/luoghi espliciti e
  alias lessicali versionati soltanto per ranking, mai per validare citazioni.
  Una query embedding per invio, nessuna quota per PDF nelle mappe, budget e
  limite dei passaggi invariati. Conservare isolati pertinenti anche con archi;
  pertinenza/utilità prima del grado dei nodi. Predicati generici verificati
  soltanto nei dettagli; niente archi fuori tema. Contesto fra chunk solo con
  prove contigue già validate. Grafico centrato con dimensioni intrinseche, senza
  stretch o altezza forzata. Versionare cache JSON e risultati RAM; niente
  rigenerazioni automatiche. Diagnostica completa solo nello sviluppo, log con
  soli conteggi/cause. Timeline: filtro di destinatari/luoghi espliciti senza
  modificare date, classificazioni o validatori.

- Design Task 13: token condivisi in `design_tokens.py`, tema bianco/blu con
  accento rosso, font di sistema senza CDN. Header unico con ricerca testuale
  locale su funzioni/edizioni/chunk indicizzati; nessun embedding. Ricerca nel
  namespace privato della sessione, cancellata al cambio identità. Nove destinazioni
  in `product_navigation.py`, nomi/ordine condivisi fra card e navigazione nativa
  con wrapping. Montare solo il prodotto attivo; conservare risultati e input
  esplicitamente elencati, mai pulsanti, conferme distruttive o vecchi invii pendenti.
  Card dei prodotti soltanto nella Rassegna stampa. Mappe: Grafo/Elenco alternativi,
  etichette abbreviate senza riscrittura, fonti editoriali e prove su richiesta;
  diagnostica solo in pannelli di sviluppo. Asse temporale soltanto per date evento
  verificate; card senza asse per gli sviluppi non datati, dettagli su richiesta.
  Card e caroselli v2 con CSS isolato, breakpoint fluidi e scorrimento interno
  touch; testi dinamici via `textContent`, indici degli eventi verificati lato
  server. Nessun selettore DOM globale o HTML attivo dei documenti. Copertine
  autentiche con proporzioni conservate, filtri solo su date curate e fascia
  In evidenza con estratti letterali, senza titoli o attualità inventati.

- Chat: un solo `st.chat_input`, invio esplicito e domanda subito nello storico;
  richiesta pendente consumata una sola volta anche dopo consenso. Rerun, errori,
  rifiuti e interruzioni non ritentano le API. Rendering Markdown escapato con
  HTML disabilitato, apostrofi leggibili e soli link di citazione creati dal codice.
  Date del chatbot esclusivamente dai metadati curati delle edizioni recuperate;
  avvisi di copertura per domande attuali, mai scambiare pubblicazione/evento,
  previsione/esito o archivio/verifica in tempo reale. Non cambiare prompt degli
  altri prodotti né il validatore delle evidenze per migliorare la fluidità.
- Conversazioni: ospiti solo RAM (20 chat), account su PostgreSQL soltanto con
  opt-in distinto dal consenso Gemini; massimo 200 chat/100 turni per chat/10 MB
  di messaggi per account. Nessuna importazione automatica delle chat temporanee.
  Contesto della sola chat attiva: massimo 6 messaggi/4000 byte UTF-8, mai prove;
  retrieval nuovo a ogni invio. Salvataggio atomico e idempotente per coppia di
  messaggi completata; errori di scrittura espliciti e retry solo manuale del DB.
  Fonti compatte per PDF/pagina, riferimenti persistenti hash/chunk e controlli
  di versione prima dell'apertura. Navigazione e ripresa mai chiamano Gemini.

- Autorizzazioni web centralizzate in `consent`/`consent_ui`: finalità versionate
  distinte per testo generale, briefing personale e audio; account su PostgreSQL,
  ospiti soltanto in sessione. Nessuna scelta preselezionata, fallback ospite per
  account o generazione automatica. Ogni richiesta SDK passa da `api_guard`, con
  verifica aggiornata di scelta e identità anche prima dei retry. Logout cancella
  scelte ospiti e azioni pendenti. Cambi materiali richiedono una nuova versione.
- Migrazioni già applicate immutabili: nuove tabelle con migrazioni additive,
  transazionali, RLS forzata e ownership. Mai applicarle automaticamente.

- Prototipo universitario: Python, Streamlit e pypdf; mantenere i moduli piccoli e leggibili.
- I PDF provengono esclusivamente da `data/incoming/`: acquisizione automatica, consultazione e chat sui testi, nessun upload.
- Riutilizzare le estrazioni persistenti tramite SHA-256, inclusi gli esiti negativi e i duplicati.
- Conservare nome file, pagina (da 1) e totale pagine; isolare gli errori dei documenti.
- Pulizia e chunking devono riusare il testo estratto: chunk per pagina, circa 1000 caratteri e overlap 150, con metadati e ID deterministici.
- Persistenza dei chunk per hash e configurazione; incrementare `PIPELINE_VERSION` se cambiano pulizia o algoritmo, ed escludere esplicitamente pagine prive di testo o con errori.
- Embeddings documenti (`google-genai`, `gemini-embedding-2`, 768 dimensioni) solo tramite comando esplicito con limite e autorizzazione; mai indicizzazione automatica da Streamlit. Embeddings delle domande solo dopo azione e autorizzazione esplicite nella ricerca o nel RAG.
- ChromaDB locale in `data/chroma/`, embedding function disabilitata; nessun modello locale o OCR.
- RAG tramite `semantic_search` e Gemini Flash (`GEMINI_RAG_MODEL`): inviare domanda e passaggi solo dopo invio esplicito e autorizzazione, mai all'apertura di Streamlit. Non reindicizzare durante le domande.
- Separare istruzioni e documenti non attendibili; validare ID delle fonti ed evidenze letterali nel codice. Se la risposta non è verificabile, dichiarare informazioni insufficienti.
- Dossier e briefing solo su invio autorizzato: fonti realmente indicizzate, budget limitato, cache persistente per modello/configurazione/fonti e validazione RAG riutilizzata. Bilanciare edizioni nel briefing e segnalare copertura parziale; non inferire testate o date mancanti.
- Timeline e mappe separate dai prodotti esistenti: validare date ed evidenze; completare un anno solo con l'edizione verificata della fonte e contesto non ambiguo, controllando calendario, giorni settimanali e cambio d'anno. Distinguere data esplicita/completata/non determinabile, pubblicazione/evento e annunci/fatti avvenuti. Niente cronologia per date inaffidabili o causalità inferita. Cache JSON separata con versione temporale solo timeline, nessuna scrittura nei database esistenti e nessuna generazione automatica.
- Mappe: massimo dieci nodi nella vista, layout compatto e raggruppamento visuale senza archi se mancano relazioni, con elenco alternativo. Relazioni letterali con modificatori controllati, senza attraversare altri soggetti; temi comuni documentati per entrambi gli estremi, mai sola co-occorrenza. Conservare le prove degli archi e distinguere le cause degli scarti con soli conteggi nei log. Versionare separatamente la strategia mappa.
- Mappe: separare etichetta proposta e predicato letterale verificato; mostrare solo quest'ultimo. Distinguere candidate/accettate/escluse e cause specifiche. Vicini solo già indicizzati, stessa pagina e continuità verificata da hash/configurazione/posizioni/offset/overlap; citazioni distribuite senza testo mancante, con entrambi i riferimenti. Mantenere chunk interi nel budget e cache/versione dei vicini solo per le mappe.
- Podcast soltanto da briefing/dossier validi nella cache editoriale in sola lettura: copioni estrattivi di sezioni complete, massimo 240 parole/3500 caratteri, senza riscrivere fatti o numeri. Fonti PDF/pagina/chunk separate dalla lettura; segnalare estratti e archivio parziale. Gemini TTS cloud (`GEMINI_TTS_MODEL`, default `gemini-3.8-flash-lite-tts`) solo dopo invio autorizzato; nessun nuovo prodotto, embedding o chiamata automatica. SDK >=2.25, metadata vocali separati dal testo, WAV validato e cache dedicata per testo/modello/voce con provenienza separata. Nessun retry automatico, attivazione di fatturazione o fallback a servizi a pagamento.
- Briefing con prompt autonomo: mantenere tutto il campione nel budget, validare da 1 a 8 notizie singolarmente senza cambiare il chatbot; distinguere astensione, errori di formato/citazioni e troncamento. Versionare solo la strategia briefing e non salvare nuovi esiti negativi in cache.
- Test API esclusivamente con mock; non stampare chiavi, richieste o errori SDK grezzi. Il controllo `--dry-run` deve funzionare senza rete e senza chiavi.
- Personalizzazione: account cloud con Google OIDC nativo e PostgreSQL Supabase; identità soltanto da issuer/subject verificati, mai email o flag client. CRUD parametrizzato e transazionale con ownership su ogni operazione, ruolo minimo senza bypass RLS, schema privato e RLS forzata. Nessun fallback demo nel pubblico se manca configurazione. SQLite demo soltanto su Windows con `EDICOLA_PROFILE_MODE=local_demo`, mai importato negli account. Consigli locali su chunk già indicizzati. Briefing personali con generatore/validatore esistenti e cache PostgreSQL per proprietario; Gemini/TTS solo su consenso e invio espliciti, senza inviare ID/salvati/storico al modello. Export e cancellazione dei soli dati propri; audio temporanei isolati in `.private-runtime/`, senza toccare corpus o cache generali. Non versionare dati personali.
- Non versionare PDF, testo estratto, database, credenziali o ambienti virtuali.
- Valutazione sperimentale separata dall'app: snapshot indicizzato e annotazioni manuali collegate da hash, nessuna etichetta o risposta di riferimento inventata. Distinguere misure reali, simulate e mancanti; non equiparare controllo tecnico delle citazioni ad accuratezza fattuale. Benchmark API solo con comando, limite e autorizzazione espliciti, contando anche i retry; nessuna modifica a indice o pipeline. Schede umane con criteri, prove e punteggi vuoti; risultati e cataloghi privati esclusi dal versionamento.
- Eseguire `python -m pytest -q` dopo modifiche all'acquisizione e aggiornare il README se cambia il comportamento.
- UI con nove destinazioni autonome, mantenendo consensi, bozze e risultati durante la navigazione. Lettore locale PDFium delle pagine originali, cache RAM limitata e accesso al motore serializzato; nessun OCR, CDN o servizio esterno. Aprire soltanto PDF acquisiti dentro `data/incoming/`, verificando percorso, SHA, pagina e chunk della versione corrente; rifiutare fonti obsolete e percorsi arbitrari/symlink. Download dei byte originali. Nessuna chiamata Gemini associata a navigazione, fonti o zoom.
- Archivio cliente: galleria di copertine reali e soli metadati verificati in `data/editions.json`, con etichette neutre quando mancanti. Lettore centrato, pagina intera adattata a 70vh e massimo iniziale 520px, zoom locale e scorrimento interno, ritorno alla galleria. CSS isolato nei componenti v2, mai selettori globali delle altre schede. Hash, nomi tecnici, chunk, testo completo, stati e tabelle solo in diagnostica attivata da configurazione `EDICOLA_ARCHIVE_DIAGNOSTICS=1`, disattivata di default e senza interruttore cliente.
- Home e consigli: selezione esclusivamente locale di fonti indicizzate, schede con estratti letterali esplicitamente distinti da titoli di articoli, niente metadati o immagini inventati. Controlli nativi con wrapping, tema locale e CSS della sola introduzione limitato alla sua classe. Chat multiple con contesto limitato e cronologia account opt-in, nessuna chiamata su bozza o navigazione. Login/logout nativi Streamlit; al cambio identità svuotare dati privati della sessione prima di montare i controlli. Nessuna cache globale di profili, export o briefing personali. Export/audio personali via payload della sessione e Blob URL del browser, senza URL media pubblici condivisi. Nascondere ID di chunk e diagnostica nella vista cliente, conservando le citazioni PDF/pagina e i passaggi verificabili.
# Deployment dimostrativo

- Cloud solo su pubblicazione esplicita dell'utente: mai push, PDF o Secrets automatici.
- Con `EDICOLA_CLOUD_DEMO=1` usare soltanto snapshot autorizzati e verificati; ripristino
  isolato da vettori esistenti, nessuna estrazione o generazione embeddings implicita.
- Escludere dati locali/profili/cache e credenziali da Git. Corpus pubblico solo se autorizzato;
  dati personali su PostgreSQL per proprietario, file audio runtime effimeri. Migrazioni,
  account esterni e credenziali si configurano manualmente: mai provisioning o deployment automatici.

