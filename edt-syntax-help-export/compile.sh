#!/usr/bin/env bash
# Сборка Tycho-плагина выгрузки синтакс-помощника: mvn clean verify, затем путь к p2-zip.
#
# XML-entity лимиты подхватывает connector/.mvn/jvm.config.
#
# Использование:
#   bash compile.sh                     # EDT 2025.2
#   bash compile.sh --profile edt-2026.1
#   bash compile.sh --java-home /usr/lib/jvm/axiom-jdk-full-17.0.16+12-x86_64 --maven-home /opt/maven

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONNECTOR="$ROOT/connector"
REPO_DIR="$CONNECTOR/repositories/com.github.malikov-pro.dt.bsl.syntaxhelp.repository/target"

PROFILE=""

usage() {
    sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --profile)         [[ $# -ge 2 ]] || { echo "--profile требует значение" >&2; exit 1; }; PROFILE="$2"; shift 2 ;;
        --profile=*)       PROFILE="${1#*=}"; shift ;;
        --java-home)       [[ $# -ge 2 ]] || { echo "--java-home требует значение" >&2; exit 1; }; JAVA_HOME_ARG="$2"; shift 2 ;;
        --java-home=*)     JAVA_HOME_ARG="${1#*=}"; shift ;;
        --maven-home)      [[ $# -ge 2 ]] || { echo "--maven-home требует значение" >&2; exit 1; }; MAVEN_HOME_ARG="$2"; shift 2 ;;
        --maven-home=*)    MAVEN_HOME_ARG="${1#*=}"; shift ;;
        -h|--help)         usage ;;
        *)                 echo "Неизвестный флаг: $1" >&2; usage >&2; exit 2 ;;
    esac
done

log()  { echo "[compile] $*"; }
die()  { echo "[compile] ОШИБКА: $*" >&2; exit 1; }

pick_java17() {
    local candidates=(
        "${JAVA_HOME_ARG:-}"
        "/usr/lib/jvm/axiom-jdk-full-17.0.16+12-x86_64"
        "/opt/1C/1CE/components/axiom-jdk-full-17.0.16+12-x86_64"
    )
    local cand
    for cand in "${candidates[@]}"; do
        if [[ -n "$cand" && -x "$cand/bin/java" ]]; then
            export JAVA_HOME="$cand"
            export PATH="$JAVA_HOME/bin:$PATH"
            return 0
        fi
    done
    return 1
}

if [[ -n "${JAVA_HOME_ARG:-}" ]]; then
    [[ -x "$JAVA_HOME_ARG/bin/java" ]] || die "bin/java не найден в --java-home: $JAVA_HOME_ARG"
    export JAVA_HOME="$JAVA_HOME_ARG"
    export PATH="$JAVA_HOME/bin:$PATH"
elif ! java -version 2>&1 | grep -q 'version "17'; then
    pick_java17 || log "Java 17 не найдена автоматически — сборка пойдёт с текущей JAVA_HOME"
fi

if [[ -n "${MAVEN_HOME_ARG:-}" ]]; then
    [[ -x "$MAVEN_HOME_ARG/bin/mvn" ]] || die "bin/mvn не найден в --maven-home: $MAVEN_HOME_ARG"
    MVN="$MAVEN_HOME_ARG/bin/mvn"
else
    command -v mvn >/dev/null || die "mvn не найден в PATH, передайте --maven-home (нужен Maven 3.9+)"
    MVN="$(command -v mvn)"
fi

log "JAVA_HOME : ${JAVA_HOME:-<из PATH>}"
log "Maven     : $MVN"

CRED_ENV="$CONNECTOR/bom/edt-credentials.env"
SETTINGS="$CONNECTOR/bom/settings.xml"
if [[ -f "$CRED_ENV" ]]; then
    # shellcheck disable=SC1090
    set -a; source "$CRED_ENV"; set +a
    log "Учётные данные: connector/bom/edt-credentials.env"
else
    log "connector/bom/edt-credentials.env не найден — если p2 EDT попросит авторизацию, см. connector/bom/edt-credentials.env.example"
fi

CMD=(clean verify --batch-mode -T 1C -Dtycho.localArtifacts=ignore)
[[ -f "$SETTINGS" ]] && CMD+=(-s "$SETTINGS")
[[ -n "$PROFILE" ]] && CMD+=(-P"$PROFILE")

log "Запуск: mvn ${CMD[*]} (в connector/)"
(cd "$CONNECTOR" && "$MVN" "${CMD[@]}")

ZIP="$(ls -t "$REPO_DIR"/*.zip 2>/dev/null | head -n 1 || true)"
[[ -n "$ZIP" ]] || die "p2-zip не найден в $REPO_DIR"

log "ГОТОВО: p2-репозиторий:"
echo "  $ZIP"
echo "  профиль: ${PROFILE:-по умолчанию (EDT 2025.2)}"
echo "Установка: Справка → Установить новое ПО → Добавить → Архив → этот zip"
echo "(флажок «Обращаться во время инсталляции ко всем сайтам…» СНЯТЬ)."
echo "Или: bash scripts/deploy-edt.sh  (EDT должна быть закрыта)."
