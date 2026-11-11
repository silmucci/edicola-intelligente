"""Pertinenza locale e spiegabile; non sostituisce la verifica delle citazioni.

Alias solo per selezione/ranking, mai per rendere letterale una prova che non lo è.
Nessuna query aggiuntiva, modello locale o riscrittura dei contenuti.
"""

import math
import re
from datetime import date
from collections import Counter
from types import SimpleNamespace

from edicola.map_context import joined_proofs
from edicola.timeline_dates import MONTHS

VERSION = "knowledge-relevance-v3"
STOP = set("a ad al alla alle allo ai agli all di del della delle dello dei degli da dal dalla dalle dei in nel nella nelle negli sul sulla sulle su per con contro tra fra e ed o il lo la le gli i un una uno l d che quali quale qual come cosa quando dove quanto sono è stato stata stati state si non più questo questa questi queste ci se attraverso usando entro fino".split())
INTENT = set("misur intervent economic propost sostener aiut tutelar novit aggiornament notizi tem event svilupp finanziament dibattit relativ principal criticità ricostruisc evoluzion mostr relazion politici partit istituzion".split())
GENERIC_TARGET = set("impres aziend attivit person cittadin settor".split())
INTENT.update("gennai febbrai marz april maggi giugn lugli agost settembr ottobr novembr dicembr".split())


def stem(word):
    return word[:-1] if len(word) > 4 and word[-1] in "aeio" else word


ALIASES = {}
for group in (
    "pesca pescatori pescatore pescherecci peschereccio ittico ittica marineria marinerie",
    "carburante carburanti gasolio diesel benzina",
    "impresa imprese azienda aziende",
    "mutuo mutui prestito prestiti",
    "scuola scuole scolastico scolastica istruzione",
    "sanità sanita sanitario sanitaria salute",
    "trasporto trasporti autotrasporto autotrasportatori",
    "protesta proteste manifestazione manifestazioni mobilitazione mobilitazioni corteo cortei sciopero scioperi contestazione contestazioni",
    "Abruzzo abruzzese abruzzesi",
):
    words = group.split()
    for word in words:
        ALIASES[stem(word)] = stem(words[0])


def terms(text):
    return {ALIASES.get(stem(w), stem(w)) for w in re.findall(r"[^\W\d_]+", text.casefold())
            if len(w) > 2 and w not in STOP}


