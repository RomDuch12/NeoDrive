# -*- coding: utf-8 -*-
"""Gravure 2,5D et évidement à la fraise conique.

Une fraise conique n'a pas UN diamètre: elle en a un par profondeur.
À la cote `z` sous la surface, son rayon vaut

    r(z) = r_pointe + z · tan(demi-angle)

Graver un contour « au V », c'est donc descendre exactement de ce
qu'il faut pour que le cône touche les deux bords à la fois — et
REMONTER dans les angles, là où la forme se resserre. C'est ce que
TypeEdit appelle les remontées d'angles.

Deux familles de parcours, et elles ne font pas le même travail:

- les ANNEAUX (érosions successives): le contour est rentré de `d`
  — érosion par un disque, ce que `buffer` négatif fait exactement —
  et le bord de l'érodé est le lieu des points à distance `d`. Toute
  la boucle est donc à la MÊME profondeur. C'est de l'évidement en
  escalier: entre deux anneaux, l'outil laisse une marche de
  `pas / tan(demi-angle)` — 0,56 mm pour un pas de 0,15 à 30°.

- l'AXE MÉDIAN en 3D: l'outil suit le squelette de la forme et sa
  profondeur change à chaque point (distance au bord ÷ tan). Le
  flanc du V n'est plus fait de marches: il est engendré par le CÔNE
  lui-même. C'est le vrai V-carving, et c'est ce qui lisse les
  pointes.

D'où la stratégie complète: anneaux en ébauche, axe médian en
finition — ou l'axe médian seul quand la matière part en une fois.

Rien de Qt ici: le calcul se vérifie sans interface.
"""

import math
import re
from typing import Dict, List, Sequence, Tuple

#: un contour est une suite de (x, y); un jeu de contours forme une
#: zone (le second contour d'un « O » est son intérieur)
Point = Tuple[float, float]
Contour = List[Point]

#: « Con 30° 0.2 »: 30 est l'angle TOTAL du cône, 0.2 le diamètre de
#: la pointe (la troncature). Les deux se lisent dans le nom d'outil.
ANGLE_DEFAUT = 30.0
TRONCATURE_DEFAUT = 0.2

#: finesse du disque d'érosion. 16 quadrants = 64 côtés: l'écart au
#: vrai cercle reste sous 0,1 % du rayon.
QUADRANTS = 16

_NOM_CONE = re.compile(
    r"con\s*(\d+(?:[.,]\d+)?)\s*°?\s*(\d+(?:[.,]\d+)?)?",
    re.IGNORECASE)


#: Une fraise cylindrique est un cône d'angle nul. `ANGLE_DEFAUT`
#: minimal accepté par les formules: sur 3 mm de profondeur, le
#: rayon varie de 3 µm — le cylindre est rendu à la tolérance de
#: mesure, sans un cas particulier dans chaque calcul.
ANGLE_CYLINDRIQUE = 0.1

#: « Cyl 6 z2L12 HSC », « Cyl 0.8 z1L3 » — le premier nombre est le
#: diamètre
_NOM_CYLINDRE = re.compile(r'\bCyl\s*([\d]+(?:[.,][\d]+)?)',
                           re.IGNORECASE)


def diametre_depuis_nom(nom: str):
    """Diamètre d'une fraise cylindrique, ou None.

    Rendre None n'est pas un échec: c'est la réponse pour un outil
    qui n'est pas cylindrique."""
    m = _NOM_CYLINDRE.search(str(nom or ""))
    if not m:
        return None
    try:
        valeur = float(m.group(1).replace(',', '.'))
    except (TypeError, ValueError):
        return None
    return valeur if valeur > 0 else None


def cone_depuis_nom(nom: str) -> Tuple[float, float]:
    """(angle total, troncature) lus dans un nom d'outil.

    « Con 30° 0.2 » → (30.0, 0.2). Ce que le nom ne dit pas prend la
    valeur par défaut: on ne devine pas une géométrie d'outil."""
    m = _NOM_CONE.search(str(nom or ""))
    if not m:
        return ANGLE_DEFAUT, TRONCATURE_DEFAUT
    try:
        angle = float(m.group(1).replace(',', '.'))
    except (TypeError, ValueError):
        angle = ANGLE_DEFAUT
    troncature = TRONCATURE_DEFAUT
    if m.group(2):
        try:
            troncature = float(m.group(2).replace(',', '.'))
        except (TypeError, ValueError):
            pass
    return angle, troncature


def rayon_a_profondeur(z: float, angle: float = ANGLE_DEFAUT,
                       troncature: float = TRONCATURE_DEFAUT) -> float:
    """Rayon du cône à la profondeur `z` (positive vers le bas)."""
    demi = math.radians(max(0.1, min(179.0, angle)) / 2.0)
    return troncature / 2.0 + max(0.0, z) * math.tan(demi)


def profondeur_pour_rayon(rayon: float, angle: float = ANGLE_DEFAUT,
                          troncature: float = TRONCATURE_DEFAUT
                          ) -> float:
    """Profondeur à laquelle le cône a ce rayon. 0 sous la pointe."""
    demi = math.radians(max(0.1, min(179.0, angle)) / 2.0)
    tangente = math.tan(demi)
    if tangente <= 1e-9:
        return 0.0
    return max(0.0, (rayon - troncature / 2.0) / tangente)


# ── Zone à graver ──

def _shapely():
    try:
        from shapely.geometry import Polygon, MultiPolygon  # noqa
        from shapely.ops import unary_union  # noqa
        import shapely.geometry as geo
        import shapely.ops as ops
        return geo, ops
    except ImportError:                       # pragma: no cover
        raise RuntimeError(
            "La gravure 2,5D demande « shapely » (pip install shapely)")


class Annule(BaseException):
    """L'utilisateur a arrêté le calcul. Pas une erreur: une décision.

    Dérive de BaseException, comme KeyboardInterrupt: les
    `except Exception` qui protègent les calculs ne doivent pas
    l'attraper — sinon un clic sur Annuler devenait « parcours vide »
    et partait au cache."""


