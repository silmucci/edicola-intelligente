# Timeline, Mappe e Chat: correzioni e verifiche

## Ambito e cause individuate nel codice

Intervento sulla versione principale `5913b49`, verificata anche sul repository
remoto prima delle modifiche. Il corpus locale corrente contiene 1407 passaggi
indicizzati su 1407, in 12 edizioni: il precedente conteggio di 76 passaggi
pendenti non descrive più questo snapshot. Non è stata eseguita indicizzazione.

- Il recupero sull’intero corpus era già presente. Il solo taglio per distanza
  semantica poteva escludere formulazioni pertinenti; il ranking lessicale non
  riconosceva alcune varianti di protesta e trattava parole generiche della
  richiesta come indizi tematici. Ora ranking semantico e lessicale cooperano
  dopo una sola embedding riuscita, mantenendo filtri e budget. Gli alias
  servono al ranking e non rendono valide citazioni o relazioni.
- La validazione temporale non completava riferimenti come «ieri» senza giorno
  del mese. Ora usa esclusivamente la data curata dell’edizione e controlla
  conflitti, citazioni dirette, riferimenti storici e tempi verbali. Una data
  proposta dal modello ma non verificabile non viene pubblicata: quando la
  prova originale è valida, lo sviluppo relativo rimane senza data. Scadenze,
  programmi e pubblicazione non diventano fatti avvenuti. L’accorpamento è
  conservativo e richiede stessa affermazione e prova, mai soltanto la città.
- Le regole delle mappe non riconoscevano alcune passive con qualifiche,
  participi coordinati e dichiarazioni attribuite. Sono state ampliate con
  costruzioni delimitate e controesempi. Un completamento locale trova i soli
  predicati espliciti fra nodi già validati, dopo una risposta AI valida; ogni
  candidato attraversa nuovamente il validatore. I passaggi contigui devono
  superare i controlli esistenti di pagina, hash, configurazione e continuità.
  Nessuna entità nuova, relazione tematica inventata o recupero locale per
  mascherare errori API/formato. Le posizioni attribuite sono distinte dai fatti.
- La Chat continua a cercare nel corpus corrente a ogni domanda. Le citazioni
  mostrano quotidiano, data e pagina; gli avvisi al lettore non espongono budget
  o dettagli dei passaggi. Percorsi e controlli del lettore PDF restano invariati.

La navigazione usa un selettore nativo compatto. Marchio a sinistra, ricerca e
profilo/accesso in aree dedicate. Rimane il solo Briefing già presente sul ramo
principale. Timeline verticale e sviluppi senza data restano separati. Il grafo
si dispone dall’alto verso il basso; un selettore nominativo permette di isolare
un concetto con i suoi collegamenti. Elenco e fonti restano disponibili e nessun
clic sui nodi Graphviz viene simulato. Il cambio vista non chiama AI.

## Evidenze raccolte e limiti

La suite completa ha superato **794 test**; dopo l’ultima modifica al solo
contatore dell’audit sono passati anche **33 test mirati**. Le API nei test sono
simulate. Le scritture delle fixture riguardano directory temporanee dedicate,
non corpus, indice o dati persistenti dell’installazione. Restano avvisi di
deprecazione delle dipendenze già presenti.

Il comando offline `python -m edicola.functional_audit` legge lo snapshot
indicizzato e costruisce un **replay letterale locale**, non una risposta Gemini.
Usa un involucro di contesto di audit di 7000 caratteri, distinto dal prompt
completo di produzione. Salva soltanto conteggi e riferimenti editoriali nel
report privato ignorato da Git `.private-runtime/functional-audit/report.json`.

| Richiesta | Candidati locali | Inclusi / esclusi per spazio | Risultato del replay |
| --- | ---: | ---: | --- |
| Proteste a Pescara | 16 | 6 / 10 | 6 sviluppi letterali senza data; 5 edizioni |
| Dibattito relativo alla chiusura dei tribunali abruzzesi | 10 | 6 / 4 | 6 nodi, 3 relazioni validate; presenti pagine 5–6 dell’edizione del 30 ottobre |
| Quali sono le principali criticità della sanità abruzzese? | 9 | 6 / 3 | 5 edizioni; 2 passaggi con quantità e unità pertinenti |

Verificati **18 riferimenti PDF su 18**, confrontando SHA dei file locali e
intervallo reale delle pagine. Questo non sostituisce la prova visiva del lettore.
Il replay Timeline usa passaggi letterali interi e non dimostra che Gemini
estragga sei eventi o che nessuna data sia ricavabile da una citazione più breve.
Il replay Mappe usa etichette note del caso, presenti letteralmente nelle fonti:
dimostra la riconoscibilità delle tre relazioni, non l’estrazione AI delle entità.
Il controllo Chat non valuta una risposta generata o la sua completezza fattuale.

### Tre prove reali, successivamente autorizzate

Dopo l’autorizzazione esplicita dell’utente è stato eseguito l’audit con
`--authorize-external --max-api-calls 6`: **esattamente sei tentativi SDK**, tre
embedding e tre generazioni, tutti con HTTP 200, senza retry inviati. Nessuna
lettura o scrittura delle cache generali per Timeline/Mappe. Gli output effettivi
sono salvati esclusivamente nella directory privata ignorata da Git.

