#!/bin/sh
# FOREST's Proxy Auto-updater
# Copyright (C) 2026 FOREST
# SPDX-License-Identifier: GPL-3.0-only
#
# install.sh — установка из портативного .tar.gz в ЛЮБОМ дистрибутиве.
#
#   sudo ./install.sh                 # системная установка (/usr, /etc, служба)
#   ./install.sh --user               # только для текущего пользователя
#   sudo ./install.sh --dry-run       # показать план, ничего не менять
#   sudo ./install.sh --prefix /opt   # другой префикс (по умолчанию /usr)
#
# Внутри архива уже лежит всё нужное: самодостаточный ELF (Python + ядро xray +
# гео-базы внутри), юниты systemd, конфиг по умолчанию, документация.
# Никаких интерактивных вопросов и никаких окон.
set -eu

APP=forest-proxy-updater
HERE=$(cd "$(dirname "$0")" && pwd)
ELF_SRC="$HERE/$APP"

MODE=system
DRY=0
PREFIX=""
while [ $# -gt 0 ]; do
    case "$1" in
        --user)          MODE=user; shift ;;
        --system)        MODE=system; shift ;;
        --prefix)        PREFIX="$2"; shift 2 ;;
        --dry-run|-n)    DRY=1; shift ;;
        --yes|-y)        shift ;;               # вопросов и так нет
        -h|--help)       sed -n '2,20p' "$0"; exit 0 ;;
        *) echo "install.sh: неизвестный аргумент: $1" >&2; exit 2 ;;
    esac
done

# ── пути ────────────────────────────────────────────────────────────────────
if [ "$MODE" = user ]; then
    : "${PREFIX:=$HOME/.local}"
    # Та же раскладка, что у штатного `--install` продукта: ~/.local/share/<app>.
    # Иначе установка из архива и установка через AppImage/`--install` создавали
    # бы два разных дерева файлов для одного и того же продукта.
    LIBDIR="$PREFIX/share/$APP"
    BINDIR="$PREFIX/bin"
    UNITDIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
    CONFDIR="${XDG_CONFIG_HOME:-$HOME/.config}/$APP"
    STATEDIR="${XDG_STATE_HOME:-$HOME/.local/state}/$APP"
    DOCDIR="$PREFIX/share/doc/$APP"
    LICDIR="$PREFIX/share/licenses/$APP"
else
    : "${PREFIX:=/usr}"
    LIBDIR="$PREFIX/lib/$APP"
    BINDIR="$PREFIX/bin"
    UNITDIR="/usr/lib/systemd/system"
    CONFDIR="/etc/$APP"
    STATEDIR="/var/lib/$APP"
    DOCDIR="$PREFIX/share/doc/$APP"
    LICDIR="$PREFIX/share/licenses/$APP"
fi
CONFIG="$CONFDIR/config.json"
STATE_HOME="$STATEDIR/state"
DATA_HOME="$STATEDIR/data"
TEMPLATES="$HERE/systemd"

[ -f "$ELF_SRC" ] || { echo "install.sh: рядом нет $ELF — распакуйте архив целиком" >&2; exit 3; }
[ -x "$ELF_SRC" ] || chmod +x "$ELF_SRC" 2>/dev/null || true

echo "== FOREST's Proxy Auto-updater: установка ($MODE) =="
echo "  программа:  $LIBDIR/$APP"
echo "  команда:    $BINDIR/$APP"
echo "  конфиг:     $CONFIG"
echo "  состояние:  $STATE_HOME"
if [ "$MODE" = user ]; then
    echo "  юниты:      $UNITDIR/$APP.service (systemctl --user)"
else
    echo "  юниты:      $UNITDIR/$APP.service (systemd, системная служба)"
fi

run() {   # run <команда...> — в dry-run только печатает
    if [ "$DRY" = 1 ]; then
        printf '  [dry-run] %s\n' "$*"
        return 0
    fi
    "$@"
}

# ── права ───────────────────────────────────────────────────────────────────
if [ "$MODE" = system ] && [ "$(id -u)" != 0 ] && [ "$DRY" != 1 ]; then
    echo "install.sh: системная установка требует root. Запустите с sudo:" >&2
    echo "  sudo $0" >&2
    echo "Либо установка только для себя (без sudo):  $0 --user" >&2
    exit 4
fi

# ── 1. программа ────────────────────────────────────────────────────────────
echo "== файлы =="
run mkdir -p "$LIBDIR" "$BINDIR"
run install -m 0755 "$ELF_SRC" "$LIBDIR/$APP"
run ln -sf "$LIBDIR/$APP" "$BINDIR/$APP"

