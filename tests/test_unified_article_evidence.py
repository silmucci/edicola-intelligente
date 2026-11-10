"""Condivisione dei metadati verificati fra prodotti senza chiamate Gemini reali."""
import json
from dataclasses import asdict, replace
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from edicola.article_evidence import evidence_source_record, verified_article, source_articles
from edicola.knowledge import generate_knowledge
from edicola.podcast_draft import (
    TOPIC_VERSION, TOPIC_INSTRUCTION, digest, load_draft, script_from_response,
)
from edicola.standalone_podcast import draft_context, list_episodes
from test_knowledge import setup_knowledge
from test_standalone_podcast import standalone, generate


TITLE = "Consiglio comunale approva il piano trasporti"


def verified(title=TITLE):
    return {
        "article_title_verified": True,
        "article_title": title,
        "article_pages_json": "[2,3]",
        "article_id": "e" * 64,
    }


def test_same_verified_metadata_format_for_all_products():
    from edicola.rag import Source, build_prompt
    from edicola.briefing import build_briefing_prompt
    source = Source("S1", "c1", "a.pdf", 2, "Il Comune approva il piano trasporti.", 0.1)
    details = {"S1": verified_article(verified())}
    assert source_articles([source], {"c1": verified()}) == details
    record = evidence_source_record(source, details["S1"], include_chunk=True)
    assert record["text"] == source.text and record["chunk_id"] == "c1"
    assert record["article_title"] == TITLE and record["article_pages"] == [2, 3]
    assert json.loads(build_prompt("Piano?", [source], articles=details))["sources"][0] == {
        key: value for key, value in record.items() if key != "chunk_id"
    }
    coverage = {"files": [{"pdf": "a.pdf", "date": "2026-10-17"}]}
    assert json.loads(build_briefing_prompt([source], coverage, [], articles=details))["sources"][0] == {
        key: value for key, value in record.items() if key != "chunk_id"
    }
    without_title = source_articles([source], {"c1": {**verified(), "article_title_verified": False}})
    assert without_title == {}
    assert "article_title" not in evidence_source_record(source)


@pytest.mark.parametrize("kind", ["map", "timeline"])
def test_knowledge_article_titles_reach_prompt_and_are_cached_with_sources(setup_knowledge, kind):
    root, catalog, client, _, _ = setup_knowledge
    original = catalog.chunks[0]
    catalog.chunks[0] = replace(original, metadata={**original.metadata, **verified()})
    initial = generate_knowledge(kind, "Trasporti", authorize_external=True, root=root, client=client)
    assert initial.source_articles["S1"]["title"] == TITLE
    assert initial.source_articles["S1"]["pages"] == [2, 3]
    prompt = json.loads(client.models.generate_content.call_args.kwargs["contents"])
    assert prompt["sources"][0]["article_title"] == TITLE
    assert prompt["sources"][0]["article_pages"] == [2, 3]
    assert prompt["sources"][0]["text"] == original.text
    assert "article_title" not in prompt["sources"][1]
    repeated = generate_knowledge(kind, "Trasporti", authorize_external=True, root=root, client=client)
    assert repeated.from_cache and repeated.source_articles == initial.source_articles
    assert client.models.generate_content.call_count == 1
    catalog.chunks[0] = replace(original, metadata={
        **original.metadata, **verified("Il nuovo piano di mobilità urbana")
    })
    changed = generate_knowledge(kind, "Trasporti", authorize_external=True, root=root, client=client)
    assert changed.source_articles["S1"]["title"] == "Il nuovo piano di mobilità urbana"
    assert client.models.generate_content.call_count == 2


def test_podcast_uses_article_metadata_and_invalidates_only_new_draft_cache(standalone):
    old = standalone.catalog.chunks[0]
    standalone.catalog.chunks[0] = replace(old, metadata={**old.metadata, **verified()})
    episode = generate(standalone)
    prompt = json.loads(standalone.text.models.generate_content.call_args.kwargs["contents"])
    assert prompt["sources"][0]["article_title"] == TITLE
    assert prompt["sources"][0]["text"] == old.text
    assert episode.source_articles["S1"]["title"] == TITLE
    assert list_episodes(standalone.root)[0].source_articles == episode.source_articles
    cached = generate(standalone)
    assert cached.from_cache and standalone.text.models.generate_content.call_count == 1
    standalone.catalog.chunks[0] = replace(old, metadata={
        **old.metadata, **verified("Nuovo titolo verificato delle scuole")
    })
    updated = generate(standalone)
    assert updated.key != episode.key
    assert standalone.text.models.generate_content.call_count == 2
    # Le vecchie registrazioni restano consultabili senza rigenerazione.
    assert len(list_episodes(standalone.root)) == 2


def test_podcast_legacy_v2_draft_remains_loadable_with_original_audio_topic(standalone):
    from edicola.rag import Source
    from edicola.podcast_draft import normalize_topic
    topic = normalize_topic("Trasporti")
    src = Source("S1", "old-chunk", "old.pdf", 2,
                 "Il Comune di Roma ha approvato il piano trasporti.", 0.0)
    def claim(text):
        return {"text": text, "evidence": [{"source_id": "S1", "quote": src.text}]}
    raw = json.dumps({"sufficient": True, "news": [{
        "title": claim("Un piano di trasporti a Roma"), "summary": claim(src.text)
    }]})
    coverage = {"files": [{"pdf": "old.pdf", "date": "2026-10-17"}]}
    script = script_from_response(raw, [src], coverage, topic)
    model = "model-old"
    config = {"query_embedding": ["old", "format"]}
    corpus = "old-corpus"
    key = digest([TOPIC_VERSION, corpus, model, config, TOPIC_INSTRUCTION, topic])
    path = standalone.root / "data/podcast_cache/standalone/scripts" / (key + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "key": key, "version": TOPIC_VERSION, "source_identity": corpus,
        "model": model, "config": config, "title": "Notizie su trasporti",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "raw": raw, "sources": [asdict(src)], "coverage": coverage,
        "script": asdict(script), "topic": topic,
    }, ensure_ascii=False), encoding="utf-8")
    old = load_draft(standalone.root, key)
    assert old.strategy == TOPIC_VERSION and old.topic == topic
    assert old.source_articles == {} and old.script == script
    assert draft_context(old)["topic"] == topic
