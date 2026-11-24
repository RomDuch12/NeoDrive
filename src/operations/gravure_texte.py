"""Opération: Gravure Texte (Engrave::StandardTextEngrave)
strokeRapidZ=14 et strokeCuttingZ=1 sont fixes.
"""

from typing import List, Dict, Any
from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement,
    REPEAT_PARAMS
)
from src.operations.registry import OperationRegistry


@OperationRegistry.register("gravure_texte")
class GravureTexte(AbstractOperation):
    DISPLAY_NAME = "Texte Datron"
    CATEGORY = "Gravure"
    DESCRIPTION = "Gravure de texte (référence, date, etc.)"
    ICON = "engrave"
    #: un nom choisi à la main l'emporte sur le texte gravé — aussi
    #: une fois le projet rouvert
    PARAMS_DURABLES = ('_name_locked',)

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return [
            ParameterDef("text", "Texte", ParameterType.STRING,
                         default="Texte", unit="",
                         group="Texte",
                         tooltip="Texte à graver. Utiliser {DATE} pour la date auto"),
            ParameterDef("use_date", "Ajouter date auto", ParameterType.BOOL,
                         default=False, group="Texte",
                         tooltip="Ajoute DateTimeModule::GetDate au texte"),
            ParameterDef("char_height", "Hauteur caractère",
                         ParameterType.FLOAT, default=2.5, min_value=0.1,
                         unit="mm", group="Texte"),
            ParameterDef("rotation", "Rotation", ParameterType.FLOAT,
                         default=0.0, min_value=0.0, max_value=360.0,
                         unit="°", group="Texte"),
            ParameterDef("depth", "Pz", ParameterType.FLOAT,
                         default=0.25, min_value=0.01, unit="mm",
                         group="Profondeur"),
            # strokeRapidZ=14 et strokeCuttingZ=1 fixes
            ParameterDef("multi_pass", "Double passe", ParameterType.BOOL,
                         default=True, group="Options",
                         tooltip="Passe d'ébauche + finition"),
            ParameterDef("depth_pass1", "Profondeur passe 1",
                         ParameterType.FLOAT, default=0.15, min_value=0.01,
                         unit="mm", group="Options"),
        ] + REPEAT_PARAMS

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        return ToolRequirement(
            tool_types=['Con20', 'Con30'],
            description="Fraise conique (gravure)"
        )

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        defaults = cls.get_default_params()
        p = {**defaults, **params}
        srz = p.get('_stroke_rapid_z', 15)
        scz = p.get('_stroke_cutting_z', 1)

        # Construction du texte — neutraliser " et retours ligne qui
        # casseraient le littéral chaîne SimPl
        text_val = str(p.get('text', 'Texte'))
        text_val = text_val.replace('"', "'").replace('\n', ' ')
        use_date = p.get('use_date', False)
        # Variable concaténée au texte (n° de série, saisie
        # opérateur...): injectée par le générateur via _text_var
        text_var = str(p.get('_text_var', '') or '').strip()
        if text_val:
            parts = [f'"{text_val}"']
        else:
            parts = []
        if text_var:
            parts.append(text_var)
        if use_date:
            parts.append("DateTimeModule :: GetDate")
        if not parts:
            parts = ['""']
        text_expr = "text=" + " + ".join(parts)

        multi_pass = p.get('multi_pass', True)

        def _engrave_line(depth_val):
            return (f"    Engrave::StandardTextEngrave ({text_expr} "
                    f"charWidth=0 charHeight={p['char_height']} "
                    f"textWidth=0 rotation={p['rotation']} slant=0 "
                    f"strokeRapidZ={srz} strokeCuttingZ={scz} "
                    f"depth={depth_val} Center)")

        if multi_pass:
            depth1 = p.get('depth_pass1', 0.15)
            depth2 = p.get('depth', 0.25)
            try:
                plus_profonde = float(depth1) >= float(depth2)
            except (TypeError, ValueError):
                plus_profonde = False
            # une passe 1 au moins aussi profonde que la gravure
            # creusait PLUS que demandé (Pz 0.08: 0.15 puis 0.08):
            # une seule passe, à la profondeur voulue
            if plus_profonde:
                return _engrave_line(depth2)
            return _engrave_line(depth1) + "\n" + _engrave_line(depth2)
        else:
            return _engrave_line(p['depth'])