def avancer(progression, fraction: float, texte: str = "") -> None:
    """Rend compte, et s'arrête si on le demande.

    `progression` est un appelable `(fraction, texte) -> bool`, ou
    None. Rendre False, c'est demander l'arrêt: on lève `Annule`,
    et rien de ce qui était en cours n'est gardé. Tout calcul qui
    peut durer passe par ici — c'est ce qui permet à la fenêtre de
    progression d'avoir un bouton Annuler qui fait quelque chose."""
    if progression is None:
        return
    if progression(max(0.0, min(1.0, float(fraction))), texte) is False:
        raise Annule(texte or "calcul arrêté")


def sous_progression(progression, debut: float, fin: float,
                     prefixe: str = ""):
    """Une progression qui n'occupe qu'une tranche de la barre.

    Le calcul d'une gamme enchaîne des étages, chaque étage des
    anneaux puis un axe médian: chacun rend compte de 0 à 1 dans SA
    tranche, et la barre avance d'un seul mouvement."""
    if progression is None:
        return None
    largeur = max(0.0, fin - debut)

    def _avance(fraction, texte=""):
        return progression(debut + largeur * max(0.0, min(1.0, fraction)),
                           (prefixe + texte) if prefixe else texte)
    return _avance


#: deux contours dont la différence symétrique est plus petite que
#: ça sont le MÊME contour (doublon d'export), en mm²
TOLERANCE_DOUBLON = 1e-6

#: tolérance de la liaison sans remontée, en mm. Les points du
#: parcours sont arrondis au dix-millième: sans elle, un contour
#: n'est pas « dans » sa propre zone.
TOLERANCE_LIAISON = 2e-4


def _polygones(contours: Sequence[Contour]) -> list:
    """Les contours en polygones valides, doublons écartés.

    Un DXF de gravure porte très souvent chaque contour DEUX fois
    (deux calques, ou un export qui repasse dessus). Superposés, ils
    ne sont pas une imbrication: les compter comme telle annulait
    toute la zone — mesuré sur un logo de 122 contours dont 55
    paires, la gravure ne rendait rien du tout."""
    geo, _ops = _shapely()
    bruts = []
    for contour in contours:
        points = [(float(x), float(y)) for x, y in contour]
        if len(points) < 3:
            continue
        if points[0] != points[-1]:
            points.append(points[0])
        poly = geo.Polygon(points)
        if not poly.is_valid:
            poly = poly.buffer(0)          # auto-intersections
        if poly.is_empty or poly.area <= 1e-12:
            continue
        if poly.geom_type == 'MultiPolygon':
            bruts.extend(p for p in poly.geoms if p.area > 1e-12)
        else:
            bruts.append(poly)
    # Dédoublonnage: on ne compare que ce qui a la même signature
    # (aire et emprise), sinon c'est n² comparaisons de géométries
    uniques, par_signature = [], {}
    for poly in bruts:
        minx, miny, maxx, maxy = poly.bounds
        signature = (round(poly.area, 6), round(minx, 4),
                     round(miny, 4), round(maxx, 4), round(maxy, 4))
        jumeaux = par_signature.setdefault(signature, [])
        if any(poly.symmetric_difference(autre).area
               < TOLERANCE_DOUBLON for autre in jumeaux):
            continue
        jumeaux.append(poly)
        uniques.append(poly)
    return uniques


def zone(contours: Sequence[Contour]):
    """Assemble des contours en une zone, trous compris.

    Un contour entouré par un nombre IMPAIR d'autres est un trou —
    l'intérieur d'un « O », le creux d'un « A ». C'est la règle des
    fontes, et celle des DXF de gravure.

    On COMPTE les imbrications au lieu de cumuler des différences
    symétriques: la cascade dépendait de l'ordre et donnait n'importe
    quoi dès que deux contours se recouvraient en partie."""
    _geo, ops = _shapely()
    polys = _polygones(contours)
    if not polys:
        return None
    if len(polys) == 1:
        return polys[0]

    from shapely import STRtree
    from shapely.geometry import Point
    arbre = STRtree(polys)
    niveaux = {}
    for i, poly in enumerate(polys):
        # Le point témoin se prend sur le BORD, pas à l'intérieur:
        # le centre d'un grand disque est aussi dans le petit qu'il
        # entoure, et l'anneau se comptait à l'envers — les deux
        # cercles devenaient des trous et la zone disparaissait.
        temoin = Point(poly.exterior.coords[0])
        profondeur = 0
        for j in arbre.query(temoin):
            if int(j) != i and polys[int(j)].contains(temoin):
                profondeur += 1
        niveaux.setdefault(profondeur, []).append(poly)
    # On empile NIVEAU PAR NIVEAU: retirer tous les trous d'un coup
    # emporterait ce qu'ils contiennent — le disque au centre de
    # trois imbrications repartait avec l'anneau qui l'entoure.
    matiere = None
    for profondeur in sorted(niveaux):
        etage = ops.unary_union(niveaux[profondeur])
        if matiere is None:
            matiere = etage
        elif profondeur % 2:
            matiere = matiere.difference(etage)
        else:
            matiere = matiere.union(etage)
    if matiere is None or matiere.is_empty:
        return None
    return matiere


def _anneaux(forme) -> List[Contour]:
    """Contours fermés d'une géométrie shapely (bords et trous)."""
    sortie = []
    geometries = getattr(forme, 'geoms', None) or [forme]
    for geom in geometries:
        exterieur = getattr(geom, 'exterior', None)
        if exterieur is None:
            continue
        sortie.append([(round(x, 4), round(y, 4))
                       for x, y in exterieur.coords])
        for trou in geom.interiors:
            sortie.append([(round(x, 4), round(y, 4))
                           for x, y in trou.coords])
    return [c for c in sortie if len(c) >= 3]


