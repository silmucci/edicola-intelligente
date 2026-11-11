"""Copertura multi-edizione con soli oggetti RAM, senza DB, indice o rete."""

import json
import math
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from edicola.archive import IndexChunk
from edicola.briefing import BriefingDraft, SYSTEM_INSTRUCTION, fit_briefing_prompt
from edicola.context_selection import fit_context, selection_coverage
from edicola.editorial import generate_product
from edicola.editorial_selection import Catalog
from edicola.knowledge import generate_knowledge
from edicola.personalization import generate_personal_briefing, recommend
from edicola.press_review import ReviewSelection
from edicola.profiles import Profile
from edicola.rag import Source, ask_question
from edicola.search import semantic_search

ROOT = Path(__file__).parent / "__mock_corpus_context_only__"


def catalog(editions=12):
    chunks = [IndexChunk(f"c{i}", f"Il piano trasporti dell’edizione {i} prevede interventi per le scuole del territorio.",
                        {"filename": f"edizione-{i}.pdf", "pdf_sha256": f"{i:064x}", "page": 1, "position": 1})
              for i in range(editions)]
    files = [{"pdf": c.metadata["filename"], "publication": f"Testata {i}", "date": "2026-10-22",
              "indexed": 1, "total": 1} for i, c in enumerate(chunks)]
    return Catalog(chunks, {c.id: [1., 0.] for c in chunks},
                   {"indexed": len(chunks), "total": len(chunks), "partial": False, "warnings": [], "files": files})


def hits_for(value):
    return [{"id": c.id, "text": c.text, **c.metadata, "distance": .1} for c in value.chunks]


def sources_for(value):
    return [Source(f"S{i}", c.id, c.metadata["filename"], c.metadata["page"], c.text, .1)
            for i, c in enumerate(value.chunks, 1)]


def test_exact_local_search_covers_editions_excludes_far_stale_and_pending_with_one_embedding():
    value = catalog()
    pending = replace(value.chunks[0], id="pending")
    stale = replace(value.chunks[0], id="stale")
    far = replace(value.chunks[0], id="far", text="Risultato sportivo di una partita.")
    chunks = value.chunks + [pending, stale, far]
    by_id = {c.id: c for c in chunks}
    collection = Mock()
    def get(**kwargs):
        chosen = [by_id[identity] for identity in kwargs["ids"]]
        return {"ids": [c.id for c in chosen], "documents": [c.text for c in chosen],
                "metadatas": [c.chroma_metadata for c in chosen],
                "embeddings": [[.1, math.sqrt(.99)] if c.id == "far" else [1., 0.] for c in chosen]}
    collection.get.side_effect = get
    embedder = Mock()
    embedder.embed.return_value = [1., 0.]
    with patch("edicola.search.read_active_chunks", return_value=(chunks, [])), patch(
        "edicola.search.open_collection", return_value=collection), patch(
        "edicola.search.plan_index", return_value=SimpleNamespace(stale_ids=["stale"], pending=[pending])):
        result = semantic_search("trasporti", root=ROOT, authorize_external=True, embedder=embedder,
                                 corpus_wide=True, top_k=3)
    assert {r["id"] for r in result} == {c.id for c in value.chunks}
    assert len({r["filename"] for r in result}) == 12
    embedder.embed.assert_called_once()
    collection.query.assert_not_called()
    collection.upsert.assert_not_called()
    collection.delete.assert_not_called()


