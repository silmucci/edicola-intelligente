"""Prompt-only RAG experiment over the exact context in an existing run."""

import argparse
import copy
import csv
import hashlib
import json
import math
import os
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

from google import genai
from google.genai import types

from edicola.embeddings import api_key
from edicola.evaluation import (
    MeasuredModels,
    evaluation_gemini_pause_seconds,
    new_directory,
    provenance,
    report_run,
)
from edicola.evaluation_data import (
    digest,
    read_json,
    validate_dataset,
    validate_snapshot,
    write_json,
)
from edicola.evaluation_metrics import rag_assessment, score_run, sources_from_hits
from edicola.rag import (
    RagError,
    SYSTEM_INSTRUCTION,
    build_prompt,
    chat_response_rejection_reasons,
    generate_response,
    response_schema,
)
from edicola.indexing import ROOT


EXPERIMENT_ID = "completeness-v1"
INCOMPLETE_RESPONSE_STATES = {"model_abstention", "validation_failed", "not_run"}
COMPLETENESS_INSTRUCTION = SYSTEM_INSTRUCTION + """

Prima di rispondere, scomponi la domanda nei suoi elementi richiesti e controlla
tutti i passaggi forniti, non soltanto il primo o il piu evidente. Includi ogni
fatto distinto e pertinente che risponde alla domanda: persone e ruoli, quantita,
date, condizioni, attribuzioni, richieste, decisioni, proposte, sviluppi e
qualificazioni o negazioni rilevanti, ma soltanto quando documentati.
Rispondi a ciascuna parte della domanda con una struttura chiara e concisa;
raggruppa fatti collegati, evita ripetizioni e ometti dettagli non pertinenti.
Se le fonti sostengono solo una parte, fornisci quella parte e dichiara il limite.
Non colmare lacune con conoscenze esterne, supposizioni o inferenze.

Ogni affermazione deve avere una prova specifica: copia in evidence.quote una
sequenza contigua e letterale dal campo text della fonte indicata, senza
normalizzare o correggere il testo. Unisci in una stessa affermazione solo fatti
che le prove citate sostengono davvero. Se un fatto richiesto non e verificabile,
non presentarlo come vero; se nessun fatto pertinente e verificabile, astieniti.
"""


def _validate_baseline(dataset, frozen, baseline_run):
    if not isinstance(dataset, dict) or not isinstance(frozen, dict) or not isinstance(baseline_run, dict):
        raise ValueError("Dataset, snapshot o run originale non validi.")
    validate_dataset(dataset, frozen)
    catalog = validate_snapshot(frozen)
    score_run(dataset, frozen, baseline_run, catalog)
    if baseline_run["mode"] != "rag":
        raise ValueError("L'esperimento richiede una run RAG originale.")
    if baseline_run.get("configuration", {}).get("generation_prompt", "original") != "original":
        raise ValueError("La run di partenza non usa il prompt originale.")
    model = baseline_run.get("configuration", {}).get("generation_model")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("La run originale non registra il modello Gemini.")

    question_order = {
        question["id"]: index for index, question in enumerate(dataset["questions"])
    }
    actual = [(record["question_id"], record["repeat"]) for record in baseline_run["records"]]
    actual_ids = [identity for identity, _ in actual]
    if (
        not actual
        or len(actual_ids) != len(set(actual_ids))
        or any(identity not in question_order or repeat != 1 for identity, repeat in actual)
        or actual_ids != sorted(actual_ids, key=question_order.__getitem__)
    ):
        raise ValueError(
            "La run deve contenere al massimo una esecuzione per domanda, "
            "in ordine dataset e con repeat=1."
        )
    return catalog, model


