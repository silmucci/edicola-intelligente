"""Prove linguistiche locali per archi: nessuna inferenza dalla sola co-occorrenza."""

import re


VERSION = "concept-map-v6"
# Solo elementi grammaticali trasparenti; niente wildcard che scavalchino altri attori.
ADVERB = r"(?:oggi|ieri|anche|già|poi|ufficialmente|formalmente|direttamente|definitivamente)"
AUXILIARY = r"(?:ha|hanno|aveva|avevano|è|sono|era|erano|stato|stata|stati|state)"
LEGAL_REFERENCE = r"\(\s*(?:ex\s+)?\d{1,4}(?:[./]\d{1,4}){0,2}\s*\)"
BEFORE = rf"(?:\s*,?\s+(?:{ADVERB}|{AUXILIARY})){{0,3}}(?:\s+{LEGAL_REFERENCE})?\s*,?\s+"
PARTY = r"(?:fratelli\s+d['’]italia|partito\s+democratico|pd|fdi|forza\s+italia|lega|movimento\s+5\s+stelle)"
ROLE = rf"(?:(?:deputato|senatore|senatrice|presidente|consigliere|consigliera|sindaco|ministro)(?:\s+abruzzese)?(?:\s+(?:di|del|della)\s+{PARTY})?\s+)?"
PURPOSE = r"(?:\s+presentat[oaie]\s+per\s+(?:garantire|assicurare|tutelare)\s+la\s+(?:salvaguardia|sopravvivenza|tutela)\s+(?:dei|degli)\s+(?:(?:quattro|tre|due)\s+)?(?:presidi\s+giudiziari|tribunali|uffici\s+giudiziari))?"
AFTER = rf"(?:\s+{ADVERB}){{0,2}}(?:\s+con\s+(?:una?\s+)?(?:delibera|decreto|voto|decisione)(?:\s+unanime)?)?\s+"
ARTICLE = r"(?:(?:il|lo|la|i|gli|le|un|una|uno|l['’])\s*)?(?:(?:citato|citata|stesso|stessa|suddetto|suddetta)\s+)?"
SPEECH = {"ha dichiarato", "ha spiegato", "ha affermato", "ha sottolineato", "dichiara", "spiega", "afferma", "sottolinea"}
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
    # Un testo citato integralmente può essere oggetto di un'attribuzione;
    # una parola isolata dentro la dichiarazione non diventa quell'oggetto.
    if relation in SPEECH and len(right) >= 20:
        quoted = r"[«“\"]" + re.escape(right) + r"[»”\"]"
        patterns = [re.escape(left) + BEFORE + re.escape(relation) + r"\s*:\s*" + quoted,
                    quoted + r"\s*[,\.]?\s*(?:lo\s+)?" + re.escape(relation) + r"\s+" + ROLE + re.escape(left)]
        for pattern in patterns:
            for match in re.finditer(r"(?<!\w)" + pattern + r"(?!\w)", quote):
                start = max(quote.rfind(mark, 0, match.start()) for mark in (".", ";", "!", "?")) + 1
                if not UNCERTAIN.search(quote[start:match.start()]):
                    return True
    pattern = (r"(?<!\w)" + re.escape(left) + PURPOSE + BEFORE + re.escape(relation) + AFTER
               + ARTICLE + ROLE + re.escape(right) + r"(?!\w)")
    patterns = [pattern]
    if re.match(r"(?:sostenut[oaie]|presentat[oaie])\b", relation):
        # Due participi coordinati condividono il soggetto. Il primo agente ha
        # una qualifica nota e al massimo quattro parole, senza verbi o subordinate.
        name = r"(?!(?:ha|hanno|è|sono|che|mentre|non|e|ma)\b)[^\W\d_]+(?:['’][^\W\d_]+)?"
        agent = ARTICLE + ROLE + name + rf"(?:\s+{name}){{0,3}}"
        patterns.append(r"(?<!\w)" + re.escape(left) + r"\s*,?\s+presentat[oaie]\s+(?:dal|dalla|da)\s+" +
                        agent + r"\s+e\s+" + re.escape(relation) + AFTER + ARTICLE + ROLE + re.escape(right) + r"(?!\w)")
    for candidate in patterns:
        for match in re.finditer(candidate, quote):
            clause_start = max(quote.rfind(mark, 0, match.start()) for mark in (".", ";", "!", "?")) + 1
            prefix = quote[clause_start:match.start()]
            if UNCERTAIN.search(prefix + match.group()):
                continue
            return True
    return False


def relation_category(predicate):
    if re.search(r"inammissibil", predicate, re.I):
        return "documented"
    return "attributed" if re.search(r"dichiar|spieg|afferm|sottoline|criticat", predicate, re.I) else "documented"


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
