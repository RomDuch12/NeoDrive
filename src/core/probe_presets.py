"""Tailles de brut à palper, enregistrées d'une fois sur l'autre.

Une série revient: le même brut se repalpe la semaine suivante. Retaper les cotes à chaque programme est le genre de saisie
où l'on se trompe d'un millimètre sans s'en apercevoir.

Fichier: `data/probe_presets.json`
    [{"name": "Barre 100x20", "width_x": 100.0, "width_y": 20.0,
      "probe_depth": 5.0, "probe_safe_z": 5.0}, …]
"""

import os
from typing import List, Dict

from src.core.tool_library import get_base_dir

FICHIER = "probe_presets.json"

#: livrés avec l'application, tant que l'utilisateur n'a rien posé
DEFAUTS = [
    {"name": "Barre 100 x 20", "width_x": 100.0, "width_y": 20.0,
     "probe_depth": 5.0, "probe_safe_z": 5.0},
    {"name": "Plaque 200 x 100", "width_x": 200.0, "width_y": 100.0,
     "probe_depth": 5.0, "probe_safe_z": 5.0},
    {"name": "Carré 80 x 80", "width_x": 80.0, "width_y": 80.0,
     "probe_depth": 4.0, "probe_safe_z": 5.0},
]

#: champs repris d'un preset
CHAMPS = ("width_x", "width_y", "probe_depth", "probe_safe_z")


def _chemin() -> str:
    return os.path.join(get_base_dir(), "data", FICHIER)


def charger() -> List[Dict]:
    """Presets enregistrés, ceux d'usine à défaut."""
    from src.core.fichiers_surs import lire_json
    data = lire_json(_chemin())
    if isinstance(data, list) and data:
        return [p for p in data if isinstance(p, dict) and p.get('name')]
    return [dict(p) for p in DEFAUTS]


def enregistrer(presets: List[Dict]) -> bool:
    """Écrit la liste. Rend False si le disque refuse."""
    try:
        from src.core.fichiers_surs import ecrire_json_sur
        ecrire_json_sur(_chemin(), presets, garder_bak=True, indent=2,
                        ensure_ascii=False)
        return True
    except OSError:
        return False


def ajouter(nom: str, params: Dict) -> List[Dict]:
    """Ajoute (ou remplace) un preset et rend la liste à jour."""
    nom = (nom or "").strip()
    if not nom:
        return charger()
    preset = {"name": nom}
    for cle in CHAMPS:
        try:
            preset[cle] = float(params.get(cle, 0.0) or 0.0)
        except (TypeError, ValueError):
            preset[cle] = 0.0
    presets = [p for p in charger() if p.get('name') != nom]
    presets.append(preset)
    presets.sort(key=lambda p: p.get('name', '').lower())
    enregistrer(presets)
    return presets


def supprimer(nom: str) -> List[Dict]:
    """Retire un preset et rend la liste à jour."""
    presets = [p for p in charger() if p.get('name') != nom]
    enregistrer(presets)
    return presets


def valeurs(nom: str) -> Dict:
    """Cotes du preset nommé, vide s'il n'existe pas."""
    for preset in charger():
        if preset.get('name') == nom:
            return {cle: preset.get(cle, 0.0) for cle in CHAMPS
                    if cle in preset}
    return {}
