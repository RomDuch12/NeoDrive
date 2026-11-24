"""
Modèle central du programme CNC - Observable par toutes les colonnes GUI.
"""

from PySide6.QtCore import QObject, Signal
from typing import List, Optional, Dict, Any
from datetime import datetime
import copy
import uuid


class ProjectSettings:
    """Paramètres globaux du projet SimPl."""

    def __init__(self):
        self.author = "RomDuch"
        self.comment = "Merci de checker le programme avant usinage"
        self.measuring_system = "Metric"
        self.workpiece_min_x = -100.0
        self.workpiece_min_y = -100.0
        self.workpiece_min_z = -25.0
        self.workpiece_max_x = 100.0
        self.workpiece_max_y = 100.0
        self.workpiece_max_z = 0.0
        # Programme destiné à être APPELÉ par un autre (usermodule,
        # Pattern) plutôt que lancé par l'opérateur: émet alors
        # @ UserVisible = false @ pour le masquer de la liste machine.
        self.library_module = False
        # Le BRUT (la plaque à usiner): un parallélépipède, dessus à
        # Z0 — pour la simulation matière et l'image du programme.
        # WorkpieceGeometry, elle, est l'ESPACE DE TRAVAIL (octobre
        # 2026). 0 = pas de brut déclaré: la zone usinée en tient lieu.
        self.brut_longueur = 0.0
        self.brut_largeur = 0.0
        self.brut_epaisseur = 0.0
        #: où est le zéro programme sur le brut: 'coin' (coin avant
        #: gauche), 'centre', ou 'libre' (à brut_dx, brut_dy du coin)
        self.brut_origine = 'coin'
        self.brut_dx = 0.0
        self.brut_dy = 0.0
        #: les réglages qu'on ne connaît pas (fichier d'une version plus
        #: récente): gardés tels quels, réécrits à l'enregistrement
        self._extra: Dict[str, Any] = {}

    def to_dict(self) -> dict:
        d = copy.deepcopy(self._extra)
        d.update(self._dict_connu())
        return d

    def _dict_connu(self) -> dict:
        return {
            'author': self.author,
            'comment': self.comment,
            'measuring_system': self.measuring_system,
            'library_module': self.library_module,
            'workpiece_min_x': self.workpiece_min_x,
            'workpiece_min_y': self.workpiece_min_y,
            'workpiece_min_z': self.workpiece_min_z,
            'workpiece_max_x': self.workpiece_max_x,
            'workpiece_max_y': self.workpiece_max_y,
            'workpiece_max_z': self.workpiece_max_z,
            'brut_longueur': self.brut_longueur,
            'brut_largeur': self.brut_largeur,
            'brut_epaisseur': self.brut_epaisseur,
            'brut_origine': self.brut_origine,
            'brut_dx': self.brut_dx,
            'brut_dy': self.brut_dy,
        }

    #: les origines du brut (clé, libellé)
    ORIGINES_BRUT = (('coin', "Coin avant gauche"), ('centre', "Centre"),
                     ('libre', "Décalage libre (X, Y depuis le coin)"))

    def boite_brut(self):
        """(xmin, xmax, ymin, ymax, zmin, zmax) du brut dans le repère
        du programme, ou None sans brut déclaré."""
        try:
            L = float(self.brut_longueur or 0.0)
            l = float(self.brut_largeur or 0.0)
            e = float(self.brut_epaisseur or 0.0)
            dx = float(self.brut_dx or 0.0)
            dy = float(self.brut_dy or 0.0)
        except (TypeError, ValueError):
            return None
        if L <= 0 or l <= 0 or e <= 0:
            return None
        if self.brut_origine == 'centre':
            x0, y0 = -L / 2.0, -l / 2.0
        elif self.brut_origine == 'libre':
            x0, y0 = -dx, -dy
        else:
            x0, y0 = 0.0, 0.0
        return (x0, x0 + L, y0, y0 + l, -e, 0.0)

    @classmethod
    def from_dict(cls, d: dict) -> 'ProjectSettings':
        s = cls()
        connus = set(vars(s)) - {'_extra'}
        for key, val in d.items():
            # un réglage, jamais une méthode (« to_dict » dans un
            # fichier remplaçait la méthode)
            if key in connus:
                setattr(s, key, val)
            else:
                s._extra[key] = copy.deepcopy(val)
        return s


