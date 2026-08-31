from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any

from app.chunking import html_to_text
from app.config import FTS_CANDIDATES, KNN_CANDIDATES, RRF_K
from app.db import committed_layers, connect, vec_available
from app.embedder import embed_texts, probe_embedder
from app.versions import VersionError, introduced_already, pick_body_layer, resolve_platform_version


class SearchError(ValueError):
    def __init__(self, message: str, loaded_layers: list[str] | None = None):
        super().__init__(message)
        self.loaded_layers = loaded_layers or []


def _require_syntax_scope(scope: str) -> None:
    if (scope or "syntax").strip().lower() != "syntax":
        raise SearchError("v1 supports scope=syntax only")


def _fts_match_query(query: str, op: str = "AND") -> str:
    tokens = re.findall(r"\w+", query, flags=re.UNICODE)
    parts = [token.replace('"', "") + "*" for token in tokens if token.replace('"', "")]
    if not parts:
        return '""'
    return f" {op} ".join(parts)


def _document_payload(conn, doc_id: str, body_layer: str) -> dict[str, Any] | None:
    doc = conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
    if doc is None:
        return None
    body = conn.execute(
        "SELECT body_text, body_hash FROM document_bodies WHERE doc_id = ? AND layer = ?",
        (doc_id, body_layer),
    ).fetchone()
    aliases = [
        row["alias"]
        for row in conn.execute("SELECT alias FROM aliases WHERE doc_id = ? ORDER BY alias", (doc_id,)).fetchall()
    ]
    return {
        "doc_id": doc["doc_id"],
        "kind": doc["kind"],
        "full_name_ru": doc["full_name_ru"],
        "full_name_en": doc["full_name_en"],
        "object_ru": doc["object_ru"],
        "object_en": doc["object_en"],
        "member_ru": doc["member_ru"],
        "member_en": doc["member_en"],
        "introduced_in": doc["introduced_in"],
        "availability": doc["availability"],
        "syntax": doc["syntax"],
        "aliases": aliases,
        "layer": body_layer,
        "body_text": body["body_text"] if body else "",
        "body_hash": body["body_hash"] if body else "",
    }


