"""Opération: Préchauffage broche.

Deux modes:

1. `SpindleWarmup` — routine intégrée de la machine. Elle fonctionne,
   mais l'argument `forceExecution` n'a AUCUN effet constaté (essais
   atelier true/false identiques) et n'apparaît dans aucun fichier de
   la documentation Datron — seulement en commentaire dans un
   programme d'exemple. Il n'est donc plus émis par défaut.

2. Rampe explicite — la méthode DOCUMENTÉE par Datron (programme
   de chauffe de la broche): montée en régime par paliers,
   chaque palier tournant puis à l'arrêt pendant une durée donnée.
   À utiliser quand on veut un préchauffage dont le déroulé est
   maîtrisé et visible dans le programme.
"""

from typing import List, Dict, Any
from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement
)
from src.operations.registry import OperationRegistry

MODE_MACHINE = "SpindleWarmup (machine)"
MODE_RAMPE = "Rampe explicite (Datron)"


@OperationRegistry.register("prechauffage_broche")
class PrechauffageBroche(AbstractOperation):
    DISPLAY_NAME = "Préchauffage broche"
    CATEGORY = "Utilitaire"
    HORS_MATIERE = True
    DESCRIPTION = "Préchauffage de la broche (routine machine ou rampe)"
    ICON = "warmup"
    INLINE = True
    REQUIRES_TOOL = False
    REQUIRES_COORDINATES = False
    SUPPORTS_MULTI_POINT = False

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return [
            ParameterDef("mode", "Mode", ParameterType.CHOICE,
                         default=MODE_MACHINE,
                         choices=[MODE_MACHINE, MODE_RAMPE],
                         group="Options", expert_only=True,
                         tooltip="SpindleWarmup: routine intégrée de la "
                                 "machine.\nRampe explicite: montée en "
                                 "régime par paliers, méthode "
                                 "documentée par Datron."),
            ParameterDef("rpm_start", "Rpm départ", ParameterType.INT,
                         default=4000, min_value=1000, max_value=60000,
                         unit="tr/min", group="Rampe",
                         expert_only=True,
                         tooltip="Régime du premier palier"),
            ParameterDef("rpm_end", "Rpm final", ParameterType.INT,
                         default=24000, min_value=1000, max_value=60000,
                         unit="tr/min", group="Rampe",
                         expert_only=True,
                         tooltip="Régime du dernier palier"),
            ParameterDef("steps", "Paliers", ParameterType.INT,
                         default=7, min_value=1, max_value=20,
                         group="Rampe", expert_only=True,
                         tooltip="Nombre de paliers entre Rpm départ "
                                 "et Rpm final"),
            ParameterDef("minutes", "Minutes/palier",
                         ParameterType.INT, default=3,
                         min_value=1, max_value=60, unit="min",
                         group="Rampe", expert_only=True,
                         tooltip="Durée de rotation puis d'arrêt à "
                                 "chaque palier"),
            ParameterDef("force_execution", "Émettre forceExecution",
                         ParameterType.BOOL, default=False,
                         group="Options", expert_only=True,
                         tooltip="Ajoute forceExecution=true à "
                                 "SpindleWarmup. SANS EFFET constaté "
                                 "sur la machine — laissé pour "
                                 "compatibilité."),
        ]

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        return ToolRequirement(tool_types=[], description="")

    @classmethod
    def _ramp_rpms(cls, p: Dict[str, Any]) -> List[int]:
        """Régimes des paliers, du départ au final (inclus)."""
        start = int(p.get('rpm_start', 4000) or 4000)
        end = int(p.get('rpm_end', 24000) or 24000)
        steps = max(1, int(p.get('steps', 7) or 1))
        if steps == 1:
            return [end]
        delta = (end - start) / (steps - 1)
        return [int(round(start + delta * i)) for i in range(steps)]

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        """Génère le préchauffage inline dans Main."""
        defaults = cls.get_default_params()
        p = {**defaults, **params}
        if p.get('mode', MODE_MACHINE) != MODE_RAMPE:
            if p.get('force_execution', False):
                return "    SpindleWarmup forceExecution=true"
            return "    SpindleWarmup"

        minutes = max(1, int(p.get('minutes', 3) or 3))
        rpms = cls._ramp_rpms(p)
        total = len(rpms) * minutes * 2
        lines = [
            f"    # Préchauffage broche: {len(rpms)} paliers "
            f"de {rpms[0]} à {rpms[-1]} tr/min",
            f"    # Durée totale ≈ {total} min",
        ]
        for rpm in rpms:
            lines.append(f"    Rpm={rpm}")
            lines.append("    Spindle mode=Activation.On")
            lines.append(f"    Sleep minutes={minutes}")
            lines.append("    Spindle mode=Activation.Off")
            lines.append(f"    Sleep minutes={minutes}")
        return "\n".join(lines)
