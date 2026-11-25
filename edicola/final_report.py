"""Offline aggregation of the 150-question RAG Ground Truth evaluation."""

from __future__ import annotations

import csv
import json
import math
import statistics
from collections import Counter
from pathlib import Path

from edicola.evaluation_data import digest, read_json, validate_snapshot
from edicola.evaluation_judge import CRITERIA as ANSWER_CRITERIA
from edicola.evaluation_judge import validate_grades
from edicola.evaluation_metrics import rag_assessment, score_run, sources_from_hits
from evaluation.llm_relevance_judge import validate_relevance


ORIGINAL_RUNS = (
    {
        "name": "rag_gt50_completo_01",
        "run": "evaluation/results/rag_gt50_completo_01/run.json",
        "judge": "evaluation/results/llm_gt50_risposte_v1.json",
        "dataset": "evaluation/work/annotations/dataset_gt50_sviluppo.json",
    },
    {
        "name": "rag_gt100_parte1_v2",
        "run": "evaluation/results/rag_gt100_parte1_v2/run.json",
        "judge": "evaluation/results/llm_gt100_parte1_risposte.json",
        "dataset": None,
    },
    {
        "name": "rag_gt100_parte2_01",
        "run": "evaluation/results/rag_gt100_parte2_01/run.json",
        "judge": "evaluation/results/llm_gt100_parte2_risposte.json",
        "dataset": "evaluation/work/annotations/dataset_gt100_parte2.json",
    },
)

RECOVERY_RUNS = (
    {
        "name": "prompt-completeness-gt100-parte2",
        "run": "evaluation/results/prompt-completeness-gt100-parte2/run.json",
        "source": "rag_gt100_parte2_01",
        "judge": None,
    },
    {
        "name": "prompt-completeness-recupero-gt50",
        "run": "evaluation/results/prompt-completeness-recupero-gt50/run.json",
        "source": "rag_gt50_completo_01",
        "judge": "evaluation/results/llm_recupero_gt50_risposte.json",
    },
    {
        "name": "prompt-completeness-recupero9",
        "run": "evaluation/results/prompt-completeness-recupero9/run.json",
        "source": "rag_gt100_parte2_01",
        "judge": None,
    },
)

METRIC_FIELDS = (
    "scope",
    "metric",
    "value",
    "valid_n",
    "missing_n",
    "denominator",
    "unit",
    "note",
)


def calculate_ai_silver_metrics(labels: list[str], k: int) -> tuple[float | None, float | None]:
    """Keep the original llm_relevance_judge.py aggregation formulas unchanged."""
    precision = None
    mrr = None
    if labels and all(label in {"R", "N"} for label in labels):
        precision = sum(label == "R" for label in labels) / k
    if labels:
        if all(label == "N" for label in labels):
            mrr = 0.0
        else:
            for rank, label in enumerate(labels, 1):
                if label == "U":
                    break
                if label == "R":
                    mrr = 1 / rank
                    break
    return precision, mrr


def summarize_values(values):
    observed = [value for value in values if value is not None]
    return {
        "n": len(observed),
        "missing": len(values) - len(observed),
        "mean": statistics.mean(observed) if observed else None,
        "median": statistics.median(observed) if observed else None,
    }


def _read_ground_truth(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"ID", "Categoria"}
        if not required <= set(reader.fieldnames or ()):
            raise ValueError("Ground Truth priva delle colonne ID e Categoria.")
        categories = {}
        for row in reader:
            identity = (row.get("ID") or "").strip()
            category = (row.get("Categoria") or "").strip()
            if not identity or not category or identity in categories:
                raise ValueError("Ground Truth con ID/categoria mancanti o duplicati.")
            categories[identity] = category
    expected_ids = {f"GT-{number:03d}" for number in range(1, 151)}
    if set(categories) != expected_ids:
        raise ValueError("La Ground Truth non contiene esattamente GT-001..GT-150.")
    return categories


