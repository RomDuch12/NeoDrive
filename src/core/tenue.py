"""La tenue de la pièce entre les phases d'un usinage 3D, et le brut réel.

Le BRUT est la pièce agrandie: `cotes` de chaque côté en X/Y, `dessus`
au-dessus, `dessous` en dessous (la prise). Le zéro Z d'une phase est
le DESSUS DU BRUT tel qu'il est posé: les déplacements rapides (1 mm
au-dessus du zéro) restent hors matière, et le surfaçage de la
surépaisseur du dessus se fait de lui-même.

Trois façons de tenir la pièce:

- ÉTAU, PRISE SOUS LA PIÈCE: en phase 1 l'étau serre les `dessous` mm
  du brut sous la pièce; le dessus, les formes et les FLANCS de la pièce
  sont usinés jusqu'à son fond. Retournée (phase 2), la pièce est serrée
  sur ses flancs usinés: palpage du brut (Z et position approchée),
  SURFAÇAGE de la prise, puis palpage précis sur les flancs usinés
  (les zones latérales), puis le dessous. Les côtés, s'il en faut,
  viennent après, pièce couchée.
- SQUELETTE: un cadre (les `largeur_cadre` mm extérieurs du brut, flancs
  usinés pour le palpage) reste autour de la pièce, reliée par des PONTS
  (nombre, largeur, hauteur) ou par une peau; retournée, l'étau serre le
  cadre. On découpe enfin la pièce de son squelette.
- PLAQUE DE REPRISE: phase 0, le dos en haut (brut en étau): surfaçage du
  dos, ses formes, perçage (facultatif) et taraudage M4 aux trous de la
  plaque qui tombent sous la pièce; pause: visser le brut sur la plaque;
  phase 1: palpage, puis tout le dessus et les flancs d'une seule prise.

Ce module ne fait que des données et de la géométrie (numpy, shapely):
le moteur (src/core/usinage3d) s'en sert pour ses phases.
"""

import math
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

MODES = (("etau", "Étau — prise sous la pièce"),
         ("squelette", "Squelette — cadre et ponts"),
         ("plaque", "Plaque de reprise vissée"))
#: le palpage d'une reprise
PALPAGES = (("rectangle", "Rectangle (4 flancs + Z)"),
            ("symetrie_x", "Symétrie en X (+ Z)"),
            ("symetrie_y", "Symétrie en Y (+ Z)"),
            ("coin", "Coin avant gauche (+ Z)"),
            ("z", "Z seul"),
            ("aucun", "Aucun"))
#: les faces latérales du brut qu'on usine pour le palpage: une peau
PEAU_FLANCS = 0.5


def brut_defaut() -> Dict:
    return {'dessus': 1.0, 'dessous': 3.0, 'cotes': 2.0}


def tenue_defaut() -> Dict:
    return {'mode': 'etau',
            # étau: l'outil reste à jeu_mors au-dessus des mors
            'jeu_mors': 1.0,
            # l'étau autocentré ou le mandrin (src/core/serrages.py):
            # None — des mors génériques
            'serrage': None,
            # une reprise serre la pièce (ou le cadre) sur ce bas
            'serrage_reprise': 3.0,
            # le palpage des reprises (phases 2 et suivantes), et en
            # phase 1 si on le veut
            'palpage': 'rectangle', 'palpage_phase1': False,
            'profondeur_palpage': 2.0,
            # squelette
            'largeur_cadre': 6.0, 'ponts': 4, 'largeur_pont': 4.0,
            'hauteur_pont': 2.0, 'peau': 0.0,
            # plaque de reprise
            'plaque': None, 'position': None, 'nombre_vis': 4,
            'filetage': 'M4', 'profondeur_taraudage': 8.0,
            'avant_trou': True, 'profondeur_avant_trou': None,
            'jeu_plaque': 0.1, 'marge_trou': 1.5}


def regler(tenue: Optional[Dict]) -> Dict:
    t = tenue_defaut()
    t.update(tenue or {})
    return t


