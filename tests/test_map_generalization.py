"""La Mappa applica criteri comuni a rubriche eterogenee, con prove originali."""
import pytest
from types import SimpleNamespace

from edicola.knowledge_relevance import Topic, select_visual_evidence
from edicola.map_evidence import map_excerpts
from edicola.map_news_events import verified_news_relations
from edicola.map_story import story_graph
from edicola.map_retrieval import request_focus
from edicola.rag import Source


@pytest.mark.parametrize("topic,title,body", [
    ("Torneo regionale e vittoria della squadra",
     "Torneo regionale: la squadra conquista la coppa",
     "La squadra della città ha conquistato la coppa dopo una finale combattuta. "
     "Il capitano festeggia insieme ai compagni davanti ai tifosi della squadra."),
    ("Mostra al museo di pittura",
     "Il museo apre una mostra di pittura contemporanea",
     "Il museo inaugura una mostra che raccoglie opere di artisti contemporanei. "
     "I visitatori osservano dipinti provenienti da diverse collezioni private."),
    ("Nuovo materiale sviluppato nel laboratorio universitario",
     "Laboratorio universitario presenta nuovo materiale",
     "I ricercatori del laboratorio hanno scoperto un materiale capace di resistere alle alte temperature. "
     "Il gruppo sperimenta il materiale in condizioni diverse durante gli studi."),
    ("Alluvione e quartieri isolati",
     "Alluvione sul territorio: i quartieri restano isolati",
     "L'alluvione ha sommerso diverse strade e ha isolato alcuni quartieri della città. "
     "I residenti raccontano che i collegamenti con le frazioni sono difficili."),
    ("Commercio e trattato fra delegazioni",
     "Trattato sul commercio: le delegazioni si incontrano",
     "Le delegazioni dei Paesi si incontrano per negoziare nuove regole commerciali. "
     "Durante la riunione vengono discusse le condizioni di accesso al mercato."),
])
def test_cross_discipline_stories_have_literal_evidence(topic, title, body):
    source = Source("S1", "chunk", "quotidiano.pdf", 3, body, .12)
    raw = {"nodes": [], "edges": []}
    completed = verified_news_relations(raw, [source], {"S1": {"title": title}}, topic)
    graph = story_graph(completed, topic, sources=[source])
    assert raw == {"nodes": [], "edges": []}
    assert graph["nodes"] and graph["edges"], topic
    assert any(edge.get("context_scope") == "same_verified_article"
               for edge in graph["edges"])
    assert all(proof["quote"] in body for edge in graph["edges"]
               for proof in edge["evidence"])


def test_large_culture_article_keeps_non_institutional_actions():
    irrelevant = "Il torneo ha radunato numerosi atleti durante le gare di qualificazione. " * 20
    actual = "Il museo ospita una mostra che raccoglie dipinti di artisti contemporanei."
    content = irrelevant + actual
    passages = map_excerpts(content, "Mostra al museo", budget=180)
    assert actual in passages
    assert all(passage in content for passage in passages)


def test_semantic_hit_survives_without_exact_keyword_overlap():
    topic = "Innovazioni nella ricerca sui materiali"
    relevant = SimpleNamespace(id="sem", text="La comunità scientifica verifica nuove proprietà nei laboratori.",
                               metadata={"filename": "a.pdf"})
    unrelated = SimpleNamespace(id="other", text="Il campionato di pallavolo si conclude domenica.",
                                metadata={"filename": "b.pdf"})
    chunks = [relevant, unrelated]
    hits = [{"id": "sem", "distance": .14}]
    selected = select_visual_evidence("map", Topic(topic, chunks), chunks, hits, limit=2)
    assert [item.id for item in selected] == ["sem"]
    assert map_excerpts((relevant.text + " ") * 25, topic, budget=180, semantic_hit=True)


def test_generic_topics_are_not_a_fixed_blacklist():
    assert request_focus("Turismo sostenibile: notizie e iniziative") is None
    assert request_focus("Tecnologie e ricerca: scoperte e rischi") is None
    assert request_focus("Giulia Bianchi: interventi e posizioni") == "Giulia Bianchi"


def test_three_independent_stories_survive_a_documented_relation():
    quote = "Il Consiglio ha approvato la proposta."
    nodes = [
        {"id": "N1", "kind": "organization", "label": "Consiglio", "source_ids": ["S1"]},
        {"id": "N2", "kind": "proposal", "label": "proposta", "source_ids": ["S1"]},
    ]
    edges = [{"from_id": "N1", "to_id": "N2", "kind": "documented", "label": "ha approvato",
              "source_ids": ["S1"], "evidence": [{"source_id": "S1", "quote": quote}]}]
    for index in range(3):
        hub, detail = f"E{index}", f"D{index}"
        nodes.extend([
            {"id": hub, "kind": "event", "label": f"Vicenda numero {index}", "source_ids": ["S1"]},
            {"id": detail, "kind": "concept", "label": f"Sviluppo documentato numero {index}", "source_ids": ["S1"]},
        ])
        edges.append({"from_id": hub, "to_id": detail,
                      "kind": "contextual", "label": "riporta", "source_ids": ["S1"],
                      "context_scope": "same_verified_article",
                      "evidence": [{"source_id": "S1", "quote": quote}]})
    result = story_graph({"nodes": nodes, "edges": edges}, "Attualità", limit=14)
    assert len([e for e in result["edges"] if e["kind"] == "contextual"]) == 3


def test_unrelated_semantic_hit_cannot_override_relevant_archive_passage():
    topic = "Tutela dei pescatori contro gli aumenti del gasolio"
    relevant = SimpleNamespace(
        id="fish", text="I pescatori chiedono aiuti per il gasolio delle barche.",
        metadata={"filename": "pesca.pdf"})
    unrelated = SimpleNamespace(
        id="road", text="Le imprese del trasporto chiedono contributi contro il caro carburante.",
        metadata={"filename": "strade.pdf"})
    chunks = [relevant, unrelated]
    selected = select_visual_evidence("map", Topic(topic, chunks), chunks,
                                      [{"id": "road", "distance": .1}], limit=3)
    assert [s.id for s in selected] == ["fish"]
