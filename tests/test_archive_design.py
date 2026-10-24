"""Vista editoriale: miniature autentiche, metadati verificati e diagnostica opt-in."""

import io
import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

from PIL import Image
import pytest
from streamlit.testing.v1 import AppTest

from edicola.archive_components import GALLERY_CSS, GALLERY_JS, READER_CSS, READER_JS
from edicola.archive_ui import cover_thumbnail, diagnostics_enabled, edition_metadata
from edicola.pdf_viewer import read_original
from test_pdf_viewer import archive, script


@pytest.fixture(autouse=True)
def client_mode(monkeypatch):
    monkeypatch.setenv("EDICOLA_ARCHIVE_DIAGNOSTICS", "0")
    with patch("google.genai.Client", side_effect=AssertionError("Nessuna chiamata Gemini")):
        yield


def test_thumbnails_are_first_page_renders_with_bounded_dimensions(archive):
    context, _ = archive
    original = read_original(context, context.documents[0])
    thumbnail = cover_thumbnail(original, 2)
    with Image.open(io.BytesIO(thumbnail)) as image:
        assert 0 < image.width <= 320 and 0 < image.height <= 420
        assert image.height > image.width
    with patch("edicola.archive_ui.render_page", side_effect=AssertionError("Miniatura rigenerata")):
        assert cover_thumbnail(original, 2) == thumbnail


def test_verified_editions_and_missing_or_invalid_metadata(archive):
    context, _ = archive
    missing = edition_metadata(context.root, context.documents)
    assert missing["a.pdf"]["title"] == "Edizione 1"
    assert missing["a.pdf"]["date"] == "Data non disponibile"
    path = context.root / "data/editions.json"
    path.write_text(json.dumps({"a.pdf": {"publication": "Testata verificata", "date": "2026-10-21"},
                                "b.pdf": {"publication": "", "date": "2026-02-30"}}), encoding="utf-8")
    known = edition_metadata(context.root, context.documents)
    assert known["a.pdf"] == {"title": "Testata verificata", "date": "21 ottobre 2026", "pages": 2}
    assert known["b.pdf"]["title"] == "Edizione 2" and known["b.pdf"]["date"] == "Data non disponibile"
    path.write_text("broken-json", encoding="utf-8")
    assert edition_metadata(context.root, context.documents) == missing


def test_gallery_payload_has_no_technical_identifiers_and_no_reader_on_start(archive):
    context, _ = archive
    with patch("edicola.archive_ui.gallery_component") as gallery, patch("edicola.archive_ui.reader_component") as reader:
        app = AppTest.from_string(script(context), default_timeout=10).run()
        assert not app.exception and not app.dataframe and not app.metric and not app.expander
        reader.assert_not_called()
        cards = gallery.call_args.kwargs["data"]["editions"]
        assert len(cards) == 2 and cards[0]["thumbnail"]
        assert set(cards[0]) == {"title", "date", "pages", "thumbnail"}
        visible = json.dumps([{k: v for k, v in c.items() if k != "thumbnail"} for c in cards])
        assert "a.pdf" not in visible and "SHA" not in visible and "chunk" not in visible
        assert not app.get("file_uploader")


def test_component_cover_click_and_page_callbacks_are_validated(archive):
    context, _ = archive
    # Adattatori di test Python: verificano i callback v2 senza simulare un browser reale.
    def gallery_adapter(**kwargs):
        import streamlit as st
        def select():
            st.session_state["archive_gallery"] = {"open_edition": 0}
            kwargs["on_open_edition_change"]()
        st.button("Copertina di prova", key="test_cover", on_click=select)
    def reader_adapter(**kwargs):
        import streamlit as st
        page, total = kwargs["data"]["page"], kwargs["data"]["total"]
        def turn(target):
            st.session_state["archive_reader"] = {"page": target}
            kwargs["on_page_change"]()
        st.button("Avanti", key="test_next", disabled=page >= total, on_click=turn, args=(page+1,))
        st.button("Indietro", key="test_previous", disabled=page <= 1, on_click=turn, args=(page-1,))
        st.button("Pagina fuori intervallo", key="test_bad", on_click=turn, args=(99,))
    with patch("edicola.archive_ui.gallery_component", side_effect=gallery_adapter), patch("edicola.archive_ui.reader_component", side_effect=reader_adapter):
        app = AppTest.from_string(script(context), default_timeout=10).run()
        app.button(key="test_cover").click().run()
        assert not app.exception and app.session_state["archive_open"] and app.session_state["archive_page"] == 1
        assert app.button(key="test_previous").disabled
        app.button(key="test_next").click().run()
        assert not app.exception and app.session_state["archive_page"] == 2 and app.button(key="test_next").disabled
        app.button(key="test_bad").click().run()
        assert not app.exception and app.session_state["archive_page"] == 2
        app.button(key="test_previous").click().run()
        assert app.session_state["archive_page"] == 1
        app.button(key="archive_back").click().run()
        assert not app.exception and not app.session_state["archive_open"]


