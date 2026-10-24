"""Task 13: componenti, navigazione e ricerca locale con dati sintetici."""

import json
import shutil
import subprocess
import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from edicola.archive_ui import edition_metadata
from edicola.design_tokens import COLORS, CSS_VARS, page_css
from edicola.editorial_components import CARD_CSS, CARD_JS, render_products
from edicola.archive_components import GALLERY_CSS, GALLERY_JS, READER_CSS
from edicola.header_ui import local_matches
from edicola.product_navigation import PRODUCTS, open_product
from test_experience_ui import archive, script
from editorial_adapter import cards_adapter


@pytest.mark.parametrize("index", range(len(PRODUCTS)))
def test_all_product_cards_reach_real_sections_without_generating(archive, index):
    root, _, _ = archive
    with patch("edicola.rag.ask_question") as rag, patch("edicola.editorial.generate_product") as editorial, patch(
        "edicola.knowledge.generate_knowledge") as knowledge:
        app = AppTest.from_string(script(root), default_timeout=15).run()
        app.session_state["consent_choices"] = {("text", "text-v2"): True}
        app.button(key=f"home_products_test_{index}").click().run()
        assert not app.exception and app.session_state["nav_section"] == PRODUCTS[index]["section"]
        product = PRODUCTS[index]
        if product.get("kind"):
            key = "editorial_kind" if product["section"] == "Approfondimenti" else "knowledge_kind"
            assert app.session_state[key] == product["kind"]
        assert app.session_state["consent_choices"][("text", "text-v2")]
        assert len(app.chat_input) == 1
        rag.assert_not_called()
        editorial.assert_not_called()
        knowledge.assert_not_called()


@pytest.mark.parametrize("value", [-1, 100, "1", True, None])
def test_forged_product_indices_do_not_navigate(value):
    state = {"nav_section": "Home"}
    with patch("streamlit.session_state", state):
        assert not open_product(value)
    assert state["nav_section"] == "Home"


def test_local_search_matches_only_real_editions_products_and_passages(archive):
    root, context, catalog = archive
    metadata = edition_metadata(root, context.documents)
    products, editions, chunks = local_matches("trasporti", context.documents, metadata, catalog.chunks)
    assert chunks and all(c in catalog.chunks and "trasporti" in c.text for c in chunks)
    assert len(chunks) <= 5
    assert local_matches("Edizione B", context.documents, metadata)[1] == [context.documents[1]]
    assert local_matches("podcast", context.documents, metadata)[0] == [5]
    assert local_matches("notizia inesistente xyz", context.documents, metadata, catalog.chunks) == ([], [], [])
    assert local_matches("  ", context.documents, metadata, catalog.chunks) == ([], [], [])


def test_header_search_and_profile_are_local_actions(archive):
    root, _, catalog = archive
    code = script(root) + '\nfrom edicola.header_ui import render_header\nrender_header(root, context)\n'
    with patch("edicola.editorial_selection.read_catalog", return_value=catalog), patch("edicola.rag.ask_question") as ask:
        app = AppTest.from_string(code, default_timeout=15).run()
        app.text_input(key="account_header_search").set_value("podcast").run()
        app.button(key="header_product_5").click().run()
        assert not app.exception and app.session_state["nav_section"] == "Podcast"
        app.button(key="header_profile").click().run()
        assert not app.exception and app.session_state["nav_section"] == "Personalizzazione"
        assert app.session_state["personal_area"] == "Preferenze"
        ask.assert_not_called()


def test_home_date_filter_and_highlights_use_real_archive_metadata(archive):
    root, _, _ = archive
    with patch("edicola.archive_ui.gallery_component") as gallery:
        app = AppTest.from_string(script(root), default_timeout=15).run()
        options = app.selectbox(key="home_edition_date").options
        assert options == ["Tutte le edizioni", "23 ottobre 2026", "21 ottobre 2026"]
        app.selectbox(key="home_edition_date").set_value("23 ottobre 2026").run()
        assert not app.exception
        home = next(c for c in reversed(gallery.call_args_list) if c.kwargs["key"] == "home_gallery")
        assert len(home.kwargs["data"]["editions"]) == 1
        assert home.kwargs["data"]["editions"][0]["title"] == "Edizione B"


def test_archive_filter_opens_selected_edition_not_unfiltered_index(archive):
    root, _, _ = archive
    def gallery_adapter(**kwargs):
        if kwargs["key"] == "archive_gallery":
            import streamlit as st
            def select():
                st.session_state["archive_gallery"] = {"open_edition": 0}
                kwargs["on_open_edition_change"]()
            st.button("Apri edizione filtrata", key="filtered_test_open", on_click=select)
    with patch("edicola.archive_ui.gallery_component", side_effect=gallery_adapter):
        app = AppTest.from_string(script(root), default_timeout=15).run()
        app.selectbox(key="archive_edition_date").set_value("23 ottobre 2026").run()
        app.button(key="filtered_test_open").click().run()
        assert not app.exception and app.session_state["archive_pdf"] == "b.pdf"
        assert app.session_state["archive_page"] == 1 and app.session_state["nav_section"] == "Archivio"


