"""Dossier e briefing limitati alle fonti indicizzate, con cache persistente."""

import hashlib
import json
import logging
import os
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from uuid import uuid4

from google import genai
from google.genai import types

from edicola.briefing import (MESSAGES, STRATEGY_VERSION, BriefingDraft,
                             SYSTEM_INSTRUCTION as BRIEFING_INSTRUCTION, fit_briefing_prompt,
                             generate_briefing_response, validate_briefing)
from edicola.editorial_selection import Catalog, balanced_briefing, read_catalog, topic_clusters
from edicola.embeddings import api_key
from edicola.indexing import ROOT
from edicola.rag import (DEFAULT_MODEL, INSUFFICIENT, RagError, Source, build_prompt,
                         generate_response, response_schema, validate_response)
from edicola.search import semantic_search


PROMPT_VERSION = 1
logger = logging.getLogger(__name__)


class EditorialError(RuntimeError):
    pass


@dataclass(frozen=True)
class EditorialConfig:
    dossier_chunks: int = 5
    briefing_chunks: int = 8
    max_source_chars: int = 8000
    topic_similarity: float = 0.82

    def __post_init__(self):
        if type(self.dossier_chunks) is not int or not 1 <= self.dossier_chunks <= 5:
            raise ValueError("Dossier: scegliere da 1 a 5 chunk.")
        if type(self.briefing_chunks) is not int or not 1 <= self.briefing_chunks <= 20:
            raise ValueError("Briefing: scegliere da 1 a 20 chunk.")
        if type(self.max_source_chars) is not int or not 2000 <= self.max_source_chars <= 20000:
            raise ValueError("Budget dei testi: scegliere da 2000 a 20000 caratteri.")
        if not 0.5 <= self.topic_similarity <= 0.99:
            raise ValueError("Soglia dei temi fuori intervallo.")

    @classmethod
    def from_env(cls):
        return cls(int(os.getenv("EDITORIAL_DOSSIER_CHUNKS", "5")),
                   int(os.getenv("EDITORIAL_BRIEFING_CHUNKS", "8")),
                   int(os.getenv("EDITORIAL_MAX_SOURCE_CHARS", "8000")),
                   float(os.getenv("EDITORIAL_TOPIC_SIMILARITY", "0.82")))


@dataclass
class EditorialResult:
    kind: str
    title: str
    sections: list[dict]
    sources: list[Source]
    used_source_ids: list[str]
    coverage: dict
    sufficient: bool
    message: str = ""
    from_cache: bool = False
    diagnostics: dict = field(default_factory=dict)


def cache_read(path: Path, key: str) -> EditorialResult | None:
    if not path.exists():
        return None
    with sqlite3.connect(path) as connection:
        row = connection.execute("SELECT result_json FROM products WHERE cache_key = ?", (key,)).fetchone()
    if row is None:
        return None
    data = json.loads(row[0])
    data["sources"] = [Source(**item) for item in data["sources"]]
    data["from_cache"] = True
    return EditorialResult(**data)


