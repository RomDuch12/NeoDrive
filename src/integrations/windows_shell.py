# -*- coding: utf-8 -*-
"""« Ouvrir avec NeoDrive » dans l'Explorateur Windows.

Un clic droit sur un .ndp, un .nds ou un .SimPl propose NeoDrive; un
double-clic sur un .ndp ou un .nds l'ouvre. Tout se joue dans la
ruche de l'utilisateur (HKCU\\Software\\Classes): pas de droits
d'administrateur, et ça se désinstalle aussi proprement que ça
s'installe — depuis l'onglet Paramètres.

Le .SimPl n'est PAS pris comme association par défaut: on l'ouvre
souvent déjà avec autre chose (un éditeur de texte, un logiciel de
gravure). Il n'a que le verbe du clic droit.

Tout ce qui écrit dans le registre passe par `racine`, pour que les
tests s'exercent sous une clé d'essai et jamais dans les vraies
associations.
"""

import os
import sys
from typing import Dict, List, Optional, Tuple

#: nom du verbe, tel qu'il apparaît dans le menu du clic droit
VERBE = "Ouvrir avec NeoDrive"
#: clé du verbe sous shell\\ — sans espace ni accent
CLE_VERBE = "NeoDrive"

#: extensions et leur ProgID; None = pas d'association par défaut
PROGIDS: Dict[str, Optional[Tuple[str, str]]] = {
    '.ndp': ("NeoDrive.Programme", "Programme NeoDrive"),
    '.nds': ("NeoDrive.SousProgramme", "Sous-programme NeoDrive"),
    '.simpl': None,
}

#: où vivent les associations d'un utilisateur
RACINE_UTILISATEUR = r"Software\Classes"


def commande_ouverture() -> str:
    """La ligne que Windows lance: l'exe (ou python + main.py)."""
    if getattr(sys, 'frozen', False):
        return f'"{sys.executable}" "%1"'
    principal = os.path.abspath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..",
        "main.py"))
    python = sys.executable
    # sans console: pythonw quand il existe à côté de python
    sans_console = os.path.join(os.path.dirname(python), "pythonw.exe")
    if os.path.isfile(sans_console):
        python = sans_console
    return f'"{python}" "{principal}" "%1"'


def icone() -> str:
    """L'icône du verbe et des fichiers: celle de l'exe."""
    if getattr(sys, 'frozen', False):
        return f'"{sys.executable}",0'
    return ""


def cles_a_ecrire(commande: str = None,
                  icone_: str = None) -> List[Tuple[str, str, str]]:
    """Ce qu'il faut écrire: (chemin sous la racine, nom de valeur,
    valeur). Nom vide = valeur par défaut de la clé.

    Pur: ne touche à rien. C'est ce que les tests vérifient."""
    commande = commande_ouverture() if commande is None else commande
    icone_ = icone() if icone_ is None else icone_
    lignes = []
    for extension, progid in PROGIDS.items():
        # le verbe du clic droit, pour toutes les extensions
        verbe = fr"SystemFileAssociations\{extension}\shell\{CLE_VERBE}"
        lignes.append((verbe, "", VERBE))
        if icone_:
            lignes.append((verbe, "Icon", icone_))
        lignes.append((verbe + r"\command", "", commande))
        if progid is None:
            continue
        # l'association par défaut: double-clic
        nom, libelle = progid
        lignes.append((extension, "", nom))
        lignes.append((nom, "", libelle))
        if icone_:
            lignes.append((nom + r"\DefaultIcon", "", icone_))
        lignes.append((nom + r"\shell\open\command", "", commande))
    # et NeoDrive dans la liste « Ouvrir avec »
    lignes.append((r"Applications\NeoDrive.exe\shell\open\command", "",
                   commande))
    lignes.append((r"Applications\NeoDrive.exe", "FriendlyAppName",
                   "NeoDrive"))
    return lignes


