"""Contesto adiacente delle mappe: solo chunk indicizzati e intervalli verificabili."""

from itertools import combinations


def contiguous(left, right):
    """Non basta la vicinanza nel risultato della ricerca o il nome del PDF."""
    required = {"pdf_sha256", "chunk_config", "page", "position", "start", "end", "filename"}
    a, b = left.metadata, right.metadata
    if not required <= a.keys() or not required <= b.keys():
        return False
    if any(a[key] != b[key] for key in ("pdf_sha256", "chunk_config", "page", "filename")):
        return False
    if b["position"] != a["position"] + 1 or not a["start"] < b["start"] <= a["end"] < b["end"]:
        return False
    if len(left.text) != a["end"] - a["start"] or len(right.text) != b["end"] - b["start"]:
        return False
    overlap = a["end"] - b["start"]
    return not overlap or left.text[-overlap:] == right.text[:overlap]


def select_map_chunks(seeds, available, max_neighbors=2):
    """Aggiunge al più due vicini per default, senza nuove query o nuovi vettori."""
    lookup = {(c.metadata.get("pdf_sha256"), c.metadata.get("position")): c for c in available}
    selected, seen = [], set()
    seed_ids = {c.id for c in seeds}
    added = 0
    for seed in seeds:
        if seed.id not in seen:
            selected.append(seed)
            seen.add(seed.id)
        for delta in (-1, 1):
            neighbor = lookup.get((seed.metadata.get("pdf_sha256"), seed.metadata.get("position", 0) + delta))
            if neighbor is None or neighbor.id in seen or neighbor.id in seed_ids or added >= max_neighbors:
                continue
            left, right = (neighbor, seed) if delta < 0 else (seed, neighbor)
            if contiguous(left, right):
                selected.append(neighbor)
                seen.add(neighbor.id)
                added += 1
    return selected


def joined_proofs(evidence, sources, contexts):
    """Unisce solo citazioni letterali che coprono porzioni contigue, non interi articoli.

    Le prove singole continuano a essere verificate dal validatore RAG invariato.
    I metadati arrivano dal catalogo Python, mai dalla risposta Gemini.
    """
    from edicola.archive import IndexChunk

    available = {s.id: s for s in sources}
    for first, second in combinations(evidence, 2):
        if first["source_id"] == second["source_id"]:
            continue
        pair = [first, second]
        if any(e["source_id"] not in contexts or "start" not in contexts[e["source_id"]] for e in pair):
            continue
        pair.sort(key=lambda e: contexts[e["source_id"]]["start"])
        a, b = [available[e["source_id"]] for e in pair]
        ma, mb = [contexts[e["source_id"]] for e in pair]
        left, right = IndexChunk(a.chunk_id, a.text, ma), IndexChunk(b.chunk_id, b.text, mb)
        if not contiguous(left, right):
            continue
        quotes = [" ".join(e["quote"].split()) for e in pair]
        # Una citazione ripetuta non ha una posizione documentale univoca.
        if any(source.text.count(quote) != 1 for source, quote in zip((a, b), quotes)):
            continue
        start_a = a.text.index(quotes[0])
        start_b = mb["start"] - ma["start"] + b.text.index(quotes[1])
        end_a, end_b = start_a + len(quotes[0]), start_b + len(quotes[1])
        if not start_a < start_b or end_b <= end_a:
            continue
        overlap = ma["end"] - mb["start"]
        original = a.text + b.text[overlap:]
        gap = original[end_a:start_b]
        if gap and not gap.isspace():
            continue
        yield {"text": original[start_a:end_b], "evidence": pair, "adjacent": True}
