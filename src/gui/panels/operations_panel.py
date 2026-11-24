"""
Colonne 1: Panneau des opérations.
Liste des opérations avec drag-drop, ajout, suppression,
et formulaire de paramètres dynamique.

- CalcLineEdit: champs numériques classiques avec mini-calculatrice intégrée
- CyclingTableWidget: Tab cyclique, navigation flèches type tableur
- Validation uniquement sur Tab/Enter (jamais per-caractère)
"""

import copy
import os
import uuid
import re
from contextlib import contextmanager

from PySide6.QtWidgets import (
    QAbstractSpinBox, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QListWidget, QListWidgetItem, QLabel, QComboBox, QLineEdit, QCheckBox,
    QScrollArea, QGroupBox, QFormLayout, QMenu, QMessageBox, QFrame,
    QSizePolicy, QGridLayout, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QFileDialog, QStyledItemDelegate, QStyleOptionViewItem,
    QSplitter, QInputDialog, QApplication, QStyle
)
from PySide6.QtCore import Qt, Signal, QTimer, QEvent, QPointF, QRect, QRectF
from PySide6.QtGui import (
    QColor, QPen, QPainter, QPainterPath, QWheelEvent, QKeyEvent,
    QKeySequence, QIcon
)
from typing import Optional, Dict, Any

from src.core.program_model import ProgramModel, OperationInstance


def _analyse_brute(code: str, nom: str) -> dict:
    from src.io import simpl_batch as sb
    return sb.analyze_subprogram(code, nom)


def _passes_brutes(code: str, nom: str) -> list:
    from src.io import simpl_batch as sb
    return sb.sequence_z_levels(code, sequence=nom)


def _bornes_brutes(texte: str):
    return ParameterFormWidget._bornes_du_texte(texte)


# La fiche d'un bloc SimPL importé relisait tout son code à chaque clic
# sur l'opération (25 ms): ces lectures ne dépendent que du texte.
from src.core.memo_texte import MemoTexte  # noqa: E402
_analyse_memo = MemoTexte(_analyse_brute)
_passes_memo = MemoTexte(_passes_brutes, copier=list)
_bornes_memo = MemoTexte(_bornes_brutes, copier=None)    # un tuple
from src.core.tool_library import ToolLibrary
from src.gui.theme import COLORS
from src.gui.widgets import SpinCote, formater_cote
from src.core.default_params import DefaultParamsConfig
from src.operations.registry import OperationRegistry
from src.operations.base_operation import ParameterDef, ParameterType


# ──── Mini-calculatrice: évalue +, -, *, / ────

def _calc_eval(text: str, fallback: float = 0.0) -> float:
    """Évalue une expression arithmétique simple (+,-,*,/).
    Accepte , comme séparateur décimal.
    Retourne fallback si l'expression est invalide."""
    text = text.strip().replace(',', '.')
    if not text:
        return fallback
    # Sécurité: n'accepter que des chiffres, points, +, -, *, /, espaces, ()
    # '**' interdit: une puissance du type 9**9**9 gèlerait l'application
    if re.match(r'^[\d\.\+\-\*/\s\(\)]+$', text) and '**' not in text:
        try:
            result = eval(text, {"__builtins__": {}}, {})
            return float(result)
        except Exception:
            pass
    try:
        return float(text)
    except ValueError:
        return fallback


# ──── CalcLineEdit: champ numérique avec mini-calculatrice ────

def select_all_soon(widget):
    """`selectAll()` au prochain tour de boucle, sans planter.

    Le champ peut avoir disparu entre-temps: valider une valeur
    reconstruit le formulaire, et le timer tirait alors sur un objet
    C++ deja detruit ("Internal C++ object (CalcLineEdit) already
    deleted")."""
    def run():
        try:
            widget.selectAll()
        except RuntimeError:
            pass        # formulaire refait: plus rien a selectionner
    QTimer.singleShot(0, run)


class CalcLineEdit(QLineEdit):
    """Champ numérique classique avec mini-calculatrice intégrée.
    - Accepte . et , comme séparateur décimal
    - Accepte +, -, *, / : calcul auto sur Enter/Tab/focus out
    - Sélectionne tout au focus, double-clic compris
    - S'affiche court: 12, 12,5, 0,05 — jamais 12,000
    - N'émet valueChanged qu'à la validation (Enter/Tab/focus out)
    """
    valueChanged = Signal(float)

    def __init__(self, parent=None, decimals=3, min_val=-99999.0,
                 max_val=99999.0, default=0.0):
        super().__init__(parent)
        self._decimals = decimals
        self._min_val = min_val
        self._max_val = max_val
        self._value = default
        self._just_focused = False
        self.setMaximumWidth(65)
        self.setMaximumHeight(26)
        self.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.setText(formater_cote(default, decimals))
        self.editingFinished.connect(self._on_editing_finished)

    def value(self) -> float:
        return self._value

    def setValue(self, val: float):
        self._value = max(self._min_val, min(self._max_val, val))
        self.setText(formater_cote(self._value, self._decimals))

    def setDecimals(self, d: int):
        self._decimals = d
        self.setText(formater_cote(self._value, d))

    def setRange(self, min_val: float, max_val: float):
        self._min_val = min_val
        self._max_val = max_val

    def _on_editing_finished(self):
        raw = self.text()
        result = _calc_eval(raw, self._value)
        result = max(self._min_val, min(self._max_val, result))
        old = self._value
        self._value = result
        self.setText(formater_cote(result, self._decimals))
        if abs(old - result) > 1e-9:
            self.valueChanged.emit(result)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self._just_focused = True
        select_all_soon(self)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if self._just_focused:
            self._just_focused = False
            select_all_soon(self)

    def mouseDoubleClickEvent(self, event):
        super().mouseDoubleClickEvent(event)
        self.selectAll()

    def wheelEvent(self, event: QWheelEvent):
        event.ignore()

    def keyPressEvent(self, event: QKeyEvent):
        if event.text() == ',':
            self.insert('.')
            return
        super().keyPressEvent(event)


class CalcIntLineEdit(CalcLineEdit):
    """Version int du CalcLineEdit."""
    def __init__(self, parent=None, min_val=-99999, max_val=99999, default=0):
        super().__init__(parent, decimals=0, min_val=float(min_val),
                         max_val=float(max_val), default=float(default))

    def value(self) -> int:
        return int(round(self._value))

    def setValue(self, val):
        super().setValue(float(int(val)))


class NoScrollComboBox(QComboBox):
    """QComboBox sans molette."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMaximumHeight(26)

    def wheelEvent(self, event: QWheelEvent):
        event.ignore()


# ──── Delegate pour table: auto-sélection + mini-calculatrice ────

class _CalcCellDelegate(QStyledItemDelegate):
    """Delegate avec auto-sélection et évaluation arithmétique au commit.
    Gère aussi les cellules pattern sub-row (format 'label=value')."""
    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        editor.setAlignment(Qt.AlignmentFlag.AlignRight)
        QTimer.singleShot(0, editor.selectAll)
        return editor

    def setEditorData(self, editor, index):
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        # Sub-row pattern: n'éditer que la partie numérique
        if '=' in text:
            text = text.split('=', 1)[1].strip()
        editor.setText(text)
        QTimer.singleShot(0, editor.selectAll)

    def setModelData(self, editor, model, index):
        raw = editor.text()
        current = index.data(Qt.ItemDataRole.DisplayRole) or ""
        result = _calc_eval(raw, 0.0)
        # Sub-row pattern: reconstruire "label=value"
        if '=' in current:
            label = current.split('=', 1)[0]
            if label in ('nbX', 'nbY'):
                model.setData(
                    index, f"{label}={int(max(1, result))}",
                    Qt.ItemDataRole.EditRole)
            else:
                model.setData(
                    index, f"{label}={result:.1f}",
                    Qt.ItemDataRole.EditRole)
        else:
            model.setData(
                index, f"{result:.3f}", Qt.ItemDataRole.EditRole)


class _ComboDelegate(QStyledItemDelegate):
    """Delegate combo pour sélection dans une liste."""
    def __init__(self, choices, parent=None):
        super().__init__(parent)
        self._choices = choices

    def createEditor(self, parent, option, index):
        combo = QComboBox(parent)
        combo.addItems(self._choices)
        return combo

    def setEditorData(self, editor, index):
        val = index.data(Qt.ItemDataRole.DisplayRole) or ""
        idx = editor.findText(val)
        if idx >= 0:
            editor.setCurrentIndex(idx)

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText(), Qt.ItemDataRole.EditRole)


class _CheckBoxDelegate(QStyledItemDelegate):
    """Delegate checkbox pour une colonne booléenne dans un tableau."""
    def __init__(self, parent=None):
        super().__init__(parent)

    def createEditor(self, parent, option, index):
        # Pas d'éditeur: on toggle au clic via editorEvent
        return None

    def editorEvent(self, event, model, option, index):
        if event.type() in (QEvent.Type.MouseButtonRelease,
                            QEvent.Type.MouseButtonDblClick):
            current = index.data(Qt.ItemDataRole.CheckStateRole)
            new_state = (Qt.CheckState.Unchecked
                         if current == Qt.CheckState.Checked
                         else Qt.CheckState.Checked)
            model.setData(index, new_state, Qt.ItemDataRole.CheckStateRole)
            return True
        return False


class CyclingTableWidget(QTableWidget):
    """QTableWidget type tableur:
    - Tab/Shift-Tab: cycle à travers cellules éditables
    - Flèches: navigation directe
    - Entrée d'un chiffre: remplace le contenu directement
    - Enter: valide et descend
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setItemDelegate(_CalcCellDelegate(self))

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        if key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
            forward = (key == Qt.Key.Key_Tab)
            self._tab_navigate(forward)
            return
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down,
                   Qt.Key.Key_Left, Qt.Key.Key_Right):
            super().keyPressEvent(event)
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            row = self.currentRow()
            col = self.currentColumn()
            if row + 1 < self.rowCount():
                self.setCurrentCell(row + 1, col)
                item = self.item(row + 1, col)
                if item and (item.flags() & Qt.ItemFlag.ItemIsEditable):
                    self.editItem(item)
            return
        # Chiffres, opérateurs: ouvrir l'éditeur directement
        char = event.text()  # capturer en Python AVANT le timer
        if char and char in '0123456789.,+-*/':
            item = self.currentItem()
            if item and (item.flags() & Qt.ItemFlag.ItemIsEditable):
                self.editItem(item)
                QTimer.singleShot(10, lambda c=char: self._inject_key(c))
                return
        super().keyPressEvent(event)

    def _inject_key(self, char: str):
        """Injecte un caractère dans l'éditeur en cours."""
        try:
            editor = self.findChild(QLineEdit)
            if editor and editor.isVisible():
                editor.clear()
                editor.insert(char)
        except RuntimeError:
            pass

    def _tab_navigate(self, forward: bool):
        """Tab: prochain champ éditable sur la MÊME ligne, puis ligne suivante."""
        row = self.currentRow()
        col = self.currentColumn()
        rows = self.rowCount()
        cols = self.columnCount()
        if rows == 0 or cols == 0:
            return
        # Chercher sur la même ligne d'abord
        search = range(col + 1, cols) if forward else range(col - 1, -1, -1)
        for c in search:
            item = self.item(row, c)
            if item and (item.flags() & Qt.ItemFlag.ItemIsEditable):
                self.setCurrentCell(row, c)
                self.editItem(self.item(row, c))
                return
        # Passer à la ligne suivante/précédente
        next_row = row + 1 if forward else row - 1
        if 0 <= next_row < rows:
            scan = range(0, cols) if forward else range(cols - 1, -1, -1)
            for c in scan:
                item = self.item(next_row, c)
                if item and (item.flags() & Qt.ItemFlag.ItemIsEditable):
                    self.setCurrentCell(next_row, c)
                    self.editItem(self.item(next_row, c))
                    return

# ──── Taraudage: table spécialisée ────

_TARAUDAGE_THREAD_TYPES = ["M2.5", "M3", "M4", "M5", "M6", "M8", "M10"]
_TAR_COL_IDX = 0   # #
_TAR_COL_X = 1      # X
_TAR_COL_Y = 2      # Y
_TAR_COL_TYPE = 3   # Type (combo)
_TAR_COL_PZ = 4     # Pz
_TAR_COL_PAT = 5    # Pat. (checkbox)
_TAR_COL_DEL = 6    # × (delete)
_TAR_COLS = 7

# Couleur de fond des sous-rangées pattern
_PAT_SUBROW_BG = QColor("#2a2a3e")
_COLLISION_BG = QColor("#6d4200")  # dark orange pour collisions

# Diamètre nominal par type de filet — importé depuis taraudage.py
from src.operations.taraudage import THREAD_DIAMETER as _THREAD_DIAMETER


class TaraudageTableWidget(CyclingTableWidget):
    """Table spécialisée pour taraudage: Type combo, Pat. checkbox, sous-rangées pattern."""
    thread_type_changed = Signal(str)  # émet le nouveau type thread quand il change

    def __init__(self, parent=None):
        super().__init__(parent)
        # Remplacer le delegate par défaut pour les colonnes numériques
        self.setItemDelegate(_CalcCellDelegate(self))
        # Delegate combo pour la colonne Type
        self._combo_delegate = _ComboDelegate(_TARAUDAGE_THREAD_TYPES, self)
        self.setItemDelegateForColumn(_TAR_COL_TYPE, self._combo_delegate)
        # Delegate checkbox pour la colonne Pat.
        self._check_delegate = _CheckBoxDelegate(self)
        self.setItemDelegateForColumn(_TAR_COL_PAT, self._check_delegate)

        self.setColumnCount(_TAR_COLS)
        self.setHorizontalHeaderLabels(["#", "X", "Y", "Type", "Pz", "Pat.", "\u00d7"])
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        # Colonne delete plus étroite
        self.horizontalHeader().setSectionResizeMode(
            _TAR_COL_DEL, QHeaderView.ResizeMode.Fixed)
        self.horizontalHeader().resizeSection(_TAR_COL_DEL, 32)
        # Colonne Pat. plus étroite
        self.horizontalHeader().setSectionResizeMode(
            _TAR_COL_PAT, QHeaderView.ResizeMode.Fixed)
        self.horizontalHeader().resizeSection(_TAR_COL_PAT, 40)
        # Colonne # plus étroite
        self.horizontalHeader().setSectionResizeMode(
            _TAR_COL_IDX, QHeaderView.ResizeMode.Fixed)
        self.horizontalHeader().resizeSection(_TAR_COL_IDX, 28)

        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.AnyKeyPressed)

    def is_subrow(self, row: int) -> bool:
        """Retourne True si la rangée est une sous-rangée pattern."""
        item = self.item(row, 0)
        if item and item.data(Qt.ItemDataRole.UserRole) == "subrow":
            return True
        return False

    def get_main_row_for_subrow(self, subrow: int) -> int:
        """Retourne l'index de la rangée principale au-dessus d'une sous-rangée."""
        for r in range(subrow - 1, -1, -1):
            if not self.is_subrow(r):
                return r
        return -1


# ──── DathreadPointsWidget: champs séparés par point, style Dathread ────

class DathreadPointsWidget(QWidget):
    """Champs séparés par point avec navigation Tab — style Dathread.
    Remplace les QTableWidget par des CalcLineEdit individuels.
    Gère les points simples et les patterns (taraudage).
    """
    points_changed = Signal()
    point_focus_requested = Signal(int)  # clic n° → surligner au canva

    #: les Ø des points comptent (perçage fraisé « Ø par point »): un
    #: ancien programme garde des Ø détectés qui ne servaient pas — ils
    #: ne s'affichent pas tant que l'opé ne les a pas faits siens
    diametres_actifs = True

    def __init__(self, show_thread_type: bool = False,
                 show_patterns: bool = False, parent=None,
                 show_diameter: bool = False):
        super().__init__(parent)
        self._show_thread_type = show_thread_type
        self._show_patterns = show_patterns
        self._show_diameter = show_diameter
        self._point_rows = []    # list of dicts with widgets
        self._pattern_rows = []  # list of dicts (taraudage only)
        self._suppressing = False

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(4)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # ── Points section ──
        pts_header = QHBoxLayout()
        pts_header.setSpacing(4)
        self._pts_info = QLabel("0 pt")
        self._pts_info.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 10px;")
        pts_header.addStretch()
        pts_header.addWidget(self._pts_info)
        main_layout.addLayout(pts_header)

        # Grille points: en-têtes (ligne 0) et champs dans les MÊMES
        # colonnes → alignement garanti quelle que soit la largeur
        pt_cols = ["n°", "X", "Y"]
        if show_thread_type:
            pt_cols.append("Type")
        if show_diameter:
            pt_cols.append("Ø")
        pt_cols.append("Pz")
        self._pts_container = QWidget()
        self._pts_container.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._pts_grid = QGridLayout(self._pts_container)
        self._pts_grid.setSpacing(2)
        self._pts_grid.setContentsMargins(4, 0, 2, 0)
        self._build_grid_header(self._pts_grid, pt_cols)
        main_layout.addWidget(self._pts_container)

        # Buttons: + Point, CSV, Suppr, Vider (NoFocus pour ne pas capter Tab)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        add_btn = QPushButton("+ Point")
        add_btn.setToolTip("Ajouter un point manuellement")
        add_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        add_btn.clicked.connect(self._on_add_point)
        btn_row.addWidget(add_btn)

        csv_btn = QPushButton("CSV")
        csv_btn.setToolTip("Importer des points depuis un fichier CSV")
        csv_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        csv_btn.clicked.connect(self._on_import_csv)
        btn_row.addWidget(csv_btn)

        del_btn = QPushButton("- Point")
        del_btn.setToolTip("Supprimer le dernier point")
        del_btn.setStyleSheet(f"color: {COLORS['red']};")
        del_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        del_btn.clicked.connect(self._on_remove_last_point)
        btn_row.addWidget(del_btn)

        clear_btn = QPushButton("Vider")
        clear_btn.setToolTip("Supprimer tous les points")
        clear_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        clear_btn.clicked.connect(lambda: self.clear_all())
        btn_row.addWidget(clear_btn)

        btn_row.addStretch()
        main_layout.addLayout(btn_row)

        # ── Pattern section (per-point patterns) ──
        if show_patterns:
            sep = QFrame()
            sep.setFrameShape(QFrame.Shape.HLine)
            sep.setStyleSheet(f"color: {COLORS['surface_hover']};")
            main_layout.addWidget(sep)

            pat_hdr = QHBoxLayout()
            pat_lbl = QLabel("Patterns")
            pat_lbl.setStyleSheet(
                f"font-weight: bold; color: {COLORS['purple']}; font-size: 11px;")
            pat_hdr.addWidget(pat_lbl)
            pat_hdr.addStretch()
            main_layout.addLayout(pat_hdr)

            # Grille patterns: en-têtes et champs dans les mêmes colonnes
            pat_cols = ["n°", "X", "Y", "NbX", "NbY", "PasX", "PasY",
                        "Pz"]
            if show_thread_type:
                pat_cols.append("Type")
            self._pat_container = QWidget()
            self._pat_container.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self._pat_container.setStyleSheet(
                f"background-color: {COLORS['pattern_bg']}; "
                "border-radius: 4px;")
            self._pat_grid = QGridLayout(self._pat_container)
            self._pat_grid.setSpacing(2)
            self._pat_grid.setContentsMargins(4, 2, 2, 2)
            self._build_grid_header(self._pat_grid, pat_cols)
            main_layout.addWidget(self._pat_container)

            # Pattern buttons (NoFocus)
            pbtn = QHBoxLayout()
            pbtn.setSpacing(4)
            pat_add = QPushButton("+ Pattern")
            pat_add.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            pat_add.clicked.connect(self._on_add_pattern)
            pbtn.addWidget(pat_add)
            pat_del = QPushButton("- Pattern")
            pat_del.setStyleSheet(f"color: {COLORS['red']};")
            pat_del.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            pat_del.clicked.connect(self._on_remove_last_pattern)
            pbtn.addWidget(pat_del)
            pbtn.addStretch()
            main_layout.addLayout(pbtn)

    # ── API publique ──

    def load_points(self, points: list):
        """Charge les points depuis les données d'opération."""
        self._suppressing = True
        self._clear_all_rows()
        for pt in points:
            if pt.get('use_pattern', False):
                if self._show_patterns:
                    self._add_pattern_row(pt)
                else:
                    # Widget sans support pattern: dégrader en point
                    # simple plutôt que PERDRE le point silencieusement
                    self._add_point_row(pt)
            else:
                self._add_point_row(pt)
        self._update_info()
        self._suppressing = False

    def collect_points(self) -> list:
        """Récupère tous les points depuis les champs."""
        points = []
        for row in self._point_rows:
            pt = {'x': row['x'].value(), 'y': row['y'].value()}
            pz = row['pz'].value()
            if pz != 0:
                pt['depth'] = pz
            if self._show_thread_type and 'type' in row:
                pt['thread_type'] = row['type'].currentText()
            if 'diam' in row and row['diam'].value() > 0:
                pt['diameter'] = row['diam'].value()
            points.append(pt)
        for row in self._pattern_rows:
            pt = {
                'x': row['x'].value(), 'y': row['y'].value(),
                'use_pattern': True,
                'x_count': max(1, row['nbx'].value()),
                'y_count': max(1, row['nby'].value()),
                'delta_x': row['pasx'].value(),
                'delta_y': row['pasy'].value(),
            }
            pz = row['pz'].value()
            if pz != 0:
                pt['depth'] = pz
            if 'type' in row:
                pt['thread_type'] = row['type'].currentText()
            points.append(pt)
        return points

    def add_point(self, x: float, y: float, depth=None,
                  thread_type='M4'):
        """Ajoute un point (depuis DXF, inject, etc.)."""
        pt = {'x': x, 'y': y}
        if depth is not None:
            pt['depth'] = depth
        if self._show_thread_type:
            pt['thread_type'] = thread_type
        self._add_point_row(pt)
        self._update_info()
        if not self._suppressing:
            self.points_changed.emit()

    def add_points(self, points: list, thread_type: str = 'M4',
                   depth_default=None):
        """Ajoute un LOT de points d'un coup.

        Un appel par point faisait reconstruire tout le formulaire à
        chaque insertion: 200 centres venus du DXF coûtaient près
        d'une minute, le temps croissant avec le nombre déjà posé."""
        if not points:
            return
        ancien = self._suppressing
        self._suppressing = True
        # Qt recalcule la mise en page à chaque widget ajouté: sur
        # deux cents points, c'est deux cents mises en page pour une
        # seule qui compte
        self.setUpdatesEnabled(False)
        try:
            for pt in points:
                ligne = {'x': pt.get('x', 0.0), 'y': pt.get('y', 0.0)}
                profondeur = pt.get('depth', depth_default)
                if profondeur is not None:
                    ligne['depth'] = profondeur
                if self._show_thread_type:
                    ligne['thread_type'] = pt.get('thread_type',
                                                  thread_type)
                if self._show_diameter and pt.get('diameter'):
                    ligne['diameter'] = pt['diameter']
                self._add_point_row(ligne)
        finally:
            self._suppressing = ancien
            self.setUpdatesEnabled(True)
        self._update_info()
        if not self._suppressing:
            self.points_changed.emit()

    def clear_all(self):
        """Supprime tous les points et patterns."""
        self._clear_all_rows()
        self._update_info()
        self.points_changed.emit()

    def point_count(self) -> int:
        return len(self._point_rows)

    # ── Tab navigation via eventFilter ──

    def _get_all_fields(self):
        """Retourne tous les champs éditables dans l'ordre Tab."""
        fields = []
        for row in self._point_rows:
            fields.append(row['x'])
            fields.append(row['y'])
            if 'type' in row:
                fields.append(row['type'])
            if 'diam' in row:
                fields.append(row['diam'])
            fields.append(row['pz'])
        for row in self._pattern_rows:
            fields.append(row['x'])
            fields.append(row['y'])
            fields.append(row['nbx'])
            fields.append(row['nby'])
            fields.append(row['pasx'])
            fields.append(row['pasy'])
            fields.append(row['pz'])
            if 'type' in row:
                fields.append(row['type'])
        return fields

    def _install_tab_filter(self, widget):
        """Installe l'event filter Tab sur un widget."""
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
                fields = self._get_all_fields()
                if not fields:
                    return False
                try:
                    idx = fields.index(obj)
                except ValueError:
                    return False
                if key == Qt.Key.Key_Tab:
                    nxt = (idx + 1) % len(fields)
                    is_last = (idx == len(fields) - 1)
                else:
                    nxt = (idx - 1) % len(fields)
                    is_last = (idx == 0)
                # Tab sur champ non-dernier : déplacer sans MAJ SimPl
                if not is_last:
                    self._suppressing = True
                # Déplacer le focus (editingFinished se déclenche
                # automatiquement sur perte de focus → valide la valeur)
                fields[nxt].setFocus()
                if hasattr(fields[nxt], 'selectAll'):
                    select_all_soon(fields[nxt])
                if not is_last:
                    QTimer.singleShot(0, self._unsuppress)
                return True  # Consommer le Tab
        return super().eventFilter(obj, event)

    def _unsuppress(self):
        """Restaure l'émission de points_changed après Tab intermédiaire."""
        self._suppressing = False

    # ── Rows internes (grilles alignées en-têtes/champs) ──

    def _build_grid_header(self, grid: QGridLayout, cols: list):
        """Ligne 0 de la grille: labels de colonnes alignés sur les
        champs (même colonne de grille = alignement garanti)."""
        for c, txt in enumerate(cols):
            lbl = QLabel(txt)
            lbl.setStyleSheet(
                f"color: {COLORS['text_dim']}; font-size: 10px; "
                "font-weight: bold;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter |
                             Qt.AlignmentFlag.AlignBottom)
            grid.addWidget(lbl, 0, c)
            if txt == "n°":
                grid.setColumnStretch(c, 0)
                grid.setColumnMinimumWidth(c, 24)
            else:
                grid.setColumnStretch(c, 1)
        # Colonnes des boutons ⧉ et × (fixes, non étirées)
        for extra in (len(cols), len(cols) + 1):
            grid.setColumnStretch(extra, 0)
            grid.setColumnMinimumWidth(extra, 24)

    def _make_del_btn(self, row_data: dict, row_list: list,
                      grid: QGridLayout,
                      prefix: str = "") -> QPushButton:
        del_btn = QPushButton("×")
        del_btn.setFixedSize(22, 22)
        del_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        del_btn.setToolTip("Supprimer cette rangée")
        del_btn.setStyleSheet(
            f"color: {COLORS['red']}; font-weight: bold; padding: 0;")
        del_btn.clicked.connect(
            lambda _=False, rd=row_data, rl=row_list, g=grid, p=prefix:
            self._delete_grid_row(rd, rl, g, p))
        return del_btn

    def _make_num_btn(self, row_data: dict,
                      is_pattern: bool) -> QPushButton:
        """N° de rangée cliquable → surligne le point sur le canva."""
        btn = QPushButton()
        btn.setFlat(True)
        btn.setFixedHeight(22)
        btn.setMaximumWidth(30)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip("Voir ce point sur le canva")
        btn.setStyleSheet(
            f"QPushButton {{ color: {COLORS['accent']}; border: none; "
            f"background: transparent; font-size: 10px; "
            f"font-weight: bold; }}"
            f"QPushButton:hover {{ color: {COLORS['yellow']}; }}")
        btn.clicked.connect(
            lambda _=False, rd=row_data, p=is_pattern:
            self._emit_point_focus(rd, p))
        return btn

    def _emit_point_focus(self, row_data: dict, is_pattern: bool):
        try:
            if is_pattern:
                idx = len(self._point_rows) + \
                    self._pattern_rows.index(row_data)
            else:
                idx = self._point_rows.index(row_data)
        except ValueError:
            return
        self.point_focus_requested.emit(idx)

    def _make_dup_btn(self, row_data: dict,
                      is_pattern: bool) -> QPushButton:
        btn = QPushButton("⧉")
        btn.setFixedSize(22, 22)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setToolTip("Dupliquer cette rangée (insérée juste après)")
        btn.setStyleSheet(
            f"color: {COLORS['teal']}; font-weight: bold; padding: 0;")
        btn.clicked.connect(
            lambda _=False, rd=row_data, p=is_pattern:
            self._duplicate_row(rd, p))
        return btn

    def _duplicate_row(self, row_data: dict, is_pattern: bool):
        """⧉: duplique la rangée et l'insère juste après l'originale."""
        if is_pattern:
            row_list, grid, prefix = (
                self._pattern_rows, self._pat_grid, "P")
            if row_data not in row_list:
                return
            pt = {
                'x': row_data['x'].value(),
                'y': row_data['y'].value(),
                'use_pattern': True,
                'x_count': row_data['nbx'].value(),
                'y_count': row_data['nby'].value(),
                'delta_x': row_data['pasx'].value(),
                'delta_y': row_data['pasy'].value(),
                'depth': row_data['pz'].value(),
            }
            if 'type' in row_data:
                pt['thread_type'] = row_data['type'].currentText()
            self._add_pattern_row(pt)
        else:
            row_list, grid, prefix = (
                self._point_rows, self._pts_grid, "")
            if row_data not in row_list:
                return
            pt = {'x': row_data['x'].value(),
                  'y': row_data['y'].value(),
                  'depth': row_data['pz'].value()}
            if 'type' in row_data:
                pt['thread_type'] = row_data['type'].currentText()
            if 'diam' in row_data:
                pt['diameter'] = row_data['diam'].value()
            self._add_point_row(pt)
        new_row = row_list.pop()
        row_list.insert(row_list.index(row_data) + 1, new_row)
        self._regrid_rows(grid, row_list, prefix)
        self._update_info()
        self.points_changed.emit()

    def _place_grid_row(self, grid: QGridLayout, r: int, widgets: list):
        # Zébrage: une rangée sur deux légèrement teintée (lisibilité
        # des grandes listes de points importées de DXF)
        bg = COLORS.get('bg_alt', '') if r % 2 == 0 else ''
        for c, w in enumerate(widgets):
            grid.addWidget(w, r, c)
            if isinstance(w, (CalcLineEdit, CalcIntLineEdit,
                              NoScrollComboBox)):
                w.setStyleSheet(
                    f"background-color: {bg};" if bg else "")

    def _regrid_rows(self, grid: QGridLayout, row_list: list,
                     prefix: str = ""):
        """Repositionne toutes les rangées (après suppression ou
        duplication) et renumérote la colonne n°."""
        for r, row in enumerate(row_list):
            self._place_grid_row(grid, r + 1, row['widgets'])
            if 'num' in row:
                row['num'].setText(f"{prefix}{r + 1}")

    def _delete_grid_row(self, row_data: dict, row_list: list,
                         grid: QGridLayout, prefix: str = ""):
        if row_data not in row_list:
            return
        row_list.remove(row_data)
        for w in row_data['widgets']:
            w.hide()
            w.deleteLater()
        self._regrid_rows(grid, row_list, prefix)
        self._update_info()
        self.points_changed.emit()

    def _make_type_combo(self, pt: dict) -> NoScrollComboBox:
        combo = NoScrollComboBox()
        for t in _TARAUDAGE_THREAD_TYPES:
            combo.addItem(t)
        combo.setCurrentText(pt.get('thread_type', 'M4'))
        combo.setMinimumWidth(0)
        sp = combo.sizePolicy()
        sp.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        combo.setSizePolicy(sp)
        combo.currentIndexChanged.connect(self._on_field_changed)
        return combo

    def _add_point_row(self, pt: dict):
        """Ajoute une rangée de champs pour un point (grille alignée)."""
        x_edit = CalcLineEdit(decimals=3, min_val=-9999, max_val=9999,
                              default=pt.get('x', 0))
        x_edit.editingFinished.connect(self._on_field_changed)

        y_edit = CalcLineEdit(decimals=3, min_val=-9999, max_val=9999,
                              default=pt.get('y', 0))
        y_edit.editingFinished.connect(self._on_field_changed)

        type_combo = None
        if self._show_thread_type:
            type_combo = self._make_type_combo(pt)

        depth_default = pt.get('depth', 0)
        if not isinstance(depth_default, (int, float)):
            depth_default = 0
        pz_edit = CalcLineEdit(decimals=2, min_val=0, max_val=200,
                               default=depth_default)
        pz_edit.editingFinished.connect(self._on_field_changed)

        diam_edit = None
        if self._show_diameter:
            diam = pt.get('diameter') if self.diametres_actifs else 0
            if not isinstance(diam, (int, float)):
                diam = 0
            diam_edit = CalcLineEdit(decimals=3, min_val=0, max_val=200,
                                     default=diam)
            diam_edit.setToolTip(
                "Le Ø de CE trou (vide ou 0: le Ø de l'opération)")
            diam_edit.editingFinished.connect(self._on_field_changed)

        row_data = {'x': x_edit, 'y': y_edit, 'pz': pz_edit}
        if type_combo:
            row_data['type'] = type_combo
        if diam_edit is not None:
            row_data['diam'] = diam_edit

        fields = [x_edit, y_edit]
        if type_combo:
            fields.append(type_combo)
        if diam_edit is not None:
            fields.append(diam_edit)
        fields.append(pz_edit)
        for w in fields:
            self._install_tab_filter(w)
        num_btn = self._make_num_btn(row_data, is_pattern=False)
        row_data['num'] = num_btn
        widgets = [num_btn] + fields + [
            self._make_dup_btn(row_data, is_pattern=False),
            self._make_del_btn(
                row_data, self._point_rows, self._pts_grid)]
        row_data['widgets'] = widgets

        self._point_rows.append(row_data)
        num_btn.setText(str(len(self._point_rows)))
        self._place_grid_row(
            self._pts_grid, len(self._point_rows), widgets)

    def _add_pattern_row(self, pt: dict):
        """Ajoute une rangée pattern (grille alignée)."""
        if not self._show_patterns:
            return
        x_e = CalcLineEdit(decimals=3, min_val=-9999, max_val=9999,
                           default=pt.get('x', 0))
        y_e = CalcLineEdit(decimals=3, min_val=-9999, max_val=9999,
                           default=pt.get('y', 0))
        nbx_e = CalcIntLineEdit(min_val=1, max_val=999,
                                default=pt.get('x_count', 2))
        nby_e = CalcIntLineEdit(min_val=1, max_val=999,
                                default=pt.get('y_count', 2))
        pasx_e = CalcLineEdit(decimals=1, min_val=-999, max_val=999,
                              default=pt.get('delta_x', 10.0))
        pasy_e = CalcLineEdit(decimals=1, min_val=-999, max_val=999,
                              default=pt.get('delta_y', 10.0))
        depth_def = pt.get('depth', 6.0)
        if not isinstance(depth_def, (int, float)):
            depth_def = 6.0
        pz_e = CalcLineEdit(decimals=2, min_val=0, max_val=200,
                            default=depth_def)
        for w in (x_e, y_e, nbx_e, nby_e, pasx_e, pasy_e, pz_e):
            w.editingFinished.connect(self._on_field_changed)

        type_combo = None
        if self._show_thread_type:
            type_combo = self._make_type_combo(pt)

        row_data = {
            'x': x_e, 'y': y_e,
            'nbx': nbx_e, 'nby': nby_e,
            'pasx': pasx_e, 'pasy': pasy_e,
            'pz': pz_e,
        }
        if type_combo:
            row_data['type'] = type_combo

        fields = [x_e, y_e, nbx_e, nby_e, pasx_e, pasy_e, pz_e]
        if type_combo:
            fields.append(type_combo)
        for w in fields:
            self._install_tab_filter(w)
        num_btn = self._make_num_btn(row_data, is_pattern=True)
        row_data['num'] = num_btn
        widgets = [num_btn] + fields + [
            self._make_dup_btn(row_data, is_pattern=True),
            self._make_del_btn(
                row_data, self._pattern_rows, self._pat_grid, "P")]
        row_data['widgets'] = widgets

        self._pattern_rows.append(row_data)
        num_btn.setText(f"P{len(self._pattern_rows)}")
        self._place_grid_row(
            self._pat_grid, len(self._pattern_rows), widgets)

    # ── Handlers ──

    def _on_add_point(self):
        pt = {'x': 0, 'y': 0}
        if self._show_thread_type:
            pt['thread_type'] = 'M4'
        self._add_point_row(pt)
        self._update_info()
        self.points_changed.emit()
        if self._point_rows:
            self._point_rows[-1]['x'].setFocus()
            self._point_rows[-1]['x'].selectAll()

    def _on_remove_last_point(self):
        if not self._point_rows:
            return
        self._delete_grid_row(
            self._point_rows[-1], self._point_rows, self._pts_grid)

    def _on_add_pattern(self):
        pt = {'x': 0, 'y': 0, 'use_pattern': True,
              'x_count': 2, 'y_count': 2,
              'delta_x': 10.0, 'delta_y': 10.0,
              'depth': 0}
        if self._show_thread_type:
            pt['depth'] = 6.0
            pt['thread_type'] = 'M4'
        self._add_pattern_row(pt)
        self._update_info()
        self.points_changed.emit()
        if self._pattern_rows:
            self._pattern_rows[-1]['x'].setFocus()
            self._pattern_rows[-1]['x'].selectAll()

    def _on_remove_last_pattern(self):
        if not self._pattern_rows:
            return
        self._delete_grid_row(
            self._pattern_rows[-1], self._pattern_rows,
            self._pat_grid, "P")

    def _on_import_csv(self):
        """Importe des points depuis un CSV (X;Y ou X,Y par ligne)."""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Importer des points CSV",
            "", "Fichiers CSV (*.csv *.txt);;Tous (*)")
        if not filepath:
            return
        try:
            with open(filepath, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    parts = line.replace(',', ';').split(';')
                    if len(parts) >= 2:
                        try:
                            x = float(parts[0].strip())
                            y = float(parts[1].strip())
                            self.add_point(x, y)
                        except ValueError:
                            continue
        except Exception:
            pass
        self._update_info()

    def _on_field_changed(self, *args):
        if not self._suppressing:
            self._update_info()
            self.points_changed.emit()

    def _clear_all_rows(self):
        for row in self._point_rows:
            for w in row['widgets']:
                w.hide()
                w.deleteLater()
        self._point_rows.clear()
        if self._show_patterns:
            for row in self._pattern_rows:
                for w in row['widgets']:
                    w.hide()
                    w.deleteLater()
            self._pattern_rows.clear()

    def _update_info(self):
        n = len(self._point_rows)
        txt = f"{n} pt" + ("s" if n > 1 else "")
        npat = len(self._pattern_rows)
        if npat:
            total = sum(
                max(1, r['nbx'].value()) * max(1, r['nby'].value())
                for r in self._pattern_rows)
            txt += f" + {npat} pattern ({total} pos)"
        self._pts_info.setText(txt)

    def flash(self, color="#a6e3a1", duration_ms=5000):
        """Flash visuel temporaire."""
        original = self.styleSheet()
        self.setStyleSheet(
            f"background-color: {color}; border: 2px solid {color};")
        QTimer.singleShot(duration_ms,
                          lambda: self._safe_restore(original))

    def _safe_restore(self, original):
        try:
            self.setStyleSheet(original)
        except RuntimeError:
            pass


# ──── Couleurs par catégorie ────

CATEGORY_COLORS = {
    "Perçage": "#89b4fa",
    "Taraudage": "#cba6f7",
    "Surfaçage": "#a6e3a1",
    "Poche": "#f9e2af",
    "Découpe": "#f38ba8",
    "Gravure": "#fab387",
    "Réglage": "#74c7ec",
    "Utilitaire": "#94e2d5",
}

# Ordre d'affichage des catégories dans le popup d'ajout
CAT_ORDER = ["Perçage", "Taraudage", "Surfaçage", "Découpe",
             "Poche", "Réglage", "Utilitaire"]

# Fonds clairs → texte noir
_DARK_TEXT_CATS = {"Surfaçage", "Poche", "Gravure"}

# Repliées à l'ouverture du popup: les 77 commandes du manuel SimPL
# (la recherche les trouve, repliées ou non)
_CATS_REPLIEES = {"Manuel SimPL"}


def _sans_accents(texte: str) -> str:
    """« Filetage spécial » → « filetage special »: la recherche du
    popup ne bute plus sur un accent."""
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", texte.lower())
                   if not unicodedata.combining(c))


class AddOperationPopup(QWidget):
    """Panneau inline pour ajouter une opération — intégré dans la colonne 1."""
    operation_chosen = Signal(str)  # op_type
    favorite_chosen = Signal(list)  # liste de dicts {type, name, params, tool_article?}
    favorite_save_requested = Signal()      # sauver le prog courant
    favorite_delete_requested = Signal(str)  # nom du favori à supprimer
    favorite_rename_requested = Signal(str)  # nom du favori à renommer
    tool_program_chosen = Signal(str)  # nom du programme outil

    def __init__(self, parent=None):
        super().__init__(parent)
        self._expert_mode = False
        self.setStyleSheet(
            "AddOperationPopup { background: #1e1e2e; "
            "border: 2px solid #45475a; border-radius: 8px; }")
        self._favorites = self._load_favorites()
        self._setup_ui()

    #: (action, nom du .nds) — insert / edit / rename / delete / add
    nds_action = Signal(str, str)

    def set_expert_mode(self, enabled: bool):
        self._expert_mode = enabled
        self._filter(self._search.text())

    # ── « expert seulement », au choix de l'utilisateur ──
    # Le code range quelques opérations en expert (bloc SimPl,
    # compteur, fonction); l'atelier, lui, sait lesquelles il ne
    # touche jamais en mode normal. Un clic droit les y envoie, un
    # autre les en ramène — retenu dans les réglages.

    #: clés des réglages: ce que l'utilisateur a rangé en expert, et
    #: ce qu'il a rendu au mode normal
    CLE_EXPERT = 'ops_expert_seulement'
    CLE_NORMAL = 'ops_mode_normal'

    def _reglages(self):
        """Les réglages de l'application, par la fenêtre — ou None."""
        fenetre = self.window()
        panneau = getattr(fenetre, 'params_panel', None)
        return getattr(panneau, '_app_settings', None), panneau

    def expert_seulement(self, op_type: str) -> bool:
        """L'opération est-elle réservée au mode expert ? Le choix de
        l'utilisateur d'abord, celui du code ensuite."""
        reglages, _p = self._reglages()
        if isinstance(reglages, dict):
            if op_type in (reglages.get(self.CLE_NORMAL) or []):
                return False
            if op_type in (reglages.get(self.CLE_EXPERT) or []):
                return True
        try:
            from src.operations.registry import OperationRegistry
            return bool(getattr(OperationRegistry.get(op_type),
                                'EXPERT_ONLY', False))
        except Exception:
            return False

    def basculer_expert(self, op_type: str, expert: bool) -> None:
        """Range l'opération en expert seulement (True) ou la rend au
        mode normal (False), et le retient."""
        reglages, panneau = self._reglages()
        if not isinstance(reglages, dict):
            return
        en_expert = [t for t in (reglages.get(self.CLE_EXPERT) or [])
                     if t != op_type]
        en_normal = [t for t in (reglages.get(self.CLE_NORMAL) or [])
                     if t != op_type]
        (en_expert if expert else en_normal).append(op_type)
        reglages[self.CLE_EXPERT] = en_expert
        reglages[self.CLE_NORMAL] = en_normal
        try:
            panneau.save_app_settings()
        except Exception:
            pass
        for ligne, _header, _cat in self._buttons:
            if ligne.property("op_type") == op_type:
                ligne.setProperty("expert_only", expert)
        self._filter(self._search.text())

    # ── épingler et ordonner ──

    #: la catégorie des épinglées, en tête du catalogue
    CAT_EPINGLES = "★ Épinglées"
    CLE_EPINGLES = 'ops_epinglees'
    CLE_ORDRE = 'ops_ordre'

    #: (action du catalogue) — le panneau le reconstruit
    catalogue_change = Signal()

    def types_epingles(self) -> list:
        reglages, _p = self._reglages()
        if not isinstance(reglages, dict):
            return []
        return [str(t) for t in (reglages.get(self.CLE_EPINGLES) or [])]

    def est_epinglee(self, op_type: str) -> bool:
        return op_type in self.types_epingles()

    def classes_ordonnees(self, cat_name: str, op_classes: list) -> list:
        """Les opérations d'une catégorie dans l'ordre de
        l'utilisateur; les nouvelles à la suite, dans celui du code."""
        reglages, _p = self._reglages()
        voulu = []
        if isinstance(reglages, dict):
            voulu = list((reglages.get(self.CLE_ORDRE) or {}).get(
                cat_name, []))
        par_type = {c.OP_TYPE: c for c in op_classes}
        sortie = [par_type[t] for t in voulu if t in par_type]
        sortie += [c for c in op_classes if c not in sortie]
        return sortie

    def _retenir(self, reglages, panneau) -> None:
        try:
            panneau.save_app_settings()
        except Exception:
            pass
        self.catalogue_change.emit()

    def epingler(self, op_type: str, epingle: bool) -> None:
        """L'étoile: l'opération entre (ou sort) de la catégorie
        « Épinglées », en tête du catalogue."""
        reglages, panneau = self._reglages()
        if not isinstance(reglages, dict):
            return
        liste = [t for t in self.types_epingles() if t != op_type]
        if epingle:
            liste.append(op_type)
        reglages[self.CLE_EPINGLES] = liste
        self._retenir(reglages, panneau)

    def deplacer(self, op_type: str, cat_name: str, sens: int) -> bool:
        """▲ (-1) ou ▼ (+1): l'opération change de place dans sa
        catégorie — ou dans les épinglées. Rend vrai si elle a bougé."""
        reglages, panneau = self._reglages()
        if not isinstance(reglages, dict):
            return False
        if cat_name == self.CAT_EPINGLES:
            liste = self.types_epingles()
        else:
            from src.operations.registry import OperationRegistry
            classes = OperationRegistry.get_by_category().get(cat_name, [])
            liste = [c.OP_TYPE for c in
                     self.classes_ordonnees(cat_name, classes)]
        if op_type not in liste:
            return False
        i = liste.index(op_type)
        j = i + sens
        if not 0 <= j < len(liste):
            return False
        liste[i], liste[j] = liste[j], liste[i]
        if cat_name == self.CAT_EPINGLES:
            reglages[self.CLE_EPINGLES] = liste
        else:
            ordres = dict(reglages.get(self.CLE_ORDRE) or {})
            ordres[cat_name] = liste
            reglages[self.CLE_ORDRE] = ordres
        self._retenir(reglages, panneau)
        return True

    def deplacer_categorie(self, cat_name: str, sens: int) -> bool:
        """▲ (-1) ou ▼ (+1): la catégorie change de place — le même
        ordre que la liste des Paramètres, retenu au même endroit."""
        reglages, panneau = self._reglages()
        if not isinstance(reglages, dict) or panneau is None:
            return False
        try:
            ordre = list(panneau.ordre_categories())
        except Exception:
            return False
        if cat_name not in ordre:
            return False
        i = ordre.index(cat_name)
        j = i + sens
        if not 0 <= j < len(ordre):
            return False
        ordre[i], ordre[j] = ordre[j], ordre[i]
        reglages['categories_order'] = ordre
        try:
            panneau.save_app_settings()
        except Exception:
            pass
        rafraichir = getattr(panneau, 'rafraichir_ordre_categories', None)
        if callable(rafraichir):
            rafraichir()
        self.catalogue_change.emit()
        return True

    def _ligne_du_catalogue(self, btn, op_type: str, cat_name: str):
        """Le bouton de l'opération, puis ★ et ▲ ▼, petits, à droite.
        La ligne porte les propriétés que le filtre lit."""
        from PySide6.QtWidgets import QToolButton
        ligne = QWidget()
        for cle in ("op_type", "cat_name", "display_name", "expert_only"):
            ligne.setProperty(cle, btn.property(cle))
        h = QHBoxLayout(ligne)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(2)
        h.addWidget(btn, stretch=1)
        epinglee = self.est_epinglee(op_type)
        style = ("QToolButton { border: none; font-size: 13px; "
                 "color: #a6adc8; padding: 0 2px; } "
                 "QToolButton:hover { color: #f9e2af; }")
        etoile = QToolButton()
        etoile.setText("★" if epinglee else "☆")
        etoile.setToolTip("Épingler: l'opération passe en tête du "
                          "catalogue, dans « ★ Épinglées », et y reste"
                          if not epinglee else "Désépingler")
        etoile.setStyleSheet(style)
        etoile.setFixedWidth(22)
        etoile.setCursor(Qt.CursorShape.PointingHandCursor)
        etoile.clicked.connect(
            lambda _c=False, t=op_type, e=epinglee: self.epingler(t, not e))
        h.addWidget(etoile)
        for texte, sens, bulle in (("▲", -1, "Monter dans la catégorie"),
                                   ("▼", +1, "Descendre dans la catégorie")):
            fleche = QToolButton()
            fleche.setText(texte)
            fleche.setToolTip(bulle)
            fleche.setStyleSheet(style)
            fleche.setFixedWidth(18)
            fleche.setCursor(Qt.CursorShape.PointingHandCursor)
            fleche.clicked.connect(
                lambda _c=False, t=op_type, c=cat_name, s_=sens:
                self.deplacer(t, c, s_))
            h.addWidget(fleche)
        return ligne

    def menu_pour_type(self, op_type: str):
        """Le menu du clic droit sur une opération du catalogue —
        construit à part pour être vérifiable sans l'ouvrir. Rend
        (menu, {action: appelable})."""
        menu = QMenu(self)
        agrandir_menu(menu)
        actions = {}
        if self.expert_seulement(op_type):
            actions[menu.addAction(
                "Rendre disponible en mode normal")] = (
                lambda t=op_type: self.basculer_expert(t, False))
        else:
            actions[menu.addAction(
                "Basculer en expert seulement")] = (
                lambda t=op_type: self.basculer_expert(t, True))
        return menu, actions

    def operations_expert_cachees(self, categorie: str = None) -> list:
        """Les opérations du catalogue que le mode simple cache —
        celles d'une catégorie, ou toutes. [(op_type, nom, catégorie)]"""
        if self._expert_mode:
            return []
        vues, sortie = set(), []
        for ligne, _header, cat in self._buttons:
            t = ligne.property("op_type")
            if not t or t in vues or not ligne.property("expert_only"):
                continue
            if categorie is not None and cat != categorie:
                continue
            vues.add(t)
            sortie.append((t, ligne.property("display_name"), cat))
        return sortie

    def menu_experts(self, categorie: str = None):
        """Le clic droit en mode simple: chaque opération expert
        cachée, à AJOUTER tout de suite ou à rendre au mode simple.
        Rend (menu, {action: appelable})."""
        menu = QMenu(self)
        agrandir_menu(menu)
        actions = {}
        cachees = self.operations_expert_cachees(categorie)
        if not cachees:
            vide = menu.addAction("Aucune opération expert cachée ici")
            vide.setEnabled(False)
            return menu, actions
        titre = menu.addAction("Opérations du mode expert")
        titre.setEnabled(False)
        for t, nom, cat in cachees:
            sous = menu.addMenu(nom if categorie else f"{nom} ({cat})")
            agrandir_menu(sous)
            actions[sous.addAction("Ajouter")] = (
                lambda op=t: self._on_chosen(op))
            actions[sous.addAction("Afficher en mode simple")] = (
                lambda op=t: self.basculer_expert(op, False))
        return menu, actions

    def _on_menu_experts(self, widget, pos, categorie=None):
        menu, actions = self.menu_experts(categorie)
        choisi = menu.exec(widget.mapToGlobal(pos))
        run = actions.get(choisi)
        if run is not None:
            run()

    def contextMenuEvent(self, event):
        """Clic droit sur le fond du catalogue: toutes les opérations
        expert cachées (une catégorie entièrement expert n'a pas
        d'en-tête à cliquer en mode simple)."""
        if self._expert_mode:
            return super().contextMenuEvent(event)
        menu, actions = self.menu_experts(None)
        choisi = menu.exec(event.globalPos())
        run = actions.get(choisi)
        if run is not None:
            run()

    def _on_menu_type(self, btn, pos):
        menu, actions = self.menu_pour_type(btn.property("op_type"))
        choisi = menu.exec(btn.mapToGlobal(pos))
        run = actions.get(choisi)
        if run is not None:
            run()

    def _build_ensemble_shortcuts(self):
        """Appel prog / Import prog, en tête du catalogue."""
        from src.gui.icons import get_op_icon
        from src.operations.registry import OperationRegistry
        ligne = QHBoxLayout()
        ligne.setSpacing(4)
        ligne.setContentsMargins(0, 0, 0, 2)
        for op_type in ("import_programme", "appel_programme"):
            try:
                op_class = OperationRegistry.get(op_type)
            except Exception:
                continue
            if op_class is None:
                continue
            btn = QPushButton(f"  {op_class.DISPLAY_NAME}")
            btn.setIcon(get_op_icon(op_type, 18))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumHeight(34)
            btn.setToolTip(op_class.DESCRIPTION)
            btn.setStyleSheet(
                "QPushButton { text-align: left; background: #181825; "
                "border-left: 4px solid #89b4fa; border-radius: 4px; "
                "padding: 6px 10px; font-size: 13px; color: #cdd6f4; }"
                "QPushButton:hover { background: #313244; }")
            btn.clicked.connect(
                lambda _c=False, t=op_type: self._on_chosen(t))
            ligne.addWidget(btn)
        self._content_layout.addLayout(ligne)

    def _nds_selected(self) -> str:
        item = self._nds_list.currentItem()
        return item.text() if item is not None else ""

    def _ajuster_hauteur_nds(self):
        """La liste prend la hauteur de son contenu.

        Une hauteur fixe montrait trois lignes sur douze et forçait un
        défilement dans un panneau qui, lui, avait la place."""
        n = max(1, self._nds_list.count())
        ligne = max(18, self._nds_list.sizeHintForRow(0))
        cadre = 2 * self._nds_list.frameWidth() + 4
        self._nds_list.setFixedHeight(min(360, n * ligne + cadre))

    def replier_nds(self):
        """Referme la barre NDS (après un choix de l'utilisateur)."""
        if self._nds_header.isChecked():
            self._nds_header.setChecked(False)

    def _on_nds_fold(self, ouvert: bool):
        self._nds_header.setText(
            ("  \u25be " if ouvert else "  \u25b8 ")
            + "Sous-programmes NDS")
        self._nds_box.setVisible(ouvert)
        if ouvert:
            self.nds_action.emit('refresh', '')

    def set_nds_names(self, noms):
        """Remplit la liste des sous-programmes enregistrés."""
        self._nds_list.clear()
        self._nds_list.addItems(list(noms))
        self._ajuster_hauteur_nds()
        self._nds_header.setText(
            self._nds_header.text().split("  (")[0]
            + (f"  ({len(noms)})" if noms else ""))

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(10, 10, 10, 10)

        # Barre de recherche
        self._search = QLineEdit()
        self._search.setPlaceholderText("Rechercher une opération...")
        self._search.setStyleSheet(
            "QLineEdit { background: #313244; border: 1px solid #45475a; "
            "border-radius: 6px; padding: 6px 10px; color: #cdd6f4; "
            "font-size: 14px; }")
        self._search.textChanged.connect(self._filter)
        layout.addWidget(self._search)

        # Sous-programmes NDS: repliés par défaut, en TÊTE — c'est
        # le premier réflexe (« est-ce que je l'ai déjà fait ? »)
        # avant de composer une opération neuve
        self._nds_header = QPushButton("  \u25b8 Sous-programmes NDS")
        self._nds_header.setCheckable(True)
        self._nds_header.setChecked(False)
        self._nds_header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._nds_header.setStyleSheet(
            "QPushButton { text-align: left; background: #94e2d5; "
            "color: #1e1e2e; font-weight: bold; font-size: 13px; "
            "border: none; border-radius: 4px; padding: 4px 8px; }")
        self._nds_header.setMaximumHeight(28)
        self._nds_header.toggled.connect(self._on_nds_fold)
        layout.addWidget(self._nds_header)

        self._nds_box = QWidget()
        self._nds_box.setVisible(False)
        nds_lay = QVBoxLayout(self._nds_box)
        nds_lay.setContentsMargins(4, 2, 4, 2)
        nds_lay.setSpacing(3)
        self._nds_list = QListWidget()
        self._nds_list.setStyleSheet(
            "QListWidget { background: #181825; color: #cdd6f4; "
            "border: 1px solid #45475a; border-radius: 4px; "
            "font-size: 12px; }")
        self._nds_list.itemDoubleClicked.connect(
            lambda _i: self.nds_action.emit('insert', self._nds_selected()))
        nds_lay.addWidget(self._nds_list)

        boutons = QHBoxLayout()
        boutons.setSpacing(3)
        from src.gui.icons import get_button_icon
        for label, action, icone, bulle in (
                ("Insérer", 'insert', "add",
                 "Ajouter ce sous-programme au programme courant"),
                ("Modifier", 'edit', "settings",
                 "Ouvrir le sous-programme pour le modifier"),
                ("Renommer", 'rename', "dialogue",
                 "Renommer le fichier .nds"),
                ("Supprimer", 'delete', "delete",
                 "Supprimer le fichier .nds"),
                ("Enregistrer", 'add', "save",
                 "Enregistrer les opérations sélectionnées en .nds")):
            b = QPushButton("")
            b.setIcon(get_button_icon(icone, 15))
            b.setToolTip(f"{label} — {bulle}")
            b.setFixedHeight(24)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(
                lambda _c=False, a=action:
                self.nds_action.emit(a, self._nds_selected()))
            boutons.addWidget(b)
        boutons.addStretch()
        nds_lay.addLayout(boutons)
        layout.addWidget(self._nds_box)

        # Conteneur scrollable — hauteur dynamique selon contenu
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setSpacing(4)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(self._content)
        layout.addWidget(scroll)

        self._buttons = []

        # ── Section Favoris (repliable, une seule ligne fermée) ──
        # dans sa zone à elle: l'étoile d'une opération ne refait
        # qu'elle (recréer tout le catalogue coûtait 0,3 s par clic)
        self._fav_header = None
        self._fav_zone = QWidget()
        self._fav_layout = QVBoxLayout(self._fav_zone)
        self._fav_layout.setContentsMargins(0, 0, 0, 0)
        self._fav_layout.setSpacing(4)
        self._content_layout.addWidget(self._fav_zone)
        self._remplir_favoris()

        self._suite_du_setup_ui(scroll)

    def recharger_favoris(self) -> None:
        """Les favoris ont changé (étoile, sauvés, renommés, retirés):
        relus, leur seule zone refaite — le catalogue reste."""
        self._favorites = self._load_favorites()
        self._remplir_favoris()

    def _remplir_favoris(self) -> None:
        ouverte = self._fav_header is not None and self._fav_header.isChecked()
        while self._fav_layout.count():
            w = self._fav_layout.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.deleteLater()
        self._fav_header = None
        self._fav_zone.setVisible(bool(self._favorites))
        if self._favorites:
            n_fav = len(self._favorites)
            fav_header = QPushButton(f"  ★ Favoris  ({n_fav})")
            fav_header.setCheckable(True)
            fav_header.setCursor(Qt.CursorShape.PointingHandCursor)
            fav_header.setToolTip(
                "Afficher / masquer les favoris")
            fav_header.setStyleSheet(
                "QPushButton { text-align: left; background: #f9e2af; "
                "color: #1e1e2e; font-weight: bold; font-size: 13px; "
                "border: none; border-radius: 4px; padding: 4px 8px; }"
                "QPushButton:hover { background: #fab387; }")
            fav_header.setMaximumHeight(28)
            self._fav_layout.addWidget(fav_header)
            self._fav_header = fav_header

            fav_grid = QGridLayout()
            fav_grid.setSpacing(4)
            col = 0
            row_idx = 0
            for fav in self._favorites:
                fav_name = fav.get('name', '?')
                fav_desc = fav.get('description', '')
                ops_list = fav.get('operations', [])
                # Résumé compact
                ops_summary = " → ".join(
                    o.get('name', o.get('type', '?'))[:15]
                    for o in ops_list[:4])
                btn = QPushButton(fav_name)
                btn.setToolTip(f"{fav_desc}\n{ops_summary}")
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.setStyleSheet(
                    "QPushButton { text-align: center; background: #313244; "
                    "border: 1px solid #f9e2af; border-radius: 6px; "
                    "padding: 6px 8px; font-size: 12px; color: #f9e2af; "
                    "font-weight: bold; }"
                    "QPushButton:hover { background: #45475a; "
                    "border-color: #fab387; }")
                btn.setMinimumHeight(34)
                btn.clicked.connect(
                    lambda _, o=ops_list: self._on_fav_chosen(o))
                # Clic droit: supprimer le favori
                btn.setContextMenuPolicy(
                    Qt.ContextMenuPolicy.CustomContextMenu)
                btn.customContextMenuRequested.connect(
                    lambda pos, b=btn, n=fav_name:
                    self._on_fav_context_menu(b, n, pos))
                fav_grid.addWidget(btn, row_idx, col)
                col += 1
                if col >= 2:
                    col = 0
                    row_idx += 1

            fav_w = QWidget()
            fav_w.setLayout(fav_grid)
            self._fav_layout.addWidget(fav_w)
            # Repliés par défaut: la liste des opérations reste
            # visible sans scroller quand on a beaucoup de favoris
            fav_w.setVisible(False)
            fav_header.toggled.connect(fav_w.setVisible)
            fav_header.toggled.connect(
                lambda on, b=fav_header, n=n_fav: b.setText(
                    f"  ★ Favoris  ({n})" if not on
                    else f"  ★ Favoris  ({n})   ▾"))
            # refaits pendant qu'on les regardait: ils restent ouverts
            fav_header.setChecked(ouverte)

    def _suite_du_setup_ui(self, scroll) -> None:
        # Les deux opérations qui créent un ENSEMBLE ouvrent le
        # catalogue: c'est par elles qu'on reprend un programme
        # existant, avant de composer quoi que ce soit de neuf
        self._build_ensemble_shortcuts()

        categories = OperationRegistry.get_by_category()
        # Ordre réglé dans Paramètres, à défaut celui du code
        ordre = list(CAT_ORDER)
        fenetre = self.window()
        panneau = getattr(fenetre, 'params_panel', None)
        if panneau is not None and hasattr(panneau, 'ordre_categories'):
            try:
                ordre = panneau.ordre_categories()
            except Exception:
                pass
        # Les épinglées (★) en tête, dans une catégorie à elles; puis
        # chaque catégorie dans l'ordre que l'utilisateur lui a donné
        # (▲ ▼), à défaut celui du code
        par_type = {c.OP_TYPE: c for cs in categories.values() for c in cs}
        epingles = [t for t in self.types_epingles() if t in par_type]
        blocs = []
        if epingles:
            blocs.append((self.CAT_EPINGLES, [par_type[t] for t in epingles]))
        for cat_name, op_classes in sorted(
                categories.items(),
                key=lambda x: ordre.index(x[0])
                if x[0] in ordre else 99):
            blocs.append((cat_name, self.classes_ordonnees(cat_name,
                                                           op_classes)))
        for cat_name, op_classes in blocs:
            color = CATEGORY_COLORS.get(cat_name, "#6c7086")
            if cat_name == self.CAT_EPINGLES:
                color = COLORS.get('yellow', "#f9e2af")

            # En-tête de catégorie: REPLIABLE, et texte sombre sur le
            # bandeau coloré — le blanc s'y lisait mal
            ouverte = cat_name not in _CATS_REPLIEES
            header = QPushButton(f"  {'▾' if ouverte else '▸'} {cat_name}")
            header.setCheckable(True)
            header.setChecked(ouverte)
            header.setCursor(Qt.CursorShape.PointingHandCursor)
            header.setStyleSheet(
                f"QPushButton {{ text-align: left; background: {color}; "
                f"color: #1e1e2e; font-weight: bold; font-size: 13px; "
                f"border: none; border-radius: 4px; padding: 4px 8px; }}"
                f"QPushButton:hover {{ background: {color}; }}")
            header.setMaximumHeight(28)
            # la ligne de l'en-tête: le bandeau, puis ▲ ▼ pour ranger
            # les catégories entre elles (les épinglées restent en
            # tête)
            ligne_entete = QWidget()
            he = QHBoxLayout(ligne_entete)
            he.setContentsMargins(0, 0, 0, 0)
            he.setSpacing(2)
            he.addWidget(header, stretch=1)
            if cat_name != self.CAT_EPINGLES:
                from PySide6.QtWidgets import QToolButton
                style_fleche = (
                    "QToolButton { border: none; font-size: 13px; "
                    "color: #a6adc8; padding: 0 2px; } "
                    "QToolButton:hover { color: #f9e2af; }")
                for texte, sens, bulle in (
                        ("▲", -1, "Monter la catégorie"),
                        ("▼", +1, "Descendre la catégorie")):
                    fleche = QToolButton()
                    fleche.setText(texte)
                    fleche.setToolTip(bulle)
                    fleche.setStyleSheet(style_fleche)
                    fleche.setFixedWidth(18)
                    fleche.setCursor(Qt.CursorShape.PointingHandCursor)
                    fleche.clicked.connect(
                        lambda _c=False, c=cat_name, s_=sens:
                        self.deplacer_categorie(c, s_))
                    he.addWidget(fleche)
            header._ligne = ligne_entete
            # clic droit: les opérations expert de la catégorie, même
            # en mode simple
            header.setContextMenuPolicy(
                Qt.ContextMenuPolicy.CustomContextMenu)
            header.customContextMenuRequested.connect(
                lambda pos, b=header, c=cat_name:
                self._on_menu_experts(b, pos, c))
            self._content_layout.addWidget(ligne_entete)
            header.toggled.connect(
                lambda on, b=header, n=cat_name: b.setText(
                    f"  ▾ {n}" if on else f"  ▸ {n}"))

            for op_class in op_classes:
                btn = QPushButton(f"  {op_class.DISPLAY_NAME}")
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                # Icône thème-aware
                from src.gui.icons import get_op_icon
                btn.setIcon(get_op_icon(op_class.OP_TYPE, 20))
                btn.setStyleSheet(
                    f"QPushButton {{ text-align: left; background: #181825; "
                    f"border-left: 4px solid {color}; border-radius: 4px; "
                    f"padding: 8px 12px; font-size: 14px; color: #cdd6f4; }}"
                    f"QPushButton:hover {{ background: #313244; }}")
                btn.setMinimumHeight(36)
                btn.setProperty("op_type", op_class.OP_TYPE)
                btn.setProperty("cat_name", cat_name)
                btn.setProperty("display_name", op_class.DISPLAY_NAME)
                # la recherche lit aussi la commande SimPL (ZAxisOffset…)
                btn.setProperty("recherche", _sans_accents(
                    f"{op_class.DISPLAY_NAME} "
                    f"{getattr(op_class, 'COMMANDE', '')}"))
                if getattr(op_class, 'DESCRIPTION', ''):
                    btn.setToolTip(op_class.DESCRIPTION)
                btn.setProperty("expert_only",
                                self.expert_seulement(op_class.OP_TYPE))
                btn.clicked.connect(
                    lambda _, t=op_class.OP_TYPE: self._on_chosen(t))
                # clic droit: expert seulement / mode normal
                btn.setContextMenuPolicy(
                    Qt.ContextMenuPolicy.CustomContextMenu)
                btn.customContextMenuRequested.connect(
                    lambda pos, b=btn: self._on_menu_type(b, pos))
                # la ligne: le bouton, l'étoile, ▲ ▼ — c'est ELLE que
                # le filtre montre ou cache
                ligne = self._ligne_du_catalogue(btn, op_class.OP_TYPE,
                                                 cat_name)
                self._content_layout.addWidget(ligne)
                self._buttons.append((ligne, header, cat_name))
            # Replier la catégorie masque ses opérations. On repasse
            # par le filtre: le déploiement rendait visibles les
            # opérations expert alors qu'on était en mode simple
            header.toggled.connect(
                lambda _on: self._filter(self._search.text()))

        # Les programmes outils NE SONT PAS des opérations: ils
        # vivent sous le bouton dédié de la barre d'outils, qui les
        # rescanne à chaque ouverture.

        # Gestion des favoris: sauver le programme courant
        save_fav_btn = QPushButton("★ Sauver le programme comme favori")
        save_fav_btn.setToolTip(
            "Enregistre la séquence d'opérations actuelle comme favori "
            "réutilisable (clic droit sur un favori pour le supprimer)")
        save_fav_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_fav_btn.setStyleSheet(
            "QPushButton { text-align: center; background: #181825; "
            "border: 1px dashed #f9e2af; border-radius: 6px; "
            "padding: 6px 8px; font-size: 12px; color: #f9e2af; }"
            "QPushButton:hover { background: #313244; }")
        save_fav_btn.setMinimumHeight(32)
        save_fav_btn.clicked.connect(
            lambda: self.favorite_save_requested.emit())
        self._content_layout.addWidget(save_fav_btn)

        self._content_layout.addStretch()

        # Filtre initial: sans lui, un popup fraîchement construit
        # montrait les opérations expert en mode simple
        self._filter("")

        # Ajuster la hauteur dynamiquement selon contenu + écran
        self._adjust_height(scroll)

    def _adjust_height(self, scroll):
        """Ajuste la hauteur du popup selon le contenu et l'écran."""
        from PySide6.QtWidgets import QApplication
        content_h = self._content.sizeHint().height() + 60  # +search+margins
        screen = QApplication.primaryScreen()
        if screen:
            max_h = int(screen.availableGeometry().height() * 0.8)
        else:
            max_h = 800
        final_h = min(content_h, max_h)
        self.setFixedHeight(final_h)

    def _filter(self, text: str):
        text = _sans_accents(text.strip())
        visible_cats = set()
        for btn, header, cat in self._buttons:
            name = btn.property("recherche") or _sans_accents(
                btn.property("display_name"))
            cat_lower = _sans_accents(cat)
            show = not text or text in name or text in cat_lower
            # Masquer les opérations expert_only si pas en mode expert
            if show and btn.property("expert_only") and not self._expert_mode:
                show = False
            if show:
                visible_cats.add(cat)
            # Catégorie repliée: son contenu reste caché — sauf à la
            # recherche, qui trouve aussi dans les repliées
            btn.setVisible(show and (header.isChecked() or bool(text)))
        # Hide headers of empty categories (la ligne entière: le
        # bandeau et ses flèches)
        for btn, header, cat in self._buttons:
            getattr(header, '_ligne', header).setVisible(
                cat in visible_cats)

    def _load_favorites(self) -> list:
        """Charge les favoris depuis data/favorites.json."""
        try:
            from src.core.tool_library import get_base_dir
            base = get_base_dir()
            chemins = []
            detour = os.environ.get('NEODRIVE_APP_SETTINGS')
            if detour:
                chemins.append(os.path.join(os.path.dirname(detour),
                                            "favorites.json"))
            # Chercher dans data/ puis à la racine
            for path in chemins + [
                os.path.join(base, "data", "favorites.json"),
                os.path.join(base, "favorites.json"),
            ]:
                if os.path.exists(path):
                    # illisible: mis de côté et .bak repris — sinon le
                    # prochain favori enregistré écrasait tous les autres
                    from src.core.fichiers_surs import lire_json
                    lu = lire_json(path, [])
                    return lu if isinstance(lu, list) else []
        except Exception:
            pass
        return []

    def _on_fav_context_menu(self, btn, fav_name: str, pos):
        """Clic droit sur un favori: menu Renommer / Supprimer."""
        menu = QMenu(self)
        act_ren = menu.addAction(f"✏ Renommer « {fav_name} »")
        act_del = menu.addAction(f"🗑 Supprimer « {fav_name} »")
        chosen = menu.exec(btn.mapToGlobal(pos))
        if chosen == act_ren:
            self.favorite_rename_requested.emit(fav_name)
        elif chosen == act_del:
            self.favorite_delete_requested.emit(fav_name)

    def _on_chosen(self, op_type: str):
        self.operation_chosen.emit(op_type)
        self.hide()

    def _on_fav_chosen(self, fav_data: list):
        self.favorite_chosen.emit(fav_data)
        self.hide()


# ──── Liste des opérations ────


def op_preview(op) -> bool:
    """L'opération est-elle montrée au canvas (et donc exportée) ?

    Vrai par défaut — un appel de programme externe aussi (octobre
    2026): tout son parcours est tracé, et « une ligne sur N » (clic
    droit) l'allège s'il est trop lourd."""
    params = getattr(op, 'params', {}) or {}
    if 'preview' in params:
        return bool(params['preview'])
    return True


def _accents_dans_le_nom(filepath: str) -> list:
    """Les caractères non ASCII du NOM du fichier (accents, etc.).

    La commande M8 refuse d'appeler un programme dont le nom en porte:
    on les remonte pour prévenir avant l'usinage. Seul le nom compte
    — le dossier au-dessus peut contenir ce qu'il veut."""
    import os as _os
    nom = _os.path.basename((filepath or "").strip().replace('\\', '/'))
    return [c for c in nom if ord(c) > 127]


def instances_offset(op, offset: float, n: int) -> list:
    """Les tailles des n instances emboîtées d'un rectangle ou d'un
    cercle: [{'width_x', 'width_y', 'corner_radius'} | {'diameter'}]
    pour k = 1..n."""
    p = getattr(op, 'params', {}) or {}

    def _f(cle):
        try:
            return float(p.get(cle, 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0
    sortie = []
    for k in range(1, max(0, int(n)) + 1):
        if 'diameter' in p and 'width_x' not in p:
            sortie.append({'diameter': round(_f('diameter')
                                             + 2.0 * offset * k, 4)})
            continue
        taille = {'width_x': round(_f('width_x') + 2.0 * offset * k, 4),
                  'width_y': round(_f('width_y') + 2.0 * offset * k, 4)}
        if 'corner_radius' in p:
            taille['corner_radius'] = round(_f('corner_radius')
                                            + offset * k, 4)
        sortie.append(taille)
    return sortie


def em_genre_rang(tool) -> int:
    """0 extrad, 1 chanfrein, 2 conique, 3 le reste: l'ordre des
    outils qu'on propose à un ébavurage."""
    from src.operations.ebavurage_modeles import genre_outil
    return {'extrad': 0, 'chamfer': 1, 'con': 2}.get(
        genre_outil(getattr(tool, 'name', '')), 3)


def genre_ebavurage(tool) -> int:
    """0 = chanfrein, 1 = conique, 2 = autre chose. C'est l'ordre dans
    lequel on propose un outil de fraisage de tête ou d'ébavurage:
    le chanfrein d'abord, la conique ensuite."""
    nom = f"{getattr(tool, 'name', '')} {getattr(tool, 'type_taraudage', '')}"
    nom = nom.lower()
    if 'cham' in nom or 'chanfrein' in nom:
        return 0
    fiche = getattr(tool, 'geometry', None) or {}
    try:
        angle = float(fiche.get('TipAngle') or 0)
    except (TypeError, ValueError):
        angle = 0.0
    if 'con' in nom.split() or nom.startswith('con') or ' con' in nom \
            or angle > 0:
        return 1
    return 2


def outils_pour_ebavurage(bibliotheque, seulement: bool = False) -> list:
    """[(identifiant, outil)] chanfreins d'abord, coniques ensuite,
    puis le reste — ou seulement les deux premiers genres."""
    if bibliotheque is None:
        return []
    ranges = [(genre_ebavurage(t), rang, tid, t)
              for rang, (tid, t) in enumerate(bibliotheque.tools.items())]
    ranges.sort(key=lambda r: (r[0], r[1]))
    return [(tid, t) for genre, _rang, tid, t in ranges
            if not seulement or genre < 2]


#: taille de police des menus contextuels d'opérations (px)
TAILLE_MENU_OPE = 13


def agrandir_menu(menu) -> None:
    """Un menu qu'on lit debout, à un mètre de l'écran: police plus
    grande, entrées plus hautes, de la marge. Les menus d'opérations
    tenaient en 11 px sur une ligne de 18."""
    menu.setStyleSheet(
        f"QMenu {{ font-size: {TAILLE_MENU_OPE}px; padding: 6px; }}"
        f"QMenu::item {{ padding: 7px 28px 7px 12px; "
        f"min-width: 220px; }}"
        f"QMenu::separator {{ height: 1px; margin: 5px 8px; }}")


class _FavStarDelegate(QStyledItemDelegate):
    """Peint une étoile ☆/★ à DROITE du label de chaque opération.
    Peinte (et non widget par ligne) pour rester compatible avec le
    drag & drop interne de la liste. L'état favori est lu dans la
    donnée UserRole+1 de l'item."""
    #: écart entre deux boutons de ligne. Collés, on visait la
    #: corbeille en croyant viser l'étoile.
    ECART = 5
    STAR_W = 24
    #: l'étoile n'est peinte que sur une OPÉRATION (pas un titre
    #: d'ensemble): la liste pose ce drapeau ligne par ligne
    STAR_ROLE = Qt.ItemDataRole.UserRole + 9
    #: bouton « parcourir » des opérations liées à un fichier externe
    BROWSE_W = 22
    FAV_ROLE = Qt.ItemDataRole.UserRole + 1
    #: opération désactivée: encadrée en rouge, libellé grisé
    OFF_ROLE = Qt.ItemDataRole.UserRole + 2
    #: l'opération porte un chemin de fichier (appel / import)
    BROWSE_ROLE = Qt.ItemDataRole.UserRole + 3
    #: aperçu au canvas: œil ouvert / œil fermé
    EYE_W = 22
    EYE_ROLE = Qt.ItemDataRole.UserRole + 4
    #: le type de l'opération de la ligne (pour le menu)
    TYPE_ROLE = Qt.ItemDataRole.UserRole + 42
    #: activation de l'opération: symbole marche/arrêt
    #: (UserRole+5 appartient déjà à GROUP_ROLE de la liste)
    POWER_W = 22
    POWER_ROLE = Qt.ItemDataRole.UserRole + 6
    #: supprimer l'opération: corbeille, tout au bout de la ligne
    TRASH_W = 22
    TRASH_ROLE = Qt.ItemDataRole.UserRole + 7
    #: reprendre les contours du dessin (gravure, évidement)
    DXF_W = 22
    DXF_ROLE = Qt.ItemDataRole.UserRole + 8
    #: annotations (étiquettes + légende) de l'opé, à droite de l'œil
    ANNOT_W = 22
    ANNOT_ROLE = Qt.ItemDataRole.UserRole + 10
    #: la ligne est une opération d'un ENSEMBLE: elle est en retrait
    #: (icône comprise), un filet à gauche relie les membres
    MEMBRE_ROLE = Qt.ItemDataRole.UserRole + 43
    #: le retrait d'un membre d'ensemble (px)
    RETRAIT = 18

    #: les boutons d'une ligne, de DROITE à gauche. Un seul endroit
    #: décide de l'ordre et des largeurs: le dessin et la zone
    #: cliquable en découlent, ils ne peuvent plus se désaccorder.
    BOUTONS = (
        ('trash', 'TRASH_W', 'TRASH_ROLE'),
        ('star', 'STAR_W', 'STAR_ROLE'),
        ('annot', 'ANNOT_W', 'ANNOT_ROLE'),
        ('eye', 'EYE_W', 'EYE_ROLE'),
        ('power', 'POWER_W', 'POWER_ROLE'),
        ('dxf', 'DXF_W', 'DXF_ROLE'),
        ('browse', 'BROWSE_W', 'BROWSE_ROLE'),
    )

    @classmethod
    def zones(cls, lire) -> dict:
        """{clé: (gauche, largeur)} depuis le bord DROIT de la ligne.

        `lire(role)` rend la donnée de la ligne. Un bouton absent ne
        prend pas de place: les suivants se décalent."""
        out = {}
        offset = 0
        for cle, attr_w, attr_role in cls.BOUTONS:
            if attr_role is not None:
                valeur = lire(getattr(cls, attr_role))
                if cle in ('browse', 'dxf', 'trash', 'star'):
                    present = bool(valeur)
                else:
                    present = valeur is not None
                if not present:
                    continue
            largeur = getattr(cls, attr_w) + cls.ECART
            out[cle] = (offset, largeur)
            offset += largeur
        return out

    @staticmethod
    def bord_droit(liste, rect_ligne) -> int:
        """L'abscisse du bord droit VISIBLE d'une ligne.

        Les boutons se calent dessus, en butée à droite. C'est le
        bord du viewport, pas celui de la ligne: une ligne plus
        large que la colonne (nom long, ancienne géométrie
        mémorisée) mettait les boutons hors de l'écran, et
        agrandir la colonne n'y changeait rien."""
        try:
            largeur = liste.viewport().width()
        except (AttributeError, RuntimeError):
            return rect_ligne.right()
        if largeur <= 0:
            return rect_ligne.right()
        return min(rect_ligne.right(), rect_ligne.left() + largeur - 1)

    @classmethod
    def _draw_dxf(cls, painter, rect, color: str,
                  survole: bool = False):
        """Pictogramme DXF: une feuille au coin plié."""
        cls._preparer(painter, rect, survole)
        pen = QPen(QColor(color))
        pen.setWidthF(1.4 if survole else 1.2)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        cx = rect.center().x()
        cy = rect.center().y()
        w, h, pli = 9.0, 11.0, 3.0
        gauche, haut = cx - w / 2.0, cy - h / 2.0
        chemin = QPainterPath()
        chemin.moveTo(gauche + w - pli, haut)
        chemin.lineTo(gauche, haut)
        chemin.lineTo(gauche, haut + h)
        chemin.lineTo(gauche + w, haut + h)
        chemin.lineTo(gauche + w, haut + pli)
        chemin.closeSubpath()
        painter.drawPath(chemin)
        # le pli du coin
        painter.drawLine(QPointF(gauche + w - pli, haut),
                         QPointF(gauche + w - pli, haut + pli))
        painter.drawLine(QPointF(gauche + w - pli, haut + pli),
                         QPointF(gauche + w, haut + pli))
        painter.restore()

    @classmethod
    def _draw_annot(cls, painter, rect, visible: bool, color: str,
                    survole: bool = False):
        """Pictogramme annotations: une étiquette « A ». Barrée quand
        les annotations de l'opé sont masquées."""
        cls._preparer(painter, rect, survole)
        pen = QPen(QColor(color))
        pen.setWidthF(1.3)
        painter.setPen(pen)
        police = painter.font()
        police.setPointSizeF(9.0)
        police.setBold(True)
        painter.setFont(police)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "A")
        if not visible:
            # trait en biais: annotations masquées
            cx, cy = rect.center().x(), rect.center().y()
            painter.drawLine(QPointF(cx - 6, cy + 6),
                             QPointF(cx + 6, cy - 6))
        painter.restore()

    @classmethod
    def _draw_trash(cls, painter, rect, color: str,
                    survole: bool = False):
        """Corbeille DESSINÉE: les glyphes 🗑 ne s'affichent pas
        partout."""
        cls._preparer(painter, rect, survole)
        pen = QPen(QColor(COLORS['red'] if survole else color))
        pen.setWidthF(1.4 if survole else 1.2)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        cx = rect.center().x()
        cy = rect.center().y()
        w, h = 8.0, 10.0
        haut = cy - h / 2.0
        bas = cy + h / 2.0
        # couvercle et sa poignée
        painter.drawLine(QPointF(cx - w / 2.0 - 1.0, haut),
                         QPointF(cx + w / 2.0 + 1.0, haut))
        painter.drawLine(QPointF(cx - 2.0, haut - 2.0),
                         QPointF(cx + 2.0, haut - 2.0))
        # la cuve, légèrement rentrée vers le bas
        painter.drawLine(QPointF(cx - w / 2.0, haut + 2.0),
                         QPointF(cx - w / 2.0 + 1.0, bas))
        painter.drawLine(QPointF(cx + w / 2.0, haut + 2.0),
                         QPointF(cx + w / 2.0 - 1.0, bas))
        painter.drawLine(QPointF(cx - w / 2.0 + 1.0, bas),
                         QPointF(cx + w / 2.0 - 1.0, bas))
        painter.drawLine(QPointF(cx, haut + 4.0),
                         QPointF(cx, bas - 2.0))
        painter.restore()

    @staticmethod
    def _preparer(painter, rect, survole: bool):
        """Réglage commun à tous les pictogrammes.

        Antialiasing et coordonnées FLOTTANTES: dessinés en entiers,
        les arcs et les diagonales sortaient crénelés. Au survol, un
        fond arrondi dit ce qui va être cliqué."""
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if survole:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(COLORS['surface_hover']))
            painter.drawRoundedRect(
                QRectF(rect).adjusted(1.5, 2.5, -1.5, -2.5), 4.0, 4.0)
            painter.setBrush(Qt.BrushStyle.NoBrush)

    @classmethod
    def _draw_power(cls, painter, rect, is_on: bool, color: str,
                    survole: bool = False):
        """Symbole marche/arrêt: cercle ouvert en haut + barre."""
        cls._preparer(painter, rect, survole)
        pen = QPen(QColor(color))
        pen.setWidthF(1.6 if survole else 1.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        centre = QPointF(rect.center().x(), rect.center().y() + 1.0)
        d = min(rect.width() - 8.0, rect.height() - 8.0, 12.0)
        r = d / 2.0
        painter.drawArc(
            QRectF(centre.x() - r, centre.y() - r, d, d),
            -60 * 16, 300 * 16)
        painter.drawLine(QPointF(centre.x(), centre.y() - r - 2.0),
                         QPointF(centre.x(), centre.y() - 1.0))
        if not is_on:
            # Barré: l'opération ne part pas à la machine
            painter.drawLine(
                QPointF(centre.x() - r - 1.0, centre.y() + r + 1.0),
                QPointF(centre.x() + r + 1.0, centre.y() - r - 1.0))
        painter.restore()

    @classmethod
    def _draw_eye(cls, painter, rect, is_open: bool, color: str,
                  survole: bool = False):
        """Œil DESSINÉ: les glyphes 👁 ne s'affichent pas partout."""
        cls._preparer(painter, rect, survole)
        pen = QPen(QColor(color))
        pen.setWidthF(1.4 if survole else 1.2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        cx = rect.center().x()
        cy = rect.center().y()
        w = min(rect.width() - 8.0, 14.0)
        h = max(4.0, w / 2.0)
        if is_open:
            painter.drawEllipse(QPointF(cx, cy), w / 2.0, h / 2.0)
            painter.setBrush(QColor(color))
            painter.drawEllipse(QPointF(cx, cy), h / 4.0, h / 4.0)
        else:
            # Paupière fermée: un arc bas et un trait
            painter.drawArc(
                QRectF(cx - w / 2.0, cy - h / 2.0, w, h),
                0, -180 * 16)
            painter.drawLine(QPointF(cx - w / 2.0, cy),
                             QPointF(cx + w / 2.0, cy))
        painter.restore()

    def sizeHint(self, option, index):
        """Une ligne ne demande jamais plus large que la colonne: sa
        largeur vient de la vue, son texte s'élide devant les boutons.
        (Le sizeHint naturel — la largeur du texte — faisait défiler
        la liste et emportait les boutons hors de vue.)"""
        from PySide6.QtCore import QSize
        base = super().sizeHint(option, index)
        return QSize(min(base.width(), 80), base.height())

    def paint(self, painter, option, index):
        zones = self.zones(index.data)
        eye = index.data(self.EYE_ROLE)
        power = index.data(self.POWER_ROLE)
        # Quel bouton la souris survole-t-elle ? La liste le sait; le
        # délégué, lui, ne voit que la ligne qu'il peint.
        liste = option.widget
        survol = getattr(liste, '_survol', (-1, ""))
        ligne_survolee = (survol[0] == index.row())

        def _survole(cle):
            return ligne_survolee and survol[1] == cle
        right = sum(largeur for _g, largeur in zones.values())
        # tout se mesure depuis le bord droit visible: le titre
        # s'arrête devant les boutons et s'élide (…) s'il dépasse
        droite = self.bord_droit(liste, option.rect)
        membre = bool(index.data(self.MEMBRE_ROLE))
        retrait = self.RETRAIT if membre else 0
        opt = QStyleOptionViewItem(option)
        gauche_ligne = option.rect.left() + retrait
        opt.rect = QRect(gauche_ligne, option.rect.top(),
                         max(0, droite - gauche_ligne + 1 - right),
                         option.rect.height())
        opt.textElideMode = Qt.TextElideMode.ElideRight
        if membre:
            # le fond (sélection, survol) sur TOUTE la ligne, puis le
            # filet de l'ensemble dans le retrait
            fond = QStyleOptionViewItem(option)
            fond.text = ""
            fond.icon = QIcon()
            style = liste.style() if liste is not None else None
            if style is not None:
                style.drawPrimitive(
                    QStyle.PrimitiveElement.PE_PanelItemViewItem, fond,
                    painter, liste)
            painter.save()
            couleur = QColor(COLORS['blue'])
            couleur.setAlpha(150)
            painter.setPen(QPen(couleur, 2))
            x = option.rect.left() + retrait // 2
            painter.drawLine(x, option.rect.top(), x, option.rect.bottom())
            painter.restore()
        super().paint(painter, opt, index)
        if index.data(self.OFF_ROLE):
            # Une opération hors production doit se voir d'un coup
            # d'œil: le seul texte grisé se confondait avec un libellé
            # de catégorie sombre
            painter.save()
            pen = QPen(QColor(COLORS['red']))
            pen.setWidth(1)
            painter.setPen(pen)
            painter.drawRoundedRect(
                option.rect.adjusted(1 + retrait, 1, -2, -2), 3, 3)
            painter.restore()
        def _rect(cle):
            gauche, largeur = zones[cle]
            return QRect(droite - gauche - largeur + 1, option.rect.top(),
                         largeur, option.rect.height())

        if 'browse' in zones:
            # Ouvrir le fichier appelé/importé sans passer par le
            # formulaire: le geste appartient à la ligne
            painter.save()
            self._preparer(painter, _rect('browse'), _survole('browse'))
            painter.setPen(QColor(COLORS['green']))
            painter.drawText(_rect('browse'),
                             Qt.AlignmentFlag.AlignCenter, "📂")
            painter.restore()
            painter.restore()
        if 'dxf' in zones:
            # Reprendre les contours du dessin, depuis la ligne
            self._draw_dxf(painter, _rect('dxf'), COLORS['blue'],
                           _survole('dxf'))
        if 'annot' in zones:
            annot = index.data(self.ANNOT_ROLE)
            self._draw_annot(
                painter, _rect('annot'), bool(annot),
                COLORS['yellow'] if annot else COLORS['text_muted'],
                _survole('annot'))
        if 'eye' in zones:
            self._draw_eye(
                painter, _rect('eye'), bool(eye),
                COLORS['blue'] if eye else COLORS['text_muted'],
                _survole('eye'))
        if 'power' in zones:
            self._draw_power(
                painter, _rect('power'), bool(power),
                COLORS['green'] if power else COLORS['red'],
                _survole('power'))
        if 'star' in zones:
            is_fav = bool(index.data(self.FAV_ROLE))
            painter.save()
            self._preparer(painter, _rect('star'), _survole('star'))
            painter.setPen(QColor(
                COLORS['yellow'] if is_fav or _survole('star')
                else COLORS['text_dim']))
            painter.drawText(_rect('star'),
                             Qt.AlignmentFlag.AlignCenter,
                             "★" if is_fav or _survole('star')
                             else "☆")
            painter.restore()
            painter.restore()
        if 'trash' in zones:
            # En DERNIER, après les favoris: le geste irréversible
            # est le plus loin de ceux qu'on fait souvent
            self._draw_trash(painter, _rect('trash'),
                             COLORS['text_muted'], _survole('trash'))


class OperationListWidget(QListWidget):
    """Liste des opérations, groupée en ENSEMBLES dépliables.

    Une ligne est soit un titre d'ensemble (import d'un SimPl,
    regroupement manuel), soit une opération. Les signaux portent
    l'INDEX de l'opération dans le programme, pas le numéro de ligne:
    les titres décalent les deux.

    Sélection multiple native (surbrillance): Ctrl+clic ajoute/retire,
    Shift+clic étend depuis la sélection en cours. Alt+clic
    active/désactive une opération. Clic sur l'étoile de droite:
    ajout/retrait des favoris. Clic droit: menu. Double-clic:
    renommage."""
    operation_selected = Signal(int)
    order_changed = Signal()
    operation_toggled = Signal(int)   # bouton ⏻ ou Alt+clic
    select_all_requested = Signal()     # menu du vide: tout choisir
    group_power_toggled = Signal(str)  # ⏻ du titre d'un ensemble
    duplicate_requested = Signal()     # dupliquer la sélection
    #: « Ébavurer avec… »: (index de la source, nom du modèle, côté
    #: ou "" pour celui qui va de soi)
    ebavurage_requested = Signal(int, str, str)
    selection_delete_requested = Signal()   # supprimer la sélection
    group_eye_toggled = Signal(str)    # œil du titre d'un ensemble
    group_annot_toggled = Signal(str)  # A du titre d'un ensemble
    group_star_toggled = Signal(str)   # étoile du titre d'un ensemble
    group_delete_requested = Signal(str)  # corbeille du titre
    rename_requested = Signal(int)    # double-clic → nom éditable
    #: le nom d'une opération a été changé SUR SA LIGNE: (index, nom)
    nom_change = Signal(int, str)
    selection_enable_requested = Signal(bool)  # clic droit sur sélection
    favorite_toggled = Signal(int)    # clic sur l'étoile d'une ligne
    delete_requested = Signal(int)    # corbeille d'une ligne
    contours_requested = Signal(int)  # bouton DXF d'une ligne
    ope_vers_dessin_requested = Signal(int)  # clic droit: Opé → dessin
    copy_requested = Signal()         # Ctrl+C
    paste_requested = Signal()        # Ctrl+V
    group_toggled = Signal(str)       # clic sur un titre d'ensemble
    group_action = Signal(str, str)   # (action, group_id)
    #: la ligne est la tête d'une gamme (son formulaire est le
    #: tableau)
    TETE_ROLE = Qt.ItemDataRole.UserRole + 41
    group_requested = Signal()        # « Grouper la sélection »
    browse_requested = Signal(int)    # clic sur 📂 d'une ligne
    preview_toggled = Signal(int)     # clic sur l'œil d'une ligne
    annotations_toggled = Signal(int)  # clic sur « A » (annot d'une ligne)
    preview_set_requested = Signal(bool)   # menu: sélection visible ?
    #: menu: (opacité 0-1 ou None, une ligne sur N ou None) des
    #: opérations sélectionnées
    affichage_requested = Signal(object, object)

    #: rôle portant l'identifiant d'ensemble d'une ligne de titre
    GROUP_ROLE = Qt.ItemDataRole.UserRole + 5

    def __init__(self, parent=None):
        super().__init__(parent)
        # Le glisser pour ordonner est fait MAISON (octobre 2026): celui
        # de Qt passe par la boucle de glisser de Windows, qui avale la
        # molette — on ne pouvait pas faire défiler une longue liste en
        # tenant une opération. Ici la molette défile pendant qu'on
        # tient, et les bords haut et bas défilent d'eux-mêmes.
        self.setDragDropMode(QListWidget.DragDropMode.NoDragDrop)
        self.setDragEnabled(False)
        self.setSelectionMode(
            QListWidget.SelectionMode.ExtendedSelection)
        self.setMinimumWidth(200)
        #: (point, ligne) du clic gauche qui peut devenir un glisser
        self._appui = None
        #: le clic était sur une ligne déjà choisie: la sélection ne
        #: se réduit qu'au relâcher sans glisser (on tire tout le lot)
        self._appui_differe = False
        #: vrai pendant qu'on tient et déplace
        self._glisse = False
        #: la ligne avant laquelle le lot sera posé (-1: aucune)
        self._cible = -1
        self._defile_bord = QTimer(self)
        self._defile_bord.setInterval(40)
        self._defile_bord.timeout.connect(self._defiler_au_bord)
        self.setItemDelegate(_FavStarDelegate(self))
        self.setMouseTracking(True)
        # Jamais de défilement horizontal: un nom long (« Gamme
        # gravure — Évidement final ») élargissait les lignes au-delà de la
        # colonne, et les boutons de ligne — peints au bord droit de
        # la ligne — sortaient de l'écran. Le texte s'élide, les
        # boutons restent.
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._dragged_ops: list = []
        self.currentRowChanged.connect(self._emit_selected)

    # ── Lignes ↔ opérations ──

    def op_index_at(self, row: int) -> int:
        """Index de l'opération d'une ligne, -1 pour un titre."""
        item = self.item(row)
        if item is None:
            return -1
        value = item.data(Qt.ItemDataRole.UserRole)
        return value if isinstance(value, int) else -1

    def group_id_at(self, row: int) -> str:
        item = self.item(row)
        if item is None:
            return ""
        return str(item.data(self.GROUP_ROLE) or "")

    def row_of_op(self, index: int) -> int:
        for row in range(self.count()):
            if self.op_index_at(row) == index:
                return row
        return -1

    def _emit_selected(self, row: int):
        self.operation_selected.emit(self.op_index_at(row))

    def select_op(self, index: int):
        row = self.row_of_op(index)
        if row >= 0:
            self.setCurrentRow(row)

    def select_group(self, group_id: str, additif: bool = False):
        """Surligne le titre ET toutes les opérations de l'ensemble.

        Le formulaire qui suit est celui de la TÊTE de gamme quand il
        y en a une — le tableau de la gamme —, sinon celui du premier
        membre.

        `additif` (Ctrl+clic): on AJOUTE l'ensemble à la sélection en
        cours au lieu de la remplacer — sans quoi Ctrl+clic sur un
        titre cassait la sélection multiple d'opérations."""
        rows = [r for r in range(self.count())
                if self.group_id_at(r) == group_id
                or self._row_belongs_to(r, group_id)]
        if not rows:
            return
        if additif:
            # Ne pas toucher au curseur (il remettrait la sélection à
            # une seule ligne) ni vider ce qui est déjà choisi
            for row in rows:
                item = self.item(row)
                if item is not None:
                    item.setSelected(True)
            return
        # Ligne courante D'ABORD: déplacer le curseur remet la
        # sélection à cette seule ligne, ce qui effaçait l'ensemble
        tete = [r for r in rows if self.op_index_at(r) >= 0
                and bool(self.item(r).data(self.TETE_ROLE))]
        for row in tete + rows:
            if self.op_index_at(row) >= 0:
                self.setCurrentRow(row)   # le formulaire suit
                break
        self.clearSelection()
        for row in rows:
            item = self.item(row)
            if item is not None:
                item.setSelected(True)

    def _row_belongs_to(self, row: int, group_id: str) -> bool:
        """Une ligne d'opération appartient-elle à cet ensemble ?

        L'appartenance est portée par le modèle: la liste ne la connaît
        que par le titre qui précède."""
        if self.op_index_at(row) < 0:
            return False
        # Une opération d'ensemble est EN RETRAIT: sans cela, la 1re
        # opération isolée suivant un ensemble était happée par lui
        if not self._est_membre(row):
            return False
        for r in range(row, -1, -1):
            gid = self.group_id_at(r)
            if gid:
                return gid == group_id
            if r != row and self.op_index_at(r) >= 0 \
                    and not self._est_membre(r):
                return False        # opération isolée: fin du groupe
        return False

    def _est_membre(self, row: int) -> bool:
        item = self.item(row)
        return bool(item is not None
                    and item.data(_FavStarDelegate.MEMBRE_ROLE))

    # ── le glisser pour ordonner ──

    #: hauteur des bords qui font défiler pendant un glisser (px)
    BORD_DEFILEMENT = 26

    def _commencer_glisser(self) -> None:
        self._glisse = True
        # Mémoriser ce qui est déplacé: à l'arrivée, c'est ce qui
        # détermine l'entrée (ou la sortie) d'un ensemble
        self._dragged_ops = [self.op_index_at(self.row(it))
                             for it in self.selectedItems()]
        self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
        self._defile_bord.start()

    def _suivre_glisser(self, pt) -> None:
        """La ligne d'insertion sous le point (moitié haute d'une
        ligne: avant elle; moitié basse: après)."""
        item = self.itemAt(pt)
        if item is None:
            cible = self.count() if (self.count() and pt.y() >
                                     self.visualItemRect(self.item(
                                         self.count() - 1)).bottom()) \
                else max(0, self._cible)
        else:
            cible = self.row(item)
            if pt.y() > self.visualItemRect(item).center().y():
                cible += 1
        if cible != self._cible:
            self._cible = cible
            self.viewport().update()

    def _point_souris(self):
        from PySide6.QtGui import QCursor
        return self.viewport().mapFromGlobal(QCursor.pos())

    def _defiler_au_bord(self) -> None:
        if not self._glisse:
            self._defile_bord.stop()
            return
        pt = self._point_souris()
        barre = self.verticalScrollBar()
        h = self.viewport().height()
        if pt.y() < self.BORD_DEFILEMENT:
            barre.setValue(barre.value() - max(1, barre.singleStep()))
        elif pt.y() > h - self.BORD_DEFILEMENT:
            barre.setValue(barre.value() + max(1, barre.singleStep()))
        else:
            return
        self._suivre_glisser(pt)

    def _finir_glisser(self) -> bool:
        """Pose le lot avant la ligne cible; rend vrai s'il a bougé."""
        self._glisse = False
        self._defile_bord.stop()
        self.viewport().unsetCursor()
        cible, self._cible = self._cible, -1
        self.viewport().update()
        lignes = sorted(self.row(it) for it in self.selectedItems())
        if not lignes or cible < 0:
            self._dragged_ops = []
            return False
        if lignes == list(range(lignes[0], lignes[-1] + 1)) \
                and lignes[0] <= cible <= lignes[-1] + 1:
            self._dragged_ops = []      # lâché sur lui-même
            return False
        self.blockSignals(True)
        try:
            items = [self.takeItem(r) for r in reversed(lignes)][::-1]
            cible -= sum(1 for r in lignes if r < cible)
            for k, it in enumerate(items):
                self.insertItem(cible + k, it)
            for it in items:
                it.setSelected(True)
        finally:
            self.blockSignals(False)
        self.order_changed.emit()
        return True

    def wheelEvent(self, event):
        super().wheelEvent(event)
        if self._glisse:
            # le contenu a défilé sous le curseur: la cible suit
            self._suivre_glisser(event.position().toPoint())

    def mouseReleaseEvent(self, event):
        if self._glisse and event.button() == Qt.MouseButton.LeftButton:
            self._appui = None
            self._appui_differe = False
            self._finir_glisser()
            return
        if self._appui_differe and self._appui is not None:
            # un simple clic sur une ligne d'un lot: elle seule reste
            item = self.item(self._appui[1])
            if item is not None:
                self.clearSelection()
                item.setSelected(True)
                self.setCurrentItem(item)
        self._appui = None
        self._appui_differe = False
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._glisse or self._cible < 0 or not self.count():
            return
        if self._cible < self.count():
            y = self.visualItemRect(self.item(self._cible)).top()
        else:
            y = self.visualItemRect(self.item(self.count() - 1)).bottom() + 1
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        couleur = QColor(COLORS.get('accent', '#89b4fa'))
        p.setPen(QPen(couleur, 2))
        p.drawLine(6, y, self.viewport().width() - 6, y)
        p.setBrush(couleur)
        p.drawEllipse(QPointF(5, y), 3.5, 3.5)
        p.end()

    def _bouton_row_at(self, pos, cle: str) -> int:
        """Ligne dont le bouton `cle` est sous le curseur, sinon -1.

        Le plan des boutons vit dans le délégué: dessin et zone
        cliquable en découlent tous les deux, ils ne peuvent plus se
        désaccorder d'un bouton."""
        item = self.itemAt(pos)
        if item is None:
            return -1
        row = self.row(item)
        est_operation = self.op_index_at(row) >= 0
        if cle in ('browse', 'dxf'):
            if not est_operation:
                return -1        # titre d'ensemble: pas ces boutons
        elif not est_operation and not self.group_id_at(row):
            return -1
        zones = _FavStarDelegate.zones(item.data)
        if cle not in zones:
            return -1
        gauche, largeur = zones[cle]
        rect = self.visualItemRect(item)
        droite = _FavStarDelegate.bord_droit(self, rect) + 1 - gauche
        if droite - largeur <= pos.x() < droite:
            return row
        return -1

    def _eye_row_at(self, pos) -> int:
        return self._bouton_row_at(pos, 'eye')

    def _annot_row_at(self, pos) -> int:
        return self._bouton_row_at(pos, 'annot')

    def _power_row_at(self, pos) -> int:
        return self._bouton_row_at(pos, 'power')

    def _browse_row_at(self, pos) -> int:
        return self._bouton_row_at(pos, 'browse')

    def _trash_row_at(self, pos) -> int:
        return self._bouton_row_at(pos, 'trash')

    def _dxf_row_at(self, pos) -> int:
        return self._bouton_row_at(pos, 'dxf')

    def _star_row_at(self, pos) -> int:
        return self._bouton_row_at(pos, 'star')

    #: (ligne, clé) du bouton sous la souris. Le délégué le lit
    #: pour éclairer celui qu'on s'apprête à cliquer.
    _survol = (-1, "")

    def leaveEvent(self, event):
        self._poser_survol(-1, "")
        super().leaveEvent(event)

    def _poser_survol(self, row: int, cle: str) -> None:
        """Retient le bouton survolé et redessine ce qu'il faut."""
        if self._survol == (row, cle):
            return
        anciennes = {self._survol[0], row}
        self._survol = (row, cle)
        for ligne in anciennes:
            # `update(QRect)` n'existe pas sur une vue: c'est le
            # viewport qui se redessine
            if 0 <= ligne < self.count():
                self.viewport().update(
                    self.visualItemRect(self.item(ligne)))

    def mouseMoveEvent(self, event):
        # Tenir une ligne et bouger: le glisser pour ordonner (et pas
        # la sélection par balayage)
        if self._appui is not None and \
                event.buttons() & Qt.MouseButton.LeftButton:
            pt = event.position().toPoint()
            if not self._glisse and (pt - self._appui[0]).manhattanLength() \
                    >= QApplication.startDragDistance():
                self._commencer_glisser()
            if self._glisse:
                self._suivre_glisser(pt)
            return
        # Boutons de ligne: le curseur dit qu'ils sont cliquables
        for finder, tip in ((self._power_row_at,
                             "Activer / désactiver l'opération"),
                            (self._eye_row_at, "Aperçu au canvas"),
                            (self._annot_row_at,
                             "Annotations et légende de cette opération"),
                            (self._browse_row_at, "Choisir le fichier"),
                            (self._dxf_row_at,
                             "Appliquer les courbes sélectionnées"),
                            (self._trash_row_at,
                             "Supprimer l'opération")):
            if finder(event.position().toPoint()) >= 0:
                self.viewport().setCursor(
                    Qt.CursorShape.PointingHandCursor)
                if self.op_index_at(
                        finder(event.position().toPoint())) < 0:
                    # le titre d'un ensemble: le geste vaut pour tous
                    tip = {self._trash_row_at: "Supprimer tout l'ensemble",
                           self._annot_row_at:
                               "Annotations de tout l'ensemble",
                           self._power_row_at:
                               "Activer / désactiver tout l'ensemble",
                           self._eye_row_at: "Aperçu de tout l'ensemble",
                           }.get(finder, tip)
                self.setToolTip(tip)
                self._poser_survol(finder(event.position().toPoint()),
                                   self._CLES_BOUTONS[finder.__name__])
                return super().mouseMoveEvent(event)
        self.setToolTip("")
        row = self._star_row_at(event.position().toPoint())
        self._poser_survol(row, 'star' if row >= 0 else "")

        # Curseur main sur la flèche d'un titre d'ensemble
        item = self.itemAt(event.position().toPoint())
        if item is not None and self.op_index_at(self.row(item)) < 0:
            rect = self.visualItemRect(item)
            if event.position().toPoint().x() <= rect.left() + self.ARROW_W:
                self.viewport().setCursor(
                    Qt.CursorShape.PointingHandCursor)
            else:
                self.viewport().unsetCursor()
            super().mouseMoveEvent(event)
            return
        # Curseur main sur la zone étoile (affordance de clic)
        if self._star_row_at(event.position().toPoint()) >= 0:
            self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.viewport().unsetCursor()
        super().mouseMoveEvent(event)

    #: largeur de la zone cliquable de la flèche, à gauche du label
    ARROW_W = 22

    #: quel bouton chaque chercheur désigne
    _CLES_BOUTONS = {
        '_power_row_at': 'power', '_eye_row_at': 'eye',
        '_annot_row_at': 'annot',
        '_browse_row_at': 'browse', '_dxf_row_at': 'dxf',
        '_trash_row_at': 'trash', '_star_row_at': 'star',
    }

    def mousePressEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        # Titre d'ensemble: SEULE la flèche de gauche plie/déplie.
        # Cliquer le label sélectionne le titre (menu contextuel,
        # renommage) sans replier l'ensemble sous le curseur.
        if item is not None and event.button() == \
                Qt.MouseButton.LeftButton \
                and self.op_index_at(self.row(item)) < 0:
            gid = self.group_id_at(self.row(item))
            rect = self.visualItemRect(item)
            # Les boutons du titre passent AVANT le pliage
            if gid and self._power_row_at(event.position().toPoint()) >= 0:
                self.group_power_toggled.emit(gid)
                return
            if gid and self._eye_row_at(event.position().toPoint()) >= 0:
                self.group_eye_toggled.emit(gid)
                return
            if gid and self._annot_row_at(event.position().toPoint()) >= 0:
                self.group_annot_toggled.emit(gid)
                return
            if gid and self._star_row_at(event.position().toPoint()) >= 0:
                self.group_star_toggled.emit(gid)
                return
            if gid and self._trash_row_at(event.position().toPoint()) >= 0:
                self.group_delete_requested.emit(gid)
                return
            if gid and event.position().toPoint().x() <= rect.left() + self.ARROW_W:
                self.group_toggled.emit(gid)
                return
            if gid:
                # Cliquer le titre sélectionne TOUT l'ensemble: on voit
                # d'un coup ce qu'il contient, et les actions de
                # sélection (activer, copier) portent sur le lot.
                # Ctrl: on AJOUTE l'ensemble à la sélection en cours au
                # lieu de la casser.
                additif = bool(event.modifiers()
                               & Qt.KeyboardModifier.ControlModifier)
                self.select_group(gid, additif=additif)
                return
        if (event.button() == Qt.MouseButton.LeftButton
                and not event.modifiers()):
            row = self._eye_row_at(event.position().toPoint())
            if row >= 0:
                self.preview_toggled.emit(self.op_index_at(row))
                return
            row = self._annot_row_at(event.position().toPoint())
            if row >= 0:
                self.annotations_toggled.emit(self.op_index_at(row))
                return
            row = self._power_row_at(event.position().toPoint())
            if row >= 0:
                self.operation_toggled.emit(self.op_index_at(row))
                return
            row = self._browse_row_at(event.position().toPoint())
            if row >= 0:
                self.browse_requested.emit(self.op_index_at(row))
                return
            row = self._dxf_row_at(event.position().toPoint())
            if row >= 0:
                self.contours_requested.emit(self.op_index_at(row))
                return
            row = self._trash_row_at(event.position().toPoint())
            if row >= 0:
                self.delete_requested.emit(self.op_index_at(row))
                return
            row = self._star_row_at(event.position().toPoint())
            if row >= 0:
                self.favorite_toggled.emit(self.op_index_at(row))
                return
        if event.modifiers() & Qt.KeyboardModifier.AltModifier:
            if item:
                idx = self.op_index_at(self.row(item))
                if idx >= 0:
                    self.operation_toggled.emit(idx)
                    return
        if item is not None and event.button() == Qt.MouseButton.LeftButton:
            self._appui = (event.position().toPoint(), self.row(item))
            # une ligne déjà choisie, sans touche: on garde le lot (on
            # va peut-être le tirer)
            if item.isSelected() and not event.modifiers() \
                    and len(self.selectedItems()) > 1:
                self._appui_differe = True
                return
        super().mousePressEvent(event)

    def build_context_menu(self, row: int):
        """Menu du clic droit + action a declencher pour chaque entree.

        Construit a part de `contextMenuEvent` pour etre verifiable
        sans ouvrir de menu modal: la version precedente referait un
        attribut disparu, et le menu ne s'ouvrait donc jamais."""
        gid = self.group_id_at(row) if row >= 0 else ""
        menu = QMenu(self)
        agrandir_menu(menu)
        actions = {}
        if gid:
            actions[menu.addAction("\u25b8 Replier / d\u00e9plier")] = (
                lambda: self.group_toggled.emit(gid))
            for label, name in (
                    ("\u2bc6 Tout replier", 'fold_all'),
                    ("\u2bc8 Tout d\u00e9plier", 'unfold_all')):
                actions[menu.addAction(label)] = (
                    lambda n=name: self.group_action.emit(n, gid))
            menu.addSeparator()
            for label, name in (
                    ("\u270e Renommer l'ensemble", 'rename'),
                    ("\u29c9 Dupliquer l'ensemble", 'duplicate'),
                    ("\u229f Dissoudre l'ensemble", 'dissolve'),
                    ("\U0001f5d1 Supprimer l'ensemble   Suppr", 'delete')):
                actions[menu.addAction(label)] = (
                    lambda n=name: self.group_action.emit(n, gid))
            menu.addSeparator()
            for label, name in (
                    ("\u23fb Activer l'ensemble", 'enable'),
                    ("\u23fc D\u00e9sactiver l'ensemble", 'disable')):
                actions[menu.addAction(label)] = (
                    lambda n=name: self.group_action.emit(n, gid))
            return menu, actions

        selected = [it for it in self.selectedItems()
                    if self.op_index_at(self.row(it)) >= 0]
        if not selected:
            # Clic dans le VIDE sous la liste: c'est là qu'on vise
            # pour coller à la fin, et la version précédente n'y
            # ouvrait aucun menu
            actions[menu.addAction("📋 Coller ici   Ctrl+V")] = (
                self.paste_requested.emit)
            tout = menu.addAction("⧉ Tout sélectionner   Ctrl+A")
            actions[tout] = self.select_all_requested.emit
            tout.setEnabled(any(self.op_index_at(r) >= 0
                                for r in range(self.count())))
            return menu, actions
        n = len(selected)
        suffix = f" ({n} op\u00e9)" if n > 1 else ""
        # Ce que les boutons de la ligne font, le menu le fait aussi:
        # un bouton peut manquer à l'écran, le clic droit, jamais.
        # (Plusieurs lignes sélectionnées: le menu est celui de la
        # sélection, pas de la ligne cliquée.)
        if n == 1 and row >= 0 and self.op_index_at(row) >= 0:
            index = self.op_index_at(row)
            lire = self.item(row).data
            if lire(_FavStarDelegate.DXF_ROLE):
                actions[menu.addAction(
                    "\u25a4 Appliquer les courbes sélectionnées")] = (
                    lambda i=index: self.contours_requested.emit(i))
            if lire(_FavStarDelegate.BROWSE_ROLE):
                actions[menu.addAction(
                    "\U0001f4c2 Ouvrir le fichier appel\u00e9\u2026")] = (
                    lambda i=index: self.browse_requested.emit(i))
            # Ébavurer: un sous-menu par modèle, sur ce qui a un bord
            genre = lire(_FavStarDelegate.TYPE_ROLE)
            try:
                from src.operations.ebavurage import SOURCES
                from src.operations import ebavurage_modeles as em
                modeles = em.noms() if genre in SOURCES else []
                cote_auto = SOURCES.get(genre)
            except Exception:
                modeles, cote_auto = [], None
            if modeles:
                sous = menu.addMenu("\u2699 \u00c9bavurer avec\u2026")
                agrandir_menu(sous)
                for nom in modeles:
                    if cote_auto is not None or genre == "decoupe_cercle":
                        actions[sous.addAction(nom)] = (
                            lambda i=index, n=nom:
                            self.ebavurage_requested.emit(i, n, ""))
                    else:
                        for cote in ("Ext\u00e9rieur", "Int\u00e9rieur"):
                            actions[sous.addAction(
                                f"{nom} \u2014 {cote.lower()}")] = (
                                lambda i=index, n=nom, c=cote:
                                self.ebavurage_requested.emit(i, n, c))
            actions[menu.addAction(
                "\u23fb Activer / d\u00e9sactiver")] = (
                lambda i=index: self.operation_toggled.emit(i))
            actions[menu.addAction(
                "\U0001f441 Montrer / masquer au canvas")] = (
                lambda i=index: self.preview_toggled.emit(i))
            actions[menu.addAction(
                "✎ Dessiner le parcours (Opé → dessin)")] = (
                lambda i=index: self.ope_vers_dessin_requested.emit(i))
            actions[menu.addAction(
                ("\u2605 Retirer des favoris" if lire(
                    _FavStarDelegate.FAV_ROLE)
                 else "\u2606 Mettre en favori"))] = (
                lambda i=index: self.favorite_toggled.emit(i))
            actions[menu.addAction(
                "\U0001f5d1 Supprimer   Suppr")] = (
                lambda i=index: self.delete_requested.emit(i))
            menu.addSeparator()
        # Dupliquer: la sélection entière — un ensemble se duplique
        # en un nouvel ensemble, tête et postes compris
        actions[menu.addAction(f"\u29c9 Dupliquer{suffix}")] = (
            self.duplicate_requested.emit)
        if n > 1:
            actions[menu.addAction(
                f"\U0001f5d1 Supprimer la s\u00e9lection{suffix}   Suppr")] = (
                self.selection_delete_requested.emit)
        actions[menu.addAction(f"\u29c9 Copier{suffix}   Ctrl+C")] = (
            self.copy_requested.emit)
        actions[menu.addAction("\U0001f4cb Coller ici   Ctrl+V")] = (
            self.paste_requested.emit)
        menu.addSeparator()
        act_group = menu.addAction(f"\u229e Grouper{suffix}")
        act_group.setEnabled(n > 1)
        actions[act_group] = self.group_requested.emit
        act_fold_all = menu.addAction(
            "\u2bc6 Replier tous les ensembles")
        act_fold_all.setEnabled(
            any(self.group_id_at(r) for r in range(self.count())))
        actions[act_fold_all] = (
            lambda: self.group_action.emit('fold_all', ''))
        menu.addSeparator()
        actions[menu.addAction(
            f"\U0001f441 Afficher au canvas{suffix}")] = (
            lambda: self.preview_set_requested.emit(True))
        actions[menu.addAction(
            f"\U0001f6ab Masquer du canvas{suffix}")] = (
            lambda: self.preview_set_requested.emit(False))
        # la transparence et la division (Canva 2D et 3D)
        from src.core import affichage as _af
        sous = menu.addMenu(f"🎚 Transparence au canvas{suffix}")
        agrandir_menu(sous)
        for pc in _af.OPACITES:
            actions[sous.addAction(
                "Opaque (100 %)" if pc == 100 else f"{pc} %")] = (
                lambda v=pc: self.affichage_requested.emit(v / 100.0,
                                                           None))
        sous = menu.addMenu(f"✂ Une ligne sur…{suffix}")
        agrandir_menu(sous)
        for n in _af.DIVISIONS:
            actions[sous.addAction(
                "Toutes (1/1)" if n == 1 else f"1 sur {n}")] = (
                lambda k=n: self.affichage_requested.emit(None, k))
        menu.addSeparator()
        actions[menu.addAction(
            f"\u23fb Activer la s\u00e9lection{suffix}")] = (
            lambda: self.selection_enable_requested.emit(True))
        actions[menu.addAction(
            f"\u23fc D\u00e9sactiver la s\u00e9lection{suffix}")] = (
            lambda: self.selection_enable_requested.emit(False))
        return menu, actions

    def contextMenuEvent(self, event):
        item = self.itemAt(event.pos())
        if item and not item.isSelected():
            self.setCurrentRow(self.row(item))
        row = self.row(item) if item else -1
        menu, actions = self.build_context_menu(row)
        if menu is None:
            return
        chosen = menu.exec(event.globalPos())
        run = actions.get(chosen)
        if run is not None:
            run()

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_requested.emit()
            return
        if event.matches(QKeySequence.StandardKey.Paste):
            self.paste_requested.emit()
            return
        super().keyPressEvent(event)

    def selected_rows(self) -> list:
        """INDEX des opérations sélectionnées, triés (titres exclus)."""
        out = [self.op_index_at(self.row(it))
               for it in self.selectedItems()]
        return sorted(i for i in out if i >= 0)

    def mouseDoubleClickEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if item:
            row = self.row(item)
            gid = self.group_id_at(row)
            if gid:
                # Le double-clic PLIE: c'est le geste attendu sur un
                # titre. Le renommage reste au menu contextuel.
                self.group_toggled.emit(gid)
                return
            idx = self.op_index_at(row)
            if idx >= 0:
                self.rename_requested.emit(idx)
        else:
            super().mouseDoubleClickEvent(event)

    def editer_nom(self, index: int, nom: str):
        """Le renommage, SUR la ligne de l'opération: un champ posé sur
        son libellé (les boutons de droite restent visibles). Entrée
        valide, Échap ou un clic ailleurs sans changement annule. Rend
        le champ (None si la ligne est repliée)."""
        row = self.row_of_op(index)
        item = self.item(row) if row >= 0 else None
        if item is None:
            return None
        self.scrollToItem(item)
        rect = self.visualItemRect(item)
        droite = _FavStarDelegate.bord_droit(self, rect)
        boutons = sum(largeur for _g, largeur
                      in _FavStarDelegate.zones(item.data).values())
        gauche = rect.left() + (24 + _FavStarDelegate.RETRAIT
                                if item.data(self.GROUP_ROLE) is None
                                and item.data(_FavStarDelegate.MEMBRE_ROLE)
                                else 4)
        ancien = getattr(self, '_editeur_nom', None)
        if ancien is not None:
            try:
                ancien.deleteLater()
            except RuntimeError:
                pass
        edit = _EditeurNom(self.viewport())
        edit.setText(nom)
        edit.setGeometry(QRect(gauche, rect.top() + 1,
                               max(80, droite - boutons - gauche),
                               rect.height() - 2))
        edit.setStyleSheet(
            "QLineEdit { background: #313244; color: #cdd6f4; "
            "border: 1px solid #89b4fa; border-radius: 3px; "
            "padding: 0 3px; }")
        self._editeur_nom = edit
        fini = {'oui': False}

        def _finir(garder: bool):
            if fini['oui']:
                return
            fini['oui'] = True
            texte = edit.text().strip()
            try:
                edit.deleteLater()
            except RuntimeError:
                pass
            self._editeur_nom = None
            self.setFocus()
            if garder and texte and texte != nom:
                self.nom_change.emit(index, texte)

        edit.editingFinished.connect(lambda: _finir(True))
        edit.annule.connect(lambda: _finir(False))
        edit.show()
        edit.setFocus()
        edit.selectAll()
        return edit


class _EditeurNom(QLineEdit):
    """Le champ du renommage sur une ligne: Échap annule."""
    annule = Signal()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.annule.emit()
            return
        super().keyPressEvent(event)


# ──── Formulaire de paramètres ────

class ParameterFormWidget(QScrollArea):
    """Formulaire dynamique des paramètres d'une opération."""

    #: les opérations qui ont une section Ébavurage (case, outil, Pz)
    OPS_EBAVURAGE = ("taraudage", "taraudage_brut", "percage_foret",
                     "percage_fraise")
    params_changed = Signal(dict)
    #: « Importer » d'un appel externe: id de l'opération à convertir
    import_call_requested = Signal(str)
    #: le tableau de la gamme a changé un poste: (id du poste, ce qui
    #: change: {'tool_id', 'enabled', 'params': {...}})
    gamme_poste_edited = Signal(str, dict)
    #: « + Poste » du tableau: (id de la tête, genre du poste)
    gamme_poste_added = Signal(str, str)
    #: un bouton ou le menu d'une ligne du tableau: (id du poste,
    #: action: ouvrir / calculer / basculer / apercu / monter /
    #: descendre / supprimer)
    gamme_poste_action = Signal(str, str)
    #: les modèles de gamme: (id de la tête, action: appliquer /
    #: enregistrer / supprimer / defaut, nom du modèle)
    gamme_modele_action = Signal(str, str, str)
    generation_blocked = Signal(bool)
    #: « Depuis la sélection du canvas »: remplir dimX dimY X Y avec
    #: les rectangles sélectionnés — un par instance
    rectangles_demandes = Signal()
    #: « Depuis la sélection du canvas » (perçage/taraudage): remplir
    #: les points avec les centres sélectionnés, et le Ø d'un cercle
    centres_demandes = Signal()
    #: « Opé → dessin »: poser l'empreinte de l'opé sur le calque Dessin
    ope_vers_dessin_demandee = Signal()
    #: le formulaire des valeurs communes a changé une valeur:
    #: {'params': {...}} ou {'x': …} / {'y': …} / {'tool_id': …} —
    #: à appliquer à toutes les opérations sélectionnées
    valeurs_communes_changees = Signal(dict)
    create_return_shift = Signal(dict)  # {shift_x, shift_y, shift_z} inversés
    favorite_toggle_requested = Signal()  # clic sur l'étoile du titre
    point_focus_requested = Signal(int)   # n° cliqué dans le tableau

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)

        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._layout.setSpacing(4)
        self._layout.setContentsMargins(2, 2, 2, 2)
        self.setWidget(self._container)

        self._widgets: Dict[str, QWidget] = {}
        self._coord_widgets: Dict[str, QWidget] = {}
        self._tool_combo: Optional[NoScrollComboBox] = None
        self._current_op: Optional[OperationInstance] = None
        self._tool_library: Optional[ToolLibrary] = None
        self._title_browse_btn: Optional[QPushButton] = None
        self._fav_star_btn: Optional[QPushButton] = None
        self._instances_vbox = None
        self._instance_rows: list = []
        self._instance_count_hint = 0
        self._opfields_vbox = None
        self._opfield_rows: list = []
        self._var_bind_widgets: Dict[str, QWidget] = {}
        self._text_var_combo = None
        self._program_ref = None
        self._suppressing_signals = False
        self._depth_warning: Optional[QLabel] = None
        self._expert_mode: bool = False
        self._depth_blocked: bool = False
        self._multi_point_table: Optional[QTableWidget] = None
        self._taraudage_table: Optional[TaraudageTableWidget] = None
        self._points_info: Optional[QLabel] = None
        self._is_multi_point: bool = False
        self._bpm_tool2_combo: Optional[NoScrollComboBox] = None
        self._bpm_tool2_group: Optional[QGroupBox] = None
        self._bpm_labels: Dict[str, QLabel] = {}
        self._rpm_override: Optional[CalcIntLineEdit] = None
        self._feed_overrides: Dict[str, CalcIntLineEdit] = {}
        self._name_label: Optional[QLabel] = None
        self._rpm_lbl: Optional[QLabel] = None
        self._dathread_widget: Optional[DathreadPointsWidget] = None
        self._form_fields: list = []  # champs éditables pour Tab navigation
        # Fiche « Contenu du bloc »: rafraîchie en différé
        self._bloc_detail: Optional[QLabel] = None
        from PySide6.QtCore import QTimer
        self._bloc_refresh_timer = QTimer(self)
        self._bloc_refresh_timer.setSingleShot(True)
        self._bloc_refresh_timer.timeout.connect(self._update_bloc_summary)

        # Le scroll area et son container ne doivent pas capter Tab
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._container.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # « Appliquer les courbes sélectionnées » et « Calculer
        # parcours »: en tête du formulaire, et ils y RESTENT quand on
        # défile — enfants du cadre, pas du contenu. Les deux gestes
        # d'un parcours, côte à côte: prendre le dessin, calculer.
        from src.gui.icons import get_button_icon
        self._barre_calcul = QWidget(self)
        colonne = QVBoxLayout(self._barre_calcul)
        colonne.setContentsMargins(4, 3, 4, 2)
        colonne.setSpacing(2)
        rangee = QHBoxLayout()
        rangee.setContentsMargins(0, 0, 0, 0)
        rangee.setSpacing(6)
        self._bouton_courbes = QPushButton(
            " Appliquer les courbes sélectionnées")
        self._bouton_courbes.setIcon(get_button_icon("dxf", 15))
        self._bouton_courbes.setMinimumHeight(28)
        self._bouton_courbes.setCursor(Qt.CursorShape.PointingHandCursor)
        self._bouton_courbes.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._bouton_courbes.setToolTip(
            "Les courbes sélectionnées au canvas deviennent le dessin "
            "de ce parcours (rectangle de sélection possible).\n"
            "Une courbe à l'intérieur d'une autre est un trou: "
            "l'intérieur d'un « O ». Pour une gamme, tous les postes "
            "les reçoivent.")
        self._bouton_courbes.clicked.connect(self._on_contours_pickup)
        rangee.addWidget(self._bouton_courbes, stretch=1)
        self._bouton_calcul = QPushButton(" Calculer parcours")
        self._bouton_calcul.setObjectName("primary")
        self._bouton_calcul.setMinimumHeight(28)
        self._bouton_calcul.setCursor(Qt.CursorShape.PointingHandCursor)
        self._bouton_calcul.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._bouton_calcul.clicked.connect(self._on_bouton_calcul)
        rangee.addWidget(self._bouton_calcul, stretch=1)
        colonne.addLayout(rangee)
        self._etat_calcul = QLabel("")
        self._etat_calcul.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 10px;")
        colonne.addWidget(self._etat_calcul)
        self._barre_calcul.hide()

    def set_tool_library(self, lib: ToolLibrary):
        self._tool_library = lib

    def set_expert_mode(self, enabled: bool):
        self._expert_mode = enabled
        # Recharger le formulaire si une opération est affichée
        if self._current_op:
            self.load_operation(self._current_op)

    @property
    def is_generation_blocked(self) -> bool:
        return self._depth_blocked

    #: hauteur de la barre de calcul, en pixels (deux boutons, puis
    #: l'état sur sa ligne)
    _HAUTEUR_BARRE_CALCUL = 54

    def _montrer_barre_calcul(self, op) -> None:
        """La barre n'existe que pour ce qui se calcule: parcours et
        tête de gamme."""
        from src.codegen.generator import SimPlGenerator
        visible = op is not None and (
            op.operation_type in SimPlGenerator.SEQ_CALCULEES
            or op.operation_type == "gamme_gravure")
        self._barre_calcul.setVisible(visible)
        # une gravure texte n'a pas de courbes à prendre: son dessin
        # est son texte
        self._bouton_courbes.setVisible(
            visible and op.operation_type != "texte_grave")
        self.setViewportMargins(
            0, self._HAUTEUR_BARRE_CALCUL if visible else 0, 0, 0)
        if visible:
            self._placer_barre_calcul()
            self._maj_barre_calcul()

    def _placer_barre_calcul(self) -> None:
        try:
            self._barre_calcul.setGeometry(
                0, 0, self.width(), self._HAUTEUR_BARRE_CALCUL)
            self._barre_calcul.raise_()
        except RuntimeError:
            pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._barre_calcul.isVisible():
            self._placer_barre_calcul()

    def _maj_barre_calcul(self) -> None:
        """Le bouton dit où on en est: à calculer (accent), calculé
        (vert, « recalculer »), rien à faire."""
        op = self._current_op
        if op is None or not self._barre_calcul.isVisible():
            return
        from src.operations.registry import OperationRegistry
        from src.operations.gravure_2d5 import params_outil
        from src.operations.gamme_gravure import GammeGravure
        bibliotheque = self._bibliotheque()
        programme = getattr(self, '_program_ref', None)
        try:
            if GammeGravure.est_tete(op):
                membres = [m for m in GammeGravure.membres(
                    op, programme.operations if programme else [])
                    if m.operation_type != "dialogue_operateur"
                    and m.enabled]
                a_faire = 0
                for membre in membres:
                    classe = OperationRegistry.get(membre.operation_type)
                    if classe.plan_si_connu(
                            params_outil(membre, bibliotheque)) is None:
                        a_faire += 1
                if not membres:
                    texte, etat, fait = " Calculer gamme", \
                        "aucun poste", False
                elif a_faire:
                    texte, etat, fait = (
                        " Calculer gamme",
                        f"{a_faire} poste(s) à calculer sur "
                        f"{len(membres)}", False)
                else:
                    texte, etat, fait = (" Recalculer gamme",
                                         "gamme calculée", True)
            else:
                classe = OperationRegistry.get(op.operation_type)
                plan = classe.plan_si_connu(params_outil(op, bibliotheque))
                if plan is None:
                    texte, etat, fait = " Calculer parcours", \
                        "parcours à calculer", False
                elif not plan:
                    texte, etat, fait = " Recalculer parcours", \
                        "rien à faire sur ce dessin", True
                else:
                    texte, etat, fait = (" Recalculer parcours",
                                         f"{len(plan)} étape(s) — "
                                         "parcours calculé", True)
        except Exception as exc:
            texte, etat, fait = " Calculer parcours", \
                f"état inconnu: {str(exc)[:40]}", False
        self._bouton_calcul.setText(texte)
        self._bouton_calcul.setEnabled(True)
        # calculé: vert; à calculer: la couleur d'accent (primary)
        self._bouton_calcul.setObjectName("" if fait else "primary")
        self._bouton_calcul.setStyleSheet(
            f"QPushButton {{ background: {COLORS['green']}; "
            f"color: {COLORS['bg']}; font-weight: bold; "
            f"border-radius: 4px; }}" if fait else "")
        self._etat_calcul.setText(etat)

    def _on_bouton_calcul(self) -> None:
        """Le bouton de la barre: parcours, ou toute la gamme."""
        from src.operations.gamme_gravure import GammeGravure
        op = self._current_op
        if op is None:
            return
        self._bouton_calcul.setEnabled(False)
        self._bouton_calcul.setText(" Calcul…")
        try:
            if GammeGravure.est_tete(op):
                self._on_calculer_gamme()
            else:
                self._on_calculer_parcours()
        finally:
            self._maj_barre_calcul()

    def clear_form(self):
        # ── Supprimer les signaux AVANT de détruire les widgets ──
        # Cela empêche _on_param_changed de se déclencher pendant la destruction
        self._suppressing_signals = True
        try:
            self._barre_calcul.hide()
            self.setViewportMargins(0, 0, 0, 0)
        except (RuntimeError, AttributeError):
            pass

        # Nullifier les références aux widgets spéciaux AVANT destruction
        self._widgets.clear()
        self._boites_groupes = {}
        self._coord_widgets.clear()
        self._tool_combo = None
        self._current_op = None
        self._depth_warning = None
        self._multi_point_table = None
        self._taraudage_table = None
        self._points_info = None
        self._is_multi_point = False
        # Ebavurage: nullifier AVANT la destruction
        if hasattr(self, '_ebav_tool_combo'):
            self._ebav_tool_combo = None
        if hasattr(self, '_ebav_cb'):
            self._ebav_cb = None
        # BPM tool2: nullifier AVANT destruction
        self._bpm_tool2_combo = None
        self._bpm_tool2_group = None
        # BPM labels: clear dictionary
        self._bpm_labels.clear()
        # Dathread widget
        self._dathread_widget = None
        # Fiche du bloc importé: couper le rafraîchissement différé,
        # sinon il viserait un QLabel détruit
        self._bloc_refresh_timer.stop()
        self._bloc_detail = None
        self._bloc_tool_combo = None
        self._bloc_tool_specs = None

        # Détacher et supprimer tous les widgets du layout
        # IMPORTANT: blockSignals évite les signaux fantômes (editingFinished etc.)
        # pendant la destruction asynchrone → prévient RuntimeError C++ object deleted
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w:
                w.blockSignals(True)
                # Bloquer aussi les enfants (QLineEdit dans QGroupBox etc.)
                for child in w.findChildren(QWidget):
                    child.blockSignals(True)
                # CACHER, garder le parent, détruire plus tard — et
                # surtout pas `setParent(None)`: un widget posé dans
                # un layout reçoit un `show` DIFFÉRÉ; détaché avant
                # que ce show n'arrive, il devenait une FENÊTRE à lui
                # seul. Quarante découpes créées d'un coup faisaient
                # trois cent vingt popups vides et autant d'entrées
                # dans la barre des tâches.
                w.hide()
                w.deleteLater()

    def operations_communes(self) -> list:
        """Les opérations du formulaire des valeurs communes, ou []."""
        return list(getattr(self, '_ops_communes', None) or [])

    #: les champs posés à côté de « Depuis la sélection » (le
    #: formulaire d'une opération qui a ce bouton)
    _mini_selection = None

    def load_operations_communes(self, ops) -> None:
        """Plusieurs opérations sélectionnées: un formulaire de ce
        qu'elles ont en commun. Chaque champ montre la valeur si
        elles la partagent, sinon celle de la première avec « ≠ »;
        ce qu'on y règle s'applique à TOUTES — régler la profondeur
        ou l'outil de dix perçages ne demande plus dix formulaires.

        Le texte, les contours, les chemins de fichier n'y sont pas:
        ils n'ont pas de valeur commune qui ait un sens."""
        from PySide6.QtWidgets import QCheckBox
        ops = [op for op in ops if op is not None]
        self._suppressing_signals = True
        self.clear_form()
        self._ops_communes = ops
        self._communs = {}
        self._preset_combo = None
        if len(ops) < 2:
            self._suppressing_signals = False
            return
        classes = []
        for op in ops:
            try:
                classes.append(OperationRegistry.get(op.operation_type))
            except KeyError:
                classes.append(None)
        if any(c is None for c in classes):
            self._suppressing_signals = False
            return

        titre = QLabel(f"Valeurs communes — {len(ops)} opérations")
        titre.setStyleSheet(f"font-weight: bold; font-size: 13px; "
                            f"color: {COLORS['accent']};")
        self._layout.addWidget(titre)
        noms = ", ".join(op.name for op in ops)
        sous_titre = QLabel(noms)
        sous_titre.setWordWrap(True)
        sous_titre.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 10px;")
        self._layout.addWidget(sous_titre)
        aide = QLabel("Ce que vous réglez ici s'applique à toutes. "
                      "« ≠ » : les valeurs diffèrent (celle de la "
                      "première est affichée).")
        aide.setWordWrap(True)
        aide.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 10px;")
        self._layout.addWidget(aide)

        # ── Préréglages: enregistrer/rappeler un jeu de valeurs ──
        from PySide6.QtWidgets import QHBoxLayout as _QHBox
        rang_preset = _QHBox()
        rang_preset.setSpacing(4)
        self._preset_combo = NoScrollComboBox()
        self._preset_combo.setToolTip(
            "Rappeler un préréglage: ses valeurs s'appliquent aux "
            "paramètres présents dans la sélection (et sont bornées).")
        self._preset_combo.currentIndexChanged.connect(self._on_choix_preset)
        self._remplir_preset_combo(None)
        btn_save = QPushButton("Enregistrer")
        btn_save.setMaximumHeight(24)
        btn_save.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn_save.setToolTip("Enregistrer les valeurs actuelles comme "
                            "préréglage")
        btn_save.clicked.connect(self._on_enregistrer_preset)
        btn_del = QPushButton("✕")
        btn_del.setMaximumHeight(24)
        btn_del.setMaximumWidth(28)
        btn_del.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn_del.setToolTip("Supprimer le préréglage choisi")
        btn_del.clicked.connect(self._on_supprimer_preset)
        rang_preset.addWidget(self._preset_combo, 1)
        rang_preset.addWidget(btn_save)
        rang_preset.addWidget(btn_del)
        self._layout.addLayout(rang_preset)

        def _etiquette(texte, valeurs):
            distinctes = []
            for v in valeurs:
                if v not in distinctes:
                    distinctes.append(v)
            lbl = QLabel(texte + (" ≠" if len(distinctes) > 1 else ""))
            if len(distinctes) > 1:
                lbl.setStyleSheet(f"color: {COLORS['orange']};")
                lbl.setToolTip("Valeurs actuelles: " + ", ".join(
                    f"{v:g}" if isinstance(v, float) else str(v)
                    for v in distinctes[:12]))
            return lbl

        # ── l'outil, si toutes en prennent un ──
        if all(getattr(c, 'REQUIRES_TOOL', False) for c in classes) \
                and self._tool_library:
            box = QGroupBox("Outil")
            v = QVBoxLayout()
            v.setContentsMargins(4, 8, 4, 4)
            combo = NoScrollComboBox()
            combo.addItem("(inchangé)", "")
            for tid, outil in self._tool_library.tools.items():
                combo.addItem(outil.display_name, tid)
            outils = [op.tool_id for op in ops]
            if len(set(outils)) == 1 and outils[0]:
                index = combo.findData(outils[0])
                if index >= 0:
                    combo.setCurrentIndex(index)
            else:
                combo.setItemText(0, "(inchangé — outils différents)"
                                  if len(set(outils)) > 1 else "(inchangé)")
            combo.currentIndexChanged.connect(
                lambda _i, c=combo: self._on_valeur_commune(
                    'tool_id', c.currentData() or None))
            v.addWidget(combo)
            box.setLayout(v)
            self._layout.addWidget(box)
            self._communs['tool_id'] = combo

        # ── la position, si toutes sont à un point ──
        if all(getattr(c, 'REQUIRES_COORDINATES', True) for c in classes) \
                and not any(op.points for op in ops):
            box = QGroupBox("Position")
            grille = QGridLayout()
            grille.setSpacing(4)
            grille.setContentsMargins(4, 8, 4, 4)
            for colonne, (cle, texte) in enumerate((('x', "X"), ('y', "Y"))):
                valeurs = [float(getattr(op, cle, 0.0)) for op in ops]
                champ = CalcLineEdit(decimals=3, min_val=-9999.0,
                                     max_val=9999.0, default=valeurs[0])
                champ.editingFinished.connect(
                    lambda k=cle, w=champ: self._on_valeur_commune(
                        k, float(w.value())))
                grille.addWidget(_etiquette(texte, valeurs), 0, colonne * 2)
                grille.addWidget(champ, 0, colonne * 2 + 1)
                self._communs[cle] = champ
            box.setLayout(grille)
            self._layout.addWidget(box)

        # ── les paramètres communs, groupe par groupe ──
        definitions = {}
        for c in classes:
            for pdef in c.get_parameters():
                if pdef.expert_only and not self._expert_mode:
                    continue
                definitions.setdefault(pdef.key, []).append(pdef)
        communs = []
        for cle, pdefs in definitions.items():
            if len(pdefs) != len(ops):
                continue
            if any(p.param_type != pdefs[0].param_type for p in pdefs):
                continue
            if pdefs[0].param_type not in (ParameterType.FLOAT,
                                           ParameterType.INT,
                                           ParameterType.BOOL,
                                           ParameterType.CHOICE):
                continue
            if cle in ('contours', 'sequence_name', 'use_pattern'):
                continue
            communs.append(pdefs[0])
        groupes = {}
        for pdef in communs:
            groupes.setdefault(pdef.group or "Paramètres", []).append(pdef)
        for nom_groupe, pdefs in groupes.items():
            box = QGroupBox(nom_groupe)
            grille = QGridLayout()
            grille.setSpacing(4)
            grille.setContentsMargins(4, 8, 4, 4)
            for rang, pdef in enumerate(pdefs):
                valeurs = [op.params.get(pdef.key, pdef.default)
                           for op in ops]
                premiere = valeurs[0]
                if pdef.param_type == ParameterType.FLOAT:
                    try:
                        depart = float(premiere)
                    except (TypeError, ValueError):
                        depart = float(pdef.default or 0.0)
                    plafond = (pdef.max_value if pdef.max_value
                               is not None else 99999.0)
                    borne = self._borne_pour(pdef.key)
                    if borne is not None:
                        plafond = min(plafond, borne)
                        depart = min(depart, borne)
                    w = CalcLineEdit(
                        decimals=3,
                        min_val=(pdef.min_value if pdef.min_value
                                 is not None else -99999.0),
                        max_val=plafond,
                        default=depart)
                    w.editingFinished.connect(
                        lambda k=pdef.key, c=w: self._on_valeur_commune(
                            k, float(c.value()), param=True))
                elif pdef.param_type == ParameterType.INT:
                    try:
                        depart = int(premiere)
                    except (TypeError, ValueError):
                        depart = int(pdef.default or 0)
                    w = CalcIntLineEdit(
                        min_val=int(pdef.min_value or -99999),
                        max_val=int(pdef.max_value or 99999),
                        default=depart)
                    w.editingFinished.connect(
                        lambda k=pdef.key, c=w: self._on_valeur_commune(
                            k, int(c.value()), param=True))
                elif pdef.param_type == ParameterType.BOOL:
                    w = QCheckBox()
                    w.setChecked(bool(premiere))
                    w.toggled.connect(
                        lambda on, k=pdef.key: self._on_valeur_commune(
                            k, bool(on), param=True))
                else:
                    w = NoScrollComboBox()
                    w.addItems([str(ch) for ch in (pdef.choices or [])])
                    w.setCurrentText(str(premiere))
                    w.currentTextChanged.connect(
                        lambda texte, k=pdef.key: self._on_valeur_commune(
                            k, texte, param=True))
                if pdef.tooltip:
                    w.setToolTip(pdef.tooltip)
                etiquette = _etiquette(pdef.label, valeurs)
                grille.addWidget(etiquette, rang, 0)
                grille.addWidget(w, rang, 1)
                if pdef.unit:
                    grille.addWidget(QLabel(pdef.unit), rang, 2)
                self._communs[pdef.key] = w
            box.setLayout(grille)
            self._layout.addWidget(box)
        if not self._communs:
            rien = QLabel("Ces opérations n'ont aucun réglage en commun.")
            rien.setWordWrap(True)
            self._layout.addWidget(rien)
        self._layout.addStretch()
        self._suppressing_signals = False

    def _borne_pour(self, cle: str):
        """La borne (avance ou RPM) qui plafonne ce paramètre en
        édition en lot, ou None. Réglée dans les Paramètres."""
        reglages = getattr(getattr(self, '_params_panel', None),
                           '_app_settings', None) or {}
        cle = str(cle or "")
        if cle.startswith('feed'):
            v = float(reglages.get('avance_max', 0.0) or 0.0)
            return v if v > 0 else None
        if cle.startswith('rpm'):
            v = float(reglages.get('rpm_max', 0.0) or 0.0)
            return v if v > 0 else None
        return None

    def _on_valeur_commune(self, cle: str, valeur, param: bool = False):
        """Un champ du formulaire commun a changé: à toutes."""
        if self._suppressing_signals or not self.operations_communes():
            return
        if cle == 'tool_id' and not valeur:
            return                       # « (inchangé) »
        # Bornes d'usinage: une avance/un régime au-dessus du plafond
        # est ramené au plafond — la machine ne verra jamais plus
        if param:
            borne = self._borne_pour(cle)
            if borne is not None and isinstance(valeur, (int, float)) \
                    and float(valeur) > borne:
                valeur = borne
                w = self._communs.get(cle)
                if w is not None and hasattr(w, 'setValue'):
                    w.blockSignals(True)
                    try:
                        w.setValue(borne)
                    except (TypeError, ValueError):
                        pass
                    w.blockSignals(False)
        self.valeurs_communes_changees.emit(
            {'params': {cle: valeur}} if param else {cle: valeur})

    # ──── Préréglages d'édition en lot ────

    def _flash_status(self, message: str):
        """Message court dans la barre d'état, s'il y en a une."""
        try:
            self.window().statusBar().showMessage(message, 4000)
        except Exception:
            pass

    def _batch_presets(self) -> list:
        reglages = getattr(getattr(self, '_params_panel', None),
                           '_app_settings', None) or {}
        presets = reglages.get('batch_presets')
        return list(presets) if isinstance(presets, list) else []

    def _sauver_batch_presets(self, presets: list) -> None:
        pp = getattr(self, '_params_panel', None)
        if pp is None or not hasattr(pp, '_app_settings'):
            return
        pp._app_settings['batch_presets'] = presets
        if hasattr(pp, 'save_app_settings'):
            try:
                pp.save_app_settings()
            except Exception:
                pass

    @staticmethod
    def _lire_widget_commun(w):
        """La valeur courante d'un champ du formulaire commun."""
        from PySide6.QtWidgets import QCheckBox
        if isinstance(w, QCheckBox):
            return bool(w.isChecked())
        if hasattr(w, 'value'):
            try:
                return w.value()
            except Exception:
                return None
        if hasattr(w, 'currentText'):
            return w.currentText()
        return None

    def _valeurs_communes_actuelles(self) -> dict:
        """Les valeurs des paramètres du formulaire commun (hors
        outil/position): ce qu'un préréglage enregistre."""
        out = {}
        for cle, w in (self._communs or {}).items():
            if cle in ('tool_id', 'x', 'y'):
                continue
            val = self._lire_widget_commun(w)
            if val is not None:
                out[cle] = val
        return out

    def _appliquer_batch_preset(self, values: dict) -> int:
        """Applique un préréglage: chaque valeur dont le paramètre est
        présent dans la sélection est posée (et bornée). Rend le
        nombre de valeurs appliquées."""
        n = 0
        for cle, val in (values or {}).items():
            w = self._communs.get(cle)
            if w is None:
                continue
            w.blockSignals(True)
            try:
                if hasattr(w, 'setValue'):
                    w.setValue(val)
                elif hasattr(w, 'setChecked'):
                    w.setChecked(bool(val))
                elif hasattr(w, 'setCurrentText'):
                    w.setCurrentText(str(val))
            except (TypeError, ValueError):
                w.blockSignals(False)
                continue
            w.blockSignals(False)
            est_param = cle not in ('tool_id', 'x', 'y')
            self._on_valeur_commune(cle, val, param=est_param)
            n += 1
        return n

    def _on_enregistrer_preset(self):
        from PySide6.QtWidgets import QInputDialog
        valeurs = self._valeurs_communes_actuelles()
        if not valeurs:
            self._flash_status("Rien à enregistrer dans ce préréglage")
            return
        nom, ok = QInputDialog.getText(
            self, "Nouveau préréglage",
            "Nom du préréglage d'édition en lot :")
        nom = (nom or "").strip()
        if not ok or not nom:
            return
        presets = [p for p in self._batch_presets()
                   if p.get('name') != nom]
        presets.append({'name': nom, 'values': valeurs})
        self._sauver_batch_presets(presets)
        if hasattr(self, '_preset_combo') and self._preset_combo is not None:
            self._remplir_preset_combo(nom)
        self._flash_status(
            f"Préréglage « {nom} » enregistré ({len(valeurs)} valeur(s))")

    def _on_supprimer_preset(self):
        combo = getattr(self, '_preset_combo', None)
        if combo is None:
            return
        nom = combo.currentData()
        if not nom:
            return
        presets = [p for p in self._batch_presets()
                   if p.get('name') != nom]
        self._sauver_batch_presets(presets)
        self._remplir_preset_combo(None)
        self._flash_status(f"Préréglage « {nom} » supprimé")

    def _on_choix_preset(self, index: int):
        combo = getattr(self, '_preset_combo', None)
        if combo is None or self._suppressing_signals:
            return
        nom = combo.itemData(index)
        if not nom:
            return
        preset = next((p for p in self._batch_presets()
                       if p.get('name') == nom), None)
        if preset is None:
            return
        n = self._appliquer_batch_preset(preset.get('values') or {})
        self._flash_status(
            f"Préréglage « {nom} » appliqué ({n} valeur(s))")

    def _remplir_preset_combo(self, a_selectionner):
        combo = getattr(self, '_preset_combo', None)
        if combo is None:
            return
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("Préréglages…", None)
        for p in self._batch_presets():
            combo.addItem(p.get('name', '?'), p.get('name'))
        if a_selectionner:
            i = combo.findData(a_selectionner)
            if i >= 0:
                combo.setCurrentIndex(i)
        combo.blockSignals(False)

    def load_operation(self, op: OperationInstance):
        self._suppressing_signals = True
        self.clear_form()
        self._ops_communes = []
        self._communs = {}
        self._preset_combo = None
        # les champs posés à côté de « Depuis la sélection »: ceux de
        # CETTE opération seulement
        self._mini_selection = None
        self._current_op = op
        self._montrer_barre_calcul(op)
        self._instances_vbox = None
        self._instance_rows = []
        self._opfields_vbox = None
        self._opfield_rows = []
        self._var_bind_widgets = {}
        self._text_var_combo = None

        try:
            op_class = OperationRegistry.get(op.operation_type)
        except KeyError:
            lbl = QLabel(f"Opération inconnue: {op.operation_type}")
            self._layout.addWidget(lbl)
            self._suppressing_signals = False
            return

        # Titre : type + nom éditable sur la même ligne
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(6)
        type_lbl = QLabel(f"{op_class.DISPLAY_NAME}")
        type_lbl.setStyleSheet(
            "font-weight: bold; font-size: 13px; color: #cdd6f4;")
        title_row.addWidget(type_lbl)

        # Nom: un LABEL — on renomme sur la ligne de la liste
        # (double-clic), et seulement là
        name_lbl = QLabel(op.name)
        name_lbl.setStyleSheet(
            "color: #cdd6f4; font-size: 13px; padding: 0 2px;")
        name_lbl.setToolTip("Pour renommer: double-clic sur la ligne de "
                            "l'opération, dans la liste")
        title_row.addWidget(name_lbl, stretch=1)
        self._name_label = name_lbl

        # Étoile favoris (☆/★) à droite du label de l'opération
        star = QPushButton()
        star.setFlat(True)
        star.setFixedSize(24, 24)
        star.setCursor(Qt.CursorShape.PointingHandCursor)
        star.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._fav_star_btn = star
        is_fav = False
        checker = getattr(self, 'favorite_check', None)
        if callable(checker):
            try:
                is_fav = bool(checker(op))
            except Exception:
                is_fav = False
        self.set_favorite_star(is_fav)
        star.clicked.connect(self.favorite_toggle_requested.emit)
        title_row.addWidget(star)

        unit_lbl = QLabel("(mm)")
        unit_lbl.setStyleSheet("color: #6c7086; font-size: 11px;")
        title_row.addWidget(unit_lbl)

        # Prog ext: bouton Parcourir sur la ligne du titre, à droite
        # du label de l'opération (câblé en fin de load_operation)
        self._title_browse_btn = None
        if op.operation_type in ("appel_programme",
                                 "import_programme"):
            # Opé liée à un programme outil: bouton ▶ relancer
            tp_name = str(op.params.get('tool_program', '') or '')
            if tp_name:
                lb = QPushButton(f"▶ {tp_name}")
                lb.setMaximumHeight(24)
                lb.setCursor(Qt.CursorShape.PointingHandCursor)
                lb.setToolTip(
                    f"Relancer le programme outil « {tp_name} »")
                lb.setStyleSheet(
                    "QPushButton { background: #94e2d5; color: #1e1e2e; "
                    "font-weight: bold; padding: 2px 10px; "
                    "border-radius: 4px; font-size: 11px; }"
                    "QPushButton:hover { background: #b5ede2; }")
                lb.clicked.connect(
                    lambda _=False, n=tp_name:
                    self._launch_tool_program_by_name(n))
                title_row.addWidget(lb)
            tb = QPushButton("📂 Parcourir")
            tb.setMaximumHeight(24)
            tb.setCursor(Qt.CursorShape.PointingHandCursor)
            tb.setToolTip(
                "Sélectionner le fichier .SimPl à importer"
                if op.operation_type == "import_programme"
                else "Sélectionner le fichier .SimPl à appeler")
            tb.setStyleSheet(
                "QPushButton { background: #a6e3a1; color: #1e1e2e; "
                "font-weight: bold; padding: 2px 10px; "
                "border-radius: 4px; font-size: 11px; }"
                "QPushButton:hover { background: #c6f0c1; }")
            title_row.addWidget(tb)
            self._title_browse_btn = tb

        title_container = QWidget()
        title_container.setLayout(title_row)
        self._layout.addWidget(title_container)

        # (« Opé → dessin » est en FIN de formulaire)

        # BPM: afficher le mode (Type) AVANT le sélecteur d'outil
        if op.operation_type == "bpm":
            type_pdefs = [
                p for p in op_class.get_parameters()
                if p.group == "Type"
                and (not p.expert_only or self._expert_mode)]
            if type_pdefs:
                type_box = QGroupBox("Type")
                tf = QFormLayout()
                tf.setSpacing(4)
                tf.setContentsMargins(4, 8, 4, 4)
                for tpdef in type_pdefs:
                    tw = self._create_param_widget(tpdef, op.params)
                    self._widgets[tpdef.key] = tw
                    self._bpm_labels[tpdef.key] = QLabel(tpdef.label)
                    tf.addRow(self._bpm_labels[tpdef.key], tw)
                    # Connecter le mode BPM
                    if tpdef.key == "bpm_mode":
                        tw.currentTextChanged.disconnect()
                        tw.currentTextChanged.connect(
                            self._on_bpm_mode_changed)
                type_box.setLayout(tf)
                self._layout.addWidget(type_box)

        # Bloc SimPl importé: son outil ouvre le formulaire — c'est lui
        # qui commande régime et avances, tout le reste en découle
        if op.operation_type == "bloc_simpl":
            self._build_bloc_tool_selector(op)

        # Sélecteur d'outil
        if op_class.REQUIRES_TOOL:
            self._add_tool_selector(op, op_class)

        # Multi-point ops: Pz est dans le tableau → exclure "depth" du groupe
        # Profondeur (garder seulement infeed_z / Passe Z si présent)
        _depth_prebuilt = False
        _is_multipoint = getattr(op_class, 'SUPPORTS_MULTI_POINT', False)
        if _is_multipoint:
            # Pour les ops multi-point, "depth" est redondant (Pz par point)
            _depth_pdefs = [
                p for p in op_class.get_parameters()
                if p.group == "Profondeur" and p.key != "depth"
                and (not p.expert_only or self._expert_mode)]
            if _depth_pdefs:
                _depth_prebuilt = True
                depth_box = QGroupBox("Profondeur")
                dg = QGridLayout()
                dg.setSpacing(4)
                dg.setContentsMargins(4, 8, 4, 4)
                for di, dpdef in enumerate(_depth_pdefs):
                    dw = self._create_param_widget(dpdef, op.params)
                    self._widgets[dpdef.key] = dw
                    dl = QLabel(dpdef.label)
                    dl.setMaximumWidth(110)
                    dg.addWidget(dl, 0, di * 2)
                    dg.addWidget(dw, 0, di * 2 + 1)
                depth_box.setLayout(dg)
                self._layout.addWidget(depth_box)
            else:
                # Taraudage: aucun champ hors depth → skip entièrement
                _depth_prebuilt = True

        # Tracé: la forme se choisit en boutons, avant tout le reste
        if op.operation_type == "trace":
            self._build_trace_shape_buttons(op)

        # BPM: paramètres (Mode BPM) AVANT coordonnées pour que le mode soit 1er
        # Autres ops: coordonnées avant paramètres (comportement classique)
        if op.operation_type != "bpm":
            # Coordonnées X/Y (Z=15 non-éditable)
            if op_class.REQUIRES_COORDINATES:
                self._add_coordinate_fields(op)

        # Paramètres de l'opération, groupés
        params = op_class.get_parameters()
        groups: Dict[str, list] = {}
        for pdef in params:
            g = pdef.group or "Général"
            if g not in groups:
                groups[g] = []
            groups[g].append(pdef)

        self._pattern_widgets = []  # widgets du groupe Pattern à afficher/masquer
        self._pattern_rect_widgets = []  # Rectangle pattern widgets
        self._pattern_circle_widgets = []  # Circle pattern widgets
        self._pattern_linear_widgets = []  # Linear pattern widgets
        self._entraxe_widgets = []  # widgets du groupe Entraxe (hors checkbox)
        is_bpm = (op.operation_type == "bpm")

        # Tracé: chaque forme n'affiche que SES champs — les boutons
        # de forme remplacent le combo
        trace_drop = set()
        if op.operation_type == "trace":
            from src.operations.trace import Trace
            shape = str(op.params.get('shape', 'Rectangle'))
            for fields in Trace.SHAPE_FIELDS.values():
                trace_drop |= set(fields)
            trace_drop -= set(Trace.SHAPE_FIELDS.get(shape, ()))
            trace_drop.add('shape')
            if shape == "Spirale":
                # Une spirale n'est pas fermée: rien à décaler
                trace_drop |= {'offset_side', 'offset_dist'}
            elif shape == "Texte":
                # des traits ouverts, suivis par le centre de l'outil
                trace_drop |= {'offset_side', 'offset_dist', 'closed',
                               'cote_outil', 'surepaisseur_xy'}

        # Ordonner les groupes selon le type d'opération
        if is_bpm:
            priority_order = [
                "Type", "Entraxe", "Profondeur", "Dimensions",
                "Finition", "Lamage", "Taraudage", "Acier", "Pattern"]
        else:
            # Ordre demandé: Tool - toolSpec - Position - Dimension,
            # puis le reste (Profondeur, Finition...)
            priority_order = ["Dimensions", "Profondeur", "Finition", "Taraudage"]
        ordered_groups = []
        for pg in priority_order:
            if pg in groups:
                ordered_groups.append((pg, groups[pg]))
        for gn, pdefs in groups.items():
            if gn not in priority_order:
                ordered_groups.append((gn, pdefs))

        for group_name, pdefs in ordered_groups:
            # Taraudage: Profondeur déjà construit au-dessus du tableau
            if _depth_prebuilt and group_name == "Profondeur":
                continue
            # Ébavurage: UNE section, construite à part (case, outil,
            # profondeur) — le groupe généré la doublait
            if op.operation_type in self.OPS_EBAVURAGE \
                    and group_name == "Ébavurage":
                continue
            # BPM: Type déjà construit au-dessus de l'outil
            if op.operation_type == "bpm" and group_name == "Type":
                continue
            # Séquence Datron: l'Échelle Z / l'Offset Z laissent la
            # place à l'éditeur de passes (construit plus bas)
            if (op.operation_type == "sequence_datron"
                    and group_name == "Profondeur"):
                continue
            # Filtrer les params expert_only en mode non-expert
            visible_pdefs = [
                p for p in pdefs
                if (not p.expert_only or self._expert_mode)
                and p.key not in trace_drop
            ]
            if not visible_pdefs:
                continue
            group_box = QGroupBox(group_name)
            self._boites_groupes[group_name] = group_box
            grid = QGridLayout()
            grid.setSpacing(4)
            grid.setContentsMargins(4, 8, 4, 4)
            col = 0
            row = 0
            for pdef in visible_pdefs:
                widget = self._create_param_widget(pdef, op.params)
                self._widgets[pdef.key] = widget
                # Label: no (mm) unless special unit
                label_text = pdef.label
                if pdef.unit and pdef.unit != "mm":
                    label_text += f" ({pdef.unit})"
                label = QLabel(label_text)
                label.setMaximumWidth(110)
                if pdef.tooltip:
                    label.setToolTip(pdef.tooltip)
                    widget.setToolTip(pdef.tooltip)
                # Filepath: pleine largeur
                if pdef.key == "filepath":
                    if col != 0:
                        col = 0
                        row += 1
                    grid.addWidget(label, row, 0, 1, 4)
                    row += 1
                    grid.addWidget(widget, row, 0, 1, 4)
                    row += 1
                    # BPM label tracking
                    if is_bpm:
                        self._bpm_labels[pdef.key] = label
                    continue
                # Un texte à graver, une police: la ligne entière —
                # coincé à côté d'un autre champ, on n'en voyait que
                # trois lettres
                if pdef.key in ("texte", "police"):
                    if col != 0:
                        col = 0
                        row += 1
                    grid.addWidget(label, row, 0)
                    grid.addWidget(widget, row, 1, 1, 3)
                    row += 1
                    continue
                # Pattern fields: grille compacte 2 par ligne
                # (NbX|PasX, NbY|PasY)
                is_pattern_field = (
                    group_name == "Pattern" and pdef.key not in (
                        "use_pattern", "pattern_type"))
                if is_pattern_field:
                    # 2 champs par ligne (col0=label, col1=edit, col2=label, col3=edit)
                    grid.addWidget(label, row, col * 2)
                    grid.addWidget(widget, row, col * 2 + 1)
                    col += 1
                    if col >= 2:
                        col = 0
                        row += 1
                elif group_name == "Répétition":
                    # Même layout compact pour Répétition (NbX|PasX, NbY|PasY)
                    grid.addWidget(label, row, col * 2)
                    grid.addWidget(widget, row, col * 2 + 1)
                    col += 1
                    if col >= 2:
                        col = 0
                        row += 1
                else:
                    grid.addWidget(label, row, col * 2)
                    grid.addWidget(widget, row, col * 2 + 1)
                    col += 1
                    if col >= 2:
                        col = 0
                        row += 1
                # Pattern : masquer les champs sauf la checkbox et le type
                if group_name == "Pattern" and pdef.key not in (
                        "use_pattern", "pattern_type"):
                    self._pattern_widgets.extend([label, widget])
                    # Classer par sous-type
                    if pdef.key in ('x_count', 'y_count', 'delta_x', 'delta_y'):
                        self._pattern_rect_widgets.extend([label, widget])
                    elif pdef.key in ('circle_count', 'circle_radius',
                                      'circle_start_angle'):
                        self._pattern_circle_widgets.extend([label, widget])
                    elif pdef.key in ('linear_count', 'linear_delta',
                                      'linear_angle'):
                        self._pattern_linear_widgets.extend([label, widget])
                if group_name == "Pattern" and pdef.key == "pattern_type":
                    self._pattern_widgets.extend([label, widget])
                # Entraxe : pour BPM, toujours visible (pas de checkbox)
                if group_name == "Entraxe" and pdef.key == "use_entraxe":
                    self._entraxe_widgets.extend([label, widget])
                # BPM: mémoriser les labels pour mode toggling
                if is_bpm:
                    self._bpm_labels[pdef.key] = label
            if col != 0:
                row += 1
            if group_name == "Répétition" and (
                    self._prend_un_rectangle(op)
                    or self._prend_un_cercle(op)):
                # l'offset XY: des instances emboîtées, chacune plus
                # large de deux fois l'offset (10 × 10, offset 6:
                # 22 × 22, 34 × 34, 46 × 46…)
                row = self._ajouter_offset_repetition(grid, row)
            group_box.setLayout(grid)
            self._layout.addWidget(group_box)

            # Si c'est le groupe Pattern, styling amélioré et masquer par défaut
            if group_name == "Pattern":
                # Champs user plus larges, un peu plus haut, police bold
                for w in self._pattern_widgets:
                    if isinstance(w, QLabel):
                        f = w.font()
                        f.setBold(True)
                        w.setFont(f)
                        w.setMinimumWidth(80)
                    elif isinstance(w, (CalcLineEdit, CalcIntLineEdit, QLineEdit)):
                        w.setMinimumHeight(28)
                        w.setMinimumWidth(90)
                        w.setMaximumWidth(120)
                    elif isinstance(w, NoScrollComboBox):
                        w.setMinimumHeight(28)
                # Forcer layout 1 champ par ligne pour alignement vertical
                grid.setColumnStretch(0, 1)
                grid.setColumnStretch(1, 2)
                grid.setColumnStretch(2, 0)
                grid.setColumnStretch(3, 0)
                self._pattern_group = group_box
                use_pat = op.params.get('use_pattern', False)
                for w in self._pattern_widgets:
                    w.setVisible(use_pat)
                # Appliquer la visibilité par sous-type de pattern
                if use_pat:
                    self._apply_pattern_type_visibility(
                        op.params.get('pattern_type', 'Rectangle'))
                # Connecter la checkbox use_pattern
                if 'use_pattern' in self._widgets:
                    cb = self._widgets['use_pattern']
                    if isinstance(cb, QCheckBox):
                        cb.toggled.connect(self._on_pattern_toggled)
                # Connecter le combo pattern_type
                if 'pattern_type' in self._widgets:
                    pt_combo = self._widgets['pattern_type']
                    if isinstance(pt_combo, NoScrollComboBox):
                        pt_combo.currentTextChanged.connect(
                            self._on_pattern_type_changed)

            # Entraxe: pour BPM, toujours visible (pas de checkbox)
            # Pour d'autres ops avec use_entraxe, toggle classique
            if group_name == "Entraxe":
                if 'use_entraxe' in self._widgets:
                    use_ent = op.params.get('use_entraxe', False)
                    for w in self._entraxe_widgets:
                        w.setVisible(use_ent)
                    cb = self._widgets['use_entraxe']
                    if isinstance(cb, QCheckBox):
                        cb.toggled.connect(self._on_entraxe_toggled)

        # (« Instances similaires » a été retiré du formulaire: les
        # instances sont désormais les membres d'un ENSEMBLE, avec
        # chacune son formulaire complet. Les programmes existants
        # gardent leur paramètre `instances`, toujours généré.)

        # Palpage: tailles de brut enregistrées
        if op.operation_type in ("palpage_rectangle",
                                 "retournement_piece"):
            self._build_probe_presets(op)

        # Appel prog externe: bouton d'import à côté de l'aperçu
        if op.operation_type == "appel_programme":
            self._add_import_button_near_preview(op)

        # Tracé: choix de la forme en boutons, puis reprise d'un
        # contour du dessin
        if op.operation_type == "trace":
            self._build_trace_pickup_section(op)

        # Séquence Datron: éditeur de passes (remplace Échelle/Offset Z)
        if op.operation_type == "sequence_datron":
            self._add_sequence_passes(op)
            self._add_sequence_sim3d(op)
        # Bloc importé qui appelle une séquence $$$ (FAO DATRON): la
        # même simulation 3D, de la séquence telle qu'il l'écrira
        if op.operation_type == "bloc_simpl":
            self._add_sequence_sim3d(op)

        # Relief: le cadre se donne par une marge OU par des
        # dimensions — le formulaire n'offre que l'un des deux
        if 'cadre_mode' in self._widgets:
            for cle in ('cadre_mode', 'mode'):
                widget = self._widgets.get(cle)
                if widget is not None and hasattr(widget,
                                                  'currentTextChanged'):
                    widget.currentTextChanged.connect(
                        lambda _t: self._maj_champs_cadre())
            self._maj_champs_cadre()

        # Parcours de gravure et tête de gamme: les contours du
        # dessin, et ce que le calcul en tire
        if op.operation_type in ("gravure_2d5", "evidement_2d5",
                                 "contour_2d5", "gamme_gravure",
                                 "texte_grave"):
            self._build_contours_section(op)
        # La gamme: son tableau récapitulatif, à éditer en place
        if op.operation_type == "gamme_gravure":
            self._build_gamme_section(op)
        # L'ébavurage: ses modèles, sa géométrie
        if op.operation_type == "ebavurage":
            self._build_ebavurage_section(op)

        # (Le cadre des instances de l'ensemble a été retiré: monter,
        # descendre et supprimer se font dans la LISTE d'opérations,
        # qui montre déjà l'ordre réel — deux commandes pour le même
        # geste, dont une sans le contexte.)

        # Bloc SimPl importé: fiche d'identité du sous-programme
        if op.operation_type == "bloc_simpl":
            self._build_bloc_simpl_summary(op)

        # Saisie opérateur: table des champs du dialogue
        if op.operation_type == "parametres_operateur":
            self._build_operator_fields_section(op)
        else:
            # Autres opérations: lier des cotes à ces variables
            self._build_variable_binding_section(op)

        # BPM: coordonnées APRÈS paramètres (Mode BPM visible en premier)
        if is_bpm and op_class.REQUIRES_COORDINATES:
            self._add_coordinate_fields(op)

        # BPM: connecter le mode combo
        if is_bpm and 'bpm_mode' in self._widgets:
            mode_combo = self._widgets['bpm_mode']
            if isinstance(mode_combo, NoScrollComboBox):
                mode_combo.currentTextChanged.connect(
                    self._on_bpm_mode_changed)

        # Section pour Décalage Origine: bouton retour + explication
        # (aller-retour: mode EXPERT uniquement)
        if op.operation_type == "decalage_origine" and self._expert_mode:
            ret_btn = QPushButton("Créer opération retour")
            ret_btn.setToolTip(
                "Crée une nouvelle opération avec le décalage opposé")
            ret_btn.setStyleSheet(
                "QPushButton { background-color: #74c7ec; color: #1e1e2e; "
                "font-weight: bold; padding: 6px 12px; }"
                "QPushButton:hover { background-color: #89dceb; }")
            ret_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            ret_btn.clicked.connect(self._on_create_return_shift)
            self._layout.addWidget(ret_btn)

            help_group = QGroupBox("Comment ça marche")
            help_group.setStyleSheet(
                "QGroupBox { font-weight: bold; color: #74c7ec; "
                "font-size: 12px; border: 1px solid #45475a; "
                "border-radius: 4px; margin-top: 6px; padding-top: 12px; }"
                "QGroupBox::title { subcontrol-origin: margin; "
                "padding: 0 6px; }")
            help_layout = QVBoxLayout()
            help_text = QLabel(
                "Le décalage origine déplace le point zéro de la machine.\n\n"
                "\u2022 X positif \u2192 décalage vers la droite\n"
                "\u2022 Y positif \u2192 décalage vers l'arrière\n"
                "\u2022 Z positif \u2192 décalage vers le haut\n\n"
                "Utilisez le bouton ci-dessus pour créer\n"
                "automatiquement l'opération de retour inverse.")
            help_text.setWordWrap(True)
            help_text.setStyleSheet("color: #a6adc8; font-size: 11px;")
            help_layout.addWidget(help_text)
            help_group.setLayout(help_layout)
            self._layout.addWidget(help_group)

        # Taraudage brut: section ébavurage dédiée (checkbox + combo outil)
        if op.operation_type == "taraudage_brut":
            ebav_group = QGroupBox("Ébavurage")
            ebav_vbox = QVBoxLayout()
            ebav_vbox.setSpacing(4)
            ebav_vbox.setContentsMargins(4, 8, 4, 4)
            self._add_ebavurage_section(ebav_vbox, op)
            ebav_group.setLayout(ebav_vbox)
            self._layout.addWidget(ebav_group)

        # Avertissement Pz
        self._depth_warning = QLabel("")
        self._depth_warning.setStyleSheet(
            "color: #f38ba8; font-size: 11px; font-weight: bold;")
        self._depth_warning.setWordWrap(True)
        self._depth_warning.setVisible(False)
        self._layout.addWidget(self._depth_warning)

        # Prog ext: câbler le bouton Parcourir du titre sur le champ
        # filepath (créé pendant la construction des groupes)
        if self._title_browse_btn is not None:
            fp_container = self._widgets.get('filepath')
            fp_edit = getattr(fp_container, '_line_edit', None)
            if fp_edit is not None:
                self._title_browse_btn.clicked.connect(
                    lambda _=False, e=fp_edit:
                    self._browse_simpl_file(e))
            else:
                self._title_browse_btn.setVisible(False)

        # « Opé → dessin », en fin de formulaire: le contour de l'opé
        # et le trajet de l'outil, sur deux calques du dessin (où on
        # les déplace, les met à la cote, les exporte en DXF). Même
        # geste qu'au clic droit de la liste.
        self._btn_ope_dessin = None
        if not getattr(op_class, 'HORS_MATIERE', False):
            btn_dessin = QPushButton(" Opé → dessin")
            try:
                from src.gui.icons import get_button_icon
                btn_dessin.setIcon(get_button_icon("dxf", 15))
            except Exception:
                pass
            btn_dessin.setMinimumHeight(26)
            btn_dessin.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn_dessin.setToolTip(
                "Pose sur le calque Dessin le CONTOUR de cette opération "
                "(calque OPE_…) et le TRAJET de l'outil (calque "
                "PARCOURS_…) — pour les déplacer, les mettre à la cote "
                "ou les exporter en DXF.")
            btn_dessin.clicked.connect(self.ope_vers_dessin_demandee.emit)
            self._layout.addWidget(btn_dessin)
            self._btn_ope_dessin = btn_dessin

        self._layout.addStretch()
        self._suppressing_signals = False

        # BPM: appliquer la visibilité initiale du mode
        # Suppression temporaire des signaux pour éviter les cascades
        if is_bpm and 'bpm_mode' in self._widgets:
            mode_combo = self._widgets['bpm_mode']
            if isinstance(mode_combo, NoScrollComboBox):
                self._suppressing_signals = True
                self._apply_bpm_mode_visibility(mode_combo.currentText())
                self._suppressing_signals = False

        # Validate depth on load
        self._validate_depth()
        self._maj_groupes_selon()

        # Si un outil par défaut est sélectionné mais non assigné, propager
        if (self._tool_combo and self._current_op
                and not self._current_op.tool_id):
            default_tid = self._tool_combo.currentData()
            if default_tid:
                params = self._collect_params()
                params['_tool_id'] = default_tid
                self.params_changed.emit(params)

        # ── Tab navigation: installer les filtres sur tous les champs ──
        self._install_tab_filters()

    # ──── Tab navigation inter-champs ────

    def _install_tab_filters(self):
        """Collecte tous les champs éditables et installe le filtre Tab."""
        self._form_fields = []
        self._collect_fields_from_layout(self._layout, self._form_fields)
        for w in self._form_fields:
            w.installEventFilter(self)

    def _collect_fields_from_layout(self, layout, fields):
        """Parcourt un layout récursivement pour trouver les champs éditables
        dans leur ordre visuel. Ignore les enfants de DathreadPointsWidget."""
        if not layout:
            return
        for i in range(layout.count()):
            item = layout.itemAt(i)
            widget = item.widget()
            nested = item.layout()
            if widget:
                if isinstance(widget, DathreadPointsWidget):
                    continue  # gère son propre Tab
                if isinstance(widget, (CalcLineEdit, CalcIntLineEdit)):
                    fields.append(widget)
                elif isinstance(widget, QLineEdit):
                    fields.append(widget)
                elif isinstance(widget, NoScrollComboBox):
                    fields.append(widget)
                elif isinstance(widget, (QAbstractSpinBox, QCheckBox)):
                    # un champ, pas un conteneur: le ranger en NoFocus
                    # rendait les SpinCote du formulaire (Offset XY,
                    # × n) impossibles à saisir — le clic ne leur
                    # donnait jamais le clavier
                    fields.append(widget)
                else:
                    # Conteneur: QGroupBox, QWidget… récurser
                    widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                    child_layout = widget.layout()
                    if child_layout:
                        self._collect_fields_from_layout(
                            child_layout, fields)
            elif nested:
                self._collect_fields_from_layout(nested, fields)

    def eventFilter(self, obj, event):
        """Intercepte Tab/Shift-Tab pour naviguer entre les champs du formulaire.
        Tab ne met PAS à jour le SimPl sauf depuis le dernier champ.
        Enter dans n'importe quel champ déclenche la MAJ via editingFinished.
        """
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
                fields = self._form_fields
                if not fields:
                    return False
                try:
                    idx = fields.index(obj)
                except ValueError:
                    return False
                if key == Qt.Key.Key_Tab:
                    nxt = (idx + 1) % len(fields)
                    is_last = (idx == len(fields) - 1)
                else:
                    nxt = (idx - 1) % len(fields)
                    is_last = (idx == 0)
                # Tab sur champ non-dernier : déplacer sans MAJ SimPl
                if not is_last:
                    self._suppressing_signals = True
                # Déplacer le focus (editingFinished se déclenche
                # automatiquement sur perte de focus → valide la valeur)
                fields[nxt].setFocus()
                if hasattr(fields[nxt], 'selectAll'):
                    QTimer.singleShot(0, fields[nxt].selectAll)
                if not is_last:
                    QTimer.singleShot(0, self._unsuppress_tab)
                return True  # Consommer l'événement Tab
        return super().eventFilter(obj, event)

    def _unsuppress_tab(self):
        """Restaure l'émission params_changed après un Tab intermédiaire."""
        self._suppressing_signals = False

    def _add_tool_selector(self, op: OperationInstance, op_class: type):
        group = QGroupBox("Outil")
        layout = QVBoxLayout()
        layout.setSpacing(2)
        layout.setContentsMargins(4, 8, 4, 4)

        self._tool_combo = NoScrollComboBox()
        req = op_class.get_tool_requirement()

        if self._tool_library:
            # Le choix de la fraise appartient au fraiseur: la liste
            # blanche par opération cachait des outils parfaitement
            # utilisables. Seuls les usinages qui EXIGENT un outil
            # d'une famille (taraudage, gravure...) restent filtrés,
            # et uniquement hors mode expert.
            familles_libres = op.operation_type in (
                "decoupe_rectangle", "decoupe_cercle", "poche_rectangle",
                "surfacage_rectangle", "surfacage_cercle", "contour",
                "trace", "poche_cercle")
            tool_types = ([] if (self._expert_mode or familles_libres)
                          else req.tool_types)
            compatible = self._tool_library.get_tools_for_operation(
                tool_types)
            if op.operation_type == "ebavurage":
                # extrad, chanfrein, conique — dans cet ordre; le
                # reste ensuite
                ranges = [(em_genre_rang(t), rang, tid, t) for rang,
                          (tid, t) in enumerate(compatible.items())]
                ranges.sort(key=lambda r: (r[0], r[1]))
                compatible = {tid: t for _g, _r, tid, t in ranges}
            self._tool_combo.addItem("-- Sélectionner --", "")
            selected_idx = 0
            default_article_idx = 0
            # Outil par défaut: d'abord depuis ParametersPanel, sinon hardcodé
            default_article = ""
            params_panel = getattr(self, '_params_panel', None)
            if params_panel and hasattr(params_panel, 'get_default_tool_article'):
                default_article = params_panel.get_default_tool_article(
                    op.operation_type)
            # Fallback hardcodé si pas de config user
            if not default_article:
                if op.operation_type in ("taraudage", "taraudage_brut"):
                    default_article = "0068420A"
                elif op.operation_type in (
                        "surfacage_rectangle", "surfacage_cercle"):
                    default_article = "0068443G"
            for i, (tid, tool) in enumerate(compatible.items()):
                self._tool_combo.addItem(tool.display_name, tid)
                if tid == op.tool_id:
                    selected_idx = i + 1
                # le PREMIER de l'article: la fiche de l'utilisateur,
                # pas son jumeau « avances DATRON » rangé après elle
                if (default_article
                        and tool.article_nr == default_article
                        and not op.tool_id and not default_article_idx):
                    default_article_idx = i + 1
            # Hors mode expert, une famille exigée filtre la liste: les
            # autres outils restent à UN clic (« + Autres outils » en
            # bas de liste) — et y sont d'emblée si l'opé en porte un
            self._autres_outils = {}
            if tool_types:
                self._autres_outils = {
                    tid: t for tid, t in self._tool_library.tools.items()
                    if tid not in compatible}
            if self._autres_outils:
                if op.tool_id in self._autres_outils:
                    selected_idx = self._deplier_autres_outils(
                        choisir=op.tool_id)
                else:
                    self._tool_combo.insertSeparator(
                        self._tool_combo.count())
                    self._tool_combo.addItem(
                        f"＋ Autres outils ({len(self._autres_outils)})",
                        self.AUTRES_OUTILS)
                    self._tool_combo.setItemData(
                        self._tool_combo.count() - 1,
                        "Les outils d'une autre famille (le mode expert "
                        "les montre toujours)", Qt.ItemDataRole.ToolTipRole)
            if selected_idx > 0:
                self._tool_combo.setCurrentIndex(selected_idx)
            elif default_article_idx > 0:
                self._tool_combo.setCurrentIndex(default_article_idx)
            else:
                self._tool_combo.setCurrentIndex(0)

        # Une liste haute: on voit d'un coup la bibliothèque (dix
        # lignes ne montraient qu'un quart des fraises)
        self._tool_combo.setMaxVisibleItems(self.LIGNES_LISTE_OUTILS)
        self._tool_combo.setStyleSheet("QComboBox { combobox-popup: 0; }")
        self._tool_index_avant = self._tool_combo.currentIndex()
        self._tool_combo.currentIndexChanged.connect(self._on_tool_changed)
        # La famille attendue reste une INDICATION (infobulle), pas une
        # ligne de texte: elle disait « Requis: fraise cylindrique »
        # au-dessus d'une liste qui propose tout.
        self._tool_combo.setToolTip(
            f"Outil de l'opération (indicatif : {req.description})"
            if req.description else "Outil de l'opération")
        # Liste deroulante large: les noms d'outils complets etaient
        # coupes, on ne distinguait plus deux references voisines
        vue = self._tool_combo.view()
        try:
            largeur = max(
                (self._tool_combo.fontMetrics().horizontalAdvance(
                    self._tool_combo.itemText(i)) + 40)
                for i in range(self._tool_combo.count()))
            vue.setMinimumWidth(min(560, max(240, largeur)))
        except ValueError:
            pass
        # Fermée, la liste prend la largeur DISPONIBLE, sans l'imposer:
        # réglée sur le nom d'outil le plus long, elle élargissait tout
        # le formulaire (barre de défilement horizontale dès que le
        # panneau était plus étroit). Le nom complet reste dans la
        # liste déroulée et dans l'infobulle.
        self._tool_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._tool_combo.setMinimumContentsLength(16)
        self._tool_combo.setToolTip(self._tool_combo.currentText())
        self._tool_combo.currentTextChanged.connect(
            self._tool_combo.setToolTip)
        layout.addWidget(self._tool_combo)

        # ── Specs outil par opération: Rpm + avances, UNE ligne
        # discrète masquée derrière un bouton poussoir ──
        tid = self._tool_combo.currentData()
        tool_obj = (self._tool_library.get_tool(tid)
                    if tid and self._tool_library else None)

        def _saved_int(key, default=0):
            try:
                return int(float(op.params.get(key, default) or 0))
            except (TypeError, ValueError):
                return 0

        has_overrides = bool(
            _saved_int('rpm_override')
            or any(_saved_int(f'feed_override_{k}')
                   for k in ('finishing', 'approach', 'plunge',
                             'ramp', 'roughing')))

        spec_btn = QPushButton("⚙ Rpm / Avances")
        spec_btn.setCheckable(True)
        spec_btn.setChecked(has_overrides)
        spec_btn.setToolTip(
            "Rpm et avances POUR CETTE OPÉRATION (pré-remplis avec "
            "l'outil; une valeur différente devient un override)")
        spec_btn.setStyleSheet(
            "QPushButton { background: #181825; color: #6c7086; "
            "border: 1px outset #313244; border-radius: 3px; "
            "padding: 2px 8px; font-size: 10px; text-align: left; }"
            "QPushButton:checked { background: #313244; "
            "color: #89b4fa; border: 1px inset #45475a; }"
            "QPushButton:hover { color: #cdd6f4; }")
        layout.addWidget(spec_btn)

        spec_widget = QWidget()
        spec_row = QHBoxLayout(spec_widget)
        spec_row.setContentsMargins(0, 2, 0, 0)
        spec_row.setSpacing(2)

        def _mini_label(text):
            ml = QLabel(text)
            ml.setStyleSheet(
                f"color: {COLORS['text_dim']}; font-size: 9px;")
            return ml

        spec_row.addWidget(_mini_label("Rpm"))
        self._rpm_override = CalcIntLineEdit(min_val=0, max_val=99999)
        self._rpm_override.setMaximumWidth(52)
        self._rpm_override.setFixedHeight(22)
        saved_rpm = _saved_int('rpm_override')
        self._rpm_override.setValue(
            saved_rpm if saved_rpm > 0
            else int(getattr(tool_obj, 'rpm', 0) or 0))
        self._rpm_override.editingFinished.connect(
            self._on_param_changed)
        spec_row.addWidget(self._rpm_override)

        self._feed_overrides = {}
        for key, label in [('finishing', 'Fin'), ('approach', 'App'),
                           ('plunge', 'Plg'), ('ramp', 'Rmp'),
                           ('roughing', 'Ébau')]:
            spec_row.addWidget(_mini_label(label))
            fe = CalcIntLineEdit(min_val=0, max_val=99999)
            fe.setMaximumWidth(46)
            fe.setFixedHeight(22)
            base = int(getattr(tool_obj, f'feed_{key}', 0) or 0) \
                if tool_obj else 0
            saved = _saved_int(f'feed_override_{key}')
            fe.setValue(saved if saved > 0 else base)
            fe.editingFinished.connect(self._on_param_changed)
            self._feed_overrides[key] = fe
            spec_row.addWidget(fe)
        spec_row.addStretch()

        spec_widget.setVisible(has_overrides)
        spec_btn.toggled.connect(spec_widget.setVisible)
        layout.addWidget(spec_widget)

        group.setLayout(layout)
        self._layout.addWidget(group)

    def _add_coordinate_fields(self, op: OperationInstance):
        # Vérifier si l'opération supporte multi-point
        try:
            op_class = OperationRegistry.get(op.operation_type)
            supports_multi = getattr(op_class, 'SUPPORTS_MULTI_POINT', False)
        except KeyError:
            supports_multi = False

        # BPM: toujours single-point (pas de tableau, entraxe gère les 2 centres)
        if op.operation_type == "bpm":
            self._is_multi_point = False
            self._add_single_point_fields(op)
        elif supports_multi and op.points:
            self._is_multi_point = True
            self._add_multi_point_fields(op)
        elif supports_multi:
            self._is_multi_point = True
            self._add_multi_point_fields(op)
        else:
            self._is_multi_point = False
            self._add_single_point_fields(op)

    def _add_single_point_fields(self, op: OperationInstance):
        group = QGroupBox("Position")
        grid = QGridLayout()
        grid.setSpacing(4)
        grid.setContentsMargins(4, 8, 4, 4)

        # X
        lbl_x = QLabel("X")
        lbl_x.setMaximumWidth(20)
        edit_x = CalcLineEdit(decimals=3, min_val=-9999.0,
                              max_val=9999.0, default=op.x)
        edit_x.editingFinished.connect(self._on_param_changed)
        self._coord_widgets['x'] = edit_x
        grid.addWidget(lbl_x, 0, 0)
        grid.addWidget(edit_x, 0, 1)

        # Y
        lbl_y = QLabel("Y")
        lbl_y.setMaximumWidth(20)
        edit_y = CalcLineEdit(decimals=3, min_val=-9999.0,
                              max_val=9999.0, default=op.y)
        edit_y.editingFinished.connect(self._on_param_changed)
        self._coord_widgets['y'] = edit_y
        grid.addWidget(lbl_y, 0, 2)
        grid.addWidget(edit_y, 0, 3)

        # Un rectangle du canvas remplit le tout: dimX, dimY, X, Y.
        # Plusieurs rectangles sélectionnés: une instance par
        # rectangle, à la suite.
        if self._prend_un_rectangle(op):
            from src.gui.icons import get_button_icon
            depuis = QPushButton("Depuis la\nsélection\ndu canvas")
            depuis.setIcon(get_button_icon("dxf", 15))
            depuis.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            depuis.setToolTip(
                "Remplit Largeur X, Largeur Y, X et Y avec le rectangle "
                "sélectionné au canvas (entité fermée, groupe, ou "
                "quatre traits).\nPlusieurs rectangles sélectionnés: "
                "celui-ci prend le premier, une opération identique "
                "est créée pour chacun des autres.\nLes réglages à côté "
                "valent pour toutes.")
            depuis.clicked.connect(self.rectangles_demandes.emit)
            grid.addWidget(self._rangee_selection(depuis, op, 'rects'),
                           2, 0, 1, 4)
            self._bouton_rectangles = depuis

        # Préremplissage: ensembles Pos/Dim/Pz déjà employés dans ce
        # programme-onglet (fournis par le panneau via prefill_provider)
        provider = getattr(self, 'prefill_provider', None)
        suggestions = []
        if callable(provider):
            try:
                suggestions = provider() or []
            except Exception:
                suggestions = []
        if suggestions:
            combo = NoScrollComboBox()
            combo.setStyleSheet("font-size: 10px; color: #94e2d5;")
            combo.addItem(
                "↪ Reprendre un rectangle du dessin ou un ensemble "
                "déjà employé…", None)
            for s in suggestions:
                combo.addItem(s['label'], s)
            combo.setToolTip(
                "Pré-remplit le formulaire: rectangles relevés sur le "
                "dessin (▭), puis ensembles PosX PosY dimX dimY Pz "
                "déjà employés dans ce programme")
            combo.currentIndexChanged.connect(
                lambda i, c=combo: self._apply_prefill(c, i))
            grid.addWidget(combo, 1, 0, 1, 4)

        group.setLayout(grid)
        self._layout.addWidget(group)

    #: « Offset XY »: (offset, nombre d'instances) — le panneau crée
    #: les instances emboîtées à la suite de l'opération courante
    instances_offset_demandees = Signal(float, int)

    def _ajouter_offset_repetition(self, grid, row: int) -> int:
        """La ligne « Offset XY … × n  [Créer les instances] » du
        groupe Répétition d'un rectangle ou d'un cercle. Rend la
        ligne suivante."""
        from src.gui.widgets import SpinEntier
        etiquette = QLabel("Offset XY")
        etiquette.setToolTip(
            "Des instances emboîtées: chacune est plus large et plus "
            "haute de DEUX fois l'offset que la précédente, même "
            "centre, rayon des coins agrandi de l'offset. Un "
            "rectangle 10 × 10 avec un offset de 6 donne 22 × 22, "
            "34 × 34, 46 × 46… Un cercle grandit de deux fois "
            "l'offset en diamètre.")
        self._offset_repet = SpinCote(decimales=2)
        self._offset_repet.setRange(0.0, 500.0)
        self._offset_repet.setValue(0.0)
        self._offset_repet.setToolTip(etiquette.toolTip())
        grid.addWidget(etiquette, row, 0)
        grid.addWidget(self._offset_repet, row, 1)
        fois = QLabel("× n")
        self._offset_n = SpinEntier()
        self._offset_n.setRange(1, 50)
        self._offset_n.setValue(1)
        self._offset_n.setToolTip("Nombre d'instances à créer")
        grid.addWidget(fois, row, 2)
        grid.addWidget(self._offset_n, row, 3)
        row += 1
        # ce que le bouton va faire, écrit au fur et à mesure de la
        # saisie: « → 22 × 22, 34 × 34, 46 × 46 »
        self._offset_apercu = QLabel("")
        self._offset_apercu.setWordWrap(True)
        self._offset_apercu.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 10px;")
        grid.addWidget(self._offset_apercu, row, 0, 1, 4)
        row += 1
        creer = QPushButton(" Créer les instances")
        creer.setMaximumHeight(24)
        creer.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        creer.setToolTip("Crée n copies emboîtées de cette opération, "
                         "à sa suite — une seule annulation.")
        creer.setEnabled(False)
        creer.clicked.connect(
            lambda: self.instances_offset_demandees.emit(
                float(self._offset_repet.value()),
                int(self._offset_n.value())))
        self._offset_bouton = creer
        self._offset_repet.valueChanged.connect(
            lambda _v: self._maj_apercu_offset())
        self._offset_n.valueChanged.connect(
            lambda _v: self._maj_apercu_offset())
        grid.addWidget(creer, row, 0, 1, 4)
        self._maj_apercu_offset()
        return row + 1

    def _maj_apercu_offset(self) -> None:
        """L'aperçu des instances emboîtées, et le bouton qui ne
        s'active qu'avec un offset."""
        op = self._current_op
        try:
            offset = float(self._offset_repet.value())
            n = int(self._offset_n.value())
        except RuntimeError:
            return
        if op is None or offset <= 0 or n <= 0:
            self._offset_apercu.setText(
                "Donnez un offset: chaque instance grandit de deux fois "
                "l'offset")
            self._offset_bouton.setEnabled(False)
            return
        tailles = instances_offset(op, offset, n)
        self._offset_apercu.setText("→ " + ", ".join(
            f"{t['width_x']:g} × {t['width_y']:g}" if 'width_x' in t
            else f"Ø {t['diameter']:g}" for t in tailles[:6])
            + (" …" if len(tailles) > 6 else ""))
        self._offset_bouton.setEnabled(True)

    @staticmethod
    def _prend_un_rectangle(op) -> bool:
        """Surfaçage, poche, découpe rectangle: ce que dimX et dimY
        décrivent."""
        try:
            from src.operations.registry import OperationRegistry
            cles = {p.key for p in
                    OperationRegistry.get(op.operation_type).get_parameters()}
        except Exception:
            return False
        return 'width_x' in cles and 'width_y' in cles

    @staticmethod
    def _prend_un_cercle(op) -> bool:
        """Surfaçage et découpe cercle: un diamètre, pas de points."""
        return getattr(op, 'operation_type', '') in (
            "decoupe_cercle", "surfacage_cercle", "poche_cercle")

    def _apply_prefill(self, combo, index: int):
        """Applique un ensemble Pos/Dim/Pz suggéré aux champs."""
        data = combo.itemData(index)
        if not data or self._suppressing_signals:
            return
        if 'x' in self._coord_widgets and data.get('x') is not None:
            self._coord_widgets['x'].setValue(float(data['x']))
        if 'y' in self._coord_widgets and data.get('y') is not None:
            self._coord_widgets['y'].setValue(float(data['y']))
        for key in ('width_x', 'width_y', 'diameter', 'depth',
                    'corner_radius'):
            val = data.get(key)
            w = self._widgets.get(key)
            if val is None or w is None:
                continue
            try:
                w.setValue(float(val))
            except (AttributeError, TypeError, ValueError):
                continue
        combo.blockSignals(True)
        combo.setCurrentIndex(0)
        combo.blockSignals(False)
        self._on_param_changed()

    def _bouton_centres_selection(self, vbox, op):
        """Ajoute « Depuis la sélection du canvas » en tête d'un groupe
        de points: reprend les centres sélectionnés (et le Ø d'un
        cercle pour un perçage). Comme pour les rectangles."""
        from src.gui.icons import get_button_icon
        avec_diam = op.operation_type in ("percage_foret", "percage_fraise")
        bulle = ("Remplit les points avec les CENTRES des entités "
                 "sélectionnées au canvas (cercles, croix, contours…).")
        if avec_diam:
            bulle += ("\nUn cercle donne aussi son Ø ; plusieurs Ø "
                      "différents créent une opération par diamètre.")
        depuis = QPushButton("Depuis la\nsélection\ndu canvas")
        depuis.setIcon(get_button_icon("dxf", 15))
        depuis.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        depuis.setToolTip(bulle + "\nLes réglages à côté valent pour "
                          "toutes les opérations créées.")
        depuis.clicked.connect(self.centres_demandes.emit)
        vbox.addWidget(self._rangee_selection(depuis, op, 'points'))
        self._bouton_centres = depuis

    #: ce que le mini formulaire garde d'une fois sur l'autre (ce qui
    #: n'est pas un paramètre de l'opération), par type d'opération
    _MEMOIRE_MINI: dict = {}
    _CLES_MEMOIRE = ('avant_trou', 'profondeur_avant_trou', 'grouper',
                     'offset')

    def _rangee_selection(self, bouton, op, quoi: str):
        """Le bouton « Depuis la sélection » et SES réglages, côte à
        côte: le bouton sur un tiers, le mini formulaire sur deux
        (profondeur, filet et avant-trou, offset, côté, ensemble…),
        prérempli de l'opération."""
        from PySide6.QtWidgets import QSizePolicy
        from src.operations import depuis_selection as ds
        from src.operations.registry import OperationRegistry
        from src.gui.dialogs.mini_formulaire import (ChampsFormulaire,
                                                     champs_communs)
        try:
            defauts = OperationRegistry.get(
                op.operation_type).get_default_params()
        except Exception:
            defauts = {}
        params = {**defauts, **(op.params or {})}
        champs = (ds.champs_points(op.operation_type, params)
                  if quoi == 'points'
                  else ds.champs_rectangles(op.operation_type, params))
        # l'ébavurage a SA section dans le formulaire: pas une
        # troisième case ici
        champs = [c for c in champs if c[0] != 'ebav']
        champs += champs_communs(op.group_name or op.name)
        mini = ChampsFormulaire(champs, compact=True)
        memoire = self._MEMOIRE_MINI.setdefault(op.operation_type, {})
        for cle, valeur in memoire.items():
            if mini.widget(cle) is not None:
                mini.regler(cle, valeur)

        def _retenir(cle):
            if cle in self._CLES_MEMOIRE:
                memoire[cle] = mini.valeurs()[cle]
        mini.change.connect(_retenir)
        rangee = QWidget()
        h = QHBoxLayout(rangee)
        h.setContentsMargins(0, 2, 0, 2)
        h.setSpacing(6)
        for w, part in ((bouton, 1), (mini, 2)):
            w.setSizePolicy(QSizePolicy.Policy.Ignored,
                            QSizePolicy.Policy.Preferred)
            h.addWidget(w, part)
        bouton.setSizePolicy(QSizePolicy.Policy.Ignored,
                             QSizePolicy.Policy.Expanding)
        self._mini_selection = mini
        return rangee

    def _add_multi_point_fields(self, op: OperationInstance):
        # Check if taraudage → use custom Dathread widget
        if op.operation_type == "taraudage":
            self._add_taraudage_fields(op)
            return

        # Perçage fraise/foret → patterns per-point (comme taraudage,
        # sans Type). Pattern::RectanglePattern est une fonction
        # MACHINE qui repositionne par SafeRapid: réservée à l'expert,
        # la répétition (nbX/pasX) lui est préférée. Les points qui en
        # portent DÉJÀ restent éditables, sinon les charger ici les
        # dégraderait en points simples — le programme changerait sans
        # le dire.
        _has_patterns = (
            op.operation_type in ("percage_fraise", "percage_foret")
            and (self._expert_mode
                 or any(pt.get('use_pattern') for pt in op.points)))

        group_title = "Points"
        if _has_patterns:
            group_title = "Points & Patterns"
        group = QGroupBox(group_title)
        vbox = QVBoxLayout()
        vbox.setSpacing(4)
        vbox.setContentsMargins(4, 8, 4, 4)

        self._bouton_centres_selection(vbox, op)

        # DathreadPointsWidget (perçage fraisé: un Ø par point)
        self._dathread_widget = DathreadPointsWidget(
            show_thread_type=False,
            show_patterns=_has_patterns,
            parent=self,
            show_diameter=op.operation_type == "percage_fraise")
        self._dathread_widget.diametres_actifs = bool(
            op.params.get('diametres_par_point'))
        self._dathread_widget.load_points(op.points)
        self._dathread_widget.points_changed.connect(
            self._on_dathread_points_changed)
        self._dathread_widget.point_focus_requested.connect(
            self.point_focus_requested.emit)
        vbox.addWidget(self._dathread_widget, stretch=1)

        # Ébavurage pour percage_foret / percage_fraise
        if op.operation_type in ("percage_foret", "percage_fraise"):
            self._add_ebavurage_section(vbox, op)

        group.setLayout(vbox)
        self._layout.addWidget(group)

    def _add_ebavurage_section(self, vbox, op: OperationInstance):
        """Section ébavurage réutilisable (taraudage, percage_foret, percage_fraise)."""
        ebav_row = QHBoxLayout()
        ebav_row.setSpacing(4)
        self._ebav_cb = QCheckBox("Ébavurage")
        self._ebav_cb.setChecked(op.params.get('use_ebav', False))
        self._ebav_cb.toggled.connect(self._on_ebav_toggled)
        ebav_row.addWidget(self._ebav_cb)

        self._ebav_tool_combo = NoScrollComboBox()
        self._ebav_tool_combo.setMinimumWidth(250)
        self._populate_ebav_tools(op.params.get('ebav_tool_id', ''))
        self._ebav_tool_combo.currentIndexChanged.connect(
            self._on_param_changed)
        ebav_row.addWidget(self._ebav_tool_combo)
        # la profondeur du Drill d'ébavurage (0: automatique)
        self._ebav_pz_label = QLabel("Pz")
        self._ebav_pz = SpinCote(decimales=3)
        self._ebav_pz.setRange(0.0, 50.0)
        self._ebav_pz.setSpecialValueText("auto")
        self._ebav_pz.setSuffix(" mm")
        self._ebav_pz.setMaximumWidth(90)
        try:
            self._ebav_pz.setValue(float(
                op.params.get('ebav_profondeur', 0.0) or 0.0))
        except (TypeError, ValueError):
            self._ebav_pz.setValue(0.0)
        self._ebav_pz.setToolTip(
            "Profondeur du Drill d'ébavurage. « auto » (0): la moitié du "
            "Ø + l'offset d'ébavurage.")
        self._ebav_pz.valueChanged.connect(self._on_ebav_pz)
        ebav_row.addWidget(self._ebav_pz_label)
        ebav_row.addWidget(self._ebav_pz)
        ebav_row.addStretch()
        vbox.addLayout(ebav_row)

        # Visibilité initiale
        self._ebav_tool_combo.setVisible(self._ebav_cb.isChecked())
        self._ebav_pz.setVisible(self._ebav_cb.isChecked())
        self._ebav_pz_label.setVisible(self._ebav_cb.isChecked())

    def _refresh_points_table(self, points):
        """Met à jour le tableau des points avec hauteur dynamique."""
        if not self._multi_point_table:
            return
        self._multi_point_table.blockSignals(True)
        self._multi_point_table.setRowCount(len(points))
        for i, pt in enumerate(points):
            # # (non-éditable)
            idx_item = QTableWidgetItem(str(i + 1))
            idx_item.setFlags(idx_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._multi_point_table.setItem(i, 0, idx_item)
            # X (éditable)
            x_item = QTableWidgetItem(f"{pt.get('x', 0):.3f}")
            self._multi_point_table.setItem(i, 1, x_item)
            # Y (éditable)
            y_item = QTableWidgetItem(f"{pt.get('y', 0):.3f}")
            self._multi_point_table.setItem(i, 2, y_item)
            # Pz (éditable) — profondeur individuelle
            depth = pt.get('depth', '')
            pz_item = QTableWidgetItem(
                f"{depth:.2f}" if isinstance(depth, (int, float)) else "")
            self._multi_point_table.setItem(i, 3, pz_item)
        self._multi_point_table.blockSignals(False)

        # Hauteur dynamique: ajustée au contenu, min 80px
        row_h = self._multi_point_table.verticalHeader().defaultSectionSize()
        header_h = self._multi_point_table.horizontalHeader().height()
        desired = header_h + row_h * max(len(points), 2) + 4
        self._multi_point_table.setMinimumHeight(min(desired, 400))

        try:
            if self._points_info is not None:
                self._points_info.setText(f"{len(points)} point(s)")
        except RuntimeError:
            pass  # Widget C++ déjà supprimé

    def _on_import_csv(self):
        """Importe des points depuis un CSV (X;Y ou X,Y par ligne)."""
        if not self._current_op:
            return
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Importer des points CSV",
            "", "Fichiers CSV (*.csv *.txt);;Tous (*)")
        if not filepath:
            return
        try:
            with open(filepath, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    # Support ; or , separator
                    parts = line.replace(',', ';').split(';')
                    if len(parts) >= 2:
                        try:
                            x = float(parts[0].strip())
                            y = float(parts[1].strip())
                            self._current_op.points.append(
                                {'x': x, 'y': y})
                        except ValueError:
                            continue
            self._refresh_points_table(self._current_op.points)
            self._on_param_changed()
        except Exception:
            pass

    # ──── Taraudage: table spécialisée ────

    def _add_taraudage_fields(self, op: OperationInstance):
        """Crée les champs taraudage Dathread: points + patterns."""
        group = QGroupBox("Points taraudage")
        vbox = QVBoxLayout()
        vbox.setSpacing(4)
        vbox.setContentsMargins(4, 8, 4, 4)

        self._bouton_centres_selection(vbox, op)

        # DathreadPointsWidget (taraudage: X, Y, Type, Pz + patterns)
        # Patterns par point: expert, ou déjà présents (voir
        # _add_multi_point_fields)
        show_pat = (self._expert_mode
                    or any(pt.get('use_pattern') for pt in op.points))
        self._dathread_widget = DathreadPointsWidget(
            show_thread_type=True, show_patterns=show_pat, parent=self)
        self._dathread_widget.load_points(op.points)
        self._dathread_widget.points_changed.connect(
            self._on_dathread_points_changed)
        self._dathread_widget.point_focus_requested.connect(
            self.point_focus_requested.emit)
        vbox.addWidget(self._dathread_widget, stretch=1)

        # ── Ébavurage ──
        self._add_ebavurage_section(vbox, op)

        group.setLayout(vbox)
        self._layout.addWidget(group)

    def _refresh_taraudage_table(self, points):
        """Reconstruit le tableau taraudage avec sous-rangées pattern."""
        tbl = self._taraudage_table
        if not tbl:
            return
        tbl.blockSignals(True)
        tbl.setRowCount(0)

        visual_row = 0
        for i, pt in enumerate(points):
            tbl.insertRow(visual_row)

            # # (non-editable)
            idx_item = QTableWidgetItem(str(i + 1))
            idx_item.setFlags(idx_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            idx_item.setData(Qt.ItemDataRole.UserRole, "main")
            idx_item.setData(Qt.ItemDataRole.UserRole + 1, i)  # point index
            tbl.setItem(visual_row, _TAR_COL_IDX, idx_item)

            # X
            x_item = QTableWidgetItem(f"{pt.get('x', 0.0):.3f}")
            tbl.setItem(visual_row, _TAR_COL_X, x_item)

            # Y
            y_item = QTableWidgetItem(f"{pt.get('y', 0.0):.3f}")
            tbl.setItem(visual_row, _TAR_COL_Y, y_item)

            # Type (combo delegate handles editing)
            type_item = QTableWidgetItem(pt.get('thread_type', 'M3'))
            tbl.setItem(visual_row, _TAR_COL_TYPE, type_item)

            # Pz (éditable — l'utilisateur saisit la profondeur)
            pz_val = pt.get('depth', '')
            if isinstance(pz_val, (int, float)) and pz_val > 0:
                pz_item = QTableWidgetItem(f"{pz_val:.2f}")
            else:
                pz_item = QTableWidgetItem("")
            tbl.setItem(visual_row, _TAR_COL_PZ, pz_item)

            # Pat. checkbox — contraste amélioré
            pat_item = QTableWidgetItem()
            pat_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            is_pat = pt.get('use_pattern', False)
            pat_item.setCheckState(
                Qt.CheckState.Checked if is_pat
                else Qt.CheckState.Unchecked)
            if is_pat:
                pat_item.setBackground(QColor("#2a4a2a"))  # vert discret
            tbl.setItem(visual_row, _TAR_COL_PAT, pat_item)

            # Delete button
            del_item = QTableWidgetItem("\u00d7")
            del_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            del_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            tbl.setItem(visual_row, _TAR_COL_DEL, del_item)

            visual_row += 1

            # Sous-rangée pattern si cochée
            if pt.get('use_pattern', False):
                visual_row = self._insert_pattern_subrow(
                    tbl, visual_row, pt, i)

        # ── Détection de collisions ──
        import math
        collision_indices = set()
        n = len(points)
        for i in range(n):
            for j in range(i + 1, n):
                dx = points[i].get('x', 0) - points[j].get('x', 0)
                dy = points[i].get('y', 0) - points[j].get('y', 0)
                dist = math.sqrt(dx * dx + dy * dy)
                d_i = _THREAD_DIAMETER.get(
                    points[i].get('thread_type', 'M3'), 3.0)
                d_j = _THREAD_DIAMETER.get(
                    points[j].get('thread_type', 'M3'), 3.0)
                min_dist = (d_i + d_j) / 2.0  # moyenne des 2 diamètres
                if dist < min_dist:
                    collision_indices.add(i)
                    collision_indices.add(j)

        # Colorier les rangées en collision en orange foncé
        if collision_indices:
            # Mapper point_index → visual_row
            for visual_r in range(tbl.rowCount()):
                idx_item = tbl.item(visual_r, _TAR_COL_IDX)
                if not idx_item:
                    continue
                row_type = idx_item.data(Qt.ItemDataRole.UserRole)
                if row_type != "main":
                    continue
                pt_idx = idx_item.data(Qt.ItemDataRole.UserRole + 1)
                if pt_idx in collision_indices:
                    for c in range(_TAR_COLS):
                        cell = tbl.item(visual_r, c)
                        if cell:
                            cell.setBackground(_COLLISION_BG)

        tbl.blockSignals(False)

        # Hauteur dynamique
        row_h = tbl.verticalHeader().defaultSectionSize()
        header_h = tbl.horizontalHeader().height()
        desired = header_h + row_h * max(tbl.rowCount(), 2) + 4
        tbl.setMinimumHeight(min(desired, 500))

        # Info avec collision
        collision_text = ""
        if collision_indices:
            collision_text = f"  ⚠ {len(collision_indices)} collision(s)"

        try:
            if self._points_info is not None:
                self._points_info.setText(
                    f"{len(points)} point(s){collision_text}")
        except RuntimeError:
            pass

    def _insert_pattern_subrow(self, tbl, visual_row, pt, pt_index):
        """Insère une sous-rangée pattern sous le point donné."""
        tbl.insertRow(visual_row)

        # Marker comme sous-rangée
        marker = QTableWidgetItem("")
        marker.setFlags(marker.flags() & ~Qt.ItemFlag.ItemIsEditable)
        marker.setData(Qt.ItemDataRole.UserRole, "subrow")
        marker.setData(Qt.ItemDataRole.UserRole + 1, pt_index)
        marker.setBackground(_PAT_SUBROW_BG)
        tbl.setItem(visual_row, _TAR_COL_IDX, marker)

        # Labels et valeurs pattern: nbX, nbY, PasX, PasY
        # Repartis sur les colonnes 1..4
        labels_vals = [
            ("nbX", f"{pt.get('x_count', 1)}"),
            ("nbY", f"{pt.get('y_count', 1)}"),
            ("PasX", f"{pt.get('delta_x', 10.0):.1f}"),
            ("PasY", f"{pt.get('delta_y', 10.0):.1f}"),
        ]
        col_map = [_TAR_COL_X, _TAR_COL_Y, _TAR_COL_TYPE, _TAR_COL_PZ]
        for col_idx, (label, val) in zip(col_map, labels_vals):
            item = QTableWidgetItem(f"{label}={val}")
            item.setBackground(_PAT_SUBROW_BG)
            tbl.setItem(visual_row, col_idx, item)

        # Colonnes Pat. et Del vides pour la sous-rangée
        for col_idx in (_TAR_COL_PAT, _TAR_COL_DEL):
            empty = QTableWidgetItem("")
            empty.setFlags(empty.flags() & ~Qt.ItemFlag.ItemIsEditable
                           & ~Qt.ItemFlag.ItemIsSelectable)
            empty.setBackground(_PAT_SUBROW_BG)
            tbl.setItem(visual_row, col_idx, empty)

        return visual_row + 1

    def _on_taraudage_delete_point(self, pt_index: int):
        """Supprime un point taraudage par son index."""
        if not self._current_op:
            return
        if 0 <= pt_index < len(self._current_op.points):
            self._current_op.points.pop(pt_index)
        self._refresh_taraudage_table(self._current_op.points)
        self._on_param_changed()

    def _on_ebav_toggled(self, checked: bool):
        """Affiche/masque le combo outil ébavurage."""
        if self._suppressing_signals:
            return
        try:
            if hasattr(self, '_ebav_tool_combo') and self._ebav_tool_combo:
                self._ebav_tool_combo.setVisible(checked)
            for w in (getattr(self, '_ebav_pz', None),
                      getattr(self, '_ebav_pz_label', None)):
                if w is not None:
                    w.setVisible(checked)
        except RuntimeError:
            pass
        if self._current_op:
            self._current_op.params['use_ebav'] = checked
        self._on_param_changed()

    def _on_ebav_pz(self, valeur: float):
        if self._current_op:
            self._current_op.params['ebav_profondeur'] = float(valeur)
        self._on_param_changed()

    def _populate_ebav_tools(self, selected_id: str = ""):
        """Remplit le combo ébavurage avec les outils Chamfer/ConXX."""
        combo = self._ebav_tool_combo
        combo.blockSignals(True)
        combo.clear()
        if not self._tool_library:
            combo.blockSignals(False)
            return
        first_idx = 0
        default_idx = -1
        # chanfreins d'abord, coniques ensuite (le reste n'ébavure pas)
        for tid, tool in outils_pour_ebavurage(self._tool_library,
                                               seulement=True):
            combo.addItem(tool.display_name, tid)
            if tid == selected_id:
                first_idx = combo.count() - 1
            # Default: Chamfer 90° z3L3 (article 0068479)
            if tool.article_nr == "0068479" and default_idx < 0:
                default_idx = combo.count() - 1
        if combo.count() == 0:
            combo.addItem("(aucun outil ébav.)", "")
        # Si pas de selected_id, utiliser le default 0068479
        if not selected_id and default_idx >= 0:
            first_idx = default_idx
        combo.setCurrentIndex(first_idx)
        combo.blockSignals(False)

    def _create_param_widget(self, pdef: ParameterDef,
                             current_params: Dict[str, Any]) -> QWidget:
        val = current_params.get(pdef.key, pdef.default)

        if pdef.param_type == ParameterType.FLOAT:
            edit = CalcLineEdit(
                decimals=3,
                min_val=pdef.min_value if pdef.min_value is not None else -99999.0,
                max_val=pdef.max_value if pdef.max_value is not None else 99999.0,
                default=float(val) if val is not None else 0.0)
            edit.editingFinished.connect(self._on_param_changed)
            return edit

        elif pdef.param_type == ParameterType.INT:
            edit = CalcIntLineEdit(
                min_val=int(pdef.min_value or -99999),
                max_val=int(pdef.max_value or 99999),
                default=int(val) if val is not None else 0)
            edit.editingFinished.connect(self._on_param_changed)
            return edit

        elif pdef.param_type == ParameterType.STRING:
            # Champ "filepath" → bouton parcourir proéminent + résumé
            if pdef.key == "filepath":
                container = QWidget()
                v = QVBoxLayout(container)
                v.setContentsMargins(0, 0, 0, 0)
                v.setSpacing(3)
                row = QHBoxLayout()
                row.setSpacing(2)
                edit = QLineEdit(str(val) if val else "")
                edit.setMaximumHeight(26)
                edit.setPlaceholderText("Aucun fichier sélectionné")
                edit.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                edit.editingFinished.connect(self._on_param_changed)
                edit.editingFinished.connect(
                    lambda: self._update_simpl_summary(edit.text()))
                row.addWidget(edit)
                # (bouton Parcourir déplacé sur la ligne du titre)
                v.addLayout(row)
                # Résumé du SimPl appelé (outils, Pz max, positions...)
                summary = QLabel("")
                summary.setWordWrap(True)
                summary.setStyleSheet(
                    "QLabel { color: #a6e3a1; font-size: 11px; "
                    "font-family: 'Cascadia Code', Consolas, monospace; "
                    "background: #181825; border: 1px solid #313244; "
                    "border-radius: 4px; padding: 6px; }")
                summary.setVisible(False)
                v.addWidget(summary)
                container._line_edit = edit  # pour _collect_params
                self._simpl_summary_label = summary
                self._update_simpl_summary(edit.text())
                return container
            # Un outil à choisir (« head_tool_id »: le fraisage de
            # tête): une liste, chanfreins d'abord, coniques ensuite
            # — un champ texte demandait l'identifiant de l'outil
            if pdef.key.endswith("_tool_id") and self._tool_library:
                combo = NoScrollComboBox()
                combo.addItem("(outil de l'opération)", "")
                for tid, outil in outils_pour_ebavurage(
                        self._tool_library):
                    combo.addItem(outil.display_name, tid)
                if val:
                    index = combo.findData(str(val))
                    if index >= 0:
                        combo.setCurrentIndex(index)
                combo.currentIndexChanged.connect(self._on_param_changed)
                combo._is_tool_id = True    # pour _collect_params
                return combo
            # Champ "tool_article" → combo avec tous les outils de tools.json
            if pdef.key == "tool_article" and self._tool_library:
                combo = NoScrollComboBox()
                combo.addItem("(aucun)", "")
                for tool in self._tool_library.get_all_tools():
                    combo.addItem(
                        f"{tool.name} [{tool.article_nr}]",
                        tool.article_nr)
                # Pré-sélectionner si une valeur existe
                if val:
                    for i in range(combo.count()):
                        if combo.itemData(i) == val:
                            combo.setCurrentIndex(i)
                            break
                combo.currentIndexChanged.connect(self._on_param_changed)
                combo._is_tool_article = True  # flag pour _collect_params
                return combo
            if getattr(pdef, 'multiline', False):
                # un texte à graver: plusieurs lignes, la hauteur de
                # trois
                from PySide6.QtWidgets import QPlainTextEdit
                zone = QPlainTextEdit(str(val) if val else "")
                zone.setFixedHeight(64)
                if pdef.key == "code":
                    # des lignes SimPl (Lignes du Main): en chasse
                    # fixe, assez haut pour lire une gravure entière
                    from PySide6.QtGui import QFontDatabase
                    zone.setFont(QFontDatabase.systemFont(
                        QFontDatabase.SystemFont.FixedFont))
                    zone.setLineWrapMode(QPlainTextEdit.NoWrap)
                    n = len(str(val or "").split("\n"))
                    zone.setFixedHeight(min(320, 24 + 17 * max(n, 3)))
                zone.setTabChangesFocus(True)
                zone.textChanged.connect(self._on_param_changed)
                return zone
            edit = QLineEdit(str(val) if val else "")
            edit.setMaximumHeight(26)
            edit.editingFinished.connect(self._on_param_changed)
            return edit

        elif pdef.param_type == ParameterType.BOOL:
            cb = QCheckBox()
            cb.setChecked(bool(val))
            cb.toggled.connect(self._on_param_changed)
            return cb

        elif pdef.param_type == ParameterType.CHOICE:
            if pdef.key == "police":
                # les polices du poste: une fenêtre haute, sur
                # plusieurs colonnes, avec les récentes — pas un
                # menu déroulant de 466 lignes
                from src.gui.dialogs.police_dialog import PolicePicker
                choix = PolicePicker(pdef.choices, str(val or ""))
                choix.changed.connect(self._on_param_changed)
                return choix
            combo = NoScrollComboBox()
            for choice in pdef.choices:
                combo.addItem(choice)
            if val in pdef.choices:
                combo.setCurrentText(str(val))
            if len(pdef.choices) > 40:
                # une liste longue (les polices du poste) ne dicte pas
                # la largeur du formulaire: elle prend la place
                # qu'on lui laisse
                from PySide6.QtWidgets import QComboBox
                combo.setSizeAdjustPolicy(
                    QComboBox.SizeAdjustPolicy
                    .AdjustToMinimumContentsLengthWithIcon)
                combo.setMinimumContentsLength(10)
            combo.currentTextChanged.connect(self._on_param_changed)
            return combo

        edit = QLineEdit(str(val))
        edit.setMaximumHeight(26)
        return edit

    def _browse_simpl_file(self, line_edit: QLineEdit):
        """Ouvre un dialogue pour sélectionner un fichier .SimPl."""
        # Démarrer dans le dossier du fichier actuel si possible
        start_dir = ""
        current = line_edit.text().strip()
        if current:
            d = os.path.dirname(current)
            if os.path.isdir(d):
                start_dir = d
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Sélectionner un programme SimPl",
            start_dir, "Fichiers SimPl (*.SimPl *.simpl);;Tous (*)")
        if filepath:
            line_edit.setText(filepath)
            self._update_simpl_summary(filepath)
            # L'opération prend le nom du fichier: la liste dit alors
            # quel programme est appelé
            op = self._current_op
            if op is not None and op.operation_type in (
                    "appel_programme", "import_programme"):
                import os as _os
                base = _os.path.splitext(
                    _os.path.basename(filepath))[0]
                if base:
                    op.name = base[:40]
                    lbl = getattr(self, '_name_label', None)
                    if lbl is not None:
                        try:
                            lbl.setText(op.name)
                        except RuntimeError:
                            pass
            self._on_param_changed()

    def _update_simpl_summary(self, filepath: str):
        """Met à jour le résumé du SimPl externe sous le champ fichier."""
        lbl = getattr(self, '_simpl_summary_label', None)
        if lbl is None:
            return
        try:
            filepath = (filepath or "").strip()
            if not filepath:
                lbl.setVisible(False)
                return
            from src.io.simpl_analyzer import (
                analyze_simpl_file, summary_text)
            style_alerte = (
                "QLabel { color: #f38ba8; font-size: 11px; "
                "font-family: 'Cascadia Code', Consolas, monospace; "
                "background: #181825; border: 1px solid #313244; "
                "border-radius: 4px; padding: 6px; }")
            # La machine REFUSE un fichier appelé dont le nom porte des
            # accents (é, è, à…) ou tout caractère non ASCII: on le dit
            # tout de suite, avant même de lire le fichier.
            accents = _accents_dans_le_nom(filepath)
            if accents:
                lbl.setText(
                    "⚠ Accents dans le nom du fichier appelé "
                    f"({' '.join(sorted(set(accents)))}) : la machine "
                    "le refuse. Renommez le .SimPl sans accent.")
                lbl.setStyleSheet(style_alerte)
                lbl.setVisible(True)
                return
            info = analyze_simpl_file(filepath, sequences=False)
            if info is None:
                lbl.setText("⚠ Fichier introuvable ou illisible")
                lbl.setStyleSheet(style_alerte)
                lbl.setVisible(True)
                return
            lbl.setText(summary_text(info))
            lbl.setStyleSheet(
                "QLabel { color: #a6e3a1; font-size: 11px; "
                "font-family: 'Cascadia Code', Consolas, monospace; "
                "background: #181825; border: 1px solid #313244; "
                "border-radius: 4px; padding: 6px; }")
            lbl.setVisible(True)
        except RuntimeError:
            pass  # widget détruit

    def _collect_params(self) -> Dict[str, Any]:
        """Collecte toutes les valeurs du formulaire."""
        params = {}
        if not self._current_op:
            return params

        try:
            op_class = OperationRegistry.get(
                self._current_op.operation_type)
        except KeyError:
            return params

        for pdef in op_class.get_parameters():
            w = self._widgets.get(pdef.key)
            if not w:
                continue
            try:
                if pdef.param_type == ParameterType.FLOAT:
                    if isinstance(w, CalcLineEdit):
                        params[pdef.key] = w.value()
                    elif hasattr(w, 'value'):
                        params[pdef.key] = w.value()
                elif pdef.param_type == ParameterType.INT:
                    if isinstance(w, CalcIntLineEdit):
                        params[pdef.key] = w.value()
                    elif hasattr(w, 'value'):
                        params[pdef.key] = w.value()
                elif pdef.param_type == ParameterType.STRING:
                    # Support du container filepath avec _line_edit
                    if hasattr(w, '_line_edit'):
                        val = w._line_edit.text()
                        # Normaliser chemins: / → \ pour Windows
                        if pdef.key == 'filepath' and '/' in val:
                            val = val.replace('/', '\\')
                            w._line_edit.setText(val)
                        params[pdef.key] = val
                    elif hasattr(w, '_is_tool_article'):
                        # Combo tool_article: récupérer l'article_nr
                        params[pdef.key] = w.currentData() or ""
                    elif hasattr(w, '_is_tool_id'):
                        params[pdef.key] = w.currentData() or ""
                    elif hasattr(w, 'toPlainText'):
                        params[pdef.key] = w.toPlainText()
                    else:
                        params[pdef.key] = w.text()
                elif pdef.param_type == ParameterType.BOOL:
                    params[pdef.key] = w.isChecked()
                elif pdef.param_type == ParameterType.CHOICE:
                    params[pdef.key] = w.currentText()
            except RuntimeError:
                pass  # Widget C++ déjà supprimé — ignorer

        # Taraudage: ajouter ebav_tool_id depuis le combo dédié
        try:
            if hasattr(self, '_ebav_tool_combo') and self._ebav_tool_combo:
                params['ebav_tool_id'] = (
                    self._ebav_tool_combo.currentData() or "")
        except RuntimeError:
            pass
        try:
            if hasattr(self, '_ebav_cb') and self._ebav_cb:
                params['use_ebav'] = self._ebav_cb.isChecked()
            if getattr(self, '_ebav_pz', None) is not None:
                params['ebav_profondeur'] = float(self._ebav_pz.value())
        except RuntimeError:
            pass
        # BPM tool2 (taraudage)
        try:
            if self._bpm_tool2_combo and self._bpm_tool2_group:
                if self._bpm_tool2_group.isVisible():
                    params['bpm_tool2_id'] = (
                        self._bpm_tool2_combo.currentData() or "")
        except RuntimeError:
            pass
        # RPM + avances par opération: n'enregistrer un OVERRIDE que si
        # la valeur diffère de l'outil (sinon les multiplicateurs
        # matériau seraient court-circuités par la valeur figée)
        tool_obj = None
        try:
            tid = self._tool_combo.currentData() if self._tool_combo \
                else ""
            if tid and self._tool_library:
                tool_obj = self._tool_library.get_tool(tid)
        except RuntimeError:
            pass
        try:
            if self._rpm_override:
                val = self._rpm_override.value()
                base = int(getattr(tool_obj, 'rpm', 0) or 0)
                params['rpm_override'] = \
                    val if (val > 0 and val != base) else 0
        except RuntimeError:
            pass
        for key, w in list(self._feed_overrides.items()):
            try:
                val = w.value()
                base = int(getattr(tool_obj, f'feed_{key}', 0) or 0) \
                    if tool_obj else 0
                params[f'feed_override_{key}'] = \
                    val if (val > 0 and val != base) else 0
            except RuntimeError:
                pass
        # Instances similaires (même sous-programme)
        if self._instances_vbox is not None:
            params['instances'] = self._read_instance_rows()
        # Champs de saisie opérateur
        if getattr(self, '_opfields_vbox', None) is not None:
            params['fields'] = self._read_operator_fields()
        # Gravure: variable concaténée au texte
        tvc = getattr(self, '_text_var_combo', None)
        if tvc is not None:
            try:
                params['text_var'] = tvc.currentData() or ""
            except RuntimeError:
                pass
        # Cotes liées à une variable opérateur
        binds = getattr(self, '_var_bind_widgets', None)
        if binds:
            mapping = {}
            for key, combo in binds.items():
                try:
                    var = combo.currentData() or ""
                except RuntimeError:
                    continue
                if var:
                    mapping[key] = var
            params['param_vars'] = mapping
        return params

    # ── Instances similaires dans le même sous-programme ──

    def _instance_finish_key(self) -> str:
        if self._current_op and \
                self._current_op.operation_type == "surfacage_rectangle":
            return 'finishing_z'
        return 'finishing_xy'

    # ── Bloc SimPl importé: fiche du sous-programme ──

    #: signal émis au panneau: (action, id d'opération)
    group_instance_action = Signal(str, str)

    def _build_probe_presets(self, op):
        """Tailles de brut à palper, enregistrées d'un programme à
        l'autre: une série revient, ses cotes aussi."""
        from src.core import probe_presets
        from src.gui.icons import get_button_icon
        box = QGroupBox("Tailles enregistrées")
        ligne = QHBoxLayout()
        ligne.setContentsMargins(4, 8, 4, 4)
        ligne.setSpacing(4)

        combo = NoScrollComboBox()
        combo.addItem("— choisir une taille —", "")
        for preset in probe_presets.charger():
            combo.addItem(
                f"{preset['name']}  "
                f"({preset.get('width_x', 0):g} × "
                f"{preset.get('width_y', 0):g})",
                preset['name'])
        combo.currentIndexChanged.connect(
            lambda _i, c=combo: self._on_probe_preset_chosen(c))
        self._probe_preset_combo = combo
        ligne.addWidget(combo, 1)

        ajouter = QPushButton("")
        ajouter.setIcon(get_button_icon("save", 15))
        ajouter.setFixedSize(26, 24)
        ajouter.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        ajouter.setToolTip("Enregistrer les cotes actuelles")
        ajouter.clicked.connect(self._on_probe_preset_save)
        ligne.addWidget(ajouter)

        retirer = QPushButton("")
        retirer.setIcon(get_button_icon("delete", 15))
        retirer.setFixedSize(26, 24)
        retirer.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        retirer.setToolTip("Supprimer la taille choisie")
        retirer.clicked.connect(self._on_probe_preset_delete)
        ligne.addWidget(retirer)

        box.setLayout(ligne)
        self._layout.addWidget(box)

    def _on_probe_preset_chosen(self, combo):
        """Une taille choisie remplit les champs de cotes."""
        if self._suppressing_signals or self._current_op is None:
            return
        from src.core import probe_presets
        nom = combo.currentData() or ""
        if not nom:
            return
        for cle, valeur in probe_presets.valeurs(nom).items():
            widget = self._widgets.get(cle)
            if widget is not None and hasattr(widget, 'setValue'):
                widget.setValue(float(valeur))
            self._current_op.params[cle] = float(valeur)
        self._on_param_changed()

    def _on_probe_preset_save(self):
        """Enregistre les cotes du formulaire sous un nom.

        Les DÉFAUTS de l'opération entrent dans le preset: `params`
        ne porte que ce que l'utilisateur a touché, et une taille
        enregistrée sans y avoir touché rappelait une profondeur de
        palpage de 0 — le palpeur cherchait le flanc au ras du
        dessus."""
        from src.core import probe_presets
        from src.operations.registry import OperationRegistry
        if self._current_op is None:
            return
        try:
            defauts = OperationRegistry.get(
                self._current_op.operation_type).get_default_params()
        except KeyError:
            defauts = {}
        params = {**defauts, **self._current_op.params}
        propose = (f"Brut {float(params.get('width_x', 0) or 0):g}"
                   f"x{float(params.get('width_y', 0) or 0):g}")
        nom, ok = QInputDialog.getText(
            self, "Taille à palper", "Nom de la taille :",
            text=propose)
        if not ok or not nom.strip():
            return
        probe_presets.ajouter(nom.strip(), params)
        self.load_operation(self._current_op)

    def _on_probe_preset_delete(self):
        """Retire la taille choisie dans la liste."""
        from src.core import probe_presets
        combo = getattr(self, '_probe_preset_combo', None)
        nom = combo.currentData() if combo is not None else ""
        if not nom:
            QMessageBox.information(
                self, "Tailles enregistrées",
                "Choisissez d'abord une taille dans la liste.")
            return
        probe_presets.supprimer(nom)
        if self._current_op is not None:
            self.load_operation(self._current_op)

    def _add_import_button_near_preview(self, op):
        """Bouton « Importer » collé à l'aperçu canvas d'un appel.

        Un appel externe qu'on veut régler devient un import: ses
        sous-programmes arrivent en ensemble. Ctrl+Z fait revenir
        l'appel."""
        from src.gui.icons import get_button_icon
        widget = self._widgets.get('preview')
        if widget is None:
            return
        parent = widget.parentWidget()
        grid = parent.layout() if parent is not None else None
        if grid is None or not hasattr(grid, 'getItemPosition'):
            return
        pos = grid.indexOf(widget)
        if pos < 0:
            return
        r, c, rs, cs = grid.getItemPosition(pos)
        btn = QPushButton(" Importer")
        btn.setIcon(get_button_icon("open_file", 16))
        btn.setMaximumHeight(24)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setToolTip(
            "Remplacer l'appel par l'IMPORT du programme: ses "
            "sous-programmes deviennent des opérations réglables. "
            "Ctrl+Z rétablit l'appel.")
        btn.setStyleSheet(
            "QPushButton { background: #89b4fa; color: #1e1e2e; "
            "font-weight: bold; padding: 2px 10px; "
            "border-radius: 4px; font-size: 11px; }"
            "QPushButton:hover { background: #a9c9ff; }")
        btn.clicked.connect(
            lambda _=False, o=op: self.import_call_requested.emit(o.id))
        grid.removeWidget(widget)
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(widget)
        row.addWidget(btn)
        row.addStretch()
        grid.addWidget(holder, r, c, rs, cs)

    def _build_trace_shape_buttons(self, op):
        """Formes du tracé en BOUTONS: une forme se choisit d'un coup
        d'œil, et chacune n'affiche que ses propres champs."""
        from src.gui.icons import get_button_icon
        from src.operations.trace import Trace
        box = QGroupBox("Forme")
        row = QHBoxLayout()
        row.setSpacing(3)
        row.setContentsMargins(4, 8, 4, 4)
        self._trace_shape_btns = {}
        current = str(op.params.get('shape', 'Rectangle'))
        for shape in Trace.SHAPES:
            btn = QPushButton("")
            btn.setIcon(get_button_icon(
                Trace.SHAPE_ICONS.get(shape, "settings"), 18))
            btn.setToolTip(shape)
            btn.setCheckable(True)
            btn.setChecked(shape == current)
            btn.setFixedSize(34, 28)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.clicked.connect(
                lambda _=False, sh=shape: self._on_trace_shape(sh))
            row.addWidget(btn)
            self._trace_shape_btns[shape] = btn
        row.addStretch()
        box.setLayout(row)
        self._layout.addWidget(box)

    def _on_trace_shape(self, shape: str):
        """Bouton de forme: change la forme et refait le formulaire.

        Les champs d'une forme ne servent pas aux autres — on
        reconstruit plutôt que de laisser des trous dans la grille."""
        op = self._current_op
        if op is None or str(op.params.get('shape')) == shape:
            return
        op.params['shape'] = shape
        # Le bouton cliqué fait partie du formulaire à refaire: on ne
        # le détruit pas pendant qu'il émet son signal
        QTimer.singleShot(0, lambda: self._rebuild_trace_form(op))

    def _rebuild_trace_form(self, op):
        if self._current_op is not op:
            return
        self.load_operation(op)
        self.params_changed.emit(dict(op.params))

    def _build_trace_pickup_section(self, op):
        """Reprendre un contour du dessin comme parcours de tracé."""
        box = QGroupBox("Contour du dessin")
        v = QVBoxLayout()
        v.setSpacing(3)
        v.setContentsMargins(4, 8, 4, 4)
        pts = op.params.get('path_points') or []
        n_contours = len(op.params.get('contours') or [])
        info = QLabel(
            f"{n_contours} contour(s) relevé(s)" if n_contours > 1
            else f"{len(pts)} sommet(s) relevés" if pts
            else "Aucun contour relevé")
        info.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 10px;")
        v.addWidget(info)
        btn = QPushButton("⌖ Reprendre les contours sélectionnés")
        btn.setMaximumHeight(24)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setToolTip(
            "Sélectionnez au canvas une ou plusieurs polylignes "
            "(mode Sélection), puis ce bouton: elles deviennent les "
            "contours du tracé (forme « Dessin »), usinés selon le "
            "côté de l'outil")
        btn.clicked.connect(self._on_trace_pickup)
        v.addWidget(btn)
        box.setLayout(v)
        self._layout.addWidget(box)
        self._trace_pickup_info = info

    def _build_contours_section(self, op):
        """Contours relevés au dessin, et résumé du calcul.

        Une gravure au V n'a pas de cotes à saisir: elle a une FORME.
        Le formulaire montre donc ce qu'il a relevé et ce que le
        calcul en tire — nombre de passes et fond atteint."""
        box = QGroupBox("Contours du dessin")
        v = QVBoxLayout()
        v.setSpacing(3)
        v.setContentsMargins(4, 8, 4, 4)
        info = QLabel("")
        info.setWordWrap(True)
        info.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 10px;")
        v.addWidget(info)
        # (« Appliquer les courbes sélectionnées » est en tête du
        # formulaire, à côté de « Calculer parcours ».)
        if op.operation_type == "texte_grave":
            # (Le texte se dessine de lui-même au canvas, par
            # l'opération; le poser en plus le superposait. Pour le
            # DXF: calque « Textes des opérations » de l'export.)
            aide = QLabel("Le texte se dessine au canvas par "
                          "l'opération; l'export DXF a un calque "
                          "« Textes des opérations ».")
            aide.setWordWrap(True)
            aide.setStyleSheet(
                f"color: {COLORS['text_dim']}; font-size: 10px;")
            v.addWidget(aide)

        # (Le calcul — parcours ou gamme entière — se lance depuis la
        # barre en tête du formulaire, qui reste visible en défilant.
        # Il ne part jamais tout seul: sur un dessin chargé, il
        # repartait à chaque frappe et à chaque redessin.)
        box.setLayout(v)
        self._layout.addWidget(box)
        self._contours_info = info
        self._maj_resume_contours(op)

    # ── la gamme: son tableau ──

    #: colonnes du tableau de la gamme: l'interrupteur, le titre (qui
    #: prend la place et s'élide), les réglages, puis les boutons de
    #: ligne en butée à droite — comme dans la liste d'opérations
    _GAMME_COLONNES = ("⏻", "Poste", "Outil", "Cote", "Passe Z", "XY",
                       "Rep.", "", "", "")
    _GAMME_COL_MARCHE, _GAMME_COL_TITRE, _GAMME_COL_OUTIL, \
        _GAMME_COL_COTE, _GAMME_COL_PASSE, _GAMME_COL_XY, \
        _GAMME_COL_REPRISE, _GAMME_COL_OEIL, _GAMME_COL_CALCUL, \
        _GAMME_COL_CORBEILLE = range(10)

    def _build_gamme_section(self, op):
        """Le tableau récapitulatif de la gamme, à éditer en place.

        Une ligne par poste — l'opération de la liste —, ses réglages
        essentiels sous la main: outil, cote, matière laissée,
        reprise. Chaque ligne porte ses boutons au bord droit (œil,
        calcul, corbeille), son menu au clic droit, et un double-clic
        sur le titre ouvre le formulaire détaillé du poste. Le titre
        prend la place qui reste et s'élide (…) s'il dépasse: le
        tableau ne déborde jamais de la colonne."""
        from PySide6.QtWidgets import QTableWidget, QHeaderView, QMenu
        from src.gui.icons import get_button_icon
        from src.operations import gamme_postes as gp
        from src.operations.gamme_gravure import GammeGravure
        programme = getattr(self, '_program_ref', None)
        membres = GammeGravure.membres(
            op, programme.operations if programme else [])
        box = QGroupBox(f"Postes de la gamme ({len(membres)})")
        v = QVBoxLayout()
        v.setSpacing(3)
        v.setContentsMargins(4, 8, 4, 4)
        table = QTableWidget(len(membres), len(self._GAMME_COLONNES))
        table.setHorizontalHeaderLabels(list(self._GAMME_COLONNES))
        table.verticalHeader().setVisible(False)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.setStyleSheet("QTableWidget { font-size: 11px; }")
        table.setTextElideMode(Qt.TextElideMode.ElideRight)
        table.setWordWrap(False)
        # Jamais de défilement horizontal: le titre absorbe, les
        # boutons restent au bord droit visible
        table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.setMinimumWidth(0)
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(self._on_gamme_menu)
        table.cellDoubleClicked.connect(
            lambda rang, _col: self._gamme_action_rang(rang, 'ouvrir'))
        bibliotheque = self._bibliotheque()
        self._gamme_lignes = []
        self._gamme_table = table
        for rang, poste in enumerate(membres):
            self._gamme_ligne(table, rang, poste, bibliotheque)
        entete = table.horizontalHeader()
        entete.setStretchLastSection(False)
        entete.setMinimumSectionSize(18)
        for colonne, largeur in ((self._GAMME_COL_MARCHE, 24),
                                 (self._GAMME_COL_OUTIL, 104),
                                 (self._GAMME_COL_COTE, 48),
                                 (self._GAMME_COL_PASSE, 52),
                                 (self._GAMME_COL_XY, 48),
                                 (self._GAMME_COL_REPRISE, 34),
                                 (self._GAMME_COL_OEIL, 26),
                                 (self._GAMME_COL_CALCUL, 26),
                                 (self._GAMME_COL_CORBEILLE, 26)):
            entete.setSectionResizeMode(colonne,
                                        QHeaderView.ResizeMode.Fixed)
            table.setColumnWidth(colonne, largeur)
        entete.setSectionResizeMode(self._GAMME_COL_TITRE,
                                    QHeaderView.ResizeMode.Stretch)
        hauteur = entete.height() + 4 + sum(
            table.rowHeight(r) for r in range(table.rowCount()))
        table.setFixedHeight(min(hauteur, 420))
        v.addWidget(table)

        ligne = QHBoxLayout()
        ajouter = QPushButton(" Poste")
        ajouter.setIcon(get_button_icon("add", 14))
        ajouter.setMaximumHeight(24)
        ajouter.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        ajouter.setToolTip("Ajoute un poste à la fin de la gamme: un "
                           "contour, une gravure, un évidement ou "
                           "une pause. Il prend le dessin et le "
                           "champ de la gamme.")
        menu = QMenu(ajouter)
        for genre in gp.POSTES_MODELES:
            menu.addAction(genre, lambda g=genre, o=op:
                           self.gamme_poste_added.emit(o.id, g))
        ajouter.setMenu(menu)
        ligne.addWidget(ajouter)
        aide = QLabel("Double-clic: le formulaire du poste · clic "
                      "droit: tout le reste.")
        aide.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 10px;")
        aide.setWordWrap(True)
        ligne.addWidget(aide, stretch=1)
        v.addLayout(ligne)
        box.setLayout(v)
        self._layout.addWidget(box)
        self._maj_etats_gamme()
        self._build_gamme_modeles(op)

    def _build_gamme_modeles(self, op):
        """Les modèles de gamme: en appliquer un aux postes,
        enregistrer la gamme telle qu'elle est, choisir celui qui
        sert à la création."""
        from src.operations import gamme_modeles as gm
        box = QGroupBox("Modèle de gamme")
        v = QVBoxLayout()
        v.setSpacing(3)
        v.setContentsMargins(4, 8, 4, 4)
        ligne = QHBoxLayout()
        combo = NoScrollComboBox()
        for nom in gm.noms():
            combo.addItem(nom, nom)
        defaut = gm.par_defaut()
        index = combo.findData(defaut)
        if index >= 0:
            combo.setCurrentIndex(index)
        combo.setToolTip("Les modèles livrés (la base, ceux de "
                         "l'atelier: data/gammes_atelier.json) et les "
                         "vôtres (data/gammes.json, à côté de l'exe).")
        ligne.addWidget(combo, stretch=1)
        self._gamme_modele_combo = combo
        detail = QLabel("")
        detail.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 10px;")
        detail.setWordWrap(True)
        self._gamme_modele_detail = detail

        def _decrire(*_):
            try:
                detail.setText(gm.description(combo.currentData() or ""))
            except Exception:
                detail.setText("")
        combo.currentIndexChanged.connect(_decrire)
        _decrire()
        v.addLayout(ligne)
        v.addWidget(detail)

        boutons = QHBoxLayout()

        def _bouton(texte, bulle, action):
            b = QPushButton(texte)
            b.setMaximumHeight(24)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setToolTip(bulle)
            b.clicked.connect(
                lambda _=False, a=action, o=op:
                self.gamme_modele_action.emit(
                    o.id, a, combo.currentData() or ""))
            boutons.addWidget(b)
            return b

        _bouton("Appliquer", "Remplace les postes de cette gamme par "
                "ceux du modèle choisi (le dessin et le champ "
                "restent). Un seul Ctrl+Z reprend le tout.", 'appliquer')
        _bouton("Enregistrer…", "Enregistre les postes de cette gamme "
                "— outils, cotes, matière laissée, reprise, ordre — "
                "sous un nom, pour la recréer d'un clic.", 'enregistrer')
        self._gamme_modele_supprimer = _bouton(
            "Supprimer", "Supprime le modèle choisi (pas la gamme).",
            'supprimer')
        self._gamme_modele_supprimer.setEnabled(
            not gm.est_livre(combo.currentData() or ""))
        combo.currentIndexChanged.connect(
            lambda _i: self._gamme_modele_supprimer.setEnabled(
                not gm.est_livre(combo.currentData() or "")))
        v.addLayout(boutons)

        defaut_cb = QCheckBox("Ce modèle sert à « Ajouter → Gamme "
                              "gravure »")
        defaut_cb.setChecked(combo.currentData() == defaut)
        defaut_cb.setToolTip("Le modèle par défaut est celui dont on "
                             "part quand on crée une gamme.")
        combo.currentIndexChanged.connect(
            lambda _i: defaut_cb.setChecked(
                combo.currentData() == gm.par_defaut()))
        defaut_cb.toggled.connect(
            lambda on, o=op: self.gamme_modele_action.emit(
                o.id, 'defaut', combo.currentData() or "") if on else None)
        v.addWidget(defaut_cb)
        box.setLayout(v)
        self._layout.addWidget(box)

    #: (id de l'ébavurage, action: appliquer / enregistrer / supprimer,
    #: nom du modèle) — et 'source' pour reprendre la géométrie
    ebavurage_action = Signal(str, str, str)

    def _build_ebavurage_section(self, op):
        """Les modèles d'ébavurage — appliquer, enregistrer,
        supprimer —, la géométrie reprise de la source ou des
        courbes sélectionnées, et ce que ça donne."""
        from src.gui.icons import get_button_icon
        from src.operations import ebavurage_modeles as em
        from src.operations.ebavurage import Ebavurage
        box = QGroupBox("Modèles d'ébavurage")
        v = QVBoxLayout()
        v.setSpacing(3)
        v.setContentsMargins(4, 8, 4, 4)
        ligne = QHBoxLayout()
        combo = NoScrollComboBox()
        for nom in em.noms():
            combo.addItem(nom)
        ligne.addWidget(combo, stretch=1)
        appliquer = QPushButton("Appliquer")
        appliquer.setMaximumHeight(24)
        appliquer.setToolTip("Prend l'outil, l'offset et la profondeur "
                             "du modèle")
        appliquer.clicked.connect(
            lambda _c=False, o=op, c=combo: self.ebavurage_action.emit(
                o.id, 'appliquer', c.currentText()))
        ligne.addWidget(appliquer)
        v.addLayout(ligne)
        ligne2 = QHBoxLayout()
        enregistrer = QPushButton(" Enregistrer…")
        enregistrer.setIcon(get_button_icon("add", 14))
        enregistrer.setMaximumHeight(24)
        enregistrer.setToolTip("Retient l'outil, l'offset et la "
                               "profondeur de cet ébavurage sous un nom")
        enregistrer.clicked.connect(
            lambda _c=False, o=op: self.ebavurage_action.emit(
                o.id, 'enregistrer', ""))
        ligne2.addWidget(enregistrer)
        supprimer = QPushButton(" Supprimer")
        supprimer.setIcon(get_button_icon("delete", 14))
        supprimer.setMaximumHeight(24)
        supprimer.clicked.connect(
            lambda _c=False, o=op, c=combo: self.ebavurage_action.emit(
                o.id, 'supprimer', c.currentText()))
        ligne2.addWidget(supprimer)
        ligne2.addStretch()
        v.addLayout(ligne2)
        self._ebavurage_modeles_combo = combo
        box.setLayout(v)
        self._layout.addWidget(box)

        geo = QGroupBox("Géométrie")
        g = QVBoxLayout()
        g.setSpacing(3)
        g.setContentsMargins(4, 8, 4, 4)
        etat = QLabel(Ebavurage.resume(op.params))
        etat.setWordWrap(True)
        etat.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 10px;")
        g.addWidget(etat)
        self._ebavurage_etat = etat
        source = QPushButton(" Reprendre la géométrie de la source")
        source.setIcon(get_button_icon("dxf", 15))
        source.setMaximumHeight(24)
        source.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        source.setToolTip("Relit le rectangle, le cercle ou les "
                          "contours de l'opération dont cet ébavurage "
                          "est parti — après l'avoir modifiée")
        source.setEnabled(bool(op.params.get('source_id')))
        source.clicked.connect(
            lambda _c=False, o=op: self.ebavurage_action.emit(
                o.id, 'source', ""))
        g.addWidget(source)
        courbes = QPushButton(" Appliquer les courbes sélectionnées")
        courbes.setIcon(get_button_icon("dxf", 15))
        courbes.setMaximumHeight(24)
        courbes.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        courbes.setToolTip("Les courbes fermées sélectionnées au "
                           "canvas deviennent ce qu'on ébavure "
                           "(forme: Contours)")
        courbes.clicked.connect(self._on_contours_pickup)
        g.addWidget(courbes)
        geo.setLayout(g)
        self._layout.addWidget(geo)

    def _gamme_ligne(self, table, rang: int, poste, bibliotheque):
        """Une ligne du tableau: les widgets qui écrivent dans le
        poste (par `gamme_poste_edited`) et ses boutons de ligne (par
        `gamme_poste_action`)."""
        from PySide6.QtWidgets import QTableWidgetItem, QCheckBox, \
            QLineEdit, QToolButton
        from src.gui.icons import get_button_icon
        from src.gui.widgets import SpinCote
        from src.operations import gamme_postes as gp
        from src.operations.registry import OperationRegistry
        ident = poste.id
        a_outil = poste.operation_type in gp.TYPES_A_OUTIL

        def _cellule(colonne, widget):
            table.setCellWidget(rang, colonne, widget)

        def _bouton(colonne, icone, bulle, action):
            bouton = QToolButton()
            bouton.setIcon(get_button_icon(icone, 14))
            bouton.setAutoRaise(True)
            bouton.setFixedSize(24, 22)
            bouton.setToolTip(bulle)
            bouton.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            bouton.clicked.connect(
                lambda _=False, i=ident, a=action:
                self.gamme_poste_action.emit(i, a))
            _cellule(colonne, bouton)
            return bouton

        marche = QCheckBox()
        marche.setChecked(bool(poste.enabled))
        marche.setToolTip("Poste actif: généré et dessiné")
        marche.toggled.connect(
            lambda on, i=ident: self.gamme_poste_edited.emit(
                i, {'enabled': bool(on)}))
        _cellule(self._GAMME_COL_MARCHE, marche)

        # le titre: celui de l'opération, élidé s'il dépasse; son
        # infobulle dit l'état du parcours
        titre = QTableWidgetItem(poste.name)
        titre.setFlags(Qt.ItemFlag.ItemIsEnabled)
        table.setItem(rang, self._GAMME_COL_TITRE, titre)

        if a_outil:
            combo = NoScrollComboBox()
            genre = gp.genre_outil(gp.nom_outil(bibliotheque,
                                                poste.tool_id))
            for identifiant in gp.outils_du_genre(bibliotheque, genre):
                combo.addItem(gp.nom_outil(bibliotheque, identifiant),
                              identifiant)
            index = combo.findData(poste.tool_id)
            if index >= 0:
                combo.setCurrentIndex(index)
            combo.currentIndexChanged.connect(
                lambda _i, c=combo, i=ident: self.gamme_poste_edited.emit(
                    i, {'tool_id': c.currentData() or ""}))
            _cellule(self._GAMME_COL_OUTIL, combo)

            classe = OperationRegistry.get(poste.operation_type)
            cle = getattr(classe, 'CLE_PROFONDEUR', 'profondeur')
            cote = SpinCote(decimales=2)
            cote.setRange(0.01, 100.0)
            cote.setValue(float(poste.params.get(cle, 1.0) or 1.0))
            cote.setToolTip("Cote visée (mm)")
            cote.editingFinished.connect(
                lambda w=cote, i=ident, k=cle: self.gamme_poste_edited.emit(
                    i, {'params': {k: float(w.value())}}))
            _cellule(self._GAMME_COL_COTE, cote)

            # la passe en Z de cet outil: de combien il descend à
            # chaque tour (0 = tout d'un coup, ou la moitié du Ø pour
            # une cylindrique)
            passe = SpinCote(decimales=2)
            passe.setRange(0.0, 50.0)
            passe.setSpecialValueText("auto")
            passe.setValue(float(poste.params.get('profondeur_passe',
                                                  0.0) or 0.0))
            passe.setToolTip("Passe Z: de combien l'outil descend à "
                             "chaque passage (mm). 0 = auto: tout en "
                             "une descente pour une conique, la "
                             "moitié du Ø pour une cylindrique.")
            passe.editingFinished.connect(
                lambda w=passe, i=ident: self.gamme_poste_edited.emit(
                    i, {'params': {'profondeur_passe': float(w.value())}}))
            _cellule(self._GAMME_COL_PASSE, passe)

            xy = SpinCote(decimales=2)
            xy.setRange(0.0, 10.0)
            xy.setValue(float(poste.params.get('offset_xy', 0.0) or 0.0))
            xy.setToolTip("Passe XY: la matière laissée le long du "
                          "contour par cet outil (mm) — un offset "
                          "d'ébauche, que la finition reprend.")
            xy.editingFinished.connect(
                lambda w=xy, i=ident: self.gamme_poste_edited.emit(
                    i, {'params': {'offset_xy': float(w.value())}}))
            _cellule(self._GAMME_COL_XY, xy)

            reprise = QCheckBox()
            reprise.setChecked(bool(poste.params.get('reprise', False)))
            reprise.setToolTip("Reprise: ne travailler que ce que les "
                               "postes précédents ont laissé, à cette "
                               "cote")
            reprise.toggled.connect(
                lambda on, i=ident: self.gamme_poste_edited.emit(
                    i, {'params': {'reprise': bool(on)}}))
            _cellule(self._GAMME_COL_REPRISE, reprise)
            _bouton(self._GAMME_COL_CALCUL, "settings",
                    "Calculer le parcours de ce poste", 'calculer')
        else:
            message = QLineEdit(str(poste.params.get('message', '')))
            message.setCursorPosition(0)
            message.setToolTip("Le message de la pause, sur la machine")
            message.editingFinished.connect(
                lambda w=message, i=ident: self.gamme_poste_edited.emit(
                    i, {'params': {'message': w.text()}}))
            _cellule(self._GAMME_COL_OUTIL, message)
            table.setSpan(rang, self._GAMME_COL_OUTIL, 1, 5)
        _bouton(self._GAMME_COL_OEIL, "eye",
                "Montrer / masquer ce poste au canvas", 'apercu')
        _bouton(self._GAMME_COL_CORBEILLE, "delete",
                "Supprimer ce poste", 'supprimer')
        self._gamme_lignes.append(ident)

    def _gamme_action_rang(self, rang: int, action: str):
        lignes = getattr(self, '_gamme_lignes', [])
        if 0 <= rang < len(lignes):
            self.gamme_poste_action.emit(lignes[rang], action)

    def _on_gamme_menu(self, position):
        """Clic droit sur une ligne du tableau: tout ce que les
        boutons font, et le reste."""
        table = getattr(self, '_gamme_table', None)
        if table is None:
            return
        rang = table.rowAt(position.y())
        if rang < 0:
            return
        menu = self._menu_gamme(rang)
        menu.exec(table.viewport().mapToGlobal(position))

    def _menu_gamme(self, rang: int):
        """Le menu d'une ligne du tableau — construit à part pour
        être vérifiable sans l'ouvrir."""
        from PySide6.QtWidgets import QMenu
        menu = QMenu(getattr(self, '_gamme_table', None))
        agrandir_menu(menu)
        for texte, action in (
                ("Ouvrir le formulaire détaillé", 'ouvrir'),
                ("Calculer le parcours de ce poste", 'calculer'),
                (None, None),
                ("⏻ Activer / désactiver", 'basculer'),
                ("👁 Montrer / masquer au canvas", 'apercu'),
                (None, None),
                ("▲ Monter", 'monter'),
                ("▼ Descendre", 'descendre'),
                (None, None),
                ("🗑 Supprimer ce poste", 'supprimer')):
            if texte is None:
                menu.addSeparator()
                continue
            menu.addAction(texte, lambda a=action, r=rang:
                           self._gamme_action_rang(r, a))
        return menu

    def _maj_etats_gamme(self):
        """L'état du parcours de chaque poste: dans l'infobulle du
        titre, et par sa couleur — dimmé tant qu'il est à calculer."""
        table = getattr(self, '_gamme_table', None)
        programme = getattr(self, '_program_ref', None)
        if table is None or programme is None:
            return
        bibliotheque = self._bibliotheque()
        for rang, ident in enumerate(getattr(self, '_gamme_lignes', [])):
            poste = programme.get_operation_by_id(ident)
            if poste is None:
                continue
            try:
                item = table.item(rang, self._GAMME_COL_TITRE)
                if item is None:
                    continue
                if poste.operation_type == "dialogue_operateur":
                    etat = "pause"
                else:
                    etat = self._etat_parcours(poste, bibliotheque)
                item.setToolTip(f"{poste.name}\nParcours: {etat}")
                a_calculer = etat in ("à calculer", "?")
                item.setForeground(QColor(
                    COLORS['text_dim'] if a_calculer else COLORS['text']))
            except RuntimeError:
                return

    def _etat_parcours(self, poste, bibliotheque) -> str:
        """« 12 étapes, reste 0,9 mm² » ou « à calculer »."""
        try:
            from src.operations.registry import OperationRegistry
            from src.operations.gravure_2d5 import params_outil
            classe = OperationRegistry.get(poste.operation_type)
            params = params_outil(poste, bibliotheque)
            plan = classe.plan_si_connu(params)
        except Exception:
            return "?"
        if plan is None:
            return "à calculer"
        if not plan:
            return "rien à faire"
        texte = f"{len(plan)} étape(s)"
        try:
            mesures = classe.mesures(params, calculer=False) or {}
            if 'reste' in mesures:
                texte += f", reste {mesures['reste']:.2f} mm²"
        except Exception:
            pass
        return texte

    def _maj_champs_cadre(self):
        """Marge OU dimensions: l'autre réglage se grise. Et en creux,
        tout le cadre se grise."""
        from src.operations.gravure_2d5 import CADRE_PAR_DIMENSIONS
        try:
            relief = (self._widgets['mode'].currentText() == "Relief"
                      if 'mode' in self._widgets else True)
            par_dimensions = (self._widgets['cadre_mode'].currentText()
                              == CADRE_PAR_DIMENSIONS)
            for cle, actif in (('cadre_mode', relief),
                               ('cadre_marge', relief and not par_dimensions),
                               ('cadre_largeur', relief and par_dimensions),
                               ('cadre_hauteur', relief and par_dimensions),
                               ('cadre_rayon', relief),
                               ('pres_du_trait', relief)):
                widget = self._widgets.get(cle)
                if widget is not None:
                    widget.setEnabled(bool(actif))
        except (RuntimeError, KeyError):
            pass

    def _maj_resume_contours(self, op):
        """Ligne d'état: ce qui est relevé, ce que le calcul donne."""
        label = getattr(self, '_contours_info', None)
        if label is None or op is None:
            return
        contours = op.params.get('contours') or []
        if not contours:
            texte = "Aucun contour relevé"
        elif op.operation_type == "gamme_gravure":
            sommets = sum(len(c) for c in contours)
            origine = ("du texte" if str(op.params.get('texte') or "")
                       .strip() else "relevés")
            texte = (f"{len(contours)} contour(s) {origine}, "
                     f"{sommets} sommet(s) — partagés par tous les "
                     f"postes")
        else:
            sommets = sum(len(c) for c in contours)
            texte = f"{len(contours)} contour(s), {sommets} sommet(s)"
            try:
                from src.operations.registry import OperationRegistry
                classe = OperationRegistry.get(op.operation_type)
                from src.operations.gravure_2d5 import params_outil
                self._chainer_la_gamme()
                params = params_outil(op, self._bibliotheque())
                texte += " — " + classe.resume(params, calculer=False)
            except Exception as exc:
                texte += f" — calcul impossible: {str(exc)[:40]}"
        try:
            label.setText(texte)
        except RuntimeError:
            pass

    def _on_calculer_parcours(self):
        """Calcule le parcours de l'opération courante, et le montre.

        C'est le seul endroit qui lance le calcul: partout ailleurs,
        on se contente de ce qui est déjà connu."""
        from src.operations.registry import OperationRegistry
        op = self._current_op
        if op is None:
            return
        try:
            classe = OperationRegistry.get(op.operation_type)
        except KeyError:
            return
        # La gamme d'abord: si cette opération reprend le reste
        # d'une autre, il faut savoir laquelle avant de calculer.
        # (Le programme s'appelle `_program_ref` ICI: écrit
        # `self.program`, l'AttributeError partait dans un except
        # muet et la reprise ne se faisait jamais depuis le bouton.)
        self._chainer_la_gamme()
        from src.gui.progression import Progression
        from src.operations.gravure_2d5 import params_outil
        params = params_outil(op, self._bibliotheque())
        # Plus de curseur d'attente muet: une fenêtre dit où en est
        # le calcul, et son bouton Annuler arrête vraiment — rien
        # n'entre au cache d'un calcul interrompu.
        try:
            def _travail(barre):
                classe.plan(params, progression=barre.sous(
                    0.0, 0.7, "parcours — "))
                classe.mesures(params, calculer=True,
                               progression=barre.sous(
                                   0.7, 1.0, "mesure — "))

            # dans un fil de travail: un appel C de trente secondes
            # ne gèle plus l'interface, et Annuler répond
            with Progression(self, "Calcul du parcours",
                             op.name or "parcours") as barre:
                barre.executer(_travail)
        except Exception as exc:
            QMessageBox.warning(
                self, "Calcul du parcours",
                f"Le parcours n'a pas pu être calculé:\n{exc}")
            return
        if barre.annule:
            return
        self._maj_resume_contours(op)
        # Le canvas montre ce qui vient d'être calculé
        fenetre = self.window()
        redessiner = getattr(fenetre, '_refresh_canvas_op', None)
        if redessiner is not None:
            redessiner()

    def _chainer_la_gamme(self) -> int:
        """Dit à chaque gravure ce que les précédentes ont laissé.

        Rend le nombre d'opérations qui reprennent quelque chose."""
        from src.operations.gravure_2d5 import chainer
        programme = getattr(self, '_program_ref', None)
        if programme is None:
            return 0
        return chainer(programme.operations, self._bibliotheque())

    def _on_calculer_gamme(self):
        """Calcule les parcours des postes de la gamme, dans l'ordre.

        Une barre dit où en est le calcul et permet de l'arrêter: sur
        une gamme de quatre outils et un logo dense, c'est une
        poignée de secondes pendant lesquelles l'application ne doit
        pas avoir l'air figée."""
        from src.codegen.generator import SimPlGenerator
        from src.operations.gravure_2d5 import params_outil
        from src.operations.registry import OperationRegistry
        from src.operations.gamme_gravure import GammeGravure
        programme = getattr(self, '_program_ref', None)
        tete = self._current_op
        if programme is None or tete is None:
            return
        if GammeGravure.est_tete(tete):
            candidates = GammeGravure.membres(tete, programme.operations)
        else:
            # hors gamme: les parcours libres du programme, qui se
            # chaînent entre eux par leur dessin
            candidates = [op for op in programme.operations
                          if not getattr(op, 'group_id', '')]
        ops = [op for op in candidates
               if op.enabled
               and op.operation_type in SimPlGenerator.SEQ_CALCULEES]
        if not ops:
            return
        from src.gui.progression import Progression
        bibliotheque = self._bibliotheque()
        self._chainer_la_gamme()
        echecs = []

        def _travail(barre):
            for index, op in enumerate(ops):
                nom = op.name or op.operation_type
                debut, fin = index / len(ops), (index + 1) / len(ops)
                etiquette = f"{nom} ({index + 1}/{len(ops)}) — "
                try:
                    classe = OperationRegistry.get(op.operation_type)
                    params = params_outil(op, bibliotheque)
                    # le parcours prend les sept dixièmes de la
                    # tranche, la mesure le reste: la barre ne
                    # revient jamais en arrière
                    classe.plan(params, progression=barre.sous(
                        debut, debut + 0.7 * (fin - debut), etiquette))
                    classe.mesures(params, calculer=True,
                                   progression=barre.sous(
                                       debut + 0.7 * (fin - debut), fin,
                                       etiquette + "mesure — "))
                except Exception as exc:
                    echecs.append(f"{nom}: {str(exc)[:60]}")

        with Progression(self, "Gamme de gravure",
                         "Calcul des parcours…") as barre:
            barre.executer(_travail)
        self._rafraichir_apres_calcul()
        if echecs:
            QMessageBox.warning(
                self, "Calcul des parcours",
                "Parcours non calculés:\n" + "\n".join(echecs))

    def _rafraichir_apres_calcul(self):
        """Ce qui doit suivre un calcul: l'état, le dessin, le code."""
        if self._current_op is not None:
            try:
                self._maj_resume_contours(self._current_op)
                self._maj_etats_gamme()
                self._maj_barre_calcul()
            except Exception:
                pass
        fenetre = self.window()
        redessiner = getattr(fenetre, '_refresh_canvas_op', None)
        if callable(redessiner):
            redessiner()
        planifier = getattr(fenetre, '_schedule_regen', None)
        if callable(planifier):
            planifier()

    def _bibliotheque(self):
        """La bibliothèque d'outils de la fenêtre, ou None."""
        return getattr(self.window(), 'tool_library', None)

    def _nom_outil(self, op) -> str:
        """Nom de l'outil monté sur cette opération, ou vide."""
        lib = self._bibliotheque()
        outil = (lib.get_tool(op.tool_id)
                 if lib is not None and getattr(op, 'tool_id', '')
                 else None)
        return outil.name if outil is not None else ""

    def _on_contours_pickup(self):
        """Copie les tracés sélectionnés dans l'opération conique."""
        if self._current_op is None:
            return
        canvas = getattr(getattr(self.window(), 'dxf_panel', None),
                         'canvas', None)
        contours = []
        if canvas is not None:
            try:
                contours = canvas.selected_polylines()
            except Exception:
                contours = []
        fermes = [c for c in contours if len(c) >= 3]
        if not fermes:
            QMessageBox.information(
                self, "Contours du dessin",
                "Sélectionnez au canvas les tracés à graver "
                "(au moins un contour fermé de trois sommets), puis "
                "reprenez-les.")
            return
        op = self._current_op
        op.params['contours'] = [
            [[round(x, 4), round(y, 4)] for x, y in contour]
            for contour in fermes]
        if op.operation_type == "ebavurage":
            op.params['forme'] = "Contours"
            widget = self._widgets.get('forme')
            if widget is not None and hasattr(widget, 'setCurrentText'):
                widget.blockSignals(True)
                widget.setCurrentText("Contours")
                widget.blockSignals(False)
        # La géométrie du cône se lit dans le nom de l'outil: on la
        # pose si l'utilisateur ne l'a pas déjà fixée
        from src.core import vcarve
        if op.operation_type != "gamme_gravure":
            angle, troncature = vcarve.cone_depuis_nom(
                self._nom_outil(op))
            op.params.setdefault('angle', angle)
            op.params.setdefault('troncature', troncature)
        self._maj_resume_contours(op)
        self._on_param_changed()
        # Les contours ont changé: le parcours d'avant ne vaut plus
        fenetre = self.window()
        redessiner = getattr(fenetre, '_refresh_canvas_op', None)
        if redessiner is not None:
            redessiner()

    def _on_trace_pickup(self):
        """Copie la polyligne sélectionnée dans le parcours du tracé."""
        if self._current_op is None:
            return
        canvas = getattr(getattr(self.window(), 'dxf_panel', None),
                         'canvas', None)
        pts = []
        fermes = []
        if canvas is not None:
            try:
                fermes = [c for c in canvas.selected_polylines()
                          if len(c) >= 3]
            except Exception:
                fermes = []
            try:
                pts = canvas.selected_polyline()
            except Exception:
                pts = []
        if len(fermes) > 1:
            # plusieurs contours: tous, chacun fermé
            pts = list(fermes[0])
        if len(pts) < 2:
            QMessageBox.information(
                self, "Contour du dessin",
                "Sélectionnez UNE polyligne (ou un rectangle) au "
                "canvas, en mode Sélection, avant de reprendre son "
                "contour.")
            return
        op = self._current_op
        op.params['path_points'] = [
            [round(x, 4), round(y, 4)] for x, y in pts]
        op.params['contours'] = [
            [[round(x, 4), round(y, 4)] for x, y in c] for c in fermes
        ] if len(fermes) > 1 else []
        lab = getattr(self, '_trace_pickup_info', None)
        if lab is not None:
            try:
                lab.setText(f"{len(fermes)} contour(s) relevé(s)"
                            if len(fermes) > 1
                            else f"{len(pts)} sommet(s) relevés")
            except RuntimeError:
                pass
        self._on_param_changed()
        # Un contour relevé, c'est la forme « Dessin »: le formulaire
        # change, donc on le refait après le clic
        if str(op.params.get('shape')) == "Texte":
            # le texte suivra ce contour
            op.params['disposition_fil'] = "Le long du dessin"
            QTimer.singleShot(0, lambda: self._rebuild_trace_form(op))
        elif str(op.params.get('shape')) != "Dessin":
            op.params['shape'] = "Dessin"
            QTimer.singleShot(0, lambda: self._rebuild_trace_form(op))

    def _build_bloc_tool_selector(self, op):
        """Outil du bloc importé, EN TÊTE du formulaire: c'est lui qui
        commande régime et avances, tout le reste en découle."""
        p = op.params
        box = QGroupBox("Outil")
        v = QVBoxLayout()
        v.setSpacing(2)
        v.setContentsMargins(4, 8, 4, 4)

        origin = p.get('_tool', '')
        if origin:
            # Le fichier nomme souvent l'outil en clair dans le
            # commentaire de sa ligne Tool: c'est parfois la seule
            # indication lisible quand la référence est inconnue
            comment = str(p.get('_tool_comment', '') or '').strip()
            txt = f"Outil d'origine : {origin}"
            if comment and comment != origin:
                txt += f"  ·  « {comment} »"
            article = str(p.get('_article', '') or '')
            known = self._tool_by_article(article) if article else None
            if known is not None and known.name not in txt:
                txt += f"  ·  tools.json : {known.name}"
            lab = QLabel(txt)
            lab.setWordWrap(True)
            lab.setStyleSheet(
                f"color: {COLORS['text_dim']}; font-size: 10px;")
            v.addWidget(lab)

        combo = NoScrollComboBox()
        combo.addItem("(outil d'origine)", "")
        if self._tool_library:
            for tool in self._tool_library.get_all_tools():
                combo.addItem(
                    f"{tool.name} [{tool.article_nr}]",
                    tool.article_nr)
        current = str(p.get('tool_article', '') or '')
        if current:
            idx = combo.findData(current)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        combo.setToolTip(
            "Remplace l'outil du bloc. Les avances et le régime de "
            "l'outil choisi sont appliqués au sous-programme.")
        combo.currentIndexChanged.connect(
            lambda _i, c=combo: self._on_bloc_tool_changed(c))
        self._bloc_tool_combo = combo

        # Retrouver l'outil de MEME REFERENCE dans tools.json: le
        # derouler a la main dans une liste de cent outils est long,
        # alors qu'il n'y a rien a changer dans la sequence
        from src.gui.icons import get_button_icon
        ligne = QHBoxLayout()
        ligne.setContentsMargins(0, 0, 0, 0)
        ligne.setSpacing(4)
        ligne.addWidget(combo, 1)
        find_btn = QPushButton("")
        find_btn.setIcon(get_button_icon("toolbox", 16))
        find_btn.setFixedSize(26, 24)
        find_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        find_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ref_origine = str(p.get('_article', '') or '')
        if ref_origine:
            find_btn.setToolTip(
                f"Selectionner l'outil de reference {ref_origine} "
                f"(celle du programme importe)".replace(
                    "Selectionner", "S\u00e9lectionner"))
        else:
            find_btn.setToolTip(
                "Aucune r\u00e9f\u00e9rence d'outil dans le bloc import\u00e9")
            find_btn.setEnabled(False)
        find_btn.clicked.connect(self._on_bloc_find_tool)
        self._bloc_find_btn = find_btn
        ligne.addWidget(find_btn)
        v.addLayout(ligne)

        spec_lab = QLabel("")
        spec_lab.setWordWrap(True)
        spec_lab.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 10px;")
        v.addWidget(spec_lab)
        self._bloc_tool_specs = spec_lab
        self._update_bloc_tool_specs(current, p)

        # Reprendre régime et avances de tools.json SANS changer
        # d'outil: le bloc garde souvent le bon outil avec des
        # réglages datant du programme d'origine
        apply_btn = QPushButton("↺ Régime et avances de tools.json")
        apply_btn.setMaximumHeight(22)
        apply_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        apply_btn.setToolTip(
            "Recopie le régime et les cinq avances de l'outil "
            "(celui choisi, sinon celui d'origine s'il est connu de "
            "tools.json) dans les champs du formulaire")
        apply_btn.clicked.connect(self._on_bloc_apply_library_feeds)
        v.addWidget(apply_btn)

        box.setLayout(v)
        self._layout.addWidget(box)

    def _build_bloc_simpl_summary(self, op):
        """Ce que contient réellement le bloc, réglages appliqués.

        Le contenu est recalculé à partir du code RÉELLEMENT émis, et
        montre origine → valeur courante pour tout ce que
        l'utilisateur a changé: sans cela on règle un programme validé
        sans voir ce qu'on lui fait."""
        p = op.params
        box = QGroupBox("Contenu du bloc")
        v = QVBoxLayout()
        v.setSpacing(2)
        v.setContentsMargins(4, 8, 4, 4)

        kind = p.get('_kind', 'inconnu')
        kind_txt = {'sequence': "appel de séquence",
                    'function': p.get('_function') or "fonction",
                    'inconnu': "contenu non reconnu"}.get(kind, kind)
        head = QLabel(f"{p.get('sub_name', '?')} — {kind_txt}")
        head.setWordWrap(True)
        head.setStyleSheet(
            f"color: {COLORS['text']}; font-size: 10px; "
            f"font-weight: bold;")
        v.addWidget(head)

        if p.get('source_file'):
            src = QLabel(f"Fichier : {p['source_file']}")
            src.setWordWrap(True)
            src.setStyleSheet(
                f"color: {COLORS['text_dim']}; font-size: 10px;")
            v.addWidget(src)

        detail = QLabel("")
        detail.setWordWrap(True)
        detail.setTextFormat(Qt.TextFormat.RichText)
        detail.setStyleSheet(
            f"color: {COLORS['text']}; font-size: 10px;")
        v.addWidget(detail)
        self._bloc_detail = detail

        box.setLayout(v)
        self._layout.addWidget(box)
        self._update_bloc_summary()

    # ── Contenu du bloc: avant / après ──

    @staticmethod
    def _fmt_change(before, after, unit: str = "") -> str:
        """« 40000 » si rien ne change, « 40000 → 25000 » sinon."""
        b = "" if before in (None, "") else f"{before:g}" \
            if isinstance(before, float) else str(before)
        a = "" if after in (None, "") else f"{after:g}" \
            if isinstance(after, float) else str(after)
        if not a or a == b:
            return f"{b}{unit}" if b else ""
        arrow = f'<span style="color:{COLORS["yellow"]}">&#8594;</span>'
        if not b:
            return f"{arrow} <b>{a}{unit}</b>"
        return f"{b}{unit} {arrow} <b>{a}{unit}</b>"

    def _bloc_after_state(self, params: dict) -> dict:
        """État réel du bloc une fois les réglages appliqués.

        Lu sur le code émis, pas recalculé en parallèle: ce que la
        fiche affiche est ce qui partira à la machine."""
        from src.operations.bloc_simpl import BlocSimpl
        from src.io import simpl_batch as sb
        out = {'tool': '', 'rpm': None, 'feeds': {}, 'levels': [],
               'params': {}, 'bounds': None, 'seq_lines': 0}
        body = BlocSimpl.body(params)
        name = BlocSimpl.effective_name(params)
        if body.strip():
            info = _analyse_memo(body, name)
            out['tool'] = info.get('tool', '')
            out['rpm'] = info.get('rpm')
            out['feeds'] = info.get('feeds') or {}
            out['params'] = info.get('params') or {}
        seq = BlocSimpl.sequence_block(params)
        if seq.strip():
            out['seq_lines'] = seq.count('\n')
            out['levels'] = _passes_memo(
                seq, str(params.get('sequence_name', '')))
        out['bounds'] = self._bloc_bounds(
            {'body': body, 'sequence_code': seq})
        return out

    def _update_bloc_summary(self):
        """Recalcule la fiche du bloc pour les réglages courants."""
        detail = getattr(self, '_bloc_detail', None)
        if detail is None or self._current_op is None:
            return
        try:
            params = self._collect_params()
        except (RuntimeError, AttributeError):
            params = dict(self._current_op.params)
        p = dict(self._current_op.params)
        p.update(params)
        try:
            after = self._bloc_after_state(p)
        except Exception:
            detail.setText("")
            return
        rows = []
        # Outil: la référence choisie remplace le nom d'origine
        origin_tool = str(p.get('_tool', '') or '')
        after_tool = after['tool']
        known = self._tool_by_article(after_tool)
        if known is not None:
            after_tool = f"{known.name} [{after_tool}]"
        if origin_tool or after_tool:
            rows.append("Outil : " + self._fmt_change(
                origin_tool, after_tool))
        rows.append("Régime : " + self._fmt_change(
            p.get('_rpm_origin') or "", after['rpm'] or "", " tr/min"))
        origin_feeds = p.get('_feeds') or {}
        feed_bits = []
        for key in ('finishing', 'approach', 'plunge', 'ramp',
                    'roughing'):
            b, a = origin_feeds.get(key), after['feeds'].get(key)
            if b is None and a is None:
                continue
            txt = self._fmt_change(b or "", a or "")
            if txt:
                feed_bits.append(f"{key} {txt}")
        if feed_bits:
            rows.append("Avances : " + " · ".join(feed_bits))

        # Étendue et profondeur, lues sur le code émis
        origin_bounds = self._bloc_bounds(p)
        if after['bounds']:
            (x0, x1), (y0, y1), zmin = after['bounds']
            rows.append(f"Étendue X {x0:g} → {x1:g}  ·  "
                        f"Y {y0:g} → {y1:g}")
            z_before = origin_bounds[2] if origin_bounds else None
            if zmin is not None:
                rows.append("Profondeur maxi : " + self._fmt_change(
                    z_before, zmin, " mm"))

        # Paramètres de la fonction Datron (depth, infeedZ...)
        origin_params = p.get('_params') or {}
        keys = list(origin_params.keys()) or list(after['params'].keys())
        if keys:
            bits = []
            for key in keys[:8]:
                txt = self._fmt_change(origin_params.get(key, ""),
                                       after['params'].get(key, ""))
                if txt:
                    bits.append(f"{key}={txt}")
            if bits:
                rows.append("Paramètres : " + "  ".join(bits))

        # Séquence appelée et ses passes
        seq_name = str(p.get('sequence_name', '') or '')
        if seq_name:
            origin_seq = str(p.get('sequence_code', '') or '')
            if origin_seq.strip():
                rows.append(f"Séquence {seq_name} — "
                            f"{after['seq_lines']} lignes")
                before_levels = _passes_memo(origin_seq, seq_name)
                after_levels = after['levels']
                if 0 < len(after_levels) <= 12:
                    # Séparateur « · » et non « → »: la flèche est
                    # réservée au changement, sinon on ne sait plus
                    # lire quelle liste est laquelle
                    txt = " · ".join(f"{z:g}" for z in after_levels)
                    if after_levels != before_levels:
                        old = " · ".join(f"{z:g}" for z in before_levels)
                        rows.append("Passes Z : " + self._fmt_change(
                            old, txt))
                    else:
                        rows.append(
                            f"Passes Z ({len(after_levels)}) : {txt}")
                elif after_levels:
                    rows.append(
                        f"Profil 3D — Z de {after_levels[0]:g} à "
                        f"{after_levels[-1]:g} "
                        f"({len(after_levels)} valeurs)")
            else:
                # Le bloc $$$ vit dans un autre fichier: le signaler
                # plutôt que d'afficher « 0 lignes »
                rows.append(f"Séquence {seq_name} — définie hors de "
                            f"ce fichier")

        detail.setText("<br>".join(r for r in rows if r.strip()))

    def _tool_by_article(self, article: str):
        if not article or not self._tool_library:
            return None
        return self._tool_library.get_tool_by_article(article)

    def _update_bloc_tool_specs(self, article: str, params: dict):
        """Affiche Ø, Pz max, régime et avances de l'outil retenu."""
        lab = getattr(self, '_bloc_tool_specs', None)
        if lab is None:
            return
        tool = self._tool_by_article(article)
        if tool is None:
            origin = str(params.get('_tool', '') or '')
            known = None
            if origin and self._tool_library:
                known = (self._tool_library.get_tool_by_article(origin)
                         or next((t for t in
                                  self._tool_library.get_all_tools()
                                  if t.name == origin), None))
            if known is None:
                lab.setText("Outil hors bibliothèque : specs inconnues")
                return
            tool = known
        specs = [f"Rpm {tool.rpm}"]
        if tool.diameter:
            specs.append(f"Ø{tool.diameter:g}")
        if tool.max_depth:
            specs.append(f"Pz max {tool.max_depth:g}")
        geo = getattr(tool, 'geometry', {}) or {}
        if geo.get('NumberOfFlutes'):
            specs.append(f"{int(geo['NumberOfFlutes'])} dents")
        feeds = (f"fin {tool.feed_finishing} · appr "
                 f"{tool.feed_approach} · plg {tool.feed_plunge} · "
                 f"rmp {tool.feed_ramp} · ébau {tool.feed_roughing}")
        lab.setText("  ·  ".join(specs) + "\n" + feeds)

    def _set_bloc_field(self, key: str, value):
        """Écrit dans le WIDGET, pas seulement dans les params:
        _collect_params relit les champs et écraserait la valeur."""
        widget = self._widgets.get(key)
        if widget is not None and hasattr(widget, 'setValue'):
            widget.setValue(int(value))
        elif self._current_op is not None:
            self._current_op.params[key] = int(value)

    def _bloc_effective_tool(self, params: dict):
        """Outil de référence d'un bloc: celui choisi, sinon celui
        d'origine s'il est connu de tools.json."""
        article = str(params.get('tool_article', '') or '')
        tool = self._tool_by_article(article) if article else None
        if tool is not None:
            return tool
        origin = str(params.get('_article', '')
                     or params.get('_tool', '') or '')
        if not origin or not self._tool_library:
            return None
        return (self._tool_library.get_tool_by_article(origin)
                or next((t for t in self._tool_library.get_all_tools()
                         if t.name == origin), None))

    def _on_bloc_apply_library_feeds(self):
        """Recopie régime et avances de tools.json dans le formulaire."""
        if self._current_op is None:
            return
        tool = self._bloc_effective_tool(self._current_op.params)
        if tool is None:
            QMessageBox.information(
                self, "Avances de tools.json",
                "L'outil de ce bloc n'est pas dans tools.json: "
                "aucune valeur à reprendre.\nChoisissez un outil "
                "dans la liste ci-dessus.")
            return
        self._set_bloc_field('rpm', tool.rpm)
        for key, val in (('feed_finishing', tool.feed_finishing),
                         ('feed_approach', tool.feed_approach),
                         ('feed_plunge', tool.feed_plunge),
                         ('feed_ramp', tool.feed_ramp),
                         ('feed_roughing', tool.feed_roughing)):
            self._set_bloc_field(key, val)
        self._on_param_changed()

    def _on_bloc_find_tool(self):
        """Loupe: pointe le combo sur l'outil de meme reference.

        La sequence n'a rien a changer — seul le sous-programme porte
        l'outil, le regime et les avances."""
        op = self._current_op
        combo = getattr(self, '_bloc_tool_combo', None)
        if op is None or combo is None:
            return
        ref = str(op.params.get('_article', '') or '').strip()
        if not ref:
            return
        index = combo.findData(ref)
        if index < 0:
            outil = self._tool_by_article(ref)
            QMessageBox.information(
                self, "Outil du bloc",
                f"La r\u00e9f\u00e9rence {ref} du programme import\u00e9 n'est pas "
                f"dans tools.json."
                if outil is None else
                f"L'outil {outil.name} [{ref}] n'est pas propos\u00e9 par "
                f"la liste.")
            return
        combo.setCurrentIndex(index)

    def _on_bloc_tool_changed(self, combo):
        """Applique l'outil choisi au bloc (avances et régime suivis).

        Changer d'outil remplace la ligne d'avances du bloc par la
        ligne complète de tools.json — l'utilisateur reste libre de
        retoucher chaque champ ensuite."""
        if self._suppressing_signals or self._current_op is None:
            return
        article = combo.currentData() or ""
        params = self._current_op.params
        tool = self._tool_by_article(article)
        if tool is not None:
            params['tool_article'] = article
            params['tool_label'] = tool.name
            self._set_bloc_field('rpm', tool.rpm)
            for key, val in (
                    ('feed_finishing', tool.feed_finishing),
                    ('feed_approach', tool.feed_approach),
                    ('feed_plunge', tool.feed_plunge),
                    ('feed_ramp', tool.feed_ramp),
                    ('feed_roughing', tool.feed_roughing)):
                self._set_bloc_field(key, val)
        else:
            for key in ('tool_article', 'tool_label', 'tool_feeds'):
                params.pop(key, None)
        self._update_bloc_tool_specs(article, params)
        self._on_param_changed()

    @staticmethod
    def _bloc_bounds(params: dict):
        """Étendue X/Y et Z mini réellement usinés par le bloc (lue une
        fois par texte: voir `_bornes_memo`)."""
        text = str(params.get('body', '') or '') + "\n" + \
            str(params.get('sequence_code', '') or '')
        return _bornes_memo(text)

    @staticmethod
    def _bornes_du_texte(text: str):
        import re as _re
        xs, ys, zs = [], [], []
        for m in _re.finditer(r'\bX\s*=\s*([-+]?[\d.]+)', text):
            xs.append(float(m.group(1)))
        for m in _re.finditer(r'\bY\s*=\s*([-+]?[\d.]+)', text):
            ys.append(float(m.group(1)))
        for m in _re.finditer(r'\bZ\s*=\s*([-+]?[\d.]+)', text):
            z = float(m.group(1))
            if z < 0:
                zs.append(z)
        for m in _re.finditer(r'\bdepth\s*=\s*([\d.]+)', text):
            zs.append(-float(m.group(1)))
        if not xs or not ys:
            return None
        return ((min(xs), max(xs)), (min(ys), max(ys)),
                min(zs) if zs else None)

    # ── Saisie opérateur (InputDialog) ──

    def _available_user_variables(self) -> list:
        """Variables déclarées par les opérations du programme courant
        (saisie opérateur, compteur de pièces)."""
        from src.operations.compteur_pieces import CompteurPieces
        from src.operations.parametres_operateur import (
            ParametresOperateur)
        providers = {
            "parametres_operateur": ParametresOperateur,
            "compteur_pieces": CompteurPieces,
        }
        out = []
        prog = getattr(self, '_program_ref', None)
        if prog is None:
            return out
        for other in prog.operations:
            cls = providers.get(other.operation_type)
            if cls is None:
                continue
            for var, _t in cls.declared_variables(other.params):
                if var not in out:
                    out.append(var)
        return out

    def _build_operator_fields_section(self, op):
        from src.operations.parametres_operateur import PARAM_TYPES
        box = QGroupBox("Champs de saisie")
        v = QVBoxLayout()
        v.setSpacing(4)
        v.setContentsMargins(4, 8, 4, 4)
        box.setLayout(v)
        self._opfields_vbox = v
        self._opfield_rows = []
        self._opfield_types = list(PARAM_TYPES.keys())
        self._rebuild_operator_fields(
            [dict(f) for f in (op.params.get('fields') or [])])
        self._layout.addWidget(box)

    def _rebuild_operator_fields(self, data: list):
        v = self._opfields_vbox
        while v.count():
            item = v.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._opfield_rows = []
        hdr = QLabel("Variable · Type · Libellé affiché · Défaut · Unité")
        hdr.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 10px;")
        v.addWidget(hdr)
        for i, f in enumerate(data):
            v.addWidget(self._make_operator_field_row(f, i))
        add = QPushButton("+ Champ de saisie")
        add.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        add.setStyleSheet(
            "QPushButton { background: #313244; color: #94e2d5; "
            "padding: 4px 8px; border-radius: 4px; font-size: 11px; }"
            "QPushButton:hover { background: #45475a; }")
        add.clicked.connect(self._on_add_operator_field)
        v.addWidget(add)

    def _make_operator_field_row(self, f: dict, num: int) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(3)
        var = QLineEdit(str(f.get('var', '')))
        var.setPlaceholderText("variable")
        var.setMaximumWidth(90)
        var.editingFinished.connect(self._on_param_changed)
        combo = NoScrollComboBox()
        combo.addItems(self._opfield_types)
        combo.setCurrentText(f.get('type', 'Position'))
        combo.setMaximumWidth(90)
        combo.currentIndexChanged.connect(self._on_param_changed)
        label = QLineEdit(str(f.get('label', '')))
        label.setPlaceholderText("libellé affiché")
        label.editingFinished.connect(self._on_param_changed)
        default = QLineEdit(str(f.get('default', '')))
        default.setPlaceholderText("défaut")
        default.setMaximumWidth(70)
        default.editingFinished.connect(self._on_param_changed)
        unit = QLineEdit(str(f.get('unit', '')))
        unit.setPlaceholderText("unité")
        unit.setMaximumWidth(55)
        unit.editingFinished.connect(self._on_param_changed)
        rm = QPushButton("✕")
        rm.setFixedSize(20, 20)
        rm.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        rm.setStyleSheet(
            f"QPushButton {{ border: none; background: transparent; "
            f"color: {COLORS['text_dim']}; font-weight: bold; }}"
            f"QPushButton:hover {{ color: {COLORS['red']}; }}")
        rm.clicked.connect(
            lambda _=False, n=num: self._on_remove_operator_field(n))
        for w in (var, combo, label, default, unit, rm):
            h.addWidget(w)
        self._opfield_rows.append(
            {'var': var, 'type': combo, 'label': label,
             'default': default, 'unit': unit})
        return row

    def _read_operator_fields(self) -> list:
        out = []
        for r in self._opfield_rows:
            try:
                out.append({
                    'var': r['var'].text().strip(),
                    'type': r['type'].currentText(),
                    'label': r['label'].text().strip(),
                    'default': r['default'].text().strip(),
                    'unit': r['unit'].text().strip(),
                })
            except RuntimeError:
                continue
        return out

    def _on_add_operator_field(self):
        data = self._read_operator_fields()
        n = len(data) + 1
        data.append({'var': f"param{n}", 'type': 'Position',
                     'label': f"Paramètre {n}", 'default': '0',
                     'unit': ''})
        self._rebuild_operator_fields(data)
        self._on_param_changed()

    def _on_remove_operator_field(self, num: int):
        data = self._read_operator_fields()
        if 0 <= num < len(data):
            del data[num]
            self._rebuild_operator_fields(data)
            self._on_param_changed()

    def _build_variable_binding_section(self, op):
        """Section « Variables opérateur »: relie une cote de cette
        opération à une variable saisie au lancement. Seuls les
        paramètres qui propagent RÉELLEMENT la variable dans le code
        généré sont proposés (vérifié par sondage)."""
        self._var_bind_widgets = {}
        self._text_var_combo = None
        if not self._expert_mode:
            return          # fonctionnalité expert
        variables = self._available_user_variables()
        if not variables:
            return
        # Gravure: concaténer une variable au texte (n° de série...)
        if op.operation_type == "gravure_texte":
            gbox = QGroupBox("Variable dans le texte")
            gbox.setToolTip(
                "Ajoute au texte gravé la valeur d'une variable "
                "(numéro de série, saisie opérateur...)")
            gl = QHBoxLayout()
            gl.setContentsMargins(4, 8, 4, 4)
            combo = NoScrollComboBox()
            combo.addItem("(aucune)", "")
            for v in variables:
                combo.addItem(v, v)
            cur = str(op.params.get('text_var', '') or '')
            if cur:
                idx = combo.findData(cur)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            combo.currentIndexChanged.connect(self._on_param_changed)
            self._text_var_combo = combo
            gl.addWidget(QLabel("Concaténer :"))
            gl.addWidget(combo, stretch=1)
            gbox.setLayout(gl)
            self._layout.addWidget(gbox)
        from src.codegen.generator import variable_capable_params
        capable = variable_capable_params(op.operation_type)
        if not capable:
            return
        try:
            op_class = OperationRegistry.get(op.operation_type)
        except KeyError:
            return
        bound = op.params.get('param_vars') or {}
        box = QGroupBox("Variables opérateur")
        box.setToolTip(
            "Remplace une cote fixe par une valeur saisie par "
            "l'opérateur au lancement du programme")
        grid = QGridLayout()
        grid.setSpacing(3)
        grid.setContentsMargins(4, 8, 4, 4)
        row = 0
        for pdef in op_class.get_parameters():
            if pdef.key not in capable:
                continue
            if pdef.expert_only and not self._expert_mode:
                continue
            lab = QLabel(pdef.label)
            lab.setStyleSheet(
                f"color: {COLORS['text_dim']}; font-size: 10px;")
            combo = NoScrollComboBox()
            combo.addItem("(valeur fixe)", "")
            for v in variables:
                combo.addItem(v, v)
            cur = str(bound.get(pdef.key, '') or '')
            if cur:
                idx = combo.findData(cur)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            combo.currentIndexChanged.connect(self._on_param_changed)
            self._var_bind_widgets[pdef.key] = combo
            grid.addWidget(lab, row, 0)
            grid.addWidget(combo, row, 1)
            row += 1
        if row == 0:
            return
        box.setLayout(grid)
        self._layout.addWidget(box)

    def _rebuild_instance_widgets(self, data: list):
        """(Re)construit les sous-formulaires d'instances + bouton +."""
        v = self._instances_vbox
        while v.count():
            item = v.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._instance_rows = []
        self._instance_count_hint = len(data)
        if data:
            # Récapitulatif: l'opération elle-même est l'instance 1
            info = QLabel(
                f"{len(data) + 1} instances dans le sous-programme "
                f"(1 = formulaire ci-dessus)")
            info.setStyleSheet(
                f"color: {COLORS['text_dim']}; font-size: 10px;")
            v.addWidget(info)
        for i, inst in enumerate(data):
            v.addWidget(self._make_instance_widget(inst, i))
        add_btn = QPushButton("+ Instance similaire")
        add_btn.setToolTip(
            "Ajoute une instance avec Position/Dimension/rayon/Pz/"
            "finition/répétition propres, usinée dans le même "
            "sous-programme (1er déplacement SafeRapid, suivants Rapid)")
        add_btn.setStyleSheet(
            "QPushButton { background: #313244; color: #94e2d5; "
            "padding: 4px 8px; border-radius: 4px; font-size: 11px; }"
            "QPushButton:hover { background: #45475a; }")
        add_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        add_btn.clicked.connect(self._on_add_instance)
        v.addWidget(add_btn)

    def _read_instance_rows(self) -> list:
        out = []
        for row in self._instance_rows:
            inst = {}
            for key, w in row.items():
                try:
                    inst[key] = w.value()
                except RuntimeError:
                    inst = None
                    break
            if inst is not None:
                out.append(inst)
        return out

    def _main_form_value(self, key: str, default: float) -> float:
        w = self._widgets.get(key)
        if w is not None and hasattr(w, 'value'):
            try:
                return float(w.value())
            except (RuntimeError, TypeError, ValueError):
                pass
        return default

    def _on_add_instance(self):
        """Ajoute une instance pré-remplie depuis le formulaire
        principal, décalée en X de dimX + 10 mm."""
        if self._instances_vbox is None:
            return
        data = self._read_instance_rows()
        wx = self._main_form_value('width_x', 10.0)
        x0 = 0.0
        y0 = 0.0
        try:
            if 'x' in self._coord_widgets:
                x0 = float(self._coord_widgets['x'].value())
            if 'y' in self._coord_widgets:
                y0 = float(self._coord_widgets['y'].value())
        except RuntimeError:
            pass
        if data:
            # Partir de la dernière instance plutôt que du form principal
            last = data[-1]
            x0 = float(last.get('pos_x', x0))
            y0 = float(last.get('pos_y', y0))
            wx = float(last.get('width_x', wx))
        inst = {
            'pos_x': x0 + wx + 10.0,
            'pos_y': y0,
            'width_x': wx,
            'width_y': self._main_form_value('width_y', 10.0),
            'depth': self._main_form_value('depth', 1.0),
            'finishing': self._main_form_value(
                self._instance_finish_key(), 0.0),
            'repeat_x_count': 1, 'repeat_x_step': 0.0,
            'repeat_y_count': 1, 'repeat_y_step': 0.0,
        }
        if self._current_op and \
                self._current_op.operation_type != "surfacage_rectangle":
            inst['corner_radius'] = self._main_form_value(
                'corner_radius', 0.0)
        if data:
            last = data[-1]
            for k in ('width_y', 'depth', 'finishing', 'corner_radius'):
                if k in inst and k in last:
                    inst[k] = last[k]
        data.append(inst)
        self._rebuild_instance_widgets(data)
        self._on_param_changed()

    def _on_remove_instance(self, num: int):
        if self._instances_vbox is None:
            return
        data = self._read_instance_rows()
        if 0 <= num < len(data):
            del data[num]
            self._rebuild_instance_widgets(data)
            self._on_param_changed()

    def _move_instance(self, num: int, delta: int):
        """▲/▼: change l'ordre d'usinage des instances."""
        if self._instances_vbox is None:
            return
        data = self._read_instance_rows()
        tgt = num + delta
        if not (0 <= num < len(data) and 0 <= tgt < len(data)):
            return
        data[num], data[tgt] = data[tgt], data[num]
        self._rebuild_instance_widgets(data)
        self._on_param_changed()

    def _duplicate_instance(self, num: int):
        """⧉: duplique une instance, insérée juste après l'originale
        et décalée en X de sa largeur + 10 mm."""
        if self._instances_vbox is None:
            return
        data = self._read_instance_rows()
        if not (0 <= num < len(data)):
            return
        clone = dict(data[num])
        clone['pos_x'] = float(clone.get('pos_x', 0.0)) + \
            float(clone.get('width_x', 0.0) or 0.0) + 10.0
        data.insert(num + 1, clone)
        self._rebuild_instance_widgets(data)
        self._on_param_changed()

    def _on_create_return_shift(self):
        """Crée une opération décalage inverse et émet le signal."""
        if not self._current_op:
            return
        params = self._collect_params()
        inverse = {
            'shift_x': -float(params.get('shift_x', 0.0)),
            'shift_y': -float(params.get('shift_y', 0.0)),
            'shift_z': -float(params.get('shift_z', 0.0)),
        }
        self.create_return_shift.emit(inverse)

    def _on_dathread_points_changed(self):
        """Synchronise les points du DathreadPointsWidget → opération."""
        if self._suppressing_signals or not self._current_op:
            return
        if not self._dathread_widget:
            return
        self._current_op.points = self._dathread_widget.collect_points()
        if self._current_op.operation_type == "percage_fraise":
            # un Ø réglé sur un point: l'opé usine chaque trou au sien
            self._current_op.params['diametres_par_point'] = any(
                float(pt.get('diameter') or 0) > 0
                for pt in self._current_op.points)
        self._on_param_changed()

    def _add_sequence_passes(self, op):
        """Éditeur de passes d'une séquence Datron étagée: lire, changer
        le Z, ajouter, supprimer — le parcours XY est conservé. Un
        profil 3D (beaucoup de niveaux) n'est pas éditable passe à
        passe: on le dit."""
        code = str(op.params.get('sequence_code', '') or '')
        name = str(op.params.get('sequence_name', '') or '')
        box = QGroupBox("Passes Z")
        v = QVBoxLayout()
        v.setSpacing(4)
        v.setContentsMargins(4, 8, 4, 4)
        if not code.strip():
            v.addWidget(QLabel("Séquence vide ou définie hors de ce "
                               "fichier — rien à éditer."))
            box.setLayout(v)
            self._layout.addWidget(box)
            return
        levels = self._seq_niveaux(code, name)
        if not levels:
            v.addWidget(QLabel("Aucune passe Z ≤ 0 détectée."))
            box.setLayout(v)
            self._layout.addWidget(box)
            return
        if len(levels) > 12:
            v.addWidget(QLabel(
                f"Profil 3D ({len(levels)} niveaux Z) — édition passe "
                "à passe indisponible."))
            box.setLayout(v)
            self._layout.addWidget(box)
            return
        aide = QLabel("Changez le Z d'une passe, ajoutez-en, "
                      "supprimez-en. Le parcours XY est conservé.")
        aide.setWordWrap(True)
        aide.setStyleSheet("color: #94a3b8; font-size: 10px;")
        v.addWidget(aide)
        grid = QGridLayout()
        grid.setSpacing(4)
        for r, z in enumerate(levels):
            grid.addWidget(QLabel(f"Passe {r + 1}"), r, 0)
            spin = SpinCote(decimales=3)
            spin.setRange(-200.0, 0.0)
            spin.setValue(float(z))
            spin.setToolTip("Profondeur Z de cette passe (≤ 0)")
            spin.editingFinished.connect(
                lambda w=spin, z0=z: self._on_pass_z_edited(z0, w.value()))
            grid.addWidget(spin, r, 1)
            btn = QPushButton("✕")
            btn.setMaximumWidth(28)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setToolTip("Supprimer cette passe")
            btn.clicked.connect(
                lambda _=False, z0=z: self._on_pass_delete(z0))
            grid.addWidget(btn, r, 2)
        v.addLayout(grid)
        add_btn = QPushButton("＋ Ajouter une passe")
        add_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        add_btn.setToolTip("Ajoute une passe au pas des précédentes, "
                           "plus profonde — à ajuster ensuite.")
        add_btn.clicked.connect(self._on_pass_add)
        v.addWidget(add_btn)
        box.setLayout(v)
        self._layout.addWidget(box)

    def _add_sequence_sim3d(self, op):
        """La simulation 3D de la séquence, repliée par défaut.

        Dépliée, elle le reste (d'une opé à l'autre, et après chaque
        édition de passe: on voit la passe bouger). La caméra aussi."""
        corps = str(op.params.get('sequence_code', '') or '')
        self._sim3d_widget = None
        if not corps.strip():
            return
        box = QGroupBox()
        v = QVBoxLayout()
        v.setSpacing(4)
        v.setContentsMargins(4, 6, 4, 4)
        ouvert = bool(getattr(self, '_sim3d_ouvert', False))
        bouton = QPushButton(("▾ " if ouvert else "▸ ") + "Simulation 3D")
        bouton.setCheckable(True)
        bouton.setChecked(ouvert)
        bouton.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        bouton.setStyleSheet("QPushButton { text-align: left; "
                             "font-weight: bold; padding: 3px 6px; }")
        bouton.setToolTip("Voir le parcours en volume, passe par passe, "
                          "et le lire — ce que la machine usinera")
        v.addWidget(bouton)
        box.setLayout(v)
        self._layout.addWidget(box)
        self._sim3d_bouton = bouton

        def _basculer(on):
            self._sim3d_ouvert = bool(on)
            bouton.setText(("▾ " if on else "▸ ") + "Simulation 3D")
            if on:
                self._monter_sim3d(op, box, v)
            else:
                self._demonter_sim3d()

        bouton.toggled.connect(_basculer)
        if ouvert:
            self._monter_sim3d(op, box, v)

    def _monter_sim3d(self, op, box, layout):
        """Lit le parcours (barre d'état + Annuler s'il est gros) et
        pose la vue."""
        from src.core import sim3d
        from src.gui.progression import travailler
        from src.gui.vue3d import Simulation3D
        from src.operations.sequence_datron import SequenceDatron
        nom = str(op.params.get('sequence_name', '') or '')
        try:
            # ce que la machine usinera: le bloc tel que généré
            if op.operation_type == "bloc_simpl":
                from src.operations.bloc_simpl import BlocSimpl
                bloc = BlocSimpl.sequence_block(op.params)
            else:
                bloc = SequenceDatron.build_sequence_block(op.params)
        except Exception:
            bloc, nom, _env = self._seq_bloc(
                str(op.params.get('sequence_code', '') or ''), nom)
        nom = nom or "SEQUENCE_1"
        cle = (hash(bloc), nom)
        cache = getattr(self, '_sim3d_cache', None)
        if cache and cache[0] == cle:
            res = cache[1]
        else:
            try:
                res = travailler(
                    self, "Simulation 3D",
                    lambda prog: sim3d.parcours_3d(bloc, nom,
                                                   progression=prog),
                    "lecture du parcours")
            except Exception as err:
                layout.addWidget(QLabel(f"Simulation impossible : {err}"))
                return
            if res is None:            # annulé: on replie
                bouton = getattr(self, '_sim3d_bouton', None)
                if bouton is not None:
                    bouton.setChecked(False)
                return
            self._sim3d_cache = (cle, res)
        w = Simulation3D(box)
        w.setMinimumHeight(340)
        w.set_parcours(res)
        camera = getattr(self, '_sim3d_camera', None)
        if camera:
            w.vue.appliquer_camera(camera)
            w.exag.blockSignals(True)
            w.exag.setValue(w.vue.exag)
            w.exag.blockSignals(False)
            w.cb_rapides.blockSignals(True)
            w.cb_rapides.setChecked(w.vue.rapides)
            w.cb_rapides.blockSignals(False)
        for signal in (w.vue.camera_changee, w.exag.valueChanged,
                       w.cb_rapides.toggled):
            signal.connect(self._sauver_camera_sim3d)
        layout.addWidget(w)
        self._sim3d_widget = w
        # dépliée sous le bas du formulaire, elle vient se montrer
        QTimer.singleShot(0, lambda: self._montrer_sim3d(w))

    def _montrer_sim3d(self, w):
        try:
            if w.isVisibleTo(self):
                self.ensureWidgetVisible(w, 0, 0)
        except RuntimeError:
            pass

    def _sauver_camera_sim3d(self, *_args):
        w = getattr(self, '_sim3d_widget', None)
        if w is None:
            return
        try:
            self._sim3d_camera = w.vue.etat_camera()
        except RuntimeError:
            self._sim3d_widget = None

    def _demonter_sim3d(self):
        w = getattr(self, '_sim3d_widget', None)
        self._sim3d_widget = None
        if w is None:
            return
        try:
            self._sim3d_camera = w.vue.etat_camera()
            w.hide()
            w.deleteLater()
        except RuntimeError:
            pass

    def _maj_sequence_code(self, new_code: str, n: int) -> bool:
        """Applique un code de séquence réécrit: édition directe des
        passes, donc échelle/offset Z remis à neutre (sinon on
        ajusterait deux fois). Régénère et reconstruit l'éditeur."""
        op = self._current_op
        if op is None or not n:
            return False
        op.params['sequence_code'] = new_code
        op.params['z_scale'] = 1.0
        op.params['z_offset'] = 0.0
        self._on_param_changed()
        self.load_operation(op)
        return True

    #: nom de travail d'une séquence sans nom, le temps d'un calcul
    _SEQ_SANS_NOM = "SEQUENCE"

    @classmethod
    def _seq_bloc(cls, corps: str, nom: str):
        """Le corps d'une séquence, entouré de son en-tête « $$$ NOM ».

        `sequence_code` est stocké SANS en-tête (l'import le retire, la
        génération le remet): les outils de simpl_batch, eux, ne lisent
        que l'intérieur d'un bloc $$$. Rend (bloc, nom, enveloppé)."""
        nom = nom or cls._SEQ_SANS_NOM
        if corps.lstrip().startswith('$$$'):
            return corps, nom, False
        return f"$$$ {nom}\n{corps}", nom, True

    @staticmethod
    def _seq_corps(bloc: str, enveloppe: bool) -> str:
        """Le bloc rendu à la forme stockée (sans l'en-tête ajouté)."""
        if not enveloppe:
            return bloc
        return bloc.partition('\n')[2]

    @classmethod
    def _seq_niveaux(cls, corps: str, nom: str) -> list:
        from src.io.simpl_batch import sequence_z_levels
        bloc, nom, _env = cls._seq_bloc(corps, nom)
        return sequence_z_levels(bloc, nom)

    def _seq_transformer(self, transformation) -> bool:
        """Applique `transformation(bloc, nom) -> (bloc, n)` à la
        séquence courante, en passant par son en-tête."""
        op = self._current_op
        if op is None:
            return False
        corps = str(op.params.get('sequence_code', '') or '')
        bloc, nom, env = self._seq_bloc(
            corps, str(op.params.get('sequence_name', '') or ''))
        bloc2, n = transformation(bloc, nom)
        return self._maj_sequence_code(self._seq_corps(bloc2, env), n)

    def _on_pass_z_edited(self, old_z: float, new_z: float):
        if self._suppressing_signals or self._current_op is None:
            return
        if abs(float(old_z) - float(new_z)) < 1e-6:
            return
        from src.io.simpl_batch import set_pass_z
        self._seq_transformer(lambda bloc, nom: set_pass_z(
            bloc, float(old_z), float(new_z), nom))

    def _on_pass_delete(self, z: float):
        if self._current_op is None:
            return
        from src.io.simpl_batch import remove_pass
        self._seq_transformer(lambda bloc, nom: remove_pass(
            bloc, float(z), nom))

    def _on_pass_add(self):
        if self._current_op is None:
            return
        from src.io.simpl_batch import add_pass
        op = self._current_op
        levels = self._seq_niveaux(
            str(op.params.get('sequence_code', '') or ''),
            str(op.params.get('sequence_name', '') or ''))
        if not levels:
            return
        if len(levels) >= 2:
            step = abs(levels[-1] - levels[-2])
        else:
            step = abs(levels[-1]) or 1.0
        new_z = round(levels[-1] - (step or 1.0), 4)
        self._seq_transformer(lambda bloc, nom: add_pass(
            bloc, new_z, nom))

    def _maj_groupes_selon(self) -> None:
        """Les groupes GROUPES_SELON de l'opération: montrés seulement
        pour leurs valeurs (le groupe « Arc » d'un Déplacement n'a rien
        à dire à un Rapid)."""
        op = self._current_op
        if op is None:
            return
        try:
            regles = OperationRegistry.get(op.operation_type).GROUPES_SELON
        except KeyError:
            return
        for groupe, (cle, valeurs) in regles.items():
            boite = self._boites_groupes.get(groupe)
            widget = self._widgets.get(cle)
            if boite is None or widget is None:
                continue
            valeur = (widget.currentText() if isinstance(widget, QComboBox)
                      else (op.params or {}).get(cle))
            boite.setVisible(valeur in valeurs)

    def _on_param_changed(self, *args):
        if self._suppressing_signals or not self._current_op:
            return
        try:
            self._validate_depth()
            self._maj_groupes_selon()
            params = self._collect_params()
            self.params_changed.emit(params)
            # un réglage change le parcours: le bouton redevient
            # « à calculer »
            if self._barre_calcul.isVisible():
                self._maj_barre_calcul()
            # La fiche du bloc importé montre l'effet du réglage:
            # différée, car relire une grosse séquence à chaque
            # frappe de touche hacherait la saisie
            if self._current_op.operation_type == "bloc_simpl" \
                    and getattr(self, '_bloc_detail', None) is not None:
                self._bloc_refresh_timer.start(150)
        except RuntimeError:
            pass  # Widget C++ déjà supprimé

    #: lignes visibles de la liste déroulante des outils
    LIGNES_LISTE_OUTILS = 30
    #: la donnée de la ligne « + Autres outils »
    AUTRES_OUTILS = "__autres_outils__"

    def _deplier_autres_outils(self, choisir: str = "") -> int:
        """Ajoute à la liste les outils filtrés (sous un titre); rend
        l'index de `choisir` s'il y est (0 sinon)."""
        combo = self._tool_combo
        i = combo.findData(self.AUTRES_OUTILS)
        if i >= 0:
            combo.removeItem(i)
            if i - 1 >= 0 and combo.itemText(i - 1) == "" \
                    and combo.itemData(i - 1) is None:
                combo.removeItem(i - 1)          # son séparateur
        combo.insertSeparator(combo.count())
        combo.addItem("— autres familles —", "")
        titre = combo.model().item(combo.count() - 1)
        if titre is not None:
            titre.setEnabled(False)
        trouve = 0
        for tid, tool in (getattr(self, '_autres_outils', None) or {}).items():
            combo.addItem(tool.display_name, tid)
            if tid == choisir:
                trouve = combo.count() - 1
        self._autres_outils = {}
        return trouve

    def _on_tool_changed(self, index: int):
        if self._suppressing_signals or not self._tool_combo:
            return
        try:
            if self._tool_combo.currentData() == self.AUTRES_OUTILS:
                # « + Autres outils »: la liste s'allonge et se rouvre,
                # le choix d'avant ne bouge pas
                avant = getattr(self, '_tool_index_avant', 0)
                self._tool_combo.blockSignals(True)
                self._deplier_autres_outils()
                self._tool_combo.setCurrentIndex(max(0, avant))
                self._tool_combo.blockSignals(False)
                QTimer.singleShot(0, self._tool_combo.showPopup)
                return
            self._tool_index_avant = self._tool_combo.currentIndex()
            tool_id = self._tool_combo.currentData() or ""
        except RuntimeError:
            return
        # Resynchroniser RPM + avances avec les valeurs du nouvel outil
        if tool_id and self._tool_library:
            tool = self._tool_library.get_tool(tool_id)
            if tool:
                if self._rpm_override:
                    self._rpm_override.setValue(int(tool.rpm))
                for key, w in list(self._feed_overrides.items()):
                    try:
                        w.setValue(
                            int(getattr(tool, f'feed_{key}', 0) or 0))
                    except RuntimeError:
                        pass
        self._validate_depth()
        params = self._collect_params()
        params['_tool_id'] = tool_id
        self.params_changed.emit(params)

    def _launch_tool_program_by_name(self, name: str):
        """Relance un programme outil depuis le formulaire."""
        from src.integrations import tool_programs as tp
        prog = next((p for p in tp.discover_tool_programs()
                     if p.name == name), None)
        if prog is None:
            QMessageBox.warning(
                self, "Programmes outils",
                f"« {name} » introuvable dans le dossier "
                "Programmes outils.")
            return
        err = tp.launch_tool_program(prog)
        if err:
            QMessageBox.warning(
                self, "Programmes outils",
                f"Impossible de lancer « {name} »:\n{err}")

    def set_favorite_star(self, is_fav: bool):
        """Met à jour l'étoile favoris du titre (☆ vide / ★ pleine)."""
        btn = getattr(self, '_fav_star_btn', None)
        if btn is None:
            return
        btn.setText("★" if is_fav else "☆")
        btn.setToolTip(
            "Retirer cette opération des favoris" if is_fav
            else "Ajouter cette opération aux favoris")
        btn.setStyleSheet(
            "QPushButton { border: none; background: transparent; "
            f"color: {'#f9e2af' if is_fav else '#6c7086'}; "
            "font-size: 16px; }"
            "QPushButton:hover { color: #f9e2af; }")

    def start_rename_overlay(self):
        """Renommage en surcouche: QLineEdit temporaire PAR-DESSUS le
        label du nom (même pattern que les onglets programmes)."""
        lbl = getattr(self, '_name_label', None)
        if lbl is None or self._current_op is None:
            return
        try:
            parent = lbl.parentWidget()
            geo = lbl.geometry()
        except RuntimeError:
            return
        edit = QLineEdit(parent)
        edit.setText(self._current_op.name)
        edit.setGeometry(geo)
        edit.setStyleSheet(
            "QLineEdit { background: #313244; color: #cdd6f4; "
            "border: 1px solid #89b4fa; border-radius: 3px; "
            "font-size: 13px; padding: 0 2px; }")
        edit.show()
        edit.setFocus()
        edit.selectAll()

        def _finish():
            new_name = edit.text().strip()
            edit.deleteLater()
            if (new_name and self._current_op
                    and new_name != self._current_op.name):
                try:
                    params = self._collect_params()
                    params['_name'] = new_name
                    self.params_changed.emit(params)
                except RuntimeError:
                    return
            try:
                if self._name_label and self._current_op:
                    self._name_label.setText(self._current_op.name)
            except RuntimeError:
                pass

        edit.editingFinished.connect(_finish)

    def _apply_pattern_type_visibility(self, pat_type: str):
        """Affiche les widgets du sous-type de pattern sélectionné."""
        for w in self._pattern_rect_widgets:
            try:
                w.setVisible(pat_type == "Rectangle")
            except RuntimeError:
                pass
        for w in self._pattern_circle_widgets:
            try:
                w.setVisible(pat_type == "Circle")
            except RuntimeError:
                pass
        for w in self._pattern_linear_widgets:
            try:
                w.setVisible(pat_type == "Linear")
            except RuntimeError:
                pass

    def _on_pattern_type_changed(self, pat_type: str):
        """Slot: type de pattern changé → montrer/cacher les bons champs."""
        if self._suppressing_signals:
            return
        self._apply_pattern_type_visibility(pat_type)
        self._on_param_changed()

    def _on_pattern_toggled(self, checked: bool):
        """Affiche/masque les champs Pattern quand la checkbox change."""
        if self._suppressing_signals:
            return
        for w in self._pattern_widgets:
            try:
                w.setVisible(checked)
            except RuntimeError:
                pass
        # Appliquer aussi la visibilité par sous-type
        if checked and 'pattern_type' in self._widgets:
            pt_combo = self._widgets['pattern_type']
            if isinstance(pt_combo, NoScrollComboBox):
                self._apply_pattern_type_visibility(
                    pt_combo.currentText())
        self._on_param_changed()

    def _on_entraxe_toggled(self, checked: bool):
        """Affiche/masque les champs Entraxe."""
        if self._suppressing_signals:
            return
        for w in self._entraxe_widgets:
            try:
                w.setVisible(checked)
            except RuntimeError:
                pass
        self._on_param_changed()

    def _apply_bpm_mode_visibility(self, mode_text: str):
        """Masque les champs BPM non concernés par le mode actif.
        N'émet PAS de signaux — safe pour appeler au chargement."""
        from src.operations.bpm import BPM_MODE_FIELDS, BPM_DEFAULT_TOOLS
        active = BPM_MODE_FIELDS.get(mode_text, set())
        for key, widget in self._widgets.items():
            if key in ('bpm_mode', 'use_pattern',
                       'x_count', 'y_count', 'delta_x', 'delta_y',
                       'entraxe', 'entraxe_axis', '_name'):
                continue  # Ces champs ne dépendent pas du mode
            label = self._bpm_labels.get(key)
            try:
                if key in active:
                    widget.setVisible(True)
                    widget.setEnabled(True)
                    widget.setStyleSheet("")
                    if label:
                        label.setVisible(True)
                        label.setEnabled(True)
                        label.setStyleSheet("")
                else:
                    # Masquer au lieu de griser
                    widget.setVisible(False)
                    if label:
                        label.setVisible(False)
            except RuntimeError:
                pass
        # Auto-sélection de l'outil par défaut (seulement si aucun outil choisi)
        default_article = BPM_DEFAULT_TOOLS.get(mode_text)
        if default_article and self._tool_combo:
            current_tool = self._tool_combo.currentData() or ""
            if not current_tool:
                self._auto_select_tool_by_article(default_article)
        # Outil 2 (taraudage) pour modes Fraise+Taraudage / Foret+Taraudage
        needs_tool2 = mode_text in ("Fraise + Taraudage", "Foret + Taraudage")
        self._update_bpm_tool2(needs_tool2)

    def _on_bpm_mode_changed(self, mode_text: str):
        """Slot: mode BPM changé par l'utilisateur → visibilité + emit."""
        if self._suppressing_signals:
            return
        self._apply_bpm_mode_visibility(mode_text)
        self._on_param_changed()

    def _update_bpm_tool2(self, visible: bool):
        """Crée ou masque le 2e sélecteur d'outil BPM (taraudage)."""
        if not visible:
            if self._bpm_tool2_group:
                self._bpm_tool2_group.setVisible(False)
            return
        # Créer le GroupBox si inexistant
        if not self._bpm_tool2_group:
            grp = QGroupBox("Outil Taraudage")
            lay = QVBoxLayout()
            lay.setSpacing(2)
            lay.setContentsMargins(4, 8, 4, 4)
            desc = QLabel("Taraud pour le filetage")
            desc.setStyleSheet(f"color: {COLORS['text_dim']}; font-size: 10px;")
            lay.addWidget(desc)
            self._bpm_tool2_combo = NoScrollComboBox()
            # Peupler avec les outils taraud (M*)
            if self._tool_library:
                tap_types = ['M3', 'M4', 'M5', 'M6', 'M8']
                compatible = self._tool_library.get_tools_for_operation(
                    tap_types)
                self._bpm_tool2_combo.addItem("-- Sélectionner --", "")
                for tid, tool in compatible.items():
                    self._bpm_tool2_combo.addItem(tool.display_name, tid)
            self._bpm_tool2_combo.currentIndexChanged.connect(
                self._on_param_changed)
            lay.addWidget(self._bpm_tool2_combo)
            grp.setLayout(lay)
            self._bpm_tool2_group = grp
            # Insérer après le groupe Outil (index 2 env.)
            # Trouver l'index du groupe Outil dans le layout
            insert_idx = 2  # Après nom + outil
            for i in range(self._layout.count()):
                item = self._layout.itemAt(i)
                w = item.widget() if item else None
                if isinstance(w, QGroupBox) and w.title() == "Outil":
                    insert_idx = i + 1
                    break
            self._layout.insertWidget(insert_idx, grp)
            # Auto-sélectionner 0068420L
            self._auto_select_tool2_by_article("0068420L")
        self._bpm_tool2_group.setVisible(True)
        # Restaurer la sélection depuis les params
        if self._current_op:
            saved = self._current_op.params.get('bpm_tool2_id', '')
            if saved:
                self._auto_select_tool2_by_article_or_id(saved)

    def _auto_select_tool_by_article(self, article_nr: str):
        """Sélectionne l'outil dont l'article correspond dans le combo."""
        if not self._tool_combo or not self._tool_library:
            return
        for i in range(self._tool_combo.count()):
            tool_id = self._tool_combo.itemData(i)
            if tool_id:
                tool = self._tool_library.get_tool(tool_id)
                if tool and tool.article_nr == article_nr:
                    self._tool_combo.setCurrentIndex(i)
                    return

    def _auto_select_tool2_by_article(self, article_nr: str):
        """Sélectionne l'outil taraudage dans le combo 2."""
        if not self._bpm_tool2_combo or not self._tool_library:
            return
        for i in range(self._bpm_tool2_combo.count()):
            tool_id = self._bpm_tool2_combo.itemData(i)
            if tool_id:
                tool = self._tool_library.get_tool(tool_id)
                if tool and tool.article_nr == article_nr:
                    self._bpm_tool2_combo.setCurrentIndex(i)
                    return

    def _auto_select_tool2_by_article_or_id(self, tool_id_or_article: str):
        """Sélectionne dans combo 2 par tool_id ou article_nr."""
        if not self._bpm_tool2_combo:
            return
        for i in range(self._bpm_tool2_combo.count()):
            tid = self._bpm_tool2_combo.itemData(i)
            if tid == tool_id_or_article:
                self._bpm_tool2_combo.setCurrentIndex(i)
                return
        # Essai par article_nr
        self._auto_select_tool2_by_article(tool_id_or_article)

    def _validate_depth(self):
        """Vérifie: 1) outil sélectionné si requis, 2) Pz <= PzMax(outil)."""
        if not self._depth_warning or not self._current_op:
            return
        try:
            self._validate_depth_impl()
        except RuntimeError:
            pass  # Widget C++ déjà supprimé

    def _validate_depth_impl(self):
        """Implémentation de la validation de profondeur."""
        # Vérifier si l'opération nécessite un outil
        try:
            op_class = OperationRegistry.get(
                self._current_op.operation_type)
        except KeyError:
            return

        if op_class.REQUIRES_TOOL and self._tool_combo:
            tool_id = self._tool_combo.currentData() or ""
            if not tool_id:
                # Pas d'outil sélectionné → blocage TOUJOURS (même expert)
                self._depth_warning.setStyleSheet(
                    "color: #f38ba8; font-size: 11px; font-weight: bold;")
                self._depth_warning.setText(
                    "Outil requis — sélectionnez un outil")
                self._depth_warning.setVisible(True)
                self._depth_blocked = True
                self.generation_blocked.emit(True)
                return
        else:
            tool_id = ""

        if not self._tool_library or not self._tool_combo:
            self._depth_warning.setVisible(False)
            self._depth_blocked = False
            self.generation_blocked.emit(False)
            return

        tool = self._tool_library.get_tool(tool_id) if tool_id else None
        if not tool:
            if op_class.REQUIRES_TOOL:
                # Outil introuvable
                self._depth_warning.setVisible(False)
                self._depth_blocked = False
                self.generation_blocked.emit(False)
            else:
                self._depth_warning.setVisible(False)
                self._depth_blocked = False
                self.generation_blocked.emit(False)
            return

        # Chercher le paramètre depth dans les widgets
        depth_val = None
        for key in ['depth', 'depth_pass1']:
            w = self._widgets.get(key)
            if w and hasattr(w, 'value'):
                v = w.value()
                if isinstance(v, (int, float)):
                    if depth_val is None or v > depth_val:
                        depth_val = v

        warnings = []  # (level, text)  level: 'block' ou 'warn'

        # --- Validation profondeur vs max outil ---
        if depth_val is not None and depth_val > tool.max_depth:
            if self._expert_mode:
                warnings.append(('warn',
                    f"Profondeur {depth_val:.2f} > max outil "
                    f"({tool.max_depth:.1f} mm)"))
            else:
                warnings.append(('block',
                    f"Profondeur {depth_val:.2f} > max outil "
                    f"({tool.max_depth:.1f} mm)"))

        # --- Validation Ø perçage vs Ø outil (R7.5) ---
        if tool.diameter > 0:
            diameter_val = None
            finishing_xy = 0.0
            for key in ['diameter', 'hole_diameter']:
                w = self._widgets.get(key)
                if w and hasattr(w, 'value'):
                    v = w.value()
                    if isinstance(v, (int, float)) and v > 0:
                        diameter_val = v
                        break
            for key in ['finishing_xy', 'finition_xy', 'surep_xy']:
                w = self._widgets.get(key)
                if w and hasattr(w, 'value'):
                    v = w.value()
                    if isinstance(v, (int, float)):
                        finishing_xy = v
                        break
            if diameter_val is not None:
                min_hole = 0.2 + tool.diameter - 2 * finishing_xy
                if diameter_val < min_hole:
                    # Le Ø de la fiche peut être déduit du nom de
                    # l'outil: il prévient, il ne bloque pas
                    warnings.append(('warn',
                        f"Ø trou {diameter_val:.2f} < min "
                        f"{min_hole:.2f} mm (Ø outil {tool.diameter:.1f})"))

        # --- Affichage résultat ---
        has_block = any(lvl == 'block' for lvl, _ in warnings)
        has_warn = any(lvl == 'warn' for lvl, _ in warnings)

        if has_block:
            msg = "BLOQUÉ: " + " | ".join(t for _, t in warnings)
            msg += " — activez le mode Expert"
            self._depth_warning.setStyleSheet(
                "color: #f38ba8; font-size: 11px; font-weight: bold;")
            self._depth_warning.setText(msg)
            self._depth_warning.setVisible(True)
            self._depth_blocked = True
            self.generation_blocked.emit(True)
        elif has_warn:
            msg = " | ".join(t for _, t in warnings)
            self._depth_warning.setStyleSheet(
                "color: #fab387; font-size: 11px; font-weight: bold;")
            self._depth_warning.setText(msg)
            self._depth_warning.setVisible(True)
            self._depth_blocked = False
            self.generation_blocked.emit(False)
        else:
            self._depth_blocked = False
            self._depth_warning.setVisible(False)
            self.generation_blocked.emit(False)

    def _flash_widget(self, widget, color="#a6e3a1", duration_ms=5000):
        """Flash temporaire d'un widget (fond coloré pendant N ms)."""
        original = widget.styleSheet()
        widget.setStyleSheet(
            f"background-color: {color}; border: 2px solid {color};")

        def _restore():
            try:
                widget.setStyleSheet(original)
            except RuntimeError:
                pass  # widget déjà détruit

        QTimer.singleShot(duration_ms, _restore)

    def set_coordinates(self, x: float, y: float):
        """Appelé depuis l'éditeur DXF pour injecter les coordonnées."""
        if self._is_multi_point and self._current_op:
            if self._dathread_widget:
                is_tar = (self._current_op.operation_type == "taraudage")
                self._dathread_widget.add_point(
                    x, y,
                    depth=6.0 if is_tar else None,
                    thread_type='M4' if is_tar else 'M4')
                self._current_op.points = (
                    self._dathread_widget.collect_points())
                self._dathread_widget.flash()
                self._on_param_changed()
            return
        # Single point: écraser X/Y
        for axis, val in [('x', x), ('y', y)]:
            w = self._coord_widgets.get(axis)
            if w and hasattr(w, 'setValue'):
                w.setValue(val)
                self._flash_widget(w)

    def inject_points(self, points: list):
        """Injecte une liste de points depuis la sélection DXF."""
        if not self._current_op or not self._is_multi_point:
            return
        if self._dathread_widget:
            is_tar = (self._current_op.operation_type == "taraudage")
            # CONSERVER le Pz venant de la source (DXF to Op);
            # fallback 6.0 seulement pour taraudage sans Pz
            self._dathread_widget.add_points(
                points, depth_default=6.0 if is_tar else None)
            self._current_op.points = (
                self._dathread_widget.collect_points())
            self._dathread_widget.flash()
            self._on_param_changed()

    def get_coordinates(self) -> tuple:
        """Retourne les coordonnées actuelles (x, y, z)."""
        def _get_val(key):
            w = self._coord_widgets.get(key)
            if w and hasattr(w, 'value'):
                return w.value()
            return 0.0
        return (_get_val('x'), _get_val('y'), 15.0)

    def set_param_value(self, key: str, value: float):
        """Injecte une valeur dans un widget parametre par sa cle."""
        # Coordonnees
        if key in ('x', 'y', 'z'):
            w = self._coord_widgets.get(key)
            if w and hasattr(w, 'setValue'):
                w.setValue(value)
                self._flash_widget(w)
                self._on_param_changed()
            return
        # Parametres classiques
        w = self._widgets.get(key)
        if w and hasattr(w, 'setValue'):
            w.setValue(value)
            self._flash_widget(w)
            self._on_param_changed()


class OperationsPanel(QWidget):
    #: le formulaire part dans son propre onglet (True) ou rentre sous la
    #: liste (False) — la fenêtre place l'onglet
    formulaire_separe_demande = Signal(bool)
    """Panneau complet de la colonne 1."""
    code_needs_update = Signal()
    #: la transparence ou la division d'opérations a changé (clic droit)
    affichage_ops_modifie = Signal()
    active_operation_changed = Signal(object)  # OperationInstance ou None

    def __init__(self, program: ProgramModel, tool_library: ToolLibrary,
                 parent=None):
        super().__init__(parent)
        self.program = program
        self.tool_library = tool_library
        self._default_params = DefaultParamsConfig()
        self._current_index = -1
        self._nds_widget = None
        self._undo_stack = None  # set by MainWindow
        # Snapshot de l'op affichée dans le formulaire (pour undo des
        # éditions de paramètres) + garde de réentrance
        self._undo_snapshot = None
        self._emitting_form_update = False
        #: ensembles repliés (par group_id)
        self._collapsed_groups: set = set()
        #: mode expert courant, à rendre aux widgets reconstruits
        self._expert_mode = False
        self._setup_ui()
        self._connect_signals()

    @staticmethod
    def _op_undo_snapshot(op: OperationInstance) -> dict:
        """Copie profonde de l'état undo-able d'une opération."""
        return {
            'id': op.id,
            'name': op.name,
            'tool_id': op.tool_id,
            'params': copy.deepcopy(op.params),
            'x': op.x,
            'y': op.y,
            'points': copy.deepcopy(op.points),
            'enabled': op.enabled,
        }

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Barre d'outils
        toolbar = QHBoxLayout()

        # Icônes teintées selon le FOND du bouton: primary/danger ont
        # un fond accent/rouge et un texte couleur `bg` — une icône
        # dessinée en accent y était invisible (surtout thèmes clairs)
        from src.gui.icons import get_button_icon
        self.add_btn = QPushButton("+ Opé")
        self.add_btn.setObjectName("primary")
        self.add_btn.setIcon(get_button_icon("add", 16, on_accent=True))
        # Pas de largeur minimale: la barre imposait à elle seule une
        # fenêtre plus large que l'écran
        self.add_btn.setToolTip(
            "Ajouter une opération au programme (les sous-programmes "
            "NDS enregistrés sont en haut du panneau)")
        self.add_btn.clicked.connect(self._on_add_operation)
        toolbar.addWidget(self.add_btn)

        self.inst_btn = QPushButton("+ instance")
        self.inst_btn.setIcon(get_button_icon("add", 16))
        self.inst_btn.setToolTip(
            "Ajoute une opération au MÊME ensemble: même outil, mêmes "
            "specs, même formulaire — seules les cotes changent")
        self.inst_btn.clicked.connect(self._on_add_instance)
        toolbar.addWidget(self.inst_btn)

        self.dup_btn = QPushButton("Dupliquer")
        self.dup_btn.setIcon(get_button_icon("duplicate", 16))
        self.dup_btn.setToolTip(
            "Copie indépendante de l'opération (pour repartir dessus "
            "avec un autre outil par exemple)")
        self.dup_btn.clicked.connect(self._on_duplicate)
        toolbar.addWidget(self.dup_btn)

        self.group_btn = QPushButton("Grouper")
        self.group_btn.setToolTip(
            "Réunit les opérations sélectionnées (même type) en un "
            "ensemble repliable: outil et specs communs, un "
            "formulaire par instance")
        self.group_btn.clicked.connect(self._on_group_selection)
        toolbar.addWidget(self.group_btn)

        self.del_btn = QPushButton("Supprimer")
        self.del_btn.setObjectName("danger")
        self.del_btn.setIcon(
            get_button_icon("delete", 16, on_accent=True))
        self.del_btn.clicked.connect(self._on_delete)
        toolbar.addWidget(self.del_btn)

        self.raz_btn = QPushButton("RAZ")
        self.raz_btn.setToolTip("Réinitialiser toutes les opérations")
        self.raz_btn.setStyleSheet(
            "QPushButton { background-color: #f9a825; color: #1e1e2e; "
            "font-weight: bold; padding: 4px 8px; }"
            "QPushButton:hover { background-color: #fbc02d; }")
        self.raz_btn.clicked.connect(self._on_raz)
        toolbar.addWidget(self.raz_btn)

        toolbar.addStretch()

        # Programmes outils externes (Dathread, ...)
        self.tools_btn = QPushButton("")
        self.tools_btn.setIcon(get_button_icon("toolbox", 18))
        self.tools_btn.setToolTip(
            "Programmes outils (Dathread…)\n"
            "Dossier « Programmes outils » à côté de NeoDrive — "
            "déposez-y un nouveau programme (.py ou .exe) pour "
            "qu'il apparaisse ici.")
        self.tools_btn.setFixedSize(34, 28)
        self.tools_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tools_btn.setStyleSheet(
            "QPushButton { background: #313244; border-radius: 4px; }"
            "QPushButton:hover { background: #45475a; }")
        self.tools_btn.clicked.connect(self._show_tool_programs_menu)
        toolbar.addWidget(self.tools_btn)

        # Le formulaire à part: dans son onglet, dans n'importe quelle
        # colonne (la liste reste seule ici); re-cliquer le remet dessous
        self.formulaire_btn = QPushButton("⇵")
        self.formulaire_btn.setCheckable(True)
        self.formulaire_btn.setFixedSize(30, 28)
        self.formulaire_btn.setToolTip(
            "Formulaire à part: il passe dans son propre onglet « Formulaire »"
            ", que l'on place dans n'importe quelle colonne (clic droit sur "
            "l'onglet, ou en le tirant); re-cliquer le remet sous la liste")
        self.formulaire_btn.toggled.connect(self.formulaire_separe_demande.emit)
        toolbar.addWidget(self.formulaire_btn)
        #: la page qui porte le formulaire quand il est à part
        self.page_formulaire = None
        self._formulaire_separe = False

        layout.addLayout(toolbar)

        # ── Specs du programme (repliées sur une ligne) ──
        # Elles appartiennent à l'ONGLET: chaque programme a son brut,
        # son commentaire et son auteur.
        self.specs_btn = QPushButton("📐 Specs programme")
        self.specs_btn.setCheckable(True)
        self.specs_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        # Le libellé ne doit pas dicter la largeur de la colonne
        self.specs_btn.setSizePolicy(QSizePolicy.Policy.Ignored,
                                     QSizePolicy.Policy.Fixed)
        self.specs_btn.setToolTip(
            "Brut, commentaire et auteur de CET onglet.\n"
            "Cliquer pour déplier et modifier.")
        self.specs_btn.setStyleSheet(
            "QPushButton { text-align: left; background: #181825; "
            "color: #94e2d5; border: 1px solid #313244; "
            "border-radius: 4px; padding: 3px 8px; font-size: 11px; }"
            "QPushButton:checked { background: #313244; }"
            "QPushButton:hover { border-color: #94e2d5; }")
        self.specs_btn.setMaximumHeight(26)
        self.specs_btn.toggled.connect(self._on_specs_toggled)
        layout.addWidget(self.specs_btn)

        self.specs_panel = QWidget()
        layout.addWidget(self.specs_panel)
        # après addWidget: l'ajout au layout d'un parent visible
        # rendrait le panneau visible
        self.specs_panel.setVisible(False)

        # Liste des opérations
        self.op_list = OperationListWidget()
        self.op_list.operation_selected.connect(self._on_operation_selected)
        self.op_list.order_changed.connect(self._on_order_changed)
        self.op_list.operation_toggled.connect(self._on_toggle_operation)
        self.op_list.group_power_toggled.connect(
            self._on_group_power_toggled)
        self.op_list.group_eye_toggled.connect(self._on_group_eye_toggled)
        self.op_list.group_annot_toggled.connect(
            self._on_group_annot_toggled)
        self.op_list.group_star_toggled.connect(self._on_group_star_toggled)
        self.op_list.group_delete_requested.connect(
            self._on_group_delete_requested)
        self.op_list.select_all_requested.connect(
            self._on_select_all_ops)
        self.op_list.affichage_requested.connect(self._on_affichage_ops)
        self.op_list.selection_enable_requested.connect(
            self._on_selection_enable)
        self.op_list.favorite_toggled.connect(
            self._on_list_favorite_toggled)
        self.op_list.copy_requested.connect(self._on_copy_operations)
        self.op_list.paste_requested.connect(self._on_paste_operations)
        self.op_list.rename_requested.connect(self._on_rename_focus)
        self.op_list.nom_change.connect(self.renommer)
        self.op_list.group_toggled.connect(self._on_group_toggled)
        self.op_list.group_action.connect(self._on_group_action)
        self.op_list.group_requested.connect(self._on_group_selection)
        self.op_list.browse_requested.connect(self._on_row_browse)
        self.op_list.delete_requested.connect(self._on_delete_row)
        self.op_list.duplicate_requested.connect(self._on_duplicate)
        self.op_list.ebavurage_requested.connect(self._on_ebavurage)
        self.op_list.selection_delete_requested.connect(self._on_delete)
        self.op_list.contours_requested.connect(self._on_contours_row)
        self.op_list.ope_vers_dessin_requested.connect(
            self._on_ope_vers_dessin_index)
        self.op_list.preview_toggled.connect(self._on_toggle_preview)
        self.op_list.annotations_toggled.connect(
            self._on_toggle_annotations)
        self.op_list.preview_set_requested.connect(
            self._on_set_selection_preview)
        # Liste et formulaire séparés par une poignée: selon la
        # pièce, on veut voir toute la liste ou tout le formulaire
        self._col1_split = QSplitter(Qt.Orientation.Vertical)
        self._col1_split.setChildrenCollapsible(False)
        self._col1_split.setHandleWidth(6)
        self._col1_split.addWidget(self.op_list)
        layout.addWidget(self._col1_split, stretch=1)

        # Panneau inline Ajouter (masqué par défaut)
        self._add_panel = AddOperationPopup(self)
        self._add_panel.set_expert_mode(self._expert_mode)
        self._connect_add_panel(self._add_panel)
        self._add_panel.nds_action.connect(self._on_nds_action)
        self._add_panel.hide()
        layout.addWidget(self._add_panel)

        # Formulaire paramètres
        self.param_form = ParameterFormWidget()
        self.param_form.group_instance_action.connect(
            self._on_group_instance_action)
        self.param_form.set_tool_library(self.tool_library)
        self.param_form.params_changed.connect(self._on_params_changed)
        self.param_form.import_call_requested.connect(
            self._on_import_call_requested)
        self.param_form.gamme_poste_edited.connect(
            self._on_gamme_poste_edited)
        self.param_form.gamme_poste_added.connect(
            self._on_gamme_poste_added)
        self.param_form.rectangles_demandes.connect(
            self._on_rectangles_depuis_selection)
        self.param_form.centres_demandes.connect(
            self._on_centres_depuis_selection)
        self.param_form.ope_vers_dessin_demandee.connect(
            lambda: self._on_ope_vers_dessin_index(self._current_index))
        self.param_form.instances_offset_demandees.connect(
            self._on_instances_offset)
        self.param_form.ebavurage_action.connect(self._on_ebavurage_action)
        self.param_form.valeurs_communes_changees.connect(
            self._on_valeurs_communes)
        self.op_list.itemSelectionChanged.connect(
            self._on_selection_multiple)
        self.param_form.gamme_poste_action.connect(
            self._on_gamme_poste_action)
        self.param_form.gamme_modele_action.connect(
            self._on_gamme_modele_action)
        self.param_form.favorite_check = self._is_single_op_favorite
        self.param_form.favorite_toggle_requested.connect(
            self._on_favorite_star_toggle)
        self.param_form.prefill_provider = self._collect_prefill_sets
        self.param_form._program_ref = self.program
        self._col1_split.addWidget(self.param_form)
        # La liste occupe les deux tiers du haut: la poignée tombe
        # entre la moitié et le quart bas de la colonne, là où on
        # l'attend au premier coup d'œil
        self._col1_split.setStretchFactor(0, 2)
        self._col1_split.setStretchFactor(1, 1)
        self._split_ratio = self._DEFAULT_SPLIT
        self._split_placed = False
        #: True dès que l'utilisateur a tiré la poignée: sa hauteur
        #: prime alors sur l'ajustement automatique
        self._split_user_defined = False
        self._col1_split.splitterMoved.connect(self._on_split_moved)

    # ── le formulaire à part ──

    def formulaire_separe(self) -> bool:
        return self._formulaire_separe

    def detacher_formulaire(self):
        """Sort le formulaire de sous la liste; rend la page qui le
        porte (à poser dans un onglet)."""
        if self.page_formulaire is None:
            self.page_formulaire = QWidget()
            v = QVBoxLayout(self.page_formulaire)
            v.setContentsMargins(0, 0, 0, 0)
        if not self._formulaire_separe:
            self.param_form.setParent(None)
            self.page_formulaire.layout().addWidget(self.param_form)
            self.param_form.show()
            self._formulaire_separe = True
        self._sync_bouton_formulaire()
        return self.page_formulaire

    def rattacher_formulaire(self) -> None:
        """Le formulaire revient sous la liste."""
        if not self._formulaire_separe:
            return
        self.param_form.setParent(None)
        self._col1_split.addWidget(self.param_form)
        self.param_form.show()
        self._formulaire_separe = False
        self._split_placed = False
        self._sync_bouton_formulaire()

    def _sync_bouton_formulaire(self) -> None:
        if self.formulaire_btn.isChecked() != self._formulaire_separe:
            self.formulaire_btn.blockSignals(True)
            self.formulaire_btn.setChecked(self._formulaire_separe)
            self.formulaire_btn.blockSignals(False)

    def _disconnect_program_signals(self):
        """Déconnecte les signaux de l'ancien programme (pour switch onglet)."""
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            try:
                self.program.changed.disconnect(self._refresh_list)
            except (RuntimeError, TypeError):
                pass
            try:
                self.program.operation_updated.disconnect(
                    self._on_operation_updated_external)
            except (RuntimeError, TypeError):
                pass

    def _connect_signals(self):
        # Déconnecter d'abord pour éviter doublons
        self._disconnect_program_signals()
        # Le formulaire doit voir le programme de l'onglet ACTIF pour
        # proposer ses variables opérateur
        self.param_form._program_ref = self.program
        # (un ajout, une suppression émettent aussi `changed`: un seul
        # signal, ou la liste entière se refaisait deux fois par ajout)
        self.program.changed.connect(self._refresh_list)
        # le sens des filets sous miroir: vérifié un instant après
        # chaque changement (ajout, suppression, déplacement, œil,
        # axes du miroir)
        self._miroir_minuterie = QTimer(self)
        self._miroir_minuterie.setSingleShot(True)
        self._miroir_minuterie.setInterval(300)
        self._miroir_minuterie.timeout.connect(self.verifier_miroirs)
        self.program.changed.connect(self._miroir_minuterie.start)
        self.program.operation_updated.connect(
            self._on_operation_updated_external)
        # create_return_shift: déconnecter si connecté (suppress warning)
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            try:
                self.param_form.create_return_shift.disconnect(
                    self._on_create_return_shift_op)
            except (RuntimeError, TypeError):
                pass
        self.param_form.create_return_shift.connect(
            self._on_create_return_shift_op)

    # Couleurs par catégorie d'opération
    _CATEGORY_COLORS = {
        "Perçage": "#89b4fa",     # bleu
        "Taraudage": "#cba6f7",   # violet
        "Surfaçage": "#a6e3a1",   # vert
        "Découpe": "#f38ba8",     # rouge
        "Poche": "#fab387",       # orange
        "Gravure": "#f9e2af",     # jaune
        "Réglage": "#6c7086",     # gris
        "Usinage": "#94e2d5",     # teal
    }

    def _estimate_suffix(self, op) -> str:
        """Suffixe '· ~12 s' pour la liste (estimation temps usinage).

        Une opération LIST_DETAIL (Déplacement, commandes du manuel)
        montre plutôt la ligne qu'elle écrit: quatre « Déplacement »
        se ressemblaient tous dans la liste."""
        try:
            classe = OperationRegistry.get(op.operation_type)
            if getattr(classe, 'LIST_DETAIL', False):
                ligne = classe.generate_operation_code(
                    {**classe.get_default_params(), **(op.params or {})})
                ligne = (ligne or "").strip().splitlines()
                if ligne:
                    texte = ligne[0].strip()
                    if len(texte) > 48:
                        texte = texte[:47] + "…"
                    return f"  · {texte}"
                return ""
        except Exception:
            pass
        try:
            from src.core.time_estimator import (
                estimate_op_seconds, format_duration)
            tool = (self.tool_library.get_tool(op.tool_id)
                    if op.tool_id else None)
            t = estimate_op_seconds(op, tool)
            if t is not None and t > 0.5:
                return f"  · {format_duration(t)}"
        except Exception:
            pass
        return ""

    def _refresh_list(self, *args):
        """Reconstruit la liste depuis le modèle.

        Ignorée pendant qu'une bascule met à jour SA ligne: marquer le
        programme modifié émet `changed`, et la reconstruction qui
        suivait annulait tout le bénéfice de la mise à jour ciblée.

        Les opérations d'un même ensemble (import d'un SimPl,
        regroupement manuel) sont précédées d'un titre repliable."""
        if getattr(self, '_maj_ciblee', False):
            return
        if getattr(self, '_liste_suspendue', 0):
            self._liste_a_refaire = True
            return
        current = self._current_index
        fav_names = self._favorite_names()
        # Position de défilement: la reconstruire remettait la liste
        # en haut à chaque action (dupliquer, plier/déplier), et
        # l'opération en cours sautait hors de l'écran
        scroll = self.op_list.verticalScrollBar().value()
        self.op_list.blockSignals(True)
        self.op_list.clear()
        open_group = None
        counts = {}
        for op in self.program.operations:
            if op.group_id:
                counts[op.group_id] = counts.get(op.group_id, 0) + 1
        for i, op in enumerate(self.program.operations):
            gid = getattr(op, 'group_id', '')
            if gid != open_group:
                open_group = gid
                if gid:
                    self.op_list.addItem(
                        self._make_group_item(op, counts.get(gid, 0)))
            if gid and gid in self._collapsed_groups:
                continue        # ensemble replié: enfants masqués
            try:
                op_class = OperationRegistry.get(op.operation_type)
                cat = op_class.CATEGORY
                color = self._CATEGORY_COLORS.get(cat, "#cdd6f4")
                display = f"{i+1}. {op.name}{self._estimate_suffix(op)}"
                if op.operation_type == "gamme_gravure":
                    # la tête: le dessin, le champ et le tableau
                    display = f"{i+1}. {op.name} — tableau"
                if not op.enabled:
                    display = f"[OFF] {display}"
            except KeyError:
                display = f"{i+1}. ??? {op.operation_type}"
                color = "#585b70"
                cat = ""
            item = QListWidgetItem(display)
            item.setData(Qt.ItemDataRole.UserRole, i)
            item.setData(OperationListWidget.TETE_ROLE,
                         op.operation_type == "gamme_gravure")
            item.setData(_FavStarDelegate.FAV_ROLE,
                         op.name in fav_names)
            item.setData(_FavStarDelegate.OFF_ROLE, not op.enabled)
            item.setData(
                _FavStarDelegate.BROWSE_ROLE,
                op.operation_type in ("appel_programme",
                                      "import_programme"))
            item.setData(_FavStarDelegate.EYE_ROLE, self._oeil_de(op))
            item.setData(_FavStarDelegate.ANNOT_ROLE, self._annot_de(op))
            item.setData(_FavStarDelegate.POWER_ROLE, bool(op.enabled))
            item.setData(_FavStarDelegate.TRASH_ROLE, True)
            item.setData(_FavStarDelegate.STAR_ROLE, True)
            item.setData(_FavStarDelegate.TYPE_ROLE, op.operation_type)
            item.setData(
                _FavStarDelegate.DXF_ROLE,
                op.operation_type in ("gravure_2d5", "evidement_2d5",
                                      "contour_2d5", "gamme_gravure",
                                      "trace", "ebavurage"))
            if not op.enabled:
                item.setForeground(QColor(COLORS['text_muted']))
            else:
                item.setForeground(QColor(color))
            # Icône thème-aware
            from src.gui.icons import get_op_icon
            item.setIcon(get_op_icon(op.operation_type, 18))
            if gid:
                # En retrait, icône comprise (le délégué le dessine): on
                # voit à quoi appartient la ligne
                item.setData(_FavStarDelegate.MEMBRE_ROLE, True)
            self.op_list.addItem(item)
        self.op_list.blockSignals(False)

        # Restaurer la sélection (par INDEX d'opération: les titres
        # décalent les numéros de ligne) puis le défilement
        if current >= 0:
            self.op_list.select_op(current)
        bar = self.op_list.verticalScrollBar()
        bar.setValue(min(scroll, bar.maximum()))

    def _make_group_item(self, op, count: int) -> QListWidgetItem:
        """Ligne de titre d'un ensemble."""
        gid = op.group_id
        collapsed = gid in self._collapsed_groups
        name = op.group_name or "Ensemble"
        chevron = "▸" if collapsed else "▾"
        item = QListWidgetItem(f"{chevron} {name}  ({count})")
        item.setData(Qt.ItemDataRole.UserRole, -1)
        item.setData(OperationListWidget.GROUP_ROLE, gid)
        item.setForeground(QColor(COLORS['blue']))
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        # L'oeil et l'interrupteur du titre valent pour TOUT
        # l'ensemble: régler vingt sous-programmes un par un pour les
        # masquer n'avait pas de sens
        membres = [o for o in self.program.operations
                   if getattr(o, 'group_id', '') == gid]
        item.setData(_FavStarDelegate.EYE_ROLE,
                     any(op_preview(o) for o in membres))
        item.setData(_FavStarDelegate.POWER_ROLE,
                     any(o.enabled for o in membres))
        # A, étoile, corbeille: chacun vaut pour TOUS les membres
        item.setData(_FavStarDelegate.ANNOT_ROLE,
                     any(self._annot_de(o) for o in membres))
        favoris = self._favorite_names()
        item.setData(_FavStarDelegate.STAR_ROLE, True)
        item.setData(_FavStarDelegate.FAV_ROLE,
                     bool(membres) and all(o.name in favoris
                                           for o in membres))
        item.setData(_FavStarDelegate.TRASH_ROLE, True)
        item.setToolTip(
            "Clic: plier/déplier — œil: aperçu de tout l'ensemble — "
            "A: ses annotations — ⏻: activer/désactiver tout l'ensemble"
            " — étoile: ses opés en favoris — corbeille: supprimer "
            "l'ensemble — clic droit: renommer, dissoudre")
        return item

    # ── Ensembles ──

    def _on_select_all_ops(self):
        """Menu du vide: sélectionne toutes les opérations."""
        lst = self.op_list
        lst.clearSelection()
        for row in range(lst.count()):
            if lst.op_index_at(row) >= 0:
                lst.item(row).setSelected(True)

    def _on_group_power_toggled(self, group_id: str):
        """⏻ du titre: bascule TOUT l'ensemble d'un coup."""
        membres = [op for _i, op in self._group_ops(group_id)]
        if not membres:
            return
        cible = not any(op.enabled for op in membres)
        rows = [i for i, _op in self._group_ops(group_id)]
        self.op_list.clearSelection()
        for index in rows:
            row = self.op_list.row_of_op(index)
            item = self.op_list.item(row) if row >= 0 else None
            if item is not None:
                item.setSelected(True)
        self._on_selection_enable(cible)
        self.op_list.select_group(group_id)

    def _on_group_eye_toggled(self, group_id: str):
        """Œil du titre: aperçu de TOUT l'ensemble."""
        membres = [op for _i, op in self._group_ops(group_id)]
        if not membres:
            return
        cible = not any(op_preview(op) for op in membres)
        for op in membres:
            op.params['preview'] = cible
        self._refresh_list()
        self.op_list.select_group(group_id)
        self.code_needs_update.emit()

    def _on_group_annot_toggled(self, group_id: str):
        """A du titre: les annotations de TOUT l'ensemble."""
        membres = [op for _i, op in self._group_ops(group_id)]
        if not membres:
            return
        canvas = getattr(getattr(self.window(), 'dxf_panel', None),
                         'canvas', None)
        if canvas is None:
            return
        cible = not any(self._annot_de(op) for op in membres)
        for op in membres:
            canvas.set_annotations_op_visible(getattr(op, 'id', None),
                                              cible)
        self._refresh_list()
        self.op_list.select_group(group_id)
        # un seul redessin pour tout l'ensemble
        redessiner = getattr(self.window(), '_refresh_canvas_op', None)
        if callable(redessiner):
            redessiner()

    def _on_group_star_toggled(self, group_id: str):
        """Étoile du titre: tous les membres en favoris (ou aucun)."""
        membres = [op for _i, op in self._group_ops(group_id)]
        if not membres:
            return
        favoris = self._favorite_names()
        cible = not all(op.name in favoris for op in membres)
        for _index, op in self._group_ops(group_id):
            if (op.name in self._favorite_names()) != cible:
                self._toggle_op_favorite(op)
        self._refresh_list()
        self.op_list.select_group(group_id)

    #: réponse des tests à la confirmation de la corbeille d'un ensemble
    #: (None: demander; True/False: répondre sans fenêtre)
    reponse_suppression_ensemble = None

    def _on_group_delete_requested(self, group_id: str):
        """Corbeille du titre: supprime TOUT l'ensemble, après
        confirmation (annulable: Ctrl+Z)."""
        rangs = [i for i, _op in self._group_ops(group_id)]
        if not rangs:
            return
        nom = self.program.operations[rangs[0]].group_name or "Ensemble"
        rep = self.reponse_suppression_ensemble
        if rep is None:
            rep = QMessageBox.question(
                self, "Supprimer l'ensemble",
                f"Supprimer les {len(rangs)} opération(s) de l'ensemble "
                f"« {nom} » ?\n(Ctrl+Z la rétablit.)",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) \
                == QMessageBox.StandardButton.Yes
        if not rep:
            return
        self._collapsed_groups.discard(group_id)
        self._supprimer_plusieurs(rangs)

    def _on_group_toggled(self, group_id: str):
        if group_id in self._collapsed_groups:
            self._collapsed_groups.discard(group_id)
        else:
            self._collapsed_groups.add(group_id)
        self._refresh_list()

    def choisir_operation(self, index: int, ajouter: bool = False) -> bool:
        """Choisit l'opération `index` dans la liste, comme un clic sur sa
        ligne (son formulaire, le canvas suivent) — son ensemble replié se
        déplie. `ajouter` (Ctrl+clic): elle s'ajoute à la sélection, ou
        en sort. Rend vrai si sa ligne est trouvée."""
        op = self.program.get_operation(index)
        if op is None:
            return False
        gid = getattr(op, 'group_id', '')
        if gid and gid in self._collapsed_groups:
            self._collapsed_groups.discard(gid)
            self._refresh_list()
        lst = self.op_list
        row = lst.row_of_op(index)
        item = lst.item(row) if row >= 0 else None
        if item is None:
            return False
        if ajouter and lst.selectedItems():
            item.setSelected(not item.isSelected())
        else:
            # elle seule (même déjà la ligne courante d'une sélection
            # de plusieurs)
            from PySide6.QtCore import QItemSelectionModel
            lst.setCurrentRow(
                row, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        lst.scrollToItem(item)
        return True

    def _group_ops(self, group_id: str) -> list:
        return [(i, op) for i, op in enumerate(self.program.operations)
                if getattr(op, 'group_id', '') == group_id]

    def _on_group_action(self, action: str, group_id: str):
        # Actions globales: elles ne visent pas un ensemble précis
        if action in ('fold_all', 'unfold_all'):
            groups = {getattr(op, 'group_id', '')
                      for op in self.program.operations
                      if getattr(op, 'group_id', '')}
            if action == 'fold_all':
                self._collapsed_groups |= groups
            else:
                self._collapsed_groups -= groups
            self._refresh_list()
            return
        members = self._group_ops(group_id)
        if not members:
            return
        if action == 'rename':
            current = members[0][1].group_name
            name, ok = QInputDialog.getText(
                self, "Ensemble", "Nom de l'ensemble:", text=current)
            if not ok or not name.strip():
                return
            for _i, op in members:
                op.group_name = name.strip()
        elif action == 'duplicate':
            self._dupliquer_plusieurs([i for i, _op in members])
            return
        elif action == 'delete':
            self._supprimer_plusieurs([i for i, _op in members])
            return
        elif action == 'dissolve':
            from src.operations.gamme_gravure import GammeGravure
            tete = GammeGravure.tete_de(group_id, self.program.operations)
            for _i, op in members:
                op.group_id = ""
                op.group_name = ""
            self._collapsed_groups.discard(group_id)
            if tete is not None:
                # les postes restent, en parcours libres; la tête
                # n'a plus rien à tenir
                self._retirer_operation(
                    self.program.operations.index(tete))
        elif action in ('enable', 'disable'):
            for _i, op in members:
                op.enabled = (action == 'enable')
        self.program._mark_modified()
        self._refresh_list()
        self.code_needs_update.emit()

    def uniquify_sequences(self, new_ops: list):
        """Numérote les séquences d'un import.

        Chaque import reçoit son propre numéro: SEQUENCE_1 devient
        SEQUENCE_1_1 au premier, SEQUENCE_1_2 au deuxième. Sans cela
        deux fichiers déclarant tous deux SEQUENCE_1 se recouvrent, et
        des blocs usinent le parcours d'un autre programme. Le numéro
        est le même pour toutes les séquences d'un import: on lit d'où
        vient un bloc $$$ rien qu'à son nom."""
        from src.io import simpl_batch as sb
        used = {str(op.params.get('sequence_name', '') or '')
                for op in self.program.operations
                if op not in new_ops}
        used.discard('')
        names = [str(op.params.get('sequence_name', '') or '')
                 for op in new_ops]
        names = [n for n in names if n]
        if not names:
            return 0
        k = 1
        while any(f"{n}_{k}" in used for n in names):
            k += 1
        renamed = 0
        for op in new_ops:
            name = str(op.params.get('sequence_name', '') or '')
            if not name:
                continue
            new_name = f"{name}_{k}"
            used.add(new_name)
            op.params['sequence_name'] = new_name
            for key in ('sequence_code', 'body'):
                code = str(op.params.get(key, '') or '')
                if code:
                    op.params[key], _ = sb.rename_sequence(
                        code, name, new_name)
            renamed += 1
        return renamed

    def _creer_gamme(self):
        """« Ajouter → Gamme gravure »: la tête et ses postes, dans
        un ensemble. Un seul Ctrl+Z reprend le tout.

        Si l'opération courante est un parcours déjà relevé, la
        gamme part de son dessin et de son champ: on ne relève pas
        deux fois le même logo."""
        from src.operations import gamme_postes as gp
        modele = self.program.get_operation(self._current_index) \
            if self._current_index >= 0 else None
        if modele is None or not (modele.params.get('contours')
                                  and modele.operation_type
                                  in gp.TYPES_A_OUTIL):
            modele = {}
        from src.operations import gamme_modeles as gm
        tete, membres = gm.creer_depuis_modele(modele, self.tool_library)
        debut = self.program.operation_count
        creations = [(debut + n, op)
                     for n, op in enumerate([tete] + membres)]
        self.inserer_operations(creations, "Créer la gamme")
        self.op_list.select_op(debut)

    def inserer_operations(self, creations, titre: str) -> int:
        """Insère des opérations, dans l'ordre et à leur index, sous
        une seule commande d'annulation; rend le nombre créé."""
        if not creations:
            return 0
        # Chaque ajout émet `changed`, et la liste se reconstruisait
        # — formulaire compris — à chacun: quarante découpes, quarante
        # formulaires. Une fois, à la fin.
        self._maj_ciblee = True
        try:
            if self._undo_stack:
                from src.core.undo_commands import AddOperationCommand
                self._undo_stack.beginMacro(titre)
                try:
                    for index, nouvelle in creations:
                        self._undo_stack.push(AddOperationCommand(
                            self.program, nouvelle, index))
                finally:
                    self._undo_stack.endMacro()
            else:
                for index, nouvelle in creations:
                    self.program.add_operation(nouvelle, index)
        finally:
            self._maj_ciblee = False
        self._refresh_list()
        return len(creations)

    def _on_selection_multiple(self):
        """Deux opérations ou plus sélectionnées: le formulaire des
        valeurs communes; retour à une seule: son formulaire."""
        self._garder_defilement_liste()
        try:
            rows = self.op_list.selected_rows()
        except RuntimeError:
            return
        form = self.param_form
        if len(rows) >= 2:
            ops = [self.program.get_operation(r) for r in rows]
            # une gamme se règle par sa tête (le tableau), pas par
            # un formulaire commun
            from src.operations.gamme_gravure import GammeGravure
            if any(op is not None and GammeGravure.est_tete(op)
                   for op in ops):
                if form.operations_communes():
                    tete = next(i for i, op in zip(rows, ops)
                                if op is not None
                                and GammeGravure.est_tete(op))
                    self._on_operation_selected(tete)
                return
            try:
                form.load_operations_communes(ops)
            except RuntimeError:
                pass
            self._undo_snapshot = None
            QTimer.singleShot(0, self.ajuster_hauteur_formulaire)
        elif len(rows) == 1 and form.operations_communes():
            self._on_operation_selected(rows[0])

    def _on_valeurs_communes(self, changes: dict):
        """Applique un réglage du formulaire commun à toutes les
        opérations sélectionnées — une annulation pour le tout."""
        from src.core.undo_commands import ModifyOperationCommand
        ops = self.param_form.operations_communes()
        if not ops or not changes:
            return
        ids = {op.id for op in ops}
        params = changes.get('params') or {}
        if self._undo_stack is not None:
            self._undo_stack.beginMacro(
                f"Valeurs communes ({len(ops)} opérations)")
        self._emitting_form_update = True
        touches = []
        try:
            for index, op in enumerate(self.program.operations):
                if op.id not in ids:
                    continue
                avant = self._op_undo_snapshot(op)
                if 'tool_id' in changes:
                    op.tool_id = changes['tool_id']
                if 'x' in changes:
                    op.x = float(changes['x'])
                if 'y' in changes:
                    op.y = float(changes['y'])
                for cle, valeur in params.items():
                    op.params[cle] = valeur
                apres = self._op_undo_snapshot(op)
                if apres == avant:
                    continue
                if self._undo_stack is not None:
                    self._undo_stack.push(ModifyOperationCommand(
                        self.program, index, avant, apres,
                        skip_first_redo=True))
                touches.append(index)
            if touches:
                self._maj_ciblee = True
                try:
                    self.program._mark_modified()
                finally:
                    self._maj_ciblee = False
                for index in touches:
                    self._update_list_item_text(index)
                    self.program.operation_updated.emit(index)
                self.code_needs_update.emit()
        finally:
            self._emitting_form_update = False
            if self._undo_stack is not None:
                self._undo_stack.endMacro()
        if touches:
            self._flash_status(
                f"{len(touches)} opération(s) réglée(s) ensemble")

    def _on_ebavurage_action(self, op_id: str, action: str, nom: str):
        """Le formulaire de l'ébavurage: appliquer un modèle,
        l'enregistrer, le supprimer, reprendre la source."""
        from src.core.undo_commands import ModifyOperationCommand
        from src.operations import ebavurage_modeles as em
        index = next((i for i, op in enumerate(self.program.operations)
                      if op.id == op_id), -1)
        if index < 0:
            return
        op = self.program.operations[index]
        avant = self._op_undo_snapshot(op)
        if action == 'appliquer':
            mdl = em.modele(nom)
            if mdl is None:
                return
            for cle in ('offset', 'depth'):
                if mdl.get(cle) is not None:
                    op.params[cle] = float(mdl[cle])
            outil = em.outil_du_modele(mdl, self.tool_library)
            if outil:
                op.tool_id = outil
        elif action == 'enregistrer':
            outil = self.tool_library.get_tool(op.tool_id) \
                if op.tool_id else None
            propose = (f"{outil.name} — offset "
                       f"{float(op.params.get('offset', 0) or 0):g}"
                       if outil else "Mon ébavurage")
            texte, ok = QInputDialog.getText(
                self, "Modèle d'ébavurage", "Nom du modèle:",
                text=propose)
            if not ok or not texte.strip():
                return
            em.sauver_modele(texte.strip(), {
                'outil': outil.name if outil else "",
                'offset': float(op.params.get('offset', 0) or 0),
                'depth': float(op.params.get('depth', 0) or 0)})
            self._flash_status(f"Modèle « {texte.strip()} » enregistré")
            self.param_form.load_operation(op)
            return
        elif action == 'supprimer':
            if em.est_livre(nom):
                self._flash_status(f"« {nom} » est livré avec NeoDrive: "
                                   "il ne se supprime pas")
                return
            if em.supprimer_modele(nom):
                self._flash_status(f"Modèle « {nom} » supprimé")
                self.param_form.load_operation(op)
            return
        elif action == 'source':
            source = next((o for o in self.program.operations
                           if o.id == op.params.get('source_id')), None)
            geometrie = em.geometrie_de(source) if source else None
            if geometrie is None:
                self._flash_status("La source n'est plus là, ou n'a "
                                   "plus rien à ébavurer")
                return
            op.params.update({k: v for k, v in geometrie.items()
                              if k not in ('x', 'y')})
            op.params.update(em.repetition_de(source))
            op.x, op.y = geometrie['x'], geometrie['y']
        apres = self._op_undo_snapshot(op)
        if apres == avant:
            return
        if self._undo_stack is not None:
            self._undo_stack.push(ModifyOperationCommand(
                self.program, index, avant, apres, skip_first_redo=True))
        self._maj_ciblee = True
        try:
            self.program._mark_modified()
        finally:
            self._maj_ciblee = False
        self._update_list_item_text(index)
        self.program.operation_updated.emit(index)
        self.param_form.load_operation(op)
        self.code_needs_update.emit()

    def _on_ebavurage(self, index: int, nom_modele: str, cote: str):
        """« Ébavurer avec… »: l'opération d'ébavurage de la source,
        réglée par le modèle, à sa suite."""
        from src.operations import ebavurage_modeles as em
        source = self.program.get_operation(index)
        if source is None:
            return
        op = em.creer_ebavurage(source, nom_modele, self.tool_library,
                                cote or None)
        if op is None:
            self._flash_status(
                f"« {source.name} » n'a rien à ébavurer (pas de "
                "rectangle, de cercle ni de contour)")
            return
        self.inserer_operations([(index + 1, op)],
                                f"Ébavurer « {source.name} »")
        self.op_list.select_op(index + 1)
        if not op.tool_id:
            self._flash_status("Ébavurage créé — l'outil du modèle "
                               "n'est pas dans la bibliothèque: "
                               "choisissez-en un")

    def _on_instances_offset(self, offset: float, n: int):
        """n copies emboîtées de l'opération courante: largeur et
        hauteur + 2 × offset × k, rayon des coins + offset × k (un
        cercle: diamètre + 2 × offset × k), même centre. Une seule
        annulation."""
        op = self.param_form._current_op
        if op is None or offset <= 0 or n <= 0:
            self._flash_status("Offset XY: donnez un offset et un "
                               "nombre d'instances")
            return
        index = next((i for i, o in enumerate(self.program.operations)
                      if o.id == op.id), -1)
        if index < 0:
            return
        creations = []
        for k, taille in enumerate(instances_offset(op, offset, n),
                                   start=1):
            copie = op.clone()
            copie.name = f"{op.name} +{offset * k:g}"
            copie.group_id = ""
            copie.group_name = ""
            copie.params.update(taille)
            creations.append((index + k, copie))
        self.inserer_operations(creations,
                                f"Offset XY: {n} instance(s)")
        derniere = creations[-1][1].params
        self._flash_status(
            f"{n} instance(s) emboîtée(s) créée(s), jusqu'à "
            + (f"{derniere.get('width_x', 0):g} × "
               f"{derniere.get('width_y', 0):g}" if 'width_x' in derniere
               else f"Ø {derniere.get('diameter', 0):g}"))

    def _on_rectangles_depuis_selection(self):
        """Les rectangles sélectionnés au canvas: le premier remplit
        l'opération courante, les autres en font des copies à la
        suite — un surfaçage par plaque, une découpe par pièce."""
        from src.core.undo_commands import ModifyOperationCommand
        op = self.param_form._current_op
        if op is None:
            return
        canvas = getattr(getattr(self.window(), 'dxf_panel', None),
                         'canvas', None)
        rects = canvas.rectangles_de_la_selection() if canvas else []
        if not rects:
            self._flash_status(
                "Sélectionnez d'abord un ou plusieurs rectangles au "
                "canvas (entité fermée, groupe, ou quatre traits)")
            return
        index = next((i for i, o in enumerate(self.program.operations)
                      if o.id == op.id), -1)
        if index < 0:
            return

        # le mini formulaire du bouton: profondeur, offset XY (le
        # côté d'une découpe), et l'ensemble — pour TOUTES les
        # opérations que la sélection crée
        from src.operations import depuis_selection as ds
        from src.gui.dialogs.mini_formulaire import champs_communs
        champs = ds.champs_rectangles(op.operation_type,
                                      self._params_effectifs(op))
        # un rectangle du dessin sans rayon de coin: le rayon se choisit
        # (pré-rempli au rayon de la fraise de l'opé)
        outil = (self.tool_library.get_tool(op.tool_id)
                 if self.tool_library is not None and op.tool_id else None)
        rayon_outil = (float(outil.diameter) / 2.0
                       if outil is not None and outil.diameter
                       else float(op.params.get('corner_radius') or 0.0))
        coins = ds.champ_coins_vifs(op.operation_type, rects, rayon_outil)
        if coins is not None:
            champs.append(coins)
        if len(rects) > 1:
            champs += champs_communs(op.group_name or op.name)
        valeurs = self.demander_mini_formulaire(
            f"{op.name} — {len(rects)} rectangle(s) sélectionné(s)",
            champs, "Ces réglages valent pour cette opération"
            + (f" et pour les {len(rects) - 1} copie(s) créée(s), une "
               "par rectangle." if len(rects) > 1 else "."))
        if valeurs is None:
            return

        def _poser(cible, rect):
            cible.x = float(rect['x'])
            cible.y = float(rect['y'])
            cible.params['width_x'] = float(rect['width'])
            cible.params['width_y'] = float(rect['height'])
            # rayon reconnu du dessin; sinon celui des coins vifs du
            # formulaire; sinon on garde le défaut du param (un rayon 3
            # était lu 2, le défaut)
            if 'corner_radius' in cible.params:
                rayon = ds.rayon_de_coin(rect, valeurs)
                if rayon is not None:
                    cible.params['corner_radius'] = rayon
            cible.params.update(ds.reglages_rectangle(
                cible.operation_type, valeurs, rect))

        if self._undo_stack is not None:
            self._undo_stack.beginMacro(
                f"Rectangles du canvas ({len(rects)})")
        try:
            avant = self._snapshot_avec_ensemble(op)
            _poser(op, rects[0])
            copies = []
            for rang, rect in enumerate(rects[1:], start=2):
                copie = op.clone()
                copie.name = f"{op.name} {rang}"
                _poser(copie, rect)
                copies.append(copie)
            self._regrouper_selection(op, copies, valeurs)
            apres = self._snapshot_avec_ensemble(op)
            if self._undo_stack is not None and apres != avant:
                self._undo_stack.push(ModifyOperationCommand(
                    self.program, index, avant, apres,
                    skip_first_redo=True))
            creations = [(index + k + 1, c) for k, c in enumerate(copies)]
            self.inserer_operations(creations,
                                    f"Rectangles du canvas ({len(rects)})")
        finally:
            if self._undo_stack is not None:
                self._undo_stack.endMacro()
        self.program._mark_modified()
        self.program.operation_updated.emit(index)
        try:
            self.param_form.load_operation(op)
        except RuntimeError:
            pass
        self._flash_status(
            f"{rects[0]['width']:g} × {rects[0]['height']:g} en "
            f"X{rects[0]['x']:g} Y{rects[0]['y']:g}"
            + (f" — et {len(rects) - 1} instance(s) créée(s) pour les "
               f"autres rectangles" if len(rects) > 1 else ""))

    #: les tests répondent au mini formulaire sans l'ouvrir: True
    #: (ses défauts), un dict (des valeurs, le reste par défaut), False
    #: (annuler); None l'ouvre
    reponse_mini_formulaire = None

    def demander_mini_formulaire(self, titre, champs, explication=""):
        """Le mini formulaire d'un bouton « depuis la sélection »: ses
        valeurs, ou None (annulé)."""
        from src.gui.dialogs.mini_formulaire import MiniFormulaire
        rep = self.reponse_mini_formulaire
        # les champs posés à côté du bouton, dans le formulaire
        posee = getattr(self.param_form, '_mini_selection', None)
        if posee is not None:
            try:
                # détruite avec un formulaire d'avant: RuntimeError
                if not posee.isVisibleTo(self.param_form) and \
                        self.param_form.isVisible():
                    posee = None
            except RuntimeError:
                posee = None
        if posee is not None and set(c[0] for c in champs) <= set(
                posee.cles()):
            if rep is False:
                return None
            if isinstance(rep, dict):
                for cle, val in rep.items():
                    if posee.widget(cle) is not None:
                        posee.regler(cle, val)
            return posee.valeurs()
        dlg = MiniFormulaire(titre, champs, self, explication)
        try:
            if rep is None:
                return dlg.demander()
            if rep is False:
                return None
            if isinstance(rep, dict):
                for cle, val in rep.items():
                    if dlg.widget(cle) is not None:
                        dlg.regler(cle, val)
            return dlg.valeurs()
        finally:
            dlg.deleteLater()

    @staticmethod
    def _params_effectifs(op) -> dict:
        """Les paramètres de l'opération, ses défauts compris."""
        try:
            from src.operations.registry import OperationRegistry
            defauts = OperationRegistry.get(
                op.operation_type).get_default_params()
        except Exception:
            defauts = {}
        return {**defauts, **(op.params or {})}

    def _snapshot_avec_ensemble(self, op) -> dict:
        """L'état undo d'une opération, son ensemble compris (le
        bouton de la sélection peut la regrouper)."""
        d = self._op_undo_snapshot(op)
        d['group_id'] = getattr(op, 'group_id', '')
        d['group_name'] = getattr(op, 'group_name', '')
        d['group_libre'] = bool(getattr(op, 'group_libre', False))
        return d

    @staticmethod
    def _regrouper_selection(op, nouvelles, valeurs) -> None:
        """L'opération et celles que la sélection crée, en un ensemble
        (celui de l'opération si elle en a un). Libre si les types
        diffèrent (un filet et son avant-trou)."""
        nouvelles = [o for o in nouvelles if o is not None]
        if not (valeurs or {}).get('grouper') or not nouvelles:
            return
        import uuid as _uuid
        gid = getattr(op, 'group_id', '') or str(_uuid.uuid4())[:8]
        nom = str(valeurs.get('nom_groupe') or op.group_name or op.name)
        libre = (getattr(op, 'group_libre', False)
                 or any(o.operation_type != op.operation_type
                        for o in nouvelles))
        for o in [op] + nouvelles:
            o.group_id = gid
            o.group_name = nom
            o.group_libre = libre

    def _on_centres_depuis_selection(self):
        """Les centres sélectionnés au canvas remplissent les points
        d'un perçage ou d'un taraudage. Un perçage fraisé garde UNE
        opération: chaque trou à son Ø (octobre 2026, RomDuch: « pas
        forcément le même pour tous »), modifiable point par point."""
        from src.core.undo_commands import ModifyOperationCommand
        op = self.param_form._current_op
        if op is None:
            return
        canvas = getattr(getattr(self.window(), 'dxf_panel', None),
                         'canvas', None)
        centres = canvas.centres_de_la_selection() if canvas else []
        if not centres:
            self._flash_status(
                "Sélectionnez d'abord des entités au canvas (cercles, "
                "croix, contours) pour en reprendre les centres")
            return
        index = next((i for i, o in enumerate(self.program.operations)
                      if o.id == op.id), -1)
        if index < 0:
            return
        # le Ø du cercle: celui du perçage, ou le Ø nominal d'un
        # filetage spécial (un filet par Ø)
        cle_diam = ("nominal_diameter"
                    if op.operation_type == "filetage_special"
                    else "diameter")
        avec_diam = (op.operation_type == "filetage_special"
                     or (op.operation_type in ("percage_foret",
                                               "percage_fraise")
                         and 'diameter' in (op.params or {})))
        # Perçage fraisé de plusieurs Ø: une opé, un Ø par point (le
        # plus fréquent devient celui de l'opé)
        par_point = False
        diam_principal = 0.0
        if avec_diam and op.operation_type == "percage_fraise":
            from collections import Counter
            comptes = Counter(round(float(c['diameter'] or 0.0), 3)
                              for c in centres
                              if float(c['diameter'] or 0.0) > 0)
            if len(comptes) > 1:
                par_point = True
                diam_principal = comptes.most_common(1)[0][0]
        # Groupes: par diamètre pour un perçage (les Ø=0 vont avec le
        # diamètre courant), un seul groupe sinon
        if par_point:
            lots = [(diam_principal, centres)]
        elif avec_diam:
            groupes: Dict[float, list] = {}
            for c in centres:
                d = float(c['diameter'] or 0.0)
                groupes.setdefault(d, []).append(c)
            # le Ø courant d'abord s'il est présent, sinon le plus gros
            ordre = sorted(groupes.keys(), reverse=True)
            cle_courante = round(float(op.params.get(cle_diam) or 0.0), 3)
            if cle_courante in groupes:
                ordre.remove(cle_courante)
                ordre.insert(0, cle_courante)
            lots = [(d, groupes[d]) for d in ordre]
        else:
            lots = [(0.0, centres)]

        # le mini formulaire du bouton: profondeur (du filet et de
        # son avant-trou), type de filet, passe Z, ébavurage, ensemble
        # — pour TOUTES les opérations que la sélection crée
        from src.operations import depuis_selection as ds
        from src.gui.dialogs.mini_formulaire import champs_communs
        taraudage = op.operation_type == "taraudage"
        champs = ds.champs_points(op.operation_type,
                                  self._params_effectifs(op))
        if op.operation_type in ParameterFormWidget.OPS_EBAVURAGE:
            # l'ébavurage a SA section dans le formulaire: on ne le
            # redemande pas (reglages_points ne touche à use_ebav que
            # si 'ebav' est fourni: les opés créées gardent celui de
            # l'opé) — et les champs posés à côté du bouton, qui n'ont
            # plus cette case, répondent sans ouvrir de fenêtre
            champs = [c for c in champs if c[0] != 'ebav']
        if len(lots) > 1 or taraudage:
            champs += champs_communs(op.group_name or op.name)
        valeurs = self.demander_mini_formulaire(
            f"{op.name} — {len(centres)} centre(s) sélectionné(s)",
            champs, "Ces réglages valent pour cette opération"
            + (f" et pour les {len(lots) - 1} copie(s) créée(s), une "
               "par Ø." if len(lots) > 1 else "")
            + (" L'avant-trou est un perçage fraisé au Ø de perçage du "
               "filet, sur les mêmes points." if taraudage else ""))
        if valeurs is None:
            return
        reglages = ds.reglages_points(op.operation_type, valeurs)

        def _poser(cible, diam, pts):
            cible.points = [{'x': float(p['x']), 'y': float(p['y'])}
                            for p in pts]
            if par_point:
                for pt, c in zip(cible.points, pts):
                    if float(c.get('diameter') or 0.0) > 0:
                        pt['diameter'] = round(float(c['diameter']), 3)
            if cible.operation_type == "percage_fraise":
                cible.params['diametres_par_point'] = par_point
            for pt in cible.points:
                if 'depth' in reglages:
                    pt['depth'] = reglages['depth']
                if 'thread_name' in reglages:
                    pt['thread_type'] = reglages['thread_name']
            if avec_diam and diam > 0:
                cible.params[cle_diam] = round(diam, 3)
            if pts:
                cible.x = float(pts[0]['x'])
                cible.y = float(pts[0]['y'])
            cible.params.update(reglages)

        if self._undo_stack is not None:
            self._undo_stack.beginMacro(
                f"Centres du canvas ({len(centres)})")
        try:
            avant = self._snapshot_avec_ensemble(op)
            _poser(op, lots[0][0], lots[0][1])
            copies = []
            for rang, (diam, pts) in enumerate(lots[1:], start=2):
                copie = op.clone()
                copie.name = (f"{op.name} Ø{diam:g}" if diam > 0
                              else f"{op.name} {rang}")
                _poser(copie, diam, pts)
                copies.append(copie)
            # le filet: son avant-trou AVANT lui, sur les mêmes points
            avant_trou = None
            if taraudage:
                donnees = ds.op_avant_trou(valeurs, op.points,
                                           self.tool_library)
                if donnees is not None:
                    from src.operations.registry import OperationRegistry
                    avant_trou = OperationInstance(
                        donnees['operation_type'], donnees['name'])
                    avant_trou.params = {
                        **OperationRegistry.get(
                            'percage_fraise').get_default_params(),
                        **donnees['params']}
                    avant_trou.points = donnees['points']
                    avant_trou.x = donnees['x']
                    avant_trou.y = donnees['y']
                    avant_trou.tool_id = donnees.get('tool_id', '')
            self._regrouper_selection(
                op, copies + ([avant_trou] if avant_trou else []), valeurs)
            apres = self._snapshot_avec_ensemble(op)
            if self._undo_stack is not None and apres != avant:
                self._undo_stack.push(ModifyOperationCommand(
                    self.program, index, avant, apres,
                    skip_first_redo=True))
            creations = [(index + k + 1, c) for k, c in enumerate(copies)]
            if avant_trou is not None:
                creations.insert(0, (index, avant_trou))
                creations = [creations[0]] + [(i + 1, c)
                                              for i, c in creations[1:]]
            if creations:
                self.inserer_operations(
                    creations, f"Centres du canvas ({len(centres)})")
            if avant_trou is not None:
                index += 1
        finally:
            if self._undo_stack is not None:
                self._undo_stack.endMacro()
        self.program._mark_modified()
        self.program.operation_updated.emit(index)
        try:
            self.param_form.load_operation(op)
        except RuntimeError:
            pass
        n_pts = len(lots[0][1])
        self._flash_status(
            f"{len(centres)} centre(s) repris"
            + (f" — {n_pts} point(s) sur cette opération, "
               f"{len(lots) - 1} opération(s) créée(s) pour les "
               "autres Ø"
               if len(lots) > 1 else f" — {n_pts} point(s)"))

    def _on_gamme_poste_edited(self, op_id: str, changes: dict):
        """Le tableau de la gamme a changé un poste: on l'applique au
        poste, avec annulation, sans quitter le formulaire de la
        gamme."""
        from src.core.undo_commands import ModifyOperationCommand
        index = next((i for i, op in enumerate(self.program.operations)
                      if op.id == op_id), -1)
        if index < 0:
            return
        op = self.program.operations[index]
        avant = self._op_undo_snapshot(op)
        if 'tool_id' in changes:
            op.tool_id = changes['tool_id']
        if 'enabled' in changes:
            op.enabled = bool(changes['enabled'])
        for cle, valeur in (changes.get('params') or {}).items():
            op.params[cle] = valeur
        apres = self._op_undo_snapshot(op)
        if apres == avant:
            return
        if self._undo_stack is not None:
            self._undo_stack.push(ModifyOperationCommand(
                self.program, index, avant, apres, skip_first_redo=True))
        self.program._mark_modified()
        self._update_list_item_text(index)
        self.program.operation_updated.emit(index)
        # le poste a changé: son parcours d'avant ne vaut plus
        try:
            self.param_form._maj_etats_gamme()
        except RuntimeError:
            pass
        self.code_needs_update.emit()

    def _on_gamme_poste_action(self, op_id: str, action: str):
        """Un bouton de ligne ou le menu du tableau de la gamme."""
        from src.operations.gamme_gravure import GammeGravure
        index = next((i for i, op in enumerate(self.program.operations)
                      if op.id == op_id), -1)
        if index < 0:
            return
        op = self.program.operations[index]
        tete = GammeGravure.tete_de(op.group_id, self.program.operations)
        tete_index = self.program.operations.index(tete) \
            if tete is not None else -1

        def _revenir_a_la_tete():
            # le tableau se refait sur l'état courant
            if tete_index >= 0 and tete in self.program.operations:
                nouvel_index = self.program.operations.index(tete)
                self.op_list.select_op(nouvel_index)
                self._on_operation_selected(nouvel_index)

        if action == 'ouvrir':
            self.op_list.select_op(index)
            self._on_operation_selected(index)
        elif action == 'calculer':
            self._calculer_operation(op)
            self.param_form._maj_etats_gamme()
        elif action == 'basculer':
            self._on_toggle_operation(index)
            self.param_form._maj_etats_gamme()
        elif action == 'apercu':
            self._on_toggle_preview(index)
            fenetre = self.window()
            redessiner = getattr(fenetre, '_refresh_canvas_op', None)
            if callable(redessiner):
                redessiner()
        elif action in ('monter', 'descendre'):
            membres = GammeGravure.membres(tete, self.program.operations) \
                if tete is not None else []
            if op not in membres:
                return
            place = membres.index(op)
            cible = place - 1 if action == 'monter' else place + 1
            if not 0 <= cible < len(membres):
                return
            vers = self.program.operations.index(membres[cible])
            if self._undo_stack is not None:
                from src.core.undo_commands import MoveOperationCommand
                self._undo_stack.push(MoveOperationCommand(
                    self.program, index, vers))
            else:
                self.program.move_operation(index, vers)
            _revenir_a_la_tete()
        elif action == 'supprimer':
            self._retirer_operation(index)
            _revenir_a_la_tete()
        self.code_needs_update.emit()

    def _calculer_operation(self, op):
        """Calcule le parcours d'UNE opération, fenêtre et Annuler
        compris — le geste du bouton « Calculer le parcours », pour
        un poste depuis le tableau."""
        from src.gui.progression import Progression
        from src.operations.gravure_2d5 import chainer, params_outil
        from src.operations.registry import OperationRegistry
        try:
            classe = OperationRegistry.get(op.operation_type)
        except KeyError:
            return
        if not hasattr(classe, 'plan'):
            return
        chainer(self.program.operations, self.tool_library)
        params = params_outil(op, self.tool_library)

        def _travail(barre):
            classe.plan(params, progression=barre.sous(0.0, 0.7,
                                                      "parcours — "))
            classe.mesures(params, calculer=True,
                           progression=barre.sous(0.7, 1.0, "mesure — "))

        try:
            with Progression(self, "Calcul du parcours",
                             op.name or "parcours") as barre:
                barre.executer(_travail)
        except Exception as exc:
            QMessageBox.warning(self, "Calcul du parcours",
                                f"Le parcours n'a pas pu être calculé:"
                                f"\n{exc}")
            return
        fenetre = self.window()
        redessiner = getattr(fenetre, '_refresh_canvas_op', None)
        if callable(redessiner):
            redessiner()

    def _on_gamme_modele_action(self, tete_id: str, action: str,
                                nom: str):
        """Appliquer / enregistrer / supprimer un modèle de gamme,
        ou le choisir par défaut."""
        from PySide6.QtWidgets import QInputDialog
        from src.operations import gamme_modeles as gm
        from src.operations import gamme_postes as gp
        from src.operations.gamme_gravure import GammeGravure
        tete = self.program.get_operation_by_id(tete_id)
        if tete is None:
            return
        membres = GammeGravure.membres(tete, self.program.operations)
        if action == 'defaut':
            gm.choisir_par_defaut(nom)
            return
        if action == 'enregistrer':
            propose = nom if nom and not gm.est_livre(nom) \
                else "Ma gamme"
            nouveau, ok = QInputDialog.getText(
                self, "Modèle de gamme", "Nom du modèle:", text=propose)
            if not ok or not nouveau.strip():
                return
            if not gm.sauver_modele(
                    nouveau.strip(),
                    gm.modele_depuis_membres(membres, self.tool_library)):
                QMessageBox.warning(self, "Modèle de gamme",
                                    "Impossible d'enregistrer le modèle.")
        elif action == 'supprimer':
            if gm.est_livre(nom) or not gm.existe(nom):
                return
            gm.supprimer_modele(nom)
        elif action == 'appliquer':
            postes = gm.postes_du(nom)
            if not postes:
                return
            # les postes d'avant s'en vont, ceux du modèle arrivent —
            # d'un seul coup pour Ctrl+Z
            if self._undo_stack:
                self._undo_stack.beginMacro(f"Appliquer le modèle {nom}")
            try:
                for membre in reversed(membres):
                    index = self.program.operations.index(membre)
                    self._retirer_operation(index)
                creations = []
                place = self.program.operations.index(tete) + 1
                for pst in postes:
                    tool_id = gp.outil_du_poste(pst, self.tool_library)
                    if pst['op_type'] in gp.TYPES_A_OUTIL and not tool_id:
                        continue
                    op = gp.operation_du_poste(pst, tete, tool_id,
                                               self.tool_library)
                    op.group_id, op.group_name = tete.group_id, \
                        tete.group_name
                    GammeGravure.propager(tete, [op])
                    creations.append((place, op))
                    place += 1
                self.inserer_operations(creations, "Postes du modèle")
            finally:
                if self._undo_stack:
                    self._undo_stack.endMacro()
        # le formulaire de la tête se refait avec ce qui a changé
        index = self.program.operations.index(tete)
        self.op_list.select_op(index)
        self._on_operation_selected(index)
        self.code_needs_update.emit()

    def _on_gamme_poste_added(self, tete_id: str, genre: str):
        """« + Poste » du tableau: un poste neuf à la fin de la gamme,
        avec le dessin et le champ de la tête."""
        from src.operations import gamme_postes as gp
        from src.operations.gamme_gravure import GammeGravure
        tete = self.program.get_operation_by_id(tete_id)
        if tete is None:
            return
        pst = gp.poste_modele(genre)
        tool_id = gp.outil_du_poste(pst, self.tool_library)
        if pst['op_type'] in gp.TYPES_A_OUTIL and not tool_id:
            QMessageBox.information(
                self, "Gamme gravure",
                "Aucun outil de ce genre dans la bibliothèque.")
            return
        op = gp.operation_du_poste(pst, tete, tool_id, self.tool_library)
        op.group_id, op.group_name = tete.group_id, tete.group_name
        GammeGravure.propager(tete, [op])
        membres = GammeGravure.membres(tete, self.program.operations)
        dernier = membres[-1] if membres else tete
        index = self.program.operations.index(dernier) + 1
        self.inserer_operations([(index, op)], f"Ajouter {op.name}")
        # le formulaire de la gamme se refait avec sa ligne de plus
        tete_index = self.program.operations.index(tete)
        self.op_list.select_op(tete_index)
        self._on_operation_selected(tete_index)

    def _on_import_call_requested(self, op_id: str):
        """Bouton « Importer » du formulaire d'un appel externe."""
        index = next((i for i, o in enumerate(self.program.operations)
                      if o.id == op_id), -1)
        if index >= 0:
            self._convert_external_call(index)

    def _convert_external_call(self, index: int):
        """Remplace un « Appel prog externe » par l'IMPORT du fichier.

        Le programme appelé arrive comme un ensemble repliable de ses
        sous-programmes, exactement comme un import depuis l'onglet
        Batch édition: on voit ce qu'il usine, on peut le régler, le
        réordonner et le mettre en sourdine bloc par bloc."""
        import os
        op = self.program.get_operation(index)
        if op is None or op.operation_type not in (
                "import_programme", "appel_programme"):
            return
        from src.core.chemins_machine import chemin_local
        path = chemin_local(str(op.params.get('filepath', '') or '').strip())
        if not path or not os.path.isfile(path):
            return
        from src.io.simpl_importer import import_simpl_as_blocks
        try:
            loaded = import_simpl_as_blocks(path, self.tool_library)
        except Exception as exc:
            QMessageBox.warning(
                self, "Import du programme externe",
                f"Fichier illisible:\n{exc}")
            return
        blocs = list(loaded.operations)
        if not blocs:
            QMessageBox.information(
                self, "Import du programme externe",
                "Aucun sous-programme appelé par le Main de "
                f"{os.path.basename(path)}.")
            return
        self.uniquify_sequences(blocs)
        for bloc in blocs:
            bloc.enabled = op.enabled and bloc.enabled
        # Une seule étape d'annulation: Ctrl+Z rend l'appel d'origine
        if self._undo_stack:
            from src.core.undo_commands import (
                AddOperationCommand, RemoveOperationCommand)
            self._undo_stack.beginMacro(
                f"Importer {os.path.basename(path)}")
            self._undo_stack.push(
                RemoveOperationCommand(self.program, index))
            for offset, bloc in enumerate(blocs):
                self._undo_stack.push(
                    AddOperationCommand(self.program, bloc,
                                        index + offset))
            self._undo_stack.endMacro()
            # Les commandes recréent les opérations: reprendre les
            # objets réellement posés dans le programme
            blocs = self.program.operations[index:index + len(blocs)]
        else:
            self.program.remove_operation(index)
            for offset, bloc in enumerate(blocs):
                self.program.add_operation(bloc, index + offset)
        self._collapsed_groups.add(blocs[0].group_id)
        self._current_index = -1
        self._refresh_list()
        self.op_list.select_op(index)
        self._flash_status(
            f"{os.path.basename(path)} importé — {len(blocs)} "
            f"sous-programme(s)")
        self.code_needs_update.emit()

    def _on_group_instance_action(self, action: str, op_id: str):
        """Monter / descendre / supprimer une instance d'un ensemble.

        Le déplacement reste INTERNE à l'ensemble: échanger avec le
        voisin du même ensemble, jamais avec l'opération d'à côté."""
        ops = self.program.operations
        target = next((o for o in ops if o.id == op_id), None)
        if target is None:
            return
        gid = getattr(target, 'group_id', '')
        members = [o for o in ops if getattr(o, 'group_id', '') == gid]
        pos = members.index(target)

        if action == 'remove':
            index = ops.index(target)
            if self._undo_stack:
                from src.core.undo_commands import RemoveOperationCommand
                self._undo_stack.push(
                    RemoveOperationCommand(self.program, index))
            else:
                self.program.remove_operation(index)
            self._current_index = -1
            self._refresh_list()
            remaining = [o for o in self.program.operations
                         if getattr(o, 'group_id', '') == gid]
            if remaining:
                self.op_list.select_op(
                    self.program.operations.index(remaining[0]))
            self.code_needs_update.emit()
            return

        swap = pos - 1 if action == 'up' else pos + 1
        if swap < 0 or swap >= len(members):
            return
        order = [o.id for o in ops]
        a = order.index(target.id)
        b = order.index(members[swap].id)
        order[a], order[b] = order[b], order[a]
        old_ids = [o.id for o in ops]
        self.program.reorder_operations(order)
        if self._undo_stack is not None:
            from src.core.undo_commands import ReorderOperationsCommand
            self._undo_stack.push(ReorderOperationsCommand(
                self.program, old_ids, order, skip_first_redo=True))
        self.op_list.select_op(
            [o.id for o in self.program.operations].index(target.id))
        self.code_needs_update.emit()

    def _on_group_selection(self):
        """Regroupe les opérations sélectionnées en un ensemble.

        Elles sont rassemblées à la position de la PREMIÈRE: un
        ensemble doit rester d'un seul tenant, sinon l'ordre d'usinage
        ne se lit plus."""
        import uuid as _uuid
        rows = self.op_list.selected_rows()
        if len(rows) < 2:
            return
        ops = [self.program.get_operation(r) for r in rows]
        ops = [o for o in ops if o is not None]
        if len(ops) < 2:
            return
        # Un ensemble est une suite de formulaires IDENTIQUES: mêmes
        # champs, même outil. Mélanger les types donnerait une liste
        # d'instances qu'on ne pourrait ni régler ni relire ensemble.
        types = {op.operation_type for op in ops}
        if len(types) > 1:
            QMessageBox.information(
                self, "Ensemble",
                "Un ensemble regroupe des opérations du MÊME type "
                "(mêmes champs, même outil).\n\nTypes sélectionnés : "
                + ", ".join(sorted(types)))
            return
        name, ok = QInputDialog.getText(
            self, "Nouvel ensemble", "Nom de l'ensemble:",
            text=f"{ops[0].name} ({len(ops)})")
        if not ok or not name.strip():
            return
        gid = str(_uuid.uuid4())[:8]
        for op in ops:
            op.group_id = gid
            op.group_name = name.strip()
        # Outil et specs communs: ceux de la première instance
        self._apply_group_tool(ops[0], ops)
        # Rassembler: ordre = celui de la sélection, à la place de la 1re
        ids = [op.id for op in ops]
        order = [o.id for o in self.program.operations
                 if o.id not in ids]
        anchor = min(rows)
        order[anchor:anchor] = ids
        self.program.reorder_operations(order)
        self._refresh_list()
        # L'ensemble qu'on vient de créer reste sélectionné: les
        # actions qui suivent (le désactiver, le masquer) portent
        # sur lui sans avoir à le recliquer
        self.op_list.select_group(gid)
        self.code_needs_update.emit()

    def fermer_ajout(self) -> bool:
        """Ferme le menu « nouvelle opération » (et la liste NDS) s'il
        est ouvert: la liste des opérations revient. Rend vrai s'il
        l'était."""
        ouvert = self._add_panel.isVisible() or (
            getattr(self, '_nds_widget', None) is not None
            and not self._nds_widget.isHidden())
        if ouvert:
            self._show_main_content()
        return ouvert

    def _on_add_operation(self):
        """Toggle le panneau inline d'ajout d'opération — prend toute la colonne 1."""
        if self._add_panel.isVisible():
            self._show_main_content()
        else:
            # Masquer NDS si visible
            if hasattr(self, '_nds_widget') and self._nds_widget and self._nds_widget.isVisible():
                self._nds_widget.hide()
            self._hide_main_content()
            self._add_panel.setFixedHeight(16777215)  # remove fixed height limit
            self._add_panel.setMaximumHeight(16777215)
            self._add_panel.show()
            self._add_panel._search.setFocus()
            self._add_panel._search.clear()

    #: part de hauteur laissée à la liste tant que l'utilisateur n'a
    #: pas déplacé la poignée (entre la moitié et le quart bas)
    _DEFAULT_SPLIT = 2.0 / 3.0

    def showEvent(self, event):
        """Poignée placée à la 1re apparition: avant, la hauteur des
        widgets n'est pas connue et les facteurs d'étirement seuls
        laissaient au formulaire vide une place ridicule."""
        super().showEvent(event)
        if not getattr(self, '_split_placed', False):
            split = getattr(self, '_col1_split', None)
            if split is not None and split.height() > 0:
                self._split_placed = True
                self._apply_default_split()

    def _apply_default_split(self):
        """Replace la poignée à sa proportion, la hauteur ayant pu
        changer pendant que le splitter était masqué."""
        split = getattr(self, '_col1_split', None)
        if split is None:
            return
        total = split.height() or sum(split.sizes())
        if total <= 0:
            return
        ratio = getattr(self, '_split_ratio', self._DEFAULT_SPLIT)
        top = int(total * ratio)
        split.setSizes([top, max(1, total - top)])

    def _on_split_moved(self, *_args):
        """Mémorise la proportion choisie: elle survit au passage par
        la surcouche « Ajouter », et gèle l'ajustement automatique."""
        sizes = self._col1_split.sizes()
        total = sum(sizes)
        if total > 0:
            self._split_ratio = sizes[0] / total
            self._split_user_defined = True

    def ajuster_hauteur_formulaire(self):
        """Donne au formulaire la hauteur qu'il demande, si elle tient.

        Un formulaire court (perçage: quatre champs) laissait un grand
        vide sous lui pendant que la liste se serrait, et un long
        (BPM) défilait alors que la place existait. Tant que
        l'utilisateur n'a pas tiré la poignée lui-même, elle suit le
        contenu."""
        if getattr(self, '_split_user_defined', False):
            return
        # Sélection multiple: ne pas voler la place à la liste — on
        # est en train d'y cocher plusieurs séquences (Ctrl+clic), et
        # rétrécir la liste les ferait sortir de vue.
        try:
            if len(self.op_list.selected_rows()) >= 2:
                return
        except RuntimeError:
            pass
        split = getattr(self, '_col1_split', None)
        if split is None or split.isHidden():
            return
        total = split.height() or sum(split.sizes())
        if total <= 0:
            return
        interieur = self.param_form.widget()
        voulu = (interieur.sizeHint().height() + 12) if interieur else 0
        if voulu <= 0:
            return
        # La liste garde au moins le quart de la colonne
        haut = max(int(total * 0.25), total - voulu)
        haut = min(haut, int(total * 0.85))
        # Redimensionner la zone de liste remet son défilement à zéro:
        # on le garde, sinon la liste remonte en haut à chaque
        # changement de sélection (Ctrl+clic sur plusieurs séquences)
        try:
            _v = self.op_list.verticalScrollBar().value()
        except RuntimeError:
            _v = 0
        split.setSizes([haut, max(1, total - haut)])
        QTimer.singleShot(0, lambda: self._reposer_defilement(_v))

    def _hide_main_content(self):
        """Cache la liste des opé et le formulaire pour laisser la place.

        C'est le SPLITTER qu'on masque, pas seulement ses deux
        enfants: vide, il gardait sa part de hauteur et la surcouche
        « Ajouter » n'occupait plus toute la colonne."""
        self._col1_split.hide()

    def _show_main_content(self):
        """Restaure la liste et le formulaire."""
        self._add_panel.hide()
        if hasattr(self, '_nds_widget') and self._nds_widget:
            try:
                mw = self.window()
                if hasattr(mw, 'hide_col1_overlay') \
                        and not self._nds_widget.isHidden():
                    mw.hide_col1_overlay(self._nds_widget)
                else:
                    self._nds_widget.hide()
            except RuntimeError:
                pass
        self._col1_split.show()
        self.op_list.show()
        self.param_form.show()
        self._apply_default_split()

    def _add_op(self, op_type: str):
        self._show_main_content()
        if op_type == "gamme_gravure":
            self._creer_gamme()
            return
        try:
            op_class = OperationRegistry.get(op_type)
        except KeyError:
            return
        op = OperationInstance(op_type, op_class.DISPLAY_NAME)
        # Merge code defaults with user-configured defaults
        op.params = self._default_params.get_defaults(op_type)
        with self._ajout_sans_rechargement():
            if self._undo_stack:
                from src.core.undo_commands import AddOperationCommand
                self._undo_stack.push(AddOperationCommand(self.program, op))
            else:
                self.program.add_operation(op)
        self.op_list.select_op(self.program.operation_count - 1)
        # Vérifier si miroir X/Y implique un changement de direction taraudage
        self._check_mirror_thread_direction()

    @contextmanager
    def _ajout_sans_rechargement(self):
        """L'ajout d'une opération émet « ajoutée » puis « modifié »:
        chacun reconstruisait la liste et rechargeait le formulaire de
        l'opération D'AVANT, que la nouvelle remplace aussitôt (trois
        formulaires construits pour un). Pendant le bloc, plus de
        sélection à rétablir et une seule reconstruction, à la fin."""
        self._current_index = -1
        self._liste_suspendue = getattr(self, '_liste_suspendue', 0) + 1
        try:
            yield
        finally:
            self._liste_suspendue -= 1
            if not self._liste_suspendue and getattr(
                    self, '_liste_a_refaire', False):
                self._liste_a_refaire = False
                self._refresh_list()

    def _on_add_tool_program_op(self, prog_name: str):
        """Programme outil choisi dans « Ajouter Opération »: crée une
        opé Appel Prog Ext liée (params['tool_program']) et LANCE le
        programme. Le .simpl qu'il déposera dans « Vers NeoDrive »
        sera proposé pour remplir le chemin de cette opération."""
        self._show_main_content()
        op = OperationInstance("appel_programme", prog_name)
        op.params = self._default_params.get_defaults("appel_programme")
        op.params['tool_program'] = prog_name
        if self._undo_stack:
            from src.core.undo_commands import AddOperationCommand
            self._undo_stack.push(AddOperationCommand(self.program, op))
        else:
            self.program.add_operation(op)
        self.op_list.select_op(self.program.operation_count - 1)
        # Lancer le programme outil
        from src.integrations import tool_programs as tp
        prog = next((p for p in tp.discover_tool_programs()
                     if p.name == prog_name), None)
        if prog is None:
            QMessageBox.warning(
                self, "Programmes outils",
                f"« {prog_name} » introuvable dans le dossier "
                "Programmes outils.")
            return
        err = tp.launch_tool_program(prog)
        if err:
            QMessageBox.warning(
                self, "Programmes outils",
                f"Impossible de lancer « {prog_name} »:\n{err}")

    def _add_favorite(self, ops_list: list):
        """Insère une séquence d'opérations depuis un favori."""
        self._show_main_content()
        for op_data in ops_list:
            op_type = op_data.get('type', '')
            try:
                op_class = OperationRegistry.get(op_type)
            except KeyError:
                continue
            op_name = op_data.get('name', op_class.DISPLAY_NAME)
            op = OperationInstance(op_type, op_name)
            op.params = self._default_params.get_defaults(op_type)
            # Appliquer les paramètres du favori
            fav_params = op_data.get('params', {})
            op.params.update(fav_params)
            # Auto-sélectionner l'outil par article
            tool_article = op_data.get('tool_article', '')
            if tool_article and self.tool_library:
                for tid, tool in self.tool_library.tools.items():
                    if tool.article_nr == tool_article:
                        op.tool_id = tid
                        break
            # Points multi-point du favori (perçages/taraudages)
            fav_points = op_data.get('points', [])
            if fav_points:
                op.points = [dict(p) for p in fav_points]
                op.x = op.points[0].get('x', 0.0)
                op.y = op.points[0].get('y', 0.0)
            # Titre dynamique pour décalage_origine
            if op_type == "decalage_origine":
                from src.operations.decalage_origine import DecalageOrigine
                op.name = DecalageOrigine.build_dynamic_name(op.params)
            self.program.add_operation(op)
        if self.program.operation_count > 0:
            self.op_list.select_op(
                self.program.operation_count - 1)
        self.code_needs_update.emit()

    def _unique_copy_name(self, base_name: str) -> str:
        """Nom incrémental pour duplication: 'Perçage' → 'Perçage (2)',
        'Perçage (2)' → 'Perçage (3)'..."""
        m = re.match(r'^(.*?)\s*\((\d+)\)$', base_name)
        root = m.group(1) if m else base_name
        # retirer aussi l'ancien suffixe " (copie)"
        if root.endswith(" (copie)"):
            root = root[:-8]
        existing = {o.name for o in self.program.operations}
        n = 2
        while f"{root} ({n})" in existing:
            n += 1
        return f"{root} ({n})"

    # ── Specs du programme (barre repliable) ──

    #: le résumé est TRONQUÉ: son texte complet fixait la largeur
    #: minimale de la colonne, au point d'imposer une fenêtre plus
    #: large que l'écran
    _SPECS_MAX_CHARS = 64

    def set_specs_summary(self, text: str):
        """Met à jour le résumé d'une ligne (brut, auteur, comment.)."""
        if text and len(text) > self._SPECS_MAX_CHARS:
            short = text[:self._SPECS_MAX_CHARS].rstrip() + "…"
        else:
            short = text
        self.specs_btn.setText(f"📐 {short}" if short
                               else "📐 Specs programme")
        self.specs_btn.setToolTip(text or "Specs du programme")

    def _on_specs_toggled(self, shown: bool):
        """Déplie la barre: les réglages du programme (brut,
        commentaire, auteur) sont montrés SUR PLACE, au-dessus de la
        première opération, plutôt que dans l'onglet Paramètres."""
        if shown and self.specs_panel.layout() is None:
            self._build_specs_panel()
        self.specs_panel.setVisible(shown)

    def _build_specs_panel(self):
        """Construit les champs, reliés au panneau Paramètres pour
        qu'il n'existe qu'UNE source de vérité par onglet."""
        pp = self._params_panel()
        grid = QGridLayout(self.specs_panel)
        grid.setContentsMargins(6, 2, 6, 4)
        grid.setSpacing(3)
        if pp is None:
            grid.addWidget(QLabel("Paramètres indisponibles"), 0, 0)
            return

        def _mini(text):
            lab = QLabel(text)
            lab.setStyleSheet(
                f"color: {COLORS['text_dim']}; font-size: 10px;")
            return lab

        self._specs_wp = {}
        for col, (key, label) in enumerate(
                (('min_x', 'X min'), ('min_y', 'Y min'),
                 ('min_z', 'Z min'))):
            grid.addWidget(_mini(label), 0, col * 2)
            spin = SpinCote()
            spin.setRange(-9999, 9999)
            spin.setDecimals(2)
            spin.setMaximumWidth(70)
            spin.setValue(pp._wp_spins[key].value())
            spin.editingFinished.connect(
                lambda k=key: self._push_spec_spin(k))
            self._specs_wp[key] = spin
            grid.addWidget(spin, 0, col * 2 + 1)
        for col, (key, label) in enumerate(
                (('max_x', 'X max'), ('max_y', 'Y max'),
                 ('max_z', 'Z max'))):
            grid.addWidget(_mini(label), 1, col * 2)
            spin = SpinCote()
            spin.setRange(-9999, 9999)
            spin.setDecimals(2)
            spin.setMaximumWidth(70)
            spin.setValue(pp._wp_spins[key].value())
            spin.editingFinished.connect(
                lambda k=key: self._push_spec_spin(k))
            self._specs_wp[key] = spin
            grid.addWidget(spin, 1, col * 2 + 1)

        grid.addWidget(_mini("Commentaire"), 2, 0)
        self._specs_comment = QLineEdit(
            pp._comment_edit.toPlainText().split('\n')[0])
        self._specs_comment.setPlaceholderText(
            "Commentaire du programme (visible sur la machine)")
        self._specs_comment.editingFinished.connect(
            self._push_spec_comment)
        grid.addWidget(self._specs_comment, 2, 1, 1, 5)

        # Les templates s'appliquent ICI: renvoyer vers l'onglet
        # Paramètres obligeait à quitter la liste d'opérations — et le
        # bouton ne trouvait même plus cet onglet.
        self._specs_tpl = NoScrollComboBox()
        self._specs_tpl.setMaximumHeight(24)
        self._specs_tpl.setToolTip(
            "Applique un brut enregistré au programme de cet onglet")
        self._specs_tpl.currentIndexChanged.connect(
            self._on_specs_template_selected)
        grid.addWidget(self._specs_tpl, 3, 0, 1, 4)
        self._reload_specs_templates()

        from src.gui.icons import get_button_icon
        tpl_save = QPushButton("")
        tpl_save.setIcon(get_button_icon("save", 14))
        tpl_save.setFixedSize(24, 24)
        tpl_save.setToolTip("Enregistrer le brut courant comme template")
        tpl_save.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tpl_save.clicked.connect(self._on_specs_template_save)
        grid.addWidget(tpl_save, 3, 4)

        tpl_more = QPushButton("")
        tpl_more.setIcon(get_button_icon("settings", 14))
        tpl_more.setFixedSize(24, 24)
        tpl_more.setToolTip(
            "Gérer les templates dans l'onglet Paramètres")
        tpl_more.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tpl_more.clicked.connect(self._open_params_tab)
        grid.addWidget(tpl_more, 3, 5)

    def _reload_specs_templates(self):
        """Repeuple la liste depuis le fichier des templates."""
        combo = getattr(self, '_specs_tpl', None)
        pp = self._params_panel()
        if combo is None or pp is None:
            return
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("Templates de brut…", None)
        for tpl in pp._load_wp_templates():
            dx = tpl.get('max_x', 0) - tpl.get('min_x', 0)
            dy = tpl.get('max_y', 0) - tpl.get('min_y', 0)
            dz = tpl.get('max_z', 0) - tpl.get('min_z', 0)
            combo.addItem(
                f"{tpl.get('name', '?')}  ({dx:g}×{dy:g}×{dz:g})", tpl)
        combo.blockSignals(False)

    def _on_specs_template_selected(self, index: int):
        pp = self._params_panel()
        combo = getattr(self, '_specs_tpl', None)
        if pp is None or combo is None:
            return
        tpl = combo.itemData(index)
        if not tpl:
            return
        for key in pp._WP_KEYS:
            if key in tpl:
                pp._wp_spins[key].setValue(float(tpl[key]))
        pp._on_project_changed()
        self.refresh_specs_fields()

    def _on_specs_template_save(self):
        pp = self._params_panel()
        if pp is None:
            return
        pp._on_wp_template_save()
        self._reload_specs_templates()

    def _params_panel(self):
        win = self.window()
        return getattr(win, 'params_panel', None)

    def _push_spec_spin(self, key: str):
        pp = self._params_panel()
        if pp is None:
            return
        # (le programme le dit à qui régénère: `settings_changed`)
        pp._wp_spins[key].setValue(self._specs_wp[key].value())
        pp._on_project_changed()

    def _push_spec_comment(self):
        pp = self._params_panel()
        if pp is None:
            return
        # la ligne n'est qu'un aperçu du commentaire: le quitter sans y
        # toucher ne le réduit pas à sa première ligne
        if self._specs_comment.text() == \
                pp._comment_edit.toPlainText().split('\n')[0]:
            return
        pp._comment_edit.setPlainText(self._specs_comment.text())
        pp._on_project_changed()

    def _open_params_tab(self):
        """Montre l'onglet Paramètres, où qu'il soit rangé.

        Il a changé de colonne: chercher dans une seule laissait le
        bouton sans effet."""
        win = self.window()
        pp = self._params_panel()
        if pp is None:
            return False
        # Depuis le round 96, c'est une page sur toute la fenêtre
        ouvrir = getattr(win, 'afficher_parametres', None)
        if callable(ouvrir):
            ouvrir()
            return True
        for name in ('_col1_tabs', '_col2_tabs', '_col3_tabs'):
            tabs = getattr(win, name, None)
            if tabs is None:
                continue
            idx = tabs.indexOf(pp)
            if idx >= 0:
                tabs.setCurrentIndex(idx)
                return True
        return False

    def refresh_specs_fields(self):
        """Recharge les champs dépliés depuis le panneau Paramètres
        (changement d'onglet)."""
        pp = self._params_panel()
        if pp is None or self.specs_panel.layout() is None:
            return
        for key, spin in getattr(self, '_specs_wp', {}).items():
            spin.blockSignals(True)
            spin.setValue(pp._wp_spins[key].value())
            spin.blockSignals(False)
        if hasattr(self, '_specs_comment'):
            self._specs_comment.blockSignals(True)
            self._specs_comment.setText(
                pp._comment_edit.toPlainText().split('\n')[0])
            self._specs_comment.blockSignals(False)
        # Un template ajouté depuis l'onglet Paramètres doit apparaître
        # ici aussi, sans redémarrer
        self._reload_specs_templates()

    # ── Programmes outils externes ──

    def _show_tool_programs_menu(self):
        """Menu 🧰: liste les programmes du dossier « Programmes
        outils » (rescanné à chaque ouverture — un nouveau dossier
        .py/.exe apparaît sans redémarrer NeoDrive)."""
        from src.integrations import tool_programs as tp
        from PySide6.QtGui import QIcon
        menu = QMenu(self)
        programs = tp.discover_tool_programs()
        if not programs:
            act = menu.addAction("(aucun programme outil trouvé)")
            act.setEnabled(False)
        for prog in programs:
            sub = menu.addMenu(prog.name)
            if prog.icon_path:
                sub.setIcon(QIcon(prog.icon_path))
            launch = sub.addAction("▶  Lancer")
            launch.triggered.connect(
                lambda _=False, p=prog: self._launch_tool_program(p))
            share = sub.addAction("Partager le tools.json NeoDrive")
            share.setCheckable(True)
            share.setChecked(prog.share_neodrive_tools)
            share.setToolTip(
                "Transmet data/tools.json au lancement "
                "(--neodrive-tools + env NEODRIVE_TOOLS_JSON)")
            share.toggled.connect(
                lambda checked, p=prog:
                self._set_tool_program_share(p, checked))
            open_dir = sub.addAction("📂  Ouvrir le dossier")
            open_dir.triggered.connect(
                lambda _=False, d=prog.dir_path: os.startfile(d))
        menu.addSeparator()
        folder_act = menu.addAction(
            "📂  Dossier des programmes outils")
        folder_act.triggered.connect(self._open_tool_programs_dir)
        menu.exec(self.tools_btn.mapToGlobal(
            self.tools_btn.rect().bottomLeft()))

    def _launch_tool_program(self, prog):
        from src.integrations import tool_programs as tp
        err = tp.launch_tool_program(prog)
        if err:
            QMessageBox.warning(
                self, "Programmes outils",
                f"Impossible de lancer « {prog.name} »:\n{err}")

    def _set_tool_program_share(self, prog, checked: bool):
        """Mémorise le partage tools.json dans le manifeste du
        programme (neodrive_tool.json, voyage avec le dossier)."""
        from src.integrations import tool_programs as tp
        prog.manifest['share_neodrive_tools'] = bool(checked)
        prog.manifest.setdefault('name', prog.name)
        tp.write_manifest(prog)

    def _open_tool_programs_dir(self):
        from src.integrations import tool_programs as tp
        d = tp.tool_programs_dir()
        os.makedirs(d, exist_ok=True)
        os.startfile(d)

    _MAX_PREFILL_SETS = 30
    #: rectangles du dessin proposés en tête de liste
    _MAX_DXF_RECTS = 20

    def _dxf_rectangle_sets(self) -> list:
        """Rectangles du dessin, proposés au formulaire.

        Les centres de cercles alimentaient déjà les perçages; un
        rectangle du DXF se relevait à la main pour régler un
        surfaçage, une poche ou une découpe."""
        canvas = getattr(getattr(self.window(), 'dxf_panel', None),
                         'canvas', None)
        if canvas is None:
            return []
        try:
            rects = canvas.detected_rectangles()
        except Exception:
            return []
        out = []
        for r in rects[:self._MAX_DXF_RECTS]:
            rayon = r.get('rayon') or 0.0
            etiq = (f"▭ {r['width']:g}×{r['height']:g}  ·  "
                    f"X{r['x']:g} Y{r['y']:g}")
            if rayon:
                etiq += f"  r{rayon:g}"
            etiq += "   (dessin)"
            out.append({
                'label': etiq,
                'x': r['x'], 'y': r['y'],
                'width_x': r['width'], 'width_y': r['height'],
                'corner_radius': rayon or None,
                'diameter': None, 'depth': None,
            })
        return out

    def _collect_prefill_sets(self) -> list:
        """Ensembles (PosX, PosY, dimX, dimY, Pz) déjà employés dans le
        programme-onglet courant, dédupliqués, pour le préremplissage
        du formulaire. L'opération en cours d'édition est exclue."""
        cur = self.param_form._current_op
        seen = {}
        for op in self.program.operations:
            if cur is not None and op.id == cur.id:
                continue
            # Ignorer les opés sans coordonnées (séquences, décalages,
            # dialogues...): leur X/Y n'a pas de sens en préremplissage
            try:
                op_class = OperationRegistry.get(op.operation_type)
                if not getattr(op_class, 'REQUIRES_COORDINATES', True):
                    continue
            except KeyError:
                continue
            dim_x = op.params.get('width_x')
            dim_y = op.params.get('width_y')
            diameter = op.params.get('diameter')
            depth = op.params.get('depth')
            points = op.points or [None]
            for pt in points:
                if pt is not None:
                    x = pt.get('x', op.x)
                    y = pt.get('y', op.y)
                    # La profondeur d'un point est sous 'depth', pas
                    # 'z' (qui n'existe pas): la chercher là revenait à
                    # perdre le Pz de toute opération multi-point
                    pz = pt.get('depth', depth)
                else:
                    x, y, pz = op.x, op.y, depth
                key = (x, y, dim_x, dim_y, diameter, pz)
                if key in seen:
                    continue
                parts = [f"X{x:g} Y{y:g}"]
                if dim_x is not None and dim_y is not None:
                    parts.append(f"{dim_x:g}×{dim_y:g}")
                if diameter is not None:
                    parts.append(f"Ø{diameter:g}")
                if pz is not None:
                    parts.append(f"Pz {pz:g}")
                seen[key] = {
                    'label': "  ·  ".join(parts) + f"   ({op.name})",
                    'x': x, 'y': y,
                    'width_x': dim_x, 'width_y': dim_y,
                    'diameter': diameter, 'depth': pz,
                }
        values = list(seen.values())
        values = self._dxf_rectangle_sets() + values
        # Plafond: une liste déroulante de centaines d'entrées est
        # illisible ET coûteuse à construire à chaque ouverture de
        # formulaire. On garde les plus récentes (fin de programme).
        if len(values) > self._MAX_PREFILL_SETS:
            values = values[-self._MAX_PREFILL_SETS:]
        return values

    # ── Gestion des favoris ──

    def _connect_add_panel(self, panel):
        panel.operation_chosen.connect(self._add_op)
        # une étoile ou une flèche: le catalogue se refait, différé
        # (on est dans le clic d'un de ses boutons)
        panel.catalogue_change.connect(
            lambda: QTimer.singleShot(0, self._rebuild_add_panel))
        panel.favorite_chosen.connect(self._add_favorite)
        panel.favorite_save_requested.connect(self._on_save_favorite)
        panel.favorite_delete_requested.connect(self._on_delete_favorite)
        panel.favorite_rename_requested.connect(self._on_rename_favorite)
        panel.tool_program_chosen.connect(self._on_add_tool_program_op)

    def _favorites_path(self) -> str:
        # à côté des réglages de test quand NEODRIVE_APP_SETTINGS les
        # détourne: la suite ajoutait un favori au fichier du dépôt
        detour = os.environ.get('NEODRIVE_APP_SETTINGS')
        if detour:
            return os.path.join(os.path.dirname(detour), "favorites.json")
        from src.core.tool_library import get_base_dir
        return os.path.join(get_base_dir(), "data", "favorites.json")

    def _write_favorites(self, favorites: list) -> bool:
        try:
            from src.core.fichiers_surs import ecrire_json_sur
            ecrire_json_sur(self._favorites_path(), favorites,
                            garder_bak=True, indent=2, ensure_ascii=False)
            return True
        except OSError as e:
            QMessageBox.warning(
                self, "Favoris",
                f"Impossible d'enregistrer les favoris:\n{e}")
            return False

    def set_expert_mode(self, enabled: bool):
        """Mode expert du panneau: retenu ici pour que les widgets
        reconstruits (popup Ajouter, formulaire) le retrouvent."""
        self._expert_mode = enabled
        self._add_panel.set_expert_mode(enabled)
        self.param_form.set_expert_mode(enabled)

    def _rebuild_add_panel(self):
        """Recrée le popup Ajouter (la grille des favoris est figée à
        la construction)."""
        layout = self.layout()
        idx = layout.indexOf(self._add_panel)
        was_visible = self._add_panel.isVisible()
        self._add_panel.deleteLater()
        self._add_panel = AddOperationPopup(self)
        # Le popup neuf ignore le mode courant: le lui redonner,
        # sinon les opérations expert réapparaissent en mode simple
        self._add_panel.set_expert_mode(self._expert_mode)
        self._connect_add_panel(self._add_panel)
        self._add_panel.nds_action.connect(self._on_nds_action)
        layout.insertWidget(idx, self._add_panel)
        if was_visible:
            self._add_panel.setFixedHeight(16777215)
            self._add_panel.setMaximumHeight(16777215)
            self._add_panel.show()
        else:
            self._add_panel.hide()

    def _on_save_favorite(self):
        """Sauve la séquence d'opérations du programme courant comme
        favori réutilisable."""
        if self.program.operation_count == 0:
            QMessageBox.information(
                self, "Favoris", "Aucune opération à sauvegarder.")
            return
        name, ok = QInputDialog.getText(
            self, "Nouveau favori", "Nom du favori:")
        if not ok or not name.strip():
            return
        name = name.strip()
        desc, _ok = QInputDialog.getText(
            self, "Nouveau favori", "Description (optionnel):")
        ops_list = []
        for op in self.program.operations:
            entry = {
                'type': op.operation_type,
                'name': op.name,
                'params': {k: v for k, v in op.params.items()
                           if not k.startswith('_')},
            }
            if op.tool_id and self.tool_library:
                tool = self.tool_library.get_tool(op.tool_id)
                if tool:
                    entry['tool_article'] = tool.article_nr
            if op.points:
                entry['points'] = [dict(p) for p in op.points]
            ops_list.append(entry)
        favorites = self._add_panel._load_favorites()
        # Remplacer si le nom existe déjà
        favorites = [f for f in favorites if f.get('name') != name]
        favorites.append({
            'name': name,
            'description': desc.strip() if desc else "",
            'operations': ops_list,
        })
        if self._write_favorites(favorites):
            self._add_panel.recharger_favoris()

    def _on_delete_favorite(self, name: str):
        favorites = self._add_panel._load_favorites()
        new_list = [f for f in favorites if f.get('name') != name]
        if len(new_list) == len(favorites):
            return
        if self._write_favorites(new_list):
            self._add_panel.recharger_favoris()
            # Rafraîchir l'étoile si l'opé affichée était ce favori
            cur = self.param_form._current_op
            if cur is not None and cur.name == name:
                self.param_form.set_favorite_star(False)
            self._refresh_list()

    def _on_rename_favorite(self, name: str):
        """Renomme un favori (menus favoris, clic droit)."""
        new_name, ok = QInputDialog.getText(
            self, "Renommer le favori",
            f"Nouveau nom pour « {name} »:", text=name)
        if not ok or not new_name.strip() or new_name.strip() == name:
            return
        new_name = new_name.strip()
        favorites = self._add_panel._load_favorites()
        if any(f.get('name') == new_name for f in favorites):
            QMessageBox.warning(
                self, "Favoris",
                f"Un favori nommé « {new_name} » existe déjà.")
            return
        for f in favorites:
            if f.get('name') == name:
                f['name'] = new_name
        if self._write_favorites(favorites):
            self._add_panel.recharger_favoris()
            self._refresh_list()

    def _single_op_favorite_entry(self, op) -> dict:
        """Sérialise UNE opération au format favori."""
        entry = {
            'type': op.operation_type,
            'name': op.name,
            'params': {k: v for k, v in op.params.items()
                       if not k.startswith('_')},
        }
        if op.tool_id and self.tool_library:
            tool = self.tool_library.get_tool(op.tool_id)
            if tool:
                entry['tool_article'] = tool.article_nr
        if op.points:
            entry['points'] = [dict(p) for p in op.points]
        return entry

    def _favorite_names(self) -> set:
        """Noms de tous les favoris (un seul accès fichier)."""
        return {f.get('name') for f in self._add_panel._load_favorites()}

    def _is_single_op_favorite(self, op) -> bool:
        """True si un favori porte le nom de cette opération."""
        return op.name in self._favorite_names()

    def _toggle_op_favorite(self, op) -> bool:
        """Ajoute/retire UNE opération des favoris (favori mono-opé
        nommé comme l'opération). Retourne le nouvel état favori."""
        favorites = self._add_panel._load_favorites()
        is_fav = any(f.get('name') == op.name for f in favorites)
        if is_fav:
            new_list = [f for f in favorites
                        if f.get('name') != op.name]
            if not self._write_favorites(new_list):
                return True
            new_state = False
        else:
            favorites.append({
                'name': op.name,
                'description': "",
                'operations': [self._single_op_favorite_entry(op)],
            })
            if not self._write_favorites(favorites):
                return False
            new_state = True
        self._add_panel.recharger_favoris()
        # Synchroniser les deux affichages de l'étoile
        cur = self.param_form._current_op
        if cur is not None and cur.name == op.name:
            self.param_form.set_favorite_star(new_state)
        return new_state

    def _on_favorite_star_toggle(self):
        """Étoile du titre du formulaire: opération courante."""
        op = self.param_form._current_op
        if op is None:
            return
        self._toggle_op_favorite(op)
        if self._current_index >= 0:
            self._update_list_item_text(self._current_index)

    def _on_toggle_preview(self, index: int):
        """Œil d'une ligne: montrer ou masquer l'opération au canvas.

        Ce que l'œil montre part aussi dans le PNG et le PDF: c'est le
        même choix, on ne le refait pas au moment d'imprimer."""
        op = self.program.get_operation(index)
        if op is None:
            return
        op.params['preview'] = not op_preview(op)
        self._update_list_item_text(index)
        self._update_group_header(getattr(op, 'group_id', ''))
        self.code_needs_update.emit()

    def _on_toggle_annotations(self, index: int):
        """Bouton « A » d'une ligne: montrer/masquer les annotations
        (étiquettes) ET la ligne de légende de CETTE opération, sans
        toucher aux autres ni à son tracé."""
        op = self.program.get_operation(index)
        if op is None:
            return
        canvas = getattr(getattr(self.window(), 'dxf_panel', None),
                         'canvas', None)
        if canvas is None:
            return
        visible = canvas.annotations_op_visibles(getattr(op, 'id', None))
        canvas.set_annotations_op_visible(getattr(op, 'id', None),
                                          not visible)
        # le bouton de la ligne suit
        row = self.op_list.row_of_op(index)
        item = self.op_list.item(row) if row >= 0 else None
        if item is not None:
            item.setData(_FavStarDelegate.ANNOT_ROLE, self._annot_de(op))
            self.op_list.viewport().update()
        # redessiner: la légende et les étiquettes se refont
        redessiner = getattr(self.window(), '_refresh_canvas_op', None)
        if callable(redessiner):
            redessiner()

    def _on_set_selection_preview(self, visible: bool):
        """Menu contextuel: aperçu de TOUTE la sélection."""
        rows = self.op_list.selected_rows()
        groupes = set()
        for index in rows:
            op = self.program.get_operation(index)
            if op is not None:
                op.params['preview'] = bool(visible)
                self._update_list_item_text(index)
                groupes.add(getattr(op, 'group_id', ''))
        for gid in groupes:
            self._update_group_header(gid)
        self.code_needs_update.emit()

    def _on_row_browse(self, index: int):
        """Clic sur 📂 d'une ligne: choisir le fichier appelé/importé.

        L'opération prend le NOM du fichier: dans la liste, on lit
        quel programme est appelé sans ouvrir le formulaire."""
        import os
        op = self.program.get_operation(index)
        if op is None:
            return
        start = os.path.dirname(
            str(op.params.get('filepath', '') or '')) or ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Programme SimPl externe", start,
            "Fichiers SimPl (*.SimPl *.simpl);;Tous (*)")
        if not path:
            return
        op.params['filepath'] = path
        base = os.path.splitext(os.path.basename(path))[0]
        if base:
            op.name = base[:40]
        self.op_list.select_op(index)
        self._refresh_list()
        self._update_list_item_text(index)
        if op.operation_type == "import_programme":
            self._convert_external_call(index)
        else:
            self.code_needs_update.emit()

    def _on_list_favorite_toggled(self, row: int):
        """Clic sur l'étoile d'une ligne de la liste d'opérations."""
        op = self.program.get_operation(row)
        if op is None:
            return
        self._toggle_op_favorite(op)
        self._update_list_item_text(row)

    def _on_add_instance(self):
        """« + instance »: une opération de plus dans le MÊME ensemble.

        Distinct de Dupliquer, qui sert à repartir d'une opération pour
        en faire une autre (souvent avec un autre outil). Ici l'outil,
        ses specs et le formulaire sont ceux de l'ensemble; seules les
        cotes changent. La nouvelle instance se pose après la dernière
        — un ensemble doit rester d'un seul tenant."""
        import uuid as _uuid
        if self._current_index < 0:
            return
        op = self.program.get_operation(self._current_index)
        if op is None:
            return
        if not getattr(op, 'group_id', ''):
            op.group_id = str(_uuid.uuid4())[:8]
            op.group_name = op.name
        clone = op.clone()
        clone.name = self._unique_copy_name(op.name)
        clone.group_id = op.group_id
        clone.group_name = op.group_name
        members = [i for i, o in enumerate(self.program.operations)
                   if getattr(o, 'group_id', '') == op.group_id]
        new_index = max(members) + 1
        if self._undo_stack:
            from src.core.undo_commands import AddOperationCommand
            self._undo_stack.push(AddOperationCommand(
                self.program, clone, new_index))
        else:
            self.program.add_operation(clone, new_index)
        self._refresh_list()
        self.op_list.select_op(new_index)
        self.code_needs_update.emit()

    @staticmethod
    def _oeil_de(op):
        """L'œil d'une ligne: l'aperçu au canvas, ou None (pas
        d'œil) pour ce qui ne dessine rien — décalage d'origine,
        dialogue, palpage, réglages. La tête de gamme garde le sien:
        elle montre le dessin partagé."""
        genre = getattr(op, 'operation_type', '')
        if genre != "gamme_gravure":
            try:
                classe = OperationRegistry.get(genre)
            except KeyError:
                classe = None
            if classe is not None and getattr(classe, 'HORS_MATIERE',
                                              False):
                return None
        return bool(op_preview(op))

    def _annot_de(self, op):
        """État du bouton annotations d'une ligne: None (pas de bouton)
        pour ce qui ne dessine rien, sinon True/False selon que les
        annotations de cette opé sont montrées au canvas."""
        if self._oeil_de(op) is None:
            return None
        canvas = getattr(getattr(self.window(), 'dxf_panel', None),
                         'canvas', None)
        if canvas is None:
            return True
        try:
            return canvas.annotations_op_visibles(getattr(op, 'id', None))
        except Exception:
            return True

    def _dupliquer_plusieurs(self, indices: list) -> int:
        """Copie plusieurs opérations à la suite de la dernière, dans
        l'ordre; les membres d'un même ensemble vont dans un NOUVEL
        ensemble (tête de gamme comprise). Une seule annulation. Rend
        l'index de la première copie."""
        indices = sorted(i for i in set(indices)
                         if 0 <= i < self.program.operation_count)
        if not indices:
            return -1
        import uuid
        nouveaux_groupes = {}
        creations = []
        debut = indices[-1] + 1
        for rang, index in enumerate(indices):
            op = self.program.get_operation(index)
            clone = op.clone()
            clone.name = self._unique_copy_name(op.name)
            gid = getattr(op, 'group_id', '') or ""
            if gid:
                if gid not in nouveaux_groupes:
                    nouveaux_groupes[gid] = str(uuid.uuid4())[:8]
                clone.group_id = nouveaux_groupes[gid]
                clone.group_name = f"{op.group_name} (copie)" \
                    if getattr(op, 'group_name', '') else ""
            else:
                clone.group_id = ""
                clone.group_name = ""
            creations.append((debut + rang, clone))
        self.inserer_operations(
            creations, f"Dupliquer {len(creations)} opération(s)")
        self.op_list.select_op(debut)
        return debut

    def _on_duplicate(self):
        """Copie INDÉPENDANTE de l'opération (autre outil possible) —
        ou de toute la sélection, un ensemble faisant un nouvel
        ensemble.

        Pour ajouter une instance au même ensemble, voir
        « + instance »."""
        rows = self.op_list.selected_rows()
        if len(rows) >= 2:
            self._dupliquer_plusieurs(rows)
            return
        if self._current_index < 0:
            return
        op = self.program.get_operation(self._current_index)
        if op:
            clone = op.clone()
            clone.name = self._unique_copy_name(op.name)
            clone.group_id = ""
            clone.group_name = ""
            new_index = self._current_index + 1
            if self._undo_stack:
                from src.core.undo_commands import AddOperationCommand
                self._undo_stack.push(AddOperationCommand(
                    self.program, clone, new_index))
            else:
                self.program.add_operation(clone, new_index)
            # Focus sur l'opération nouvellement créée
            self.op_list.select_op(new_index)

    def _retirer_operation(self, index: int):
        """Retire une opération, avec annulation."""
        if self._undo_stack:
            from src.core.undo_commands import RemoveOperationCommand
            self._undo_stack.push(RemoveOperationCommand(
                self.program, index))
        else:
            self.program.remove_operation(index)

    def _supprimer_plusieurs(self, indices: list) -> int:
        """Retire plusieurs opérations, du bas vers le haut, sous une
        seule annulation. Rend le nombre retiré."""
        indices = sorted({i for i in indices
                          if 0 <= i < self.program.operation_count},
                         reverse=True)
        if not indices:
            return 0
        if self._undo_stack is not None:
            from src.core.undo_commands import RemoveOperationCommand
            self._undo_stack.beginMacro(
                f"Supprimer {len(indices)} opération(s)")
            try:
                for index in indices:
                    self._undo_stack.push(RemoveOperationCommand(
                        self.program, index))
            finally:
                self._undo_stack.endMacro()
        else:
            for index in indices:
                self.program.remove_operation(index)
        count = self.program.operation_count
        if count > 0:
            self.op_list.select_op(min(indices[-1], count - 1))
        else:
            self.param_form.clear_form()
            self._current_index = -1
        self.code_needs_update.emit()
        return len(indices)

    def _on_delete(self):
        # Plusieurs opérations sélectionnées — un ensemble entier
        # quand on a cliqué son titre —: tout part, d'un coup
        rows = self.op_list.selected_rows()
        if len(rows) >= 2:
            self._supprimer_plusieurs(rows)
            return
        if self._current_index < 0:
            return
        op = self.program.get_operation(self._current_index)
        if op:
            deleted_idx = self._current_index
            self._retirer_operation(self._current_index)
            # Auto-sélectionner l'opération suivante ou précédente
            count = self.program.operation_count
            if count > 0:
                new_idx = min(deleted_idx, count - 1)
                self.op_list.select_op(new_idx)
            else:
                self.param_form.clear_form()
                self._current_index = -1
            self.code_needs_update.emit()

    def _on_contours_row(self, index: int):
        """Bouton DXF d'une ligne: reprendre les contours du dessin.

        Le geste appartient a la ligne: on n'ouvre pas le formulaire
        pour relever un contour qu'on vient de selectionner."""
        if index < 0 or index >= self.program.operation_count:
            return
        self.op_list.select_op(index)
        self._current_index = index
        self.param_form._on_contours_pickup()

    def _on_ope_vers_dessin_index(self, index: int):
        """Clic droit « Dessiner le parcours »: pose l'empreinte de
        l'opération sur le calque Dessin, où on la déplace, la met à
        la cote et la duplique comme un dessin."""
        if index < 0 or index >= self.program.operation_count:
            return
        self.op_list.select_op(index)
        self._current_index = index
        op = self.program.get_operation(index)
        canvas = getattr(getattr(self.window(), 'dxf_panel', None),
                         'canvas', None)
        if op is None or canvas is None:
            return
        n = canvas.entites_depuis_operation(op, calque=f"OPE {op.name}")
        # le trajet de l'outil, simulé depuis le code de l'opération
        parcours = []
        fenetre = self.window()
        trajet = getattr(fenetre, 'parcours_xy_operation', None)
        if callable(trajet):
            try:
                parcours = trajet(op)
            except Exception:
                parcours = []
        p = 0
        if parcours:
            if canvas.poser_polylignes(parcours, f"PARCOURS {op.name}"):
                p = 1
        dxf = getattr(fenetre, 'dxf_panel', None)
        if (n or p) and dxf is not None and hasattr(dxf, '_montrer_calque'):
            dxf._montrer_calque('drawn')
        morceaux = []
        if n:
            morceaux.append(f"contour en {n} entité(s)")
        if p:
            morceaux.append(f"parcours ({len(parcours)} tracé(s))")
        self._flash_status(
            f"« {op.name} » au dessin: " + " + ".join(morceaux)
            if morceaux else
            f"« {op.name} » n'a ni empreinte ni parcours à dessiner")

    def _on_delete_row(self, index: int):
        """Corbeille d'une ligne: supprimer CETTE opération, pas la
        sélection courante — on peut viser une ligne sans l'avoir
        sélectionnée."""
        if index < 0 or index >= self.program.operation_count:
            return
        self.op_list.select_op(index)
        self._current_index = index
        self._on_delete()

    def _on_raz(self):
        """Réinitialise toutes les opérations (RAZ)."""
        if self.program.operation_count == 0:
            return
        reply = QMessageBox.question(
            self, "RAZ",
            "Supprimer toutes les opérations ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            if self._undo_stack is not None:
                # Macro undo: un seul Ctrl+Z restaure tout
                from src.core.undo_commands import \
                    RemoveOperationCommand
                self._undo_stack.beginMacro(
                    "RAZ — supprimer toutes les opérations")
                while self.program.operation_count > 0:
                    self._undo_stack.push(
                        RemoveOperationCommand(self.program, 0))
                self._undo_stack.endMacro()
            else:
                while self.program.operation_count > 0:
                    self.program.remove_operation(0)
            self.param_form.clear_form()
            self._current_index = -1
            self.code_needs_update.emit()

    def _nds_files(self) -> list:
        """Noms (sans extension) des sous-programmes enregistrés."""
        import os
        dossier = self._get_programs_dir()
        try:
            return sorted(
                os.path.splitext(f)[0] for f in os.listdir(dossier)
                if f.lower().endswith('.nds'))
        except OSError:
            return []

    def _on_nds_action(self, action: str, nom: str):
        """Barre « Sous-programmes NDS » du panneau « + Opé »."""
        import os
        from src.io.program_serializer import SubProgramSerializer
        dossier = self._get_programs_dir()
        chemin = os.path.join(dossier, f"{nom}.nds") if nom else ""

        if action == 'refresh':
            self._add_panel.set_nds_names(self._nds_files())
            return

        if action == 'add':
            # Enregistrer la sélection (à défaut tout le programme)
            rows = self.op_list.selected_rows()
            ops = ([self.program.get_operation(i) for i in rows]
                   or list(self.program.operations))
            ops = [o for o in ops if o is not None]
            if not ops:
                QMessageBox.information(
                    self, "Sous-programme",
                    "Aucune opération à enregistrer.")
                return
            propose, ok = QInputDialog.getText(
                self, "Nouveau sous-programme",
                f"Nom du .nds ({len(ops)} opération(s)) :")
            if not ok or not propose.strip():
                return
            cible = os.path.join(dossier, f"{propose.strip()}.nds")
            # un nom déjà pris remplaçait le .nds existant sans un mot
            # (un bloc de 5 opés devenait une opé): on demande, et
            # l'ancien reste en .bak
            if os.path.exists(cible):
                reponse = QMessageBox.question(
                    self, "Sous-programme",
                    f"« {propose.strip()}.nds » existe déjà.\n\n"
                    f"Le remplacer par ces {len(ops)} opération(s) ?\n"
                    f"L'ancien reste en « {propose.strip()}.nds.bak ».",
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No)
                if reponse != QMessageBox.StandardButton.Yes:
                    self._flash_status(
                        f"{propose.strip()}.nds gardé tel quel")
                    return
            SubProgramSerializer.save(ops, cible)
            self._add_panel.set_nds_names(self._nds_files())
            self._flash_status(f"{propose.strip()}.nds enregistré")
            return

        if not nom or not os.path.isfile(chemin):
            QMessageBox.information(
                self, "Sous-programme",
                "Sélectionnez d'abord un sous-programme dans la liste.")
            return

        if action in ('insert', 'edit'):
            try:
                ops = SubProgramSerializer.load(chemin, self.tool_library)
            except Exception as exc:
                QMessageBox.warning(
                    self, "Sous-programme", f"Fichier illisible:\n{exc}")
                return
            for op in ops:
                self.program.add_operation(op)
            self._refresh_list()
            if ops:
                self.op_list.select_op(
                    self.program.operation_count - len(ops))
            self._flash_status(
                f"{nom}: {len(ops)} opération(s) ajoutée(s)"
                + (" — à modifier puis réenregistrer"
                   if action == 'edit' else ""))
            # Le choix est fait: on revient à la liste d'opérations, et
            # la barre NDS se referme pour le prochain passage
            self._add_panel.replier_nds()
            self._show_main_content()
            self.code_needs_update.emit()
            return

        if action == 'rename':
            neuf, ok = QInputDialog.getText(
                self, "Renommer le sous-programme",
                "Nouveau nom :", text=nom)
            if not ok or not neuf.strip() or neuf.strip() == nom:
                return
            try:
                os.rename(chemin,
                          os.path.join(dossier, f"{neuf.strip()}.nds"))
            except OSError as exc:
                QMessageBox.warning(self, "Renommer", str(exc))
                return
            self._add_panel.set_nds_names(self._nds_files())
            return

        if action == 'delete':
            rep = QMessageBox.question(
                self, "Supprimer le sous-programme",
                f"Supprimer définitivement « {nom}.nds » ?")
            if rep != QMessageBox.StandardButton.Yes:
                return
            try:
                os.remove(chemin)
            except OSError as exc:
                QMessageBox.warning(self, "Supprimer", str(exc))
                return
            self._add_panel.set_nds_names(self._nds_files())
            self._flash_status(f"{nom}.nds supprimé")

    def _get_programs_dir(self) -> str:
        """Retourne le répertoire des programmes."""
        from src.core.tool_library import get_base_dir
        base = get_base_dir()
        programs = os.path.join(base, "programs")
        os.makedirs(programs, exist_ok=True)
        return programs

    # ── Copier / coller d'opérations (entre onglets) ──

    #: marqueur du format de presse-papiers NeoDrive
    _CLIP_TAG = "NeoDriveOperations/1"

    def _on_copy_operations(self):
        """Copie les opérations sélectionnées dans le presse-papiers
        SYSTÈME (JSON): elles se collent dans un autre onglet, et même
        dans une autre instance de NeoDrive."""
        import json
        from PySide6.QtWidgets import QApplication
        rows = self.op_list.selected_rows()
        ops = [self.program.get_operation(r) for r in rows]
        ops = [o for o in ops if o is not None]
        if not ops:
            return
        payload = {'format': self._CLIP_TAG,
                   'operations': []}
        for op in ops:
            data = op.to_dict()
            # L'outil est repéré par son ARTICLE: un tool_id interne
            # n'aurait pas de sens dans une autre bibliothèque
            if op.tool_id and self.tool_library:
                tool = self.tool_library.get_tool(op.tool_id)
                if tool:
                    data['tool_article'] = tool.article_nr
            payload['operations'].append(data)
        QApplication.clipboard().setText(
            json.dumps(payload, ensure_ascii=False, indent=1))
        self._flash_status(
            f"{len(ops)} opération(s) copiée(s)")

    def _on_paste_operations(self):
        """Colle les opérations du presse-papiers après la sélection."""
        import json
        from PySide6.QtWidgets import QApplication
        raw = QApplication.clipboard().text() or ""
        try:
            payload = json.loads(raw)
        except ValueError:
            self._flash_status("Presse-papiers: pas d'opération NeoDrive")
            return
        if not isinstance(payload, dict) \
                or payload.get('format') != self._CLIP_TAG:
            self._flash_status("Presse-papiers: pas d'opération NeoDrive")
            return
        entries = payload.get('operations') or []
        if not entries:
            return
        rows = self.op_list.selected_rows()
        insert_at = (max(rows) + 1 if rows
                     else self.program.operation_count)
        added = 0
        for data in entries:
            try:
                OperationRegistry.get(data.get('operation_type', ''))
            except KeyError:
                continue        # type inconnu de cette version
            op = OperationInstance.from_dict(data)
            op.id = str(uuid.uuid4())[:8]      # nouvelle identité
            op.name = self._unique_copy_name(op.name)
            # Résoudre l'outil par article dans CETTE bibliothèque
            article = data.get('tool_article', '')
            op.tool_id = ""
            if article and self.tool_library:
                for tid, tool in self.tool_library.tools.items():
                    if tool.article_nr == article:
                        op.tool_id = tid
                        break
            if self._undo_stack:
                from src.core.undo_commands import AddOperationCommand
                self._undo_stack.push(AddOperationCommand(
                    self.program, op, insert_at + added))
            else:
                self.program.add_operation(op, insert_at + added)
            added += 1
        if added:
            self.op_list.select_op(insert_at + added - 1)
            missing = [o.name for o in self.program.operations
                       if not o.tool_id
                       and OperationRegistry.get(
                           o.operation_type).REQUIRES_TOOL]
            note = " — outil à re-sélectionner" if missing else ""
            self._flash_status(f"{added} opération(s) collée(s){note}")
        else:
            self._flash_status("Aucune opération collable")

    def _flash_status(self, text: str):
        win = self.window()
        label = getattr(win, '_status_label', None)
        if label is not None:
            label.setText(text)

    def _on_affichage_ops(self, opacite, division) -> None:
        """Clic droit: transparence ou « une ligne sur N » des
        opérations sélectionnées (Canva 2D et 3D)."""
        from src.core import affichage as af
        rows = self.op_list.selected_rows()
        for row in rows:
            op = self.program.get_operation(row)
            if op is not None:
                af.regler(op, opacite, division)
                self._update_list_item_text(row)
        if rows:
            # l'affichage seul: rien à reconstruire, rien à resimuler
            self.affichage_ops_modifie.emit()

    def _on_selection_enable(self, enable: bool):
        """Clic droit sur la sélection: active/désactive TOUTES les
        opérations sélectionnées (undo-able, une commande par opé)."""
        rows = self.op_list.selected_rows()
        changed = False
        for row in rows:
            op = self.program.get_operation(row)
            if not op or op.enabled == enable:
                continue
            old = self._op_undo_snapshot(op)
            op.enabled = enable
            if self._undo_stack is not None:
                from src.core.undo_commands import ModifyOperationCommand
                cmd = ModifyOperationCommand(
                    self.program, row, old, self._op_undo_snapshot(op),
                    skip_first_redo=True)
                cmd.setText(
                    ("Activer " if enable else "Désactiver ") + op.name)
                self._undo_stack.push(cmd)
            self.program.operation_updated.emit(row)
            changed = True
        if changed:
            self._maj_ciblee = True
            try:
                self.program._mark_modified()
            finally:
                self._maj_ciblee = False
            groupes = set()
            for row in rows:
                op = self.program.get_operation(row)
                if op is not None:
                    self._update_list_item_text(row)
                    groupes.add(getattr(op, 'group_id', ''))
            for gid in groupes:
                self._update_group_header(gid)
            self.code_needs_update.emit()

    def _on_toggle_operation(self, index: int):
        """Alt+clic: active/désactive une opération (undo-able)."""
        op = self.program.get_operation(index)
        if not op:
            return
        old = self._op_undo_snapshot(op)
        # Garde posée sur TOUT le geste: la commande d'annulation
        # comme le marquage « modifié » émettent des signaux qui
        # reconstruisaient la liste entière derrière nous
        self._maj_ciblee = True
        try:
            op.enabled = not op.enabled
            if self._undo_stack is not None:
                from src.core.undo_commands import (
                    ModifyOperationCommand)
                cmd = ModifyOperationCommand(
                    self.program, index, old,
                    self._op_undo_snapshot(op), skip_first_redo=True)
                cmd.setText(
                    ("Activer " if op.enabled else "Désactiver ")
                    + op.name)
                self._undo_stack.push(cmd)
            # L'émission déclenche _on_operation_updated_external qui
            # recharge le formulaire et le snapshot si nécessaire
            self.program.operation_updated.emit(index)
            self.program._mark_modified()
        finally:
            self._maj_ciblee = False
        # Une seule LIGNE change: la reconstruire toute entière
        # coûtait, sur un programme fourni, plus cher que le clic
        self._update_list_item_text(index)
        self._update_group_header(getattr(op, 'group_id', ''))
        self.code_needs_update.emit()

    def _update_group_header(self, group_id: str):
        """Réaccorde l'œil et l'interrupteur du titre d'un ensemble.

        Ils résument l'état de ses membres: si le dernier membre actif
        vient d'être éteint, le titre doit l'être aussi."""
        if not group_id:
            return
        for row in range(self.op_list.count()):
            if self.op_list.group_id_at(row) != group_id:
                continue
            item = self.op_list.item(row)
            membres = [o for o in self.program.operations
                       if getattr(o, 'group_id', '') == group_id]
            item.setData(_FavStarDelegate.EYE_ROLE,
                         any(op_preview(o) for o in membres))
            item.setData(_FavStarDelegate.POWER_ROLE,
                         any(o.enabled for o in membres))
            return

    def _on_operation_updated_external(self, index: int):
        """Réagit à une mise à jour d'opération venant d'AILLEURS que du
        formulaire (undo/redo, injections...): recharge le
        formulaire et le snapshot pour que l'UI reflète le modèle."""
        if self._emitting_form_update:
            return  # la modification vient du formulaire lui-même
        self._update_list_item_text(index)
        if index != self._current_index:
            return
        op = self.program.get_operation(index)
        if not op:
            return
        try:
            self.param_form.load_operation(op)
        except RuntimeError:
            pass  # Widget C++ déjà supprimé — ignoré
        self._undo_snapshot = self._op_undo_snapshot(op)

    def _on_rename_focus(self, index: int):
        """Double-clic dans la liste: sélectionne l'op et ouvre le
        renommage SUR SA LIGNE."""
        if index != self._current_index:
            self.op_list.select_op(index)
        op = self.program.get_operation(index)
        if op is not None:
            self.op_list.editer_nom(index, op.name)

    def renommer(self, index: int, nom: str) -> bool:
        """Le nouveau nom d'une opération (une annulation). Un nom
        choisi à la main l'emporte, durablement, sur les noms
        automatiques (décalage d'origine, texte gravé)."""
        from src.core.undo_commands import ModifyOperationCommand
        op = self.program.get_operation(index)
        nom = (nom or "").strip()
        if op is None or not nom or nom == op.name:
            return False
        avant = self._op_undo_snapshot(op)
        op.name = nom
        op.params['nom_fixe'] = True
        apres = self._op_undo_snapshot(op)
        if self._undo_stack is not None:
            self._undo_stack.push(ModifyOperationCommand(
                self.program, index, avant, apres, skip_first_redo=True))
        self.program._mark_modified()
        self._update_list_item_text(index)
        if self.param_form._current_op is op:
            lbl = getattr(self.param_form, '_name_label', None)
            if lbl is not None:
                try:
                    lbl.setText(op.name)
                except RuntimeError:
                    pass
            self._undo_snapshot = self._op_undo_snapshot(op)
        self.code_needs_update.emit()
        return True

    def _garder_defilement_liste(self):
        """La liste ne doit pas remonter en haut quand on change la
        sélection (Ctrl+clic sur plusieurs séquences issues de
        rectangles): on note la position et on la repose."""
        try:
            bar = self.op_list.verticalScrollBar()
            v = bar.value()
        except RuntimeError:
            return
        QTimer.singleShot(0, lambda: self._reposer_defilement(v))

    def _reposer_defilement(self, v: int):
        try:
            bar = self.op_list.verticalScrollBar()
            bar.setValue(min(v, bar.maximum()))
        except RuntimeError:
            pass

    def _on_operation_selected(self, index: int):
        self._garder_defilement_liste()
        self._current_index = index
        op = self.program.get_operation(index)
        if op:
            try:
                self.param_form.load_operation(op)
            except RuntimeError:
                pass  # Widget C++ déjà supprimé — ignoré
            self._surligner_rectangle_de(op)
            # La hauteur suit le formulaire chargé (différée: sa taille
            # n'est connue qu'une fois la mise en page faite)
            QTimer.singleShot(0, self.ajuster_hauteur_formulaire)
            self._undo_snapshot = self._op_undo_snapshot(op)
            self.active_operation_changed.emit(op)
        else:
            self._undo_snapshot = None
            self.active_operation_changed.emit(None)

    def _surligner_rectangle_de(self, op) -> None:
        """Une opération issue d'un rectangle (découpe, poche,
        surfaçage, ébavurage rectangle): son rectangle en
        surbrillance au canvas, ses cotes dans la barre d'état. Les
        autres effacent la surbrillance."""
        canvas = getattr(getattr(self.window(), 'dxf_panel', None),
                         'canvas', None)
        if canvas is None:
            return
        p = getattr(op, 'params', {}) or {}

        def _f(cle):
            try:
                return float(p.get(cle, 0.0) or 0.0)
            except (TypeError, ValueError):
                return 0.0
        w, h = _f('width_x'), _f('width_y')
        if w <= 0 or h <= 0:
            try:
                canvas.effacer_evidence()
            except Exception:
                pass
            return
        x = float(getattr(op, 'x', 0.0) or 0.0)
        y = float(getattr(op, 'y', 0.0) or 0.0)
        try:
            canvas.mettre_en_evidence(x, y, w, h)
        except Exception:
            return
        rayon = _f('corner_radius')
        cotes = f"{op.name}: centre X{x:g} Y{y:g} — {w:g} × {h:g} mm"
        if rayon > 0:
            cotes += f", rayon {rayon:g}"
        self._flash_status(cotes)

    def _on_order_changed(self):
        """Synchronise le réordonnancement drag-drop vers le modèle
        (undo-able) et met à jour l'appartenance aux ensembles."""
        old_ops = self.program.operations
        # Lignes visibles → index d'opération; un ensemble replié
        # garde ses membres masqués, ils suivent leur titre
        visible = []
        for row in range(self.op_list.count()):
            gid = self.op_list.group_id_at(row)
            idx = self.op_list.op_index_at(row)
            visible.append((gid, idx))

        self._apply_drop_groups(visible, old_ops)

        new_order = []
        for gid, idx in visible:
            if idx < 0:
                # Titre: ses membres masqués (ensemble replié) le
                # suivent, sinon ils apparaissent à leur propre ligne
                if gid in self._collapsed_groups:
                    new_order += [i for i, op in enumerate(old_ops)
                                  if getattr(op, 'group_id', '') == gid]
                continue
            new_order.append(idx)

        if len(new_order) == len(old_ops):
            old_ids = [op.id for op in old_ops]
            new_ids = [old_ops[i].id for i in new_order
                       if i < len(old_ops)]
            new_ids = self._contiguous_groups(new_ids, old_ops)
            # reorder_operations émet changed → _refresh_list
            self.program.reorder_operations(new_ids)
            if self._undo_stack is not None and old_ids != new_ids:
                from src.core.undo_commands import \
                    ReorderOperationsCommand
                self._undo_stack.push(ReorderOperationsCommand(
                    self.program, old_ids, new_ids,
                    skip_first_redo=True))
        else:
            self._refresh_list()
        self.code_needs_update.emit()

    #: paramètres qui suivent l'outil (specs partagées d'un ensemble)
    _TOOL_SPEC_KEYS = ('rpm_override', 'feed_override_finishing',
                       'feed_override_approach', 'feed_override_plunge',
                       'feed_override_ramp', 'feed_override_roughing')

    def _apply_group_tool(self, source, members=None):
        """Aligne l'outil et ses specs sur toutes les instances.

        Dans un ensemble, l'outil est COMMUN: changer d'outil sur une
        instance changerait sinon la moitié d'une série sans le dire."""
        gid = getattr(source, 'group_id', '')
        if not gid:
            return 0
        # Un ensemble libre (un filet et son avant-trou, une phase de
        # bridage) réunit des outils DIFFÉRENTS: rien à aligner
        if any(getattr(op, 'group_libre', False)
               for op in self.program.operations
               if getattr(op, 'group_id', '') == gid):
            return 0
        # Une gamme est un ensemble d'outils DIFFÉRENTS: rien à
        # aligner
        from src.operations.gamme_gravure import GammeGravure
        if GammeGravure.tete_de(gid, self.program.operations) is not None:
            return 0
        if members is None:
            members = [op for op in self.program.operations
                       if getattr(op, 'group_id', '') == gid]
        n = 0
        for op in members:
            if op is source:
                continue
            changed = (op.tool_id != source.tool_id)
            op.tool_id = source.tool_id
            for key in self._TOOL_SPEC_KEYS:
                if source.params.get(key, 0) != op.params.get(key, 0):
                    changed = True
                op.params[key] = source.params.get(key, 0)
            n += 1 if changed else 0
        return n

    @staticmethod
    def _contiguous_groups(order: list, ops: list) -> list:
        """Rassemble les membres d'un ensemble d'un seul tenant.

        Un membre lâché de l'autre côté de la liste couperait
        l'ensemble en deux, et il s'afficherait alors sous DEUX titres.
        Chaque ensemble est ramené à la place de son premier membre,
        les autres opérations gardant leur ordre."""
        group_of = {op.id: getattr(op, 'group_id', '') for op in ops}
        out, placed = [], set()
        for op_id in order:
            if op_id in placed:
                continue
            gid = group_of.get(op_id, '')
            if not gid:
                out.append(op_id)
                placed.add(op_id)
                continue
            for other in order:
                if group_of.get(other, '') == gid \
                        and other not in placed:
                    out.append(other)
                    placed.add(other)
        return out

    def _apply_drop_groups(self, visible: list, old_ops: list):
        """Appartenance d'une opération déplacée à la souris.

        Règle: une opération lâchée ENTRE deux membres d'un ensemble
        le rejoint; lâchée ailleurs, elle en sort. Poser après le
        dernier membre fait donc sortir de l'ensemble — sans quoi il
        n'y aurait aucun moyen de déposer une opération juste après un
        ensemble."""
        dragged = set(getattr(self.op_list, '_dragged_ops', []) or [])
        self.op_list._dragged_ops = []
        if not dragged:
            return
        rows = [(gid, idx) for gid, idx in visible]
        for pos, (gid, idx) in enumerate(rows):
            if idx < 0 or idx not in dragged or idx >= len(old_ops):
                continue
            op = old_ops[idx]
            before = self._row_group(rows, pos - 1, old_ops, -1)
            after = self._row_group(rows, pos + 1, old_ops, +1)
            if before and before == after:
                if op.group_id != before:
                    members = [o for o in old_ops
                               if getattr(o, 'group_id', '') == before]
                    from src.operations.gamme_gravure import GammeGravure
                    tete = GammeGravure.tete_de(before, old_ops)
                    if tete is not None:
                        # Une gamme accueille un parcours ou une
                        # pause: il prend son dessin et son champ
                        from src.operations import gamme_postes as gp
                        if op.operation_type not in gp.TYPES_A_OUTIL \
                                + ("dialogue_operateur",):
                            continue
                        op.group_id = before
                        op.group_name = tete.group_name
                        GammeGravure.propager(tete, [op])
                        continue
                    # Même type obligatoire: un ensemble est une suite
                    # de formulaires identiques
                    if members and members[0].operation_type != \
                            op.operation_type:
                        continue
                    op.group_id = before
                    op.group_name = members[0].group_name if members \
                        else ""
                    # L'outil de l'ensemble s'applique à l'arrivant
                    if members:
                        self._apply_group_tool(members[0], [op])
            elif op.group_id:
                op.group_id = ""
                op.group_name = ""

    @staticmethod
    def _row_group(rows: list, pos: int, old_ops: list,
                   step: int) -> str:
        """Ensemble de la ligne voisine (titre inclus)."""
        if pos < 0 or pos >= len(rows):
            return ""
        gid, idx = rows[pos]
        if idx < 0:
            # Un TITRE au-dessus ouvre son ensemble; en dessous, il
            # marque la fin du précédent
            return gid if step < 0 else ""
        if 0 <= idx < len(old_ops):
            return getattr(old_ops[idx], 'group_id', '')
        return ""

    def _on_params_changed(self, params: Dict[str, Any]):
        if self._current_index < 0:
            return
        op = self.program.get_operation(self._current_index)
        if not op:
            return

        # Traiter les méta-paramètres
        if '_tool_id' in params:
            op.tool_id = params.pop('_tool_id')
        if '_name' in params:
            new_name = params.pop('_name')
            if new_name and new_name != op.name:
                op.name = new_name
                # Gravure: un nom choisi à la main l'emporte
                # définitivement sur le texte gravé
                if op.operation_type == "gravure_texte":
                    op.params['_name_locked'] = True
                self._update_list_item_text(self._current_index)

        # Coordonnées
        if not self.param_form._is_multi_point:
            coord_w = self.param_form._coord_widgets
            if 'x' in coord_w:
                w = coord_w['x']
                if hasattr(w, 'value'):
                    op.x = w.value()
            if 'y' in coord_w:
                w = coord_w['y']
                if hasattr(w, 'value'):
                    op.y = w.value()
        else:
            # Multi-point: x/y du premier point si disponible
            if op.points:
                op.x = op.points[0].get('x', 0.0)
                op.y = op.points[0].get('y', 0.0)
        # Z is always 15
        op.z = 15.0

        # Paramètres métier
        op.params.update(params)

        # Tête de gamme: le dessin et le champ vont à tous les postes
        if op.operation_type == "gamme_gravure":
            from src.operations.gamme_gravure import GammeGravure
            membres = GammeGravure.membres(op, self.program.operations)
            if GammeGravure.propager(op, membres):
                for membre in membres:
                    try:
                        self.program.operation_updated.emit(
                            self.program.operations.index(membre))
                    except ValueError:
                        pass
        # Ensemble d'instances: l'outil et ses specs sont COMMUNS
        elif getattr(op, 'group_id', ''):
            self._apply_group_tool(op)

        # Import prog: choisir un fichier l'IMPORTE, comme depuis
        # l'onglet Batch édition. Différé: on ne détruit pas le
        # formulaire pendant qu'il émet ses valeurs. « Appel prog
        # externe », lui, laisse le fichier dehors.
        if op.operation_type == "import_programme" \
                and str(op.params.get('filepath', '') or '').strip():
            from PySide6.QtCore import QTimer
            QTimer.singleShot(
                0, lambda i=self._current_index:
                self._convert_external_call(i))

        # Gravure: le nom de l'opération EST le texte gravé — on
        # retrouve ce qui sera écrit sans ouvrir le formulaire.
        # Un renommage explicite ('_name') l'emporte.
        if op.operation_type == "gravure_texte" \
                and not op.params.get('_name_locked') \
                and not op.params.get('nom_fixe'):
            engraved = str(op.params.get('text', '') or '').strip()
            if engraved:
                new_name = engraved[:30]
                if new_name != op.name:
                    op.name = new_name
                    name_lbl = getattr(self.param_form,
                                       '_name_label', None)
                    if name_lbl is not None:
                        try:
                            name_lbl.setText(op.name)
                        except RuntimeError:
                            pass

        # Titre dynamique pour décalage origine
        if op.operation_type == "decalage_origine" \
                and '_name' not in params and not op.params.get('nom_fixe'):
            from src.operations.decalage_origine import DecalageOrigine
            op.name = DecalageOrigine.build_dynamic_name(op.params)
            # Mettre à jour le label nom dans le formulaire
            name_lbl = getattr(self.param_form, '_name_label', None)
            if name_lbl is not None:
                try:
                    name_lbl.setText(op.name)
                except RuntimeError:
                    pass

        # Undo: pousser une commande couvrant cette édition (l'état 'new'
        # est déjà appliqué → skip_first_redo). Le snapshot est pris à la
        # sélection de l'op et rafraîchi après chaque édition, il couvre
        # donc aussi les modifications de points faites par le formulaire.
        new_snapshot = self._op_undo_snapshot(op)
        if (self._undo_stack is not None
                and self._undo_snapshot is not None
                and self._undo_snapshot.get('id') == op.id
                and self._undo_snapshot != new_snapshot):
            from src.core.undo_commands import ModifyOperationCommand
            self._undo_stack.push(ModifyOperationCommand(
                self.program, self._current_index,
                self._undo_snapshot, new_snapshot,
                skip_first_redo=True))
        self._undo_snapshot = new_snapshot

        # Garde de réentrance: éviter que _on_operation_updated_external
        # recharge le formulaire pendant la saisie (perte de focus)
        self._emitting_form_update = True
        try:
            self.program.operation_updated.emit(self._current_index)
        finally:
            self._emitting_form_update = False
        # Don't refresh list on every param change (avoids focus loss):
        # « modifié » émet `changed`, que la liste écoute — et la
        # reconstruire re-sélectionnait la ligne, ce qui RECHARGEAIT
        # le formulaire à chaque frappe. Un texte sur plusieurs
        # lignes perdait le clavier à la première lettre.
        self._maj_ciblee = True
        try:
            self.program._mark_modified()
        finally:
            self._maj_ciblee = False
        self._update_list_item_text(self._current_index)
        self.code_needs_update.emit()

    def _update_list_item_text(self, index: int):
        """Met à jour le texte d'un seul item sans reconstruire toute la liste."""
        op = self.program.get_operation(index)
        if not op:
            return
        # La LIGNE n'est pas l'index: les titres d'ensemble décalent
        row = self.op_list.row_of_op(index)
        if row < 0:
            return          # membre d'un ensemble replié
        display = f"{index+1}. {op.name}{self._estimate_suffix(op)}"
        if not op.enabled:
            display = f"[OFF] {display}"
        if getattr(op, 'group_id', ''):
            display = "    " + display
        item = self.op_list.item(row)
        if item:
            item.setText(display)
            is_fav = op.name in self._favorite_names()
            item.setData(_FavStarDelegate.FAV_ROLE, is_fav)
            item.setData(_FavStarDelegate.OFF_ROLE, not op.enabled)
            item.setData(
                _FavStarDelegate.BROWSE_ROLE,
                op.operation_type in ("appel_programme",
                                      "import_programme"))
            item.setData(_FavStarDelegate.EYE_ROLE, self._oeil_de(op))
            item.setData(_FavStarDelegate.ANNOT_ROLE, self._annot_de(op))
            item.setData(_FavStarDelegate.POWER_ROLE, bool(op.enabled))
            item.setData(_FavStarDelegate.TRASH_ROLE, True)
            item.setData(_FavStarDelegate.STAR_ROLE, True)
            item.setData(
                _FavStarDelegate.DXF_ROLE,
                op.operation_type in ("gravure_2d5", "evidement_2d5",
                                      "contour_2d5", "gamme_gravure",
                                      "trace"))
            # Couleur cohérente avec _refresh_list (état enabled)
            if not op.enabled:
                item.setForeground(QColor(COLORS['text_muted']))
            else:
                try:
                    op_class = OperationRegistry.get(op.operation_type)
                    color = self._CATEGORY_COLORS.get(
                        op_class.CATEGORY, "#cdd6f4")
                except KeyError:
                    color = "#585b70"
                item.setForeground(QColor(color))

    @staticmethod
    def _cle_outil(op) -> tuple:
        """Ce qui rend deux opérations enchaînables sans reprise.

        L'outil ne suffit pas: deux taraudages M4, l'un ébavuré et
        l'autre non, partagent le taraud mais PAS la suite du travail
        — les rassembler mettrait un ébavurage sur des trous qui n'en
        demandaient pas. L'ébavurage compte donc dans la clé, avec son
        propre outil."""
        params = getattr(op, 'params', {}) or {}
        ebav = ''
        if params.get('use_ebav') and params.get('ebav_tool_id'):
            ebav = str(params.get('ebav_tool_id'))
        return (op.tool_id or '', ebav)

    def _ordre_par_outil(self, ops: list) -> list:
        """Nouvel ordre des index: un passage par outil.

        Deux règles que la version précédente ignorait:
        - un ENSEMBLE ne se disloque pas (ses membres restent
          contigus, à la place du premier d'entre eux);
        - à l'INTÉRIEUR d'un ensemble, les opérations se rassemblent
          quand même par outil et ébavurage — c'est là que les
          taraudages identiques se retrouvent.
        """
        from collections import OrderedDict

        blocs = OrderedDict()
        for i, op in enumerate(ops):
            gid = getattr(op, 'group_id', '')
            cle = ('ensemble', gid) if gid else (
                'outil', self._cle_outil(op) if op.tool_id
                else ('__sans_outil__', i))
            blocs.setdefault(cle, []).append(i)

        ordre = []
        for cle, indices in blocs.items():
            if cle[0] == 'ensemble' and len(indices) > 1:
                # Tri STABLE par outil: l'ordre d'apparition des
                # outils dans l'ensemble est conservé
                vus = []
                for i in indices:
                    k = self._cle_outil(ops[i])
                    if k not in vus:
                        vus.append(k)
                indices = sorted(
                    indices, key=lambda i: vus.index(self._cle_outil(ops[i])))
            ordre.extend(indices)
        return ordre

    def _on_optimize_tool_order(self):
        """Réorganise les opérations pour minimiser les changements d'outils."""
        ops = self.program.operations
        if len(ops) < 2:
            QMessageBox.information(
                self, "Optimisation",
                "Pas assez d'opérations à réorganiser.")
            return

        new_order = self._ordre_par_outil(ops)

        # Vérifier s'il y a un changement
        current_order = list(range(len(ops)))
        if new_order == current_order:
            QMessageBox.information(
                self, "Optimisation",
                "L'ordre actuel est déjà optimal.\n"
                "Aucun changement d'outil en trop.")
            return

        # Compter les tool changes avant/après
        def _count_changes(order):
            changes = 0
            prev_tid = None
            for idx in order:
                tid = ops[idx].tool_id or ''
                if prev_tid is not None and tid != prev_tid and tid:
                    changes += 1
                prev_tid = tid
            return changes

        before = _count_changes(current_order)
        after = _count_changes(new_order)

        # Construire le résumé
        summary_lines = []
        for i, idx in enumerate(new_order):
            op = ops[idx]
            moved = " ←" if idx != i else ""
            summary_lines.append(
                f"{i+1}. {op.name} (outil: {op.tool_id or '—'}){moved}")
        summary = "\n".join(summary_lines[:20])
        if len(summary_lines) > 20:
            summary += f"\n... ({len(summary_lines)} opérations au total)"

        reply = QMessageBox.question(
            self, "Optimisation des outils",
            f"Changements d'outils: {before} → {after}\n\n"
            f"Nouvel ordre proposé:\n{summary}\n\n"
            f"Appliquer cette réorganisation?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Appliquer le nouvel ordre
        new_ops = [ops[idx] for idx in new_order]
        self.program.operations[:] = new_ops
        self.program._mark_modified()
        self._refresh_list()
        self.code_needs_update.emit()
        # Vérifier si miroir X/Y implique un changement de direction taraudage
        self._check_mirror_thread_direction()

    #: la réponse à « miroir: retourner / remettre les taraudages ? » —
    #: None: on demande; True / False (tests)
    reponse_miroir = None

    def _check_mirror_thread_direction(self):
        """(ancien nom) La question du sens des filets sous miroir,
        posée tout de suite."""
        return self.verifier_miroirs(force=True)

    def verifier_miroirs(self, force: bool = False) -> int:
        """Un miroir sur un seul axe retourne l'hélice: les taraudages
        qu'il couvre (jusqu'à « Rétablir Miroir ») passent en
        LeftHandThread; ceux que NeoDrive a retournés et qu'aucun miroir
        ne couvre plus sont REMIS en RightHandThread. On le propose une
        fois par situation (une question refusée n'est pas reposée).
        Rend le nombre d'opérations changées."""
        from src.core import miroirs_filets as mf
        from PySide6.QtWidgets import QApplication
        if not force and (not self.isVisible()
                          or QApplication.activeModalWidget() is not None):
            return 0                # pas de question par-dessus une autre
        ops = self.program.operations
        b = mf.bilan(ops)
        if not b['a_inverser'] and not b['a_remettre']:
            self._miroir_vu = None
            return 0
        sig = mf.signature(b)
        if sig == getattr(self, '_miroir_vu', None) and not force:
            return 0
        self._miroir_vu = sig
        lignes = []
        if b['a_inverser']:
            lignes.append(
                "Un miroir sur un seul axe retourne le sens des filets.\n"
                "Passer en LeftHandThread (le filet reste à droite) :\n  "
                + "\n  ".join(o.name for o in b['a_inverser'][:8]))
        if b['a_remettre']:
            lignes.append(
                "Ces taraudages, retournés pour un miroir, n'en ont plus.\n"
                "Les remettre en RightHandThread :\n  "
                + "\n  ".join(o.name for o in b['a_remettre'][:8]))
        reponse = self.reponse_miroir
        if reponse is None:
            reponse = QMessageBox.question(
                self, "Miroir et sens des filets", "\n\n".join(lignes),
                QMessageBox.StandardButton.Yes |
                QMessageBox.StandardButton.No
            ) == QMessageBox.StandardButton.Yes
        if not reponse:
            return 0
        touches = b['a_inverser'] + b['a_remettre']
        n = mf.appliquer(b)
        self._miroir_vu = None
        self.program._mark_modified()
        self._refresh_list()
        self.code_needs_update.emit()
        # le formulaire de l'opé courante, si elle a changé de sens
        if (self._current_index >= 0
                and self.program.get_operation(self._current_index)
                in touches):
            self.param_form.load_operation(
                self.program.get_operation(self._current_index))
        return n

    def _on_create_return_shift_op(self, inverse_params: dict):
        """Crée une opération Décalage Origine avec les valeurs inversées."""
        sx = inverse_params.get('shift_x', 0.0)
        sy = inverse_params.get('shift_y', 0.0)
        sz = inverse_params.get('shift_z', 0.0)
        # Nom descriptif
        parts = []
        if sx != 0.0:
            parts.append(f"X={sx}")
        if sy != 0.0:
            parts.append(f"Y={sy}")
        if sz != 0.0:
            parts.append(f"Z={sz}")
        label = f"Retour {' '.join(parts)}" if parts else "Retour Origine"
        # Créer l'OperationInstance correctement
        new_op = OperationInstance("decalage_origine", label)
        new_op.params = self._default_params.get_defaults("decalage_origine")
        new_op.params['shift_x'] = sx
        new_op.params['shift_y'] = sy
        new_op.params['shift_z'] = sz
        if self._undo_stack:
            from src.core.undo_commands import AddOperationCommand
            self._undo_stack.push(AddOperationCommand(self.program, new_op))
        else:
            self.program.add_operation(new_op)
        self._refresh_list()
        idx = self.program.operation_count - 1
        self.op_list.select_op(idx)
        self.code_needs_update.emit()

    def inject_coordinates(self, x: float, y: float):
        """Injecte des coordonnées depuis l'éditeur DXF."""
        self.param_form.set_coordinates(x, y)

    def inject_points(self, points: list):
        """Injecte une liste de points depuis la sélection DXF."""
        self.param_form.inject_points(points)
