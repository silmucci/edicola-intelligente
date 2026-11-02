# Podcast indipendente e icone dell’intestazione

## Causa del comportamento precedente

La UI chiamava `list_products()` prima di mostrare il comando e terminava se non
trovava letture valide. `generate_podcast(product_key)` richiedeva una riga nella
cache editoriale; `prepare_script()` ne leggeva le sezioni. Era un convertitore
di letture salvate, non un prodotto autonomo. Non era un problema del TTS.

## Nuovo flusso

1. L’utente preme **Genera podcast**, senza argomento obbligatorio. Il comando
   è presente anche se non esiste alcun Briefing. Prima di inviare contenuti
   vengono richiesti entrambi i consensi, usando i dialoghi esistenti.
2. `generate_standalone_podcast()` legge solo il catalogo attualmente indicizzato.
   Riusa `balanced_briefing`, vettori esistenti e il budget di passaggi interi,
   alternando le edizioni e senza embedding o richieste per singolo PDF.
3. Una richiesta al modello testuale già configurato prepara titoli e sintesi
   brevi adatte all’ascolto. Schema e validazione delle citazioni sono condivisi
   con il Briefing; il prompt Podcast è distinto e il DB Briefing non è coinvolto.
   Sono respinti anche numeri non presenti nelle evidenze citate. Introduzione e
   conclusione sono frasi editoriali fisse, senza nuove affermazioni sulle notizie.
4. La composizione conserva sezioni complete entro 240 parole/3500 caratteri,
   inclusi saluto e chiusura. Identificativi, rimandi e nomi PDF non sono letti.
   Copione, prove e riferimenti vengono salvati nella cache Podcast dedicata.
5. Il TTS esistente genera il WAV. Si controllano completamento dichiarato dal
   servizio, formato, campioni, durata massima e una soglia minima prudente
   rispetto alla lunghezza del testo. Audio troppo brevi non vengono pubblicati.
6. Player, download, data di preparazione, durata, testo e fonti sono mostrati
   nella sezione Podcast. Gli episodi passati sono selezionabili senza richieste AI.

Se il TTS fallisce, il copione resta in cache e nella sessione. **Riprova solo
l’audio** rilegge quel copione e verifica le fonti correnti, senza generare nuovo
testo. Se le fonti sono cambiate, il retry viene rifiutato e serve un nuovo episodio.
Un errore non cancella gli episodi già disponibili. Un normale nuovo invio con lo
stesso corpus/modello riusa anch’esso il copione; la voce può cambiare senza rigenerarlo.

## Cache, consensi e compatibilità

- Copioni: `data/podcast_cache/standalone/scripts/`.
- Indici degli episodi: `data/podcast_cache/standalone/episodes/`.
- WAV e manifest vocali: motore comune `data/podcast_cache/`.
- Identità del copione: snapshot/fingerprint delle fonti, strategia
  `standalone-podcast-v1`, modello testuale, configurazione e istruzioni.
- Identità audio: testo, versione TTS, modello, voce, stile e contesto con
  strategia, snapshot, modello del copione e chiave del copione.
- Scritture atomiche e lock separati per testo e audio evitano richieste
  concorrenti duplicate. Nessun retry automatico, inclusi quelli SDK.
- Il consenso testuale passa da `text-v2` a **`text-v3`**, aggiungendo i copioni
  Podcast alla descrizione del trattamento. Una scelta vecchia non autorizza il
  nuovo uso. Audio resta `audio-v1`, con descrizione chiarita sul copione che
  viene inviato (stesso servizio e stessi dati: testo e voce); identità e scelta sono ricontrollate prima
  delle chiamate, anche tra i due stadi. Nessuna migrazione o cancellazione di consensi.
- Il vecchio `generate_podcast(product_key)` resta per ascolti personali e usi
  storici, delegando al medesimo motore audio. Le sue identità di cache sono
  invariate. La consultazione degli episodi storici funziona anche se il database
  Briefing manca o non è leggibile, con etichette neutre quando necessario.

Briefing rimane autonomo e testuale: il generatore non è stato modificato e
non prepara audio. Il Podcast non chiama `generate_product()` né scrive
`editorial.sqlite3`. Non sono cambiati modelli configurati, dipendenze, corpus,
indicizzazione, account o logiche di autenticazione. Nessuna cache esistente è
stata eliminata. I nuovi percorsi sono già esclusi da Git dalle regole di `data/`.

## Intestazione

Logo e nome a sinistra; ricerca e Profilo come piccole icone native a destra,
con descrizioni di aiuto. Il menu Profilo mantiene accesso Google, area personale,
privacy e autorizzazioni. Nessun duplicato nelle sette card, il cui design non è
stato toccato. La navigazione conserva anche la scelta dell’episodio corrente.

## File modificati

- `edicola/podcast_draft.py` (nuovo): selezione, generazione/validazione e cache copione.
- `edicola/standalone_podcast.py` (nuovo): orchestrazione, retry audio e catalogo episodi.
- `edicola/podcast.py`: motore TTS condiviso, contesto cache facoltativo e controllo durata.
- `edicola/podcast_text.py`: limiti facoltativi per riservare spazio alla cornice del copione.
- `edicola/podcast_ui.py`: comando autonomo, due consensi, player, fonti, storico e retry.
- `edicola/consent.py`: descrizione e versione della sola finalità testuale.
- `edicola/header_ui.py`: icone a destra e logo a sinistra.
- `edicola/product_navigation.py`: sola conservazione dello stato episodio; card invariate.
- `tests/test_standalone_podcast.py` (nuovo), `tests/test_podcast_ui.py`,
  `tests/test_consent.py`: regressioni del nuovo flusso e aggiornamento versioni nei test.
- `AGENTS.md`, `README.md`, questo documento: istruzioni aggiornate senza eliminare
  il resoconto dei percorsi storici.

Le altre modifiche già presenti, compresi Rassegna, Timeline, Mappe e componenti
grafici non ancora pubblicati, sono state conservate. Intatte anche le cancellazioni
e gli accessi negati preesistenti sotto `deployment/seed/`.

## Verifica e limiti

I test offline usano mock SDK, notizie sintetiche e WAV di prova in cartelle
temporanee isolate. Verificano indipendenza dal Briefing, output non supportati,
consensi separati e revoca tra stadi, riuso di copione/audio, errore TTS, cambi di
fonti/modello/voce, storico, assenza di chiamate alla navigazione e accesso Google
dal controllo del Profilo. Sono inclusi i test esistenti del TTS e dei prodotti
testuali, oltre alla consultazione degli audio personali.

Non sono state eseguite chiamate Gemini reali, modifiche ai dati dell’installazione,
commit, push o deploy. **131 test superati**, con quattro avvisi delle dipendenze
esistenti: test del nuovo flusso, TTS storico, UI, consensi, generatore editoriale,
regressioni del lettore e consultazione di testo/audio personali salvati.
La suite completa non è stata eseguita. Nessun collaudo visivo a viewport desktop
o smartphone, né ascolto di una voce reale: AppTest verifica i controlli e i flussi,
non il layout del browser. Il WAV valido e il controllo della durata non provano
che ogni parola sia stata pronunciata; le citazioni letterali non costituiscono
una verifica semantica automatica completa della parafrasi. Questi controlli
restano da svolgere con un collaudo autorizzato, senza considerare i mock come
risposte effettive del servizio.
