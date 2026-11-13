"""Test della lettura editoriale del Knowledge Graph, con articoli sintetici."""
from copy import deepcopy

from edicola.map_evidence import map_excerpts, map_prompt_source
from edicola.map_facts import complete_salient_facts
from edicola.map_story import story_focus, story_graph
from edicola.knowledge_validation import validate_map
from edicola.rag import Source


def claim(label, source):
    return {"text": label, "evidence": [{"source_id": source.id, "quote": source.text}]}


def test_map_evidence_chooses_original_salient_sentences_without_rewriting():
    irrelevant = ("Una rubrica di cinema presenta nuovi spettacoli e recensioni. " * 13)
    senato = "Il Senato ha approvato il disegno di legge ColtivaItalia."
    second = "Il provvedimento prevede risorse per il settore agricolo."
    source = Source("S1", "c1", "giornale.pdf", 4, irrelevant + senato + " " + second, .1)
    original_text = source.text
    excerpts = map_excerpts(source.text, "Senato e legge per agricoltura", budget=220)
    assert excerpts and senato in excerpts
    assert all(excerpt in original_text for excerpt in excerpts)
    assert sum(map(len, excerpts)) <= 220
    payload = map_prompt_source(source, None, "Senato e legge per agricoltura", excerpt_budget=220)
    assert senato in payload["text"]
    assert len(payload["text"]) < len(source.text)
    assert source.text == original_text  # Il validatore conserva tutti i passaggi.


def test_map_extracts_proven_senate_decision_without_dependence_on_a_named_case():
    sentence = "Il Senato ha approvato il disegno di legge ColtivaItalia."
    source = Source("S1", "c1", "giornale.pdf", 4, sentence, .1)
    raw = {"nodes": [], "edges": []}
    completed = complete_salient_facts(raw, [source], "provvedimenti Senato e agricoltura")
    assert raw == {"nodes": [], "edges": []}
    names = {node["label"]["text"] for node in completed["nodes"]}
    assert "Senato" in names and "disegno di legge ColtivaItalia" in names
    checked, metrics = validate_map(completed, [source])
    assert metrics["accepted_edges"] >= 1
    assert any(edge["kind"] == "documented" and edge["label"] == "ha approvato"
               for edge in checked["edges"])
    assert all(proof["quote"] == sentence for edge in checked["edges"]
               for proof in edge["evidence"])


def test_map_preserves_explicit_person_role_and_measure_category():
    sentence = "Il ministro Rossi ha presentato il piano Trasporti."
    source = Source("S1", "c1", "giornale.pdf", 2, sentence, .1)
    raw = complete_salient_facts({"nodes": [], "edges": []}, [source], "Rossi piano Trasporti")
    kinds = {n["label"]["text"]: n["kind"] for n in raw["nodes"]}
    assert kinds["Rossi"] == "person"
    assert kinds["piano Trasporti"] == "proposal"
    checked, counts = validate_map(raw, [source])
    assert counts["accepted_edges"] == 1
    assert checked["edges"][0]["label"] == "ha presentato"


def test_passive_approval_with_an_apposition_survives_source_validation():
    sentence = ('Il disegno di legge "PonteVerde", il piano strategico per la mobilità, '
                'è stato approvato dal Senato con 76 voti favorevoli.')
    source = Source("S1", "c1", "giornale.pdf", 44, sentence, .1)
    raw = complete_salient_facts({"nodes": [], "edges": []}, [source],
                                 "PonteVerde: approvazione e misure")
    labels = {node["label"]["text"] for node in raw["nodes"]}
    assert 'disegno di legge "PonteVerde"' in labels
    assert "Senato" in labels
    checked, metrics = validate_map(raw, [source])
    assert metrics["accepted_edges"] == 1
    edge = checked["edges"][0]
    assert edge["label"] == "è stato approvato dal"
    assert edge["evidence"][0]["quote"] == sentence
    by_id = {node["id"]: node["label"] for node in checked["nodes"]}
    assert by_id[edge["from_id"]] == 'disegno di legge "PonteVerde"'
    assert by_id[edge["to_id"]] == "Senato"


