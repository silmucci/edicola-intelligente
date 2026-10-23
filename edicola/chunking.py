"""Pulizia e chunking locali del testo già estratto, senza accesso ai PDF."""

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

from edicola.models import Document
from edicola.storage import load_chunks, open_registry, save_chunks


PIPELINE_VERSION = 1  # Incrementare se cambiano pulizia o algoritmo.
SENTENCE_END = re.compile(r'[.!?…]["»”’\)\]]*(?=\s|$)')


@dataclass(frozen=True)
class ChunkConfig:
    size: int = 1000
    overlap: int = 150

    def __post_init__(self):
        if not isinstance(self.size, int) or not isinstance(self.overlap, int):
            raise ValueError("Dimensione e overlap devono essere interi.")
        if self.size <= 0 or not 0 <= self.overlap < self.size:
            raise ValueError("Richiesti size > 0 e 0 <= overlap < size.")

    @property
    def signature(self) -> str:
        payload = {**asdict(self), "pipeline_version": PIPELINE_VERSION}
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


@dataclass(frozen=True)
class Chunk:
    id: str
    filename: str
    pdf_sha256: str
    page: int
    position: int
    start: int
    end: int
    text: str


@dataclass
class ChunkedDocument:
    filename: str
    chunks: list[Chunk] = field(default_factory=list)
    skipped_pages: dict[int, str] = field(default_factory=dict)


def clean_text(text: str) -> str:
    """Normalizza Unicode/spazi; conserva accenti, punteggiatura e sillabazione.

    Rimuove i trattini discrezionali, ma non ricompone arbitrariamente parole
    divise da trattini visibili: nei quotidiani le righe possono essere colonne.
    """
    text = unicodedata.normalize("NFKC", text)
    text = "".join(
        char for char in text
        if char.isspace() or unicodedata.category(char) not in {"Cc", "Cf", "Cs"}
    )
    return re.sub(r"\s+", " ", text).strip()


def split_text(text: str, config: ChunkConfig) -> list[tuple[int, int, str]]:
    """Intervalli [start, end) nella pagina pulita, overlap esatto in caratteri.

    Preferisce frasi nell'ultimo quarto della finestra, poi spazi, poi il limite
    rigido. Il frammento finale può essere più corto. Non attraversa pagine.
    """
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + config.size, len(text))
        if end < len(text):
            minimum = start + max(config.overlap + 1, config.size * 3 // 4)
            boundaries = [match.end() for match in SENTENCE_END.finditer(text, minimum, end)]
            if boundaries:
                end = boundaries[-1]
            else:
                space = text.rfind(" ", minimum, end)
                if space >= minimum:
                    end = space
        chunks.append((start, end, text[start:end]))
        if end == len(text):
            break
        start = end - config.overlap
    return chunks


def build_chunks(document: Document, config: ChunkConfig) -> dict:
    """Genera dati indipendenti dal nome file per condividere copie e rinomine."""
    chunks = []
    skipped = {}
    pages = {page.number: page for page in document.pages}
    for number in range(1, document.total_pages + 1):
        page = pages.get(number)
        if page is None or page.error:
            skipped[number] = page.error if page else "Testo della pagina non disponibile."
            continue
        text = clean_text(page.text)
        if not text:
            skipped[number] = "Nessun testo utilizzabile dopo la pulizia."
            continue
        for start, end, content in split_text(text, config):
            position = len(chunks) + 1
            identity = f"{document.sha256}:{config.signature}:{number}:{start}:{end}"
            chunks.append({
                "id": hashlib.sha256(identity.encode()).hexdigest(),
                "page": number, "position": position,
                "start": start, "end": end, "text": content,
            })
    return {"chunks": chunks, "skipped_pages": skipped}


def prepare_documents(
    documents: list[Document], registry: Path, config: ChunkConfig = ChunkConfig()
) -> list[ChunkedDocument]:
    """Riusa per hash/configurazione; sostituisce atomicamente solo i set cambiati."""
    prepared = []
    with open_registry(Path(registry)) as connection:
        for document in documents:
            if document.sha256 is None:
                prepared.append(ChunkedDocument(document.filename))
                continue
            result = load_chunks(connection, document.sha256, config.signature)
            if result is None:
                result = build_chunks(document, config)
                save_chunks(connection, document.sha256, config.signature, result)
            prepared.append(ChunkedDocument(
                filename=document.filename,
                chunks=[Chunk(filename=document.filename, pdf_sha256=document.sha256, **item)
                        for item in result["chunks"]],
                skipped_pages={int(key): value for key, value in result["skipped_pages"].items()},
            ))
    return prepared
