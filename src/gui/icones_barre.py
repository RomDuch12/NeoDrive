"""Les icônes des barres d'outils des canvas (2D et 3D).

Les boutons des barres n'ont plus que leur icône (le libellé passe
dans la ligne d'état au survol): chaque outil a la sienne, dessinée
au QPainter comme celles de `icons.py`, aux couleurs du thème. Elles
rejoignent le registre de `icons` (nom « b_… »): `get_icon` les sert
et les garde en cache.

Les dessins sont décrits en coordonnées unitaires (0 à 1 sur le côté
de l'icône); l'épaisseur des traits suit la taille.
"""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPen, QBrush

from src.gui import icons as _icons

_TEINTES = {'t': 'text', 'a': 'accent', 'v': 'green', 'r': 'red',
            'o': 'orange', 'j': 'yellow', 'b': 'blue', 'p': 'purple',
            'd': 'text_dim', 'c': 'teal'}


class _Crayon:
    """Un QPainter en coordonnées unitaires."""

    def __init__(self, p, s):
        self.p = p
        self.s = float(s)
        self.c = _icons._colors()

    def couleur(self, c, alpha=255):
        q = QColor(self.c.get(_TEINTES.get(c, c), c))
        q.setAlpha(alpha)
        return q

    def _stylo(self, c, w, tiret=False):
        pen = QPen(self.couleur(c), max(1.0, w * self.s / 18.0))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        if tiret:
            pen.setDashPattern([2.0, 1.8])
        return pen

    def _poser(self, c, w, fond, alpha, tiret):
        self.p.setPen(self._stylo(c, w, tiret) if c else Qt.PenStyle.NoPen)
        if fond:
            self.p.setBrush(QBrush(self.couleur(fond, alpha)))
        else:
            self.p.setBrush(Qt.BrushStyle.NoBrush)

    def P(self, x, y):
        return QPointF(x * self.s, y * self.s)

    def chemin(self, pts, ferme=False):
        ch = QPainterPath(self.P(*pts[0]))
        for pt in pts[1:]:
            ch.lineTo(self.P(*pt))
        if ferme:
            ch.closeSubpath()
        return ch

    def trait(self, *pts, c='t', w=1.5, tiret=False, ferme=False,
              fond=None, alpha=255):
        self._poser(c, w, fond, alpha, tiret)
        self.p.drawPath(self.chemin(pts, ferme))

    def tracer(self, chemin, c='t', w=1.5, fond=None, alpha=255,
               tiret=False):
        self._poser(c, w, fond, alpha, tiret)
        self.p.drawPath(chemin)

    def cercle(self, x, y, r, c='t', w=1.5, fond=None, alpha=255,
               tiret=False):
        self._poser(c, w, fond, alpha, tiret)
        self.p.drawEllipse(self.P(x, y), r * self.s, r * self.s)

    def rect(self, x, y, l, h, c='t', w=1.5, fond=None, alpha=255,
             rayon=0.0, tiret=False):
        self._poser(c, w, fond, alpha, tiret)
        r = QRectF(x * self.s, y * self.s, l * self.s, h * self.s)
        if rayon:
            self.p.drawRoundedRect(r, rayon * self.s, rayon * self.s)
        else:
            self.p.drawRect(r)

    def arc(self, x, y, r, debut, etendue, c='t', w=1.5, tiret=False):
        """Un arc (degrés, sens trigonométrique, 0 = 3 h)."""
        self._poser(c, w, None, 255, tiret)
        rr = QRectF((x - r) * self.s, (y - r) * self.s, 2 * r * self.s,
                    2 * r * self.s)
        self.p.drawArc(rr, int(debut * 16), int(etendue * 16))

    def point(self, x, y, r=0.07, c='a'):
        self._poser(None, 0, c, 255, False)
        self.p.drawEllipse(self.P(x, y), r * self.s, r * self.s)

    def fleche(self, x1, y1, x2, y2, c='t', w=1.5, tete=0.16):
        self.trait((x1, y1), (x2, y2), c=c, w=w)
        a = math.atan2(y2 - y1, x2 - x1)
        g = (x2 - tete * math.cos(a - 0.5), y2 - tete * math.sin(a - 0.5))
        d = (x2 - tete * math.cos(a + 0.5), y2 - tete * math.sin(a + 0.5))
        self.trait(g, (x2, y2), d, c=c, w=w)

    def cube(self, x=0.18, y=0.3, l=0.46, prof=0.2, c='t', w=1.4,
             faces=None, tiret_cache=False):
        """Un cube en perspective cavalière: face avant (x, y, l, l),
        décalage (prof, -prof). `faces`: teintes (avant, dessus, côté)."""
        av = [(x, y), (x + l, y), (x + l, y + l), (x, y + l)]
        de = [(x, y), (x + prof, y - prof), (x + l + prof, y - prof),
              (x + l, y)]
        co = [(x + l, y), (x + l + prof, y - prof),
              (x + l + prof, y + l - prof), (x + l, y + l)]
        if faces:
            for pts, teinte in zip((av, de, co), faces):
                if teinte:
                    self.trait(*pts, c=None, ferme=True, fond=teinte[0],
                               alpha=teinte[1])
        for pts in (av, de, co):
            self.trait(*pts, c=c, w=w, ferme=True)
        if tiret_cache:
            # les arêtes cachées (le coin arrière bas)
            cx, cy = x + prof, y + l - prof
            self.trait((cx, y - prof), (cx, cy), c=c, w=1.0, tiret=True)
            self.trait((x, y + l), (cx, cy), c=c, w=1.0, tiret=True)
            self.trait((cx, cy), (x + l + prof, cy), c=c, w=1.0, tiret=True)


