"""Opération: Palpage coin (CornerMeasure) — inline.

Manuel SimPL 3.1.1, § 5.3.1.1 « Corner » (p. 232): le palpeur XYZ
reprend l'origine (et, si on le demande, l'orientation) sur un COIN de
la pièce. Les vecteurs de mesure partent de la position courante de
la pointe: on l'amène d'abord au-dessus du coin (SafeRapid).

    SafeRapid X=0 Y=0 Z=5
    CornerMeasure view=MeasuringView.Outside
        orientation=MeasuringOrientation.FrontLeft
        xMeasureYOffset=10 xMeasureZOffset=-5 yMeasureXOffset=10
        yMeasureZOffset=-5 zMeasureXOffset=10 zMeasureYOffset=10
        retractDistance=15 searchDistance=15 skipZMeasureResult=false
        skipZMeasure=false forceSafeHeight=false resultCs=CsType.Wcs
        originXShift=0 originYShift=0 originZShift=0
        stockXOffset=0 stockYOffset=0 stockZOffset=0
"""

from typing import List, Dict, Any
from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement
)
from src.operations.registry import OperationRegistry

#: coin palpé -> MeasuringOrientation
COINS = {"Avant gauche": "FrontLeft", "Avant droit": "FrontRight",
         "Arrière gauche": "BackLeft", "Arrière droit": "BackRight"}
#: côté d'approche -> MeasuringView
VUES = {"Extérieur": "Outside", "Intérieur": "Inside"}
#: où va le résultat -> CsType
RESULTATS = {"Repère pièce (Wcs)": "Wcs", "Repère local (Lcs)": "Lcs",
             "Aucun (valeur seule)": "None"}


