# Edicola Digitale Intelligente — Docker e anteprima su Codespaces

Questa configurazione introduce un ambiente **locale e isolato** con Python,
Streamlit, SQLite e Chroma. Gemini resta un servizio esterno tramite API:
non vengono scaricati né avviati modelli AI locali.
L'avvio abituale su Windows con `streamlit run app.py` resta disponibile.

## Prerequisiti

- Docker Desktop avviato in modalità container Linux e Compose v2.24 o superiore
  (per `env_file.required: false`).
- Il repository clonato sul computer.
- Connessione Internet per scaricare immagine e dipendenze al primo build.

## Anteprima con i 12 PDF gia pubblicati (GitHub Codespaces, anche da tablet)

Il repository contiene gia `deployment/seed`: e lo snapshot che la versione
Streamlit Cloud usa per i quotidiani. Per mostrarli anche in Docker **senza
ricaricare i PDF e senza chiamare Gemini**, il file `compose.snapshot.yaml`
attiva la stessa funzione di ripristino (`prepare_cloud`). In un Codespace,
apri il Terminale sul branch di questa modifica ed esegui:

```bash
git pull
docker compose -f compose.yaml -f compose.snapshot.yaml up --build -d
```

La prima ricostruzione di Chroma puo richiedere tempo. In Codespaces apri
**Ports / Porte**, inoltra la porta **8501** e seleziona **Open in Browser**.
Lascia la visibilita **Private**. All'inizio non servono chiavi Gemini per
sfogliare i quotidiani, le fonti e i passaggi gia indicizzati.

Per vedere i log (utile se l'app sembra ancora in avvio):

```bash
docker compose -f compose.yaml -f compose.snapshot.yaml logs -f edicola
```

Per fermare l'anteprima senza cancellare il volume:

```bash
docker compose -f compose.yaml -f compose.snapshot.yaml down
```

**Attenzione ai diritti:** usa lo snapshot soltanto se i PDF e i contenuti
derivati sono autorizzati per questo utilizzo. Il repository e pubblico e
l'anteprima non deve diventare pubblica senza una verifica separata dei diritti.
La presenza dei file in GitHub non dimostra che siano liberamente distribuibili.

Lo snapshot viene **montato in sola lettura**: non finisce nell'immagine Docker.
Viene verificato il manifest (hash dei file) e l'indice Chroma viene ricostruito
localmente dagli embedding esistenti, in un volume dedicato. Non si esegue OCR,
nuova estrazione o indicizzazione Gemini. Il corpus e un'istantanea:
non include automaticamente i PDF nuovi presenti soltanto sul PC. La modalita
account continua a richiedere i Secrets OIDC e PostgreSQL; senza di essi si
consulta come ospite e non si utilizza il profilo Google.

## Avviare l'app in modalita locale, senza snapshot

Aprire PowerShell nella cartella principale del repository ed eseguire:

```powershell
docker compose up --build -d
```

Aprire **http://localhost:8501** nel browser.

Per controllare lo stato e i log:

```powershell
docker compose ps
docker compose logs -f edicola
```

Per arrestare il container senza cancellare i dati:

```powershell
docker compose down
```

**Non usare `docker compose down -v`** se vuoi conservare database,
indice e cache memorizzati nel volume Docker.

## Dati e persistenza

I due avvii sono alternativi: `docker compose up --build -d` utilizza i PDF
locali, mentre il comando con **entrambi i file** (`-f compose.yaml -f
compose.snapshot.yaml`) utilizza lo snapshot del repository. Evita di avviare
entrambe le configurazioni contemporaneamente con lo stesso nome di progetto.


- I PDF presenti in `data/incoming` sul PC vengono montati **in sola lettura**
  nel container; non entrano nell'immagine Docker o nel repository.
- SQLite (`data/archive.sqlite3`), Chroma (`data/chroma`) e le cache
  del container sono conservati in un volume Docker persistente `edicola_data`.
- L'indice Chroma e il database SQLite della precedente installazione Windows
  **non vengono importati automaticamente** nella modalità locale: il volume Docker è separato. La modalità snapshot, invece, ricostruisce l'indice dai vettori del pacchetto pubblicato.
  Al primo avvio l'app acquisisce e prepara localmente i PDF visibili,
  ma non invia automaticamente contenuti a Gemini e non crea gli embedding.
  Per la ricerca semantica bisogna disporre di vettori indicizzati.
- I metadati curati `data/editions.json`, se presenti sul PC, non sono
  trasferiti automaticamente. Per copiarli nel container, dopo l'avvio:

  ```powershell
  docker compose cp data/editions.json edicola:/app/data/editions.json
  docker compose restart edicola
  ```

Non trasferire indiscriminatamente tutto `data/` nel repository o nei container.
Il trasferimento di un indice o snapshot esistente è un'operazione separata:
verificare prima compatibilità tecnica e diritti sui contenuti.

## API Gemini e accessi personali

Per usare Gemini, crea un file privato `.env` nella radice del progetto
partendo da `.env.example`, con la tua API key. Compose legge questo file
**a runtime**; `.dockerignore` lo esclude dall'immagine. Non pubblicare
mai `.env` o i Secrets Streamlit su GitHub.

Il container Linux usa `EDICOLA_PROFILE_MODE=accounts`: la modalità
`local_demo` è prevista dal codice esclusivamente su Windows e non è attiva.
Per usare Google Login e i profili personali servono i Secrets OIDC Streamlit
e il database PostgreSQL configurati come descritto in `ACCOUNTS.md`.
Per sicurezza i Secrets non vengono montati automaticamente: configurarli
in locale con un mount di sola lettura solo dopo aver verificato il
redirect OAuth. Senza tali configurazioni si può consultare l'app come ospite.

Non vengono avviate indicizzazioni Gemini o generazioni AI automaticamente:
restano necessari i comandi o consensi espliciti già previsti dal progetto.

## Verifica dell'ambiente

```powershell
docker compose config
docker compose exec edicola python -c "import sqlite3, chromadb, streamlit; assert sqlite3.sqlite_version_info >= (3, 35); print('Dipendenze e SQLite OK')"
```

Questi controlli non richiedono chiamate a Gemini. La porta esposta sul
computer è solo `127.0.0.1:8501`: il servizio non è pubblicato su Internet.

**Limite della verifica:** la configurazione è stata adattata al codice
del repository, ma non è ancora stata provata con un build/esecuzione Docker
reale. Dopo aver integrato la modifica verificare la disponibilità delle wheel
Python su Linux e i flussi applicativi usando Docker Desktop.