def eroder(forme, distance: float):
    """Érode la zone d'un disque de rayon `distance`.

    C'est l'opération centrale: le bord de l'érodé est le lieu des
    points à `distance` du bord d'origine."""
    if distance <= 0:
        return forme
    ronge = forme.buffer(-distance, quad_segs=QUADRANTS,
                         join_style=1)      # 1 = joint arrondi
    return None if ronge.is_empty else ronge


def _numpy():
    try:
        import numpy as np
        return np
    except ImportError:                       # pragma: no cover
        raise RuntimeError("La gravure 2,5D demande « numpy »")


def echantillonner(forme, pas: float) -> List[Point]:
    """Points du bord, espacés d'au plus `pas`."""
    points = []
    lignes = [forme.exterior] + list(forme.interiors) \
        if hasattr(forme, 'exterior') \
        else [ligne for geom in forme.geoms
              for ligne in [geom.exterior] + list(geom.interiors)]
    import shapely
    np = _numpy()
    for ligne in lignes:
        longueur = ligne.length
        if longueur <= 0:
            continue
        n = max(4, int(math.ceil(longueur / max(0.01, pas))))
        # un seul appel vectorisé: neuf mille interpolations en
        # Python coûtaient plus que Voronoï lui-même
        abscisses = np.arange(n, dtype=float) * (longueur / n)
        echantillons = shapely.line_interpolate_point(ligne, abscisses)
        coords = shapely.get_coordinates(echantillons)
        points.extend((float(x), float(y)) for x, y in coords)
    return points


#: en dessous, l'échantillonnage coûte plus qu'il ne rapporte
PAS_MINI = 0.02
#: garde-fou: au-delà, Voronoï devient long sans rien apporter
POINTS_MAXI = 80000


def largeur_caracteristique(forme) -> float:
    """Largeur moyenne des traits: 2 x aire / périmètre.

    Sur un long trait d'épaisseur e, l'aire vaut e x L et le
    périmètre 2 L: le rapport rend e. C'est grossier sur une forme
    massive, mais c'est précisément sur les traits fins qu'il est
    juste — et ce sont eux qui décident du pas."""
    if forme is None or forme.is_empty or forme.length <= 0:
        return 0.0
    return 2.0 * forme.area / forme.length


def pas_pour(forme, pas: float) -> float:
    """Le pas demandé, resserré à ce que le dessin exige.

    Un logo de signature fait 0,2 mm de trait: échantillonné au pas
    de 0,2, son squelette n'existe pas (mesuré: 0 chaîne). Il faut
    quatre points en travers du trait pour que Voronoï trouve
    l'axe."""
    largeur = largeur_caracteristique(forme)
    if largeur > 0:
        pas = min(pas, largeur / 4.0)
    pas = max(PAS_MINI, pas)
    # et si le contour est immense, on desserre plutôt que de
    # faire attendre
    if forme is not None and forme.length / pas > POINTS_MAXI:
        pas = forme.length / POINTS_MAXI
    return pas


def axe_median(forme, pas: float = 0.2,
               marge: float = 0.0, progression=None) -> List[Contour]:
    """Squelette de la forme, en chaînes de points.

    Voronoï des points du bord: entre deux bords qui se font face,
    les arêtes de Voronoï passent à égale distance des deux — c'est
    l'axe médian. On ne garde que ce qui est DANS la forme et à plus
    de `marge` du bord (sous cette distance, le squelette n'est que
    le bruit de l'échantillonnage).
    """
    from scipy.spatial import Voronoi, QhullError
    import shapely
    np = _numpy()

    pas = pas_pour(forme, pas)
    avancer(progression, 0.0, "échantillonnage du bord")
    points = echantillonner(forme, pas)
    if len(points) < 8:
        return []
    avancer(progression, 0.15, f"Voronoï de {len(points)} points")
    try:
        vor = Voronoi(np.array(points))
    except (QhullError, ValueError):           # pragma: no cover
        return []
    avancer(progression, 0.6, "chaînes de l'axe médian")

    sommets = vor.vertices
    if len(sommets) == 0:
        return []
    # Un sommet ne vaut que s'il est dans la matière, assez loin du
    # bord: le reste est le bruit de l'échantillonnage
    points_shapely = shapely.points(sommets)
    dedans = shapely.contains_xy(forme, sommets[:, 0], sommets[:, 1])
    distances = shapely.distance(forme.boundary, points_shapely)
    # Le filtre écarte le BRUIT de l'échantillonnage, rien d'autre.
    # Il valait `max(marge, pas * 0.75)` avec marge = rayon de
    # pointe: sur un trait de 0,2 mm, l'axe est à 0,1 du bord et
    # passait donc à la trappe — la lettre n'était pas gravée du
    # tout. Un outil trop gros ne fait pas disparaître le trait: il
    # le grave moins profond, et c'est parcours_3d qui le dit.
    valide = dedans & (distances >= max(marge, pas * 0.75))

    voisins: Dict[int, set] = {}
    for a, b in vor.ridge_vertices:
        if a < 0 or b < 0 or not (valide[a] and valide[b]):
            continue
        voisins.setdefault(a, set()).add(b)
        voisins.setdefault(b, set()).add(a)
    if not voisins:
        return []

    # Chaînes: on part des extrémités (un seul voisin), puis de ce
    # qui reste (les boucles). Chaque arête n'est parcourue qu'une
    # fois — l'outil ne repasse pas où il est déjà passé.
    vues = set()

    def _arete(a, b):
        return (a, b) if a < b else (b, a)

    def _suivre(depart):
        chaine = [depart]
        courant = depart
        while True:
            suite = [v for v in voisins.get(courant, ())
                     if _arete(courant, v) not in vues]
            if not suite:
                break
            suivant = suite[0]
            vues.add(_arete(courant, suivant))
            chaine.append(suivant)
            courant = suivant
        return chaine

    chaines = []
    extremites = [i for i, v in voisins.items() if len(v) == 1]
    departs = extremites + list(voisins)
    for numero, depart in enumerate(departs):
        if numero % 500 == 0:
            avancer(progression, 0.6 + 0.4 * numero / max(1, len(departs)),
                    "chaînes de l'axe médian")
        while any(_arete(depart, v) not in vues
                  for v in voisins.get(depart, ())):
            chaine = _suivre(depart)
            if len(chaine) >= 2:
                chaines.append([(round(float(sommets[i][0]), 4),
                                 round(float(sommets[i][1]), 4))
                                for i in chaine])
    return chaines


