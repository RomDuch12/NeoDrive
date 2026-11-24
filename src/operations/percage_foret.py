"""Opération: Perçage Foret (Drill)"""

from typing import List, Dict, Any
from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement,
    REPEAT_PARAMS, GROUP_PARAMS
)
from src.operations.registry import OperationRegistry


@OperationRegistry.register("percage_foret")
class PercageForet(AbstractOperation):
    DISPLAY_NAME = "Perçage Foret"
    CATEGORY = "Perçage"
    DESCRIPTION = "Perçage classique au foret"
    ICON = "drill"
    SUPPORTS_MULTI_POINT = True

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return [
            ParameterDef("depth", "Pz", ParameterType.FLOAT,
                         default=10.0, min_value=0.01, unit="mm",
                         group="Profondeur"),
            ParameterDef("infeed_z", "Passe Z", ParameterType.FLOAT,
                         default=1.0, min_value=0.01, unit="mm",
                         group="Profondeur"),
            ParameterDef("use_ebav", "Ébavurage", ParameterType.BOOL,
                         default=False, group="Ébavurage"),
            ParameterDef("ebav_offset", "Offset ébav.", ParameterType.FLOAT,
                         default=0.05, min_value=0.0, max_value=1.0,
                         unit="mm", group="Ébavurage", expert_only=True),
            ParameterDef("ebav_profondeur", "Profondeur ébav. (Drill)",
                         ParameterType.FLOAT, default=0.0, min_value=0.0,
                         max_value=50.0, unit="mm", group="Ébavurage",
                         tooltip="Profondeur du Drill d'ébavurage. 0 = "
                                 "automatique (la moitié du Ø + l'offset)."),
        ] + REPEAT_PARAMS + GROUP_PARAMS

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        return ToolRequirement(
            tool_types=['Drill'],
            description="Foret"
        )

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        """Génère le code de perçage (sans Pattern — géré par le générateur)."""
        defaults = cls.get_default_params()
        p = {**defaults, **params}
        srz = p.get('_stroke_rapid_z', 15)
        scz = p.get('_stroke_cutting_z', 1)
        code = f"    Drill depth={p['depth']} infeedZ={p['infeed_z']} strokeRapidZ={srz} strokeCuttingZ={scz}"
        return code
