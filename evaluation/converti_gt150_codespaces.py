#!/usr/bin/env python3
"""Converte la Ground Truth CSV in dataset JSON per edicola.evaluation.

Non verifica autonomamente gli articoli, non assegna rilevanza ai chunk,
non esegue API e non modifica alcuna edizione. Le domande confermate sono
indicate dall'utente con --confirmed-ids DOPO controllo delle fonti.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default="evaluation/data/Ground_Truth_Edicola_150_domande.csv")
    parser.add_argument("--snapshot", default="evaluation/work/snapshot.json")
    parser.add_argument("--dest", default="evaluation/work/annotations")
    parser.add_argument("--confirmed-ids", default="", help="ID verificati sulle fonti, separati da virgole, es. GT-001,GT-002")
    parser.add_argument("--overwrite", action="store_true", help="Sostituisce i JSON esistenti: non usarlo dopo avere creato run con quei file.")
    args = parser.parse_args()

    with Path(args.csv).open(encoding="utf-8-sig", newline="") as stream:
        items = list(csv.DictReader(stream))
    if len(items) != 150:
        parser.error(f"Attese esattamente 150 domande nel CSV; trovate {len(items)}.")
    required = {"ID", "Categoria", "Difficoltà", "Domanda", "Risposta di riferimento", "Edizioni (date)", "Pagine PDF", "Fatti attesi", "Errori da evitare"}
    if not required.issubset(items[0]):
        parser.error(f"Colonne CSV mancanti: {sorted(required - set(items[0]))}")
    ids = [x["ID"].strip() for x in items]
    expected = [f"GT-{i:03d}" for i in range(1, 151)]
    if ids != expected:
        parser.error("ID o ordine inattesi: le domande devono essere GT-001...GT-150, senza duplicati.")

    snap_path = Path(args.snapshot)
    if not snap_path.is_file():
        parser.error(f"Snapshot non trovato: {snap_path}. Prima esegui il comando 'snapshot'.")
    snapshot = json.loads(snap_path.read_text(encoding="utf-8"))
    snap_id = snapshot.get("snapshot_id")
    if not isinstance(snap_id, str) or not snap_id:
        parser.error("Lo snapshot non contiene uno snapshot_id valido.")

    confirmed = {v.strip().upper() for v in args.confirmed_ids.split(",") if v.strip()}
    if not confirmed <= set(ids):
        parser.error(f"ID confermati non presenti nel CSV: {sorted(confirmed - set(ids))}")
    nonanswerable = {x["ID"] for x in items if x["Categoria"].strip() == "Non rispondibile"}
    if confirmed & nonanswerable:
        parser.error("Non segnare i casi 'Non rispondibile' come answerable: richiedono una verifica esaustiva sullo snapshot e annotazioni distinte.")

    questions = []
    for row in items:
        qid = row["ID"].strip()
        points = [x.strip() for x in row["Fatti attesi"].split(";") if x.strip()]
        if not row["Domanda"].strip() or not row["Risposta di riferimento"].strip() or not points:
            parser.error(f"Domanda, risposta o fatti attesi mancanti: {qid}")
        verified = qid in confirmed
        details = (
            f"Categoria CSV: {row['Categoria']}; difficolta: {row['Difficoltà']}; "
            f"edizioni: {row['Edizioni (date)']}; pagine: {row['Pagine PDF']}. "
            f"Errori da evitare: {row['Errori da evitare']}. "
            + ("Riferimento controllato manualmente dall'utente." if verified else "RIFERIMENTO DA CONVALIDARE prima del giudizio automatico.")
        )
        questions.append({
            "id": qid,
            "question": row["Domanda"].strip(),
            "annotator": "revisore-1" if verified else "",
            "answerability": "answerable" if verified else None,
            "judgments_complete": False,
            "relevant_chunks": [],
            "nonrelevant_chunk_ids": [],
            "expected_points": points,
            "reference_answer": row["Risposta di riferimento"].strip(),
            "annotation_notes": details,
        })

    directory = Path(args.dest)
    directory.mkdir(parents=True, exist_ok=True)
    for name, subset in (("dataset_gt50_sviluppo.json", questions[:50]), ("dataset_gt100_finale.json", questions[50:])):
        outfile = directory / name
        if outfile.exists() and not args.overwrite:
            parser.error(f"{outfile} esiste già: non sovrascriverlo se vi sono run collegate. Usa --overwrite solo consapevolmente.")
        data = {
            "schema_version": 1,
            "snapshot_id": snap_id,
            "notes": "Ground Truth da CSV; 22 edizioni nel corpus. Solo i casi confermati manualmente sono marcati answerable. I giudizi sui chunk non sono ancora presenti; Recall non calcolabile.",
            "questions": subset,
        }
        outfile.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Creato: {outfile} | {len(subset)} domande | {sum(q['answerability'] == 'answerable' for q in subset)} confermate")
    print("ATTENZIONE: i casi non rispondibili vanno annotati separatamente dopo verifica dell'intero snapshot.")
    print("Per il judge sono richieste risposte RAG validate; Precision/Recall/MRR richiedono annotazioni dei chunk.")


if __name__ == "__main__":
    main()
