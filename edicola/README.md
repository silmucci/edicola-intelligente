# Struttura interna di Edicola Digitale Intelligente

La cartella raccoglie i moduli Python per responsabilità:

- **ui/** – componenti Streamlit comuni, navigazione, lettura e consultazione dell'archivio
- **podcast/** – preparazione del copione, sintesi audio, cache, riproduzione e interfaccia dedicata
- **chat/** – sessioni, cronologia, citazioni e persistenza delle conversazioni
- **retrieval/** – RAG, embedding, ricerca semantica, selezione del contesto e indice vettoriale
- **pdf/** – ingestione, OCR, estrazione, struttura dei quotidiani e aggiornamenti PDF
- **editorial/** – briefing, rassegna stampa e feed personalizzato
- **knowledge/** – timeline, mappe concettuali, relazioni, verifiche e presentazione
- **personalization/** – profili, preferenze, dati personali e interfaccia profilo
- **evaluation/** – ground truth, benchmark, giudice, metriche e report
- **infrastructure/** – configurazione, cloud, identità, autorizzazioni e archiviazione
- **maintenance/** – comandi amministrativi, indicizzazione, snapshot e manutenzione

## Compatibilità

La riorganizzazione **non** cambia gli import storici. Si continua a scrivere, per
esempio, `from edicola.rag import ask_question` e a eseguire
`python -m edicola.indexing`, anche se i file sono stati spostati.

`edicola/__init__.py` aggiunge le cartelle alla ricerca dei moduli Python.
Le sottocartelle **non** hanno un proprio `__init__.py`: sono gruppi di file,
non namespace Python distinti. Non usare import come
`from edicola.retrieval.rag import ask_question`, perché ciò rischierebbe
di caricare lo stesso modulo sotto due nomi differenti.

Questo refactoring conserva le implementazioni e i nomi delle funzioni;
l'unico adattamento interno riguarda i percorsi relativi dei file e
l'individuazione del codice per la provenienza dei benchmark.
