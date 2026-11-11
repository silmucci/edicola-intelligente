"""Navigazione e temi Podcast: solo documenti sintetici e SDK simulati."""
import json
from unittest.mock import Mock, patch

import pytest
from streamlit.testing.v1 import AppTest

from edicola import podcast_draft as drafts
from edicola.product_navigation import PRODUCTS, active_product, destination
from edicola.podcast_text import PodcastError
from edicola.standalone_podcast import PodcastAudioError, list_episodes, draft_context
from test_standalone_podcast import standalone, generate
from test_pdf_viewer import archive
from test_podcast_ui import ui_script, grant


@pytest.mark.parametrize('previous,expected', [(None, 'In edicola'), ('Archivio PDF', 'In edicola'),
    ('Rassegna stampa', 'Per te'), ('Timeline', 'Esplora')])
def test_start_and_previous_sessions(previous, expected):
    with patch('edicola.editorial_components.cards_component') as cards:
        app = AppTest.from_string('from edicola.product_navigation import render_navigation\nrender_navigation()')
        if previous:
            app.session_state['nav_section'] = previous
        app.run()
        assert not app.exception and app.session_state['nav_section'] == expected
        items = cards.call_args.kwargs['data']['items']
        assert [p['id'] for p in items] == ['archive', 'for_you', 'chat', 'briefing', 'podcast', 'explore']
        assert sum(p['active'] for p in items) == 1
        assert all(p['icon'] and p['description'] for p in items)
    assert destination('Archivio PDF') == 'In edicola'
    assert active_product('Archivio PDF')['id'] == 'archive'


@pytest.mark.parametrize('choice', ['archive', 'home', 'chat', 'briefing', 'timeline', 'map', 'podcast', 0, 1])
def test_card_callbacks_use_stable_ids_and_accept_old_indices(choice):
    with patch('edicola.editorial_components.cards_component') as cards:
        app = AppTest.from_string('from edicola.editorial_components import render_products\nrender_products()').run()
        app.session_state['home_products'] = {'selected': choice}
        # Callback executed inside Streamlit's session, as with a component trigger.
        callback = cards.call_args.kwargs['on_selected_change']
        with patch('edicola.editorial_components.open_product_id') as opened:
            with patch('edicola.editorial_components.st.session_state', {'home_products': {'selected': choice}}):
                callback()
            opened.assert_called_once_with(('home', 'archive')[choice] if type(choice) is int else choice)


def test_all_six_cards_navigate_and_preserve_drafts_without_ai():
    def adapter(**kwargs):
        import streamlit as st
        def click(identifier):
            st.session_state['home_products'] = {'selected': identifier}
            kwargs['on_selected_change']()
        for product in kwargs['data']['items']:
            st.button(product['title'], key='card_'+product['id'], on_click=click, args=(product['id'],))
    with patch('edicola.editorial_components.cards_component', side_effect=adapter), \
         patch('google.genai.Client', side_effect=AssertionError('Nessuna API')):
        app = AppTest.from_string('from edicola.product_navigation import render_navigation\nrender_navigation()').run()
        app.session_state['podcast_topic'] = 'Una bozza da conservare'
        app.session_state['knowledge_result_map'] = 'Risultato esistente'
        for product in (p for p in PRODUCTS if p["id"] != "profile"):
            app.button(key='card_'+product['id']).click().run()
            assert not app.exception and app.session_state['nav_section'] == product['section']
            assert app.session_state['podcast_topic'] == 'Una bozza da conservare'
            assert app.session_state['knowledge_result_map'] == 'Risultato esistente'


