"""Chat a singolo composer, rendering sicuro e invii espliciti; nessuna API reale."""

from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from edicola.rag import RagError, RagResult, Source
from edicola.reading_ui import chat_markdown, _finish_chat_turn
from test_personal_accounts import accounts_mode, auth, backend, B, user


RESULT = RagResult("L'articolo documenta un progetto. [S1]", [
    Source("S1", "chunk-test", "a.pdf", 2, "Il progetto è stato annunciato dal Comune.", .2)
], ["S1"], True, source_editions={"S1": {"publication": "Quotidiano di prova", "publication_date": "2026-10-17"}})


def script(root):
    return f"from pathlib import Path\nfrom edicola.reading_ui import render_chat\nrender_chat(Path({str(root)!r}), None)"


def grant(app):
    app.session_state["consent_choices"] = {("text", "text-v2"): True}


@pytest.mark.parametrize("text", ["dell'Aquila", "dell&#x27;Aquila", "dell&amp;#x27;Aquila", "dell’Aquila"])
def test_italian_apostrophes_and_legacy_entities_are_readable(text):
    rendered = chat_markdown(text)
    assert rendered in ("dell'Aquila", "dell’Aquila")
    assert "&#" not in rendered


@pytest.mark.parametrize("text", [
    '<script>alert("x")</script>', '&lt;img src=x onerror=alert(1)&gt;',
    '[clicca](javascript:alert(1))', '![foto](https://example.test/pixel)',
    '<a href="https://example.test">link</a>',
])
def test_untrusted_html_links_and_images_remain_text(text):
    rendered = chat_markdown(text)
    assert "<script>" not in rendered and "<img" not in rendered and "<a " not in rendered
    assert "[clicca](" not in rendered and "![foto](" not in rendered


def test_only_validated_citations_become_navigation_links():
    rendered = chat_markdown("Fatto [S1], falso [S99]. [clicca](https://example.test)", cited=["S1"], anchor="rag-fonti-0")
    assert "[S1](#rag-fonti-0)" in rendered
    assert "[S99](" not in rendered and "[clicca](" not in rendered


def test_one_composer_no_form_or_external_calls_at_start(tmp_path):
    with patch("edicola.rag.ask_question") as ask, patch("google.genai.Client", side_effect=AssertionError("API vietate")):
        app = AppTest.from_string(script(tmp_path)).run()
        assert not app.exception and len(app.chat_input) == 1
        assert not app.main.text_input and not app.get("form")
        assert not any(b.key == "rag_submit" for b in app.button)
        assert app.chat_input[0].proto.submit_mode and not app.chat_input[0].disabled
        app.run()
        ask.assert_not_called()


def test_question_visible_before_consent_then_resumed_once(tmp_path):
    with patch("edicola.rag.ask_question", return_value=RESULT) as ask:
        app = AppTest.from_string(script(tmp_path)).run()
        app.chat_input[0].set_value("Novità per le case dell'Aquila?").run()
        ask.assert_not_called()
        assert app.chat_message[0].name == "user" and len(app.chat_message) == 1
        assert any("dell'Aquila" in item.value for item in app.markdown)
        assert app.chat_input[0].disabled
        app.button(key="consent_accept").click().run()
        assert not app.exception and len(app.chat_message) == 2
        assert [m.name for m in app.chat_message] == ["user", "assistant"]
        assert not app.chat_input[0].disabled
        assert "rag_pending" not in app.session_state
        assert all("&#x27;" not in item.value for item in app.markdown)
        assert all(not item.proto.allow_html for item in app.markdown)
        app.run()
        ask.assert_called_once()


def test_refusal_leaves_question_and_never_calls_rag(tmp_path):
    with patch("edicola.rag.ask_question") as ask:
        app = AppTest.from_string(script(tmp_path)).run()
        app.chat_input[0].set_value("Domanda senza consenso").run()
        app.button(key="consent_refuse").click().run()
        assert not app.exception and app.chat_message[0].name == "user" and app.error
        assert not app.chat_input[0].disabled
        app.run()
        ask.assert_not_called()


def test_closing_consent_does_not_repeat_request(tmp_path):
    with patch("edicola.rag.ask_question") as ask:
        app = AppTest.from_string(script(tmp_path)).run()
        app.chat_input[0].set_value("Una domanda").run()
        del app.session_state["consent_pending"]  # Effetto del callback on_dismiss.
        app.run()
        assert not app.exception and "rag_pending" not in app.session_state
        assert not app.chat_input[0].disabled
        ask.assert_not_called()


