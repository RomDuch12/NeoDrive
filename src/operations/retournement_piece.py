"""Opération: Retournement de pièce (park + question opérateur).

Reprise du motif vu dans les programmes de la machine: on choisit un
outil COURT, on coupe arrosage et broche, on part en position de
parking, et on demande à l'opérateur de retourner la pièce et de
palper sa nouvelle origine. Ce qui suit dans le programme n'est
exécuté que s'il répond Oui.

  program Retournement_xxx returns DialogResult
      Tool type="0068460Y"  skipRestoring
      SpraySystem Off
      Spindle Off
      MoveToParkPosition
      result = Dialog message="…" Yes=true No=true
      return result
  endprogram

Le choix de l'outil compte: c'est lui qui reste en broche pendant la
manipulation, et un outil long gêne l'accès à la pièce.
"""

from typing import List, Dict, Any

from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement
)
from src.operations.registry import OperationRegistry
from src.operations.palpage_rectangle import (
    PalpageRectangle, parametres_palpage)


@OperationRegistry.register("retournement_piece")
class RetournementPiece(AbstractOperation):
    OP_TYPE = "retournement_piece"
    DISPLAY_NAME = "Retournement pièce"
    CATEGORY = "Réglage"
    HORS_MATIERE = True
    DESCRIPTION = ("Park + question opérateur: retourner la pièce et "
                   "palper la nouvelle origine")
    ICON = "dialog"
    INLINE = True
    #: l'outil est FACULTATIF: retourner une pièce ne demande pas
    #: d'usiner. On en monte un quand celui qui est en broche gêne
    #: la manipulation — c'est alors un choix, pas une obligation.
    REQUIRES_TOOL = False
    REQUIRES_COORDINATES = False

    #: message par défaut, réécrit par l'utilisateur
    MESSAGE_DEFAUT = ("Retourner la piece, palper l'origine, "
                      "puis continuer ?")

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return [
            ParameterDef("message", "Message opérateur",
                         ParameterType.STRING,
                         default=cls.MESSAGE_DEFAUT, unit="",
                         group="Dialogue",
                         tooltip="Texte affiché sur le pupitre. Sans "
                                 "accents: la machine est en jeu de "
                                 "caractères allemand."),
            ParameterDef("changer_outil",
                         "Monter l'outil choisi avant la question",
                         ParameterType.BOOL, default=False, unit="",
                         group="Dialogue",
                         tooltip="Coché, l'outil sélectionné est monté "
                                 "AVANT le message: c'est lui qui "
                                 "reste en broche pendant que "
                                 "l'opérateur manipule la pièce.\n"
                                 "Décoché, l'outil en place ne bouge "
                                 "pas."),
            ParameterDef("park", "Aller en position de parking",
                         ParameterType.BOOL, default=True, unit="",
                         group="Dialogue",
                         tooltip="Dégage la broche pour laisser "
                                 "l'accès à la pièce"),
            ParameterDef("stop_if_no", "Non = arrêter le programme",
                         ParameterType.BOOL, default=True, unit="",
                         group="Dialogue",
                         tooltip="Coché, tout ce qui suit est dans le "
                                 "if: répondre Non termine le "
                                 "programme."),
            ParameterDef("spray_off", "Couper l'arrosage",
                         ParameterType.BOOL, default=True, unit="",
                         group="Options", expert_only=True),
            ParameterDef("spindle_off", "Couper la broche",
                         ParameterType.BOOL, default=True, unit="",
                         group="Options", expert_only=True),

        ] + parametres_palpage()

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        return ToolRequirement(
            tool_types=[],
            description="Facultatif — outil laissé en broche pendant "
                        "la manipulation")

    @classmethod
    def _corps(cls, p: Dict[str, Any]) -> List[str]:
        """Lignes communes: outil, arrosage, broche, parking."""
        lignes = []
        article = str(p.get('_tool_article', '') or '').strip()
        if article and p.get('changer_outil', False):
            commentaire = str(p.get('_tool_name', '') or '').strip()
            suffixe = f"    #{commentaire}" if commentaire else ""
            lignes.append(f'    Tool type="{article}"  skipRestoring'
                          f'{suffixe}')
        if p.get('spray_off', True):
            lignes.append("    SpraySystem Off")
        if p.get('spindle_off', True):
            lignes.append("    Spindle Off")
        if p.get('park', True):
            lignes.append("    MoveToParkPosition")
        return lignes

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        """Corps inline (sans le if): utilisé quand « Non » n'arrête
        pas le programme."""
        p = {**cls.get_default_params(), **params}
        message = cls._message(p)
        lignes = cls._corps(p)
        lignes.append(f'    Dialog (')
        lignes.append(f'    caption="Retournement de piece"')
        lignes.append(f'    message="{message}"')
        lignes.append(f'    )')
        return "\n".join(lignes)

    @classmethod
    def generate_askfor_program(cls, params: Dict[str, Any],
                                prog_name: str = "Retournement") -> str:
        """Sous-programme qui rend la réponse de l'opérateur."""
        p = {**cls.get_default_params(), **params}
        lignes = [f"program {prog_name} returns DialogResult"]
        lignes.extend(cls._corps(p))
        lignes.append(
            f'    result = Dialog message="{cls._message(p)}" '
            f'Yes=true No=true')
        lignes.append("    return result")
        lignes.append("endprogram")
        return "\n".join(lignes)

    # ── Palpage du brut retourné ──
    # Une seule implémentation: celle de « Palpage rectangle ».

    @classmethod
    def probe_program_name(cls, params: Dict[str, Any]) -> str:
        return PalpageRectangle.program_name(params)

    @classmethod
    def rotation_distance(cls, params: Dict[str, Any]) -> float:
        return PalpageRectangle.rotation_distance(params)

    @classmethod
    def rotation_axis(cls, params: Dict[str, Any]) -> str:
        return PalpageRectangle.rotation_axis(params)

    @classmethod
    def generate_probe_program(cls, params: Dict[str, Any],
                               prog_name: str = "") -> str:
        return PalpageRectangle.generate_probe_program(
            params, prog_name or cls.probe_program_name(params))

    @staticmethod
    def _message(p: Dict[str, Any]) -> str:
        """Message nettoyé: la machine n'affiche pas les accents."""
        from src.codegen.generator import strip_accents
        brut = str(p.get('message', '') or
                   RetournementPiece.MESSAGE_DEFAUT)
        return strip_accents(brut).replace('"', "'")
