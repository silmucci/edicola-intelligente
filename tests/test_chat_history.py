"""Conversazioni e PostgreSQL simulati: nessun account, rete o modello reale."""

import json
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from streamlit.testing.v1 import AppTest

from edicola import chat_sessions as sessions
from edicola.chat_data import bounded_context, decode_messages, decode_result
from edicola.chat_store import ChatStore
from edicola.personal_store import PersonalStoreError
from edicola.rag import ask_question, RagResult, Source
from edicola.pdf_viewer import resolve_reference, PdfViewError
from test_chat_ui import RESULT, script, grant
from test_personal_accounts import A, B, backend, auth, accounts_mode, user
from test_pdf_viewer import archive
from test_rag import response


@pytest.fixture
def chats(backend):
    db, actor, _ = backend
    def factory(who=None):
        return ChatStore(who or actor[0], connect=db.connect, identity_provider=lambda: actor[0])
    return db, actor, factory


def turn(question="Ricostruzione?", result=RESULT):
    return dict(id=str(uuid4()), question=question, result=result)


def test_opt_in_multiple_chats_titles_order_and_fresh_connection(chats):
    db, _, factory = chats
    store = factory()
    assert not store.history_enabled() and not db.chat_settings
    with pytest.raises(PersonalStoreError):
        store.create_chat()
    store.set_history_enabled(True)
    one, two = store.create_chat("Ricostruzione"), store.create_chat("Trasporti")
    assert one["id"] != two["id"]
    store.append_turn(one["id"], turn())
    store.rename_chat(one["id"], "Edifici pubblici")
    assert factory().list_chats()[0]["id"] == one["id"]
    restored = factory().load_chat(one["id"])
    assert restored["title"] == "Edifici pubblici" and restored["turns"][0]["result"] == RESULT
    assert restored["created_at"] <= restored["updated_at"]
    assert all(connection.owner is None for connection in db.connections)
    assert any("set_config('edicola.owner_id'" in sql and "true" in sql for sql, _ in db.calls)


def test_atomic_idempotent_messages_sources_export_and_owner_delete(chats):
    db, actor, factory = chats
    store = factory()
    store.set_history_enabled(True)
    chat = store.create_chat()
    result = replace(RESULT, source_references={"S1": {"pdf_sha256": "a" * 64}})
    message = turn(result=result)
    store.append_turn(chat["id"], message)
    store.append_turn(chat["id"], message)
    assert len(db.messages) == 2
    assert factory().load_chat(chat["id"])["turns"][0]["result"] == result
    exported = store.export_data()["chat_history"]
    assert exported["save_new_chats"] and len(exported["messages"]) == 2
    source = exported["messages"][1]["details"]["result"]["sources"][0]
    assert source["filename"] == "a.pdf" and source["page"] == 2
    assert source["chunk_id"] == "chunk-test" and "pdf" not in source
    actor[0] = B
    factory().set_history_enabled(True)
    other = factory().create_chat("Privata B")
    actor[0] = A
    store.delete_all()
    assert not store.list_chats() and not store.history_enabled()
    assert (B.owner_id, other["id"]) in db.chats


def test_owner_guards_cross_chat_read_write_delete_and_stale_identity(chats):
    _, actor, factory = chats
    old_store = factory()
    old_store.set_history_enabled(True)
    cid = old_store.create_chat()["id"]
    actor[0] = B
    current = factory()
    current.set_history_enabled(True)
    assert not current.list_chats()
    for call in (lambda: current.load_chat(cid), lambda: current.rename_chat(cid, "Rubata"),
                 lambda: current.append_turn(cid, turn()), old_store.list_chats):
        with pytest.raises(PersonalStoreError):
            call()
    current.delete_chat(cid)
    current.delete_history()
    actor[0] = A
    assert factory().load_chat(cid)["title"] == "Nuova chat"


