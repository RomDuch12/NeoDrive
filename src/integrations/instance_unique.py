# -*- coding: utf-8 -*-
"""Une seule instance de NeoDrive: « Ouvrir avec » ouvre un onglet.

Depuis l'Explorateur, « Ouvrir avec NeoDrive » lançait un DEUXIÈME
NeoDrive — avec sa propre session restaurée, ses onglets, et le
fichier quelque part dedans. L'atelier veut le fichier dans un nouvel
onglet de la fenêtre déjà ouverte.

Le premier NeoDrive tient un serveur local (une prise nommée, par
utilisateur). Chaque lancement suivant s'y connecte, lui passe ses
fichiers, et s'en va; le premier les ouvre et se met devant. Sans
fichier, un lancement de plus ne fait que ramener la fenêtre.
"""

import getpass
import json
import os
import re
import time
from typing import Callable, List, Optional, Tuple

from PySide6.QtNetwork import QLocalServer, QLocalSocket

#: le temps qu'on laisse à l'instance en place pour répondre
DELAI_MS = 400
#: une instance qui DÉMARRE (verrou pris, fenêtre en construction):
#: le temps qu'on lui laisse pour ouvrir sa prise, puis pour lire
ATTENTE_DEMARRAGE_MS = 8000
ATTENTE_LECTURE_MS = 12000

#: les verrous tenus par ce processus (nom → poignée Windows): gardés
#: jusqu'à la sortie, où Windows les libère — même après un plantage
_VERROUS: dict = {}


def nom_du_serveur() -> str:
    """Un nom par utilisateur: deux sessions Windows ne se marchent
    pas dessus."""
    try:
        utilisateur = getpass.getuser()
    except Exception:
        utilisateur = "local"
    propre = re.sub(r'[^A-Za-z0-9_]+', '_', utilisateur)
    return f"NeoDrive-{propre}"


def deleguer(fichiers: List[str], nom: Optional[str] = None,
             attente_ms: int = 0) -> bool:
    """Passe les fichiers à l'instance déjà ouverte.

    Rend True si une instance a pris le relais — l'appelant n'a plus
    qu'à s'en aller —, False s'il n'y en a pas. `attente_ms`: une
    instance qui démarre n'a peut-être pas encore ouvert sa prise; on
    réessaie jusque-là, et on lui laisse le temps de lire."""
    nom = nom or nom_du_serveur()
    limite = time.monotonic() + max(0, attente_ms) / 1000.0
    while True:
        prise = QLocalSocket()
        prise.connectToServer(nom)
        if prise.waitForConnected(DELAI_MS):
            break
        if time.monotonic() >= limite:
            return False
        time.sleep(0.05)
    message = json.dumps({'fichiers': [os.path.abspath(f)
                                       for f in fichiers]})
    prise.write(message.encode('utf-8') + b"\n")
    prise.flush()
    prise.waitForBytesWritten(DELAI_MS)
    # l'instance en place répond « ok » quand elle a lu: on ne coupe
    # pas avant, sinon le tuyau part avec le message dedans. Une
    # instance qui démarre (prise ouverte, fenêtre en construction)
    # ne lit qu'une fois sa boucle lancée: on l'attend — une instance
    # en route répond, elle, en quelques millisecondes
    prise.waitForReadyRead(ATTENTE_LECTURE_MS)
    prise.disconnectFromServer()
    if prise.state() != QLocalSocket.LocalSocketState.UnconnectedState:
        prise.waitForDisconnected(DELAI_MS)
    return True


def prendre_le_verrou(nom: Optional[str] = None) -> Optional[bool]:
    """Le verrou d'instance (un mutex Windows nommé, par utilisateur).

    Sous Windows, deux NeoDrive lancés ensemble (plusieurs fichiers
    ouverts d'un coup depuis l'Explorateur) ouvraient chacun LEUR
    prise: Windows accepte deux serveurs du même nom. Ils devenaient
    deux instances complètes, et la seconde écrasait la session de la
    première. Le mutex, lui, n'a qu'un premier.

    Rend True (ce lancement est le premier: verrou gardé jusqu'à la
    sortie), False (un autre NeoDrive le tient: il tourne ou démarre),
    None (pas de verrou possible ici: on fait comme avant)."""
    nom = nom or nom_du_serveur()
    if nom in _VERROUS:
        return True
    if os.name != 'nt':
        return None
    try:
        import ctypes
        from ctypes import wintypes
        noyau = ctypes.WinDLL('kernel32', use_last_error=True)
        noyau.CreateMutexW.restype = wintypes.HANDLE
        noyau.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL,
                                       wintypes.LPCWSTR]
        noyau.CloseHandle.argtypes = [wintypes.HANDLE]
        poignee = noyau.CreateMutexW(None, False, "Local\\" + nom)
        erreur = ctypes.get_last_error()
    except Exception:
        return None
    if not poignee:
        return None
    if erreur == 183:                  # ERROR_ALREADY_EXISTS
        noyau.CloseHandle(poignee)
        return False
    _VERROUS[nom] = poignee
    return True


