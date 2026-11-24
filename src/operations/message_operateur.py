"""Opération: Message (StatusMessage) — inline.

Manuel SimPL 3.1.1, § 5.7.3.3 « Notification » (p. 425): un message
dans la zone des messages de la machine, SANS arrêter le programme —
à la différence du Dialogue opérateur, qui attend une réponse.

    StatusMessage message="Retourner la pièce après ce programme"
"""

from typing import List, Dict, Any
from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement
)
from src.operations.registry import OperationRegistry


@OperationRegistry.register("message_operateur")
class MessageOperateur(AbstractOperation):
    DISPLAY_NAME = "Message"
    CATEGORY = "Utilitaire"
    HORS_MATIERE = True
    DESCRIPTION = ("Affiche un message sur la machine sans arrêter le "
                   "programme (StatusMessage)")
    ICON = "dialog"
    # nouvelle (manuel SimPL, octobre 2026): en expert par
    # défaut — en mode simple, clic droit sur sa catégorie
    EXPERT_ONLY = True
    INLINE = True
    REQUIRES_TOOL = False
    REQUIRES_COORDINATES = False

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return [
            ParameterDef("message", "Message", ParameterType.STRING,
                         default="", unit="", group="Message",
                         tooltip="Le texte affiché dans la zone des "
                                 "messages de la machine. Le programme "
                                 "continue (pour attendre une réponse: "
                                 "Dialogue opérateur)."),
        ]

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        return ToolRequirement(tool_types=[],
                               description="Aucun outil requis")

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        texte = " ".join(str(params.get('message', '') or '').split())
        if not texte:
            return "    # StatusMessage (message vide)"
        texte = texte.replace('"', "'")
        return f'    StatusMessage message="{texte}"'
