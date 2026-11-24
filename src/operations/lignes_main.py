"""Opération: Lignes du Main — inline.

Un programme importé en blocs qui grave, attend l'opérateur ou décale
son origine DANS son Main (gravures sur un chant, Dialog entre deux
positions de la pièce, ShiftWcsInc, `if … endif` autour des appels):
ces lignes repartent telles quelles, à leur place, entre les blocs.
L'import n'en gardait que les appels de sous-programmes — la gravure
disparaissait du Canva 3D comme de la machine.

Elles restent dans le Main (pas de sous-programme): un `if` ouvert
avant un appel et fermé après lui garde ainsi sa forme d'origine.
"""

import re
import textwrap
from typing import List, Dict, Any
from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement
)
from src.operations.registry import OperationRegistry


@OperationRegistry.register("lignes_main")
class LignesMain(AbstractOperation):
    DISPLAY_NAME = "Lignes du Main"
    CATEGORY = "Utilitaire"
    DESCRIPTION = ("Lignes SimPl écrites telles quelles dans le Main "
                   "(reprises d'un programme importé)")
    ICON = "custom"
    EXPERT_ONLY = True
    INLINE = True
    REQUIRES_TOOL = False
    REQUIRES_COORDINATES = False
    SUPPORTS_MULTI_POINT = False
    #: les programmes et usermodule du fichier d'origine que les
    #: lignes nomment ({nom: corps}, lignes « usermodule … »)
    PARAMS_DURABLES = ('_programmes', '_usermodules', '_descriptions',
                       '_outil_en_place', '_modules')

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return [
            ParameterDef("code", "Lignes", ParameterType.STRING,
                         default="", unit="", group="Code",
                         multiline=True,
                         tooltip="Écrites telles quelles dans le Main, "
                                 "à la place de l'opération dans la "
                                 "liste."),
        ]

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        return ToolRequirement(tool_types=[],
                               description="Aucun outil requis")

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        texte = textwrap.dedent(
            str(params.get('code', '') or '').expandtabs(4))
        lignes = ["    " + l.rstrip() for l in texte.split('\n')
                  if l.strip()]
        return "\n".join(lignes) if lignes \
            else "    # Lignes du Main (vides)"

    #: commandes d'entretien du Main: seules, elles ne font pas une
    #: opération (le Main généré les écrit lui-même)
    ENTRETIEN = ('Absolute', 'SpraySystem', 'Spindle',
                 'MoveToParkPosition', 'Relative')

    @staticmethod
    def mettre_en_forme(instructions: List[str]) -> str:
        """Les instructions lues dans le Main, remises au propre: la
        première ligne de chacune au bord, ses lignes suivantes (les
        paramètres d'un Engrave ( … )) en retrait, la parenthèse
        fermante au bord. Les fichiers de l'atelier mêlent tabulations,
        retraits de 4 et de 9 espaces, et commentaires en colonne 0."""
        out = []
        for instruction in instructions:
            for k, ligne in enumerate(instruction.split('\n')):
                s = ligne.strip()
                if s:
                    out.append(s if k == 0 or s.startswith(')')
                               else "    " + s)
        return "\n".join(out)

    @classmethod
    def utile(cls, lignes: List[str]) -> bool:
        """Les lignes font-elles autre chose que l'entretien du Main
        (arrosage, broche, parking) ?"""
        for l in lignes:
            s = l.strip()
            if s and not s.startswith('#') \
                    and s.split()[0] not in cls.ENTRETIEN:
                return True
        return False

    @classmethod
    def nom_pour(cls, lignes: List[str]) -> str:
        """Un nom qui dit ce que font les lignes: la pause, la gravure,
        le décalage, le test — sinon la première ligne utile."""
        # un « #Dialog ( » mis en sourdine ne nomme rien
        code = "\n".join(l for l in "\n".join(lignes).split('\n')
                         if not l.strip().startswith('#'))
        parties = []
        m = re.search(r'\bDialog\b[^)]*?caption\s*=\s*"([^"]*)"', code,
                      re.DOTALL)
        if m:
            parties.append(f"Pause : {m.group(1).strip()}")
        m = re.search(r'Engrave::\w+[^)]*?\btext\s*=\s*"([^"]*)"', code,
                      re.DOTALL)
        if m:
            parties.append(f"Gravure {m.group(1).strip()}")
        m = re.search(r'^\s*(ShiftWcsInc[^\n#]*)', code, re.MULTILINE)
        if m:
            parties.append(" ".join(m.group(1).split()))
        m = re.search(r'^\s*(if\b[^\n#]*)', code, re.MULTILINE)
        if m:
            parties.append(" ".join(m.group(1).split()))
        elif re.search(r'^\s*endif\b', code, re.MULTILINE):
            parties.append("endif")
        if not parties:
            for l in lignes:
                s = l.strip()
                if s and not s.startswith('#') \
                        and s.split()[0] not in cls.ENTRETIEN:
                    parties.append(" ".join(s.split()))
                    break
        nom = " · ".join(parties[:2]) or cls.DISPLAY_NAME
        return nom if len(nom) <= 60 else nom[:59] + "…"

    #: {(lignes, diamètres): parcours} — le Canva redessine souvent
    _PARCOURS: Dict[tuple, Any] = {}

    @classmethod
    def parcours(cls, params: Dict[str, Any], diametres=None):
        """Le parcours simulé de ces lignes seules (une gravure du Main
        importé), depuis l'état initial de la machine, avec les
        programmes du fichier qu'elles appellent; None si elles ne
        bougent pas. Le Canva le dessine: la 3D, elle, simule le
        programme entier."""
        code = str(params.get('code', '') or '')
        if not code.strip():
            return None
        programmes = [str(c) for c in
                      (params.get('_programmes') or {}).values()]
        cle = (code, tuple(programmes),
               tuple(sorted((diametres or {}).items())))
        if cle in cls._PARCOURS:
            return cls._PARCOURS[cle]
        from src.core import sim_cycles
        try:
            res = sim_cycles.simuler(
                "export program Main\n" + code + "\nendprogram\n"
                + "\n".join(programmes), diametres)
        except Exception:
            res = None
        if res is not None and len(res.get('x') or []) < 2:
            res = None
        if len(cls._PARCOURS) > 64:
            cls._PARCOURS.clear()
        cls._PARCOURS[cle] = res
        return res

    @staticmethod
    def outil(params: Dict[str, Any], res, tool_library=None):
        """(référence, nom) du premier outil que prend leur parcours. Le
        Main l'écrit souvent par son nom (`Tool name="…"`): la référence
        vient alors de tools.json, sinon de sa @ ToolDescription @. Des
        lignes qui n'en prennent pas gravent avec celui qu'une ligne
        précédente a mis en broche (relevé à l'import)."""
        pris = next((o for o in ((res or {}).get('outil') or []) if o),
                    "") or str(params.get('_outil_en_place', '') or '')
        if not pris:
            return "", ""
        if tool_library is not None:
            t = tool_library.get_tool_by_article(pris) or next(
                (t for t in tool_library.get_all_tools() if t.name == pris),
                None)
            if t is not None:
                return (t.article_nr or pris), t.name
        desc = str((params.get('_descriptions') or {}).get(pris, '') or '')
        ref = re.search(r'"ArticleNr"\s*:\s*"([^"]+)"', desc)
        nom = re.search(r'"Name"\s*:\s*"([^"]+)"', desc)
        return ((ref.group(1) if ref else pris),
                (nom.group(1) if nom else pris))
