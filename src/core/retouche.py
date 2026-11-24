"""Retouches du dessin 2D: nettoyer, joindre, décaler, arrondir,
chanfreiner, unir.

Un DXF venu d'ailleurs arrive rarement prêt à usiner: des traits
en double (l'outil repasse, la gravure se creuse deux fois), des
contours livrés en morceaux (une poche veut un contour FERMÉ), des
angles intérieurs vifs qu'aucune fraise ne peut faire. Ces fonctions
travaillent sur des polylignes en mm — une polyligne fermée répète
son premier point à la fin — et ne connaissent pas Qt.

Les commandes viennent de CADCraft (OVERKILL, JOIN, OFFSET, FILLET,
CHAMFER) et de VectorCraft (Pathfinder: unir, soustraire,
intersection, exclure) — © 2026 ArtCraft Team and the CADCraft /
VectorCraft contributors, licence MIT, voir THIRD_PARTY_NOTICES.md.
Réécrites ici pour l'usinage:

- `nettoyer` ne retire pas que les doublons exacts (OVERKILL): un
  trait COUVERT par un autre, même en partie, même en sens inverse,
  perd la partie couverte; puis les morceaux se joignent;
- `conge` d'un contour fermé est morphologique: « saillants »
  arrondit ce qu'une fraise de rayon r ne peut pas atteindre dans
  une poche (ouverture), « rentrants » ce qu'elle laisse autour d'une
  pièce (fermeture). Un contour trop étroit pour la fraise y perd ce
  que la fraise y perdrait.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

Point = Tuple[float, float]
Polyligne = List[Point]

#: écart en dessous duquel deux points sont le même, en mm
TOLERANCE = 0.01

#: un sommet dont le trait tourne de moins que ça n'est pas un ANGLE
#: (les courbes aplaties en petits segments tournent d'un ou deux
#: degrés à chaque sommet)
ANGLE_MIN = 8.0

#: flèche des arcs ajoutés (congés, décalages), en mm
FLECHE = 0.005


# ── outils ──────────────────────────────────────────────────────────

def est_fermee(pl: Sequence[Point], tol: float = TOLERANCE) -> bool:
    return len(pl) >= 4 and math.dist(pl[0], pl[-1]) <= tol


def _propre(pl: Sequence[Point], tol: float = 1e-9) -> Polyligne:
    """Sans points répétés."""
    out: Polyligne = []
    for p in pl:
        p = (float(p[0]), float(p[1]))
        if not out or math.dist(out[-1], p) > tol:
            out.append(p)
    return out


def longueur(pl: Sequence[Point]) -> float:
    return sum(math.dist(pl[i], pl[i + 1]) for i in range(len(pl) - 1))


def _segments_arc(rayon: float, angle: float) -> int:
    """Combien de segments pour un arc d'`angle` radians à `FLECHE`."""
    if rayon <= FLECHE:
        return 2
    pas = 2.0 * math.acos(max(-1.0, min(1.0, 1.0 - FLECHE / rayon)))
    return max(2, int(math.ceil(abs(angle) / max(pas, 1e-3))))


def _quad_segs(distance: float) -> int:
    return max(8, min(256, _segments_arc(abs(distance), math.pi / 2)))


# ── doublons et chevauchements ──────────────────────────────────────

def _cle_doublon(pl: Polyligne, tol: float):
    """Une signature qui ne dépend ni du sens ni du point de départ."""
    q = [(round(x / tol), round(y / tol)) for x, y in pl]
    if est_fermee(pl, tol):
        q = q[:-1]
        k = q.index(min(q))
        q = q[k:] + q[:k]
        inverse = [q[0]] + q[1:][::-1]
        return ('f', tuple(min(q, inverse)))
    return ('o', tuple(min(q, q[::-1])))


def doublons(polylignes: Sequence[Polyligne],
             tol: float = TOLERANCE) -> List[int]:
    """Indices des polylignes qui répètent une polyligne précédente
    (mêmes sommets à `tol` près, dans un sens ou dans l'autre, un
    contour fermé quel que soit son point de départ)."""
    vus = set()
    sortie = []
    for i, pl in enumerate(polylignes):
        pl = _propre(pl)
        if len(pl) < 2:
            continue
        cle = _cle_doublon(pl, tol)
        if cle in vus:
            sortie.append(i)
        else:
            vus.add(cle)
    return sortie


