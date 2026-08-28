from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_QUERY_PREFIX = (
    "Instruct: Given a question, retrieve passages that answer the question\nQuery: "
)
EXPECTED_EMBED_DIM = 2048
SESSION_TTL_SECONDS = 2 * 60 * 60
MAX_BATCH_CARDS = 200
FTS_CANDIDATES = 50
KNN_CANDIDATES = 50
RRF_K = 60


def _expand_newlines(value: str) -> str:
    return value.replace("\\n", "\n")


@dataclass(frozen=True)
class Settings:
    ingest_token: str
    mcp_token: str
    embed_url: str
    embed_model: str
    embed_api_key: str
    embed_query_prefix: str
    db_path: str
    port: int

    @property
    def embed_base(self) -> str:
        return self.embed_url.rstrip("/")


def load_settings() -> Settings:
    ingest = os.environ.get("INGEST_TOKEN", "").strip()
    mcp = os.environ.get("MCP_TOKEN", "").strip()
    if not ingest or not mcp:
        raise RuntimeError("INGEST_TOKEN and MCP_TOKEN must be set")
    if ingest == mcp:
        raise RuntimeError("INGEST_TOKEN and MCP_TOKEN must be different")

    prefix = os.environ.get("EMBED_QUERY_PREFIX", DEFAULT_QUERY_PREFIX)
    return Settings(
        ingest_token=ingest,
        mcp_token=mcp,
        embed_url=os.environ.get("EMBED_URL", "http://giga-embeddings:7997/v1").strip(),
        embed_model=os.environ.get("EMBED_MODEL", "Giga-Embeddings-instruct").strip(),
        embed_api_key=os.environ.get("EMBED_API_KEY", "").strip(),
        embed_query_prefix=_expand_newlines(prefix),
        db_path=os.environ.get("DB_PATH", "/data/help.sqlite"),
        port=int(os.environ.get("PORT", "8004")),
    )


settings = load_settings()
