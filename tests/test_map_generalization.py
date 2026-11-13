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
    topic = "Quali aiuti sono proposti per sostenere le imprese di pesca contro il caro carburante?"
    relevant = SimpleNamespace(
        id="fish", text="Le imprese di pesca chiedono ristori per il caro carburante.",
        metadata={"filename": "pesca.pdf"})
    unrelated = SimpleNamespace(
        id="road", text="Le imprese del trasporto chiedono contributi contro il caro carburante.",
        metadata={"filename": "strade.pdf"})
    chunks = [relevant, unrelated]
    selected = select_visual_evidence("map", Topic(topic, chunks), chunks,
                                      [{"id": "road", "distance": .1}], limit=3)
    assert [s.id for s in selected] == ["fish"]


@pytest.mark.parametrize("topic,sentence,actor,verb,object_name", [
    ("Rinnovo del contratto e sindacati",
     "I sindacati hanno chiesto l'apertura di un tavolo di confronto.",
     "sindacati", "hanno chiesto", "apertura di un tavolo di confronto"),
    ("Coppa regionale della squadra",
     "La squadra ha conquistato la coppa regionale durante la finale.",
     "squadra", "ha conquistato", "coppa regionale"),
    ("Materiali innovativi in laboratorio",
     "I ricercatori del laboratorio hanno scoperto un nuovo materiale resistente.",
     "ricercatori del laboratorio", "hanno scoperto", "nuovo materiale resistente"),
    ("Parco e sostenibilità urbana",
     "Il Comune ha inaugurato il parco urbano davanti ai cittadini.",
     "Comune", "ha inaugurato", "parco urbano"),
])
def test_generic_action_relations_are_validated(topic, sentence, actor, verb, object_name):
    from edicola.map_facts import complete_salient_facts
    from edicola.knowledge_validation import validate_map
    source = Source("S1", "chunk", "quotidiano.pdf", 1, sentence, .1)
    raw = complete_salient_facts({"nodes": [], "edges": []}, [source], topic)
    checked, diagnostic = validate_map(raw, [source])
    labels = {node["id"]: node["label"] for node in checked["nodes"]}
    assert any(labels[edge["from_id"]] == actor
               and edge["label"] == verb
               and labels[edge["to_id"]] == object_name
               and edge["kind"] == "documented"
               for edge in checked["edges"]), diagnostic


@pytest.mark.parametrize("sentence", [
    "I sindacati non hanno firmato l'accordo.",
    "Il ministro ha annunciato che potrebbe essere istituito un comitato.",
    "Secondo gli osservatori, la società ha annunciato una nuova misura.",
])
def test_generic_relations_do_not_invent_negated_or_attributed_actions(sentence):
    from edicola.map_facts import complete_salient_facts
    source = Source("S1", "chunk", "quotidiano.pdf", 1, sentence, .1)
    result = complete_salient_facts({"nodes": [], "edges": []}, [source], sentence)
    assert not result["edges"]


def test_verified_article_connects_grounded_action_to_its_story():
    from edicola.map_facts import complete_salient_facts
    from edicola.knowledge_validation import validate_map
    text = "I sindacati hanno chiesto l'apertura di un tavolo di confronto sulla sanità privata."
    topic = "sindacati sanità privata confronto"
    source = Source("S1", "chunk", "giornale.pdf", 2, text, .2)
    raw = complete_salient_facts({"nodes": [], "edges": []}, [source], topic)
    accepted, _ = validate_map(raw, [source])
    complete = verified_news_relations(
        accepted, [source], {"S1": {"title": "Sindacati e sanità privata: richiesta di confronto"}}, topic)
    hub = next(node for node in complete["nodes"]
               if node.get("origin") == "verified_article_story")
    bridge = next(edge for edge in complete["edges"]
                  if edge["from_id"] == hub["id"] and edge["label"] == "documenta un'azione")
    assert bridge["source_ids"] == ["S1"]
    assert bridge["evidence"][0]["quote"] == text
    graph = story_graph(complete, topic, sources=[source])
    assert bridge in graph["edges"]


