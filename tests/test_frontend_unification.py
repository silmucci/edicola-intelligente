"""Navigazione semplificata: compatibilità e sottoviste senza chiamate AI."""

from unittest.mock import patch

from edicola import product_navigation as navigation


def test_six_visible_sections_and_profile_in_header():
    assert [p["id"] for p in navigation.PRODUCTS if p["id"] != "profile"] == [
        "archive", "for_you", "chat", "briefing", "podcast", "explore"
    ]
    assert len({p["section"] for p in navigation.PRODUCTS}) == 7
    assert navigation.destination("profile") == "Il mio profilo"


def test_old_links_resolve_into_correct_new_sections():
    expected = {
        "home": "Per te",
        "Rassegna stampa": "Per te",
        "timeline": "Esplora",
        "map": "Esplora",
        "Mappe concettuali": "Esplora",
        "Timeline": "Esplora",
        "Archivio PDF": "In edicola",
    }
    for old, new in expected.items():
        assert navigation.destination(old) == new
        if old not in {"home", "timeline", "map"}:
            assert navigation.active_product(old)["section"] == new


def test_old_section_restores_its_selected_subview():
    state = {"nav_section": "Mappe concettuali"}
    with patch.object(navigation.st, "session_state", state), patch(
        "edicola.editorial_components.render_products"
    ):
        section = navigation.render_navigation()
    assert section == "Esplora"
    assert state["nav_section"] == "Esplora"
    assert state["knowledge_kind"] == "Mappa"

    state = {"nav_section": "Rassegna stampa"}
    with patch.object(navigation.st, "session_state", state), patch(
        "edicola.editorial_components.render_products"
    ):
        section = navigation.render_navigation()
    assert section == "Per te"
    assert state["for_you_mode"] == "Tutte le notizie"


def test_legacy_card_actions_do_not_generate_and_cancel_old_request():
    state = {"nav_section": "Briefing", "consent_pending": {"action": "briefing"},
             "rag_pending": {"new": True}}
    with patch.object(navigation.st, "session_state", state), patch(
        "google.genai.Client", side_effect=AssertionError("Nessuna API prevista")
    ):
        assert navigation.open_product_id("timeline")
    assert state["nav_section"] == "Esplora"
    assert state["knowledge_kind"] == "Timeline"
    assert "consent_pending" not in state
    assert state["rag_pending"]["new"] is False


def test_legacy_map_navigation_opens_explore_without_generating():
    """I riferimenti storici alle mappe rimangono navigabili senza API."""
    state = {"nav_section": "Chat AI", "knowledge_topic": "Piano trasporti"}
    with patch.object(navigation.st, "session_state", state), patch(
        "google.genai.Client", side_effect=AssertionError("Nessuna API prevista")
    ):
        assert navigation.open_product_id("map")
    assert state["nav_section"] == "Esplora"
    assert state["knowledge_kind"] == "Mappa"
    assert state["knowledge_topic"] == "Piano trasporti"


def test_subview_inputs_are_preserved_across_navigation():
    assert {"for_you_mode", "for_you_topic", "knowledge_kind", "knowledge_topic"}.issubset(
        navigation.VIEW_INPUTS
    )