def _validate_experiment_run(dataset, frozen, baseline_run, experiment_run):
    if not isinstance(experiment_run, dict):
        raise ValueError("La run sperimentale esistente non e un oggetto JSON valido.")
    catalog, model = _validate_baseline(dataset, frozen, baseline_run)
    score_run(dataset, frozen, experiment_run, catalog)
    source_run_id = digest(baseline_run)
    prompt_sha256 = hashlib.sha256(COMPLETENESS_INSTRUCTION.encode("utf-8")).hexdigest()

    expected_header = {
        "schema_version": 1,
        "origin": baseline_run["origin"],
        "mode": "rag",
        "top_k": baseline_run["top_k"],
        "snapshot_id": frozen["snapshot_id"],
        "dataset_id": digest(dataset),
        "source_run_id": source_run_id,
    }
    if any(experiment_run.get(key) != value for key, value in expected_header.items()):
        raise ValueError("La run sperimentale non corrisponde alla baseline e al dataset.")

    configuration = experiment_run.get("configuration")
    if not isinstance(configuration, dict):
        raise ValueError("Configurazione della run sperimentale mancante.")
    code_hash = configuration.get("experiment_code_sha256")
    pause_seconds = configuration.get("inter_question_pause_seconds")
    if (
        not isinstance(code_hash, str)
        or len(code_hash) != 64
        or any(character not in "0123456789abcdef" for character in code_hash)
        or type(pause_seconds) not in (int, float)
        or not math.isfinite(pause_seconds)
        or pause_seconds < 0
    ):
        raise ValueError("Metadati della configurazione sperimentale non validi.")
    overridden = {
        "generation_prompt",
        "generation_prompt_sha256",
        "experiment_code_sha256",
        "retrieval_strategy",
        "retrieval_reused_from",
        "embedding_model",
        "dimensions",
        "query_embedding_api_calls",
        "generation_cache",
        "pipeline_scope",
        "generation_seconds_scope",
        "inter_question_pause_seconds",
    }
    for key, value in baseline_run["configuration"].items():
        if key not in overridden and configuration.get(key) != value:
            raise ValueError("Configurazione sperimentale incompatibile con la baseline.")
    expected_configuration = {
        "generation_model": model,
        "generation_prompt": EXPERIMENT_ID,
        "generation_prompt_sha256": prompt_sha256,
        "retrieval_strategy": "reused_original_run",
        "retrieval_reused_from": source_run_id,
        "embedding_model": baseline_run["configuration"].get("embedding_model"),
        "dimensions": baseline_run["configuration"].get("dimensions"),
        "query_embedding_api_calls": 0,
        "generation_cache": "non utilizzata",
        "pipeline_scope": (
            "esperimento prompt-only; stessi chunk recuperati della run originale; "
            "nessun retrieval o embedding ripetuto"
        ),
        "generation_seconds_scope": "solo generazione sperimentale; retrieval riusato",
    }
    if any(configuration.get(key) != value for key, value in expected_configuration.items()):
        raise ValueError("Prompt o strategia della run sperimentale non compatibili.")

    original_records = baseline_run["records"]
    saved_records = experiment_run["records"]
    original_indexes = {
        (record["question_id"], record["repeat"]): index
        for index, record in enumerate(original_records)
    }
    failed_indexes = []
    previous_original_index = -1
    for saved_index, saved in enumerate(saved_records):
        identity = (saved["question_id"], saved["repeat"])
        original_index = original_indexes.get(identity)
        if original_index is None or original_index <= previous_original_index:
            raise ValueError(
                "La run sperimentale contiene record non presenti nella baseline "
                "o in ordine incompatibile."
            )
        original = original_records[original_index]
        if (
            saved.get("retrieval_status") != original["retrieval_status"]
            or saved.get("retrieved") != original["retrieved"]
            or saved["status"] not in ("ok", "error")
        ):
            raise ValueError("Chunk o identita dei record sperimentali alterati.")
        previous_original_index = original_index
        if saved["status"] == "error":
            if (
                saved.get("error_phase") != "generation"
                or saved.get("retrieval_status") != "ok"
                or not saved["retrieved"]
            ):
                raise ValueError("La run contiene errori non recuperabili tramite sola generazione.")
            failed_indexes.append((saved_index, original_index))
    return model, failed_indexes