def test_map_does_not_invent_a_decision_from_a_conditional_phrase():
    sentence = "Il Senato potrebbe approvare il disegno di legge ColtivaItalia."
    source = Source("S1", "c1", "giornale.pdf", 4, sentence, .1)
    result = complete_salient_facts({"nodes": [], "edges": []}, [source], "Senato")
    assert not result["edges"]


def test_story_graph_prioritizes_facts_and_measures_over_the_article_hub():
    text = "Il Senato ha approvato il disegno di legge ColtivaItalia."
    proof = [{"source_id": "S1", "quote": text}]
    graph = {
        "nodes": [
            {"id": "A1", "kind": "article", "label": "La legge e la cronaca completa",
             "source_ids": ["S1"]},
            {"id": "N1", "kind": "organization", "label": "Senato", "source_ids": ["S1"]},
            {"id": "N2", "kind": "proposal", "label": "disegno di legge ColtivaItalia", "source_ids": ["S1"]},
            {"id": "N3", "kind": "person", "label": "Un protagonista", "source_ids": ["S1"]},
        ],
        "edges": [
            {"from_id": "A1", "to_id": "N1", "kind": "mention", "label": "menziona",
             "source_ids": ["S1"], "evidence": proof},
            {"from_id": "A1", "to_id": "N3", "kind": "mention", "label": "menziona",
             "source_ids": ["S1"], "evidence": proof},
            {"from_id": "N1", "to_id": "N2", "kind": "documented", "label": "ha approvato",
             "source_ids": ["S1"], "evidence": proof},
        ],
    }
    original = deepcopy(graph)
    selected = story_graph(graph, "Governo e legge ColtivaItalia")
    assert selected["edges"][0]["kind"] == "documented"
    assert story_focus(selected, "Governo e legge ColtivaItalia") == "N2"
    assert selected["nodes"][0]["id"] in {"N1", "N2"}
    assert all({edge["from_id"], edge["to_id"]} <=
               {node["id"] for node in selected["nodes"]} for edge in selected["edges"])
    assert original == graph


def test_story_graph_can_show_more_than_ten_grounded_nodes_and_never_make_arcs():
    nodes = [{"id": f"N{i}", "kind": "measure" if i % 2 else "organization",
              "label": f"Misura numero {i}", "source_ids": ["S1"]} for i in range(1, 17)]
    edges = [{"from_id": f"N{i}", "to_id": f"N{i+1}",
              "kind": "documented", "label": "approva", "source_ids": ["S1"],
              "evidence": []} for i in range(1, 16)]
    raw = {"nodes": nodes, "edges": edges}
    shown = story_graph(raw, "misure", limit=14)
    assert 10 < len(shown["nodes"]) <= 14
    assert shown["edges"]
    assert all(edge in edges for edge in shown["edges"])
    assert all({edge["from_id"], edge["to_id"]} <= {node["id"] for node in shown["nodes"]}
               for edge in shown["edges"])


def test_story_graph_does_not_convert_mentions_into_verified_events():
    graph = {"nodes": [
        {"id": "A1", "kind": "article", "label": "Titolo verificato", "source_ids": ["S1"]},
        {"id": "N1", "kind": "person", "label": "Rossi", "source_ids": ["S1"]},
        {"id": "N2", "kind": "organization", "label": "Comune", "source_ids": ["S1"]}],
        "edges": [{"from_id": "A1", "to_id": "N1", "kind": "mention", "label": "menziona",
                   "source_ids": ["S1"], "evidence": []},
                  {"from_id": "A1", "to_id": "N2", "kind": "mention", "label": "menziona",
                   "source_ids": ["S1"], "evidence": []}]}
    out = story_graph(graph, "Comune")
    assert out == {"nodes": [], "edges": []}  # Non chiamare mappa un elenco di menzioni.