def cles_a_effacer() -> List[str]:
    """Les clés qui sont à nous, à retirer à la désinstallation.

    L'association `.ndp` → ProgID est retirée seulement si elle
    pointe encore sur nous (voir `desinstaller`)."""
    cles = []
    for extension, progid in PROGIDS.items():
        cles.append(fr"SystemFileAssociations\{extension}\shell\{CLE_VERBE}")
        if progid is not None:
            cles.append(progid[0])
    cles.append(r"Applications\NeoDrive.exe")
    return cles


# ── le registre lui-même ──

def _winreg():
    try:
        import winreg
        return winreg
    except ImportError:                       # pragma: no cover
        return None


def installer(racine: str = RACINE_UTILISATEUR,
              commande: str = None) -> bool:
    """Écrit les clés. Vrai si tout a été écrit."""
    winreg = _winreg()
    if winreg is None:
        return False
    try:
        for chemin, nom, valeur in cles_a_ecrire(commande):
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,
                                    racine + "\\" + chemin, 0,
                                    winreg.KEY_SET_VALUE) as cle:
                winreg.SetValueEx(cle, nom or None, 0, winreg.REG_SZ,
                                  valeur)
    except OSError:
        return False
    if racine == RACINE_UTILISATEUR:
        _prevenir_explorateur()
    return True


def _effacer_arbre(winreg, racine_hkey, chemin: str) -> None:
    """Supprime une clé et tout ce qu'elle contient."""
    try:
        with winreg.OpenKey(racine_hkey, chemin, 0,
                            winreg.KEY_READ | winreg.KEY_WRITE) as cle:
            enfants = []
            index = 0
            while True:
                try:
                    enfants.append(winreg.EnumKey(cle, index))
                except OSError:
                    break
                index += 1
        for enfant in enfants:
            _effacer_arbre(winreg, racine_hkey, chemin + "\\" + enfant)
        winreg.DeleteKey(racine_hkey, chemin)
    except FileNotFoundError:
        pass


def desinstaller(racine: str = RACINE_UTILISATEUR) -> bool:
    """Retire nos clés — et seulement les nôtres.

    Si `.ndp` pointe encore sur notre ProgID, l'association est
    retirée; si l'utilisateur l'a redirigée ailleurs entre-temps, on
    n'y touche pas."""
    winreg = _winreg()
    if winreg is None:
        return False
    try:
        for extension, progid in PROGIDS.items():
            if progid is None:
                continue
            chemin = racine + "\\" + extension
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, chemin, 0,
                                    winreg.KEY_READ) as cle:
                    actuel, _genre = winreg.QueryValueEx(cle, None)
            except OSError:
                continue
            if actuel == progid[0]:
                _effacer_arbre(winreg, winreg.HKEY_CURRENT_USER, chemin)
        for chemin in cles_a_effacer():
            _effacer_arbre(winreg, winreg.HKEY_CURRENT_USER,
                           racine + "\\" + chemin)
    except OSError:
        return False
    if racine == RACINE_UTILISATEUR:
        _prevenir_explorateur()
    return True


def etat(racine: str = RACINE_UTILISATEUR) -> str:
    """« absent », « installé », ou « installé pour un autre
    chemin » quand l'exe a bougé depuis."""
    winreg = _winreg()
    if winreg is None:
        return "absent"
    chemin = (racine + fr"\SystemFileAssociations\.ndp\shell"
              fr"\{CLE_VERBE}\command")
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, chemin, 0,
                            winreg.KEY_READ) as cle:
            valeur, _genre = winreg.QueryValueEx(cle, None)
    except OSError:
        return "absent"
    return ("installé" if valeur == commande_ouverture()
            else "installé pour un autre chemin")


def _prevenir_explorateur() -> None:
    """Dit à l'Explorateur que les associations ont changé: sinon
    les icônes ne suivent qu'après une session."""
    try:
        import ctypes
        SHCNE_ASSOCCHANGED = 0x08000000
        SHCNF_IDLIST = 0x0000
        ctypes.windll.shell32.SHChangeNotify(
            SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)
    except Exception:
        pass
