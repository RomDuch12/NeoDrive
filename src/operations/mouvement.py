"""Opération: Déplacement — inline.

Les mouvements du manuel SimPL 3.1.1 (§ 5.4.2 et 5.4.3) écrits un par
un, comme dans les programmes d'exemple DATRON (octobre 2026):

    Rapid X=50                       (rapide, coordonnées modales)
    Line Z=10                        (à l'avance de finition)
    Arc (X=5 Y=5 Z=0 dX=3 dY=3 radius=6 CCW)
    MoveToSafetyPosition / MoveToParkPosition

Une coordonnée vide n'est pas écrite: l'axe garde sa position.
"""

from typing import Any, Dict, List

from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement
)
from src.operations.registry import OperationRegistry

#: les commandes, et les champs que chacune écrit
COMMANDES = {
    "Rapid": ("X", "Y", "Z"),
    "Line": ("X", "Y", "Z"),
    "SafeRapid": ("X", "Y", "Z"),
    "PrePositioning": ("X", "Y", "Z"),
    "Arc": ("X", "Y", "Z", "dX", "dY", "dZ", "radius"),
    "MoveToSafetyPosition": (),
    "MoveToParkPosition": (),
}


def _nombre(v) -> str:
    texte = str(v if v is not None else "").strip().replace(",", ".")
    if not texte:
        return ""
    try:
        return f"{float(texte):g}"
    except ValueError:
        # une variable ou une expression SimPL, telle quelle
        return texte


@OperationRegistry.register("mouvement")
class Mouvement(AbstractOperation):
    DISPLAY_NAME = "Déplacement"
    CATEGORY = "Utilitaire"
    DESCRIPTION = ("Un mouvement du manuel: Rapid, Line, Arc (rayon), "
                   "SafeRapid, PrePositioning, position de sécurité ou "
                   "de parking")
    ICON = "shift"
    EXPERT_ONLY = True
    INLINE = True
    LIST_DETAIL = True
    GROUPES_SELON = {"Arc": ("commande", ("Arc",))}
    REQUIRES_TOOL = False
    REQUIRES_COORDINATES = False

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        bulle_axe = ("vide: l'axe n'est pas écrit et garde sa position "
                     "(coordonnées modales); un nombre ou une variable")
        return [
            ParameterDef("commande", "Commande", ParameterType.CHOICE,
                         default="Rapid", choices=list(COMMANDES),
                         unit="", group="Mouvement",
                         tooltip="Rapid: en rapide; Line: à l'avance de "
                                 "finition; Arc: un arc (centre décalé "
                                 "dX/dY de la pointe, ou rayon); "
                                 "SafeRapid: monte d'abord à la hauteur "
                                 "sûre"),
        ] + [
            ParameterDef(axe, axe, ParameterType.STRING, default="",
                         unit="mm", group="Mouvement",
                         tooltip=f"{axe}= ({bulle_axe})")
            for axe in ("X", "Y", "Z")
        ] + [
            ParameterDef(cle, cle, ParameterType.STRING, default="",
                         unit="mm", group="Arc",
                         tooltip=bulle)
            for cle, bulle in (
                ("dX", "Arc: centre décalé en X depuis la pointe de "
                       "l'outil"),
                ("dY", "Arc: centre décalé en Y depuis la pointe de "
                       "l'outil"),
                ("dZ", "Arc: montée ou descente pendant l'arc (hélice)"),
                ("radius", "Arc: le rayon"))
        ] + [
            ParameterDef("direction", "Sens", ParameterType.CHOICE,
                         default="CCW", choices=["CCW", "CW"], unit="",
                         group="Arc",
                         tooltip="CCW: trigonométrique; CW: horaire"),
        ]

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        return ToolRequirement(tool_types=[], description="Aucun outil requis")

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        p = {**cls.get_default_params(), **(params or {})}
        commande = p.get('commande') if p.get('commande') in COMMANDES \
            else "Rapid"
        morceaux = []
        for cle in COMMANDES[commande]:
            v = _nombre(p.get(cle))
            if v:
                morceaux.append(f"{cle}={v}")
        if commande == "Arc":
            sens = "CW" if p.get('direction') == "CW" else "CCW"
            return "    Arc (" + " ".join(morceaux + [sens]) + ")"
        if COMMANDES[commande] and not morceaux:
            return f"    # {commande}: aucune coordonnée"
        return "    " + " ".join([commande] + morceaux)
