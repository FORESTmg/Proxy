#!/bin/sh
# FOREST's Proxy Auto-updater
# Copyright (C) 2026 FOREST
# SPDX-License-Identifier: GPL-3.0-only
#
# Сборка Linux-версии: один самодостаточный ELF (PyInstaller onefile).
#
#   sh build-linux.sh                 # ядро + сборка
#   sh build-linux.sh --skip-core     # без скачивания ядра (уже есть)
#   PYI_PYTHON=/path/to/python sh build-linux.sh   # свой интерпретатор сборки
#
# Результат: linux/dist/forest-proxy-updater (+ .sha256), ядро и гео-базы внутри.
#
# Почему отдельный venv: PyInstaller запускается на том интерпретаторе, под
# который собирается бинарь; системный python3 в Ubuntu не имеет pip
# (PEP 668) — сборка не должна требовать sudo.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(dirname "$HERE")
LINUX="$REPO/linux"
OUT="$LINUX/dist"
WORK="$HERE/build-linux"

SKIP_CORE=0
for a in "$@"; do
    case "$a" in
        --skip-core) SKIP_CORE=1 ;;
        *) echo "неизвестный аргумент: $a" >&2; exit 2 ;;
    esac
done

PY=${PYI_PYTHON:-python3}

echo "== 0/4 иконка пользователя (app.ico) =="
sh "$HERE/check_icon.sh" || exit 1

echo "== 1/4 ядро Xray-core (Linux x64) =="
if [ "$SKIP_CORE" -eq 1 ]; then
    "$PY" "$HERE/fetch_core_linux.py" --verify
else
    "$PY" "$HERE/fetch_core_linux.py"
fi

echo "== 2/4 PyInstaller =="
if ! "$PY" -c 'import PyInstaller' 2>/dev/null; then
    echo "PyInstaller не найден в $PY."
    echo "Создайте окружение сборки, например:"
    echo "  uv venv --python 3.12 $REPO/packaging/.build-venv-linux"
    echo "  uv pip install --python $REPO/packaging/.build-venv-linux/bin/python pyinstaller"
    echo "  PYI_PYTHON=$REPO/packaging/.build-venv-linux/bin/python sh $0"
    exit 3
fi
"$PY" -c 'import PyInstaller,sys; print("PyInstaller", PyInstaller.__version__, "|", sys.version.split()[0])'

echo "== 3/4 сборка (onefile) =="
mkdir -p "$OUT"
"$PY" -m PyInstaller --noconfirm --clean \
    --distpath "$OUT" --workpath "$WORK" \
    "$HERE/forest-proxy-updater-linux.spec"

echo "== 4/4 проверка артефакта =="
BIN="$OUT/forest-proxy-updater"
test -x "$BIN" || { echo "нет исполняемого файла $BIN" >&2; exit 4; }
file "$BIN" || true
ls -l "$BIN"
sha256sum "$BIN" | tee "$BIN.sha256"
echo
echo "Готово: $BIN"
echo "Проверка на чистой машине (без Python и venv):"
echo "  cd /tmp && /путь/к/$BIN --selftest"
