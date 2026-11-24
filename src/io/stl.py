"""Écrire et relire un STL binaire (des triangles, en mm).

Le STL est le format que tout lit — visionneuses, logiciels de CAO,
trancheurs: la pièce usinée simulée (ou la pièce STEP) part avec le
programme pour qu'on la regarde ailleurs.
"""

import struct

import numpy as np


def ecrire_stl(chemin: str, triangles, nom: str = "NeoDrive") -> int:
    """Écrit `triangles` (N, 3, 3) en STL binaire; rend N. Les normales
    sont calculées (sens des sommets)."""
    T = np.asarray(triangles, dtype=np.float32).reshape(-1, 3, 3)
    n = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
    norme = np.linalg.norm(n, axis=1)
    n = n / np.where(norme == 0, 1, norme)[:, None]
    enreg = np.zeros(len(T), dtype=[('n', '<f4', 3), ('v', '<f4', (3, 3)),
                                    ('attr', '<u2')])
    enreg['n'] = n
    enreg['v'] = T
    entete = (nom.encode('ascii', 'replace') + b" " * 80)[:80]
    with open(chemin, 'wb') as f:
        f.write(entete)
        f.write(struct.pack('<I', len(T)))
        f.write(enreg.tobytes())
    return int(len(T))


def lire_stl(chemin: str) -> np.ndarray:
    """Les triangles (N, 3, 3) d'un STL binaire."""
    with open(chemin, 'rb') as f:
        f.read(80)
        n = struct.unpack('<I', f.read(4))[0]
        donnees = np.frombuffer(f.read(50 * n), dtype=[
            ('n', '<f4', 3), ('v', '<f4', (3, 3)), ('attr', '<u2')])
    return np.asarray(donnees['v'], dtype=float)
