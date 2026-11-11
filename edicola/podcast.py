"""Gemini TTS esplicito, WAV verificato e cache locale separata dai prodotti editoriali."""

import hashlib
import io
import json
import logging
import os
import re
import tempfile
import wave
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx
from google import genai
from google.genai import errors, types

from edicola.embeddings import api_key
from edicola.indexing import ROOT
from edicola.podcast_text import PodcastError, Script, list_products, prepare_script


MODEL = "gemini-3.8-flash-lite-tts"
VOICES = ("Kore", "Puck", "Aoede", "Leda")  # Voci predefinite documentate, senza query di catalogo.
VERSION = "podcast-v1"
STYLE = "Italiano naturale, dizione chiara, tono giornalistico sobrio e ritmo di circa 130 parole al minuto."
logger = logging.getLogger(__name__)


@dataclass
class PodcastResult:
    audio_path: Path
    script: Script
    model: str
    voice: str
    seconds: float
    from_cache: bool


def wav_duration(data: bytes) -> float:
    try:
        if not data or len(data) > 20_000_000:
            raise ValueError
        with wave.open(io.BytesIO(data), "rb") as audio:
            channels, width, rate, frames = audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getnframes()
            if channels != 1 or width != 2 or not 8000 <= rate <= 48000 or not 0 < frames / rate <= 420:
                raise ValueError
            if len(audio.readframes(frames)) != frames * channels * width:
                raise ValueError
            return frames / rate
    except (wave.Error, EOFError, ValueError, OverflowError):
        raise PodcastError("Audio WAV vuoto, incompleto, non supportato o oltre il limite consentito; risultato non salvato.") from None


def audio_bytes(response) -> bytes:
    candidates = response.candidates or []
    if len(candidates) != 1 or candidates[0].finish_reason != types.FinishReason.STOP:
        raise PodcastError("Gemini TTS non ha completato l'audio; risultato non salvato.")
    parts = candidates[0].content.parts if candidates[0].content else []
    blobs = [part.inline_data for part in (parts or []) if part.inline_data is not None]
    if not blobs:
        raise PodcastError("Gemini TTS non ha restituito audio.")
    mime = blobs[0].mime_type or ""
    if any(blob.mime_type != mime or not isinstance(blob.data, bytes) for blob in blobs):
        raise PodcastError("Formato audio Gemini incoerente.")
    data = b"".join(blob.data for blob in blobs)
    base_mime = mime.split(";", 1)[0].strip().lower()
    parameters = dict(part.strip().split("=", 1) for part in mime.lower().split(";")[1:] if "=" in part)
    if base_mime in {"audio/wav", "audio/x-wav", "audio/wave"}:
        if len(blobs) != 1:
            raise PodcastError("Risposta WAV multipla non supportata; nessun audio concatenato.")
    elif (base_mime == "audio/l16" and parameters.get("rate") == "24000"
          and parameters.get("channels", "1") == "1" and len(data) % 2 == 0):
        # Solo PCM dichiarato esplicitamente; i WAV 3.8 non vanno incapsulati due volte.
        output = io.BytesIO()
        with wave.open(output, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(24000)
            audio.writeframes(data)
        data = output.getvalue()
    else:
        raise PodcastError("Formato audio non supportato: atteso WAV o PCM 16 bit a 24 kHz dichiarato.")
    wav_duration(data)
    return data


def synthesize(client, model, voice, script):
    logger.info("phase=podcast_tts model=%r voice=%s event=start chars=%d", model, voice, len(script))
    try:
        from edicola.api_guard import require_permission
        require_permission("audio")
        response = client.models.generate_content(model=model,
            contents=[types.Content(role="user", parts=[types.Part(text=script,
                speech_metadata=types.SpeechMetadata(style=STYLE))])],
            config=types.GenerateContentConfig(response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(voice=voice)),
                max_output_tokens=8192))
        return audio_bytes(response)
    except errors.APIError as exc:
        code = exc.code
        logger.warning("phase=podcast_tts model=%r http_status=%s event=error", model, code)
        message = {400: "Richiesta TTS non compatibile: verificare modello, voce e SDK.",
                   401: "Chiave Gemini non valida.", 403: "Accesso al modello TTS non consentito.",
                   404: "Modello TTS non disponibile per questo progetto.",
                   429: "Quota o limite TTS raggiunto: attendere e riprovare manualmente. Nessun passaggio a servizi a pagamento."}
        raise PodcastError(f"Gemini TTS HTTP {code}. " + message.get(code, "Servizio temporaneamente non disponibile; riprovare manualmente.")) from None
    except (httpx.TransportError, ConnectionError, TimeoutError, OSError):
        logger.warning("phase=podcast_tts model=%r event=connection_error", model)
        raise PodcastError("Connessione TTS assente o timeout; nessun nuovo tentativo automatico.") from None


