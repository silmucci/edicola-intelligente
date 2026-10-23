"""Task 7: dati temporanei, selezione locale e API esclusivamente simulate."""

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from google.genai import errors, types
from streamlit.testing.v1 import AppTest

from edicola.editorial import cache_write
from edicola.personalization import WORD_BUDGET, generate_personal_briefing, recommend
from edicola.podcast_text import list_products, prepare_script
from edicola.profiles import (Profile, delete_profile, load_profile, personal_root, remove_passage,
                             save_passage, save_profile, set_feedback)
from edicola.rag import RagError
from test_editorial import make_catalog, simulated_response


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setenv("GEMINI_RAG_MODEL", "configured-flash")
    with patch("google.genai.Client", side_effect=AssertionError("API reali vietate")):
        yield


def test_profile_persistence_edit_feedback_and_saved_passages(tmp_path):
    assert load_profile(tmp_path) == Profile()
    assert not (tmp_path / "data").exists()  # Apertura senza creare dati personali.
    profile = Profile(interests=["trasporti", "scuola"], minutes=2, format="audio")
    save_profile(tmp_path, profile)
    assert load_profile(tmp_path) == profile
    set_feedback(tmp_path, "demo", "trasporti", 1)
    set_feedback(tmp_path, "demo", "scuola", -1)
    chunk = make_catalog().chunks[0]
    save_passage(tmp_path, "demo", chunk)
    save_passage(tmp_path, "demo", chunk)
    loaded = load_profile(tmp_path)
    assert loaded.feedback == {"trasporti": 1, "scuola": -1}
    assert len(loaded.saved) == 1 and loaded.saved[chunk.id]["text"] == chunk.text
    loaded.minutes, loaded.format = 10, "visuale"
    save_profile(tmp_path, loaded)
    assert load_profile(tmp_path).minutes == 10
    remove_passage(tmp_path, "demo", chunk.id)
    set_feedback(tmp_path, "demo", "scuola", 0)
    assert load_profile(tmp_path).saved == {}
    assert load_profile(tmp_path).feedback == {"trasporti": 1}


@pytest.mark.parametrize("changes", [{"minutes": 3}, {"format": "video"}, {"interests": ["x"] * 11},
                                     {"feedback": {"segreto": 1}}, {"interests": [""]}])
def test_invalid_preferences_are_not_saved(tmp_path, changes):
    with pytest.raises(ValueError):
        save_profile(tmp_path, replace(Profile(), **changes))
    assert not (tmp_path / "data/profiles.sqlite3").exists()


def test_local_relevance_diversification_duplicates_and_feedback(tmp_path, offline):
    catalog = make_catalog()
    assert recommend(catalog, Profile(interests=["astronomia"])) == []
    assert recommend(catalog, Profile()) == []
    profile = Profile(interests=["trasporti"], minutes=10)
    result = recommend(catalog, profile)
    assert len(result) == 8
    assert len({r.chunk.metadata["filename"] for r in result[:4]}) == 4
    assert all(r.topics == ["trasporti"] and "trasporti" in r.reason for r in result)
    catalog.chunks.append(replace(catalog.chunks[0], id="duplicate"))
    result = recommend(catalog, profile, limit=20)
    assert len(result) == 12
    profile.feedback = {"trasporti": -1}
    assert recommend(catalog, profile) == []
    profile.feedback = {"trasporti": 1}
    assert recommend(catalog, profile)[0].score == 2
    profile.saved = {"chunk-0-2": {}}
    assert recommend(catalog, profile)[0].chunk.id == "chunk-0-2"


def test_topic_feedback_changes_ranking_without_tracking_views(offline):
    catalog = make_catalog()
    catalog.chunks[1] = replace(catalog.chunks[1], text="Nuove risorse per la scuola cittadina e la mensa.")
    profile = Profile(interests=["trasporti", "scuola"])
    profile.feedback["scuola"] = 1
    result = recommend(catalog, profile)
    assert result[0].chunk.id == catalog.chunks[1].id
    assert "feedback" in result[0].reason
    profile.feedback["scuola"] = -1
    assert catalog.chunks[1].id not in [r.chunk.id for r in recommend(catalog, profile)]


def client_with_news():
    client = Mock()
    client.models.generate_content.side_effect = simulated_response
    return client