def _validated_answer_ids(dataset, frozen, baseline_run, experiment_run):
    _validate_experiment_run(dataset, frozen, baseline_run, experiment_run)
    validated = set()
    for record in experiment_run["records"]:
        state, _ = rag_assessment(
            record.get("raw_response"),
            sources_from_hits(record["retrieved"]),
        )
        if record.get("response_state") != state:
            raise ValueError("Lo stato della risposta non corrisponde alla validazione RAG.")
        if record["status"] == "ok" and state == "answered":
            validated.add(record["question_id"])
    return validated


def _atomic_write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _parse_only_ids(value):
    ids = tuple(identity.strip() for identity in value.split(","))
    if not ids or any(not identity for identity in ids):
        raise argparse.ArgumentTypeError("Specificare ID separati da virgole.")
    if len(set(ids)) != len(ids):
        raise argparse.ArgumentTypeError("Gli ID specificati non devono essere duplicati.")
    return ids


def _read_ground_truth_categories(path):
    categories = {}
    try:
        with Path(path).open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if not {"ID", "Categoria"} <= set(reader.fieldnames or ()):
                raise ValueError("Il CSV Ground Truth deve contenere ID e Categoria.")
            for row in reader:
                identity = (row.get("ID") or "").strip()
                category = (row.get("Categoria") or "").strip()
                if not identity or not category or identity in categories:
                    raise ValueError("CSV Ground Truth con ID/categoria mancanti o ID duplicati.")
                categories[identity] = category
    except csv.Error as exc:
        raise ValueError("CSV Ground Truth non valido.") from exc
    if not categories:
        raise ValueError("CSV Ground Truth vuoto.")
    return categories


def _select_recovery_records(
    dataset,
    baseline_run,
    only_ids,
    *,
    ground_truth_categories=None,
    already_validated_ids=(),
):
    if only_ids is None:
        return baseline_run["records"]
    try:
        requested = tuple(only_ids)
        requested_ids = set(requested)
    except TypeError as exc:
        raise ValueError("Gli ID selezionati non sono validi.") from exc
    if (
        not requested_ids
        or len(requested) != len(requested_ids)
        or any(not isinstance(identity, str) or not identity.strip() for identity in requested)
    ):
        raise ValueError("Specificare ID domanda validi e non duplicati.")

    baseline_records = {
        record["question_id"]: record for record in baseline_run["records"]
    }
    missing_ids = requested_ids - baseline_records.keys()
    if missing_ids:
        raise ValueError(
            "ID non presenti nella baseline: " + ", ".join(sorted(missing_ids))
        )

    questions = {question["id"]: question for question in dataset["questions"]}
    already_validated = set(already_validated_ids)
    previously_answered = requested_ids & already_validated
    if previously_answered:
        raise ValueError(
            "ID gia recuperati con risposta validata: "
            + ", ".join(sorted(previously_answered))
        )

    selected_records = []
    for identity in requested:
        record = baseline_records[identity]
        state, _ = rag_assessment(
            record.get("raw_response"),
            sources_from_hits(record["retrieved"]),
        )
        if record.get("response_state") != state:
            raise ValueError(
                f"{identity}: stato della baseline non coerente con la validazione RAG."
            )
        if (
            state not in INCOMPLETE_RESPONSE_STATES
            or record.get("retrieval_status") != "ok"
            or not record.get("retrieved")
            or (
                record.get("status") == "error"
                and record.get("error_phase") != "generation"
            )
        ):
            raise ValueError(
                f"{identity}: la baseline non e una risposta incompleta recuperabile."
            )
        if ground_truth_categories is not None:
            category = ground_truth_categories.get(identity)
            if category is None:
                raise ValueError(f"{identity}: assente dalla Ground Truth.")
            if category.casefold() == "non rispondibile":
                raise ValueError(f"{identity}: domanda Non rispondibile, esclusa.")
        if identity not in questions:
            raise ValueError(f"{identity}: domanda assente dal dataset.")
        selected_records.append(record)

    order = {record["question_id"]: index for index, record in enumerate(baseline_run["records"])}
    return sorted(selected_records, key=lambda record: order[record["question_id"]])


