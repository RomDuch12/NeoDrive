"""Opération: Découpe Rectangle"""

from typing import List, Dict, Any
from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement,
    REPEAT_PARAMS
)
from src.operations.registry import OperationRegistry


@OperationRegistry.register("decoupe_rectangle")
class DecoupeRectangle(AbstractOperation):
    DISPLAY_NAME = "Découpe Rectangle"
    CATEGORY = "Découpe"
    DESCRIPTION = "Découpe rectangulaire intérieure ou extérieure"
    ICON = "cut_rect"

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return [
            ParameterDef("width_x", "Largeur X", ParameterType.FLOAT,
                         default=40.0, min_value=0.1, unit="mm",
                         group="Dimensions"),
            ParameterDef("width_y", "Largeur Y", ParameterType.FLOAT,
                         default=30.0, min_value=0.1, unit="mm",
                         group="Dimensions"),
            ParameterDef("corner_radius", "Rayon coins", ParameterType.FLOAT,
                         default=2.0, min_value=0.0, unit="mm",
                         group="Dimensions"),
            ParameterDef("side", "Côté usinage", ParameterType.CHOICE,
                         default="Outside",
                         choices=["Outside", "Inside", "Over"],
                         group="Options"),
            ParameterDef("depth", "Pz", ParameterType.FLOAT,
                         default=3.0, min_value=0.01, unit="mm",
                         group="Profondeur"),
            ParameterDef("infeed_z", "Passe Z", ParameterType.FLOAT,
                         default=0.5, min_value=0.01, unit="mm",
                         group="Profondeur"),
            ParameterDef("finishing_xy", "Finition XY", ParameterType.FLOAT,
                         default=0.2, min_value=0.0, unit="mm",
                         group="Finition"),
            ParameterDef("infeed_finishing_z", "Passe Z finition",
                         ParameterType.FLOAT, default=1.0, min_value=0.0,
                         unit="mm", group="Finition"),
            ParameterDef("diagonal_infeed", "Plongée diagonale",
                         ParameterType.BOOL, default=False, group="Options",
                         expert_only=True),
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
        diag = "diagonalInfeed=true" if p.get('diagonal_infeed', True) \
            else "diagonalInfeed=false"
        return (
            f"    RectFromMid (widthX={p['width_x']} widthY={p['width_y']} "
            f"cornerRadius={p['corner_radius']} {p['side']} {diag} "
            f"depth={p['depth']} infeedZ={p['infeed_z']} "
            f"strokeRapidZ={srz} strokeCuttingZ={scz} "
            f"finishingXY={p['finishing_xy']} "
            f"infeedFinishingZ={p['infeed_finishing_z']})"
        )
