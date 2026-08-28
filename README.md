# BSL syntax-help MCP

Docker services that store 1C platform syntax help in SQLite and expose Comol-style MCP tools (`docinfo`, `docsearch`). The EDT plugin dumps the syntax helper into the MCP container over HTTP.

## Layout

- `docker/giga` — GPU SentenceTransformers OpenAI embeddings (`ai-sage/Giga-Embeddings-instruct`, dim 2048)
- `docker/mcp` — CPU FastAPI + FastMCP, SQLite FTS5 + sqlite-vec
- `edt-syntax-help-export` — Tycho plugin for 1С:EDT (HTTP ingest client)

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

## Move the SQLite corpus between machines

The searchable corpus is **not** in git. It lives on the MCP host as Docker volume files:

- `docker/mcp/data/help.sqlite`
- `docker/mcp/data/help.sqlite-wal` (may be missing or empty after a clean stop)
- `docker/mcp/data/help.sqlite-shm`

After a full ingest + embed this is a few GB. Copying it is how you take a precomputed index to another PC **without** re-exporting from EDT or re-embedding on Giga.

Do **not** copy `docker/giga/hf-cache/` for this: the work box still needs its own Giga container for *query* embeddings. The SQLite file already holds document vectors.

### 1. Snapshot on the source PC

Wait until the queue is idle (or accept that leftover `pending` rows will resume on the destination):

```bash
curl -sS http://127.0.0.1:8004/status
# embed_queue.pending == 0 and error == 0  →  safe to freeze
```

Stop **MCP only** so SQLite closes the WAL. Leave Giga running if you want; it does not open this file.

```bash
docker compose -f docker/mcp/docker-compose.yml stop
```

Checkpoint into a single file (needs `sqlite3` on the host):

```bash
sqlite3 docker/mcp/data/help.sqlite "PRAGMA wal_checkpoint(TRUNCATE);"
```

If `sqlite3` is missing, copy all three `help.sqlite*` files together — never the `.sqlite` alone while a `-wal` still has data.

Pack everything SQLite left in `data/` (the main file plus WAL/SHM if present):

```bash
tar -C docker/mcp/data -cvf help-sqlite.tar help.sqlite*
```

Then start MCP again on the source if you still need it:

```bash
docker compose -f docker/mcp/docker-compose.yml start
```

Copy `help-sqlite.tar` with whatever you use (`rsync`, USB, scp). The file is local syntax-help text; it is not a 1C infobase, but treat it as internal.

### 2. Restore on the work PC

Same repo revision (or at least the same SQLite schema and `EXPECTED_EMBED_DIM=2048`). Create `docker/mcp/.env` on the work box with **that** machine’s `INGEST_TOKEN` / `MCP_TOKEN` — tokens are not inside the database.

```bash
git clone git@github.com:malikov-pro/bsl-syntax-help-mcp.git
cd bsl-syntax-help-mcp
docker network create syntax-help   # ignore "already exists"

cp docker/giga/.env.example docker/giga/.env
cp docker/mcp/.env.example docker/mcp/.env
# edit tokens

mkdir -p docker/mcp/data
# stop MCP if a first `up` already created an empty help.sqlite
docker compose -f docker/mcp/docker-compose.yml stop 2>/dev/null || true

tar -C docker/mcp/data -xvf /path/to/help-sqlite.tar
# destination must contain help.sqlite; include -wal/-shm if they were in the archive

docker compose -f docker/giga/docker-compose.yml up -d --build
docker compose -f docker/mcp/docker-compose.yml up -d --build
```

If MCP was already running with an empty DB, **replace the files while it is stopped**, then `start` / `up -d`. Overwriting `help.sqlite` under a live container will corrupt it.

Check:

```bash
curl -sS http://127.0.0.1:8004/status
```

You should see the same `layers`, `documents`, `chunks`, and `embed_queue.done`. `status` is `ready` when FTS is up; hybrid search needs Giga `up` on this machine (first Giga start still pulls ~13 GB weights).

Cursor MCP URL stays `http://127.0.0.1:8004/mcp` with the **work** `MCP_TOKEN`.

### Notes

- Copy only while MCP is stopped. A live copy of WAL SQLite is not a consistent backup.
- Destination Giga must be the same model (`Giga-Embeddings-instruct`, dim 2048). A different model will not match stored vectors; FTS still works.
- If `pending` was not zero, the dest MCP worker continues the queue against dest Giga.
- Do not commit `docker/mcp/data/` or `*.sqlite`.

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

## EDT plugin

Tycho layout lives in `edt-syntax-help-export/connector/` (bom / bundles / features / repositories / targets). Default target is EDT **2025.2** + Eclipse **2025-12**; `-Pedt-2026.1` switches the p2 URL. Details: [edt-syntax-help-export/README.md](edt-syntax-help-export/README.md).

```bash
cd edt-syntax-help-export
cp connector/bom/edt-credentials.env.example connector/bom/edt-credentials.env
# MAVEN_USERNAME / MAVEN_CENTRAL_TOKEN — учётка edt.1c.ru, файл не коммитить

bash compile.sh
# или: bash compile.sh --profile edt-2026.1
```

Install into a **closed** EDT (p2 director, auto-detects `~/.local/share/1C/1cedtstart/installations/1C_EDT*`):

```bash
bash scripts/deploy-edt.sh
```

From the zip by hand: `Справка` → `Установить новое ПО` → `Добавить` → `Архив`. **Do not enable** `Обращаться во время инсталляции ко всем сайтам обновления…` — p2 will hit `services.1c.dev`, fail auth, then report `No repository found containing`.

In EDT: `Окно` → `Параметры` → `Синтакс-помощник MCP` — URL `http://127.0.0.1:8004`, `INGEST_TOKEN`, layer checkboxes, then **Выгрузить**.

## Env

MCP (`docker/mcp/.env`): `INGEST_TOKEN`, `MCP_TOKEN`, `EMBED_URL=http://giga-embeddings:7997/v1`, `EMBED_MODEL=Giga-Embeddings-instruct`, `EMBED_API_KEY` (empty), `EMBED_QUERY_PREFIX` (instruct text, query side only).

Giga (`docker/giga/.env`): `MODEL_ID`, optional `HF_TOKEN`. Weights stay in the Giga volume, never in the MCP image.
