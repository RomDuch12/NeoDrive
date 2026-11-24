"""
Opération BPM (Bore Pattern Machine) — Programme combiné DATRON.
4 modes:
  0. Perçage simple (Drill)
  1. Lamage + Perçage (DrillMilling × 2 outils)
  2. Perçage Fraise + Taraudage (DrillMilling + Thread)
  3. Perçage Foret + Taraudage (Drill + Thread)

Génère un programme complet autonome (INLINE = False) avec un ou deux outils.
Supporte l'entraxe pour calculer automatiquement 2 centres symétriques.
"""

from typing import List, Dict, Any
from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement,
    REPEAT_PARAMS
)
from src.operations.registry import OperationRegistry


def _mm(valeur) -> str:
    """Une cote en mm pour le code: au millième, sans zéros inutiles
    mais avec au moins une décimale (« 3.0 », « 4.05 »). Le « :.1f »
    d'avant arrondissait au dixième: un perçage Ø4,05 sortait en
    Ø4,0 et une profondeur 3,25 en 3,2."""
    try:
        v = float(valeur)
    except (TypeError, ValueError):
        v = 0.0
    texte = f"{v:.3f}".rstrip('0')
    if texte in ('-0.', '-0'):
        texte = '0.'
    return texte + '0' if texte.endswith('.') else texte


# Champs actifs par mode BPM
BPM_MODE_FIELDS = {
    "Perçage Simple": {
        "depth", "infeed_z",
        "steel_rpm", "steel_approach", "steel_finishing",
        "steel_plunge", "steel_ramp", "steel_roughing"},
    "Lamage + Perçage": {
        "depth", "infeed_z", "diameter", "finishing_xy", "finishing_z",
        "cbore_depth", "cbore_diameter"},
    "Fraise + Taraudage": {
        "depth", "diameter", "finishing_xy", "finishing_z",
        "tap_depth", "thread_name"},
    "Foret + Taraudage": {
        "depth", "infeed_z", "tap_depth", "thread_name",
        "steel_rpm", "steel_approach", "steel_finishing",
        "steel_plunge", "steel_ramp", "steel_roughing"},
}

# Outil par défaut par mode (article number)
BPM_DEFAULT_TOOLS = {
    "Perçage Simple": "0068240L",
    "Lamage + Perçage": None,        # au choix de l'utilisateur
    "Fraise + Taraudage": None,      # Cyl auto
    "Foret + Taraudage": "0068233",
}


