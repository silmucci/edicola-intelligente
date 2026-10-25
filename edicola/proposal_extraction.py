"""Recupero estrattivo di elenchi nominali espliciti, mai integrazione di articoli."""

import re

MARKER = re.compile(r"\bTra le proposte (?:inoltrate|presentate|avanzate) al Governo\b", re.I)
ITEM = re.compile(r"^(?:(?:la|il|lo)\s+)?(?:proroga|modifica|sospensione|ristoro|ripristino|riduzione|aumento|estensione)\b", re.I)
STOP = re.compile(r";|[.!?](?=\s+[A-ZÀ-ÖØ-Ý«]|$)")
UNSAFE = re.compile(r"\b(non|mai|nega|smentisce|potrebbe|potrebbero|sarebbe|sarebbero|se)\b", re.I)


def proposal_items(sources, limit=12):
    events, seen = [], set()
    for source in sources:
        for marker in MARKER.finditer(source.text):
            before = source.text[:marker.start()]
            boundary = max(before.rfind(mark) for mark in (".", ";", "!", "?")) + 1
            if UNSAFE.search(before[boundary:] + marker.group()):
                continue
            start = marker.end()
            for stop in STOP.finditer(source.text, start):
                end = stop.end()
                item = source.text[start:stop.start()].strip(" :\n\r")
                if not ITEM.match(item):
                    break
                proof = source.text[marker.start():end]
                # Nessuna inferenza di agente o adozione: solo il punto dell'elenco
                # e il suo qualificatore documentale originale, entrambi letterali.
                if not UNSAFE.search(proof):
                    key = (source.chunk_id, item)
                    if key not in seen:
                        evidence = [{"source_id": source.id, "quote": proof}]
                        events.append({"title": {"text": item, "evidence": evidence},
                                       "description": {"text": item, "evidence": evidence},
                                       "event_date": None, "date_evidence": None})
                        seen.add(key)
                        if len(events) >= limit:
                            return events
                if stop.group() != ";":
                    break
                start = end
    return events
