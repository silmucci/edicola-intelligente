"""Regressioni: le Mappe devono conservare fatti notiziabili anche senza SVO.

Titoli di prova sintetici sui settori lavoro, sanità e amministrazioni.
La relazione è sempre una notizia riportata, non una causalità inventata.
"""
import pytest

from edicola.map_headline_facts import headline_parts, reported_headline_facts
from edicola.map_story import story_graph
from edicola.rag import Source


@pytest.mark.parametrize("topic,title", [
    ("Sicurezza sul lavoro: incidenti, morti bianche e prevenzione",
     "Morti sul lavoro: 823 vittime in Italia nei primi nove mesi del 2026, Abruzzo in zona bianca"),
    ("Rinnovo del contratto della sanità privata: sindacati e trattative",
     "Fallito tentativo di conciliazione nella sanità privata: nessuna risposta sui contratti"),
    ("Bilancio del Comune dell'Aquila: opposizione e decisioni",
     "Non c'è il numero legale, in Consiglio a L'Aquila salta il voto sul bilancio consolidato"),
])
def test_broad_map_without_explicit_triples_keeps_documented_headline_observations(topic, title):
    original = {"nodes": [], "edges": []}
    source = Source("S1", "chunk", "giornale.pdf", 8, title, 0.13)
    data = reported_headline_facts(original, [source],
                                   {"S1": {"title": title, "pages": [8]}}, topic)
    assert original == {"nodes": [], "edges": []}
    assert len(data["nodes"]) >= 2
    assert 1 <= len(data["edges"]) <= 2
    assert all(edge["kind"] == "contextual" and
               edge["label"] == "il titolo riporta" and
               edge["context_scope"] == "verified_article_title" and
               edge["evidence"] == [{"source_id": "S1", "quote": title}]
               for edge in data["edges"])
    visual = story_graph(data, topic, sources=[source])
    assert visual["edges"]
    assert all(e["from_id"] in {n["id"] for n in visual["nodes"]}
               and e["to_id"] in {n["id"] for n in visual["nodes"]}
               for e in visual["edges"])


def test_titled_mention_does_not_create_claim_without_a_second_fact():
    title = "Sicurezza sul lavoro e prevenzione"
    source = Source("S1", "chunk", "giornale.pdf", 8, "Notizie sul lavoro.", 0.13)
    assert headline_parts(title) == []
    assert reported_headline_facts({"nodes": [], "edges": []},
                                   [source], {"S1": {"title": title, "pages": [8]}},
                                   "Sicurezza sul lavoro")["edges"] == []


def test_unverified_titles_and_unrelated_news_cannot_be_promoted():
    source = Source("S1", "chunk", "giornale.pdf", 8, "Incidenti sul lavoro", 0.2)
    title = "Sport: successo della squadra in campionato"
    for articles in ({}, {"S1": {"title": title, "pages": [8]}}):
        assert reported_headline_facts({"nodes": [], "edges": []},
                                       [source], articles,
                                       "Sicurezza sul lavoro: prevenzione") == {
                                           "nodes": [], "edges": []}


def test_existing_fact_is_not_replaced_by_headline_observation():
    source = Source("S1", "chunk", "giornale.pdf", 8, "Il Consiglio approva il piano.", 0.2)
    data = {"nodes": [{"id": "N1", "label": "Consiglio", "kind": "organization",
                       "source_ids": ["S1"]},
                      {"id": "N2", "label": "piano", "kind": "proposal",
                       "source_ids": ["S1"]}],
            "edges": [{"from_id": "N1", "to_id": "N2", "kind": "documented",
                       "label": "approva", "source_ids": ["S1"], "evidence": [
                           {"source_id": "S1", "quote": source.text}]}]}
    title = "Bilancio comunale: approvato il nuovo piano"
    assert reported_headline_facts(data, [source],
                                   {"S1": {"title": title, "pages": [8]}},
                                   "Bilancio comunale") is data