#: sous cette profondeur, l'outil effleure sans rien enlever
PROFONDEUR_MORTE = 0.005


def passages_median(forme, angle: float = ANGLE_DEFAUT,
                    troncature: float = TRONCATURE_DEFAUT,
                    profondeur_max: float = 2.0,
                    pas: float = 0.2, progression=None) -> List[Dict]:
    """Les passages 3D sur l'axe médian d'une forme DÉJÀ calculée.

    Un Z par point: c'est ce qui donne au V ses flancs lisses.

    Deux règles apprises sur un logo de signature dont neuf dixièmes
    du tracé n'étaient pas usinés:

    - on ne filtre PAS l'axe par le rayon de l'outil. Un trait plus
      étroit que la pointe se grave moins profond, il ne disparaît
      pas du parcours;
    - en revanche on coupe les portions où l'outil n'enlèverait
      rien (Z sous PROFONDEUR_MORTE): l'outil ne s'y promène pas.
    """
    import shapely
    np = _numpy()
    if forme is None or forme.is_empty:
        return []
    chaines = axe_median(forme, pas=pas, marge=0.0,
                         progression=sous_progression(progression,
                                                      0.0, 0.7))
    if not chaines:
        return []
    bord = forme.boundary
    sortie = []
    # La distance au bord de TOUS les points d'un coup: deux cents
    # appels par chaîne devenaient un seul, en C.
    avancer(progression, 0.7, "profondeur des passages 3D")
    tous = np.array([p for chaine in chaines for p in chaine],
                    dtype=float)
    toutes_distances = shapely.distance(bord, shapely.points(tous))
    debut = 0
    for numero, chaine in enumerate(chaines):
        if numero % 50 == 0:
            avancer(progression, 0.7 + 0.3 * numero / len(chaines),
                    f"profondeur des passages 3D ({numero}/"
                    f"{len(chaines)})")
        distances = toutes_distances[debut:debut + len(chaine)]
        debut += len(chaine)
        courant = []
        for (x, y), d in zip(chaine, distances):
            z = min(float(profondeur_pour_rayon(float(d), angle,
                                                troncature)),
                    float(profondeur_max))
            if z < PROFONDEUR_MORTE:
                # l'outil est plus gros que le trait: on lève le
                # crayon plutôt que de balader la fraise à vide
                if len(courant) >= 2:
                    sortie.append({'points': courant})
                courant = []
                continue
            courant.append((x, y, round(z, 4)))
        if len(courant) >= 2:
            sortie.append({'points': courant})
    return sortie


def parcours_3d(contours: Sequence[Contour],
                angle: float = ANGLE_DEFAUT,
                troncature: float = TRONCATURE_DEFAUT,
                profondeur_max: float = 2.0,
                pas: float = 0.2,
                relief: bool = False,
                cadre_marge: float = 2.0,
                decalage: float = 0.0) -> List[Dict]:
    """Passages 3D sur l'axe médian: un Z par POINT.

    Rend `[{'points': [(x, y, z), …]}]`. C'est le passage qui donne
    au V ses flancs lisses: la marche entre deux anneaux disparaît,
    le cône engendre le flanc d'un seul tenant.
    """
    forme = zone_a_usiner(contours, relief=relief,
                          cadre_marge=cadre_marge, decalage=decalage)
    return passages_median(forme, angle, troncature,
                           profondeur_max, pas)


#: bandes de rayon pour le calcul de couverture. Tampon par bande
#: plutôt que par segment: 8 opérations au lieu de 9000.
BANDES_COUVERTURE = 12

#: en deçà, deux profondeurs sont la même: un passage à 1,49 vaut
#: la cote 1,5
TOLERANCE_PROFONDEUR = 0.02


def dernier_palier(plan: Sequence[Dict]) -> List[Dict]:
    """Les étapes du palier le plus profond — celles qui comptent.

    Une gravure en plusieurs descentes répète le MÊME chemin à chaque
    cran; la surface enlevée est celle du dernier cran, qui contient
    toutes les autres. Mesurer chacun des paliers d'une gravure en
    quinze crans multipliait le balayage par 70: 68 s au lieu
    d'une."""
    paliers = [e.get('palier') for e in plan if e.get('palier') is not None]
    if not paliers:
        return list(plan)
    dernier = max(paliers)
    return [e for e in plan if e.get('palier', dernier) == dernier]