class Topic:
    def __init__(self, question, chunks=()):
        self.words = terms(question)
        # Beneficiari e luoghi dichiarati sono vincoli, non parole comuni del problema.
        target = re.search(r"\b(?:sostenere|tutelare|aiutare|proteggere|favorire)\s+(.+?)(?:\s+(?:contro|attraverso|mediante|con)\b|[?!.]|$)", question, re.I)
        place = re.search(r"\b(?:comune|città|provincia|regione)\s+di\s+(.+?)(?:\s+(?:contro|attraverso|mediante|per|con|sul|sulla)\b|[?!.]|$)", question, re.I)
        city = re.search(r"\ba\s+([A-ZÀ-ÖØ-Þ][\w’'-]+)\b", question)
        # Anche formulazioni nominali: "aiuti per le scuole contro ...".
        nominal = re.search(r"\bper\s+(.+?)\s+(?:contro|attraverso|mediante)\b", question, re.I)
        beneficiary = target or nominal
        target_text = re.split(r"\b(?:nel|nella|nei|nelle|del|della)\s+(?:comune|città|provincia|regione)\b",
                               beneficiary.group(1), flags=re.I)[0] if beneficiary else ""
        self.location = terms(place.group(1)) if place else terms(city.group(1)) if city else set()
        explicit = terms(target_text) if beneficiary else self.location
        specific = explicit - GENERIC_TARGET - INTENT
        self.strict = bool(specific)
        self.focus = specific or (self.words - INTENT - GENERIC_TARGET)
        # La città delimita l'argomento, non può sostituirlo nel matching.
        if city and not beneficiary:
            self.focus = self.words - self.location - INTENT - GENERIC_TARGET
        subject = re.search(r"\b(?:chiusura|salvaguardia|riforma|criticità|problemi)\s+(?:dei|degli|delle|della|del)\s+([^\W\d_]+)", question, re.I)
        if subject and not beneficiary:
            self.focus = terms(subject.group(1))
        self.region = terms("Abruzzo") if re.search(r"\babruzz(?:o|es[ei])\b", question, re.I) else set()
        if self.focus - self.region:
            self.focus -= self.region
        self.context_pattern = None
        if "tribunal" in self.focus and re.search(r"chiusura|salvaguardia|ripristino", question, re.I):
            self.context_pattern = re.compile(r"chiusur|salvaguard|ripristin|circoscrizion|geografi|subprovincial", re.I)
        elif terms("sanità") & self.focus and re.search(r"criticità|problemi|carenze", question, re.I):
            self.context_pattern = re.compile(r"criticit|problem|deficit|disavanz|carenz|attesa|attese|posti letto|debiti|tagli", re.I)
        # Se non esistono termini discriminanti, il solo ranking semantico rimane
        # utilizzabile; non si finge di aver verificato una pertinenza lessicale.
        documents = [terms(c.text) for c in chunks]
        counts = Counter(w for words in documents for w in words)
        self.weights = {w: 1 + math.log((len(documents) + 1) / (counts[w] + 1)) for w in self.words}

    def score(self, text, *, context_required=True):
        words = terms(text)
        if self.location and not self.location <= words:
            return 0.0
        if self.focus and not (words & self.focus):
            return 0.0
        if context_required and self.context_pattern is not None and not self.context_pattern.search(text):
            return 0.0
        if not self.focus:
            return 1.0
        matched = words & self.words
        return sum(self.weights.get(w, 1) for w in matched) + 2 * len(words & self.focus) + 3 * len(words & self.region)

    def semantic_allowed(self, text, *, strong=False):
        """Vincoli espliciti anche sui candidati semantici; nessuna validazione di fatti."""
        words = terms(text)
        return ((not self.location or self.location <= words) and
                (strong or not self.location or not self.focus or bool(words & self.focus)))

    def evidence_score(self, evidence, sources, *, anchor=None):
        """Contesto locale della citazione, non l'intero chunk multicollonna.

        La finestra è solo un indizio di pertinenza: non prova relazioni fra nodi.
        Non attraversa fine frase, capoverso o altri chunk.
        """
        available = {s.id: s for s in sources}
        best = 0.0
        for entry in evidence:
            source = available.get(entry.get("source_id"))
            quote = " ".join(entry.get("quote", "").split())
            if source is None or not quote:
                continue
            original = " ".join(source.text.split())
            start = original.find(quote)
            if start < 0:
                continue
            spans = [(start, start + len(quote))]
            if anchor:
                label = " ".join(anchor.split())
                spans = [(start + m.start(), start + m.end()) for m in re.finditer(
                    r"(?<!\w)" + re.escape(label) + r"(?!\w)", quote, re.I)]
            # Una citazione ampia non attribuisce automaticamente a ogni concetto
            # il tema di un articolo diverso: usare sempre la prova del concetto.
            for start, end in spans:
                # Una frase lunga può legare autore, provvedimento e argomento.
                # Non attraversare mai il confine della frase per recuperare il tema.
                before = re.split(r"[.!?;]", original[:start])[-1]
                after = re.split(r"[.!?;]", original[end:])[0]
                if len(before) + end - start + len(after) > 1800:
                    before, after = before[-180:], after[:180]
                best = max(best, self.score(before + original[start:end] + after, context_required=False))
        return best


