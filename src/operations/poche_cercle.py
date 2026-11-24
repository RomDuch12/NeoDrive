"""Opération: Poche Cercle (CircleCavity).

Manuel SimPL 3.1.1, § 5.2.3.2 « Circular pocket » (p. 206): la fraise
part du CENTRE et le diamètre usiné grandit à chaque tour, du
recouvrement, jusqu'au diamètre voulu.

    CircleCavity diameter=20 depth=2 infeedZ=1 strokeRapidZ=14
        strokeCuttingZ=1 finishingZ=0.0 finishingXY=0.0
        infeedFinishingZ=2 percentageStepover=50
"""

from typing import List, Dict, Any
from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement,
    REPEAT_PARAMS
)
from src.operations.registry import OperationRegistry


@OperationRegistry.register("poche_cercle")
class PocheCercle(AbstractOperation):
    DISPLAY_NAME = "Poche Cercle"
    CATEGORY = "Poche"
    DESCRIPTION = "Évidement circulaire (CircleCavity), depuis le centre"
    ICON = "cut_circle"
    # nouvelle (manuel SimPL, octobre 2026): en expert par
    # défaut — en mode simple, clic droit sur sa catégorie
    EXPERT_ONLY = True

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return [
            ParameterDef("diameter", "Diamètre", ParameterType.FLOAT,
                         default=20.0, min_value=0.1, unit="mm",
                         group="Dimensions",
                         tooltip="Diamètre de la poche (diameter)"),
            ParameterDef("depth", "Pz", ParameterType.FLOAT,
                         default=2.0, min_value=0.01, unit="mm",
                         group="Profondeur"),
            ParameterDef("infeed_z", "Passe Z", ParameterType.FLOAT,
                         default=0.5, min_value=0.01, unit="mm",
                         group="Profondeur",
                         tooltip="Prise de passe maximale par tour en Z "
                                 "(infeedZ)"),
            ParameterDef("finishing_z", "Finition Z", ParameterType.FLOAT,
                         default=0.1, min_value=0.0, unit="mm",
                         group="Finition"),
            ParameterDef("infeed_finishing_z", "Passe Z finition",
                         ParameterType.FLOAT, default=1.0, min_value=0.0,
                         unit="mm", group="Finition"),
            ParameterDef("finishing_xy", "Finition XY", ParameterType.FLOAT,
                         default=0.2, min_value=0.0, unit="mm",
                         group="Finition"),
            ParameterDef("stepover", "Recouvrement", ParameterType.INT,
                         default=45, min_value=1, max_value=100, unit="%",
                         group="Avances",
                         tooltip="Prise latérale, en % du diamètre de "
                                 "l'outil (percentageStepover)"),
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
            f"    CircleCavity (diameter={p['diameter']} "
            f"depth={p['depth']} infeedZ={p['infeed_z']} "
            f"strokeRapidZ={srz} strokeCuttingZ={scz} "
            f"finishingZ={p['finishing_z']} "
            f"infeedFinishingZ={p['infeed_finishing_z']} "
            f"finishingXY={p['finishing_xy']} "
            f"percentageStepover={p['stepover']})"
        )