| Richiesta reale | Recuperati / inclusi / esclusi per spazio | Esito effettivo |
| --- | --- | --- |
| Proteste a Pescara | 84 / 7 / 77 | 4 eventi candidati: 1 respinto per citazione, 1 escluso per pertinenza; rimangono 1 evento datato e 1 senza data |
| Dibattito relativo alla chiusura dei tribunali abruzzesi | 14 / 6 / 10 | 3 archi AI respinti perché non espliciti; 2 archi letterali rivalidati, di cui 1 escluso per pertinenza; rimangono 4 concetti e 1 relazione |
| Quali sono le principali criticità della sanità abruzzese? | 1084 / 9 / 1075 | Il risultato restituito dalla Chat dichiara informazioni insufficienti |

Per la mappa il recupero semantico ha prodotto 1160 risultati; la selezione
tematica/di contesto ha poi considerato 14 passaggi, più 2 tentativi di vicinato
conteggiati separatamente nel log della costruzione del contesto. Le esclusioni
qui indicate riguardano il prodotto finale, non implicano che tutti i risultati
semantici fossero pertinenti. Un numero elevato di candidati non prova copertura
utile: resta necessario controllare il ranking e gli output.

L’evento Timeline datato usa una data relativa completata con metadati verificati.
Gli altri sviluppi non sono stati forzati sulla data del giornale. La relazione
rimasta nella mappa è il predicato letterale «presentato dal». Questo risultato
dimostra un miglioramento rispetto ai soli nodi isolati, ma non la completezza
del dibattito o di tutte le relazioni disponibili.

La Chat ha ricevuto 9 passaggi da 9 edizioni, 5 contenenti quantità con unità o
percentuali. Pertanto il fallimento non è spiegato dal vecchio limite di tre
passaggi. Il risultato persistito non conserva la risposta strutturata precedente
alla validazione: con questa esecuzione non è possibile distinguere astensione
del modello da rifiuto per formato/citazione. Non sono state allentate le regole
di validazione per ottenere comunque una risposta. **Il caso Chat resta aperto.**

Verificati anche tutti i **22 riferimenti PDF delle prove reali** tramite SHA e
intervallo delle pagine: 7 Timeline, 6 Mappe, 9 Chat. Non equivale a una prova
visiva dei pulsanti. Esaurito il limite autorizzato, non sono state effettuate
altre chiamate. Le prove reali non permettono di dichiarare risolti completamente
i tre casi: Timeline e Mappa producono contenuti validati, Chat non risponde ancora.

Il browser integrato non aveva sessioni disponibili: nessuna verifica visiva
desktop/mobile è stata eseguita. Streamlit AppTest verifica navigazione, fonti,
selezione dei concetti e assenza di chiamate AI al cambio vista, ma non il layout
reale dello schermo.

## Controlli manuali da completare

1. Dopo autorizzazione, inviare le tre richieste con il corpus corrente. Esaminare
   gli output effettivi e i conteggi di recupero, utilizzo e scarto nei log di
   sviluppo. Controllare pertinenza e contributi delle edizioni, senza aspettarsi
   rappresentanza forzata di ogni giornale.
2. Timeline: distinguere proteste diverse a Pescara; verificare annunci, date
   relative, ordine cronologico e sezione Senza data. Confrontare ogni evento con
   il passaggio originale e controllare che eventuali duplicati conservino fonti.
3. Mappe: verificare autori, sostegni e decisioni nei passaggi dei tribunali;
   distinguere opinioni attribuite, relazioni documentate e temi comuni. Scegliere
   un concetto collegato e uno isolato, poi passare a Elenco senza nuove chiamate.
4. Chat: verificare che numeri e affermazioni siano sostenuti dalle citazioni;
   aprire fonti di edizioni diverse. Le etichette devono distinguere quotidiano,
   data e pagina; le omissioni non devono apparire come fonti analizzate.
5. Aprire le fonti PDF nelle pagine indicate, zoomare e tornare al prodotto.
   Ripetere su desktop e larghezze 360/390 px: intestazione, selettore, profilo,
   Timeline, grafo ed elenco devono rimanere leggibili e utilizzabili.

## File modificati

- Recupero e contesto: `edicola/search.py`, `knowledge_relevance.py`,
  `context_selection.py`, `rag.py`.
- Generazione e validazione: `edicola/knowledge.py`, `timeline_dates.py`,
  `timeline_events.py` (nuovo), `knowledge_validation.py`,
  `knowledge_presentation.py`, `map_relations.py`, `map_literal.py` (nuovo).
- Presentazione: `edicola/chat_sources.py`, `knowledge_views.py`, `header_ui.py`,
  `product_navigation.py`.
- Audit: `edicola/functional_audit.py` e `tests/test_functional_regressions.py`
  (nuovi).
- Test aggiornati alle viste correnti: `tests/test_app.py`, `test_archive_design.py`,
  `test_cloud.py`, `test_consumer_ui.py`, `test_editorial_audit.py`,
  `test_editorial_design.py`, `test_experience_ui.py`, `test_indexing.py`,
  `test_knowledge.py`, `test_knowledge_functional.py`, `test_knowledge_relevance.py`,
  `test_navigation_editorial.py`, `test_pdf_viewer.py`, `test_podcast_ui.py`.
- Documentazione: `README.md`, questo documento.

Versionate separatamente pertinenza, regole temporali e mappa; nessuna cancellazione
di risultati salvati e nessuna rigenerazione al cambio vista. Invariati budget,
pipeline PDF/indicizzazione, dipendenze, account, consensi e autorizzazioni.
Nessun testo originale o PDF aggiunto a Git; nessun commit, push o deploy.
Le cancellazioni/accessi negati già presenti sotto `deployment/seed/` sono stati
lasciati invariati; non fanno parte di questo intervento.