def test_personal_briefing_cache_sources_partial_archive_and_podcast(tmp_path, offline):
    catalog, client = make_catalog(), client_with_news()
    profile = Profile(interests=["trasporti"], minutes=2)
    key, result = generate_personal_briefing(tmp_path, profile, authorize_external=True, catalog=catalog, client=client)
    assert result.sufficient and result.coverage["partial"]
    assert len(result.sections) == 4
    assert set(result.used_source_ids) <= {s.id for s in result.sources}
    prompt = json.loads(client.models.generate_content.call_args.kwargs["contents"])
    assert prompt["delivery"]["max_words"] == 240
    assert "demo" not in json.dumps(prompt) and "preferences" not in prompt
    assert client.models.generate_content.call_args.kwargs["model"] == "configured-flash"
    repeated_key, cached = generate_personal_briefing(tmp_path, profile, authorize_external=True, catalog=catalog, client=client)
    assert repeated_key == key and cached.from_cache
    assert client.models.generate_content.call_count == 1
    # Il podcast esistente legge il prodotto personale senza ricreare il briefing.
    product = list_products(personal_root(tmp_path, "demo"))[0]
    script = prepare_script(product)
    assert script.sources and script.coverage["partial"]
    assert "[S" not in script.text
    assert not (tmp_path / "data/editorial.sqlite3").exists()
    profile.minutes = 5
    different, _ = generate_personal_briefing(tmp_path, profile, authorize_external=True, catalog=catalog, client=client)
    assert different != key and client.models.generate_content.call_count == 2


@pytest.mark.parametrize("minutes", [2, 5, 10])
def test_length_budget_keeps_complete_validated_news(tmp_path, offline, minutes):
    client = client_with_news()
    def long_response(**kwargs):
        response = simulated_response(**kwargs)
        raw = json.loads(response.text)
        for i, news in enumerate(raw["news"]):
            news["summary"]["text"] = f"Notizia {i}: " + "Parola " * 180
        response.text = json.dumps(raw)
        return response
    client.models.generate_content.side_effect = long_response
    _, result = generate_personal_briefing(tmp_path, Profile(interests=["trasporti"], minutes=minutes),
        authorize_external=True, catalog=make_catalog(), client=client)
    words = sum(len((s["heading"] + " " + s["text"]).split()) for s in result.sections)
    assert result.sufficient and words <= WORD_BUDGET[minutes]
    assert len(result.sections) == {2: 1, 5: 3, 10: 4}[minutes]
    assert all(s["text"].endswith("]") for s in result.sections)


def test_consent_empty_selection_api_error_and_invalid_citations(tmp_path, offline):
    client = client_with_news()
    profile, catalog = Profile(interests=["trasporti"]), make_catalog()
    with pytest.raises(RagError, match="Autorizza"):
        generate_personal_briefing(tmp_path, profile, client=client)
    with pytest.raises(RagError, match="Nessun passaggio"):
        generate_personal_briefing(tmp_path, Profile(), authorize_external=True, client=client, catalog=catalog)
    client.models.generate_content.assert_not_called()
    client.models.generate_content.side_effect = errors.APIError(400, {"error": {"message": "private"}})
    with pytest.raises(RagError, match="HTTP 400"):
        generate_personal_briefing(tmp_path, profile, authorize_external=True, client=client, catalog=catalog)
    assert list_products(personal_root(tmp_path, "demo")) == []
    bad = {"text": "Una notizia non verificata", "evidence": [{"source_id": "S999", "quote": "Non esiste nel documento"}]}
    client.models.generate_content.side_effect = None
    client.models.generate_content.return_value = SimpleNamespace(text=json.dumps({"sufficient": True,
        "news": [{"title": bad, "summary": bad}]}), candidates=[SimpleNamespace(finish_reason=types.FinishReason.STOP)])
    _, result = generate_personal_briefing(tmp_path, profile, authorize_external=True, client=client, catalog=catalog)
    assert not result.sufficient and result.diagnostics["status"] == "citation_validation_failed"
    assert list_products(personal_root(tmp_path, "demo")) == []


