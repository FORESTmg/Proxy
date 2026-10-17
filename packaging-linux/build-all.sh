#!/usr/bin/env bash
# FOREST's Proxy Auto-updater
# Copyright (C) 2026 FOREST
# SPDX-License-Identifier: GPL-3.0-only
#
# build-all.sh — собирает все форматы, которые возможны на этой машине.
#
#   sh packaging-linux/build-all.sh
#   FOREST_PKG_VERSION=1.0.2 sh build-all.sh
#
# Форматы без своих инструментов пропускаются с внятным сообщением (это не
# ошибка: например, на Arch нет dpkg-deb, а на Debian — makepkg). Готовые файлы
# попадают в packaging-linux/out/, сводка печатается в конце.
set -u

. "$(cd "$(dirname "$0")" && pwd)/lib/common.sh"

step "что можно собрать на этой машине"
have_dpkg=0; have_rpm=0; have_arch=0; have_appimage=0
command -v dpkg-deb  >/dev/null 2>&1 && have_dpkg=1
command -v rpmbuild  >/dev/null 2>&1 && have_rpm=1
command -v makepkg   >/dev/null 2>&1 && have_arch=1
command -v mksquashfs >/dev/null 2>&1 && have_appimage=1

printf '  %-22s %s\n' ".deb (dpkg-deb)"     "$( [ $have_dpkg = 1 ] && echo да || echo 'нет инструмента — пропуск' )"
printf '  %-22s %s\n' ".rpm (rpmbuild)"     "$( [ $have_rpm = 1 ] && echo да || echo 'нет инструмента — пропуск' )"
printf '  %-22s %s\n' "Arch (makepkg)"      "$( [ $have_arch = 1 ] && echo да || echo 'нет инструмента — пропуск' )"
printf '  %-22s %s\n' "AppImage (mksquashfs)" "$( [ $have_appimage = 1 ] && echo да || echo 'нет инструмента — пропуск' )"
printf '  %-22s %s\n' ".tar.gz (tar)"       "да"
echo

mkdir -p "$OUT_DIR"
FAILED=0
run_builder() {   # run_builder <скрипт> <что>
    local script="$1" what="$2"
    echo
    echo "############ $what ############"
    if sh "$PACKAGING_LINUX_DIR/$script"; then
        :
    else
        FAILED=1
        warn "$what: сборка не удалась"
    fi
}

[ "$have_dpkg" = 1 ]     && run_builder build-deb.sh      ".deb"
[ "$have_rpm" = 1 ]      && run_builder build-rpm.sh      ".rpm"
[ "$have_arch" = 1 ]     && run_builder build-arch.sh     "Arch .pkg.tar.zst"
[ "$have_appimage" = 1 ] && run_builder build-appimage.sh "AppImage"
run_builder build-tar.sh ".tar.gz"

step "итог"
if command -v sha256sum >/dev/null 2>&1; then
    ( cd "$OUT_DIR" && ls -1 *.deb *.rpm *.pkg.tar.zst *.AppImage *.tar.gz 2>/dev/null \
        | while IFS= read -r f; do printf '%-52s %8s  %s\n' "$f" \
            "$(du -h "$f" | cut -f1)" "$(sha256sum "$f" | cut -d' ' -f1)"; done )
fi
echo
if [ "$FAILED" = 1 ]; then
    echo "Часть сборок не удалась — смотрите сообщения выше." >&2
    exit 1
fi
echo "Все доступные форматы собраны в $OUT_DIR"
