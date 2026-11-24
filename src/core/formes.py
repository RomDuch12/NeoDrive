"""Reconnaître les formes d'un dessin: une polyligne qui EST un cercle,
un rectangle, une ellipse, une droite, un arc.

Un DXF exporté par certains logiciels, une image vectorisée, un tracé
à main levée: les cercles y arrivent en polygones, les rectangles en
polylignes de cent points. Reconnus, ils redeviennent des entités
exactes — un cercle a son centre (perçage, « DXF to Op »), un
rectangle ses cotes (poche rectangle), une droite deux points.

Idée reprise de la reconnaissance de formes du Shaper de VectorCraft
(crate geom, `recognize`, © 2026 ArtCraft Team and the VectorCraft
contributors, licence MIT — voir THIRD_PARTY_NOTICES.md), ici sur des
polylignes de dessin et non des gestes: ajustements aux moindres carrés
(cercle de Kåsa, ellipse directe de Fitzgibbon), puis l'écart RÉEL de
chaque sommet à la forme doit rester sous la tolérance.
"""
from __future__ import annotations

import math
from typing import Dict, Optional, Sequence, Tuple

import numpy as np

Point = Tuple[float, float]


def _tableau(pl) -> np.ndarray:
    P = np.asarray(pl, dtype=float)
    if len(P) >= 2:
        garde = np.ones(len(P), dtype=bool)
        garde[1:] = np.hypot(*np.diff(P, axis=0).T) > 1e-12
        P = P[garde]
    return P


def est_fermee(P: np.ndarray, tol: float) -> bool:
    return len(P) >= 4 and float(np.hypot(*(P[0] - P[-1]))) <= tol


def ajuster_cercle(P: np.ndarray) -> Optional[Tuple[float, float, float, float]]:
    """(cx, cy, r, écart max des sommets) — cercle de Kåsa."""
    if len(P) < 3:
        return None
    x, y = P[:, 0], P[:, 1]
    A = np.c_[x, y, np.ones_like(x)]
    b = x * x + y * y
    try:
        sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    except np.linalg.LinAlgError:
        return None
    cx, cy = sol[0] / 2.0, sol[1] / 2.0
    r2 = sol[2] + cx * cx + cy * cy
    if r2 <= 0:
        return None
    r = math.sqrt(r2)
    ecart = float(np.max(np.abs(np.hypot(x - cx, y - cy) - r)))
    return cx, cy, r, ecart


def ajuster_ellipse(P: np.ndarray):
    """(cx, cy, a, b, angle en degrés, écart max) — ellipse directe de
    Fitzgibbon; None si les points ne décrivent pas une ellipse."""
    if len(P) < 6:
        return None
    m = P.mean(axis=0)
    k = max(float(np.abs(P - m).max()), 1e-12)
    x, y = (P[:, 0] - m[0]) / k, (P[:, 1] - m[1]) / k
    D1 = np.c_[x * x, x * y, y * y]
    D2 = np.c_[x, y, np.ones_like(x)]
    S1, S2, S3 = D1.T @ D1, D1.T @ D2, D2.T @ D2
    try:
        T = -np.linalg.solve(S3, S2.T)
    except np.linalg.LinAlgError:
        return None
    M = S1 + S2 @ T
    M = np.array([M[2] / 2.0, -M[1], M[0] / 2.0])
    try:
        valeurs, vecteurs = np.linalg.eig(M)
    except np.linalg.LinAlgError:
        return None
    vecteurs = np.real(vecteurs)
    cond = 4 * vecteurs[0] * vecteurs[2] - vecteurs[1] ** 2
    choix = np.flatnonzero(cond > 0)
    if not len(choix):
        return None
    a1 = vecteurs[:, choix[0]]
    a, b, c = a1
    d, e, f = T @ a1
    den = b * b - 4 * a * c
    if den >= 0:
        return None
    x0 = (2 * c * d - b * e) / den
    y0 = (2 * a * e - b * d) / den
    num = 2 * (a * e * e + c * d * d - b * d * e + den * f)
    racine = math.sqrt((a - c) ** 2 + b * b)
    try:
        ra = -math.sqrt(num * (a + c + racine)) / den
        rb = -math.sqrt(num * (a + c - racine)) / den
    except ValueError:
        return None
    if not (ra > 0 and rb > 0):
        return None
    theta = 0.5 * math.atan2(-b, c - a)
    if ra < rb:
        ra, rb = rb, ra
        theta += math.pi / 2
    cx, cy = x0 * k + m[0], y0 * k + m[1]
    ra, rb = ra * k, rb * k
    # écart réel: distance de chaque sommet à l'ellipse échantillonnée
    t = np.linspace(0, 2 * math.pi, 1441)
    ct, st = math.cos(theta), math.sin(theta)
    ex = cx + ra * np.cos(t) * ct - rb * np.sin(t) * st
    ey = cy + ra * np.cos(t) * st + rb * np.sin(t) * ct
    from scipy.spatial import cKDTree
    d_, _i = cKDTree(np.c_[ex, ey]).query(P)
    return cx, cy, ra, rb, math.degrees(theta) % 180.0, float(d_.max())


