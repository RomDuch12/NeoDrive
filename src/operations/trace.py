"""Opération: Tracé (séquence de contours).

Un contour FERMÉ s'usine de trois façons (« Côté de l'outil »):

- centre sur le contour: le CENTRE de la fraise suit le tracé, sans
  correction (gravure au trait, rainure);
- intérieur: découpe intérieure — l'outil reste dedans, à un rayon
  du contour (une poche ajourée, une fenêtre);
- extérieur: détourage — l'outil reste dehors, à un rayon.

La compensation est un vrai décalage (shapely, coins arrondis): juste
sur un contour rentrant. « Matière laissée en XY » éloigne encore
l'outil du contour (reprise en finition). Plusieurs contours du
dessin peuvent être usinés par la même opération, chacun à toutes
ses passes avant le suivant. Sert aux contours qu'aucune fonction
Datron ne couvre — polygones, spirales, contours relevés au dessin.

Génération: comme une séquence Datron embarquée.
  - En-tête:   @ EmbeddedSequences = true @  +  sequence NOM
  - Sous-prog: Tool/Rpm/SetFeedTechnology + appel du NOM
  - Pied:      bloc $$$ NOM contenant le parcours

Le parcours est CALCULÉ à la génération (jamais stocké), sauf en mode
« Points » où il vient du tableau de points de l'opération.
"""

import math
from typing import List, Dict, Any, Tuple

from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement
)
from src.operations.registry import OperationRegistry


