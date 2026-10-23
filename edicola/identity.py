"""Identità native Streamlit: nessuna password, token o identità dal browser."""

import hashlib
import json
import platform
from dataclasses import dataclass
from collections.abc import Mapping

import streamlit as st

from edicola.settings import setting

GOOGLE_ISSUER = "https://accounts.google.com"
GOOGLE_METADATA = GOOGLE_ISSUER + "/.well-known/openid-configuration"
PRIVATE_PREFIXES = ("rag_", "personal_", "editorial_", "knowledge_", "podcast_", "account_", "home_personal_")


def secret_section(name):
    try:
        return dict(st.secrets.get(name, {}))
    except (FileNotFoundError, KeyError, TypeError, ValueError):
        return {}


def development_host():
    return platform.system() == "Windows"


def local_demo():
    # Il default è chiuso, anche su Windows. La demo locale è opt-in e vietata nel cloud.
    return (development_host() and setting("EDICOLA_PROFILE_MODE", "accounts") == "local_demo"
            and setting("EDICOLA_CLOUD_DEMO", "0") != "1")


def native_logged_in():
    try:
        return st.user.is_logged_in is True
    except (AttributeError, KeyError, RuntimeError):
        return False


def google_configured():
    auth = secret_section("auth")
    google = auth.get("google", {})
    cookie = auth.get("cookie_secret", "")
    if not isinstance(cookie, str) or len(cookie.strip()) < 32 or cookie.startswith("GENERARE_"):
        return False
    return (all(isinstance(auth.get(k), str) and auth[k].strip() for k in ("redirect_uri", "cookie_secret"))
            and isinstance(google, Mapping)
            and all(isinstance(google.get(k), str) and google[k].strip() for k in ("client_id", "client_secret"))
            and google.get("server_metadata_url") == GOOGLE_METADATA)


@dataclass(frozen=True)
class Identity:
    issuer: str
    subject: str

    def __post_init__(self):
        if self.issuer != GOOGLE_ISSUER or not isinstance(self.subject, str) or not self.subject.strip() or len(self.subject) > 255:
            raise ValueError("Identità OIDC non valida.")

    @property
    def owner_id(self):
        return hashlib.sha256(json.dumps([self.issuer, self.subject], separators=(",", ":")).encode()).hexdigest()


def current_identity():
    if not native_logged_in() or not google_configured():
        return None
    try:
        issuer, subject, audience = st.user.get("iss"), st.user.get("sub"), st.user.get("aud")
        client_id = secret_section("auth")["google"]["client_id"]
        if issuer not in {GOOGLE_ISSUER, "accounts.google.com"}:
            return None
        if not (audience == client_id or isinstance(audience, list) and client_id in audience):
            return None
        # Firma, nonce, issuer e audience sono verificati dall'OIDC nativo/Authlib.
        # L'app non interpreta JWT arbitrari e non identifica mai l'utente dall'email.
        return Identity(GOOGLE_ISSUER, subject)
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


def clear_private_state():
    for key in list(st.session_state):
        if key.startswith(PRIVATE_PREFIXES) or key == "profile_deleted_notice":
            del st.session_state[key]


def synchronize_identity():
    identity = current_identity() if not local_demo() else None
    owner = "local-demo" if local_demo() else identity.owner_id if identity else "guest"
    if st.session_state.get("_active_owner") != owner:
        clear_private_state()
        st.session_state["_active_owner"] = owner
    return identity


def login():
    if google_configured():
        clear_private_state()
        st.login("google")


def logout():
    if native_logged_in():
        clear_private_state()
        st.session_state.pop("_active_owner", None)
        st.logout()


def login_controls(key="account"):
    if native_logged_in():
        st.button("Logout", key=f"{key}_logout", on_click=logout)
    else:
        ready = google_configured()
        st.button("Accedi con Google", key=f"{key}_login", on_click=login, disabled=not ready)
        if not ready:
            st.caption("L’accesso personale non è ancora configurato. L’Archivio resta consultabile.")
