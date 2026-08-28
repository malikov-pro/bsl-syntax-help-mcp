from __future__ import annotations

from typing import Any

from app.db import committed_layers, connect, get_meta, vec_available
from app.embedder import probe_embedder


def collect_status() -> dict[str, Any]:
    embedder = probe_embedder()
    with connect() as conn:
        documents = conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()["n"]
        bodies = conn.execute("SELECT COUNT(*) AS n FROM document_bodies").fetchone()["n"]
        chunks = conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()["n"]
        layers = committed_layers(conn)
        fts_ready = get_meta(conn, "fts_ready", "1") == "1"
        queue = {
            row["status"]: row["n"]
            for row in conn.execute(
                "SELECT status, COUNT(*) AS n FROM embed_queue GROUP BY status"
            ).fetchall()
        }
        embed_queue = {
            "pending": int(queue.get("pending", 0)),
            "done": int(queue.get("done", 0)),
            "error": int(queue.get("error", 0)),
        }

    if not layers:
        state = "starting"
    elif not fts_ready:
        state = "indexing"
    elif embedder["status"] != "up" or not vec_available():
        state = "degraded"
    else:
        state = "ready"

    return {
        "status": state,
        "documents": documents,
        "bodies": bodies,
        "layers": layers,
        "fts_ready": fts_ready,
        "chunks": chunks,
        "embed_queue": embed_queue,
        "dependencies": {
            "embedder": {
                "url": embedder["url"],
                "status": embedder["status"],
                "model": embedder["model"],
            }
        },
    }


def ready_response() -> tuple[int, dict[str, Any]]:
    payload = collect_status()
    state = payload["status"]
    if state in {"starting", "indexing"}:
        return 503, payload
    return 200, payload


def render_dashboard(payload: dict[str, Any]) -> str:
    layers = ", ".join(payload["layers"]) or "—"
    queue = payload["embed_queue"]
    embedder = payload["dependencies"]["embedder"]
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta http-equiv="refresh" content="5"/>
  <title>BSL syntax-help</title>
  <style>
    body {{ font-family: ui-sans-serif, system-ui, sans-serif; margin: 2rem; background: #111; color: #eee; }}
    h1 {{ font-size: 1.4rem; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr)); gap: 1rem; }}
    .card {{ background: #1c1c1c; padding: 1rem; border-radius: 8px; }}
    .ok {{ color: #7dcea0; }}
    .warn {{ color: #f7dc6f; }}
    .bad {{ color: #f1948a; }}
    code {{ color: #85c1e9; }}
  </style>
</head>
<body>
  <h1>BSL syntax-help MCP</h1>
  <p class="{'ok' if payload['status']=='ready' else 'warn' if payload['status']=='degraded' else 'bad'}">
    status: <strong>{payload['status']}</strong>
  </p>
  <div class="grid">
    <div class="card">documents<br><strong>{payload['documents']}</strong></div>
    <div class="card">bodies<br><strong>{payload['bodies']}</strong></div>
    <div class="card">chunks<br><strong>{payload['chunks']}</strong></div>
    <div class="card">fts_ready<br><strong>{str(payload['fts_ready']).lower()}</strong></div>
    <div class="card">embed queue<br>pending {queue['pending']} / done {queue['done']} / error {queue['error']}</div>
    <div class="card">layers<br><strong>{layers}</strong></div>
  </div>
  <p>embedder <code>{embedder['url']}</code> · {embedder['model']} · {embedder['status']}</p>
</body>
</html>
"""
