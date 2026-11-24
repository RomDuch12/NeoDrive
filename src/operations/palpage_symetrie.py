"""Opération: Palpage axe de symétrie (SymmetryAxisMeasure).

Palpe les DEUX faces d'une pièce et place l'origine sur son axe de
symétrie — bien plus juste qu'un palpage d'arête unique, car
l'incertitude sur la largeur réelle du brut est répartie.

Deux orientations, telles que relevées sur la machine:

  Palpage X (+ Z)   →  YAligned   (les faces palpées sont ⊥ à X)
  Palpage Y (+ Z)   →  XAligned

    SymmetryAxisMeasure (
         width=20
         Outside
         YAligned
         measureZOffset=-0.5
         zMeasureXShift=0  zMeasureYShift=0
         Wcs
         originXShift=0  originYShift=0  originZShift=0
         searchDistance=15  retractDistance=15
         skipZMeasureResult=false  forceSafeHeight=false
         skipZMeasure=false
         )

En mode normal, seuls l'origine (Wcs/Lcs), la largeur et
intérieur/extérieur sont exposés: le reste relève du réglage fin et
passe en expert.
"""

from typing import List, Dict, Any
from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement
)
from src.operations.registry import OperationRegistry

AXE_X = "X (+ Z)"
AXE_Y = "Y (+ Z)"
OUTSIDE = "Extérieur (largeur de pièce)"
INSIDE = "Intérieur (largeur de poche)"
WCS = "Wcs (origine pièce)"
LCS = "Lcs (origine locale)"

#: orientation Datron selon l'axe palpé
_ALIGNMENT = {AXE_X: "YAligned", AXE_Y: "XAligned"}


