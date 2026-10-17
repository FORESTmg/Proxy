#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# wsl-matrix-inner.sh — payload install / verify / uninstall probe.
#
# Runs INSIDE a Linux distribution (as root). Normally invoked by wsl-matrix.sh,
# but it is also usable standalone on any Linux host (pure bash + the distro's own
# tools), which is what makes the bench reusable:
#
#   FP_PKG=/tmp/foo.deb FP_PORT=11808 bash wsl-matrix-inner.sh
#
# Supported payloads
#   .deb / .rpm / .pkg.tar.zst  — installed through the distro package manager
#   .tar.gz                     — unpacked; install.sh / uninstall.sh are run
#   .AppImage                   — run with --appimage-extract-and-run --install
#
# Inputs (environment):
#   FP_PKG           Path to the payload inside the distro
#   FP_PORT          Proxy port verified end-to-end (default 11808)
#   FP_UNIT          systemd unit to exercise (optional; auto-detected)
#   FP_SERVICE_CMD   Fallback shell command to start when no unit can be found
#   FP_TRAFFIC_WAIT  Seconds to wait for the first 204 (default 900). A cold
#                    product cycle downloads server lists and speed-tests them,
#                    so this is minutes, not seconds.
#   FP_AS_USER       Install/run in USER mode (systemd --user) as this account —
#                    required for payloads whose only mode is per-user (AppImage)
#   FP_INSTALLER     Shell command that installs (instead of a package manager)
#   FP_UNINSTALLER   Shell command that removes (instead of a package manager)
#
# Output contract (parsed by wsl-matrix.sh):
#   ##RESULT##|<step>|<PASS|FAIL|SKIP>|<detail>
#
# Exit code: 0 if every step PASSed, 1 if any step FAILed.

MARK='##RESULT##'
PORT="${FP_PORT:-11808}"
PKG="${FP_PKG:-}"
UNIT_OVERRIDE="${FP_UNIT:-}"
SERVICE_CMD="${FP_SERVICE_CMD:-}"
TRAFFIC_WAIT="${FP_TRAFFIC_WAIT:-900}"
AS_USER="${FP_AS_USER:-}"
INSTALLER_CMD="${FP_INSTALLER:-}"
UNINSTALLER_CMD="${FP_UNINSTALLER:-}"

FAILED=0
res() { # res <step> <PASS|FAIL|SKIP> <detail>
  local d; d=$(printf '%s' "$3" | tr '|\n\r' ' / ')
  printf '%s|%s|%s|%s\n' "$MARK" "$1" "$2" "$d"
  [ "$2" = FAIL ] && FAILED=1
  return 0
}
log() { printf '%s\n' "$*"; }
hr()  { printf '%s\n' '------------------------------------------------------------'; }

# ---------------------------------------------------------------------------
# Guard: the bench must NEVER collide with the user's live proxy on the host.
# ---------------------------------------------------------------------------
case "$PORT" in
  10808|10809|10820|10821)
    log "REFUSING reserved live-proxy port $PORT (host owns it). Pick e.g. 11808."
    exit 9
    ;;
esac

[ -n "$PKG" ] || { log "ERROR: FP_PKG is not set"; exit 8; }
[ -f "$PKG" ] || { log "ERROR: payload not found inside distro: $PKG"; exit 3; }

# ---------------------------------------------------------------------------
# 1. environment
# ---------------------------------------------------------------------------
if [ -r /etc/os-release ]; then . /etc/os-release; fi
DESC="${PRETTY_NAME:-unknown Linux} ${VERSION_ID:-rolling}"
log "=== environment ==="
log "distro : $DESC"
log "kernel : $(uname -r)"
log "port   : $PORT"
log "payload: $PKG"
[ -n "$AS_USER" ] && log "user   : $AS_USER (systemd --user flow)"
res env PASS "$DESC"

if command -v systemctl >/dev/null 2>&1; then
  SYS=$(systemctl is-system-running 2>/dev/null || true)
  case "$SYS" in
    running|degraded|starting|initializing) res systemd PASS "systemd is-system-running=$SYS" ;;
    "") res systemd FAIL "systemctl present but systemd is not the init (enable via /etc/wsl.conf [boot] systemd=true)" ;;
    *)  res systemd FAIL "systemd state: $SYS" ;;
  esac
else
  res systemd FAIL "systemctl not installed"
fi

