"""Test offline del benchmark: nessuna API, nessun archivio reale."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from evaluation.performance.benchmark import (
    AttemptBudget, TOPICS, main, make_plan, parse_mix, parse_rates,
    percentile, save_outputs, summarize,
)


def test_preview_without_index_or_key(tmp_path, capsys):
    assert main(["--preview", "--root", str(tmp_path), "--rates", "1,2",
                 "--max-requests", "3"]) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview["estimated_requests"] == 3
    assert [r["scheduled_offset_s"] for r in preview["plan"]] == [0, 60, 90]
    assert all(r["class"] != "podcast" for r in preview["plan"])


def test_live_requires_explicit_authorization_before_preflight(tmp_path):
    with pytest.raises(SystemExit) as error:
        main(["--run", "--root", str(tmp_path)])
    assert error.value.code == 2


def test_check_missing_archive_never_calls_api(tmp_path, capsys):
    with pytest.raises(SystemExit) as error:
        main(["--check", "--root", str(tmp_path)])
    assert error.value.code == 2
    assert "Nessuna chiamata API" in capsys.readouterr().err


def test_rates_and_mix_validation():
    assert parse_rates("1,2,4") == [1, 2, 4]
    with pytest.raises(ValueError):
        parse_rates("3,2")
    with pytest.raises(ValueError):
        parse_rates("1,7")
    with pytest.raises(ValueError):
        parse_mix("podcast:1", False)
    assert parse_mix("chat:2,podcast:1", True) == {"chat": 2, "podcast": 1}


def test_weighted_plan_is_deterministic():
    weights = {"chat": 2, "briefing": 1, "timeline": 1, "map": 1}
    x = make_plan([1, 2, 3], 60, 6, weights, TOPICS)
    y = make_plan([1, 2, 3], 60, 6, weights, TOPICS)
    assert x == y
    assert [row["target_rpm"] for row in x] == [1, 2, 2, 3, 3, 3]
    assert len({row["class"] for row in x}) >= 3


def test_api_budget_includes_retry_attempts():
    budget = AttemptBudget(2)
    budget.claim()
    budget.claim()
    with pytest.raises(RuntimeError):
        budget.claim()
    assert budget.used == 2


def test_percentile_and_summary():
    assert percentile([], .95) is None
    assert percentile([1, 3, 5, 7], .95) == 7
    rows = [{
        "class": "chat", "phase": 1, "outcome": "ok",
        "cache_hit": False, "api_attempts": 2, "http_429_attempts": 0,
        "end_to_end_s": 1.2, "completion_offset_s": 1.2,
    }, {
        "class": "map", "phase": 2, "outcome": "error",
        "cache_hit": None, "api_attempts": 3, "http_429_attempts": 1,
        "end_to_end_s": 4.2, "completion_offset_s": 65.0,
    }]
    summary = summarize(rows, [1, 2], 60)
    assert summary["total"]["scheduled"] == 2
    assert summary["total"]["success_rate"] == .5
    assert summary["total"]["api_attempts"] == 5
    assert summary["total"]["http_429_attempts"] == 1
    assert summary["by_phase"]["1"]["observed_completions_per_min"] == 1
    assert summary["by_phase"]["2"]["failed"] == 1

def test_cli_script_direct_from_codespaces_root():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "evaluation/performance/benchmark.py", "--preview",
         "--rates", "1", "--max-requests", "1"],
        cwd=root, capture_output=True, text=True, timeout=15, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["estimated_requests"] == 1

def test_export_creates_tables_and_report_without_api(tmp_path):
    rows = [{
        "request_id": "R001", "class": "chat", "phase": 1,
        "target_rpm": 1, "prompt": "Domanda di prova",
        "scheduled_offset_s": 0, "outcome": "ok", "error_kind": None,
        "cache_hit": False, "content_available": True,
        "actual_start_offset_s": 0.01, "completion_offset_s": 1.2,
        "queue_delay_s": 0.01, "processing_s": 1.19,
        "end_to_end_s": 1.2, "api_attempts": 2,
        "embedding_attempts": 1, "generation_attempts": 1,
        "tts_attempts": 0, "http_429_attempts": 0, "api_errors": 0,
        "api_events": [],
    }]
    stats = summarize(rows, [1], 60)
    output = tmp_path / "performance-output"
    metadata = {"started_utc": "2026-11-20T12:00:00+00:00",
                "environment": {"pdf_count": 22,
                                "active_chunks": 2606, "chroma_vectors": 2367},
                "max_in_flight": 1, "actual_api_claims": 2}
    save_outputs(output, rows, stats, metadata)
    assert (output / "requests.csv").is_file()
    assert (output / "metrics.csv").is_file()
    assert (output / "summary.json").is_file()
    assert (output / "api_attempts.json").is_file()
    report = (output / "report_tesi.md").read_text(encoding="utf-8")
    assert "## Latenza per classe" in report
    assert "## Evoluzione al crescere" in report
    assert "| chat | 1 | 1.0 |" in report
    assert report.count("\\n") == 0