def test_disabling_keeps_old_chats_and_blocks_new_writes(chats):
    _, _, factory = chats
    store = factory()
    store.set_history_enabled(True)
    cid = store.create_chat()["id"]
    store.append_turn(cid, turn())
    store.set_history_enabled(False)
    assert len(store.load_chat(cid)["turns"]) == 1
    with pytest.raises(PersonalStoreError):
        store.append_turn(cid, turn())
    with pytest.raises(PersonalStoreError):
        store.create_chat()
    store.rename_chat(cid, "Archivio personale")
    store.delete_chat(cid)
    assert store.list_chats() == []


def test_commit_failure_rollback_safe_error_and_no_false_save(chats):
    db, _, factory = chats
    store = factory()
    store.set_history_enabled(True)
    cid = store.create_chat()["id"]
    db.fail_commit = True
    with pytest.raises(PersonalStoreError) as error:
        store.append_turn(cid, turn())
    assert not db.messages and "password" not in str(error.value)
    with pytest.raises(PersonalStoreError):
        store.set_history_enabled(False)
    db.fail_commit = False
    assert store.history_enabled()
    db.fail = True
    with pytest.raises(PersonalStoreError):
        store.load_chat(cid)


@pytest.mark.parametrize("limit,value", [("MAX_CHATS", 0), ("MAX_TURNS", 0), ("MAX_ACCOUNT_BYTES", 1)])
def test_chat_and_payload_limits(chats, monkeypatch, limit, value):
    _, _, factory = chats
    store = factory()
    store.set_history_enabled(True)
    cid = store.create_chat()["id"]
    monkeypatch.setattr("edicola.chat_store." + limit, value)
    with pytest.raises(PersonalStoreError):
        store.create_chat() if limit == "MAX_CHATS" else store.append_turn(cid, turn())


def test_guest_multiple_chats_switch_rename_delete_no_api(tmp_path):
    with patch("edicola.rag.ask_question", return_value=RESULT) as ask:
        app = AppTest.from_string(script(tmp_path)).run()
        grant(app)
        app.chat_input[0].set_value("Ricostruzione Aquila").run()
        first = app.session_state["rag_active_id"]
        app.button(key="rag_new_chat").click().run()
        assert not app.exception and not app.chat_message and len(app.chat_input) == 1
        app.chat_input[0].set_value("Trasporti Roma").run()
        assert "conversation" not in ask.call_args.kwargs
        app.selectbox(key="rag_chat_selector").set_value(first).run()
        assert not app.exception and len(app.chat_message) == 2
        app.text_input(key="rag_rename_input").set_value("Lavori pubblici").run()
        app.button(key="rag_rename").click().run()
        assert app.session_state["rag_chats"][first]["title"] == "Lavori pubblici"
        assert app.button(key="rag_delete").disabled
        app.checkbox(key="rag_delete_confirm").check().run()
        app.button(key="rag_delete").click().run()
        assert first not in app.session_state["rag_chats"]
        app.checkbox(key="rag_delete_all_confirm").check().run()
        app.button(key="rag_delete_all").click().run()
        assert not app.exception and app.session_state["rag_history"] == []
        assert ask.call_count == 2


def test_follow_up_context_bound_and_independent_chat(tmp_path):
    with patch("edicola.rag.ask_question", return_value=RESULT) as ask:
        app = AppTest.from_string(script(tmp_path)).run()
        grant(app)
        app.chat_input[0].set_value("Ricostruzione all'Aquila?").run()
        app.chat_input[0].set_value("E per gli edifici pubblici?").run()
        context = ask.call_args.kwargs["conversation"]
        assert context[0]["content"] == "Ricostruzione all'Aquila?"
        assert context[1]["content"] == RESULT.answer
        app.run()
        app.button(key="rag_new_chat").click().run()
        app.chat_input[0].set_value("Trasporti?").run()
        assert "conversation" not in ask.call_args.kwargs and ask.call_count == 3
    limited = bounded_context([{"role": "user", "content": "è" * 3000}] * 20)
    assert len(limited) <= 6 and sum(len(m["content"].encode()) for m in limited) <= 4000


