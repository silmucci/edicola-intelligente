"""Esportazione riservata dei prodotti reali per la valutazione offline.

Non esegue generazione, embedding o chiamate a Groq. La password resta
esclusivamente nei Secrets dell'istanza, mai nell'URL o nel file esportato.
"""
import hmac
import json
import sqlite3
from pathlib import Path

from edicola.settings import setting


def export_authorized(configured: str, supplied: str) -> bool:
    """In assenza di un segreto robusto l'accesso resta disabilitato."""
    return (isinstance(configured, str) and len(configured) >= 16
            and isinstance(supplied, str)
            and hmac.compare_digest(configured, supplied))


def export_bytes(root, *, limit_per_kind: int) -> bytes:
    """Legge solo le cache dell'archivio runtime corrente e ne valida le fonti."""
    from edicola.evaluation_products import collect_product_manifest, validate_manifest

    manifest = collect_product_manifest(root, limit_per_kind=limit_per_kind)
    if not manifest["products"]:
        raise ValueError("Non sono disponibili prodotti salvati con fonti ancora indicizzate.")
    validate_manifest(manifest)
    return (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")



def export_diagnostics(root) -> dict:
    """Soli conteggi per aiutare l'amministratore, senza testi o credenziali."""
    data = Path(root) / "data"
    state = {
        "archive": (data / "archive.sqlite3").is_file(),
        "chroma": (data / "chroma").is_dir(),
        "briefing_cache": 0,
        "podcast_scripts": 0,
        "knowledge_files": 0,
    }
    db = data / "editorial.sqlite3"
    if db.is_file():
        try:
            with sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True) as conn:
                state["briefing_cache"] = conn.execute(
                    "SELECT COUNT(*) FROM products").fetchone()[0]
        except sqlite3.Error:
            state["briefing_cache"] = -1
    state["podcast_scripts"] = len(list(
        (data / "podcast_cache/standalone/scripts").glob("*.json")))
    state["knowledge_files"] = len(list((data / "knowledge_cache").glob("*.json")))
    return state

def render_export(root):
    """Pagina separata: accessibile soltanto tramite URL esplicito e password."""
    import streamlit as st

    st.title("Esportazione per la valutazione")
    secret = setting("EDICOLA_EVAL_EXPORT_PASSWORD", root=root)
    if not isinstance(secret, str) or len(secret) < 16:
        st.error("Esportazione amministrativa non configurata.")
        return

    password = st.text_input("Password di esportazione", type="password", key="_eval_export_password")
    if not export_authorized(secret, password):
        if password:
            st.error("Password non valida.")
        return

    st.caption("Solo prodotti già generati e relative fonti. Nessuna chiamata AI.")
    amount = st.number_input("Prodotti massimi per tipologia", min_value=1, max_value=25,
                             value=5, step=1, key="_eval_export_limit")
    if st.button("Prepara file JSON", type="primary"):
        try:
            payload = export_bytes(root, limit_per_kind=int(amount))
        except (OSError, RuntimeError, ValueError, KeyError, TypeError, sqlite3.Error):
            # Nessun dettaglio del corpus o delle credenziali nei messaggi pubblici.
            st.session_state.pop("_eval_export_payload", None)
            st.warning("Nessun prodotto esportabile con le fonti correnti.")
            state = export_diagnostics(root)
            if not state["archive"] or not state["chroma"]:
                st.info("Archivio o indice vettoriale non disponibile nel runtime attuale.")
            elif not any(state[k] > 0 for k in ("briefing_cache", "podcast_scripts", "knowledge_files")):
                st.info("Non ci sono prodotti salvati in questa istanza: genera prima un prodotto nell'app, poi torna qui.")
            else:
                st.info("Esistono cache, ma nessun prodotto è risultato esportabile: le fonti potrebbero non corrispondere all'indice corrente.")
            with st.expander("Diagnostica esportazione"):
                st.write({
                    "Archivio presente": state["archive"],
                    "Indice presente": state["chroma"],
                    "Prodotti nella cache editoriale": state["briefing_cache"],
                    "Copioni podcast": state["podcast_scripts"],
                    "File timeline/mappe": state["knowledge_files"],
                })
        else:
            st.session_state["_eval_export_payload"] = payload

    payload = st.session_state.get("_eval_export_payload")
    if payload:
        count = len(json.loads(payload)["products"])
        st.success(f"Prodotti pronti: {count}.")
        st.warning("Il file contiene testi e citazioni dei quotidiani: conservalo privatamente e non caricarlo su GitHub.")
        st.download_button("Scarica prodotti_valutazione.json", data=payload,
                           file_name="prodotti_valutazione.json", mime="application/json")
