"""
Panneau overlay (col2) de génération d'opérations depuis les centres DXF.
- Filtre par circularité (0-100%) via slider
- Tableau des centres filtrés
- Choix opération, ébavurage, parcours optimisé
- Boutons Rafraîchir / Effacer / Générer / Fermer
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QCheckBox, QSlider, QTableWidgetItem, QHeaderView, QGroupBox, QFrame,
    QAbstractItemView, QScrollArea, QFileDialog
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from typing import List, Dict

from src.gui.panels.operations_panel import CyclingTableWidget
from src.gui.widgets import SpinCote

from src.core.circle_detection import (
    filter_by_circularity,
    compute_ebav_depth,
    optimize_path_from_origin,
    deduplicate_circles,
    detect_collisions
)


class _Spin(SpinCote):
    """Cote du panneau: 12 s'écrit 12, et l'entrée prend tout."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMaximumHeight(26)


class CircleOpsPanel(QWidget):
    """Panneau overlay pour créer des opérations à partir de centres détectés."""

    operations_generated = Signal(list)
    close_requested = Signal()
    points_changed = Signal(list)    # liste de dicts {x, y, ...}
    point_selected = Signal(int)     # index du point sélectionné
    add_points_to_op = Signal(list)  # points isolés à ajouter à l'opération active
    #: import / export / clear du DESSIN (exécutés par le panneau DXF)
    dxf_action = Signal(str)

    #: le bouton « Retirer au clic » a changé d'état
    retrait_bascule = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._all_circles: List[Dict] = []
        self._filtered_circles: List[Dict] = []
        self._setup_ui()

    def _setup_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── Header ──
        header = QHBoxLayout()
        header.setContentsMargins(8, 6, 8, 6)

        title = QLabel("Générer des opérations depuis DXF")
        title.setStyleSheet(
            "font-weight: bold; font-size: 14px; color: #89b4fa;")
        header.addWidget(title)
        header.addStretch()

        # (Importer / Exporter / Effacer le dessin sont dans la
        # barre du bas du canvas: pas deux fois.)
        self._refresh_btn = QPushButton("Rafraîchir")
        self._refresh_btn.setToolTip("Recharger les centres depuis le DXF")
        header.addWidget(self._refresh_btn)

        self._clear_btn = QPushButton("Effacer")
        self._clear_btn.setToolTip("Vider la liste")
        self._clear_btn.clicked.connect(self._on_clear)
        header.addWidget(self._clear_btn)

        outer.addLayout(header)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #45475a;")
        outer.addWidget(sep)

        # ── Scrollable content ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(8)
        layout.setContentsMargins(8, 8, 8, 8)

        # Info
        self._info_label = QLabel("Importez un DXF puis cliquez Rafraîchir")
        self._info_label.setStyleSheet(
            "color: #a6adc8; font-size: 12px;")
        layout.addWidget(self._info_label)

        # ── Filtre par circularité ──
        filter_group = QGroupBox("Précision de circularité")
        filter_layout = QVBoxLayout()
        filter_layout.setSpacing(6)

        slider_row = QHBoxLayout()
        slider_row.addWidget(QLabel("0%\nTout"))

        self.circularity_slider = QSlider(Qt.Orientation.Horizontal)
        self.circularity_slider.setRange(0, 100)
        self.circularity_slider.setValue(30)
        self.circularity_slider.setTickPosition(
            QSlider.TickPosition.TicksBelow)
        self.circularity_slider.setTickInterval(10)
        self.circularity_slider.valueChanged.connect(self._update_filter)
        slider_row.addWidget(self.circularity_slider, stretch=1)

        slider_row.addWidget(QLabel("100%\nParfait"))
        filter_layout.addLayout(slider_row)

        self._filter_label = QLabel("")
        self._filter_label.setStyleSheet(
            "color: #a6e3a1; font-size: 12px;")
        filter_layout.addWidget(self._filter_label)

        # La profondeur des points, ICI, à côté de la précision: elle
        # s'applique à tous les points du tableau (la colonne Pz reste
        # éditable point par point ensuite). Et le retrait à la
        # souris: un clic sur un marqueur du canvas ôte le point.
        ligne_pz = QHBoxLayout()
        ligne_pz.setSpacing(6)
        ligne_pz.addWidget(QLabel("Profondeur des points (Pz):"))
        self.depth_spin = _Spin()
        self.depth_spin.setRange(0.0, 200.0)
        self.depth_spin.setDecimals(2)
        self.depth_spin.setValue(3.5)   # Pz par défaut
        self.depth_spin.setMaximumWidth(72)
        self.depth_spin.setToolTip(
            "Profondeur donnée à TOUS les points du tableau, et aux "
            "opérations générées. La colonne Pz du tableau reste "
            "modifiable point par point.")
        self.depth_spin.valueChanged.connect(self._on_profondeur_changee)
        ligne_pz.addWidget(self.depth_spin)
        ligne_pz.addWidget(QLabel("mm"))
        ligne_pz.addStretch()
        self._retrait_btn = QPushButton("🖱 Retirer au clic")
        self._retrait_btn.setCheckable(True)
        self._retrait_btn.setToolTip(
            "Enclenché: un clic sur un marqueur du canvas RETIRE ce "
            "point de la liste (les indésirables s'ôtent à la "
            "souris). Déclenché: le clic sélectionne la ligne.")
        self._retrait_btn.setStyleSheet(
            "QPushButton:checked { background: #f38ba8; color: #1e1e2e; "
            "font-weight: bold; }")
        self._retrait_btn.toggled.connect(self.retrait_bascule.emit)
        ligne_pz.addWidget(self._retrait_btn)
        filter_layout.addLayout(ligne_pz)

        filter_group.setLayout(filter_layout)
        layout.addWidget(filter_group)

        # ── Tableau ──
        self.table = CyclingTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ["#", "X", "Y", "Pz", "Ø", "Type", "Score"])
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        # Colonnes Pz et Ø éditables — Tab/Enter + chiffres
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.AnyKeyPressed)
        self.table.setMinimumHeight(100)
        self.table.currentCellChanged.connect(
            lambda row, col, prev_row, prev_col:
            self.point_selected.emit(row))
        # Sélection multiple pour export/suppression
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        # Score sortable on header click
        self.table.setSortingEnabled(False)  # Manual control
        self._score_sort_order = Qt.SortOrder.DescendingOrder
        self.table.horizontalHeader().sectionClicked.connect(
            self._on_header_clicked)
        # Persister les Pz/Ø édités dans les dicts de centres
        # (sinon perdus à chaque reconstruction du tableau)
        self.table.itemChanged.connect(self._on_table_item_changed)
        layout.addWidget(self.table, stretch=1)

        # ── Boutons points ──
        pts_btn_row = QHBoxLayout()
        pts_btn_row.setSpacing(4)

        add_sel_btn = QPushButton("→ Ajouter à l'opé active")
        add_sel_btn.setToolTip(
            "Envoie les points sélectionnés dans le tableau de l'opération "
            "courante (colonne 1). Sélectionnez d'abord une opération "
            "multi-point (Perçage, Taraudage).")
        add_sel_btn.setStyleSheet(
            "QPushButton { color: #1e1e2e; background: #a6e3a1; "
            "font-weight: bold; padding: 4px 10px; border-radius: 4px; }"
            "QPushButton:hover { background: #94d390; }")
        add_sel_btn.clicked.connect(self._on_add_selected_to_op)
        pts_btn_row.addWidget(add_sel_btn)

        del_pt_btn = QPushButton("× Supprimer")
        del_pt_btn.setToolTip("Supprimer les points sélectionnés")
        del_pt_btn.setStyleSheet("color: #f38ba8;")
        del_pt_btn.clicked.connect(self._on_delete_points)
        pts_btn_row.addWidget(del_pt_btn)

        sel_all_btn = QPushButton("Tout ✓")
        sel_all_btn.setToolTip("Sélectionner tous les points")
        sel_all_btn.clicked.connect(self.table.selectAll)
        pts_btn_row.addWidget(sel_all_btn)

        csv_export_btn = QPushButton("CSV ↓")
        csv_export_btn.setToolTip("Exporter les points filtrés en CSV")
        csv_export_btn.clicked.connect(self._on_export_csv)
        pts_btn_row.addWidget(csv_export_btn)

        pts_btn_row.addStretch()
        layout.addLayout(pts_btn_row)

        # ── Attributs internes (pas de UI pour la section opération) ──
        # Les opérations sont configurées dans Col1 (operations_panel)
        self.op_type_combo = QComboBox()
        self.op_type_combo.addItem(
            "Perçage Fraise (DrillMilling)", "percage_fraise")
        self.op_type_combo.addItem("Taraudage (Thread)", "taraudage")
        self.op_type_combo.addItem("Perçage Foret (Drill)", "percage_foret")
        self.op_type_combo.addItem("BPM", "bpm")
        self.op_type_combo.setVisible(False)

        self.thread_combo = QComboBox()
        self.thread_combo.addItems(
            ["M2.5", "M3", "M4", "M5", "M6", "M8", "M10"])
        self.thread_combo.setCurrentText("M4")
        self.thread_label = QLabel()
        self.thread_combo.setVisible(False)
        self.thread_label.setVisible(False)

        self.ebav_cb = QCheckBox()
        self.ebav_cb.setChecked(True)
        self.ebav_cb.setVisible(False)

        self.ebav_offset_spin = _Spin()
        self.ebav_offset_spin.setValue(0.05)
        self.ebav_offset_spin.setVisible(False)

        self.path_cb = QCheckBox()
        self.path_cb.setChecked(True)
        self.path_cb.setVisible(False)

        # ── Résumé ──
        self._summary = QLabel("")
        self._summary.setStyleSheet(
            "color: #cdd6f4; font-weight: bold; font-size: 12px;")
        layout.addWidget(self._summary)

        # ── Bouton Générer: un menu demande la famille ──
        gen_btn = QPushButton("Générer les opérations…")
        gen_btn.setObjectName("primary")
        gen_btn.setMinimumHeight(36)
        gen_btn.setStyleSheet(
            "QPushButton { background: #89b4fa; color: #1e1e2e; "
            "font-weight: bold; font-size: 14px; border-radius: 6px; "
            "padding: 8px; }"
            "QPushButton:hover { background: #b4d0fb; }")
        gen_btn.clicked.connect(self._menu_generer)
        self._gen_btn = gen_btn
        layout.addWidget(gen_btn)

        layout.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll, stretch=1)

        self._on_op_type_changed(0)

    @property
    def refresh_btn(self):
        return self._refresh_btn

    def load_circles(self, circles: List[Dict]):
        """Charge une nouvelle liste de centres."""
        self._all_circles = circles
        self._info_label.setText(
            f"{len(circles)} entité(s) détectée(s)")
        self._update_filter()

    #: un trou TRAVERSANT descend plus bas que la pièce: la pointe
    #: d'un foret à 118° (0,3 × Ø) plus une marge, sinon il ne débouche
    #: pas à son plein diamètre
    POINTE_FORET = 0.3
    MARGE_DEBOUCHAGE = 0.2

    @classmethod
    def pz_step(cls, c: Dict):
        """La profondeur d'un trou STEP depuis le DESSUS de la pièce (Z0
        du programme): là où il commence, plus sa profondeur, plus le
        débouchage s'il traverse. None si le point ne vient pas d'un
        STEP."""
        if c.get('entity_type') != 'STEP' or c.get('profondeur') is None:
            return None
        pz = float(c.get('pz_depart') or 0.0) + float(c['profondeur'])
        if c.get('traversant'):
            pz += (cls.POINTE_FORET * 2 * float(c.get('radius') or 0.0)
                   + cls.MARGE_DEBOUCHAGE)
        return round(pz, 3)

    def _on_profondeur_changee(self, valeur: float):
        """La profondeur vaut pour TOUS les points: les Pz réglés un
        par un sont remis à celle-ci — sauf les trous d'un STEP, qui
        portent la leur (le fichier la dit)."""
        for c in self._all_circles:
            c.pop('user_pz', None)
        if self._filtered_circles:
            self._rebuild_table()
            self._update_summary()

    def retrait_a_la_souris(self) -> bool:
        """Le clic sur un marqueur du canvas retire-t-il le point ?"""
        return bool(self._retrait_btn.isChecked())

    def retirer_point(self, index: int) -> bool:
        """Ôte le point `index` (rang du tableau) de la liste — celui
        que la souris a cliqué au canvas."""
        if not (0 <= index < len(self._filtered_circles)):
            return False
        retire = self._filtered_circles[index]
        if retire in self._all_circles:
            self._all_circles.remove(retire)
        self._update_filter()
        self._filter_label.setText(
            f"{self._filter_label.text()} — point {index + 1} retiré "
            f"(X{retire['x']:g} Y{retire['y']:g})")
        return True

    def _on_delete_points(self):
        """Supprime les points sélectionnés du tableau."""
        rows = sorted(set(item.row() for item in self.table.selectedItems()),
                      reverse=True)
        if not rows:
            return
        for row in rows:
            if 0 <= row < len(self._filtered_circles):
                removed = self._filtered_circles.pop(row)
                # Aussi retirer de _all_circles
                if removed in self._all_circles:
                    self._all_circles.remove(removed)
        # Reconstruire le tableau
        self._update_filter()

    def _on_clear(self):
        self._all_circles.clear()
        self._filtered_circles.clear()
        self.table.setRowCount(0)
        self._info_label.setText("Liste vidée")
        self._summary.setText("")
        self._filter_label.setText("")
        self.points_changed.emit([])

    def _update_filter(self, *args):
        threshold = self.circularity_slider.value()
        filtered = filter_by_circularity(
            self._all_circles, threshold)

        # Déduplication automatique (tolérance 0.01 mm)
        before_dedup = len(filtered)
        filtered = deduplicate_circles(filtered, tolerance=0.01)
        n_dedup = before_dedup - len(filtered)

        if self.path_cb.isChecked() and filtered:
            ordered, total_dist = optimize_path_from_origin(filtered)
            filtered = ordered

        self._filtered_circles = filtered

        # Détection de collisions (distance < 1.0 mm par défaut)
        collisions = detect_collisions(self._filtered_circles, min_distance=1.0)
        self._collision_pairs = collisions

        info_parts = [f"{len(self._filtered_circles)} centre(s) à "
                      f"≥{threshold}% de circularité"]
        if n_dedup > 0:
            info_parts.append(f"({n_dedup} doublon(s) supprimé(s))")
        if collisions:
            info_parts.append(
                f"⚠ {len(collisions)} collision(s) < 1mm")
        self._filter_label.setText(" ".join(info_parts))

        self._rebuild_table()

        self._update_summary()
        # Émettre les points pour le canvas (T12)
        pts = [{'x': c['x'], 'y': c['y'],
                'label': c.get('entity_type', '')}
               for c in self._filtered_circles]
        self.points_changed.emit(pts)

    def _rebuild_table(self):
        """Reconstruit le tableau depuis _filtered_circles.
        Les Pz/Ø édités (user_pz/user_dia dans les dicts) sont préservés."""
        self.table.blockSignals(True)
        self.table.setRowCount(len(self._filtered_circles))
        default_depth = self.depth_spin.value()
        for i, c in enumerate(self._filtered_circles):
            # # (non-éditable)
            idx_item = QTableWidgetItem(str(i + 1))
            idx_item.setFlags(idx_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(i, 0, idx_item)
            # X (non-éditable)
            x_item = QTableWidgetItem(f"{c['x']:.3f}")
            x_item.setFlags(x_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(i, 1, x_item)
            # Y (non-éditable)
            y_item = QTableWidgetItem(f"{c['y']:.3f}")
            y_item.setFlags(y_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(i, 2, y_item)
            # Pz (éditable) - profondeur individuelle; un trou STEP
            # arrive avec la sienne
            pz_fichier = self.pz_step(c)
            pz = c.get('user_pz', pz_fichier if pz_fichier is not None
                       else default_depth)
            pz_item = QTableWidgetItem(f"{pz:.2f}")
            if pz_fichier is not None:
                detail = (f"Depuis le STEP: entrée à Pz "
                          f"{float(c.get('pz_depart') or 0):g}, "
                          f"{float(c['profondeur']):g} mm de trou")
                if c.get('traversant'):
                    detail += (" — traversant: + pointe du foret "
                               f"({self.POINTE_FORET:g} × Ø) + "
                               f"{self.MARGE_DEBOUCHAGE:g} mm pour "
                               "déboucher")
                if c.get('fraisure'):
                    detail += f"; fraisure Ø{float(c['fraisure']):g}"
                pz_item.setToolTip(detail)
            self.table.setItem(i, 3, pz_item)
            # Ø (éditable) - diamètre individuel
            dia = c.get('user_dia', c.get('radius', 2) * 2)
            dia_item = QTableWidgetItem(f"{dia:.3f}")
            self.table.setItem(i, 4, dia_item)
            # Type (non-éditable)
            type_item = QTableWidgetItem(c.get('entity_type', '?'))
            type_item.setFlags(
                type_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(i, 5, type_item)
            # Score (non-éditable, coloré)
            score = c.get('circularity', 0) * 100
            score_item = QTableWidgetItem(f"{score:.0f}%")
            score_item.setFlags(
                score_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if score >= 90:
                score_item.setForeground(QColor("#a6e3a1"))
            elif score >= 50:
                score_item.setForeground(QColor("#f9e2af"))
            else:
                score_item.setForeground(QColor("#f38ba8"))
            self.table.setItem(i, 6, score_item)

        # Marquer les lignes en collision (fond orange subtil)
        collision_rows = set()
        for a, b, d in getattr(self, '_collision_pairs', []):
            collision_rows.add(a)
            collision_rows.add(b)
        for row in collision_rows:
            for col in range(7):
                item = self.table.item(row, col)
                if item:
                    item.setBackground(QColor("#3d2e1a"))  # fond sombre orange

        self.table.blockSignals(False)

    def _on_table_item_changed(self, item):
        """Persiste les Pz/Ø édités dans le dict du centre correspondant."""
        row, col = item.row(), item.column()
        if not (0 <= row < len(self._filtered_circles)):
            return
        if col not in (3, 4):
            return
        try:
            val = float(item.text().replace(',', '.'))
        except ValueError:
            return
        key = 'user_pz' if col == 3 else 'user_dia'
        self._filtered_circles[row][key] = val

    def _on_header_clicked(self, col: int):
        """Tri par la colonne Score (col 6): trie la LISTE puis reconstruit.
        (Trier seulement le QTableWidget désynchroniserait le tableau de
        _filtered_circles → mauvais Pz/Ø associés aux points.)"""
        if col == 6:
            reverse = (self._score_sort_order
                       == Qt.SortOrder.DescendingOrder)
            self._filtered_circles.sort(
                key=lambda c: c.get('circularity', 0), reverse=reverse)
            if reverse:
                self._score_sort_order = Qt.SortOrder.AscendingOrder
            else:
                self._score_sort_order = Qt.SortOrder.DescendingOrder
            self._rebuild_table()
            pts = [{'x': c['x'], 'y': c['y'],
                    'label': c.get('entity_type', '')}
                   for c in self._filtered_circles]
            self.points_changed.emit(pts)

    def _on_op_type_changed(self, index: int):
        is_thread = self.op_type_combo.currentData() == "taraudage"
        self.thread_label.setVisible(is_thread)
        self.thread_combo.setVisible(is_thread)
        self._update_summary()

    def _update_summary(self):
        n = len(self._filtered_circles)
        if n == 0:
            self._summary.setText("Aucun centre à traiter")
            return
        op_name = self.op_type_combo.currentText().split(" (")[0]
        summary = f"→ 1 op {op_name} × {n} points"
        if self.ebav_cb.isChecked():
            summary += f" + 1 ébav × {n} pts"
        self._summary.setText(summary)

    #: les familles proposées par « Générer » aux points détectés
    FAMILLES = (
        ("percage_foret", "Perçage foret"),
        ("percage_fraise", "Perçage fraise"),
        ("taraudage", "Taraudage"),
        ("filetage_special", "Filetage spécial (SpecialThread)"),
        ("poche_cercle", "Poche cercle"),
        ("ebavurage_points", "Ébavurage (chanfrein aux points)"),
    )

    #: les familles proposées aux RECTANGLES du canvas
    FAMILLES_RECT = (
        ("poche_rectangle", "Poche rectangle"),
        ("decoupe_rectangle", "Découpe rectangle"),
        ("surfacage_rectangle", "Surfaçage rectangle"),
        ("ebavurage_rect", "Ébavurage extrad (offset XY)"),
    )

    #: les familles proposées aux CONTOURS fermés sélectionnés
    FAMILLES_CONTOURS = (
        ("trace_interieur", "Découpe intérieure (tracé)"),
        ("trace_exterieur", "Détourage extérieur (tracé)"),
        ("trace_centre", "Suivi du contour (centre fraise)"),
        ("evidement_2d5", "Évidement (poche libre)"),
    )

    def _canvas(self):
        return getattr(getattr(self.window(), 'dxf_panel', None),
                       'canvas', None)

    def _rectangles_du_canvas(self, seulement_selection=False) -> list:
        canvas = self._canvas()
        if canvas is None:
            return []
        try:
            return canvas.detected_rectangles(seulement_selection)
        except Exception:
            return []

    def sources(self) -> dict:
        """Ce que « Générer » usinera: les entités SÉLECTIONNÉES au
        canvas s'il y en a (leurs centres de cercles, leurs rectangles,
        leurs contours fermés), sinon tout ce qui est détecté."""
        canvas = self._canvas()
        selection = []
        if canvas is not None:
            try:
                selection = canvas.selection_courante()
            except Exception:
                selection = []
        if selection:
            # les cercles de la sélection (la même source que le bouton
            # des formulaires: `selection_courante`, groupes compris)
            centres = []
            try:
                centres = [{'x': c['x'], 'y': c['y'],
                            'radius': c['diameter'] / 2.0,
                            'circularity': 1.0}
                           for c in canvas.centres_de_la_selection()
                           if c.get('diameter', 0) > 0]
            except Exception:
                centres = []
            try:
                contours = [c for c in canvas.selected_polylines()
                            if len(c) >= 3]
            except Exception:
                contours = []
            return {'selection': True, 'points': centres,
                    'rects': self._rectangles_du_canvas(True),
                    'contours': contours}
        return {'selection': False, 'points': list(self._filtered_circles),
                'rects': self._rectangles_du_canvas(), 'contours': []}

    def _rayon_outil_defaut(self, op_type: str) -> float:
        """Le rayon de la fraise que l'opé recevra (l'outil par défaut
        de sa famille), sinon le rayon de coin par défaut de l'opé."""
        win = self.window()
        lib = getattr(win, 'tool_library', None)
        params = getattr(win, 'params_panel', None)
        try:
            art = params.get_default_tool_article(op_type) if params else ''
            outil = lib.get_tool_by_article(art) if lib and art else None
            if outil is not None and outil.diameter:
                return float(outil.diameter) / 2.0
        except Exception:
            pass
        try:
            from src.operations.registry import OperationRegistry
            return float(OperationRegistry.get(op_type).get_default_params()
                         .get('corner_radius') or 0.0)
        except Exception:
            return 0.0

    def champs_famille(self, quoi: str, op_type: str, rects=None):
        """(titre, champs, explication) du mini-formulaire d'une
        famille (`rects`: les rectangles visés — un sans rayon de coin
        fait demander le rayon des coins vifs)."""
        from src.gui.dialogs.mini_formulaire import champs_communs
        from src.operations import depuis_selection as ds
        libelles = dict(self.FAMILLES + self.FAMILLES_RECT
                        + self.FAMILLES_CONTOURS)
        nom = libelles.get(op_type, op_type).split(" (")[0]
        prof = ('depth', "Profondeur", 'nombre', self.depth_spin.value(),
                {'min': 0.0, 'max': 200.0, 'unite': "mm"})
        champs = []
        if quoi == 'points':
            if op_type == "ebavurage_points":
                champs = [('depth', "Profondeur du chanfrein", 'nombre', 0.3,
                           {'min': 0.0, 'max': 10.0, 'unite': "mm"}),
                          ('offset', "Offset (au-delà du trou)", 'nombre',
                           self.ebav_offset_spin.value(),
                           {'min': 0.0, 'max': 10.0, 'unite': "mm"})]
            else:
                # les mêmes champs que le bouton des formulaires: le
                # filet ET son avant-trou, la passe Z…
                champs = ds.champs_points(op_type, {
                    'depth': self.depth_spin.value(),
                    'thread_name': self.thread_combo.currentText(),
                    'use_ebav': self.ebav_cb.isChecked()})
        elif quoi == 'rects':
            if op_type == "ebavurage_rect":
                champs = [('offset', "Offset XY (bord → centre outil)",
                           'nombre', 1.25,
                           {'min': 0.0, 'max': 50.0, 'unite': "mm"})]
            else:
                champs = ds.champs_rectangles(
                    op_type, {'depth': self.depth_spin.value()})
                coins = ds.champ_coins_vifs(
                    op_type, rects or [], self._rayon_outil_defaut(op_type))
                if coins is not None:
                    champs.append(coins)
        else:
            champs = [prof,
                      ('infeed_z', "Passe Z", 'nombre', 1.0,
                       {'min': 0.01, 'max': 50.0, 'unite': "mm"})]
            if op_type != "evidement_2d5":
                champs.append(('surepaisseur_xy', "Matière laissée en XY",
                               'nombre', 0.0,
                               {'min': 0.0, 'max': 50.0, 'unite': "mm"}))
        champs += champs_communs(nom)
        return (nom, champs,
                "Les réglages de cette génération — chaque opération reste "
                "modifiable ensuite dans son formulaire.")

    def _menu_generer(self):
        """Demande la famille — aux points, aux rectangles, aux contours
        de la SÉLECTION du canvas (sinon à tout ce qui est détecté) —,
        puis son mini-formulaire, puis génère."""
        from PySide6.QtWidgets import QMenu
        src = self.sources()
        if not (src['points'] or src['rects'] or src['contours']):
            self._summary.setText(
                "Rien à usiner: sélectionnez des entités au canvas, ou "
                "importez un DXF et rafraîchissez")
            return
        menu = QMenu(self)
        menu.setStyleSheet("QMenu { font-size: 13px; padding: 6px; }"
                           "QMenu::item { padding: 7px 24px; }")
        actions = {}
        dou = " sélectionné(s)" if src['selection'] else ""
        for quoi, familles, n, mot in (
                ('points', self.FAMILLES, len(src['points']), "point(s)"),
                ('rects', self.FAMILLES_RECT, len(src['rects']),
                 "rectangle(s)"),
                ('contours', self.FAMILLES_CONTOURS, len(src['contours']),
                 "contour(s) fermé(s)")):
            if not n:
                continue
            if actions:
                menu.addSeparator()
            titre = menu.addAction(f"— {n} {mot}{dou} —")
            titre.setEnabled(False)
            for op_type, libelle in familles:
                actions[menu.addAction(libelle)] = (quoi, op_type)
        choisi = menu.exec(self._gen_btn.mapToGlobal(
            self._gen_btn.rect().bottomLeft()))
        run = actions.get(choisi)
        if run is None:
            return
        quoi, op_type = run
        from src.gui.dialogs.mini_formulaire import MiniFormulaire
        titre, champs, explication = self.champs_famille(
            quoi, op_type, src['rects'] if quoi == 'rects' else None)
        formulaire = MiniFormulaire(titre, champs, self, explication)
        valeurs = formulaire.demander()
        # une fenêtre par génération restait en mémoire
        formulaire.deleteLater()
        if valeurs is None:
            return
        self.generer(quoi, op_type, valeurs, src)

    def generer(self, quoi: str, op_type: str, valeurs: dict,
                src: dict = None) -> list:
        """Génère la famille avec les valeurs du mini-formulaire; rend
        les opérations émises."""
        src = src or self.sources()
        if quoi == 'points':
            cercles = None if not src.get('selection') else src['points']
            return self._on_generate(op_type, valeurs, cercles) or []
        if quoi == 'rects':
            return self._generer_depuis_rectangles(op_type, src['rects'],
                                                   valeurs) or []
        return self._generer_depuis_contours(op_type, src['contours'],
                                             valeurs) or []

    @staticmethod
    def _grouper(ops: list, valeurs: dict) -> list:
        """Les opérations générées, en un ensemble de la liste (si on
        le demande et qu'il y en a plusieurs)."""
        from src.operations import depuis_selection as ds
        return ds.grouper(ops, valeurs)

    def _generer_depuis_contours(self, op_type: str, contours: list,
                                 valeurs: dict) -> list:
        """Les contours fermés sélectionnés: un tracé par contour (son
        côté d'outil, sa matière laissée), ou un évidement de tous."""
        from src.operations.trace import Trace
        if not contours:
            return []
        prof = float(valeurs.get('depth', self.depth_spin.value()))
        passe = float(valeurs.get('infeed_z', 1.0)) or prof
        ops = []
        if op_type == "evidement_2d5":
            ops.append({'operation_type': 'evidement_2d5',
                        'name': f"Évidement ({len(contours)} contour(s))",
                        'x': 0.0, 'y': 0.0, 'points': [],
                        'params': {'contours': [[[round(x, 4), round(y, 4)]
                                                 for x, y in c]
                                                for c in contours],
                                   'profondeur': prof,
                                   'profondeur_passe': passe,
                                   'mode': 'Creux'}})
        else:
            cote = {"trace_interieur": Trace.COTES[1],
                    "trace_exterieur": Trace.COTES[2]}.get(op_type,
                                                          Trace.COTES[0])
            nom = dict(self.FAMILLES_CONTOURS).get(op_type, "Tracé")
            nom = nom.split(" (")[0]
            for k, c in enumerate(contours):
                pts = [[round(x, 4), round(y, 4)] for x, y in c]
                ops.append({'operation_type': 'trace',
                            'name': f"{nom} {k + 1}",
                            'x': 0.0, 'y': 0.0, 'points': [],
                            'params': {'shape': 'Dessin', 'closed': True,
                                       'path_points': pts,
                                       'cote_outil': cote,
                                       'surepaisseur_xy': float(
                                           valeurs.get('surepaisseur_xy',
                                                       0.0)),
                                       'depth': prof, 'infeed_z': passe}})
        ops = self._grouper(ops, valeurs)
        self.operations_generated.emit(ops)
        self._summary.setText(
            f"{len(ops)} opération(s) générée(s) depuis les contours")
        return ops

    def _generer_depuis_rectangles(self, op_type: str, rects: list,
                                   valeurs: dict = None):
        """Une opération par rectangle du canvas. L'ébavurage extrad
        demande l'offset XY (au mini-formulaire, sinon ici)."""
        from PySide6.QtWidgets import QInputDialog
        offset = 0.0
        forme = op_type
        decal = float((valeurs or {}).get('offset', 0.0) or 0.0)
        if op_type == "ebavurage_rect":
            forme = "ebavurage"
            if valeurs is not None:
                offset = decal
                decal = 0.0
            else:
                val, ok = QInputDialog.getDouble(
                    self, "Ébavurage extrad",
                    "Offset XY (distance du bord au centre de l'outil, mm):",
                    1.25, 0.0, 50.0, 2)
                if not ok:
                    return
                offset = float(val)
        ops = []
        if op_type == "poche_rectangle" and any(r.get('pz') for r in rects):
            # d'un STEP: une poche par FOND de poche — le contour du
            # dessus (Pz 0) n'en est pas une
            rects = [r for r in rects if (r.get('pz') or 0) > 0]
        prof_form = (float(valeurs['depth']) if valeurs
                     and 'depth' in valeurs else None)
        for r in rects:
            params = {'width_x': round(r['width'] + 2 * decal, 4),
                      'width_y': round(r['height'] + 2 * decal, 4)}
            # la cote du calque STEP, sinon celle du formulaire (ou du
            # panneau)
            if forme != "ebavurage":
                params['depth'] = (float(r['pz']) if r.get('pz')
                                   else prof_form if prof_form is not None
                                   else self.depth_spin.value())
            if forme == "decoupe_rectangle" and valeurs \
                    and valeurs.get('side'):
                from src.operations.depuis_selection import cote_decoupe
                params['side'] = cote_decoupe(valeurs['side'])
            rayon = r.get('rayon') or 0.0
            if forme == "ebavurage":
                params.update({'forme': "Rectangle", 'cote': "Extérieur",
                               'offset': offset, 'corner_radius': rayon})
                nom = "Ébavurage"
            else:
                # un coin vif: le rayon choisi au formulaire (0 sinon,
                # comme avant)
                from src.operations.depuis_selection import rayon_de_coin
                params['corner_radius'] = rayon_de_coin(r, valeurs, rayon)
                nom = dict(self.FAMILLES_RECT).get(op_type, op_type)
                nom = nom.split(" (")[0]
            ops.append({
                'operation_type': forme,
                'name': f"{nom} {r['width']:g}×{r['height']:g}",
                'x': r['x'], 'y': r['y'], 'params': params, 'points': []})
        if ops:
            ops = self._grouper(ops, valeurs)
            self.operations_generated.emit(ops)
            self._summary.setText(
                f"{len(ops)} opération(s) générée(s) depuis les "
                "rectangles")
        return ops

    def _on_generate(self, op_type=None, valeurs: dict = None,
                     cercles: list = None):
        """Les points: ceux du tableau (leurs Pz et Ø), ou `cercles` (la
        sélection du canvas). `valeurs`: le mini-formulaire."""
        if cercles is None and not self._filtered_circles:
            return
        if cercles is not None and not cercles:
            return
        if not op_type:
            op_type = self.op_type_combo.currentData()
        depth = self.depth_spin.value()
        add_ebav = self.ebav_cb.isChecked()
        ebav_offset = self.ebav_offset_spin.value()
        prof_form = None
        if valeurs:
            if 'depth' in valeurs:
                prof_form = float(valeurs['depth'])
                # une profondeur CHANGÉE au formulaire vaut pour tous
                # les points; sinon chaque ligne garde sa Pz
                if abs(prof_form - depth) < 1e-9:
                    prof_form = None
                depth = float(valeurs['depth'])
            add_ebav = bool(valeurs.get('ebav', add_ebav))
            ebav_offset = float(valeurs.get('offset', ebav_offset))

        # Générer dans l'ordre AFFICHÉ (le chemin optimisé est déjà
        # appliqué par _update_filter). Ré-optimiser ici pouvait
        # désynchroniser les lignes du tableau (Pz/Ø) des points.
        ordered = self._filtered_circles if cercles is None else cercles

        # Lire les profondeurs/diamètres individuels depuis le tableau
        points = []
        for i, c in enumerate(ordered):
            if cercles is not None:
                points.append({'x': c['x'], 'y': c['y'], 'depth': depth,
                               'diameter': round(
                                   float(c.get('radius', 2)) * 2, 4)})
                continue
            pt = {'x': c['x'], 'y': c['y']}
            # Profondeur individuelle
            pz_item = self.table.item(i, 3)
            if pz_item:
                try:
                    pt['depth'] = float(pz_item.text())
                except ValueError:
                    pt['depth'] = depth
            else:
                pt['depth'] = depth
            # Diamètre individuel
            dia_item = self.table.item(i, 4)
            if dia_item:
                try:
                    pt['diameter'] = float(dia_item.text())
                except ValueError:
                    pt['diameter'] = c.get('radius', 2) * 2
            else:
                pt['diameter'] = c.get('radius', 2) * 2
            if prof_form is not None:
                pt['depth'] = prof_form
            points.append(pt)

        ops = []

        params = {'depth': depth}
        if op_type in ("percage_fraise", "poche_cercle") and ordered:
            params['diameter'] = ordered[0].get('radius', 2) * 2
        if op_type == "percage_fraise" and points:
            # chaque trou à son Ø (ils étaient lus puis ignorés: tout
            # se perçait au Ø du premier cercle); le plus fréquent
            # devient celui de l'opé
            from collections import Counter
            comptes = Counter(round(float(pt.get('diameter') or 0), 3)
                              for pt in points
                              if float(pt.get('diameter') or 0) > 0)
            if comptes:
                params['diameter'] = comptes.most_common(1)[0][0]
            params['diametres_par_point'] = len(comptes) > 1
        elif op_type == "taraudage":
            params['thread_name'] = str(
                (valeurs or {}).get('thread_name')
                or self.thread_combo.currentText())
            # le tableau du formulaire montre le filet de CHAQUE trou
            for pt in points:
                pt['thread_type'] = params['thread_name']
        if valeurs and 'infeed_z' in valeurs:
            params['infeed_z'] = float(valeurs['infeed_z'])
        # le filet: son avant-trou d'abord (perçage fraise au Ø de
        # perçage du filet), sur les mêmes points
        if op_type == "taraudage" and valeurs:
            from src.operations import depuis_selection as ds
            avant = ds.op_avant_trou(
                valeurs, points,
                getattr(self.window(), 'tool_library', None))
            if avant is not None:
                ops.append(avant)

        libelles = dict(self.FAMILLES)
        if op_type == "filetage_special":
            # un filet par Ø de cercle: le Ø nominal est celui du dessin
            from src.operations import depuis_selection as ds
            params.update(ds.reglages_points(op_type, valeurs))
            lots = {}
            for pt in points:
                d = round(float(pt.get('diameter') or 0.0), 3)
                lots.setdefault(d, []).append(
                    {k: v for k, v in pt.items() if k != 'diameter'})
            for d, pts in sorted(lots.items(), reverse=True):
                ops.append({
                    'operation_type': op_type,
                    'name': (f"Filetage spécial Ø{d:g} ({len(pts)}pts)"
                             if d > 0 else
                             f"Filetage spécial ({len(pts)}pts)"),
                    'x': pts[0]['x'],
                    'y': pts[0]['y'],
                    'params': ({**params, 'nominal_diameter': d} if d > 0
                               else dict(params)),
                    'points': pts,
                })
            ops = self._grouper(ops, valeurs)
            self.operations_generated.emit(ops)
            self._summary.setText(f"{len(ops)} opération(s) générée(s) !")
            return ops
        if op_type == "ebavurage_points":
            # un chanfrein à chaque trou: percage_fraise peu profond
            op_type = "percage_fraise"
            op_name = "Ébavurage"
            params['depth'] = (float(valeurs['depth']) if valeurs
                               and 'depth' in valeurs else 0.3)
            add_ebav = False
        else:
            op_name = libelles.get(op_type,
                                   self.op_type_combo.currentText())
            op_name = op_name.split(" (")[0]
        ops.append({
            'operation_type': op_type,
            'name': f"{op_name} ({len(points)}pts)",
            'x': points[0]['x'] if points else 0,
            'y': points[0]['y'] if points else 0,
            'params': params,
            'points': points,
        })

        if add_ebav and ordered:
            r = ordered[0].get('radius', 2)
            ebav_params = {
                'diameter': r * 2 + ebav_offset * 2,
                'depth': compute_ebav_depth(ordered[0], ebav_offset),
            }
            ops.append({
                'operation_type': 'percage_fraise',
                'name': f"Ébav. ({len(points)}pts)",
                'x': points[0]['x'] if points else 0,
                'y': points[0]['y'] if points else 0,
                'params': ebav_params,
                'points': points,
            })

        ops = self._grouper(ops, valeurs)
        self.operations_generated.emit(ops)
        self._summary.setText(
            f"{len(ops)} opération(s) générée(s) !")
        return ops

    def _on_add_selected_to_op(self):
        """Ajoute les points sélectionnés dans le tableau vers l'op active.
        Si aucune sélection, envoie tous les points."""
        rows = sorted(set(item.row() for item in self.table.selectedItems()))
        if not rows:
            # Aucune sélection → envoyer tous les points
            rows = list(range(len(self._filtered_circles)))
        if not rows:
            return
        points = []
        for row in rows:
            if 0 <= row < len(self._filtered_circles):
                c = self._filtered_circles[row]
                pt = {'x': c['x'], 'y': c['y']}
                # Inclure la profondeur individuelle si modifiée
                pz_item = self.table.item(row, 3)
                if pz_item:
                    try:
                        pt['depth'] = float(pz_item.text())
                    except ValueError:
                        pass
                if 'depth' not in pt:
                    pt['depth'] = self.depth_spin.value()
                points.append(pt)
        if points:
            self.add_points_to_op.emit(points)
            self._summary.setText(
                f"✓ {len(points)} point(s) envoyé(s) vers l'opération")

    def _on_export_csv(self):
        """Exporte les points filtrés en CSV."""
        if not self._filtered_circles:
            return
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Exporter les points en CSV",
            "points.csv",
            "Fichiers CSV (*.csv);;Tous (*)")
        if not filepath:
            return
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write("X;Y;Diameter;Type;Score\n")
                for c in self._filtered_circles:
                    r = c.get('radius', 0)
                    score = c.get('circularity', 0) * 100
                    f.write(
                        f"{c['x']:.3f};{c['y']:.3f};"
                        f"{r*2:.3f};"
                        f"{c.get('entity_type', '')};"
                        f"{score:.0f}\n")
            self._summary.setText(
                f"Exporté: {len(self._filtered_circles)} points → CSV")
        except Exception as e:
            self._summary.setText(f"Erreur export: {e}")
