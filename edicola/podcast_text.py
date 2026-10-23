"""Copioni estrattivi dalle cache editoriali: nessuna riscrittura AI o nuova ricerca."""

import json
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from edicola.editorial import EditorialResult
from edicola.rag import Source


REFERENCES = re.compile(r"\[\s*S\d+(?:[\s,;]+S\d+)*\s*\]")
MAX_WORDS = 240
MAX_CHARS = 3500


class PodcastError(RuntimeError):
    """Messaggio pubblico senza contenuti della richiesta o credenziali."""


@dataclass
class CachedProduct:
    key: str
    created_at: str
    result: EditorialResult


@dataclass
class Script:
    text: str
    sources: list[dict]
    coverage: dict
    selected_sections: int
    total_sections: int

    @property
    def excerpt(self):
        return self.selected_sections < self.total_sections


def list_products(root: Path) -> list[CachedProduct]:
    path = root / "data/editorial.sqlite3"
    if not path.is_file():
        return []
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
            rows = connection.execute("SELECT cache_key, created_at, result_json FROM products ORDER BY created_at DESC, cache_key").fetchall()
        products = []
        for key, created, raw in rows:
            try:
                data = json.loads(raw)
                data["sources"] = [Source(**s) for s in data["sources"]]
                result = EditorialResult(**data)
                if result.kind in {"dossier", "briefing"} and result.sufficient is True and result.sections:
                    products.append(CachedProduct(key, created, result))
            except (ValueError, TypeError, KeyError):
                continue  # Le vecchie astensioni o voci illeggibili non diventano podcast.
        return products
    except (sqlite3.Error, OSError):
        raise PodcastError("Cache editoriale non leggibile: nessun nuovo briefing è stato generato.") from None


def spoken_text(text: str, filenames: list[str]) -> str:
    text = REFERENCES.sub("", text)
    text = re.sub(r"!?\[([^\]]+)\]\([^)]*\)", r"\1", text)
    for filename in sorted(filenames, key=len, reverse=True):
        text = re.sub(re.escape(filename), "", text, flags=re.I)
    text = re.sub(r"\b[^\s<>\[\]]+\.pdf\b", "", text, flags=re.I)
    text = re.sub(r"</?[A-Za-z][^>]*>", "", text)  # Anche i tag vocali non appartengono al copione.
    text = re.sub(r"(?m)^\s*(?:-{3,}|\*{3,}|_{3,})\s*$", "", text)
    # Un segno davanti a cifre o valuta può essere un dato, non un punto elenco.
    text = re.sub(r"(?m)^\s*(?:#{1,6}\s+|[-*+]\s+(?![\s\d€$£])|>\s*)", "", text)
    text = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m[1] or m[2], text)
    text = re.sub(r"(?<!\w)([*_])([^\s*_](?:[^*_\n]*[^\s*_])?)\1(?!\w)", r"\2", text)
    text = text.replace("`", "")
    return " ".join(text.split()).strip()


def prepare_script(product: CachedProduct) -> Script:
    result = product.result
    if (not isinstance(result.title, str) or not isinstance(result.sections, list) or not isinstance(result.sources, list)
            or not isinstance(result.coverage, dict)
            or not isinstance(result.used_source_ids, list)
            or not all(isinstance(identity, str) for identity in result.used_source_ids)
            or not all(isinstance(s.id, str) and isinstance(s.filename, str) and isinstance(s.page, int)
                       and s.page > 0 for s in result.sources)):
        raise PodcastError("Formato del prodotto editoriale o delle fonti non valido.")
    if result.kind not in {"briefing", "dossier"} or not result.sufficient:
        raise PodcastError("Selezionare un briefing o dossier già generato con fonti valide.")
    available = {s.id: s for s in result.sources}
    allowed = set(result.used_source_ids)
    if not allowed or not allowed <= available.keys() or len(available) != len(result.sources):
        raise PodcastError("Le fonti del prodotto editoriale non sono verificabili.")
    filenames = [s.filename for s in result.sources]
    title = spoken_text(result.title, filenames)
    parts, original, selected = [], [], 0
    if title:
        parts.append(title if title.endswith((".", "?", "!")) else title + ".")
        original.append(result.title)
    for section in result.sections:
        if not isinstance(section, dict) or not isinstance(section.get("text"), str) or not isinstance(section.get("heading", ""), str):
            raise PodcastError("Formato del prodotto editoriale non valido.")
        heading = spoken_text(section.get("heading", ""), filenames)
        body = spoken_text(section["text"], filenames)
        if not body:
            continue
        block = (heading + ". " if heading and heading.casefold() not in {"introduzione", "conclusioni"} else "") + body
        if not block.endswith((".", "?", "!")):
            block += "."
        candidate = "\n\n".join(parts + [block])
        if len(candidate) > MAX_CHARS or len(candidate.split()) > MAX_WORDS:
            break  # Non tagliare frasi, importi o sezioni per riempire il minutaggio.
        parts.append(block)
        original.extend([section.get("heading", ""), section["text"]])
        selected += 1
    if not selected:
        raise PodcastError("Nessuna sezione completa leggibile entro 240 parole e 3500 caratteri; scegliere un prodotto più breve.")
    used = list(dict.fromkeys(identity for text in original for match in REFERENCES.finditer(text)
                             for identity in re.findall(r"S\d+", match.group())))
    if not used or not set(used) <= allowed:
        raise PodcastError("Il testo selezionato contiene riferimenti alle fonti mancanti o non validi.")
    sources = [{"id": identity, "chunk_id": available[identity].chunk_id, "filename": available[identity].filename,
                "page": available[identity].page} for identity in used]
    return Script("\n\n".join(parts), sources, result.coverage, selected, len(result.sections))