def _validate_run_records(run, snapshot, expected_ids):
    if (
        run.get("schema_version") != 1
        or run.get("origin") != "real"
        or run.get("mode") != "rag"
        or run.get("snapshot_id") != snapshot["snapshot_id"]
        or run.get("top_k") != 3
        or not isinstance(run.get("records"), list)
    ):
        raise ValueError("Run originale incompatibile con il benchmark RAG atteso.")
    records = {}
    chunks = {chunk.id: chunk for chunk in validate_snapshot(snapshot).chunks}
    for record in run["records"]:
        identity = record.get("question_id")
        if (
            identity not in expected_ids
            or identity in records
            or record.get("repeat") != 1
            or record.get("retrieval_status") not in {"ok", "error"}
            or record.get("status") not in {"ok", "error"}
        ):
            raise ValueError("Record run sconosciuto, duplicato o con stato invalido.")
        hits = record.get("retrieved")
        if not isinstance(hits, list) or len(hits) > 3:
            raise ValueError(f"{identity}: risultati retrieval non validi.")
        seen_chunks = set()
        for hit in hits:
            chunk = chunks.get(hit.get("id"))
            if (
                chunk is None
                or hit["id"] in seen_chunks
                or hit.get("filename") != chunk.metadata["filename"]
                or hit.get("page") != chunk.metadata["page"]
                or hit.get("text") != chunk.text
            ):
                raise ValueError(f"{identity}: chunk diverso dallo snapshot.")
            seen_chunks.add(hit["id"])
        state, _ = rag_assessment(record.get("raw_response"), sources_from_hits(hits))
        if record.get("response_state") != state:
            raise ValueError(f"{identity}: stato risposta diverso dalla validazione.")
        for field in ("retrieval_seconds", "generation_seconds", "total_seconds"):
            value = record.get(field)
            if value is not None and (
                type(value) not in (int, float) or not math.isfinite(value) or value < 0
            ):
                raise ValueError(f"{identity}: tempo registrato non valido.")
        records[identity] = record
    if set(records) != set(expected_ids):
        raise ValueError("La run non copre esattamente la coorte prevista.")
    return records


def _validate_relevance_file(path: Path, run, records):
    data = read_json(path)
    if (
        data.get("schema_version") != 1
        or data.get("provider") != "groq"
        or data.get("origin") != "ai_silver"
        or data.get("snapshot_id") != run["snapshot_id"]
        or data.get("run_sha256") != digest(run)
        or not isinstance(data.get("records"), dict)
    ):
        raise ValueError(f"Giudizi Groq non collegati alla run: {path}.")
    metrics = {}
    statuses = Counter()
    expected_items = {f"{qid}#1" for qid in records}
    if set(data["records"]) != expected_items:
        raise ValueError(f"Copertura giudizi chunk incompleta o estranea: {path}.")
    for item_id, judged in data["records"].items():
        statuses[judged.get("status", "missing_status")] += 1
        if judged.get("status") != "judged":
            metrics[item_id.split("#", 1)[0]] = (None, None)
            continue
        record = records[item_id.split("#", 1)[0]]
        hits = record["retrieved"] if record["retrieval_status"] == "ok" else []
        checked = validate_relevance(
            json.dumps({"judgments": judged.get("judgments")}, ensure_ascii=False),
            hits,
        )
        by_chunk = {judgment["chunk_id"]: judgment for judgment in checked}
        labels = [by_chunk[hit["id"]]["label"] for hit in hits]
        metrics[record["question_id"]] = calculate_ai_silver_metrics(
            labels, run["top_k"]
        )
    return metrics, statuses


def _validated_answer_scores(answer_file, run, records):
    scores = {}
    statuses = Counter()
    invalid_judged = 0
    if answer_file is None:
        return scores, statuses, invalid_judged
    data = read_json(answer_file)
    if (
        data.get("schema_version") != 1
        or data.get("provider") != "groq"
        or data.get("snapshot_id") != run["snapshot_id"]
        or data.get("run_sha256") != digest(run)
        or not isinstance(data.get("answer_records"), dict)
    ):
        raise ValueError(f"Giudizi risposta Groq non collegati alla run: {answer_file}.")
    entries = data["answer_records"]
    if not set(entries) <= {f"{qid}#1" for qid in records}:
        raise ValueError(f"Giudizio risposta relativo a record estraneo: {answer_file}.")

    for item_id, entry in entries.items():
        status = entry.get("status", "missing_status")
        statuses[status] += 1
        if status != "judged":
            continue
        qid = item_id.split("#", 1)[0]
        record = records[qid]
        sources = sources_from_hits(record["retrieved"])
        state, checked = rag_assessment(record.get("raw_response"), sources)
        grades = entry.get("grades")
        if record["status"] != "ok" or state != "answered" or checked is None:
            invalid_judged += 1
            continue
        if not isinstance(grades, dict) or set(grades) != set(ANSWER_CRITERIA):
            invalid_judged += 1
            continue
        normalized = {}
        for criterion in ANSWER_CRITERIA:
            grade = grades[criterion]
            score = grade.get("score") if isinstance(grade, dict) else None
            if score is None:
                normalized[criterion] = {
                    **grade,
                    "score": "NA",
                } if isinstance(grade, dict) else grade
            elif type(score) is int and 0 <= score <= 4:
                normalized[criterion] = {**grade, "score": str(score)}
            else:
                normalized[criterion] = {**grade, "score": score}
        try:
            validated = validate_grades(
                json.dumps(normalized, ensure_ascii=False), sources
            )
        except (ValueError, TypeError, KeyError, AttributeError):
            invalid_judged += 1
            continue
        scores[qid] = {
            criterion: grade["score"]
            for criterion, grade in validated.items()
        }
    return scores, statuses, invalid_judged