# ---------------------------------------------------------------------------
# user-mode plumbing (systemd --user as $FP_AS_USER)
# ---------------------------------------------------------------------------
U_HOME=""; U_UID=""; U_URD=""
if [ -n "$AS_USER" ]; then
  if id "$AS_USER" >/dev/null 2>&1; then
    U_UID="$(id -u "$AS_USER")"
    U_HOME="$(getent passwd "$AS_USER" | cut -d: -f6)"
    U_URD="/run/user/$U_UID"
    res user-mode PASS "$AS_USER uid=$U_UID home=$U_HOME"
  else
    res user-mode FAIL "no such user: $AS_USER"
    AS_USER=""
  fi
fi

# run a command (or a shell line) as the target user with a working session bus
u_run() { runuser -u "$AS_USER" -- env HOME="$U_HOME" XDG_RUNTIME_DIR="$U_URD" \
            DBUS_SESSION_BUS_ADDRESS="unix:path=$U_URD/bus" "$@"; }
u_sh()  { runuser -u "$AS_USER" -- env HOME="$U_HOME" XDG_RUNTIME_DIR="$U_URD" \
            DBUS_SESSION_BUS_ADDRESS="unix:path=$U_URD/bus" sh -c "$1"; }
sysctl_user() { u_run systemctl --user "$@"; }

# ---------------------------------------------------------------------------
# 2. payload type + identity
# ---------------------------------------------------------------------------
case "$PKG" in
  *.deb)                                   KIND=deb ; MGR=deb ;;
  *.rpm)                                   KIND=rpm ; MGR=rpm ;;
  *.pkg.tar.zst|*.pkg.tar.xz|*.pkg.tar.gz) KIND=pac ; MGR=pac ;;
  *.tar.gz|*.tgz|*.tar.xz)                 KIND=tar ; MGR="" ;;
  *.AppImage)                              KIND=appimage ; MGR="" ;;
  *)                                       KIND="" ; MGR="" ;;
esac
if [ -z "$KIND" ]; then
  res pkg-type FAIL "unrecognised payload: $(basename "$PKG")"
  hr; log "cannot continue without a known payload type"; exit 1
fi

case "$MGR" in
  deb) command -v dpkg >/dev/null 2>&1 || { res pkg-type FAIL "dpkg missing"; exit 1; }
       NAME=$(dpkg-deb -f "$PKG" Package 2>/dev/null || true)
       VER=$(dpkg-deb -f "$PKG" Version 2>/dev/null || true) ;;
  rpm) command -v rpm >/dev/null 2>&1 || { res pkg-type FAIL "rpm missing"; exit 1; }
       NAME=$(rpm -qp --qf '%{NAME}' "$PKG" 2>/dev/null || true)
       VER=$(rpm -qp --qf '%{VERSION}-%{RELEASE}' "$PKG" 2>/dev/null || true) ;;
  pac) command -v pacman >/dev/null 2>&1 || { res pkg-type FAIL "pacman missing"; exit 1; }
       # `-Qp --format` was removed in pacman 7; parse `-Qip` (stable across versions)
       NAME=$(pacman -Qip "$PKG" 2>/dev/null | awk -F': *' '/^Name[[:space:]]*:/{print $2; exit}')
       VER=$(pacman -Qip "$PKG"  2>/dev/null | awk -F': *' '/^Version[[:space:]]*:/{print $2; exit}') ;;
  *)   # tarball / AppImage: the real application name is derived after install
       NAME=$(basename "$PKG" | sed -e 's/\.tar\.gz$//' -e 's/\.tgz$//' -e 's/\.tar\.xz$//' \
                                     -e 's/\.AppImage$//' \
                                     -e 's/-[0-9][0-9.]*-linux-x86_64$//' \
                                     -e 's/-[0-9][0-9.]*-x86_64$//' \
                                     -e 's/-[0-9][0-9.]*$//')
       VER=$(basename "$PKG" | sed -n 's/.*-\([0-9][0-9.]*\)\(-x86_64\)\?\(\..*\)\?$/\1/p') ;;
esac
[ -n "$NAME" ] || { res pkg-type FAIL "could not read a name from $(basename "$PKG")"; hr; exit 1; }
log "=== payload ==="
log "kind   : $KIND"
log "manager: ${MGR:-none (installer / AppImage)}"
log "name   : $NAME"
log "version: ${VER:-?}"
res pkg-type PASS "$KIND '$NAME' ${VER:-}"

# ---------------------------------------------------------------------------
# 3. copy the payload into the distro (local /tmp, not /mnt)
# ---------------------------------------------------------------------------
DEST="/tmp/$(basename "$PKG")"
log "=== copy payload into distro ==="
if cp -f "$PKG" "$DEST" 2>/tmp/.fpm_cp.err; then
  if [ "$KIND" = appimage ]; then chmod 0755 "$DEST"; else chmod 0644 "$DEST"; fi 2>/dev/null || true
  res pkg-copy PASS "$DEST ($(du -h "$DEST" 2>/dev/null | cut -f1))"
