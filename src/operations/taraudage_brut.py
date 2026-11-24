"""Opération: Taraudage Brut.
Crée automatiquement 2 taraudages symétriques (entraxe X ou Y).
Sélection automatique de la fraise THR selon le type de filet.
"""

from typing import List, Dict, Any
from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement,
    REPEAT_PARAMS, GROUP_PARAMS
)
from src.operations.registry import OperationRegistry

# Mapping type filet → articles fraise THR compatibles
THREAD_TOOL_MAP = {
    "M3": ["0068419A"],
    "M4": ["0068420A"],
    "M6": ["0068456"],
    "M8": ["0068457"],
}


@OperationRegistry.register("taraudage_brut")
class TaraudageBrut(AbstractOperation):
    DISPLAY_NAME = "Taraudage Brut"
    CATEGORY = "Taraudage"
    DESCRIPTION = "2 taraudages symétriques avec entraxe automatique"
    ICON = "thread_pair"
    INLINE = False
    REQUIRES_TOOL = True
    REQUIRES_COORDINATES = True
    SUPPORTS_MULTI_POINT = False

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return [
            ParameterDef("thread_type", "Type filet", ParameterType.CHOICE,
                         default="M4",
                         choices=["M3", "M4", "M6", "M8"],
                         group="Taraudage"),
            ParameterDef("depth", "Profondeur Pz", ParameterType.FLOAT,
                         default=6.0, min_value=0.5, unit="mm",
                         group="Profondeur"),
            ParameterDef("entraxe", "Entraxe", ParameterType.FLOAT,
                         default=20.0, min_value=1.0, unit="mm",
                         group="Entraxe"),
            ParameterDef("entraxe_axis", "Axe", ParameterType.CHOICE,
                         default="X",
                         choices=["X", "Y"],
                         group="Entraxe"),
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
            tool_types=["M3", "M4", "M6", "M8"],
            description="Fraise à fileter THR"
        )

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        """Génère 2 Thread à ±entraxe/2 du centre."""
        defaults = cls.get_default_params()
        p = {**defaults, **params}
        thread_name = p.get('thread_type', 'M4')
        depth = p['depth']
        entraxe = float(p.get('entraxe', 20.0))
        axis = p.get('entraxe_axis', 'X')
        half = entraxe / 2.0
        direction = p.get('direction', 'RightHandThread')
        milling = p.get('milling_type', 'ConventionalMilling')
        finishing = p.get('finishing', 0.1)

        srz = p.get('_stroke_rapid_z', 15)
        scz = p.get('_stroke_cutting_z', 1)
        op_x = p.get('_op_x', 0.0)
        op_y = p.get('_op_y', 0.0)
        safe_z = p.get('_safe_rapid_z', srz + scz)
        thread_cmd = (
            f"    Thread (Metric threadName=\"{thread_name}\" "
            f"depth={depth} strokeRapidZ={srz} strokeCuttingZ={scz} "
            f"Inside {direction} {milling} finishing={finishing})")

        safe_rapid = f"    SafeRapid X={op_x:.3f} Y={op_y:.3f} Z={safe_z}"
        if axis == "X":
            pos1 = f"    ShiftWcsInc X={-half}"
            pos2 = f"    ShiftWcsInc X={entraxe}"
            ret = f"    ShiftWcsInc X={-half}"
        else:
            pos1 = f"    ShiftWcsInc Y={-half}"
            pos2 = f"    ShiftWcsInc Y={entraxe}"
            ret = f"    ShiftWcsInc Y={-half}"

        lines = [pos1, safe_rapid, thread_cmd,
                 pos2, safe_rapid, thread_cmd, ret]
        return "\n".join(lines)
