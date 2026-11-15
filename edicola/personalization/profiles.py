"""Profili dimostrativi locali: preferenze esplicite, nessuna autenticazione."""

import hashlib
import json
import shutil
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Profile:
    user_id: str = "demo"
    interests: list[str] = field(default_factory=list)
    minutes: int = 5
    format: str = "testo"
    feedback: dict[str, int] = field(default_factory=dict)
    saved: dict[str, dict] = field(default_factory=dict)


def validate(profile):
    if not isinstance(profile.user_id, str) or not 1 <= len(profile.user_id) <= 80:
        raise ValueError("Identificativo demo non valido.")
    if type(profile.minutes) is not int or profile.minutes not in (2, 5, 10) or profile.format not in ("testo", "visuale", "audio"):
        raise ValueError("Scegliere 2, 5 o 10 minuti e un formato disponibile.")
    if (len(profile.interests) > 10 or any(not isinstance(t, str) or not t.strip() or len(t) > 100 for t in profile.interests)
            or any(t not in profile.interests or type(v) is not int or v not in (-1, 1) for t, v in profile.feedback.items())):
        raise ValueError("Inserire al massimo dieci interessi di 100 caratteri; feedback solo sugli interessi dichiarati.")


def load_profile(root: Path, user_id="demo") -> Profile:
    path = root / "data/profiles.sqlite3"
    if not path.exists():
        return Profile(user_id=user_id)
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        row = connection.execute("SELECT data FROM profiles WHERE user_id=?", (user_id,)).fetchone()
    return Profile(**json.loads(row[0])) if row else Profile(user_id=user_id)


def save_profile(root: Path, profile: Profile):
    validate(profile)
    path = root / "data/profiles.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("PRAGMA secure_delete=ON")
        connection.execute("CREATE TABLE IF NOT EXISTS profiles(user_id TEXT PRIMARY KEY, data TEXT NOT NULL)")
        connection.execute("INSERT OR REPLACE INTO profiles VALUES (?,?)",
                           (profile.user_id, json.dumps(asdict(profile), ensure_ascii=False)))


def set_feedback(root, user_id, topic, value):
    profile = load_profile(root, user_id)
    if value == 0:
        profile.feedback.pop(topic, None)
    else:
        profile.feedback[topic] = value
    save_profile(root, profile)


def save_passage(root, user_id, chunk):
    profile = load_profile(root, user_id)
    profile.saved[chunk.id] = {"text": chunk.text, "metadata": chunk.metadata}
    save_profile(root, profile)


def remove_passage(root, user_id, chunk_id):
    profile = load_profile(root, user_id)
    profile.saved.pop(chunk_id, None)
    save_profile(root, profile)


def personal_root(root: Path, user_id: str) -> Path:
    # L'identificativo non diventa mai un percorso fornito dall'utente.
    return root / "data/personalized" / hashlib.sha256(user_id.encode()).hexdigest()


def delete_profile(root: Path, user_id="demo"):
    scope = personal_root(root, user_id)
    base = (root / "data/personalized").resolve()
    if scope.is_symlink() or scope.resolve().parent != base or not base.is_relative_to(root.resolve()):
        raise ValueError("Percorso dei dati personali non valido.")
    if scope.exists():
        shutil.rmtree(scope)
    path = root / "data/profiles.sqlite3"
    if path.exists():
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("PRAGMA secure_delete=ON")
            connection.execute("DELETE FROM profiles WHERE user_id=?", (user_id,))
