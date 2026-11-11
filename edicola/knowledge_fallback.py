"""Estrazione conservativa di prove per i soli prodotti di esplorazione.

Niente nuove API: candidati letterali da chunk già indicizzati, sempre
sottoposti ai validatori esistenti prima della pubblicazione.
"""
import re

# Due soggetti nominati e un predicato esplicito, nello stesso segmento.
# Le corrispondenze non trasformano dichiarazioni attribuite in fatti accertati.
RELATION = re.compile(
    r"\b([A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ’'-]{2,})\s+"
    r"(attacca|critica|accusa|convoca|incontra|sostiene|interroga|"
    r"risponde\s+a|replica\s+a|chiede\s+a)\s+"
    r"([A-ZÀ-ÖØ-Þ][a-zà-öø-ÿ’'-]{2,})\b"
)
SKIP = {"Regione", "Comune", "Provincia", "Abruzzo", "Chieti", "Pescara",
        "Teramo", "Aquila", "Dissesto", "Emergenza", "Maltempo", "Politica"}


def graph_candidates(raw, sources, topic):
    """Integra solo archi soggetto-verbo-oggetto leggibili letteralmente."""
    from edicola.knowledge_relevance import Topic
    matcher = Topic(topic)
    result = {"nodes": list(raw.get("nodes", [])), "edges": list(raw.get("edges", []))}
    labels = {n["label"]["text"].casefold(): n["id"] for n in result["nodes"]
              if isinstance(n, dict) and isinstance(n.get("label"), dict)}
    next_id = max((int(n["id"][1:]) for n in result["nodes"]
                   if isinstance(n, dict) and re.fullmatch(r"N\d+", str(n.get("id", "")))), default=0) + 1
    existing = {(e.get("from_id"), e.get("to_id"), e.get("predicate") or e.get("label", {}).get("text"))
                for e in result["edges"] if isinstance(e, dict)}
    for source in sources:
        # Solo frasi nel contesto tematico. Non inferire dalla mera co-occorrenza.
        sentences = re.split(r"(?<=[.!?])\s+|\n{2,}", source.text)
        for segment in sentences:
            if len(result["edges"]) >= 24 or len(result["nodes"]) >= 16:
                break
            if matcher.score(segment) <= 0:
                # Evita di recuperare un confronto fra persone fuori tema.
                continue
            for match in RELATION.finditer(segment):
                left, predicate, right = match.groups()
                if left in SKIP or right in SKIP or left == right:
                    continue
                if len(result["edges"]) >= 24 or len(result["nodes"]) + sum(x.casefold() not in labels for x in (left, right)) > 16:
                    break
                quote = segment.strip()
                if not 25 <= len(quote) <= 1800:
                    continue
                ids = []
                for name in (left, right):
                    key = name.casefold()
                    if key not in labels:
                        identity = f"N{next_id}"
                        next_id += 1
                        result["nodes"].append({"id": identity, "kind": "person",
                            "label": {"text": name, "evidence": [{"source_id": source.id, "quote": quote}]}})
                        labels[key] = identity
                    ids.append(labels[key])
                signature = (ids[0], ids[1], predicate)
                if signature in existing:
                    continue
                result["edges"].append({"from_id": ids[0], "to_id": ids[1],
                    "kind": "documented", "predicate": predicate,
                    "label": {"text": predicate,
                              "evidence": [{"source_id": source.id, "quote": quote}]}})
                existing.add(signature)
    return result


def source_developments(sources, topic, *, limit=7):
    """Sviluppi letterali di riserva; la data di edizione è solo per la vista."""
    from edicola.knowledge_relevance import Topic
    matcher = Topic(topic)
    output, seen_editions, seen_text = [], set(), set()
    for source in sources:
        if source.filename in seen_editions:
            continue
        segments = re.split(r"(?<=[.!?])\s+|\n{2,}", source.text)
        ranked = []
        for segment in segments:
            passage = " ".join(segment.split())
            if not 45 <= len(passage) <= 550:
                continue
            score = matcher.score(passage)
            if score > 0:
                ranked.append((score, passage, segment.strip()))
        if not ranked:
            continue
        ranked.sort(key=lambda item: (-item[0], len(item[1])))
        _, sentence, original = ranked[0]
        signature = sentence.casefold()
        if signature in seen_text:
            continue
        seen_text.add(signature)
        seen_editions.add(source.filename)
        evidence = [{"source_id": source.id, "quote": original}]
        output.append({"title": {"text": sentence[:min(95, len(sentence))].rsplit(" ", 1)[0] or sentence,
                                   "evidence": evidence},
                       "description": {"text": sentence, "evidence": evidence},
                       "event_date": None, "date_evidence": None})
        if len(output) >= limit:
            break
    return output
