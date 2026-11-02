# Snapshot pubblico aggiornato

Il gestore ha autorizzato esplicitamente la distribuzione pubblica dei dodici PDF
selezionati e dei dati derivati, inclusi consultazione e download.

Il pacchetto `deployment/seed` comprende:

- 12 PDF, con testata e data curate nei metadati;
- 1.407 chunk preparati;
- 1.361 embedding esistenti, modello Gemini Embedding 2, dimensione 768;
- 46 chunk ancora mancanti nell'indice: la copertura semantica resta parziale.

L'esportazione non ha eseguito nuove chiamate Gemini o ricostruito l'indice locale.
Non include Secrets, credenziali, profili, chat, cache editoriali/audio, diario dei
batch o backup. Manifest, hash dei file, riferimenti dei vettori e dimensioni
sono stati verificati offline prima del caricamento.

Il corpus locale resta separato dallo snapshot pubblico. L'aggiunta di altre
edizioni richiede una nuova selezione e autorizzazione alla distribuzione.
