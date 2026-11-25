"""Retrieval sperimentale isolato dal percorso di ricerca dell'applicazione."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from google import genai
from google.genai import errors, types
import httpx

from edicola.editorial_selection import near_duplicate, read_catalog
from edicola.evaluation_data import (
    dataset_template,
    digest,
    read_json,
    snapshot,
    validate_dataset,
    validate_snapshot,
    write_json,
)
from edicola.retrieval.embeddings import (
    DIMENSIONS,
    MODEL,
    GeminiEmbedder,
    api_key,
    question_prompt,
)
from edicola.retrieval.search import semantic_search


RANKING_STRATEGIES = ("cosine_all", "hybrid_rrf", "hybrid_rrf_dedup")
STRATEGIES = ("production_baseline", *RANKING_STRATEGIES)
RRF_CONSTANT = 60
DEFAULT_POOL_SIZE = 50
_TOKEN_RE = re.compile(r"[^\W_]+", flags=re.UNICODE)
_STOP_WORDS = frozenset(
    "a ad al allo ai agli all alla alle anche che chi ci cio con cosa da dal "
    "dallo dai dagli dalle degli dei del della delle dello di dove e ed era "
    "gli i il in io la le lo ma nei nel nella nelle nello non o per quale "
    "quali quando quanto quanti questa queste questo questi si sono su tra un "
    "una uno".split()
)


class _MeasuredEmbeddingModels:
    def __init__(self, client, events):
        self.client = client
        self.events = events

    def embed_content(self, **kwargs):
        event = {
            "phase": "query_embedding",
            "model": kwargs["model"],
            "http_status": None,
            "outcome": "error",
            "error_category": None,
        }
        started = time.perf_counter()
        try:
            response = self.client.models.embed_content(**kwargs)
            event["outcome"] = "ok"
            return response
        except errors.APIError as exc:
            event["http_status"] = exc.code if type(exc.code) is int else None
            event["error_category"] = "http"
            raise
        except (httpx.TransportError, ConnectionError, TimeoutError, OSError):
            event["error_category"] = "transport"
            raise
        except Exception:
            event["error_category"] = "sdk_or_local"
            raise
        finally:
            event["seconds"] = time.perf_counter() - started
            self.events.append(event)


def _tokens(text: str) -> list[str]:
    return [
        token
        for token in _TOKEN_RE.findall(text.casefold())
        if len(token) > 1 and token not in _STOP_WORDS
    ]


def _bm25_scores(query: str, candidates: list[dict]) -> dict[str, float]:
    query_terms = set(_tokens(query))
    if not candidates or not query_terms:
        return {candidate["id"]: 0.0 for candidate in candidates}

    documents = [_tokens(candidate["text"]) for candidate in candidates]
    average_length = sum(map(len, documents)) / len(documents) or 1.0
    document_frequency = Counter(
        term for tokens in documents for term in set(tokens)
    )
    scores = {}
    for candidate, tokens in zip(candidates, documents, strict=True):
        counts = Counter(tokens)
        score = 0.0
        for term in query_terms:
            frequency = counts[term]
            if not frequency:
                continue
            df = document_frequency[term]
            inverse_frequency = math.log(
                1 + (len(documents) - df + 0.5) / (df + 0.5)
            )
            denominator = frequency + 1.5 * (
                1 - 0.75 + 0.75 * len(tokens) / average_length
            )
            score += inverse_frequency * frequency * 2.5 / denominator
        scores[candidate["id"]] = score
    return scores


def candidates_from_vectors(query_vector, chunks, vectors) -> list[dict]:
    """Costruisce hits ordinati semanticamente da tutti i vettori correnti."""
    query = np.asarray(query_vector, dtype=float)
    query_norm = np.linalg.norm(query)
    if query.ndim != 1 or not query_norm or not np.isfinite(query).all():
        raise ValueError("Embedding della domanda non valido.")

    if set(vectors) != {chunk.id for chunk in chunks}:
        raise ValueError("I vettori non corrispondono esattamente ai chunk correnti.")

    candidates = []
    for chunk in chunks:
        vector = np.asarray(vectors[chunk.id], dtype=float)
        norm = np.linalg.norm(vector)
        if (
            vector.shape != query.shape
            or not norm
            or not np.isfinite(vector).all()
        ):
            raise ValueError("Vettore del corpus non valido.")
        distance = 1 - float(np.clip(vector @ query / (norm * query_norm), -1, 1))
        candidates.append(
            {
                "id": chunk.id,
                "text": chunk.text,
                **chunk.metadata,
                "distance": distance,
            }
        )
    return sorted(candidates, key=lambda hit: (hit["distance"], hit["id"]))


def rank_candidates(
    question: str,
    candidates: list[dict],
    *,
    strategy: str,
    top_k: int = 3,
    pool_size: int = DEFAULT_POOL_SIZE,
) -> list[dict]:
    """Reranking deterministico; conserva i chunk originali senza modificarli."""
    if strategy not in RANKING_STRATEGIES or top_k != 3:
        raise ValueError("Strategia non valida: la valutazione finale richiede K=3.")
    if type(pool_size) is not int or pool_size < top_k:
        raise ValueError("Il candidate pool deve essere un intero >= 3.")
    if not question.strip():
        raise ValueError("La domanda non può essere vuota.")

    by_id = {}
    for hit in candidates:
        identity = hit.get("id")
        distance = hit.get("distance")
        if (
            not isinstance(identity, str)
            or identity in by_id
            or not isinstance(hit.get("text"), str)
            or not isinstance(hit.get("filename"), str)
            or type(distance) not in (int, float)
            or not math.isfinite(distance)
        ):
            raise ValueError("Candidate pool con chunk duplicati o non validi.")
        by_id[identity] = hit

    semantic = sorted(
        candidates, key=lambda hit: (hit["distance"], hit["id"])
    )
    if strategy == "cosine_all":
        return semantic[:top_k]

    lexical_scores = _bm25_scores(question, candidates)
    lexical = sorted(
        candidates,
        key=lambda hit: (-lexical_scores[hit["id"]], hit["id"]),
    )
    semantic_pool = semantic[:pool_size]
    lexical_pool = [
        hit
        for hit in lexical
        if lexical_scores[hit["id"]] > 0
    ][:pool_size]
    candidate_ids = {
        hit["id"] for hit in (*semantic_pool, *lexical_pool)
    }

    semantic_rank = {
        hit["id"]: rank for rank, hit in enumerate(semantic, start=1)
    }
    lexical_rank = {
        hit["id"]: rank
        for rank, hit in enumerate(
            (hit for hit in lexical if lexical_scores[hit["id"]] > 0),
            start=1,
        )
    }

    def fusion_score(identity):
        return (
            1 / (RRF_CONSTANT + semantic_rank[identity])
            + (
                1 / (RRF_CONSTANT + lexical_rank[identity])
                if identity in lexical_rank
                else 0
            )
        )

    ranked = sorted(
        (by_id[identity] for identity in candidate_ids),
        key=lambda hit: (
            -fusion_score(hit["id"]),
            hit["distance"],
            hit["id"],
        ),
    )
    if strategy == "hybrid_rrf":
        return ranked[:top_k]

    selected = []
    for hit in ranked:
        duplicate_in_same_edition = any(
            hit.get("pdf_sha256") == earlier.get("pdf_sha256")
            and near_duplicate(hit["text"], earlier["text"])
            for earlier in selected
        )
        if not duplicate_in_same_edition:
            selected.append(hit)
        if len(selected) == top_k:
            break
    return selected


def dataset_from_ground_truth(csv_path: Path, snapshot_id: str) -> dict:
    dataset = dataset_template(snapshot_id)
    questions = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            identity = (row.get("ID") or "").strip()
            question = (row.get("Domanda") or "").strip()
            if not identity or not question:
                raise ValueError("Ground Truth con ID o domanda mancante.")
            questions.append(
                {
                    "id": identity,
                    "question": question,
                    "annotator": "",
                    "answerability": None,
                    "judgments_complete": False,
                    "relevant_chunks": [],
                    "nonrelevant_chunk_ids": [],
                    "expected_points": [],
                    "reference_answer": (
                        row.get("Risposta di riferimento") or ""
                    ).strip(),
                    "annotation_notes": (
                        f"Categoria CSV: {row.get('Categoria', '').strip()}; "
                        f"difficoltà: {row.get('Difficoltà', '').strip()}. "
                        "Solo query Ground Truth: nessun giudizio di rilevanza "
                        "è stato trasferito."
                    ),
                }
            )
    expected = [f"GT-{number:03d}" for number in range(1, 151)]
    if [question["id"] for question in questions] != expected:
        raise ValueError("Ground Truth deve contenere GT-001..GT-150 in ordine.")
    dataset["questions"] = questions
    dataset["notes"] = (
        "Adattamento tecnico non modificante del CSV Ground Truth: contiene "
        "solo domande e risposte di riferimento, senza etichette di chunk."
    )
    return dataset


def question_ids_for_split(split: str) -> list[str]:
    if split == "development":
        first, last = 1, 50
    elif split == "holdout":
        first, last = 51, 150
    elif split == "all":
        first, last = 1, 150
    else:
        raise ValueError("Lo split deve essere development, holdout o all.")
    return [f"GT-{number:03d}" for number in range(first, last + 1)]


def run_retrieval_experiment(
    dataset,
    frozen,
    catalog,
    *,
    strategy: str,
    question_ids: list[str],
    embedder_factory,
    authorize_external: bool,
    pool_size: int = DEFAULT_POOL_SIZE,
    root: Path = Path.cwd(),
    clock=time.perf_counter,
) -> dict:
    """Esegue solo retrieval; i test usano un embedder sintetico iniettato."""
    if not authorize_external:
        raise ValueError("Occorre autorizzare esplicitamente le embedding query.")
    validate_dataset(dataset, frozen)
    catalog_from_snapshot = validate_snapshot(frozen)
    current_snapshot = snapshot(catalog, frozen["origin"])
    if current_snapshot["snapshot_id"] != frozen["snapshot_id"]:
        raise ValueError("Archivio/chunk/vectori diversi dallo snapshot congelato.")
    if (
        strategy not in STRATEGIES
        or type(pool_size) is not int
        or pool_size < 3
        or not question_ids
        or len(set(question_ids)) != len(question_ids)
    ):
        raise ValueError("Parametri sperimentali non validi.")
    questions = {item["id"]: item for item in dataset["questions"]}
    if not set(question_ids) <= questions.keys():
        raise ValueError("Lo split contiene ID assenti dalla Ground Truth.")
    frozen_ids = {chunk.id for chunk in catalog_from_snapshot.chunks}
    if {chunk.id for chunk in catalog.chunks} != frozen_ids:
        raise ValueError("Catalogo retrieval diverso dallo snapshot.")

    records = []
    for identity in question_ids:
        question = questions[identity]
        events = []
        record = {
            "question_id": identity,
            "repeat": 1,
            "status": "error",
            "retrieval_status": "error",
            "retrieved": [],
            "raw_response": None,
            "answer": None,
            "response_state": "not_run",
            "retrieval_seconds": None,
            "generation_seconds": None,
            "total_seconds": None,
            "api_events": events,
            "error_phase": "retrieval",
            "error_type": None,
        }
        started = clock()
        phase_started = clock()
        try:
            embedder = embedder_factory(events)
            if strategy == "production_baseline":
                candidates = semantic_search(
                    question["question"],
                    authorize_external=True,
                    root=root,
                    embedder=embedder,
                    top_k=3,
                    corpus_wide=True,
                    preserve_relevance_order=True,
                )
                hits = candidates[:3]
            else:
                vector = embedder.embed(question_prompt(question["question"]))
                candidates = candidates_from_vectors(
                    vector, catalog.chunks, catalog.vectors
                )
                hits = rank_candidates(
                    question["question"],
                    candidates,
                    strategy=strategy,
                    top_k=3,
                    pool_size=pool_size,
                )
            record.update(
                {
                    "status": "ok",
                    "retrieval_status": "ok",
                    "retrieved": hits,
                    "retrieval_seconds": clock() - phase_started,
                    "error_phase": None,
                    "candidate_count": len(candidates),
                }
            )
        except Exception as exc:
            record["retrieval_seconds"] = clock() - phase_started
            record["error_type"] = type(exc).__name__
        finally:
            record["total_seconds"] = clock() - started
            records.append(record)

    return {
        "schema_version": 1,
        "origin": frozen["origin"],
        "mode": "retrieval",
        "top_k": 3,
        "snapshot_id": frozen["snapshot_id"],
        "dataset_id": digest(dataset),
        "provenance": {
            "utc": datetime.now(timezone.utc).isoformat(),
            "retrieval_module_sha256": digest(
                Path(__file__).read_text(encoding="utf-8")
            ),
        },
        "configuration": {
            "retrieval_strategy": f"experimental_{strategy}_v1",
            "embedding_model": MODEL,
            "dimensions": DIMENSIONS,
            "candidate_pool_size": pool_size,
            "candidate_source": (
                "semantic_search production corpus-wide"
                if strategy == "production_baseline"
                else "tutti i chunk correnti con vettori nello snapshot"
            ),
            "rank_fusion": (
                "semantic_search production corpus-wide"
                if strategy == "production_baseline"
                else (
                    "RRF semantic+BM25, k=60"
                    if strategy != "cosine_all"
                    else "cosine distance"
                )
            ),
            "deduplication": (
                "near-duplicate solo nella stessa edizione; nessun accorpamento"
                if strategy == "hybrid_rrf_dedup"
                else "disattivata"
            ),
            "generation": "non eseguita",
            "external_authorization": True,
            "question_ids": question_ids,
        },
        "records": records,
    }


def _analyze_runs(root: Path) -> tuple[list[dict], list[dict], dict]:
    from evaluation.llm_relevance_judge import calculate_metrics, validate_relevance

    config = (
        ("GT-001..050", "rag_gt50_completo_01"),
        ("GT-051..100", "rag_gt100_parte1_v2"),
        ("GT-101..150", "rag_gt100_parte2_01"),
    )
    with (root / "evaluation/data/Ground_Truth_Edicola_150_domande.csv").open(
        "r", encoding="utf-8-sig", newline=""
    ) as stream:
        categories = {
            row["ID"]: row["Categoria"]
            for row in csv.DictReader(stream)
        }
    analysis_rows, nonrelevant, group_summary = [], [], {}
    for group, run_name in config:
        run = read_json(
            root / f"evaluation/results/{run_name}/run.json"
        )
        judge_path = root / {
            "rag_gt50_completo_01": "evaluation/results/llm_gt50_risposte_v1.json",
            "rag_gt100_parte1_v2": "evaluation/results/llm_gt100_parte1_risposte.json",
            "rag_gt100_parte2_01": "evaluation/results/llm_gt100_parte2_risposte.json",
        }[run_name]
        judge = read_json(judge_path)
        if (
            judge.get("run_sha256") != digest(run)
            or judge.get("snapshot_id") != run.get("snapshot_id")
        ):
            raise ValueError(f"Giudizi Groq non collegati alla run {run_name}.")
        judgments = judge.get("records", {})
        group_data = {
            "run": run_name,
            "n": len(run["records"]),
            "labels": Counter(),
            "per_category": defaultdict(list),
            "category_counts": Counter(),
            "questions_with_n": 0,
            "nonrelevant_chunks": 0,
            "p": [],
            "mrr": [],
            "n_by_rank": Counter(),
            "near_duplicate_pairs": 0,
            "same_pdf_pair_questions": 0,
            "fewer_than_three_editions": 0,
            "edition_counts": Counter(),
        }
        for record in run["records"]:
            identity = record["question_id"]
            hits = record["retrieved"] if record["retrieval_status"] == "ok" else []
            entry = judgments.get(f"{identity}#1", {})
            if entry.get("status") != "judged":
                raise ValueError(f"Giudizio rilevanza mancante per {identity}.")
            checked = validate_relevance(
                json.dumps(
                    {"judgments": entry.get("judgments")},
                    ensure_ascii=False,
                ),
                hits,
            )
            labels = [item["label"] for item in checked]
            group_data["labels"].update(labels)
            precision, mrr = calculate_metrics(labels, run["top_k"])
            if precision is not None:
                group_data["p"].append(precision)
            if mrr is not None:
                group_data["mrr"].append(mrr)
            group_data["per_category"][categories[identity]].append(
                (precision, mrr)
            )
            group_data["category_counts"][categories[identity]] += 1
            if "N" in labels:
                group_data["questions_with_n"] += 1
                group_data["nonrelevant_chunks"] += labels.count("N")
            for rank, (hit, label) in enumerate(
                zip(hits, labels, strict=True), start=1
            ):
                if label == "N":
                    group_data["n_by_rank"][rank] += 1
                    nonrelevant.append(
                        {
                            "coorte": group,
                            "id_domanda": identity,
                            "categoria": categories[identity],
                            "posizione": rank,
                            "pdf": hit["filename"],
                            "pagina": hit["page"],
                            "chunk_id": hit["id"],
                            "estratto": " ".join(hit["text"].split())[:220],
                            "motivazione_groq": next(
                                item["reason"]
                                for item in checked
                                if item["chunk_id"] == hit["id"]
                            ),
                        }
                    )
            distinct_editions = len({h["filename"] for h in hits})
            group_data["edition_counts"][distinct_editions] += 1
            if distinct_editions < 3:
                group_data["fewer_than_three_editions"] += 1
            if distinct_editions < len(hits):
                group_data["same_pdf_pair_questions"] += 1
            for index, first in enumerate(hits):
                for second in hits[index + 1 :]:
                    if near_duplicate(first["text"], second["text"]):
                        group_data["near_duplicate_pairs"] += 1
            analysis_rows.append(
                {
                    "coorte": group,
                    "id_domanda": identity,
                    "categoria": categories[identity],
                    "etichette": "".join(labels),
                    "precision_at_3": precision,
                    "mrr_at_3": mrr,
                }
            )
        group_summary[group] = group_data
    return analysis_rows, nonrelevant, group_summary


def write_offline_analysis(root: Path, output: Path) -> Path:
    """Confronta run e giudizi esistenti senza invocare API."""
    analysis_rows, nonrelevant, groups = _analyze_runs(root)
    snapshot_data = read_json(root / "evaluation/work/snapshot.json")
    exact_groups = defaultdict(list)
    for chunk in snapshot_data["chunks"]:
        normalized = " ".join(_TOKEN_RE.findall(chunk["text"].casefold()))
        exact_groups[normalized].append(chunk)
    duplicates = [items for items in exact_groups.values() if len(items) > 1]
    ordered_groups = list(groups.items())
    near_duplicate_pairs = sum(
        data["near_duplicate_pairs"] for data in groups.values()
    )
    chunk_n_comparison = ", ".join(
        f"{group}: {data['nonrelevant_chunks']} N"
        for group, data in ordered_groups
    )

    lines = [
        "# Analisi offline del retrieval — Ground Truth 150",
        "",
        "Analisi delle tre run originali e dei giudizi Groq AI-silver già "
        "collegati ai rispettivi hash. Nessuna API o benchmark è stato avviato. "
        "Le etichette Groq sono segnali automatici, non annotazioni umane.",
        "",
        "## Risultati per coorte",
        "",
        "| Coorte | N | Precision@3 (N) | MRR@3 (N) | Chunk N | Domande con N | N per posizione 1/2/3 | <3 PDF distinti | PDF ripetuto |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for group, data in groups.items():
        p_n, mrr_n = len(data["p"]), len(data["mrr"])
        lines.append(
            f"| {group} | {data['n']} | "
            f"{statistics.mean(data['p']):.1%} ({p_n}) | "
            f"{statistics.mean(data['mrr']):.3f} ({mrr_n}) | "
            f"{data['nonrelevant_chunks']} | {data['questions_with_n']} | "
            f"{data['n_by_rank'][1]}/{data['n_by_rank'][2]}/{data['n_by_rank'][3]} | "
            f"{data['fewer_than_three_editions']} | "
            f"{data['same_pdf_pair_questions']} |"
        )
    lines.extend(["", "## Risultati per categoria e coorte", ""])
    for group, data in groups.items():
        lines.extend(
            [
                f"### {group}",
                "",
                "| Categoria | Domande giudicate | Precision@3 (N) | MRR@3 (N) |",
                "|---|---:|---:|---:|",
            ]
        )
        for category, values in sorted(data["per_category"].items()):
            p_values = [value[0] for value in values if value[0] is not None]
            mrr_values = [value[1] for value in values if value[1] is not None]
            p_text = (
                f"{statistics.mean(p_values):.1%} ({len(p_values)})"
                if p_values
                else f"n.c. (0/{len(values)})"
            )
            mrr_text = (
                f"{statistics.mean(mrr_values):.3f} ({len(mrr_values)})"
                if mrr_values
                else f"n.c. (0/{len(values)})"
            )
            lines.append(
                f"| {category} | {len(values)} | {p_text} | {mrr_text} |"
            )
    lines.extend(
        [
            "",
            "## Diagnosi osservabile",
            "",
            f"- Chunk classificati N: {chunk_n_comparison}. Il conteggio N "
            "non va confuso con un giudizio fattuale umano.",
            "- La composizione per coorte è diversa: "
            + "; ".join(
                f"{group}: "
                + ", ".join(
                    f"{count} {category}"
                    for category, count in sorted(
                        data["category_counts"].items()
                    )
                )
                for group, data in groups.items()
            )
            + ". Questo rende i confronti grezzi tra gruppi non causali.",
            f"- Nei top-3 delle run sono state trovate {near_duplicate_pairs} "
            "coppie quasi duplicate secondo `near_duplicate`. Il controllo normalizzato del corpus "
            f"trova {sum(len(group) - 1 for group in duplicates)} chunk "
            "eccedenti con sequenza di token identica dopo normalizzazione, in "
            f"{len(duplicates)} gruppo/i; tutti nella stessa edizione.",
            "- Il retrieval baseline è `corpus_wide_ranked_top_k`: il ranking "
            "usa cosine e un contributo lessicale limitato con filtri di "
            "rilevanza; la valutazione conserva fino ai primi tre (una domanda "
            "GT-001..050 ha solo due hit). La tabella separa i casi con meno "
            "di tre PDF distinti dai casi con PDF ripetuto: meno di tre fonti "
            "non è di per sé un errore, soprattutto per i quesiti multi-documento "
            "o quando sono disponibili meno risultati.",
            "- I numeri non dimostrano che l'ordinamento sia la sola causa: "
            "non esistono giudizi esaustivi sugli altri 2606 chunk. Per questo "
            "il reranking e l'hybrid sono esperimenti da giudicare nuovamente, "
            "non correzioni già dimostrate.",
            "",
            "## Domande con chunk N",
            "",
            "Gli estratti e le motivazioni sono quelli registrati nei giudizi "
            "Groq esistenti; non sono stati ricalcolati o trasferiti a chunk "
            "diversi.",
            "",
            "| Coorte | ID | Categoria | Pos. | PDF, pagina | Chunk | Estratto | Motivazione Groq |",
            "|---|---|---|---:|---|---|---|---|",
        ]
    )
    for row in nonrelevant:
        excerpt = row["estratto"].replace("|", "\\|")
        reason = row["motivazione_groq"].replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {row['coorte']} | {row['id_domanda']} | {row['categoria']} | "
            f"{row['posizione']} | {row['pdf']}, {row['pagina']} | "
            f"`{row['chunk_id']}` | {excerpt} | {reason} |"
        )
    lines.extend(
        [
            "",
            "## Protocollo delle alternative",
            "",
            "Il modulo sperimentale è separato da `semantic_search` e non "
            "cambia il retrieval dell'applicazione. Le alternative previste "
            "sono baseline di produzione invariata, cosine puro su tutto il "
            "corpus, RRF semantico+BM25 con candidate pool di 50 per sorgente, "
            "e la stessa fusione con deduplicazione prudente "
            "solo entro la stessa edizione. Chunk simili fra PDF distinti "
            "rimangono prove separate; non si uniscono passaggi né si perdono "
            "numeri o negazioni. Ogni strategia conserva K=3.",
            "",
            "Usare GT-001..050 per sviluppare/tarare e confrontare varianti. "
            "I risultati storici su tutti i 150 quesiti sono già noti: "
            "GT-051..150 va tenuto fuori dalla scelta della strategia e usato "
            "come insieme di valutazione dopo averla congelata. Non è però un "
            "holdout cieco in senso stretto, perché le metriche storiche su "
            "questi ID sono già state consultate. Ogni nuova run richiede giudizi "
            "Groq sui nuovi chunk; gli ID dei giudizi precedenti non vengono "
            "riusati, anche quando una fonte ricompare.",
            "",
            "Output generato offline; nessuna modifica alle run originali, "
            "Ground Truth, giudizi Groq, metriche o retrieval in produzione.",
        ]
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def _run_cli(args) -> int:
    if not args.authorize_external:
        raise ValueError("Usare --authorize-external per inviare le query a Gemini.")
    frozen = read_json(args.snapshot)
    validate_snapshot(frozen)
    if frozen["origin"] != "real":
        raise ValueError("Uno snapshot simulato non può essere inviato a Gemini.")
    catalog = read_catalog(args.root)
    current = snapshot(catalog, frozen["origin"])
    if current["snapshot_id"] != frozen["snapshot_id"]:
        raise ValueError("L'archivio corrente non corrisponde allo snapshot.")
    dataset = dataset_from_ground_truth(args.ground_truth_csv, frozen["snapshot_id"])
    validate_dataset(dataset, frozen)
    question_ids = question_ids_for_split(args.split)
    if args.out.exists():
        raise ValueError("La destinazione esiste già; scegliere una nuova cartella.")

    key = api_key(args.root)
    if not key:
        raise ValueError("Configurare GEMINI_API_KEY prima dell'esecuzione autorizzata.")
    client = genai.Client(
        api_key=key,
        vertexai=False,
        http_options=types.HttpOptions(
            timeout=30000,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )

    def embedder_factory(events):
        proxy = type("MeasuredClient", (), {})()
        proxy.models = _MeasuredEmbeddingModels(client, events)
        return GeminiEmbedder(key, client=proxy)

    try:
        run = run_retrieval_experiment(
            dataset,
            frozen,
            catalog,
            strategy=args.strategy,
            question_ids=question_ids,
            embedder_factory=embedder_factory,
            authorize_external=True,
            pool_size=args.pool_size,
            root=args.root,
        )
    finally:
        client.close()

    args.out.mkdir(parents=True)
    write_json(args.out / "dataset.json", dataset)
    write_json(args.out / "run.json", run)
    print(f"Retrieval sperimentale salvato in {args.out}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Analisi offline o retrieval sperimentale isolato."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    analyze = commands.add_parser("analyze", help="Analizza run e giudizi esistenti offline.")
    analyze.add_argument("--root", type=Path, default=Path.cwd())
    analyze.add_argument(
        "--out",
        type=Path,
        default=Path("evaluation/results/retrieval_experiment_gt150/analisi_offline.md"),
    )
    run = commands.add_parser("run", help="Esegue solo retrieval, mai generazione RAG.")
    run.add_argument("--root", type=Path, default=Path.cwd())
    run.add_argument("--snapshot", type=Path, required=True)
    run.add_argument("--ground-truth-csv", type=Path, required=True)
    run.add_argument(
        "--split", choices=("development", "holdout", "all"), required=True
    )
    run.add_argument("--strategy", choices=STRATEGIES, required=True)
    run.add_argument("--pool-size", type=int, default=DEFAULT_POOL_SIZE)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--authorize-external", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "analyze":
            output = write_offline_analysis(args.root, args.out)
            print(f"Analisi offline salvata in {output}")
            return 0
        return _run_cli(args)
    except (OSError, RuntimeError, TypeError, ValueError):
        print(
            "Esperimento non completato: verificare snapshot, Ground Truth, "
            "catalogo, autorizzazione e destinazione."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
