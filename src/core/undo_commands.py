"""
Commandes Undo/Redo pour QUndoStack.
Chaque action utilisateur (ajout, suppression, déplacement, modification)
est encapsulée dans un QUndoCommand.
"""

import copy
from PySide6.QtGui import QUndoCommand
from src.core.program_model import ProgramModel, OperationInstance


def _find_op_index(program: ProgramModel, op_id: str,
                   fallback: int) -> int:
    """Retrouve l'index d'une opération par son id (les index stockés
    peuvent être périmés si d'autres commandes ont bougé la liste)."""
    for i, op in enumerate(program.operations):
        if op.id == op_id:
            return i
    return fallback


class AddOperationCommand(QUndoCommand):
    """Ajout d'une opération."""
    def __init__(self, program: ProgramModel, op: OperationInstance,
                 index: int = -1):
        super().__init__(f"Ajouter {op.name}")
        self._program = program
        self._op_data = op.to_dict()
        self._op_data['points'] = copy.deepcopy(op.points)
        self._index = index
        self._actual_index = -1

    def redo(self):
        op = OperationInstance.from_dict(self._op_data)
        op.points = copy.deepcopy(self._op_data.get('points', []))
        if self._index >= 0:
            self._program.add_operation(op, self._index)
            self._actual_index = self._index
        else:
            self._program.add_operation(op)
            self._actual_index = self._program.operation_count - 1

    def undo(self):
        if self._actual_index < 0:
            return
        idx = _find_op_index(
            self._program, self._op_data.get('id', ''),
            self._actual_index)
        op = self._program.get_operation(idx)
        if op and op.id == self._op_data.get('id'):
            # Re-snapshot: les modifications de paramètres faites après
            # l'ajout ne passent pas par le undo stack — les conserver
            # pour que redo restaure l'état le plus récent.
            self._op_data = op.to_dict()
            self._op_data['points'] = copy.deepcopy(op.points)
        self._program.remove_operation(idx)


class RemoveOperationCommand(QUndoCommand):
    """Suppression d'une opération."""
    def __init__(self, program: ProgramModel, index: int):
        op = program.get_operation(index)
        name = op.name if op else "?"
        super().__init__(f"Supprimer {name}")
        self._program = program
        self._index = index
        self._op_data = op.to_dict() if op else {}
        self._op_points = copy.deepcopy(op.points) if op else []

    def redo(self):
        idx = _find_op_index(
            self._program, self._op_data.get('id', ''), self._index)
        op = self._program.get_operation(idx)
        if op and op.id == self._op_data.get('id'):
            # Re-snapshot avant suppression (voir AddOperationCommand)
            self._op_data = op.to_dict()
            self._op_points = copy.deepcopy(op.points)
        self._program.remove_operation(idx)

    def undo(self):
        op = OperationInstance.from_dict(self._op_data)
        op.points = copy.deepcopy(self._op_points)
        self._program.add_operation(op, self._index)


class MoveOperationCommand(QUndoCommand):
    """Déplacement d'une opération."""
    def __init__(self, program: ProgramModel, from_idx: int, to_idx: int):
        super().__init__(f"Déplacer op {from_idx} → {to_idx}")
        self._program = program
        self._from = from_idx
        self._to = to_idx

    def redo(self):
        self._program.move_operation(self._from, self._to)

    def undo(self):
        self._program.move_operation(self._to, self._from)


class ReorderOperationsCommand(QUndoCommand):
    """Réordonnancement complet des opérations (drag-drop).

    skip_first_redo: comme ModifyOperationCommand — l'ordre 'new' est
    déjà appliqué au modèle par l'appelant."""
    def __init__(self, program: ProgramModel, old_ids: list,
                 new_ids: list, skip_first_redo: bool = False):
        super().__init__("Réordonner les opérations")
        self._program = program
        self._old_ids = list(old_ids)
        self._new_ids = list(new_ids)
        self._skip_first_redo = skip_first_redo

    def redo(self):
        if self._skip_first_redo:
            self._skip_first_redo = False
            return
        self._program.reorder_operations(self._new_ids)

    def undo(self):
        self._program.reorder_operations(self._old_ids)


class ModifyOperationCommand(QUndoCommand):
    """Modification des paramètres d'une opération.

    skip_first_redo: à utiliser quand l'état 'new' est DÉJÀ appliqué au
    modèle par l'appelant (ex: édition via le formulaire). Le premier
    redo() déclenché par QUndoStack.push() ne fait alors rien.
    """
    def __init__(self, program: ProgramModel, index: int,
                 old_data: dict, new_data: dict,
                 skip_first_redo: bool = False):
        op = program.get_operation(index)
        name = op.name if op else "?"
        super().__init__(f"Modifier {name}")
        self._program = program
        self._index = index
        self._op_id = op.id if op else old_data.get('id', '')
        self._old = copy.deepcopy(old_data)
        self._new = copy.deepcopy(new_data)
        self._skip_first_redo = skip_first_redo

    def redo(self):
        if self._skip_first_redo:
            self._skip_first_redo = False
            return
        self._apply(self._new)

    def undo(self):
        self._apply(self._old)

    def _apply(self, data: dict):
        idx = _find_op_index(self._program, self._op_id, self._index)
        op = self._program.get_operation(idx)
        if not op:
            return
        if self._op_id and op.id != self._op_id:
            return
        self._index = idx
        if 'name' in data:
            op.name = data['name']
        if 'tool_id' in data:
            op.tool_id = data['tool_id']
        if 'params' in data:
            op.params = copy.deepcopy(data['params'])
        if 'x' in data:
            op.x = data['x']
        if 'y' in data:
            op.y = data['y']
        if 'points' in data:
            op.points = copy.deepcopy(data['points'])
        if 'enabled' in data:
            op.enabled = data['enabled']
        # l'ensemble, quand l'état le porte (bouton de la sélection)
        if 'group_id' in data:
            op.group_id = data['group_id']
            op.group_name = data.get('group_name', '')
            op.group_libre = bool(data.get('group_libre', False))
        self._program.operation_updated.emit(self._index)
        self._program._mark_modified()