def tts_segments(text, *, max_words=115, max_chars=1000):
    """Segmenti completi per evitare il troncamento TTS di copioni lunghi."""
    if not text.strip():
        raise PodcastError("Il copione non contiene testo leggibile.")
    # Mantiene le parole originali, compresa la punteggiatura; niente riassunti o tagli.
    sentences = re.split(r"(?<=[.!?])\s+|\n\s*\n+", text.strip())
    units = []
    for sentence in sentences:
        words = sentence.split()
        while words:
            count = 0
            chars = 0
            for word in words:
                next_chars = chars + len(word) + (1 if count else 0)
                if count and (count + 1 > max_words or next_chars > max_chars):
                    break
                if not count and next_chars > max_chars:
                    raise PodcastError("Il copione contiene una parola troppo lunga per la sintesi.")
                chars = next_chars
                count += 1
            units.append(" ".join(words[:count]))
            words = words[count:]
    segments, current = [], []
    for unit in units:
        candidate = " ".join(current + [unit])
        if current and (len(candidate.split()) > max_words or len(candidate) > max_chars):
            segments.append(" ".join(current))
            current = []
        current.append(unit)
    if current:
        segments.append(" ".join(current))
    if " ".join(" ".join(segments).split()) != " ".join(text.split()):
        raise PodcastError("Il copione è stato suddiviso in modo incompleto.")
    if len(segments) > 12:
        raise PodcastError("Copione troppo lungo per la sintesi audio.")
    return segments


def join_wav_segments(parts):
    """Unisce soltanto PCM WAV omogenei, senza duplicare intestazioni."""
    if not parts:
        raise PodcastError("Gemini non ha restituito segmenti audio.")
    target = io.BytesIO()
    sound_format = None
    with wave.open(target, "wb") as output:
        for part in parts:
            if wav_duration(part) > 180:
                raise PodcastError("Un segmento TTS supera il limite di durata.")
            with wave.open(io.BytesIO(part), "rb") as source:
                params = (source.getnchannels(), source.getsampwidth(),
                          source.getframerate(), source.getcomptype())
                if sound_format is None:
                    sound_format = params
                    output.setnchannels(params[0])
                    output.setsampwidth(params[1])
                    output.setframerate(params[2])
                    output.setcomptype(params[3], "not compressed")
                elif params != sound_format:
                    raise PodcastError("I segmenti TTS hanno formati audio incompatibili.")
                output.writeframesraw(source.readframes(source.getnframes()))
    result = target.getvalue()
    wav_duration(result)
    return result


def atomic_write(path, data):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def audio_identity(text, model, voice, cache_context=None):
    material = [VERSION, text, model, voice, STYLE]
    if cache_context is not None:
        material.append(cache_context)
    return hashlib.sha256(json.dumps(material, ensure_ascii=False).encode()).hexdigest()


def generate_podcast(product_key: str, *, voice=None, authorize_external=False, root=ROOT, client=None):
    """Percorso storico, conservato per letture e ascolti personali esistenti."""
    if not authorize_external:
        raise PodcastError("Autorizzare l'invio a Gemini TTS del copione selezionato.")
    product = next((p for p in list_products(root) if p.key == product_key), None)
    if product is None:
        raise PodcastError("Prodotto editoriale non presente nella cache: selezionare una lettura già disponibile.")
    return generate_script_audio(prepare_script(product), product.key, voice=voice,
        authorize_external=authorize_external, root=root, client=client)