def _icone(fonction):
    """La fonction de dessin devient une icône du registre (« b_<nom> »)."""
    nom = "b_" + fonction.__name__.lstrip('_')

    def fabrique(size=24):
        return _icons._make_icon(lambda p, s: fonction(_Crayon(p, s)), size)
    _icons._ICON_REGISTRY[nom] = fabrique
    return fonction


# ══════════════ Canva 2D: le fichier, l'affichage ══════════════

@_icone
def _vider(k):
    k.rect(0.16, 0.16, 0.68, 0.68, c='d', w=1.3, rayon=0.08)
    k.trait((0.32, 0.32), (0.68, 0.68), c='r', w=1.9)
    k.trait((0.68, 0.32), (0.32, 0.68), c='r', w=1.9)


@_icone
def _imprimer(k):
    k.rect(0.3, 0.14, 0.4, 0.22, c='t', w=1.3)
    k.rect(0.14, 0.36, 0.72, 0.32, c='t', w=1.5, rayon=0.06)
    k.rect(0.3, 0.56, 0.4, 0.3, c='t', w=1.3, fond='bg', alpha=255)
    k.trait((0.37, 0.66), (0.63, 0.66), c='d', w=1.0)
    k.trait((0.37, 0.76), (0.57, 0.76), c='d', w=1.0)
    k.point(0.74, 0.46, 0.04, 'v')


@_icone
def _effacer(k):
    k.trait((0.2, 0.62), (0.5, 0.32), (0.76, 0.56), (0.46, 0.86),
            ferme=True, c='t', w=1.4)
    k.trait((0.2, 0.62), (0.35, 0.47), (0.61, 0.71), (0.46, 0.86),
            ferme=True, c='r', w=1.4, fond='r', alpha=150)
    k.trait((0.5, 0.86), (0.86, 0.86), c='d', w=1.2)


@_icone
def _nettoyer(k):
    # un balai: le manche, la ligature, les brins
    k.trait((0.78, 0.14), (0.5, 0.48), c='o', w=1.8)
    k.trait((0.42, 0.42), (0.6, 0.56), c='t', w=1.8)
    k.trait((0.42, 0.42), (0.18, 0.72), (0.34, 0.86), (0.6, 0.56),
            ferme=True, c='t', w=1.3, fond='j', alpha=170)
    k.trait((0.3, 0.62), (0.24, 0.76), c='t', w=1.0)
    k.trait((0.4, 0.66), (0.33, 0.8), c='t', w=1.0)
    k.point(0.78, 0.6, 0.035, 'a')
    k.point(0.68, 0.78, 0.03, 'a')


