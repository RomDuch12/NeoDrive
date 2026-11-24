# -*- coding: utf-8 -*-
"""« À propos de NeoDrive »: version, auteur et licence.

NeoDrive est sous licence MIT ou Apache-2.0, au choix (round 32). Le
dialogue le dit et ouvre les textes: LICENSE.txt (à côté de l'exe, ou à
la racine du dépôt) et le dossier licences/ — dans la version portable,
les licences de tout ce que l'exe embarque (tools/licences_tierces.py).
"""
from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

from src import __version__
from src.core.tool_library import get_base_dir

LICENCE_LISIBLE = "MIT ou Apache-2.0, au choix"
# les liens du dialogue: fichier ou dossier, relatif au dossier de l'exe
LIENS = {
    "licence": "LICENSE.txt",
    "tiers": "licences",
}
TAILLE_MINI = QSize(400, 320)


def chemin_du_lien(lien: str, base: str | None = None) -> str:
    return os.path.join(base or get_base_dir(), LIENS[lien])


def ouvrir(chemin: str) -> bool:
    """Le fichier (Bloc-notes pour un .txt) ou le dossier (Explorateur)."""
    return QDesktopServices.openUrl(QUrl.fromLocalFile(chemin))


class DialogueAPropos(QDialog):
    """Le dialogue « À propos »; `base`: le dossier de l'exe (des tests
    en donnent un autre)."""

    def __init__(self, parent=None, base: str | None = None):
        super().__init__(parent)
        self._base = base or get_base_dir()
        self.setWindowTitle("À propos de NeoDrive")
        self.setStyleSheet("background: #1e1e2e; color: #cdd6f4;")
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image = os.path.join(self._base, "data", "NeoDrive.png")
        if os.path.exists(image):
            pm = QPixmap(image)
            if not pm.isNull():
                lbl_img = QLabel()
                lbl_img.setPixmap(pm.scaledToWidth(
                    200, Qt.TransformationMode.SmoothTransformation))
                lbl_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lay.addWidget(lbl_img)
        self.texte = QLabel(
            "<h2 style='color:#89b4fa;'>NeoDrive</h2>"
            f"<p style='color: #a6adc8;'>Version {__version__}</p>"
            "<p>Générateur de programmes SimPl pour Datron</p>"
            "<p style='color: #a6adc8;'>Créé par RomDuch</p>")
        self.texte.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.texte)
        self.licence = QLabel(
            f"<p>Logiciel libre — licence {LICENCE_LISIBLE}<br>"
            "<a href='licence' style='color:#89b4fa;'>Licence</a>"
            " &nbsp;·&nbsp; "
            "<a href='tiers' style='color:#89b4fa;'>"
            "Licences du code embarqué</a></p>")
        self.licence.setTextFormat(Qt.TextFormat.RichText)
        self.licence.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.licence.setTextInteractionFlags(
            Qt.TextInteractionFlag.LinksAccessibleByMouse
            | Qt.TextInteractionFlag.LinksAccessibleByKeyboard)
        self.licence.linkActivated.connect(self.ouvrir_lien)
        lay.addWidget(self.licence)
        self.ok_btn = QPushButton("OK")
        self.ok_btn.setObjectName("primary")
        self.ok_btn.setFixedWidth(80)
        self.ok_btn.clicked.connect(self.accept)
        lay.addWidget(self.ok_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        # la taille qu'il faut au contenu, jamais moins qu'avant
        self.setFixedSize(self.sizeHint().expandedTo(TAILLE_MINI))

    def ouvrir_lien(self, lien: str) -> bool:
        chemin = chemin_du_lien(lien, self._base)
        return os.path.exists(chemin) and bool(ouvrir(chemin))
