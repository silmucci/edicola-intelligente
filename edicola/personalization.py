"""Suggerimenti locali e briefing personale esplicito con i validatori editoriali."""

import hashlib
import json
import os
import re
import sqlite3
import unicodedata
from collections import defaultdict, deque
from contextlib import closing
from dataclasses import asdict, dataclass

from google import genai
from google.genai import types

from edicola.archive import IndexChunk
from edicola.briefing import STRATEGY_VERSION, fit_briefing_prompt, generate_briefing_response
from edicola.editorial import EditorialResult, briefing_result
from edicola.editorial_selection import near_duplicate, read_catalog
from edicola.embeddings import api_key
from edicola.profiles import Profile, personal_root, validate
from edicola.rag import DEFAULT_MODEL, RagError, Source


VERSION = "personal-briefing-v1"
WORD_BUDGET = {2: 240, 5: 600, 10: 1200}
STOPWORDS = set("a ad al alla alle ai agli con da dal dalla delle degli dei del di e ed il in la le lo gli i l un una uno per tra su sul sulla nel nella nelle degli notizie notizia informazioni tema temi".split())


def read_personal_cache(path, key):
    if not path.exists():
        return None
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        row = connection.execute("SELECT result_json FROM products WHERE cache_key=?", (key,)).fetchone()
    if row is None:
        return None
    data = json.loads(row[0])
    data["sources"] = [Source(**item) for item in data["sources"]]
    data["from_cache"] = True
    return EditorialResult(**data)


def write_personal_cache(path, key, result):
    # Stesso formato letto dal podcast, connessione chiusa anche su Windows.
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS products (
            cache_key TEXT PRIMARY KEY, result_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        connection.execute("INSERT OR REPLACE INTO products(cache_key,result_json) VALUES (?,?)",
                           (key, json.dumps(asdict(result), ensure_ascii=False)))


def tokens(text):
    plain = "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))
    return set(re.findall(r"[a-z0-9]+", plain)) - STOPWORDS


@dataclass
class Recommendation:
    chunk: IndexChunk
    topics: list[str]
    score: float
    reason: str


def recommend(catalog, profile: Profile, limit=None):
    """Corrispondenze lessicali dichiarate; non genera embedding della domanda."""
    validate(profile)
    limit = limit if limit is not None else {2: 3, 5: 5, 10: 8}[profile.minutes]
    ranked = []
    for chunk in catalog.chunks:
        words = tokens(chunk.text)
        # Un argomento escluso esplicitamente prevale sui boost positivi.
        matches = [topic for topic in profile.interests if tokens(topic) and
                   len(tokens(topic) & words) / len(tokens(topic)) >= 0.6]
        if not matches or any(profile.feedback.get(t) == -1 for t in matches):
            continue
        score = sum(len(tokens(t) & words) / len(tokens(t)) * (2 if profile.feedback.get(t) == 1 else 1) for t in matches)
        saved = chunk.id in profile.saved
        score += 0.5 if saved else 0
        reason = "Corrispondenza nel testo: " + ", ".join(matches)
        if any(profile.feedback.get(t) == 1 for t in matches):
            reason += ". Priorità aumentata dal tuo feedback"
        if saved:
            reason += ". Passaggio salvato (+0,5)"
        ranked.append(Recommendation(chunk, matches, score, reason))
    ranked.sort(key=lambda item: (-item.score, item.chunk.id))
    editions = {f["pdf"]: (f.get("publication") or f["pdf"], f.get("date", "")) for f in catalog.coverage.get("files", [])}
    groups = defaultdict(deque)
    for item in ranked:
        name = item.chunk.metadata["filename"]
        groups[editions.get(name, (name, ""))].append(item)
    result = []
    while any(groups.values()) and len(result) < limit:
        # Primo candidato migliore di ciascuna edizione, poi giro successivo.
        order = sorted((key for key in groups if groups[key]), key=lambda k: -groups[k][0].score)
        for edition in order:
            while groups[edition]:
                item = groups[edition].popleft()
                if not any(near_duplicate(item.chunk.text, previous.chunk.text) for previous in result):
                    result.append(item)
                    break
            if len(result) >= limit:
                break
    return result


def generate_personal_briefing(root, profile, *, authorize_external=False, client=None, catalog=None):
    if not authorize_external:
        raise RagError("Autorizza l'invio dei passaggi selezionati e del tempo di lettura a Gemini.")
    validate(profile)
    catalog = catalog if catalog is not None else read_catalog(root)
    selected = recommend(catalog, profile, limit={2: 6, 5: 10, 10: 12}[profile.minutes])
    if not selected:
        raise RagError("Nessun passaggio indicizzato pertinente agli interessi attivi. Modifica le preferenze.")
    key = api_key(root)  # Carica soltanto la configurazione locale; nessuna rete.
    model = os.getenv("GEMINI_RAG_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    delivery = {"available_minutes": profile.minutes, "max_words": WORD_BUDGET[profile.minutes],
                "instruction": "Briefing selettivo: rispetta il limite di parole, senza aggiungere notizie per riempire il tempo."}
    extra = json.dumps(delivery, ensure_ascii=False)
    sources = [Source(f"S{i}", item.chunk.id, item.chunk.metadata["filename"],
                      item.chunk.metadata["page"], item.chunk.text, 0.0) for i, item in enumerate(selected, 1)]
    sources, prompt = fit_briefing_prompt(sources, catalog.coverage, [], 14000 - len(extra) - 40)
    data = json.loads(prompt)
    data["delivery"] = delivery
    prompt = json.dumps(data, ensure_ascii=False)
    identity = hashlib.sha256(json.dumps({"version": [VERSION, STRATEGY_VERSION], "model": model, "prompt": prompt,
        "chunks": [(r.chunk.id, r.chunk.fingerprint) for r in selected]}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    path = personal_root(root, profile.user_id) / "data/editorial.sqlite3"
    cached = read_personal_cache(path, identity)
    if cached is not None:
        return identity, cached
    own_client = client is None
    if own_client:
        if not key:
            raise RagError("Configurare GEMINI_API_KEY in .env.")
        client = genai.Client(api_key=key, vertexai=False, http_options=types.HttpOptions(
            timeout=30000, retry_options=types.HttpRetryOptions(attempts=1)))
    try:
        draft = generate_briefing_response(client, model, prompt, sources)
    finally:
        if own_client:
            client.close()
    result = briefing_result(draft, sources, catalog.coverage)
    # Limite locale su sezioni intere: non tagliare fatti o riferimenti validati.
    kept, words = [], 0
    for section in result.sections:
        size = len((section["heading"] + " " + section["text"]).split())
        if words + size <= WORD_BUDGET[profile.minutes]:
            kept.append(section)
            words += size
    if len(kept) < len(result.sections):
        result.message += " Selezione ridotta a notizie complete per rispettare il tempo disponibile."
    result.sections = kept
    cited = set(re.findall(r"\[(S\d+)\]", " ".join(s["heading"] + " " + s["text"] for s in kept)))
    result.used_source_ids = [s.id for s in sources if s.id in cited]
    result.sufficient = bool(kept)
    result.title = f"Il mio briefing — fino a {profile.minutes} minuti"
    result.diagnostics["personalization_strategy"] = VERSION
    if not kept and not result.message:
        result.message = "Nessuna notizia verificata disponibile nel limite scelto."
    if result.sufficient:
        write_personal_cache(path, identity, result)
    return identity, result
