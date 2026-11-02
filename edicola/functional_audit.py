"""Regressioni locali sui testi indicizzati; API solo con flag e limite espliciti."""

import argparse
from dataclasses import asdict
import json
import logging
import hashlib
import re
from pathlib import Path
from types import SimpleNamespace
from pypdf import PdfReader

from edicola.api_guard import PermissionDenied, permission_scope
from edicola.context_selection import fit_context
from edicola.editorial_selection import read_catalog
from edicola.knowledge_relevance import Topic, select_topic_chunks
from edicola.knowledge_validation import validate_map, validate_timeline
from edicola.map_literal import literal_candidates
from edicola.rag import Source

CASES = {"timeline": "Proteste a Pescara", "map": "Dibattito relativo alla chiusura dei tribunali abruzzesi",
         "chat": "Quali sono le principali criticità della sanità abruzzese?"}


def has_health_quantity(text):
    """Una data editoriale non attesta la presenza di dati numerici sulla sanità."""
    return bool(re.search(r"\b\d+(?:[.,]\d+)*\s*(?:%(?!\w)|(?:posti\s+letto|milioni|miliardi|euro|medici|infermieri|pazienti|ore|giorni)\b)", text, re.I))


def local_report(root):
    """Replay letterale esplicito: non simula un output realmente ottenuto da Gemini."""
    catalog = read_catalog(root)
    pdf_checks = {}
    report = {"stage": "local_literal_replay", "indexed": len(catalog.chunks), "total": catalog.coverage["total"], "cases": {}}
    for kind, query in CASES.items():
        topic = Topic(query, catalog.chunks)
        ranked = select_topic_chunks(topic, catalog.chunks, [], len(catalog.chunks), preserve_editions=True)
        sources = [Source(f"S{i}", c.id, c.metadata["filename"], c.metadata["page"], c.text, 0.) for i, c in enumerate(ranked, 1)]
        kept, _ = fit_context(sources, lambda items: json.dumps([asdict(s) for s in items], ensure_ascii=False), 7000)
        row = {"candidates": len(sources), "included": len(kept), "discarded_for_context": len(sources)-len(kept),
               "editions": sorted({s.filename for s in kept}), "pages": sorted({s.page for s in kept})}
        references = 0
        incoming = (root / "data/incoming").resolve()
        for source in kept:
            chunk = next(c for c in ranked if c.id == source.chunk_id)
            if source.filename not in pdf_checks:
                path = incoming / source.filename
                valid = (path.resolve().parent == incoming and not path.is_symlink() and path.suffix.lower() == ".pdf"
                         and not any(char in source.filename for char in "/\\:\0"))
                try:
                    valid = valid and hashlib.sha256(path.read_bytes()).hexdigest() == chunk.metadata["pdf_sha256"]
                    pages = 0
                    if valid:
                        with path.open("rb") as stream:
                            pages = len(PdfReader(stream).pages)
                except (OSError, ValueError):
                    pages = 0
                pdf_checks[source.filename] = pages
            references += 0 < source.page <= pdf_checks[source.filename]
        row["verified_pdf_page_references"] = references
        if kind == "timeline":
            events = [{"title": {"text": "Sviluppo documentato", "evidence": [{"source_id": s.id, "quote": s.text}]},
                       "description": {"text": s.text, "evidence": [{"source_id": s.id, "quote": s.text}]},
                       "event_date": None, "date_evidence": {"source_id": s.id, "quote": s.text}} for s in kept[:12]]
            data, diagnostics = validate_timeline({"events": events}, kept, catalog.coverage)
            row.update(dated=len(data["events"]), undated=len(data["undated_events"]), diagnostics=diagnostics)
        elif kind == "map":
            # Etichette note dal caso dell'utente: incluse solo se letterali nel contesto.
            labels = ("emendamento", "Commissione Giustizia", "Guerino Testa", "Partito Democratico",
                      "Michele Fina", "Etelwardo Sigismondi", "Consiglio dei ministri", "disegno di legge")
            nodes = []
            for label in labels:
                source = next((s for s in kept if label in s.text), None)
                if source:
                    nodes.append({"id": f"N{len(nodes)+1}", "kind": "concept", "label": {
                        "text": label, "evidence": [{"source_id": source.id, "quote": source.text}]}})
            data, _ = validate_map({"nodes": nodes, "edges": []}, kept)
            contexts = {s.id: next(c.metadata for c in ranked if c.id == s.chunk_id) for s in kept}
            extra = literal_candidates(data["nodes"], kept, contexts)
            data, diagnostics = validate_map({"nodes": nodes, "edges": extra}, kept, contexts=contexts)
            row.update(nodes=len(data["nodes"]), edges=len(data["edges"]), diagnostics=diagnostics)
        else:
            row["passages_with_health_quantities"] = sum(has_health_quantity(s.text) for s in kept)
        report["cases"][kind] = row
    return report


