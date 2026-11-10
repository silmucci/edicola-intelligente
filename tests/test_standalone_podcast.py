"""Podcast indipendente: SDK simulati, corpus sintetico e file solo temporanei."""
import io
import json
import wave
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from google.genai import types

from edicola.api_guard import PermissionDenied
from edicola.archive import IndexChunk
from edicola.editorial_selection import Catalog
from edicola.podcast import generate_podcast
from edicola.podcast_draft import script_from_response, load_draft
from edicola.podcast_text import PodcastError
from edicola.standalone_podcast import generate_standalone_podcast, list_episodes, PodcastAudioError
from test_podcast import podcast_archive, fake_client, tts_response


def long_wav(seconds=20):
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b'\0\0' * 24000 * seconds)
    return stream.getvalue()


@pytest.fixture
def standalone(tmp_path, monkeypatch):
    texts = ["Il Comune ha stanziato 4 milioni di euro per le scuole.",
             "La Regione ha approvato un piano per il trasporto pubblico."]
    chunks = [IndexChunk(str(i), text, {"filename": f'giornale-{i}.pdf', "pdf_sha256": str(i)*64,
              "chunk_config": "v1", "position": 0, "page": i+1}) for i, text in enumerate(texts)]
    catalog = Catalog(chunks, {c.id: [1., float(i)] for i, c in enumerate(chunks)},
        {"corpus_version": "corpus-test", "indexed": 2, "total": 2, "partial": False, "files": [
         {"pdf": c.metadata['filename'], "date": "2026-10-25", "publication": "Testata di prova", "indexed": 1, "total": 1} for c in chunks]})
    client = Mock()
    def response(**kwargs):
        sources = json.loads(kwargs['contents'])['sources']
        news = [{"title": {"text": "Notizia dalle fonti", "evidence": [{"source_id": s['source_id'], "quote": s['text']}]},
                 "summary": {"text": s['text'], "evidence": [{"source_id": s['source_id'], "quote": s['text']}]}} for s in sources]
        return SimpleNamespace(text=json.dumps({"sufficient": True, "news": news}), candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)])
    client.models.generate_content.side_effect = response
    tts = Mock()
    tts.models.generate_content.return_value = tts_response(long_wav())
    monkeypatch.setenv("GEMINI_API_KEY", "fake-test-key")
    monkeypatch.setenv("GEMINI_RAG_MODEL", "configured-text-model")
    monkeypatch.setenv("GEMINI_TTS_MODEL", "configured-tts-model")
    with patch("edicola.podcast_draft.read_catalog", return_value=catalog), patch("google.genai.Client", side_effect=AssertionError("API reali vietate")):
        yield SimpleNamespace(root=tmp_path, catalog=catalog, text=client, audio=tts)


def generate(case, **kwargs):
    return generate_standalone_podcast(root=case.root, client=case.text, tts_client=case.audio,
                                      authorize_text=True, authorize_audio=True, **kwargs)


def test_no_briefing_is_required_and_no_briefing_is_written(standalone):
    with patch("edicola.editorial.generate_product", side_effect=RuntimeError("Briefing failed")) as briefing:
        episode = generate(standalone)
        briefing.assert_not_called()
    assert episode.audio_path.exists() and episode.seconds == 20
    assert not (standalone.root/'data/editorial.sqlite3').exists()
    assert standalone.text.models.generate_content.call_count == standalone.audio.models.generate_content.call_count == 1
    assert len(episode.script.sources) == 2
    assert not any(token in episode.script.text for token in ('[S1]', '.pdf', 'chunk-'))
    assert len(episode.script.text.split()) <= 240
    assert "4 milioni" in episode.script.text
    assert list_episodes(standalone.root)[0].script == episode.script