def boite_brut(modele, brut: Dict) -> Tuple[float, ...]:
    """Le brut, dans le repère de la pièce: (x0, y0, z0, x1, y1, z1)."""
    b = modele.bornes()
    c = float(brut.get('cotes', 0.0))
    return (float(b[0]) - c, float(b[1]) - c,
            float(b[2]) - float(brut.get('dessous', 0.0)),
            float(b[3]) + c, float(b[4]) + c,
            float(b[5]) + float(brut.get('dessus', 0.0)))


# ───────────────────────── les phases d'un mode ─────────────────────────

def phases_du_mode(plan: Dict, mode: str, brut: Dict) -> Tuple[List, List]:
    """Les phases dans l'ordre que la tenue impose, et les faces qu'elle
    rend inaccessibles: (phases, faces en plus des non usinables).

    Étau: le dessus, puis TOUJOURS le dessous s'il y a une prise (elle
    s'enlève par là), puis les côtés. Squelette: dessus, dessous — le
    cadre ferme les côtés. Plaque: le dos d'abord (phase 0), puis le
    dessus et les flancs; les côtés n'ont pas de prise."""
    par_cle = {p['cle']: p for p in plan.get('phases', [])}

    def phase(cle):
        if cle in par_cle:
            return dict(par_cle[cle])
        from src.core.usinage3d import DIRECTIONS
        return {'cle': cle, 'libelle': DIRECTIONS[cle][2], 'faces': []}

    cotes = [p for p in plan.get('phases', []) if p['cle'][0] in 'XY']
    prise = float(brut.get('dessous', 0.0)) > 1e-6
    if mode == 'plaque':
        phases = [phase('Z-'), phase('Z+')]
        perdues = [i for p in cotes for i in p['faces']]
    elif mode == 'squelette':
        phases = [phase('Z+'), phase('Z-')]
        perdues = [i for p in cotes for i in p['faces']]
    else:
        phases = [phase('Z+')]
        if prise or 'Z-' in par_cle:
            phases.append(phase('Z-'))
        phases += [dict(p) for p in cotes]
        perdues = []
    return phases, perdues


def texte_bridage(mode: str, cle: str, rang: int, tenue: Dict,
                  brut: Dict) -> str:
    """Ce qu'on dit à l'opérateur (ASCII: le message part dans le
    programme)."""
    prise = float(brut.get('dessous', 0.0))
    if mode == 'plaque':
        if rang == 0:
            return ("Brut en etau, DOS EN HAUT (serrer %g mm): surfacage "
                    "du dos, percage et taraudage %s pour la plaque"
                    % (max(3.0, prise), tenue.get('filetage', 'M4')))
        nom = (tenue.get('plaque') or {}).get('nom', 'de reprise')
        return ("Visser le brut sur la plaque %s (%d vis %s par le dos), "
                "dessus en haut" % (_ascii(nom), len(tenue.get('_vis') or
                                                     []),
                                    tenue.get('filetage', 'M4')))
    if rang == 0:
        if prise > 0:
            return ("Brut en etau, serrer les %g mm du dessous (la prise "
                    "sous la piece)" % prise)
        return "Brut bride, dessus en Z+"
    if cle == 'Z-':
        if mode == 'squelette':
            return ("Retourner autour de X: etau sur les flancs usines du "
                    "cadre")
        return ("Retourner autour de X: mors doux sur les flancs usines "
                "de la piece; la prise (%g mm) est en haut" % prise)
    from src.core.usinage3d import DIRECTIONS
    autre = 'Y' if cle[0] == 'X' else 'X'
    return ("Coucher la piece (%s): mors doux sur le dessus et le "
            "dessous, butee sur la face %s-" % (DIRECTIONS[cle][2], autre))


def _ascii(texte: str) -> str:
    import unicodedata
    t = unicodedata.normalize('NFKD', str(texte))
    return "".join(c for c in t if ord(c) < 128 and c not in '"')


# ───────────────────────── la géométrie gardée ─────────────────────────

