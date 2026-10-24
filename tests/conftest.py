"""I test precedenti esercitano esplicitamente la modalità di sviluppo locale."""

import pytest
from types import SimpleNamespace


@pytest.fixture(autouse=True)
def explicit_local_development_mode(monkeypatch):
    # Non leggere mai Secrets reali durante i test: login e modalità cloud locali
    # devono essere configurati esplicitamente dal singolo scenario simulato.
    monkeypatch.setattr("streamlit.secrets", {})
    # Il proxy nativo st.user può inizializzare anche il singleton Secrets;
    # nei test l'ospite è esplicito. Gli scenari OIDC sostituiscono questo mock.
    monkeypatch.setattr("streamlit.user", SimpleNamespace(is_logged_in=False))
    monkeypatch.setenv("EDICOLA_CLOUD_DEMO", "0")
    monkeypatch.setenv("GEMINI_API_KEY", "simulated-test-key-not-a-credential")
    monkeypatch.setenv("EDICOLA_PROFILE_MODE", "local_demo")
    # Anche la CI Linux può esercitare la modalità Windows con host simulato.
    monkeypatch.setattr("edicola.identity.development_host", lambda: True)