def test_reader_uses_one_page_and_hides_file_names_hashes_and_extracted_text(archive):
    context, _ = archive
    source = script(context).replace('render_archive(context, prepared)', '''
st.session_state["archive_open"]=True
st.session_state["archive_pdf"]="a.pdf"
st.session_state["archive_page"]=2
render_archive(context, prepared)''')
    with patch("edicola.archive_ui.reader_component") as reader, patch("edicola.archive_ui.gallery_component") as gallery:
        app = AppTest.from_string(source, default_timeout=10).run()
        assert not app.exception and not app.dataframe and not app.expander
        gallery.assert_not_called()
        data = reader.call_args.kwargs["data"]
        assert data["page"] == 2 and data["total"] == 2 and "png" in data
        assert "filename" not in data
        visible = " ".join(e.value for family in (app.caption, app.text, app.subheader) for e in family)
        assert all(text not in visible for text in ("SHA-256", "chunk", "a.pdf", "Seconda pagina", "F11", "browser"))
        assert app.get("download_button")


def test_diagnostics_only_from_configuration_not_normal_ui(archive, monkeypatch):
    context, _ = archive
    assert not diagnostics_enabled(context.root)
    monkeypatch.delenv("EDICOLA_ARCHIVE_DIAGNOSTICS")
    (context.root / ".env").write_text("EDICOLA_ARCHIVE_DIAGNOSTICS=1\n", encoding="utf-8")
    assert diagnostics_enabled(context.root)
    app = AppTest.from_string(script(context), default_timeout=10).run()
    assert not app.exception and app.dataframe
    assert any(e.label == "Diagnostica archivio" for e in app.expander)
    assert not app.checkbox and not app.toggle  # Nessun interruttore cliente per attivarla.


@pytest.mark.parametrize("area_width,area_height", [(1200, 850), (740, 700), (390, 560), (320, 400), (0, 0)])
def test_real_javascript_fit_and_zoom_geometry(area_width, area_height):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node non disponibile per il test del solo calcolo JavaScript; nessun browser simulato.")
    code = READER_JS + f"\nconsole.log(JSON.stringify({{fit:pageGeometry(1000,1500,{area_width},{area_height}),zoomed:pageGeometry(1000,1500,{area_width},{area_height},200),limits:[clampZoom(-10),clampZoom(999)]}}));"
    result = subprocess.run([node, "--input-type=module", "-e", code], capture_output=True, text=True, check=True)
    geometry = json.loads(result.stdout)
    assert geometry["limits"] == [75, 200]
    if area_width == 0:
        assert geometry["fit"] is None
    else:
        fit, zoomed = geometry["fit"], geometry["zoomed"]
        assert fit["width"] <= min(520, area_width-32) and fit["height"] <= area_height-32
        assert fit["width"] / fit["height"] == pytest.approx(2/3)
        assert zoomed["width"] == pytest.approx(fit["width"]*2)


def test_styles_and_metadata_rendering_are_isolated_and_offline():
    assert "grid-template-columns" in GALLERY_CSS and "max-width:740px" in READER_CSS
    assert "height:70dvh" in READER_CSS and "overflow:auto" in READER_CSS
    assert ".stApp" not in GALLERY_CSS + READER_CSS and "data-testid" not in GALLERY_CSS + READER_CSS
    assert "https://" not in GALLERY_JS + READER_JS and "innerHTML" not in GALLERY_JS


def test_full_app_client_home_keeps_all_sections_without_archive_diagnostics(archive):
    from edicola.profiles import Profile
    context, prepared = archive
    with patch("edicola.ingestion.ingest_directory", return_value=context.documents), patch(
        "edicola.chunking.prepare_documents", return_value=prepared
    ), patch("edicola.pdf_viewer.archive_context", return_value=context), patch(
        "edicola.podcast_ui.list_products", return_value=[]
    ), patch("edicola.personalization_ui.load_profile", return_value=Profile()), patch(
        "edicola.personalization_ui.list_products", return_value=[]
    ):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=10).run()
        assert not app.exception and not app.dataframe and not app.metric
        assert [tab.label for tab in app.tabs] == ["Home", "Archivio", "Chat AI", "Approfondimenti", "Timeline e Mappe", "Podcast", "Personalizzazione"]
        assert not app.checkbox
        assert "consent_choices" not in app.session_state
        assert not app.get("file_uploader")
