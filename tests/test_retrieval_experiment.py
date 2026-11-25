import copy

import pytest

from edicola.archive import IndexChunk
from edicola.editorial_selection import Catalog
from edicola.evaluation_data import dataset_template, snapshot
from edicola.retrieval import search
from edicola.retrieval.experimental import (
    candidates_from_vectors,
    compare_retrieval_runs,
    question_ids_for_split,
    rank_candidates,
    run_retrieval_experiment,
)
from edicola.retrieval.reranker import LocalOnnxCrossEncoder
from evaluation.llm_relevance_judge import select_run_records


def _hit(identity, text, distance, filename="edition-a.pdf", pdf_sha="a" * 64):
    return {
        "id": identity,
        "text": text,
        "filename": filename,
        "page": 1,
        "pdf_sha256": pdf_sha,
        "distance": distance,
    }


def test_semantic_strategy_preserves_original_distance_order_and_k3():
    candidates = [
        _hit("c", "Un passaggio terzo con contenuto generale.", 0.3),
        _hit("a", "Un passaggio primo con contenuto generale.", 0.1),
        _hit("b", "Un passaggio secondo con contenuto generale.", 0.2),
        _hit("d", "Un passaggio quarto con contenuto generale.", 0.4),
    ]
    original = copy.deepcopy(candidates)

    selected = rank_candidates(
        "argomento della domanda",
        candidates,
        strategy="cosine_all",
        pool_size=3,
    )

    assert [item["id"] for item in selected] == ["a", "b", "c"]
    assert candidates == original


def test_hybrid_rrf_can_promote_a_lexical_candidate_from_broader_pool():
    candidates = [
        _hit("a", "Informazione generale non collegata.", 0.01),
        _hit("b", "Un contenuto in parte relativo ai trasporti.", 0.02),
        _hit("c", "Un altro passaggio non specifico.", 0.03),
        _hit("d", "Trasporti TUA, tariffe abbonamenti pendolari.", 0.2),
        _hit("e", "Tariffe TUA e abbonamenti dei pendolari.", 0.3),
    ]

    selected = rank_candidates(
        "tariffe abbonamenti TUA pendolari",
        candidates,
        strategy="hybrid_rrf",
        pool_size=3,
    )

    assert len(selected) == 3
    assert "d" in {item["id"] for item in selected}


def test_cross_encoder_reranks_exactly_ten_candidates_and_preserves_hits():
    candidates = [
        _hit(f"c{index}", f"Chunk testuale {index}.", index / 100)
        for index in range(10)
    ]
    original = copy.deepcopy(candidates)
    scores = [float(index) for index in range(10)]

    selected = rank_candidates(
        "Domanda sui trasporti?",
        candidates,
        strategy="cross_encoder_rerank",
        pool_size=10,
        reranker_scores=scores,
    )

    assert [item["id"] for item in selected] == ["c9", "c8", "c7"]
    assert candidates == original


def test_cross_encoder_rejects_missing_or_invalid_scores():
    candidates = [_hit("a", "Testo del passaggio.", 0.1)]

    with pytest.raises(ValueError, match="punteggio reranker"):
        rank_candidates(
            "Domanda?",
            candidates,
            strategy="cross_encoder_rerank",
            pool_size=10,
            reranker_scores=[],
        )
    with pytest.raises(ValueError, match="Punteggi reranker non validi"):
        rank_candidates(
            "Domanda?",
            candidates,
            strategy="cross_encoder_rerank",
            pool_size=10,
            reranker_scores=[float("nan")],
        )


