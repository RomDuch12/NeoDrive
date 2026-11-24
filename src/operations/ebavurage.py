# -*- coding: utf-8 -*-
"""L'ébavurage: un passage à l'offset d'un contour, le centre de
l'outil SUR la ligne.

Une découpe laisse une arête vive; on y passe un extrad (fraise à
rayon extérieur), un chanfrein ou une conique, à quelques dixièmes
de profondeur, à une distance choisie du bord — l'offset: c'est là
que le CENTRE de l'outil passe (« Over » pour la machine, pas de
compensation). Un extrad à 1 mm du bord d'un rectangle: le
rectangle s'agrandit de deux fois l'offset en X et en Y, et ses
rayons de coin de l'offset. Même règle pour un cercle, et pour des
contours fermés venus d'un DXF, où l'on choisit le côté.

L'opération se crée d'un clic droit sur une découpe (côté
extérieur), une poche (côté intérieur) ou un contour, avec un
MODÈLE — outil, offset, profondeur — retenu dans data/ebavurage.json
(voir `ebavurage_modeles`). Elle garde sa propre géométrie: on peut
la retoucher, ou la reprendre de sa source.
"""

from typing import Any, Dict, List

from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement,
    REPEAT_PARAMS
)
from src.operations.registry import OperationRegistry

#: ce dont on fait le tour
FORMES = ("Rectangle", "Cercle", "Contours")
#: de quel côté du bord passe l'outil
COTES = ("Extérieur", "Intérieur")

#: les opérations dont un clic droit fait un ébavurage, et le côté
#: qui va de soi (None: on demande)
SOURCES = {
    "decoupe_rectangle": COTES[0], "poche_rectangle": COTES[1],
    "surfacage_rectangle": COTES[0], "decoupe_cercle": None,
    "surfacage_cercle": COTES[0], "percage_fraise": COTES[1],
    "contour_2d5": None, "gravure_2d5": None, "evidement_2d5": None,
    "texte_grave": None, "gamme_gravure": None,
}


