# -*- coding: utf-8 -*-
"""Champs numériques communs à toute l'application.

Trois défauts revenaient dans chaque formulaire, et il y en a une
cinquantaine:

- « 12,000 » là où l'on a saisi 12. Les décimales servent à ÉCRIRE
  0,05 mm, pas à être relues;
- un double-clic ne prenait que les unités ou que les décimales — la
  virgule sépare deux « mots » pour Qt, on retapait par-dessus la
  moitié d'un nombre;
- l'unité écrite DANS le champ (« 12,000 mm »): elle entre dans la
  sélection, il faut la contourner à chaque correction.

`SpinCote` et `SpinEntier` corrigent les trois. L'unité se met à
côté du champ, avec `etiquette_unite`.
"""

from PySide6.QtCore import QEvent, QTimer
from PySide6.QtWidgets import (
    QAbstractSpinBox, QDoubleSpinBox, QLabel, QSpinBox
)


class _PriseTotale:
    """Entrer dans un champ, c'est le prendre en entier.

    Mêmes gestes pour les entiers et les décimaux; le comportement
    vit ici pour n'être écrit qu'une fois."""

    def _ecouter_le_champ(self):
        """Un spin délègue la saisie à un QLineEdit ENFANT.

        C'est lui qui reçoit la souris: redéfinir
        `mouseDoubleClickEvent` sur le spin ne servait à rien —
        mesuré, un double-clic sur « 12,5 » ne prenait que « 5 »."""
        champ = self.lineEdit()
        if champ is not None:
            champ.installEventFilter(self)

    def eventFilter(self, objet, evenement):
        if (evenement.type() == QEvent.Type.MouseButtonDblClick
                and objet is self.lineEdit()):
            # Laisser Qt faire sa sélection de mot, puis tout prendre
            self._armer_prise()
        return super().eventFilter(objet, evenement)

    def _armer_prise(self):
        # Après le clic: Qt place d'abord le curseur, on prend ensuite
        QTimer.singleShot(0, self._prendre_tout)

    def _prendre_tout(self):
        try:
            self.selectAll()
        except RuntimeError:      # champ détruit entre-temps
            pass

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self._armer_prise()

    def wheelEvent(self, event):
        # Molette = défilement du formulaire, jamais un réglage subi
        event.ignore()


class SpinCote(_PriseTotale, QDoubleSpinBox):
    """Un nombre affiché comme on l'écrit: 12, et non 12,000."""

    def __init__(self, parent=None, decimales: int = 3):
        super().__init__(parent)
        self.setDecimals(decimales)
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._ecouter_le_champ()

    def textFromValue(self, valeur: float) -> str:
        """Sans les zéros de queue — séparateur local respecté."""
        texte = super().textFromValue(valeur)
        separateur = self.locale().decimalPoint()
        if separateur and separateur in texte:
            texte = texte.rstrip('0').rstrip(separateur)
        return texte or "0"

    # Le point ET la virgule: le pavé numérique donne un point, le
    # clavier français une virgule, et le champ refusait l'un des
    # deux (« 0.5 » restait rouge dans le tableau de la gamme).
    def _au_separateur_local(self, texte: str) -> str:
        separateur = self.locale().decimalPoint()
        autre = '.' if separateur == ',' else ','
        return texte.replace(autre, separateur)

    def validate(self, texte: str, position: int):
        return super().validate(self._au_separateur_local(texte),
                                position)

    def valueFromText(self, texte: str) -> float:
        return super().valueFromText(self._au_separateur_local(texte))


class SpinEntier(_PriseTotale, QSpinBox):
    """Un entier, mêmes gestes que `SpinCote`."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._ecouter_le_champ()


def etiquette_unite(unite: str, parent=None) -> QLabel:
    """L'unité se pose À CÔTÉ du champ, jamais dedans.

    Dans le champ, elle entre dans la sélection et il faut la
    contourner à chaque correction."""
    label = QLabel(unite, parent)
    label.setStyleSheet("color: #a6adc8; font-size: 11px;")
    return label


def formater_cote(valeur: float, decimales: int = 3) -> str:
    """Un nombre écrit court: 12, 12,5, 0,05 — jamais 12,000.

    Sert aux champs qui ne sont pas des spins (saisie libre avec
    calculatrice) pour qu'ils s'affichent comme les autres."""
    texte = f"{float(valeur):.{max(0, int(decimales))}f}"
    if '.' in texte:
        texte = texte.rstrip('0').rstrip('.')
    return texte or "0"
