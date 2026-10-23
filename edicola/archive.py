"""Snapshot in sola lettura dei chunk attuali; nessuna estrazione o pulizia."""

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from edicola.embeddings import document_prompt


@dataclass(frozen=True)
class IndexChunk:
    id: str
    text: str
    metadata: dict

    @property
    def prompt(self):
        # Titolo stabile anche dopo una rinomina o l'aggiunta di copie identiche.
        return document_prompt(
            f"Quotidiano {self.metadata['pdf_sha256']} - pagina {self.metadata['page']}", self.text
        )

    @property
    def fingerprint(self):
        return hashlib.sha256(self.prompt.encode("utf-8")).hexdigest()

    @property
    def chroma_metadata(self):
        return {**self.metadata, "input_sha256": self.fingerprint}


def read_active_chunks(registry: Path, incoming: Path) -> tuple[list[IndexChunk], list[str]]:
    """Esclude hash storici e file rimossi. Verifica SHA senza aprire il PDF con pypdf."""
    if not registry.is_file() or not incoming.is_dir():
        raise RuntimeError("Archivio o cartella incoming assente: eseguire prima l'app Streamlit.")
    connection = sqlite3.connect(registry.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            connection.execute("BEGIN")
            sources = dict(connection.execute("SELECT filename, sha256 FROM sources"))
            aliases = {}
            warnings = []
            for path in sorted(incoming.iterdir(), key=lambda item: item.name):
                if not path.is_file() or path.suffix.lower() != ".pdf":
                    continue
                with path.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                if sources.get(path.name) != digest:
                    warnings.append(f"{path.name}: file nuovo/modificato; aggiornare prima tramite Streamlit.")
                    continue
                aliases.setdefault(digest, []).append(path.name)
            chunks = []
            for digest, names in sorted(aliases.items()):
                config = connection.execute(
                    "SELECT config_signature FROM chunk_sets WHERE sha256 = ?", (digest,)
                ).fetchone()
                if config is None:
                    warnings.append(f"{names[0]}: preprocessing non disponibile; aprire Streamlit.")
                    continue
                extraction = connection.execute(
                    "SELECT result_json FROM extractions WHERE sha256 = ?", (digest,)
                ).fetchone()
                total_pages = json.loads(extraction[0])["total_pages"] if extraction else 0
                for row in connection.execute(
                    "SELECT * FROM chunks WHERE pdf_sha256 = ? ORDER BY position", (digest,)
                ):
                    chunks.append(IndexChunk(row["id"], row["text"], {
                        "filename": names[0], "filenames_json": json.dumps(names, ensure_ascii=False),
                        "pdf_sha256": digest, "page": row["page"], "total_pages": total_pages,
                        "position": row["position"], "start": row["start"], "end": row["end"],
                        "chunk_config": config[0],
                    }))
            return chunks, warnings
    except sqlite3.Error:
        raise RuntimeError("SQLite non leggibile o schema incompleto: verificare i Task 1 e 2.") from None
    finally:
        connection.close()