def test_tts_failure_preserves_script_and_retry_never_regenerates_text(standalone):
    standalone.audio.models.generate_content.side_effect = TimeoutError()
    with pytest.raises(PodcastAudioError) as failed:
        generate(standalone)
    key = failed.value.draft.key
    assert load_draft(standalone.root, key).script.text
    assert not list_episodes(standalone.root)
    standalone.audio.models.generate_content.side_effect = None
    episode = generate(standalone, retry_key=key)
    assert episode.audio_path.exists()
    assert standalone.text.models.generate_content.call_count == 1
    assert standalone.audio.models.generate_content.call_count == 2


def test_cache_avoids_both_requests_and_voice_change_reuses_text(standalone):
    first = generate(standalone, voice="Kore")
    cached = generate(standalone, voice="Kore")
    assert cached.from_cache and cached.audio_path == first.audio_path
    assert standalone.text.models.generate_content.call_count == standalone.audio.models.generate_content.call_count == 1
    other = generate(standalone, voice="Aoede")
    assert other.audio_path != first.audio_path and standalone.text.models.generate_content.call_count == 1
    assert standalone.audio.models.generate_content.call_count == 2 and len(list_episodes(standalone.root)) == 2


@pytest.mark.parametrize('purpose', ['text', 'audio'])
def test_missing_consent_prevents_all_remote_requests(standalone, purpose):
    options = dict(authorize_text=True, authorize_audio=True)
    options['authorize_'+purpose] = False
    with pytest.raises(PermissionDenied):
        generate_standalone_podcast(root=standalone.root, client=standalone.text, tts_client=standalone.audio, **options)
    standalone.text.models.generate_content.assert_not_called()
    standalone.audio.models.generate_content.assert_not_called()


def test_audio_revoked_between_stages_preserves_script_and_sends_no_audio(standalone):
    check = Mock(side_effect=[True, False])
    with pytest.raises(PodcastAudioError):
        generate(standalone, audio_check=check)
    assert standalone.text.models.generate_content.call_count == 1
    standalone.audio.models.generate_content.assert_not_called()


def test_no_sources_or_unsupported_output_never_produces_audio(standalone):
    standalone.catalog.chunks.clear()
    with pytest.raises(PodcastError, match="fonti"):
        generate(standalone)
    standalone.text.models.generate_content.assert_not_called()
    standalone.audio.models.generate_content.assert_not_called()


def test_invented_number_and_invalid_citation_are_rejected(standalone):
    def response(**kwargs):
        return SimpleNamespace(text=json.dumps({"sufficient": True, "news": [{
            "title": {"text": "Nuovi fondi", "evidence": [{"source_id": "S1", "quote": standalone.catalog.chunks[0].text}]},
            "summary": {"text": "Sono stanziati 999 milioni.", "evidence": [{"source_id": "S1", "quote": standalone.catalog.chunks[0].text}]}}]}),
            candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)])
    standalone.text.models.generate_content.side_effect = response
    with pytest.raises(PodcastError):
        generate(standalone)
    standalone.audio.models.generate_content.assert_not_called()
    assert not list((standalone.root/'data/podcast_cache/standalone/scripts').glob('*.json'))


def test_briefing_database_corruption_does_not_block_standalone(standalone):
    (standalone.root/'data').mkdir()
    database = standalone.root/'data/editorial.sqlite3'
    database.write_bytes(b'broken database')
    episode = generate(standalone)
    assert episode.audio_path.exists() and list_episodes(standalone.root)
    assert database.read_bytes() == b'broken database'


def test_historical_podcast_remains_available_without_generating(podcast_archive):
    client = fake_client()
    old = generate_podcast('product-1', root=podcast_archive, authorize_external=True, client=client)
    with patch('google.genai.Client', side_effect=AssertionError('API vietate')):
        episodes = list_episodes(podcast_archive)
    assert len(episodes) == 1 and episodes[0].audio_path == old.audio_path
    assert episodes[0].script == old.script


def test_corpus_model_and_strategy_have_distinct_cache_identities(standalone, monkeypatch):
    first = generate(standalone)
    standalone.catalog.coverage['corpus_version'] = 'new-snapshot'
    second = generate(standalone)
    monkeypatch.setenv('GEMINI_RAG_MODEL', 'another-configured-text-model')
    third = generate(standalone)
    assert len({first.key, second.key, third.key}) == 3
    assert standalone.text.models.generate_content.call_count == standalone.audio.models.generate_content.call_count == 3


