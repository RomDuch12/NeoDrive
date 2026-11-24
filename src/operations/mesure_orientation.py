"""Opération: Mesure d'orientation de la pièce (2 palpages).

Une pièce rarement parfaitement d'équerre dans l'étau fait dériver
tout l'usinage. Plutôt que de la réaligner mécaniquement, on palpe
DEUX repères de position nominale connue et on fait pivoter le repère
local de l'angle mesuré.

Méthode documentée par Datron
(MeasureOrientationWithTwoMeasurings.simpl):

    PrePositioning X=… Y=… Z=…
    r1 = CircleMeasure( diameter=… Inside None skipZMeasure )
    …
    gamma = Degree( Atan2( dy, dx ) )
    RotateLcsInc gamma=gamma

`None` demande à CircleMeasure de NE PAS créer de repère: on ne veut
que les coordonnées mesurées. `skipZMeasure` évite un palpage Z
inutile sur le second repère.
"""

from typing import List, Dict, Any
from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement
)
from src.operations.registry import OperationRegistry

AXE_X = "X (les 2 repères alignés sur X)"
AXE_Y = "Y (les 2 repères alignés sur Y)"
INSIDE = "Intérieur (perçage)"
OUTSIDE = "Extérieur (bossage)"


@OperationRegistry.register("mesure_orientation")
class MesureOrientation(AbstractOperation):
    OP_TYPE = "mesure_orientation"
    DISPLAY_NAME = "Mesure d'orientation"
    CATEGORY = "Réglage"
    HORS_MATIERE = True
    DESCRIPTION = ("Palpe deux repères et corrige la rotation du "
                   "repère (pièce de travers dans l'étau)")
    ICON = "probe"
    INLINE = True
    REQUIRES_TOOL = False
    REQUIRES_COORDINATES = False
    SUPPORTS_MULTI_POINT = False
    EXPERT_ONLY = True

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return [
            ParameterDef("x1", "X repère 1", ParameterType.FLOAT,
                         default=0.0, unit="mm", group="Repère 1"),
            ParameterDef("y1", "Y repère 1", ParameterType.FLOAT,
                         default=0.0, unit="mm", group="Repère 1"),
            ParameterDef("d1", "Ø repère 1", ParameterType.FLOAT,
                         default=10.0, min_value=0.5, max_value=500.0,
                         unit="mm", group="Repère 1"),
            ParameterDef("x2", "X repère 2", ParameterType.FLOAT,
                         default=50.0, unit="mm", group="Repère 2"),
            ParameterDef("y2", "Y repère 2", ParameterType.FLOAT,
                         default=0.0, unit="mm", group="Repère 2"),
            ParameterDef("d2", "Ø repère 2", ParameterType.FLOAT,
                         default=10.0, min_value=0.5, max_value=500.0,
                         unit="mm", group="Repère 2"),
            ParameterDef("feature", "Type de repère",
                         ParameterType.CHOICE, default=INSIDE,
                         choices=[INSIDE, OUTSIDE], group="Mesure",
                         tooltip="Perçage (mesure intérieure) ou "
                                 "bossage (mesure extérieure)"),
            ParameterDef("axis", "Alignement nominal",
                         ParameterType.CHOICE, default=AXE_X,
                         choices=[AXE_X, AXE_Y], group="Mesure",
                         tooltip="Axe sur lequel les deux repères "
                                 "sont censés être alignés"),
            ParameterDef("approach_z", "Z d'approche",
                         ParameterType.FLOAT, default=15.0,
                         unit="mm", group="Mesure",
                         tooltip="Hauteur de positionnement avant "
                                 "chaque palpage"),
            ParameterDef("set_origin", "Origine sur le repère 1",
                         ParameterType.BOOL, default=False,
                         group="Mesure",
                         tooltip="Le premier palpage crée aussi le "
                                 "repère (origine au centre du "
                                 "repère 1)"),
            ParameterDef("show_result", "Afficher l'angle",
                         ParameterType.BOOL, default=True,
                         group="Mesure",
                         tooltip="Montre l'angle mesuré à "
                                 "l'opérateur avant de tourner"),
            ParameterDef("max_angle", "Angle max toléré",
                         ParameterType.FLOAT, default=5.0,
                         min_value=0.0, max_value=90.0, unit="°",
                         group="Sécurité",
                         tooltip="Au-delà, le programme demande "
                                 "confirmation: un angle aberrant "
                                 "signale un palpage raté.\n"
                                 "0 = pas de contrôle."),
        ]

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        return ToolRequirement(tool_types=[],
                               description="Palpeur / outil de mesure")

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        defaults = cls.get_default_params()
        p = {**defaults, **params}
        side = ("Inside" if p.get('feature', INSIDE) == INSIDE
                else "Outside")
        z = float(p.get('approach_z', 15.0) or 15.0)
        x1, y1 = float(p.get('x1', 0.0)), float(p.get('y1', 0.0))
        x2, y2 = float(p.get('x2', 0.0)), float(p.get('y2', 0.0))

        lines = ["    # ── Mesure d'orientation (2 palpages) ──",
                 f"    PrePositioning X={x1:g} Y={y1:g} Z={z:g}"]
        # `None` = ne pas créer de repère à partir de cette mesure
        opts1 = f"diameter={float(p.get('d1', 10.0)):g} {side}"
        if not p.get('set_origin', False):
            opts1 += " None"
        lines.append(f"    ndOrientRef1 = CircleMeasure( {opts1} )")
        lines.append(f"    PrePositioning X={x2:g} Y={y2:g} Z={z:g}")
        lines.append(
            f"    ndOrientRef2 = CircleMeasure( "
            f"diameter={float(p.get('d2', 10.0)):g} {side} None "
            f"skipZMeasure )")

        lines += [
            "    ndOrientDx = ndOrientRef2.MeasuredPosition.X - "
            "ndOrientRef1.MeasuredPosition.X",
            "    ndOrientDy = ndOrientRef2.MeasuredPosition.Y - "
            "ndOrientRef1.MeasuredPosition.Y",
        ]
        if p.get('axis', AXE_X) == AXE_X:
            lines.append(
                "    ndOrientAngle = Degree( Atan2( ndOrientDy, "
                "ndOrientDx ) )")
        else:
            # Alignement sur Y: l'angle se mesure depuis l'axe Y
            lines.append(
                "    ndOrientAngle = Degree( Atan2( ndOrientDx, "
                "ndOrientDy ) ) * -1")

        max_angle = float(p.get('max_angle', 0.0) or 0.0)
        indent = "    "
        if max_angle > 0:
            lines += [
                f"    # Garde-fou: un angle aberrant trahit un "
                f"palpage raté",
                f"    if Abs(ndOrientAngle) > {max_angle:g}",
                '        ndOrientOk = Dialog Yes No message="Angle '
                'mesuré: " + ValueToString(ndOrientAngle) + " °',
                "",
                f"Au-delà de {max_angle:g} ° attendus.",
                'Corriger le repère quand même ?" caption="Mesure '
                'd\'orientation"',
                "        if ndOrientOk == DialogResult.Yes",
                "            RotateLcsInc gamma=ndOrientAngle",
                "        endif",
                "    else",
            ]
            indent = "        "
        if p.get('show_result', True):
            lines.append(
                f'{indent}Dialog Ok message="Orientation mesurée: " '
                f'+ ValueToString(ndOrientAngle) + " °" '
                f'caption="Mesure d\'orientation"')
        lines.append(f"{indent}RotateLcsInc gamma=ndOrientAngle")
        if max_angle > 0:
            lines.append("    endif")
        return "\n".join(lines)

    @classmethod
    def declared_variables(cls, params: Dict[str, Any]) -> List[tuple]:
        """Aucune variable de module: tout est local au Main."""
        return []

    @classmethod
    def validate_params(cls, params: Dict[str, Any]) -> List[str]:
        p = {**cls.get_default_params(), **params}
        errors = []
        dx = float(p.get('x2', 0.0)) - float(p.get('x1', 0.0))
        dy = float(p.get('y2', 0.0)) - float(p.get('y1', 0.0))
        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            errors.append(
                "Les deux repères sont au même endroit: "
                "l'angle serait indéterminé")
        elif (dx * dx + dy * dy) ** 0.5 < 10.0:
            errors.append(
                "Repères trop proches (< 10 mm): la mesure d'angle "
                "serait imprécise")
        return errors
