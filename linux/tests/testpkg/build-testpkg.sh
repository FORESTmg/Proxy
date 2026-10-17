#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# build-testpkg.sh [outdir] [deb|rpm|pac] — build a THROWAWAY package that ships
# a tiny proxy + a systemd unit.  Purpose: let wsl-matrix.sh prove it is alive
# (install -> service -> real traffic -> uninstall -> no residue) long before the
# real ForestProxyUpdater packages exist.  Nothing here is a product component.
#
# Family is auto-detected from the host (dpkg-deb / pacman / rpmbuild) unless the
# second argument forces one.  Output lands in <outdir> (default ./out).
set -e

SELF="$(cd "$(dirname "$0")" && pwd)"
OUT="${1:-$SELF/out}"
FAMILY="${2:-}"
NAME=fp-matrix-test
VER=1.0.0

mkdir -p "$OUT"

stage_tree() {
  local root="$1"
  rm -rf "$root"
  mkdir -p "$root/usr/lib/fp-matrix-test" "$root/usr/lib/systemd/system" "$root/etc"
  install -m 0755 "$SELF/testproxy.py"            "$root/usr/lib/fp-matrix-test/testproxy.py"
  install -m 0644 "$SELF/fp-matrix-test.service"  "$root/usr/lib/systemd/system/fp-matrix-test.service"
  printf 'FP_TEST_PORT=11808\n'                   > "$root/etc/fp-matrix-test.conf"
}

if [ -z "$FAMILY" ]; then
  if   command -v dpkg-deb >/dev/null 2>&1; then FAMILY=deb
  elif command -v pacman   >/dev/null 2>&1; then FAMILY=pac
  elif command -v rpmbuild >/dev/null 2>&1; then FAMILY=rpm
  else
    echo "build-testpkg: no packaging tool found (need dpkg-deb, pacman or rpmbuild)" >&2
    exit 1
  fi
fi
echo "build-testpkg: family=$FAMILY out=$OUT"

# ---------------------------------------------------------------------------
case "$FAMILY" in
deb)
  ROOT="$SELF/.root.deb"
  stage_tree "$ROOT"
  mkdir -p "$ROOT/DEBIAN"
  cat > "$ROOT/DEBIAN/control" <<EOF
Package: $NAME
Version: $VER
Architecture: all
Maintainer: ForestProxyUpdater tests <dev@example.invalid>
Section: misc
Priority: optional
Depends: python3, curl
Description: throwaway proxy package used to self-test wsl-matrix.sh
 Not a product component. Installs a toy HTTP proxy and a systemd unit so the
 WSL package matrix bench can be validated before the real release exists.
EOF
  cat > "$ROOT/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
[ -d /run/systemd/system ] && systemctl daemon-reload >/dev/null 2>&1 || true
exit 0
EOF
  cat > "$ROOT/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
case "$1" in
  remove|purge|deconfigure)
    [ -d /run/systemd/system ] && systemctl disable --now fp-matrix-test.service >/dev/null 2>&1 || true ;;
esac
exit 0
EOF
  cat > "$ROOT/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
[ -d /run/systemd/system ] && systemctl daemon-reload >/dev/null 2>&1 || true
exit 0
EOF
  chmod 0755 "$ROOT/DEBIAN/postinst" "$ROOT/DEBIAN/prerm" "$ROOT/DEBIAN/postrm"
  dpkg-deb --root-owner-group --build "$ROOT" "$OUT/${NAME}_${VER}_all.deb"
  rm -rf "$ROOT"
  ;;

# ---------------------------------------------------------------------------
pac)
  ROOT="$SELF/.root.pac"
  stage_tree "$ROOT"
  cat > "$ROOT/.PKGINFO" <<EOF
pkgname = $NAME
pkgbase = $NAME
pkgver = $VER-1
pkgdesc = throwaway proxy package used to self-test wsl-matrix.sh
url = https://example.invalid
builddate = $(date +%s)
packager = ForestProxyUpdater tests
size = $(du -sb "$ROOT/usr" | cut -f1)
arch = any
license = GPL-3.0-or-later
depend = python
depend = curl
EOF
  cat > "$ROOT/.INSTALL" <<'EOF'
post_install() {
  [ -d /run/systemd/system ] && systemctl daemon-reload >/dev/null 2>&1 || true
}
pre_remove() {
  [ -d /run/systemd/system ] && systemctl disable --now fp-matrix-test.service >/dev/null 2>&1 || true
}
post_remove() {
  [ -d /run/systemd/system ] && systemctl daemon-reload >/dev/null 2>&1 || true
}
EOF
  PKGFILE="$OUT/${NAME}-${VER}-1-any.pkg.tar.zst"
  ( cd "$ROOT" && tar --format=gnu -I zstd -cf "$PKGFILE" .PKGINFO .INSTALL usr etc )
  rm -rf "$ROOT"
  ;;

# ---------------------------------------------------------------------------
rpm)
  if ! command -v rpmbuild >/dev/null 2>&1; then
    echo "build-testpkg: rpmbuild not installed (zypper install rpm-build / dnf install rpm-build)" >&2
    exit 1
  fi
  TOP="$(mktemp -d)"
  mkdir -p "$TOP"/{BUILD,RPMS,SOURCES,SPECS,SRPMS}
  TREE="$SELF/.root.rpm.tree"
  stage_tree "$TREE"
  cp -r "$TREE"/. "$TOP/SOURCES/"
  cat > "$TOP/SPECS/$NAME.spec" <<EOF
Name:           $NAME
Version:        $VER
Release:        1
Summary:        throwaway proxy package used to self-test wsl-matrix.sh
License:        GPL-3.0-or-later
BuildArch:      noarch
Requires:       python3, curl
%description
Not a product component. Installs a toy HTTP proxy and a systemd unit so the
WSL package matrix bench can be validated before the real release exists.
%prep
%build
%install
mkdir -p %{buildroot}
cp -r %{_sourcedir}/usr %{buildroot}/
cp -r %{_sourcedir}/etc %{buildroot}/
%files
/usr/lib/fp-matrix-test/testproxy.py
/usr/lib/systemd/system/fp-matrix-test.service
%config(noreplace) /etc/fp-matrix-test.conf
%post
[ -d /run/systemd/system ] && systemctl daemon-reload >/dev/null 2>&1 || true
%preun
if [ "\$1" = "0" ]; then
  [ -d /run/systemd/system ] && systemctl disable --now fp-matrix-test.service >/dev/null 2>&1 || true
fi
%postun
[ -d /run/systemd/system ] && systemctl daemon-reload >/dev/null 2>&1 || true
EOF
  rpmbuild -bb --define "_topdir $TOP" "$TOP/SPECS/$NAME.spec" >/tmp/fp-rpmbuild.log 2>&1 || {
    echo "build-testpkg: rpmbuild failed, see /tmp/fp-rpmbuild.log" >&2; tail -n 20 /tmp/fp-rpmbuild.log >&2; exit 1; }
  find "$TOP/RPMS" -name '*.rpm' -exec cp {} "$OUT/" \;
  rm -rf "$TOP" "$TREE"
  ;;

*) echo "build-testpkg: unknown family '$FAMILY'" >&2; exit 1 ;;
esac

echo "build-testpkg: built:"
ls -1 "$OUT"