def _boite(x0, x1, y0, y1, z0, z1) -> np.ndarray:
    """Les 12 triangles d'une boîte."""
    P = np.array([(x, y, z) for z in (z0, z1) for y in (y0, y1)
                  for x in (x0, x1)], dtype=float)
    faces = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3),
             (0, 4, 6, 2), (1, 3, 7, 5)]
    tri = []
    for a, b, c, d in faces:
        tri += [(P[a], P[b], P[c]), (P[a], P[c], P[d])]
    return np.array(tri)


def _prisme(poly, z0: float, z1: float) -> np.ndarray:
    """Les triangles d'un prisme droit sur un polygone shapely (trous
    compris): dessus, dessous (triangulation contrainte) et parois."""
    import shapely
    from shapely.geometry import Polygon, MultiPolygon
    geoms = list(poly.geoms) if isinstance(poly, MultiPolygon) else [poly]
    tri = []
    for g in geoms:
        if not isinstance(g, Polygon) or g.area < 1e-6:
            continue
        for t in shapely.constrained_delaunay_triangles(g).geoms:
            c = list(t.exterior.coords)[:3]
            tri.append([(c[0][0], c[0][1], z1), (c[1][0], c[1][1], z1),
                        (c[2][0], c[2][1], z1)])
            tri.append([(c[0][0], c[0][1], z0), (c[2][0], c[2][1], z0),
                        (c[1][0], c[1][1], z0)])
        for anneau in [g.exterior] + list(g.interiors):
            pts = list(anneau.coords)
            for (xa, ya), (xb, yb) in zip(pts[:-1], pts[1:]):
                tri.append([(xa, ya, z0), (xb, yb, z0), (xb, yb, z1)])
                tri.append([(xa, ya, z0), (xb, yb, z1), (xa, ya, z1)])
    return np.array(tri, dtype=float).reshape(-1, 3, 3)


def silhouette_piece(modele):
    """La silhouette de la pièce vue de dessus (shapely), ou None."""
    from shapely.geometry import Polygon
    from src.core import usinage_faces
    pts = usinage_faces.silhouette(modele.triangles)
    if len(pts) < 3:
        return None
    p = Polygon(pts).buffer(0.0)
    return p if not p.is_empty else None


def cadre(boite, largeur: float) -> Tuple[Tuple, Tuple]:
    """(extérieur, intérieur) du cadre d'un squelette: le brut moins la
    peau des flancs usinés, et son ouverture."""
    x0, y0, _z0, x1, y1, _z1 = boite
    e = PEAU_FLANCS
    ext = (x0 + e, y0 + e, x1 - e, y1 - e)
    w = max(0.5, float(largeur))
    inte = (ext[0] + w, ext[1] + w, ext[2] - w, ext[3] - w)
    return ext, inte


def _repartir(n: int, cotes: Sequence[float]) -> List[int]:
    """n ponts sur les 4 côtés, d'abord les plus longs."""
    compte = [0, 0, 0, 0]
    ordre = sorted(range(4), key=lambda k: -cotes[k])
    for k in range(max(0, int(n))):
        compte[ordre[k % 4]] += 1
    return compte


