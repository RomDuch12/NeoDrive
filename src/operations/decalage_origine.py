"""Opération: Décalage Origine (ShiftWcsInc) - opération inline
Avec option de retour automatique à l'origine précédente.
"""

from typing import List, Dict, Any
from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement
)
from src.operations.registry import OperationRegistry


@OperationRegistry.register("decalage_origine")
class DecalageOrigine(AbstractOperation):
    DISPLAY_NAME = "Décalage Origine"
    CATEGORY = "Réglage"
    HORS_MATIERE = True
    DESCRIPTION = "Déplace l'origine de l'usinage"
    ICON = "shift"
    INLINE = True
    REQUIRES_TOOL = False
    REQUIRES_COORDINATES = False

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return [
            ParameterDef("shift_x", "X=", ParameterType.FLOAT,
                         default=0.0, unit="mm", group="Décalage"),
            ParameterDef("shift_y", "Y=", ParameterType.FLOAT,
                         default=0.0, unit="mm", group="Décalage"),
            ParameterDef("shift_z", "Z=", ParameterType.FLOAT,
                         default=0.0, unit="mm", group="Décalage"),
            ParameterDef("auto_return", "Aller-retour",
                         ParameterType.BOOL, default=False,
                         unit="", group="Décalage", expert_only=True,
                         tooltip="Génère le ShiftWcsInc inverse en fin "
                                 "de programme (retour à l'origine "
                                 "précédente)"),
        ]

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        return ToolRequirement(tool_types=[], description="Aucun outil requis")

    @classmethod
    def build_dynamic_name(cls, params: Dict[str, Any]) -> str:
        """Construit un titre dynamique: 'Décalage X=.. Y=.. Z=..'"""
        parts = []
        sx = float(params.get('shift_x', 0.0))
        sy = float(params.get('shift_y', 0.0))
        sz = float(params.get('shift_z', 0.0))
        if sx != 0.0:
            parts.append(f"X={sx:g}")
        if sy != 0.0:
            parts.append(f"Y={sy:g}")
        if sz != 0.0:
            parts.append(f"Z={sz:g}")
        if parts:
            return "Décalage " + " ".join(parts)
        return "Décalage Origine"

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        defaults = cls.get_default_params()
        p = {**defaults, **params}
        parts = []
        if p.get('shift_x', 0.0) != 0.0:
            parts.append(f"X={p['shift_x']}")
        if p.get('shift_y', 0.0) != 0.0:
            parts.append(f"Y={p['shift_y']}")
        if p.get('shift_z', 0.0) != 0.0:
            parts.append(f"Z={p['shift_z']}")
        if parts:
            return "    ShiftWcsInc " + " ".join(parts)
        return "    # ShiftWcsInc (aucun décalage)"
