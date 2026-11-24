# -*- coding: utf-8 -*-
"""Choisir une police: haut, sur plusieurs colonnes, avec les récentes.

Quatre cent soixante-six polices dans un menu déroulant de dix lignes,
ce n'est pas un choix, c'est une recherche à l'aveugle. Ici: une
fenêtre haute, les familles sur autant de colonnes qu'on veut, chacune
écrite dans sa police, un filtre, la colonne des récentes (les deux
cents dernières choisies, la plus récente en tête), et l'aperçu du
texte dans la police retenue.
"""

from typing import List, Sequence

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QSpinBox, QVBoxLayout,
    QWidget
)

#: combien de polices récentes on garde
RECENTES_MAXI = 200

#: colonnes par défaut de la liste
COLONNES_DEFAUT = 3


def _reglages(widget):
    """Les réglages de l'application, par la fenêtre — ou None."""
    fenetre = widget.window() if widget is not None else None
    panneau = getattr(fenetre, 'params_panel', None)
    return getattr(panneau, '_app_settings', None), panneau


def polices_recentes(widget) -> List[str]:
    reglages, _panneau = _reglages(widget)
    if not reglages:
        return []
    return [str(p) for p in (reglages.get('polices_recentes') or [])]


def noter_police_recente(widget, famille: str) -> List[str]:
    """La police choisie passe en tête des récentes (200 gardées)."""
    reglages, panneau = _reglages(widget)
    if not reglages or not famille:
        return []
    recentes = [p for p in (reglages.get('polices_recentes') or [])
                if p != famille]
    recentes.insert(0, famille)
    reglages['polices_recentes'] = recentes[:RECENTES_MAXI]
    try:
        panneau.save_app_settings()
    except Exception:
        pass
    return reglages['polices_recentes']