def ponts_squelette(modele, brut: Dict, tenue: Dict) -> List[Dict]:
    """Les ponts du squelette (repère de la pièce): [{'polygone' (plan
    XY, shapely), 'z0', 'z1'}] — du cadre à la pièce, au bas de la
    pièce. Vide hors squelette ou sans pont."""
    t = regler(tenue)
    if t['mode'] != 'squelette' or int(t.get('ponts') or 0) <= 0:
        return []
    from shapely.geometry import box
    b = modele.bornes()
    boite = boite_brut(modele, brut)
    z_bas = float(b[2])
    (_ex0, _ey0, _ex1, _ey1), (ix0, iy0, ix1, iy1) = cadre(
        boite, t['largeur_cadre'])
    if ix1 <= ix0 or iy1 <= iy0:
        return []
    piece = silhouette_piece(modele)
    if piece is None:
        piece = box(float(b[0]), float(b[1]), float(b[3]), float(b[4]))
    ouverture = box(ix0, iy0, ix1, iy1)
    n = int(t.get('ponts') or 0)
    h = max(0.1, float(t.get('hauteur_pont', 2.0)))
    w = max(0.5, float(t.get('largeur_pont', 4.0)))
    # une bande du cadre à la pièce, au milieu de chaque part de côté;
    # ce qui tombe DANS la pièce est déjà de la pièce
    cx, cy = (ix0 + ix1) / 2, (iy0 + iy1) / 2
    compte = _repartir(n, [ix1 - ix0, ix1 - ix0, iy1 - iy0, iy1 - iy0])
    bandes = []
    for k in range(compte[0]):          # Y-
        x = ix0 + (k + 0.5) * (ix1 - ix0) / compte[0]
        bandes.append(box(x - w / 2, iy0 - 0.2, x + w / 2, cy))
    for k in range(compte[1]):          # Y+
        x = ix0 + (k + 0.5) * (ix1 - ix0) / compte[1]
        bandes.append(box(x - w / 2, cy, x + w / 2, iy1 + 0.2))
    for k in range(compte[2]):          # X-
        y = iy0 + (k + 0.5) * (iy1 - iy0) / compte[2]
        bandes.append(box(ix0 - 0.2, y - w / 2, cx, y + w / 2))
    for k in range(compte[3]):          # X+
        y = iy0 + (k + 0.5) * (iy1 - iy0) / compte[3]
        bandes.append(box(cx, y - w / 2, ix1 + 0.2, y + w / 2))
    sortie = []
    bord = box(ix0, iy0, ix1, iy1).exterior.buffer(0.25)
    for bande in bandes:
        reste = bande.intersection(ouverture.buffer(0.2)).difference(piece)
        # le morceau qui touche le cadre, prolongé de 0,3 dans la pièce
        # pour qu'il la tienne
        geoms = list(getattr(reste, 'geoms', [reste]))
        utiles = [g for g in geoms if g.area > 1e-4 and g.intersects(bord)]
        for g in utiles:
            pont = g.union(g.buffer(0.3).intersection(piece.buffer(0.0)))
            pont = pont.intersection(bande)
            if not pont.is_empty:
                sortie.append({'polygone': pont, 'z0': z_bas,
                               'z1': z_bas + h})
    return sortie


def triangles_tenue(modele, brut: Dict, tenue: Dict) -> np.ndarray:
    """Ce que la tenue GARDE de matière (repère de la pièce): le cadre
    du squelette, ses ponts ou sa peau. Vide pour l'étau et la plaque."""
    t = regler(tenue)
    if t['mode'] != 'squelette':
        return np.zeros((0, 3, 3))
    from shapely.geometry import box
    b = modele.bornes()
    boite = boite_brut(modele, brut)
    z_bas, z_haut = float(b[2]), float(b[5])
    (ex0, ey0, ex1, ey1), (ix0, iy0, ix1, iy1) = cadre(
        boite, t['largeur_cadre'])
    if ix1 <= ix0 or iy1 <= iy0:
        return np.zeros((0, 3, 3))
    morceaux = [_prisme(box(ex0, ey0, ex1, ey1).difference(
        box(ix0, iy0, ix1, iy1)), z_bas, z_haut)]
    piece = silhouette_piece(modele)
    if piece is None:
        piece = box(float(b[0]), float(b[1]), float(b[3]), float(b[4]))
    ouverture = box(ix0, iy0, ix1, iy1)
    n = int(t.get('ponts') or 0)
    if n > 0:
        for pont in ponts_squelette(modele, brut, t):
            morceaux.append(_prisme(pont['polygone'], pont['z0'],
                                    pont['z1']))
    elif float(t.get('peau', 0.0)) > 0:
        peau = ouverture.difference(piece.buffer(-0.0))
        morceaux.append(_prisme(peau, z_bas, z_bas + float(t['peau'])))
    morceaux = [m for m in morceaux if len(m)]
    return np.concatenate(morceaux) if morceaux else np.zeros((0, 3, 3))


