"""Les onglets des imports d'un dessin: un onglet par fichier importé
(DXF), visible au-dessus du Canva 2D comme du Canva 3D.

Clic sur un onglet: ses entités sont sélectionnées; l'œil (à gauche) le
montre ou le masque; « × » le ferme. Clic droit: rouvrir le dernier
onglet fermé, ou l'un des précédents (les 100 derniers sont gardés,
d'une session à l'autre).

La barre ne fait qu'afficher et rapporter: le panneau du canvas
(`DxfEditorPanel`) ferme, rouvre et tient l'historique.
"""

import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QHBoxLayout, QMenu, QTabBar, QToolButton,
                               QWidget)

#: combien d'onglets fermés on garde
HISTORIQUE_MAX = 100
#: la clé des réglages Qt où l'historique est gardé
CLE_HISTORIQUE = "canvas/imports_fermes"


def lire_historique() -> list:
    """Les imports fermés, le plus récent d'abord: [{'nom', 'chemin'}]."""
    from src.gui.theme import reglages_qt
    try:
        brut = reglages_qt().value(CLE_HISTORIQUE, "")
        liste = json.loads(brut) if brut else []
    except (TypeError, ValueError):
        return []
    return [h for h in liste if isinstance(h, dict) and h.get('chemin')
            ][:HISTORIQUE_MAX]


def ecrire_historique(liste: list) -> None:
    from src.gui.theme import reglages_qt
    reglages_qt().setValue(CLE_HISTORIQUE, json.dumps(
        list(liste)[:HISTORIQUE_MAX], ensure_ascii=False))


class BarreImports(QTabBar):
    """Un onglet par import du dessin."""

    #: clic sur un onglet: sélectionner ses entités (clé de l'import)
    choisi = Signal(str)
    #: « × »: fermer l'import
    ferme = Signal(str)
    #: l'œil d'un onglet
    visibilite = Signal(str, bool)
    #: rouvrir l'onglet fermé n° k de l'historique (0: le dernier)
    rouvrir_demande = Signal(int)

    _STYLE = """
        QTabBar::tab { background: #313244; color: #cdd6f4;
                       padding: 3px 6px; margin-right: 2px;
                       border-top-left-radius: 4px;
                       border-top-right-radius: 4px; }
        QTabBar::tab:selected { background: #45475a; color: #f9e2af; }
        QTabBar::tab:hover:!selected { background: #3b3d52; }
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabsClosable(True)
        self.setMovable(False)
        self.setExpanding(False)
        self.setUsesScrollButtons(True)
        # le nom entier (les flèches font défiler s'ils sont nombreux):
        # une police posée sur le widget, pas dans la feuille de style —
        # sinon la largeur se calcule avec l'une et le texte s'écrit
        # avec l'autre, et le nom s'élide pour rien
        self.setElideMode(Qt.TextElideMode.ElideNone)
        police = self.font()
        police.setPointSizeF(8.5)
        self.setFont(police)
        self.setDrawBase(False)
        self.setDocumentMode(True)
        self.setStyleSheet(self._STYLE)
        #: l'historique des onglets fermés: () -> [{'nom', 'chemin'}]
        self.historique = lambda: []
        self.tabBarClicked.connect(self._clic)
        self.tabCloseRequested.connect(
            lambda i: self.ferme.emit(str(self.tabData(i) or "")))
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.hide()

    #: les pièces 3D en tête (la barre au-dessus du Canva 3D)
    pieces_d_abord = False

    def cles(self) -> list:
        return [str(self.tabData(i)) for i in range(self.count())]

    def remplir(self, imports: list) -> None:
        """Les onglets des imports [{'cle', 'nom', 'chemin',
        'visible'}]. La barre se montre dès qu'il y a un import — ou un
        onglet fermé à rouvrir."""
        self.blockSignals(True)
        while self.count():
            self.removeTab(0)
        if self.pieces_d_abord:
            imports = ([i for i in imports if i.get('source_3d')]
                       + [i for i in imports if not i.get('source_3d')])
        from src.gui.icons import get_icon
        for imp in imports:
            i = self.addTab(str(imp.get('nom', '')))
            cle = str(imp['cle'])
            self.setTabData(i, cle)
            visible = bool(imp.get('visible', True))
            piece = bool(imp.get('source_3d'))
            if piece:
                # une pièce en volume: son icône; l'ACTIVE (celle qu'on
                # usine) en couleur
                self.setTabIcon(i, get_icon("b_piece", 14,
                                            "#f9e2af" if imp.get('active')
                                            else "#a6adc8"))
            self.setTabToolTip(
                i, f"{imp.get('chemin') or imp.get('nom', '')}\n"
                + ("Pièce 3D" + (" ACTIVE (usinage, faces)"
                                  if imp.get('active') else
                                  " — clic: la rendre active") + "\n"
                   if piece else "")
                + "Clic: sélectionner ses entités · œil: montrer ou "
                "masquer · ×: fermer\nClic droit: rouvrir un onglet fermé")
            oeil = QToolButton(self)
            oeil.setCheckable(True)
            oeil.setChecked(visible)
            oeil.setAutoRaise(True)
            oeil.setFixedSize(18, 18)
            oeil.setStyleSheet("QToolButton { background: transparent; "
                               "border: none; padding: 0; }")
            self._icone_oeil(oeil, visible)
            oeil.setToolTip("Montrer ou masquer ce dessin")
            oeil.toggled.connect(
                lambda on, c=cle: self._sur_oeil(c, on))
            self.setTabButton(i, QTabBar.ButtonPosition.LeftSide, oeil)
            self._teinter(i, visible)
        self.blockSignals(False)
        self.setVisible(bool(imports) or bool(self.historique()))

    def oeil(self, cle: str):
        """Le bouton œil de l'onglet de cet import (ou None)."""
        for i in range(self.count()):
            if str(self.tabData(i)) == cle:
                return self.tabButton(i, QTabBar.ButtonPosition.LeftSide)
        return None

    def _teinter(self, i: int, visible: bool) -> None:
        from PySide6.QtGui import QColor
        self.setTabTextColor(i, QColor("#cdd6f4" if visible else "#6c7086"))

    @staticmethod
    def _icone_oeil(bouton, visible: bool) -> None:
        from src.gui.icons import get_icon
        bouton.setIcon(get_icon("eye", 14,
                                "#a6e3a1" if visible else "#6c7086"))

    def _sur_oeil(self, cle: str, on: bool) -> None:
        for i in range(self.count()):
            if str(self.tabData(i)) == cle:
                self._teinter(i, on)
                self._icone_oeil(self.tabButton(
                    i, QTabBar.ButtonPosition.LeftSide), on)
        self.visibilite.emit(cle, bool(on))

    def _clic(self, i: int) -> None:
        if i >= 0:
            self.choisi.emit(str(self.tabData(i)))

    def menu_contextuel(self, i: int = -1) -> QMenu:
        """Le menu du clic droit (sur l'onglet i, ou à côté)."""
        menu = QMenu(self)
        hist = self.historique()
        dernier = menu.addAction(
            "Rouvrir le dernier onglet fermé"
            + (f" — {hist[0].get('nom', '')}" if hist else ""))
        dernier.setEnabled(bool(hist))
        dernier.triggered.connect(lambda: self.rouvrir_demande.emit(0))
        if len(hist) > 1:
            # un parent explicite: sans lui, PySide détruit le sous-menu
            # dès que la fonction rend la main
            sous = QMenu(f"Onglets fermés ({len(hist)})", menu)
            menu.addMenu(sous)
            for k, h in enumerate(hist):
                act = sous.addAction(str(h.get('nom', '')))
                act.setToolTip(str(h.get('chemin', '')))
                act.triggered.connect(
                    lambda _=False, k=k: self.rouvrir_demande.emit(k))
        if i >= 0:
            cle = str(self.tabData(i))
            menu.addSeparator()
            menu.addAction("Sélectionner ses entités").triggered.connect(
                lambda: self.choisi.emit(cle))
            menu.addAction("Fermer l'onglet").triggered.connect(
                lambda: self.ferme.emit(cle))
        return menu

    def _menu(self, pos) -> None:
        self.menu_contextuel(self.tabAt(pos)).exec(self.mapToGlobal(pos))


