"""Opération: Hélice / Hélice avec cercle complet (Helix / HelixWithFullCircle)

Manuel SimPL 3.1.1, § 5.4.2.4 et 5.4.2.5: deux MOUVEMENTS (pas des
cycles) — le centre de l'outil décrit une hélice de Ø `diameter` autour
de la position courante, descend de `deltaZ` au pas `pitch`; « avec
cercle complet », un tour plein au fond:

    HelixWithFullCircle diameter=8 deltaZ=0.5 pitch=0.4 startAngle=10 CCW

(Programme d'exemple DATRON, octobre 2026.) NeoDrive écrivait auparavant
« HelixWithFullCircle (diameter=… Inside depth=… infeedZ=…
finishingXY=…) », des paramètres de DrillMilling que la commande n'a
pas, et partait de la hauteur de sécurité: l'hélice tournait en l'air.
Désormais: descente au plan d'approche lente (strokeCuttingZ), hélice
jusqu'à Pz; le Ø usiné est compensé du Ø de la fraise (Inside: Ø − d,
Outside: Ø + d; Centre: le Ø est celui du centre de l'outil).
"""

from typing import List, Dict, Any
from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement,
    REPEAT_PARAMS
)
from src.operations.registry import OperationRegistry


@OperationRegistry.register("helice")
class Helice(AbstractOperation):
    DISPLAY_NAME = "Hélice"
    CATEGORY = "Perçage"
    EXPERT_ONLY = True
    DESCRIPTION = "Interpolation hélicoïdale (avec ou sans cercle complet en fond)"
    ICON = "helix"
    SUPPORTS_MULTI_POINT = True

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return [
            ParameterDef("full_circle", "Cercle complet en fond",
                         ParameterType.BOOL, default=True,
                         group="Options",
                         tooltip="Cochée: HelixWithFullCircle, Décochée: Helix"),
            ParameterDef("diameter", "Diamètre", ParameterType.FLOAT,
                         default=6.0, min_value=0.1, unit="mm",
                         group="Dimensions"),
            ParameterDef("side", "Côté usinage", ParameterType.CHOICE,
                         default="Inside",
                         choices=["Inside", "Outside", "Centre"],
                         group="Options",
                         tooltip="Inside: un trou de ce Ø (centre outil sur "
                                 "Ø − fraise); Outside: un tenon (Ø + "
                                 "fraise); Centre: le Ø du centre de "
                                 "l'outil, tel quel"),
            ParameterDef("direction", "Direction", ParameterType.CHOICE,
                         default="CCW",
                         choices=["CCW", "CW"],
                         group="Options"),
            ParameterDef("depth", "Pz", ParameterType.FLOAT,
                         default=4.0, min_value=0.01, unit="mm",
                         group="Profondeur"),
            ParameterDef("pitch", "Pas (descente par tour)",
                         ParameterType.FLOAT, default=0.5, min_value=0.01,
                         unit="mm", group="Profondeur",
                         tooltip="pitch: la descente à chaque tour d'hélice"),
            ParameterDef("start_angle", "Angle départ", ParameterType.FLOAT,
                         default=0.0, min_value=0.0, max_value=360.0,
                         unit="°", group="Expert", expert_only=True),
            ParameterDef("use_pattern", "Pattern", ParameterType.BOOL,
                         default=False, group="Pattern",
                         expert_only=True),
            ParameterDef("pattern_type", "Type", ParameterType.CHOICE,
                         default="Rectangle",
                         choices=["Rectangle", "Circle", "Linear"],
                         group="Pattern",
                         expert_only=True),
            ParameterDef("x_count", "NbX", ParameterType.INT,
                         default=1, min_value=1, max_value=999,
                         group="Pattern",
                         expert_only=True),
            ParameterDef("y_count", "NbY", ParameterType.INT,
                         default=1, min_value=1, max_value=999,
                         group="Pattern",
                         expert_only=True),
            ParameterDef("delta_x", "PasX", ParameterType.FLOAT,
                         default=10.0, min_value=0.0, unit="mm",
                         group="Pattern",
                         expert_only=True),
            ParameterDef("delta_y", "PasY", ParameterType.FLOAT,
                         default=10.0, min_value=0.0, unit="mm",
                         group="Pattern",
                         expert_only=True),
            ParameterDef("circle_count", "Nombre", ParameterType.INT,
                         default=6, min_value=1, max_value=999,
                         group="Pattern",
                         expert_only=True),
            ParameterDef("circle_radius", "Rayon", ParameterType.FLOAT,
                         default=20.0, min_value=0.1, unit="mm",
                         group="Pattern",
                         expert_only=True),
            ParameterDef("circle_start_angle", "Angle départ", ParameterType.FLOAT,
                         default=0.0, min_value=0.0, max_value=360.0,
                         unit="°", group="Pattern",
                         expert_only=True),
            ParameterDef("linear_count", "Nombre", ParameterType.INT,
                         default=4, min_value=1, max_value=999,
                         group="Pattern",
                         expert_only=True),
            ParameterDef("linear_delta", "Pas", ParameterType.FLOAT,
                         default=10.0, min_value=0.0, unit="mm",
                         group="Pattern",
                         expert_only=True),
            ParameterDef("linear_angle", "Angle", ParameterType.FLOAT,
                         default=0.0, min_value=0.0, max_value=360.0,
                         unit="°", group="Pattern",
                         expert_only=True),
        ] + REPEAT_PARAMS

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        return ToolRequirement(
            tool_types=['Cyl2', 'Cyl3', 'Cyl6', 'Cyl8',
                        'Con1', 'Con2', 'Con3', 'Con20', 'Con30',
                        'Chamfer'],
            description="Fraise cylindrique, conique ou chanfrein"
        )

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        defaults = cls.get_default_params()
        p = {**defaults, **params}
        commande = ("HelixWithFullCircle" if p.get('full_circle', True)
                    else "Helix")
        direction = "CW" if p.get('direction') == "CW" else "CCW"
        scz = float(p.get('_stroke_cutting_z', 1) or 0)
        diametre = float(p['diameter'])
        fraise = float(p.get('_diametre_outil') or 0)
        cote = p.get('side', 'Inside')
        trajet = diametre
        lignes = []
        if fraise > 0 and cote in ("Inside", "Outside"):
            trajet = diametre - fraise if cote == "Inside" \
                else diametre + fraise
            if trajet <= 0.01:
                lignes.append(f"    # Hélice: fraise Ø{fraise:g} ≥ "
                              f"Ø{diametre:g}, centre outil sur Ø{diametre:g}")
                trajet = diametre
            else:
                lignes.append(f"    # Hélice Ø{diametre:g} {cote}, fraise "
                              f"Ø{fraise:g}: centre outil sur Ø{trajet:g}")
        pas = p.get('pitch', 0.5) or 0.5
        # une profondeur saisie par l'opérateur (variable) reste écrite
        # par son nom: deltaZ=profondeur + 1
        profondeur = p['depth']
        if hasattr(profondeur, 'name'):
            delta = f"{profondeur} + {scz:g}"
        else:
            delta = f"{float(profondeur) + scz:g}"
        # un mouvement depuis la position courante: d'abord le plan
        # d'approche lente, puis l'hélice jusqu'à Pz
        lignes.append(f"    Rapid Z={scz:g}")
        lignes.append(
            f"    {commande} (diameter={trajet:g} "
            f"deltaZ={delta} pitch={pas} "
            f"startAngle={float(p.get('start_angle', 0) or 0):g} "
            f"{direction})")
        return "\n".join(lignes)
