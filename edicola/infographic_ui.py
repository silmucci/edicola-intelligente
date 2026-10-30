"""Prodotto infografico autonomo, con generazione locale esplicita."""

import streamlit as st

from edicola.editorial_selection import read_catalog
from edicola.infographic import build_infographic
from edicola.pdf_viewer import source_button


def render_infographic(root, context):
    st.subheader("Infografica editoriale")
    st.caption("Un quadro di punti documentati: estratti letterali, senza stime, percentuali o relazioni ricostruite. Elaborazione locale, nessun invio a Gemini.")
    topic = st.text_input("Tema dell’infografica", key="editorial_infographic_topic", max_chars=500)
    if st.button("Crea infografica", key="editorial_infographic_submit"):
        st.session_state.pop("editorial_infographic_result", None)
        try:
            st.session_state["editorial_infographic_result"] = build_infographic(read_catalog(root), topic)
        except ValueError as exc:
            st.warning(str(exc))
        except Exception:
            st.error("Archivio indicizzato non disponibile. Nessun contenuto è stato generato.")
    result = st.session_state.get("editorial_infographic_result")
    if result is None:
        return
    st.text(result.topic)
    from edicola.corpus_cache import render_history_notice
    render_history_notice(result.coverage, context)
    if topic.strip() != result.topic:
        st.caption("Risultato del tema precedente. Premi Crea infografica per aggiornarlo.")
    if result.coverage.get("partial"):
        st.warning("Copertura parziale dell’archivio indicizzato.")
    if not result.blocks:
        st.info("Nessuna frase completa adatta a un quadro documentato per questo tema.")
        return
    st.caption(f"{len(result.blocks)} punti selezionati · ordine delle fonti, non cronologico · non è un confronto quantitativo o un elenco esaustivo.")
    columns = st.columns(2)
    for index, block in enumerate(result.blocks):
        with columns[index % 2], st.container(border=True):
            st.caption(f"Punto documentato {index + 1}")
            st.text(block["quote"])
    st.caption("Fonti originali")
    pages = set()
    for index, block in enumerate(result.blocks):
        page = (block["filename"], block["page"])
        if page in pages:
            continue
        pages.add(page)
        points = ", ".join(str(i + 1) for i, item in enumerate(result.blocks) if (item["filename"], item["page"]) == page)
        source_button(*page, context=context, chunk_id=block["chunk_id"], key=f"infographic_pdf_{index}",
                      label=f"Punti {points} · pagina {block['page']}")
