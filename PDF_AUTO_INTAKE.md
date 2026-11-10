# Acquisizione automatica PDF e conservazione delle edizioni

L'Edicola legge automaticamente i nuovi PDF depositati in `data/inbox` quando
l'app viene aperta o ricaricata. Questa è una funzione **locale**: nello snapshot
pubblicato (`EDICOLA_CLOUD_DEMO=1`) l'importazione è disabilitata e i 12 PDF
distribuiti non vengono modificati.

## Utilizzo senza terminale

1. Aprire il progetto in VS Code o GitHub Codespaces.
2. Nell'Explorer aprire `data/inbox`. Depositare uno o più file PDF con
   **Upload / Carica**, o trascinandoli da una cartella.
3. Ricaricare la pagina dell'app Streamlit, porta 8501. I nuovi quotidiani
   compaiono in `In edicola`; l'estrazione del testo e il chunking avvengono
   in locale, senza chiamate API.
4. Se il titolo e la data non sono già curati in `data/editions.json`,
   l'edizione rimane correttamente etichettata come senza data verificata.
   L'app non inventa testata e data.

`data/inbox` è una **cartella transitoria**, non la cartella di lettura finale.
Usare questa cartella per le nuove edizioni: copiare file con lo stesso nome
direttamente in `data/incoming` può sovrascrivere la versione precedente.

## Come funziona

- Controllo nome e tipo PDF, limite **75 MiB** per file, lettura da file
  regolare e controllo del fatto che non stia cambiando durante il caricamento.
  I file danneggiati o non ammissibili rimangono in `inbox` e non vengono
  pubblicati. Massimo dieci PDF elaborati per caricamento: ricaricare per i successivi.
- SHA-256 unico per contenuto. Se una copia identica esiste già in
  `data/incoming`, la copia transitoria viene scartata e la versione attiva
  resta immutata. Un PDF rinominato ma identico **non** richiede una nuova estrazione.
- Se il nome è già presente ma il contenuto differisce, la nuova edizione
  entra con `nome--<12caratteriSHA>.pdf`. Il PDF precedente rimane
  fisicamente accessibile. Non si riscrivono mai le edizioni già presenti.
- La pubblicazione del file è atomica: non appare in `incoming` finché la
  copia non è completa. L'estrazione viene memorizzata in SQLite usando
  lo stesso SHA, così l'app non ripete la lettura appena effettuata.
- Le pagine estratte vengono divise nei chunk esistenti; si riusano le
  estrazioni e i chunk con SHA già acquisito. Riconoscimento locale degli
  articoli e delle continuazioni disponibile in modo automatico sulle
  estrazioni PyMuPDF adatte. Non vengono eseguiti OCR o modelli locali.
- Il vecchio archivio e gli embedding **non vengono sostituiti**.
  In una nuova versione dello stesso nome, ogni chunk con **testo, pagina
  e intervallo identici** conserva esattamente il prompt della precedente
  versione. Se il suo vettore è già indicizzato, viene copiato localmente
  senza chiamate Gemini; i passaggi cambiati rimangono `pending`.
  Senza un vettore originale valido, anche il passaggio identico rimane
  `pending`. Solo un'autorizzazione esplicita può generare gli embedding
  mancanti: nessun invio parte dalla inbox.
- I quotidiani fisicamente rimossi da `incoming` non compaiono più
  nell'app, anche se lo storico SQLite resta intatto. Per conservare le
  edizioni storiche non spostarle o eliminarle da `incoming`.

## Docker e Codespaces

La configurazione Docker locale ora monta `./data/inbox` e
`./data/incoming` in lettura/scrittura nel container, senza includere
i PDF nell'immagine. Riavviare la configurazione dopo aver aggiornato
il repository:

```bash
docker compose up -d --build
```

Poi depositare il file nella cartella del progetto `data/inbox` e ricaricare
l'app. Nella variante `compose.snapshot.yaml` il ripristino dello snapshot
resta in sola lettura, senza import automatico.

La semplice esecuzione `streamlit run app.py` da Codespaces importa dalla
`data/inbox` del Codespace, **non** dai 12 PDF già presenti nello snapshot
`deployment/seed`. Per utilizzarli basta continuare con la modalità
di anteprima snapshot documentata in `DOCKER.md`, senza copiarli nella inbox.

## Sicurezza e limiti

- Cartella e PDF non vengono mai inviati a GitHub: il contenuto di
  `data/inbox` e `data/incoming` è ignorato dal versionamento.
  Non fare commit dei quotidiani senza autorizzazione di distribuzione.
- Non usare la inbox come cartella condivisa con utenti non autorizzati.
  L'Edicola per i lettori **non** espone un endpoint di upload pubblico.
- La presenza dei PDF non prova che gli embedding siano completi.
  L'elaborazione locale automatica non consuma quote Gemini e non assicura
  che le nuove notizie siano già ricercabili semanticamente.
- Se un batch Gemini è in corso, l'importazione può essere rimandata
  al successivo caricamento per evitare scritture concorrenti.
