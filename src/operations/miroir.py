"""Opération: Miroir (MirrorWcs) — opération inline
Active le miroir sur les axes sélectionnés.
"""

from typing import List, Dict, Any
from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement
)
from src.operations.registry import OperationRegistry


@OperationRegistry.register("miroir")
class Miroir(AbstractOperation):
    DISPLAY_NAME = "Miroir"
    CATEGORY = "Réglage"
    HORS_MATIERE = True
    EXPERT_ONLY = True
    DESCRIPTION = "Active le miroir sur les axes sélectionnés"
    ICON = "mirror"
    INLINE = True
    REQUIRES_TOOL = False
    REQUIRES_COORDINATES = False

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return [
            ParameterDef("mirror_x", "Miroir X", ParameterType.BOOL,
                         default=False, group="Axes"),
            ParameterDef("mirror_y", "Miroir Y", ParameterType.BOOL,
                         default=False, group="Axes"),
        ]

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        return ToolRequirement(tool_types=[], description="Aucun outil requis")

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        defaults = cls.get_default_params()
        p = {**defaults, **params}
        parts = []
        if p.get('mirror_x', False):
            parts.append("mirrorX=true")
        if p.get('mirror_y', False):
            parts.append("mirrorY=true")
        if parts:
            return "    MirrorWcs " + " ".join(parts)
        return "    # MirrorWcs (aucun axe sélectionné)"
