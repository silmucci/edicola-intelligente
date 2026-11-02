# Edicola Digitale Intelligente

**Mappe — Task 14.4:** etichette senza troncamenti, gruppi per tipo e dettagli
dedicati a ogni concetto, con pagina PDF originale verificata. Solo presentazione,
senza rigenerare risultati. [Comportamento e prova locale](MAPS_TASK14_4.md).

**Mappe — Task 14.3:** pertinenza distinta dalla verifica delle fonti, selezione
locale dei passaggi indicizzati, conservazione dei concetti isolati e grafici
con dimensioni intrinseche. [Diagnosi, limiti e verifiche](MAPS_TASK14_3.md).

**UI — Task 14.2:** nove destinazioni autonome, con nomi e ordine condivisi fra
card e barra di navigazione responsive. Mappe con Grafo/Elenco alternativi,
timeline sintetiche, fonti e dettagli su richiesta.
[Modifiche, test e checklist visiva](UI_TASK14_2.md).

**Timeline e Mappe — Task 14.1:** raggruppamento visuale anche senza archi,
stati vuoti distinti per fase e proposte nominali documentate senza date inventate.
[Diagnosi, test e verifica manuale](KNOWLEDGE_TASK14_1.md).

**Timeline e Mappe — Task 14:** cronologia soltanto per date evento verificate;
proposte, decisioni e annunci senza data in **Eventi e sviluppi documentati**, con
ordine di lettura esplicito. Card verticali, fonti compatte, mappe Graphviz con
elenco alternativo, passaggi interi nel budget e cache versionate separatamente.
[Comportamento, limiti e prova locale](KNOWLEDGE_TASK14.md).

**Design editoriale — Task 13:** nuova testata con ricerca locale, card dei prodotti,
copertine autentiche in carosello e fascia In evidenza con estratti documentati.
Tema bianco/blu, accenti rossi, font locali e layout adattivi; conservati account,
consensi, cronologia e prodotti AI. Nessuna nuova dipendenza o migrazione SQL.
[Componenti, limiti e checklist desktop/tablet/mobile](DESIGN_TASK13.md).

**Chat AI - Task 12.2:** conversazioni multiple con titoli modificabili, sidebar
nativa e un solo `st.chat_input`. La domanda compare subito e ogni invio viene
consumato una sola volta, anche dopo il consenso. Ospiti: conversazioni temporanee.
Account Google: cronologia PostgreSQL solo dopo una scelta esplicita, distinta dal
consenso Gemini. Applicare manualmente la nuova
[004_chat_history.sql](migrations/004_chat_history.sql), dopo 001/002/003.

La guida [CHAT_HISTORY.md](CHAT_HISTORY.md) descrive migrazione, privacy, limiti,
verifiche con due account e test su un secondo dispositivo. Lo storico della sola
chat attiva aiuta a interpretare i follow-up, ma ogni risposta recupera nuove fonti.
Il nuovo consenso testuale `text-v2` spiega questo trattamento e richiede una nuova
scelta; le autorizzazioni audio e briefing personali restano invariate.

Fonti compatte cliccabili per PDF/pagina, con etichette editoriali verificate o
neutre, aprono il documento originale. I passaggi sono secondari in un popover.
Hash e chunk salvati impediscono di aprire fonti appartenenti a versioni obsolete.

Il prompt del solo chatbot riceve le date ISO valide delle edizioni recuperate.
Per richieste di novità/ultimi aggiornamenti la finestra prudenziale è di sette
giorni; per oggi/attualmente/adesso si cercano date del giorno. È un criterio di
copertura, non prova che i fatti siano ancora attuali. Date assenti o future non
attestano aggiornamenti: un avviso esplicito segnala il limite. Nessuna ricerca
web o verifica in tempo reale viene effettuata. Le previsioni degli articoli
rimangono previsioni riferite al loro contesto, senza trasformare «entro due anni»
in una scadenza attuale. Il miglioramento della fluidità usa istruzioni al modello:
non riscrive le prove e non sostituisce la verifica giornalistica delle fonti.

Verifica manuale: avviare `python -m streamlit run app.py`, aprire Chat AI e inviare
una domanda con apostrofi, per esempio «Ci sono novità per la ricostruzione delle
case all'Aquila?». Controllare domanda immediata, consenso al primo invio, risposta,
date e collegamenti PDF; cambiare sezione e tornare senza nuove richieste.
Provare anche rifiuto/revoca e una domanda «oggi» su fonti datate. Su smartphone
verificare il composer unico sotto il riquadro scorrevole, Invio/Maiusc+Invio e
consultazione delle fonti. Dentro le schede Streamlit il composer è inline sotto
la conversazione, non fissato al fondo globale della finestra; non vengono usati
hack CSS. La verifica visiva sui dispositivi reali resta manuale.

**UX e autorizzazioni AI — Task 12:** [guida e checklist](UX_TASK12.md).
Dialogo al primo invio, scelte distinte per testi, briefing personali e audio,
revocabili nel profilo; account su Supabase, ospiti nella sola sessione.
Prima del rilascio applicare manualmente
[`003_ai_consents.sql`](migrations/003_ai_consents.sql), senza modificare 001/002.
Tema editoriale locale, selettori compatti, profilo organizzato e accesso diretto
alle pagine originali. Nessuna chiamata AI all'apertura delle sezioni.

**Account cloud — Task 11A:** configurazione completa in [ACCOUNTS.md](ACCOUNTS.md),
con Google OIDC, PostgreSQL Supabase, migrazione SQL, Secrets e prova con due utenti.
La modalità predefinita è `accounts`: senza configurazione l'Archivio resta consultabile,
ma non viene mostrato il vecchio profilo demo. Per il solo sviluppo Windows con SQLite
impostare esplicitamente `$env:EDICOLA_PROFILE_MODE="local_demo"` prima dell'avvio.

Task 1–9A.1 del prototipo universitario: acquisizione locale dei PDF, archivio editoriale con copertine e lettore delle pagine originali, pulizia, chunking, indicizzazione semantica, RAG, dossier, briefing, timeline, mappe concettuali, podcast editoriali, personalizzazione demo e valutazione sperimentale. La consultazione Streamlit e i consigli locali funzionano senza chiavi e senza chiamate esterne; indicizzazione, ricerca e prodotti Gemini richiedono azioni esplicite e autorizzazione.

## Avvio (PowerShell, Python 3.11 o successivo)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Aprire l'indirizzo locale indicato da Streamlit. L'installazione iniziale delle dipendenze richiede accesso al repository dei pacchetti. Il corpus resta locale; gli account personali, se configurati, usano Google OIDC e PostgreSQL Supabase.

## Acquisizione

Inserire le edizioni complete in `data/incoming/`, terminando la copia prima di aprire l'app. Ogni avvio e interazione Streamlit controlla automaticamente tutti i file `.pdf` (anche `.PDF`) al primo livello della cartella. Per rilevare nuovi file mentre la pagina è inattiva, ricaricare la pagina. Non ci sono pulsanti di caricamento o elaborazione, né monitoraggio in background.

Per ogni file viene calcolato SHA-256. Solo i contenuti nuovi vengono estratti con `pypdf`, pagina per pagina, e salvati in `data/archive.sqlite3`. I file invariati, rinominati o duplicati riusano il risultato persistente anche dopo un riavvio. Le modifiche al contenuto producono un nuovo hash e una nuova estrazione. Il calcolo degli hash richiede comunque la lettura dei file a ogni scansione. Hash ed estrazione usano gli stessi byte letti in memoria, un PDF alla volta.

La tabella mostra nome, numero di pagine, stato e dettagli; i selettori consentono di leggere il testo per pagina. Ogni pagina espone nome file, numero da 1 e totale pagine. I conteggi sono per file, comprese le copie identiche: “Quotidiani acquisiti” comprende documenti estratti, parzialmente estratti e leggibili senza testo; esclude file vuoti e non leggibili. “PDF disponibili” comprende tutti i PDF rilevati.

File di zero byte, PDF senza pagine, danneggiati, protetti da password ed errori per pagina sono segnalati senza fermare gli altri documenti. Anche gli esiti negativi sono salvati per hash. Un file non accessibile dal filesystem non può essere identificato tramite hash e viene ricontrollato alle scansioni successive. I PDF con sole immagini sono indicati come privi di testo estraibile: non è previsto OCR. Il numero di pagine è zero quando non è possibile determinarlo.

La consultazione riflette i file presenti: rimuovere un PDF dalla cartella lo rimuove dall'elenco, ma conserva il risultato storico nel database. Per ricostruire tutte le estrazioni, arrestare l'app e rimuovere `data/archive.sqlite3`. Il database contiene testo dei quotidiani: è locale ed escluso da Git, così come i PDF. La cartella viene creata automaticamente se assente.

## Preprocessing e chunking

Dopo l'acquisizione, `prepare_documents` utilizza esclusivamente il testo delle pagine già estratte, senza aprire PDF. La pulizia normalizza Unicode (NFKC, incluse le legature), spazi e interruzioni di riga; rimuove caratteri di controllo, caratteri invisibili di formattazione e trattini discrezionali. Conserva accenti e punteggiatura. Non ricostruisce colonne, articoli o parole divise da trattini visibili: l'ordine di lettura dipende da pypdf.

Ogni pagina viene suddivisa separatamente con `ChunkConfig(size=1000, overlap=150)`. La dimensione massima è 1000 caratteri Unicode, non token; si preferisce un confine di frase nell'ultimo quarto della finestra, poi uno spazio, altrimenti si taglia al limite. L'overlap è esattamente 150 caratteri nel testo pulito; può iniziare a metà parola. Il frammento finale e le pagine brevi possono essere più corti. I chunk non attraversano pagine.

