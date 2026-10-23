"""CSV, schede umane, tabelle Markdown e grafici Altair da misure presenti."""

import csv
import json

from edicola.evaluation_data import CRITERIA, RUBRICS, SCALE, write_json
from edicola.evaluation_metrics import summarize


REVIEW_FIELDS = ["run_id", "item_id", "kind", "origin", "reviewer", "criterion", "score", "evidence", "notes"]


def write_csv(path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def review_rows(kind, item_id, origin, run_id=""):
    return [{"run_id": run_id, "item_id": item_id, "kind": kind, "origin": origin, "reviewer": "",
             "criterion": c, "score": "", "evidence": "", "notes": ""} for c in RUBRICS[kind]]


def read_reviews(path, expected_run=None, allowed_items=None):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != REVIEW_FIELDS:
            raise ValueError("Intestazione della scheda umana non valida.")
        reviews = list(reader)
    rows, seen = [], set()
    for r in reviews:
        if (r["kind"] not in RUBRICS or r["criterion"] not in RUBRICS[r["kind"]]
                or r["origin"] not in ("real", "simulated") or not r["item_id"]
                or (expected_run is not None and r["run_id"] != expected_run)
                or (allowed_items is not None and r["item_id"] not in allowed_items)):
            raise ValueError("Scheda umana: criterio, provenienza o riferimento al campione non valido.")
        score = r["score"].strip()
        if score not in ("", "NA", "0", "1", "2", "3", "4"):
            raise ValueError("Punteggio umano: usare 0–4, NA motivato oppure lasciare vuoto.")
        if score and (not r["reviewer"].strip() or not (r["notes"] if score == "NA" else r["evidence"]).strip()):
            raise ValueError("Ogni giudizio richiede valutatore e prove; NA richiede motivazione.")
        key = tuple(r[f] for f in ("run_id", "item_id", "kind", "origin", "reviewer", "criterion"))
        if key in seen:
            raise ValueError("Giudizio umano duplicato per lo stesso valutatore.")
        seen.add(key)
        rows.append({"item_id": r["item_id"], "origin": r["origin"], "metric": f"human:{r['kind']}:{r['criterion']}",
                     "value": int(score) if score.isdigit() else None, "unit": "score_0_4",
                     "note": "Non applicabile" if score == "NA" else ("Da valutare" if not score else f"Valutatore: {r['reviewer']}")})
    return rows


def render_report(out, rows, *, metadata, warnings=(), review_template=()):
    out.mkdir(parents=True, exist_ok=True)
    summary = summarize(rows)
    write_csv(out / "metrics.csv", rows, ["item_id", "origin", "metric", "value", "unit", "note"])
    write_csv(out / "summary.csv", summary, ["origin", "metric", "unit", "n", "missing", "mean", "median", "p95"])
    write_json(out / "rubrics.json", {"scale": SCALE, "criteria": CRITERIA, "products": RUBRICS})
    # Una rigenerazione del report non sovrascrive annotazioni umane già compilate.
    if review_template and not (out / "human_review.csv").exists():
        write_csv(out / "human_review.csv", review_template, REVIEW_FIELDS)
    def cell(value):
        return "mancante" if value is None else (f"{value:.4f}" if isinstance(value, float) else str(value).replace("|", "/").replace("\n", " "))
    lines = ["# Report sperimentale — Edicola Digitale Intelligente", "",
        "Le misure reali, simulate e mancanti sono distinte. La provenienza dei file importati è dichiarata, non certificata da questo strumento.", "",
        "## Protocollo e provenienza", "", "```json", json.dumps(metadata, ensure_ascii=False, indent=2), "```", "",
        "## Statistiche descrittive", "",
        "| Provenienza | Metrica | Unità | n validi | Mancanti/NA | Media | Mediana | P95 |",
        "|---|---|---|---:|---:|---:|---:|---:|"]
    for s in summary:
        lines.append("| " + " | ".join(cell(s[f]) for f in ("origin", "metric", "unit", "n", "missing", "mean", "median", "p95")) + " |")
    lines += ["", "P95: interpolazione lineare, pubblicato solo con almeno 20 campioni validi per metrica/provenienza. Media e mediana richiedono almeno un campione. I mancanti e NA non diventano zero.", "",
        "Ogni campione automatico è una domanda-esecuzione. Ripetizioni della stessa domanda non sono osservazioni indipendenti: non usarle come aumento della numerosità del test di qualità. Le statistiche non sono intervalli di confidenza. I punteggi umani 0–4 sono ordinali: la media è solo descrittiva; conservare le valutazioni individuali.", "",
        "## Interpretazione", "",
        "- Precision@K divide per K anche se vengono restituiti meno risultati. Un risultato non giudicato non viene trattato automaticamente come negativo.",
        "- Recall@K richiede giudizi esaustivi sullo snapshot e almeno un rilevante. MRR@K è il reciproco del primo rango rilevante entro K; resta mancante se un rango precedente non è giudicato o non esistono positivi annotati.",
        "- Copertura documentale = PDF distinti recuperati / PDF indicizzati nello snapshot. global_document_coverage usa l'unione su tutta la run; non equivale alla media delle coperture delle domande.",
        "- La verifica tecnica delle citazioni controlla schema, ID e prove letterali: non dimostra accuratezza fattuale, implicazione semantica o completezza. Queste richiedono la scheda umana e i passaggi originali.",
        "- Tempi di retrieval includono lettura locale ed embedding della domanda; generazione include chiamate LLM e retry. Il totale include orchestrazione e validazione, esclude UI e preparazione del dataset. I tempi falliti sono separati dai successi.",
        "- api_calls conta invocazioni SDK effettive, compresi i retry applicativi; retry SDK disattivati nel benchmark. Gli errori HTTP sono conteggi per tentativo, non per utente. Nessuna stima di costo o garanzia sul piano gratuito.",
        "- Copertura degli interessi è una corrispondenza lessicale del prototipo, non pertinenza semantica misurata. Differenze dopo feedback rappresentano regole esplicite, non apprendimento automatico.", "",
        "## Limiti e dati mancanti", ""]
    lines += [f"- {w}" for w in warnings] or ["- Nessun avviso di coerenza; ciò non certifica la qualità delle annotazioni."]
    lines += ["- Archivio parziale: le conclusioni riguardano soltanto lo snapshot indicizzato, non tutti i quotidiani o gli eventi reali.",
        "- Nessuna accuratezza/fedeltà/qualità audio è attribuita senza valutazione umana. Evitare conclusioni generalizzate da un campione di convenienza.", "",
        "## Grafici e materiali", "", "Aprire `metrics.html` per i grafici delle medie, separati per unità e metrica; `metrics.vl.json` conserva la specifica Altair/Vega-Lite. L'HTML usa le librerie Vega da CDN solo all'apertura nel browser: nessuna chiamata Gemini, ma occorre rete per caricare il renderer. I valori non vengono inviati a Gemini. CSV e Markdown sono utilizzabili offline.", "",
        "Conservare snapshot, dataset annotato, run grezza, versioni, schede individuali e protocollo insieme al report. In tesi citare solo misure realmente eseguite e giudizi manuali completati; i test simulati dimostrano correttezza del software, non qualità editoriale del sistema."]
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    import altair as alt  # Già installato con Streamlit; il salvataggio non apre connessioni.
    values = [{k: s[k] for k in ("origin", "metric", "unit", "mean", "n")} for s in summary if s["mean"] is not None]
    chart = alt.Chart(alt.Data(values=values)).mark_bar().encode(
        x=alt.X("origin:N", title="Provenienza"), y=alt.Y("mean:Q", title="Media descrittiva"),
        color="origin:N", tooltip=["metric:N", "origin:N", "unit:N", "mean:Q", "n:Q"]
    ).properties(width=210, height=130).facet(facet="metric:N", columns=3).resolve_scale(y="independent")
    chart.save(str(out / "metrics.html"))
    chart.save(str(out / "metrics.vl.json"))
    return summary