def _add_metric(rows, scope, metric, value, valid_n, denominator, unit, note=""):
    rows.append(
        {
            "scope": scope,
            "metric": metric,
            "value": "" if value is None else value,
            "valid_n": valid_n,
            "missing_n": max(0, denominator - valid_n),
            "denominator": denominator,
            "unit": unit,
            "note": note,
        }
    )


def _aggregate_scope(
    scope,
    records,
    categories,
    retrieval_metrics,
    answer_scores,
    *,
    retrieval_is_reused=False,
):
    rows = []
    denominator = len(records)

    def count_where(predicate):
        return sum(predicate(record) for record in records.values())

    raw_generated = count_where(
        lambda record: record["status"] == "ok"
        and record.get("raw_response") is not None
    )
    answered = count_where(
        lambda record: record["status"] == "ok"
        and record.get("response_state") == "answered"
    )
    abstentions = count_where(
        lambda record: record["status"] == "ok"
        and record.get("response_state") == "model_abstention"
    )
    validation_failed = count_where(
        lambda record: record["status"] == "ok"
        and record.get("response_state") == "validation_failed"
    )
    api_error_attempts = sum(
        event.get("outcome") == "error"
        for record in records.values()
        for event in record.get("api_events", [])
    )
    api_error_questions = count_where(
        lambda record: any(
            event.get("outcome") == "error"
            for event in record.get("api_events", [])
        )
    )
    terminal_errors = count_where(lambda record: record["status"] == "error")
    non_api_terminal_errors = count_where(
        lambda record: record["status"] == "error"
        and not any(
            event.get("outcome") == "error"
            for event in record.get("api_events", [])
        )
    )

    counters = {
        "domande": denominator,
        "risposte_generate_raw": raw_generated,
        "risposte_validate": answered,
        "astensioni_modello": abstentions,
        "errori_validazione": validation_failed,
        "domande_con_errori_api": api_error_questions,
        "tentativi_api_falliti": api_error_attempts,
        "errori_esecuzione_terminali": terminal_errors,
        "errori_terminali_non_api": non_api_terminal_errors,
    }
    for metric, value in counters.items():
        _add_metric(rows, scope, metric, value, denominator, denominator, "count")
    for metric, value in (
        ("tasso_risposta_generata_raw", raw_generated),
        ("tasso_risposta_validata", answered),
        ("tasso_astensione", abstentions),
        ("tasso_errore_validazione", validation_failed),
        ("tasso_domande_con_errori_api", api_error_questions),
        ("tasso_errori_esecuzione_terminali", terminal_errors),
    ):
        _add_metric(
            rows,
            scope,
            metric,
            value / denominator if denominator else None,
            denominator if denominator else 0,
            denominator,
            "ratio",
        )

    for metric, pair_index in (("precision_at_3", 0), ("mrr_at_3", 1)):
        values = [
            pair[pair_index]
            for identity, pair in retrieval_metrics.items()
            if identity in records
        ]
        summary = summarize_values(values)
        note = (
            "Metriche di retrieval ereditate dalla baseline: retrieval e chunk invariati."
            if retrieval_is_reused
            else "Macro-media delle sole domande con giudizio Groq valido secondo la formula originale."
        )
        _add_metric(
            rows,
            scope,
            metric,
            summary["mean"],
            summary["n"],
            denominator,
            "ratio",
            note,
        )
    _add_metric(
        rows,
        scope,
        "recall_at_3",
        None,
        0,
        denominator,
        "ratio",
        "Non calcolabile: mancano annotazioni esaustive dei chunk rilevanti.",
    )

    for criterion in ANSWER_CRITERIA:
        values = [
            row.get(criterion)
            for identity, row in answer_scores.items()
            if identity in records and row.get(criterion) is not None
        ]
        summary = summarize_values(values)
        _add_metric(
            rows,
            scope,
            f"groq_{criterion}_mean",
            summary["mean"],
            summary["n"],
            denominator,
            "score_0_4",
            "Media dei soli voti Groq validi e numerici; NA/errori esclusi.",
        )

    for phase in ("retrieval", "generation", "total"):
        values = [record.get(f"{phase}_seconds") for record in records.values()]
        summary = summarize_values(values)
        for statistic in ("mean", "median"):
            _add_metric(
                rows,
                scope,
                f"{phase}_seconds_{statistic}",
                summary[statistic],
                summary["n"],
                denominator,
                "seconds",
                "Solo valori temporali numerici effettivamente registrati.",
            )

    return rows


