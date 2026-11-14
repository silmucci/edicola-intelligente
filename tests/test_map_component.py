"""La resa interattiva distingue archi fattuali e associazioni editoriali."""

from edicola.map_component import DIRECTIONAL_EDGE_KINDS, is_directional_edge


def test_only_documented_actions_and_source_mentions_have_arrowheads():
    assert DIRECTIONAL_EDGE_KINDS == frozenset({"documented", "mention"})
    assert is_directional_edge({"kind": "documented"})
    assert is_directional_edge({"kind": "mention"})
    assert not is_directional_edge({"kind": "contextual"})
    assert not is_directional_edge({"kind": "thematic"})


def test_map_uses_full_page_height_without_nested_scroll_or_fixed_canvas_width():
    from edicola.map_component import CSS, JS
    assert "overflow:visible" in CSS and "max-height:75vh" not in CSS
    assert "overflow:auto" not in CSS
    assert "ResizeObserver" in JS
    assert "canvas.style.height=height+'px'" in JS
    assert "canvas.style.width='100%'" in JS
    assert "setTriggerValue('selected',index)" in JS
