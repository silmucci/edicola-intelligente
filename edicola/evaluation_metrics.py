"""Metriche con denominatori dichiarati: mancante non significa zero."""

import json
import math
import statistics
from collections import defaultdict

from edicola.rag import Source, validate_response


def retrieval_metrics(question, hits, catalog, k):
    ids = [h["id"] for h in hits[:k]]
    if len(set(ids)) != len(ids):
        raise ValueError("Risultati retrieval duplicati: correggere la run, non i giudizi.")
    positive = {c["chunk_id"] for c in question["relevant_chunks"]}
    negative = set(question["nonrelevant_chunk_ids"])
    complete = question["judgments_complete"]
    judged = complete or set(ids) <= positive | negative
    relevant_found = len(set(ids) & positive)
    reciprocal = None
    # È MRR troncato a K: un non giudicato precedente rende il rango incerto.
    for rank, identity in enumerate(ids, 1):
        if identity in positive:
            reciprocal = 1 / rank
            break
        if not complete and identity not in negative:
            break
    else:
        reciprocal = 0.0
    if not positive:
        reciprocal = None
    documents = {c.metadata["filename"] for c in catalog.chunks}
    retrieved = {h["filename"] for h in hits[:k]}
    relevant_docs = {c["pdf"] for c in question["relevant_chunks"]}
    return {"precision_at_k": relevant_found / k if judged else None,
            "recall_at_k": relevant_found / len(positive) if complete and positive else None,
            "mrr_at_k": reciprocal,
            "document_coverage": len(retrieved) / len(documents) if documents else None,
            "relevant_document_coverage": len(retrieved & relevant_docs) / len(relevant_docs) if complete and relevant_docs else None}


def sources_from_hits(hits):
    return [Source(f"S{i}", h["id"], h["filename"], h["page"], h["text"], h["distance"]) for i, h in enumerate(hits, 1)]


def rag_assessment(raw, sources):
    if not sources:
        return "no_sources", None
    if raw is None:
        return "not_run", None
    checked = validate_response(raw, sources)
    if checked.sufficient:
        return "answered", checked
    try:
        data = json.loads(raw)
        if data == {"sufficient": False, "claims": []}:
            return "model_abstention", checked
    except (ValueError, TypeError):
        pass
    return "validation_failed", checked


def summarize(rows, min_p95=20):
    groups = defaultdict(list)
    for row in rows:
        groups[(row["origin"], row["metric"], row["unit"])].append(row["value"])
    output = []
    for (origin, metric, unit), all_values in sorted(groups.items()):
        values = sorted(v for v in all_values if v is not None)
        if any(not math.isfinite(v) for v in values):
            raise ValueError("Metrica non finita.")
        n = len(values)
        p95 = None
        if n >= min_p95:
            position = (n - 1) * 0.95
            low = math.floor(position)
            p95 = values[low] + (values[math.ceil(position)] - values[low]) * (position - low)
        output.append({"origin": origin, "metric": metric, "unit": unit, "n": n,
                       "missing": len(all_values) - n, "mean": statistics.mean(values) if n else None,
                       "median": statistics.median(values) if n else None, "p95": p95})
    return output


