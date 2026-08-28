# Выгрузка синтакс-помощника из EDT

Tycho-плагин для 1С:EDT. Читает синтакс-помощник через `PlatformDocProvider` (`getTree` + `loadPage`) и шлёт карточки по HTTP в Docker MCP на `http://127.0.0.1:8004`. SQLite JDBC в плагине нет.

Каркас как у [bslls-connector-for-edt](https://github.com/malikov-pro/bslls-connector-for-edt) и [гайда 1С](https://edt.1c.ru/dev/ru/docs/plugins/project/).

## Сборка

Нужны JDK **17**, Maven **3.9+**, доступ к p2 EDT (`connector/bom/edt-credentials.env`, файл в git не кладётся).

```bash
cd edt-syntax-help-export
cp connector/bom/edt-credentials.env.example connector/bom/edt-credentials.env
# заполните MAVEN_USERNAME / MAVEN_CENTRAL_TOKEN (учётка edt.1c.ru)

bash compile.sh
# EDT 2026.1:
bash compile.sh --profile edt-2026.1
```

Или вручную:

```bash
cd connector
set -a && source bom/edt-credentials.env && set +a
mvn verify -s bom/settings.xml -Dtycho.localArtifacts=ignore
```

Результат: `connector/repositories/com.github.malikov-pro.dt.bsl.syntaxhelp.repository/target/*.zip`.

## Установка в EDT

EDT должна быть **закрыта**.

```bash
bash scripts/deploy-edt.sh
# своя инсталляция:
bash scripts/deploy-edt.sh --edt "$HOME/.local/share/1C/1cedtstart/installations/1C_EDT 2025.2/1cedt"
```

Скрипт ставит IU `com.github.malikov-pro.dt.bsl.syntaxhelp.feature.group` через p2 director в первую найденную `~/.local/share/1C/1cedtstart/installations/1C_EDT*`.

Из архива вручную:

1. `Справка` → `Установить новое ПО` → `Добавить` → `Архив` → zip из `target/`.
2. **Снимите** флажок `Обращаться во время инсталляции ко всем сайтам обновления…`. Иначе p2 лезет на `services.1c.dev` (ошибка аутентификации) и потом не находит локальные артефакты (`No repository found containing`).
3. Выберите фичу → `Далее` → `Готово` → перезапустите EDT.

## Настройки

`Окно` → `Параметры` → `Синтакс-помощник MCP`:

- URL контейнера, по умолчанию `http://127.0.0.1:8004`
- `INGEST_TOKEN` (тот же, что в `docker/mcp/.env`)
- слои: `base`, `8.3.25`, `8.3.26`, `8.3.27`, `8.5.1`

Кнопки (работают в `WorkspaceJob`, не в UI-потоке):

- **Выгрузить** — `POST /ingest/begin` → батчи по ~200 → `POST /ingest/commit`
- **Обновить статус** — `GET /status`
- **Очистить слои** — `DELETE /admin/layers/{layer}` для отмеченных
- **Очистить базу** — `DELETE /admin/database` с `{"confirm":true}`

Карточка: обязательны `doc_id`, `layer`, `kind`, `full_name_ru`, `body_text` (HTML страницы в plaintext).
