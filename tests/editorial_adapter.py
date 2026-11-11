"""Adattatore offline per verificare interazioni dei componenti Streamlit v2."""

import streamlit as st


def cards_adapter(**kwargs):
    key = kwargs["key"]

    def select(identifier):
        st.session_state[key] = {"selected": identifier}
        kwargs["on_selected_change"]()

    for index, item in enumerate(kwargs["data"]["items"]):
        # L'interfaccia reale comunica un ID stabile, non l'indice della card.
        value = item["id"] if kwargs["data"]["mode"] == "products" else index
        st.button(item["title"], key=f"{key}_test_{index}",
                  on_click=select, args=(value,))


def navigate_to(app, section):
    """Navigazione programmatica nei test di pagina; le card hanno test propri."""
    app.session_state["nav_section"] = section
    return app.run()
