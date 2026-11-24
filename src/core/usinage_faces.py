"""Des faces du STEP aux usinages 2D.

On sélectionne des faces de la pièce dans la vue 3D; ce module dit ce
qu'elles sont et propose les opérations NeoDrive qui les font:

- un CYLINDRE vertical creux (un trou; ses deux demi-faces n'en font
  qu'un): perçage au foret du Ø, perçage fraisé (DrillMilling), poche
  cercle, découpe intérieure s'il traverse; plusieurs trous de même Ø
  et même profondeur: UNE opération, plusieurs points;
- un cylindre vertical plein et complet (un bossage — un congé, quart
  de cylindre, n'en est pas un): découpe extérieure;
- un PLAN horizontal tourné vers le haut, sous le dessus (un fond de
  poche): poche cercle ou rectangle si son contour en est un, sinon un
  évidement 2D5 de son contour (ses trous sont des îlots), à sa cote;
- le dessus ou le dessous de la pièce: la découpe du contour
  extérieur, sur toute l'épaisseur (rectangle ou cercle).

Les coordonnées sont celles de la MACHINE: celles du modèle décalées
comme le dessin (`decalage`), le dessus de la pièce en Z 0 (`haut`).
L'outil est choisi dans la bibliothèque: foret du Ø, sinon la plus
grosse fraise cylindrique qui passe et dont la longueur utile suffit.
"""

import math
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

#: un axe à moins de ceci de la verticale est vertical (cosinus)
_VERTICAL = 0.995
#: deux cotes ou deux Ø plus proches que ceci sont les mêmes (mm)
_EPS = 0.02
#: un cylindre couvert à ce point de son tour est complet (bossage)
_COMPLET = 0.93
#: débouchage sous un trou qui traverse (mm)
DEBOUCHAGE = 0.3
#: une face plus petite que ceci (mm²) est une miette du maillage CAO
AIRE_MIN = 0.5
#: un trou plus petit que ceci (Ø mm) ne s'usine pas
DIAMETRE_MIN = 0.5


def _xy(points, dx, dy):
    return [(round(float(p[0]) + dx, 4), round(float(p[1]) + dy, 4))
            for p in points]


def _aire_xy(points) -> float:
    p = np.asarray(points, dtype=float)
    if len(p) < 3:
        return 0.0
    x, y = p[:, 0], p[:, 1]
    return abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def _ilot(boucle, z: float, triangles) -> bool:
    """La boucle intérieure d'un fond à la cote z est-elle un îlot (la
    matière monte au-dessus d'elle)? Sans le maillage, on le suppose."""
    if triangles is None or not len(triangles):
        return True
    try:
        from shapely.geometry import Polygon
        from src.io.vecteur.step3d import dans_la_matiere
        poly = Polygon([(float(p[0]), float(p[1])) for p in boucle])
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty:
            return True
        q = poly.representative_point()
        return bool(dans_la_matiere(triangles,
                                    [(q.x, q.y, z + 0.05)])[0])
    except Exception:
        return True


def _cylindres_par_cotes(cylindres, triangles, haut: float) -> List[Dict]:
    """Les parois d'un même axe et d'un même diamètre, regroupées par
    cotes: un élément par suite de parois qui se touchent en Z (ou que
    seul du vide sépare: les deux parois d'un tube). Deux trous borgnes
    de même diamètre, un par face, devenaient UN trou débouchant — avec
    le maillage, la matière entre eux les sépare, et celui qu'elle ferme
    par le haut (il s'usine par l'autre face) n'est pas proposé."""
    from src.io.vecteur.maillage import groupes_en_z
    sortie = []
    for cyl in cylindres:
        morceaux = cyl['morceaux']
        dans = None
        if cyl['genre'] == 'trou' and triangles is not None \
                and len(triangles):
            from src.io.vecteur.step3d import dans_la_matiere
            x, y = cyl['axe']
            e = max(0.01, min(0.2, 0.05 * cyl['diametre']))

            def dans(z, x=x, y=y, e=e):
                # (trois sondes près de l'axe: un rayon qui rase une
                # arête ne décide pas seul)
                sondes = [(x, y, z), (x + e, y + 0.3 * e, z),
                          (x - 0.4 * e, y - e, z)]
                return int(dans_la_matiere(triangles, sondes).sum()) >= 2
        for g in groupes_en_z(morceaux, dans):
            z_min = min(morceaux[k][0] for k in g)
            z_max = max(morceaux[k][1] for k in g)
            if dans is not None and z_max < haut - _EPS \
                    and dans(z_max + 0.05):
                continue                 # fermé par le haut
            sortie.append({
                'genre': cyl['genre'], 'x': cyl['x'], 'y': cyl['y'],
                'diametre': cyl['diametre'], 'z_min': z_min, 'z_max': z_max,
                'aire': sum(morceaux[k][2] for k in g),
                'faces': [morceaux[k][3] for k in g]})
    return sortie