def _runs_par_bande(plan: Sequence[Dict], angle: float,
                    troncature: float, profondeur_mini: float = 0.0):
    """Les chemins du plan, coupés en runs de segments de même bande
    de rayon: (bande, [(x, y), …]). Un passage 3D change de
    profondeur doucement — il fait quelques runs, pas mille
    segments.

    `profondeur_mini` écarte les segments qui ne sont pas descendus
    jusque-là: c'est ce qui permet de ne compter, pour la reprise,
    que ce que l'outil d'amont a fini à la cote."""
    runs = []            # [(rayon, [(x, y), ...])]
    r_max = 1e-9
    seuil = float(profondeur_mini or 0.0) - TOLERANCE_PROFONDEUR
    for etape in plan:
        points = etape.get('points')
        if points:
            for a, b in zip(points, points[1:]):
                z = abs((a[2] + b[2]) / 2.0) if len(a) > 2 else 0.0
                if z < seuil:
                    continue
                r = rayon_a_profondeur(z, angle, troncature)
                r_max = max(r_max, r)
                runs.append((r, (a[0], a[1]), (b[0], b[1])))
            continue
        z = abs(float(etape.get('profondeur', 0.0) or 0.0))
        if z < seuil:
            continue
        r = etape.get('rayon')
        if r is None:
            r = rayon_a_profondeur(z, angle, troncature)
        r = float(r)
        r_max = max(r_max, r)
        for contour in etape.get('contours') or []:
            for a, b in zip(contour, contour[1:]):
                runs.append((r, (a[0], a[1]), (b[0], b[1])))
    if not runs:
        return [], r_max
    # bande par segment, puis fusion des segments CONSÉCUTIFS de
    # même bande en une seule ligne
    lignes = []
    bande_courante = None
    points_courants: list = []
    for r, a, b in runs:
        bande = min(BANDES_COUVERTURE - 1,
                    int(BANDES_COUVERTURE * r / (r_max + 1e-12)))
        if (bande == bande_courante and points_courants
                and points_courants[-1] == a):
            points_courants.append(b)
            continue
        if len(points_courants) >= 2:
            lignes.append((bande_courante, points_courants))
        bande_courante = bande
        points_courants = [a, b]
    if len(points_courants) >= 2:
        lignes.append((bande_courante, points_courants))
    return lignes, r_max


def balayage(plan: Sequence[Dict], angle: float = ANGLE_DEFAUT,
             troncature: float = TRONCATURE_DEFAUT, progression=None,
             profondeur_mini: float = 0.0):
    """La surface que l'outil enlève vraiment, en suivant le plan.

    Le cône est plus large en haut: un passage à Z=0,3 enlève un
    trait de 2 r(0,3) de large, un passage à fleur de surface
    n'enlève presque rien. On tamponne donc chaque run de son rayon
    À SA PROFONDEUR — en un seul appel vectorisé de shapely, qui
    fait le travail en C sans repasser par Python pour chaque ligne.

    Avec `profondeur_mini`, seuls comptent les passages descendus au
    moins jusque-là: la surface que l'outil a FINIE à cette cote.
    Une conique qui a gravé un creux peu profond n'a pas fait le
    travail de la cylindrique qui doit évider plus bas; sans cela, la
    reprise
    laissait une arête à mi-hauteur au milieu du champ.
    """
    import shapely
    geo, ops = _shapely()
    np = _numpy()
    lignes, r_max = _runs_par_bande(dernier_palier(plan), angle,
                                    troncature, profondeur_mini)
    if not lignes:
        return None
    avancer(progression, 0.1, f"surface balayée ({len(lignes)} runs)")
    geometries = np.array([geo.LineString(pts) for _b, pts in lignes],
                          dtype=object)
    rayons = np.array([max(1e-4, r_max * (b + 1) / BANDES_COUVERTURE)
                       for b, _pts in lignes], dtype=float)
    avancer(progression, 0.3, "tampon des runs")
    tampons = shapely.buffer(geometries, rayons, quad_segs=6)
    avancer(progression, 0.7, "fusion des surfaces")
    fusion = shapely.union_all(tampons)
    avancer(progression, 1.0, "surface balayée")
    return None if fusion.is_empty else fusion


def couverture(forme, plan: Sequence[Dict],
               angle: float = ANGLE_DEFAUT,
               troncature: float = TRONCATURE_DEFAUT) -> float:
    """Part de la zone (0 à 1) que ce parcours enlève.

    C'est la mesure de conformité au dessin: sur un logo de
    signature gravé à la 30° 0,2, elle valait 0,107 — un dixième du
    tracé — et la pièce sortait méconnaissable.
    """
    if forme is None or forme.is_empty or not plan:
        return 0.0
    balaye = balayage(plan, angle, troncature)
    if balaye is None:
        return 0.0
    return min(1.0, balaye.intersection(forme).area / forme.area)


def reste_a_faire(forme, plan: Sequence[Dict],
                  angle: float = ANGLE_DEFAUT,
                  troncature: float = TRONCATURE_DEFAUT,
                  lissage: float = 0.01):
    """Ce que ce parcours LAISSE: la matière du prochain outil.

    `lissage` referme les échardes numériques — sans lui, la
    différence de deux surfaces rend des milliers de copeaux d'un
    micron que l'outil suivant essaierait d'usiner.
    """
    if forme is None or forme.is_empty:
        return None
    balaye = balayage(plan, angle, troncature)
    reste = forme if balaye is None else forme.difference(balaye)
    if reste.is_empty:
        return None
    if lissage > 0:
        reste = reste.buffer(-lissage, quad_segs=8, join_style=1)
        if reste.is_empty:
            return None
        reste = reste.buffer(lissage, quad_segs=8, join_style=1)
    return None if reste.is_empty else reste


def atteignable(forme, troncature: float):
    """Ce qu'un outil de pointe `troncature` peut atteindre au FOND.

    Ouverture morphologique: érosion du rayon de pointe, puis
    dilatation. Ce que l'outil ne peut pas atteindre au fond, il
    peut encore le graver moins profond — mais pas à la cote.
    """
    if forme is None or forme.is_empty:
        return None
    rayon = max(1e-6, float(troncature) / 2.0)
    ouvert = forme.buffer(-rayon, quad_segs=QUADRANTS,
                          join_style=1)
    if ouvert.is_empty:
        return None
    ouvert = ouvert.buffer(rayon, quad_segs=QUADRANTS, join_style=1)
    ouvert = ouvert.intersection(forme)
    return None if ouvert.is_empty else ouvert