def _rectangle(P: np.ndarray, tol: float):
    """(cx, cy, largeur, hauteur, angle en degrés) d'un contour fermé
    qui est un rectangle, sinon None."""
    from shapely.geometry import LineString, Polygon
    anneau = LineString(P).simplify(tol, preserve_topology=False)
    Q = np.asarray(anneau.coords, dtype=float)
    if len(Q) == 6 and np.hypot(*(Q[0] - Q[-1])) <= tol:
        # le départ tombait au milieu d'un côté: un sommet de trop
        Q = Q[1:]
        Q = np.vstack([Q, Q[:1]]) if np.hypot(*(Q[0] - Q[-1])) > tol else Q
    if len(Q) != 5:
        return None
    coins = Q[:4]
    cotes = np.roll(coins, -1, axis=0) - coins
    longueurs = np.hypot(cotes[:, 0], cotes[:, 1])
    if longueurs.min() <= 2 * tol:
        return None
    for i in range(4):
        u, v = cotes[i], cotes[(i + 1) % 4]
        cos = abs(float(np.dot(u, v))) / (longueurs[i] * longueurs[(i + 1) % 4])
        if cos > math.sin(math.radians(1.5)):      # pas d'équerre
            return None
    if abs(longueurs[0] - longueurs[2]) > 2 * tol or \
            abs(longueurs[1] - longueurs[3]) > 2 * tol:
        return None
    poly = Polygon(coins)
    bord = poly.exterior
    from shapely.geometry import Point as SPoint
    if max(bord.distance(SPoint(p)) for p in P) > tol:
        return None
    angle = math.degrees(math.atan2(cotes[0][1], cotes[0][0])) % 180.0
    if angle >= 90.0 - 1e-9:
        angle -= 90.0
        largeur, hauteur = float(longueurs[1]), float(longueurs[0])
    else:
        largeur, hauteur = float(longueurs[0]), float(longueurs[1])
    c = coins.mean(axis=0)
    return float(c[0]), float(c[1]), largeur, hauteur, angle


def reconnaitre(polyligne: Sequence[Point], tol: float = 0.05
                ) -> Optional[Dict]:
    """La forme exacte d'une polyligne, ou None:

    - {'genre': 'cercle', 'cx', 'cy', 'r'}
    - {'genre': 'rectangle', 'cx', 'cy', 'largeur', 'hauteur', 'angle'}
    - {'genre': 'ellipse', 'cx', 'cy', 'a', 'b', 'angle'}
    - {'genre': 'ligne', 'p0', 'p1'}
    - {'genre': 'arc', 'cx', 'cy', 'r', 'depart', 'fin', 'trigo'}
    Chaque fois, 'ecart': le plus grand écart d'un sommet à la forme."""
    P = _tableau(polyligne)
    if len(P) < 2:
        return None
    forme = _reconnaitre(P, tol)
    if forme is None:
        return None
    # des flottants Python (pas de numpy dans les paramètres)
    return {k: (float(v) if isinstance(v, (np.floating, float)) else v)
            for k, v in forme.items()}


def _reconnaitre(P: np.ndarray, tol: float) -> Optional[Dict]:
    ferme = est_fermee(P, tol)
    if not ferme:
        a, b = P[0], P[-1]
        ab = b - a
        n = float(np.hypot(*ab))
        if n > tol:
            d = np.abs((P[:, 0] - a[0]) * ab[1] - (P[:, 1] - a[1]) * ab[0]) / n
            if float(d.max()) <= tol:
                return {'genre': 'ligne', 'p0': (float(a[0]), float(a[1])),
                        'p1': (float(b[0]), float(b[1])),
                        'ecart': float(d.max())}
        if len(P) >= 5:
            c = ajuster_cercle(P)
            if c and c[3] <= tol and c[2] < 1e5:
                cx, cy, r, ecart = c
                ang = np.unwrap(np.arctan2(P[:, 1] - cy, P[:, 0] - cx))
                da = np.diff(ang)
                if np.all(da > 0) or np.all(da < 0):
                    return {'genre': 'arc', 'cx': cx, 'cy': cy, 'r': r,
                            'depart': (float(P[0][0]), float(P[0][1])),
                            'fin': (float(P[-1][0]), float(P[-1][1])),
                            'trigo': bool(da[0] > 0), 'ecart': ecart}
        return None
    if len(P) >= 8:
        c = ajuster_cercle(P[:-1])
        if c and c[3] <= tol:
            cx, cy, r, ecart = c
            return {'genre': 'cercle', 'cx': cx, 'cy': cy, 'r': r,
                    'ecart': ecart}
    rect = _rectangle(P, tol)
    if rect is not None:
        cx, cy, w, h, angle = rect
        return {'genre': 'rectangle', 'cx': cx, 'cy': cy, 'largeur': w,
                'hauteur': h, 'angle': angle, 'ecart': 0.0}
    if len(P) >= 12:
        e = ajuster_ellipse(P[:-1])
        if e and e[5] <= tol:
            cx, cy, a, b, angle, ecart = e
            return {'genre': 'ellipse', 'cx': cx, 'cy': cy, 'a': a, 'b': b,
                    'angle': angle, 'ecart': ecart}
    return None


NOMS = {'cercle': "cercle", 'rectangle': "rectangle", 'ellipse': "ellipse",
        'ligne': "droite", 'arc': "arc"}