def test_saved_chat_new_session_retrieves_sources_without_generating(auth, backend, chats, tmp_path):
    db, actor, factory = chats
    personal = backend[2]
    factory().set_history_enabled(True)
    personal().set_consent("text", "text-v2", True)
    with patch("edicola.chat_sessions.ChatStore", side_effect=lambda _: factory()), patch(
        "edicola.consent.PostgresPersonalStore", side_effect=lambda _: personal()), patch(
        "edicola.rag.ask_question", return_value=RESULT) as ask:
        app = AppTest.from_string(script(tmp_path)).run()
        app.chat_input[0].set_value("Domanda privata A").run()
        cid = app.session_state["rag_active_id"]
        assert not app.exception and len(db.messages) == 2
        fresh = AppTest.from_string(script(tmp_path)).run()
        fresh.selectbox(key="rag_chat_selector").set_value(cid).run()
        assert not fresh.exception and fresh.session_state["rag_history"][0]["result"] == RESULT
        assert len(fresh.chat_message) == 2
        fresh.toggle(key="rag_save_history").set_value(False).run()
        fresh.chat_input[0].set_value("Non salvare questo seguito").run()
        assert not fresh.exception
        assert not fresh.session_state["rag_chats"][fresh.session_state["rag_active_id"]]["saved"]
        assert len(db.messages) == 2
        fresh.toggle(key="rag_save_history").set_value(True).run()
        assert len(db.messages) == 2  # Nessuna importazione implicita.
        actor[0] = B
        with patch("streamlit.user", user(B)):
            fresh.run()
        assert not fresh.exception and not fresh.chat_message
        assert cid not in fresh.session_state["rag_chats"]
        assert ask.call_count == 2


def test_history_choice_is_not_gemini_permission(auth, backend, chats, tmp_path):
    _, _, factory = chats
    with patch("edicola.chat_sessions.ChatStore", side_effect=lambda _: factory()), patch(
        "edicola.consent.PostgresPersonalStore", side_effect=lambda _: backend[2]()), patch("edicola.rag.ask_question") as ask:
        backend[2]().set_consent("text", "text-v1", True)
        app = AppTest.from_string(script(tmp_path)).run()
        assert not app.toggle(key="rag_save_history").value
        app.toggle(key="rag_save_history").set_value(True).run()
        app.chat_input[0].set_value("Domanda").run()
        assert not app.exception and app.button(key="consent_accept")
        ask.assert_not_called()
        app.button(key="consent_refuse").click().run()
        ask.assert_not_called()


def test_saved_cancelled_turn_is_persisted_without_api(auth, backend, chats, tmp_path):
    db, _, factory = chats
    factory().set_history_enabled(True)
    with patch("edicola.chat_sessions.ChatStore", side_effect=lambda _: factory()), patch(
        "edicola.consent.PostgresPersonalStore", side_effect=lambda _: backend[2]()), patch("edicola.rag.ask_question") as ask:
        app = AppTest.from_string(script(tmp_path)).run()
        app.chat_input[0].set_value("Prima domanda in attesa").run()
        cid = app.session_state["rag_active_id"]
        app.button(key="rag_new_chat").click().run()
        assert not app.exception and len(db.messages) == 2
        assert factory().load_chat(cid)["turns"][0]["error"]
        app.selectbox(key="rag_chat_selector").set_value(cid).run()
        assert not app.exception and app.error and len(app.chat_message) == 2
        ask.assert_not_called()


def test_sidebar_title_survives_section_navigation_without_model_call(tmp_path):
    with patch("edicola.rag.ask_question", return_value=RESULT) as ask:
        app = AppTest.from_string(script(tmp_path)).run()
        grant(app)
        app.chat_input[0].set_value("Ricostruzione Aquila").run()
        app.session_state["nav_section"] = "Home"
        app.run()
        app.session_state["nav_section"] = "Chat AI"
        app.run()
        assert not app.exception and app.text_input(key="rag_rename_input").value == "Ricostruzione Aquila"
        ask.assert_called_once()


