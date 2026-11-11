"""Date del chatbot da edizioni curate: nessuna ricerca web o chiamata reale."""

import json
from datetime import date
from unittest.mock import Mock, patch

import pytest

from edicola.rag import Source, ask_question, build_prompt, CHAT_INSTRUCTION, SYSTEM_INSTRUCTION, generate_response
from edicola.rag_context import source_editions, temporal_context, temporal_notice
from test_rag import response


TODAY = date(2026, 10, 23)
TEXT = "Il Comune prevede la conclusione dei lavori entro due anni."
SOURCE = Source("S1", "test-chunk", "a.pdf", 3, TEXT, .1)


def write_editions(root, data):
    (root / "data").mkdir(exist_ok=True)
    (root / "data/editions.json").write_text(json.dumps(data), encoding="utf-8")


@pytest.mark.parametrize("published,expected", [("2020-10-17", "2020-10-17"),
    ("2026-02-30", None), ("17/10/2026", None), ("2026-10", None), (None, None)])
def test_only_complete_valid_dates_from_existing_schema(tmp_path, published, expected):
    write_editions(tmp_path, {"a.pdf": {"publication": "Testata verificata", "date": published},
                              "unused.pdf": {"date": "2026-10-23"}})
    info = source_editions(tmp_path, [SOURCE])
    assert info == {"S1": {"publication": "Testata verificata", "publication_date": expected}}


def test_missing_or_malformed_editions_do_not_infer_dates_from_filenames(tmp_path):
    source = Source("S1", "id", "giornale-2026-10-23.pdf", 1, TEXT, .1)
    assert source_editions(tmp_path, [source])["S1"]["publication_date"] is None
    write_editions(tmp_path, ["invalid schema"])
    assert source_editions(tmp_path, [source])["S1"]["publication_date"] is None
    (tmp_path / "data/editions.json").write_text("invalid JSON")
    assert source_editions(tmp_path, [source])["S1"]["publication_date"] is None


@pytest.mark.parametrize("question", ["Ci sono novità per le case?", "Che cosa succede oggi?",
    "Quali sono gli ultimi aggiornamenti?", "Attualmente come procedono i lavori?", "Le ultime notizie?"])
def test_old_sources_cannot_confirm_current_news(question):
    info = {"S1": {"publication_date": "2020-10-17"}}
    context = temporal_context(question, info, today=TODAY)
    assert context["recency_requested"] and not context["recent_source_ids"]
    assert context["live_verification_available"] is False
    assert "2020-10-17" in temporal_notice(context)
    assert "Non posso confermare aggiornamenti attuali" in temporal_notice(context)


def test_today_requires_todays_edition_and_future_dates_are_not_recent():
    info = {"S1": {"publication_date": "2026-10-22"}, "S2": {"publication_date": "2026-10-24"}}
    now = temporal_context("Oggi ci sono aggiornamenti?", info, today=TODAY)
    assert now["recent_source_ids"] == [] and now["future_publication_source_ids"] == ["S2"]
    assert temporal_context("Ci sono novità?", info, today=TODAY)["recent_source_ids"] == ["S1"]
    info["S3"] = {"publication_date": "2026-10-23"}
    now = temporal_context("Oggi?", info, today=TODAY)
    assert now["recent_source_ids"] == ["S3"]
    assert "non costituiscono una verifica in tempo reale" in temporal_notice(now)


def test_undated_sources_are_explicit_and_historical_questions_are_not_current():
    info = {"S1": {"publication_date": None}}
    context = temporal_context("Novità?", info, today=TODAY)
    assert context["undated_source_ids"] == ["S1"]
    assert "non hanno una data" in temporal_notice(context)
    context = temporal_context("Che cosa riportava il quotidiano nel 2020?", info, today=TODAY)
    assert not context["recency_requested"] and temporal_notice(context) == ""


def test_rag_receives_dates_without_changing_retrieval_or_grounding(tmp_path):
    write_editions(tmp_path, {"a.pdf": {"publication": "Testata verificata", "date": "2020-10-17"}})
    hit = {"id": SOURCE.chunk_id, "filename": SOURCE.filename, "page": 3, "text": TEXT, "distance": .1}
    data = {"sufficient": True, "claims": [{"text": "L'articolo prevedeva la conclusione entro due anni.",
            "evidence": [{"source_id": "S1", "quote": TEXT}]}]}
    client = Mock()
    client.models.generate_content.return_value = response(data)
    question = "Ci sono novità sulla ricostruzione?"
    with patch("edicola.rag.semantic_search", return_value=[hit]) as retrieve, patch(
        "edicola.rag_context.reference_day", return_value=TODAY), patch("google.genai.Client", side_effect=AssertionError("Rete vietata")):
        result = ask_question(question, authorize_external=True, root=tmp_path, client=client)
    assert result.sufficient and result.used_source_ids == ["S1"] and result.sources == [SOURCE]
    assert "2020-10-17" in result.temporal_notice
    assert retrieve.call_args.args == (question,) and retrieve.call_args.kwargs["top_k"] == 3
    sent = client.models.generate_content.call_args.kwargs
    prompt = json.loads(sent["contents"])
    assert prompt["sources"][0]["text"] == TEXT  # Nessuna riscrittura di testi/prove.
    assert prompt["sources"][0]["publication_date"] == "2020-10-17"
    assert prompt["temporal_context"]["reference_date"] == "2026-10-23"
    assert sent["config"].system_instruction == CHAT_INSTRUCTION
    assert "previsioni" in CHAT_INSTRUCTION and "non calcolare una scadenza" in CHAT_INSTRUCTION
    client.models.generate_content.assert_called_once()


def test_shared_prompt_and_generation_defaults_remain_unchanged_for_other_products():
    prompt = build_prompt("Un dossier", [SOURCE])
    assert set(json.loads(prompt)) == {"question", "sources"}
    assert "publication_date" not in json.loads(prompt)["sources"][0]
    client = Mock()
    client.models.generate_content.return_value = response()
    generate_response(client, "unchanged-model", prompt, {})
    assert client.models.generate_content.call_args.kwargs["config"].system_instruction == SYSTEM_INSTRUCTION
