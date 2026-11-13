"""Regressioni del recupero per richiesta specifica e dei seguiti di articolo."""
from edicola.archive import IndexChunk
from edicola.map_retrieval import focused_map_seeds, request_focus
from edicola.map_evidence import map_excerpts, map_prompt_source
from edicola.rag import Source


def chunk(identifier, text, filename, page, *, article_id=None, title=None):
    metadata = {"filename": filename, "page": page}
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
    assert measure not in map_excerpts(source.text, topic, budget=220,
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