# ───────────────────────── les obstacles ─────────────────────────

def obstacle_mors(grille, y_min: float, y_max: float, z: float
                  ) -> np.ndarray:
    """Les mors d'un étau qui serre en Y le corps entre y_min et y_max:
    hors de cette bande, l'outil ne descend pas sous z."""
    Y = np.broadcast_to(grille.yc[:, None], (grille.ny, grille.nx))
    return np.where((Y < y_min) | (Y > y_max), float(z), -np.inf)


# ───────────────────────── le palpage ─────────────────────────

def op_palpage(genre: str, largeur_x: float, largeur_y: float,
               profondeur: float, nom: str, mesurer_z: bool = True
               ) -> Optional[Dict]:
    """L'opération de palpage d'une reprise (format operations_generated),
    l'origine au centre du corps palpé, Z sur son dessus (sauf
    `mesurer_z` faux: le Z d'avant reste — un palpage après surfaçage)."""
    if genre in (None, '', 'aucun'):
        return None
    if genre == 'z' and not mesurer_z:
        return None
    p = float(max(0.5, profondeur))
    if genre == 'rectangle':
        return {'operation_type': 'palpage_rectangle', 'name': nom,
                'x': 0.0, 'y': 0.0, 'points': [],
                'params': {'width_x': round(float(largeur_x), 3),
                           'width_y': round(float(largeur_y), 3),
                           'probe_depth': p, 'probe_safe_z': 5.0,
                           'skip_z_measure': not mesurer_z,
                           'skip_z_result': not mesurer_z}}
    if genre in ('symetrie_x', 'symetrie_y'):
        from src.operations.palpage_symetrie import AXE_X, AXE_Y
        axe_x = genre == 'symetrie_x'
        return {'operation_type': 'palpage_symetrie', 'name': nom,
                'x': 0.0, 'y': 0.0, 'points': [],
                'params': {'axis': AXE_X if axe_x else AXE_Y,
                           'width': round(float(largeur_x if axe_x
                                                else largeur_y), 3),
                           'measure_z_offset': -p,
                           'skip_z_measure': not mesurer_z,
                           'skip_z_measure_result': not mesurer_z}}
    if genre == 'coin':
        return {'operation_type': 'palpage_coin', 'name': nom,
                'x': round(-float(largeur_x) / 2, 3),
                'y': round(-float(largeur_y) / 2, 3), 'points': [],
                'params': {'probe_depth': p,
                           'skip_z_measure': not mesurer_z,
                           'origin_x_shift': round(float(largeur_x) / 2, 3),
                           'origin_y_shift': round(float(largeur_y) / 2, 3)}}
    if genre == 'z':
        return {'operation_type': 'palpage_z', 'name': nom, 'x': 0.0,
                'y': 0.0, 'points': [], 'params': {}}
    return None


# ───────────────────────── la plaque de reprise ─────────────────────────

def cartes_dos(modele, pas: float = None):
    """Pour placer les vis: la grille (repère pièce), le dessus et le
    dessous de la pièce par case."""
    from src.core.usinage3d import Grille, carte_piece
    T = np.asarray(modele.triangles, dtype=float)
    b = modele.bornes()
    g = Grille(float(b[0]) - 1, float(b[3]) + 1, float(b[1]) - 1,
               float(b[4]) + 1, pas=pas or max(0.1, min(
                   0.5, math.sqrt((b[3] - b[0]) * (b[4] - b[1]) / 40000.0))))
    fond = float(b[2]) - 1.0
    dessus = carte_piece(T, g, fond)
    Tm = T.copy()
    Tm[..., 2] = -Tm[..., 2]
    dessous = -carte_piece(Tm, g, -float(b[5]) - 1.0)
    return g, dessus, dessous, float(b[2])


