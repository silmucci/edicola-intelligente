"""Accorpamento conservativo di doppioni, senza identità inferite dalla città."""

import re
from copy import deepcopy


def compact_events(events):
    clean = lambda text: " ".join(re.sub(r"\[S\d+\]", "", text).casefold().split())
    kept, merged = [], 0
    for event in events:
        publication_days = {item["date"] for item in event["publication_dates"] if item.get("date")}
        key = (event["event_date"], event["event_status"], event["development_kind"],
               clean(event["title"]), clean(event["description"]))
        existing = next((item for item in kept if item[0] == key and
            (event["event_date"] or set(item[1]["source_ids"]) & set(event["source_ids"]) or
             publication_days and publication_days == {p["date"] for p in item[1]["publication_dates"] if p.get("date")}) and any(
            len(clean(a["quote"])) >= 80 and clean(a["quote"]) == clean(b["quote"])
            for a in item[1]["evidence"] for b in event["evidence"])), None)
        if existing is None:
            kept.append((key, deepcopy(event)))
            continue
        target = existing[1]
        for field in ("source_ids", "evidence", "publication_dates"):
            target[field].extend(value for value in event[field] if value not in target[field])
        merged += 1
    return [event for _, event in kept], merged