def test_invalid_short_audio_is_not_published_but_script_is_kept(standalone):
    standalone.audio.models.generate_content.return_value = tts_response()
    with pytest.raises(PodcastAudioError):
        generate(standalone)
    assert not list_episodes(standalone.root)
    assert list((standalone.root/'data/podcast_cache/standalone/scripts').glob('*.json'))


@pytest.mark.parametrize('outcome', ['abstention', 'citation', 'truncated'])
def test_unsuitable_text_output_never_reaches_tts(standalone, outcome):
    value = {"sufficient": False, "news": []}
    if outcome == 'citation':
        claim = {"text": "Notizia non documentata", "evidence": [{"source_id": "S999", "quote": "Una citazione inventata e non presente."}]}
        value = {"sufficient": True, "news": [{"title": claim, "summary": claim}]}
    reason = types.FinishReason.MAX_TOKENS if outcome == 'truncated' else types.FinishReason.STOP
    standalone.text.models.generate_content.side_effect = None
    standalone.text.models.generate_content.return_value = SimpleNamespace(text=json.dumps(value), candidates=[SimpleNamespace(finish_reason=reason)])
    with pytest.raises(PodcastError):
        generate(standalone)
    assert standalone.text.models.generate_content.call_count == 1
    standalone.audio.models.generate_content.assert_not_called()


def test_failed_new_episode_keeps_the_previous_one(standalone):
    previous = generate(standalone)
    standalone.catalog.coverage['corpus_version'] = 'updated'
    standalone.audio.models.generate_content.side_effect = TimeoutError()
    with pytest.raises(PodcastAudioError):
        generate(standalone)
    episodes = list_episodes(standalone.root)
    assert len(episodes) == 1 and episodes[0].key == previous.key


def test_retry_rejects_changed_sources_without_regenerating_text(standalone):
    standalone.audio.models.generate_content.side_effect = TimeoutError()
    with pytest.raises(PodcastAudioError) as failure:
        generate(standalone)
    old = standalone.catalog.chunks[0]
    standalone.catalog.chunks[0] = replace(old, text=old.text + ' Fonte modificata.')
    with pytest.raises(PodcastError, match='fonti'):
        generate(standalone, retry_key=failure.value.draft.key)
    assert standalone.text.models.generate_content.call_count == standalone.audio.models.generate_content.call_count == 1


def test_topic_podcast_keeps_strong_semantic_match_without_exact_keyword(standalone):
    """Un articolo può trattare il tema senza ripeterne la parola letterale."""
    from edicola.podcast_draft import select_chunks
    source = standalone.catalog.chunks[0]
    strong_hit = {"id": source.id, "text": source.text, "distance": 0.23}
    with patch("edicola.podcast_draft.require_permission"), patch(
        "edicola.podcast_draft.semantic_search", return_value=[strong_hit]
    ), patch("edicola.podcast_draft.ranked_chunks", return_value=[]):
        selected = select_chunks(standalone.root, standalone.catalog, SimpleNamespace(),
                                 "corruzione in abruzzo", "fake", embedder=Mock())
    assert [item.id for item in selected] == [source.id]


def test_topic_podcast_does_not_accept_weak_semantic_match_alone(standalone):
    from edicola.podcast_draft import select_chunks
    source = standalone.catalog.chunks[0]
    weak_hit = {"id": source.id, "text": source.text, "distance": 0.58}
    with patch("edicola.podcast_draft.require_permission"), patch(
        "edicola.podcast_draft.semantic_search", return_value=[weak_hit]
    ), patch("edicola.podcast_draft.ranked_chunks", return_value=[]):
        selected = select_chunks(standalone.root, standalone.catalog, SimpleNamespace(),
                                 "corruzione in abruzzo", "fake", embedder=Mock())
    assert selected == []
