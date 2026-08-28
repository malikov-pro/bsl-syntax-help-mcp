from __future__ import annotations

import json
import time
import uuid
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field

from app.chunking import body_hash
from app.config import MAX_BATCH_CARDS, SESSION_TTL_SECONDS
from app.db import committed_layers, connect, rebuild_fts, reset_database
from app.embedder import enqueue_layer_embeddings


class Card(BaseModel):
    doc_id: str
    layer: str
    kind: str
    full_name_ru: str
    body_text: str
    object_ru: str | None = None
    object_en: str | None = None
    member_ru: str | None = None
    member_en: str | None = None
    full_name_en: str | None = None
    introduced_in: str | None = None
    availability: str | None = None
    syntax: str | None = None
    aliases: list[str] = Field(default_factory=list)


class BeginRequest(BaseModel):
    layer: str


class BatchesRequest(BaseModel):
    session_id: str
    cards: list[Card]


class SessionRequest(BaseModel):
    session_id: str


class ConfirmRequest(BaseModel):
    confirm: bool = False


def _expire_sessions(conn) -> None:
    cutoff = time.time() - SESSION_TTL_SECONDS
    stale = conn.execute(
        "SELECT session_id FROM ingest_sessions WHERE status = 'open' AND created_at < ?",
        (cutoff,),
    ).fetchall()
    for row in stale:
        conn.execute("UPDATE ingest_sessions SET status = 'aborted' WHERE session_id = ?", (row["session_id"],))
        conn.execute("DELETE FROM ingest_cards WHERE session_id = ?", (row["session_id"],))


def _require_open_session(conn, session_id: str) -> Any:
    _expire_sessions(conn)
    row = conn.execute("SELECT * FROM ingest_sessions WHERE session_id = ?", (session_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="session not found")
    if row["status"] != "open":
        raise HTTPException(status_code=409, detail=f"session is {row['status']}")
    if time.time() - row["created_at"] > SESSION_TTL_SECONDS:
        conn.execute("UPDATE ingest_sessions SET status = 'aborted' WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM ingest_cards WHERE session_id = ?", (session_id,))
        raise HTTPException(status_code=410, detail="session expired")
    return row


def begin_ingest(layer: str) -> dict[str, str]:
    layer = layer.strip()
    if not layer:
        raise HTTPException(status_code=400, detail="layer is required")
    session_id = str(uuid.uuid4())
    now = time.time()
    with connect(write=True) as conn:
        _expire_sessions(conn)
        previous = conn.execute(
            "SELECT session_id FROM ingest_sessions WHERE layer = ? AND status = 'open'",
            (layer,),
        ).fetchall()
        for row in previous:
            conn.execute("UPDATE ingest_sessions SET status = 'aborted' WHERE session_id = ?", (row["session_id"],))
            conn.execute("DELETE FROM ingest_cards WHERE session_id = ?", (row["session_id"],))
        conn.execute(
            "INSERT INTO ingest_sessions(session_id, layer, created_at, status) VALUES (?, ?, ?, 'open')",
            (session_id, layer, now),
        )
    return {"session_id": session_id, "layer": layer}


def add_batches(session_id: str, cards: list[Card]) -> dict[str, Any]:
    if len(cards) > MAX_BATCH_CARDS:
        raise HTTPException(status_code=400, detail=f"max {MAX_BATCH_CARDS} cards per batch")
    with connect(write=True) as conn:
        session = _require_open_session(conn, session_id)
        accepted = 0
        for card in cards:
            if card.layer != session["layer"]:
                raise HTTPException(
                    status_code=400,
                    detail=f"card layer {card.layer!r} does not match session layer {session['layer']!r}",
                )
            conn.execute(
                "INSERT OR REPLACE INTO ingest_cards(session_id, doc_id, payload) VALUES (?, ?, ?)",
                (session_id, card.doc_id, card.model_dump_json()),
            )
            accepted += 1
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM ingest_cards WHERE session_id = ?",
            (session_id,),
        ).fetchone()["n"]
    return {"session_id": session_id, "accepted": accepted, "total": total}


def abort_ingest(session_id: str) -> dict[str, Any]:
    with connect(write=True) as conn:
        session = _require_open_session(conn, session_id)
        conn.execute("UPDATE ingest_sessions SET status = 'aborted' WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM ingest_cards WHERE session_id = ?", (session_id,))
    return {"session_id": session_id, "layer": session["layer"], "aborted": True}


