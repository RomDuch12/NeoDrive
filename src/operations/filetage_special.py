"""Opérations: Filetage spécial (SpecialThread) et Taraudage rigide
(ThreadCutting), les deux cycles de filets du manuel SimPL 3.1.1 que le
Taraudage (Thread, M2.5 à M10 métriques) n'écrit pas.

§ 5.2.1.4 « Special thread » (p. 174): fraisage d'un filet intérieur ou
extérieur, de Ø, pas et angle de flanc libres:

    SpecialThread nominalDiameter=6 pitch=1 depth=10 strokeRapidZ=14
        strokeCuttingZ=1 deburring=ThreadMillingDeburring.NoDeburring
        insideOutside=ThreadMillingSide.Inside
        direction=ThreadMillingDirection.RightHandThread
        threadStandard=ThreadStandards.Metric threadAngle=60 finishing=1
        technology=ClimbMilling

§ 5.2.1.5 « Drilling thread » (p. 182, broche 8 kW seulement): un
taraud, à vitesse et avance données, débourrage par passes:

    ThreadCutting pitch=2 depth=6 strokeRapidZ=18 strokeCuttingZ=2
        threadRpm=300 threadFeed=300 breakChipInfeed=2
        direction=ThreadMillingDirection.RightHandThread

Un facultatif à vide n'est pas écrit (le défaut du manuel s'applique).
"""

from typing import Any, Dict, List

from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement,
    REPEAT_PARAMS, GROUP_PARAMS
)
from src.operations.registry import OperationRegistry
from src.operations.taraudage import THREAD_TYPES

_SENS = ["RightHandThread", "LeftHandThread"]


def _nombre(v) -> str:
    try:
        return f"{float(v):g}"
    except (TypeError, ValueError):
        return ""


@OperationRegistry.register("filetage_special")
class FiletageSpecial(AbstractOperation):
    DISPLAY_NAME = "Filetage spécial"
    CATEGORY = "Taraudage"
    DESCRIPTION = ("Filet fraisé intérieur ou extérieur, Ø, pas et angle "
                   "libres (SpecialThread)")
    ICON = "thread"
    SUPPORTS_MULTI_POINT = True
    # nouvelle (manuel SimPL, octobre 2026): en expert par défaut
    EXPERT_ONLY = True

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return [
            ParameterDef("nominal_diameter", "Ø nominal", ParameterType.FLOAT,
                         default=6.0, min_value=0.5, max_value=200.0,
                         unit="mm", group="Filet",
                         tooltip="Diamètre extérieur du filet "
                                 "(nominalDiameter)"),
            ParameterDef("pitch", "Pas", ParameterType.FLOAT, default=1.0,
                         min_value=0.05, max_value=20.0, unit="mm",
                         group="Filet", tooltip="pitch"),
            ParameterDef("depth", "Pz", ParameterType.FLOAT, default=10.0,
                         min_value=0.1, unit="mm", group="Profondeur",
                         tooltip="Profondeur du filet (depth)"),
            ParameterDef("inside_outside", "Côté", ParameterType.CHOICE,
                         default="Inside", choices=["Inside", "Outside"],
                         group="Filet",
                         tooltip="Inside: taraudage; Outside: filet "
                                 "extérieur (insideOutside)"),
            ParameterDef("direction", "Direction", ParameterType.CHOICE,
                         default="RightHandThread", choices=_SENS,
                         group="Filet"),
            ParameterDef("thread_angle", "Angle de flanc", ParameterType.STRING,
                         default="", unit="°", group="Filet",
                         expert_only=True,
                         tooltip="threadAngle (vide: celui de la norme, 60° "
                                 "en métrique)"),
            ParameterDef("deburring", "Ébavurage", ParameterType.BOOL,
                         default=False, group="Finition",
                         tooltip="deburring=ThreadMillingDeburring.Deburring"),
            ParameterDef("finishing", "Finition XY", ParameterType.STRING,
                         default="", unit="mm", group="Finition",
                         expert_only=True,
                         tooltip="Largeur de finition (finishing; vide: "
                                 "défaut du manuel)"),
            ParameterDef("technology", "Technologie", ParameterType.CHOICE,
                         default="ConventionalMilling",
                         choices=["ConventionalMilling", "ClimbMilling"],
                         group="Finition", expert_only=True,
                         tooltip="Sens d'usinage (technology): la fraise "
                                 "à fileter fait mieux en opposition "
                                 "(ConventionalMilling, défaut)"),
        ] + REPEAT_PARAMS + GROUP_PARAMS

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        return ToolRequirement(tool_types=THREAD_TYPES,
                               description="Fraise à fileter")

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        p = {**cls.get_default_params(), **(params or {})}
        srz = p.get('_stroke_rapid_z', 15)
        scz = p.get('_stroke_cutting_z', 1)
        cote = "Outside" if p.get('inside_outside') == "Outside" \
            else "Inside"
        sens = p['direction'] if p.get('direction') in _SENS \
            else "RightHandThread"
        morceaux = [
            f"nominalDiameter={_nombre(p['nominal_diameter'])}",
            f"pitch={_nombre(p['pitch'])}",
            f"depth={_nombre(p['depth'])}",
            f"strokeRapidZ={srz} strokeCuttingZ={scz}",
            "deburring=ThreadMillingDeburring."
            + ("Deburring" if p.get('deburring') else "NoDeburring"),
            f"insideOutside=ThreadMillingSide.{cote}",
            f"direction=ThreadMillingDirection.{sens}",
            "threadStandard=ThreadStandards.Metric",
        ]
        for cle, nom in (('thread_angle', 'threadAngle'),
                         ('finishing', 'finishing')):
            v = _nombre(p.get(cle))
            if str(p.get(cle, '')).strip() and v:
                morceaux.append(f"{nom}={v}")
        if p.get('technology') == "ClimbMilling":
            morceaux.append("technology=ClimbMilling")
        return "    SpecialThread (" + " ".join(morceaux) + ")"


