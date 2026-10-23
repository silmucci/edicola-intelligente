"""Adattatore TTS esistente: file effimeri isolati, PostgreSQL resta autorevole."""

import shutil
import sqlite3

from edicola.personal_store import PersonalStoreError
from edicola.personalization import write_personal_cache


def audio_scope(root, store):
    owner = store.assert_owner()
    # Indipendente dalla versione dello snapshot: cancellare copre gli audio
    # dello stesso proprietario anche dopo un aggiornamento dell'archivio cloud.
    if root.parent.name == ".cloud-runtime":
        root = root.parent.parent
    base = root / ".private-runtime"
    scope = base / owner
    if (base.is_symlink() or scope.is_symlink() or not scope.resolve().is_relative_to(root.resolve())
            or scope.resolve().parent != base.resolve()):
        raise PersonalStoreError("Percorso degli audio personali non consentito.")
    return scope


def prepare_audio(root, store, key):
    result = store.get_briefing(key)  # Sempre dal proprietario corrente, mai dalla cache di un altro utente.
    if result is None:
        raise PersonalStoreError("Briefing personale non disponibile.")
    scope = audio_scope(root, store)
    try:
        write_personal_cache(scope / "data/editorial.sqlite3", key, result)
    except (OSError, sqlite3.Error):
        raise PersonalStoreError("La copia temporanea per l’audio non è disponibile. Il briefing resta conservato su PostgreSQL.") from None
    return scope


def remove_audio(root, store):
    scope = audio_scope(root, store)
    if scope.exists():
        shutil.rmtree(scope)
