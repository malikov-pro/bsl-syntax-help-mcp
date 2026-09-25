#!/usr/bin/env bash
# Канонический локальный сценарий сборки bsl-syntax-help-mcp (плагин EDT).
# Делегирует в edt-syntax-help-export/compile.sh — воспроизводит то, что делает
# CI (.github/workflows/ci.yml): mvn clean verify, затем печатает путь к
# готовому p2-артефакту (zip) для установки в EDT.
#
# Таргет один — EDT 2026.2; артефакт ставится в EDT 2026.1 и 2026.2.
#
# Docker-сервисы (giga, mcp) собираются отдельно:
#   docker compose -f docker/giga/docker-compose.yml up -d --build
#   docker compose -f docker/mcp/docker-compose.yml up -d --build

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec bash "$DIR/edt-syntax-help-export/compile.sh" "$@"
