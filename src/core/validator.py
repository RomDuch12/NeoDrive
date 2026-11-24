"""
Validation croisée des opérations du programme.
Détecte les problèmes potentiels avant la génération.
"""

from typing import List
from src.core.program_model import ProgramModel
from src.core.tool_library import ToolLibrary
from src.operations.registry import OperationRegistry


class ValidationMessage:
    """Un message de validation."""
    WARN = "warn"
    ERROR = "error"
    INFO = "info"

    def __init__(self, level: str, op_index: int, op_name: str, message: str):
        self.level = level
        self.op_index = op_index
        self.op_name = op_name
        self.message = message

    def __repr__(self):
        prefix = {"warn": "⚠", "error": "✗", "info": "ℹ"}.get(
            self.level, "?")
        return f"{prefix} [{self.op_name}] {self.message}"


def validate_program(program: ProgramModel,
                     tool_library: ToolLibrary) -> List[ValidationMessage]:
    """Exécute toutes les validations croisées.
    Retourne une liste de ValidationMessage triée par gravité."""
    messages = []

    for i, op in enumerate(program.operations):
        if not op.enabled:
            continue
        try:
            op_class = OperationRegistry.get(op.operation_type)
        except KeyError:
            messages.append(ValidationMessage(
                ValidationMessage.ERROR, i, op.name,
                f"Type d'opération inconnu: {op.operation_type}"))
            continue

        # 1. Outil requis mais non sélectionné
        if op_class.REQUIRES_TOOL and not op.tool_id:
            messages.append(ValidationMessage(
                ValidationMessage.ERROR, i, op.name,
                "Aucun outil sélectionné"))
            continue

        # 2. Outil référencé inexistant
        if op.tool_id and op.tool_id not in tool_library.tools:
            messages.append(ValidationMessage(
                ValidationMessage.ERROR, i, op.name,
                f"Outil introuvable: {op.tool_id}"))
            continue

        tool = tool_library.get_tool(op.tool_id) if op.tool_id else None

        # 3. Profondeur > capacité outil (params + profondeurs par point)
        if tool and tool.max_depth > 0:
            depths = []
            try:
                depths.append(float(op.params.get('depth', 0) or 0))
            except (TypeError, ValueError):
                pass
            for pt in op.points:
                pd = pt.get('depth')
                if pd is None:
                    continue
                try:
                    depths.append(float(pd))
                except (TypeError, ValueError):
                    pass
            depth = max(depths) if depths else 0.0
            if depth > tool.max_depth:
                messages.append(ValidationMessage(
                    ValidationMessage.WARN, i, op.name,
                    f"Profondeur {depth:.1f}mm > max outil "
                    f"{tool.max_depth:.1f}mm"))

        # 4. Ébavurage: outil ébav manquant
        if op.params.get('use_ebav', False):
            ebav_tool_id = op.params.get('ebav_tool_id', '')
            if not ebav_tool_id:
                messages.append(ValidationMessage(
                    ValidationMessage.WARN, i, op.name,
                    "Ébavurage activé mais aucun outil sélectionné"))
            elif ebav_tool_id not in tool_library.tools:
                messages.append(ValidationMessage(
                    ValidationMessage.ERROR, i, op.name,
                    f"Outil ébavurage introuvable: {ebav_tool_id}"))

        # 5. Multi-point sans points
        if op_class.SUPPORTS_MULTI_POINT and not op.points:
            if op.operation_type not in ("bpm",):
                messages.append(ValidationMessage(
                    ValidationMessage.INFO, i, op.name,
                    "Opération multi-point sans points définis"))

        # 6. Appel programme: fichier manquant
        if op.operation_type == "appel_programme":
            filepath = op.params.get('filepath', '')
            if not filepath:
                messages.append(ValidationMessage(
                    ValidationMessage.WARN, i, op.name,
                    "Chemin du programme externe non renseigné"))

        # 7. BPM: 2e outil taraudage manquant
        if op.operation_type == "bpm":
            bpm_mode = op.params.get('bpm_mode', '')
            if bpm_mode in ("Fraise + Taraudage", "Foret + Taraudage"):
                tool2_id = op.params.get('bpm_tool2_id', '')
                if not tool2_id:
                    messages.append(ValidationMessage(
                        ValidationMessage.WARN, i, op.name,
                        "Mode taraudage BPM sans 2e outil sélectionné"))

        # 8. Validation des paramètres via la classe d'opération
        param_errors = op_class.validate_params(op.params)
        for err in param_errors:
            messages.append(ValidationMessage(
                ValidationMessage.WARN, i, op.name, err))

    # Tri: errors first, then warnings, then info
    order = {ValidationMessage.ERROR: 0, ValidationMessage.WARN: 1,
             ValidationMessage.INFO: 2}
    messages.sort(key=lambda m: (order.get(m.level, 9), m.op_index))
    return messages
