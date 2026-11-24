"""
Classe de base abstraite pour toutes les opérations CNC.
Chaque opération concrète hérite de AbstractOperation et définit:
- ses paramètres (ParameterDef)
- les types d'outils compatibles
- la méthode de génération de code SimPl
"""

from enum import Enum
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field


class ParameterType(Enum):
    FLOAT = "float"
    INT = "int"
    STRING = "string"
    BOOL = "bool"
    CHOICE = "choice"  # dropdown


@dataclass
class ParameterDef:
    """Définition d'un paramètre d'opération."""
    key: str                    # clé interne (ex: 'width_x')
    label: str                  # label affiché (ex: 'Largeur X (mm)')
    param_type: ParameterType   # type du paramètre
    default: Any = 0.0          # valeur par défaut
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    choices: List[str] = field(default_factory=list)  # pour CHOICE
    tooltip: str = ""           # info-bulle
    unit: str = "mm"            # unité affichée
    group: str = ""             # groupe visuel (ex: "Profondeur", "Avances")
    expert_only: bool = False   # masqué en mode non-expert
    multiline: bool = False     # STRING sur plusieurs lignes (un texte)


@dataclass
class ToolRequirement:
    """Définit les types d'outils compatibles avec une opération."""
    tool_types: List[str]       # liste de type_taraudage acceptés
    description: str = ""       # description pour l'utilisateur


# ── Groupage user-defined: les opérations portant le MÊME nom de
# groupe (et le même outil) sont usinées dans un seul sous-programme,
# donc un seul changement d'outil. Plusieurs groupes coexistent.
GROUP_PARAMS = [
    ParameterDef("group_name", "Groupe", ParameterType.STRING,
                 default="", unit="", group="Groupage",
                 tooltip="Nom de groupe libre. Les opérations de même "
                         "groupe ET même outil sont réunies dans un "
                         "seul sous-programme (un seul changement "
                         "d'outil).\nVide = pas de groupage explicite."),
]


# ── Paramètres de répétition réutilisables par toutes les opérations ──
REPEAT_PARAMS = [
    ParameterDef("repeat_x_count", "NbX", ParameterType.INT,
                 default=1, min_value=1, max_value=50,
                 group="Répétition"),
    ParameterDef("repeat_x_step", "PasX", ParameterType.FLOAT,
                 default=0.0, unit="mm", group="Répétition"),
    ParameterDef("repeat_y_count", "NbY", ParameterType.INT,
                 default=1, min_value=1, max_value=50,
                 group="Répétition"),
    ParameterDef("repeat_y_step", "PasY", ParameterType.FLOAT,
                 default=0.0, unit="mm", group="Répétition"),
    # La répétition de la répétition: la grille NbX × NbY entière est
    # reprise Nb2X fois en X et Nb2Y fois en Y — « (2 en X entraxe
    # 20, 4 en Y entraxe 10) × 2 en X entraxe 100 »
    ParameterDef("repeat2_x_count", "Nb2X", ParameterType.INT,
                 default=1, min_value=1, max_value=50,
                 group="Répétition",
                 tooltip="Second niveau: combien de fois la grille "
                         "NbX × NbY se répète en X"),
    ParameterDef("repeat2_x_step", "Pas2X", ParameterType.FLOAT,
                 default=0.0, unit="mm", group="Répétition",
                 tooltip="Second niveau: l'entraxe en X entre deux "
                         "grilles"),
    ParameterDef("repeat2_y_count", "Nb2Y", ParameterType.INT,
                 default=1, min_value=1, max_value=50,
                 group="Répétition",
                 tooltip="Second niveau: combien de fois la grille "
                         "NbX × NbY se répète en Y"),
    ParameterDef("repeat2_y_step", "Pas2Y", ParameterType.FLOAT,
                 default=0.0, unit="mm", group="Répétition",
                 tooltip="Second niveau: l'entraxe en Y entre deux "
                         "grilles"),
]


class AbstractOperation:
    """Classe abstraite pour une opération CNC."""

    # Identifiant unique de l'opération (défini par chaque sous-classe)
    OP_TYPE: str = ""
    # Nom affiché dans l'interface
    DISPLAY_NAME: str = ""
    # Catégorie pour le regroupement
    CATEGORY: str = "Usinage"
    #: l'opération ne touche PAS la matière (palpage, dialogue,
    #: réglage d'origine…): son tracé reste au canvas, mais elle
    #: n'a pas sa ligne dans la légende des outils — sauf réglage
    HORS_MATIERE: bool = False
    # Icône (nom sans extension)
    ICON: str = "operation"
    # Description courte
    DESCRIPTION: str = ""
    # Est-ce une opération inline (pas de sous-programme dédié) ?
    INLINE: bool = False
    # La liste des opérations montre-t-elle la ligne écrite (Déplacement,
    # commandes du manuel) plutôt que la durée ?
    LIST_DETAIL: bool = False
    # Groupes du formulaire montrés seulement pour certaines valeurs
    # d'un paramètre: {"Arc": ("commande", ("Arc",))}
    GROUPES_SELON: Dict[str, Tuple[str, Tuple[str, ...]]] = {}
    # Nécessite-t-elle un outil ?
    REQUIRES_TOOL: bool = True
    # Nécessite-t-elle des coordonnées X/Y ?
    REQUIRES_COORDINATES: bool = True
    # Supporte-t-elle une liste de points (multi-point) ?
    SUPPORTS_MULTI_POINT: bool = False
    # Visible uniquement en mode expert ?
    EXPERT_ONLY: bool = False
    #: paramètres en « _ » enregistrés quand même (projet, NDMETA,
    #: copie, annulation) — les autres sont des calculs du moment
    PARAMS_DURABLES: Tuple[str, ...] = ()

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        """Retourne la liste des paramètres de l'opération."""
        raise NotImplementedError

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        """Retourne les exigences d'outil pour cette opération."""
        return ToolRequirement(tool_types=[], description="Tout outil")

    @classmethod
    def get_default_params(cls) -> Dict[str, Any]:
        """Retourne un dict de paramètres avec leurs valeurs par défaut."""
        return {p.key: p.default for p in cls.get_parameters()}

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        """Génère le bloc de code SimPl pour cette opération.
        Ne génère PAS le wrapper program/endprogram ni l'appel outil.
        Uniquement le code de l'opération elle-même.
        """
        raise NotImplementedError

    @classmethod
    def validate_params(cls, params: Dict[str, Any]) -> List[str]:
        """Valide les paramètres. Retourne une liste d'erreurs (vide si OK)."""
        errors = []
        for pdef in cls.get_parameters():
            val = params.get(pdef.key)
            if val is None:
                continue
            if pdef.param_type in (ParameterType.FLOAT, ParameterType.INT):
                try:
                    num = float(val)
                    if pdef.min_value is not None and num < pdef.min_value:
                        errors.append(
                            f"{pdef.label}: valeur minimum {pdef.min_value}")
                    if pdef.max_value is not None and num > pdef.max_value:
                        errors.append(
                            f"{pdef.label}: valeur maximum {pdef.max_value}")
                except (ValueError, TypeError):
                    errors.append(f"{pdef.label}: valeur numérique attendue")
        return errors
