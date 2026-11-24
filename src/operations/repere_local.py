"""Opération: Repère local (ShiftLcs, RotateLcs, ResetLcs) — inline.

Manuel SimPL 3.1.1, § 5.6.2 « Local coordinate system » (p. 403-411):
le repère LOCAL se décale et tourne PAR-DESSUS le repère pièce (Wcs),
sans toucher à ce que le palpage y a mis; ResetLcs le remet à zéro.

    ShiftLcsAbs X=10 Y=50 Z=0        (depuis le Wcs)
    ShiftLcsInc X=10 Y=50 Z=0        (depuis le Lcs courant)
    RotateLcsAbs gamma=45            (depuis le Wcs)
    RotateLcsInc gamma=45            (depuis le Lcs courant)
    ResetLcs
"""

from typing import Any, Dict, List

from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement
)
from src.operations.registry import OperationRegistry

MODES = {"Décalage incrémental (ShiftLcsInc)": "ShiftLcsInc",
         "Décalage absolu (ShiftLcsAbs)": "ShiftLcsAbs",
         "Rotation incrémentale (RotateLcsInc)": "RotateLcsInc",
         "Rotation absolue (RotateLcsAbs)": "RotateLcsAbs",
         "Remise à zéro (ResetLcs)": "ResetLcs"}


@OperationRegistry.register("repere_local")
class RepereLocal(AbstractOperation):
    DISPLAY_NAME = "Repère local"
    CATEGORY = "Réglage"
    HORS_MATIERE = True
    DESCRIPTION = ("ShiftLcs / RotateLcs / ResetLcs: décaler ou tourner le "
                   "repère local par-dessus le repère pièce")
    ICON = "shift"
    EXPERT_ONLY = True
    INLINE = True
    REQUIRES_TOOL = False
    REQUIRES_COORDINATES = False

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        g = "Repère local"
        return [
            ParameterDef("mode", "Commande", ParameterType.CHOICE,
                         default="Décalage incrémental (ShiftLcsInc)",
                         choices=list(MODES), group=g,
                         tooltip="Absolu: depuis le repère pièce (Wcs). "
                                 "Incrémental: depuis le repère local "
                                 "courant. Le repère pièce (et ce que le "
                                 "palpage y a mis) ne bouge pas."),
            ParameterDef("shift_x", "X", ParameterType.FLOAT, default=0.0,
                         unit="mm", group=g),
            ParameterDef("shift_y", "Y", ParameterType.FLOAT, default=0.0,
                         unit="mm", group=g),
            ParameterDef("shift_z", "Z", ParameterType.FLOAT, default=0.0,
                         unit="mm", group=g),
            ParameterDef("gamma", "Angle autour de Z", ParameterType.FLOAT,
                         default=0.0, min_value=-360.0, max_value=360.0,
                         unit="°", group=g),
        ]

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        return ToolRequirement(tool_types=[],
                               description="Aucun outil requis")

    @staticmethod
    def commande(params: Dict[str, Any]) -> str:
        return MODES.get(params.get('mode'), "ShiftLcsInc")

    @classmethod
    def appliquer(cls, params: Dict[str, Any], shift, rot: float,
                  memo: Dict) -> tuple:
        """Le repère après cette opération, pour le dessin (canvas 2D,
        3D): (x, y, angle). `memo` garde le repère pièce d'où le local
        part et les valeurs du local (un décalage ou une rotation du
        repère pièce le remet à None)."""
        import math

        def _f(cle):
            try:
                return float(params.get(cle, 0.0) or 0.0)
            except (TypeError, ValueError):
                return 0.0
        if memo.get('base') is None:
            memo['base'] = (float(shift[0]), float(shift[1]), float(rot))
            memo['v'] = {'X': 0.0, 'Y': 0.0, 'gamma': 0.0}
        v = memo['v']
        c = cls.commande(params)
        if c == "ResetLcs":
            v.update({'X': 0.0, 'Y': 0.0, 'gamma': 0.0})
        elif c == "ShiftLcsAbs":
            v['X'], v['Y'] = _f('shift_x'), _f('shift_y')
        elif c == "ShiftLcsInc":
            a = math.radians(v['gamma'])
            dx, dy = _f('shift_x'), _f('shift_y')
            v['X'] += dx * math.cos(a) - dy * math.sin(a)
            v['Y'] += dx * math.sin(a) + dy * math.cos(a)
        elif c == "RotateLcsAbs":
            v['gamma'] = _f('gamma')
        elif c == "RotateLcsInc":
            v['gamma'] += _f('gamma')
        bx, by, ba = memo['base']
        a = math.radians(ba)
        return (bx + v['X'] * math.cos(a) - v['Y'] * math.sin(a),
                by + v['X'] * math.sin(a) + v['Y'] * math.cos(a),
                ba + v['gamma'])

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        p = {**cls.get_default_params(), **params}

        def _f(cle):
            try:
                return float(p.get(cle, 0.0) or 0.0)
            except (TypeError, ValueError):
                return 0.0

        c = cls.commande(p)
        if c == "ResetLcs":
            return "    ResetLcs"
        if c.startswith("Rotate"):
            return f"    {c} gamma={_f('gamma'):g}"
        return (f"    {c} X={_f('shift_x'):g} Y={_f('shift_y'):g} "
                f"Z={_f('shift_z'):g}")