def select_topic_chunks(topic, chunks, hits, limit, *, preserve_editions=False):
    """Reranking di soli chunk già indicizzati; nessuna quota obbligatoria per PDF."""
    positions = {h["id"]: i for i, h in enumerate(hits)}
    scored = [(topic.score(c.text), positions.get(c.id, len(hits) + 1), c) for c in chunks]
    ranked = sorted((row for row in scored if row[0] > 0), key=lambda row: (-row[0], row[1], row[2].id))
    if ranked and (topic.location or topic.context_pattern):
        ranked = [row for row in ranked if row[0] >= ranked[0][0] * .55 or row[2].id in positions]
    # Con domanda non discriminante non espandere alla cieca sull'intero archivio.
    if not topic.focus:
        ranked = [row for row in ranked if row[2].id in positions]
    selected, seen = [], set()
    for _, _, chunk in ranked:
        signature = " ".join(chunk.text.casefold().split())
        if preserve_editions:
            signature = (chunk.metadata["filename"], signature)
        if signature not in seen:
            seen.add(signature)
            selected.append(chunk)
        if len(selected) == limit:
            break
    return selected


GENERIC_PREDICATE = re.compile(r"^(?:chiede|chiedono|si rivolge|si rivolgono)\s+(?:a|al|alla|ai|alle)$", re.I)


def scoped_score(topic, evidence, sources, anchor, contexts):
    score = topic.evidence_score(evidence, sources, anchor=anchor)
    for proof in joined_proofs(evidence, sources, contexts):
        # Contesto effimero del solo ranking, mai nuova fonte/citazione esposta.
        context = SimpleNamespace(id="_ranking", text=proof["text"])
        score = max(score, topic.evidence_score(
            [{"source_id": context.id, "quote": context.text}], [context], anchor=anchor))
    return score


def relevant_map(data, raw, sources, topic, *, contexts=None):
    """Solo dopo validate_map: prima prove valide, poi pertinenza distinta."""
    raw_nodes = {n["id"]: n for n in raw["nodes"]}
    scores, decisions, kept, utility = {}, [], [], {}
    for node in data["nodes"]:
        evidence = list(raw_nodes[node["id"]]["label"]["evidence"])
        # Un legame già provato può fornire il contesto del nodo al suo estremo;
        # mai propagarlo tramite co-occorrenza o archi scartati dal validatore.
        for edge in data["edges"]:
            if node["id"] in {edge["from_id"], edge["to_id"]}:
                evidence.extend(e for e in edge["evidence"] if e not in evidence)
        score = scoped_score(topic, evidence, sources, node["label"], contexts or {})
        if score:
            # Utilità della denominazione prima della sua connettività.
            score += 2 * len(terms(node["label"]) & topic.words)
            utility[node["id"]] = node["kind"] in {"measure", "proposal"} and bool(topic.words & INTENT)
            kept.append(node)
            scores[node["id"]] = score
        decisions.append({"node_id": node["id"], "label": node["label"], "reason": "relevant_evidence" if score else "off_topic", "score": round(score, 3)})
    kept.sort(key=lambda n: (-int(utility[n["id"]]), -scores[n["id"]]))
    ids = {n["id"] for n in kept}
    edges, secondary, rejected = [], [], []
    for i, edge in enumerate(data["edges"]):
        anchor = edge.get("topic") or edge["label"]
        if not {edge["from_id"], edge["to_id"]} <= ids or not scoped_score(topic, edge["evidence"], sources, anchor, contexts or {}):
            rejected.append({"edge": i, "reason": "off_topic"})
        elif GENERIC_PREDICATE.fullmatch(edge["label"]):
            secondary.append(edge)
            rejected.append({"edge": i, "reason": "generic_predicate_details_only"})
        else:
            edges.append(edge)
    return {"nodes": kept, "edges": edges, "context_edges": secondary}, {
        "relevance_nodes": decisions, "relevance_edges": rejected,
        "off_topic_nodes": sum(d["reason"] == "off_topic" for d in decisions),
        "off_topic_edges": sum(d["reason"] == "off_topic" for d in rejected),
        "context_only_edges": len(secondary), "relevant_nodes": len(kept), "relevant_edges": len(edges)}


def relevant_timeline(data, sources, topic):
    """Solo per destinatari/luoghi espliciti; date e classificazioni restano intatte."""
    if not topic.strict:
        return data, 0
    filtered = {name: [e for e in data[name] if topic.evidence_score(e["evidence"], sources)]
                for name in ("events", "undated_events")}
    return filtered, sum(len(data[k]) - len(filtered[k]) for k in filtered)


