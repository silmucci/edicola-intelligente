"""Lock di processo e diario locale dei batch; mai chiavi o testo dei quotidiani."""

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


def private_directory(root):
    root = Path(root).resolve()
    path = root / "data/corpus_updates"
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ValueError("Area di manutenzione non consentita.")
    path.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def maintenance_lock(root):
    """Il sistema operativo libera il lock anche dopo kill o crash."""
    path = private_directory(root) / "manager.lock"
    if path.is_symlink():
        raise ValueError("Lock non consentito.")
    with path.open("a+b") as stream:
        stream.seek(0, 2)
        if not stream.tell():
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError("Un’altra operazione di manutenzione è già in corso.") from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class MaintenanceStore:
    def __init__(self, root):
        path = private_directory(root) / "manager.sqlite3"
        if path.is_symlink():
            raise ValueError("Diario non consentito.")
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS batches (
                id TEXT PRIMARY KEY, created REAL NOT NULL, updated REAL NOT NULL,
                selection_version TEXT NOT NULL, planned INTEGER NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
                reused INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL,
                error_code TEXT NOT NULL DEFAULT '', next_allowed REAL NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS staged_vectors (
                chunk_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, vector_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS batch_items (
                batch_id TEXT NOT NULL, chunk_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
                done INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(batch_id,chunk_id));
        """)

    def close(self):
        self.db.close()

    def recover(self, indexed=None):
        # Chiamato solo dopo aver ottenuto il lock esclusivo: nessun batch vivo.
        with self.db:
            if indexed is not None:
                rows = self.db.execute("SELECT batch_id,chunk_id,fingerprint FROM batch_items JOIN batches ON batches.id=batch_id WHERE batches.status='running'").fetchall()
                for row in rows:
                    if indexed.get(row["chunk_id"]) == row["fingerprint"]:
                        self.db.execute("UPDATE batch_items SET done=1 WHERE batch_id=? AND chunk_id=?", (row["batch_id"], row["chunk_id"]))
                self.db.execute("UPDATE batches SET completed=MAX(completed,(SELECT COUNT(*) FROM batch_items WHERE batch_id=batches.id AND done=1)) WHERE status='running'")
            self.db.execute("UPDATE batches SET status='interrupted', updated=? WHERE status='running'", (time.time(),))

    def latest(self):
        row = self.db.execute("SELECT * FROM batches ORDER BY created DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    def start(self, version, planned, chunks=()):
        identity, now = uuid4().hex, time.time()
        with self.db:
            self.db.execute("INSERT INTO batches(id,created,updated,selection_version,planned,status) VALUES (?,?,?,?,?,'running')",
                            (identity, now, now, version, planned))
            self.db.executemany("INSERT INTO batch_items(batch_id,chunk_id,fingerprint) VALUES (?,?,?)",
                                [(identity, chunk.id, chunk.fingerprint) for chunk in chunks])
        return identity

    def attempt(self, identity):
        with self.db:
            row = self.db.execute("SELECT attempts,planned FROM batches WHERE id=?", (identity,)).fetchone()
            if row is None or row["attempts"] >= row["planned"] * 3:
                raise RuntimeError("Budget dei tentativi esaurito.")
            self.db.execute("UPDATE batches SET attempts=attempts+1, updated=? WHERE id=?", (time.time(), identity))

    def completed(self, identity, reused, chunk_id):
        with self.db:
            self.db.execute("UPDATE batch_items SET done=1 WHERE batch_id=? AND chunk_id=?", (identity, chunk_id))
            self.db.execute("UPDATE batches SET completed=completed+1, reused=reused+?, updated=? WHERE id=?",
                            (int(reused), time.time(), identity))

    def finish(self, identity, status, code="", cooldown=0):
        now = time.time()
        with self.db:
            self.db.execute("UPDATE batches SET status=?, error_code=?, next_allowed=?, updated=? WHERE id=?",
                            (status, code, now + cooldown if cooldown else 0, now, identity))

    def load_vector(self, chunk):
        row = self.db.execute("SELECT vector_json FROM staged_vectors WHERE chunk_id=? AND fingerprint=?",
                              (chunk.id, vector_identity(chunk))).fetchone()
        return json.loads(row[0]) if row else None

    def stage(self, chunk, vector):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO staged_vectors VALUES (?,?,?)",
                            (chunk.id, vector_identity(chunk), json.dumps(vector)))

    def unstage(self, chunk):
        with self.db:
            self.db.execute("DELETE FROM staged_vectors WHERE chunk_id=?", (chunk.id,))


def vector_identity(chunk):
    import hashlib
    from edicola.embeddings import MODEL, DIMENSIONS, FORMAT_VERSION
    return hashlib.sha256(json.dumps([MODEL, DIMENSIONS, FORMAT_VERSION, chunk.fingerprint]).encode()).hexdigest()


def recent_batches(root, limit=10):
    path = Path(root) / "data/corpus_updates/manager.sqlite3"
    if not path.is_file():
        return []
    if path.is_symlink() or not path.resolve().is_relative_to(Path(root).resolve()):
        raise ValueError("Diario non consentito.")
    from contextlib import closing
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute("SELECT * FROM batches ORDER BY created DESC LIMIT ?", (limit,))]