def cases_vissables(modele, tenue: Dict, pas: float = None):
    """Où une vis peut entrer par le dos: le dos à plat au fond de la
    pièce, assez d'épaisseur pour le filet, assez loin du bord. Rend
    (grille, masque)."""
    from scipy.ndimage import distance_transform_edt
    t = regler(tenue)
    g, dessus, dessous, z_bas = cartes_dos(modele, pas)
    prof = float(t['profondeur_taraudage']) + 1.0
    from src.operations.taraudage import THREAD_DIAMETER
    r = THREAD_DIAMETER.get(t['filetage'], 4.0) / 2.0
    ok = ((dessous <= z_bas + 0.02) & (dessus - z_bas >= prof)
          & np.isfinite(dessous))
    dist = distance_transform_edt(ok) * g.pas
    return g, dist >= r + float(t['marge_trou'])


def placer_sur_plaque(modele, brut: Dict, tenue: Dict, plaque: Dict,
                      pas_recherche: float = 0.5) -> Dict:
    """Le brut posé sur la plaque: où (le centre du brut dans le repère
    de la plaque) et quelles vis. Le brut doit tenir sur la plaque; on
    garde la position qui donne le plus de vis (jusqu'à nombre_vis),
    les plus écartées. Rend {'position', 'vis' (repère pièce),
    'trous' (repère plaque), 'n_possibles'}."""
    from shapely.geometry import Polygon, box
    from src.core import plaques as pl
    t = regler(tenue)
    trous = np.asarray(plaque.get('trous') or [], dtype=float).reshape(-1, 2)
    vide = {'position': None, 'vis': [], 'trous': [], 'n_possibles': 0}
    if not len(trous):
        return vide
    g, ok = cases_vissables(modele, t)
    x0, y0, _z0, x1, y1, _z1 = boite_brut(modele, brut)
    cxb, cyb = (x0 + x1) / 2, (y0 + y1) / 2
    lx, ly = x1 - x0, y1 - y0
    contour = Polygon(pl.contour(plaque)).buffer(0.0)
    mn = np.array(contour.bounds[:2])
    mxp = np.array(contour.bounds[2:])
    centre = (mn + mxp) / 2
    if t.get('position') is not None:
        candidats = [np.asarray(t['position'], dtype=float)]
    else:
        pasr = float(pas_recherche)
        dx = np.arange(-25.0, 25.0 + 1e-9, pasr)
        candidats = [centre + np.array([a, b]) for a in dx for b in dx]
    meilleur, score = None, None
    posable = None
    for pos in candidats:
        if not contour.contains(box(pos[0] - lx / 2, pos[1] - ly / 2,
                                    pos[0] + lx / 2, pos[1] + ly / 2)):
            continue
        if posable is None or np.hypot(*(pos - centre)) < np.hypot(
                *(posable - centre)):
            posable = pos
        # les trous dans le repère de la pièce
        p = trous - pos + np.array([cxb, cyb])
        j = np.floor((p[:, 1] - g.y0) / g.pas).astype(int)
        i = np.floor((p[:, 0] - g.x0) / g.pas).astype(int)
        dedans = (i >= 0) & (i < g.nx) & (j >= 0) & (j < g.ny)
        bons = np.zeros(len(p), dtype=bool)
        bons[dedans] = ok[j[dedans], i[dedans]]
        n = int(bons.sum())
        if n == 0:
            continue
        choix = _ecartes(p[bons], int(t['nombre_vis']))
        etendue = _aire_enveloppe(choix)
        s = (min(n, int(t['nombre_vis'])), etendue,
             -float(np.hypot(*(pos - centre))))
        if score is None or s > score:
            score = s
            meilleur = (pos, choix, n)
    if meilleur is None:
        # aucune vis: le brut reste posé au milieu (l'aperçu montre la
        # plaque et ses trous)
        if posable is not None:
            vide = dict(vide, position=[round(float(posable[0]), 3),
                                        round(float(posable[1]), 3)])
        return vide
    pos, choix, n = meilleur
    return {'position': [round(float(pos[0]), 3), round(float(pos[1]), 3)],
            'vis': [[round(float(x), 4), round(float(y), 4)]
                    for x, y in choix],
            'trous': [[round(float(x - cxb + pos[0]), 4),
                       round(float(y - cyb + pos[1]), 4)] for x, y in choix],
            'n_possibles': n}


