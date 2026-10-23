"""Fonti indicizzate attuali e campionamento editoriale locale, senza API."""

import json
import re
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np  # Già dipendenza di ChromaDB.

from edicola.archive import IndexChunk, read_active_chunks
from edicola.vectorstore import open_collection, stored_records


@dataclass
class Catalog:
    chunks: list[IndexChunk]
    vectors: dict[str, list[float]]
    coverage: dict


def read_catalog(root: Path) -> Catalog:
    chunks, warnings = read_active_chunks(root / "data/archive.sqlite3", root / "data/incoming")
    collection = open_collection(root / "data/chroma")
    stored = stored_records(collection)
    current = [chunk for chunk in chunks if chunk.id in stored
               and stored[chunk.id]["text"] == chunk.text
               and stored[chunk.id]["metadata"].get("input_sha256") == chunk.fingerprint]
    vectors = {}
    if current:
        for offset in range(0, len(current), 500):
            result = collection.get(ids=[chunk.id for chunk in current[offset:offset + 500]], include=["embeddings"])
            vectors.update((identity, vector.tolist()) for identity, vector in zip(result["ids"], result["embeddings"]))
    edition_path = root / "data/editions.json"
    editions = json.loads(edition_path.read_text(encoding="utf-8")) if edition_path.exists() else {}
    counts = Counter(chunk.metadata["filename"] for chunk in current)
    total = Counter(chunk.metadata["filename"] for chunk in chunks)
    files = []
    for filename, count in sorted(total.items()):
        info = editions.get(filename, {})
        publication = str(info.get("publication", "")).strip()
        published = str(info.get("date", "")).strip()
        if published:
            date.fromisoformat(published)  # Non inferire date da file o ordine dei chunk.
        files.append({"pdf": filename, "publication": publication, "date": published,
                      "indexed": counts[filename], "total": count})
    coverage = {"indexed": len(current), "total": len(chunks), "files": files,
                "partial": len(current) < len(chunks), "warnings": warnings}
    if any(not item["publication"] or not item["date"] for item in files if item["indexed"]):
        warnings.append("Testata o data non disponibili per alcune edizioni: selezione bilanciata per PDF, senza inferire metadati.")
    return Catalog(current, vectors, coverage)


def topic_clusters(chunks: list[IndexChunk], vectors: dict, similarity: float) -> dict[str, int]:
    """Raggruppamento greedy deterministico per cosine, non ricostruzione di articoli."""
    centers, totals, assignments = [], [], {}
    for chunk in chunks:
        vector = np.asarray(vectors[chunk.id], dtype=float)
        norm = np.linalg.norm(vector)
        if not norm or not np.isfinite(vector).all():
            raise ValueError("Embedding non valido nel catalogo.")
        vector = vector / norm
        scores = [float(vector @ center) for center in centers]
        group = int(np.argmax(scores)) if scores else -1
        if group < 0 or scores[group] < similarity:
            group = len(centers)
            centers.append(vector)
            totals.append(vector.copy())
        else:
            totals[group] += vector
            centers[group] = totals[group] / np.linalg.norm(totals[group])
        assignments[chunk.id] = group
    return assignments


def near_duplicate(first: str, second: str) -> bool:
    """Conservativo: non accorpare fatti con numeri diversi o il solo overlap."""
    a, b = re.findall(r"\w+", first.casefold()), re.findall(r"\w+", second.casefold())
    if a == b:
        return True
    if min(len(a), len(b)) < 20 or min(len(a), len(b)) / max(len(a), len(b)) < 0.9:
        return False
    if re.findall(r"\d+(?:[.,]\d+)*", first) != re.findall(r"\d+(?:[.,]\d+)*", second):
        return False
    shingles = lambda tokens: {tuple(tokens[index:index + 4]) for index in range(len(tokens) - 3)}
    left, right = shingles(a), shingles(b)
    return len(left & right) / len(left | right) >= 0.9


def headline_priority(chunk: IndexChunk) -> int:
    """Indizi, non riconoscimento di articoli: titoli brevi/capitali e inizio pagina."""
    prefix = chunk.text[:180]
    words = re.findall(r"[^\W\d_]+", prefix, flags=re.UNICODE)
    capitals = sum(word.isupper() and len(word) > 2 for word in words[:12])
    heading = bool(re.search(r"^[^.!?]{12,110}(?:[.!?]|:)", prefix))
    front_page = chunk.metadata["page"] == 1
    page_start = chunk.metadata.get("start", 0) == 0
    return 3 * int(capitals >= 3) + int(heading) + 2 * int(front_page) + int(page_start)


def balanced_briefing(catalog: Catalog, limit: int, similarity: float) -> list[IndexChunk]:
    """Alterna testate e date/edizioni; favorisce temi frequenti e testi distinti."""
    chunks = sorted(catalog.chunks, key=lambda item: (item.metadata["filename"], item.metadata["position"]))
    if not chunks:
        return []
    topics = topic_clusters(chunks, catalog.vectors, similarity)
    frequency = Counter(topics.values())
    editions = {item["pdf"]: item for item in catalog.coverage["files"]}
    pools = defaultdict(lambda: defaultdict(list))
    for chunk in chunks:
        info = editions[chunk.metadata["filename"]]
        publication = info["publication"] or info["pdf"]
        pools[publication][(info["date"], info["pdf"])].append(chunk)
    queues = {}
    for publication, edition_pools in sorted(pools.items()):
        queues[publication] = deque(
            sorted(items, key=lambda chunk: (-frequency[topics[chunk.id]], chunk.metadata["position"]))
            for _, items in sorted(edition_pools.items())
        )
    selected, seen_topics, seen_pages = [], set(), set()
    while queues and len(selected) < limit:
        for publication in list(queues):
            editions_queue = queues[publication]
            chosen = None
            while editions_queue and chosen is None:
                candidates = editions_queue.popleft()
                candidates[:] = [chunk for chunk in candidates
                                 if len(chunk.text.strip()) >= 40
                                 and not any(near_duplicate(chunk.text, other.text) for other in selected)]
                if candidates:
                    index = max(range(len(candidates)), key=lambda i: (
                        (candidates[i].metadata["filename"], candidates[i].metadata["page"]) not in seen_pages,
                        headline_priority(candidates[i]), topics[candidates[i].id] not in seen_topics,
                        frequency[topics[candidates[i].id]], -candidates[i].metadata["position"],
                    ))
                    chosen = candidates.pop(index)
                    if candidates:
                        editions_queue.append(candidates)
            if not editions_queue:
                del queues[publication]
            if chosen is not None:
                selected.append(chosen)
                seen_topics.add(topics[chosen.id])
                seen_pages.add((chosen.metadata["filename"], chosen.metadata["page"]))
            if len(selected) == limit:
                break
    return selected