# ── 2. юниты systemd (тот же шаблон, что и в пакетах) ───────────────────────
render_unit() {   # render_unit <файл-шаблон> <куда>
    sed -e "s|@EXEC@|$LIBDIR/$APP|g" \
        -e "s|@WORKDIR@|$LIBDIR|g" \
        -e "s|@ROOT@|$STATEDIR|g" \
        -e "s|@CONFIG@|$CONFIG|g" \
        -e "s|@STATE_HOME@|$STATE_HOME|g" \
        -e "s|@DATA_HOME@|$DATA_HOME|g" \
        -e "s|@DOCDIR@|$DOCDIR|g" \
        "$1" > "$2"
}
if [ -d "$TEMPLATES" ]; then
    if [ "$DRY" = 1 ]; then
        echo "  [dry-run] установлю юниты в $UNITDIR:"
        for t in "$TEMPLATES"/*.service "$TEMPLATES"/*.timer; do
            [ -f "$t" ] && echo "  [dry-run]   $(basename "$t")"
        done
    else
        mkdir -p "$UNITDIR"
        for t in "$TEMPLATES"/*.service "$TEMPLATES"/*.timer; do
            [ -f "$t" ] || continue
            render_unit "$t" "$UNITDIR/$(basename "$t")"
            echo "  юнит: $UNITDIR/$(basename "$t")"
        done
    fi
else
    echo "  юнитов в архиве нет — автозапуск придётся настроить вручную" >&2
fi

# ── 3. конфиг (существующий не трогаем) ─────────────────────────────────────
echo "== конфиг =="
if [ -f "$CONFIG" ]; then
    echo "  уже есть, оставляю: $CONFIG"
else
    run mkdir -p "$CONFDIR"
    run install -m 0644 "$HERE/config.example.json" "$CONFIG"
    echo "  создан: $CONFIG"
fi

# ── 4. состояние ────────────────────────────────────────────────────────────
echo "== состояние =="
run mkdir -p "$STATEDIR"
run chmod 0755 "$STATEDIR"

# ── 5. документация и лицензия ──────────────────────────────────────────────
echo "== документация =="
run mkdir -p "$DOCDIR" "$LICDIR"
for f in README.md INSTALL.md INSTALL.ru.md PACKAGE-README.md copyright COPYING TERMS.md TERMS.ru.md; do
    [ -f "$HERE/doc/$f" ] && run install -m 0644 "$HERE/doc/$f" "$DOCDIR/$f"
done
[ -f "$HERE/doc/COPYING" ] && run install -m 0644 "$HERE/doc/COPYING" "$LICDIR/COPYING"
echo "  документация: $DOCDIR"

# ── 6. служба ───────────────────────────────────────────────────────────────
echo "== служба =="
if [ ! -d /run/systemd/system ]; then
    echo "  systemd не используется (/run/systemd/system отсутствует)."
    echo "  Запуск вручную:"
    echo "    FOREST_ROOT=$STATEDIR FOREST_CONFIG=$CONFIG \\"
    echo "    XDG_STATE_HOME=$STATE_HOME $BINDIR/$APP --run"
elif [ "$MODE" = user ]; then
    if [ "$DRY" = 1 ]; then
        echo "  [dry-run] systemctl --user daemon-reload"
        echo "  [dry-run] systemctl --user enable --now $APP.service"
        echo "  [dry-run] loginctl enable-linger $USER"
    else
        systemctl --user daemon-reload >/dev/null 2>&1 || true
        if systemctl --user enable --now "$APP.service" >/dev/null 2>&1; then
            echo "  служба пользователя включена: systemctl --user status $APP.service"
        else
            echo "  службу пользователя включить не удалось. Проверьте:"
            echo "    systemctl --user is-system-running   # должен быть running"
            echo "    loginctl enable-linger \$USER"
            echo "  В WSL нужен systemd: /etc/wsl.conf -> [boot] systemd=true"
        fi
        if loginctl enable-linger "$USER" >/dev/null 2>&1; then
            echo "  автозапуск без входа в систему (linger): включён"
        else
            echo "  linger не включён — нужен root: sudo loginctl enable-linger $USER"
        fi
    fi
else
    if [ "$DRY" = 1 ]; then
        echo "  [dry-run] systemctl daemon-reload"
        echo "  [dry-run] systemctl enable --now $APP.service"
    else
        systemctl daemon-reload >/dev/null 2>&1 || true
        if systemctl enable --now "$APP.service" >/dev/null 2>&1; then
            echo "  служба включена и запущена: systemctl status $APP.service"
        else
            echo "  службу запустить не удалось, смотрите журнал:"
            echo "    journalctl -u $APP.service -n 50 --no-pager"
        fi
    fi
fi

cat <<EOF

Установка завершена.
  Проверка связи (первые минуты идёт подбор серверов):
    curl -x http://127.0.0.1:10808 -o /dev/null -w '%{http_code}\\n' \\
         https://www.gstatic.com/generate_204          # ожидается 204
  Журнал:
    $( [ "$MODE" = user ] && echo "journalctl --user -u $APP -f" || echo "journalctl -u $APP -f" )
  Удаление:
    $HERE/uninstall.sh$( [ "$MODE" = user ] && echo " --user" )

Программа даёт доступ ко всем сайтам, включая заблокированные.
Ответственность за соблюдение законов своей юрисдикции лежит на пользователе.
Условия использования: $DOCDIR/TERMS.ru.md (English: TERMS.md).
EOF
