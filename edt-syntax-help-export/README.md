# Выгрузка синтакс-помощника из EDT

Tycho-плагин для 1С:EDT. Читает синтакс-помощник через `PlatformDocProvider` (`getTree` + `loadPage`) и шлёт карточки по HTTP в Docker MCP на `http://127.0.0.1:8004`. SQLite JDBC в плагине нет.

Каркас как у [bslls-connector-for-edt](https://github.com/malikov-pro/bslls-connector-for-edt) и [гайда 1С](https://edt.1c.ru/dev/ru/docs/plugins/project/).

## Сборка

Нужны JDK **21+** (лучше 25 — Tycho 5 читает классы Java 25 из таргета),
Maven **3.9+**, доступ к p2 EDT (`connector/bom/edt-credentials.env`, файл в git не кладётся).
Сам бандл компилируется в байткод 17, поэтому готовый артефакт ставится и в EDT 2026.1, и в EDT 2026.2.

```bash
# из корня репозитория (канонический путь):
bash compile.sh
# или отсюда:
cp connector/bom/edt-credentials.env.example connector/bom/edt-credentials.env
# заполните MAVEN_USERNAME / MAVEN_CENTRAL_TOKEN (учётка edt.1c.ru)

bash compile.sh
```

Или вручную:

```bash
cd connector
set -a && source bom/edt-credentials.env && set +a
mvn verify -s bom/settings.xml -Dtycho.localArtifacts=ignore
```

Результат: `connector/repositories/com.github.malikov-pro.dt.bsl.syntaxhelp.repository/target/*.zip`.

## Установка в EDT

1. Откройте `Справка` → `Установить новое ПО`.
2. Введите ссылку:

```
https://malikov-pro.github.io/bsl-syntax-help-mcp/update/bsl-syntax-help-mcp/latest/
```

3. Нажмите `Добавить`.
4. Установите флажок на `BSL syntax-help export for EDT`.
5. Убедитесь, что установлен флажок `Обращаться во время инсталляции ко всем сайтам обновления для поиска требуемого ПО`.
6. Нажмите `Далее` → `Готово`.
7. Перезапустите 1С:EDT.

### Установка из архива

1. `Справка` → `Установить новое ПО` → `Добавить` → `Архив` → zip из `connector/repositories/…/target/`.
2. **Снимите** флажок `Обращаться во время инсталляции ко всем сайтам обновления…`. Иначе p2 лезет на `services.1c.dev` (ошибка аутентификации) и потом не находит локальные артефакты (`No repository found containing`).
3. Выберите `BSL syntax-help export for EDT` → `Далее` → `Готово` → перезапустите EDT.

С закрытой EDT можно поставить через p2 director:

```bash
bash scripts/deploy-edt.sh
# своя инсталляция:
bash scripts/deploy-edt.sh --edt "$HOME/.local/share/1C/1cedtstart/installations/1C_EDT 2026.1/1cedt"
```

### Публикация сайта обновления

Основная ссылка установки — p2 в корне GitHub Pages:

```
https://malikov-pro.github.io/bsl-syntax-help-mcp/
```

Копия на длинном пути сохранена для уже установленных EDT (HTML-редирект p2 не понимает):

```
https://malikov-pro.github.io/bsl-syntax-help-mcp/update/bsl-syntax-help-mcp/latest/
```

Публикует workflow `deploy-update-site.yml` (пуш тега `X.Y.Z`, событие «релиз опубликован» или вручную из Actions): собирает p2 и перезаписывает обе копии. Порядок релизов — [DEVELOPER.md](../DEVELOPER.md). Нужны:

1. `Settings → Pages → Source: GitHub Actions`.
2. Секреты `MAVEN_USERNAME` / `MAVEN_CENTRAL_TOKEN` (реджестри EDT, те же, что у [bslls-connector-for-edt](https://github.com/malikov-pro/bslls-connector-for-edt)).

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