@OperationRegistry.register("taraudage_rigide")
class TaraudageRigide(AbstractOperation):
    DISPLAY_NAME = "Taraudage rigide"
    CATEGORY = "Taraudage"
    DESCRIPTION = ("Taraud à vitesse et avance imposées, broche 8 kW "
                   "seulement (ThreadCutting)")
    ICON = "thread"
    SUPPORTS_MULTI_POINT = True
    EXPERT_ONLY = True

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return [
            ParameterDef("pitch", "Pas", ParameterType.FLOAT, default=1.0,
                         min_value=0.05, max_value=20.0, unit="mm",
                         group="Filet", tooltip="Pas du taraud (pitch)"),
            ParameterDef("depth", "Pz", ParameterType.FLOAT, default=6.0,
                         min_value=0.1, unit="mm", group="Profondeur"),
            ParameterDef("thread_rpm", "Vitesse", ParameterType.INT,
                         default=300, min_value=10, max_value=10000,
                         unit="tr/min", group="Filet",
                         tooltip="Vitesse de broche du taraudage "
                                 "(threadRpm)"),
            ParameterDef("thread_feed", "Avance", ParameterType.FLOAT,
                         default=300.0, min_value=1.0, max_value=20000.0,
                         unit="mm/min", group="Filet",
                         tooltip="threadFeed (pas × vitesse pour un "
                                 "taraud: 1 mm × 300 tr/min = 300)"),
            ParameterDef("break_chip_infeed", "Débourrage",
                         ParameterType.FLOAT, default=0.0, min_value=0.0,
                         unit="mm", group="Profondeur",
                         tooltip="Prise maximale par passe pour casser le "
                                 "copeau (breakChipInfeed; 0: d'un coup)"),
            ParameterDef("direction", "Direction", ParameterType.CHOICE,
                         default="RightHandThread", choices=_SENS,
                         group="Filet"),
        ] + REPEAT_PARAMS + GROUP_PARAMS

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        return ToolRequirement(tool_types=[], description="Taraud")

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        p = {**cls.get_default_params(), **(params or {})}
        srz = p.get('_stroke_rapid_z', 15)
        scz = p.get('_stroke_cutting_z', 1)
        sens = p['direction'] if p.get('direction') in _SENS \
            else "RightHandThread"
        morceaux = [
            f"pitch={_nombre(p['pitch'])}",
            f"depth={_nombre(p['depth'])}",
            f"strokeRapidZ={srz} strokeCuttingZ={scz}",
            f"threadRpm={int(float(p['thread_rpm']))}",
            f"threadFeed={_nombre(p['thread_feed'])}",
        ]
        debourrage = float(p.get('break_chip_infeed') or 0)
        if debourrage > 0:
            morceaux.append(f"breakChipInfeed={_nombre(debourrage)}")
        morceaux.append(f"direction=ThreadMillingDirection.{sens}")
        return "    ThreadCutting (" + " ".join(morceaux) + ")"