@OperationRegistry.register("palpage_symetrie")
class PalpageSymetrie(AbstractOperation):
    OP_TYPE = "palpage_symetrie"
    DISPLAY_NAME = "Palpage axe de symétrie"
    CATEGORY = "Réglage"
    HORS_MATIERE = True
    EXPERT_ONLY = True
    DESCRIPTION = ("Palpe les deux faces et centre l'origine sur "
                   "l'axe de symétrie (SymmetryAxisMeasure)")
    ICON = "probe"
    INLINE = True
    REQUIRES_TOOL = False
    REQUIRES_COORDINATES = False
    SUPPORTS_MULTI_POINT = False

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return [
            # ── Réglages courants ──
            ParameterDef("axis", "Axe palpé", ParameterType.CHOICE,
                         default=AXE_X, choices=[AXE_X, AXE_Y],
                         group="Palpage",
                         tooltip="X (+ Z): palpe les deux faces "
                                 "perpendiculaires à X.\n"
                                 "Y (+ Z): idem selon Y."),
            ParameterDef("width", "Largeur", ParameterType.FLOAT,
                         default=20.0, min_value=0.1, max_value=999.0,
                         unit="mm", group="Palpage",
                         tooltip="Distance nominale entre les deux "
                                 "faces palpées"),
            ParameterDef("side", "Type", ParameterType.CHOICE,
                         default=OUTSIDE, choices=[OUTSIDE, INSIDE],
                         group="Palpage",
                         tooltip="Extérieur: on palpe une pièce.\n"
                                 "Intérieur: on palpe une poche."),
            ParameterDef("origin", "Origine", ParameterType.CHOICE,
                         default=WCS, choices=[WCS, LCS],
                         group="Palpage",
                         tooltip="Repère mis à jour par la mesure"),
            # ── Réglage fin (expert) ──
            ParameterDef("measure_z_offset", "measureZOffset",
                         ParameterType.FLOAT, default=-0.5, unit="mm",
                         group="Réglage fin", expert_only=True,
                         tooltip="Décalage Z du palpage latéral "
                                 "(négatif = sous la surface)"),
            ParameterDef("search_distance", "searchDistance",
                         ParameterType.FLOAT, default=15.0, unit="mm",
                         group="Réglage fin", expert_only=True,
                         tooltip="Course de recherche de la face"),
            ParameterDef("retract_distance", "retractDistance",
                         ParameterType.FLOAT, default=15.0, unit="mm",
                         group="Réglage fin", expert_only=True,
                         tooltip="Retrait après contact"),
            ParameterDef("z_measure_x_shift", "zMeasureXShift",
                         ParameterType.FLOAT, default=0.0, unit="mm",
                         group="Réglage fin", expert_only=True,
                         tooltip="Décalage X du point de palpage Z"),
            ParameterDef("z_measure_y_shift", "zMeasureYShift",
                         ParameterType.FLOAT, default=0.0, unit="mm",
                         group="Réglage fin", expert_only=True,
                         tooltip="Décalage Y du point de palpage Z"),
            ParameterDef("origin_x_shift", "originXShift",
                         ParameterType.FLOAT, default=0.0, unit="mm",
                         group="Décalage origine", expert_only=True),
            ParameterDef("origin_y_shift", "originYShift",
                         ParameterType.FLOAT, default=0.0, unit="mm",
                         group="Décalage origine", expert_only=True),
            ParameterDef("origin_z_shift", "originZShift",
                         ParameterType.FLOAT, default=0.0, unit="mm",
                         group="Décalage origine", expert_only=True),
            ParameterDef("skip_z_measure", "skipZMeasure",
                         ParameterType.BOOL, default=False,
                         group="Options", expert_only=True,
                         tooltip="Ne pas palper Z (garde l'origine Z "
                                 "actuelle)"),
            ParameterDef("skip_z_measure_result", "skipZMeasureResult",
                         ParameterType.BOOL, default=False,
                         group="Options", expert_only=True,
                         tooltip="Palper Z sans l'appliquer à "
                                 "l'origine"),
            ParameterDef("force_safe_height", "forceSafeHeight",
                         ParameterType.BOOL, default=False,
                         group="Options", expert_only=True,
                         tooltip="Remonter à hauteur de sécurité "
                                 "entre les palpages"),
        ]

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        return ToolRequirement(tool_types=[],
                               description="Palpeur / outil de mesure")

    @staticmethod
    def _b(value) -> str:
        return "true" if value else "false"

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        defaults = cls.get_default_params()
        p = {**defaults, **params}
        axis = p.get('axis', AXE_X)
        aligned = _ALIGNMENT.get(axis, "YAligned")
        side = "Outside" if p.get('side', OUTSIDE) == OUTSIDE \
            else "Inside"
        origin = "Wcs" if p.get('origin', WCS) == WCS else "Lcs"

        def num(key, default=0.0):
            try:
                return float(p.get(key, default) or 0.0)
            except (TypeError, ValueError):
                return float(default)

        return "\n".join([
            f"    # Palpage axe de symétrie {axis}",
            "    SymmetryAxisMeasure (",
            f"         width={num('width', 20.0):g}",
            f"         {side}",
            f"         {aligned}",
            f"         measureZOffset={num('measure_z_offset', -0.5):g}",
            f"         zMeasureXShift={num('z_measure_x_shift'):g}",
            f"         zMeasureYShift={num('z_measure_y_shift'):g}",
            f"         {origin}",
            f"         originXShift={num('origin_x_shift'):g}",
            f"         originYShift={num('origin_y_shift'):g}",
            f"         originZShift={num('origin_z_shift'):g}",
            f"         searchDistance={num('search_distance', 15.0):g}",
            f"         retractDistance="
            f"{num('retract_distance', 15.0):g}",
            f"         skipZMeasureResult="
            f"{cls._b(p.get('skip_z_measure_result'))}",
            f"         forceSafeHeight="
            f"{cls._b(p.get('force_safe_height'))}",
            f"         skipZMeasure={cls._b(p.get('skip_z_measure'))}",
            "         )",
        ])

    @classmethod
    def validate_params(cls, params: Dict[str, Any]) -> List[str]:
        p = {**cls.get_default_params(), **params}
        errors = []
        try:
            width = float(p.get('width', 0) or 0)
        except (TypeError, ValueError):
            width = 0.0
        if width <= 0:
            errors.append("La largeur doit être positive")
        if p.get('skip_z_measure') and p.get('skip_z_measure_result'):
            errors.append(
                "skipZMeasure et skipZMeasureResult sont redondants: "
                "le palpage Z est déjà ignoré")
        return errors
