#!/usr/bin/env python3
"""Pipeline locale di valutazione della Ground Truth dell'Edicola.

Collocare in evaluation/ground_truth_pipeline.py ed eseguire dalla radice del
repository: python evaluation/ground_truth_pipeline.py <comando>.

Usa il motore `python -m edicola.evaluation` esistente. Non cambia il RAG,
non esegue API se non viene passato esplicitamente --autorizza-api.
Le proposte automatiche NON diventano etichette di verita' senza revisione.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_PROJECT = Path(__file__).resolve().parent.parent
REVIEW_COLUMNS = ["ID", "Domanda", "Risposta attesa", "PDF", "Pagina",
                  "Chunk ID", "Testo", "Priorita lessicale", "Proposta",
                  "Giudizio", "Note revisione"]
QUESTION_COLUMNS = ["ID", "Domanda", "Risposta di riferimento", "Fatti attesi",
                    "Fonti verificate (SI)", "Note revisione"]
METRICS = {
    "precision_at_k": "Precision@K",
    "recall_at_k": "Recall@K",
    "mrr_at_k": "MRR@K",
    "document_coverage": "Copertura documenti per domanda",
    "global_document_coverage": "Copertura documenti globale",
    "request_error": "Errori di esecuzione",
    "retrieval_seconds": "Tempo retrieval",
    "generation_seconds": "Tempo generazione",
    "citation_technical_pass": "Validita tecnica citazioni",
    "answerability_decision_correct": "Gestione risposta/astensione",
    "llm_judge:rag:faithfulness": "LLM judge: faithfulness",
    "llm_judge:rag:completeness": "LLM judge: completezza",
    "llm_judge:rag:answer_relevance": "LLM judge: pertinenza risposta",
    "llm_judge:rag:citation_correctness": "LLM judge: citazioni",
}


def rel(project: Path, path: str) -> Path:
    p = Path(path).expanduser()
    return p if p.is_absolute() else project / p


def paths(project: Path) -> dict[str, Path]:
    base = project / "evaluation"
    return {
        "snapshot": base / "work/snapshot.json",
        "dataset": base / "work/annotations/dataset_gt50.json",
        "dataset_reviewed": base / "work/annotations/dataset_gt50_verificato.json",
        "candidates": base / "work/candidati_ground_truth.csv",
        "review": base / "work/revisione_chunks.csv",
        "questions": base / "work/revisione_domande.csv",
        "suggestions": base / "work/annotazioni_proposte_gt50.csv",
        "results": base / "results",
    }


def read_json(path: Path):
    if not path.is_file():
        raise ValueError(f"File mancante: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise ValueError(f"CSV mancante: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        sample = f.read(8192)
        f.seek(0)
        try:
            delim = csv.Sniffer().sniff(sample, delimiters=",;").delimiter
        except csv.Error:
            delim = ","
        rows = list(csv.DictReader(f, delimiter=delim))
    if not rows:
        raise ValueError(f"CSV vuoto: {path}")
    return rows


def save_csv(path: Path, columns: list[str], rows: list[dict], *, overwrite=False):
    if path.exists() and not overwrite:
        print(f"Preservato, non sovrascritto: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Creato: {path} ({len(rows)} righe)")


def save_json(path: Path, obj: dict, *, overwrite=False):
    if path.exists() and not overwrite:
        raise ValueError(f"Dataset gia' presente: {path}. Usa --sovrascrivi se intendi aggiornarlo.")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    print(f"Dataset creato: {path}")


def required(row: dict, columns: tuple[str, ...], path: str):
    for name in columns:
        if name not in row:
            raise ValueError(f"Colonna mancante nel CSV {path}: {name}")


def words(s: str) -> set[str]:
    return {w for w in re.findall(r"[\wÀ-ÿ]+", s.lower()) if len(w) >= 4}


def lexical_priority(row: dict) -> int:
    target = words(row.get("Domanda", "") + " " + row.get("Risposta attesa", ""))
    text = row.get("Testo", "").lower()
    return sum(w in text for w in target)


def validate_review_row(row: dict, index: dict, questions: dict, label="CSV"):
    required(row, ("ID", "Chunk ID", "PDF", "Pagina", "Giudizio"), label)
    qid = row["ID"].strip()
    chunk_id = row["Chunk ID"].strip()
    if qid not in questions:
        raise ValueError(f"{label}: domanda sconosciuta {qid}")
    chunk = index.get(chunk_id)
    if chunk is None:
        raise ValueError(f"{label}: chunk sconosciuto {chunk_id}")
    md = chunk["metadata"]
    if row["PDF"] != md["filename"] or int(row["Pagina"]) != md["page"]:
        raise ValueError(f"{label}: PDF/pagina non corrispondono allo snapshot per {qid}")
    if "Testo" in row and row["Testo"] and row["Testo"] != chunk["text"]:
        raise ValueError(f"{label}: testo del chunk alterato in {qid} ({chunk_id})")
    if "Domanda" in row and row["Domanda"] and row["Domanda"] != questions[qid]["question"]:
        raise ValueError(f"{label}: domanda modificata nel CSV per {qid}")
    return qid, chunk_id


def prepara(project: Path):
    p = paths(project)
    frozen, dataset = read_json(p["snapshot"]), read_json(p["dataset"])
    if frozen["snapshot_id"] != dataset["snapshot_id"]:
        raise ValueError("Snapshot e dataset non coincidono.")
    questions = {q["id"]: q for q in dataset["questions"]}
    index = {c["id"]: c for c in frozen["chunks"]}
    if len(questions) != len(dataset["questions"]):
        raise ValueError("Domande duplicate nel dataset.")

    proposals = {}
    if p["suggestions"].exists():
        for item in read_csv(p["suggestions"]):
            proposals[(item.get("ID", ""), item.get("Chunk ID", ""))] = item.get("Giudizio proposto", "")
    rows = []
    for row in read_csv(p["candidates"]):
        required(row, ("ID", "Domanda", "Risposta attesa", "PDF", "Pagina", "Chunk ID", "Testo"), str(p["candidates"]))
        row = dict(row)
        row.setdefault("Giudizio", "")
        validate_review_row(row, index, questions, "candidati")
        row["Priorita lessicale"] = lexical_priority(row)
        row["Proposta"] = proposals.get((row["ID"], row["Chunk ID"]), "")
        row["Note revisione"] = ""
        rows.append(row)
    order = {q["id"]: n for n, q in enumerate(dataset["questions"])}
    rows.sort(key=lambda r: (order[r["ID"]], -r["Priorita lessicale"], r["Chunk ID"]))
    save_csv(p["review"], REVIEW_COLUMNS, rows)
    question_rows = [
        {"ID": q["id"], "Domanda": q["question"],
         "Risposta di riferimento": q.get("reference_answer", ""),
         "Fatti attesi": "; ".join(q["expected_points"]),
         "Fonti verificate (SI)": "", "Note revisione": ""}
        for q in dataset["questions"]
    ]
    save_csv(p["questions"], QUESTION_COLUMNS, question_rows)
    print("\nCOMPILAZIONE MANUALE")
    print(f"1) In {p['review']} scrivi R o N nella colonna 'Giudizio' solo dopo aver letto il chunk.")
    print(f"2) In {p['questions']} scrivi SI solo se la risposta attesa e' verificata nelle fonti.")
    print("3) Le colonne 'Proposta' e 'Priorita lessicale' NON diventano ground truth.")
    print("4) Esegui poi: python evaluation/ground_truth_pipeline.py applica --annotatore revisore-1")


def leggi_giudizi(file: Path, index: dict, questions: dict, judgments: dict):
    if not file.is_file():
        return 0
    total = 0
    for row in read_csv(file):
        qid, cid = validate_review_row(row, index, questions, str(file))
        val = row["Giudizio"].strip().upper()
        if val in ("", "?", "DA_VERIFICARE"):
            continue
        if val not in ("R", "N"):
            raise ValueError(f"Giudizio invalido per {qid}, {cid}: '{val}'. Usare R, N o vuoto.")
        key = (qid, cid)
        if key in judgments and judgments[key] != val:
            raise ValueError(f"Giudizi in conflitto sullo stesso chunk {qid}, {cid}.")
        judgments[key] = val
        total += 1
    return total


def applica(project: Path, args):
    p = paths(project)
    frozen = read_json(p["snapshot"])
    dataset = read_json(p["dataset"])
    if frozen["snapshot_id"] != dataset["snapshot_id"]:
        raise ValueError("Snapshot e dataset non coincidono.")
    index = {c["id"]: c for c in frozen["chunks"]}
    questions = {q["id"]: q for q in dataset["questions"]}
    judgments = {}
    n1 = leggi_giudizi(p["review"], index, questions, judgments)
    n2 = leggi_giudizi(rel(project, args.hits), index, questions, judgments) if args.hits else 0
    if not p["questions"].exists():
        raise ValueError(f"Manca la revisione delle domande: {p['questions']}. Esegui 'prepara'.")
    confirmations, notes = {}, {}
    for row in read_csv(p["questions"]):
        required(row, ("ID", "Domanda", "Fonti verificate (SI)"), str(p["questions"]))
        qid = row["ID"].strip()
        if qid not in questions or row["Domanda"] != questions[qid]["question"]:
            raise ValueError(f"ID o domanda sconosciuta nella revisione: {qid}")
        if qid in confirmations:
            raise ValueError(f"Domanda duplicata: {qid}")
        value = row["Fonti verificate (SI)"].strip().upper()
        if value not in ("", "SI", "?", "NO"):
            raise ValueError(f"Valore non valido per {qid}: usare SI o lasciare vuoto.")
        confirmations[qid] = (value == "SI")
        notes[qid] = row.get("Note revisione", "").strip()
    if set(confirmations) != set(questions):
        raise ValueError("Il CSV delle domande deve contenere tutte le domande del dataset.")
    positives = defaultdict(list)
    negatives = defaultdict(list)
    for (qid, cid), label in judgments.items():
        chunk = index[cid]
        if label == "R":
            positives[qid].append({"chunk_id": cid, "pdf": chunk["metadata"]["filename"],
                                   "page": chunk["metadata"]["page"]})
        else:
            negatives[qid].append(cid)
    for q in dataset["questions"]:
        qid = q["id"]
        q["relevant_chunks"] = sorted(positives[qid], key=lambda x: x["chunk_id"])
        q["nonrelevant_chunk_ids"] = sorted(negatives[qid])
        q["judgments_complete"] = False  # Mai dedurre completezza dal pool candidato.
        q["answerability"] = "answerable" if confirmations[qid] else None
        if q["answerability"] == "answerable" and (not q["relevant_chunks"] or not q["expected_points"]):
            raise ValueError(f"{qid}: SI richiede almeno un chunk R verificato e punti attesi.")
        if q["relevant_chunks"] or q["nonrelevant_chunk_ids"] or q["answerability"] is not None:
            q["annotator"] = args.annotatore.strip()
        if notes[qid]:
            q["annotation_notes"] = q.get("annotation_notes", "") + " | Revisione: " + notes[qid]
    if not args.annotatore.strip() and (judgments or any(confirmations.values())):
        raise ValueError("Specificare il nome/pseudonimo dell'annotatore con --annotatore.")
    out = rel(project, args.out) if args.out else p["dataset_reviewed"]
    save_json(out, dataset, overwrite=args.sovrascrivi)
    confirmed = sum(q["answerability"] == "answerable" for q in dataset["questions"])
    print(f"R: {sum(map(len, positives.values()))}; N: {sum(map(len, negatives.values()))}; "
          f"domande rispondibili confermate: {confirmed}/50")
    print("Recall@K resta non disponibile: non sono stati giudicati tutti i chunk dello snapshot.")
    print(f"Per verificare: python -m edicola.evaluation validate --snapshot {p['snapshot']} --dataset {out}")
    if (n1 + n2) == 0:
        print("ATTENZIONE: nessun giudizio R/N confermato. Non saranno calcolabili Precision@K e MRR@K.")


def subprocess_evaluation(project: Path, root: Path, cmd: list[str]):
    if not root.exists():
        raise ValueError(f"Archivio runtime non trovato: {root}; configura EVAL_ROOT come fatto per lo snapshot.")
    env = os.environ.copy()
    # Leggi .env del repository, se presente. Mai stampare le chiavi.
    env_file = project / ".env"
    if env_file.exists():
        try:
            from dotenv import dotenv_values
            for key, value in dotenv_values(env_file).items():
                if value is not None and key not in env:
                    env[key] = value
        except ImportError:
            pass
    full = [sys.executable, "-m", "edicola.evaluation", "--root", str(root)] + cmd
    print("Avvio motore di valutazione esistente...", flush=True)
    subprocess.run(full, cwd=project, env=env, check=True)


def eval_root(project: Path, name: str | None) -> Path:
    value = name or os.environ.get("EVAL_ROOT")
    if not value:
        raise ValueError("EVAL_ROOT non e' definita. Ripeti export EVAL_ROOT=... con prepare_cloud come gia' fatto.")
    return rel(project, value)


def selected_dataset(project: Path, name: str | None) -> Path:
    p = paths(project)
    return rel(project, name) if name else (p["dataset_reviewed"] if p["dataset_reviewed"].exists() else p["dataset"])


def new_results_dir(project: Path, prefix: str, specified: str | None):
    p = paths(project)
    out = rel(project, specified) if specified else p["results"] / (prefix + "-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"))
    if out.exists():
        raise ValueError(f"Cartella risultati gia' presente: {out}; scegline un'altra tramite --out.")
    return out


def riepilogo(directory: Path):
    file = directory / "summary.csv"
    if not file.exists():
        raise ValueError(f"Non trovo il report {file}.")
    rows = read_csv(file)
    selected = {r["metric"]: r for r in rows if r.get("metric") in METRICS}
    print("\nMETRICHE VERIFICATE DAL MOTORE DI VALUTAZIONE")
    for metric, title in METRICS.items():
        r = selected.get(metric)
        if not r:
            continue
        n = int(r.get("n") or 0)
        missing = int(r.get("missing") or 0)
        mean = r.get("mean", "")
        if not mean or n == 0:
            val = "NON CALCOLABILE"
        elif r.get("unit") == "ratio":
            val = f"{float(mean)*100:.1f}%"
        elif r.get("unit") == "score_0_4":
            val = f"{float(mean):.2f}/4"
        elif r.get("unit") == "seconds":
            val = f"{float(mean):.2f} s"
        else:
            val = f"{float(mean):.3f}"
        print(f"{title:34s} {val:19s} n={n} mancanti={missing}")
    print("\nFile della run:")
    for name in ("report.md", "metrics.csv", "summary.csv", "metrics.html", "run.json", "judge.json"):
        f = directory / name
        if f.exists():
            print(" -", f)
    print("\nNota: valori mancanti = metriche non valutabili, non punteggi zero.")


def benchmark(project: Path, args):
    p = paths(project)
    if not args.autorizza_api:
        raise ValueError("Per inviare domande e fonti a Gemini aggiungi --autorizza-api.")
    frozen = read_json(p["snapshot"])
    dataset_file = selected_dataset(project, args.dataset)
    dataset = read_json(dataset_file)
    if frozen["snapshot_id"] != dataset["snapshot_id"]:
        raise ValueError("Snapshot e dataset non coincidono.")
    q = dataset["questions"][:args.limite]
    n_answers = sum(row["answerability"] == "answerable" for row in q)
    n_labels = sum(len(row["relevant_chunks"]) + len(row["nonrelevant_chunk_ids"]) for row in q)
    print(f"Dataset: {dataset_file}; domande richieste: {len(q)}, rispondibili verificate: {n_answers}, "
          f"giudizi sui chunk: {n_labels}")
    if n_labels == 0:
        print("AVVISO: Precision@K e MRR@K resteranno non calcolabili senza giudizi sui chunk top-K.")
    if n_answers == 0 and args.modo == "rag":
        print("AVVISO: il giudice LLM non potra' valutare le risposte senza domande rispondibili verificate.")
    out = new_results_dir(project, f"{args.modo}-k{args.k}-{args.limite}", args.out)
    subprocess_evaluation(project, eval_root(project, args.root), [
        "benchmark", "--snapshot", str(p["snapshot"]), "--dataset", str(dataset_file),
        "--mode", args.modo, "--k", str(args.k), "--limit", str(args.limite),
        "--authorize-external", "--out", str(out)])
    riepilogo(out)
    print("\nPer verificare gli hit recuperati: python evaluation/ground_truth_pipeline.py hit --run", out / "run.json")


def hit_review(project: Path, args):
    p = paths(project)
    run = read_json(rel(project, args.run))
    dataset_path = selected_dataset(project, args.dataset)
    dataset = read_json(dataset_path)
    questions = {q["id"]: q for q in dataset["questions"]}
    if run.get("snapshot_id") != dataset["snapshot_id"]:
        raise ValueError("Run e dataset su snapshot diversi.")
    reviewed = {}
    if p["review"].exists():
        for row in read_csv(p["review"]):
            label = row.get("Giudizio", "").strip().upper()
            if label in ("R", "N"):
                reviewed[(row["ID"], row["Chunk ID"])] = label
    rows = {}
    for rec in run["records"]:
        if rec["retrieval_status"] != "ok":
            continue
        qid = rec["question_id"]
        if qid not in questions:
            raise ValueError(f"Domanda sconosciuta in run: {qid}")
        for rank, h in enumerate(rec["retrieved"], 1):
            key = (qid, h["id"])
            if key not in rows:
                rows[key] = {"ID": qid, "Domanda": questions[qid]["question"],
                             "Risposta attesa": questions[qid].get("reference_answer", ""),
                             "PDF": h["filename"], "Pagina": h["page"],
                             "Chunk ID": h["id"], "Testo": h["text"],
                             "Posizione retrieval": str(rank),
                             "Giudizio": reviewed.get(key, ""), "Note revisione": ""}
            else:
                rows[key]["Posizione retrieval"] += f", {rank}"
    out = rel(project, args.out) if args.out else p["review"].parent / f"revisione_hits_{Path(args.run).parent.name}.csv"
    columns = ["ID", "Domanda", "Risposta attesa", "PDF", "Pagina", "Chunk ID",
               "Testo", "Posizione retrieval", "Giudizio", "Note revisione"]
    save_csv(out, columns, list(rows.values()))
    print("Compila R/N sui chunk recuperati, poi 'applica --hits <percorso file>'.")
    print("Le run gia' eseguite usano l'hash del vecchio dataset: dopo 'applica' va eseguita una nuova run.")


def giudica(project: Path, args):
    p = paths(project)
    if not args.autorizza_api:
        raise ValueError("Il giudice usa API esterne: aggiungi --autorizza-api.")
    run_path = rel(project, args.run)
    run = read_json(run_path)
    dataset_path = selected_dataset(project, args.dataset)
    dataset = read_json(dataset_path)
    if run["snapshot_id"] != dataset["snapshot_id"]:
        raise ValueError("Run e dataset su snapshot diversi.")
    if run["mode"] != "rag":
        raise ValueError("Il giudice richiede una run RAG.")
    if not any(q["answerability"] == "answerable" for q in dataset["questions"]):
        raise ValueError("Nessuna domanda confermata rispondibile: compila la revisione, poi 'applica'.")
    out = new_results_dir(project, "judge-rag", args.out)
    model = args.modello or os.environ.get("GEMINI_RAG_MODEL") or "gemini-3.5-flash-lite"
    subprocess_evaluation(project, eval_root(project, args.root), [
        "judge", "--snapshot", str(p["snapshot"]), "--dataset", str(dataset_path),
        "--run", str(run_path), "--provider", args.provider,
        "--model", model, "--limit", str(args.limite),
        "--authorize-external", "--out", str(out)])
    riepilogo(out)


def main():
    parser = argparse.ArgumentParser(description="Valutazione della ground truth usando edicola.evaluation.")
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT,
                        help="Radice del repository (di norma non serve specificarla).")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepara", help="Prepara CSV di revisione senza chiamate API e senza inventare giudizi.")
    a = sub.add_parser("applica", help="Trasferisce nel JSON soltanto giudizi R/N e SI confermati.")
    a.add_argument("--hits", help="CSV di revisione dei chunk top-K recuperati, se presente.")
    a.add_argument("--annotatore", default="revisore-1")
    a.add_argument("--out", help="Dataset JSON di destinazione.")
    a.add_argument("--sovrascrivi", action="store_true")
    b = sub.add_parser("benchmark", help="Esegue il motore benchmark reale, genera report e grafici.")
    b.add_argument("--modo", choices=("retrieval", "rag"), default="rag")
    b.add_argument("--k", type=int, default=3)
    b.add_argument("--limite", type=int, default=50)
    b.add_argument("--dataset")
    b.add_argument("--root")
    b.add_argument("--out")
    b.add_argument("--autorizza-api", action="store_true")
    h = sub.add_parser("hit", help="Esporta i top-K effettivamente recuperati per giudicarli.")
    h.add_argument("--run", required=True)
    h.add_argument("--dataset")
    h.add_argument("--out")
    j = sub.add_parser("giudica", help="Esegue il giudice LLM sul benchmark RAG.")
    j.add_argument("--run", required=True)
    j.add_argument("--dataset")
    j.add_argument("--provider", choices=("gemini", "groq"), default="gemini")
    j.add_argument("--modello")
    j.add_argument("--limite", type=int, default=50)
    j.add_argument("--root")
    j.add_argument("--out")
    j.add_argument("--autorizza-api", action="store_true")
    s = sub.add_parser("riepilogo", help="Mostra le metriche di una run senza chiamate API.")
    s.add_argument("--directory", required=True)
    args = parser.parse_args()
    project = args.project_root.resolve()
    try:
        if args.command == "prepara":
            prepara(project)
        elif args.command == "applica":
            applica(project, args)
        elif args.command == "benchmark":
            if not 1 <= args.k <= 5 or not 1 <= args.limite <= 100:
                raise ValueError("K deve essere 1..5; limite deve essere 1..100.")
            benchmark(project, args)
        elif args.command == "hit":
            hit_review(project, args)
        elif args.command == "giudica":
            if not 1 <= args.limite <= 100:
                raise ValueError("Limite deve essere 1..100.")
            giudica(project, args)
        elif args.command == "riepilogo":
            riepilogo(rel(project, args.directory))
    except (ValueError, FileNotFoundError, subprocess.CalledProcessError, KeyError, OSError) as exc:
        print(f"ERRORE: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
