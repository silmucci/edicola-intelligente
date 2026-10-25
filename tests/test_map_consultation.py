"""Task 14.4: sola presentazione, corpus sintetico e nessuna API reale."""

import json
import re
from copy import deepcopy
from dataclasses import replace
from unittest.mock import patch

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from edicola.knowledge import KnowledgeResult, generate_knowledge
from edicola.knowledge_validation import map_dot, validate_map
from edicola.map_presentation import GROUPS, node_caption, node_captions
from edicola.rag import Source
from test_knowledge import COVERAGE, claim, setup_knowledge
from test_knowledge_exploration import installed_fixture, render_script
from test_pdf_viewer import archive


@pytest.mark.parametrize("original,expected", [
    ("Proroga del credito di imposta", "Proroga credito d’imposta"),
    ("Sospensione del pagamento dei mutui", "Sospensione pagamento mutui"),
    ("Modifica dei criteri del bando per il ristoro alle imprese di pesca", "Modifica criteri bando per il ristoro alle imprese di pesca"),
    ("Proroga del credito di imposta fino al 31 dicembre 2026 per il 20%", "Proroga credito d’imposta fino al 31 dicembre 2026 per il 20%"),
])
def test_nominal_captions_are_complete_and_preserve_scope_numbers_and_original(original, expected):
    node = {"label": original, "kind": "proposal"}
    assert node_caption(node) == expected
    assert "…" not in expected and "..." not in expected
    assert node["label"] == original


@pytest.mark.parametrize("kind,label", [
    ("organization", "Associazione delle imprese del territorio della provincia di Chieti"),
    ("person", "Maria della Valle"),
    ("place", "Comune di San Giovanni Teatino"),
    ("proposal", "Non è stata approvata la sospensione dei pagamenti dei mutui"),
    ("event", "La proposta potrebbe essere discussa il 21 ottobre 2026"),
    ("concept", "Una denominazione non riconosciuta viene conservata integralmente anche quando supera ampiamente cinquantadue caratteri"),
])
def test_names_modality_and_unrecognized_phrases_are_not_rewritten_or_cut(kind, label):
    assert node_caption({"kind": kind, "label": label}) == label


def test_caption_collisions_restore_original_denominations():
    nodes = [{"id": "N1", "kind": "measure", "label": "Proroga del contributo"},
             {"id": "N2", "kind": "measure", "label": "Proroga contributo"}]
    assert node_captions(nodes) == {n["id"]: n["label"] for n in nodes}


def test_clusters_contain_only_actual_types_and_do_not_create_links():
    nodes = [{"id": f"N{i}", "kind": kind, "label": f"Denominazione {i}", "source_ids": []}
             for i, kind in enumerate(GROUPS, 1)]
    data = {"nodes": nodes, "edges": []}
    original = deepcopy(data)
    dot = map_dot(data, grouping=True)
    for kind, (_, title, _, _) in GROUPS.items():
        assert f"subgraph cluster_{kind}" in dot and f'label="{title}"' in dot
    assert "->" not in dot and "style=invis" not in dot and data == original
    smaller = map_dot({"nodes": nodes[:2], "edges": []}, grouping=True)
    assert "cluster_measure" in smaller and "cluster_proposal" in smaller
    assert "cluster_person" not in smaller and "cluster_organization" not in smaller


def test_verified_edge_predicate_is_fully_readable_with_original_proof():
    text = "Il Comune assegna complessivamente quattrocentomila euro per la riqualificazione delle scuole."
    source = Source("S1", "synthetic", "a.pdf", 1, text, .1)
    predicate = "assegna complessivamente quattrocentomila euro per la"
    raw = {"nodes": [{"id": "N1", "kind": "organization", "label": claim("Comune", source)},
                     {"id": "N2", "kind": "event", "label": claim("riqualificazione delle scuole", source)}],
           "edges": [{"from_id": "N1", "to_id": "N2", "kind": "documented", "label": claim(predicate, source)}]}
    data, _ = validate_map(raw, [source])
    assert data["edges"] and len(predicate) > 52
    original = deepcopy(data)
    dot = map_dot(data)
    edge_label = re.search(r'"N1" -> "N2" \[label=("(?:[^"\\]|\\.)*")', dot).group(1)
    assert " ".join(json.loads(edge_label).split()) == predicate
    assert "style=solid, dir=forward" in dot and data == original


def pdf_map(context, prepared):
    chunks = next(d.chunks for d in prepared if d.filename == "a.pdf")
    sources = [Source(f"S{i}", c.id, "a.pdf", c.page, c.text, .1) for i, c in enumerate(chunks, 1)]
    raw = {"nodes": [{"id": f"N{i}", "kind": "concept", "label": claim(s.text, s)}
                     for i, s in enumerate(sources, 1)], "edges": []}
    data, diagnostics = validate_map(raw, sources)
    return KnowledgeResult("map", "Letture documentate", data, sources, COVERAGE, diagnostics)


def test_each_node_has_named_details_and_opens_its_own_original_pdf_page(archive):
    context, prepared = archive
    result = pdf_map(context, prepared)
    module, code = render_script(result, context)
    original_popover = st.popover
    with installed_fixture(module), patch("google.genai.Client") as api, patch("streamlit.popover", wraps=original_popover) as popover:
        app = AppTest.from_string(code).run()
        assert not app.exception and not app.dataframe
        labels = [call.args[0] for call in popover.call_args_list]
        assert "Prima pagina" in labels and "Seconda pagina" in labels
        assert all("knowledge_node" not in label and "N1" not in label for label in labels)
        assert {text.value for text in app.text} >= {s.text for s in result.sources}
        app.button(key="map_node_N2_pdf_S2").click().run()
        assert not app.exception and app.session_state["archive_page"] == 2
        assert app.session_state["archive_pdf"] == "a.pdf"
        app.run()
        api.assert_not_called()


@pytest.mark.parametrize("change", [{"page": 999}, {"filename": "../outside.pdf"}, {"chunk_id": "obsolete"}])
def test_node_sources_keep_existing_page_path_and_current_chunk_checks(archive, change):
    context, prepared = archive
    result = pdf_map(context, prepared)
    result.sources[0] = replace(result.sources[0], **change)
    module, code = render_script(result, context)
    with installed_fixture(module), patch("google.genai.Client") as api:
        app = AppTest.from_string(code).run()
    assert not app.exception
    assert not any(button.key == "map_node_N1_pdf_S1" for button in app.button)
    assert app.button(key="map_node_N2_pdf_S2")
    api.assert_not_called()


def test_display_uses_existing_cache_and_switches_views_without_regeneration(setup_knowledge):
    root, _, client, _, search = setup_knowledge
    result = generate_knowledge("map", "Trasporti", authorize_external=True, root=root, client=client)
    cache = next((root / "data/knowledge_cache").glob("*.json"))
    saved = cache.read_bytes()
    module, code = render_script(result)
    with installed_fixture(module):
        app = AppTest.from_string(code).run()
        assert not app.exception and app.get("graphviz_chart") and not app.dataframe
        app.segmented_control(key="knowledge_map_view").set_value("Elenco").run()
        assert app.dataframe and not app.get("graphviz_chart")
        app.segmented_control(key="knowledge_map_view").set_value("Grafo").run()
        assert app.get("graphviz_chart") and not app.dataframe
    assert generate_knowledge("map", "Trasporti", authorize_external=True, root=root, client=client).from_cache
    assert cache.read_bytes() == saved
    search.assert_called_once()
    client.models.generate_content.assert_called_once()
