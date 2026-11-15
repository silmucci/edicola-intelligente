"""OCR locale opzionale sulle pagine con testo digitale insufficiente.

Tesseract lavora solo su pagine contenenti immagini raster significative;
nessuna richiesta API e nessuna sovrascrittura di estrazioni migliori.
"""
from __future__ import annotations

import re
import shutil
import subprocess


OCR_METHOD = "tesseract-ocr-v1"
TRIGGER_CHARS = 180
MIN_OCR_LETTERS = 55
MIN_IMAGE_COVERAGE = 0.22
MAX_PIXELS = 24_000_000
TIMEOUT_SECONDS = 40


def needs_ocr(text: str) -> bool:
    """Considera solo pagine con poco contenuto alfanumerico digitale."""
    return len(re.findall(r"\w", text or "", flags=re.UNICODE)) < TRIGGER_CHARS


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def _raster_coverage(page) -> float:
    """Esclude pagine bianche, grafica vettoriale e sole piccole icone."""
    area = float(page.rect.width * page.rect.height)
    if area <= 0:
        return 0.0
    total = 0.0
    largest = 0.0
    for item in page.get_image_info():
        bbox = item.get("bbox")
        if not bbox or len(bbox) != 4:
            continue
        x0, y0, x1, y1 = map(float, bbox)
        width = max(0.0, min(x1, page.rect.x1) - max(x0, page.rect.x0))
        height = max(0.0, min(y1, page.rect.y1) - max(y0, page.rect.y0))
        fraction = width * height / area
        total += fraction
        largest = max(largest, fraction)
    return min(1.0, total) if largest >= 0.12 else 0.0


def _use_recognized(recognized: str, current: str) -> bool:
    recognized_letters = len(re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]", recognized))
    current_letters = len(re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]", current))
    words = re.findall(r"\b\w{2,}\b", recognized, flags=re.UNICODE)
    return (recognized_letters >= MIN_OCR_LETTERS and len(words) >= 9 and
            recognized_letters > current_letters * 1.5 + 30)


def recognize_page(pdf_content: bytes, page_number: int, native_text: str = "") -> str | None:
    """Restituisce testo OCR solo se supera quello nativo; altrimenti None.

    page_number parte da 1, come i metadati delle citazioni.
    L'assenza del binario o un timeout non compromette il PDF originale.
    """
    if not needs_ocr(native_text) or not tesseract_available():
        return None
    try:
        import fitz

        with fitz.open(stream=pdf_content, filetype="pdf") as document:
            if document.needs_pass or not 1 <= page_number <= len(document):
                return None
            page = document[page_number - 1]
            if _raster_coverage(page) < MIN_IMAGE_COVERAGE:
                return None
            width, height = float(page.rect.width), float(page.rect.height)
            if width <= 0 or height <= 0:
                return None
            scale = min(200 / 72, (MAX_PIXELS / (width * height)) ** 0.5)
            if scale <= 0:
                return None
            image = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).tobytes("png")
        if len(image) > 20 * 1024 * 1024:
            return None
        completed = subprocess.run(
            ["tesseract", "stdin", "stdout", "-l", "ita+eng", "--psm", "3"],
            input=image, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=TIMEOUT_SECONDS, check=False,
        )
        if completed.returncode != 0:
            return None
        recognized = completed.stdout.decode("utf-8", errors="replace").strip()
        return recognized if _use_recognized(recognized, native_text) else None
    except (ImportError, OSError, ValueError, RuntimeError, TypeError,
            subprocess.TimeoutExpired, MemoryError):
        return None
