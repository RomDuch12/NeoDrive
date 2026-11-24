"""Simulation 3D d'un parcours d'outil (séquence Datron).

Un simple QPainter, pas d'OpenGL: un parcours d'outil n'est fait que
de segments, la projection se calcule en numpy, et la vue se RENDRE
hors écran — on peut donc vérifier ce qu'elle dessine, pixel par
pixel, au lieu de faire confiance à un widget qui existe.

Souris: glisser (gauche) tourne autour, glisser (milieu/droit) décale,
molette zoome, double-clic remet la vue iso.
"""

import math
from typing import Dict, Optional

import numpy as np
from PySide6.QtCore import Qt, QPointF, QLineF, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QFont
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QSlider, QLabel,
    QCheckBox, QDoubleSpinBox, QSizePolicy)

from src.core import sim3d

#: dégradé de profondeur des coupes: surface -> fond
_DEGRADE = ("#94e2d5", "#a6e3a1", "#f9e2af", "#fab387", "#f38ba8")
_NIVEAUX = 12
_FOND = QColor("#181825")
_GRILLE = QColor("#313244")
_AIR = QColor(166, 173, 200, 110)          # avance hors matière
_RAPIDE = QColor(116, 199, 236, 110)       # comme le canvas 2D


def _teinte(t: float) -> QColor:
    """t = 0 (surface) .. 1 (fond) -> couleur du dégradé."""
    t = max(0.0, min(1.0, t)) * (len(_DEGRADE) - 1)
    i = min(int(t), len(_DEGRADE) - 2)
    f = t - i
    a, b = QColor(_DEGRADE[i]), QColor(_DEGRADE[i + 1])
    return QColor(int(a.red() + (b.red() - a.red()) * f),
                  int(a.green() + (b.green() - a.green()) * f),
                  int(a.blue() + (b.blue() - a.blue()) * f))


