"""Opération: Table à vide (Vacuum, VacuumSelection) — inline.

Manuel SimPL 3.1.1, § 5.5.4 « Vacuum » (p. 338-339): la pompe à vide en
marche ou à l'arrêt; les raccords ouverts sous la pièce seulement (une
meilleure adhérence).

    Vacuum mode=Activation.On
    VacuumSelection valve1=true valve2=true valve3=false
        valve4=false valve5=false valve6=false
"""

from typing import Any, Dict, List

from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement
)
from src.operations.registry import OperationRegistry

#: les raccords de la table à vide
RACCORDS = 6


@OperationRegistry.register("table_vide")
class TableVide(AbstractOperation):
    DISPLAY_NAME = "Table à vide"
    CATEGORY = "Réglage"
    HORS_MATIERE = True
    DESCRIPTION = ("Vacuum / VacuumSelection: la pompe à vide et les "
                   "raccords ouverts sous la pièce")
    ICON = "settings"
    EXPERT_ONLY = True
    INLINE = True
    REQUIRES_TOOL = False
    REQUIRES_COORDINATES = False

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        g = "Vide"
        params = [
            ParameterDef("mode", "Pompe à vide", ParameterType.CHOICE,
                         default="Marche", choices=["Marche", "Arrêt"],
                         group=g,
                         tooltip="Vacuum mode=Activation.On / Off"),
            ParameterDef("select_valves", "Choisir les raccords",
                         ParameterType.BOOL, default=False, group=g,
                         tooltip="Écrire VacuumSelection: seuls les "
                                 "raccords cochés sont ouverts (ceux sous "
                                 "la pièce)"),
        ]
        for k in range(1, RACCORDS + 1):
            params.append(ParameterDef(
                f"valve{k}", f"Raccord {k}", ParameterType.BOOL,
                default=k == 1, group=g))
        return params

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        return ToolRequirement(tool_types=[],
                               description="Aucun outil requis")

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        p = {**cls.get_default_params(), **params}
        marche = str(p.get('mode', 'Marche')) != "Arrêt"
        lignes = [f"    Vacuum mode=Activation.{'On' if marche else 'Off'}"]
        if marche and p.get('select_valves'):
            valves = " ".join(
                f"valve{k}={'true' if p.get(f'valve{k}') else 'false'}"
                for k in range(1, RACCORDS + 1))
            lignes.append(f"    VacuumSelection {valves}")
        return "\n".join(lignes)
