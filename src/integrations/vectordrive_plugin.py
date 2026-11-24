# -*- coding: utf-8 -*-
"""Installer, dans VectorDrive, le plugin qui fait de NeoDrive son
post-processeur Datron (voir `integrations/vectordrive/neodrive_post`).

Le plugin est copié dans le dossier des plugins de l'utilisateur de
VectorDrive (`%LOCALAPPDATA%\\VectorDrive\\plugins`), avec ses réglages
(`neodrive_post.json`): la commande qui lance CE NeoDrive — l'exe, ou
Python et main.py dans le dépôt —, l'ouverture du programme dans
NeoDrive, et l'origine du régime et des avances.
"""

import json
import os
import shutil
import sys
from typing import Dict, List, Optional

NOM_PAQUET = "neodrive_post"
FICHIER_REGLAGES = "neodrive_post.json"


def source_plugin() -> Optional[str]:
    """Le dossier du paquet du plugin: dans l'exe (données embarquées)
    ou dans le dépôt."""
    candidats = []
    if getattr(sys, 'frozen', False):
        candidats.append(os.path.join(getattr(sys, '_MEIPASS', ''),
                                      'integrations', 'vectordrive',
                                      NOM_PAQUET))
        candidats.append(os.path.join(os.path.dirname(sys.executable),
                                      'integrations', 'vectordrive',
                                      NOM_PAQUET))
    racine = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    candidats.append(os.path.join(racine, 'integrations', 'vectordrive',
                                  NOM_PAQUET))
    return next((c for c in candidats
                 if os.path.isfile(os.path.join(c, '__init__.py'))), None)


def dossier_plugins_vectordrive() -> str:
    """Le dossier des plugins de l'utilisateur de VectorDrive."""
    base = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    return os.path.join(base, 'VectorDrive', 'plugins')


def commande_neodrive() -> List[str]:
    """La commande qui lance ce NeoDrive-ci."""
    if getattr(sys, 'frozen', False):
        return [sys.executable]
    racine = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    return [sys.executable, os.path.join(racine, 'main.py')]


def _meme_plugin(source: str, cible: str) -> bool:
    """Les fichiers .py installés sont-ils ceux de ce NeoDrive?"""
    for nom in os.listdir(source):
        if not nom.endswith('.py'):
            continue
        try:
            with open(os.path.join(source, nom), 'rb') as a, \
                    open(os.path.join(cible, nom), 'rb') as b:
                if a.read() != b.read():
                    return False
        except OSError:
            return False
    return True


def etat(dossier: str = None) -> Dict:
    """Le plugin est-il installé, à jour (le même que celui de ce
    NeoDrive), et vers quel NeoDrive pointe-t-il — qui existe encore?"""
    cible = os.path.join(dossier or dossier_plugins_vectordrive(),
                         NOM_PAQUET)
    installe = os.path.isfile(os.path.join(cible, '__init__.py'))
    reglages = {}
    try:
        with open(os.path.join(cible, FICHIER_REGLAGES), 'r',
                  encoding='utf-8') as f:
            reglages = json.load(f)
    except (OSError, ValueError):
        pass
    if not isinstance(reglages, dict):
        reglages = {}
    source = source_plugin()
    a_jour = installe and (source is None or _meme_plugin(source, cible))
    cmd = reglages.get('neodrive') or []
    lance = str(cmd[-1] if isinstance(cmd, list) and cmd else cmd or "")
    return {'installe': installe, 'dossier': cible, 'reglages': reglages,
            'a_jour': a_jour, 'lance': lance,
            'lance_existe': bool(lance) and os.path.isfile(lance)}


def installer(dossier: str = None, ouvrir: bool = True,
              avances: str = 'vectordrive') -> str:
    """Copie le plugin dans le dossier des plugins de VectorDrive et y
    écrit ses réglages (la commande de ce NeoDrive). Rend le dossier du
    plugin installé. Les réglages d'avant sont gardés, sauf la commande."""
    source = source_plugin()
    if source is None:
        raise FileNotFoundError("le plugin VectorDrive n'est pas livré "
                                "avec ce NeoDrive")
    cible = os.path.join(dossier or dossier_plugins_vectordrive(),
                         NOM_PAQUET)
    anciens = etat(dossier)['reglages']
    os.makedirs(cible, exist_ok=True)
    for nom in os.listdir(source):
        if nom.endswith('.py'):
            shutil.copy2(os.path.join(source, nom), os.path.join(cible, nom))
    reglages = dict(anciens) if isinstance(anciens, dict) else {}
    reglages['neodrive'] = commande_neodrive()
    reglages.setdefault('ouvrir', bool(ouvrir))
    reglages.setdefault('avances', avances)
    from src.core.fichiers_surs import ecrire_json_sur
    ecrire_json_sur(os.path.join(cible, FICHIER_REGLAGES), reglages,
                    indent=1, ensure_ascii=False)
    return cible
