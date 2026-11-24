"""La géométrie des cotes d'un plan: linéaire (horizontale ou
verticale), alignée, rayon, diamètre, angle.

Une cote rend ses TRAITS (lignes d'attache, ligne de cote, flèches
ouvertes) en polylignes, et son TEXTE: la valeur, le centre de sa
boîte et son angle (toujours lisible, jamais tête en bas). Tout est en
millimètres, Y vers le haut; le canvas en fait des entités du calque
Annotations, exportées au DXF et imprimées.

Les genres et leurs règles (une cote linéaire est horizontale si le
point de placement s'écarte plus en hauteur qu'en largeur) suivent les
commandes DIMLINEAR, DIMALIGNED, DIMRADIUS, DIMDIAMETER, DIMANGULAR de
CADCraft (crate engine, © 2026 ArtCraft Team and the CADCraft
contributors, licence MIT — voir THIRD_PARTY_NOTICES.md), réécrites
ici.
"""
from __future__ import annotations

import math
from typing import Dict, List, Tuple

Point = Tuple[float, float]

#: longueur des flèches, dépassement et écart des lignes d'attache (mm)
FLECHE = 1.5
DEPASSEMENT = 1.0
ECART = 0.6
#: ouverture d'une flèche, en degrés de part et d'autre
OUVERTURE = 18.0

GENRES = {
    'cote_lin': "Cote linéaire",
    'cote_ali': "Cote alignée",
    'cote_ray': "Cote de rayon",
    'cote_dia': "Cote de diamètre",
    'cote_ang': "Cote d'angle",
}
#: combien de clics demande chaque genre
CLICS = {'cote_lin': 3, 'cote_ali': 3, 'cote_ray': 1, 'cote_dia': 1,
         'cote_ang': 3}


def valeur(v: float, decimales: int = 2) -> str:
    """12.5 et non 12.50; 12 et non 12.00."""
    texte = f"{round(float(v), decimales):.{decimales}f}"
    if '.' in texte:
        texte = texte.rstrip('0').rstrip('.')
    return texte or "0"


def _angle_lisible(deg: float) -> float:
    """Un texte jamais tête en bas: dans ]-90°, 90°]."""
    deg = (deg + 180.0) % 360.0 - 180.0
    if deg > 90.0 + 1e-9:
        deg -= 180.0
    elif deg <= -90.0 + 1e-9:
        deg += 180.0
    return deg


def _fleche(pointe: Point, vers: Point, longueur: float = FLECHE
            ) -> List[Point]:
    """Une flèche ouverte en `pointe`, sa queue vers `vers`."""
    dx, dy = vers[0] - pointe[0], vers[1] - pointe[1]
    n = math.hypot(dx, dy) or 1.0
    ux, uy = dx / n, dy / n
    a = math.radians(OUVERTURE)
    c, s = math.cos(a), math.sin(a)
    g = (pointe[0] + longueur * (ux * c - uy * s),
         pointe[1] + longueur * (ux * s + uy * c))
    d = (pointe[0] + longueur * (ux * c + uy * s),
         pointe[1] + longueur * (-ux * s + uy * c))
    return [g, pointe, d]


def _cote_droite(p1: Point, p2: Point, u: Point, p3: Point,
                 mesure: float, hauteur: float, prefixe: str = "",
                 decimales: int = 2) -> Dict:
    """Ligne de cote parallèle à u, placée par p3."""
    n = (-u[1], u[0])
    o = (p3[0] - p1[0]) * n[0] + (p3[1] - p1[1]) * n[1]
    o2 = (p3[0] - p2[0]) * n[0] + (p3[1] - p2[1]) * n[1]
    q1 = (p1[0] + n[0] * o, p1[1] + n[1] * o)
    q2 = (p2[0] + n[0] * o2, p2[1] + n[1] * o2)
    traits = []
    for p, q, dist in ((p1, q1, o), (p2, q2, o2)):
        sens = 1.0 if dist >= 0 else -1.0
        if abs(dist) > ECART:
            traits.append([(p[0] + n[0] * sens * ECART,
                            p[1] + n[1] * sens * ECART),
                           (q[0] + n[0] * sens * DEPASSEMENT,
                            q[1] + n[1] * sens * DEPASSEMENT)])
    traits.append([q1, q2])
    traits.append(_fleche(q1, q2))
    traits.append(_fleche(q2, q1))
    sens = 1.0 if o >= 0 else -1.0
    m = ((q1[0] + q2[0]) / 2 + n[0] * sens * (0.6 * hauteur + ECART),
         (q1[1] + q2[1]) / 2 + n[1] * sens * (0.6 * hauteur + ECART))
    angle = _angle_lisible(math.degrees(math.atan2(u[1], u[0])))
    return {'traits': traits, 'texte': prefixe + valeur(mesure, decimales),
            'centre': m, 'angle': angle, 'mesure': mesure}