def cadre(forme, marge: float = 2.0, largeur: float = 0.0,
          hauteur: float = 0.0, rayon: float = 0.0):
    """Le cadre autour d'une forme: le champ de la gravure.

    Par défaut, l'emprise du dessin plus une marge. Une largeur ou
    une hauteur donnée l'impose, centrée sur le dessin — c'est la
    plaque, pas le dessin, qui décide. Un rayon arrondit les
    coins."""
    if forme is None or forme.is_empty:
        return None
    geo, _ops = _shapely()
    minx, miny, maxx, maxy = forme.bounds
    cx, cy = (minx + maxx) / 2.0, (miny + maxy) / 2.0
    m = max(0.0, float(marge))
    demi_l = (float(largeur) / 2.0 if largeur and float(largeur) > 0
              else (maxx - minx) / 2.0 + m)
    demi_h = (float(hauteur) / 2.0 if hauteur and float(hauteur) > 0
              else (maxy - miny) / 2.0 + m)
    boite = geo.box(cx - demi_l, cy - demi_h, cx + demi_l, cy + demi_h)
    r = min(max(0.0, float(rayon or 0.0)), demi_l, demi_h)
    if r > 1e-9:
        # érosion puis dilatation: les coins deviennent des arcs
        boite = boite.buffer(-r, quad_segs=QUADRANTS, join_style=1) \
                     .buffer(r, quad_segs=QUADRANTS, join_style=1)
    return boite


def zone_a_usiner(contours: Sequence[Contour], relief: bool = False,
                  cadre_marge: float = 2.0, decalage: float = 0.0,
                  cadre_largeur: float = 0.0, cadre_hauteur: float = 0.0,
                  cadre_rayon: float = 0.0):
    """La zone que l'outil doit vider.

    En CREUX, c'est l'intérieur des contours. En RELIEF, c'est tout
    ce qui les entoure jusqu'à un cadre: la forme reste debout et
    c'est le fond qui descend.

    `decalage` déporte le contour avant tout calcul: positif vers
    l'extérieur. Un décalage rentrant plus grand que le rayon local
    fait disparaître la zone — shapely referme proprement, sans
    boucle parasite.
    """
    forme = zone(contours)
    if forme is None:
        return None
    if abs(decalage) > 1e-9:
        forme = forme.buffer(decalage, quad_segs=QUADRANTS,
                             join_style=1)
        if forme.is_empty:
            return None
    if not relief:
        return forme
    champ = cadre(forme, max(0.01, float(cadre_marge)), cadre_largeur,
                  cadre_hauteur, cadre_rayon)
    reste = champ.difference(forme)
    return None if reste.is_empty else reste


def passes_gravure(contours: Sequence[Contour],
                   angle: float = ANGLE_DEFAUT,
                   troncature: float = TRONCATURE_DEFAUT,
                   profondeur_max: float = 2.0,
                   pas_radial: float = 0.05,
                   forme=None, progression=None) -> List[Dict]:
    """Parcours de gravure 2,5D, du bord vers le fond.

    Rend une liste de `{'profondeur': z, 'contours': [...]}`, du plus
    superficiel au plus profond. La dernière passe non vide est
    l'axe médian: c'est là que la gravure atteint son fond, et c'est
    l'absence des passes profondes dans les angles qui produit les
    remontées."""
    if forme is None:
        forme = zone(contours)
    if forme is None:
        return []
    rayon_pointe = max(0.0, troncature / 2.0)
    rayon_max = rayon_a_profondeur(max(0.0, profondeur_max), angle,
                                   troncature)
    pas = max(0.005, float(pas_radial))

    def _passe(distance):
        ronge = eroder(forme, distance)
        if ronge is None:
            return None
        anneaux = _anneaux(ronge)
        if not anneaux:
            return None
        profondeur = profondeur_pour_rayon(distance, angle,
                                           troncature)
        if profondeur < PROFONDEUR_MORTE:
            # La première érosion vaut le rayon de pointe: sa
            # « passe » est à Z=0. L'outil y ferait le tour du
            # dessin sans rien enlever — on commence à la suivante.
            return {'vide': True}
        return {'profondeur': round(profondeur, 4),
                'contours': anneaux, 'zone': ronge}

    passes = []
    distance = rayon_pointe
    derniere_bonne = None
    premiere_vide = None
    # Garde-fou: une zone de 500 mm au pas de 0,005 ferait 100 000
    # passes. Au-delà, c'est un réglage à revoir, pas un calcul.
    for _ in range(4000):
        if distance > rayon_max + 1e-9:
            derniere_bonne = None      # borné par la profondeur
            break
        if rayon_max > rayon_pointe:
            avancer(progression,
                    (distance - rayon_pointe) / (rayon_max - rayon_pointe),
                    f"anneau à {distance:.2f} mm du bord")
        passe = _passe(distance)
        if passe is not None and passe.get('vide'):
            distance += pas          # trop en surface: on descend
            continue
        if passe is None:
            premiere_vide = distance
            break
        passes.append(passe)
        derniere_bonne = distance
        distance += pas

    # Le pas laisse la dernière passe EN DEÇÀ du fond: un pas radial
    # de 0,25 mm sur un cône à 30° manque la cote de près d'un
    # millimètre. On termine donc sur le fond exact — l'axe médian,
    # ou la profondeur demandée si elle arrive avant.
    if premiere_vide is None:
        fond = _passe(rayon_max)
        if fond is not None and (not passes
                                 or fond['profondeur']
                                 > passes[-1]['profondeur'] + 1e-6):
            passes.append(fond)
    elif derniere_bonne is not None:
        bas, haut = derniere_bonne, premiere_vide
        fond = None
        for _ in range(24):            # 24 bissections: < 1 µm
            milieu = (bas + haut) / 2.0
            passe = _passe(milieu)
            if passe is None:
                haut = milieu
            else:
                bas, fond = milieu, passe
            if haut - bas < 0.002:
                break
        if fond is not None and (not passes
                                 or fond['profondeur']
                                 > passes[-1]['profondeur'] + 1e-6):
            passes.append(fond)
    return passes


#: stratégies de gravure proposées à l'utilisateur
STRATEGIES = ("Anneaux + axe médian 3D", "Axe médian 3D seul",
              "Anneaux seuls")


