#!/bin/sh
# Instala Cutter solo para tu usuario, sin root y sin reiniciar.
#
# Pensado para sistemas inmutables (Bazzite, Fedora Silverblue/Kinoite, SteamOS)
# y para cualquier distribución donde no quieras tocar el sistema.
#
#   ./instalar-usuario.sh                # instalar o actualizar
#   ./instalar-usuario.sh --desinstalar  # quitarlo
#
# Usa PyQt6 del sistema si existe; si no, lo descarga en un entorno propio
# (~/.local/share/cutter-linux/venv) con pip.
set -eu

ORIGEN=$(cd "$(dirname "$0")" && pwd)
DATOS="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG="${XDG_CONFIG_HOME:-$HOME/.config}"
BASE="$DATOS/cutter-linux"
BIN="$HOME/.local/bin"
EXE="$BIN/cutter-linux"

desinstalar() {
    "$EXE" salir 2>/dev/null || true
    rm -rf "$BASE/app" "$BASE/venv"
    rm -f "$EXE" "$DATOS/applications/cutter-linux.desktop" \
        "$DATOS/icons/hicolor/scalable/apps/cutter-linux.svg" \
        "$CONFIG/autostart/cutter-linux.desktop"
    echo "Cutter desinstalado. Tu historial sigue en $BASE/historial (bórralo si no lo quieres)."
}

if [ "${1:-}" = "--desinstalar" ]; then
    desinstalar
    exit 0
fi

command -v python3 >/dev/null 2>&1 || { echo "Hace falta python3." >&2; exit 1; }
python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' || {
    echo "Hace falta Python 3.10 o más reciente." >&2; exit 1; }

echo ">> Preparando Python…"
if python3 -c 'import PyQt6.QtWidgets, PyQt6.QtDBus' 2>/dev/null; then
    PYTHON=$(command -v python3)
    echo "   Se usará el PyQt6 del sistema."
else
    if [ ! -x "$BASE/venv/bin/python" ]; then
        python3 -m venv "$BASE/venv" || {
            echo "No se pudo crear el entorno de Python (falta python3-venv)." >&2; exit 1; }
    fi
    "$BASE/venv/bin/python" -m pip install --quiet --upgrade pip
    "$BASE/venv/bin/python" -m pip install --quiet --upgrade "PyQt6>=6.5,<7"
    PYTHON="$BASE/venv/bin/python"
    echo "   PyQt6 instalado en $BASE/venv."
fi

echo ">> Copiando Cutter…"
mkdir -p "$BASE/app/cutter_linux" "$BIN" "$DATOS/applications" \
    "$DATOS/icons/hicolor/scalable/apps" "$CONFIG/autostart"
rm -f "$BASE/app/cutter_linux/"*.py
cp "$ORIGEN"/src/cutter_linux/*.py "$ORIGEN"/src/cutter_linux/*.svg "$BASE/app/cutter_linux/"
cp "$ORIGEN/data/icons/cutter-linux.svg" "$DATOS/icons/hicolor/scalable/apps/"

cat > "$EXE" <<SH
#!/bin/sh
export PYTHONPATH="$BASE/app\${PYTHONPATH:+:\$PYTHONPATH}"
exec "$PYTHON" -m cutter_linux "\$@"
SH
chmod 755 "$EXE"

# Los lanzadores usan la ruta completa: ~/.local/bin no siempre está en el PATH
# de los atajos del escritorio.
sed "s|^Exec=cutter-linux|Exec=$EXE|" "$ORIGEN/data/applications/cutter-linux.desktop" \
    > "$DATOS/applications/cutter-linux.desktop"
if ! grep -q '^Hidden=true' "$CONFIG/autostart/cutter-linux.desktop" 2>/dev/null; then
    sed "s|^Exec=cutter-linux|Exec=$EXE|" "$ORIGEN/data/autostart/cutter-linux.desktop" \
        > "$CONFIG/autostart/cutter-linux.desktop"
fi
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q "$DATOS/applications" || true

echo ">> Comprobando herramientas opcionales…"
falta=""
if [ -n "${WAYLAND_DISPLAY:-}" ]; then
    command -v wl-paste >/dev/null 2>&1 || falta="$falta wl-clipboard"
else
    command -v xdotool >/dev/null 2>&1 || falta="$falta xdotool"
fi
command -v notify-send >/dev/null 2>&1 || falta="$falta libnotify"
if [ "$PYTHON" = "$BASE/venv/bin/python" ] && ! ldconfig -p 2>/dev/null | grep -q 'libxcb-cursor\.so\.0'; then
    # El PyQt6 de pip lo necesita para X11 y XWayland.
    falta="$falta xcb-util-cursor"
fi
if [ -n "$falta" ]; then
    echo "   Recomendado instalar:$falta"
    echo "   (Fedora: sudo dnf install …  ·  Bazzite/Silverblue: rpm-ostree install … y reiniciar"
    echo "    ·  Debian/Ubuntu: libxcb-cursor0, wl-clipboard, xdotool, libnotify-bin)"
fi

"$EXE" salir 2>/dev/null || true
nohup "$EXE" segundo-plano >/dev/null 2>&1 &
echo
echo "Cutter $("$EXE" version | cut -d' ' -f2) instalado para $(id -un)."
echo "Ábrelo desde el menú de aplicaciones. Atajos: Super+Shift+S (recortar) y Super+V (historial)."
case ":$PATH:" in *":$BIN:"*) ;; *) echo "Nota: $BIN no está en tu PATH; el menú y los atajos funcionan igual." ;; esac
