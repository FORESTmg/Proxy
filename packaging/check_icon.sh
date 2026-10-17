#!/bin/sh
# FOREST's Proxy Auto-updater
# Copyright (C) 2026 FOREST
# SPDX-License-Identifier: GPL-3.0-only
#
# check_icon.sh — проверка иконки пользователя перед сборкой.
#
#   sh packaging/check_icon.sh        # 0 — иконка на месте, 1 — нет
#
# Зачем: app.ico — РИСУНОК ПОЛЬЗОВАТЕЛЯ (собран из его PNG), а не картинка,
# нарисованная make_icon.py. Если файл потеряется, значок трея молча станет
# чужим. Сборка должна падать громко, а не подставлять другую иконку.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
ICON="$HERE/app.ico"
PIN="$HERE/app.ico.sha256"

if [ ! -f "$ICON" ]; then
    echo "ОШИБКА: нет иконки пользователя: $ICON" >&2
    echo "        Верните её из репозитория:  git checkout -- packaging/app.ico" >&2
    exit 1
fi

want=""
if [ -f "$PIN" ]; then
    want=$(grep -v '^[[:space:]]*#' "$PIN" | grep -v '^[[:space:]]*$' | head -n1 | awk '{print $1}')
fi
got=$(sha256sum "$ICON" | awk '{print $1}')

if [ -n "$want" ] && [ "$want" != "$got" ]; then
    echo "ВНИМАНИЕ: app.ico не совпадает с записанным хешем" >&2
    echo "  ожидалось: $want" >&2
    echo "  получено:  $got" >&2
    echo "  Если иконку обновили СОЗНАТЕЛЬНО — впишите новый хеш в packaging/app.ico.sha256" >&2
else
    echo "иконка app.ico на месте, sha256=$got"
fi
exit 0