@OperationRegistry.register("bpm")
class BPMOperation(AbstractOperation):
    OP_TYPE = "bpm"
    DISPLAY_NAME = "BPM"
    CATEGORY = "Perçage"
    ICON = "bpm"
    DESCRIPTION = (
        "Programme combiné: perçage simple, lamage+perçage, "
        "perçage+taraudage. Supporte 2 outils distincts.")
    INLINE = False
    REQUIRES_TOOL = True
    REQUIRES_COORDINATES = True
    SUPPORTS_MULTI_POINT = True

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return [
            # ── Mode BPM ──
            ParameterDef(
                "bpm_mode", "Mode BPM", ParameterType.CHOICE,
                default="Perçage Simple",
                choices=[
                    "Perçage Simple",
                    "Lamage + Perçage",
                    "Fraise + Taraudage",
                    "Foret + Taraudage",
                ],
                group="Type",
                tooltip="Type de programme BPM"),

            # ── Entraxe (toujours visible, pas de checkbox) ──
            ParameterDef(
                "entraxe", "Entraxe", ParameterType.FLOAT,
                default=20.0, min_value=0.1, max_value=500.0,
                unit="mm", group="Entraxe",
                tooltip="Distance entre les 2 centres"),
            ParameterDef(
                "entraxe_axis", "Axe", ParameterType.CHOICE,
                default="X",
                choices=["X", "Y"],
                group="Entraxe",
                tooltip="Axe sur lequel répartir les 2 centres"),

            # ── Profondeur ──
            ParameterDef(
                "depth", "Pz", ParameterType.FLOAT,
                default=10.0, min_value=0.01, max_value=50.0,
                unit="mm", group="Profondeur"),
            ParameterDef(
                "infeed_z", "Passe Z", ParameterType.FLOAT,
                default=2.0, min_value=0.1, max_value=10.0,
                unit="mm", group="Profondeur"),

            # ── Dimensions ──
            ParameterDef(
                "diameter", "Ø", ParameterType.FLOAT,
                default=4.0, min_value=0.1, max_value=50.0,
                unit="mm", group="Dimensions"),

            # ── Finition ──
            ParameterDef(
                "finishing_xy", "Finition XY", ParameterType.FLOAT,
                default=0.15, min_value=0.0, max_value=2.0,
                unit="mm", group="Finition"),
            ParameterDef(
                "finishing_z", "Finition Z", ParameterType.FLOAT,
                default=0.1, min_value=0.0, max_value=2.0,
                unit="mm", group="Finition"),

            # ── Taraudage (si mode 2 ou 3) ──
            ParameterDef(
                "tap_depth", "Pz Taraudage", ParameterType.FLOAT,
                default=10.0, min_value=0.01, max_value=50.0,
                unit="mm", group="Taraudage"),
            ParameterDef(
                "thread_name", "Filetage", ParameterType.CHOICE,
                default="M4",
                choices=["M2.5", "M3", "M4", "M5", "M6", "M8", "M10"],
                group="Taraudage"),

            # ── Lamage (si mode 1) ──
            ParameterDef(
                "cbore_depth", "Pz Lamage", ParameterType.FLOAT,
                default=4.4, min_value=0.01, max_value=50.0,
                unit="mm", group="Lamage",
                tooltip="Profondeur du lamage"),
            ParameterDef(
                "cbore_diameter", "Ø Lamage", ParameterType.FLOAT,
                default=8.0, min_value=0.1, max_value=50.0,
                unit="mm", group="Lamage"),

            # ── Paramètres Acier (Perçage Simple + Foret+Taraudage) ──
            ParameterDef(
                "steel_rpm", "Rpm", ParameterType.INT,
                default=15000, min_value=100, max_value=60000,
                group="Acier"),
            ParameterDef(
                "steel_approach", "Approach", ParameterType.INT,
                default=300, min_value=1, max_value=10000,
                group="Acier"),
            ParameterDef(
                "steel_finishing", "Finishing", ParameterType.INT,
                default=400, min_value=1, max_value=10000,
                group="Acier"),
            ParameterDef(
                "steel_plunge", "Plunge", ParameterType.INT,
                default=120, min_value=1, max_value=10000,
                group="Acier"),
            ParameterDef(
                "steel_ramp", "Ramp", ParameterType.INT,
                default=150, min_value=1, max_value=10000,
                group="Acier"),
            ParameterDef(
                "steel_roughing", "Roughing", ParameterType.INT,
                default=80, min_value=1, max_value=10000,
                group="Acier"),

            # ── Pattern support ──
            ParameterDef(
                "use_pattern", "Pattern", ParameterType.BOOL,
                default=False, group="Pattern",
                         expert_only=True),
            ParameterDef(
                "x_count", "NbX", ParameterType.INT,
                default=1, min_value=1, max_value=999,
                group="Pattern",
                         expert_only=True),
            ParameterDef(
                "y_count", "NbY", ParameterType.INT,
                default=1, min_value=1, max_value=999,
                group="Pattern",
                         expert_only=True),
            ParameterDef(
                "delta_x", "PasX", ParameterType.FLOAT,
                default=10.0, min_value=0.0, unit="mm",
                group="Pattern",
                         expert_only=True),
            ParameterDef(
                "delta_y", "PasY", ParameterType.FLOAT,
                default=10.0, min_value=0.0, unit="mm",
                group="Pattern",
                         expert_only=True),
        ] + REPEAT_PARAMS

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        return ToolRequirement(
            tool_types=['Drill', 'Cyl2', 'Cyl3', 'Cyl6', 'Cyl8',
                        'M3', 'M4', 'M5', 'M6', 'M8'],
            description="Foret, Fraise cylindrique ou Taraud"
        )

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        """Génère le code SimPl pour l'opération BPM."""
        p = {**cls.get_default_params(), **params}
        srz = p.get('_stroke_rapid_z', 15)
        scz = p.get('_stroke_cutting_z', 1)
        mode = p.get('bpm_mode', 'Perçage Simple')

        depth = float(p.get('depth', 10.0))
        infeed_z = float(p.get('infeed_z', 2.0))
        diameter = float(p.get('diameter', 4.0))
        finishing_xy = float(p.get('finishing_xy', 0.15))
        finishing_z = float(p.get('finishing_z', 0.1))

        if mode == "Perçage Simple":
            # Drill command with steel feed params
            lines = []
            lines.append(
                f"    Drill depth={_mm(depth)} "
                f"infeedZ={_mm(infeed_z)} "
                f"strokeRapidZ={srz} strokeCuttingZ={scz}")
            return "\n".join(lines)

        elif mode == "Lamage + Perçage":
            cbore_depth = float(p.get('cbore_depth', 4.3))
            cbore_diameter = float(p.get('cbore_diameter', 7.1))
            lines = []
            lines.append(
                f"    # Lamage Ø{_mm(cbore_diameter)} Pz{_mm(cbore_depth)}")
            lines.append(
                f"    DrillMilling diameter={_mm(cbore_diameter)} "
                f"depth={_mm(cbore_depth)} infeedZ=0.50 "
                f"strokeRapidZ={srz} strokeCuttingZ={scz} "
                f"finishingXY={_mm(finishing_xy)} "
                f"finishingZ={_mm(finishing_z)} "
                f"infeedFinishingZ=0.5")
            lines.append(
                f"    # Perçage Ø{_mm(diameter)} Pz{_mm(depth)}")
            lines.append(
                f"    DrillMilling diameter={_mm(diameter)} "
                f"depth={_mm(depth)} infeedZ=0.50 "
                f"strokeRapidZ={srz} strokeCuttingZ={scz} "
                f"finishingXY={_mm(finishing_xy)} "
                f"finishingZ={_mm(finishing_z)} "
                f"infeedFinishingZ=0.5")
            return "\n".join(lines)

        elif mode == "Fraise + Taraudage":
            tap_depth = float(p.get('tap_depth', 10.0))
            thread = p.get('thread_name', 'M4')
            tool2_article = p.get('_tool2_article', '')
            tool2_name = p.get('_tool2_name', '')
            tool2_rpm = int(p.get('_tool2_rpm', 0))
            tool2_feeds = p.get('_tool2_feeds', '')
            lines = []
            lines.append(
                f"    # Perçage Fraise Ø{_mm(diameter)} Pz{_mm(depth)}")
            lines.append(
                f"    DrillMilling diameter={_mm(diameter)} "
                f"depth={_mm(depth)} infeedZ=0.50 "
                f"strokeRapidZ={srz} strokeCuttingZ={scz} "
                f"finishingXY={_mm(finishing_xy)} "
                f"finishingZ={_mm(finishing_z)} "
                f"infeedFinishingZ=0.5")
            # Changement d'outil pour taraudage
            if tool2_article:
                lines.append(f'    Tool type="{tool2_article}"  skipRestoring    #{tool2_name}')
                if tool2_rpm:
                    lines.append(f"    Rpm = {tool2_rpm}")
                lines.append("    Spindle On")
                if tool2_feeds:
                    lines.append(f"    SetFeedTechnology ({tool2_feeds})")
            lines.append(
                f"    # Taraudage {thread} Pz{_mm(tap_depth)}")
            lines.append(
                f"    Thread (Metric threadName=\"{thread}\" "
                f"depth={_mm(tap_depth)} Inside RightHandThread "
                f"ConventionalMilling strokeRapidZ={srz} "
                f"strokeCuttingZ={scz} finishing=0.1)")
            return "\n".join(lines)

        elif mode == "Foret + Taraudage":
            tap_depth = float(p.get('tap_depth', 10.0))
            thread = p.get('thread_name', 'M4')
            tool2_article = p.get('_tool2_article', '')
            tool2_name = p.get('_tool2_name', '')
            tool2_rpm = int(p.get('_tool2_rpm', 0))
            tool2_feeds = p.get('_tool2_feeds', '')
            lines = []
            lines.append(
                f"    # Perçage Foret Pz{_mm(depth)}")
            lines.append(
                f"    Drill depth={_mm(depth)} "
                f"infeedZ={_mm(infeed_z)} "
                f"strokeRapidZ={srz} strokeCuttingZ={scz}")
            # Changement d'outil pour taraudage
            if tool2_article:
                lines.append(f'    Tool type="{tool2_article}"  skipRestoring    #{tool2_name}')
                if tool2_rpm:
                    lines.append(f"    Rpm = {tool2_rpm}")
                lines.append("    Spindle On")
                if tool2_feeds:
                    lines.append(f"    SetFeedTechnology ({tool2_feeds})")
            lines.append(
                f"    # Taraudage {thread} Pz{_mm(tap_depth)}")
            lines.append(
                f"    Thread (Metric threadName=\"{thread}\" "
                f"depth={_mm(tap_depth)} Inside RightHandThread "
                f"ConventionalMilling strokeRapidZ={srz} "
                f"strokeCuttingZ={scz} finishing=0.1)")
            return "\n".join(lines)

        # Fallback
        return f"    # BPM mode inconnu: {mode}"

    @classmethod
    def is_dual_tool(cls, params: Dict[str, Any]) -> bool:
        """Retourne True si le mode BPM utilise 2 outils."""
        mode = params.get('bpm_mode', 'Perçage Simple')
        return mode in ("Fraise + Taraudage", "Foret + Taraudage")

    @classmethod
    def generate_tool1_code(cls, params: Dict[str, Any]) -> str:
        """Génère uniquement la partie Outil 1 (perçage/fraisage)."""
        p = {**cls.get_default_params(), **params}
        srz = p.get('_stroke_rapid_z', 15)
        scz = p.get('_stroke_cutting_z', 1)
        mode = p.get('bpm_mode', 'Perçage Simple')
        depth = float(p.get('depth', 10.0))
        infeed_z = float(p.get('infeed_z', 2.0))
        diameter = float(p.get('diameter', 4.0))
        finishing_xy = float(p.get('finishing_xy', 0.15))
        finishing_z = float(p.get('finishing_z', 0.1))

        if mode == "Fraise + Taraudage":
            lines = []
            lines.append(
                f"    # Perçage Fraise Ø{_mm(diameter)} Pz{_mm(depth)}")
            lines.append(
                f"    DrillMilling diameter={_mm(diameter)} "
                f"depth={_mm(depth)} infeedZ=0.50 "
                f"strokeRapidZ={srz} strokeCuttingZ={scz} "
                f"finishingXY={_mm(finishing_xy)} "
                f"finishingZ={_mm(finishing_z)} "
                f"infeedFinishingZ=0.5")
            return "\n".join(lines)
        elif mode == "Foret + Taraudage":
            lines = []
            lines.append(
                f"    # Perçage Foret Pz{_mm(depth)}")
            lines.append(
                f"    Drill depth={_mm(depth)} "
                f"infeedZ={_mm(infeed_z)} "
                f"strokeRapidZ={srz} strokeCuttingZ={scz}")
            return "\n".join(lines)
        # Non dual-tool: fallback complet
        return cls.generate_operation_code(params)

    @classmethod
    def generate_tool2_code(cls, params: Dict[str, Any]) -> str:
        """Génère uniquement la partie Outil 2 (taraudage)."""
        p = {**cls.get_default_params(), **params}
        srz = p.get('_stroke_rapid_z', 15)
        scz = p.get('_stroke_cutting_z', 1)
        tap_depth = float(p.get('tap_depth', 10.0))
        thread = p.get('thread_name', 'M4')
        lines = []
        lines.append(
            f"    # Taraudage {thread} Pz{_mm(tap_depth)}")
        lines.append(
            f"    Thread (Metric threadName=\"{thread}\" "
            f"depth={_mm(tap_depth)} Inside RightHandThread "
            f"ConventionalMilling strokeRapidZ={srz} "
            f"strokeCuttingZ={scz} finishing=0.1)")
        return "\n".join(lines)

    @classmethod
    def generate_tool2_header(cls, params: Dict[str, Any]) -> str:
        """Génère les lignes de changement d'outil 2 (Tool, Rpm, Spindle, SetFeedTechnology)."""
        p = {**cls.get_default_params(), **params}
        tool2_article = p.get('_tool2_article', '')
        tool2_name = p.get('_tool2_name', '')
        tool2_rpm = int(p.get('_tool2_rpm', 0))
        tool2_feeds = p.get('_tool2_feeds', '')
        lines = []
        if tool2_article:
            lines.append(
                f'    Tool type="{tool2_article}"  skipRestoring'
                f"    #{tool2_name}")
            if tool2_rpm:
                lines.append(f"    Rpm = {tool2_rpm}")
            lines.append("    Spindle On")
            if tool2_feeds:
                lines.append(f"    SetFeedTechnology ({tool2_feeds})")
        return "\n".join(lines)
