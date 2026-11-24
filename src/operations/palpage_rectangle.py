"""Opération: Palpage rectangle (RectangleMeasure du brut).

Le palpage seul, sans la manipulation: c'est « Retournement pièce »
privé de sa question opérateur, de son park et de son changement
d'outil. Sert à reprendre l'origine et l'orientation d'un brut posé
en début de programme.

    program Palpage_X100_Y20
        SafeRapid X=0.000 Y=0.000 Z=5
        RectangleMeasure (
             dimensionX=100  dimensionY=20  Center  Outside
             xMeasureZOffset=-5  yMeasureZOffset=-5
             YPositive  distanceForRotation=80  Wcs  … )
    endprogram

Deux valeurs se déduisent des cotes, sans que l'utilisateur ait à les
poser:
  - `distanceForRotation` = 80 % de la plus grande cote;
  - le sens de la mesure d'orientation se prend sur le LONG côté
    (X plus grand que Y → YPositive, sinon XPositive).

Le Z du SafeRapid est celui du formulaire: il n'est PAS recalculé
depuis strokeRapidZ + strokeCuttingZ comme celui des usinages — on
approche un palpeur, pas une fraise.

C'est ce module qui porte la génération; « Retournement pièce » la
réutilise pour son propre palpage.
"""

from typing import List, Dict, Any

from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement
)
from src.operations.registry import OperationRegistry


