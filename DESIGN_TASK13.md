# Design editoriale — Task 13

Il riferimento allegato guida identità e proporzioni, senza riprodurne giornali,
notizie o date dimostrative. La piattaforma conserva le sette sezioni con stato,
Google OIDC, account PostgreSQL, consensi e generazione su invio esplicito.
Non cambiano modelli, retrieval, embeddings, corpus, migrazioni o dipendenze.

## Sistema condiviso e componenti

`edicola/design_tokens.py` definisce colori, tipografia, spazi, raggi, focus e
ombre. Il tema nativo `.streamlit/config.toml` usa gli stessi colori, verificati
nei test. Sfondo bianco, titoli blu notte `#082654`, azioni blu `#0866D9`, accento
rosso `#E51B2B`, superfici `#F2F7FD`, bordi `#E2E8F0`; secondari `#536782`, più
scuri del riferimento per migliorare il contrasto. Serif Georgia e sans-serif
di sistema: nessun font remoto. Nessun marchio TIM.

- `header_ui.py`: logo SVG originale, ricerca locale visibile, accesso al profilo,
  iniziali solo se il nome è disponibile per l'identità verificata, login/logout
  nativi. La modalità demo locale è dichiarata esplicitamente.
- `product_navigation.py`: catalogo delle nove destinazioni effettive, inclusi
  dossier/briefing e timeline/mappa come selezioni dei prodotti esistenti.
- `editorial_components.py`: card di prodotto e fascia In evidenza, con eventi v2
  verificati lato server. Nessun accesso al DOM esterno dei widget Streamlit.
- `design.py`: intestazioni editoriali, stati vuoti e messaggi d'errore condivisi.
- `archive_components.py`: copertine autentiche in carosello, frecce accessibili,
  focus visibile, proporzioni originali, lettore locale e toolbar mobile a capo.
- `chat_sources.py`: fonti compatte riutilizzate anche dagli approfondimenti,
  con chiavi distinte dalla chat e passaggi originali nel popover.

La navigazione principale resta quella delle sette schede native, per conservare
controlli, risultati e conversazioni nei rerun. Non viene aggiunto un secondo menu
permanente: le card sono accessi editoriali nella sola Home. Su schermi piccoli
le schede native scorrono orizzontalmente; la sidebar della cronologia è quella
Streamlit, richiudibile. Aprire un prodotto non genera contenuti.

La ricerca dell'header è lessicale per prefissi di parole, con massimo cinque
risultati per tipo: funzioni, edizioni e passaggi già indicizzati. Non è una
ricerca semantica, non invia domande, non interroga il web. I collegamenti ai
documenti riutilizzano le verifiche di pagina, percorso e chunk. Il testo cercato
è cancellato con lo stato privato al logout/cambio identità.

## Home e prodotti

Le copertine usano il rendering PDFium esistente. Il filtro condiviso Home/Archivio propone **Tutte le
edizioni** e soltanto le date verificate presenti in `data/editions.json`.
Non ci sono filtri fittizi Oggi/Ieri o classificazioni nazionali non documentate.
**In evidenza** alterna estratti originali dei PDF indicizzati, con riferimento
all'edizione e alla pagina. Non aggiunge fotografie, categorie, titoli di articoli,
orari, breaking news o aggiornamenti in tempo reale. Il click apre il PDF originale.

Chat conserva composer unico, conversazioni e citazioni. Dossier e briefing hanno
sezioni in card e fonti compatte. Timeline mantiene eventi, date e avvisi di
verifica; il grafico usa il colore principale. Mappe conservano grafi compatti,
distinzione tra relazioni e associazioni e lista in assenza di collegamenti.
Podcast mantiene player nativo, durata stimata, audio già disponibili e nuove
generazioni distinti. Il profilo conserva interessi in multiselect con chip,
raccolta, preferenze e privacy; le azioni distruttive restano separate e confermate.

## Responsive e accessibilità

- Desktop 1440+: nove card prodotto, copertine su più colonne e highlights in
  quattro colonne. La galleria ha scorrimento interno e frecce anche da tastiera.
- Notebook fino a 1280: prodotti in cinque colonne, copertine in quattro.
- Tablet fino a 1024: prodotti in tre colonne, copertine in tre, highlights in due.
- Mobile fino a 600: card prodotto e copertine in caroselli touch con scroll-snap;
  copertine larghe il 78% del contenitore, highlights all'85%. Titoli fluidi,
  header nativo a capo e toolbar PDF su più righe anziché sovrapposta.

