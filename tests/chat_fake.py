"""Catalogo chat simulato per verificare le query reali del CRUD, senza PostgreSQL."""

import json
from datetime import datetime, timezone


def execute_chat(db, sql, params, current_owner):
    owner = params[1] if sql.startswith("UPDATE") and "SET title=" in sql else params[0]
    assert owner == current_owner, "Accesso SQL a un altro proprietario"
    if getattr(db, "chat_schema_missing", False):
        raise RuntimeError("private-schema-missing")
    stamp = datetime.now(timezone.utc)
    if "chat_settings" in sql:
        if sql.startswith("INSERT"):
            db.chat_settings[owner] = params[1]
            return []
        return [(db.chat_settings[owner],)] if owner in db.chat_settings else []
    if "conversations" in sql:
        if sql.startswith("SELECT count"):
            return [(sum(who == owner for who, _ in db.chats),)]
        if sql.startswith("INSERT"):
            db.chats[(owner, params[1])] = dict(title=params[2], created_at=stamp, updated_at=stamp)
            return [(stamp, stamp)]
        if sql.startswith("UPDATE"):
            cid = params[2] if "SET title=" in sql else params[1]
            chat = db.chats.get((owner, cid))
            if chat is None:
                return []
            if "SET title=" in sql:
                chat["title"] = params[0]
            chat["updated_at"] = stamp
            return [(cid,)]
        if sql.startswith("DELETE"):
            ids = [cid for who, cid in db.chats if who == owner and (len(params) == 1 or cid == params[1])]
            for cid in ids:
                db.chats.pop((owner, cid))
                db.messages = {key: value for key, value in db.messages.items() if key[:2] != (owner, cid)}
            return []
        if len(params) == 2:
            row = db.chats.get((owner, params[1]))
            if row is None:
                return []
            return [(params[1],)] if sql.startswith("SELECT id FROM") else [(row["title"], row["created_at"], row["updated_at"])]
        rows = [(cid, c["title"], c["created_at"], c["updated_at"]) for (who, cid), c in db.chats.items() if who == owner]
        return sorted(rows, key=lambda row: (row[3], row[0]), reverse=True)[:200]
    if sql.startswith("INSERT"):
        _, cid, position, request, role, content, details = params
        assert (owner, cid) in db.chats
        assert (owner, cid, position) not in db.messages
        db.messages[(owner, cid, position)] = (request, role, content, json.loads(details))
        return []
    rows = [(cid, pos, *message) for (who, cid, pos), message in db.messages.items() if who == owner]
    if "COALESCE(sum" in sql:
        return [(sum(len((row[4] + json.dumps(row[5])).encode()) for row in rows),)]
    if len(params) >= 2:
        rows = [row for row in rows if row[0] == params[1]]
    if len(params) == 3:
        rows = [row for row in rows if row[2] == params[2]]
    if sql.startswith("SELECT count"):
        return [(len(rows),)]
    rows.sort(key=lambda row: (row[0], row[1]))
    return [row[1:] for row in rows][:200] if sql.startswith("SELECT position") else rows[:40000]
