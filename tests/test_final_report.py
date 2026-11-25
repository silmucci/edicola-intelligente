import json

from edicola.evaluation_data import digest, write_json
from edicola.final_report import (
    _aggregate_scope,
    _validated_answer_scores,
    calculate_ai_silver_metrics,
    summarize_values,
)


def _metric(rows, name):
    return next(row for row in rows if row["metric"] == name)


def test_ai_silver_metrics_preserve_original_denominators_and_unknown_labels():
    precision, mrr = calculate_ai_silver_metrics(["R", "N", "N"], 3)
    assert precision == 1 / 3
    assert mrr == 1.0

    precision, mrr = calculate_ai_silver_metrics(["U", "R", "N"], 3)
    assert precision is None
    assert mrr is None

    precision, mrr = calculate_ai_silver_metrics(["N", "N", "N"], 3)
    assert precision == 0.0
    assert mrr == 0.0


def test_summarize_values_excludes_missing_without_imputing_zero():
    summary = summarize_values([1.0, None, 3.0])
    assert summary == {"n": 2, "missing": 1, "mean": 2.0, "median": 2.0}
    assert summarize_values([None, None]) == {
        "n": 0,
        "missing": 2,
        "mean": None,
        "median": None,
    }


def test_aggregate_scope_reports_denominators_api_failures_and_recorded_times():
    records = {
        "GT-001": {
            "status": "ok",
            "raw_response": "{}",
            "response_state": "answered",
            "api_events": [{"outcome": "error"}],
            "retrieval_seconds": 0.5,
            "generation_seconds": 1.0,
            "total_seconds": 1.5,
        },
        "GT-002": {
            "status": "ok",
            "raw_response": "{}",
            "response_state": "model_abstention",
            "api_events": [{"outcome": "ok"}],
            "retrieval_seconds": None,
            "generation_seconds": 2.0,
            "total_seconds": 2.0,
        },
        "GT-003": {
            "status": "ok",
            "raw_response": "{}",
            "response_state": "validation_failed",
            "api_events": [],
            "retrieval_seconds": 0.5,
            "generation_seconds": None,
            "total_seconds": None,
        },
        "GT-004": {
            "status": "error",
            "raw_response": None,
            "response_state": "not_run",
            "api_events": [{"outcome": "error"}, {"outcome": "error"}],
            "retrieval_seconds": None,
            "generation_seconds": 3.0,
            "total_seconds": 4.0,
        },
    }
    rows = _aggregate_scope(
        "synthetic",
        records,
        {},
        {
            "GT-001": (1 / 3, 1.0),
            "GT-002": (None, None),
            "GT-003": (0.0, 0.0),
        },
        {"GT-001": {"faithfulness": 4}, "GT-002": {"faithfulness": None}},
    )

    assert _metric(rows, "domande")["value"] == 4
    assert _metric(rows, "risposte_generate_raw")["value"] == 3
    assert _metric(rows, "risposte_validate")["value"] == 1
    assert _metric(rows, "astensioni_modello")["value"] == 1
    assert _metric(rows, "errori_validazione")["value"] == 1
    assert _metric(rows, "domande_con_errori_api")["value"] == 2
    assert _metric(rows, "tentativi_api_falliti")["value"] == 3
    assert _metric(rows, "precision_at_3")["value"] == 1 / 6
    assert _metric(rows, "precision_at_3")["valid_n"] == 2
    assert _metric(rows, "mrr_at_3")["value"] == 0.5
    assert _metric(rows, "groq_faithfulness_mean")["value"] == 4
    assert _metric(rows, "groq_faithfulness_mean")["valid_n"] == 1
    assert _metric(rows, "total_seconds_mean")["value"] == 2.5
    assert _metric(rows, "total_seconds_median")["value"] == 2.0


def test_answer_score_aggregation_excludes_judge_errors_and_invalid_evidence(tmp_path):
    hit = {
        "id": "chunk-1",
        "filename": "edizione.pdf",
        "page": 1,
        "text": "Il Comune ha stanziato 10 milioni per l'intervento.",
        "distance": 0.1,
    }
    raw_answer = json.dumps(
        {
            "sufficient": True,
            "claims": [
                {
                    "text": "Il Comune ha stanziato 10 milioni.",
                    "evidence": [
                        {
                            "source_id": "S1",
                            "quote": "Il Comune ha stanziato 10 milioni",
                        }
                    ],
                }
            ],
        }
    )
    run = {
        "snapshot_id": "snapshot-id",
        "records": [
            {
                "question_id": identity,
                "status": "ok",
                "response_state": "answered",
                "raw_response": raw_answer,
                "retrieved": [hit],
            }
            for identity in ("GT-001", "GT-002", "GT-003")
        ],
    }
    valid_grades = {
        "faithfulness": {
            "score": 4,
            "reason": "La frase è supportata dalla fonte.",
            "source_id": "S1",
            "quote": "Il Comune ha stanziato 10 milioni",
        },
        "completeness": {
            "score": 3,
            "reason": "La risposta copre i fatti richiesti.",
            "source_id": "",
            "quote": "",
        },
        "answer_relevance": {
            "score": 4,
            "reason": "La risposta è pertinente alla domanda.",
            "source_id": "",
            "quote": "",
        },
        "citation_correctness": {
            "score": 4,
            "reason": "La citazione sostiene l'affermazione.",
            "source_id": "S1",
            "quote": "Il Comune ha stanziato 10 milioni",
        },
    }
    invalid_grades = json.loads(json.dumps(valid_grades))
    invalid_grades["citation_correctness"]["quote"] = "Una frase inventata."
    judge_data = {
        "schema_version": 1,
        "provider": "groq",
        "snapshot_id": "snapshot-id",
        "run_sha256": digest(run),
        "answer_records": {
            "GT-001#1": {"status": "judged", "grades": valid_grades},
            "GT-002#1": {"status": "judge_error", "grades": valid_grades},
            "GT-003#1": {"status": "judged", "grades": invalid_grades},
        },
    }
    judge_path = tmp_path / "judge.json"
    write_json(judge_path, judge_data)

    scores, statuses, invalid = _validated_answer_scores(
        judge_path, run, {record["question_id"]: record for record in run["records"]}
    )

    assert set(scores) == {"GT-001"}
    assert scores["GT-001"] == {
        "faithfulness": 4,
        "completeness": 3,
        "answer_relevance": 4,
        "citation_correctness": 4,
    }
    assert statuses == {"judged": 2, "judge_error": 1}
    assert invalid == 1
