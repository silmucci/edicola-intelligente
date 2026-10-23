"""Gemini Embedding 2: chiamate esplicite, timeout e retry limitati."""

import math
import os
import time

import httpx
from dotenv import dotenv_values
from google import genai
from google.genai import errors, types
from edicola.settings import setting


MODEL = "gemini-embedding-2"
DIMENSIONS = 768
FORMAT_VERSION = "qa-v1"


class EmbeddingError(RuntimeError):
    """Errore pubblico senza URL, chiavi o contenuti della richiesta."""

    def __init__(self, message: str, *, http_status=None):
        super().__init__(message)
        self.http_status = http_status


def api_key(root=None) -> str:
    # Secrets/ambiente precedono .env; non esportare né registrare la chiave.
    value = setting("GEMINI_API_KEY", root=root)
    if root is not None:
        for name, configured in dotenv_values(root / ".env").items():
            if name != "GEMINI_API_KEY" and configured is not None:
                os.environ.setdefault(name, configured)
    return value


def document_prompt(title: str, content: str) -> str:
    return f"title: {title} | text: {content}"


def question_prompt(content: str) -> str:
    return f"task: question answering | query: {content}"


def validate_vector(values) -> list[float]:
    try:
        vector = [float(value) for value in values]
        if len(vector) != DIMENSIONS or not all(math.isfinite(value) for value in vector):
            raise ValueError
        if not any(vector):
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        raise EmbeddingError("Embedding non valido: atteso un vettore finito non nullo di 768 dimensioni.") from None
    return vector


class GeminiEmbedder:
    def __init__(self, key: str, *, client=None, max_attempts=3, sleep=time.sleep):
        if not key:
            raise EmbeddingError("Configurare GEMINI_API_KEY nell'ambiente o in .env.")
        if not 1 <= max_attempts <= 3:
            raise ValueError("Sono consentiti da 1 a 3 tentativi.")
        self.client = client or genai.Client(
            api_key=key, vertexai=False,
            http_options=types.HttpOptions(
                timeout=30_000, retry_options=types.HttpRetryOptions(attempts=1)
            ),
        )
        self.max_attempts = max_attempts
        self.sleep = sleep

    def close(self):
        self.client.close()

    def embed(self, prompt: str) -> list[float]:
        for attempt in range(self.max_attempts):
            try:
                response = self.client.models.embed_content(
                    model=MODEL, contents=prompt,
                    config=types.EmbedContentConfig(output_dimensionality=DIMENSIONS),
                )
                if not response.embeddings or len(response.embeddings) != 1:
                    raise EmbeddingError("La risposta Gemini non contiene un singolo embedding.")
                return validate_vector(response.embeddings[0].values)
            except errors.APIError as exc:
                code = exc.code
                http_status = code
                retryable = code in {408, 429, 500, 502, 503, 504}
                message = f"Gemini API: errore HTTP {code}; verificare accesso, quota e disponibilità."
            except (httpx.TransportError, ConnectionError, TimeoutError, OSError):
                http_status = None
                retryable = True
                message = "Gemini API non raggiungibile o timeout di connessione."
            if not retryable or attempt + 1 == self.max_attempts:
                raise EmbeddingError(message, http_status=http_status) from None
            self.sleep(2 ** attempt)
        raise EmbeddingError("Tentativi Gemini esauriti.")