def parametres_palpage(groupe: str = "Palpage",
                       groupe_expert: str = "Palpage expert"
                       ) -> List[ParameterDef]:
    """Champs communs au palpage rectangle et au retournement.

    En mode simple: les deux cotes du brut, la profondeur de palpage,
    le Z d'approche, et la POSITION du palpage Z — une pièce
    retournée n'a pas toujours son dessus au centre (bossage,
    perçage), il faut pouvoir viser à côté."""
    champs = [
        ParameterDef("width_x", "Dimension X", ParameterType.FLOAT,
                     default=100.0, min_value=0.1, max_value=2000.0,
                     unit="mm", group=groupe,
                     tooltip="Cote du BRUT en X (dimensionX)"),
        ParameterDef("width_y", "Dimension Y", ParameterType.FLOAT,
                     default=20.0, min_value=0.1, max_value=2000.0,
                     unit="mm", group=groupe,
                     tooltip="Cote du BRUT en Y (dimensionY)"),
        ParameterDef("probe_depth", "Profondeur de palpage",
                     ParameterType.FLOAT, default=5.0,
                     min_value=0.1, max_value=200.0, unit="mm",
                     group=groupe,
                     tooltip="Hauteur sous le dessus du brut où le "
                             "palpeur touche les flancs "
                             "(xMeasureZOffset et yMeasureZOffset)"),
        ParameterDef("probe_safe_z", "Z du SafeRapid",
                     ParameterType.FLOAT, default=5.0,
                     min_value=0.0, max_value=200.0, unit="mm",
                     group=groupe,
                     tooltip="Hauteur d'approche AVANT la mesure.\n"
                             "Indépendante de strokeRapidZ + "
                             "strokeCuttingZ: on approche un palpeur."),

        ParameterDef("rotation_distance", "Distance de rotation",
                     ParameterType.FLOAT, default=0.0,
                     min_value=0.0, max_value=2000.0, unit="mm",
                     group=groupe_expert, expert_only=True,
                     tooltip="Écart entre les deux points qui donnent "
                             "l'orientation.\n0 = automatique: 80 % "
                             "de la plus grande des deux cotes."),
        ParameterDef("probe_side", "Côté palpé", ParameterType.CHOICE,
                     default="Outside", choices=["Outside", "Inside"],
                     unit="", group=groupe_expert, expert_only=True),
        ParameterDef("origin", "Origine mesurée", ParameterType.CHOICE,
                     default="Center",
                     choices=["Center", "LeftFront", "RightFront",
                              "LeftRear", "RightRear"],
                     unit="", group=groupe_expert, expert_only=True),
        ParameterDef("rotation_axis", "Sens de rotation",
                     ParameterType.CHOICE, default="Auto",
                     choices=["Auto", "YPositive", "XPositive"],
                     unit="", group=groupe_expert, expert_only=True,
                     tooltip="Auto: YPositive si X est la plus grande "
                             "cote, XPositive sinon — l'orientation "
                             "se prend sur le long côté."),
        ParameterDef("x_measure_y_shift", "xMeasureYShift",
                     ParameterType.FLOAT, default=0.0,
                     min_value=-2000.0, max_value=2000.0, unit="mm",
                     group=groupe_expert, expert_only=True),
        ParameterDef("y_measure_x_shift", "yMeasureXShift",
                     ParameterType.FLOAT, default=0.0,
                     min_value=-2000.0, max_value=2000.0, unit="mm",
                     group=groupe_expert, expert_only=True),
        ParameterDef("z_measure_x_shift", "Palpage Z: décalage X",
                     ParameterType.FLOAT, default=0.0,
                     min_value=-2000.0, max_value=2000.0, unit="mm",
                     group=groupe,
                     tooltip="zMeasureXShift: où le palpeur touche le "
                             "dessus, en X depuis le centre du brut. "
                             "0 = au centre."),
        ParameterDef("z_measure_y_shift", "Palpage Z: décalage Y",
                     ParameterType.FLOAT, default=0.0,
                     min_value=-2000.0, max_value=2000.0, unit="mm",
                     group=groupe,
                     tooltip="zMeasureYShift: idem en Y."),
        ParameterDef("origin_x_shift", "originXShift",
                     ParameterType.FLOAT, default=0.0,
                     min_value=-2000.0, max_value=2000.0, unit="mm",
                     group=groupe_expert, expert_only=True),
        ParameterDef("origin_y_shift", "originYShift",
                     ParameterType.FLOAT, default=0.0,
                     min_value=-2000.0, max_value=2000.0, unit="mm",
                     group=groupe_expert, expert_only=True),
        ParameterDef("origin_z_shift", "originZShift",
                     ParameterType.FLOAT, default=0.0,
                     min_value=-2000.0, max_value=2000.0, unit="mm",
                     group=groupe_expert, expert_only=True),
        ParameterDef("skip_z_measure", "Ne pas mesurer le Z",
                     ParameterType.BOOL, default=False, unit="",
                     group=groupe_expert, expert_only=True,
                     tooltip="skipZMeasure. Décoché, le Z mesuré sert "
                             "aux palpages suivants."),
        ParameterDef("skip_z_result", "Ignorer le Z pour l'origine",
                     ParameterType.BOOL, default=False, unit="",
                     group=groupe_expert, expert_only=True,
                     tooltip="skipZMeasureResult: le Z mesuré ne "
                             "modifie pas l'origine programme"),
        ParameterDef("force_safe_height", "forceSafeHeight",
                     ParameterType.BOOL, default=False, unit="",
                     group=groupe_expert, expert_only=True),
        ParameterDef("wcs", "Écrire dans le WCS", ParameterType.BOOL,
                     default=True, unit="", group=groupe_expert,
                     expert_only=True,
                     tooltip="Wcs: la mesure devient l'origine "
                             "programme"),
    ]
    return champs


