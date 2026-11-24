"""Opération: Palpage Z (SurfaceMeasure) — opération inline.
Mesure la surface pour calibrer l'origine Z.
"""

from typing import List, Dict, Any
from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement
)
from src.operations.registry import OperationRegistry


@OperationRegistry.register("palpage_z")
class PalpageZ(AbstractOperation):
    DISPLAY_NAME = "Palpage Z"
    CATEGORY = "Réglage"
    HORS_MATIERE = True
    DESCRIPTION = "Mesure de surface pour calibration Z (SurfaceMeasure)"
    ICON = "probe"
    INLINE = True
    REQUIRES_TOOL = False
    REQUIRES_COORDINATES = False

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return [
            ParameterDef("probe_x", "X", ParameterType.FLOAT,
                         default=0.0, unit="mm",
                         group="Coordonnées de palpage"),
            ParameterDef("probe_y", "Y", ParameterType.FLOAT,
                         default=0.0, unit="mm",
                         group="Coordonnées de palpage"),
            ParameterDef("origin_z_shift", "originZShift", ParameterType.FLOAT,
                         default=0.0, unit="mm",
                         group="Options", expert_only=True),
            ParameterDef("stock_offset", "stockOffset", ParameterType.FLOAT,
                         default=0.0, unit="mm",
                         group="Options", expert_only=True),
            ParameterDef("retract_distance", "retractDistance",
                         ParameterType.FLOAT, default=15.0, min_value=0.0,
                         max_value=200.0, unit="mm", group="Options",
                         expert_only=True,
                         tooltip="Remontée après la mesure (défaut du "
                                 "manuel: 15, alors non écrit)"),
        ]

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        return ToolRequirement(tool_types=[], description="Aucun outil requis")

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        defaults = cls.get_default_params()
        p = {**defaults, **params}
        x = p.get('probe_x', 0.0)
        y = p.get('probe_y', 0.0)
        oz = p.get('origin_z_shift', 0.0)
        so = p.get('stock_offset', 0.0)
        mesure = f"    SurfaceMeasure Wcs originZShift={oz} stockOffset={so}"
        try:
            retrait = float(p.get('retract_distance', 15.0))
        except (TypeError, ValueError):
            retrait = 15.0
        if abs(retrait - 15.0) > 1e-9:
            mesure += f" retractDistance={retrait:g}"
        lines = [
            f"    SafeRapid X={x} Y={y}",
            mesure,
        ]
        return "\n".join(lines)