else
  res pkg-copy FAIL "cannot copy to $DEST: $(cat /tmp/.fpm_cp.err)"
fi

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
pkg_files() {
  case "$MGR" in
    deb) dpkg -L "$NAME" 2>/dev/null ;;
    rpm) rpm -ql "$NAME" 2>/dev/null ;;
    pac) pacman -Ql "$NAME" 2>/dev/null | awk '{print $2}' ;;
  esac
}
is_installed() {
  case "$MGR" in
    deb) dpkg-query -W -f='${Status}' "$NAME" 2>/dev/null | grep -q "install ok installed" ;;
    rpm) rpm -q "$NAME" >/dev/null 2>&1 ;;
    pac) pacman -Q "$NAME" >/dev/null 2>&1 ;;
    *)   [ -n "$APPNAME" ] && [ -e "${APPBIN:-/nonexistent}" ] ;;
  esac
}
port_open()  { (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; }
unit_active()   { if [ -n "$AS_USER" ]; then u_run systemctl --user is-active  "$1" >/dev/null 2>&1; else systemctl is-active  "$1" >/dev/null 2>&1; fi; }
unit_present()  { if [ -n "$AS_USER" ]; then u_run systemctl --user cat        "$1" >/dev/null 2>&1; else systemctl cat        "$1" >/dev/null 2>&1; fi; }
unit_enabled()  { if [ -n "$AS_USER" ]; then u_run systemctl --user is-enabled "$1" >/dev/null 2>&1; else systemctl is-enabled "$1" >/dev/null 2>&1; fi; }

INSTALL_LOG=/tmp/.fpm_install.log
# Vendor/remote repos can be unreachable from inside WSL (the host's localhost
# proxy is not usable in NAT mode).  If the normal install fails, retry with every
# repo disabled so a local file whose dependencies are already present installs.
rpm_install_with_fallback() {   # $1 = dnf | yum
  "$1" install -y --nogpgcheck "$DEST" >"$INSTALL_LOG" 2>&1 && return 0
  "$1" install -y --nogpgcheck --disablerepo='*' "$DEST" >"$INSTALL_LOG" 2>&1
}

# ---------------------------------------------------------------------------
# 4. install
# ---------------------------------------------------------------------------
log "=== install ==="
PAYLOAD_DIR=""
APPNAME=""
: > /tmp/.fpm-clock            # маркер времени: по нему ищем только что созданные юниты
# в пользовательском режиме сначала снимаем прежнюю установку (идемпотентность)
if [ -n "$AS_USER" ] && { [ "$KIND" = tar ] || [ "$KIND" = appimage ]; }; then
  preclean_user_install
fi
case "$KIND" in
  deb)
    export DEBIAN_FRONTEND=noninteractive
    if [ -n "$INSTALLER_CMD" ]; then sh -c "$INSTALLER_CMD" >"$INSTALL_LOG" 2>&1
    elif command -v apt-get >/dev/null 2>&1; then apt-get install -y "$DEST" >"$INSTALL_LOG" 2>&1
    else dpkg -i "$DEST" >"$INSTALL_LOG" 2>&1; fi ;;
  rpm)
    if [ -n "$INSTALLER_CMD" ]; then sh -c "$INSTALLER_CMD" >"$INSTALL_LOG" 2>&1
    elif   command -v zypper >/dev/null 2>&1; then zypper --non-interactive --no-gpg-checks install "$DEST" >"$INSTALL_LOG" 2>&1
    elif   command -v dnf    >/dev/null 2>&1; then rpm_install_with_fallback dnf
    elif   command -v yum    >/dev/null 2>&1; then rpm_install_with_fallback yum
    else rpm -ivh "$DEST" >"$INSTALL_LOG" 2>&1; fi ;;
  pac)
    if [ -n "$INSTALLER_CMD" ]; then sh -c "$INSTALLER_CMD" >"$INSTALL_LOG" 2>&1
    else pacman -U --noconfirm "$DEST" >"$INSTALL_LOG" 2>&1; fi ;;
  tar)
    rm -rf /tmp/fp-payload; mkdir -p /tmp/fp-payload
    if tar -xzf "$DEST" -C /tmp/fp-payload >"$INSTALL_LOG" 2>&1; then
      _i=$(find /tmp/fp-payload -maxdepth 2 -name install.sh -type f | head -n1)
      PAYLOAD_DIR="$(dirname "${_i:-/tmp/fp-payload}")"
      log "unpacked to $PAYLOAD_DIR"
    else
      res install FAIL "unpack failed: $(tail -n 2 "$INSTALL_LOG" | tr '\n' ' ')"
    fi
    if [ -n "$INSTALLER_CMD" ]; then
      if [ -n "$AS_USER" ]; then u_sh "$INSTALLER_CMD" >"$INSTALL_LOG" 2>&1
      else sh -c "$INSTALLER_CMD" >"$INSTALL_LOG" 2>&1; fi
    elif [ -d "$PAYLOAD_DIR" ]; then
      if [ -n "$AS_USER" ]; then u_sh "cd '$PAYLOAD_DIR' && sh install.sh --user --yes" >"$INSTALL_LOG" 2>&1
      else sh -c "cd '$PAYLOAD_DIR' && sh install.sh --system --yes" >"$INSTALL_LOG" 2>&1; fi
    fi ;;
  appimage)
    if [ -n "$INSTALLER_CMD" ]; then
      if [ -n "$AS_USER" ]; then u_sh "$INSTALLER_CMD" >"$INSTALL_LOG" 2>&1
      else sh -c "$INSTALLER_CMD" >"$INSTALL_LOG" 2>&1; fi
    else
      log "running the AppImage installer (first cycle skipped — the service does it below)…"
      # FOREST_SKIP_FIRST_CYCLE is a product switch: without it --install runs a
      # full selection cycle inline (minutes) before the service even starts.
      if [ -n "$AS_USER" ]; then u_sh "FOREST_SKIP_FIRST_CYCLE=1 '$DEST' --appimage-extract-and-run --install" >"$INSTALL_LOG" 2>&1
      else sh -c "FOREST_SKIP_FIRST_CYCLE=1 '$DEST' --appimage-extract-and-run --install" >"$INSTALL_LOG" 2>&1; fi
    fi ;;
