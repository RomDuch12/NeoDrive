"""Opération: Palpage d'une arête (EdgeMeasureV2) — inline.

Manuel SimPL 3.1.1, § 5.3.1.5 « Edge » (p. 271-278): le palpeur XYZ
reprend l'origine sur UNE arête de la pièce (et, si on le demande, son
orientation, par deux points symétriques). La position X/Y est celle
où le palpeur descend, au-dessus de la matière près de l'arête.

    SafeRapid X=0 Y=0 Z=5
    EdgeMeasureV2 direction=MeasuringDirection.XPositive
        zMeasureEdgeOffset=10 measureZOffset=-0.5
        offsetForRotation=50
        retractDistance=15 searchDistance=15 skipZMeasureResult=false
        skipZMeasure=false forceSafeHeight=false
        resultCs=CsType.Wcs originXShift=0 originYShift=0
        originZShift=0 stockEdgeOffset=0 stockZOffset=0
"""

from typing import Any, Dict, List

from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement
)
from src.operations.registry import OperationRegistry

#: l'arête palpée -> MeasuringDirection
DIRECTIONS = {"X+ (arête à droite)": "XPositive",
              "X− (arête à gauche)": "XNegative",
              "Y+ (arête derrière)": "YPositive",
              "Y− (arête devant)": "YNegative"}
#: où va le résultat -> CsType
RESULTATS = {"Repère pièce (Wcs)": "Wcs", "Repère local (Lcs)": "Lcs",
             "Aucun (valeur seule)": "None"}


def _oui(v) -> str:
    return "true" if v else "false"


@OperationRegistry.register("palpage_arete")
class PalpageArete(AbstractOperation):
    DISPLAY_NAME = "Palpage arête"
    CATEGORY = "Réglage"
    HORS_MATIERE = True
    DESCRIPTION = ("EdgeMeasureV2: origine (et orientation) reprises sur "
                   "une arête de la pièce")
    ICON = "ruler"
    # nouvelle (manuel SimPL): en expert par défaut
    EXPERT_ONLY = True
    INLINE = True
    REQUIRES_TOOL = False
    REQUIRES_COORDINATES = True

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        g, e = "Palpage", "Palpage expert"
        return [
            ParameterDef("direction", "Arête", ParameterType.CHOICE,
                         default="X+ (arête à droite)",
                         choices=list(DIRECTIONS), group=g,
                         tooltip="L'arête mesurée, par rapport au point "
                                 "de départ (direction)"),
            ParameterDef("z_edge_offset", "Point Z: distance à l'arête",
                         ParameterType.FLOAT, default=10.0, min_value=0.0,
                         max_value=500.0, unit="mm", group=g,
                         tooltip="Où le dessus est mesuré, depuis l'arête "
                                 "(zMeasureEdgeOffset; positif: vers la "
                                 "pièce)"),
            ParameterDef("measure_z_offset", "Hauteur de mesure",
                         ParameterType.FLOAT, default=-0.5, min_value=-200.0,
                         max_value=0.0, unit="mm", group=g,
                         tooltip="Sous le dessus, où l'arête est touchée "
                                 "(measureZOffset)"),
            ParameterDef("rotation_offset", "Écart pour l'orientation",
                         ParameterType.FLOAT, default=0.0, min_value=0.0,
                         max_value=2000.0, unit="mm", group=g,
                         tooltip="0: pas d'orientation. Sinon, deux points "
                                 "symétriques écartés d'autant mesurent "
                                 "l'angle de la pièce (offsetForRotation)"),
            ParameterDef("rotation_only", "Orientation seule",
                         ParameterType.BOOL, default=False, group=e,
                         expert_only=True,
                         tooltip="Garder l'angle, rejeter la position "
                                 "(setRotationOnly)"),
            ParameterDef("probe_safe_z", "Z d'approche", ParameterType.FLOAT,
                         default=5.0, min_value=0.0, max_value=200.0,
                         unit="mm", group=g),
            ParameterDef("skip_z_measure", "Ne pas mesurer Z",
                         ParameterType.BOOL, default=False, group=e,
                         expert_only=True),
            ParameterDef("skip_z_result", "Rejeter le Z mesuré",
                         ParameterType.BOOL, default=False, group=e,
                         expert_only=True),
            ParameterDef("force_safe_height", "Hauteur sûre entre les "
                         "points", ParameterType.BOOL, default=False,
                         group=e, expert_only=True),
            ParameterDef("retract", "Z après mesure", ParameterType.FLOAT,
                         default=15.0, min_value=0.0, unit="mm", group=e,
                         expert_only=True),
            ParameterDef("search", "Course de recherche",
                         ParameterType.FLOAT, default=15.0, min_value=1.0,
                         unit="mm", group=e, expert_only=True),
            ParameterDef("result", "Résultat", ParameterType.CHOICE,
                         default="Repère pièce (Wcs)",
                         choices=list(RESULTATS), group=e, expert_only=True),
            ParameterDef("origin_x_shift", "Décalage origine X",
                         ParameterType.FLOAT, default=0.0, group=e,
                         expert_only=True),
            ParameterDef("origin_y_shift", "Décalage origine Y",
                         ParameterType.FLOAT, default=0.0, group=e,
                         expert_only=True),
            ParameterDef("origin_z_shift", "Décalage origine Z",
                         ParameterType.FLOAT, default=0.0, group=e,
                         expert_only=True),
            ParameterDef("stock_edge", "Surépaisseur brut à l'arête",
                         ParameterType.FLOAT, default=0.0, group=e,
                         expert_only=True),
            ParameterDef("stock_z", "Surépaisseur brut Z",
                         ParameterType.FLOAT, default=0.0, group=e,
                         expert_only=True),
        ]

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        return ToolRequirement(tool_types=[],
                               description="Palpeur XYZ (automatique)")

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        p = {**cls.get_default_params(), **params}

        def _f(cle, defaut=0.0):
            try:
                return float(p.get(cle, defaut) or 0.0)
            except (TypeError, ValueError):
                return float(defaut)

        x, y = _f('_x'), _f('_y')
        lignes = [
            f"    SafeRapid X={x:.3f} Y={y:.3f} "
            f"Z={_f('probe_safe_z', 5.0):g}",
            "    EdgeMeasureV2 (",
            f"         direction=MeasuringDirection."
            f"{DIRECTIONS.get(p.get('direction'), 'XPositive')}",
            f"         zMeasureEdgeOffset={_f('z_edge_offset', 10.0):g} "
            f"measureZOffset={-abs(_f('measure_z_offset', -0.5)):g}",
        ]
        if _f('rotation_offset') > 0:
            lignes.append(f"         offsetForRotation="
                          f"{_f('rotation_offset'):g}")
            if p.get('rotation_only'):
                lignes.append("         setRotationOnly=true")
        lignes += [
            f"         retractDistance={_f('retract', 15.0):g} "
            f"searchDistance={_f('search', 15.0):g}",
            f"         skipZMeasureResult={_oui(p.get('skip_z_result'))} "
            f"skipZMeasure={_oui(p.get('skip_z_measure'))} "
            f"forceSafeHeight={_oui(p.get('force_safe_height'))}",
            f"         resultCs=CsType."
            f"{RESULTATS.get(p.get('result'), 'Wcs')}",
            f"         originXShift={_f('origin_x_shift'):g} "
            f"originYShift={_f('origin_y_shift'):g} "
            f"originZShift={_f('origin_z_shift'):g}",
            f"         stockEdgeOffset={_f('stock_edge'):g} "
            f"stockZOffset={_f('stock_z'):g}",
            "         )",
        ]
        return "\n".join(lignes)
