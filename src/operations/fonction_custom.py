"""
Opération: Fonction Custom — permet de définir une fonction DATRON
avec un nom personnalisé, du code SimPl libre et des paramètres utilisateur.

Le code SimPl peut contenir des placeholders {param_name} qui seront
remplacés par les valeurs des paramètres à la génération.
"""

from typing import List, Dict, Any
from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement
)
from src.operations.registry import OperationRegistry


@OperationRegistry.register("fonction_custom")
class FonctionCustom(AbstractOperation):
    DISPLAY_NAME = "Fonction Custom"
    CATEGORY = "Utilitaire"
    DESCRIPTION = "Fonction DATRON personnalisée avec code SimPl libre"
    ICON = "custom"
    INLINE = False
    REQUIRES_TOOL = True
    REQUIRES_COORDINATES = True
    SUPPORTS_MULTI_POINT = False
    EXPERT_ONLY = True

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return [
            ParameterDef("simpl_code", "Code SimPl", ParameterType.STRING,
                         default="    ' Code SimPl ici",
                         tooltip="Code SimPl de la fonction.\n"
                                 "Utilisez {p1}, {p2}... comme placeholders\n"
                                 "pour les paramètres ci-dessous.",
                         group="Code"),
            ParameterDef("p1", "Param 1", ParameterType.FLOAT,
                         default=0.0, group="Paramètres"),
            ParameterDef("p2", "Param 2", ParameterType.FLOAT,
                         default=0.0, group="Paramètres"),
            ParameterDef("p3", "Param 3", ParameterType.FLOAT,
                         default=0.0, group="Paramètres"),
            ParameterDef("p4", "Param 4", ParameterType.FLOAT,
                         default=0.0, group="Paramètres"),
            ParameterDef("p5", "Param 5", ParameterType.FLOAT,
                         default=0.0, group="Paramètres",
                         expert_only=True),
            ParameterDef("p6", "Param 6", ParameterType.FLOAT,
                         default=0.0, group="Paramètres",
                         expert_only=True),
        ]

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        return ToolRequirement(
            tool_types=[
                'Cyl2', 'Cyl3', 'Cyl6', 'Cyl8', 'Cyl14',
                'Con20', 'Con30', 'Drill', 'TSlot',
                'ExtraD3', 'ExtraD6', 'Chamfer'
            ],
            description="Tout type d'outil"
        )

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        defaults = cls.get_default_params()
        p = {**defaults, **params}

        code_template = str(p.get('simpl_code', ''))

        # Remplacer les placeholders {p1}..{p6}
        for i in range(1, 7):
            key = f'p{i}'
            val = p.get(key, 0.0)
            code_template = code_template.replace(
                '{' + key + '}', str(val))

        # Assurer l'indentation
        lines = []
        for line in code_template.split('\n'):
            stripped = line.strip()
            if stripped:
                if not stripped.startswith('    '):
                    lines.append(f"    {stripped}")
                else:
                    lines.append(stripped)
            else:
                lines.append("")

        return '\n'.join(lines) if lines else "    ' (code vide)"