def score_run(dataset, frozen, run, catalog):
    from edicola.evaluation_data import digest
    if (run.get("schema_version") != 1 or run.get("snapshot_id") != frozen["snapshot_id"]
            or run.get("dataset_id") != digest(dataset) or run.get("origin") not in ("real", "simulated")
            or run.get("mode") not in ("retrieval", "rag") or type(run.get("top_k")) is not int or not 1 <= run["top_k"] <= 5):
        raise ValueError("Run incompatibile con dataset/snapshot, modalità o provenienza.")
    if frozen["origin"] == "simulated" and run["origin"] != "simulated":
        raise ValueError("Uno snapshot simulato non produce risultati reali.")
    questions = {q["id"]: q for q in dataset["questions"]}
    chunks = {c.id: c for c in catalog.chunks}
    rows, union, seen = [], set(), set()
    successful_retrievals = 0
    if not isinstance(run.get("records"), list) or not run["records"]:
        raise ValueError("Run senza campioni.")
    for record in run["records"]:
        qid, repeat = record["question_id"], record["repeat"]
        if qid not in questions or type(repeat) is not int or repeat < 1 or (qid, repeat) in seen:
            raise ValueError("Campione sconosciuto o duplicato.")
        seen.add((qid, repeat))
        hits = record["retrieved"]
        if len(hits) > run["top_k"]:
            raise ValueError("Troppi risultati rispetto a K.")
        for hit in hits:
            c = chunks.get(hit["id"])
            if (c is None or hit["filename"] != c.metadata["filename"] or hit["page"] != c.metadata["page"] or hit["text"] != c.text):
                raise ValueError("Risultato estraneo allo snapshot o riferimento alterato.")
        q = questions[qid]
        item = f"{qid}#{repeat}"
        def add(metric, value, unit="ratio", note=""):
            rows.append({"item_id": item, "origin": run["origin"], "metric": metric, "value": value, "unit": unit, "note": note})
        if record["retrieval_status"] not in ("ok", "error") or record["status"] not in ("ok", "error"):
            raise ValueError("Stato del campione non valido.")
        if record["retrieval_status"] == "ok":
            successful_retrievals += 1
            union.update(h["filename"] for h in hits)
            for metric, value in retrieval_metrics(q, hits, catalog, run["top_k"]).items():
                add(metric, value, note="Giudizi incompleti o denominatore non definito" if value is None else "")
        else:
            for metric in ("precision_at_k", "recall_at_k", "mrr_at_k", "document_coverage", "relevant_document_coverage"):
                add(metric, None, note="Retrieval fallito, escluso dalle metriche di qualità")
        for phase in ("retrieval", "generation", "total"):
            value = record.get(f"{phase}_seconds")
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
                raise ValueError("Tempo non valido.")
            success = record["retrieval_status"] == "ok" if phase == "retrieval" else record["status"] == "ok"
            add(f"{phase}_seconds" if success else f"failed_{phase}_seconds", value, "seconds")
        events = record["api_events"]
        for event in events:
            code = event["http_status"]
            if event["phase"] not in ("query_embedding", "generation") or (code is not None and (type(code) is not int or not 100 <= code <= 599)):
                raise ValueError("Evento API non valido.")
        add("api_calls", len(events), "count")
        for phase in ("query_embedding", "generation"):
            add(f"{phase}_api_calls", sum(e["phase"] == phase for e in events), "count")
        add("http_errors", sum(e["http_status"] is not None and e["http_status"] >= 400 for e in events), "count")
        add("non_http_api_errors", sum(e.get("outcome") == "error" and e["http_status"] is None for e in events), "count")
        add("request_error", int(record["status"] == "error"))
        if run["mode"] == "rag":
            state, _ = rag_assessment(record.get("raw_response"), sources_from_hits(hits))
            add("rag_validation_failure", int(state == "validation_failed") if record["status"] == "ok" else None)
            add("citation_technical_pass", 1 if state == "answered" else (0 if state == "validation_failed" else None),
                note="Solo struttura, ID e prove letterali; NON correttezza fattuale")
            decision = None
            if record["status"] == "ok" and q["answerability"] is not None and state not in ("validation_failed", "not_run"):
                abstains = state in ("model_abstention", "no_sources")
                decision = int(abstains == (q["answerability"] == "unanswerable"))
            add("answerability_decision_correct", decision, note="Decisione tecnica di astensione, non accuratezza della risposta")
    docs = {c.metadata["filename"] for c in catalog.chunks}
    rows.append({"item_id": "whole_run", "origin": run["origin"], "metric": "global_document_coverage",
                 "value": len(union) / len(docs) if docs and successful_retrievals else None, "unit": "ratio", "note": "Unione PDF / PDF indicizzati nello snapshot, solo retrieval completati"})
    return rows