def test_legacy_rassegna_opens_full_news_not_pdf_gallery(standalone):
    from types import ModuleType, SimpleNamespace
    fixture = ModuleType("edicola.rassegna_fixture")
    fixture.root = standalone.root
    fixture.context = SimpleNamespace(root=standalone.root, documents=[])
    code = """from edicola.rassegna_fixture import root, context
from edicola.experience_ui import render_home
render_home(root, context)
"""
    with patch.dict("sys.modules", {"edicola.rassegna_fixture": fixture}), patch(
        "edicola.experience_ui.identity.synchronize_identity"), patch(
        "edicola.experience_ui.read_catalog", return_value=standalone.catalog), patch(
        "edicola.press_review_ui.render_press_review") as review, patch(
        "edicola.archive_ui.gallery_component") as gallery:
        app = AppTest.from_string(code).run()
        assert not app.exception
        assert app.session_state["for_you_mode"] == "Tutte le notizie"
        review.assert_called_once()
        gallery.assert_not_called()


def test_covers_are_sorted_and_open_matching_pdf(archive):
    from edicola.archive_ui import latest_first, edition_metadata, render_gallery
    context, _ = archive
    (context.root/'data/editions.json').write_text(json.dumps({'a.pdf': {'publication': 'Uno', 'date': '2026-10-01'},
        'b.pdf': {'publication': 'Due', 'date': '2026-11-01'}}), encoding='utf-8')
    documents = latest_first(context.root, context.documents)
    assert [d.filename for d in documents] == ['b.pdf', 'a.pdf']
    with patch('edicola.archive_ui.gallery_component') as gallery, patch('edicola.archive_ui.section_intro'), \
         patch('edicola.archive_ui.cover_thumbnail', return_value=b'png'):
        render_gallery(context, edition_metadata(context.root, documents), documents=documents)
        data = gallery.call_args.kwargs['data']
        assert data['layout'] == 'grid' and data['editions'][0]['title'] == 'Due'
        with patch('edicola.archive_ui.st.session_state', {'archive_gallery': {'open_edition': 0}}), \
             patch('edicola.archive_ui.open_reference') as opened:
            gallery.call_args.kwargs['on_open_edition_change']()
            opened.assert_called_once_with(context, 'b.pdf', 1)


def test_general_has_no_query_embedding(standalone):
    with patch('edicola.podcast_draft.semantic_search') as search:
        generate(standalone, topic='   ')
        search.assert_not_called()


def test_topics_semantic_selection_cache_and_no_irrelevant_fill(standalone):
    first, second = standalone.catalog.chunks
    def hits(query, **kwargs):
        chunk = first if query == 'istruzione' else second
        assert kwargs['corpus_wide'] and kwargs['allowed_ids'] == {first.id, second.id}
        return [{'id': chunk.id, 'text': chunk.text, 'distance': .1}]
    with patch('edicola.podcast_draft.semantic_search', side_effect=hits) as search:
        a = generate(standalone, topic='  ISTRUZIONE ', embedder=Mock())
        cached = generate(standalone, topic='istruzione', embedder=Mock())
        b = generate(standalone, topic='mobilità', embedder=Mock())
    assert a.audio_path == cached.audio_path and a.audio_path != b.audio_path
    assert [s['chunk_id'] for s in a.script.sources] == [first.id]
    assert [s['chunk_id'] for s in b.script.sources] == [second.id]
    assert 'trasporto pubblico' not in a.script.text
    assert search.call_count == standalone.text.models.generate_content.call_count == 2
    assert len(list_episodes(standalone.root)) == 2


def test_no_topic_sources_stops_before_generation(standalone):
    with patch('edicola.podcast_draft.semantic_search', return_value=[]):
        with pytest.raises(PodcastError, match='fonti'):
            generate(standalone, topic='vulcanologia', embedder=Mock())
    standalone.text.models.generate_content.assert_not_called()
    standalone.audio.models.generate_content.assert_not_called()


def test_semantic_topic_includes_multiple_relevant_editions(standalone):
    hits = [{'id': c.id, 'text': c.text, 'distance': .1} for c in standalone.catalog.chunks]
    with patch('edicola.podcast_draft.semantic_search', return_value=hits):
        episode = generate(standalone, topic='investimenti pubblici', embedder=Mock())
    assert {s['filename'] for s in episode.script.sources} == {'giornale-0.pdf', 'giornale-1.pdf'}


