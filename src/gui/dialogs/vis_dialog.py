"""Les vis à la main: sur la plaque de reprise, la pièce posée (sa
silhouette et son brut), ses trous — en vert ceux où une vis entre par
le dos de la pièce. Un clic met ou retire une vis; la position du brut
sur la plaque se règle. « Automatique » rend la main au placement
calculé (src/core/tenue.placer_sur_plaque)."""

from typing import Dict, List, Optional

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget
)

from src.gui.widgets import SpinCote

VERT, GRIS, JAUNE, ROUGE = "#a6e3a1", "#585b70", "#f9e2af", "#f38ba8"


class _Plan(QWidget):
    """La plaque vue de dessus, la pièce posée, les trous cliquables."""

    def __init__(self, dialogue, parent=None):
        super().__init__(parent)
        self.d = dialogue
        self.setMinimumSize(520, 380)
        self._vue = None

    def _transformation(self):
        from src.core import plaques as pl
        pts = pl.contour(self.d.plaque) + [tuple(t) for t in
                                           self.d.plaque.get('trous') or []]
        xs, ys = [q[0] for q in pts], [q[1] for q in pts]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        s = 0.92 * min(self.width() / max(x1 - x0, 1e-3),
                       self.height() / max(y1 - y0, 1e-3))
        ox = (self.width() - s * (x1 - x0)) / 2
        oy = (self.height() + s * (y1 - y0)) / 2
        return x0, y0, s, ox, oy

    def vers_ecran(self, x, y) -> QPointF:
        x0, y0, s, ox, oy = self._transformation()
        return QPointF(ox + s * (x - x0), oy - s * (y - y0))

    def vers_plaque(self, px, py):
        x0, y0, s, ox, oy = self._transformation()
        return x0 + (px - ox) / s, y0 + (oy - py) / s

    def paintEvent(self, _e):
        from src.core import plaques as pl
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#1e1e2e"))
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        v = self.vers_ecran
        p.setPen(QPen(QColor("#9399b2"), 1.2))
        p.drawPolygon(QPolygonF([v(x, y) for x, y in
                                 pl.contour(self.d.plaque)]))
        # le brut et la silhouette de la pièce, posés
        dx, dy = self.d.decalage_piece()
        x0, y0, _z0, x1, y1, _z1 = self.d.boite
        p.setPen(QPen(QColor("#fab387"), 1.0, Qt.PenStyle.DashLine))
        p.drawPolygon(QPolygonF([v(x + dx, y + dy) for x, y in
                                 ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]))
        if self.d.silhouette is not None:
            p.setPen(QPen(QColor("#89b4fa"), 1.4))
            p.setBrush(QBrush(QColor(137, 180, 250, 40)))
            for poly in getattr(self.d.silhouette, 'geoms',
                                [self.d.silhouette]):
                p.drawPolygon(QPolygonF([v(x + dx, y + dy) for x, y in
                                         poly.exterior.coords]))
            p.setBrush(Qt.BrushStyle.NoBrush)
        # les trous
        _x0, _y0, s, _ox, _oy = self._transformation()
        r = max(2.5, s * float(self.d.plaque.get('diametre_trou', 4.05)) / 2)
        for (hx, hy), ok in zip(self.d.trous, self.d.vissables):
            pris = self.d.est_choisi(hx, hy)
            couleur = (JAUNE if pris and ok else ROUGE if pris
                       else VERT if ok else GRIS)
            p.setPen(QPen(QColor(couleur), 1.6 if ok else 1.0))
            p.setBrush(QBrush(QColor(couleur)) if pris
                       else Qt.BrushStyle.NoBrush)
            p.drawEllipse(v(hx, hy), r, r)
        p.end()

    def mousePressEvent(self, ev):
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        x, y = self.vers_plaque(ev.position().x(), ev.position().y())
        self.d.basculer_pres_de(x, y)