@_icone
def _etiquettes(k):
    k.trait((0.14, 0.32), (0.56, 0.32), (0.86, 0.5), (0.56, 0.68),
            (0.14, 0.68), ferme=True, c='t', w=1.4)
    k.cercle(0.62, 0.5, 0.05, c='t', w=1.1)
    k.trait((0.26, 0.44), (0.3, 0.41), (0.3, 0.6), c='a', w=1.4)
    k.trait((0.38, 0.44), (0.48, 0.44), c='a', w=1.2)
    k.trait((0.38, 0.56), (0.48, 0.56), c='a', w=1.2)


@_icone
def _legende(k):
    for i, teinte in enumerate(('a', 'v', 'o')):
        y = 0.24 + i * 0.26
        k.rect(0.16, y - 0.07, 0.14, 0.14, c=None, fond=teinte)
        k.trait((0.4, y), (0.84, y), c='t', w=1.4)


@_icone
def _vers_points(k):
    k.fleche(0.12, 0.5, 0.5, 0.5, c='t', w=1.5, tete=0.14)
    for x, y in ((0.66, 0.26), (0.8, 0.5), (0.66, 0.74)):
        k.cercle(x, y, 0.07, c='a', w=1.3)
        k.point(x, y, 0.025, 'a')


# ══════════════ Canva 2D: dessiner ══════════════

@_icone
def _grille(k):
    for i in range(4):
        v = 0.17 + i * 0.22
        k.trait((v, 0.17), (v, 0.83), c='t', w=1.1)
        k.trait((0.17, v), (0.83, v), c='t', w=1.1)
    k.point(0.39, 0.61, 0.065, 'a')


@_icone
def _ortho(k):
    k.trait((0.22, 0.14), (0.22, 0.8), (0.86, 0.8), c='t', w=1.6)
    k.rect(0.22, 0.62, 0.18, 0.18, c='a', w=1.2)
    k.fleche(0.22, 0.8, 0.62, 0.4, c='o', w=1.3, tete=0.13)


@_icone
def _ligne(k):
    k.trait((0.22, 0.78), (0.78, 0.22), c='t', w=1.6)
    k.rect(0.14, 0.7, 0.16, 0.16, c='a', w=1.2)
    k.rect(0.7, 0.14, 0.16, 0.16, c='a', w=1.2)


@_icone
def _cercle(k):
    k.cercle(0.5, 0.5, 0.34, c='t', w=1.6)
    k.trait((0.5, 0.5), (0.74, 0.26), c='d', w=1.0, tiret=True)
    k.point(0.5, 0.5, 0.06, 'a')


@_icone
def _rectangle(k):
    k.rect(0.16, 0.26, 0.68, 0.48, c='t', w=1.6)
    for x, y in ((0.16, 0.26), (0.84, 0.74)):
        k.point(x, y, 0.07, 'a')


@_icone
def _polyligne(k):
    pts = ((0.14, 0.76), (0.34, 0.3), (0.6, 0.62), (0.86, 0.22))
    k.trait(*pts, c='t', w=1.6)
    for x, y in pts:
        k.rect(x - 0.06, y - 0.06, 0.12, 0.12, c='a', w=1.1, fond='bg')


@_icone
def _texte(k):
    k.trait((0.2, 0.2), (0.8, 0.2), c='t', w=1.9)
    k.trait((0.5, 0.2), (0.5, 0.82), c='t', w=1.9)
    k.trait((0.38, 0.82), (0.62, 0.82), c='t', w=1.4)
    k.trait((0.2, 0.2), (0.2, 0.3), c='t', w=1.4)
    k.trait((0.8, 0.2), (0.8, 0.3), c='t', w=1.4)
    k.trait((0.74, 0.5), (0.74, 0.86), c='a', w=1.2)


@_icone
def _contraintes(k):
    # ⊥ et ∥: le dessin tenu par ses relations
    k.trait((0.14, 0.82), (0.56, 0.82), c='t', w=1.5)
    k.trait((0.35, 0.82), (0.35, 0.4), c='t', w=1.5)
    k.rect(0.35, 0.68, 0.12, 0.14, c='a', w=1.1)
    k.trait((0.62, 0.62), (0.78, 0.16), c='o', w=1.5)
    k.trait((0.74, 0.7), (0.9, 0.24), c='o', w=1.5)


