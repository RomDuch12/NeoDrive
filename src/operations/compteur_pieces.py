"""Opération: Compteur de pièces / numéro de série.

Reprend le mécanisme de persistance documenté par Datron
(UserDataPersistence/PartsCounter.simpl): `loadvalueof` relit la
valeur conservée d'une exécution à l'autre, `savevalueof` l'enregistre.

    compteur:number
    loadvalueof compteur 0
    compteur = compteur + 1
    savevalueof compteur

La variable déclarée est utilisable par les autres opérations — en
particulier par la Gravure texte, qui peut alors graver un numéro de
série auto-incrémenté (voir `serial_expression`).
"""

from typing import List, Dict, Any
from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement
)
from src.operations.registry import OperationRegistry
from src.operations.parametres_operateur import sanitize_var


@OperationRegistry.register("compteur_pieces")
class CompteurPieces(AbstractOperation):
    OP_TYPE = "compteur_pieces"
    DISPLAY_NAME = "Compteur de pièces"
    CATEGORY = "Utilitaire"
    HORS_MATIERE = True
    DESCRIPTION = ("Compteur persistant entre exécutions (traçabilité, "
                   "numéro de série gravé)")
    ICON = "dialogue"
    INLINE = True
    REQUIRES_TOOL = False
    REQUIRES_COORDINATES = False
    SUPPORTS_MULTI_POINT = False
    EXPERT_ONLY = True

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return [
            ParameterDef("var_name", "Variable", ParameterType.STRING,
                         default="compteur", group="Compteur",
                         tooltip="Nom de la variable persistante, "
                                 "réutilisable par les autres "
                                 "opérations (gravure...)"),
            ParameterDef("start_value", "Valeur initiale",
                         ParameterType.INT, default=1,
                         min_value=0, max_value=999999,
                         group="Compteur",
                         tooltip="Valeur au tout premier lancement, "
                                 "avant toute sauvegarde"),
            ParameterDef("step", "Incrément", ParameterType.INT,
                         default=1, min_value=1, max_value=1000,
                         group="Compteur"),
            ParameterDef("show_dialog", "Afficher la valeur",
                         ParameterType.BOOL, default=True,
                         group="Compteur",
                         tooltip="Affiche le numéro courant à "
                                 "l'opérateur au lancement"),
            ParameterDef("prefix", "Préfixe", ParameterType.STRING,
                         default="", group="Numéro de série",
                         tooltip="Texte devant le numéro dans les "
                                 "gravures (ex: « SN- »)"),
            ParameterDef("digits", "Chiffres", ParameterType.INT,
                         default=0, min_value=0, max_value=9,
                         group="Numéro de série", expert_only=True,
                         tooltip="0 = pas de remplissage. Sinon le "
                                 "numéro est complété par des zéros "
                                 "(3 → 007)"),
        ]

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        return ToolRequirement(tool_types=[], description="")

    @classmethod
    def variable_name(cls, params: Dict[str, Any]) -> str:
        return sanitize_var(params.get('var_name') or 'compteur',
                            'compteur')

    @classmethod
    def declared_variables(cls, params: Dict[str, Any]) -> List[tuple]:
        """Variables à déclarer au niveau module."""
        out = [(cls.variable_name(params), 'number')]
        if cls._serial_var(params):
            out.append((cls._serial_var(params), 'string'))
        return out

    @classmethod
    def _serial_var(cls, params: Dict[str, Any]) -> str:
        """Variable texte « numéro de série » (préfixe + numéro),
        créée seulement si un préfixe ou un remplissage est demandé."""
        p = {**cls.get_default_params(), **params}
        if not str(p.get('prefix') or '') and not int(p.get('digits', 0) or 0):
            return ""
        return cls.variable_name(params) + "_txt"

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        defaults = cls.get_default_params()
        p = {**defaults, **params}
        var = cls.variable_name(p)
        start = int(p.get('start_value', 1) or 0)
        step = max(1, int(p.get('step', 1) or 1))
        lines = [
            "    # ── Compteur de pièces (persistant) ──",
            f"    loadvalueof {var} {start}",
        ]
        serial = cls._serial_var(p)
        if serial:
            prefix = str(p.get('prefix') or '').replace('"', "'")
            digits = int(p.get('digits', 0) or 0)
            if digits > 0:
                # StringFormat suit les formats .NET: « 000 » complète
                # à gauche par des zéros (7 → 007)
                zeros = "0" * digits
                lines.append(
                    f'    {serial} = StringFormat '
                    f'baseString="{prefix}{{0:{zeros}}}" p0={var}')
            else:
                lines.append(
                    f'    {serial} = "{prefix}" + ValueToString({var})')
        if p.get('show_dialog', True):
            shown = serial or f"ValueToString({var})"
            lines.append(
                f'    Dialog message="Pièce n° " + {shown} '
                f'caption="Compteur"')
        lines.append(f"    {var} = {var} + {step}")
        lines.append(f"    savevalueof {var}")
        return "\n".join(lines)

    @classmethod
    def validate_params(cls, params: Dict[str, Any]) -> List[str]:
        errors = []
        if not cls.variable_name(params):
            errors.append("Nom de variable invalide")
        return errors
