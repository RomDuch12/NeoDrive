"""Opération: Palpage d'une forme en U (UShapeMeasure) — inline.

Manuel SimPL 3.1.1, § 5.3.1.7 « U-shape » (p. 289-298): une pièce à
trois arêtes en U (un fond et deux côtés): le cycle combine l'arête (le
fond) et la symétrie (les côtés). La position X/Y est celle où le
palpeur descend, au milieu du U.

    SafeRapid X=0 Y=0 Z=5
    UShapeMeasure direction=MeasuringDirection.XPositive
        view=MeasuringView.Outside width=20
        zMeasureOffset=10 zMeasureSideOffset=10 sideMeasureOffset=10
        sideMeasureZOffset=-0.5 bottomMeasureZOffset=-0.5
        bottomMeasureDistanceForRotation=0 sideMeasureOffsetForRotation=0
        retractDistance=15 searchDistance=15 skipZMeasureResult=false
        skipZMeasure=false forceSafeHeight=false
        resultCs=CsType.Wcs originXShift=0 originYShift=0 originZShift=0
        stockXOffset=0 stockYOffset=0 stockZOffset=0
"""

from typing import Any, Dict, List

from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement
)
from src.operations.palpage_arete import DIRECTIONS, RESULTATS, _oui
from src.operations.registry import OperationRegistry

#: côté d'approche -> MeasuringView
VUES = {"Extérieur": "Outside", "Intérieur": "Inside"}


@OperationRegistry.register("palpage_u")
class PalpageU(AbstractOperation):
    DISPLAY_NAME = "Palpage forme en U"
    CATEGORY = "Réglage"
    HORS_MATIERE = True
    DESCRIPTION = ("UShapeMeasure: origine reprise sur une pièce en U "
                   "(un fond et deux côtés: arête + symétrie)")
    ICON = "ruler"
    EXPERT_ONLY = True
    INLINE = True
    REQUIRES_TOOL = False
    REQUIRES_COORDINATES = True

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        g, e = "Palpage", "Palpage expert"
        return [
            ParameterDef("direction", "Sens du U", ParameterType.CHOICE,
                         default="X+ (arête à droite)",
                         choices=list(DIRECTIONS), group=g,
                         tooltip="L'axe de symétrie du U et où est son "
                                 "fond (direction)"),
            ParameterDef("view", "Approche", ParameterType.CHOICE,
                         default="Extérieur", choices=list(VUES), group=g,
                         tooltip="Extérieur: le palpeur vient de dehors "
                                 "vers la matière; Intérieur: de dedans"),
            ParameterDef("width", "Largeur du fond", ParameterType.FLOAT,
                         default=20.0, min_value=0.1, max_value=5000.0,
                         unit="mm", group=g,
                         tooltip="La largeur du fond du U (width), en X "
                                 "ou en Y selon le sens"),
            ParameterDef("z_offset", "Point Z: distance au fond",
                         ParameterType.FLOAT, default=10.0, min_value=0.0,
                         unit="mm", group=e, expert_only=True),
            ParameterDef("z_side_offset", "Point Z: distance au côté",
                         ParameterType.FLOAT, default=10.0, min_value=0.0,
                         unit="mm", group=e, expert_only=True),
            ParameterDef("side_offset", "Côtés: distance au fond",
                         ParameterType.FLOAT, default=10.0, min_value=0.0,
                         unit="mm", group=e, expert_only=True),
            ParameterDef("side_z", "Côtés: hauteur de mesure",
                         ParameterType.FLOAT, default=-0.5, max_value=0.0,
                         min_value=-200.0, unit="mm", group=g),
            ParameterDef("bottom_z", "Fond: hauteur de mesure",
                         ParameterType.FLOAT, default=-0.5, max_value=0.0,
                         min_value=-200.0, unit="mm", group=g),
            ParameterDef("bottom_rotation", "Orientation: 2e point du fond",
                         ParameterType.FLOAT, default=0.0, min_value=0.0,
                         unit="mm", group=e, expert_only=True),
            ParameterDef("side_rotation", "Orientation: 2e point du côté",
                         ParameterType.FLOAT, default=0.0, min_value=0.0,
                         unit="mm", group=e, expert_only=True),
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
            ParameterDef("stock_x", "Surépaisseur brut X",
                         ParameterType.FLOAT, default=0.0, group=e,
                         expert_only=True),
            ParameterDef("stock_y", "Surépaisseur brut Y",
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
        return "\n".join([
            f"    SafeRapid X={x:.3f} Y={y:.3f} "
            f"Z={_f('probe_safe_z', 5.0):g}",
            "    UShapeMeasure (",
            f"         direction=MeasuringDirection."
            f"{DIRECTIONS.get(p.get('direction'), 'XPositive')}",
            f"         view=MeasuringView."
            f"{VUES.get(p.get('view'), 'Outside')}",
            f"         width={_f('width', 20.0):g}",
            f"         zMeasureOffset={_f('z_offset', 10.0):g} "
            f"zMeasureSideOffset={_f('z_side_offset', 10.0):g} "
            f"sideMeasureOffset={_f('side_offset', 10.0):g}",
            f"         sideMeasureZOffset={-abs(_f('side_z', -0.5)):g} "
            f"bottomMeasureZOffset={-abs(_f('bottom_z', -0.5)):g}",
            f"         bottomMeasureDistanceForRotation="
            f"{_f('bottom_rotation'):g} "
            f"sideMeasureOffsetForRotation={_f('side_rotation'):g}",
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
            f"         stockXOffset={_f('stock_x'):g} "
            f"stockYOffset={_f('stock_y'):g} "
            f"stockZOffset={_f('stock_z'):g}",
            "         )",
        ])