# ══════════════ Canva 2D: retoucher ══════════════

@_icone
def _decaler(k):
    k.rect(0.3, 0.3, 0.4, 0.4, c='t', w=1.4, rayon=0.04)
    k.rect(0.14, 0.14, 0.72, 0.72, c='a', w=1.3, rayon=0.16, tiret=True)


@_icone
def _conge(k):
    k.trait((0.2, 0.86), (0.2, 0.5), c='t', w=1.6)
    k.arc(0.5, 0.5, 0.3, 90, 90, c='a', w=1.8)
    k.trait((0.5, 0.2), (0.86, 0.2), c='t', w=1.6)
    k.trait((0.2, 0.5), (0.2, 0.2), (0.5, 0.2), c='d', w=1.0, tiret=True)


@_icone
def _chanfrein(k):
    k.trait((0.2, 0.86), (0.2, 0.48), c='t', w=1.6)
    k.trait((0.2, 0.48), (0.48, 0.2), c='a', w=1.8)
    k.trait((0.48, 0.2), (0.86, 0.2), c='t', w=1.6)
    k.trait((0.2, 0.48), (0.2, 0.2), (0.48, 0.2), c='d', w=1.0, tiret=True)


@_icone
def _arcs(k):
    k.trait((0.12, 0.62), (0.26, 0.38), (0.42, 0.3), (0.58, 0.3),
            (0.74, 0.38), (0.88, 0.62), c='d', w=1.1, tiret=True)
    k.arc(0.5, 0.86, 0.42, 25, 130, c='a', w=1.8)
    for x, y in ((0.12, 0.62), (0.88, 0.62)):
        k.point(x, y, 0.05, 't')


@_icone
def _formes(k):
    k.cercle(0.32, 0.32, 0.17, c='a', w=1.4)
    k.rect(0.54, 0.16, 0.3, 0.3, c='v', w=1.4)
    k.trait((0.5, 0.56), (0.76, 0.86), (0.24, 0.86), ferme=True, c='o',
            w=1.4)


@_icone
def _couper(k):
    k.cercle(0.28, 0.74, 0.12, c='t', w=1.4)
    k.cercle(0.72, 0.74, 0.12, c='t', w=1.4)
    k.trait((0.36, 0.65), (0.76, 0.16), c='t', w=1.5)
    k.trait((0.64, 0.65), (0.24, 0.16), c='t', w=1.5)
    k.point(0.5, 0.48, 0.045, 'r')


@_icone
def _depart(k):
    k.arc(0.5, 0.52, 0.32, 120, 300, c='t', w=1.5)
    k.fleche(0.34, 0.25, 0.42, 0.21, c='t', w=1.4, tete=0.12)
    k.point(0.34, 0.25, 0.08, 'v')
    k.trait((0.34, 0.25), (0.34, 0.06), c='v', w=1.3)
    k.trait((0.34, 0.06), (0.5, 0.11), (0.34, 0.16), ferme=True, c='v',
            w=1.0, fond='v')


@_icone
def _ajuster(k):
    k.trait((0.5, 0.12), (0.5, 0.88), c='t', w=1.5)
    k.trait((0.12, 0.5), (0.5, 0.5), c='t', w=1.6)
    k.trait((0.5, 0.5), (0.88, 0.5), c='r', w=1.4, tiret=True)
    k.trait((0.66, 0.38), (0.78, 0.62), c='r', w=1.4)
    k.trait((0.78, 0.38), (0.66, 0.62), c='r', w=1.4)


@_icone
def _prolonger(k):
    k.trait((0.84, 0.12), (0.84, 0.88), c='t', w=1.6)
    k.trait((0.12, 0.5), (0.44, 0.5), c='t', w=1.6)
    k.fleche(0.48, 0.5, 0.8, 0.5, c='a', w=1.4, tete=0.14)