class PoliceDialog(QDialog):
    """La fenêtre de choix."""

    def __init__(self, parent, familles: Sequence[str],
                 courante: str = "", recentes: Sequence[str] = (),
                 colonnes: int = COLONNES_DEFAUT, apercu: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Police")
        self.resize(960, 640)
        self._familles = list(familles)
        self._choix = courante
        self._apercu_texte = apercu.strip() or "NeoDrive 0123"

        disposition = QVBoxLayout(self)
        haut = QHBoxLayout()
        self._filtre = QLineEdit()
        self._filtre.setPlaceholderText("Chercher une police…")
        self._filtre.textChanged.connect(self._remplir)
        haut.addWidget(self._filtre, stretch=1)
        haut.addWidget(QLabel("Colonnes"))
        self._colonnes = QSpinBox()
        self._colonnes.setRange(1, 6)
        self._colonnes.setValue(max(1, min(6, int(colonnes or 3))))
        self._colonnes.valueChanged.connect(lambda _v: self._mettre_en_grille())
        haut.addWidget(self._colonnes)
        disposition.addLayout(haut)

        milieu = QHBoxLayout()
        gauche = QVBoxLayout()
        self._titre_recentes = QLabel("Récentes")
        gauche.addWidget(self._titre_recentes)
        self._recentes = QListWidget()
        self._recentes.setFixedWidth(220)
        self._recentes.itemClicked.connect(self._sur_item)
        self._recentes.itemDoubleClicked.connect(self._sur_double)
        gauche.addWidget(self._recentes)
        milieu.addLayout(gauche)

        droite = QVBoxLayout()
        self._titre_toutes = QLabel("Toutes")
        droite.addWidget(self._titre_toutes)
        self._toutes = QListWidget()
        self._toutes.setFlow(QListWidget.Flow.LeftToRight)
        self._toutes.setWrapping(True)
        self._toutes.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._toutes.itemClicked.connect(self._sur_item)
        self._toutes.itemDoubleClicked.connect(self._sur_double)
        droite.addWidget(self._toutes, stretch=1)
        milieu.addLayout(droite, stretch=1)
        disposition.addLayout(milieu, stretch=1)

        self._apercu = QLabel(self._apercu_texte)
        self._apercu.setMinimumHeight(48)
        self._apercu.setAlignment(Qt.AlignmentFlag.AlignCenter)
        disposition.addWidget(self._apercu)

        boutons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        boutons.button(QDialogButtonBox.StandardButton.Cancel).setText(
            "Annuler")
        boutons.accepted.connect(self.accept)
        boutons.rejected.connect(self.reject)
        disposition.addWidget(boutons)

        self._recentes_liste = [r for r in recentes if r in self._familles]
        self._remplir()
        self._montrer_apercu()

    # ── les listes ──

    def _item(self, famille: str) -> QListWidgetItem:
        item = QListWidgetItem(famille)
        police = QFont(famille)
        police.setPointSize(11)
        item.setFont(police)
        item.setToolTip(famille)
        return item

    def _remplir(self, *_):
        filtre = self._filtre.text().strip().lower()
        self._recentes.clear()
        for famille in self._recentes_liste:
            if not filtre or filtre in famille.lower():
                self._recentes.addItem(self._item(famille))
        self._titre_recentes.setText(
            f"Récentes ({self._recentes.count()})")
        self._toutes.clear()
        for famille in self._familles:
            if not filtre or filtre in famille.lower():
                self._toutes.addItem(self._item(famille))
        self._titre_toutes.setText(f"Toutes ({self._toutes.count()})")
        self._mettre_en_grille()
        self._selectionner(self._choix)

    def _mettre_en_grille(self):
        colonnes = max(1, self._colonnes.value())
        largeur = max(80, (self._toutes.viewport().width() - 4) // colonnes)
        self._toutes.setGridSize(QSize(largeur, 26))
        # chaque item prend sa case entière: sinon le nom s'élidait
        # à la largeur du premier item
        for rang in range(self._toutes.count()):
            self._toutes.item(rang).setSizeHint(QSize(largeur - 4, 24))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._mettre_en_grille()

    def _selectionner(self, famille: str):
        for liste in (self._toutes, self._recentes):
            for rang in range(liste.count()):
                item = liste.item(rang)
                if item.text() == famille:
                    liste.setCurrentItem(item)
                    liste.scrollToItem(item)
                    if liste is self._toutes:
                        return
        return

    def _sur_item(self, item: QListWidgetItem):
        self._choix = item.text()
        self._montrer_apercu()

    def _sur_double(self, item: QListWidgetItem):
        self._choix = item.text()
        self.accept()

    def _montrer_apercu(self):
        # par la feuille de style: celle de l'application fixe la
        # taille des QLabel, et QFont seul ne passait pas
        famille = (self._choix or "").replace("'", "")
        self._apercu.setStyleSheet(
            f"QLabel {{ font-family: '{famille}'; font-size: 30px; }}")
        self._apercu.setText(
            f"{self._apercu_texte}     — {self._choix or '…'}")

    # ── le résultat ──

    def famille(self) -> str:
        return self._choix

    def colonnes(self) -> int:
        return self._colonnes.value()


class PolicePicker(QWidget):
    """Le champ « Police » d'un formulaire: un bouton écrit dans la
    police courante, qui ouvre la fenêtre de choix."""

    changed = Signal(str)

    def __init__(self, familles: Sequence[str], courante: str = "",
                 parent=None):
        super().__init__(parent)
        self._familles = list(familles)
        self._courante = courante if courante in self._familles \
            else (self._familles[0] if self._familles else "")
        disposition = QHBoxLayout(self)
        disposition.setContentsMargins(0, 0, 0, 0)
        self._bouton = QPushButton()
        self._bouton.setCursor(Qt.CursorShape.PointingHandCursor)
        self._bouton.setMinimumHeight(28)
        self._bouton.setToolTip("Choisir la police: liste haute, sur "
                                "plusieurs colonnes, avec les récentes")
        self._bouton.clicked.connect(self._choisir)
        disposition.addWidget(self._bouton, stretch=1)
        self._montrer()

    def _montrer(self):
        self._bouton.setText(self._courante or "(police)")
        police = QFont(self._courante) if self._courante else QFont()
        police.setPointSize(11)
        self._bouton.setFont(police)

    def currentText(self) -> str:
        """Comme un QComboBox: c'est ce que le formulaire lit."""
        return self._courante

    def setCurrentText(self, famille: str):
        if famille in self._familles and famille != self._courante:
            self._courante = famille
            self._montrer()
            self.changed.emit(famille)

    def _choisir(self):
        reglages, panneau = _reglages(self)
        colonnes = COLONNES_DEFAUT
        if reglages:
            try:
                colonnes = int(reglages.get('police_colonnes',
                                            COLONNES_DEFAUT))
            except (TypeError, ValueError):
                colonnes = COLONNES_DEFAUT
        boite = PoliceDialog(self, self._familles, self._courante,
                             polices_recentes(self), colonnes,
                             apercu=self._apercu_texte())
        if boite.exec() != QDialog.DialogCode.Accepted:
            return
        if reglages is not None and panneau is not None:
            reglages['police_colonnes'] = boite.colonnes()
        famille = boite.famille()
        if famille:
            noter_police_recente(self, famille)
            self.setCurrentText(famille)

    def _apercu_texte(self) -> str:
        """Le texte de l'opération, s'il est sous la main."""
        parent = self.parent()
        while parent is not None:
            widgets = getattr(parent, '_widgets', None)
            if isinstance(widgets, dict) and 'texte' in widgets:
                champ = widgets['texte']
                try:
                    return (champ.toPlainText() if hasattr(
                        champ, 'toPlainText') else champ.text())
                except RuntimeError:
                    return ""
            parent = parent.parent()
        return ""
