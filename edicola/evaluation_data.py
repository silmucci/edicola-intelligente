"""Snapshot e annotazioni sperimentali; nessuna etichetta dedotta automaticamente."""

import hashlib
import json
from dataclasses import asdict

from edicola.archive import IndexChunk
from edicola.editorial_selection import Catalog


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def snapshot(catalog, origin="real"):
    body = {"coverage": catalog.coverage, "chunks": [asdict(c) for c in sorted(catalog.chunks, key=lambda c: c.id)]}
    return {"schema_version": 1, "origin": origin, "snapshot_id": digest(body), **body}


def validate_snapshot(data):
    if data.get("schema_version") != 1 or data.get("origin") not in ("real", "simulated"):
        raise ValueError("Snapshot: versione o provenienza non valida.")
    catalog = Catalog([IndexChunk(**c) for c in data["chunks"]], {}, data["coverage"])
    if snapshot(catalog, data["origin"]) != data:
        raise ValueError("Snapshot modificato o non coerente con il suo hash.")
    ids = [c.id for c in catalog.chunks]
    if len(ids) != len(set(ids)):
        raise ValueError("Snapshot: ID duplicati.")
    for c in catalog.chunks:
        if (not c.id or not c.text.strip() or not c.metadata.get("filename") or
                type(c.metadata.get("page")) is not int or c.metadata["page"] < 1):
            raise ValueError("Snapshot: chunk senza testo o riferimento PDF/pagina valido.")
    return catalog


def dataset_template(snapshot_id=""):
    return {"schema_version": 1, "snapshot_id": snapshot_id, "notes": "Compilare manualmente. Nessuna risposta o rilevanza è predefinita.",
            "questions": [{"id": "q01", "question": "", "annotator": "", "answerability": None,
                "judgments_complete": False, "relevant_chunks": [], "nonrelevant_chunk_ids": [],
                "expected_points": [], "annotation_notes": ""}]}


def validate_dataset(data, frozen):
    catalog = validate_snapshot(frozen)
    if data.get("schema_version") != 1 or data.get("snapshot_id") != frozen["snapshot_id"]:
        raise ValueError("Dataset non collegato a questo snapshot.")
    questions = data.get("questions")
    if not isinstance(questions, list) or not questions:
        raise ValueError("Compilare almeno una domanda reale nel dataset.")
    chunks = {c.id: c for c in catalog.chunks}
    seen, warnings = set(), []
    for q in questions:
        identity = q.get("id")
        if not isinstance(identity, str) or not identity.strip() or identity in seen:
            raise ValueError("Identificativo domanda assente o duplicato.")
        seen.add(identity)
        if not isinstance(q.get("question"), str) or not q["question"].strip():
            raise ValueError(f"{identity}: compilare la domanda, senza placeholder.")
        if q.get("answerability") not in (None, "answerable", "unanswerable") or type(q.get("judgments_complete")) is not bool:
            raise ValueError(f"{identity}: stato delle annotazioni non valido.")
        relevant, negative = q.get("relevant_chunks"), q.get("nonrelevant_chunk_ids")
        if not isinstance(relevant, list) or not isinstance(negative, list):
            raise ValueError(f"{identity}: elenchi di rilevanza mancanti.")
        positive = []
        for item in relevant:
            chunk = chunks.get(item.get("chunk_id"))
            if (chunk is None or item.get("pdf") != chunk.metadata["filename"] or
                    type(item.get("page")) is not int or item["page"] != chunk.metadata["page"]):
                raise ValueError(f"{identity}: riferimento rilevante non presente nello snapshot o PDF/pagina errati.")
            positive.append(chunk.id)
        if (len(set(positive)) != len(positive) or len(set(negative)) != len(negative)
                or set(positive) & set(negative) or not set(negative) <= chunks.keys()):
            raise ValueError(f"{identity}: giudizi duplicati, contraddittori o ID sconosciuti.")
        if q["answerability"] == "unanswerable" and (positive or not q["judgments_complete"]):
            raise ValueError(f"{identity}: senza risposta richiede verifica dell'intero snapshot e nessun positivo.")
        if q["answerability"] == "answerable" and q["judgments_complete"] and not positive:
            raise ValueError(f"{identity}: domanda rispondibile senza chunk rilevanti.")
        if (positive or negative or q["judgments_complete"] or q["answerability"] is not None) and not str(q.get("annotator", "")).strip():
            raise ValueError(f"{identity}: indicare l'annotatore dei giudizi manuali.")
        if not isinstance(q.get("expected_points"), list) or any(not isinstance(p, str) or not p.strip() for p in q["expected_points"]):
            raise ValueError(f"{identity}: punti attesi non validi.")
        if not q["judgments_complete"]:
            warnings.append(f"{identity}: giudizi incompleti; recall non calcolabile e risultati non giudicati non sono negativi.")
        if q["answerability"] is None:
            warnings.append(f"{identity}: rispondibilità non annotata.")
    return warnings


