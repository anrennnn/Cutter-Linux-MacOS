"""Ventana «Opciones»."""

from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout,
)

from . import config
from . import settings as settings_mod
from .editor import icon


class OptionsDialog(QDialog):
    def __init__(self, parent=None, on_clear_history=None):
        super().__init__(parent)
        self.on_clear_history = on_clear_history
        self.setWindowTitle(f"Opciones de {config.APP_NAME}")
        self.setWindowIcon(icon(config.APP_ID))
        s = settings_mod.current
        layout = QVBoxLayout(self)

        snips = QGroupBox("Recortes")
        v = QVBoxLayout(snips)
        self.copy = QCheckBox("Copiar siempre los recortes al portapapeles")
        self.copy.setChecked(s.copy_to_clipboard)
        v.addWidget(self.copy)
        self.autosave = QCheckBox(f"Guardar automáticamente los recortes de {config.SNIP_KEYS} en:")
        self.autosave.setChecked(s.autosave)
        v.addWidget(self.autosave)
        row = QHBoxLayout()
        self.folder = QLineEdit(str(s.screenshots_dir()))
        row.addWidget(self.folder, 1)
        browse = QPushButton("Cambiar…")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        v.addLayout(row)
        self.autosave.toggled.connect(self.folder.setEnabled)
        self.autosave.toggled.connect(browse.setEnabled)
        self.folder.setEnabled(s.autosave)
        browse.setEnabled(s.autosave)
        self.notify = QCheckBox("Mostrar una notificación después de recortar")
        self.notify.setChecked(s.notify)
        v.addWidget(self.notify)
        self.editor = QCheckBox(f"Abrir el editor después de recortar con {config.SNIP_KEYS}")
        self.editor.setChecked(s.open_editor_after_shortcut)
        v.addWidget(self.editor)
        layout.addWidget(snips)

        hist = QGroupBox(f"Historial del portapapeles ({config.HISTORY_KEYS})")
        v = QVBoxLayout(hist)
        self.history = QCheckBox("Guardar en el historial lo que copio")
        self.history.setChecked(s.history_enabled)
        v.addWidget(self.history)
        row = QHBoxLayout()
        row.addWidget(QLabel("Número máximo de elementos (sin contar los fijados):"))
        self.limit = QSpinBox()
        self.limit.setRange(5, 200)
        self.limit.setValue(s.history_limit)
        row.addWidget(self.limit)
        row.addStretch(1)
        v.addLayout(row)
        clear = QPushButton(icon("edit-clear-history", "edit-clear"), "Borrar el historial ahora")
        clear.clicked.connect(self._clear_history)
        v.addWidget(clear)
        layout.addWidget(hist)

        app = QGroupBox("Aplicación")
        v = QVBoxLayout(app)
        self.tray = QCheckBox(
            "Mostrar el icono de Cutter en la barra de menús" if config.IS_MAC
            else "Mostrar el icono de Cutter junto al reloj"
        )
        self.tray.setChecked(s.tray_icon)
        v.addWidget(self.tray)
        if config.desktop() == "gnome":
            hint = QLabel("En GNOME hace falta la extensión «AppIndicator and KStatusNotifierItem Support».")
            hint.setWordWrap(True)
            hint.setStyleSheet("color: palette(placeholder-text);")
            v.addWidget(hint)
        self.autostart = QCheckBox(f"Iniciar Cutter al iniciar sesión (necesario para {config.HISTORY_KEYS})")
        self.autostart.setChecked(s.autostart)
        v.addWidget(self.autostart)
        if config.IS_MAC:
            # En Mac los atajos los registra Cutter; lo que hace falta son permisos.
            for label, pane in (
                ("Permiso de grabación de pantalla (para recortar)…", "Privacy_ScreenCapture"),
                ("Permiso de accesibilidad (para pegar desde el historial)…", "Privacy_Accessibility"),
            ):
                button = QPushButton(icon("configure"), label)
                button.clicked.connect(lambda _c=False, p=pane: _open_mac_settings(p))
                v.addWidget(button)
        else:
            keys = QPushButton(icon("preferences-desktop-keyboard-shortcuts", "input-keyboard"),
                               f"Volver a configurar {config.SNIP_KEYS} y {config.HISTORY_KEYS}")
            keys.clicked.connect(self._shortcuts)
            v.addWidget(keys)
        layout.addWidget(app)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Carpeta para los recortes", self.folder.text())
        if folder:
            self.folder.setText(folder)

    def _clear_history(self):
        if self.on_clear_history is not None:
            self.on_clear_history()

    def _shortcuts(self):
        from .shortcuts import setup_shortcuts

        QMessageBox.information(self, config.APP_NAME, "\n".join(setup_shortcuts(force=True)))

    def accept(self):
        s = settings_mod.current
        s.copy_to_clipboard = self.copy.isChecked()
        s.autosave = self.autosave.isChecked()
        folder = self.folder.text().strip()
        s.save_dir = "" if folder == str(config.screenshots_dir()) else folder
        s.notify = self.notify.isChecked()
        s.open_editor_after_shortcut = self.editor.isChecked()
        s.history_enabled = self.history.isChecked()
        s.history_limit = self.limit.value()
        s.tray_icon = self.tray.isChecked()
        s.autostart = self.autostart.isChecked()
        s.save()
        super().accept()


def _open_mac_settings(pane: str):
    import subprocess

    subprocess.Popen(["/usr/bin/open", f"x-apple.systempreferences:com.apple.preference.security?{pane}"])
