"""Opération: Reprise du dernier palpage (données persistées).

Trouvé dans la documentation machine —
`Datron Documentation/UserDataPersistence/PersistMeasuring.simpl`.
La machine n'a pas d'instruction « refaire le dernier palpage »; elle
a mieux: une PERSISTANCE de variables, qui survit à la fin du
programme et au redémarrage.

    measuringDataSet:MeasuringCommonValues::MeasuringDataWithInfo[]

    if measuringDataSet hassavedvalue          # y a-t-il un palpage ?
        result = Dialog message="…" Yes=true No=true
    endif
    if result == DialogResult.Yes
        loadvalueof measuringDataSet           # on le reprend
    else
        data = SurfaceMeasure resultCs=CsType.Wcs …
        append data to measuringDataSet
        savevalueof measuringDataSet           # on l'enregistre
    endif
    …
    deletesavedvalueof measuringDataSet        # après usinage réussi

D'où cette opération: sur la première pièce d'une série, elle palpe et
retient; sur les suivantes, elle propose de reprendre la mesure au
lieu de repalper.

Portée: le Z mesuré par `SurfaceMeasure`, seul palpage dont la
documentation montre le résultat persistable
(`MeasuredTransformation.TranslationZ`).
"""

from typing import List, Dict, Any

from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement
)
from src.operations.registry import OperationRegistry