def elements(faces: Sequence[Dict], decalage=(0.0, 0.0),
             haut: float = 0.0, bas: Optional[float] = None,
             triangles=None) -> List[Dict]:
    """Les éléments d'usinage d'une sélection de faces (infos de
    `step3d.info_face`, en coordonnées du modèle): [{'genre': 'trou'|
    'bossage'|'fond'|'contour', 'faces': [index], …}] — en machine.
    `triangles` (le maillage du modèle) départage les boucles
    intérieures d'un fond: îlot (la matière monte) ou trou (la poche
    passe dessus)."""
    dx, dy = float(decalage[0]), float(decalage[1])
    haut = float(haut)
    bas = float(bas) if bas is not None else None
    epaisseur = (haut - bas) if bas is not None else None
    sortie: List[Dict] = []
    cylindres: Dict[Tuple, Dict] = {}
    fonds: Dict[float, Dict] = {}
    tour_piece = None
    for f in faces:
        genre = f.get('genre')
        if float(f.get('aire', 1.0)) < AIRE_MIN:
            continue
        if genre == 'cylindre':
            axe = np.asarray(f.get('axe', (0, 0, 1)), dtype=float)
            if abs(axe[2]) < _VERTICAL:
                continue
            c = np.asarray(f['centre'], dtype=float)
            d = 2.0 * float(f['rayon'])
            if d < DIAMETRE_MIN:
                continue
            cle = (round(c[0] / _EPS), round(c[1] / _EPS), round(d / _EPS),
                   bool(f.get('creux')))
            # (ses parois: regroupées après la boucle, par cotes)
            el = cylindres.setdefault(cle, {
                'genre': 'trou' if f.get('creux') else 'bossage',
                'x': round(float(c[0]) + dx, 4),
                'y': round(float(c[1]) + dy, 4),
                'diametre': round(d, 4), 'axe': (float(c[0]), float(c[1])),
                'morceaux': []})
            el['morceaux'].append((float(f['z_min']), float(f['z_max']),
                                   float(f.get('aire', 0.0)),
                                   f.get('index')))
        elif genre == 'plan':
            n = np.asarray(f.get('normale', (0, 0, 1)), dtype=float)
            if abs(n[2]) < _VERTICAL:
                continue
            boucles = f.get('boucles') or []
            if not boucles:
                continue
            # la boucle extérieure: la plus grande en XY (les CAO ne
            # marquent pas toutes FACE_OUTER_BOUND)
            ext = [max((p for p, _e in boucles), key=_aire_xy)]
            exterieur = _xy(ext[0], dx, dy)
            z = float(f['z_max'])
            # le contour du fond et ses vrais îlots seulement
            contours = [exterieur] + [
                _xy(p, dx, dy) for p, _e in boucles
                if p is not ext[0] and n[2] > 0 and _ilot(p, z, triangles)]
            pz = round(haut - z, 4)
            if n[2] > 0 and pz > _EPS:
                # un fond de poche; ceux d'une même cote vont ensemble
                el = fonds.setdefault(round(pz, 2), {
                    'genre': 'fond', 'profondeur': pz, 'contours': [],
                    'exterieurs': [], 'faces': []})
                el['contours'] += contours
                el['exterieurs'].append(exterieur)
                el['faces'].append(f.get('index'))
            elif (n[2] > 0 and pz <= _EPS) or (
                    n[2] < 0 and bas is not None and z <= bas + _EPS):
                # le dessus, ou le dessous de la pièce: son tour. Une
                # face tournée vers le bas AILLEURS (une contre-
                # dépouille) ne s'usine pas par le dessus.
                prof = epaisseur if epaisseur is not None else pz
                aire = float(f.get('aire', 0.0))
                if prof and prof > _EPS and (
                        tour_piece is None or aire > tour_piece['aire']):
                    tour_piece = {'genre': 'contour',
                                  'profondeur': round(prof, 4),
                                  'exterieur': exterieur, 'aire': aire,
                                  'faces': [f.get('index')]}
    sortie += list(fonds.values())
    if tour_piece is not None:
        del tour_piece['aire']
        # le tour de la pièce, c'est sa SILHOUETTE vue de dessus: la
        # face de dessous peut être plus petite (un chanfrein, un
        # congé) — la suivre, ce serait mordre le flanc
        if triangles is not None and len(triangles):
            tour = silhouette(triangles)
            if tour:
                tour_piece['exterieur'] = _xy(tour, dx, dy)
        sortie.append(tour_piece)
    for el in _cylindres_par_cotes(cylindres.values(), triangles, haut):
        h = max(1e-9, el['z_max'] - el['z_min'])
        tour = el['aire'] / (math.pi * el['diametre'] * h)
        el['profondeur'] = round(haut - el['z_min'], 4)
        el['traversant'] = bool(bas is not None
                                and el['z_min'] <= bas + _EPS)
        if el['genre'] == 'bossage' and tour < _COMPLET:
            continue                     # un congé, pas un bossage
        if el['genre'] == 'trou' and tour < 0.45:
            continue                     # un arrondi creux, pas un trou
        del el['aire']
        sortie.append(el)
    return sortie


