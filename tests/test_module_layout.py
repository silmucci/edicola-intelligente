"""La nuova disposizione mantiene gli import storici dei moduli."""

from importlib.util import find_spec
from pathlib import Path

import edicola


def test_grouped_modules_preserve_flat_import_paths():
    root = Path(edicola.__file__).resolve().parent
    examples = {
        "ui": "account_ui",
        "podcast": "podcast",
        "chat": "chat_sessions",
        "retrieval": "rag",
        "pdf": "ingestion",
        "editorial": "briefing",
        "knowledge": "knowledge",
        "personalization": "profiles",
        "evaluation": "evaluation",
        "infrastructure": "settings",
        "maintenance": "indexing",
    }
    for group, name in examples.items():
        spec = find_spec(f"edicola.{name}")
        assert spec is not None
        assert Path(spec.origin).resolve() == root / group / f"{name}.py"


def test_indexing_root_still_points_to_repository():
    from edicola.indexing import ROOT
    assert ROOT == Path(edicola.__file__).resolve().parents[1]
