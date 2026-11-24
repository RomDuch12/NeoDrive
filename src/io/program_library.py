"""Bibliothèque de programmes organisée en GROUPES.

Un atelier accumule vite des centaines de programmes: une liste plate
devient inutilisable. Les programmes sont donc rangés en groupes —
matérialisés par des SOUS-DOSSIERS de `programs/`, ce qui reste
lisible et manipulable depuis l'explorateur de fichiers, sans base de
données ni index à maintenir.

  programs/
      Platines/            ← groupe
          Platine A.ndp
          Platine B.ndp
      Supports moteur/
          ...
      Programme isolé.ndp  ← racine = groupe « (sans groupe) »
"""

import json
import os
import re
import shutil
from datetime import datetime
from typing import Dict, List, Optional

ROOT_GROUP = "(sans groupe)"
#: sous-dossiers techniques, jamais présentés comme des groupes
_HIDDEN = {"onglets_fermes", "__pycache__", "templates"}


def sanitize_group(name: str) -> str:
    """Nom de groupe utilisable comme nom de dossier."""
    cleaned = re.sub(r'[<>:"/\\|?*]', '_', str(name or '')).strip()
    return cleaned.strip('. ') or ""


def group_dir(programs_dir: str, group: str) -> str:
    """Dossier d'un groupe (la racine pour le groupe par défaut)."""
    group = sanitize_group(group)
    if not group or group == ROOT_GROUP:
        return programs_dir
    return os.path.join(programs_dir, group)


def list_groups(programs_dir: str) -> List[str]:
    """Groupes existants, triés, précédés du groupe par défaut."""
    groups = []
    try:
        for entry in sorted(os.listdir(programs_dir),
                            key=lambda s: s.lower()):
            path = os.path.join(programs_dir, entry)
            if os.path.isdir(path) and entry not in _HIDDEN \
                    and not entry.startswith('.'):
                groups.append(entry)
    except OSError:
        return [ROOT_GROUP]
    return [ROOT_GROUP] + groups


def create_group(programs_dir: str, name: str) -> str:
    """Crée un groupe et retourne son nom assaini ("" si invalide)."""
    name = sanitize_group(name)
    if not name:
        return ""
    os.makedirs(os.path.join(programs_dir, name), exist_ok=True)
    return name


def _entry(path: str, group: str) -> dict:
    """Fiche d'un programme, sans lever si le fichier est illisible."""
    info = {
        'path': path,
        'name': os.path.splitext(os.path.basename(path))[0],
        'group': group,
        'mtime': 0.0,
        'operations': 0,
        'author': '',
        'comment': '',
    }
    try:
        info['mtime'] = os.path.getmtime(path)
    except OSError:
        pass
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        info['operations'] = len(data.get('operations') or [])
        settings = data.get('settings') or {}
        info['author'] = str(settings.get('author', '') or '')
        info['comment'] = str(settings.get('comment', '') or '')
    except (OSError, ValueError):
        pass        # fichier corrompu: il reste listé, sans détail
    return info


def list_programs(programs_dir: str, group: Optional[str] = None,
                  query: str = "") -> List[dict]:
    """Programmes d'un groupe (ou de TOUS si group est None).

    `query` filtre sur le nom, le groupe, l'auteur et le commentaire —
    chercher « platine » ou un nom d'opérateur doit suffire à
    retrouver un programme sans savoir où il est rangé.
    """
    groups = ([group] if group is not None
              else list_groups(programs_dir))
    needle = query.strip().lower()
    out = []
    for grp in groups:
        folder = group_dir(programs_dir, grp)
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for fn in names:
            if not fn.lower().endswith('.ndp'):
                continue
            path = os.path.join(folder, fn)
            if not os.path.isfile(path):
                continue
            info = _entry(path, grp)
            if needle:
                hay = " ".join((info['name'], info['group'],
                                info['author'],
                                info['comment'])).lower()
                if needle not in hay:
                    continue
            out.append(info)
    out.sort(key=lambda e: e['mtime'], reverse=True)
    return out


def group_counts(programs_dir: str) -> Dict[str, int]:
    """Nombre de programmes par groupe."""
    return {grp: len(list_programs(programs_dir, grp))
            for grp in list_groups(programs_dir)}


def move_to_group(programs_dir: str, path: str, group: str) -> str:
    """Déplace un programme vers un groupe. Retourne le nouveau
    chemin (l'ancien si le déplacement n'a pas eu lieu)."""
    target_dir = group_dir(programs_dir, group)
    os.makedirs(target_dir, exist_ok=True)
    dest = os.path.join(target_dir, os.path.basename(path))
    if os.path.abspath(dest) == os.path.abspath(path):
        return path
    if os.path.exists(dest):
        base, ext = os.path.splitext(os.path.basename(path))
        stamp = datetime.now().strftime("%y%m%d-%H%M%S")
        dest = os.path.join(target_dir, f"{base} ({stamp}){ext}")
    shutil.move(path, dest)
    return dest


def rename_group(programs_dir: str, old: str, new: str) -> str:
    """Renomme un groupe. Retourne le nouveau nom, ou "" si refusé."""
    old, new = sanitize_group(old), sanitize_group(new)
    if not old or not new or old == ROOT_GROUP:
        return ""
    src = os.path.join(programs_dir, old)
    dst = os.path.join(programs_dir, new)
    if not os.path.isdir(src) or os.path.exists(dst):
        return ""
    os.rename(src, dst)
    return new
