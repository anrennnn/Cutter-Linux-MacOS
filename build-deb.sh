#!/bin/sh
# Construye dist/cutter-linux_<versión>_all.deb sin dependencias de compilación.
set -eu
cd "$(dirname "$0")"
VERSION=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' src/cutter_linux/config.py)
ROOT=build/cutter-linux_${VERSION}_all
rm -rf "$ROOT"
mkdir -p "$ROOT/DEBIAN" "$ROOT/usr/bin" "$ROOT/usr/lib/python3/dist-packages" \
    "$ROOT/usr/share/applications" "$ROOT/etc/xdg/autostart" \
    "$ROOT/usr/share/icons/hicolor/scalable/apps" "$ROOT/usr/share/doc/cutter-linux" dist

cp -r src/cutter_linux "$ROOT/usr/lib/python3/dist-packages/"
find "$ROOT" -name __pycache__ -prune -exec rm -rf {} +
cat > "$ROOT/usr/bin/cutter-linux" <<'SH'
#!/bin/sh
exec /usr/bin/python3 -m cutter_linux "$@"
SH
chmod 755 "$ROOT/usr/bin/cutter-linux"
install -m 644 data/applications/*.desktop "$ROOT/usr/share/applications/"
install -m 644 data/autostart/cutter-linux.desktop "$ROOT/etc/xdg/autostart/"
install -m 644 data/icons/cutter-linux.svg "$ROOT/usr/share/icons/hicolor/scalable/apps/"
install -m 644 LICENSE "$ROOT/usr/share/doc/cutter-linux/copyright"

cp packaging/DEBIAN/postinst packaging/DEBIAN/postrm "$ROOT/DEBIAN/"
SIZE=$(du -sk "$ROOT" | cut -f1)
sed -e "s/@VERSION@/$VERSION/" -e "s/@SIZE@/$SIZE/" packaging/DEBIAN/control > "$ROOT/DEBIAN/control"
dpkg-deb --root-owner-group --build "$ROOT" "dist/cutter-linux_${VERSION}_all.deb"
