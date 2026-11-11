"""Pipeline autonoma e consultazione locale degli episodi, compresi gli storici."""
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from edicola.api_guard import PermissionDenied, permission_scope
from edicola.indexing import ROOT
from edicola.podcast import generate_script_audio, wav_duration, atomic_write, audio_identity
from edicola.podcast_draft import prepare_draft, load_draft, digest, VERSION, V4_VERSION, V3_VERSION, TOPIC_VERSION
from edicola.podcast_text import PodcastError, Script, list_products
from edicola.rag import Source
from edicola.personal_store import PersonalStoreError


def draft_context(draft):
    context = {"strategy": draft.strategy, "corpus": draft.source_identity, "script_model": draft.model, "draft": draft.key}
    if draft.strategy in {VERSION, V4_VERSION, V3_VERSION, TOPIC_VERSION}:
        context["topic"] = draft.topic
    return context


@dataclass
class Episode:
    key: str
    title: str
    created_at: str
    audio_path: Path
    script: Script
    sources: list[Source]
    seconds: float
    voice: str
    from_cache: bool = True
    source_articles: dict = field(default_factory=dict)


class PodcastAudioError(PodcastError):
    def __init__(self, message, draft):
        super().__init__(message)
        self.draft = draft


def generate_standalone_podcast(*, root=ROOT, voice=None, authorize_text=False, authorize_audio=False,
                                text_check=None, audio_check=None, client=None, tts_client=None, retry_key=None,
                                topic="", embedder=None, selection=None):
    if not authorize_text or not authorize_audio:
        raise PermissionDenied("Autorizzare preparazione del testo e sintesi audio prima di continuare.")
    text_check = text_check or (lambda: authorize_text)
    audio_check = audio_check or (lambda: authorize_audio)
    # Preflight di entrambe le finalità prima di inviare anche il solo testo.
    with permission_scope(text_check, "text"):
        pass
    with permission_scope(audio_check, "audio"):
        pass
    with permission_scope(text_check, "text"):
        try:
            draft = prepare_draft(root, client=client, retry_key=retry_key, topic=topic,
                                  embedder=embedder, selection=selection)
        except (PermissionDenied, PodcastError):
            raise
        except (OSError, ValueError, RuntimeError):
            raise PodcastError("L’archivio non è disponibile per preparare il podcast in questo momento.") from None
    context = draft_context(draft)
    try:
        with permission_scope(audio_check, "audio"):
            audio = generate_script_audio(draft.script, draft.key, root=root, voice=voice,
                authorize_external=True, client=tts_client, cache_context=context, minimum_seconds=max(1., len(draft.script.text.split()) / 6))
    except (PodcastError, PermissionDenied, PersonalStoreError) as exc:
        raise PodcastAudioError(str(exc), draft) from None
    directory = root / "data/podcast_cache/standalone/episodes"
    key = digest([draft.key, audio.model, audio.voice, audio.audio_path.name])
    path = directory / (key + ".json")
    created = datetime.now(timezone.utc).isoformat()
    try:
        if not path.exists():
            directory.mkdir(parents=True, exist_ok=True)
            atomic_write(path, json.dumps({"draft_key": draft.key, "audio_file": audio.audio_path.name,
                "audio_sha256": hashlib.sha256(audio.audio_path.read_bytes()).hexdigest(), "voice": audio.voice,
                "model": audio.model, "created_at": created}, ensure_ascii=False).encode())
        else:
            created = json.loads(path.read_text(encoding="utf-8"))["created_at"]
    except (OSError, ValueError, KeyError):
        raise PodcastAudioError("L’episodio non è stato salvato correttamente. Puoi riprovare senza rigenerare il copione.", draft) from None
    return Episode(key, draft.title, created, audio.audio_path, draft.script, draft.sources,
                   audio.seconds, audio.voice, audio.from_cache, draft.source_articles)


def _audio_file(root, filename, sha):
    if not isinstance(filename, str) or not re.fullmatch(r"[a-f0-9]{64}\.wav", filename):
        raise ValueError
    base = root / "data/podcast_cache"
    path = base / filename
    if path.is_symlink() or path.resolve().parent != base.resolve():
        raise ValueError
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != sha:
        raise ValueError
    return path, wav_duration(data)


def list_episodes(root):
    """Sola lettura: la mancanza o corruzione del DB Briefing non blocca Podcast."""
    episodes = []
    for path in sorted((root / "data/podcast_cache/standalone/episodes").glob("*.json")):
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            draft = load_draft(root, saved["draft_key"])
            context = draft_context(draft)
            if saved["audio_file"] != audio_identity(draft.script.text, saved["model"], saved["voice"], context) + ".wav":
                raise ValueError
            audio, seconds = _audio_file(root, saved["audio_file"], saved["audio_sha256"])
            episodes.append(Episode(path.stem, draft.title, saved["created_at"], audio, draft.script,
                                    draft.sources, seconds, saved["voice"], source_articles=draft.source_articles))
        except (OSError, ValueError, TypeError, KeyError, PodcastError):
            continue
    products = {}
    try:
        products = {p.key: p for p in list_products(root)}
    except PodcastError:
        pass
    for path in sorted((root / "data/podcast_cache").glob("*.json")):
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
            if saved.get("context"):
                continue  # Manifest di un episodio autonomo già elencato sopra.
            audio, seconds = _audio_file(root, saved["audio_file"], saved["audio_sha256"])
            script = Script(**saved["script"])
            if saved["audio_file"] != audio_identity(script.text, saved["model"], saved["voice"]) + ".wav":
                raise ValueError
            product = products.get(saved.get("product_key"))
            title = "Podcast dell’archivio"
            sources = [Source(s["id"], s["chunk_id"], s["filename"], s["page"], "", 0.) for s in script.sources]
            articles = {}
            if product:
                from edicola.design import reading_title
                from edicola.podcast_text import spoken_text
                title = spoken_text(reading_title(product.result), [s.filename for s in product.result.sources])
                sources = product.result.sources
                articles = getattr(product.result, "source_articles", {}) or {}
            episodes.append(Episode("historical:" + path.stem, title,
                product.created_at if product else "Data non disponibile",
                audio, script, sources, seconds, saved["voice"], source_articles=articles))
        except (OSError, ValueError, TypeError, KeyError, PodcastError):
            continue
    return sorted(episodes, key=lambda e: e.created_at, reverse=True)