class OperationInstance:
    """Instance concrète d'une opération avec ses paramètres remplis."""

    def __init__(self, operation_type: str, name: str = ""):
        self.id = str(uuid.uuid4())[:8]
        self.operation_type = operation_type
        self.name = name or operation_type
        self.tool_id = ""  # clé dans ToolLibrary
        self.params: Dict[str, Any] = {}
        self.enabled = True
        self.x = 0.0
        self.y = 0.0
        self.z = 15.0  # SafeRapid Z par défaut
        self.points: List[Dict] = []  # multi-point: [{"x": float, "y": float}]
        # Ensemble d'appartenance: les opérations d'un même group_id
        # sont affichées repliées sous un même titre (import d'un
        # SimPl, regroupement manuel). Vide = opération isolée.
        self.group_id: str = ""
        self.group_name: str = ""
        # Ensemble LIBRE: des opérations différentes réunies (un filet
        # et son avant-trou, les séquences d'une phase de bridage):
        # l'outil n'y est pas commun. Sinon, un ensemble est une suite
        # d'instances qui partagent leur outil.
        self.group_libre: bool = False
        #: l'outil du fichier, absent de la bibliothèque de ce poste:
        #: l'opération tourne sans outil (comme avant), mais le fichier
        #: le garde — ouvrir puis enregistrer l'effaçait
        self.outil_absent: str = ""
        #: les champs qu'on ne connaît pas (version plus récente)
        self._extra: Dict[str, Any] = {}

    #: les champs d'une opération que cette version connaît
    _CLES_CONNUES = frozenset((
        'id', 'operation_type', 'name', 'tool_id', 'params', 'enabled',
        'x', 'y', 'z', 'points', 'group_id', 'group_name', 'group_libre',
        'outil_absent'))

    #: paramètres injectés au vol (nom d'outil, hauteurs de
    #: dégagement, opérations d'amont d'une gamme): ils se
    #: recalculent à chaque ouverture et n'ont rien à faire dans un
    #: fichier — l'amont y recopierait tout le parcours d'une autre
    #: opération.
    @staticmethod
    def _params_durables(params: dict, operation_type: str = '') -> dict:
        # ce que le type d'opération tient à garder malgré le « _ »:
        # l'appel en motif d'un bloc importé, son outil d'origine…
        try:
            from src.operations.registry import OperationRegistry
            garder = set(getattr(OperationRegistry.get(operation_type),
                                 'PARAMS_DURABLES', ()))
        except Exception:
            garder = set()
        # (« _aff_ »: la transparence et la division de l'opération)
        return {k: v for k, v in params.items()
                if not str(k).startswith('_') or k in garder
                or str(k).startswith('_aff_')}

    def to_dict(self) -> dict:
        d = copy.deepcopy(self._extra)
        d.update({
            'id': self.id,
            'operation_type': self.operation_type,
            'name': self.name,
            'tool_id': self.tool_id,
            'params': self._params_durables(self.params,
                                            self.operation_type),
            'enabled': self.enabled,
            'x': self.x,
            'y': self.y,
            'z': self.z,
        })
        if self.points:
            d['points'] = [dict(p) for p in self.points]
        if self.group_id:
            d['group_id'] = self.group_id
            d['group_name'] = self.group_name
            if self.group_libre:
                d['group_libre'] = True
        if self.outil_absent and not self.tool_id:
            d['outil_absent'] = self.outil_absent
        return d

    def dict_fichier(self) -> dict:
        """`to_dict` pour un fichier (.ndp, .nds, session): l'outil
        absent de ce poste reprend sa place dans `tool_id` — le poste
        qui l'a le retrouve."""
        d = self.to_dict()
        absent = d.pop('outil_absent', '')
        if absent and not d.get('tool_id'):
            d['tool_id'] = absent
        return d

    @classmethod
    def from_dict(cls, d: dict) -> 'OperationInstance':
        op = cls(d.get('operation_type', ''), d.get('name', ''))
        op.id = d.get('id', str(uuid.uuid4())[:8])
        op.tool_id = d.get('tool_id', '')
        # Copie profonde: ne jamais partager le dict params avec la
        # source (snapshots undo, données de fichier, etc.)
        op.params = copy.deepcopy(d.get('params', {}))
        op.enabled = d.get('enabled', True)
        op.x = d.get('x', 0.0)
        op.y = d.get('y', 0.0)
        op.z = d.get('z', 15.0)
        op.points = [dict(p) for p in d.get('points', [])]
        op.group_id = d.get('group_id', '')
        op.group_name = d.get('group_name', '')
        op.group_libre = bool(d.get('group_libre', False))
        op.outil_absent = str(d.get('outil_absent', '') or '')
        op._extra = {k: copy.deepcopy(v) for k, v in d.items()
                     if k not in cls._CLES_CONNUES}
        return op

    def clone(self) -> 'OperationInstance':
        d = self.to_dict()
        d['id'] = str(uuid.uuid4())[:8]
        d['name'] = self.name + " (copie)"
        # Les anciennes « instances similaires » ne se dupliquent PAS:
        # la copie émettait sinon les usinages de l'originale, avec des
        # cotes qui n'étaient plus les siennes.
        d.get('params', {}).pop('instances', None)
        cloned = OperationInstance.from_dict(d)
        cloned.points = copy.deepcopy(self.points)
        return cloned


