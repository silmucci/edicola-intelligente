# Acquisizione strutturata e recupero degli articoli

Questa estensione è **opzionale e incrementale**: non aggiunge prodotti editoriali,
non cambia la navigazione e non chiama Gemini durante il caricamento dell'app.

## Cosa fa

- I PDF **nuovi** vengono estratti con PyMuPDF (blocchi, coordinate e ordine di lettura
  per colonne). `pypdf` resta fallback di singola pagina, anche quando PyMuPDF
  perderebbe una parte significativa del testo.
- Le pagine interne con **un solo titolo dominante** sono identificate già in locale.
  Una pagina successiva senza titolo viene collegata soltanto se inizia come
  continuazione e non presenta altri titoli forti. I metadati riportano titolo,
  ID dell'articolo, pagine collegate e ruolo della pagina. Copertine complesse,
  pagine ambigue e pagine senza titolo verificabile restano escluse.
- L'analisi Vision di Gemini è un **comando esplicito**, limitato a poche pagine
  (prima pagina, pagine richiamate e aperture di sezione riconoscibili),
  escludendo le pagine già riconosciute con sufficiente evidenza geometrica.
  Il PDF completo non viene inviato; vengono inviati solo PNG delle pagine scelte
  a 200 DPI. Nessun OCR, nessun modello locale.
- I titoli proposti da Vision vengono **verificati letteralmente** contro il testo
  estratto. Titoli assenti/ambigui e riferimenti fuori intervallo vengono scartati.
  Il corpo resta testo originale, senza riscrittura o limite di 1200 caratteri.
- La segmentazione degli articoli è conservativa ma non perfetta: un intervallo
  termina al titolo successivo verificato; dove manca un confine, può non essere
  sicuro attribuire tutti i chunk a un articolo. I chunk che attraversano
  confini riconosciuti **non** ricevono l'identità articolo.
- Un collegamento tra pagine viene attivato solo se il richiamo è presente nel
  testo della pagina sorgente e il **medesimo titolo** viene verificato nella
  pagina di destinazione già analizzata. Richiami ambigui non collegano articoli.
- I metadati verificati sono letti da `data/editorial_pages.sqlite3`. I chunk
  continuano ad avere ID, testo e citazioni a pagina originali. La ricerca
  corpus-wide può includere altri chunk dello stesso articolo verificato,
  senza ulteriori richieste di embedding. I prodotti selezionano poi nel
  proprio budget.

## Attivazione su una copia locale dei dati

Installare prima le dipendenze da `requirements.txt` e configurare
`GEMINI_API_KEY` nell'ambiente privato. Non versionare le credenziali o i PDF.

**Per PDF già acquisiti che richiedono una nuova estrazione, eseguire il punto 3
prima del punto 2**: una nuova estrazione può cambiare il testo e rende
obsoleta l'eventuale cache Vision precedente.

### Verifica immediata da GitHub Codespaces (senza API)

I dodici PDF dello snapshot sono in `deployment/seed/data/incoming`, non
necessariamente in `data/incoming`. Il comando seguente cerca in entrambe le
cartelle, legge il PDF in memoria, e **non scrive file**:

```bash
python -m edicola.pdf_diagnostics --pdf "7ZycEw6ad2611b84bd0_full.pdf"
```

Nel campione A4 Quotidiano 17/10/2026 (35 pagine), l'analisi locale con
PyMuPDF ha identificato **25 articoli** su **33 pagine**, comprendendo
**8 pagine di continuazione**. Pagina 1 e pagina 35 non sono state attribuite
ad articoli completi. Il risultato è euristico, non una verifica editoriale
manuale né una modifica dell'indice pubblicato.
\n1. **Anteprima senza rete né scritture:**

   ```powershell
   python -m edicola.pdf_enrichment --dry-run --max-pages-per-pdf 4 --limit 4
   ```

2. **Analisi su un solo PDF già disponibile (con invio esterno esplicito):**

   ```powershell
   python -m edicola.pdf_enrichment --pdf "nome-quotidiano.pdf" --limit 2 --max-pages-per-pdf 4 --authorize-external
   ```

   Ri-eseguire il comando non reinvia le pagine con cache valida per hash
   PDF, testo, modello e versione di analisi. Per una pagina fallita il
   comando non conserva risultati parziali invalidi.

3. **Aggiornamento dell'estrazione di un PDF *già presente*** (facoltativo).
   Le estrazioni vecchie rimangono attive finché non si sceglie l'aggiornamento:

   ```powershell
   python -m edicola.pdf_refresh --pdf "nome-quotidiano.pdf" --dry-run
   python -m edicola.pdf_refresh --pdf "nome-quotidiano.pdf" --apply
   ```

   `--apply` crea un backup coerente del registro in
   `data/corpus_updates/archive-before-layout-*.sqlite3`, aggiorna
   solo le estrazioni indicate e rigenera i chunk locali. Non tocca
   `data/chroma`. Se i testi sono cambiati, alcune vecchie embedding
   diventano obsolete, ma non vengono rigenerate automaticamente.

4. **Controllo dell'indice, senza rete:**

   ```powershell
   python -m edicola.indexing --dry-run
   ```

   Se ci sono nuovi chunk, la sincronizzazione rimane esplicita e
   autorizzata (esempio: `python -m edicola.indexing --limit 20
   --authorize-external --keep-stale`). La presenza di soli
   `metadata_updates` non richiede nuove embedding, ma va applicata
   tramite il comando esplicito di sincronizzazione.

## Sicurezza, compatibilità e limiti

- Avviare Streamlit, aprire i PDF, sfogliare, cercare localmente e consultare
  fonti **non** avvia la Vision. L'analisi può usare quote a pagamento:
  verificare il piano API prima dell'autorizzazione.
- I vecchi risultati editoriali, podcast e citazioni non vengono cancellati
  da questi comandi. Le citazioni a chunk obsoleti possono però richiedere
  una nuova generazione autorizzata.
- La Vision non prova la verità dei contenuti: fornisce soltanto proposte
  sull'impaginazione, validate contro il PDF.
- Il riconoscimento locale di articoli si applica alle nuove estrazioni
  PyMuPDF o dopo un refresh esplicito: i dati storici `pypdf` non possiedono
  ancora i blocchi geometrici. La diagnostica dello snapshot non attiva
  automaticamente queste annotazioni nel database.
- L'estrazione geometrica su impaginazioni editoriali complesse non è
  infallibile. Per PDF scansionati senza testo non c'è OCR: queste pagine
  restano fuori dall'annotazione e dal recupero RAG testuale.
- I PDF già acquisiti non vengono reprocessati automaticamente al cambio
  di versione; usare `pdf_refresh` su un campione di prova, confrontare
  prima/dopo e solo poi estendere agli altri documenti.
- L'analisi **locale** del PDF reale è stata effettuata senza Gemini. Vision
  non è stata eseguita su quotidiani reali: i relativi test usano PDF sintetici
  e nessuna API reale.