class _Lignes:
    """Index des segments déjà gardés, par droite support."""

    #: largeur des bandes de droites parallèles, en mm: loin de
    #: l'origine, un millième de radian déplace la droite d'un mm
    BANDE = 1.0

    def __init__(self, tol: float):
        self.tol = tol
        self.pas_angle = max(1e-4, tol / 10.0)
        self.cases: Dict[Tuple[int, int], List[Tuple]] = {}

    def _support(self, p: Point, q: Point):
        """Direction (θ dans [0, π)) et distance signée à l'origine de
        la droite p–q. Au raccord θ = 0 / θ = π, d change de signe."""
        dx, dy = q[0] - p[0], q[1] - p[1]
        n = math.hypot(dx, dy)
        ux, uy = dx / n, dy / n
        if uy < -1e-12 or (abs(uy) <= 1e-12 and ux < 0):
            ux, uy = -ux, -uy
        theta = math.atan2(uy, ux)
        if theta >= math.pi:
            theta -= math.pi
        d = ux * p[1] - uy * p[0]
        return (ux, uy), theta, d

    def couvert(self, p: Point, q: Point) -> List[Tuple[float, float]]:
        """Les intervalles [t0, t1] (abscisse le long de p→q, 0 à la
        longueur) déjà couverts par un segment gardé."""
        n = math.dist(p, q)
        (ux, uy), theta, d = self._support(p, q)
        ka, kd = round(theta / self.pas_angle), round(d / self.BANDE)
        sx, sy = (q[0] - p[0]) / n, (q[1] - p[1]) / n
        sortie = []
        na = int(round(math.pi / self.pas_angle))
        for da in (-1, 0, 1):
            for dd in (-1, 0, 1):
                a = ka + da
                cles = [(a, kd + dd)]
                # θ = 0 et θ = π sont la même direction (d change de signe)
                if a < 0 or a >= na:
                    cles.append(((a % na), -(kd + dd)))
                for cle in cles:
                    for (a1, b1) in self.cases.get(cle, ()):
                        # les deux bouts de l'autre près de notre droite ?
                        ok = True
                        ts = []
                        for r in (a1, b1):
                            rx, ry = r[0] - p[0], r[1] - p[1]
                            if abs(sx * ry - sy * rx) > self.tol:
                                ok = False
                                break
                            ts.append(sx * rx + sy * ry)
                        if ok:
                            sortie.append((min(ts), max(ts)))
        return sortie

    def ajouter(self, p: Point, q: Point) -> None:
        (_u, theta, d) = self._support(p, q)
        cle = (round(theta / self.pas_angle), round(d / self.BANDE))
        self.cases.setdefault(cle, []).append((p, q))


def _soustraire(t0: float, t1: float, trous) -> List[Tuple[float, float]]:
    morceaux = [(t0, t1)]
    for a, b in sorted(trous):
        neufs = []
        for c, e in morceaux:
            if b <= c or a >= e:
                neufs.append((c, e))
                continue
            if a > c:
                neufs.append((c, a))
            if b < e:
                neufs.append((b, e))
        morceaux = neufs
    return morceaux


def sans_chevauchement(polylignes: Sequence[Polyligne],
                       tol: float = TOLERANCE,
                       references: Sequence[Polyligne] = ()
                       ) -> Tuple[List[Polyligne], int]:
    """Les polylignes, sans les parties déjà couvertes par une
    polyligne précédente (sur la même droite, à `tol` près) ou par
    une des `references` (des contours fermés qu'on garde tels quels:
    les quatre traits qui doublent un rectangle s'en vont).

    Rend (morceaux, nombre de segments raccourcis ou retirés)."""
    index = _Lignes(tol)
    for ref in references:
        ref = _propre(ref)
        for i in range(len(ref) - 1):
            if math.dist(ref[i], ref[i + 1]) > 1e-12:
                index.ajouter(ref[i], ref[i + 1])
    sortie: List[Polyligne] = []
    touches = 0
    for pl in polylignes:
        pl = _propre(pl)
        courant: Polyligne = []
        for i in range(len(pl) - 1):
            p, q = pl[i], pl[i + 1]
            n = math.dist(p, q)
            if n <= 1e-12:
                continue
            reste = _soustraire(0.0, n, index.couvert(p, q))
            reste = [(a, b) for a, b in reste if b - a > tol]
            if len(reste) != 1 or reste[0][0] > tol or reste[0][1] < n - tol:
                touches += 1
            sx, sy = (q[0] - p[0]) / n, (q[1] - p[1]) / n
            for a, b in reste:
                pa = p if a <= tol else (p[0] + sx * a, p[1] + sy * a)
                pb = q if b >= n - tol else (p[0] + sx * b, p[1] + sy * b)
                if courant and math.dist(courant[-1], pa) <= 1e-9:
                    courant.append(pb)
                else:
                    if len(courant) >= 2:
                        sortie.append(courant)
                    courant = [pa, pb]
            if not reste or reste[-1][1] < n - tol:
                if len(courant) >= 2:
                    sortie.append(courant)
                courant = []
        if len(courant) >= 2:
            sortie.append(courant)
        # on n'indexe la polyligne qu'APRÈS: elle ne se mange pas
        # elle-même (un aller-retour sur un trait reste à l'usineur)
        for i in range(len(pl) - 1):
            if math.dist(pl[i], pl[i + 1]) > 1e-12:
                index.ajouter(pl[i], pl[i + 1])
    return sortie, touches


