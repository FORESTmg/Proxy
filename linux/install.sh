#!/bin/sh
# FOREST's Proxy Auto-updater
# Copyright (C) 2026 FOREST
# SPDX-License-Identifier: GPL-3.0-only
#
# Удобная обёртка вокруг `--install`: запускает установщик и печатает,
# что делать дальше. Никаких окон и диалогов.
#
#   sh install.sh [--port 10808] [--dry]
#
# Ставить лучше НЕ из этого скрипта, а из самой программы:
#   ./forest-proxy-updater --install
# здесь — только подсказки и проверка окружения.
set -eu

DRY=0
PORT=""
while [ $# -gt 0 ]; do
    case "$1" in
        --port) PORT="$2"; shift 2 ;;
        --dry)  DRY=1; shift ;;
        -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
        *) echo "неизвестный аргумент: $1" >&2; exit 2 ;;
    esac
done

HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(dirname "$HERE")
BIN="$HERE/dist/forest-proxy-updater"

echo "== проверка окружения =="
printf '%-24s %s\n' "systemd (/run/systemd/system)" \
    "$( [ -d /run/systemd/system ] && echo есть || echo 'НЕТ — автозапуск недоступен' )"
printf '%-24s %s\n' "systemctl --user" \
    "$( systemctl --user is-system-running >/dev/null 2>&1 && echo работает || echo 'не отвечает (нужен linger: loginctl enable-linger $USER)' )"
printf '%-24s %s\n' "notify-send" \
    "$( command -v notify-send >/dev/null 2>&1 && echo есть || echo 'нет (уведомления только в лог)' )"
printf '%-24s %s\n' "gsettings" \
    "$( command -v gsettings >/dev/null 2>&1 && echo есть || echo 'нет (системный прокси не трогаем)' )"

if [ -x "$BIN" ]; then
    CMD="$BIN"
elif [ -f "$HERE/dist/forest-proxy-updater" ]; then
    CMD="$BIN"
else
    CMD="python3 $REPO/src/v2ray_updater.py"
    echo "Собранного ELF нет — использую исходники: $CMD"
fi

if [ "$DRY" -eq 1 ]; then
    echo "== dry-run: ничего не запускаю =="
    exit 0
fi

if [ -n "$PORT" ]; then
    echo "== задаю порт $PORT в конфиге (если файл уже есть) =="
    CFG="${XDG_CONFIG_HOME:-$HOME/.config}/forest-proxy-updater/config.json"
    if [ -f "$CFG" ]; then
        python3 - "$CFG" "$PORT" <<'PY'
import json, sys
p, port = sys.argv[1], int(sys.argv[2])
d = json.load(open(p, encoding="utf-8"))
d.setdefault("client", {})["socks_port"] = port
json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("порт в конфиге:", port)
PY
    else
        echo "конфига ещё нет — установлю с портом по умолчанию, поменяйте после"
    fi
fi

echo "== установка =="
# shellcheck disable=SC2086
$CMD --install

cat <<EOF

Дальше:
  systemctl --user status forest-proxy-updater.service
  $CMD --status
  journalctl --user -u forest-proxy-updater -f
Удалить:
  $CMD --uninstall
EOF
