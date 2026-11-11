# Edicola Digitale Intelligente

**Edicola Digitale Intelligente** è un prototipo di applicazione web che permette di consultare più quotidiani in un unico spazio e di approfondire le notizie con strumenti basati sull'intelligenza artificiale.

Il progetto nasce per rendere più semplice la ricerca e la lettura di contenuti giornalistici presenti in documenti PDF. Le risposte e i contenuti generati rimandano, quando disponibili, ai quotidiani e alle pagine da cui provengono le informazioni.

## Cosa si può fare

L'applicazione comprende queste sezioni:

- **In edicola:** sfogliare i quotidiani disponibili e aprire le pagine originali in PDF.
- **Rassegna stampa:** esplorare le notizie e cercare argomenti nelle edizioni presenti.
- **Chat AI:** porre domande sui contenuti dei giornali e consultare le fonti delle risposte.
- **Briefing:** ottenere una sintesi organizzata di un argomento, scegliendo anche le fonti da considerare.
- **Timeline:** seguire gli eventi in ordine cronologico quando le date sono verificabili.
- **Mappe concettuali:** esplorare temi, soggetti e collegamenti ricavati dai documenti.
- **Podcast:** ascoltare un approfondimento narrativo sulle notizie disponibili, anche su un tema specifico. Se le fonti lo permettono, il copione punta a circa 4–5 minuti, altrimenti resta più breve. Le citazioni rimangono accessibili insieme al testo; la sintesi vocale suddivide i copioni lunghi in segmenti verificati e produce un solo file WAV.
- **Il mio profilo:** gestire preferenze, letture e impostazioni personali, secondo la modalità di accesso configurata.

Il Podcast utilizza anche le scelte delle edizioni e i filtri già impostati nel Briefing, quando presenti, senza richiedere che sia stato generato prima un Briefing. Il testo e l'audio vengono preparati soltanto su richiesta e dopo le autorizzazioni richieste. Gli episodi già salvati restano consultabili.

Le funzioni AI lavorano sui contenuti disponibili e indicizzati: non effettuano automaticamente ricerche di notizie in tempo reale sul web.

## Come funziona

Il funzionamento si articola in quattro passaggi principali:

1. **Acquisizione:** i quotidiani vengono caricati come PDF e registrati nell'archivio.
2. **Preparazione:** il testo viene estratto e suddiviso in passaggi più piccoli (*chunk*).
3. **Indicizzazione:** i passaggi vengono trasformati in rappresentazioni numeriche (*embedding*) e salvati in un database vettoriale, per consentire la ricerca semantica.
4. **Consultazione e generazione:** l'app recupera i passaggi pertinenti e li utilizza per rispondere alle domande o preparare i contenuti editoriali.

Questa modalità di lavoro è chiamata **RAG (Retrieval-Augmented Generation)**: il modello AI utilizza informazioni recuperate dai documenti, anziché basarsi soltanto sulle proprie conoscenze.

Le citazioni consentono di tornare alle fonti originali. I contenuti generati possono comunque contenere imprecisioni e devono essere verificati prima di essere utilizzati come informazioni definitive.

## Tecnologie utilizzate

| Tecnologia | Utilizzo |
| --- | --- |
| **Python** | Logica dell'applicazione ed elaborazione dei documenti |
| **Streamlit** | Interfaccia web |
| **pypdf e PyMuPDF** | Lettura ed estrazione del contenuto dei PDF |
| **SQLite** | Archivio locale e metadati dei documenti |
| **Google Gemini** | Embedding, generazione dei testi e funzioni AI abilitate |
| **ChromaDB** | Memorizzazione degli embedding e ricerca semantica |
| **PostgreSQL** | Dati degli account nella modalità che prevede profili personali |
| **Docker** | Esecuzione dell'app in un ambiente isolato, quando necessario |

I modelli AI sono utilizzati tramite servizi cloud: non è necessario scaricare o eseguire un modello linguistico in locale.

## Avvio del progetto

Per eseguire l'app in locale servono Python, una versione di SQLite compatibile con ChromaDB e le dipendenze del progetto.

Clonare il repository:

```bash
git clone https://github.com/silmucci/edicola-intelligente.git
cd edicola-intelligente
```

Creare un ambiente virtuale e installare le dipendenze:

```bash
python -m venv .venv
```

Su Windows:

```powershell
.venv\Scripts\activate
pip install -r requirements.txt
```

Su macOS o Linux:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

Avviare l'applicazione:

```bash
streamlit run app.py
```

L'interfaccia si apre normalmente all'indirizzo `http://localhost:8501`.

### Configurazione delle API

Per usare le funzioni Gemini, creare un file `.env` locale a partire da `.env.example` e inserire una chiave API valida:

```env
GEMINI_API_KEY=la_tua_chiave_api
```

Le chiamate esterne richiedono le autorizzazioni previste dal progetto. La sola apertura dei PDF e la navigazione non comportano automaticamente nuove richieste di generazione AI.

L'accesso Google e i profili personali richiedono una configurazione separata delle credenziali di autenticazione e del database. In assenza di tale configurazione, le funzioni disponibili dipendono dalla modalità di esecuzione.

## Aggiungere nuovi quotidiani

Nella modalità locale, si possono inserire nuovi PDF nella cartella `data/inbox`. Quando l'app viene ricaricata, i file validi vengono preparati e aggiunti all'archivio senza avviare automaticamente chiamate Gemini.

**Importante:** preparare un PDF non significa averlo già indicizzato per la ricerca semantica. Per generare gli embedding mancanti è necessaria un'operazione separata e autorizzata.

L'acquisizione automatica non è attiva nella modalità cloud basata su uno snapshot dei documenti. Per dettagli vedere [Acquisizione dei PDF](PDF_AUTO_INTAKE.md) e [Gestione dell'archivio](GESTIONE_ARCHIVIO.md).

## Esecuzione con Docker

Il progetto include anche una configurazione Docker. È un'alternativa all'avvio con Python e Streamlit, utile per eseguire l'app in un ambiente isolato o visualizzarla tramite GitHub Codespaces.

Per l'avvio locale con Docker:

```bash
docker compose up --build -d
```

La configurazione con lo snapshot dei PDF già preparati segue una procedura diversa, descritta in [DOCKER.md](DOCKER.md). Docker non sostituisce Streamlit e non esegue modelli AI locali.

## Organizzazione del progetto

- `app.py`: punto di ingresso dell'interfaccia.
- `edicola/`: moduli per documenti, ricerca, generazione AI e sezioni dell'app.
- `tests/`: test automatici.
- `data/`: dati e documenti locali, secondo la configurazione utilizzata.
- `deployment/`: file necessari alle modalità di pubblicazione previste.
- `requirements.txt`: dipendenze Python.
- `.env.example`: esempio delle variabili di configurazione.

## Limiti e attenzione alle fonti

Il prototipo utilizza i quotidiani effettivamente presenti e i passaggi già indicizzati. Una copertura incompleta dell'indice può limitare i risultati della ricerca. L'estrazione del testo dai PDF, l'individuazione degli articoli e la generazione AI non sono sempre perfette.

I PDF e i contenuti derivati devono essere utilizzati e condivisi nel rispetto dei relativi diritti. Non pubblicare nel repository chiavi API, credenziali, dati personali o documenti non autorizzati.

## Contesto del progetto

L'Edicola Digitale Intelligente è stata sviluppata come prototipo nell'ambito di un percorso di tirocinio, con l'obiettivo di sperimentare l'uso dell'intelligenza artificiale generativa e della ricerca semantica per valorizzare e rendere più accessibili i contenuti editoriali.
