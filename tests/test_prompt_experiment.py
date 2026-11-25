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


RECOVERY_IDS = (
    "GT-103",
    "GT-104",
    "GT-105",
    "GT-106",
    "GT-113",
    "GT-118",
    "GT-120",
    "GT-121",
    "GT-136",
)


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


def _fifty_question_inputs(tmp_path, study):
    dataset = copy.deepcopy(study[2])
    template = copy.deepcopy(dataset["questions"][0])
    dataset["questions"] = []
    for number in range(101, 151):
        question = copy.deepcopy(template)
        question_id = f"GT-{number}"
        question.update(id=question_id, question=f"Domanda sintetica {question_id}?")
        dataset["questions"].append(question)

    baseline = run_mock(tmp_path, study)
    baseline["dataset_id"] = digest(dataset)
    baseline_record = copy.deepcopy(baseline["records"][0])
    baseline["records"] = []
    for question in dataset["questions"]:
        record = copy.deepcopy(baseline_record)
        record["question_id"] = question["id"]
        if question["id"] in RECOVERY_IDS:
            record.update(
                response_state="validation_failed",
                raw_response="{}",
                answer=INSUFFICIENT,
            )
        baseline["records"].append(record)
    return dataset, baseline


def test_experiment_only_regenerates_selected_ids_and_validates_every_response(
    tmp_path, study
):
    dataset, baseline = _fifty_question_inputs(tmp_path, study)
    baseline_before = copy.deepcopy(baseline)

    client = Mock()
    generated_ids = []

    def generate(**kwargs):
        payload = json.loads(kwargs["contents"])
        question_id = payload["question"].removeprefix("Domanda sintetica ").removesuffix("?")
        generated_ids.append(question_id)
        if question_id == "GT-104":
            response = {"sufficient": False, "claims": []}
        elif question_id == "GT-106":
            raise RagError("Mocked generation failure.", http_status=503)
        elif question_id == "GT-103":
            response = {
                "sufficient": True,
                "claims": [{
                    "text": "Affermazione senza prova valida.",
                    "evidence": [{
                        "source_id": payload["sources"][0]["source_id"],
                        "quote": "Citazione non presente nel chunk.",
                    }],
                }],
            }
        else:
            source = payload["sources"][0]
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

    client.models.generate_content.side_effect = generate
    experiment = prompt_experiment(
        dataset,
        study[1],
        baseline,
        authorize_external=True,
        only_ids=RECOVERY_IDS,
        client=client,
        inter_question_sleep=Mock(),
    )

    assert baseline == baseline_before
    assert set(generated_ids) == set(RECOVERY_IDS)
    unselected_ids = {
        f"GT-{number}" for number in range(101, 151)
    } - set(RECOVERY_IDS)
    assert len(unselected_ids) == 41
    assert not set(generated_ids) & unselected_ids
    assert len(generated_ids) == 9
    assert generated_ids.count("GT-103") == 1
    assert all(
        generated_ids.count(identity) == 1
        for identity in RECOVERY_IDS
        if identity != "GT-103"
    )
    assert len(experiment["records"]) == 9
    assert [record["question_id"] for record in experiment["records"]] == list(RECOVERY_IDS)
    assert client.models.embed_content.call_count == 0
    for record in experiment["records"]:
        original = next(
            item for item in baseline["records"] if item["question_id"] == record["question_id"]
        )
        assert record["retrieved"] == original["retrieved"]

    states = {record["question_id"]: record["response_state"] for record in experiment["records"]}
    assert states["GT-103"] == "validation_failed"
    assert states["GT-104"] == "model_abstention"
    assert states["GT-106"] == "not_run"
    assert next(
        record for record in experiment["records"] if record["question_id"] == "GT-106"
    )["status"] == "error"
    assert sum(state == "answered" for state in states.values()) == 6
    invalid = next(record for record in experiment["records"] if record["question_id"] == "GT-103")
    assert invalid["answer"] == INSUFFICIENT


def test_selective_recovery_rejects_unanswerable_and_previously_validated_ids(
    tmp_path, study
):
    dataset, baseline = _fifty_question_inputs(tmp_path, study)
    client = Mock()

    with pytest.raises(ValueError, match="Non rispondibile"):
        prompt_experiment(
            dataset,
            study[1],
            baseline,
            authorize_external=True,
            only_ids=("GT-103",),
            ground_truth_categories={"GT-103": "Non rispondibile"},
            client=client,
        )
    with pytest.raises(ValueError, match="risposta validata"):
        prompt_experiment(
            dataset,
            study[1],
            baseline,
            authorize_external=True,
            only_ids=("GT-103",),
            ground_truth_categories={"GT-103": "Fattuale"},
            already_validated_ids={"GT-103"},
            client=client,
        )

    client.models.generate_content.assert_not_called()
    client.models.embed_content.assert_not_called()


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


