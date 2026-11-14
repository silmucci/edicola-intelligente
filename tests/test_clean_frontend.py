"""Regression: ripristino della navigazione editoriale classica senza modifiche alle funzioni."""

from pathlib import Path
import tomllib

from edicola.design_tokens import COLORS, page_css
from edicola.editorial_components import CARD_CSS, CARD_JS
from edicola.header_ui import LOGO
from edicola.product_navigation import PRODUCTS


ROOT = Path(__file__).resolve().parents[1]


def test_classic_blue_red_theme_and_minimal_streamlit_toolbar():
    config = tomllib.loads((ROOT / ".streamlit/config.toml").read_text(encoding="utf-8"))
    assert config["client"]["toolbarMode"] == "minimal"
    theme = config["theme"]
    assert theme["primaryColor"] == COLORS["primary"] == "#0866D9"
    assert COLORS["accent"] == "#E51B2B"
    assert theme["backgroundColor"] == COLORS["paper"]
    assert theme["textColor"] == COLORS["ink"]
    assert theme["borderColor"] == COLORS["border"]


def test_six_full_cards_keep_descriptions_and_accessibility():
    assert ".cards.products{grid-template-columns:repeat(6" in CARD_CSS
    assert ".products .card p{font-size:12px" in CARD_CSS
    assert ".cards.products{display:grid;grid-template-columns:repeat(2" in CARD_CSS
    assert "item.id" in CARD_JS
    assert "aria-current" in CARD_JS
    assert "setTriggerValue('selected'" in CARD_JS
    assert [p["id"] for p in PRODUCTS if p["id"] != "profile"] == [
        "for_you", "archive", "chat", "briefing", "podcast", "explore"
    ]


def test_original_logo_scoped_styles_no_streamlit_dom_overrides():
    assert LOGO.startswith("<svg")
    assert "edi-brand" in page_css()
    assert "data-testid" not in page_css()
    assert "data-testid" not in CARD_CSS
    assert "prefers-reduced-motion" in CARD_CSS