def trous_vissables(modele, brut: Dict, tenue: Dict, plaque: Dict,
                    position) -> List[bool]:
    """Pour chaque trou de la plaque (le brut centré en `position`): une
    vis peut-elle y entrer par le dos de la pièce?"""
    t = regler(tenue)
    trous = np.asarray(plaque.get('trous') or [], dtype=float).reshape(-1, 2)
    if not len(trous) or position is None:
        return [False] * len(trous)
    g, ok = cases_vissables(modele, t)
    x0, y0, _z0, x1, y1, _z1 = boite_brut(modele, brut)
    p = trous - np.asarray(position, dtype=float) + np.array(
        [(x0 + x1) / 2, (y0 + y1) / 2])
    j = np.floor((p[:, 1] - g.y0) / g.pas).astype(int)
    i = np.floor((p[:, 0] - g.x0) / g.pas).astype(int)
    dedans = (i >= 0) & (i < g.nx) & (j >= 0) & (j < g.ny)
    bons = np.zeros(len(p), dtype=bool)
    bons[dedans] = ok[j[dedans], i[dedans]]
    return [bool(b) for b in bons]


def vis_a_la_main(modele, brut: Dict, tenue: Dict, plaque: Dict, position,
                  trous_choisis) -> Dict:
    """Le placement que l'opérateur a choisi: le brut centré en
    `position` sur la plaque, une vis dans chacun des `trous_choisis`
    (repère plaque) où elle peut entrer. Rend {'position', 'vis',
    'trous', 'n_possibles', 'refuses' (trous choisis sans dos
    vissable), 'manuel': True}."""
    x0, y0, _z0, x1, y1, _z1 = boite_brut(modele, brut)
    cxb, cyb = (x0 + x1) / 2, (y0 + y1) / 2
    trous = [list(map(float, tr)) for tr in plaque.get('trous') or []]
    vissables = trous_vissables(modele, brut, tenue, plaque, position)
    choisis = {(round(float(a), 3), round(float(b), 3))
               for a, b in trous_choisis or []}
    pris, refuses = [], []
    for (hx, hy), ok in zip(trous, vissables):
        if (round(hx, 3), round(hy, 3)) not in choisis:
            continue
        (pris if ok else refuses).append((hx, hy))
    px, py = (float(v) for v in position)
    return {'position': [round(px, 3), round(py, 3)],
            'vis': [[round(hx - px + cxb, 4), round(hy - py + cyb, 4)]
                    for hx, hy in pris],
            'trous': [[round(hx, 4), round(hy, 4)] for hx, hy in pris],
            'n_possibles': int(sum(vissables)),
            'refuses': [[round(hx, 4), round(hy, 4)] for hx, hy in refuses],
            'manuel': True}


def _ecartes(points, n: int):
    """n points les plus écartés (le plus loin du centre d'abord, puis
    le plus loin des déjà pris)."""
    pts = np.asarray(points, dtype=float)
    if len(pts) <= n:
        return pts
    c = pts.mean(axis=0)
    pris = [int(np.argmax(np.hypot(*(pts - c).T)))]
    while len(pris) < n:
        d = np.min(np.hypot(pts[:, None, 0] - pts[None, pris, 0],
                            pts[:, None, 1] - pts[None, pris, 1]), axis=1)
        d[pris] = -1
        pris.append(int(np.argmax(d)))
    return pts[pris]


def _aire_enveloppe(points) -> float:
    pts = np.asarray(points, dtype=float)
    if len(pts) < 3:
        return float(np.ptp(pts[:, 0]) + np.ptp(pts[:, 1])) if len(pts) \
            else 0.0
    from shapely.geometry import MultiPoint
    return float(MultiPoint([tuple(p) for p in pts]).convex_hull.area)
