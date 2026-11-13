"""Strutture linguistiche dei casi locali, riscritte senza versionare gli articoli."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from edicola.functional_audit import LimitedClient
from edicola.api_guard import permission_scope, PermissionDenied
from edicola.knowledge_relevance import Topic
from edicola.knowledge_validation import validate_map, validate_timeline
from edicola.map_literal import literal_candidates
from edicola.map_relations import documented_relation, relation_category
from edicola.rag import Source
from edicola.timeline_dates import resolve_date


@pytest.mark.parametrize("text,expected", [
    ("A Pescara si prepara una manifestazione pacifica.", True),
    ("A Pescara è annunciata una mobilitazione dei lavoratori.", True),
    ("A Pescara apre una mostra fotografica.", False),
    ("A Roma è annunciato un corteo dei lavoratori.", False),
])
def test_protests_need_both_topic_and_city_with_variants(text, expected):
    topic = Topic("Proteste a Pescara")
    assert bool(topic.score(text)) is expected
    assert topic.semantic_allowed(text) is expected


def test_courts_query_does_not_match_any_generic_debate_or_abruzzo_mention():
    topic = Topic("Dibattito relativo alla chiusura dei tribunali abruzzesi")
    assert topic.score("Il dibattito relativo ai trasporti in Abruzzo.") == 0
    assert topic.score("La salvaguardia dei tribunali abruzzesi è in discussione.") > 0


@pytest.mark.parametrize("quote,published,expected", [
    ("Ieri si è svolta una manifestazione a Pescara.", "2026-10-25", "2026-10-24"),
    ("Domani si terrà una manifestazione a Pescara.", "2026-10-24", "2026-10-25"),
    ("Ieri si è svolta la riunione.", "2026-01-01", "2025-12-31"),
    ("Edizione del 25/10/2026 Ieri si è svolta una manifestazione a Pescara.", "2026-10-25", "2026-10-24"),
    ("Edizione del 25/10/2025 Ieri si è svolta una manifestazione a Pescara.", "2026-10-25", None),
    ("Ieri e domani sono previste riunioni.", "2026-10-25", None),
    ("Ha dichiarato: «Domani manifesteremo».", "2026-10-25", None),
    ("Ieri si è svolta la manifestazione «Per la scuola».", "2026-10-25", "2026-10-24"),
    ("All’epoca, un anno scorso, ieri si è svolta una manifestazione.", "2026-10-25", None),
    ("Domani si è svolta una manifestazione.", "2026-10-25", None),
    ("Ieri si è svolta una manifestazione.", "", None),
])
def test_relative_dates_need_verified_edition_and_unambiguous_context(quote, published, expected):
    assert resolve_date(quote, None, published)["event_date"] == expected


def test_indirect_date_does_not_drop_documented_event_or_turn_plan_into_fact():
    quote = "Il corteo a Pescara doveva essere ieri; i partecipanti hanno preferito restare a casa."
    source = Source("S1", "chunk", "a.pdf", 3, quote, .1)
    claim = {"text": quote, "evidence": [{"source_id": "S1", "quote": quote}]}
    raw = {"events": [{"title": claim, "description": claim, "event_date": None,
                       "date_evidence": {"source_id": "S1", "quote": quote}}]}
    data, _ = validate_timeline(raw, [source], {"files": [{"pdf": "a.pdf", "date": "2026-10-25"}]})
    assert data["events"][0]["event_date"] == "2026-10-24"
    assert data["events"][0]["event_status"] != "occurred"


def test_relative_deadline_is_not_the_date_of_a_proposal():
    from edicola.knowledge_presentation import deadline_reference
    assert deadline_reference("La proroga proposta arriva fino a domani.")


def test_unsupported_relative_date_in_paraphrase_falls_back_to_original_undated_evidence():
    quote = "Il sindaco ha dichiarato: «Domani ci sarà una mobilitazione a Pescara»."
    source = Source("S1", "chunk", "a.pdf", 3, quote, .1)
    claim = {"text": "Mobilitazione il 26 ottobre 2026.", "evidence": [{"source_id": "S1", "quote": quote}]}
    raw = {"events": [{"title": claim, "description": claim, "event_date": "2026-10-26",
                       "date_evidence": {"source_id": "S1", "quote": quote}}]}
    data, _ = validate_timeline(raw, [source], {"files": [{"pdf": "a.pdf", "date": "2026-10-25"}]})
    assert not data["events"] and len(data["undated_events"]) == 1
    assert "26 ottobre 2026" not in data["undated_events"][0]["description"]


@pytest.mark.parametrize("left,predicate,right,text,accepted", [
    ("emendamento", "presentato dal", "Mario Rossi", "L'emendamento, presentato dal deputato di Fratelli d’Italia Mario Rossi, sarà discusso.", True),
    ("emendamento", "è stato dichiarato inammissibile dalla", "Commissione Giustizia", "L'emendamento presentato per garantire la salvaguardia dei quattro presidi giudiziari è stato dichiarato inammissibile dalla Commissione Giustizia.", True),
    ("Mario Rossi", "ha criticato", "decisione", "Mario Rossi ha criticato la decisione.", True),
    ("Mario Rossi", "ha sostenuto", "emendamento", "Mario Rossi ha sostenuto l’emendamento.", True),
    ("Mario Rossi", "ha sostenuto", "emendamento", "Mario Rossi non ha sostenuto l’emendamento.", False),
    ("emendamento", "sostenuto anche dal", "Partito Democratico", "L’emendamento, presentato dal deputato di Fratelli d’Italia Mario Rossi e sostenuto anche dal Partito Democratico, sarà discusso.", True),
    ("emendamento", "sostenuto anche dal", "Partito Democratico", "L’emendamento, presentato dal deputato Mario Rossi, mentre il piano è sostenuto anche dal Partito Democratico.", False),
    ("Mario Rossi", "ha presentato", "emendamento", "Mario Rossi ha spiegato che Luigi Verdi ha presentato l’emendamento.", False),
])
def test_passives_roles_and_positions_keep_actor_scope(left, predicate, right, text, accepted):
    assert documented_relation(left, predicate, right, text) is accepted


def test_statement_attribution_requires_whole_quoted_object_and_is_distinct_from_fact():
    statement = "Il provvedimento non risolve tutti i problemi"
    text = f'«{statement}», ha dichiarato Mario Rossi.'
    assert documented_relation("Mario Rossi", "ha dichiarato", statement, text)
    assert not documented_relation("Mario Rossi", "ha dichiarato", "provvedimento", text)
    assert not documented_relation("Mario Rossi", "ha dichiarato", statement, "Non è vero che " + text)
    assert relation_category("ha criticato") == "attributed"
    assert relation_category("ha dichiarato inammissibile") == "documented"


def test_literal_completion_uses_only_existing_validated_nodes_and_revalidates_sources():
    quote = "L’emendamento è stato dichiarato inammissibile dalla Commissione Giustizia."
    source = Source("S1", "chunk", "a.pdf", 5, quote, .1)
    nodes = [{"id": f"N{i}", "kind": "concept", "label": {"text": label,
               "evidence": [{"source_id": "S1", "quote": quote}]}}
             for i, label in enumerate(("emendamento", "Commissione Giustizia"), 1)]
    data, _ = validate_map({"nodes": nodes, "edges": []}, [source])
    extra = literal_candidates(data["nodes"], [source], {})
    checked, _ = validate_map({"nodes": nodes, "edges": extra}, [source])
    assert len(checked["edges"]) == 1
    assert checked["edges"][0]["source_ids"] == ["S1"]
    assert not literal_candidates(data["nodes"][:1], [source], {})


def test_duplicates_need_matching_claims_and_proofs_not_same_city():
    from edicola.timeline_events import compact_events
    quote = "A Pescara i lavoratori della fabbrica hanno manifestato davanti allo stabilimento per chiedere garanzie sul futuro occupazionale."
    base = {"event_date": None, "event_status": "occurred", "development_kind": "fact",
            "title": "Presidio davanti alla fabbrica", "description": quote, "source_ids": ["S1"],
            "evidence": [{"source_id": "S1", "quote": quote}], "publication_dates": [{"source_id": "S1", "date": "2026-10-25"}]}
    second = deepcopy(base)
    second.update(source_ids=["S2"], evidence=[{"source_id": "S2", "quote": quote}])
    different = {**base, "title": "Corteo degli studenti", "description": "A Pescara gli studenti manifestano per il clima."}
    kept, merged = compact_events([base, second, different])
    assert len(kept) == 2 and merged == 1 and kept[0]["source_ids"] == ["S1", "S2"]


def test_live_audit_has_hard_limit_including_retries():
    client = Mock()
    limited = LimitedClient(client, 6)
    with permission_scope(lambda: True):
        for kind in ("timeline", "map", "chat"):
            limited.case = kind
            limited.embed()
            limited.generate()
            with pytest.raises(PermissionDenied):
                limited.generate()
        with pytest.raises(PermissionDenied):
            limited.embed()
    assert limited.calls == 6
    assert client.models.generate_content.call_count == client.models.embed_content.call_count == 3


def test_audit_does_not_confuse_publication_dates_with_health_quantities():
    from edicola.functional_audit import has_health_quantity
    assert not has_health_quantity("Edizione del 25/10/2026 pag. 15/38")
    assert has_health_quantity("La struttura dispone di 60 posti letto.")
    assert has_health_quantity("La quota raggiunge il 95% del totale.")


def test_native_node_focus_changes_only_graph_and_keeps_sources_without_ai(monkeypatch):
    from unittest.mock import patch
    from streamlit.testing.v1 import AppTest
    import streamlit as st
    from edicola.knowledge import KnowledgeResult
    from test_knowledge import map_data, SOURCES, COVERAGE
    from test_knowledge_exploration import installed_fixture, render_script
    monkeypatch.setenv("EDICOLA_ARCHIVE_DIAGNOSTICS", "0")
    data, counts = validate_map(map_data(), SOURCES)
    fixture, code = render_script(KnowledgeResult("map", "Trasporti", data, SOURCES, COVERAGE, counts))
    def graph_adapter(data, *, topic, selected, on_select):
        st.button("Seleziona N1", key="test_map_select_n1", on_click=on_select, args=("N1",))

    with installed_fixture(fixture), patch("google.genai.Client") as api, patch(
        "edicola.knowledge_views.render_graph", side_effect=graph_adapter) as graph:
        app = AppTest.from_string(code).run()
        app.button(key="test_map_select_n1").click().run()
        assert not app.exception and app.session_state["knowledge_map_focus"] == "N1"
        assert graph.call_args.kwargs["selected"] == "N1"
        assert any(SOURCES[0].text in text.value for text in app.text)
        graph.reset_mock()
        app.run()
        assert graph.called and not app.dataframe
        assert not any(c.key == "knowledge_map_view" for c in app.segmented_control)
        api.assert_not_called()
