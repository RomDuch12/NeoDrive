"""Accrochages objet / Object snaps.

Tracer une ligne d'un coin à l'autre, mesurer d'un trou au bord,
piquer le milieu d'un côté: le curseur doit TOMBER sur le point, pas
à côté. Le canvas n'accrochait que les centres de cercles et la
grille; voici les accrochages d'un logiciel de DAO:

| mode            | marque      | le point                              |
|-----------------|-------------|---------------------------------------|
| extrémité       | carré       | bout d'un tracé, sommet d'un angle    |
| intersection    | croix       | croisement de deux tracés             |
| centre          | cercle      | centre d'un cercle                    |
| quadrant        | losange     | 0°, 90°, 180°, 270° d'un cercle       |
| milieu          | triangle    | milieu d'un côté, d'un arc            |
| perpendiculaire | équerre     | pied de la perpendiculaire depuis le  |
|                 |             | point précédent                       |
| proche          | sablier     | le point du tracé le plus proche      |

Les modes et leur ordre viennent de CADCraft (moteur `snap`, © 2026
ArtCraft Team and the CADCraft contributors, licence MIT — voir
THIRD_PARTY_NOTICES.md); le calcul est réécrit ici, vectorisé avec
numpy: un logo importé d'un seul tracé compte des milliers de
segments, et l'accrochage tourne à chaque mouvement de souris.

Le module est purement géométrique: des polylignes (tableaux (n, 2))
et des cercles (cx, cy, r), dans n'importe quel repère — celui de la
scène pour le canvas.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

import numpy as np

MODES = ('extremite', 'intersection', 'centre', 'quadrant', 'milieu',
         'perpendiculaire', 'proche')

NOMS = {
    'extremite': "Extrémité",
    'intersection': "Intersection",
    'centre': "Centre",
    'quadrant': "Quadrant",
    'milieu': "Milieu",
    'perpendiculaire': "Perpendiculaire",
    'proche': "Proche",
    'grille': "Grille",
}

#: les modes « précis » gagnent toujours sur perpendiculaire, qui
#: gagne sur proche (le plus vague: il est partout)
_RANG = {'extremite': 0, 'intersection': 0, 'centre': 0, 'quadrant': 0,
         'milieu': 0, 'perpendiculaire': 1, 'proche': 2}

#: un sommet où le tracé tourne de moins que ça n'est pas une
#: extrémité (les courbes aplaties tournent un peu à chaque sommet)
ANGLE_SOMMET = 8.0


@dataclass
class Prise:
    """Le point accroché."""
    x: float
    y: float
    mode: str
    distance: float = 0.0

    @property
    def nom(self) -> str:
        return NOMS.get(self.mode, self.mode)


def _segments_proches(P: np.ndarray, c: np.ndarray, rayon: float):
    """Les segments de la polyligne P à moins de `rayon` du point c:
    (A, B, projection, distance) pour ceux-là seulement."""
    A, B = P[:-1], P[1:]
    AB = B - A
    L2 = np.einsum('ij,ij->i', AB, AB)
    L2 = np.where(L2 <= 1e-24, 1e-24, L2)
    t = np.clip(np.einsum('ij,ij->i', c - A, AB) / L2, 0.0, 1.0)
    proj = A + t[:, None] * AB
    d = np.hypot(*(proj - c).T)
    ok = d <= rayon
    return A[ok], B[ok], proj[ok], d[ok], np.flatnonzero(ok)


def _sommets_angles(P: np.ndarray, ferme: bool) -> np.ndarray:
    """Les bouts (polyligne ouverte) et les sommets qui font un
    angle."""
    n = len(P)
    if n < 2:
        return P[:0]
    garde = np.zeros(n, dtype=bool)
    if not ferme:
        garde[0] = garde[-1] = True
    if n >= 3:
        u = P[1:-1] - P[:-2]
        v = P[2:] - P[1:-1]
        nu = np.hypot(*u.T)
        nv = np.hypot(*v.T)
        cos = np.einsum('ij,ij->i', u, v) / np.maximum(nu * nv, 1e-24)
        tourne = np.degrees(np.arccos(np.clip(cos, -1.0, 1.0)))
        garde[1:-1] = tourne >= ANGLE_SOMMET
        if ferme and n >= 4:
            u0 = P[0] - P[-2]
            v0 = P[1] - P[0]
            c0 = float(np.dot(u0, v0)) / max(
                float(np.hypot(*u0) * np.hypot(*v0)), 1e-24)
            garde[0] = math.degrees(math.acos(max(-1.0, min(1.0, c0)))) \
                >= ANGLE_SOMMET
    return P[garde]


def _intersection(a, b, c, d) -> Optional[Tuple[float, float]]:
    """Croisement des segments [a, b] et [c, d], s'il existe."""
    r = (b[0] - a[0], b[1] - a[1])
    s = (d[0] - c[0], d[1] - c[1])
    den = r[0] * s[1] - r[1] * s[0]
    if abs(den) <= 1e-18:
        return None
    qp = (c[0] - a[0], c[1] - a[1])
    t = (qp[0] * s[1] - qp[1] * s[0]) / den
    u = (qp[0] * r[1] - qp[1] * r[0]) / den
    if -1e-9 <= t <= 1 + 1e-9 and -1e-9 <= u <= 1 + 1e-9:
        return (a[0] + t * r[0], a[1] + t * r[1])
    return None


