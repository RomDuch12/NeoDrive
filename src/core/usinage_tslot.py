"""Les contre-dépouilles à la fraise en T.

Une face qui regarde VERS LE BAS sous un surplomb (le plafond d'une
rainure dans une paroi, le dessous d'une collerette) n'est atteinte par
aucune fraise droite en 3 axes: elle est en rouge. Une fraise en T — un
disque d'épaisseur h au bout d'un col fin — y entre par le côté: son col
descend dans ce qui est OUVERT au-dessus, son disque passe sous le
surplomb.

Pour chaque plafond (et le sol qui lui fait face), à chaque niveau du
disque (du sol jusqu'au plafond, par pas ≤ son épaisseur):

- le col (et la queue au-dessus) reste là où rien ne dépasse le dessus du
  disque — la carte de hauteurs de la pièce le dit;
- le disque ne mord pas la pièce dans sa tranche [z, z + h] — les
  sections de la pièce le disent;
- le parcours est le bord de ce qui reste permis, du côté du plafond: le
  disque y va aussi loin sous le surplomb qu'il le peut; l'outil descend
  là où le disque passe à la verticale, fait le tour, remonte.

Les séquences sortent comme celles du moteur 3D (src/core/usinage3d):
dans le repère de la phase du dessus.
"""

import math
from typing import Dict, List, Optional, Sequence

import numpy as np

#: le jeu (mm) gardé autour du col et du disque
JEU = 0.1
#: un niveau de disque recouvre le précédent de cette part
RECOUVREMENT = 0.2


# ───────────────────────── la géométrie ─────────────────────────

def section(triangles, z: float):
    """La section de la pièce à la cote z (shapely, plan XY)."""
    from shapely.geometry import LineString, Polygon
    from shapely.ops import polygonize, unary_union
    T = np.asarray(triangles, dtype=float)
    Z = T[:, :, 2] - float(z)
    Z = np.where(np.abs(Z) < 1e-9, 1e-9, Z)
    sel = (Z.min(axis=1) < 0) & (Z.max(axis=1) > 0)
    segs = []
    for tri, zz in zip(T[sel], Z[sel]):
        pts = []
        for a, b in ((0, 1), (1, 2), (2, 0)):
            if (zz[a] < 0) != (zz[b] < 0):
                t = zz[a] / (zz[a] - zz[b])
                p = tri[a] + t * (tri[b] - tri[a])
                pts.append((round(float(p[0]), 6), round(float(p[1]), 6)))
        if len(pts) == 2 and pts[0] != pts[1]:
            segs.append(LineString(pts))
    if not segs:
        return Polygon()
    morceaux = sorted(polygonize(unary_union(segs)), key=lambda p: -p.area)
    sortie = Polygon()
    for p in morceaux:                      # pair-impair: les trous
        sortie = sortie.symmetric_difference(p)
    return sortie.buffer(0)


def zone_basse(grille, H, z_max: float):
    """Les cases dont la pièce ne dépasse pas z_max (shapely): là où un
    col peut descendre jusqu'à z_max."""
    import contourpy
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    bas = float(np.min(H)) - 1.0
    gen = contourpy.contour_generator(grille.xc, grille.yc, H,
                                      fill_type="OuterOffset")
    points, offsets = gen.filled(bas, float(z_max))
    polys = []
    for pts, offs in zip(points, offsets):
        anneaux = [pts[offs[k]:offs[k + 1]] for k in range(len(offs) - 1)]
        anneaux = [a for a in anneaux if len(a) >= 4]
        if anneaux:
            polys.append(Polygon(anneaux[0], anneaux[1:]).buffer(0))
    return unary_union(polys) if polys else Polygon()