class Vue3D(QWidget):
    """La vue elle-même: projection orthographique orbitale."""

    camera_changee = Signal()

    ISO = (-35.0, 30.0)          # (lacet, élévation) en degrés

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        self.setMouseTracking(False)
        self._x = self._y = self._z = np.zeros(0)
        self._k = np.zeros(0, dtype=np.int8)
        self._centre = (0.0, 0.0, 0.0)
        self._etendue = 1.0
        self._z_haut = 0.0
        self._z_bas = -1.0
        self.lacet, self.elevation = self.ISO
        self.zoom = 1.0
        self.decalage = QPointF(0.0, 0.0)
        self.exag = 1.0
        self.rapides = True
        self.curseur = -1                # -1: tout le parcours
        self._glisse = None
        self._bouton = None

    # ──── Données ────

    def set_parcours(self, res: Optional[Dict]) -> None:
        if not res or not res.get('x'):
            self._x = self._y = self._z = np.zeros(0)
            self._k = np.zeros(0, dtype=np.int8)
            self.update()
            return
        self._x = np.asarray(res['x'], dtype=float)
        self._y = np.asarray(res['y'], dtype=float)
        self._z = np.asarray(res['z'], dtype=float)
        self._k = np.asarray(res['k'], dtype=np.int8)
        coupe = self._k == sim3d.COUPE
        # l'échelle des couleurs va de la SURFACE au fond: une sortie
        # de matière (Z > 0) ne doit pas l'étirer
        if coupe.any():
            zc = self._z[coupe]
            self._z_bas = float(zc.min())
            self._z_haut = min(0.0, float(zc.max()))
        else:
            self._z_bas, self._z_haut = float(self._z.min()), 0.0
        # le cadrage suit la matière (les dégagements hauts l'écrasaient)
        ref = coupe if coupe.any() else np.ones_like(coupe)
        xs, ys, zs = self._x[ref], self._y[ref], self._z[ref]
        self._centre = (float((xs.min() + xs.max()) / 2),
                        float((ys.min() + ys.max()) / 2),
                        float((zs.min() + zs.max()) / 2))
        self._etendue = max(float(xs.max() - xs.min()),
                            float(ys.max() - ys.min()), 1e-3)
        self.exag = self.exag_auto()
        self.curseur = -1
        self.update()

    def n_sommets(self) -> int:
        return int(self._x.size)

    def exag_auto(self) -> float:
        """Assez de relief pour lire les passes: la profondeur de
        coupe occupe ~ un quart de l'emprise."""
        dz = max(self._z_haut - self._z_bas, 1e-6)
        return float(max(1.0, min(50.0, round(0.25 * self._etendue
                                               / dz))))

    # ──── Caméra ────

    def vue(self, lacet: float, elevation: float) -> None:
        self.lacet, self.elevation = lacet, elevation
        self.zoom = 1.0
        self.decalage = QPointF(0.0, 0.0)
        self.update()
        self.camera_changee.emit()

    def vue_iso(self):
        self.vue(*self.ISO)

    def vue_dessus(self):
        self.vue(0.0, 90.0)

    def vue_face(self):
        self.vue(0.0, 0.0)

    def etat_camera(self) -> Dict:
        return {'lacet': self.lacet, 'elevation': self.elevation,
                'zoom': self.zoom, 'dx': self.decalage.x(),
                'dy': self.decalage.y(), 'exag': self.exag,
                'rapides': self.rapides}

    def appliquer_camera(self, etat: Optional[Dict]) -> None:
        if not etat:
            return
        self.lacet = float(etat.get('lacet', self.lacet))
        self.elevation = float(etat.get('elevation', self.elevation))
        self.zoom = float(etat.get('zoom', self.zoom))
        self.decalage = QPointF(float(etat.get('dx', 0.0)),
                                float(etat.get('dy', 0.0)))
        self.exag = float(etat.get('exag', self.exag))
        self.rapides = bool(etat.get('rapides', self.rapides))
        self.update()

    # ──── Projection ────

    def _echelle(self) -> float:
        cote = max(1.0, min(self.width(), self.height()) * 0.8)
        return cote / self._etendue * self.zoom

    def _projeter(self, x, y, z):
        cx, cy, cz = self._centre
        X = x - cx
        Y = y - cy
        Z = (z - cz) * self.exag
        a = math.radians(self.lacet)
        e = math.radians(self.elevation)
        x1 = X * math.cos(a) - Y * math.sin(a)
        y1 = X * math.sin(a) + Y * math.cos(a)
        haut = Z * math.cos(e) + y1 * math.sin(e)
        s = self._echelle()
        px = self.width() / 2.0 + self.decalage.x() + x1 * s
        py = self.height() / 2.0 + self.decalage.y() - haut * s
        return px, py

    # ──── Dessin ────

    def paintEvent(self, _event):
        p = QPainter(self)
        p.fillRect(self.rect(), _FOND)
        n = self._x.size
        if n < 2:
            p.setPen(QColor("#6c7086"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "Aucun parcours à simuler")
            p.end()
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing,
                        self._glisse is None)
        px, py = self._projeter(self._x, self._y, self._z)
        self._dessiner_surface(p)

        # un segment i relie le sommet i-1 au sommet i, de genre k[i]
        ax, ay = px[:-1], py[:-1]
        bx, by = px[1:], py[1:]
        genres = self._k[1:]
        fait = (np.arange(1, n) <= self.curseur) if self.curseur >= 0 \
            else np.ones(n - 1, dtype=bool)
        pas = 4 if (self._glisse is not None and n > 20000) else 1
        garde = np.zeros(n - 1, dtype=bool)
        garde[::pas] = True

        def _tracer(masque, stylo):
            idx = np.nonzero(masque & garde)[0]
            if idx.size == 0:
                return
            p.setPen(stylo)
            lx, ly = ax[idx].tolist(), ay[idx].tolist()
            mx, my = bx[idx].tolist(), by[idx].tolist()
            p.drawLines([QLineF(a, b, c, d)
                         for a, b, c, d in zip(lx, ly, mx, my)])

        if self.rapides:
            stylo = QPen(_RAPIDE, 1.0, Qt.PenStyle.DashLine)
            _tracer(genres == sim3d.RAPIDE, stylo)
        _tracer(genres == sim3d.AIR, QPen(_AIR, 1.0))

        # coupes: une teinte par tranche de profondeur (le bout le plus
        # profond du segment décide)
        coupe = genres == sim3d.COUPE
        if coupe.any():
            zseg = np.minimum(self._z[:-1], self._z[1:])
            plage = max(self._z_haut - self._z_bas, 1e-9)
            t = np.clip((self._z_haut - zseg) / plage, 0.0, 1.0)
            tranche = np.minimum((t * _NIVEAUX).astype(int), _NIVEAUX - 1)
            for b in range(_NIVEAUX):
                couleur = _teinte((b + 0.5) / _NIVEAUX)
                _tracer(coupe & (tranche == b) & fait, QPen(couleur, 1.4))
                reste = QColor(couleur)
                reste.setAlpha(45)
                _tracer(coupe & (tranche == b) & ~fait, QPen(reste, 1.0))

        if self.curseur >= 0:
            self._dessiner_outil(p, px, py)
        self._dessiner_triedre(p)
        p.end()

    def _dessiner_surface(self, p: QPainter) -> None:
        """Le rectangle de la surface (Z = 0) sous le parcours:
        on sait où est le haut de la pièce."""
        if self._x.size == 0:
            return
        xs = [float(self._x.min()), float(self._x.max())]
        ys = [float(self._y.min()), float(self._y.max())]
        coins = [(xs[0], ys[0]), (xs[1], ys[0]), (xs[1], ys[1]),
                 (xs[0], ys[1])]
        pts = [self._projeter(np.array([cx]), np.array([cy]),
                              np.array([0.0])) for cx, cy in coins]
        p.setPen(QPen(_GRILLE, 1.0))
        for i in range(4):
            a, b = pts[i], pts[(i + 1) % 4]
            p.drawLine(QLineF(float(a[0][0]), float(a[1][0]),
                              float(b[0][0]), float(b[1][0])))

    def _dessiner_outil(self, p: QPainter, px, py) -> None:
        i = max(0, min(self.curseur, self._x.size - 1))
        x0, y0 = float(px[i]), float(py[i])
        # l'axe de l'outil: vers +Z projeté
        hx, hy = self._projeter(np.array([self._x[i]]),
                                np.array([self._y[i]]),
                                np.array([self._z[i]
                                          + 0.25 * self._etendue
                                          / max(self.exag, 1e-6)]))
        p.setPen(QPen(QColor("#cdd6f4"), 2.0))
        p.drawLine(QLineF(x0, y0, float(hx[0]), float(hy[0])))
        p.setBrush(QColor("#f9e2af"))
        p.drawEllipse(QPointF(x0, y0), 4.0, 4.0)
        p.setBrush(Qt.BrushStyle.NoBrush)

    def _dessiner_triedre(self, p: QPainter) -> None:
        """X rouge, Y vert, Z bleu, en bas à gauche."""
        o = QPointF(28.0, self.height() - 26.0)
        a = math.radians(self.lacet)
        e = math.radians(self.elevation)
        axes = (((1, 0, 0), "#f38ba8", "X"), ((0, 1, 0), "#a6e3a1", "Y"),
                ((0, 0, 1), "#89b4fa", "Z"))
        f = QFont()
        f.setPointSize(7)
        p.setFont(f)
        for (X, Y, Z), couleur, nom in axes:
            x1 = X * math.cos(a) - Y * math.sin(a)
            y1 = X * math.sin(a) + Y * math.cos(a)
            haut = Z * math.cos(e) + y1 * math.sin(e)
            fin = QPointF(o.x() + x1 * 18, o.y() - haut * 18)
            p.setPen(QPen(QColor(couleur), 1.6))
            p.drawLine(o, fin)
            p.drawText(QPointF(fin.x() + 2, fin.y() + 3), nom)

    # ──── Souris ────

    def mousePressEvent(self, ev):
        self._glisse = ev.position()
        self._bouton = ev.button()

    def mouseMoveEvent(self, ev):
        if self._glisse is None:
            return
        d = ev.position() - self._glisse
        self._glisse = ev.position()
        if self._bouton == Qt.MouseButton.LeftButton:
            self.lacet = (self.lacet + d.x() * 0.5) % 360.0
            self.elevation = max(-90.0, min(90.0,
                                            self.elevation + d.y() * 0.5))
        else:
            self.decalage = self.decalage + d
        self.update()

    def mouseReleaseEvent(self, _ev):
        self._glisse = None
        self._bouton = None
        self.update()
        self.camera_changee.emit()

    def mouseDoubleClickEvent(self, _ev):
        self.vue_iso()

    def wheelEvent(self, ev):
        facteur = 1.15 if ev.angleDelta().y() > 0 else 1 / 1.15
        self.zoom = max(0.05, min(80.0, self.zoom * facteur))
        self.update()
        self.camera_changee.emit()


