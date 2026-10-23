"""Registro persistente: un risultato per contenuto, indipendente dal nome."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def open_registry(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30)
    try:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS extractions (
                sha256 TEXT PRIMARY KEY,
                result_json TEXT NOT NULL,
                extracted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS sources (
                filename TEXT PRIMARY KEY,
                sha256 TEXT NOT NULL,
                last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS chunk_sets (
                sha256 TEXT PRIMARY KEY,
                config_signature TEXT NOT NULL,
                skipped_pages_json TEXT NOT NULL,
                processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS chunks (
                id TEXT PRIMARY KEY,
                pdf_sha256 TEXT NOT NULL,
                page INTEGER NOT NULL,
                position INTEGER NOT NULL,
                start INTEGER NOT NULL,
                end INTEGER NOT NULL,
                text TEXT NOT NULL,
                UNIQUE(pdf_sha256, position)
            )"""
        )
        connection.commit()
        yield connection
    except sqlite3.Error as exc:
        raise RuntimeError(f"Errore nel registro SQLite: {exc}") from exc
    finally:
        connection.close()


def load_result(connection, digest: str) -> dict | None:
    row = connection.execute(
        "SELECT result_json FROM extractions WHERE sha256 = ?", (digest,)
    ).fetchone()
    return json.loads(row[0]) if row else None


def save_result(connection, digest: str, result: dict) -> None:
    with connection:
        connection.execute(
            "INSERT OR IGNORE INTO extractions (sha256, result_json) VALUES (?, ?)",
            (digest, json.dumps(result, ensure_ascii=False)),
        )


def record_source(connection, filename: str, digest: str) -> None:
    with connection:
        connection.execute(
            """INSERT INTO sources (filename, sha256) VALUES (?, ?)
            ON CONFLICT(filename) DO UPDATE SET
                sha256 = excluded.sha256, last_seen_at = CURRENT_TIMESTAMP""",
            (filename, digest),
        )


def load_chunks(connection, digest: str, signature: str) -> dict | None:
    row = connection.execute(
        "SELECT skipped_pages_json FROM chunk_sets WHERE sha256 = ? AND config_signature = ?",
        (digest, signature),
    ).fetchone()
    if row is None:
        return None
    rows = connection.execute(
        """SELECT id, page, position, start, end, text FROM chunks
        WHERE pdf_sha256 = ? ORDER BY position""", (digest,)
    ).fetchall()
    keys = ("id", "page", "position", "start", "end", "text")
    return {"chunks": [dict(zip(keys, item)) for item in rows],
            "skipped_pages": json.loads(row[0])}


def save_chunks(connection, digest: str, signature: str, result: dict) -> None:
    with connection:
        connection.execute("DELETE FROM chunks WHERE pdf_sha256 = ?", (digest,))
        connection.executemany(
            """INSERT INTO chunks (id, pdf_sha256, page, position, start, end, text)
            VALUES (:id, :pdf_sha256, :page, :position, :start, :end, :text)""",
            [{**chunk, "pdf_sha256": digest} for chunk in result["chunks"]],
        )
        connection.execute(
            """INSERT INTO chunk_sets (sha256, config_signature, skipped_pages_json)
            VALUES (?, ?, ?) ON CONFLICT(sha256) DO UPDATE SET
                config_signature = excluded.config_signature,
                skipped_pages_json = excluded.skipped_pages_json,
                processed_at = CURRENT_TIMESTAMP""",
            (digest, signature, json.dumps(result["skipped_pages"], ensure_ascii=False)),
        )