class LimitedClient:
    """Limite duro dei tentativi SDK: un embedding e una generazione per caso."""
    def __init__(self, client, limit):
        self.client, self.limit, self.calls, self.seen = client, limit, 0, set()
        self.failures = []
        self.case = ""
        self.models = SimpleNamespace(embed_content=self.embed, generate_content=self.generate)

    def call(self, method, **kwargs):
        from edicola.api_guard import require_permission
        require_permission("text")
        identity = (self.case, method)
        if self.calls >= self.limit or identity in self.seen:
            raise PermissionDenied("Limite del collaudo raggiunto; nessun retry inviato.")
        self.seen.add(identity)
        self.calls += 1
        try:
            return getattr(self.client.models, method)(**kwargs)
        except Exception as exc:
            code = getattr(exc, "code", None)
            self.failures.append({"case": self.case, "method": method, "http_status": code if isinstance(code, int) else None})
            raise

    def embed(self, **kwargs):
        return self.call("embed_content", **kwargs)

    def generate(self, **kwargs):
        return self.call("generate_content", **kwargs)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--authorize-external", action="store_true")
    parser.add_argument("--max-api-calls", type=int, default=0)
    args = parser.parse_args(argv)
    if args.authorize_external and args.max_api_calls != 6:
        parser.error("Il collaudo delle tre richieste richiede un limite esplicito di sei tentativi SDK.")
    logging.basicConfig(level=logging.INFO)
    report = local_report(args.root)
    directory = args.root / ".private-runtime/functional-audit"
    directory.mkdir(parents=True, exist_ok=True)
    if args.authorize_external:
        from google import genai
        from google.genai import types
        from edicola.embeddings import api_key, GeminiEmbedder
        from edicola.knowledge import generate_knowledge
        from edicola.rag import ask_question
        try:
            client = genai.Client(api_key=api_key(args.root), vertexai=False,
                http_options=types.HttpOptions(timeout=30000, retry_options=types.HttpRetryOptions(attempts=1)))
        except Exception as exc:
            report.update(live={"status": "not_started", "error_class": type(exc).__name__}, api_attempts=0)
            (directory / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1
        limited = LimitedClient(client, args.max_api_calls)
        report["live"] = {}
        try:
            with permission_scope(lambda: args.authorize_external, "text"):
                for kind, query in CASES.items():
                    limited.case = kind
                    embedder = GeminiEmbedder("configured", client=limited, max_attempts=1)
                    try:
                        if kind == "chat":
                            result = ask_question(query, root=args.root, authorize_external=True, client=limited, embedder=embedder)
                        else:
                            result = generate_knowledge(kind, query, root=args.root, authorize_external=True,
                                client=limited, embedder=embedder, cache_enabled=False)
                        (directory / f"{kind}.json").write_text(json.dumps(asdict(result), ensure_ascii=False, indent=2), encoding="utf-8")
                        useful = result.sufficient if kind == "chat" else bool(result.data.get("events") or result.data.get("undated_events") or result.data.get("nodes"))
                        report["live"][kind] = {"status": "validated_output" if useful else "no_valid_items", "sources": len(result.sources)}
                    except Exception as exc:
                        # Solo la classe; mai messaggi SDK, chiavi o payload.
                        report["live"][kind] = {"status": "failed", "error_class": type(exc).__name__}
        finally:
            client.close()
        report["api_attempts"] = limited.calls
        report["sdk_failures"] = limited.failures
    (directory / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
