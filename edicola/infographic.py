"""Infografica estrattiva da passaggi indicizzati, senza dati o frasi inventati."""

import re
from dataclasses import dataclass

from edicola.press_review import ReviewSelection, filter_catalog


@dataclass
class Infographic:
    topic: str
    blocks: list[dict]
    coverage: dict


def complete_quotes(chunk):
    """Confini conservativi: numeri decimali e abbreviazioni non chiudono frasi."""
    start = 0
    abbreviations = {"sig", "sigg", "dott", "prof", "on", "art", "n", "pag", "ecc"}
    for stop in re.finditer(r'[.!?](?:[»”"])?(?=\s+[A-ZÀ-ÖØ-Þ«“"]|\s*$)', chunk.text):
        prefix = chunk.text[:stop.start()]
        word = re.search(r"(\w+)$", prefix)
        if chunk.text[stop.start()] == "." and word and word[1].casefold() in abbreviations:
            continue
        quote = chunk.text[start:stop.end()].strip()
        if start > 0 or chunk.metadata.get("start", 0) == 0:
            yield quote
        start = stop.end()


def build_infographic(catalog, topic, *, limit=8):
    topic = " ".join(topic.split())
    if not re.search(r"\w", topic) or len(topic) > 500:
        raise ValueError("Inserisci un tema da 1 a 500 caratteri.")
    selected = filter_catalog(catalog, ReviewSelection(keyword=topic))
    terms = re.findall(r"\w+", topic.casefold())
    blocks, seen = [], set()
    # Frasi con inizio/fine documentati: escludere i bordi potenzialmente tagliati.
    for chunk in selected.chunks:
        for quote in complete_quotes(chunk):
            if not 30 <= len(quote) <= 650 or not all(term in quote.casefold() for term in terms):
                continue
            if quote in seen:
                continue
            # Rivalidazione letterale prima di presentare qualsiasi blocco.
            if quote not in chunk.text:
                continue
            seen.add(quote)
            blocks.append({"quote": quote, "chunk_id": chunk.id, "filename": chunk.metadata["filename"], "page": chunk.metadata["page"]})
            if len(blocks) == limit:
                return Infographic(topic, blocks, selected.coverage)
    return Infographic(topic, blocks, selected.coverage)