class BandeauImports(QWidget):
    """La barre des imports et, au bout, « Importer » et « Exporter »
    (octobre 2026, RomDuch: les gestes du dessin là où sont ses
    onglets). Le bandeau reste visible sans import: c'est par lui
    qu'arrive le premier."""

    importer = Signal()
    exporter = Signal()

    def __init__(self, barre: "BarreImports", parent=None):
        super().__init__(parent)
        from src.gui.icons import get_icon
        self.barre = barre
        rangee = QHBoxLayout(self)
        rangee.setContentsMargins(0, 0, 2, 0)
        rangee.setSpacing(2)
        rangee.addWidget(barre)
        rangee.addStretch(1)
        self.importer_btn = QToolButton(self)
        self.importer_btn.setIcon(get_icon("import", 16))
        # élargi (novembre 2026, RomDuch): l'icône ET son nom — c'est
        # par lui qu'arrive chaque onglet d'import
        self.importer_btn.setText("Importer")
        self.importer_btn.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.importer_btn.setMinimumWidth(84)
        self.importer_btn.setAutoRaise(True)
        self.importer_btn.setToolTip(
            "Importer un dessin (DXF, DWG, SVG, PDF, STEP, image…) — "
            "dans un nouvel onglet d'import")
        self.importer_btn.clicked.connect(lambda: self.importer.emit())
        rangee.addWidget(self.importer_btn)
        self.exporter_btn = QToolButton(self)
        self.exporter_btn.setIcon(get_icon("export", 16))
        self.exporter_btn.setAutoRaise(True)
        self.exporter_btn.setToolTip(
            "Exporter le dessin du Canva (DXF, SVG, PDF, PNG…)")
        self.exporter_btn.clicked.connect(lambda: self.exporter.emit())
        rangee.addWidget(self.exporter_btn)
