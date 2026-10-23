#!/bin/bash
# Construye dist/Cutter.app y dist/Cutter-<versión>-macOS-<etiqueta>.dmg.
# Uso: packaging/macos/build.sh AppleSilicon|Intel
set -euo pipefail
cd "$(dirname "$0")/../.."
LABEL=${1:-$(uname -m)}
VERSION=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' src/cutter_linux/config.py)

rm -rf build dist
mkdir -p build
python packaging/macos/make_icns.py build/Cutter.icns
pyinstaller --noconfirm --clean --distpath dist --workpath build/pyinstaller packaging/macos/cutter.spec

# Firma ad hoc (sin cuenta de Apple Developer): obligatoria para que arranque en Apple Silicon.
codesign --force --deep --sign - dist/Cutter.app

mkdir -p build/dmg
cp -R dist/Cutter.app build/dmg/
ln -s /Applications build/dmg/Aplicaciones
cp packaging/macos/LEEME.txt "build/dmg/Léeme primero.txt"
hdiutil create -volname "Cutter $VERSION" -srcfolder build/dmg -ov -format UDZO \
    "dist/Cutter-$VERSION-macOS-$LABEL.dmg"
echo "Listo: dist/Cutter-$VERSION-macOS-$LABEL.dmg"
