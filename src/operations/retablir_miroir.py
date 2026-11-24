"""Opération: Rétablir Miroir (MirrorWcs reset) — opération inline
Désactive tous les miroirs actifs.
"""

from typing import List, Dict, Any
from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ToolRequirement
)
from src.operations.registry import OperationRegistry


@OperationRegistry.register("retablir_miroir")
class RetablirMiroir(AbstractOperation):
    DISPLAY_NAME = "Rétablir Miroir"
    CATEGORY = "Réglage"
    HORS_MATIERE = True
    EXPERT_ONLY = True
    DESCRIPTION = "Désactive tous les miroirs (reset)"
    ICON = "mirror_off"
    INLINE = True
    REQUIRES_TOOL = False
    REQUIRES_COORDINATES = False

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return []

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        return ToolRequirement(tool_types=[], description="Aucun outil requis")

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        return "    MirrorWcs mirrorX=false mirrorY=false mirrorZ=false"