def accrocher(curseur: Tuple[float, float],
              polylignes: Iterable[Sequence], cercles: Iterable = (),
              rayon: float = 1.0, base: Optional[Tuple[float, float]] = None,
              modes: Sequence[str] = MODES) -> Optional[Prise]:
    """Le meilleur point d'accrochage à moins de `rayon` du curseur,
    ou None.

    `polylignes`: tracés (suites de points; fermé si le dernier point
    répète le premier). `cercles`: (cx, cy, r). `base`: le point
    précédent du tracé en cours (pour la perpendiculaire)."""
    c = np.asarray(curseur, dtype=float)
    modes = set(modes)
    prises: List[Prise] = []

    def proposer(x, y, mode):
        d = math.hypot(x - c[0], y - c[1])
        if d <= rayon and mode in modes:
            prises.append(Prise(float(x), float(y), mode, d))

    proches = []          # (A, B) des segments près du curseur
    for pl in polylignes:
        P = np.asarray(pl, dtype=float)
        if P.ndim != 2 or len(P) < 2:
            continue
        # tri rapide: la boîte du tracé
        if (P[:, 0].min() - rayon > c[0] or P[:, 0].max() + rayon < c[0]
                or P[:, 1].min() - rayon > c[1]
                or P[:, 1].max() + rayon < c[1]):
            continue
        A, B, proj, d, _idx = _segments_proches(P, c, rayon)
        if not len(A):
            continue
        ferme = len(P) >= 4 and np.hypot(*(P[0] - P[-1])) <= 1e-9
        if 'extremite' in modes:
            for x, y in _sommets_angles(P, ferme):
                proposer(x, y, 'extremite')
        if 'milieu' in modes:
            L = np.hypot(*(B - A).T)
            for (ax, ay), (bx, by), lg in zip(A, B, L):
                if lg >= 4.0 * rayon:
                    proposer((ax + bx) / 2, (ay + by) / 2, 'milieu')
            if not ferme and len(P) >= 3:
                # le milieu d'un arc: à mi-longueur du tracé
                seg = np.hypot(*np.diff(P, axis=0).T)
                cum = np.concatenate([[0.0], np.cumsum(seg)])
                moitie = cum[-1] / 2.0
                k = int(np.searchsorted(cum, moitie)) - 1
                k = max(0, min(k, len(seg) - 1))
                f = (moitie - cum[k]) / max(seg[k], 1e-12)
                m = P[k] + f * (P[k + 1] - P[k])
                proposer(m[0], m[1], 'milieu')
        if 'proche' in modes:
            i = int(np.argmin(d))
            proposer(proj[i][0], proj[i][1], 'proche')
        if base is not None and 'perpendiculaire' in modes:
            b = np.asarray(base, dtype=float)
            AB = B - A
            L2 = np.maximum(np.einsum('ij,ij->i', AB, AB), 1e-24)
            t = np.einsum('ij,ij->i', b - A, AB) / L2
            for k in np.flatnonzero((t > 1e-6) & (t < 1 - 1e-6)):
                pied = A[k] + t[k] * AB[k]
                proposer(pied[0], pied[1], 'perpendiculaire')
        proches.extend(zip(map(tuple, A), map(tuple, B)))

    if 'intersection' in modes and len(proches) >= 2:
        proches = proches[:200]
        for i in range(len(proches)):
            a, b = proches[i]
            for j in range(i + 1, len(proches)):
                e, f = proches[j]
                # deux segments qui se suivent se « croisent » à leur
                # sommet commun: c'est une extrémité, pas un croisement
                # (à un rien près: le bouclage d'un cercle aplati)
                if min(math.dist(a, e), math.dist(a, f), math.dist(b, e),
                       math.dist(b, f)) <= 1e-7:
                    continue
                p = _intersection(a, b, e, f)
                if p is not None:
                    proposer(p[0], p[1], 'intersection')

    for cx, cy, r in cercles:
        proposer(cx, cy, 'centre')
        if r > 0 and 'quadrant' in modes:
            for dx, dy in ((r, 0), (0, r), (-r, 0), (0, -r)):
                proposer(cx + dx, cy + dy, 'quadrant')

    if not prises:
        return None
    return min(prises, key=lambda p: (_RANG.get(p.mode, 3), p.distance))


def marque(mode: str, taille: float = 5.0) -> List[List[Tuple[float, float]]]:
    """Le dessin de la marque d'un mode, centré en (0, 0), en traits
    (pour le canvas, en pixels d'écran)."""
    t = float(taille)
    if mode == 'extremite':
        return [[(-t, -t), (t, -t), (t, t), (-t, t), (-t, -t)]]
    if mode == 'milieu':
        return [[(-t, t), (t, t), (0, -t), (-t, t)]]
    if mode == 'centre' or mode == 'grille':
        n = 16
        return [[(t * math.cos(2 * math.pi * k / n),
                  t * math.sin(2 * math.pi * k / n)) for k in range(n + 1)]]
    if mode == 'quadrant':
        return [[(0, -t), (t, 0), (0, t), (-t, 0), (0, -t)]]
    if mode == 'intersection':
        return [[(-t, -t), (t, t)], [(-t, t), (t, -t)]]
    if mode == 'perpendiculaire':
        return [[(-t, -t), (-t, t), (t, t)], [(-t, 0), (0, 0), (0, t)]]
    # proche: sablier
    return [[(-t, -t), (t, -t), (-t, t), (t, t), (-t, -t)]]
