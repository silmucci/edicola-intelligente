"""Podcast autonomo: consensi sequenziali e navigazione, SDK sempre simulati."""
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
from edicola import consent
from edicola.standalone_podcast import generate_standalone_podcast
from edicola.podcast import generate_podcast
from edicola.personal_store import PersonalStoreError
from test_standalone_podcast import standalone
from test_podcast import podcast_archive, fake_client


def ui_script(root):
    return f"from pathlib import Path\nfrom edicola.podcast_ui import render_podcast_ui\nrender_podcast_ui(Path({str(root)!r}))"


def grant(app):
    app.session_state['consent_choices'] = {(p, consent.PURPOSES[p][0]): True for p in ('text', 'audio')}


def test_empty_library_has_generate_command_and_never_requires_briefing(tmp_path):
    with patch('google.genai.Client', side_effect=AssertionError('API vietate')), patch('edicola.podcast_ui.generate_standalone_podcast') as generate:
        app = AppTest.from_string(ui_script(tmp_path)).run()
        assert not app.exception and app.button(key='podcast_submit').label == 'Genera podcast'
        assert app.text_input(key='podcast_topic').value == ''
        assert not any('briefing' in i.value.lower() for i in app.info)
        app.run()
        generate.assert_not_called()
        assert not list(tmp_path.iterdir())


def test_two_consents_before_any_request_then_player_and_no_repeat(standalone):
    def generate(**kwargs):
        return generate_standalone_podcast(**kwargs, client=standalone.text, tts_client=standalone.audio)
    with patch('edicola.podcast_ui.generate_standalone_podcast', side_effect=generate) as service:
        app = AppTest.from_string(ui_script(standalone.root)).run()
        app.button(key='podcast_submit').click().run()
        assert not app.exception and app.button(key='consent_accept')
        standalone.text.models.generate_content.assert_not_called()
        app.button(key='consent_accept').click().run()
        assert not app.exception and app.session_state['consent_pending']['purpose'] == 'audio'
        standalone.text.models.generate_content.assert_not_called()
        app.button(key='consent_accept').click().run()
        assert not app.exception and len(app.get('audio')) == 1 and len(app.get('download_button')) == 1
        assert service.call_count == 1
        app.run()
        app.selectbox(key='podcast_voice').set_value('Aoede').run()
        assert service.call_count == 1
        assert standalone.text.models.generate_content.call_count == standalone.audio.models.generate_content.call_count == 1


def test_old_text_consent_does_not_authorize_new_podcast_treatment(standalone):
    with patch('edicola.podcast_ui.generate_standalone_podcast') as generate:
        app = AppTest.from_string(ui_script(standalone.root)).run()
        app.session_state['consent_choices'] = {('text', 'text-v3'): True, ('audio', 'audio-v1'): True}
        app.button(key='podcast_submit').click().run()
        assert app.session_state['consent_pending']['purpose'] == 'text'
        app.button(key='consent_refuse').click().run()
        assert not app.exception
        generate.assert_not_called()


def test_audio_refusal_prevents_text_generation_too(standalone):
    with patch('edicola.podcast_ui.generate_standalone_podcast') as generate:
        app = AppTest.from_string(ui_script(standalone.root)).run()
        app.session_state['consent_choices'] = {('text', consent.PURPOSES['text'][0]): True}
        app.button(key='podcast_submit').click().run()
        assert app.session_state['consent_pending']['purpose'] == 'audio'
        app.button(key='consent_refuse').click().run()
        app.run()
        assert not app.exception
        generate.assert_not_called()


def test_failed_tts_has_manual_audio_only_retry(standalone):
    def generate(**kwargs):
        return generate_standalone_podcast(**kwargs, client=standalone.text, tts_client=standalone.audio)
    standalone.audio.models.generate_content.side_effect = TimeoutError()
    with patch('edicola.podcast_ui.generate_standalone_podcast', side_effect=generate) as service:
        app = AppTest.from_string(ui_script(standalone.root)).run()
        grant(app)
        app.button(key='podcast_submit').click().run()
        assert not app.exception and app.error and app.button(key='podcast_retry')
        app.run()
        assert service.call_count == 1
        standalone.audio.models.generate_content.side_effect = None
        app.button(key='podcast_retry').click().run()
        assert not app.exception and len(app.get('audio')) == 1
        assert standalone.text.models.generate_content.call_count == 1 and standalone.audio.models.generate_content.call_count == 2


def test_historical_episode_is_playable_on_open_without_new_generation(podcast_archive):
    generate_podcast('product-1', root=podcast_archive, authorize_external=True, client=fake_client())
    with patch('edicola.podcast_ui.generate_standalone_podcast') as generate, patch('google.genai.Client', side_effect=AssertionError('API vietate')):
        app = AppTest.from_string(ui_script(podcast_archive)).run()
        assert not app.exception and len(app.get('audio')) == 1
        app.run()
        generate.assert_not_called()


def test_navigation_does_not_resume_generation(tmp_path):
    script = 'import streamlit as st\n' + ui_script(tmp_path).replace('render_podcast_ui(Path(', 'if st.session_state.get("area", "Podcast") == "Podcast": render_podcast_ui(Path(')
    with patch('edicola.podcast_ui.generate_standalone_podcast') as generate, patch('google.genai.Client', side_effect=AssertionError('API vietate')):
        app = AppTest.from_string(script).run()
        app.session_state['area'] = 'Briefing'
        app.run()
        app.session_state['area'] = 'Podcast'
        app.run()
        assert not app.exception
        generate.assert_not_called()


def test_header_has_search_and_profile_icons_after_the_brand(tmp_path):
    code = f'''from pathlib import Path
from types import SimpleNamespace
from edicola.header_ui import render_header
render_header(Path({str(tmp_path)!r}), SimpleNamespace(documents=[],root=Path({str(tmp_path)!r})))
'''
    with patch('edicola.identity.synchronize_identity'), patch('edicola.identity.local_demo', return_value=False), patch('edicola.identity.native_logged_in', return_value=False), patch('edicola.identity.google_configured', return_value=True), patch('edicola.identity.login') as login:
        app = AppTest.from_string(code).run()
        assert not app.exception
        assert app.button(key='header_auth_login').label == 'Accedi con Google'
        assert app.button(key='header_profile').label == 'Il mio profilo'
        app.button(key='header_auth_login').click().run()
        login.assert_called_once()
        assert not app.exception


def test_consent_lookup_error_sends_nothing(standalone):
    with patch('edicola.podcast_ui.generate_standalone_podcast') as generate, patch('edicola.consent.allowed', side_effect=[True, PersonalStoreError('unavailable')]):
        app = AppTest.from_string(ui_script(standalone.root)).run()
        app.button(key='podcast_submit').click().run()
        assert not app.exception and app.error
        generate.assert_not_called()


def test_unreadable_episode_catalog_keeps_the_last_session_audio(standalone):
    episode = generate_standalone_podcast(root=standalone.root, authorize_text=True, authorize_audio=True,
        client=standalone.text, tts_client=standalone.audio)
    with patch('edicola.podcast_ui.list_episodes', side_effect=OSError('unavailable')), patch('edicola.podcast_ui.generate_standalone_podcast') as generate:
        app = AppTest.from_string(ui_script(standalone.root))
        app.session_state['podcast_episode'] = episode
        app.run()
        assert not app.exception and len(app.get('audio')) == 1
        generate.assert_not_called()
