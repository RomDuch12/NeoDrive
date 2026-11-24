"""« Usinage 3D… »: la gamme de fraises qui usine la pièce STEP.

La fenêtre montre ce que la pièce demande, la gamme que le moteur
propose (src/core/usinage3d.proposer_gamme) — modifiable: outil,
stratégie, surépaisseur, passe Z, pas latéral — et pourquoi. « Calculer »
déroule toute la gamme (suivi dans la barre d'état, Annuler agit) et
dit ce qu'elle donne: longueurs, et le contrôle de la matière simulée
(aucune entaille, ce qui reste). « Ajouter au programme » rend une
opération « Séquence Datron » par étape, avec son outil.

Le BRUT réel (surépaisseurs dessus, dessous — la prise —, côtés) et la
TENUE de la pièce (src/core/tenue): étau avec prise sous la pièce,
squelette (cadre et ponts), ou plaque de reprise vissée par le dos.
Une pièce qu'une fraiseuse 3 axes n'usine pas d'une seule prise
(dessous, flancs, contre-dépouilles) ou dont la prise doit partir se
voit proposer ses PHASES: les bridages successifs, chacun avec sa
gamme, sa reprise (retournement et palpage) et son zéro; chaque phase
reprend la matière que les précédentes ont laissée. À droite, la phase
choisie en 3D: la pièce comme elle est bridée, ce qui la tient, et
après calcul la matière qui reste et les parcours.
"""

from typing import Dict, List, Optional

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QTableWidget, QHeaderView,
                               QComboBox, QAbstractItemView, QCheckBox,
                               QFrame, QGroupBox, QGridLayout,
                               QScrollArea, QStackedWidget, QSpinBox,
                               QSplitter, QWidget)

from src.gui.widgets import SpinCote

COL_NOM, COL_OUTIL, COL_STRAT, COL_SUREP, COL_PASSE, COL_LAT = range(6)
STRATEGIES = {"niveaux": "Par niveaux", "balayage": "Balayage",
              "zconstant": "Z constant (parois)"}
ROLES = {"ebauche": "Ébauche", "reprise": "Reprise", "finition": "Finition"}


def _spin(valeur: float, maxi: float = 100.0, decimales: int = 2,
          mini: float = 0.0, bulle: str = "") -> SpinCote:
    sp = SpinCote(decimales=decimales)
    sp.setRange(mini, maxi)
    sp.setValue(float(valeur))
    sp.setMaximumWidth(70)
    if bulle:
        sp.setToolTip(bulle)
    return sp


class _ColonneDefilante(QScrollArea):
    """Une colonne qui défile en hauteur, jamais plus étroite que son
    contenu (lu à l'affichage: avant, les polices ne sont pas posées)."""

    def minimumSizeHint(self) -> QSize:
        base = super().minimumSizeHint()
        w = self.widget()
        if w is None:
            return base
        return QSize(w.minimumSizeHint().width()
                     + self.verticalScrollBar().sizeHint().width() + 2,
                     base.height())


