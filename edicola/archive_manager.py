"""Console del gestore locale; nessun endpoint amministrativo Streamlit."""

import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from collections import Counter

from edicola.corpus_update import inspect_corpus
from edicola.incremental import preview_all, preview_batch, require_local_manager, run_batch, reconcile_progress
from edicola.incremental_all import run_all_missing
from edicola.maintenance_store import MaintenanceStore, maintenance_lock, recent_batches

STATUS = {"completed": "completato", "running": "in esecuzione", "paused": "in pausa",
          "failed": "non completato", "interrupted": "interrotto", "nothing_pending": "nessun passaggio mancante"}
ERRORS = {"429": "Quota raggiunta: attendere almeno un minuto prima di autorizzare un nuovo batch.",
          "503": "Servizio temporaneamente indisponibile. Riprovare più tardi con un nuovo invio.",
          "network_or_vector": "Connessione, timeout o formato della risposta non valido.",
          "local_or_source_error": "Le fonti o il salvataggio locale richiedono una verifica.",
          "manual_stop": "Operazione fermata dal gestore."}
DOCUMENTS = {"new": "nuovo", "modified": "modificato", "duplicate": "copia identica", "unchanged": "invariato",
             "ok": "testo disponibile", "partial": "estrazione parziale", "error": "non elaborabile",
             "no_text": "senza testo estraibile", "empty": "vuoto", "not_prepared": "da preparare"}


def prepare_changes(root):
    require_local_manager(root)
    with maintenance_lock(root):
        report = inspect_corpus(root)
        needed = (report["changes"]["new"] or report["changes"]["modified"]
                  or any(not document["prepared"] for document in report["documents"]))
        report = inspect_corpus(root, refresh=True) if needed else report
        if report["metadata_updates"] and not report["warnings"]:
            from edicola.archive import read_active_chunks
            from edicola.indexing import IndexPlan, apply_plan, plan_index
            from edicola.vectorstore import open_collection
            root = Path(root)
            chunks, _ = read_active_chunks(root / "data/archive.sqlite3", root / "data/incoming")
            collection = open_collection(root / "data/chroma")
            plan = plan_index(chunks, collection)
            apply_plan(IndexPlan([], plan.metadata_updates, [], 0), collection, None, 1, prune_stale=False)
            report = inspect_corpus(root)
        return report


def show_status(root, write=print):
    if any(job["status"] == "running" for job in recent_batches(root)):
        try:
            with maintenance_lock(root), closing(MaintenanceStore(root)) as store:
                reconcile_progress(root, store)
        except RuntimeError:
            write("Un batch è attualmente in esecuzione; lo stato mostrato può avanzare.")
    report = inspect_corpus(root)
    write(f"ARCHIVIO: {report['pdfs']} PDF · {report['pages']} pagine · {report['chunks']} chunk")
    write(f"Indicizzati: {report['indexed']} · Mancanti: {report['pending']} · Vettori storici conservati: {report['stale_vectors_preserved']}")
    for document in report["documents"]:
        metadata = report["metadata"][document["pdf"]]
        write(f"{document['pdf']} | {metadata['publication'] or 'Testata da verificare'} | {metadata['date'] or 'Data da verificare'} | "
              f"{document['pages']} pagine | {document['chunks']} chunk | {document['indexed']} indicizzati | "
              f"{document['pending']} mancanti | {DOCUMENTS[document['change']]} | {DOCUMENTS.get(document['status'], 'da verificare')}")
        if metadata["issues"]:
            write("  Metadati da controllare: " + ", ".join(metadata["issues"]))
        if document["skipped_pages"]:
            write(f"  {document['skipped_pages']} pagine escluse perché prive di testo utilizzabile o con errori.")
    if report["changes"]["duplicates"]:
        write("Copie identiche rilevate: estrazione, chunk ed embedding sono condivisi per contenuto.")
    if report["warnings"]:
        write("Occorre preparare o verificare alcuni documenti prima di indicizzare.")
    for job in recent_batches(root, limit=3):
        write(f"Batch recente: {STATUS.get(job['status'], job['status'])} · {job['completed']}/{job['planned']} completati · "
              f"{job['attempts']} tentativi SDK · {job['reused']} vettori ripresi dalla coda locale · codice {job['error_code'] or 'nessuno'}")
        if job["error_code"]:
            write(ERRORS.get(job["error_code"], "Verificare accesso al modello e configurazione prima di un nuovo invio."))
    return report


