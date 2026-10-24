"""Adattatore AppTest per i soli eventi dei componenti v2."""

import streamlit as st


def cards_adapter(**kwargs):
    key = kwargs["key"]
    def select(index):
        st.session_state[key] = {"selected": index}
        kwargs["on_selected_change"]()
    for index, item in enumerate(kwargs["data"]["items"]):
        st.button(item["title"], key=f"{key}_test_{index}", on_click=select, args=(index,))