@OperationRegistry.register("trace")
class Trace(AbstractOperation):
    OP_TYPE = "trace"
    DISPLAY_NAME = "Tracé (centre fraise)"
    CATEGORY = "Usinage"
    DESCRIPTION = ("Parcours suivi par le CENTRE de la fraise: "
                   "rectangle, cercle, polygone, spirale, points, "
                   "dessin, ou texte en TRAIT SIMPLE (un passage)")
    ICON = "cut_rect"
    INLINE = False
    REQUIRES_TOOL = True
    REQUIRES_COORDINATES = True
    SUPPORTS_MULTI_POINT = False

    SHAPES = ("Rectangle", "Cercle", "Polygone", "Spirale",
              "Points", "Dessin", "Texte")

    #: le côté de l'outil sur un contour fermé
    COTES = ("Centre sur le contour", "Intérieur (découpe intérieure)",
             "Extérieur (détourage)")

    #: pas d'échantillonnage des courbes, en degrés
    _ARC_STEP_DEG = 6.0

    #: champs propres à chaque forme — le formulaire ne montre que
    #: ceux-là, plus les groupes communs (décalage, profondeur)
    SHAPE_FIELDS = {
        "Rectangle": ("width_x", "width_y", "rotation", "closed"),
        "Cercle": ("diameter",),
        "Polygone": ("diameter", "sides", "rotation", "closed"),
        "Spirale": ("diameter", "inner_diameter", "spiral_from",
                    "pitch_xy", "rotation"),
        "Points": ("closed",),
        "Dessin": ("closed",),
        "Texte": ("texte_fil", "hauteur_fil", "alignement_fil",
                  "interligne_fil", "disposition_fil", "rayon_fil",
                  "rotation"),
    }
    #: icône du bouton de chaque forme
    SHAPE_ICONS = {
        "Rectangle": "cut_rect", "Cercle": "cut_circle",
        "Polygone": "pattern", "Spirale": "helix",
        "Points": "pick_point", "Dessin": "dxf", "Texte": "engrave",
    }

    ALIGNEMENTS_FIL = ("Centre", "Gauche", "Droite")

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return [
            ParameterDef("shape", "Forme", ParameterType.CHOICE,
                         default="Rectangle", choices=list(cls.SHAPES),
                         unit="", group="Tracé",
                         tooltip="Rectangle et Cercle: cotes du "
                                 "parcours.\nPolygone: inscrit dans le "
                                 "cercle de diamètre donné.\nSpirale: "
                                 "entre deux cercles.\nPoints: le "
                                 "parcours passe par les points saisis."),
            ParameterDef("width_x", "Longueur X", ParameterType.FLOAT,
                         default=40.0, min_value=0.0, max_value=2000.0,
                         unit="mm", group="Tracé"),
            ParameterDef("width_y", "Longueur Y", ParameterType.FLOAT,
                         default=25.0, min_value=0.0, max_value=2000.0,
                         unit="mm", group="Tracé"),
            ParameterDef("diameter", "Ø", ParameterType.FLOAT,
                         default=30.0, min_value=0.0, max_value=2000.0,
                         unit="mm", group="Tracé",
                         tooltip="Cercle: son diamètre. Polygone: le "
                                 "cercle dans lequel il est INSCRIT. "
                                 "Spirale: le cercle extérieur."),
            ParameterDef("sides", "Nb de côtés", ParameterType.INT,
                         default=6, min_value=3, max_value=64,
                         unit="", group="Tracé"),
            ParameterDef("inner_diameter", "Ø intérieur",
                         ParameterType.FLOAT, default=5.0,
                         min_value=0.0, max_value=2000.0, unit="mm",
                         group="Tracé",
                         tooltip="Spirale: cercle intérieur"),
            ParameterDef("spiral_from", "Départ",
                         ParameterType.CHOICE, default="Extérieur",
                         choices=["Extérieur", "Intérieur"], unit="",
                         group="Tracé"),
            ParameterDef("pitch_xy", "Pas XY", ParameterType.FLOAT,
                         default=2.0, min_value=0.05, max_value=100.0,
                         unit="mm", group="Tracé",
                         tooltip="Spirale: écart radial par tour"),
            ParameterDef("rotation", "Rotation",
                         ParameterType.FLOAT, default=0.0,
                         min_value=-360.0, max_value=360.0, unit="°",
                         group="Tracé"),
            ParameterDef("closed", "Fermer le tracé",
                         ParameterType.BOOL, default=True, unit="",
                         group="Tracé",
                         tooltip="Revient au point de départ "
                                 "(sans effet sur une spirale)"),
            ParameterDef("texte_fil", "Texte", ParameterType.STRING,
                         default="NeoDrive", unit="", group="Tracé",
                         multiline=True,
                         tooltip="Gravé en TRAIT SIMPLE: l'outil passe "
                                 "une fois par trait, comme une plume "
                                 "(police à trait simple de NeoDrive). "
                                 "Lisible en petit, là où le contour "
                                 "d'une police s'empâte."),
            ParameterDef("hauteur_fil", "Hauteur de capitale",
                         ParameterType.FLOAT, default=3.0,
                         min_value=0.2, max_value=500.0, unit="mm",
                         group="Tracé"),
            ParameterDef("alignement_fil", "Alignement",
                         ParameterType.CHOICE, default="Centre",
                         choices=list(cls.ALIGNEMENTS_FIL), unit="",
                         group="Tracé",
                         tooltip="Où le point de l'opération tombe dans "
                                 "le texte (sur la ligne de base de la "
                                 "première ligne)."),
            ParameterDef("interligne_fil", "Interligne",
                         ParameterType.FLOAT, default=1.6,
                         min_value=0.5, max_value=5.0, unit="",
                         group="Tracé",
                         tooltip="En hauteurs de capitale, d'une ligne "
                                 "à la suivante."),
            ParameterDef("disposition_fil", "Disposition",
                         ParameterType.CHOICE, default="Ligne droite",
                         choices=["Ligne droite", "Arc (dessus)",
                                  "Arc (dessous)", "Le long du dessin"],
                         unit="", group="Tracé",
                         tooltip="Arc: centré sur le point de "
                                 "l'opération, la ligne de base au "
                                 "rayon donné — « dessus » se lit en "
                                 "haut du cercle, « dessous » en bas; "
                                 "la rotation déplace le texte autour "
                                 "du cercle.\nLe long du dessin: le "
                                 "contour repris au canvas (bouton "
                                 "« Reprendre les contours "
                                 "sélectionnés »), dans son sens."),
            ParameterDef("rayon_fil", "Rayon de l'arc",
                         ParameterType.FLOAT, default=20.0,
                         min_value=0.5, max_value=5000.0, unit="mm",
                         group="Tracé",
                         tooltip="Rayon de la ligne de base du texte."),

            ParameterDef("cote_outil", "Côté de l'outil",
                         ParameterType.CHOICE,
                         default="Centre sur le contour",
                         choices=list(cls.COTES), unit="",
                         group="Décalage",
                         tooltip="Centre: la fraise suit le tracé.\n"
                                 "Intérieur: découpe intérieure, "
                                 "l'outil à un rayon DEDANS.\n"
                                 "Extérieur: détourage, l'outil à un "
                                 "rayon DEHORS.\nLe rayon est celui de "
                                 "l'outil de l'opération."),
            ParameterDef("surepaisseur_xy", "Matière laissée en XY",
                         ParameterType.FLOAT, default=0.0,
                         min_value=0.0, max_value=50.0, unit="mm",
                         group="Décalage",
                         tooltip="Intérieur/extérieur: l'outil s'écarte "
                                 "encore d'autant du contour — la "
                                 "matière qu'une finition reprendra."),
            ParameterDef("offset_side", "Décalage manuel",
                         ParameterType.CHOICE, default="Aucun",
                         choices=["Aucun", "Extérieur", "Intérieur"],
                         unit="", group="Décalage", expert_only=True,
                         tooltip="Décale le tracé d'une distance "
                                 "donnée à la main (avant le côté de "
                                 "l'outil)."),
            ParameterDef("offset_dist", "Distance manuelle",
                         ParameterType.FLOAT, default=0.0,
                         min_value=0.0, max_value=200.0, unit="mm",
                         group="Décalage", expert_only=True),

            ParameterDef("depth", "Profondeur", ParameterType.FLOAT,
                         default=1.0, min_value=0.0, max_value=200.0,
                         unit="mm", group="Profondeur"),
            ParameterDef("infeed_z", "Passe Z", ParameterType.FLOAT,
                         default=0.5, min_value=0.01, max_value=50.0,
                         unit="mm", group="Profondeur",
                         tooltip="Profondeur retirée par passe"),

            ParameterDef("arcs", "Arcs de cercle (Arc)",
                         ParameterType.BOOL, default=False, unit="",
                         group="Séquence",
                         tooltip="Les suites de segments qui dessinent "
                                 "un cercle sortent en « Arc CW/CCW » "
                                 "(le format des fichiers Datron de "
                                 "l'atelier): la machine suit le vrai "
                                 "cercle, le programme est plus court."),
            ParameterDef("tolerance_arcs", "Tolérance des arcs",
                         ParameterType.FLOAT, default=0.005,
                         min_value=0.0005, max_value=1.0, unit="mm",
                         group="Séquence", expert_only=True,
                         tooltip="Écart toléré entre les sommets du "
                                 "tracé et l'arc qui les remplace."),
            ParameterDef("sequence_name", "Nom séquence",
                         ParameterType.STRING, default="TRACE_1",
                         unit="", group="Séquence", expert_only=True,
                         tooltip="Nom du bloc $$$ (rendu unique à la "
                                 "génération)"),
        ]

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        return ToolRequirement(tool_types=[], description="Tout outil")

    # ── Géométrie ──

    @classmethod
    def cote(cls, params: Dict[str, Any]) -> int:
        """0 = centre, -1 = intérieur, +1 = extérieur."""
        c = str(params.get('cote_outil') or cls.COTES[0])
        if c.startswith("Intérieur"):
            return -1
        if c.startswith("Extérieur"):
            return 1
        return 0

    @staticmethod
    def _ferme(pts) -> bool:
        return (len(pts) >= 4 and abs(pts[0][0] - pts[-1][0]) < 1e-9
                and abs(pts[0][1] - pts[-1][1]) < 1e-9)

    @classmethod
    def chemins(cls, params: Dict[str, Any], x: float = 0.0,
                y: float = 0.0, op_points: List[Dict] = None
                ) -> List[List[Tuple]]:
        """Les parcours du CENTRE de la fraise: un par contour (une
        découpe intérieure trop étroite pour l'outil n'en a pas; un
        contour qui se sépare en deux en a deux). Le diamètre de
        l'outil est `_diametre_outil` (posé par le générateur et les
        dessins)."""
        if str(params.get('shape')) == "Texte":
            # des traits OUVERTS: le centre de la fraise les suit,
            # aucun côté d'outil
            return cls.traits_texte(params, x, y)
        if str(params.get('shape')) == "Dessin" and params.get('contours'):
            bruts = []
            for contour in params.get('contours') or []:
                sous = dict(params, path_points=contour, contours=None)
                p = cls.path_points(sous, x, y, op_points, compenser=False)
                if len(p) >= 2:
                    bruts.append(p)
        else:
            p = cls.path_points(params, x, y, op_points, compenser=False)
            bruts = [p] if len(p) >= 2 else []
        sens = cls.cote(params)
        if not sens:
            return bruts
        try:
            d = float(params.get('_diametre_outil') or 0.0)
            s = float(params.get('surepaisseur_xy') or 0.0)
        except (TypeError, ValueError):
            d, s = 0.0, 0.0
        distance = sens * (max(0.0, d) / 2.0 + max(0.0, s))
        sortie = []
        for p in bruts:
            if not cls._ferme(p) or abs(distance) < 1e-9:
                sortie.append(p)
                continue
            sortie += cls._decaler(p, distance)
        return sortie

    @staticmethod
    def _decaler(pts, distance: float) -> List[List[Tuple]]:
        """Un contour fermé décalé de `distance` (>0 dehors), coins
        arrondis: [contour fermé] — vide s'il disparaît (l'outil n'y
        entre pas), plusieurs s'il se sépare."""
        try:
            from shapely.geometry import Polygon
        except ImportError:                       # pragma: no cover
            return [list(pts)]
        poly = Polygon(pts)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty:
            return []
        dec = poly.buffer(distance, quad_segs=16, join_style=1)
        if dec.is_empty:
            return []
        dec = dec.simplify(0.002)
        sortie = []
        for g in getattr(dec, 'geoms', [dec]):
            ext = getattr(g, 'exterior', None)
            if ext is None or g.area < 1e-9:
                continue
            anneau = [(round(px, 4), round(py, 4)) for px, py in ext.coords]
            # le sens du contour d'origine (shapely le rend à sa façon)
            sortie.append(anneau)
        return sortie

    @classmethod
    def path_points(cls, params: Dict[str, Any],
                    x: float = 0.0, y: float = 0.0,
                    op_points: List[Dict] = None,
                    compenser: bool = True) -> List[Tuple]:
        """Parcours du CENTRE de la fraise, en coordonnées machine —
        le premier de `chemins` (le côté de l'outil compris, sauf
        `compenser=False`: le tracé seul).

        Retourne [(x, y), …]. Liste vide si la forme est dégénérée —
        on ne trace pas un parcours de dimension nulle."""
        if compenser and (cls.cote(params) or (
                str(params.get('shape')) == "Dessin"
                and params.get('contours'))):
            tous = cls.chemins(params, x, y, op_points)
            return tous[0] if tous else []
        shape = str(params.get('shape', 'Rectangle'))

        def _f(key, default=0.0):
            try:
                return float(params.get(key, default) or 0.0)
            except (TypeError, ValueError):
                return 0.0

        angle0 = math.radians(_f('rotation'))
        closed = bool(params.get('closed', True))

        # Décalage: sur les formes paramétriques il s'applique aux
        # COTES (exact), sur un contour quelconque aux sommets
        side = str(params.get('offset_side', 'Aucun'))
        dist = abs(_f('offset_dist'))
        signed = 0.0
        if dist > 0 and side in ("Extérieur", "Intérieur"):
            signed = dist if side == "Extérieur" else -dist

        if shape == "Dessin":
            # Contour relevé sur le canvas: les sommets sont stockés
            # tels quels, en coordonnées machine ABSOLUES — le point
            # de l'opération ne les décale pas
            raw = params.get('path_points') or []
            pts = []
            for entry in raw:
                try:
                    pts.append((float(entry[0]), float(entry[1])))
                except (TypeError, ValueError, IndexError):
                    continue
            open_ends = (len(pts) >= 3
                         and (abs(pts[0][0] - pts[-1][0]) > 1e-9
                              or abs(pts[0][1] - pts[-1][1]) > 1e-9))
            if closed and open_ends:
                pts.append(pts[0])
            return cls._offset_closed(pts, signed) if signed else pts

        if shape == "Points":
            pts = [(float(p.get('x', 0.0)), float(p.get('y', 0.0)))
                   for p in (op_points or [])]
            if len(pts) >= 3 and closed:
                pts.append(pts[0])
            return cls._offset_closed(pts, signed) if signed else pts

        if shape == "Rectangle":
            wx = _f('width_x') + 2 * signed
            wy = _f('width_y') + 2 * signed
            if wx <= 0 or wy <= 0:
                return []
            hx, hy = wx / 2.0, wy / 2.0
            corners = [(-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy)]
            pts = [cls._rotate(cx, cy, angle0) for cx, cy in corners]
            if closed:
                pts.append(pts[0])
            return [(x + px, y + py) for px, py in pts]

        if shape in ("Cercle", "Polygone"):
            d = _f('diameter')
            if d <= 0:
                return []
            r = d / 2.0
            if shape == "Polygone":
                n = max(3, int(params.get('sides', 6) or 6))
                # Décaler les CÔTÉS de `signed` déplace l'apothème
                # d'autant: le rayon circonscrit suit en 1/cos(pi/n)
                r += signed / math.cos(math.pi / n)
            else:
                n = max(8, int(round(360.0 / cls._ARC_STEP_DEG)))
                r += signed
            if r <= 0:
                return []
            pts = []
            for i in range(n):
                a = angle0 + 2 * math.pi * i / n
                pts.append((x + r * math.cos(a), y + r * math.sin(a)))
            if closed:
                pts.append(pts[0])
            return pts

        if shape == "Spirale":
            return cls._spiral_points(params, x, y, angle0)

        if shape == "Texte":
            tous = cls.traits_texte(params, x, y)
            return tous[0] if tous else []

        return []

    @classmethod
    def traits_texte(cls, params: Dict[str, Any], x: float = 0.0,
                     y: float = 0.0) -> List[List[Tuple]]:
        """Forme Texte: les traits du texte (police à trait simple,
        src/core/police_fil), placés au point de l'opération."""
        from src.core import police_fil

        def _f(key, default):
            try:
                return float(params.get(key, default))
            except (TypeError, ValueError):
                return default
        from src.core import texte_courbe as tc
        texte = str(params.get('texte_fil') or "")
        alignement = {'Gauche': 'gauche', 'Droite': 'droite'}.get(
            str(params.get('alignement_fil') or "Centre"), 'centre')
        hauteur = _f('hauteur_fil', 3.0)
        interligne = _f('interligne_fil', 1.6)
        disposition = str(params.get('disposition_fil') or "Ligne droite")
        chemin = None
        if disposition == "Le long du dessin":
            try:
                chemin = [(float(p[0]), float(p[1]))
                          for p in params.get('path_points') or []]
            except (TypeError, ValueError, IndexError):
                chemin = None
        if disposition == "Ligne droite" or tc.support_depuis(
                disposition, x, y, _f('rayon_fil', 20.0), 0.0,
                chemin) is None:
            traits = police_fil.texte_place(
                texte, hauteur, alignement=alignement,
                interligne=interligne, rotation=_f('rotation', 0.0))
            return [[(x + px, y + py) for px, py in t] for t in traits
                    if len(t) >= 2]
        traits = []
        for n, ligne in enumerate(texte.splitlines() or [""]):
            glyphes = police_fil.glyphes_ligne(ligne, hauteur)
            decale = n * interligne * hauteur
            if disposition.startswith("Arc"):
                # chaque ligne a son cercle: la suivante plus près du
                # centre (dessus) ou plus loin (dessous)
                rayon = _f('rayon_fil', 20.0) + (
                    -decale if "dessus" in disposition else decale)
                support = tc.support_depuis(disposition, x, y,
                                            max(0.1, rayon),
                                            _f('rotation', 0.0))
            else:
                support = tc.support_depuis(disposition, x, y, 0.0, 0.0,
                                            chemin)
                glyphes = [(gx, lg, [[(u, v - decale) for u, v in t]
                                     for t in ts])
                           for gx, lg, ts in glyphes]
            traits += tc.poser_glyphes(glyphes, support, alignement)
        return [t for t in traits if len(t) >= 2]


    @classmethod
    def _offset_closed(cls, pts: List[Tuple],
                       distance: float) -> List[Tuple]:
        """Décale un contour FERMÉ de `distance` (>0 vers l'extérieur).

        Chaque côté est déporté de sa normale, puis les côtés voisins
        sont recoupés (raccord en onglet). Exact sur un contour
        convexe; sur un contour rentrant, un décalage plus grand que
        le plus petit rayon local peut créer une boucle — c'est la
        limite de la méthode, et c'est pourquoi la distance reste à la
        main de l'utilisateur."""
        if len(pts) < 4 or abs(distance) < 1e-9:
            return list(pts)
        ring = pts[:-1] if (abs(pts[0][0] - pts[-1][0]) < 1e-9
                            and abs(pts[0][1] - pts[-1][1]) < 1e-9) \
            else list(pts)
        n = len(ring)
        if n < 3:
            return list(pts)
        # Sens de parcours: aire signée. Positive = trigonométrique,
        # la normale extérieure est alors à droite du sens de marche.
        area = 0.0
        for i in range(n):
            x1, y1 = ring[i]
            x2, y2 = ring[(i + 1) % n]
            area += x1 * y2 - x2 * y1
        sign = 1.0 if area > 0 else -1.0
        d = distance * sign

        lines = []
        for i in range(n):
            x1, y1 = ring[i]
            x2, y2 = ring[(i + 1) % n]
            dx, dy = x2 - x1, y2 - y1
            length = math.hypot(dx, dy)
            if length < 1e-9:
                continue
            nx, ny = dy / length, -dx / length      # normale droite
            lines.append((x1 + nx * d, y1 + ny * d,
                          x2 + nx * d, y2 + ny * d))
        if len(lines) < 3:
            return list(pts)

        out = []
        for i, line in enumerate(lines):
            prev = lines[i - 1]
            inter = cls._intersect(prev, line)
            out.append(inter if inter is not None else (line[0], line[1]))
        out.append(out[0])
        return out

    @staticmethod
    def _intersect(a, b):
        """Intersection de deux segments infinis, None si parallèles."""
        x1, y1, x2, y2 = a
        x3, y3, x4, y4 = b
        den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        if abs(den) < 1e-12:
            return None
        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))

    @staticmethod
    def _rotate(px: float, py: float, angle: float) -> Tuple:
        if not angle:
            return px, py
        ca, sa = math.cos(angle), math.sin(angle)
        return px * ca - py * sa, px * sa + py * ca

    @classmethod
    def _spiral_points(cls, params, x, y, angle0) -> List[Tuple]:
        """Spirale d'Archimède entre deux cercles.

        Le pas XY est l'écart RADIAL par tour: c'est la prise de passe
        latérale, la grandeur que règle un fraiseur."""
        def _f(key, default=0.0):
            try:
                return float(params.get(key, default) or 0.0)
            except (TypeError, ValueError):
                return 0.0

        r_out = _f('diameter') / 2.0
        r_in = _f('inner_diameter') / 2.0
        pitch = _f('pitch_xy')
        if r_out <= 0 or pitch <= 0 or abs(r_out - r_in) < 1e-6:
            return []
        r_in = max(0.0, min(r_in, r_out))
        outward = str(params.get('spiral_from', 'Extérieur')) \
            == "Intérieur"
        r_start, r_end = ((r_in, r_out) if outward
                          else (r_out, r_in))

        turns = abs(r_end - r_start) / pitch
        steps = max(8, int(turns * 360.0 / cls._ARC_STEP_DEG))
        pts = []
        for i in range(steps + 1):
            t = i / steps
            r = r_start + (r_end - r_start) * t
            a = angle0 + 2 * math.pi * turns * t * (1 if outward else -1)
            pts.append((x + r * math.cos(a), y + r * math.sin(a)))
        return pts

    # ── Génération ──

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        """Dans le sous-programme: appel de la séquence."""
        name = str(params.get('sequence_name', 'TRACE_1')).strip() \
            or "TRACE_1"
        return f"    {name}"

    @classmethod
    def z_levels(cls, params: Dict[str, Any]) -> List[float]:
        """Profondeurs successives, la dernière tombant sur la cote."""
        def _f(key, default=0.0):
            try:
                return float(params.get(key, default) or 0.0)
            except (TypeError, ValueError):
                return 0.0

        depth = abs(_f('depth'))
        step = abs(_f('infeed_z')) or depth
        if depth <= 0:
            return []
        if step <= 0 or step >= depth:
            return [-depth]
        levels = []
        z = step
        while z < depth - 1e-9:
            levels.append(-round(z, 4))
            z += step
        levels.append(-round(depth, 4))
        return levels

    #: parcours déjà calculés (signature → bloc). Le programme est
    #: régénéré à CHAQUE frappe: sans cache, une spirale fine
    #: recalculait ses 200 000 lignes pour la modification d'une
    #: autre opération.
    _BLOCK_CACHE: Dict[tuple, str] = {}
    _CACHE_MAX = 16

    @classmethod
    def _signature(cls, params: Dict[str, Any], x: float, y: float,
                   op_points: List[Dict] = None) -> tuple:
        keys = ('shape', 'width_x', 'width_y', 'diameter', 'sides',
                'inner_diameter', 'spiral_from', 'pitch_xy',
                'rotation', 'closed', 'offset_side', 'offset_dist',
                'depth', 'infeed_z', 'sequence_name',
                '_safe_rapid_z', '_stroke_cutting_z', 'cote_outil',
                'surepaisseur_xy', '_diametre_outil', 'arcs',
                'tolerance_arcs', 'texte_fil', 'hauteur_fil',
                'alignement_fil', 'interligne_fil')
        sig = tuple(params.get(k) for k in keys)
        path = tuple(tuple(p) for p in (params.get('path_points') or []))
        path += tuple(tuple(tuple(p) for p in c)
                      for c in (params.get('contours') or []))
        pts = tuple((p.get('x'), p.get('y'))
                    for p in (op_points or []))
        return sig + (x, y, path, pts)

    @classmethod
    def build_sequence_block(cls, params: Dict[str, Any],
                             x: float = 0.0, y: float = 0.0,
                             op_points: List[Dict] = None) -> str:
        """Bloc $$$ du parcours, une boucle par passe en Z.

        En génération manuelle, le bloc figé est réémis tel quel: on
        ne recalcule pas un parcours que l'utilisateur n'a pas
        redemandé."""
        if params.get('manual_seq'):
            frozen = str(params.get('frozen_seq', '') or '')
            if frozen.strip():
                name = str(params.get('sequence_name', 'TRACE_1')
                           ).strip() or "TRACE_1"
                # Le nom peut avoir été rendu unique depuis le gel
                _first, _nl, rest = frozen.partition("\n")
                return f"$$$ {name}\n{rest}" if rest else frozen
        key = cls._signature(params, x, y, op_points)
        cached = cls._BLOCK_CACHE.get(key)
        if cached is not None:
            return cached
        block = cls._compute_sequence_block(params, x, y, op_points)
        if len(cls._BLOCK_CACHE) >= cls._CACHE_MAX:
            cls._BLOCK_CACHE.pop(next(iter(cls._BLOCK_CACHE)))
        cls._BLOCK_CACHE[key] = block
        return block

    @classmethod
    def _compute_sequence_block(cls, params: Dict[str, Any],
                                x: float = 0.0, y: float = 0.0,
                                op_points: List[Dict] = None) -> str:
        name = str(params.get('sequence_name', 'TRACE_1')).strip() \
            or "TRACE_1"
        tous = [p for p in cls.chemins(params, x, y, op_points)
                if len(p) >= 2]
        levels = cls.z_levels(params)
        if not tous or not levels:
            return ""
        try:
            safe_z = float(params.get('_safe_rapid_z', 15) or 15)
        except (TypeError, ValueError):
            safe_z = 15.0
        try:
            approach = float(params.get('_stroke_cutting_z', 1) or 1)
        except (TypeError, ValueError):
            approach = 1.0

        x0, y0 = tous[0][0]
        lines = [f"$$$ {name}",
                 f"PrePositioning X={x0:g} Y={y0:g} Z={safe_z:g}",
                 f"Rapid Z={approach:g}"]
        avec_arcs = bool(params.get('arcs', False))
        try:
            tol_arcs = float(params.get('tolerance_arcs', 0.005) or 0.005)
        except (TypeError, ValueError):
            tol_arcs = 0.005
        for n, pts in enumerate(tous):
            x0, y0 = pts[0]
            if n:
                # le contour suivant: dégager, se placer, redescendre
                lines.append(f"Rapid Z={approach:g}")
                lines.append(f"Rapid X={round(x0, 4):g} Y={round(y0, 4):g}")
            segments = None
            if avec_arcs:
                from src.core import arcs as _arcs
                segments = _arcs.ajuster(pts, tol_arcs)
                if not any(sg[0] == 'A' for sg in segments):
                    segments = None
            for level in levels:
                lines.append("Feed Plunge")
                lines.append(f"Line Z={level:g}")
                lines.append("Feed Finishing")
                prev = (x0, y0)
                if segments is not None:
                    # les arcs retrouvés: « Arc CW|CCW X Y dX dY »
                    for sg in segments:
                        ligne = _arcs.ligne_simpl(prev, sg)
                        if ligne:
                            lines.append(ligne)
                        prev = (round(sg[1][0], 4), round(sg[1][1], 4))
                    pts_fin = segments[-1][1] if segments else (x0, y0)
                    prev = (pts_fin[0], pts_fin[1])
                for px, py in ([] if segments is not None else pts[1:]):
                    parts = []
                    if abs(px - prev[0]) > 1e-9:
                        parts.append(f"X={round(px, 4):g}")
                    if abs(py - prev[1]) > 1e-9:
                        parts.append(f"Y={round(py, 4):g}")
                    if parts:
                        lines.append("Line " + " ".join(parts))
                    prev = (px, py)
                # Retour au départ pour la passe suivante (coordonnées
                # modales: seuls les axes qui changent sont réécrits)
                if level is not levels[-1] and prev != (x0, y0):
                    if math.hypot(prev[0] - x0, prev[1] - y0) <= 1e-3:
                        # contour fermé: c'est son dernier côté
                        lines.append(f"Line X={x0:g} Y={y0:g}")
                    else:
                        # contour OUVERT: remonter, revenir en rapide,
                        # redescendre à la passe suivante. Revenir en
                        # Line à la profondeur usinait le côté que le
                        # tracé exclut (le 4e côté d'un U).
                        lines.append(f"Rapid Z={approach:g}")
                        lines.append(f"Rapid X={x0:g} Y={y0:g}")
                    prev = (x0, y0)
        lines.append(f"Rapid Z={safe_z:g}")
        return "\n".join(lines)

    @classmethod
    def validate_params(cls, params: Dict[str, Any]) -> List[str]:
        errors = super().validate_params(params)
        shape = str(params.get('shape', 'Rectangle'))
        if shape == "Dessin" and not (params.get('path_points') or []) \
                and not (params.get('contours') or []):
            errors.append(
                "Aucun contour relevé — sélectionnez une polyligne au "
                "canvas puis « Reprendre le contour sélectionné »")
        if shape == "Spirale":
            try:
                d_out = float(params.get('diameter', 0) or 0)
                d_in = float(params.get('inner_diameter', 0) or 0)
            except (TypeError, ValueError):
                d_out = d_in = 0.0
            if d_in >= d_out:
                errors.append(
                    "Spirale: le Ø intérieur doit être plus petit que "
                    "le Ø extérieur")
        if not cls.z_levels(params):
            errors.append("Profondeur nulle: rien à usiner")
        return errors