def test_search_filters_before_reading_vectors_and_does_not_embed_empty_selection():
    value = catalog()
    collection = Mock()
    embedder = Mock()
    embedder.embed.return_value = [1., 0.]
    selected = value.chunks[3]
    collection.get.return_value = {"ids": [selected.id], "documents": [selected.text],
                                   "metadatas": [selected.chroma_metadata], "embeddings": [[1., 0.]]}
    with patch("edicola.search.read_active_chunks", return_value=(value.chunks, [])), patch(
        "edicola.search.open_collection", return_value=collection), patch(
        "edicola.search.plan_index", return_value=SimpleNamespace(stale_ids=[], pending=[])):
        assert semantic_search("trasporti", root=ROOT, authorize_external=True, embedder=embedder,
                               corpus_wide=True, filenames={"outside.pdf"}) == []
        embedder.embed.assert_not_called()
        collection.get.assert_not_called()
        restricted = semantic_search("trasporti", root=ROOT, authorize_external=True, embedder=embedder,
            corpus_wide=True, filenames={selected.metadata["filename"]}, allowed_ids={selected.id, value.chunks[0].id})
    assert [hit["id"] for hit in restricted] == [selected.id]
    embedder.embed.assert_called_once()
    assert collection.get.call_args.kwargs["ids"] == [selected.id]


def test_budget_alternates_pdfs_keeps_whole_chunks_and_skips_large_items_without_losing_later_ones():
    sources = sources_for(catalog())
    oversized = replace(sources[0], chunk_id="large", text="x" * 30000)
    crowded = [replace(sources[0], chunk_id=f"same{i}") for i in range(20)]
    original = deepcopy(sources)
    kept, prompt = fit_context([oversized] + crowded + sources, lambda items: json.dumps([s.text for s in items]), 4000)
    assert len(prompt) <= 4000 and oversized not in kept
    assert {s.filename for s in sources} <= {s.filename for s in kept}
    assert sources == original and all(s.text == sources[0].text or s in sources for s in kept)


def test_briefing_context_has_only_included_metadata_and_hints():
    value = catalog()
    sources = sources_for(value)
    sources[0] = replace(sources[0], text="x" * 30000)
    kept, prompt = fit_briefing_prompt(sources, value.coverage, [[s.id for s in sources]], 14000)
    payload = json.loads(prompt)
    assert len(SYSTEM_INSTRUCTION) + len(prompt) <= 14000
    assert all(s.text == next(item.text for item in sources if item.id == s.id) for s in kept)
    assert {row["pdf"] for row in payload["coverage"]["files"]} == {s.filename for s in kept}
    assert "S1" not in payload["topic_hints"][0]
    report = selection_coverage(value.coverage, sources, kept)["context_selection"]
    assert report["omitted_editions"] == 1


def test_chat_has_new_corpus_retrieval_for_each_question_and_budget_beyond_five():
    value = catalog()
    with patch("edicola.rag.api_key", return_value="mock"), patch(
        "edicola.rag.semantic_search", return_value=hits_for(value)) as search, patch(
        "edicola.rag.source_editions", return_value={s.id: {} for s in sources_for(value)}), patch(
        "edicola.rag.generate_response", return_value='{"sufficient":false,"claims":[]}') as generate:
        result = ask_question("trasporti", root=ROOT, authorize_external=True, client=Mock())
        ask_question("E le scuole?", root=ROOT, authorize_external=True, client=Mock(),
                     conversation=[{"role": "assistant", "content": "Vecchia risposta non probante."}])
    assert len(result.sources) == 12
    assert search.call_count == generate.call_count == 2
    assert all(call.kwargs["corpus_wide"] for call in search.call_args_list)
    assert len(json.loads(generate.call_args_list[0].args[2])["sources"]) == 12


@pytest.mark.parametrize("kind", ["timeline", "map"])
def test_visual_products_consider_more_than_five_editions_without_writing_empty_results(kind):
    value = catalog()
    raw = '{"events":[]}' if kind == "timeline" else '{"nodes":[],"edges":[]}'
    with patch("edicola.knowledge.api_key", return_value="mock"), patch(
        "edicola.knowledge.read_catalog", return_value=value), patch(
        "edicola.knowledge.semantic_search", return_value=hits_for(value)) as search, patch(
        "edicola.knowledge.generate_data", return_value=raw) as generate, patch(
        "edicola.knowledge.tempfile.NamedTemporaryFile", side_effect=AssertionError("Scrittura vietata")):
        result = generate_knowledge(kind, "trasporti", root=ROOT, authorize_external=True, client=Mock())
    assert len(result.sources) == 12 and result.coverage["context_selection"]["included_editions"] == 12
    assert search.call_args.kwargs["corpus_wide"]
    generate.assert_called_once()


