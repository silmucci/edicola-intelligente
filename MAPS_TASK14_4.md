# Consultazione delle mappe — Task 14.4

Intervento esclusivamente sulla presentazione dei risultati già validati.
Retrieval, selezione delle fonti, prompt, ranking di pertinenza, modelli,
validatori, consensi, account e versioni delle cache rimangono invariati.

## Etichette

`map_presentation.py` applica una compressione locale limitata ad alcune
formulazioni nominali: per esempio «Proroga del credito di imposta» diventa
«Proroga credito d’imposta» e «Sospensione del pagamento dei mutui» diventa
«Sospensione pagamento mutui». Non genera riassunti con un modello.

Date, importi, beneficiari, scopi, agenti, negazioni e qualifiche non vengono
eliminati. Nomi propri e formulazioni non riconosciute restano completi. Se due
denominazioni diventassero indistinguibili, vengono mostrati gli originali.
Non si tagliano parole o frasi dopo un numero massimo di caratteri e non si
aggiungono «…» o «...». Quando una riduzione sicura non è disponibile, il testo
va a capo: la fedeltà prevale su un limite arbitrario di lunghezza.

Il testo originale rimane nel risultato persistente, nel tooltip e nei dettagli
del nodo. Anche i predicati degli archi restano completi, con ritorni a capo,
anziché perdere le ultime parole durante la visualizzazione.

## Gruppi e consultazione

Il grafo presenta gruppi etichettati esclusivamente per i tipi effettivamente
presenti: Misure, Proposte, Persone, Organizzazioni, Eventi, Luoghi e Concetti.
Colori sobri e forme coerenti con il design Task 13. I gruppi sono contenitori
visivi: non introducono soggetti, eventi o collegamenti nuovi.

Senza relazioni validate, i nodi restano raggruppati per tipo, senza archi,
nemmeno invisibili. Con relazioni, si conservano soltanto gli archi esistenti,
distinguendo relazione documentata e tema comune. Rimane il limite di dieci nodi
nel grafo e la possibilità di consultare tutti i concetti del risultato.

Sotto il grafo, **Esplora un concetto** offre controlli nominativi raggruppati
per tipo. Aprendo un concetto si consultano testo originale e fonti specifiche,
con pulsanti PDF per testata/pagina e passaggi originali su richiesta. Non occorre
cercare il concetto in un unico pannello che mescola tutte le fonti.

Il nodo Graphviz ha un tooltip; il controllo nominativo Streamlit è il punto
interattivo per aprire dettagli e PDF. Non viene simulato un click diretto sui
nodi Graphviz né inserito un URL arbitrario dentro il DOT.

I controlli PDF riutilizzano le verifiche esistenti di archivio autorizzato,
percorso, SHA/versione del documento, chunk e pagina. ID, punteggi, motivi di
esclusione e metadati tecnici restano nella diagnostica di sviluppo.

Grafo ed Elenco sono alternativi. Dimensioni intrinseche, contenitore centrato
e limitato, font leggibili e spaziature contenute restano quelli del Task 14.3.
I controlli dei concetti vanno a capo nei contenitori nativi sui piccoli schermi.
Etichette eccezionalmente lunghe possono richiedere più righe: non vengono
accorciate alterandone il significato.

## Cache e confini dell'intervento

La nuova presentazione si applica direttamente anche ai risultati già salvati.
Non cambiano le chiavi/versioni della cache: nessuna nuova chiamata per adeguare
etichette o gruppi. Navigazione, consultazione dei nodi e Grafo/Elenco non
generano richieste Gemini. Non vengono modificati corpus, SQLite, ChromaDB,
embeddings, Timeline o prodotti editoriali.

## File

Creati: `edicola/map_presentation.py`, `tests/test_map_consultation.py`, questa guida.

Modificati: `edicola/knowledge_validation.py` **solo nel renderer `map_dot`**,
`edicola/knowledge_views.py` per la consultazione, `README.md` e `AGENTS.md`.
Non sono state introdotte nuove dipendenze.

## Verifica locale

```powershell
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.venv\Scripts\python.exe -m streamlit run app.py
```

1. Aprire **Mappe concettuali** e consultare un risultato già disponibile, oppure
   generarlo solo con invio e consenso espliciti. Controllare che le etichette
   non finiscano con troncamenti e che i nomi originali rimangano nei dettagli.
2. Controllare i gruppi effettivamente presenti: nessun gruppo vuoto, nessuna
   relazione aggiunta per collegare i contenitori o gli isolati.
3. Aprire un controllo in **Esplora un concetto**, poi la fonte: verificare che
   si apra il quotidiano e la pagina specifici di quel concetto.
4. Passare a Elenco e tornare al Grafo: una sola vista principale, nessuna nuova
   generazione. Cambiare sezione e tornare senza perdere il risultato.
5. Controllare a 1440, 1024, 768, 390 e 360 px: gruppi leggibili, grafico contenuto,
   controlli a capo, dettagli e fonti accessibili da tastiera e touch.

I test usano esclusivamente API simulate e PDF sintetici. La verifica visiva
reale nel browser e su smartphone resta manuale: i test del rendering non sono
una prova mediante screenshot. Non sono state effettuate chiamate Gemini reali,
commit, push o deployment.

Esito: **691 test superati**, nessun fallimento; 88 avvisi di deprecazione delle
librerie esistenti. Inclusi 18 nuovi casi per fedeltà delle etichette, gruppi senza
archi inventati, predicati completi, dettagli nominativi, pagina PDF specifica,
rifiuto di riferimenti non validi e riuso della cache senza rigenerazione.