def silhouette(triangles, pas: float = None) -> List[Tuple[float, float]]:
    """Le contour de la pièce vue de dessus (coordonnées du modèle): la
    plus grande courbe fermée de sa carte de hauteurs, simplifiée."""
    try:
        import contourpy
        from src.core import usinage3d
        T = np.asarray(triangles, dtype=float)
        mn, mx = T.reshape(-1, 3).min(axis=0), T.reshape(-1, 3).max(axis=0)
        if pas is None:
            pas = max(0.02, math.sqrt((mx[0] - mn[0]) * (mx[1] - mn[1])
                                      / 250000.0))
        marge = 3 * pas
        g = usinage3d.Grille(mn[0] - marge, mx[0] + marge, mn[1] - marge,
                             mx[1] + marge, pas=pas)
        fond = float(mn[2]) - 1.0
        dedans = (usinage3d.carte_piece(T, g, fond) > fond + 1e-9)
        lignes = contourpy.contour_generator(
            g.xc, g.yc, dedans.astype(float),
            line_type="Separate").lines(0.5)
        if not lignes:
            return []
        tour = max(lignes, key=lambda l: _aire_xy(l))
        from shapely.geometry import Polygon
        poly = Polygon(tour).buffer(0.0)
        # la courbe de niveau passe entre deux centres de cases: on
        # rend la demi-case, côté matière (prudent)
        poly = poly.buffer(pas / 2.0, quad_segs=8).simplify(pas / 4.0)
        geom = max(getattr(poly, 'geoms', [poly]), key=lambda p: p.area)
        return [(round(x, 4), round(y, 4))
                for x, y in geom.exterior.coords]
    except Exception:
        return []