class ProgramModel(QObject):
    """Modèle central observable. Les 3 colonnes GUI écoutent ses signaux."""

    changed = Signal()  # Signal global de modification
    operation_added = Signal(int)  # index
    operation_removed = Signal(int)  # index
    operation_moved = Signal(int, int)  # from_index, to_index
    operation_updated = Signal(int)  # index
    settings_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = ProjectSettings()
        #: une ligne pour dire à quoi sert ce programme (ou ce
        #: sous-programme): lue dans le navigateur de fichiers
        self.description: str = ""
        self._operations: List[OperationInstance] = []
        self._filepath: Optional[str] = None
        self._modified = False
        #: les opérations d'un type que cette version ne connaît pas
        #: (fichier d'une version plus récente), avec leur rang dans
        #: le fichier: pas affichées, pas générées, mais réécrites à
        #: l'enregistrement — ouvrir puis enregistrer les effaçait
        self.ops_inconnues: List[tuple] = []
        #: les clés de premier niveau du fichier qu'on ne connaît pas
        self.extra_fichier: Dict[str, Any] = {}

    def reprendre_conservation(self, autre: 'ProgramModel') -> None:
        """Reprend d'un programme chargé ce qu'on garde sans le
        connaître (opérations inconnues, clés de fichier)."""
        self.ops_inconnues = copy.deepcopy(
            getattr(autre, 'ops_inconnues', []))
        self.extra_fichier = copy.deepcopy(
            getattr(autre, 'extra_fichier', {}))

    @property
    def operations(self) -> List[OperationInstance]:
        return list(self._operations)

    @property
    def operation_count(self) -> int:
        return len(self._operations)

    @property
    def is_modified(self) -> bool:
        return self._modified

    @property
    def filepath(self) -> Optional[str]:
        return self._filepath

    @filepath.setter
    def filepath(self, value: Optional[str]):
        self._filepath = value

    def _mark_modified(self):
        self._modified = True
        self.changed.emit()

    def mark_saved(self):
        self._modified = False

    def mark_unsaved(self):
        """Des modifications non enregistrées, sans rien changer d'autre:
        un onglet de session restauré qui n'était pas enregistré ne
        l'est toujours pas (il passait pour enregistré, et Ctrl+O
        l'écrasait sans rien demander)."""
        self._modified = True

    def add_operation(self, op: OperationInstance, index: int = -1):
        if index < 0 or index >= len(self._operations):
            self._operations.append(op)
            idx = len(self._operations) - 1
        else:
            self._operations.insert(index, op)
            idx = index
        self.operation_added.emit(idx)
        self._mark_modified()

    def remove_operation(self, index: int):
        if 0 <= index < len(self._operations):
            self._operations.pop(index)
            self.operation_removed.emit(index)
            self._mark_modified()

    def move_operation(self, from_index: int, to_index: int):
        if from_index == to_index:
            return
        if 0 <= from_index < len(self._operations) and \
                0 <= to_index < len(self._operations):
            op = self._operations.pop(from_index)
            self._operations.insert(to_index, op)
            self.operation_moved.emit(from_index, to_index)
            self._mark_modified()

    def update_operation(self, index: int, **kwargs):
        if 0 <= index < len(self._operations):
            op = self._operations[index]
            for key, val in kwargs.items():
                if hasattr(op, key):
                    setattr(op, key, val)
            self.operation_updated.emit(index)
            self._mark_modified()

    def update_operation_params(self, index: int, params: Dict[str, Any]):
        if 0 <= index < len(self._operations):
            self._operations[index].params.update(params)
            self.operation_updated.emit(index)
            self._mark_modified()

    def get_operation(self, index: int) -> Optional[OperationInstance]:
        if 0 <= index < len(self._operations):
            return self._operations[index]
        return None

    def get_operation_by_id(self, op_id: str) -> Optional[OperationInstance]:
        for op in self._operations:
            if op.id == op_id:
                return op
        return None

    def reorder_operations(self, id_order: List[str]):
        """Réordonne les opérations selon la liste d'ids donnée.
        Les opérations absentes de id_order conservent leur ordre
        relatif et sont placées à la fin."""
        by_id = {op.id: op for op in self._operations}
        wanted = set(id_order)
        new_list = [by_id[i] for i in id_order if i in by_id]
        new_list.extend(
            op for op in self._operations if op.id not in wanted)
        if new_list == self._operations:
            return
        self._operations = new_list
        self._mark_modified()

    def update_settings(self, **kwargs):
        for key, val in kwargs.items():
            if hasattr(self.settings, key):
                setattr(self.settings, key, val)
        # les réglages, pas les opérations: ni leur liste ni le dessin
        # n'ont à se refaire (tout l'était à chaque cote du brut)
        self._modified = True
        self.settings_changed.emit()

    def clear(self):
        self._operations.clear()
        self.settings = ProjectSettings()
        self.ops_inconnues = []
        self.extra_fichier = {}
        self._filepath = None
        self._modified = False
        self.changed.emit()

    def get_used_tool_ids(self) -> List[str]:
        """Retourne la liste des tool_id utilisés par les opérations ACTIVES.
        Inclut les outils d'ébavurage."""
        seen = set()
        result = []
        for op in self._operations:
            if not op.enabled:
                continue
            if op.tool_id and op.tool_id not in seen:
                seen.add(op.tool_id)
                result.append(op.tool_id)
            # Ébavurage: outil dédié
            ebav_tool = op.params.get('ebav_tool_id', '')
            if ebav_tool and ebav_tool not in seen:
                if op.params.get('use_ebav', False):
                    seen.add(ebav_tool)
                    result.append(ebav_tool)
            # BPM: 2e outil (taraudage) — seulement si le mode l'utilise
            bpm_tool2 = op.params.get('bpm_tool2_id', '')
            if (bpm_tool2 and bpm_tool2 not in seen
                    and op.operation_type == "bpm"
                    and op.params.get('bpm_mode', '') in (
                        "Fraise + Taraudage", "Foret + Taraudage")):
                seen.add(bpm_tool2)
                result.append(bpm_tool2)
        return result

    def to_dict(self, avec_inconnues: bool = True) -> dict:
        """Le programme pour un fichier (.ndp, session, archive).

        Les opérations inconnues reprennent leur rang (borné à la
        fin); `avec_inconnues=False` donne une liste alignée sur
        `operations` (le bloc NDMETA les apparie une à une)."""
        operations = [op.dict_fichier() for op in self._operations]
        if avec_inconnues:
            for rang, donnees in sorted(self.ops_inconnues,
                                        key=lambda e: e[0]):
                operations.insert(min(int(rang), len(operations)),
                                  copy.deepcopy(donnees))
        d = copy.deepcopy(self.extra_fichier)
        d.update({
            'format_version': '1.0',
            'type': 'program',
            'description': str(getattr(self, 'description', '') or ''),
            'created': datetime.now().isoformat(),
            'modified': datetime.now().isoformat(),
            'settings': self.settings.to_dict(),
            'operations': operations,
        })
        return d


