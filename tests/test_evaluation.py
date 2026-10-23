"""Dati di prova interamente sintetici: nessuna qualità reale viene attribuita."""

import copy
import json
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from google.genai import errors, types

from edicola.archive import IndexChunk
from edicola.editorial_selection import Catalog
from edicola.evaluation import benchmark, main, personalization_experiment, report_run
from edicola.evaluation_data import dataset_template, digest, read_json, snapshot, validate_dataset, validate_snapshot, write_json
from edicola.evaluation_metrics import rag_assessment, retrieval_metrics, score_run, sources_from_hits, summarize
from edicola.evaluation_report import REVIEW_FIELDS, read_reviews, review_rows, write_csv
from edicola.profiles import Profile


@pytest.fixture(autouse=True)
def no_real_api(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-never-log")
    monkeypatch.setenv("GEMINI_RAG_MODEL", "configured-test-model")
    with patch("google.genai.Client", side_effect=AssertionError("API reale vietata")):
        yield


@pytest.fixture
def study():
    texts = ["Il Comune approva il piano trasporti con nuove corse.", "La scuola apre una nuova biblioteca per gli studenti.",
             "I trasporti della provincia avranno nuovi collegamenti.", "La scuola cittadina inaugura i laboratori didattici."]
    chunks = [IndexChunk(chr(97+i), text, {"filename": f"giornale-{i//2}.pdf", "page": i % 2+1, "pdf_sha256": str(i//2)*64}) for i, text in enumerate(texts)]
    catalog = Catalog(chunks, {}, {"indexed": 4, "total": 8, "partial": True, "warnings": [], "files": [
        {"pdf": "giornale-0.pdf", "publication": "Testata A", "date": "2026-10-20", "indexed": 2, "total": 4},
        {"pdf": "giornale-1.pdf", "publication": "Testata B", "date": "2026-10-21", "indexed": 2, "total": 4}]})
    frozen = snapshot(catalog, "simulated")
    dataset = dataset_template(frozen["snapshot_id"])
    q = dataset["questions"][0]
    q.update(question="Quali interventi sono previsti per i trasporti?", annotator="annotatore-sintetico",
             answerability="answerable", judgments_complete=True,
             relevant_chunks=[{"chunk_id": c.id, "pdf": c.metadata["filename"], "page": c.metadata["page"]} for c in (chunks[0], chunks[2])],
             nonrelevant_chunk_ids=["b", "d"], expected_points=["Punto sintetico del test, non riferimento sperimentale reale."])
    return catalog, frozen, dataset


def hit(chunk):
    return {"id": chunk.id, "text": chunk.text, "distance": 0.2, **chunk.metadata}


def mock_client():
    client = Mock()
    client.models.embed_content.return_value = SimpleNamespace(embeddings=[SimpleNamespace(values=[1.0] + [0.0]*767)])
    def answer(**kwargs):
        data = json.loads(kwargs["contents"])
        source = data["sources"][0]
        claim = {"text": "Il Comune approva il piano trasporti.", "evidence": [{"source_id": source["source_id"], "quote": source["text"]}]}
        return SimpleNamespace(text=json.dumps({"sufficient": True, "claims": [claim]}), candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)])
    client.models.generate_content.side_effect = answer
    return client


def run_mock(tmp_path, study, **kwargs):
    catalog, frozen, dataset = study
    client = kwargs.pop("client", mock_client())
    def search(_question, **options):
        options["embedder"].embed("task: question answering | query: domanda sintetica")
        return [hit(c) for c in catalog.chunks[:options["top_k"]]]
    with patch("edicola.evaluation.read_catalog", return_value=catalog), patch("edicola.evaluation.semantic_search", side_effect=search):
        return benchmark(tmp_path, dataset, frozen, mode="rag", k=3, limit=1, client=client, authorize_external=True, **kwargs)


def test_metric_definitions_short_results_and_corpus_coverage(study):
    catalog, _, dataset = study
    q = dataset["questions"][0]
    result = retrieval_metrics(q, [hit(catalog.chunks[1]), hit(catalog.chunks[0])], catalog, 3)
    assert result == {"precision_at_k": pytest.approx(1/3), "recall_at_k": 0.5, "mrr_at_k": 0.5,
                      "document_coverage": 0.5, "relevant_document_coverage": 0.5}
    assert retrieval_metrics(q, [], catalog, 3)["precision_at_k"] == 0
    assert retrieval_metrics(q, [], catalog, 3)["mrr_at_k"] == 0
    with pytest.raises(ValueError, match="duplicati"):
        retrieval_metrics(q, [hit(catalog.chunks[0])]*2, catalog, 3)


def test_unjudged_is_not_negative_and_unknown_early_rank_blocks_mrr(study):
    catalog, _, dataset = study
    q = dataset["questions"][0]
    q.update(judgments_complete=False, relevant_chunks=q["relevant_chunks"][:1], nonrelevant_chunk_ids=["b"])
    metrics = retrieval_metrics(q, [hit(catalog.chunks[2]), hit(catalog.chunks[0])], catalog, 3)
    assert metrics["precision_at_k"] is None and metrics["recall_at_k"] is None and metrics["mrr_at_k"] is None
    metrics = retrieval_metrics(q, [hit(catalog.chunks[0]), hit(catalog.chunks[2])], catalog, 3)
    assert metrics["mrr_at_k"] == 1


def test_unanswerable_and_empty_corpus_have_undefined_recall(study):
    catalog, _, dataset = study
    q = dataset["questions"][0]
    q.update(answerability="unanswerable", relevant_chunks=[], nonrelevant_chunk_ids=[])
    metrics = retrieval_metrics(q, [hit(catalog.chunks[1])], catalog, 3)
    assert metrics["recall_at_k"] is None and metrics["mrr_at_k"] is None and metrics["precision_at_k"] == 0
    assert retrieval_metrics(q, [], Catalog([], {}, {}), 3)["document_coverage"] is None


@pytest.mark.parametrize("mutation", ["pdf", "page", "unknown", "duplicate", "contradiction", "annotator", "question", "noanswer", "snapshot"])
def test_annotations_are_checked_not_filled_in(study, mutation):
    _, frozen, dataset = study
    q = dataset["questions"][0]
    if mutation == "pdf": q["relevant_chunks"][0]["pdf"] = "inventato.pdf"
    if mutation == "page": q["relevant_chunks"][0]["page"] = 99
    if mutation == "unknown": q["relevant_chunks"][0]["chunk_id"] = "unknown"
    if mutation == "duplicate": dataset["questions"].append(copy.deepcopy(q))
    if mutation == "contradiction": q["nonrelevant_chunk_ids"].append("a")
    if mutation == "annotator": q["annotator"] = ""
    if mutation == "question": q["question"] = ""
    if mutation == "noanswer": q["answerability"] = "unanswerable"
    if mutation == "snapshot": dataset["snapshot_id"] = "obsolete"
    with pytest.raises(ValueError): validate_dataset(dataset, frozen)


def test_snapshot_hash_and_empty_template(study):
    _, frozen, _ = study
    template = dataset_template(frozen["snapshot_id"])
    assert template["questions"][0]["answerability"] is None and template["questions"][0]["relevant_chunks"] == []
    with pytest.raises(ValueError, match="domanda"): validate_dataset(template, frozen)
    frozen["chunks"][0]["text"] += " modificato"
    with pytest.raises(ValueError, match="hash"): validate_snapshot(frozen)


def test_benchmark_measures_separate_phases_model_and_actual_calls(tmp_path, study):
    run = run_mock(tmp_path, study)
    record = run["records"][0]
    assert run["origin"] == "simulated" and record["status"] == "ok"
    assert record["response_state"] == "answered"
    assert [e["phase"] for e in record["api_events"]] == ["query_embedding", "generation"]
    assert record["api_events"][1]["model"] == "configured-test-model"
    assert record["total_seconds"] >= record["retrieval_seconds"] + record["generation_seconds"]
    assert all(e["http_status"] is None for e in record["api_events"])  # Nessun 200 inventato.
    assert "test-key-never-log" not in json.dumps(run)


def test_retry_attempts_http_errors_and_failed_latency_are_counted(tmp_path, study):
    client = mock_client()
    response = client.models.embed_content.return_value
    client.models.embed_content.side_effect = [errors.APIError(503, {"error": {"message": "secret-payload"}}), response]
    from edicola.embeddings import GeminiEmbedder
    with patch("edicola.evaluation.GeminiEmbedder", side_effect=lambda key, **kw: GeminiEmbedder(key, sleep=lambda _: None, **kw)):
        run = run_mock(tmp_path, study, client=client)
    assert len(run["records"][0]["api_events"]) == 3
    assert run["records"][0]["api_events"][0]["http_status"] == 503
    client = mock_client()
    client.models.generate_content.side_effect = errors.APIError(400, {"error": {"message": "secret-payload"}})
    run = run_mock(tmp_path, study, client=client)
    record = run["records"][0]
    assert record["error_phase"] == "generation" and record["retrieval_status"] == "ok"
    rows = score_run(study[2], study[1], run, study[0])
    assert any(r["metric"] == "failed_generation_seconds" and r["value"] >= 0 for r in rows)
    assert next(r["value"] for r in rows if r["metric"] == "http_errors") == 1
    assert "secret-payload" not in json.dumps(run)


def test_consent_stale_snapshot_and_limit_checked_before_api(tmp_path, study):
    catalog, frozen, dataset = study
    client = mock_client()
    with pytest.raises(ValueError, match="authorize"):
        benchmark(tmp_path, dataset, frozen, mode="rag", k=3, limit=1, client=client)
    with pytest.raises(ValueError, match="limite"):
        benchmark(tmp_path, dataset, frozen, mode="rag", k=3, limit=0, client=client, authorize_external=True)
    changed = copy.deepcopy(catalog)
    changed.chunks.clear()
    with patch("edicola.evaluation.read_catalog", return_value=changed), pytest.raises(ValueError, match="cambiato"):
        benchmark(tmp_path, dataset, frozen, mode="rag", k=3, limit=1, client=client, authorize_external=True)
    client.models.embed_content.assert_not_called()
    client.models.generate_content.assert_not_called()


def test_citation_presence_is_not_fact_verification_and_invalid_is_not_abstention(tmp_path, study):
    catalog, frozen, dataset = study
    source = sources_from_hits([hit(catalog.chunks[0])])
    bad = json.dumps({"sufficient": True, "claims": [{"text": "Affermazione", "evidence": [{"source_id": "S999", "quote": source[0].text}]}]})
    assert rag_assessment(bad, source)[0] == "validation_failed"
    assert rag_assessment(json.dumps({"sufficient": False, "claims": []}), source)[0] == "model_abstention"
    assert rag_assessment(None, source)[0] == "not_run"
    run = run_mock(tmp_path, study)
    run["records"][0]["raw_response"] = bad
    rows = score_run(dataset, frozen, run, catalog)
    assert next(r["value"] for r in rows if r["metric"] == "citation_technical_pass") == 0
    assert next(r["value"] for r in rows if r["metric"] == "answerability_decision_correct") is None
    assert not any("factual_accuracy" in r["metric"] for r in rows)


def test_statistics_do_not_mix_origins_or_fill_missing_and_p95_needs_20():
    rows = [{"origin": "simulated", "metric": "time", "unit": "seconds", "value": v} for v in range(1, 21)]
    rows += [{"origin": "simulated", "metric": "time", "unit": "seconds", "value": None},
             {"origin": "real", "metric": "time", "unit": "seconds", "value": 100}]
    result = {s["origin"]: s for s in summarize(rows)}
    assert result["simulated"]["mean"] == result["simulated"]["median"] == 10.5
    assert result["simulated"]["p95"] == pytest.approx(19.05) and result["simulated"]["missing"] == 1
    assert result["real"]["p95"] is None and result["real"]["mean"] == 100


def test_personalization_profiles_feedback_and_reproducible_local_results(study):
    _, frozen, _ = study
    profiles = {"schema_version": 1, "profiles": [asdict(Profile(user_id="trasporti", interests=["trasporti", "scuola"], feedback={"scuola": 1})),
                                                  asdict(Profile(user_id="scuola", interests=["scuola"]))]}
    experiment, rows = personalization_experiment(frozen, profiles)
    assert experiment["origin"] == "simulated"
    assert experiment["records"][0]["before"][0]["chunk"]["id"] != experiment["records"][0]["after"][0]["chunk"]["id"]
    assert any(r["metric"] == "feedback_rank_change_fraction" and r["value"] > 0 for r in rows)
    assert any(r["metric"] == "between_profiles_jaccard_distance" and r["value"] > 0 for r in rows)
    assert all(r["value"] == 0 for r in rows if r["metric"].startswith("recommendation_duplicate"))
    _, repeated = personalization_experiment(frozen, profiles)
    assert repeated == rows


def test_human_sheets_score_zero_is_valid_but_blank_is_missing(tmp_path):
    rows = review_rows("podcast", "real-product-key", "real")
    path = tmp_path / "review.csv"
    write_csv(path, rows, REVIEW_FIELDS)
    assert all(r["value"] is None for r in read_reviews(path))
    rows[0].update(reviewer="r1", score="0", evidence="PDF A, pagina 2: confronto con la frase del prodotto")
    write_csv(path, rows, REVIEW_FIELDS)
    assert read_reviews(path)[0]["value"] == 0
    rows[0]["score"] = "5"
    write_csv(path, rows, REVIEW_FIELDS)
    with pytest.raises(ValueError, match="Punteggio"): read_reviews(path)


def test_report_csv_charts_missing_and_provenance_no_external_calls(tmp_path, study):
    run = run_mock(tmp_path, study)
    out = tmp_path / "report"
    report_run(out, study[2], study[1], run)
    assert (out / "metrics.csv").is_file() and (out / "summary.csv").is_file()
    assert (out / "metrics.html").is_file() and read_json(out / "metrics.vl.json")["$schema"]
    report = (out / "report.md").read_text(encoding="utf-8")
    assert "simulated" in report
    assert "human:rag:factual_accuracy" not in (out / "metrics.csv").read_text(encoding="utf-8-sig")
    assert "non dimostra accuratezza fattuale" in report and "20 campioni" in report
    reviews = out / "human_review.csv"
    original = reviews.read_bytes()
    report_run(out, study[2], study[1], run)
    assert reviews.read_bytes() == original
    assert "test-key-never-log" not in report


def test_cli_init_validation_and_offline_score(tmp_path, study, capsys):
    _, frozen, dataset = study
    snap, data = tmp_path / "snapshot.json", tmp_path / "dataset.json"
    write_json(snap, frozen)
    write_json(data, dataset)
    assert main(["init", "--snapshot", str(snap), "--out", str(tmp_path / "templates")]) == 0
    template = read_json(tmp_path / "templates/dataset.json")
    assert template["questions"][0]["question"] == "" and template["questions"][0]["relevant_chunks"] == []
    assert main(["validate", "--snapshot", str(snap), "--dataset", str(data)]) == 0
    assert main(["benchmark", "--snapshot", str(snap), "--dataset", str(data), "--out", str(tmp_path / "forbidden"), "--mode", "rag", "--limit", "1"]) == 1
    assert not (tmp_path / "forbidden").exists()
    run = run_mock(tmp_path, study)
    path = tmp_path / "run.json"
    write_json(path, run)
    assert main(["score", "--snapshot", str(snap), "--dataset", str(data), "--run", str(path), "--out", str(tmp_path / "offline")]) == 0
    assert (tmp_path / "offline/report.md").exists()


def test_unanswerable_is_scored_only_for_valid_decisions(tmp_path, study):
    catalog, frozen, dataset = study
    dataset["questions"][0].update(answerability="unanswerable", relevant_chunks=[], nonrelevant_chunk_ids=["a", "b", "c", "d"])
    client = mock_client()
    client.models.generate_content.side_effect = None
    client.models.generate_content.return_value = SimpleNamespace(text=json.dumps({"sufficient": False, "claims": []}), candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)])
    run = run_mock(tmp_path, study, client=client)
    rows = score_run(dataset, frozen, run, catalog)
    assert next(r["value"] for r in rows if r["metric"] == "answerability_decision_correct") == 1
    record = run["records"][0]
    record["raw_response"] = ""
    rows = score_run(dataset, frozen, run, catalog)
    assert next(r["value"] for r in rows if r["metric"] == "answerability_decision_correct") is None
    record.update(status="error", retrieval_status="error", retrieved=[], raw_response=None)
    rows = score_run(dataset, frozen, run, catalog)
    assert next(r["value"] for r in rows if r["metric"] == "global_document_coverage") is None
    assert next(r["value"] for r in rows if r["metric"] == "precision_at_k") is None


def test_imported_runs_cannot_change_snapshot_labels_or_claim_real_from_simulated(tmp_path, study):
    run = run_mock(tmp_path, study)
    run["origin"] = "real"
    with pytest.raises(ValueError, match="simulato"):
        score_run(study[2], study[1], run, study[0])
    run["origin"] = "simulated"
    run["records"][0]["retrieved"][0]["page"] = 999
    with pytest.raises(ValueError, match="riferimento"):
        score_run(study[2], study[1], run, study[0])


def test_human_results_are_joined_to_exact_run_and_missing_scores_stay_missing(tmp_path, study):
    run = run_mock(tmp_path, study)
    report_run(tmp_path / "report", study[2], study[1], run)
    sheet = tmp_path / "report/human_review.csv"
    rows = review_rows("rag", "q01#1", "simulated", digest(run))
    rows[0].update(score="3", reviewer="valutatore-test", evidence="Confronto sintetico con pagina 1 di giornale-0.pdf")
    write_csv(sheet, rows, REVIEW_FIELDS)
    summary = report_run(tmp_path / "scored", study[2], study[1], run, sheet)
    accuracy = next(s for s in summary if s["metric"] == "human:rag:factual_accuracy")
    assert accuracy["n"] == 1 and accuracy["mean"] == 3 and accuracy["p95"] is None
    faithfulness = next(s for s in summary if s["metric"] == "human:rag:faithfulness")
    assert faithfulness["n"] == 0 and faithfulness["mean"] is None
    rows[0]["run_id"] = "another-run"
    write_csv(sheet, rows, REVIEW_FIELDS)
    with pytest.raises(ValueError, match="campione"):
        report_run(tmp_path / "bad", study[2], study[1], run, sheet)


def test_cli_product_review_has_all_audio_criteria_and_no_assigned_scores(tmp_path):
    out = tmp_path / "podcast"
    assert main(["prepare-review", "--kind", "podcast", "--item-id", "actual-cache-key-provided-by-user", "--origin", "real", "--out", str(out)]) == 0
    rubric = read_json(out / "rubrics.json")
    assert "audio_quality" in rubric["products"]["podcast"]
    assert all(r["value"] is None for r in read_reviews(out / "human_review.csv"))
    assert main(["reviews", "--sheet", str(out / "human_review.csv"), "--out", str(tmp_path / "empty-report")]) == 0
    assert (tmp_path / "empty-report/metrics.html").exists()


def test_benchmark_reuses_actual_search_and_preserves_sqlite_and_vectors(tmp_path):
    from edicola.archive import read_active_chunks
    from edicola.chunking import prepare_documents
    from edicola.editorial_selection import read_catalog
    from edicola.indexing import apply_plan, plan_index
    from edicola.ingestion import ingest_directory
    from edicola.vectorstore import open_collection
    from test_ingestion import make_pdf
    incoming = tmp_path / "data/incoming"
    incoming.mkdir(parents=True)
    (incoming / "sintetico.pdf").write_bytes(make_pdf(("Una notizia sintetica sui trasporti. " * 120, "Seconda pagina.")))
    registry = tmp_path / "data/archive.sqlite3"
    prepare_documents(ingest_directory(incoming, registry), registry)
    chunks, _ = read_active_chunks(registry, incoming)
    collection = open_collection(tmp_path / "data/chroma", create=True)
    embedder = Mock(embed=Mock(return_value=[1.0] + [0.0]*767))
    apply_plan(plan_index(chunks, collection), collection, embedder, 2)
    catalog = read_catalog(tmp_path)
    frozen = snapshot(catalog, "simulated")
    dataset = dataset_template(frozen["snapshot_id"])
    dataset["questions"][0].update(question="Domanda del test sintetico sui trasporti")
    before = collection.get(include=["documents", "metadatas", "embeddings"])
    sqlite_before = registry.read_bytes()
    with patch("edicola.ingestion.extract_pdf", side_effect=AssertionError("Estrazione vietata")), patch(
        "edicola.chunking.build_chunks", side_effect=AssertionError("Chunking vietato")):
        run = benchmark(tmp_path, dataset, frozen, mode="rag", k=3, limit=1,
                        authorize_external=True, client=mock_client())
    assert run["records"][0]["status"] == "ok"
    assert len(run["records"][0]["api_events"]) == 2
    assert len(run["records"][0]["retrieved"]) == 2
    assert run["records"][0]["response_state"] == "answered"
    after = collection.get(include=["documents", "metadatas", "embeddings"])
    assert after["ids"] == before["ids"] and after["documents"] == before["documents"]
    assert after["metadatas"] == before["metadatas"]
    assert (after["embeddings"] == before["embeddings"]).all()
    assert registry.read_bytes() == sqlite_before


def test_cli_local_profile_comparison_without_persisting_profiles(tmp_path, study):
    frozen = tmp_path / "snapshot.json"
    profiles = tmp_path / "profiles.json"
    write_json(frozen, study[1])
    write_json(profiles, {"schema_version": 1, "profiles": [asdict(Profile(user_id="a", interests=["trasporti"])),
                                                           asdict(Profile(user_id="b", interests=["scuola"]))]})
    assert main(["personalization", "--snapshot", str(frozen), "--profiles", str(profiles), "--out", str(tmp_path / "comparison")]) == 0
    assert read_json(tmp_path / "comparison/personalization.json")["origin"] == "simulated"
    assert not (tmp_path / "data/profiles.sqlite3").exists()
