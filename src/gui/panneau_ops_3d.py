"""Le panneau « Opés » du Canva 3D: la transparence, « une ligne sur N » et
l'œil de chaque opération, importées comprises — une par une ou en lot.

Une ligne par opération, légère: pas de curseur par ligne (cent vingt
opérations coûtaient cent vingt curseurs et autant de listes déroulantes),
une barre qu'on tire. La sélection se fait comme partout (clic, Ctrl, Maj);
un geste sur une ligne sélectionnée vaut pour toute la sélection, et les
réglages du haut valent pour la sélection, ou pour toutes les opérations
montrées s'il n'y en a pas.
"""
from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel, QRect, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMenu,
                               QPushButton, QSlider, QStyle,
                               QStyledItemDelegate, QTableWidget,
                               QTableWidgetItem, QToolButton, QVBoxLayout,
                               QWidget)

from src.core import affichage as af

COL_OEIL, COL_NOM, COL_OPACITE, COL_DIVISION = range(4)
#: les opérations sans parcours à elles: rien à régler
TYPES_SANS_TRACE = ('decalage_origine', 'rotation_repere', 'repere_local')
ROLE_OPACITE = Qt.ItemDataRole.UserRole
ROLE_COULEUR = Qt.ItemDataRole.UserRole + 1
COULEUR_DEFAUT = "#89b4fa"
HAUTEUR_LIGNE = 22


def _visible(op) -> bool:
    from src.gui.panels.operations_panel import op_preview
    return bool(op_preview(op))


class _BarreOpacite(QStyledItemDelegate):
    """L'opacité d'une ligne: une barre à la couleur de l'outil."""

    def paint(self, p, option, index) -> None:
        if option.state & QStyle.StateFlag.State_Selected:
            p.fillRect(option.rect, option.palette.highlight())
        r = option.rect.adjusted(3, 4, -3, -4)
        valeur = int(index.data(ROLE_OPACITE) or 0)
        couleur = QColor(index.data(ROLE_COULEUR) or COULEUR_DEFAUT)
        p.save()
        fond = QColor(option.palette.base().color())
        fond.setAlphaF(0.7)
        p.fillRect(r, fond)
        pleine = QRect(r)
        pleine.setWidth(max(1, int(r.width() * valeur / 100.0)))
        couleur.setAlphaF(0.55)
        p.fillRect(pleine, couleur)
        p.setPen(option.palette.text().color())
        police = QFont(option.font)
        police.setPointSizeF(max(6.0, police.pointSizeF() - 1.0))
        p.setFont(police)
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, f"{valeur} %")
        p.restore()


class _TableOps(QTableWidget):
    """La liste: tirer la barre, cliquer l'œil ou la division n'y change
    pas la sélection (c'est sur elle qu'ils agissent)."""

    def __init__(self, panneau):
        super().__init__(0, 4, panneau)
        self._panneau = panneau
        self._tiree = None

    def _valeur_de(self, x: float, rangee: int) -> int:
        r = self.visualRect(self.model().index(rangee, COL_OPACITE))
        r = r.adjusted(3, 0, -3, 0)
        v = (x - r.left()) / max(1.0, float(r.width()))
        return max(5, min(100, int(round(v * 100.0))))

    def mousePressEvent(self, ev) -> None:
        index = self.indexAt(ev.position().toPoint())
        if ev.button() == Qt.MouseButton.LeftButton and index.isValid() \
                and not ev.modifiers() & (
                    Qt.KeyboardModifier.ControlModifier
                    | Qt.KeyboardModifier.ShiftModifier):
            rangee, col = index.row(), index.column()
            if col == COL_OPACITE:
                self._tiree = rangee
                self._panneau.tirer_barre(
                    rangee, self._valeur_de(ev.position().x(), rangee))
                ev.accept()
                return
            if col == COL_OEIL:
                self._panneau.basculer_oeil(rangee)
                ev.accept()
                return
            if col == COL_DIVISION:
                self._panneau.division_suivante(rangee)
                ev.accept()
                return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev) -> None:
        if self._tiree is not None:
            self._panneau.tirer_barre(
                self._tiree, self._valeur_de(ev.position().x(), self._tiree))
            ev.accept()
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev) -> None:
        if self._tiree is not None:
            self._tiree = None
            self._panneau.barre_lachee()
            ev.accept()
            return
        super().mouseReleaseEvent(ev)


