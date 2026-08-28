# BSL syntax-help MCP

Docker services that store 1C platform syntax help in SQLite and expose Comol-style MCP tools (`docinfo`, `docsearch`). The EDT Tycho exporter is not in this repo yet.

## Layout

- `docker/giga` — GPU SentenceTransformers OpenAI embeddings (`ai-sage/Giga-Embeddings-instruct`, dim 2048)
- `docker/mcp` — CPU FastAPI + FastMCP, SQLite FTS5 + sqlite-vec
- `edt-syntax-help-export` — stub for the later Tycho plugin

## Start

```bash
git clone git@github.com:malikov-pro/bsl-syntax-help-mcp.git
cd bsl-syntax-help-mcp

docker network create syntax-help   # once; ignore "already exists"

cp docker/giga/.env.example docker/giga/.env
cp docker/mcp/.env.example docker/mcp/.env
# set distinct INGEST_TOKEN and MCP_TOKEN in docker/mcp/.env

docker compose -f docker/giga/docker-compose.yml up -d --build
docker compose -f docker/mcp/docker-compose.yml up -d --build
```

There is no `depends_on` between the two projects. MCP starts even while Giga is still building or pulling weights.

First Giga start is slow: CUDA 12.6 + PyTorch image build, then ~13 GB into `docker/giga/hf-cache/` (`ai-sage/Giga-Embeddings-instruct`). `/health` stays 503 until the model is in VRAM. Compose `start_period` is 30 minutes. RTX 3090 is enough (~8–12 GB VRAM in bf16). `flash_attn` is optional; the server falls back to default attention.

## Ports (loopback only)

| Service | Host | Docker DNS |
| --- | --- | --- |
| Giga embeddings | `http://127.0.0.1:7997` | `http://giga-embeddings:7997` |
| MCP | `http://127.0.0.1:8004` | — |

`GET /health`, `/ready`, `/status`, and `/` on MCP do not require a token. Ingest and `/admin/*` use `INGEST_TOKEN`. Every `/mcp` method (including GET/DELETE) uses `MCP_TOKEN`.

`GET /ready` is 200 when FTS search is possible (`ready` or `degraded` if the embedder is down). 503 is only `starting` (empty) or `indexing` (FTS rebuild).

## Ingest example

```bash
set -a && source docker/mcp/.env && set +a

SESSION=$(curl -sS http://127.0.0.1:8004/ingest/begin \
  -H "Authorization: Bearer $INGEST_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"layer":"base"}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["session_id"])')

curl -sS http://127.0.0.1:8004/ingest/batches \
  -H "Authorization: Bearer $INGEST_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION\",\"cards\":[{
    \"doc_id\":\"array.find\",
    \"layer\":\"base\",
    \"kind\":\"method\",
    \"full_name_ru\":\"Массив.Найти\",
    \"body_text\":\"<h2>Синтаксис</h2><p>Найти(Значение) — ищет элемент в массиве и возвращает индекс либо Undefined.</p>\"
  }]}"

curl -sS http://127.0.0.1:8004/ingest/commit \
  -H "Authorization: Bearer $INGEST_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"session_id\":\"$SESSION\"}"

curl -sS http://127.0.0.1:8004/status
```

Search with `platform_version` `8.3.23` (membership layer `base`). Hybrid FTS + embeddings runs when Giga is healthy; FTS-only works in `degraded`.

## Cursor

```json
{
  "mcpServers": {
    "bsl-syntax-help": {
      "url": "http://127.0.0.1:8004/mcp",
      "headers": {
        "Authorization": "Bearer ${MCP_TOKEN}"
      }
    }
  }
}
```

Do not commit real tokens. Do not run this MCP next to HelpSearchServer: the tool names collide.

## Env

MCP (`docker/mcp/.env`): `INGEST_TOKEN`, `MCP_TOKEN`, `EMBED_URL=http://giga-embeddings:7997/v1`, `EMBED_MODEL=Giga-Embeddings-instruct`, `EMBED_API_KEY` (empty), `EMBED_QUERY_PREFIX` (instruct text, query side only).

Giga (`docker/giga/.env`): `MODEL_ID`, optional `HF_TOKEN`. Weights stay in the Giga volume, never in the MCP image.
