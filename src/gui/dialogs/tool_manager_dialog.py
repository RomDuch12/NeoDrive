"""
Gestionnaire d'outils : panneau inline (overlay col2 ou plein écran).
- Tableau avec double-click sur cellule pour édition directe
- Click sur n°ligne ouvre l'éditeur complet inline
- Pas de popup
- Champs simplifiés: pas de coolant/min_depth/materials
- Reference = ArticleNr uniquement
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QLabel, QLineEdit, QComboBox, QMessageBox,
    QGroupBox, QFormLayout, QAbstractItemView, QStackedLayout, QFileDialog,
    QApplication
)
from contextlib import nullcontext
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor
from datetime import datetime
from src.core.tool_library import ToolLibrary, Tool, reference_avec_article
from src.gui.widgets import SpinCote, SpinEntier


class _Spin(SpinEntier):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMaximumHeight(26)


class _DSpin(SpinCote):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMaximumHeight(26)


class ToolEditorInline(QWidget):
    """Éditeur d'outil inline (affiché dans le même panneau)."""
    saved = Signal()
    cancelled = Signal()

    def __init__(self, tool_data: dict = None, parent=None):
        super().__init__(parent)
        self.tool_data = tool_data or {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        title = QLabel(
            "Modifier l'outil" if self.tool_data.get('name') else "Nouvel outil")
        title.setStyleSheet("font-weight: bold; font-size: 14px; color: #cdd6f4;")
        layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(6)

        self.name_edit = QLineEdit(self.tool_data.get('name', ''))
        form.addRow("Nom:", self.name_edit)

        self.ref_edit = QLineEdit(self.tool_data.get('reference', ''))
        self.ref_edit.setPlaceholderText("0068xxxx")
        form.addRow("Ref:", self.ref_edit)

        self.type_edit = QLineEdit(self.tool_data.get('type_taraudage', ''))
        self.type_edit.setToolTip(
            "Ex: Cyl3, Cyl6, Con30, M3, M4, Drill, Chamfer, etc.")
        form.addRow("Type:", self.type_edit)

        self.vendor_edit = QLineEdit(self.tool_data.get('vendor', 'DATRON'))
        form.addRow("Fabricant:", self.vendor_edit)

        self.rpm_spin = _Spin()
        self.rpm_spin.setRange(1000, 60000)
        self.rpm_spin.setValue(self.tool_data.get('rpm', 40000))
        form.addRow("RPM:", self.rpm_spin)

        layout.addLayout(form)

        # Avances
        feeds_group = QGroupBox("Avances (mm/min)")
        feeds_layout = QFormLayout()
        feeds_layout.setSpacing(4)

        self.feed_finishing = _Spin()
        self.feed_finishing.setRange(0, 20000)
        self.feed_finishing.setValue(
            self.tool_data.get('feed_finishing', 800))
        feeds_layout.addRow("Finition:", self.feed_finishing)

        self.feed_approach = _Spin()
        self.feed_approach.setRange(0, 20000)
        self.feed_approach.setValue(
            self.tool_data.get('feed_approach', 1000))
        feeds_layout.addRow("Approche:", self.feed_approach)

        self.feed_plunge = _Spin()
        self.feed_plunge.setRange(0, 20000)
        self.feed_plunge.setValue(
            self.tool_data.get('feed_plunge', 500))
        feeds_layout.addRow("Plongée:", self.feed_plunge)

        self.feed_ramp = _Spin()
        self.feed_ramp.setRange(0, 20000)
        self.feed_ramp.setValue(self.tool_data.get('feed_ramp', 400))
        feeds_layout.addRow("Rampe:", self.feed_ramp)

        self.feed_roughing = _Spin()
        self.feed_roughing.setRange(0, 20000)
        self.feed_roughing.setValue(
            self.tool_data.get('feed_roughing', 400))
        feeds_layout.addRow("Ébauche:", self.feed_roughing)

        feeds_group.setLayout(feeds_layout)
        layout.addWidget(feeds_group)

        # Prof max et notes
        extra = QFormLayout()
        self.max_depth = _DSpin()
        self.max_depth.setRange(0, 200)
        self.max_depth.setDecimals(1)
        self.max_depth.setValue(self.tool_data.get('max_depth', 15.0))
        extra.addRow("Prof. max (mm):", self.max_depth)

        self.notes_edit = QLineEdit(self.tool_data.get('notes', ''))
        extra.addRow("Notes:", self.notes_edit)
        layout.addLayout(extra)

        # ── La fiche complète (@ ToolDescription @) ──
        # Chaque champ peut rester vide: un vide n'est pas écrit dans
        # la déclaration, et ne bloque rien. Ce qui est rempli nourrit
        # les formulaires de parcours et de gravure (Ø, angle de
        # pointe, troncature) avant le nom de l'outil.
        from PySide6.QtWidgets import QGridLayout, QComboBox
        from PySide6.QtGui import QDoubleValidator, QIntValidator
        from src.core.tool_library import Tool
        fiche = QGroupBox("Fiche complète (@ ToolDescription @) — "
                          "un champ vide n'est pas déclaré")
        grille = QGridLayout()
        grille.setSpacing(3)
        grille.setContentsMargins(6, 6, 6, 6)
        geometrie = dict(self.tool_data.get('geometry') or {})
        self._geom_widgets = {}
        rang, colonne = 0, 0
        for cle, libelle in Tool.GEOMETRY_LABELS:
            valeur = geometrie.get(cle)
            if cle == 'Category':
                w = QComboBox()
                w.setEditable(True)
                w.addItems(list(Tool.CATEGORIES))
                w.setCurrentText(str(valeur or Tool.CATEGORIES[0]))
                w.setToolTip("Catégorie Datron. « Unspecified » est "
                             "celle de tous les programmes de "
                             "l'atelier — la machine les accepte.")
            else:
                w = QLineEdit("" if valeur in (None, "") else
                              (f"{int(valeur)}" if cle in
                               ('ToolNumber', 'NumberOfFlutes')
                               else f"{float(valeur):g}"))
                w.setPlaceholderText("—")
                if cle in ('ToolNumber', 'NumberOfFlutes'):
                    w.setValidator(QIntValidator(0, 9999, w))
                else:
                    validateur = QDoubleValidator(0.0, 9999.0, 4, w)
                    validateur.setNotation(
                        QDoubleValidator.Notation.StandardNotation)
                    w.setValidator(validateur)
                w.setMaximumWidth(90)
                w.textChanged.connect(self._montrer_declaration)
            self._geom_widgets[cle] = w
            etiquette = QLabel(libelle + ":")
            etiquette.setStyleSheet("font-size: 11px;")
            grille.addWidget(etiquette, rang, colonne * 2)
            grille.addWidget(w, rang, colonne * 2 + 1)
            colonne += 1
            if colonne == 2:
                colonne = 0
                rang += 1
        self._geom_widgets['Category'].currentTextChanged.connect(
            self._montrer_declaration)
        rang += 1
        deduire = QPushButton("Déduire du nom")
        deduire.setToolTip("Remplit les champs VIDES avec ce que le "
                           "nom dit: « Cyl 2 z1L4 » → Ø 2, 1 dent, "
                           "coupe 4; « Con 30° 0.6 » → pointe 30°, "
                           "troncature 0,6.")
        deduire.clicked.connect(self._deduire_du_nom)
        grille.addWidget(deduire, rang, 0, 1, 2)
        vider = QPushButton("Vider la fiche")
        vider.clicked.connect(self._vider_fiche)
        grille.addWidget(vider, rang, 2, 1, 2)
        rang += 1
        self._declaration = QLabel("")
        self._declaration.setWordWrap(True)
        self._declaration.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self._declaration.setStyleSheet(
            "color: #a6adc8; font-size: 10px; font-family: monospace;")
        grille.addWidget(self._declaration, rang, 0, 1, 4)
        fiche.setLayout(grille)
        layout.addWidget(fiche)
        self.name_edit.textChanged.connect(self._montrer_declaration)
        self.ref_edit.textChanged.connect(self._montrer_declaration)
        self.vendor_edit.textChanged.connect(self._montrer_declaration)
        self._montrer_declaration()

        # Boutons
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("Enregistrer")
        save_btn.setObjectName("primary")
        save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(save_btn)

        cancel_btn = QPushButton("Annuler")
        cancel_btn.clicked.connect(self.cancelled.emit)
        btn_layout.addWidget(cancel_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        layout.addStretch()

    def _on_save(self):
        self.tool_data = self.get_tool_data()
        self.saved.emit()

    def geometrie(self) -> dict:
        """La fiche telle que saisie: les champs vides n'y sont pas."""
        sortie = {}
        for cle, w in getattr(self, '_geom_widgets', {}).items():
            if cle == 'Category':
                texte = w.currentText().strip()
                if texte and texte != 'Unspecified':
                    sortie[cle] = texte
                continue
            texte = w.text().strip().replace(',', '.')
            if not texte:
                continue
            try:
                sortie[cle] = (int(float(texte)) if cle in
                               ('ToolNumber', 'NumberOfFlutes')
                               else float(texte))
            except ValueError:
                continue
        return sortie

    def _montrer_declaration(self, *_):
        """La ligne @ ToolDescription @ telle qu'elle sortira."""
        from src.core.tool_library import Tool
        try:
            apercu = Tool({'name': self.name_edit.text(),
                           'reference': self.ref_edit.text(),
                           'vendor': self.vendor_edit.text(),
                           'geometry': self.geometrie()})
            self._declaration.setText(apercu.tool_description())
        except Exception:
            pass

    def _deduire_du_nom(self):
        from src.core.tool_library import geometrie_depuis_nom
        deduit = geometrie_depuis_nom(self.name_edit.text())
        for cle, valeur in deduit.items():
            w = self._geom_widgets.get(cle)
            if w is None or cle == 'Category' or w.text().strip():
                continue
            w.setText(f"{int(valeur)}" if cle in
                      ('ToolNumber', 'NumberOfFlutes')
                      else f"{float(valeur):g}")
        self._montrer_declaration()

    def _vider_fiche(self):
        for cle, w in self._geom_widgets.items():
            if cle == 'Category':
                w.setCurrentText('Unspecified')
            else:
                w.clear()
        self._montrer_declaration()

    def get_tool_data(self) -> dict:
        # ce que le formulaire ne montre pas (usage, arrosage…) est
        # gardé tel quel: l'éditeur remplaçait l'outil entier et
        # perdait sa géométrie
        conserve = {k: v for k, v in dict(self.tool_data).items()
                    if k not in ('geometry',)}
        conserve.update(self._valeurs_du_formulaire())
        conserve['geometry'] = self.geometrie()
        try:
            conserve['diameter'] = float(
                conserve['geometry'].get('Diameter') or 0.0)
        except (TypeError, ValueError):
            pass
        return conserve

    def _valeurs_du_formulaire(self) -> dict:
        return {
            'name': self.name_edit.text(),
            'reference': self.ref_edit.text(),
            'type_taraudage': self.type_edit.text(),
            'vendor': self.vendor_edit.text(),
            'rpm': self.rpm_spin.value(),
            'feed_finishing': self.feed_finishing.value(),
            'feed_approach': self.feed_approach.value(),
            'feed_plunge': self.feed_plunge.value(),
            'feed_ramp': self.feed_ramp.value(),
            'feed_roughing': self.feed_roughing.value(),
            'max_depth': self.max_depth.value(),
            'notes': self.notes_edit.text(),
        }


#: les teintes Mocha écrites dans les feuilles de style de ce panneau,
#: et la couleur du thème qui les remplace (thème clair: le tableau et
#: ses boutons restaient sombres)
_TEINTES_MOCHA = {
    "#313244": "surface", "#45475a": "surface_hover", "#89b4fa": "accent",
    "#a6e3a1": "green", "#f38ba8": "red", "#f9e2af": "yellow",
    "#a6adc8": "text_dim", "#cdd6f4": "text", "#74c7ec": "teal",
    "#1e1e2e": "bg", "#181825": "bg_alt",
}


def _t(cle: str) -> str:
    """Une couleur du thème courant (lue à l'affichage)."""
    from src.gui.icons import _colors
    return _colors().get(cle, '#888888')


def _carte_du_theme() -> dict:
    """{teinte Mocha: couleur du thème courant}."""
    return {hexa: _t(cle) for hexa, cle in _TEINTES_MOCHA.items()}


def _au_theme(css: str, carte: dict = None) -> str:
    """La feuille de style aux couleurs du thème courant."""
    sortie = css
    for hexa, couleur in (carte or _carte_du_theme()).items():
        sortie = sortie.replace(hexa, couleur)
    return sortie


def theme_des_enfants(racine) -> None:
    """Chaque widget de `racine` aux couleurs du thème (sa feuille
    d'origine est gardée: un changement de thème la retraduit).

    Une feuille inchangée n'est pas reposée: Qt repolit le widget à
    chaque setStyleSheet, même identique — 428 fois par mise à jour du
    tableau des outils (▲ ▼, filtre), pour rien en thème sombre."""
    from PySide6.QtWidgets import QWidget
    carte = _carte_du_theme()
    for w in [racine] + racine.findChildren(QWidget):
        orig = w.property('css_mocha')
        if orig is None:
            orig = w.styleSheet()
            if not orig or not any(h in orig for h in _TEINTES_MOCHA):
                continue
            w.setProperty('css_mocha', orig)
        voulue = _au_theme(orig, carte)
        if w.styleSheet() != voulue:
            w.setStyleSheet(voulue)


class _ToolTable(QTableWidget):
    """Table d'outils éditable au clavier.

    Entrée ouvre l'éditeur sur la cellule courante; un second Entrée
    valide (comportement natif de Qt en cours d'édition). Évite de
    devoir viser un double-clic pour corriger une avance."""

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            editing = (self.state()
                       == QAbstractItemView.State.EditingState)
            item = self.currentItem()
            if (not editing and item is not None
                    and item.flags() & Qt.ItemFlag.ItemIsEditable):
                self.editItem(item)
                return
        super().keyPressEvent(event)


class ToolManagerPanel(QWidget):
    """Panneau inline de gestion des outils (overlay col2)."""
    close_requested = Signal()
    #: la bibliothèque a changé par un bouton « DATRON »
    outils_changes = Signal()
    #: le tableau dans toute la fenêtre (True), ou à sa place (False)
    plein_fenetre_demande = Signal(bool)

    #: colonne des boutons « DATRON »
    COL_DATRON = 12
    #: longueurs de coupe et utile (fiche @ ToolDescription @)
    COL_L_COUPE = 13
    COL_L_UTILE = 14
    _COLS_LONGUEURS = {13: 'FluteLength', 14: 'ShoulderLength'}
    #: colonne des boutons « Dessin » (DXF + STEP de l'outil)
    COL_DESSIN = 15
    #: la couleur de l'outil au plan, dans la légende et en 3D
    COL_COULEUR = 16
    #: les teintes des familles d'outils (bandes du tableau)
    TEINTES_FAMILLES = (('Cyl', 'green'), ('Con', 'blue'),
                        ('Drill', 'orange'), ('Chamfer', 'purple'),
                        ('M', 'teal'), ('Thr', 'teal'))
    #: les pages du panneau: le tableau, la fiche (quand la fenêtre
    #: ne la prend pas en colonnes 1 et 2)
    PAGE_TABLE, PAGE_EDITEUR = 0, 1
    #: la fenêtre héberge la fiche d'un outil à la place des colonnes 1
    #: et 2: `hote_fiche(fiche) -> bool` (False: pas de place, la fiche
    #: va dans le panneau), `fermer_hote_fiche(fiche)` la rend
    hote_fiche = None
    fermer_hote_fiche = None
    #: () -> contexte: une fiche en remplace une autre dans le même
    #: geste (la fenêtre garde sa page au lieu de rendre les colonnes)
    remplacement_fiche = None
    #: une fiche d'un AUTRE panneau (le catalogue) est ouverte en
    #: colonnes 1 et 2: () -> bool, et de quoi la fermer
    fiche_ailleurs = None
    fermer_fiche_ailleurs = None
    #: la réponse à « fiche retouchée: l'enregistrer ? » — None: on
    #: demande; 'enregistrer', 'abandonner' ou 'annuler' (tests)
    reponse_fiche_modifiee = None

    def __init__(self, tool_library: ToolLibrary, parent=None,
                 catalogue=None, guide=None, broche=None):
        super().__init__(parent)
        self.tool_lib = tool_library
        self._displayed_ids = []
        self._editing_tid = None
        #: la fiche ouverte, et où: colonnes 1+2 (True) ou panneau
        self._fiche = None
        self._fiche_hebergee = False
        self._en_bascule = False
        self._refus_tid = None
        # catalogue DATRON et guide de coupe: ceux de l'application
        # par défaut; `broche` rend la broche choisie (onglet Catalogue)
        self._catalogue = catalogue
        self._guide = guide
        self._broche = broche
        self._setup_ui()
        self._refresh_table()
        # boutons et cadres aux couleurs du thème
        theme_des_enfants(self)

    def marquer_plein(self, oui: bool) -> None:
        """(la fenêtre) le bouton dit l'état réel, sans réémettre."""
        self.plein_btn.blockSignals(True)
        self.plein_btn.setChecked(bool(oui))
        self.plein_btn.setText("⤡ Revenir à la colonne" if oui
                               else "⛶ Toute la fenêtre")
        self.plein_btn.blockSignals(False)
        if oui:
            # après la mise en page: la largeur n'est connue qu'alors
            QTimer.singleShot(0, self.etaler_colonnes)
        else:
            self._rendre_colonnes()

    def etaler_colonnes(self) -> None:
        """Les colonnes s'élargissent au prorata jusqu'à remplir la
        largeur (le bouton de copie et DATRON gardent la leur); les
        largeurs d'avant sont gardées pour le retour."""
        if not self.plein_btn.isChecked():
            return
        hdr = self.table.horizontalHeader()
        if getattr(self, '_largeurs_avant', None) is None:
            self._largeurs_avant = [hdr.sectionSize(i)
                                    for i in range(hdr.count())]
        largeurs = list(self._largeurs_avant)
        fixes = {10, self.COL_DATRON, self.COL_DESSIN, self.COL_COULEUR}
        dispo = (self.table.viewport().width()
                 - sum(largeurs[i] for i in fixes) - 2)
        souples = sum(w for i, w in enumerate(largeurs) if i not in fixes)
        if souples <= 0 or dispo <= souples:
            return
        facteur = dispo / souples
        for i, w in enumerate(largeurs):
            if i not in fixes and not hdr.isSectionHidden(i):
                hdr.resizeSection(i, int(w * facteur))

    def _rendre_colonnes(self) -> None:
        avant = getattr(self, '_largeurs_avant', None)
        if avant is None:
            return
        self._largeurs_avant = None
        hdr = self.table.horizontalHeader()
        for i, w in enumerate(avant):
            hdr.resizeSection(i, w)

    def keyPressEvent(self, event):
        if (event.key() == Qt.Key.Key_Escape
                and self._stack.currentIndex() == self.PAGE_EDITEUR):
            self.fermer_fiche()
            return
        if (event.key() == Qt.Key.Key_Escape
                and self.plein_btn.isChecked()):
            self.plein_fenetre_demande.emit(False)
            return
        super().keyPressEvent(event)

    def catalogue(self):
        if self._catalogue is None:
            from src.core.catalogue_datron import catalogue
            self._catalogue = catalogue()
        return self._catalogue

    def guide(self):
        if self._guide is None:
            from src.core.coupe_datron import guide
            self._guide = guide()
        return self._guide

    def broche(self) -> str:
        from src.core.coupe_datron import BROCHE_DEFAUT
        try:
            return (self._broche() if callable(self._broche)
                    else self._broche) or BROCHE_DEFAUT
        except Exception:
            return BROCHE_DEFAUT

    def _setup_ui(self):
        self._stack = QStackedLayout(self)

        # Page 0: Tableau
        table_page = QWidget()
        layout = QVBoxLayout(table_page)
        layout.setContentsMargins(4, 4, 4, 4)

        # Titre + fermer
        header = QHBoxLayout()
        title = QLabel("Gestionnaire d'outils")
        title.setStyleSheet("font-weight: bold; font-size: 14px; color: #cdd6f4;")
        header.addWidget(title)
        header.addStretch()
        # tools.json en grand: toutes les colonnes lisibles d'un coup
        self.plein_btn = QPushButton("⛶ Toute la fenêtre")
        self.plein_btn.setCheckable(True)
        self.plein_btn.setToolTip(
            "Afficher les outils (tools.json) dans toute la fenêtre.\n"
            "Re-cliquer, « Fermer » ou Échap: retour à la colonne.")
        self.plein_btn.toggled.connect(self.plein_fenetre_demande.emit)
        header.addWidget(self.plein_btn)
        close_btn = QPushButton("Fermer")
        close_btn.clicked.connect(self.close_requested.emit)
        header.addWidget(close_btn)
        layout.addLayout(header)

        # Barre de recherche
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Recherche:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Filtrer par nom ou référence...")
        self.search_edit.textChanged.connect(self._on_search)
        search_layout.addWidget(self.search_edit)

        self.type_filter = QComboBox()
        self.type_filter.addItem("Tous types", "")
        types = sorted(set(t.type_taraudage
                           for t in self.tool_lib.get_all_tools()))
        for t in types:
            self.type_filter.addItem(t, t)
        self.type_filter.currentIndexChanged.connect(self._on_search)
        search_layout.addWidget(self.type_filter)
        layout.addLayout(search_layout)

        # Tableau
        self.table = _ToolTable()
        self.table.setColumnCount(17)
        self.table.setHorizontalHeaderLabels([
            "Type", "Nom", "Ref", "Pz.Max", "RPM",
            "roughing", "ramp", "plunge", "finishing", "approach", "",
            "Géométrie", "DATRON", "L coupe", "L utile", "Dessin",
            "Couleur"
        ])
        hdr = self.table.horizontalHeader()
        # Toutes les colonnes librement redimensionnables par l'utilisateur
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hdr.setStretchLastSection(False)
        # Colonnes réarrangeables par glissé-déposé
        hdr.setSectionsMovable(True)
        # Largeurs par défaut raisonnables
        hdr.setDefaultSectionSize(75)
        hdr.resizeSection(0, 60)    # Type
        hdr.resizeSection(1, 150)   # Nom plus large
        hdr.resizeSection(10, 45)   # Bouton Copy petit
        hdr.resizeSection(11, 150)  # la fiche, en un coup d'œil
        hdr.resizeSection(self.COL_DATRON, 72)
        # L coupe et L utile à côté de Pz.Max: trois longueurs qu'on
        # compare d'un coup d'œil
        for i, col in enumerate((self.COL_L_COUPE, self.COL_L_UTILE)):
            hdr.resizeSection(col, 58)
            hdr.moveSection(hdr.visualIndex(col), hdr.visualIndex(3) + 1 + i)
        # le bouton DATRON en FIN de ligne (demande d'atelier,
        # octobre 2026): le tableau se lit d'abord, on agit au bout —
        # « Toute la fenêtre » le garde en vue
        hdr.moveSection(hdr.visualIndex(self.COL_DATRON), hdr.count() - 1)
        # le dessin juste avant: deux actions au bout de la ligne
        hdr.resizeSection(self.COL_DESSIN, 72)
        hdr.moveSection(hdr.visualIndex(self.COL_DESSIN), hdr.count() - 2)
        # la couleur à côté du nom: c'est elle qu'on retrouve au plan
        hdr.resizeSection(self.COL_COULEUR, 54)
        hdr.moveSection(hdr.visualIndex(self.COL_COULEUR),
                        hdr.visualIndex(1) + 1)
        self.table.horizontalHeaderItem(self.COL_COULEUR).setToolTip(
            "La couleur de l'outil au plan 2D, dans la légende et en 3D "
            "(clic: la choisir, ou revenir à l'automatique)")
        self.table.cellClicked.connect(self._sur_clic_cellule)
        self.table.horizontalHeaderItem(self.COL_DESSIN).setToolTip(
            "Le dessin de l'outil à partir de ses cotes: DXF coté et "
            "STEP 3D,\ndans le dossier « outils » à côté de tools.json, "
            "annexés à la fiche")
        self.table.horizontalHeaderItem(self.COL_L_COUPE).setToolTip(
            "Longueur de COUPE (FluteLength): la partie taillée")
        self.table.horizontalHeaderItem(self.COL_L_UTILE).setToolTip(
            "Longueur UTILE (ShoulderLength): jusqu'à l'épaulement — "
            "le « L » des noms de l'atelier")
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked)
        # aux couleurs du thème (le tableau restait sombre en thème
        # clair)
        self.appliquer_theme(rafraichir=False)
        self.table.cellChanged.connect(self._on_cell_changed)
        # la fiche ouverte en colonnes 1 et 2 suit l'outil choisi ici
        self.table.itemSelectionChanged.connect(self._fiche_suit_selection)
        self.table.verticalHeader().sectionClicked.connect(
            self._on_row_header_clicked)
        layout.addWidget(self.table)

        # Ce que le dernier bouton « DATRON » a fait — ici, sous le
        # tableau, pas dans une fenêtre qui s'interpose
        self._statut = QLabel("")
        self._statut.setWordWrap(True)
        self._statut.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self._statut.setStyleSheet("color: #a6e3a1; font-size: 11px;")
        self._statut.hide()
        layout.addWidget(self._statut)

        # Coefficients Matériau
        mat_group = QGroupBox("Coefficients Matériau")
        mat_group.setStyleSheet(
            "QGroupBox { font-weight: bold; color: #74c7ec; font-size: 11px; "
            "border: 1px solid #45475a; border-radius: 4px; margin-top: 4px; "
            "padding-top: 10px; } "
            "QGroupBox::title { subcontrol-origin: margin; padding: 0 4px; }")
        mat_layout = QVBoxLayout()
        mat_layout.setSpacing(2)
        mat_layout.setContentsMargins(6, 4, 6, 4)

        # Les coefficients que la génération applique VRAIMENT
        # (materials.json): la base ×1 est l'aluminium 6061 — celle
        # des avances DATRON. (Le texte figé d'avant disait Laiton.)
        mat_label = QLabel(self._texte_coefficients())
        mat_label.setStyleSheet("color: #a6adc8; font-size: 10px; font-family: monospace;")
        mat_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        mat_layout.addWidget(mat_label)
        mat_group.setLayout(mat_layout)
        mat_group.setMaximumHeight(110)
        layout.addWidget(mat_group)

        # Boutons
        btn_layout = QHBoxLayout()
        add_btn = QPushButton("Ajouter")
        add_btn.setObjectName("primary")
        add_btn.clicked.connect(self._on_add)
        btn_layout.addWidget(add_btn)

        del_btn = QPushButton("Supprimer")
        del_btn.setObjectName("danger")
        del_btn.clicked.connect(self._on_delete)
        btn_layout.addWidget(del_btn)

        geom_btn = QPushButton("📥 Géométrie")
        geom_btn.setToolTip(
            "Importer la géométrie d'outils depuis un SimPl Datron\n"
            "(déclarations @ ToolDescription @ : Ø, longueur de coupe,\n"
            "rayon de bec, nombre de dents, angle de pointe...).\n"
            "Les avances et RPM réglés ici ne sont jamais écrasés.")
        geom_btn.clicked.connect(self._on_import_geometry)
        # deuxième rangée: en colonne 3 (~600 px), une seule rangée
        # tronquait les boutons (« Géomét », « ssiner les »)
        btn_layout2 = QHBoxLayout()
        btn_layout2.addWidget(geom_btn)

        noms_btn = QPushButton("Fiches ← noms")
        noms_btn.setToolTip(
            "Complète les fiches VIDES avec ce que le nom de chaque "
            "outil dit:\n« Cyl 2 z1L4 » → Ø 2, 1 dent, coupe 4; "
            "« Con 30° 0.6 » → pointe 30°, troncature 0,6.\n"
            "Rien de ce qui est déjà renseigné n'est touché.")
        noms_btn.clicked.connect(self._on_completer_depuis_noms)
        btn_layout2.addWidget(noms_btn)

        up_btn = QPushButton("▲")
        up_btn.setToolTip("Monter l'outil sélectionné")
        up_btn.setMaximumWidth(36)
        up_btn.setStyleSheet(
            "QPushButton { font-size: 16px; font-weight: bold; "
            "color: #a6e3a1; background: #313244; border: 1px solid #45475a; "
            "border-radius: 4px; padding: 2px; }"
            "QPushButton:hover { background: #45475a; }")
        up_btn.clicked.connect(self._on_move_up)
        btn_layout.addWidget(up_btn)

        down_btn = QPushButton("▼")
        down_btn.setToolTip("Descendre l'outil sélectionné")
        down_btn.setMaximumWidth(36)
        down_btn.setStyleSheet(
            "QPushButton { font-size: 16px; font-weight: bold; "
            "color: #f38ba8; background: #313244; border: 1px solid #45475a; "
            "border-radius: 4px; padding: 2px; }"
            "QPushButton:hover { background: #45475a; }")
        down_btn.clicked.connect(self._on_move_down)
        btn_layout.addWidget(down_btn)

        dessins_btn = QPushButton("📐 Dessiner les outils")
        dessins_btn.setToolTip(
            "Dessine chaque outil du tableau (le filtre s'applique) à "
            "partir de ses cotes —\ncatalogue DATRON, sinon la fiche "
            "@ ToolDescription @, sinon le nom:\nun DXF coté et un STEP "
            "3D dans le dossier « outils » à côté de tools.json,\n"
            "annexés à la fiche de l'outil (bloc « dessins »).")
        dessins_btn.clicked.connect(lambda: self.dessiner_outils())
        btn_layout2.addWidget(dessins_btn)
        btn_layout2.addStretch()

        btn_layout.addStretch()

        # Import/Export
        import_btn = QPushButton("Importer")
        import_btn.setToolTip("Importer un fichier tools.json")
        import_btn.setStyleSheet(
            "QPushButton { font-size: 11px; padding: 2px 8px; "
            "background: #313244; color: #89b4fa; border-radius: 4px; }"
            "QPushButton:hover { background: #45475a; }")
        import_btn.clicked.connect(self._on_import_tools)
        btn_layout.addWidget(import_btn)

        export_btn = QPushButton("Exporter")
        export_btn.setToolTip("Exporter tools.json")
        export_btn.setStyleSheet(
            "QPushButton { font-size: 11px; padding: 2px 8px; "
            "background: #313244; color: #a6e3a1; border-radius: 4px; }"
            "QPushButton:hover { background: #45475a; }")
        export_btn.clicked.connect(self._on_export_tools)
        btn_layout.addWidget(export_btn)

        layout.addLayout(btn_layout)
        layout.addLayout(btn_layout2)

        self._stack.addWidget(table_page)

        # Page 1: Éditeur inline (sera créé dynamiquement)
        self._editor_page = QWidget()
        self._editor_layout = QVBoxLayout(self._editor_page)
        self._editor_layout.setContentsMargins(0, 0, 0, 0)
        self._stack.addWidget(self._editor_page)


    @staticmethod
    def _texte_coefficients() -> str:
        try:
            from src.core.materials import MaterialsLibrary
            lignes = []
            for m in MaterialsLibrary().get_all()[:5]:
                base = ("  (base, avances DATRON)"
                        if m.feed_multiplier == 1.0
                        and m.rpm_multiplier == 1.0 else "")
                lignes.append(f"{m.name[:16]:<17}feed ×"
                              f"{float(m.feed_multiplier):.2f}, rpm ×"
                              f"{float(m.rpm_multiplier):.2f}{base}")
            if lignes:
                return "\n".join(lignes)
        except Exception:
            pass
        return "Coefficients: data/materials.json"

    def _refresh_table(self, filter_query: str = "",
                       filter_type: str = ""):
        self.table.blockSignals(True)
        results = self.tool_lib.search_tools(
            query=filter_query, type_taraudage=filter_type)
        self.table.setRowCount(len(results))
        self._displayed_ids = []

        # Une bande par suite d'outils du même type, teintée de sa
        # famille, sur toute la ligne; deux intensités alternent quand le
        # type change (Cyl14 → Cyl8: on voit la frontière) — aux couleurs
        # du thème
        prev_type = None
        bande = 0

        for row, (tid, tool) in enumerate(results.items()):
            self._displayed_ids.append(tid)
            # Nouvel ordre: Type, Nom, Ref, Pz.Max, RPM, roughing, ramp, plunge, finishing, approach, Copy
            self.table.setItem(row, 0,
                               QTableWidgetItem(tool.type_taraudage))
            self.table.setItem(row, 1,
                               QTableWidgetItem(tool.name))
            ref = QTableWidgetItem(tool.article_nr)
            if (tool.reference or "").strip() != tool.article_nr:
                # la colonne montre l'article; la référence entière
                # (« 0068808L / 108141 ») reste dans l'infobulle
                ref.setToolTip(f"Référence: {tool.reference}")
            self.table.setItem(row, 2, ref)
            self.table.setItem(row, 3,
                               QTableWidgetItem(str(tool.max_depth)))
            self.table.setItem(row, 4,
                               QTableWidgetItem(str(tool.rpm)))
            self.table.setItem(row, 5,
                               QTableWidgetItem(str(tool.feed_roughing)))
            self.table.setItem(row, 6,
                               QTableWidgetItem(str(tool.feed_ramp)))
            self.table.setItem(row, 7,
                               QTableWidgetItem(str(tool.feed_plunge)))
            self.table.setItem(row, 8,
                               QTableWidgetItem(str(tool.feed_finishing)))
            self.table.setItem(row, 9,
                               QTableWidgetItem(str(tool.feed_approach)))

            # Bouton copier vers clipboard
            copy_btn = QPushButton("Copy")
            copy_btn.setMaximumHeight(22)
            copy_btn.setStyleSheet(
                "QPushButton { font-size: 10px; padding: 1px 4px; "
                "background: #313244; color: #89b4fa; border-radius: 3px; }"
                "QPushButton:hover { background: #45475a; }")
            copy_btn.clicked.connect(
                lambda _, t=tool: self._copy_tool_to_clipboard(t))
            self.table.setCellWidget(row, 10, copy_btn)

            # La fiche: ce que la déclaration @ ToolDescription @
            # dira de l'outil (clic sur le n° de ligne pour l'éditer)
            fiche = QTableWidgetItem(tool.geometrie_lisible() or "—")
            fiche.setFlags(fiche.flags() & ~Qt.ItemFlag.ItemIsEditable)
            fiche.setToolTip(tool.tool_description())
            self.table.setItem(row, 11, fiche)

            # Bouton « DATRON »: pour chaque outil du catalogue
            self._poser_bouton_datron(row, tid, tool)
            # Bouton « Dessin »: le DXF et le STEP de l'outil
            self._poser_bouton_dessin(row, tid, tool)

            # L coupe et L utile, éditables comme les avances
            for col, cle in self._COLS_LONGUEURS.items():
                val = tool.geometry.get(cle)
                txt = "" if val in (None, "") else f"{float(val):g}"
                self.table.setItem(row, col, QTableWidgetItem(txt))

            # La bande de la famille, sur toute la ligne
            tool_type = tool.type_taraudage
            if prev_type is not None and tool_type != prev_type:
                bande = 1 - bande
            bg_color = self.fond_famille(tool_type, bande)
            for c in range(self.table.columnCount()):
                if c == self.COL_COULEUR:
                    continue
                item = self.table.item(row, c)
                if item:
                    item.setBackground(bg_color)
            prev_type = tool_type
            self._poser_couleur(row, tid, tool)

            # Le jumeau « avances DATRON »: même outil, avances
            # constructeur — le nom le dit en couleur (le texte reste
            # le nom, éditable, sans marque ajoutée)
            if tool.avances_constructeur:
                nom = self.table.item(row, 1)
                police = nom.font()
                police.setItalic(True)
                nom.setFont(police)
                nom.setForeground(QColor(_t('orange')))
                nom.setToolTip(
                    "Avances DATRON recommandées"
                    + (f" — jumeau de « {self.tool_lib.tools[tool.jumeau_de].name} »"
                       if tool.jumeau_de in self.tool_lib.tools else "")
                    + ".\nRégler une avance en fait une fiche à vous.")

        self.table.blockSignals(False)
        # les boutons des lignes (Copy, Dessin, DATRON) au thème
        theme_des_enfants(self.table)

    def _poser_bouton_datron(self, row: int, tid: str, tool):
        try:
            x = self.catalogue().entree(tool.article_nr)
        except Exception:
            x = None
        if x is None:
            self.table.removeCellWidget(row, self.COL_DATRON)
            return
        jumeau = tool.avances_constructeur
        bouton = QPushButton("↻ DATRON" if jumeau else "DATRON")
        bouton.setMaximumHeight(22)
        bouton.setStyleSheet(
            "QPushButton { font-size: 10px; padding: 1px 4px; "
            "background: #313244; color: #f9e2af; border-radius: 3px; }"
            "QPushButton:hover { background: #45475a; }")
        bouton.setToolTip(
            f"{x.get('ref')} — {x.get('famille', '')}\n"
            "Importer les données constructeur: fiche complétée "
            "(jamais écrasée, écarts signalés), cotes et prix rangés "
            "dans tools.json.\nPour une fraise 1 dent, un jumeau "
            "« avances DATRON » porte les avances recommandées: vos "
            "avances restent les vôtres.")
        bouton.clicked.connect(
            lambda _=False, t=tid: self.importer_datron(t))
        self.table.setCellWidget(row, self.COL_DATRON, bouton)

    def _poser_bouton_dessin(self, row: int, tid: str, tool):
        from src.core.dessin_outil import dessins_de
        fichiers = dessins_de(self.tool_lib, tid)
        bouton = QPushButton("📐 Voir" if fichiers else "📐 Dessiner")
        bouton.setMaximumHeight(22)
        bouton.setStyleSheet(
            "QPushButton { font-size: 10px; padding: 1px 4px; "
            "background: #313244; color: %s; border-radius: 3px; }"
            "QPushButton:hover { background: #45475a; }"
            % ("#a6e3a1" if fichiers else "#a6adc8"))
        if fichiers:
            bouton.setToolTip(
                "Voir le dessin de l'outil (DXF coté + STEP 3D):\n"
                + "\n".join(fichiers.values()))
        else:
            bouton.setToolTip(
                "Dessiner l'outil à partir de ses cotes (catalogue "
                "DATRON, fiche, nom):\nun DXF coté et un STEP 3D, "
                "annexés à sa fiche dans tools.json.")
        bouton.clicked.connect(
            lambda _=False, t=tid: self.voir_dessin(t))
        self.table.setCellWidget(row, self.COL_DESSIN, bouton)

    def _signaler(self, texte: str, ok: bool = True) -> None:
        """Le compte rendu sous le tableau (et au journal)."""
        self._statut.setText(texte)
        self._statut.setStyleSheet(
            "color: %s; font-size: 11px;" % (_t('green') if ok else _t('red')))
        self._statut.show()
        if hasattr(self.window(), '_log_action'):
            self.window()._log_action(texte)

    def dessiner_outil(self, tool_id: str) -> dict:
        """Dessine un outil (DXF + STEP), l'annexe à sa fiche et
        enregistre tools.json. Rend ce que `dessin_outil.dessiner`
        rend, ou {} en cas d'échec (dit sous le tableau)."""
        from src.core import dessin_outil
        try:
            res = dessin_outil.dessiner(self.tool_lib, tool_id,
                                        self.catalogue())
        except Exception as exc:
            nom = getattr(self.tool_lib.tools.get(tool_id), 'name', tool_id)
            self._signaler(f"Dessin de « {nom} » impossible: {exc}", False)
            return {}
        self.tool_lib.save()
        self._signaler(f"Dessin de « {self.tool_lib.tools[tool_id].name} »"
                       f" ({res['cotes']['famille']}, cotes: "
                       f"{res['cotes']['source']}): "
                       f"{res['dxf']} — {res['step']}")
        return res

    def dessiner_outils(self, ids=None) -> dict:
        """« 📐 Dessiner les outils »: tous ceux du tableau (le filtre
        s'applique), dans la barre d'état avec Annuler. Ce qui est
        dessiné avant l'annulation reste dessiné (fichiers complets,
        annexés). Rend {'faits', 'echecs', 'annule'}."""
        from src.core import dessin_outil
        from src.core.vcarve import avancer
        from src.gui.progression import travailler
        ids = [t for t in (self._displayed_ids if ids is None else ids)
               if t in self.tool_lib.tools]
        bilan = {'faits': [], 'echecs': [], 'annule': False}
        if not ids:
            return bilan
        cat = self.catalogue()

        def travail(progression):
            for i, tid in enumerate(ids):
                avancer(progression, i / len(ids),
                        f"{i + 1}/{len(ids)} {self.tool_lib.tools[tid].name}")
                try:
                    dessin_outil.dessiner(self.tool_lib, tid, cat)
                    bilan['faits'].append(tid)
                except Exception as exc:
                    bilan['echecs'].append((tid, str(exc)))
            avancer(progression, 1.0, "fini")
            return bilan

        bilan['annule'] = travailler(self, "Dessin des outils", travail,
                                     f"{len(ids)} outils") is None
        if bilan['faits']:
            self.tool_lib.save()
        self._on_search()
        texte = (f"{len(bilan['faits'])} outil(s) dessiné(s) sur {len(ids)}"
                 f" — DXF + STEP dans {dessin_outil.dossier_dessins(self.tool_lib)},"
                 " annexés à tools.json")
        if bilan['annule']:
            texte = "Annulé: " + texte
        if bilan['echecs']:
            texte += "\nÉchecs: " + "; ".join(
                f"{self.tool_lib.tools[t].name}: {e}"
                for t, e in bilan['echecs'][:6])
        self._signaler(texte, not bilan['echecs'])
        return bilan

    def voir_dessin(self, tool_id: str) -> bool:
        """Le bouton « Dessin » d'une ligne: la fiche de l'outil (son
        DXF et son STEP y sont, faits la première fois)."""
        with self._remplacement():
            if not self.quitter_fiche(sauf=tool_id):
                return False
            return self.ouvrir_fiche_outil(tool_id) is not None

    def assurer_dessin(self, tool_id: str) -> bool:
        """Le dessin de l'outil dans le dossier de sa fiche, à jour:
        calculé et gardé la première fois (ou quand la fiche a changé
        ailleurs, une longueur du tableau…), relu ensuite."""
        from src.core import dessin_outil
        if dessin_outil.dessins_a_jour(self.tool_lib, tool_id,
                                       self.catalogue()):
            return True
        ok = bool(self.dessiner_outil(tool_id))
        if ok:
            self._maj_bouton_dessin(tool_id)
        return ok

    def _maj_bouton_dessin(self, tool_id: str) -> None:
        if tool_id in self._displayed_ids:
            row = self._displayed_ids.index(tool_id)
            self._poser_bouton_dessin(row, tool_id,
                                      self.tool_lib.tools[tool_id])

    def quitter_fiche(self, sauf: str = None) -> bool:
        """Avant d'ouvrir une autre fiche: celle-ci, retouchée, est
        enregistrée ou abandonnée — ou l'on reste (False). `sauf`: la
        fiche de cet outil est déjà ouverte, rien à quitter."""
        fiche = self._fiche
        if fiche is None or (sauf is not None and fiche.tool_id == sauf):
            return True
        if not fiche.modifiee():
            self.fermer_fiche()
            return True
        reponse = self.reponse_fiche_modifiee
        if reponse is None:
            boite = QMessageBox(self)
            boite.setWindowTitle("Fiche retouchée")
            boite.setText(f"La fiche de « {fiche.editor.name_edit.text()} »"
                          " a été retouchée.")
            boite.setInformativeText("L'enregistrer (tools.json et son "
                                     "dessin) avant d'ouvrir l'autre ?")
            oui = boite.addButton("Enregistrer",
                                  QMessageBox.ButtonRole.AcceptRole)
            non = boite.addButton("Abandonner les retouches",
                                  QMessageBox.ButtonRole.DestructiveRole)
            boite.addButton("Rester sur la fiche",
                            QMessageBox.ButtonRole.RejectRole)
            boite.exec()
            clic = boite.clickedButton()
            reponse = ('enregistrer' if clic is oui else
                       'abandonner' if clic is non else 'annuler')
        if reponse == 'enregistrer':
            self._enregistrer_fiche(fiche, reselectionner=False)
            return True
        if reponse == 'abandonner':
            self.fermer_fiche()
            return True
        return False

    def _fiche_suit_selection(self) -> None:
        """Une fiche est ouverte en colonnes 1 et 2: elle s'adapte à
        l'outil choisi dans le tableau."""
        if self._en_bascule:
            return
        ici = self._fiche is not None and self._fiche_hebergee
        ailleurs = callable(self.fiche_ailleurs) and self.fiche_ailleurs()
        if not (ici or ailleurs):
            return
        rangs = sorted({i.row() for i in self.table.selectedIndexes()})
        if len(rangs) != 1 or not 0 <= rangs[0] < len(self._displayed_ids):
            return
        tid = self._displayed_ids[rangs[0]]
        if ici and self._fiche.tool_id == tid:
            return
        self._en_bascule = True
        try:
            with self._remplacement():
                if ici and not self.quitter_fiche():
                    self._refus_tid = tid
                    return
                if ailleurs and callable(self.fermer_fiche_ailleurs):
                    self.fermer_fiche_ailleurs()
                self.ouvrir_fiche_outil(tid)
        finally:
            self._en_bascule = False

    def _remplacement(self):
        """Le contexte « une fiche en remplace une autre » de la
        fenêtre (rien sans fenêtre)."""
        if callable(self.remplacement_fiche):
            return self.remplacement_fiche()
        return nullcontext()

    # ──── la fiche d'un outil ────

    def ouvrir_fiche_outil(self, tool_id: str):
        """La fiche d'un outil de tools.json (rend le widget): son
        dessin est fait et gardé la première fois, relu ensuite."""
        tool = self.tool_lib.get_tool(tool_id)
        if tool is None:
            return None
        if self._fiche is not None and self._fiche.tool_id == tool_id:
            return self._fiche              # déjà ouverte
        self.assurer_dessin(tool_id)
        tool = self.tool_lib.get_tool(tool_id)
        self._editing_tid = tool_id
        return self.ouvrir_fiche(tool.to_dict(), tool_id)

    def ouvrir_fiche(self, tool_data: dict, tool_id: str = None):
        """Ouvre la fiche: en colonnes 1 et 2 si la fenêtre a la place,
        sinon dans ce panneau. Une fiche déjà ouverte se ferme."""
        from src.gui.dialogs.fiche_outil import FicheOutil
        with self._remplacement():
            self.fermer_fiche(garder_edition=True)
            fiche = FicheOutil(tool_data, self.tool_lib, self.catalogue(),
                               tool_id)
            fiche.enregistrer_demande.connect(
                lambda: self._enregistrer_fiche(fiche))
            fiche.fermer_demande.connect(self.fermer_fiche)
            self._fiche = fiche
            if callable(self.hote_fiche) and self.hote_fiche(fiche):
                self._fiche_hebergee = True
                self._stack.setCurrentIndex(self.PAGE_TABLE)
            else:
                self._fiche_hebergee = False
                self._editor_layout.addWidget(fiche)
                self._stack.setCurrentIndex(self.PAGE_EDITEUR)
        return fiche

    def heberger_fiche_ici(self) -> None:
        """La fenêtre rend la fiche (« Toute la fenêtre »): elle passe
        dans le panneau, telle quelle."""
        fiche = self._fiche
        if fiche is None or not self._fiche_hebergee:
            return
        self._fiche_hebergee = False
        self._editor_layout.addWidget(fiche)
        fiche.show()
        self._stack.setCurrentIndex(self.PAGE_EDITEUR)

    def fermer_fiche(self, garder_edition: bool = False) -> None:
        """Ferme la fiche ouverte (sans enregistrer)."""
        fiche, self._fiche = self._fiche, None
        if fiche is not None:
            if self._fiche_hebergee and callable(self.fermer_hote_fiche):
                self.fermer_hote_fiche(fiche)
            else:
                self._editor_layout.removeWidget(fiche)
            fiche.hide()
            fiche.deleteLater()
        self._fiche_hebergee = False
        if not garder_edition:
            self._editing_tid = None
        self._stack.setCurrentIndex(self.PAGE_TABLE)

    def _enregistrer_fiche(self, fiche, reselectionner: bool = True) -> str:
        """« Enregistrer et fermer »: l'outil dans tools.json, puis son
        DXF et son STEP refaits d'après la fiche. Rend l'id de
        l'outil."""
        from src.core import dessin_outil
        data = fiche.editor.get_tool_data()
        tid = self._editing_tid or fiche.tool_id
        if tid and tid in self.tool_lib.tools:
            self.tool_lib.update_tool(tid, data)
        else:
            tid = f"custom_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            self.tool_lib.add_tool(tid, data)
        try:
            res = dessin_outil.dessiner(self.tool_lib, tid, self.catalogue())
            self.tool_lib.save()
            self._signaler(f"Fiche de « {self.tool_lib.tools[tid].name} » "
                           f"enregistrée — dessin mis à jour: {res['dxf']}"
                           f" — {res['step']}")
        except Exception as exc:
            self._signaler(f"Fiche enregistrée, dessin impossible: {exc}",
                           False)
        self.fermer_fiche()
        bascule, self._en_bascule = self._en_bascule, True
        try:
            selection = [self._displayed_ids[i.row()] for i in
                         self.table.selectionModel().selectedRows()
                         if i.row() < len(self._displayed_ids)]
            self._on_search()
            garde = tid if reselectionner else (selection[0] if selection
                                                else None)
            if garde in self._displayed_ids:
                self.table.selectRow(self._displayed_ids.index(garde))
        finally:
            self._en_bascule = bascule
        self.outils_changes.emit()
        return tid

    def importer_datron(self, tool_id: str) -> dict:
        """Le bouton « DATRON » d'une ligne."""
        from src.core.catalogue_datron import resume_import
        rapport = self.tool_lib.importer_constructeur(
            tool_id, self.catalogue(), self.broche(), self.guide())
        texte = resume_import(rapport, self.tool_lib)
        self._on_search()
        if rapport.get('ok'):
            cible = rapport.get('jumeau') or rapport.get('outil')
            if cible in self._displayed_ids:
                self.table.selectRow(self._displayed_ids.index(cible))
            self.outils_changes.emit()
        self._statut.setText(texte)
        self._statut.setStyleSheet(
            "color: %s; font-size: 11px;"
            % (_t('green') if rapport.get('ok') else _t('red')))
        self._statut.show()
        if hasattr(self.window(), '_log_action'):
            self.window()._log_action(texte)
        return rapport

    def _on_search(self, *args):
        query = self.search_edit.text()
        type_filter = self.type_filter.currentData() or ""
        self._refresh_table(query, type_filter)

    def _on_cell_changed(self, row: int, col: int):
        """Direct cell editing: update tool from table cell."""
        if row < 0 or row >= len(self._displayed_ids):
            return
        tid = self._displayed_ids[row]
        tool = self.tool_lib.get_tool(tid)
        if not tool:
            return

        item = self.table.item(row, col)
        if not item:
            return
        val = item.text()

        data = tool.to_dict()
        # Nouvel ordre: Type, Nom, Ref, Pz.Max, RPM, roughing, ramp, plunge, finishing, approach
        col_map = {
            0: ('type_taraudage', str),
            1: ('name', str),
            2: ('reference', str),
            3: ('max_depth', float),
            4: ('rpm', int),
            5: ('feed_roughing', int),
            6: ('feed_ramp', int),
            7: ('feed_plunge', int),
            8: ('feed_finishing', int),
            9: ('feed_approach', int),
        }
        if col == 2:
            # la case montre l'ARTICLE seul: le reste de la référence
            # (« / 108141 ») ne doit pas partir quand on le corrige
            data['reference'] = reference_avec_article(tool.reference, val)
        elif col in col_map:
            key, conv = col_map[col]
            try:
                data[key] = conv(val)
            except (ValueError, TypeError):
                pass
        elif col in self._COLS_LONGUEURS:
            cle = self._COLS_LONGUEURS[col]
            geo = dict(data.get('geometry') or {})
            texte = val.strip().replace(',', '.')
            if not texte:
                geo.pop(cle, None)          # vide: non déclarée
            else:
                try:
                    geo[cle] = float(texte)
                except ValueError:
                    return
            data['geometry'] = geo

        self.tool_lib.update_tool(tid, data)

    # ── la couleur de l'outil ──

    def fond_famille(self, type_outil: str, bande: int) -> QColor:
        """Le fond d'une ligne: la teinte de la famille mêlée au fond du
        thème (plus ou moins, selon la bande)."""
        from src.gui.icons import _colors
        c = _colors()
        fond = QColor(c['bg_alt'])
        teinte = None
        for prefixe, cle in self.TEINTES_FAMILLES:
            if str(type_outil).startswith(prefixe):
                teinte = QColor(c.get(cle, c['accent']))
                break
        if teinte is None:
            teinte = QColor(c['text_dim'])
        part = 0.10 if bande == 0 else 0.20
        return QColor(
            round(fond.red() * (1 - part) + teinte.red() * part),
            round(fond.green() * (1 - part) + teinte.green() * part),
            round(fond.blue() * (1 - part) + teinte.blue() * part))

    def appliquer_theme(self, rafraichir: bool = True) -> None:
        """Le tableau aux couleurs du thème courant."""
        from src.gui.icons import _colors
        c = _colors()
        self.table.setStyleSheet(f"""
            QTableWidget {{
                background: {c['bg_alt']};
                color: {c['text']};
                gridline-color: {c['border']};
                font-size: 12px;
            }}
            QTableWidget::item:selected {{
                background: {c['surface_press']};
                color: {c['text']};
            }}
            QHeaderView::section {{
                background: {c['surface']};
                color: {c['accent']};
                border: 1px solid {c['border']};
                padding: 4px;
                font-weight: bold;
                font-size: 11px;
            }}
        """)
        theme_des_enfants(self)
        if rafraichir and hasattr(self, '_displayed_ids'):
            self._on_search()

    def _poser_couleur(self, row: int, tid: str, tool) -> None:
        couleur = self.tool_lib.couleur_outil(tid) or "#a6adc8"
        item = QTableWidgetItem("" if tool.couleur else "auto")
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        item.setBackground(QColor(couleur))
        item.setForeground(QColor("#1e1e2e"))
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setToolTip(
            f"{couleur} — {'choisie' if tool.couleur else 'automatique'}"
            "\nClic: la choisir, ou revenir à l'automatique")
        # l'état d'avant revient (pendant un rafraîchissement, les signaux
        # restent coupés: sinon chaque cellule posée réécrivait tools.json)
        avant = self.table.blockSignals(True)
        self.table.setItem(row, self.COL_COULEUR, item)
        self.table.blockSignals(avant)

    def _sur_clic_cellule(self, row: int, col: int) -> None:
        if col == self.COL_COULEUR:
            self.menu_couleur(row).exec(
                self.table.viewport().mapToGlobal(
                    self.table.visualRect(self.table.model().index(
                        row, col)).bottomLeft()))

    #: la fenêtre de choix (remplaçable par les tests): (couleur de
    #: départ « #rrggbb ») -> « #rrggbb » ou "" si annulé
    choisir_couleur = None

    def menu_couleur(self, row: int):
        """Le menu de la cellule Couleur: choisir, ou l'automatique."""
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        if row < 0 or row >= len(self._displayed_ids):
            return menu
        tid = self._displayed_ids[row]
        tool = self.tool_lib.get_tool(tid)
        a = menu.addAction("Choisir une couleur…")
        a.triggered.connect(lambda _c=False: self._choisir_couleur(tid))
        b = menu.addAction("Couleur automatique")
        b.setEnabled(bool(tool and tool.couleur))
        b.triggered.connect(lambda _c=False: self.regler_couleur(tid, ""))
        return menu

    def _choisir_couleur(self, tid: str) -> None:
        depart = self.tool_lib.couleur_outil(tid) or "#89b4fa"
        if self.choisir_couleur is not None:
            choix = self.choisir_couleur(depart)
        else:
            from PySide6.QtWidgets import QColorDialog
            c = QColorDialog.getColor(QColor(depart), self,
                                      "Couleur de l'outil")
            choix = c.name() if c.isValid() else ""
        if choix:
            self.regler_couleur(tid, choix)

    def regler_couleur(self, tid: str, couleur: str) -> None:
        """La couleur de l'outil (« » = automatique), enregistrée; le
        plan et la 3D la reprennent."""
        if self.tool_lib.regler_couleur(tid, couleur):
            if tid in self._displayed_ids:
                row = self._displayed_ids.index(tid)
                self._poser_couleur(row, tid, self.tool_lib.get_tool(tid))
            self.outils_changes.emit()

    def _on_row_header_clicked(self, row: int):
        """Click on row number: open full editor inline."""
        if row < 0 or row >= len(self._displayed_ids):
            return
        tid = self._displayed_ids[row]
        tool = self.tool_lib.get_tool(tid)
        if not tool:
            return
        if self._refus_tid == tid:
            # « rester sur la fiche » vient d'être répondu pour ce clic
            self._refus_tid = None
            return
        with self._remplacement():
            if not self.quitter_fiche(sauf=tid):
                return
            self.ouvrir_fiche_outil(tid)

    def _show_editor(self, tool_data: dict):
        """(ancien nom) La fiche d'un outil."""
        return self.ouvrir_fiche(tool_data, self._editing_tid)

    def _on_add(self):
        with self._remplacement():
            if not self.quitter_fiche():
                return
            self._editing_tid = None
            self.ouvrir_fiche({})

    def _on_completer_depuis_noms(self):
        n = self.tool_lib.completer_geometries()
        if n:
            self.tool_lib.save()
        self._refresh_table()
        QMessageBox.information(
            self, "Fiches des outils",
            f"{n} fiche(s) complétée(s) depuis le nom." if n
            else "Rien à compléter: les noms ne disent rien de plus.")

    def _on_import_geometry(self):
        """Enrichit la bibliothèque depuis les @ ToolDescription @
        d'un SimPl Datron (géométrie complète des outils)."""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Importer la géométrie d'outils depuis un SimPl",
            "", "Fichiers SimPl (*.SimPl *.simpl);;Tous (*)")
        if not filepath:
            return
        try:
            report = self.tool_lib.import_geometry_from_simpl(filepath)
        except Exception as e:
            QMessageBox.warning(
                self, "Import géométrie",
                f"Lecture impossible:\n{e}")
            return
        added, updated = report['added'], report['updated']
        if not added and not updated:
            QMessageBox.information(
                self, "Import géométrie",
                "Aucune déclaration @ ToolDescription @ exploitable "
                "dans ce fichier.")
            return
        lines = []
        if updated:
            lines.append(f"{len(updated)} outil(s) enrichi(s):")
            lines += [f"  • {n}" for n in updated[:12]]
        if added:
            lines.append(f"{len(added)} outil(s) ajouté(s):")
            lines += [f"  • {n}" for n in added[:12]]
        lines.append("")
        lines.append("Avances et RPM existants inchangés.")
        QMessageBox.information(
            self, "Import géométrie", "\n".join(lines))
        self._refresh_table()

    def _on_delete(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._displayed_ids):
            return
        tid = self._displayed_ids[row]
        tool = self.tool_lib.get_tool(tid)
        if not tool:
            return

        reply = QMessageBox.question(
            self, "Supprimer l'outil",
            f"Supprimer '{tool.name}' ?",
            QMessageBox.StandardButton.Yes |
            QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.tool_lib.delete_tool(tid)
            self._refresh_table()

    def _on_move_up(self):
        """Monte l'outil sélectionné d'une position."""
        row = self.table.currentRow()
        if row <= 0 or row >= len(self._displayed_ids):
            return
        self._swap_tools(row, row - 1)

    def _on_move_down(self):
        """Descend l'outil sélectionné d'une position."""
        row = self.table.currentRow()
        if row < 0 or row >= len(self._displayed_ids) - 1:
            return
        self._swap_tools(row, row + 1)

    def _swap_tools(self, row_a: int, row_b: int):
        """Échange la position de deux outils dans la bibliothèque."""
        tid_a = self._displayed_ids[row_a]
        tid_b = self._displayed_ids[row_b]
        # Reconstruire le dict ordonné avec les positions échangées
        keys = list(self.tool_lib.tools.keys())
        idx_a = keys.index(tid_a)
        idx_b = keys.index(tid_b)
        keys[idx_a], keys[idx_b] = keys[idx_b], keys[idx_a]
        new_tools = {k: self.tool_lib.tools[k] for k in keys}
        self.tool_lib.tools = new_tools
        self.tool_lib.save()
        target_row = row_b
        self._refresh_table()
        if target_row < self.table.rowCount():
            self.table.setCurrentCell(target_row, 0)

    def _copy_tool_to_clipboard(self, tool):
        """Copie Tool type + Rpm + SetFeedTechnology de l'outil dans le clipboard."""
        text = (
            f"Tool type=\"{tool.article_nr}\"\n"
            f"newRpm {tool.rpm}\n"
            f"SetFeedTechnology(approach={tool.feed_approach} "
            f"finishing={tool.feed_finishing} plunge={tool.feed_plunge} "
            f"ramp={tool.feed_ramp} roughing={tool.feed_roughing})")
        QApplication.clipboard().setText(text)
        # Notification in statusbar (if available via signal or parent)
        if hasattr(self.parent(), '_log_action'):
            self.parent()._log_action(f"Outil copié: {tool.name}")

    def _on_import_tools(self):
        """Importe un fichier tools.json."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Importer tools.json", "",
            "JSON (*.json);;Tous (*)")
        if not path:
            return
        import json
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # Format export: {'version', 'last_modified', 'tools': {...}}
            # ou dict d'outils à plat
            tools_data = data.get('tools', data)
            count = 0
            skipped = []
            for tid, tdata in tools_data.items():
                if not isinstance(tdata, dict):
                    continue
                try:
                    self.tool_lib.tools[tid] = Tool(tdata)
                    count += 1
                except Exception:
                    skipped.append(tid)
            self.tool_lib.save()
            self._refresh_table()
            msg = f"{count} outil(s) importé(s) depuis {path}"
            if skipped:
                msg += f"\nIgnoré(s): {', '.join(skipped)}"
            QMessageBox.information(self, "Import", msg)
        except Exception as e:
            QMessageBox.warning(
                self, "Erreur", f"Impossible d'importer: {e}")

    def _on_export_tools(self):
        """Exporte tools.json vers un fichier choisi."""
        src_path = self.tool_lib.filepath
        path, _ = QFileDialog.getSaveFileName(
            self, "Exporter tools.json", "tools.json",
            "JSON (*.json);;Tous (*)")
        if not path:
            return
        import shutil
        try:
            shutil.copy2(src_path, path)
            QMessageBox.information(
                self, "Export", f"Tools exporté vers {path}")
        except Exception as e:
            QMessageBox.warning(
                self, "Erreur", f"Impossible d'exporter: {e}")