class DialogueVis(QDialog):
    """Choisir à la main les trous de la plaque où vont les vis."""

    def __init__(self, modele, brut: Dict, tenue: Dict, plaque: Dict,
                 placement: Optional[Dict] = None, parent=None):
        super().__init__(parent)
        from src.core import tenue as tn
        self.setWindowTitle("Vis à la main")
        self.modele, self.brut, self.tenue = modele, brut, tenue
        self.plaque = plaque
        self.boite = tn.boite_brut(modele, brut)
        self.silhouette = tn.silhouette_piece(modele)
        self.trous = [tuple(map(float, t)) for t in plaque.get('trous') or []]
        #: None: placement automatique; sinon les trous choisis
        self.automatique = False
        pos = (placement or {}).get('position')
        if pos is None:
            from src.core import plaques as pl
            from shapely.geometry import Polygon
            c = Polygon(pl.contour(plaque)).centroid
            pos = (c.x, c.y)
        self.choisis: List[tuple] = [tuple(map(float, t)) for t in
                                     (placement or {}).get('trous') or []]
        self.pos_x = SpinCote(decimales=2)
        self.pos_y = SpinCote(decimales=2)
        for sp, val in ((self.pos_x, pos[0]), (self.pos_y, pos[1])):
            sp.setRange(-10000.0, 10000.0)
            sp.setValue(float(val))
            sp.valueChanged.connect(self._position_changee)
        self.plan = _Plan(self)
        self.etat = QLabel("")
        self.etat.setWordWrap(True)
        auto = QPushButton("Automatique")
        auto.setToolTip("Rendre la main au placement calculé (les vis les "
                        "plus écartées)")
        auto.clicked.connect(self._automatique)
        vider = QPushButton("Aucune vis")
        vider.clicked.connect(self._vider)
        ok = QPushButton("Garder ces vis")
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        annuler = QPushButton("Annuler")
        annuler.clicked.connect(self.reject)
        haut = QHBoxLayout()
        haut.addWidget(QLabel("Centre du brut sur la plaque: X"))
        haut.addWidget(self.pos_x)
        haut.addWidget(QLabel("Y"))
        haut.addWidget(self.pos_y)
        haut.addStretch()
        bas = QHBoxLayout()
        bas.addWidget(self.etat, 1)
        for b in (auto, vider, ok, annuler):
            bas.addWidget(b)
        v = QVBoxLayout(self)
        v.addLayout(haut)
        v.addWidget(QLabel("Clic sur un trou: une vis ou pas. Vert: une vis "
                           "entre par le dos; gris: pas de dos vissable; "
                           "jaune: vis choisie; rouge: choisie mais pas "
                           "vissable."))
        v.addWidget(self.plan, 1)
        v.addLayout(bas)
        self._position_changee()

    # ──── l'état ────

    def position(self):
        return (self.pos_x.value(), self.pos_y.value())

    def decalage_piece(self):
        """Du repère de la pièce à celui de la plaque."""
        x0, y0, _z0, x1, y1, _z1 = self.boite
        px, py = self.position()
        return px - (x0 + x1) / 2, py - (y0 + y1) / 2

    def est_choisi(self, x, y) -> bool:
        return any(abs(x - a) < 1e-3 and abs(y - b) < 1e-3
                   for a, b in self.choisis)

    def _position_changee(self, *_):
        from src.core import tenue as tn
        self.vissables = tn.trous_vissables(self.modele, self.brut,
                                            self.tenue, self.plaque,
                                            self.position())
        self._maj()

    def _maj(self) -> None:
        pris = [t for t in self.choisis if self._vissable(*t)]
        refuses = len(self.choisis) - len(pris)
        self.etat.setText(
            f"{len(pris)} vis — {sum(self.vissables)} trous vissables sous "
            "la pièce" + (f" — {refuses} choisi(s) sans dos vissable (en "
                          "rouge, ignoré(s))" if refuses else ""))
        self.plan.update()

    def _vissable(self, x, y) -> bool:
        for (hx, hy), ok in zip(self.trous, self.vissables):
            if abs(hx - x) < 1e-3 and abs(hy - y) < 1e-3:
                return ok
        return False

    # ──── les gestes ────

    def basculer(self, x, y) -> None:
        if self.est_choisi(x, y):
            self.choisis = [t for t in self.choisis
                            if not (abs(t[0] - x) < 1e-3
                                    and abs(t[1] - y) < 1e-3)]
        else:
            self.choisis.append((x, y))
        self._maj()

    def basculer_pres_de(self, x, y) -> bool:
        """Le trou le plus proche du clic (à 1,5 Ø près)."""
        if not self.trous:
            return False
        d = [np.hypot(hx - x, hy - y) for hx, hy in self.trous]
        k = int(np.argmin(d))
        if d[k] > 1.5 * float(self.plaque.get('diametre_trou', 4.05)) + 2.0:
            return False
        self.basculer(*self.trous[k])
        return True

    def _vider(self) -> None:
        self.choisis = []
        self._maj()

    def _automatique(self) -> None:
        self.automatique = True
        self.accept()

    def placement(self) -> Optional[Dict]:
        """Le placement choisi (tenue.vis_a_la_main), ou None pour
        l'automatique."""
        if self.automatique:
            return None
        from src.core import tenue as tn
        return tn.vis_a_la_main(self.modele, self.brut, self.tenue,
                                self.plaque, self.position(), self.choisis)