def test_initial_adverbial_does_not_hide_a_literal_relation():
    from edicola.map_facts import complete_salient_facts
    from edicola.knowledge_validation import validate_map
    sentence = (
        "Per queste ragioni, Fp Cgil ha chiesto la convocazione di un tavolo "
        "di confronto con tutte le Organizzazioni Sindacali, al fine di "
        "approfondire la proposta di riorganizzazione dell'ente."
    )
    source = Source("S1", "chunk", "giornale.pdf", 4, sentence, .2)
    raw = complete_salient_facts({"nodes": [], "edges": []}, [source],
                                 "Riorganizzazione dell'ente e tavolo sindacale")
    checked, diagnostics = validate_map(raw, [source])
    labels = {node["id"]: node["label"] for node in checked["nodes"]}
    assert any(labels[edge["from_id"]] == "Fp Cgil"
               and labels[edge["to_id"]] == "convocazione di un tavolo di confronto con tutte le Organizzazioni Sindacali"
               and edge["label"] == "ha chiesto"
               for edge in checked["edges"]), diagnostics


def test_introductory_independent_clause_cannot_be_skipped():
    from edicola.map_facts import generic_action
    assert generic_action(
        "Il Comune ha annunciato un investimento, la società ha firmato un contratto."
    ) is None or generic_action(
        "Il Comune ha annunciato un investimento, la società ha firmato un contratto."
    )[0] == "Comune"
    assert generic_action(
        "Secondo le fonti, Fp Cgil ha firmato un accordo vincolante."
    ) is None



def test_postverb_nominal_modifier_keeps_an_explicit_approval():
    from edicola.map_facts import complete_salient_facts
    from edicola.knowledge_validation import validate_map
    quote = ("«Oggi il Consiglio regionale ha approvato senza nessun voto "
             "contrario il «Piano Verde», una proposta già discussa a marzo.")
    source = Source("S1", "chunk", "giornale.pdf", 1, quote, .1)
    topic = "Consiglio regionale e Piano Verde"
    raw = complete_salient_facts({"nodes": [], "edges": []}, [source], topic)
    checked, diagnostics = validate_map(raw, [source])
    labels = {node["id"]: node["label"] for node in checked["nodes"]}
    assert any(labels[e["from_id"]] == "Consiglio regionale"
               and labels[e["to_id"]] == "Piano Verde"
               and e["label"] == "ha approvato" for e in checked["edges"]), diagnostics


def test_negated_action_does_not_become_approval():
    from edicola.map_facts import complete_salient_facts
    from edicola.knowledge_validation import validate_map
    quote = "Il Consiglio regionale non ha approvato il Piano Verde."
    source = Source("S1", "chunk", "giornale.pdf", 1, quote, .1)
    raw = complete_salient_facts({"nodes": [], "edges": []}, [source],
                                 "Consiglio regionale e Piano Verde")
    checked, _ = validate_map(raw, [source])
    assert checked["edges"] == []


def test_factual_completion_survives_full_model_node_budget():
    from edicola.map_facts import complete_verified_relations
    from edicola.map_story import story_graph
    quote = ("Il Comitato civico ha presentato una proposta di recupero "
             "del quartiere dopo una lunga assemblea.")
    source = Source("S1", "chunk", "giornale.pdf", 1, quote, .1)
    # Una risposta del modello ha già riempito il suo tetto di nodi.
    original = {"nodes": [
        {"id": f"N{i}", "label": f"Concetto verificato {i}",
         "kind": "concept", "source_ids": ["S1"]} for i in range(1, 17)],
        "edges": []}
    done = complete_verified_relations(original, [source],
                                       "Comitato civico e recupero del quartiere")
    assert len(done["nodes"]) > 16
    assert len(done["edges"]) >= 1
    assert any(e["label"] == "ha presentato" for e in done["edges"])
    graph = story_graph(done, "Comitato civico e quartiere", sources=[source])
    assert any(e["kind"] == "documented" for e in graph["edges"])
