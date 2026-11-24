"""Les chemins que lit la machine et ceux du poste.

Le réglage « remplacement de chemin » réécrit, à la génération, le
chemin d'un programme appelé (usermodule) pour la machine:

    S:\\CNC\\Gabarits\\Dessus.simpl
    → network:X:\\Gabarits\\Dessus.simpl

Le Canva 3D simule ce code-là: le simulateur cherchait alors
« network:X:\\… » sur le poste, ne le trouvait pas, et le programme
appelé disparaissait de la 3D. Même chose pour un programme de
l'atelier importé en blocs, dont les usermodule sont écrits à la façon
de la machine (« Appel prog externe » sans aperçu, sans outils).
`chemin_local` fait le chemin inverse — pour LIRE le fichier; le
chemin gardé dans l'opération reste celui de la machine.
"""

import os
import time
from typing import Dict, List, Tuple

#: [(début local, début machine)] — réglés par la fenêtre principale
_CORRESPONDANCES: List[Tuple[str, str]] = []
#: le préfixe des lecteurs réseau de la machine (« network:X:\\… »)
_RESEAU = 'network:'
#: {chemin: (instant, chemin du poste)} — le Canva redemande les mêmes
#: chemins à chaque dessin, et un lecteur réseau absent répond lentement
_VUS: Dict[str, Tuple[float, str]] = {}
_DUREE_VUS = 5.0


def _normaliser(chemin: str) -> str:
    # comme le générateur: « / » ou « \\ », sans le dernier séparateur
    return str(chemin or '').replace('/', '\\').rstrip('\\')


def regler(local: str, machine: str) -> None:
    """La correspondance du réglage (vide: aucune)."""
    _CORRESPONDANCES.clear()
    _VUS.clear()
    local, machine = _normaliser(local), _normaliser(machine)
    if local and machine:
        _CORRESPONDANCES.append((local, machine))


def _candidats(brut: str):
    bas = brut.lower()
    for local, machine in _CORRESPONDANCES:
        if bas.startswith(machine.lower() + '\\'):
            yield local + brut[len(machine):]
    # « network:X:\\ » de la machine: le même lecteur X: sur le poste
    if bas.startswith(_RESEAU):
        yield brut[len(_RESEAU):]


def chemin_local(chemin: str) -> str:
    """Le fichier du poste derrière un chemin de la machine, s'il
    existe; sinon le chemin tel quel."""
    chemin = str(chemin or '')
    if not chemin or os.path.exists(chemin):
        return chemin
    vu = _VUS.get(chemin)
    if vu is not None and time.monotonic() - vu[0] < _DUREE_VUS:
        return vu[1]
    trouve = chemin
    for candidat in _candidats(chemin.replace('/', '\\')):
        if os.path.exists(candidat):
            trouve = candidat
            break
    if len(_VUS) > 64:
        _VUS.clear()
    _VUS[chemin] = (time.monotonic(), trouve)
    return trouve
