"""Regressioni offline: esempi sintetici, nessun testo del corpus o API reale."""
from copy import deepcopy
from unittest.mock import Mock, patch
import pytest
from edicola.archive import IndexChunk
from edicola.editorial_selection import Catalog
from edicola.press_review import ranked_chunks, article_groups, filter_catalog, ReviewSelection
from edicola.timeline_dates import resolve_date, event_status
from edicola.timeline_events import compact_events
from edicola.map_relations import documented_relation
from edicola.map_literal import complete_nodes, literal_candidates
from edicola.knowledge_validation import validate_map, compact_map, explicit_aliases
from edicola.knowledge_relevance import Topic, relevant_map, scope_timeline
from edicola.rag import Source


def chunk(identity, text, filename="a.pdf", **metadata):
    return IndexChunk(identity, text, {"filename": filename, "page": 1, "position": 0,
        "pdf_sha256": "a" * 64, "chunk_config": "test", **metadata})


def test_ranking_does_not_require_every_word_and_normalizes_accents():
    chunks = [chunk("a", "La SANITA presenta carenze di medici."),
              chunk("b", "La struttura sanitaria ha lunghe attese.", "b.pdf"),
              chunk("c", "In Abruzzo riparte il campionato sportivo.")]
    with patch("google.genai.Client") as api:
        assert {c.id for c in ranked_chunks(chunks, "sanità abruzzese")} == {"a", "b"}
        api.assert_not_called()
    assert ranked_chunks(chunks, "!!!") == []


def test_verified_title_ranks_first_but_unverified_title_does_not():
    a = chunk("a", "Lunghe attese nella sanità.")
    b = chunk("b", "Sanità: carenza di medici. Altri dettagli.", article_title="Sanità: carenza di medici", article_title_verified=True)
    assert ranked_chunks([a, b], "sanità")[0].id == "b"


def test_article_groups_do_not_infer_identity_from_page():
    a, b = chunk("a", "Prima notizia."), chunk("b", "Seconda notizia.")
    assert len(article_groups([a, b])) == 2
    a.metadata["article_id"] = b.metadata["article_id"] = "verified-article"
    assert len(article_groups([a, b])) == 1
    b.metadata["pdf_sha256"] = "b" * 64
    assert len(article_groups([a, b])) == 2


@pytest.mark.parametrize("quote,expected,status", [
    ("I lavoratori hanno manifestato il 24 ottobre 2026.", "2026-10-24", "occurred"),
    ("I lavoratori hanno manifestato il 24 ottobre.", "2026-10-24", "occurred"),
    ("Ieri i lavoratori hanno manifestato in piazza.", "2026-10-24", "occurred"),
    ("Oggi i lavoratori hanno manifestato in piazza.", "2026-10-25", "occurred"),
    ("Domani si terrà il corteo dei lavoratori.", "2026-10-26", "announced"),
    ("Il giorno precedente alla pubblicazione i lavoratori hanno manifestato in piazza.", "2026-10-24", "occurred"),
    ("Il giorno precedente alla data dell'edizione i lavoratori hanno manifestato in piazza.", "2026-10-24", "occurred"),
    ("Il giorno precedente i lavoratori hanno manifestato in piazza.", None, "occurred"),
])
def test_explicit_relative_and_announced_dates(quote, expected, status):
    temporal = resolve_date(quote, None, "2026-10-25")
    assert temporal["event_date"] == expected
    assert event_status(quote, expected, "2026-10-25") == status


def test_query_interval_scopes_editions_but_does_not_create_event_dates():
    a, b = chunk("a", "A Pescara un corteo.", "a.pdf"), chunk("b", "A Pescara un presidio.", "b.pdf")
    cat = Catalog([a, b], {}, {"files": [{"pdf": "a.pdf", "date": "2026-10-24"}, {"pdf": "b.pdf", "date": "2026-10-30"}]})
    question = "Ricostruisci l'evoluzione delle notizie sulle proteste a Pescara dal 24 al 29 ottobre 2026."
    assert [c.id for c in scope_timeline(cat, question).chunks] == ["a"]
    assert cat.chunks == [a, b]
    topic = Topic(question)
    assert topic.score("A Pescara apre una mostra il 24 ottobre.") == 0
    assert topic.score("A Pescara è annunciato uno sciopero.") > 0


