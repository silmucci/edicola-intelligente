"""Prove linguistiche locali per archi: nessuna inferenza dalla sola co-occorrenza."""

import re


VERSION = "concept-map-v15"
# Solo elementi grammaticali trasparenti; niente wildcard che scavalchino altri attori.
ADVERB = r"(?:oggi|ieri|anche|già|poi|ufficialmente|formalmente|direttamente|definitivamente)"
AUXILIARY = r"(?:ha|hanno|aveva|avevano|è|sono|era|erano|stato|stata|stati|state)"
LEGAL_REFERENCE = r"\(\s*(?:ex\s+)?\d{1,4}(?:[./]\d{1,4}){0,2}\s*\)"
BEFORE = rf"(?:\s*,?\s+(?:{ADVERB}|{AUXILIARY})){{0,3}}(?:\s+{LEGAL_REFERENCE})?\s*,?\s+"
PARTY = r"(?:fratelli\s+d['’]italia|partito\s+democratico|pd|fdi|forza\s+italia|lega|movimento\s+5\s+stelle)"
ROLE = rf"(?:(?:deputato|senatore|senatrice|presidente|consigliere|consigliera|sindaco|ministro)(?:\s+abruzzese)?(?:\s+(?:di|del|della)\s+{PARTY}(?:\s*\([a-z. ]{{2,12}}\))?)?\s+)?"
PURPOSE = r"(?:\s+presentat[oaie]\s+per\s+(?:garantire|assicurare|tutelare)\s+la\s+(?:salvaguardia|sopravvivenza|tutela)\s+(?:dei|degli)\s+(?:(?:quattro|tre|due)\s+)?(?:presidi\s+giudiziari|tribunali|uffici\s+giudiziari))?"
AFTER = rf"(?:\s+{ADVERB}){{0,2}}(?:\s+con\s+(?:una?\s+)?(?:delibera|decreto|voto|decisione)(?:\s+unanime)?)?\s+"
ARTICLE = r"(?:(?:il|lo|la|i|gli|le|un|una|uno|l['’])\s*)?(?:(?:citato|citata|stesso|stessa|suddetto|suddetta)\s+)?"
DESIGNATION = r"(?:disegno\s+di\s+legge|proposta\s+di\s+legge|decreto|provvedimento|piano|progetto|riforma)\s+"
SPEECH = {"ha dichiarato", "ha spiegato", "ha affermato", "ha sottolineato", "dichiara", "spiega", "afferma", "sottolinea"}
UNCERTAIN = re.compile(r"\b(non|mai|nessun[oa]?|senza|potrebbe|potrebbero|dovrebbe|dovrebbero|sarebbe|sarebbero|avrebbe|avrebbero|vorrebbe|vorrebbero|forse|possibile|probabilmente|ipotizza|ipotizzano|smentisce|smentiscono|nega|negano|se)\b", re.I)
THEME_LINKS = ("riguarda", "riguardano", "si occupa di", "si occupano di", "tratta", "trattano",
               "è dedicato a", "è dedicata a", "sono dedicati a", "sono dedicate a",
               "si concentra su", "si concentrano su")


def normalized(text):
    return " ".join(text.casefold().split())


def documented_relation(left, relation, right, quote, *, _aliases=True):
    """Soggetto-predicato-oggetto nella stessa proposizione, con modificatori limitati.

    La relazione è letterale. Voci passive sono ammesse se label conserva ausiliari
    e preposizione della fonte (es. 'è stato approvato dal'), senza invertirne il senso.
    """
    if _aliases:
        variants = []
        for endpoint in (left, right):
            found = [m[1] for m in re.finditer(r"(?<!\w)" + re.escape(endpoint) + r"\s*\(\s*([A-Z.]{2,12})\s*\)", quote, re.I)
                     if re.fullmatch(r"[A-Z][A-Z.]{1,11}", m[1])]
            variants.append([endpoint] + list(dict.fromkeys(found)))
        if any(documented_relation(a, relation, b, quote, _aliases=False)
               for a in variants[0] for b in variants[1] if (a, b) != (left, right)):
            return True
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
    # Denominazione composta nella stessa proposizione: "Il Senato ha approvato
    # il disegno di legge ColtivaItalia". I due estremi e il verbo restano letterali.
    if len(right.split()) <= 4:
        patterns.append(r"(?<!\w)" + re.escape(left) + PURPOSE + BEFORE +
                        re.escape(relation) + AFTER + ARTICLE + DESIGNATION +
                        re.escape(right) + r"(?!\w)")
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


