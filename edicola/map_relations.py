"""Prove linguistiche locali per archi: nessuna inferenza dalla sola co-occorrenza."""

import re


VERSION = "concept-map-v5"
# Solo elementi grammaticali trasparenti; niente wildcard che scavalchino altri attori.
ADVERB = r"(?:oggi|ieri|anche|già|poi|ufficialmente|formalmente|direttamente|definitivamente)"
AUXILIARY = r"(?:ha|hanno|aveva|avevano|è|sono|era|erano|stato|stata|stati|state)"
LEGAL_REFERENCE = r"\(\s*(?:ex\s+)?\d{1,4}(?:[./]\d{1,4}){0,2}\s*\)"
BEFORE = rf"(?:\s*,?\s+(?:{ADVERB}|{AUXILIARY})){{0,3}}(?:\s+{LEGAL_REFERENCE})?\s*,?\s+"
AFTER = rf"(?:\s+{ADVERB}){{0,2}}(?:\s+con\s+(?:una?\s+)?(?:delibera|decreto|voto|decisione)(?:\s+unanime)?)?\s+"
ARTICLE = r"(?:(?:il|lo|la|i|gli|le|un|una|uno|l['’])\s*)?"
UNCERTAIN = re.compile(r"\b(non|mai|nessun[oa]?|senza|potrebbe|potrebbero|dovrebbe|dovrebbero|sarebbe|sarebbero|avrebbe|avrebbero|vorrebbe|vorrebbero|forse|possibile|probabilmente|ipotizza|ipotizzano|smentisce|smentiscono|nega|negano|se)\b", re.I)
THEME_LINKS = ("riguarda", "riguardano", "si occupa di", "si occupano di", "tratta", "trattano",
               "è dedicato a", "è dedicata a", "sono dedicati a", "sono dedicate a",
               "si concentra su", "si concentrano su")


def normalized(text):
    return " ".join(text.casefold().split())


def documented_relation(left, relation, right, quote):
    """Soggetto-predicato-oggetto nella stessa proposizione, con modificatori limitati.

    La relazione è letterale. Voci passive sono ammesse se label conserva ausiliari
    e preposizione della fonte (es. 'è stato approvato dal'), senza invertirne il senso.
    """
    left, relation, right, quote = map(normalized, (left, relation, right, quote))
    if (len(relation) > 80 or len(relation.split()) > 8
            or re.search(r"[.;!?,]|\b(che|mentre|quando|perché|sebbene)\b", relation)):
        return False
    # Nessuna distanza arbitraria tra estremi: non scavalcare subordinate o altri attori.
    pattern = (r"(?<!\w)" + re.escape(left) + BEFORE + re.escape(relation) + AFTER
               + ARTICLE + re.escape(right) + r"(?!\w)")
    for match in re.finditer(pattern, quote):
        clause_start = max(quote.rfind(mark, 0, match.start()) for mark in (".", ";", "!", "?")) + 1
        prefix = quote[clause_start:match.start()]
        # Una negazione o ipotesi prima del soggetto può avere portata sull'intera frase.
        if UNCERTAIN.search(prefix + match.group()):
            continue
        return True
    return False


def thematic_support(node, topic, quote):
    """Ciascun estremo deve essere esplicitamente collegato al medesimo tema."""
    return any(documented_relation(node, relation, topic, quote) for relation in THEME_LINKS)


def relation_failure(left, relation, right, quote):
    """Motivi diagnostici distinti, senza restituire testi o etichette nei log."""
    left, relation, right, quote = map(normalized, (left, relation, right, quote))
    literal = lambda text: re.search(r"(?<!\w)" + re.escape(text) + r"(?!\w)", quote)
    if not literal(relation):
        return "predicate_not_literal"
    if not literal(left) or not literal(right):
        return "endpoints_not_in_evidence"
    if UNCERTAIN.search(quote):
        return "uncertain_or_negated"
    return "unsupported_relation_form"