def test_duplicate_events_merge_proofs_across_editions_without_merging_announcements():
    quote = "I lavoratori della fabbrica hanno manifestato nella piazza della città per chiedere garanzie sul futuro occupazionale."
    first = {"event_date": "2026-10-24", "event_status": "occurred", "development_kind": "fact",
             "title": "Presidio dei lavoratori", "description": "I lavoratori manifestano.", "source_ids": ["S1"],
             "evidence": [{"source_id": "S1", "quote": quote}], "publication_dates": [{"date": "2026-10-25"}]}
    second = {**deepcopy(first), "description": "Manifestazione della fabbrica.", "source_ids": ["S2"],
              "evidence": [{"source_id": "S2", "quote": quote}], "publication_dates": [{"date": "2026-10-26"}]}
    announced = {**deepcopy(first), "event_status": "announced"}
    other = {**deepcopy(first), "title": "Corteo degli studenti"}
    events, merged = compact_events([first, second, announced, other])
    assert merged == 1 and len(events) == 3 and events[0]["source_ids"] == ["S1", "S2"]
    different_numbers = {**deepcopy(second), "description": "I manifestanti sono 300."}
    assert compact_events([first, different_numbers])[1] == 0


@pytest.mark.parametrize("left,predicate,right,quote,valid", [
    ("Mario Rossi", "ha presentato", "emendamento", "Mario Rossi ha presentato l'emendamento.", True),
    ("emendamento", "presentato dal", "Mario Rossi", "L'emendamento, presentato dal deputato del Partito Democratico (PD) Mario Rossi, riguarda i tribunali.", True),
    ("Mario Rossi", "ha presentato", "emendamento", "Mario Rossi parla dei tribunali. Lucia Bianchi ha presentato l'emendamento.", False),
    ("Mario Rossi", "ha presentato", "emendamento", "Mario Rossi non ha presentato l'emendamento.", False),
    ("Partito Democratico", "sostiene", "emendamento", "Il Partito Democratico (PD) interviene. Il PD sostiene l'emendamento.", True),
    ("Partito Democratico", "sostiene", "emendamento", "Il Partito Democratico interviene. Il PD sostiene l'emendamento.", False),
])
def test_active_passive_and_explicit_abbreviations(left, predicate, right, quote, valid):
    assert documented_relation(left, predicate, right, quote) is valid


def test_missing_intermediate_entities_are_literal_and_revalidated():
    text = "L'emendamento, presentato dal deputato Mario Rossi e sostenuto anche dal Partito Democratico, è stato dichiarato inammissibile dalla Commissione Giustizia per la chiusura dei tribunali."
    source = Source("S1", "c", "a.pdf", 5, text, .2)
    raw = [{"id": "N1", "kind": "proposal", "label": {"text": "emendamento", "evidence": [{"source_id": "S1", "quote": text}]}}]
    completed = complete_nodes(raw, [source], accepted_ids={"N1"})
    data, _ = validate_map({"nodes": completed, "edges": []}, [source])
    labels = {n["label"] for n in data["nodes"]}
    assert {"Mario Rossi", "Commissione Giustizia", "Partito Democratico"} <= labels
    extra = literal_candidates(data["nodes"], [source], {})
    data, _ = validate_map({"nodes": completed, "edges": extra}, [source])
    assert len(data["edges"]) >= 2
    assert complete_nodes(raw, [source], accepted_ids=set()) == raw
    # Anche quando l'AI ha estratto soltanto l'autore, il provvedimento non si perde.
    person_only = [{"id": "N1", "kind": "person", "label": {"text": "Mario Rossi", "evidence": [{"source_id": "S1", "quote": text}]}}]
    completed = complete_nodes(person_only, [source], accepted_ids={"N1"})
    assert any(n["label"]["text"] == "emendamento" for n in completed)