Ogni chunk contiene nome PDF, SHA-256 del contenuto, pagina originale da 1, posizione progressiva da 1 nel documento, intervallo `[start, end)` nella pagina pulita e ID SHA-256 deterministico. Gli offset partono da zero e non si riferiscono al testo grezzo o ai byte del PDF. Copie e rinomine condividono ID e contenuti; il nome del file corrente viene associato in consultazione attraverso i dati di origine.

Nel medesimo database vengono aggiunte automaticamente le tabelle `chunk_sets` (hash del PDF, firma di configurazione/versione, pagine escluse) e `chunks` (testo e metadati). Il nome è persistito nella tabella `sources`, collegata tramite hash. Il database del Task 1 viene esteso senza cancellare le estrazioni. Ogni hash conserva un solo set di chunk: una configurazione cambiata sostituisce atomicamente quel set; gli altri PDF non vengono riscritti finché non richiedono elaborazione. I risultati con zero chunk vengono memorizzati anch'essi.

Per cambiare dimensione e overlap, passare un `ChunkConfig` a `prepare_documents` nell'app. La firma include entrambi i parametri e `PIPELINE_VERSION`, da incrementare quando cambia il codice di pulizia/chunking. Un cambio di configurazione nell'app rigenera i chunk dei documenti presenti, senza ripetere l'estrazione PDF. Un PDF modificato genera solo il nuovo set per il nuovo hash; il contenuto precedente rimane storico come le estrazioni del Task 1. La UI mostra solo i PDF attualmente presenti; per una futura indicizzazione usare i risultati restituiti da `prepare_documents`, evitando di includere indiscriminatamente gli hash storici.

Le pagine con testo vuoto dopo la pulizia, errori di estrazione o testo non disponibile vengono escluse e indicate con pagina e motivo. La UI espone il numero di chunk per quotidiano e una selezione per leggerne testo e metadati di origine. I file non leggibili mantengono la segnalazione di acquisizione anche quando non è possibile determinarne le pagine. Non viene usato OCR.

## Embeddings e indice vettoriale (Task 3)

Installare le dipendenze aggiornate con `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`. Il pacchetto ufficiale `google-genai` genera vettori con `gemini-embedding-2` a 768 dimensioni. ChromaDB usa persistenza locale in `data/chroma/` e distanza cosine; la sua embedding function è esplicitamente `None`. Non vengono scaricati o eseguiti modelli locali. Le dipendenze transitive di Chroma possono includere runtime di inferenza: l'applicazione non li usa per generare embeddings.

La chiave viene letta da `GEMINI_API_KEY` nell'ambiente o dal file `.env` nella radice del progetto, senza sovrascrivere l'ambiente. `.env.example` contiene solo un segnaposto. Non committare la chiave. Il controllo locale segnala soltanto se la chiave è presente: non ne verifica la validità con richieste al servizio.

Controllo dell'archivio e del lavoro previsto, senza chiamate API né modifiche ai vettori:

```powershell
.\.venv\Scripts\python.exe -m edicola.indexing --dry-run --limit 10
```

Prima indicizzazione, da eseguire solo su contenuti autorizzati all'invio a Gemini:

```powershell
.\.venv\Scripts\python.exe -m edicola.indexing --limit 10 --authorize-external
```

`--authorize-external` autorizza l'invio dei chunk selezionati; `--limit` è obbligatorio e positivo nelle esecuzioni reali. Nessun comando senza argomenti avvia l'indicizzazione completa. Il limite conta i nuovi chunk o i chunk modificati, non quelli già indicizzati: ripetere lo stesso comando prosegue con i successivi. Per restringere i contenuti autorizzati a un quotidiano, aggiungere `--pdf "nome_esatto.pdf"`; l'opzione è ripetibile e può essere usata anche nel controllo locale. Streamlit non importa o avvia il modulo di indicizzazione.

Il modulo apre SQLite in sola lettura e usa direttamente le tabelle esistenti, senza estrarre PDF o ripetere preprocessing. Legge i PDF solo per verificare SHA-256 e confrontarli con `sources`: esclude lo storico e i file rimossi. Se un PDF è nuovo/modificato o manca il preprocessing, il controllo lo segnala e la sincronizzazione reale si arresta prima di cambiare l'indice; aprire prima Streamlit per aggiornare i Task 1 e 2. Una cartella o un database mancanti provocano un errore, evitando cancellazioni accidentali dell'indice.

In Chroma vengono salvati ID, testo del chunk SQLite senza ulteriori trasformazioni, PDF, elenco degli alias, hash PDF, pagina e totale pagine, posizione, offset, firma del chunking e impronta del testo inviato. Copie identiche condividono un vettore. Una rinomina o l'aggiunta/rimozione di alias aggiorna solo i metadati, senza nuove richieste. Il titolo inviato è stabile: `Quotidiano {sha256} - pagina {page}`, così la rinomina non cambia l'input dell'embedding.