def test_missing_cover_still_keeps_edition_action(archive):
    from edicola.archive_ui import render_gallery, edition_metadata
    from edicola.pdf_viewer import PdfViewError
    context, _ = archive
    with patch('edicola.archive_ui.read_original', side_effect=PdfViewError('Non disponibile')), \
         patch('edicola.archive_ui.gallery_component') as gallery, patch('edicola.archive_ui.section_intro'):
        render_gallery(context, edition_metadata(context.root, context.documents))
        assert all(c['thumbnail'] is None and c['title'] and c['date'] for c in gallery.call_args.kwargs['data']['editions'])


def test_responsive_components_keep_icons_and_entire_card_actions():
    from edicola.editorial_components import CARD_CSS, CARD_JS
    from edicola.archive_components import GALLERY_CSS, GALLERY_JS
    assert '@media(max-width:600px)' in CARD_CSS and '@media(max-width:340px)' in CARD_CSS
    assert 'createElementNS' in CARD_JS and 'item.id' in CARD_JS and 'aria-current' in CARD_JS
    assert 'repeat(auto-fit,minmax(min(100%,220px),1fr))' in GALLERY_CSS
    assert 'textContent' in GALLERY_JS and 'innerHTML' not in GALLERY_JS


def test_topic_audio_retry_reuses_draft_even_if_topic_changes(standalone):
    chunk = standalone.catalog.chunks[0]
    with patch('edicola.podcast_draft.semantic_search', return_value=[{'id': chunk.id, 'text': chunk.text, 'distance': .1}]) as search:
        standalone.audio.models.generate_content.side_effect = TimeoutError()
        with pytest.raises(PodcastAudioError) as failure:
            generate(standalone, topic='istruzione', embedder=Mock())
        standalone.audio.models.generate_content.side_effect = None
        episode = generate(standalone, retry_key=failure.value.draft.key, topic='economia')
        assert 'istruzione' in episode.title and search.call_count == 1
        assert standalone.text.models.generate_content.call_count == 1


def test_v1_draft_and_audio_context_remain_compatible(standalone):
    episode = generate(standalone)
    path = next((standalone.root/'data/podcast_cache/standalone/scripts').glob('*.json'))
    saved = json.loads(path.read_text(encoding='utf-8'))
    saved['version'] = drafts.LEGACY_VERSION
    saved.pop('topic')
    saved['key'] = drafts.digest([drafts.LEGACY_VERSION, saved['source_identity'], saved['model'], saved['config'], drafts.LEGACY_INSTRUCTION])
    old_path = path.with_name(saved['key']+'.json')
    old_path.write_text(json.dumps(saved), encoding='utf-8')
    old = drafts.load_draft(standalone.root, saved['key'])
    assert old.script.text == episode.script.text
    assert draft_context(old) == {'strategy': drafts.LEGACY_VERSION, 'corpus': old.source_identity, 'script_model': old.model, 'draft': old.key}
    restored = generate(standalone, retry_key=old.key)
    assert any(e.key == restored.key for e in list_episodes(standalone.root))
    assert standalone.text.models.generate_content.call_count == 1


def test_typing_topic_never_submits_and_explicit_submit_is_consumed_once(standalone):
    with patch('edicola.podcast_ui.generate_standalone_podcast') as service:
        app = AppTest.from_string(ui_script(standalone.root)).run()
        app.text_input(key='podcast_topic').set_value('sanità abruzzese').run()
        assert not app.exception
        service.assert_not_called()
        grant(app)
        service.side_effect = PodcastError('fonti insufficienti')
        app.button(key='podcast_submit').click().run()
        assert service.call_args.kwargs['topic'] == 'sanità abruzzese'
        app.run()
        assert service.call_count == 1