#: les clés de premier niveau d'un fichier programme
_CLES_FICHIER = frozenset(('format_version', 'type', 'description',
                           'created', 'modified', 'settings',
                           'operations'))


def operation_depuis_dict(donnees: dict, outils) -> Optional[OperationInstance]:
    """Une opération lue d'un fichier, ou None si son type est inconnu
    de cette version. Un outil absent de `outils` (dict des outils du
    poste) est mis de côté dans `outil_absent`, pas effacé."""
    from src.operations.registry import OperationRegistry
    op = OperationInstance.from_dict(donnees)
    try:
        OperationRegistry.get(op.operation_type)
    except KeyError:
        return None
    if op.tool_id and op.tool_id not in outils:
        op.outil_absent = op.tool_id
        op.tool_id = ""
    return op


def programme_depuis_dict(data: dict, outils) -> 'ProgramModel':
    """Un programme lu d'un fichier (.ndp, session): rien de ce que
    cette version ne connaît n'est perdu — outil absent, opération
    d'un type inconnu, champ inconnu se réécrivent à l'enregistrement."""
    prog = ProgramModel()
    prog.settings = ProjectSettings.from_dict(data.get('settings', {}) or {})
    prog.description = str(data.get('description', '') or '')
    for rang, op_data in enumerate(data.get('operations', []) or []):
        if not isinstance(op_data, dict):
            continue
        op = operation_depuis_dict(op_data, outils)
        if op is None:
            prog.ops_inconnues.append((rang, copy.deepcopy(op_data)))
            continue
        prog.add_operation(op)
    prog.extra_fichier = {k: copy.deepcopy(v) for k, v in data.items()
                          if k not in _CLES_FICHIER}
    return prog


