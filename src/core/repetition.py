# -*- coding: utf-8 -*-
"""La répétition d'une opération: une grille, et la grille de la
grille.

NbX × PasX, NbY × PasY répètent l'usinage en quadrillage; Nb2X ×
Pas2X, Nb2Y × Pas2Y reprennent ce quadrillage entier — deux
niveaux: « (2 en X entraxe 20, 4 en Y entraxe 10) × 2 en X entraxe
100 » fait seize positions. Le générateur, le canvas et l'estimation
de temps lisent la même liste de positions, dans le même ordre.
"""

from typing import Any, Dict, List, Sequence, Tuple

#: les clés des deux niveaux, dans l'ordre du formulaire
CLES = ('repeat_x_count', 'repeat_x_step', 'repeat_y_count',
        'repeat_y_step', 'repeat2_x_count', 'repeat2_x_step',
        'repeat2_y_count', 'repeat2_y_step')


def _entier(params: Dict[str, Any], cle: str, defaut: int = 1) -> int:
    try:
        return max(1, int(params.get(cle, defaut) or defaut))
    except (TypeError, ValueError):
        return defaut


def _nombre(params: Dict[str, Any], cle: str, defaut: float = 0.0) -> float:
    try:
        return float(params.get(cle, defaut) or 0.0)
    except (TypeError, ValueError):
        return defaut


def grille(params: Dict[str, Any]) -> Tuple[int, float, int, float,
                                            int, float, int, float]:
    """(nbX, pasX, nbY, pasY, nb2X, pas2X, nb2Y, pas2Y) — les anciens
    `repeat_count` / `repeat_shift_x` / `repeat_shift_y` sont lus."""
    nx = _entier(params, 'repeat_x_count', _entier(params, 'repeat_count'))
    sx = _nombre(params, 'repeat_x_step',
                 _nombre(params, 'repeat_shift_x'))
    ny = _entier(params, 'repeat_y_count')
    sy = _nombre(params, 'repeat_y_step',
                 _nombre(params, 'repeat_shift_y'))
    return (nx, sx, ny, sy,
            _entier(params, 'repeat2_x_count'),
            _nombre(params, 'repeat2_x_step'),
            _entier(params, 'repeat2_y_count'),
            _nombre(params, 'repeat2_y_step'))


def positions(params: Dict[str, Any]) -> List[Tuple[float, float]]:
    """Les décalages (dx, dy) de chaque position, (0, 0) d'abord.

    Ordre d'usinage: rangée par rangée dans la grille, puis la grille
    suivante — Y puis X à chaque niveau, comme avant."""
    nx, sx, ny, sy, n2x, s2x, n2y, s2y = grille(params)
    sortie = []
    for iy2 in range(n2y):
        for ix2 in range(n2x):
            for iy in range(ny):
                for ix in range(nx):
                    sortie.append((round(ix * sx + ix2 * s2x, 4),
                                   round(iy * sy + iy2 * s2y, 4)))
    return sortie


def compte(params: Dict[str, Any]) -> int:
    nx, _sx, ny, _sy, n2x, _s2x, n2y, _s2y = grille(params)
    return nx * ny * n2x * n2y


def deltas(pos: Sequence[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """Le pas d'une position à la suivante — ce que ShiftWcsInc
    reçoit — et, en dernier, le retour à l'origine."""
    sortie = []
    for k in range(1, len(pos)):
        sortie.append((round(pos[k][0] - pos[k - 1][0], 4),
                       round(pos[k][1] - pos[k - 1][1], 4)))
    if pos:
        sortie.append((round(-pos[-1][0], 4), round(-pos[-1][1], 4)))
    return sortie


def shift_wcs(dx: float, dy: float) -> str:
    """La ligne ShiftWcsInc d'un pas, ou "" s'il est nul."""
    # « X=12.0 »: l'écriture des programmes d'avant, à l'identique
    parts = []
    if abs(dx) > 1e-9:
        parts.append(f"X={float(dx)}")
    if abs(dy) > 1e-9:
        parts.append(f"Y={float(dy)}")
    return f"    ShiftWcsInc {' '.join(parts)}" if parts else ""


def emettre(body_lines: Sequence[str], params: Dict[str, Any],
            ligne_safe_rapid: str = "") -> List[str]:
    """Le corps répété à chaque position, un ShiftWcsInc entre deux,
    et le retour à l'origine. `ligne_safe_rapid`: si donnée, elle est
    reposée après chaque décalage (les fonctions machine partent de
    la position courante)."""
    pos = positions(params)
    if len(pos) <= 1:
        return list(body_lines)
    corps = []
    for item in body_lines:
        corps.extend(str(item).split("\n"))
    # le SafeRapid initial est déjà dans le corps; après un décalage
    # on le repose s'il est demandé
    out = []
    pas = deltas(pos)
    total = len(pos)
    for k in range(total):
        if k > 0:
            ligne = shift_wcs(*pas[k - 1])
            if ligne:
                out.append(ligne)
                if ligne_safe_rapid and not (
                        corps and corps[0].strip().startswith("SafeRapid")):
                    out.append(ligne_safe_rapid)
        out.append(f"    # ── Répétition {k + 1}/{total} ──")
        out.extend(corps)
    retour = shift_wcs(*pas[-1])
    if retour:
        out.append("    # Retour origine")
        out.append(retour)
    return out