@OperationRegistry.register("palpage_memorise")
class PalpageMemorise(AbstractOperation):
    OP_TYPE = "palpage_memorise"
    DISPLAY_NAME = "Palpage mémorisé"
    CATEGORY = "Réglage"
    HORS_MATIERE = True
    DESCRIPTION = ("Palpe Z et retient la mesure; sur la pièce "
                   "suivante, propose de la reprendre sans repalper")
    ICON = "ruler"
    INLINE = False
    REQUIRES_TOOL = False
    REQUIRES_COORDINATES = True

    #: type de la liste de mesures, tel que déclaré par la machine
    TYPE_MESURE = "MeasuringCommonValues::MeasuringDataWithInfo[]"

    MESSAGE_DEFAUT = ("Un palpage enregistre existe. Le reprendre "
                      "sans repalper ?")

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return [
            ParameterDef("message", "Question opérateur",
                         ParameterType.STRING,
                         default=cls.MESSAGE_DEFAUT, unit="",
                         group="Reprise",
                         tooltip="Posée seulement s'il existe une "
                                 "mesure enregistrée. Sans accents: "
                                 "charset machine."),
            ParameterDef("mode", "Comportement", ParameterType.CHOICE,
                         default="Demander",
                         choices=["Demander", "Toujours reprendre",
                                  "Toujours repalper"],
                         unit="", group="Reprise",
                         tooltip="« Toujours reprendre » ne palpe que "
                                 "la première fois; « Toujours "
                                 "repalper » ignore l'enregistrement."),
            ParameterDef("forget_after", "Oublier en fin de programme",
                         ParameterType.BOOL, default=False, unit="",
                         group="Reprise",
                         tooltip="deletesavedvalueof après l'usinage: "
                                 "la pièce suivante repalpera. À "
                                 "cocher si le brut change."),

            ParameterDef("approach_z", "Z d'approche",
                         ParameterType.FLOAT, default=15.0,
                         min_value=0.0, max_value=200.0, unit="mm",
                         group="Palpage"),
            ParameterDef("origin_z_shift", "Décalage Z de l'origine",
                         ParameterType.FLOAT, default=0.0,
                         min_value=-200.0, max_value=200.0, unit="mm",
                         group="Palpage",
                         tooltip="originZShift du SurfaceMeasure"),
            ParameterDef("stock_offset", "Surépaisseur",
                         ParameterType.FLOAT, default=0.0,
                         min_value=-200.0, max_value=200.0, unit="mm",
                         group="Palpage",
                         tooltip="stockOffset: matière laissée "
                                 "au-dessus de la cote mesurée"),

            ParameterDef("variable", "Variable persistée",
                         ParameterType.STRING,
                         default="dernierPalpage", unit="",
                         group="Expert", expert_only=True,
                         tooltip="Nom de la variable module. Deux "
                                 "opérations qui partagent ce nom "
                                 "partagent la mesure."),
        ]

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        return ToolRequirement(
            tool_types=[],
            description="Palpeur ou outil en place (aucun changement)")

    # ── Déclarations au niveau MODULE ──

    @classmethod
    def variable_name(cls, params: Dict[str, Any]) -> str:
        """Nom de la variable persistée, assaini."""
        brut = str(params.get('variable', '') or 'dernierPalpage')
        propre = "".join(c for c in brut.strip()
                         if c.isalnum() or c == '_')
        return propre or "dernierPalpage"

    @classmethod
    def declared_variables(cls, params: Dict[str, Any]) -> List[tuple]:
        """(nom, type) à déclarer hors de tout program."""
        return [(cls.variable_name(params), cls.TYPE_MESURE)]

    # ── Code ──

    @classmethod
    def generate_program(cls, params: Dict[str, Any],
                         prog_name: str, x: float = 0.0,
                         y: float = 0.0) -> str:
        """Sous-programme complet: question, reprise ou palpage."""
        p = {**cls.get_default_params(), **params}
        var = cls.variable_name(p)
        mode = str(p.get('mode', 'Demander'))

        def _f(cle, defaut=0.0):
            try:
                return float(p.get(cle, defaut) or 0.0)
            except (TypeError, ValueError):
                return float(defaut)

        # Indentation des blocs: la machine ne l'exige pas, mais on
        # relit ce programme sur son ecran, sans coloration
        def _mesure(marge: str) -> list:
            return [
                f"{marge}{var} = {{ }}",
                f"{marge}PrePositioning X={x:.3f} Y={y:.3f} "
                f"Z={_f('approach_z', 15.0):g}",
                f"{marge}mesure = SurfaceMeasure resultCs=CsType.Wcs "
                f"originZShift={_f('origin_z_shift'):g} "
                f"stockOffset={_f('stock_offset'):g}",
                f"{marge}append mesure to {var}",
                f"{marge}savevalueof {var}",
            ]

        lignes = [f"program {prog_name}"]
        if mode == "Toujours repalper":
            # L'enregistrement sert quand même aux opérations
            # suivantes qui, elles, peuvent le reprendre
            lignes.extend(_mesure("    "))
        else:
            lignes.append("    reprise:DialogResult = DialogResult.No")
            lignes.append(f"    if {var} hassavedvalue")
            if mode == "Toujours reprendre":
                lignes.append("        reprise = DialogResult.Yes")
            else:
                lignes.append(
                    f'        reprise = Dialog '
                    f'message="{cls._message(p)}" Yes=true No=true')
            lignes.append("    endif")
            lignes.append("    if reprise == DialogResult.Yes")
            lignes.append(f"        loadvalueof {var}")
            lignes.append("    else")
            lignes.extend(_mesure("        "))
            lignes.append("    endif")
        # Reprise comme palpage neuf: la mesure retenue devient
        # l'origine programme
        lignes.append(f"    foreach mesure in {var}")
        lignes.append(
            "        SetWcs Z=mesure.MeasuredTransformation."
            "TranslationZ")
        lignes.append("    endforeach")
        lignes.append("endprogram")
        return "\n".join(lignes)

    @classmethod
    def generate_forget_line(cls, params: Dict[str, Any]) -> str:
        """Ligne d'oubli, posée en fin de Main si demandée."""
        p = {**cls.get_default_params(), **params}
        if not p.get('forget_after'):
            return ""
        return f"    deletesavedvalueof {cls.variable_name(p)}"

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        """L'opération vit dans son sous-programme (INLINE = False)."""
        return ""

    @staticmethod
    def _message(p: Dict[str, Any]) -> str:
        from src.codegen.generator import strip_accents
        brut = str(p.get('message', '') or PalpageMemorise.MESSAGE_DEFAUT)
        return strip_accents(brut).replace('"', "'")
