"""Opération: Surfaçage Rectangle"""

from typing import List, Dict, Any
from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement,
    REPEAT_PARAMS
)
from src.operations.registry import OperationRegistry


@OperationRegistry.register("surfacage_rectangle")
class SurfacageRectangle(AbstractOperation):
    DISPLAY_NAME = "Surfaçage Rectangle"
    CATEGORY = "Surfaçage"
    DESCRIPTION = "Surfaçage d'une zone rectangulaire"
    ICON = "surf_rect"

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return [
            ParameterDef("width_x", "Largeur X", ParameterType.FLOAT,
                         default=20.0, min_value=0.1, unit="mm",
                         group="Dimensions"),
            ParameterDef("width_y", "Largeur Y", ParameterType.FLOAT,
                         default=20.0, min_value=0.1, unit="mm",
                         group="Dimensions"),
            ParameterDef("extension_x", "Débordement X", ParameterType.FLOAT,
                         default=0.0, min_value=0.0, unit="mm",
                         group="Dimensions", expert_only=True),
            ParameterDef("extension_y", "Débordement Y", ParameterType.FLOAT,
                         default=0.0, min_value=0.0, unit="mm",
                         group="Dimensions", expert_only=True),
            ParameterDef("depth", "Pz", ParameterType.FLOAT,
                         default=0.1, min_value=0.01, unit="mm",
                         group="Profondeur"),
            ParameterDef("infeed_z", "Passe Z", ParameterType.FLOAT,
                         default=0.5, min_value=0.01, unit="mm",
                         group="Profondeur"),
            ParameterDef("finishing_z", "Finition Z", ParameterType.FLOAT,
                         default=0.12, min_value=0.0, unit="mm",
                         group="Profondeur"),
            ParameterDef("stepover", "Recouvrement", ParameterType.INT,
                         default=45, min_value=1, max_value=100, unit="%",
                         group="Avances"),
            ParameterDef("angle", "Angle", ParameterType.FLOAT,
                         default=90.0, min_value=0.0, max_value=360.0,
                         unit="°", group="Avances"),
            ParameterDef("both_ways", "Aller-retour", ParameterType.BOOL,
                         default=True, group="Options",
                         expert_only=True,
                         tooltip="Usine dans les deux sens. Décoché, "
                                 "chaque passe repart du même côté."),
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
        both = "BothWays " if p.get('both_ways', True) else ""
        depth = float(p['depth'])
        finishing_z = float(p['finishing_z'])

        # Extension: omettre si à 0
        ext_x = float(p.get('extension_x', 0))
        ext_y = float(p.get('extension_y', 0))
        ext_str = ""
        if ext_x > 0 or ext_y > 0:
            ext_str = f"extensionX={ext_x} extensionY={ext_y} "

        # Pz <= 0.2 : supprimer la finition (passe unique)
        lines = []
        if depth <= 0.2:
            lines.append(
                "    # Pz<=0.2mm : passe unique sans finition "
                "(finishing reporté dans roughing)")
            lines.append(
                f"    RectangleFace (widthX={p['width_x']} "
                f"widthY={p['width_y']} {both}{ext_str}"
                f"depth={depth} infeedZ={depth} "
                f"strokeRapidZ={srz} strokeCuttingZ={scz} "
                f"finishingZ=0 "
                f"percentageStepover={p['stepover']} angle={p['angle']})")
        else:
            lines.append(
                f"    RectangleFace (widthX={p['width_x']} "
                f"widthY={p['width_y']} {both}{ext_str}"
                f"depth={depth} infeedZ={p['infeed_z']} "
                f"strokeRapidZ={srz} strokeCuttingZ={scz} "
                f"finishingZ={finishing_z} "
                f"percentageStepover={p['stepover']} angle={p['angle']})")
        return "\n".join(lines)
