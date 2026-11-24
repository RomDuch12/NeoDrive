"""Les réglages du PNG écrit à côté du .SimPl à l'export (l'aperçu
@image: que la machine montre, et celui du dessin joint).

Octobre 2026 (RomDuch): « en 3D on ne voit plus rien à cause de la
matière ». On choisit maintenant ce que l'image montre en 2D (les
calques du Canva, la légende, les étiquettes, les couleurs papier ou
écran, toute la pièce ou la vue du Canva) et en 3D (pièce, arêtes,
parcours, opérations, dessin, matière avec son opacité et sa couleur,
la vue du Canva 3D — zoom et angle — ou une vue type), la taille de
l'image et le fond. Un aperçu se calcule dans la fenêtre.
"""

from typing import Callable, Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton,
    QSlider, QVBoxLayout, QWidget
)

#: les calques du Canva 2D (clé du panneau, libellé)
CALQUES_2D = (('dxf', "DXF importé"), ('ope', "Opérations"),
              ('drawn', "Dessin"), ('texte', "Annotations et cotes"),
              ('centres', "Centres détectés"), ('smb', "Symboles"))
#: ce que l'image 3D peut montrer (clé, libellé)
COUCHES_3D = (('piece', "Pièce STEP"), ('aretes', "Arêtes"),
              ('parcours', "Parcours de l'outil"),
              ('operations', "Opérations"), ('dessin', "Dessin du canvas"),
              ('matiere', "Matière (le brut usiné)"))
VUES_2D = (("Toute la pièce", 'tout'), ("La vue du Canva (zoom actuel)",
                                        'canva'))
VUES_3D = (("La vue du Canva 3D (zoom et angle actuels)", 'canva'),
           ("Isométrique", 'iso'), ("Dessus", 'dessus'), ("Face", 'face'))
COULEURS_2D = (("Papier (teintes foncées sur fond clair)", 'papier'),
               ("Écran (les couleurs du Canva)", 'canvas'),
               ("Noir (photocopie)", 'noir'))

#: les réglages par défaut: la matière à demi transparente (elle
#: cachait tout), le parcours et la pièce visibles
DEFAUT: Dict = {
    'largeur': 1200,
    'fond': '#b8b8b8',
    'calques_2d': {'dxf': True, 'ope': True, 'drawn': True, 'texte': True,
                   'centres': False, 'smb': True},
    'legende_2d': True,
    'etiquettes_2d': False,
    'couleurs_2d': 'papier',
    'vue_2d': 'tout',
    'couches_3d': {'piece': True, 'aretes': True, 'parcours': True,
                   'operations': False, 'dessin': False, 'matiere': True},
    'opacite_matiere': 0.45,
    'couleur_matiere': '',          # "" = les teintes du brut
    'vue_3d': 'iso',
    'fond_3d': '#181825',
}


def lire(reglages: Optional[Dict]) -> Dict:
    """Les réglages complets (ceux qui manquent: les défauts)."""
    sortie = {k: (dict(v) if isinstance(v, dict) else v)
              for k, v in DEFAUT.items()}
    for cle, valeur in (reglages or {}).items():
        if cle not in sortie:
            continue
        if isinstance(sortie[cle], dict) and isinstance(valeur, dict):
            sortie[cle].update({k: bool(v) for k, v in valeur.items()
                                if k in sortie[cle]})
        else:
            sortie[cle] = valeur
    # une valeur abîmée dans les réglages reprend son défaut (l'export
    # du .SimPl levait au moment d'écrire l'image)
    for cle, conv in (('opacite_matiere', float), ('largeur', int)):
        try:
            sortie[cle] = conv(sortie[cle])
        except (TypeError, ValueError):
            sortie[cle] = DEFAUT[cle]
    sortie['opacite_matiere'] = max(0.0, min(1.0, sortie['opacite_matiere']))
    sortie['largeur'] = max(200, min(4000, sortie['largeur']))
    return sortie