def test_delete_removes_only_personal_data_and_preserves_general_products(tmp_path, offline):
    profile = Profile(interests=["trasporti"])
    save_profile(tmp_path, profile)
    save_profile(tmp_path, Profile(user_id="other", interests=["scuola"]))
    _, result = generate_personal_briefing(tmp_path, profile, authorize_external=True, client=client_with_news(), catalog=make_catalog())
    cache_write(tmp_path / "data/editorial.sqlite3", "general", result)
    scope = personal_root(tmp_path, "demo")
    audio = scope / "data/podcast_cache"
    audio.mkdir()
    (audio / "example.wav").write_bytes(b"demo-audio")
    general_before = (tmp_path / "data/editorial.sqlite3").read_bytes()
    delete_profile(tmp_path)
    assert not scope.exists() and load_profile(tmp_path) == Profile()
    assert load_profile(tmp_path, "other").interests == ["scuola"]
    assert (tmp_path / "data/editorial.sqlite3").read_bytes() == general_before


def test_ui_local_start_preferences_recommendations_consent_and_rerun(tmp_path, offline):
    source = f"from pathlib import Path\nfrom edicola.personalization_ui import render_personalization_ui\nrender_personalization_ui(Path({str(tmp_path)!r}))"
    save_profile(tmp_path, Profile(interests=["trasporti"]))
    with patch("edicola.personalization_ui.read_catalog", return_value=make_catalog()), patch(
        "edicola.personalization_ui.generate_personal_briefing", return_value=("test", Mock(sufficient=True))
    ) as generate, patch("edicola.personalization_ui.generate_podcast") as audio:
        app = AppTest.from_string(source).run()
        assert not app.exception
        assert any(s.value == "Consigliati per te" for s in app.subheader)
        generate.assert_not_called()
        audio.assert_not_called()
        app.button(key="FormSubmitter:personal_briefing_form-Genera il mio briefing").click().run()
        assert not app.exception and app.warning
        generate.assert_not_called()
        app.checkbox(key="personal_authorized").check()
        app.button(key="FormSubmitter:personal_briefing_form-Genera il mio briefing").click().run()
        assert not app.exception and generate.call_count == 1
        app.run()
        assert generate.call_count == 1 and audio.call_count == 0
        app.multiselect(key="personal_interests").set_value(["scuola", "ambiente"])
        app.button(key="FormSubmitter:personal_preferences-Salva preferenze").click().run()
        assert not app.exception and load_profile(tmp_path).interests == ["scuola", "ambiente"]
        app.button(key="personal_delete").click().run()
        assert not app.exception and load_profile(tmp_path).interests == []


def test_cache_updates_only_for_effective_changes(tmp_path, offline, monkeypatch):
    profile, catalog, client = Profile(interests=["trasporti"]), make_catalog(), client_with_news()
    first, _ = generate_personal_briefing(tmp_path, profile, authorize_external=True, catalog=catalog, client=client)
    catalog.chunks[0] = replace(catalog.chunks[0], text=catalog.chunks[0].text + " Nuova dichiarazione verificabile.")
    changed, _ = generate_personal_briefing(tmp_path, profile, authorize_external=True, catalog=catalog, client=client)
    assert changed != first
    monkeypatch.setenv("GEMINI_RAG_MODEL", "another-configured-model")
    model_key, _ = generate_personal_briefing(tmp_path, profile, authorize_external=True, catalog=catalog, client=client)
    assert model_key not in {first, changed}
    profile.feedback = {"trasporti": 1}
    feedback_key, _ = generate_personal_briefing(tmp_path, profile, authorize_external=True, catalog=catalog, client=client)
    assert feedback_key == model_key  # Nessuna variazione effettiva della selezione.
    profile.format = "audio"
    audio_key, _ = generate_personal_briefing(tmp_path, profile, authorize_external=True, catalog=catalog, client=client)
    assert audio_key == model_key  # Cambiare la vista non richiede una nuova sintesi.
    assert len(list_products(personal_root(tmp_path, "demo"))) == 3
    assert client.models.generate_content.call_count == 3


