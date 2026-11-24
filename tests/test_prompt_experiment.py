"""Prompt sperimentale validato con run e client Gemini simulati."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from google.genai import types

from edicola.evaluation_data import digest, write_json
from edicola.evaluation import report_run
from edicola.prompt_experiment import (
    COMPLETENESS_INSTRUCTION,
    EXPERIMENT_ID,
    _atomic_write_json,
    main,
    prompt_experiment,
    retry_errors,
)
from edicola.rag import INSUFFICIENT, RagError
from test_evaluation import run_mock, study


def test_experiment_preserves_provenance_and_reuses_exact_baseline_chunks(
    tmp_path, study
):
    baseline = run_mock(tmp_path, study)
    baseline_before = copy.deepcopy(baseline)
    client = Mock()
    captured = []

    def generate(**kwargs):
        captured.append(kwargs)
        source = json.loads(kwargs["contents"])["sources"][0]
        result = {
            "sufficient": True,
            "claims": [{
                "text": "Il fatto richiesto e documentato.",
                "evidence": [{
                    "source_id": source["source_id"],
                    "quote": source["text"],
                }],
            }],
        }
        return SimpleNamespace(
            text=json.dumps(result),
            candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)],
        )

    client.models.generate_content.side_effect = generate
    with patch(
        "edicola.prompt_experiment.provenance",
        return_value={"source": "test"},
    ):
        experiment = prompt_experiment(
            study[2],
            study[1],
            baseline,
            authorize_external=True,
            client=client,
            inter_question_sleep=Mock(),
        )

    source_record = baseline["records"][0]
    result_record = experiment["records"][0]
    assert baseline == baseline_before
    assert experiment["snapshot_id"] == baseline["snapshot_id"]
    assert experiment["dataset_id"] == baseline["dataset_id"] == digest(study[2])
    assert experiment["source_run_id"] == digest(baseline)
    assert experiment["top_k"] == baseline["top_k"]
    assert experiment["configuration"]["generation_model"] == baseline["configuration"]["generation_model"]
    assert experiment["configuration"]["generation_prompt"] == EXPERIMENT_ID
    assert result_record["retrieved"] == source_record["retrieved"]
    assert len(result_record["retrieved"]) == len(source_record["retrieved"])
    assert result_record["response_state"] == "answered"
    assert result_record["api_events"] and all(
        event["phase"] == "generation" for event in result_record["api_events"]
    )
    assert client.models.embed_content.call_count == 0
    assert captured[0]["model"] == baseline["configuration"]["generation_model"]
    assert captured[0]["config"].system_instruction == COMPLETENESS_INSTRUCTION
    assert source_record["retrieved"][0]["text"] in captured[0]["contents"]
    assert "Punto sintetico del test" not in captured[0]["contents"]
    assert result_record["answer"] != source_record["answer"]
    report_run(tmp_path / "prompt-report", study[2], study[1], experiment)
    assert (tmp_path / "prompt-report" / "report.md").is_file()
    assert (tmp_path / "prompt-report" / "human_review.csv").is_file()


def test_experiment_requires_consent_before_any_model_call(tmp_path, study):
    baseline = run_mock(tmp_path, study)
    client = Mock()
    with pytest.raises(ValueError, match="Autorizzare"):
        prompt_experiment(study[2], study[1], baseline, client=client)
    client.models.generate_content.assert_not_called()
    client.models.embed_content.assert_not_called()


def test_experiment_rejects_nonmatching_dataset_without_calls(tmp_path, study):
    baseline = run_mock(tmp_path, study)
    altered = copy.deepcopy(study[2])
    altered["questions"][0]["question"] += "?"
    client = Mock()
    with pytest.raises(ValueError, match="dataset/snapshot"):
        prompt_experiment(
            altered,
            study[1],
            baseline,
            authorize_external=True,
            client=client,
        )
    client.models.generate_content.assert_not_called()


def test_experiment_rejects_partial_or_multiple_baseline_runs(tmp_path, study):
    baseline = run_mock(tmp_path, study)
    baseline["records"][0]["repeat"] = 2
    client = Mock()
    with pytest.raises(ValueError, match="una esecuzione per domanda"):
        prompt_experiment(
            study[2],
            study[1],
            baseline,
            authorize_external=True,
            client=client,
        )
    client.models.generate_content.assert_not_called()


def test_experiment_instructions_require_coverage_and_literal_evidence():
    assert "tutti i passaggi forniti" in COMPLETENESS_INSTRUCTION
    assert "sequenza contigua e letterale" in COMPLETENESS_INSTRUCTION
    assert "Non colmare lacune" in COMPLETENESS_INSTRUCTION
    assert "source_id" in COMPLETENESS_INSTRUCTION


def test_experiment_does_not_accept_unverifiable_claims_after_quote_retry(
    tmp_path, study
):
    baseline = run_mock(tmp_path, study)
    client = Mock()
    invalid = json.dumps({
        "sufficient": True,
        "claims": [{
            "text": "Un'affermazione priva di prova verificabile.",
            "evidence": [{
                "source_id": "S1",
                "quote": "Citazione inventata e non presente nella fonte.",
            }],
        }],
    })
    client.models.generate_content.return_value = SimpleNamespace(
        text=invalid,
        candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)],
    )

    experiment = prompt_experiment(
        study[2],
        study[1],
        baseline,
        authorize_external=True,
        client=client,
        inter_question_sleep=Mock(),
    )

    assert client.models.generate_content.call_count == 2
    assert experiment["records"][0]["response_state"] == "validation_failed"
    assert experiment["records"][0]["answer"] == INSUFFICIENT
    assert "affermazione priva di prova" not in experiment["records"][0]["answer"]


def test_experiment_keeps_initial_invalid_response_if_quote_retry_fails(
    tmp_path, study
):
    baseline = run_mock(tmp_path, study)
    client = Mock()
    initial = json.dumps({
        "sufficient": True,
        "claims": [{
            "text": "Claim with an unverifiable quote.",
            "evidence": [{
                "source_id": "S1",
                "quote": "A fabricated quote that is absent from the source.",
            }],
        }],
    })
    client.models.generate_content.side_effect = [
        SimpleNamespace(
            text=initial,
            candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)],
        ),
        RagError("Mocked retry failure.", http_status=503),
    ]

    experiment = prompt_experiment(
        study[2],
        study[1],
        baseline,
        authorize_external=True,
        client=client,
        inter_question_sleep=Mock(),
    )

    record = experiment["records"][0]
    assert client.models.generate_content.call_count == 2
    assert record["raw_response"] == initial
    assert record["response_state"] == "validation_failed"
    assert record["answer"] == INSUFFICIENT
    assert "unverifiable quote" not in record["answer"]
    assert record["retry_error"] == {
        "phase": "generation",
        "http_status": 503,
        "error_type": "RagError",
    }


def _two_record_experiment(tmp_path, study):
    dataset = copy.deepcopy(study[2])
    second_question = copy.deepcopy(dataset["questions"][0])
    second_question.update(id="q02", question="Quali fatti documentano la domanda?")
    dataset["questions"].append(second_question)

    baseline = run_mock(tmp_path, study)
    baseline["dataset_id"] = digest(dataset)
    second_record = copy.deepcopy(baseline["records"][0])
    second_record["question_id"] = second_question["id"]
    baseline["records"].append(second_record)

    client = Mock()

    def answer(**kwargs):
        source = json.loads(kwargs["contents"])["sources"][0]
        response = {
            "sufficient": True,
            "claims": [{
                "text": "Il fatto richiesto e documentato.",
                "evidence": [{
                    "source_id": source["source_id"],
                    "quote": source["text"],
                }],
            }],
        }
        return SimpleNamespace(
            text=json.dumps(response),
            candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)],
        )

    client.models.generate_content.side_effect = answer
    experiment = prompt_experiment(
        dataset,
        study[1],
        baseline,
        authorize_external=True,
        client=client,
        inter_question_sleep=Mock(),
    )
    experiment["records"][0].update(
        status="error",
        raw_response=None,
        answer=None,
        response_state="not_run",
        error_phase="generation",
        error_type="request_or_local_error",
    )
    return dataset, baseline, experiment


def test_retry_errors_only_retries_failed_generation_and_saves_progress(
    tmp_path, study
):
    dataset, baseline, experiment = _two_record_experiment(tmp_path, study)
    successful_record_before = copy.deepcopy(experiment["records"][1])
    client = Mock()

    def answer(**kwargs):
        source = json.loads(kwargs["contents"])["sources"][0]
        response = {
            "sufficient": True,
            "claims": [{
                "text": "La risposta recuperata e verificata.",
                "evidence": [{
                    "source_id": source["source_id"],
                    "quote": source["text"],
                }],
            }],
        }
        return SimpleNamespace(
            text=json.dumps(response),
            candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)],
        )

    client.models.generate_content.side_effect = answer
    path = tmp_path / "run.json"
    write_json(path, experiment)

    result = retry_errors(
        dataset,
        study[1],
        baseline,
        experiment,
        authorize_external=True,
        client=client,
        inter_question_sleep=Mock(),
        save_progress=lambda updated: _atomic_write_json(path, updated),
    )

    assert client.models.generate_content.call_count == 1
    assert result["records"][0]["status"] == "ok"
    assert result["records"][0]["retrieved"] == baseline["records"][0]["retrieved"]
    assert result["records"][1] == successful_record_before
    assert json.loads(path.read_text(encoding="utf-8")) == result


def test_retry_errors_keeps_previous_record_when_generation_fails(tmp_path, study):
    dataset, baseline, experiment = _two_record_experiment(tmp_path, study)
    previous = copy.deepcopy(experiment)
    client = Mock()
    client.models.generate_content.side_effect = RagError(
        "Simulated unavailable service.", http_status=503
    )
    saved = Mock()

    result = retry_errors(
        dataset,
        study[1],
        baseline,
        experiment,
        authorize_external=True,
        client=client,
        inter_question_sleep=Mock(),
        save_progress=saved,
    )

    assert client.models.generate_content.call_count == 1
    assert result == previous
    saved.assert_not_called()


def test_retry_errors_rejects_changed_run_before_any_generation(tmp_path, study):
    dataset, baseline, experiment = _two_record_experiment(tmp_path, study)
    experiment["records"][1]["retrieved"][0]["text"] += " altered"
    client = Mock()

    with pytest.raises(ValueError):
        retry_errors(
            dataset,
            study[1],
            baseline,
            experiment,
            authorize_external=True,
            client=client,
        )

    client.models.generate_content.assert_not_called()


def test_cli_retry_errors_uses_existing_run_directory(tmp_path, monkeypatch):
    out = tmp_path / "existing-run"
    out.mkdir()
    run_path = out / "run.json"
    run_path.touch()
    snapshot = {"origin": "real"}
    dataset = {"questions": []}
    baseline = {"origin": "real"}
    experiment = {"records": [{"status": "error"}]}
    files = {
        tmp_path / "snapshot.json": snapshot,
        tmp_path / "dataset.json": dataset,
        tmp_path / "baseline.json": baseline,
        run_path: experiment,
    }
    monkeypatch.setattr(
        "edicola.prompt_experiment.read_json", lambda path: files[Path(path)]
    )
    monkeypatch.setattr(
        "edicola.prompt_experiment._validate_baseline", lambda *_args: (None, "model")
    )
    monkeypatch.setattr("edicola.prompt_experiment.report_run", Mock())

    def retry(*_args, save_progress, **_kwargs):
        save_progress(experiment)
        return experiment

    retry_mock = Mock(side_effect=retry)
    monkeypatch.setattr("edicola.prompt_experiment.retry_errors", retry_mock)

    assert main([
        "--snapshot", str(tmp_path / "snapshot.json"),
        "--dataset", str(tmp_path / "dataset.json"),
        "--baseline-run", str(tmp_path / "baseline.json"),
        "--out", str(out),
        "--authorize-external",
        "--retry-errors",
    ]) == 0
    retry_mock.assert_called_once()
    assert json.loads(run_path.read_text(encoding="utf-8")) == experiment


def test_atomic_json_write_preserves_previous_file_if_replace_fails(tmp_path, monkeypatch):
    path = tmp_path / "run.json"
    path.write_text('{"previous": true}\n', encoding="utf-8")
    monkeypatch.setattr(
        "edicola.prompt_experiment.os.replace",
        Mock(side_effect=OSError("simulated replace failure")),
    )

    with pytest.raises(OSError):
        _atomic_write_json(path, {"new": True})

    assert path.read_text(encoding="utf-8") == '{"previous": true}\n'