def lacher_le_verrou(nom: str) -> None:
    """Rend le verrou (les tests; NeoDrive le garde jusqu'à la fin)."""
    poignee = _VERROUS.pop(nom, None)
    if poignee:
        try:
            import ctypes
            ctypes.WinDLL('kernel32').CloseHandle(poignee)
        except Exception:
            pass


class Accueil:
    """Les fichiers arrivés par la prise avant que la fenêtre soit
    prête: ils attendent ici, puis lui sont passés dans l'ordre."""

    def __init__(self):
        self.serveur: Optional[QLocalServer] = None
        self._attente: List[List[str]] = []
        self._cible: Optional[Callable[[List[str]], None]] = None

    def recevoir(self, fichiers: List[str]) -> None:
        if self._cible is not None:
            self._cible(list(fichiers))
        else:
            self._attente.append(list(fichiers))

    def brancher(self, cible: Callable[[List[str]], None]) -> None:
        self._cible = cible
        attente, self._attente = self._attente, []
        for fichiers in attente:
            cible(fichiers)


def demarrer(fichiers: List[str], nom: Optional[str] = None,
             attente_ms: int = ATTENTE_DEMARRAGE_MS,
             en_attente: Optional[Callable[[], None]] = None
             ) -> Tuple[Optional[Accueil], bool]:
    """Le début d'un lancement: rend (accueil, délégué).

    - une instance répond: on lui passe les fichiers, délégué=True;
    - sinon on prend le verrou et on ouvre la prise TOUT DE SUITE —
      avant la fenêtre (4 à 5 s): l'accueil garde ce qui arrive
      entre-temps (`Accueil.brancher` quand la fenêtre est là);
    - le verrou est déjà pris: une instance démarre à l'instant; on
      attend sa prise et on lui passe les fichiers. Si elle ne répond
      pas, on continue seul, sans prise (comme avant)."""
    nom = nom or nom_du_serveur()
    if deleguer(fichiers, nom):
        return None, True
    verrou = prendre_le_verrou(nom)
    if verrou is False:
        if en_attente is not None:
            en_attente()
        if deleguer(fichiers, nom, attente_ms=attente_ms):
            return None, True
        return Accueil(), False
    accueil = Accueil()
    accueil.serveur = servir(accueil.recevoir, nom)
    return accueil, False


def servir(sur_fichiers: Callable[[List[str]], None],
           nom: Optional[str] = None) -> Optional[QLocalServer]:
    """Ouvre la prise et appelle `sur_fichiers(liste)` à chaque
    lancement suivant — liste vide quand il n'apportait rien.

    Rend le serveur (à garder en vie), ou None si la prise n'a pas pu
    s'ouvrir: on fonctionne alors comme avant, sans instance unique."""
    nom = nom or nom_du_serveur()
    # une prise laissée par un NeoDrive tué reste enregistrée
    QLocalServer.removeServer(nom)
    serveur = QLocalServer()
    if not serveur.listen(nom):
        return None

    def _arrivee():
        while serveur.hasPendingConnections():
            prise = serveur.nextPendingConnection()
            if prise is None:
                continue

            def _lire(p=prise):
                if not p.canReadLine() and not p.bytesAvailable():
                    return
                brut = bytes(p.readAll()).decode('utf-8', 'replace')
                fichiers: List[str] = []
                for ligne in brut.splitlines():
                    ligne = ligne.strip()
                    if not ligne:
                        continue
                    try:
                        fichiers.extend(
                            json.loads(ligne).get('fichiers') or [])
                    except ValueError:
                        continue
                try:
                    p.write(b"ok\n")
                    p.flush()
                except RuntimeError:
                    pass
                p.disconnectFromServer()
                sur_fichiers([f for f in fichiers if os.path.isfile(f)])

            if prise.bytesAvailable():
                _lire()
            else:
                prise.readyRead.connect(_lire)

    serveur.newConnection.connect(_arrivee)
    return serveur
