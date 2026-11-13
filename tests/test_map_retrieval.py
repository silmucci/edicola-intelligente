"""Regressioni del recupero per richiesta specifica e dei seguiti di articolo."""
import hashlib

from edicola.archive import IndexChunk
from edicola.map_retrieval import focused_map_seeds, request_focus
from edicola.map_evidence import map_excerpts, map_prompt_source
from edicola.rag import Source
from test_knowledge import setup_knowledge


def chunk(identifier, text, filename, page, *, article_id=None, title=None):
    metadata = {"filename": filename, "page": page,
                "pdf_sha256": hashlib.sha256(filename.encode("utf-8")).hexdigest()}
    if article_id:
        metadata["article_id"] = article_id
    if title:
        metadata["article_title"] = title
        metadata["article_title_verified"] = True
    return IndexChunk(identifier, text, metadata)


def test_focused_map_drops_lexically_similar_but_unrelated_articles():
    topic = "ColtivaItalia: approvazione, protagonisti, misure previste e conseguenze"
    story_title = "ColtivaItalia: via libera definitivo dal Senato"
    chunks = [
        chunk("a", "Il Consiglio comunale ha approvato il bilancio, previste misure.", "a.pdf", 8),
        chunk("b", 'Il disegno di legge "ColtivaItalia" è stato approvato dal Senato.', "b.pdf", 44,
              article_id="story_001", title=story_title),
        chunk("c", "Sono previsti 150 milioni di euro per giovani agricoltori.", "b.pdf", 45,
              article_id="story_001", title=story_title),
        chunk("d", "Altre misure per il bilancio locale.", "a.pdf", 7),
    ]
    selected = focused_map_seeds(topic, chunks, [{"id": "a", "distance": .09}],
                                 fallback=chunks, limit=28)
    assert request_focus(topic) == "ColtivaItalia"
    assert {c.id for c in selected} == {"b", "c"}
    assert {c.metadata["filename"] for c in selected} == {"b.pdf"}


def test_contextual_excerpts_keep_measure_from_continuation_of_verified_article():
    topic = "ColtivaItalia: approvazione, protagonisti, misure previste e conseguenze"
    other = "Nella rubrica sportiva si parla del campionato locale. " * 35
    measure = "Sono previsti 150 milioni di euro per sostenere l'agricoltura giovanile."
    source = Source("S1", "c1", "b.pdf", 45, other + " " + measure, 0.25)
    chunks = map_excerpts(source.text, topic, budget=220,
                          verified_article_title="ColtivaItalia: via libera del Senato")
    assert measure in chunks
    assert all(p in source.text for p in chunks)
    # Una frase esplicitamente pertinente può essere selezionata anche senza
    # metadati articolo: la decisione di ammettere una fonte spetta al retrieval.
    assert measure in map_excerpts(source.text, topic, budget=220,
                                   verified_article_title="Bilancio regionale")
    payload = map_prompt_source(source, {"title": "ColtivaItalia: via libera del Senato", "pages": [44, 45]},
                                topic, excerpt_budget=220)
    assert measure in payload["text"]
    assert source.text.startswith(other)


def test_focused_map_does_not_force_unrelated_long_or_generic_subjects():
    assert request_focus("Governo, Senato e provvedimenti per l'agricoltura") is None
    assert request_focus("Agricoltura: notizie e protagonisti") is None
    assert request_focus("Lavoro e occupazione") is None


def test_focused_map_falls_back_when_specific_subject_is_absent():
    available = [chunk("a", "Il Governo presenta le novità sul settore.", "a.pdf", 1)]
    assert focused_map_seeds("ProgettoInesistente: decisioni", available, [], fallback=available) == available



def test_focus_includes_declared_article_continuation_even_if_name_not_repeated():
    title = "PonteVerde: via libera al piano"
    first = chunk("start", 'Il progetto "PonteVerde" viene esaminato.',
                  "a.pdf", 7, title=title)
    first.metadata["article_pages_json"] = "[7,8]"
    continuation = chunk("continued", "Sono previsti finanziamenti per i territori.",
                         "a.pdf", 8)
    different = chunk("other", "Il bilancio comunale è stato approvato.",
                      "a.pdf", 8, article_id="unrelated_article_2026")
    outside = chunk("outside", "Altri stanziamenti per l'economia.",
                    "a.pdf", 9)
    result = focused_map_seeds("PonteVerde: misure e conseguenze",
                               [first, continuation, different, outside],
                               [], fallback=[first])
    assert {c.id for c in result} == {"start", "continued"}


def test_undeclared_next_page_not_assumed_to_be_same_article():
    first = chunk("start", "Il progetto PonteVerde è stato presentato.",
                  "a.pdf", 7, title="PonteVerde: piano")
    unknown = chunk("other", "Un'altra notizia sullo sport.",
                    "a.pdf", 8)
    result = focused_map_seeds("PonteVerde: novità", [first, unknown], [],
                               fallback=[first])
    assert [c.id for c in result] == ["start"]



def test_end_to_end_map_uses_named_article_not_unrelated_lexical_matches(setup_knowledge):
    import json
    from types import SimpleNamespace
    from google.genai import types
    from edicola.map_story import story_graph
    from edicola.knowledge import generate_knowledge

    root, catalog, client, _read, search = setup_knowledge
    title = "PonteVerde: via libera definitivo dal Senato"
    approval = ('Il disegno di legge "PonteVerde", il piano strategico per il territorio, '
                'è stato approvato dal Senato con 76 voti.')
    measures = ('Sostegno ai giovani: sono previsti 150 milioni di euro. '
                'Settore olivicolo: sono stanziati 300 milioni di euro.')
    irrelevant = 'Il Consiglio comunale approva il bilancio con nuove misure e risorse.'
    others = 'L’opposizione presenta proposte sulla finanza locale.'
    first = chunk("wrong_a", irrelevant, "a.pdf", 18)
    lead = chunk("lead", approval, "b.pdf", 44, title=title)
    lead.metadata["article_pages_json"] = "[44, 45]"
    continuation = chunk("continue", measures, "b.pdf", 45)
    extra = chunk("wrong_b", others, "a.pdf", 13)
    catalog.chunks = [first, lead, continuation, extra]
    catalog.coverage["files"] = [
        {"pdf": "a.pdf", "publication": "Testata A", "date": "2026-10-31",
         "indexed": 2, "total": 2},
        {"pdf": "b.pdf", "publication": "Testata B", "date": "2026-11-05",
         "indexed": 2, "total": 2},
    ]
    search.return_value = [{"id": "wrong_a", "distance": .02},
                           {"id": "lead", "distance": .4}]
    client.models.generate_content.side_effect = None
    client.models.generate_content.return_value = SimpleNamespace(
        text=json.dumps({"nodes": [], "edges": []}),
        candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)])
    topic = "PonteVerde: approvazione, protagonisti, misure previste e conseguenze"
    result = generate_knowledge("map", topic, authorize_external=True,
                                root=root, client=client, cache_enabled=False)
    assert {s.filename for s in result.sources} == {"b.pdf"}
    assert {s.page for s in result.sources} == {44, 45}
    assert any(edge["kind"] == "documented" for edge in result.data["edges"])
    assert any(edge["kind"] == "contextual" for edge in result.data["edges"])
    visual = story_graph(result.data, topic, sources=result.sources)
    assert len(visual["nodes"]) >= 3
    assert any("150 milioni" in n["label"] for n in visual["nodes"])
    assert all("bilancio" not in n["label"].casefold() for n in visual["nodes"])
