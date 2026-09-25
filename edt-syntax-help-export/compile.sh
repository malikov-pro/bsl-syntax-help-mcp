#!/usr/bin/env bash
# Сборка Tycho-плагина выгрузки синтакс-помощника: mvn clean verify, затем путь к p2-zip.
#
# XML-entity лимиты подхватывает connector/.mvn/jvm.config.
#
# Таргет один — EDT 2026.2 + Eclipse 2025-12; готовый артефакт ставится
# и в EDT 2026.1, и в EDT 2026.2 (байткод 17, как в EDT-MCP).
#
# Использование:
#   bash compile.sh
#   bash compile.sh --java-home ~/tools/jdk-25.0.4.1+1 --maven-home ~/tools/apache-maven-3.9.9
#
# Для запуска сборки нужен JDK 21+ (Tycho 5; читает классы Java 25 из таргета),
# сам бандл компилируется в байткод 17.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONNECTOR="$ROOT/connector"
REPO_DIR="$CONNECTOR/repositories/com.github.malikov-pro.dt.bsl.syntaxhelp.repository/target"

usage() {
    sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
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

java_major() {
    "$1" -version 2>&1 | sed -n '1s/.*version "\([0-9]*\).*/\1/p'
}

# Tycho 5 требует JDK 21+ (читает классы Java 25 из таргета EDT 2026.2).
pick_jdk() {
    local candidates=(
        "${JAVA_HOME_ARG:-}"
        "/home/$USER/tools"/jdk-25*/ 
        "/usr/lib/jvm"/jdk-25*/
        "/usr/lib/jvm"/java-25*/
        "/usr/lib/jvm"/jdk-21*/
        "/usr/lib/jvm"/java-21*/
    )
    local cand major
    for cand in "${candidates[@]}"; do
        [[ -n "$cand" && -x "$cand/bin/java" ]] || continue
        cand="${cand%/}"
        major="$(java_major "$cand/bin/java" || true)"
        [[ "${major:-0}" -ge 21 ]] || continue
        export JAVA_HOME="$cand"
        export PATH="$JAVA_HOME/bin:$PATH"
        return 0
    done
    return 1
}

if [[ -n "${JAVA_HOME_ARG:-}" ]]; then
    [[ -x "$JAVA_HOME_ARG/bin/java" ]] || die "bin/java не найден в --java-home: $JAVA_HOME_ARG"
    export JAVA_HOME="$JAVA_HOME_ARG"
    export PATH="$JAVA_HOME/bin:$PATH"
elif [[ -z "${JAVA_HOME:-}" ]] || [[ "$(java_major "${JAVA_HOME}/bin/java" 2>/dev/null || echo 0)" -lt 21 ]]; then
    pick_jdk || log "JDK 21+ не найден автоматически — сборка пойдёт с текущей JAVA_HOME (Tycho 5 требует JDK 21+)"
fi

if [[ -n "${JAVA_HOME:-}" ]]; then
    MAJOR="$(java_major "${JAVA_HOME}/bin/java" 2>/dev/null || echo 0)"
    [[ "$MAJOR" -ge 21 ]] || log "ВНИМАНИЕ: JAVA_HOME указывает на Java ${MAJOR:-?}; Tycho 5 требует JDK 21+, иначе сборка упадёт"
fi

if [[ -n "${MAVEN_HOME_ARG:-}" ]]; then
    [[ -x "$MAVEN_HOME_ARG/bin/mvn" ]] || die "bin/mvn не найден в --maven-home: $MAVEN_HOME_ARG"
    MVN="$MAVEN_HOME_ARG/bin/mvn"
else
    MVN="$(command -v mvn || true)"
    if [[ -z "$MVN" ]]; then
        for cand in /home/$USER/tools/apache-maven-*/bin/mvn /opt/apache-maven-*/bin/mvn; do
            [[ -x "$cand" ]] || continue
            MVN="$cand"
            break
        done
    fi
    [[ -n "$MVN" ]] || die "mvn не найден в PATH и в ~/tools — передайте --maven-home (нужен Maven 3.9+)"
fi

log "JAVA_HOME : ${JAVA_HOME:-<из PATH>} (Java $(java_major "${JAVA_HOME:-}/bin/java" 2>/dev/null || java -version 2>&1 | sed -n '1s/.*version "\([0-9]*\).*/\1/p'))"
log "Maven     : $MVN"

CRED_ENV="$CONNECTOR/bom/edt-credentials.env"
SETTINGS="$CONNECTOR/bom/settings.xml"
if [[ -f "$CRED_ENV" ]]; then
    # shellcheck disable=SC1090
    set -a; source "$CRED_ENV"; set +a
    log "Учётные данные: connector/bom/edt-credentials.env"
else
    log "connector/bom/edt-credentials.env не найден — p2 EDT запрашивается анонимно (публичный репозиторий релизов это позволяет)"
fi

CMD=(clean verify --batch-mode -T 1C -Dtycho.localArtifacts=ignore)
# settings.xml — только с реальными учётными данными: с незаданными
# ${env.MAVEN_*} литерал «{env.MAVEN_CENTRAL_TOKEN}» матчится Maven как
# зашифрованный пароль, и сборка падает на отсутствии
# ~/.m2/settings-security.xml при первом обращении транспорта к кредам.
if [[ -n "${MAVEN_CENTRAL_TOKEN:-}" && -f "$SETTINGS" ]]; then
    CMD+=(-s "$SETTINGS")
fi

log "Запуск: mvn ${CMD[*]} (в connector/)"
(cd "$CONNECTOR" && "$MVN" "${CMD[@]}")

ZIP="$(ls -t "$REPO_DIR"/*.zip 2>/dev/null | head -n 1 || true)"
[[ -n "$ZIP" ]] || die "p2-zip не найден в $REPO_DIR"

log "ГОТОВО: p2-репозиторий:"
echo "  $ZIP"
echo "  таргет: EDT 2026.2 (артефакт ставится в EDT 2026.1 и 2026.2)"
echo "Установка с сайта обновления:"
echo "  https://malikov-pro.github.io/bsl-syntax-help-mcp/"
echo "Локально: Справка → Установить новое ПО → Добавить → Архив → этот zip"
echo "(для архива флажок «Обращаться во время инсталляции ко всем сайтам…» СНЯТЬ)."
echo "Или: bash scripts/deploy-edt.sh  (EDT должна быть закрыта)."
