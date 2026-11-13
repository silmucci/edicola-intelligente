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
    purposes = {n["id"] for n in enriched["nodes"] if n["kind"] == "concept"}
    measures = {n["id"] for n in enriched["nodes"] if n["kind"] == "measure"}
    assert purposes and len(measures) >= 3
    assert all(any(e["from_id"] == "N1" and e["to_id"] == pid for e in related)
               for pid in purposes)
    assert all(any(e["from_id"] in purposes and e["to_id"] == mid for e in related)
               for mid in measures)
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



def test_map_recovers_named_initiative_and_measures_when_model_returns_only_mentions():
    """Regression: fonte pertinente verificata, ma nessun arco LLM."""
    empty = {"nodes": [], "edges": []}
    recovered = article_measure_facts(
        empty, SOURCES, {"S1": {"title": TITLE, "pages": [44, 45]}},
        "ColtivaItalia: approvazione, protagonisti, misure previste e conseguenze")
    assert empty == {"nodes": [], "edges": []}
    provisions = [n for n in recovered["nodes"] if n["kind"] == "proposal"]
    assert len(provisions) == 1
    assert provisions[0]["label"] == 'disegno di legge "ColtivaItalia"'
    measures = [n for n in recovered["nodes"] if n["kind"] == "measure"]
    assert len(measures) >= 3
    assert all(edge["kind"] == "contextual" for edge in recovered["edges"])
    assert any(edge["from_id"] == provisions[0]["id"] for edge in recovered["edges"])
    purpose_ids = {n["id"] for n in recovered["nodes"] if n["kind"] == "concept"}
    assert purpose_ids
    assert all(any(edge["from_id"] in purpose_ids and edge["to_id"] == node["id"]
                   for edge in recovered["edges"]) for node in measures)
    shown = story_graph(recovered, "ColtivaItalia", sources=SOURCES)
    assert shown["edges"]
    assert all(edge["kind"] == "contextual" for edge in shown["edges"])


def test_map_does_not_invent_initiative_from_article_title_alone():
    """Verified headline alone cannot manufacture an unquoted proposal."""
    body = Source("S1", "c1", "a.pdf", 44,
                  "Il comparto prevede uno stanziamento di 40 milioni di euro.", .1)
    empty = {"nodes": [], "edges": []}
    assert article_measure_facts(
        empty, [body], {"S1": {"title": TITLE, "pages": [44]}},
        "ColtivaItalia: stanziamenti") == empty


def test_map_does_not_merge_two_named_initiatives_into_one_hub():
    first = Source("S1", "c1", "a.pdf", 44,
        'Il disegno di legge "ColtivaItalia" stanzia 20 milioni di euro. '
        'Il piano ColtivaItalia prevede 35 milioni di euro.', .1)
    empty = {"nodes": [], "edges": []}
    assert article_measure_facts(
        empty, [first], {"S1": {"title": TITLE, "pages": [44]}},
        "ColtivaItalia: stanziamenti") == empty



def test_purposeless_amounts_are_not_promoted_to_conceptual_nodes():
    article = Source(
        "S1", "c1", "a.pdf", 44,
        ('Il disegno di legge "ColtivaItalia" introduce nuove misure. '
         'Sono previsti 1 miliardo di euro. Sono stanziati 3 milioni di euro. '
         'Per rafforzare la filiera agricola sono previsti 150 milioni di euro.'),
        .1)
    result = article_measure_facts(
        {"nodes": [], "edges": []}, [article],
        {"S1": {"title": TITLE, "pages": [44]}},
        "ColtivaItalia: misure, stanziamenti")
    amounts = [n["label"] for n in result["nodes"] if n["kind"] == "measure"]
    assert amounts == ["150 milioni di euro"]
    assert any(n["label"] == "rafforzare la filiera agricola"
               for n in result["nodes"] if n["kind"] == "concept")
    assert len(result["edges"]) == 2


def test_same_article_grouping_does_not_merge_different_destinations():
    article = Source("S1", "c1", "a.pdf", 44,
                     ('Il disegno di legge "ColtivaItalia" prevede nuove misure. '
                      'Sostegno ai giovani: sono previsti 150 milioni di euro. '
                      'Sostegno alle cooperative: sono previsti 150 milioni di euro. '
                      'Sostegno ai giovani: sono previsti 150 milioni di euro.'), .1)
    result = article_measure_facts(
        {"nodes": [], "edges": []}, [article],
        {"S1": {"title": TITLE, "pages": [44]}},
        "ColtivaItalia: destinatari e stanziamenti")
    amounts = [n for n in result["nodes"] if n["kind"] == "measure"]
    purposes = [n for n in result["nodes"] if n["kind"] == "concept"]
    assert len(amounts) == 2 and len(purposes) == 2
    assert {n["purpose"] for n in amounts} == {"Sostegno ai giovani", "Sostegno alle cooperative"}


def test_verified_headline_reports_parliamentary_action_without_inventing_body_quote():
    from edicola.map_article_measures import verified_headline_actions
    article = Source("S1", "c1", "a.pdf", 44,
                     'Il disegno di legge "ColtivaItalia" prevede risorse.', .1)
    raw = {"nodes": [{"id": "N1", "kind": "proposal",
                      "label": 'disegno di legge "ColtivaItalia"',
                      "source_ids": ["S1"]}], "edges": []}
    headline = '"ColtivaItalia": via libera definitivo dal Senato: oltre 1,1 miliardi'
    result = verified_headline_actions(raw, [article],
                                       {"S1": {"title": headline, "pages": [44]}},
                                       "ColtivaItalia: approvazione, protagonisti")
    assert raw["edges"] == []
    assert any(n["label"] == "Senato" and n["kind"] == "organization"
               for n in result["nodes"])
    contextual = [e for e in result["edges"] if e["kind"] == "contextual"]
    assert len(contextual) == 1
    assert contextual[0]["label"] == "via libera definitivo"
    assert contextual[0]["context_scope"] == "verified_article_title"
    assert contextual[0]["evidence"] == [{"source_id": "S1", "quote": headline}]
    assert verified_headline_actions(raw, [article],
                                    {"S1": {"title": "ColtivaItalia al centro del dibattito"}},
                                    "ColtivaItalia: approvazione") == raw
