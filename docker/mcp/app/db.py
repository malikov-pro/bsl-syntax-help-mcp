from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.config import EXPECTED_EMBED_DIM, settings

_write_lock = threading.RLock()
_vec_available = False


def vec_available() -> bool:
    return _vec_available


def _connect(readonly: bool = False) -> sqlite3.Connection:
    path = Path(settings.db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    uri = f"file:{path}?mode=ro" if readonly and path.exists() else str(path)
    conn = sqlite3.connect(uri if readonly and path.exists() else str(path), check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    _try_load_vec(conn)
    return conn


def _try_load_vec(conn: sqlite3.Connection) -> None:
    global _vec_available
    try:
        conn.enable_load_extension(True)
        import sqlite_vec

        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        _vec_available = True
    except Exception:
        _vec_available = False


@contextmanager
def connect(*, write: bool = False) -> Iterator[sqlite3.Connection]:
    if write:
        with _write_lock:
            conn = _connect()
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
    else:
        conn = _connect()
        try:
            yield conn
        finally:
            conn.close()


def get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM embed_meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO embed_meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def init_db() -> None:
    with connect(write=True) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                doc_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                full_name_ru TEXT NOT NULL,
                full_name_en TEXT,
                object_ru TEXT,
                object_en TEXT,
                member_ru TEXT,
                member_en TEXT,
                introduced_in TEXT,
                availability TEXT,
                syntax TEXT
            );

            CREATE TABLE IF NOT EXISTS document_bodies (
                doc_id TEXT NOT NULL,
                layer TEXT NOT NULL,
                body_text TEXT NOT NULL,
                body_hash TEXT NOT NULL,
                PRIMARY KEY (doc_id, layer)
            );

            CREATE TABLE IF NOT EXISTS layer_members (
                layer TEXT NOT NULL,
                doc_id TEXT NOT NULL,
                PRIMARY KEY (layer, doc_id)
            );

            CREATE TABLE IF NOT EXISTS aliases (
                doc_id TEXT NOT NULL,
                alias TEXT NOT NULL,
                PRIMARY KEY (doc_id, alias)
            );

            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id TEXT PRIMARY KEY,
                doc_id TEXT NOT NULL,
                layer TEXT NOT NULL,
                n INTEGER NOT NULL,
                text TEXT NOT NULL,
                body_hash TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS embed_queue (
                chunk_id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS embed_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS ingest_sessions (
                session_id TEXT PRIMARY KEY,
                layer TEXT NOT NULL,
                created_at REAL NOT NULL,
                status TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS ingest_cards (
                session_id TEXT NOT NULL,
                doc_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY (session_id, doc_id)
            );

            CREATE INDEX IF NOT EXISTS idx_bodies_layer ON document_bodies(layer);
            CREATE INDEX IF NOT EXISTS idx_members_layer ON layer_members(layer);
            CREATE INDEX IF NOT EXISTS idx_chunks_doc_layer ON chunks(doc_id, layer);
            CREATE INDEX IF NOT EXISTS idx_queue_status ON embed_queue(status);
            """
        )
        conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
                doc_id UNINDEXED,
                layer UNINDEXED,
                full_name_ru,
                full_name_en,
                object_ru,
                member_ru,
                aliases,
                body_text,
                tokenize = 'unicode61'
            )
            """
        )
        if _vec_available:
            try:
                conn.execute(
                    f"""
                    CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
                        chunk_id TEXT PRIMARY KEY,
                        embedding float[{EXPECTED_EMBED_DIM}]
                    )
                    """
                )
            except sqlite3.OperationalError:
                conn.execute(
                    f"""
                    CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
                        embedding float[{EXPECTED_EMBED_DIM}]
                    )
                    """
                )
        if get_meta(conn, "fts_ready") is None:
            set_meta(conn, "fts_ready", "1")
        set_meta(conn, "expected_dim", str(EXPECTED_EMBED_DIM))
        set_meta(conn, "embed_model", settings.embed_model)


def rebuild_fts(conn: sqlite3.Connection) -> None:
    set_meta(conn, "fts_ready", "0")
    conn.execute("DELETE FROM documents_fts")
    conn.execute(
        """
        INSERT INTO documents_fts(
            doc_id, layer, full_name_ru, full_name_en, object_ru, member_ru, aliases, body_text
        )
        SELECT
            b.doc_id,
            b.layer,
            d.full_name_ru,
            IFNULL(d.full_name_en, ''),
            IFNULL(d.object_ru, ''),
            IFNULL(d.member_ru, ''),
            IFNULL((
                SELECT group_concat(a.alias, ' ')
                FROM aliases a
                WHERE a.doc_id = d.doc_id
            ), ''),
            b.body_text
        FROM document_bodies b
        JOIN documents d ON d.doc_id = b.doc_id
        """
    )
    set_meta(conn, "fts_ready", "1")


def committed_layers(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT DISTINCT layer FROM layer_members ORDER BY layer").fetchall()
    return [row["layer"] for row in rows]


def reset_database() -> None:
    path = Path(settings.db_path)
    with _write_lock:
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(path) + suffix) if suffix else path
            if candidate.exists():
                candidate.unlink()
    init_db()