# ── jonction ────────────────────────────────────────────────────────

def joindre(polylignes: Sequence[Polyligne], tol: float = TOLERANCE
            ) -> List[Polyligne]:
    """Les polylignes OUVERTES qui se touchent bout à bout (à `tol`
    près) n'en font plus qu'une; une chaîne qui revient à son départ
    se ferme. À un carrefour (trois bouts ou plus au même point), les
    chaînes s'arrêtent: on ne devine pas quel chemin suivre."""
    from scipy.spatial import cKDTree
    ouvertes = []
    sortie: List[Polyligne] = []
    for pl in polylignes:
        pl = _propre(pl)
        if len(pl) < 2:
            continue
        if est_fermee(pl, tol):
            pl[-1] = pl[0]
            sortie.append(pl)
        else:
            ouvertes.append(pl)
    if not ouvertes:
        return sortie
    bouts = np.array([pl[k] for pl in ouvertes for k in (0, -1)],
                     dtype=float)
    parent = list(range(len(bouts)))

    def racine(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, j in cKDTree(bouts).query_pairs(tol):
        ri, rj = racine(i), racine(j)
        if ri != rj:
            parent[ri] = rj
    noeud = [racine(i) for i in range(len(bouts))]
    membres: Dict[int, List[int]] = {}
    for i, n in enumerate(noeud):
        membres.setdefault(n, []).append(i)
    position = {n: tuple(bouts[m].mean(axis=0)) for n, m in membres.items()}

    utilise = [False] * len(ouvertes)

    def bout_libre(n, sauf):
        """L'autre bout (indice de bout) arrivant au nœud n."""
        if len(membres[n]) != 2:
            return None
        a, b = membres[n]
        autre = b if a == sauf else a
        return None if utilise[autre // 2] else autre

    def chaine_depuis(i_bout):
        k = i_bout // 2
        pl = ouvertes[k] if i_bout % 2 == 0 else ouvertes[k][::-1]
        utilise[k] = True
        pts = list(pl)
        pts[0] = position[noeud[i_bout]]
        fin = i_bout ^ 1
        while True:
            n = noeud[fin]
            pts[-1] = position[n]
            suivant = bout_libre(n, fin)
            if suivant is None:
                break
            k = suivant // 2
            utilise[k] = True
            pl = ouvertes[k] if suivant % 2 == 0 else ouvertes[k][::-1]
            pts.extend(pl[1:])
            fin = suivant ^ 1
        if noeud[fin] == noeud[i_bout] and len(pts) >= 3:
            pts[-1] = pts[0]
        return _propre(pts)

    # d'abord les chaînes qui partent d'un bout libre ou d'un carrefour
    for i in range(len(bouts)):
        if utilise[i // 2]:
            continue
        if len(membres[noeud[i]]) != 2:
            sortie.append(chaine_depuis(i))
    # ce qui reste fait des boucles
    for i in range(0, len(bouts), 2):
        if not utilise[i // 2]:
            sortie.append(chaine_depuis(i))
    return sortie


def nettoyer(polylignes: Sequence[Polyligne], tol: float = TOLERANCE
             ) -> Tuple[List[Polyligne], dict]:
    """Doublons retirés, parties couvertes retirées, morceaux joints.

    Rend (polylignes, bilan) — bilan: {'doublons', 'raccourcis',
    'avant', 'apres', 'fermees'}."""
    polylignes = [_propre(p) for p in polylignes]
    polylignes = [p for p in polylignes if len(p) >= 2]
    jetes = set(doublons(polylignes, tol))
    restent = [p for i, p in enumerate(polylignes) if i not in jetes]
    fermees = [p for p in restent if est_fermee(p, tol)]
    ouvertes = [p for p in restent if not est_fermee(p, tol)]
    morceaux, touches = sans_chevauchement(ouvertes, tol, fermees)
    jointes = joindre(morceaux, tol)
    sortie = fermees + jointes
    return sortie, {
        'avant': len(polylignes), 'apres': len(sortie),
        'doublons': len(jetes), 'raccourcis': touches,
        'fermees': sum(1 for p in sortie if est_fermee(p, tol))}


def resume_nettoyage(bilan: dict) -> str:
    parts = [f"{bilan['avant']} → {bilan['apres']} tracé(s)"]
    if bilan.get('doublons'):
        parts.append(f"{bilan['doublons']} doublon(s) retiré(s)")
    if bilan.get('raccourcis'):
        parts.append(f"{bilan['raccourcis']} segment(s) couvert(s) "
                     f"retiré(s) ou raccourci(s)")
    parts.append(f"{bilan.get('fermees', 0)} contour(s) fermé(s)")
    return " · ".join(parts)


# ── régions (shapely) ───────────────────────────────────────────────

def region(polylignes: Sequence[Polyligne], tol: float = TOLERANCE):
    """La surface délimitée par les contours FERMÉS, en pair-impair:
    l'intérieur du « O » est un trou, l'îlot dans le trou est plein."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union  # noqa: F401
    surf = None
    for pl in polylignes:
        pl = _propre(pl)
        if not est_fermee(pl, tol) or len(pl) < 4:
            continue
        poly = Polygon(pl).buffer(0)
        if poly.is_empty:
            continue
        surf = poly if surf is None else surf.symmetric_difference(poly)
    if surf is None:
        return Polygon()
    return surf


def contours_de(geom) -> List[Polyligne]:
    """Les bords d'une surface shapely: extérieurs puis trous."""
    if geom is None or geom.is_empty:
        return []
    polys = getattr(geom, 'geoms', [geom])
    sortie = []
    for g in polys:
        if g.geom_type == 'Polygon':
            sortie.append([tuple(p) for p in g.exterior.coords])
            for trou in g.interiors:
                sortie.append([tuple(p) for p in trou.coords])
        elif g.geom_type in ('MultiPolygon', 'GeometryCollection'):
            sortie.extend(contours_de(g))
    return sortie


# ── décaler ─────────────────────────────────────────────────────────

def decaler(polylignes: Sequence[Polyligne], distance: float,
            coins: str = 'rond', tol: float = TOLERANCE) -> List[Polyligne]:
    """Les contours décalés de `distance` mm: vers l'extérieur si
    positive, vers l'intérieur si négative (contours fermés, pris
    ensemble en pair-impair); à gauche du sens de parcours si
    positive (polylignes ouvertes). `coins`: 'rond' (le chemin d'un
    outil) ou 'vif'."""
    from shapely.geometry import LineString
    joint = 'round' if coins == 'rond' else 'mitre'
    qs = _quad_segs(distance)
    fermees = [p for p in polylignes if est_fermee(_propre(p), tol)]
    ouvertes = [_propre(p) for p in polylignes
                if not est_fermee(_propre(p), tol)]
    sortie: List[Polyligne] = []
    if fermees and abs(distance) > 0:
        surf = region(fermees, tol).buffer(
            distance, quad_segs=qs, join_style=joint, mitre_limit=10.0)
        sortie.extend(contours_de(surf))
    for pl in ouvertes:
        if len(pl) < 2 or distance == 0:
            continue
        g = LineString(pl).offset_curve(distance, quad_segs=qs,
                                        join_style=joint, mitre_limit=10.0)
        for part in getattr(g, 'geoms', [g]):
            if not part.is_empty and len(part.coords) >= 2:
                sortie.append([tuple(p) for p in part.coords])
    return sortie


# ── congés et chanfreins ────────────────────────────────────────────

def _orientation(pl: Polyligne) -> float:
    """Aire signée (> 0: sens trigonométrique)."""
    a = 0.0
    for i in range(len(pl) - 1):
        a += pl[i][0] * pl[i + 1][1] - pl[i + 1][0] * pl[i][1]
    return a / 2.0


def _angles(pl: Polyligne, ferme: bool, angles: str):
    """Les sommets qui sont des ANGLES à traiter: [(i, A, B, C)]."""
    n = len(pl) - 1 if ferme else len(pl)
    pts = pl[:-1] if ferme else pl
    sens = _orientation(pl) if ferme else 0.0
    sortie = []
    for i in range(n):
        if not ferme and (i == 0 or i == n - 1):
            continue
        a, b, c = pts[i - 1], pts[i], pts[(i + 1) % n]
        u = (a[0] - b[0], a[1] - b[1])
        v = (c[0] - b[0], c[1] - b[1])
        nu, nv = math.hypot(*u), math.hypot(*v)
        if nu <= 1e-12 or nv <= 1e-12:
            continue
        cos = max(-1.0, min(1.0, (u[0] * v[0] + u[1] * v[1]) / (nu * nv)))
        theta = math.acos(cos)              # angle intérieur au sommet
        if math.pi - theta < math.radians(ANGLE_MIN):
            continue                        # presque droit: pas un angle
        if ferme and angles != 'tous':
            croix = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
            saillant = croix * sens > 0
            if (angles == 'saillants') != saillant:
                continue
        sortie.append((i, a, b, c, theta, nu, nv))
    return sortie


def _arrondir_sommets(pl: Polyligne, rayon: float, chanfrein: bool,
                      angles: str, tol: float) -> Tuple[Polyligne, int]:
    """Congé (ou chanfrein de `rayon` mm le long de chaque côté) aux
    angles d'une polyligne. Rend (polyligne, nombre d'angles réduits
    faute de place)."""
    pl = _propre(pl)
    ferme = est_fermee(pl, tol)
    if ferme:
        pl[-1] = pl[0]
    pts = pl[:-1] if ferme else pl
    n = len(pts)
    coins = {i: (a, b, c, th, nu, nv)
             for i, a, b, c, th, nu, nv in _angles(pl, ferme, angles)}
    reduits = 0
    sortie: Polyligne = []
    for i in range(n):
        if i not in coins:
            sortie.append(pts[i])
            continue
        a, b, c, theta, nu, nv = coins[i]
        # la place: la moitié de chaque côté si l'autre bout est aussi
        # un angle traité, le côté entier sinon
        place_u = nu / 2.0 if ((i - 1) % n in coins) else nu
        place_v = nv / 2.0 if ((i + 1) % n in coins) else nv
        ux, uy = (a[0] - b[0]) / nu, (a[1] - b[1]) / nu
        vx, vy = (c[0] - b[0]) / nv, (c[1] - b[1]) / nv
        if chanfrein:
            t = rayon
            if t > min(place_u, place_v):
                t = min(place_u, place_v)
                reduits += 1
            sortie.append((b[0] + ux * t, b[1] + uy * t))
            sortie.append((b[0] + vx * t, b[1] + vy * t))
            continue
        r = rayon
        t = r / math.tan(theta / 2.0)
        if t > min(place_u, place_v):
            t = min(place_u, place_v)
            r = t * math.tan(theta / 2.0)
            reduits += 1
        t1 = (b[0] + ux * t, b[1] + uy * t)
        t2 = (b[0] + vx * t, b[1] + vy * t)
        bx, by = ux + vx, uy + vy
        nb = math.hypot(bx, by)
        if nb <= 1e-12 or r <= 1e-9:
            sortie.append(b)
            continue
        dc = r / math.sin(theta / 2.0)
        centre = (b[0] + bx / nb * dc, b[1] + by / nb * dc)
        a1 = math.atan2(t1[1] - centre[1], t1[0] - centre[0])
        a2 = math.atan2(t2[1] - centre[1], t2[0] - centre[0])
        da = (a2 - a1 + math.pi) % (2 * math.pi) - math.pi
        k = _segments_arc(r, da)
        for j in range(k + 1):
            ang = a1 + da * j / k
            sortie.append((centre[0] + r * math.cos(ang),
                           centre[1] + r * math.sin(ang)))
    if ferme and sortie:
        sortie.append(sortie[0])
    return _propre(sortie), reduits


def conge(polylignes: Sequence[Polyligne], rayon: float,
          angles: str = 'tous', tol: float = TOLERANCE
          ) -> Tuple[List[Polyligne], dict]:
    """Arrondit les angles au rayon `rayon` mm.

    `angles`: 'saillants', 'rentrants' ou 'tous'. Les contours fermés
    sont pris ensemble comme une surface (pair-impair): « saillants »
    est ce que la fraise ne peut pas atteindre dans une poche,
    « rentrants » ce qu'elle laisse autour d'une pièce. Les
    polylignes ouvertes, sommet par sommet ('tous').

    Rend (polylignes, bilan {'reduits', 'fermees', 'ouvertes'})."""
    fermees = [p for p in polylignes if est_fermee(_propre(p), tol)]
    ouvertes = [p for p in polylignes if not est_fermee(_propre(p), tol)]
    sortie: List[Polyligne] = []
    bilan = {'reduits': 0, 'fermees': len(fermees),
             'ouvertes': len(ouvertes)}
    if fermees and rayon > 0:
        qs = _quad_segs(rayon)
        surf = region(fermees, tol)
        if angles in ('saillants', 'tous'):
            surf = surf.buffer(-rayon, quad_segs=qs).buffer(rayon, quad_segs=qs)
        if angles in ('rentrants', 'tous'):
            surf = surf.buffer(rayon, quad_segs=qs).buffer(-rayon, quad_segs=qs)
        sortie.extend(contours_de(surf))
    elif fermees:
        sortie.extend(fermees)
    for pl in ouvertes:
        neuf, red = _arrondir_sommets(pl, rayon, False, 'tous', tol)
        bilan['reduits'] += red
        sortie.append(neuf)
    return sortie, bilan


def chanfrein(polylignes: Sequence[Polyligne], distance: float,
              angles: str = 'tous', tol: float = TOLERANCE
              ) -> Tuple[List[Polyligne], dict]:
    """Coupe les angles: `distance` mm le long de chaque côté.
    `angles` ('saillants', 'rentrants', 'tous') pour les contours
    fermés, selon leur sens."""
    sortie: List[Polyligne] = []
    bilan = {'reduits': 0}
    for pl in polylignes:
        neuf, red = _arrondir_sommets(pl, distance, True, angles, tol)
        bilan['reduits'] += red
        sortie.append(neuf)
    return sortie, bilan


# ── opérations booléennes (Pathfinder) ──────────────────────────────

OPERATIONS_BOOLEENNES = {
    'unir': "Unir",
    'soustraire': "Soustraire (le plus grand moins les autres)",
    'intersection': "Intersection",
    'exclure': "Exclure (ou exclusif)",
}


def booleen(groupes: Sequence[Sequence[Polyligne]], operation: str,
            tol: float = TOLERANCE) -> List[Polyligne]:
    """Combine des surfaces: chaque groupe (les contours fermés d'une
    entité: un « O » et son trou) en est une. 'soustraire' retire
    toutes les autres de la plus GRANDE — l'ordre de sélection ne se
    voit pas à l'écran, la taille si."""
    from shapely.ops import unary_union
    if operation not in OPERATIONS_BOOLEENNES:
        raise ValueError(f"opération inconnue: {operation}")
    surfaces = [region(g, tol) for g in groupes]
    surfaces = [s for s in surfaces if not s.is_empty]
    if not surfaces:
        return []
    if operation == 'unir':
        res = unary_union(surfaces)
    elif operation == 'soustraire':
        surfaces.sort(key=lambda s: -s.area)
        res = surfaces[0]
        if len(surfaces) > 1:
            res = res.difference(unary_union(surfaces[1:]))
    elif operation == 'intersection':
        res = surfaces[0]
        for s in surfaces[1:]:
            res = res.intersection(s)
    else:
        res = surfaces[0]
        for s in surfaces[1:]:
            res = res.symmetric_difference(s)
    return contours_de(res)


def surfaces_de(groupes: Sequence[Sequence[Polyligne]],
                tol: float = TOLERANCE) -> int:
    """Combien de groupes forment une surface (contours fermés)."""
    return sum(1 for g in groupes if not region(g, tol).is_empty)


# ── à un point du tracé: couper, départ, ajuster, prolonger ─────────

def _ligne(pl):
    from shapely.geometry import LineString
    return LineString([tuple(p) for p in _propre(pl)])


def _morceau(ligne, s0: float, s1: float) -> Polyligne:
    from shapely.ops import substring
    m = substring(ligne, s0, s1)
    if m.geom_type == 'Point':
        return []
    return [tuple(p) for p in m.coords]


def couper_au_point(pl: Sequence[Point], point: Point,
                    tol: float = TOLERANCE) -> List[Polyligne]:
    """Le tracé coupé au point (son projeté): un contour fermé s'ouvre
    là (une seule polyligne qui y commence et y finit), un tracé ouvert
    devient deux."""
    from shapely.geometry import Point as SPoint
    pl = _propre(pl)
    ligne = _ligne(pl)
    s = ligne.project(SPoint(point))
    L = ligne.length
    if est_fermee(pl, tol):
        a = _morceau(ligne, s, L)
        b = _morceau(ligne, 0.0, s)
        return [_propre(a + b[1:])] if a and b else [pl]
    if s <= tol or s >= L - tol:
        return [pl]
    return [m for m in (_morceau(ligne, 0.0, s), _morceau(ligne, s, L))
            if len(m) >= 2]


def depart_au_point(pl: Sequence[Point], point: Point,
                    tol: float = TOLERANCE) -> Polyligne:
    """Un contour FERMÉ qui commence (et finit) au point: l'outil y
    entrera. Un tracé ouvert est rendu tel quel."""
    pl = _propre(pl)
    if not est_fermee(pl, tol):
        return pl
    ouvert = couper_au_point(pl, point, tol)[0]
    ouvert[-1] = ouvert[0]
    return ouvert


def _parametres_intersection(ligne, autres) -> List[float]:
    """Abscisses, le long de `ligne`, de ses croisements avec les
    autres tracés."""
    from shapely.geometry import LineString, Point as SPoint
    from shapely.ops import unary_union
    lignes = [LineString([tuple(p) for p in _propre(o)]) for o in autres
              if len(_propre(o)) >= 2]
    if not lignes:
        return []
    inter = ligne.intersection(unary_union(lignes))
    pts = []
    for g in getattr(inter, 'geoms', [inter]):
        if g.is_empty:
            continue
        if g.geom_type == 'Point':
            pts.append(g)
        else:                   # un recouvrement: ses deux bouts
            c = list(getattr(g, 'coords', []))
            pts.extend(SPoint(q) for q in (c[:1] + c[-1:]))
    return sorted({round(ligne.project(p), 9) for p in pts})


def ajuster(pl: Sequence[Point], autres: Sequence[Sequence[Point]],
            point: Point, tol: float = TOLERANCE):
    """AJUSTER (TRIM): la partie du tracé autour du point, entre ses
    deux croisements les plus proches avec les autres tracés, s'en va.
    Rend les morceaux qui restent, ou None (aucun croisement)."""
    from shapely.geometry import Point as SPoint
    pl = _propre(pl)
    ligne = _ligne(pl)
    L = ligne.length
    params = _parametres_intersection(ligne, autres)
    s = ligne.project(SPoint(point))
    if est_fermee(pl, tol):
        params = [p for p in params if p < L - tol]
        if len(params) < 2:
            return None
        avant = [p for p in params if p < s]
        apres = [p for p in params if p > s]
        s0 = avant[-1] if avant else params[-1]
        s1 = apres[0] if apres else params[0]
        # garder de s1 à s0 en avançant (par la fermeture s'il le faut)
        if s1 < s0:
            garde = _morceau(ligne, s1, s0)
        else:
            garde = _morceau(ligne, s1, L) + _morceau(ligne, 0.0, s0)[1:]
        return [_propre(garde)] if len(garde) >= 2 else []
    interieurs = [p for p in params if tol < p < L - tol]
    if not interieurs:
        return None
    avant = [p for p in interieurs if p < s]
    apres = [p for p in interieurs if p > s]
    s0 = avant[-1] if avant else 0.0
    s1 = apres[0] if apres else L
    morceaux = []
    if s0 > tol:
        morceaux.append(_morceau(ligne, 0.0, s0))
    if s1 < L - tol:
        morceaux.append(_morceau(ligne, s1, L))
    return [m for m in morceaux if len(m) >= 2]


def prolonger(pl: Sequence[Point], autres: Sequence[Sequence[Point]],
              point: Point, longueur_max: float = 10000.0,
              tol: float = TOLERANCE):
    """PROLONGER (EXTEND): le bout du tracé le plus proche du point
    avance dans sa direction jusqu'au premier autre tracé. Rend le
    tracé prolongé, ou None (rien à rejoindre, ou tracé fermé)."""
    from shapely.geometry import LineString
    pl = _propre(pl)
    if len(pl) < 2 or est_fermee(pl, tol):
        return None
    fin = math.dist(point, pl[-1]) <= math.dist(point, pl[0])
    bout, avant = (pl[-1], pl[-2]) if fin else (pl[0], pl[1])
    dx, dy = bout[0] - avant[0], bout[1] - avant[1]
    n = math.hypot(dx, dy)
    if n <= 1e-12:
        return None
    ux, uy = dx / n, dy / n
    rayon = LineString([(bout[0] + ux * tol, bout[1] + uy * tol),
                        (bout[0] + ux * longueur_max,
                         bout[1] + uy * longueur_max)])
    params = _parametres_intersection(rayon, autres)
    if not params:
        return None
    s = params[0] + tol
    neuf = (bout[0] + ux * s, bout[1] + uy * s)
    pts = list(pl)
    if fin:
        pts[-1] = neuf               # le dernier côté s'allonge
    else:
        pts[0] = neuf
    return pts


def region_au_point(polylignes: Sequence[Sequence[Point]], point: Point
                    ) -> List[Polyligne]:
    """La région FERMÉE par les tracés autour du point (même faite de
    traits qui se croisent ou de morceaux): son contour et ses îlots.
    Vide si le point n'est enfermé par rien."""
    from shapely.geometry import LineString, Point as SPoint
    from shapely.ops import polygonize, unary_union
    lignes = [LineString([tuple(p) for p in _propre(pl)])
              for pl in polylignes if len(_propre(pl)) >= 2]
    if not lignes:
        return []
    faces = [f for f in polygonize(unary_union(lignes))
             if f.contains(SPoint(point))]
    if not faces:
        return []
    return contours_de(min(faces, key=lambda f: f.area))


def points_le_long(pl: Sequence[Point], nombre: int = 0, pas: float = 0.0,
                   bouts: bool = True, tol: float = TOLERANCE
                   ) -> List[Point]:
    """Des points répartis sur le tracé: `nombre` à intervalles égaux,
    ou tous les `pas` mm. Sur un contour fermé, le tour est partagé
    (pas de point en double au départ); sur un tracé ouvert, `bouts`
    met un point à chaque extrémité."""
    pl = _propre(pl)
    ligne = _ligne(pl)
    L = ligne.length
    if L <= tol:
        return []
    ferme = est_fermee(pl, tol)
    abscisses = []
    if nombre and nombre > 0:
        n = int(nombre)
        if ferme:
            abscisses = [L * k / n for k in range(n)]
        elif bouts:
            abscisses = ([L / 2.0] if n == 1 else
                         [L * k / (n - 1) for k in range(n)])
        else:
            abscisses = [L * k / (n + 1) for k in range(1, n + 1)]
    elif pas and pas > tol:
        k = 0
        while k * pas < L - tol:
            abscisses.append(k * pas)
            k += 1
        if not ferme:
            if bouts and L - abscisses[-1] > tol:
                abscisses.append(L)
            if not bouts:
                abscisses = [s for s in abscisses if tol < s < L - tol]
    sortie = []
    for s in abscisses:
        p = ligne.interpolate(s)
        sortie.append((float(p.x), float(p.y)))
    return sortie


def mesures(polylignes: Sequence[Sequence[Point]], tol: float = TOLERANCE
            ) -> dict:
    """Ce que mesure une sélection: nombre de tracés, longueur totale
    (celle que parcourt un outil de gravure), contours fermés, leur
    périmètre, l'aire qu'ils enferment (pair-impair), l'emprise."""
    pls = [_propre(p) for p in polylignes]
    pls = [p for p in pls if len(p) >= 2]
    fermees = [p for p in pls if est_fermee(p, tol)]
    pts = [q for p in pls for q in p]
    surf = region(fermees, tol) if fermees else None
    m = {
        'traces': len(pls),
        'longueur': sum(longueur(p) for p in pls),
        'fermees': len(fermees),
        'perimetre': sum(longueur(p) for p in fermees),
        'aire': float(surf.area) if surf is not None else 0.0,
        'emprise': ((min(q[0] for q in pts), min(q[1] for q in pts),
                     max(q[0] for q in pts), max(q[1] for q in pts))
                    if pts else None),
    }
    if surf is not None and not surf.is_empty:
        c = surf.centroid
        m['centre'] = (float(c.x), float(c.y))
    return m


def resume_mesures(m: dict) -> str:
    lignes = [f"{m['traces']} tracé(s), longueur totale "
              f"{m['longueur']:.2f} mm"]
    if m['fermees']:
        lignes.append(f"{m['fermees']} contour(s) fermé(s): périmètre "
                      f"{m['perimetre']:.2f} mm, aire {m['aire']:.2f} mm²")
    if m.get('centre'):
        lignes.append(f"centre de la surface: X {m['centre'][0]:.3f}  "
                      f"Y {m['centre'][1]:.3f}")
    if m['emprise']:
        x0, y0, x1, y1 = m['emprise']
        lignes.append(f"emprise {x1 - x0:.2f} × {y1 - y0:.2f} mm "
                      f"(X {x0:.2f} → {x1:.2f}, Y {y0:.2f} → {y1:.2f})")
    return "\n".join(lignes)


# ── réseaux ─────────────────────────────────────────────────────────

#: une transformation affine (a, b, c, d, e, f):
#: x' = a·x + c·y + e, y' = b·x + d·y + f
Affine = Tuple[float, float, float, float, float, float]


def reseau_rectangulaire(nx: int, ny: int, dx: float, dy: float
                         ) -> List[Affine]:
    """Les copies d'un réseau rectangulaire (l'original exclu)."""
    sortie = []
    for j in range(max(1, int(ny))):
        for i in range(max(1, int(nx))):
            if i == 0 and j == 0:
                continue
            sortie.append((1.0, 0.0, 0.0, 1.0, i * dx, j * dy))
    return sortie


def reseau_polaire(n: int, angle_total: float, cx: float, cy: float,
                   tourner: bool = True, centre_objet: Point = (0.0, 0.0)
                   ) -> List[Affine]:
    """Les copies d'un réseau circulaire autour de (cx, cy), l'original
    exclu. 360° partage le tour en n; un angle plus petit va du premier
    au dernier. `tourner`: les copies tournent avec le réseau (sinon
    elles ne font que se déplacer, comme leur `centre_objet`)."""
    n = max(1, int(n))
    if n < 2:
        return []
    pas = angle_total / n if abs(abs(angle_total) - 360.0) < 1e-9 \
        else angle_total / (n - 1)
    sortie = []
    for k in range(1, n):
        a = math.radians(pas * k)
        c, s = math.cos(a), math.sin(a)
        if tourner:
            sortie.append((c, s, -s, c, cx - c * cx + s * cy,
                           cy - s * cx - c * cy))
        else:
            ox, oy = centre_objet
            nx_ = cx + (ox - cx) * c - (oy - cy) * s
            ny_ = cy + (ox - cx) * s + (oy - cy) * c
            sortie.append((1.0, 0.0, 0.0, 1.0, nx_ - ox, ny_ - oy))
    return sortie


def appliquer(t: Affine, p: Point) -> Point:
    a, b, c, d, e, f = t
    return (a * p[0] + c * p[1] + e, b * p[0] + d * p[1] + f)