def test_long_sentence_retains_intermediate_node_but_not_next_article():
    text = "L'emendamento per la chiusura dei tribunali " + "con tutte le garanzie richieste " * 8 + "è stato presentato da Mario Rossi. Mario Rossi apre una mostra fotografica."
    source = Source("S1", "c", "a.pdf", 5, text, .2)
    topic = Topic("Dibattito sulla chiusura dei tribunali abruzzesi")
    assert topic.evidence_score([{"source_id": "S1", "quote": text}], [source], anchor="Mario Rossi") > 0
    assert topic.evidence_score([{"source_id": "S1", "quote": "Mario Rossi apre una mostra fotografica."}], [source], anchor="mostra") == 0


def test_visible_graph_keeps_documented_bridge_without_adding_edges():
    nodes = [{"id": f"N{i}", "label": f"Concetto {i}", "kind": "concept"} for i in range(12)]
    edges = [{"from_id": "N0", "to_id": "N11", "kind": "documented"}, {"from_id": "N11", "to_id": "N1", "kind": "documented"}]
    data = {"nodes": nodes, "edges": edges}
    view = compact_map(data)
    assert len(view["nodes"]) == 10 and "N11" in {n["id"] for n in view["nodes"]}
    assert view["edges"] == edges and data["nodes"] == nodes


def test_card_navigation_preserves_readings_and_does_not_call_ai():
    from edicola import product_navigation as nav
    state = {"nav_section": "Rassegna stampa", "knowledge_results": {"timeline": "saved"},
             "consent_pending": {"action": "timeline"}, "rag_pending": {"new": True}}
    with patch.object(nav.st, "session_state", state), patch("google.genai.Client") as api:
        assert nav.open_product_id("timeline")
        assert state["nav_section"] == "Esplora" and state["knowledge_kind"] == "Timeline"
        assert state["knowledge_results"]["timeline"] == "saved"
        assert "consent_pending" not in state and state["rag_pending"]["new"] is False
        api.assert_not_called()


def test_explicit_aliases_merge_only_when_proven_without_destroying_edges():
    text = "Il Partito Democratico (PD) sostiene l'emendamento sui tribunali."
    source = Source("S1", "c", "a.pdf", 5, text, .2)
    nodes = [{"id": identity, "kind": "organization", "label": {"text": label,
              "evidence": [{"source_id": "S1", "quote": text}]}}
             for identity, label in (("N1", "Partito Democratico"), ("N2", "PD"))]
    raw = {"nodes": nodes, "edges": []}
    merged = explicit_aliases(raw, [source], {"N1", "N2"})
    assert len(merged["nodes"]) == 1 and len(raw["nodes"]) == 2
    unrelated = Source("S1", "c", "a.pdf", 5, "Il Partito Democratico interviene, il PD replica in un altro contesto.", .2)
    assert len(explicit_aliases(raw, [unrelated], {"N1", "N2"})["nodes"]) == 2


def test_party_extraction_does_not_turn_a_verb_into_an_organization():
    text = "L'emendamento lega i tribunali a un nuovo assetto territoriale."
    source = Source("S1", "c", "a.pdf", 5, text, .2)
    raw = [{"id": "N1", "kind": "proposal", "label": {"text": "emendamento", "evidence": [{"source_id": "S1", "quote": text}]}}]
    completed = complete_nodes(raw, [source], accepted_ids={"N1"})
    assert not any(n["label"]["text"].casefold() == "lega" for n in completed)


def test_review_form_waits_for_submit_and_preserves_briefing_filters():
    from streamlit.testing.v1 import AppTest
    code = '''
from types import SimpleNamespace
import streamlit as st
from edicola.archive import IndexChunk
from edicola.editorial_selection import Catalog
from edicola.press_review_ui import render_press_review
chunks = [IndexChunk('a', 'La sanità registra carenze di medici.', {'filename':'a.pdf','page':1,'position':0}),
          IndexChunk('b', 'La scuola apre nuove classi.', {'filename':'b.pdf','page':1,'position':0})]
catalog = Catalog(chunks, {}, {'files':[]})
render_press_review(catalog, None, {})
'''
    with patch("google.genai.Client") as api, patch("edicola.consent.decision", return_value=False):
        app = AppTest.from_string(code)
        app.session_state["editorial_review_files"] = ["obsolete.pdf"]
        app.session_state["editorial_review_latest"] = True
        app.run()
        assert not app.exception and len(app.text_input) == 1 and not app.selectbox and not app.multiselect
        assert app.session_state["editorial_review_files"] == ["obsolete.pdf"]
        assert app.session_state["editorial_review_latest"] is True
        app.text_input[0].set_value("sanità abruzzese").run()
        assert "editorial_press_query" not in app.session_state
        app.text_input[0].set_value("sanità abruzzese")
        app.button[0].click().run()
        assert not app.exception and app.session_state["editorial_press_query"] == "sanità abruzzese"
        assert any("carenze" in item.value for item in app.markdown)
        assert not any("nuove classi" in item.value for item in app.markdown)
        api.assert_not_called()


