"""
Navigateur moderne de sous-programmes NDS.
Permet de charger et sauvegarder des fichiers .nds
avec aperçu détaillé et interface optimisée productivité.
"""

import json
import os
import glob
from datetime import datetime
from typing import Optional, List

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget,
    QListWidgetItem, QLabel, QTextEdit, QLineEdit, QMessageBox, QSplitter,
    QWidget, QInputDialog
)
from PySide6.QtCore import Qt, Signal


class NdsFileItem(QListWidgetItem):
    """Item de liste représentant un fichier .nds avec métadonnées."""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.filename = os.path.basename(filepath)
        self.name = os.path.splitext(self.filename)[0]

        # Lire les métadonnées
        self.description = ""
        self.created = ""
        self.op_count = 0
        self.op_names: List[str] = []
        self.file_size = 0

        try:
            self.file_size = os.path.getsize(filepath)
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self.description = data.get('description', '')
            self.created = data.get('created', '')
            ops = data.get('operations', [])
            self.op_count = len(ops)
            self.op_names = [
                op.get('name', op.get('operation_type', '?'))
                for op in ops[:20]
            ]
        except Exception:
            pass

        # Texte affiché
        display = f"{self.name}"
        if self.op_count:
            display += f"  ({self.op_count} ops)"
        super().__init__(display)

        # Tooltip détaillé
        tip_lines = [f"Fichier: {self.filename}"]
        if self.description:
            tip_lines.append(f"Description: {self.description}")
        if self.created:
            tip_lines.append(f"Créé: {self.created[:19]}")
        tip_lines.append(f"Taille: {self._format_size(self.file_size)}")
        self.setToolTip("\n".join(tip_lines))

        # Date pour le tri
        self.mtime = os.path.getmtime(filepath)

    @staticmethod
    def _format_size(size: int) -> str:
        if size < 1024:
            return f"{size} o"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} Ko"
        return f"{size / (1024 * 1024):.1f} Mo"


