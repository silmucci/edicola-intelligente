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
from edicola.editorial_selection import read_catalog
from edicola.embeddings import api_key
from edicola.profiles import Profile, personal_root, validate
from edicola.rag import DEFAULT_MODEL, RagError, Source
from edicola.context_selection import VERSION as CONTEXT_VERSION, selection_coverage


VERSION = "personal-briefing-v2"
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
    # Le preferenze non cambiano tra i chunk: normalizzarle una sola volta.
    interest_terms = [(topic, tokens(topic)) for topic in profile.interests]
    ranked = []
    for chunk in catalog.chunks:
        words = tokens(chunk.text)
        matches = []
        for topic, topic_words in interest_terms:
            if topic_words:
                overlap = len(topic_words & words) / len(topic_words)
                if overlap >= 0.6:
                    matches.append((topic, overlap))
        # Un argomento escluso esplicitamente prevale sui boost positivi.
        if not matches or any(profile.feedback.get(topic) == -1 for topic, _ in matches):
            continue
        score = sum(overlap * (2 if profile.feedback.get(topic) == 1 else 1)
                    for topic, overlap in matches)
        saved = chunk.id in profile.saved
        score += 0.5 if saved else 0
        topics = [topic for topic, _ in matches]
        reason = "Corrispondenza nel testo: " + ", ".join(topics)
        if any(profile.feedback.get(topic) == 1 for topic in topics):
            reason += ". Priorità aumentata dal tuo feedback"
        if saved:
            reason += ". Passaggio salvato (+0,5)"
        ranked.append(Recommendation(chunk, topics, score, reason))
    ranked.sort(key=lambda item: (-item.score, item.chunk.id))
    editions = {f["pdf"]: (f.get("publication") or f["pdf"], f.get("date", "")) for f in catalog.coverage.get("files", [])}
    groups = defaultdict(deque)
    for item in ranked:
        name = item.chunk.metadata["filename"]
        groups[editions.get(name, (name, "")) + (name,)].append(item)
    result = []
    while any(groups.values()) and len(result) < limit:
        # Primo candidato migliore di ciascuna edizione, poi giro successivo.
        order = sorted((key for key in groups if groups[key]), key=lambda k: -groups[k][0].score)
        for edition in order:
            while groups[edition]:
                item = groups[edition].popleft()
                if not any(item.chunk.metadata["filename"] == previous.chunk.metadata["filename"]
                           and " ".join(item.chunk.text.split()) == " ".join(previous.chunk.text.split()) for previous in result):
                    result.append(item)
                    break
            if len(result) >= limit:
                break
    return result


def balanced_briefing_selection(catalog, profile):
    """Priorità agli interessi, con spazio per notizie generali di altre edizioni."""
    preferred = recommend(catalog, profile, limit=len(catalog.chunks))
    if not preferred:
        return []
    used = {item.chunk.id for item in preferred}
    other = []
    excluded = [tokens(topic) for topic, value in profile.feedback.items() if value == -1]
    for chunk in catalog.chunks:
        if chunk.id in used:
            continue
        words = tokens(chunk.text)
        if any(topic_words and len(topic_words & words) / len(topic_words) >= .6 for topic_words in excluded):
            continue
        other.append(chunk)
    # Aggiunge una notizia generale ogni tre selezioni pertinenti,
    # senza mettere in coda tutto il corpus prima dei temi preferiti.
    editions = defaultdict(deque)
    for chunk in other:
        editions[chunk.metadata["filename"]].append(chunk)
    general = []
    while any(editions.values()):
        for name in sorted(editions):
            if editions[name]:
                general.append(editions[name].popleft())
    result = []
    index = 0
    for position, item in enumerate(preferred, 1):
        result.append(item.chunk)
        if position % 3 == 0 and index < len(general):
            result.append(general[index])
            index += 1
    result.extend(general[index:])
    return result


def generate_personal_briefing(root, profile, *, authorize_external=False, client=None, catalog=None, store=None):
    if not authorize_external:
        raise RagError("Autorizza l'invio dei passaggi selezionati e del tempo di lettura a Gemini.")
    validate(profile)
    if store is not None:
        store.assert_owner(profile.user_id)
    catalog = catalog if catalog is not None else read_catalog(root)
    selected = balanced_briefing_selection(catalog, profile)
    if not selected:
        raise RagError("Nessun passaggio indicizzato pertinente agli interessi attivi. Modifica le preferenze.")
    key = api_key(root)  # Carica soltanto la configurazione locale; nessuna rete.
    model = os.getenv("GEMINI_RAG_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    delivery = {"available_minutes": profile.minutes, "max_words": WORD_BUDGET[profile.minutes],
                "instruction": "Briefing selettivo: rispetta il limite di parole, senza aggiungere notizie per riempire il tempo."}
    extra = json.dumps(delivery, ensure_ascii=False)
    sources = [Source(f"S{i}", chunk.id, chunk.metadata["filename"],
                      chunk.metadata["page"], chunk.text, 0.0) for i, chunk in enumerate(selected, 1)]
    candidates = sources
    sources, prompt = fit_briefing_prompt(sources, catalog.coverage, [], 14000 - len(extra) - 40)
    data = json.loads(prompt)
    data["delivery"] = delivery
    data["editorial_preference"] = ("Dai priorità alle notizie sugli interessi scelti, "
        "ma includi anche notizie importanti su altri temi quando supportate dalle fonti. "
        "Non inventare e non ripetere notizie.")
    prompt = json.dumps(data, ensure_ascii=False)
    identity = hashlib.sha256(json.dumps({"version": [VERSION, STRATEGY_VERSION, CONTEXT_VERSION], "model": model, "prompt": prompt,
        "chunks": [(r.id, r.fingerprint) for r in selected]}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    path = personal_root(root, profile.user_id) / "data/editorial.sqlite3" if store is None else None
    cached = read_personal_cache(path, identity) if store is None else store.get_briefing(identity)
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
    result = briefing_result(draft, sources, selection_coverage(catalog.coverage, candidates, sources))
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
        if store is None:
            write_personal_cache(path, identity, result)
        else:
            store.save_briefing(identity, result)
    return identity, result