class DialogueUsinage3D(QDialog):

    def __init__(self, modele, placement, bibliotheque, nom_piece="pièce",
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Usinage 3D de la pièce STEP")
        self.resize(1240, 760)
        self.modele = modele
        self.placement = placement
        self.bibliotheque = bibliotheque
        self.nom_piece = nom_piece
        self.resultat: Optional[Dict] = None
        self.gamme: List[Dict] = []
        # les phases: plan, gamme et raisons de chacune (par clé)
        self.calcul_phases: Optional[Dict] = None
        self.gammes: Dict[str, List[Dict]] = {}
        self.pourquois: Dict[str, List[str]] = {}
        self._cle_affichee = 'Z+'
        self._placement_plaque: Optional[Dict] = None
        self._en_construction = True

        from src.core import usinage3d
        from src.core import tenue as tn
        a = usinage3d.analyser(modele, placement)
        b = modele.bornes()
        rc = a['rayon_coin']
        self.analyse = QLabel(
            f"Pièce {b[3] - b[0]:.1f} × {b[4] - b[1]:.1f} × "
            f"{a['profondeur']:.2f} mm · plus petit rayon de coin: "
            + (f"R{rc:g}" if rc < 1e9 else "aucun") + " · surfaces "
            f"gauches: {a['surfaces_gauches']}")
        self.analyse.setWordWrap(True)

        try:
            self.plan = usinage3d.planifier_phases(modele, placement)
        except Exception:   # pièce sans faces lues: une seule prise
            self.plan = {'phases': [{'cle': 'Z+', 'libelle': 'dessus',
                                     'faces': [], 'bridage': '',
                                     'zero': ''}], 'non_usinables': []}
        self.phases: List[Dict] = list(self.plan['phases'])

        # ── le brut et la tenue ──
        brut = tn.brut_defaut()
        defaut = tn.tenue_defaut()
        self.sp_dessus = _spin(brut['dessus'], 50, bulle=(
            "Surépaisseur du brut au-dessus de la pièce (surfacée en "
            "phase 1; le zéro Z est sur le dessus du brut)"))
        self.sp_dessous = _spin(brut['dessous'], 50, bulle=(
            "Le brut sous la pièce: la PRISE serrée en phase 1, enlevée "
            "en phase retournée"))
        self.sp_cotes = _spin(brut['cotes'], 100, bulle=(
            "Surépaisseur du brut de chaque côté en X et Y"))
        self.mode = QComboBox()
        for cle, libelle in tn.MODES:
            self.mode.addItem(libelle, cle)
        self.mode.setToolTip("Comment la pièce tient pendant l'usinage")
        self.pile = QStackedWidget()
        # étau
        p_etau = QWidget()
        g_etau = QGridLayout(p_etau)
        g_etau.setContentsMargins(0, 0, 0, 0)
        self.sp_jeu_mors = _spin(defaut['jeu_mors'], 20, bulle=(
            "L'outil reste à cette hauteur au-dessus des mors"))
        self.sp_serrage = _spin(defaut['serrage_reprise'], 50, bulle=(
            "Hauteur serrée par les mors en reprise (sur les flancs "
            "usinés de la pièce, ou du cadre)"))
        g_etau.addWidget(QLabel("Jeu au-dessus des mors"), 0, 0)
        g_etau.addWidget(self.sp_jeu_mors, 0, 1)
        g_etau.addWidget(QLabel("Serrage en reprise"), 0, 2)
        g_etau.addWidget(self.sp_serrage, 0, 3)
        # l'étau autocentré ou le mandrin de l'atelier
        self.serrage = QComboBox()
        self.serrage.setToolTip(
            "L'étau autocentré ou le mandrin: dessiné autour de la pièce "
            "(phases, Canva 3D) et vérifié (course, collisions)")
        b_serrages = QPushButton("Étaux et mandrins…")
        b_serrages.clicked.connect(self._editer_serrages)
        g_etau.addWidget(QLabel("Étau / mandrin"), 1, 0)
        g_etau.addWidget(self.serrage, 1, 1, 1, 2)
        g_etau.addWidget(b_serrages, 1, 3)
        g_etau.setColumnStretch(4, 1)
        self._remplir_serrages()
        self.serrage.currentIndexChanged.connect(self._tenue_changee)
        # squelette
        p_sq = QWidget()
        g_sq = QGridLayout(p_sq)
        g_sq.setContentsMargins(0, 0, 0, 0)
        self.sp_cadre = _spin(defaut['largeur_cadre'], 100, bulle=(
            "Largeur du cadre gardé autour de la pièce (ses flancs "
            "extérieurs sont usinés pour le palpage)"))
        self.sp_ponts = QSpinBox()
        self.sp_ponts.setRange(0, 16)
        self.sp_ponts.setValue(int(defaut['ponts']))
        self.sp_ponts.setToolTip("Nombre de ponts entre la pièce et le "
                                 "cadre (0: une peau, ou rien)")
        self.sp_l_pont = _spin(defaut['largeur_pont'], 50)
        self.sp_h_pont = _spin(defaut['hauteur_pont'], 50)
        self.sp_peau = _spin(defaut['peau'], 10, bulle=(
            "Sans ponts: une peau de cette épaisseur au fond, entre la "
            "pièce et le cadre (0: la pièce se libère)"))
        for k, (texte, w) in enumerate((("Cadre", self.sp_cadre),
                                        ("Ponts", self.sp_ponts),
                                        ("largeur", self.sp_l_pont),
                                        ("hauteur", self.sp_h_pont),
                                        ("Peau", self.sp_peau))):
            g_sq.addWidget(QLabel(texte), 0, 2 * k)
            g_sq.addWidget(w, 0, 2 * k + 1)
        g_sq.setColumnStretch(10, 1)
        # plaque
        p_pl = QWidget()
        g_pl = QGridLayout(p_pl)
        g_pl.setContentsMargins(0, 0, 0, 0)
        self.plaque = QComboBox()
        self.plaque.setMinimumWidth(180)
        self.plaques_btn = QPushButton("Plaques…")
        self.plaques_btn.setToolTip("L'éditeur des plaques de reprise "
                                    "(motifs de trous, import DXF)")
        self.plaques_btn.clicked.connect(self._editer_plaques)
        from src.operations.taraudage import THREAD_TYPES
        self.filetage = QComboBox()
        self.filetage.addItems(list(THREAD_TYPES))
        self.filetage.setCurrentText(defaut['filetage'])
        self.sp_taraudage = _spin(defaut['profondeur_taraudage'], 50,
                                  bulle="Profondeur du filet au dos")
        self.cb_avant_trou = QCheckBox("avant-trou")
        self.cb_avant_trou.setChecked(bool(defaut['avant_trou']))
        self.cb_avant_trou.setToolTip(
            "Percer au Ø de perçage du filet (M4: 3,3) avant le filet; "
            "décoché: le taraudage seul")
        self.sp_vis = QSpinBox()
        self.sp_vis.setRange(1, 24)
        self.sp_vis.setValue(int(defaut['nombre_vis']))
        self.sp_vis.setToolTip("Nombre de vis au plus (les plus écartées)")
        self.vis_label = QLabel("")
        self.vis_label.setWordWrap(True)
        self.vis_main_btn = QPushButton("Vis à la main…")
        self.vis_main_btn.setToolTip(
            "Choisir soi-même les trous de la plaque où vont les vis (et "
            "où le brut se pose); « Automatique » y revient")
        # (lambda: Qt glisserait `checked` dans `executer`)
        self.vis_main_btn.clicked.connect(lambda: self._vis_a_la_main())
        #: le placement choisi à la main (None: l'automatique), et la
        #: plaque pour laquelle il vaut
        self._vis_manuelles = None
        g_pl.addWidget(QLabel("Plaque"), 0, 0)
        g_pl.addWidget(self.plaque, 0, 1)
        g_pl.addWidget(self.plaques_btn, 0, 2)
        g_pl.addWidget(QLabel("Filet"), 0, 3)
        g_pl.addWidget(self.filetage, 0, 4)
        g_pl.addWidget(self.sp_taraudage, 0, 5)
        g_pl.addWidget(self.cb_avant_trou, 0, 6)
        g_pl.addWidget(QLabel("vis"), 0, 7)
        g_pl.addWidget(self.sp_vis, 0, 8)
        g_pl.addWidget(self.vis_label, 1, 0, 1, 8)
        g_pl.addWidget(self.vis_main_btn, 1, 8)
        g_pl.setColumnStretch(9, 1)
        for page in (p_etau, p_sq, p_pl):
            self.pile.addWidget(page)
        self.palpage = QComboBox()
        for cle, libelle in tn.PALPAGES:
            self.palpage.addItem(libelle, cle)
        self.palpage.setToolTip(
            "Le palpage d'une reprise: la nouvelle origine (et le Z) de "
            "la pièce retournée ou revissée")
        self.sp_palpage = _spin(defaut['profondeur_palpage'], 50, bulle=(
            "Profondeur de palpage des flancs, sous le dessus"))
        self.cb_palpage1 = QCheckBox("palper aussi la phase 1")
        groupe = QGroupBox("Brut et tenue de la pièce")
        gb = QGridLayout(groupe)
        gb.setContentsMargins(6, 4, 6, 4)
        lb = QHBoxLayout()
        for texte, w in (("Brut: dessus", self.sp_dessus),
                         ("prise dessous", self.sp_dessous),
                         ("côtés", self.sp_cotes)):
            lb.addWidget(QLabel(texte))
            lb.addWidget(w)
        lb.addStretch()
        gb.addLayout(lb, 0, 0, 1, 2)
        gb.addWidget(QLabel("Tenue"), 1, 0)
        gb.addWidget(self.mode, 1, 1)
        gb.addWidget(self.pile, 2, 0, 1, 2)
        lpal = QHBoxLayout()
        lpal.addWidget(QLabel("Palpage des reprises"))
        lpal.addWidget(self.palpage)
        lpal.addWidget(self.sp_palpage)
        lpal.addWidget(self.cb_palpage1)
        lpal.addStretch()
        gb.addLayout(lpal, 3, 0, 1, 2)
        gb.setColumnStretch(1, 1)
        self.groupe_tenue = groupe

        # ── les phases ──
        self.phases_label = QLabel("")
        self.phases_label.setWordWrap(True)
        self.toutes_phases = QCheckBox("Usiner toutes les phases "
                                       "(bridages et reprises)")
        self.toutes_phases.setToolTip(
            "Chaque phase part de la matière que les précédentes ont "
            "laissée; au programme, une reprise entre deux phases pour "
            "retourner, brider et palper la pièce")
        self.toutes_phases.toggled.connect(self._oublier_resultat)
        self.phase_combo = QComboBox()
        self.phase_combo.currentIndexChanged.connect(self._changer_phase)
        self.bridage_label = QLabel("")
        self.bridage_label.setWordWrap(True)
        self.bridage_label.setStyleSheet("color: #89dceb;")
        cadre = QFrame()
        cadre.setFrameShape(QFrame.Shape.StyledPanel)
        vp = QVBoxLayout(cadre)
        vp.setContentsMargins(6, 4, 6, 4)
        vp.addWidget(self.phases_label)
        lp = QHBoxLayout()
        lp.addWidget(QLabel("Gamme de la"))
        lp.addWidget(self.phase_combo, 1)
        lp.addWidget(self.toutes_phases)
        vp.addLayout(lp)
        vp.addWidget(self.bridage_label)
        # les contre-dépouilles: la fraise en T y entre par le côté
        self.cb_tslot = QCheckBox("Contre-dépouilles à la fraise en T")
        self.cb_tslot.setToolTip(
            "Les faces qui regardent vers le bas sous un surplomb (plafond "
            "de rainure, dessous de collerette): une fraise en T de la "
            "bibliothèque y entre par le côté, son col dans ce qui est "
            "ouvert, son disque sous le surplomb — dans la phase du dessus")
        self.cb_tslot.setChecked(True)
        self.cb_tslot.toggled.connect(self._oublier_resultat)
        vp.addWidget(self.cb_tslot)
        self.cadre_phases = cadre
        #: le calcul des contre-dépouilles (usinage_tslot.proposer)
        self.tslot = None

        # ── la précision du calcul (réglée par l'utilisateur) ──
        self.precision = QComboBox()
        for cle_p, (libelle, _pas, _tol) in usinage3d.PRECISIONS.items():
            self.precision.addItem(libelle, cle_p)
        self.precision.setToolTip(
            "La finesse de la carte de hauteurs sur laquelle le moteur "
            "calcule: plus fine, les parcours suivent la pièce de plus "
            "près (petits rayons, fentes étroites), mais le calcul est "
            "plus long. « Auto » la règle d'après la taille de la pièce: "
            "très fine sur une petite pièce (jusqu'à 0,04 mm), plus "
            "grossière sur une grande — c'est là que la régler compte.")
        self.sp_pas = _spin(0.1, 2.0, 3, 0.02, bulle=(
            "Pas de la carte de hauteurs (mm): l'écart entre deux points "
            "où la pièce est mesurée"))
        self.sp_tolerance = _spin(usinage3d.TOLERANCE, 0.2, 3, 0.001, bulle=(
            "Tolérance des parcours (mm): l'écart permis quand une suite "
            "de petits segments est simplifiée"))
        self.precision_info = QLabel("")
        self.precision_info.setWordWrap(True)
        self.precision_info.setStyleSheet("color: #a6adc8; font-size: 11px;")
        self._lire_reglage_precision()
        self.precision.currentIndexChanged.connect(self._precision_changee)
        self.sp_pas.valueChanged.connect(self._precision_changee)
        self.sp_tolerance.valueChanged.connect(self._precision_changee)
        self._precision_changee()

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Étape", "Outil", "Stratégie", "Surép.", "Passe Z", "Pas lat."])
        self.table.verticalHeader().setVisible(False)
        # trois étapes visibles au moins (la fenêtre est chargée)
        self.table.setMinimumHeight(118)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hdr.resizeSection(COL_NOM, 90)
        hdr.resizeSection(COL_OUTIL, 230)
        hdr.resizeSection(COL_STRAT, 110)

        self.pourquoi = QLabel("")
        self.pourquoi.setWordWrap(True)
        self.pourquoi.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.pourquoi.setStyleSheet("color: #a6adc8;")
        self.bilan = QLabel("")
        self.bilan.setWordWrap(True)
        self.bilan.setStyleSheet("color: #a6e3a1;")

        self.proposer_btn = QPushButton("Proposer la gamme")
        self.proposer_btn.setToolTip(
            "Le moteur choisit les outils d'après la pièce et la "
            "bibliothèque")
        self.proposer_btn.clicked.connect(self.proposer)
        self.plus_btn = QPushButton("+ Étape")
        self.plus_btn.clicked.connect(self._ajouter_etape)
        self.moins_btn = QPushButton("− Étape")
        self.moins_btn.clicked.connect(self._retirer_etape)
        self.calculer_btn = QPushButton("Calculer")
        self.calculer_btn.setObjectName("primary")
        self.calculer_btn.clicked.connect(self.calculer)
        self.ajouter_btn = QPushButton("Ajouter au programme")
        self.ajouter_btn.setEnabled(False)
        self.ajouter_btn.clicked.connect(self.accept)
        fermer = QPushButton("Fermer")
        fermer.clicked.connect(self.reject)

        # ── la phase en 3D ──
        from src.gui.canvas3d import VueScene
        self.vue = VueScene(self)
        self.vue.setMinimumWidth(360)
        self.vue_info = QLabel("")
        self.vue_info.setWordWrap(True)
        self.vue_info.setStyleSheet("color: #a6adc8; font-size: 10px;")
        self.canva3d_btn = QPushButton("Montrer au Canva 3D")
        self.canva3d_btn.setToolTip(
            "La phase choisie dans le Canva 3D de la fenêtre (« ↻ » y "
            "revient à la pièce et au programme)")
        self.canva3d_btn.clicked.connect(self.montrer_au_canva3d)
        vues = QHBoxLayout()
        for texte, action in (("Iso", self.vue.vue_iso),
                              ("Dessus", self.vue.vue_dessus),
                              ("Face", self.vue.vue_face)):
            bouton = QPushButton(texte)
            bouton.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            bouton.clicked.connect(action)
            vues.addWidget(bouton)
        vues.addStretch()
        vues.addWidget(self.canva3d_btn)
        droite = QWidget()
        vd = QVBoxLayout(droite)
        vd.setContentsMargins(0, 0, 0, 0)
        vd.addLayout(vues)
        vd.addWidget(self.vue, 1)
        vd.addWidget(self.vue_info)

        haut = QHBoxLayout()
        haut.addWidget(self.proposer_btn)
        haut.addWidget(self.plus_btn)
        haut.addWidget(self.moins_btn)
        haut.addStretch()
        bas = QHBoxLayout()
        bas.addStretch()
        bas.addWidget(self.calculer_btn)
        bas.addWidget(self.ajouter_btn)
        bas.addWidget(fermer)
        gauche = QWidget()
        v = QVBoxLayout(gauche)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.analyse)
        v.addWidget(self.groupe_tenue)
        v.addWidget(self.cadre_phases)
        lprec = QHBoxLayout()
        lprec.addWidget(QLabel("Précision du calcul"))
        lprec.addWidget(self.precision)
        lprec.addWidget(QLabel("pas"))
        lprec.addWidget(self.sp_pas)
        lprec.addWidget(QLabel("tolérance"))
        lprec.addWidget(self.sp_tolerance)
        lprec.addWidget(self.precision_info, 1)
        v.addLayout(lprec)
        v.addLayout(haut)
        v.addWidget(self.table, 1)
        v.addWidget(self.pourquoi)
        v.addWidget(self.bilan)
        # la colonne de gauche défile plutôt que d'écraser ses réglages
        # (la fenêtre en porte beaucoup: tenue, phases, précision, gamme)
        defil = _ColonneDefilante()
        defil.setWidgetResizable(True)
        defil.setFrameShape(QFrame.Shape.NoFrame)
        defil.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        defil.setWidget(gauche)
        self.defil_gauche = defil
        coupe = QSplitter(Qt.Orientation.Horizontal)
        coupe.addWidget(defil)
        coupe.addWidget(droite)
        coupe.setStretchFactor(0, 3)
        coupe.setStretchFactor(1, 2)
        racine = QVBoxLayout(self)
        racine.addWidget(coupe, 1)
        racine.addLayout(bas)

        # les réglages qui changent les phases
        for sp in (self.sp_dessus, self.sp_dessous, self.sp_cotes,
                   self.sp_jeu_mors, self.sp_serrage, self.sp_cadre,
                   self.sp_l_pont, self.sp_h_pont, self.sp_peau,
                   self.sp_palpage, self.sp_taraudage):
            sp.valueChanged.connect(self._tenue_changee)
        for sp in (self.sp_ponts, self.sp_vis):
            sp.valueChanged.connect(self._tenue_changee)
        for combo in (self.mode, self.plaque, self.filetage, self.palpage):
            combo.currentIndexChanged.connect(self._tenue_changee)
        for cb in (self.cb_avant_trou, self.cb_palpage1):
            cb.toggled.connect(self._tenue_changee)
        self._remplir_plaques()
        self._en_construction = False
        self._refaire_phases(proposer=True)
        self.toutes_phases.setChecked(len(self.phases) > 1)

    # ── la précision ──

    CLE_REGLAGE = 'usinage3d/precision'

    def _lire_reglage_precision(self) -> None:
        from src.core import usinage3d
        try:
            from src.gui.theme import reglages_qt
            r = reglages_qt()
            cle = str(r.value(self.CLE_REGLAGE, 'auto') or 'auto')
            pas = float(r.value(self.CLE_REGLAGE + '_pas', 0.1) or 0.1)
            tol = float(r.value(self.CLE_REGLAGE + '_tolerance',
                                usinage3d.TOLERANCE) or usinage3d.TOLERANCE)
        except Exception:
            cle, pas, tol = 'auto', 0.1, usinage3d.TOLERANCE
        if cle not in usinage3d.PRECISIONS:
            cle = 'auto'
        self.precision.setCurrentIndex(self.precision.findData(cle))
        if cle == 'mesure':
            self.sp_pas.setValue(pas)
            self.sp_tolerance.setValue(tol)

    def lire_precision(self):
        """(pas de la carte en mm ou None = auto, tolérance en mm)."""
        from src.core import usinage3d
        cle = self.precision.currentData() or 'auto'
        if cle == 'mesure':
            return self.sp_pas.value(), self.sp_tolerance.value()
        _lib, pas, tol = usinage3d.PRECISIONS[cle]
        return pas, tol

    def _precision_changee(self, *_a) -> None:
        from src.core import usinage3d
        cle = self.precision.currentData() or 'auto'
        sur_mesure = cle == 'mesure'
        self.sp_pas.setEnabled(sur_mesure)
        self.sp_tolerance.setEnabled(sur_mesure)
        try:
            marge = usinage3d._marge(self.lire_gamme()) if hasattr(
                self, 'table') else 4.0
        except Exception:
            marge = 4.0
        if not sur_mesure:
            _lib, pas, tol = usinage3d.PRECISIONS[cle]
            for sp, val in ((self.sp_pas, pas if pas is not None else
                             usinage3d.pas_auto(self.modele, marge)),
                            (self.sp_tolerance, tol)):
                sp.blockSignals(True)
                sp.setValue(float(val))
                sp.blockSignals(False)
        pas, _tol = self.lire_precision()
        est = usinage3d.estimer_precision(self.modele, pas, marge)
        cases = est['cases']
        compte = (f"{cases / 1e6:.2f} M" if cases >= 1e6
                  else f"{cases / 1e3:.0f} k")
        court = f"{est['pas']:.3g} mm · {compte} cases"
        long = (f"Carte au pas de {est['pas']:.3g} mm: "
                f"{cases:,} cases".replace(",", " "))
        if cle != 'auto' and abs(est['facteur'] - 1) > 0.05:
            court += f" · ×{est['facteur']:.1f} l'auto"
            long += f", calcul ≈ ×{est['facteur']:.1f} le temps de l'auto"
        if est['grossi']:
            court += " · grossi"
            long += (f" — trop de cases pour cette pièce: le pas sera "
                     f"porté à {est['pas']:.3g} mm")
        self.precision_info.setText(court)
        self.precision_info.setToolTip(long + ".")
        try:
            from src.gui.theme import reglages_qt
            r = reglages_qt()
            r.setValue(self.CLE_REGLAGE, cle)
            if sur_mesure:
                r.setValue(self.CLE_REGLAGE + '_pas', self.sp_pas.value())
                r.setValue(self.CLE_REGLAGE + '_tolerance',
                           self.sp_tolerance.value())
        except Exception:
            pass
        if not self._en_construction:
            self._oublier_resultat()

    # ── le brut et la tenue ──

    def lire_brut(self) -> Dict:
        return {'dessus': self.sp_dessus.value(),
                'dessous': self.sp_dessous.value(),
                'cotes': self.sp_cotes.value()}

    def lire_tenue(self) -> Dict:
        from src.core import tenue as tn
        t = tn.tenue_defaut()
        t.update({'mode': self.mode.currentData() or 'etau',
                  'jeu_mors': self.sp_jeu_mors.value(),
                  'serrage_reprise': self.sp_serrage.value(),
                  'largeur_cadre': self.sp_cadre.value(),
                  'ponts': self.sp_ponts.value(),
                  'largeur_pont': self.sp_l_pont.value(),
                  'hauteur_pont': self.sp_h_pont.value(),
                  'peau': self.sp_peau.value(),
                  'palpage': self.palpage.currentData() or 'aucun',
                  'profondeur_palpage': self.sp_palpage.value(),
                  'palpage_phase1': self.cb_palpage1.isChecked(),
                  'filetage': self.filetage.currentText(),
                  'profondeur_taraudage': self.sp_taraudage.value(),
                  'avant_trou': self.cb_avant_trou.isChecked(),
                  'nombre_vis': self.sp_vis.value(),
                  'plaque': self.plaque.currentData(),
                  'serrage': self.serrage.currentData()})
        if t['mode'] == 'plaque' and self._placement_plaque is not None:
            t['_vis_placement'] = self._placement_plaque
            t['_vis'] = self._placement_plaque.get('vis') or []
        return t

    def _remplir_serrages(self, choisir: str = None) -> None:
        from src.core import serrages as sg
        actuel = choisir or self.serrage.currentText()
        self.serrage.blockSignals(True)
        self.serrage.clear()
        self.serrage.addItem("(mors génériques)", None)
        for nom, chemin in sg.lister():
            self.serrage.addItem(nom, sg.charger(chemin))
        i = self.serrage.findText(actuel)
        self.serrage.setCurrentIndex(i if i >= 0 else 0)
        self.serrage.blockSignals(False)

    def _editer_serrages(self) -> None:
        from src.gui.dialogs.serrages_dialog import DialogueSerrages
        dlg = DialogueSerrages(self, self.serrage.currentText())
        dlg.exec()
        self._remplir_serrages(dlg.choisi or None)
        self._tenue_changee()

    def _remplir_plaques(self) -> None:
        from src.core import plaques as pl
        actuel = self.plaque.currentText()
        self.plaque.blockSignals(True)
        self.plaque.clear()
        for nom, chemin in pl.lister():
            self.plaque.addItem(nom, pl.charger(chemin))
        i = self.plaque.findText(actuel)
        if i >= 0:
            self.plaque.setCurrentIndex(i)
        self.plaque.blockSignals(False)

    def _vis_a_la_main(self, executer: bool = True):
        """« Vis à la main… »: les trous de la plaque où vont les vis.
        Rend la fenêtre (les tests la pilotent: executer=False)."""
        from src.gui.dialogs.vis_dialog import DialogueVis
        plaque = self.plaque.currentData()
        if not plaque:
            return None
        dlg = DialogueVis(self.modele, self.lire_brut(), self.lire_tenue(),
                          plaque, self._placement_plaque, self)
        if executer and dlg.exec():
            self.appliquer_vis(dlg)
        return dlg

    def appliquer_vis(self, dlg) -> None:
        place = dlg.placement()
        plaque = self.plaque.currentData() or {}
        self._vis_manuelles = (None if place is None else {
            'plaque': plaque.get('nom'), 'position': place['position'],
            'trous': [list(t) for t in dlg.choisis]})
        self._tenue_changee()

    def _editer_plaques(self) -> None:
        from src.gui.dialogs.plaques_dialog import DialoguePlaques
        dlg = DialoguePlaques(self, self.plaque.currentText())
        dlg.exec()
        self._remplir_plaques()
        if dlg.choisie:
            i = self.plaque.findText(dlg.choisie)
            if i >= 0:
                self.plaque.setCurrentIndex(i)
        self._tenue_changee()

    def _placer_sur_plaque(self) -> None:
        """Où le brut se pose sur la plaque, et ses vis (affiché)."""
        from src.core import tenue as tn
        self._placement_plaque = None
        if (self.mode.currentData() != 'plaque'):
            self.vis_label.setText("")
            return
        plaque = self.plaque.currentData()
        if not plaque:
            self.vis_label.setText(
                "Aucune plaque: créez-en une (« Plaques… »), ou posez ses "
                "fichiers dans le dossier « Plaques de reprise ».")
            self.vis_label.setStyleSheet("color: #f9e2af;")
            return
        t = self.lire_tenue()
        t.pop('_vis_placement', None)
        manuel = self._vis_manuelles
        if manuel is not None and manuel.get('plaque') == plaque.get('nom'):
            # les vis choisies à la main, revérifiées (la tenue a pu
            # changer: filet plus profond, autre brut)
            place = tn.vis_a_la_main(self.modele, self.lire_brut(), t,
                                     plaque, manuel['position'],
                                     manuel['trous'])
        else:
            self._vis_manuelles = None
            place = tn.placer_sur_plaque(self.modele, self.lire_brut(), t,
                                         plaque)
        self._placement_plaque = place
        if not place['vis']:
            self.vis_label.setText(
                "Aucune vis possible: il faut un dos plat, assez épais "
                f"pour {self.sp_taraudage.value():g} mm de filet + 1, à "
                "1,5 mm des bords, au-dessus d'un trou de la plaque.")
            self.vis_label.setStyleSheet("color: #f38ba8;")
            return
        x, y = place['position']
        self.vis_label.setText(
            f"{len(place['vis'])} vis {self.filetage.currentText()} "
            + ("choisies à la main " if place.get('manuel') else "")
            + f"({place['n_possibles']} trous possibles sous la pièce) — "
            f"centre du brut en X {x:g} Y {y:g} sur la plaque"
            + (f" — {len(place['refuses'])} trou(s) choisi(s) sans dos "
               "vissable, ignoré(s)" if place.get('refuses') else ""))
        self.vis_label.setStyleSheet("color: #a6e3a1;")

    def _tenue_changee(self, *_a) -> None:
        if self._en_construction:
            return
        self.pile.setCurrentIndex(max(0, self.mode.currentIndex()))
        self._placer_sur_plaque()
        self._refaire_phases()

    def _refaire_phases(self, proposer: bool = False) -> None:
        """Les phases que la tenue impose (dans son ordre), au combo."""
        from src.core import tenue as tn
        self.pile.setCurrentIndex(max(0, self.mode.currentIndex()))
        mode = self.mode.currentData() or 'etau'
        if not getattr(self, '_tableau_pret', False):
            self._tableau_pret = True
        else:
            self.gammes[self._cle_affichee] = self.lire_gamme()
        self.phases, perdues = tn.phases_du_mode(self.plan, mode,
                                                 self.lire_brut())
        self.faces_rouges = set(self.plan['non_usinables']) | set(perdues)
        n = len(self.phases)
        nu = len(self.plan['non_usinables']) + len(perdues)
        texte = (f"{n} phases (bridages et reprises) pour cette pièce et "
                 f"cette tenue." if n > 1 else
                 "Une seule prise suffit: la pièce s'usine par le dessus.")
        if perdues:
            texte += (f" {len(perdues)} face(s) de côté que cette tenue "
                      "n'atteint pas (étau pour les côtés) — en rouge.")
        if self.plan['non_usinables']:
            texte += (f" {len(self.plan['non_usinables'])} face(s) "
                      "qu'aucune orientation 3 axes n'atteint "
                      "(contre-dépouilles: fraise spéciale ou 5 axes) — "
                      "en rouge.")
        self.phases_label.setText(texte)
        self.phases_label.setStyleSheet(
            "color: #f9e2af;" if n > 1 or nu else "color: #a6adc8;")
        cle_avant = self.cle_phase() if self.phase_combo.count() else 'Z+'
        self.phase_combo.blockSignals(True)
        self.phase_combo.clear()
        for k, ph in enumerate(self.phases):
            self.phase_combo.addItem(
                f"Phase {k + 1} — {ph['libelle']} "
                f"({len(ph.get('faces') or [])} face(s))", ph['cle'])
        i = self.phase_combo.findData(cle_avant)
        self.phase_combo.setCurrentIndex(max(0, i))
        self.phase_combo.blockSignals(False)
        self.phase_combo.setEnabled(n > 1)
        self.toutes_phases.setVisible(n > 1)
        cle = self.cle_phase()
        self._cle_affichee = cle
        if proposer or cle not in self.gammes:
            self._proposer_phase(cle)
        else:
            self.remplir(self.gammes[cle])
            self.pourquoi.setText("\n".join(self.pourquois.get(cle, [])))
        self._montrer_bridage()
        self._oublier_resultat()

    # ── les phases ──

    def multi_phases(self) -> bool:
        return len(self.phases) > 1 and self.toutes_phases.isChecked()

    def cle_phase(self) -> str:
        return self.phase_combo.currentData() or 'Z+'

    def phase(self, cle: str) -> Optional[Dict]:
        for ph in self.phases:
            if ph['cle'] == cle:
                return ph
        return None

    def rang(self, cle: str) -> int:
        for k, ph in enumerate(self.phases):
            if ph['cle'] == cle:
                return k
        return 0

    def _montrer_bridage(self) -> None:
        from src.core import tenue as tn
        from src.core import usinage3d
        cle = self.cle_phase()
        ph = self.phase(cle)
        if ph is None:
            self.bridage_label.setText("")
            return
        t = self.lire_tenue()
        rang = self.rang(cle)
        self.bridage_label.setText(
            f"Bridage: {tn.texte_bridage(t['mode'], cle, rang, t, self.lire_brut())}. "
            f"Zéro: {usinage3d._texte_zero(t['mode'], cle, rang, t)}.")
        self.montrer_phase()

    def _changer_phase(self, *_a) -> None:
        """Le tableau montre la gamme de la phase choisie (celle qu'on
        quitte est gardée)."""
        self.gammes[self._cle_affichee] = self.lire_gamme()
        cle = self.cle_phase()
        self._cle_affichee = cle
        if cle not in self.gammes:
            self._proposer_phase(cle)
        else:
            self.remplir(self.gammes[cle])
            self.pourquoi.setText("\n".join(self.pourquois.get(cle, [])))
        self._montrer_bridage()
        if not self.multi_phases():
            # une seule phase: c'est celle qu'on calcule
            self._oublier_resultat()

    def _proposer_phase(self, cle: str) -> None:
        from src.core import usinage3d
        gamme, pourquoi = usinage3d.proposer_phase(
            self.modele, self.placement, cle, self.bibliotheque,
            self.lire_brut())
        self.gammes[cle] = gamme
        self.pourquois[cle] = list(pourquoi)
        self.remplir(gamme)
        self.pourquoi.setText("\n".join(pourquoi))

    def gammes_phases(self) -> Dict[str, List[Dict]]:
        """La gamme de chaque phase (proposée pour celles qu'on n'a pas
        regardées)."""
        from src.core import usinage3d
        self.gammes[self._cle_affichee] = self.lire_gamme()
        for ph in self.phases:
            if ph['cle'] not in self.gammes:
                g, pq = usinage3d.proposer_phase(
                    self.modele, self.placement, ph['cle'],
                    self.bibliotheque, self.lire_brut())
                self.gammes[ph['cle']] = g
                self.pourquois[ph['cle']] = list(pq)
        return {c: list(g) for c, g in self.gammes.items()}

    # ── la phase en 3D ──

    def _resultat_de(self, cle: str):
        if self.calcul_phases:
            for item in self.calcul_phases['phases']:
                if item['phase']['cle'] == cle:
                    return item['resultat']
        if self.resultat is not None and cle == 'Z+':
            return self.resultat
        return None

    def scene(self) -> Optional[Dict]:
        """La scène 3D de la phase choisie (src/core/scene_phases)."""
        from src.core import scene_phases
        cle = self.cle_phase()
        ph = self.phase(cle)
        if ph is None:
            return None
        try:
            return scene_phases.scene_phase(
                self.modele, self.placement, ph, self.lire_brut(),
                self.lire_tenue(), self.rang(cle), self._resultat_de(cle),
                faces_rouges=getattr(self, 'faces_rouges', None))
        except Exception as exc:          # noqa: BLE001 — l'aperçu seul
            return {'erreur': str(exc)}

    def montrer_phase(self) -> None:
        sc = self.scene()
        if sc is None or 'erreur' in sc:
            self.vue.set_scene()
            self.vue_info.setText(
                "" if sc is None else f"Aperçu impossible: {sc['erreur']}")
            return
        self.vue.set_scene(sc['triangles'], sc['couleurs'], sc['aretes'],
                           sc['calques'])
        if sc.get('matiere'):
            self.vue.montrer_matiere = True
            self.vue.set_matiere(sc['matiere'][0], sc['matiere'][1])
        else:
            self.vue.set_matiere(None)
        self.vue_info.setText(sc['texte'] + (
            " · matière et parcours calculés" if sc.get('matiere')
            else " · brut en orange, avant calcul"))

    def montrer_au_canva3d(self) -> bool:
        """La phase choisie dans le Canva 3D de la fenêtre."""
        fen = self.parent()
        canvas = None
        while fen is not None and canvas is None:
            canvas = getattr(fen, 'vue3d_panel', None)
            fen = fen.parent() if canvas is None else fen
        sc = self.scene()
        if canvas is None or sc is None or 'erreur' in sc:
            return False
        canvas.montrer_scene(sc)
        return True

    # ── la gamme ──

    def _outils(self):
        """[(id, libellé)] des fraises utilisables (cylindriques, boules)."""
        from src.core import usinage3d
        sortie = [(tid, f"{t.name} [{t.article_nr}]")
                  for tid, t, _d, _l in usinage3d._cylindriques(
                      self.bibliotheque)]
        sortie += [(tid, f"{t.name} [{t.article_nr}] (boule)")
                   for tid, t, _d in usinage3d._boules(self.bibliotheque)]
        return sortie

    def proposer(self) -> None:
        """La gamme proposée pour la phase affichée."""
        self._proposer_phase(self.cle_phase())
        self._oublier_resultat()

    def remplir(self, gamme: List[Dict]) -> None:
        outils = self._outils()
        self.table.setRowCount(0)
        for et in gamme:
            r = self.table.rowCount()
            self.table.insertRow(r)
            from PySide6.QtWidgets import QTableWidgetItem
            item = QTableWidgetItem(et.get('nom') or ROLES.get(et['role'],
                                                               et['role']))
            item.setData(Qt.ItemDataRole.UserRole, et['role'])
            self.table.setItem(r, COL_NOM, item)
            combo = QComboBox()
            for tid, libelle in outils:
                combo.addItem(libelle, tid)
            i = combo.findData(et['outil'])
            if i >= 0:
                combo.setCurrentIndex(i)
            combo.currentIndexChanged.connect(self._oublier_resultat)
            self.table.setCellWidget(r, COL_OUTIL, combo)
            strat = QComboBox()
            for cle, libelle in STRATEGIES.items():
                strat.addItem(libelle, cle)
            strat.setCurrentIndex(max(0, strat.findData(et['strategie'])))
            strat.currentIndexChanged.connect(self._oublier_resultat)
            self.table.setCellWidget(r, COL_STRAT, strat)
            for col, cle, maxi in ((COL_SUREP, 'surepaisseur', 5.0),
                                   (COL_PASSE, 'passe_z', 50.0),
                                   (COL_LAT, 'pas_lateral', 20.0)):
                sp = SpinCote(decimales=3)
                sp.setRange(0.0, maxi)
                sp.setValue(float(et.get(cle, 0.0)))
                sp.valueChanged.connect(self._oublier_resultat)
                self.table.setCellWidget(r, col, sp)

    def lire_gamme(self) -> List[Dict]:
        """La gamme telle que le tableau la dit."""
        from src.core import usinage3d
        gamme = []
        for r in range(self.table.rowCount()):
            item = self.table.item(r, COL_NOM)
            tid = self.table.cellWidget(r, COL_OUTIL).currentData()
            if not tid:
                continue
            t = self.bibliotheque.tools.get(tid)
            gamme.append(usinage3d.etape(
                item.text() if item else "Étape", tid,
                usinage3d.forme_de(self.bibliotheque, tid),
                (item.data(Qt.ItemDataRole.UserRole) if item else None)
                or 'finition',
                self.table.cellWidget(r, COL_STRAT).currentData(),
                self.table.cellWidget(r, COL_SUREP).value(),
                self.table.cellWidget(r, COL_PASSE).value() or 1.0,
                self.table.cellWidget(r, COL_LAT).value() or 1.0,
                nom_outil=t.name if t else ""))
        return gamme

    def _ajouter_etape(self) -> None:
        from src.core import usinage3d
        gamme = self.lire_gamme()
        modele = gamme[-1] if gamme else None
        outils = self._outils()
        if not outils:
            return
        tid = modele['outil'] if modele else outils[0][0]
        gamme.append(usinage3d.etape(
            "Finition", tid, usinage3d.forme_de(self.bibliotheque, tid),
            'finition', 'balayage', 0.0, 1.0, 0.3))
        self.remplir(gamme)
        self._oublier_resultat()

    def _retirer_etape(self) -> None:
        r = self.table.currentRow()
        if r < 0:
            r = self.table.rowCount() - 1
        if r >= 0:
            self.table.removeRow(r)
            self._oublier_resultat()

    # ── le calcul ──

    def _oublier_resultat(self, *_a) -> None:
        self.resultat = None
        self.calcul_phases = None
        self.ajouter_btn.setEnabled(False)
        self.bilan.setText("")
        if not self._en_construction and hasattr(self, 'vue'):
            self.montrer_phase()

    def _decalage_dessus(self):
        """Le zéro de la phase du dessus sans calcul: le dessus du brut
        (s'il y en a un), sinon celui de la pièce."""
        from src.core import tenue as tn
        dx, dy, haut, _bas = self.placement
        try:
            boite = tn.boite_brut(self.modele, self.lire_brut())
            return (-dx, -dy, float(boite[5]))
        except Exception:
            return (-dx, -dy, haut)

    def _calculer_tslot(self, decalage=None) -> Optional[Dict]:
        """Les contre-dépouilles à la fraise en T (phase du dessus), si
        la case le demande et qu'il y en a."""
        from src.core import usinage_tslot
        from src.gui.progression import travailler
        self.tslot = None
        faces = list(self.plan.get('non_usinables') or [])
        if not self.cb_tslot.isChecked() or not faces:
            return None
        hote = self.parent() if self.parent() is not None else self
        res = travailler(
            hote, "Contre-dépouilles",
            lambda prog: usinage_tslot.proposer(
                self.modele, self.placement, self.bibliotheque,
                faces=faces, decalage=decalage, progression=prog,
                pas=self.lire_precision()[0]),
            "Fraises en T sous les surplombs…")
        if res is None:
            return None
        self.tslot = res
        if res.get('faces'):
            # ce que la fraise en T usine n'est plus en rouge
            self.faces_rouges = set(self.faces_rouges) - set(res['faces'])
        texte = usinage_tslot.resume(res)
        if texte:
            self.bilan.setText((self.bilan.text() + "\n" + texte).strip())
        if res.get('etapes'):
            self.ajouter_btn.setEnabled(True)
        return res

    def calculer(self) -> Optional[Dict]:
        from src.core import usinage3d
        from src.gui.progression import travailler
        gamme = self.lire_gamme()
        if not gamme:
            self.bilan.setText("Aucune étape à calculer.")
            self.resultat = None
            self.calcul_phases = None
            # les contre-dépouilles se calculent quand même
            if self._calculer_tslot(self._decalage_dessus()):
                self.montrer_phase()
                return self.tslot
            return None
        hote = self.parent() if self.parent() is not None else self
        cle = self.cle_phase()
        brut, tenue = self.lire_brut(), self.lire_tenue()
        pas, tolerance = self.lire_precision()
        if self.multi_phases() or cle != 'Z+':
            # toutes les phases, ou une phase seule (partant du brut
            # entier)
            gammes = self.gammes_phases()
            phases = (self.phases if self.multi_phases()
                      else [self.phase(cle)])
            calc = travailler(
                hote, "Usinage 3D",
                lambda prog: usinage3d.calculer_phases(
                    self.modele, self.placement, gammes, phases,
                    pas=pas, progression=prog, brut=brut, tenue=tenue,
                    bibliotheque=self.bibliotheque, tolerance=tolerance),
                "Calcul des phases…")
            if calc is None:
                self.bilan.setText("Calcul annulé.")
                return None
            self.calcul_phases = calc
            self.resultat = None
            lignes = []
            for item in calc['phases']:
                ph = item['phase']
                rang = self.rang(ph['cle']) + 1
                lignes.append(f"Phase {rang} ({ph['libelle']}): "
                              + usinage3d.resume(item['resultat']))
            self.bilan.setText("\n".join(lignes))
            self.ajouter_btn.setEnabled(any(
                it['resultat'].get('etapes') for it in calc['phases']))
            dessus = next((it['resultat'] for it in calc['phases']
                           if it['phase']['cle'] == 'Z+'), None)
            self._calculer_tslot((dessus or {}).get('decalage'))
            self.montrer_phase()
            return calc
        res = travailler(
            hote, "Usinage 3D",
            lambda prog: usinage3d.calculer(self.modele, self.placement,
                                            gamme, pas=pas, progression=prog,
                                            brut=brut, tenue=tenue,
                                            tolerance=tolerance),
            "Calcul de la gamme…")
        if res is None:
            self.bilan.setText("Calcul annulé.")
            return None
        self.resultat = res
        self.gamme = gamme
        self.bilan.setText(usinage3d.resume(res))
        self.ajouter_btn.setEnabled(bool(res.get('etapes')))
        self._calculer_tslot(res.get('decalage'))
        self.montrer_phase()
        return res

    def operations(self) -> List[Dict]:
        from src.core import usinage3d
        if self.calcul_phases:
            ops = usinage3d.operations_phases(self.calcul_phases,
                                              self.nom_piece)
        elif self.resultat:
            ops = usinage3d.operations(self.resultat, self.nom_piece)
        else:
            ops = []
        t = getattr(self, 'tslot', None) or {}
        if t.get('etapes'):
            # dans la phase du dessus, après ses séquences (le zéro est
            # le sien)
            extra = usinage3d.operations({'etapes': t['etapes']},
                                         self.nom_piece)
            groupe = ops[0].get('group_id') if ops else None
            fin = 0
            for k, o in enumerate(ops):
                if o.get('group_id') == groupe:
                    fin = k + 1
            for o in extra:
                if groupe:
                    o['group_id'] = groupe
                    o['group_name'] = ops[0].get('group_name')
                    o['group_libre'] = True
                    o['name'] = "P1 " + o['name']
            ops = ops[:fin] + extra + ops[fin:]
        return ops
