# Fonti articolo condivise tra i prodotti

L'Edicola usa la stessa funzione locale `evidence_source_record` per
preparare i passaggi delle notizie destinati a Chat AI, Briefing, Mappe
concettuali, Timeline e Podcast. Le fonti restano i **chunk indicizzati
del corpus corrente**, senza chiamate aggiuntive né elaborazione dei PDF
durante la generazione.

## Dati editoriali

Se il chunk possiede un titolo di articolo verificato, il modello riceve:
- `source_id` associato a un passaggio originale;
- PDF, pagina e testo integrale del passaggio;
- `article_title` e, se note, `article_pages`.

Questi campi servono a capire a quale articolo appartiene una frase. Non
sono prove autonome: le risposte, i nodi, le relazioni, gli eventi e i
copioni richiedono sempre citazioni testuali originali validate. I titoli
incerti non vengono inviati come titoli verificati. Le notizie prive di
metadati continuano a funzionare come prima.

Le pagine esatte sono presenti nelle azioni per consultare gli originali:
- **Chat/Briefing:** titolo verificato nei collegamenti alle fonti;
- **Mappe:** titolo nei collegamenti ai PDF di nodi e relazioni;
- **Timeline:** titolo nei riferimenti delle schede eventi e delle fonti;
- **Podcast:** titolo nei collegamenti agli articoli dell'episodio, quando
  riconosciuto.

## Cache e aggiornamenti

- **Mappe/Timeline:** strategia `knowledge-v3`. Cambiare corpus, chunk,
  metadati, tema o criteri pertinenti produce una nuova identità di cache.
  I vecchi JSON restano nel filesystem, non vengono cancellati.
- **Podcast:** strategia `standalone-podcast-v3`; i metadati verificati
  contribuiscono all'identità del copione. I vecchi copioni
  `standalone-podcast-v1` e `v2` restano leggibili, inclusi i
  riferimenti del tema per l'audio v2.
- I prodotti **non si rigenerano autonomamente** all'arrivo di un PDF:
  i nuovi chunk devono prima essere indicizzati, previa autorizzazione
  esplicita per gli embedding Gemini. Solo una nuova richiesta dell'utente
  applica la strategia aggiornata. Le cache già salvate restano consultabili.

## Attenzione allo snapshot storico

I 12 quotidiani dello snapshot GitHub hanno ancora estrazioni precedenti.
La sola pubblicazione del codice non ricostruisce automaticamente
articoli e continuazioni su quei chunk. Occorrono aggiornamento locale
controllato, backup, verifica e sincronizzazione dell'indice prima che
tutti i prodotti abbiano i nuovi metadati.

Nessuna modifica è stata apportata alle sette card, ai colori e al
layout originale dell'Edicola.
