"""Pertinenza locale e spiegabile; non sostituisce la verifica delle citazioni.

Alias solo per selezione/ranking, mai per rendere letterale una prova che non lo è.
Nessuna query aggiuntiva, modello locale o riscrittura dei contenuti.
"""

import math
import re
from collections import Counter
from types import SimpleNamespace

from edicola.map_context import joined_proofs

VERSION = "knowledge-relevance-v1"
STOP = set("a ad al alla alle allo ai agli all di del della delle dello dei degli da dal dalla dalle dei in nel nella nelle negli sul sulla sulle su per con contro tra fra e ed o il lo la le gli i un una uno l d che quali quale qual come cosa quando dove quanto sono è stato stata stati state si non più questo questa questi queste ci se attraverso usando entro fino".split())
INTENT = set("misur intervent economic propost sostener aiut tutelar novit aggiornament notizi tem event svilupp finanziament".split())
GENERIC_TARGET = set("impres aziend attivit person cittadin settor".split())


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
        # Anche formulazioni nominali: "aiuti per le scuole contro ...".
        nominal = re.search(r"\bper\s+(.+?)\s+(?:contro|attraverso|mediante)\b", question, re.I)
        beneficiary = target or nominal
        target_text = re.split(r"\b(?:nel|nella|nei|nelle|del|della)\s+(?:comune|città|provincia|regione)\b",
                               beneficiary.group(1), flags=re.I)[0] if beneficiary else ""
        self.location = terms(place.group(1)) if place else set()
        explicit = terms(target_text) if beneficiary else self.location
        specific = explicit - GENERIC_TARGET - INTENT
        self.strict = bool(specific)
        self.focus = specific or (self.words - INTENT - GENERIC_TARGET)
        # Se non esistono termini discriminanti, il solo ranking semantico rimane
        # utilizzabile; non si finge di aver verificato una pertinenza lessicale.
        documents = [terms(c.text) for c in chunks]
        counts = Counter(w for words in documents for w in words)
        self.weights = {w: 1 + math.log((len(documents) + 1) / (counts[w] + 1)) for w in self.words}

    def score(self, text):
        words = terms(text)
        if self.location and not self.location <= words:
            return 0.0
        if self.focus and not (words & self.focus):
            return 0.0
        if not self.focus:
            return 1.0
        matched = words & self.words
        return sum(self.weights.get(w, 1) for w in matched) + 2 * len(words & self.focus)

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
                before = original[max(0, start - 180):start]
                after = original[end:end + 180]
                before = re.split(r"[.!?]", before)[-1]
                after = re.split(r"[.!?]", after)[0]
                best = max(best, self.score(before + original[start:end] + after))
        return best


def select_topic_chunks(topic, chunks, hits, limit):
    """Reranking di soli chunk già indicizzati; nessuna quota obbligatoria per PDF."""
    positions = {h["id"]: i for i, h in enumerate(hits)}
    scored = [(topic.score(c.text), positions.get(c.id, len(hits) + 1), c) for c in chunks]
    ranked = sorted((row for row in scored if row[0] > 0), key=lambda row: (-row[0], row[1], row[2].id))
    # Con domanda non discriminante non espandere alla cieca sull'intero archivio.
    if not topic.focus:
        ranked = [row for row in ranked if row[2].id in positions]
    selected, seen = [], set()
    for _, _, chunk in ranked:
        signature = " ".join(chunk.text.casefold().split())
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