def test_briefing_uses_filtered_editions_without_eight_source_cap_or_query_embedding():
    value = catalog(14)
    draft = BriefingDraft(sections=[{"heading": "Titolo [S1]", "text": "Notizia [S1]"}], used_source_ids=["S1"])
    selected = tuple(c.metadata["filename"] for c in value.chunks[:12])
    with patch("edicola.editorial.api_key", return_value="mock"), patch(
        "edicola.editorial.read_catalog", return_value=value), patch(
        "edicola.editorial.cache_read", return_value=None), patch("edicola.editorial.cache_write"), patch(
        "edicola.editorial.semantic_search") as search, patch(
        "edicola.editorial.generate_briefing_response", return_value=draft) as generate:
        result = generate_product("briefing", root=ROOT, authorize_external=True, client=Mock(),
                                  selection=ReviewSelection(keyword="trasporti", filenames=selected))
    assert {s.filename for s in result.sources} == set(selected)
    generate.assert_called_once()
    search.assert_not_called()


def test_personal_briefing_covers_all_relevant_editions_without_sending_profile_identity():
    value = catalog(14)
    profile = Profile(user_id="identity-never-sent", interests=["trasporti"])
    store = Mock(assert_owner=Mock())
    store.get_briefing.return_value = None
    draft = BriefingDraft(sections=[{"heading": "Titolo [S1]", "text": "Notizia [S1]"}], used_source_ids=["S1"])
    with patch("edicola.personalization.api_key", return_value="mock"), patch(
        "edicola.personalization.generate_briefing_response", return_value=draft) as generate:
        _, result = generate_personal_briefing(ROOT, profile, catalog=value, authorize_external=True, client=Mock(), store=store)
    assert len(result.sources) == 14
    assert profile.user_id not in generate.call_args.args[2]
    generate.assert_called_once()
    store.save_briefing.assert_called_once()


def test_budget_failure_does_not_claim_sources_were_included_or_call_generation():
    from edicola.design import product_notice
    value = catalog()
    value.chunks = [replace(chunk, text=chunk.text * 400) for chunk in value.chunks]
    with patch("edicola.editorial.api_key", return_value="mock"), patch(
        "edicola.editorial.read_catalog", return_value=value), patch(
        "edicola.editorial.cache_read", return_value=None), patch("edicola.editorial.cache_write") as write, patch(
        "edicola.editorial.generate_briefing_response") as generate:
        result = generate_product("briefing", root=ROOT, authorize_external=True, client=Mock())
    assert result.sources == [] and result.diagnostics["status"] == "prompt_budget_exceeded"
    assert "informazioni sufficienti" in product_notice(result)
    generate.assert_not_called()
    write.assert_not_called()


def test_identical_articles_in_different_pdfs_and_opposite_wording_are_not_deduplicated():
    value = catalog(2)
    value.chunks[1] = replace(value.chunks[1], text=value.chunks[0].text)
    opposite = replace(value.chunks[0], id="opposite", text=value.chunks[0].text.replace("prevede", "non prevede"))
    value.chunks.append(opposite)
    profile = Profile(interests=["trasporti"])
    assert len(recommend(value, profile, limit=100)) == 3


def test_chat_history_accepts_wider_context_without_changing_serialized_format():
    from dataclasses import asdict
    from edicola.chat_data import decode_result
    from edicola.rag import RagResult
    result = RagResult("Risposta [S1]", sources_for(catalog()), ["S1"], True)
    data = asdict(result)
    answer = data.pop("answer")
    assert decode_result(answer, {"result": data}) == result