def test_local_onnx_reranker_uses_mocked_cpu_runtime_without_network(
    tmp_path, monkeypatch
):
    import sys
    from types import SimpleNamespace

    import numpy as np

    model_dir = tmp_path / "model"
    (model_dir / "onnx").mkdir(parents=True)
    (model_dir / "tokenizer.json").write_text("{}", encoding="utf-8")
    (model_dir / "onnx" / "model.onnx").write_bytes(b"mock")

    class MockEncoding:
        ids = [1, 2]
        attention_mask = [1, 1]
        type_ids = [0, 0]

    class MockTokenizer:
        @classmethod
        def from_file(cls, _path):
            return cls()

        def token_to_id(self, token):
            assert token == "<pad>"
            return 1

        def enable_truncation(self, *, max_length):
            assert max_length == 512

        def enable_padding(self, *, pad_id, pad_token):
            assert pad_id == 1
            assert pad_token == "<pad>"

        def encode_batch(self, pairs):
            assert pairs == [("Domanda?", "Passaggio uno."), ("Domanda?", "Passaggio due.")]
            return [MockEncoding(), MockEncoding()]

    class MockSession:
        def __init__(self, _path, *, providers):
            assert providers == ["CPUExecutionProvider"]

        def get_inputs(self):
            return [
                SimpleNamespace(name="input_ids", type="tensor(int64)"),
                SimpleNamespace(name="attention_mask", type="tensor(int64)"),
                SimpleNamespace(name="token_type_ids", type="tensor(int64)"),
            ]

        def run(self, _outputs, inputs):
            assert inputs["input_ids"].shape == (2, 2)
            return [np.asarray([[0.2], [0.8]], dtype=np.float32)]

    monkeypatch.setitem(
        sys.modules, "tokenizers", SimpleNamespace(Tokenizer=MockTokenizer)
    )
    monkeypatch.setitem(
        sys.modules,
        "onnxruntime",
        SimpleNamespace(InferenceSession=MockSession),
    )
    reranker = LocalOnnxCrossEncoder(model_dir)

    assert reranker.predict_scores(
        "Domanda?", [{"text": "Passaggio uno."}, {"text": "Passaggio due."}]
    ) == pytest.approx([0.2, 0.8])


def test_deduplication_is_limited_to_near_duplicates_in_same_edition():
    duplicated = "La regione finanzia interventi di trasporto pubblico e nuove corse per i pendolari in Abruzzo."
    candidates = [
        _hit("a", duplicated, 0.1, "edition-a.pdf", "a" * 64),
        _hit("b", duplicated, 0.2, "edition-a.pdf", "a" * 64),
        _hit("c", duplicated, 0.3, "edition-b.pdf", "b" * 64),
        _hit("d", "Un fatto completamente diverso relativo a un evento locale.", 0.4, "edition-a.pdf", "a" * 64),
    ]

    selected = rank_candidates(
        "trasporto pubblico nuove corse pendolari",
        candidates,
        strategy="hybrid_rrf_dedup",
        pool_size=4,
    )

    selected_ids = [item["id"] for item in selected]
    assert "a" in selected_ids
    assert "b" not in selected_ids
    assert "c" in selected_ids


def test_candidate_scoring_uses_all_current_vectors_without_mutating_chunks():
    chunks = [
        IndexChunk("a", "Prima fonte sui trasporti regionali.", {
            "filename": "edition-a.pdf", "page": 1, "pdf_sha256": "a" * 64,
        }),
        IndexChunk("b", "Seconda fonte sulle tariffe.", {
            "filename": "edition-b.pdf", "page": 2, "pdf_sha256": "b" * 64,
        }),
    ]
    vectors = {"a": [1.0, 0.0], "b": [0.0, 1.0]}
    original = copy.deepcopy(chunks)

    hits = candidates_from_vectors([1.0, 0.0], chunks, vectors)

    assert [item["id"] for item in hits] == ["a", "b"]
    assert hits[0]["distance"] == pytest.approx(0.0)
    assert hits[1]["distance"] == pytest.approx(1.0)
    assert chunks == original


