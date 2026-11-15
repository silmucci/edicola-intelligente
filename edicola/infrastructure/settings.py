"""Configurazione portabile: ambiente, Secrets Streamlit, .env locale."""

import os

from dotenv import dotenv_values


def setting(name, default="", *, root=None):
    value = os.environ.get(name)
    if value is not None:
        return value.strip()
    # La lettura non crea client API né stampa il contenuto dei Secrets.
    import streamlit as st
    try:
        value = st.secrets.get(name)
    except (FileNotFoundError, KeyError):
        value = None
    if value is not None:
        return str(value).strip()
    if root is not None:
        return str(dotenv_values(root / ".env").get(name) or default).strip()
    return default
