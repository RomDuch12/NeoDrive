"""Lire et écrire les fichiers de données sans jamais les perdre.

Écrire un JSON par `open(chemin, 'w')` VIDE le fichier d'abord: une
coupure de courant, un plantage pendant l'écriture, et il ne reste ni
l'ancienne version ni la nouvelle — un risque réel sur un poste
d'atelier. Pire, la bibliothèque d'outils illisible était remplacée
en silence par celle par défaut — puis réenregistrée par-dessus: les
outils de l'atelier pouvaient disparaître sans un mot.

Ici:
- l'écriture passe par un fichier temporaire, vidé sur le disque, puis
  remplace l'ancien d'un coup (`os.replace`, atomique sur un même
  volume): on a toujours l'une OU l'autre version, entière;
- `garder_bak`: la version précédente reste en `<fichier>.bak`;
- la lecture d'un fichier illisible le MET DE CÔTÉ (jamais écrasé),
  essaie la sauvegarde `.bak`, et rend un message à montrer.
"""

import json
import os
import shutil
import tempfile
from datetime import datetime
from typing import Any, List, Optional, Tuple

#: les alertes de lecture que la fenêtre n'a pas encore montrées: un
#: fichier lu par un module (favoris, modèles…) avant qu'elle existe
_ALERTES: List[str] = []


def alertes_en_attente(vider: bool = True) -> List[str]:
    """Les alertes de lecture à montrer (sans doublon), et on oublie."""
    sortie = list(dict.fromkeys(_ALERTES))
    if vider:
        _ALERTES.clear()
    return sortie


def lire_json(chemin: str, defaut: Any = None) -> Any:
    """Les données d'un JSON — `defaut` s'il est absent ou illisible.

    Illisible, il est mis de côté (le prochain enregistrement ne
    l'écrase donc pas), sa sauvegarde .bak est reprise si elle existe,
    et l'alerte attend la fenêtre (`alertes_en_attente`)."""
    donnees, _alerte = lire_json_sur(chemin)
    return defaut if donnees is None else donnees


def ecrire_json_sur(chemin: str, donnees: Any, garder_bak: bool = False,
                    **options_json) -> None:
    """Écrit `donnees` en JSON sans jamais laisser un fichier à moitié
    écrit. `options_json` va à `json.dump` (indent, ensure_ascii…)."""
    chemin = os.path.abspath(chemin)
    dossier = os.path.dirname(chemin)
    os.makedirs(dossier, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(chemin) + ".",
                               suffix=".tmp", dir=dossier)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(donnees, f, **options_json)
            f.flush()
            os.fsync(f.fileno())
        if garder_bak and os.path.exists(chemin):
            try:
                shutil.copy2(chemin, chemin + ".bak")
            except OSError:
                pass
        os.replace(tmp, chemin)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def ecrire_texte_sur(chemin: str, texte: str, garder_bak: bool = False,
                     encoding: str = 'utf-8') -> None:
    """Écrit un texte (un .SimPl…) sans jamais laisser un fichier à
    moitié écrit: temporaire vidé sur le disque, puis remplacement
    d'un coup. Mode texte comme `open(chemin, 'w')`: mêmes octets
    qu'avant (fins de ligne du système).

    `garder_bak`: la version précédente reste en `<fichier>.bak` — un
    programme écrasé par un export ou un enregistrement se reprend."""
    chemin = os.path.abspath(chemin)
    dossier = os.path.dirname(chemin)
    os.makedirs(dossier, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(chemin) + ".",
                               suffix=".tmp", dir=dossier)
    try:
        with os.fdopen(fd, 'w', encoding=encoding) as f:
            f.write(texte)
            f.flush()
            os.fsync(f.fileno())
        if garder_bak and os.path.exists(chemin):
            try:
                shutil.copy2(chemin, chemin + ".bak")
            except OSError:
                pass
        os.replace(tmp, chemin)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _remettre_bak(bak: str, chemin: str) -> bool:
    """Remet la sauvegarde à la place du fichier (copie puis
    remplacement d'un coup); la sauvegarde reste. Rend True si c'est
    fait. Sans cela, le fichier repris n'existait qu'en mémoire: au
    démarrage suivant il manquait, et la bibliothèque par défaut
    prenait sa place — puis son enregistrement écrasait le bon .bak."""
    dossier = os.path.dirname(os.path.abspath(chemin))
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(prefix=os.path.basename(chemin) + ".",
                                   suffix=".tmp", dir=dossier)
        os.close(fd)
        shutil.copy2(bak, tmp)
        os.replace(tmp, chemin)
        return True
    except OSError:
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass
        return False