# Associazioni di argomento: contesti diversi e citazioni distinte sono ammessi.
# Sono legami NON fattuali; gli archi di azione restano verificati da documented_relation.
SEMANTIC_ALIASES = {
    "agricol": "agricoltura", "agricoltur": "agricoltura", "agricoltor": "agricoltura",
    "coltivazion": "agricoltura", "coltiv": "agricoltura", "rural": "agricoltura",
    "occupazion": "lavoro", "lavor": "lavoro", "lavorator": "lavoro",
    "impieg": "lavoro", "occupat": "lavoro",
    "energi": "energia", "energet": "energia", "elettric": "energia",
    "nuclear": "nucleare", "reattor": "nucleare",
    "sanit": "sanità", "sanitari": "sanità", "salut": "sanità",
    "scuol": "scuola", "istruzion": "scuola", "scolastic": "scuola",
}
GENERIC_THEMES = {"govern", "senat", "politic", "politich", "relazion", "istituzion",
                  "istituzional", "provvediment", "misur", "legge", "disegn",
                  "propost", "pian", "ital", "itali", "italian", "italia",
                  "minist", "president", "notizi", "giornal", "articol", "novembr",
                  "dicembr", "ottobr", "approv", "pubblic", "stat", "nazional"}
CAUSAL_THEME = re.compile(r"\b(?:causa|provoca|determina|comporta|conseguenza|effetto|responsabil[ei])\b", re.I)


def semantic_terms(value):
    """Stemming leggero e sinonimi di settore SOLO per la Mappa."""
    from edicola.knowledge_relevance import terms
    words = terms(value)
    return {SEMANTIC_ALIASES.get(word, word) for word in words
            if word not in GENERIC_THEMES and len(word) >= 4}


def anchored_contexts(endpoint, evidence):
    """Raccoglie soltanto le proposizioni in cui compare letteralmente l'entità."""
    pattern = re.compile(r"(?<!\w)" + re.escape(endpoint) + r"(?!\w)", re.I)
    for item in evidence:
        if not isinstance(item, dict) or not isinstance(item.get("quote"), str):
            continue
        quote = item["quote"]
        for sentence in re.split(r"(?<=[.!?;])\s+|\n+", quote):
            if pattern.search(sentence):
                yield item, semantic_terms(sentence), sentence


def semantic_vector_similarity(first, second):
    """Similarità soltanto tra vettori GIA' presenti, mai nuove chiamate AI."""
    from math import sqrt
    try:
        dot = sum(float(x) * float(y) for x, y in zip(first, second))
        na = sqrt(sum(float(x) ** 2 for x in first))
        nb = sqrt(sum(float(y) ** 2 for y in second))
        return dot / (na * nb) if na and nb else 0.0
    except (TypeError, ValueError, OverflowError):
        return 0.0


def contextual_theme(left, right, theme, evidence, *, vectors=None):
    """Verifica un tema attraverso DUE prove locali, anche in articoli differenti.

    Nessuna associazione basata sulla sola compresenza nel chunk. Servono una
    citazione per ogni estremo e un contesto specifico comune, con equivalenze
    lessicali dichiarate; l'affinità fra embedding può sostenere un paraphrase
    quando almeno un estremo menziona il tema. Non autorizza azioni o causalità.
    """
    if CAUSAL_THEME.search(theme) or len(theme) > 100:
        return False
    topic = semantic_terms(theme)
    if not topic:
        return False
    a = list(anchored_contexts(left, evidence))
    b = list(anchored_contexts(right, evidence))
    for left_entry, left_words, left_sentence in a:
        for right_entry, right_words, right_sentence in b:
            # Una stessa frase copiata due volte non costituisce due prove
            # contestuali indipendenti: niente archi tematici ornamentali.
            if (left_entry.get("source_id") == right_entry.get("source_id")
                    and normalized(left_sentence) == normalized(right_sentence)):
                continue
            # Prove locali, non un elenco di concetti sparsi nello stesso PDF.
            common = left_words & right_words
            if topic & common:
                return True
            # Un embedding simile non prova che un articolo citi la
            # STESSA legge o iniziativa nominata. Per i nomi propri servono
            # riferimenti espliciti in entrambe le frasi.
            named_initiative = bool(re.search(r"[a-zà-öø-ÿ][A-ZÀ-ÖØ-Þ]", theme))
            if named_initiative or not vectors or not (topic & (left_words | right_words)):
                continue
            first = vectors.get(left_entry.get("source_id"))
            second = vectors.get(right_entry.get("source_id"))
            if (first is not None and second is not None
                    and left_entry.get("source_id") != right_entry.get("source_id")
                    and len(left_words) >= 2 and len(right_words) >= 2
                    and semantic_vector_similarity(first, second) >= 0.86):
                return True
    return False