def test_experiment_requires_explicit_authorization_before_embedding():
    chunks = [
        IndexChunk("a", "Testo fonte sufficiente per la domanda sintetica.", {
            "filename": "edition-a.pdf", "page": 1, "pdf_sha256": "a" * 64,
        })
    ]
    catalog = Catalog(chunks, {"a": [1.0, 0.0]}, {})
    frozen = snapshot(catalog, "simulated")
    dataset = dataset_template(frozen["snapshot_id"])
    dataset["questions"] = [{
        "id": "GT-001",
        "question": "Domanda sintetica?",
        "annotator": "",
        "answerability": None,
        "judgments_complete": False,
        "relevant_chunks": [],
        "nonrelevant_chunk_ids": [],
        "expected_points": [],
        "reference_answer": "",
        "annotation_notes": "",
    }]
    calls = []

    with pytest.raises(ValueError, match="autorizzare"):
        run_retrieval_experiment(
            dataset,
            frozen,
            catalog,
            strategy="cosine_all",
            question_ids=["GT-001"],
            embedder_factory=lambda _events: calls.append("called"),
            authorize_external=False,
        )

    assert calls == []


def test_experimental_module_does_not_replace_application_search():
    original_search = search.semantic_search

    from edicola.retrieval import experimental

    assert experimental.rank_candidates is not original_search
    assert search.semantic_search is original_search


def test_development_and_holdout_question_sets_are_disjoint_and_complete():
    development = question_ids_for_split("development")
    holdout = question_ids_for_split("holdout")

    assert len(development) == 50
    assert len(holdout) == 100
    assert set(development).isdisjoint(holdout)
    assert development[0] == "GT-001" and development[-1] == "GT-050"
    assert holdout[0] == "GT-051" and holdout[-1] == "GT-150"
    assert question_ids_for_split("all") == development + holdout


def test_relevance_judge_start_slices_a_150_question_run():
    records = [{"question_id": f"GT-{number:03d}"} for number in range(1, 151)]

    assert select_run_records(records, 0, 100)[-1]["question_id"] == "GT-100"
    assert select_run_records(records, 100, 100)[0]["question_id"] == "GT-101"
    assert len(select_run_records(records, 100, 100)) == 50
    with pytest.raises(ValueError, match="Intervallo"):
        select_run_records(records, 150, 100)


def test_experiment_run_uses_mock_embedding_and_returns_only_top_three():
    chunks = [
        IndexChunk(
            f"chunk-{index}",
            f"Passaggio di prova numero {index} sui trasporti regionali.",
            {
                "filename": f"edition-{index}.pdf",
                "page": 1,
                "pdf_sha256": f"{index:064x}",
            },
        )
        for index in range(4)
    ]
    vectors = {
        chunk.id: [1.0, float(index)]
        for index, chunk in enumerate(chunks)
    }
    catalog = Catalog(chunks, vectors, {})
    frozen = snapshot(catalog, "simulated")
    dataset = dataset_template(frozen["snapshot_id"])
    dataset["questions"] = [{
        "id": "GT-001",
        "question": "Quali trasporti regionali?",
        "annotator": "",
        "answerability": None,
        "judgments_complete": False,
        "relevant_chunks": [],
        "nonrelevant_chunk_ids": [],
        "expected_points": [],
        "reference_answer": "",
        "annotation_notes": "",
    }]

    class MockEmbedder:
        def embed(self, _prompt):
            return [1.0, 0.0]

    run = run_retrieval_experiment(
        dataset,
        frozen,
        catalog,
        strategy="cosine_all",
        question_ids=["GT-001"],
        embedder_factory=lambda _events: MockEmbedder(),
        authorize_external=True,
    )

    assert run["mode"] == "retrieval"
    assert run["top_k"] == 3
    assert run["configuration"]["generation"] == "non eseguita"
    assert len(run["records"][0]["retrieved"]) == 3
    assert run["records"][0]["candidate_count"] == 4


