# -*- coding: utf-8 -*-
"""Programmes outils externes (Dathread, ...).

Découverte dynamique dans le dossier « Programmes outils » à côté de
l'exe (ou de la racine du projet en dev) : chaque sous-dossier est un
programme. AUCUNE compilation nécessaire — déposer un nouveau dossier
avec un .py ou un .exe suffit pour qu'il apparaisse dans NeoDrive.

Manifeste optionnel `neodrive_tool.json` dans le dossier du programme:
{
  "name":  "Dathread",              // nom affiché (défaut: nom dossier)
  "entry": "Dathread_4.py",         // script/exe à lancer (défaut: auto)
  "icon":  "icon.ico",              // icône (défaut: 1er .ico trouvé)
  "share_neodrive_tools": true      // transmettre le tools.json NeoDrive
}

Interaction proposée: au lancement, NeoDrive transmet son tools.json
via l'argument `--neodrive-tools "<chemin>"` ET la variable
d'environnement NEODRIVE_TOOLS_JSON. Les programmes outils sont libres
de l'exploiter (bibliothèque d'outils partagée) ou de l'ignorer.
"""

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import List, Optional

from src.core.tool_library import get_base_dir

MANIFEST_NAME = "neodrive_tool.json"
TOOL_PROGRAMS_DIRNAME = "Programmes outils"


@dataclass
class ToolProgram:
    name: str
    dir_path: str
    entry: str            # chemin absolu du .py ou .exe à lancer
    kind: str             # 'py' | 'exe'
    icon_path: str = ""
    manifest: dict = field(default_factory=dict)

    @property
    def share_neodrive_tools(self) -> bool:
        return bool(self.manifest.get('share_neodrive_tools', True))


def tool_programs_dir() -> str:
    """Dossier « Programmes outils » (à côté de l'exe / racine projet)."""
    return os.path.join(get_base_dir(), TOOL_PROGRAMS_DIRNAME)


def _read_manifest(dir_path: str) -> dict:
    path = os.path.join(dir_path, MANIFEST_NAME)
    # illisible: mis de côté, sinon le réglage suivant (partage des
    # outils) l'écrasait avec un manifeste vide
    from src.core.fichiers_surs import lire_json
    data = lire_json(path, {})
    return data if isinstance(data, dict) else {}


def write_manifest(prog: 'ToolProgram') -> bool:
    """Réécrit le manifeste du programme (persistance des réglages)."""
    path = os.path.join(prog.dir_path, MANIFEST_NAME)
    try:
        from src.core.fichiers_surs import ecrire_json_sur
        ecrire_json_sur(path, prog.manifest, garder_bak=True, indent=2,
                        ensure_ascii=False)
        return True
    except OSError:
        return False


def _find_entry(dir_path: str, manifest: dict) -> Optional[str]:
    """Résout le fichier à lancer: manifeste > .exe > .py principal."""
    entry = manifest.get('entry', '')
    if entry:
        p = os.path.join(dir_path, entry)
        if os.path.isfile(p):
            return p
    try:
        files = sorted(os.listdir(dir_path))
    except OSError:
        return None
    # 1) un .exe à la racine (programme déjà compilé)
    exes = [f for f in files
            if f.lower().endswith('.exe')
            and not f.lower().startswith(('unins', 'setup'))]
    if exes:
        return os.path.join(dir_path, exes[0])
    # 2) le plus gros .py à la racine (script principal)
    pys = [f for f in files
           if f.lower().endswith('.py')
           and not f.lower().startswith(('create_', 'setup', 'test'))]
    if pys:
        pys.sort(key=lambda f: os.path.getsize(
            os.path.join(dir_path, f)), reverse=True)
        return os.path.join(dir_path, pys[0])
    return None


def _find_icon(dir_path: str, manifest: dict) -> str:
    icon = manifest.get('icon', '')
    if icon:
        p = os.path.join(dir_path, icon)
        if os.path.isfile(p):
            return p
    try:
        for f in sorted(os.listdir(dir_path)):
            if f.lower().endswith('.ico'):
                return os.path.join(dir_path, f)
    except OSError:
        pass
    return ""


def discover_tool_programs() -> List[ToolProgram]:
    """Scanne le dossier « Programmes outils ». Appelé à chaque
    ouverture du menu: un nouveau dossier apparaît sans redémarrage."""
    root = tool_programs_dir()
    programs = []
    if not os.path.isdir(root):
        return programs
    try:
        subdirs = sorted(os.listdir(root))
    except OSError:
        return programs
    for sub in subdirs:
        dir_path = os.path.join(root, sub)
        if not os.path.isdir(dir_path):
            continue
        manifest = _read_manifest(dir_path)
        entry = _find_entry(dir_path, manifest)
        if not entry:
            continue
        kind = 'exe' if entry.lower().endswith('.exe') else 'py'
        programs.append(ToolProgram(
            name=manifest.get('name', sub),
            dir_path=dir_path,
            entry=entry,
            kind=kind,
            icon_path=_find_icon(dir_path, manifest),
            manifest=manifest,
        ))
    return programs


def _python_interpreter() -> Optional[str]:
    """Interpréteur Python pour lancer les .py.
    En dev: celui de NeoDrive. En .exe gelé: py/pythonw du système."""
    if not getattr(sys, 'frozen', False):
        return sys.executable
    for cand in ('pythonw', 'python', 'py'):
        path = shutil.which(cand)
        if path:
            return path
    return None


def neodrive_tools_json_path() -> str:
    return os.path.join(get_base_dir(), 'data', 'tools.json')


def launch_tool_program(prog: ToolProgram) -> Optional[str]:
    """Lance le programme (détaché). Retourne un message d'erreur ou
    None si OK. Transmet le tools.json NeoDrive si le manifeste le
    demande (argument --neodrive-tools + env NEODRIVE_TOOLS_JSON)."""
    if prog.kind == 'exe':
        cmd = [prog.entry]
    else:
        interp = _python_interpreter()
        if not interp:
            return ("Aucun interpréteur Python trouvé sur ce poste "
                    "(requis pour lancer un programme .py). Installez "
                    "Python ou compilez le programme en .exe.")
        cmd = [interp, prog.entry]

    env = dict(os.environ)
    if prog.share_neodrive_tools:
        tools_path = neodrive_tools_json_path()
        if os.path.isfile(tools_path):
            cmd += ['--neodrive-tools', tools_path]
            env['NEODRIVE_TOOLS_JSON'] = tools_path
    try:
        flags = 0
        if sys.platform == 'win32':
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | \
                subprocess.DETACHED_PROCESS
        subprocess.Popen(cmd, cwd=prog.dir_path, env=env,
                         creationflags=flags,
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL)
        return None
    except OSError as e:
        return str(e)
