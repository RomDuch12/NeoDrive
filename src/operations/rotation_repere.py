"""Opération: Rotation du repère (RotateWcsInc) — inline.

Manuel SimPL 3.1.1, § 5.6.1.7 « Rotation incremental » (p. 266):

    RotateWcsInc gamma=45

tourne le repère pièce autour de Z: tout ce qui SUIT est usiné tourné
d'autant autour de l'origine courante. Pour revenir, une seconde
rotation de l'angle opposé (comme le décalage d'origine).

L'absolue (`RotateWcsAbs`, § 5.6.1.6) se rapporte au repère MACHINE:
elle efface l'orientation mesurée par un palpage (coin, rectangle).
Elle n'est proposée qu'en mode expert, et le formulaire le dit.
"""

from typing import List, Dict, Any
from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement
)
from src.operations.registry import OperationRegistry


@OperationRegistry.register("rotation_repere")
class RotationRepere(AbstractOperation):
    DISPLAY_NAME = "Rotation repère"
    CATEGORY = "Réglage"
    HORS_MATIERE = True
    DESCRIPTION = ("Tourne le repère pièce autour de Z: la suite est "
                   "usinée tournée (RotateWcsInc)")
    ICON = "rotate"
    # nouvelle (manuel SimPL, octobre 2026): en expert par
    # défaut — en mode simple, clic droit sur sa catégorie
    EXPERT_ONLY = True
    INLINE = True
    REQUIRES_TOOL = False
    REQUIRES_COORDINATES = False

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return [
            ParameterDef("gamma", "Angle", ParameterType.FLOAT,
                         default=0.0, min_value=-360.0, max_value=360.0,
                         unit="°", group="Rotation",
                         tooltip="Rotation autour de Z, en degrés, sens "
                                 "trigonométrique. Pour revenir: une "
                                 "seconde rotation de l'angle opposé."),
            ParameterDef("mode", "Référence", ParameterType.CHOICE,
                         default="Incrémentale",
                         choices=["Incrémentale", "Absolue"],
                         group="Rotation", expert_only=True,
                         tooltip="Incrémentale (RotateWcsInc): depuis le "
                                 "repère pièce courant — garde "
                                 "l'orientation palpée.\nAbsolue "
                                 "(RotateWcsAbs): depuis le repère "
                                 "MACHINE — efface l'orientation "
                                 "mesurée par un palpage."),
        ]

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        return ToolRequirement(tool_types=[],
                               description="Aucun outil requis")

    @staticmethod
    def angle(params: Dict[str, Any]) -> float:
        try:
            return float(params.get('gamma', 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def absolue(params: Dict[str, Any]) -> bool:
        return str(params.get('mode', '')).startswith("Abs")

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        p = {**cls.get_default_params(), **params}
        gamma = cls.angle(p)
        commande = "RotateWcsAbs" if cls.absolue(p) else "RotateWcsInc"
        if not gamma and not cls.absolue(p):
            return "    # RotateWcsInc (angle nul: rien à tourner)"
        return f"    {commande} gamma={gamma:g}"
