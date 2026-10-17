#!/bin/sh
# FOREST's Proxy Auto-updater
# Copyright (C) 2026 FOREST
# SPDX-License-Identifier: GPL-3.0-only
#
# uninstall.sh — полное удаление установки из портативного .tar.gz.
#
#   sudo ./uninstall.sh                 # снять системную установку и все следы
#   ./uninstall.sh --user               # снять установку для текущего пользователя
#   sudo ./uninstall.sh --dry-run       # показать план, ничего не менять
#   sudo ./uninstall.sh --keep-config   # оставить конфиг в /etc
#
# Идемпотентен: повторный запуск на чистой системе ничего не ломает.
set -eu

APP=forest-proxy-updater
MODE=system
DRY=0
KEEP_CONFIG=0
PREFIX=""
while [ $# -gt 0 ]; do
    case "$1" in
        --user)          MODE=user; shift ;;
        --system)        MODE=system; shift ;;
        --prefix)        PREFIX="$2"; shift 2 ;;
        --dry-run|-n)    DRY=1; shift ;;
        --keep-config)   KEEP_CONFIG=1; shift ;;
        --yes|-y)        shift ;;
        -h|--help)       sed -n '2,16p' "$0"; exit 0 ;;
        *) echo "uninstall.sh: неизвестный аргумент: $1" >&2; exit 2 ;;
    esac
done

if [ "$MODE" = user ]; then
    : "${PREFIX:=$HOME/.local}"
    LIBDIR="$PREFIX/share/$APP"      # та же раскладка, что у `--install` продукта
    UNITDIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
    CONFDIR="${XDG_CONFIG_HOME:-$HOME/.config}/$APP"
    STATEDIR="${XDG_STATE_HOME:-$HOME/.local/state}/$APP"
    SYSTEMCTL="systemctl --user"
else
    : "${PREFIX:=/usr}"
    UNITDIR="/usr/lib/systemd/system"
    CONFDIR="/etc/$APP"
    STATEDIR="/var/lib/$APP"
    SYSTEMCTL="systemctl"
fi
LIBDIR="$PREFIX/lib/$APP"
BINDIR="$PREFIX/bin"
DOCDIR="$PREFIX/share/doc/$APP"
LICDIR="$PREFIX/share/licenses/$APP"
# в пользовательском режиме раскладка другая (как у `--install` продукта)
if [ "$MODE" = user ]; then
    LIBDIR="$PREFIX/share/$APP"
fi

if [ "$MODE" = system ] && [ "$(id -u)" != 0 ] && [ "$DRY" != 1 ]; then
    echo "uninstall.sh: системное удаление требует root. Запустите с sudo:" >&2
    echo "  sudo $0" >&2
    exit 4
fi

run() {
    if [ "$DRY" = 1 ]; then
        printf '  [dry-run] %s\n' "$*"
        return 0
    fi
    "$@"
}

echo "== удаление FOREST's Proxy Auto-updater ($MODE) =="

echo "== служба =="
if [ -d /run/systemd/system ]; then
    # --now останавливает; KillMode=control-group в юните снимает и ядро xray,
    # поэтому порт освобождается вместе со службой
    if [ "$DRY" = 1 ]; then
        echo "  [dry-run] $SYSTEMCTL disable --now $APP.service $APP.timer"
    else
        # shellcheck disable=SC2086
        $SYSTEMCTL disable --now "$APP.service" >/dev/null 2>&1 || true
        # shellcheck disable=SC2086
        $SYSTEMCTL disable --now "$APP.timer"   >/dev/null 2>&1 || true
        echo "  служба остановлена и снята с автозапуска"
    fi
else
    echo "  systemd не используется — останавливать нечего"
fi

echo "== файлы =="
for f in "$UNITDIR/$APP.service" "$UNITDIR/$APP-refresh.service" "$UNITDIR/$APP.timer"; do
    [ -e "$f" ] || continue
    run rm -f "$f"
    echo "  удалён: $f"
done
for d in "$LIBDIR" "$DOCDIR" "$LICDIR"; do
    [ -d "$d" ] || continue
    run rm -rf "$d"
    echo "  удалён: $d"
done
if [ -L "$BINDIR/$APP" ] || [ -e "$BINDIR/$APP" ]; then
    run rm -f "$BINDIR/$APP"
    echo "  удалён: $BINDIR/$APP"
fi

echo "== состояние =="
if [ -d "$STATEDIR" ]; then
    run rm -rf "$STATEDIR"
    echo "  удалён: $STATEDIR"
else
    echo "  нет каталога состояния"
fi

echo "== конфиг =="
if [ "$KEEP_CONFIG" = 1 ]; then
    echo "  оставлен по флагу --keep-config: $CONFDIR"
else
    if [ -d "$CONFDIR" ]; then
        run rm -rf "$CONFDIR"
        echo "  удалён: $CONFDIR"
    else
        echo "  нет каталога конфига"
    fi
fi

if [ -d /run/systemd/system ] && [ "$DRY" != 1 ]; then
    # shellcheck disable=SC2086
    $SYSTEMCTL daemon-reload >/dev/null 2>&1 || true
    echo "  daemon-reload выполнен"
fi

echo
echo "Удаление завершено. Проверка:"
echo "  ${SYSTEMCTL} is-active $APP.service     # inactive/unknown"
if [ "$MODE" = system ]; then
    echo "  command -v $APP || echo 'команды нет — ок'"
    echo "  ls $STATEDIR 2>/dev/null || echo 'следов нет — ок'"
fi