def _segment_libre(zone_precedente, depart: Point,
                   arrivee: Point) -> bool:
    """Peut-on aller d'un point à l'autre SANS remonter ?

    Oui si le segment reste dans la zone que l'outil vient de vider:
    il n'y a plus de matière sur son chemin. Sinon il faut dégager —
    une liaison à travers la matière casserait l'outil."""
    if (abs(depart[0] - arrivee[0]) < 1e-9
            and abs(depart[1] - arrivee[1]) < 1e-9):
        # sur place: l'outil replonge là où il est (le tour suivant
        # du même contour, un cran plus bas)
        return True
    if zone_precedente is None:
        return False
    geo, _ops = _shapely()
    try:
        trait = geo.LineString([depart[:2], arrivee[:2]])
        # Les points du parcours sont ARRONDIS au dix-millième; la
        # zone, non. Un coin à 0,30000000000000004 rendait son
        # propre point (0,3) « dehors », et l'outil remontait au
        # dégagement entre CHAQUE passe. Deux dixièmes de micron de
        # tolérance: sous le bruit de l'arrondi, très au-dessus de
        # rien qui puisse casser une fraise.
        return bool(zone_precedente.buffer(TOLERANCE_LIAISON,
                                           quad_segs=2).covers(trait))
    except Exception:                          # pragma: no cover
        return False


def plan_gravure(contours: Sequence[Contour],
                 angle: float = ANGLE_DEFAUT,
                 troncature: float = TRONCATURE_DEFAUT,
                 profondeur_max: float = 2.0,
                 pas_radial: float = 0.05,
                 strategie: str = STRATEGIES[0],
                 relief: bool = False,
                 cadre_marge: float = 2.0,
                 decalage: float = 0.0,
                 surepaisseur: float = 0.0,
                 pas_median: float = 0.2,
                 forme=None, progression=None,
                 passages=None) -> List[Dict]:
    """Le parcours complet, dans l'ordre où il sera usiné.

    `passages`: les passages 3D déjà calculés au palier le plus
    profond. Une gravure en plusieurs descentes les reçoit tels
    quels et BORNE leur Z au palier — exact, puisque
    z_p(d) = min(z(d), p) — au lieu de refaire Voronoï à chaque
    cran: quinze paliers coûtaient quinze axes médians.

    Chaque étape est un dictionnaire:
      {'role': 'ebauche'|'finition', 'type': 'anneau'|'median',
       'profondeur': z, 'contours': [...]}          — anneau, Z plat
      {'role': …, 'type': 'median', 'points': [(x, y, z), …]}

    Chaque étape porte aussi `liaison_directe`: vrai quand l'outil
    peut y aller depuis la fin de l'étape précédente SANS remonter au
    dégagement — le segment de liaison reste alors dans la matière
    déjà retirée.
    """
    # `forme` permet à la gamme de donner le RESTE laissé par
    # l'outil précédent, au lieu de la zone entière.
    avancer(progression, 0.0, "zone à graver")
    if forme is None:
        forme = zone_a_usiner(contours, relief=relief,
                              cadre_marge=cadre_marge,
                              decalage=decalage)
    if forme is None or forme.is_empty:
        return []

    etapes = []
    fait_anneaux = strategie != "Axe médian 3D seul"
    fait_median = strategie != "Anneaux seuls"
    # les anneaux prennent le tiers de la barre, l'axe médian le
    # reste: c'est lui qui coûte
    part_anneaux = 0.3 if (fait_anneaux and fait_median) else (
        1.0 if fait_anneaux else 0.0)
    surepaisseur = max(0.0, float(surepaisseur))

    if fait_anneaux:
        forme_ebauche = forme
        if surepaisseur > 1e-9:
            # Laisser de la matière sur les flancs: l'ébauche travaille
            # une forme rétrécie, la finition reprend à la cote
            forme_ebauche = forme.buffer(-surepaisseur,
                                         quad_segs=QUADRANTS,
                                         join_style=1)
            if forme_ebauche.is_empty:
                forme_ebauche = None
        if forme_ebauche is not None:
            for passe in passes_gravure(
                    contours, angle, troncature, profondeur_max,
                    pas_radial, forme=forme_ebauche,
                    progression=sous_progression(
                        progression, 0.05, 0.05 + 0.9 * part_anneaux,
                        "anneaux — ")):
                etapes.append({
                    'role': 'ebauche' if surepaisseur > 1e-9
                    else 'finition',
                    'type': 'anneau',
                    'profondeur': passe['profondeur'],
                    'contours': passe['contours'],
                    'zone': passe['zone'],
                })

    if fait_median:
        if passages is None:
            # Le MÊME calcul que l'aperçu: la copie qui vivait ici
            # gardait l'ancien filtre par rayon d'outil, et le
            # parcours généré n'était pas celui qu'on montrait.
            passages = passages_median(
                forme, angle, troncature, profondeur_max, pas_median,
                progression=sous_progression(
                    progression, 0.05 + 0.9 * part_anneaux, 0.95,
                    "axe médian — "))
        for passage in passages:
            points = [(x, y, min(z, float(profondeur_max)))
                      for x, y, z in passage['points']]
            etapes.append({'role': 'finition', 'type': 'median',
                           'points': points, 'zone': None})

    # Liaisons: peut-on enchaîner sans remonter ?
    avancer(progression, 0.95, "liaisons entre passes")
    zone_precedente = None
    fin_precedente = None
    for etape in etapes:
        if etape['type'] == 'anneau':
            debut = etape['contours'][0][0] if etape['contours'] \
                else None
            fin = etape['contours'][-1][-1] if etape['contours'] \
                else None
        else:
            debut = etape['points'][0][:2]
            fin = etape['points'][-1][:2]
        etape['liaison_directe'] = bool(
            fin_precedente is not None and debut is not None
            and _segment_libre(zone_precedente, fin_precedente, debut))
        if fin is not None:
            fin_precedente = fin
        if etape.get('zone') is not None:
            zone_precedente = etape['zone']
        etape.pop('zone', None)
    avancer(progression, 1.0, "parcours prêt")
    return etapes


