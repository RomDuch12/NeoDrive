"""Opération: Séquence Datron embarquée.

Réutilise une SEQUENCE issue d'un programme Datron (bloc $$$) comme
opération NeoDrive éditable. Génération:
  - En-tête:   @ EmbeddedSequences = true @  +  sequence NOM
  - Sous-prog: Tool/Rpm/SetFeedTechnology + appel du NOM
  - Pied:      bloc $$$ NOM avec les Z ajustés (offset/échelle)

Le code de la séquence est stocké dans params['sequence_code']
(non exposé dans le formulaire — potentiellement des milliers de
lignes). L'offset et l'échelle Z s'appliquent aux Z ≤ 0 uniquement
(profondeurs et passes), les dégagements restent intacts.
"""

from typing import List, Dict, Any
from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement
)
from src.operations.registry import OperationRegistry


@OperationRegistry.register("sequence_datron")
class SequenceDatron(AbstractOperation):
    DISPLAY_NAME = "Séquence Datron"
    CATEGORY = "Usinage"
    DESCRIPTION = ("Séquence d'usinage Datron embarquée ($$$), "
                   "profondeur/passes Z ajustables")
    ICON = "operation"
    INLINE = False
    REQUIRES_TOOL = True
    REQUIRES_COORDINATES = False
    SUPPORTS_MULTI_POINT = False

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return [
            ParameterDef("sequence_name", "Nom séquence",
                         ParameterType.STRING, default="SEQUENCE_1",
                         unit="", group="Séquence",
                         tooltip="Nom du bloc $$$ (unique dans le "
                                 "programme généré)"),
            ParameterDef("z_scale", "Échelle Z", ParameterType.FLOAT,
                         default=1.0, min_value=0.01, max_value=10.0,
                         unit="×", group="Profondeur",
                         tooltip="Multiplie les Z ≤ 0 de la séquence "
                                 "(profondeurs ET passes)"),
            ParameterDef("z_offset", "Offset Z", ParameterType.FLOAT,
                         default=0.0, min_value=-50.0, max_value=50.0,
                         unit="mm", group="Profondeur",
                         tooltip="Ajouté aux Z ≤ 0 après l'échelle "
                                 "(négatif = plus profond)"),
        ]

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        return ToolRequirement(tool_types=[], description="Tout outil")

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        """Dans le sous-programme: appel de la séquence par son nom."""
        name = str(params.get('sequence_name', 'SEQUENCE_1')).strip() \
            or "SEQUENCE_1"
        if not str(params.get('sequence_code') or '').strip():
            # pas de bloc $$$ pour une séquence vide: l'appeler
            # arrêterait la machine sur un nom inconnu
            return f"    # {name}: séquence vide, rien à usiner"
        return f"    {name}"

    @classmethod
    def build_sequence_block(cls, params: Dict[str, Any]) -> str:
        """Construit le bloc $$$ complet (pied de programme), avec les
        ajustements Z appliqués."""
        name = str(params.get('sequence_name', 'SEQUENCE_1')).strip() \
            or "SEQUENCE_1"
        code = str(params.get('sequence_code', '') or '').rstrip()
        block = f"$$$ {name}\n{code}"
        try:
            scale = float(params.get('z_scale', 1.0) or 1.0)
            offset = float(params.get('z_offset', 0.0) or 0.0)
        except (TypeError, ValueError):
            scale, offset = 1.0, 0.0
        if scale != 1.0 or offset != 0.0:
            from src.io.simpl_batch import adjust_sequence_z
            block, _n = adjust_sequence_z(
                block, sequence=name, offset=offset, scale=scale)
        return block

    @classmethod
    def validate_params(cls, params: Dict[str, Any]) -> List[str]:
        errors = super().validate_params(params)
        if not str(params.get('sequence_code', '') or '').strip():
            errors.append(
                "Séquence vide — importez-la depuis Édition SimPl "
                "(bouton 'Séquence → opération')")
        return errors
