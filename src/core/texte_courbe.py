"""Un texte sur un arc, ou le long d'un tracé.

Une référence autour d'une bague, une date sur le bord d'une plaque
ronde, un nom qui suit une courbe: le texte ne court plus sur une
ligne droite mais sur un SUPPORT.

- `Arc`: un cercle de centre (cx, cy) et de rayon r (la ligne de
  base). « Dessus »: le texte tourne dans le sens horaire, les lettres
  vers l'extérieur — il se lit en haut du cercle. « Dessous »: sens
  trigonométrique, les lettres vers le centre — il se lit en bas, sans
  retourner la pièce. `angle` place le milieu (ou le début, la fin) du
  texte.
- `Chemin`: une polyligne; le texte la suit dans son sens, les
  lettres à sa gauche.

Deux façons de poser les lettres:
- `poser_glyphes` (police à trait simple): chaque lettre reste DROITE,
  tournée selon la tangente en son milieu — comme on grave à la main;
- `courber` (contours d'une police TrueType): chaque point suit le
  support (les lettres épousent la courbe). Les segments longs sont
  d'abord recoupés, sinon le haut d'un « T » resterait droit.

Idée reprise du texte sur un tracé de VectorCraft (crate text,
© 2026 ArtCraft Team and the VectorCraft contributors, licence MIT —
voir THIRD_PARTY_NOTICES.md), réécrite ici.
"""
from __future__ import annotations

import math
from typing import List, Sequence, Tuple

Point = Tuple[float, float]

DISPOSITIONS = ("Ligne droite", "Arc (dessus)", "Arc (dessous)",
                "Le long du dessin")


class Arc:
    """Un cercle parcouru dans un sens, s = 0 à l'angle `angle`."""

    def __init__(self, cx: float, cy: float, rayon: float,
                 angle_deg: float, dessus: bool = True):
        self.cx, self.cy = float(cx), float(cy)
        self.r = max(1e-6, float(rayon))
        self.a0 = math.radians(angle_deg)
        self.sens = -1.0 if dessus else 1.0
        self.longueur = None

    def point(self, s: float) -> Tuple[float, float, float]:
        """(x, y, angle de la tangente) à l'abscisse s."""
        a = self.a0 + self.sens * s / self.r
        return (self.cx + self.r * math.cos(a),
                self.cy + self.r * math.sin(a),
                a + self.sens * math.pi / 2.0)

    def debut(self, largeur: float, alignement: str) -> float:
        if alignement == 'gauche':
            return 0.0
        if alignement == 'droite':
            return -largeur
        return -largeur / 2.0


class Chemin:
    """Une polyligne, paramétrée par sa longueur."""

    def __init__(self, points: Sequence[Point]):
        pts = []
        for p in points:
            p = (float(p[0]), float(p[1]))
            if not pts or math.dist(pts[-1], p) > 1e-9:
                pts.append(p)
        if len(pts) < 2:
            raise ValueError("un chemin demande deux points")
        self.pts = pts
        self.cumul = [0.0]
        for i in range(len(pts) - 1):
            self.cumul.append(self.cumul[-1] + math.dist(pts[i], pts[i + 1]))
        self.longueur = self.cumul[-1]

    def point(self, s: float) -> Tuple[float, float, float]:
        import bisect
        n = len(self.pts)
        if s <= 0:
            i = 0
        elif s >= self.longueur:
            i = n - 2
        else:
            i = min(n - 2, max(0, bisect.bisect_right(self.cumul, s) - 1))
        a, b = self.pts[i], self.pts[i + 1]
        lg = max(1e-12, self.cumul[i + 1] - self.cumul[i])
        t = (s - self.cumul[i]) / lg          # au-delà des bouts: prolongé
        return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t,
                math.atan2(b[1] - a[1], b[0] - a[0]))

    def debut(self, largeur: float, alignement: str) -> float:
        if alignement == 'gauche':
            return 0.0
        if alignement == 'droite':
            return self.longueur - largeur
        return (self.longueur - largeur) / 2.0


def poser_glyphes(glyphes, support, alignement: str = 'centre'
                  ) -> List[List[Point]]:
    """Des lettres posées DROITES sur le support. `glyphes`: liste de
    (x de début, largeur, traits) d'une ligne (ligne de base y = 0,
    voir `police_fil.glyphes_ligne`)."""
    if not glyphes:
        return []
    largeur = max(x + lg for x, lg, _t in glyphes)
    s0 = support.debut(largeur, alignement)
    sortie = []
    for x, lg, traits in glyphes:
        milieu = x + lg / 2.0
        px, py, th = support.point(s0 + milieu)
        c, s = math.cos(th), math.sin(th)
        for trait in traits:
            sortie.append([(px + (u - milieu) * c - v * s,
                            py + (u - milieu) * s + v * c)
                           for u, v in trait])
    return sortie


def _recouper(contour: Sequence[Point], pas: float) -> List[Point]:
    sortie = [tuple(contour[0])]
    for a, b in zip(contour, contour[1:]):
        d = math.dist(a, b)
        n = max(1, int(math.ceil(d / pas)))
        for k in range(1, n + 1):
            sortie.append((a[0] + (b[0] - a[0]) * k / n,
                           a[1] + (b[1] - a[1]) * k / n))
    return sortie


def courber(contours: Sequence[Sequence[Point]], support,
            alignement: str = 'centre', pas: float = 0.2
            ) -> List[List[Point]]:
    """Des contours (texte posé sur y = 0, x de gauche à droite)
    épousant le support: x devient l'abscisse le long du support, y le
    décalage à sa gauche."""
    if not contours:
        return []
    xs = [p[0] for c in contours for p in c]
    gauche, droite = min(xs), max(xs)
    s0 = support.debut(droite - gauche, alignement)
    sortie = []
    for contour in contours:
        pts = []
        for x, y in _recouper(contour, pas):
            px, py, th = support.point(s0 + (x - gauche))
            pts.append((px - y * math.sin(th), py + y * math.cos(th)))
        sortie.append(pts)
    return sortie


def support_depuis(disposition: str, cx: float, cy: float, rayon: float,
                   decalage_deg: float = 0.0, chemin=None):
    """Le support d'une disposition (None: ligne droite). L'arc du
    dessus a son milieu en haut (90°), celui du dessous en bas (270°),
    plus le décalage."""
    if disposition == "Arc (dessus)":
        return Arc(cx, cy, rayon, 90.0 + decalage_deg, dessus=True)
    if disposition == "Arc (dessous)":
        return Arc(cx, cy, rayon, 270.0 + decalage_deg, dessus=False)
    if disposition == "Le long du dessin" and chemin and len(chemin) >= 2:
        return Chemin(chemin)
    return None