def test_highlights_are_literal_excerpts_with_verified_labels(archive):
    root, _, catalog = archive
    # Override only the test adapter to inspect the actual component payload.
    with patch("edicola.editorial_components.cards_component") as component:
        app = AppTest.from_string(script(root), default_timeout=15).run()
        assert not app.exception
        highlights = next(c.kwargs["data"] for c in component.call_args_list if c.kwargs["key"] == "home_highlights")
    for item in highlights["items"]:
        excerpt = item["description"].strip("«»").removesuffix("…")
        assert any(excerpt in c.text for c in catalog.chunks)
        assert "Edizione" in item["title"] and ".pdf" not in item["title"]


def test_tokens_theme_contrast_and_styles_are_local_and_scoped():
    theme = tomllib.loads((Path(__file__).parents[1] / ".streamlit/config.toml").read_text())["theme"]
    assert theme["primaryColor"] == COLORS["primary"] and theme["backgroundColor"] == COLORS["paper"]
    assert theme["textColor"] == COLORS["ink"] and theme["borderColor"] == COLORS["border"]
    combined = CARD_CSS + GALLERY_CSS + READER_CSS + page_css()
    assert "@media(max-width:1280px)" in combined and "@media(max-width:1024px)" in combined
    assert "@media(max-width:600px)" in combined and "prefers-reduced-motion" in combined
    assert "overflow-x:auto" in CARD_CSS and "scroll-snap-type:x mandatory" in GALLERY_CSS
    assert "object-fit:contain" in GALLERY_CSS and "height:70dvh" in READER_CSS
    assert "focus-visible" in CARD_CSS + GALLERY_CSS
    assert not any(value in combined for value in ("data-testid", ".stApp", "!important", "@import", "https://"))
    assert "innerHTML" not in CARD_JS + GALLERY_JS


def test_product_component_uses_keyboard_buttons_and_literal_text(tmp_path):
    """Esegue il JS effettivo su un DOM minimo, non una verifica visiva simulata."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node non disponibile")
    harness = r'''
const nodes=[];
class Element{
 constructor(tag){this.tag=tag;this.children=[];this.attrs={};this.classList={toggle(){},add(){}};nodes.push(this);}
 append(...items){this.children.push(...items);} replaceChildren(){this.children=[];}
 setAttribute(k,v){this.attrs[k]=v;}
}
const root=new Element('nav');
const document={createElement:t=>new Element(t),createElementNS:(_,t)=>new Element(t)};
const parentElement={querySelector:()=>root};const events=[];
const run=COMPONENT;
run({parentElement,data:{mode:'products',items:[{title:'<img onerror=x>',description:'Testo originale',icon:'paper',active:true}]},setTriggerValue:(...args)=>events.push(args)});
root.children[0].onclick();
console.log(JSON.stringify({tag:root.children[0].tag,type:root.children[0].type,title:nodes.find(n=>n.tag==='h3').textContent,events}));
'''.replace("COMPONENT", CARD_JS.replace("export default function", "function"))
    result = subprocess.run([node, "--input-type=module", "-e", harness], capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    assert data == dict(tag="button", type="button", title="<img onerror=x>", events=[["selected", 0]])


def test_section_heading_escapes_untrusted_text():
    code = '''from edicola.design import section_intro
section_intro('<img src=x onerror=x>', '<script>bad()</script>', 'Fonte & testo')
'''
    app = AppTest.from_string(code).run()
    assert not app.exception
    rendered = app.get("html")[0].proto.body
    assert "&lt;img" in rendered and "<img src=x" not in rendered
    assert "&lt;script&gt;" in rendered and "<script>" not in rendered


def test_authenticated_header_initials_logout_and_private_search_reset(archive, monkeypatch):
    from types import ModuleType
    from test_personal_accounts import AUTH, user, User
    _, context, _ = archive
    monkeypatch.setenv("EDICOLA_PROFILE_MODE", "accounts")
    fixture = ModuleType("edicola.header_test_context")
    fixture.context = context
    code = '''from edicola.header_test_context import context
from edicola.header_ui import render_header
render_header(context.root, context)
'''
    guest = User()
    guest.is_logged_in = False
    with patch.dict("sys.modules", {"edicola.header_test_context": fixture}), patch("streamlit.secrets", {"auth": AUTH}), patch(
        "streamlit.user", user(name="Mario Rossi")), patch("streamlit.logout") as logout, patch(
        "edicola.editorial_selection.read_catalog", side_effect=RuntimeError("Indice non disponibile")):
        app = AppTest.from_string(code).run()
        assert not app.exception and app.button(key="header_profile").label.startswith("MR")
        app.text_input(key="account_header_search").set_value("podcast").run()
        app.button(key="header_auth_logout").click().run()
        logout.assert_called_once()
        assert not app.exception and app.text_input(key="account_header_search").value == ""
        with patch("streamlit.user", guest):
            app.run()
        assert not app.exception and app.button(key="header_auth_login")
        assert app.button(key="header_profile").label == "Il mio profilo"