esac
INSTALL_RC=$?

# фактическое имя приложения (у tar/AppImage его даёт сам продукт) и признак установки
if [ "$KIND" = tar ] || [ "$KIND" = appimage ]; then
  if [ -n "$AS_USER" ]; then
    APPNAME="$(pick_new_appname "$U_HOME/.config/systemd/user")"
    [ -z "$APPNAME" ] && APPNAME="forest-proxy-updater"
    APPBIN="$U_HOME/.local/share/$APPNAME/$APPNAME"
  else
    APPNAME="$(pick_new_appname /usr/lib/systemd/system)"
    [ -z "$APPNAME" ] && APPNAME="$NAME"
    APPBIN="/usr/lib/$APPNAME/$APPNAME"
  fi
  log "app name: $APPNAME (binary: $APPBIN)"
else
  APPNAME="$NAME"
  APPBIN="/usr/lib/$NAME/$NAME"
fi

if is_installed; then
  res install PASS "$NAME installed (${APPBIN})"
else
  res install FAIL "install rc=$INSTALL_RC; last log: $(tail -n 3 "$INSTALL_LOG" 2>/dev/null | tr '\n' ' ')"
fi

# ---------------------------------------------------------------------------
# 5. systemd unit presence
# ---------------------------------------------------------------------------
# The supervisor unit is a .service that is not the scheduled oneshot
# (*-refresh); prefer one named after the product.
pick_unit() {
  local names best=""
  names="$(printf '%s\n' "$1" | sed 's|.*/||' | grep -E '\.service$' | grep -v -- '-refresh' | sort -u)"
  [ -n "$names" ] || names="$(printf '%s\n' "$1" | sed 's|.*/||' | grep -E '\.service$' | sort -u)"
  for n in $names; do
    case "$n" in
      "$APPNAME.service"|"forest-proxy-updater.service") best="$n"; break ;;
    esac
  done
  [ -n "$best" ] || best="$(printf '%s\n' $names | head -n1)"
  printf '%s' "$best"
}

# Имя приложения, которое ТОЛЬКО ЧТО установилось: юниты, созданные после
# /tmp/.fpm-clock, без «-refresh» (это плановый прогон, а не супервизор), и с
# приоритетом тому, чей ExecStart содержит --run. Иначе легко поймать чужой
# юнит, оставшийся в образе (например, от прежних экспериментов в этом же
# дистрибутиве).
pick_new_appname() {   # pick_new_appname <каталог с юнитами>
    local dir="$1" f name best=""
    for f in $(find "$dir" -maxdepth 1 -name '*.service' -newer /tmp/.fpm-clock 2>/dev/null | sort); do
        case "$f" in *-refresh.service) continue ;; esac
        name="$(basename "$f" .service)"
        if [ -z "$best" ]; then best="$name"; fi
        if grep -q -- '--run' "$f" 2>/dev/null; then printf '%s' "$name"; return 0; fi
    done
    printf '%s' "$best"
}