@_icone
def _region(k):
    zone = k.chemin(((0.14, 0.3), (0.62, 0.14), (0.86, 0.5), (0.5, 0.86),
                     (0.18, 0.7)), ferme=True)
    k.tracer(zone, c=None, fond='a', alpha=80)
    k.p.save()
    k.p.setClipPath(zone)
    for i in range(6):
        x = 0.02 + i * 0.16
        k.trait((x, 0.9), (x + 0.4, 0.1), c='a', w=1.0)
    k.p.restore()
    k.tracer(zone, c='t', w=1.4)
    k.trait((0.56, 0.46), (0.56, 0.86), (0.66, 0.76), (0.76, 0.9),
            c='t', w=1.2)


@_icone
def _points(k):
    k.arc(0.5, 0.95, 0.62, 30, 120, c='d', w=1.2)
    for a in (40, 70, 100, 130):
        r = math.radians(a)
        k.cercle(0.5 + 0.62 * math.cos(r), 0.95 - 0.62 * math.sin(r),
                 0.065, c='a', w=1.3)


@_icone
def _reseau_rect(k):
    for i in range(3):
        for j in range(2):
            k.rect(0.12 + i * 0.27, 0.24 + j * 0.3, 0.2, 0.2,
                   c='a' if (i, j) == (0, 0) else 't', w=1.3)


@_icone
def _reseau_polaire(k):
    k.cercle(0.5, 0.5, 0.3, c='d', w=1.0, tiret=True)
    for i in range(6):
        a = math.radians(90 + i * 60)
        k.cercle(0.5 + 0.3 * math.cos(a), 0.5 - 0.3 * math.sin(a), 0.08,
                 c='a' if i == 0 else 't', w=1.3)
    k.point(0.5, 0.5, 0.04, 't')


@_icone
def _mesurer(k):
    k.trait((0.16, 0.86), (0.16, 0.5), c='d', w=1.0)
    k.trait((0.84, 0.86), (0.84, 0.5), c='d', w=1.0)
    k.fleche(0.5, 0.62, 0.17, 0.62, c='a', w=1.3, tete=0.12)
    k.fleche(0.5, 0.62, 0.83, 0.62, c='a', w=1.3, tete=0.12)
    # Σ: la longueur totale de la sélection
    k.trait((0.64, 0.14), (0.36, 0.14), (0.52, 0.29), (0.36, 0.44),
            (0.64, 0.44), c='t', w=1.4)


def _deux_disques(k):
    a = QPainterPath()
    a.addEllipse(k.P(0.38, 0.5), 0.26 * k.s, 0.26 * k.s)
    b = QPainterPath()
    b.addEllipse(k.P(0.62, 0.5), 0.26 * k.s, 0.26 * k.s)
    return a, b


@_icone
def _unir(k):
    a, b = _deux_disques(k)
    k.tracer(a.united(b), c='t', w=1.4, fond='a', alpha=170)


@_icone
def _soustraire(k):
    a, b = _deux_disques(k)
    k.tracer(a.subtracted(b), c='t', w=1.4, fond='a', alpha=170)
    k.tracer(b, c='d', w=1.0, tiret=True)


@_icone
def _intersection(k):
    a, b = _deux_disques(k)
    k.tracer(a, c='d', w=1.0)
    k.tracer(b, c='d', w=1.0)
    k.tracer(a.intersected(b), c='t', w=1.4, fond='a', alpha=190)


@_icone
def _exclure(k):
    a, b = _deux_disques(k)
    ou = a.united(b).subtracted(a.intersected(b))
    k.tracer(ou, c=None, fond='a', alpha=170)
    k.tracer(a, c='t', w=1.3)
    k.tracer(b, c='t', w=1.3)


@_icone
def _image(k):
    k.rect(0.12, 0.2, 0.76, 0.6, c='t', w=1.4, rayon=0.05)
    k.trait((0.16, 0.76), (0.4, 0.46), (0.56, 0.64), (0.66, 0.54),
            (0.84, 0.76), ferme=True, c='v', w=1.1, fond='v', alpha=150)
    k.cercle(0.68, 0.36, 0.07, c='j', w=1.1, fond='j')


# ══════════════ Canva 2D: annoter, grouper, placer ══════════════

