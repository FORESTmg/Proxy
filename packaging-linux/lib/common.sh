#!/usr/bin/env bash
# FOREST's Proxy Auto-updater
# Copyright (C) 2026 FOREST
# SPDX-License-Identifier: GPL-3.0-only
#
# common.sh — общий слой для всех сборщиков пакетов (packaging-linux/).
#
# Здесь ровно одна раскладка файлов и одна версия — все форматы (.deb, .rpm,
# Arch, AppImage, .tar.gz) собираются из ОДНОГО дерева, поэтому содержимое
# пакетов не может разъехаться.
#
# Подключение:  . "$(dirname "$0")/lib/common.sh"

set -eu

# ── расположение ────────────────────────────────────────────────────────────
PKG_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGING_LINUX_DIR="$(dirname "$PKG_LIB_DIR")"
REPO_DIR="$(dirname "$PACKAGING_LINUX_DIR")"

# ── версия и имена ──────────────────────────────────────────────────────────
APP=forest-proxy-updater
VERSION="${FOREST_PKG_VERSION:-1.1.0}"
RELEASE="${FOREST_PKG_RELEASE:-1}"          # номер выпуска пакета (.rpm/.pkg)
SUMMARY="Auto-updating proxy supervisor built on top of the Xray core"
HOMEPAGE="https://github.com/FORESTmg/proxy-auto-updater"
MAINT="FOREST <forest@example.invalid>"

# ── пути установки (системная раскладка: и для пакетов, и для .tar.gz) ──────
PREFIX="${FOREST_PKG_PREFIX:-/usr}"                   # /usr/lib, /usr/bin
LIBDIR="$PREFIX/lib/$APP"                             # сам ELF
UNITDIR="${FOREST_PKG_UNITDIR:-/usr/lib/systemd/system}"
CONFDIR="/etc/$APP"                                   # config.json
STATEDIR="/var/lib/$APP"                              # состояние и логи
DOCDIR="$PREFIX/share/doc/$APP"
LICDIR="$PREFIX/share/licenses/$APP"

# ── входы сборки ────────────────────────────────────────────────────────────
ELF="${FOREST_ELF:-$REPO_DIR/linux/dist/$APP}"
UNIT_SRC_DIR="$PACKAGING_LINUX_DIR/system"
EXAMPLE_CONFIG="$REPO_DIR/config.example.json"
LICENSE_FILE="$REPO_DIR/LICENSE"
LINUX_README="$REPO_DIR/linux/README.md"

# Куда складывать готовые пакеты (НЕ в git — см. .gitignore).
OUT_DIR="${FOREST_OUT_DIR:-$PACKAGING_LINUX_DIR/out}"
# Рабочий каталог сборки (тоже не в git).
WORK_DIR="${FOREST_WORK_DIR:-$PACKAGING_LINUX_DIR/work}"

# ── вывод ───────────────────────────────────────────────────────────────────
say()  { printf '  %s\n' "$*"; }
step() { printf '\n== %s ==\n' "$*"; }
warn() { printf 'ВНИМАНИЕ: %s\n' "$*" >&2; }
die()  { printf 'ОШИБКА: %s\n' "$*" >&2; exit 1; }

require_tool() {   # require_tool <tool> [подсказка]
    command -v "$1" >/dev/null 2>&1 || die "нет '$1'${2:+ — $2}"
}

# ── проверки входов ─────────────────────────────────────────────────────────
check_inputs() {
    [ -f "$ELF" ] || die "нет собранного ELF: $ELF
  Соберите Linux-версию: sh packaging/build-linux.sh"
    [ -x "$ELF" ] || warn "ELF без бита исполняемости: $ELF"
    [ -f "$EXAMPLE_CONFIG" ] || die "нет $EXAMPLE_CONFIG"
    [ -f "$LICENSE_FILE" ]   || die "нет $LICENSE_FILE (GPL-3.0)"
    [ -f "$LINUX_README" ]   || die "нет $LINUX_README"
    [ -f "$REPO_DIR/docs/LINUX-INSTALL.md" ]    || die "нет docs/LINUX-INSTALL.md"
    [ -f "$REPO_DIR/docs/LINUX-INSTALL.ru.md" ] || die "нет docs/LINUX-INSTALL.ru.md"
    [ -f "$REPO_DIR/docs/TERMS.md" ]            || die "нет docs/TERMS.md"
    [ -f "$REPO_DIR/docs/TERMS.ru.md" ]         || die "нет docs/TERMS.ru.md"
    for u in "$APP.service" "$APP-refresh.service" "$APP.timer"; do
        [ -f "$UNIT_SRC_DIR/$u" ] || die "нет шаблона юнита: $UNIT_SRC_DIR/$u"
    done
}

