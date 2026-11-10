"""Estrazione testuale e geometria dei PDF; nessuna API o OCR."""
from __future__ import annotations

from dataclasses import dataclass

try:
    import fitz
except ImportError:  # Il lettore pypdf rimane utilizzabile.
    fitz = None


EXTRACTION_VERSION = "pymupdf-layout-v1"


@dataclass(frozen=True)
class TextBlock:
    bbox: tuple[float, float, float, float]
    text: str
    font_size: float

    def as_dict(self):
        return {"bbox": [round(value, 2) for value in self.bbox],
                "text": self.text, "font_size": round(self.font_size, 2)}


def text_blocks(page) -> list[TextBlock]:
    """Scarta immagini e conserva testo, coordinate e dimensione massima dei caratteri."""
    info = page.get_text("dict", flags=fitz.TEXTFLAGS_TEXT)
    result = []
    for block in info.get("blocks", []):
        if block.get("type") != 0:
            continue
        lines = []
        sizes = []
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = "".join(str(span.get("text", "")) for span in spans).strip()
            if text:
                lines.append(text)
                sizes.extend(float(span.get("size", 0)) for span in spans)
        if lines and len(block.get("bbox", [])) == 4:
            result.append(TextBlock(tuple(float(v) for v in block["bbox"]),
                                    "\n".join(lines), max(sizes or [0])))
    return result


def reading_order(blocks: list[TextBlock], width: float) -> list[TextBlock]:
    """Euristica prudente per due colonne; le testate a tutta larghezza separano fasce.

    Per impaginazioni non riconoscibili si torna all'ordine geometrico normale.
    Non è una segmentazione degli articoli.
    """
    geometry = lambda b: (b.bbox[1], b.bbox[0])
    if len(blocks) < 3 or width <= 0:
        return sorted(blocks, key=geometry)
    midpoint = width / 2
    narrow = [b for b in blocks if b.bbox[2] - b.bbox[0] < width * .70]
    left = [b for b in narrow if b.bbox[2] <= midpoint + width * .05]
    right = [b for b in narrow if b.bbox[0] >= midpoint - width * .05]
    if not left or not right:
        return sorted(blocks, key=geometry)

    # Non assegnare due colonne se i blocchi si sovrappongono orizzontalmente.
    if max(b.bbox[2] for b in left) > min(b.bbox[0] for b in right) + width * .02:
        return sorted(blocks, key=geometry)
    wide = sorted((b for b in blocks if b not in left and b not in right), key=geometry)
    bands = []
    previous = float("-inf")
    for anchor in wide:
        bands.append((previous, anchor.bbox[1], anchor))
        previous = anchor.bbox[1]
    bands.append((previous, float("inf"), None))
    ordered = []
    assigned = set()
    for low, high, anchor in bands:
        candidates = [b for b in left + right if low <= b.bbox[1] < high and id(b) not in assigned]
        candidates.sort(key=lambda b: (int(b in right), b.bbox[1], b.bbox[0]))
        ordered.extend(candidates)
        assigned.update(map(id, candidates))
        if anchor is not None:
            ordered.append(anchor)
    ordered.extend(b for b in sorted(blocks, key=geometry) if id(b) not in
                   assigned and b not in wide)
    return ordered


def extract_layout(content: bytes) -> list[dict] | None:
    """Una pagina può fallire senza invalidare tutte le altre; non genera immagini."""
    if fitz is None:
        return None
    try:
        with fitz.open(stream=content, filetype="pdf") as document:
            if document.needs_pass:
                return None
            pages = []
            for page in document:
                try:
                    blocks = reading_order(text_blocks(page), float(page.rect.width))
                    pages.append({"text": "\n\n".join(b.text for b in blocks),
                                  "blocks": [b.as_dict() for b in blocks],
                                  "extraction_method": EXTRACTION_VERSION})
                except (ValueError, RuntimeError, TypeError, KeyError):
                    pages.append(None)
            return pages
    except (ValueError, RuntimeError, TypeError):
        return None
