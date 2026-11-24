# -*- coding: utf-8 -*-
"""Les données de l'utilisateur, en un fichier: exporter, importer.

Ce qu'il règle depuis l'exe — outils, réglages, défauts des
formulaires, favoris, modèles de gamme, gabarits de brut, matières,
raccourcis, réglages de palpage — vit dans `data/` à côté de l'exe.
Un poste neuf, une sauvegarde, un collègue: on emporte le tout dans
un .zip et on le rend où l'on veut.
"""

import json
import os
import re
import shutil
import zipfile
from datetime import datetime
from typing import Dict, List, Optional

from src.core.tool_library import get_base_dir

#: les fichiers de l'utilisateur, dans data/
FICHIERS = ('tools.json', 'app_settings.json', 'default_params.json',
            'favorites.json', 'gammes.json', 'workpiece_templates.json',
            'materials.json', 'shortcuts.json', 'probe_presets.json',
            'ebavurage.json')

#: nom de la carte d'identité de l'archive
MANIFESTE = 'neodrive_donnees.json'

#: les dessins des outils (DXF, STEP), annexés à tools.json: ils
#: voyagent avec lui, dans ce sous-dossier de data/ et de l'archive
DOSSIER_DESSINS = 'outils'
_EXTENSIONS_DESSINS = ('.dxf', '.step', '.stp')
#: les fiches d'outils (un dossier par outil: dessin, fiche JSON,
#: photos du webshop). Les originaux des photos (6000 px, ~2 Mo
#: chacun) restent sur le poste: leurs copies d'affichage partent, un
#: poste hors ligne voit les photos, un poste en ligne retélécharge
#: l'original à la demande
DOSSIER_FICHES = 'fiches_outils'
_FICHE = re.compile(r'^fiches_outils/([A-Za-z0-9._-]+)/((?:apercu/)?'
                    r'[A-Za-z0-9._-]+\.(?:dxf|step|stp|json|jpe?g|png|'
                    r'webp))$', re.I)
_IMAGE = re.compile(r'\.(?:jpe?g|png|webp)$', re.I)


def dossier_data() -> str:
    return os.path.join(get_base_dir(), 'data')


def presents(dossier: Optional[str] = None) -> List[str]:
    """Les fichiers de l'utilisateur qui existent."""
    dossier = dossier or dossier_data()
    return [f for f in FICHIERS
            if os.path.isfile(os.path.join(dossier, f))]


def dessins_presents(dossier: Optional[str] = None) -> List[str]:
    """Les dessins d'outils de data/outils (noms de fichiers)."""
    d = os.path.join(dossier or dossier_data(), DOSSIER_DESSINS)
    if not os.path.isdir(d):
        return []
    return sorted(f for f in os.listdir(d)
                  if f.lower().endswith(_EXTENSIONS_DESSINS)
                  and os.path.isfile(os.path.join(d, f)))


def fiches_presentes(dossier: Optional[str] = None) -> List[str]:
    """Les fichiers des fiches d'outils qui voyagent (« réf/fichier »,
    « réf/apercu/fichier »): dessins, fiches JSON, copies d'affichage
    des photos — pas les originaux."""
    racine = os.path.join(dossier or dossier_data(), DOSSIER_FICHES)
    sortie = []
    if not os.path.isdir(racine):
        return sortie
    for cle in sorted(os.listdir(racine)):
        d = os.path.join(racine, cle)
        if not os.path.isdir(d):
            continue
        for sous in ("", "apercu/"):
            ici = os.path.join(d, sous)
            if not os.path.isdir(ici):
                continue
            for f in sorted(os.listdir(ici)):
                rel = f"{cle}/{sous}{f}"
                if not os.path.isfile(os.path.join(ici, f)) or \
                        not _FICHE.match(f"{DOSSIER_FICHES}/{rel}"):
                    continue
                if not sous and _IMAGE.search(f):
                    continue            # l'original reste sur le poste
                sortie.append(rel)
    return sortie


