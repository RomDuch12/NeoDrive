"""L'éditeur des plaques de reprise (src/core/plaques): la liste, les
cotes, les trous (un par un, en motif, ou lus d'un DXF), l'aperçu."""

from typing import Dict, Optional

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QPainter, QPen, QColor, QPolygonF
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QVBoxLayout, QListWidget,
                               QPushButton, QLineEdit, QGridLayout, QLabel,
                               QTableWidget, QTableWidgetItem, QWidget,
                               QFileDialog, QComboBox)

from src.gui.widgets import SpinCote


class _Apercu(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.plaque: Optional[Dict] = None
        self.setMinimumSize(260, 200)

    def paintEvent(self, _e):
        from src.core import plaques as pl
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#1e1e2e"))
        if not self.plaque:
            p.end()
            return
        pts = pl.contour(self.plaque) + [tuple(t) for t in
                                         self.plaque.get('trous') or []]
        xs, ys = [q[0] for q in pts], [q[1] for q in pts]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        s = 0.9 * min(self.width() / max(x1 - x0, 1e-3),
                      self.height() / max(y1 - y0, 1e-3))
        ox = (self.width() - s * (x1 - x0)) / 2
        oy = (self.height() + s * (y1 - y0)) / 2

        def v(x, y):
            return QPointF(ox + s * (x - x0), oy - s * (y - y0))

        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor("#9399b2"), 1.2))
        p.drawPolygon(QPolygonF([v(x, y) for x, y in pl.contour(self.plaque)]))
        r = max(1.5, s * float(self.plaque.get('diametre_trou', 4.05)) / 2)
        p.setPen(QPen(QColor("#f9e2af"), 1.0))
        for x, y in self.plaque.get('trous') or []:
            p.drawEllipse(v(x, y), r, r)
        p.end()


