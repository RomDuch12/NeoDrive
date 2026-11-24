"""
Gestion des templates de projet NeoDrive (.ndpt).
Un template sauvegarde les réglages projet + opérations prédéfinies.
"""

import json
import os
from datetime import datetime
from typing import List, Dict
from src.core.program_model import ProgramModel, OperationInstance, ProjectSettings
from src.core.tool_library import ToolLibrary, get_base_dir
from src.operations.registry import OperationRegistry


def _templates_dir() -> str:
    d = os.path.join(get_base_dir(), 'data', 'templates')
    os.makedirs(d, exist_ok=True)
    return d


def list_templates() -> List[Dict]:
    """Retourne la liste des templates disponibles.
    Chaque élément: {name, description, filepath, op_count, modified}
    """
    result = []
    tdir = _templates_dir()
    for fname in sorted(os.listdir(tdir)):
        if not fname.endswith('.ndpt'):
            continue
        fpath = os.path.join(tdir, fname)
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            result.append({
                'name': data.get('name', fname.replace('.ndpt', '')),
                'description': data.get('description', ''),
                'filepath': fpath,
                'op_count': len(data.get('operations', [])),
                'modified': data.get('modified', ''),
            })
        except Exception:
            continue
    return result


def save_template(program: ProgramModel, name: str,
                  description: str = "") -> str:
    """Sauvegarde le programme courant comme template.
    Retourne le chemin du fichier créé."""
    data = {
        'format_version': '1.0',
        'type': 'template',
        'name': name,
        'description': description,
        'modified': datetime.now().isoformat(),
        'settings': program.settings.to_dict(),
        'operations': [op.to_dict() for op in program.operations],
    }
    safe_name = "".join(c if c.isalnum() or c in (' ', '-', '_')
                        else '_' for c in name).strip()
    filepath = os.path.join(_templates_dir(), f"{safe_name}.ndpt")
    from src.core.fichiers_surs import ecrire_json_sur
    ecrire_json_sur(filepath, data, indent=2, ensure_ascii=False)
    return filepath


def load_template(filepath: str, tool_library: ToolLibrary) -> ProgramModel:
    """Charge un template et retourne un ProgramModel (nouveau, non-sauvegardé)."""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    program = ProgramModel()
    program.settings = ProjectSettings.from_dict(data.get('settings', {}))

    for op_data in data.get('operations', []):
        op = OperationInstance.from_dict(op_data)
        try:
            OperationRegistry.get(op.operation_type)
        except KeyError:
            continue
        if op.tool_id and op.tool_id not in tool_library.tools:
            op.tool_id = ""
        program.add_operation(op)

    from src.core.program_model import expand_legacy_instances
    expand_legacy_instances(program)
    return program


def delete_template(filepath: str) -> bool:
    """Supprime un template. Retourne True si réussi."""
    try:
        os.remove(filepath)
        return True
    except Exception:
        return False
