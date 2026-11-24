"""
Colonne 3: Panneau éditeur DXF complet.
Import/export DXF, outils de dessin, calques, picking coordonnées.
Centre+dimensions form bar, détection centres, circle detection.
"""

from collections import OrderedDict

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFileDialog,
    QFrame, QCheckBox, QSizePolicy
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QTransform

from src.gui.dxf.dxf_canvas import DxfCanvas
from src.gui.widgets import SpinCote, etiquette_unite


class _NoScrollSpin(SpinCote):
    """Petit champ de cote pour le panneau DXF."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMaximumWidth(70)
        self.setMaximumHeight(24)
        self.setRange(-9999, 9999)


class _OngletCalque(QWidget):
    """Onglet d'un calque: son NOM et son ŒIL.

    Le nom déplie la boîte à outils du calque (et la replie si elle
    l'était déjà); l'œil montre ou masque son contenu sur le canvas.
    Deux gestes distincts sur un même bouton — la convention de la
    liste d'opérations."""

    #: le calque a été activé (ou refermé) — clic sur le nom
    active = Signal(str)
    #: la visibilité a changé — clic sur l'œil
    visibilite = Signal(str, bool)

    def __init__(self, cle: str, nom: str, couleur: str,
                 visible: bool = True, parent=None):
        super().__init__(parent)
        from src.gui.icons import get_button_icon
        self.cle = cle
        self.couleur = couleur
        self._ouvert = False
        self._visible = visible

        ligne = QHBoxLayout(self)
        ligne.setContentsMargins(0, 0, 0, 0)
        ligne.setSpacing(0)

        self.bouton_nom = QPushButton(nom)
        self.bouton_nom.setCheckable(True)
        self.bouton_nom.setCursor(Qt.CursorShape.PointingHandCursor)
        self.bouton_nom.setToolTip(
            f"Boîte à outils du calque {nom} (clic pour ouvrir ou "
            f"refermer)")
        self.bouton_nom.clicked.connect(
            lambda: self.active.emit(self.cle))
        ligne.addWidget(self.bouton_nom)

        self.bouton_oeil = QPushButton("")
        self.bouton_oeil.setFixedWidth(22)
        self.bouton_oeil.setCheckable(True)
        self.bouton_oeil.setChecked(visible)
        self.bouton_oeil.setCursor(Qt.CursorShape.PointingHandCursor)
        self.bouton_oeil.setToolTip(f"Montrer ou masquer {nom}")
        self.bouton_oeil.setIcon(get_button_icon("eye", 13))
        self.bouton_oeil.toggled.connect(self._on_oeil)
        ligne.addWidget(self.bouton_oeil)

        self.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Fixed)
        self._appliquer_style()

    def _on_oeil(self, coche: bool):
        self._visible = coche
        self._appliquer_style()
        self.visibilite.emit(self.cle, coche)

    def set_ouvert(self, ouvert: bool):
        self._ouvert = bool(ouvert)
        self.bouton_nom.setChecked(self._ouvert)
        self._appliquer_style()

    def est_ouvert(self) -> bool:
        return self._ouvert

    def est_visible(self) -> bool:
        return self._visible

    def _appliquer_style(self):
        teinte = self.couleur if self._visible else "#6c7086"
        souligne = (f"border-bottom: 2px solid {self.couleur};"
                    if self._ouvert else
                    "border-bottom: 2px solid transparent;")
        self.bouton_nom.setStyleSheet(
            f"QPushButton {{ font-size: 11px; padding: 3px 7px; "
            f"color: {teinte}; background: transparent; "
            f"border: none; {souligne} border-radius: 0; }}"
            f"QPushButton:hover {{ background: #313244; }}"
            f"QPushButton:checked {{ background: #1e1e2e; }}")
        self.bouton_oeil.setStyleSheet(
            f"QPushButton {{ padding: 2px; border: none; "
            f"background: transparent; {souligne} border-radius: 0; }}"
            f"QPushButton:hover {{ background: #313244; }}")