def test_missing_migration_fails_closed_without_guest_fallback(auth, chats, tmp_path):
    db, _, factory = chats
    db.chat_schema_missing = True
    with patch("edicola.chat_sessions.ChatStore", side_effect=lambda _: factory()), patch("edicola.rag.ask_question") as ask:
        app = AppTest.from_string(script(tmp_path)).run()
        assert not app.exception and app.error and app.chat_input[0].disabled
        assert "rag_chats" not in app.session_state
        ask.assert_not_called()


def test_switch_cancels_pending_consent_without_model_call(tmp_path):
    with patch("edicola.rag.ask_question") as ask:
        app = AppTest.from_string(script(tmp_path)).run()
        app.chat_input[0].set_value("Non ancora autorizzata").run()
        old = app.session_state["rag_active_id"]
        app.button(key="rag_new_chat").click().run()
        assert not app.exception and "rag_pending" not in app.session_state
        assert "consent_pending" not in app.session_state
        app.selectbox(key="rag_chat_selector").set_value(old).run()
        assert app.error and not app.chat_input[0].disabled
        ask.assert_not_called()


@pytest.mark.parametrize("result", [RESULT, None])
def test_failed_save_visible_manual_retry_never_regenerates(auth, backend, chats, tmp_path, result):
    _, _, factory = chats
    factory().set_history_enabled(True)
    backend[2]().set_consent("text", "text-v2", True)
    with patch("edicola.chat_sessions.ChatStore", side_effect=lambda _: factory()), patch(
        "edicola.consent.PostgresPersonalStore", side_effect=lambda _: backend[2]()), patch(
        "edicola.rag.ask_question", return_value=result) as ask, patch.object(
        ChatStore, "append_turn", side_effect=PersonalStoreError("Scrittura non riuscita")) as append:
        if result is None:
            from edicola.rag import RagError
            ask.side_effect = RagError("HTTP 503")
        app = AppTest.from_string(script(tmp_path)).run()
        app.chat_input[0].set_value("Domanda").run()
        assert not app.exception and app.warning
        message = app.session_state["rag_history"][0]
        assert message["save_error"] and append.call_count == 1
        app.run()
        assert append.call_count == 1 and ask.call_count == 1
        append.side_effect = None
        app.button(key=f"rag_retry_save_{message['id']}").click().run()
        assert not app.exception and not app.warning and ask.call_count == 1
        assert append.call_count == 2 and not message.get("save_error")


def test_follow_up_retrieves_fresh_evidence_prior_answer_is_not_grounding(tmp_path):
    source = RESULT.sources[0]
    hit = dict(id=source.chunk_id, filename=source.filename, page=source.page, text=source.text, distance=.2, pdf_sha256="a" * 64)
    context = [{"role": "user", "content": "Novità all'Aquila?"}, {"role": "assistant", "content": "Affermazione vecchia [S99]"}]
    client = Mock()
    client.models.generate_content.return_value = response({"sufficient": True, "claims": [{
        "text": "Progetto annunciato.", "evidence": [{"source_id": "S1", "quote": source.text}]}]})
    with patch("edicola.rag.semantic_search", return_value=[hit]) as search:
        result = ask_question("E gli edifici pubblici?", conversation=context, authorize_external=True, root=tmp_path, client=client)
    assert "Aquila" in search.call_args.args[0] and "edifici pubblici" in search.call_args.args[0]
    prompt = json.loads(client.models.generate_content.call_args.kwargs["contents"])
    assert prompt["conversation_context"] == context and len(prompt["sources"]) == 1
    assert result.used_source_ids == ["S1"] and result.source_references["S1"]["pdf_sha256"] == "a" * 64
    assert result.temporal_notice  # La richiesta di attualità non sparisce nel seguito.
    client.models.generate_content.return_value = response({"sufficient": True, "claims": [{
        "text": "Vecchia affermazione.", "evidence": [{"source_id": "S99", "quote": "Affermazione vecchia"}]}]})
    with patch("edicola.rag.semantic_search", return_value=[hit]):
        assert not ask_question("E poi?", conversation=context, authorize_external=True, root=tmp_path, client=client).sufficient


