"""La resa interattiva distingue archi fattuali e associazioni editoriali."""

from edicola.map_component import DIRECTIONAL_EDGE_KINDS, is_directional_edge


def test_only_documented_actions_and_source_mentions_have_arrowheads():
    assert DIRECTIONAL_EDGE_KINDS == frozenset({"documented", "mention"})
    assert is_directional_edge({"kind": "documented"})
    assert is_directional_edge({"kind": "mention"})
    assert not is_directional_edge({"kind": "contextual"})
    assert not is_directional_edge({"kind": "thematic"})
