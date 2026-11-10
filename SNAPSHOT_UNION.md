# Unificare lo snapshot GitHub con i nuovi quotidiani del Codespace

Questa procedura serve quando l'Edicola locale ha già acquisito nuovi PDF
in `data/incoming`, mentre i 12 quotidiani precedenti e i relativi embedding
sono conservati nel pacchetto `deployment/seed`.

**Non copiare semplicemente la cartella seed al posto di data/**: perderesti
l'archivio locale e potresti azzerare i chunk preparati o i vettori.

## Procedura in Codespaces

Verifica prima lo snapshot GitHub (sola lettura, nessuna API):

```bash
python -m edicola.cloud --validate deployment/seed
```

Poi calcola il piano di unione **senza modifiche**:

```bash
python -m edicola.snapshot_union --dry-run
```

Nel caso dei 10 nuovi PDF e dei 12 già presenti nel pacchetto, il risultato
atteso è circa 22 PDF e 2.606 chunk complessivi, dei quali 1.361 con un
embedding nello snapshot. I numeri definitivi sono quelli del piano:
file con lo stesso SHA non producono chunk distinti.

**Ferma Streamlit con Ctrl+C prima di applicare** (nessun terminale del
Codespace deve tenere il registro o Chroma aperti). Accertati che non siano
in corso comandi di indicizzazione. Poi:

```bash
python -m edicola.snapshot_union --apply
```

Il comando importa i 12 vecchi PDF mancanti, le estrazioni e i chunk
salvati, gli embedding già generati e i metadati delle edizioni.

Se l'unione ha successo, verifica:

```bash
python -m edicola.indexing --dry-run
```

L'esito dovrebbe riportare `already_indexed` di almeno 1.361 se i vettori
dello snapshot non entrano in conflitto con dati locali; i 1.199 chunk
nuovi restano `pending` finché non sono indicizzati. Nello snapshot
originario c'erano anche 46 vecchi chunk non indicizzati: su documenti
tutti distinti, il totale atteso in sospeso è 1.245.

Riavvia Streamlit solo dopo queste verifiche:

```bash
python -m streamlit run app.py --server.address 0.0.0.0
```

Apri la scheda **Porte** del Codespace, porta **8501**.

## Garanzie e limiti

- Nessuna chiamata Gemini o generazione di embeddings dall'operazione di
  unione. `api_key_configured: false` non impedisce la fusione locale.
- Lo snapshot GitHub originale rimane immutato.
- Un backup del registro SQLite viene creato in
  `data/corpus_updates/before-seed-union-…/archive.sqlite3`.
  Se già esistono un archivio Chroma o un catalogo locale delle edizioni,
  vengono conservate copie anche di questi.
- I PDF locali con lo stesso nome ma hash differente causano un errore:
  **non vengono sovrascritti**. I vettori locali conflittuali non vengono
  sostituiti.
- Dopo un'interruzione il comando può essere ripetuto. Conservare il
  backup, non spostare/eliminare manualmente i file in `data/incoming`.
- Non modificare `deployment/seed`, non fare commit delle copie dei
  quotidiani locali e non pubblicare archivi Chroma o dati privati.
- Le nuove notizie entrano nella ricerca semantica solo dopo
  indicizzazione autorizzata dei rispettivi chunk. L'utilizzo di Chat AI,
  Mappe, Timeline o Podcast con nuovi prompt richiede una chiave Gemini
  configurata e i consensi previsti dall'app.
- I 12 PDF storici sono preservati con i loro **chunk originali**:
  il successivo aggiornamento delle estrazioni e dei metadati degli
  articoli deve avvenire separatamente, dopo backup e verifica, per non
  invalidare gli embedding già disponibili.
