import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation import llm_relevance_judge as judge


def make_inputs(tmp_path, existing_records=None, answer_records=None, count=4):
    run = {
        "mode": "rag",
        "top_k": 1,
        "records": [
            {
                "question_id": f"GT-{index:03}",
                "repeat": 1,
                "retrieval_status": "ok",
                "status": "ok",
                "raw_response": "Risposta sintetica.",
                "retrieved": [{
                    "id": f"chunk-{index}",
                    "text": "Il Comune approva il piano dei trasporti.",
                    "distance": 0.1,
                    "filename": "edizione.pdf",
                    "page": 1,
                }],
            }
            for index in range(1, count + 1)
        ],
    }
    dataset = {
        "questions": [
            {
                "id": f"GT-{index:03}",
                "question": "Quale piano è approvato?",
                "reference_answer": "Il piano dei trasporti.",
                "expected_points": ["Piano dei trasporti"],
            }
            for index in range(1, count + 1)
        ]
    }
    snapshot = {"snapshot_id": "snapshot-test"}
    paths = {
        "run": tmp_path / "run.json",
        "dataset": tmp_path / "dataset.json",
        "snapshot": tmp_path / "snapshot.json",
        "out": tmp_path / "results.json",
    }
    for key, data in (("run", run), ("dataset", dataset), ("snapshot", snapshot)):
        paths[key].write_text(json.dumps(data), encoding="utf-8")

    results = {
        "schema_version": 1,
        "origin": "ai_silver",
        "run_sha256": judge.digest(run),
        "snapshot_id": "snapshot-test",
        "model": "openai/gpt-oss-120b",
        "provider": "groq",
        "records": existing_records or {},
        "answer_records": answer_records or {},
    }
    paths["out"].write_text(json.dumps(results), encoding="utf-8")
    return paths, results


def invoke_main(monkeypatch, paths, fake_client, *extra_args):
    args = [
        "llm_relevance_judge.py",
        "--run", str(paths["run"]),
        "--dataset", str(paths["dataset"]),
        "--snapshot", str(paths["snapshot"]),
        "--out", str(paths["out"]),
        "--autorizza-api",
        *extra_args,
    ]
    monkeypatch.setattr(judge.sys, "argv", args)
    with (
        patch("edicola.evaluation_data.validate_dataset"),
        patch("edicola.evaluation_data.validate_snapshot", return_value={}),
        patch("edicola.evaluation_metrics.score_run"),
        patch.object(judge, "GroqJudge", return_value=fake_client),
        patch.object(judge, "export_results"),
    ):
        judge.main()


class FakeGroqJudge:
    def __init__(self, response=None, failure=None):
        self.calls = []
        self.response = response
        self.failure = failure

    def generate(self, _instruction, prompt, *_args):
        request = json.loads(prompt)
        self.calls.append(request["question_id"])
        if self.failure is not None and len(self.calls) == self.failure[0]:
            raise self.failure[1]
        chunk_id = request["chunks"][0]["chunk_id"]
        judgment = self.response or {
            "judgments": [{
                "chunk_id": chunk_id,
                "label": "R",
                "quote": "Il Comune approva il piano dei trasporti.",
                "reason": "Il passaggio contiene la prova richiesta.",
            }]
        }
        return json.dumps(judgment)

    def close(self):
        pass


def test_solo_mancanti_preserves_existing_statuses_and_judges_only_absent(tmp_path, monkeypatch):
    records = {
        "GT-001#1": {"status": "judged", "judgments": [{"chunk_id": "keep"}]},
        "GT-002#1": {"status": "judge_error", "error_type": "ValueError"},
        "GT-003#1": {"status": "retrieval_missing", "judgments": []},
    }
    paths, _ = make_inputs(tmp_path, existing_records=records)
    client = FakeGroqJudge()

    invoke_main(monkeypatch, paths, client, "--solo-mancanti")

    saved = judge.read_json(paths["out"])
    assert client.calls == ["GT-004"]
    assert saved["records"]["GT-001#1"] == records["GT-001#1"]
    assert saved["records"]["GT-002#1"] == records["GT-002#1"]
    assert saved["records"]["GT-003#1"] == records["GT-003#1"]
    assert saved["records"]["GT-004#1"]["status"] == "judged"