@OperationRegistry.register("palpage_coin")
class PalpageCoin(AbstractOperation):
    DISPLAY_NAME = "Palpage coin"
    CATEGORY = "Réglage"
    HORS_MATIERE = True
    DESCRIPTION = ("CornerMeasure: origine (et orientation) reprises "
                   "sur un coin de la pièce")
    ICON = "ruler"
    # nouvelle (manuel SimPL, octobre 2026): en expert par
    # défaut — en mode simple, clic droit sur sa catégorie
    EXPERT_ONLY = True
    INLINE = True
    REQUIRES_TOOL = False
    REQUIRES_COORDINATES = True

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        g, e = "Palpage", "Palpage expert"
        return [
            ParameterDef("corner", "Coin", ParameterType.CHOICE,
                         default="Avant gauche", choices=list(COINS),
                         group=g, tooltip="Le coin palpé, vu de face "
                         "(orientation). La position X/Y est celle où "
                         "le palpeur descend, à côté du coin."),
            ParameterDef("view", "Approche", ParameterType.CHOICE,
                         default="Extérieur", choices=list(VUES),
                         group=g, tooltip="Extérieur: un coin de brut. "
                         "Intérieur: un coin de poche (view)."),
            ParameterDef("probe_depth", "Profondeur de palpage",
                         ParameterType.FLOAT, default=5.0, min_value=0.1,
                         max_value=200.0, unit="mm", group=g,
                         tooltip="Hauteur sous le dessus où X et Y sont "
                                 "mesurés (x/yMeasureZOffset)"),
            ParameterDef("distance", "Distance au coin", ParameterType.FLOAT,
                         default=10.0, min_value=0.5, max_value=500.0,
                         unit="mm", group=g,
                         tooltip="Où les flancs sont touchés, depuis le "
                                 "coin (x/yMeasure…Offset, zMeasure…)"),
            ParameterDef("measure_rotation", "Mesurer l'orientation",
                         ParameterType.BOOL, default=False, group=g,
                         tooltip="Un second point par flanc: l'angle de "
                                 "la pièce sur la table est mesuré"),
            ParameterDef("rotation_distance", "Écart pour l'orientation",
                         ParameterType.FLOAT, default=40.0, min_value=1.0,
                         max_value=2000.0, unit="mm", group=g,
                         tooltip="Distance du second point: plus elle "
                                 "est grande, plus l'angle est précis"),
            ParameterDef("probe_safe_z", "Z d'approche", ParameterType.FLOAT,
                         default=5.0, min_value=0.0, max_value=200.0,
                         unit="mm", group=g),
            ParameterDef("skip_z_measure", "Ne pas mesurer Z",
                         ParameterType.BOOL, default=False, group=e,
                         expert_only=True),
            ParameterDef("force_safe_height", "Hauteur sûre entre les "
                         "points", ParameterType.BOOL, default=False,
                         group=e, expert_only=True),
            ParameterDef("retract", "Z après mesure", ParameterType.FLOAT,
                         default=15.0, min_value=0.0, unit="mm", group=e,
                         expert_only=True),
            ParameterDef("search", "Course de recherche",
                         ParameterType.FLOAT, default=15.0, min_value=1.0,
                         unit="mm", group=e, expert_only=True),
            ParameterDef("result", "Résultat", ParameterType.CHOICE,
                         default="Repère pièce (Wcs)",
                         choices=list(RESULTATS), group=e, expert_only=True),
            ParameterDef("origin_x_shift", "Décalage origine X",
                         ParameterType.FLOAT, default=0.0, group=e,
                         expert_only=True),
            ParameterDef("origin_y_shift", "Décalage origine Y",
                         ParameterType.FLOAT, default=0.0, group=e,
                         expert_only=True),
            ParameterDef("origin_z_shift", "Décalage origine Z",
                         ParameterType.FLOAT, default=0.0, group=e,
                         expert_only=True),
            ParameterDef("stock_x", "Surépaisseur brut X",
                         ParameterType.FLOAT, default=0.0, group=e,
                         expert_only=True),
            ParameterDef("stock_y", "Surépaisseur brut Y",
                         ParameterType.FLOAT, default=0.0, group=e,
                         expert_only=True),
            ParameterDef("stock_z", "Surépaisseur brut Z",
                         ParameterType.FLOAT, default=0.0, group=e,
                         expert_only=True),
        ]

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        return ToolRequirement(tool_types=[],
                               description="Palpeur XYZ (automatique)")

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        p = {**cls.get_default_params(), **params}

        def _f(cle, defaut=0.0):
            try:
                return float(p.get(cle, defaut) or 0.0)
            except (TypeError, ValueError):
                return float(defaut)

        oui = {True: "true", False: "false"}
        d = _f('distance', 10.0)
        prof = -abs(_f('probe_depth', 5.0))
        x, y = _f('_x'), _f('_y')
        lignes = [
            f"    SafeRapid X={x:.3f} Y={y:.3f} Z={_f('probe_safe_z', 5.0):g}",
            "    CornerMeasure (",
            f"         view=MeasuringView."
            f"{VUES.get(p.get('view'), 'Outside')}",
            f"         orientation=MeasuringOrientation."
            f"{COINS.get(p.get('corner'), 'FrontLeft')}",
            f"         xMeasureYOffset={d:g} xMeasureZOffset={prof:g}",
            f"         yMeasureXOffset={d:g} yMeasureZOffset={prof:g}",
            f"         zMeasureXOffset={d:g} zMeasureYOffset={d:g}",
        ]
        if p.get('measure_rotation'):
            r = _f('rotation_distance', 40.0)
            lignes.append(f"         xMeasureYOffsetForRotation={r:g} "
                          f"yMeasureXOffsetForRotation={r:g}")
        lignes += [
            f"         retractDistance={_f('retract', 15.0):g} "
            f"searchDistance={_f('search', 15.0):g}",
            f"         skipZMeasureResult=false "
            f"skipZMeasure={oui[bool(p.get('skip_z_measure'))]} "
            f"forceSafeHeight={oui[bool(p.get('force_safe_height'))]}",
            f"         resultCs=CsType."
            f"{RESULTATS.get(p.get('result'), 'Wcs')}",
            f"         originXShift={_f('origin_x_shift'):g} "
            f"originYShift={_f('origin_y_shift'):g} "
            f"originZShift={_f('origin_z_shift'):g}",
            f"         stockXOffset={_f('stock_x'):g} "
            f"stockYOffset={_f('stock_y'):g} "
            f"stockZOffset={_f('stock_z'):g}",
            "         )",
        ]
        return "\n".join(lignes)