# Пользовательская установка живёт в домашнем каталоге и переживает прогоны,
# поэтому перед повтором её надо снять: иначе установщик продукта пытается
# перезаписать работающий бинарь («Text file busy») и прогон не идемпотентен.
preclean_user_install() {
    [ -n "$AS_USER" ] || return 0
    local f bin
    for f in "$U_HOME/.config/systemd/user"/*.service; do
        [ -f "$f" ] || continue
        bin="$(sed -n 's/^ExecStart=\([^ ]*\).*/\1/p' "$f" | head -n1)"
        case "$bin" in
            "$U_HOME/.local/"*)
                u_run systemctl --user disable --now "$(basename "$f")" >/dev/null 2>&1 || true
                rm -f "$f" 2>/dev/null || true
                rm -rf "$(dirname "$bin")" 2>/dev/null || true
                log "pre-clean: снята прежняя пользовательская установка ($(basename "$f"))"
                ;;
        esac
    done
    rm -rf "$U_HOME/.local/state/$NAME" "$U_HOME/.config/$NAME" 2>/dev/null || true
    u_run systemctl --user daemon-reload >/dev/null 2>&1 || true
}

UNIT="${UNIT_OVERRIDE:-}"
if [ -z "$UNIT" ] && [ -n "$AS_USER" ]; then
  if [ -f "$U_HOME/.config/systemd/user/$APPNAME.service" ]; then
    UNIT="$APPNAME.service"
  else
    UNIT=$(pick_unit "$(find "$U_HOME/.config/systemd/user" -maxdepth 1 -name '*.service' 2>/dev/null)")
  fi
elif [ -z "$UNIT" ] && [ -n "$MGR" ] && is_installed; then
  UNIT=$(pick_unit "$(pkg_files)")
elif [ -z "$UNIT" ] && [ -f "/usr/lib/systemd/system/$APPNAME.service" ]; then
  UNIT="$APPNAME.service"
fi
log "=== unit: ${UNIT:-<none>} ==="

# ---------------------------------------------------------------------------
# 6. port steering + service activation
# ---------------------------------------------------------------------------
# The bench runs the product on ITS port, never on the product default (10808
# belongs to the user's live proxy on the host). The product reads its config
# from FOREST_CONFIG, so the bench writes a copy of the shipped config with the
# bench port and points the unit at it through a drop-in: the shipped product
# configuration is never modified.
find_product_config() {
  local c
  for c in "/etc/$APPNAME/config.json"; do
    [ -f "$c" ] && { printf '%s' "$c"; return 0; }
  done
  if [ -n "$U_HOME" ] && [ -f "$U_HOME/.config/$APPNAME/config.json" ]; then
    printf '%s' "$U_HOME/.config/$APPNAME/config.json"; return 0
  fi
  if [ -n "$MGR" ] && is_installed; then
    c=$(pkg_files | grep -E '/etc/.+/config\.json$' | head -n1)
    [ -n "$c" ] && { printf '%s' "$c"; return 0; }
  fi
  return 1
}
CONFIG_SRC="$(find_product_config || true)"
RUN_DIR="/run/fp-matrix-$PORT"
TEST_CONFIG="$RUN_DIR/config.json"
mkdir -p "$RUN_DIR/unit.d"

if [ -n "$UNIT" ]; then
  if [ -n "$AS_USER" ]; then
    ORIG_FILES=$(sysctl_user show "$UNIT" -p EnvironmentFiles 2>/dev/null \
                   | sed -n 's/^EnvironmentFiles=//p' | tr ' ' '\n' \
                   | sed 's/([^)]*)//g' | grep '^/' || true)
  else
    ORIG_FILES=$(systemctl show "$UNIT" -p EnvironmentFiles 2>/dev/null \
                   | sed -n 's/^EnvironmentFiles=//p' | tr ' ' '\n' \
                   | sed 's/([^)]*)//g' | grep '^/' || true)
  fi
  {
    printf '[Service]\n'
    printf 'EnvironmentFile=\n'
    for f in $ORIG_FILES; do printf 'EnvironmentFile=-%s\n' "$f"; done
    printf 'EnvironmentFile=-/run/fp-matrix-port.env\n'
    printf 'Environment=FP_TEST_PORT=%s\nEnvironment=FP_PROXY_PORT=%s\n' "$PORT" "$PORT"
    [ -n "$CONFIG_SRC" ] && printf 'Environment=FOREST_CONFIG=%s\n' "$TEST_CONFIG"
  } > "$RUN_DIR/unit.d/50-fp-matrix-port.conf"
fi