# ── раскладка: одно дерево для всех форматов ────────────────────────────────
# stage_payload <root>
#   <root>/usr/lib/<app>/<app>            — ELF (0755), ядро и гео-базы внутри
#   <root>/usr/bin/<app>                  — симлинк на ELF
#   <root>/usr/lib/systemd/system/*       — системные юниты (служба + таймер)
#   <root>/etc/<app>/config.json          — конфиг по умолчанию
#   <root>/usr/share/doc/<app>/*          — README, INSTALL (ru/en), copyright
#   <root>/usr/share/licenses/<app>/COPYING — полный текст GPL-3.0
stage_payload() {
    local root="$1"
    [ -n "$root" ] || die "stage_payload: не передан корень"
    rm -rf "$root"
    mkdir -p "$root$LIBDIR" "$root$PREFIX/bin" "$root$UNITDIR" "$root$CONFDIR" \
             "$root$DOCDIR" "$root$LICDIR"

    # 1. сама программа (ядро xray и гео-базы уже внутри ELF)
    install -m 0755 "$ELF" "$root$LIBDIR/$APP"

    # 2. команда в PATH
    ln -sf "$LIBDIR/$APP" "$root$PREFIX/bin/$APP"

    # 3. системные юниты (пути уже подставлены)
    render_units "$root$UNITDIR"

    # 4. конфиг по умолчанию (пакет не перезатрёт уже существующий: см. postinst)
    install -m 0644 "$EXAMPLE_CONFIG" "$root$CONFDIR/config.json"

    # 5. документация и лицензия
    install -m 0644 "$LINUX_README"       "$root$DOCDIR/README.md"
    install -m 0644 "$LICENSE_FILE"       "$root$DOCDIR/COPYING"
    install -m 0644 "$LICENSE_FILE"       "$root$LICDIR/COPYING"
    # Документация установки — та же, что в репозитории (docs/), чтобы копии
    # в пакетах не разъезжались с исходником.
    install -m 0644 "$REPO_DIR/docs/LINUX-INSTALL.md"    "$root$DOCDIR/INSTALL.md"
    install -m 0644 "$REPO_DIR/docs/LINUX-INSTALL.ru.md" "$root$DOCDIR/INSTALL.ru.md"
    # Условия использования: показываются один раз при первом запуске и должны
    # лежать рядом с программой (см. src/v2ray_updater.py::TERMS_NOTICE).
    install -m 0644 "$REPO_DIR/docs/TERMS.md"    "$root$DOCDIR/TERMS.md"
    install -m 0644 "$REPO_DIR/docs/TERMS.ru.md" "$root$DOCDIR/TERMS.ru.md"
    install -m 0644 "$PACKAGING_LINUX_DIR/doc/copyright"     "$root$DOCDIR/copyright"
    install -m 0644 "$PACKAGING_LINUX_DIR/doc/PACKAGE-README.md" "$root$DOCDIR/PACKAGE-README.md"
}

# render_units <куда класть>
# Подставляет пути в шаблоны packaging-linux/system/*.
render_units() {
    local dest="$1" f base
    mkdir -p "$dest"
    for f in "$UNIT_SRC_DIR"/*.service "$UNIT_SRC_DIR"/*.timer; do
        [ -f "$f" ] || continue
        base="$(basename "$f")"
        sed -e "s|@EXEC@|$LIBDIR/$APP|g" \
            -e "s|@WORKDIR@|$LIBDIR|g" \
            -e "s|@ROOT@|$STATEDIR|g" \
            -e "s|@CONFIG@|$CONFDIR/config.json|g" \
            -e "s|@STATE_HOME@|$STATEDIR/state|g" \
            -e "s|@DATA_HOME@|$STATEDIR/data|g" \
            -e "s|@DOCDIR@|$DOCDIR|g" \
            "$f" > "$dest/$base"
    done
}

# Конфиг, который увидит программа при первом запуске (если пользовательского нет).
install_default_config() {
    local target="$1"
    if [ -e "$target" ]; then
        say "конфиг уже есть, оставляю: $target"
        return 1
    fi
    mkdir -p "$(dirname "$target")"
    install -m 0644 "$EXAMPLE_CONFIG" "$target"
    say "конфиг создан: $target"
    return 0
}

# sha256 рядом с артефактом
write_sha256() {
    local f="$1"
    if command -v sha256sum >/dev/null 2>&1; then
        ( cd "$(dirname "$f")" && sha256sum "$(basename "$f")" > "$(basename "$f").sha256" )
    elif command -v shasum >/dev/null 2>&1; then
        ( cd "$(dirname "$f")" && shasum -a 256 "$(basename "$f")" > "$(basename "$f").sha256" )
    else
        warn "нет sha256sum — контрольная сумма не записана"
        return 0
    fi
    cat "$f.sha256"
}

# Печатает один короткий блок про готовый артефакт.
report_artifact() {
    local f="$1"
    [ -f "$f" ] || die "артефакт не создан: $f"
    printf '\nГотово: %s (%s)\n' "$f" "$(du -h "$f" | cut -f1)"
    write_sha256 "$f"
}

ensure_dirs() {
    mkdir -p "$OUT_DIR" "$WORK_DIR"
    # Каталог сборки на drvfs (/mnt/d, /mnt/c — Windows-диск из WSL) НЕ хранит
    # права: всё оказывается 0777. Пакет, собранный там, положил бы конфиг
    # доступным на запись всем. Проверяем и, если так, уходим в локальный /tmp.
    local probe="$WORK_DIR/.mode-probe.$$"
    : > "$probe" 2>/dev/null || true
    chmod 600 "$probe" 2>/dev/null || true
    local mode=""
    mode="$(stat -c '%a' "$probe" 2>/dev/null || echo '')"
    rm -f "$probe"
    if [ "$mode" != "600" ]; then
        local fallback="${TMPDIR:-/tmp}/${APP}-pkg-build$(printf '%s' "$WORK_DIR" | tr '/ ' '__')"
        warn "каталог сборки $WORK_DIR не сохраняет права файлов (получилось ${mode:-?}, а не 600).
  Это типично для Windows-диска, смонтированного в WSL (/mnt/*): пакет вышел бы
  с доступным всем конфигом. Перехожу на локальный каталог: $fallback"
        WORK_DIR="$fallback"
        mkdir -p "$WORK_DIR"
    fi
}
