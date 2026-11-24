# -*- coding: utf-8 -*-
"""Formulaire F2: mettre la sélection à la cote.

Repris de TauDrive: cotes visées OU pourcentages, proportions au
choix, et la position du centre dans le même dialogue —
redimensionner et placer sont le même geste dans la pratique.
"""

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
    QVBoxLayout
)

from src.gui.widgets import SpinCote


class RedimensionnerDialog(QDialog):
    """Cotes visées, pourcentages, et centre où poser la sélection."""

    def __init__(self, parent, largeur: float, hauteur: float,
                 centre_x: float, centre_y: float, titre: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Redimensionner")
        self.setMinimumWidth(360)
        self.w0, self.h0 = float(largeur), float(hauteur)
        self.cx0, self.cy0 = float(centre_x), float(centre_y)
        self._garde = False

        disposition = QVBoxLayout(self)
        disposition.addWidget(QLabel(f"<b>{titre or 'Sélection'}</b>"))
        disposition.addWidget(QLabel(
            f"Dimensions actuelles : {self.w0:g} × {self.h0:g} mm"
            f"<br>Centre actuel : {self.cx0:g} · {self.cy0:g} mm"))

        def _spin(valeur, mini, maxi):
            """L'unité va dans l'étiquette: DANS le champ, elle entre
            dans la sélection et il faut la contourner."""
            widget = SpinCote()
            widget.setRange(mini, maxi)
            widget.setValue(valeur)
            return widget

        formulaire = QFormLayout()
        self.proportions = QCheckBox("Respecter les proportions")
        self.proportions.setChecked(True)
        formulaire.addRow("", self.proportions)
        self.w_x = _spin(self.w0, 0.001, 5000)
        self.w_y = _spin(self.h0, 0.001, 5000)
        self.p_x = _spin(100.0, 0.01, 100000)
        self.p_y = _spin(100.0, 0.01, 100000)
        formulaire.addRow("Largeur X (mm)", self.w_x)
        formulaire.addRow("Largeur Y (mm)", self.w_y)
        formulaire.addRow("Échelle X (%)", self.p_x)
        formulaire.addRow("Échelle Y (%)", self.p_y)
        disposition.addLayout(formulaire)

        # tourner l'ensemble sur lui-même: autour du centre de son
        # emprise (sens trigonométrique)
        rotation = QFormLayout()
        self.angle = SpinCote()
        self.angle.setRange(-360.0, 360.0)
        self.angle.setValue(0.0)
        self.angle.setToolTip(
            "Tourne la sélection autour du centre de l'ensemble "
            "(sens trigonométrique; négatif: sens horaire)")
        rotation.addRow("Rotation (°)", self.angle)
        disposition.addLayout(rotation)

        placement = QFormLayout()
        self.deplacer = QCheckBox("Positionner le centre")
        self.deplacer.setToolTip(
            "Déplace la sélection pour que le centre de son emprise "
            "tombe sur les cotes données.")
        placement.addRow("", self.deplacer)
        self.c_x = _spin(self.cx0, -5000, 5000)
        self.c_y = _spin(self.cy0, -5000, 5000)
        for widget in (self.c_x, self.c_y):
            widget.setEnabled(False)
        self.deplacer.toggled.connect(self.c_x.setEnabled)
        self.deplacer.toggled.connect(self.c_y.setEnabled)
        placement.addRow("Centre X (mm)", self.c_x)
        placement.addRow("Centre Y (mm)", self.c_y)
        disposition.addLayout(placement)

        boutons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        boutons.accepted.connect(self.accept)
        boutons.rejected.connect(self.reject)
        disposition.addWidget(boutons)

        # Les quatre champs disent la même chose de deux façons: ils
        # se suivent l'un l'autre, sans boucler
        self.w_x.valueChanged.connect(
            lambda v: self._depuis_cote('x', v))
        self.w_y.valueChanged.connect(
            lambda v: self._depuis_cote('y', v))
        self.p_x.valueChanged.connect(
            lambda v: self._depuis_pourcent('x', v))
        self.p_y.valueChanged.connect(
            lambda v: self._depuis_pourcent('y', v))

    def _depuis_cote(self, axe: str, valeur: float):
        if self._garde:
            return
        self._garde = True
        try:
            base = self.w0 if axe == 'x' else self.h0
            pourcent = (valeur / base * 100.0) if base else 100.0
            (self.p_x if axe == 'x' else self.p_y).setValue(pourcent)
            if self.proportions.isChecked():
                if axe == 'x':
                    self.p_y.setValue(pourcent)
                    self.w_y.setValue(self.h0 * pourcent / 100.0)
                else:
                    self.p_x.setValue(pourcent)
                    self.w_x.setValue(self.w0 * pourcent / 100.0)
        finally:
            self._garde = False

    def _depuis_pourcent(self, axe: str, valeur: float):
        if self._garde:
            return
        self._garde = True
        try:
            base = self.w0 if axe == 'x' else self.h0
            (self.w_x if axe == 'x' else self.w_y).setValue(
                base * valeur / 100.0)
            if self.proportions.isChecked():
                if axe == 'x':
                    self.p_y.setValue(valeur)
                    self.w_y.setValue(self.h0 * valeur / 100.0)
                else:
                    self.p_x.setValue(valeur)
                    self.w_x.setValue(self.w0 * valeur / 100.0)
        finally:
            self._garde = False

    def facteurs(self) -> tuple:
        """(fx, fy) — les facteurs d'échelle retenus."""
        fx = (self.w_x.value() / self.w0) if self.w0 else 1.0
        fy = (self.w_y.value() / self.h0) if self.h0 else 1.0
        return fx, fy

    def rotation(self) -> float:
        """L'angle de rotation demandé (°, sens trigonométrique)."""
        return float(self.angle.value())

    def centre_vise(self):
        """(x, y) si l'utilisateur veut placer le centre, sinon None."""
        if not self.deplacer.isChecked():
            return None
        return self.c_x.value(), self.c_y.value()