def show_preview(preview, write=print):
    write(f"Totali: {preview.total} · Indicizzati: {preview.indexed} · Mancanti nella selezione: {preview.missing}")
    write(f"PROSSIMO BATCH: {len(preview.chunks)} chunk. Destinatario: Google Gemini Embedding 2 (768 dimensioni).")
    write(f"Massimo {3 * len(preview.chunks)} tentativi SDK inclusi i retry. Nessun invio finché non autorizzi.")
    for index, chunk in enumerate(preview.chunks, 1):
        write(f"{index}. {chunk.metadata['filename']} · pagina {chunk.metadata['page']} · {len(chunk.text)} caratteri")


def show_all_preview(preview, write=print):
    write(f"TUTTI I MANCANTI: {preview.missing} chunk · {preview.indexed}/{preview.total} già indicizzati.")
    for name, count in sorted(Counter(c.metadata["filename"] for c in preview.chunks).items()):
        write(f"{name}: {count} chunk mancanti")
    write(f"Google Gemini Embedding 2: {preview.missing} richieste previste, massimo {3 * preview.missing} tentativi inclusi i retry; meno richieste se esistono vettori recuperabili dalla coda.")
    write(f"Batch fino a 50: {(preview.missing + 49) // 50}. Dopo la conferma proseguono automaticamente solo finché non si verifica un arresto o errore.")
    write("Nessun aumento automatico di quota o attivazione di servizi a pagamento. Ctrl+C interrompe; la ripresa richiede una nuova conferma dei soli mancanti.")