def test_production_baseline_delegates_to_existing_search_with_k3(monkeypatch):
    from edicola.retrieval import experimental

    chunks = [
        IndexChunk("a", "Testo fonte sufficiente per la domanda sintetica.", {
            "filename": "edition-a.pdf", "page": 1, "pdf_sha256": "a" * 64,
        })
    ]
    catalog = Catalog(chunks, {"a": [1.0, 0.0]}, {})
    frozen = snapshot(catalog, "simulated")
    dataset = dataset_template(frozen["snapshot_id"])
    dataset["questions"] = [{
        "id": "GT-001",
        "question": "Domanda sintetica?",
        "annotator": "",
        "answerability": None,
        "judgments_complete": False,
        "relevant_chunks": [],
        "nonrelevant_chunk_ids": [],
        "expected_points": [],
        "reference_answer": "",
        "annotation_notes": "",
    }]
    calls = []

    class MockEmbedder:
        def embed(self, _prompt):
            return [1.0, 0.0]

    def production_search(_question, **kwargs):
        calls.append(kwargs)
        kwargs["embedder"].embed("mock production query")
        return [_hit("a", chunks[0].text, 0.0)]

    original_search = search.semantic_search
    monkeypatch.setattr(experimental, "semantic_search", production_search)
    run = run_retrieval_experiment(
        dataset,
        frozen,
        catalog,
        strategy="production_baseline",
        question_ids=["GT-001"],
        embedder_factory=lambda _events: MockEmbedder(),
        authorize_external=True,
    )

    assert len(run["records"][0]["retrieved"]) == 1
    assert calls[0]["corpus_wide"] is True
    assert calls[0]["preserve_relevance_order"] is True
    assert calls[0]["top_k"] == 3
    assert search.semantic_search is original_search


def test_cross_encoder_experiment_uses_top_ten_search_hits_and_returns_top_three(
    monkeypatch,
):
    from edicola.retrieval import experimental

    chunks = [
        IndexChunk(
            f"chunk-{index}",
            f"Testo chunk {index} sui trasporti regionali.",
            {
                "filename": f"edition-{index}.pdf",
                "page": 1,
                "pdf_sha256": f"{index:064x}",
            },
        )
        for index in range(12)
    ]
    catalog = Catalog(
        chunks,
        {chunk.id: [1.0, float(index)] for index, chunk in enumerate(chunks)},
        {},
    )
    frozen = snapshot(catalog, "simulated")
    dataset = dataset_template(frozen["snapshot_id"])
    dataset["questions"] = [{
        "id": "GT-001",
        "question": "Quali trasporti regionali?",
        "annotator": "",
        "answerability": None,
        "judgments_complete": False,
        "relevant_chunks": [],
        "nonrelevant_chunk_ids": [],
        "expected_points": [],
        "reference_answer": "",
        "annotation_notes": "",
    }]
    calls = []

    class MockEmbedder:
        def embed(self, _prompt):
            return [1.0, 0.0]

    class MockReranker:
        def predict_scores(self, question, candidates):
            calls.append((question, [hit["id"] for hit in candidates]))
            return [float(index) for index in range(len(candidates))]

    def production_search(_question, **kwargs):
        assert kwargs["top_k"] == 3
        assert kwargs["corpus_wide"] is True
        assert kwargs["preserve_relevance_order"] is True
        kwargs["embedder"].embed("mock production query")
        return [
            {
                "id": chunk.id,
                "text": chunk.text,
                **chunk.metadata,
                "distance": index / 100,
            }
            for index, chunk in enumerate(chunks)
        ]

    monkeypatch.setattr(experimental, "semantic_search", production_search)
    run = run_retrieval_experiment(
        dataset,
        frozen,
        catalog,
        strategy="cross_encoder_rerank",
        question_ids=["GT-001"],
        embedder_factory=lambda _events: MockEmbedder(),
        authorize_external=True,
        reranker=MockReranker(),
    )

    record = run["records"][0]
    assert record["retrieval_status"] == "ok"
    assert calls == [("Quali trasporti regionali?", [f"chunk-{i}" for i in range(10)])]
    assert [hit["id"] for hit in record["retrieved"]] == [
        "chunk-9", "chunk-8", "chunk-7",
    ]
    assert [item["chunk_id"] for item in record["rerank_candidates"]] == [
        f"chunk-{i}" for i in range(10)
    ]
    assert run["top_k"] == 3
    assert run["configuration"]["candidate_pool_size"] == 10
    assert run["configuration"]["reranker"]["runtime"] == (
        "onnxruntime CPUExecutionProvider"
    )