def prompt_experiment(
    dataset,
    frozen,
    baseline_run,
    *,
    authorize_external=False,
    only_ids=None,
    ground_truth_categories=None,
    already_validated_ids=(),
    allow_literal_quote_retry=True,
    root: Path = ROOT,
    client=None,
    inter_question_sleep=None,
):
    """Rigenera solo le risposte; riusa snapshot, domande e chunk della run."""
    if not authorize_external:
        raise ValueError("Autorizzare l'invio delle domande e dei passaggi a Gemini.")
    _, model = _validate_baseline(dataset, frozen, baseline_run)
    pause_seconds = evaluation_gemini_pause_seconds()
    sleeper = time.sleep if inter_question_sleep is None else inter_question_sleep
    if not callable(sleeper):
        raise ValueError("La funzione di attesa non e valida.")

    questions = {question["id"]: question for question in dataset["questions"]}
    selected_records = _select_recovery_records(
        dataset,
        baseline_run,
        only_ids,
        ground_truth_categories=ground_truth_categories,
        already_validated_ids=already_validated_ids,
    )

    own_client = client is None
    if own_client:
        key = api_key(root)
        if not key:
            raise ValueError("Configurare GEMINI_API_KEY nell'ambiente o in .env.")
        client = genai.Client(
            api_key=key,
            vertexai=False,
            http_options=types.HttpOptions(
                timeout=30000,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )

    records = []
    total_samples = len(selected_records)
    try:
        for index, original in enumerate(selected_records, 1):
            record = copy.deepcopy(original)
            record.update(
                retrieval_seconds=None,
                generation_seconds=None,
                total_seconds=None,
                api_events=[],
                raw_response=None,
                answer=None,
                response_state="not_run",
                error_phase=None,
                error_type=None,
            )
            hits = original["retrieved"]
            if original["retrieval_status"] != "ok":
                record.update(
                    status="error",
                    response_state="not_run",
                    error_phase="retrieval",
                    error_type=original.get("error_type") or "request_or_local_error",
                )
                records.append(record)
                continue
            if not hits:
                record.update(
                    status="ok",
                    response_state="no_sources",
                    error_phase=None,
                    error_type=None,
                )
                records.append(record)
                continue

            events = []
            proxy = SimpleNamespace(models=MeasuredModels(client, events))
            sources = sources_from_hits(hits)
            prompt = build_prompt(questions[original["question_id"]]["question"], sources)
            started = time.perf_counter()
            try:
                raw = generate_response(
                    proxy,
                    model,
                    prompt,
                    response_schema(sources),
                    system_instruction=COMPLETENESS_INSTRUCTION,
                )
                state, checked = rag_assessment(raw, sources)
                if (
                    allow_literal_quote_retry
                    and only_ids is None
                    and state == "validation_failed"
                    and "quote_mismatch" in chat_response_rejection_reasons(raw, sources)
                ):
                    initial_raw = raw
                    try:
                        raw = generate_response(
                            proxy,
                            model,
                            build_prompt(
                                questions[original["question_id"]]["question"],
                                sources,
                                literal_quote_retry=True,
                            ),
                            response_schema(sources),
                            system_instruction=COMPLETENESS_INSTRUCTION,
                            single_attempt=True,
                        )
                    except (
                        RagError,
                        ValueError,
                        TypeError,
                        KeyError,
                        OSError,
                        TimeoutError,
                        ConnectionError,
                    ) as exc:
                        raw = initial_raw
                        record["retry_error"] = {
                            "phase": "generation",
                            "http_status": (
                                exc.http_status if isinstance(exc, RagError) else None
                            ),
                            "error_type": type(exc).__name__,
                        }
                    state, checked = rag_assessment(raw, sources)
                record.update(
                    status="ok",
                    raw_response=raw,
                    answer=checked.answer if checked else None,
                    response_state=state,
                )
            except (
                RagError,
                ValueError,
                TypeError,
                KeyError,
                OSError,
                TimeoutError,
                ConnectionError,
            ):
                record.update(
                    status="error",
                    error_phase="generation",
                    error_type="request_or_local_error",
                )
            finally:
                record["generation_seconds"] = time.perf_counter() - started
                record["total_seconds"] = record["generation_seconds"]
                record["api_events"] = events
                records.append(record)
                if pause_seconds > 0 and index < total_samples:
                    sleeper(pause_seconds)
    finally:
        if own_client and client is not None:
            try:
                client.close()
            except Exception:
                pass

    source_run_id = digest(baseline_run)
    prompt_sha256 = hashlib.sha256(COMPLETENESS_INSTRUCTION.encode("utf-8")).hexdigest()
    return {
        "schema_version": 1,
        "origin": baseline_run["origin"],
        "mode": "rag",
        "top_k": baseline_run["top_k"],
        "snapshot_id": frozen["snapshot_id"],
        "dataset_id": digest(dataset),
        "source_run_id": source_run_id,
        "provenance": provenance(),
        "configuration": {
            **baseline_run["configuration"],
            "generation_model": model,
            "generation_prompt": EXPERIMENT_ID,
            "generation_prompt_sha256": prompt_sha256,
            "experiment_code_sha256": hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest(),
            "retrieval_strategy": "reused_original_run",
            "retrieval_reused_from": source_run_id,
            "embedding_model": baseline_run["configuration"].get("embedding_model"),
            "dimensions": baseline_run["configuration"].get("dimensions"),
            "query_embedding_api_calls": 0,
            "generation_cache": "non utilizzata",
            "pipeline_scope": (
                "esperimento prompt-only; stessi chunk recuperati della run originale; "
                "nessun retrieval o embedding ripetuto"
            ),
            "generation_seconds_scope": "solo generazione sperimentale; retrieval riusato",
            "inter_question_pause_seconds": pause_seconds,
        },
        "records": records,
    }


def retry_errors(
    dataset,
    frozen,
    baseline_run,
    experiment_run,
    *,
    authorize_external=False,
    root: Path = ROOT,
    client=None,
    inter_question_sleep=None,
    save_progress=None,
):
    """Riprova esclusivamente errori di generazione e conserva ogni esito precedente."""
    if not authorize_external:
        raise ValueError("Autorizzare l'invio delle domande e dei passaggi a Gemini.")
    _, failed_indexes = _validate_experiment_run(
        dataset, frozen, baseline_run, experiment_run
    )
    sleeper = time.sleep if inter_question_sleep is None else inter_question_sleep
    if not callable(sleeper):
        raise ValueError("La funzione di attesa non e valida.")
    if save_progress is not None and not callable(save_progress):
        raise ValueError("La funzione di salvataggio progressivo non e valida.")
    if not failed_indexes:
        return experiment_run

    own_client = client is None
    if own_client:
        key = api_key(root)
        if not key:
            raise ValueError("Configurare GEMINI_API_KEY nell'ambiente o in .env.")
        client = genai.Client(
            api_key=key,
            vertexai=False,
            http_options=types.HttpOptions(
                timeout=30000,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )

    pause_seconds = experiment_run["configuration"].get(
        "inter_question_pause_seconds", evaluation_gemini_pause_seconds()
    )
    try:
        for retry_index, (record_index, baseline_index) in enumerate(failed_indexes):
            single_record_baseline = copy.deepcopy(baseline_run)
            single_record_baseline["records"] = [
                copy.deepcopy(baseline_run["records"][baseline_index])
            ]
            attempt = prompt_experiment(
                dataset,
                frozen,
                single_record_baseline,
                authorize_external=True,
                allow_literal_quote_retry=False,
                root=root,
                client=client,
                inter_question_sleep=lambda _seconds: None,
            )["records"][0]
            if attempt["status"] == "ok":
                experiment_run["records"][record_index] = attempt
                if save_progress is not None:
                    save_progress(copy.deepcopy(experiment_run))
            if pause_seconds > 0 and retry_index + 1 < len(failed_indexes):
                sleeper(pause_seconds)
    finally:
        if own_client and client is not None:
            try:
                client.close()
            except Exception:
                pass
    return experiment_run


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Esperimento RAG prompt-only sui chunk di una run esistente."
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--baseline-run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--authorize-external", action="store_true")
    parser.add_argument(
        "--ground-truth-csv",
        type=Path,
        help="Ground Truth CSV usata per escludere le domande Non rispondibile.",
    )
    parser.add_argument(
        "--exclude-validated-run",
        type=Path,
        action="append",
        default=[],
        metavar="RUN_JSON",
        help="Run sperimentale precedente da consultare prima della selezione; ripetibile.",
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--only-ids",
        type=_parse_only_ids,
        metavar="ID[,ID...]",
        help="Rigenera soltanto gli ID indicati, separati da virgole.",
    )
    selection.add_argument(
        "--retry-errors",
        action="store_true",
        help="Riprova solo gli errori di generazione in una run sperimentale esistente.",
    )
    args = parser.parse_args(argv)
    try:
        if not args.authorize_external:
            raise ValueError("Usare --authorize-external per autorizzare Gemini.")
        recovery_options = args.ground_truth_csv is not None or bool(
            args.exclude_validated_run
        )
        if args.only_ids is None and recovery_options:
            raise ValueError(
                "--ground-truth-csv e --exclude-validated-run richiedono --only-ids."
            )
        frozen = read_json(args.snapshot)
        dataset = read_json(args.dataset)
        baseline_run = read_json(args.baseline_run)
        if not isinstance(frozen, dict) or not isinstance(baseline_run, dict):
            raise ValueError("Snapshot o run baseline non validi.")
        if frozen["origin"] != "real" or baseline_run.get("origin") != "real":
            raise ValueError("L'esperimento Gemini richiede snapshot e run reali.")
        _validate_baseline(dataset, frozen, baseline_run)
        if args.retry_errors:
            out = args.out
            if not out.is_dir():
                raise ValueError("La directory esistente della run sperimentale non e stata trovata.")
            run_path = out / "run.json"
            if not run_path.is_file():
                raise ValueError("La run.json esistente non e stata trovata.")
            experiment_run = read_json(run_path)
            run = retry_errors(
                dataset,
                frozen,
                baseline_run,
                experiment_run,
                authorize_external=True,
                root=args.root,
                save_progress=lambda updated: _atomic_write_json(run_path, updated),
            )
            report_run(out, dataset, frozen, run)
            print(f"Risultati aggiornati: {run_path}")
            return 0

        ground_truth_categories = None
        already_validated_ids = set()
        if args.only_ids is not None:
            if args.ground_truth_csv is None:
                raise ValueError("--only-ids richiede --ground-truth-csv.")
            ground_truth_categories = _read_ground_truth_categories(
                args.ground_truth_csv
            )
            for previous_path in args.exclude_validated_run:
                previous_run = read_json(previous_path)
                already_validated_ids.update(
                    _validated_answer_ids(
                        dataset, frozen, baseline_run, previous_run
                    )
                )
            _select_recovery_records(
                dataset,
                baseline_run,
                args.only_ids,
                ground_truth_categories=ground_truth_categories,
                already_validated_ids=already_validated_ids,
            )

        out = new_directory(args.out)
        run = prompt_experiment(
            dataset,
            frozen,
            baseline_run,
            authorize_external=True,
            only_ids=args.only_ids,
            ground_truth_categories=ground_truth_categories,
            already_validated_ids=already_validated_ids,
            root=args.root,
        )
        write_json(out / "run.json", run)
        report_run(out, dataset, frozen, run)
        print(f"Risultati sperimentali separati: {out / 'run.json'}")
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"Esperimento non avviato: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