def interactive(root, read=input, write=print):
    write("GESTIONE ARCHIVIO — console locale riservata al gestore del computer")
    while True:
        write("\n1 Stato ed edizioni | 2 Prepara nuovi PDF | 3 Anteprima / autorizza un batch | 4 Verifica metadati | 5 Prepara snapshot autorizzato | 6 Indicizza tutti i chunk mancanti | 0 Esci")
        choice = read("Scelta: ").strip()
        try:
            if choice == "0":
                return 0
            if choice == "1":
                show_status(root, write)
            elif choice == "2":
                write("Inserisci i PDF in data/incoming. Le edizioni esistenti saranno riutilizzate.")
                if read("Scrivi PREPARA per continuare senza API: ").strip() == "PREPARA":
                    report = prepare_changes(root)
                    write(f"Preparazione conclusa. {report['chunks']} chunk, {report['pending']} da indicizzare. Nessuna API.")
            elif choice == "3":
                size = int(read("Dimensione batch (10, 20 o 50): "))
                if size not in {10, 20, 50}:
                    raise ValueError("Dimensione non prevista.")
                name = read("Nome esatto di un PDF, oppure Invio per tutte le edizioni: ").strip()
                filenames = (name,) if name else ()
                preview = preview_batch(root, size, filenames)
                show_preview(preview, write)
                if not preview.chunks:
                    continue
                selected = read("Numero del chunk per leggerlo, oppure Invio: ").strip()
                if selected:
                    index = int(selected)
                    if not 1 <= index <= len(preview.chunks):
                        raise ValueError("Chunk non presente nell’anteprima.")
                    write(preview.chunks[index - 1].text)
                expected = f"AUTORIZZO {len(preview.chunks)}"
                if read(f"Per inviare questi testi a Gemini scrivi {expected}, altrimenti Invio: ").strip() != expected:
                    write("Nessun invio eseguito.")
                    continue
                result = run_batch(root, limit=size, filenames=filenames, token=preview.token, authorize_external=True,
                    progress=lambda job: write(f"Salvati {job['completed']}/{job['planned']} chunk."))
                write(f"Batch {STATUS.get(result['status'], result['status'])}: {result['completed']} completati.")
                if result.get("error_code"):
                    write(ERRORS.get(result["error_code"], "Verificare accesso al modello e configurazione prima di un nuovo invio."))
                write("Per proseguire occorre scegliere e autorizzare un nuovo batch. I chunk salvati saranno saltati.")
            elif choice == "6":
                preview = preview_all(root)
                show_all_preview(preview, write)
                if not preview.chunks:
                    continue
                expected = f"AUTORIZZO TUTTI {preview.missing}"
                if read(f"Per inviare l’intero piano a Gemini scrivi {expected}, altrimenti Invio: ").strip() != expected:
                    write("Nessun invio eseguito.")
                    continue
                result = run_all_missing(root, token=preview.token, authorize_external=True,
                    progress=lambda state: write(f"Batch {state['batch']} · Salvati {state['completed']}/{state['planned']} · "
                                                 f"Indicizzati {state['indexed']}/{state['total']} · Rimanenti {state['remaining']}"))
                write(f"Operazione {STATUS.get(result['status'], result['status'])}: {result['completed']} completati, {result['remaining']} rimanenti nel piano.")
                if result.get("error_code"):
                    write(ERRORS.get(result["error_code"], "Verificare il servizio o la configurazione prima di riprovare."))
                write("Se interrotta, scegliere di nuovo 6 e confermare il nuovo riepilogo: i vettori salvati saranno saltati.")
            elif choice == "4":
                from edicola.maintenance_metadata import confirm_metadata
                report = show_status(root, write)
                for index, document in enumerate(report["documents"], 1):
                    write(f"{index}. {document['pdf']}")
                selected = int(read("Numero dell’edizione da verificare: "))
                if not 1 <= selected <= len(report["documents"]):
                    raise ValueError("Edizione non presente.")
                name = report["documents"][selected - 1]["pdf"]
                write("Apri il PDF originale da data/incoming e verifica testata e data di pubblicazione, non la data di un evento.")
                publication = read("Testata verificata (vuoto se non determinabile): ")
                published = read("Data verificata AAAA-MM-GG (vuoto se non determinabile): ")
                if read("Scrivi CONFERMO METADATI dopo la verifica nel PDF: ").strip() == "CONFERMO METADATI":
                    confirm_metadata(root, name, publication, published, confirmed=True)
                    write("Metadati salvati. Le altre edizioni sono conservate; nessuna API.")
            elif choice == "5":
                from edicola.maintenance_snapshot import prepare_snapshot
                report = show_status(root, write)
                for index, document in enumerate(report["documents"], 1):
                    write(f"{index}. {document['pdf']}")
                indexes = [int(value.strip()) for value in read("Numeri dei SOLI PDF distribuibili, separati da virgola: ").split(",")]
                if len(set(indexes)) != len(indexes) or any(not 1 <= i <= len(report["documents"]) for i in indexes):
                    raise ValueError("Selezione dei PDF non valida.")
                names = [report["documents"][i - 1]["pdf"] for i in indexes]
                for name in names:
                    write("Da includere: " + name)
                write("Devi avere il diritto di pubblicare questi PDF e i loro dati derivati, inclusi consultazione e download web.")
                if read("Scrivi AUTORIZZO DISTRIBUZIONE per creare una copia locale, senza pubblicarla: ").strip() == "AUTORIZZO DISTRIBUZIONE":
                    path, manifest = prepare_snapshot(Path(root), names, authorize_distribution=True)
                    write(f"Snapshot locale verificato: {path} · {manifest['pdfs']} PDF · {manifest['indexed']}/{manifest['chunks']} chunk indicizzati.")
                    write("Non è stato pubblicato nulla. Segui GESTIONE_ARCHIVIO.md per la revisione e il rilascio manuale.")
        except (OSError, ValueError, RuntimeError, PermissionError, sqlite3.Error):
            write("Operazione non completata. Verifica documenti, metadati, compatibilità dell’indice e disponibilità del servizio; nessun retry automatico del batch.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--status", action="store_true")
    actions.add_argument("--prepare", action="store_true")
    actions.add_argument("--preview", action="store_true")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--pdf", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        require_local_manager(args.root)
        if args.status:
            show_status(args.root)
        elif args.prepare:
            report = prepare_changes(args.root)
            print(f"Preparati {report['pdfs']} PDF: {report['pending']} chunk mancanti. Nessuna API.")
        elif args.preview:
            show_preview(preview_batch(args.root, args.batch_size, args.pdf))
        else:
            return interactive(args.root)
        return 0
    except PermissionError:
        print("Gestione disponibile solo nella console locale. Aprire Gestione archivio.cmd; il sito Streamlit non abilita operazioni amministrative.")
        return 1
    except (OSError, ValueError, RuntimeError, sqlite3.Error, KeyboardInterrupt, EOFError):
        print("Gestione interrotta. Nessuna richiesta verrà ripresa automaticamente; i dati salvati restano disponibili.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
