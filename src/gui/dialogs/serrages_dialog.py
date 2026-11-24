"""L'éditeur des étaux autocentrés et des mandrins: on les décrit par
leurs cotes (un modèle 3D tout de suite), on remplace leur corps par le
STEP du fabricant, on les voit serrer une pièce.

Les fichiers vont dans « Étaux et mandrins » à côté de l'exe
(src/core/serrages.py)."""

import os
from typing import Dict, Optional

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QMessageBox, QPushButton, QSpinBox,
    QStackedWidget, QVBoxLayout, QWidget
)

from src.gui.widgets import SpinCote

#: (clé, libellé, maxi) des champs de chaque genre
CHAMPS_ETAU = (('largeur_mors', "Largeur des mors", 1000),
               ('hauteur_mors', "Hauteur des mors", 300),
               ('epaisseur_mors', "Épaisseur des mors", 200),
               ('ouverture_min', "Ouverture mini", 1000),
               ('ouverture_max', "Ouverture maxi", 1000),
               ('prise', "Prise (hauteur serrée)", 100),
               ('longueur_base', "Longueur du corps", 2000),
               ('largeur_base', "Largeur du corps", 2000),
               ('hauteur_base', "Hauteur du corps", 500))
CHAMPS_MANDRIN = (('diametre', "Ø du corps", 1000),
                  ('hauteur', "Hauteur du corps", 500),
                  ('hauteur_mors', "Hauteur des mors", 300),
                  ('largeur_mors', "Largeur d'un mors", 200),
                  ('longueur_mors', "Longueur d'un mors (radiale)", 300),
                  ('serrage_min', "Ø de serrage mini", 1000),
                  ('serrage_max', "Ø de serrage maxi", 1000),
                  ('prise', "Prise (hauteur serrée)", 100))
#: la pièce de l'aperçu
PIECE = (0.98, 0.70, 0.53)


