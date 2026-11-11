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