def decouper(contours: Sequence[Contour], zone,
             marge: float) -> List[Contour]:
    """Les morceaux des chemins qui passent à moins de `marge` de la
    zone.

    C'est la reprise d'évidement: les anneaux se calculent sur toute
    la matière — l'outil peut rouler dans ce qu'un autre a déjà
    vidé —, mais on ne parcourt que ce qui enlève encore quelque
    chose. `marge` est le rayon de l'outil, moins un rien: un anneau
    qui ne fait qu'effleurer le reste n'en enlève pas."""
    geo, _ops = _shapely()
    if zone is None or zone.is_empty:
        return []
    portee = zone.buffer(max(0.0, marge), quad_segs=QUADRANTS)
    morceaux = []
    for contour in contours:
        if len(contour) < 2:
            continue
        coupe = geo.LineString(contour).intersection(portee)
        for ligne in getattr(coupe, 'geoms', None) or [coupe]:
            if ligne.geom_type != 'LineString' or len(ligne.coords) < 2:
                continue
            morceaux.append([(round(x, 4), round(y, 4))
                             for x, y in ligne.coords])
    return morceaux


def decouper_3d(points: Sequence, zone, marge: float) -> List[List]:
    """Comme `decouper`, pour un passage 3D (x, y, z): les morceaux
    dont les points sont à moins de `marge` de la zone. Un point
    hors de portée coupe le passage — l'outil remonte entre deux
    morceaux."""
    geo, _ops = _shapely()
    if zone is None or zone.is_empty or not points:
        return []
    portee = zone.buffer(max(0.0, marge), quad_segs=QUADRANTS)
    import shapely
    xy = shapely.points([(p[0], p[1]) for p in points])
    dedans = shapely.intersects(portee, xy)
    morceaux = []
    courant: list = []
    for point, ok in zip(points, dedans):
        if ok:
            courant.append(point)
            continue
        if len(courant) >= 2:
            morceaux.append(courant)
        courant = []
    if len(courant) >= 2:
        morceaux.append(courant)
    return morceaux


def passes_evidement(contours: Sequence[Contour],
                     profondeur: float = 1.0,
                     angle: float = ANGLE_DEFAUT,
                     troncature: float = TRONCATURE_DEFAUT,
                     recouvrement: float = 40.0,
                     forme=None, progression=None) -> List[Dict]:
    """Évidement à profondeur CONSTANTE, du bord vers le centre.

    À cette profondeur, le cône a un rayon connu: c'est lui qui donne
    le premier passage (collé au bord) et le pas entre les passages
    suivants. Le recouvrement est en pourcentage du diamètre."""
    if forme is None:
        forme = zone(contours)
    if forme is None:
        return []
    rayon = rayon_a_profondeur(max(0.0, profondeur), angle, troncature)
    if rayon <= 1e-6:
        return []
    part = max(0.0, min(95.0, float(recouvrement))) / 100.0
    pas = max(0.01, 2.0 * rayon * (1.0 - part))
    passes = []
    distance = rayon
    # la portée maximale: le rayon du plus grand cercle inscrit
    minx, miny, maxx, maxy = forme.bounds
    portee = max(rayon, min(maxx - minx, maxy - miny) / 2.0)
    ronge = eroder(forme, distance)
    for _ in range(4000):
        avancer(progression, min(1.0, distance / portee),
                f"passage à {distance:.2f} mm du bord")
        if ronge is None:
            break
        anneaux = _anneaux(ronge)
        if not anneaux:
            break
        passes.append({'profondeur': round(float(profondeur), 4),
                       'contours': anneaux, 'zone': ronge})
        ronge = eroder(forme, distance + pas)
        distance += pas
    # Si le pas dépasse le rayon (recouvrement < 50 %), là où un bras
    # de la zone s'arrête entre deux passages son milieu reste debout:
    # une lamelle au fond de la poche. On en fait le tour — plus
    # étroite que l'outil, elle part en entier.
    reste = _non_couvert(forme, passes, rayon)
    if reste is not None:
        passes.append({'profondeur': round(float(profondeur), 4),
                       'contours': _anneaux(reste), 'zone': reste})
    return passes


#: une matière oubliée plus fine que ceci n'en est pas une (arrondis)
_LAMELLE_MIN = 0.02


def _non_couvert(forme, passes, rayon: float):
    """Ce que les passages (l'outil de `rayon` sur le bord de chaque
    zone) laissent de la forme; None si rien de plus épais que
    _LAMELLE_MIN."""
    if not passes:
        return None
    _geo, ops = _shapely()
    traits = []
    for passe in passes:
        z = passe.get('zone')
        if z is not None:
            traits.append(z.boundary.buffer(rayon, quad_segs=QUADRANTS))
    if not traits:
        return None
    couvert = ops.unary_union(traits)
    # Seule la matière où le CENTRE de l'outil peut aller (la zone du
    # premier passage, à un rayon du bord) se reprend sans mordre la
    # paroi; ce qui reste hors de là (un coin vif) est hors de portée
    # de toute façon — le bord du premier passage passe au plus près.
    centre = passes[0].get('zone')
    if centre is None:
        return None
    reste = forme.difference(couvert).intersection(centre)
    if reste.is_empty:
        return None
    # le bruit des arrondis de buffer: ce qui ne survit pas à une
    # ouverture de _LAMELLE_MIN / 2 n'est pas de la matière
    reste = reste.buffer(-_LAMELLE_MIN / 2, quad_segs=QUADRANTS) \
        .buffer(_LAMELLE_MIN / 2, quad_segs=QUADRANTS)
    return None if reste.is_empty or reste.area < 1e-4 else reste
