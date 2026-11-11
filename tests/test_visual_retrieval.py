"""Regressioni del retrieval dedicato a Timeline e Knowledge Graph."""
from types import SimpleNamespace

from edicola.knowledge_relevance import Topic, select_visual_evidence


def chunk(identity, text, filename):
    return SimpleNamespace(id=identity, text=text, metadata={"filename": filename})


def test_timeline_prioritizes_related_developments_and_diversifies_editions():
    question = "Ricostruisci la cronologia dell'emergenza idrogeologica in Abruzzo"
    items = [
        chunk("a", "Emergenza idrogeologica in Abruzzo: il vertice viene convocato il 7 novembre 2026.", "7.pdf"),
        chunk("b", "Emergenza idrogeologica in Abruzzo: Marsilio replica alle critiche il 9 novembre 2026.", "9.pdf"),
        chunk("c", "Emergenza idrogeologica in Abruzzo: il sindaco chiede risorse il 10 novembre 2026.", "10.pdf"),
        chunk("x", "Un libro di teatro e spie viene presentato a Pescara.", "6.pdf"),
    ]
    selected = select_visual_evidence("timeline", Topic(question, items), items, [], limit=3)
    assert {item.id for item in selected} == {"a", "b", "c"}


def test_map_retrieval_keeps_relational_passages_not_isolated_names():
    question = "Crea una mappa concettuale del dissesto idrogeologico in Abruzzo"
    items = [
        chunk("a", "Il dissesto idrogeologico in Abruzzo coinvolge la Provincia di Chieti, che convoca i sindaci.", "7.pdf"),
        chunk("b", "Sul dissesto idrogeologico in Abruzzo Legnini critica Marsilio e chiede interventi urgenti.", "10.pdf"),
        chunk("x", "Il teatro aquilano presenta nuove iniziative culturali.", "6.pdf"),
    ]
    selected = select_visual_evidence("map", Topic(question, items), items, [], limit=3)
    assert [item.id for item in selected] == ["a", "b"] or {item.id for item in selected} == {"a", "b"}


def test_visual_retrieval_has_no_unsupported_event_or_relation():
    question = "Dissesto idrogeologico in Abruzzo"
    items = [chunk("a", "In Abruzzo si parla del dissesto idrogeologico.", "a.pdf")]
    for kind in ("timeline", "map"):
        selected = select_visual_evidence(kind, Topic(question, items), items, [], limit=5)
        assert [item.id for item in selected] == ["a"]
        # Il selettore non fabbrica eventi o archi: quelli sono prodotti e verificati a valle.


def test_undated_news_are_ordered_by_publication_without_fabricating_event_date():
    from edicola.knowledge_presentation import ordered_timeline
    later = {"title": "Notizia di novembre", "event_date": None,
             "publication_dates": [{"source_id": "S2", "date": "2026-11-10"}]}
    earlier = {"title": "Notizia di ottobre", "event_date": None,
               "publication_dates": [{"source_id": "S1", "date": "2026-10-23"}]}
    ordered, missing = ordered_timeline([], [later, earlier])
    assert not missing
    assert ordered == [earlier, later]
    assert all(item["event_date"] is None for item in ordered)


def test_graph_candidates_have_literal_source_and_validated_relation():
    from edicola.knowledge_fallback import graph_candidates
    from edicola.knowledge_validation import validate_map
    from edicola.rag import Source

    text = "Dissesto idrogeologico in Abruzzo, Legnini attacca Marsilio: ai sindaci servono risposte."
    source = Source("S1", "chunk", "edizione.pdf", 13, text, .1)
    raw = graph_candidates({"nodes": [], "edges": []}, [source],
                           "emergenza idrogeologica in Abruzzo")
    assert len(raw["nodes"]) == 2 and len(raw["edges"]) == 1
    checked, details = validate_map(raw, [source])
    assert details["accepted_edges"] == 1
    assert checked["edges"][0]["label"] == "attacca"
    assert all(item["source_ids"] == ["S1"] for item in checked["nodes"])


def test_local_news_fallback_remains_undated_until_render():
    from edicola.knowledge_fallback import source_developments
    from edicola.knowledge_validation import validate_timeline
    from edicola.rag import Source
    text = "Il dissesto idrogeologico in Abruzzo provoca danni alle infrastrutture secondo gli articoli pubblicati."
    source = Source("S1", "chunk", "edizione.pdf", 13, text, .1)
    proposals = source_developments([source], "dissesto idrogeologico in Abruzzo")
    coverage = {"files": [{"pdf": "edizione.pdf", "date": "2026-11-10"}]}
    assert proposals and proposals[0]["event_date"] is None
    checked, _ = validate_timeline({"events": proposals}, [source], coverage)
    assert len(checked["undated_events"]) == 1
    assert checked["undated_events"][0]["event_date"] is None


def test_newspaper_headline_links_person_to_documented_proposal():
    from edicola.knowledge_fallback import graph_candidates
    from edicola.knowledge_validation import validate_map
    from edicola.rag import Source

    passage = "Dissesto idrogeologico, D'Amico chiede un piano straordinario per la sicurezza del territorio."
    source = Source("S1", "one", "8nov.pdf", 15, passage, .2)
    candidates = graph_candidates({"nodes": [], "edges": []}, [source], "dissesto idrogeologico in Abruzzo")
    graph, details = validate_map(candidates, [source])
    assert graph["edges"], details
    assert any(edge["label"].casefold() == "chiede" for edge in graph["edges"])


def test_newspaper_headline_links_office_to_documented_meeting():
    from edicola.knowledge_fallback import graph_candidates
    from edicola.knowledge_validation import validate_map
    from edicola.rag import Source

    passage = "Dissesto idrogeologico, il presidente della Provincia convoca un vertice straordinario."
    source = Source("S1", "two", "7nov.pdf", 19, passage, .2)
    candidates = graph_candidates({"nodes": [], "edges": []}, [source], "dissesto idrogeologico")
    graph, details = validate_map(candidates, [source])
    assert graph["edges"], details
    assert any(edge["label"].casefold() == "convoca" for edge in graph["edges"])
