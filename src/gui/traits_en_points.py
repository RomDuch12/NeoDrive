"""Des traits en points, dans un tableau numpy: pour une vue qui bouge.

Pendant une rotation, l'œil suit la forme, pas le trait. Un programme de
400 000 sommets, c'est 12 000 polylignes: chacune un appel à Qt (extraire,
tracer), 0,16 s par image même en un pixel. Ici chaque sommet est un pixel posé
d'un bloc dans un tableau, les segments de plus d'un pixel sont remplis de
points: le coût ne dépend plus du nombre de polylignes.
"""

import numpy as np
from PySide6.QtGui import QColor

#: au-delà de ces sommets, une vue qui bouge trace en points
SOMMETS_EN_POINTS = 20_000
#: un tiret, un blanc (pixels)
TIRET, PERIODE = 4, 8


def couleur_premultipliee(couleur: QColor) -> int:
    """Le pixel ARGB32_Premultiplied d'une couleur."""
    a = couleur.alpha()
    return ((a << 24) | ((couleur.red() * a // 255) << 16)
            | ((couleur.green() * a // 255) << 8) | (couleur.blue() * a // 255))


def _poser(tampon, X, Y, pixel) -> None:
    hauteur, largeur = tampon.shape
    # (un seul test: un négatif devient un très grand entier)
    dedans = (X.astype(np.uint32) < largeur) & (Y.astype(np.uint32) < hauteur)
    tampon[Y[dedans], X[dedans]] = pixel


def segments_visibles(x0, y0, dx, dy, largeur, hauteur):
    """Les bornes (t0, t1) de chaque segment dans l'image; t1 <= t0 s'il n'y
    passe pas. Un long segment ne se remplit que sur ce qu'on en voit: à fort
    zoom, ses millions de pixels sont dehors."""
    t0 = np.zeros(len(x0))
    t1 = np.ones(len(x0))
    with np.errstate(divide='ignore', invalid='ignore'):
        for p, d, borne in ((x0, dx, largeur), (y0, dy, hauteur)):
            a = -p / d
            b = (borne - p) / d
            bas = np.minimum(a, b)
            haut = np.maximum(a, b)
            nul = d == 0.0
            dehors = nul & ((p < 0.0) | (p >= borne))
            bas[nul] = 0.0
            haut[nul] = 1.0
            haut[dehors] = -1.0
            t0 = np.maximum(t0, bas)
            t1 = np.minimum(t1, haut)
    return t0, t1


def tracer(tampon, x, y, debuts, pixel: int, tirets: bool = False) -> None:
    """Les polylignes (x, y)[debuts[i]:debuts[i+1]] dans `tampon` (uint32,
    (hauteur, largeur)), en coordonnées de l'image. `tirets`: des pointillés,
    comptés depuis le début de chaque segment."""
    if len(x) < 1:
        return
    hauteur, largeur = tampon.shape
    if not tirets:
        _poser(tampon, x.astype(np.int32), y.astype(np.int32), pixel)
    if len(x) < 2:
        return
    dx = np.diff(x)
    dy = np.diff(y)
    d = np.hypot(dx, dy)
    d[debuts[1:-1] - 1] = 0.0           # rien entre deux polylignes
    longs = np.flatnonzero(d > 1.0)
    if not len(longs):
        return
    x0, y0, ddx, ddy, dl = x[longs], y[longs], dx[longs], dy[longs], d[longs]
    t0, t1 = segments_visibles(x0, y0, ddx, ddy, largeur, hauteur)
    vus = t1 > t0
    if not vus.any():
        return
    x0, y0, ddx, ddy, dl, t0, t1 = (a[vus] for a in (x0, y0, ddx, ddy, dl,
                                                     t0, t1))
    n = np.ceil(dl * (t1 - t0)).astype(np.int64) + 1
    rang = np.repeat(np.arange(len(n)), n)
    k = np.arange(int(n.sum())) - (np.cumsum(n) - n)[rang]
    t = t0[rang] + (t1 - t0)[rang] * (k / n[rang])
    if tirets:
        garde = (k % PERIODE) < TIRET
        rang, t = rang[garde], t[garde]
    _poser(tampon, (x0[rang] + t * ddx[rang]).astype(np.int32),
           (y0[rang] + t * ddy[rang]).astype(np.int32), pixel)
