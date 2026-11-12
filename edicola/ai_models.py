"""Instradamento comune delle richieste testuali Gemini.

Le quote sono per progetto e modello: un 429 non garantisce che un modello
alternativo abbia spazio. Niente rotazioni di API key, richieste parallele o
passaggi impliciti a un servizio a pagamento.
"""

import logging
import time

import httpx
from google.genai import errors

from edicola.settings import setting

logger = logging.getLogger(__name__)
SERVER_CODES = {500, 502, 503, 504}
RETRY_CODES = SERVER_CODES | {408, 429}
DISABLED = {"off", "none", "disabled", "0"}
TRANSPORT_ERRORS = (httpx.TransportError, ConnectionError, TimeoutError, OSError)


def product_model(product: str, default: str, *, root=None) -> str:
    """Un modello principale per funzione, con fallback alla vecchia impostazione."""
    return setting(f"GEMINI_{product.upper()}_MODEL", "", root=root) or default


def alternative_models(product: str, primary: str, *, root=None,
                       default_fallback="gemini-3.8-flash") -> tuple[str, ...]:
    """Lista esplicita per prodotto o vecchia riserva comune, senza duplicati."""
    configured = setting(f"GEMINI_{product.upper()}_FALLBACK_MODELS", "", root=root)
    if configured:
        raw = configured
    else:
        raw = setting("GEMINI_RAG_FALLBACK_MODEL", default_fallback, root=root)
    if raw.casefold() in DISABLED:
        return ()
    unique = []
    for candidate in raw.split(","):
        name = candidate.strip()
        if name and name.casefold() not in DISABLED and name != primary and name not in unique:
            unique.append(name)
    return tuple(unique[:2])


def run_text_request(send, model: str, *, fallbacks=(), sleep=time.sleep,
                     request_id="-", phase="generation", quota_fallback=False,
                     on_error=None):
    """Unica politica: massimo due tentativi per modello con riserve.

    Un 429 passa subito alla riserva se abilitata; con le quote esaurite
    non manda altre richieste a quel modello nella stessa operazione.
    Per 500/502/503/504 prova ancora una volta, poi passa alla riserva.
    Non cambia mai prompt, schema, finalita' o autorizzazioni.
    """
    models = [model]
    for candidate in fallbacks:
        candidate = candidate.strip()
        if candidate and candidate not in models and candidate.casefold() not in DISABLED:
            models.append(candidate)
    models = models[:3]
    for index, active in enumerate(models):
        attempts = 2 if len(models) > 1 else 3
        for attempt in range(attempts):
            logger.info("request_id=%s phase=%s model=%r event=start attempt=%d max_attempts=%d",
                        request_id, phase, active, attempt + 1, attempts)
            try:
                response = send(active)
                logger.info("request_id=%s phase=%s model=%r event=success attempt=%d",
                            request_id, phase, active, attempt + 1)
                return response
            except errors.APIError as exc:
                failure = exc
                code = exc.code
                retryable = code in RETRY_CODES
                next_model = index + 1 < len(models)
                failover = next_model and (code in SERVER_CODES or
                                           (code == 429 and quota_fallback))
                # Nessuna raffica di retry sullo stesso modello dopo un 429.
                retry = (retryable and attempt < attempts - 1 and
                         not (quota_fallback and code == 429))
            except TRANSPORT_ERRORS as exc:
                failure = exc
                code = "-"
                failover = False
                retry = attempt < attempts - 1
            logger.warning("request_id=%s phase=%s model=%r event=error http_status=%s attempt=%d retry=%s",
                           request_id, phase, active, code, attempt + 1, retry)
            if on_error:
                on_error(active, failure, attempt + 1, retry)
            if retry:
                sleep(2 ** attempt)
                continue
            if failover:
                logger.warning("request_id=%s phase=%s event=model_fallback from_model=%r to_model=%r reason=%s",
                               request_id, phase, active, models[index + 1], code)
                break
            raise failure
    raise RuntimeError("No available Gemini model completed the text request.")