@pytest.mark.parametrize("preferred", ["testo", "visuale", "audio"])
def test_cached_products_and_audio_display_offline_on_start(tmp_path, offline, preferred):
    from edicola.podcast import generate_podcast
    from test_podcast import fake_client
    profile = Profile(interests=["trasporti"], format=preferred)
    save_profile(tmp_path, profile)
    key, _ = generate_personal_briefing(tmp_path, profile, authorize_external=True, client=client_with_news(), catalog=make_catalog())
    generate_podcast(key, root=personal_root(tmp_path, "demo"), authorize_external=True, client=fake_client())
    source = f"from pathlib import Path\nfrom edicola.personalization_ui import render_personalization_ui\nrender_personalization_ui(Path({str(tmp_path)!r}))"
    with patch("edicola.personalization_ui.read_catalog", return_value=make_catalog()), patch(
        "edicola.personalization_ui.generate_personal_briefing", side_effect=AssertionError("Generazione automatica vietata")
    ), patch("edicola.personalization_ui.generate_podcast", side_effect=AssertionError("TTS automatico vietato")):
        app = AppTest.from_string(source).run()
        assert not app.exception
        assert app.get("audio") and app.get("download_button")
        assert any("pagina" in item.value for item in app.text)
        assert app.warning  # Copertura parziale dichiarata anche dalla cache.
        app.run()
        assert not app.exception


def test_local_recommendations_preserve_actual_index_and_archive(tmp_path, offline):
    from edicola.chunking import prepare_documents
    from edicola.ingestion import ingest_directory
    from edicola.archive import read_active_chunks
    from edicola.indexing import apply_plan, plan_index
    from edicola.vectorstore import open_collection
    from edicola.editorial_selection import read_catalog
    from test_ingestion import make_pdf
    incoming = tmp_path / "data/incoming"
    incoming.mkdir(parents=True)
    (incoming / "giornale.pdf").write_bytes(make_pdf(("Il piano trasporti approvato. " * 200,)))
    registry = tmp_path / "data/archive.sqlite3"
    prepare_documents(ingest_directory(incoming, registry), registry)
    chunks, _ = read_active_chunks(registry, incoming)
    collection = open_collection(tmp_path / "data/chroma", create=True)
    apply_plan(plan_index(chunks, collection), collection, Mock(embed=Mock(return_value=[1.0] + [0.0] * 767)), 2)
    before = collection.get(include=["embeddings", "documents", "metadatas"])
    archive_before = registry.read_bytes()
    with patch("edicola.ingestion.extract_pdf", side_effect=AssertionError("Nuova estrazione vietata")), patch(
        "edicola.chunking.build_chunks", side_effect=AssertionError("Nuovo chunking vietato")
    ), patch("edicola.embeddings.GeminiEmbedder.embed", side_effect=AssertionError("Nuovo embedding vietato")):
        catalog = read_catalog(tmp_path)
        result = recommend(catalog, Profile(interests=["trasporti"]))
    assert result and catalog.coverage["partial"]
    assert {r.chunk.id for r in result} <= set(before["ids"])
    after = collection.get(include=["embeddings", "documents", "metadatas"])
    assert before["ids"] == after["ids"] and before["documents"] == after["documents"]
    assert before["metadatas"] == after["metadatas"]
    assert (before["embeddings"] == after["embeddings"]).all()
    assert registry.read_bytes() == archive_before


def test_personal_audio_requires_consent_reuses_cache_and_is_deleted(tmp_path, offline):
    from edicola.podcast import generate_podcast
    from test_podcast import fake_client
    profile = Profile(interests=["trasporti"], format="audio")
    save_profile(tmp_path, profile)
    generate_personal_briefing(tmp_path, profile, authorize_external=True, client=client_with_news(), catalog=make_catalog())
    scope = personal_root(tmp_path, "demo")
    client = fake_client()
    source = f"from pathlib import Path\nfrom edicola.personalization_ui import render_personalization_ui\nrender_personalization_ui(Path({str(tmp_path)!r}))"
    with patch("edicola.personalization_ui.read_catalog", return_value=make_catalog()), patch(
        "edicola.personalization_ui.generate_podcast", side_effect=lambda key, **kw: generate_podcast(key, client=client, **kw)
    ) as generate:
        app = AppTest.from_string(source).run()
        submit = "FormSubmitter:personal_audio_form-Genera podcast del mio briefing"
        app.button(key=submit).click().run()
        generate.assert_not_called()
        app.checkbox(key="personal_audio_authorized").check()
        app.button(key=submit).click().run()
        assert not app.exception and app.get("audio")
        client.models.generate_content.assert_called_once()
        app.run()
        assert generate.call_count == 1
        app.button(key=submit).click().run()
        assert generate.call_count == 2 and client.models.generate_content.call_count == 1
        app.button(key="personal_delete").click().run()
        assert not app.exception and not scope.exists()
        assert not app.get("audio") and load_profile(tmp_path).interests == []
