"""Contesto temporale del solo chatbot, da metadati locali curati, senza rete."""

import re
from datetime import date, datetime, timedelta, timezone
from calendar import monthrange
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from edicola.timeline_dates import publication_date, MONTHS
from edicola.edition_dates import read_edition_metadata
from edicola.chat_data import bounded_context


def reference_day():
    try:
        return datetime.now(ZoneInfo("Europe/Rome")).date()
    except ZoneInfoNotFoundError:
        return datetime.now(timezone.utc).date()


def source_editions(root, sources):
    editions = read_edition_metadata(root)
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



def requested_publication_period(question: str):
    """Intervallo di edizioni esplicito; nessuna data ricavata dai nomi PDF."""
    month_names = "|".join(MONTHS)
    interval = re.search(
        rf"\bdal\s+(\d{{1,2}})(?:[°º])?\s+al\s+(\d{{1,2}})(?:[°º])?\s+"
        rf"({month_names})\s+(\d{{4}})\b", question, re.I
    )
    if interval:
        try:
            year, month = int(interval[4]), MONTHS[interval[3].lower()]
            start, end = date(year, month, int(interval[1])), date(year, month, int(interval[2]))
            return (start.isoformat(), end.isoformat()) if start <= end else None
        except (ValueError, KeyError):
            return None
    month = re.search(r"\b(" + month_names + r")\s+(\d{4})\b", question, re.I)
    if not month:
        return None
    try:
        year, number = int(month[2]), MONTHS[month[1].lower()]
        return date(year, number, 1).isoformat(), date(
            year, number, monthrange(year, number)[1]
        ).isoformat()
    except (ValueError, KeyError):
        return None


def retrieval_query(question, context):
    """La ricerca di una domanda autonoma non eredita domande e risposte precedenti.

    Solo i riferimenti espliciti a una notizia già discussa usano l'ultima domanda
    dell'utente per chiarire il soggetto. Le risposte AI non sono mai fonti.
    """
    previous = bounded_context(context)
    if not previous:
        return question
    followup = bool(re.search(
        r"\b(?:quest[oaie]|quell[oaie]|precedent[ei]|sopra|prima|stess[oaie]|"
        r"citat[oaie]|menzionat[oaie]|approfondisc\w*|continua|prosegui)\b",
        question, re.I))
    # Follow-up ellittici come «E gli edifici pubblici?» dipendono dal tema precedente.
    followup = followup or bool(re.match(r"^\s*(?:e|invece|ma)\b", question, re.I))
    if not followup:
        return question
    last_question = next(
        (item["content"] for item in reversed(previous) if item["role"] == "user"), "")
    if not last_question:
        return question
    return "Argomento precedente: " + last_question[:400] + "\nDomanda attuale: " + question