if [ -n "$CONFIG_SRC" ]; then
  cp -f "$CONFIG_SRC" "$TEST_CONFIG"
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$TEST_CONFIG" "$PORT" <<'PY' >/dev/null 2>&1 || true
import json, sys
p, port = sys.argv[1], int(sys.argv[2])
d = json.load(open(p, encoding="utf-8"))
d.setdefault("client", {})["socks_port"] = port
d["client"]["listen"] = "127.0.0.1"
d["client"]["manage_system_proxy"] = False     # в тесте чужие настройки не трогаем
t = d.setdefault("test", {})
t["port_start"] = port + 100                   # временные ядра — тоже в стороне
# Бюджет прогона: продукт по умолчанию тестирует 400 узлов и качает по 5 МБ на
# узел. Для доказательства «прокси возит трафик» хватает меньшего — иначе шаг
# ожидания трафика перестаёт помещаться в разумное время.
t["max_candidates"] = 150
t["top_for_speed"] = 20
t["speed_bytes"] = 1048576                     # 1 МБ вместо 5 МБ
t["min_pool"] = 5
t["reserve_min"] = 2
t["final_verify_top"] = 20
t["rtt_repeats"] = 1
t.setdefault("workers", 8)
d.setdefault("limits", {})["max_servers"] = 20
w = d.setdefault("watch", {})
w["check_interval_s"] = 30                     # меньше шума в журнале при пустом пуле
json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
PY
  else
    sed -i "s/\"socks_port\": *[0-9]\+/\"socks_port\": $PORT/" "$TEST_CONFIG" || true
  fi
  chmod 0644 "$TEST_CONFIG"
  log "test config : $TEST_CONFIG (port $PORT, core test ports from $((PORT + 100)))"
else
  log "no product config found — the payload is expected to use env vars (FP_PROXY_PORT)"
fi

if [ "$FAILED" = 0 ] && [ -n "$UNIT" ]; then
  log "=== service unit ==="
  if unit_present "$UNIT"; then
    res unit-present PASS "systemd unit '$UNIT' installed and visible"

    # The package's own postinst already started the unit (with the shipped
    # config). Stop it before the drop-in below and start it once, so there is
    # exactly ONE instance: a restart while a cycle is running leaves the
    # product's cycle lock behind, and a locked-out cycle means no pool and no
    # traffic for hours.
    if [ -n "$AS_USER" ]; then
      sysctl_user stop "$UNIT" >/dev/null 2>&1 || true
    else
      systemctl stop "$UNIT" >/dev/null 2>&1 || true
    fi
    # fresh state: the bench verifies a clean install, and a stale lock/cache
    # would make the next start refuse to run its cycle
    if [ -n "$AS_USER" ]; then
      rm -rf "$U_HOME/.local/state/$APPNAME" 2>/dev/null || true
      find "$U_HOME/.local/share/$APPNAME" -maxdepth 2 -name 'lock.json' -delete 2>/dev/null || true
    else
      rm -rf "/var/lib/$APPNAME/state/$APPNAME" 2>/dev/null || true
      find "/var/lib/$APPNAME" -maxdepth 3 -name 'lock.json' -delete 2>/dev/null || true
    fi

    if [ -n "$AS_USER" ]; then
      mkdir -p "$U_HOME/.config/systemd/user/$UNIT.d"
      cp -f "$RUN_DIR/unit.d/50-fp-matrix-port.conf" "$U_HOME/.config/systemd/user/$UNIT.d/"
      chown -R "$AS_USER" "$U_HOME/.config/systemd/user/$UNIT.d" 2>/dev/null || true
      sysctl_user daemon-reload >/dev/null 2>&1 || true
      log "starting $UNIT (systemctl --user enable + start) with proxy port $PORT"
      sysctl_user enable "$UNIT" >/dev/null 2>&1 || true
      sysctl_user start "$UNIT" >/dev/null 2>&1 || true
      ST="$(u_run systemctl --user is-active "$UNIT" 2>/dev/null || true)"
      DIAG="$(u_run systemctl --user status "$UNIT" --no-pager -l 2>/dev/null | tail -n 3 | tr '\n' ' ')"
    else
      mkdir -p "/etc/systemd/system/$UNIT.d"
      cp -f "$RUN_DIR/unit.d/50-fp-matrix-port.conf" "/etc/systemd/system/$UNIT.d/"
      printf 'FP_TEST_PORT=%s\nFP_PROXY_PORT=%s\n' "$PORT" "$PORT" > /run/fp-matrix-port.env
      systemctl daemon-reload >/dev/null 2>&1 || true
      log "starting $UNIT (systemctl enable + start) with proxy port $PORT"
      systemctl enable "$UNIT" >/dev/null 2>&1 || true
      systemctl start "$UNIT" >/dev/null 2>&1 || true
      ST="$(systemctl is-active "$UNIT" 2>/dev/null || true)"
      DIAG="$(systemctl status "$UNIT" --no-pager -l 2>/dev/null | tail -n 3 | tr '\n' ' ')"
    fi
    if [ "$ST" = active ]; then
      res service-active PASS "$UNIT is active"
    else
      res service-active FAIL "$UNIT state=$ST: $DIAG"
    fi
  else
    res unit-present FAIL "unit '$UNIT' named but not found via systemctl"
    res service-active SKIP "no unit"
  fi