def test_retry_errors_recovers_one_error_in_partial_experiment(tmp_path, study):
    dataset, baseline = _fifty_question_inputs(tmp_path, study)
    baseline_before = copy.deepcopy(baseline)
    client = Mock()

    def generate(**kwargs):
        payload = json.loads(kwargs["contents"])
        question_id = payload["question"].removeprefix(
            "Domanda sintetica "
        ).removesuffix("?")
        if question_id == "GT-120":
            raise RagError("Mocked generation failure.", http_status=503)
        source = payload["sources"][0]
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

    client.models.generate_content.side_effect = generate
    experiment = prompt_experiment(
        dataset,
        study[1],
        baseline,
        authorize_external=True,
        only_ids=RECOVERY_IDS,
        client=client,
        inter_question_sleep=Mock(),
    )
    assert len(experiment["records"]) == 9
    failed = [
        record for record in experiment["records"] if record["status"] == "error"
    ]
    assert [record["question_id"] for record in failed] == ["GT-120"]
    preserved = {
        record["question_id"]: copy.deepcopy(record)
        for record in experiment["records"]
        if record["question_id"] != "GT-120"
    }

    def retry(**kwargs):
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

    client.models.generate_content.reset_mock()
    client.models.generate_content.side_effect = retry
    client.models.embed_content.reset_mock()
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
    retry_payload = json.loads(
        client.models.generate_content.call_args.kwargs["contents"]
    )
    assert retry_payload["question"] == "Domanda sintetica GT-120?"
    assert client.models.embed_content.call_count == 0
    assert len(result["records"]) == 9
    assert all(
        next(
            record for record in result["records"]
            if record["question_id"] == question_id
        ) == record
        for question_id, record in preserved.items()
    )
    recovered = next(
        record for record in result["records"] if record["question_id"] == "GT-120"
    )
    assert recovered["status"] == "ok"
    assert recovered["response_state"] == "answered"
    assert recovered["retrieved"] == next(
        record for record in baseline["records"]
        if record["question_id"] == "GT-120"
    )["retrieved"]
    assert baseline == baseline_before
    saved.assert_called_once()
    assert saved.call_args.args[0] == result


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


def test_cli_only_ids_parses_selection_and_preserves_previous_run(
    tmp_path, monkeypatch
):
    out = tmp_path / "prompt-completeness-recupero9"
    snapshot_path = tmp_path / "snapshot.json"
    dataset_path = tmp_path / "dataset.json"
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text('{"origin": "real"}\n', encoding="utf-8")
    baseline_before = baseline_path.read_bytes()
    previous_path = tmp_path / "prompt-completeness-previous" / "run.json"
    previous_path.parent.mkdir()
    previous_path.write_text('{"historical": true}\n', encoding="utf-8")
    previous_before = previous_path.read_bytes()
    files = {
        snapshot_path: {"origin": "real"},
        dataset_path: {"questions": []},
        baseline_path: {"origin": "real"},
    }
    monkeypatch.setattr(
        "edicola.prompt_experiment.read_json", lambda path: files[Path(path)]
    )
    monkeypatch.setattr(
        "edicola.prompt_experiment._validate_baseline", lambda *_args: (None, "model")
    )
    monkeypatch.setattr(
        "edicola.prompt_experiment._read_ground_truth_categories",
        lambda _path: {identity: "Fattuale" for identity in RECOVERY_IDS},
    )
    monkeypatch.setattr(
        "edicola.prompt_experiment._select_recovery_records",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "edicola.prompt_experiment._validated_answer_ids",
        Mock(return_value={"GT-146"}),
    )
    monkeypatch.setattr("edicola.prompt_experiment.report_run", Mock())
    files[previous_path] = {"records": []}
    generated = {"records": []}
    experiment = Mock(return_value=generated)
    monkeypatch.setattr("edicola.prompt_experiment.prompt_experiment", experiment)

    assert main([
        "--snapshot", str(snapshot_path),
        "--dataset", str(dataset_path),
        "--baseline-run", str(baseline_path),
        "--out", str(out),
        "--authorize-external",
        "--ground-truth-csv", str(tmp_path / "ground_truth.csv"),
        "--exclude-validated-run", str(previous_path),
        "--only-ids", ",".join(RECOVERY_IDS),
    ]) == 0

    assert experiment.call_args.kwargs["only_ids"] == RECOVERY_IDS
    assert experiment.call_args.kwargs["ground_truth_categories"] == {
        identity: "Fattuale" for identity in RECOVERY_IDS
    }
    assert experiment.call_args.kwargs["already_validated_ids"] == {"GT-146"}
    assert baseline_path.read_bytes() == baseline_before
    assert previous_path.read_bytes() == previous_before
    assert json.loads((out / "run.json").read_text(encoding="utf-8")) == generated


def test_cli_selective_run_requires_ground_truth_before_creating_output(
    tmp_path, monkeypatch
):
    paths = {
        tmp_path / "snapshot.json": {"origin": "real"},
        tmp_path / "dataset.json": {"questions": []},
        tmp_path / "baseline.json": {"origin": "real"},
    }
    monkeypatch.setattr(
        "edicola.prompt_experiment.read_json", lambda path: paths[Path(path)]
    )
    monkeypatch.setattr(
        "edicola.prompt_experiment._validate_baseline", lambda *_args: (None, "model")
    )
    output = tmp_path / "must-not-be-created"

    assert main([
        "--snapshot", str(tmp_path / "snapshot.json"),
        "--dataset", str(tmp_path / "dataset.json"),
        "--baseline-run", str(tmp_path / "baseline.json"),
        "--out", str(output),
        "--authorize-external",
        "--only-ids", "GT-001",
    ]) == 1
    assert not output.exists()


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
