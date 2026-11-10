# Fonti degli articoli, Briefing e salvataggio delle chat

## Fonti editoriali più chiare

Chat AI e Briefing utilizzano, quando disponibili, i titoli e le pagine
dell'articolo **verificati dall'estrazione locale o dalla Vision validata**.
Questi metadati aiutano a individuare passaggi della stessa notizia, ma
**non sono una prova del fatto**: le risposte devono ancora citare parole
presenti nei passaggi originali dei quotidiani.

Le fonti visibili mostrano testata, data curata quando presente, pagina e
titolo verificato. I titoli incerti o assenti non vengono inventati.
Per i 12 quotidiani già indicizzati nello snapshot occorre prima un aggiornamento
controllato delle vecchie estrazioni, altrimenti restano visibili solo i dati
precedenti; i nuovi PDF acquisiti con PyMuPDF dispongono già dei metadati
locali necessari.
La Chat evita passaggi identici dello stesso articolo; il Briefing elimina
notizie sostanzialmente ripetute, mantenendo notizie con numeri o dettagli
materialmente differenti. La strategia del Briefing passa a `briefing-v3`:
le cache storiche restano leggibili, mentre i nuovi briefing usano la
logica aggiornata.

## Cronologia delle chat

- L'utente autenticato può abilitare il salvataggio nel proprio account.
  I dati vengono conservati nel database PostgreSQL privato con controlli
  di proprietà (owner). Le chat temporanee non vengono pubblicate o
  importate silenziosamente quando l'opzione cambia.
- Ogni scambio completato viene salvato con un identificatore di richiesta
  stabile. La scrittura è una transazione di due messaggi: domanda e risposta
  (o errore), con ripetizioni idempotenti.
- Se un salvataggio non riesce, il lettore vede un avviso esplicito e può
  riprovare solo il salvataggio, senza richiamare Gemini. Un comando nella
  sidebar riprende i salvataggi non confermati in ordine; ogni tentativo è
  riferito alla chat originale anche se nel frattempo ne è stata aperta
  un'altra.
- I messaggi non ancora confermati dal database esistono **solo nella
  sessione Streamlit corrente** e possono andare persi se quella sessione
  viene chiusa. Non viene promesso un backup persistente locale di dati
  personali non autorizzati.
- In assenza di Google login e database PostgreSQL configurato, l'Edicola
  usa conversazioni temporanee: GitHub Codespaces, da solo, non rende le
  conversazioni persistenti tra browser/dispositivi.
- Un database dell'account non disponibile blocca le funzionalità di
  cronologia anziché fingere che il salvataggio sia riuscito.

## Interfaccia e consenso

Le sette card e la navigazione rimangono invariate. Sono stati rimossi
soltanto alcuni testi esplicativi ripetuti; citazioni, avvisi sulle fonti
parziali e opzioni privacy restano visibili.

Tutti i nuovi test sono offline: nessuna chiamata a Gemini, accesso a
quotidiani privati o modifica dei dati dei lettori.
