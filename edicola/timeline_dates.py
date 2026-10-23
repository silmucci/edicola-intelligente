"""Normalizzazione temporale conservativa, senza orologio, API o date dai nomi PDF."""

import re
from datetime import date


MONTHS = {name: number for number, name in enumerate(
    ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
     "agosto", "settembre", "ottobre", "novembre", "dicembre"), start=1)}
WEEKDAYS = {name: index for index, names in enumerate(
    (("lunedì", "lunedi"), ("martedì", "martedi"), ("mercoledì", "mercoledi"),
     ("giovedì", "giovedi"), ("venerdì", "venerdi"), ("sabato",), ("domenica",))) for name in names}
WEEKDAY = r"(?:(?P<weekday>" + "|".join(WEEKDAYS) + r")\s*,?\s*)?"
NAMED = re.compile(r"\b" + WEEKDAY + r"(?P<day>\d{1,2})\s+(?P<month>" + "|".join(MONTHS)
                   + r")\b(?:\s+(?P<year>\d{4})\b)?", re.I)
NUMERIC = re.compile(r"(?<![\d/-])" + WEEKDAY + r"(?P<day>\d{1,2})[/-](?P<month>\d{1,2})"
                     r"(?:[/-](?P<year>\d{4}))?(?![\d/-])", re.I)
ISO = re.compile(r"(?<![\d/-])" + WEEKDAY + r"(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})(?![\d/-])", re.I)
FUTURE = re.compile(r"\b(prossim[oa]|si terrà|si svolgerà|avrà luogo|è in programma|è previst[oa]|sarà|approverà)\b", re.I)
PAST = re.compile(r"\b(scors[oa]|passat[oa]|si è svolt[oa]|si è tenut[oa]|ha avuto luogo|è avvenut[oa]|ha approvato|ha partecipato)\b", re.I)
OCCURRED = re.compile(r"\b(si è svolt[oa]|si è tenut[oa]|ha avuto luogo|è avvenut[oa]|ha approvato|ha partecipato)\b", re.I)
ANNOUNCED = re.compile(r"\b(annunciat[oa]|programmat[oa]|previst[oa])\b", re.I)
VERSION = "timeline-dates-v1"


def mentions(text):
    for pattern in (ISO, NAMED, NUMERIC):
        for match in pattern.finditer(text):
            fields = match.groupdict()
            month = fields["month"].casefold()
            yield (int(fields["year"]) if fields["year"] else None,
                   MONTHS[month] if month in MONTHS else int(month), int(fields["day"]),
                   WEEKDAYS[fields["weekday"].casefold()] if fields["weekday"] else None)


def documented_dates(text: str) -> set[str]:
    found = set()
    for year, month, day, _ in mentions(text):
        if year is not None:
            try:
                found.add(date(year, month, day).isoformat())
            except ValueError:
                pass
    return found


def publication_date(value):
    """Accetta solo il formato ISO dello schema editions.json, già curato localmente."""
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def resolve_date(quote, proposed, published):
    """Completa un anno solo con un ancoraggio documentale e indizi concordanti.

    Senza anno esplicito nel contesto, la finestra contemporanea è di 31 giorni:
    occorre anche un giorno settimanale o una direzione temporale esplicita.
    A cavallo d'anno la sola vicinanza e il giorno settimanale non bastano.
    """
    result = {"event_date": None, "date_status": "unverified", "date_origin": "undetermined",
              "date_reason": "insufficient_context", "date_rule": ""}
    def fail(reason, status="unverified"):
        return dict(result, date_reason=reason, date_status=status)
    if re.search(r"pubblicazion|edizione del|pubblicat[oa] il", quote, re.I):
        return fail("publication_reference", "publication_reference")
    values = set(mentions(quote))
    if not values:
        return fail("missing_calendar_date")
    if len(values) != 1:
        return fail("multiple_dates", "ambiguous")
    year, month, day, weekday = values.pop()
    try:
        date(year or 2000, month, day)
    except ValueError:
        return fail("invalid_calendar_date")
    pub = publication_date(published)
    future, past = bool(FUTURE.search(quote)), bool(PAST.search(quote))
    if future and past:
        return fail("conflicting_temporal_context", "ambiguous")
    text = quote.casefold()
    offsets = set()
    if re.search(r"quest['’]anno|anno in corso|anno corrente", text):
        offsets.add(0)
    if re.search(r"anno prossimo|prossimo anno", text):
        offsets.add(1)
    if re.search(r"anno scorso|scorso anno", text):
        offsets.add(-1)
    if len(offsets) > 1:
        return fail("conflicting_year_context", "ambiguous")
    relative = {delta for word, delta in (("oggi", 0), ("domani", 1), ("ieri", -1))
                if re.search(r"\b" + word + r"\b", text)}
    if len(relative) > 1:
        return fail("conflicting_relative_context", "ambiguous")
    # Un altro anno citato può indicare un contesto storico: non attribuirgli il corrente.
    if year is None and re.search(r"\b\d{4}\b", text):
        return fail("unbound_explicit_year", "ambiguous")
    if year is None and re.search(r"\b(?:" + "|".join(MONTHS) + r")\s+['’]?\d{2}\b", text):
        return fail("abbreviated_year", "ambiguous")
    if year is None and re.search(r"ricord|anniversario|all['’]epoca|nel passato|storico", text):
        return fail("historical_context", "ambiguous")
    if year is None and pub is None:
        return fail("missing_edition_date")
    if year is None and weekday is None and not (future or past or offsets or relative):
        return fail("missing_year_anchor", "ambiguous")
    candidates = []
    for candidate_year in ([year] if year else [pub.year - 1, pub.year, pub.year + 1]):
        try:
            candidate = date(candidate_year, month, day)
        except ValueError:
            continue
        if weekday is not None and candidate.weekday() != weekday:
            continue
        if pub:
            delta = (candidate - pub).days
            if future and delta < 0 or past and delta > 0:
                continue
            if offsets and candidate.year != pub.year + next(iter(offsets)):
                continue
            if relative and delta != next(iter(relative)):
                continue
            if year is None:
                if not offsets and abs(delta) > 31:
                    continue
                if candidate.year != pub.year and not (future or past or offsets or relative):
                    continue
        elif offsets or relative:
            return fail("missing_edition_date")
        candidates.append(candidate.isoformat())
    if len(candidates) != 1:
        return fail("calendar_or_context_conflict" if not candidates else "ambiguous_year", "ambiguous" if candidates else "unverified")
    resolved = candidates[0]
    if proposed is not None and proposed != resolved:
        return fail("model_date_conflict")
    return {"event_date": resolved, "date_status": "verified" if year else "completed_context",
            "date_origin": "explicit" if year else "edition_metadata", "date_reason": "",
            "date_rule": "explicit_text" if year else "edition_and_document_context"}


def event_status(quote, event_date, published):
    """Data passata non significa evento avvenuto; conta lo stato riferito dalla fonte."""
    future, past = bool(FUTURE.search(quote) or ANNOUNCED.search(quote)), bool(PAST.search(quote))
    pub = publication_date(published)
    when = publication_date(event_date)
    if future and past or past and pub and when and when > pub:
        return "conflicting"
    if future:
        return "announced"
    if pub and when and when > pub:
        return "future"
    return "occurred" if OCCURRED.search(quote) else "undetermined"
