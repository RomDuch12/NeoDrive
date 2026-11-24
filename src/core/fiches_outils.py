"""Le dossier des fiches d'outils, à côté de tools.json: un dossier par
outil (sa référence), qui garde tout ce que la fiche a calculé ou
téléchargé une première fois — le DXF et le STEP de son dessin, ses
photos du webshop DATRON (l'original, et sa copie d'affichage), et la
fiche elle-même (« fiche_<id>.json »: toutes ses specs). Les accès
suivants lisent le dossier au lieu de recalculer ou de retélécharger.

    fiches_outils/
        0068808L/
            0068808L.dxf  0068808L.step
            0068808L_1.png  0068808L_2.png  0068808L_3.png   (originaux)
            apercu/0068808L_1.jpg …                          (affichage)
            fiche_datron_cyl8_z1l41.json
"""

import json
import os
import re
from datetime import datetime
from typing import Dict, Optional

#: le dossier des fiches, à côté de tools.json
DOSSIER = "fiches_outils"


def racine(bibliotheque=None, base: str = None) -> str:
    if base is None:
        base = os.path.dirname(os.path.abspath(
            getattr(bibliotheque, 'filepath', '') or "tools.json"))
    return os.path.join(base, DOSSIER)


def _sur(texte: str) -> str:
    """Un nom de fichier sage (ASCII, sans séparateur)."""
    import unicodedata
    t = unicodedata.normalize('NFKD', str(texte or ''))
    t = t.encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'[^A-Za-z0-9._-]+', '_', t).strip('._')[:60]


def cle(tool=None, tool_id: str = "", ref: str = "") -> str:
    """Le nom du dossier d'un outil: sa référence (les photos, le
    catalogue et le dessin sont ceux de la référence), sinon son nom."""
    from src.core.tool_library import extract_article_nr
    ref = ref or str(getattr(tool, 'article_nr', '') or '')
    ref = _sur(extract_article_nr(ref).strip().upper())
    if ref:
        return ref
    return _sur(getattr(tool, 'name', '') or '') or _sur(tool_id) or "outil"


def dossier(bibliotheque=None, tool=None, tool_id: str = "",
            ref: str = "", base: str = None, creer: bool = False) -> str:
    """Le dossier de la fiche d'un outil (créé à la demande)."""
    d = os.path.join(racine(bibliotheque, base), cle(tool, tool_id, ref))
    if creer:
        os.makedirs(d, exist_ok=True)
    return d


def nom_spec(tool_id: str = "") -> str:
    return f"fiche_{_sur(tool_id) or 'catalogue'}.json"


def ecrire_spec(dossier_fiche: str, tool_id: str, donnees: Dict) -> str:
    """La fiche telle qu'enregistrée (« form_spec_tool »): les specs
    de l'outil, les cotes du dessin, les fichiers du dossier."""
    os.makedirs(dossier_fiche, exist_ok=True)
    chemin = os.path.join(dossier_fiche, nom_spec(tool_id))
    sortie = dict(donnees)
    sortie.setdefault('genere_le', datetime.now().isoformat(
        timespec='seconds'))
    from src.core.fichiers_surs import ecrire_json_sur
    ecrire_json_sur(chemin, sortie, garder_bak=False, indent=2,
                    ensure_ascii=False)
    return chemin


def lire_spec(dossier_fiche: str, tool_id: str = "") -> Optional[Dict]:
    try:
        with open(os.path.join(dossier_fiche, nom_spec(tool_id)),
                  encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None