def test_normal_run_retries_errors_but_never_repeats_judged(tmp_path, monkeypatch):
    records = {
        "GT-001#1": {"status": "judged", "judgments": [{"chunk_id": "keep"}]},
        "GT-002#1": {"status": "judge_error", "error_type": "ValueError"},
    }
    paths, _ = make_inputs(tmp_path, existing_records=records, count=3)
    client = FakeGroqJudge()

    invoke_main(monkeypatch, paths, client)

    saved = judge.read_json(paths["out"])
    assert client.calls == ["GT-002", "GT-003"]
    assert saved["records"]["GT-001#1"] == records["GT-001#1"]
    assert saved["records"]["GT-002#1"]["status"] == "judged"


def test_solo_mancanti_skips_no_valid_answer_and_answer_judge_error(tmp_path, monkeypatch):
    answer_records = {
        "GT-001#1": {"status": "no_valid_answer", "state": "model_abstention"},
        "GT-002#1": {"status": "judge_error", "error_type": "ValueError"},
    }
    paths, _ = make_inputs(tmp_path, answer_records=answer_records, count=2)
    client = FakeGroqJudge()

    invoke_main(
        monkeypatch, paths, client,
        "--solo-risposte", "--valuta-risposte", "--solo-mancanti",
    )

    saved = judge.read_json(paths["out"])
    assert client.calls == []
    assert saved["answer_records"] == answer_records


def test_http_429_saves_completed_results_and_stops_following_questions(tmp_path, monkeypatch):
    paths, _ = make_inputs(tmp_path, count=3)
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = httpx.Response(429, request=request)
    failure = httpx.HTTPStatusError("rate limited", request=request, response=response)
    client = FakeGroqJudge(failure=(2, failure))

    invoke_main(monkeypatch, paths, client)

    saved = judge.read_json(paths["out"])
    assert client.calls == ["GT-001", "GT-002"]
    assert saved["records"]["GT-001#1"]["status"] == "judged"
    assert saved["records"]["GT-002#1"] == {
        "status": "judge_error",
        "judgments": [],
        "http_status": 429,
        "error_type": "HTTPStatusError",
    }
    assert "GT-003#1" not in saved["records"]


def test_answer_http_429_is_saved_before_stopping(tmp_path, monkeypatch):
    paths, _ = make_inputs(tmp_path, count=3)
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = httpx.Response(429, request=request)
    failure = httpx.HTTPStatusError("rate limited", request=request, response=response)

    class Always429:
        calls = 0

        def generate(self, *_args):
            self.calls += 1
            raise failure

        def close(self):
            pass

    client = Always429()
    with patch(
        "edicola.evaluation_metrics.rag_assessment",
        return_value=("answered", SimpleNamespace(answer="Risposta valida.")),
    ):
        invoke_main(
            monkeypatch, paths, client,
            "--solo-risposte", "--valuta-risposte",
        )

    saved = judge.read_json(paths["out"])
    assert client.calls == 1
    assert saved["answer_records"]["GT-001#1"] == {
        "status": "judge_error",
        "http_status": 429,
        "error_type": "HTTPStatusError",
        "diagnostic": "rate_limited",
        "diagnostic_criterion": "",
    }
    assert "GT-002#1" not in saved["answer_records"]


def test_solo_giudizi_falliti_retries_only_answer_errors_and_preserves_other_results(
    tmp_path, monkeypatch
):
    existing = {
        "GT-001#1": {"status": "judged", "grades": {"keep": True}},
        "GT-002#1": {"status": "judge_error", "error_type": "ValueError"},
        "GT-003#1": {"status": "no_valid_answer", "state": "model_abstention"},
    }
    retrieval_records = {
        "GT-001#1": {"status": "judged", "judgments": [{"chunk_id": "keep"}]},
    }
    paths, _ = make_inputs(
        tmp_path,
        existing_records=retrieval_records,
        answer_records=existing,
        count=3,
    )

    class ValidAnswerJudge:
        calls = []

        def generate(self, _instruction, prompt, *_args):
            request = json.loads(prompt)
            self.calls.append(request["question"])
            source = request["retrieved_sources"][0]
            quote = source["text"]
            return json.dumps({
                criterion: {
                    "score": "4",
                    "reason": "La valutazione è motivata dalle prove.",
                    "source_id": source["source_id"],
                    "quote": quote,
                }
                for criterion in (
                    "faithfulness", "completeness",
                    "answer_relevance", "citation_correctness",
                )
            })

        def close(self):
            pass

    client = ValidAnswerJudge()
    with patch(
        "edicola.evaluation_metrics.rag_assessment",
        return_value=("answered", SimpleNamespace(answer="Risposta valida.")),
    ):
        invoke_main(
            monkeypatch, paths, client,
            "--valuta-risposte", "--solo-giudizi-falliti",
        )

    saved = judge.read_json(paths["out"])
    assert client.calls == ["Quale piano è approvato?"]
    assert saved["records"] == retrieval_records
    assert saved["answer_records"]["GT-001#1"] == existing["GT-001#1"]
    assert saved["answer_records"]["GT-002#1"]["status"] == "judged"
    assert saved["answer_records"]["GT-002#1"]["grades"]["faithfulness"]["score"] == 4
    assert saved["answer_records"]["GT-003#1"] == existing["GT-003#1"]


