from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from app.auth import BearerAuthMiddleware
from app.db import init_db
from app.embedder import start_worker, stop_worker
from app.ingest import (
    BatchesRequest,
    BeginRequest,
    ConfirmRequest,
    SessionRequest,
    abort_ingest,
    add_batches,
    begin_ingest,
    commit_ingest,
    delete_layer,
    wipe_database,
)
from app.mcp_tools import make_mcp_app
from app.status import collect_status, ready_response, render_dashboard

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

mcp_app = make_mcp_app()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    start_worker()
    async with mcp_app.lifespan(app):
        yield
    stop_worker()


app = FastAPI(title="BSL syntax-help MCP", lifespan=lifespan)
app.add_middleware(BearerAuthMiddleware)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
def ready():
    code, payload = ready_response()
    return JSONResponse(payload, status_code=code)


@app.get("/status")
def status() -> dict:
    return collect_status()


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    return render_dashboard(collect_status())


@app.post("/ingest/begin")
def ingest_begin(body: BeginRequest) -> dict:
    return begin_ingest(body.layer)


@app.post("/ingest/batches")
def ingest_batches(body: BatchesRequest) -> dict:
    return add_batches(body.session_id, body.cards)


@app.post("/ingest/commit")
def ingest_commit(body: SessionRequest) -> dict:
    return commit_ingest(body.session_id)


@app.post("/ingest/abort")
def ingest_abort(body: SessionRequest) -> dict:
    return abort_ingest(body.session_id)


@app.delete("/admin/layers/{layer}")
def admin_delete_layer(layer: str) -> dict:
    return delete_layer(layer)


@app.delete("/admin/database")
def admin_wipe(body: ConfirmRequest) -> dict:
    if not body.confirm:
        raise HTTPException(status_code=400, detail="confirm must be true")
    return wipe_database(True)


app.mount("/mcp", mcp_app)