CSS confinato ai componenti v2 o alle classi `edi-brand` e `edi-section`.
HTML delle intestazioni escapato, testi dei componenti creati con `textContent`.
Nessun selettore delle classi generate da Streamlit, CDN o dipendenza frontend.
Le transizioni rispettano `prefers-reduced-motion`. I pulsanti HTML nativi hanno
focus visibile e funzionano con Invio/Spazio. Lo scorrimento riguarda i singoli
caroselli, non richiede una pagina larga quanto l'intera sequenza delle card.

## Verifiche e checklist manuale

```powershell
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
.venv\Scripts\python.exe -m streamlit run app.py
```

I test coprono destinazioni delle nove card, input contraffatti, ricerca locale,
filtri da metadati reali, estratti letterali, callback PDF, sicurezza dei testi,
token/tema, breakpoint e regressioni. Un test Node esegue il codice effettivo
delle card su un DOM minimo: **non è una verifica visuale di un browser**.
Provider e API sono simulati. Il proxy nativo `st.user` è sostituito nei test
per evitare l'inizializzazione indiretta dei Secrets locali reali.

Esito finale: **599 test superati, nessun fallimento**, 89 avvisi di deprecazione
delle librerie già presenti. La suite include anche le regressioni di account,
cronologia, consensi, PDF, RAG, prodotti editoriali e personalizzazione.

Il canale di controllo UI non rileva browser o applicazioni abilitati: non sono
stati acquisiti screenshot reali né verificati i layout su dispositivi fisici.
Prima del rilascio controllare nel browser a **1440, 1280, 1024, 768, 430 e 360 px**:

1. Header: titolo, ricerca e profilo leggibili senza sovrapposizioni; ricerca con
   una testata, un argomento presente e uno assente. Aprire un risultato reale.
2. Tutte le nove card: sezione corretta; Dossier/Briefing e Timeline/Mappa devono
   selezionare il prodotto giusto senza chiamare Gemini.
3. Copertine: frecce, swipe mobile e tastiera; immagini non deformate; filtro con
   date presenti e metadati assenti. Click, cambio pagina, zoom, ritorno e download.
4. In evidenza: estratti riconoscibili come tali, riferimento reale, apertura PDF
   alla pagina corretta; assenza di notizie o miniature inventate.
5. Chat: un composer; cronologia, fonti e consenso invariati; nessuna API su
   navigazione. Provare annullamento e ripresa della richiesta autorizzata.
6. Dossier/briefing: sezioni e passaggi leggibili. Timeline: date distinte dagli
   annunci. Mappa: pan/zoom nativi dove disponibili e fallback a lista.
7. Podcast: ascolto e download di audio già presenti; nuova generazione soltanto
   su invio autorizzato. Verificare player e controlli touch.
8. Due account: profilo/raccolta separati, privacy e logout. Verificare che la ricerca
   dell'header sia svuotata al cambio account e che i salvataggi restino corretti.
9. Verificare zoom browser 200%, tabulazione, contrasto e assenza di scorrimento
   orizzontale dell'intera pagina. Il tema può richiedere riavvio completo di Streamlit.

I componenti nativi impongono alcuni limiti: tabs scorrevoli anziché menu hamburger,
player audio del browser, chat inline nella sezione e strumenti di zoom delle mappe
offerti da Streamlit. Non vengono simulati comportamenti non supportati.

File nuovi: `design_tokens.py`, `header_ui.py`, `product_navigation.py`,
`editorial_components.py`, `tests/editorial_adapter.py`,
`tests/test_editorial_design.py`, questo documento.
File aggiornati: `app.py`, `.streamlit/config.toml`, `design.py`,
`experience_ui.py`, `archive_components.py`, `archive_ui.py`, `reading_ui.py`,
`chat_sources.py`, `knowledge_ui.py`, `podcast_ui.py`, `account_ui.py`,
`personalization_ui.py`, `tests/conftest.py`, `tests/test_experience_ui.py`,
`tests/test_personal_accounts.py`, `README.md`, `AGENTS.md`.
I nomi dei moduli senza prefisso si riferiscono alla cartella `edicola/`.
