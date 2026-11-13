"""Copertura trasversale delle Mappe giornalistiche per diverse rubriche.

Le prove sono fittizie e descrivono la forma delle notizie, non asserzioni
su eventi reali. Non dipendono da un singolo nome di legge.
"""
import pytest

from edicola.map_news_events import verified_news_relations, same_paragraph_relations
from edicola.map_headline_facts import reported_headline_facts
from edicola.map_story import story_graph
from edicola.map_retrieval import request_focus
from edicola.rag import Source


@pytest.mark.parametrize("topic,title,body", [
    (
        "Sicurezza sul lavoro: incidenti, morti bianche, istituzioni e interventi di prevenzione",
        "Morti sul lavoro: 823 vittime in Italia, Abruzzo in zona bianca",
        "Nei primi nove mesi dell'anno sono state registrate 823 vittime sul lavoro. "
        "Il rapporto registra un aumento degli incidenti nei luoghi di lavoro.",
    ),
    (
        "Ritorno del nucleare in Italia: Governo, Senato, provvedimenti e tecnologie previste",
        "Ritorno del nucleare: il Senato approva il disegno di legge",
        "Il Senato ha approvato il disegno di legge sul ritorno del nucleare. "
        "Il provvedimento prevede nuove tecnologie per la produzione di energia nucleare.",
    ),
    (
        "Rinnovo del contratto della sanità privata: sindacati, Ministero del Lavoro, trattative e conseguenze",
        "Sanità privata: fallito tentativo di conciliazione sui contratti",
        "È fallito il tentativo di conciliazione per il rinnovo del contratto della sanità privata. "
        "I sindacati annunciano una mobilitazione per il contratto della sanità privata.",
    ),
    (
        "Bilancio del Comune dell'Aquila: Consiglio comunale, maggioranza, opposizione e decisioni",
        "Bilancio del Comune dell'Aquila: salta il voto in Consiglio",
        "La votazione sul bilancio del Comune dell'Aquila è stata rinviata per mancanza del numero legale. "
        "Il Consiglio comunale discute nuovamente il bilancio consolidato.",
    ),
])
def test_verified_newspaper_issues_create_sourced_maps_without_specific_law(topic, title, body):
    source = Source("S1", "chunk1", "giornale.pdf", 7, body, .08)
    raw = {"nodes": [], "edges": []}
    enriched = verified_news_relations(raw, [source], {"S1": {"title": title, "pages": [7]}}, topic)
    assert raw == {"nodes": [], "edges": []}
    graph = story_graph(enriched, topic, sources=[source])
    assert graph["nodes"] and graph["edges"], topic
    assert {edge["kind"] for edge in graph["edges"]} == {"contextual"}
    assert all(edge["context_scope"] == "same_verified_article" for edge in graph["edges"])
    assert any(node["kind"] == "event" for node in graph["nodes"])
    for edge in graph["edges"]:
        assert edge["source_ids"] == ["S1"]
        assert edge["evidence"][0]["quote"] in source.text
        assert "causato da" not in edge["label"].casefold()


@pytest.mark.parametrize("topic", [
    "Sicurezza sul lavoro: incidenti, morti bianche, istituzioni e interventi di prevenzione",
    "Rinnovo del contratto della sanità privata: sindacati, Ministero del Lavoro, trattative e conseguenze",
    "Bilancio del Comune dell'Aquila: Consiglio comunale, maggioranza, opposizione e decisioni",
])
def test_broad_topics_are_not_mistaken_for_named_initiatives(topic):
    assert request_focus(topic) is None


def test_unverified_titles_cannot_cause_story_claims():
    source = Source("S1", "c", "a.pdf", 1,
                    "Il Governo ha presentato i dati sugli interventi.", .2)
    data = {"nodes": [], "edges": []}
    assert verified_news_relations(data, [source], {}, "interventi del Governo") == data
    assert reported_headline_facts(data, [source], {}, "interventi del Governo") == data


def test_unrelated_news_on_same_page_remains_outside_story():
    title = "Sanità privata: fallito tentativo di conciliazione"
    source = Source("S1", "c", "a.pdf", 8,
        "Il tentativo di conciliazione nella sanità privata è fallito. "
        "L'esito del confronto sul contratto della sanità privata è stato comunicato ai sindacati. "
        "Nel campionato locale il sindaco parla di calcio e sport.", .1)
    data = verified_news_relations({"nodes": [], "edges": []},
                                   [source], {"S1": {"title": title}},
                                   "sanità privata: sindacati e contratto")
    labels = [n["label"].casefold() for n in data["nodes"]]
    assert any("conciliazione" in label for label in labels)
    assert not any("calcio" in label for label in labels)


def test_same_paragraph_local_evidence_keeps_only_coherent_claims():
    original = ("Il Comune ha rinviato la votazione sul bilancio consolidato. "
                "Il Consiglio comunale discuterà nuovamente il bilancio consolidato.")
    unrelated = "Un'altra rubrica presenta eventi sportivi."
    source = Source("S1", "c", "a.pdf", 12, original + "\n\n" + unrelated, .2)
    data = same_paragraph_relations({"nodes": [], "edges": []}, [source],
                                    "Bilancio del Comune: Consiglio comunale, maggioranza")
    assert len(data["edges"]) == 1
    edge = data["edges"][0]
    assert edge["context_scope"] == "same_source_paragraph"
    assert len(edge["evidence"]) == 2
    assert all(item["quote"] in source.text for item in edge["evidence"])
    assert unrelated not in [n["label"] for n in data["nodes"]]


def test_single_unverified_source_without_two_related_facts_does_not_invent_connections():
    source = Source("S1", "c", "a.pdf", 1,
                    "La Commissione presenta il calendario.", .2)
    data = {"nodes": [], "edges": []}
    assert same_paragraph_relations(data, [source], "economia") == data


def test_multiple_articles_about_same_theme_remain_separate_without_evidence_of_relation():
    first = Source("S1", "c1", "a.pdf", 1,
        "Il ministero annuncia un intervento per i contratti. "
        "I sindacati criticano le nuove condizioni del contratto.", .1)
    second = Source("S2", "c2", "b.pdf", 2,
        "Il Comune annuncia un intervento per il lavoro. "
        "Le aziende presentano un accordo per il lavoro.", .2)
    articles = {"S1": {"title": "Lavoro e contratti: interventi del ministero"},
                "S2": {"title": "Lavoro e aziende: accordo in Comune"}}
    out = verified_news_relations({"nodes": [], "edges": []},
                                  [first, second], articles,
                                  "Lavoro: contratti, interventi e accordi")
    nodes = {n["id"]: n for n in out["nodes"]}
    assert out["edges"]
    for edge in out["edges"]:
        assert len(edge["source_ids"]) == 1
        assert edge["source_ids"][0] in nodes[edge["from_id"]]["source_ids"]
        assert edge["source_ids"][0] in nodes[edge["to_id"]]["source_ids"]
