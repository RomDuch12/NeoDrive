"""Opération: Découpe Cercle"""

from typing import List, Dict, Any
from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement,
    REPEAT_PARAMS
)
from src.operations.registry import OperationRegistry


@OperationRegistry.register("decoupe_cercle")
class DecoupeCercle(AbstractOperation):
    DISPLAY_NAME = "Découpe Cercle"
    CATEGORY = "Découpe"
    DESCRIPTION = "Découpe circulaire intérieure ou extérieure"
    ICON = "cut_circle"

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return [
            ParameterDef("diameter", "Diamètre", ParameterType.FLOAT,
                         default=10.0, min_value=0.1, unit="mm",
                         group="Dimensions"),
            ParameterDef("side", "Côté usinage", ParameterType.CHOICE,
                         default="Inside",
                         choices=["Inside", "Outside", "Over"],
                         group="Options"),
            ParameterDef("depth", "Pz", ParameterType.FLOAT,
                         default=5.0, min_value=0.01, unit="mm",
                         group="Profondeur"),
            ParameterDef("infeed_z", "Passe Z", ParameterType.FLOAT,
                         default=0.5, min_value=0.01, unit="mm",
                         group="Profondeur"),
            ParameterDef("finishing_xy", "Finition XY", ParameterType.FLOAT,
                         default=0.1, min_value=0.0, unit="mm",
                         group="Finition"),
            ParameterDef("finishing_z", "Finition Z", ParameterType.FLOAT,
                         default=0.1, min_value=0.0, unit="mm",
                         group="Finition"),
            ParameterDef("infeed_finishing_z", "Passe Z finition",
                         ParameterType.FLOAT, default=0.5, min_value=0.0,
                         unit="mm", group="Finition"),
        ] + REPEAT_PARAMS

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        return ToolRequirement(
            tool_types=['Cyl2', 'Cyl3', 'Cyl6', 'Cyl8', 'Cyl14'],
            description="Fraise cylindrique"
        )

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        defaults = cls.get_default_params()
        p = {**defaults, **params}
        srz = p.get('_stroke_rapid_z', 15)
        scz = p.get('_stroke_cutting_z', 1)
        return (
            f"    CircleFromMid (diameter={p['diameter']} {p['side']} "
            f"depth={p['depth']} infeedZ={p['infeed_z']} "
            f"strokeRapidZ={srz} strokeCuttingZ={scz} "
            f"finishingXY={p['finishing_xy']} finishingZ={p['finishing_z']} "
            f"infeedFinishingZ={p['infeed_finishing_z']})"
        )