def forme_du_contour(points) -> Optional[Tuple]:
    """('cercle', d, x, y) ou ('rect', largeur, hauteur, rayon, x, y)
    si le contour en est un, sinon None."""
    pts = np.asarray(points, dtype=float)
    if len(pts) < 4:
        return None
    c = pts.mean(axis=0)
    r = np.hypot(pts[:, 0] - c[0], pts[:, 1] - c[1])
    # un cercle: assez de points, à égale distance du centre, et l'aire
    # d'un disque (les 4 coins d'un rectangle sont équidistants aussi)
    if len(pts) >= 8 and r.mean() > 1e-6 \
            and (r.max() - r.min()) < 0.01 * r.mean() + 1e-4 \
            and abs(_aire_xy(pts) / 2 - math.pi * r.mean() ** 2) \
            < 0.03 * math.pi * r.mean() ** 2:
        return ('cercle', round(2 * float(r.mean()), 4),
                round(float(c[0]), 4), round(float(c[1]), 4))
    try:
        from src.gui.dxf.dxf_canvas import DxfCanvas
        rect = DxfCanvas.rectangle_arrondi([tuple(p) for p in pts])
    except Exception:
        rect = None
    if rect:
        x0, y0, x1, y1, rayon = rect
        return ('rect', round(x1 - x0, 4), round(y1 - y0, 4),
                round(float(rayon or 0.0), 4), round((x0 + x1) / 2, 4),
                round((y0 + y1) / 2, 4))
    return None


# ── les outils ──

def _longueur_utile(t) -> float:
    g = getattr(t, 'geometry', None) or {}
    for cle in ('ShoulderLength', 'FluteLength'):
        try:
            v = float(g.get(cle) or 0)
        except (TypeError, ValueError):
            v = 0.0
        if v > 0:
            return v
    return 0.0


def _fraises(bibliotheque):
    for tid, t in (getattr(bibliotheque, 'tools', None) or {}).items():
        nom = str(getattr(t, 'name', '') or '')
        try:
            d = float(getattr(t, 'diameter', 0) or 0)
        except (TypeError, ValueError):
            d = 0.0
        if d > 0 and nom.lower().startswith('cyl'):
            yield tid, t, d


def foret(bibliotheque, diametre: float) -> Optional[str]:
    """L'id du foret de ce Ø (à 0,05 près), ou None."""
    for tid, t in (getattr(bibliotheque, 'tools', None) or {}).items():
        nom = str(getattr(t, 'name', '') or '').lower()
        try:
            d = float(getattr(t, 'diameter', 0) or 0)
        except (TypeError, ValueError):
            continue
        if nom.startswith('foret') and abs(d - diametre) <= 0.05:
            return tid
    return None


def fraise(bibliotheque, largeur_max: float,
           profondeur: float = 0.0) -> Optional[str]:
    """La plus grosse fraise cylindrique de Ø ≤ `largeur_max` dont la
    longueur utile atteint `profondeur` (sinon la plus longue de
    celles qui passent)."""
    candidates = [(d, _longueur_utile(t), tid)
                  for tid, t, d in _fraises(bibliotheque)
                  if d <= largeur_max + 1e-9]
    if not candidates:
        return None
    assez = [c for c in candidates if c[1] >= profondeur - 1e-9
             or c[1] == 0.0]
    if assez:
        return max(assez, key=lambda c: (c[0], -c[1]))[2]
    return max(candidates, key=lambda c: (c[1], c[0]))[2]


def _largeur_utile(contours) -> float:
    """Deux fois le rayon du plus grand cercle inscrit (shapely)."""
    try:
        from src.core import vcarve
        forme = vcarve.zone(contours)
        if forme is None:
            return 0.0
        bas, haut = 0.0, max(forme.bounds[2] - forme.bounds[0],
                              forme.bounds[3] - forme.bounds[1])
        for _ in range(18):
            m = (bas + haut) / 2
            if forme.buffer(-m).is_empty:
                haut = m
            else:
                bas = m
        return 2 * bas
    except Exception:
        return 0.0


# ── les propositions ──

def _op(genre, nom, params, points, tool_id=None):
    x, y = (points[0]['x'], points[0]['y']) if points else (0.0, 0.0)
    return {'operation_type': genre, 'name': nom, 'x': x, 'y': y,
            'params': params, 'points': [dict(p) for p in points],
            'tool_id': tool_id or ''}


