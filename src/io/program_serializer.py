"""
Sérialisation/désérialisation des programmes et sous-programmes.
Formats: .ndp (programme complet), .nds (sous-programme réutilisable)
"""

import json
from datetime import datetime
from typing import List
from src.core.program_model import ProgramModel, OperationInstance
from src.core.tool_library import ToolLibrary


class ProgramSerializer:
    """Sauvegarde/chargement de programmes .ndp — et .nds.

    Les deux extensions portent le MÊME format: un JSON avec
    `operations`, `settings` (le brut, l'origine) et `description`.
    Elles ne disent que l'intention: .ndp est un programme qu'on
    ouvre, .nds un sous-programme qu'on insère dans un autre. L'un
    comme l'autre s'ouvrent dans un onglet, se modifient, et se
    réenregistrent par Ctrl+S sous leur nom — c'est ce qui manquait
    au .nds, qu'il fallait insérer, modifier, puis réenregistrer
    « comme sous-programme » sous le même nom."""

    @staticmethod
    def genre_du_fichier(filepath: str) -> str:
        """« program » ou « subprogram », d'après l'extension."""
        return ("subprogram" if str(filepath).lower().endswith('.nds')
                else "program")

    @staticmethod
    def save(program: ProgramModel, filepath: str) -> None:
        data = program.to_dict()
        data['type'] = ProgramSerializer.genre_du_fichier(filepath)
        from src.core.fichiers_surs import ecrire_json_sur
        # jamais à moitié écrit: une coupure pendant l'enregistrement
        # laisse l'ancienne version entière
        ecrire_json_sur(filepath, data, indent=2, ensure_ascii=False)
        program.filepath = filepath
        program.mark_saved()

    @staticmethod
    def load(filepath: str, tool_library: ToolLibrary) -> ProgramModel:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # rien de ce que cette version ne connaît n'est perdu: outil
        # absent du poste, opération d'un type inconnu, champ inconnu
        # se réécrivent à l'enregistrement (ouvrir puis Ctrl+S les
        # effaçait en silence)
        from src.core.program_model import programme_depuis_dict
        program = programme_depuis_dict(data, tool_library.tools)

        # Anciennes « instances similaires » → membres d'ensemble
        from src.core.program_model import expand_legacy_instances
        expand_legacy_instances(program)

        program.filepath = filepath
        program.mark_saved()
        return program


class SubProgramSerializer:
    """Sauvegarde/chargement de sous-programmes .nds"""

    @staticmethod
    def save(operations: List[OperationInstance], filepath: str,
             description: str = "") -> None:
        data = {
            "format_version": "1.0",
            "type": "subprogram",
            "description": description,
            "created": datetime.now().isoformat(),
            "operations": [op.dict_fichier() for op in operations],
        }
        from src.core.fichiers_surs import ecrire_json_sur
        # le sous-programme remplacé reste en .bak
        ecrire_json_sur(filepath, data, garder_bak=True, indent=2,
                        ensure_ascii=False)

    @staticmethod
    def load(filepath: str,
             tool_library: ToolLibrary) -> List[OperationInstance]:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        from src.core.program_model import operation_depuis_dict
        operations = []
        for op_data in data.get("operations", []):
            if not isinstance(op_data, dict):
                continue
            # l'outil absent du poste reste en `outil_absent`
            op = operation_depuis_dict(op_data, tool_library.tools)
            if op is not None:
                operations.append(op)
        return operations


class SimPlExporter:
    """Export du code SimPl vers fichier .SimPl"""

    @staticmethod
    def export(program: ProgramModel, tool_library: ToolLibrary,
               filepath: str,
               path_replace_from: str = "",
               path_replace_to: str = "",
               expert_settings: dict = None) -> None:
        from src.codegen.generator import SimPlGenerator
        generator = SimPlGenerator(
            program, tool_library, path_replace_from, path_replace_to,
            expert_settings=expert_settings)
        code = generator.generate()

        if not filepath.lower().endswith('.simpl'):
            filepath += '.SimPl'

        # d'un coup (jamais à moitié écrit, même coupé en route), et
        # le programme qu'on remplace reste en .bak
        from src.core.fichiers_surs import ecrire_texte_sur
        ecrire_texte_sur(filepath, code, garder_bak=True)

    @staticmethod
    def get_default_filename(program: ProgramModel,
                             tab_name: str = "") -> str:
        timestamp = datetime.now().strftime("%y%m%d-%H%M")
        author = program.settings.author or ""
        parts = ["Neodrive"]
        if tab_name:
            parts.append(tab_name)
        if author:
            parts.append(author)
        parts.append(timestamp)
        return " - ".join(parts) + ".SimPl"
