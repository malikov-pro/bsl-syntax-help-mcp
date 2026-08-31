# Руководство разработчика — bsl-syntax-help-mcp

Docker-сервисы (MCP-поиск по синтакс-помощнику 1С + эмбеддинги Giga) и плагин
выгрузки синтакс-помощника для 1С:EDT (Maven/Tycho).
Обзор возможностей, установка и первый запуск — в [README](README.md).

## Содержание

- [Требования](#требования)
- [Ветки и релизы](#ветки-и-релизы)
- [Сайт обновления (GitHub Pages)](#сайт-обновления-github-pages)
- [Целевая платформа в EDT](#целевая-платформа-в-edt)
- [Локальная сборка](#локальная-сборка)
- [Docker-сервисы](#docker-сервисы)
- [Уровни проверки](#уровни-проверки)

## Требования

* JDK 17+
* Maven 3.9+ (Tycho 4.0.5 на 3.8.x падает «requires Maven version 3.9.0»)
* Доступ к репозиторию EDT (credentials в `edt-syntax-help-export/connector/bom/edt-credentials.env`)
* Для MCP-стека: Docker + NVIDIA GPU (только для `docker/giga`; MCP — CPU)

## Ветки и релизы

* `develop` — рабочая интеграционная ветка (default). Признаки `feature/*` / `fix/*` заводятся от неё.
* `main` — стабильная: в неё попадают готовые изменения из `develop` (merge по готовности к релизу).
* Теги `X.Y.Z` ставятся только на `main`.

Релиз — пуш тега из `main`, дальше всё автоматом (workflow `release.yml`):
сборка Tycho со снятым `-SNAPSHOT`, GitHub Release с p2-zip и автоматическое
обновление сайта обновления (GitHub Pages, workflow `deploy-update-site.yml`).

Порядок выпуска версии (пример `0.2.0`):

```bash
# 1. В develop поднять версию (обновит pom, MANIFEST и feature):
cd edt-syntax-help-export/connector
mvn org.eclipse.tycho:tycho-versions-plugin:4.0.5:set-version -DnewVersion=0.2.0-SNAPSHOT -DgenerateBackupPoms=false
# 2. bom — родитель ВНЕ реактора, set-version его не трогает. Вручную поставить
#    0.2.0-SNAPSHOT в connector/bom/pom.xml (<version> bom'а) и в <parent><version>
#    файла connector/pom.xml.
# 3. Закоммитить в develop, слить в main и поставить тег:
git checkout main
git merge --no-ff develop
git tag 0.2.0
git push origin main develop --tags
```

Workflow сверяет тег с версией в pom: тег `0.2.0` требует `<version>0.2.0-SNAPSHOT</version>` в коммите.
У релизной сборки версия фиксированная (`set-version` снимает и `-SNAPSHOT`, и `.qualifier`),
в `develop` остаётся `X.Y.Z-SNAPSHOT` → `Bundle-Version: X.Y.Z.qualifier` — каждая сборка получает свой квалификатор с меткой времени.

CI (`ci.yml`) собирает каждый push/PR, после сборки гоняет анализ SonarCloud
(конфиг — `sonar-project.properties`, секрет `SONAR_TOKEN`; на форк-PR шаг пропускается).

### Сайт обновления (GitHub Pages)

Ссылка установки для пользователей (p2 лежит в корне Pages):

```
https://malikov-pro.github.io/bsl-syntax-help-mcp/
```

Публикует workflow `deploy-update-site.yml` (пуш тега, событие «релиз опубликован» или
вручную из вкладки Actions): собирает p2, кладёт его в корень Pages и дублирует
на старый путь `…/update/bsl-syntax-help-mcp/latest/` — у уже установленных
экземпляров EDT он прописан в «Доступных сайтах обновления», HTML-редирект p2
не понимает. EDT видит обновление по изменившемуся квалификатору.

Требуется:

1. `Settings → Pages → Source: GitHub Actions`.
2. Секреты `MAVEN_USERNAME` / `MAVEN_CENTRAL_TOKEN` (доступ к реджестри 1С).

## Целевая платформа в EDT

По умолчанию сборка идёт против **EDT 2025.2 + Eclipse 2025-12**
(`edt-syntax-help-export/connector/targets/default/default.target`);
профиль `-Pedt-2026.1` переключает p2-URL на EDT 2026.1.

`Reload Target Platform` есть только в **EDT для разработки плагинов** (PDE). В обычном EDT с конфигурациями 1С этого пункта нет: туда ставится уже собранный p2 (`Справка` → `Установить новое ПО`).

В PDE-workspace:

1. Вид **Project Explorer** (не Package Explorer).
2. Проект `default` (в `edt-syntax-help-export/connector/targets/default/`) → файл `default.target`. Для 2026.1 — `edt-2026.1/edt-2026.1.target`.
3. Либо **Окно → Параметры → Plug-in Development → Target Platform** → **Add** → **Workspace**.

## Локальная сборка

> Канонический путь — скрипт в корне репозитория: он делегирует в
> `edt-syntax-help-export/compile.sh` (entity-лимиты берёт из
> `connector/.mvn/jvm.config`) и печатает путь к p2-zip.

```bash
bash compile.sh
# профиль EDT 2026.1:
bash compile.sh --profile edt-2026.1
```

Ниже — те же шаги вручную (например, для Windows без bash):

> XML-entity лимиты уже заданы в `connector/.mvn/jvm.config` — Maven подхватывает их сам.

```bash
cd edt-syntax-help-export/connector
set -a && source bom/edt-credentials.env && set +a
mvn verify -s bom/settings.xml -Dtycho.localArtifacts=ignore
```

Результат сборки — p2-репозиторий в `edt-syntax-help-export/connector/repositories/com.github.malikov-pro.dt.bsl.syntaxhelp.repository/target/`.
Ставьте этот репозиторий в ту EDT, под которую собирали.

## Docker-сервисы

MCP-стек живёт в `docker/` и к плагину привязан только HTTP-контрактом ingest:

```bash
docker network create syntax-help   # один раз

cp docker/giga/.env.example docker/giga/.env
cp docker/mcp/.env.example docker/mcp/.env
# задать разные INGEST_TOKEN и MCP_TOKEN

docker compose -f docker/giga/docker-compose.yml up -d --build
docker compose -f docker/mcp/docker-compose.yml up -d --build
```

* `docker/giga` — OpenAI-совместимые эмбеддинги (`ai-sage/Giga-Embeddings-instruct`, dim 2048), GPU; первый старт тянет ~13 ГБ весов в `hf-cache/`.
* `docker/mcp` — FastAPI + FastMCP, SQLite FTS5 + sqlite-vec; размерность зафиксирована `EXPECTED_EMBED_DIM=2048` в `docker/mcp/app/config.py`.

Здоровье: `GET /health`, `/ready`, `/status` на `http://127.0.0.1:8004` (без токена).
Перенос готового корпуса между машинами — раздел «Move the SQLite corpus between machines» в [README](README.md).

## Уровни проверки

Зелёный нижний ярус не доказывает верхний: «собралось» ≠ «работает в EDT».

* **Ярус 0 — сборка:** `bash compile.sh` → BUILD SUCCESS, свежий квалификатор в имени p2-zip.
* **Ярус 1 — тесты:** юнит-тестов пока нет; план — чистая логика плагина (чанкинг карточек, клиент ingest) и Python-приложения (chunking, search).
* **Ярус 2 — живая установка:** установить p2 в EDT 2025.2, в `Окно → Параметры → Синтакс-помощник MCP` указать URL/`INGEST_TOKEN` и выполнить реальную «Выгрузить»; затем `docsearch` через MCP.
* **Ярус 3 — e2e в CI:** план; headless EDT через `p2 director`.