elif [ -n "$SERVICE_CMD" ]; then
  log "no unit; falling back to --service-cmd"
  res unit-present SKIP "payload ships no usable .service; using FP_SERVICE_CMD"
  setsid bash -c "$SERVICE_CMD" >/tmp/.fpm_svc.log 2>&1 &
  sleep 2
  PGREP=$(pgrep -f "$SERVICE_CMD" | head -n1 || true)
  if [ -n "$PGREP" ]; then res service-active PASS "cmd pid=$PGREP"; else
    res service-active FAIL "cmd exited: $(tail -n 2 /tmp/.fpm_svc.log 2>/dev/null | tr '\n' ' ')"
  fi
else
  if [ "$FAILED" = 0 ]; then
    res unit-present FAIL "payload installs no systemd unit and no --service-cmd given"
  else
    res unit-present SKIP "install failed"
  fi
  res service-active SKIP "no unit"
fi

# ---------------------------------------------------------------------------
# 7. real proxy traffic
# ---------------------------------------------------------------------------
log "=== proxy traffic ==="
if [ "$FAILED" = 0 ]; then
  CODE=""; waited=0
  while [ "$waited" -lt "$TRAFFIC_WAIT" ]; do
    CODE=$(curl -s -m 20 -x "http://127.0.0.1:$PORT" -o /dev/null \
             -w '%{http_code}' https://www.gstatic.com/generate_204 2>/dev/null || true)
    [ "$CODE" = "204" ] && break
    sleep 3; waited=$((waited + 3))
    [ $((waited % 30)) -eq 0 ] && log "  ... waiting for the first 204: ${waited}s (last: ${CODE:-<no response>})"
  done
  if [ "$CODE" = "204" ]; then
    res proxy-traffic PASS "curl -x http://127.0.0.1:$PORT -> 204 after ~${waited}s"
  else
    res proxy-traffic FAIL "expected 204 within ${TRAFFIC_WAIT}s, got '${CODE:-<no response>}' on 127.0.0.1:$PORT"
  fi
else
  res proxy-traffic SKIP "service not up"
fi

# ---------------------------------------------------------------------------
# 8. uninstall
# ---------------------------------------------------------------------------
log "=== uninstall ==="
# Only files matter for residue: package managers also list shared directories
# (/usr, /etc, ...) which legitimately survive removal.
PRE_FILES=""
if [ "$FAILED" = 0 ] || is_installed; then
  if [ -n "$MGR" ]; then
    PRE_FILES=$(pkg_files | while IFS= read -r f; do
        case "$f" in ""|"/."|".") continue ;; esac
        if [ -f "$f" ] || [ -L "$f" ]; then printf '%s\n' "$f"; fi
      done | sort -u)
  fi
  case "$KIND" in
    deb) export DEBIAN_FRONTEND=noninteractive
         if command -v apt-get >/dev/null 2>&1; then apt-get purge -y "$NAME" >/tmp/.fpm_rm.log 2>&1
         else dpkg --purge "$NAME" >/tmp/.fpm_rm.log 2>&1; fi ;;
    rpm) if   command -v zypper >/dev/null 2>&1; then zypper --non-interactive remove "$NAME" >/tmp/.fpm_rm.log 2>&1
         elif command -v dnf    >/dev/null 2>&1; then dnf remove -y "$NAME"                 >/tmp/.fpm_rm.log 2>&1
         elif command -v yum    >/dev/null 2>&1; then yum remove -y "$NAME"                 >/tmp/.fpm_rm.log 2>&1
         else rpm -e "$NAME" >/tmp/.fpm_rm.log 2>&1; fi ;;
    pac) pacman -Rns --noconfirm "$NAME" >/tmp/.fpm_rm.log 2>&1 ;;
    tar)
         if [ -n "$UNINSTALLER_CMD" ]; then sh -c "$UNINSTALLER_CMD" >/tmp/.fpm_rm.log 2>&1
         elif [ -n "$AS_USER" ]; then u_sh "cd '$PAYLOAD_DIR' && sh uninstall.sh --user --yes" >/tmp/.fpm_rm.log 2>&1
         else sh -c "cd '$PAYLOAD_DIR' && sh uninstall.sh --system --yes" >/tmp/.fpm_rm.log 2>&1; fi ;;
    appimage)
         if [ -n "$UNINSTALLER_CMD" ]; then sh -c "$UNINSTALLER_CMD" >/tmp/.fpm_rm.log 2>&1
         elif [ -n "$AS_USER" ]; then u_sh "'$APPBIN' --uninstall" >/tmp/.fpm_rm.log 2>&1
         else sh -c "'$APPBIN' --uninstall" >/tmp/.fpm_rm.log 2>&1; fi ;;
  esac
  RM_RC=$?
  if is_installed; then
    res uninstall FAIL "still present after removal (rc=$RM_RC); $(tail -n 2 /tmp/.fpm_rm.log | tr '\n' ' ')"
  else
    res uninstall PASS "$APPNAME removed"
  fi
