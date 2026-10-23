# Instalación común a todos los paquetes (.deb, Arch/CachyOS) y a `sudo make install`.
#
#   make install DESTDIR=/ruta/paquete PREFIX=/usr DOCDIR=/usr/share/licenses/cutter-linux
#
# El código se instala en un directorio propio y no en site-packages, así el
# paquete sigue funcionando cuando la distribución actualiza Python (en Arch
# eso pasa a menudo).

PREFIX  ?= /usr
SYSCONFDIR ?= /etc
LIBDIR  ?= $(PREFIX)/lib/cutter-linux
DOCDIR  ?= $(PREFIX)/share/doc/cutter-linux
LICENSE_NAME ?= LICENSE
DESTDIR ?=

APPS = data/applications/cutter-linux.desktop

.PHONY: install uninstall

install:
	install -d "$(DESTDIR)$(LIBDIR)/cutter_linux"
	install -m 644 src/cutter_linux/*.py "$(DESTDIR)$(LIBDIR)/cutter_linux/"
	install -d "$(DESTDIR)$(PREFIX)/bin"
	printf '%s\n' '#!/bin/sh' \
	    'export PYTHONPATH="$(LIBDIR)$${PYTHONPATH:+:$$PYTHONPATH}"' \
	    'exec /usr/bin/python3 -m cutter_linux "$$@"' > "$(DESTDIR)$(PREFIX)/bin/cutter-linux"
	chmod 755 "$(DESTDIR)$(PREFIX)/bin/cutter-linux"
	install -Dm 644 -t "$(DESTDIR)$(PREFIX)/share/applications" $(APPS)
	install -Dm 644 data/autostart/cutter-linux.desktop "$(DESTDIR)$(SYSCONFDIR)/xdg/autostart/cutter-linux.desktop"
	install -Dm 644 data/icons/cutter-linux.svg "$(DESTDIR)$(PREFIX)/share/icons/hicolor/scalable/apps/cutter-linux.svg"
	install -Dm 644 LICENSE "$(DESTDIR)$(DOCDIR)/$(LICENSE_NAME)"

uninstall:
	rm -rf "$(DESTDIR)$(LIBDIR)"
	rm -f "$(DESTDIR)$(PREFIX)/bin/cutter-linux" \
	      "$(DESTDIR)$(SYSCONFDIR)/xdg/autostart/cutter-linux.desktop" \
	      "$(DESTDIR)$(PREFIX)/share/icons/hicolor/scalable/apps/cutter-linux.svg" \
	      $(addprefix "$(DESTDIR)$(PREFIX)/share/applications/,$(addsuffix ",$(notdir $(APPS))))
	rm -rf "$(DESTDIR)$(DOCDIR)"