La formattazione segue la [documentazione ufficiale Gemini Embeddings](https://ai.google.dev/gemini-api/docs/embeddings): `title: {title} | text: {content}` per i documenti, `task: question answering | query: {content}` per le domande, senza `task_type`. Ogni richiesta riguarda un solo chunk o una sola domanda, evitando aggregazioni involontarie di più documenti.

La collezione `edicola_gemini_embedding_2_768` registra modello, dimensionalità, formato dei prompt e metrica; valori incompatibili, incluse dimensioni effettive errate, bloccano l'operazione prima delle chiamate API. Per introdurre un altro modello o formato usare un'altra collezione e reindicizzare esplicitamente. Non modificare i metadati per aggirare il controllo.

Prima degli invii il comando elimina i vettori non più associati ai chunk attuali e aggiorna i soli metadati cambiati. `--limit` non limita queste operazioni locali di sincronizzazione, anche quando si usa `--pdf`; il filtro PDF limita gli invii, senza eliminare documenti attivi degli altri PDF. Il controllo locale mostra le cancellazioni previste senza eseguirle. Dopo un cambiamento della configurazione di chunking, i vecchi ID sono rimossi e i nuovi vengono indicizzati progressivamente secondo il limite.

Ogni vettore viene salvato subito dopo la risposta valida. Se la quota termina o la connessione manca, i chunk già salvati restano disponibili e non vengono inviati nuovamente al comando successivo. Ogni chunk ha al massimo 3 tentativi, con attese di 1 e 2 secondi, timeout di 30 secondi per tentativo e retry interni SDK disattivati. Sono ritentati solo errori temporanei di rete e HTTP 408/429/500/502/503/504; gli errori permanenti arrestano il lavoro. Un limite di 10 chunk può quindi comportare fino a 30 tentativi in presenza di errori temporanei. Un'interruzione fra risposta API e salvataggio locale può richiedere di rigenerare il singolo vettore non ancora salvato. Eseguire un solo comando di indicizzazione alla volta per evitare invii concorrenti dello stesso chunk.

## Ricerca semantica

Da terminale, riutilizzando i vettori già presenti in Chroma e generando soltanto l'embedding della domanda:

```powershell
.\.venv\Scripts\python.exe -m edicola.search "Quali sono le principali notizie economiche?" --authorize-external
```

Il comando mostra fino a cinque chunk con testo completo, nome PDF, pagina, ID e distanza vettoriale. Non modifica l'indice e non avvia estrazione, preprocessing o indicizzazione dei documenti. Richiede la stessa `GEMINI_API_KEY` già configurata per l'indicizzazione. Se l'indice è vuoto, lo segnala senza chiamate API.

Disponibile come funzione Python, senza interfaccia chatbot e senza generazione di risposte:

```python
from edicola.search import semantic_search

# Autorizza l'invio della sola domanda al servizio Gemini.
hits = semantic_search("Quali sono le principali notizie economiche?", authorize_external=True)
for hit in hits:
    print(hit["filename"], hit["page"], hit["distance"], hit["text"])
```

La ricerca restituisce fino a cinque chunk indicizzati attuali, ordinati per distanza cosine (più bassa indica maggiore prossimità), con ID, testo e metadati. Esclude i vettori obsoleti anche prima della prossima sincronizzazione; un indice vuoto non genera chiamate API. Se sono stati indicizzati solo dieci chunk, la ricerca copre soltanto quei dieci: il test con vettori simulati verifica il funzionamento della ricerca, non la qualità semantica del modello remoto.

## Chat con l'Edicola (Task 4)

Avviare Streamlit con il comando della sezione Avvio e aprire **Chat AI**. La consultazione dei PDF resta nella scheda **Archivio**. Non viene avviata alcuna chiamata Gemini all'apertura o durante la consultazione dell'archivio.

Per provare la prima domanda:

1. Verificare che `.env` contenga `GEMINI_API_KEY` e che alcuni chunk siano già indicizzati.
2. Facoltativamente aggiungere `GEMINI_RAG_MODEL=gemini-2.5-flash` a `.env` (è il valore predefinito).
3. Inserire una domanda su un tema presente nei quotidiani indicizzati, per esempio «Che cosa riportano gli articoli sui trasporti?».
4. Selezionare l'autorizzazione all'invio della domanda e dei passaggi a Gemini e premere **Chiedi all'Edicola**.
5. Leggere la risposta con rimandi `[S1]`, `[S2]`, ecc.; consultare PDF e pagine nelle fonti utilizzate ed espandere i passaggi originali recuperati.

Il modello predefinito è [Gemini 2.5 Flash, disponibile anche nel piano gratuito](https://ai.google.dev/gemini-api/docs/pricing#gemini-2.5-flash), con limiti di quota e disponibilità legati all'account. La variabile `GEMINI_RAG_MODEL` permette di scegliere un altro modello Flash compatibile con output JSON strutturati. Il codice non abilita billing né ripiega automaticamente su modelli a pagamento; usare una chiave del piano gratuito per operare entro quel piano. Non viene effettuato un controllo remoto del piano all'avvio.

Il backend `edicola.rag.ask_question` riusa `semantic_search` per recuperare inizialmente tre chunk. Il numero è configurabile con `GEMINI_RAG_TOP_K` (intero da 1 a 5, default 3) in `.env` o nell'ambiente, oppure con l'argomento `top_k` del backend. Il comando di ricerca semantica da terminale conserva il valore predefinito di cinque risultati. Invia l'embedding della sola domanda tramite il modulo esistente e poi domanda e passaggi al modello Flash; non rigenera embeddings dei documenti e non aggiunge, aggiorna o elimina vettori. Le risposte coprono soltanto la parte dell'archivio già indicizzata. Ogni invio è indipendente: non viene trasmessa una cronologia, e l'ultima risposta resta nella sessione Streamlit durante le interazioni di consultazione.

Le istruzioni operative sono separate dal contenuto JSON dei documenti, trattato come dati non attendibili; al modello è vietato seguire istruzioni contenute negli articoli o usare conoscenze esterne. Non sono configurati strumenti, ricerca Web o esecuzione di codice. L'output richiesto è strutturato: sufficienza delle informazioni, affermazioni e relative evidenze letterali con ID di fonte. I rimandi vengono aggiunti **dal codice**, dopo avere verificato che gli ID siano fra quelli recuperati e che le evidenze citate siano presenti nei testi (normalizzando soltanto gli spazi). Sono rifiutati citazioni libere nel testo, ID sconosciuti, evidenze inventate, output malformati, troncati o senza supporto. In questi casi viene mostrato un messaggio fisso di informazioni insufficienti, senza esporre la risposta non validata. Anche in caso di astensione restano visibili i passaggi realmente recuperati.

Questi controlli verificano riferimenti e presenza delle citazioni, **non dimostrano che ogni parafrasi sia semanticamente implicata dalle evidenze**. I prompt riducono, ma non eliminano, il rischio di errori o prompt injection. Per questo l'interfaccia rende consultabili le fonti originali. Non viene applicata una soglia arbitraria di distanza: i cinque vicini possono essere poco pertinenti e il modello deve astenersi quando non consentono una risposta.

Gli errori Gemini, quota e rete vengono mostrati senza chiavi o dettagli SDK grezzi. La generazione ha timeout di 30 secondi per tentativo e massimo tre tentativi per errori temporanei, con attese di 1 e 2 secondi; nessun retry per errori permanenti o per correggere output non validati. Il retrieval mantiene i propri retry limitati. La chat non salva su disco domande o risposte; un nuovo invio rimuove la vecchia risposta anche se fallisce. I podcast hanno un modulo separato descritto nel Task 6B; la personalizzazione demo è descritta nel Task 7.

Esempio backend, solo su contenuti autorizzati:

```python
from edicola.rag import ask_question

result = ask_question("Che cosa riportano gli articoli sui trasporti?", authorize_external=True)
print(result.answer)
print(result.used_source_ids)  # ID citati e validati dal codice.
print(result.sources)         # Tutti e soli i passaggi effettivamente recuperati.
```

### Diagnostica delle chiamate Gemini

Nel terminale da cui viene avviato Streamlit, i log `edicola` distinguono le fasi senza stampare domanda, passaggi, chiavi o errori SDK grezzi. Un `request_id` collega l'intero flusso di un invio. Per esempio:

```text
request_id=abc123 phase=rag model='modello-configurato' event=start top_k=3
request_id=abc123 phase=query_embedding model='gemini-embedding-2' event=success
request_id=abc123 phase=generation model='modello-configurato' event=error http_status=503 attempt=1 retry=True
```

`phase=query_embedding` con `http_status=503` individua l'errore durante l'embedding della domanda. `phase=generation` con lo stesso codice individua la generazione della risposta. `model` mostra il modello effettivamente passato all'SDK, senza cambiare `GEMINI_RAG_MODEL`. Per errori di rete senza risposta HTTP il codice è `-`. Ogni tentativo di generazione è numerato: più righe `phase=generation` con lo stesso `request_id` e `attempt` crescente indicano retry limitati, non altre esecuzioni RAG. I normali rerun non avviano il flusso e non ritentano un invio fallito; un nuovo clic autorizzato costituisce invece una nuova richiesta.

Il codice installato dell'SDK è stato verificato: `HttpRetryOptions(attempts=1)` include la chiamata iniziale, quindi non aggiunge retry. Rimangono soltanto i tre tentativi massimi applicativi per fase, con attese di 1 e 2 secondi, già presenti nel progetto. Non sono stati aggiunti fallback di modello, nuovi retry, indicizzazioni o modifiche alla validazione delle fonti.

Secondo la [guida ufficiale Gemini](https://ai.google.dev/gemini-api/docs/troubleshooting), HTTP 503 indica indisponibilità temporanea o sovraccarico del servizio. Ridurre i passaggi da cinque a tre alleggerisce la richiesta, ma non garantisce di eliminare un errore remoto. La ricerca da terminale usa l'endpoint di embedding, mentre il RAG usa anche quello di generazione: il successo della prima non verifica la disponibilità del secondo. Senza una richiesta reale o log dell'errore non si può attribuire con certezza il 503 osservato a una delle due fasi.

Dopo gli aggiornamenti riavviare Streamlit. Per provare un numero diverso di passaggi, impostare ad esempio `GEMINI_RAG_TOP_K=3` in `.env` e riavviare il processo; le variabili già presenti nell'ambiente hanno precedenza sul file. Non occorre reindicizzare.

## Prodotti editoriali (Task 5)

La scheda **Approfondimenti** contiene dossier e briefing, separati dalla chat. Il backend RAG e la sua validazione non sono stati modificati.

- **Dossier tematico:** inserire un argomento (per esempio «Trasporti»), autorizzare l'invio e premere **Genera dossier tematico**. Vengono recuperati passaggi pertinenti con la ricerca semantica esistente, bilanciando le edizioni: un solo embedding dell'argomento viene riutilizzato nelle query locali per PDF. L'opzione `diversify_by_pdf` è attiva solo per il dossier; chat e ricerca ordinaria mantengono il loro comportamento. Il prodotto ha titolo, introduzione, due sezioni tematiche e conclusioni, con rimandi a PDF e pagina.
- **Briefing:** autorizzare l'invio e premere **Genera briefing**; non serve inserire un argomento. Non viene eseguita una query top-3 e non viene generato un embedding. Sono letti tutti i vettori indicizzati attuali; il campione iniziale di otto passaggi alterna testate, edizioni/date e pagine, privilegia indizi di titoli e prima pagina e filtra testi identici o quasi identici. Tutti i passaggi selezionati arrivano al prompt, entro i budget configurati: i gruppi semantici sono soltanto suggerimenti e non tagliano il campione. Il modello dispone di istruzioni autonome da redattore e produce fino a otto notizie con titolo, sintesi e fonti: normalmente da tre a otto, ma anche una o due quando sono le sole documentate.

Il raggruppamento è euristico: i chunk non sono articoli segmentati, una somiglianza vettoriale non prova che due notizie siano identiche e il briefing non rappresenta una classifica completa degli eventi. Gli indizi di titolo (maiuscole, inizio pagina, intestazione breve) non ricostruiscono colonne o articoli. Il filtro locale dei quasi duplicati confronta sequenze di parole, preserva aggiornamenti con numeri diversi e non considera duplicato il solo overlap di chunk. Il modello accorpa ripetizioni distinguendo i fatti diversi; il codice rimuove sintesi identiche dall'output. Nessuna notizia viene aggiunta per raggiungere un numero prefissato. Una singola notizia verificabile è un briefing parziale valido, non un motivo di astensione.

### Copertura e metadati delle edizioni

Prima di usare le fonti, il backend confronta SQLite e Chroma senza eseguire ingestion, preprocessing, indicizzazione o aggiornamenti dei vettori. Usa solo ID attuali con testo e impronta corrispondenti. Gli hash storici, i PDF rimossi e i chunk non indicizzati non vengono inviati. La UI riporta chunk indicizzati/totali, conteggi per PDF, eventuali avvisi e l'indicazione di archivio parziale.

Non si deducono nome della testata e data dal nome file, dalla posizione dei chunk o dal giorno corrente. Se mancano, la selezione alterna i PDF come edizioni distinte e segnala che testata/data non sono disponibili. Quando verificati dall'utente, questi metadati possono essere specificati nel file facoltativo `data/editions.json`, usando la struttura di [editions.example.json](editions.example.json): chiave uguale al nome PDF, `publication` e `date` in formato ISO `YYYY-MM-DD`. Il file di esempio contiene valori dimostrativi, non metadati reali dei quotidiani. Cambiare questa associazione non richiede rigenerare embeddings. Copie identiche del PDF condividono i chunk e non vengono considerate testate indipendenti.

### Budget, modello e cache

Il modello è esattamente quello di `GEMINI_RAG_MODEL` già caricato da `.env`/ambiente; nessun fallback di modello e nessun nuovo pacchetto. Il raggruppamento utilizza NumPy, già richiesto da ChromaDB. Configurazione facoltativa in `.env` (riavviare Streamlit dopo la modifica):

| Variabile | Default | Limiti / significato |
| --- | --- | --- |
| `EDITORIAL_DOSSIER_CHUNKS` | 5 | Da 1 a 5 passaggi pertinenti |
| `EDITORIAL_BRIEFING_CHUNKS` | 8 | Da 1 a 20 passaggi; 8–12 consigliati per il prototipo |
| `EDITORIAL_MAX_SOURCE_CHARS` | 8000 | Da 2000 a 20000 caratteri complessivi di testi inviati |
| `EDITORIAL_BRIEFING_MAX_PROMPT_CHARS` | 14000 | Da 2000 a 40000 caratteri: istruzioni di sistema + contenuto JSON del briefing, inclusi metadati |
| `EDITORIAL_TOPIC_SIMILARITY` | 0.82 | Soglia cosine per raggruppare temi affini, da 0.5 a 0.99 |

Se necessario, i testi inviati vengono limitati a un prefisso per passaggio, dividendo equamente il budget. Per il briefing un secondo controllo misura il prompt testuale complessivo, incluse istruzioni e metadati, e riduce equamente i prefissi mantenendo gli ID e il numero di fonti; se il solo contesto minimo non entra nel budget, lo segnala senza chiamare Gemini. Il conteggio non include l'involucro di trasporto SDK o lo schema JSON di configurazione. L'interfaccia mostra esattamente i passaggi inviati, senza alterare i chunk originali. È disponibile anche `EditorialConfig` per il budget delle fonti e il campionamento; il limite complessivo del prompt briefing si configura nell'ambiente.

La cache persistente è separata in `data/editorial.sqlite3`, esclusa da Git. La chiave include tipo di prodotto, argomento normalizzato negli spazi, modello, configurazione, versione della strategia, metadati di edizione e snapshot dei chunk effettivamente indicizzati. Una richiesta identica riusa il prodotto senza chiamare Gemini, **nemmeno per l'embedding del tema del dossier**. Una variazione dell'archivio, delle edizioni, del modello o dei parametri invalida la cache. Il briefing usa `briefing-v2`, con chiave diversa da quella della prima implementazione: le vecchie voci (incluse astensioni negative) restano su disco ma non vengono lette dal nuovo briefing, mentre le chiavi del dossier sono preservate. Il briefing memorizza soltanto prodotti con almeno una notizia valida; astensioni, errori e output non validi non vengono salvati. Il dossier mantiene il precedente comportamento di cache, incluse le astensioni esplicite. Gli invii simultanei da processi diversi non hanno un blocco distribuito: la cache è pensata per richieste successive del prototipo.

Titoli, introduzioni, paragrafi e conclusioni del dossier passano attraverso `rag.validate_response`, senza modificarne le regole. Nel briefing viene validata separatamente ogni coppia titolo/sintesi: il limite di otto claims del chatbot non limita l'intero briefing a quattro notizie. Ogni fonte deve essere tra i passaggi realmente selezionati e ogni evidenza deve essere letteralmente presente. I gruppi tematici non impongono una corrispondenza uno-a-uno con le notizie e una notizia può combinare più fonti selezionate. Il codice aggiunge i rimandi `[S1]`, ecc.; le notizie con errori sono scartate mantenendo le altre valide e mostrando un avviso. Valgono i limiti di verifica semantica descritti per il RAG.

### Diagnostica del briefing (Task 5B)

L'interfaccia indica la strategia e uno stato esplicito; nel terminale i log collegati dal `request_id` riportano solo conteggi, modello, fase ed esito, mai contenuti editoriali, argomenti, citazioni o credenziali.

| Fase / stato | Significato |
| --- | --- |
| `briefing_selection` | Chunk disponibili e selezionati, PDF/pagine distinte, caratteri e gruppi; `empty_index` e `selection_empty` distinguono indice vuoto e filtri senza risultati |
| `briefing_context` | Dimensione del prompt e budget; `prompt_budget_exceeded` evita la richiesta se il contesto minimo non entra |
| `briefing_generation` | Modello, tentativo e codice HTTP; `output_truncated` distingue `MAX_TOKENS`, `output_blocked` una risposta non completata |
| `model_abstention` | Il modello ha dichiarato esplicitamente di non avere una notizia supportata |
| `invalid_json`, `invalid_structure`, `empty_response` | Errore di formato o risposta vuota, non insufficienza delle fonti |
| `citation_validation_failed` | Tutte le notizie sono state respinte dalla validazione, non un giudizio sul catalogo |
| `partial_validation` | Almeno una notizia valida; conteggio delle altre scartate per formato o riferimenti |
| `editorial_cache` | Hit/miss, strategia e stato; i nuovi briefing negativi riportano `not_stored` |

La versione precedente selezionava otto passaggi ma, quando erano in otto gruppi diversi, ne inviava solo quattro. Richiedeva inoltre esattamente una notizia per gruppo usando il prompt del chatbot, e mostrava lo stesso messaggio per astensione, citazioni respinte o output troncato. La nuova implementazione elimina questi vincoli. La risposta grezza precedente non è conservata: senza i nuovi log non è possibile ricostruire quale controllo abbia respinto una specifica risposta storica. Il briefing ha un budget di output di 8192 token e mantiene massimo tre tentativi applicativi e uno SDK, senza cambiare modello o configurazione del chatbot.

I prodotti partono soltanto dai rispettivi pulsanti dopo autorizzazione. L'avvio della piattaforma e i rerun di consultazione non generano prodotti; l'ultimo risultato resta nella sessione. Gli errori riutilizzano i timeout, i retry limitati e i log sicuri già presenti nella generazione RAG. Non vengono inviati né modificati i PDF completi.

## Timeline e mappe concettuali (Task 6A)

Riavviare Streamlit e aprire **Timeline e Mappe**. La scheda dispone di un campo argomento e un consenso dedicati:

1. Inserire un argomento presente nei quotidiani indicizzati, per esempio «Trasporti».
2. Selezionare l'autorizzazione all'invio dell'argomento e dei passaggi a Gemini.
3. Premere **Genera timeline** oppure **Genera mappa concettuale**.

Le nuove funzioni usano `semantic_search` e il modello `GEMINI_RAG_MODEL` già configurato. Non modificano chatbot, dossier, briefing, ingestion o chunking e non scrivono nei database esistenti. Il retrieval legge solo contenuti indicizzati attuali; non genera embeddings dei documenti e non aggiunge o elimina vettori. La normale acquisizione automatica preesistente dell'app resta invariata. L'apertura e i rerun di consultazione non avviano generazioni; una nuova rappresentazione richiede sempre il pulsante e l'autorizzazione.

### Timeline

Gemini restituisce fino a dodici eventi con titolo, descrizione, evidenze e data proposta. Python valida titoli, descrizioni e ID delle fonti attraverso il validatore RAG esistente. La data può essere esplicita nel testo oppure completata dal contesto verificato dell'edizione (Task 6A.1); non viene mai sostituita con la data di pubblicazione o ricavata dall'orologio.

Per completare un giorno/mese senza anno serve la data ISO verificata dall'utente in `data/editions.json`, associata al PDF esatto della citazione temporale. Si riutilizza lo [schema esistente](editions.example.json), senza nuovi campi: `publication` e `date` (`YYYY-MM-DD`, quindi `2026-10-17` per il 17/10/2026). Il software controlla il calendario, ma non può certificare autonomamente che il metadato inserito corrisponda alla copertina: verificarlo sul PDF. Se il file o il metadato manca, l'anno non viene completato e l'interfaccia segnala l'esito.

Le regole sono conservative: servono un giorno della settimana coerente oppure riferimenti temporali espliciti (`si terrà`, `si è svolto`, `oggi`, `domani`, `ieri`). Senza un riferimento esplicito all'anno corrente/prossimo/scorso, l'evento deve essere entro 31 giorni dall'edizione. Si esaminano anche gli anni adiacenti: a cavallo d'anno serve un riferimento direzionale esplicito, non basta scegliere la data più vicina. «Mercoledì 21 ottobre», dall'edizione verificata del 17/10/2026, diventa 21/10/2026; «21 ottobre» da solo resta ambiguo. «Si terrà il 2 gennaio» da un'edizione del 29/12/2026 può diventare 02/01/2027. Date multiple, giorno settimanale errato, contesto storico o indicazioni contraddittorie impediscono il completamento. Queste regole non ricostruiscono liberamente la cronologia di un articolo.

Sono riconosciuti `YYYY-MM-DD`, `DD/MM/YYYY`, `DD-MM-YYYY` e date con mese italiano completo, per esempio «12 ottobre 2026». Giorni impossibili sono rifiutati. Citazioni con più date o con indizi espliciti di data editoriale non vengono usate per ordinare l'evento. Le date complete eventualmente contenute nelle descrizioni devono comparire nelle rispettive evidenze.

Gli eventi con data verificata sono ordinati cronologicamente e mostrati in un grafico temporale nativo Streamlit/Vega-Lite e in schede con descrizione e riferimenti. Le schede distinguono **Data esplicita nel testo**, **Data completata tramite metadati verificati** (con fonte dell'ancoraggio) e **Data non determinabile**, mantenuta in **Eventi non collocati cronologicamente**. La **data di pubblicazione** rimane separata. Lo stato distingue annunci/programmi, futuro rispetto all'edizione, svolgimento esplicitamente riferito e stato non determinabile: una data passata non prova che l'evento sia avvenuto. Per annunci o futuro si mostra il passo originale, evitando parafrasi che trasformino un programma in un fatto compiuto. Ogni rappresentazione conserva nome PDF, pagina e ID del chunk originale, con i passaggi consultabili.

### Mappa concettuale

Gemini propone preferibilmente 8–10 nodi (`concept`, `event`, `place`, `organization`), al massimo dieci e quattordici collegamenti, partendo dalle proposizioni relazionali documentate. Le denominazioni dei nodi devono essere presenti letteralmente nelle evidenze. I limiti di sicurezza Python rimangono sedici nodi e ventiquattro collegamenti; la vista compatta mostra al massimo dieci nodi. Ogni arco è validato prima di creare il grafo:

- **Documentato:** linea continua con freccia. Entrambi gli estremi e una locuzione relazionale letterale devono comparire in una proposizione verificabile. Il controllo ammette ausiliari, avverbi e modificatori limitati (es. «ha approvato», «approva oggi», «approva con delibera il piano»), senza wildcard che attraversino altri soggetti o frasi. Le forme passive mantengono la locuzione originale e la direzione corrispondente («piano → è stato approvato dal → Comune»). Negazioni, ipotesi, subordinate impropriamente collegate e inversioni non documentate sono scartate. Non è un analizzatore linguistico completo: formulazioni complesse possono restare escluse.
- **Associazione tematica:** linea tratteggiata senza freccia, con tema comune nell'etichetta. `label.text` contiene il tema letterale, e le citazioni devono collegare esplicitamente ciascun nodo a quel tema (es. «piano riguarda i trasporti» e «commissione si occupa di trasporti»). La semplice compresenza nello stesso articolo o una parola condivisa non bastano. L'associazione non rappresenta causalità.

Per le relazioni documentate il Task 6A.3 separa l'etichetta proposta dal **predicato letterale** (`predicate`). Per esempio, «finanzia» può accompagnare la prova «stanzia oltre quattro milioni per», ma il grafico mostra soltanto quest'ultima, dopo verifica di soggetto, predicato e oggetto. Non vengono dichiarati equivalenti sinonimi arbitrari né accettate relazioni sulla sola fiducia nel modello. Se `predicate` manca, resta compatibile il precedente controllo letterale su `label.text`.

Le mappe possono aggiungere pochi chunk adiacenti già indicizzati dello stesso PDF, senza query Gemini aggiuntive. Si controllano hash, configurazione, pagina, posizioni consecutive, intervalli e corrispondenza esatta dell'overlap. Una prova distribuita può usare due citazioni originali separate solo se coprono un intervallo continuo (sono ammessi esclusivamente eventuali spazi intermedi). Non si uniscono pagine diverse, chunk non indicizzati o frammenti con testo mancante. Entrambi gli ID e le citazioni restano visibili, con PDF e pagina; la vicinanza non crea da sola una relazione.

Riferimenti sconosciuti, nodi assenti, citazioni inventate e relazioni non supportate vengono scartati. `source_id` usa solo gli identificativi `S1`, `S2`, ecc.; gli estremi usano `N1`, `N2`, ecc. La mappa conserva solo le citazioni che provano ogni arco. L'interfaccia mostra **candidate, accettate ed escluse**, distinguendo «Gemini non ha proposto relazioni» da «tutte le candidate sono state scartate». In **Dettagli e prove dei collegamenti** sono consultabili passi letterali, PDF, pagina e una tabella per candidata: nodo inesistente/scartato, fonte sconosciuta, citazione inesatta, predicato parafrasato, estremi assenti dalle prove, negazione/ipotesi, costruzione non verificabile, tema non supportato o duplicato. I log riportano soltanto categorie e conteggi, senza testi editoriali, argomento o proposte grezze del modello. La UI segnala anche quanti chunk adiacenti sono stati usati e quanti passaggi sono stati esclusi per il budget.

Il layout Graphviz va da sinistra a destra con font 10/9, spaziature e margini ridotti, etichette su più righe e colori sobri per i tipi di nodo. La larghezza naturale è limitata al contenitore Streamlit, senza ingrandire i grafi piccoli; il riquadro ha altezza 360 pixel. La selezione dà precedenza agli archi documentati e conserva entrambi gli estremi, fino a dieci nodi collegati. I nomi completi restano nei tooltip e nell'elenco. **Se non ci sono archi validati, viene mostrato un elenco compatto, senza grafico di nodi isolati.** I concetti non inclusi nella vista restano nei dettagli. Si usa DOT quotato con `st.graphviz_chart`, senza HTML/URL generati, modelli, eseguibili Graphviz o nuove dipendenze.

La strategia `concept-map-v2` include la configurazione dei vicini nella cache e invalida soltanto le vecchie mappe alla successiva generazione esplicita, senza eliminarle. Timeline, RAG, dossier, briefing e indici rimangono invariati. Riavviare Streamlit e premere nuovamente **Genera mappa concettuale** dopo autorizzazione; una mappa senza archi rimane un risultato valido quando i passaggi selezionati non contengono prove sufficienti.

### Cache, limiti e API

Task 6A usa `response_mime_type="application/json"` e un solo `response_json_schema` con tipi, campi e identificativi ammessi. I limiti `minItems`/`maxItems` degli array annidati sono esclusi dalla richiesta per ridurre la complessità dello schema; Python continua a verificare massimo 12 eventi, 16 nodi, 24 archi e da 1 a 5 evidenze per affermazione, insieme a date, citazioni e relazioni. Questi limiti sono anche indicati nelle istruzioni. La strategia `knowledge-v2` distingue la nuova cache senza eliminare dati esistenti.

Un HTTP 400 non viene ritentato né attribuito automaticamente alla quota: nei log `phase=knowledge_generation`, `model`, `http_status` ed `error_kind` distinguono `schema` (indizi espliciti nel dettaglio del server), `unsupported_parameter`, `authentication` e `invalid_request` (causa non specificata). I messaggi e i payload grezzi del server non vengono registrati. La compatibilità lato server non è dimostrabile con i soli test simulati: i precedenti log, privi di tali dettagli, non consentono di accertare retroattivamente la causa dei 400.

La cache è nuova e separata in `data/knowledge_cache/`, con file JSON scritti atomicamente ed esclusi da Git. Nessuna nuova tabella o scrittura negli SQLite esistenti. La chiave include versione della strategia, tipo, argomento, modello, budget e snapshot delle fonti indicizzate con metadati. Richieste identiche riusano i dati senza ripetere né retrieval remoto né generazione; fonti, metadati o modello cambiati invalidano la cache. Risposte vuote, malformate, bloccate o troncate non vengono salvate; rappresentazioni parziali con elementi validi possono essere riutilizzate.

| Variabile facoltativa | Default | Limiti |
| --- | --- | --- |
| `KNOWLEDGE_CHUNKS` | 5 | Da 1 a 5 passaggi, con ricerca diversificata fra PDF |
| `KNOWLEDGE_MAX_PROMPT_CHARS` | 12000 | Da 4000 a 24000 caratteri per istruzioni + JSON, escluso l'involucro SDK e lo schema |
| `MAP_ADJACENT_CHUNKS` | 2 | Da 0 a 4 vicini complessivi, soltanto per le mappe, già indicizzati e contigui sulla stessa pagina |

La timeline rispetta il budget riducendo equamente i prefissi dei passaggi. Le mappe mantengono invece chunk interi per non distruggere la continuità delle prove: se il budget non basta, rimuovono i passaggi meno prioritari, preservando prima il seed più pertinente e i suoi vicini. Se neppure un chunk completo entra nel prompt, viene richiesto di aumentare il budget senza invocare la generazione. I chunk persistenti non cambiano e l'interfaccia mostra proprio i testi inviati. Il client usa timeout di 30 secondi e un solo tentativo SDK; il codice ammette al massimo tre tentativi per errori temporanei, senza cambiare modello o ricorrere a servizi ulteriori. Sono mostrati messaggi sicuri per errori, quota o connessione; i log non contengono testi o credenziali.

La cache timeline include una versione separata della normalizzazione temporale: l'aggiornamento non riutilizza timeline obsolete e non invalida mappe o altri prodotti. Cambiare i metadati dell'edizione invalida già la cache delle fonti interessate; non occorre reindicizzare.

Queste visualizzazioni coprono soltanto i passaggi recuperati, non tutti gli eventi o le relazioni dell'archivio. Date parziali e relative prive degli indizi richiesti restano fuori dalla cronologia anche quando un lettore potrebbe ricostruirle. Anche i controlli sullo stato degli eventi riconoscono solo espressioni esplicite: in dubbio lo stato resta indeterminato. I controlli delle relazioni sono volutamente conservativi e possono omettere collegamenti veri espressi con forme complesse. Citazioni e corrispondenze letterali non costituiscono una prova automatica dell'implicazione semantica: verificare sempre i passaggi. La qualità del modello remoto non viene provata dai test simulati.

## Podcast editoriali (Task 6B)

Avviare Streamlit come di consueto:

```powershell
.venv\Scripts\python.exe -m streamlit run app.py
```

In **Prodotti editoriali → Podcast editoriali**:

1. Selezionare un briefing o dossier già generato. Il catalogo legge `data/editorial.sqlite3` in sola lettura, escludendo astensioni e risultati vuoti; non crea un nuovo prodotto né interroga Chroma.
2. Scegliere una voce predefinita (Kore, Puck, Aoede o Leda) e controllare **Testo da leggere e fonti**. Sono voci multilingue supportate; il testo e la direzione vocale sono in italiano.
3. Autorizzare l'invio del copione a Gemini TTS e premere **Genera podcast**. Il lettore integrato riproduce il WAV e **Scarica WAV** permette di salvarlo. Apertura, cambio selezione, download e rerun non avviano sintesi.

Configurazione facoltativa in `.env`, separata dal modello generativo esistente:

```dotenv
GEMINI_TTS_MODEL=gemini-3.8-flash-lite-tts
GEMINI_TTS_VOICE=Kore
```

Si riutilizza `GEMINI_API_KEY`. Non si modifica `GEMINI_RAG_MODEL`. La [guida Google TTS](https://ai.google.dev/gemini-api/docs/speech-generation) richiede `google-genai >= 2.25.0`: la versione locale verificata è **2.32.0** e `requirements.txt` ora indica il minimo necessario, senza nuove dipendenze. La compatibilità della richiesta GenerateContent, inclusi i campi vocali, è testata attraverso l'SDK reale con trasporto HTTP simulato. La voce usa `speech_config.voice_config.voice`; stile e ritmo sono in `speech_metadata`, separati dal copione, per evitare che le istruzioni vengano lette ad alta voce.

Il copione è una preparazione **locale ed estrattiva**, senza un'altra chiamata generativa: conserva titolo e sezioni complete nell'ordine originale, ripulisce Markdown, identificativi `[S1]` e nomi PDF. Non riassume o parafrasa fatti, date e importi e conserva i tempi verbali, compresi gli eventi soltanto previsti. Le fonti delle parti selezionate rimangono separate, con PDF, pagina e chunk. Il limite è **240 parole e 3500 caratteri**, circa 1–2 minuti al ritmo richiesto di 130 parole/minuto; prodotti più brevi restano più brevi. Se non entra un'intera sezione, viene segnalato il limite senza tagliare frasi o generare nuovi contenuti. Gli estratti e la copertura parziale vengono indicati nell'interfaccia; non è una nuova selezione delle notizie dell'archivio.

La cache separata `data/podcast_cache/` contiene WAV e manifest JSON ed è esclusa da Git. L'hash comprende copione, modello, voce, stile e versione. Audio identici vengono riutilizzati, mentre la provenienza è salvata separatamente per prodotto e fonti: una cache condivisa non attribuisce a un dossier le fonti di un altro. Un lock impedisce richieste concorrenti duplicate e le scritture sono atomiche. In caso di interruzione del processo, un eventuale `.lock` residuo va rimosso solo dopo aver verificato che nessuna generazione sia ancora attiva.

Gemini 3.8 restituisce normalmente un **WAV completo**: il codice non aggiunge un secondo header. L'audio viene verificato (PCM mono 16 bit, campioni presenti, durata positiva e massimo tre minuti di tolleranza); output vuoti, troncati o non supportati non vengono salvati. È gestito anche PCM grezzo esplicitamente dichiarato a 24 kHz, incapsulato una sola volta con la libreria standard `wave`. Il client usa timeout di 60 secondi e **un solo tentativo**, senza retry SDK/applicativi, fallback di modello o attivazioni di fatturazione. HTTP 400/401/403/404/429/5xx e problemi di rete producono messaggi sicuri; i log non includono chiavi, copioni o audio.

### Piano gratuito e verifica reale

Alla verifica del **23 ottobre 2026**, il [listino Gemini Developer API](https://ai.google.dev/gemini-api/docs/pricing) indica un Free Tier per `gemini-3.8-flash-lite-tts`; il [modello supporta l'italiano](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash-lite-tts). Usare una chiave di un progetto Free Tier senza fatturazione attiva: il codice non controlla né cambia il piano del progetto, non abilita servizi Cloud Text-to-Speech/Vertex e non passa a un'offerta a pagamento quando la quota termina. Un progetto già fatturato segue invece il suo piano Google.

Le [quote effettive](https://ai.google.dev/gemini-api/docs/rate-limits) dipendono dal progetto e dal modello e sono consultabili in Google AI Studio; non sono garantite da questo prototipo e non sono state interrogate durante lo sviluppo. Nel piano gratuito Google indica l'uso dei dati per migliorare i propri prodotti: inviare soltanto contenuti autorizzati. Quota esaurita o capacità temporaneamente assente richiedono di attendere e riprovare manualmente. Pronuncia, naturalezza della voce e durata effettiva richiedono una prova reale: i test automatici usano esclusivamente audio e API simulati.

## Struttura

```text
app.py                  Interfaccia Streamlit e scansione automatica
edicola/models.py       Documenti e pagine
edicola/ingestion.py    Scansione, SHA-256 ed estrazione pypdf
edicola/chunking.py     Pulizia, suddivisione, metadati e cache dei chunk
edicola/storage.py      Registro SQLite persistente
edicola/archive.py      Lettura dei chunk attuali da SQLite senza rielaborazione
edicola/embeddings.py   Client Gemini, formattazione, timeout e retry
edicola/vectorstore.py  Chroma persistente e controlli di compatibilità
edicola/indexing.py     CLI di controllo e indicizzazione esplicita limitata
edicola/search.py       Ricerca semantica dei cinque chunk più vicini
edicola/rag.py          Prompt RAG, generazione Gemini Flash e validazione fonti
edicola/editorial.py    Dossier, briefing, validazione condivisa e cache SQLite
edicola/editorial_selection.py  Copertura locale, bilanciamento e gruppi tematici
edicola/briefing.py     Prompt autonomo, notizie validate singolarmente e diagnostica
edicola/knowledge.py    Generazione visuale e cache JSON separata
edicola/knowledge_validation.py  Date, citazioni, relazioni e DOT sicuro
edicola/knowledge_ui.py Visualizzazione Streamlit di timeline e mappe
edicola/profiles.py     Profilo demo SQLite, feedback, salvati e cancellazione
edicola/personalization.py  Consigli locali e briefing personale con fonti validate
edicola/personalization_ui.py  Preferenze, raccomandazioni e prodotti personali
edicola/evaluation.py   CLI, benchmark espliciti e confronto locale di profili demo
edicola/evaluation_data.py  Snapshot, dataset manuale, controlli e rubriche umane
edicola/evaluation_metrics.py  Retrieval, controlli tecnici RAG e statistiche
edicola/evaluation_report.py  CSV, report Markdown, schede e grafici Altair
data/incoming/          Content provider simulato
tests/                  Test con PDF sintetici e cartelle temporanee
```

## Test

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

I test non modificano i quotidiani reali. Verificano acquisizione, pulizia, chunking e consultazione Streamlit dei Task 1 e 2. Per il Task 3 usano esclusivamente client Gemini simulati e Chroma reale in cartelle temporanee: formato e dimensioni, retry, quota, connessione assente, errori permanenti, protezione delle chiavi, limite e autorizzazione CLI, lettura SQLite senza scritture o rielaborazioni, persistenza fra processi, deduplicazione, rinomine, aggiornamenti, eliminazioni, compatibilità della collezione e ordinamento della ricerca. Non consumano chiamate Gemini reali. Il controllo locale si limita a verificare la presenza della chiave, senza provarla sul servizio.

Per il Task 4 i test simulano il client di generazione e verificano domande con e senza evidenze pertinenti, indice vuoto, autorizzazione, formato del prompt, separazione delle istruzioni, modello configurabile, ID e citazioni, output malformati/troncati, errori API e rete, retry e mancata esposizione delle chiavi. I test Streamlit verificano avvio e consultazione senza chiamate esterne, invio autorizzato, fonti visibili, persistenza dell'ultima risposta e gestione degli errori. I test non misurano la qualità di un modello remoto e non consumano chiamate reali.

Per il Task 5 i test verificano struttura dei dossier, briefing da più edizioni/date, duplicati e raggruppamento, budget dei testi, cache persistente senza nuove richieste, invalidazione per fonti/modello/configurazione, astensione, autorizzazione, errori, modello configurato, citazioni e UI senza generazione automatica. Le integrazioni Chroma usano soltanto directory temporanee e vettori simulati; la ricerca diversificata produce una sola richiesta di embedding del tema. Nessuna chiamata Gemini reale durante sviluppo e test.

Per il Task 5B sono verificati briefing con una o otto notizie, passaggi su più pagine senza taglio ai quattro gruppi, titoli riconoscibili, quasi duplicati, riferimenti errati senza rigetto delle notizie valide, output troncati/malformati, budget complessivo del prompt e invalidazione delle sole vecchie cache briefing preservando il dossier.

Per il Task 6A i test simulano le API e verificano cronologia, date mancanti/impossibili/ambigue o editoriali, date inventate nelle descrizioni, mappe e relazioni tematiche/documentate, negazioni e causalità non supportata, riferimenti sconosciuti, cache e invalidazione, modello e retry, errori/troncamento e archivio parziale. Sono esercitati i grafici Streamlit e gli invii autorizzati senza chiamate all'avvio o nei rerun. Un'integrazione con Chroma temporaneo verifica che generare una mappa non cambi SQLite, metadati, documenti o vettori esistenti.

## Task 7 — Profilo demo e consigli personali

Nella sola modalità di sviluppo Windows `EDICOLA_PROFILE_MODE=local_demo`, aprire
la scheda **Personalizzazione**, che contiene **Il mio profilo**. Queste istruzioni
Task 7 descrivono la demo SQLite; per gli account pubblici seguire [ACCOUNTS.md](ACCOUNTS.md):

1. Inserire uno o più interessi, uno per riga (es. `Chieti`, `trasporti`, `scuola`), scegliere 2, 5 o 10 minuti e il formato testo, visuale o audio; premere **Salva preferenze**.
2. **Consigliati per te** si aggiorna automaticamente dai soli chunk attualmente indicizzati. Ogni passaggio conserva PDF, pagina e motivo del suggerimento. Salvare un passaggio o dichiarare un argomento gradito/non pertinente modifica il successivo ordinamento locale.
3. Per un nuovo prodotto, autorizzare l'invio dei passaggi selezionati e del tempo di lettura, poi premere **Genera il mio briefing**. Il generatore e la verifica delle citazioni sono quelli del briefing esistente; non viene eseguita una nuova ricerca remota né un embedding.
4. I briefing personali salvati sono consultabili senza API. Per ascoltarli usare **Genera podcast del mio briefing**, con autorizzazione TTS separata, oppure riprodurre/scaricare l'audio già presente. Il modulo podcast esistente produce un estratto di circa 1–2 minuti, anche per briefing da 5/10 minuti. I prodotti generali restano nelle sezioni precedenti.

La selezione usa parole normalizzate, non un nuovo modello: almeno il 60% delle parole significative di un interesse deve comparire nel passaggio. Un interesse gradito pesa il doppio, un salvato pertinente aggiunge 0,5, un argomento escluso prevale sui boost positivi. Si alternano testate/date verificate, con ripiego sul PDF se mancano metadati, rimuovendo duplicati testuali e quasi identici tramite il componente esistente. Sinonimi e articoli impaginati su più colonne possono limitare la selezione: non viene promessa una ricostruzione completa degli articoli. Il formato visuale mostra la distribuzione delle corrispondenze agli interessi, senza inventare relazioni tra notizie.

Il tempo corrisponde a un massimo indicativo di 240/600/1200 parole: possono esserci meno contenuti quando le fonti non bastano. Il limite Python conserva solo notizie complete e validate; non taglia frasi o citazioni per riempire il minutaggio. La copertura parziale dell'archivio è sempre segnalata. La cache distingue modello, versione, fonti, copertura e tempo: le preferenze contano quando cambiano effettivamente la selezione o l'ordinamento. Cambiare soltanto formato non richiede una nuova sintesi. Le vecchie edizioni dei briefing restano consultabili come risultati salvati, senza aggiornarsi silenziosamente alle nuove preferenze.

Il profilo locale `demo` è memorizzato in `data/profiles.sqlite3`, con preferenze, feedback espliciti e copie dei passaggi salvati. Non è autenticazione: tutte le persone che usano questa installazione condividono lo stesso profilo demo. Non inserire dati riservati. I prodotti personali e i loro audio sono isolati sotto `data/personalized/<hash-identificativo>/`; questa cartella e i database personali sono esclusi dal versionamento. **Cancella preferenze e storico demo** rimuove il profilo, i salvati, i briefing personali e i relativi WAV, lasciando invariati archivio, indice e prodotti generali. ID utente, feedback e storico non sono inseriti nel prompt; l'invio dei passaggi scelti e del tempo richiede sempre consenso esplicito. Non ci sono notifiche esterne, tracciamento implicito o generazioni all'avvio.

Test mirati: `.\.venv\Scripts\python.exe -m pytest -q tests/test_personalization.py`. Coprono persistenza, modifiche, feedback, rilevanza, diversificazione, duplicati, budget di lettura, citazioni, cache, errori API, cancellazione selettiva, tre formati e accesso offline ai prodotti. L'integrazione con Chroma temporaneo verifica che consigli e letture non alterino SQLite, documenti, metadati o vettori. Le API sono simulate.

## Task 8 — Valutazione sperimentale

Il framework indipendente `python -m edicola.evaluation --help` esporta lo snapshot dei soli chunk indicizzati, prepara dataset **vuoti da annotare manualmente**, controlla PDF/pagina/ID e calcola Precision@K, Recall@K, MRR@K e copertura documentale. I giudizi incompleti producono metriche mancanti quando non verificabili, non etichette negative inventate. La verifica tecnica delle citazioni resta distinta dalla valutazione umana di accuratezza, fedeltà e completezza.

Il [protocollo completo](evaluation/README.md) include i comandi per creare il dataset, avviare benchmark limitati e autorizzati, compilare le schede RAG/prodotti editoriali e confrontare profili demo senza API. I benchmark riutilizzano i componenti backend e misurano retrieval, generazione, totale, tentativi API e HTTP, senza cambiare la pipeline. Esportano run grezza, CSV, tabelle, grafici Altair e report Markdown con provenienza, conteggi e dati mancanti. Media/mediana da almeno un campione valido; P95 da almeno 20. I grafici HTML usano Vega da CDN all'apertura; il resto del report è consultabile offline. Nessuna dipendenza aggiunta.

Non sono state effettuate chiamate Gemini reali né compilate etichette o misure sperimentali reali durante lo sviluppo. Le fixture sintetiche verificano soltanto il software. Per la tesi servono domande/giudizi manuali, esperimenti reali esplicitamente avviati e schede umane effettivamente compilate. Conservare cataloghi e risultati sotto `evaluation/work/` e `evaluation/results/`, esclusi da Git.

## Task 9A — Navigazione e lettore PDF locale

La piattaforma è divisa in sette schede: **Home**, **Archivio**, **Chat AI**, **Approfondimenti**, **Timeline e Mappe**, **Podcast**, **Personalizzazione**. I controlli e i consensi restano montati durante la navigazione: cambiare scheda, pagina o zoom non genera richieste Gemini. L'acquisizione automatica preesistente resta invariata.

Ambiente verificato: Streamlit **1.66.1**, pypdf **6.21.2**, Pillow **13.0.0**. L'estensione facoltativa di `st.pdf` non era installata. È stato aggiunto **pypdfium2 5.14.0** (wheel Windows di circa 3,9 MB): PDFium renderizza direttamente ogni pagina del PDF originale, inclusi grafica, fotografie, colonne, font e rotazioni, senza OCR né ricostruzione dal testo estratto. La dipendenza è dichiarata in `requirements.txt`; Streamlit richiede ora almeno 1.66 per le schede con stato. Nessun componente, font o script del lettore viene caricato da CDN o da servizi esterni.

Per provare il lettore:

1. Avviare `.\.venv\Scripts\python.exe -m streamlit run app.py` e aprire **Archivio**.
2. Cliccare una copertina della galleria per aprire il quotidiano. Le frecce della barra compatta consentono di sfogliarlo.
3. La pagina intera è inizialmente adattata all'area visibile. I pulsanti − e + regolano lo zoom dal 75% al 200%; il comando **Adatta alla pagina** ripristina la vista iniziale. Il lettore consente scorrimento interno quando necessario.
4. Usare **Schermo intero** nella barra se consentito dal browser, ed **Esc** per uscire.
5. **Scarica PDF** restituisce gli stessi byte del documento acquisito. **← Edizioni** riporta alla galleria. I dettagli tecnici sono disponibili soltanto nella modalità diagnostica configurata sul server, descritta sotto.

Il lettore visualizza un raster fedele della pagina originale, non un documento riscritto dai chunk. Non offre selezione/ricerca del testo o link interni cliccabili nel raster: per queste funzioni aprire il PDF originale scaricato. Si renderizza soltanto la pagina selezionata, con cache RAM limitata a dodici immagini, raster di circa dodici megapixel massimi e accesso PDFium serializzato fra sessioni. Non vengono creati file di anteprima né modificati PDF, SQLite, Chroma o cache editoriali.

Accanto alle fonti di chat, dossier, briefing, eventi della timeline, mappe e briefing personali è disponibile **Apri PDF · pagina N**. Per mappe e altri prodotti consultare anche i pannelli delle fonti/prove. Il pulsante apre **Archivio** sul quotidiano e sulla pagina corretti, senza rigenerare il prodotto. Sono collegati anche i passaggi consigliati/salvati e le fonti dei podcast, quando ancora presenti nell'archivio corrente.

Prima dell'apertura si verificano appartenenza alla lista acquisita, nome semplice `.pdf`, percorso risolto dentro `data/incoming/`, pagina valida e corrispondenza del chunk alla versione corrente del documento. I byte sono confrontati con SHA-256; il renderer controlla anche il numero reale delle pagine. Percorsi assoluti, traversal, stream NTFS, symlink, file estranei, fonti obsolete e pagine fuori intervallo non consentono l'apertura. Una fonte non disponibile rimane leggibile nel risultato ma non offre un collegamento attivo a un'altra edizione. Gli errori non espongono percorsi locali.

Test mirati: `.\.venv\Scripts\python.exe -m pytest -q tests/test_pdf_viewer.py tests/test_app.py`. Verificano selezione, pagine, zoom, byte originali, raster di grafica senza testo estraibile, controlli dei percorsi, PDF corrotti, fonti obsolete, collegamenti dei prodotti e conservazione dei consensi senza chiamate Gemini. Lo schermo intero dipende dalle autorizzazioni del browser; i test verificano il controllo della disponibilità e l'azione prevista, senza simulare l'API del browser come un risultato reale.

## Task 9A.1 — Archivio editoriale

La vista cliente si apre sulla galleria delle edizioni. Ogni scheda mostra una miniatura autentica della prima pagina, testata e data lette soltanto dai metadati verificati di `data/editions.json`, numero di pagine e azione **Sfoglia**. La copertina intera è cliccabile anche da tastiera. I metadati non vengono dedotti dal nome del PDF: in loro assenza compaiono etichette neutre come “Edizione 1” e “Data non disponibile”. Schede uniformi e griglia responsive consentono la consultazione anche su mobile.

Il lettore è centrato in un contenitore di massimo 740px. L'immagine della pagina parte da una larghezza massima di 520px, ridotta quando necessario per mostrare **tutta** la pagina nell'area alta circa 70% della finestra; l'aspect ratio è conservato. Il limite verticale prevale sulla larghezza indicativa nei portatili con schermo basso e nei documenti molto alti. La barra riunisce frecce, indicatore pagina, adattamento, zoom e schermo intero. Download e ritorno alla galleria sono due azioni compatte sopra il lettore. Una sola pagina viene renderizzata alla volta; l'ingrandimento successivo agisce sull'immagine già presente nel browser, senza nuove estrazioni o chiamate esterne.

I componenti v2 inclusi in Streamlit 1.66.1 permettono il clic sulla copertina senza ricaricare l'intera sessione e senza alterare i consensi. HTML/CSS/JavaScript sono locali; gli stili sono isolati in Shadow DOM e non selezionano elementi delle altre schede. I metadati sono inseriti come testo, mai interpretati come HTML. Miniature e pagine rimangono in cache RAM limitate; non vengono scritti file di anteprima durante l'uso dell'app.

Nella vista cliente non esistono tabella tecnica, hash, ID, testo estratto, selettori di chunk o indicatori di preprocessing, neppure dentro un espansore. Le metriche di acquisizione sopra le schede sono anch'esse riservate alla diagnostica. I dati restano disponibili al backend e possono essere consultati dallo sviluppatore abilitando esplicitamente:

```dotenv
EDICOLA_ARCHIVE_DIAGNOSTICS=1
```

La configurazione può essere inserita nel `.env` locale oppure nell'ambiente del processo (che ha precedenza). Il valore predefinito è `0`; non c'è un interruttore nella UI cliente né un parametro URL per abilitarla. Per tornare alla presentazione cliente impostare `0` e riavviare Streamlit. Nessuna modifica al `.env` esistente viene effettuata automaticamente.

I collegamenti dalle citazioni continuano ad aprire il lettore sul PDF e sulla pagina richiesti, mantenendo i controlli di appartenenza all'archivio, contenuto, versione e intervallo delle pagine. Non sono stati cambiati generatori AI, database, indici, cache dei prodotti o profili.

Verifica automatica:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_archive_design.py tests/test_pdf_viewer.py tests/test_app.py
```

I test coprono miniature reali, metadati mancanti/errati, dati della galleria privi di identificativi tecnici, callback di apertura/sfoglio, fonti dirette, assenza di diagnostica nella vista cliente e compatibilità delle sei schede. Node, quando disponibile, verifica le funzioni JavaScript effettive di adattamento e zoom su dimensioni desktop/mobile, inclusi limiti e proporzioni. I callback dei componenti sono verificati con adattatori di test Python: questi controlli non sostituiscono il collaudo visivo nel browser, che non era disponibile nella sessione di sviluppo. Per la verifica manuale aprire l'app, cliccare una copertina, provare frecce/zoom/adattamento e tornare alla galleria, quindi aprire una citazione da un risultato già presente senza generare nuovi contenuti.
# Preparazione al cloud

Per Streamlit Community Cloud seguire [DEPLOYMENT.md](DEPLOYMENT.md): compatibilità,
snapshot dei soli PDF autorizzati con embeddings esistenti, Secrets, limiti della
persistenza e procedura manuale di pubblicazione. Nessun deployment automatico.

## Esperienza editoriale — Task 11B

L'app si apre su **Home**, accanto alle sei sezioni esistenti. Le edizioni recenti
usano copertine reali e date del file `data/editions.json`; date mancanti o non valide
non vengono ricostruite. La selezione di letture usa soltanto passaggi già indicizzati,
alternati tra PDF e deduplicati localmente. Le brevi citazioni nelle schede sono
estratti originali, **non titoli di articoli riconosciuti**: un passaggio può includere
più notizie. Nessuna fotografia, notizia, data o chiamata API viene aggiunta all'avvio.

**Chat AI** mostra messaggi conversazionali e fonti compatte apribili alla pagina
originale. Il Task 12.2 sostituisce lo storico RAM di otto domande indipendenti del
Task 11B/12.1: ora le chat sono separate e contestuali, con persistenza account
facoltativa. Bozze, navigazione, apertura e consenso da soli non generano risposte:
serve un invio dal composer (il consenso puo riprendere soltanto quello pendente).

In **Personalizzazione → Il mio profilo**, selezionare o scrivere fino a dieci interessi
in **Preferenze e impostazioni**, scegliere tempo/formato e salvare. Le schede permettono
di salvare letture, ritrovabili in **Notizie salvate**, e di aprire il documento originale.
**Il mio briefing** conserva generazione, consensi, cache, fonti e conversione audio
esistenti. Salvataggi, feedback, rimozioni e cancellazioni hanno conferme visibili.

### Autenticazione e profili — aggiornamento Task 11A

La nuova UX usa ora Google OIDC nativo e PostgreSQL Supabase per l'area personale,
secondo [ACCOUNTS.md](ACCOUNTS.md). Il proprietario deriva da issuer e subject
verificati, non dall'email. La UI non importa il vecchio profilo demo in account
personali e non mostra un fallback condiviso se mancano login o database.
Il profilo SQLite resta soltanto nella modalità esplicita di sviluppo Windows.
La configurazione esterna non è stata creata né simulata nel codice pubblico.

### Controllo visivo locale

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Aprire `http://localhost:8501`. Controllare Home, le copertine e i quattro accessi rapidi;
aprire una lettura e verificare il salto al PDF. Provare interessi, salvataggio e rimozione
nel profilo personale configurato, oppure nella demo Windows abilitata esplicitamente.
In Chat AI la generazione richiede consenso e invio volontario;
per controllare solo il layout non è necessario chiamare Gemini.

Ridurre la finestra oppure usare la modalità dispositivo degli strumenti sviluppatore
del browser a **390 px** e **320 px**: verificare che schede e azioni vadano a capo,
che la barra delle sezioni sia scorribile e che il lettore mantenga il comportamento
approvato. Il tema è locale, neutro con accento petrolio, senza font remoti o CDN.
Le schede usano il wrapping nativo Streamlit; la galleria e il lettore conservano
i componenti isolati e i test di geometria precedenti. I test AppTest verificano
rendering e stato dei controlli, non sostituiscono un controllo visivo su browser reali.

Test mirati:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_experience_ui.py tests/test_app.py tests/test_personalization.py tests/test_pdf_viewer.py tests/test_archive_design.py tests/test_cloud.py tests/test_podcast.py tests/test_podcast_ui.py
```

Test degli account, esclusivamente simulati:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_personal_accounts.py
```

### Audit funzionale editoriale — ottobre 2026

La **Rassegna stampa** comprende ora filtri locali per parole chiave e fonti,
consultazione dei gruppi per affinità tematica e briefing della selezione con
citazioni e cache distinta per filtri. I gruppi usano i vettori già presenti,
senza nuovi embedding o nomi di temi inventati. Il campo facoltativo curato
`scope` nelle edizioni può essere `nazionale` o `internazionale`: indica
l’ambito dell’edizione, non classifica automaticamente gli articoli.

In **Briefing → Prodotto editoriale → Infografica** è disponibile un prodotto
locale autonomo a blocchi, fino a otto punti estrattivi verificabili per tema,
con link alle pagine PDF. Non usa Gemini e non produce grafici numerici in
assenza di dati strutturati verificati. Le nove destinazioni restano invariate.

Le **Mappe concettuali** consentono il focus su un nodo e sui suoi collegamenti
già verificati, senza ricerca aggiuntiva. La **Chat AI** offre azioni **Prepara…**
per aprire bozze degli altri prodotti: nessuna generazione parte dalla navigazione.
I **Dossier** dichiarano le edizioni effettivamente citate; i **Podcast** si
cercano anche per argomento e mantengono copioni brevi estrattivi con sezioni
intere e fonti separate dalla lettura. Gli audio già presenti sono mostrati
solo se corrispondono al copione e al modello correnti.

Audit, file, limiti e istruzioni per ogni prodotto: [EDITORIAL_AUDIT.md](EDITORIAL_AUDIT.md).
Test specifici, con API simulate:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_editorial_audit.py
```

### Aggiornare il corpus senza perdere l’indice

**Nuovo percorso per il gestore locale:** aprire con doppio clic
`Gestione archivio.cmd`. Il menu permette stato, preparazione dei soli nuovi file,
metadati verificati, anteprima e autorizzazione di batch da 10/20/50 chunk, ripresa
dopo interruzioni e preparazione di snapshot autorizzati. Non è un pannello pubblico
e non assegna privilegi agli account Google. Guida senza comandi Python:
[GESTIONE_ARCHIVIO.md](GESTIONE_ARCHIVIO.md).

Il diario/coda locale conserva il progresso; nessun batch successivo parte da solo.
Questa regola vale per la modalità a batch singolo (opzione 3). Con la nuova
**6 — Indicizza tutti i chunk mancanti** una conferma autorizza il piano completo:
i batch, ciascuno di massimo 50 chunk, proseguono automaticamente fino a completamento
o arresto per errore, quota o Ctrl+C. Il riepilogo mostra PDF, richieste previste e
massimo dei retry; dopo un arresto la ripresa richiede una nuova conferma dei soli
mancanti. Non parte alcun invio dalla semplice apertura della console.
Quote e problemi temporanei hanno retry limitati e pausa persistente. Le cache
distinguono corpus e selezioni tramite versioni deterministiche, senza cancellare
prodotti storici. I filtri della rassegna includono date curate e ultima edizione.

Usare `python -m edicola.corpus_update --refresh --report data/corpus_updates/latest.json`
per acquisizione/chunking locali con backup preventivo, senza Gemini. Verificare
poi `python -m edicola.indexing --dry-run --limit 50 --keep-stale`. Solo un comando
successivo esplicitamente autorizzato può generare gli embedding mancanti.
`--keep-stale` conserva gli eventuali vettori storici, esclusi comunque dalla
ricerca corrente. Il tool distingue nuove edizioni, metadati incompleti, chunk
già indicizzati e mancanti, copertura storica e fonti obsolete delle cache.

Le nuove fonti entrano nei sette prodotti solo dopo l’indicizzazione; il podcast
richiede prima un briefing/dossier aggiornato. Non vengono cancellati o rigenerati
automaticamente i prodotti precedenti. Per uno snapshot locale nuovo e già
autorizzato è disponibile `python -m edicola.cloud --validate PERCORSO`.
Procedura completa, stato verificato e operazioni prima della pubblicazione:
[CORPUS_UPDATE.md](CORPUS_UPDATE.md).