else
  res uninstall SKIP "nothing installed"
fi
rm -rf "/etc/systemd/system/${UNIT:-__none__}.d" /run/fp-matrix-port.env 2>/dev/null || true
if [ -n "$AS_USER" ] && [ -n "$UNIT" ]; then rm -rf "$U_HOME/.config/systemd/user/$UNIT.d" 2>/dev/null || true; fi
if command -v systemctl >/dev/null 2>&1; then
  systemctl daemon-reload >/dev/null 2>&1 || true
  [ -n "$AS_USER" ] && sysctl_user daemon-reload >/dev/null 2>&1 || true
fi

# ---------------------------------------------------------------------------
# 9. residue checks
# ---------------------------------------------------------------------------
log "=== residue ==="
if is_installed; then
  res residue-pkg FAIL "still registered / still present"
else
  res residue-pkg PASS "not registered in the package DB and payload gone"
fi

LEFT=""
if [ -n "$PRE_FILES" ]; then
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    if [ -e "$f" ] || [ -L "$f" ]; then
      LEFT="$LEFT $f"
    fi
  done <<EOF
$PRE_FILES
EOF
fi
# the same places the product itself uses — checked for every payload kind
if [ -n "$AS_USER" ]; then
  for f in "$U_HOME/.local/share/$APPNAME/$APPNAME" \
           "$U_HOME/.config/systemd/user/$APPNAME.service" \
           "$U_HOME/.local/state/$APPNAME"; do
    [ -e "$f" ] && LEFT="$LEFT $(echo "$f" | sed "s|$U_HOME|~|")"
  done
else
  for f in "/usr/lib/$APPNAME/$APPNAME" "/usr/bin/$APPNAME" "/usr/local/bin/$APPNAME" \
           "/etc/$APPNAME/config.json"; do
    [ -e "$f" ] && LEFT="$LEFT $f"
  done
fi
if [ -z "$LEFT" ]; then
  res residue-files PASS "no payload files left behind"
else
  res residue-files FAIL "leftovers:$(printf '%s' "$LEFT" | cut -c1-160)"
fi

UNIT_LEFT=""
if [ -n "$UNIT" ]; then
  unit_present "$UNIT" && UNIT_LEFT="$UNIT_LEFT unit-file"
  unit_active  "$UNIT" && UNIT_LEFT="$UNIT_LEFT running"
  unit_enabled "$UNIT" && UNIT_LEFT="$UNIT_LEFT enabled/autostart"
fi
if [ -z "$UNIT_LEFT" ]; then
  res residue-units PASS "no unit file / no active service / no autostart"
else
  res residue-units FAIL "leftover:$UNIT_LEFT"
fi

# systemd stops the service asynchronously; a slow shutdown (seen on dnf-based
# Rocky) must not be misreported as leftover residue, so wait for the port to
# close, up to 15s.
STILL=0
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
  if port_open; then STILL=1; sleep 1; else STILL=0; break; fi
done
if [ "$STILL" = 1 ]; then
  HOLDER=$( (ss -ltnp 2>/dev/null || netstat -ltnp 2>/dev/null) \
              | grep -E "[:.]$PORT[[:space:]]" | head -n1 | tr -s ' ')
  res residue-port FAIL "still listening on 127.0.0.1:$PORT after 15s [${HOLDER:-unknown holder}]"
else
  res residue-port PASS "127.0.0.1:$PORT is closed"
fi

hr
if [ "$FAILED" = 0 ]; then log "inner verdict: ALL PASS"; else log "inner verdict: FAILURES PRESENT"; fi
exit "$FAILED"
