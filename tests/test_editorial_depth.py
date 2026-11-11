"""Regressioni dei prodotti editoriali: prove simulate, nessuna rete esterna."""

import json

from edicola.briefing import (
    SYSTEM_INSTRUCTION as BRIEFING_INSTRUCTION,
    briefing_schema,
    provider_briefing_schema,
    validate_briefing,
)
from edicola.context_selection import (
    COMPARISON_INSTRUCTION, EDITORIAL_DEPTH_INSTRUCTION,
)
from edicola.knowledge import (
    MAP_INSTRUCTIONS, TIMELINE_INSTRUCTIONS, SYSTEM as KNOWLEDGE_SYSTEM,
    VERSION as KNOWLEDGE_VERSION,
)
from edicola.rag import CHAT_INSTRUCTION, Source, chat_response_schema, response_schema, validate_response


def sources(count):
    return [
        Source(
            f"S{i}", f"chunk-{i}", f"giornale-{i}.pdf", 2,
            f"Il consiglio comunale ha comunicato il provvedimento numero {i} dopo la seduta ufficiale.",
            0.1,
        )
        for i in range(1, count + 1)
    ]


def claim(text, source):
    return {"text": text, "evidence": [{"source_id": source.id, "quote": source.text}]}


def test_briefing_accepts_more_than_eight_distinct_verified_news():
    original = sources(10)
    news = [
        {"title": claim(f"Provvedimento numero {i}", source),
         "summary": claim(f"Il provvedimento numero {i} è stato comunicato dal consiglio.", source)}
        for i, source in enumerate(original, 1)
    ]
    result = validate_briefing(json.dumps({"sufficient": True, "news": news}), original)
    assert result.status == "ok"
    assert len(result.sections) == 10
    assert len(set(result.used_source_ids)) == 10
    assert briefing_schema(original)["properties"]["news"]["maxItems"] == 12


def test_briefing_still_rejects_excessive_structural_output():
    original = sources(13)
    news = [{"title": claim(f"Notizia {i}", source), "summary": claim(f"Fatto {i}", source)}
            for i, source in enumerate(original, 1)]
    result = validate_briefing(json.dumps({"sufficient": True, "news": news}), original)
    assert not result.sections and result.status == "invalid_structure"


def test_chat_accepts_ten_paragraphs_with_original_evidence():
    original = sources(10)
    claims = [claim(f"Il consiglio ha comunicato il provvedimento {i}.", source)
              for i, source in enumerate(original, 1)]
    answer = validate_response(json.dumps({"sufficient": True, "claims": claims}), original)
    assert answer.sufficient
    assert len(answer.answer.split("\n\n")) == 10
    assert len(answer.used_source_ids) == 10
    assert chat_response_schema(original)["properties"]["claims"]["maxItems"] == 12
    assert response_schema(original)["properties"]["claims"]["maxItems"] == 8


def test_shared_editorial_depth_is_document_based():
    assert "antefatti" in EDITORIAL_DEPTH_INSTRUCTION
    assert "non dedurre causalità" in EDITORIAL_DEPTH_INSTRUCTION
    assert EDITORIAL_DEPTH_INSTRUCTION in BRIEFING_INSTRUCTION
    assert EDITORIAL_DEPTH_INSTRUCTION in CHAT_INSTRUCTION
    assert "numero minimo" in MAP_INSTRUCTIONS
    assert KNOWLEDGE_VERSION == "knowledge-v8"
    assert len(KNOWLEDGE_SYSTEM + MAP_INSTRUCTIONS + COMPARISON_INSTRUCTION
               + EDITORIAL_DEPTH_INSTRUCTION) < 4400
    assert len(KNOWLEDGE_SYSTEM + TIMELINE_INSTRUCTIONS + COMPARISON_INSTRUCTION
               + EDITORIAL_DEPTH_INSTRUCTION) < 3500
    assert len(CHAT_INSTRUCTION) < 4500


def test_remote_briefing_schema_is_simple_but_local_validation_stays_strict():
    original = sources(14)
    remote = provider_briefing_schema(original)
    assert "maxItems" not in remote["properties"]["news"]
    for name in ("title", "summary"):
        evidence = remote["properties"]["news"]["items"]["properties"][name]["properties"]["evidence"]
        assert "maxItems" not in evidence and "minItems" not in evidence
        assert "enum" not in evidence["items"]["properties"]["source_id"]
    assert briefing_schema(original)["properties"]["news"]["maxItems"] == 12
    bad = {"sufficient": True, "news": [{
        "title": claim("Titolo", original[0]),
        "summary": {"text": "Contenuto inventato", "evidence": [
            {"source_id": "S999", "quote": original[0].text}]},
    }]}
    assert not validate_briefing(json.dumps(bad), original).sections



def test_briefing_depth_guidance_and_cache_version():
    from edicola.briefing import STRATEGY_VERSION
    from edicola.editorial import cache_key, EditorialConfig
    from edicola.editorial_selection import Catalog

    assert STRATEGY_VERSION == "briefing-v9"
    assert len(BRIEFING_INSTRUCTION) < 3000
    assert "cinque-otto frasi" in BRIEFING_INSTRUCTION
    assert "resta breve quando il materiale" in BRIEFING_INSTRUCTION
    assert "sequenza letterale contigua" in BRIEFING_INSTRUCTION
    assert "non limitarti arbitrariamente" in BRIEFING_INSTRUCTION
    assert "Una sola notizia va bene" in BRIEFING_INSTRUCTION
    assert "non limitarti al primo PDF" in BRIEFING_INSTRUCTION
    assert "fonti non pertinenti" in BRIEFING_INSTRUCTION

    # Una versione nuova invalida le vecchie risposte brevi in cache senza
    # cancellare i prodotti storici; mantieni il limite strutturale di 12 news.
    catalog = Catalog([], {}, {"indexed": 0, "total": 0, "files": [], "partial": False})
    assert briefing_schema(sources(1))["properties"]["news"]["maxItems"] == 12
    assert cache_key("briefing", "", "model", EditorialConfig(), catalog)
