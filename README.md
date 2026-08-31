# BSL syntax-help MCP

[![GitHub all releases](https://img.shields.io/github/downloads/malikov-pro/bsl-syntax-help-mcp/total)](https://github.com/malikov-pro/bsl-syntax-help-mcp/releases)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue)](LICENSE)

[![Непрерывная интеграция](https://github.com/malikov-pro/bsl-syntax-help-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/malikov-pro/bsl-syntax-help-mcp/actions/workflows/ci.yml)
[![Релиз](https://github.com/malikov-pro/bsl-syntax-help-mcp/actions/workflows/release.yml/badge.svg)](https://github.com/malikov-pro/bsl-syntax-help-mcp/actions/workflows/release.yml)
[![Deploy Update Site](https://github.com/malikov-pro/bsl-syntax-help-mcp/actions/workflows/deploy-update-site.yml/badge.svg)](https://github.com/malikov-pro/bsl-syntax-help-mcp/actions/workflows/deploy-update-site.yml)

[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=malikov-pro_bsl-syntax-help-mcp&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=malikov-pro_bsl-syntax-help-mcp)
[![Bugs](https://sonarcloud.io/api/project_badges/measure?project=malikov-pro_bsl-syntax-help-mcp&metric=bugs)](https://sonarcloud.io/summary/new_code?id=malikov-pro_bsl-syntax-help-mcp)
[![Code Smells](https://sonarcloud.io/api/project_badges/measure?project=malikov-pro_bsl-syntax-help-mcp&metric=code_smells)](https://sonarcloud.io/summary/new_code?id=malikov-pro_bsl-syntax-help-mcp)

Docker-сервисы, которые хранят синтакс-помощник платформы 1С в SQLite и отдают
MCP-инструменты в стиле Comol (`docinfo`, `docsearch`). Плагин для 1С:EDT
выгружает синтакс-помощник в MCP-контейнер по HTTP.
Потоки данных — в [CHECK-FLOWS.md](CHECK-FLOWS.md).

## Состав

- `docker/giga` — OpenAI-совместимые эмбеддинги на GPU, SentenceTransformers (`ai-sage/Giga-Embeddings-instruct`, размерность 2048)
- `docker/mcp` — FastAPI + FastMCP на CPU, SQLite FTS5 + sqlite-vec
- `edt-syntax-help-export` — Tycho-плагин для 1С:EDT (HTTP-клиент ingest)

## Запуск

```bash
git clone git@github.com:malikov-pro/bsl-syntax-help-mcp.git
cd bsl-syntax-help-mcp

docker network create syntax-help   # один раз; «already exists» игнорировать

cp docker/giga/.env.example docker/giga/.env
cp docker/mcp/.env.example docker/mcp/.env
# задайте разные INGEST_TOKEN и MCP_TOKEN в docker/mcp/.env

docker compose -f docker/giga/docker-compose.yml up -d --build
docker compose -f docker/mcp/docker-compose.yml up -d --build
```

`depends_on` между проектами нет: MCP стартует, даже пока Giga ещё собирается
или тянет веса.

Первый старт Giga небыстрый: сборка образа CUDA 12.6 + PyTorch, затем ~13 ГБ
в `docker/giga/hf-cache/` (`ai-sage/Giga-Embeddings-instruct`). `/health`
держит 503, пока модель не в VRAM. `start_period` в compose — 30 минут.
RTX 3090 достаточно (~8–12 ГБ VRAM в bf16). `flash_attn` опционален: без него
сервер откатывается к обычному attention.

## Порты (только loopback)

| Сервис | На хосте | Docker DNS |
| --- | --- | --- |
| Giga-эмбеддинги | `http://127.0.0.1:7997` | `http://giga-embeddings:7997` |
| MCP | `http://127.0.0.1:8004` | — |

`GET /health`, `/ready`, `/status` и `/` на MCP токена не требуют.
Ingest и `/admin/*` используют `INGEST_TOKEN`. Любой метод `/mcp`
(включая GET/DELETE) — `MCP_TOKEN`.

`GET /ready` возвращает 200, когда возможен FTS-поиск (`ready` или `degraded`,
если эмбеддер недоступен). 503 — только `starting` (пустая база) или
`indexing` (пересборка FTS).

## Ручная выгрузка (ingest)

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

Поиск с `platform_version` `8.3.23` (слой членства `base`). Гибрид FTS +
эмбеддинги работает, когда Giga здоров; в `degraded` остаётся FTS-only.

## Перенос SQLite-корпуса между машинами

Индексируемый корпус **не** лежит в git. Он живёт на хосте MCP как файлы
Docker-тома:

- `docker/mcp/data/help.sqlite`
- `docker/mcp/data/help.sqlite-wal` (после чистой остановки может отсутствовать или быть пустым)
- `docker/mcp/data/help.sqlite-shm`

После полной выгрузки и векторизации это несколько ГБ. Копирование — способ
забрать готовый индекс на другой ПК **без** повторной выгрузки из EDT и
повторной векторизации на Giga.

Для этого **не** копируйте `docker/giga/hf-cache/`: рабочей машине всё равно
нужен собственный контейнер Giga — для векторов *запросов*. Векторы документов
уже внутри SQLite-файла.

### 1. Снимок на исходном ПК

Дождитесь, пока очередь опустеет (или примите, что остаточные `pending`-строки
доиграют уже на принимающей стороне):

```bash
curl -sS http://127.0.0.1:8004/status
# embed_queue.pending == 0 и error == 0  →  можно замораживать
```

Остановите **только MCP**, чтобы SQLite закрыл WAL. Giga можно не трогать:
этот файл он не открывает.

```bash
docker compose -f docker/mcp/docker-compose.yml stop
```

Чекпоинт в один файл (нужен `sqlite3` на хосте):

```bash
sqlite3 docker/mcp/data/help.sqlite "PRAGMA wal_checkpoint(TRUNCATE);"
```

Если `sqlite3` нет, копируйте все три файла `help.sqlite*` вместе — никогда не
один `.sqlite`, пока `-wal` ещё содержит данные.

Упакуйте всё, что SQLite оставил в `data/` (основной файл плюс WAL/SHM, если есть):

```bash
tar -C docker/mcp/data -cvf help-sqlite.tar help.sqlite*
```

Затем поднимите MCP на исходной машине, если он ещё нужен:

```bash
docker compose -f docker/mcp/docker-compose.yml start
```

`help-sqlite.tar` передавайте чем удобно (`rsync`, флешка, scp). Внутри —
локальный текст синтакс-помощника: не информбаза 1С, но считайте файл
внутренним.

### 2. Восстановление на рабочем ПК

Та же ревизия репозитория (как минимум — та же схема SQLite и
`EXPECTED_EMBED_DIM=2048`). Создайте на рабочем ПК `docker/mcp/.env` с
токенами **этой** машины — `INGEST_TOKEN` / `MCP_TOKEN` внутри базы не хранятся.

```bash
git clone git@github.com:malikov-pro/bsl-syntax-help-mcp.git
cd bsl-syntax-help-mcp
docker network create syntax-help   # «already exists» игнорировать

cp docker/giga/.env.example docker/giga/.env
cp docker/mcp/.env.example docker/mcp/.env
# впишите токены

mkdir -p docker/mcp/data
# остановите MCP, если первый up успел создать пустой help.sqlite
docker compose -f docker/mcp/docker-compose.yml stop 2>/dev/null || true

tar -C docker/mcp/data -xvf /путь/к/help-sqlite.tar
# в назначении должен оказаться help.sqlite; -wal/-shm включите, если были в архиве

docker compose -f docker/giga/docker-compose.yml up -d --build
docker compose -f docker/mcp/docker-compose.yml up -d --build
```

Если MCP уже работал с пустой базой, **замените файлы при остановленном
контейнере**, затем `start` / `up -d`. Перезапись `help.sqlite` под живым
контейнером его испортит.

Проверка:

```bash
curl -sS http://127.0.0.1:8004/status
```

Должны совпасть `layers`, `documents`, `chunks` и `embed_queue.done`.
`status` — `ready`, когда FTS поднят; гибридному поиску нужен поднятый Giga на
этой машине (первый старт Giga всё равно тянет ~13 ГБ весов).

MCP URL в Cursor не меняется: `http://127.0.0.1:8004/mcp` с токеном
**рабочей** машины `MCP_TOKEN`.

### Замечания

- Копируйте только при остановленном MCP: живая копия WAL-SQLite — не
  консистентный бэкап.
- Giga на принимающей стороне должен быть той же модели
  (`Giga-Embeddings-instruct`, размерность 2048). Другая модель не совпадёт
  с сохранёнными векторами; FTS при этом продолжит работать.
- Если `pending` не был нулём, воркер MCP на принимающей стороне доиграет
  очередь против местного Giga.
- `docker/mcp/data/` и `*.sqlite` не коммитьте.

## Подключение в Cursor

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

Реальные токены не коммитьте. Не запускайте этот MCP рядом с
HelpSearchServer: имена инструментов пересекаются.

## Плагин для EDT

Tycho-раскладка в `edt-syntax-help-export/connector/`
(bom / bundles / features / repositories / targets). Таргет по умолчанию —
EDT **2025.2** + Eclipse **2025-12**; `-Pedt-2026.1` переключает p2-URL.
Подробнее: [edt-syntax-help-export/README.md](edt-syntax-help-export/README.md).

Установка с сайта обновления (GitHub Pages):

1. Откройте `Справка` → `Установить новое ПО`.
2. Введите ссылку:

```
https://malikov-pro.github.io/bsl-syntax-help-mcp/
```

3. Нажмите `Добавить`.
4. Установите флажок на `BSL syntax-help export for EDT`.
5. Убедитесь, что установлен флажок `Обращаться во время инсталляции ко всем сайтам обновления для поиска требуемого ПО`.
6. `Далее` → `Готово`, затем перезапустите EDT.

### Установка из архива (без сайта обновления)

1. Скачайте zip со страницы [Releases](https://github.com/malikov-pro/bsl-syntax-help-mcp/releases) — файл `…repository-<версия>.zip`.
2. `Справка` → `Установить новое ПО` → `Добавить` → `Архив` → укажите скачанный zip.
3. **Снимите** флажок `Обращаться во время инсталляции ко всем сайтам обновления…` — иначе p2 лезет на `services.1c.dev` (ошибка аутентификации) и не находит локальные артефакты (`No repository found containing`).
4. Выберите `BSL syntax-help export for EDT` → `Далее` → `Готово` → перезапустите EDT.

В закрытую EDT установка через p2 director тоже работает:
`bash scripts/deploy-edt.sh` (из `edt-syntax-help-export/`).

Сайт публикует `.github/workflows/deploy-update-site.yml` (пуш тега релиза,
событие «релиз опубликован» или Actions → Run workflow); p2 лежит в корне
Pages, копия на длинном пути `…/update/bsl-syntax-help-mcp/latest/` сохранена
для уже установленных EDT. Настройки репозитория → Pages → Source:
GitHub Actions, плюс секреты `MAVEN_USERNAME` / `MAVEN_CENTRAL_TOKEN`.

В EDT: `Окно` → `Параметры` → `Синтакс-помощник MCP` — URL `http://127.0.0.1:8004`,
`INGEST_TOKEN`, флажки слоёв, затем **Выгрузить**.

## Переменные окружения

MCP (`docker/mcp/.env`): `INGEST_TOKEN`, `MCP_TOKEN`,
`EMBED_URL=http://giga-embeddings:7997/v1`, `EMBED_MODEL=Giga-Embeddings-instruct`,
`EMBED_API_KEY` (пустой), `EMBED_QUERY_PREFIX` (инструкт, только на стороне запроса).

Giga (`docker/giga/.env`): `MODEL_ID`, опционально `HF_TOKEN`. Веса живут
в томе Giga, в образ MCP не попадают.

## Разработчикам

Сборка плагина (`bash compile.sh`), целевые платформы EDT, ветвление, релизы и
Docker-сервисы — в [Руководстве разработчика](DEVELOPER.md); карта минных полей
проекта — [CLAUDE.md](CLAUDE.md).

## Лицензия

[AGPL-3.0](LICENSE).
