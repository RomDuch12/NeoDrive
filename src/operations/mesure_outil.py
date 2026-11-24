"""Opération: Mesure de longueur d'outil (MeasureToolLength) — inline.

Manuel SimPL 3.1.1, § 5.1.6 « Length measurement » (p. 145): la
longueur de l'outil EN BROCHE est mesurée; hors tolérance (cassure,
usure, arête rapportée — MeasuringTolerance), le programme s'arrête
sur un dialogue. Placée après l'opération d'un outil, elle vérifie
qu'il n'a pas cassé avant la suite.

    MeasureToolLength skipRestoring=false skipSaving=false
        skipDialogs=false
"""

from typing import List, Dict, Any
from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement
)
from src.operations.registry import OperationRegistry


@OperationRegistry.register("mesure_outil")
class MesureOutil(AbstractOperation):
    DISPLAY_NAME = "Mesure longueur outil"
    CATEGORY = "Utilitaire"
    HORS_MATIERE = True
    DESCRIPTION = ("Mesure l'outil en broche: cassé ou usé, le programme "
                   "s'arrête (MeasureToolLength)")
    ICON = "ruler"
    # nouvelle (manuel SimPL, octobre 2026): en expert par
    # défaut — en mode simple, clic droit sur sa catégorie
    EXPERT_ONLY = True
    INLINE = True
    REQUIRES_TOOL = False
    REQUIRES_COORDINATES = False

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        g = "Mesure"
        return [
            ParameterDef("skip_restoring", "Ne pas revenir",
                         ParameterType.BOOL, default=False, group=g,
                         tooltip="La mesure s'arrête au-dessus du "
                                 "capteur: la dernière position n'est "
                                 "pas reprise (skipRestoring)"),
            ParameterDef("skip_saving", "Ne pas enregistrer",
                         ParameterType.BOOL, default=False, group=g,
                         tooltip="La longueur mesurée n'est pas gardée "
                                 "(skipSaving): un simple contrôle"),
            ParameterDef("skip_dialogs", "Sans dialogue",
                         ParameterType.BOOL, default=False, group=g,
                         expert_only=True,
                         tooltip="Hors tolérance, le programme continue "
                                 "et l'outil est verrouillé "
                                 "(skipDialogs)"),
        ]

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        return ToolRequirement(tool_types=[],
                               description="L'outil en broche")

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        oui = {True: "true", False: "false"}
        return ("    MeasureToolLength "
                f"skipRestoring={oui[bool(params.get('skip_restoring'))]} "
                f"skipSaving={oui[bool(params.get('skip_saving'))]} "
                f"skipDialogs={oui[bool(params.get('skip_dialogs'))]}")
