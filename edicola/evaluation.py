"""CLI sperimentale separata dall'app. Le sole API possibili sono in benchmark."""

import argparse
import json
import os
import platform
import time
from collections import Counter
from dataclasses import asdict, replace
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace

import httpx
from google import genai
from google.genai import errors, types

from edicola.editorial_selection import near_duplicate, read_catalog
from edicola.embeddings import DIMENSIONS, MODEL, GeminiEmbedder, api_key
from edicola.evaluation_data import (CRITERIA, RUBRICS, SCALE, dataset_template, digest, read_json,
    snapshot, validate_dataset, validate_snapshot, write_json)
from edicola.evaluation_metrics import rag_assessment, score_run, sources_from_hits
from edicola.evaluation_report import REVIEW_FIELDS, read_reviews, render_report, review_rows, write_csv
from edicola.indexing import ROOT
from edicola.personalization import recommend
from edicola.profiles import Profile, validate as validate_profile
from edicola.rag import DEFAULT_MODEL, build_prompt, generate_response, response_schema
from edicola.search import semantic_search


class MeasuredModels:
    """Misura ogni invocazione SDK, senza intercettare o stampare payload/chiavi."""

    def __init__(self, client, events):
        self.client, self.events = client, events

    def call(self, method, phase, kwargs):
        start = time.perf_counter()
        event = {"phase": phase, "model": kwargs["model"], "http_status": None, "outcome": "error", "error_category": None}
        try:
            result = getattr(self.client.models, method)(**kwargs)
            event["outcome"] = "ok"
            # Non assumere HTTP 200 quando l'SDK non fornisce lo status di successo.
            return result
        except errors.APIError as exc:
            event["http_status"] = exc.code
            event["error_category"] = "http"
            raise
        except (httpx.TransportError, ConnectionError, TimeoutError, OSError):
            event["error_category"] = "transport"
            raise
        except Exception:
            event["error_category"] = "sdk_or_local"
            raise
        finally:
            event["seconds"] = time.perf_counter() - start
            self.events.append(event)

    def embed_content(self, **kwargs):
        return self.call("embed_content", "query_embedding", kwargs)

    def generate_content(self, **kwargs):
        return self.call("generate_content", "generation", kwargs)


def provenance():
    modules = ("search.py", "rag.py", "embeddings.py", "evaluation.py", "evaluation_data.py", "evaluation_metrics.py", "evaluation_report.py", "personalization.py", "editorial_selection.py", "profiles.py", "archive.py", "vectorstore.py", "indexing.py")
    return {"utc": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(),
        "packages": {p: version(p) for p in ("google-genai", "chromadb", "streamlit", "altair")},
        "code_sha256": digest({p: (Path(__file__).parent / p).read_text(encoding="utf-8") for p in modules})}


