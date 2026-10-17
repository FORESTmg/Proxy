#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# wsl-matrix.sh — reusable, idempotent package matrix bench for ForestProxyUpdater.
#
# Installs a real package inside a WSL distribution, proves that the proxy it
# ships actually carries traffic, checks the systemd unit, then uninstalls it and
# verifies nothing is left behind.  One PASS/FAIL table per run.
#
# Handles .deb, .rpm, .pkg.tar.zst (package managers), .tar.gz (its own
# install.sh/uninstall.sh) and .AppImage (per-user install; needs --as-user).
#
# Designed for Windows + WSL (runs in git-bash), but degrades to "run locally on
# this Linux host" when wsl.exe is absent, so the same file works in CI.
#
#   ./wsl-matrix.sh --distro Debian     --package ../dist/forestproxyupdater_1.1.0_amd64.deb
#   ./wsl-matrix.sh --distro openSUSE-Tumbleweed --package ../dist/fp-1.1.0.x86_64.rpm --port 11808
#   ./wsl-matrix.sh --distro archlinux  --package ../dist/fp-1.1.0-1-x86_64.pkg.tar.zst
#   ./wsl-matrix.sh --distro Debian     --package ../dist/fp-1.1.0-linux-x86_64.tar.gz
#   ./wsl-matrix.sh --distro Ubuntu     --package ../dist/ForestProxyUpdater-1.1.0-x86_64.AppImage --as-user tester
#   ./wsl-matrix.sh --distro Debian     --selftest          # throwaway pkg; proves the bench is alive
#   ./wsl-matrix.sh --list
#
# Exit codes:
#   0  every step PASSed
#   1  usage error
#   2  distro not registered in WSL
#   3  package not found
#   4  at least one bench step FAILed
#   5  environment error (no WSL, no root, staging failure)
#
set -u

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INNER="$SELF_DIR/wsl-matrix-inner.sh"
TESTPKG_DIR="$SELF_DIR/testpkg"

DEFAULT_PORT=11808
DEFAULT_TRAFFIC_WAIT=900
PORT="$DEFAULT_PORT"
DISTRO=""
PKG=""
UNIT=""
SERVICE_CMD=""
TRAFFIC_WAIT="$DEFAULT_TRAFFIC_WAIT"
AS_USER=""
INSTALLER_CMD=""
UNINSTALLER_CMD=""
ISOLATE=0
SELFTEST=0
DO_LIST=0

# ---------------------------------------------------------------------------
# exit codes
# ---------------------------------------------------------------------------
EX_OK=0; EX_USAGE=1; EX_NO_DISTRO=2; EX_NO_PACKAGE=3; EX_STEP_FAIL=4; EX_ENV=5

# files this bench knows how to install
PKG_GLOBS=( '*.deb' '*.rpm' '*.pkg.tar.zst' '*.pkg.tar.xz' '*.tar.gz' '*.AppImage' )

usage() {
  cat <<EOF
wsl-matrix.sh — install / verify / uninstall a ForestProxyUpdater package in a
WSL distribution and report a PASS/FAIL table.

Usage:
  wsl-matrix.sh --distro NAME (--package FILE | --selftest) [options]

Required (one of):
  --package FILE      .deb / .rpm / .pkg.tar.zst / .tar.gz / .AppImage to test
  --selftest          build a throwaway package inside the distro and test THAT
                      (proves the bench is alive on its own)

Options:
  --distro NAME       WSL distribution to test (default: the WSL default distro)
  --port N            proxy port to verify (default $DEFAULT_PORT; 10808/10809/10820
                      are refused — they belong to the user's live proxy on the host)
  --unit NAME         systemd unit to exercise (default: auto-detected from payload)
  --service-cmd CMD   shell command to start when the payload ships no unit
  --as-user NAME      run a USER-mode (systemd --user) install as that account —
                      required for .AppImage, also usable for .tar.gz --user
  --installer CMD     shell command that installs (instead of the package manager)
  --uninstaller CMD   shell command that removes (instead of the package manager)
  --traffic-wait N    seconds to wait for the first 204 (default $DEFAULT_TRAFFIC_WAIT:
                      the product's first cycle downloads lists and speed-tests them)
  --isolate           terminate every other WSL distro first (avoids the WSL
                      "user session / cgroup" collision bug, and respects the
                      one-distro-at-a-time resource rule)
  --list              list WSL distros and discoverable packages, then exit
  -h, --help          this help

Exit codes: 0 ok | 1 usage | 2 no such distro | 3 package not found |
            4 a step failed | 5 environment error
EOF
}

# ---------------------------------------------------------------------------
# arg parsing
# ---------------------------------------------------------------------------
while [ $# -gt 0 ]; do
  case "$1" in
    --distro)        DISTRO="${2:-}"; shift 2 ;;
    --package)       PKG="${2:-}"; shift 2 ;;
    --port)          PORT="${2:-}"; shift 2 ;;
    --unit)          UNIT="${2:-}"; shift 2 ;;
    --service-cmd)   SERVICE_CMD="${2:-}"; shift 2 ;;
    --traffic-wait)  TRAFFIC_WAIT="${2:-}"; shift 2 ;;
    --as-user)       AS_USER="${2:-}"; shift 2 ;;
    --installer)     INSTALLER_CMD="${2:-}"; shift 2 ;;
    --uninstaller)   UNINSTALLER_CMD="${2:-}"; shift 2 ;;
    --isolate)       ISOLATE=1; shift ;;
    --selftest)      SELFTEST=1; shift ;;
    --list|-l)       DO_LIST=1; shift ;;
    -h|--help)       usage; exit $EX_OK ;;
    *) echo "wsl-matrix: unknown argument '$1'" >&2; usage >&2; exit $EX_USAGE ;;
  esac