def test_offline_comparison_requires_fresh_hash_linked_judgments():
    from edicola.evaluation_data import digest

    chunks = [
        IndexChunk(
            f"chunk-{index}",
            f"Prova letterale del chunk {index}.",
            {
                "filename": f"edition-{index}.pdf",
                "page": 1,
                "pdf_sha256": f"{index:064x}",
            },
        )
        for index in range(3)
    ]
    catalog = Catalog(
        chunks,
        {chunk.id: [1.0, float(index)] for index, chunk in enumerate(chunks)},
        {},
    )
    frozen = snapshot(catalog, "simulated")
    dataset = dataset_template(frozen["snapshot_id"])
    dataset["questions"] = [
        {
            "id": f"GT-{number:03d}",
            "question": f"Domanda {number}?",
            "annotator": "",
            "answerability": None,
            "judgments_complete": False,
            "relevant_chunks": [],
            "nonrelevant_chunk_ids": [],
            "expected_points": [],
            "reference_answer": "",
            "annotation_notes": "",
        }
        for number in range(1, 151)
    ]

    def make_run(labels, strategy):
        records = []
        judgments = {}
        for number in range(1, 151):
            hits = [
                {
                    "id": chunk.id,
                    "text": chunk.text,
                    **chunk.metadata,
                    "distance": index / 10,
                }
                for index, chunk in enumerate(chunks)
            ]
            records.append({
                "question_id": f"GT-{number:03d}",
                "repeat": 1,
                "status": "ok",
                "retrieval_status": "ok",
                "retrieved": hits,
                "retrieval_seconds": 0.1,
                "generation_seconds": None,
                "total_seconds": 0.1,
                "api_events": [],
            })
            judgments[f"GT-{number:03d}#1"] = {
                "status": "judged",
                "judgments": [
                    {
                        "chunk_id": hit["id"],
                        "label": label,
                        "quote": hit["text"] if label == "R" else "",
                        "reason": "Giudizio motivato sul chunk disponibile.",
                    }
                    for hit, label in zip(hits, labels, strict=True)
                ],
            }
        run = {
            "schema_version": 1,
            "origin": "simulated",
            "mode": "retrieval",
            "top_k": 3,
            "snapshot_id": frozen["snapshot_id"],
            "dataset_id": digest(dataset),
            "configuration": {"retrieval_strategy": strategy},
            "records": records,
        }
        judge = {
            "provider": "groq",
            "run_sha256": digest(run),
            "snapshot_id": frozen["snapshot_id"],
            "records": judgments,
        }
        return run, judge

    baseline, baseline_judgments = make_run(["R", "N", "N"], "baseline")
    reranked, reranked_judgments = make_run(["N", "R", "N"], "reranker")
    report = compare_retrieval_runs(
        dataset,
        frozen,
        baseline,
        baseline_judgments,
        reranked,
        reranked_judgments,
    )

    overall = report["metrics"]["all_GT-001..150"]
    assert len(report["per_question"]) == 150
    assert overall["precision_at_3"]["baseline"]["mean"] == pytest.approx(1 / 3)
    assert overall["precision_at_3"]["reranked"]["mean"] == pytest.approx(1 / 3)
    assert overall["mrr_at_3"]["baseline"]["mean"] == pytest.approx(1.0)
    assert overall["mrr_at_3"]["reranked"]["mean"] == pytest.approx(0.5)
    with pytest.raises(ValueError, match="Giudizi Groq non collegati"):
        compare_retrieval_runs(
            dataset,
            frozen,
            baseline,
            baseline_judgments,
            reranked,
            baseline_judgments,
        )