def _category_rows(records, categories, retrieval_metrics, answer_scores):
    rows = []
    for category in sorted(set(categories.values())):
        ids = {identity for identity in records if categories[identity] == category}
        subset = {identity: records[identity] for identity in ids}
        row = {
            "categoria": category,
            "domande": len(ids),
            "risposte_generate_raw": sum(
                r["status"] == "ok" and r.get("raw_response") is not None
                for r in subset.values()
            ),
            "risposte_validate": sum(
                r["status"] == "ok" and r.get("response_state") == "answered"
                for r in subset.values()
            ),
            "astensioni_modello": sum(
                r["status"] == "ok" and r.get("response_state") == "model_abstention"
                for r in subset.values()
            ),
            "errori_validazione": sum(
                r["status"] == "ok" and r.get("response_state") == "validation_failed"
                for r in subset.values()
            ),
            "domande_con_errori_api": sum(
                any(e.get("outcome") == "error" for e in r.get("api_events", []))
                for r in subset.values()
            ),
            "tentativi_api_falliti": sum(
                e.get("outcome") == "error"
                for r in subset.values()
                for e in r.get("api_events", [])
            ),
        }
        for metric, position in (("precision_at_3", 0), ("mrr_at_3", 1)):
            summary = summarize_values(
                [
                    pair[position]
                    for identity, pair in retrieval_metrics.items()
                    if identity in ids
                ]
            )
            row[metric] = summary["mean"]
            row[f"{metric}_n"] = summary["n"]
        row["recall_at_3"] = ""
        row["recall_at_3_n"] = 0
        for criterion in ANSWER_CRITERIA:
            summary = summarize_values(
                [
                    values.get(criterion)
                    for identity, values in answer_scores.items()
                    if identity in ids and values.get(criterion) is not None
                ]
            )
            row[f"groq_{criterion}_mean"] = summary["mean"]
            row[f"groq_{criterion}_n"] = summary["n"]
        for phase in ("retrieval", "generation", "total"):
            values = [record.get(f"{phase}_seconds") for record in subset.values()]
            summary = summarize_values(values)
            row[f"{phase}_seconds_mean"] = summary["mean"]
            row[f"{phase}_seconds_mean_n"] = summary["n"]
            row[f"{phase}_seconds_median"] = summary["median"]
            row[f"{phase}_seconds_median_n"] = summary["n"]
        rows.append(row)
    return rows


def _validate_recovery(recovery, baseline, baseline_records, snapshot):
    expected_ids = set(baseline_records)
    recovery_ids = {record.get("question_id") for record in recovery["records"]}
    if not recovery_ids or not recovery_ids <= expected_ids:
        raise ValueError("Il recupero contiene ID estranei o nessun record.")
    records = _validate_run_records(recovery, snapshot, recovery_ids)
    if (
        recovery.get("source_run_id") != digest(baseline)
        or recovery.get("dataset_id") != baseline.get("dataset_id")
        or recovery.get("configuration", {}).get("generation_model")
        != baseline.get("configuration", {}).get("generation_model")
        or recovery.get("configuration", {}).get("generation_prompt")
        != "completeness-v1"
    ):
        raise ValueError("Esperimento di recupero non collegato alla baseline attesa.")
    for identity, record in records.items():
        original = baseline_records[identity]
        if record["retrieved"] != original["retrieved"]:
            raise ValueError(f"{identity}: i chunk del recupero differiscono dalla baseline.")
    return records


