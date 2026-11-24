"""Polygones Qt remplis d'un bloc depuis numpy.

Construire un QPolygonF point par point (un QPointF Python par sommet)
coûtait 0,6 s pour 200 000 points: c'était l'essentiel du temps d'une
image du Canva 3D sur un gros parcours. Ici le tableau numpy est copié
directement dans le stockage du polygone (0,003 s).

Le stockage n'est écrit que si on a vérifié, une fois, en LECTURE, que
`QPolygonF.data()` le désigne bien; sinon (autre version de PySide), on
revient à la construction point par point — plus lente, jamais fausse.
"""

import numpy as np
from PySide6.QtCore import QPointF
from PySide6.QtGui import QPolygonF

try:
    # importé une fois: un `import` dans la fonction repasse par le
    # crochet d'import de shiboken à chaque polygone (7 µs chacun)
    from shiboken6 import VoidPtr as _VoidPtr, getCppPointer as _pointeur
except Exception:           # pragma: no cover — PySide sans shiboken6
    _VoidPtr = _pointeur = None

#: None: pas encore vérifié; True/False: le stockage s'écrit directement
_DIRECT = None


def _tampon(poly: QPolygonF, n: int, ecriture: bool):
    """Les n points du polygone, vus comme 2n doubles (sans copie)."""
    return np.frombuffer(memoryview(_VoidPtr(
        _pointeur(poly.data())[0], n * 16, ecriture)), dtype=np.float64)


def stockage_direct() -> bool:
    """`data()` d'un QPolygonF désigne-t-il ses points (x, y en double,
    à la suite)? Vérifié une fois, sans rien écrire."""
    global _DIRECT
    if _DIRECT is None:
        try:
            essai = QPolygonF([QPointF(1.5, 2.5), QPointF(3.5, 4.5),
                               QPointF(5.5, 6.5)])
            lu = _tampon(essai, 3, False).tolist()
            _DIRECT = lu == [1.5, 2.5, 3.5, 4.5, 5.5, 6.5]
        except Exception:
            _DIRECT = False
    return _DIRECT


def polygone(xy) -> QPolygonF:
    """Le QPolygonF des points `xy` (tableau (N, 2), ou deux colonnes)."""
    if not (isinstance(xy, np.ndarray) and xy.dtype == np.float64):
        xy = np.asarray(xy, dtype=np.float64)
    n = len(xy)
    if n and (_DIRECT or (_DIRECT is None and stockage_direct())):
        try:
            poly = QPolygonF()
            poly.resize(n)
            _tampon(poly, n, True)[:] = xy.reshape(-1)
            return poly
        except Exception:
            pass
    return QPolygonF([QPointF(a, b) for a, b in xy.tolist()])


def polygone_xy(px, py) -> QPolygonF:
    """Le QPolygonF de deux tableaux de coordonnées."""
    return polygone(np.column_stack([np.asarray(px, dtype=np.float64),
                                     np.asarray(py, dtype=np.float64)]))