#: opérations qui portaient des « instances similaires », et la clé de
#: finition propre à chacune
_LEGACY_INSTANCE_TYPES = ("poche_rectangle", "decoupe_rectangle",
                          "surfacage_rectangle")
_LEGACY_FINISH_KEY = {
    "poche_rectangle": "finishing_xy",
    "decoupe_rectangle": "finishing_xy",
    "surfacage_rectangle": "finishing_z",
}


def expand_legacy_instances(program: 'ProgramModel') -> int:
    """Convertit les « instances similaires » en membres d'ensemble.

    Ce paramètre décrivait des usinages supplémentaires DANS le
    sous-programme d'une opération. Il se dupliquait avec elle, si
    bien qu'une copie réémettait les usinages de l'originale avec des
    cotes qui n'étaient plus les siennes. Chaque instance devient une
    opération à part entière, membre du même ensemble: elle a son
    formulaire, se voit, se déplace et se supprime.

    Retourne le nombre d'opérations créées."""
    created = 0
    for op in list(program.operations):
        instances = op.params.get('instances') or []
        op.params.pop('instances', None)
        if not instances or op.operation_type not in _LEGACY_INSTANCE_TYPES:
            continue
        if not op.group_id:
            op.group_id = str(uuid.uuid4())[:8]
            op.group_name = op.name
        finish_key = _LEGACY_FINISH_KEY.get(op.operation_type)
        index = program.operations.index(op)
        for n, inst in enumerate(instances, start=2):
            clone = op.clone()
            clone.name = f"{op.name} ({n})"
            clone.group_id = op.group_id
            clone.group_name = op.group_name
            clone.x = float(inst.get('pos_x', op.x))
            clone.y = float(inst.get('pos_y', op.y))
            for key in ('width_x', 'width_y', 'corner_radius', 'depth',
                        'repeat_x_count', 'repeat_x_step',
                        'repeat_y_count', 'repeat_y_step',
                        'repeat2_x_count', 'repeat2_x_step',
                        'repeat2_y_count', 'repeat2_y_step'):
                if inst.get(key) is not None:
                    clone.params[key] = inst[key]
            if inst.get('finishing') is not None and finish_key:
                clone.params[finish_key] = inst['finishing']
            index += 1
            program.add_operation(clone, index)
            created += 1
    return created
