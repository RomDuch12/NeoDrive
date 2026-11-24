"""
Opération Appel Programme Externe.
Permet de sélectionner un fichier .SimPl existant et de l'appeler
comme sous-programme via usermodule.

Génération:
  - Après les imports: usermodule UM_nom="chemin\\programme.SimPl"
  - Dans Main: UM_nom
  - Le label est dérivé automatiquement du nom de l'opération
"""

import re
from typing import List, Dict, Any
from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType
)
from src.operations.registry import OperationRegistry


@OperationRegistry.register("appel_programme")
class AppelProgramme(AbstractOperation):
    OP_TYPE = "appel_programme"
    DISPLAY_NAME = "Appel prog externe"
    CATEGORY = "Utilitaire"
    ICON = "external"
    DESCRIPTION = (
        "Appelle un programme SimPl externe sans l'importer "
        "(usermodule). Le fichier reste maître de son contenu.")
    INLINE = True  # Géré directement dans Main (pas de sous-programme)
    REQUIRES_TOOL = False
    REQUIRES_COORDINATES = False
    SUPPORTS_MULTI_POINT = False

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return [
            ParameterDef(
                "filepath", "Chemin .SimPl", ParameterType.STRING,
                default="", unit="",
                tooltip="Chemin complet vers le fichier .SimPl externe"),
            ParameterDef(
                "preview", "Aperçu au canvas", ParameterType.BOOL,
                default=True, unit="",
                tooltip="Trace TOUT le parcours du programme appelé "
                        "(Canva 2D et 3D). Trop lourd: clic droit sur "
                        "l'opération, « une ligne sur 2, 3, 5 ou 10 »."),
        ]

    @classmethod
    def _build_label(cls, name: str) -> str:
        """Construit le label UM_ à partir du nom de l'opération.
        Remplace les espaces par _, supprime la ponctuation,
        et ajoute le préfixe UM_."""
        clean = name.strip().replace(' ', '_')
        # Supprimer tout caractère non alphanumérique/underscore
        clean = re.sub(r'[^A-Za-z0-9_]', '', clean)
        if not clean:
            clean = "Programme"
        if not clean.startswith('UM_'):
            clean = f"UM_{clean}"
        return clean

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        """Génère l'appel dans Main: juste le label."""
        p = {**cls.get_default_params(), **params}
        name = p.get('_name', 'Appel Prog Ext')
        label = cls._build_label(name)
        if not str(p.get('filepath', '') or '').strip():
            # sans chemin, pas de déclaration usermodule: l'appel
            # arrêterait la machine sur un nom inconnu
            return f"    # {label}: chemin du programme non défini"
        return f"    {label}"

    @classmethod
    def generate_usermodule_line(cls, params: Dict[str, Any]) -> str:
        """Génère la ligne usermodule pour la section imports."""
        p = {**cls.get_default_params(), **params}
        name = p.get('_name', 'Appel Prog Ext')
        label = cls._build_label(name)
        filepath = p.get('filepath', '').strip()
        if not filepath:
            return f'# usermodule {label} — chemin non défini'
        # Normaliser les backslashes
        filepath = filepath.replace('/', '\\')
        return f'usermodule {label}="{filepath}"'
