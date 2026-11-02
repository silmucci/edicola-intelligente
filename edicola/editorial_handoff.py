"""Passaggio dalla chat a una bozza: mai una richiesta API pendente."""

import streamlit as st
from edicola.product_navigation import cancel_navigation_action, destination

TARGETS = {"Dossier": ("dossier", "editorial_topic"),
           "Rassegna": ("briefing", "editorial_review_keyword"),
           "Timeline": ("timeline", "knowledge_topic_timeline"),
           "Mappa": ("map", "knowledge_topic_map"),
           "Infografica": ("briefing", "editorial_infographic_topic"),
           "Podcast": ("podcast", "podcast_topic")}


def open_draft(label, topic):
    if label not in TARGETS or not isinstance(topic, str):
        return
    identifier, key = TARGETS[label]
    cancel_navigation_action()
    st.session_state[key] = " ".join(topic.split())[:500]
    if identifier == "briefing":
        st.session_state["editorial_workspace"] = "Infografica" if label == "Infografica" else "Briefing"
    st.session_state["nav_section"] = destination(identifier)


def render_handoff(topic):
    st.caption("Prosegui questo argomento in un prodotto editoriale. Si apre una bozza: conferma il tema prima di generare. Per il podcast scegli un prodotto già disponibile.")
    with st.container(horizontal=True):
        for label in TARGETS:
            st.button("Prepara " + label.lower(), key="editorial_handoff_" + label,
                      on_click=open_draft, args=(label, topic))
