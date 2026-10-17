#!/bin/sh
# FOREST's Proxy Auto-updater
# Copyright (C) 2026 FOREST
# SPDX-License-Identifier: GPL-3.0-only
#
# build-ui.sh — сборка ПОМОЩНИКА ИНТЕРФЕЙСА (Qt) для Linux отдельным файлом.
#
#   sh packaging/build-ui.sh                # -> linux/dist/forest-ui (+ .sha256)
#   sh packaging/build-ui.sh --skip-venv    # использовать текущий python3
#   PYI_PYTHON=/path/to/python sh packaging/build-ui.sh
#
# Почему отдельный файл: Qt весит десятки мегабайт, а основная программа должна
# оставаться лёгкой и без сторонних зависимостей (см. packaging/forest-ui.spec).
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(dirname "$HERE")
OUT="$REPO/linux/dist"
WORK="$HERE/build-ui-linux"
VENV="$HERE/.build-venv-linux"

SKIP_VENV=0
for a in "$@"; do
    case "$a" in
        --skip-venv) SKIP_VENV=1 ;;
        *) echo "неизвестный аргумент: $a" >&2; exit 2 ;;
    esac
done

PY=${PYI_PYTHON:-python3}

echo "== 0/3 иконка пользователя (app.ico) =="
sh "$HERE/check_icon.sh" || exit 1

echo "== 1/3 окружение сборки (PyInstaller + PySide6-Essentials) =="
if [ "$SKIP_VENV" -eq 1 ]; then
    PYEXE="$PY"
else
    if [ ! -x "$VENV/bin/python" ]; then
        "$PY" -m venv "$VENV" || { echo "не удалось создать $VENV" >&2; exit 3; }
    fi
    PYEXE="$VENV/bin/python"
    # venv, созданный uv, идёт БЕЗ pip (и без ensurepip) — тогда ставим через uv
    if "$PYEXE" -m pip --version >/dev/null 2>&1; then
        "$PYEXE" -m pip install --disable-pip-version-check -q -r "$HERE/requirements-build.txt"
        "$PYEXE" -m pip install --disable-pip-version-check -q -r "$HERE/requirements-ui.txt"
    elif command -v uv >/dev/null 2>&1; then
        uv pip install --python "$PYEXE" -q -r "$HERE/requirements-build.txt"
        uv pip install --python "$PYEXE" -q -r "$HERE/requirements-ui.txt"
    else
        "$PYEXE" -m ensurepip --upgrade >/dev/null 2>&1 || {
            echo "нет pip и нет uv — поставьте один из них" >&2; exit 3; }
        "$PYEXE" -m pip install --disable-pip-version-check -q -r "$HERE/requirements-build.txt"
        "$PYEXE" -m pip install --disable-pip-version-check -q -r "$HERE/requirements-ui.txt"
    fi
fi
"$PYEXE" -c "import PySide6, PyInstaller; print('PySide6', PySide6.__version__)"

echo "== 2/3 сборка forest-ui =="
mkdir -p "$OUT" "$WORK"
"$PYEXE" -m PyInstaller --noconfirm --clean \
    --distpath "$OUT" --workpath "$WORK" "$HERE/forest-ui.spec"

echo "== 3/3 отчёт =="
if command -v sha256sum >/dev/null 2>&1; then
    ( cd "$OUT" && sha256sum forest-ui > forest-ui.sha256 )
    cat "$OUT/forest-ui.sha256"
fi
ls -lh "$OUT/forest-ui"