def plafonds(modele, triangles, indices: Optional[Sequence[int]] = None
             ) -> List[Dict]:
    """Les faces planes qui regardent vers le bas (hors le dessous de la
    pièce): [{'face', 'z', 'region'}] dans le repère de `triangles`."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    T = np.asarray(triangles, dtype=float)
    faces = getattr(modele, 'faces', None) or []
    fd = getattr(modele, 'face_de', None)
    face_de = np.asarray(fd if fd is not None else [])
    if not len(face_de) or len(face_de) != len(T):
        return []
    bas = float(T[:, :, 2].min())
    voulues = set(indices) if indices is not None else None
    sortie = []
    for info in faces:
        if voulues is not None and info['index'] not in voulues:
            continue
        if info.get('genre') != 'plan':
            continue
        sel = np.nonzero(face_de == info['index'])[0]
        if not len(sel):
            continue
        tri = T[sel]
        zs = tri[:, :, 2]
        if float(np.ptp(zs)) > 1e-3:
            continue                        # pas horizontale
        z = float(zs.mean())
        if z <= bas + 1e-3:
            continue                        # le dessous: le brut
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        n = n[np.argmax(np.linalg.norm(n, axis=1))]
        # le côté matière se mesure: la face regarde vers le bas si la
        # matière est AU-DESSUS d'elle
        from src.io.vecteur.step3d import dans_la_matiere
        c = tri[np.argmax(np.linalg.norm(np.cross(
            tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1))].mean(
            axis=0)
        eps = 1e-3 * (float(np.ptp(T.reshape(-1, 3), axis=0).max()) or 1.0)
        dessus = dans_la_matiere(T, np.array([c + (0, 0, eps)]))[0]
        dessous = dans_la_matiere(T, np.array([c - (0, 0, eps)]))[0]
        if not (dessus and not dessous):
            continue
        region = unary_union([Polygon(t[:, :2]).buffer(0) for t in tri
                              if Polygon(t[:, :2]).area > 1e-12])
        if region.is_empty:
            continue
        sortie.append({'face': info['index'], 'z': z, 'region': region})
    return sortie


def sol_sous(triangles, region, z_plafond: float, fond: float) -> float:
    """La plus haute matière SOUS le plafond, dans sa région (le sol de
    la rainure), sinon le fond."""
    from shapely.geometry import Polygon
    T = np.asarray(triangles, dtype=float)
    zmax = T[:, :, 2].max(axis=1)
    sous = T[zmax < z_plafond - 1e-3]
    meilleur = float(fond)
    if not len(sous):
        return meilleur
    zs = sous[:, :, 2].max(axis=1)
    for t, z in zip(sous, zs):
        if z <= meilleur:
            continue
        p = Polygon(t[:, :2])
        if p.area > 1e-12 and p.buffer(0).intersection(region).area > 1e-6:
            meilleur = float(z)
    return meilleur


# ───────────────────────── les outils ─────────────────────────

def outils_t(bibliotheque, cat=None) -> List[Dict]:
    """Les fraises en T de la bibliothèque: [{'id', 'outil', 'rayon',
    'hauteur', 'col', 'portee', 'queue'}] (les cotes de leur dessin)."""
    from src.core import dessin_outil
    sortie = []
    for tid, t in getattr(bibliotheque, 'tools', {}).items():
        try:
            c = dessin_outil.cotes_outil(t, cat)
        except Exception:
            continue
        if c.get('famille') != 'tslot':
            continue
        r = c['D1'] / 2.0
        h = c.get('hauteur') or max(0.5, 0.2 * c['D1'])
        sortie.append({'id': tid, 'outil': t, 'rayon': r, 'hauteur': h,
                       'col': 0.45 * r, 'queue': c['D2'] / 2.0,
                       'portee': c.get('L3') or c.get('L2') or 3 * c['D1']})
    return sortie


# ───────────────────────── le parcours ─────────────────────────

def _anneaux(geom) -> List[np.ndarray]:
    sortie = []
    for p in getattr(geom, 'geoms', [geom]):
        if p.is_empty or p.geom_type != 'Polygon':
            continue
        for a in [p.exterior] + list(p.interiors):
            c = np.asarray(a.coords, dtype=float)
            if len(c) >= 4:
                sortie.append(c)
    return sortie


def _reechantillonner(c: np.ndarray, pas: float) -> np.ndarray:
    pts = [c[0]]
    for a, b in zip(c[:-1], c[1:]):
        n = max(1, int(math.ceil(np.linalg.norm(b - a) / pas)))
        for k in range(1, n + 1):
            pts.append(a + (b - a) * k / n)
    return np.asarray(pts)


def proposer(modele, placement, bibliotheque, cat=None,
             faces: Optional[Sequence[int]] = None, decalage=None,
             pas: float = None, progression=None) -> Dict:
    """Les contre-dépouilles usinables à la fraise en T: {'etapes':
    (comme usinage3d.calculer), 'rainures': [{'face', 'z_plafond',
    'z_sol', 'outil', 'couverture', 'niveaux'}], 'faces': indices
    traitées, 'raisons': [texte des plafonds laissés]}."""
    from shapely.geometry import box
    from src.core import usinage3d as u3
    from src.core.vcarve import avancer
    dx, dy, haut, bas = placement
    dec = np.asarray(decalage if decalage is not None else (-dx, -dy, haut),
                     dtype=float)
    T = np.asarray(modele.triangles, dtype=float) - dec
    fond = float(T[:, :, 2].min())
    sortie = {'etapes': [], 'rainures': [], 'faces': [], 'raisons': []}
    outils = sorted(outils_t(bibliotheque, cat), key=lambda o: -o['rayon'])
    hauts = plafonds(modele, T, faces)
    if not hauts:
        return sortie
    if not outils:
        sortie['raisons'].append("aucune fraise en T dans la bibliothèque")
        return sortie
    # assez de place autour de la pièce: le bord de la grille ne doit
    # pas borner ce qui est ouvert (le col et le disque y passent)
    marge = max(2 * o['rayon'] + o['col'] + 5.0 for o in outils)
    mn, mx = T.reshape(-1, 3).min(axis=0), T.reshape(-1, 3).max(axis=0)
    grille = u3.Grille(mn[0] - marge, mx[0] + marge, mn[1] - marge,
                       mx[1] + marge, pas=pas)
    H = u3.carte_piece(T, grille, fond)
    cadre = box(grille.x0, grille.y0, grille.x0 + grille.nx * grille.pas,
                grille.y0 + grille.ny * grille.pas)
    cache = {}
    for k, pl in enumerate(hauts):
        avancer(progression, k / len(hauts),
                f"contre-dépouille {k + 1}/{len(hauts)}")
        z_sol = sol_sous(T, pl['region'], pl['z'], fond)
        fait = None
        for o in outils:
            h = o['hauteur']
            if pl['z'] - z_sol < h - 1e-3:
                continue                    # le disque n'y entre pas
            hauteur = pl['z'] - z_sol
            n = max(1, int(math.ceil((hauteur - h) / (h * (1 - RECOUVREMENT))
                                     )) + 1) if hauteur > h + 1e-6 else 1
            niveaux = ([z_sol + (pl['z'] - h - z_sol) * i / (n - 1)
                        for i in range(n)] if n > 1 else [pl['z'] - h])
            ecr = u3._Ecrivain(f"TSLOT_{pl['face']}_{o['outil'].name}")
            coupe = None
            premier = True
            for z in niveaux:
                # le col: là où rien ne dépasse le dessus du disque; la
                # queue: assez haut au-dessus
                libre = zone_basse(grille, H, z + h + 1e-3)
                col = libre.buffer(-(o['col'] + JEU))
                # le disque: hors de la pièce dans sa tranche
                tranche = section(T, z + 0.01).union(
                    section(T, z + h / 2)).union(section(T, z + h - 0.01))
                disque = cadre.difference(tranche.buffer(o['rayon'] + JEU))
                permis = col.intersection(disque).intersection(
                    pl['region'].buffer(o['rayon'] + 0.5))
                # descendre: là où le disque passe à la verticale, puis
                # entrer à l'horizontale jusqu'au contour
                from shapely.geometry import LineString
                from shapely.ops import nearest_points
                rd = o['rayon'] / grille.pas
                cle = round(rd, 3)
                if cle not in cache:
                    cache[cle] = u3.dilater_disque(H, rd)
                plongee = zone_basse(grille, cache[cle], z + 1e-3
                                     ).intersection(permis)
                if plongee.is_empty:
                    continue
                large = permis.buffer(1e-3)
                for anneau in _anneaux(permis):
                    contour = LineString(anneau[:, :2])
                    # seuls les contours qui passent SOUS le plafond
                    if contour.buffer(o['rayon']).intersection(
                            pl['region']).area < 1e-6:
                        continue
                    q, p = nearest_points(contour, plongee)
                    entree = LineString([p.coords[0], q.coords[0]])
                    if entree.length > 1e-6 and not large.contains(entree):
                        continue
                    pts = _reechantillonner(anneau[:, :2], grille.pas * 2)
                    qa = np.asarray(q.coords[0])
                    debut_k = int(np.argmin(np.linalg.norm(pts - qa,
                                                           axis=1)))
                    boucle = np.concatenate([pts[debut_k:],
                                             pts[1:debut_k + 1]])
                    px, py = p.coords[0]
                    if premier:
                        ecr.placer(px, py)
                        premier = False
                    else:
                        ecr.rapide(z=u3.SECURITE)
                        ecr.rapide(px, py)
                    ecr.rapide(z=u3.APPROCHE)
                    ecr.ligne(z=z, feed="Plunge")
                    for x, y in boucle:
                        ecr.ligne(x, y, feed="Roughing")
                    ecr.ligne(px, py, feed="Roughing")
                    ecr.ligne(z=u3.APPROCHE)
                    balaye = LineString(boucle).buffer(o['rayon'])
                    coupe = balaye if coupe is None else coupe.union(balaye)
            if coupe is None:
                continue
            couverture = float(coupe.intersection(pl['region']).area
                               / max(pl['region'].area, 1e-9))
            if couverture < 0.5:
                continue
            ecr.degager()
            fait = (o, ecr, couverture, niveaux)
            break
        if fait is None:
            sortie['raisons'].append(
                f"face {pl['face']} (plafond Z {pl['z']:.2f}): aucune fraise "
                "en T n'y entre (disque trop épais ou col bloqué)")
            continue
        o, ecr, couverture, niveaux = fait
        nom = f"TSLOT{len(sortie['etapes']) + 1}"
        ecr.lignes[0] = f"$$$ {nom}"
        sortie['etapes'].append({
            'etape': {'nom': f"Fraise en T {o['outil'].name}",
                      'outil': o['id'], 'role': 'contre-depouille'},
            'nom_sequence': nom, 'code': ecr.texte(),
            'longueur': ecr.longueur, 'n_passes': len(niveaux)})
        sortie['rainures'].append({'face': pl['face'], 'z_plafond': pl['z'],
                                   'z_sol': z_sol,
                                   'outil': o['outil'].name,
                                   'couverture': couverture,
                                   'niveaux': niveaux})
        sortie['faces'].append(pl['face'])
    avancer(progression, 1.0, "fini")
    return sortie


def resume(res: Dict) -> str:
    r = res.get('rainures') or []
    if not r and not res.get('raisons'):
        return ""
    lignes = []
    for x in r:
        lignes.append(f"Contre-dépouille (plafond Z {x['z_plafond']:.2f}, sol "
                      f"Z {x['z_sol']:.2f}): {x['outil']}, "
                      f"{len(x['niveaux'])} niveau(x), "
                      f"{x['couverture'] * 100:.0f} % du plafond")
    lignes += [f"Laissée: {t}" for t in res.get('raisons') or []]
    return "\n".join(lignes)