def cache_write(path: Path, key: str, result: EditorialResult):
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS products (
            cache_key TEXT PRIMARY KEY, result_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        connection.execute("INSERT OR REPLACE INTO products (cache_key, result_json) VALUES (?, ?)",
                           (key, json.dumps(asdict(result), ensure_ascii=False)))


def cache_key(kind: str, topic: str, model: str, config: EditorialConfig, catalog: Catalog, *, briefing_prompt_chars=14000) -> str:
    payload = {"version": STRATEGY_VERSION if kind == "briefing" else PROMPT_VERSION,
               "kind": kind, "topic": topic, "model": model,
               "config": asdict(config), "coverage": catalog.coverage,
               "chunks": sorted((chunk.id, chunk.fingerprint, chunk.metadata) for chunk in catalog.chunks)}
    if kind == "briefing":
        payload["briefing_prompt_chars"] = briefing_prompt_chars
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def briefing_result(draft: BriefingDraft, sources: list[Source], coverage: dict) -> EditorialResult:
    message = MESSAGES.get(draft.status, "")
    if draft.status == "partial_validation":
        rejected = draft.diagnostics.get("invalid_citations", 0) + draft.diagnostics.get("invalid_structure", 0)
        message = f"Briefing parziale: {rejected} notizie scartate per errori di formato o citazioni non valide."
    return EditorialResult("briefing", "Briefing delle notizie disponibili" if draft.sections else "Briefing non generato",
                           draft.sections, sources, draft.used_source_ids, coverage, bool(draft.sections), message,
                           diagnostics={"strategy": STRATEGY_VERSION, "status": draft.status, **draft.diagnostics})


def render_product(kind: str, raw: str, sources: list[Source], coverage: dict, groups: list[list[str]]) -> EditorialResult:
    """Ogni titolo e paragrafo passa attraverso il validatore RAG esistente."""
    if kind == "briefing":
        return briefing_result(validate_briefing(raw, sources), sources, coverage)
    fallback = EditorialResult(kind, "Informazioni insufficienti", [], sources, [], coverage, False, INSUFFICIENT)
    checked = validate_response(raw, sources)
    if not checked.sufficient:
        return fallback
    claims = json.loads(raw)["claims"]
    if kind == "dossier" and len(claims) != 7:
        return fallback

    def render(claim, allowed=sources):
        return validate_response(json.dumps({"sufficient": True, "claims": [claim]}), allowed)

    if kind == "dossier":
        parts = [render(claim).answer for claim in claims]
        return EditorialResult(kind, parts[0], [
            {"heading": "Introduzione", "text": parts[1]},
            {"heading": parts[2], "text": parts[3]},
            {"heading": parts[4], "text": parts[5]},
            {"heading": "Conclusioni", "text": parts[6]},
        ], sources, checked.used_source_ids, coverage, True)
    return fallback


def generate_product(kind: str, topic: str = "", *, authorize_external=False, root: Path = ROOT,
                     config: EditorialConfig | None = None, client=None) -> EditorialResult:
    if kind not in {"dossier", "briefing"}:
        raise EditorialError("Prodotto editoriale non riconosciuto.")
    if not authorize_external:
        raise EditorialError("Autorizzare l'invio a Gemini dell'argomento e dei passaggi selezionati.")
    topic = " ".join(topic.split()) if kind == "dossier" else ""
    if kind == "dossier" and (not topic or len(topic) > 500):
        raise EditorialError("Inserire un argomento da 1 a 500 caratteri.")
    own_client = False
    try:
        key = api_key(root)
        model = os.getenv("GEMINI_RAG_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
        config = config or EditorialConfig.from_env()
        prompt_budget = 14000
        if kind == "briefing":
            try:
                prompt_budget = int(os.getenv("EDITORIAL_BRIEFING_MAX_PROMPT_CHARS", "14000"))
            except ValueError:
                raise EditorialError("EDITORIAL_BRIEFING_MAX_PROMPT_CHARS deve essere un intero da 2000 a 40000.") from None
            if not 2000 <= prompt_budget <= 40000:
                raise EditorialError("EDITORIAL_BRIEFING_MAX_PROMPT_CHARS deve essere un intero da 2000 a 40000.")
        catalog = read_catalog(root)
        request_id = "editorial-" + uuid4().hex[:12]
        identity = cache_key(kind, topic, model, config, catalog, briefing_prompt_chars=prompt_budget)
        path = root / "data/editorial.sqlite3"
        cached = cache_read(path, identity)
        if cached is not None:
            logger.info("request_id=%s phase=editorial_cache kind=%s event=hit sufficient=%s status=%s",
                        request_id, kind, cached.sufficient, cached.diagnostics.get("status", "legacy"))
            return cached  # Anche l'embedding del tema è evitato.
        logger.info("request_id=%s phase=editorial_cache kind=%s event=miss strategy=%s",
                    request_id, kind, STRATEGY_VERSION if kind == "briefing" else PROMPT_VERSION)
        groups = []
        distances = {}
        if kind == "dossier" and catalog.chunks:
            hits = semantic_search(topic, authorize_external=True, root=root,
                                   top_k=config.dossier_chunks, diversify_by_pdf=True)
            available = {chunk.id: chunk for chunk in catalog.chunks}
            selected = [available[hit["id"]] for hit in hits if hit["id"] in available]
            distances = {hit["id"]: float(hit["distance"]) for hit in hits}
        elif kind == "briefing":
            selected = balanced_briefing(catalog, config.briefing_chunks, config.topic_similarity)
            assignments = topic_clusters(selected, catalog.vectors, config.topic_similarity)
            grouped = {}
            for chunk in selected:
                grouped.setdefault(assignments[chunk.id], []).append(chunk)
            # Conservare tutto il campione: i gruppi sono suggerimenti, non un taglio ai primi quattro.
            groups = [[chunk.id for chunk in group] for group in grouped.values()]
        else:
            selected = []
        char_limit = config.max_source_chars // max(1, len(selected))
        sources = [Source(f"S{index + 1}", chunk.id, chunk.metadata["filename"], chunk.metadata["page"],
                          chunk.text[:char_limit], distances.get(chunk.id, 0.0))
                   for index, chunk in enumerate(selected)]
        if kind == "briefing":
            logger.info("request_id=%s phase=briefing_selection indexed=%d total=%d selected=%d pdfs=%d pages=%d chars=%d groups=%d",
                        request_id, catalog.coverage["indexed"], catalog.coverage["total"], len(sources),
                        len({source.filename for source in sources}),
                        len({(source.filename, source.page) for source in sources}),
                        sum(len(source.text) for source in sources), len(groups))
        if not sources:
            result = EditorialResult(kind, "Informazioni insufficienti", [], [], [], catalog.coverage,
                                     False, "Nessun passaggio indicizzato pertinente disponibile.")
            if kind == "briefing":
                status = "selection_empty" if catalog.chunks else "empty_index"
                result = briefing_result(BriefingDraft(status=status), [], catalog.coverage)
                logger.warning("request_id=%s phase=briefing_selection status=%s", request_id, status)
            else:
                cache_write(path, identity, result)
            return result
        if kind == "dossier":
            task = (f"Prepara un dossier tematico sull'argomento: {topic}. Integra le diverse fonti pertinenti; "
                    "non riempire lacune con conoscenze esterne. Se insufficienti, astieniti. "
                    "Se sufficienti, restituisci ESATTAMENTE sette claims in ordine: "
                    "titolo del dossier, introduzione, titolo prima sezione tematica, testo prima sezione, "
                    "titolo seconda sezione tematica, testo seconda sezione, conclusioni. "
                    "Anche i titoli devono avere evidenze verificabili. Non inventare testate o date.")
        else:
            ids = {source.chunk_id: source.id for source in sources}
            groups = [[ids[identity] for identity in group] for group in groups]
            task = ""  # Il briefing ha istruzioni autonome, senza una domanda RAG fittizia.
        # Metadati di edizione forniti solo se esplicitamente disponibili.
        task += " Edizioni disponibili: " + json.dumps(catalog.coverage["files"], ensure_ascii=False)
        if client is None:
            if not key:
                raise EditorialError("Configurare GEMINI_API_KEY nell'ambiente o in .env.")
            client = genai.Client(api_key=key, vertexai=False, http_options=types.HttpOptions(
                timeout=30_000, retry_options=types.HttpRetryOptions(attempts=1)))
            own_client = True
        if kind == "briefing":
            try:
                sources, prompt = fit_briefing_prompt(sources, catalog.coverage, groups, prompt_budget)
            except ValueError:
                logger.warning("request_id=%s phase=briefing_context status=prompt_budget_exceeded budget=%d", request_id, prompt_budget)
                return briefing_result(BriefingDraft(status="prompt_budget_exceeded"), sources, catalog.coverage)
            prompt_chars = len(BRIEFING_INSTRUCTION) + len(prompt)
            logger.info("request_id=%s phase=briefing_context prompt_chars=%d budget=%d", request_id, prompt_chars, prompt_budget)
            draft = generate_briefing_response(client, model, prompt, sources, request_id=request_id)
            result = briefing_result(draft, sources, catalog.coverage)
            result.diagnostics.update({"selected_passages": len(sources), "selected_pdfs": len({s.filename for s in sources}),
                                       "source_chars": sum(len(s.text) for s in sources), "prompt_chars": prompt_chars,
                                       "prompt_budget": prompt_budget})
            if result.sufficient:
                cache_write(path, identity, result)
            logger.info("request_id=%s phase=editorial_cache kind=briefing event=%s status=%s",
                        request_id, "stored" if result.sufficient else "not_stored", draft.status)
            return result
        raw = generate_response(client, model, build_prompt(task, sources), response_schema(sources),
                                request_id=request_id)
        result = render_product(kind, raw, sources, catalog.coverage, groups)
        try:
            explicit_abstention = json.loads(raw) == {"sufficient": False, "claims": []}
        except (ValueError, TypeError):
            explicit_abstention = False
        if result.sufficient or explicit_abstention:
            cache_write(path, identity, result)
        return result
    except EditorialError:
        raise
    except RagError as exc:
        raise EditorialError(str(exc)) from None
    except Exception:
        raise EditorialError("Prodotto non disponibile: verificare archivio, metadati, configurazione e connessione Gemini.") from None
    finally:
        if own_client:
            try:
                client.close()
            except Exception:
                pass