def cote_lineaire(p1: Point, p2: Point, p3: Point, hauteur: float = 2.5,
                  decimales: int = 2) -> Dict:
    """Horizontale si p3 s'écarte plus en hauteur qu'en largeur du
    milieu des deux points, verticale sinon."""
    mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
    if abs(p3[1] - my) >= abs(p3[0] - mx):
        return _cote_droite(p1, p2, (1.0, 0.0), p3, abs(p2[0] - p1[0]),
                            hauteur, decimales=decimales)
    return _cote_droite(p1, p2, (0.0, 1.0), p3, abs(p2[1] - p1[1]),
                        hauteur, decimales=decimales)


def cote_alignee(p1: Point, p2: Point, p3: Point, hauteur: float = 2.5,
                 decimales: int = 2) -> Dict:
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    n = math.hypot(dx, dy) or 1.0
    return _cote_droite(p1, p2, (dx / n, dy / n), p3, math.hypot(dx, dy),
                        hauteur, decimales=decimales)


def cote_rayon(centre: Point, r: float, point: Point,
               diametre: bool = False, hauteur: float = 2.5,
               decimales: int = 2) -> Dict:
    """Le rayon (ou le diamètre) d'un cercle, dans la direction du
    point cliqué. Le texte se pose au-delà du cercle s'il y a été
    cliqué, sur la ligne sinon."""
    dx, dy = point[0] - centre[0], point[1] - centre[1]
    n = math.hypot(dx, dy)
    ux, uy = (dx / n, dy / n) if n > 1e-9 else (1.0, 0.0)
    bord = (centre[0] + r * ux, centre[1] + r * uy)
    traits = []
    if diametre:
        oppose = (centre[0] - r * ux, centre[1] - r * uy)
        traits.append([oppose, bord])
        traits.append(_fleche(bord, oppose))
        traits.append(_fleche(oppose, bord))
        texte = "Ø" + valeur(2 * r, decimales)
        mesure = 2 * r
    else:
        traits.append([centre, bord])
        traits.append(_fleche(bord, centre))
        texte = "R" + valeur(r, decimales)
        mesure = r
    angle = _angle_lisible(math.degrees(math.atan2(uy, ux)))
    if n > r + ECART:
        # cliqué dehors: une ligne de rappel jusqu'au texte
        traits.append([bord, (centre[0] + n * ux, centre[1] + n * uy)])
        ref = (centre[0] + (n + 0.3 * hauteur * len(texte)) * ux,
               centre[1] + (n + 0.3 * hauteur * len(texte)) * uy)
    else:
        milieu = r / 2.0 if not diametre else 0.0
        ref = (centre[0] + milieu * ux - uy * (0.6 * hauteur + ECART),
               centre[1] + milieu * uy + ux * (0.6 * hauteur + ECART))
    return {'traits': traits, 'texte': texte, 'centre': ref,
            'angle': angle, 'mesure': mesure}


def cote_angle(sommet: Point, a: Point, b: Point, hauteur: float = 2.5,
               decimales: int = 1) -> Dict:
    """L'angle (le plus petit) entre sommet→a et sommet→b, un arc à
    0,6 fois le plus court des deux côtés."""
    ta = math.atan2(a[1] - sommet[1], a[0] - sommet[0])
    tb = math.atan2(b[1] - sommet[1], b[0] - sommet[0])
    d = (tb - ta + math.pi) % (2 * math.pi) - math.pi
    r = 0.6 * min(math.dist(sommet, a), math.dist(sommet, b))
    r = max(r, 2 * FLECHE)
    n = max(8, int(abs(d) / math.radians(3)))
    arc = [(sommet[0] + r * math.cos(ta + d * k / n),
            sommet[1] + r * math.sin(ta + d * k / n)) for k in range(n + 1)]
    traits = [arc, _fleche(arc[0], arc[1]), _fleche(arc[-1], arc[-2])]
    for p, t in ((a, ta), (b, tb)):
        if math.dist(sommet, p) < r:
            # le côté est court: on le prolonge jusqu'à l'arc
            traits.append([p, (sommet[0] + (r + DEPASSEMENT) * math.cos(t),
                               sommet[1] + (r + DEPASSEMENT) * math.sin(t))])
    tm = ta + d / 2
    ref = (sommet[0] + (r + 0.6 * hauteur + ECART) * math.cos(tm),
           sommet[1] + (r + 0.6 * hauteur + ECART) * math.sin(tm))
    deg = abs(math.degrees(d))
    return {'traits': traits, 'texte': valeur(deg, decimales) + "°",
            'centre': ref, 'angle': 0.0, 'mesure': deg}