@_icone
def _cote_selection(k):
    k.rect(0.2, 0.38, 0.6, 0.44, c='t', w=1.4)
    k.fleche(0.5, 0.2, 0.22, 0.2, c='a', w=1.2, tete=0.1)
    k.fleche(0.5, 0.2, 0.78, 0.2, c='a', w=1.2, tete=0.1)
    k.trait((0.2, 0.12), (0.2, 0.3), c='d', w=1.0)
    k.trait((0.8, 0.12), (0.8, 0.3), c='d', w=1.0)


@_icone
def _cotes(k):
    k.trait((0.14, 0.86), (0.14, 0.36), c='d', w=1.0)
    k.trait((0.86, 0.86), (0.86, 0.36), c='d', w=1.0)
    k.fleche(0.5, 0.5, 0.15, 0.5, c='t', w=1.3, tete=0.12)
    k.fleche(0.5, 0.5, 0.85, 0.5, c='t', w=1.3, tete=0.12)
    # le chiffre de la cote: deux petits traits au-dessus
    k.trait((0.36, 0.3), (0.46, 0.3), c='a', w=1.6)
    k.trait((0.54, 0.3), (0.64, 0.3), c='a', w=1.6)


@_icone
def _marqueurs(k):
    for x, y in ((0.32, 0.34), (0.7, 0.66)):
        k.cercle(x, y, 0.15, c='#f5c2e7', w=1.3)
        k.trait((x - 0.22, y), (x + 0.22, y), c='#f5c2e7', w=1.0)
        k.trait((x, y - 0.22), (x, y + 0.22), c='#f5c2e7', w=1.0)


@_icone
def _cube(k):
    k.cube(0.16, 0.34, 0.48, 0.2, c='t', w=1.4,
           faces=(('a', 70), ('a', 140), ('a', 40)))


@_icone
def _centrer_import(k):
    k.cercle(0.5, 0.5, 0.18, c='a', w=1.3)
    k.trait((0.5, 0.36), (0.5, 0.64), c='a', w=1.0)
    k.trait((0.36, 0.5), (0.64, 0.5), c='a', w=1.0)
    k.fleche(0.1, 0.1, 0.34, 0.34, c='t', w=1.4, tete=0.13)
    k.fleche(0.9, 0.9, 0.66, 0.66, c='t', w=1.4, tete=0.13)


@_icone
def _grouper(k):
    k.rect(0.1, 0.1, 0.8, 0.8, c='a', w=1.2, rayon=0.06, tiret=True)
    k.cercle(0.36, 0.38, 0.13, c='t', w=1.4)
    k.rect(0.48, 0.5, 0.26, 0.24, c='t', w=1.4)


@_icone
def _degrouper(k):
    k.rect(0.08, 0.12, 0.42, 0.42, c='d', w=1.0, rayon=0.05, tiret=True)
    k.rect(0.5, 0.46, 0.42, 0.42, c='d', w=1.0, rayon=0.05, tiret=True)
    k.cercle(0.29, 0.33, 0.12, c='t', w=1.4)
    k.rect(0.6, 0.56, 0.22, 0.22, c='t', w=1.4)


@_icone
def _miroir_h(k):
    k.trait((0.5, 0.1), (0.5, 0.9), c='d', w=1.1, tiret=True)
    k.trait((0.42, 0.24), (0.42, 0.76), (0.12, 0.76), ferme=True, c='t',
            w=1.3, fond='a', alpha=170)
    k.trait((0.58, 0.24), (0.58, 0.76), (0.88, 0.76), ferme=True, c='t',
            w=1.3)


@_icone
def _miroir_v(k):
    k.trait((0.1, 0.5), (0.9, 0.5), c='d', w=1.1, tiret=True)
    k.trait((0.24, 0.42), (0.76, 0.42), (0.76, 0.12), ferme=True, c='t',
            w=1.3, fond='a', alpha=170)
    k.trait((0.24, 0.58), (0.76, 0.58), (0.76, 0.88), ferme=True, c='t',
            w=1.3)


