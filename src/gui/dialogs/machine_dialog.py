"""L'éditeur de la machine (DATRON neo): ses cotes — courses, table et
rainures, broche, pince —, le STEP de son bâti et de sa broche, et un
aperçu. L'atelier les corrige et les améliore; le fichier est
« Machine/machine.json » à côté de l'exe (src/core/machine.py)."""

from typing import Dict

import numpy as np
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QVBoxLayout, QWidget
)

from src.gui.widgets import SpinCote

#: (clé, libellé, maxi), dans l'ordre du formulaire
CHAMPS = (('course_x', "Course X", 5000), ('course_y', "Course Y", 5000),
          ('course_z', "Course Z", 2000),
          ('table_longueur', "Table: longueur", 5000),
          ('table_largeur', "Table: largeur", 5000),
          ('table_epaisseur', "Table: épaisseur", 500),
          ('rainure_pas', "Rainures: pas", 500),
          ('rainure_largeur', "Rainures: largeur", 100),
          ('rainure_profondeur', "Rainures: profondeur", 100),
          ('ecrou_diametre', "Écrou de pince: Ø", 300),
          ('ecrou_hauteur', "Écrou de pince: hauteur", 300),
          ('nez_diametre', "Nez de broche: Ø", 500),
          ('nez_hauteur', "Nez de broche: hauteur", 500),
          ('broche_diametre', "Broche: Ø", 1000),
          ('broche_longueur', "Broche: longueur", 2000),
          ('pince_longueur', "Queue d'outil serrée par la pince", 100),
          ('z_max_ecrou', "Écrou au plus haut, au-dessus de la table",
           3000),
          ('vitesse_rapide', "Rapides (mm/min)", 100000),
          ('changement_outil_s', "Changement d'outil (s)", 600))


class DialogueMachine(QDialog):
    """La machine de l'atelier: cotes, STEP, aperçu."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from src.core import machine as mc
        self.setWindowTitle("La machine")
        self.resize(1000, 640)
        self._machine = mc.charger()
        self.nom = QLineEdit(self._machine['nom'])
        self.champs: Dict[str, SpinCote] = {}
        form = QFormLayout()
        form.addRow("Nom", self.nom)
        for cle, libelle, maxi in CHAMPS:
            sp = SpinCote(decimales=2)
            sp.setRange(0.0, float(maxi))
            sp.setValue(float(self._machine[cle]))
            sp.valueChanged.connect(self._maj_apercu)
            form.addRow(libelle, sp)
            self.champs[cle] = sp
        self.steps = {}
        for cle, libelle in (('step_bati', "Bâti / table (STEP)"),
                             ('step_broche', "Broche (STEP)")):
            ligne = QHBoxLayout()
            etiquette = QLabel(self._machine[cle] or "paramétrique")
            importer = QPushButton("STEP…")
            importer.clicked.connect(lambda _=False, c=cle: self._importer(c))
            retirer = QPushButton("Retirer")
            retirer.clicked.connect(lambda _=False, c=cle: self._retirer(c))
            ligne.addWidget(etiquette, 1)
            ligne.addWidget(importer)
            ligne.addWidget(retirer)
            dec = [SpinCote(decimales=2) for _ in range(3)]
            ligne_dec = QHBoxLayout()
            for lettre, sp, v in zip("XYZ", dec,
                                     self._machine[cle + '_decalage']):
                sp.setRange(-10000.0, 10000.0)
                sp.setValue(float(v))
                sp.valueChanged.connect(self._maj_apercu)
                ligne_dec.addWidget(QLabel(lettre))
                ligne_dec.addWidget(sp)
            form.addRow(libelle, ligne)
            form.addRow("   décalage", ligne_dec)
            self.steps[cle] = (etiquette, dec)
        self.notes = QLineEdit(self._machine.get('notes', ''))
        form.addRow("Notes", self.notes)
        cadre = QWidget()
        cadre.setLayout(form)
        defile = QScrollArea()
        defile.setWidgetResizable(True)
        defile.setWidget(cadre)

        from src.gui.canvas3d import VueScene
        self.apercu = VueScene()
        self.apercu.setMinimumWidth(420)

        self.statut = QLabel("")
        self.statut.setStyleSheet("color: #a6adc8; font-size: 11px;")
        enregistrer = QPushButton("Enregistrer")
        enregistrer.setObjectName("primary")
        enregistrer.clicked.connect(self._enregistrer_et_fermer)
        fermer = QPushButton("Fermer")
        fermer.clicked.connect(self.reject)
        bas = QHBoxLayout()
        bas.addWidget(self.statut, 1)
        bas.addWidget(enregistrer)
        bas.addWidget(fermer)
        haut = QHBoxLayout()
        haut.addWidget(defile, 2)
        haut.addWidget(self.apercu, 3)
        v = QVBoxLayout(self)
        v.addLayout(haut, 1)
        v.addLayout(bas)
        self._maj_apercu()

    def machine(self) -> Dict:
        from src.core import machine as mc
        m = dict(self._machine)
        m['nom'] = self.nom.text().strip() or m['nom']
        for cle, sp in self.champs.items():
            m[cle] = sp.value()
        for cle, (_e, dec) in self.steps.items():
            m[cle + '_decalage'] = [sp.value() for sp in dec]
        m['notes'] = self.notes.text()
        return mc.normaliser(m)

    def _maj_apercu(self, *_):
        """La table, une pièce de 100 × 80 × 25 posée, la broche
        au-dessus, l'enveloppe des courses."""
        from src.core import machine as mc
        from src.core.tenue import _boite
        m = self.machine()
        T, C = mc.triangles_table(m, (0.0, 0.0), -25.0)
        piece = _boite(-50, 50, -40, 40, -25, 0)
        B, CB = mc.triangles_broche(m, 0.0, 0.0, 40.0)
        tri = np.concatenate([T, piece, B])
        col = np.concatenate([C, np.tile((0.98, 0.70, 0.53), (len(piece), 1)),
                              CB])
        self.apercu.set_scene(tri, col, mc.enveloppe(m, (0.0, 0.0), -25.0))
        self.statut.setText(
            f"{m['nom']}: courses {m['course_x']:g} × {m['course_y']:g} × "
            f"{m['course_z']:g} mm — broche Ø {m['broche_diametre']:g}, "
            f"écrou Ø {m['ecrou_diametre']:g}")

    def _importer(self, cle: str) -> None:
        chemin, _f = QFileDialog.getOpenFileName(
            self, "STEP de la machine", "", "STEP (*.stp *.step *.STP *.STEP)")
        if chemin:
            self.importer_step(cle, chemin)

    def importer_step(self, cle: str, chemin: str) -> None:
        from src.core import machine as mc
        self._machine = mc.importer_step(self.machine(), cle, chemin)
        self.steps[cle][0].setText(self._machine[cle])
        self._maj_apercu()

    def _retirer(self, cle: str) -> None:
        self._machine = dict(self.machine())
        self._machine[cle] = ""
        self.steps[cle][0].setText("paramétrique")
        self._maj_apercu()

    def enregistrer(self) -> str:
        from src.core import machine as mc
        self._machine = self.machine()
        chemin = mc.enregistrer(self._machine)
        self.statut.setText(f"Enregistré: {chemin}")
        return chemin

    def _enregistrer_et_fermer(self) -> None:
        self.enregistrer()
        self.accept()