def scope_timeline(catalog, question):
    match = re.search(r"\bdal\s+(\d{1,2})\s+al\s+(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s+(\d{4})\b", question, re.I)
    if not match:
        return catalog
    try:
        start, end = (date(int(match[4]), MONTHS[match[3].lower()], int(match[i])).isoformat() for i in (1, 2))
    except ValueError:
        raise ValueError("Intervallo delle edizioni non valido.") from None
    if start > end:
        raise ValueError("Intervallo delle edizioni non valido.")
    files = [f for f in catalog.coverage["files"] if start <= f.get("date", "") <= end]
    names = {f["pdf"] for f in files}
    chunks = [c for c in catalog.chunks if c.metadata["filename"] in names]
    return type(catalog)(chunks, {c.id: catalog.vectors[c.id] for c in chunks if c.id in catalog.vectors},
                         {**catalog.coverage, "files": files, "requested_editions": [start, end]})


# Selezione dedicata ai prodotti visuali: mantiene il retrieval generale invariato.
VISUAL_RETRIEVAL_VERSION = "visual-retrieval-v1"
TEMPORAL_CUES = re.compile(r"\\b(?:ieri|oggi|domani|successivamente|precedentemente|dopo|prima|annunciato|convocato|approvato|replica|incontro|vertice|emergenza|(?:\\d{1,2}\\s+)?(?:gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)\\s+\\d{4})\\b", re.I)
RELATION_CUES = re.compile(r"\\b(?:ha|hanno|chiede|chiedono|critica|criticano|attacca|replica|convoca|finanzia|approva|riguarda|coinvolge|colpisce|provoca|sostiene|accusa|risponde|propone|annuncia|prevede)\\b", re.I)


def select_visual_evidence(kind, topic, chunks, hits, *, limit=28):
    """Recall selettivo per eventi o relazioni, senza mutare indice e validatori.

    I candidati devono rispettare i vincoli tematici locali. Il segnale
    temporale/relazionale è un bonus, mai una prova sufficiente da solo.
    Si evita che un'unica edizione consumi l'intero budget di contesto.
    """
    if kind not in {"timeline", "map"}:
        raise ValueError("Prodotto visuale sconosciuto")
    positions = {hit["id"]: i for i, hit in enumerate(hits)}
    distances = {hit["id"]: float(hit.get("distance", 1.0)) for hit in hits}
    matched = []
    for chunk in chunks:
        lexical = topic.score(chunk.text)
        if lexical <= 0:
            continue
        # La posizione semantica fa da preferenza, non da esclusione:
        # un articolo pertinente può non essere nei primi risultati vettoriali.
        pos = positions.get(chunk.id)
        semantic_bonus = 6 / (1 + pos / 6) if pos is not None else 0
        evidence_cues = TEMPORAL_CUES if kind == "timeline" else RELATION_CUES
        signal = min(3, len(evidence_cues.findall(chunk.text)))
        score = lexical + semantic_bonus + signal * 0.65
        matched.append((score, distances.get(chunk.id, 1.0), chunk))
    matched.sort(key=lambda item: (-item[0], item[1], item[2].id))
    if not matched:
        return []
    # Impedisce ai risultati con una sola parola generica di prevalere
    # sul nucleo tematico, senza imporre una soglia assoluta tra argomenti.
    floor = matched[0][0] * 0.38
    matched = [item for item in matched if item[0] >= floor]
    chosen, seen, by_edition = [], set(), Counter()
    for pass_number in (0, 1):
        for _, _, chunk in matched:
            if chunk.id in seen:
                continue
            filename = chunk.metadata["filename"]
            if pass_number == 0 and by_edition[filename] >= 2:
                continue
            signature = (filename, " ".join(chunk.text.casefold().split()))
            if signature in seen:
                continue
            chosen.append(chunk)
            seen.add(chunk.id)
            seen.add(signature)
            by_edition[filename] += 1
            if len(chosen) >= limit:
                return chosen
    return chosen
