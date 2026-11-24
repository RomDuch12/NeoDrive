# -*- coding: utf-8 -*-
"""Ce qu'on sort du canvas, et sous quelle forme.

Un dessin ne sort pas toujours pour la même raison. Renvoyer le plan
au client: le dessin seul, en PDF. Faire découper une tôle: le dessin
seul, en SVG noir. Archiver la préparation: le dessin, ses annotations
et le parcours, en DXF. Tout sortir à chaque fois oblige à nettoyer
dans un autre logiciel — et exporter uniquement en DXF oblige à
convertir ailleurs.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFrame, QLabel,
    QVBoxLayout
)

#: ce qui a été choisi la dernière fois — deux exports d'affilée
#: veulent presque toujours la même chose
_DERNIER = {}


class ExportDessinDialog(QDialog):
    """Calques à sortir, couleurs, format de fichier."""

    def __init__(self, parent=None, compte: dict = None,
                 calques=None, couleurs=None, formats=None):
        super().__init__(parent)
        from src.gui.dxf.dxf_canvas import DxfCanvas
        self.setWindowTitle("Exporter le dessin")
        self.setMinimumWidth(420)
        compte = compte or {}
        calques = calques or DxfCanvas.CALQUES_EXPORT
        couleurs = couleurs or DxfCanvas.COULEURS_EXPORT
        formats = formats or DxfCanvas.FORMATS_EXPORT

        disposition = QVBoxLayout(self)
        disposition.addWidget(QLabel(
            "<b>Quels calques faut-il sortir ?</b>"))

        #: cases à cocher, une par calque du canvas
        self._cases = {}
        retenus = _DERNIER.get('calques')
        for cle, libelle, bulle in calques:
            n = int(compte.get(cle, 0))
            case = QCheckBox(libelle if n == 0 else f"{libelle}   ({n})")
            case.setToolTip(bulle)
            # Ne pas proposer de cocher ce qui n'existe pas
            case.setEnabled(n > 0)
            defaut = (cle in retenus if retenus is not None
                      else cle in ('dxf', 'drawn', 'texte', 'smb'))
            case.setChecked(bool(defaut) and n > 0)
            disposition.addWidget(case)
            self._cases[cle] = case

        trait = QFrame()
        trait.setFrameShape(QFrame.Shape.HLine)
        disposition.addWidget(trait)

        disposition.addWidget(QLabel("<b>Format de sortie</b>"))
        self.format_cb = QComboBox()
        for cle, libelle, filtre, suffixe in formats:
            self.format_cb.addItem(libelle, (cle, filtre, suffixe))
        disposition.addWidget(self.format_cb)

        self._label_couleurs = QLabel("<b>Couleurs</b>")
        disposition.addWidget(self._label_couleurs)
        self.couleurs_cb = QComboBox()
        for cle, libelle, bulle in couleurs:
            self.couleurs_cb.addItem(libelle, cle)
            self.couleurs_cb.setItemData(
                self.couleurs_cb.count() - 1, bulle,
                Qt.ItemDataRole.ToolTipRole)
        disposition.addWidget(self.couleurs_cb)

        self.note = QLabel("")
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: #a6adc8; font-size: 11px;")
        disposition.addWidget(self.note)

        boutons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        boutons.accepted.connect(self.accept)
        boutons.rejected.connect(self.reject)
        disposition.addWidget(boutons)
        self._ok = boutons.button(QDialogButtonBox.StandardButton.Ok)

        # Retrouver le format et les couleurs du dernier export
        self._choisir(self.format_cb, _DERNIER.get('format'),
                      lambda d: d[0])
        self._choisir(self.couleurs_cb, _DERNIER.get('couleurs'),
                      lambda d: d)

        for case in self._cases.values():
            case.toggled.connect(self._verifier)
        self.format_cb.currentIndexChanged.connect(self._verifier)
        self._verifier()

    @staticmethod
    def _choisir(combo, valeur, cle):
        if valeur is None:
            return
        for i in range(combo.count()):
            if cle(combo.itemData(i)) == valeur:
                combo.setCurrentIndex(i)
                return

    def format_choisi(self) -> tuple:
        """(clé, filtre de fichier, suffixe)."""
        return tuple(self.format_cb.currentData())

    def _verifier(self, *_args):
        """Un fichier vide n'aurait pas de sens; et un DXF porte ses
        propres couleurs de calque — le choix ne s'y applique pas."""
        coches = [c for c in self._cases.values() if c.isChecked()]
        if self._ok is not None:
            self._ok.setEnabled(bool(coches))
        cle, _filtre, _suffixe = self.format_choisi()
        dxf = (cle == 'dxf')
        self.couleurs_cb.setEnabled(not dxf)
        self._label_couleurs.setEnabled(not dxf)
        if dxf:
            self.note.setText(
                "Le DXF porte ses propres calques (DXF, DESSIN, SMB, "
                "ANNOTATION, CENTRES, PARCOURS) avec leurs couleurs: "
                "le fichier reste triable une fois ouvert ailleurs.")
        elif cle == 'pdf':
            self.note.setText(
                "Page A4 à une échelle normalisée, avec cartouche "
                "(échelle, étendue, date).")
        elif cle == 'svg':
            self.note.setText(
                "Vectoriel à l'échelle 1:1 — 1 mm du dessin fait "
                "1 mm à l'ouverture.")
        elif cle in ('eps', 'ai'):
            self.note.setText(
                "PostScript vectoriel, à l'échelle 1:1. Le « .ai » "
                "est le même fichier: c'est le format Illustrator "
                "jusqu'à la version 8. Les annotations partent en "
                "contours de lettres — aucune police à fournir.")
        else:
            self.note.setText(
                "Image en pixels: pratique à coller dans un compte "
                "rendu, pas à ré-usiner.")

    def choix(self) -> dict:
        """Ce que l'utilisateur a retenu, et qu'on retient aussi."""
        cle, filtre, suffixe = self.format_choisi()
        retenu = {
            'calques': [c for c, case in self._cases.items()
                        if case.isChecked()],
            'format': cle,
            'filtre': filtre,
            'suffixe': suffixe,
            'couleurs': self.couleurs_cb.currentData(),
        }
        _DERNIER['calques'] = list(retenu['calques'])
        _DERNIER['format'] = cle
        _DERNIER['couleurs'] = retenu['couleurs']
        return retenu
