"""Calendario e contesto temporale: solo funzioni locali, nessuna API."""

import pytest

from edicola.timeline_dates import event_status, resolve_date


@pytest.mark.parametrize("quote,published,expected,origin", [
    ("L'incontro si è svolto il 12 ottobre 2026.", "2026-10-17", "2026-10-12", "explicit"),
    ("L'incontro si è svolto il 12/10/2026.", "", "2026-10-12", "explicit"),
    ("L'incontro è previsto il 2026-10-21.", "2026-10-17", "2026-10-21", "explicit"),
    ("Mercoledì 21 ottobre è previsto un incontro.", "2026-10-17", "2026-10-21", "edition_metadata"),
    ("Mercoledì 21 ottobre: incontro sui trasporti.", "2026-10-17", "2026-10-21", "edition_metadata"),
    ("L'incontro si terrà il 21 ottobre.", "2026-10-17", "2026-10-21", "edition_metadata"),
    ("L'incontro si è svolto il 12 ottobre.", "2026-10-17", "2026-10-12", "edition_metadata"),
    ("L'incontro si terrà il 2 gennaio prossimo.", "2026-12-29", "2027-01-02", "edition_metadata"),
    ("L'incontro si è svolto lo scorso 30 dicembre.", "2027-01-03", "2026-12-30", "edition_metadata"),
    ("L'incontro è il 21 ottobre di quest'anno.", "2026-01-17", "2026-10-21", "edition_metadata"),
    ("L'incontro si terrà il 21 ottobre del prossimo anno.", "2026-10-17", "2027-10-21", "edition_metadata"),
    ("L'incontro era il 21 ottobre dello scorso anno.", "2026-10-17", "2025-10-21", "edition_metadata"),
    ("Domani, 18 ottobre, è previsto un incontro.", "2026-10-17", "2026-10-18", "edition_metadata"),
    ("Oggi, 17/10, incontro sui trasporti.", "2026-10-17", "2026-10-17", "edition_metadata"),
    ("Ieri, 16 ottobre, incontro sui trasporti.", "2026-10-17", "2026-10-16", "edition_metadata"),
    ("Lunedì 29 febbraio: incontro sui trasporti.", "2016-02-27", "2016-02-29", "edition_metadata"),
])
def test_explicit_and_documented_context_dates(quote, published, expected, origin):
    result = resolve_date(quote, None, published)
    assert result["event_date"] == expected
    assert result["date_origin"] == origin


@pytest.mark.parametrize("quote,published", [
    ("Incontro il 21 ottobre.", "2026-10-17"),  # Nessun indizio che individui l'anno.
    ("Mercoledì 21 ottobre: incontro.", ""),
    ("Mercoledì 21 ottobre: incontro.", "17/10/2026"),  # Lo schema richiede ISO.
    ("Giovedì 21 ottobre: incontro.", "2026-10-17"),  # Giorno settimanale incompatibile.
    ("Giovedì 21 ottobre 2026: incontro.", "2026-10-17"),
    ("L'incontro si terrà il 30 febbraio.", "2026-02-17"),
    ("L'incontro si terrà il 21 ottobre.", "2026-10-23"),  # Futuro incompatibile.
    ("L'incontro si è svolto il 21 ottobre.", "2026-10-17"),
    ("Sabato 2 gennaio: incontro.", "2026-12-29"),  # Rollover senza direzione.
    ("L'incontro si terrà il 21 ottobre.", "2026-01-17"),  # Troppo distante.
    ("Mercoledì 21 ottobre: si ricorda l'incontro storico.", "2026-10-17"),
    ("Mercoledì 21 ottobre, nel 2020, incontro.", "2026-10-17"),
    ("Mercoledì 21 ottobre, nel 1789, incontro.", "2026-10-17"),
    ("Mercoledì 21 ottobre '26: incontro.", "2026-10-17"),
    ("Il 21 ottobre o il 22 ottobre si terrà l'incontro.", "2026-10-17"),
    ("L'incontro si terrà domani, 21 ottobre.", "2026-10-17"),
    ("Ieri o domani, 21 ottobre, incontro.", "2026-10-17"),
    ("L'incontro si terrà il 21 ottobre dell'anno scorso.", "2026-10-17"),
    ("Edizione del 17 ottobre 2026: incontro.", "2026-10-17"),
])
def test_ambiguous_or_inconsistent_dates_remain_undetermined(quote, published):
    result = resolve_date(quote, None, published)
    assert result["event_date"] is None
    assert result["date_origin"] == "undetermined"
    assert result["date_reason"]


def test_model_cannot_override_verified_context():
    assert resolve_date("Mercoledì 21 ottobre: incontro.", "2025-10-21", "2026-10-17")["date_reason"] == "model_date_conflict"


@pytest.mark.parametrize("quote,when,published,expected", [
    ("Il convegno si terrà il 21 ottobre.", "2026-10-21", "2026-10-17", "announced"),
    ("Il convegno si terrà il 21 ottobre.", "2026-10-21", "2026-10-25", "announced"),
    ("Il convegno è annunciato.", None, "2026-10-17", "announced"),
    ("Il convegno del 21 ottobre.", "2026-10-21", "2026-10-17", "future"),
    ("Il convegno del 12 ottobre.", "2026-10-12", "2026-10-17", "undetermined"),
    ("Il convegno dello scorso anno.", "2025-10-12", "2026-10-17", "undetermined"),
    ("Il convegno si è svolto il 12 ottobre.", "2026-10-12", "2026-10-17", "occurred"),
    ("Il convegno si è svolto il 21 ottobre.", "2026-10-21", "2026-10-17", "conflicting"),
])
def test_announced_future_and_occurred_are_separate(quote, when, published, expected):
    assert event_status(quote, when, published) == expected
