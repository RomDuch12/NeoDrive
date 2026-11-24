"""Opération: Import prog.

Choisir un fichier .SimPl le fait ENTRER dans le programme: ses
sous-programmes deviennent un ensemble repliable d'opérations
éditables (outil, régime, avances, profondeurs, mise en sourdine).
L'opération elle-même disparaît alors, remplacée par cet ensemble —
elle n'est qu'un point d'entrée.

À ne pas confondre avec « Appel prog externe », qui laisse le fichier
DEHORS: la machine le charge au vol, ses mises à jour s'appliquent
sans rien refaire, mais on ne voit ni ne règle ce qu'il usine.
"""

from typing import List, Dict, Any
from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType
)
from src.operations.registry import OperationRegistry


@OperationRegistry.register("import_programme")
class ImportProgramme(AbstractOperation):
    OP_TYPE = "import_programme"
    DISPLAY_NAME = "Import prog externe"
    CATEGORY = "Utilitaire"
    ICON = "external"
    DESCRIPTION = (
        "Importe un programme SimPl: ses sous-programmes deviennent "
        "un ensemble d'opérations éditables")
    INLINE = True
    REQUIRES_TOOL = False
    REQUIRES_COORDINATES = False
    SUPPORTS_MULTI_POINT = False

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return [
            ParameterDef(
                "filepath", "Fichier .SimPl", ParameterType.STRING,
                default="", unit="",
                tooltip="Le fichier choisi est importé: ses "
                        "sous-programmes rejoignent la liste "
                        "d'opérations, repliés sous un ensemble"),
        ]

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        """Rien à émettre: l'opération est remplacée par l'ensemble
        importé dès qu'un fichier est choisi. Tant qu'il n'y en a
        pas, elle ne produit qu'un rappel en commentaire."""
        path = str(params.get('filepath', '') or '').strip()
        if not path:
            return "    # Import prog: aucun fichier choisi"
        return ""

    @classmethod
    def validate_params(cls, params: Dict[str, Any]) -> List[str]:
        errors = super().validate_params(params)
        if not str(params.get('filepath', '') or '').strip():
            errors.append(
                "Aucun fichier choisi — bouton Parcourir sur la ligne "
                "du titre")
        return errors