def test_compact_sources_group_pages_click_exact_page_and_no_technical_name(archive):
    context, prepared = archive
    items = next(p for p in prepared if p.filename == "a.pdf").chunks
    sources = [Source("S1", items[0].id, "a.pdf", 1, items[0].text, .1),
               Source("S2", items[0].id, "a.pdf", 1, items[0].text, .1),
               Source("S3", items[-1].id, "a.pdf", 2, items[-1].text, .2)]
    result = RagResult("Risposta [S1] [S2] [S3]", sources, [s.id for s in sources], True,
                       source_editions={s.id: {"publication": "Testata verificata", "publication_date": None} for s in sources})
    code = '''from edicola.chat_sources import render_sources
from edicola.reading_ui import chat_markdown
from edicola.chat_test_fixture import context, result
render_sources(result,index=0,last=True,root=context.root,context=context,formatter=chat_markdown)
'''
    import types
    fixture = types.ModuleType("edicola.chat_test_fixture")
    fixture.context, fixture.result = context, result
    with patch.dict("sys.modules", {"edicola.chat_test_fixture": fixture}), patch("google.genai.Client") as sdk:
        app = AppTest.from_string(code).run()
        assert not app.exception and len(app.button) == 2
        assert all("a.pdf" not in b.label for b in app.button)
        assert all("Testata verificata" in b.label and b.proto.type == "tertiary" for b in app.button)
        assert "S1/S2" in app.button[0].label
        app.button(key="rag_pdf_S3").click().run()
        assert app.session_state["archive_pdf"] == "a.pdf" and app.session_state["archive_page"] == 2
        sdk.assert_not_called()
    document = resolve_reference(context, "a.pdf", 1, items[0].id)
    with pytest.raises(PdfViewError):
        resolve_reference(context, "a.pdf", 1, items[0].id, pdf_sha256="0" * 64)
    assert resolve_reference(context, "a.pdf", 1, items[0].id, pdf_sha256=document.sha256)


@pytest.mark.parametrize("mutation", ["path", "source_id", "hash", "metadata", "order", "partial"])
def test_invalid_persisted_data_fails_safely(mutation):
    data = asdict(RESULT)
    answer = data.pop("answer")
    if mutation == "path":
        data["sources"][0]["filename"] = "../outside.pdf"
    elif mutation == "source_id":
        data["used_source_ids"] = ["S99"]
    elif mutation == "hash":
        data["source_references"] = {"S1": {"pdf_sha256": "bad"}}
    elif mutation == "metadata":
        data["source_editions"] = {"S1": "not-an-object"}
    with pytest.raises(PersonalStoreError):
        if mutation in {"order", "partial"}:
            rid = str(uuid4())
            rows = [(0, rid, "user", "Domanda", {}), (3, rid, "assistant", answer, {"result": data})]
            decode_messages(rows[:1] if mutation == "partial" else rows)
        else:
            decode_result(answer, {"result": data})


def test_migration_additive_owner_keys_rls_and_no_tokens():
    sql = (Path(__file__).parents[1] / "migrations/004_chat_history.sql").read_text()
    assert sql.count("FORCE ROW LEVEL SECURITY") == 3 and sql.count("WITH CHECK") == 3
    assert "PRIMARY KEY (owner_id,conversation_id,position)" in sql
    assert "FOREIGN KEY (owner_id,conversation_id)" in sql and "ON DELETE CASCADE" in sql
    assert "current_setting('edicola.owner_id',true)" in sql
    assert "TO edicola_app" in sql and "BEGIN;" in sql and "COMMIT;" in sql
    assert "ALTER TABLE edicola_private.profiles" not in sql
