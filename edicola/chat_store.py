"""CRUD chat: riusa connessione, ownership, SET LOCAL e controlli del personal store."""

import json
from uuid import uuid4

from edicola.chat_data import MAX_CHATS, MAX_TURNS, MAX_ACCOUNT_BYTES, identifier, encode_turn, decode_messages
from edicola.personal_store import PostgresPersonalStore, PersonalStoreError


class ChatStore(PostgresPersonalStore):
    def history_enabled(self):
        with self.transaction() as (db, owner):
            row = db.execute("SELECT enabled FROM edicola_private.chat_settings WHERE owner_id=%s", (owner,)).fetchone()
        return row[0] if row else False

    def set_history_enabled(self, enabled):
        if type(enabled) is not bool:
            raise ValueError("Scelta di salvataggio non valida.")
        with self.transaction() as (db, owner):
            self.ensure_profile(db, owner)
            db.execute("INSERT INTO edicola_private.chat_settings(owner_id,enabled) VALUES (%s,%s) "
                       "ON CONFLICT(owner_id) DO UPDATE SET enabled=excluded.enabled", (owner, enabled))

    def list_chats(self):
        with self.transaction() as (db, owner):
            rows = db.execute("SELECT id,title,created_at,updated_at FROM edicola_private.conversations WHERE owner_id=%s "
                              "ORDER BY updated_at DESC,id LIMIT 200", (owner,)).fetchall()
        return [dict(id=str(cid), title=title, created_at=created.isoformat(), updated_at=updated.isoformat(), saved=True)
                for cid, title, created, updated in rows]

    def create_chat(self, title="Nuova chat"):
        title = self.checked_title(title)
        with self.transaction() as (db, owner):
            self.ensure_profile(db, owner)
            db.execute("SELECT owner_id FROM edicola_private.profiles WHERE owner_id=%s FOR UPDATE", (owner,)).fetchone()
            self.require_enabled(db, owner)
            count = db.execute("SELECT count(*) FROM edicola_private.conversations WHERE owner_id=%s", (owner,)).fetchone()[0]
            if count >= MAX_CHATS:
                raise PersonalStoreError("La cronologia è piena. Elimina alcune chat o usa una conversazione temporanea.")
            cid = str(uuid4())
            row = db.execute("INSERT INTO edicola_private.conversations(owner_id,id,title) VALUES (%s,%s,%s) "
                             "RETURNING created_at,updated_at", (owner, cid, title)).fetchone()
        return dict(id=cid, title=title, created_at=row[0].isoformat(), updated_at=row[1].isoformat(), saved=True, turns=[])

    @staticmethod
    def require_enabled(db, owner):
        row = db.execute("SELECT enabled FROM edicola_private.chat_settings WHERE owner_id=%s FOR SHARE", (owner,)).fetchone()
        if not row or row[0] is not True:
            raise PersonalStoreError("Il salvataggio delle nuove conversazioni è disattivato.")

    @staticmethod
    def checked_title(title):
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 80:
            raise ValueError("Usa un titolo da 1 a 80 caratteri.")
        return title.strip()

    def load_chat(self, chat_id):
        cid = identifier(chat_id)
        with self.transaction(repeatable=True) as (db, owner):
            row = db.execute("SELECT title,created_at,updated_at FROM edicola_private.conversations WHERE owner_id=%s AND id=%s",
                             (owner, cid)).fetchone()
            if row is None:
                raise PersonalStoreError("Conversazione non disponibile per questo account.")
            messages = db.execute("SELECT position,request_id,role,content,details FROM edicola_private.chat_messages "
                                  "WHERE owner_id=%s AND conversation_id=%s ORDER BY position LIMIT 200", (owner, cid)).fetchall()
        return dict(id=cid, title=row[0], created_at=row[1].isoformat(), updated_at=row[2].isoformat(),
                    saved=True, turns=decode_messages(messages))

    def rename_chat(self, chat_id, title):
        cid, title = identifier(chat_id), self.checked_title(title)
        with self.transaction() as (db, owner):
            row = db.execute("UPDATE edicola_private.conversations SET title=%s,updated_at=now() WHERE owner_id=%s AND id=%s RETURNING id",
                             (title, owner, cid)).fetchone()
            if row is None:
                raise PersonalStoreError("Conversazione non disponibile per questo account.")

    def delete_chat(self, chat_id):
        with self.transaction() as (db, owner):
            db.execute("DELETE FROM edicola_private.conversations WHERE owner_id=%s AND id=%s", (owner, identifier(chat_id)))

    def delete_history(self):
        with self.transaction() as (db, owner):
            db.execute("DELETE FROM edicola_private.conversations WHERE owner_id=%s", (owner,))

    def append_turn(self, chat_id, turn):
        cid, request = identifier(chat_id), identifier(turn["id"])
        question, answer, details = encode_turn(turn)
        with self.transaction() as (db, owner):
            # Stesso lock per creazione/quota e append: niente sequenze o quote concorrenti incoerenti.
            db.execute("SELECT owner_id FROM edicola_private.profiles WHERE owner_id=%s FOR UPDATE", (owner,)).fetchone()
            self.require_enabled(db, owner)
            row = db.execute("SELECT id FROM edicola_private.conversations WHERE owner_id=%s AND id=%s FOR UPDATE", (owner, cid)).fetchone()
            if row is None:
                raise PersonalStoreError("Conversazione non disponibile per questo account.")
            exists = db.execute("SELECT count(*) FROM edicola_private.chat_messages WHERE owner_id=%s AND conversation_id=%s AND request_id=%s",
                                (owner, cid, request)).fetchone()[0]
            if exists == 2:
                return  # Invio già committato: nessun duplicato, anche dopo retry del solo salvataggio.
            if exists:
                raise PersonalStoreError("Messaggi salvati incompleti: nessuna sovrascrittura.")
            position = db.execute("SELECT count(*) FROM edicola_private.chat_messages WHERE owner_id=%s AND conversation_id=%s",
                                  (owner, cid)).fetchone()[0]
            if position >= MAX_TURNS * 2:
                raise PersonalStoreError("Questa conversazione è completa. Avvia una nuova chat.")
            size = db.execute("SELECT COALESCE(sum(octet_length(content)+octet_length(details::text)),0) "
                              "FROM edicola_private.chat_messages WHERE owner_id=%s", (owner,)).fetchone()[0]
            if size + len((question + answer + details).encode("utf-8")) > MAX_ACCOUNT_BYTES:
                raise PersonalStoreError("Lo spazio della cronologia è esaurito. Elimina alcune chat o usa una chat temporanea.")
            for offset, role, content, payload in [(0, "user", question, "{}"), (1, "assistant", answer, details)]:
                db.execute("INSERT INTO edicola_private.chat_messages(owner_id,conversation_id,position,request_id,role,content,details) "
                           "VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)", (owner, cid, position + offset, request, role, content, payload))
            db.execute("UPDATE edicola_private.conversations SET updated_at=now() WHERE owner_id=%s AND id=%s", (owner, cid))

    @staticmethod
    def export_history(db, owner):
        settings = db.execute("SELECT enabled FROM edicola_private.chat_settings WHERE owner_id=%s", (owner,)).fetchone()
        chats = db.execute("SELECT id,title,created_at,updated_at FROM edicola_private.conversations WHERE owner_id=%s ORDER BY updated_at DESC,id LIMIT 200", (owner,)).fetchall()
        rows = db.execute("SELECT conversation_id,position,request_id,role,content,details FROM edicola_private.chat_messages "
                          "WHERE owner_id=%s ORDER BY conversation_id,position LIMIT 40000", (owner,)).fetchall()
        return {"save_new_chats": settings[0] if settings else False,
                "conversations": [{"id": str(cid), "title": title, "created_at": created.isoformat(), "updated_at": updated.isoformat()} for cid, title, created, updated in chats],
                "messages": [{"conversation_id": str(cid), "position": pos, "request_id": str(rid), "role": role, "content": text, "details": details}
                             for cid, pos, rid, role, text, details in rows]}
