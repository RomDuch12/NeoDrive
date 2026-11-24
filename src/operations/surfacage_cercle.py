"""Opération: Surfaçage Cercle"""

from typing import List, Dict, Any
from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement,
    REPEAT_PARAMS
)
from src.operations.registry import OperationRegistry


@OperationRegistry.register("surfacage_cercle")
class SurfacageCercle(AbstractOperation):
    DISPLAY_NAME = "Surfaçage Cercle"
    CATEGORY = "Surfaçage"
    DESCRIPTION = "Surfaçage d'une zone circulaire"
    ICON = "surf_circle"

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return [
            ParameterDef("diameter", "Diamètre", ParameterType.FLOAT,
                         default=20.0, min_value=0.1, unit="mm",
                         group="Dimensions"),
            ParameterDef("extension_diameter", "Débordement diamètre",
                         ParameterType.FLOAT, default=8.0, min_value=0.0,
                         unit="mm", group="Dimensions"),
            ParameterDef("depth", "Pz", ParameterType.FLOAT,
                         default=0.1, min_value=0.01, unit="mm",
                         group="Profondeur"),
            ParameterDef("infeed_z", "Passe Z", ParameterType.FLOAT,
                         default=0.5, min_value=0.01, unit="mm",
                         group="Profondeur"),
            ParameterDef("finishing_z", "Finition Z", ParameterType.FLOAT,
                         default=0.1, min_value=0.0, unit="mm",
                         group="Profondeur"),
            ParameterDef("stepover", "Recouvrement", ParameterType.INT,
                         default=45, min_value=1, max_value=100, unit="%",
                         group="Avances"),
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
            f"    CircleFace (diameter={p['diameter']} "
            f"extensionDiameter={p['extension_diameter']} "
            f"depth={p['depth']} infeedZ={p['infeed_z']} "
            f"strokeRapidZ={srz} strokeCuttingZ={scz} "
            f"finishingZ={p['finishing_z']} "
            f"percentageStepover={p['stepover']})"
        )