class DialoguePlaques(QDialog):

    def __init__(self, parent=None, nom: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Plaques de reprise")
        self.resize(900, 560)
        self.choisie = ""
        self._chemin: Optional[str] = None
        self.liste = QListWidget()
        self.liste.currentRowChanged.connect(self._choisir)
        boutons = QVBoxLayout()
        for texte, action in (("Nouvelle", self.nouvelle),
                              ("Importer un DXF…", self._importer),
                              ("Supprimer", self.supprimer)):
            b = QPushButton(texte)
            b.clicked.connect(action)
            boutons.addWidget(b)
        boutons.addStretch()
        self.nom = QLineEdit()
        self.largeur = SpinCote(decimales=2)
        self.hauteur = SpinCote(decimales=2)
        self.epaisseur = SpinCote(decimales=2)
        self.diametre = SpinCote(decimales=3)
        for sp, maxi in ((self.largeur, 5000), (self.hauteur, 5000),
                         (self.epaisseur, 500), (self.diametre, 50)):
            sp.setRange(0.0, maxi)
        from src.operations.taraudage import THREAD_TYPES
        self.filetage = QComboBox()
        self.filetage.addItems(list(THREAD_TYPES))
        self.zero = QLineEdit()
        self.zero.setToolTip("Où est l'origine de la plaque (coin, goupille)")
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["X", "Y"])
        self.motif = [SpinCote(decimales=3) for _ in range(6)]
        for sp, v in zip(self.motif, (5, 4, 20, 20, 10, 10)):
            sp.setRange(-5000, 5000)
            sp.setValue(v)
        g = QGridLayout()
        for k, (texte, w) in enumerate((("Nom", self.nom),
                                        ("Largeur", self.largeur),
                                        ("Hauteur", self.hauteur),
                                        ("Épaisseur", self.epaisseur),
                                        ("Ø des trous", self.diametre),
                                        ("Filetage", self.filetage),
                                        ("Zéro", self.zero))):
            g.addWidget(QLabel(texte), k, 0)
            g.addWidget(w, k, 1)
        lm = QHBoxLayout()
        for texte, sp in zip(("nx", "ny", "pas X", "pas Y", "X0", "Y0"),
                             self.motif):
            lm.addWidget(QLabel(texte))
            lm.addWidget(sp)
        b_motif = QPushButton("+ Motif")
        b_motif.clicked.connect(lambda: self.ajouter_motif(
            *(sp.value() for sp in self.motif)))
        lm.addWidget(b_motif)
        b_vider = QPushButton("Vider les trous")
        b_vider.clicked.connect(lambda: self.table.setRowCount(0))
        lm.addWidget(b_vider)
        self.apercu = _Apercu()
        enregistrer = QPushButton("Enregistrer")
        enregistrer.clicked.connect(self.enregistrer)
        choisir = QPushButton("Choisir cette plaque")
        choisir.setObjectName("primary")
        choisir.clicked.connect(self._valider)
        fermer = QPushButton("Fermer")
        fermer.clicked.connect(self.reject)
        milieu = QVBoxLayout()
        milieu.addLayout(g)
        milieu.addWidget(self.table, 1)
        milieu.addLayout(lm)
        bas = QHBoxLayout()
        bas.addStretch()
        for b in (enregistrer, choisir, fermer):
            bas.addWidget(b)
        haut = QHBoxLayout()
        gauche = QVBoxLayout()
        gauche.addWidget(self.liste, 1)
        gauche.addLayout(boutons)
        haut.addLayout(gauche, 1)
        haut.addLayout(milieu, 2)
        haut.addWidget(self.apercu, 2)
        v = QVBoxLayout(self)
        v.addLayout(haut, 1)
        v.addLayout(bas)
        self.table.itemChanged.connect(lambda _i: self._maj_apercu())
        self._relire(nom)

    def _relire(self, nom: str = "") -> None:
        from src.core import plaques as pl
        self._liste = pl.lister()
        self.liste.blockSignals(True)
        self.liste.clear()
        for n, _c in self._liste:
            self.liste.addItem(n)
        self.liste.blockSignals(False)
        noms = [n for n, _c in self._liste]
        if nom in noms:
            self.liste.setCurrentRow(noms.index(nom))
        elif noms:
            self.liste.setCurrentRow(0)
        else:
            self.nouvelle()

    def _choisir(self, rang: int) -> None:
        from src.core import plaques as pl
        if 0 <= rang < len(self._liste):
            self._chemin = self._liste[rang][1]
            self.poser(pl.charger(self._chemin))

    def poser(self, p: Dict) -> None:
        self.nom.setText(p['nom'])
        self.largeur.setValue(p['largeur'])
        self.hauteur.setValue(p['hauteur'])
        self.epaisseur.setValue(p['epaisseur'])
        self.diametre.setValue(p['diametre_trou'])
        self.filetage.setCurrentText(p['filetage'])
        self.zero.setText(p['zero'])
        self._contour = p.get('contour') or []
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for x, y in p['trous']:
            self._ligne(x, y)
        self.table.blockSignals(False)
        self._maj_apercu()

    def _ligne(self, x, y) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(f"{x:g}"))
        self.table.setItem(r, 1, QTableWidgetItem(f"{y:g}"))

    def plaque_courante(self) -> Dict:
        from src.core import plaques as pl
        trous = []
        for r in range(self.table.rowCount()):
            try:
                trous.append([float(self.table.item(r, 0).text().replace(
                    ',', '.')), float(self.table.item(r, 1).text().replace(
                        ',', '.'))])
            except (AttributeError, ValueError):
                continue
        p = pl.nouvelle(self.nom.text().strip() or "Plaque",
                        self.largeur.value(), self.hauteur.value())
        p.update({'epaisseur': self.epaisseur.value(),
                  'diametre_trou': self.diametre.value(),
                  'filetage': self.filetage.currentText(),
                  'zero': self.zero.text(), 'trous': trous,
                  'contour': list(getattr(self, '_contour', []) or [])})
        return pl.normaliser(p)

    def _maj_apercu(self) -> None:
        self.apercu.plaque = self.plaque_courante()
        self.apercu.update()

    def nouvelle(self) -> None:
        from src.core import plaques as pl
        self._chemin = None
        self.poser(pl.nouvelle())

    def ajouter_motif(self, nx, ny, px, py, x0, y0) -> None:
        from src.core import plaques as pl
        self.table.blockSignals(True)
        for x, y in pl.motif(int(nx), int(ny), px, py, x0, y0):
            self._ligne(x, y)
        self.table.blockSignals(False)
        self._maj_apercu()

    def importer_dxf(self, chemin: str) -> Dict:
        from src.core import plaques as pl
        p = pl.depuis_dxf(chemin)
        self._chemin = None
        self.poser(p)
        return p

    def _importer(self) -> None:
        chemin, _f = QFileDialog.getOpenFileName(
            self, "Plaque depuis un DXF", "", "DXF (*.dxf)")
        if chemin:
            self.importer_dxf(chemin)

    def enregistrer(self) -> str:
        from src.core import plaques as pl
        p = self.plaque_courante()
        self._chemin = pl.enregistrer(p, None)
        self._relire(p['nom'])
        return self._chemin

    def supprimer(self) -> None:
        from src.core import plaques as pl
        if self._chemin:
            pl.supprimer(self._chemin)
        self._relire()

    def _valider(self) -> None:
        self.enregistrer()
        self.choisie = self.plaque_courante()['nom']
        self.accept()
