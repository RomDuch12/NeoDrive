"""
Opération: Appel Outil Simple.
Monte un outil sans opération d'usinage.
Utile pour les changements d'outils manuels ou les préparations.

Génère:
  Tool type="article_nr"
  Rpm = rpm
  Spindle On
"""

from typing import List, Dict, Any
from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement
)
from src.operations.registry import OperationRegistry


@OperationRegistry.register("appel_outil")
class AppelOutil(AbstractOperation):
    OP_TYPE = "appel_outil"
    DISPLAY_NAME = "Appel Outil"
    CATEGORY = "Utilitaire"
    ICON = "tool_call"
    DESCRIPTION = (
        "Monte un outil sans opération d'usinage. "
        "Utile pour un changement d'outil ou une préparation.")
    INLINE = False
    REQUIRES_TOOL = True
    REQUIRES_COORDINATES = False
    SUPPORTS_MULTI_POINT = False

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return [
            ParameterDef(
                "spindle_on", "Broche On", ParameterType.BOOL,
                default=True, group="Options",
                tooltip="Démarrer la broche après le changement d'outil"),
            ParameterDef(
                "spray_on", "Spray On", ParameterType.BOOL,
                default=True, group="Options",
                tooltip="Activer le spray"),
        ]

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        return ToolRequirement(
            tool_types=['Drill', 'Cyl2', 'Cyl3', 'Cyl6', 'Cyl8',
                        'Cyl14', 'Con1', 'Con2', 'Con3',
                        'M3', 'M4', 'M5', 'M6', 'M8', 'M10'],
            description="Tout type d'outil"
        )

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        """Génère le code d'appel outil simple (intégré dans le sous-programme)."""
        p = {**cls.get_default_params(), **params}
        lines = []
        if p.get('spray_on', True):
            lines.append("    SpraySystem On")
        if p.get('spindle_on', True):
            lines.append("    Spindle On")
        if not lines:
            lines.append("    # Outil monté (broche et spray off)")
        return "\n".join(lines)