class DxfEditorPanel(QWidget):
    """Panneau complet de la colonne 3: éditeur DXF."""

    coordinate_picked = Signal(float, float)
    #: des entités viennent d'être choisies au canvas (Suppr les vise)
    entites_choisies = Signal()
    circles_detected = Signal(list)  # [{x, y, radius}, ...]
    selected_centers = Signal(list)  # centres des entités sélectionnées
    #: un canvas vient d'être créé (nouvel onglet): ce qui s'y
    #: branche ailleurs doit le faire pour LUI aussi
    canvas_cree = Signal(object)
    #: des opérations à ajouter, demandées par les faces choisies de
    #: la pièce STEP (vue 3D)
    usinage_step = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active_shape = None
        self._expert_mode = False
        self._dxf_dir = ""  # dossier DXF courant
        self._dxf_files = []  # liste des .dxf dans le dossier
        self._dxf_index = -1  # index du fichier DXF chargé
        self._current_dxf_path = ""  # chemin complet du DXF chargé
        self._setup_ui()
        self._connect_signals()

    def set_default_dxf_dir(self, path: str):
        """Définit le dossier DXF par défaut (depuis settings)."""
        if path:
            self._dxf_dir = path

    #: (clé, nom affiché, couleur, visible au départ). L'ordre est
    #: celui de la barre.
    CALQUES = (
        ('dxf',     "DXF",     "#cdd6f4", True),
        ('ope',     "Opé",     "#89b4fa", True),
        ('drawn',   "Dessin",  "#f9e2af", True),
        ('texte',   "Annot.",  "#a6e3a1", True),
        ('centres', "Centres", "#f38ba8", False),
        ('smb',     "SMB",     "#94e2d5", True),
    )

    def set_expert_mode(self, enabled: bool):
        self._expert_mode = enabled

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # ----- Barre d'outils supérieure -----
        # Style compact pour boutons toggle
        _tb = ("QPushButton { font-size: 11px; padding: 2px 6px; "
               "border-radius: 3px; }"
               "QPushButton:checked { background: #45475a; "
               "border: 1px solid #89b4fa; }"
               "QPushButton:hover { background: #313244; }")

        toolbar_top = QHBoxLayout()
        toolbar_top.setSpacing(2)

        def _compressible(widget):
            """Rendu tel quel: un bouton garde sa taille.

            La barre entière défile dans son cadre (voir
            `_barre_defilante`); écraser les boutons un par un les
            réduisait à ZÉRO pixel — ils disparaissaient."""
            return widget

        from src.gui.icons import get_icon
        # Zoom Fit — dans la barre du BAS, avec Importer et Exporter
        self.zoom_fit_btn = QPushButton("Fit")
        self.zoom_fit_btn.setIcon(get_icon("zoom_fit", 16))
        self.zoom_fit_btn.setStyleSheet(_tb)
        self.zoom_fit_btn.setToolTip("Ajuster la vue [F]")
        self.zoom_fit_btn.clicked.connect(self._on_fit)

        # Exporter ne regarde PAS un calque en particulier: le
        # formulaire demande lesquels sortir. Barre du bas aussi.
        self.export_btn = QPushButton("Exporter")
        self.export_btn.setIcon(get_icon("export", 16))
        self.export_btn.setStyleSheet(_tb)
        self.export_btn.setToolTip(
            "Sortir le dessin: calques au choix, couleurs, "
            "format (DXF, SVG, PDF, PNG)")
        self.export_btn.clicked.connect(self._on_export)

        # Onglets de calques: le NOM sort la boîte à outils du
        # calque, l'ŒIL montre ou masque son contenu. Deux gestes
        # distincts sur un même bouton, comme les lignes d'opérations.
        self._onglets_calque = {}
        for cle, nom, couleur, visible in self.CALQUES:
            onglet = _OngletCalque(cle, nom, couleur, visible)
            # nom et œil côte à côte, même en barre verticale
            onglet.setProperty('barre_garde_sens', True)
            onglet.active.connect(self._on_calque_active)
            onglet.visibilite.connect(self._on_calque_visible)
            toolbar_top.addWidget(onglet)
            self._onglets_calque[cle] = onglet

        toolbar_top.addStretch()

        # Navigation DXF: ◀ ▶
        self._prev_dxf_btn = QPushButton("◀")
        self._prev_dxf_btn.setMaximumWidth(28)
        self._prev_dxf_btn.setToolTip("DXF précédent dans le dossier")
        self._prev_dxf_btn.setStyleSheet(_tb)
        self._prev_dxf_btn.clicked.connect(self._on_prev_dxf)
        toolbar_top.addWidget(_compressible(self._prev_dxf_btn))

        self._next_dxf_btn = QPushButton("▶")
        self._next_dxf_btn.setMaximumWidth(28)
        self._next_dxf_btn.setToolTip("DXF suivant dans le dossier")
        self._next_dxf_btn.setStyleSheet(_tb)
        self._next_dxf_btn.clicked.connect(self._on_next_dxf)
        toolbar_top.addWidget(_compressible(self._next_dxf_btn))

        # Importer / Exporter / Effacer vivent dans l'onglet
        # « DXF to Op » (ils appartiennent au dessin, pas au canvas).
        # Les widgets restent créés — masqués — pour que les
        # raccourcis et le glisser-déposer gardent leurs poignées.
        self.import_btn = QPushButton("Importer")
        self.import_btn.clicked.connect(self._on_import)
        self.import_btn.setVisible(False)

        # Annotation: poser un repère sur le plan, puis le placer
        # aux flèches — c'est plus sûr qu'à la souris pour une cote
        self.text_btn = QPushButton("Texte")
        self.text_btn.setCheckable(True)
        self.text_btn.setToolTip(
            "Poser une annotation AU CLIC sur le dessin.\n"
            "F2 pour la cote, flèches pour la placer.")
        self.text_btn.setStyleSheet(_tb)
        self.text_btn.clicked.connect(
            lambda: self._on_draw_tool("texte"))
        toolbar_top.addWidget(_compressible(self.text_btn))

        # Texte GRAVÉ: pas un repère, un tracé. Il est vectorisé à la
        # pose et se grave comme un contour venu d'un DXF.
        self.texte_grave_btn = QPushButton("Texte gravé")
        self.texte_grave_btn.setCheckable(True)
        self.texte_grave_btn.setIcon(get_icon("engrave", 16))
        self.texte_grave_btn.setToolTip(
            "Poser un texte VECTORISÉ au clic: police du poste, "
            "hauteur de capitale en mm.\n"
            "Ce sont des contours, gravables comme un DXF.")
        self.texte_grave_btn.setStyleSheet(_tb)
        self.texte_grave_btn.clicked.connect(
            lambda: self._on_draw_tool("texte_grave"))
        toolbar_top.addWidget(_compressible(self.texte_grave_btn))

        # Pas des flèches: le même que TauDrive, et il se règle aussi
        # au clavier (Ctrl + haut/bas). Il vit dans la barre du BAS
        # du canvas (voir `_barre_du_bas`): une étiquette courte, un
        # champ étroit en gros chiffres — l'unité est sous-entendue,
        # tout est en millimètres ici, et « pas 1 mm » prenait la
        # place de trois boutons sans être plus lisible.
        self.pas_etiquette = QLabel("Pas")
        self.pas_etiquette.setStyleSheet(
            "color: #a6adc8; font-size: 11px; font-weight: bold;")
        self.pas_etiquette.setToolTip(
            "Pas des flèches, en mm: déplacement d'un appui.\n"
            "Maj + flèche: dix fois plus. Ctrl + haut/bas: changer "
            "de pas.")
        self.pas_spin = SpinCote()
        self.pas_spin.setRange(0.001, 100.0)
        self.pas_spin.setSingleStep(0.1)
        self.pas_spin.setValue(1.0)   # accordé au canvas plus bas
        self.pas_spin.setFixedWidth(58)
        self.pas_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pas_spin.setStyleSheet(
            "QDoubleSpinBox { font-size: 13px; font-weight: bold; "
            "padding: 1px 2px; }")
        self.pas_spin.setToolTip(self.pas_etiquette.toolTip())
        # Entrée dans le champ « Pas » rend le focus au dessin: les
        # flèches déplacent alors la sélection du pas qu'on vient de
        # taper (Ctrl+flèche depuis le dessin amène ici)
        self.pas_spin.lineEdit().returnPressed.connect(
            self._pas_valide_rend_le_focus)
        # gardée pour ce qui la référence, mais plus affichée
        self.pas_unite = etiquette_unite("mm")
        self.pas_unite.setVisible(False)

        # Vider tout le canvas: dessin, annotations, opérations,
        # brut. « Effacer » ne touchait que le dessin.
        self.clear_all_btn = QPushButton("Clear")
        self.clear_all_btn.setToolTip(
            "Vider TOUT le canvas: dessin, annotations, marqueurs "
            "d'opération et brut")
        self.clear_all_btn.setStyleSheet(_tb)
        self.clear_all_btn.clicked.connect(self._on_clear_all)
        toolbar_top.addWidget(_compressible(self.clear_all_btn))

        self.print_btn = QPushButton("Imprimer")
        self.print_btn.setToolTip(
            "Imprimer le canvas en A4 (PDF) avec échelle annotée")
        self.print_btn.clicked.connect(self._on_print_a4)
        toolbar_top.addWidget(_compressible(self.print_btn))

        self.clear_btn = QPushButton("Effacer")
        self.clear_btn.clicked.connect(self._on_clear)
        self.clear_btn.setVisible(False)

        _haut = QWidget()
        _haut.setLayout(toolbar_top)
        self._barre_haut_cadre = self._barre_defilante(_haut)
        layout.addWidget(self._barre_haut_cadre)

        # Une boîte à outils par calque, dépliée au clic sur son nom
        self._boites_calque = {}
        self._boites_conteneur = QWidget()
        _boites_lay = QVBoxLayout(self._boites_conteneur)
        _boites_lay.setContentsMargins(0, 0, 0, 0)
        _boites_lay.setSpacing(0)
        for cle, _nom, _couleur, _vis in self.CALQUES:
            boite = QWidget()
            rangee = QHBoxLayout(boite)
            rangee.setContentsMargins(2, 2, 2, 2)
            rangee.setSpacing(2)
            boite.setVisible(False)
            _boites_lay.addWidget(boite)
            self._boites_calque[cle] = (boite, rangee)
        self._boites_cadre = self._barre_defilante(
            self._boites_conteneur)
        layout.addWidget(self._boites_cadre)

        # ----- Barre d'outils dessin (masquable via Outils toggle) -----
        self._draw_toolbar_widget = QWidget()
        draw_tb_layout = QVBoxLayout(self._draw_toolbar_widget)
        draw_tb_layout.setContentsMargins(0, 0, 0, 0)
        draw_tb_layout.setSpacing(2)

        draw_toolbar = QHBoxLayout()
        draw_toolbar.setSpacing(2)

        # ── Groupe 1: Grille ──
        self.grid_cb = QCheckBox("Grille")
        self.grid_cb.setChecked(True)
        self.grid_cb.setStyleSheet("font-size: 11px;")
        draw_toolbar.addWidget(self.grid_cb)

        # Grid step éditable
        self.grid_spin = SpinCote()
        self.grid_spin.setRange(0.1, 100.0)
        self.grid_spin.setValue(1.0)
        self.grid_spin.setDecimals(1)
        self.grid_spin.setMaximumWidth(70)
        self.grid_spin.setMaximumHeight(22)
        self.grid_spin.valueChanged.connect(self._on_grid_step_changed)
        draw_toolbar.addWidget(self.grid_spin)
        self.grid_unite = etiquette_unite("mm")
        draw_toolbar.addWidget(self.grid_unite)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.VLine)
        sep1.setFixedWidth(1)
        draw_toolbar.addWidget(sep1)

        # ── Groupe 2: Modes interactifs ──
        self.pick_btn = QPushButton("XY")
        self.pick_btn.setIcon(get_icon("pick_point", 16))
        self.pick_btn.setCheckable(True)
        self.pick_btn.setToolTip("Picker coordonnées X/Y")
        self.pick_btn.setStyleSheet(_tb)
        self.pick_btn.toggled.connect(self._on_pick_toggled)
        draw_toolbar.addWidget(self.pick_btn)

        # « Sél. » n'existe plus: sélectionner EST le comportement
        # par défaut du canvas. Le bouton reste créé, masqué, le
        # temps que les modes de dessin cessent d'y toucher.
        self.select_btn = QPushButton("Sél.")
        self.select_btn.setCheckable(True)
        self.select_btn.setChecked(True)
        self.select_btn.setVisible(False)
        self.select_btn.setToolTip(
            "Sélectionner entités (clic ou rectangle glissé)")
        self.select_btn.setStyleSheet(_tb)
        self.select_btn.toggled.connect(self._on_select_toggled)

        self.to_points_btn = QPushButton("→ Pts")
        self.to_points_btn.setToolTip(
            "Envoyer centres sélectionnés vers l'opération")
        self.to_points_btn.setStyleSheet(_tb)
        self.to_points_btn.setEnabled(False)
        self.to_points_btn.clicked.connect(self._on_send_selected_points)
        draw_toolbar.addWidget(self.to_points_btn)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.VLine)
        sep2.setFixedWidth(1)
        draw_toolbar.addWidget(sep2)

        # ── Groupe 3: Outils de dessin ──
        self.draw_buttons = {}
        draw_tools = [
            ("line", "Ligne"),
            ("circle", "Cercle"),
            ("rect", "Rectangle"),
            ("bezier", "Polyligne"),
        ]
        for tool_id, label in draw_tools:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setStyleSheet(_tb)
            btn.clicked.connect(
                lambda checked, t=tool_id: self._on_draw_tool(t))
            draw_toolbar.addWidget(btn)
            self.draw_buttons[tool_id] = btn

        sep3 = QFrame()
        sep3.setFrameShape(QFrame.Shape.VLine)
        sep3.setFixedWidth(1)
        draw_toolbar.addWidget(sep3)

        # ── Groupe 4: Mesure et génération ──
        self.ruler_btn = QPushButton("Règle")
        self.ruler_btn.setIcon(get_icon("ruler", 16))
        self.ruler_btn.setCheckable(True)
        self.ruler_btn.setToolTip("Mesurer une distance (clic → clic)")
        self.ruler_btn.setStyleSheet(_tb)
        self.ruler_btn.toggled.connect(self._on_ruler_toggled)
        draw_toolbar.addWidget(self.ruler_btn)

        # L'empreinte de l'opération courante, en entités du dessin:
        # à déplacer, mettre à la cote, retoucher — puis à reprendre
        # par une opération
        self.ope_dessin_btn = QPushButton("Opé → dessin")
        self.ope_dessin_btn.setIcon(get_icon("dxf", 16))
        self.ope_dessin_btn.setStyleSheet(_tb)
        self.ope_dessin_btn.setToolTip(
            "Pose l'empreinte de l'opération sélectionnée sur le "
            "calque Dessin: rectangle, cercles ou contours, "
            "sélectionnés.\nDéplacez-les, mettez-les à la cote (F2), "
            "retouchez-les, puis reprenez-les dans une opération "
            "(« Depuis la sélection du canvas », « Appliquer les "
            "courbes sélectionnées »).")
        self.ope_dessin_btn.clicked.connect(self._on_ope_vers_dessin)
        draw_toolbar.addWidget(self.ope_dessin_btn)

        # Accrochages objet: pendant un tracé, une mesure ou un
        # pointage, le curseur TOMBE sur les points du dessin
        self.accroche_btn = QPushButton("Accroch.")
        self.accroche_btn.setCheckable(True)
        self.accroche_btn.setChecked(True)
        self.accroche_btn.setStyleSheet(
            _tb + " QPushButton:checked { color: #a6e3a1; }")
        self.accroche_btn.setToolTip(
            "Accrochages objet pendant un tracé, la règle ou le "
            "pointage XY:\n□ extrémité · ✕ intersection · ○ centre · "
            "◇ quadrant · △ milieu · ⊥ perpendiculaire · ⧖ proche.\n"
            "Décoché: la grille et les centres marqués seulement.")
        self.accroche_btn.toggled.connect(self._on_accrochages)
        draw_toolbar.addWidget(self.accroche_btn)

        # Ortho / angles imposés (F8): le trait tourne par pas
        self.ortho_btn = QPushButton("Ortho")
        self.ortho_btn.setCheckable(True)
        self.ortho_btn.setStyleSheet(
            _tb + " QPushButton:checked { color: #fab387; }")
        self.ortho_btn.setToolTip(
            "Ortho (F8): le trait qu'on trace part à 0°, 90°, 180°, 270° "
            "du point précédent. Clic droit: 45°, 30° ou 15°.")
        self._ortho_pas_choisi = 90.0
        self.ortho_btn.toggled.connect(self._on_ortho)
        self.ortho_btn.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.ortho_btn.customContextMenuRequested.connect(
            self._menu_ortho)
        draw_toolbar.addWidget(self.ortho_btn)

        # Retouches du dessin (CADCraft / VectorCraft, MIT)
        from PySide6.QtWidgets import QMenu
        self.retouches_btn = QPushButton("Retouches")
        self.retouches_btn.setStyleSheet(_tb)
        self.retouches_btn.setToolTip(
            "Nettoyer, décaler, arrondir, chanfreiner, unir… les "
            "tracés sélectionnés; vectoriser une image.")
        menu = QMenu(self.retouches_btn)
        self._actions_retouche = {}

        #: les retouches en BARRE D'OUTILS (boîte Dessin): un bouton
        #: chacune, None = un trait entre deux familles
        self._boutons_retouche = {}
        self._ordre_retouches = []
        courts = {'nettoyer': "Nettoyer", 'decaler': "Décaler",
                  'conge': "Congé", 'chanfrein': "Chanfrein",
                  'arcs': "Arcs", 'formes': "Formes",
                  'couper': "Couper", 'depart': "Départ",
                  'ajuster': "Ajuster", 'prolonger': "Prolonger",
                  'region': "Région", 'points': "Points",
                  'reseau_rect': "Réseau ▦", 'reseau_polaire': "Réseau ◎",
                  'mesurer': "Mesurer", 'unir': "Unir",
                  'soustraire': "Soustraire", 'intersection': "Inter.",
                  'exclure': "Exclure", 'image': "Image…"}

        def _action(cle, texte, bulle, fonction):
            a = menu.addAction(texte)
            a.setToolTip(bulle)
            a.triggered.connect(lambda _c=False: fonction())
            self._actions_retouche[cle] = a
            b = QPushButton(courts.get(cle, texte))
            b.setStyleSheet(_tb)
            b.setToolTip(f"{texte}\n{bulle}")
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(lambda _c=False: fonction())
            self._boutons_retouche[cle] = b
            self._ordre_retouches.append(cle)
            return a

        _separer = menu.addSeparator

        def _trait():
            _separer()
            self._ordre_retouches.append(None)
        menu.addSeparator = _trait

        _action('nettoyer', "Nettoyer (doublons, jonctions)",
                "Retire les traits en double ou couverts par un autre, "
                "joint les morceaux bout à bout (contours fermés).",
                self.nettoyer_dessin)
        menu.addSeparator()
        _action('decaler', "Décaler…",
                "Une copie décalée des tracés sélectionnés (+ dehors, "
                "− dedans).", lambda: self.retoucher('decaler'))
        _action('conge', "Congé aux angles…",
                "Arrondit les angles (saillants: ce qu'une fraise ne "
                "peut pas atteindre dans une poche).",
                lambda: self.retoucher('conge'))
        _action('chanfrein', "Chanfrein aux angles…",
                "Coupe les angles d'une distance le long de chaque côté.",
                lambda: self.retoucher('chanfrein'))
        _action('arcs', "Lisser en arcs…",
                "Refait les tracés en droites et arcs tangents: un "
                "contour en escalier devient lisse, un cercle en "
                "cordes redevient un cercle.",
                lambda: self.retoucher('arcs'))
        _action('formes', "Reconnaître les formes…",
                "Les polylignes qui sont des cercles, rectangles, "
                "ellipses, droites ou arcs deviennent ces entités "
                "exactes (un cercle reconnu est un perçage).",
                lambda: self.retoucher('formes'))
        menu.addSeparator()
        for cle, bulle in (
                ('couper', "Cliquez sur un tracé: il est coupé là (un "
                           "contour fermé s'ouvre)."),
                ('depart', "Cliquez sur un contour fermé: il commence "
                           "là — l'outil y entrera."),
                ('ajuster', "Cliquez sur la partie d'un tracé à ôter "
                            "entre deux croisements."),
                ('prolonger', "Cliquez près du bout d'un tracé: il "
                              "avance jusqu'au trait suivant."),
                ('region', "Cliquez DANS une zone fermée par des traits "
                           "(même croisés): son contour, prêt pour une "
                           "poche.")):
            from src.gui.dxf.dxf_canvas import DxfCanvas as _C
            _action(cle, _C.NOMS_OUTILS_CLIC[cle], bulle,
                    lambda c=cle: self.armer_outil(c))
        menu.addSeparator()
        _action('points', "Points le long d'un tracé…",
                "Des repères (cercles) répartis sur les tracés "
                "sélectionnés: « DXF to Op » en fait des perçages.",
                lambda: self.retoucher('points'))
        _action('reseau_rect', "Réseau rectangulaire…",
                "Des copies de la sélection en lignes et colonnes.",
                lambda: self.retoucher('reseau_rect'))
        _action('reseau_polaire', "Réseau circulaire…",
                "Des copies de la sélection autour d'un centre.",
                lambda: self.retoucher('reseau_polaire'))
        _action('mesurer', "Mesurer la sélection",
                "Longueur totale, contours fermés, périmètre, aire, "
                "emprise.", lambda: self.mesurer())
        menu.addSeparator()
        from src.core.retouche import OPERATIONS_BOOLEENNES
        for op, texte in OPERATIONS_BOOLEENNES.items():
            _action(op, texte, "Contours fermés sélectionnés: chaque "
                    "entité est une surface.",
                    lambda o=op: self.booleen(o))
        menu.addSeparator()
        _action('image', "Vectoriser une image…",
                "PNG, JPG, BMP, GIF, TIFF → contours ou lignes médianes.",
                lambda: self.vectoriser_image())
        menu.setToolTipsVisible(True)
        self.retouches_btn.setMenu(menu)
        draw_toolbar.addWidget(self.retouches_btn)

        # Le dessin paramétrique: les contraintes (boîte Dessin)
        from src.core import contraintes as _cg
        self.contraintes_btn = QPushButton("Contraintes")
        self.contraintes_btn.setStyleSheet(_tb)
        self.contraintes_btn.setToolTip(
            "Dessin paramétrique: horizontale, verticale, parallèles, "
            "perpendiculaires, égales, cotes pilotantes (longueur, "
            "distance, rayon), confondus, concentriques, tangente, fixe. "
            "Le dessin bouge le moins possible pour les tenir; déplacer "
            "un sommet aux poignées les garde.")
        menu_c = QMenu(self.contraintes_btn)
        self._actions_contraintes = {}
        for genre, nom in _cg.NOMS.items():
            a = menu_c.addAction(nom)
            a.triggered.connect(
                lambda _c=False, g=genre: self.armer_outil(f"contrainte:{g}"))
            self._actions_contraintes[genre] = a
        menu_c.addSeparator()
        a = menu_c.addAction("Résoudre à nouveau")
        a.triggered.connect(lambda _c=False: self.canvas.resoudre_contraintes())
        self._actions_contraintes['resoudre'] = a
        a = menu_c.addAction("Montrer les symboles")
        a.setCheckable(True)
        a.setChecked(True)
        a.toggled.connect(lambda on: [c.montrer_glyphes(on) for c in
                                      self._canvas_par_onglet.values()])
        self._actions_contraintes['symboles'] = a
        a = menu_c.addAction("Effacer les contraintes")
        a.triggered.connect(lambda _c=False: self.canvas.effacer_contraintes())
        self._actions_contraintes['effacer'] = a
        self.contraintes_btn.setMenu(menu_c)
        draw_toolbar.addWidget(self.contraintes_btn)

        # Les cotes d'un plan (boîte Annotations)
        from src.core import cotation as _ct
        self.cotes_btn = QPushButton("Cotes")
        self.cotes_btn.setStyleSheet(_tb)
        self.cotes_btn.setToolTip(
            "Coter le dessin: linéaire, alignée, rayon, diamètre, angle "
            "— les points s'accrochent au dessin; exportées et imprimées "
            "avec les annotations.")
        menu_cotes = QMenu(self.cotes_btn)
        self._actions_cotes = {}
        aides = {'cote_lin': "deux points, puis le placement (horizontale "
                             "ou verticale selon où l'on pose)",
                 'cote_ali': "deux points, puis le placement",
                 'cote_ray': "un clic sur un cercle ou un arc",
                 'cote_dia': "un clic sur un cercle ou un arc",
                 'cote_ang': "le sommet, puis un point sur chaque côté"}
        for cle, nom in _ct.GENRES.items():
            a = menu_cotes.addAction(nom)
            a.setToolTip(aides[cle])
            a.triggered.connect(lambda _c=False, k=cle: self.armer_outil(k))
            self._actions_cotes[cle] = a
        menu_cotes.addSeparator()
        a = menu_cotes.addAction("Hauteur du texte des cotes…")
        a.triggered.connect(lambda _c=False: self.retoucher('hauteur_cotes'))
        self._actions_cotes['hauteur'] = a
        menu_cotes.setToolTipsVisible(True)
        self.cotes_btn.setMenu(menu_cotes)
        draw_toolbar.addWidget(self.cotes_btn)

        # « Nettoyer » aussi dans la boîte DXF: c'est là qu'on regarde
        # un fichier importé
        self.nettoyer_btn = QPushButton("Nettoyer")
        self.nettoyer_btn.setStyleSheet(_tb)
        self.nettoyer_btn.setToolTip(
            "Traits en double ou couverts retirés, morceaux joints en "
            "contours — sur la sélection, ou tout le dessin visible.")
        self.nettoyer_btn.clicked.connect(lambda _c=False:
                                          self.nettoyer_dessin())
        draw_toolbar.addWidget(self.nettoyer_btn)

        draw_toolbar.addStretch()

        draw_tb_layout.addLayout(draw_toolbar)

        # Ajouter la toolbar de dessin au layout principal (masquée par défaut)
        # L'ancienne barre de dessin est vidée par
        # _ranger_outils_par_calque: son conteneur reste, invisible,
        # pour ne pas casser ce qui le référence.
        self._draw_toolbar_widget.setVisible(False)
        layout.addWidget(self._draw_toolbar_widget)

        # Label mesure règle
        self._ruler_label = QLabel("")
        self._ruler_label.setStyleSheet(
            "color: #f9e2af; font-size: 12px; font-weight: bold;")
        self._ruler_label.setVisible(False)
        layout.addWidget(self._ruler_label)

        # ----- Canvas DXF: un par ONGLET de programme -----
        # Le dessin appartient au programme, pas à la fenêtre: passer
        # d'un onglet à l'autre gardait le dessin du précédent, et
        # importer un DXF écrasait celui de l'onglet d'à côté.
        from PySide6.QtWidgets import QStackedWidget
        self._canvas_pile = QStackedWidget()
        self._canvas_par_onglet = {}
        self._cle_onglet = "P1"
        self._canvas_par_onglet[self._cle_onglet] = self._neuf_canvas()
        self._canvas_pile.addWidget(
            self._canvas_par_onglet[self._cle_onglet])
        # Le champ « pas » existe avant le canvas: on les accorde ici
        self.pas_spin.setValue(DxfCanvas.NUDGE_DEFAULT)
        # ── Boutons propres aux boîtes Annot., Centres et SMB ──
        from src.gui.icons import get_button_icon as _ic

        def _bascule(texte, coche, bulle, couleur, action):
            b = QPushButton(texte)
            b.setCheckable(True)
            b.setChecked(coche)
            b.setToolTip(bulle)
            b.setStyleSheet(
                _tb + f" QPushButton:checked {{ color: {couleur}; }}")
            b.toggled.connect(action)
            return b

        # Les opérations et les centres se montrent par l'ŒIL de leur
        # onglet; ces deux-là restent pour ce que l'œil ne dit pas.
        self.show_all_ops_btn = _bascule(
            "Opé", True,
            "Marqueurs d'opération, aperçu prog. externe, parcours",
            "#89b4fa", self._on_show_all_ops_toggled)
        self.show_all_ops_btn.setVisible(False)   # doublon de l'œil

        # Étiquettes et légende ÉTEINTES au départ: sur un dessin
        # chargé d'opérations, elles couvraient le tracé
        self.show_labels_btn = _bascule(
            "Étiquettes", False,
            "Étiquettes (n° + Pz) des marqueurs d'opération",
            "#f9e2af",
            lambda c: self.canvas.set_op_labels_visible(c))

        self.show_legend_btn = _bascule(
            "Légende", False,
            "Légende des couleurs d'outils, en bas du dessin",
            "#a6e3a1",
            lambda c: self.canvas.set_legend_visible(c))

        self.show_centers_btn = _bascule(
            "Marqueurs", False,
            "Marqueurs roses des centres détectés. "
            "La détection fonctionne même marqueurs masqués.",
            "#f38ba8",
            lambda c: self.canvas.set_centers_visible(c))

        self.resize_btn = QPushButton(" F2 · cote")
        self.resize_btn.setIcon(_ic("ruler", 15))
        self.resize_btn.setStyleSheet(_tb)
        self.resize_btn.setToolTip(
            "Mettre la sélection à la cote (F2): dimensions, "
            "pourcentages, position du centre")
        self.resize_btn.clicked.connect(self._on_redimensionner)

        self.dup_btn = QPushButton(" Dupliquer")
        self.dup_btn.setIcon(_ic("duplicate", 15))
        self.dup_btn.setStyleSheet(_tb)
        self.dup_btn.setToolTip(
            "Copier la sélection, décalée d'un pas")
        self.dup_btn.clicked.connect(self._on_dupliquer)

        # (sans icône: la même pour grouper et dégrouper ne disait
        # rien, et la barre doit tenir dans la colonne)
        self.grouper_btn = QPushButton("Grouper")
        self.grouper_btn.setStyleSheet(_tb)
        self.grouper_btn.setToolTip(
            "Réunir les entités sélectionnées (Ctrl+G).\n"
            "Un groupe se prend, se déplace et s'efface d'un bloc: "
            "un dessin importé en trente polylignes ne se reprend "
            "plus une par une.")
        self.grouper_btn.clicked.connect(self._on_grouper)

        self.degrouper_btn = QPushButton("Dégrouper")
        self.degrouper_btn.setStyleSheet(_tb)
        self.degrouper_btn.setToolTip(
            "Défaire les groupes de la sélection (Ctrl+Maj+G)")
        self.degrouper_btn.clicked.connect(self._on_degrouper)

        # Centrer: la SÉLECTION vient en 0,0 et tout le dessin suit —
        # le ® du coin n'entre pas dans le calcul, mais reste dans le
        # dessin, à sa place. Sans sélection: le dessin entier.
        self.centrer_btn = QPushButton(" Centrer")
        self.centrer_btn.setIcon(_ic("pick_point", 15))
        self.centrer_btn.setStyleSheet(_tb)
        self.centrer_btn.setToolTip(
            "Ramener en X0 Y0 le centre de la sélection — tout le "
            "dessin se déplace avec elle.\nExemple: tout sélectionner "
            "sauf le ®: le logo se centre, le ® suit et reste dans "
            "le dessin.\nSans sélection: le centre du dessin entier.\n"
            "Alt+W: la sélection SEULE vient en 0,0, le reste du dessin "
            "garde sa place.")
        self.centrer_btn.clicked.connect(self._on_centrer)

        # Miroir: on grave généralement le miroir du dessin
        # (« ↔ » et « ↕ » seuls: la barre doit tenir dans la colonne)
        _tm = _tb + ("QPushButton { font-size: 14px; font-weight: bold; "
                     "padding: 0px 6px; }")
        self.miroir_h_btn = QPushButton("↔")
        self.miroir_h_btn.setStyleSheet(_tm)
        self.miroir_h_btn.setToolTip(
            "Miroir gauche ↔ droite de la sélection (axe vertical), "
            "sur place — la sélection ne change pas de centre.")
        self.miroir_h_btn.clicked.connect(
            lambda: self._on_miroir('vertical'))
        self.miroir_v_btn = QPushButton("↕")
        self.miroir_v_btn.setStyleSheet(_tm)
        self.miroir_v_btn.setToolTip(
            "Miroir haut ↕ bas de la sélection (axe horizontal), "
            "sur place.")
        self.miroir_v_btn.clicked.connect(
            lambda: self._on_miroir('horizontal'))

        self.del_btn = QPushButton(" Supprimer")
        self.del_btn.setIcon(_ic("delete", 15))
        self.del_btn.setStyleSheet(_tb)
        self.del_btn.setToolTip("Supprimer la sélection (Suppr)")
        self.del_btn.clicked.connect(
            lambda: self.canvas._delete_selected())

        self.centres_ops_btn = QPushButton(" DXF to Op")
        self.centres_ops_btn.setIcon(_ic("pattern", 15))
        self.centres_ops_btn.setStyleSheet(_tb)
        self.centres_ops_btn.setToolTip(
            "Ouvrir l'onglet qui transforme les centres en opérations")
        self.centres_ops_btn.clicked.connect(self._on_aller_dxf_to_op)

        self.smb_btn = QPushButton(" Symboles")
        self.smb_btn.setIcon(_ic("dxf", 15))
        self.smb_btn.setStyleSheet(_tb)
        self.smb_btn.setToolTip(
            "Ouvrir la bibliothèque de symboles TypeEdit")
        self.smb_btn.clicked.connect(self._on_aller_symboles)

        self._ranger_outils_par_calque()
        self._ajuster_hauteur_barres()

        # ----- Bandeau: « centrer le dessin en 0 ? » -----
        # Un bandeau et non une boîte modale: l'import ne s'arrête
        # pas, et rien n'attend un clic qui, sans écran, ne vient
        # jamais.
        self._bandeau_centrage = QFrame()
        self._bandeau_centrage.setStyleSheet(
            "QFrame { background: #313244; border: 1px solid #45475a; "
            "border-radius: 4px; }")
        bandeau = QHBoxLayout(self._bandeau_centrage)
        bandeau.setContentsMargins(8, 3, 8, 3)
        self._bandeau_texte = QLabel("")
        self._bandeau_texte.setStyleSheet("color: #cdd6f4;")
        bandeau.addWidget(self._bandeau_texte, stretch=1)
        self._bandeau_retenir = QCheckBox("retenir")
        self._bandeau_retenir.setToolTip(
            "Retenir ce choix pour les prochains imports "
            "(modifiable dans Paramètres).")
        bandeau.addWidget(self._bandeau_retenir)
        self._bandeau_centrer = QPushButton("Centrer en 0")
        self._bandeau_centrer.setMaximumHeight(22)
        self._bandeau_centrer.clicked.connect(
            lambda: self._repondre_centrage(True))
        bandeau.addWidget(self._bandeau_centrer)
        self._bandeau_laisser = QPushButton("Laisser")
        self._bandeau_laisser.setMaximumHeight(22)
        self._bandeau_laisser.clicked.connect(
            lambda: self._repondre_centrage(False))
        bandeau.addWidget(self._bandeau_laisser)
        self._bandeau_centrage.hide()
        layout.addWidget(self._bandeau_centrage)

        # Les imports du dessin, un onglet chacun — la même barre
        # au-dessus du Canva 3D (voir `vue_3d`)
        from src.gui.dxf.barre_imports import lire_historique
        #: les onglets d'imports fermés, le plus récent d'abord (100)
        self._imports_fermes = lire_historique()
        self._barres_imports = []
        self.barre_imports = self._neuve_barre_imports()
        # avec Importer / Exporter au bout de la barre
        self.bandeau_imports = self._bandeau(self.barre_imports)
        layout.addWidget(self.bandeau_imports)

        # 2D (le canvas de l'onglet) ou 3D (la vue en volume)
        self._pile_vues = QStackedWidget()
        self._pile_vues.addWidget(self._canvas_pile)
        self._canvas3d = None
        self._modeles_3d = {}          # (chemin, date, axe) -> Modele3D
        self._axe_3d = 'auto'
        self._brouillon_3d = None
        self._3d_montree = False
        self._sims_3d = OrderedDict()  # clé du code -> simulation
        layout.addWidget(self._pile_vues, stretch=1)

        # ----- Barre du bas: les gestes de tous les jours -----
        # Fit, Importer, Exporter, Grouper, Dégrouper et le pas sont
        # là quel que soit le calque ouvert en haut: on ne va pas
        # chercher l'import dans la boîte DXF ni le groupement dans
        # la boîte Dessin. La ligne d'état (X Y, message) suit à
        # droite.
        self.coord_label = QLabel("X: 0.000  Y: 0.000")
        self.coord_label.setStyleSheet(
            "color: #a6adc8; font-family: 'Cascadia Code', monospace; "
            "font-size: 12px;")
        self.info_label = QLabel("")
        self.info_label.setStyleSheet("color: #a6adc8; font-size: 11px;")
        # un long message (survol, import) ne doit pas imposer sa
        # largeur au panneau, ni à la colonne: il se coupe
        self.info_label.setSizePolicy(QSizePolicy.Policy.Ignored,
                                      QSizePolicy.Policy.Preferred)
        self._barre_bas_cadre = self._barre_defilante(
            self._barre_du_bas())
        layout.addWidget(self._barre_bas_cadre)
        # la ligne d'état reste une ligne à elle: le message d'import
        # est long, les boutons ne doivent pas le pousser hors de vue
        etat = QHBoxLayout()
        etat.setContentsMargins(2, 0, 2, 0)
        etat.addWidget(self.coord_label)
        etat.addStretch()
        etat.addWidget(self.info_label)
        layout.addLayout(etat)
        self._ajuster_hauteur_barres()
        self._installer_barre_unique()

    def _installer_barre_unique(self) -> None:
        """Tous les outils du canvas sur UNE barre — les onglets des
        calques, les outils du calque ouvert, les gestes du bas —,
        placée par l'utilisateur en haut, en bas, à gauche ou à
        droite: la vue garde sa hauteur."""
        from src.gui.barre_outils import BarreOutils, installer
        lay = self.layout()
        cadres = (self._barre_haut_cadre, self._boites_cadre,
                  self._barre_bas_cadre)
        groupes = [c.takeWidget() for c in cadres]
        elements = []
        while lay.count():
            stretch = lay.stretch(0)
            elements.append((lay.takeAt(0), stretch))
        zone = QWidget()
        zl = QVBoxLayout(zone)
        zl.setContentsMargins(0, 0, 0, 0)
        zl.setSpacing(4)
        for item, stretch in elements:
            w = item.widget()
            if w is not None and w in cadres:
                w.setParent(None)
                w.deleteLater()
                continue
            if w is not None:
                zl.addWidget(w, stretch)
            elif item.layout() is not None:
                sous = item.layout()
                sous.setParent(None)
                zl.addLayout(sous, stretch)
            else:
                zl.addItem(item)
        barre = BarreOutils('canvas2d/barre_outils', self)
        for g in groupes:
            if g is not None:
                barre.ajouter(g)
        barre.terminer()
        self.barre_outils = barre
        self._zone_vue = zone
        # ce qui visait les trois cadres vise la barre
        self._barre_haut_cadre = self._boites_cadre = \
            self._barre_bas_cadre = barre
        # les boîtes des calques: leur layout est maintenant celui que
        # la barre a posé (même liste, il ne place plus rien)
        self._boites_calque = {cle: (boite, boite.layout())
                               for cle, (boite, _r)
                               in self._boites_calque.items()}
        barre.icones(self._table_icones())
        # « Importer »: le geste d'entrée, élargi (icône + nom)
        barre.elargir(self.import_btn, "Importer")
        barre.relier_etat(self.info_label)
        installer(self, lay, barre, zone)

    def _table_icones(self):
        """Chaque bouton de la barre, son icône et son nom (le nom
        s'affiche en ligne d'état au survol)."""
        d = self.draw_buttons
        r = self._boutons_retouche
        table = [
            (self.clear_all_btn, 'b_vider', "Vider tout le canvas"),
            (self._prev_dxf_btn, 'precedent', "DXF précédent"),
            (self._next_dxf_btn, 'suivant', "DXF suivant"),
            (self.print_btn, 'b_imprimer', "Imprimer (A4)"),
            (self.clear_btn, 'b_effacer', "Effacer le dessin"),
            (self.nettoyer_btn, 'b_nettoyer', "Nettoyer le dessin"),
            (self.show_labels_btn, 'b_etiquettes', "Étiquettes des opérations"),
            (self.show_legend_btn, 'b_legende', "Légende des outils"),
            (self.to_points_btn, 'b_vers_points', "Centres → points de l'opération"),
            (self.grid_cb, 'b_grille', "Grille"),
            (self.pick_btn, 'pick_point', "Pointer X / Y"),
            (self.accroche_btn, 'snap', "Accrochages"),
            (self.ortho_btn, 'b_ortho', "Ortho (F8)"),
            (d.get('line'), 'b_ligne', "Ligne"),
            (d.get('circle'), 'b_cercle', "Cercle"),
            (d.get('rect'), 'b_rectangle', "Rectangle"),
            (d.get('bezier'), 'b_polyligne', "Polyligne"),
            (self.text_btn, 'b_texte', "Texte"),
            (self.texte_grave_btn, 'engrave', "Texte gravé"),
            (self.ruler_btn, 'ruler', "Règle"),
            (self.ope_dessin_btn, 'dxf', "Opé → dessin"),
            (self.contraintes_btn, 'b_contraintes', "Contraintes"),
            (self.resize_btn, 'b_cote_selection', "Mettre à la cote (F2)"),
            (self.dup_btn, 'duplicate', "Dupliquer"),
            (self.del_btn, 'delete', "Supprimer"),
            (self.cotes_btn, 'b_cotes', "Cotes"),
            (self.show_centers_btn, 'b_marqueurs', "Marqueurs des centres"),
            (self.centres_ops_btn, 'pattern', "DXF to Op"),
            (self.smb_btn, 'dxf', "Symboles"),
            (self.zoom_fit_btn, 'zoom_fit', "Ajuster la vue (F)"),
            (getattr(self, 'vue3d_btn', None), 'b_cube', "Vue 3D"),
            (self.import_btn, 'import', "Importer un dessin"),
            (self.export_btn, 'export', "Exporter"),
            (getattr(self, 'centrer_import_cb', None), 'b_centrer_import',
             "Centrer à l'import"),
            (self.grouper_btn, 'b_grouper', "Grouper (Ctrl+G)"),
            (self.degrouper_btn, 'b_degrouper', "Dégrouper (Ctrl+Maj+G)"),
            (self.centrer_btn, 'pick_point', "Centrer en X0 Y0"),
            (self.miroir_h_btn, 'b_miroir_h', "Miroir gauche ↔ droite"),
            (self.miroir_v_btn, 'b_miroir_v', "Miroir haut ↕ bas"),
        ]
        noms = {'intersection': "Intersection",
                'reseau_rect': "Réseau rectangulaire",
                'reseau_polaire': "Réseau circulaire",
                'image': "Vectoriser une image"}
        for cle in self._ordre_retouches:
            if cle is not None and cle in r:
                table.append((r[cle], 'b_' + cle,
                              noms.get(cle, r[cle].text().rstrip(' ▦◎…'))))
        return table

    # ──── Vue 3D ────

    #: la fenêtre héberge la vue 3D dans un onglet à elle (« STEP
    #: 3D »): elle reçoit ici `voulu` — montrer l'onglet, ou revenir
    #: au Canva. Sans hôte, la vue prend la place du canvas.
    hote_3d = None
    #: le code SimPL à simuler (les cycles déroulés): () -> str
    fournisseur_code_3d = None

    def vue_3d(self):
        """La vue 3D, créée à la première demande."""
        if self._canvas3d is None:
            from src.gui.canvas3d import Canvas3D
            self._canvas3d = Canvas3D()
            self._canvas3d.retour_2d.connect(
                lambda: self.basculer_3d(False))
            self._canvas3d.actualiser_demande.connect(self.actualiser_3d)
            self._canvas3d.affichage_ops_change.connect(
                self._sur_affichage_ops_3d)
            self._canvas3d.oeil_op_change.connect(self.oeil_op_change.emit)
            self._canvas3d.panneau_ops.couleur_de_op = \
                self._couleur_outil_de_op
            self._canvas3d.panneau_ops.nom_outil_de_op = self._nom_outil_de_op
            self._canvas3d.axe_change.connect(self._sur_axe_3d)
            self._canvas3d.importer_demande.connect(self.importer_step_3d)
            self._canvas3d.usinage_demande.connect(self.usinage_step.emit)
            self._canvas3d.usinage3d_demande.connect(self.ouvrir_usinage_3d)
            self.barre_imports_3d = self._neuve_barre_imports()
            # au-dessus du 3D: les pièces 3D d'abord
            self.barre_imports_3d.pieces_d_abord = True
            self.bandeau_imports_3d = self._bandeau(self.barre_imports_3d)
            self._canvas3d.poser_barre_imports(self.bandeau_imports_3d)
            self.maj_onglets_imports()
            if self.hote_3d is None:
                self._pile_vues.addWidget(self._canvas3d)
        return self._canvas3d

    #: les fichiers que « Importer STEP… » propose
    FILTRE_STEP = "Pièce STEP (*.stp *.step *.STP *.STEP)"

    def importer_step_3d(self, chemin: str = "") -> bool:
        """« Importer STEP… » de la vue 3D: la pièce arrive au canvas
        (son dessin, comme par l'import du canvas) et dans la vue en
        volume. Rend vrai si elle est lue."""
        if not chemin:
            chemin, _ = QFileDialog.getOpenFileName(
                self, "Importer une pièce STEP", self._dxf_dir or "",
                self.FILTRE_STEP)
        if not chemin:
            return False
        rapport = self.charger_dessin(chemin)
        self.actualiser_3d()
        return rapport is not None

    def ouvrir_usinage_3d(self, executer: bool = True):
        """« Usinage 3D… »: la gamme de fraises de la pièce affichée.
        Acceptée, ses opérations partent au programme. Rend la fenêtre
        (les tests la pilotent sans l'ouvrir: executer=False)."""
        import os
        c3 = self._canvas3d
        if c3 is None or c3._modele is None or c3._piece_place is None:
            return None
        from src.gui.dialogs.usinage3d_dialog import DialogueUsinage3D
        source = getattr(self.canvas, '_source_3d', None) or {}
        nom = os.path.basename(source.get('chemin', '') or 'pièce')
        dlg = DialogueUsinage3D(c3._modele, c3._piece_place,
                                c3.bibliotheque, nom, self.window())
        if not executer:
            return dlg
        if dlg.exec() and dlg.operations():
            self.usinage_step.emit(dlg.operations())
        return dlg

    def est_en_3d(self) -> bool:
        if self._canvas3d is None:
            return False
        if self.hote_3d is not None:
            return self._3d_montree
        return self._pile_vues.currentWidget() is self._canvas3d

    def _cocher_3d(self, voulu: bool) -> None:
        if bool(voulu) != self.vue3d_btn.isChecked():
            self.vue3d_btn.blockSignals(True)
            self.vue3d_btn.setChecked(bool(voulu))
            self.vue3d_btn.blockSignals(False)

    def basculer_3d(self, voulu: bool) -> None:
        """Le bouton « 3D »: la vue en volume, ou le canvas 2D."""
        self._cocher_3d(voulu)
        if self.hote_3d is not None:
            self.vue_3d()
            self.hote_3d(bool(voulu))
            return
        if not voulu:
            self._pile_vues.setCurrentWidget(self._canvas_pile)
            return
        self._pile_vues.setCurrentWidget(self.vue_3d())
        self.actualiser_3d()

    #: le Canva 3D est en retard sur le programme (calculs sur demande)
    _3d_perime = True

    def calculs_3d_sur_demande(self) -> bool:
        """Réglage « Calculs 3D »: sur demande (le bouton), ou en temps
        réel."""
        return self._reglage('calculs_3d', 'temps_reel') == 'demande'

    def sur_onglet_3d(self, montre: bool) -> None:
        """(hôte) l'onglet 3D vient d'être montré, ou quitté."""
        self._3d_montree = bool(montre)
        self._cocher_3d(montre)
        if not montre:
            return
        if self.calculs_3d_sur_demande() and self._canvas3d is not None:
            self._canvas3d.marquer_perime(self._3d_perime)
            return
        self.actualiser_3d()

    def planifier_actualisation_3d(self) -> None:
        """Le programme a changé: la vue 3D se relit — une fois, un
        instant après la dernière modification (pas à chaque frappe).
        Calculs sur demande: elle se dit seulement en retard."""
        self._3d_perime = True
        if self.calculs_3d_sur_demande():
            if self._canvas3d is not None:
                self._canvas3d.marquer_perime(True)
            return
        if not self.est_en_3d():
            return
        if getattr(self, '_minuterie_3d', None) is None:
            from PySide6.QtCore import QTimer
            self._minuterie_3d = QTimer(self)
            self._minuterie_3d.setSingleShot(True)
            self._minuterie_3d.timeout.connect(self._actualiser_3d_libre)
        from src.gui import activite
        activite.veiller(self)
        self._minuterie_3d.start(350)

    def _actualiser_3d_libre(self) -> None:
        """La relecture du 3D attend, elle aussi, que l'utilisateur
        marque une pause (basse priorité: voir src.gui.activite)."""
        from src.gui import activite
        sans_attendre = getattr(self, '_3d_sans_attendre', False)
        self._3d_sans_attendre = False
        if not sans_attendre and activite.occupe():
            self._minuterie_3d.start(activite.attente_restante())
            return
        activite.relacher(self)
        self.actualiser_3d()

    def _sur_axe_3d(self, axe: str) -> None:
        self._axe_3d = axe or 'auto'
        self.actualiser_3d()

    def _modele_3d(self, chemin: str):
        """La pièce STEP maillée (gardée tant que le fichier ne change
        pas); la lecture se suit dans la barre d'état, et s'annule."""
        import os
        try:
            date = os.path.getmtime(chemin)
        except OSError:
            return None, "pièce STEP introuvable: " + os.path.basename(chemin)
        cle = (chemin, date, self._axe_3d)
        if cle not in self._modeles_3d:
            from src.gui.progression import travailler
            from src.io.vecteur import SUFFIXES_MAILLAGES, maillage, step3d
            maillee = chemin.lower().endswith(SUFFIXES_MAILLAGES)
            try:
                modele = travailler(
                    self, "Pièce en 3D",
                    (lambda prog: maillage.lire_modele(
                        chemin, axe_haut=self._axe_3d, progress=prog))
                    if maillee else
                    (lambda prog: step3d.lire_modele(
                        chemin, axe_haut=self._axe_3d, progress=prog)),
                    "Faces de la pièce…" if maillee
                    else "Maillage des faces…")
            except Exception as err:
                return None, f"pièce STEP illisible: {err}"
            if modele is None:
                return None, "lecture de la pièce annulée"
            self._modeles_3d = {cle: modele}
        modele = self._modeles_3d[cle]
        return modele, f"{os.path.basename(chemin)}: {modele.resume()}"

    #: la transparence ou la division d'une opération a changé au
    #: panneau du Canva 3D (la fenêtre redessine le Canva 2D)
    affichage_ops_change = Signal()
    #: l'œil d'une opération basculé au panneau 3D (l'opération)
    oeil_op_change = Signal(object)

    def _sur_affichage_ops_3d(self) -> None:
        # (la vue 3D s'est mise à jour: rien à relire)
        self.affichage_ops_change.emit()

    def _couleur_outil_de_op(self, op):
        """La couleur de l'outil d'une opération, comme ses tracés."""
        try:
            cle, libelle = self.canvas._op_tool_key(op)
            return self.canvas.tool_color(cle, libelle).name()
        except Exception:
            return None

    def _nom_outil_de_op(self, op) -> str:
        try:
            return str(self.canvas._op_tool_key(op)[1] or "")
        except Exception:
            return ""

    def actualiser_3d(self) -> None:
        """Relit le dessin, les opérations et la pièce dans la vue 3D."""
        if self._canvas3d is None:
            return
        if getattr(self, '_actualisation_3d', False):
            # une simulation tient la barre d'état (la boucle tourne
            # pendant ce temps): celle en cours lit un état déjà dépassé.
            # On recommencera derrière elle, et son résultat ne s'affiche
            # pas — le parcours de l'onglet d'avant restait à l'écran
            self._refaire_3d = True
            return
        self._actualisation_3d = True
        try:
            while True:
                self._refaire_3d = False
                self._actualiser_3d()
                if not self._refaire_3d:
                    break
        finally:
            self._actualisation_3d = False

    def sur_changement_de_programme(self) -> None:
        """Un autre programme (onglet) devient le programme courant: ce
        que la vue 3D montre n'est plus le sien. Elle se vide tout de
        suite: cachée, sur demande ou le temps d'une simulation, elle
        gardait les parcours de l'onglet d'avant, jusque dans le PNG."""
        self._3d_perime = True
        minuterie = getattr(self, '_minuterie_3d', None)
        if minuterie is not None:
            minuterie.stop()
        if getattr(self, '_actualisation_3d', False):
            self._refaire_3d = True
        if self._canvas3d is not None:
            self._canvas3d.oublier_programme()
            self._canvas3d.marquer_perime(self.calculs_3d_sur_demande())

    def relire_3d_sans_attendre(self) -> None:
        """L'actualisation planifiée part tout de suite (l'attente est
        pour les frappes, pas pour un changement d'onglet)."""
        minuterie = getattr(self, '_minuterie_3d', None)
        if minuterie is not None and minuterie.isActive():
            # ni la pause de l'utilisateur: c'est lui qui a changé
            # d'onglet, il attend le programme qu'il vient de choisir
            self._3d_sans_attendre = True
            minuterie.start(0)

    def _actualiser_3d(self) -> None:
        self._3d_perime = False
        self._canvas3d.marquer_perime(False)
        from src.gui.dxf import canvas_volume
        canvas = self.canvas
        modele, texte = None, ""
        decalage = (0.0, 0.0)
        pieces = canvas_volume.sources_3d(canvas)
        source = canvas_volume.source_3d(canvas)
        active_visible = all(p['visible'] for p in pieces if p['active'])
        if source and active_visible:
            modele, texte = self._modele_3d(source['chemin'])
            decalage = source['decalage']
        # les autres pièces visibles: en annexe (vues, pas usinées)
        annexes = []
        for p in pieces:
            if p['active'] or not p['visible']:
                continue
            m, _t = self._modele_3d(p['chemin'])
            if m is not None:
                annexes.append((m, p['decalage'], p['nom']))
        operations = []
        formes_par_op = []
        programme = outils = None
        fournisseur = getattr(self, 'fournisseur_3d', None)
        if callable(fournisseur):
            try:
                programme, outils = fournisseur()
            except Exception:
                programme, outils = None, None
            # les faces de la pièce s'usinent avec ces outils
            self._canvas3d.bibliotheque = outils
            if programme is not None:
                if self._brouillon_3d is None:
                    self._brouillon_3d = DxfCanvas()
                    self._brouillon_3d.hide()
                if outils is not None:
                    self._brouillon_3d.set_tool_library(outils)
                # les gros programmes appelés: simulés d'abord dans la
                # barre d'état (avec Annuler), pas au milieu du dessin
                from src.core import sim_cycles
                from src.gui.progression import preparer_parcours_fichiers
                lib = getattr(self._brouillon_3d, '_tool_library', None)
                preparer_parcours_fichiers(self, [
                    str((op.params or {}).get('filepath') or '').strip()
                    for op in getattr(programme, 'operations', [])
                    if op.operation_type == 'appel_programme'
                    and op.enabled],
                    sim_cycles.diametres_de(lib) if lib is not None
                    else {})
        # la simulation d'abord: le tracé des blocs s'en déduit
        parcours = self._simulation_3d(outils)
        if getattr(self, '_refaire_3d', False):
            return      # le programme a changé pendant la simulation
        if programme is not None:
            self._lire_les_traces(programme, parcours)
            if getattr(self, '_refaire_3d', False):
                return
            operations = canvas_volume.formes_3d(
                canvas, programme, self._brouillon_3d, formes_par_op,
                parcours)
            self._canvas3d.set_operations_affichage(
                getattr(programme, 'operations', []))
        couleurs = (canvas_volume.couleurs_outils(canvas, parcours)
                    if parcours else {})
        self._canvas3d.charger(modele, decalage,
                               canvas_volume.dessin_3d(canvas), operations,
                               texte, parcours, couleurs, annexes=annexes,
                               formes_par_op=formes_par_op)

    def _lire_les_traces(self, programme, parcours) -> None:
        """Les gros blocs que la simulation n'a pas atteints: lus d'abord
        dans la barre d'état, avec Annuler (leur tracé manque alors)."""
        from src.gui.dxf import canvas_volume
        from src.gui.progression import travailler, zone_de
        codes = canvas_volume.codes_a_lire(programme, parcours)
        if sum(len(c) for c in codes) < canvas_volume.CARACTERES_SUIVIS:
            return
        if zone_de(self) is None:
            return          # un calcul tient déjà la barre d'état
        if travailler(self, "Lecture des blocs",
                      lambda prog: canvas_volume.lire_codes(codes, prog),
                      "Lecture des tracés…") is None:
            canvas_volume.renoncer_a_lire(codes)

    #: au-delà de ces lignes, la simulation se suit dans la barre d'état
    LIGNES_SIM_SUIVIE = 20000
    #: les simulations gardées (les onglets qu'on alterne se retrouvent
    #: sans recalcul), en sommets cumulés
    SOMMETS_GARDES = 1_500_000

    def _simulation_3d(self, outils=None):
        """Le parcours simulé du code du programme (cycles déroulés),
        gardé tant que le code ne change pas; None sans code."""
        fournisseur = getattr(self, 'fournisseur_code_3d', None)
        if not callable(fournisseur):
            return None
        try:
            code = fournisseur() or ""
        except Exception:
            return None
        if not code.strip():
            return None
        from src.core import sim_cycles
        diametres = sim_cycles.diametres_de(outils) if outils else {}
        formes = sim_cycles.formes_outils(outils) if outils else {}
        cle_code = sim_cycles.cle_de_simulation(code)
        self._cle_code_3d = cle_code
        cle = (cle_code, tuple(sorted(diametres.items())),
               tuple(sorted((k, tuple(sorted(v.items())))
                            for k, v in formes.items())))
        if cle in self._sims_3d:
            self._sims_3d.move_to_end(cle)
            res = self._sims_3d[cle]
            # (l'en-tête ne compte pas dans la clé)
            res['brut'] = sim_cycles.brut_du_code(code)
            return res
        try:
            # long à dérouler: beaucoup de lignes, ou un appel à un gros
            # programme externe (usermodule) que la simulation suit
            if code.count('\n') > self.LIGNES_SIM_SUIVIE or \
                    sim_cycles.taille_avec_modules(code) > \
                    sim_cycles.SEUIL_SUIVI:
                from src.gui.progression import travailler
                res = travailler(
                    self, "Simulation des cycles",
                    lambda prog: sim_cycles.simuler(code, diametres, prog,
                                                    formes=formes),
                    "Déroulement des cycles…")
                if res is None:
                    return None
            else:
                res = sim_cycles.simuler(code, diametres,
                                         formes=formes)
        except Exception:
            return None
        self._sims_3d[cle] = res
        total = sum(len(r['x']) for r in self._sims_3d.values())
        while total > self.SOMMETS_GARDES and len(self._sims_3d) > 1:
            _cle, ancienne = self._sims_3d.popitem(last=False)
            total -= len(ancienne['x'])
        return res

    def reglages_seuls_changes(self) -> bool:
        """Seuls les réglages du programme ont changé (brut, commentaire).
        Si le code usiné reste celui que la vue montre, elle n'a rien à
        relire: juste le brut qu'il déclare. Rend vrai si c'est réglé."""
        fournisseur = getattr(self, 'fournisseur_code_3d', None)
        if self._canvas3d is None or self._3d_perime \
                or not callable(fournisseur):
            return False
        from src.core import sim_cycles
        code = fournisseur() or ""
        if not code.strip() or getattr(self, '_cle_code_3d', None) \
                != sim_cycles.cle_de_simulation(code):
            return False
        self._canvas3d.nouveau_brut_declare(sim_cycles.brut_du_code(code))
        return True

    # ──── Un canvas par onglet ────

    @property
    def canvas(self) -> DxfCanvas:
        """Le canvas de l'onglet courant.

        Tout ce qui écrivait `panneau.canvas` continue de marcher:
        c'est la même façade, sur le dessin du bon onglet."""
        return self._canvas_pile.currentWidget()

    def _neuf_canvas(self) -> DxfCanvas:
        """Crée un canvas et le branche comme les autres.

        Les branchements sont ici, et pas dans `_connect_signals`:
        un canvas créé plus tard doit être aussi complet que le
        premier — sinon la souris, la règle ou les cotes ne
        répondent que dans l'onglet d'origine."""
        canvas = DxfCanvas()
        canvas.setSizePolicy(QSizePolicy.Policy.Expanding,
                             QSizePolicy.Policy.Expanding)
        canvas.nudge_step_changed.connect(self._on_pas_change)
        canvas.pas_focus_demande.connect(self._focus_champ_pas)
        canvas.resize_requested.connect(self._on_redimensionner)
        canvas.texte_demande.connect(self._on_texte_au_clic)
        canvas.texte_grave_demande.connect(self._on_texte_grave_au_clic)
        canvas.mouse_position.connect(self._on_mouse_move)
        canvas.coordinate_picked.connect(self._on_coordinate_picked)
        canvas.circles_detected.connect(
            lambda c: self.circles_detected.emit(c))
        canvas.selection_changed.connect(self._on_selection_changed)
        canvas.entity_info.connect(self._on_entity_info)
        canvas.ruler_measured.connect(self._on_ruler_measured)
        self.pas_spin.valueChanged.connect(canvas.set_nudge_step)
        self.grid_cb.toggled.connect(canvas.set_grid_visible)
        bouton = getattr(self, 'accroche_btn', None)
        if bouton is not None:
            canvas.set_accrochages(bouton.isChecked())
        canvas.ortho_change.connect(self._sur_ortho_canvas)
        canvas.retour_selection.connect(self.revenir_selection)
        canvas.demander_valeur = self._valeur_contrainte
        self.canvas_cree.emit(canvas)
        return canvas

    def utiliser_canvas(self, cle: str) -> DxfCanvas:
        """Montre le canvas de cet onglet, en le créant au besoin."""
        cle = str(cle or "P1")
        canvas = self._canvas_par_onglet.get(cle)
        if canvas is None:
            canvas = self._neuf_canvas()
            self._canvas_par_onglet[cle] = canvas
            self._canvas_pile.addWidget(canvas)
        self._cle_onglet = cle
        self._canvas_pile.setCurrentWidget(canvas)
        # Les réglages de la barre suivent le canvas affiché
        canvas.set_nudge_step(self.pas_spin.value())
        canvas.set_grid_visible(self.grid_cb.isChecked())
        canvas.set_op_labels_visible(self.show_labels_btn.isChecked())
        canvas.set_legend_visible(self.show_legend_btn.isChecked())
        self._on_selection_changed(len(canvas.selection_courante()))
        self.maj_onglets_imports()
        return canvas

    def _bandeau(self, barre):
        """La barre des imports dans son bandeau: Importer, Exporter."""
        from src.gui.dxf.barre_imports import BandeauImports
        bandeau = BandeauImports(barre, self)
        bandeau.importer.connect(self._on_import)
        bandeau.exporter.connect(self._on_export)
        return bandeau

    def _neuve_barre_imports(self):
        from src.gui.dxf.barre_imports import BarreImports
        barre = BarreImports(self)
        barre.historique = lambda: self._imports_fermes
        barre.choisi.connect(self._on_import_choisi)
        barre.ferme.connect(self.fermer_import)
        barre.visibilite.connect(self._on_import_visible)
        barre.rouvrir_demande.connect(self.rouvrir_import)
        self._barres_imports.append(barre)
        return barre

    def maj_onglets_imports(self) -> None:
        """Un onglet par DXF importé dans ce dessin — au-dessus du
        Canva 2D et du Canva 3D: son nom, son œil, « × » le ferme, le
        clic droit rouvre un onglet fermé."""
        canvas = self.canvas
        imports = canvas.imports_dxf() if canvas is not None else []
        # un fichier ouvert n'est plus « fermé »
        ouverts = {i.get('chemin') for i in imports}
        fermes = getattr(self, '_imports_fermes', [])
        if any(h.get('chemin') in ouverts for h in fermes):
            from src.gui.dxf.barre_imports import ecrire_historique
            self._imports_fermes = [h for h in fermes
                                    if h.get('chemin') not in ouverts]
            ecrire_historique(self._imports_fermes)
        actif = getattr(canvas, '_source_3d', None) if canvas else None
        imports = [dict(i, active=bool(i.get('source_3d'))
                        and i.get('source_3d') is actif) for i in imports]
        for barre in getattr(self, '_barres_imports', []):
            try:
                barre.remplir(imports)
            except RuntimeError:
                continue

    def memoriser_imports(self) -> None:
        """Le dessin va être effacé (Remplacer, Effacer): ses imports
        rejoignent les onglets fermés — on peut les rouvrir."""
        for imp in reversed(self.canvas.imports_dxf()):
            self._pousser_ferme(imp)

    def _pousser_ferme(self, imp: dict) -> None:
        from src.gui.dxf.barre_imports import (HISTORIQUE_MAX,
                                               ecrire_historique)
        if not imp.get('chemin'):
            return
        entree = {'nom': imp.get('nom', ''), 'chemin': imp['chemin']}
        if imp.get('reglages'):
            entree['reglages'] = dict(imp['reglages'])
        self._imports_fermes = ([entree] + [
            h for h in self._imports_fermes
            if h.get('chemin') != entree['chemin']])[:HISTORIQUE_MAX]
        ecrire_historique(self._imports_fermes)

    def fermer_import(self, cle: str) -> int:
        """« × » d'un onglet d'import: ses entités et ses centres
        quittent le dessin; il rejoint les onglets fermés (clic droit:
        rouvrir). Rend le nombre d'entités ôtées."""
        imp = next((i for i in self.canvas.imports_dxf()
                    if i['cle'] == cle), None)
        if imp is None:
            return 0
        self._pousser_ferme(imp)
        n = self.canvas.retirer_import(cle)
        self.canvas.circles_detected.emit(self.canvas.get_detected_circles())
        self.maj_onglets_imports()
        if imp.get('genre') == 'step':
            self.actualiser_3d()        # la pièce quitte la vue 3D
        self.info_label.setText(
            f"{imp['nom']} fermé ({n} entité(s)) — clic droit sur la "
            "barre des imports pour le rouvrir")
        return n

    def rouvrir_import(self, k: int = 0) -> bool:
        """Rouvre l'onglet fermé n° k (0: le dernier): le fichier revient
        au dessin, superposé à ce qui y est."""
        import os
        from src.gui.dxf.barre_imports import ecrire_historique
        if not 0 <= k < len(self._imports_fermes):
            return False
        h = self._imports_fermes.pop(k)
        ecrire_historique(self._imports_fermes)
        if not os.path.isfile(h['chemin']):
            self.maj_onglets_imports()
            self.info_label.setText(f"{h['nom']}: fichier introuvable "
                                    f"({h['chemin']})")
            return False
        if h['chemin'].lower().endswith('.dxf'):
            self._append_dxf_file(h['chemin'])
            return True
        if h['chemin'].lower().endswith('.dwg'):
            from src.io.vecteur import dwg
            try:
                self._append_dxf_file(dwg.vers_dxf(h['chemin']))
            except dwg.DwgError as err:
                self.info_label.setText(f"{h['nom']}: {err}")
                return False
            return True
        # une image se retrace avec les réglages de son import
        rapport = self._charger_vectoriel(h['chemin'], ajouter=True,
                                          options=h.get('reglages'))
        from src.io.vecteur import est_piece_3d
        if est_piece_3d(h['chemin']):
            self.actualiser_3d()        # la pièce revient en volume
        return rapport is not None

    def _on_import_choisi(self, cle: str) -> None:
        """Clic sur le nom d'un DXF importé: ses entités, sélectionnées.
        Une pièce 3D devient en plus la pièce ACTIVE (usinage, faces)."""
        n = self.canvas.selectionner_import(cle)
        nom = next((i['nom'] for i in self.canvas.imports_dxf()
                    if i['cle'] == cle), cle)
        self.info_label.setText(f"{nom}: {n} entité(s) sélectionnée(s)")
        if self.canvas.activer_piece(cle):
            self.maj_onglets_imports()
            self.info_label.setText(f"{nom}: pièce 3D active")
            self.planifier_actualisation_3d()

    def _on_import_visible(self, cle: str, visible: bool) -> None:
        n = self.canvas.set_import_visible(cle, visible)
        self.info_label.setText(
            f"{n} entité(s) {'montrée(s)' if visible else 'masquée(s)'}")
        imp = next((i for i in self.canvas.imports_dxf()
                    if i['cle'] == cle), None)
        if (imp or {}).get('source_3d'):
            # la pièce se montre ou se masque aussi en volume
            self.planifier_actualisation_3d()

    def _on_import_retire(self, cle: str) -> None:
        """(ancien nom) Fermer l'onglet d'un import — sans demander: il
        se rouvre d'un clic droit."""
        self.fermer_import(cle)

    def attacher_canvas_courant(self, cle: str) -> None:
        """Range le canvas affiché sous cette clé d'onglet.

        Le premier canvas naît avec le panneau, avant que la fenêtre
        ait donné son identifiant à l'onglet: sans ce raccord, le
        premier onglet repartait sur un canvas vide au premier
        changement d'onglet."""
        cle = str(cle or "P1")
        courant = self.canvas
        for ancienne, canvas in list(self._canvas_par_onglet.items()):
            if canvas is courant:
                self._canvas_par_onglet.pop(ancienne, None)
        self._canvas_par_onglet[cle] = courant
        self._cle_onglet = cle

    def garder_canvas(self, cles) -> int:
        """Ne garde que les canvas des onglets encore ouverts.

        Un canvas orphelin ne se voit pas mais garde sa scène en
        mémoire: un dessin de dix mille entités reste entier. Rend le
        nombre de canvas libérés."""
        vivants = {str(c) for c in cles if c}
        vivants.add(self._cle_onglet)
        perdus = [c for c in self._canvas_par_onglet if c not in vivants]
        for cle in perdus:
            self.oublier_canvas(cle)
        return len(perdus)

    def oublier_canvas(self, cle: str) -> bool:
        """Onglet fermé: son dessin s'en va avec lui."""
        canvas = self._canvas_par_onglet.pop(str(cle or ""), None)
        if canvas is None:
            return False
        self._canvas_pile.removeWidget(canvas)
        canvas.deleteLater()
        return True

    def _connect_signals(self):
        """Les signaux du canvas sont branchés à sa création
        (`_neuf_canvas`): il y en a un par onglet."""
        return

    def _on_import(self):
        from src.io import vecteur
        start_dir = self._dxf_dir or ""
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Importer un dessin", start_dir, vecteur.FILE_FILTER)
        if not filepath:
            return
        self.charger_dessin(filepath)

    def charger_dessin(self, filepath: str, ask: bool = True):
        """Ouvre un dessin, quel que soit son format.

        Le DXF garde sa route propre (couleurs de calque, sélection
        par entité). Les autres formats passent par le lecteur
        vectoriel, qui rend des tracés."""
        import os
        from src.io import vecteur
        if os.path.splitext(filepath)[1].lower() == '.dxf':
            return self._load_dxf_file(filepath, ask=ask)
        if os.path.splitext(filepath)[1].lower() == '.dwg':
            return self._charger_dwg(filepath, ask)
        ajouter = ask and self.a_du_dessin()
        if os.path.splitext(filepath)[1].lower() in vecteur.SUFFIXES_IMAGES:
            return self.vectoriser_image(filepath)
        if not vecteur.sait_lire(filepath):
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "Importer un dessin",
                f"Format non lu: {os.path.splitext(filepath)[1]}\n\n"
                f"Formats disponibles sur ce poste:\n"
                f"{vecteur.formats_lisibles()}")
            return None
        return self._charger_vectoriel(filepath, ajouter=ajouter)

    def a_du_dessin(self) -> bool:
        """Un dessin est-il en place (un import nouveau s'y ajoute
        alors dans son onglet, au lieu de le remplacer)?"""
        c = self.canvas
        return bool(getattr(c, '_dxf_items', None)
                    or (hasattr(c, 'imports_dxf') and c.imports_dxf()))

    def _charger_dwg(self, filepath: str, ask: bool = True):
        """Un DWG: converti en DXF (convertisseur gratuit, dans la
        barre d'état), puis ouvert comme un DXF."""
        import os
        from PySide6.QtWidgets import QMessageBox
        from src.gui.progression import travailler
        from src.io.vecteur import dwg
        try:
            dxf = travailler(self, "Conversion DWG → DXF",
                             lambda _prog: dwg.vers_dxf(filepath),
                             os.path.basename(filepath))
        except dwg.DwgError as err:
            QMessageBox.warning(self, "Importer un DWG", str(err))
            self.info_label.setText("DWG non converti")
            return None
        if dxf is None:
            return None
        rapport = self._load_dxf_file(dxf, ask=ask)
        # l'onglet porte le nom du DWG (et le rouvre)
        for imp in getattr(self.canvas, '_imports_dxf', []):
            if os.path.normcase(imp.get('chemin', '')) == os.path.normcase(
                    dxf):
                imp['nom'] = os.path.basename(filepath)
                imp['chemin'] = filepath
        self.maj_onglets_imports()
        self.info_label.setText(
            f"{os.path.basename(filepath)} — converti ({dwg.etat()})")
        return rapport

    def _charger_vectoriel(self, filepath: str, ajouter: bool = False,
                           options=None):
        """Lit un PDF / AI / EPS / SVG / CDR / STEP, en rendant des
        comptes. `ajouter`: superposé au dessin (une pièce 3D de plus a
        son onglet et devient la pièce active; les autres restent).

        Un dessin de dix mégaoctets demande plusieurs secondes: sans
        barre de progression l'application paraît plantée, et sans
        bouton d'annulation, elle l'est."""
        import os
        from PySide6.QtWidgets import QMessageBox
        from src.io import vecteur
        from src.gui.progression import Progression

        # la progression dans la barre d'état (plus de fenêtre)
        boite = Progression(self, "Import du dessin",
                            f"Lecture de {os.path.basename(filepath)}…")
        boite.__enter__()

        def avance(fraction: float, texte: str) -> bool:
            return boite(max(0.0, min(1.0, float(fraction))), texte or "")

        try:
            # `ajouter`: superposé — une pièce 3D de plus a son onglet et
            # devient la pièce active, celles d'avant restent (en annexe)
            if not ajouter:
                # le dessin en place part: ses imports restent à rouvrir
                self.memoriser_imports()
            rapport = self.canvas.load_vector(filepath, progress=avance,
                                              ajouter=ajouter,
                                              options=options)
        except vecteur.Cancelled:
            boite.__exit__(None, None, None)
            self.info_label.setText("Import annulé")
            return None
        except Exception as exc:
            boite.__exit__(None, None, None)
            QMessageBox.warning(
                self, "Importer un dessin",
                f"Lecture impossible:\n{exc}")
            self.info_label.setText(f"Import échoué: {str(exc)[:60]}")
            return None
        boite.__exit__(None, None, None)
        self._dxf_dir = os.path.dirname(filepath)
        self.maj_onglets_imports()
        self.info_label.setText(
            f"{os.path.basename(filepath)} — {rapport.summary()}")
        if not ajouter:
            self.proposer_centrage()
        return rapport

    # ──── Accrochages, retouches, image vectorisée ────

    def _valeur_contrainte(self, genre: str, actuelle: float):
        """La valeur d'une cote pilotante (le mini-formulaire)."""
        from src.core import contraintes as cg
        from src.gui.dialogs.mini_formulaire import MiniFormulaire
        f = MiniFormulaire(cg.NOMS[genre], [
            ('valeur', "Valeur", 'nombre', round(float(actuelle), 4),
             {'unite': 'mm', 'min': 0.0001, 'max': 100000.0,
              'decimales': 4})], self,
            "Le dessin s'ajuste pour la tenir (et la garde ensuite).")
        valeurs = f.demander()
        return None if valeurs is None else float(valeurs['valeur'])

    def _on_ortho(self, actif: bool) -> None:
        pas = self._ortho_pas_choisi if actif else 0.0
        for canvas in self._canvas_par_onglet.values():
            canvas.set_ortho(pas)
        self.ortho_btn.setText(
            "Ortho" if pas in (0.0, 90.0) else f"Ortho {pas:g}°")
        self.info_label.setText(f"Ortho {pas:g}° (F8)" if pas
                                else "Ortho désactivé")

    def _menu_ortho(self, _pos=None) -> None:
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self.ortho_btn)
        for pas in (90.0, 45.0, 30.0, 15.0):
            a = menu.addAction(f"Par pas de {pas:g}°")
            a.setCheckable(True)
            a.setChecked(self.ortho_btn.isChecked()
                         and pas == self._ortho_pas_choisi)
            a.triggered.connect(lambda _c=False, p=pas: self.regler_ortho(p))
        menu.exec(self.ortho_btn.mapToGlobal(
            self.ortho_btn.rect().bottomLeft()))

    def regler_ortho(self, pas: float) -> None:
        self._ortho_pas_choisi = float(pas)
        if self.ortho_btn.isChecked():
            self._on_ortho(True)
        else:
            self.ortho_btn.setChecked(True)

    def _sur_ortho_canvas(self, pas: float) -> None:
        """F8 au canvas: le bouton suit."""
        self.ortho_btn.blockSignals(True)
        self.ortho_btn.setChecked(bool(pas))
        self.ortho_btn.blockSignals(False)
        if pas:
            self._ortho_pas_choisi = pas
        for canvas in self._canvas_par_onglet.values():
            canvas.set_ortho(pas)

    def _on_accrochages(self, actifs: bool) -> None:
        for canvas in self._canvas_par_onglet.values():
            canvas.set_accrochages(actifs)

    def nettoyer_dessin(self):
        """« Nettoyer »: le calcul tourne dans un fil, la barre et son
        Annuler dans la barre d'état."""
        from src.gui.progression import travailler

        def executer(calcul):
            return travailler(self, "Nettoyage du dessin", calcul,
                              "doublons, traits couverts, jonctions")
        bilan = self.canvas.nettoyer_dessin(executer=executer)
        if bilan is not None:
            self.info_label.setText(f"Nettoyé: {bilan['message']}")
        return bilan

    #: les mini-formulaires des retouches: (titre, champs, explication)
    _FORMULAIRES_RETOUCHE = {
        'decaler': ("Décaler", [
            ('distance', "Distance", 'nombre', 1.0,
             {'unite': 'mm', 'min': -1000.0, 'max': 1000.0,
              'decimales': 3,
              'bulle': "Positive: vers l'extérieur d'un contour fermé "
                       "(à gauche d'un trait ouvert); négative: vers "
                       "l'intérieur."}),
            ('coins', "Coins", 'choix', 'ronds',
             {'choix': ['ronds', 'vifs'],
              'bulle': "Ronds: le chemin du centre d'un outil. Vifs: "
                       "les côtés prolongés."})],
            "Une copie décalée des tracés sélectionnés, au calque "
            "Dessin. Les contours fermés se décalent ensemble (le trou "
            "d'un « O » rétrécit quand le « O » grossit)."),
        'conge': ("Congé aux angles", [
            ('valeur', "Rayon", 'nombre', 1.0,
             {'unite': 'mm', 'min': 0.001, 'max': 1000.0,
              'decimales': 3}),
            ('angles', "Angles", 'choix', 'saillants',
             {'choix': ['saillants', 'rentrants', 'tous'],
              'bulle': "Saillants: les coins qu'une fraise de ce rayon "
                       "n'atteint pas dans une POCHE. Rentrants: ceux "
                       "qu'elle laisse autour d'une PIÈCE."})],
            "Les contours fermés sont pris comme une surface: un "
            "passage plus étroit que la fraise disparaît, comme à "
            "l'usinage. Les traits ouverts s'arrondissent sommet par "
            "sommet."),
        'chanfrein': ("Chanfrein aux angles", [
            ('valeur', "Distance", 'nombre', 0.5,
             {'unite': 'mm', 'min': 0.001, 'max': 1000.0,
              'decimales': 3,
              'bulle': "Le long de chaque côté, depuis le sommet."}),
            ('angles', "Angles", 'choix', 'tous',
             {'choix': ['tous', 'saillants', 'rentrants']})],
            "Coupe les angles des tracés sélectionnés."),
        'arcs': ("Lisser en arcs", [
            ('valeur', "Écart toléré", 'nombre', 0.05,
             {'unite': 'mm', 'min': 0.001, 'max': 5.0, 'decimales': 3,
              'bulle': "Écart entre les sommets du tracé et les arcs "
                       "qui les remplacent: plus grand = plus lisse."})],
            "Les tracés sélectionnés deviennent des droites et des ARCS "
            "exacts (un tracé vectorisé en escalier s'adoucit; au DXF "
            "et au Tracé « Arcs », ce sont de vrais arcs)."),
        'formes': ("Reconnaître les formes", [
            ('valeur', "Écart toléré", 'nombre', 0.05,
             {'unite': 'mm', 'min': 0.001, 'max': 5.0, 'decimales': 3,
              'bulle': "Écart maximal entre un sommet et la forme "
                       "reconnue."})],
            "Les polylignes sélectionnées qui sont des cercles, des "
            "rectangles, des ellipses, des droites ou des arcs deviennent "
            "ces entités exactes. Un cercle reconnu porte son centre: "
            "« DXF to Op » en fait un perçage."),
        'points': ("Points le long d'un tracé", [
            ('nombre', "Nombre de points", 'nombre', 8,
             {'min': 0, 'max': 10000, 'decimales': 0,
              'bulle': "Répartis à intervalles égaux (0: utiliser le "
                       "pas)."}),
            ('pas', "Ou un point tous les", 'nombre', 0.0,
             {'unite': 'mm', 'min': 0.0, 'max': 10000.0, 'decimales': 3}),
            ('bouts', "Un point à chaque bout (tracé ouvert)", 'case',
             True, {}),
            ('diametre', "Ø des repères", 'nombre', 1.0,
             {'unite': 'mm', 'min': 0.01, 'max': 500.0, 'decimales': 3,
              'bulle': "Des cercles de ce diamètre, centrés sur les "
                       "points: le Ø proposé pour le perçage."})],
            "Sur chaque tracé sélectionné. Sur un contour fermé, le tour "
            "est partagé sans doubler le départ."),
        'reseau_rect': ("Réseau rectangulaire", [
            ('nx', "Colonnes (X)", 'nombre', 3,
             {'min': 1, 'max': 1000, 'decimales': 0}),
            ('ny', "Lignes (Y)", 'nombre', 1,
             {'min': 1, 'max': 1000, 'decimales': 0}),
            ('dx', "Pas en X", 'nombre', 10.0,
             {'unite': 'mm', 'min': -10000.0, 'max': 10000.0}),
            ('dy', "Pas en Y", 'nombre', 10.0,
             {'unite': 'mm', 'min': -10000.0, 'max': 10000.0})],
            "Des copies de la sélection; l'original est la première "
            "case. Les cercles copiés gardent leur centre (perçages)."),
        'reseau_polaire': ("Réseau circulaire", [
            ('n', "Nombre d'éléments", 'nombre', 6,
             {'min': 2, 'max': 1000, 'decimales': 0,
              'bulle': "L'original compris."}),
            ('angle', "Angle total", 'nombre', 360.0,
             {'unite': '°', 'min': -360.0, 'max': 360.0,
              'bulle': "360: le tour partagé; moins: du premier au "
                       "dernier élément."}),
            ('cx', "Centre X", 'nombre', 0.0,
             {'unite': 'mm', 'min': -10000.0, 'max': 10000.0}),
            ('cy', "Centre Y", 'nombre', 0.0,
             {'unite': 'mm', 'min': -10000.0, 'max': 10000.0}),
            ('tourner', "Les copies tournent", 'case', True, {})],
            "Des copies de la sélection autour du centre."),
        'hauteur_cotes': ("Hauteur des cotes", [
            ('valeur', "Hauteur du texte", 'nombre', 2.5,
             {'unite': 'mm', 'min': 0.2, 'max': 100.0, 'decimales': 2})],
            "Pour les prochaines cotes posées."),
    }

    def retoucher(self, genre: str, executer: bool = True):
        """Décaler, congé, chanfrein: le mini-formulaire, puis la
        retouche. `executer=False` rend le formulaire sans l'ouvrir
        (les tests le remplissent et appellent `appliquer_retouche`)."""
        from PySide6.QtWidgets import QDialogButtonBox
        from src.gui.dialogs.mini_formulaire import MiniFormulaire
        if genre != 'hauteur_cotes' and not self.canvas.items_retouchables():
            self.info_label.setText(
                "Sélectionnez d'abord des tracés (clic, ou rectangle)")
            return None
        titre, champs, explication = self._FORMULAIRES_RETOUCHE[genre]
        formulaire = MiniFormulaire(titre, champs, self, explication)
        formulaire.genre = genre
        boite = formulaire.findChild(QDialogButtonBox)
        if boite is not None:
            boite.button(QDialogButtonBox.StandardButton.Ok).setText(
                "Appliquer")
        if not executer:
            return formulaire
        valeurs = formulaire.demander()
        if valeurs is None:
            return None
        return self.appliquer_retouche(genre, valeurs)

    def appliquer_retouche(self, genre: str, valeurs: dict):
        c = self.canvas
        if genre == 'decaler':
            bilan = c.decaler_selection(
                float(valeurs['distance']),
                'rond' if valeurs.get('coins', 'ronds') == 'ronds'
                else 'vif')
        elif genre == 'conge':
            bilan = c.conge_selection(float(valeurs['valeur']),
                                      valeurs.get('angles', 'tous'))
        elif genre == 'arcs':
            bilan = c.lisser_en_arcs_selection(float(valeurs['valeur']))
        elif genre == 'formes':
            bilan = c.reconnaitre_selection(float(valeurs['valeur']))
        elif genre == 'points':
            bilan = c.points_le_long_selection(
                int(round(valeurs['nombre'])), float(valeurs['pas']),
                bool(valeurs['bouts']), float(valeurs['diametre']))
        elif genre == 'reseau_rect':
            from src.core import retouche as rt
            bilan = c.reseau_selection(rt.reseau_rectangulaire(
                int(round(valeurs['nx'])), int(round(valeurs['ny'])),
                float(valeurs['dx']), float(valeurs['dy'])))
        elif genre == 'reseau_polaire':
            from src.core import retouche as rt
            emprise = c.emprise_de(c.items_retouchables())
            centre = ((emprise.center().x(), -emprise.center().y())
                      if emprise is not None else (0.0, 0.0))
            bilan = c.reseau_selection(rt.reseau_polaire(
                int(round(valeurs['n'])), float(valeurs['angle']),
                float(valeurs['cx']), float(valeurs['cy']),
                bool(valeurs['tourner']), centre))
        elif genre == 'hauteur_cotes':
            c.hauteur_cote = float(valeurs['valeur'])
            for autre in self._canvas_par_onglet.values():
                autre.hauteur_cote = c.hauteur_cote
            self.info_label.setText(
                f"Cotes: texte de {c.hauteur_cote:g} mm")
            return c.hauteur_cote
        else:
            bilan = c.chanfrein_selection(float(valeurs['valeur']),
                                          valeurs.get('angles', 'tous'))
        if bilan is not None:
            self.info_label.setText(self.coord_label.text())
        return bilan

    def armer_outil(self, outil: str) -> None:
        """Un outil à clic (couper, ajuster, région…) ou une cote:
        armé jusqu'à Échap; les points s'accrochent au dessin."""
        from src.core import cotation as ct
        from src.gui.dxf.dxf_canvas import DxfCanvas
        self.pick_btn.setChecked(False)
        self.canvas.set_pick_mode(False)
        for b in list(self.draw_buttons.values()) + [self.text_btn,
                                                     self.texte_grave_btn]:
            b.setChecked(False)
        self.canvas.set_draw_tool(outil)
        from src.core import contraintes as cg
        nom = (DxfCanvas.NOMS_OUTILS_CLIC.get(outil)
               or ct.GENRES.get(outil)
               or cg.NOMS.get(outil.split(':', 1)[-1], outil))
        self.canvas._choix_contrainte = []
        self.info_label.setText(f"{nom}: cliquez au canvas — Échap pour "
                                f"sortir")
        self.canvas.setFocus()

    def mesurer(self, executer: bool = True) -> dict:
        """« Mesurer la sélection »: le compte rendu dans une boîte (le
        texte se copie)."""
        m = self.canvas.mesurer_selection()
        self.info_label.setText(m['message'].replace("\n", " · "))
        if executer:
            from PySide6.QtWidgets import QMessageBox
            boite = QMessageBox(self)
            boite.setWindowTitle("Mesures")
            boite.setText(m['message'])
            boite.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse)
            boite.exec()
        return m

    def booleen(self, operation: str):
        bilan = self.canvas.booleen_selection(operation)
        self.info_label.setText(self.coord_label.text())
        return bilan

    #: les réglages du dernier tracé d'image (la fenêtre s'y rouvre)
    _reglages_trace = None

    def vectoriser_image(self, filepath: str = "", executer: bool = True):
        """« Vectoriser une image »: sa fenêtre (réglages, aperçu),
        puis les tracés au canvas, dans leur onglet. `executer=False`
        rend la fenêtre sans l'ouvrir (tests)."""
        import os
        from PySide6.QtWidgets import QMessageBox
        from src.io import vecteur
        if not filepath:
            filtre = ("Image à vectoriser (*.png *.jpg *.jpeg *.bmp "
                      "*.gif *.tif *.tiff)")
            filepath, _ = QFileDialog.getOpenFileName(
                self, "Vectoriser une image", self._dxf_dir or "", filtre)
            if not filepath:
                return None
        if os.path.splitext(filepath)[1].lower() not in \
                vecteur.SUFFIXES_IMAGES:
            return None
        from src.gui.dialogs.trace_image_dialog import DialogueTraceImage
        try:
            dlg = DialogueTraceImage(
                filepath, self, reglages=self._reglages_trace,
                dessin_present=bool(self.canvas._dxf_items))
        except ValueError as exc:
            QMessageBox.warning(self, "Vectoriser une image", str(exc))
            return None
        if not executer:
            return dlg
        if not dlg.exec() or dlg.trace is None:
            return None
        return self.poser_image_tracee(dlg)

    def poser_image_tracee(self, dlg):
        """Les tracés de la fenêtre, posés au canvas (son onglet)."""
        import os
        calques, rapport = dlg.calques()
        if not calques or rapport is None:
            return None
        ajouter = dlg.ajouter.isChecked() and dlg.ajouter.isEnabled()
        if not ajouter:
            self.memoriser_imports()
        reglages = dlg.reglages()
        type(self)._reglages_trace = reglages
        rapport = self.canvas.poser_calques(calques, rapport, dlg.chemin,
                                            ajouter=ajouter,
                                            reglages=reglages)
        self._dxf_dir = os.path.dirname(dlg.chemin)
        self.maj_onglets_imports()
        self.info_label.setText(
            f"{os.path.basename(dlg.chemin)} — {rapport.summary()}")
        if not ajouter:
            self.proposer_centrage()
        return rapport

    def _load_dxf_file(self, filepath: str, ask: bool = True):
        """Charge un fichier DXF et met à jour la navigation.

        Le chargement EFFACE le dessin en place et les centres
        détectés — avec les Pz et Ø qu'on y a saisis. Quand il y a
        quelque chose à perdre, on demande."""
        import os
        # Octobre 2026 (RomDuch): plus de question — un dessin en place
        # garde tout (Pz/Ø des centres compris), le nouveau fichier
        # arrive dans SON onglet d'import
        if ask and self.a_du_dessin():
            return self._append_dxf_file(filepath)
        try:
            self.memoriser_imports()
            self.canvas.clear_dxf()
            self.canvas.load_dxf(filepath)
            self.maj_onglets_imports()
            self._current_dxf_path = filepath
            # Mémoriser le dossier et scanner les .dxf
            dirpath = os.path.dirname(filepath)
            self._dxf_dir = dirpath
            self._scan_dxf_folder(dirpath, filepath)
            circles = self.canvas.get_detected_circles()
            n_entities = len(self.canvas._dxf_items)
            fname = os.path.basename(filepath)
            idx_info = ""
            if self._dxf_files:
                idx_info = f" [{self._dxf_index + 1}/{len(self._dxf_files)}]"
            if self._expert_mode:
                fsize = os.path.getsize(filepath)
                size_str = (f"{fsize / 1024:.1f} Ko" if fsize < 1048576
                            else f"{fsize / 1048576:.1f} Mo")
                rect = self.canvas.scene().itemsBoundingRect()
                bbox = (f"{rect.width():.1f}×{rect.height():.1f}"
                        if not rect.isEmpty() else "?")
                self.info_label.setText(
                    f"{fname}{idx_info} | {n_entities} entités | "
                    f"{len(circles)} centres | {bbox} mm | {size_str}")
            else:
                self.info_label.setText(
                    f"Chargé: {fname}{idx_info} ({len(circles)} centres)")
        except Exception as e:
            self.info_label.setText(f"Erreur: {str(e)[:50]}")
            return
        self.proposer_centrage(demander=ask)

    #: au-delà de cet écart à l'origine (mm), on propose de centrer
    SEUIL_CENTRAGE = 0.5

    def _reglage(self, cle: str, defaut=None):
        """Un réglage de l'application, s'il y en a une autour."""
        panneau = getattr(self.window(), 'params_panel', None)
        reglages = getattr(panneau, '_app_settings', None)
        if not isinstance(reglages, dict):
            return defaut
        return reglages.get(cle, defaut)

    def _memoriser_reglage(self, cle: str, valeur) -> None:
        panneau = getattr(self.window(), 'params_panel', None)
        reglages = getattr(panneau, '_app_settings', None)
        if isinstance(reglages, dict):
            reglages[cle] = valeur
            try:
                panneau.save_app_settings()
            except Exception:
                pass

    def _on_centrer_import_change(self, coche: bool) -> None:
        self._memoriser_reglage(
            'dxf_centrage', 'toujours' if coche else 'jamais')

    def proposer_centrage(self, demander: bool = True) -> bool:
        """Après un import: sélectionne tout le dessin importé (Alt+W
        centre alors la sélection en 0,0), et NE centre de lui-même
        que si « Centrer à l'import » est cochée.

        Rend vrai si le dessin a été centré."""
        n = self.canvas.selectionner_tout()
        centre = self.canvas.centre_dessin()
        coche = (getattr(self, 'centrer_import_cb', None) is not None
                 and self.centrer_import_cb.isChecked())
        if (coche and centre is not None
                and max(abs(centre[0]), abs(centre[1]))
                >= self.SEUIL_CENTRAGE):
            return self._centrer_maintenant()
        if n:
            self.info_label.setText(
                f"{self.info_label.text()} — {n} entité(s) "
                "sélectionnée(s); Alt+W pour les amener en 0,0")
        return False

    def _centrer_maintenant(self) -> bool:
        dx, dy = self.canvas.centrer_dessin()
        self.info_label.setText(
            f"{self.info_label.text()} — centré en 0 "
            f"(déplacé de {dx:+.2f}, {dy:+.2f})")
        return True

    def _repondre_centrage(self, centrer: bool) -> None:
        """Le clic sur le bandeau: on centre ou on laisse, et on
        retient si on l'a demandé."""
        self._bandeau_centrage.hide()
        if self._bandeau_retenir.isChecked():
            self._memoriser_reglage(
                'dxf_centrage', 'toujours' if centrer else 'jamais')
        if centrer:
            self._centrer_maintenant()

    def _append_dxf_file(self, filepath: str):
        """Superpose un DXF au dessin en place.

        Les entités et les centres déjà détectés — avec les Pz et Ø
        saisis dessus — sont conservés."""
        import os
        # le canvas superpose le fichier: ce qui était là reste dans
        # la scène (load_dxf effaçait tout, la liste seule était remise
        # — les entités d'avant disparaissaient de l'écran)
        try:
            self.canvas.load_dxf(filepath, ajouter=True)
        except Exception as e:
            self.info_label.setText(f"Erreur: {str(e)[:50]}")
            return
        merged = self.canvas.get_detected_circles()
        self.canvas.circles_detected.emit(merged)
        self.maj_onglets_imports()
        self._current_dxf_path = filepath
        self._dxf_dir = os.path.dirname(filepath)
        self.info_label.setText(
            f"Ajouté: {os.path.basename(filepath)} — "
            f"{len(self.canvas._dxf_items)} entités, "
            f"{len(merged)} centres")

    def _scan_dxf_folder(self, dirpath: str, current_file: str = ""):
        """Scanne le dossier pour trouver tous les .dxf triés par nom."""
        import os
        try:
            all_files = sorted(
                [f for f in os.listdir(dirpath)
                 if f.lower().endswith('.dxf')],
                key=str.lower)
            self._dxf_files = [
                os.path.join(dirpath, f) for f in all_files]
            # Trouver l'index du fichier courant
            self._dxf_index = -1
            if current_file:
                norm = os.path.normpath(current_file)
                for i, fp in enumerate(self._dxf_files):
                    if os.path.normpath(fp) == norm:
                        self._dxf_index = i
                        break
        except Exception:
            self._dxf_files = []
            self._dxf_index = -1

    def _on_prev_dxf(self):
        """Charge le DXF précédent dans le dossier."""
        if not self._dxf_files:
            if self._dxf_dir:
                self._scan_dxf_folder(self._dxf_dir)
            if not self._dxf_files:
                self.info_label.setText("Aucun fichier DXF dans le dossier")
                return
        idx = self._dxf_index - 1
        if idx < 0:
            idx = len(self._dxf_files) - 1
        self._load_dxf_file(self._dxf_files[idx], ask=False)

    def _on_next_dxf(self):
        """Charge le DXF suivant dans le dossier."""
        if not self._dxf_files:
            if self._dxf_dir:
                self._scan_dxf_folder(self._dxf_dir)
            if not self._dxf_files:
                self.info_label.setText("Aucun fichier DXF dans le dossier")
                return
        idx = self._dxf_index + 1
        if idx >= len(self._dxf_files):
            idx = 0
        self._load_dxf_file(self._dxf_files[idx], ask=False)

    def _on_clear_all(self):
        """Vide le canvas entier, après confirmation s'il y a de quoi."""
        from PySide6.QtWidgets import QMessageBox
        compte = self.canvas.compte_calques(
            getattr(self.window(), 'program', None))
        traces = sum(compte.get(c, 0)
                     for c in ('dxf', 'drawn', 'smb'))
        total = traces + compte.get('texte', 0)
        if total:
            reponse = QMessageBox.question(
                self, "Vider le canvas",
                f"Effacer {traces} tracé(s) et "
                f"{compte.get('texte', 0)} annotation(s) ?\n"
                f"Les opérations du programme ne sont pas touchées, "
                f"seulement leur aperçu.")
            if reponse != QMessageBox.StandardButton.Yes:
                return
        n = self.canvas.clear_all()
        self.info_label.setText(f"Canvas vidé ({n} élément(s))")

    def _on_grouper(self):
        """Réunit la sélection en un groupe."""
        n = self.canvas.grouper_selection()
        self.info_label.setText(
            f"{n} entités groupées" if n
            else "Sélectionnez au moins deux entités à grouper")

    def _on_ope_vers_dessin(self):
        """« Opé → dessin »: l'empreinte de l'opération courante."""
        fenetre = self.window()
        panneau = getattr(fenetre, 'operations_panel', None)
        op = None
        if panneau is not None:
            try:
                op = panneau.program.get_operation(panneau._current_index)
            except Exception:
                op = None
        if op is None:
            self.info_label.setText(
                "Opé → dessin: sélectionnez d'abord une opération")
            return
        n = self.canvas.entites_depuis_operation(op)
        if not n:
            self.info_label.setText(
                f"« {op.name} » n'a pas d'empreinte à dessiner")
            return
        self._montrer_calque('drawn') if hasattr(
            self, '_montrer_calque') else None
        self.info_label.setText(
            f"« {op.name} » posée en {n} entité(s) sur le calque Dessin "
            "— F2 pour la cote, flèches pour déplacer")

    def _on_centrer(self):
        """Le centre de la sélection en 0,0 — ou celui du dessin."""
        if self.canvas.centre_dessin() is None:
            self.info_label.setText("Rien à centrer: le dessin est vide")
            return
        (dx, dy), n = self.canvas.centrer_sur_selection()
        quoi = (f"la sélection ({n} entité(s))" if n
                else "le dessin entier")
        self.info_label.setText(
            f"Centré sur {quoi}: tout déplacé de {dx:+.2f}, {dy:+.2f}")

    def _on_miroir(self, axe: str):
        """Miroir de la sélection, sur place."""
        n = self.canvas.miroir_selection(axe)
        if not n:
            self.info_label.setText(
                "Miroir: sélectionnez d'abord ce qu'il faut retourner")
            return
        sens = ("gauche ↔ droite" if axe == 'vertical'
                else "haut ↕ bas" if axe == 'horizontal'
                else "demi-tour")
        self.info_label.setText(f"Miroir {sens}: {n} entité(s)")

    def _on_degrouper(self):
        """Défait les groupes de la sélection."""
        n = self.canvas.degrouper_selection()
        self.info_label.setText(
            f"{n} groupe(s) défait(s)" if n
            else "Aucun groupe dans la sélection")

    def _on_dupliquer(self):
        """Copie la sélection, décalée d'un pas: on voit la copie."""
        n = self.canvas.dupliquer_selection()
        self.info_label.setText(
            f"{n} élément(s) dupliqué(s)" if n
            else "Rien à dupliquer: sélectionnez d'abord")

    def _on_aller_dxf_to_op(self):
        fenetre = self.window()
        panneau = getattr(fenetre, 'circle_ops_panel', None)
        onglets = getattr(fenetre, '_col2_tabs', None)
        if panneau is not None and onglets is not None:
            onglets.setCurrentWidget(panneau)

    def _on_aller_symboles(self):
        fenetre = self.window()
        panneau = getattr(fenetre, 'symbol_panel', None)
        onglets = getattr(fenetre, '_col3_tabs', None)
        if panneau is not None and onglets is not None:
            onglets.setCurrentWidget(panneau)

    def _barre_du_bas(self) -> QWidget:
        """La barre sous le canvas: Fit · Import · Export · Grouper ·
        Dégrouper · Pas. La ligne d'état (X Y, message) est dessous."""
        from src.gui.icons import get_icon
        barre = QWidget()
        rangee = QHBoxLayout(barre)
        rangee.setContentsMargins(2, 2, 2, 2)
        rangee.setSpacing(3)

        def _poser(*widgets):
            for w in widgets:
                w.setParent(None)
                w.setVisible(True)
                rangee.addWidget(w)

        def _sep():
            trait = QFrame()
            trait.setFrameShape(QFrame.Shape.VLine)
            trait.setFixedWidth(1)
            rangee.addWidget(trait)

        self.import_btn.setText(" Importer un dessin")
        self.import_btn.setIcon(get_icon("import", 18))
        self.import_btn.setObjectName("primary")
        self.import_btn.setMinimumHeight(30)
        self.import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.import_btn.setStyleSheet(
            "QPushButton#primary { background: #89b4fa; color: #1e1e2e; "
            "font-weight: bold; font-size: 13px; border-radius: 5px; "
            "padding: 4px 12px; }"
            "QPushButton#primary:hover { background: #b4d0fb; }")
        self.import_btn.setToolTip(
            "Ouvrir un dessin (DXF, SVG, PDF, AI…) dans cet onglet")
        self.export_btn.setText("Export")
        # « Centrer à l'import »: décochée par défaut — le dessin
        # arrive où son auteur l'a laissé; Alt+W le recentre au
        # besoin sur la sélection
        if not hasattr(self, 'centrer_import_cb'):
            self.centrer_import_cb = QCheckBox("Centrer à l'import")
            self.centrer_import_cb.setToolTip(
                "Cochée: le dessin importé est ramené en X0 Y0.\n"
                "Décochée (défaut): il garde sa position; Alt+W "
                "amène alors la sélection (elle seule) en 0,0.")
            self.centrer_import_cb.setChecked(
                str(self._reglage('dxf_centrage', 'jamais')) == 'toujours')
            self.centrer_import_cb.toggled.connect(
                self._on_centrer_import_change)
        if not hasattr(self, 'vue3d_btn'):
            self.vue3d_btn = QPushButton("3D")
            self.vue3d_btn.setCheckable(True)
            self.vue3d_btn.setToolTip(
                "Voir en volume: la pièce STEP importée, le dessin à sa "
                "cote et les opérations à leur profondeur")
            self.vue3d_btn.toggled.connect(self.basculer_3d)
        _poser(self.zoom_fit_btn, self.vue3d_btn, self.import_btn,
               self.export_btn, self.centrer_import_cb)
        _sep()
        _poser(self.grouper_btn, self.degrouper_btn)
        _sep()
        _poser(self.centrer_btn, self.miroir_h_btn, self.miroir_v_btn)
        _sep()
        from src.gui.barre_outils import bloc
        _poser(bloc(self.pas_etiquette, self.pas_spin))
        rangee.addStretch()
        self._barre_bas = barre
        return barre

    @staticmethod
    def _barre_defilante(contenu: QWidget) -> QWidget:
        """Enferme une barre dans un cadre qui défile horizontalement.

        C'est LUI qui accepte de rétrécir, pas les boutons: la fenêtre
        n'est plus tenue par la longueur de la barre, et les boutons
        gardent leur largeur lisible."""
        from PySide6.QtWidgets import QScrollArea
        cadre = QScrollArea()
        cadre.setWidget(contenu)
        cadre.setWidgetResizable(True)
        cadre.setFrameShape(QFrame.Shape.NoFrame)
        cadre.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        cadre.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # La hauteur est réglée APRÈS remplissage: mesurée sur un
        # contenu vide, elle écrasait la barre à quelques pixels
        cadre.setMinimumHeight(0)
        cadre.setMinimumWidth(0)
        cadre.setSizePolicy(QSizePolicy.Policy.Ignored,
                            QSizePolicy.Policy.Fixed)
        return cadre

    def _ranger_outils_par_calque(self):
        """Chaque outil existant rejoint la boîte de son calque.

        Les widgets ne sont pas recréés: ils changent de parent. Tout
        ce qui les référence ailleurs (raccourcis, handlers, tests)
        continue de fonctionner."""
        def _poser(cle, *widgets):
            _boite, rangee = self._boites_calque[cle]
            for w in widgets:
                if w is None:
                    continue
                w.setParent(None)
                w.setVisible(True)
                rangee.addWidget(w)

        def _sep(cle):
            _boite, rangee = self._boites_calque[cle]
            trait = QFrame()
            trait.setFrameShape(QFrame.Shape.VLine)
            trait.setFixedWidth(1)
            rangee.addWidget(trait)

        # DXF: le fichier et sa sortie (Importer et Exporter sont
        # dans la barre du bas: on les cherche partout, ils sont
        # toujours là)
        _poser('dxf', self._prev_dxf_btn, self._next_dxf_btn,
               self.print_btn, self.clear_btn, self.nettoyer_btn)
        self.clear_btn.setText("Effacer le dessin")

        # Opé: ce que les opérations montrent
        _poser('ope', self.show_labels_btn, self.show_legend_btn,
               self.to_points_btn)

        # Dessin: la barre de dessin AU COMPLET
        from src.gui.barre_outils import bloc
        _poser('drawn', self.grid_cb, bloc(self.grid_spin, self.grid_unite),
               self.pick_btn, self.accroche_btn, self.ortho_btn)
        _sep('drawn')
        _poser('drawn', *[self.draw_buttons[t] for t in
                          ('line', 'circle', 'rect', 'bezier')
                          if t in self.draw_buttons])
        _poser('drawn', self.text_btn, self.texte_grave_btn)
        _sep('drawn')
        _poser('drawn', self.ruler_btn)
        _sep('drawn')
        _poser('drawn', self.ope_dessin_btn, self.contraintes_btn)
        _sep('drawn')
        for cle in self._ordre_retouches:
            if cle is None:
                _sep('drawn')
            else:
                _poser('drawn', self._boutons_retouche[cle])
        self.retouches_btn.setVisible(False)    # la barre le remplace

        # Annotations: poser, coter, déplacer
        _poser('texte', self.resize_btn, self.dup_btn, self.del_btn,
               self.cotes_btn)

        # Centres détectés
        _poser('centres', self.show_centers_btn, self.centres_ops_btn)

        # Symboles
        _poser('smb', self.smb_btn)

        for cle in self._boites_calque:
            _boite, rangee = self._boites_calque[cle]
            rangee.addStretch()

        # Une seule boîte ouverte à la fois; « Dessin » au départ
        self._calque_ouvert = ""
        self._on_calque_active('drawn')

    def _ajuster_hauteur_barres(self):
        """Chaque cadre défilant prend la hauteur de sa barre.

        Une barre d'outils mesure ~30 px; y ajouter la barre de
        défilement horizontale demande une quinzaine de pixels de
        plus, sinon elle recouvre les boutons. Depuis la barre
        unique, c'est elle qui s'ajuste."""
        barre = getattr(self, 'barre_outils', None)
        if barre is not None:
            barre.ajuster()
            return
        marge = 4 + self._barre_haut_cadre.horizontalScrollBar(
            ).sizeHint().height() if getattr(
                self, '_barre_haut_cadre', None) else 16
        haut = self._barre_haut_cadre
        if haut is not None:
            contenu = haut.widget()
            if contenu is not None:
                haut.setFixedHeight(
                    max(34, contenu.sizeHint().height()) + marge)
        bas = getattr(self, '_barre_bas_cadre', None)
        if bas is not None and bas.widget() is not None:
            bas.setFixedHeight(
                max(34, bas.widget().sizeHint().height()) + marge)
        cadre = getattr(self, '_boites_cadre', None)
        if cadre is None:
            return
        if not self._calque_ouvert:
            cadre.setVisible(False)
            return
        boite, _rangee = self._boites_calque[self._calque_ouvert]
        cadre.setVisible(True)
        cadre.setFixedHeight(
            max(34, boite.sizeHint().height()) + marge)

    def _on_calque_active(self, cle: str):
        """Clic sur le NOM d'un calque: déplier sa boîte, ou la
        replier si elle l'était déjà."""
        ferme = (self._calque_ouvert == cle)
        self._calque_ouvert = "" if ferme else cle
        for autre, (boite, _rangee) in self._boites_calque.items():
            boite.setVisible(autre == self._calque_ouvert)
        for autre, onglet in self._onglets_calque.items():
            onglet.set_ouvert(autre == self._calque_ouvert)
        self._boites_conteneur.setVisible(bool(self._calque_ouvert))
        self._ajuster_hauteur_barres()
        # Un calque dont on sort les outils doit être visible: on ne
        # dessine pas sur un calque masqué
        if self._calque_ouvert:
            onglet = self._onglets_calque.get(self._calque_ouvert)
            if onglet is not None and not onglet.est_visible():
                onglet.bouton_oeil.setChecked(True)

    def _on_calque_visible(self, cle: str, visible: bool):
        """Clic sur l'ŒIL d'un calque."""
        if cle == 'ope':
            self._on_show_all_ops_toggled(visible)
        elif cle == 'centres':
            self.canvas.set_centers_visible(visible)
        else:
            self.canvas.set_layer_visible(cle, visible)
        self.info_label.setText(
            f"Calque {cle}: {'visible' if visible else 'masqué'}")

    def _on_pas_change(self, valeur: float):
        """Le pas a changé au clavier: le champ suit."""
        if abs(self.pas_spin.value() - valeur) > 1e-9:
            self.pas_spin.blockSignals(True)
            self.pas_spin.setValue(valeur)
            self.pas_spin.blockSignals(False)
        self.info_label.setText(f"Pas de déplacement : {valeur:g} mm")

    def _focus_champ_pas(self):
        """Ctrl+flèche depuis le dessin: on vient régler le pas.

        Le champ prend le focus, tout sélectionné pour taper par-
        dessus; Entrée rendra le focus au dessin."""
        self.pas_spin.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.pas_spin.selectAll()
        self.info_label.setText(
            "Pas : tapez la valeur puis Entrée — les flèches "
            "déplaceront la sélection de ce pas")

    def _pas_valide_rend_le_focus(self):
        """Entrée dans le champ « Pas »: le dessin reprend le focus."""
        canvas = self.canvas
        if canvas is not None:
            canvas.set_nudge_step(self.pas_spin.value())
            canvas.setFocus(Qt.FocusReason.OtherFocusReason)
            self.info_label.setText(
                f"Pas de déplacement : {self.pas_spin.value():g} mm — "
                "les flèches déplacent la sélection")

    def _on_texte_grave_au_clic(self, x: float, y: float):
        """Outil « Texte gravé »: l'utilisateur a cliqué en (x, y).

        Le formulaire se souvient de la police et de la hauteur: on
        grave rarement une seule ligne."""
        from PySide6.QtWidgets import QDialog
        from src.gui.dialogs.texte_grave_dialog import TexteGraveDialog
        boite = TexteGraveDialog(self)
        if boite.exec() != QDialog.DialogCode.Accepted:
            return
        choix = boite.choix()
        item = self.canvas.add_texte_vectorise(
            choix['texte'], x, y, police=choix['police'],
            hauteur=choix['hauteur'],
            alignement=choix['alignement'])
        if item is None:
            self.info_label.setText(
                "Cette police ne donne aucun contour pour ce texte")
            return
        contours = len(item.path().toSubpathPolygons())
        self.info_label.setText(
            f"« {choix['texte']} » posé en {contours} contour(s) — "
            f"sélectionnez-le pour le graver")

    def _on_texte_au_clic(self, x: float, y: float):
        """Outil Texte: l'utilisateur a cliqué en (x, y)."""
        from PySide6.QtWidgets import QInputDialog
        texte, ok = QInputDialog.getText(
            self, "Annotation",
            f"Texte à poser en X={x:.2f} Y={y:.2f} :")
        if not ok or not texte.strip():
            return
        # Un repère posé SUR une entité la désigne: il lui est
        # rattaché et la suivra dans ses déplacements
        porteuse = self.canvas.entite_sous(x, y)
        item = self.canvas.add_text(
            texte.strip(), x, y, hauteur=self._hauteur_texte,
            attache_a=porteuse)
        if item is not None:
            self.canvas._scene.clearSelection()
            item.setSelected(True)
            attache = (" — rattaché à l'entité sous le texte"
                       if porteuse is not None else "")
            self.info_label.setText(
                f"« {texte.strip()} » posé{attache} — F2 pour la "
                f"cote, flèches pour le placer")

    #: hauteur de caractères retenue d'une annotation à l'autre
    _hauteur_texte = 5.0

    def _on_ajouter_texte(self):
        """Pose une annotation au centre de la vue."""
        from PySide6.QtWidgets import QInputDialog
        texte, ok = QInputDialog.getText(
            self, "Annotation", "Texte à poser sur le plan :")
        if not ok or not texte.strip():
            return
        hauteur, ok = QInputDialog.getDouble(
            self, "Annotation", "Hauteur des caractères (mm) :",
            5.0, 0.5, 100.0, 1)
        if not ok:
            return
        centre = self.canvas.mapToScene(
            self.canvas.viewport().rect().center())
        item = self.canvas.add_text(
            texte.strip(), centre.x(), -centre.y(), hauteur=hauteur)
        if item is not None:
            self.canvas._scene.clearSelection()
            item.setSelected(True)
            self.info_label.setText(
                f"« {texte.strip()} » posé — flèches pour le placer, "
                f"F2 pour la cote")

    def _on_redimensionner(self):
        """F2: met la sélection à la cote.

        La sélection se fait de deux façons — au pinceau pour les
        entités importées, par Qt pour ce qu'on a dessiné. F2 ne
        regardait que la seconde: cliquer un cercle du DXF puis
        appuyer sur F2 répondait « sélectionnez d'abord »."""
        from PySide6.QtWidgets import QDialog
        from src.gui.dialogs.redimensionner_dialog import (
            RedimensionnerDialog)
        items = self.canvas.selection_courante()
        if not items:
            self.info_label.setText(
                "F2 : sélectionnez d'abord quelque chose")
            return
        boite_englobante = None
        for item in items:
            rect = item.mapToScene(
                item.boundingRect()).boundingRect()
            boite_englobante = (rect if boite_englobante is None
                                else boite_englobante.united(rect))
        if boite_englobante is None or boite_englobante.isEmpty():
            return
        titre = (f"{len(items)} élément(s) sélectionné(s)"
                 if len(items) > 1 else "Élément sélectionné")
        dialogue = RedimensionnerDialog(
            self, boite_englobante.width(), boite_englobante.height(),
            boite_englobante.center().x(),
            -boite_englobante.center().y(), titre)
        if dialogue.exec() != QDialog.DialogCode.Accepted:
            return
        fx, fy = dialogue.facteurs()
        centre = boite_englobante.center()
        for item in items:
            # X et Y à des facteurs DIFFÉRENTS: `setScale` n'en tient
            # qu'un — la moyenne des deux ratait la cote demandée.
            # Une matrice, elle, sait étirer dans un seul sens.
            local = item.mapFromScene(centre)
            matrice = QTransform()
            matrice.translate(local.x(), local.y())
            matrice.scale(fx, fy)
            matrice.translate(-local.x(), -local.y())
            item.setTransform(matrice, True)
        angle = dialogue.rotation()
        if abs(angle) > 1e-9:
            # l'ensemble tourne sur lui-même: autour du centre de
            # l'emprise de la sélection
            self.canvas.tourner_items(items, angle, centre)
        vise = dialogue.centre_vise()
        if vise is not None:
            apres = None
            for item in items:
                r = item.mapToScene(item.boundingRect()).boundingRect()
                apres = r if apres is None else apres.united(r)
            dx = vise[0] - apres.center().x()
            dy = (-vise[1]) - apres.center().y()
            # Par le canvas: ce qui appartient aux entités (centre
            # marqué, annotation) doit suivre le déplacement
            self.canvas.deplacer_items(items, dx, dy)
        mesure = (f"×{fx:.3f}" if abs(fx - fy) < 1e-9
                  else f"×{fx:.3f} en X, ×{fy:.3f} en Y")
        if abs(angle) > 1e-9:
            mesure += f", tourné de {angle:g}°"
        self.info_label.setText(f"Redimensionné {mesure}")

    def _on_export(self):
        """Sort le dessin: quels calques, quelles couleurs, quel
        format. Le DXF n'est plus la seule porte de sortie."""
        import os
        from PySide6.QtWidgets import QDialog
        from src.gui.dialogs.export_dialog import ExportDessinDialog
        programme = getattr(self.window(), 'program', None)
        boite = ExportDessinDialog(
            self, self.canvas.compte_calques(programme))
        if boite.exec() != QDialog.DialogCode.Accepted:
            return
        choix = boite.choix()
        noms = {cle: nom for cle, nom, _b
                in self.canvas.CALQUES_EXPORT}
        base = os.path.join(self._dxf_dir or "",
                            "dessin" + choix['suffixe'])
        filepath, _ = QFileDialog.getSaveFileName(
            self, f"Exporter en {choix['format'].upper()}",
            base, choix['filtre'])
        if not filepath:
            return
        if not os.path.splitext(filepath)[1]:
            filepath += choix['suffixe']
        try:
            self.canvas.exporter(
                filepath, sortie=choix['format'],
                calques=choix['calques'], couleurs=choix['couleurs'],
                program=programme,
                titre=os.path.splitext(os.path.basename(filepath))[0])
            self._dxf_dir = os.path.dirname(filepath)
            retenu = ", ".join(noms.get(c, c).lower()
                               for c in choix['calques'])
            self.info_label.setText(
                f"{os.path.basename(filepath)} exporté — {retenu}")
        except Exception as e:
            self.info_label.setText(f"Erreur export: {str(e)[:60]}")

    def _on_print_a4(self):
        """Impression A4: orientation + échelle (auto ou imposée)."""
        import os
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QFormLayout, QComboBox,
            QDialogButtonBox, QLineEdit as _QLE)

        dlg = QDialog(self)
        dlg.setWindowTitle("Imprimer le canvas (A4)")
        v = QVBoxLayout(dlg)
        form = QFormLayout()
        orient = QComboBox()
        orient.addItem("Portrait", False)
        orient.addItem("Paysage", True)
        form.addRow("Orientation:", orient)
        scale_cb = QComboBox()
        scale_cb.addItem("Automatique (ajusté à la page)", 0.0)
        for s in self.canvas._PRINT_SCALES:
            label = (f"1:{s:g}  (1 mm papier = {s:g} mm pièce)"
                     if s >= 1 else f"{1 / s:g}:1  (agrandi)")
            scale_cb.addItem(label, float(s))
        form.addRow("Échelle:", scale_cb)
        title_edit = _QLE()
        title_edit.setPlaceholderText("(optionnel)")
        form.addRow("Titre:", title_edit)
        v.addLayout(form)

        # Les opérations imprimées sont celles dont l'ŒIL est ouvert
        # dans la liste: le choix se fait là, une fois pour toutes —
        # à l'écran comme sur le papier.

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        v.addWidget(btns)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        start_dir = self._dxf_dir or ""
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Imprimer en PDF",
            os.path.join(start_dir, "canvas_A4.pdf"),
            "Fichiers PDF (*.pdf)")
        if not filepath:
            return
        # Ne jamais écraser un PDF existant: on incrémente
        # (canvas_A4.pdf → canvas_A4 (2).pdf)
        base, ext = os.path.splitext(filepath)
        n = 2
        while os.path.exists(filepath):
            filepath = f"{base} ({n}){ext}"
            n += 1
        try:
            # Le plan montre les opérations dont l'œil est ouvert
            win = self.window()
            program = getattr(win, 'program', None)
            drawn = 0
            if program is not None:
                drawn = self.canvas.draw_all_operations(program)
            used = self.canvas.print_a4(
                filepath,
                landscape=bool(orient.currentData()),
                scale=float(scale_cb.currentData()),
                title=title_edit.text().strip())
            ratio = f"1:{used:g}" if used >= 1 else f"{1 / used:g}:1"
            self.info_label.setText(
                f"{os.path.basename(filepath)} — échelle {ratio}, "
                f"{drawn} opération(s)")
        except Exception as e:
            self.info_label.setText(f"Erreur impression: {str(e)[:60]}")

    def _on_clear(self):
        self.memoriser_imports()
        self.canvas.clear_dxf()
        self.maj_onglets_imports()
        self.info_label.setText("Canvas vidé")

    def _on_pick_toggled(self, checked: bool):
        self.canvas.set_pick_mode(checked)
        if checked:
            self.select_btn.setChecked(False)
            self.canvas.set_select_mode(False)
            for btn in self.draw_buttons.values():
                btn.setChecked(False)
            self.canvas.set_draw_tool(None)
            self.info_label.setText(
                "Mode Picker: cliquez pour récupérer X/Y")
        else:
            self.info_label.setText("")

    #: libellés des outils, pour la ligne d'état
    _NOMS_OUTILS = {'line': "Ligne", 'circle': "Cercle",
                    'rect': "Rectangle", 'bezier': "Polyligne",
                    'texte': "Texte",
                    'texte_grave': "Texte gravé"}

    def _on_draw_tool(self, tool_id: str):
        """Un outil de dessin s'arme ou se désarme.

        Sortir d'un outil REND la sélection: c'est le comportement par
        défaut du canvas, pas un mode à réarmer."""
        self.pick_btn.setChecked(False)
        self.canvas.set_pick_mode(False)

        boutons = dict(self.draw_buttons)
        boutons['texte'] = self.text_btn
        boutons['texte_grave'] = self.texte_grave_btn
        btn = boutons.get(tool_id)
        if btn and btn.isChecked():
            for tid, b in boutons.items():
                if tid != tool_id:
                    b.setChecked(False)
            self.canvas.set_select_mode(False)
            self.canvas.set_draw_tool(tool_id)
            nom = self._NOMS_OUTILS.get(tool_id, tool_id)
            aide = (" — double-clic pour fermer"
                    if tool_id == 'bezier' else
                    " — cliquez où poser le texte"
                    if tool_id == 'texte' else "")
            self.info_label.setText(
                f"Outil {nom}{aide} (Échap pour sortir)")
        else:
            self.canvas.set_draw_tool(None)
            self.canvas.set_select_mode(True)
            self.info_label.setText("Sélection")
            self.info_label.setText("")

    def _on_show_all_ops_toggled(self, checked: bool):
        """Affiche/masque toutes les opérations sur le canvas."""
        self.canvas.set_show_all_operations(checked)

    def _on_grid_step_changed(self, value: float):
        """Met à jour le pas de grille du canvas (grille redessinée)."""
        self.canvas.set_grid_spacing(value)

    def _on_ruler_toggled(self, checked: bool):
        """Active/désactive le mode règle."""
        if checked:
            self.canvas.set_draw_tool("ruler")
            self._ruler_label.setVisible(True)
            self._ruler_label.setText("Cliquez sur deux points pour mesurer")
            # Désactiver les autres modes
            self.pick_btn.setChecked(False)
            self.canvas.set_pick_mode(False)
            self.select_btn.setChecked(False)
            self.canvas.set_select_mode(False)
            for btn in self.draw_buttons.values():
                btn.setChecked(False)
        else:
            self.canvas.set_draw_tool(None)
            self._ruler_label.setVisible(False)

    def _on_ruler_measured(self, distance: float):
        """Callback quand la règle mesure une distance."""
        self._ruler_label.setText(f"Distance: {distance:.3f} mm")

    def _on_fit(self):
        self.canvas.fit_all()

    def _on_mouse_move(self, x: float, y: float):
        self.coord_label.setText(f"X: {x:.3f}  Y: {y:.3f}")

    def _on_coordinate_picked(self, x: float, y: float):
        self.coordinate_picked.emit(x, y)
        self.info_label.setText(f"Coordonnées pickées: X={x:.3f} Y={y:.3f}")

    def _on_select_toggled(self, checked: bool):
        """Active/désactive le mode sélection d'entités."""
        self.canvas.set_select_mode(checked)
        if checked:
            # Désactiver les autres modes
            self.pick_btn.setChecked(False)
            self.canvas.set_pick_mode(False)
            for btn in self.draw_buttons.values():
                btn.setChecked(False)
            self.canvas.set_draw_tool(None)
            self.info_label.setText(
                "Mode Sélection: cliquez pour sélectionner des entités")
        else:
            self.canvas.set_select_mode(False)
            self.to_points_btn.setEnabled(False)
            self.info_label.setText("")

    def revenir_selection(self) -> None:
        """Clic droit pendant un outil (règle, ligne, texte, pipette,
        outil à clic, cote, symbole): ses boutons se décochent et le
        canvas rend la sélection — comme Échap, sans lâcher la souris."""
        for b in [self.ruler_btn, self.pick_btn, self.text_btn,
                  self.texte_grave_btn, *self.draw_buttons.values()]:
            if b.isChecked():
                b.setChecked(False)
        self.canvas.quitter_outil()
        self._ruler_label.setVisible(False)
        self.info_label.setText("Sélection")

    def _on_selection_changed(self, count: int):
        """Mise à jour quand la sélection change."""
        self.to_points_btn.setEnabled(count > 0)
        if count > 0:
            self.info_label.setText(f"{count} entité(s) sélectionnée(s)")
            self.entites_choisies.emit()
        elif self.select_btn.isChecked():
            self.info_label.setText(
                "Mode Sélection: cliquez pour sélectionner des entités")

    def _on_entity_info(self, info: str):
        """Affiche les spécifications de l'entité sélectionnée."""
        if info:
            self.coord_label.setText(info)
        else:
            self.coord_label.setText("X: 0.000  Y: 0.000")

    def _on_send_selected_points(self):
        """Envoie les centres sélectionnés comme liste de points."""
        centers = self.canvas.get_selected_centers()
        if centers:
            self.selected_centers.emit(centers)
            self.info_label.setText(
                f"{len(centers)} centre(s) envoyé(s) vers l'opération")