def benchmark(root, dataset, frozen, *, mode, k, limit, repeats=1, authorize_external=False, client=None):
    if not authorize_external:
        raise ValueError("Benchmark reale: occorre --authorize-external per inviare domande e, nel RAG, passaggi a Gemini.")
    validate_dataset(dataset, frozen)
    if mode not in ("retrieval", "rag") or type(k) is not int or not 1 <= k <= 5:
        raise ValueError("Modalità o K non validi.")
    if type(limit) is not int or not 1 <= limit <= 100 or type(repeats) is not int or not 1 <= repeats <= 10:
        raise ValueError("Specificare un limite 1–100 e ripetizioni 1–10.")
    current = snapshot(read_catalog(root), frozen["origin"])
    if current["snapshot_id"] != frozen["snapshot_id"]:
        raise ValueError("Archivio cambiato/non aggiornato: esportare un nuovo snapshot e rivedere le annotazioni prima delle API.")
    key = api_key(root)
    model = os.environ.get("GEMINI_RAG_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    own_client = client is None
    if own_client and current["chunks"]:
        if not key:
            raise ValueError("Configurare GEMINI_API_KEY in .env prima del benchmark.")
        client = genai.Client(api_key=key, vertexai=False, http_options=types.HttpOptions(
            timeout=30000, retry_options=types.HttpRetryOptions(attempts=1)))
    records = []
    try:
        for q in dataset["questions"][:limit]:
            for repetition in range(1, repeats + 1):
                events = []
                proxy = SimpleNamespace(models=MeasuredModels(client, events))
                embedder = GeminiEmbedder(key or "injected-client", client=proxy)
                record = {"question_id": q["id"], "repeat": repetition, "status": "error", "retrieval_status": "error",
                    "retrieved": [], "raw_response": None, "answer": None, "response_state": "not_run",
                    "retrieval_seconds": None, "generation_seconds": None, "total_seconds": None,
                    "api_events": events, "error_phase": None, "error_type": None}
                start, phase_start, phase = time.perf_counter(), None, "retrieval"
                try:
                    phase_start = time.perf_counter()
                    hits = semantic_search(q["question"], authorize_external=True, root=root, embedder=embedder, top_k=k)
                    record["retrieval_seconds"] = time.perf_counter() - phase_start
                    record.update(retrieved=hits, retrieval_status="ok")
                    if mode == "rag":
                        sources = sources_from_hits(hits)
                        phase = "generation"
                        if sources:
                            phase_start = time.perf_counter()
                            record["raw_response"] = generate_response(proxy, model, build_prompt(q["question"], sources), response_schema(sources))
                            record["generation_seconds"] = time.perf_counter() - phase_start
                        phase = "validation"
                        state, checked = rag_assessment(record["raw_response"], sources)
                        record["response_state"] = state
                        record["answer"] = checked.answer if checked else None
                    record["status"] = "ok"
                except Exception:
                    # Codici HTTP solo dagli eventi misurati, mai str(exception)/URL/token.
                    record["error_phase"], record["error_type"] = phase, "request_or_local_error"
                    if phase in ("retrieval", "generation"):
                        record[f"{phase}_seconds"] = time.perf_counter() - phase_start
                finally:
                    record["total_seconds"] = time.perf_counter() - start
                    records.append(record)
    finally:
        if own_client and client is not None:
            try:
                client.close()
            except Exception:
                pass  # Un errore SDK di chiusura non deve perdere le misure raccolte.
    return {"schema_version": 1, "origin": frozen["origin"], "mode": mode, "top_k": k,
        "snapshot_id": frozen["snapshot_id"], "dataset_id": digest(dataset), "provenance": provenance(),
        "configuration": {"embedding_model": MODEL, "dimensions": DIMENSIONS, "generation_model": model if mode == "rag" else None,
            "sdk_attempts": 1, "application_attempts_max_per_phase": 3, "limit": limit, "repeats": repeats,
            "sampling": "primi N nel dataset, ordine originale", "generation_cache": "non utilizzata",
            "local_cache": "non controllata; registrare condizioni cold/warm nel protocollo", "ui_included": False},
        "records": records}


def personalization_experiment(frozen, profiles_data):
    catalog = validate_snapshot(frozen)
    rows, records, seen = [], [], set()
    if profiles_data.get("schema_version") != 1 or len(profiles_data.get("profiles", [])) < 2:
        raise ValueError("Compilare almeno due profili demo per confrontarli.")
    for data in profiles_data["profiles"]:
        profile = Profile(**data)
        validate_profile(profile)
        if not profile.interests or profile.user_id in seen or profile.saved:
            raise ValueError("Profili demo: interessi necessari, ID distinti e saved vuoto; nessun profilo personale viene letto.")
        seen.add(profile.user_id)
        before = recommend(catalog, replace(profile, feedback={}))
        after = recommend(catalog, profile)
        for label, recommendations in (("before_feedback", before), ("after_feedback", after)):
            ids = [r.chunk.id for r in recommendations]
            matched = {t for r in recommendations for t in r.topics}
            active = {t for t in profile.interests if label == "before_feedback" or profile.feedback.get(t) != -1}
            docs = {r.chunk.metadata["filename"] for r in recommendations}
            all_docs = {c.metadata["filename"] for c in catalog.chunks}
            duplicates = sum(any(near_duplicate(r.chunk.text, earlier.chunk.text) for earlier in recommendations[:i]) for i, r in enumerate(recommendations))
            values = {"interest_lexical_coverage": len(matched & active) / len(active) if active else None,
                "recommendation_document_coverage": len(docs) / len(all_docs) if all_docs else None,
                "recommendation_duplicate_fraction": duplicates / len(ids) if ids else None}
            for metric, value in values.items():
                rows.append({"item_id": f"{profile.user_id}:{label}", "origin": frozen["origin"], "metric": metric + ":" + label, "value": value, "unit": "ratio", "note": "Regole locali, non apprendimento automatico"})
        a, b = [r.chunk.id for r in before], [r.chunk.id for r in after]
        changed = sum((a[i] if i < len(a) else None) != (b[i] if i < len(b) else None) for i in range(max(len(a), len(b))))
        rows.append({"item_id": profile.user_id, "origin": frozen["origin"], "metric": "feedback_rank_change_fraction",
            "value": changed / max(len(a), len(b)) if a or b else None, "unit": "ratio", "note": "Posizioni diverse, inclusi inserimenti/rimozioni"})
        records.append({"profile": asdict(profile), "before": [asdict(r) for r in before], "after": [asdict(r) for r in after]})
    for i, first in enumerate(records):
        for second in records[i + 1:]:
            a, b = {r["chunk"]["id"] for r in first["after"]}, {r["chunk"]["id"] for r in second["after"]}
            rows.append({"item_id": first["profile"]["user_id"] + "/" + second["profile"]["user_id"], "origin": frozen["origin"],
                "metric": "between_profiles_jaccard_distance", "value": 1 - len(a & b) / len(a | b) if a | b else None,
                "unit": "ratio", "note": "Diversità di insiemi, non qualità o pertinenza"})
    return {"snapshot_id": frozen["snapshot_id"], "origin": frozen["origin"], "provenance": provenance(), "records": records}, rows


def report_run(out, dataset, frozen, run, reviews=None):
    warnings = validate_dataset(dataset, frozen)
    catalog = validate_snapshot(frozen)
    rows = score_run(dataset, frozen, run, catalog)
    run_id = digest(run)
    items = [f"{r['question_id']}#{r['repeat']}" for r in run["records"]]
    if reviews:
        human = read_reviews(reviews, run_id, set(items))
        if any(r["origin"] != run["origin"] for r in human):
            raise ValueError("Giudizi umani con provenienza diversa dalla run.")
        rows.extend(human)
    templates = [r for item in items for r in review_rows("rag", item, run["origin"], run_id)] if run["mode"] == "rag" else []
    errors_seen = Counter(e["phase"] + ":" + str(e["http_status"]) for r in run["records"] for e in r["api_events"] if e["http_status"] is not None)
    return render_report(out, rows, metadata={k: v for k, v in run.items() if k != "records"} | {
        "run_id": run_id, "samples": len(items), "http_status_counts": dict(errors_seen),
        "archive_coverage": frozen["coverage"], "dataset_warnings": warnings}, warnings=warnings, review_template=templates)


def new_directory(path):
    path.mkdir(parents=True, exist_ok=False)
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Valutazione locale del prototipo; API solo nel sottocomando benchmark autorizzato.")
    parser.add_argument("--root", type=Path, default=ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("snapshot", help="Esporta solo chunk già indicizzati e metadati, senza API.")
    export.add_argument("--out", type=Path, required=True)
    init = commands.add_parser("init", help="Template vuoti di dataset, profili e criteri umani.")
    init.add_argument("--snapshot", type=Path, required=True)
    init.add_argument("--out", type=Path, required=True)
    for name in ("validate", "benchmark", "score"):
        p = commands.add_parser(name)
        p.add_argument("--snapshot", type=Path, required=True)
        p.add_argument("--dataset", type=Path, required=True)
        if name != "validate":
            p.add_argument("--out", type=Path, required=True)
        if name == "benchmark":
            p.add_argument("--mode", choices=("retrieval", "rag"), required=True)
            p.add_argument("--k", type=int, default=3)
            p.add_argument("--limit", type=int, required=True)
            p.add_argument("--repeat", type=int, default=1)
            p.add_argument("--authorize-external", action="store_true")
        if name == "score":
            p.add_argument("--run", type=Path, required=True)
            p.add_argument("--reviews", type=Path)
    personal = commands.add_parser("personalization", help="Esperimento locale, senza API e senza modificare profili salvati.")
    personal.add_argument("--snapshot", type=Path, required=True)
    personal.add_argument("--profiles", type=Path, required=True)
    personal.add_argument("--out", type=Path, required=True)
    review = commands.add_parser("prepare-review", help="Scheda umana vuota per un prodotto già disponibile.")
    review.add_argument("--kind", choices=list(RUBRICS), required=True)
    review.add_argument("--item-id", required=True)
    review.add_argument("--origin", choices=("real", "simulated"), required=True)
    review.add_argument("--out", type=Path, required=True)
    human = commands.add_parser("reviews", help="Report delle sole valutazioni umane compilate.")
    human.add_argument("--sheet", type=Path, required=True)
    human.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "snapshot":
            if args.out.exists():
                raise ValueError("Il file snapshot esiste già: scegliere un nuovo nome.")
            frozen = snapshot(read_catalog(args.root))
            write_json(args.out, frozen)
            print(f"Snapshot locale: {len(frozen['chunks'])} chunk indicizzati; nessuna API.")
        elif args.command == "init":
            frozen = read_json(args.snapshot)
            validate_snapshot(frozen)
            out = new_directory(args.out)
            write_json(out / "dataset.json", dataset_template(frozen["snapshot_id"]))
            write_json(out / "profiles.json", {"schema_version": 1, "profiles": [asdict(Profile(user_id="demo-a")), asdict(Profile(user_id="demo-b"))]})
            write_json(out / "annotation-catalog.json", frozen)
            write_json(out / "rubrics.json", {"scale": SCALE, "criteria": CRITERIA, "products": RUBRICS})
            print("Template da compilare manualmente; nessun giudizio di rilevanza generato.")
        elif args.command in ("validate", "benchmark", "score"):
            frozen, dataset = read_json(args.snapshot), read_json(args.dataset)
            warnings = validate_dataset(dataset, frozen)
            if args.command == "validate":
                print(json.dumps({"questions": len(dataset["questions"]), "warnings": warnings}, ensure_ascii=False, indent=2))
            else:
                if args.command == "benchmark":
                    if not args.authorize_external:
                        raise ValueError("Usare --authorize-external per autorizzare il benchmark Gemini.")
                    if frozen["origin"] != "real":
                        raise ValueError("Il comando reale non invia snapshot simulati a Gemini.")
                    # Non avviare API se la destinazione è già occupata.
                    out = new_directory(args.out)
                    run = benchmark(args.root, dataset, frozen, mode=args.mode, k=args.k, limit=args.limit,
                                    repeats=args.repeat, authorize_external=True)
                    write_json(out / "run.json", run)
                else:
                    out = args.out
                    run = read_json(args.run)
                report_run(out, dataset, frozen, run, getattr(args, "reviews", None))
                print(f"Report: {out / 'report.md'}")
        elif args.command == "personalization":
            frozen = read_json(args.snapshot)
            experiment, rows = personalization_experiment(frozen, read_json(args.profiles))
            out = new_directory(args.out)
            write_json(out / "personalization.json", experiment)
            templates = [r for p in experiment["records"] for r in review_rows("personalization", p["profile"]["user_id"], frozen["origin"], digest(experiment))]
            render_report(out, rows, metadata={k: v for k, v in experiment.items() if k != "records"}, review_template=templates)
            print(f"Report locale: {out / 'report.md'}")
        elif args.command == "prepare-review":
            out = new_directory(args.out)
            rows = review_rows(args.kind, args.item_id, args.origin)
            write_csv(out / "human_review.csv", rows, REVIEW_FIELDS)
            write_json(out / "rubrics.json", {"scale": SCALE, "criteria": CRITERIA, "products": RUBRICS})
            print("Scheda vuota: allegare il prodotto e verificare le fonti originali.")
        elif args.command == "reviews":
            rows = read_reviews(args.sheet)
            render_report(new_directory(args.out), rows, metadata={"source": args.sheet.name, "type": "human_review"})
            print("Report dei giudizi presenti; i punteggi vuoti non sono stati stimati.")
        return 0
    except ValueError as exc:
        if args.command == "validate":
            print(f"Annotazioni non valide: {exc}")
        else:
            print("Valutazione non eseguita: controllare annotazioni, parametri e autorizzazione esplicita; nessun errore SDK viene mostrato.")
        return 1
    except (KeyError, TypeError, OSError, RuntimeError):
        # Nessun errore SDK grezzo o credenziale in output.
        print("Valutazione non eseguita: controllare file, annotazioni, snapshot, destinazione e autorizzazione. Usare validate per controllare il dataset.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
