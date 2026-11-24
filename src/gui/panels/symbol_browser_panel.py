"""
Navigateur de la bibliothèque de symboles TypeEdit (.smb).
Grille de vignettes (extraites des fichiers), recherche, filtre par
sous-dossier, aperçu agrandi, double-clic pour ouvrir dans TypeEdit.
"""

import os
from typing import List

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QListWidget, QListWidgetItem, QFileDialog, QListView,
    QTreeWidget, QTreeWidgetItem,
)
from PySide6.QtCore import Qt, QSize, Signal, QTimer
from PySide6.QtGui import QIcon

from src.integrations.smb_thumbnail import (
    extract_smb_thumbnail, upscale_lineart)


class SymbolBrowserPanel(QWidget):
    """Bibliothèque de symboles .smb avec vignettes."""

    symbols_dir_changed = Signal(str)  # pour persister le dossier
    symbol_to_canvas = Signal(str)     # filepath → import sur le canvas

    def __init__(self, symbols_dir: str = "", parent=None):
        super().__init__(parent)
        self._symbols_dir = symbols_dir
        self._all_files: List[str] = []
        self._icon_cache = {}  # filepath -> QIcon bitmap (fallback)
        # Vignettes VECTORIELLES rendues progressivement en arrière-plan
        self._vector_cache = {}  # filepath -> QIcon | None (échec)
        self._items_by_fp = {}   # filepath -> QListWidgetItem affiché
        self._vector_queue: List[str] = []
        self._vector_timer = QTimer(self)
        self._vector_timer.setInterval(30)
        self._vector_timer.timeout.connect(self._process_vector_batch)
        # Le scan (parcours disque + décodage des vignettes de
        # plusieurs milliers de .smb) est DIFFÉRÉ à la première
        # ouverture de l'onglet: c'était le plus gros poste du
        # démarrage, payé même sans jamais ouvrir la bibliothèque.
        self._scan_pending = True
        self._setup_ui()

    def showEvent(self, event):
        super().showEvent(event)
        if self._scan_pending:
            self._scan_pending = False
            if self._symbols_dir and os.path.isdir(self._symbols_dir):
                self._scan()

    def set_symbols_dir(self, path: str):
        if path and os.path.isdir(path):
            self._symbols_dir = path
            self._dir_label.setText(path)
            if self.isVisible():
                self._scan_pending = False
                self._scan()
            else:
                self._scan_pending = True

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        title = QLabel("Bibliothèque de symboles TypeEdit")
        title.setStyleSheet(
            "font-weight: bold; font-size: 13px; color: #94e2d5;")
        layout.addWidget(title)

        # Dossier
        dir_row = QHBoxLayout()
        dir_row.setSpacing(4)
        self._dir_label = QLabel(self._symbols_dir or "(aucun dossier)")
        self._dir_label.setStyleSheet(
            "color: #a6adc8; font-size: 10px;")
        self._dir_label.setWordWrap(True)
        dir_row.addWidget(self._dir_label, stretch=1)
        browse_btn = QPushButton("📂")
        browse_btn.setFixedWidth(32)
        browse_btn.setToolTip("Choisir le dossier des symboles")
        browse_btn.clicked.connect(self._on_browse_dir)
        dir_row.addWidget(browse_btn)
        refresh_btn = QPushButton("⟳")
        refresh_btn.setFixedWidth(32)
        refresh_btn.setToolTip("Rescanner le dossier")
        refresh_btn.clicked.connect(self._scan)
        dir_row.addWidget(refresh_btn)
        layout.addLayout(dir_row)

        # Recherche
        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍 Rechercher...")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._apply_filter)
        layout.addWidget(self._search)

        # Arborescence des dossiers (rangement = structure disque)
        self._folder_tree = QTreeWidget()
        self._folder_tree.setHeaderHidden(True)
        self._folder_tree.setMaximumHeight(150)
        self._folder_tree.setStyleSheet(
            "QTreeWidget { background: #181825; border: 1px solid "
            "#313244; border-radius: 4px; font-size: 11px; "
            "color: #cdd6f4; }"
            "QTreeWidget::item:selected { background: #313244; "
            "color: #89b4fa; }")
        self._folder_tree.currentItemChanged.connect(self._apply_filter)
        layout.addWidget(self._folder_tree)

        # Grille de vignettes
        self._grid = QListWidget()
        self._grid.setViewMode(QListView.ViewMode.IconMode)
        self._grid.setIconSize(QSize(80, 80))
        self._grid.setGridSize(QSize(104, 116))
        self._grid.setResizeMode(QListView.ResizeMode.Adjust)
        self._grid.setWordWrap(True)
        self._grid.setStyleSheet(
            "QListWidget { background: #181825; border: 1px solid "
            "#313244; border-radius: 4px; font-size: 10px; }"
            "QListWidget::item { color: #cdd6f4; }"
            "QListWidget::item:selected { background: #313244; "
            "border: 1px solid #89b4fa; border-radius: 4px; }")
        self._grid.currentItemChanged.connect(self._on_item_selected)
        self._grid.itemDoubleClicked.connect(self._on_open_symbol)
        layout.addWidget(self._grid, stretch=1)

        self._count_label = QLabel("0 symbole(s)")
        self._count_label.setStyleSheet(
            "color: #6c7086; font-size: 10px;")
        layout.addWidget(self._count_label)

        # Aperçu agrandi (upscale préservant les bords)
        self._preview = QLabel()
        self._preview.setFixedHeight(300)
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setStyleSheet(
            "background: #181825; border: 1px solid #313244; "
            "border-radius: 4px;")
        layout.addWidget(self._preview)

        # Actions
        actions_row = QHBoxLayout()
        actions_row.setSpacing(4)
        to_canvas_btn = QPushButton("→ Canvas DXF")
        to_canvas_btn.setToolTip(
            "Importe le symbole sélectionné sur le canvas DXF en "
            "vectoriel (calque SMB, centres détectés pour GenOps)")
        to_canvas_btn.setStyleSheet(
            "QPushButton { color: #1e1e2e; background: #94e2d5; "
            "font-weight: bold; padding: 4px 10px; border-radius: 4px; }"
            "QPushButton:hover { background: #b5ede2; }")
        to_canvas_btn.clicked.connect(self._on_to_canvas)
        actions_row.addWidget(to_canvas_btn)
        hint = QLabel("Double-clic: ouvrir dans TypeEdit")
        hint.setStyleSheet(
            "color: #6c7086; font-size: 9px; font-style: italic;")
        actions_row.addWidget(hint, stretch=1)
        layout.addLayout(actions_row)

    # ── Scan / filtre ──

    def _on_browse_dir(self):
        path = QFileDialog.getExistingDirectory(
            self, "Dossier des symboles TypeEdit",
            self._symbols_dir or "")
        if path:
            self._symbols_dir = path
            self._dir_label.setText(path)
            self.symbols_dir_changed.emit(path)
            self._scan()

    def _scan(self):
        """Scanne récursivement le dossier pour les .smb."""
        self._all_files = []
        folders = set()
        if self._symbols_dir and os.path.isdir(self._symbols_dir):
            for root, _dirs, files in os.walk(self._symbols_dir):
                for f in files:
                    if f.lower().endswith('.smb'):
                        fp = os.path.join(root, f)
                        self._all_files.append(fp)
                        rel = os.path.relpath(root, self._symbols_dir)
                        folders.add("" if rel == "." else rel)
        self._all_files.sort(key=lambda p: os.path.basename(p).lower())

        # Arborescence des sous-dossiers (structure disque)
        self._folder_tree.blockSignals(True)
        current_item = self._folder_tree.currentItem()
        current_path = (current_item.data(0, Qt.ItemDataRole.UserRole)
                        if current_item else "")
        self._folder_tree.clear()
        root = QTreeWidgetItem(["📁 Tous les symboles"])
        root.setData(0, Qt.ItemDataRole.UserRole, "")
        self._folder_tree.addTopLevelItem(root)
        nodes = {"": root}
        for folder in sorted(f for f in folders if f):
            parts = folder.split(os.sep)
            for depth in range(len(parts)):
                rel = os.sep.join(parts[:depth + 1])
                if rel in nodes:
                    continue
                parent = nodes[os.sep.join(parts[:depth])] \
                    if depth else root
                node = QTreeWidgetItem([f"📁 {parts[depth]}"])
                node.setData(0, Qt.ItemDataRole.UserRole, rel)
                parent.addChild(node)
                nodes[rel] = node
        root.setExpanded(True)
        # Restaurer la sélection précédente si possible
        sel = nodes.get(current_path, root)
        self._folder_tree.setCurrentItem(sel)
        self._folder_tree.blockSignals(False)

        self._apply_filter()

    def _apply_filter(self, *args):
        """Reconstruit la grille selon recherche + dossier sélectionné."""
        text = self._search.text().lower().strip()
        item = self._folder_tree.currentItem()
        folder = (item.data(0, Qt.ItemDataRole.UserRole)
                  if item else "") or ""
        self._grid.clear()
        self._items_by_fp = {}
        self._vector_queue = []
        shown = 0
        for fp in self._all_files:
            name = os.path.splitext(os.path.basename(fp))[0]
            if text and text not in name.lower():
                continue
            if folder:
                rel = os.path.relpath(os.path.dirname(fp),
                                      self._symbols_dir)
                if rel != folder and not rel.startswith(
                        folder + os.sep):
                    continue
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, fp)
            # Vignette vectorielle si déjà rendue, sinon bitmap
            # (le rendu vectoriel arrive progressivement via le timer)
            # AUCUN décodage synchrone ici: sur une bibliothèque de
            # plusieurs milliers de symboles, extraire les vignettes
            # en boucle gelait l'interface. On n'utilise que le cache
            # et on confie le reste à la file progressive (timer).
            vec_icon = self._vector_cache.get(fp)
            if vec_icon is not None:
                item.setIcon(vec_icon)
            else:
                icon = self._icon_cache.get(fp)
                if icon is not None and not icon.isNull():
                    item.setIcon(icon)
                if fp not in self._vector_cache:
                    self._vector_queue.append(fp)
            item.setToolTip(fp)
            self._grid.addItem(item)
            self._items_by_fp[fp] = item
            shown += 1
        self._count_label.setText(
            f"{shown}/{len(self._all_files)} symbole(s)")
        if self._vector_queue:
            self._vector_timer.start()

    def _process_vector_batch(self):
        """Rend quelques vignettes vectorielles par tick (non bloquant)."""
        from src.integrations.smb_vector import render_smb_vector
        done = 0
        while self._vector_queue and done < 6:
            fp = self._vector_queue.pop(0)
            if fp in self._vector_cache:
                continue
            try:
                pm = render_smb_vector(fp, 96)
            except Exception:
                pm = None
            if pm is None:
                # Repli vignette bitmap (décodée ici, hors du filtre)
                bmp = self._icon_cache.get(fp)
                if bmp is None:
                    thumb = extract_smb_thumbnail(fp)
                    bmp = QIcon(thumb) if thumb is not None else QIcon()
                    self._icon_cache[fp] = bmp
                self._vector_cache[fp] = bmp if not bmp.isNull() else None
            else:
                self._vector_cache[fp] = QIcon(pm)
            icon = self._vector_cache[fp]
            if icon is not None:
                item = self._items_by_fp.get(fp)
                if item is not None:
                    try:
                        item.setIcon(icon)
                    except RuntimeError:
                        pass  # item détruit (refiltre)
            done += 1
        if not self._vector_queue:
            self._vector_timer.stop()

    # ── Sélection / ouverture ──

    def _on_item_selected(self, current, previous):
        if current is None:
            self._preview.clear()
            return
        fp = current.data(Qt.ItemDataRole.UserRole)
        # Aperçu VECTORIEL (décodage des courbes du .smb) —
        # fallback sur la vignette bitmap si le décodage échoue
        try:
            from src.integrations.smb_vector import render_smb_vector
            vec_pm = render_smb_vector(fp, 290)
        except Exception:
            vec_pm = None
        if vec_pm is not None:
            self._preview.setPixmap(vec_pm)
            return
        pm = extract_smb_thumbnail(fp)
        if pm is not None:
            self._preview.setPixmap(upscale_lineart(pm, 290, 290))
        else:
            self._preview.setText("(pas de vignette)")

    def _on_to_canvas(self):
        """Envoie le symbole sélectionné vers le canvas DXF."""
        item = self._grid.currentItem()
        if item is None:
            return
        fp = item.data(Qt.ItemDataRole.UserRole)
        if fp and os.path.exists(fp):
            self.symbol_to_canvas.emit(fp)

    def _on_open_symbol(self, item):
        """Double-clic: ouvre le .smb avec l'application associée
        (TypeEdit)."""
        fp = item.data(Qt.ItemDataRole.UserRole)
        if fp and os.path.exists(fp):
            try:
                os.startfile(fp)
            except OSError:
                pass
