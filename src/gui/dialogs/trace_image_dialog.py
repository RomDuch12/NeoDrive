"""« Vectoriser une image »: un PNG, un JPG devient des tracés.

À gauche les réglages, à droite l'image pâlie et ce qu'on en tire —
contours en bleu (remplis comme ils seront usinés), lignes médianes en
orange —, recalculé à chaque réglage. La barre de progression, avec
son Annuler, est en bas de la fenêtre: une grande photo demande
quelques secondes. « Importer » pose les tracés au canvas, dans leur
onglet d'import (src/io/vecteur/trace_image fait le travail)."""

import os
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QHBoxLayout, QLabel, QSpinBox, QVBoxLayout, QWidget
)

from src.gui.widgets import SpinCote
from src.io.vecteur import trace_image as ti

BLEU, ORANGE = "#89b4fa", "#fab387"

MODES = (('contours', "Contours (zones pleines)"),
         ('traits', "Traits: ligne médiane (un passage d'outil)"),
         ('les_deux', "Les deux: traits fins en ligne médiane, "
                      "le reste en contour"))


class ApercuTrace(QWidget):
    """L'image pâlie, le tracé par-dessus."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(460, 360)
        self.image: Optional[QImage] = None
        self.trace: Optional[ti.Trace] = None

    def _cadre(self):
        """Le rectangle où l'image se peint (proportions gardées)."""
        if self.image is None or self.image.isNull():
            return None
        w, h = self.image.width(), self.image.height()
        s = min((self.width() - 16) / max(1, w),
                (self.height() - 16) / max(1, h))
        return QRectF((self.width() - s * w) / 2, (self.height() - s * h) / 2,
                      s * w, s * h)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#11111b"))
        cadre = self._cadre()
        if cadre is None:
            p.end()
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setOpacity(0.35)
        p.drawImage(cadre, self.image)
        p.setOpacity(1.0)
        t = self.trace
        if t is not None and t.taille_px[0]:
            w, h = t.taille_px
            kx = cadre.width() / max(1, w)
            ky = cadre.height() / max(1, h)
            s = t.mm_par_pixel

            def ecran(x, y):
                return QPointF(cadre.left() + (x / s + 0.5) * kx,
                               cadre.top() + (h - 1 - y / s + 0.5) * ky)

            chemin = QPainterPath()
            chemin.setFillRule(Qt.FillRule.OddEvenFill)
            for c in t.contours:
                chemin.moveTo(ecran(*c[0]))
                for q in c[1:]:
                    chemin.lineTo(ecran(*q))
                chemin.closeSubpath()
            p.setBrush(QBrush(QColor(137, 180, 250, 70)))
            p.setPen(QPen(QColor(BLEU), 1.2))
            p.drawPath(chemin)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(ORANGE), 1.6))
            for tr in t.traits:
                ch = QPainterPath(ecran(*tr[0]))
                for q in tr[1:]:
                    ch.lineTo(ecran(*q))
                p.drawPath(ch)
        p.end()