@_icone
def _noms(k):
    # une icône et son nom dessous: la barre dépliée
    k.rect(0.3, 0.1, 0.4, 0.4, c='t', w=1.3, rayon=0.06)
    k.point(0.5, 0.3, 0.07, 'a')
    k.trait((0.2, 0.66), (0.8, 0.66), c='a', w=1.6)
    k.trait((0.3, 0.84), (0.7, 0.84), c='d', w=1.4)


@_icone
def _placer(k):
    k.rect(0.32, 0.32, 0.36, 0.36, c='d', w=1.1, rayon=0.04)
    k.fleche(0.5, 0.26, 0.5, 0.06, c='t', w=1.3, tete=0.1)
    k.fleche(0.5, 0.74, 0.5, 0.94, c='t', w=1.3, tete=0.1)
    k.fleche(0.26, 0.5, 0.06, 0.5, c='t', w=1.3, tete=0.1)
    k.fleche(0.74, 0.5, 0.94, 0.5, c='t', w=1.3, tete=0.1)


# ══════════════ Canva 3D ══════════════

@_icone
def _retour_2d(k):
    k.trait((0.42, 0.34), (0.9, 0.34), (0.78, 0.78), (0.3, 0.78),
            ferme=True, c='t', w=1.3, fond='a', alpha=60)
    k.fleche(0.5, 0.18, 0.08, 0.18, c='a', w=1.5, tete=0.13)


@_icone
def _piece(k):
    k.cube(0.16, 0.34, 0.48, 0.2, c='t', w=1.3,
           faces=(('b', 150), ('b', 220), ('b', 90)))


@_icone
def _aretes(k):
    k.cube(0.16, 0.34, 0.48, 0.2, c='a', w=1.5)


@_icone
def _ops3d(k):
    k.trait((0.1, 0.42), (0.6, 0.42), (0.9, 0.22), (0.4, 0.22), ferme=True,
            c='t', w=1.2)
    for x in (0.36, 0.62):
        k.cercle(x, 0.32, 0.06, c='a', w=1.2)
        k.trait((x, 0.38), (x, 0.82), c='a', w=1.2, tiret=True)
        k.point(x, 0.84, 0.05, 'a')


@_icone
def _parcours(k):
    k.trait((0.14, 0.2), (0.86, 0.2), (0.86, 0.4), (0.14, 0.4),
            (0.14, 0.6), (0.86, 0.6), (0.86, 0.8), (0.5, 0.8), c='o', w=1.4)
    k.point(0.5, 0.8, 0.07, 't')


@_icone
def _matiere(k):
    k.cube(0.12, 0.4, 0.52, 0.22, c='t', w=1.2,
           faces=(('o', 120), ('o', 170), ('o', 80)))
    k.trait((0.3, 0.29), (0.5, 0.29), (0.42, 0.37), (0.24, 0.37),
            ferme=True, c='t', w=1.1, fond='bg', alpha=255)


@_icone
def _dessin3d(k):
    k.trait((0.1, 0.74), (0.34, 0.4), (0.9, 0.4), (0.66, 0.74), ferme=True,
            c='d', w=1.1)
    k.cercle(0.44, 0.58, 0.07, c='a', w=1.3)
    k.trait((0.56, 0.5), (0.72, 0.5), (0.66, 0.64), c='a', w=1.3)
    k.trait((0.5, 0.36), (0.5, 0.1), c='d', w=1.0, tiret=True)


@_icone
def _transparente(k):
    k.cube(0.16, 0.34, 0.48, 0.2, c='t', w=1.3,
           faces=(('b', 50), ('b', 70), ('b', 35)), tiret_cache=True)


@_icone
def _inaccessibles(k):
    k.cube(0.16, 0.34, 0.48, 0.2, c='t', w=1.3,
           faces=(None, None, ('r', 210)))
    k.trait((0.26, 0.48), (0.54, 0.72), c='r', w=1.0, tiret=True)


@_icone
def _vue_iso(k):
    k.cube(0.2, 0.36, 0.42, 0.2, c='t', w=1.3,
           faces=(('a', 60), ('a', 150), ('a', 100)))
    k.fleche(0.94, 0.94, 0.72, 0.72, c='o', w=1.3, tete=0.12)


@_icone
def _vue_dessus(k):
    k.rect(0.2, 0.44, 0.6, 0.42, c='t', w=1.3, fond='a', alpha=120)
    k.fleche(0.5, 0.06, 0.5, 0.36, c='o', w=1.5, tete=0.13)


