"""Controllo per singola richiesta SDK; i comandi CLI mantengono il loro opt-in."""

from contextlib import contextmanager
from contextvars import ContextVar

_permission = ContextVar("edicola_external_permission", default=None)


class PermissionDenied(RuntimeError):
    pass


@contextmanager
def permission_scope(check, purpose="text"):
    token = _permission.set((check, purpose))
    try:
        require_permission()
        yield
    finally:
        _permission.reset(token)


def require_permission(expected=None):
    scope = _permission.get()
    if scope is not None:
        check, purpose = scope
        compatible = expected is None or expected == purpose or expected == "text" and purpose == "personal_text"
        if not compatible or not check():
            raise PermissionDenied("Autorizzazione assente o revocata. Nessun nuovo contenuto è stato inviato.")
    else:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        if get_script_run_ctx(suppress_warning=True) is not None:
            raise PermissionDenied("Questa operazione richiede un’autorizzazione dalle impostazioni privacy.")