class NdsBrowserDialog(QDialog):
    """Navigateur moderne de sous-programmes NDS."""

    # Signal émis quand l'utilisateur charge un fichier
    file_loaded = Signal(str)  # filepath

    def __init__(self, programs_dir: str, current_ops: list = None,
                 parent=None):
        """
        Args:
            programs_dir: Répertoire contenant les .nds
            current_ops: Liste des OperationInstance actuelles (pour sauver)
            parent: Widget parent
        """
        super().__init__(parent)
        self.setWindowTitle("📂 Sous-programmes NDS")
        # Taille dynamique selon l'écran
        from PySide6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            w = min(750, int(avail.width() * 0.5))
            h = min(600, int(avail.height() * 0.7))
        else:
            w, h = 750, 550
        self.resize(w, h)
        self.programs_dir = programs_dir
        self.current_ops = current_ops or []
        self.selected_filepath: Optional[str] = None
        self._mode = "load"  # "load" ou "save"

        self._setup_ui()
        self._apply_style()
        self._populate_list()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(8)

        # ── Barre du haut : Recherche + Bouton Sauver ──
        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)

        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍 Rechercher un sous-programme...")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._filter_list)
        top_bar.addWidget(self._search, stretch=1)

        # Bouton sauver: visible seulement si on a des ops
        self._save_btn = QPushButton("💾 Sauvegarder comme NDS...")
        self._save_btn.setObjectName("accent")
        self._save_btn.setMinimumHeight(32)
        self._save_btn.clicked.connect(self._on_save_new)
        self._save_btn.setEnabled(len(self.current_ops) > 0)
        self._save_btn.setToolTip(
            "Sauvegarder les opérations actuelles comme nouveau sous-programme")
        top_bar.addWidget(self._save_btn)

        main_layout.addLayout(top_bar)

        # ── Splitter : Liste + Aperçu ──
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Liste des fichiers
        list_container = QWidget()
        list_layout = QVBoxLayout(list_container)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(4)

        list_header = QLabel("Sous-programmes disponibles")
        list_header.setObjectName("section_header")
        list_layout.addWidget(list_header)

        self._file_list = QListWidget()
        self._file_list.setMinimumWidth(280)
        self._file_list.currentItemChanged.connect(self._on_item_selected)
        self._file_list.itemDoubleClicked.connect(self._on_double_click)
        list_layout.addWidget(self._file_list)

        self._count_label = QLabel("0 fichier(s)")
        self._count_label.setObjectName("count_label")
        list_layout.addWidget(self._count_label)

        splitter.addWidget(list_container)

        # Panneau aperçu
        preview_container = QWidget()
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(4)

        preview_header = QLabel("Aperçu")
        preview_header.setObjectName("section_header")
        preview_layout.addWidget(preview_header)

        self._preview = QTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setPlaceholderText(
            "Sélectionnez un sous-programme pour voir son contenu...")
        preview_layout.addWidget(self._preview)

        splitter.addWidget(preview_container)
        splitter.setSizes([320, 400])

        main_layout.addWidget(splitter, stretch=1)

        # ── Barre de boutons ──
        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(8)

        self._delete_btn = QPushButton("🗑 Supprimer")
        self._delete_btn.setObjectName("danger")
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._on_delete)
        btn_bar.addWidget(self._delete_btn)

        self._rename_btn = QPushButton("✏ Renommer")
        self._rename_btn.setEnabled(False)
        self._rename_btn.clicked.connect(self._on_rename)
        btn_bar.addWidget(self._rename_btn)

        btn_bar.addStretch()

        self._load_btn = QPushButton("📥 Charger")
        self._load_btn.setObjectName("primary")
        self._load_btn.setEnabled(False)
        self._load_btn.setMinimumWidth(120)
        self._load_btn.setMinimumHeight(34)
        self._load_btn.clicked.connect(self._on_load)
        btn_bar.addWidget(self._load_btn)

        cancel_btn = QPushButton("Fermer")
        cancel_btn.setMinimumHeight(34)
        cancel_btn.clicked.connect(self.reject)
        btn_bar.addWidget(cancel_btn)

        main_layout.addLayout(btn_bar)

    def _apply_style(self):
        self.setStyleSheet("""
            QDialog {
                background: #1e1e2e;
                color: #cdd6f4;
            }
            QLabel#section_header {
                font-weight: bold;
                font-size: 12px;
                color: #89b4fa;
                padding: 2px 0;
            }
            QLabel#count_label {
                color: #6c7086;
                font-size: 11px;
            }
            QLineEdit {
                background: #313244;
                border: 1px solid #45475a;
                border-radius: 6px;
                padding: 6px 10px;
                color: #cdd6f4;
                font-size: 13px;
            }
            QLineEdit:focus {
                border-color: #89b4fa;
            }
            QListWidget {
                background: #181825;
                border: 1px solid #45475a;
                border-radius: 6px;
                padding: 4px;
                color: #cdd6f4;
                font-size: 13px;
            }
            QListWidget::item {
                padding: 6px 10px;
                border-radius: 4px;
            }
            QListWidget::item:selected {
                background: #313244;
                color: #cdd6f4;
                border-left: 3px solid #89b4fa;
            }
            QListWidget::item:hover:!selected {
                background: #1e1e2e;
            }
            QTextEdit {
                background: #181825;
                border: 1px solid #45475a;
                border-radius: 6px;
                padding: 8px;
                color: #cdd6f4;
                font-family: "Cascadia Code", "Consolas", monospace;
                font-size: 12px;
            }
            QPushButton {
                background: #313244;
                border: 1px solid #45475a;
                border-radius: 6px;
                padding: 6px 16px;
                color: #cdd6f4;
                font-size: 12px;
            }
            QPushButton:hover {
                background: #45475a;
            }
            QPushButton:pressed {
                background: #585b70;
            }
            QPushButton:disabled {
                color: #585b70;
                background: #1e1e2e;
            }
            QPushButton#primary {
                background: #89b4fa;
                color: #1e1e2e;
                font-weight: bold;
                border: none;
            }
            QPushButton#primary:hover {
                background: #b4d0fb;
            }
            QPushButton#primary:disabled {
                background: #45475a;
                color: #585b70;
            }
            QPushButton#accent {
                background: #a6e3a1;
                color: #1e1e2e;
                font-weight: bold;
                border: none;
            }
            QPushButton#accent:hover {
                background: #c6f0c1;
            }
            QPushButton#accent:disabled {
                background: #45475a;
                color: #585b70;
            }
            QPushButton#danger {
                color: #f38ba8;
            }
            QPushButton#danger:hover {
                background: #3a2030;
            }
            QSplitter::handle {
                background: #45475a;
                width: 2px;
            }
        """)

    def _populate_list(self):
        """Charge la liste des fichiers .nds."""
        self._file_list.clear()
        self._all_items: List[NdsFileItem] = []

        pattern = os.path.join(self.programs_dir, "*.nds")
        files = glob.glob(pattern)

        for fp in files:
            item = NdsFileItem(fp)
            self._all_items.append(item)

        # Trier par date de modification (plus récent en premier)
        self._all_items.sort(key=lambda it: it.mtime, reverse=True)

        for item in self._all_items:
            self._file_list.addItem(item)

        self._count_label.setText(f"{len(self._all_items)} fichier(s)")

    def _filter_list(self, text: str):
        """Filtre la liste par texte."""
        text = text.lower().strip()
        for i in range(self._file_list.count()):
            item = self._file_list.item(i)
            if isinstance(item, NdsFileItem):
                match = (not text
                         or text in item.name.lower()
                         or text in item.description.lower()
                         or any(text in n.lower() for n in item.op_names))
                item.setHidden(not match)

        # Compter les visibles
        visible = sum(1 for i in range(self._file_list.count())
                      if not self._file_list.item(i).isHidden())
        self._count_label.setText(
            f"{visible}/{len(self._all_items)} fichier(s)")

    def _on_item_selected(self, current, previous):
        """Quand un fichier est sélectionné dans la liste."""
        if not current or not isinstance(current, NdsFileItem):
            self._preview.clear()
            self._load_btn.setEnabled(False)
            self._delete_btn.setEnabled(False)
            self._rename_btn.setEnabled(False)
            self.selected_filepath = None
            return

        self.selected_filepath = current.filepath
        self._load_btn.setEnabled(True)
        self._delete_btn.setEnabled(True)
        self._rename_btn.setEnabled(True)
        self._show_preview(current)

    def _show_preview(self, item: NdsFileItem):
        """Affiche l'aperçu détaillé d'un fichier NDS."""
        lines = []
        lines.append(f"╔══ {item.name} ══╗")
        lines.append("")

        if item.description:
            lines.append(f"📋 {item.description}")
            lines.append("")

        if item.created:
            try:
                dt = datetime.fromisoformat(item.created)
                lines.append(f"📅 Créé: {dt.strftime('%d/%m/%Y %H:%M')}")
            except ValueError:
                lines.append(f"📅 Créé: {item.created[:19]}")

        lines.append(f"📦 Taille: {item._format_size(item.file_size)}")
        lines.append(f"⚙ Opérations: {item.op_count}")
        lines.append("")

        if item.op_names:
            lines.append("─── Contenu ───")
            for i, name in enumerate(item.op_names, 1):
                lines.append(f"  {i:2d}. {name}")
            if item.op_count > len(item.op_names):
                lines.append(
                    f"  ... et {item.op_count - len(item.op_names)} autre(s)")

        self._preview.setPlainText("\n".join(lines))

    def _on_double_click(self, item):
        """Double-clic = charger directement."""
        if isinstance(item, NdsFileItem):
            self.selected_filepath = item.filepath
            self.accept()

    def _on_load(self):
        """Charge le fichier sélectionné."""
        if self.selected_filepath:
            self.accept()

    def _on_save_new(self):
        """Sauvegarde les opérations actuelles comme nouveau .nds."""
        if not self.current_ops:
            QMessageBox.information(
                self, "Info", "Aucune opération à sauvegarder.")
            return

        # Demander le nom
        name, ok = QInputDialog.getText(
            self, "Nouveau sous-programme",
            "Nom du sous-programme:",
            QLineEdit.EchoMode.Normal,
            f"sous_programme_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        if not ok or not name.strip():
            return

        # Demander la description
        desc, ok = QInputDialog.getText(
            self, "Description",
            "Description (optionnel):",
            QLineEdit.EchoMode.Normal, "")
        if not ok:
            desc = ""

        # Nettoyer le nom
        safe_name = "".join(
            c for c in name.strip() if c.isalnum() or c in "._- ")
        if not safe_name:
            safe_name = "sous_programme"

        filepath = os.path.join(self.programs_dir, f"{safe_name}.nds")

        # Vérifier si existe déjà
        if os.path.exists(filepath):
            reply = QMessageBox.question(
                self, "Fichier existant",
                f"Le fichier '{safe_name}.nds' existe déjà. Écraser ?",
                QMessageBox.StandardButton.Yes |
                QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return

        try:
            from src.io.program_serializer import SubProgramSerializer
            SubProgramSerializer.save(
                self.current_ops, filepath, description=desc)
            # Rafraîchir la liste
            self._populate_list()
            self._preview.setPlainText(
                f"✅ Sauvegardé: {safe_name}.nds\n"
                f"   {len(self.current_ops)} opération(s)")
        except Exception as e:
            QMessageBox.warning(
                self, "Erreur",
                f"Impossible de sauvegarder:\n{e}")

    def _on_delete(self):
        """Supprime le fichier sélectionné."""
        if not self.selected_filepath:
            return
        name = os.path.basename(self.selected_filepath)
        reply = QMessageBox.question(
            self, "Supprimer",
            f"Supprimer le sous-programme '{name}' ?\n"
            "Cette action est irréversible.",
            QMessageBox.StandardButton.Yes |
            QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            try:
                os.remove(self.selected_filepath)
                self.selected_filepath = None
                self._populate_list()
                self._preview.clear()
                self._load_btn.setEnabled(False)
                self._delete_btn.setEnabled(False)
                self._rename_btn.setEnabled(False)
            except Exception as e:
                QMessageBox.warning(
                    self, "Erreur", f"Impossible de supprimer:\n{e}")

    def _on_rename(self):
        """Renomme le fichier sélectionné."""
        if not self.selected_filepath:
            return
        old_name = os.path.splitext(
            os.path.basename(self.selected_filepath))[0]
        new_name, ok = QInputDialog.getText(
            self, "Renommer",
            "Nouveau nom:",
            QLineEdit.EchoMode.Normal,
            old_name)
        if not ok or not new_name.strip() or new_name == old_name:
            return

        safe_name = "".join(
            c for c in new_name.strip() if c.isalnum() or c in "._- ")
        if not safe_name:
            return

        new_path = os.path.join(
            os.path.dirname(self.selected_filepath),
            f"{safe_name}.nds")

        if os.path.exists(new_path):
            QMessageBox.warning(
                self, "Erreur",
                f"Un fichier '{safe_name}.nds' existe déjà.")
            return

        try:
            os.rename(self.selected_filepath, new_path)
            self.selected_filepath = new_path
            self._populate_list()
        except Exception as e:
            QMessageBox.warning(
                self, "Erreur", f"Impossible de renommer:\n{e}")