def test_review_cache_strategy_changes_without_changing_catalog():
    cat = Catalog([chunk("a", "La sanità registra carenze di medici.")], {},
                  {"files": [{"pdf": "a.pdf", "date": "2026-10-25"}]})
    original = deepcopy(cat)
    first = filter_catalog(cat, ReviewSelection("sanità abruzzese"))
    with patch("edicola.press_review.VERSION", "future-strategy"):
        other = filter_catalog(cat, ReviewSelection("sanità abruzzese"))
    assert first.coverage["selection_version"] != other.coverage["selection_version"]
    assert cat == original


def test_authorized_semantic_review_runs_only_on_explicit_submit_without_retry():
    from streamlit.testing.v1 import AppTest
    code = '''
from pathlib import Path
from types import SimpleNamespace
from edicola.archive import IndexChunk
from edicola.editorial_selection import Catalog
from edicola.press_review_ui import render_press_review
from unittest.mock import patch
catalog = Catalog([IndexChunk('a', 'Mancano medici nella struttura regionale.', {'filename':'a.pdf','page':1,'position':0})], {}, {})
with patch('edicola.pdf_viewer.source_button'):
    render_press_review(catalog, SimpleNamespace(root=Path('.')), {})
'''
    hits = [{"id": "a", "text": "Mancano medici nella struttura regionale.", "distance": .2}]
    with patch("edicola.consent.decision", return_value=True), patch("edicola.consent.perform", return_value=hits) as perform, patch("google.genai.Client") as api:
        app = AppTest.from_string(code).run()
        perform.assert_not_called()
        app.text_input[0].set_value("sanità abruzzese")
        app.button[0].click().run()
        assert not app.exception and perform.call_count == 1
        assert app.session_state["editorial_press_hits"] == hits
        app.run()
        assert perform.call_count == 1
        perform.side_effect = RuntimeError("SDK unavailable")
        app.text_input[0].set_value("ospedali")
        app.button[0].click().run()
        assert not app.exception and perform.call_count == 2 and app.session_state["editorial_press_hits"] == []
        app.run()
        assert perform.call_count == 2
        api.assert_not_called()


def test_map_literal_recovers_explicit_government_relation_without_inventing_arcs():
    text = "Giorgia Meloni guida il Governo e presenta un piano per le imprese."
    source = Source("S1", "chunk", "giornale.pdf", 2, text, 0.1)
    nodes = [
        {"id": "N1", "kind": "person", "label": {"text": "Giorgia Meloni",
         "evidence": [{"source_id": "S1", "quote": text}]}},
        {"id": "N2", "kind": "organization", "label": {"text": "Governo",
         "evidence": [{"source_id": "S1", "quote": text}]}},
    ]
    candidates = literal_candidates(
        [{"id": n["id"], "label": n["label"]["text"]} for n in nodes], [source], {})
    checked, _ = validate_map({"nodes": nodes, "edges": candidates}, [source])
    assert any(e["from_id"] == "N1" and e["to_id"] == "N2"
               and e["label"] == "guida" for e in checked["edges"])
    assert all(e["evidence"][0]["quote"] == text for e in checked["edges"])


def test_map_does_not_infer_institution_from_adjacent_person_name():
    text = "La riforma del lavoro è discussa dal Consiglio Giorgia Meloni sostiene la proposta."
    source = Source("S1", "chunk", "giornale.pdf", 2, text, 0.1)
    nodes = [{"id": "N1", "kind": "measure", "label": {"text": "riforma del lavoro",
              "evidence": [{"source_id": "S1", "quote": text}]}}]
    expanded = complete_nodes(nodes, [source], accepted_ids={"N1"})
    assert "Consiglio Giorgia" not in [node["label"]["text"] for node in expanded]