def propositions(faces: Sequence[Dict], bibliotheque=None,
                 decalage=(0.0, 0.0), haut: float = 0.0,
                 bas: Optional[float] = None,
                 triangles=None) -> List[Tuple[str, List]]:
    """[(libellé, [opération])] pour la sélection: chaque libellé est
    un choix du menu « Usiner la sélection », ses opérations au format
    de `operations_generated` (plus 'tool_id')."""
    els = elements(faces, decalage, haut, bas, triangles)
    choix: List[Tuple[str, List]] = []
    # les trous, par Ø et profondeur
    trous: Dict[Tuple, List[Dict]] = {}
    for el in els:
        if el['genre'] == 'trou':
            trous.setdefault((el['diametre'], el['profondeur'],
                              el['traversant']), []).append(el)
    for (d, p, traverse), groupe in sorted(trous.items()):
        pts = [{'x': e['x'], 'y': e['y']} for e in groupe]
        n = f" ×{len(pts)}" if len(pts) > 1 else ""
        prof = round(p + (DEBOUCHAGE if traverse else 0.0), 4)
        quoi = f"Ø{d:g}{n}, {'débouchant' if traverse else f'prof. {p:g}'}"
        f_id = foret(bibliotheque, d)
        choix.append((f"Perçage foret {quoi}" + (
            "" if f_id else " (pas de foret de ce Ø)"),
            [_op('percage_foret', f"Perçage Ø{d:g}", {'depth': prof},
                 pts, f_id)]))
        m_id = fraise(bibliotheque, 0.8 * d, prof)
        choix.append((f"Perçage fraisé {quoi}",
                      [_op('percage_fraise', f"Perçage fraisé Ø{d:g}",
                           {'diameter': d, 'depth': prof}, pts, m_id)]))
        choix.append((f"Poche cercle {quoi}",
                      [_op('poche_cercle', f"Poche Ø{d:g}",
                           {'diameter': d, 'depth': prof}, pts, m_id)]))
    # les bossages
    for el in els:
        if el['genre'] != 'bossage':
            continue
        p = el['profondeur']
        choix.append((f"Découpe extérieure Ø{el['diametre']:g} "
                      f"(prof. {p:g})",
                      [_op('decoupe_cercle', f"Bossage Ø{el['diametre']:g}",
                           {'diameter': el['diametre'], 'side': 'Outside',
                            'depth': p},
                           [{'x': el['x'], 'y': el['y']}],
                           fraise(bibliotheque, 6.0, p))]))
    # les fonds de poche
    for el in els:
        if el['genre'] != 'fond':
            continue
        p = el['profondeur']
        largeur = _largeur_utile(el['contours'])
        m_id = fraise(bibliotheque, max(0.5, 0.9 * largeur), p)
        forme = forme_du_contour(el['exterieurs'][0]) \
            if len(el['contours']) == 1 else None
        if forme and forme[0] == 'cercle':
            _g, d, x, y = forme
            choix.append((f"Poche cercle Ø{d:g} à {p:g} mm",
                          [_op('poche_cercle', f"Poche Ø{d:g}",
                               {'diameter': d, 'depth': p},
                               [{'x': x, 'y': y}], m_id)]))
        elif forme and forme[0] == 'rect':
            _g, w, h, r, x, y = forme
            choix.append((f"Poche rectangle {w:g}×{h:g} à {p:g} mm",
                          [_op('poche_rectangle', f"Poche {w:g}×{h:g}",
                               {'width_x': w, 'width_y': h,
                                'corner_radius': r, 'depth': p},
                               [{'x': x, 'y': y}], m_id)]))
        n_faces = len(el['faces'])
        ilots = len(el['contours']) - len(el['exterieurs'])
        ilots = (f", {n_faces} faces" if n_faces > 1 else "") + (
            f", {ilots} îlot(s)" if ilots > 0 else "")
        choix.append((f"Évidement du fond à {p:g} mm{ilots}",
                      [_op('evidement_2d5', f"Évidement à {p:g}",
                           {'contours': [list(map(list, c))
                                         for c in el['contours']],
                            'profondeur': p, 'mode': 'Creux',
                            'profondeur_passe': 1.0},
                           [], m_id)]))
    # le contour extérieur de la pièce
    for el in els:
        if el['genre'] != 'contour':
            continue
        p = round(el['profondeur'] + DEBOUCHAGE, 4)
        forme = forme_du_contour(el['exterieur'])
        m_id = fraise(bibliotheque, 6.0, p)
        if forme and forme[0] == 'rect':
            _g, w, h, r, x, y = forme
            choix.append((f"Découpe du contour {w:g}×{h:g} (épaisseur)",
                          [_op('decoupe_rectangle', f"Découpe {w:g}×{h:g}",
                               {'width_x': w, 'width_y': h,
                                'corner_radius': r, 'side': 'Outside',
                                'depth': p},
                               [{'x': x, 'y': y}], m_id)]))
        elif forme and forme[0] == 'cercle':
            _g, d, x, y = forme
            choix.append((f"Découpe du contour Ø{d:g} (épaisseur)",
                          [_op('decoupe_cercle', f"Découpe Ø{d:g}",
                               {'diameter': d, 'side': 'Outside',
                                'depth': p},
                               [{'x': x, 'y': y}], m_id)]))
        # tout contour, libre ou non: le détourage au tracé, le centre de
        # l'outil à un rayon du bord (offset exact, coins arrondis)
        d_outil = _diametre(bibliotheque, m_id) or 6.0
        chemin = decaler(el['exterieur'], d_outil / 2.0)
        if chemin:
            choix.append((f"Détourage du contour (tracé, épaisseur "
                          f"{el['profondeur']:g})",
                          [_op('trace', "Détourage",
                               {'shape': 'Dessin', 'closed': True,
                                'path_points': chemin,
                                'offset_side': 'Aucun', 'depth': p,
                                'infeed_z': round(max(0.5, d_outil / 2.0),
                                                  3)},
                               [], m_id)]))
    return choix