SCALE = {"0": "Assente o scorretto", "1": "Gravi problemi prevalenti", "2": "Parziale, con problemi sostanziali",
         "3": "Adeguato, con difetti minori", "4": "Completo e corretto rispetto al perimetro dichiarato",
         "NA": "Non applicabile: motivare; non equivale a zero"}
CRITERIA = {
    "factual_accuracy": "Verificare ogni fatto, nome, cifra e attribuzione nei passaggi originali. 0=fatti errati prevalenti; 4=tutti supportati.",
    "faithfulness": "Confrontare il significato con le fonti: nessuna aggiunta o causalità inventata. 0=distorsioni prevalenti; 4=nessuna distorsione.",
    "citation_correctness": "Ogni riferimento PDF/pagina deve sostenere proprio l'affermazione associata. 0=riferimenti inservibili; 4=tutti pertinenti. La sola presenza non basta.",
    "answerability_handling": "Verificare astensione motivata per domande non rispondibili e risposta supportata per le altre. 0=comportamento opposto; 4=decisione appropriata.",
    "completeness": "Confrontare con i punti attesi annotati manualmente, rispettando budget e copertura. 0=nessun punto coperto; 4=tutti i punti necessari.",
    "no_duplicates": "0=ripetizioni prevalenti; 4=nessuna ripetizione della stessa notizia. Non confondere fatti correlati ma diversi.",
    "structure": "0=contenuto disorganizzato; 4=titolo, sezioni o sequenza chiari e adeguati al formato.",
    "temporal_correctness": "Controllare date e prove: pubblicazione/evento, anno contestuale, annunci/fatti. 0=date inventate o confuse; 4=tutte affidabili o dichiarate indeterminate.",
    "relation_support": "Controllare ogni arco nelle prove dei chunk: documentato/tematico, nessuna causalità inferita. 0=archi inventati; 4=tutti giustificati.",
    "audio_quality": "Ascoltare il WAV: intelligibilità, pronuncia italiana, pause, ritmo e artefatti. 0=non fruibile; 4=chiaro e naturale. Non valutabile dal solo testo.",
    "recommendation_relevance": "Leggere i passaggi e gli interessi dichiarati. 0=nessun consiglio pertinente; 4=tutti pertinenti. La corrispondenza lessicale non è una prova semantica.",
}
RUBRICS = {
    "rag": ["factual_accuracy", "faithfulness", "citation_correctness", "answerability_handling", "completeness"],
    "dossier": ["faithfulness", "completeness", "no_duplicates", "structure", "citation_correctness", "temporal_correctness"],
    "briefing": ["faithfulness", "completeness", "no_duplicates", "structure", "citation_correctness", "temporal_correctness"],
    "timeline": ["faithfulness", "completeness", "no_duplicates", "structure", "citation_correctness", "temporal_correctness"],
    "map": ["faithfulness", "completeness", "no_duplicates", "structure", "citation_correctness", "temporal_correctness", "relation_support"],
    "podcast": ["faithfulness", "completeness", "no_duplicates", "structure", "citation_correctness", "temporal_correctness", "audio_quality"],
    "personalization": ["recommendation_relevance", "no_duplicates", "completeness"],
}