done

# never, ever poke the user's live proxy ports
case "$PORT" in
  10808|10809|10820|10821)
    echo "wsl-matrix: refusing port $PORT — that is the user's live proxy. Use $DEFAULT_PORT." >&2
    exit $EX_USAGE ;;
esac

# ---------------------------------------------------------------------------
# WSL plumbing helpers (stdout of wsl.exe is UTF-8, its *own* status lines are
# UTF-16LE; child stderr is re-encoded to UTF-16LE as well — handle both)
# ---------------------------------------------------------------------------
decode_utf16() {
  if command -v iconv >/dev/null 2>&1; then
    iconv -f UTF-16LE -t UTF-8 2>/dev/null || cat
  elif command -v python3 >/dev/null 2>&1; then
    python3 -c 'import sys; sys.stdout.write(sys.stdin.buffer.read().decode("utf-16le","replace"))'
  else
    tr -d '\000'            # ASCII survives; good enough without iconv/python
  fi
}

ON_WINDOWS=0
command -v wsl.exe >/dev/null 2>&1 && ON_WINDOWS=1

wsl_list() {
  wsl.exe -l -q 2>/dev/null | decode_utf16 | tr -d '\r' | sed '/^[[:space:]]*$/d'
}

# Microsoft Windows path  ->  /mnt/<drive>/... path usable inside WSL
# Accepts relative paths too (they are made absolute against the current shell).
to_wsl_path() {
  local w p="$1"
  case "$p" in
    /*) ;;                                     # already a POSIX path
    *)  p="$(cd "$(dirname "$p")" 2>/dev/null && pwd)/$(basename "$p")" ;;
  esac
  if command -v cygpath >/dev/null 2>&1; then
    w="$(cygpath -w "$p")"
  else
    case "$p" in
      /[A-Za-z]/*) w="$(printf '%s:/%s' "${p:1:1}" "${p:3}")" ;;   # /d/x -> d:/x
      *)           w="$p" ;;
    esac
  fi
  case "$w" in
    [A-Za-z]:[\\/]*)
      local d rest
      d="$(printf '%s' "${w:0:1}" | tr 'A-Z' 'a-z')"
      rest="$(printf '%s' "${w:2}" | tr '\\' '/')"
      printf '/mnt/%s%s' "$d" "$rest" ;;
    /*) printf '%s' "$w" ;;          # already a unix path
    *)  printf '%s' "$w" ;;
  esac
}

find_packages() {
  find "$SELF_DIR/../.." -maxdepth 4 -type f \
    \( -name '*.deb' -o -name '*.rpm' -o -name '*.pkg.tar.zst' -o -name '*.pkg.tar.xz' \
       -o -name '*.tar.gz' -o -name '*.AppImage' \) 2>/dev/null | sort
}

die() { echo "wsl-matrix: $*" >&2; exit "$EX_ENV"; }

if [ ! -f "$INNER" ]; then die "missing companion script: $INNER"; fi

# ---------------------------------------------------------------------------
# --list
# ---------------------------------------------------------------------------
if [ "$DO_LIST" = 1 ]; then
  if [ "$ON_WINDOWS" = 1 ]; then
    echo "WSL distributions:"
    wsl_list | sed 's/^/  - /'
  else
    echo "Not on Windows — will test this host directly."
  fi
  echo
  echo "Payloads discoverable under the repo:"
  found=0
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    echo "  - $f"; found=1
  done < <(find_packages)
  [ "$found" = 0 ] && echo "  (none yet — that is expected before the first release)"
  exit $EX_OK
fi

# ---------------------------------------------------------------------------
# distro resolution
# ---------------------------------------------------------------------------
if [ "$ON_WINDOWS" = 1 ]; then
  ALL="$(wsl_list)"
  if [ -z "$ALL" ]; then die "WSL is not installed / no distributions registered"; fi
  if [ -z "$DISTRO" ]; then DISTRO="$(printf '%s\n' "$ALL" | head -n1)"; fi
  if ! printf '%s\n' "$ALL" | grep -Fxq "$DISTRO"; then
    echo "wsl-matrix: WSL distribution '$DISTRO' is not registered." >&2
    echo "Registered: $(printf '%s' "$ALL" | tr '\n' ' ')" >&2
    exit $EX_NO_DISTRO
  fi
  echo "== distro: $DISTRO"
fi

# ---------------------------------------------------------------------------
# payload resolution
# ---------------------------------------------------------------------------
if [ "$SELFTEST" = 1 ]; then
  echo "== selftest: will build a throwaway package inside the distro"
elif [ -z "$PKG" ]; then
  CAND="$(find_packages)"
  N="$(printf '%s\n' "$CAND" | sed '/^$/d' | wc -l | tr -d ' ')"
  if [ "$N" = 0 ]; then
    cat >&2 <<EOF
wsl-matrix: no payload to test.

  No --package was given and no .deb/.rpm/.pkg.tar.zst/.tar.gz/.AppImage exists in
  the repository yet.  Build the packages first (packaging-linux/build-all.sh), or
  run with --selftest to validate the bench against a throwaway package:

      ./wsl-matrix.sh --distro $DISTRO --selftest

EOF
    exit $EX_NO_PACKAGE
  elif [ "$N" = 1 ]; then
    PKG="$(printf '%s\n' "$CAND" | sed '/^$/d' | head -n1)"
    echo "== payload (auto-discovered): $PKG"
  else
    echo "wsl-matrix: several payloads found, choose one with --package:" >&2
    printf '  %s\n' $CAND >&2
    exit $EX_NO_PACKAGE
  fi
elif [ ! -f "$PKG" ]; then
  echo "wsl-matrix: payload not found: $PKG" >&2
  exit $EX_NO_PACKAGE
fi

# ---------------------------------------------------------------------------
# run a shell script inside the distro (stdin pipe => no quoting hell)
# ---------------------------------------------------------------------------
run_in_distro() {   # run_in_distro <script-file> [env VAR=VAL ...]
  local script="$1"; shift
  if [ "$ON_WINDOWS" = 1 ]; then
    cat "$script" | tr -d '\r' | \
      wsl.exe -d "$DISTRO" -u root -e env "$@" bash -s
  else
    if [ "$(id -u)" = 0 ]; then
      env "$@" bash -s < "$script"
    else
      env "$@" sudo bash -s < "$script"
    fi
  fi
}

# one distro at a time (resource rule + avoids the WSL cgroup/user-session bug)
if [ "$ON_WINDOWS" = 1 ]; then
  wsl.exe --terminate "$DISTRO" >/dev/null 2>&1 || true
  if [ "$ISOLATE" = 1 ]; then
    while IFS= read -r d; do
      [ -n "$d" ] && [ "$d" != "$DISTRO" ] && wsl.exe --terminate "$d" >/dev/null 2>&1 || true
    done <<EOF
$ALL
EOF
  fi
fi

# common env for the inner probe
env_args=(FP_PORT="$PORT" FP_TRAFFIC_WAIT="$TRAFFIC_WAIT")
[ -n "$UNIT" ]            && env_args+=(FP_UNIT="$UNIT")
[ -n "$SERVICE_CMD" ]     && env_args+=(FP_SERVICE_CMD="$SERVICE_CMD")
[ -n "$AS_USER" ]         && env_args+=(FP_AS_USER="$AS_USER")
[ -n "$INSTALLER_CMD" ]   && env_args+=(FP_INSTALLER="$INSTALLER_CMD")
[ -n "$UNINSTALLER_CMD" ] && env_args+=(FP_UNINSTALLER="$UNINSTALLER_CMD")

# ---------------------------------------------------------------------------
# --selftest : stage testpkg/ into the distro and build a throwaway package
# ---------------------------------------------------------------------------
STAGE_LOG="$(mktemp)"
if [ "$SELFTEST" = 1 ]; then
  TP_WSL="$(to_wsl_path "$TESTPKG_DIR")"
  echo "== selftest: building throwaway package inside $DISTRO from $TP_WSL"
  OUT="$(run_in_distro /dev/stdin FP_TP_DIR="$TP_WSL" <<'EOS' 2>/dev/null
set -e
D=/tmp/fp-matrix-testpkg
rm -rf "$D"; mkdir -p "$D/out"
cp -r "$FP_TP_DIR"/. "$D"/
bash "$D/build-testpkg.sh" "$D/out" >/tmp/fp-matrix-build.log 2>&1 || { echo "BUILD-FAILED"; tail -n 15 /tmp/fp-matrix-build.log; exit 7; }
for f in "$D"/out/*; do [ -f "$f" ] && echo "$f"; done
EOS
)"
  echo "$OUT" | sed 's/^/   /'
  PKG_IN_DISTRO="$(printf '%s\n' "$OUT" | grep -E '\.(deb|rpm|pkg\.tar\.zst)$' | head -n1)"
  if [ -z "$PKG_IN_DISTRO" ]; then
    echo "wsl-matrix: selftest package could not be built inside $DISTRO" >&2
    exit $EX_STEP_FAIL
  fi
  echo "== selftest package built: $PKG_IN_DISTRO"
  run_in_distro "$INNER" "${env_args[@]}" FP_PKG="$PKG_IN_DISTRO" >"$STAGE_LOG" 2>/tmp/.fpm_wsl_stderr
else
  PKG_WSL="$(to_wsl_path "$PKG")"
  if [ "$ON_WINDOWS" = 1 ]; then
    case "$PKG_WSL" in /mnt/*) ;; *) die "cannot map '$PKG' into a WSL path";; esac
  fi
  echo "== payload: $PKG  (inside distro: $PKG_WSL)"
  [ -n "$AS_USER" ] && echo "== user mode: $AS_USER (systemd --user)"
  [ -n "$TRAFFIC_WAIT" ] && echo "== traffic wait: ${TRAFFIC_WAIT}s"
  run_in_distro "$INNER" "${env_args[@]}" FP_PKG="$PKG_WSL" >"$STAGE_LOG" 2>/tmp/.fpm_wsl_stderr
fi
RUN_RC=$?

# ---------------------------------------------------------------------------
# present the run: human log, then the PASS/FAIL table
# ---------------------------------------------------------------------------
echo
echo "================ distro output ($DISTRO) ================"
grep -v '^##RESULT##|' "$STAGE_LOG" || true
if [ -s /tmp/.fpm_wsl_stderr ]; then
  echo "--- wsl/diagnostic stderr ---"
  decode_utf16 < /tmp/.fpm_wsl_stderr | tr -d '\r'
fi

echo
echo "================ PASS/FAIL matrix ($DISTRO) ================"
RESULTS="$(grep '^##RESULT##|' "$STAGE_LOG" || true)"
if [ -z "$RESULTS" ]; then
  echo "no step results were produced (distro bootstrap failed, rc=$RUN_RC)"
  exit $EX_STEP_FAIL
fi
printf '%s\n' "$RESULTS" | awk -F'|' '
  BEGIN { printf "%-4s %-18s %-6s %s\n", "#", "STEP", "STATUS", "DETAIL";
          printf "%-4s %-18s %-6s %s\n", "--", "------------------", "------", "---------------------------------------------" }
  { n++; printf "%-4d %-18s %-6s %s\n", n, $2, $3, $4;
    if ($3=="PASS") p++; else if ($3=="FAIL") f++; else s++ }
  END { printf "\nTOTAL: %d steps  |  %d PASS  |  %d FAIL  |  %d SKIP\n", n, p+0, f+0, s+0;
        if (f>0) printf "RESULT: FAIL\n"; else printf "RESULT: PASS\n" }'

echo
if printf '%s\n' "$RESULTS" | grep -q '|FAIL|'; then
  exit $EX_STEP_FAIL
fi
exit $EX_OK
