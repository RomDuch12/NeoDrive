"""Commandes d'annulation/rétablissement du canvas (pile par volet).

Chaque commande garde de quoi défaire ET refaire un geste du dessin —
suppression, déplacement, ajout (coller). Le canvas expose les
helpers `_retirer_lot` / `_restaurer_lot` (suppression), et les
déplacements/ajouts se rejouent à l'identique.

Les commandes sont poussées après que le geste a déjà eu lieu: leur
premier `redo` (appelé par QUndoStack.push) ne doit donc rien
refaire. D'où `_premier`.
"""

from PySide6.QtGui import QUndoCommand


class _CommandeCanvas(QUndoCommand):
    """Base: le premier redo (au push) est neutre — le geste est fait."""

    def __init__(self, texte: str):
        super().__init__(texte)
        self._premier = True

    def redo(self):
        if self._premier:
            self._premier = False
            return
        self._refaire()

    def _refaire(self):
        raise NotImplementedError


class SupprimerCommande(_CommandeCanvas):
    """Suppression d'un lot d'entités (le lot capturé par le canvas)."""

    def __init__(self, canvas, lot):
        super().__init__(f"Supprimer {len(lot)} entité(s)")
        self._canvas = canvas
        self._lot = lot

    def undo(self):
        self._canvas._restaurer_lot(self._lot)

    def _refaire(self):
        self._canvas._retirer_lot(self._lot)


class DeplacerCommande(_CommandeCanvas):
    """Déplacement d'items de (dx, dy) en coordonnées de scène."""

    def __init__(self, canvas, items, dx: float, dy: float):
        super().__init__(f"Déplacer {len(items)} entité(s)")
        self._canvas = canvas
        self._items = list(items)
        self._dx = float(dx)
        self._dy = float(dy)

    def undo(self):
        self._canvas._decaler_items_scene(self._items, -self._dx, -self._dy)

    def _refaire(self):
        self._canvas._decaler_items_scene(self._items, self._dx, self._dy)


class AjouterCommande(_CommandeCanvas):
    """Ajout d'entités (coller): undo les retire, redo les remet."""

    def __init__(self, canvas, items, texte="Coller"):
        super().__init__(f"{texte} {len(items)} entité(s)")
        self._canvas = canvas
        self._items = list(items)

    def undo(self):
        self._canvas._retirer_items_simple(self._items)

    def _refaire(self):
        self._canvas._rajouter_items_simple(self._items)


class TracerCommande(_CommandeCanvas):
    """Une entité qu'on vient de tracer à la main.

    L'annuler, c'est exactement la supprimer — avec ce qui lui
    appartient (centre marqué, annotation attachée). On repasse donc
    par la machinerie de la suppression, éprouvée, plutôt que d'en
    écrire une seconde qui oublierait la moitié."""

    def __init__(self, canvas, item, etype: str = ""):
        super().__init__(f"Tracer {etype.lower()}".strip())
        self._canvas = canvas
        self._item = item
        self._lot = None

    def undo(self):
        self._lot = self._canvas._effacer_en_lot([self._item])
        self._canvas._selected_items.clear()
        self._canvas._scene.clearSelection()
        self._canvas.selection_changed.emit(0)

    def _refaire(self):
        if self._lot:
            self._canvas._restaurer_lot(self._lot)
            self._lot = None


class DeplacerSourisCommande(_CommandeCanvas):
    """Un déplacement fait À LA SOURIS (Qt a bougé les items lui-même).

    On rend les positions exactes d'avant, pas un delta rejoué: le
    glisser ne déplace que les items saisis, et rejouer un delta
    emporterait aussi leurs compagnons — le dessin ne reviendrait pas
    où il était."""

    def __init__(self, canvas, poses):
        """`poses`: [(item, (x_avant, y_avant), (x_apres, y_apres))]"""
        super().__init__(f"Déplacer {len(poses)} entité(s) à la souris")
        self._canvas = canvas
        self._poses = list(poses)

    def _poser(self, index: int):
        for item, avant, apres in self._poses:
            cible = avant if index == 0 else apres
            try:
                item.setPos(cible[0], cible[1])
            except RuntimeError:
                continue
        try:
            self._canvas._extend_scene_rect()
            if getattr(self._canvas, '_poignees', None):
                self._canvas._maj_poignees()      # elles suivent
        except Exception:
            pass

    def undo(self):
        self._poser(0)

    def _refaire(self):
        self._poser(1)


class RemplacerCommande(_CommandeCanvas):
    """Des entités remplacées par d'autres (nettoyer, congé, unir…):
    undo retire les nouvelles et rend les anciennes avec ce qui leur
    appartenait; redo refait l'échange."""

    def __init__(self, canvas, lot, neufs, texte: str = "Remplacer"):
        super().__init__(f"{texte} ({len(lot)} → {len(neufs)})")
        self._canvas = canvas
        self._lot = list(lot)
        self._neufs = list(neufs)

    def undo(self):
        self._canvas._retirer_items_simple(self._neufs)
        if self._lot:
            self._canvas._restaurer_lot(self._lot)

    def _refaire(self):
        if self._lot:
            self._canvas._retirer_lot(self._lot)
        self._canvas._rajouter_items_simple(self._neufs)


class GeometrieCommande(_CommandeCanvas):
    """La forme d'une entité retouchée aux poignées (un sommet déplacé,
    ajouté, supprimé): undo rend la forme d'avant, redo celle d'après."""

    def __init__(self, canvas, item, avant, apres, texte: str):
        super().__init__(texte)
        self._canvas = canvas
        self._item = item
        self._avant = avant
        self._apres = apres

    def undo(self):
        self._canvas._poser_geometrie(self._item, self._avant)

    def _refaire(self):
        self._canvas._poser_geometrie(self._item, self._apres)


class EchangerCommande(_CommandeCanvas):
    """Des entités posées (réseau, points, cotes, formes reconnues),
    en remplacement d'autres ou non: undo les retire AVEC ce qui leur
    appartient (centres marqués, groupes) et rend les anciennes; redo
    refait l'échange."""

    def __init__(self, canvas, lot, neufs, texte: str = "Poser"):
        super().__init__(f"{texte} ({len(neufs)})")
        self._canvas = canvas
        self._lot = list(lot)
        self._neufs = list(neufs)
        self._lot_neufs = None

    def undo(self):
        self._lot_neufs = self._canvas._effacer_en_lot(self._neufs)
        self._canvas._selected_items.clear()
        self._canvas._scene.clearSelection()
        if self._lot:
            self._canvas._restaurer_lot(self._lot)
        self._canvas.selection_changed.emit(0)

    def _refaire(self):
        if self._lot:
            self._canvas._retirer_lot(self._lot)
        if self._lot_neufs:
            self._canvas._restaurer_lot(self._lot_neufs)
            self._lot_neufs = None
