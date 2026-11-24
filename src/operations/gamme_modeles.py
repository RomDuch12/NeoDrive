# -*- coding: utf-8 -*-
"""Les modèles de gamme: une gamme réglée se garde, et se recrée.

Trois sources, dans cet ordre:

- la gamme de base, générique, livrée avec NeoDrive (`BASE`);
- les gammes d'un atelier, livrées avec ses données:
  `data/gammes_atelier.json` à côté de l'exe (absent de la version
  libre). NeoDrive les lit, ne les modifie jamais;
- celles que l'utilisateur met au point — une plaque, un logo
  dense —, enregistrées sous un nom dans
  `data/gammes.json`.

« Ajouter → Gamme gravure » part du modèle par défaut (celui que
l'utilisateur a choisi, sinon celui de l'atelier, sinon la base); le
formulaire de la tête permet d'appliquer un autre modèle aux postes,
d'enregistrer la gamme courante, de supprimer un modèle.

Un modèle est la liste des postes (voir `gamme_postes.poste`): genre,
type d'opération, outil par son nom, moment, réglages essentiels.
"""

import os
from typing import Any, Dict, List, Optional, Sequence

from src.operations import gamme_postes as gp

#: le modèle générique, livré avec NeoDrive, jamais modifiable
BASE = "Gamme de base"

#: le fichier des gammes de l'atelier, à côté de `gammes.json`
NOM_ATELIER = "gammes_atelier.json"

#: réglages d'un poste qui font le modèle (pas le dessin, pas le
#: champ: ceux-là viennent de la tête)
REGLAGES_MODELE = ('profondeur', 'profondeur_max', 'profondeur_passe',
                   'offset_xy', 'offset_z', 'reprise', 'contour_source',
                   'marge_champ', 'cadre_decalage', 'message',
                   'dialog_type', 'park_before', 'pas_radial',
                   'recouvrement', 'strategie', 'pres_du_trait')


def chemin() -> str:
    """`data/gammes.json` à côté de l'exe — ou à côté des réglages de
    test quand NEODRIVE_APP_SETTINGS les détourne."""
    detour = os.environ.get('NEODRIVE_APP_SETTINGS')
    if detour:
        return os.path.join(os.path.dirname(detour), "gammes.json")
    from src.core.tool_library import get_base_dir
    return os.path.join(get_base_dir(), 'data', 'gammes.json')


def chemin_atelier() -> str:
    """`data/gammes_atelier.json`, dans le dossier de `gammes.json` —
    ou celui que NEODRIVE_GAMMES_ATELIER désigne (les tests)."""
    return (os.environ.get('NEODRIVE_GAMMES_ATELIER')
            or os.path.join(os.path.dirname(chemin()), NOM_ATELIER))


def _modeles(lu) -> Dict[str, list]:
    modeles = lu.get('modeles') if isinstance(lu, dict) else None
    if not isinstance(modeles, dict):
        return {}
    return {str(k): list(v) for k, v in modeles.items()
            if isinstance(v, list)}


def charger() -> Dict[str, Any]:
    """Les modèles de l'utilisateur: {'par_defaut': nom ou "",
    'modeles': {nom: [postes]}}."""
    from src.core.fichiers_surs import lire_json
    lu = lire_json(chemin())
    par_defaut = lu.get('par_defaut') if isinstance(lu, dict) else ""
    return {'par_defaut': str(par_defaut or ""), 'modeles': _modeles(lu)}


def charger_atelier() -> Dict[str, Any]:
    """Les gammes de l'atelier, telles que son fichier les livre:
    {'par_defaut': nom ou "", 'modeles': {nom: [postes]}} — vide sans
    le fichier (version libre)."""
    from src.core.fichiers_surs import lire_json
    lu = lire_json(chemin_atelier())
    par_defaut = lu.get('par_defaut') if isinstance(lu, dict) else ""
    return {'par_defaut': str(par_defaut or ""), 'modeles': _modeles(lu)}


def livres() -> List[str]:
    """Les modèles livrés, jamais modifiables: la base, puis ceux de
    l'atelier dans l'ordre de son fichier."""
    return [BASE] + [n for n in charger_atelier()['modeles']
                     if n != BASE]


def est_livre(nom: str) -> bool:
    return nom in livres()


def enregistrer(donnees: Dict[str, Any]) -> bool:
    try:
        from src.core.fichiers_surs import ecrire_json_sur
        ecrire_json_sur(chemin(), donnees, garder_bak=True, indent=2,
                        ensure_ascii=False)
        return True
    except OSError:
        return False