class Simulation3D(QWidget):
    """La vue et ses commandes: lecture, curseur, relief Z, vues."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.vue = Vue3D(self)
        self._res: Optional[Dict] = None

        self.lecture = QPushButton("▶")
        self.lecture.setFixedWidth(32)
        self.lecture.setToolTip("Lire le parcours (l'outil avance)")
        self.lecture.clicked.connect(self._basculer_lecture)
        self.curseur = QSlider(Qt.Orientation.Horizontal)
        self.curseur.setToolTip("Avancement de l'outil le long du "
                                "parcours")
        self.curseur.valueChanged.connect(self._sur_curseur)

        self.exag = QDoubleSpinBox()
        self.exag.setRange(1.0, 50.0)
        self.exag.setDecimals(0)
        self.exag.setPrefix("Z ×")
        self.exag.setToolTip("Exagération du relief: les passes d'une "
                             "gravure font quelques dixièmes, à "
                             "l'échelle elles se confondent")
        self.exag.valueChanged.connect(self._sur_exag)
        self.cb_rapides = QCheckBox("Rapides")
        self.cb_rapides.setChecked(True)
        self.cb_rapides.toggled.connect(self._sur_rapides)
        boutons = []
        for texte, action, bulle in (
                ("Iso", self.vue.vue_iso, "Vue isométrique"),
                ("Dessus", self.vue.vue_dessus, "Vue de dessus"),
                ("Face", self.vue.vue_face, "Vue de face")):
            b = QPushButton(texte)
            b.setToolTip(bulle)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(action)
            boutons.append(b)
        self.info = QLabel("")
        self.info.setStyleSheet("color: #a6adc8; font-size: 10px;")
        self.info.setWordWrap(True)

        # trois rangées courtes: le panneau du formulaire est étroit,
        # une seule rangée l'élargissait
        l1 = QHBoxLayout()
        l1.setContentsMargins(0, 0, 0, 0)
        l1.addWidget(self.lecture)
        l1.addWidget(self.curseur, 1)
        l2 = QHBoxLayout()
        l2.setContentsMargins(0, 0, 0, 0)
        l2.addWidget(self.exag)
        l2.addWidget(self.cb_rapides)
        l2.addStretch()
        l3 = QHBoxLayout()
        l3.setContentsMargins(0, 0, 0, 0)
        for b in boutons:
            l3.addWidget(b, 1)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(3)
        v.addWidget(self.vue, 1)
        v.addLayout(l1)
        v.addLayout(l2)
        v.addLayout(l3)
        v.addWidget(self.info)

        self._minuterie = QTimer(self)
        self._minuterie.setInterval(30)
        self._minuterie.timeout.connect(self._avancer)

    def set_parcours(self, res: Optional[Dict]) -> None:
        self._res = res
        self.vue.set_parcours(res)
        n = self.vue.n_sommets()
        self.curseur.blockSignals(True)
        self.curseur.setRange(0, max(0, n - 1))
        self.curseur.setValue(max(0, n - 1))
        self.curseur.blockSignals(False)
        self.exag.blockSignals(True)
        self.exag.setValue(self.vue.exag)
        self.exag.blockSignals(False)
        self.info.setText(self._resume(res))

    @staticmethod
    def _resume(res: Optional[Dict]) -> str:
        if not res or not res.get('x'):
            return "Aucun parcours dans cette séquence."
        coupe_z = {round(z, 3) for z, k in zip(res['z'], res['k'])
                   if k == sim3d.COUPE and z <= 0.0}
        passes = (f"{len(coupe_z)} passe(s)" if 0 < len(coupe_z) <= 12
                  else "profil 3D" if coupe_z else "pas de coupe")
        txt = (f"{res['n_moves']} mouvements · {passes} · coupe "
               f"{res['longueur_coupe']:.0f} mm")
        if res.get('pas', 1) > 1:
            txt += f" · aperçu allégé (1 mouvement sur {res['pas']})"
        return txt

    def _sur_curseur(self, v: int) -> None:
        n = self.vue.n_sommets()
        self.vue.curseur = -1 if v >= n - 1 else v
        self.vue.update()

    def _sur_exag(self, v: float) -> None:
        self.vue.exag = float(v)
        self.vue.update()

    def _sur_rapides(self, on: bool) -> None:
        self.vue.rapides = bool(on)
        self.vue.update()

    def _basculer_lecture(self) -> None:
        if self._minuterie.isActive():
            self._minuterie.stop()
            self.lecture.setText("▶")
            return
        if self.curseur.value() >= self.curseur.maximum():
            self.curseur.setValue(0)
        self.lecture.setText("⏸")
        self._minuterie.start()

    def _avancer(self) -> None:
        n = max(1, self.curseur.maximum())
        pas = max(1, n // 400)            # ~12 s pour tout le parcours
        v = self.curseur.value() + pas
        if v >= self.curseur.maximum():
            self.curseur.setValue(self.curseur.maximum())
            self._minuterie.stop()
            self.lecture.setText("▶")
            return
        self.curseur.setValue(v)
