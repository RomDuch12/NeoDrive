"""Arcs de cercle dans les polylignes / Arc fitting.

Un cercle importé arrive en soixante petits segments; une courbe d'un
logo vectorisé, en centaines. Retrouver les ARCS qu'ils dessinent:

- l'export DXF écrit des polylignes à « bulge » (arcs exacts, dix
  fois moins de sommets);
- le Tracé écrit `Arc CW|CCW X= Y= dX= dY=` — le format relevé sur
  les fichiers Datron de l'atelier (voir `sim3d`): la machine suit un
  vrai cercle au lieu d'enchaîner des cordes;
- « Lisser en arcs » remplace un tracé en escalier par des arcs
  tangents à `tolerance` près.

Glouton: depuis un sommet, la plus longue suite de sommets que porte
UNE droite ou UN arc à `tolerance` près (recherche exponentielle puis
dichotomique), la plus longue des deux gagne. Un arc demande au moins
quatre sommets (trois tiennent toujours sur un cercle), tourne dans un
seul sens, ne dépasse pas un demi-tour (un cercle complet = deux
arcs, sans ambiguïté pour la commande); ses sommets restent à
`tolerance` de lui, et ses cordes à une flèche d'échantillonnage (un
polygone de 60 côtés EST un cercle, un hexagone non). Idée reprise du lissage des courbes de CADCraft
(crate geom, `spline_fit`, © 2026 ArtCraft Team and the CADCraft
contributors, licence MIT — voir THIRD_PARTY_NOTICES.md), ici en arcs,
ce que la commande machine sait suivre.
"""
from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

import numpy as np

Point = Tuple[float, float]
#: ('L', fin) ou ('A', fin, centre, sens_trigo)
Segment = tuple

#: rayon au-delà duquel un « arc » est une droite
RAYON_MAX = 10000.0

#: flèche admise des cordes d'un cercle échantillonné: 0,5 % du rayon
#: (un polygone d'au moins 32 côtés), plafonnée à FLECHE_MAX mm
FLECHE_RELATIVE = 0.005
FLECHE_MAX = 0.1