@OperationRegistry.register("ebavurage")
class Ebavurage(AbstractOperation):
    """Un tour à l'offset, une passe, le centre de l'outil sur la
    ligne."""

    OP_TYPE = "ebavurage"
    DISPLAY_NAME = "Ébavurage"
    CATEGORY = "Découpe"
    DESCRIPTION = ("Un passage à l'offset d'un rectangle, d'un cercle "
                   "ou de contours fermés — extrad, chanfrein ou "
                   "conique, le centre de l'outil sur la ligne")
    ICON = "cut_rect"
    INLINE = False
    REQUIRES_TOOL = True
    REQUIRES_COORDINATES = True
    SUPPORTS_MULTI_POINT = False
    PREFIXE_SEQ = "EBAVURAGE"

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return [
            ParameterDef("forme", "Forme", ParameterType.CHOICE,
                         default=FORMES[0], choices=list(FORMES),
                         unit="", group="Ébavurage",
                         tooltip="Ce dont on fait le tour: le "
                                 "rectangle ou le cercle donné ici, "
                                 "ou des contours fermés (bouton "
                                 "« Appliquer les courbes »)."),
            ParameterDef("cote", "Côté", ParameterType.CHOICE,
                         default=COTES[0], choices=list(COTES),
                         unit="", group="Ébavurage",
                         tooltip="Extérieur: l'outil passe DEHORS, à "
                                 "l'offset du bord (une découpe). "
                                 "Intérieur: dedans (une poche, un "
                                 "trou)."),
            ParameterDef("offset", "Offset", ParameterType.FLOAT,
                         default=1.0, min_value=0.0, max_value=50.0,
                         unit="mm", group="Ébavurage",
                         tooltip="Distance du bord au CENTRE de "
                                 "l'outil (« Over »: pas de "
                                 "compensation). Un extrad à 1: "
                                 "le rectangle grandit de 2 en X et "
                                 "en Y."),
            ParameterDef("depth", "Pz", ParameterType.FLOAT,
                         default=0.2, min_value=0.01, max_value=50.0,
                         unit="mm", group="Ébavurage",
                         tooltip="Profondeur du passage, en une "
                                 "descente."),
            ParameterDef("width_x", "Largeur X", ParameterType.FLOAT,
                         default=40.0, min_value=0.1, unit="mm",
                         group="Rectangle"),
            ParameterDef("width_y", "Largeur Y", ParameterType.FLOAT,
                         default=30.0, min_value=0.1, unit="mm",
                         group="Rectangle"),
            ParameterDef("corner_radius", "Rayon coins",
                         ParameterType.FLOAT, default=0.0,
                         min_value=0.0, unit="mm", group="Rectangle"),
            ParameterDef("diameter", "Diamètre", ParameterType.FLOAT,
                         default=10.0, min_value=0.1, unit="mm",
                         group="Cercle"),
            ParameterDef("source_id", "Source", ParameterType.STRING,
                         default="", unit="", group="Ébavurage",
                         expert_only=True,
                         tooltip="L'opération dont la géométrie a été "
                                 "reprise (bouton « Reprendre la "
                                 "géométrie de la source »)."),
            ParameterDef("contours", "Contours", ParameterType.STRING,
                         default="", unit="", group="Contours",
                         expert_only=True,
                         tooltip="Contours fermés relevés au canvas "
                                 "(coordonnées machine)."),
            ParameterDef("sequence_name", "Nom séquence",
                         ParameterType.STRING, default="",
                         unit="", group="Séquence", expert_only=True,
                         tooltip="Nom du bloc $$$ des contours (rendu "
                                 "unique à la génération)"),
        ] + REPEAT_PARAMS

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        return ToolRequirement(
            tool_types=[],
            description="Extrad, chanfrein ou conique")

    # ── la géométrie ──

    @staticmethod
    def _f(params: Dict[str, Any], cle: str, defaut: float = 0.0) -> float:
        try:
            valeur = params.get(cle, defaut)
            return float(defaut if valeur in (None, "") else valeur)
        except (TypeError, ValueError):
            return float(defaut)

    @classmethod
    def signe(cls, params: Dict[str, Any]) -> float:
        """+1 dehors, -1 dedans."""
        return -1.0 if str(params.get('cote', COTES[0])) == COTES[1] \
            else 1.0

    @classmethod
    def forme(cls, params: Dict[str, Any]) -> str:
        forme = str(params.get('forme') or FORMES[0])
        return forme if forme in FORMES else FORMES[0]

    @classmethod
    def rectangle_offset(cls, params: Dict[str, Any]) -> tuple:
        """(largeur, hauteur, rayon) du tour, offset compris."""
        d = cls.signe(params) * cls._f(params, 'offset')
        largeur = max(0.01, cls._f(params, 'width_x') + 2.0 * d)
        hauteur = max(0.01, cls._f(params, 'width_y') + 2.0 * d)
        rayon = max(0.0, cls._f(params, 'corner_radius') + d)
        rayon = min(rayon, largeur / 2.0, hauteur / 2.0)
        return (round(largeur, 4), round(hauteur, 4), round(rayon, 4))

    @classmethod
    def diametre_offset(cls, params: Dict[str, Any]) -> float:
        d = cls.signe(params) * cls._f(params, 'offset')
        return round(max(0.01, cls._f(params, 'diameter') + 2.0 * d), 4)

    @staticmethod
    def contours(params: Dict[str, Any]) -> List[List]:
        """Les contours fermés relevés, en machine."""
        bruts = params.get('contours') or []
        if isinstance(bruts, str):
            return []
        sortie = []
        for contour in bruts:
            points = []
            for entree in contour or []:
                try:
                    points.append((float(entree[0]), float(entree[1])))
                except (TypeError, ValueError, IndexError):
                    continue
            if len(points) >= 3:
                sortie.append(points)
        return sortie

    @classmethod
    def anneaux(cls, params: Dict[str, Any]) -> List[List]:
        """Les tours à l'offset des contours: dehors, les lettres
        grossissent et leurs trous rétrécissent; dedans, l'inverse.
        Coordonnées machine."""
        from src.core import vcarve
        contours = cls.contours(params)
        if not contours:
            return []
        zone = vcarve.zone(contours)
        if zone is None or zone.is_empty:
            return []
        d = cls.signe(params) * cls._f(params, 'offset')
        if abs(d) > 1e-9:
            zone = zone.buffer(d, quad_segs=vcarve.QUADRANTS, join_style=1)
        if zone is None or zone.is_empty:
            return []
        return vcarve._anneaux(zone)

    # ── le code ──

    @classmethod
    def nom_sequence(cls, params: Dict[str, Any]) -> str:
        nom = str(params.get('sequence_name', '') or '').strip()
        return nom or f"{cls.PREFIXE_SEQ}_1"

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        p = {**cls.get_default_params(), **params}
        srz = p.get('_stroke_rapid_z', 15)
        scz = p.get('_stroke_cutting_z', 1)
        profondeur = cls._f(p, 'depth', 0.3)
        forme = cls.forme(p)
        if forme == "Rectangle":
            largeur, hauteur, rayon = cls.rectangle_offset(p)
            return (f"    RectFromMid (widthX={largeur:g} widthY={hauteur:g} "
                    f"cornerRadius={rayon:g} Over diagonalInfeed=false "
                    f"depth={profondeur:g} infeedZ={profondeur:g} "
                    f"strokeRapidZ={srz} strokeCuttingZ={scz} "
                    f"finishingXY=0 infeedFinishingZ=0)")
        if forme == "Cercle":
            return (f"    CircleFromMid (diameter={cls.diametre_offset(p):g} "
                    f"Over depth={profondeur:g} infeedZ={profondeur:g} "
                    f"strokeRapidZ={srz} strokeCuttingZ={scz} "
                    f"finishingXY=0 finishingZ=0 infeedFinishingZ=0)")
        return f"    {cls.nom_sequence(p)}"

    @classmethod
    def build_sequence_block(cls, params: Dict[str, Any]) -> str:
        """Le bloc $$$ des contours: chaque tour, à la cote, en une
        passe; l'outil dégage entre deux tours."""
        anneaux = cls.anneaux(params)
        if not anneaux:
            return ""
        safe_z = cls._f(params, '_safe_rapid_z', 15.0)
        approche = cls._f(params, '_stroke_cutting_z', 1.0)
        profondeur = cls._f(params, 'depth', 0.3)
        lignes = [f"$$$ {cls.nom_sequence(params)}", "Spindle On"]
        premier = True
        for anneau in anneaux:
            if len(anneau) < 2:
                continue
            x0, y0 = anneau[0][0], anneau[0][1]
            if premier:
                lignes.append(f"PrePositioning X={round(x0, 4):g} "
                              f"Y={round(y0, 4):g} Z={safe_z:g}")
                premier = False
            else:
                lignes.append(f"Rapid Z={approche:g}")
                lignes.append(f"Rapid X={round(x0, 4):g} "
                              f"Y={round(y0, 4):g}")
            lignes.append(f"Rapid Z={approche:g}")
            lignes.append("Feed Plunge")
            lignes.append(f"Line Z={-abs(profondeur):g}")
            lignes.append("Feed Finishing")
            for x, y in anneau[1:]:
                lignes.append(f"Line X={round(x, 4):g} Y={round(y, 4):g}")
        if premier:
            return ""
        lignes.append(f"Rapid Z={safe_z:g}")
        lignes.append("MoveToSafetyPosition")
        return "\n".join(lignes)

    @classmethod
    def validate_params(cls, params: Dict[str, Any]) -> List[str]:
        erreurs = super().validate_params(params)
        if cls.forme(params) == "Contours" and not cls.contours(params):
            erreurs.append("Aucun contour: sélectionnez au canvas les "
                           "courbes fermées à ébavurer, puis "
                           "« Appliquer les courbes sélectionnées ».")
        return erreurs

    @classmethod
    def resume(cls, params: Dict[str, Any], calculer: bool = True) -> str:
        cote = "extérieur" if cls.signe(params) > 0 else "intérieur"
        offset = cls._f(params, 'offset')
        profondeur = cls._f(params, 'depth', 0.3)
        forme = cls.forme(params)
        if forme == "Rectangle":
            largeur, hauteur, rayon = cls.rectangle_offset(params)
            quoi = f"rectangle {largeur:g} × {hauteur:g}, r {rayon:g}"
        elif forme == "Cercle":
            quoi = f"cercle Ø {cls.diametre_offset(params):g}"
        else:
            quoi = f"{len(cls.contours(params))} contour(s)"
        return (f"{quoi} — {cote}, offset {offset:g}, Pz {profondeur:g}")