def test_story_graph_discards_repeated_subject_links_and_keeps_verifiable_decisions():
    first = Source("S1", "a", "giornale-a.pdf", 4, "Il Senato approva la proposta.", .1)
    second = Source("S2", "b", "giornale-b.pdf", 6, "Altre notizie sul tema.", .2)
    proof = [{"source_id": "S1", "quote": first.text},
             {"source_id": "S2", "quote": second.text}]
    raw = {"nodes": [
        {"id": "N1", "kind": "organization", "label": "Senato", "source_ids": ["S1"]},
        {"id": "N2", "kind": "proposal", "label": "proposta", "source_ids": ["S1"]},
        {"id": "N3", "kind": "person", "label": "Una persona", "source_ids": ["S2"]},
        {"id": "N4", "kind": "measure", "label": "Risorse", "source_ids": ["S1", "S2"]},
        {"id": "A1", "kind": "article", "label": "Titolo", "source_ids": ["S1"]},
    ], "edges": [
        {"from_id": "N1", "to_id": "N2", "kind": "documented",
         "label": "approva", "source_ids": ["S1"], "evidence": [proof[0]]},
        *[{"from_id": a, "to_id": b, "kind": "thematic",
           "label": "associazione tematica", "topic": "stessa vicenda",
           "source_ids": ["S1", "S2"], "evidence": proof}
          for a, b in [("N1", "N4"), ("N2", "N3"), ("N2", "N4")]],
        {"from_id": "A1", "to_id": "N1", "kind": "mention", "label": "menziona",
         "source_ids": ["S1"], "evidence": [proof[0]]},
    ]}
    out = story_graph(raw, "stessa vicenda", sources=[first, second])
    assert len([e for e in out["edges"] if e["kind"] == "documented"]) == 1
    assert len([e for e in out["edges"] if e["kind"] == "thematic"]) <= 1
    assert not any(e["kind"] == "mention" for e in out["edges"])
    assert not any(n["kind"] == "article" for n in out["nodes"])
    assert all(edge in raw["edges"] for edge in out["edges"])


def test_story_graph_rejects_theme_edges_from_the_same_newspaper():
    sources = [Source("S1", "a", "giornale-a.pdf", 1, "Tema", .1),
               Source("S2", "b", "giornale-a.pdf", 2, "Tema", .2)]
    raw = {"nodes": [
        {"id": "N1", "kind": "organization", "label": "Organo", "source_ids": ["S1"]},
        {"id": "N2", "kind": "measure", "label": "Iniziativa", "source_ids": ["S2"]}],
        "edges": [{"from_id": "N1", "to_id": "N2", "kind": "thematic",
                   "label": "associazione tematica", "topic": "iniziativa",
                   "source_ids": ["S1", "S2"], "evidence": []}]}
    assert story_graph(raw, "iniziativa", sources=sources) == {"nodes": [], "edges": []}


def test_quoted_named_bill_remains_specific_when_approval_is_explicit():
    sentence = 'Il Senato ha approvato il disegno di legge «ColtivaItalia».'
    source = Source("S1", "b", "quotidiano.pdf", 4, sentence, .1)
    extracted = complete_salient_facts({"nodes": [], "edges": []}, [source],
                                       "ColtivaItalia approvazione")
    texts = {n["label"]["text"] for n in extracted["nodes"]}
    assert "disegno di legge «ColtivaItalia»" in texts
    data, counts = validate_map(extracted, [source])
    assert counts["accepted_edges"] == 1
    assert data["edges"][0]["label"] == "ha approvato"


def test_named_provision_and_exact_amount_create_validated_fact():
    sentence = "Il programma PonteVerde stanzia oltre 1,2 miliardi di euro per la mobilità pubblica."
    source = Source("S1", "b", "quotidiano.pdf", 4, sentence, .1)
    extracted = complete_salient_facts({"nodes": [], "edges": []}, [source],
                                       "PonteVerde finanziamenti mobilità")
    names = {n["label"]["text"]: n["kind"] for n in extracted["nodes"]}
    assert names["programma PonteVerde"] == "proposal"
    assert names["oltre 1,2 miliardi di euro per la mobilità pubblica"] == "measure"
    data, counts = validate_map(extracted, [source])
    assert counts["accepted_edges"] == 1
    assert data["edges"][0]["label"] == "stanzia"


def test_conditional_amount_does_not_create_a_fact():
    sentence = "Il programma PonteVerde potrebbe stanziare oltre 1,2 miliardi di euro."
    source = Source("S1", "b", "quotidiano.pdf", 4, sentence, .1)
    result = complete_salient_facts({"nodes": [], "edges": []}, [source], "PonteVerde")
    assert not result["edges"]
