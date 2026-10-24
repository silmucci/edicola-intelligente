"""Limiti, serializzazione verificata e contesto delle conversazioni."""

import json
import re
from dataclasses import asdict
from uuid import UUID

from edicola.personal_store import PersonalStoreError

MAX_CHATS = 200
MAX_LOCAL_CHATS = 20
MAX_TURNS = 100
MAX_ACCOUNT_BYTES = 10_000_000


def identifier(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise PersonalStoreError("Conversazione non disponibile.") from None


def title_from_question(question):
    return " ".join(question.split())[:80] or "Nuova chat"


def bounded_context(messages):
    """Al massimo 6 messaggi/4000 byte UTF-8, senza tokenizer o richieste extra.

    Il budget in byte è conservativo rispetto ai token; l'output LLM mantiene
    inoltre il max_output_tokens già configurato dal RAG.
    """
    kept, remaining = [], 4000
    for item in reversed(list(messages or [])[-6:]):
        if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"} or not isinstance(item.get("content"), str):
            continue
        text = item["content"][:800].encode("utf-8")[:remaining].decode("utf-8", errors="ignore")
        if text:
            kept.append({"role": item["role"], "content": text})
            remaining -= len(text.encode("utf-8"))
        if remaining <= 0:
            break
    return list(reversed(kept))


def turn_context(turns):
    messages = []
    for turn in turns:
        messages.append({"role": "user", "content": turn["question"]})
        if turn.get("result"):
            messages.append({"role": "assistant", "content": turn["result"].answer})
    return bounded_context(messages)


def encode_turn(turn):
    question = turn["question"]
    if not isinstance(question, str) or not 1 <= len(question) <= 2000:
        raise PersonalStoreError("Messaggio troppo lungo o non valido.")
    result = turn.get("result")
    details = {"error": turn.get("error") or None}
    content = ""
    if result:
        data = asdict(result)
        content = data.pop("answer")
        details["result"] = data
    if len(content) > 32000:
        raise PersonalStoreError("Risposta troppo lunga per la cronologia.")
    encoded = json.dumps(details, ensure_ascii=False, allow_nan=False)
    if len(encoded.encode("utf-8")) > 160000:
        raise PersonalStoreError("Fonti troppo estese per la cronologia.")
    return question, content, encoded


def decode_result(content, details):
    from edicola.rag import RagResult, Source
    data = details.get("result")
    if data is None:
        return None
    try:
        data = dict(data)
        sources = data.get("sources", [])
        if not isinstance(sources, list) or len(sources) > 5:
            raise ValueError()
        data["sources"] = [Source(**source) for source in sources]
        for source in data["sources"]:
            if (not re.fullmatch(r"S[1-9]\d*", source.id) or not source.chunk_id or len(source.chunk_id) > 256
                    or not source.filename.lower().endswith(".pdf") or any(c in source.filename for c in "/\\:\0")
                    or type(source.page) is not int or source.page < 1 or len(source.text) > 20000):
                raise ValueError()
        if len({s.id for s in data["sources"]}) != len(sources):
            raise ValueError()
        if (not isinstance(data.get("used_source_ids"), list)
                or not set(data["used_source_ids"]) <= {s.id for s in data["sources"]}
                or type(data.get("sufficient")) is not bool):
            raise ValueError()
        ids = {s.id for s in data["sources"]}
        for field in ("source_editions", "source_references"):
            metadata = data.get(field, {})
            if not isinstance(metadata, dict) or not set(metadata) <= ids:
                raise ValueError()
            for entry in metadata.values():
                if not isinstance(entry, dict) or any(v is not None and not isinstance(v, str) for v in entry.values()):
                    raise ValueError()
                if field == "source_references" and (set(entry) != {"pdf_sha256"} or not re.fullmatch(r"[0-9a-f]{64}", entry["pdf_sha256"])):
                    raise ValueError()
        if not isinstance(data.get("temporal_notice", ""), str):
            raise ValueError()
        return RagResult(answer=content, **data)
    except (ValueError, TypeError, KeyError, AttributeError):
        raise PersonalStoreError("Una risposta salvata non è leggibile. Nessuna rigenerazione automatica.") from None


def decode_messages(rows):
    turns = []
    if len(rows) % 2 or len(rows) > MAX_TURNS * 2:
        raise PersonalStoreError("Cronologia incompleta o troppo estesa.")
    for expected, (position, request_id, role, content, details) in enumerate(rows):
        if position != expected or not isinstance(details, dict) or not isinstance(content, str) or len(content) > 32000:
            raise PersonalStoreError("Cronologia non leggibile.")
        identifier(request_id)
        if details.get("error") is not None and not isinstance(details["error"], str):
            raise PersonalStoreError("Cronologia non leggibile.")
        if role == "user":
            if position % 2 or not isinstance(content, str) or len(content) > 2000:
                raise PersonalStoreError("Cronologia non leggibile.")
            turns.append({"id": str(request_id), "question": content, "result": None})
        elif role == "assistant" and turns and turns[-1]["id"] == str(request_id) and position % 2:
            turns[-1].update(result=decode_result(content, details), error=details.get("error"))
        else:
            raise PersonalStoreError("Ordine della cronologia non valido.")
    return turns