def test_sources_include_verified_metadata_original_text_and_pdf_route(tmp_path):
    with patch("edicola.rag.ask_question", return_value=RESULT), patch("edicola.chat_sources.source_button") as open_pdf:
        app = AppTest.from_string(script(tmp_path)).run()
        grant(app)
        app.chat_input[0].set_value("Progetto?").run()
        assert not app.exception and not app.main.expander
        assert len(app.get("popover")) == 1
        assert any(x.value == RESULT.sources[0].text for x in app.text)
        assert all("a.pdf" not in x.value for x in app.text)
        assert "Quotidiano di prova" in open_pdf.call_args.kwargs["label"]
        assert "2026-10-17" in open_pdf.call_args.kwargs["help_text"]
        assert open_pdf.call_args.args == ("a.pdf", 2)
        assert open_pdf.call_args.kwargs["chunk_id"] == "chunk-test"


def test_error_keeps_order_and_never_retries_on_rerun(tmp_path):
    with patch("edicola.rag.ask_question", side_effect=[RESULT, RagError("HTTP 503")]) as ask:
        app = AppTest.from_string(script(tmp_path)).run()
        grant(app)
        app.chat_input[0].set_value("Prima domanda").run()
        app.chat_input[0].set_value("Seconda domanda").run()
        assert not app.exception and app.error and len(app.chat_message) == 4
        assert [t["question"] for t in app.session_state["rag_history"]] == ["Prima domanda", "Seconda domanda"]
        assert app.session_state["rag_history"][0]["result"] == RESULT
        assert app.session_state["rag_history"][1]["result"] is None
        app.run()
        assert ask.call_count == 2


def test_guest_history_keeps_ten_turns_in_session_only(tmp_path):
    with patch("edicola.rag.ask_question", return_value=RagResult("Nessuna informazione.", [], [], False)):
        app = AppTest.from_string(script(tmp_path)).run()
        grant(app)
        for i in range(10):
            app.chat_input[0].set_value(f"Domanda {i}").run()
        assert not app.exception and len(app.session_state["rag_history"]) == 10
        assert app.session_state["rag_history"][0]["question"] == "Domanda 0"
        new = AppTest.from_string(script(tmp_path)).run()
        assert new.session_state["rag_history"] == []


def test_identity_change_clears_chat_and_pending(auth, backend, tmp_path):
    db, actor, factory = backend
    from edicola.chat_store import ChatStore
    factory().set_consent("text", "text-v2", True)
    with patch("edicola.chat_sessions.ChatStore", side_effect=lambda _: ChatStore(actor[0], connect=db.connect, identity_provider=lambda: actor[0])), patch("edicola.consent.PostgresPersonalStore", side_effect=lambda _: factory()), patch("edicola.rag.ask_question", return_value=RESULT) as ask:
        app = AppTest.from_string(script(tmp_path)).run()
        app.chat_input[0].set_value("Domanda privata A").run()
        actor[0] = B
        with patch("streamlit.user", user(B)):
            app.run()
        assert not app.exception and not app.chat_message
        assert app.session_state["rag_history"] == [] and "rag_pending" not in app.session_state
        ask.assert_called_once()


def test_late_result_cannot_consume_another_users_pending_request():
    state = {"rag_pending": {"id": "new", "owner": "b"},
             "rag_history": [{"id": "new", "question": "Domanda B", "result": None}]}
    with patch("streamlit.session_state", state), patch("edicola.consent.actor", return_value="b"):
        assert not _finish_chat_turn({"id": "old", "owner": "a"}, result=RESULT)
    assert state["rag_pending"]["id"] == "new" and state["rag_history"][0]["result"] is None


def test_interrupted_turn_is_not_automatically_retried(tmp_path):
    with patch("edicola.rag.ask_question") as ask:
        app = AppTest.from_string(script(tmp_path)).run()
        app.chat_input[0].set_value("Domanda interrotta").run()
        pending = dict(app.session_state["rag_pending"])
        pending["running"] = True
        app.session_state["rag_pending"] = pending
        del app.session_state["consent_pending"]
        app.run()
        assert not app.exception and "rag_pending" not in app.session_state
        assert not app.chat_input[0].disabled and app.error
        ask.assert_not_called()
