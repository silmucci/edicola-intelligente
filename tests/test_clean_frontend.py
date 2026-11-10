"""Smoke test del restyling: nessuna modifica alla logica editoriale o alla AI."""

from pathlib import Path
import tomllib

from edicola.design_tokens import APP_SHELL_CSS, COLORS, app_shell_css, page_css
from edicola.editorial_components import CARD_CSS, CARD_JS
from edicola.product_navigation import PRODUCTS


ROOT = Path(__file__).resolve().parents[1]


def test_minimal_native_toolbar_and_consistent_palette():
    config = tomllib.loads((ROOT / ".streamlit/config.toml").read_text(encoding="utf-8"))
    assert config["client"]["toolbarMode"] == "minimal"
    theme = config["theme"]
    assert theme["primaryColor"] == COLORS["primary"]
    assert theme["backgroundColor"] == COLORS["paper"]
    assert theme["textColor"] == COLORS["ink"]
    assert theme["borderColor"] == COLORS["border"]


def test_chrome_css_is_separate_from_editorial_components():
    css = app_shell_css()
    assert css == APP_SHELL_CSS
    assert '[data-testid="stToolbar"]' in css
    assert '[data-testid="stHeader"]' in css
    assert '[data-testid="stMainBlockContainer"]' in css
    assert "data-testid" not in page_css()
    assert "data-testid" not in CARD_CSS
    assert "prefers-reduced-motion" in CARD_CSS


def test_compact_navigation_preserves_actions_and_accessibility():
    assert ".cards.products{display:flex" in CARD_CSS
    assert ".products .card p,.products .arrow{display:none}" in CARD_CSS
    assert "overflow-x:auto" in CARD_CSS
    assert "item.id" in CARD_JS
    assert "aria-current" in CARD_JS
    assert "setTriggerValue('selected'" in CARD_JS
    assert [p["id"] for p in PRODUCTS if p["id"] != "profile"] == [
        "archive", "home", "chat", "briefing", "timeline", "map", "podcast"
    ]
