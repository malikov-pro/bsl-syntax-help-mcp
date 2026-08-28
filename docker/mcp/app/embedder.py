from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import EXPECTED_EMBED_DIM, settings
from app.db import connect, get_meta, set_meta, vec_available

log = logging.getLogger("syntax-help.embedder")

_stop = threading.Event()
_worker: threading.Thread | None = None
_last_status = "unknown"


def embedder_health_url() -> str:
    parsed = urlparse(settings.embed_base)
    root = f"{parsed.scheme}://{parsed.netloc}"
    return f"{root}/health"


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if settings.embed_api_key:
        headers["Authorization"] = f"Bearer {settings.embed_api_key}"
    return headers


def probe_embedder() -> dict[str, Any]:
    global _last_status
    info = {
        "url": settings.embed_url,
        "model": settings.embed_model,
        "status": "down",
    }
    try:
        with httpx.Client(timeout=3.0) as client:
            health = client.get(embedder_health_url())
            info["status"] = "up" if health.status_code == 200 else "down"
    except Exception:
        info["status"] = "down"
    _last_status = info["status"]
    return info


def embed_texts(texts: list[str], *, query: bool = False) -> list[list[float]] | None:
    if not texts:
        return []
    payload_texts = [f"{settings.embed_query_prefix}{text}" if query else text for text in texts]
    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                f"{settings.embed_base}/embeddings",
                headers=_headers(),
                json={"input": payload_texts, "model": settings.embed_model},
            )
            response.raise_for_status()
            data = response.json().get("data") or []
            data = sorted(data, key=lambda item: item.get("index", 0))
            vectors = [item["embedding"] for item in data]
            if any(len(vec) != EXPECTED_EMBED_DIM for vec in vectors):
                log.warning("embedder returned unexpected dim; vectors not stored")
                return None
            return vectors
    except Exception as exc:
        log.info("embed request failed: %s", exc)
        return None


def enqueue_layer_embeddings(conn, layer: str) -> int:
    from app.chunking import body_hash, chunk_body

    now = datetime.now(timezone.utc).isoformat()
    rows = conn.execute(
        "SELECT doc_id, layer, body_text, body_hash FROM document_bodies WHERE layer = ?",
        (layer,),
    ).fetchall()
    queued = 0
    for row in rows:
        existing = conn.execute(
            "SELECT body_hash FROM chunks WHERE doc_id = ? AND layer = ? LIMIT 1",
            (row["doc_id"], row["layer"]),
        ).fetchone()
        if existing and existing["body_hash"] == row["body_hash"]:
            continue
        old_ids = [
            item["chunk_id"]
            for item in conn.execute(
                "SELECT chunk_id FROM chunks WHERE doc_id = ? AND layer = ?",
                (row["doc_id"], row["layer"]),
            ).fetchall()
        ]
        if old_ids:
            placeholders = ",".join("?" * len(old_ids))
            conn.execute(f"DELETE FROM chunks WHERE chunk_id IN ({placeholders})", old_ids)
            conn.execute(f"DELETE FROM embed_queue WHERE chunk_id IN ({placeholders})", old_ids)
            if vec_available():
                try:
                    conn.execute(f"DELETE FROM vec_chunks WHERE chunk_id IN ({placeholders})", old_ids)
                except Exception:
                    pass
        digest = row["body_hash"] or body_hash(row["body_text"])
        for chunk_id, n, text in chunk_body(row["doc_id"], row["layer"], row["body_text"]):
            conn.execute(
                "INSERT OR REPLACE INTO chunks(chunk_id, doc_id, layer, n, text, body_hash) VALUES (?, ?, ?, ?, ?, ?)",
                (chunk_id, row["doc_id"], row["layer"], n, text, digest),
            )
            conn.execute(
                "INSERT OR REPLACE INTO embed_queue(chunk_id, status, attempts, last_error, updated_at) VALUES (?, 'pending', 0, NULL, ?)",
                (chunk_id, now),
            )
            queued += 1
    return queued


def _pack_embedding(vector: list[float]):
    try:
        import sqlite_vec

        return sqlite_vec.serialize_float32(vector)
    except Exception:
        return json.dumps(vector)


def _write_vectors(items: list[tuple[str, list[float]]]) -> None:
    if not vec_available() or not items:
        return
    with connect(write=True) as conn:
        stored_dim = get_meta(conn, "expected_dim", str(EXPECTED_EMBED_DIM))
        if stored_dim != str(EXPECTED_EMBED_DIM):
            log.warning("embed_meta dim %s != %s; skip write", stored_dim, EXPECTED_EMBED_DIM)
            return
        set_meta(conn, "embed_model", settings.embed_model)
        now = datetime.now(timezone.utc).isoformat()
        for chunk_id, vector in items:
            conn.execute("DELETE FROM vec_chunks WHERE chunk_id = ?", (chunk_id,))
            conn.execute(
                "INSERT INTO vec_chunks(chunk_id, embedding) VALUES (?, ?)",
                (chunk_id, _pack_embedding(vector)),
            )
            conn.execute(
                "UPDATE embed_queue SET status = 'done', last_error = NULL, updated_at = ? WHERE chunk_id = ?",
                (now, chunk_id),
            )


def _mark_error(chunk_ids: list[str], message: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with connect(write=True) as conn:
        for chunk_id in chunk_ids:
            conn.execute(
                """
                UPDATE embed_queue
                SET attempts = attempts + 1,
                    last_error = ?,
                    status = CASE WHEN attempts + 1 >= 5 THEN 'error' ELSE 'pending' END,
                    updated_at = ?
                WHERE chunk_id = ?
                """,
                (message[:500], now, chunk_id),
            )


def _worker_loop() -> None:
    log.info("embedding worker started")
    while not _stop.is_set():
        if probe_embedder()["status"] != "up" or not vec_available():
            _stop.wait(5)
            continue
        with connect() as conn:
            rows = conn.execute(
                """
                SELECT q.chunk_id, c.text
                FROM embed_queue q
                JOIN chunks c ON c.chunk_id = q.chunk_id
                WHERE q.status IN ('pending', 'error')
                ORDER BY CASE q.status WHEN 'pending' THEN 0 ELSE 1 END, q.updated_at
                LIMIT 8
                """
            ).fetchall()
        if not rows:
            _stop.wait(2)
            continue
        texts = [row["text"] for row in rows]
        ids = [row["chunk_id"] for row in rows]
        vectors = embed_texts(texts, query=False)
        if vectors is None or len(vectors) != len(ids):
            _mark_error(ids, "embed request failed")
            _stop.wait(5)
            continue
        try:
            _write_vectors(list(zip(ids, vectors, strict=True)))
        except Exception as exc:
            log.exception("failed to store vectors")
            _mark_error(ids, str(exc))
            time.sleep(1)


def start_worker() -> None:
    global _worker
    if _worker and _worker.is_alive():
        return
    _stop.clear()
    _worker = threading.Thread(target=_worker_loop, name="embed-worker", daemon=True)
    _worker.start()


def stop_worker() -> None:
    _stop.set()
    if _worker:
        _worker.join(timeout=2)