class DialogueSerrages(QDialog):
    """Étaux autocentrés et mandrins: créer, régler, importer le corps."""

    def __init__(self, parent=None, nom: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Étaux autocentrés et mandrins")
        self.resize(1100, 640)
        self.choisi = ""
        self._chemin: Optional[str] = None
        self._courant: Dict = {}
        self._pose_en_cours = False

        self.liste = QListWidget()
        self.liste.currentRowChanged.connect(self._choisir)
        boutons = QVBoxLayout()
        for texte, action in (("Nouvel étau autocentré", self.nouvel_etau),
                              ("Nouveau mandrin", self.nouveau_mandrin),
                              ("Dupliquer", self.dupliquer),
                              ("Corps STEP…", self._importer_step),
                              ("Supprimer", self.supprimer)):
            b = QPushButton(texte)
            b.clicked.connect(action)
            boutons.addWidget(b)
        boutons.addStretch()
        gauche = QVBoxLayout()
        gauche.addWidget(self.liste, 1)
        gauche.addLayout(boutons)

        # le formulaire
        self.nom = QLineEdit()
        self.genre = QLabel("")
        self.genre.setStyleSheet("color: #89b4fa; font-weight: bold;")
        self.pile = QStackedWidget()
        self.champs: Dict[str, Dict[str, SpinCote]] = {'etau': {},
                                                       'mandrin': {}}
        for genre, liste in (('etau', CHAMPS_ETAU),
                             ('mandrin', CHAMPS_MANDRIN)):
            page = QWidget()
            f = QFormLayout(page)
            f.setContentsMargins(0, 0, 0, 0)
            for cle, libelle, maxi in liste:
                sp = SpinCote(decimales=2)
                sp.setRange(0.0, float(maxi))
                sp.valueChanged.connect(self._changement)
                f.addRow(libelle, sp)
                self.champs[genre][cle] = sp
            if genre == 'etau':
                self.axe = QComboBox()
                self.axe.addItem("Serre en Y (mors devant / derrière)", 'Y')
                self.axe.addItem("Serre en X (mors à gauche / à droite)", 'X')
                self.axe.currentIndexChanged.connect(self._changement)
                f.addRow("Sens", self.axe)
            else:
                self.nb_mors = QSpinBox()
                self.nb_mors.setRange(2, 8)
                self.nb_mors.valueChanged.connect(self._changement)
                f.addRow("Nombre de mors", self.nb_mors)
            self.pile.addWidget(page)
        self.step = QLabel("Corps: paramétrique")
        self.step.setWordWrap(True)
        retirer = QPushButton("Retirer le STEP")
        retirer.clicked.connect(self._retirer_step)
        self.decalage = [SpinCote(decimales=2) for _ in range(3)]
        ligne_dec = QHBoxLayout()
        for lettre, sp in zip("XYZ", self.decalage):
            sp.setRange(-5000.0, 5000.0)
            sp.valueChanged.connect(self._changement)
            ligne_dec.addWidget(QLabel(lettre))
            ligne_dec.addWidget(sp)
        self.notes = QLineEdit()
        self.ouverture = SpinCote(decimales=1)
        self.ouverture.setRange(0.0, 2000.0)
        self.ouverture.setToolTip("L'ouverture (étau) ou le Ø serré "
                                  "(mandrin) de l'aperçu")
        self.ouverture.valueChanged.connect(self._maj_apercu)
        milieu = QVBoxLayout()
        f0 = QFormLayout()
        f0.addRow("Nom", self.nom)
        f0.addRow("Genre", self.genre)
        milieu.addLayout(f0)
        milieu.addWidget(self.pile)
        f1 = QFormLayout()
        f1.addRow(self.step)
        f1.addRow(retirer)
        f1.addRow("Décalage du STEP", ligne_dec)
        f1.addRow("Notes", self.notes)
        f1.addRow("Aperçu: ouverture / Ø", self.ouverture)
        milieu.addLayout(f1)
        milieu.addStretch()

        from src.gui.canvas3d import VueScene
        self.apercu = VueScene()
        self.apercu.setMinimumWidth(380)

        enregistrer = QPushButton("Enregistrer")
        enregistrer.clicked.connect(self.enregistrer)
        choisir = QPushButton("Choisir")
        choisir.setObjectName("primary")
        choisir.clicked.connect(self._valider)
        fermer = QPushButton("Fermer")
        fermer.clicked.connect(self.reject)
        bas = QHBoxLayout()
        self.statut = QLabel("")
        self.statut.setStyleSheet("color: #a6adc8; font-size: 11px;")
        bas.addWidget(self.statut, 1)
        for b in (enregistrer, choisir, fermer):
            bas.addWidget(b)
        haut = QHBoxLayout()
        haut.addLayout(gauche, 1)
        haut.addLayout(milieu, 2)
        haut.addWidget(self.apercu, 3)
        v = QVBoxLayout(self)
        v.addLayout(haut, 1)
        v.addLayout(bas)
        self._relire(nom)

    # ──── la liste ────

    def _relire(self, nom: str = "") -> None:
        from src.core import serrages as sg
        self._fichiers = sg.lister()
        self.liste.blockSignals(True)
        self.liste.clear()
        for n, _c in self._fichiers:
            self.liste.addItem(n)
        self.liste.blockSignals(False)
        rang = next((i for i, (n, _c) in enumerate(self._fichiers)
                     if n == nom), 0 if self._fichiers else -1)
        if rang >= 0:
            self.liste.setCurrentRow(rang)
            self._choisir(rang)
        else:
            self.poser(sg.nouvel_etau())

    def _choisir(self, rang: int) -> None:
        from src.core import serrages as sg
        if 0 <= rang < len(self._fichiers):
            self._chemin = self._fichiers[rang][1]
            p = sg.charger(self._chemin)
            if p is not None:
                self.poser(p)

    def poser(self, p: Dict) -> None:
        """Le dispositif dans le formulaire."""
        from src.core import serrages as sg
        p = sg.normaliser(p) or sg.nouvel_etau()
        self._courant = dict(p)
        self._pose_en_cours = True
        try:
            self.nom.setText(p['nom'])
            self.genre.setText(dict(sg.GENRES)[p['genre']])
            self.pile.setCurrentIndex(0 if p['genre'] == 'etau' else 1)
            for cle, sp in self.champs[p['genre']].items():
                sp.setValue(float(p[cle]))
            if p['genre'] == 'etau':
                self.axe.setCurrentIndex(0 if p.get('axe') != 'X' else 1)
                self.ouverture.setValue(p['ouverture_max'] / 2)
            else:
                self.nb_mors.setValue(int(p['mors']))
                self.ouverture.setValue(p['serrage_max'] / 2)
            for sp, v in zip(self.decalage, p['step_decalage']):
                sp.setValue(float(v))
            self.notes.setText(p.get('notes', ''))
            self._maj_step()
        finally:
            self._pose_en_cours = False
        self._maj_apercu()

    def dispositif(self) -> Dict:
        """Le dispositif tel que le formulaire le décrit."""
        from src.core import serrages as sg
        p = dict(self._courant)
        p['nom'] = self.nom.text().strip() or p.get('nom', "Serrage")
        for cle, sp in self.champs[p.get('genre', 'etau')].items():
            p[cle] = sp.value()
        if p.get('genre') == 'etau':
            p['axe'] = self.axe.currentData() or 'Y'
        else:
            p['mors'] = self.nb_mors.value()
        p['step_decalage'] = [sp.value() for sp in self.decalage]
        p['notes'] = self.notes.text()
        return sg.normaliser(p)

    def _changement(self, *_):
        if not self._pose_en_cours:
            self._courant = self.dispositif()
            self._maj_apercu()

    def _maj_step(self) -> None:
        from src.core import serrages as sg
        s = self._courant.get('step') or ""
        chemin = sg.chemin_step(self._courant)
        self.step.setText(
            "Corps: paramétrique" if not s else
            (f"Corps: STEP « {s} »" if chemin else
             f"Corps: STEP « {s} » INTROUVABLE (paramétrique en attendant)"))

    def _maj_apercu(self, *_) -> None:
        """Le dispositif serrant une pièce de l'ouverture choisie."""
        from src.core import serrages as sg
        from src.core.tenue import _boite
        p = self._courant
        if not p:
            return
        o = sg.ouverture_bornee(p, self.ouverture.value())
        T, C = sg.triangles(p, o)
        prise = float(p.get('prise', 3.0))
        if p['genre'] == 'etau':
            longueur = min(p['largeur_mors'] * 0.8, 1.5 * o + 10)
            if p.get('axe') == 'X':
                piece = _boite(-o / 2, o / 2, -longueur / 2, longueur / 2,
                               -prise, 20.0)
            else:
                piece = _boite(-longueur / 2, longueur / 2, -o / 2, o / 2,
                               -prise, 20.0)
        else:
            from src.core.serrages import _cylindre
            piece = _cylindre(o / 2, -prise, 20.0, n=40)
        T = np.concatenate([T, piece])
        C = np.concatenate([C, np.tile(PIECE, (len(piece), 1))])
        self.apercu.set_scene(T, C)
        self.statut.setText(
            f"{p['nom']}: {'ouverture' if p['genre'] == 'etau' else 'Ø serré'}"
            f" {o:g} mm — {len(T)} triangles")

    # ──── les actions ────

    def nouvel_etau(self) -> None:
        from src.core import serrages as sg
        self._chemin = None
        self.liste.clearSelection()
        self.poser(sg.nouvel_etau("Nouvel étau autocentré"))

    def nouveau_mandrin(self) -> None:
        from src.core import serrages as sg
        self._chemin = None
        self.liste.clearSelection()
        self.poser(sg.nouveau_mandrin("Nouveau mandrin"))

    def dupliquer(self) -> None:
        p = self.dispositif()
        p['nom'] = p['nom'] + " (copie)"
        self._chemin = None
        self.poser(p)

    def importer_step(self, chemin: str) -> Dict:
        from src.core import serrages as sg
        self._courant = sg.importer_step(self.dispositif(), chemin)
        self._maj_step()
        self._maj_apercu()
        return self._courant

    def _importer_step(self) -> None:
        chemin, _f = QFileDialog.getOpenFileName(
            self, "Le corps de l'étau ou du mandrin (STEP du fabricant)",
            "", "STEP (*.stp *.step *.STP *.STEP)")
        if chemin:
            self.importer_step(chemin)

    def _retirer_step(self) -> None:
        self._courant = dict(self.dispositif())
        self._courant['step'] = ""
        self._maj_step()
        self._maj_apercu()

    def enregistrer(self) -> str:
        from src.core import serrages as sg
        p = self.dispositif()
        self._chemin = sg.enregistrer(p, self._chemin)
        self._relire(p['nom'])
        self.statut.setText(f"Enregistré: {self._chemin}")
        return self._chemin

    def supprimer(self) -> None:
        from src.core import serrages as sg
        if not self._chemin:
            return
        rep = QMessageBox.question(
            self, "Étaux et mandrins",
            f"Supprimer « {self.nom.text()} » ?\n{self._chemin}")
        if rep == QMessageBox.StandardButton.Yes:
            sg.supprimer(self._chemin)
            self._chemin = None
            self._relire()

    def _valider(self) -> None:
        self.choisi = self.dispositif()['nom']
        if self._chemin is None or self.dispositif() != self._courant_enregistre():
            self.enregistrer()
        self.accept()

    def _courant_enregistre(self) -> Optional[Dict]:
        from src.core import serrages as sg
        return sg.charger(self._chemin) if self._chemin else None