class DialogueTraceImage(QDialog):
    """Les réglages du traceur, l'aperçu, l'import."""

    #: délai entre un réglage et le recalcul (ms)
    DELAI = 350

    def __init__(self, chemin: str, parent=None, reglages=None,
                 dessin_present: bool = False):
        super().__init__(parent)
        from src.gui.progression import ZoneProgression
        self.chemin = str(chemin)
        self.setWindowTitle(f"Vectoriser une image — "
                            f"{os.path.basename(self.chemin)}")
        self.resize(980, 600)
        r = reglages or ti.Reglages()
        self.trace: Optional[ti.Trace] = None
        self._occupe = False
        self._encore = False

        self._image = QImage(self.chemin)
        self._gris = ti.lire_image(self.chemin)

        racine = QVBoxLayout(self)
        haut = QHBoxLayout()
        racine.addLayout(haut, 1)
        gauche = QWidget()
        gauche.setMaximumWidth(380)
        form = QFormLayout(gauche)
        haut.addWidget(gauche)

        self.mode = QComboBox()
        for cle, texte in MODES:
            self.mode.addItem(texte, cle)
        self.mode.setCurrentIndex(max(0, self.mode.findData(r.mode)))
        self.mode.setToolTip(
            "Contours: le bord des zones sombres, fermé (poche, gravure "
            "au V).\nTraits: la ligne médiane des traits fins — "
            "l'outil passe une fois, comme une plume (signature, dessin "
            "au trait).")
        form.addRow("Tracer", self.mode)

        self.seuil_auto = QCheckBox("automatique (Otsu)")
        self.seuil_auto.setChecked(r.seuil is None)
        self.seuil = QSpinBox()
        self.seuil.setRange(1, 255)
        self.seuil.setValue(int(r.seuil if r.seuil is not None else 128))
        self.seuil.setToolTip("Plus sombre que ce gris (0 noir – 255 "
                              "blanc): tracé.")
        ligne = QHBoxLayout()
        ligne.addWidget(self.seuil_auto)
        ligne.addWidget(self.seuil)
        form.addRow("Seuil", ligne)

        self.inverser = QCheckBox("tracer le clair (logo blanc sur fond "
                                  "sombre)")
        self.inverser.setChecked(bool(r.inverser))
        form.addRow("", self.inverser)

        self.largeur = SpinCote(decimales=2)
        self.largeur.setRange(0.1, 5000.0)
        self.largeur.setValue(float(r.largeur_mm))
        self.hauteur = QLabel("")
        ligne = QHBoxLayout()
        ligne.addWidget(self.largeur)
        ligne.addWidget(self.hauteur)
        form.addRow("Largeur (mm)", ligne)

        self.largeur_trait = SpinCote(decimales=2)
        self.largeur_trait.setRange(0.05, 100.0)
        self.largeur_trait.setValue(float(r.largeur_trait_mm))
        self.largeur_trait.setToolTip(
            "Mode « les deux »: un trait plus large que ça (en "
            "moyenne) reste un contour.")
        form.addRow("Trait au plus (mm)", self.largeur_trait)

        self.bruit = QSpinBox()
        self.bruit.setRange(0, 100000)
        self.bruit.setValue(int(r.bruit))
        self.bruit.setToolTip("Taches et trous de moins de tant de "
                              "pixels: ignorés (poussières d'un scan).")
        form.addRow("Bruit (px)", self.bruit)

        self.lissage = SpinCote(decimales=2)
        self.lissage.setRange(0.0, 8.0)
        self.lissage.setValue(float(r.lissage))
        self.lissage.setToolTip("Flou avant le contour: 0 = bord en "
                                "escalier, 1 = bord lisse.")
        form.addRow("Lissage (px)", self.lissage)

        self.fidelite = SpinCote(decimales=2)
        self.fidelite.setRange(0.05, 10.0)
        self.fidelite.setValue(float(r.fidelite))
        self.fidelite.setToolTip("Écart toléré entre le tracé et l'image, "
                                 "en pixels: plus petit = plus de points.")
        form.addRow("Fidélité (px)", self.fidelite)

        self.ajouter = QCheckBox("ajouter au dessin en place")
        self.ajouter.setChecked(False)
        self.ajouter.setEnabled(bool(dessin_present))
        self.ajouter.setToolTip("Sinon, le dessin en place est remplacé "
                                "(ses imports restent à rouvrir).")
        form.addRow("", self.ajouter)

        self.resume = QLabel("")
        self.resume.setWordWrap(True)
        self.resume.setStyleSheet("color: #a6adc8;")
        form.addRow(self.resume)

        self.apercu = ApercuTrace()
        self.apercu.image = self._image
        haut.addWidget(self.apercu, 1)

        bas = QHBoxLayout()
        # la progression vit ICI, dans la fenêtre: Annuler y agit
        self._zone_progression = ZoneProgression(self)
        bas.addWidget(self._zone_progression, 1)
        self.boutons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        self.boutons.button(QDialogButtonBox.StandardButton.Ok).setText(
            "Importer")
        self.boutons.accepted.connect(self.accept)
        self.boutons.rejected.connect(self.reject)
        bas.addWidget(self.boutons)
        racine.addLayout(bas)

        self._minuterie = QTimer(self)
        self._minuterie.setSingleShot(True)
        self._minuterie.setInterval(self.DELAI)
        self._minuterie.timeout.connect(self.calculer)
        for w in (self.seuil, self.largeur, self.largeur_trait, self.bruit,
                  self.lissage, self.fidelite):
            w.valueChanged.connect(self._change)
        self.mode.currentIndexChanged.connect(self._change)
        self.seuil_auto.toggled.connect(self._change)
        self.inverser.toggled.connect(self._change)
        self._maj_champs()
        self._minuterie.start()

    # ── réglages ──

    def reglages(self) -> ti.Reglages:
        return ti.Reglages(
            mode=self.mode.currentData(),
            seuil=None if self.seuil_auto.isChecked()
            else float(self.seuil.value()),
            inverser=self.inverser.isChecked(),
            largeur_mm=float(self.largeur.value()),
            bruit=int(self.bruit.value()),
            lissage=float(self.lissage.value()),
            fidelite=float(self.fidelite.value()),
            largeur_trait_mm=float(self.largeur_trait.value()))

    def _maj_champs(self) -> None:
        self.seuil.setEnabled(not self.seuil_auto.isChecked())
        mode = self.mode.currentData()
        self.largeur_trait.setEnabled(mode == 'les_deux')
        self.lissage.setEnabled(mode in ('contours', 'les_deux'))
        h, w = self._gris.shape
        self.hauteur.setText(
            f"× {self.largeur.value() * h / max(1, w):.2f} mm de haut")

    def _change(self, *_args) -> None:
        self._maj_champs()
        self.boutons.button(
            QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self._minuterie.start()

    # ── calcul ──

    def calculer(self) -> Optional[ti.Trace]:
        """Retrace avec les réglages du moment (dans un fil, la barre
        en bas de la fenêtre)."""
        if self._occupe:
            self._encore = True
            return None
        # un recalcul demandé à la main rend l'attente inutile (elle
        # retracerait plus tard, au milieu d'autre chose)
        self._minuterie.stop()
        from src.core.vcarve import Annule
        from src.gui.progression import travailler
        from src.io.vecteur.dxfimport import Cancelled
        reglages = self.reglages()
        gris = self._gris

        def travail(progression):
            try:
                return ti.tracer(gris, reglages, progression)
            except Cancelled:
                raise Annule("vectorisation arrêtée")

        self._occupe = True
        try:
            trace = travailler(self, "Vectorisation", travail,
                               os.path.basename(self.chemin))
        finally:
            self._occupe = False
        if trace is not None:
            self.trace = trace
            self._seuil_vu(trace.seuil)
            self.resume.setText(trace.resume())
            self.apercu.trace = trace
            self.apercu.update()
            self.boutons.button(
                QDialogButtonBox.StandardButton.Ok).setEnabled(
                    bool(trace.contours or trace.traits))
        else:
            self.resume.setText("Vectorisation arrêtée")
        if self._encore:
            self._encore = False
            self._minuterie.start()
        return trace

    def _seuil_vu(self, seuil: float) -> None:
        """Le seuil automatique se montre dans le champ (grisé)."""
        if self.seuil_auto.isChecked():
            self.seuil.blockSignals(True)
            self.seuil.setValue(int(round(seuil)))
            self.seuil.blockSignals(False)

    def calques(self):
        """(calques, rapport) du dernier tracé, pour le canvas."""
        if self.trace is None:
            self.calculer()
        if self.trace is None:
            return {}, None
        calques = ti.calques_de(self.trace)
        return calques, ti.rapport_de(self.trace, calques)