def cercle_par_3(a: Point, b: Point, c: Point
                 ) -> Optional[Tuple[float, float, float]]:
    """Le cercle passant par trois points (cx, cy, r), None s'ils
    sont alignés."""
    ax, ay = a
    bx, by = b
    cx, cy = c
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return None
    a2, b2, c2 = ax * ax + ay * ay, bx * bx + by * by, cx * cx + cy * cy
    ux = (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / d
    uy = (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / d
    return ux, uy, math.hypot(ax - ux, ay - uy)


def _droite_ok(P: np.ndarray, i: int, j: int, tol: float) -> bool:
    """Les sommets i..j tiennent-ils sur le segment P[i]–P[j] ?"""
    a, b = P[i], P[j]
    ab = b - a
    n = math.hypot(ab[0], ab[1])
    q = P[i:j + 1] - a
    if n <= 1e-12:
        return bool(np.all(np.hypot(q[:, 0], q[:, 1]) <= tol))
    dist = np.abs(q[:, 0] * ab[1] - q[:, 1] * ab[0]) / n
    if np.any(dist > tol):
        return False
    t = (q[:, 0] * ab[0] + q[:, 1] * ab[1]) / n
    # pas de retour en arrière le long de la droite
    return bool(np.all(np.diff(t) >= -tol))


def _arc(P: np.ndarray, i: int, j: int, tol: float):
    """L'arc qui porte les sommets i..j, ou None."""
    if j - i < 3:
        return None
    m = (i + j) // 2
    c = cercle_par_3(tuple(P[i]), tuple(P[m]), tuple(P[j]))
    if c is None:
        return None
    cx, cy, r = c
    if r > RAYON_MAX or r < tol:
        return None
    q = P[i:j + 1] - (cx, cy)
    if np.any(np.abs(np.hypot(q[:, 0], q[:, 1]) - r) > tol):
        return None
    # la flèche d'une corde: l'échantillonnage d'un cercle (un
    # polygone fin), pas un écart — jusqu'à 0,5 % du rayon (0,1 mm au
    # plus); un hexagone (13 %) reste un hexagone
    seg = np.hypot(*np.diff(P[i:j + 1], axis=0).T)
    if np.any(seg * seg / (8.0 * r) > max(tol, min(FLECHE_RELATIVE * r,
                                                   FLECHE_MAX))):
        return None
    ang = np.arctan2(q[:, 1], q[:, 0])
    da = (np.diff(ang) + math.pi) % (2.0 * math.pi) - math.pi
    if not (np.all(da > 0) or np.all(da < 0)):
        return None
    balayage = float(np.sum(da))
    if abs(balayage) > math.pi + 1e-9:
        return None
    return cx, cy, r, balayage > 0


def _plus_loin(ok, i: int, n: int, debut: int) -> int:
    """Le plus grand j (≥ i + debut, < n) tel que ok(i, j), par
    recherche exponentielle puis dichotomique; i + debut - 1 sinon."""
    bas = i + debut - 1
    if i + debut >= n or not ok(i, i + debut):
        return bas
    bas = i + debut
    pas = 1
    haut = None
    while True:
        essai = min(n - 1, bas + pas)
        if essai == bas:
            return bas
        if ok(i, essai):
            bas = essai
            if essai == n - 1:
                return bas
            pas *= 2
        else:
            haut = essai
            break
    while haut - bas > 1:
        mil = (bas + haut) // 2
        if ok(i, mil):
            bas = mil
        else:
            haut = mil
    return bas


def ajuster(points: Sequence[Point], tolerance: float = 0.005
            ) -> List[Segment]:
    """Les segments (droites et arcs) qui suivent la polyligne à
    `tolerance` près, depuis son premier point (non répété)."""
    P = np.asarray(points, dtype=float)
    if len(P) < 2:
        return []
    garde = np.ones(len(P), dtype=bool)
    garde[1:] = np.hypot(*np.diff(P, axis=0).T) > 1e-12
    P = P[garde]
    n = len(P)
    sortie: List[Segment] = []
    i = 0
    while i < n - 1:
        jd = _plus_loin(lambda a, b: _droite_ok(P, a, b, tolerance),
                        i, n, 1)
        ja = _plus_loin(lambda a, b: _arc(P, a, b, tolerance) is not None,
                        i, n, 3)
        if ja > jd and ja >= i + 3:
            cx, cy, _r, trigo = _arc(P, i, ja, tolerance)
            sortie.append(('A', (float(P[ja][0]), float(P[ja][1])),
                           (float(cx), float(cy)), bool(trigo)))
            i = ja
        else:
            j = max(jd, i + 1)
            sortie.append(('L', (float(P[j][0]), float(P[j][1]))))
            i = j
    return sortie


def balayage(depart: Point, seg: Segment) -> float:
    """L'angle balayé par un arc (radians, > 0 en sens trigo)."""
    _g, fin, (cx, cy), trigo = seg
    a0 = math.atan2(depart[1] - cy, depart[0] - cx)
    a1 = math.atan2(fin[1] - cy, fin[0] - cx)
    b = a1 - a0
    if trigo:
        while b <= 1e-12:
            b += 2.0 * math.pi
    else:
        while b >= -1e-12:
            b -= 2.0 * math.pi
    return b


def vers_points(depart: Point, segments: Sequence[Segment],
                fleche: float = 0.002) -> List[Point]:
    """Les segments ré-aplatis à `fleche` près (départ compris)."""
    pts = [tuple(depart)]
    cour = tuple(depart)
    for seg in segments:
        if seg[0] == 'L':
            pts.append(tuple(seg[1]))
        else:
            _g, fin, (cx, cy), _t = seg
            r = math.hypot(cour[0] - cx, cour[1] - cy)
            b = balayage(cour, seg)
            pas = 2.0 * math.acos(max(-1.0, min(1.0, 1.0 - fleche / max(
                r, fleche)))) if r > fleche else abs(b)
            k = max(1, int(math.ceil(abs(b) / max(pas, 1e-4))))
            a0 = math.atan2(cour[1] - cy, cour[0] - cx)
            for m in range(1, k):
                a = a0 + b * m / k
                pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
            pts.append(tuple(fin))
        cour = tuple(seg[1])
    return pts


def bulges(depart: Point, segments: Sequence[Segment]
           ) -> List[Tuple[float, float, float]]:
    """Les sommets d'une LWPOLYLINE DXF: (x, y, bulge) — le bulge d'un
    sommet décrit le segment qui en PART (tan(balayage / 4), > 0 en
    sens trigo, 0 pour une droite)."""
    sortie = []
    cour = (float(depart[0]), float(depart[1]))
    for seg in segments:
        b = 0.0 if seg[0] == 'L' else math.tan(balayage(cour, seg) / 4.0)
        sortie.append((cour[0], cour[1], float(b)))
        cour = (float(seg[1][0]), float(seg[1][1]))
    sortie.append((cour[0], cour[1], 0.0))
    return sortie


def _n(v: float, decimales: int) -> str:
    v = round(float(v), decimales)
    return f"{(v if v else 0.0):g}"         # jamais « -0 »


def ligne_simpl(depart: Point, seg: Segment, decimales: int = 4) -> str:
    """La commande SimPL d'un segment: `Line X= Y=` (axes qui
    changent seulement) ou `Arc CW|CCW X= Y= dX= dY=` (centre relatif
    au départ, comme les fichiers Datron de l'atelier)."""
    fin = seg[1]
    if seg[0] == 'L':
        parts = []
        if abs(fin[0] - depart[0]) > 1e-9:
            parts.append(f"X={_n(fin[0], decimales)}")
        if abs(fin[1] - depart[1]) > 1e-9:
            parts.append(f"Y={_n(fin[1], decimales)}")
        return ("Line " + " ".join(parts)) if parts else ""
    _g, fin, (cx, cy), trigo = seg
    return (f"Arc {'CCW' if trigo else 'CW'} X={_n(fin[0], decimales)} "
            f"Y={_n(fin[1], decimales)} dX={_n(cx - depart[0], decimales)} "
            f"dY={_n(cy - depart[1], decimales)}")


def compte(segments: Sequence[Segment]) -> Tuple[int, int]:
    """(droites, arcs)."""
    arcs = sum(1 for s in segments if s[0] == 'A')
    return len(segments) - arcs, arcs