def test_retry_saves_json_parse_diagnostic_without_accepting_invalid_output(
    tmp_path, monkeypatch
):
    existing = {
        "GT-001#1": {"status": "judge_error", "error_type": "ValueError"},
        "GT-002#1": {"status": "judged", "grades": {"keep": True}},
    }
    paths, _ = make_inputs(tmp_path, answer_records=existing, count=2)

    class InvalidJsonJudge:
        calls = 0

        def generate(self, *_args):
            self.calls += 1
            return "non è JSON"

        def close(self):
            pass

    client = InvalidJsonJudge()
    with patch(
        "edicola.evaluation_metrics.rag_assessment",
        return_value=("answered", SimpleNamespace(answer="Risposta valida.")),
    ):
        invoke_main(
            monkeypatch, paths, client,
            "--valuta-risposte", "--solo-giudizi-falliti",
        )

    saved = judge.read_json(paths["out"])
    assert client.calls == 1
    assert saved["answer_records"]["GT-001#1"] == {
        "status": "judge_error",
        "http_status": None,
        "error_type": "JSONDecodeError",
        "diagnostic": "invalid_json",
        "diagnostic_criterion": "",
    }
    assert saved["answer_records"]["GT-002#1"] == existing["GT-002#1"]


def test_retry_keeps_unverifiable_judgment_as_error_with_criterion(
    tmp_path, monkeypatch
):
    paths, _ = make_inputs(
        tmp_path,
        answer_records={
            "GT-001#1": {"status": "judge_error", "error_type": "ValueError"},
            "GT-002#1": {"status": "judged", "grades": {"keep": True}},
        },
        count=2,
    )

    class InvalidEvidenceJudge:
        def generate(self, _instruction, prompt, *_args):
            source = json.loads(prompt)["retrieved_sources"][0]
            return json.dumps({
                criterion: {
                    "score": "4",
                    "reason": "La valutazione è motivata dalle prove.",
                    "source_id": source["source_id"],
                    "quote": "Citazione non contenuta nella fonte."
                    if criterion == "faithfulness"
                    else source["text"],
                }
                for criterion in (
                    "faithfulness", "completeness",
                    "answer_relevance", "citation_correctness",
                )
            })

        def close(self):
            pass

    with patch(
        "edicola.evaluation_metrics.rag_assessment",
        return_value=("answered", SimpleNamespace(answer="Risposta valida.")),
    ):
        invoke_main(
            monkeypatch, paths, InvalidEvidenceJudge(),
            "--valuta-risposte", "--solo-giudizi-falliti",
        )

    saved = judge.read_json(paths["out"])
    assert saved["answer_records"]["GT-001#1"] == {
        "status": "judge_error",
        "http_status": None,
        "error_type": "JudgmentValidationError",
        "diagnostic": "unverifiable_evidence",
        "diagnostic_criterion": "faithfulness",
    }
    assert saved["answer_records"]["GT-002#1"] == {
        "status": "judged",
        "grades": {"keep": True},
    }


def test_groq_429_is_not_retried_and_configured_pause_remains(monkeypatch):
    client = Mock()
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = httpx.Response(
        429,
        headers={"retry-after": "1"},
        request=request,
    )
    client.post.return_value = response
    groq = judge.GroqJudge.__new__(judge.GroqJudge)
    groq.client = client
    groq._ultima_chiamata = 100
    monkeypatch.setenv("GROQ_PAUSA_SECONDI", "30")

    with (
        patch.object(judge.time, "monotonic", side_effect=[110, 110]),
        patch.object(judge.time, "sleep") as sleep,
    ):
        returned = groq._post_con_pausa("https://api.groq.com/openai/v1/chat/completions")

    assert returned is response
    assert client.post.call_count == 1
    sleep.assert_called_once_with(20)