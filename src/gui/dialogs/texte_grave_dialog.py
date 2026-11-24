# -*- coding: utf-8 -*-
"""Poser un texte à graver, dans une police du poste.

Ce n'est pas une annotation: le texte est VECTORISÉ tout de suite,
et ce qui arrive au canvas est un tracé — comme un contour venu d'un
DXF. Il se sélectionne, se déplace, se met à la cote, et se grave
avec les mêmes opérations.

La hauteur demandée est celle des CAPITALES: la taille en points
d'une police ne dit rien de la hauteur des lettres, et deux polices
de même corps ne gravent pas la même cote.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPainterPath
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFontComboBox,
    QFormLayout, QLabel, QLineEdit, QVBoxLayout, QWidget
)

from src.gui.widgets import SpinCote

#: ce qui a été choisi la dernière fois — on grave rarement une
#: seule ligne, et rarement dans une police différente à chaque fois
_DERNIER = {}


class _Apercu(QWidget):
    """Le texte tel qu'il sera gravé: ses contours, rien d'autre."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(70)
        self._chemin = QPainterPath()

    def montrer(self, chemin: QPainterPath):
        self._chemin = chemin
        self.update()

    def paintEvent(self, _event):
        from PySide6.QtGui import QPainter, QPen, QColor
        peintre = QPainter(self)
        peintre.setRenderHint(QPainter.RenderHint.Antialiasing)
        peintre.fillRect(self.rect(), QColor("#181825"))
        rect = self._chemin.boundingRect()
        if rect.isEmpty():
            peintre.setPen(QColor("#6c7086"))
            peintre.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "(rien à graver)")
            return
        marge = 8.0
        facteur = min(
            (self.width() - 2 * marge) / max(rect.width(), 1e-6),
            (self.height() - 2 * marge) / max(rect.height(), 1e-6))
        peintre.translate(self.width() / 2.0, self.height() / 2.0)
        peintre.scale(facteur, facteur)
        peintre.translate(-rect.center().x(), -rect.center().y())
        stylo = QPen(QColor("#f9e2af"))
        stylo.setCosmetic(True)
        stylo.setWidthF(1.2)
        peintre.setPen(stylo)
        peintre.setBrush(Qt.BrushStyle.NoBrush)
        peintre.drawPath(self._chemin)


class TexteGraveDialog(QDialog):
    """Texte, police, hauteur — et l'aperçu de ce qui sera tracé."""

    ALIGNEMENTS = ("Gauche", "Centre", "Droite")

    def __init__(self, parent=None, texte: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Texte à graver")
        self.setMinimumWidth(420)

        disposition = QVBoxLayout(self)
        formulaire = QFormLayout()

        self.texte = QLineEdit(texte or _DERNIER.get('texte', ""))
        self.texte.setPlaceholderText("Ce qui sera gravé")
        formulaire.addRow("Texte", self.texte)

        self.police = QFontComboBox()
        nom = _DERNIER.get('police')
        if nom:
            self.police.setCurrentFont(QFont(nom))
        formulaire.addRow("Police", self.police)

        self.hauteur = SpinCote()
        self.hauteur.setRange(0.2, 500.0)
        self.hauteur.setValue(float(_DERNIER.get('hauteur', 5.0)))
        self.hauteur.setToolTip(
            "Hauteur des CAPITALES, en millimètres.")
        formulaire.addRow("Hauteur (mm)", self.hauteur)

        self.gras = QCheckBox("Gras")
        self.gras.setChecked(bool(_DERNIER.get('gras', False)))
        self.italique = QCheckBox("Italique")
        self.italique.setChecked(bool(_DERNIER.get('italique', False)))
        styles = QWidget()
        from PySide6.QtWidgets import QHBoxLayout
        ligne = QHBoxLayout(styles)
        ligne.setContentsMargins(0, 0, 0, 0)
        ligne.addWidget(self.gras)
        ligne.addWidget(self.italique)
        ligne.addStretch()
        formulaire.addRow("Style", styles)

        self.alignement = QComboBox()
        self.alignement.addItems(list(self.ALIGNEMENTS))
        self.alignement.setCurrentText(
            str(_DERNIER.get('alignement', "Gauche")))
        self.alignement.setToolTip(
            "Par rapport au point où l'on clique.")
        formulaire.addRow("Aligné", self.alignement)
        disposition.addLayout(formulaire)

        self.apercu = _Apercu()
        disposition.addWidget(self.apercu)
        self.etat = QLabel("")
        self.etat.setStyleSheet("color: #a6adc8; font-size: 11px;")
        disposition.addWidget(self.etat)

        boutons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        boutons.accepted.connect(self.accept)
        boutons.rejected.connect(self.reject)
        disposition.addWidget(boutons)
        self._ok = boutons.button(QDialogButtonBox.StandardButton.Ok)

        for signal in (self.texte.textChanged,
                       self.police.currentFontChanged,
                       self.hauteur.valueChanged,
                       self.gras.toggled, self.italique.toggled):
            signal.connect(self._rafraichir)
        self._rafraichir()

    # ── ce que l'appelant récupère ──

    def police_choisie(self) -> QFont:
        police = QFont(self.police.currentFont())
        police.setBold(self.gras.isChecked())
        police.setItalic(self.italique.isChecked())
        return police

    def choix(self) -> dict:
        retenu = {
            'texte': self.texte.text().strip(),
            'police': self.police_choisie(),
            'hauteur': float(self.hauteur.value()),
            'alignement': self.alignement.currentText(),
        }
        _DERNIER.update({
            'texte': retenu['texte'],
            'police': self.police.currentFont().family(),
            'hauteur': retenu['hauteur'],
            'gras': self.gras.isChecked(),
            'italique': self.italique.isChecked(),
            'alignement': retenu['alignement'],
        })
        return retenu

    # ── aperçu ──

    def _rafraichir(self, *_args):
        from src.gui.dxf.dxf_canvas import DxfCanvas
        texte = self.texte.text().strip()
        chemin = QPainterPath()
        if texte:
            chemin = DxfCanvas.chemin_texte(
                texte, self.police_choisie(), self.hauteur.value())
        self.apercu.montrer(chemin)
        if self._ok is not None:
            self._ok.setEnabled(not chemin.isEmpty())
        if chemin.isEmpty():
            self.etat.setText(
                "Aucun contour: police sans dessin pour ce texte ?"
                if texte else "")
            return
        rect = chemin.boundingRect()
        contours = len(chemin.toSubpathPolygons())
        message = (f"{contours} contour(s) — {rect.width():.2f} × "
                   f"{rect.height():.2f} mm")
        # Une police absente du poste est REMPLACÉE en silence par
        # Qt: on graverait le dessin d'une autre police, ou des
        # rectangles. L'aperçu le montre, l'état le dit.
        from PySide6.QtGui import QFontInfo
        demandee = self.police.currentFont().family()
        reelle = QFontInfo(self.police_choisie()).family()
        if reelle and reelle.lower() != demandee.lower():
            message += f" — police remplacée par « {reelle} »"
        self.etat.setText(message)