def _compare_recovery(name, baseline_records, recovery_records):
    pairs = []
    for identity, record in recovery_records.items():
        original = baseline_records[identity]
        before = (
            original["response_state"]
            if original["status"] == "ok"
            else "api_error"
        )
        after = (
            record["response_state"]
            if record["status"] == "ok"
            else "api_error"
        )
        pairs.append(
            {
                "scope": name,
                "question_id": identity,
                "baseline_state": before,
                "recovery_state": after,
                "transition": f"{before} -> {after}",
            }
        )
    return pairs


def _write_csv(path: Path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _format(value, unit):
    if value == "" or value is None:
        return "n.c."
    if unit == "ratio":
        return f"{100 * value:.1f}%"
    if unit == "score_0_4":
        return f"{value:.2f}/4"
    if unit == "seconds":
        return f"{value:.3f} s"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def _render_markdown(
    original_rows,
    category_rows,
    original_records,
    categories,
    answer_statuses,
    invalid_answer_judgments,
    recovery_data,
    missing_dataset,
):
    metrics = {
        row["metric"]: row
        for row in original_rows
        if row["scope"] == "GT150 original"
    }
    lines = [
        "# Report finale delle metriche RAG — Ground Truth 150",
        "",
        "## Sintesi",
        "",
        "Analisi offline delle tre run RAG originali (150 domande uniche, K=3), "
        "dei giudizi Groq già salvati e degli esperimenti successivi. Non sono "
        "state effettuate chiamate API né avviati benchmark. I risultati degli "
        "esperimenti di recupero sono mantenuti separati e non sommati al benchmark.",
        "",
        "| Metrica | Risultato | N con misura | Denominatore |",
        "|---|---:|---:|---:|",
    ]
    for metric, label in (
        ("precision_at_3", "Precision@3 Groq AI-silver"),
        ("mrr_at_3", "MRR@3 Groq AI-silver"),
        ("recall_at_3", "Recall@3"),
        ("groq_faithfulness_mean", "Faithfulness Groq"),
        ("groq_completeness_mean", "Completeness Groq"),
        ("groq_answer_relevance_mean", "Answer Relevance Groq"),
        ("groq_citation_correctness_mean", "Citation Correctness Groq"),
        ("tasso_risposta_generata_raw", "Risposta generata (raw disponibile)"),
        ("tasso_risposta_validata", "Risposta validata"),
        ("tasso_astensione", "Astensione del modello"),
        ("tasso_errore_validazione", "Errore di validazione"),
        ("tasso_domande_con_errori_api", "Domande con almeno un errore API"),
        ("total_seconds_mean", "Latenza totale media registrata"),
        ("total_seconds_median", "Latenza totale mediana registrata"),
    ):
        item = metrics[metric]
        unit = item["unit"]
        lines.append(
            f"| {label} | {_format(item['value'], unit)} | "
            f"{item['valid_n']} | {item['denominator']} |"
        )

    nonanswerable_ids = {
        identity for identity, category in categories.items()
        if category.casefold() == "non rispondibile"
    }
    nonanswerable = [original_records[identity] for identity in sorted(nonanswerable_ids)]
    nonanswerable_states = Counter(
        r["response_state"] if r["status"] == "ok" else "api_error"
        for r in nonanswerable
    )
    lines.extend(
        [
            "",
            "## Metodo e limiti",
            "",
            "- Precision@3 e MRR@3 sono macro-medie dei valori per domanda "
            "calcolati con la formula originale `calculate_metrics` sulle "
            "etichette R/N/U Groq; vengono incluse solo domande valutabili "
            "secondo quella formula. `U` non è trasformato in negativo.",
            "- Recall@3 non è calcolabile: le annotazioni di rilevanza non "
            "coprono esaustivamente l’intero insieme dei chunk per domanda.",
            "- I quattro punteggi di risposta sono medie dei soli record "
            "`judged` con score 0–4 e prove/motivazioni validate. `judge_error`, "
            "assenze di risposta valida e score `NA` non sono zeri.",
            "- I conteggi e le percentuali di risposta hanno come denominatore "
            "le 150 domande originali. Una risposta `raw` non equivale a una "
            "risposta valida o fattualmente corretta.",
            "- Latenze medie e mediane usano esclusivamente i secondi presenti "
            "nei record; non si imputano tempi mancanti. Nelle run di recupero "
            "total_seconds coincide con il solo tempo di generazione, poiché il "
            "retrieval è stato riusato.",
            f"- Il dataset annotato esatto per `{missing_dataset}` non è "
            "disponibile nel checkout. La run e i giudizi sono collegati "
            "tramite hash, ma non si sostituiscono le annotazioni mancanti con "
            "un dataset di hash diverso.",
            "- Le run originali coprono coorti disgiunte GT-001..050, "
            "GT-051..100 e GT-101..150; il report verifica ID univoci e hash "
            "dei giudizi prima dell'aggregazione. I JSON `judge.json` pilota "
            "con hash di run differenti non sono attribuiti a queste coorti.",
            "- Le etichette di categoria e Non rispondibile provengono dal CSV "
            "Ground Truth; i giudizi AI-silver e Groq restano misure automatiche, "
            "non validazioni umane.",
            "",
            "## Copertura dei giudizi Groq",
            "",
            "| Stato giudizio risposta | Record |",
            "|---|---:|",
        ]
    )
    for status, count in sorted(answer_statuses.items()):
        lines.append(f"| {status} | {count} |")
    lines.append(
        f"| nessun record risposta salvato | "
        f"{150 - sum(answer_statuses.values())} |"
    )
    lines.append(f"| Giudizi dichiarati `judged` ma non validi in verifica | {invalid_answer_judgments} |")
    lines.extend(
        [
            "",
            "## Risultati per categoria Ground Truth",
            "",
            "| Categoria | N | Precision@3 (N) | MRR@3 (N) | Faithfulness (N) | Completeness (N) | "
            "Answer Relevance (N) | Citation Correctness (N) | Risposte validate | "
            "Astensioni | Errori validazione |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in category_rows:
        cells = [
            row["categoria"],
            str(row["domande"]),
            f"{_format(row['precision_at_3'], 'ratio')} ({row['precision_at_3_n']})",
            f"{_format(row['mrr_at_3'], 'ratio')} ({row['mrr_at_3_n']})",
        ]
        for criterion in ANSWER_CRITERIA:
            key = f"groq_{criterion}_mean"
            cells.append(
                f"{_format(row[key], 'score_0_4')} "
                f"({row[f'groq_{criterion}_n']})"
            )
        cells.extend(
            str(row[key])
            for key in ("risposte_validate", "astensioni_modello", "errori_validazione")
        )
        lines.append("| " + " | ".join(cells) + " |")
    lines.extend(
        [
            "",
            "### 20 domande «Non rispondibile»",
            "",
            f"Esito delle run originali: **{len(nonanswerable)}** domande. "
            + "; ".join(f"{state}: {count}" for state, count in sorted(nonanswerable_states.items()))
            + f"; astensioni {nonanswerable_states['model_abstention']}/{len(nonanswerable)} "
            f"({100 * nonanswerable_states['model_abstention'] / len(nonanswerable):.1f}%). "
            "L’astensione del modello è un comportamento osservato, non "
            "un giudizio di correttezza fattuale.",
            "",
            "## Esperimenti successivi di recupero (separati)",
            "",
            "Gli esperimenti riusano i chunk originali e non sono aggiunti alle "
            "150 osservazioni del benchmark. Il recupero completo della parte 2 "
            "e il recupero selettivo `recupero9` si sovrappongono sulle stesse "
            "nove domande: sono riportati come esperimenti distinti e non sommati.",
            "",
            "| Esperimento | N record | Risposte validate | Astensioni | Errori validazione | "
            "Errori API terminali | Nuove risposte non rispondibili | "
            "Prima non valida → risposta validata | "
            "Risposta validata → non valida |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for item in recovery_data:
        counts = item["counts"]
        lines.append(
            f"| {item['name']} | {counts['n']} | {counts['answered']} | "
            f"{counts['abstention']} | {counts['validation_failed']} | "
            f"{counts['api_error']} | {item['newly_answered_unanswerable']} "
            f"({', '.join(item['newly_answered_unanswerable_ids']) or 'nessuna'}) | "
            f"{item['newly_answered']} | {item['regressed']} |"
        )
    for item in recovery_data:
        if item["transitions"]:
            lines.append("")
            lines.append(f"Transizioni per `{item['name']}`:")
            for transition, count in sorted(Counter(item["transitions"]).items()):
                lines.append(f"- `{transition}`: {count}")
    lines.extend(
        [
            "",
            "Per il recupero GT-50 è disponibile un file Groq collegato alla run, "
            "ma non contiene giudizi di risposta validi: gli errori Groq e le "
            "assenze di risposta valutabile sono riportati come mancanti, non zero. "
            "Gli altri recuperi non hanno giudizi Groq di risposta collegati.",
            "",
            "## API, latenza e interpretazione",
            "",
            f"Tra le run originali si osservano **{metrics['tentativi_api_falliti']['value']} "
            "tentativi API falliti** distribuiti su "
            f"**{metrics['domande_con_errori_api']['value']} domande**; alcuni "
            "tentativi sono stati seguiti da retry riusciti. Gli errori terminali "
            f"sono {metrics['errori_esecuzione_terminali']['value']}, di cui "
            f"{metrics['errori_terminali_non_api']['value']} senza evento API "
            "fallito registrato.",
            "",
            "Le metriche di retrieval derivano da etichette Groq AI-silver, non "
            "da annotazioni umane esaustive. Citation Correctness giudicata da "
            "Groq non certifica la correttezza fattuale. Per la tesi riportare "
            "queste limitazioni insieme ai denominatori e non generalizzare "
            "oltre il corpus, il modello e le condizioni sperimentali misurate.",
            "",
        ]
    )
    return "\n".join(lines)


def build_final_report(root: Path):
    root = Path(root)
    snapshot = read_json(root / "evaluation/work/snapshot.json")
    validate_snapshot(snapshot)
    categories = _read_ground_truth(root / "evaluation/data/Ground_Truth_Edicola_150_domande.csv")
    expected = set(categories)
    all_original_records = {}
    original_rows = []
    run_by_name = {}
    answer_statuses = Counter()
    invalid_answer_judgments = 0

    for config, first, last in zip(
        ORIGINAL_RUNS, (1, 51, 101), (50, 100, 150), strict=True
    ):
        run = read_json(root / config["run"])
        expected_cohort = {
            f"GT-{number:03d}" for number in range(first, last + 1)
        }
        run_ids = {record.get("question_id") for record in run.get("records", [])}
        if run_ids != expected_cohort:
            raise ValueError(f"La run {config['name']} non corrisponde alla coorte ID prevista.")
        records = _validate_run_records(run, snapshot, run_ids)
        if set(records) & set(all_original_records):
            raise ValueError("Le coorti originali contano almeno una domanda due volte.")
        if config["dataset"]:
            dataset = read_json(root / config["dataset"])
            if digest(dataset) != run.get("dataset_id"):
                raise ValueError(f"Dataset non corrispondente alla baseline {config['name']}.")
            score_run(dataset, snapshot, run, validate_snapshot(snapshot))
        retrieval, _ = _validate_relevance_file(
            root / config["judge"], run, records
        )
        answer_file = root / config["judge"]
        answers, statuses, invalid = _validated_answer_scores(
            answer_file, run, records
        )
        answer_statuses.update(statuses)
        invalid_answer_judgments += invalid
        all_original_records.update(records)
        run_by_name[config["name"]] = (
            run,
            records,
            retrieval,
            answers,
            statuses,
            invalid,
        )
        original_rows.extend(
            _aggregate_scope(config["name"], records, categories, retrieval, answers)
        )

    if set(all_original_records) != expected:
        raise ValueError("Le run originali non formano una copertura univoca di 150 ID.")

    merged_retrieval = {}
    merged_scores = {}
    for _, _, retrieval, answers, _, _ in run_by_name.values():
        merged_retrieval.update(retrieval)
        merged_scores.update(answers)
    original_rows.extend(
        _aggregate_scope(
            "GT150 original",
            all_original_records,
            categories,
            merged_retrieval,
            merged_scores,
        )
    )

    category_rows = _category_rows(
        all_original_records, categories, merged_retrieval, merged_scores
    )

    recovery_data = []
    recovery_metric_rows = []
    for config in RECOVERY_RUNS:
        baseline_run, baseline_records, retrieval, _, _, _ = run_by_name[
            config["source"]
        ]
        recovery = read_json(root / config["run"])
        records = _validate_recovery(
            recovery, baseline_run, baseline_records, snapshot
        )
        answer_file = root / config["judge"] if config["judge"] else None
        if answer_file is not None:
            scores, statuses, invalid = _validated_answer_scores(
                answer_file, recovery, records
            )
            recovery_statuses = statuses
        else:
            scores, invalid, recovery_statuses = {}, 0, Counter()
        scope_rows = _aggregate_scope(
            config["name"],
            records,
            categories,
            retrieval,
            scores,
            retrieval_is_reused=True,
        )
        recovery_metric_rows.extend(scope_rows)
        transitions = _compare_recovery(config["name"], baseline_records, records)
        state_counts = Counter(
            record["response_state"]
            if record["status"] == "ok"
            else "api_error"
            for record in records.values()
        )
        newly_answered = sum(
            item["baseline_state"] != "answered"
            and item["recovery_state"] == "answered"
            for item in transitions
        )
        regressed = sum(
            item["baseline_state"] == "answered"
            and item["recovery_state"] != "answered"
            for item in transitions
        )
        newly_answered_unanswerable_ids = sorted(
            item["question_id"]
            for item in transitions
            if item["baseline_state"] != "answered"
            and item["recovery_state"] == "answered"
            and categories[item["question_id"]].casefold() == "non rispondibile"
        )
        recovery_data.append(
            {
                "name": config["name"],
                "counts": {
                    "n": len(records),
                    "answered": state_counts["answered"],
                    "abstention": state_counts["model_abstention"],
                    "validation_failed": state_counts["validation_failed"],
                    "api_error": state_counts["api_error"],
                },
                "newly_answered": newly_answered,
                "newly_answered_unanswerable": len(newly_answered_unanswerable_ids),
                "newly_answered_unanswerable_ids": newly_answered_unanswerable_ids,
                "regressed": regressed,
                "transitions": [item["transition"] for item in transitions],
                "answer_judge_statuses": recovery_statuses,
                "invalid_answer_judgments": invalid,
            }
        )

    final_rows = original_rows + recovery_metric_rows
    for config_name, (_, records, _, answers, statuses, invalid) in run_by_name.items():
        # Preserve answer-judge status counts as explicit report metrics.
        for status, count in sorted(statuses.items()):
            _add_metric(
                final_rows,
                config_name,
                f"groq_answer_status_{status}",
                count,
                len(statuses),
                len(records),
                "count",
                "Stato di valutazione, non score.",
            )
        _add_metric(
            final_rows,
            config_name,
            "groq_answer_status_not_recorded",
            len(records) - len(statuses),
            len(records) - len(statuses),
            len(records),
            "count",
            "Record senza alcun esito Groq risposta salvato.",
        )
        _add_metric(
            final_rows,
            config_name,
            "groq_answer_invalid_judged_records",
            invalid,
            invalid,
            len(records),
            "count",
            "Record etichettati judged ma non validi alla verifica offline.",
        )

    for item in recovery_data:
        for status, count in sorted(item["answer_judge_statuses"].items()):
            _add_metric(
                final_rows,
                item["name"],
                f"groq_answer_status_{status}",
                count,
                sum(item["answer_judge_statuses"].values()),
                item["counts"]["n"],
                "count",
                "Stato di valutazione, non score.",
            )

    for item in recovery_data:
        scope = item["name"]
        denominator = item["counts"]["n"]
        _add_metric(
            final_rows,
            scope,
            "nuove_risposte_validate_vs_baseline",
            item["newly_answered"],
            denominator,
            denominator,
            "count",
        )
        _add_metric(
            final_rows,
            scope,
            "risposte_validate_regredite_vs_baseline",
            item["regressed"],
            denominator,
            denominator,
            "count",
        )

    report_dir = root / "evaluation/results/report_finale_gt150"
    if report_dir.exists():
        raise FileExistsError(f"Destinazione gia esistente: {report_dir}")
    report_dir.mkdir(parents=True)
    _write_csv(report_dir / "metriche_finali.csv", METRIC_FIELDS, final_rows)

    category_fields = list(category_rows[0])
    _write_csv(
        report_dir / "metriche_per_categoria.csv",
        category_fields,
        category_rows,
    )
    markdown = _render_markdown(
        original_rows,
        category_rows,
        all_original_records,
        categories,
        answer_statuses,
        invalid_answer_judgments,
        recovery_data,
        "GT-051..GT-100 (dataset_id 50169bd7dab5f8d6cd29830dccce409416e7f93db6e0fcfc9bab7140be954868)",
    )
    (report_dir / "report_finale.md").write_text(markdown, encoding="utf-8")
    return report_dir


def main():
    root = Path(__file__).resolve().parents[1]
    output = build_final_report(root)
    print(f"Report offline creato in: {output}")


if __name__ == "__main__":
    main()