class _BoutonCouleur(QPushButton):
    """Un bouton qui montre une couleur et la fait choisir (« » = aucune
    si `vide` est permis)."""

    def __init__(self, couleur: str, vide: str = "", parent=None):
        super().__init__(parent)
        self._vide = vide
        self.couleur = couleur
        self.setFixedWidth(110)
        self.clicked.connect(self._choisir)
        self._montrer()

    def _montrer(self):
        if self.couleur:
            self.setText(self.couleur)
            fonce = QColor(self.couleur).lightness() < 128
            self.setStyleSheet(
                f"QPushButton {{ background: {self.couleur}; "
                f"color: {'#ffffff' if fonce else '#1e1e2e'}; }}")
        else:
            self.setText(self._vide or "—")
            self.setStyleSheet("")

    #: remplaçable par les tests: (couleur de départ) -> couleur ou ""
    choisir = None

    def _choisir(self):
        if self.choisir is not None:
            c = self.choisir(self.couleur)
        else:
            q = QColorDialog.getColor(QColor(self.couleur or "#888888"),
                                      self, "Couleur")
            c = q.name() if q.isValid() else None
        if c is not None:
            self.couleur = c
            self._montrer()


class DialogueReglagesPng(QDialog):
    """La fenêtre des réglages; `apercu(reglages) -> QImage` calcule
    l'image (celle de l'export) pour la vignette."""

    def __init__(self, reglages: Dict, genre: str = '2d3d',
                 apercu: Callable = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PNG du programme — réglages")
        self._apercu = apercu
        self._genre = genre
        r = lire(reglages)

        # ── 2D ──
        g2 = QGroupBox("Image 2D (le plan du Canva)")
        f2 = QFormLayout(g2)
        grille = QGridLayout()
        self.cases_2d = {}
        for i, (cle, nom) in enumerate(CALQUES_2D):
            cb = QCheckBox(nom)
            cb.setChecked(bool(r['calques_2d'].get(cle, True)))
            self.cases_2d[cle] = cb
            grille.addWidget(cb, i // 2, i % 2)
        boite = QWidget()
        boite.setLayout(grille)
        f2.addRow("Calques", boite)
        self.legende_2d = QCheckBox("Légende des outils")
        self.legende_2d.setChecked(bool(r['legende_2d']))
        self.etiquettes_2d = QCheckBox("Étiquettes des opérations")
        self.etiquettes_2d.setChecked(bool(r['etiquettes_2d']))
        ligne = QHBoxLayout()
        ligne.addWidget(self.legende_2d)
        ligne.addWidget(self.etiquettes_2d)
        ligne.addStretch()
        f2.addRow("Montrer", ligne)
        self.couleurs_2d = QComboBox()
        for texte, cle in COULEURS_2D:
            self.couleurs_2d.addItem(texte, cle)
        self.couleurs_2d.setCurrentIndex(
            max(0, self.couleurs_2d.findData(r['couleurs_2d'])))
        f2.addRow("Couleurs", self.couleurs_2d)
        self.vue_2d = QComboBox()
        for texte, cle in VUES_2D:
            self.vue_2d.addItem(texte, cle)
        self.vue_2d.setCurrentIndex(max(0, self.vue_2d.findData(r['vue_2d'])))
        f2.addRow("Cadrage", self.vue_2d)
        self.fond = _BoutonCouleur(r['fond'])
        f2.addRow("Fond", self.fond)

        # ── 3D ──
        g3 = QGroupBox("Image 3D (la pièce usinée)")
        f3 = QFormLayout(g3)
        grille3 = QGridLayout()
        self.cases_3d = {}
        for i, (cle, nom) in enumerate(COUCHES_3D):
            cb = QCheckBox(nom)
            cb.setChecked(bool(r['couches_3d'].get(cle, True)))
            self.cases_3d[cle] = cb
            grille3.addWidget(cb, i // 2, i % 2)
        boite3 = QWidget()
        boite3.setLayout(grille3)
        f3.addRow("Montrer", boite3)
        self.opacite = QSlider(Qt.Orientation.Horizontal)
        self.opacite.setRange(5, 100)
        self.opacite.setValue(int(round(r['opacite_matiere'] * 100)))
        self.opacite_txt = QLabel("")
        self.opacite.valueChanged.connect(
            lambda v: self.opacite_txt.setText(f"{v} %"))
        self.opacite_txt.setText(f"{self.opacite.value()} %")
        lo = QHBoxLayout()
        lo.addWidget(self.opacite, 1)
        lo.addWidget(self.opacite_txt)
        f3.addRow("Opacité de la matière", lo)
        self.couleur_matiere = _BoutonCouleur(r['couleur_matiere'],
                                              vide="teintes du brut")
        auto = QPushButton("Teintes du brut")
        auto.clicked.connect(self._matiere_auto)
        lc = QHBoxLayout()
        lc.addWidget(self.couleur_matiere)
        lc.addWidget(auto)
        lc.addStretch()
        f3.addRow("Couleur de la matière", lc)
        self.vue_3d = QComboBox()
        for texte, cle in VUES_3D:
            self.vue_3d.addItem(texte, cle)
        self.vue_3d.setCurrentIndex(max(0, self.vue_3d.findData(r['vue_3d'])))
        f3.addRow("Vue", self.vue_3d)
        self.fond_3d = _BoutonCouleur(r['fond_3d'])
        f3.addRow("Fond", self.fond_3d)

        # ── commun ──
        from src.gui.widgets import SpinEntier
        self.largeur = SpinEntier()
        self.largeur.setRange(200, 4000)
        self.largeur.setSingleStep(100)
        self.largeur.setValue(int(r['largeur']))
        self.vignette = QLabel("")
        self.vignette.setMinimumSize(360, 240)
        self.vignette.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.vignette.setStyleSheet("border: 1px solid #45475a;")
        voir = QPushButton("Aperçu")
        voir.setToolTip("Calcule l'image telle que l'export l'écrira")
        voir.clicked.connect(self.montrer_apercu)
        voir.setEnabled(apercu is not None)
        boutons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        boutons.accepted.connect(self.accept)
        boutons.rejected.connect(self.reject)

        gauche = QVBoxLayout()
        gauche.addWidget(g2)
        gauche.addWidget(g3)
        lw = QHBoxLayout()
        lw.addWidget(QLabel("Largeur de l'image"))
        lw.addWidget(self.largeur)
        lw.addWidget(QLabel("px"))
        lw.addStretch()
        gauche.addLayout(lw)
        droite = QVBoxLayout()
        droite.addWidget(self.vignette, 1)
        droite.addWidget(voir)
        haut = QHBoxLayout()
        haut.addLayout(gauche, 3)
        haut.addLayout(droite, 2)
        racine = QVBoxLayout(self)
        racine.addLayout(haut)
        racine.addWidget(boutons)

    def _matiere_auto(self):
        self.couleur_matiere.couleur = ""
        self.couleur_matiere._montrer()

    def reglages(self) -> Dict:
        return lire({
            'largeur': self.largeur.value(),
            'fond': self.fond.couleur or DEFAUT['fond'],
            'calques_2d': {k: cb.isChecked()
                           for k, cb in self.cases_2d.items()},
            'legende_2d': self.legende_2d.isChecked(),
            'etiquettes_2d': self.etiquettes_2d.isChecked(),
            'couleurs_2d': self.couleurs_2d.currentData(),
            'vue_2d': self.vue_2d.currentData(),
            'couches_3d': {k: cb.isChecked()
                           for k, cb in self.cases_3d.items()},
            'opacite_matiere': self.opacite.value() / 100.0,
            'couleur_matiere': self.couleur_matiere.couleur,
            'vue_3d': self.vue_3d.currentData(),
            'fond_3d': self.fond_3d.couleur or DEFAUT['fond_3d'],
        })

    def montrer_apercu(self):
        """La vignette: l'image de l'export avec les réglages en cours."""
        if self._apercu is None:
            return None
        try:
            image = self._apercu(self.reglages())
        except Exception as exc:
            self.vignette.setText(f"Aperçu impossible:\n{exc}")
            return None
        if image is None or image.isNull():
            self.vignette.setText("Rien à montrer")
            return None
        pix = QPixmap.fromImage(image).scaled(
            self.vignette.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        self.vignette.setPixmap(pix)
        return image
