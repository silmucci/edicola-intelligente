"""Benchmark backend per prestazioni e scalabilità di Edicola Digitale Intelligente.

Nessuna API in preview/check. Il carico reale richiede --run e
--authorize-external, con tetti espliciti su richieste, rate e concorrenza.
Non misura il rendering Streamlit né la rete del browser.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
import sys
import time
from threading import Lock
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOPICS = {
    "chat": [
        "Quali aumenti degli abbonamenti TUA L'Aquila–Roma sono riportati?",
        "Che cosa riportano i quotidiani sull'inchiesta ASL di Pescara?",
        "Quali informazioni sono riportate sul corteo USB a Pescara?",
    ],
    "briefing": ["sanità", "trasporti", "lavoro", "scuola"],
    "timeline": [
        "inchiesta ASL di Pescara",
        "trasporti TUA L'Aquila Roma",
        "corteo USB a Pescara",
        "sanità in Abruzzo",
    ],
    "map": [
        "inchiesta ASL di Pescara",
        "trasporti TUA L'Aquila Roma",
        "corteo USB a Pescara",
        "sanità in Abruzzo",
    ],
    "podcast": ["sanità", "trasporti", "lavoro", "scuola"],
}
CLASSES = tuple(TOPICS)


def parse_rates(value):
    try:
        rates = [int(x.strip()) for x in value.split(",")]
    except ValueError:
        raise ValueError("Le intensità devono essere interi separati da virgole.") from None
    if not rates or len(rates) > 5 or any(not 1 <= x <= 6 for x in rates):
        raise ValueError("Usare da 1 a 5 livelli, ciascuno tra 1 e 6 richieste/minuto.")
    if rates != sorted(rates):
        raise ValueError("I livelli devono essere in ordine crescente.")
    return rates


def parse_mix(value, include_podcast):
    weights = {}
    for item in value.split(","):
        name, sep, weight = item.strip().partition(":")
        try:
            n = int(weight) if sep else 1
        except ValueError:
            raise ValueError("Peso del mix non valido.") from None
        if name not in CLASSES or not 1 <= n <= 10 or name in weights:
            raise ValueError("Classi o pesi non validi nel mix.")
        if name == "podcast" and not include_podcast:
            raise ValueError("Il podcast richiede anche --include-podcast (TTS a consumo).")
        weights[name] = n
    if not weights:
        raise ValueError("Specificare almeno una classe.")
    return weights


def load_questions(root):
    questions = []
    path = root / "evaluation/data/ground_truth_edicola_50_casi.csv"
    if path.is_file():
        with path.open(encoding="utf-8-sig", newline="") as stream:
            questions = [row["Domanda"].strip() for row in csv.DictReader(stream)
                         if row.get("Domanda", "").strip()]
    return {**TOPICS, "chat": questions or TOPICS["chat"]}


def make_plan(rates, phase_seconds, max_requests, weights, workload):
    """Arrivi a intervalli regolari, indipendenti dal termine dei task precedenti."""
    if phase_seconds < 60 or phase_seconds > 600:
        raise ValueError("Ogni fase deve durare tra 60 e 600 secondi.")
    counts = Counter()
    tasks = []
    for phase, rpm in enumerate(rates, start=1):
        n = rpm * phase_seconds // 60
        for j in range(n):
            if len(tasks) >= max_requests:
                return tasks
            # Distribuzione pesata progressiva: evita blocchi della stessa classe.
            name = min(weights, key=lambda c: (counts[c] + 1) / weights[c])
            index = counts[name] % len(workload[name])
            tasks.append({
                "request_id": f"R{len(tasks) + 1:03d}",
                "phase": phase,
                "target_rpm": rpm,
                "class": name,
                "prompt": workload[name][index],
                "scheduled_offset_s": phase_seconds * (phase - 1) + j * 60 / rpm,
            })
            counts[name] += 1
    return tasks


def check_environment(root):
    """Controlli locali: non invia PDF, prompt o embedding a servizi esterni."""
    data = root / "data"
    missing = [str(p.relative_to(root)) for p in
               [data / "archive.sqlite3", data / "incoming", data / "chroma"]
               if not p.exists()]
    if missing:
        raise RuntimeError("Archivio locale incompleto: " + ", ".join(missing) +
                           ". I PDF/Chroma non sono nel repository Git.")
    if not list((data / "incoming").glob("*.pdf")):
        raise RuntimeError("Nessun PDF in data/incoming. Ripristinare il corpus usato nella tesi.")
    from edicola.archive import read_active_chunks
    from edicola.vectorstore import open_collection
    from edicola.embeddings import api_key
    chunks, warnings = read_active_chunks(data / "archive.sqlite3", data / "incoming")
    if warnings:
        raise RuntimeError("Archivio non coerente; aggiornare il registro prima dei test.")
    collection = open_collection(data / "chroma", create=False)
    indexed = collection.count() if collection is not None else 0
    if not chunks or not indexed:
        raise RuntimeError("Chunk indicizzati mancanti. Ripristinare lo snapshot Chroma.")
    if not api_key(root):
        raise RuntimeError("GEMINI_API_KEY non configurata; nessuna richiesta inviata.")
    return {"active_chunks": len(chunks), "chroma_vectors": indexed,
            "pdf_count": len(list((data / "incoming").glob("*.pdf")))}


class AttemptBudget:
    """Tetto condiviso tra thread, inclusi retry e modelli di fallback."""

    def __init__(self, limit):
        self.limit = limit
        self.used = 0
        self.lock = Lock()

    def claim(self):
        with self.lock:
            if self.used >= self.limit:
                raise RuntimeError("Limite massimo di invocazioni SDK raggiunto.")
            self.used += 1


def _metered_clients(key, events, budget):
    """Conta invocazioni SDK reali, inclusi tentativi aggiuntivi e fallback."""
    from google import genai
    from google.genai import errors, types
    import httpx

    class Models:
        def __init__(self, real, purpose):
            self.real, self.purpose = real, purpose

        def _call(self, method, kwargs):
            start = time.perf_counter()
            event = {"operation": "embedding" if method == "embed_content" else self.purpose,
                     "model": kwargs.get("model", ""), "outcome": "ok", "http_status": None}
            budget.claim()
            try:
                return getattr(self.real, method)(**kwargs)
            except errors.APIError as exc:
                event["outcome"], event["http_status"] = "api_error", exc.code
                raise
            except (httpx.TransportError, ConnectionError, TimeoutError, OSError):
                event["outcome"] = "transport_error"
                raise
            except Exception:
                event["outcome"] = "other_error"
                raise
            finally:
                event["duration_s"] = round(time.perf_counter() - start, 4)
                events.append(event)

        def embed_content(self, **kwargs):
            return self._call("embed_content", kwargs)

        def generate_content(self, **kwargs):
            return self._call("generate_content", kwargs)

    class Client:
        def __init__(self, purpose, timeout):
            self.original = genai.Client(
                api_key=key, vertexai=False,
                http_options=types.HttpOptions(
                    timeout=timeout, retry_options=types.HttpRetryOptions(attempts=1)))
            self.models = Models(self.original.models, purpose)

        def close(self):
            self.original.close()

    return Client("generation", 30_000), Client("tts", 120_000)


def perform_one(task, root, run_start_perf, budget):
    """Usa le vere funzioni backend e un client SDK misurato per ogni invio."""
    from edicola.api_guard import permission_scope
    from edicola.embeddings import GeminiEmbedder, api_key
    from edicola.rag import ask_question
    from edicola.editorial import generate_product
    from edicola.press_review import ReviewSelection
    from edicola.knowledge import generate_knowledge
    from edicola.standalone_podcast import generate_standalone_podcast

    started = time.perf_counter()
    events = []
    result = None
    error_kind = None
    clients = []
    try:
        key = api_key(root)
        text_client, tts_client = _metered_clients(key, events, budget)
        clients = [text_client, tts_client]
        embedder = GeminiEmbedder(key, client=text_client)
        kind, prompt = task["class"], task["prompt"]
        # Il comando --authorize-external è l'autorizzazione esplicita CLI.
        with permission_scope(lambda: True, "text"):
            if kind == "chat":
                result = ask_question(prompt, authorize_external=True, root=root,
                                      client=text_client, embedder=embedder)
            elif kind == "briefing":
                result = generate_product("briefing", authorize_external=True, root=root,
                                          client=text_client,
                                          selection=ReviewSelection(keyword=prompt))
            elif kind in {"timeline", "map"}:
                result = generate_knowledge(kind, prompt, authorize_external=True, root=root,
                                            client=text_client, embedder=embedder)
            elif kind == "podcast":
                result = generate_standalone_podcast(
                    root=root, topic=prompt, authorize_text=True, authorize_audio=True,
                    text_check=lambda: True, audio_check=lambda: True,
                    client=text_client, tts_client=tts_client, embedder=embedder)
        outcome = "ok"
    except Exception as exc:
        # Mai scrivere eccezioni/prompt/chiavi nei report di errore.
        outcome = "error"
        error_kind = type(exc).__name__
    finally:
        for client in clients:
            try:
                client.close()
            except Exception:
                pass
    ended = time.perf_counter()
    actual_start_offset = started - run_start_perf
    completion_offset = ended - run_start_perf
    calls = Counter(e["operation"] for e in events)
    statuses = Counter(str(e["http_status"]) for e in events if e["http_status"] is not None)
    sufficient = getattr(result, "sufficient", None)
    if task["class"] in {"timeline", "map"} and result is not None:
        sufficient = bool(getattr(result, "sources", [])) and bool(getattr(result, "data", {}))
    return {
        **task,
        "outcome": outcome, "error_kind": error_kind,
        "cache_hit": bool(getattr(result, "from_cache", False)) if result is not None else None,
        "content_available": sufficient,
        "actual_start_offset_s": round(actual_start_offset, 4),
        "completion_offset_s": round(completion_offset, 4),
        "queue_delay_s": round(max(0, actual_start_offset - task["scheduled_offset_s"]), 4),
        "processing_s": round(ended - started, 4),
        "end_to_end_s": round(max(0, completion_offset - task["scheduled_offset_s"]), 4),
        "api_attempts": len(events),
        "embedding_attempts": calls["embedding"],
        "generation_attempts": calls["generation"],
        "tts_attempts": calls["tts"],
        "http_429_attempts": statuses["429"],
        "api_errors": sum(e["outcome"] != "ok" for e in events),
        # Conteggi per modello e status senza registrare prompt o payload.
        "api_events": events,
    }


def percentile(values, quantile):
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(quantile * len(ordered)) - 1)], 3)


def summarize(rows, rates, phase_seconds):
    def stats(group):
        completed = [r for r in group if r["outcome"] == "ok"]
        latencies = [r["end_to_end_s"] for r in completed]
        return {
            "scheduled": len(group), "successful": len(completed),
            "failed": len(group) - len(completed),
            "success_rate": round(len(completed) / len(group), 3) if group else None,
            "cache_hits": sum(r["cache_hit"] is True for r in completed),
            "api_attempts": sum(r["api_attempts"] for r in group),
            "http_429_attempts": sum(r["http_429_attempts"] for r in group),
            "latency_mean_s": round(statistics.mean(latencies), 3) if latencies else None,
            "latency_p50_s": percentile(latencies, .50),
            "latency_p95_s": percentile(latencies, .95),
        }
    by_phase = {}
    for phase, rpm in enumerate(rates, 1):
        group = [r for r in rows if r["phase"] == phase]
        left, right = (phase - 1) * phase_seconds, phase * phase_seconds
        completed_in_window = sum(left <= r["completion_offset_s"] < right and
                                  r["outcome"] == "ok" for r in rows)
        by_phase[str(phase)] = {
            "target_rpm": rpm, **stats(group),
            "completed_in_phase_window": completed_in_window,
            "observed_completions_per_min": round(completed_in_window * 60 / phase_seconds, 3),
        }
    return {
        "total": stats(rows),
        "by_class": {name: stats([r for r in rows if r["class"] == name])
                     for name in CLASSES if any(r["class"] == name for r in rows)},
        "by_phase": by_phase,
        "note": ("Latenza end-to-end backend: attesa dalla schedulazione al completamento, "
                 "esclusa UI Streamlit. Throughput: completamenti effettivi nelle finestre "
                 "temporali, anche di richieste della fase precedente. "
                 "P95 su pochi campioni è solo esplorativo. Le cache sono conservate "
                 "e i cache hit sono distinti, non cancellati."),
    }


def save_outputs(output, rows, summary, metadata):
    output.mkdir(parents=True, exist_ok=False)
    path = output / "requests.csv"
    fields = [key for key in rows[0] if key != "api_events"]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row[k] for k in fields})
    with (output / "summary.json").open("w", encoding="utf-8") as stream:
        json.dump({"metadata": metadata, "metrics": summary}, stream,
                  ensure_ascii=False, indent=2)
    with (output / "api_attempts.json").open("w", encoding="utf-8") as stream:
        json.dump([{ "request_id": r["request_id"], "events": r["api_events"]}
                   for r in rows], stream, ensure_ascii=False, indent=2)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--preview", action="store_true", help="Mostra il piano, nessuna API.")
    action.add_argument("--check", action="store_true", help="Controlla archivio/indice/chiave, nessuna API.")
    action.add_argument("--run", action="store_true", help="Esegue carico reale autorizzato.")
    parser.add_argument("--authorize-external", action="store_true")
    parser.add_argument("--include-podcast", action="store_true", help="Abilita TTS reale, potenzialmente costoso.")
    parser.add_argument("--rates", default="1,2,3", help="Richieste al minuto per fase (max 6).")
    parser.add_argument("--phase-seconds", type=int, default=60)
    parser.add_argument("--max-requests", type=int, default=6)
    parser.add_argument("--max-in-flight", type=int, default=2)
    parser.add_argument("--max-api-attempts", type=int, default=24,
                        help="Tetto totale di invocazioni SDK, inclusi retry e fallback.")
    parser.add_argument("--mix", default="chat:2,briefing:1,timeline:1,map:1")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    if not 1 <= args.max_requests <= 30 or not 1 <= args.max_in_flight <= 3 or not 1 <= args.max_api_attempts <= 100:
        parser.error("Limiti: 1–30 richieste, 1–3 concorrenti e 1–100 invocazioni SDK.")
    try:
        rates = parse_rates(args.rates)
        weights = parse_mix(args.mix, args.include_podcast)
        workload = load_questions(args.root)
        plan = make_plan(rates, args.phase_seconds, args.max_requests, weights, workload)
    except ValueError as exc:
        parser.error(str(exc))
    if args.preview:
        print(json.dumps({"estimated_requests": len(plan), "phase_seconds": args.phase_seconds,
                          "plan": plan}, ensure_ascii=False, indent=2))
        return 0
    if args.run and not args.authorize_external:
        parser.error("--run richiede --authorize-external: invia domande/passaggi alle API Gemini.")
    try:
        environment = check_environment(args.root)
    except (RuntimeError, OSError, ValueError) as exc:
        parser.exit(2, f"Controllo non superato: {exc}\nNessuna chiamata API inviata.\n")
    if args.check:
        print(json.dumps({"status": "ready", **environment}, indent=2))
        return 0
    output = args.out or (args.root / "evaluation/results" /
                          ("performance-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")))
    if output.exists():
        parser.error("La cartella di output esiste già: usare una nuova destinazione.")
    print(f"Esecuzione autorizzata: {len(plan)} richieste, massimo {args.max_in_flight} concorrenti.",
          flush=True)
    start_perf = time.perf_counter()
    start_wall = datetime.now(timezone.utc).isoformat()
    budget = AttemptBudget(args.max_api_attempts)
    with ThreadPoolExecutor(max_workers=args.max_in_flight) as executor:
        futures = []
        for task in plan:
            delay = task["scheduled_offset_s"] - (time.perf_counter() - start_perf)
            if delay > 0:
                time.sleep(delay)
            futures.append(executor.submit(perform_one, task, args.root, start_perf, budget))
        rows = [future.result() for future in futures]
    rows.sort(key=lambda r: r["request_id"])
    summary = summarize(rows, rates, args.phase_seconds)
    save_outputs(output, rows, summary, {
        "started_utc": start_wall, "rates": rates,
        "phase_seconds": args.phase_seconds, "mix": weights,
        "max_in_flight": args.max_in_flight, "max_api_attempts": args.max_api_attempts,
        "actual_api_claims": budget.used, "environment": environment,
        "backend_only": True, "live_api": True,
    })
    print(json.dumps({"output": str(output), "metrics": summary},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
