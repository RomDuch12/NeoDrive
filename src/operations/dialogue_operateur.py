"""Opération: Dialogue Opérateur (Dialog/AskFor)
Génère un bloc conditionnel avec pause opérateur."""

from typing import List, Dict, Any
from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement
)
from src.operations.registry import OperationRegistry


@OperationRegistry.register("dialogue_operateur")
class DialogueOperateur(AbstractOperation):
    DISPLAY_NAME = "Dialogue Opérateur"
    CATEGORY = "Utilitaire"
    HORS_MATIERE = True
    DESCRIPTION = "Pause avec question opérateur (Oui/Non)"
    ICON = "dialog"
    INLINE = True
    REQUIRES_TOOL = False
    REQUIRES_COORDINATES = False

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return [
            ParameterDef("message", "Message", ParameterType.STRING,
                         default="Continuer l'usinage ?", unit="",
                         group="Dialogue"),
            ParameterDef("dialog_type", "Type", ParameterType.CHOICE,
                         default="ask_continue",
                         choices=["ask_continue", "info_only"],
                         group="Dialogue",
                         tooltip="ask_continue: Oui/Non conditionnel, info_only: simple message"),
            ParameterDef("park_before", "Park avant dialogue",
                         ParameterType.BOOL, default=True, group="Options"),
            ParameterDef("tool_before_park", "Changer outil avant park",
                         ParameterType.BOOL, default=False, group="Options",
                         tooltip="Insérer un changement d'outil (skipRestoring) avant le park"),
            ParameterDef("tool_article", "Article outil", ParameterType.STRING,
                         default="", group="Options",
                         tooltip="N° article de l'outil à charger avant park"),
        ]

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        return ToolRequirement(tool_types=[], description="Aucun outil requis")

    @classmethod
    def _build_tool_line(cls, p: dict) -> list:
        """Génère la ligne Tool skipRestoring si configurée."""
        if p.get('tool_before_park') and p.get('tool_article', '').strip():
            article = p['tool_article'].strip()
            return [f'    Tool type="{article}"  skipRestoring']
        return []

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        defaults = cls.get_default_params()
        p = {**defaults, **params}
        msg = p.get('message', 'Continuer ?')
        dialog_type = p.get('dialog_type', 'ask_continue')
        park = p.get('park_before', True)

        if dialog_type == "info_only":
            lines = [
                f'    Dialog (',
                f'        caption="Information"',
                f'        message="{msg}"',
                f'    )',
            ]
            return "\n".join(lines)

        # ask_continue: génère un bloc AskFor + if/endif
        lines = []
        lines.extend(cls._build_tool_line(p))
        if park:
            lines.extend([
                "    SpraySystem Off",
                "    Spindle Off",
                "    MoveToParkPosition",
            ])
        lines.extend([
            f'    result = Dialog message="{msg}" Yes=true No=true',
        ])
        return "\n".join(lines)

    @classmethod
    def generate_askfor_program(cls, params: Dict[str, Any],
                                prog_name: str = "AskFor") -> str:
        """Génère le sous-programme AskFor complet."""
        defaults = cls.get_default_params()
        p = {**defaults, **params}
        msg = p.get('message', 'Continuer ?')
        park = p.get('park_before', True)

        lines = [f"program {prog_name} returns DialogResult"]
        lines.extend(cls._build_tool_line(p))
        if park:
            lines.extend([
                "    SpraySystem Off",
                "    Spindle Off",
                "    MoveToParkPosition",
            ])
        lines.extend([
            f'    result = Dialog message="{msg}" Yes=true No=true',
            "    return result",
            "endprogram",
        ])
        return "\n".join(lines)
