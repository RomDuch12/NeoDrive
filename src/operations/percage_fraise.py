"""Opération: Perçage par fraisage (DrillMilling)"""

from typing import List, Dict, Any
from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement,
    REPEAT_PARAMS, GROUP_PARAMS
)
from src.operations.registry import OperationRegistry


@OperationRegistry.register("percage_fraise")
class PercageFraise(AbstractOperation):
    DISPLAY_NAME = "Perçage Fraise"
    CATEGORY = "Perçage"
    DESCRIPTION = "Perçage hélicoïdal par fraisage"
    ICON = "drill_mill"
    SUPPORTS_MULTI_POINT = True

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return [
            ParameterDef("diameter", "Diamètre", ParameterType.FLOAT,
                         default=4.05, min_value=0.1, unit="mm",
                         group="Dimensions"),
            ParameterDef("depth", "Pz", ParameterType.FLOAT,
                         default=4.0, min_value=0.01, unit="mm",
                         group="Profondeur"),
            ParameterDef("infeed_z", "Passe Z", ParameterType.FLOAT,
                         default=0.5, min_value=0.01, unit="mm",
                         group="Profondeur"),
            ParameterDef("finishing_xy", "Finition XY", ParameterType.FLOAT,
                         default=0.1, min_value=0.0, unit="mm",
                         group="Finition"),
            ParameterDef("finishing_z", "Finition Z", ParameterType.FLOAT,
                         default=0.1, min_value=0.0, unit="mm",
                         group="Finition"),
            ParameterDef("infeed_finishing_z", "Passe Z finition",
                         ParameterType.FLOAT, default=1.0, min_value=0.0,
                         unit="mm", group="Finition"),
            # ── Fraisage de la tête de vis ──
            ParameterDef("head_milling", "Fraisage pour tête de vis",
                         ParameterType.BOOL, default=False, unit="",
                         group="Tête de vis",
                         tooltip="Deuxième DrillMilling au MÊME point, "
                                 "plus large et peu profond, pour "
                                 "noyer la tête. "
                                 "Suit le tableau de "
                                 "perçages: un point ajouté est fraisé "
                                 "lui aussi."),
            ParameterDef("head_surface_z", "Z de la surface à fraiser",
                         ParameterType.FLOAT, default=0.0,
                         min_value=-200.0, max_value=200.0, unit="mm",
                         group="Tête de vis",
                         tooltip="Hauteur de la face où débouche la "
                                 "tête, par rapport à l'origine "
                                 "programme. 0 = dessus du brut; une "
                                 "surface plus basse creuse d'autant."),
            ParameterDef("head_tool_id", "Outil de fraisage",
                         ParameterType.STRING, default="", unit="",
                         group="Tête de vis",
                         tooltip="Outil du fraisage de tête (souvent "
                                 "un chanfreineur). Vide = outil de "
                                 "l'opération."),
            ParameterDef("head_diameter", "Ø de fraisage",
                         ParameterType.FLOAT, default=9.05,
                         min_value=0.1, max_value=200.0, unit="mm",
                         group="Tête de vis expert", expert_only=True),
            ParameterDef("head_depth", "Profondeur de tête",
                         ParameterType.FLOAT, default=2.85,
                         min_value=0.01, max_value=200.0, unit="mm",
                         group="Tête de vis expert", expert_only=True),
            ParameterDef("head_infeed_z", "Passe Z de tête",
                         ParameterType.FLOAT, default=0.25,
                         min_value=0.01, max_value=50.0, unit="mm",
                         group="Tête de vis expert", expert_only=True),
            ParameterDef("head_stroke_rapid_z", "strokeRapidZ tête",
                         ParameterType.FLOAT, default=4.0,
                         min_value=0.0, max_value=200.0, unit="mm",
                         group="Tête de vis expert", expert_only=True),
            ParameterDef("head_stroke_cutting_z", "strokeCuttingZ tête",
                         ParameterType.FLOAT, default=1.0,
                         min_value=0.0, max_value=200.0, unit="mm",
                         group="Tête de vis expert", expert_only=True),
            ParameterDef("head_finishing_xy", "Finition XY tête",
                         ParameterType.FLOAT, default=0.0,
                         min_value=0.0, max_value=10.0, unit="mm",
                         group="Tête de vis expert", expert_only=True),
            ParameterDef("head_finishing_z", "Finition Z tête",
                         ParameterType.FLOAT, default=0.0,
                         min_value=0.0, max_value=10.0, unit="mm",
                         group="Tête de vis expert", expert_only=True),
            ParameterDef("head_infeed_finishing_z",
                         "Passe Z finition tête", ParameterType.FLOAT,
                         default=0.0, min_value=0.0, max_value=50.0,
                         unit="mm", group="Tête de vis expert",
                         expert_only=True),
            ParameterDef("head_safe_rapid_z", "Z du SafeRapid tête",
                         ParameterType.FLOAT, default=5.0,
                         min_value=0.0, max_value=200.0, unit="mm",
                         group="Tête de vis expert", expert_only=True),

            ParameterDef("use_ebav", "Ébavurage", ParameterType.BOOL,
                         default=False, group="Ébavurage"),
            ParameterDef("ebav_offset", "Offset ébav.", ParameterType.FLOAT,
                         default=0.05, min_value=0.0, max_value=1.0,
                         unit="mm", group="Ébavurage", expert_only=True),
            ParameterDef("ebav_profondeur", "Profondeur ébav. (Drill)",
                         ParameterType.FLOAT, default=0.0, min_value=0.0,
                         max_value=50.0, unit="mm", group="Ébavurage",
                         tooltip="Profondeur du Drill d'ébavurage. 0 = "
                                 "automatique (la moitié du Ø + l'offset)."),
        ] + REPEAT_PARAMS + GROUP_PARAMS

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        return ToolRequirement(
            tool_types=['Cyl2', 'Cyl3', 'Cyl6', 'Cyl8'],
            description="Fraise cylindrique"
        )

    @classmethod
    def head_depth(cls, params: Dict[str, Any]) -> float:
        """Profondeur du fraisage de tête, surface comprise.

        `head_depth` se compte depuis la SURFACE à fraiser. Si cette
        surface est plus basse que l'origine programme, l'outil doit
        d'abord descendre jusqu'à elle: c'est le sens du signe.

        Plus HAUTE, la profondeur reste `head_depth`: le générateur
        monte le repère jusqu'à la face (ShiftWcsInc Z=+s … Z=-s). Sans
        cela, la profondeur devenait petite ou négative, et le
        SafeRapid passait sous la face."""
        p = {**cls.get_default_params(), **params}

        def _f(cle, defaut=0.0):
            try:
                return float(p.get(cle, defaut) or 0.0)
            except (TypeError, ValueError):
                return float(defaut)

        return round(_f('head_depth', 2.85)
                     - min(_f('head_surface_z'), 0.0), 4)

    @classmethod
    def head_surface_haute(cls, params: Dict[str, Any]) -> float:
        """La hauteur de la face à fraiser quand elle est AU-DESSUS de
        l'origine programme (0 sinon): le décalage du repère."""
        try:
            s = float(params.get('head_surface_z', 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0
        return s if s > 0 else 0.0

    @classmethod
    def generate_head_code(cls, params: Dict[str, Any]) -> str:
        """Ligne DrillMilling du fraisage de tête."""
        p = {**cls.get_default_params(), **params}

        def _f(cle, defaut=0.0):
            try:
                return float(p.get(cle, defaut) or 0.0)
            except (TypeError, ValueError):
                return float(defaut)

        return (f"    DrillMilling (diameter={_f('head_diameter', 9.05):g} "
                f"depth={cls.head_depth(p):g} "
                f"infeedZ={_f('head_infeed_z', 0.25):g} "
                f"strokeRapidZ={_f('head_stroke_rapid_z', 4.0):g} "
                f"strokeCuttingZ={_f('head_stroke_cutting_z', 1.0):g} "
                f"finishingXY={_f('head_finishing_xy'):g} "
                f"finishingZ={_f('head_finishing_z'):g} "
                f"infeedFinishingZ={_f('head_infeed_finishing_z'):g})")

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        """Génère le code DrillMilling (sans Pattern — géré par le générateur)."""
        defaults = cls.get_default_params()
        p = {**defaults, **params}
        srz = p.get('_stroke_rapid_z', 15)
        scz = p.get('_stroke_cutting_z', 1)
        code = (
            f"    DrillMilling (diameter={p['diameter']} "
            f"depth={p['depth']} infeedZ={p['infeed_z']} "
            f"strokeRapidZ={srz} strokeCuttingZ={scz} "
            f"finishingXY={p['finishing_xy']} finishingZ={p['finishing_z']} "
            f"infeedFinishingZ={p['infeed_finishing_z']})"
        )
        return code
