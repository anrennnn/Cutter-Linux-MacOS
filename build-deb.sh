#!/bin/sh
# Construye dist/cutter-linux_<versión>_all.deb (Debian, Ubuntu, Mint, Pop!_OS, Zorin).
set -eu
cd "$(dirname "$0")"
VERSION=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' src/cutter_linux/config.py)
ROOT=build/cutter-linux_${VERSION}_all
rm -rf "$ROOT"
mkdir -p "$ROOT/DEBIAN" dist

make --no-print-directory install DESTDIR="$ROOT" LICENSE_NAME=copyright

cp packaging/DEBIAN/postinst packaging/DEBIAN/postrm "$ROOT/DEBIAN/"
SIZE=$(du -sk "$ROOT" | cut -f1)
sed -e "s/@VERSION@/$VERSION/" -e "s/@SIZE@/$SIZE/" packaging/DEBIAN/control > "$ROOT/DEBIAN/control"
dpkg-deb --root-owner-group --build "$ROOT" "dist/cutter-linux_${VERSION}_all.deb"
