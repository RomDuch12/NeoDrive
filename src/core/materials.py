"""
Bibliothèque de matériaux.
Fournit des multiplicateurs de vitesses/avances par matériau.
"""

import json
import os
from typing import List, Dict, Optional
from src.core.tool_library import get_base_dir


class Material:
    """Un matériau avec ses multiplicateurs."""
    def __init__(self, data: dict):
        self.id = data.get('id', '')
        self.name = data.get('name', '')
        self.category = data.get('category', '')
        self.feed_multiplier = data.get('feed_multiplier', 1.0)
        self.rpm_multiplier = data.get('rpm_multiplier', 1.0)
        self.notes = data.get('notes', '')

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'name': self.name,
            'category': self.category,
            'feed_multiplier': self.feed_multiplier,
            'rpm_multiplier': self.rpm_multiplier,
            'notes': self.notes,
        }


class MaterialsLibrary:
    """Gestion de la bibliothèque de matériaux."""

    def __init__(self):
        self._materials: Dict[str, Material] = {}
        self._filepath = os.path.join(
            get_base_dir(), 'data', 'materials.json')
        self._load()

    def _load(self):
        try:
            if os.path.exists(self._filepath):
                with open(self._filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for m_data in data.get('materials', []):
                    mat = Material(m_data)
                    self._materials[mat.id] = mat
        except Exception:
            pass

    def get_all(self) -> List[Material]:
        return list(self._materials.values())

    def get(self, material_id: str) -> Optional[Material]:
        return self._materials.get(material_id)

    def get_by_category(self) -> Dict[str, List[Material]]:
        result: Dict[str, List[Material]] = {}
        for mat in self._materials.values():
            if mat.category not in result:
                result[mat.category] = []
            result[mat.category].append(mat)
        return result

    def get_display_list(self) -> List[str]:
        """Retourne la liste des noms pour affichage dans un combo."""
        return [f"{m.name} ({m.category})" for m in self._materials.values()]

    def get_ids(self) -> List[str]:
        return list(self._materials.keys())