class PanneauAffichageOps(QWidget):
    """Les opérations du programme, chacune avec sa transparence (de 5 à
    100 %), « une ligne sur N » (src.core.affichage) et son œil."""

    #: un réglage bouge (une barre qu'on tire): la vue suit tout de suite
    apercu = Signal()
    #: un réglage est posé: le reste du programme suit (dessin 2D, liste)
    change = Signal()
    #: l'œil d'opérations a été basculé ici (la première)
    oeil_change = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        # dans l'onglet « Opés » du panneau 3D: sa largeur est la sienne
        self.setMinimumWidth(0)
        #: les opérations du dernier réglage (la liste met leur texte à jour)
        self.ops_touchees: list = []
        #: (op) -> la couleur de son outil (posé par le Canva)
        self.couleur_de_op = None
        #: (op) -> le nom de son outil (posé par le Canva)
        self.nom_outil_de_op = None
        self._ops: list = []
        self._lire_lot = False
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(3)
        titre = QLabel("Affichage des opés")
        titre.setStyleSheet("font-weight: bold;")
        aide = QLabel("Tirer la barre, cliquer l'œil ou 1/N. Sur une ligne "
                      "sélectionnée (Ctrl, Maj): toute la sélection.")
        aide.setWordWrap(True)
        aide.setStyleSheet("color: #a6adc8; font-size: 10px;")
        v.addWidget(titre)
        v.addWidget(aide)
        v.addLayout(self._neuve_barre_choix())
        self.filtre = QLineEdit()
        self.filtre.setPlaceholderText("Filtrer par nom…")
        self.filtre.setClearButtonEnabled(True)
        self.filtre.textChanged.connect(self._filtrer)
        v.addWidget(self.filtre)
        v.addLayout(self._neuve_ligne_lot())
        self.table = self._neuve_table()
        v.addWidget(self.table, 1)
        tout = QPushButton("Tout opaque, tout tracé")
        tout.setToolTip("Remettre toutes les opérations à 100 % et 1/1")
        tout.clicked.connect(self.remettre)
        v.addWidget(tout)
        self._maj_lot()

    # ── la construction ──

    def _neuve_barre_choix(self):
        from src.gui.barre_outils import FluxLayout
        rangee = FluxLayout()
        for texte, aide, action in (
                ("Toutes", "Sélectionner toutes les opérations montrées",
                 self.tout_selectionner),
                ("Aucune", "Ne rien sélectionner", self.rien_selectionner),
                ("Inverser", "Inverser la sélection", self.inverser_selection),
                ("Importées", "Sélectionner les opérations venues d'un "
                 "programme importé (blocs, lignes du Main, appels)",
                 self.selectionner_importees)):
            b = QToolButton()
            b.setText(texte)
            b.setToolTip(aide)
            b.clicked.connect(lambda _on=False, f=action: f())
            rangee.addWidget(b)
        self.par_outil = QToolButton()
        self.par_outil.setText("Outil ▾")
        self.par_outil.setToolTip("Sélectionner les opérations d'un outil")
        self.par_outil.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.par_outil.setMenu(QMenu(self.par_outil))
        self.par_outil.menu().aboutToShow.connect(self._remplir_menu_outils)
        rangee.addWidget(self.par_outil)
        return rangee

    def _neuve_ligne_lot(self):
        boite = QVBoxLayout()
        boite.setSpacing(2)
        self.titre_lot = QLabel()
        self.titre_lot.setStyleSheet("font-size: 10px;")
        boite.addWidget(self.titre_lot)
        ligne = QHBoxLayout()
        ligne.setSpacing(3)
        self.oeil_lot = QToolButton()
        self.oeil_lot.setAutoRaise(True)
        self.oeil_lot.setToolTip("Montrer ou masquer ces opérations")
        self.oeil_lot.clicked.connect(self._sur_oeil_lot)
        self.curseur_lot = QSlider(Qt.Orientation.Horizontal)
        self.curseur_lot.setRange(5, 100)
        self.curseur_lot.setToolTip("Opacité de ces opérations (%)")
        self.curseur_lot.valueChanged.connect(self._sur_curseur_lot)
        self.curseur_lot.sliderReleased.connect(self.barre_lachee)
        self.pourcent_lot = QLabel("100 %")
        self.pourcent_lot.setMinimumWidth(34)
        self.division_lot = QComboBox()
        for n in af.DIVISIONS:
            self.division_lot.addItem(f"1/{n}", n)
        self.division_lot.setToolTip("Une ligne sur N, pour ces opérations")
        self.division_lot.currentIndexChanged.connect(self._sur_division_lot)
        for w in (self.oeil_lot, self.curseur_lot, self.pourcent_lot,
                  self.division_lot):
            ligne.addWidget(w)
        ligne.setStretch(1, 1)
        boite.addLayout(ligne)
        return boite

    def _neuve_table(self):
        t = _TableOps(self)
        t.setHorizontalHeaderLabels(["", "Opération", "Opacité", "1/N"])
        t.verticalHeader().hide()
        t.verticalHeader().setDefaultSectionSize(HAUTEUR_LIGNE)
        t.setShowGrid(False)
        t.setAlternatingRowColors(True)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setItemDelegateForColumn(COL_OPACITE, _BarreOpacite(t))
        entete = t.horizontalHeader()
        entete.setMinimumSectionSize(20)
        entete.setSectionResizeMode(COL_OEIL, QHeaderView.ResizeMode.Fixed)
        entete.setSectionResizeMode(COL_NOM, QHeaderView.ResizeMode.Stretch)
        entete.setSectionResizeMode(COL_OPACITE, QHeaderView.ResizeMode.Fixed)
        entete.setSectionResizeMode(COL_DIVISION, QHeaderView.ResizeMode.Fixed)
        t.setColumnWidth(COL_OEIL, 24)
        t.setColumnWidth(COL_OPACITE, 76)
        t.setColumnWidth(COL_DIVISION, 34)
        t.itemSelectionChanged.connect(self._maj_lot)
        t.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        t.customContextMenuRequested.connect(self._menu_contextuel)
        return t

    def _icone_oeil(self, visible: bool):
        from src.gui.icons import get_icon
        return get_icon("eye", 15, "#89b4fa" if visible else "#6c7086")

    # ── la liste ──

    def set_operations(self, ops) -> None:
        """Les lignes des opérations (refaites seulement si la liste a
        changé: une barre qu'on tire n'est pas détruite)."""
        ops = [op for op in (ops or [])
               if getattr(op, 'operation_type', '') not in TYPES_SANS_TRACE]
        if [id(o) for o in ops] == [id(o) for o in self._ops]:
            self._relire()
            return
        choisies = {id(o) for o in self.selection()}
        self._ops = ops
        t = self.table
        t.setUpdatesEnabled(False)
        avant = t.blockSignals(True)
        t.clearContents()
        t.setRowCount(len(ops))
        for rangee, op in enumerate(ops):
            oeil = QTableWidgetItem()
            nom = QTableWidgetItem(str(getattr(op, 'name', '') or '?'))
            barre = QTableWidgetItem()
            division = QTableWidgetItem()
            division.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if self._est_importee(op):
                police = nom.font()
                police.setItalic(True)
                nom.setFont(police)
                nom.setToolTip(f"{nom.text()} (importée)")
            else:
                nom.setToolTip(nom.text())
            oeil.setToolTip("Montrer ou masquer l'opération (son œil de "
                            "la liste d'opés)")
            barre.setToolTip("Tirer: opacité de l'opération")
            division.setToolTip("Cliquer: une ligne sur 1, 2, 3, 5, 10")
            for col, item in ((COL_OEIL, oeil), (COL_NOM, nom),
                              (COL_OPACITE, barre), (COL_DIVISION, division)):
                t.setItem(rangee, col, item)
        t.blockSignals(avant)
        t.setUpdatesEnabled(True)
        self.selectionner([o for o in ops if id(o) in choisies])
        self._filtrer(self.filtre.text())
        self._relire()

    @staticmethod
    def _est_importee(op) -> bool:
        return getattr(op, 'operation_type', '') in af.TYPES_IMPORTES

    def _relire(self) -> None:
        """Les lignes reprennent les réglages des opérations."""
        for rangee, op in enumerate(self._ops):
            self._relire_ligne(rangee, op)
            barre = self.table.item(rangee, COL_OPACITE)
            couleur = self.couleur_de_op(op) if self.couleur_de_op else None
            barre.setData(ROLE_COULEUR, couleur or COULEUR_DEFAUT)
        self.table.viewport().update()
        self._maj_lot()

    def _relire_ligne(self, rangee: int, op) -> None:
        t = self.table
        visible = _visible(op)
        oeil = t.item(rangee, COL_OEIL)
        if oeil.data(Qt.ItemDataRole.UserRole) is not visible:
            oeil.setData(Qt.ItemDataRole.UserRole, visible)
            oeil.setIcon(self._icone_oeil(visible))
        barre = t.item(rangee, COL_OPACITE)
        barre.setData(ROLE_OPACITE, int(round(af.opacite(op) * 100)))
        n = af.division(op)
        t.item(rangee, COL_DIVISION).setText(f"1/{n}")

    # ── la sélection ──

    def selection(self) -> list:
        """Les opérations sélectionnées, dans l'ordre de la liste."""
        rangees = sorted({i.row() for i in
                          self.table.selectionModel().selectedRows()})
        return [self._ops[r] for r in rangees if r < len(self._ops)]

    def _montrees(self) -> list:
        return [op for r, op in enumerate(self._ops)
                if not self.table.isRowHidden(r)]

    def cibles(self) -> list:
        """Ce sur quoi les réglages du haut agissent: la sélection, sinon
        toutes les opérations montrées."""
        return self.selection() or self._montrees()

    def selectionner(self, ops) -> None:
        """Sélectionne ces opérations (celles que le panneau connaît)."""
        ids = {id(o) for o in ops or []}
        t = self.table
        modele = t.selectionModel()
        avant = t.blockSignals(True)
        modele.clearSelection()
        for r, op in enumerate(self._ops):
            if id(op) in ids:
                modele.select(
                    t.model().index(r, 0),
                    QItemSelectionModel.SelectionFlag.Select
                    | QItemSelectionModel.SelectionFlag.Rows)
        t.blockSignals(avant)
        t.viewport().update()
        self._maj_lot()

    def tout_selectionner(self) -> None:
        self.selectionner(self._montrees())

    def rien_selectionner(self) -> None:
        self.selectionner([])

    def inverser_selection(self) -> None:
        choisies = {id(o) for o in self.selection()}
        self.selectionner([o for o in self._montrees()
                           if id(o) not in choisies])

    def selectionner_importees(self) -> None:
        self.selectionner([o for o in self._montrees()
                           if self._est_importee(o)])

    def _remplir_menu_outils(self) -> None:
        menu = self.par_outil.menu()
        menu.clear()
        par_nom = {}
        for op in self._montrees():
            nom = (self.nom_outil_de_op(op) if self.nom_outil_de_op
                   else str(getattr(op, 'tool_id', '') or '')) or "Sans outil"
            par_nom.setdefault(nom, []).append(op)
        for nom in sorted(par_nom):
            action = QAction(f"{nom} ({len(par_nom[nom])})", menu)
            action.triggered.connect(
                lambda _on=False, l=par_nom[nom]: self.selectionner(l))
            menu.addAction(action)

    def _filtrer(self, texte: str) -> None:
        texte = (texte or "").strip().lower()
        for r, op in enumerate(self._ops):
            nom = str(getattr(op, 'name', '') or '').lower()
            self.table.setRowHidden(r, bool(texte) and texte not in nom)
        self._maj_lot()

    # ── les réglages ──

    def _pour_rangee(self, rangee: int) -> list:
        """Sur une ligne sélectionnée: toute la sélection. Sinon elle."""
        if not 0 <= rangee < len(self._ops):
            return []
        op = self._ops[rangee]
        choisies = self.selection()
        return choisies if any(o is op for o in choisies) else [op]

    def regler_opacite(self, ops, pourcent: int, fini: bool = True) -> None:
        for op in ops:
            af.regler(op, opacite_=pourcent / 100.0)
        self._apres_reglage(ops, fini)

    def regler_division(self, ops, n: int) -> None:
        for op in ops:
            af.regler(op, division_=n)
        self._apres_reglage(ops, True)

    def regler_oeil(self, ops, visible: bool) -> None:
        ops = [op for op in ops if getattr(op, 'params', None) is not None]
        for op in ops:
            op.params['preview'] = bool(visible)
        self._relire()
        if ops:
            # un seul signal: le programme ne se relit qu'une fois
            self.oeil_change.emit(ops[0])

    def _apres_reglage(self, ops, fini: bool) -> None:
        self.ops_touchees = list(ops)
        touchees = {id(o) for o in ops}
        for rangee, op in enumerate(self._ops):
            if id(op) in touchees:
                self._relire_ligne(rangee, op)
        self.table.viewport().update()
        self._maj_lot()
        self.apercu.emit()
        if fini:
            self.change.emit()

    def tirer_barre(self, rangee: int, pourcent: int) -> None:
        self.regler_opacite(self._pour_rangee(rangee), pourcent, fini=False)

    def barre_lachee(self) -> None:
        self.change.emit()

    def basculer_oeil(self, rangee: int) -> None:
        ops = self._pour_rangee(rangee)
        if ops:
            self.regler_oeil(ops, not _visible(self._ops[rangee]))

    def division_suivante(self, rangee: int) -> None:
        ops = self._pour_rangee(rangee)
        if ops:
            i = af.DIVISIONS.index(af.division(self._ops[rangee]))
            self.regler_division(ops, af.DIVISIONS[(i + 1)
                                                   % len(af.DIVISIONS)])

    def remettre(self) -> None:
        for op in self._ops:
            af.regler(op, 1.0, 1)
        self._apres_reglage(list(self._ops), True)

    # ── les réglages du haut ──

    def _maj_lot(self) -> None:
        """Le haut montre les cibles (la première, si elles diffèrent)."""
        cibles = self.cibles()
        choisies = len(self.selection())
        if choisies:
            self.titre_lot.setText(
                f"Réglage de la sélection ({choisies} opé"
                f"{'s' if choisies > 1 else ''}):")
        else:
            self.titre_lot.setText(f"Réglage de toutes les opés montrées "
                                   f"({len(cibles)}):")
        self._lire_lot = True
        try:
            premiere = cibles[0] if cibles else None
            pc = int(round(af.opacite(premiere) * 100)) if premiere else 100
            if not self.curseur_lot.isSliderDown():
                self.curseur_lot.setValue(pc)
            self.pourcent_lot.setText(f"{self.curseur_lot.value()} %")
            n = af.division(premiere) if premiere else 1
            self.division_lot.setCurrentIndex(
                max(0, self.division_lot.findData(n)))
            self.oeil_lot.setIcon(self._icone_oeil(
                _visible(premiere) if premiere else True))
        finally:
            self._lire_lot = False

    def _sur_curseur_lot(self, valeur: int) -> None:
        self.pourcent_lot.setText(f"{valeur} %")
        if self._lire_lot:
            return
        self.regler_opacite(self.cibles(), valeur,
                            fini=not self.curseur_lot.isSliderDown())

    def _sur_division_lot(self, _i: int) -> None:
        if not self._lire_lot:
            self.regler_division(self.cibles(),
                                 int(self.division_lot.currentData()))

    def _sur_oeil_lot(self) -> None:
        cibles = self.cibles()
        if cibles:
            self.regler_oeil(cibles, not _visible(cibles[0]))

    def _menu_contextuel(self, pos) -> None:
        rangee = self.table.rowAt(pos.y())
        ops = self._pour_rangee(rangee)
        if not ops:
            return
        suffixe = f" ({len(ops)} opés)" if len(ops) > 1 else ""
        menu = QMenu(self)
        sous = menu.addMenu(f"Transparence{suffixe}")
        for pc in af.OPACITES:
            sous.addAction("Opaque (100 %)" if pc == 100 else f"{pc} %",
                           lambda v=pc, o=ops: self.regler_opacite(o, v))
        sous = menu.addMenu(f"Une ligne sur…{suffixe}")
        for n in af.DIVISIONS:
            sous.addAction("Toutes (1/1)" if n == 1 else f"1 sur {n}",
                           lambda k=n, o=ops: self.regler_division(o, k))
        menu.addSeparator()
        menu.addAction(f"Montrer{suffixe}",
                       lambda o=ops: self.regler_oeil(o, True))
        menu.addAction(f"Masquer{suffixe}",
                       lambda o=ops: self.regler_oeil(o, False))
        menu.exec(self.table.viewport().mapToGlobal(pos))