def _diametre(bibliotheque, tool_id) -> float:
    t = (getattr(bibliotheque, 'tools', None) or {}).get(tool_id)
    try:
        return float(getattr(t, 'diameter', 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def decaler(contour, distance: float) -> List[List[float]]:
    """Le contour décalé vers l'extérieur de `distance` (coins
    arrondis), fermé, en [[x, y]]; [] si la forme est dégénérée."""
    try:
        from shapely.geometry import Polygon
        poly = Polygon([tuple(p) for p in contour])
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty:
            return []
        dec = poly.buffer(distance, quad_segs=16, join_style=1)
        dec = dec.simplify(0.005)
        geom = max(getattr(dec, 'geoms', [dec]), key=lambda g: g.area)
        return [[round(x, 4), round(y, 4)] for x, y in
                geom.exterior.coords]
    except Exception:
        return []


def decrire(faces: Sequence[Dict], decalage=(0.0, 0.0), haut: float = 0.0,
            bas: Optional[float] = None, triangles=None) -> str:
    """Une ligne pour la sélection: « 2 faces: trou Ø8 prof. 6 · … »."""
    els = elements(faces, decalage, haut, bas, triangles)
    morceaux = []
    for el in els:
        if el['genre'] in ('trou', 'bossage'):
            morceaux.append(
                f"{el['genre']} Ø{el['diametre']:g} "
                + ("débouchant" if el.get('traversant')
                   else f"prof. {el['profondeur']:g}"))
        elif el['genre'] == 'fond':
            morceaux.append(f"fond à {el['profondeur']:g} mm")
        elif el['genre'] == 'contour':
            morceaux.append(f"contour de la pièce, épaisseur "
                            f"{el['profondeur']:g}")
    autres = len(faces) - sum(len(el['faces']) for el in els)
    if autres > 0:
        morceaux.append(f"{autres} autre(s) face(s)")
    return f"{len(faces)} face(s): " + (" · ".join(morceaux) or "—")
