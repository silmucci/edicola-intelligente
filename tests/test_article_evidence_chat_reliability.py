"""Fonti articolo, Briefing e salvataggi chat: test offline, nessuna API reale."""
import json
from dataclasses import asdict
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest

from edicola.article_evidence import (verified_article, clean_source_articles,
                                     duplicate_article_hit)
from edicola.briefing import build_briefing_prompt, validate_briefing
from edicola.chat_data import decode_result
from edicola.personal_store import PersonalStoreError
from edicola.rag import RagResult, Source, ask_question, build_prompt
from edicola import chat_sessions as sessions


TEXT = "Il consiglio comunale ha approvato il progetto dopo la discussione in aula."


def article(title="Consiglio approva progetto"):
    return {"article_title_verified": True, "article_title": title,
            "article_pages_json": "[2,3]", "article_id": "a" * 64}


def test_only_verified_article_titles_enter_evidence():
    valid = verified_article(article("Approvazione del nuovo progetto"))
    assert valid == {"title": "Approvazione del nuovo progetto", "pages": [2, 3]}
    assert verified_article({**article(), "article_title_verified": False}) is None
    assert verified_article({"article_title": "Titolo inventato"}) is None
    assert verified_article({**article(), "article_title": "  "}) is None
    assert clean_source_articles({"S1": valid}, {"S1"}) == {"S1": valid}
    with pytest.raises(ValueError):
        clean_source_articles({"S2": valid}, {"S1"})
    with pytest.raises(ValueError):
        clean_source_articles({"S1": {"title": "Titolo verificato", "pages": [0]}}, {"S1"})


def test_article_prompt_cites_text_not_headline_as_independent_evidence():
    sources = [Source("S1", "chunk1", "quotidiano.pdf", 2, TEXT, .1)]
    title = "Consiglio approva nuovo progetto"
    details = {"S1": {"title": title, "pages": [2, 3]}}
    prompt = json.loads(build_prompt("Cosa ha approvato?", sources, articles=details))
    assert prompt["sources"][0]["article_title"] == title
    assert prompt["sources"][0]["article_pages"] == [2, 3]
    assert prompt["sources"][0]["text"] == TEXT
    briefing = json.loads(build_briefing_prompt(sources,
        {"files": [{"pdf": "quotidiano.pdf"}]}, [], articles=details))
    assert briefing["sources"][0]["article_title"] == title
    assert briefing["sources"][0]["text"] == TEXT


def test_rag_uses_verified_titles_dedupes_identical_article_chunks_without_api(tmp_path):
    hits = [
        {"id": "chunk1", "filename": "quotidiano.pdf", "page": 2,
         "text": TEXT, "distance": .1, "pdf_sha256": "a"*64, **article("Consiglio approva nuovo progetto")},
        {"id": "chunk2", "filename": "quotidiano.pdf", "page": 2,
         "text": TEXT, "distance": .2, "pdf_sha256": "a"*64, **article("Consiglio approva nuovo progetto")},
    ]
    reply = json.dumps({"sufficient": True, "claims": [{
        "text": "Il consiglio ha approvato il progetto.",
        "evidence": [{"source_id": "S1", "quote": TEXT}]}]})
    client = Mock()
    with patch("edicola.rag.semantic_search", return_value=hits), patch(
        "edicola.rag.generate_response", return_value=reply
    ) as generate:
        result = ask_question("Progetto approvato?", root=tmp_path, client=client,
                              authorize_external=True)
    assert result.sufficient and len(result.sources) == 1
    assert result.source_articles["S1"]["title"] == "Consiglio approva nuovo progetto"
    prompt = json.loads(generate.call_args.args[2])
    assert len(prompt["sources"]) == 1
    assert prompt["sources"][0]["article_pages"] == [2, 3]
    assert client.models.generate_content.call_count == 0
    assert decode_result(result.answer, {"result": {
        key: value for key, value in asdict(result).items() if key != "answer"
    }}) == result
    assert not duplicate_article_hit(
        {"article_id": "a", "text": "una notizia davvero diversa"},
        [{"article_id": "a", "text": TEXT}]
    )


def test_briefing_merges_reworded_repeat_without_hiding_new_numbers():
    sources = [Source("S1", "chunk1", "quotidiano.pdf", 2, TEXT, .1)]
    def claim(text):
        return {"text": text, "evidence": [{"source_id": "S1", "quote": TEXT}]}
    title = "Il consiglio comunale approva un nuovo progetto importante"
    summary = ("Il consiglio comunale ha approvato oggi il nuovo progetto dopo "
               "una discussione approfondita in aula con tutti i rappresentanti presenti")
    first = {"title": claim(title), "summary": claim(summary)}
    duplicate = {"title": claim(title + " "), "summary": claim(summary + ".")}
    changed = {"title": claim(title + " 2028"), "summary": claim(summary + " nel 2028")}
    result = validate_briefing(json.dumps(
        {"sufficient": True, "news": [first, duplicate, changed]}
    ), sources)
    assert result.status == "ok" and len(result.sections) == 2
    assert result.diagnostics["duplicates_removed"] == 1


def test_failed_save_retry_uses_original_chat_and_no_model():
    original_id, other_id, turn_id = str(uuid4()), str(uuid4()), str(uuid4())
    turns = [{"id": turn_id, "question": "Qual è la notizia?", "result": None,
              "error": "Servizio non disponibile", "save_error": True}]
    original = {"id": original_id, "saved": True, "turns": turns}
    other = {"id": other_id, "saved": False, "turns": []}
    state = {"rag_chats": {original_id: original, other_id: other},
             "rag_active_id": other_id}
    backend = Mock()
    with patch.object(sessions.st, "session_state", state), patch(
        "edicola.chat_sessions.store", return_value=backend
    ):
        assert sessions.retry_saved_turn(original_id, turn_id) is True
        backend.append_turn.assert_called_once_with(original_id, turns[0])
        assert not turns[0].get("save_error")
        assert state["rag_active_id"] == other_id
        with pytest.raises(PersonalStoreError):
            sessions.retry_saved_turn(other_id, turn_id)


def test_failed_save_is_reported_then_retried_idempotently():
    cid, tid = str(uuid4()), str(uuid4())
    turn = {"id": tid, "question": "Domanda", "result": None, "error": "Interrotta",
            "save_error": True}
    original = {"id": cid, "saved": True, "turns": [turn]}
    state = {"rag_chats": {cid: original}}
    backend = Mock()
    backend.append_turn.side_effect = [PersonalStoreError("temporary"), None]
    with patch.object(sessions.st, "session_state", state), patch(
        "edicola.chat_sessions.store", return_value=backend
    ):
        assert sessions.retry_unsaved() == {"saved": 0, "remaining": 1}
        assert turn["save_error"] is True
        assert sessions.retry_unsaved() == {"saved": 1, "remaining": 0}
    assert backend.append_turn.call_count == 2
