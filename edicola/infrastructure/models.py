"""Dati esposti dal modulo di acquisizione."""

from dataclasses import dataclass, field


STATUS_LABELS = {
    "ok": "Estratto",
    "partial": "Estrazione parziale",
    "no_text": "Nessun testo estraibile",
    "empty": "PDF vuoto",
    "error": "Non leggibile",
}


@dataclass
class Page:
    filename: str
    number: int
    total_pages: int
    text: str
    error: str = ""


@dataclass
class Document:
    filename: str
    sha256: str | None
    total_pages: int
    status: str
    message: str = ""
    pages: list[Page] = field(default_factory=list)

    @property
    def status_label(self) -> str:
        return STATUS_LABELS[self.status]
