# Timeline e mappe — Task 14.1

## Diagnosi verificata

L'ispezione locale in sola lettura dei chunk ha trovato un elenco nominale
introdotto da «Tra le proposte inoltrate al Governo». Il testo documenta misure
proposte, non una loro approvazione né un rapporto causale con qualsiasi concetto
recuperato. Il validatore delle mappe riconosce principalmente costruzioni
letterali soggetto–predicato–oggetto: una lista non le contiene necessariamente.
Il riferimento numerico `(ex 5.68)` interrompeva una costruzione nominale con
`per`; ora è ammesso senza consentire parentesi contenenti altri soggetti.

Una parafrasi come «credito d'imposta» può inoltre non coincidere con la forma
letterale «credito di imposta». Il prompt richiede la forma originale: non sono
stati introdotti sinonimi automatici nel controllo delle prove. Altri passaggi
che menzionano carburante o mutui riguardano l'agricoltura: non possono diventare
misure per la pesca per la sola pertinenza lessicale della domanda.

Non sono state trovate cache locali della richiesta sul carburante con cui
ricostruire i singoli scarti della risposta reale. Queste sono cause strutturali
verificate, non una ricostruzione certa di ogni candidato prodotto da Gemini.
Non sono state effettuate chiamate Gemini reali.

## Correzioni

- **Mappa con archi:** conserva predicati letterali, direzione, prove e distinzione
  fra relazioni documentate e associazioni tematiche supportate.
- **Soli concetti:** mostra nodi Graphviz compatti, al massimo dieci, raggruppati
  sotto l'argomento dichiaratamente navigazionale. Nessun arco, nemmeno decorativo.
  Il selettore Grafo/Elenco rimane disponibile; dettagli e fonti includono tutti
  i concetti verificati. Non viene inventato un nodo centrale fattuale.
- **Timeline:** cronologia solo con date evento verificate; sviluppi senza data
  nelle card «Eventi e sviluppi documentati», in ordine dei passaggi recuperati,
  esplicitamente non cronologico. Una scadenza di una misura non diventa la data
  in cui è stata proposta.
- Se il risultato AI strutturalmente valido non contiene eventi verificati,
  un recupero locale conservativo può estrarre punti completi di elenchi nominali
  espliciti dai soli passaggi selezionati. Titoli, descrizioni e prove sono
  letterali e ripassano nello stesso validatore. Nessuna unione di frammenti,
  articoli o colonne; nessun agente o esito dedotto. Questo percorso non maschera
  errori API o JSON. La UI ne dichiara l'origine estrattiva locale.
- Stato vuoto unico: distingue nessuna fonte recuperata, nessun candidato
  documentato individuato e candidati scartati. Le date non verificabili non
  comportano da sole la perdita di uno sviluppo verificato.
- Il risultato indica il proprio argomento. Restano risultati RAM separati per
  Timeline e Mappa; una cache con prodotto/argomento incoerente viene rifiutata
  senza rigenerazione automatica.

Ricerca semantica, numero di query, budget e modelli rimangono invariati. I vicini
delle mappe restano soltanto quelli già indicizzati con continuità verificata di
pagina/hash/configurazione/offset/overlap e articolo quando noto. Nessun recupero
aggiuntivo indiscriminato. Le nuove regole mantengono negazioni, condizionali e
attribuzioni nelle prove; la parentesi ammessa è esclusivamente numerica.

## Cache, sicurezza e limiti

Strategie aggiornate a `concept-map-v4` e `timeline-developments-v3`, senza cambiare
la versione delle regole calendariali. Le vecchie cache restano su disco ma non
sono riutilizzate. Non cambiano RAG, altri prodotti, consensi, autenticazione,
database, corpus, embeddings o ChromaDB. Nessuna nuova dipendenza.

Graphviz è il renderer nativo Streamlit: zoom e navigazione dipendono dalle sue
capacità, non sono simulati. La lista alternativa favorisce la consultazione su
smartphone. La verifica visiva reale a diverse risoluzioni resta manuale.
Il riconoscimento locale degli elenchi è deliberatamente limitato: non sostituisce
un parser degli articoli e non recupera frasi troncate. Un grafo può legittimamente
rimanere senza archi se le fonti non contengono relazioni verificabili.

## File di questo intervento

Creati: `edicola/proposal_extraction.py`, `tests/test_knowledge_functional.py`,
questa guida.

Modificati: `edicola/knowledge.py`, `edicola/knowledge_presentation.py`,
`edicola/knowledge_validation.py`, `edicola/map_relations.py`,
`edicola/knowledge_views.py`, `tests/test_app.py`, `README.md`, `AGENTS.md`.
Aggiornata anche la nota iniziale di `KNOWLEDGE_TASK14.md`.
I componenti e le modifiche del precedente Task 14 restano presenti.

## Verifica manuale

```powershell
.venv\Scripts\python.exe -m streamlit run app.py
```

1. In **Timeline e Mappe**, scegliere Mappa e usare la domanda sulle misure per
   sostenere le imprese di pesca contro il caro carburante. Generare e autorizzare
   esplicitamente. Con soli concetti verificati devono apparire nodi senza archi,
   intestazione navigazionale e alternativa Elenco. Con archi verificati devono
   comparire predicati originali e prove.
2. Aprire le fonti dai dettagli dei concetti/relazioni: verificare PDF e pagina
   originali. Nessuna API deve essere chiamata dalla consultazione.
3. Passare a Timeline: non deve apparire la precedente mappa. Generare soltanto
   premendo il comando. Le proposte senza data rimangono negli sviluppi; le
   scadenze citate non diventano date di proposta. Il risultato dipende dai
   passaggi realmente recuperati, quindi non è garantito un numero di elementi.
4. Provare una fonte con data evento verificata: deve entrare nella cronologia,
   mantenendo separata la pubblicazione e lo stato annunciato/avvenuto.
5. Cambiare prodotto, argomento e Grafo/Elenco: controllare argomento del risultato,
   avviso di bozza diversa e nessuna nuova generazione involontaria. Ripetere la
   medesima richiesta esplicita per verificare la cache aggiornata.
6. Controllare a 1440, 768, 430 e 360 px: nodi contenuti, card verticali, fonti
   accessibili e lista leggibile. I test di rendering non equivalgono a questa
   prova visiva su browser/dispositivi reali.

I test usano API e documenti sintetici: comprendono grafi con/senza archi, stati
vuoti distinti, proposte letterali, date/scadenze, negazioni e condizionali,
parentesi numeriche, fonti PDF, cache, errori API/JSON e frammenti non unibili.
La suite comprende anche navigazione fra prodotti, layout adattivo e regressioni
delle funzionalità precedenti. Nessun commit, push o deployment.

Esito finale: **639 test superati**, nessun fallimento; 89 avvisi di deprecazione
delle librerie esistenti. Comando eseguito:

```powershell
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```
