"""Opération: Bloc SimPl importé.

Un sous-programme issu d'un fichier SimPl externe, chargé dans la
liste d'opérations habituelle pour être réordonné, mis en sourdine et
réglé comme n'importe quelle opération NeoDrive.

Point important: l'unité chargée est le SOUS-PROGRAMME, pas la
séquence. Un sous-programme Datron contient soit une fonction
d'usinage, soit un appel de séquence — dans ce dernier cas le bloc
$$$ correspondant voyage AVEC lui (`sequence_code`), car une séquence
seule n'a ni outil, ni régime, ni avances: elle ne s'usine pas.

Le code du bloc est conservé tel quel (`body`) et réémis à
l'identique, hormis les valeurs que l'utilisateur modifie
explicitement (outil, régime, profondeurs, passe Z).
"""

import re
from typing import List, Dict, Any
from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement
)
from src.operations.registry import OperationRegistry


@OperationRegistry.register("bloc_simpl")
class BlocSimpl(AbstractOperation):
    OP_TYPE = "bloc_simpl"
    DISPLAY_NAME = "Bloc SimPl importé"
    CATEGORY = "Utilitaire"
    EXPERT_ONLY = True
    DESCRIPTION = ("Sous-programme d'un SimPl externe, éditable comme "
                   "une opération")
    ICON = "external"
    INLINE = False
    REQUIRES_TOOL = False        # l'outil est déjà dans le bloc
    REQUIRES_COORDINATES = False
    SUPPORTS_MULTI_POINT = False
    #: ce que l'import a lu du fichier d'origine: la fiche du bloc le
    #: compare aux réglages, et l'appel en motif se réémet — perdus à
    #: l'enregistrement, un bloc appelé 2 × 2 n'usinait plus qu'une
    #: pièce une fois le projet rouvert
    PARAMS_DURABLES = ('_kind', '_function', '_tool', '_tool_comment',
                       '_article', '_rpm_origin', '_feeds', '_params',
                       '_call', '_descriptions', '_modules')

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return [
            # sub_name / source_file ne sont PAS exposés: ils sont
            # déjà affichés en tête de la fiche du bloc
            ParameterDef("rpm", "Rpm", ParameterType.INT,
                         default=0, min_value=0, max_value=100000,
                         unit="tr/min", group="Usinage",
                         tooltip="Régime du bloc (ligne Rpm ou "
                                 "newRpm de la déclaration d'outil).\n"
                                 "0 = laisser la valeur d'origine."),
            ParameterDef("feed_finishing", "Finition",
                         ParameterType.INT, default=0,
                         min_value=0, max_value=99999,
                         unit="mm/min", group="Avances",
                         tooltip="SetFeedTechnology du bloc. "
                                 "0 = valeur d'origine."),
            ParameterDef("feed_approach", "Approche",
                         ParameterType.INT, default=0,
                         min_value=0, max_value=99999,
                         unit="mm/min", group="Avances"),
            ParameterDef("feed_plunge", "Plongée", ParameterType.INT,
                         default=0, min_value=0, max_value=99999,
                         unit="mm/min", group="Avances"),
            ParameterDef("feed_ramp", "Rampe", ParameterType.INT,
                         default=0, min_value=0, max_value=99999,
                         unit="mm/min", group="Avances"),
            ParameterDef("feed_roughing", "Ébauche",
                         ParameterType.INT, default=0,
                         min_value=0, max_value=99999,
                         unit="mm/min", group="Avances"),
            # Retoucher les cotes d'un programme déjà validé est un
            # geste d'expert: le bloc a été calculé par la CAO
            ParameterDef("depth_scale", "Profondeurs ×",
                         ParameterType.FLOAT, default=1.0,
                         min_value=0.01, max_value=10.0,
                         group="Usinage", expert_only=True,
                         tooltip="Multiplie les profondeurs du bloc"),
            ParameterDef("depth_offset", "Profondeurs +",
                         ParameterType.FLOAT, default=0.0,
                         min_value=-100.0, max_value=100.0, unit="mm",
                         group="Usinage", expert_only=True),
            ParameterDef("infeed_scale", "Passe Z ×",
                         ParameterType.FLOAT, default=1.0,
                         min_value=0.01, max_value=10.0,
                         group="Usinage", expert_only=True,
                         tooltip="Multiplie la prise de passe en Z"),
            ParameterDef("seq_z_max", "Z final séquence",
                         ParameterType.FLOAT, default=0.0,
                         min_value=-200.0, max_value=0.0, unit="mm",
                         group="Séquence", expert_only=True,
                         tooltip="Profondeur finale voulue "
                                 "(0 = inchangée).\n"
                                 "Moins profond: les passes trop "
                                 "basses sont commentées et la "
                                 "dernière passe conservée est ramenée "
                                 "à cette cote — elle est donc "
                                 "réellement atteinte.\n"
                                 "Plus profond: des passes sont "
                                 "ajoutées au pas des précédentes."),
            ParameterDef("seq_z_offset", "Z séquence +",
                         ParameterType.FLOAT, default=0.0,
                         min_value=-100.0, max_value=100.0, unit="mm",
                         group="Séquence", expert_only=True,
                         tooltip="Décale les Z ≤ 0 de la séquence "
                                 "appelée (les dégagements sont "
                                 "préservés)"),
        ]

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        return ToolRequirement(tool_types=[],
                               description="Outil défini dans le bloc")

    # ── Code du bloc ──

    #: champs du formulaire ↔ mots-clés SetFeedTechnology
    FEED_KEYS = {
        'feed_finishing': 'finishing', 'feed_approach': 'approach',
        'feed_plunge': 'plunge', 'feed_ramp': 'ramp',
        'feed_roughing': 'roughing',
    }

    @classmethod
    def feeds(cls, params: Dict[str, Any]) -> Dict[str, int]:
        """Avances renseignées dans le formulaire (0 = d'origine)."""
        out = {}
        for field, key in cls.FEED_KEYS.items():
            try:
                val = int(float(params.get(field, 0) or 0))
            except (TypeError, ValueError):
                val = 0
            if val > 0:
                out[key] = val
        return out

    @classmethod
    def effective_name(cls, params: Dict[str, Any]) -> str:
        """Nom du sous-programme après renommage éventuel."""
        from src.codegen.generator import _clean_name
        wanted = str(params.get('_name', '') or '').strip()
        origin = str(params.get('sub_name', '') or 'Bloc').strip()
        if not wanted:
            return origin
        clean = _clean_name(wanted)
        return clean or origin

    @classmethod
    def body(cls, params: Dict[str, Any]) -> str:
        """Corps du sous-programme, réglages utilisateur appliqués."""
        from src.io import simpl_batch as sb
        code = str(params.get('body', '') or '')
        if not code.strip():
            return ""
        name = str(params.get('sub_name', '') or 'Bloc')
        # Outil de remplacement choisi par l'utilisateur
        article = str(params.get('tool_article', '') or '').strip()
        if article:
            code, _ = sb.set_subprogram_tool(
                code, name, article,
                tool_name=str(params.get('tool_label', '') or ''))
        rpm = int(params.get('rpm', 0) or 0)
        if rpm > 0:
            code, _ = sb.set_subprogram_rpm(code, name, rpm)
        feeds = cls.feeds(params)
        if feeds:
            code, _ = sb.set_subprogram_feeds(code, name, feeds)
        # Renommage: l'opération est renommée dans la liste, le bloc
        # doit suivre PARTOUT (program, BeginBlock, appels)
        new_name = cls.effective_name(params)
        if new_name != name:
            code, _ = sb.rename_subprogram(code, name, new_name)
        d_scale = float(params.get('depth_scale', 1.0) or 1.0)
        d_off = float(params.get('depth_offset', 0.0) or 0.0)
        if d_scale != 1.0 or d_off != 0.0:
            code, _ = sb.adjust_depths(code, offset=d_off,
                                       scale=d_scale, program=name)
        i_scale = float(params.get('infeed_scale', 1.0) or 1.0)
        if i_scale != 1.0:
            code, _ = sb.adjust_depths(code, scale=i_scale,
                                       program=name,
                                       keys=("infeedZ",))
        code, _ = sb.rename_sequence(code, *cls._noms_de_sequence(params))
        return code

    @staticmethod
    def _noms_de_sequence(params: Dict[str, Any]):
        """(nom d'origine, nom émis) de sa séquence: le générateur
        donne un nom unique (`_sequence_unique`) quand deux opérations
        portent la même — un bloc copié, deux programmes réunis."""
        origine = str(params.get('sequence_name', '') or '').strip()
        unique = str(params.get('_sequence_unique', '') or '').strip()
        return origine, (unique or origine)

    @classmethod
    def sequence_block(cls, params: Dict[str, Any]) -> str:
        """Bloc $$$ appelé par ce sous-programme, Z ajustés."""
        from src.io import simpl_batch as sb
        seq = str(params.get('sequence_code', '') or '')
        if not seq.strip():
            return ""
        # Profondeur finale AVANT l'offset: la cote saisie est celle
        # que l'utilisateur lit sur la séquence d'origine
        z_max = float(params.get('seq_z_max', 0.0) or 0.0)
        if z_max < 0:
            seq, _ = sb.set_sequence_depth(
                seq, z_max,
                sequence=str(params.get('sequence_name', '')))
        offset = float(params.get('seq_z_offset', 0.0) or 0.0)
        if offset != 0.0:
            seq, _ = sb.adjust_sequence_z(
                seq, sequence=str(params.get('sequence_name', '')),
                offset=offset)
        origine, unique = cls._noms_de_sequence(params)
        # sans sa ligne « $$$ NOM », la séquence se collerait au bloc
        # précédent: le programme appellerait une séquence absente
        if origine and not seq.lstrip().startswith('$$$'):
            seq = f"$$$ {origine}\n" + seq.lstrip('\n')
        seq, _ = sb.rename_sequence(seq, origine, unique)
        return seq

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        """Dans Main: l'appel du sous-programme (nom effectif)."""
        return f"    {cls.effective_name(params)}"

    @classmethod
    def appel_main(cls, params: Dict[str, Any], nom: str) -> str:
        """L'appel du bloc dans Main, sous le nom effectif `nom`: le motif
        du fichier d'origine (« Pattern::RectanglePattern xCount=2 …
        callProgram=X ») quand le Main l'appelait ainsi — réduit au nom
        seul, une seule pièce du motif était usinée (et montrée au Canva
        3D) —, sinon le nom seul."""
        appel = str(params.get('_call', '') or '').strip()
        origine = str(params.get('sub_name', '') or '')
        m = re.search(r'callProgram\s*=\s*"?(\w+)', appel)
        if appel.startswith('Pattern::') and m and m.group(1) == origine:
            return "    " + appel[:m.start(1)] + nom + appel[m.end(1):]
        return f"    {nom}"

    @classmethod
    def validate_params(cls, params: Dict[str, Any]) -> List[str]:
        errors = []
        if not str(params.get('body', '') or '').strip():
            errors.append("Bloc vide (code source manquant)")
        return errors