def generate_script_audio(script: Script, product_key: str, *, voice=None, authorize_external=False,
                          root=ROOT, client=None, cache_context=None, minimum_seconds=0.):
    """TTS e cache condivisi: identità storica invariata se manca cache_context."""
    if not authorize_external:
        raise PodcastError("Autorizzare l'invio a Gemini TTS del copione selezionato.")
    own_client = False
    lock = None
    try:
        key = api_key(root)
        model = os.getenv("GEMINI_TTS_MODEL", MODEL).strip() or MODEL
        voice = voice or os.getenv("GEMINI_TTS_VOICE", "Kore").strip()
        if voice not in VOICES:
            raise PodcastError("Scegliere una delle voci predefinite supportate.")
        identity = audio_identity(script.text, model, voice, cache_context)
        directory = root / "data/podcast_cache"
        audio_path = directory / f"{identity}.wav"

        def cached_audio():
            if not audio_path.is_file():
                return None
            data = audio_path.read_bytes()
            try:
                if wav_duration(data) < minimum_seconds:
                    return None
            except PodcastError:
                return None
            return data

        data = cached_audio()
        from_cache = data is not None
        if data is None:
            directory.mkdir(parents=True, exist_ok=True)
            candidate_lock = directory / f"{identity}.lock"
            try:
                with candidate_lock.open("x", encoding="utf-8") as stream:
                    stream.write("podcast in progress")
            except FileExistsError:
                raise PodcastError("Questo podcast è già in generazione: attendere e riprovare.") from None
            lock = candidate_lock
            data = cached_audio()  # Un altro processo potrebbe averlo appena completato.
            from_cache = data is not None
            if data is None:
                if client is None:
                    if not key:
                        raise PodcastError("Configurare GEMINI_API_KEY in .env per la sintesi TTS.")
                    client = genai.Client(api_key=key, vertexai=False, http_options=types.HttpOptions(
                        timeout=60000, retry_options=types.HttpRetryOptions(attempts=1)))
                    own_client = True
                longform = isinstance(cache_context, dict) and cache_context.get("strategy") == "standalone-podcast-v5"
                segments = tts_segments(script.text) if longform else [script.text]
                audio_parts = []
                for segment in segments:
                    sound = synthesize(client, model, voice, segment)
                    # Controllo prudente: un testo lungo non deve produrre pochi secondi
                    # per un output parziale. Non fornisce una trascrizione automatica.
                    if longform and wav_duration(sound) < max(1., len(segment.split()) / 3.5):
                        raise PodcastError("La sintesi vocale di un segmento è incompleta; audio non salvato.")
                    audio_parts.append(sound)
                data = join_wav_segments(audio_parts) if len(audio_parts) > 1 else audio_parts[0]
                if wav_duration(data) < minimum_seconds:
                    raise PodcastError("L’audio ricevuto è troppo breve per il copione; risultato non salvato.")
                atomic_write(audio_path, data)
        # Provenienza separata: un audio identico può appartenere a prodotti/fonti diversi.
        manifest = {"version": VERSION, "product_key": product_key, "model": model, "voice": voice,
                    "script": asdict(script), "audio_sha256": hashlib.sha256(data).hexdigest(), "audio_file": audio_path.name}
        if cache_context is not None:
            manifest["context"] = cache_context
        provenance = hashlib.sha256(json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        atomic_write(directory / f"{identity}-{provenance}.json", json.dumps(manifest, ensure_ascii=False).encode())
        logger.info("phase=podcast_cache event=%s", "hit" if from_cache else "stored")
        return PodcastResult(audio_path, script, model, voice, wav_duration(data), from_cache)
    except PodcastError:
        raise
    except Exception:
        raise PodcastError("Podcast non disponibile: verificare cache, configurazione TTS e SDK google-genai >= 2.25.") from None
    finally:
        if lock is not None:
            try:
                lock.unlink(missing_ok=True)
            except OSError:
                logger.warning("phase=podcast_cache event=lock_cleanup_failed")
        if own_client:
            try:
                client.close()
            except Exception:
                pass
