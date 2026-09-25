#!/usr/bin/env bash
# Установка собранного плагина в инсталляцию 1С:EDT через p2 director
# (без GUI «Установить новое ПО»). EDT во время установки должна быть ЗАКРЫТА.
#
# Использование:
#   bash scripts/deploy-edt.sh                          # авто-поиск EDT
#   bash scripts/deploy-edt.sh --edt "/путь/к/1cedt"    # своя инсталляция (каталог с 1cedt)
#
# Репозиторий берётся последний собранный:
#   connector/repositories/com.github.malikov-pro.dt.bsl.syntaxhelp.repository/target/repository

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_REPO="$ROOT/connector/repositories/com.github.malikov-pro.dt.bsl.syntaxhelp.repository/target/repository"
FEATURE_IU="com.github.malikov-pro.dt.bsl.syntaxhelp.feature.group"
BUNDLE_ID="com.github.malikov-pro.dt.bsl.syntaxhelp"

REPO=""
EDT=""

usage() { sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }
log() { echo "[deploy] $*"; }
die() { echo "[deploy] ОШИБКА: $*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --edt)  [[ $# -ge 2 ]] || die "--edt требует значение"; EDT="$2"; shift 2 ;;
        --repo) [[ $# -ge 2 ]] || die "--repo требует значение"; REPO="$2"; shift 2 ;;
        -h|--help) usage ;;
        *)      die "Неизвестный флаг: $1 (см. --help)" ;;
    esac
done

[[ -d "$REPO" ]] || REPO="$DEFAULT_REPO"
[[ -d "$REPO" ]] || die "p2-репозиторий не найден: $REPO (сначала bash compile.sh)"

if [[ -z "$EDT" ]]; then
    BASE="$HOME/.local/share/1C/1cedtstart/installations"
    EDT="$(ls -d "$BASE"/1C_EDT*/*/ 2>/dev/null | head -n 1 || true)"
    [[ -n "$EDT" ]] || die "инсталляция 1C_EDT не найдена в $BASE — передайте --edt"
fi

EDT="${EDT%/}"
[[ -x "$EDT/1cedt" ]] || die "$EDT/1cedt не найден или не исполняемый"

# EDT должна быть закрыта: p2 блокирует профиль. Лаунчер 1cedtstart не считаем EDT.
if pgrep -f "$EDT/1cedt( |$)" >/dev/null 2>&1 || pgrep -x 1cedt >/dev/null 2>&1; then
    die "инсталляция $EDT запущена — закройте EDT и повторите (процесс не убиваем)"
fi

REPO_URI="file://$(cd "$REPO" && pwd)"
log "EDT        : $EDT"
log "Репозиторий: $REPO_URI"

log "Снятие прежней копии (если была)…"
"$EDT/1cedt" -nosplash \
    -application org.eclipse.equinox.p2.director \
    -uninstallIU "$FEATURE_IU" \
    -profileProperties org.eclipse.update.reconcile=true 2>/dev/null || true

log "Установка IU: $FEATURE_IU"

"$EDT/1cedt" -nosplash \
    -application org.eclipse.equinox.p2.director \
    -repository "$REPO_URI" \
    -installIU "$FEATURE_IU" \
    -profileProperties org.eclipse.update.reconcile=true

EXPECTED_JAR="$(ls "$REPO"/plugins/${BUNDLE_ID}_*.jar | tail -n 1)"
EXPECTED_VER="$(basename "$EXPECTED_JAR" .jar)"
BUNDLES_INFO="$EDT/configuration/org.eclipse.equinox.simpleconfigurator/bundles.info"
if ! grep -qF "$EXPECTED_VER" "$BUNDLES_INFO"; then
    die "в $BUNDLES_INFO нет $EXPECTED_VER"
fi

sed -i "/${BUNDLE_ID},/ { /${EXPECTED_VER}/!d; }" "$BUNDLES_INFO"

REFERENCED="$(mktemp)"
for info in "$BUNDLES_INFO" \
    "$HOME/.local/share/1C/1cedtstart/installations/"1C_EDT*/*/configuration/org.eclipse.equinox.simpleconfigurator/bundles.info; do
    [[ -f "$info" ]] || continue
    grep -hF "$BUNDLE_ID," "$info" >> "$REFERENCED" || true
done

REMOVED=0
for jar in "$HOME/.p2/pool/plugins/${BUNDLE_ID}_"*.jar; do
    [[ -f "$jar" ]] || continue
    base="$(basename "$jar")"
    if ! grep -qF "$base" "$REFERENCED"; then
        rm -f "$jar"
        REMOVED=$((REMOVED + 1))
    fi
done
rm -f "$REFERENCED"
if [[ "$REMOVED" -gt 0 ]]; then
    log "Удалено устаревших jar из пула: $REMOVED"
fi

log "ГОТОВО, установлен: $(basename "$EXPECTED_JAR")"
log "Запустите EDT: Окно → Параметры → Синтакс-помощник MCP"