def commit_ingest(session_id: str) -> dict[str, Any]:
    with connect(write=True) as conn:
        session = _require_open_session(conn, session_id)
        layer = session["layer"]
        rows = conn.execute(
            "SELECT payload FROM ingest_cards WHERE session_id = ?",
            (session_id,),
        ).fetchall()
        cards = [Card.model_validate_json(row["payload"]) for row in rows]

        conn.execute("DELETE FROM document_bodies WHERE layer = ?", (layer,))
        conn.execute("DELETE FROM layer_members WHERE layer = ?", (layer,))

        for card in cards:
            conn.execute(
                """
                INSERT INTO documents(
                    doc_id, kind, full_name_ru, full_name_en, object_ru, object_en,
                    member_ru, member_en, introduced_in, availability, syntax
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(doc_id) DO UPDATE SET
                    kind = excluded.kind,
                    full_name_ru = excluded.full_name_ru,
                    full_name_en = excluded.full_name_en,
                    object_ru = excluded.object_ru,
                    object_en = excluded.object_en,
                    member_ru = excluded.member_ru,
                    member_en = excluded.member_en,
                    introduced_in = excluded.introduced_in,
                    availability = excluded.availability,
                    syntax = excluded.syntax
                """,
                (
                    card.doc_id,
                    card.kind,
                    card.full_name_ru,
                    card.full_name_en,
                    card.object_ru,
                    card.object_en,
                    card.member_ru,
                    card.member_en,
                    card.introduced_in,
                    card.availability,
                    card.syntax,
                ),
            )
            conn.execute(
                "INSERT INTO document_bodies(doc_id, layer, body_text, body_hash) VALUES (?, ?, ?, ?)",
                (card.doc_id, layer, card.body_text, body_hash(card.body_text)),
            )
            conn.execute(
                "INSERT INTO layer_members(layer, doc_id) VALUES (?, ?)",
                (layer, card.doc_id),
            )
            conn.execute("DELETE FROM aliases WHERE doc_id = ?", (card.doc_id,))
            for alias in card.aliases:
                alias = alias.strip()
                if alias:
                    conn.execute(
                        "INSERT OR IGNORE INTO aliases(doc_id, alias) VALUES (?, ?)",
                        (card.doc_id, alias),
                    )

        rebuild_fts(conn)
        queued = enqueue_layer_embeddings(conn, layer)
        conn.execute("UPDATE ingest_sessions SET status = 'committed' WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM ingest_cards WHERE session_id = ?", (session_id,))
        layers = committed_layers(conn)

    return {
        "session_id": session_id,
        "layer": layer,
        "documents": len(cards),
        "bodies": len(cards),
        "queued_chunks": queued,
        "layers": layers,
        "fts_ready": True,
    }


def delete_layer(layer: str) -> dict[str, Any]:
    with connect(write=True) as conn:
        chunk_ids = [
            row["chunk_id"]
            for row in conn.execute("SELECT chunk_id FROM chunks WHERE layer = ?", (layer,)).fetchall()
        ]
        conn.execute("DELETE FROM document_bodies WHERE layer = ?", (layer,))
        conn.execute("DELETE FROM layer_members WHERE layer = ?", (layer,))
        conn.execute("DELETE FROM chunks WHERE layer = ?", (layer,))
        if chunk_ids:
            placeholders = ",".join("?" * len(chunk_ids))
            conn.execute(f"DELETE FROM embed_queue WHERE chunk_id IN ({placeholders})", chunk_ids)
            try:
                conn.execute(f"DELETE FROM vec_chunks WHERE chunk_id IN ({placeholders})", chunk_ids)
            except Exception:
                pass
        rebuild_fts(conn)
        leftover_docs = {
            row["doc_id"]
            for row in conn.execute("SELECT DISTINCT doc_id FROM document_bodies").fetchall()
        }
        for row in conn.execute("SELECT doc_id FROM documents").fetchall():
            if row["doc_id"] not in leftover_docs:
                conn.execute("DELETE FROM aliases WHERE doc_id = ?", (row["doc_id"],))
                conn.execute("DELETE FROM documents WHERE doc_id = ?", (row["doc_id"],))
        layers = committed_layers(conn)
    return {"deleted_layer": layer, "layers": layers}


def wipe_database(confirm: bool) -> dict[str, Any]:
    if not confirm:
        raise HTTPException(status_code=400, detail="confirm must be true")
    reset_database()
    return {"wiped": True}
