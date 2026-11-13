"""Misure correlate tramite provenienza articolo, non correlazioni indovinate."""
from copy import deepcopy

from edicola.map_article_measures import article_measure_facts
from edicola.map_story import story_graph
from edicola.rag import Source


TITLE = "ColtivaItalia: via libera definitivo dal Senato"
START = ('Il disegno di legge "ColtivaItalia" è stato approvato dal Senato. '
         'Il provvedimento prevede uno stanziamento di oltre 1,1 miliardi di euro per l’agricoltura.')
FOLLOW = ('Sostegno al ricambio generazionale: sono previsti 150 milioni di euro. '
          'Settore olivicolo: sono previsti 300 milioni di euro per il comparto. '
          'Filiera cerealicola: sono stanziati 10 milioni di euro per il frumento.')
SOURCES = [
    Source("S1", "c1", "a.pdf", 44, START, .1),
    Source("S2", "c2", "a.pdf", 45, FOLLOW, .2),
]


def base():
    return {"nodes": [
        {"id": "N1", "kind": "proposal", "label": 'disegno di legge "ColtivaItalia"',
         "source_ids": ["S1"]},
        {"id": "N2", "kind": "organization", "label": "Senato", "source_ids": ["S1"]}],
        "edges": [
            {"from_id": "N1", "to_id": "N2", "kind": "documented",
             "label": "è stato approvato dal", "source_ids": ["S1"],
             "evidence": [{"source_id": "S1", "quote": START}]}
        ]}


def test_verified_article_continuation_yields_specific_measures_not_just_mentions():
    original = base()
    enriched = article_measure_facts(original, SOURCES,
        {"S1": {"title": TITLE, "pages": [44, 45]}},
        "ColtivaItalia: misure, protagonisti e conseguenze")
    assert original == base()
    related = [e for e in enriched["edges"] if e["kind"] == "contextual"]
    assert len(related) >= 3
    labels = [n["label"] for n in enriched["nodes"] if n["kind"] == "measure"]
    assert any("150 milioni di euro" in label for label in labels)
    assert any("300 milioni di euro" in label for label in labels)
    assert any("10 milioni di euro" in label for label in labels)
    assert all(edge["from_id"] == "N1" for edge in related)
    assert all(edge["source_ids"] and edge["context_scope"] == "same_verified_article"
               for edge in related)
    for edge in related:
        item = edge["evidence"][0]
        assert item["quote"] in next(s.text for s in SOURCES if s.id == item["source_id"])
    shown = story_graph(enriched, "ColtivaItalia", sources=SOURCES)
    assert len(shown["nodes"]) > 2
    assert len([e for e in shown["edges"] if e["kind"] == "contextual"]) >= 3


def test_no_measures_attached_without_verified_same_article_identity():
    assert article_measure_facts(base(), SOURCES, {},
        "ColtivaItalia: misure e conseguenze") == base()
    assert article_measure_facts(base(), SOURCES,
        {"S1": {"title": "Un altro disegno di legge", "pages": [44, 45]}},
        "ColtivaItalia: misure e conseguenze") == base()


def test_measures_never_cross_different_pdf_or_ambiguous_article_page():
    other = Source("S3", "c3", "another.pdf", 45,
                   "Si prevede uno stanziamento di 800 milioni di euro.", .2)
    result = article_measure_facts(base(), SOURCES + [other],
        {"S1": {"title": TITLE, "pages": [44, 45]},
         "S3": {"title": TITLE, "pages": [45]}},
        "ColtivaItalia: misure e conseguenze")
    assert all(e["source_ids"][0] != "S3" for e in result["edges"] if e["kind"] == "contextual")


def test_unrelated_topic_does_not_create_context_edges():
    assert article_measure_facts(base(), SOURCES,
        {"S1": {"title": TITLE, "pages": [44, 45]}},
        "Elezioni e partiti politici") == base()
