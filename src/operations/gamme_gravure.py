# -*- coding: utf-8 -*-
"""La gamme de gravure: un ensemble d'opérations, un outil par poste.

Une gravure fine ne se fait pas toujours avec un seul outil: une
cylindrique autour des contours, des coniques de plus en plus fines,
une pause si l'opérateur doit intervenir, des cylindriques pour
l'évidement. Chaque passage est une opération de la liste — un parcours, avec son
formulaire détaillé, son sous-programme et sa séquence dans le
SimPl. La gamme est l'ENSEMBLE qui les tient: cette opération-ci
en est la tête. Elle porte ce que tous les postes partagent — le
dessin relevé au canvas, le mode creux ou relief, le champ — et son
formulaire montre le tableau récapitulatif des postes, à éditer en
place: outil, cote, matière laissée, reprise.

Elle n'écrit rien dans le programme: ce sont ses membres qui
usinent.
"""

from typing import Any, Dict, List

from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement
)
from src.operations.gravure_2d5 import _SequenceConique
from src.operations.registry import OperationRegistry

#: nom de l'ensemble dans la liste
NOM_ENSEMBLE = "Gamme gravure"


@OperationRegistry.register("gamme_gravure")
class GammeGravure(AbstractOperation):
    """La tête de l'ensemble: le dessin, le champ, le tableau."""

    OP_TYPE = "gamme_gravure"
    DISPLAY_NAME = "Gamme gravure"
    CATEGORY = "Gravure"
    DESCRIPTION = ("Un ensemble de parcours, un outil par poste: "
                   "contour, coniques, pause, évidement — sur le "
                   "même dessin")
    ICON = "engrave"
    HORS_MATIERE = True
    INLINE = True
    REQUIRES_TOOL = False
    REQUIRES_COORDINATES = False
    SUPPORTS_MULTI_POINT = False

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        # Des contours relevés au canvas, et les mêmes champs de
        # forme que les parcours: c'est la gamme qui les tient, les
        # postes les reçoivent. (Le texte n'y est pas: « Gravure
        # texte » est une opération à part entière.)
        return list(_SequenceConique._champs_forme()) + [
            ParameterDef("contours", "Contours", ParameterType.STRING,
                         default="", unit="", group="Contour",
                         expert_only=True,
                         tooltip="Relevés au canvas (bouton « Reprendre "
                                 "les contours »), partagés par tous "
                                 "les postes de la gamme."),
        ]

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        return ToolRequirement(tool_types=[],
                               description="Aucun outil: chaque poste "
                                           "a le sien")

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        """Rien: ce sont les membres qui écrivent."""
        return ""

    @classmethod
    def validate_params(cls, params: Dict[str, Any]) -> List[str]:
        return []

    # ── le dessin ──

    @staticmethod
    def contours(params: Dict[str, Any]) -> List[List]:
        """Ceux relevés au canvas."""
        return _SequenceConique.contours(params)

    # ── l'ensemble ──

    @staticmethod
    def est_tete(op) -> bool:
        return getattr(op, 'operation_type', '') == "gamme_gravure"

    @staticmethod
    def tete_de(group_id: str, operations):
        """La tête de l'ensemble `group_id`, ou None si ce n'est pas
        une gamme (un ensemble d'instances, par exemple)."""
        if not group_id:
            return None
        for op in operations or []:
            if (getattr(op, 'group_id', '') == group_id
                    and GammeGravure.est_tete(op)):
                return op
        return None

    @staticmethod
    def membres(tete, operations) -> List[Any]:
        """Les postes de la gamme, dans l'ordre du programme."""
        gid = getattr(tete, 'group_id', '')
        if not gid:
            return []
        return [op for op in operations or []
                if getattr(op, 'group_id', '') == gid and op is not tete
                and not GammeGravure.est_tete(op)]

    @classmethod
    def propager(cls, tete, membres) -> int:
        """Recopie dans chaque poste ce que la gamme partage: le
        dessin et le champ. Rend le nombre de postes changés."""
        from src.operations.gamme_postes import CHAMPS_PARTAGES, _copie
        changes = 0
        for op in membres:
            if op.operation_type == "dialogue_operateur":
                continue
            for cle in CHAMPS_PARTAGES:
                if cle not in tete.params:
                    continue
                if op.params.get(cle) != tete.params[cle]:
                    op.params[cle] = _copie(tete.params[cle])
                    changes += 1
        return changes
