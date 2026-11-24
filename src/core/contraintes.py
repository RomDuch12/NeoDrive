"""Un dessin paramétrique: des contraintes géométriques, et un solveur
qui déplace le dessin le MOINS possible pour les satisfaire.

Une cote qui pilote (cette longueur VAUT 40), deux traits qui restent
parallèles, un trou qui reste concentrique à un bossage, un sommet
fixe: on retouche le dessin, il garde ses intentions.

Le modèle: des POINTS (x, y) et des CERCLES (un point centre et un
rayon). Les traits sont des couples de points. Chaque contrainte donne
des résidus (nuls quand elle est tenue); le solveur (moindres carrés de
SciPy, régularisés vers la position de départ — un petit poids, plus
fort sur les points qu'on vient de bouger) les annule. Les points fixes
ne bougent pas du tout.

Idée et genres repris du solveur paramétrique de CADCraft (crate
constraints, © 2026 ArtCraft Team and the CADCraft contributors,
licence MIT — voir THIRD_PARTY_NOTICES.md), réécrit ici.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

#: genre → (ce qu'il faut désigner, a-t-il une valeur, symbole)
GENRES: Dict[str, Tuple[Tuple[str, ...], bool, str]] = {
    'horizontale': (('ligne',), False, "H"),
    'verticale': (('ligne',), False, "V"),
    'parallele': (('ligne', 'ligne'), False, "∥"),
    'perpendiculaire': (('ligne', 'ligne'), False, "⊥"),
    'egales': (('ligne', 'ligne'), False, "="),
    'longueur': (('ligne',), True, "L"),
    'distance': (('point', 'point'), True, "D"),
    'coincidents': (('point', 'point'), False, "●"),
    'concentriques': (('cercle', 'cercle'), False, "◎"),
    'rayon': (('cercle',), True, "R"),
    'tangente': (('ligne', 'cercle'), False, "T"),
    'fixe': (('point',), False, "⚓"),
}

NOMS = {
    'horizontale': "Horizontale", 'verticale': "Verticale",
    'parallele': "Parallèles", 'perpendiculaire': "Perpendiculaires",
    'egales': "Longueurs égales", 'longueur': "Longueur (cote pilotante)",
    'distance': "Distance entre deux points", 'coincidents': "Points confondus",
    'concentriques': "Concentriques", 'rayon': "Rayon (cote pilotante)",
    'tangente': "Tangente (trait et cercle)", 'fixe': "Point fixe",
}


class Systeme:
    """Des points, des cercles, des contraintes."""

    def __init__(self):
        self.points: List[List[float]] = []
        #: (indice du point centre, rayon)
        self.cercles: List[List[float]] = []
        self.contraintes: List[Tuple[str, tuple, Optional[float]]] = []
        self.fixes = set()

    def point(self, x: float, y: float) -> int:
        self.points.append([float(x), float(y)])
        return len(self.points) - 1

    def cercle(self, cx: float, cy: float, r: float) -> int:
        self.cercles.append([self.point(cx, cy), float(r)])
        return len(self.cercles) - 1

    def ajouter(self, genre: str, refs: Sequence, valeur: float = None):
        if genre not in GENRES:
            raise ValueError(f"contrainte inconnue: {genre}")
        if genre == 'fixe':
            self.fixes.add(int(refs[0]))
        self.contraintes.append((genre, tuple(refs), valeur))

    # ── les inconnues: x, y de chaque point, puis chaque rayon ──

    def _vecteur(self) -> np.ndarray:
        v = [c for p in self.points for c in p]
        v += [c[1] for c in self.cercles]
        return np.array(v, dtype=float)

    def _poser(self, v: np.ndarray) -> None:
        n = len(self.points)
        for i in range(n):
            self.points[i] = [float(v[2 * i]), float(v[2 * i + 1])]
        for k in range(len(self.cercles)):
            self.cercles[k][1] = float(v[2 * n + k])

    def _residus(self, v: np.ndarray) -> np.ndarray:
        n = len(self.points)

        def P(i):
            return v[2 * i], v[2 * i + 1]

        def C(k):
            ci = int(self.cercles[k][0])
            return P(ci), v[2 * n + k]
        r = []
        for genre, refs, val in self.contraintes:
            if genre in ('horizontale', 'verticale', 'longueur'):
                (ax, ay), (bx, by) = P(refs[0]), P(refs[1])
                if genre == 'horizontale':
                    r.append(ay - by)
                elif genre == 'verticale':
                    r.append(ax - bx)
                else:
                    r.append(math.hypot(bx - ax, by - ay) - float(val))
            elif genre in ('parallele', 'perpendiculaire', 'egales'):
                (ax, ay), (bx, by) = P(refs[0]), P(refs[1])
                (cx, cy), (dx, dy) = P(refs[2]), P(refs[3])
                u = (bx - ax, by - ay)
                w = (dx - cx, dy - cy)
                nu = math.hypot(*u) or 1e-12
                nw = math.hypot(*w) or 1e-12
                if genre == 'parallele':
                    r.append((u[0] * w[1] - u[1] * w[0]) / (nu * nw))
                elif genre == 'perpendiculaire':
                    r.append((u[0] * w[0] + u[1] * w[1]) / (nu * nw))
                else:
                    r.append(nu - nw)
            elif genre in ('distance', 'coincidents'):
                (ax, ay), (bx, by) = P(refs[0]), P(refs[1])
                if genre == 'distance':
                    r.append(math.hypot(bx - ax, by - ay) - float(val))
                else:
                    r += [ax - bx, ay - by]
            elif genre == 'concentriques':
                (a, _ra), (b, _rb) = C(refs[0]), C(refs[1])
                r += [a[0] - b[0], a[1] - b[1]]
            elif genre == 'rayon':
                _c, rc = C(refs[0])
                r.append(rc - float(val))
            elif genre == 'tangente':
                (ax, ay), (bx, by) = P(refs[0]), P(refs[1])
                (cx, cy), rc = C(refs[2])
                ux, uy = bx - ax, by - ay
                nu = math.hypot(ux, uy) or 1e-12
                d = abs((cx - ax) * uy - (cy - ay) * ux) / nu
                r.append(d - rc)
        return np.array(r, dtype=float)

    def residu(self) -> float:
        """Le plus grand écart restant (0: tout est tenu)."""
        r = self._residus(self._vecteur())
        return float(np.max(np.abs(r))) if len(r) else 0.0

    def resoudre(self, prioritaires: Sequence[int] = (),
                 tol: float = 1e-7) -> Tuple[bool, float]:
        """Satisfait les contraintes en bougeant le moins possible
        (les `prioritaires`, des points qu'on vient de poser, bougent
        encore moins). Rend (tenu ?, plus grand écart restant)."""
        from scipy.optimize import least_squares
        if not self.contraintes:
            return True, 0.0
        v0 = self._vecteur()
        libres = np.ones(len(v0), dtype=bool)
        for i in self.fixes:
            libres[2 * i] = libres[2 * i + 1] = False
        if not libres.any():
            return self.residu() <= 1e-6, self.residu()
        poids = np.full(len(v0), 1e-3)
        for i in prioritaires:
            if 0 <= i < len(self.points):
                poids[2 * i] = poids[2 * i + 1] = 1e-1
        z0 = v0[libres]
        w = poids[libres]

        def f(z):
            v = v0.copy()
            v[libres] = z
            return np.concatenate([self._residus(v), w * (z - z0)])

        sol = least_squares(f, z0, xtol=1e-12, ftol=1e-12, gtol=1e-12,
                            max_nfev=2000)
        v = v0.copy()
        v[libres] = sol.x
        # le poids de régularisation laisse un écart minuscule: on
        # finit sans lui (les points restent près, le résidu s'annule)
        def g(z):
            vv = v0.copy()
            vv[libres] = z
            return np.concatenate([self._residus(vv), 1e-6 * (z - sol.x)])
        sol2 = least_squares(g, sol.x, xtol=1e-14, ftol=1e-14, gtol=1e-14,
                             max_nfev=2000)
        v[libres] = sol2.x
        self._poser(v)
        reste = self.residu()
        return reste <= max(tol, 1e-6), reste


def symbole(genre: str, valeur=None) -> str:
    s = GENRES[genre][2]
    if valeur is not None and GENRES[genre][1]:
        return f"{s}={valeur:g}"
    return s