def _visible_docs(conn, membership_layer: str, platform_version: str) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT d.*
        FROM layer_members m
        JOIN documents d ON d.doc_id = m.doc_id
        WHERE m.layer = ?
        """,
        (membership_layer,),
    ).fetchall()
    visible = {}
    for row in rows:
        if introduced_already(row["introduced_in"], platform_version):
            visible[row["doc_id"]] = row
    return visible


def _body_map(conn, doc_ids: list[str], body_layers: tuple[str, ...]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    if not doc_ids:
        return mapping
    placeholders = ",".join("?" * len(doc_ids))
    rows = conn.execute(
        f"SELECT doc_id, layer FROM document_bodies WHERE doc_id IN ({placeholders})",
        doc_ids,
    ).fetchall()
    by_doc: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        by_doc[row["doc_id"]].append(row["layer"])
    for doc_id, layers in by_doc.items():
        chosen = pick_body_layer(layers, body_layers)
        if chosen:
            mapping[doc_id] = chosen
    return mapping


def _format_document(payload: dict[str, Any]) -> str:
    header = [
        f"# {payload['full_name_ru']}",
        f"kind: {payload['kind']}",
        f"layer: {payload['layer']}",
    ]
    if payload.get("full_name_en"):
        header.append(f"en: {payload['full_name_en']}")
    if payload.get("syntax"):
        header.append(f"syntax: {payload['syntax']}")
    if payload.get("introduced_in"):
        header.append(f"introduced_in: {payload['introduced_in']}")
    if payload.get("availability"):
        header.append(f"availability: {payload['availability']}")
    body = payload.get("body_text") or ""
    text = html_to_text(body) if "<" in body else body
    return "\n".join(header) + "\n\n" + text.strip()


def lookup_document(name: str, platform_version: str, scope: str = "syntax") -> str:
    _require_syntax_scope(scope)
    with connect() as conn:
        layers = committed_layers(conn)
        try:
            resolved = resolve_platform_version(platform_version, layers)
        except VersionError as exc:
            raise SearchError(str(exc), exc.loaded_layers) from exc
        visible = _visible_docs(conn, resolved.membership_layer, platform_version)
        needle = name.strip().casefold()
        match_id = None
        for doc_id, row in visible.items():
            names = [row["full_name_ru"], row["full_name_en"], row["object_ru"], row["member_ru"]]
            aliases = [
                item["alias"]
                for item in conn.execute("SELECT alias FROM aliases WHERE doc_id = ?", (doc_id,)).fetchall()
            ]
            names.extend(aliases)
            if any(value and value.casefold() == needle for value in names):
                match_id = doc_id
                break
        if match_id is None:
            return f"Document {name!r} was not found for platform_version {platform_version}."
        bodies = _body_map(conn, [match_id], resolved.body_layers)
        layer = bodies.get(match_id)
        if not layer:
            return f"Document {name!r} has no body for platform_version {platform_version}."
        payload = _document_payload(conn, match_id, layer)
        return _format_document(payload) if payload else "Document not found."


def _fts_ranks(conn, query: str, visible: dict[str, Any], body_map: dict[str, str]) -> list[str]:
    rows = []
    for op in ("AND", "OR"):
        match = _fts_match_query(query, op)
        try:
            rows = conn.execute(
                """
                SELECT doc_id, layer, bm25(documents_fts) AS score
                FROM documents_fts
                WHERE documents_fts MATCH ?
                ORDER BY score
                LIMIT 200
                """,
                (match,),
            ).fetchall()
        except Exception:
            rows = []
        if rows:
            break
    ranked: list[str] = []
    seen: set[str] = set()
    for row in rows:
        doc_id = row["doc_id"]
        if doc_id not in visible or doc_id in seen:
            continue
        expected_layer = body_map.get(doc_id)
        if expected_layer and row["layer"] != expected_layer:
            continue
        ranked.append(doc_id)
        seen.add(doc_id)
        if len(ranked) >= FTS_CANDIDATES:
            break
    return ranked


def _knn_ranks(conn, query: str, visible: dict[str, Any], body_map: dict[str, str]) -> list[str]:
    if not vec_available() or probe_embedder()["status"] != "up":
        return []
    vectors = embed_texts([query], query=True)
    if not vectors:
        return []
    vector = vectors[0]
    try:
        import sqlite_vec

        packed = sqlite_vec.serialize_float32(vector)
    except Exception:
        packed = json.dumps(vector)
    rows = []
    for sql, params in (
        (
            """
            SELECT v.chunk_id, v.distance, c.doc_id, c.layer
            FROM vec_chunks v
            JOIN chunks c ON c.chunk_id = v.chunk_id
            WHERE v.embedding MATCH ?
              AND k = 200
            """,
            (packed,),
        ),
        (
            """
            SELECT v.chunk_id, v.distance, c.doc_id, c.layer
            FROM vec_chunks v
            JOIN chunks c ON c.chunk_id = v.chunk_id
            WHERE v.embedding MATCH ?
            ORDER BY v.distance
            LIMIT 200
            """,
            (json.dumps(vector),),
        ),
    ):
        try:
            rows = conn.execute(sql, params).fetchall()
            if rows:
                break
        except Exception:
            continue
    if not rows:
        return []
    ranked: list[str] = []
    seen: set[str] = set()
    for row in rows:
        doc_id = row["doc_id"]
        if doc_id not in visible or doc_id in seen:
            continue
        if body_map.get(doc_id) and row["layer"] != body_map[doc_id]:
            continue
        ranked.append(doc_id)
        seen.add(doc_id)
        if len(ranked) >= KNN_CANDIDATES:
            break
    return ranked


def _rrf(*rank_lists: list[str]) -> list[str]:
    scores: dict[str, float] = defaultdict(float)
    for ranks in rank_lists:
        for index, doc_id in enumerate(ranks):
            scores[doc_id] += 1.0 / (RRF_K + index + 1)
    return [doc_id for doc_id, _ in sorted(scores.items(), key=lambda item: item[1], reverse=True)]


MEMBER_KIND_ORDER = (
    "constructor",
    "method",
    "property",
    "event",
    "operator",
    "literal",
    "enum",
    "statement",
    "definition",
    "value",
    "value_set",
    "enum_value",
    "form_parameter",
    "query_table",
    "query_field",
    "query_parameter",
    "catalog",
    "type",
)


def _kind_rank(kind: str) -> int:
    try:
        return MEMBER_KIND_ORDER.index(kind)
    except ValueError:
        return len(MEMBER_KIND_ORDER)


def _owner_matches(row: Any, needle: str) -> bool:
    for field in ("object_ru", "object_en"):
        owner = row[field] or ""
        if owner.strip().casefold() == needle:
            return True
    return False


def _type_article_matches(row: Any, needle: str) -> bool:
    for field in ("full_name_ru", "full_name_en"):
        name = row[field] or ""
        if name.strip().casefold() == needle:
            return True
    return False


def _ctor_owner_doc_id(doc_id: str) -> str | None:
    marker = "/ctors/"
    if marker not in doc_id:
        return None
    return doc_id.rsplit(marker, 1)[0] + ".html"


def list_type_members(
    type_name: str,
    platform_version: str,
    kind: str = "",
    limit: int = 50,
    scope: str = "syntax",
) -> str:
    _require_syntax_scope(scope)
    needle = (type_name or "").strip().casefold()
    if not needle:
        raise SearchError("type is required")
    wanted_kind = (kind or "").strip().lower()
    try:
        limit = int(limit)
    except (TypeError, ValueError) as exc:
        raise SearchError("limit must be an integer") from exc
    if limit < 1 or limit > 200:
        raise SearchError("limit must be between 1 and 200")
    with connect() as conn:
        layers = committed_layers(conn)
        try:
            resolved = resolve_platform_version(platform_version, layers)
        except VersionError as exc:
            raise SearchError(str(exc), exc.loaded_layers) from exc
        visible = _visible_docs(conn, resolved.membership_layer, platform_version)
        owner_name = ""
        for row in visible.values():
            if (row["kind"] or "").lower() == "type" and _type_article_matches(row, needle):
                owner_name = row["full_name_ru"] or row["full_name_en"] or type_name
                break
        owned: list[tuple[str, Any]] = []
        for row in visible.values():
            member_name = row["member_ru"] or row["member_en"] or ""
            in_type = _owner_matches(row, needle)
            if not in_type and (row["kind"] or "").lower() == "constructor" and not member_name:
                owner = visible.get(_ctor_owner_doc_id(row["doc_id"]) or "")
                if owner is not None and _type_article_matches(owner, needle):
                    member_name = row["full_name_ru"] or row["full_name_en"] or ""
                    in_type = bool(member_name)
            if not in_type or not member_name:
                continue
            if not owner_name:
                candidate = row["object_ru"] or row["object_en"] or ""
                if candidate.strip().casefold() == needle:
                    owner_name = candidate
            owned.append((member_name, row))
        if not owned:
            return f"No members found for type {type_name!r} at platform_version {platform_version}."
        if wanted_kind:
            members = [(name, row) for name, row in owned if (row["kind"] or "").lower() == wanted_kind]
            if not members:
                present = sorted({row["kind"] or "unknown" for _, row in owned})
                return (
                    f"No members with kind {wanted_kind!r} for type {type_name!r} "
                    f"at platform_version {platform_version}."
                    f" Available kinds: {', '.join(present)}."
                )
        else:
            members = owned
        members.sort(key=lambda item: (_kind_rank(item[1]["kind"] or ""), item[0].casefold()))
        shown = members[:limit]
        syntax_used = any(row["syntax"] for _, row in shown)
        width = min(max(max(len(name) for name, _ in shown), len("member")), 28)
        lines = [f"# {owner_name or type_name} — {len(members)} member{'s' if len(members) != 1 else ''}"]
        header = f"{'kind':<12} {'member':<{width}}"
        if syntax_used:
            header += " syntax"
        lines.append(header)
        for name, row in shown:
            line = f"{(row['kind'] or '-'):<12} {name:<{width}}"
            if syntax_used:
                line += f" {row['syntax'] or '-'}"
            lines.append(line)
        if len(members) > len(shown):
            lines.append(f"... and {len(members) - len(shown)} more (raise limit, up to 200)")
        return "\n".join(lines)


def search_documents(query: str, platform_version: str, scope: str = "syntax") -> str:
    _require_syntax_scope(scope)
    query = (query or "").strip()
    if not query:
        raise SearchError("query is required")
    with connect() as conn:
        layers = committed_layers(conn)
        try:
            resolved = resolve_platform_version(platform_version, layers)
        except VersionError as exc:
            raise SearchError(str(exc), exc.loaded_layers) from exc
        visible = _visible_docs(conn, resolved.membership_layer, platform_version)
        body_map = _body_map(conn, list(visible.keys()), resolved.body_layers)
        fts_ranks = _fts_ranks(conn, query, visible, body_map)
        knn_ranks = _knn_ranks(conn, query, visible, body_map)
        ordered = _rrf(fts_ranks, knn_ranks) or fts_ranks
        if not ordered:
            return f"No documents found for {query!r} at platform_version {platform_version}."
        parts: list[str] = []
        for doc_id in ordered[:10]:
            layer = body_map.get(doc_id)
            if not layer:
                continue
            payload = _document_payload(conn, doc_id, layer)
            if payload:
                parts.append(_format_document(payload))
        return "\n\n---\n\n".join(parts) if parts else "No documents found."