@OperationRegistry.register("palpage_rectangle")
class PalpageRectangle(AbstractOperation):
    OP_TYPE = "palpage_rectangle"
    DISPLAY_NAME = "Palpage rectangle"
    CATEGORY = "Réglage"
    HORS_MATIERE = True
    DESCRIPTION = ("RectangleMeasure du brut: origine et orientation "
                   "reprises sur ses quatre flancs")
    ICON = "ruler"
    INLINE = False
    REQUIRES_TOOL = False
    REQUIRES_COORDINATES = True

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return parametres_palpage()

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        return ToolRequirement(
            tool_types=[],
            description="Palpeur ou outil en place (aucun changement)")

    # ── Valeurs déduites des cotes ──

    @classmethod
    def program_name(cls, params: Dict[str, Any]) -> str:
        """Nom du sous-programme, d'après les cotes palpées."""
        p = {**cls.get_default_params(), **params}

        def _cote(valeur):
            return f"{float(valeur or 0):g}".replace('.', '_').replace(
                '-', 'm')

        return (f"Palpage_X{_cote(p.get('width_x'))}"
                f"_Y{_cote(p.get('width_y'))}")

    @classmethod
    def rotation_distance(cls, params: Dict[str, Any]) -> float:
        """Écart des deux points d'orientation.

        80 % de la plus grande cote: assez large pour que l'angle soit
        précis, assez court pour rester sur la matière."""
        p = {**cls.get_default_params(), **params}
        saisie = float(p.get('rotation_distance', 0.0) or 0.0)
        if saisie > 0:
            return saisie
        grand = max(float(p.get('width_x', 0.0) or 0.0),
                    float(p.get('width_y', 0.0) or 0.0))
        return round(grand * 0.8, 3)

    @classmethod
    def rotation_axis(cls, params: Dict[str, Any]) -> str:
        """Sens de la mesure d'orientation: sur le LONG côté."""
        p = {**cls.get_default_params(), **params}
        choix = str(p.get('rotation_axis', 'Auto') or 'Auto')
        if choix in ("YPositive", "XPositive"):
            return choix
        wx = float(p.get('width_x', 0.0) or 0.0)
        wy = float(p.get('width_y', 0.0) or 0.0)
        return "YPositive" if wx > wy else "XPositive"

    # ── Code ──

    @classmethod
    def generate_probe_program(cls, params: Dict[str, Any],
                               prog_name: str = "",
                               x: float = 0.0, y: float = 0.0) -> str:
        """Sous-programme RectangleMeasure."""
        p = {**cls.get_default_params(), **params}
        nom = prog_name or cls.program_name(p)

        def _f(cle, defaut=0.0):
            try:
                return float(p.get(cle, defaut) or 0.0)
            except (TypeError, ValueError):
                return float(defaut)

        # La profondeur se saisit en positif: le palpeur descend, donc
        # l'offset qui part à la machine est négatif
        profondeur = -abs(_f('probe_depth', 5.0))
        booleen = {True: "true", False: "false"}
        lignes = [
            f"program {nom}",
            f"    SafeRapid X={x:.3f} Y={y:.3f} "
            f"Z={_f('probe_safe_z', 5.0):g}",
            "    RectangleMeasure (",
            f"         dimensionX={_f('width_x'):g}",
            f"         dimensionY={_f('width_y'):g}",
            f"         {p.get('origin', 'Center')}",
            f"         {p.get('probe_side', 'Outside')}",
            f"         xMeasureYShift={_f('x_measure_y_shift'):g}",
            f"         xMeasureZOffset={profondeur:g}",
            f"         yMeasureXShift={_f('y_measure_x_shift'):g}",
            f"         yMeasureZOffset={profondeur:g}",
            f"         zMeasureXShift={_f('z_measure_x_shift'):g}",
            f"         zMeasureYShift={_f('z_measure_y_shift'):g}",
            f"         {cls.rotation_axis(p)}",
            f"         distanceForRotation={cls.rotation_distance(p):g}",
        ]
        if p.get('wcs', True):
            lignes.append("         Wcs")
        lignes += [
            f"         originXShift={_f('origin_x_shift'):g}",
            f"         originYShift={_f('origin_y_shift'):g}",
            f"         originZShift={_f('origin_z_shift'):g}",
            f"         skipZMeasureResult="
            f"{booleen[bool(p.get('skip_z_result', False))]}",
            f"         forceSafeHeight="
            f"{booleen[bool(p.get('force_safe_height', False))]}",
            f"         skipZMeasure="
            f"{booleen[bool(p.get('skip_z_measure', False))]}",
            "         )",
            "endprogram",
        ]
        return "\n".join(lignes)

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        """L'opération vit dans son sous-programme (INLINE = False)."""
        return ""
