"""Contesto temporale del solo chatbot, da metadati locali curati, senza rete."""

import json
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from edicola.timeline_dates import publication_date


def reference_day():
    try:
        return datetime.now(ZoneInfo("Europe/Rome")).date()
    except ZoneInfoNotFoundError:
        return datetime.now(timezone.utc).date()


def source_editions(root, sources):
    try:
        editions = json.loads((root / "data/editions.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        editions = {}
    if not isinstance(editions, dict):
        editions = {}
    result = {}
    for source in sources:
        item = editions.get(source.filename, {})
        item = item if isinstance(item, dict) else {}
        published = publication_date(item.get("date"))
        name = item.get("publication")
        result[source.id] = {"publication": name.strip() if isinstance(name, str) and name.strip() else None,
                             "publication_date": published.isoformat() if published else None}
    return result


def temporal_context(question, editions, *, today=None):
    today = today or reference_day()
    current = bool(re.search(r"\b(oggi|attualmente|adesso|in tempo reale|al momento)\b", question, re.I))
    sensitive = current or bool(re.search(r"\b(novit[àa]|ultim[ioae]\s+(?:aggiornament\w*|notizi\w*)|recent[ie]|attual[ei])\b", question, re.I))
    # Finestra editoriale prudenziale, non una garanzia che la notizia sia aggiornata.
    days = 0 if current else 7
    dated = {key: publication_date(item.get("publication_date")) for key, item in editions.items()}
    recent = [key for key, value in dated.items() if value and today - timedelta(days=days) <= value <= today]
    available = [value for value in dated.values() if value and value <= today]
    return {"reference_date": today.isoformat(), "recency_requested": sensitive,
            "recency_window_days": days, "recent_source_ids": recent,
            "undated_source_ids": [key for key, value in dated.items() if value is None],
            "future_publication_source_ids": [key for key, value in dated.items() if value and value > today],
            "latest_available_publication": max(available).isoformat() if available else None,
            "live_verification_available": False}


def temporal_notice(context):
    if not context["recency_requested"]:
        return ""
    latest = context["latest_available_publication"]
    if not context["recent_source_ids"]:
        detail = f" L’edizione più recente tra le fonti recuperate è del {latest}." if latest else " Le fonti recuperate non hanno una data di pubblicazione utilizzabile."
        return "Non posso confermare aggiornamenti attuali con queste fonti." + detail + " La ricerca riguarda solo l’archivio, senza verifica in tempo reale."
    return (f"Consultazione dell’archivio al {context['reference_date']}: le fonti recuperate includono edizioni recenti, "
            "ma non costituiscono una verifica in tempo reale. Le date di pubblicazione sono indicate nelle fonti.")
