#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# run-matrix.sh — runs the whole release matrix: every artifact against the
# distributions that can install it, one distribution at a time.
#
#   bash linux/tests/run-matrix.sh                 # everything
#   bash linux/tests/run-matrix.sh deb rpm         # only those families
#   FOREST_MATRIX_WAIT=600 bash run-matrix.sh      # shorter traffic wait
#   FOREST_PKG_DIR=/tmp/pkgs bash run-matrix.sh
#
# Each run gets its own log in the output directory, and a summary.csv plus a
# final table is printed. Exit code 0 only if every run passed.
set -u

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$(dirname "$SELF_DIR")")"
PKG_DIR="${FOREST_PKG_DIR:-$REPO_DIR/packaging-linux/out}"
WAIT="${FOREST_MATRIX_WAIT:-900}"
PORT="${FOREST_MATRIX_PORT:-11808}"
OUT="${FOREST_MATRIX_OUT:-$SELF_DIR/matrix-$(date +%Y%m%d-%H%M%S)}"

# distro | family | extra wsl-matrix arguments
MATRIX=(
  "Debian|deb|"
  "Ubuntu|deb|"
  "openSUSE-Tumbleweed|rpm|"
  "RLCPlus-10|rpm|"
  "archlinux|pac|"
  "Debian|tar|"
  "archlinux|tar|"
  "Ubuntu|tar|--as-user tester"
  "Ubuntu|appimage|--as-user tester"
)

# optional family filter from the command line
WANT=("$@")

want_family() {   # want_family <family>
  [ "${#WANT[@]}" -eq 0 ] && return 0
  local f
  for f in "${WANT[@]}"; do [ "$f" = "$1" ] && return 0; done
  return 1
}

pkg_for() {   # pkg_for <family> -> path or empty
  case "$1" in
    deb)      ls -1 "$PKG_DIR"/*.deb            2>/dev/null | head -n1 ;;
    rpm)      ls -1 "$PKG_DIR"/*.rpm            2>/dev/null | head -n1 ;;
    pac)      ls -1 "$PKG_DIR"/*.pkg.tar.zst    2>/dev/null | head -n1 ;;
    tar)      ls -1 "$PKG_DIR"/*.tar.gz         2>/dev/null | head -n1 ;;
    appimage) ls -1 "$PKG_DIR"/*.AppImage       2>/dev/null | head -n1 ;;
  esac
}

mkdir -p "$OUT"
echo "== matrix output: $OUT"
echo "== artifacts:     $PKG_DIR"
echo "== traffic wait:  ${WAIT}s, port $PORT"
echo

: > "$OUT/summary.csv"
printf 'family,distro,package,steps,pass,fail,skip,verdict\n' >> "$OUT/summary.csv"

FAILED_RUNS=0
IDX=0
for row in "${MATRIX[@]}"; do
  IFS='|' read -r DISTRO FAMILY EXTRA <<EOF
$row
EOF
  want_family "$FAMILY" || continue
  PKG="$(pkg_for "$FAMILY")"
  if [ -z "$PKG" ]; then
    echo "!! $FAMILY: no artifact in $PKG_DIR — skipping $DISTRO"
    printf '%s,%s,,0,0,0,0,NO-ARTIFACT\n' "$FAMILY" "$DISTRO" >> "$OUT/summary.csv"
    FAILED_RUNS=1
    continue
  fi
  IDX=$((IDX + 1))
  LOG="$OUT/$(printf '%02d' "$IDX")-$DISTRO-$FAMILY.log"
  echo "===== [$IDX] $FAMILY on $DISTRO  ($(basename "$PKG")) ====="
  # shellcheck disable=SC2086
  bash "$SELF_DIR/wsl-matrix.sh" --distro "$DISTRO" --package "$PKG" \
       --port "$PORT" --traffic-wait "$WAIT" $EXTRA >"$LOG" 2>&1
  RC=$?
  TOTAL_LINE="$(grep -E '^TOTAL: ' "$LOG" | tail -n1)"
  VERDICT="$(grep -E '^RESULT: ' "$LOG" | tail -n1 | awk '{print $2}')"
  STEPS="$(printf '%s' "$TOTAL_LINE" | awk '{print $2}')"
  PASS="$(printf '%s' "$TOTAL_LINE" | awk '{print $5}')"
  FAIL="$(printf '%s' "$TOTAL_LINE" | awk '{print $8}')"
  SKIP="$(printf '%s' "$TOTAL_LINE" | awk '{print $11}')"
  [ -n "$VERDICT" ] || VERDICT="NO-RESULT(rc=$RC)"
  printf '%s,%s,%s,%s,%s,%s,%s,%s\n' "$FAMILY" "$DISTRO" "$(basename "$PKG")" \
      "${STEPS:-0}" "${PASS:-0}" "${FAIL:-0}" "${SKIP:-0}" "$VERDICT" >> "$OUT/summary.csv"
  echo "    -> $VERDICT   ${TOTAL_LINE:-no TOTAL line}   (log: $LOG)"
  [ "$RC" = 0 ] || FAILED_RUNS=1
  echo
done

echo "==================== SUMMARY ===================="
awk -F, 'NR==1 { printf "%-9s %-20s %-10s %-8s %s\n", "FAMILY", "DISTRO", "VERDICT", "STEPS", "PASS/FAIL/SKIP";
              next }
        { printf "%-9s %-20s %-10s %-8s %s/%s/%s\n", $1, $2, $8, $4, $5, $6, $7 }' \
    "$OUT/summary.csv"
echo
echo "logs:   $OUT"
echo "csv:    $OUT/summary.csv"
[ "$FAILED_RUNS" = 0 ] || { echo "RESULT: at least one run did not pass" >&2; exit 4; }
echo "RESULT: every run passed"
