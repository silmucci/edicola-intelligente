"""Controlli offline dell'esportazione protetta, senza chiamate esterne."""
import json
from unittest.mock import patch

import pytest

from edicola.evaluation_export_ui import export_authorized, export_bytes


def test_export_requires_configured_long_password():
    assert not export_authorized("", "")
    assert not export_authorized("breve", "breve")
    assert not export_authorized("x" * 16, "errata")
    assert export_authorized("x" * 16, "x" * 16)


def test_export_reuses_only_valid_manifest(tmp_path):
    source = {"source_id": "S1", "pdf": "testata.pdf", "page": 1, "text": "Testo della fonte."}
    product = {"kind": "briefing", "item_id": "real-cache", "origin": "real",
               "content": "Titolo e testo", "sources": [source]}
    manifest = {"schema_version": 1, "products": [product]}
    with patch("edicola.evaluation_products.collect_product_manifest", return_value=manifest) as collector:
        result = json.loads(export_bytes(tmp_path, limit_per_kind=1))
    collector.assert_called_once_with(tmp_path, limit_per_kind=1)
    assert result == manifest


def test_export_does_not_fabricate_products(tmp_path):
    with patch("edicola.evaluation_products.collect_product_manifest",
               return_value={"schema_version": 1, "products": []}):
        with pytest.raises(ValueError, match="Non sono disponibili"):
            export_bytes(tmp_path, limit_per_kind=1)
