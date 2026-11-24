"""
Dialogue de navigation des programmes et sous-programmes sauvegardés.
"""

import json
import os
import glob
from datetime import datetime
from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget,
    QListWidgetItem, QTextEdit, QTabWidget, QMessageBox, QLineEdit, QSplitter,
    QInputDialog, QMenu, QWidget
)
from PySide6.QtCore import Qt


class ProgramBrowserDialog(QDialog):
    """Navigateur de programmes et sous-programmes."""

    def __init__(self, programs_dir: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Programmes enregistrés")
        self.resize(700, 500)
        self.programs_dir = programs_dir
        self.selected_filepath: Optional[str] = None
        self.selected_type: str = ""  # "program" ou "subprogram"
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # Tabs
        tabs = QTabWidget()

        # Tab Programmes: groupes à gauche, programmes à droite
        tabs.addTab(self._build_programs_tab(), "Programmes (.ndp)")

        # Tab Sous-programmes
        self.subprog_list = QListWidget()
        self._populate_list(self.subprog_list, "*.nds")
        self.subprog_list.currentRowChanged.connect(
            lambda r: self._on_selected(r, "subprogram", self.subprog_list))
        tabs.addTab(self.subprog_list, "Sous-programmes (.nds)")

        layout.addWidget(tabs)

        # Preview
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(150)
        self.preview.setPlaceholderText("Sélectionner un fichier pour voir l'aperçu")
        layout.addWidget(self.preview)

        # Boutons
        btn_layout = QHBoxLayout()

        del_btn = QPushButton("Supprimer")
        del_btn.setObjectName("danger")
        del_btn.clicked.connect(self._on_delete)
        btn_layout.addWidget(del_btn)

        btn_layout.addStretch()

        open_btn = QPushButton("Ouvrir")
        open_btn.setObjectName("primary")
        open_btn.clicked.connect(self.accept)
        btn_layout.addWidget(open_btn)

        cancel_btn = QPushButton("Annuler")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

    # ── Onglet Programmes: groupes + recherche ──

    def _build_programs_tab(self) -> QWidget:
        """Groupes à gauche, programmes du groupe à droite.

        Avec une centaine de groupes, une liste plate ne permet plus
        de retrouver un programme: on navigue par groupe, et la
        recherche traverse TOUS les groupes."""
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)

        self._search = QLineEdit()
        self._search.setPlaceholderText(
            "Rechercher (nom, groupe, auteur, commentaire) — "
            "cherche dans tous les groupes")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._refresh_programs)
        v.addWidget(self._search)

        split = QSplitter(Qt.Orientation.Horizontal)
        self.group_list = QListWidget()
        self.group_list.setMaximumWidth(230)
        self.group_list.currentRowChanged.connect(
            lambda _r: self._refresh_programs())
        self.group_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.group_list.customContextMenuRequested.connect(
            self._on_group_menu)
        split.addWidget(self.group_list)

        self.program_list = QListWidget()
        self.program_list.currentRowChanged.connect(
            lambda r: self._on_selected(r, "program", self.program_list))
        self.program_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.program_list.customContextMenuRequested.connect(
            self._on_program_menu)
        split.addWidget(self.program_list)
        split.setStretchFactor(1, 1)
        v.addWidget(split, stretch=1)

        self._refresh_groups()
        return page

    def _refresh_groups(self):
        """Liste des groupes avec leur effectif."""
        from src.io import program_library as pl
        current = self._selected_group()
        counts = pl.group_counts(self.programs_dir)
        total = sum(counts.values())
        self.group_list.blockSignals(True)
        self.group_list.clear()
        item = QListWidgetItem(f"★ Tous les programmes  ({total})")
        item.setData(Qt.ItemDataRole.UserRole, None)
        self.group_list.addItem(item)
        for group, n in counts.items():
            item = QListWidgetItem(f"{group}  ({n})")
            item.setData(Qt.ItemDataRole.UserRole, group)
            self.group_list.addItem(item)
        self.group_list.blockSignals(False)
        row = 0
        for i in range(self.group_list.count()):
            if self.group_list.item(i).data(
                    Qt.ItemDataRole.UserRole) == current:
                row = i
                break
        self.group_list.setCurrentRow(row)

    def _selected_group(self):
        item = self.group_list.currentItem() \
            if hasattr(self, 'group_list') else None
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _refresh_programs(self):
        from src.io import program_library as pl
        query = self._search.text() if hasattr(self, '_search') else ""
        # Une recherche porte sur TOUS les groupes: chercher ne doit
        # pas obliger à deviner où le programme est rangé
        group = None if query.strip() else self._selected_group()
        entries = pl.list_programs(self.programs_dir, group, query)
        self.program_list.blockSignals(True)
        self.program_list.clear()
        for e in entries:
            stamp = datetime.fromtimestamp(e['mtime']).strftime(
                "%d/%m/%y %H:%M") if e['mtime'] else "?"
            label = f"{e['name']}   ·   {e['operations']} opé   ·   {stamp}"
            if group is None and e['group']:
                label += f"   [{e['group']}]"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, e['path'])
            item.setToolTip(e['comment'] or e['path'])
            self.program_list.addItem(item)
        self.program_list.blockSignals(False)

    def _on_group_menu(self, pos):
        from src.io import program_library as pl
        menu = QMenu(self)
        act_new = menu.addAction("➕ Nouveau groupe…")
        item = self.group_list.itemAt(pos)
        group = item.data(Qt.ItemDataRole.UserRole) if item else None
        act_ren = None
        if group and group != pl.ROOT_GROUP:
            act_ren = menu.addAction(f"✏ Renommer « {group} »…")
        chosen = menu.exec(self.group_list.mapToGlobal(pos))
        if chosen == act_new:
            name, ok = QInputDialog.getText(
                self, "Nouveau groupe", "Nom du groupe:")
            if ok and pl.create_group(self.programs_dir, name):
                self._refresh_groups()
        elif act_ren is not None and chosen == act_ren:
            name, ok = QInputDialog.getText(
                self, "Renommer le groupe", "Nouveau nom:",
                text=group)
            if ok and pl.rename_group(self.programs_dir, group, name):
                self._refresh_groups()
                self._refresh_programs()

    def _on_program_menu(self, pos):
        from src.io import program_library as pl
        item = self.program_list.itemAt(pos)
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        move = menu.addMenu("📁 Déplacer vers")
        actions = {}
        for group in pl.list_groups(self.programs_dir):
            actions[move.addAction(group)] = group
        move.addSeparator()
        new_act = move.addAction("➕ Nouveau groupe…")
        chosen = menu.exec(self.program_list.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is new_act:
            name, ok = QInputDialog.getText(
                self, "Nouveau groupe", "Nom du groupe:")
            if not ok:
                return
            group = pl.create_group(self.programs_dir, name)
            if not group:
                return
        elif chosen in actions:
            group = actions[chosen]
        else:
            return
        try:
            pl.move_to_group(self.programs_dir, path, group)
        except OSError as e:
            QMessageBox.warning(self, "Déplacer", str(e))
            return
        self._refresh_groups()
        self._refresh_programs()

    def _populate_list(self, list_widget: QListWidget, pattern: str):
        files = glob.glob(os.path.join(self.programs_dir, pattern))
        files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
        for fp in files:
            item = QListWidgetItem(os.path.basename(fp))
            item.setData(Qt.ItemDataRole.UserRole, fp)
            list_widget.addItem(item)

    def _on_selected(self, row: int, file_type: str,
                     list_widget: QListWidget):
        if row < 0:
            return
        item = list_widget.item(row)
        if not item:
            return
        filepath = item.data(Qt.ItemDataRole.UserRole)
        self.selected_filepath = filepath
        self.selected_type = file_type
        self._show_preview(filepath)

    def _show_preview(self, filepath: str):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            settings = data.get("settings", {})
            ops = data.get("operations", [])
            lines = []
            if settings:
                lines.append(f"Auteur: {settings.get('author', '?')}")
                lines.append(f"Commentaire: {settings.get('comment', '')}")
            lines.append(f"Modifié: {data.get('modified', '?')}")
            lines.append(f"Opérations: {len(ops)}")
            for op in ops[:10]:
                name = op.get('name', '?')
                otype = op.get('operation_type', '?')
                lines.append(f"  - {name} ({otype})")
            if len(ops) > 10:
                lines.append(f"  ... et {len(ops) - 10} autres")
            self.preview.setPlainText("\n".join(lines))
        except Exception as e:
            self.preview.setPlainText(f"Erreur: {e}")

    def _on_delete(self):
        if not self.selected_filepath:
            return
        name = os.path.basename(self.selected_filepath)
        reply = QMessageBox.question(
            self, "Supprimer",
            f"Supprimer le fichier '{name}' ?",
            QMessageBox.StandardButton.Yes |
            QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            try:
                os.remove(self.selected_filepath)
                # Rafraîchir
                self._refresh_groups()
                self._refresh_programs()
                self.subprog_list.clear()
                self._populate_list(self.subprog_list, "*.nds")
                self.preview.clear()
                self.selected_filepath = None
            except Exception as e:
                QMessageBox.warning(
                    self, "Erreur", f"Impossible de supprimer: {e}")