def lire_json_sur(chemin: str, reprendre_si_absent: bool = False
                  ) -> Tuple[Optional[Any], Optional[str]]:
    """Lit un JSON. Rend (données, alerte).

    - absent: (None, None) — rien à signaler; avec `reprendre_si_absent`,
      sa sauvegarde `.bak` lisible est reprise et remise en place (le
      fichier a disparu: ce n'est pas une première installation);
    - lisible: (données, None);
    - illisible: le fichier est mis de côté sous
      `<fichier>.illisible-AAAAMMJJ-HHMMSS` (jamais écrasé), on essaie
      `<fichier>.bak`, REMIS à sa place; rend (données de la sauvegarde
      ou None, alerte).
    """
    if not os.path.exists(chemin):
        bak = chemin + ".bak"
        if not reprendre_si_absent or not os.path.exists(bak):
            return None, None
        try:
            with open(bak, 'r', encoding='utf-8') as f:
                donnees = json.load(f)
        except (OSError, ValueError):
            return None, None
        remis = _remettre_bak(bak, chemin)
        alerte = (f"{os.path.basename(chemin)} manquait. Sa sauvegarde "
                  "précédente a été reprise"
                  + (" et remise à sa place." if remis else
                     " (elle n'a pas pu être remise à sa place)."))
        _ALERTES.append(alerte)
        return donnees, alerte
    try:
        with open(chemin, 'r', encoding='utf-8') as f:
            return json.load(f), None
    except (OSError, ValueError) as err:
        raison = str(err)
    nom = os.path.basename(chemin)
    cote = f"{chemin}.illisible-{datetime.now():%Y%m%d-%H%M%S}"
    try:
        os.replace(chemin, cote)
        garde = f"L'original est gardé sous « {os.path.basename(cote)} »."
    except OSError:
        garde = "L'original n'a pas pu être mis de côté: il est laissé en place."
    bak = chemin + ".bak"
    if os.path.exists(bak):
        try:
            with open(bak, 'r', encoding='utf-8') as f:
                donnees = json.load(f)
            remis = _remettre_bak(bak, chemin)
            alerte = (f"{nom} était illisible ({raison}). La sauvegarde "
                      "précédente a été reprise"
                      + (" et remise à sa place. " if remis else
                         " (elle n'a pas pu être remise à sa place). ")
                      + garde)
            _ALERTES.append(alerte)
            return donnees, alerte
        except (OSError, ValueError):
            pass
    alerte = (f"{nom} est illisible ({raison}) et aucune sauvegarde "
              f"lisible n'existe. {garde}")
    _ALERTES.append(alerte)
    return None, alerte


def mettre_de_cote(chemin: str) -> str:
    """Met un fichier de côté (copie datée, l'original reste) et rend
    la phrase qui le dit. Sert quand le JSON se lit mais que son
    CONTENU ne tient pas: on ne doit pas l'écraser ensuite."""
    if not os.path.exists(chemin):
        return ""
    cote = f"{chemin}.illisible-{datetime.now():%Y%m%d-%H%M%S}"
    try:
        shutil.copy2(chemin, cote)
        return f"Une copie est gardée sous « {os.path.basename(cote)} »."
    except OSError:
        return "Il n'a pas pu être copié de côté."
