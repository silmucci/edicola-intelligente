"""Criteri editoriali locali: stato documentato e ordine non cronologico esplicito."""

import re

TIMELINE_CONTENT_VERSION = "timeline-developments-v3"
PROPOSAL = re.compile(r"\b(propon\w*|propost[aoe]|richied\w*|chied\w*|ipotizz\w*)\b", re.I)
DECISION = re.compile(r"\b(ha approvato|hanno approvato|ha deliberato|è stato approvato|è stata approvata|ha deciso)\b", re.I)
NEGATION = re.compile(r"\b(non|smentisce|nega|mai)\b", re.I)


def development_kind(quotes, lifecycle):
    """Nessuna etichetta fattuale dal titolo proposto dal modello o dalla data editoriale."""
    text = " ".join(dict.fromkeys(quotes))
    if lifecycle == "conflicting" or NEGATION.search(text):
        return "undetermined"
    if PROPOSAL.search(text):
        return "proposal" if not DECISION.search(text) else "undetermined"
    if lifecycle in {"announced", "future"}:
        return "announced"
    if DECISION.search(text):
        return "decision"
    return "fact" if lifecycle == "occurred" else "undetermined"


def strict_chronology(topic):
    return bool(re.search(r"cronologic\w*|in ordine di data|sequenza temporale|quando.*prima", topic, re.I))


def undated_order(events, sources):
    """Ordine di lettura per passaggio recuperato; non usa le date di pubblicazione."""
    order = {source.id: index for index, source in enumerate(sources)}
    return sorted(events, key=lambda event: min((order.get(s, len(order)) for s in event["source_ids"]), default=len(order)))


def short_text(text, limit=100):
    text = re.sub(r"\s*\[S\d+\]", "", text)
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


def theme_title(topic):
    """Abbreviazione locale della richiesta, non un titolo di notizia generato."""
    text = re.sub(r"^(?:quali\s+|qual[ei]\s+|mostra(?:mi)?\s+|crea(?:mi)?\s+|genera(?:mi)?\s+)", "", topic.strip(), flags=re.I)
    return short_text(text.rstrip(" ?.!"), 62) or "Tema scelto"


def deadline_reference(text):
    return bool(re.search(r"\b(?:fino al|entro il|scadenza(?: del)?|scade il)\s+\d", text, re.I))


def empty_knowledge_message(result):
    """Distingue le fasi osservabili; non attribuisce al retrieval gli scarti AI."""
    if not result.sources:
        message = "Non ho trovato passaggi su questo tema nell’archivio disponibile."
    elif result.diagnostics.get("rejected_events", 0) or result.diagnostics.get("rejected_nodes", 0):
        message = "Le fonti disponibili non consentono una ricostruzione affidabile."
    elif result.kind == "timeline":
        message = "Nei passaggi disponibili non emergono eventi o sviluppi documentati su questo tema."
    else:
        message = "Nei passaggi disponibili non emergono concetti documentati su questo tema."
    if result.coverage.get("partial"):
        message += " La copertura dell’archivio è parziale."
    return message + " Prova un tema più specifico o consulta le edizioni originali."
