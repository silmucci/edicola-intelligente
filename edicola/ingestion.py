"""Scansione del filesystem, estrazione con pypdf e riuso per SHA-256."""

import hashlib
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

from edicola.models import Document, Page
from edicola.storage import load_result, open_registry, record_source, save_result


def extract_pdf(content: bytes) -> dict:
    """Estrae tutte le pagine e isola gli errori del singolo documento/pagina."""
    result = {"total_pages": 0, "status": "error", "message": "", "pages": []}
    if not content:
        return {**result, "status": "empty", "message": "Il file contiene zero byte."}
    try:
        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted and not reader.decrypt(""):
            return {**result, "message": "PDF protetto da password."}
        result["total_pages"] = len(reader.pages)
        if not result["total_pages"]:
            return {**result, "status": "empty", "message": "Il PDF non contiene pagine."}
        for number, page in enumerate(reader.pages, start=1):
            item = {"number": number, "text": "", "error": ""}
            try:
                item["text"] = page.extract_text() or ""
            except Exception as exc:
                item["error"] = f"Pagina non estraibile: {type(exc).__name__}: {exc}"
            result["pages"].append(item)
    except Exception as exc:
        # pypdf può sollevare errori differenti per strutture PDF malformate.
        result["message"] = f"PDF non leggibile: {type(exc).__name__}: {exc}"
        return result

    has_text = any(page["text"].strip() for page in result["pages"])
    errors = sum(bool(page["error"]) for page in result["pages"])
    blank = sum(not page["text"].strip() and not page["error"] for page in result["pages"])
    if errors:
        result["status"] = "partial" if has_text else "error"
        result["message"] = f"{errors} pagine con errori di estrazione."
    elif not has_text:
        result["status"] = "no_text"
        result["message"] = "Nessun testo estraibile; il PDF potrebbe contenere scansioni. OCR non attivo."
    else:
        result["status"] = "ok"
        if blank:
            result["message"] = f"{blank} pagine senza testo estraibile."
    return result


def ingest_directory(incoming: Path, registry: Path) -> list[Document]:
    """Rilegge gli hash a ogni scansione, ma estrae solo contenuti mai registrati.

    I PDF sono cercati nel solo livello principale, senza distinzione fra .pdf e .PDF.
    La lista riflette i file attuali; i risultati storici restano nel registro.
    """
    incoming = Path(incoming)
    incoming.mkdir(parents=True, exist_ok=True)
    documents = []
    with open_registry(Path(registry)) as connection:
        for path in sorted(incoming.iterdir(), key=lambda item: item.name.casefold()):
            if path.suffix.lower() != ".pdf" or not path.is_file():
                continue
            try:
                # Hash ed estrazione usano la medesima istantanea del file.
                content = path.read_bytes()
            except OSError as exc:
                documents.append(Document(path.name, None, 0, "error", f"File non accessibile: {exc}"))
                continue
            digest = hashlib.sha256(content).hexdigest()
            result = load_result(connection, digest)
            if result is None:
                result = extract_pdf(content)
                save_result(connection, digest, result)
            record_source(connection, path.name, digest)
            pages = [
                Page(path.name, item["number"], result["total_pages"], item["text"], item["error"])
                for item in result["pages"]
            ]
            documents.append(Document(
                path.name, digest, result["total_pages"], result["status"], result["message"], pages
            ))
    return documents
