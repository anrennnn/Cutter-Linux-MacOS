# Cutter para Fedora (Workstation, KDE Plasma y los spins Cinnamon, XFCE…).
# También sirve en Fedora Atomic (Silverblue, Kinoite, Bazzite) con rpm-ostree.
#
#   rpmbuild -ba cutter-linux.spec

%global commit @COMMIT@

Name:           cutter-linux
Version:        @VERSION@
Release:        1%{?dist}
Summary:        Herramienta Recortes (Super+Shift+S) e historial del portapapeles (Super+V)
License:        MIT
URL:            https://github.com/anrennnn/Cutter-Linux
Source0:        %{url}/archive/%{commit}/Cutter-Linux-%{commit}.tar.gz
BuildArch:      noarch

BuildRequires:  make
Requires:       python3 >= 3.10
Requires:       python3-pyqt6
Requires:       qt6-qtsvg
Requires:       libnotify
Requires:       xdg-utils
Requires:       xdg-user-dirs
Requires:       hicolor-icon-theme
Recommends:     wl-clipboard
Recommends:     xdg-desktop-portal
Recommends:     qt6-qtwayland
Recommends:     xdotool
Recommends:     xprop
Recommends:     xwininfo
# El icono junto al reloj en GNOME necesita esta extensión.
Recommends:     (gnome-shell-extension-appindicator if gnome-shell)

%description
Cutter lleva a Linux la Herramienta Recortes y el historial del portapapeles de
Windows. Super+Shift+S abre la selección de recorte (rectángulo, ventana,
pantalla completa o forma libre) y Super+V el historial de textos e imágenes
copiados. Desde el menú o el icono junto al reloj se abre la ventana clásica
(Nuevo, Modo, Aplazar, Cancelar, Opciones) con un editor de anotaciones.

%prep
%autosetup -n Cutter-Linux-%{commit}

%build
# Nada que compilar: es Python.

%install
%make_install PREFIX=%{_prefix} SYSCONFDIR=%{_sysconfdir} \
    DOCDIR=%{_licensedir}/%{name} LICENSE_NAME=LICENSE

%files
%license %{_licensedir}/%{name}/LICENSE
%{_bindir}/cutter-linux
%{_prefix}/lib/cutter-linux/
%{_datadir}/applications/cutter-linux.desktop
%{_datadir}/icons/hicolor/scalable/apps/cutter-linux.svg
%config(noreplace) %{_sysconfdir}/xdg/autostart/cutter-linux.desktop

%changelog
* Fri Oct 23 2026 Cutter-Linux <cutter-linux@users.noreply.github.com> - @VERSION@-1
- Ventana principal clásica, editor de anotaciones, icono junto al reloj y opciones.
- Primer paquete para Fedora.