def noms() -> List[str]:
    """Les modèles livrés d'abord, puis ceux de l'utilisateur, triés."""
    deja = livres()
    return deja + sorted((n for n in charger()['modeles']
                          if n not in deja), key=str.lower)


def par_defaut() -> str:
    """Le modèle choisi par l'utilisateur; sinon celui que l'atelier
    désigne; sinon la base."""
    tous = noms()
    for nom in (charger()['par_defaut'], charger_atelier()['par_defaut']):
        if nom and nom in tous:
            return nom
    return BASE


def choisir_par_defaut(nom: str) -> bool:
    if not existe(nom):
        return False
    donnees = charger()
    donnees['par_defaut'] = nom
    return enregistrer(donnees)


def _postes_depuis(bruts) -> List[Dict[str, Any]]:
    postes = []
    for brut in bruts or []:
        if not isinstance(brut, dict) or 'op_type' not in brut:
            continue
        postes.append(gp.poste(
            str(brut.get('nom') or brut['op_type']), str(brut['op_type']),
            brut.get('outil'), str(brut.get('moment') or gp.MOMENTS[0]),
            **dict(brut.get('reglages') or {})))
    return postes


def postes_du(nom: str) -> List[Dict[str, Any]]:
    """Les postes d'un modèle, prêts pour `creer_gamme`."""
    if nom == BASE:
        return [dict(p, reglages=dict(p['reglages']))
                for p in gp.POSTES_BASE]
    atelier = charger_atelier()['modeles']
    if nom in atelier:
        return _postes_depuis(atelier[nom])
    return _postes_depuis(charger()['modeles'].get(nom))


def modele_depuis_membres(membres: Sequence[Any],
                          bibliotheque) -> List[Dict[str, Any]]:
    """La gamme telle qu'elle est: ses postes, dans l'ordre, avec
    l'outil de chacun (par son nom) et ses réglages essentiels."""
    postes = []
    for op in membres:
        genre = {"contour_2d5": "Contour", "gravure_2d5": "Gravure",
                 "evidement_2d5": "Évidement",
                 "dialogue_operateur": "Pause"}.get(op.operation_type)
        if genre is None:
            continue
        if op.operation_type == "contour_2d5" and str(
                op.params.get('contour_source') or "") == \
                gp.SOURCES_CONTOUR[0]:
            genre = "Détourage"
        outil = gp.nom_outil(bibliotheque, getattr(op, 'tool_id', '')) \
            if op.operation_type in gp.TYPES_A_OUTIL else None
        moment = gp.MOMENTS[1] if op.operation_type == "evidement_2d5" \
            else gp.MOMENTS[0]
        reglages = {k: op.params[k] for k in REGLAGES_MODELE
                    if k in op.params}
        postes.append(gp.poste(genre, op.operation_type, outil, moment,
                               **reglages))
    return postes


def sauver_modele(nom: str, postes: Sequence[Dict[str, Any]]) -> bool:
    nom = str(nom or "").strip()
    if not nom or est_livre(nom):
        return False
    donnees = charger()
    donnees['modeles'][nom] = [dict(p, reglages=dict(p['reglages']))
                               for p in postes]
    return enregistrer(donnees)


def supprimer_modele(nom: str) -> bool:
    donnees = charger()
    if nom not in donnees['modeles'] or est_livre(nom):
        return False
    del donnees['modeles'][nom]
    if donnees['par_defaut'] == nom:
        donnees['par_defaut'] = ""      # retour au défaut de l'atelier
    return enregistrer(donnees)


def existe(nom: str) -> bool:
    return nom in noms()


def description(nom: str) -> str:
    """« 7 postes: Contour, Gravure ×3, Pause, Évidement ×2 »."""
    postes = postes_du(nom)
    if not postes:
        return "aucun poste"
    comptes: Dict[str, int] = {}
    ordre: List[str] = []
    for p in postes:
        if p['nom'] not in comptes:
            ordre.append(p['nom'])
        comptes[p['nom']] = comptes.get(p['nom'], 0) + 1
    morceaux = [f"{n} ×{comptes[n]}" if comptes[n] > 1 else n
                for n in ordre]
    return f"{len(postes)} poste(s): " + ", ".join(morceaux)


def creer_depuis_modele(modele, bibliotheque,
                        nom: Optional[str] = None):
    """`creer_gamme` avec les postes d'un modèle (le modèle par
    défaut si `nom` est None)."""
    nom = nom or par_defaut()
    return gp.creer_gamme(modele, bibliotheque, postes_du(nom))