@_icone
def _vue_face(k):
    k.rect(0.38, 0.18, 0.5, 0.64, c='t', w=1.3, fond='a', alpha=120)
    k.fleche(0.04, 0.5, 0.3, 0.5, c='o', w=1.5, tete=0.13)


@_icone
def _actualiser(k):
    # un tour presque complet; la flèche au bout, dans le sens du tour
    k.arc(0.5, 0.5, 0.3, 40, 290, c='a', w=1.7)
    fin = math.radians(330)
    x, y = 0.5 + 0.3 * math.cos(fin), 0.5 - 0.3 * math.sin(fin)
    tx, ty = -math.sin(fin), -math.cos(fin)       # la tangente (écran)
    k.fleche(x - 0.06 * tx, y - 0.06 * ty, x + 0.05 * tx, y + 0.05 * ty,
             c='a', w=1.7, tete=0.17)


@_icone
def _import_step(k):
    k.cube(0.14, 0.46, 0.4, 0.18, c='t', w=1.2,
           faces=(('b', 90), ('b', 150), ('b', 60)))
    k.fleche(0.78, 0.06, 0.78, 0.5, c='v', w=1.6, tete=0.13)


@_icone
def _usinage3d(k):
    k.trait((0.08, 0.86), (0.08, 0.66), (0.3, 0.6), (0.5, 0.7), (0.72, 0.6),
            (0.92, 0.66), (0.92, 0.86), ferme=True, c='t', w=1.2,
            fond='o', alpha=110)
    k.rect(0.42, 0.08, 0.16, 0.34, c='t', w=1.2, fond='d', alpha=120)
    k.trait((0.44, 0.42), (0.44, 0.58), (0.5, 0.64), (0.56, 0.58),
            (0.56, 0.42), c='a', w=1.4)


@_icone
def _usiner_selection(k):
    k.cube(0.12, 0.4, 0.46, 0.2, c='t', w=1.2,
           faces=(None, ('a', 200), None))
    k.rect(0.7, 0.06, 0.12, 0.26, c='t', w=1.1)
    k.trait((0.72, 0.32), (0.76, 0.42), (0.8, 0.32), c='a', w=1.3)


@_icone
def _croix(k):
    k.trait((0.26, 0.26), (0.74, 0.74), c='t', w=1.9)
    k.trait((0.74, 0.26), (0.26, 0.74), c='t', w=1.9)


@_icone
def _machine(k):
    k.rect(0.08, 0.66, 0.84, 0.18, c='t', w=1.3)
    for x in (0.24, 0.46, 0.68):
        k.rect(x, 0.66, 0.08, 0.08, c='d', w=1.0, fond='d')
    k.rect(0.4, 0.08, 0.2, 0.3, c='t', w=1.3, fond='a', alpha=110)
    k.trait((0.5, 0.38), (0.5, 0.56), c='a', w=1.6)


@_icone
def _collisions(k):
    k.rect(0.12, 0.08, 0.2, 0.32, c='t', w=1.2)
    k.trait((0.22, 0.4), (0.22, 0.58), c='t', w=1.5)
    k.rect(0.12, 0.7, 0.4, 0.16, c='d', w=1.1)
    k.trait((0.66, 0.2), (0.92, 0.68), (0.4, 0.68), ferme=True, c='r',
            w=1.3, fond='r', alpha=80)
    k.trait((0.66, 0.34), (0.66, 0.52), c='r', w=1.6)
    k.point(0.66, 0.6, 0.035, 'r')


@_icone
def _ops_affichage(k):
    for i, pos in enumerate((0.3, 0.68, 0.48)):
        y = 0.24 + i * 0.26
        k.trait((0.12, y), (0.88, y), c='d', w=1.3)
        k.rect(pos - 0.07, y - 0.09, 0.14, 0.18, c='t', w=1.2, fond='a',
               rayon=0.03)


#: les icônes de ce module (pour les tests et la planche de contrôle)
NOMS = sorted(n for n in _icons._ICON_REGISTRY if n.startswith("b_"))
