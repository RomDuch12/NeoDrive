"""L'activité de l'utilisateur: le moment de son dernier geste (clic,
touche, molette) — les calculs de basse priorité (régénération du SimPL,
relecture du Canva 3D) attendent qu'il marque une pause.

Novembre 2026 (RomDuch): « le calcul de maj simpl peut être différé
(prio basse, code couleur reflétant l'état) pour conserver de la
réactivité appli ». Un clic sur l'opé suivante ne doit pas tomber sur
une régénération lancée par la modification d'avant.

Le veilleur n'est posé sur l'application que tant qu'un calcul attend
(`veiller` / `relacher`): un filtre d'événements global coûte un appel
Python par événement, qu'on ne paie pas quand tout est à jour.
"""

import time

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication

#: les gestes qui disent « l'utilisateur est là » (les mouvements de la
#: souris sans bouton n'en sont pas: survoler n'est pas travailler)
_GESTES = frozenset((
    QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
    QEvent.Type.MouseButtonDblClick, QEvent.Type.KeyPress,
    QEvent.Type.KeyRelease, QEvent.Type.Wheel))

#: la pause (s) après le dernier geste au-delà de laquelle un calcul de
#: basse priorité peut passer
PAUSE = 0.35


class _Veilleur(QObject):

    def __init__(self):
        super().__init__()
        self.dernier = 0.0

    def eventFilter(self, obj, ev):          # noqa: N802 (Qt)
        if ev.type() in _GESTES:
            self.dernier = time.monotonic()
        return False


_veilleur = None
_demandeurs = set()


def veiller(qui, geste: bool = True) -> None:
    """`qui` attend une pause: le veilleur se pose (s'il ne l'est pas)
    et le geste qui a lancé l'attente compte comme le dernier — sauf
    `geste` faux: une attente qui ne vient pas d'un geste (l'image
    voisine du Canva 3D, planifiée par un repeint) ne retarde pas les
    autres."""
    global _veilleur
    app = QApplication.instance()
    if app is None:
        return
    if _veilleur is None:
        _veilleur = _Veilleur()
    if not _demandeurs:
        app.installEventFilter(_veilleur)
    _demandeurs.add(id(qui))
    if geste:
        _veilleur.dernier = time.monotonic()


def relacher(qui) -> None:
    """`qui` n'attend plus: sans autre demandeur, le veilleur s'en va."""
    _demandeurs.discard(id(qui))
    if not _demandeurs and _veilleur is not None:
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(_veilleur)


def depuis_dernier_geste() -> float:
    """Secondes depuis le dernier geste vu (l'infini s'il n'y en a pas)."""
    if _veilleur is None or not _veilleur.dernier:
        return float('inf')
    return time.monotonic() - _veilleur.dernier


def occupe(pause: float = None) -> bool:
    """L'utilisateur est-il en plein geste: un bouton de la souris
    enfoncé (il glisse, il tire une poignée) ou un geste il y a moins de
    `pause` secondes?"""
    try:
        if QApplication.mouseButtons() != Qt.MouseButton.NoButton:
            return True
    except Exception:
        pass
    return depuis_dernier_geste() < (PAUSE if pause is None else pause)


def attente_restante(pause: float = None) -> int:
    """Les millisecondes qu'il reste avant la fin de la pause (au moins
    30: on revient voir)."""
    p = PAUSE if pause is None else pause
    reste = p - depuis_dernier_geste()
    return max(30, int(reste * 1000) + 5)