def exporter(chemin_zip: str, dossier: Optional[str] = None) -> List[str]:
    """Écrit le .zip; rend la liste des fichiers emportés (les
    dessins d'outils partent aussi, sous outils/, avec tools.json)."""
    dossier = dossier or dossier_data()
    fichiers = presents(dossier)
    dessins = dessins_presents(dossier) if 'tools.json' in fichiers else []
    fiches = fiches_presentes(dossier) if 'tools.json' in fichiers else []
    with zipfile.ZipFile(chemin_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
        for nom in fichiers:
            zf.write(os.path.join(dossier, nom), nom)
        for nom in dessins:
            zf.write(os.path.join(dossier, DOSSIER_DESSINS, nom),
                     f"{DOSSIER_DESSINS}/{nom}")
        for nom in fiches:
            zf.write(os.path.join(dossier, DOSSIER_FICHES, *nom.split('/')),
                     f"{DOSSIER_FICHES}/{nom}")
        zf.writestr(MANIFESTE, json.dumps({
            'type': 'neodrive_donnees', 'version': 1,
            'date': datetime.now().isoformat(timespec='seconds'),
            'fichiers': fichiers, 'dessins': len(dessins),
            'fiches': len(fiches)},
            ensure_ascii=False, indent=2))
    return fichiers


def contenu(chemin_zip: str) -> Dict[str, object]:
    """Ce que l'archive contient, sans rien écrire: {'fichiers':
    [...], 'date': …}. Lève ValueError si ce n'est pas une archive
    de données NeoDrive."""
    with zipfile.ZipFile(chemin_zip) as zf:
        noms = set(zf.namelist())
        fichiers = [f for f in FICHIERS if f in noms]
        if not fichiers:
            raise ValueError("cette archive ne contient aucune donnée "
                             "NeoDrive (tools.json, app_settings.json…)")
        date = ""
        if MANIFESTE in noms:
            try:
                date = str(json.loads(zf.read(MANIFESTE).decode(
                    'utf-8')).get('date', ''))
            except (ValueError, UnicodeDecodeError):
                date = ""
        # chaque JSON doit se lire: on refuse une archive abîmée
        # AVANT d'avoir touché au dossier
        for nom in fichiers:
            json.loads(zf.read(nom).decode('utf-8'))
    return {'fichiers': fichiers, 'date': date}


def importer(chemin_zip: str, dossier: Optional[str] = None,
             seulement: Optional[List[str]] = None) -> Dict[str, object]:
    """Remplace les fichiers de `dossier` par ceux de l'archive —
    après en avoir gardé une copie datée dans data/sauvegardes/.
    Rend {'fichiers': [...], 'sauvegarde': chemin}."""
    dossier = dossier or dossier_data()
    info = contenu(chemin_zip)
    fichiers = [f for f in info['fichiers']
                if seulement is None or f in seulement]
    os.makedirs(dossier, exist_ok=True)
    sauvegarde = os.path.join(
        dossier, 'sauvegardes',
        datetime.now().strftime('avant_import_%Y%m%d_%H%M%S'))
    os.makedirs(sauvegarde, exist_ok=True)
    for nom in fichiers:
        ancien = os.path.join(dossier, nom)
        if os.path.isfile(ancien):
            shutil.copy2(ancien, os.path.join(sauvegarde, nom))
    dessins = []
    with zipfile.ZipFile(chemin_zip) as zf:
        for nom in fichiers:
            with open(os.path.join(dossier, nom), 'wb') as f:
                f.write(zf.read(nom))
        if 'tools.json' in fichiers:
            # les dessins annexés à tools.json: un nom de fichier nu,
            # jamais un chemin (« ../ » ne sort pas de data/outils)
            for entree in zf.namelist():
                tete, _, nom = entree.partition('/')
                if (tete != DOSSIER_DESSINS or not nom or '/' in nom
                        or '\\' in nom or nom in ('.', '..')
                        or not nom.lower().endswith(_EXTENSIONS_DESSINS)):
                    continue
                cible = os.path.join(dossier, DOSSIER_DESSINS)
                os.makedirs(cible, exist_ok=True)
                with open(os.path.join(cible, nom), 'wb') as f:
                    f.write(zf.read(entree))
                dessins.append(nom)
            # les fiches d'outils: « fiches_outils/<réf>/[apercu/]
            # <fichier> », noms sages
            for entree in zf.namelist():
                m = _FICHE.match(entree)
                if not m or '..' in entree or m.group(1) in ('.', '..'):
                    continue
                chemin = os.path.join(dossier, DOSSIER_FICHES, m.group(1),
                                      *m.group(2).split('/'))
                os.makedirs(os.path.dirname(chemin), exist_ok=True)
                with open(chemin, 'wb') as f:
                    f.write(zf.read(entree))
    return {'fichiers': fichiers, 'sauvegarde': sauvegarde,
            'dessins': dessins}
