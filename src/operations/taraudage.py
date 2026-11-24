"""Opération: Taraudage (Thread)"""

from typing import List, Dict, Any
from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement,
    REPEAT_PARAMS, GROUP_PARAMS
)
from src.operations.registry import OperationRegistry

THREAD_TYPES = ["M2.5", "M3", "M4", "M5", "M6", "M8", "M10"]

# Diamètre nominal par type de filet (mm) — source canonique
THREAD_DIAMETER = {
    "M2.5": 2.5, "M3": 3.0, "M4": 4.0, "M5": 5.0,
    "M6": 6.0, "M8": 8.0, "M10": 10.0
}

# Pas du filet (ISO pas gros, mm)
PAS_FILET = {
    "M2.5": 0.45, "M3": 0.5, "M4": 0.7, "M5": 0.8,
    "M6": 1.0, "M8": 1.25, "M10": 1.5
}

# Ø de l'avant-trou (perçage du filet, ISO pas gros) — M4: 3,3
AVANT_TROU = {
    "M2.5": 2.05, "M3": 2.5, "M4": 3.3, "M5": 4.2,
    "M6": 5.0, "M8": 6.8, "M10": 8.5
}


@OperationRegistry.register("taraudage")
class Taraudage(AbstractOperation):
    DISPLAY_NAME = "Taraudage"
    CATEGORY = "Taraudage"
    DESCRIPTION = "Taraudage par fraisage (M2.5 à M10)"
    ICON = "thread"
    SUPPORTS_MULTI_POINT = True

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return [
            ParameterDef("depth", "Pz", ParameterType.FLOAT,
                         default=6.0, min_value=0.5, unit="mm",
                         group="Profondeur",
                         tooltip="Ne pas dépasser max_depth de l'outil"),
            ParameterDef("direction", "Direction", ParameterType.CHOICE,
                         default="RightHandThread",
                         choices=["RightHandThread", "LeftHandThread"],
                         group="Taraudage", expert_only=True),
            ParameterDef("milling_type", "Type fraisage", ParameterType.CHOICE,
                         default="ConventionalMilling",
                         choices=["ConventionalMilling", "ClimbMilling"],
                         group="Taraudage", expert_only=True),
            ParameterDef("finishing", "Finition", ParameterType.FLOAT,
                         default=0.1, min_value=0.0, unit="mm",
                         group="Finition", expert_only=True),
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
            tool_types=THREAD_TYPES,
            description="Fraise à fileter"
        )

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        """Génère le code Thread."""
        defaults = cls.get_default_params()
        p = {**defaults, **params}
        thread_name = p.get('thread_name', 'M3')
        srz = p.get('_stroke_rapid_z', 15)
        scz = p.get('_stroke_cutting_z', 1)
        code = (
            f"    Thread (Metric "
            f"threadName=\"{thread_name}\" "
            f"depth={p['depth']} "
            f"strokeRapidZ={srz} strokeCuttingZ={scz} "
            f"Inside "
            f"{p['direction']} {p['milling_type']} "
            f"finishing={p['finishing']})"
        )
        return code
