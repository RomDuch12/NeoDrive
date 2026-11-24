"""
Canvas DXF basé sur QGraphicsView/QGraphicsScene.
Gère le rendu, zoom, pan, grille, accrochage, et les outils de dessin.

Corrections:
- Zoom centré sur le pointeur souris (AnchorUnderMouse)
- fit_all fonctionne pour dessins hors-origine
- SceneRect dynamique étendue si nécessaire
- Détection centres exposée publiquement
- Support dessin par centre+dimensions via draw_shape_from_params()
"""

import math
import re
from PySide6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsItem,
    QGraphicsEllipseItem, QGraphicsPolygonItem, QGraphicsLineItem,
    QGraphicsRectItem,
    QGraphicsPathItem, QGraphicsTextItem, QGraphicsItemGroup
)
from PySide6.QtCore import Qt, Signal, QPointF, QRectF, QLineF
from PySide6.QtGui import (
    QPen, QBrush, QColor, QPainter, QPainterPath, QFont,
    QWheelEvent, QMouseEvent, QKeyEvent, QTransform, QUndoStack
)
from typing import Optional, List, Tuple, Dict
# ezdxf n'est chargé qu'à la 1re ouverture/export DXF: son import
# coûte ~600 ms, soit l'essentiel du temps de démarrage de NeoDrive,
# alors que beaucoup de sessions ne touchent jamais un DXF.
ezdxf = None
ezdxf_recover = None


def _load_ezdxf():
    """Importe ezdxf à la demande (idempotent)."""
    global ezdxf, ezdxf_recover
    if ezdxf is None:
        import ezdxf as _ezdxf
        from ezdxf import recover as _recover
        ezdxf = _ezdxf
        ezdxf_recover = _recover
    return ezdxf


# Couleurs pour les calques DXF (AutoCAD color index)
ACI_COLORS = {
    0: "#ffffff", 1: "#ff0000", 2: "#ffff00", 3: "#00ff00",
    4: "#00ffff", 5: "#0000ff", 6: "#ff00ff", 7: "#ffffff",
    8: "#808080", 9: "#c0c0c0",
}


def aci_to_qcolor(aci: int) -> QColor:
    """Convertit un ACI en QColor."""
    hex_color = ACI_COLORS.get(aci, "#ffffff")
    return QColor(hex_color)


def _least_squares_circle(pts):
    """Ajustement de cercle par moindres carrés (Kåsa method).
    Résout: minimise sum((xi-cx)^2 + (yi-cy)^2 - r^2)^2
    Retourne (cx, cy, r).
    """
    n = len(pts)
    if n < 3:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return sum(xs) / n, sum(ys) / n, 0.0

    # Construire le système linéaire: A * [cx, cy, D]^T = b
    # xi^2 + yi^2 = 2*cx*xi + 2*cy*yi + D  (D = r^2 - cx^2 - cy^2)
    sx = sum(p[0] for p in pts)
    sy = sum(p[1] for p in pts)
    sxx = sum(p[0]**2 for p in pts)
    syy = sum(p[1]**2 for p in pts)
    sxy = sum(p[0]*p[1] for p in pts)
    sxxx = sum(p[0]**3 for p in pts)
    syyy = sum(p[1]**3 for p in pts)
    sxyy = sum(p[0]*p[1]**2 for p in pts)
    sxxy = sum(p[0]**2*p[1] for p in pts)

    a11 = 2 * (sxx - sx * sx / n)
    a12 = 2 * (sxy - sx * sy / n)
    a21 = a12
    a22 = 2 * (syy - sy * sy / n)

    b1 = sxxx + sxyy - sx * (sxx + syy) / n
    b2 = syyy + sxxy - sy * (sxx + syy) / n

    det = a11 * a22 - a12 * a21
    if abs(det) < 1e-12:
        # Dégénéré: fallback au centroïde
        return sx / n, sy / n, 0.0

    cx = (b1 * a22 - b2 * a12) / det
    cy = (a11 * b2 - a21 * b1) / det
    r = math.sqrt(sum((p[0] - cx)**2 + (p[1] - cy)**2 for p in pts) / n)
    return cx, cy, r


class _CosmeticScene(QGraphicsScene):
    """Scène dont TOUT trait est cosmétique.

    Un pinceau cosmétique garde une épaisseur constante EN PIXELS quel
    que soit le zoom. L'appliquer après coup ne suffisait pas: chaque
    nouveau tracé (marqueurs d'opération, symboles, séquences) revenait
    à des pinceaux en unités de scène, qui grossissent au zoom. On
    l'impose donc à la CRÉATION, quel que soit le chemin de code.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.line_width_px = 1.0
        self.thin_factor = 1.0      # utilisé pour la grille

    def _fix(self, item):
        try:
            pen = QPen(item.pen())
        except (AttributeError, RuntimeError):
            return item
        pen.setCosmetic(True)
        pen.setWidthF(max(0.1, self.line_width_px * self.thin_factor))
        item.setPen(pen)
        return item

    def addLine(self, *args, **kwargs):
        return self._fix(super().addLine(*args, **kwargs))

    def addRect(self, *args, **kwargs):
        return self._fix(super().addRect(*args, **kwargs))

    def addEllipse(self, *args, **kwargs):
        return self._fix(super().addEllipse(*args, **kwargs))

    def addPath(self, *args, **kwargs):
        return self._fix(super().addPath(*args, **kwargs))

    def addPolygon(self, *args, **kwargs):
        return self._fix(super().addPolygon(*args, **kwargs))


class DxfCanvas(QGraphicsView):
    """Vue/scène DXF avec zoom, pan, grille, et coordonnées."""

    coordinate_picked = Signal(float, float)  # x, y en coordonnées DXF
    mouse_position = Signal(float, float)  # position souris en coords DXF
    circles_detected = Signal(list)  # liste de dicts {x, y, radius, ...}
    selection_changed = Signal(int)  # nombre d'entités sélectionnées
    entity_info = Signal(str)  # spécifications entité sélectionnée
    ruler_measured = Signal(float)  # distance mesurée en mm
    op_point_clicked = Signal(str, int)  # (source, index) marqueur cliqué
    nudge_step_changed = Signal(float)  # pas des flèches, en mm
    pas_focus_demande = Signal()        # Ctrl+flèche: régler le pas
    resize_requested = Signal()         # F2 sur la sélection
    texte_demande = Signal(float, float)  # outil Texte: clic en x, y
    texte_grave_demande = Signal(float, float)  # texte vectorise
    ortho_change = Signal(float)  # F8: le pas de l'ortho (0: libre)
    #: clic droit pendant un outil (règle, dessin, pipette, outil à clic,
    #: symbole à poser): le panneau rend le mode sélection
    retour_selection = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = _CosmeticScene(self)
        self.setScene(self._scene)
        # Épaisseur de trait à l'écran (px) et en sortie papier/image
        self._line_width_px = 1.0
        self._output_line_px = 1.0
        self._origin_items = []

        # Configuration
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing |
            QPainter.RenderHint.SmoothPixmapTransform)
        # IMPORTANT: zoom centré sur le pointeur souris
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(
            QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setBackgroundBrush(QBrush(QColor("#11111b")))

        # État
        self._zoom = 1.0
        self._pan_active = False
        self._pan_start = QPointF()
        self._pick_mode = False
        self._show_all_ops = True
        # Marqueurs de centres détectés: masqués par défaut (pollution
        # visuelle) — toggle 'Centres' dans la toolbar DXF
        self._centers_visible = False
        self._ruler_mode = False
        self._ruler_points = []
        self._draw_tool: Optional[str] = None
        self._draw_points: List[QPointF] = []
        self._temp_item: Optional[QGraphicsItem] = None
        self._snap_enabled = True
        self._snap_radius = 10.0
        #: accrochages OBJET (extrémité, milieu, centre, intersection,
        #: quadrant, perpendiculaire, proche — src.core.accrochage)
        self._accrochages = True
        #: la marque du point accroché (carré, triangle, cercle…)
        self._marque_accroche = None
        #: tracés des entités pour l'accrochage: {id: (signature,
        #: entité, (polylignes, cercles))}
        self._geo_cache: Dict[int, tuple] = {}
        #: la dernière prise d'accrochage (accrochage.Prise) ou None
        self.derniere_prise = None
        #: ortho / angles imposés: le pas en degrés (0: libre)
        self._ortho_pas = 0.0
        #: les contraintes géométriques du dessin: [{'genre', 'refs',
        #: 'valeur'}] — refs: (entité, indice) d'un trait, d'un sommet,
        #: ou (entité,) d'un cercle
        self._contraintes: List[dict] = []
        self._choix_contrainte: List[tuple] = []
        self._glyphes_contraintes: List[QGraphicsItem] = []
        self.glyphes_visibles = True
        #: demander la valeur d'une cote pilotante: f(genre, actuelle)
        #: → valeur ou None (posé par le panneau; sans lui, l'actuelle)
        self.demander_valeur = None
        #: poignées d'édition des sommets de l'entité sélectionnée
        self._poignees: List[QGraphicsItem] = []
        self._poignee_item = None
        #: le sommet en cours de déplacement: {'item', 'indices',
        #: 'avant'} — ou None
        self._poignee_drag = None
        self.selection_changed.connect(lambda _n: self._maj_poignees())
        self._grid_visible = True
        self._grid_spacing = 1.0
        self._dxf_items: List[QGraphicsItem] = []
        self._center_markers: List[QGraphicsItem] = []
        #: ce qui appartient à une entité et la suit partout:
        #: {id(entité): [marqueur de centre, annotation, …]}
        self._attaches: Dict[int, List[QGraphicsItem]] = {}
        #: groupes de tracés: {clé: [entités]}. Prendre un membre,
        #: c'est prendre tout le groupe — un logo importé en trente
        #: polylignes se déplace d'un bloc.
        self._groupes: Dict[str, List[QGraphicsItem]] = {}
        self._groupe_de: Dict[int, str] = {}
        self._detected_circles: List[Dict] = []
        self._grid_items: List[QGraphicsItem] = []
        # Métadonnées par item (pour sélection et détection)
        self._item_metadata: Dict[int, Dict] = {}  # id(item) → metadata
        # Calques: chaque entité de _dxf_items est taguée par source.
        # 'dxf' = fichier importé, 'drawn' = dessin interne,
        # 'smb' = symbole importé. (Les overlays d'opération ont leur
        # propre visibilité via _show_all_ops.)
        self._item_layer: Dict[int, str] = {}  # id(item) → layer
        self._layer_visible: Dict[str, bool] = {
            'dxf': True, 'drawn': True, 'smb': True}
        # Sélection d'entités
        # La sélection est le comportement PAR DÉFAUT: le bouton
        # « Sél. » ne faisait qu'armer ce qu'on attend d'un clic.
        self._select_mode: bool = True
        self._selected_items: List[QGraphicsItem] = []
        self._original_pens: Dict[int, QPen] = {}  # styles originaux
        # Pile d'annulation/rétablissement DU DESSIN (par volet):
        # suppression, déplacement, coller. Ctrl+Z/Y agit dessus quand
        # le canvas a le focus (la liste d'opés a sa propre pile).
        self._pile_undo = QUndoStack(self)
        self._pile_undo.setUndoLimit(100)
        # Contour du brut (@ WorkpieceGeometry @): repère de cadrage
        self._workpiece_items: List[QGraphicsItem] = []
        self._workpiece_rect: Optional[QRectF] = None
        # Une couleur par outil + sa légende: sur un plan, c'est
        # l'outil qui distingue les parcours, pas la profondeur
        self._tool_library = None
        self._tool_colors: Dict[str, QColor] = {}
        self._tool_labels: Dict[str, str] = {}
        self._legend_items: List[QGraphicsItem] = []
        #: la légende est-elle montrée ? (bouton « Légende »)
        self._legend_visible: bool = False
        #: légende: inclure aussi les opérations hors matière ?
        self._legende_hors_matiere = False
        #: lignes de légende: (clé outil, nom d'opération, libellé)
        self._legend_rows: list = []
        # Items d'opérations dessinés sur le canvas
        self._op_point_items: List[QGraphicsItem] = []
        self._op_label_items: List[QGraphicsItem] = []  # étiquettes texte
        self._op_labels_visible: bool = False
        #: ids d'opérations dont on masque annotations ET ligne de
        #: légende (bouton par opération, à droite de l'œil)
        self._annot_masquees: set = set()
        #: vrai pendant le tracé d'une opé dont les annot sont masquées
        self._masquer_annot_courante: bool = False
        self._op_point_positions: List[tuple] = []  # (x, y_scene, index)
        self._op_points_source: str = ""
        # Sélection par rectangle (rubber band)
        self._rubber_band_active = False
        self._rubber_band_origin: Optional[QPointF] = None
        self._rubber_band_item: Optional[QGraphicsRectItem] = None

        # Scène initiale - large pour ne pas bloquer le scroll
        self._scene.setSceneRect(-5000, -5000, 10000, 10000)
        self._draw_grid()
        self._draw_origin()

        # Zoom initial
        self.setTransform(QTransform.fromScale(5, 5))
        self._zoom = 5.0

    def _draw_grid(self):
        """Dessine la grille de fond (visibilité appliquée aux items)."""
        # la grille reste plus fine que le dessin
        self._scene.thin_factor = 0.6
        pen = QPen(QColor("#1e1e2e"), 0.1)
        spacing = self._grid_spacing
        extent = 500

        for x in range(int(-extent), int(extent) + 1):
            xf = x * spacing
            item = self._scene.addLine(
                xf, -extent * spacing, xf, extent * spacing, pen)
            self._grid_items.append(item)
        for y in range(int(-extent), int(extent) + 1):
            yf = y * spacing
            item = self._scene.addLine(
                -extent * spacing, yf, extent * spacing, yf, pen)
            self._grid_items.append(item)
        self._scene.thin_factor = 1.0    # retour à l'épaisseur dessin
        if not self._grid_visible:
            for item in self._grid_items:
                item.setVisible(False)

    def set_grid_spacing(self, spacing: float):
        """Change le pas de grille et REDESSINE la grille.
        (Modifier _grid_spacing seul ne changeait que le snap,
        pas les lignes affichées.)"""
        if spacing <= 0:
            return
        self._grid_spacing = spacing
        for item in self._grid_items:
            self._scene.removeItem(item)
        self._grid_items.clear()
        self._draw_grid()
        self.viewport().update()

    def _draw_origin(self):
        """Dessine le repère d'origine."""
        pen_x = QPen(QColor("#f38ba8"), 0.3)
        ix = self._scene.addLine(0, 0, 20, 0, pen_x)
        pen_y = QPen(QColor("#a6e3a1"), 0.3)
        iy = self._scene.addLine(0, 0, 0, -20, pen_y)
        pen_o = QPen(QColor("#cdd6f4"), 0.2)
        io = self._scene.addEllipse(-0.5, -0.5, 1, 1, pen_o)
        # Repérés pour être exclus de l'étendue à l'impression
        self._origin_items = [ix, iy, io]

    def imports_dxf(self) -> list:
        """Les fichiers importés dans ce dessin (DXF, STEP, SVG, PDF…),
        dans l'ordre: [{'cle', 'nom', 'chemin', 'visible', 'genre'}] —
        un onglet chacun."""
        return list(getattr(self, '_imports_dxf', []))

    def activer_piece(self, cle: str) -> bool:
        """La pièce 3D de cet import devient la pièce ACTIVE (celle
        qu'on usine, dont on choisit les faces); rend vrai si elle a
        changé."""
        imp = next((i for i in getattr(self, '_imports_dxf', [])
                    if i['cle'] == cle), None)
        source = (imp or {}).get('source_3d')
        if source is None or source is self._source_3d:
            return False
        self._source_3d = source
        return True

    def set_import_visible(self, cle: str, visible: bool) -> int:
        """L'œil d'un DXF importé: ses entités seules (le calque DXF
        entier garde son propre œil)."""
        n = 0
        for imp in getattr(self, '_imports_dxf', []):
            if imp['cle'] == cle:
                imp['visible'] = bool(visible)
        calque = self._layer_visible.get('dxf', True)
        source = getattr(self, '_item_source', {})
        for item in self._dxf_items:
            if source.get(id(item)) == cle:
                try:
                    item.setVisible(bool(visible) and calque)
                except RuntimeError:
                    continue
                n += 1
        self.viewport().update()
        return n

    def retirer_import(self, cle: str) -> int:
        """Ôte du dessin les entités d'un import (et ses centres). Une
        pièce STEP emporte sa vue en volume."""
        source = getattr(self, '_item_source', {})
        imp = next((i for i in getattr(self, '_imports_dxf', [])
                    if i['cle'] == cle), None)
        for c in (imp or {}).get('cercles', []):
            if c in self._detected_circles:
                self._detected_circles.remove(c)
        if (imp or {}).get('genre') == 'step' and (
                imp.get('source_3d') is None
                or imp.get('source_3d') is self._source_3d):
            # la pièce active part: la dernière qui reste devient active
            autres = [i for i in getattr(self, '_imports_dxf', [])
                      if i['cle'] != cle and i.get('source_3d')]
            self._source_3d = autres[-1]['source_3d'] if autres else None
        garde, n = [], 0
        for item in self._dxf_items:
            if source.get(id(item)) == cle:
                try:
                    self._scene.removeItem(item)
                except RuntimeError:
                    pass
                source.pop(id(item), None)
                self._item_layer.pop(id(item), None)
                if item in self._selected_items:
                    self._selected_items.remove(item)
                centre = self._item_metadata.pop(id(item), None)
                if centre is not None and centre in self._detected_circles:
                    self._detected_circles.remove(centre)
                n += 1
            else:
                garde.append(item)
        self._dxf_items = garde
        self._imports_dxf = [i for i in getattr(self, '_imports_dxf', [])
                             if i['cle'] != cle]
        self.circles_detected.emit(self._detected_circles)
        self.viewport().update()
        return n

    def load_dxf(self, filepath: str, ajouter: bool = False):
        """Charge et affiche un fichier DXF. `ajouter`: superposé au
        dessin en place (ses entités, ses centres et leurs Pz/Ø
        restent), son propre onglet de calque."""
        import os as _os
        _load_ezdxf()
        try:
            doc = ezdxf.readfile(filepath)
        except Exception:
            # Fichier non conforme: tentative de récupération
            try:
                doc, _auditor = ezdxf_recover.readfile(filepath)
            except Exception as e:
                raise RuntimeError(f"Impossible de lire le DXF: {e}")

        avant = None
        if ajouter:
            avant = (list(self._dxf_items), list(self._detected_circles),
                     dict(self._item_metadata))
        else:
            self.clear_dxf()
        if not hasattr(self, '_imports_dxf'):
            self._imports_dxf = []
        if not hasattr(self, '_item_source'):
            self._item_source = {}
        cles = {i['cle'] for i in self._imports_dxf}
        k = len(self._imports_dxf) + 1
        while f"dxf{k}" in cles:
            k += 1
        cle_import = f"dxf{k}"
        deja = set(map(id, self._dxf_items))
        msp = doc.modelspace()

        # Expanser les blocs INSERT en entités monde (les perçages des
        # DXF réels sont très souvent dans des blocs)
        entities = list(self._iter_entities(msp))

        # ── Gros fichier: progression + annulation + rendu par lots ──
        progress = None
        if len(entities) > 800:
            from PySide6.QtWidgets import QProgressDialog, QApplication
            progress = QProgressDialog(
                f"Chargement DXF ({len(entities)} entités)...",
                "Annuler", 0, len(entities), self)
            progress.setWindowTitle("Import DXF")
            progress.setMinimumDuration(400)
            progress.setWindowModality(
                Qt.WindowModality.WindowModal)

        merge_mode = len(entities) > self._MERGE_THRESHOLD
        cancelled = False
        if merge_mode:
            cancelled = self._render_entities_merged(entities, progress)
        else:
            self.setUpdatesEnabled(False)
            try:
                for i, entity in enumerate(entities):
                    item = self._render_entity(entity)
                    if item:
                        self._register_item(item, 'dxf')
                    if progress is not None and i % 200 == 0:
                        progress.setValue(i)
                        from PySide6.QtWidgets import QApplication
                        QApplication.processEvents()
                        if progress.wasCanceled():
                            cancelled = True
                            entities = entities[:i + 1]
                            break
            finally:
                self.setUpdatesEnabled(True)

        # Détection des centres de cercles/arcs (blocs inclus)
        self._detect_centers(entities)
        if avant is not None:
            # ce qui était là reste, avec ses centres et leurs Pz/Ø
            anciens, cercles, meta = avant
            connus = {(round(c.get('x', 0), 3), round(c.get('y', 0), 3))
                      for c in cercles}
            nouveaux = [c for c in self._detected_circles
                        if (round(c.get('x', 0), 3),
                            round(c.get('y', 0), 3)) not in connus]
            self._detected_circles = cercles + nouveaux
            meta.update(self._item_metadata)
            self._item_metadata = meta
        # chaque entité sait de quel import elle vient
        for item in self._dxf_items:
            if id(item) not in deja:
                self._item_source[id(item)] = cle_import
        self._imports_dxf.append({'cle': cle_import,
                                  'nom': _os.path.basename(filepath),
                                  'chemin': filepath, 'visible': True})
        if progress is not None:
            progress.setValue(progress.maximum())
        if cancelled:
            self.entity_info.emit(
                "Chargement interrompu — dessin partiel")

        # Étendre la scène si nécessaire
        self._extend_scene_rect()

        # Ajuster la vue sur le dessin importé
        self.fit_all()

    #: calques dont les entités se manipulent à la souris — ce que
    #: NOUS avons dessiné, pas ce qui vient d'un fichier
    _CALQUES_MANIPULABLES = ('drawn', 'texte')

    def _register_item(self, item, layer: str):
        """Enregistre une entité dans _dxf_items avec son calque.

        Une entité dessinée ici se sélectionne, se déplace et se met à
        la cote: c'est notre dessin, on doit pouvoir le reprendre."""
        self._dxf_items.append(item)
        self._item_layer[id(item)] = layer
        item.setVisible(self._layer_visible.get(layer, True))
        if layer in self._CALQUES_MANIPULABLES:
            item.setFlag(
                QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
            item.setFlag(
                QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)

    def set_layer_visible(self, layer: str, visible: bool):
        """Affiche/masque toutes les entités d'un calque
        ('dxf', 'drawn', 'smb')."""
        self._layer_visible[layer] = visible
        # un DXF importé masqué par son propre œil le reste
        caches = {i['cle'] for i in getattr(self, '_imports_dxf', [])
                  if not i.get('visible', True)}
        source = getattr(self, '_item_source', {})
        for item in self._dxf_items:
            if self._item_layer.get(id(item), 'dxf') == layer:
                item.setVisible(visible and source.get(id(item))
                                not in caches)
        self.viewport().update()

    def clear_layer(self, layer: str):
        """Supprime toutes les entités d'un calque."""
        keep = []
        for item in self._dxf_items:
            if self._item_layer.get(id(item), 'dxf') == layer:
                self._scene.removeItem(item)
                self._item_layer.pop(id(item), None)
                if item in self._selected_items:
                    self._selected_items.remove(item)
                # Retirer le centre détecté associé
                center = self._item_metadata.pop(id(item), None)
                if center is not None and center in self._detected_circles:
                    self._detected_circles.remove(center)
            else:
                keep.append(item)
        self._dxf_items = keep
        self.selection_changed.emit(len(self._selected_items))
        self.circles_detected.emit(self._detected_circles)

    def clear_dxf(self):
        """Supprime les entités dessin (tous calques dxf/drawn/smb).
        Les overlays d'opération (marqueurs op, preview prog ext) sont
        indépendants: 'Effacer' ne doit pas tout supprimer — ils
        suivent l'opération active."""
        self._selected_items.clear()
        self._original_pens.clear()
        self._item_metadata.clear()
        self._item_layer.clear()
        self._item_source = {}
        self._imports_dxf = []
        # la pièce STEP du dessin (vue 3D) part avec lui
        self._source_3d = None
        # Vider l'undo: sinon Ctrl+Z restaurerait des entités de
        # l'ancien fichier dans la nouvelle scène
        self._pile_undo.clear()
        for item in self._dxf_items:
            self._scene.removeItem(item)
        self._dxf_items.clear()
        for marker in self._center_markers:
            self._scene.removeItem(marker)
        self._center_markers.clear()
        self._detected_circles.clear()

    def draw_operation_points(self, points: list,
                               highlight_index: int = -1,
                               label_prefix: str = "",
                               source: str = "",
                               keep_existing: bool = False):
        """Dessine des marqueurs d'opération sur le canvas.
        points: list de dicts {x, y, [depth], [label], [color]}
        highlight_index: index du point en surbrillance
        label_prefix: préfixe pour les étiquettes
        source: origine des points ('op', 'genops', 'external') —
            réémise par op_point_clicked au clic sur un marqueur
        """
        if keep_existing:
            # Empilement (export « toutes les opérations »): on garde
            # les marqueurs déjà tracés et on complète la table de
            # positions pour que les clics restent cohérents
            base = len(self._op_point_positions)
            self._op_point_positions += [
                (pt.get('x', 0), -pt.get('y', 0), base + i)
                for i, pt in enumerate(points)]
        else:
            self.clear_operation_points()
            self._op_points_source = source
            self._op_point_positions = [
                (pt.get('x', 0), -pt.get('y', 0), i)
                for i, pt in enumerate(points)]
        # Couleurs contrastées : cyan normal, vert vif sélectionné
        pen_normal = QPen(QColor("#00e5ff"), 0.3)      # cyan vif
        pen_highlight = QPen(QColor("#00ff88"), 0.6)    # vert vif
        brush_hl = QBrush(QColor(0, 255, 136, 60))     # remplissage translucide

        for i, pt in enumerate(points):
            x = pt.get('x', 0)
            y_scene = -pt.get('y', 0)  # DXF→scene: y inversé
            is_hl = (i == highlight_index)
            # Couleur par point optionnelle (ex: profondeur prog externe)
            pt_color = pt.get('color')
            if is_hl:
                pen = pen_highlight
            elif pt_color:
                pen = QPen(QColor(pt_color), 0.3)
            else:
                pen = pen_normal

            # Croix
            r = 0.5
            line1 = self._scene.addLine(x - r, y_scene - r,
                                         x + r, y_scene + r, pen)
            line2 = self._scene.addLine(x - r, y_scene + r,
                                         x + r, y_scene - r, pen)
            self._op_point_items.extend([line1, line2])

            # Cercle (rempli si sélectionné)
            if is_hl:
                circle = self._scene.addEllipse(
                    x - r, y_scene - r, r * 2, r * 2, pen, brush_hl)
            else:
                circle = self._scene.addEllipse(
                    x - r, y_scene - r, r * 2, r * 2, pen)
            self._op_point_items.append(circle)

            # Étiquette — sautée si les annotations de l'opé sont
            # masquées (bouton par opération)
            if self._masquer_annot_courante:
                continue
            label_text = pt.get('label', '')
            if not label_text:
                depth = pt.get('depth', '')
                label_text = f"{label_prefix}{i+1}"
                if depth:
                    label_text += f" Pz{depth}"
            text_item = self._scene.addText(label_text)
            text_item.setPos(x + r + 0.2, y_scene - r)
            if is_hl:
                text_item.setDefaultTextColor(QColor("#00ff88"))
            elif pt_color:
                text_item.setDefaultTextColor(QColor(pt_color))
            else:
                text_item.setDefaultTextColor(QColor("#00e5ff"))
            # Taille d'écran CONSTANTE: l'échelle calculée au tracé
            # figeait le libellé au zoom du moment, si bien qu'il
            # grossissait ou disparaissait ensuite.
            text_item.setFlag(
                QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
            font = text_item.font()
            font.setPointSizeF(8.0)
            text_item.setFont(font)
            text_item.setVisible(self._op_labels_visible
                                 and not self._masquer_annot_courante)
            self._op_point_items.append(text_item)
            self._op_label_items.append(text_item)

    # ──── Rectangles du dessin ────

    #: tolérance d'équerrage/fermeture d'un rectangle, en mm
    _RECT_TOL = 0.02

    def selected_polyline(self) -> List[Tuple[float, float]]:
        """Sommets de la polyligne sélectionnée, en coordonnées
        machine. Sert à reprendre un contour du dessin comme parcours
        d'usinage. Liste vide si la sélection n'est pas une
        polyligne unique."""
        items = [it for it in self._selected_items
                 if isinstance(it, (QGraphicsPathItem,
                                    QGraphicsLineItem,
                                    QGraphicsRectItem))]
        if len(items) != 1:
            return []
        item = items[0]
        try:
            if isinstance(item, QGraphicsRectItem):
                r = item.mapRectToScene(item.rect())
                pts = [(r.left(), r.top()), (r.right(), r.top()),
                       (r.right(), r.bottom()), (r.left(), r.bottom()),
                       (r.left(), r.top())]
            elif isinstance(item, QGraphicsLineItem):
                ln = item.line()
                pos = item.scenePos()
                pts = [(ln.x1() + pos.x(), ln.y1() + pos.y()),
                       (ln.x2() + pos.x(), ln.y2() + pos.y())]
            else:
                pts = self._path_points(item)
        except RuntimeError:
            return []
        # Scène → machine: Y inversé
        return [(x, -y) for x, y in pts]

    #: écart maximal entre une courbe et sa polyligne, en mm.
    #: `QPainterPath.toSubpathPolygons()` aplatit avec un seuil
    #: FIXE dans l'unité du chemin — 0,15 mm de flèche sur un cercle
    #: de rayon 2 (mesuré: 9 points). En millimètres, c'est un
    #: polygone: un trait de 0,2 mm de large était gravé de travers
    #: et le tracé exporté en DXF ressortait à facettes.
    APLAT_MM = 0.002

    @classmethod
    def polygones_fins(cls, chemin: QPainterPath,
                       tolerance: float = None) -> list:
        """Sous-chemins aplatis à `tolerance` mm près.

        Le seuil de Qt ne se règle pas, mais il s'applique dans le
        repère qu'on lui donne: on aplatit le chemin agrandi, puis on
        ramène les points. Le nombre de points d'une courbe croît
        comme la racine de l'agrandissement — le micron ne coûte
        que dix fois plus de sommets que le dixième."""
        from PySide6.QtGui import QTransform
        tolerance = float(tolerance or cls.APLAT_MM)
        # mesuré: flèche de 0,15 mm à l'échelle 1, 0,0023 à 100
        facteur = max(1.0, 0.2 / max(1e-4, tolerance))
        agrandi = QTransform.fromScale(facteur, facteur)
        sortie = []
        for polygone in chemin.toSubpathPolygons(agrandi):
            sortie.append([(p.x() / facteur, p.y() / facteur)
                           for p in polygone])
        return sortie

    def selected_polylines(self) -> List[List[Tuple[float, float]]]:
        """Sommets de TOUTES les entités sélectionnées.

        Une lettre gravée, c'est plusieurs contours: le « O » a son
        intérieur, le « A » son creux. `selected_polyline` n'en rend
        qu'un — elle sert au tracé, qui suit un seul chemin."""
        sortie = []
        for item in self.selection_courante():
            if not isinstance(item, (QGraphicsPathItem,
                                     QGraphicsLineItem,
                                     QGraphicsRectItem,
                                     QGraphicsEllipseItem)):
                continue
            try:
                if isinstance(item, QGraphicsRectItem):
                    r = item.mapRectToScene(item.rect())
                    pts = [(r.left(), r.top()), (r.right(), r.top()),
                           (r.right(), r.bottom()),
                           (r.left(), r.bottom()),
                           (r.left(), r.top())]
                elif isinstance(item, QGraphicsEllipseItem):
                    chemin = QPainterPath()
                    chemin.addEllipse(item.rect())
                    pts = self.polygones_fins(
                        item.mapToScene(chemin))[0]
                elif isinstance(item, QGraphicsLineItem):
                    ln = item.line()
                    pos = item.scenePos()
                    pts = [(ln.x1() + pos.x(), ln.y1() + pos.y()),
                           (ln.x2() + pos.x(), ln.y2() + pos.y())]
                else:
                    # Un tracé COMPOSÉ (une lettre, un DXF à trous)
                    # porte plusieurs sous-chemins: chacun est un
                    # contour à part entière, sinon le trou du « O »
                    # se grave comme du plein
                    for polygone in self.polygones_fins(
                            item.mapToScene(item.path())):
                        contour = [(x, -y) for x, y in polygone]
                        if len(contour) >= 2:
                            sortie.append(contour)
                    continue
            except (RuntimeError, IndexError):
                continue
            if len(pts) >= 2:
                sortie.append([(x, -y) for x, y in pts])
        return sortie

    def detected_rectangles(self, seulement_selection: bool = False
                            ) -> List[Dict]:
        """Rectangles du dessin, prêts à remplir un formulaire.

        Les centres de cercles alimentent déjà les perçages; les
        rectangles manquaient, alors que surfaçage, poche et découpe
        se règlent exactement avec: centre, longueur X, longueur Y.
        Coordonnées MACHINE (Y remis à l'endroit)."""
        out: List[Dict] = []
        seen = set()
        # « Générer » depuis la sélection: ses rectangles seulement
        items_vus = (self.selection_courante() if seulement_selection
                     else self._dxf_items)

        def _add(x0, y0, x1, y1, source, rayon=0.0, pz=None):
            w, h = abs(x1 - x0), abs(y1 - y0)
            if w < self._RECT_TOL or h < self._RECT_TOL:
                return
            cx = (x0 + x1) / 2.0
            cy = (y0 + y1) / 2.0
            key = (round(cx, 3), round(cy, 3),
                   round(w, 3), round(h, 3))
            if key in seen:
                return
            seen.add(key)
            rect = {'x': cx, 'y': cy, 'width': w, 'height': h,
                    'source': source, 'rayon': round(rayon, 3)}
            if pz is not None:
                rect['pz'] = pz       # cote d'un calque « STEP Pz N »
            out.append(rect)

        for item in list(items_vus):
            try:
                if not item.isVisible():
                    continue
                layer = self._item_layer.get(id(item), 'dxf')
                if isinstance(item, QGraphicsRectItem):
                    # rect() et non sceneBoundingRect(): ce dernier
                    # englobe l'épaisseur du trait et donnait 51×31
                    # pour un rectangle de 50×30
                    r = item.mapRectToScene(item.rect())
                    # Scène → machine: Y inversé
                    _add(r.left(), -r.bottom(), r.right(), -r.top(),
                         layer)
                    continue
                if isinstance(item, QGraphicsPathItem):
                    pts = self._path_points(item)
                    rect = self._as_rectangle(pts)
                    if rect is None:
                        # coins arrondis: le contour aplati le dit
                        arrondi = self.rectangle_arrondi(
                            self._points_du_contour_scene(item))
                        if arrondi is not None:
                            x0, y0, x1, y1, rayon = arrondi
                            m = re.match(r"STEP Pz\s+(-?[\d.]+)",
                                         str(item.data(0) or ""))
                            _add(x0, -y1, x1, -y0, layer, rayon,
                                 float(m.group(1)) if m else None)
                            continue
                    if rect is not None:
                        x0, y0, x1, y1 = rect
                        from PySide6.QtCore import QRectF as _QR
                        boite = _QR(min(x0, x1), min(y0, y1),
                                    abs(x1 - x0), abs(y1 - y0))
                        # un contour d'un calque « STEP Pz N » est à
                        # la cote N sous le dessus de la pièce
                        m = re.match(r"STEP Pz\s+(-?[\d.]+)",
                                     str(item.data(0) or ""))
                        _add(x0, -y1, x1, -y0, layer,
                             self._rayon_coin(item, boite),
                             float(m.group(1)) if m else None)
            except RuntimeError:
                continue
        out.sort(key=lambda r: (-r['width'] * r['height'],
                                r['x'], r['y']))
        return out

    def _rectangle_de_scene(self, item) -> Optional[QRectF]:
        """Le rectangle de la GÉOMÉTRIE d'une entité, en scène — sans
        l'épaisseur du trait, que `sceneBoundingRect` compte."""
        try:
            if isinstance(item, (QGraphicsRectItem, QGraphicsEllipseItem)):
                return item.mapRectToScene(item.rect())
            if isinstance(item, QGraphicsLineItem):
                ligne = item.line()
                p1 = item.mapToScene(ligne.p1())
                p2 = item.mapToScene(ligne.p2())
                return QRectF(p1, p2).normalized()
            if isinstance(item, QGraphicsPathItem):
                return item.mapToScene(item.path()).boundingRect()
            return item.sceneBoundingRect()
        except RuntimeError:
            return None

    def rectangles_de_la_selection(self) -> List[Dict]:
        """Les rectangles que la sélection dessine, en MACHINE:
        {'x', 'y' (centre), 'width', 'height'}.

        Un rectangle tracé d'un trait (entité fermée) ou un groupe
        fait un rectangle chacun; les traits épars (un rectangle en
        quatre lignes) en font un seul, celui qui les contient. C'est
        ce qui remplit un surfaçage, une poche ou une découpe — et en
        crée plusieurs quand on a pris plusieurs rectangles."""
        items = self.selection_courante()
        if not items:
            return []
        rects = []          # (QRectF, rayon coin)
        groupes: Dict[str, list] = {}
        epars: list = []
        for item in items:
            cle = self._groupe_de.get(id(item), "")
            if cle:
                groupes.setdefault(cle, []).append(item)
                continue
            rect = self._rectangle_de_scene(item)
            if rect is None:
                continue
            if (rect.width() >= self._RECT_TOL
                    and rect.height() >= self._RECT_TOL):
                rects.append((rect, self._rayon_coin(item, rect)))
            else:
                epars.append(rect)
        for membres in groupes.values():
            union = None
            rayon = 0.0
            for membre in membres:
                rect = self._rectangle_de_scene(membre)
                if rect is None:
                    continue
                rayon = max(rayon, self._rayon_coin(membre, rect))
                union = rect if union is None else union.united(rect)
            if union is not None:
                rects.append((union, rayon))
        if epars:
            union = epars[0]
            for rect in epars[1:]:
                union = union.united(rect)
            if (union.width() >= self._RECT_TOL
                    and union.height() >= self._RECT_TOL):
                rects.append((union, 0.0))
        sortie = []
        vus = set()
        for rect, rayon in rects:
            cle = (round(rect.center().x(), 3), round(-rect.center().y(), 3),
                   round(rect.width(), 3), round(rect.height(), 3))
            if cle in vus:
                continue
            vus.add(cle)
            sortie.append({'x': cle[0], 'y': cle[1],
                           'width': cle[2], 'height': cle[3],
                           'rayon': round(rayon, 3)})
        # de gauche à droite, puis de haut en bas: l'ordre d'usinage
        # qu'on lit sur le dessin
        sortie.sort(key=lambda r: (r['x'], -r['y']))
        return sortie

    #: écart max entre largeur et hauteur pour qu'on lise un CERCLE
    _CERCLE_TOL = 0.15

    def centres_de_la_selection(self) -> List[Dict]:
        """Les centres des entités sélectionnées, en MACHINE:
        [{'x', 'y', 'diameter'}]. `diameter` = 0 si l'entité n'est pas
        un cercle (on ne retient alors que le point).

        C'est ce qui remplit les points d'un perçage ou d'un
        taraudage: un cercle sélectionné donne son centre ET son Ø;
        une croix, un texte, un contour quelconque ne donnent que leur
        centre. Groupes étendus, doublons écartés, rangés de gauche à
        droite puis de haut en bas — l'ordre qu'on lit sur le dessin."""
        items = self.selection_courante()
        sortie = []
        vus = set()
        for item in items:
            rect = self._rectangle_de_scene(item)
            if rect is None:
                continue
            cx = round(rect.center().x(), 3)
            cy = round(-rect.center().y(), 3)
            cle = (cx, cy)
            if cle in vus:
                continue
            vus.add(cle)
            w, h = rect.width(), rect.height()
            diametre = 0.0
            moyen = (w + h) / 2.0
            if moyen > 1e-6 and abs(w - h) <= self._CERCLE_TOL * moyen:
                if self._est_cercle(item):
                    diametre = round(moyen, 3)
            sortie.append({'x': cx, 'y': cy, 'diameter': diametre})
        sortie.sort(key=lambda p: (p['x'], -p['y']))
        return sortie

    def _est_cercle(self, item) -> bool:
        """L'entité est-elle un cercle (ellipse Qt, ou contour rond) ?

        Une ellipse Qt l'est d'emblée. Un contour importé (chemin) est
        rond si ses points se tiennent à égale distance du centre."""
        import math
        if isinstance(item, QGraphicsEllipseItem):
            return True
        if not isinstance(item, QGraphicsPathItem):
            return False
        pts = self._points_du_contour_scene(item)
        if len(pts) < 8:
            return False
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        rayons = [math.hypot(px - cx, py - cy) for px, py in pts]
        moyen = sum(rayons) / len(rayons)
        if moyen < 1e-6:
            return False
        return (max(rayons) - min(rayons)) <= 0.12 * moyen

    def _rayon_coin(self, item, rect) -> float:
        """Le rayon des coins d'un rectangle arrondi, en mm — 0 pour
        des coins vifs.

        Le contour d'un rectangle arrondi s'écarte du coin franc: au
        plus près (le point de l'arc à 45°), il en reste à distance
        r·(sqrt2 - 1) ~ 0,414·r. On mesure cet écart aux quatre coins
        de la boîte et on remonte au rayon. Un QGraphicsRectItem est
        franc par construction."""
        import math
        from PySide6.QtWidgets import QGraphicsRectItem
        if isinstance(item, QGraphicsRectItem) or rect is None:
            return 0.0
        pts = self._points_du_contour_scene(item)
        if len(pts) < 8:
            return 0.0
        coins = ((rect.left(), rect.top()), (rect.right(), rect.top()),
                 (rect.right(), rect.bottom()),
                 (rect.left(), rect.bottom()))
        ecarts = [min(math.hypot(px - cx, py - cy) for px, py in pts)
                  for cx, cy in coins]
        moyen = sum(ecarts) / len(ecarts)
        if moyen < 1e-3:
            return 0.0
        # cohérent aux quatre coins, sinon ce n'est pas un arrondi
        if max(ecarts) - min(ecarts) > 0.35 * moyen + 0.05:
            return 0.0
        rayon = moyen / (math.sqrt(2.0) - 1.0)
        rayon = min(rayon, rect.width() / 2.0, rect.height() / 2.0)
        return round(rayon, 3) if rayon > 0.05 else 0.0

    def _points_du_contour_scene(self, item) -> list:
        """Le contour d'un QGraphicsPathItem échantillonné (arcs
        aplatis), en coordonnées de scène."""
        try:
            chemin = item.path()
        except (RuntimeError, AttributeError):
            return []
        pts = []
        for poly in chemin.toSubpathPolygons():
            for pt in poly:
                sc = item.mapToScene(pt)
                pts.append((sc.x(), sc.y()))
        return pts

    @staticmethod
    def _path_points(item) -> list:
        """Sommets d'un tracé, en coordonnées de scène."""
        path = item.path()
        pos = item.scenePos()
        pts = []
        for i in range(path.elementCount()):
            el = path.elementAt(i)
            pts.append((el.x + pos.x(), el.y + pos.y()))
        return pts

    @classmethod
    def _as_rectangle(cls, pts: list):
        """(x0, y0, x1, y1) si les sommets forment un rectangle à
        angles droits, sinon None. Un contour fermé répète son
        premier point: 4 ou 5 sommets sont acceptés."""
        if len(pts) == 5 and (
                abs(pts[0][0] - pts[-1][0]) < cls._RECT_TOL
                and abs(pts[0][1] - pts[-1][1]) < cls._RECT_TOL):
            pts = pts[:4]
        if len(pts) != 4:
            return None
        xs = sorted({round(p[0], 3) for p in pts})
        ys = sorted({round(p[1], 3) for p in pts})
        # Rectangle droit: exactement deux abscisses et deux ordonnées,
        # chacune employée deux fois
        if len(xs) != 2 or len(ys) != 2:
            return None
        for x in xs:
            if sum(1 for p in pts
                   if abs(p[0] - x) < cls._RECT_TOL) != 2:
                return None
        for y in ys:
            if sum(1 for p in pts
                   if abs(p[1] - y) < cls._RECT_TOL) != 2:
                return None
        return xs[0], ys[0], xs[1], ys[1]

    @classmethod
    def rectangle_arrondi(cls, pts: list):
        """(x0, y0, x1, y1, rayon) si le contour (points d'un tracé
        fermé, arcs aplatis) est un rectangle à coins arrondis — ou à
        coins vifs —, sinon None.

        Chaque point doit tenir sur le rectangle arrondi idéal (même
        boîte, même rayon) à la tolérance près. Un cercle ou un oblong
        (rayon = demi-largeur) n'en est PAS un: ce sont des perçages et
        des rainures, pas des poches rectangulaires."""
        import math
        if len(pts) < 4:
            return None
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        w, h = x1 - x0, y1 - y0
        if w < cls._RECT_TOL or h < cls._RECT_TOL:
            return None
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        demi_x, demi_y = w / 2.0, h / 2.0
        # le rayon: l'écart au coin franc vaut r·(√2 - 1)
        ecarts = [min(math.hypot(px - kx, py - ky) for px, py in pts)
                  for kx, ky in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
        r = (sum(ecarts) / 4.0) / (math.sqrt(2.0) - 1.0)
        if r < 0.05:
            r = 0.0
        if r >= 0.98 * min(demi_x, demi_y):
            return None                    # cercle, oblong
        tol = max(cls._RECT_TOL, 0.005 * max(w, h))
        for px, py in pts:
            qx = abs(px - cx) - (demi_x - r)
            qy = abs(py - cy) - (demi_y - r)
            exterieur = math.hypot(max(qx, 0.0), max(qy, 0.0))
            d = exterieur + min(max(qx, qy), 0.0) - r
            if abs(d) > tol:
                return None
        return x0, y0, x1, y1, round(r, 3)

    # ──── Forme réelle des opérations ────

    #: types dessinés en rectangle, avec la clé de leurs cotes
    _RECT_OPS = ("surfacage_rectangle", "poche_rectangle",
                 "decoupe_rectangle")
    #: types dessinés en cercle, avec la clé de leur diamètre
    _CIRCLE_OPS = ("surfacage_cercle", "decoupe_cercle",
                   "percage_fraise", "helice", "poche_cercle")

    @staticmethod
    def _thread_diameter(name: str) -> float:
        """Diamètre nominal d'un filetage (M6 → 6 mm)."""
        m = re.match(r'\s*M\s*([\d.]+)', str(name or ''), re.I)
        try:
            return float(m.group(1)) if m else 0.0
        except ValueError:
            return 0.0

    def _tool_diameter(self, op) -> float:
        """Diamètre de l'outil, de tools.json ou de sa géométrie
        Datron (@ ToolDescription @). 0 = inconnu: on ne dessine alors
        aucun cercle plutôt qu'un diamètre inventé."""
        tool = (self._tool_library.get_tool(op.tool_id)
                if (self._tool_library and getattr(op, 'tool_id', ''))
                else None)
        if tool is None:
            return 0.0
        try:
            d = float(getattr(tool, 'diameter', 0) or 0)
            if d > 0:
                return d
            return float((getattr(tool, 'geometry', {}) or {}).get(
                'Diameter', 0) or 0)
        except (TypeError, ValueError):
            return 0.0

    def _op_shape(self, op, pt: dict) -> Optional[tuple]:
        """Forme usinée à un point: ('rect', w, h) ou ('circle', d).

        Le marqueur en croix ne dit pas ce que l'opération enlève: sur
        un plan, c'est l'empreinte qui compte."""
        kind = getattr(op, 'operation_type', '')
        p = getattr(op, 'params', {}) or {}

        def _f(key, default=0.0):
            try:
                return float(p.get(key, default) or 0.0)
            except (TypeError, ValueError):
                return 0.0

        if kind in self._RECT_OPS:
            wx, wy = _f('width_x'), _f('width_y')
            if kind == "surfacage_rectangle":
                wx += 2 * _f('extension_x')
                wy += 2 * _f('extension_y')
            if wx > 0 and wy > 0:
                # découpe et poche portent un rayon de coin: le plan
                # doit le montrer, c'est lui qui distingue un
                # rectangle d'une plaque à coins arrondis
                rayon = min(_f('corner_radius'), wx / 2.0, wy / 2.0)
                return ('rect', wx, wy, max(0.0, rayon))
            return None
        if kind in self._CIRCLE_OPS:
            d = _f('diameter')
            if kind == "percage_fraise" and p.get('diametres_par_point'):
                try:
                    d = float(pt.get('diameter') or 0.0) or d
                except (TypeError, ValueError):
                    pass
            return ('circle', d) if d > 0 else None
        if kind == "ebavurage":
            # le tour à l'offset: là où passe le centre de l'outil
            from src.operations.ebavurage import Ebavurage
            forme = Ebavurage.forme(p)
            if forme == "Rectangle":
                largeur, hauteur, rayon = Ebavurage.rectangle_offset(p)
                return ('rect', largeur, hauteur, rayon)
            if forme == "Cercle":
                return ('circle', Ebavurage.diametre_offset(p))
            return None
        if kind == "percage_foret":
            d = self._tool_diameter(op)
            return ('circle', d) if d > 0 else None
        if kind in ("taraudage", "taraudage_brut"):
            thread = (pt.get('thread_type')
                      or p.get('thread_type')
                      or p.get('thread_name') or '')
            d = self._thread_diameter(thread)
            return ('circle', d) if d > 0 else None
        if kind == "filetage_special":
            d = _f('nominal_diameter')
            return ('circle', d) if d > 0 else None
        if kind == "taraudage_rigide":
            d = self._tool_diameter(op)
            return ('circle', d) if d > 0 else None
        return None

    @staticmethod
    def _op_positions(op, pt: dict) -> list:
        """Toutes les positions usinées à partir d'un point.

        La répétition (nbX/pasX, nbY/pasY) et l'entraxe d'un taraudage
        brut produisent plusieurs usinages: n'en dessiner qu'un
        laissait croire à une pièce percée une seule fois."""
        p = getattr(op, 'params', {}) or {}

        def _i(key, default=1):
            try:
                return max(1, int(p.get(key, default) or default))
            except (TypeError, ValueError):
                return default

        def _f(key, default=0.0):
            try:
                return float(p.get(key, default) or default)
            except (TypeError, ValueError):
                return default

        base = [(pt.get('x', 0.0), pt.get('y', 0.0))]
        # Taraudage brut: deux trous séparés par l'entraxe
        if getattr(op, 'operation_type', '') == "taraudage_brut":
            entraxe = _f('entraxe')
            if entraxe > 0:
                half = entraxe / 2.0
                axis = str(p.get('entraxe_axis', 'X') or 'X').upper()
                x0, y0 = base[0]
                base = ([(x0 - half, y0), (x0 + half, y0)]
                        if axis == 'X'
                        else [(x0, y0 - half), (x0, y0 + half)])
        # Répétition en grille — et la grille de la grille
        from src.core import repetition
        decalages = repetition.positions(p)
        if len(decalages) > 1:
            return [(bx + dx, by + dy) for dx, dy in decalages
                    for bx, by in base]
        rx, ry = _i('repeat_x_count'), _i('repeat_y_count')
        sx, sy = _f('repeat_x_step'), _f('repeat_y_step')
        if rx > 1 or ry > 1:
            base = [(x + ix * sx, y + iy * sy)
                    for (x, y) in base
                    for iy in range(ry) for ix in range(rx)]
        # Pattern machine (expert): grille Pattern::RectanglePattern
        if p.get('use_pattern') and str(
                p.get('pattern_type', 'Rectangle')) == 'Rectangle':
            nx, ny = _i('x_count'), _i('y_count')
            dx, dy = _f('delta_x', 10.0), _f('delta_y', 10.0)
            if nx > 1 or ny > 1:
                base = [(x + ix * dx, y + iy * dy)
                        for (x, y) in base
                        for iy in range(ny) for ix in range(nx)]
        # Pattern par point (perçages, taraudages)
        if pt.get('use_pattern'):
            nx = max(1, int(pt.get('x_count', 1) or 1))
            ny = max(1, int(pt.get('y_count', 1) or 1))
            dx = float(pt.get('delta_x', 10.0) or 0.0)
            dy = float(pt.get('delta_y', 10.0) or 0.0)
            if nx > 1 or ny > 1:
                base = [(x + ix * dx, y + iy * dy)
                        for (x, y) in base
                        for iy in range(ny) for ix in range(nx)]
        return base

    def _draw_op_shapes(self, op, points: list, color: QColor,
                        offset=(0.0, 0.0)):
        """Trace l'empreinte de l'opération à CHAQUE position usinée."""
        for pt in points:
            shape = self._op_shape(op, pt)
            if not shape:
                continue
            for px, py in self._op_positions(op, pt):
                self._draw_one_shape(op, shape, px + offset[0],
                                     py + offset[1], color)

    def _draw_one_shape(self, op, shape, x: float, y: float,
                        color: QColor):
        y_s = -y
        pen = QPen(QColor(color), 0.12)
        pen.setStyle(Qt.PenStyle.SolidLine)
        if shape[0] == 'rect':
            _k, w, h = shape[:3]
            rayon = shape[3] if len(shape) > 3 else 0.0
            if rayon > 1e-6:
                chemin = QPainterPath()
                chemin.addRoundedRect(
                    QRectF(x - w / 2, y_s - h / 2, w, h), rayon, rayon)
                item = self._scene.addPath(chemin, pen)
            else:
                item = self._scene.addRect(
                    x - w / 2, y_s - h / 2, w, h, pen)
        else:
            _k, d = shape
            r = d / 2.0
            item = self._scene.addEllipse(
                x - r, y_s - r, d, d, pen)
        item.setVisible(self._show_all_ops)
        self._op_point_items.append(item)
        # Taraudage brut: le perçage préalable, en pointillé —
        # c'est lui qui est réellement fait avant le filetage
        if getattr(op, 'operation_type', '') == "taraudage_brut" \
                and shape[0] == 'circle':
            tool = (self._tool_library.get_tool(op.tool_id)
                    if (self._tool_library and op.tool_id) else None)
            dd = float(getattr(tool, 'diameter', 0) or 0)
            if dd > 0:
                dash = QPen(QColor(color), 0.1)
                dash.setStyle(Qt.PenStyle.DashLine)
                rr = dd / 2.0
                hole = self._scene.addEllipse(
                    x - rr, y_s - rr, dd, dd, dash)
                hole.setVisible(self._show_all_ops)
                self._op_point_items.append(hole)

    # ──── Couleur par outil et légende ────

    #: teintes distinctes, lisibles sur fond sombre comme sur blanc
    #: (elles passent par _ink() pour les sorties papier) — celles de la
    #: bibliothèque, pour un outil qu'elle ne connaît pas
    from src.core.tool_library import PALETTE_OUTILS as _TOOL_PALETTE

    def set_tool_library(self, library):
        """Bibliothèque d'outils: sert à nommer les outils en légende."""
        self._tool_library = library

    def reset_tool_colors(self):
        """Repart d'une palette vierge (nouveau programme)."""
        self._tool_colors.clear()
        self._tool_labels.clear()

    def tool_color(self, key: str, label: str = "") -> QColor:
        """La couleur d'un outil: celle que tools.json lui donne (choisie
        par l'utilisateur, sinon son rang dans la bibliothèque — la même
        d'un programme à l'autre); un outil inconnu de la bibliothèque
        prend la teinte suivante."""
        key = str(key or "?")
        if key not in self._tool_colors:
            lib = getattr(self, '_tool_library', None)
            couleur = lib.couleur_outil(key) if lib is not None and \
                hasattr(lib, 'couleur_outil') else None
            if not couleur:
                idx = len(self._tool_colors) % len(self._TOOL_PALETTE)
                couleur = self._TOOL_PALETTE[idx]
            self._tool_colors[key] = QColor(couleur)
            self._tool_labels[key] = label or key
        elif label and self._tool_labels.get(key) in (None, key):
            self._tool_labels[key] = label
        return self._tool_colors[key]

    def _op_tool_key(self, op) -> Tuple[str, str]:
        """(clé, libellé) de l'outil d'une opération.

        La clé est la RÉFÉRENCE quand on la connaît: deux opérations
        qui tournent avec le même outil doivent partager sa couleur,
        même si l'une vient d'un import et l'autre d'un formulaire."""
        params = getattr(op, 'params', {}) or {}
        lib = self._tool_library
        # Bloc importé: outil de remplacement, sinon celui du fichier
        article = str(params.get('tool_article', '') or '')
        if article:
            tool = (lib.get_tool_by_article(article) if lib else None)
            name = tool.name if tool else str(
                params.get('tool_label', '') or article)
            return article, f"{name} [{article}]"
        origin = str(params.get('_tool', '') or '')
        if origin:
            tool = None
            if lib:
                tool = (lib.get_tool_by_article(origin)
                        or next((t for t in lib.get_all_tools()
                                 if t.name == origin), None))
            if tool is not None:
                return tool.article_nr, f"{tool.name} [{tool.article_nr}]"
            return origin, origin
        # Opération NeoDrive: outil de la bibliothèque
        tool_id = getattr(op, 'tool_id', '') or ''
        if tool_id and lib:
            tool = lib.get_tool(tool_id)
            if tool is not None:
                key = tool.article_nr or tool.name
                return key, f"{tool.name} [{tool.article_nr}]"
        return "", "(sans outil)"

    def set_legende_hors_matiere(self, voulue: bool) -> None:
        """Réglage: la légende cite-t-elle aussi les palpages,
        dialogues et réglages ? Non par défaut."""
        self._legende_hors_matiere = bool(voulue)

    def _legende_voulue(self, op) -> bool:
        """Une opération HORS MATIÈRE (palpage, dialogue, décalage
        d'origine…) n'a pas sa ligne de légende: la légende dit
        « quel outil coupe où », et ces opérations ne coupent rien.
        Leur tracé, lui, reste dessiné. Le réglage les rétablit."""
        if self._legende_hors_matiere:
            return True
        try:
            from src.operations.registry import OperationRegistry
            classe = OperationRegistry.get(
                getattr(op, 'operation_type', ''))
        except KeyError:
            return True
        return not getattr(classe, 'HORS_MATIERE', False)

    def rebuild_tool_legend(self):
        """Légende des couleurs d'outils, ancrée sur le dessin.

        Placée dans la scène (et non en surimpression de la vue) pour
        qu'elle parte aussi dans le PNG et le PDF."""
        self.clear_tool_legend()
        used = list(self._legend_rows)
        if not used:
            return
        anchor = self._content_bounds()
        if anchor.isNull():
            anchor = QRectF(0, 0, 10, 10)
        x = anchor.left()
        y = anchor.top()
        for i, (key, op_name, tool_label) in enumerate(used):
            item = self._scene.addText(f"■ {op_name} — {tool_label}")
            item.setDefaultTextColor(
                self._tool_colors.get(key, QColor("#cdd6f4")))
            item.setFlag(
                QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
            font = item.font()
            font.setPointSizeF(8.0)
            item.setFont(font)
            # Empilement en unités de scène: la vue les garde lisibles,
            # l'export les retrouve au même endroit
            step = max(anchor.height() * 0.035, 1.0)
            item.setPos(x, y - step * (len(used) - i))
            item.setZValue(900)
            item.setVisible(self._legend_visible)
            self._legend_items.append(item)

    def set_legend_visible(self, visible: bool):
        """Affiche/masque la légende des couleurs d'outils.

        Le réglage tient à travers les reconstructions (chaque dessin
        d'opération refait la légende)."""
        self._legend_visible = bool(visible)
        for item in self._legend_items:
            try:
                item.setVisible(self._legend_visible)
            except RuntimeError:
                pass
        self.update()

    def clear_tool_legend(self):
        for item in self._legend_items:
            try:
                self._scene.removeItem(item)
            except RuntimeError:
                pass
        self._legend_items.clear()

    # ──── Brut (@ WorkpieceGeometry @) ────

    def set_workpiece(self, settings):
        """Trace le contour du brut déclaré par le programme.

        C'est le repère de la pièce: sans lui, on lit des coordonnées
        sans savoir où tombe la matière. Il commande aussi le cadrage
        (`fit_all`), pour revenir à la pièce d'un clic."""
        self.clear_workpiece()
        if settings is None:
            return
        try:
            x0 = float(getattr(settings, 'workpiece_min_x', 0.0))
            y0 = float(getattr(settings, 'workpiece_min_y', 0.0))
            z0 = float(getattr(settings, 'workpiece_min_z', 0.0))
            x1 = float(getattr(settings, 'workpiece_max_x', 0.0))
            y1 = float(getattr(settings, 'workpiece_max_y', 0.0))
            z1 = float(getattr(settings, 'workpiece_max_z', 0.0))
        except (TypeError, ValueError):
            return
        if x1 - x0 <= 0 or y1 - y0 <= 0:
            return          # brut non déclaré: rien à tracer

        # Scène: Y inversé (machine Y+ vers le haut)
        rect = QRectF(x0, -y1, x1 - x0, y1 - y0)
        pen = QPen(QColor("#7f849c"), 0.25)
        pen.setStyle(Qt.PenStyle.DashLine)
        item = self._scene.addRect(rect, pen)
        item.setZValue(-500)        # derrière le dessin et les opés
        self._workpiece_items.append(item)

        label = self._scene.addText(
            f"Brut {x1 - x0:g} × {y1 - y0:g} × {z1 - z0:g}")
        label.setDefaultTextColor(QColor("#7f849c"))
        label.setPos(rect.left(), rect.top())
        label.setFlag(
            QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        font = label.font()
        font.setPointSizeF(8.0)
        label.setFont(font)
        label.setZValue(-499)
        self._workpiece_items.append(label)

        self._workpiece_rect = rect

    def clear_workpiece(self):
        for item in self._workpiece_items:
            try:
                self._scene.removeItem(item)
            except RuntimeError:
                pass
        self._workpiece_items.clear()
        self._workpiece_rect = None

    def clear_operation_points(self):
        """Efface tous les marqueurs d'opération."""
        # ce que montrait le canvas des opérations n'y est plus
        self._ops_dessinees = None
        for item in self._op_point_items:
            self._scene.removeItem(item)
        self._op_point_items.clear()
        self._op_label_items.clear()
        self._op_point_positions = []
        self._op_points_source = ""
        self._legend_rows = []
        self.clear_tool_legend()

    def highlight_point(self, x: float, y: float,
                        duration_ms: int = 2500):
        """Anneaux temporaires pour repérer un point (clic sur le n°
        d'une rangée du tableau de points). Coordonnées machine (mm),
        Y inversé pour la scène. S'efface après duration_ms."""
        from PySide6.QtCore import QTimer
        self._clear_highlight()
        ys = -y
        pen = QPen(QColor("#f9e2af"), 0.4)
        for r in (1.2, 2.4):
            ring = self._scene.addEllipse(
                x - r, ys - r, 2 * r, 2 * r, pen)
            ring.setZValue(1000)
            self._highlight_items.append(ring)
        self.ensureVisible(x - 3, ys - 3, 6, 6, 60, 60)
        QTimer.singleShot(duration_ms, self._clear_highlight)

    def _clear_highlight(self):
        for it in getattr(self, '_highlight_items', []):
            try:
                self._scene.removeItem(it)
            except RuntimeError:
                pass
        self._highlight_items = []

    def draw_all_operations(self, program, only_ids=None) -> int:
        """Dessine TOUTES les opérations actives (points, patterns,
        séquences et positions des programmes SimPl externes appelés).

        Utilisé pour les sorties papier/image: un plan d'atelier doit
        montrer l'ensemble du programme, pas seulement l'opération
        en cours d'édition. Retourne le nombre d'opérations dessinées.
        """
        self.clear_operation_points()
        drawn = 0
        # Décalage d'origine cumulé: tout ce qui SUIT un ShiftWcsInc
        # est usiné dans le repère décalé. Le brut, lui, ne bouge pas —
        # c'est la pièce, pas le repère.
        shift = [0.0, 0.0]
        #: rotation cumulée du repère (RotateWcsInc), en degrés
        rot = [0.0]
        #: le repère local (ShiftLcs, RotateLcs) par-dessus
        lcs = {}
        from src.gui.panels.operations_panel import op_preview
        for op in getattr(program, 'operations', []) or []:
            if not getattr(op, 'enabled', True):
                continue
            # Le décalage d'origine compte TOUJOURS, même masqué:
            # sinon la suite serait mal placée
            if getattr(op, 'operation_type', '') == "decalage_origine":
                p = getattr(op, 'params', {}) or {}
                try:
                    dx = float(p.get('shift_x', 0.0) or 0.0)
                    dy = float(p.get('shift_y', 0.0) or 0.0)
                except (TypeError, ValueError):
                    dx = dy = 0.0
                # ShiftWcsInc se compte dans le repère COURANT: tourné,
                # le décalage tourne avec lui
                a = math.radians(rot[0])
                shift[0] += dx * math.cos(a) - dy * math.sin(a)
                shift[1] += dx * math.sin(a) + dy * math.cos(a)
                lcs['base'] = None
                # le nouveau repère se voit
                if op_preview(op):
                    self.dessiner_repere(shift[0], shift[1], rot[0])
                continue
            if getattr(op, 'operation_type', '') == "repere_local":
                from src.operations.repere_local import RepereLocal
                shift[0], shift[1], rot[0] = RepereLocal.appliquer(
                    getattr(op, 'params', {}) or {}, shift, rot[0], lcs)
                if op_preview(op):
                    self.dessiner_repere(shift[0], shift[1], rot[0])
                continue
            if getattr(op, 'operation_type', '') == "rotation_repere":
                from src.operations.rotation_repere import RotationRepere
                p = getattr(op, 'params', {}) or {}
                if RotationRepere.absolue(p):
                    rot[0] = RotationRepere.angle(p)
                else:
                    rot[0] += RotationRepere.angle(p)
                lcs['base'] = None
                if op_preview(op):
                    self.dessiner_repere(shift[0], shift[1], rot[0])
                continue
            if only_ids is not None and getattr(op, 'id', None) \
                    not in only_ids:
                continue
            # L'œil de la liste commande l'affichage ET les exports
            if not op_preview(op):
                continue
            try:
                avant = len(self._op_point_items)
                if rot[0]:
                    # repère tourné: l'opération est dessinée dans SON
                    # repère, puis tournée et décalée comme la machine
                    # le fera
                    self.set_active_operation(op, keep_existing=True)
                    self._placer_dans_le_repere(
                        self._op_point_items[avant:], rot[0], shift)
                else:
                    self.set_active_operation(op, keep_existing=True,
                                              offset=tuple(shift))
                drawn += 1
            except Exception:
                continue
        self.rebuild_tool_legend()
        return drawn

    @staticmethod
    def _placer_dans_le_repere(items, angle: float, decalage) -> None:
        """Tourne (autour de l'origine machine) puis décale des entités
        dessinées dans le repère d'une opération: la rotation du repère
        (RotateWcsInc gamma) est trigonométrique en coordonnées
        machine, donc horaire dans la scène (Y vers le bas)."""
        from PySide6.QtGui import QTransform
        from PySide6.QtWidgets import (QGraphicsTextItem,
                                       QGraphicsSimpleTextItem)
        t = QTransform()
        t.translate(float(decalage[0]), -float(decalage[1]))
        t.rotate(-float(angle))
        for item in items:
            try:
                if isinstance(item, (QGraphicsTextItem,
                                     QGraphicsSimpleTextItem)):
                    # une étiquette suit l'opération sans tourner: elle
                    # reste lisible
                    item.setPos(t.map(item.pos()))
                    continue
                p = item.pos()
                avant = QTransform.fromTranslate(p.x(), p.y())
                apres = QTransform.fromTranslate(-p.x(), -p.y())
                item.setTransform(item.transform() * avant * t * apres)
            except RuntimeError:
                continue

    def set_active_operation(self, op=None, keep_existing: bool = False,
                             offset=(0.0, 0.0)):
        """Dessine l'opération (voir `_dessiner_operation`), puis lui
        applique son affichage: transparence et une ligne sur N."""
        avant = len(self._op_point_items) if keep_existing else 0
        self._dessiner_operation(op, keep_existing, offset)
        if op is not None:
            self._appliquer_affichage(op, avant)

    def _appliquer_affichage(self, op, avant: int) -> None:
        """La transparence et la division (src.core.affichage) sur les
        entités que l'opération vient de poser."""
        from src.core import affichage as af
        n = af.division(op)
        a = af.opacite(op)
        if n <= 1 and a >= 1.0:
            return
        items = self._op_point_items[avant:]
        if n > 1:
            retires = set()
            for genre in (QGraphicsLineItem, QGraphicsEllipseItem):
                liste = [it for it in items if isinstance(it, genre)]
                if len(liste) > 2 * n:
                    garde = {id(it) for it in af.decimer(liste, n)}
                    for it in liste:
                        if id(it) not in garde:
                            retires.add(id(it))
                            try:
                                self._scene.removeItem(it)
                            except RuntimeError:
                                pass
            for it in items:
                if isinstance(it, QGraphicsPathItem) and id(it) not in retires:
                    try:
                        it.setPath(self._decimer_chemin(it.path(), n))
                    except RuntimeError:
                        pass
            if retires:
                self._op_point_items[avant:] = [
                    it for it in items if id(it) not in retires]
                items = self._op_point_items[avant:]
        if a < 1.0:
            for it in items:
                try:
                    it.setOpacity(a)
                except RuntimeError:
                    pass

    @staticmethod
    def _decimer_chemin(chemin: QPainterPath, n: int) -> QPainterPath:
        """Un chemin allégé: beaucoup de sous-chemins (des passes, des
        segments) → un sur n; peu → un sommet sur n."""
        from src.core import affichage as af
        sous = [list(p) for p in chemin.toSubpathPolygons()]
        sous = af.decimer_polylignes(sous, n)
        sortie = QPainterPath()
        for pts in sous:
            if len(pts) < 2:
                continue
            sortie.moveTo(pts[0])
            for q in pts[1:]:
                sortie.lineTo(q)
        return sortie

    def _dessiner_operation(self, op=None, keep_existing: bool = False,
                            offset=(0.0, 0.0)):
        """Dessine les marqueurs pour l'opération active.
        op: OperationInstance ou None pour effacer.
        keep_existing: ne pas effacer les marqueurs déjà présents
        (utilisé pour empiler toutes les opérations avant un export).
        Inclut la prévisualisation Pattern si use_pattern est actif.
        """
        if not keep_existing:
            self.clear_operation_points()
        if op is None:
            return
        if not getattr(op, 'enabled', True):
            return

        # Annotations de CETTE opé masquées ? (bouton par opération)
        self._masquer_annot_courante = (
            getattr(op, 'id', None) in self._annot_masquees)

        # Lignes du Main (import): ce qu'elles usinent elles-mêmes — pas
        # de marqueur à l'origine pour une pause ou un ShiftWcsInc
        if getattr(op, 'operation_type', '') == 'lignes_main':
            self._draw_lignes_main(op, offset)
            if not keep_existing:
                self.rebuild_tool_legend()
            return

        # Couleur de l'outil: elle identifie l'opération sur le plan
        key, label = self._op_tool_key(op)
        color = self.tool_color(key, label)
        # Une ligne de légende par ENSEMBLE (à défaut par opération):
        # un import de vingt sous-programmes tenait vingt lignes
        if getattr(op, 'group_id', ''):
            legend_name = str(getattr(op, 'group_name', '')
                              or 'Ensemble')
        else:
            legend_name = str(getattr(op, 'name', '') or '?')
        entry = (str(key or "?"), legend_name, label)
        # un appel de programme externe écrit SA ligne, avec l'outil que
        # le fichier prend — s'il est illisible (lecteur T: absent du
        # poste), pas de « (sans outil) »
        externe_sans_outil = (
            not key and getattr(op, 'operation_type', '') == 'appel_programme')
        if (entry not in self._legend_rows and self._legende_voulue(op)
                and not self._masquer_annot_courante
                and not externe_sans_outil):
            self._legend_rows.append(entry)

        # Appel prog ext: TOUT le parcours du fichier appelé (l'œil de
        # la liste en décide en amont; « une ligne sur N » l'allège)
        if getattr(op, 'operation_type', '') == 'appel_programme':
            self._draw_external_program(op, offset)
            return

        # Tracé: le parcours du centre de la fraise, tel qu'il sera
        # calculé à la génération
        if getattr(op, 'operation_type', '') == 'trace':
            self._draw_trace_op(op, color, offset)
            if not keep_existing:
                self.rebuild_tool_legend()
            return

        # Séquence Datron embarquée: parcours vectoriels
        if getattr(op, 'operation_type', '') == 'sequence_datron':
            self._draw_sequence_op(op)
            return

        # Gravure 2,5D et évidement: le parcours est CALCULÉ, on le
        # montre avant de générer — la profondeur se lit à la couleur
        if getattr(op, 'operation_type', '') in ('gravure_2d5',
                                                 'evidement_2d5',
                                                 'contour_2d5',
                                                 'texte_grave'):
            self._draw_passes_coniques(op)
            if not keep_existing:
                self.rebuild_tool_legend()
            return

        # Un ébavurage de contours: les tours à l'offset
        if getattr(op, 'operation_type', '') == 'ebavurage':
            from src.operations.ebavurage import Ebavurage
            params = getattr(op, 'params', {}) or {}
            if Ebavurage.forme(params) == "Contours":
                self._draw_anneaux(op, Ebavurage.anneaux(params), color)
                if not keep_existing:
                    self.rebuild_tool_legend()
                return

        # La tête d'une gamme: son dessin, en pointillé — ce sont
        # ses postes qui dessinent leurs parcours
        if getattr(op, 'operation_type', '') == 'gamme_gravure':
            try:
                from src.operations.gamme_gravure import GammeGravure
                self._draw_contours_en_attente(
                    op, GammeGravure, getattr(op, 'params', {}) or {})
            except Exception:
                pass
            return

        # Bloc importé d'un SimPl: parcours de son sous-programme et
        # de la séquence qu'il appelle
        if getattr(op, 'operation_type', '') == 'bloc_simpl':
            self._draw_bloc_simpl(op, keep_existing=keep_existing,
                                  color=color)
            if not keep_existing:
                self.rebuild_tool_legend()
            return

        points = []
        if hasattr(op, 'points') and op.points:
            for pt in op.points:
                points.append({
                    'x': pt.get('x', 0),
                    'y': pt.get('y', 0),
                    'depth': pt.get('depth', ''),
                    'color': color.name(),
                })
        else:
            points.append({'x': op.x, 'y': op.y,
                           'color': color.name()})

        # L'empreinte usinée, sous les marqueurs
        self._draw_op_shapes(op, points, color, offset=offset)
        if getattr(op, 'operation_type', '') == 'gravure_texte':
            self._draw_engrave_text(op, points, color, offset)
        if offset != (0.0, 0.0):
            # Décalage d'origine actif: les marqueurs suivent l'usinage
            points = [dict(pt, x=pt.get('x', 0.0) + offset[0],
                           y=pt.get('y', 0.0) + offset[1])
                      for pt in points]

        self.draw_operation_points(
            points, label_prefix=getattr(op, 'name', 'Op') + " ",
            source="op", keep_existing=keep_existing)

        # Pattern preview overlay (pattern global de l'opération)
        params = getattr(op, 'params', {})
        if params.get('use_pattern', False) and points:
            self._draw_pattern_preview(points, params)

        # Patterns PER-POINT (taraudage/perçages): expanser chaque grille
        # — sinon seul le point de base apparaît et les valeurs nbX/nbY/
        # pas semblent ignorées
        if hasattr(op, 'points') and op.points:
            pattern_pts = [pt for pt in op.points
                           if pt.get('use_pattern', False)]
            if pattern_pts:
                self._draw_per_point_patterns(pattern_pts)

        # Répétition preview overlay (deux niveaux)
        from src.core import repetition
        if repetition.compte(params) > 1 and points:
            self._draw_repeat_preview(points, params)

    def _draw_external_program(self, op, offset=(0.0, 0.0)):
        """Le programme SimPl externe appelé (Appel Prog Ext): TOUT son
        parcours simulé (Main, cycles, séquences — src.core.sim_cycles,
        gardé tant que le fichier ne change pas), la coupe à la couleur
        de son outil, l'air en pointillé; ses positions en points."""
        params = getattr(op, 'params', {}) or {}
        filepath = (params.get('filepath') or '').strip()
        if not filepath:
            return
        from src.core import sim_cycles
        if sim_cycles.parcours_en_cours(filepath):
            return          # il se simule dans la barre d'état: après
        self._dessiner_parcours_fichier(op, filepath, offset)
        # les séquences ne servent qu'en secours (la simulation n'a rien
        # tracé): les découper prend des secondes sur un gros programme
        trace = getattr(self, '_parcours_externe_trace', False)
        try:
            from src.io.simpl_analyzer import analyze_simpl_file
            info = analyze_simpl_file(filepath, sequences=not trace)
        except Exception:
            return
        if not info:
            return
        a_des_sequences = (info.get('sequences')
                           if info.get('_sequences_lues')
                           else info.get('a_des_sequences'))
        if not info.get('points') and not a_des_sequences:
            return
        # Rendu ÉPURÉ: petits points pleins, sans cibles ni numéros
        # (pollution visuelle). Le Pz reste accessible via le tooltip
        # du clic (op_point_clicked).
        self._op_points_source = "external"
        self._op_point_positions = []

        # Couleur de l'outil du fichier appelé: un programme externe
        # est identifié par son outil comme les autres opérations
        ext_color = None
        tools = info.get('tools') or []
        if tools:
            article, name = tools[0]
            ext_label = f"{name or article} [{article}]"
            ext_color = self.tool_color(article, ext_label)
            entry = (str(article or "?"),
                     str(getattr(op, 'name', '') or '?'), ext_label)
            if entry not in self._legend_rows:
                self._legend_rows.append(entry)

        # Séquences Datron: parcours outil vectoriels (si la
        # simulation n'a rien rendu: un fichier de séquences seules)
        sequences = info.get('sequences') or {}
        if sequences and not getattr(self, '_parcours_externe_trace', False):
            self._draw_sequence_paths(sequences, color=ext_color)

        # Parcours HORS matière (déplacements rapides entre positions):
        # polyligne pointillée bleu-gris dans l'ordre d'exécution.
        # Les points colorés = plongées DANS la matière.
        pts_seq = info['points']
        if len(pts_seq) >= 2 and not getattr(
                self, '_parcours_externe_trace', False):
            rapid_pen = QPen(QColor(116, 199, 236, 110), 0.12)
            rapid_pen.setStyle(Qt.PenStyle.DashLine)
            for a, b in zip(pts_seq, pts_seq[1:]):
                seg = self._scene.addLine(
                    a['x'], -a['y'], b['x'], -b['y'], rapid_pen)
                seg.setVisible(self._show_all_ops)
                self._op_point_items.append(seg)

        r = 0.45
        for i, p in enumerate(info['points']):
            d = p.get('depth')
            color = QColor(ext_color) if ext_color is not None \
                else QColor("#00e5ff")
            pen = QPen(color, 0.1)
            brush = QBrush(QColor(color.red(), color.green(),
                                  color.blue(), 170))
            x, y_s = p['x'] + offset[0], -(p['y'] + offset[1])
            dot = self._scene.addEllipse(
                x - r, y_s - r, 2 * r, 2 * r, pen, brush)
            if d is not None:
                dot.setToolTip(f"{i + 1}: Pz {d:g} mm")
            dot.setVisible(self._show_all_ops)
            self._op_point_items.append(dot)
            self._op_point_positions.append((x, y_s, i))

    def _dessiner_parcours_fichier(self, op, chemin: str, offset) -> None:
        """Le parcours simulé du fichier appelé, en deux chemins (coupe,
        air) — rapide même sur cent mille mouvements."""
        from src.core import sim_cycles
        self._parcours_externe_trace = False
        diametres = (sim_cycles.diametres_de(self._tool_library)
                     if self._tool_library is not None else {})
        res = sim_cycles.parcours_fichier(chemin, diametres)
        if not res or len(res.get('x') or []) < 2:
            return
        self._dessiner_parcours(res, offset)
        self._parcours_externe_trace = True

    def _draw_lignes_main(self, op, offset=(0.0, 0.0)) -> None:
        """Les lignes d'un Main importé: leur parcours simulé (une
        gravure), à la couleur de l'outil qu'elles prennent; une ligne
        de légende seulement si elles coupent."""
        from src.core import sim_cycles, sim3d
        from src.operations.lignes_main import LignesMain
        diametres = (sim_cycles.diametres_de(self._tool_library)
                     if self._tool_library is not None else {})
        params = getattr(op, 'params', {}) or {}
        res = LignesMain.parcours(params, diametres)
        if not res:
            return
        article, outil = LignesMain.outil(params, res, self._tool_library)
        if sim3d.COUPE in (res.get('k') or []) \
                and not self._masquer_annot_courante:
            libelle = (f"{outil} [{article}]" if outil and outil != article
                       else (article or "(sans outil)"))
            nom = str(getattr(op, 'group_name', '')
                      or getattr(op, 'name', '') or '?')
            entree = (article or "?", nom, libelle)
            if entree not in self._legend_rows:
                self._legend_rows.append(entree)
        self._dessiner_parcours(res, offset, article)

    def _dessiner_parcours(self, res, offset, article="") -> None:
        """Un parcours simulé (src.core.sim_cycles) en deux chemins:
        la coupe à la couleur de son outil (`article`, sinon celui que
        le parcours prend), l'air en pointillé."""
        from src.core import sim3d
        import numpy as np
        from src.gui.polygones import polygone
        dx, dy = offset
        coupe, air = QPainterPath(), QPainterPath()
        ks = np.asarray(res['k'])
        n = len(ks)
        if n >= 2:
            xy = np.column_stack([np.asarray(res['x'], dtype=float) + dx,
                                  -(np.asarray(res['y'], dtype=float)
                                    + dy)])
            # les tronçons de même genre (le segment i va du sommet i-1
            # au sommet i): un sous-chemin chacun, rempli d'un bloc
            genre = np.where(ks == sim3d.DEPART, 0,
                             np.where(ks == sim3d.COUPE, 1, 2))
            change = np.flatnonzero(genre[2:] != genre[1:-1]) + 2
            debuts = np.concatenate(([1], change)).tolist()
            fins = np.concatenate((change - 1, [n - 1])).tolist()
            for i, j in zip(debuts, fins):
                if genre[i]:
                    (coupe if genre[i] == 1 else air).addPolygon(
                        polygone(xy[i - 1:j + 1]))
        couleur = None
        article = article or next(
            (o for o in (res.get('outil') or []) if o), "")
        if article:
            couleur = self.tool_color(article, str(article))
        if not coupe.isEmpty():
            c = QColor(couleur) if couleur is not None \
                else QColor(250, 179, 135)
            c.setAlpha(210)
            item = self._scene.addPath(coupe, QPen(c, 0.15))
            item.setVisible(self._show_all_ops)
            self._op_point_items.append(item)
        if not air.isEmpty():
            stylo = QPen(QColor(116, 199, 236, 90), 0.1)
            stylo.setStyle(Qt.PenStyle.DashLine)
            item = self._scene.addPath(air, stylo)
            item.setVisible(self._show_all_ops)
            self._op_point_items.append(item)

    #: les tracés des séquences déjà lues: texte → (coupe, rapides).
    #: Un clic sur une opé relisait tout le SimPL de chaque bloc importé
    #: (41 ms par clic sur un programme de 12 opés). Commun aux canvas;
    #: borné en caractères gardés.
    _CHEMINS_SEQ = None
    CHEMINS_SEQ_MAX_CARACTERES = 16_000_000

    @staticmethod
    def _chemins_de(sequences: dict):
        cut_path = QPainterPath()
        rapid_path = QPainterPath()
        for seq in sequences.values():
            for x1, y1, x2, y2, cutting in seq['segments']:
                target = cut_path if cutting else rapid_path
                target.moveTo(x1, -y1)
                target.lineTo(x2, -y2)
        return cut_path, rapid_path

    @classmethod
    def chemins_de_sequences(cls, texte: str):
        """(coupe, rapides) des séquences « $$$ » d'un texte SimPL,
        lues une fois puis gardées."""
        from collections import OrderedDict
        if cls._CHEMINS_SEQ is None:
            DxfCanvas._CHEMINS_SEQ = OrderedDict()
        cache = cls._CHEMINS_SEQ
        trouve = cache.get(texte)
        if trouve is not None:
            cache.move_to_end(texte)
            return trouve
        from src.io.simpl_analyzer import parse_sequences
        try:
            sequences = parse_sequences(texte)
        except Exception:
            sequences = {}
        chemins = cls._chemins_de(sequences) if sequences else (
            QPainterPath(), QPainterPath())
        cache[texte] = chemins
        total = sum(len(k) for k in cache)
        while len(cache) > 1 and total > cls.CHEMINS_SEQ_MAX_CARACTERES:
            vieux, _c = cache.popitem(last=False)
            total -= len(vieux)
        return chemins

    def _draw_sequence_paths(self, sequences: dict, color=None):
        """Parcours outil vectoriels des séquences Datron: la coupe
        (dans la matière) prend la couleur de l'OUTIL, les rapides
        (hors matière) restent en bleu pointillé.
        Un QPainterPath par type (performance)."""
        self._poser_chemins_sequences(*self._chemins_de(sequences),
                                      color=color)

    def _poser_chemins_sequences(self, cut_path, rapid_path, color=None):
        if not cut_path.isEmpty():
            cut_color = (QColor(color) if color is not None
                         else QColor(250, 179, 135))
            cut_color.setAlpha(210)
            cut_item = self._scene.addPath(
                cut_path, QPen(cut_color, 0.15))
            cut_item.setVisible(self._show_all_ops)
            self._op_point_items.append(cut_item)
        if not rapid_path.isEmpty():
            rp = QPen(QColor(116, 199, 236, 90), 0.1)
            rp.setStyle(Qt.PenStyle.DashLine)
            rapid_item = self._scene.addPath(rapid_path, rp)
            rapid_item.setVisible(self._show_all_ops)
            self._op_point_items.append(rapid_item)

    def _draw_engrave_text(self, op, points: list, color=None,
                           offset=(0.0, 0.0)):
        """Le texte gravé, à sa hauteur de caractère RÉELLE.

        Une croix ne dit ni ce qui est écrit ni la place que ça prend:
        c'est justement ce qu'on veut voir avant d'usiner."""
        p = getattr(op, 'params', {}) or {}
        text = str(p.get('text', '') or '').strip()
        if not text:
            return
        try:
            height = float(p.get('char_height', 2.5) or 2.5)
            rotation = float(p.get('rotation', 0.0) or 0.0)
        except (TypeError, ValueError):
            height, rotation = 2.5, 0.0
        if height <= 0:
            return
        font = QFont("Arial")
        # Police construite à taille arbitraire puis MISE À L'ÉCHELLE:
        # une taille en points ne dit rien des millimètres usinés
        font.setPointSizeF(100.0)
        pen_color = QColor(color) if color is not None \
            else QColor("#00e5ff")
        for pt in points:
            for px, py in self._op_positions(op, pt):
                path = QPainterPath()
                path.addText(0, 0, font, text)
                rect = path.boundingRect()
                if rect.height() <= 0:
                    continue
                scale = height / rect.height()
                tf = QTransform()
                tf.translate(px + offset[0], -(py + offset[1]))
                tf.rotate(-rotation)
                tf.scale(scale, scale)
                # Centré sur le point, comme l'option Center de Datron
                tf.translate(-rect.center().x(), -rect.center().y())
                item = self._scene.addPath(
                    tf.map(path), QPen(pen_color, 0.08))
                item.setVisible(self._show_all_ops)
                self._op_point_items.append(item)

    #: longueur des flèches d'un repère dessiné (mm)
    LONGUEUR_REPERE = 6.0

    def dessiner_repere(self, x: float, y: float, angle: float = 0.0,
                        couleur: str = "#f5c2e7") -> list:
        """Un repère (flèches X et Y) posé en (x, y) machine, tourné de
        `angle` degrés: là où le programme a déplacé ou tourné son
        origine. Rend les items posés."""
        items = []
        a = math.radians(angle)
        L = self.LONGUEUR_REPERE
        stylo = QPen(QColor(couleur), 0.25)
        for nom, ang in (("X", a), ("Y", a + math.pi / 2)):
            fx, fy = x + L * math.cos(ang), y + L * math.sin(ang)
            chemin = QPainterPath()
            chemin.moveTo(x, -y)
            chemin.lineTo(fx, -fy)
            # la pointe
            for d in (2.6, -2.6):
                chemin.moveTo(fx, -fy)
                chemin.lineTo(fx - 1.2 * math.cos(ang + d / 3),
                              -(fy - 1.2 * math.sin(ang + d / 3)))
            item = self._scene.addPath(chemin, stylo)
            item.setVisible(self._show_all_ops)
            item.setData(2, f"repère {nom}")
            self._op_point_items.append(item)
            items.append(item)
        return items

    def _draw_trace_op(self, op, color=None, offset=(0.0, 0.0)):
        """Parcours du centre de la fraise (opération Tracé).

        Dessiné depuis les MÊMES paramètres que la génération: ce
        qu'on voit est ce qui sera usiné."""
        try:
            from src.operations.trace import Trace
            params = dict(op.params or {},
                          _diametre_outil=self._tool_diameter(op))
            tous = Trace.chemins(params, op.x + offset[0],
                                 op.y + offset[1],
                                 getattr(op, 'points', None))
        except Exception:
            return
        tous = [p for p in tous if len(p) >= 2]
        if not tous:
            return
        pts = tous[0]
        path = QPainterPath()
        for chemin in tous:
            path.moveTo(chemin[0][0], -chemin[0][1])
            for px, py in chemin[1:]:
                path.lineTo(px, -py)
        pen_color = QColor(color) if color is not None \
            else QColor(250, 179, 135)
        pen_color.setAlpha(220)
        item = self._scene.addPath(path, QPen(pen_color, 0.15))
        item.setVisible(self._show_all_ops)
        self._op_point_items.append(item)
        # Point de départ: on doit savoir par où l'outil entre
        r = 0.4
        x0, y0 = pts[0][0], -pts[0][1]
        dot = self._scene.addEllipse(
            x0 - r, y0 - r, 2 * r, 2 * r, QPen(pen_color, 0.12))
        dot.setVisible(self._show_all_ops)
        self._op_point_items.append(dot)

    def _draw_sequence_op(self, op):
        """Prévisualise une opération Séquence Datron (code embarqué).
        Les ajustements Z (échelle/offset) sont appliqués — la visu
        reflète ce qui sera réellement généré."""
        params = getattr(op, 'params', {}) or {}
        code = str(params.get('sequence_code', '') or '')
        if not code.strip():
            return
        try:
            from src.operations.sequence_datron import SequenceDatron
            block = SequenceDatron.build_sequence_block(params)
        except Exception:
            return
        self._poser_chemins_sequences(*self.chemins_de_sequences(block))

    #: teintes distinctes d'un passage 3D. Douze suffisent a lire
    #: la remontee, et gardent l'apercu leger.
    _NIVEAUX_3D = 12

    def _draw_anneaux(self, op, anneaux, color) -> None:
        """Des tours fermés (machine, Y vers le haut), au trait de
        l'outil."""
        chemin = QPainterPath()
        for anneau in anneaux or []:
            if len(anneau) < 2:
                continue
            chemin.moveTo(anneau[0][0], -anneau[0][1])
            for px, py in anneau[1:]:
                chemin.lineTo(px, -py)
            chemin.closeSubpath()
        if chemin.isEmpty():
            return
        stylo = QPen(QColor(color) if color else QColor("#f9e2af"), 0.12)
        item = self._scene.addPath(chemin, stylo)
        item.setToolTip(f"{op.name} — ébavurage")
        item.setVisible(self._show_all_ops)
        self._op_point_items.append(item)

    def _draw_contours_en_attente(self, op, classe, params):
        """Le contour d'une gravure dont le parcours n'est pas
        calculé: pointillé, et l'infobulle dit quoi faire."""
        try:
            contours = classe.contours(params)
        except Exception:
            return
        chemin = QPainterPath()
        for contour in contours:
            if len(contour) < 2:
                continue
            chemin.moveTo(contour[0][0], -contour[0][1])
            for px, py in contour[1:]:
                chemin.lineTo(px, -py)
            chemin.closeSubpath()
        if chemin.isEmpty():
            return
        from src.gui.theme import COLORS
        stylo = QPen(QColor(COLORS.get('text_muted', '#7f849c')), 0.0)
        stylo.setStyle(Qt.PenStyle.DashLine)
        stylo.setCosmetic(True)
        item = self._scene.addPath(chemin, stylo)
        item.setToolTip(
            f"{op.name} — parcours non calculé: bouton "
            "« Calculer parcours » ou « Calculer gamme »")
        item.setVisible(self._show_all_ops)
        self._op_point_items.append(item)

    def _draw_passes_coniques(self, op):
        """Parcours d'une gravure 2,5D ou d'un évidement.

        Le fond est le trait le plus clair: on voit d'un coup d'œil
        jusqu'où la gravure descend, et où les angles remontent. Un
        passage 3D change de profondeur en chemin: il est découpé en
        segments, chacun à sa teinte — c'est la remontée qu'on voit
        s'installer."""
        try:
            from src.operations.registry import OperationRegistry
            classe = OperationRegistry.get(op.operation_type)
            # L'aperçu ne DÉCLENCHE pas le calcul: sur un dessin
            # chargé, il repartait à chaque redessin. Il montre ce
            # qui est déjà calculé; le bouton du formulaire fait le
            # travail une fois.
            from src.operations.gravure_2d5 import params_outil
            params = params_outil(op, self._tool_library)
            plan = classe.plan_si_connu(params)
        except Exception:
            return
        if plan is None:
            # Pas encore calculé: on montre au moins OÙ est
            # l'opération — son contour, en pointillé — sinon la
            # liste dit « gravure » et le dessin ne montre rien.
            self._draw_contours_en_attente(op, classe, params)
            return
        if not plan:
            return
        fond = 0.0
        for etape in plan:
            if etape['type'] == 'anneau':
                fond = max(fond, float(etape['profondeur']))
            else:
                fond = max([fond] + [z for _x, _y, z
                                     in etape['points']])
        fond = fond or 1.0

        def _teinte(profondeur):
            part = min(1.0, max(0.0, float(profondeur) / fond))
            return QColor.fromHsvF(0.09, 0.75, 0.45 + 0.5 * part)

        tranches = {}
        for etape in plan:
            if etape['type'] == 'anneau':
                chemin = QPainterPath()
                vide = True
                for contour in etape['contours']:
                    if len(contour) < 2:
                        continue
                    chemin.moveTo(contour[0][0], -contour[0][1])
                    for px, py in contour[1:]:
                        chemin.lineTo(px, -py)
                    vide = False
                if vide:
                    continue
                item = self._scene.addPath(
                    chemin, QPen(_teinte(etape['profondeur']), 0.1))
                item.setToolTip(
                    f"{op.name} — Z {-etape['profondeur']:g} mm")
                item.setVisible(self._show_all_ops)
                self._op_point_items.append(item)
                continue
            # Passage 3D: la profondeur change a chaque point. Un
            # item par segment ferait des centaines d'items pour une
            # seule operation — on les groupe par TRANCHE de teinte,
            # sur TOUTE l'operation: groupées par chaîne, une
            # signature de 280 chaînes rendait 667 items.
            points = etape['points']
            for (x1, y1, z1), (x2, y2, z2) in zip(points, points[1:]):
                part = min(1.0, max(0.0, ((z1 + z2) / 2.0) / fond))
                niveau = int(round(part * (self._NIVEAUX_3D - 1)))
                chemin = tranches.get(niveau)
                if chemin is None:
                    chemin = tranches[niveau] = QPainterPath()
                chemin.moveTo(x1, -y1)
                chemin.lineTo(x2, -y2)

        for niveau, chemin in sorted(tranches.items()):
            part = niveau / max(1, self._NIVEAUX_3D - 1)
            item = self._scene.addPath(
                chemin, QPen(_teinte(part * fond), 0.14))
            item.setToolTip(f"{op.name} — 3D, Z {-part * fond:.2f} mm")
            item.setVisible(self._show_all_ops)
            self._op_point_items.append(item)

    def _draw_bloc_simpl(self, op, keep_existing: bool = False,
                         color=None):
        """Dessine un bloc importé: les positions de son
        sous-programme et le parcours de la séquence appelée.

        Les réglages de l'utilisateur (troncature, offset Z) sont
        appliqués: la visu montre ce qui sera RÉELLEMENT usiné."""
        params = getattr(op, 'params', {}) or {}
        try:
            from src.operations.bloc_simpl import BlocSimpl
            body = BlocSimpl.body(params)
            seq = BlocSimpl.sequence_block(params)
        except Exception:
            body, seq = str(params.get('body', '') or ''), ""

        if seq.strip():
            self._poser_chemins_sequences(*self.chemins_de_sequences(seq),
                                          color=color)

        # Positions du sous-programme lui-même (SafeRapid/Rapid)
        points = []
        for m in re.finditer(
                r'\b(?:SafeRapid|Rapid|PrePositioning)\s+'
                r'X\s*=\s*([-+]?[\d.]+)\s+Y\s*=\s*([-+]?[\d.]+)',
                body):
            pt = {'x': float(m.group(1)), 'y': float(m.group(2))}
            if color is not None:
                pt['color'] = color.name()
            points.append(pt)
        if points:
            self.draw_operation_points(
                points, label_prefix=getattr(op, 'name', 'Bloc') + " ",
                source="op", keep_existing=keep_existing)

    def _draw_pattern_preview(self, base_points: list, params: dict):
        """Dessine un aperçu léger des points de pattern sur le canvas."""
        pat_type = params.get('pattern_type', 'Rectangle')
        pen = QPen(QColor(255, 165, 0, 100), 0.15)  # orange translucide

        generated = []
        if pat_type == "Circle":
            count = int(params.get('circle_count', 6))
            radius = float(params.get('circle_radius', 20.0))
            start = float(params.get('circle_start_angle', 0.0))
            for bp in base_points:
                bx, by = bp.get('x', 0), bp.get('y', 0)
                for i in range(count):
                    angle = math.radians(start + i * 360.0 / count)
                    generated.append({
                        'x': bx + radius * math.cos(angle),
                        'y': by + radius * math.sin(angle)})
        elif pat_type == "Linear":
            count = int(params.get('linear_count', 4))
            delta = float(params.get('linear_delta', 10.0))
            angle = math.radians(float(params.get('linear_angle', 0.0)))
            dx = delta * math.cos(angle)
            dy = delta * math.sin(angle)
            for bp in base_points:
                bx, by = bp.get('x', 0), bp.get('y', 0)
                for i in range(count):
                    generated.append({'x': bx + i * dx, 'y': by + i * dy})
        else:  # Rectangle
            nx = int(params.get('x_count', 1))
            ny = int(params.get('y_count', 1))
            ddx = float(params.get('delta_x', 10.0))
            ddy = float(params.get('delta_y', 10.0))
            for bp in base_points:
                bx, by = bp.get('x', 0), bp.get('y', 0)
                for ix in range(nx):
                    for iy in range(ny):
                        generated.append({
                            'x': bx + ix * ddx, 'y': by + iy * ddy})

        # Dessiner les points pattern (croix légère orange)
        r = 0.3
        for pt in generated:
            x = pt['x']
            y_s = -pt['y']  # DXF→scene y inversé
            l1 = self._scene.addLine(x - r, y_s - r, x + r, y_s + r, pen)
            l2 = self._scene.addLine(x - r, y_s + r, x + r, y_s - r, pen)
            self._op_point_items.extend([l1, l2])

    def _draw_per_point_patterns(self, pattern_points: list):
        """Expanse les grilles des points pattern (croix oranges)."""
        pen = QPen(QColor(255, 165, 0, 110), 0.15)
        r = 0.3
        for pt in pattern_points:
            bx, by = pt.get('x', 0), pt.get('y', 0)
            nx = max(1, int(pt.get('x_count', 1)))
            ny = max(1, int(pt.get('y_count', 1)))
            dx = float(pt.get('delta_x', 10.0))
            dy = float(pt.get('delta_y', 10.0))
            for ix in range(nx):
                for iy in range(ny):
                    if ix == 0 and iy == 0:
                        continue  # point de base déjà affiché
                    x = bx + ix * dx
                    y_s = -(by + iy * dy)
                    l1 = self._scene.addLine(
                        x - r, y_s - r, x + r, y_s + r, pen)
                    l2 = self._scene.addLine(
                        x - r, y_s + r, x + r, y_s - r, pen)
                    self._op_point_items.extend([l1, l2])

    def _draw_repeat_preview(self, base_points: list, params: dict):
        """Dessine un aperçu des répétitions (REPEAT_PARAMS, deux
        niveaux) sur le canvas."""
        from src.core import repetition
        decalages = repetition.positions(params)
        pen = QPen(QColor(180, 130, 255, 100), 0.15)  # violet translucide

        r = 0.25
        for bp in base_points:
            bx, by = bp.get('x', 0), bp.get('y', 0)
            for dx, dy in decalages[1:]:      # la base est déjà affichée
                x = bx + dx
                y_s = -(by + dy)
                l1 = self._scene.addLine(
                    x - r, y_s - r, x + r, y_s + r, pen)
                l2 = self._scene.addLine(
                    x - r, y_s + r, x + r, y_s - r, pen)
                self._op_point_items.extend([l1, l2])

    def _extend_scene_rect(self):
        """Étend la scène si les entités sont en dehors."""
        if not self._dxf_items:
            return
        items_rect = QRectF()
        for item in self._dxf_items:
            items_rect = items_rect.united(item.sceneBoundingRect())
        # Ajouter une large marge
        margin = max(items_rect.width(), items_rect.height(), 100) * 2
        extended = items_rect.adjusted(-margin, -margin, margin, margin)
        current = self._scene.sceneRect()
        self._scene.setSceneRect(current.united(extended))

    # Au-delà de ce nombre d'entités, fusion en paths par couleur
    # (des dizaines de milliers de QGraphicsItems rendent Qt inutilisable)
    _MERGE_THRESHOLD = 4000

    def _render_entities_merged(self, entities, progress=None) -> bool:
        """MODE PERFORMANCE (gros DXF): fusionne les entités en un
        QPainterPath par couleur — quelques items au lieu de dizaines
        de milliers. La sélection individuelle d'entités est alors
        indisponible (la détection de centres GenOps reste complète).
        Retourne True si l'utilisateur a annulé."""
        from PySide6.QtWidgets import QApplication
        paths: Dict[str, QPainterPath] = {}
        cancelled = False
        for i, entity in enumerate(entities):
            color = self._get_entity_color(entity).name()
            path = paths.get(color)
            if path is None:
                path = QPainterPath()
                paths[color] = path
            try:
                self._entity_to_path(entity, path)
            except Exception:
                pass
            if progress is not None and i % 500 == 0:
                progress.setValue(i)
                QApplication.processEvents()
                if progress.wasCanceled():
                    cancelled = True
                    break
        for color, path in paths.items():
            if path.isEmpty():
                continue
            item = self._scene.addPath(path, QPen(QColor(color), 0.2))
            self._register_item(item, 'dxf')
        self._extend_scene_rect()
        self.entity_info.emit(
            f"Mode performance: {len(entities)} entités fusionnées "
            f"({len(paths)} tracés) — sélection par entité désactivée")
        return cancelled

    #: finesse d'aplatissement des courbes, en mm (valeur TauDrive:
    #: 0.1 mm rendait un petit percage anguleux)
    FLATTENING_MM = 0.02

    def _points_reels(self, entity) -> list:
        """Sommets d'une polyligne, arcs compris.

        Une POLYLINE dont les sommets portent un « bulge » décrit des
        arcs: lue sommet par sommet, elle passe pour un polygone."""
        from ezdxf import path as ezpath
        try:
            chemin = ezpath.make_path(entity)
            return [(v.x, v.y)
                    for v in chemin.flattening(self.FLATTENING_MM)]
        except (ValueError, TypeError, AttributeError):
            return []

    def _polyline_path(self, entity) -> Optional[QPainterPath]:
        """Chemin d'une entité, courbes GARDÉES EN COURBES.

        `ezdxf.path.make_path` sait ce qu'une entité contient
        vraiment: une polyligne dont les sommets portent un « bulge »
        est faite d'arcs, pas de segments. Elle les rend en Béziers
        cubiques — et Qt en dessine aussi. On les recopie tels quels:
        le tracé reste vectoriel, net à n'importe quel zoom, et pèse
        huit commandes au lieu de mille segments.

        (`flattening` reste la voie de secours, et sert toujours à la
        détection de centres, qui raisonne sur des points.)"""
        from ezdxf import path as ezpath
        try:
            chemin = ezpath.make_path(entity)
        except (ValueError, TypeError, AttributeError):
            return None
        return self._chemin_qt(chemin)

    @staticmethod
    def _chemin_qt(chemin, sortie: QPainterPath = None):
        """Un chemin ezdxf recopié en chemin Qt, COURBES COMPRISES.

        Les deux bibliothèques parlent la même langue: des Béziers
        cubiques et quadratiques. Il n'y a rien à échantillonner."""
        from ezdxf.path import Command
        out = QPainterPath() if sortie is None else sortie
        vide = True
        for sous in (chemin.sub_paths() or [chemin]):
            commandes = list(sous.commands())
            if not commandes:
                continue
            debut = sous.start
            out.moveTo(debut.x, -debut.y)
            for c in commandes:
                fin = c.end
                if c.type == Command.LINE_TO:
                    out.lineTo(fin.x, -fin.y)
                elif c.type == Command.CURVE4_TO:
                    out.cubicTo(c.ctrl1.x, -c.ctrl1.y,
                                c.ctrl2.x, -c.ctrl2.y,
                                fin.x, -fin.y)
                elif c.type == Command.CURVE3_TO:
                    out.quadTo(c.ctrl.x, -c.ctrl.y, fin.x, -fin.y)
                else:                       # MOVE_TO
                    out.moveTo(fin.x, -fin.y)
            vide = False
        if sortie is not None:
            return out if not vide else None
        return None if vide else out

    def _entity_to_path(self, entity, path: QPainterPath):
        """Ajoute la géométrie d'une entité DXF à un QPainterPath
        (types principaux — utilisé par le mode performance)."""
        dxf_type = entity.dxftype()
        if dxf_type == 'LINE':
            s, e = entity.dxf.start, entity.dxf.end
            path.moveTo(s.x, -s.y)
            path.lineTo(e.x, -e.y)
        elif dxf_type == 'CIRCLE':
            c, r = entity.dxf.center, entity.dxf.radius
            path.addEllipse(c.x - r, -c.y - r, 2 * r, 2 * r)
        elif dxf_type == 'ARC':
            c, r = entity.dxf.center, entity.dxf.radius
            start = entity.dxf.start_angle
            span = entity.dxf.end_angle - start
            if span <= 0:
                span += 360
            rect = QRectF(c.x - r, -c.y - r, 2 * r, 2 * r)
            path.arcMoveTo(rect, start)
            path.arcTo(rect, start, span)
        elif dxf_type in ('LWPOLYLINE', 'POLYLINE', 'SPLINE',
                          'ELLIPSE'):
            morceau = self._polyline_path(entity)
            if morceau is not None:
                path.addPath(morceau)

    @staticmethod
    def _iter_entities(entities, depth: int = 0, max_depth: int = 4):
        """Itère des entités DXF en EXPANSANT les blocs INSERT
        (récursif, transformations appliquées par ezdxf)."""
        for e in entities:
            try:
                is_insert = e.dxftype() == 'INSERT'
            except Exception:
                continue
            if is_insert and depth < max_depth:
                try:
                    yield from DxfCanvas._iter_entities(
                        e.virtual_entities(), depth + 1, max_depth)
                except Exception:
                    continue
            else:
                yield e

    def _render_entity(self, entity) -> Optional[QGraphicsItem]:
        """Rend une entité DXF en item graphique."""
        dxf_type = entity.dxftype()
        color = self._get_entity_color(entity)
        pen = QPen(color, 0.2)

        try:
            if dxf_type == 'LINE':
                return self._render_line(entity, pen)
            elif dxf_type == 'CIRCLE':
                return self._render_circle(entity, pen)
            elif dxf_type == 'ARC':
                return self._render_arc(entity, pen)
            elif dxf_type == 'LWPOLYLINE':
                return self._render_lwpolyline(entity, pen)
            elif dxf_type == 'POLYLINE':
                return self._render_polyline(entity, pen)
            elif dxf_type == 'POINT':
                return self._render_point(entity, pen)
            elif dxf_type == 'TEXT' or dxf_type == 'MTEXT':
                return self._render_text(entity, color)
            elif dxf_type == 'ELLIPSE':
                return self._render_ellipse(entity, pen)
            elif dxf_type == 'SPLINE':
                return self._render_spline(entity, pen)
            elif dxf_type == 'INSERT':
                return self._render_insert(entity, pen)
            elif dxf_type == 'DIMENSION':
                return self._render_dimension(entity, pen)
            elif dxf_type == 'HATCH':
                return self._render_hatch(entity, pen)
        except Exception:
            pass
        return None

    def _get_entity_color(self, entity) -> QColor:
        try:
            color = entity.dxf.color
            if color == 256:
                return QColor("#cdd6f4")
            return aci_to_qcolor(color)
        except Exception:
            return QColor("#cdd6f4")

    def _render_line(self, entity, pen) -> QGraphicsItem:
        start = entity.dxf.start
        end = entity.dxf.end
        return self._scene.addLine(
            start.x, -start.y, end.x, -end.y, pen)

    def _render_circle(self, entity, pen) -> QGraphicsItem:
        center = entity.dxf.center
        r = entity.dxf.radius
        return self._scene.addEllipse(
            center.x - r, -center.y - r, 2 * r, 2 * r, pen)

    def _render_arc(self, entity, pen) -> QGraphicsItem:
        center = entity.dxf.center
        r = entity.dxf.radius
        start_angle = entity.dxf.start_angle
        end_angle = entity.dxf.end_angle

        span = end_angle - start_angle
        if span <= 0:
            span += 360

        path = QPainterPath()
        rect = QRectF(center.x - r, -center.y - r, 2 * r, 2 * r)
        path.arcMoveTo(rect, start_angle)
        path.arcTo(rect, start_angle, span)
        return self._scene.addPath(path, pen)

    def _render_lwpolyline(self, entity, pen) -> QGraphicsItem:
        """Une LWPOLYLINE passe par la même route que les autres.

        Le calcul d'arc maison tournait les congés À L'ENVERS: un
        rectangle 100 × 60 à coins R10 sortait en 120 × 80, bombé
        vers l'extérieur. ezdxf sait faire, lui."""
        path = self._polyline_path(entity)
        if path is None:
            return None
        return self._scene.addPath(path, pen)

    def _render_polyline(self, entity, pen) -> QGraphicsItem:
        # Les sommets d'une POLYLINE portent souvent un « bulge »:
        # un cercle s'exporte en quatre sommets et quatre arcs
        path = self._polyline_path(entity)
        if path is None:
            return None
        return self._scene.addPath(path, pen)

    def _render_point(self, entity, pen) -> QGraphicsItem:
        loc = entity.dxf.location
        size = 0.5
        return self._scene.addEllipse(
            loc.x - size / 2, -loc.y - size / 2,
            size, size, pen, QBrush(pen.color()))

    #: les codes de contrôle d'AutoCAD dans un texte (cotes, TEXT)
    _CODES_TEXTE = (("%%c", "Ø"), ("%%C", "Ø"), ("%%d", "°"), ("%%D", "°"),
                    ("%%p", "±"), ("%%P", "±"), ("%%%", "%"))

    @classmethod
    def _decoder_texte(cls, texte: str) -> str:
        for code, car in cls._CODES_TEXTE:
            texte = texte.replace(code, car)
        return texte

    def _render_text(self, entity, color: QColor) -> QGraphicsItem:
        """Texte DXF VECTORISÉ (path de glyphes): net à tout zoom,
        exportable en DXF comme le reste (polylignes de contours). Son
        point d'accroche (centré, en haut… — les textes des cotes) et sa
        rotation (un MTEXT la porte par sa direction) sont respectés;
        %%c, %%d, %%p deviennent Ø, °, ±."""
        hor, ver = 0, 'base'
        try:
            if entity.dxftype() == 'MTEXT':
                text = entity.plain_text() if hasattr(
                    entity, 'plain_text') else entity.text
                pos = entity.dxf.insert
                height = float(entity.dxf.char_height)
                try:
                    rotation = float(entity.get_rotation())
                except Exception:
                    rotation = float(getattr(entity.dxf, 'rotation', 0.0)
                                     or 0.0)
                att = int(entity.dxf.get('attachment_point', 1) or 1)
                hor = (att - 1) % 3
                ver = ('haut', 'milieu', 'bas')[min(2, (att - 1) // 3)]
            else:
                text = entity.dxf.text
                pos = entity.dxf.insert
                height = float(entity.dxf.height)
                rotation = float(getattr(entity.dxf, 'rotation', 0.0)
                                 or 0.0)
                halign = int(entity.dxf.get('halign', 0) or 0)
                valign = int(entity.dxf.get('valign', 0) or 0)
                if (halign or valign) and entity.dxf.hasattr('align_point'):
                    pos = entity.dxf.align_point
                hor = {0: 0, 1: 1, 2: 2}.get(halign, 1)
                ver = {0: 'base', 1: 'bas', 2: 'milieu', 3: 'haut'}.get(
                    valign, 'base')
        except Exception:
            return None
        text = self._decoder_texte((text or "").strip())
        if not text or height <= 0:
            return None

        font = QFont("Arial")
        font.setPointSizeF(100.0)
        raw = QPainterPath()
        raw.addText(0, 0, font, text)
        br = raw.boundingRect()
        if br.height() <= 0:
            return None
        # Échelle: la hauteur de police DXF = hauteur des majuscules
        scale = height / (font.pointSizeF() * 0.72)
        # l'accroche: le point d'insertion à gauche/centre/droite, en
        # haut/milieu/bas/ligne de base du texte
        dx = -(br.left() + br.width() * hor / 2.0)
        dy = {'haut': -br.top(), 'milieu': -(br.top() + br.height() / 2),
              'bas': -br.bottom()}.get(ver, 0.0)
        transform = QTransform()
        transform.translate(pos.x, -pos.y)
        if rotation:
            transform.rotate(-rotation)
        transform.scale(scale, scale)
        transform.translate(dx, dy)
        path = transform.map(raw)
        item = self._scene.addPath(
            path, QPen(color, 0.05), QBrush(QColor(
                color.red(), color.green(), color.blue(), 110)))
        return item

    def _render_ellipse(self, entity, pen) -> QGraphicsItem:
        try:
            # Arc d'ellipse partiel: échantillonner (sinon la figure
            # serait fausse — ellipse complète au lieu de l'arc)
            start = float(getattr(entity.dxf, 'start_param', 0.0))
            end = float(getattr(entity.dxf, 'end_param', math.tau))
            if abs((end - start) % math.tau) > 1e-6 \
                    and abs(end - start - math.tau) > 1e-6:
                # ezdxf rend l'arc en Béziers, bornes comprises: le
                # tracé reste lisse là où 0,05 mm de corde se voyait
                path = self._polyline_path(entity)
                if path is None:
                    return None
                return self._scene.addPath(path, pen)

            center = entity.dxf.center
            major_axis = entity.dxf.major_axis
            ratio = entity.dxf.ratio
            a = math.sqrt(major_axis.x**2 + major_axis.y**2)
            b = a * ratio
            angle = math.degrees(math.atan2(major_axis.y, major_axis.x))

            item = self._scene.addEllipse(-a, -b, 2 * a, 2 * b, pen)
            item.setPos(center.x, -center.y)
            item.setRotation(-angle)
            return item
        except Exception:
            return None

    def _render_spline(self, entity, pen) -> QGraphicsItem:
        try:
            path = self._polyline_path(entity)
            if path is None:
                return None
            return self._scene.addPath(path, pen)
        except Exception:
            return None

    def _render_insert(self, entity, pen) -> QGraphicsItem:
        try:
            pos = entity.dxf.insert
            name = entity.dxf.name
            item = QGraphicsTextItem(f"[{name}]")
            item.setDefaultTextColor(QColor("#f9e2af"))
            item.setPos(pos.x, -pos.y)
            item.setScale(0.3)
            self._scene.addItem(item)
            return item
        except Exception:
            return None

    def _render_dimension(self, entity, pen) -> QGraphicsItem:
        """Une cote: sa géométrie (lignes d'attache, ligne de cote,
        flèches, texte) — celle de son bloc, lue par ezdxf —, en un
        groupe. Le texte seul, posé à son point de définition, faisait
        lire « %%c » au pied du dessin."""
        items = []
        try:
            # les flèches sont des blocs (_ARCHTICK…): dépliés
            for ve in self._iter_entities(entity.virtual_entities()):
                it = self._render_entity(ve)
                if it is not None:
                    items.append(it)
        except Exception:
            items = []
        if items:
            return self._scene.createItemGroup(items)
        try:
            text = self._decoder_texte(
                entity.dxf.text if hasattr(entity.dxf, 'text') else "")
            defpoint = entity.dxf.defpoint
            item = QGraphicsTextItem(text or "dim")
            item.setDefaultTextColor(QColor("#89dceb"))
            item.setPos(defpoint.x, -defpoint.y)
            item.setScale(0.2)
            self._scene.addItem(item)
            return item
        except Exception:
            return None

    def _render_hatch(self, entity, pen) -> QGraphicsItem:
        """Le bord d'une hachure suit ses arcs.

        Lu sommet par sommet, un contour arrondi rendait un polygone
        — et la zone hachurée débordait de la pièce."""
        from ezdxf import path as ezpath
        try:
            qpath = QPainterPath()
            vide = True
            try:
                for chemin in ezpath.from_hatch(entity):
                    if self._chemin_qt(chemin, qpath) is not None:
                        qpath.closeSubpath()
                        vide = False
            except (ValueError, TypeError, AttributeError):
                vide = True
            if vide:
                # Contour que ezdxf ne sait pas lire: les sommets
                for bp in entity.paths:
                    verts = list(getattr(bp, 'vertices', []) or [])
                    if not verts:
                        continue
                    qpath.moveTo(verts[0][0], -verts[0][1])
                    for v in verts[1:]:
                        qpath.lineTo(v[0], -v[1])
                    qpath.closeSubpath()
            if qpath.isEmpty():
                return None
            hatch_pen = QPen(pen.color(), 0.1)
            hatch_brush = QBrush(pen.color(),
                                 Qt.BrushStyle.Dense6Pattern)
            return self._scene.addPath(qpath, hatch_pen, hatch_brush)
        except Exception:
            return None

    # ──── Détection de centres ────

    def _detect_centers(self, msp):
        """Détecte les centres de TOUTES les entités avec score de circularité."""
        self._detected_circles.clear()
        self._item_metadata.clear()
        marker_pen = QPen(QColor("#f38ba8"), 0.15)
        marker_size = 0.8

        for entity in msp:
            cx, cy, radius, circularity, etype = None, None, 0, 0.0, ""
            try:
                dtype = entity.dxftype()
                if dtype == 'CIRCLE':
                    c = entity.dxf.center
                    cx, cy = c.x, c.y
                    radius = entity.dxf.radius
                    circularity = 1.0
                    etype = "CIRCLE"
                elif dtype == 'ARC':
                    c = entity.dxf.center
                    cx, cy = c.x, c.y
                    radius = entity.dxf.radius
                    span = entity.dxf.end_angle - entity.dxf.start_angle
                    if span <= 0:
                        span += 360
                    circularity = min(span / 360.0, 1.0)
                    etype = "ARC"
                elif dtype == 'ELLIPSE':
                    c = entity.dxf.center
                    cx, cy = c.x, c.y
                    major = entity.dxf.major_axis
                    radius = math.sqrt(major.x**2 + major.y**2)
                    ratio = entity.dxf.ratio
                    circularity = min(ratio, 1.0 / ratio) if ratio > 0 else 0.0
                    etype = "ELLIPSE"
                elif dtype == 'LWPOLYLINE':
                    pts = self._points_reels(entity) or list(
                        entity.get_points(format='xy'))
                    if len(pts) >= 3 and entity.closed:
                        # Moindres carrés pour trouver le cercle optimal
                        cx, cy, radius = _least_squares_circle(pts)
                        perim = sum(math.sqrt(
                            (pts[i][0]-pts[i-1][0])**2 +
                            (pts[i][1]-pts[i-1][1])**2)
                            for i in range(len(pts)))
                        area = abs(sum(
                            pts[i][0]*pts[(i+1)%len(pts)][1] -
                            pts[(i+1)%len(pts)][0]*pts[i][1]
                            for i in range(len(pts)))) / 2
                        if perim > 0 and area > 0:
                            circularity = min(
                                4 * math.pi * area / (perim**2), 1.0)
                        else:
                            circularity = 0.0
                        etype = "POLYLINE"
                    elif len(pts) >= 2:
                        xs = [p[0] for p in pts]
                        ys = [p[1] for p in pts]
                        cx = sum(xs) / len(xs)
                        cy = sum(ys) / len(ys)
                        circularity = 0.0
                        etype = "POLYLINE"
                elif dtype == 'POLYLINE':
                    verts = list(entity.vertices)
                    if len(verts) >= 3:
                        # Sommets APRÈS aplatissement des arcs: sur les
                        # sommets bruts, un cercle en quatre bulges
                        # notait 0.785 (le rapport d'un cercle à son
                        # carré) et le filtre de circularité l'écartait
                        pts = self._points_reels(entity) or [
                            (v.dxf.location.x, v.dxf.location.y)
                            for v in verts]
                        n = len(pts)
                        is_closed = entity.is_closed
                        # Moindres carrés pour centre précis
                        if is_closed and n >= 3:
                            cx, cy, radius = _least_squares_circle(pts)
                        else:
                            xs = [p[0] for p in pts]
                            ys = [p[1] for p in pts]
                            cx = sum(xs) / n
                            cy = sum(ys) / n
                        # Calcul périmètre / aire
                        if is_closed:
                            loop = pts + [pts[0]]
                        else:
                            loop = pts
                        perim = sum(math.sqrt(
                            (loop[i+1][0]-loop[i][0])**2 +
                            (loop[i+1][1]-loop[i][1])**2)
                            for i in range(len(loop)-1))
                        area = abs(sum(
                            pts[i][0]*pts[(i+1)%n][1] -
                            pts[(i+1)%n][0]*pts[i][1]
                            for i in range(n))) / 2
                        if perim > 0 and area > 0:
                            circularity = min(
                                4 * math.pi * area / (perim**2), 1.0)
                        else:
                            circularity = 0.0
                        etype = "POLYLINE"
                    elif len(verts) >= 2:
                        pts = [(v.dxf.location.x, v.dxf.location.y)
                               for v in verts]
                        cx = sum(p[0] for p in pts) / len(pts)
                        cy = sum(p[1] for p in pts) / len(pts)
                        circularity = 0.0
                        etype = "POLYLINE"
                elif dtype == 'LINE':
                    s = entity.dxf.start
                    e = entity.dxf.end
                    cx = (s.x + e.x) / 2
                    cy = (s.y + e.y) / 2
                    circularity = 0.0
                    etype = "LINE"
                elif dtype == 'POINT':
                    loc = entity.dxf.location
                    cx, cy = loc.x, loc.y
                    circularity = 0.0
                    etype = "POINT"
            except Exception:
                continue

            if cx is not None:
                self._detected_circles.append({
                    'x': cx, 'y': cy, 'radius': radius,
                    'circularity': circularity, 'entity_type': etype
                })
                # Marqueur visuel (créé pour tout centre circulaire,
                # visibilité pilotée par le toggle 'Centres')
                if circularity > 0:
                    sx, sy = cx, -cy
                    line1 = self._scene.addLine(
                        sx - marker_size, sy,
                        sx + marker_size, sy, marker_pen)
                    line2 = self._scene.addLine(
                        sx, sy - marker_size,
                        sx, sy + marker_size, marker_pen)
                    circ = self._scene.addEllipse(
                        sx - marker_size * 0.6, sy - marker_size * 0.6,
                        marker_size * 1.2, marker_size * 1.2, marker_pen)
                    for m in (line1, line2, circ):
                        m.setVisible(self._centers_visible)
                    self._center_markers.extend([line1, line2, circ])

        # Stocker les métadonnées pour chaque item DXF rendu
        self._rebuild_item_metadata()

    def _rebuild_item_metadata(self):
        """Associe chaque item DXF rendu à ses métadonnées (centre,
        circularité). Grille spatiale: O(n) au lieu du produit
        items × centres (quadratique — intenable sur les gros DXF)."""
        self._item_metadata.clear()
        if not self._detected_circles:
            return
        cell = 10.0
        grid: Dict[tuple, list] = {}
        for center in self._detected_circles:
            key = (int(center['x'] // cell), int(center['y'] // cell))
            grid.setdefault(key, []).append(center)

        for item in self._dxf_items:
            rect = item.sceneBoundingRect()
            cx = rect.center().x()
            cy = -rect.center().y()  # Y inversé
            r = max(rect.width(), rect.height()) / 2
            max_dist = max(r * 2, 5)
            best = None
            best_dist = max_dist
            kx, ky = int(cx // cell), int(cy // cell)
            # Borne: un item géant (path fusionné) ne doit pas
            # parcourir des milliers de cellules
            reach = min(int(max_dist // cell) + 1, 20)
            for gx in range(kx - reach, kx + reach + 1):
                for gy in range(ky - reach, ky + reach + 1):
                    for center in grid.get((gx, gy), ()):
                        dist = math.hypot(center['x'] - cx,
                                          center['y'] - cy)
                        if dist < best_dist:
                            best_dist = dist
                            best = center
            # Cohérence taille/position: un item beaucoup plus grand
            # que le cercle (ex: TEXTE voisin) ne doit PAS hériter du
            # centre — sinon il serait exporté comme un cercle
            if best is not None:
                radius = max(float(best.get('radius', 0) or 0), 0.5)
                if (best_dist <= max(radius * 1.5, 2.5)
                        and r <= radius * 3 + 2):
                    self._item_metadata[id(item)] = best

    def detect_centers_manual(self):
        """Relance la détection de centres et émet le signal."""
        if self._detected_circles:
            self.circles_detected.emit(self._detected_circles)

    # ── Dessins vectoriels (noyau TauDrive) ──

    def load_vector(self, filepath: str, progress=None,
                    ajouter: bool = False, options=None) -> dict:
        """Charge un dessin vectoriel: PDF, AI, EPS, PS, SVG, CDR, STEP.

        Le DXF garde sa route propre (couleurs de calque, sélection
        par entité); ces formats-ci n'ont pas d'entités au sens DXF,
        seulement des tracés — on les pose tels quels. `ajouter`:
        superposé au dessin en place (son onglet à lui).

        `progress(fraction, texte)` rend False pour annuler.
        `options`: réglages de lecture (une image: ceux du traceur).
        Retourne le compte rendu de lecture.
        """
        from src.io import vecteur
        calques, rapport = vecteur.lire(filepath, progress=progress,
                                        options=options)
        return self.poser_calques(calques, rapport, filepath, ajouter,
                                  reglages=options)

    def poser_calques(self, calques: dict, rapport, filepath: str,
                      ajouter: bool = False, reglages=None):
        """Pose des tracés déjà lus — {calque: [Chemin]} — comme un
        import: son onglet, ses centres détectés. Une image vectorisée
        dans sa fenêtre arrive par ici (ses `reglages` sont gardés:
        rouvrir l'onglet la retrace pareil)."""
        import dataclasses as _dc
        import os as _os
        from src.io.vecteur import trace_image as _ti
        cercles_avant = []
        if ajouter:
            cercles_avant = list(self._detected_circles)
        else:
            self.clear_dxf()
        if not hasattr(self, '_imports_dxf'):
            self._imports_dxf = []
        if not hasattr(self, '_item_source'):
            self._item_source = {}
        deja = set(map(id, self._dxf_items))
        couleur = QColor("#cdd6f4")
        stylo = QPen(couleur, 0.2)
        polylignes = []
        premier = None
        for nom, tracés in calques.items():
            for trace in tracés:
                if len(trace) < 2:
                    continue
                polylignes.append(list(trace))
                item = self._scene.addPath(
                    self._chemin_vecteur(trace), stylo)
                item.setData(0, nom)
                self._register_item(item, 'dxf')
                premier = premier or item
        from src.io.vecteur import est_piece_3d as _piece_3d
        source_piece = None
        if premier is not None and _piece_3d(filepath):
            # La pièce en volume (bouton « 3D »): son fichier, et une
            # entité témoin — si le dessin est centré ou déplacé, la
            # pièce le suit du même décalage. La dernière importée est
            # la pièce ACTIVE (usinage, faces); les autres restent, en
            # annexe (octobre 2026: une pièce par onglet)
            source_piece = {'chemin': str(filepath), 'repere': premier,
                            'pos0': QPointF(premier.pos())}
            self._source_3d = source_piece
        self._detecter_depuis_polylignes(polylignes)
        trous = getattr(rapport, 'trous', None)
        if trous is not None:
            # Un STEP DIT où sont ses trous (cylindres qui font le
            # tour): on les prend tels quels. La mesure de rondeur
            # prenait une petite poche à coins arrondis pour un cercle
            # — et « Générer » y aurait proposé un perçage.
            self._detected_circles = [{
                'x': t['x'], 'y': t['y'], 'radius': t['diametre'] / 2.0,
                'circularity': 1.0, 'entity_type': 'STEP',
                'profondeur': t['profondeur'],
                'traversant': t['traversant'],
                # où le trou commence sous le dessus (épaulement)
                'pz_depart': t.get('pz_depart', 0.0),
                'fraisure': t.get('fraisure'),
            } for t in trous]
        # son onglet: ses entités et ses centres savent d'où ils viennent
        cles = {i['cle'] for i in self._imports_dxf}
        etape = _piece_3d(filepath)
        image = str(filepath).lower().endswith(_ti.SUFFIXES)
        prefixe = 'step' if etape else ('img' if image else 'vec')
        k = 1
        while f"{prefixe}{k}" in cles:
            k += 1
        cle_import = f"{prefixe}{k}"
        for item in self._dxf_items:
            if id(item) not in deja:
                self._item_source[id(item)] = cle_import
        connus = {(round(c.get('x', 0), 3), round(c.get('y', 0), 3))
                  for c in cercles_avant}
        # (la détection a vidé la liste: elle ne tient que ce fichier)
        nouveaux = [c for c in self._detected_circles
                    if (round(c.get('x', 0), 3), round(c.get('y', 0), 3))
                    not in connus]
        self._detected_circles = cercles_avant + nouveaux
        entree = {
            'cle': cle_import, 'nom': _os.path.basename(str(filepath)),
            'chemin': str(filepath), 'visible': True,
            'genre': 'step' if etape else ('image' if image else 'vecteur'),
            'cercles': nouveaux}
        if reglages is not None:
            entree['reglages'] = (_dc.asdict(reglages)
                                  if _dc.is_dataclass(reglages)
                                  else dict(reglages))
        if source_piece is not None:
            entree['source_3d'] = source_piece
        self._imports_dxf.append(entree)
        self._extend_scene_rect()
        self.fit_all()
        self.circles_detected.emit(self._detected_circles)
        self.entity_info.emit(rapport.summary())
        return rapport

    @staticmethod
    def _chemin_vecteur(trace) -> QPainterPath:
        """Un tracé du noyau vectoriel en chemin Qt.

        Le noyau rend des `Chemin`: ils gardent leurs courbes, et Qt
        sait les dessiner telles quelles. Un PDF ou un SVG importé
        est alors aussi net qu'un DXF — pas de facettes au zoom."""
        out = QPainterPath()
        commandes = getattr(trace, 'commandes', None)
        if not commandes:
            points = list(trace)
            if len(points) < 2:
                return out
            out.moveTo(points[0][0], -points[0][1])
            for x, y in points[1:]:
                out.lineTo(x, -y)
            return out
        for commande in commandes:
            nom = commande[0]
            if nom == 'M':
                out.moveTo(commande[1], -commande[2])
            elif nom == 'L':
                out.lineTo(commande[1], -commande[2])
            elif nom == 'C':
                out.cubicTo(commande[1], -commande[2],
                            commande[3], -commande[4],
                            commande[5], -commande[6])
            elif nom == 'Z':
                out.closeSubpath()
        return out

    def _detecter_depuis_polylignes(self, polylignes: list) -> None:
        """Centres et rectangles d'un dessin sans entités.

        Un PDF ou un SVG ne dit pas « ceci est un cercle »: il donne
        des tracés. On les mesure — c'est la même mesure que sur une
        polyligne DXF aplatie."""
        self._detected_circles.clear()
        for points in polylignes:
            if len(points) < 8:
                continue
            ferme = (abs(points[0][0] - points[-1][0]) < 1e-6
                     and abs(points[0][1] - points[-1][1]) < 1e-6)
            sommets = points[:-1] if ferme else points
            if len(sommets) < 8:
                continue
            cx, cy, rayon = _least_squares_circle(sommets)
            if not rayon or rayon <= 0:
                continue
            perim = sum(
                math.dist(sommets[i], sommets[i - 1])
                for i in range(len(sommets)))
            n = len(sommets)
            aire = abs(sum(
                sommets[i][0] * sommets[(i + 1) % n][1]
                - sommets[(i + 1) % n][0] * sommets[i][1]
                for i in range(n))) / 2
            if perim <= 0 or aire <= 0:
                continue
            circularite = min(4 * math.pi * aire / (perim ** 2), 1.0)
            # Une petite poche à coins arrondis a une « rondeur » de
            # 0,9 et plus: elle passait pour un trou, et « Générer » y
            # proposait un perçage. Un VRAI cercle a tous ses points à
            # son rayon (aux cordes près); un rectangle arrondi non.
            ecart = max(abs(math.hypot(px - cx, py - cy) - rayon)
                        for px, py in sommets) / rayon
            if ecart > 0.03 or self.rectangle_arrondi(sommets) is not None:
                continue
            self._detected_circles.append({
                'x': cx, 'y': cy, 'radius': rayon,
                'circularity': circularite,
                'entity_type': 'POLYLIGNE',
            })

    # ── Annotations ──

    #: pas de déplacement proposés aux flèches, en mm (échelle
    #: reprise de TauDrive)
    NUDGE_STEPS = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0,
                   25.0)
    NUDGE_DEFAULT = 1.0

    def entite_sous(self, x: float, y: float):
        """L'entité dessinée sous ce point, en coordonnées DXF.

        Sert à savoir à QUI appartient une annotation qu'on pose."""
        from PySide6.QtCore import QPointF as _QPointF
        connus = {id(i) for i in self._dxf_items}
        for item in self._scene.items(_QPointF(x, -y)):
            if id(item) not in connus or not item.isVisible():
                continue
            if self._item_layer.get(id(item)) in ('drawn', 'dxf',
                                                  'smb'):
                return item
        return None

    def add_text(self, texte: str, x: float = 0.0, y: float = 0.0,
                 hauteur: float = 5.0, couleur: str = "#a6e3a1",
                 attache_a=None):
        """Pose une annotation sur le dessin, déplaçable.

        Un plan qui part à l'atelier porte des repères — « face A »,
        « brut 100×20 », une cote rappelée. Ils vivent sur leur propre
        calque: on choisit de les exporter ou non.

        `attache_a`: l'entité que ce repère désigne. L'annotation la
        suit alors dans ses déplacements et s'efface avec elle."""
        from PySide6.QtGui import QFont, QFontMetricsF
        texte = str(texte or "").strip()
        if not texte:
            return None
        item = self._scene.addText(texte)
        police = QFont()
        police.setPointSizeF(10.0)
        item.setFont(police)
        item.setDefaultTextColor(QColor(couleur))
        # Mise à l'échelle: la police est en points, la scène en mm
        metrique = QFontMetricsF(police)
        hauteur_px = max(1.0, metrique.height())
        facteur = float(hauteur) / hauteur_px
        item.setScale(facteur)
        item.setPos(x, -y)
        item.setFlag(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        item.setFlag(
            QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        item.setData(1, 'annotation')
        item.setData(2, texte)
        item.setData(3, float(hauteur))
        self._register_item(item, 'texte')
        if attache_a is not None:
            self.attacher(attache_a, item)
        self._extend_scene_rect()
        return item

    #: hauteur de référence pour mesurer une police, en points
    _POLICE_REFERENCE = 200.0

    @classmethod
    def chemin_texte(cls, texte: str, police, hauteur: float
                     ) -> QPainterPath:
        """Contours d'un texte, mis à la hauteur de CAPITALE voulue.

        La taille d'une police est en points et ne dit rien de la
        hauteur des lettres: deux polices de même corps ne gravent
        pas la même hauteur. On mesure donc un « H » et on met à
        l'échelle — la cote demandée est celle qu'on obtient."""
        from PySide6.QtGui import QFont
        mesure = QFont(police)
        mesure.setPointSizeF(cls._POLICE_REFERENCE)
        reference = QPainterPath()
        reference.addText(0.0, 0.0, mesure, "H")
        hauteur_h = reference.boundingRect().height()
        if hauteur_h <= 0:
            return QPainterPath()
        brut = QPainterPath()
        brut.addText(0.0, 0.0, mesure, str(texte))
        if brut.isEmpty():
            return QPainterPath()
        facteur = float(hauteur) / hauteur_h
        from PySide6.QtGui import QTransform
        return QTransform.fromScale(facteur, facteur).map(brut)

    @staticmethod
    def nom_de_calque(texte: str) -> str:
        """Un nom de calque DXF propre (lettres, chiffres, _ -)."""
        import re
        nom = re.sub(r"[^0-9A-Za-z_\-]+", "_", str(texte or "")).strip("_")
        return (nom or "CALQUE")[:60].upper()

    def poser_polylignes(self, polylignes, calque: str,
                         couleur: str = "#fab387") -> Optional[object]:
        """Des polylignes OUVERTES (coordonnées machine) posées sur le
        calque Dessin, en une entité, exportées sur le calque DXF
        `calque` — le trajet d'un outil, par exemple."""
        chemin = QPainterPath()
        for pl in polylignes or []:
            if len(pl) < 2:
                continue
            chemin.moveTo(pl[0][0], -pl[0][1])
            for px, py in pl[1:]:
                chemin.lineTo(px, -py)
        if chemin.isEmpty():
            return None
        item = self._scene.addPath(chemin, QPen(QColor(couleur), 0.15))
        item.setData(1, 'parcours_dessine')
        item.setData(2, calque)
        item.setData(4, self.nom_de_calque(calque))
        centre = chemin.boundingRect().center()
        self._poser_entite_dessinee(item, centre.x(), centre.y(), 0, calque)
        self._extend_scene_rect()
        return item

    def entites_depuis_operation(self, op, calque: Optional[str] = None
                                 ) -> int:
        """L'empreinte d'une opération, posée en entités du calque
        Dessin — un rectangle, des cercles, des contours —, et
        sélectionnée: on la déplace, on la met à la cote, on la
        retouche, puis une opération la reprend (« Depuis la
        sélection du canvas », « Appliquer les courbes »). Rend le
        nombre d'entités posées."""
        import math
        genre = getattr(op, 'operation_type', '')
        params = getattr(op, 'params', {}) or {}
        poses = []

        def _arrondi(cx, cy, w, h, r):
            """Un rectangle à coins arrondis, en polygone."""
            r = max(0.0, min(r, w / 2.0, h / 2.0))
            if r < 1e-6:
                return [(cx - w / 2, cy - h / 2), (cx + w / 2, cy - h / 2),
                        (cx + w / 2, cy + h / 2), (cx - w / 2, cy + h / 2)]
            points = []
            coins = ((cx + w / 2 - r, cy - h / 2 + r, -90.0),
                     (cx + w / 2 - r, cy + h / 2 - r, 0.0),
                     (cx - w / 2 + r, cy + h / 2 - r, 90.0),
                     (cx - w / 2 + r, cy - h / 2 + r, 180.0))
            for ox, oy, depart in coins:
                for k in range(9):
                    a = math.radians(depart + 90.0 * k / 8)
                    points.append((round(ox + r * math.cos(a), 4),
                                   round(oy + r * math.sin(a), 4)))
            return points

        # les contours: gravures, contours, texte, tête de gamme,
        # ébavurage de contours
        contours = []
        try:
            from src.operations.registry import OperationRegistry
            classe = OperationRegistry.get(genre)
            if genre == "ebavurage":
                from src.operations.ebavurage import Ebavurage
                if Ebavurage.forme(params) == "Contours":
                    contours = Ebavurage.anneaux(params)
            elif hasattr(classe, 'contours') and genre not in (
                    "trace",):
                contours = classe.contours(params)
        except Exception:
            contours = []
        if contours:
            item = self.add_contours(contours, etiquette=op.name)
            if item is not None:
                poses.append(item)
        else:
            points = list(getattr(op, 'points', None) or []) or [
                {'x': getattr(op, 'x', 0.0), 'y': getattr(op, 'y', 0.0)}]
            for pt in points:
                forme = self._op_shape(op, pt)
                if not forme:
                    continue
                for px, py in self._op_positions(op, pt):
                    if forme[0] == 'rect':
                        _k, w, h = forme[:3]
                        rayon = forme[3] if len(forme) > 3 else 0.0
                        if rayon > 1e-6:
                            item = self.add_contours(
                                [_arrondi(px, py, w, h, rayon)],
                                etiquette=op.name)
                        else:
                            self.draw_shape_from_params("rect", px, py,
                                                        w, h)
                            item = self._dxf_items[-1]
                    else:
                        self.draw_shape_from_params("circle", px, py,
                                                    diameter=forme[1])
                        item = self._dxf_items[-1]
                    if item is not None:
                        poses.append(item)
        if not poses:
            return 0
        if calque:
            # le calque DXF de l'empreinte (export)
            for item in poses:
                try:
                    item.setData(4, self.nom_de_calque(calque))
                except RuntimeError:
                    pass
        self._scene.clearSelection()
        self._selected_items = []
        for item in poses:
            try:
                item.setSelected(True)
            except RuntimeError:
                pass
        self.selection_changed.emit(len(self.selection_courante()))
        self._extend_scene_rect()
        return len(poses)

    def add_contours(self, contours, etiquette: str = "TEXTE"):
        """Pose des contours (coordonnées machine, Y vers le haut) sur
        le calque Dessin, en UNE entité: un texte vectorisé par une
        opération vient ainsi au canvas — pour l'export DXF, ou pour
        le manipuler avec le reste du dessin."""
        chemin = QPainterPath()
        for contour in contours or []:
            if len(contour) < 3:
                continue
            chemin.moveTo(contour[0][0], -contour[0][1])
            for px, py in contour[1:]:
                chemin.lineTo(px, -py)
            chemin.closeSubpath()
        if chemin.isEmpty():
            return None
        item = self._scene.addPath(chemin, QPen(QColor("#f9e2af"), 0.2))
        item.setData(1, 'texte_vectoriel')
        item.setData(2, etiquette)
        centre = chemin.boundingRect().center()
        self._poser_entite_dessinee(item, centre.x(), centre.y(),
                                    0, etiquette)
        self._extend_scene_rect()
        return item

    def add_texte_vectorise(self, texte: str, x: float = 0.0,
                            y: float = 0.0, police=None,
                            hauteur: float = 5.0,
                            alignement: str = "Gauche"):
        """Pose un texte en CONTOURS sur le calque Dessin.

        Ce n'est pas une annotation: ce sont des tracés comme ceux
        d'un DXF, qui se sélectionnent, se déplacent et se gravent.
        La vectorisation est faite ici, sans étape à demander."""
        from PySide6.QtGui import QFont
        texte = str(texte or "").strip()
        if not texte:
            return None
        police = police if police is not None else QFont()
        chemin = self.chemin_texte(texte, police, hauteur)
        if chemin.isEmpty():
            return None
        rect = chemin.boundingRect()
        dx = -rect.left()
        if alignement == "Centre":
            dx = -rect.center().x()
        elif alignement == "Droite":
            dx = -rect.right()
        from PySide6.QtGui import QTransform
        # La scène a Y vers le bas, comme le repère des polices: le
        # texte est déjà à l'endroit, il ne reste qu'à le poser
        chemin = QTransform.fromTranslate(x + dx, -y).map(chemin)
        item = self._scene.addPath(chemin,
                                   QPen(QColor("#f9e2af"), 0.2))
        item.setData(1, 'texte_vectoriel')
        item.setData(2, texte)
        centre = chemin.boundingRect().center()
        self._poser_entite_dessinee(item, centre.x(), centre.y(),
                                    0, "TEXTE")
        self._extend_scene_rect()
        return item

    def clear_all(self) -> int:
        """Vide le canvas: dessin, annotations, opérations, brut.

        Ne touche ni à la grille ni au repère d'origine — ce sont les
        repères de travail, pas du contenu."""
        n = len(self._dxf_items)
        self.clear_dxf()
        self.clear_operation_points()
        self.clear_workpiece()
        self._detected_circles.clear()
        self.circles_detected.emit([])
        self.entity_info.emit("Canvas vidé")
        return n

    def annotations(self) -> list:
        """Items d'annotation posés sur le dessin."""
        return [i for i in self._dxf_items
                if self._item_layer.get(id(i)) == 'texte']

    def nudge_step(self) -> float:
        return getattr(self, '_nudge_step', self.NUDGE_DEFAULT)

    def set_nudge_step(self, valeur: float) -> float:
        """Pas des flèches, en mm. Retenu pour la session."""
        self._nudge_step = max(0.001, float(valeur))
        self.nudge_step_changed.emit(self._nudge_step)
        return self._nudge_step

    def cycle_nudge_step(self, sens: int) -> float:
        """Pas suivant ou précédent de l'échelle proposée."""
        courant = self.nudge_step()
        proche = min(range(len(self.NUDGE_STEPS)),
                     key=lambda i: abs(self.NUDGE_STEPS[i] - courant))
        index = min(max(proche + sens, 0), len(self.NUDGE_STEPS) - 1)
        return self.set_nudge_step(self.NUDGE_STEPS[index])

    def selection_courante(self) -> list:
        """Ce qui est sélectionné, des deux façons possibles.

        Les entités importées le sont par la liste maison
        `_selected_items` (surlignage au pinceau), les annotations par
        Qt. Les flèches doivent déplacer les unes comme les autres.

        Un membre de GROUPE amène tout son groupe: c'est ce qu'on
        attend d'un groupe, et ça vaut pour le déplacement, la mise à
        la cote, la copie et la suppression."""
        items = []
        vus = set()

        def _ajouter(item):
            try:
                if item.scene() is None:
                    return           # déjà retiré de la scène
            except RuntimeError:
                return               # objet C++ détruit
            if id(item) in vus:
                return
            vus.add(id(item))
            items.append(item)

        for item in list(self._selected_items):
            _ajouter(item)
        for item in self._scene.selectedItems():
            _ajouter(item)
        for item in list(items):
            cle = self._groupe_de.get(id(item))
            for membre in self._groupes.get(cle, ()) if cle else ():
                _ajouter(membre)
        return items

    # ──── Couper / copier / coller ────

    #: presse-papiers COMMUN à tous les canvas: c'est ce qui permet
    #: de porter un dessin d'un onglet à l'autre. Chaque entrée est
    #: une description autonome — pas un item Qt, qui appartient à
    #: la scène d'où il vient.
    _PRESSE_PAPIERS: List[Dict] = []
    #: quel canvas a rempli le presse-papiers (pour savoir s'il faut
    #: décaler la copie ou la poser à la même place)
    _SOURCE_COPIE = None

    def _decrire_pour_copie(self, item) -> Optional[Dict]:
        """Une entité en description autonome, en coordonnées scène."""
        calque = self._item_layer.get(id(item))
        if calque is None:
            return None
        if isinstance(item, QGraphicsTextItem):
            return {'genre': 'texte', 'calque': calque,
                    'texte': str(item.data(2) or item.toPlainText()),
                    'hauteur': float(item.data(3) or 5.0),
                    'x': item.pos().x(), 'y': item.pos().y(),
                    'couleur': item.defaultTextColor().name()}
        chemin = QPainterPath()
        try:
            if isinstance(item, QGraphicsPathItem):
                chemin = item.path()
            elif isinstance(item, QGraphicsEllipseItem):
                chemin.addEllipse(item.rect())
            elif isinstance(item, QGraphicsRectItem):
                chemin.addRect(item.rect())
            elif isinstance(item, QGraphicsLineItem):
                ligne = item.line()
                chemin.moveTo(ligne.p1())
                chemin.lineTo(ligne.p2())
            else:
                return None
            chemin = item.mapToScene(chemin)
            couleur = item.pen().color().name()
        except RuntimeError:
            return None
        if chemin.isEmpty():
            return None
        return {'genre': 'chemin', 'calque': calque,
                'chemin': chemin, 'couleur': couleur}

    def copier_selection(self) -> int:
        """Met la sélection au presse-papiers. Rend le compte."""
        entrees = []
        for item in self.selection_courante():
            decrit = self._decrire_pour_copie(item)
            if decrit is not None:
                entrees.append(decrit)
        if not entrees:
            return 0
        DxfCanvas._PRESSE_PAPIERS = entrees
        DxfCanvas._SOURCE_COPIE = self
        self.entity_info.emit(
            f"{len(entrees)} entité(s) copiée(s) — Ctrl+V, ici ou "
            f"dans un autre onglet")
        return len(entrees)

    def couper_selection(self) -> int:
        """Copie puis supprime. Ctrl+Z rend la suppression."""
        n = self.copier_selection()
        if n:
            self._delete_selected()
        return n

    def coller(self, decalage: float = None) -> int:
        """Pose le presse-papiers dans CE canvas.

        Collé dans un autre onglet, le dessin garde ses coordonnées:
        c'est la même pièce. Collé au même endroit, il est décalé
        d'un pas, sans quoi la copie serait invisible sous
        l'original."""
        entrees = DxfCanvas._PRESSE_PAPIERS
        if not entrees:
            return 0
        if decalage is None:
            decalage = (self.nudge_step()
                        if DxfCanvas._SOURCE_COPIE is self else 0.0)
        from PySide6.QtGui import QTransform
        self.clear_selection()
        poses = []
        for entree in entrees:
            calque = entree.get('calque', 'drawn')
            if entree['genre'] == 'texte':
                item = self.add_text(
                    entree['texte'],
                    entree['x'] + decalage,
                    -(entree['y'] + decalage),
                    hauteur=entree['hauteur'],
                    couleur=entree.get('couleur', "#a6e3a1"))
                if item is not None:
                    poses.append(item)
                continue
            chemin = QTransform.fromTranslate(
                decalage, -decalage).map(entree['chemin'])
            item = self._scene.addPath(
                chemin, QPen(QColor(entree.get('couleur', "#f9e2af")),
                             0.2))
            if calque == 'drawn':
                centre = chemin.boundingRect().center()
                self._poser_entite_dessinee(
                    item, centre.x(), centre.y(), 0, "COPIE",
                    annuler=False)
            else:
                self._register_item(item, calque)
            poses.append(item)
        if not poses:
            return 0
        # La copie est SÉLECTIONNÉE: on la place tout de suite
        self._scene.clearSelection()
        self._selected_items = []
        for item in poses:
            self._surligner(item)
        self._extend_scene_rect()
        self.selection_changed.emit(len(self.selection_courante()))
        self.entity_info.emit(f"{len(poses)} entité(s) collée(s)")
        from src.gui.dxf.canvas_undo import AjouterCommande
        self._pile_undo.push(AjouterCommande(self, poses, "Coller"))
        return len(poses)

    # ──── Groupes de tracés ────

    def grouper_selection(self) -> int:
        """Réunit la sélection en un groupe. Rend le nombre d'entités.

        Un dessin importé arrive en dizaines de polylignes: sans
        groupe, le déplacer demande de toutes les reprendre, et une
        seule oubliée reste en arrière."""
        import uuid
        membres = [i for i in self.selection_courante()
                   if id(i) in self._item_layer]
        if len(membres) < 2:
            return 0
        # Un groupe qui en absorbe un autre reprend tous ses membres
        anciens = {self._groupe_de.get(id(i)) for i in membres}
        for cle in anciens:
            if cle:
                for membre in self._groupes.pop(cle, []):
                    if id(membre) not in {id(m) for m in membres}:
                        membres.append(membre)
                    self._groupe_de.pop(id(membre), None)
        cle = uuid.uuid4().hex[:8]
        self._groupes[cle] = membres
        for membre in membres:
            self._groupe_de[id(membre)] = cle
        self.entity_info.emit(
            f"{len(membres)} entités groupées — elles se déplacent "
            f"ensemble")
        return len(membres)

    def degrouper_selection(self) -> int:
        """Défait les groupes de la sélection. Rend leur nombre."""
        cles = {self._groupe_de.get(id(i))
                for i in self.selection_courante()}
        cles.discard(None)
        for cle in cles:
            for membre in self._groupes.pop(cle, []):
                self._groupe_de.pop(id(membre), None)
        if cles:
            self.entity_info.emit(f"{len(cles)} groupe(s) défait(s)")
        return len(cles)

    def groupe_de(self, item) -> str:
        """Clé du groupe d'une entité, vide si elle est seule."""
        return self._groupe_de.get(id(item), "")

    def _oublier_les_fantomes(self) -> int:
        """Retire du registre ce qui n'est plus dans la scene.

        Une entite retiree ailleurs (undo partiel, nettoyage) restait
        comptee: elle ressortait dans les exports et la legende sans
        se voir nulle part. Rend le nombre d'entites oubliees."""
        fantomes = []
        for item in list(self._dxf_items):
            try:
                vivant = item.scene() is not None
            except RuntimeError:
                vivant = False
            if not vivant:
                fantomes.append(item)
        for item in fantomes:
            self._dxf_items.remove(item)
            self._item_layer.pop(id(item), None)
            self._item_metadata.pop(id(item), None)
            self._attaches.pop(id(item), None)
            self._oublier_des_groupes(item)
            if item in self._selected_items:
                self._selected_items.remove(item)
        return len(fantomes)

    def _oublier_des_groupes(self, item) -> None:
        """Retire une entité de son groupe (suppression, effacement).

        Un groupe qui tombe à un seul membre n'en est plus un."""
        cle = self._groupe_de.pop(id(item), None)
        if not cle:
            return
        membres = [m for m in self._groupes.get(cle, [])
                   if id(m) != id(item)]
        if len(membres) < 2:
            for membre in membres:
                self._groupe_de.pop(id(membre), None)
            self._groupes.pop(cle, None)
        else:
            self._groupes[cle] = membres

    def dupliquer_selection(self, decalage: float = None) -> int:
        """Copie la sélection, décalée d'un pas pour qu'on la voie.

        Ne duplique que ce qui a une géométrie propre: un tracé, une
        forme, une annotation."""
        from PySide6.QtGui import QPen as _QPen
        pas = self.nudge_step() if decalage is None else float(decalage)
        copies = []
        for item in self.selection_courante():
            copie = None
            try:
                if isinstance(item, QGraphicsPathItem):
                    copie = self._scene.addPath(
                        QPainterPath(item.path()), _QPen(item.pen()))
                elif isinstance(item, QGraphicsEllipseItem):
                    copie = self._scene.addEllipse(
                        item.rect(), _QPen(item.pen()))
                elif isinstance(item, QGraphicsRectItem):
                    copie = self._scene.addRect(
                        item.rect(), _QPen(item.pen()))
                elif isinstance(item, QGraphicsLineItem):
                    copie = self._scene.addLine(
                        item.line(), _QPen(item.pen()))
                elif isinstance(item, QGraphicsTextItem):
                    copie = self.add_text(
                        str(item.data(2) or item.toPlainText()),
                        item.pos().x() + pas, -item.pos().y() - pas,
                        hauteur=float(item.data(3) or 5.0))
                    copies.append(copie)
                    continue
            except (RuntimeError, TypeError):
                continue
            if copie is None:
                continue
            copie.setPos(item.pos().x() + pas, item.pos().y() + pas)
            copie.setFlag(
                QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
            copie.setFlag(
                QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
            self._register_item(
                copie, self._item_layer.get(id(item), 'drawn'))
            copies.append(copie)
        if copies:
            self._scene.clearSelection()
            self._selected_items = []
            for copie in copies:
                if copie is not None:
                    copie.setSelected(True)
            self._extend_scene_rect()
        return len(copies)

    def emprise_de(self, items) -> Optional[QRectF]:
        """Le rectangle qui contient ces entités (visibles), en
        coordonnées de scène — None s'il n'y en a aucune."""
        emprise = None
        for item in items:
            try:
                if not item.isVisible():
                    continue
                r = item.sceneBoundingRect()
            except RuntimeError:
                continue
            emprise = r if emprise is None else emprise.united(r)
        return emprise

    def emprise_dessin(self) -> Optional[QRectF]:
        """Le rectangle qui contient tout le dessin, en coordonnées
        de scène — None s'il n'y a rien."""
        return self.emprise_de(self._dxf_items)

    def centre_dessin(self, reference=None) -> Optional[Tuple[float,
                                                               float]]:
        """Le centre du dessin — ou des entités `reference` —, en
        coordonnées MACHINE (Y vers le haut), ou None."""
        emprise = (self.emprise_de(reference) if reference
                   else self.emprise_dessin())
        if emprise is None:
            return None
        return (emprise.center().x(), -emprise.center().y())

    def centrer_dessin(self, reference=None) -> Tuple[float, float]:
        """Ramène le centre du dessin en (0, 0).

        Un DXF de client arrive où son auteur l'a laissé — parfois
        à des centaines de millimètres de l'origine. Tout se déplace: entités, centres détectés,
        annotations. Rend le déplacement appliqué, en machine.

        `reference`: les entités dont le centre doit venir en 0 —
        la sélection, sans le ® du coin. Le ® se déplace avec le
        reste: il reste dans le dessin, à sa place."""
        centre = self.centre_dessin(reference)
        if centre is None:
            return (0.0, 0.0)
        dx, dy = -centre[0], -centre[1]
        self.deplacer_items(list(self._dxf_items), dx, -dy)
        try:
            self._scene.update()
        except RuntimeError:
            pass
        return (dx, dy)

    def centrer_sur_selection(self) -> Tuple[Tuple[float, float], int]:
        """Le centre de la SÉLECTION vient en (0, 0), tout le dessin
        suit. Sans sélection: le dessin entier. Rend (déplacement,
        nombre d'entités de référence)."""
        items = self.selection_courante()
        return self.centrer_dessin(items or None), len(items)

    def amener_selection_en_zero(self) -> Tuple[Tuple[float, float], int]:
        """Alt+W: le centre de la SÉLECTION vient en (0, 0) — elle
        seule se déplace, le reste du dessin garde sa place (novembre
        2026, RomDuch: « Alt+W ne concerne que l'ensemble
        sélectionné »: un deuxième dessin importé se centre sans
        emmener le premier). Un membre de groupe amène son groupe.
        Annulable (Ctrl+Z). Sans sélection: rien ne bouge.

        Rend (déplacement en machine, nombre d'entités déplacées)."""
        items = self.selection_courante()
        centre = self.centre_dessin(items) if items else None
        if centre is None:
            return (0.0, 0.0), 0
        dx, dy = -centre[0], -centre[1]
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            return (0.0, 0.0), len(items)
        n = self.deplacer_items(items, dx, -dy)
        if n:
            from src.gui.dxf.canvas_undo import DeplacerCommande
            self._pile_undo.push(DeplacerCommande(self, items, dx, -dy))
            try:
                self._scene.update()
            except RuntimeError:
                pass
        return (dx, dy), n

    def miroir_selection(self, axe: str = 'vertical') -> int:
        """Retourne la sélection en miroir, sur place.

        On grave souvent le miroir du dessin: un tampon imprime à
        l'envers. `axe` est la LIGNE de symétrie —
        'vertical' échange gauche et droite, 'horizontal' haut et
        bas, 'les deux' retourne (demi-tour). Le miroir se fait
        autour du centre de la sélection: elle ne bouge pas de
        place. Rend le nombre d'entités retournées."""
        items = self.selection_courante()
        if not items:
            return 0
        emprise = self.emprise_de(items)
        if emprise is None:
            return 0
        centre = emprise.center()
        fx = -1.0 if axe in ('vertical', 'les deux') else 1.0
        fy = -1.0 if axe in ('horizontal', 'les deux') else 1.0
        n = 0
        for item in items:
            try:
                local = item.mapFromScene(centre)
                matrice = QTransform()
                matrice.translate(local.x(), local.y())
                matrice.scale(fx, fy)
                matrice.translate(-local.x(), -local.y())
                item.setTransform(matrice, True)
            except RuntimeError:
                continue
            n += 1
            # le centre détecté de l'entité suit (en machine, Y
            # vers le haut)
            marque = self._item_metadata.get(id(item))
            if marque is not None:
                if fx < 0:
                    marque['x'] = 2.0 * centre.x() - marque['x']
                if fy < 0:
                    marque['y'] = 2.0 * (-centre.y()) - marque['y']
        if n:
            try:
                self._scene.update()
            except RuntimeError:
                pass
            if self._detected_circles:
                self.circles_detected.emit(self._detected_circles)
        return n

    def tourner_items(self, items, angle: float, centre=None) -> int:
        """Tourne des entités de `angle` degrés (sens trigonométrique,
        Y machine vers le haut) autour de `centre` (un point de la
        scène) — par défaut le centre de leur emprise: l'ensemble
        tourne sur lui-même. Les centres détectés suivent. Rend le
        nombre d'entités tournées."""
        import math
        items = list(items or [])
        if not items or abs(float(angle)) < 1e-12:
            return 0
        if centre is None:
            emprise = self.emprise_de(items)
            if emprise is None:
                return 0
            centre = emprise.center()
        a = math.radians(float(angle))
        cx, cy = centre.x(), -centre.y()
        n = 0
        for item in items:
            try:
                local = item.mapFromScene(centre)
                matrice = QTransform()
                matrice.translate(local.x(), local.y())
                # la scène a Y vers le bas: le sens trigonométrique y
                # est un angle négatif
                matrice.rotate(-float(angle))
                matrice.translate(-local.x(), -local.y())
                item.setTransform(matrice, True)
            except RuntimeError:
                continue
            n += 1
            marque = self._item_metadata.get(id(item))
            if marque is not None and 'x' in marque and 'y' in marque:
                x, y = marque['x'] - cx, marque['y'] - cy
                marque['x'] = cx + x * math.cos(a) - y * math.sin(a)
                marque['y'] = cy + x * math.sin(a) + y * math.cos(a)
        if n:
            try:
                self._scene.update()
            except RuntimeError:
                pass
            if self._detected_circles:
                self.circles_detected.emit(self._detected_circles)
        return n

    def deplacer_selection(self, dx: float, dy: float) -> int:
        """Déplace la sélection. Retourne le nombre d'items déplacés.

        `setPos` déplace n'importe quel item, qu'il soit marqué
        déplaçable ou non: le drapeau ne concerne que la souris.
        Le geste est annulable (Ctrl+Z sur le dessin)."""
        items = self.selection_courante()
        if not items:
            return 0
        n = self.deplacer_items(items, dx, -dy)
        if n:
            from src.gui.dxf.canvas_undo import DeplacerCommande
            self._pile_undo.push(DeplacerCommande(self, items, dx, -dy))
        return n

    def get_detected_circles(self) -> List[Dict]:
        """Retourne la liste des cercles détectés."""
        return self._detected_circles.copy()

    def get_centers_by_circularity(self, threshold_pct: float = 50.0) -> List[Dict]:
        """Filtre les centres par score de circularité (0-100%)."""
        threshold = threshold_pct / 100.0
        return [
            c for c in self._detected_circles
            if c.get('circularity', 0) >= threshold
        ]

    def get_circles_by_diameter(self, target_diameter: float,
                                 tolerance_pct: float = 10.0
                                 ) -> List[Dict]:
        """Filtre les cercles par diamètre avec tolérance en %."""
        target_radius = target_diameter / 2.0
        tol = target_radius * tolerance_pct / 100.0
        return [
            c for c in self._detected_circles
            if abs(c['radius'] - target_radius) <= tol
        ]

    # ──── Sélection d'entités ────

    def set_snap_enabled(self, enabled: bool):
        """Active/désactive le snap."""
        self._snap_enabled = enabled

    def set_grid_visible(self, visible: bool):
        """Affiche/masque la grille."""
        self._grid_visible = visible
        # Redessiner la grille
        for item in self._grid_items:
            item.setVisible(visible)
        self.viewport().update()

    def set_select_mode(self, enabled: bool):
        """Active/désactive le mode sélection d'entités."""
        self._select_mode = enabled
        if enabled:
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif not self._pick_mode and not self._draw_tool:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        if not enabled:
            self.clear_selection()

    def clear_selection(self):
        """Désélectionne tout, quel que soit le chemin par lequel
        l'entité a été prise.

        Les pinceaux d'origine sont rendus même si l'item a été
        retiré de la scène entre-temps: une exception ici laissait
        la moitié du dessin en surbrillance, sans moyen d'en sortir."""
        for item in list(self._selected_items):
            iid = id(item)
            if iid not in self._original_pens:
                continue
            try:
                if isinstance(item, (QGraphicsLineItem,
                                     QGraphicsEllipseItem,
                                     QGraphicsRectItem,
                                     QGraphicsPathItem)):
                    item.setPen(self._original_pens[iid])
            except RuntimeError:
                continue
        self._selected_items.clear()
        self._original_pens.clear()
        # Le rectangle prend aussi ce qui porte la sélection de Qt
        # (annotations, tracés dessinés): la vider ici également
        self._scene.clearSelection()
        self.selection_changed.emit(0)

    def get_selected_centers(self) -> List[Dict]:
        """Retourne les centres des entités sélectionnées."""
        centers = []
        for item in self._selected_items:
            meta = self._item_metadata.get(id(item))
            if meta:
                centers.append(meta)
            else:
                # Fallback: centre du bounding rect
                rect = item.sceneBoundingRect()
                centers.append({
                    'x': rect.center().x(),
                    'y': -rect.center().y(),
                    'radius': max(rect.width(), rect.height()) / 2,
                    'circularity': 0.0,
                    'entity_type': 'UNKNOWN'
                })
        return centers

    # ──── Vue et navigation ────

    def fit_all(self):
        """Ajuste la vue. Le brut commande le cadrage quand il est
        déclaré: c'est la pièce qu'on veut retrouver d'un clic, pas
        l'étendue d'un DXF qui peut déborder très loin."""
        # Les items fraîchement créés ont des pinceaux en unités de
        # scène: les rendre cosmétiques ici couvre tous les imports
        self.set_line_width_px(getattr(self, '_line_width_px', 1.0))
        if self._workpiece_rect is not None:
            rect = QRectF(self._workpiece_rect)
            margin = max(rect.width(), rect.height()) * 0.08 + 2
            rect.adjust(-margin, -margin, margin, margin)
            self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
            self._zoom = self.transform().m11()
        elif self._dxf_items:
            rect = QRectF()
            for item in self._dxf_items:
                rect = rect.united(item.sceneBoundingRect())
            # Marge proportionnelle
            margin = max(rect.width(), rect.height()) * 0.15 + 5
            rect.adjust(-margin, -margin, margin, margin)
            self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
            self._zoom = self.transform().m11()
        else:
            # Pas d'items: centrer sur l'origine
            rect = QRectF(-50, -50, 100, 100)
            self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
            self._zoom = self.transform().m11()

    def set_pick_mode(self, enabled: bool):
        self._pick_mode = enabled
        if enabled:
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def outil_en_cours(self) -> bool:
        """Un outil tient-il la souris (dessin, règle, outil à clic,
        cote, pipette, symbole à poser)?"""
        return bool(self._draw_tool or self._pick_mode
                    or getattr(self, '_placement_ghost', None) is not None
                    or getattr(self, '_placing_symbol_path', None))

    def quitter_outil(self) -> None:
        """Lâche l'outil en cours, le tracé commencé avec, et rend la
        sélection (clic droit; le panneau décoche ses boutons)."""
        self.cancel_symbol_placement()
        self.set_draw_tool(None)
        self.set_pick_mode(False)
        self._choix_contrainte = []
        self.set_select_mode(True)

    def set_draw_tool(self, tool: Optional[str]):
        self._draw_tool = tool
        self._draw_points.clear()
        if self._temp_item:
            self._scene.removeItem(self._temp_item)
            self._temp_item = None
        if tool:
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif not self._pick_mode:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_show_all_operations(self, show: bool):
        """Affiche/masque les marqueurs d'opération sur le canvas.
        (Les marqueurs de centres détectés ont leur propre toggle.)"""
        self._show_all_ops = show
        for item in self._op_point_items:
            item.setVisible(show)
        self.update()

    def annotations_op_visibles(self, op_id) -> bool:
        """Les annotations (étiquettes + ligne de légende) de cette
        opération sont-elles montrées ?"""
        return op_id not in self._annot_masquees

    def set_annotations_op_visible(self, op_id, visible: bool) -> bool:
        """Montre/masque annotations + ligne de légende d'UNE opé.

        Le tracé étant reconstruit par le panneau (draw_all_operations),
        on ne fait ici que retenir le choix ; rend l'état voulu."""
        if op_id is None:
            return True
        if visible:
            self._annot_masquees.discard(op_id)
        else:
            self._annot_masquees.add(op_id)
        return visible

    def set_op_labels_visible(self, visible: bool):
        """Affiche/masque les ÉTIQUETTES des marqueurs d'opération
        (les croix/cercles restent visibles)."""
        self._op_labels_visible = visible
        for item in self._op_label_items:
            item.setVisible(visible and self._show_all_ops)
        self.update()

    def set_centers_visible(self, visible: bool):
        """Affiche/masque les marqueurs de centres détectés (roses)."""
        self._centers_visible = visible
        for item in self._center_markers:
            item.setVisible(visible)
        self.update()

    def set_ruler_mode(self, enabled: bool):
        """Active/désactive le mode mesure règle."""
        self._ruler_mode = enabled
        self._ruler_points = []
        if enabled:
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif not self._pick_mode and not self._draw_tool:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    # ──── Placement interactif de symbole ────

    def start_symbol_placement(self, filepath: str) -> bool:
        """Démarre le placement interactif d'un symbole: un fantôme
        suit la souris (avec accrochage), clic gauche pour poser,
        Échap pour annuler."""
        try:
            from src.integrations.smb_vector import (
                extract_smb_polylines, extract_smb_texts,
                text_path_in_rect)
            polylines = extract_smb_polylines(filepath)
            texts = extract_smb_texts(filepath)
        except Exception:
            return False
        if not polylines and not texts:
            return False
        self.cancel_symbol_placement()

        group = QGraphicsItemGroup()
        # Le fantôme est posé à la main (addItem): la scène ne passe
        # pas derrière lui rendre ses pinceaux cosmétiques — il
        # épaississait au zoom pendant qu'on cherchait sa place
        ghost_pen = QPen(QColor(148, 226, 213, 130), 1.0)
        ghost_pen.setCosmetic(True)
        for poly in polylines:
            if len(poly) < 2:
                continue
            path = QPainterPath()
            path.moveTo(poly[0][0], -poly[0][1])
            for x, y in poly[1:]:
                path.lineTo(x, -y)
            it = QGraphicsPathItem(path)
            it.setPen(ghost_pen)
            group.addToGroup(it)
        for text, tx0, ty0, tx1, ty1 in texts:
            tp = text_path_in_rect(text, tx0, -ty1,
                                   tx1 - tx0, ty1 - ty0)
            if tp is None:
                continue
            it = QGraphicsPathItem(tp)
            stylo_texte = QPen(QColor(148, 226, 213, 90), 1.0)
            stylo_texte.setCosmetic(True)
            it.setPen(stylo_texte)
            it.setBrush(QBrush(QColor(148, 226, 213, 60)))
            group.addToGroup(it)
        group.setZValue(50)
        self._scene.addItem(group)
        self._placement_ghost = group
        self._placing_symbol_path = filepath
        self.setCursor(Qt.CursorShape.CrossCursor)
        return True

    def cancel_symbol_placement(self):
        """Annule le placement en cours (Échap)."""
        ghost = getattr(self, '_placement_ghost', None)
        if ghost is not None:
            self._scene.removeItem(ghost)
        self._placement_ghost = None
        self._placing_symbol_path = None
        if not self._pick_mode and not self._draw_tool \
                and not self._select_mode:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def _confirm_symbol_placement(self, dxf_x: float, dxf_y: float):
        """Pose le symbole en cours de placement aux coordonnées DXF."""
        fp = getattr(self, '_placing_symbol_path', None)
        if not fp:
            return
        self.cancel_symbol_placement()
        n = self.add_smb_symbol(fp, offset_x=dxf_x, offset_y=dxf_y)
        if n:
            self.entity_info.emit(
                f"Symbole posé à X={dxf_x:.3f} Y={dxf_y:.3f}")

    def add_smb_symbol(self, filepath: str,
                       offset_x: float = 0.0,
                       offset_y: float = 0.0) -> int:
        """Importe un symbole .smb comme entités vectorielles (calque
        'smb'). Les contours circulaires alimentent la détection de
        centres (GenOps). Retourne le nombre de contours importés."""
        try:
            from src.integrations.smb_vector import (
                extract_smb_polylines, extract_smb_texts,
                text_path_in_rect)
            polylines = extract_smb_polylines(filepath)
            texts = extract_smb_texts(filepath)
        except Exception:
            return 0
        if not polylines and not texts:
            return 0

        pen = QPen(QColor("#94e2d5"), 0.2)  # teal: calque symboles
        added = 0
        for poly in polylines:
            if len(poly) < 2:
                continue
            path = QPainterPath()
            path.moveTo(poly[0][0] + offset_x, -(poly[0][1] + offset_y))
            for x, y in poly[1:]:
                path.lineTo(x + offset_x, -(y + offset_y))
            item = self._scene.addPath(path, pen)
            self._register_item(item, 'smb')
            added += 1

            # Contour fermé → fit cercle + score de circularité
            closed = (abs(poly[0][0] - poly[-1][0]) < 1e-6
                      and abs(poly[0][1] - poly[-1][1]) < 1e-6)
            if closed and len(poly) >= 8:
                pts = [(x + offset_x, y + offset_y) for x, y in poly]
                cx, cy, r = _least_squares_circle(pts)
                perim = sum(
                    math.hypot(pts[i][0] - pts[i - 1][0],
                               pts[i][1] - pts[i - 1][1])
                    for i in range(1, len(pts)))
                area = abs(sum(
                    pts[i][0] * pts[(i + 1) % len(pts)][1]
                    - pts[(i + 1) % len(pts)][0] * pts[i][1]
                    for i in range(len(pts)))) / 2
                circ = (min(4 * math.pi * area / (perim ** 2), 1.0)
                        if perim > 0 and area > 0 else 0.0)
                center = {'x': cx, 'y': cy, 'radius': r,
                          'circularity': circ, 'entity_type': 'SMB'}
                self._detected_circles.append(center)
                self._item_metadata[id(item)] = center
                # Marqueur de centre (accrochage + toggle 'Centres')
                if circ > 0.5:
                    mpen = QPen(QColor("#f38ba8"), 0.15)
                    ms = 0.8
                    sx, sy = cx, -cy
                    m1 = self._scene.addLine(
                        sx - ms, sy, sx + ms, sy, mpen)
                    m2 = self._scene.addLine(
                        sx, sy - ms, sx, sy + ms, mpen)
                    m3 = self._scene.addEllipse(
                        sx - ms * 0.6, sy - ms * 0.6,
                        ms * 1.2, ms * 1.2, mpen)
                    for m in (m1, m2, m3):
                        m.setVisible(self._centers_visible)
                    self._center_markers.extend([m1, m2, m3])

        # Entités texte: police Arial vectorisée dans leur bbox
        for text, tx0, ty0, tx1, ty1 in texts:
            path = text_path_in_rect(
                text,
                tx0 + offset_x, -(ty1 + offset_y),
                tx1 - tx0, ty1 - ty0)
            if path is None:
                continue
            item = self._scene.addPath(
                path, QPen(QColor("#94e2d5"), 0.1),
                QBrush(QColor(148, 226, 213, 90)))
            self._register_item(item, 'smb')
            added += 1

        if added:
            self._extend_scene_rect()
            self.circles_detected.emit(self._detected_circles)
        return added

    def draw_shape_from_params(self, shape_type: str, cx: float, cy: float,
                                width: float = 0, height: float = 0,
                                diameter: float = 0):
        """Dessine une forme par centre + dimensions (formulaire)."""
        pen = QPen(QColor("#f9e2af"), 0.2)
        # Coordonnées scène (Y inversé)
        sy = -cy

        if shape_type == "rect" and width > 0 and height > 0:
            item = self._scene.addRect(
                cx - width / 2, sy - height / 2, width, height, pen)
            self._poser_entite_dessinee(item, cx, sy, 0, "RECT")
        elif shape_type == "circle" and diameter > 0:
            r = diameter / 2.0
            item = self._scene.addEllipse(
                cx - r, sy - r, 2 * r, 2 * r, pen)
            self._poser_entite_dessinee(item, cx, sy, r, "CIRCLE")
        elif shape_type == "line" and width > 0:
            item = self._scene.addLine(
                cx - width / 2, sy, cx + width / 2, sy, pen)
            self._poser_entite_dessinee(item, cx, sy, 0, "LINE")

    # ──── Events ────

    def wheelEvent(self, event: QWheelEvent):
        """Zoom centré sur la position du pointeur."""
        # AnchorUnderMouse est déjà configuré, donc scale() suffit
        factor = 1.15
        if event.angleDelta().y() > 0:
            self.scale(factor, factor)
            self._zoom *= factor
        else:
            self.scale(1 / factor, 1 / factor)
            self._zoom /= factor

    #: tolerance sous laquelle un glisser n'en est pas un (mm scene)
    _DRAG_EPS = 1e-6

    def _noter_poses_avant_drag(self):
        """Positions des entites deplacables, avant un glisser."""
        poses = {}
        try:
            for item in self._scene.selectedItems():
                if item.flags() & (QGraphicsItem.GraphicsItemFlag
                                   .ItemIsMovable):
                    poses[id(item)] = (item, item.pos().x(),
                                       item.pos().y())
        except RuntimeError:
            poses = {}
        self._poses_avant_drag = poses

    def _empiler_drag_souris(self):
        """Apres un glisser: si des entites ont bouge, une annulation.

        Qt a deja fait le deplacement; la commande ne fait que retenir
        les positions d'avant et d'apres."""
        poses = getattr(self, '_poses_avant_drag', None) or {}
        self._poses_avant_drag = {}
        if self._poignees:
            self._maj_poignees()
        if not poses:
            return
        bouges = []
        for item, x0, y0 in poses.values():
            try:
                x1, y1 = item.pos().x(), item.pos().y()
            except RuntimeError:
                continue
            if (abs(x1 - x0) > self._DRAG_EPS
                    or abs(y1 - y0) > self._DRAG_EPS):
                bouges.append((item, (x0, y0), (x1, y1)))
        if not bouges:
            return
        from src.gui.dxf.canvas_undo import DeplacerSourisCommande
        self._pile_undo.push(DeplacerSourisCommande(self, bouges))

    def mousePressEvent(self, event: QMouseEvent):
        # Cliquer dans le canvas doit y AMENER LE CLAVIER: presque
        # tous les chemins ci-dessous rendent la main sans appeler
        # l'implémentation de Qt, qui est celle qui donne le focus.
        # Sans ça, F2, Suppr, Ctrl+Z et les flèches partaient à
        # l'onglet — la sélection était bien faite, rien ne répondait.
        if not self.hasFocus():
            self.setFocus(Qt.FocusReason.MouseFocusReason)
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_active = True
            self._pan_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return

        if event.button() == Qt.MouseButton.RightButton \
                and self.outil_en_cours():
            # une polyligne commencée se finit au relâcher (courbe
            # ouverte); tout autre outil rend la sélection
            if not (self._draw_tool == "bezier"
                    and len(self._draw_points) >= 2):
                self.quitter_outil()
                self.retour_selection.emit()
            event.accept()
            return

        if event.button() == Qt.MouseButton.LeftButton:
            scene_pos = self.mapToScene(event.position().toPoint())
            # une poignée sous la souris: on prend le SOMMET (Ctrl+clic:
            # on le supprime), pas l'entité
            if (self._poignees and self._select_mode
                    and not self._pick_mode and not self._draw_tool):
                k = self._poignee_sous(scene_pos)
                if k is not None:
                    if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                        self.supprimer_sommet(k)
                    else:
                        self._commencer_poignee(k)
                    return
            self._noter_poses_avant_drag()
            snapped = self._snap_to_point(scene_pos)
            dxf_x = snapped.x()
            dxf_y = -snapped.y()

            # Placement de symbole en cours: poser au clic
            if getattr(self, '_placing_symbol_path', None):
                self._confirm_symbol_placement(dxf_x, dxf_y)
                return

            if (self._select_mode and not self._pick_mode
                    and not self._draw_tool):
                # Démarrer la sélection rectangle (rubber band)
                self._rubber_band_active = True
                self._rubber_band_origin = scene_pos
                rb_pen = QPen(QColor("#89b4fa"), 0)
                rb_pen.setStyle(Qt.PenStyle.DashLine)
                rb_pen.setWidthF(0.5 / max(self._zoom, 0.01))
                rb_brush = QBrush(QColor(137, 180, 250, 30))
                self._rubber_band_item = self._scene.addRect(
                    QRectF(scene_pos, scene_pos), rb_pen, rb_brush)
                return

            if self._draw_tool == "texte_grave":
                # Texte GRAVE: le formulaire s'ouvre, puis les
                # contours se posent la ou l'on a clique
                self.texte_grave_demande.emit(dxf_x, dxf_y)
                return

            if self._draw_tool == "texte":
                # Le texte se pose LÀ OÙ L'ON CLIQUE: au centre de la
                # vue, il fallait le déplacer aussitôt
                self.texte_demande.emit(dxf_x, dxf_y)
                return

            if self._pick_mode:
                self.coordinate_picked.emit(dxf_x, dxf_y)
                return

            if self._draw_tool:
                self._handle_draw_click(snapped)
                return

            # Clic sur un marqueur d'opération → sélectionner le point
            if self._op_point_positions:
                radius = 8.0 / max(self._zoom, 0.01)
                best_i, best_d = -1, radius
                for px, py, i in self._op_point_positions:
                    d = QLineF(scene_pos, QPointF(px, py)).length()
                    if d < best_d:
                        best_d = d
                        best_i = i
                if best_i >= 0:
                    self.op_point_clicked.emit(
                        self._op_points_source, best_i)
                    return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._pan_active:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta.y()))
            return

        scene_pos = self.mapToScene(event.position().toPoint())
        if self._poignee_drag is not None:
            # le sommet suit la souris, et tombe sur les points du
            # dessin (accrochages)
            pos = self._snap_to_point(scene_pos)
            self._montrer_prise(self.derniere_prise)
            self.deplacer_sommet(pos)
            self.mouse_position.emit(pos.x(), -pos.y())
            return
        ghost = getattr(self, '_placement_ghost', None)
        # Pendant un tracé, une mesure, un pointage ou un placement,
        # le curseur TOMBE sur les points du dessin: la marque dit
        # lequel (carré = extrémité, triangle = milieu…)
        if (self._draw_tool or self._pick_mode or self._ruler_mode
                or ghost is not None):
            scene_pos = self._snap_to_point(scene_pos)
            self._montrer_prise(self.derniere_prise)
        elif self._marque_accroche is not None:
            self._montrer_prise(None)
        self.mouse_position.emit(scene_pos.x(), -scene_pos.y())

        # Fantôme de placement: suit la souris (avec accrochage)
        if ghost is not None:
            ghost.setPos(scene_pos)
            return

        # Mise à jour du rubber band de sélection rectangle
        if self._rubber_band_active and self._rubber_band_item and self._rubber_band_origin:
            r = QRectF(self._rubber_band_origin, scene_pos).normalized()
            self._rubber_band_item.setRect(r)
            return

        if self._draw_tool and self._draw_points:
            self._update_draw_preview(scene_pos)

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        # Right-click: finaliser bezier comme courbe ouverte
        if event.button() == Qt.MouseButton.RightButton:
            if self._draw_tool == "bezier" and len(self._draw_points) >= 2:
                self._finalize_bezier(close=False)
                return
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_active = False
            if self._pick_mode or self._draw_tool or self._select_mode:
                self.setCursor(Qt.CursorShape.CrossCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)
            return

        if (event.button() == Qt.MouseButton.LeftButton
                and self._poignee_drag is not None):
            self.finir_poignee()
            return

        if event.button() == Qt.MouseButton.LeftButton and self._rubber_band_active:
            self._rubber_band_active = False
            if self._rubber_band_item and self._rubber_band_origin:
                scene_pos = self.mapToScene(event.position().toPoint())
                sel_rect = QRectF(
                    self._rubber_band_origin, scene_pos).normalized()
                # Vérifier si c'est un simple clic (pas de drag)
                if sel_rect.width() < 2 / max(self._zoom, 0.01) and \
                   sel_rect.height() < 2 / max(self._zoom, 0.01):
                    # Simple clic: toggle l'entité la plus proche
                    self._scene.removeItem(self._rubber_band_item)
                    self._rubber_band_item = None
                    self._handle_select_click(
                        scene_pos,
                        ajouter=bool(event.modifiers()
                                     & (Qt.KeyboardModifier
                                        .ControlModifier
                                        | Qt.KeyboardModifier
                                        .ShiftModifier)))
                    return
                # Sélectionner toutes les entités dans le rectangle
                self._scene.removeItem(self._rubber_band_item)
                self._rubber_band_item = None
                # Sans modificateur, un nouveau rectangle REMPLACE la
                # sélection: sinon, sur un dessin dense, on empile
                # sans jamais pouvoir revenir en arrière
                if not (event.modifiers()
                        & (Qt.KeyboardModifier.ControlModifier
                           | Qt.KeyboardModifier.ShiftModifier)):
                    self.clear_selection()
                # Commencé en HAUT (la souris descend), le rectangle
                # prend ce qu'il englobe entièrement; commencé en
                # BAS, ce qu'il touche. La scène a Y vers le bas: un
                # départ plus haut à l'écran est un y de scène plus
                # petit.
                englobees = self._rubber_band_origin.y() <= scene_pos.y()
                self._select_items_in_rect(sel_rect,
                                           englobees=englobees)
            self._poses_avant_drag = {}
            return

        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self._empiler_drag_souris()

    #: pinceau du surlignage d'une entité prise
    _PINCEAU_SELECTION = ("#f9e2af", 0.5)

    def _surligner(self, item) -> bool:
        """Marque une entité comme prise. Rend True si c'est nouveau.

        Ce qu'on a DESSINÉ porte le drapeau de sélection de Qt (cadre
        pointillé, déplaçable); ce qui vient d'un fichier n'a que son
        pinceau — on le surligne."""
        if item in self._selected_items or item.isSelected():
            return False
        if item.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsSelectable:
            item.setSelected(True)
            return True
        couleur, epaisseur = self._PINCEAU_SELECTION
        if isinstance(item, (QGraphicsLineItem, QGraphicsEllipseItem,
                             QGraphicsRectItem, QGraphicsPathItem)):
            self._original_pens[id(item)] = item.pen()
            item.setPen(QPen(QColor(couleur), epaisseur))
        self._selected_items.append(item)
        return True

    def _select_items_in_rect(self, rect: QRectF,
                              englobees: bool = False):
        """Prend ce que le rectangle touche — ou, `englobees`, ce
        qu'il contient entièrement — sur les calques visibles.

        Trois limites tombaient ici: seul le CENTRE de l'entité
        comptait (une pièce plus grande que le rectangle ne se
        prenait jamais), les annotations étaient sautées, et un
        calque masqué se sélectionnait quand même — on effaçait
        alors ce qu'on ne voyait pas."""
        connus = {id(i) for i in self._dxf_items}
        pris = 0
        mode = (Qt.ItemSelectionMode.ContainsItemShape if englobees
                else Qt.ItemSelectionMode.IntersectsItemShape)
        for item in self._scene.items(rect, mode):
            if id(item) not in connus or not item.isVisible():
                continue
            if self._surligner(item):
                pris += 1
        selection = self.selection_courante()
        self.selection_changed.emit(len(selection))
        if selection:
            calques = {self._item_layer.get(id(i), 'dxf')
                       for i in selection}
            self.entity_info.emit(
                f"{len(selection)} entités sélectionnées "
                f"({len(calques)} calque(s))")

    #: déplacements des quatre flèches, en pas
    _FLECHES = {
        Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0),
        Qt.Key.Key_Up: (0, 1), Qt.Key.Key_Down: (0, -1),
    }

    def mettre_en_evidence(self, x: float, y: float, w: float,
                           h: float) -> bool:
        """Encadre en surbrillance le rectangle (centre machine x,y;
        dimensions w×h) — celui d'une instance —, et le remplace à
        l'appel suivant. Rend vrai si le cadre a été posé."""
        self.effacer_evidence()
        if w <= 0 or h <= 0:
            return False
        from PySide6.QtCore import QRectF
        rect = QRectF(x - w / 2.0, -y - h / 2.0, w, h)
        stylo = QPen(QColor("#f9e2af"), 0.0)
        stylo.setCosmetic(True)
        stylo.setWidth(3)
        item = self._scene.addRect(rect, stylo)
        item.setZValue(1000)
        self._evidence_item = item
        # amener le rectangle dans la vue
        try:
            self.ensureVisible(rect, 40, 40)
        except RuntimeError:
            pass
        return True

    def effacer_evidence(self) -> None:
        item = getattr(self, '_evidence_item', None)
        if item is not None:
            try:
                if item.scene() is not None:
                    self._scene.removeItem(item)
            except RuntimeError:
                pass
            self._evidence_item = None

    def selectionner_import(self, cle: str) -> int:
        """Sélectionne les entités d'un DXF importé (pour les déplacer,
        les tourner, en tirer des opérations). Rend leur nombre."""
        source = getattr(self, '_item_source', {})
        # ce qui vient d'un fichier se prend au pinceau (pas de drapeau
        # de sélection Qt)
        self.clear_selection()
        n = 0
        for item in list(self._dxf_items):
            if source.get(id(item)) != cle:
                continue
            try:
                if not item.isVisible():
                    continue
                if self._surligner(item):
                    n += 1
            except RuntimeError:
                continue
        self.selection_changed.emit(len(self.selection_courante()))
        return n

    def selectionner_tout(self) -> int:
        """Sélectionne toutes les entités du dessin (calques dxf,
        drawn, smb). Rend le nombre sélectionné."""
        self._scene.clearSelection()
        self._selected_items = []
        n = 0
        for item in list(self._dxf_items):
            try:
                item.setSelected(True)
            except RuntimeError:
                continue
            n += 1
        self.selection_changed.emit(len(self.selection_courante()))
        return n

    def keyPressEvent(self, event: QKeyEvent):
        touche = event.key()
        ctrl = bool(event.modifiers()
                    & Qt.KeyboardModifier.ControlModifier)
        alt = bool(event.modifiers()
                   & Qt.KeyboardModifier.AltModifier)
        # Alt+W: le centre de la sélection en 0,0 — la sélection
        # SEULE se déplace, le reste du dessin garde sa place (le
        # bouton « Centrer », lui, emmène tout le dessin)
        if alt and touche == Qt.Key.Key_W:
            (dx, dy), n = self.amener_selection_en_zero()
            self.entity_info.emit(
                f"Alt+W: la sélection ({n} entité(s)) en 0,0 — déplacée "
                f"de {dx:+.2f}, {dy:+.2f}; le reste du dessin n'a pas "
                "bougé (Ctrl+Z annule)" if n else
                "Alt+W: sélectionnez d'abord ce qu'il faut amener en "
                "0,0 (un clic sur l'onglet d'un import le sélectionne)")
            event.accept()
            return
        # Ctrl+A: tout sélectionner
        if ctrl and touche == Qt.Key.Key_A:
            self.selectionner_tout()
            event.accept()
            return
        # Ctrl + flèche: donner le focus au champ « Pas » pour y taper
        # une valeur exacte. Entrée rend le focus au dessin, et les
        # flèches déplacent alors la sélection de ce pas.
        if ctrl and touche in self._FLECHES:
            self.pas_focus_demande.emit()
            event.accept()
            return
        # Flèches: déplacer la sélection du pas courant (×10 avec Maj)
        if touche in self._FLECHES and not ctrl:
            dx, dy = self._FLECHES[touche]
            pas = self.nudge_step()
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                pas *= 10
            self.deplacer_selection(dx * pas, dy * pas)
            # Consommé dans tous les cas: une flèche ne fait pas
            # défiler la vue sous les doigts de l'utilisateur
            event.accept()
            return
        if touche in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            # Pendant un tracé, Suppr appartient au tracé en cours
            if not (self._draw_tool and self._draw_points):
                # La fenêtre décide: Suppr vise ce qu'on a choisi en
                # dernier, entités OU opération
                routeur = getattr(self.window(),
                                  'supprimer_selon_le_dernier_choix', None)
                if callable(routeur):
                    routeur()
                else:
                    self._delete_selected()
                event.accept()
                return
        if (event.modifiers() & Qt.KeyboardModifier.ControlModifier
                and touche in (Qt.Key.Key_C, Qt.Key.Key_X,
                               Qt.Key.Key_V)):
            if touche == Qt.Key.Key_C:
                self.copier_selection()
            elif touche == Qt.Key.Key_X:
                self.couper_selection()
            else:
                self.coller()
            event.accept()
            return
        if touche == Qt.Key.Key_G and (
                event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.degrouper_selection()
            else:
                self.grouper_selection()
            event.accept()
            return
        if touche == Qt.Key.Key_F2:
            self.resize_requested.emit()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            # Échap rend toujours la main: outil en cours d'abord,
            # sélection ensuite
            if not (self._draw_tool
                    or getattr(self, '_placement_ghost', None)):
                if self.selection_courante():
                    self.clear_selection()
                    event.accept()
                    return
            avait_outil = self.outil_en_cours()
            self.cancel_symbol_placement()
            if self._draw_tool == "bezier" and self._draw_points:
                # Cancel current bezier without creating curve
                self._draw_points.clear()
                if self._temp_item:
                    self._scene.removeItem(self._temp_item)
                    self._temp_item = None
            self.set_draw_tool(None)
            self.set_pick_mode(False)
            if avait_outil:
                # les boutons du panneau (la Règle restait enfoncée)
                self.retour_selection.emit()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._draw_tool == "bezier" and len(self._draw_points) >= 2:
                self._finalize_bezier(close=False)
        elif event.key() == Qt.Key.Key_F8:
            # F8: ortho (90°), comme partout en DAO
            self.set_ortho(0.0 if self._ortho_pas else 90.0)
            self.ortho_change.emit(self._ortho_pas)
        elif event.key() == Qt.Key.Key_F:
            self.fit_all()
        elif (event.key() == Qt.Key.Key_Z and
              event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            # Ctrl+Maj+Z = rétablir; Ctrl+Z = annuler
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.redo()
            else:
                self.undo()
            event.accept()
            return
        elif (event.key() == Qt.Key.Key_Y and
              event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.redo()
            event.accept()
            return
        super().keyPressEvent(event)

    def _delete_selected(self):
        """Supprime la sélection (Suppr ou Retour arrière).

        UNE seule source de vérité: `selection_courante`. Elle réunit
        les deux façons de sélectionner (au pinceau, par Qt), étend
        aux GROUPES, et écarte ce qui n'est plus dans la scène — un
        item déjà retiré faisait planter la touche Suppr.

        Chaque entité emporte ce qui lui appartient: son centre
        marqué (sinon « DXF to Op » proposerait encore des perçages
        sur les trous supprimés) et l'annotation posée dessus.
        Ctrl+Z rend le tout d'un coup."""
        self._oublier_les_fantomes()
        selection = self.selection_courante()
        if not selection:
            return
        lot = self._effacer_en_lot(selection)
        if lot:
            from src.gui.dxf.canvas_undo import SupprimerCommande
            self._pile_undo.push(SupprimerCommande(self, lot))
        self._selected_items.clear()
        self._scene.clearSelection()
        self.selection_changed.emit(0)
        self.entity_info.emit("")

    def _effacer_en_lot(self, items) -> list:
        """Retire des entités AVEC ce qui leur appartient (centres
        marqués, annotations attachées, liens de groupe) et rend le
        « lot » qui permet de tout rendre d'un coup.

        Le tracé à la main s'annule par le même chemin que la touche
        Suppr: une seule machinerie, éprouvée."""
        removed_center = False
        lot = []
        a_effacer = []
        vus = set()
        for item in items:
            for candidat in [item] + self._attaches.get(id(item), []):
                if id(candidat) in vus:
                    continue
                vus.add(id(candidat))
                a_effacer.append(candidat)
        # Les clés de groupe se lisent AVANT toute suppression:
        # retirer le premier membre dissout un groupe de deux, et le
        # second serait rendu sans son lien
        groupes_avant = {id(i): self._groupe_de.get(id(i), "")
                         for i in a_effacer}
        for item in a_effacer:
            iid = id(item)
            pen = self._original_pens.pop(iid, None)
            was_in_dxf = item in self._dxf_items
            if was_in_dxf:
                self._dxf_items.remove(item)
            if item in self._center_markers:
                self._center_markers.remove(item)
            groupe = groupes_avant.get(iid, "")
            self._oublier_des_groupes(item)
            try:
                if item.scene() is not None:
                    self._scene.removeItem(item)
            except RuntimeError:
                continue      # objet déjà détruit: rien à défaire
            # Retirer le centre détecté associé (restauré par undo)
            center = self._item_metadata.get(iid)
            if center is not None and center in self._detected_circles:
                self._detected_circles.remove(center)
                removed_center = True
            layer = self._item_layer.pop(iid, 'dxf')
            attaches = self._attaches.pop(iid, [])
            lot.append((item, pen, was_in_dxf, center, layer,
                        attaches, groupe))
        if removed_center:
            self.circles_detected.emit(self._detected_circles)
        return lot

    def _retirer_lot(self, lot):
        """Re-supprime un lot déjà restauré (rétablir d'une suppression).

        Miroir de `_restaurer_lot`: retire les entités de la scène et
        des index, ré-oublie centres et groupes."""
        centre_retire = False
        for entree in lot:
            (item, pen, was_in_dxf, center, layer, attaches,
             groupe) = (entree + ("",))[:7]
            self._oublier_des_groupes(item)
            try:
                if item.scene() is not None:
                    self._scene.removeItem(item)
            except RuntimeError:
                continue
            if was_in_dxf and item in self._dxf_items:
                self._dxf_items.remove(item)
            if item in self._center_markers:
                self._center_markers.remove(item)
            if center is not None and center in self._detected_circles:
                self._detected_circles.remove(center)
                centre_retire = True
        if centre_retire:
            self.circles_detected.emit(self._detected_circles)
        self._selected_items.clear()
        self._scene.clearSelection()
        self.selection_changed.emit(0)

    def _restaurer_lot(self, lot):
        """Rend une suppression, entière (annuler d'une suppression)."""
        # Les anciennes entrées étaient un tuple par entité
        if not isinstance(lot, list):
            lot = [lot]
        centre_rendu = False
        groupes_rendus = {}
        for entree in lot:
            # Les lots d'avant les groupes n'ont que six champs
            (item, pen, was_in_dxf, center, layer, attaches,
             groupe) = (entree + ("",))[:7]
            try:
                self._scene.addItem(item)
            except RuntimeError:
                continue
            if attaches:
                self._attaches[id(item)] = attaches
            if groupe:
                groupes_rendus.setdefault(groupe, []).append(item)
            if pen and isinstance(
                    item, (QGraphicsLineItem, QGraphicsEllipseItem,
                           QGraphicsRectItem, QGraphicsPathItem)):
                item.setPen(pen)
            if was_in_dxf:
                self._register_item(item, layer)
            if (center is not None
                    and center not in self._detected_circles):
                self._detected_circles.append(center)
                centre_rendu = True
            if item.data(0) == 'marqueur_centre':
                self._center_markers.append(item)
        # Un groupe défait par la suppression se refait: rendre les
        # entités sans leur lien serait les rendre à moitié
        for cle, membres in groupes_rendus.items():
            if len(membres) >= 2:
                self._groupes[cle] = membres
                for membre in membres:
                    self._groupe_de[id(membre)] = cle
        if centre_rendu:
            self.circles_detected.emit(self._detected_circles)
        self.entity_info.emit(
            f"{len(lot)} entité(s) rendue(s)")

    # ──── Annuler / rétablir du dessin (helpers des commandes) ────

    def _decaler_items_scene(self, items, dx: float, dy: float):
        """Déplace des items d'un delta de SCÈNE (pour undo/redo)."""
        self.deplacer_items(list(items), dx, dy)

    def _retirer_items_simple(self, items):
        """Retire des items ajoutés (undo d'un coller)."""
        for it in list(items):
            try:
                if it.scene() is not None:
                    self._scene.removeItem(it)
            except RuntimeError:
                continue
            if it in self._dxf_items:
                self._dxf_items.remove(it)
        self._selected_items.clear()
        self._scene.clearSelection()
        self.selection_changed.emit(0)

    def _rajouter_items_simple(self, items):
        """Remet des items retirés (redo d'un coller)."""
        for it in list(items):
            layer = self._item_layer.get(id(it), 'drawn')
            try:
                self._scene.addItem(it)
            except RuntimeError:
                continue
            if it not in self._dxf_items:
                self._register_item(it, layer)
        self._extend_scene_rect()

    def undo(self):
        """Annule le dernier geste du dessin (Ctrl+Z sur le canvas)."""
        if self._pile_undo.canUndo():
            self._pile_undo.undo()

    def redo(self):
        """Rétablit le dernier geste annulé (Ctrl+Y sur le canvas)."""
        if self._pile_undo.canRedo():
            self._pile_undo.redo()

    def _snap_to_point(self, scene_pos: QPointF) -> QPointF:
        """Le point où tombe le curseur: un point du dessin
        (accrochage objet), sinon un centre marqué, sinon la grille.
        La prise retenue reste dans `derniere_prise`."""
        from src.core.accrochage import Prise
        self.derniere_prise = None
        if not self._snap_enabled:
            return scene_pos

        snap_dist = self._snap_radius / max(self._zoom, 0.01)
        if self._accrochages:
            prise = self._prise_objet(scene_pos, snap_dist)
            if prise is not None:
                self.derniere_prise = prise
                return QPointF(prise.x, prise.y)
        if self._ortho_pas and self._draw_tool and self._draw_points:
            # ortho: la direction d'abord, la grille ne la fausse pas
            return self._contraindre_ortho(scene_pos)

        best_dist = snap_dist
        best_point = scene_pos
        mode = None

        for marker in self._center_markers:
            if isinstance(marker, QGraphicsEllipseItem):
                center = marker.sceneBoundingRect().center()
                dist = QLineF(scene_pos, center).length()
                if dist < best_dist:
                    best_dist = dist
                    best_point = center
                    mode = 'centre'

        if self._grid_visible:
            gx = round(scene_pos.x() / self._grid_spacing) * self._grid_spacing
            gy = round(scene_pos.y() / self._grid_spacing) * self._grid_spacing
            grid_point = QPointF(gx, gy)
            dist = QLineF(scene_pos, grid_point).length()
            if dist < best_dist:
                best_dist = dist
                best_point = grid_point
                mode = 'grille'

        if mode is not None:
            self.derniere_prise = Prise(best_point.x(), best_point.y(),
                                        mode, best_dist)
        return best_point

    def set_ortho(self, pas_degres: float) -> None:
        """Ortho (90°) ou angles imposés (45°, 30°, 15°): le trait qu'on
        trace tourne par pas depuis le point précédent; 0: libre."""
        self._ortho_pas = max(0.0, float(pas_degres or 0.0))
        self.entity_info.emit(
            f"Ortho {self._ortho_pas:g}°" if self._ortho_pas
            else "Ortho désactivé")

    def _contraindre_ortho(self, pos: QPointF) -> QPointF:
        """Le point ramené sur la direction permise la plus proche (un
        accrochage objet l'emporte: on vise un point du dessin)."""
        if not self._ortho_pas or not (self._draw_tool and self._draw_points):
            return pos
        prise = self.derniere_prise
        if prise is not None and prise.mode != 'grille':
            return pos
        base = self._draw_points[-1]
        vx, vy = pos.x() - base.x(), -(pos.y() - base.y())
        longueur = math.hypot(vx, vy)
        if longueur <= 1e-12:
            return pos
        pas = math.radians(self._ortho_pas)
        a = math.atan2(vy, vx)
        a2 = round(a / pas) * pas
        proj = longueur * math.cos(a - a2)
        return QPointF(base.x() + proj * math.cos(a2),
                       base.y() - proj * math.sin(a2))

    def set_accrochages(self, actifs: bool) -> None:
        """Les accrochages objet (bouton « Accroch. »). La grille et
        les centres marqués accrochent toujours."""
        self._accrochages = bool(actifs)
        if not actifs:
            self._montrer_prise(None)

    def _traces_scene(self, item, tolerance: float = None) -> list:
        """Les tracés d'une entité, en coordonnées de SCÈNE: une liste
        de polylignes [(x, y), …] (fermée: le dernier point répète le
        premier)."""
        try:
            if isinstance(item, QGraphicsLineItem):
                ln = item.line()
                a, b = item.mapToScene(ln.p1()), item.mapToScene(ln.p2())
                return [[(a.x(), a.y()), (b.x(), b.y())]]
            if isinstance(item, QGraphicsRectItem):
                pol = item.mapToScene(item.rect())
                pts = [(p.x(), p.y()) for p in pol]
                return [pts + pts[:1]]
            if isinstance(item, QGraphicsEllipseItem):
                chemin = QPainterPath()
                chemin.addEllipse(item.rect())
                return self.polygones_fins(item.mapToScene(chemin),
                                           tolerance)
            if isinstance(item, QGraphicsPolygonItem):
                pol = item.mapToScene(item.polygon())
                pts = [(p.x(), p.y()) for p in pol]
                return [pts + pts[:1]] if len(pts) >= 3 else []
            if isinstance(item, QGraphicsPathItem):
                return self.polygones_fins(item.mapToScene(item.path()),
                                           tolerance)
        except (RuntimeError, IndexError):
            return []
        return []

    def _geometrie_item(self, item):
        """(polylignes, cercles) d'une entité pour l'accrochage, en
        scène — gardées tant qu'elle ne bouge ni ne change."""
        import numpy as _np
        try:
            t = item.sceneTransform()
            r = item.boundingRect()
        except RuntimeError:
            return [], []
        signature = (t.m11(), t.m12(), t.m21(), t.m22(), t.dx(), t.dy(),
                     r.x(), r.y(), r.width(), r.height())
        cache = self._geo_cache.get(id(item))
        if cache is not None and cache[1] is item and cache[0] == signature:
            return cache[2]
        polylignes = [_np.asarray(p, dtype=float)
                      for p in self._traces_scene(item, 0.01) if len(p) >= 2]
        cercles = []
        if isinstance(item, QGraphicsEllipseItem):
            rect = item.rect()
            if abs(rect.width() - rect.height()) <= 1e-6 * max(
                    1.0, rect.width()):
                centre = item.mapToScene(rect.center())
                bord = item.mapToScene(QPointF(rect.right(),
                                               rect.center().y()))
                cercles.append((centre.x(), centre.y(),
                                QLineF(centre, bord).length()))
        if len(self._geo_cache) > 5000:
            self._geo_cache.clear()
        self._geo_cache[id(item)] = (signature, item, (polylignes, cercles))
        return polylignes, cercles

    def _prise_objet(self, scene_pos: QPointF, rayon: float):
        """Le meilleur accrochage objet près du curseur (ou None)."""
        from src.core import accrochage
        boite = QRectF(scene_pos.x() - rayon, scene_pos.y() - rayon,
                       2 * rayon, 2 * rayon)
        polylignes, cercles = [], []
        temporaires = {id(self._temp_item), id(self._marque_accroche)}
        for item in self._scene.items(
                boite, Qt.ItemSelectionMode.IntersectsItemBoundingRect):
            if id(item) in temporaires or id(item) not in self._item_layer:
                continue
            if not item.isVisible() or isinstance(item, QGraphicsTextItem):
                continue
            pl, ce = self._geometrie_item(item)
            polylignes.extend(pl)
            cercles.extend(ce)
        # les cercles détectés (DXF, STEP): centre et quadrants
        x, y = scene_pos.x(), scene_pos.y()
        for c in self._detected_circles:
            try:
                cx, cy = float(c.get('x', 0.0)), -float(c.get('y', 0.0))
                rc = float(c.get('radius', 0.0) or 0.0)
            except (TypeError, ValueError, AttributeError):
                continue
            if abs(cx - x) <= rc + rayon and abs(cy - y) <= rc + rayon:
                cercles.append((cx, cy, rc))
        base = None
        if self._draw_tool and self._draw_points:
            p = self._draw_points[-1]
            base = (p.x(), p.y())
        if not polylignes and not cercles:
            return None
        return accrochage.accrocher((x, y), polylignes, cercles, rayon,
                                    base=base)

    def _montrer_prise(self, prise) -> None:
        """La marque du point accroché, à taille fixe à l'écran."""
        from src.core import accrochage
        marque = self._marque_accroche
        if prise is None or prise.mode == 'grille':
            if marque is not None:
                try:
                    marque.setVisible(False)
                except RuntimeError:
                    self._marque_accroche = None
            return
        try:
            vivante = marque is not None and marque.scene() is self._scene
        except RuntimeError:
            vivante = False
        if not vivante:
            marque = QGraphicsPathItem()
            marque.setFlag(
                QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations,
                True)
            stylo = QPen(QColor("#a6e3a1"), 1.6)
            stylo.setCosmetic(True)
            marque.setPen(stylo)
            marque.setZValue(1e6)
            self._scene.addItem(marque)
            self._marque_accroche = marque
        chemin = QPainterPath()
        for trait in accrochage.marque(prise.mode, 5.0):
            chemin.moveTo(trait[0][0], trait[0][1])
            for px, py in trait[1:]:
                chemin.lineTo(px, py)
        marque.setPath(chemin)
        marque.setPos(prise.x, prise.y)
        marque.setToolTip(prise.nom)
        marque.setVisible(True)

    # ──── Retouches du dessin (src.core.retouche) ────

    _GENRES_RETOUCHABLES = (QGraphicsPathItem, QGraphicsLineItem,
                            QGraphicsRectItem, QGraphicsEllipseItem,
                            QGraphicsPolygonItem)

    def _polylignes_machine(self, item) -> list:
        """Les tracés d'une entité en coordonnées MACHINE (Y vers le
        haut), finement aplatis."""
        return [[(x, -y) for x, y in pl]
                for pl in self._traces_scene(item) if len(pl) >= 2]

    def items_retouchables(self, items=None) -> list:
        """Les entités de la sélection (ou `items`) qu'une retouche
        peut reprendre: tracés des calques DXF et Dessin."""
        items = self.selection_courante() if items is None else items
        sortie = []
        for it in items:
            if not isinstance(it, self._GENRES_RETOUCHABLES):
                continue
            if self._item_layer.get(id(it)) not in ('dxf', 'drawn'):
                continue
            sortie.append(it)
        return sortie

    def _nouvelle_entite(self, polyligne, calque: str, stylo,
                         source=None, nom=None):
        from src.core.retouche import est_fermee
        if isinstance(polyligne, QPainterPath):
            chemin = QPainterPath(polyligne)      # déjà en scène
        else:
            chemin = QPainterPath()
            pts = list(polyligne)
            ferme = est_fermee(pts)
            if ferme:
                pts = pts[:-1]
            chemin.moveTo(pts[0][0], -pts[0][1])
            for x, y in pts[1:]:
                chemin.lineTo(x, -y)
            if ferme:
                chemin.closeSubpath()
        item = self._scene.addPath(chemin, QPen(stylo))
        if nom is not None:
            item.setData(0, nom)
        self._register_item(item, calque)
        if source:
            if not hasattr(self, '_item_source'):
                self._item_source = {}
            self._item_source[id(item)] = source
        return item

    def remplacer_entites(self, anciens, nouvelles, texte: str,
                          calque: str = None) -> list:
        """Remplace des entités par des polylignes (coordonnées
        machine), en UN geste annulable. Les nouvelles prennent le
        calque, l'import (onglet) et le trait de la première ancienne;
        elles restent sélectionnées. Rend les nouvelles entités."""
        from src.gui.dxf.canvas_undo import RemplacerCommande
        anciens = list(anciens)
        modele = anciens[0] if anciens else None
        if calque is None:
            calque = (self._item_layer.get(id(modele), 'drawn')
                      if modele is not None else 'drawn')
        source = (getattr(self, '_item_source', {}).get(id(modele))
                  if modele is not None and calque == 'dxf' else None)
        try:
            stylo = QPen(self._original_pens.get(id(modele))
                         or modele.pen())
        except (AttributeError, RuntimeError, TypeError):
            stylo = QPen(QColor("#f9e2af"), 0.2)
        nom = modele.data(0) if modele is not None else None
        self.clear_selection()
        lot = self._effacer_en_lot(anciens) if anciens else []
        neufs = [self._nouvelle_entite(pl, calque, stylo, source, nom)
                 for pl in nouvelles
                 if (isinstance(pl, QPainterPath) and not pl.isEmpty())
                 or (not isinstance(pl, QPainterPath) and len(pl) >= 2)]
        self._scene.clearSelection()
        self._selected_items = []
        for item in neufs:
            self._surligner(item)
        self._extend_scene_rect()
        self._pile_undo.push(RemplacerCommande(self, lot, neufs, texte))
        self.selection_changed.emit(len(self.selection_courante()))
        return neufs

    def nettoyer_dessin(self, items=None, tol: float = None,
                        executer=None) -> Optional[dict]:
        """Doublons retirés, traits couverts retirés, morceaux joints.

        Sur la sélection, ou — sans sélection — sur tout le dessin
        visible (DXF et Dessin). Chaque import se nettoie à part: un
        trait ne disparaît pas parce qu'un autre fichier le double.
        Les contours fermés ne sont pas touchés, sauf leurs doublons.

        `executer(calcul)`: fait tourner le calcul (un fil de travail
        et sa barre de progression — `travailler`), rend None s'il a
        été annulé. Rend le bilan (voir `retouche.nettoyer`) +
        'message', ou None (annulé)."""
        from src.core import retouche as rt
        from src.core.vcarve import avancer
        tol = float(tol or rt.TOLERANCE)
        if items is None:
            items = self.items_retouchables()
            if not items:
                items = self.items_retouchables(
                    [it for it in self._dxf_items if it.isVisible()])
        else:
            items = self.items_retouchables(items)
        source = getattr(self, '_item_source', {})
        groupes = {}
        for it in items:
            cle = (self._item_layer.get(id(it)), source.get(id(it)))
            groupes.setdefault(cle, []).append(it)
        # 1. lire les tracés (fil de l'interface: ce sont des items Qt)
        lus = [(calque, [(it, self._polylignes_machine(it)) for it in m])
               for (calque, _src), m in groupes.items()]

        # 2. le calcul, sans Qt (dans un fil s'il y a un `executer`)
        def calcul(progression=None):
            sortie = []
            for k, (calque, membres) in enumerate(lus):
                avancer(progression, k / max(1, len(lus)),
                        f"nettoyage {k + 1}/{len(lus)}")
                vus, gardes, jetes = set(), [], []
                avant = doubles = 0
                for i, (it, pls) in enumerate(membres):
                    if progression is not None and i % 500 == 0:
                        avancer(progression, (k + 0.3 * i / max(
                            1, len(membres))) / max(1, len(lus)),
                            "doublons")
                    pls = [q for q in (rt._propre(p) for p in pls)
                           if len(q) >= 2]
                    if not pls:
                        continue
                    avant += len(pls)
                    cle = tuple(sorted(rt._cle_doublon(p, tol)
                                       for p in pls))
                    if cle in vus:
                        jetes.append(it)
                        doubles += len(pls)
                    else:
                        vus.add(cle)
                        gardes.append((it, pls))
                ouvertes = [(it, pls) for it, pls in gardes
                            if not any(rt.est_fermee(p, tol) for p in pls)]
                fermees = [p for _it, pls in gardes for p in pls
                           if rt.est_fermee(p, tol)]
                polys = [p for _it, pls in ouvertes for p in pls]
                avancer(progression, (k + 0.5) / max(1, len(lus)),
                        "traits couverts")
                morceaux, touches = rt.sans_chevauchement(
                    polys, tol, references=fermees)
                avancer(progression, (k + 0.8) / max(1, len(lus)),
                        "jonction")
                jointes = rt.joindre(morceaux, tol)
                change = bool(touches) or len(jointes) != len(polys)
                sortie.append({
                    'calque': calque, 'jetes': jetes,
                    'remplaces': [it for it, _p in ouvertes] if change
                    else [],
                    'nouvelles': jointes if change else [],
                    'avant': avant, 'doublons': doubles,
                    'raccourcis': touches,
                    'apres': (sum(len(p) for _i, p in gardes) - len(polys)
                              + (len(jointes) if change else len(polys))),
                    'fermees': len(fermees) + sum(
                        1 for p in (jointes if change else polys)
                        if rt.est_fermee(p, tol))})
            avancer(progression, 1.0, "nettoyage fini")
            return sortie

        resultats = executer(calcul) if executer is not None else calcul()
        if resultats is None:
            self.entity_info.emit("Nettoyage annulé")
            return None
        # 3. remplacer (fil de l'interface), en un seul geste annulable
        bilan = {'avant': 0, 'apres': 0, 'doublons': 0, 'raccourcis': 0,
                 'fermees': 0}
        self._pile_undo.beginMacro("Nettoyer le dessin")
        try:
            for r in resultats:
                for cle in bilan:
                    bilan[cle] += r[cle]
                if r['jetes'] or r['remplaces']:
                    self.remplacer_entites(r['jetes'] + r['remplaces'],
                                           r['nouvelles'], "Nettoyer",
                                           calque=r['calque'])
        finally:
            self._pile_undo.endMacro()
        bilan['message'] = rt.resume_nettoyage(bilan)
        self.entity_info.emit(bilan['message'])
        return bilan

    def _retouche_selection(self, calcul, texte: str, remplacer: bool):
        """Applique `calcul(polylignes) -> (polylignes, bilan)` à la
        sélection: les anciennes entités sont remplacées (congé,
        unir…) ou gardées (décaler)."""
        items = self.items_retouchables()
        if not items:
            self.entity_info.emit(f"{texte}: sélectionnez des tracés")
            return None
        resultat = calcul(items)
        if resultat is None:
            return None
        nouvelles, bilan = resultat
        if not nouvelles:
            self.entity_info.emit(f"{texte}: rien à produire")
            return bilan
        if remplacer:
            self.remplacer_entites(items, nouvelles, texte)
        else:
            self.remplacer_entites([], nouvelles, texte, calque='drawn')
        return bilan

    def decaler_selection(self, distance: float, coins: str = 'rond'):
        """Une copie décalée des tracés sélectionnés, posée au calque
        Dessin (les originaux restent)."""
        from src.core import retouche as rt

        def calcul(items):
            pls = [p for it in items for p in self._polylignes_machine(it)]
            return rt.decaler(pls, distance, coins), {}
        bilan = self._retouche_selection(calcul, "Décaler", False)
        if bilan is not None:
            self.entity_info.emit(
                f"Décalé de {distance:+.3f} mm — copie sélectionnée")
        return bilan

    def conge_selection(self, rayon: float, angles: str = 'tous'):
        from src.core import retouche as rt

        def calcul(items):
            pls = [p for it in items for p in self._polylignes_machine(it)]
            return rt.conge(pls, rayon, angles)
        bilan = self._retouche_selection(calcul, "Congé", True)
        if bilan is not None:
            note = (f", {bilan['reduits']} angle(s) réduit(s) faute de "
                    f"place" if bilan.get('reduits') else "")
            self.entity_info.emit(f"Congé R{rayon:g} ({angles}){note}")
        return bilan

    def chanfrein_selection(self, distance: float, angles: str = 'tous'):
        from src.core import retouche as rt

        def calcul(items):
            pls = [p for it in items for p in self._polylignes_machine(it)]
            return rt.chanfrein(pls, distance, angles)
        bilan = self._retouche_selection(calcul, "Chanfrein", True)
        if bilan is not None:
            note = (f", {bilan['reduits']} angle(s) réduit(s) faute de "
                    f"place" if bilan.get('reduits') else "")
            self.entity_info.emit(f"Chanfrein {distance:g} mm "
                                  f"({angles}){note}")
        return bilan

    # ──── Outils à clic: couper, départ, ajuster, prolonger, région ────

    #: outils qui agissent d'un clic sur un tracé (ou dans une région)
    OUTILS_CLIC = ('couper', 'depart', 'ajuster', 'prolonger', 'region')

    NOMS_OUTILS_CLIC = {
        'couper': "Couper au point",
        'depart': "Point de départ ici",
        'ajuster': "Ajuster (couper aux croisements)",
        'prolonger': "Prolonger jusqu'au trait suivant",
        'region': "Région par clic",
    }

    def _visibles_retouchables(self) -> list:
        return self.items_retouchables(
            [it for it in self._dxf_items if it.isVisible()])

    def _item_proche(self, scene_pos: QPointF, rayon: float = None):
        """Le tracé le plus proche du point (à quelques pixels), ou
        None."""
        import numpy as _np
        rayon = rayon if rayon is not None else 6.0 / max(self._zoom, 0.01)
        boite = QRectF(scene_pos.x() - rayon, scene_pos.y() - rayon,
                       2 * rayon, 2 * rayon)
        c = _np.array([scene_pos.x(), scene_pos.y()])
        meilleur, d_min = None, rayon
        for item in self._scene.items(
                boite, Qt.ItemSelectionMode.IntersectsItemBoundingRect):
            if id(item) not in self._item_layer or not item.isVisible():
                continue
            if not self.items_retouchables([item]):
                continue
            for P in self._geometrie_item(item)[0]:
                A, B = P[:-1], P[1:]
                AB = B - A
                L2 = _np.maximum(_np.einsum('ij,ij->i', AB, AB), 1e-24)
                t = _np.clip(_np.einsum('ij,ij->i', c - A, AB) / L2, 0, 1)
                d = float(_np.min(_np.hypot(*(A + t[:, None] * AB - c).T)))
                if d <= d_min:
                    meilleur, d_min = item, d
        return meilleur

    def _polylignes_autour(self, rect: QRectF, sauf) -> list:
        """Les tracés (coordonnées machine) des entités visibles qui
        touchent `rect`, sauf `sauf`."""
        sortie = []
        for item in self._scene.items(
                rect, Qt.ItemSelectionMode.IntersectsItemBoundingRect):
            if item is sauf or id(item) not in self._item_layer:
                continue
            if not item.isVisible() or not self.items_retouchables([item]):
                continue
            for P in self._geometrie_item(item)[0]:
                sortie.append([(float(x), -float(y)) for x, y in P])
        return sortie

    def _chemin_lisse(self, pl):
        """Une polyligne (machine) en chemin de scène, ses arcs
        retrouvés: un morceau de cercle coupé reste un arc."""
        from src.core import arcs as _arcs
        segments = _arcs.ajuster(pl, 0.002)
        if segments and any(sg[0] == 'A' for sg in segments):
            return self.chemin_depuis_segments(pl[0], segments)
        return list(pl)

    @staticmethod
    def _plus_proche(polylignes, point):
        """L'indice de la polyligne la plus proche du point."""
        from shapely.geometry import LineString, Point as SPoint
        meilleur, d_min = 0, float('inf')
        for i, pl in enumerate(polylignes):
            if len(pl) < 2:
                continue
            d = LineString(pl).distance(SPoint(point))
            if d < d_min:
                meilleur, d_min = i, d
        return meilleur

    def _outil_clic(self, outil: str, scene_pos: QPointF):
        """Un clic d'un outil de retouche. Rend ce qui a été produit
        (liste d'entités) ou None."""
        from src.core import retouche as rt
        p = (scene_pos.x(), -scene_pos.y())
        nom = self.NOMS_OUTILS_CLIC.get(outil, outil)
        if outil == 'region':
            tous = []
            for item in self._visibles_retouchables():
                for P in self._geometrie_item(item)[0]:
                    tous.append([(float(x), -float(y)) for x, y in P])
            contours = rt.region_au_point(tous, p)
            if not contours:
                self.entity_info.emit(f"{nom}: ce point n'est enfermé "
                                      f"par aucun tracé")
                return None
            chemin = QPainterPath()
            for c in contours:
                chemin.addPath(self._chemin_ferme(c))
            neufs = self.remplacer_entites([], [chemin], "Région",
                                           calque='drawn')
            self.entity_info.emit(
                f"Région: {len(contours)} contour(s), "
                f"aire {rt.region(contours).area:.2f} mm² — sélectionnée")
            return neufs
        item = self._item_proche(scene_pos)
        if item is None:
            self.entity_info.emit(f"{nom}: cliquez SUR un tracé")
            return None
        pls = self._polylignes_machine(item)
        if not pls:
            return None
        k = self._plus_proche(pls, p)
        pl, autres_du_meme = pls[k], pls[:k] + pls[k + 1:]
        if outil == 'couper':
            morceaux = rt.couper_au_point(pl, p)
            message = (f"Coupé: {len(morceaux)} morceau(x)"
                       if len(morceaux) > 1 else
                       "Contour ouvert au point")
        elif outil == 'depart':
            if not rt.est_fermee(pl):
                self.entity_info.emit(f"{nom}: un contour FERMÉ seulement")
                return None
            morceaux = [rt.depart_au_point(pl, p)]
            message = "Le contour commence ici (l'outil y entrera)"
        elif outil == 'ajuster':
            zone = item.sceneBoundingRect().adjusted(-1, -1, 1, 1)
            autres = self._polylignes_autour(zone, item) + autres_du_meme
            morceaux = rt.ajuster(pl, autres, p)
            if morceaux is None:
                self.entity_info.emit(f"{nom}: aucun croisement sur ce "
                                      f"tracé")
                return None
            message = f"Ajusté: {len(morceaux)} morceau(x) restant(s)"
        else:                                          # prolonger
            emprise = self.emprise_dessin() or item.sceneBoundingRect()
            zone = emprise.adjusted(-10, -10, 10, 10)
            autres = self._polylignes_autour(zone, item) + autres_du_meme
            long = max(zone.width(), zone.height()) * 1.5 + 10
            neuf = rt.prolonger(pl, autres, p, longueur_max=long)
            if neuf is None:
                self.entity_info.emit(f"{nom}: rien à rejoindre dans "
                                      f"cette direction")
                return None
            morceaux = [neuf]
            message = "Prolongé jusqu'au trait suivant"
        nouvelles = [self._chemin_lisse(m) for m in morceaux
                     if len(m) >= 2]
        nouvelles += [self._chemin_lisse(q) for q in autres_du_meme]
        neufs = self.remplacer_entites([item], nouvelles, nom)
        self.entity_info.emit(message + " — Ctrl+Z pour revenir")
        return neufs

    def _chemin_ferme(self, contour) -> QPainterPath:
        chemin = QPainterPath()
        pts = list(contour)
        if len(pts) > 2 and pts[0] == pts[-1]:
            pts = pts[:-1]
        chemin.moveTo(pts[0][0], -pts[0][1])
        for x, y in pts[1:]:
            chemin.lineTo(x, -y)
        chemin.closeSubpath()
        return chemin

    # ──── Points répartis, réseaux, mesures, formes ────

    def _cercle_dessine(self, cx: float, cy: float, r: float,
                        calque: str = 'drawn', stylo=None):
        """Un cercle (coordonnées machine) avec son centre marqué —
        « DXF to Op » y verra un perçage. Sans geste d'annulation (le
        geste est celui de l'appelant)."""
        item = self._scene.addEllipse(cx - r, -cy - r, 2 * r, 2 * r,
                                      QPen(stylo) if stylo is not None
                                      else QPen(QColor("#f9e2af"), 0.2))
        self._register_item(item, calque)
        centre, marqueurs = self._register_drawn_center(
            cx, -cy, r, "CIRCLE", emettre=False)
        self._item_metadata[id(item)] = centre
        self.attacher(item, *marqueurs)
        return item

    def _poser_lot(self, neufs, texte: str, anciens=()) -> list:
        """Des entités déjà posées deviennent UN geste annulable (les
        anciennes, s'il y en a, partent dans le même geste)."""
        from src.gui.dxf.canvas_undo import EchangerCommande
        lot = self._effacer_en_lot(list(anciens)) if anciens else []
        self._scene.clearSelection()
        self._selected_items = []
        for item in neufs:
            if self._item_layer.get(id(item)) != 'texte':
                self._surligner(item)
        self._extend_scene_rect()
        self._pile_undo.push(EchangerCommande(self, lot, neufs, texte))
        self.circles_detected.emit(self._detected_circles)
        self.selection_changed.emit(len(self.selection_courante()))
        return neufs

    def points_le_long_selection(self, nombre: int = 0, pas: float = 0.0,
                                 bouts: bool = True,
                                 diametre: float = 1.0) -> int:
        """Des cercles de Ø `diametre` répartis sur les tracés
        sélectionnés (leurs centres sont des perçages pour « DXF to
        Op »). Rend leur nombre."""
        from src.core import retouche as rt
        items = self.items_retouchables()
        if not items:
            self.entity_info.emit("Points le long: sélectionnez des tracés")
            return 0
        r = max(0.01, float(diametre) / 2.0)
        neufs = []
        for it in items:
            for pl in self._polylignes_machine(it):
                for x, y in rt.points_le_long(pl, nombre, pas, bouts):
                    neufs.append(self._cercle_dessine(x, y, r))
        if not neufs:
            self.entity_info.emit("Points le long: aucun point")
            return 0
        self._poser_lot(neufs, "Points le long")
        self.entity_info.emit(
            f"{len(neufs)} point(s) Ø{diametre:g} posés — « DXF to Op » "
            f"en fait des perçages")
        return len(neufs)

    def _chemin_scene_item(self, item) -> QPainterPath:
        """La géométrie d'une entité en chemin de scène."""
        if isinstance(item, QGraphicsLineItem):
            ch = QPainterPath()
            ln = item.line()
            ch.moveTo(ln.p1())
            ch.lineTo(ln.p2())
            return item.mapToScene(ch)
        if isinstance(item, QGraphicsRectItem):
            ch = QPainterPath()
            ch.addRect(item.rect())
            return item.mapToScene(ch)
        if isinstance(item, QGraphicsEllipseItem):
            ch = QPainterPath()
            ch.addEllipse(item.rect())
            return item.mapToScene(ch)
        if isinstance(item, QGraphicsPolygonItem):
            ch = QPainterPath()
            ch.addPolygon(item.polygon())
            ch.closeSubpath()
            return item.mapToScene(ch)
        return item.mapToScene(item.path())

    def reseau_selection(self, transformations) -> int:
        """Des copies de la sélection, une par transformation affine
        (coordonnées machine, src.core.retouche.reseau_*). Les cercles
        restent des cercles, avec leur centre. Rend le nombre de
        copies."""
        from PySide6.QtGui import QTransform
        items = self.items_retouchables()
        if not items or not transformations:
            self.entity_info.emit("Réseau: sélectionnez des tracés")
            return 0
        neufs = []
        for t in transformations:
            a, b, c, d, e, f = t
            # machine → scène: Y change de signe
            q = QTransform(a, -b, -c, d, e, -f)
            for it in items:
                try:
                    stylo = QPen(self._original_pens.get(id(it))
                                 or it.pen())
                except (AttributeError, RuntimeError, TypeError):
                    stylo = QPen(QColor("#f9e2af"), 0.2)
                if isinstance(it, QGraphicsEllipseItem) and abs(
                        it.rect().width() - it.rect().height()) < 1e-9:
                    centre = it.mapToScene(it.rect().center())
                    x, y = centre.x(), -centre.y()
                    nx_, ny_ = a * x + c * y + e, b * x + d * y + f
                    neufs.append(self._cercle_dessine(
                        nx_, ny_, it.rect().width() / 2.0, stylo=stylo))
                    continue
                chemin = q.map(self._chemin_scene_item(it))
                neufs.append(self._nouvelle_entite(chemin, 'drawn', stylo))
        self._poser_lot(neufs, "Réseau")
        self.entity_info.emit(f"Réseau: {len(neufs)} copie(s)")
        return len(neufs)

    def mesurer_selection(self) -> dict:
        """Longueur, contours, aire, emprise de la sélection (ou du
        dessin visible sans sélection)."""
        from src.core import retouche as rt
        items = self.items_retouchables() or self._visibles_retouchables()
        pls = [pl for it in items for pl in self._polylignes_machine(it)]
        m = rt.mesures(pls)
        m['entites'] = len(items)
        m['message'] = rt.resume_mesures(m)
        self.entity_info.emit(m['message'].replace("\n", " · "))
        return m

    def reconnaitre_selection(self, tolerance: float = 0.05) -> dict:
        """Les tracés sélectionnés qui sont des cercles, rectangles,
        ellipses, droites ou arcs deviennent ces entités EXACTES. Rend
        le compte par genre."""
        from src.core import formes as fm
        items = self.items_retouchables()
        compte = {}
        anciens, neufs = [], []
        for it in items:
            if isinstance(it, (QGraphicsEllipseItem, QGraphicsLineItem,
                               QGraphicsRectItem)):
                continue                       # déjà exacts
            pls = self._polylignes_machine(it)
            if len(pls) != 1:
                continue
            forme = fm.reconnaitre(pls[0], tolerance)
            if forme is None:
                continue
            calque = self._item_layer.get(id(it), 'drawn')
            try:
                stylo = QPen(self._original_pens.get(id(it)) or it.pen())
            except (AttributeError, RuntimeError, TypeError):
                stylo = QPen(QColor("#f9e2af"), 0.2)
            neuf = self._entite_de_forme(forme, calque, stylo)
            if neuf is None:
                continue
            source = getattr(self, '_item_source', {}).get(id(it))
            if source and calque == 'dxf':
                self._item_source[id(neuf)] = source
            anciens.append(it)
            neufs.append(neuf)
            compte[forme['genre']] = compte.get(forme['genre'], 0) + 1
        if not neufs:
            self.entity_info.emit("Reconnaître: aucune forme reconnue")
            return compte
        self._poser_lot(neufs, "Reconnaître les formes", anciens)
        texte = ", ".join(f"{n} {fm.NOMS.get(g, g)}(s)"
                          for g, n in sorted(compte.items()))
        self.entity_info.emit(f"Reconnu: {texte}")
        return compte

    def _entite_de_forme(self, forme: dict, calque: str, stylo):
        g = forme['genre']
        if g == 'cercle':
            return self._cercle_dessine(forme['cx'], forme['cy'],
                                        forme['r'], calque, stylo)
        if g == 'ligne':
            (x0, y0), (x1, y1) = forme['p0'], forme['p1']
            item = self._scene.addLine(x0, -y0, x1, -y1, QPen(stylo))
            self._register_item(item, calque)
            return item
        if g == 'rectangle' and abs(forme['angle']) < 1e-6:
            w, h = forme['largeur'], forme['hauteur']
            item = self._scene.addRect(
                QRectF(forme['cx'] - w / 2, -forme['cy'] - h / 2, w, h),
                QPen(stylo))
            self._register_item(item, calque)
            return item
        if g == 'rectangle':
            a = math.radians(forme['angle'])
            c, s = math.cos(a), math.sin(a)
            w, h = forme['largeur'] / 2, forme['hauteur'] / 2
            coins = [(forme['cx'] + u * c - v * s, forme['cy'] + u * s + v * c)
                     for u, v in ((-w, -h), (w, -h), (w, h), (-w, h))]
            return self._nouvelle_entite(coins + coins[:1], calque, stylo)
        if g == 'ellipse':
            a, b = forme['a'], forme['b']
            item = self._scene.addEllipse(
                QRectF(forme['cx'] - a, -forme['cy'] - b, 2 * a, 2 * b),
                QPen(stylo))
            item.setTransformOriginPoint(forme['cx'], -forme['cy'])
            item.setRotation(-forme['angle'])
            self._register_item(item, calque)
            return item
        if g == 'arc':
            segment = ('A', forme['fin'], (forme['cx'], forme['cy']),
                       forme['trigo'])
            from src.core import arcs as _arcs
            depart = forme['depart']
            if abs(_arcs.balayage(depart, segment)) > math.pi:
                # plus d'un demi-tour: en deux arcs
                return None
            return self._nouvelle_entite(
                self.chemin_depuis_segments(depart, [segment]), calque,
                stylo)
        return None

    # ──── Contraintes géométriques (src.core.contraintes) ────

    @staticmethod
    def _segments_item(item) -> list:
        """Les sommets (scène) d'une entité à segments, par indice
        d'élément; None si elle n'en a pas (courbes, rectangle)."""
        try:
            if isinstance(item, QGraphicsLineItem):
                ln = item.line()
                return [item.mapToScene(ln.p1()), item.mapToScene(ln.p2())]
            if isinstance(item, QGraphicsPathItem):
                ch = item.path()
                pts = []
                for k in range(ch.elementCount()):
                    e = ch.elementAt(k)
                    if e.type not in (QPainterPath.ElementType.MoveToElement,
                                      QPainterPath.ElementType.LineToElement):
                        return None
                    pts.append(item.mapToScene(QPointF(e.x, e.y)))
                return pts
        except RuntimeError:
            return None
        return None

    def _cercle_item(self, item):
        if isinstance(item, QGraphicsEllipseItem):
            r = item.rect()
            if abs(r.width() - r.height()) < 1e-6:
                c = item.mapToScene(r.center())
                return c, r.width() / 2.0
        return None

    def _ref_sous(self, genre_ref: str, scene_pos: QPointF):
        """Ce que le clic désigne: ('ligne', entité, k), ('point',
        entité, k) ou ('cercle', entité) — ou None."""
        item = self._item_proche(scene_pos)
        if item is None:
            return None
        if genre_ref == 'cercle':
            return (item,) if self._cercle_item(item) else None
        pts = self._segments_item(item)
        if not pts:
            return None
        if genre_ref == 'point':
            k = min(range(len(pts)), key=lambda i: QLineF(
                pts[i], scene_pos).length())
            return (item, k)
        # un trait: le segment le plus proche (pas à cheval sur deux
        # sous-chemins)
        meilleur = None
        for k in range(len(pts) - 1):
            if isinstance(item, QGraphicsPathItem) and item.path().elementAt(
                    k + 1).type == QPainterPath.ElementType.MoveToElement:
                continue
            a, b = pts[k], pts[k + 1]
            ab = b - a
            l2 = ab.x() ** 2 + ab.y() ** 2
            if l2 <= 1e-18:
                continue
            t = max(0.0, min(1.0, ((scene_pos.x() - a.x()) * ab.x()
                                   + (scene_pos.y() - a.y()) * ab.y()) / l2))
            d = QLineF(a + ab * t, scene_pos).length()
            if meilleur is None or d < meilleur[0]:
                meilleur = (d, k)
        return (item, meilleur[1]) if meilleur else None

    def _clic_contrainte(self, genre: str, scene_pos: QPointF):
        from src.core import contraintes as ct
        voulus, a_valeur, _s = ct.GENRES[genre]
        n = len(self._choix_contrainte)
        quoi = voulus[n]
        ref = self._ref_sous(quoi, scene_pos)
        if ref is None:
            self.entity_info.emit(
                f"{ct.NOMS[genre]}: cliquez sur "
                + {'ligne': "un trait (ligne ou polyligne)",
                   'point': "un sommet", 'cercle': "un cercle"}[quoi])
            return None
        self._choix_contrainte.append(ref)
        if len(self._choix_contrainte) < len(voulus):
            self.entity_info.emit(f"{ct.NOMS[genre]}: puis "
                                  f"{voulus[len(self._choix_contrainte)]}")
            return None
        refs = list(self._choix_contrainte)
        self._choix_contrainte = []
        valeur = None
        if a_valeur:
            actuelle = self._mesure_refs(genre, refs)
            valeur = (self.demander_valeur(genre, actuelle)
                      if callable(self.demander_valeur) else actuelle)
            if valeur is None:
                self.entity_info.emit("Contrainte abandonnée")
                return None
        return self.ajouter_contrainte(genre, refs, valeur)

    def _mesure_refs(self, genre, refs) -> float:
        if genre == 'rayon':
            return self._cercle_item(refs[0][0])[1]
        if genre == 'longueur':
            pts = self._segments_item(refs[0][0])
            k = refs[0][1]
            return QLineF(pts[k], pts[k + 1]).length()
        a = self._segments_item(refs[0][0])[refs[0][1]]
        b = self._segments_item(refs[1][0])[refs[1][1]]
        return QLineF(a, b).length()

    def ajouter_contrainte(self, genre: str, refs, valeur=None) -> bool:
        """Une contrainte de plus, et le dessin résolu. Rend vrai si
        toutes les contraintes sont tenues."""
        from src.core import contraintes as ct
        self._contraintes.append({'genre': genre, 'refs': list(refs),
                                  'valeur': valeur})
        ok, reste = self.resoudre_contraintes()
        self.entity_info.emit(
            f"{ct.NOMS[genre]}" + (f" = {valeur:g}" if valeur is not None
                                   else "")
            + (" — tenue" if ok else
               f" — IMPOSSIBLE à tenir (écart {reste:.3g}): Ctrl+Z"))
        return ok

    def _contraintes_de(self, item) -> list:
        return [c for c in self._contraintes
                if any(r[0] is item for r in c['refs'])]

    def resoudre_contraintes(self, prioritaires=()) -> tuple:
        """Résout toutes les contraintes et pose le dessin qui en sort
        (un geste annulable). Rend (tenu ?, écart restant)."""
        from src.core import contraintes as ct
        self._contraintes = [c for c in self._contraintes
                             if all(self._vivant(r[0]) for r in c['refs'])]
        if not self._contraintes:
            self._dessiner_glyphes()
            return True, 0.0
        s = ct.Systeme()
        carte_pt = {}
        carte_c = {}
        items = []
        for c in self._contraintes:
            for r in c['refs']:
                if r[0] not in items:
                    items.append(r[0])
        for item in items:
            cercle = self._cercle_item(item)
            if cercle is not None:
                carte_c[id(item)] = s.cercle(cercle[0].x(), cercle[0].y(),
                                             cercle[1])
                continue
            pts = self._segments_item(item) or []
            for k, p in enumerate(pts):
                jum = self._jumeaux(item, k)
                if k != jum[0] and (id(item), jum[0]) in carte_pt:
                    carte_pt[(id(item), k)] = carte_pt[(id(item), jum[0])]
                else:
                    carte_pt[(id(item), k)] = s.point(p.x(), p.y())
        for c in self._contraintes:
            genre, refs = c['genre'], c['refs']
            voulus = ct.GENRES[genre][0]
            sys_refs = []
            for quoi, r in zip(voulus, refs):
                if quoi == 'ligne':
                    sys_refs += [carte_pt[(id(r[0]), r[1])],
                                 carte_pt[(id(r[0]), r[1] + 1)]]
                elif quoi == 'point':
                    sys_refs.append(carte_pt[(id(r[0]), r[1])])
                else:
                    sys_refs.append(carte_c[id(r[0])])
            s.ajouter(genre, sys_refs, c['valeur'])
        prio = [carte_pt[(id(it), k)] for it, k in prioritaires
                if (id(it), k) in carte_pt]
        ok, reste = s.resoudre(prio)
        # poser le dessin résolu
        from src.gui.dxf.canvas_undo import GeometrieCommande
        self._pile_undo.beginMacro("Contraintes")
        try:
            for item in items:
                avant = self._geometrie_ou_rect(item)
                if id(item) in carte_c:
                    ci, r = s.cercles[carte_c[id(item)]]
                    cx, cy = s.points[int(ci)]
                    centre = item.mapFromScene(QPointF(cx, cy))
                    neuf = QRectF(centre.x() - r, centre.y() - r, 2 * r, 2 * r)
                    item.setRect(neuf)
                    apres = QRectF(neuf)
                else:
                    pts = self._segments_item(item) or []
                    if isinstance(item, QGraphicsLineItem):
                        p1 = s.points[carte_pt[(id(item), 0)]]
                        p2 = s.points[carte_pt[(id(item), 1)]]
                        item.setLine(QLineF(item.mapFromScene(QPointF(*p1)),
                                            item.mapFromScene(QPointF(*p2))))
                    else:
                        ch = item.path()
                        for k in range(len(pts)):
                            x, y = s.points[carte_pt[(id(item), k)]]
                            loc = item.mapFromScene(QPointF(x, y))
                            ch.setElementPositionAt(k, loc.x(), loc.y())
                        item.setPath(ch)
                    apres = self._geometrie(item)
                self._geo_cache.pop(id(item), None)
                self._pile_undo.push(GeometrieCommande(
                    self, item, avant, apres, "Contraintes"))
        finally:
            self._pile_undo.endMacro()
        self._dessiner_glyphes()
        if self._poignees:
            self._maj_poignees()
        return ok, reste

    def _geometrie_ou_rect(self, item):
        if isinstance(item, QGraphicsEllipseItem):
            return QRectF(item.rect())
        return self._geometrie(item)

    @staticmethod
    def _vivant(item) -> bool:
        try:
            return item.scene() is not None
        except RuntimeError:
            return False

    def effacer_contraintes(self) -> int:
        n = len(self._contraintes)
        self._contraintes = []
        self._choix_contrainte = []
        self._dessiner_glyphes()
        self.entity_info.emit(f"{n} contrainte(s) effacée(s)")
        return n

    def montrer_glyphes(self, oui: bool) -> None:
        self.glyphes_visibles = bool(oui)
        self._dessiner_glyphes()

    def _dessiner_glyphes(self) -> None:
        """Les symboles des contraintes (H, V, ∥, ⊥, =, L=…, R=…) près
        de ce qu'elles tiennent — repères d'écran, pas des entités."""
        from PySide6.QtWidgets import QGraphicsSimpleTextItem
        from src.core import contraintes as ct
        for g in self._glyphes_contraintes:
            try:
                if g.scene() is not None:
                    self._scene.removeItem(g)
            except RuntimeError:
                pass
        self._glyphes_contraintes = []
        if not self.glyphes_visibles:
            return
        decalages = {}
        for c in self._contraintes:
            r = c['refs'][0]
            try:
                cercle = self._cercle_item(r[0])
                if cercle is not None:
                    pos = cercle[0] + QPointF(cercle[1], 0)
                else:
                    pts = self._segments_item(r[0])
                    if ct.GENRES[c['genre']][0][0] == 'ligne':
                        pos = (pts[r[1]] + pts[r[1] + 1]) / 2.0
                    else:
                        pos = pts[r[1]]
            except (RuntimeError, IndexError, TypeError):
                continue
            cle = (round(pos.x(), 3), round(pos.y(), 3))
            n = decalages.get(cle, 0)
            decalages[cle] = n + 1
            g = QGraphicsSimpleTextItem(ct.symbole(c['genre'], c['valeur']))
            g.setBrush(QBrush(QColor("#f9e2af")))
            g.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations,
                      True)
            g.setZValue(1e6 - 2)
            g.setPos(pos)
            # décalé en PIXELS (l'entité ignore le zoom)
            g.setTransform(QTransform.fromTranslate(4 + 14 * n, -14))
            g.setToolTip(ct.NOMS[c['genre']])
            self._scene.addItem(g)
            self._glyphes_contraintes.append(g)

    # ──── Cotes ────

    #: hauteur du texte des cotes, en mm
    hauteur_cote = 2.5

    def _cercle_sous(self, scene_pos: QPointF):
        """(cx, cy, r) machine du cercle ou de l'arc cliqué, ou None."""
        from src.core import formes as fm
        item = self._item_proche(scene_pos)
        if item is None:
            return None
        if isinstance(item, QGraphicsEllipseItem):
            r = item.rect()
            if abs(r.width() - r.height()) < 1e-6:
                c = item.mapToScene(r.center())
                return c.x(), -c.y(), r.width() / 2.0
        for pl in self._polylignes_machine(item):
            forme = fm.reconnaitre(pl, 0.02)
            if forme and forme['genre'] in ('cercle', 'arc'):
                return forme['cx'], forme['cy'], forme['r']
        return None

    def _geometrie_cote(self, genre: str, points, cercle=None):
        """La cote (src.core.cotation) de points de scène."""
        from src.core import cotation as ct
        m = [(p.x(), -p.y()) for p in points]
        h = self.hauteur_cote
        if genre == 'cote_lin' and len(m) >= 3:
            return ct.cote_lineaire(m[0], m[1], m[2], h)
        if genre == 'cote_ali' and len(m) >= 3:
            return ct.cote_alignee(m[0], m[1], m[2], h)
        if genre in ('cote_ray', 'cote_dia') and cercle and m:
            return ct.cote_rayon(cercle[:2], cercle[2], m[-1],
                                 genre == 'cote_dia', h)
        if genre == 'cote_ang' and len(m) >= 3:
            return ct.cote_angle(m[0], m[1], m[2], h)
        return None

    def _chemin_traits(self, traits) -> QPainterPath:
        chemin = QPainterPath()
        for t in traits:
            if len(t) < 2:
                continue
            chemin.moveTo(t[0][0], -t[0][1])
            for x, y in t[1:]:
                chemin.lineTo(x, -y)
        return chemin

    def _apercu_cote(self, courant: QPointF):
        pts = list(self._draw_points)
        genre = self._draw_tool
        if genre in ('cote_lin', 'cote_ali', 'cote_ang') and len(pts) == 2:
            cote = self._geometrie_cote(genre, pts + [courant])
            return self._chemin_traits(cote['traits']) if cote else None
        if pts:
            chemin = QPainterPath(pts[0])
            for q in pts[1:] + [courant]:
                chemin.lineTo(q)
            return chemin
        return None

    def _clic_cote(self, scene_pos: QPointF):
        from src.core import cotation as ct
        genre = self._draw_tool
        if genre in ('cote_ray', 'cote_dia'):
            cercle = self._cercle_sous(scene_pos)
            if cercle is None:
                self.entity_info.emit(f"{ct.GENRES[genre]}: cliquez sur "
                                      f"un cercle ou un arc")
                return None
            return self.poser_cote(genre, [scene_pos], cercle)
        self._draw_points.append(scene_pos)
        if len(self._draw_points) < ct.CLICS.get(genre, 3):
            aide = {1: "deuxième point", 2: "placement de la cote"}
            if genre == 'cote_ang':
                aide = {1: "point sur le 1er côté",
                        2: "point sur le 2e côté"}
            self.entity_info.emit(f"{ct.GENRES[genre]}: "
                                  f"{aide.get(len(self._draw_points), '')}")
            return None
        pts = list(self._draw_points)
        self._draw_points.clear()
        if self._temp_item:
            self._scene.removeItem(self._temp_item)
            self._temp_item = None
        return self.poser_cote(genre, pts)

    def poser_cote(self, genre: str, points, cercle=None) -> list:
        """Une cote au calque Annotations: ses traits et son texte, en
        un groupe (ils se déplacent ensemble), un geste annulable."""
        from src.core import cotation as ct
        cote = self._geometrie_cote(genre, points, cercle)
        if cote is None:
            return []
        stylo = QPen(QColor("#a6e3a1"), 0.15)
        trait = self._scene.addPath(self._chemin_traits(cote['traits']),
                                    stylo)
        trait.setData(1, 'cote')
        self._register_item(trait, 'texte')
        texte = self.add_text(cote['texte'], 0.0, 0.0, self.hauteur_cote)
        neufs = [trait]
        if texte is not None:
            self._placer_texte_cote(texte, cote['centre'], cote['angle'])
            neufs.append(texte)
        cle = f"cote_{id(trait)}"
        self._groupes[cle] = list(neufs)
        for it in neufs:
            self._groupe_de[id(it)] = cle
        self._poser_lot(neufs, ct.GENRES.get(genre, "Cote"))
        self.entity_info.emit(f"{ct.GENRES.get(genre, 'Cote')}: "
                              f"{cote['texte']}")
        return neufs

    @staticmethod
    def _placer_texte_cote(item, centre, angle: float) -> None:
        """Le texte centré sur `centre` (machine), tourné de `angle`
        degrés (sens trigo, comme à l'export)."""
        r = item.boundingRect()
        item.setTransformOriginPoint(r.center())
        item.setRotation(-float(angle))
        item.setPos(centre[0] - r.center().x(), -centre[1] - r.center().y())
        item.setData(5, 'cote')
        item.setData(6, (float(centre[0]), float(centre[1]), float(angle)))

    def lisser_en_arcs_selection(self, tolerance: float = 0.05):
        """Les tracés sélectionnés refaits en droites et ARCS tangents
        à `tolerance` mm près (src.core.arcs): un contour vectorisé en
        escalier devient lisse, un cercle en soixante cordes redevient
        un cercle."""
        from src.core import arcs as _arcs
        bilan = {'avant': 0, 'droites': 0, 'arcs': 0}

        def calcul(items):
            chemins = []
            for it in items:
                for pl in self._polylignes_machine(it):
                    segments = _arcs.ajuster(pl, tolerance)
                    if not segments:
                        continue
                    bilan['avant'] += len(pl)
                    d, a = _arcs.compte(segments)
                    bilan['droites'] += d
                    bilan['arcs'] += a
                    chemins.append(self.chemin_depuis_segments(
                        pl[0], segments))
            return chemins, bilan
        res = self._retouche_selection(calcul, "Lisser en arcs", True)
        if res is not None:
            self.entity_info.emit(
                f"Lissé en arcs: {bilan['avant']} sommets → "
                f"{bilan['droites']} droite(s) + {bilan['arcs']} arc(s)")
        return res

    @staticmethod
    def chemin_depuis_segments(depart, segments) -> QPainterPath:
        """Droites et arcs (coordonnées machine, src.core.arcs) en
        chemin Qt de scène — les arcs restent des arcs."""
        from src.core import arcs as _arcs
        chemin = QPainterPath()
        chemin.moveTo(depart[0], -depart[1])
        cour = (float(depart[0]), float(depart[1]))
        for sg in segments:
            if sg[0] == 'L':
                chemin.lineTo(sg[1][0], -sg[1][1])
            else:
                _g, fin, (cx, cy), _t = sg
                r = math.hypot(cour[0] - cx, cour[1] - cy)
                a0 = math.degrees(math.atan2(cour[1] - cy, cour[0] - cx))
                b = math.degrees(_arcs.balayage(cour, sg))
                chemin.arcTo(QRectF(cx - r, -cy - r, 2 * r, 2 * r), a0, b)
            cour = (float(sg[1][0]), float(sg[1][1]))
        if math.dist(cour, (float(depart[0]), float(depart[1]))) <= 1e-9 \
                and len(segments) >= 2:
            chemin.closeSubpath()
        return chemin

    # ──── Poignées d'édition des sommets ────

    #: une entité de plus de sommets que ça n'a pas de poignées (un
    #: logo importé en mille points: on ne les montre pas)
    POIGNEES_MAX = 400

    def _sommets_editables(self, item):
        """Les sommets d'une entité qu'on peut prendre aux poignées:
        [(indice d'élément, QPointF scène)], ou None si elle n'en a
        pas (courbes, rectangle, cercle, trop de sommets)."""
        try:
            if isinstance(item, QGraphicsLineItem):
                ln = item.line()
                return [(0, item.mapToScene(ln.p1())),
                        (1, item.mapToScene(ln.p2()))]
            if not isinstance(item, QGraphicsPathItem):
                return None
            chemin = item.path()
            n = chemin.elementCount()
            if n < 2 or n > self.POIGNEES_MAX:
                return None
            sortie = []
            for k in range(n):
                e = chemin.elementAt(k)
                if e.type not in (QPainterPath.ElementType.MoveToElement,
                                  QPainterPath.ElementType.LineToElement):
                    return None
                sortie.append((k, item.mapToScene(QPointF(e.x, e.y))))
            return sortie
        except RuntimeError:
            return None

    def _jumeaux(self, item, k: int) -> list:
        """L'élément k et celui qui le double (le point de fermeture
        d'un sous-chemin fermé est le point de départ)."""
        if not isinstance(item, QGraphicsPathItem):
            return [k]
        chemin = item.path()
        n = chemin.elementCount()
        # les sous-chemins: de MoveTo en MoveTo
        debuts = [i for i in range(n) if chemin.elementAt(i).type
                  == QPainterPath.ElementType.MoveToElement] + [n]
        for a, b in zip(debuts, debuts[1:]):
            if not a <= k < b:
                continue
            ea, eb = chemin.elementAt(a), chemin.elementAt(b - 1)
            ferme = b - 1 > a and abs(ea.x - eb.x) < 1e-9 \
                and abs(ea.y - eb.y) < 1e-9
            if ferme and k in (a, b - 1):
                return [a, b - 1]
            return [k]
        return [k]

    def _maj_poignees(self) -> None:
        """Une seule entité sélectionnée, à sommets: ses poignées."""
        for p in self._poignees:
            try:
                if p.scene() is not None:
                    self._scene.removeItem(p)
            except RuntimeError:
                pass
        self._poignees = []
        self._poignee_item = None
        try:
            sel = self.selection_courante()
        except RuntimeError:
            return
        if len(sel) != 1 or self._item_layer.get(id(sel[0])) not in (
                'dxf', 'drawn'):
            return
        item = sel[0]
        sommets = self._sommets_editables(item)
        if not sommets:
            return
        self._poignee_item = item
        vus = set()
        for k, pt in sommets:
            jum = tuple(self._jumeaux(item, k))
            if jum in vus:
                continue
            vus.add(jum)
            p = QGraphicsRectItem(-3.5, -3.5, 7, 7)
            p.setFlag(
                QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations,
                True)
            stylo = QPen(QColor("#89dceb"), 1.2)
            stylo.setCosmetic(True)
            p.setPen(stylo)
            p.setBrush(QBrush(QColor(17, 17, 27, 200)))
            p.setZValue(1e6 - 1)
            p.setPos(pt)
            p.setData(0, 'poignee')
            p.setData(1, k)
            p.setToolTip("Glisser: déplacer le sommet · Ctrl+clic: le "
                         "supprimer · double-clic sur un côté: en ajouter")
            self._scene.addItem(p)
            self._poignees.append(p)

    def _poignee_sous(self, scene_pos: QPointF):
        """L'indice d'élément de la poignée sous la souris, ou None."""
        rayon = 6.0 / max(self._zoom, 0.01)
        meilleur, k_meilleur = rayon, None
        for p in self._poignees:
            try:
                d = QLineF(p.pos(), scene_pos).length()
            except RuntimeError:
                continue
            if d <= meilleur:
                meilleur, k_meilleur = d, int(p.data(1))
        return k_meilleur

    def _geometrie(self, item):
        """Ce qu'on rend à l'annulation: le chemin, ou la ligne."""
        if isinstance(item, QGraphicsLineItem):
            return QLineF(item.line())
        return QPainterPath(item.path())

    def _poser_geometrie(self, item, geometrie) -> None:
        try:
            if isinstance(item, QGraphicsLineItem):
                item.setLine(geometrie)
            elif isinstance(item, QGraphicsEllipseItem):
                item.setRect(geometrie)
            else:
                item.setPath(geometrie)
        except RuntimeError:
            return
        self._geo_cache.pop(id(item), None)
        self._maj_poignees()
        if getattr(self, '_contraintes', None):
            self._dessiner_glyphes()

    def _commencer_poignee(self, k: int) -> None:
        item = self._poignee_item
        if item is None:
            return
        self._poignee_drag = {'item': item,
                              'indices': self._jumeaux(item, k),
                              'avant': self._geometrie(item)}

    def deplacer_sommet(self, scene_pos: QPointF) -> None:
        """Le sommet pris va en `scene_pos` (et son jumeau)."""
        d = self._poignee_drag
        if d is None:
            return
        item = d['item']
        try:
            local = item.mapFromScene(scene_pos)
            if isinstance(item, QGraphicsLineItem):
                ln = QLineF(item.line())
                if d['indices'][0] == 0:
                    ln.setP1(local)
                else:
                    ln.setP2(local)
                item.setLine(ln)
            else:
                chemin = item.path()
                for k in d['indices']:
                    chemin.setElementPositionAt(k, local.x(), local.y())
                item.setPath(chemin)
        except RuntimeError:
            self._poignee_drag = None
            return
        self._geo_cache.pop(id(item), None)
        for p in self._poignees:
            if int(p.data(1)) in d['indices']:
                p.setPos(scene_pos)

    def finir_poignee(self) -> None:
        """Le sommet est posé: un geste annulable."""
        d, self._poignee_drag = self._poignee_drag, None
        self._montrer_prise(None)
        if d is None:
            return
        from src.gui.dxf.canvas_undo import GeometrieCommande
        apres = self._geometrie(d['item'])
        lie = self._contraintes_de(d['item'])
        if lie:
            self._pile_undo.beginMacro("Déplacer un sommet")
        self._pile_undo.push(GeometrieCommande(
            self, d['item'], d['avant'], apres, "Déplacer un sommet"))
        if lie:
            # le dessin garde ses intentions: le sommet posé bouge peu
            self.resoudre_contraintes(
                prioritaires=[(d['item'], k) for k in d['indices']])
            self._pile_undo.endMacro()
        self._maj_poignees()
        self.entity_info.emit("Sommet déplacé — Ctrl+Z pour revenir")

    def _polyligne_elements(self, chemin: QPainterPath):
        """Les sous-chemins d'un chemin à segments: [(points, fermé)]
        avec, pour chaque point, son indice d'élément."""
        n = chemin.elementCount()
        debuts = [i for i in range(n) if chemin.elementAt(i).type
                  == QPainterPath.ElementType.MoveToElement] + [n]
        sortie = []
        for a, b in zip(debuts, debuts[1:]):
            pts = [(k, QPointF(chemin.elementAt(k).x,
                               chemin.elementAt(k).y)) for k in range(a, b)]
            ferme = len(pts) > 2 and QLineF(pts[0][1], pts[-1][1]
                                            ).length() < 1e-9
            if ferme:
                pts = pts[:-1]
            sortie.append((pts, ferme))
        return sortie

    @staticmethod
    def _chemin_depuis(sous_chemins) -> QPainterPath:
        chemin = QPainterPath()
        for pts, ferme in sous_chemins:
            if len(pts) < 2:
                continue
            chemin.moveTo(pts[0])
            for q in pts[1:]:
                chemin.lineTo(q)
            if ferme and len(pts) >= 3:
                chemin.closeSubpath()
        return chemin

    def supprimer_sommet(self, k: int) -> bool:
        """Ctrl+clic sur une poignée: le sommet part (le tracé garde au
        moins deux points, un contour fermé au moins trois)."""
        item = self._poignee_item
        if not isinstance(item, QGraphicsPathItem):
            return False
        avant = self._geometrie(item)
        sous = []
        fait = False
        for pts, ferme in self._polyligne_elements(item.path()):
            garde = [q for (i, q) in pts
                     if not (i == k or (ferme and k in self._jumeaux(
                         item, i)))]
            if len(garde) != len(pts) and len(garde) >= (3 if ferme else 2):
                fait = True
                sous.append((garde, ferme))
            else:
                sous.append(([q for _i, q in pts], ferme))
        if not fait:
            return False
        from src.gui.dxf.canvas_undo import GeometrieCommande
        apres = self._chemin_depuis(sous)
        self._poser_geometrie(item, apres)
        self._pile_undo.push(GeometrieCommande(
            self, item, avant, QPainterPath(apres), "Supprimer un sommet"))
        self.entity_info.emit("Sommet supprimé — Ctrl+Z pour revenir")
        return True

    def ajouter_sommet(self, scene_pos: QPointF) -> bool:
        """Double-clic sur un côté de l'entité en édition: un sommet de
        plus, là (accroché aux points du dessin)."""
        item = self._poignee_item
        if not isinstance(item, QGraphicsPathItem):
            return False
        rayon = 6.0 / max(self._zoom, 0.01)
        local = item.mapFromScene(scene_pos)
        meilleur = None
        sous = self._polyligne_elements(item.path())
        for s_i, (pts, ferme) in enumerate(sous):
            suite = [q for _i, q in pts] + ([pts[0][1]] if ferme else [])
            for j in range(len(suite) - 1):
                a, b = suite[j], suite[j + 1]
                ab = b - a
                l2 = ab.x() ** 2 + ab.y() ** 2
                if l2 <= 1e-18:
                    continue
                t = ((local.x() - a.x()) * ab.x()
                     + (local.y() - a.y()) * ab.y()) / l2
                if not 0.0 < t < 1.0:
                    continue
                proj = a + ab * t
                d = QLineF(proj, local).length()
                if d <= rayon and (meilleur is None or d < meilleur[0]):
                    meilleur = (d, s_i, j, proj)
        if meilleur is None:
            return False
        _d, s_i, j, proj = meilleur
        avant = self._geometrie(item)
        neuf = []
        for i, (pts, ferme) in enumerate(sous):
            liste = [q for _k, q in pts]
            if i == s_i:
                liste.insert(j + 1, proj)
            neuf.append((liste, ferme))
        from src.gui.dxf.canvas_undo import GeometrieCommande
        apres = self._chemin_depuis(neuf)
        self._poser_geometrie(item, apres)
        self._pile_undo.push(GeometrieCommande(
            self, item, avant, QPainterPath(apres), "Ajouter un sommet"))
        self.entity_info.emit("Sommet ajouté — glissez sa poignée")
        return True

    def booleen_selection(self, operation: str):
        """Unir, soustraire, intersection, exclure: chaque entité
        sélectionnée est une surface (ses contours fermés)."""
        from src.core import retouche as rt

        def calcul(items):
            groupes = [self._polylignes_machine(it) for it in items]
            if rt.surfaces_de(groupes) < 2:
                self.entity_info.emit(
                    f"{rt.OPERATIONS_BOOLEENNES[operation]}: il faut au "
                    f"moins deux contours FERMÉS")
                return None
            return rt.booleen(groupes, operation), {}
        texte = rt.OPERATIONS_BOOLEENNES[operation].split(' (')[0]
        bilan = self._retouche_selection(calcul, texte, True)
        if bilan is not None:
            self.entity_info.emit(f"{texte}: fait")
        return bilan

    def _handle_select_click(self, scene_pos: QPointF,
                             ajouter: bool = False):
        """Clic en mode sélection: prend l'entité la plus proche.

        Dans le VIDE, il désélectionne — sans quoi, sur un dessin
        dense, plus rien ne rendait la main: aucun clic ne tombait
        assez loin de tout pour lâcher la sélection."""
        # Chercher l'item DXF le plus proche du clic
        best_item = None
        best_dist = float('inf')
        search_radius = 5.0 / max(self._zoom, 0.01)

        # l'INDEX SPATIAL de la scène: seules les entités dont la boîte
        # touche le clic — un DXF de cent mille entités ne se parcourt
        # plus à chaque clic
        boite = QRectF(scene_pos.x() - search_radius,
                       scene_pos.y() - search_radius,
                       2 * search_radius, 2 * search_radius)
        candidats = [it for it in self._scene.items(
            boite, Qt.ItemSelectionMode.IntersectsItemBoundingRect)
            if id(it) in self._item_layer]
        for item in candidats:
            if not item.isVisible():
                continue        # on ne prend pas ce qu'on ne voit pas
            if isinstance(item, QGraphicsTextItem):
                continue  # les annotations se prennent au rectangle
            rect = item.sceneBoundingRect()
            center = rect.center()
            dist = QLineF(scene_pos, center).length()
            # Aussi vérifier si le clic est dans le bounding rect
            if rect.adjusted(-search_radius, -search_radius,
                             search_radius, search_radius).contains(scene_pos):
                if dist < best_dist:
                    best_dist = dist
                    best_item = item

        if best_item is None:
            if not ajouter:
                self.clear_selection()
            return
        if not ajouter and best_item not in self._selected_items:
            # Un clic simple REMPLACE: on ajoute avec Ctrl ou Maj
            self.clear_selection()

        highlight_pen = QPen(QColor("#f9e2af"), 0.5)

        if best_item in self._selected_items:
            # Désélectionner
            self._selected_items.remove(best_item)
            iid = id(best_item)
            if iid in self._original_pens:
                if isinstance(best_item, (QGraphicsLineItem, QGraphicsEllipseItem,
                                          QGraphicsRectItem)):
                    best_item.setPen(self._original_pens[iid])
                elif isinstance(best_item, QGraphicsPathItem):
                    best_item.setPen(self._original_pens[iid])
                del self._original_pens[iid]
        else:
            # Sélectionner
            iid = id(best_item)
            if isinstance(best_item, (QGraphicsLineItem, QGraphicsEllipseItem,
                                      QGraphicsRectItem)):
                self._original_pens[iid] = best_item.pen()
                best_item.setPen(highlight_pen)
            elif isinstance(best_item, QGraphicsPathItem):
                self._original_pens[iid] = best_item.pen()
                best_item.setPen(highlight_pen)
            self._selected_items.append(best_item)

        self.selection_changed.emit(len(self._selected_items))

        # Émettre les spécifications de l'entité sélectionnée (T5)
        if self._selected_items:
            item = self._selected_items[-1]  # dernière sélectionnée
            rect = item.sceneBoundingRect()
            # Coordonnées scène → DXF (y est inversé: scene_y = -dxf_y)
            xmin, xmax = rect.left(), rect.right()
            ymin_scene, ymax_scene = rect.top(), rect.bottom()
            # Inverser Y pour coords DXF
            ymin_dxf, ymax_dxf = -ymax_scene, -ymin_scene
            w = xmax - xmin
            h = ymax_dxf - ymin_dxf
            # Utiliser le centre géométrique des métadonnées si disponible
            # (plus précis que le centre du bounding box pour arcs/polylines)
            meta = self._item_metadata.get(id(item))
            if meta:
                cx = meta['x']
                cy = meta['y']
            else:
                cx = (xmin + xmax) / 2
                cy = (ymin_dxf + ymax_dxf) / 2
            info = (f"X[{xmin:.3f},{xmax:.3f}] "
                    f"Y[{ymin_dxf:.3f},{ymax_dxf:.3f}] "
                    f"W={w:.3f} H={h:.3f} "
                    f"C=({cx:.3f},{cy:.3f})")
            self.entity_info.emit(info)
        else:
            self.entity_info.emit("")

    def _register_drawn_center(self, cx_scene, cy_scene, radius,
                               etype, emettre: bool = True) -> tuple:
        """Centre d'une entité tracée ici. Rend (centre, marqueurs)."""
        # Coords scène → coords DXF (Y inversé)
        dxf_x = cx_scene
        dxf_y = -cy_scene
        circularity = 1.0 if etype == "CIRCLE" else 0.0
        centre = {
            'x': dxf_x, 'y': dxf_y, 'radius': radius,
            'circularity': circularity, 'entity_type': etype
        }
        self._detected_circles.append(centre)
        marqueurs = []
        # Marqueur visuel pour les cercles (visibilité: toggle 'Centres')
        if circularity > 0:
            marker_pen = QPen(QColor("#f38ba8"), 0.15)
            marker_size = 0.8
            line1 = self._scene.addLine(
                cx_scene - marker_size, cy_scene,
                cx_scene + marker_size, cy_scene, marker_pen)
            line2 = self._scene.addLine(
                cx_scene, cy_scene - marker_size,
                cx_scene, cy_scene + marker_size, marker_pen)
            circ = self._scene.addEllipse(
                cx_scene - marker_size * 0.6, cy_scene - marker_size * 0.6,
                marker_size * 1.2, marker_size * 1.2, marker_pen)
            for m in (line1, line2, circ):
                m.setVisible(self._centers_visible)
                # Repéré pour que Ctrl+Z le remette dans la liste
                m.setData(0, 'marqueur_centre')
            marqueurs = [line1, line2, circ]
            self._center_markers.extend(marqueurs)
        # Émettre le signal pour actualiser GenOps
        if emettre:
            self.circles_detected.emit(self._detected_circles)
        return centre, marqueurs

    # ──── Ce qui appartient à une entité ────

    def attacher(self, item, *compagnons) -> None:
        """Lie des items à une entité: ils la suivent et s'effacent
        avec elle.

        Le centre marqué d'un cercle et l'annotation posée dessus ne
        sont pas des dessins indépendants: les laisser sur place
        quand l'entité bouge, c'est perdre ce qu'ils repéraient."""
        if item is None:
            return
        liste = self._attaches.setdefault(id(item), [])
        liste.extend(c for c in compagnons if c is not None)

    def compagnons(self, item) -> list:
        """Ce qui suit cette entité."""
        return list(self._attaches.get(id(item), []))

    def _poser_entite_dessinee(self, item, cx_scene, cy_scene,
                               radius: float, etype: str,
                               annuler: bool = True):
        """Une entité qu'on vient de tracer.

        Elle est enregistrée, son centre lui est rattaché, et elle
        reste SÉLECTIONNÉE: F2 la met à la cote et la place dans la
        foulée, sans avoir à la retrouver à la souris."""
        self._register_item(item, 'drawn')
        centre, marqueurs = self._register_drawn_center(
            cx_scene, cy_scene, radius, etype)
        self._item_metadata[id(item)] = centre
        self.attacher(item, *marqueurs)
        self._scene.clearSelection()
        try:
            item.setSelected(True)
        except RuntimeError:
            pass
        self.selection_changed.emit(len(self.selection_courante()))
        self.entity_info.emit(
            f"{etype.lower()} tracé — F2 pour la cote et la position, "
            f"flèches pour le déplacer")
        # Un tracé s'annule comme le reste (Ctrl+Z sur le dessin).
        # `coller` pousse UNE commande pour tout le presse-papiers:
        # il ne repasse donc pas par ici.
        if annuler:
            from src.gui.dxf.canvas_undo import TracerCommande
            self._pile_undo.push(TracerCommande(self, item, etype))
        return item

    def deplacer_items(self, items, dx: float, dy: float) -> int:
        """Déplace des entités AVEC ce qui leur appartient.

        `dx`, `dy` en coordonnées de SCÈNE (Y vers le bas)."""
        vus = set()
        centres_bouges = False
        n = 0
        for item in items:
            if id(item) in vus:
                continue
            vus.add(id(item))
            try:
                item.setPos(item.pos().x() + dx, item.pos().y() + dy)
            except RuntimeError:
                continue
            n += 1
            for compagnon in self._attaches.get(id(item), []):
                if id(compagnon) in vus:
                    continue
                vus.add(id(compagnon))
                try:
                    compagnon.setPos(compagnon.pos().x() + dx,
                                     compagnon.pos().y() + dy)
                except RuntimeError:
                    continue
            centre = self._item_metadata.get(id(item))
            if centre is not None:
                centre['x'] += dx
                centre['y'] -= dy      # la scène a Y vers le bas
                centres_bouges = True
        if n:
            self._extend_scene_rect()
            if self._poignees:
                self._maj_poignees()      # les poignées suivent
        if centres_bouges:
            # « DXF to Op » travaille sur ces centres: ils doivent
            # suivre, sinon on percerait à l'ancienne place
            self.circles_detected.emit(self._detected_circles)
        return n

    def _handle_draw_click(self, scene_pos: QPointF):
        # les outils qui agissent sur un tracé, d'un seul clic
        if self._draw_tool in self.OUTILS_CLIC:
            self._outil_clic(self._draw_tool, scene_pos)
            return
        if str(self._draw_tool or "").startswith('cote_'):
            self._clic_cote(scene_pos)
            return
        if str(self._draw_tool or "").startswith('contrainte:'):
            self._clic_contrainte(self._draw_tool.split(':', 1)[1],
                                  scene_pos)
            return
        self._draw_points.append(scene_pos)
        pen = QPen(QColor("#f9e2af"), 0.2)

        if self._draw_tool == "line":
            if len(self._draw_points) == 2:
                p1, p2 = self._draw_points
                item = self._scene.addLine(
                    p1.x(), p1.y(), p2.x(), p2.y(), pen)
                mid_x = (p1.x() + p2.x()) / 2
                mid_y = (p1.y() + p2.y()) / 2
                self._poser_entite_dessinee(
                    item, mid_x, mid_y, 0, "LINE")
                self._draw_points.clear()
                if self._temp_item:
                    self._scene.removeItem(self._temp_item)
                    self._temp_item = None

        elif self._draw_tool == "circle":
            if len(self._draw_points) == 2:
                center = self._draw_points[0]
                edge = self._draw_points[1]
                r = QLineF(center, edge).length()
                item = self._scene.addEllipse(
                    center.x() - r, center.y() - r, 2 * r, 2 * r, pen)
                self._poser_entite_dessinee(
                    item, center.x(), center.y(), r, "CIRCLE")
                self._draw_points.clear()
                if self._temp_item:
                    self._scene.removeItem(self._temp_item)
                    self._temp_item = None

        elif self._draw_tool == "rect":
            if len(self._draw_points) == 2:
                p1, p2 = self._draw_points
                rect = QRectF(p1, p2).normalized()
                item = self._scene.addRect(rect, pen)
                self._poser_entite_dessinee(
                    item, rect.center().x(), rect.center().y(),
                    0, "RECT")
                self._draw_points.clear()
                if self._temp_item:
                    self._scene.removeItem(self._temp_item)
                    self._temp_item = None

        elif self._draw_tool == "ruler":
            if len(self._draw_points) == 2:
                p1, p2 = self._draw_points
                distance = QLineF(p1, p2).length()
                self.ruler_measured.emit(distance)
                item = self._scene.addLine(p1.x(), p1.y(), p2.x(), p2.y(),
                                           QPen(QColor("#a6e3a1"), 0.15))
                self._register_item(item, 'drawn')
                self._draw_points.clear()
                if self._temp_item:
                    self._scene.removeItem(self._temp_item)
                    self._temp_item = None

        elif self._draw_tool == "bezier":
            if len(self._draw_points) >= 3:
                p1 = self._draw_points[0]
                pn = self._draw_points[-1]
                snap_tolerance = 0.3
                if QLineF(p1, pn).length() < snap_tolerance:
                    self._finalize_bezier(close=True)
            if len(self._draw_points) > 10:
                self._finalize_bezier(close=False)

    def mouseDoubleClickEvent(self, event):
        """Double-clic: ferme la polyligne en cours.

        Sans lui, il fallait connaître la touche Entrée pour terminer
        un tracé — un geste qu'on ne devine pas."""
        if self._draw_tool == "bezier" and len(self._draw_points) >= 2:
            self._finalize_bezier(close=True)
            event.accept()
            return
        # sur un côté de l'entité en édition: un sommet de plus
        if self._poignees and not self._draw_tool and not self._pick_mode:
            pos = self.mapToScene(event.position().toPoint())
            if self.ajouter_sommet(pos):
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def _finalize_bezier(self, close: bool = False):
        """Finalise la courbe Bézier (right-click ou Enter pour ouverte, snap pour fermée)."""
        if len(self._draw_points) < 2:
            self._draw_points.clear()
            return
        pen = QPen(QColor("#f9e2af"), 0.2)
        path = QPainterPath(self._draw_points[0])
        pts = self._draw_points
        i = 1
        while i < len(pts):
            if i + 2 < len(pts):
                path.cubicTo(pts[i], pts[i + 1], pts[i + 2])
                i += 3
            elif i + 1 < len(pts):
                path.quadTo(pts[i], pts[i + 1])
                i += 2
            else:
                path.lineTo(pts[i])
                i += 1
        if close:
            path.closeSubpath()
        item = self._scene.addPath(path, pen)
        cx = sum(p.x() for p in pts) / len(pts)
        cy = sum(p.y() for p in pts) / len(pts)
        self._poser_entite_dessinee(item, cx, cy, 0, "BEZIER")
        self._draw_points.clear()
        if self._temp_item:
            self._scene.removeItem(self._temp_item)
            self._temp_item = None

    def _update_draw_preview(self, current_pos: QPointF):
        if self._temp_item:
            self._scene.removeItem(self._temp_item)
            self._temp_item = None

        pen = QPen(QColor("#89b4fa"), 0.15, Qt.PenStyle.DashLine)
        start = self._draw_points[0]

        if str(self._draw_tool or "").startswith('cote_'):
            chemin = self._apercu_cote(current_pos)
            if chemin is not None:
                self._temp_item = self._scene.addPath(chemin, pen)
            return

        if self._draw_tool == "line":
            self._temp_item = self._scene.addLine(
                start.x(), start.y(),
                current_pos.x(), current_pos.y(), pen)
        elif self._draw_tool == "circle":
            r = QLineF(start, current_pos).length()
            self._temp_item = self._scene.addEllipse(
                start.x() - r, start.y() - r, 2 * r, 2 * r, pen)
        elif self._draw_tool == "rect":
            rect = QRectF(start, current_pos).normalized()
            self._temp_item = self._scene.addRect(rect, pen)

        elif self._draw_tool == "ruler":
            # Preview: ligne pointillée avec distance en temps réel
            if len(self._draw_points) >= 1:
                distance = QLineF(start, current_pos).length()
                self._temp_item = self._scene.addLine(
                    start.x(), start.y(), current_pos.x(), current_pos.y(), pen)
                self.ruler_measured.emit(distance)

        elif self._draw_tool == "bezier":
            # Preview: courbe Bézier complète en temps réel
            if len(self._draw_points) >= 1:
                preview_pts = list(self._draw_points) + [current_pos]
                path = QPainterPath(preview_pts[0])
                i = 1
                while i < len(preview_pts):
                    if i + 2 < len(preview_pts):
                        path.cubicTo(
                            preview_pts[i], preview_pts[i + 1],
                            preview_pts[i + 2])
                        i += 3
                    elif i + 1 < len(preview_pts):
                        path.quadTo(preview_pts[i], preview_pts[i + 1])
                        i += 2
                    else:
                        path.lineTo(preview_pts[i])
                        i += 1
                self._temp_item = self._scene.addPath(path, pen)

    _EXPORT_LAYERS = {
        'dxf': ('DXF', 7),          # blanc
        'drawn': ('DESSIN', 2),     # jaune
        'smb': ('SMB', 4),          # cyan
        'texte': ('ANNOTATION', 3),  # vert
    }

    # ── Impression A4 ──

    #: échelles normalisées proposées (mm dessin : mm papier)
    _PRINT_SCALES = (0.05, 0.1, 0.2, 0.25, 0.5, 1, 2, 2.5, 5, 10, 20, 50)

    def print_a4(self, filepath: str, landscape: bool = False,
                 scale: float = 0.0, margin_mm: float = 12.0,
                 title: str = "", couleurs: str = 'papier') -> float:
        """Imprime le canvas dans un PDF A4 (portrait ou paysage).

        scale: mm dessin pour 1 mm papier. 0 = ajustement automatique
        sur une échelle normalisée (jamais tronqué). Retourne
        l'échelle réellement employée, également annotée sur la page.
        """
        from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter
        from PySide6.QtCore import QMarginsF

        rect = self._content_bounds()
        if rect.isNull() or rect.width() <= 0 or rect.height() <= 0:
            raise RuntimeError("Rien à imprimer: le canvas est vide.")

        writer = QPdfWriter(filepath)
        writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        writer.setPageOrientation(
            QPageLayout.Orientation.Landscape if landscape
            else QPageLayout.Orientation.Portrait)
        writer.setPageMargins(QMarginsF(margin_mm, margin_mm,
                                        margin_mm, margin_mm),
                              QPageLayout.Unit.Millimeter)
        writer.setResolution(600)
        writer.setTitle(title or "NeoDrive")

        # Zone utile en mm papier (bandeau bas réservé au cartouche)
        page_mm = writer.pageLayout().paintRectPixels(
            writer.resolution())
        px_per_mm = writer.resolution() / 25.4
        avail_w_mm = page_mm.width() / px_per_mm
        avail_h_mm = page_mm.height() / px_per_mm - 10.0

        if scale and scale > 0:
            used = float(scale)
        else:
            need = max(rect.width() / avail_w_mm,
                       rect.height() / avail_h_mm)
            used = next((s for s in self._PRINT_SCALES if s >= need),
                        need)

        painter = QPainter(writer)
        # Même traitement que le PNG: sans lui, les traits clairs du
        # thème sombre sont invisibles sur le papier blanc
        state = self._begin_output_style(
            getattr(self, '_output_line_px', 1.0), couleurs)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            draw_w = rect.width() / used * px_per_mm
            draw_h = rect.height() / used * px_per_mm
            target = QRectF(
                (page_mm.width() - draw_w) / 2.0,
                max(0.0, (page_mm.height() - 10.0 * px_per_mm
                          - draw_h) / 2.0),
                draw_w, draw_h)
            self._scene.render(painter, target, rect,
                               Qt.AspectRatioMode.KeepAspectRatio)
            self._paint_print_footer(
                painter, page_mm, px_per_mm, used, rect, title)
        finally:
            painter.end()
            self._end_output_style(state)
        return used

    # ── Rendu pour sortie papier / image ──

    @staticmethod
    def _ink(color: QColor) -> QColor:
        """Couleur lisible sur fond blanc.

        Le canvas est conçu pour un fond sombre: ses traits sont
        clairs et disparaissent sur du blanc. On assombrit la teinte
        en la CONSERVANT (le code couleur des calques reste lisible)."""
        h, s, light, a = color.getHslF()
        if light > 0.42:
            light = 0.28
        s = min(1.0, max(s, 0.35)) if s > 0.05 else 0.0
        out = QColor()
        out.setHslF(max(0.0, h), s, light, a)
        return out

    @classmethod
    def _teinte(cls, color: QColor, couleurs: str) -> QColor:
        """La couleur d'un trait dans la sortie demandée."""
        if couleurs == 'canvas':
            return QColor(color)
        if couleurs == 'noir':
            return QColor("#000000")
        return cls._ink(color)

    def _begin_output_style(self, line_px: float,
                            couleurs: str = 'papier'):
        """Prépare la scène pour un rendu papier/image: grille et
        repère masqués, traits d'épaisseur constante.

        `couleurs`: 'papier' assombrit les teintes pour qu'elles
        tiennent sur du blanc, 'noir' met tout en noir (photocopie,
        découpe), 'canvas' ne touche à rien — la sortie ressemble
        alors à l'écran, fond sombre compris.
        Retourne l'état à restaurer."""
        hidden, pens, texts = [], [], []
        for attr in ('_grid_items', '_origin_items'):
            for it in getattr(self, attr, []) or []:
                try:
                    if it.isVisible():
                        it.setVisible(False)
                        hidden.append(it)
                except RuntimeError:
                    continue
        for item in self._scene.items():
            try:
                if hasattr(item, 'setDefaultTextColor'):
                    texts.append((item, QColor(item.defaultTextColor())))
                    item.setDefaultTextColor(
                        self._teinte(item.defaultTextColor(),
                                     couleurs))
                    continue
                if not hasattr(item, 'pen'):
                    continue
                old = QPen(item.pen())
                pens.append((item, old))
                new = QPen(old)
                new.setColor(self._teinte(old.color(), couleurs))
                new.setCosmetic(True)
                new.setWidthF(max(0.1, line_px))
                item.setPen(new)
            except (RuntimeError, TypeError):
                continue
        return hidden, pens, texts

    @staticmethod
    def _end_output_style(state):
        hidden, pens, texts = state
        for it in hidden:
            try:
                it.setVisible(True)
            except RuntimeError:
                pass
        for it, pen in pens:
            try:
                it.setPen(pen)
            except RuntimeError:
                pass
        for it, color in texts:
            try:
                it.setDefaultTextColor(color)
            except RuntimeError:
                pass

    def set_line_width_px(self, width_px: float):
        """Épaisseur des traits à l'écran, en PIXELS et constante quel
        que soit le zoom (pinceaux cosmétiques). S'applique aux items
        existants ET aux suivants (la scène l'impose à la création)."""
        self._line_width_px = max(0.5, min(6.0, float(width_px)))
        self._scene.line_width_px = self._line_width_px
        # L'ensemble des items de grille est calculé UNE fois: le
        # reconstruire à chaque item faisait le carré du nombre
        # d'items (2 000 lignes de grille × 2 000 items du dessin)
        ids_grille = self._grid_ids()
        for item in self._scene.items():
            try:
                if not hasattr(item, 'pen'):
                    continue
                pen = QPen(item.pen())
                pen.setCosmetic(True)
                # la grille reste plus fine que le dessin
                factor = 0.6 if id(item) in ids_grille else 1.0
                pen.setWidthF(self._line_width_px * factor)
                item.setPen(pen)
            except (RuntimeError, TypeError):
                continue
        self.viewport().update()

    def _grid_ids(self) -> set:
        return {id(i) for i in (getattr(self, '_grid_items', []) or [])}

    def export_png(self, filepath: str, width_px: int = 1000,
                   background: str = "#b8b8b8",
                   couleurs: str = 'papier', zone=None) -> tuple:
        """Rend le DESSIN (hors grille et repère) dans un PNG.

        Sert à embarquer un aperçu de la pièce dans le programme SimPl
        (@image:), pour que l'opérateur voie le dessin dans l'éditeur
        de la machine. `zone` (QRectF de la scène): ce cadre au lieu de
        toute la pièce — 'canva': ce que la vue montre. Retourne
        (largeur, hauteur) en pixels."""
        from PySide6.QtGui import QImage
        if zone == 'canva':
            zone = self.mapToScene(self.viewport().rect()).boundingRect()
        rect = zone if zone is not None else self._content_bounds()
        if rect.isNull() or rect.width() <= 0 or rect.height() <= 0:
            raise RuntimeError("Rien à exporter: le canvas est vide.")
        width_px = max(200, min(4000, int(width_px)))
        height_px = max(
            1, int(round(width_px * rect.height() / rect.width())))
        img = QImage(width_px, height_px,
                     QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QColor(background))
        painter = QPainter(img)
        state = self._begin_output_style(
            getattr(self, '_output_line_px', 1.0), couleurs)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._scene.render(
                painter, QRectF(0, 0, width_px, height_px), rect,
                Qt.AspectRatioMode.KeepAspectRatio)
        finally:
            painter.end()
            self._end_output_style(state)
        if not img.save(filepath, "PNG"):
            raise RuntimeError(f"Écriture impossible: {filepath}")
        return width_px, height_px

    @staticmethod
    def _textes_des_operations(program) -> list:
        """(nom, contours) des opérations à texte actives: les
        « Gravure texte », et les têtes de gamme qui portent un
        texte."""
        sortie = []
        for op in getattr(program, 'operations', None) or []:
            if not getattr(op, 'enabled', True):
                continue
            genre = getattr(op, 'operation_type', '')
            if genre != 'texte_grave':
                continue
            params = getattr(op, 'params', {}) or {}
            if not str(params.get('texte') or "").strip():
                continue
            try:
                from src.core import texte as noyau_texte
                contours = noyau_texte.contours_depuis_params(params)
            except Exception:
                contours = None
            if contours:
                sortie.append((op.name, contours))
        return sortie

    def _exporter_textes(self, msp, program) -> int:
        """Les lettres des opérations à texte, fermées, sur TEXTES."""
        n = 0
        for _nom, contours in self._textes_des_operations(program):
            for contour in contours:
                points = [(float(x), float(y)) for x, y in contour]
                if len(points) >= 3:
                    msp.add_lwpolyline(points, close=True,
                                       dxfattribs={'layer': 'TEXTES'})
                    n += 1
        return n

    def _exporter_parcours(self, msp, program) -> int:
        """Empreinte des opérations actives, sur le calque PARCOURS.

        On rejoue le dessin que le canvas fait déjà à l'écran: ce que
        l'on exporte est ce que l'on voit."""
        # Les anciens tracés sont GARDÉS EN VIE le temps de comparer:
        # draw_all_operations les efface, et Python redonnait leur id()
        # aux tracés neufs — qui passaient pour anciens, et le calque
        # PARCOURS sortait vide (selon l'état de la mémoire)
        anciens = list(self._op_point_items)
        avant = set(id(i) for i in anciens)
        self.draw_all_operations(program)
        n = 0
        for item in self._op_point_items:
            if id(item) in avant:
                continue
            chemin = None
            if isinstance(item, QGraphicsPathItem):
                chemin = item.path()
            elif isinstance(item, QGraphicsEllipseItem):
                rect = item.rect()
                centre = item.mapToScene(rect.center())
                if abs(rect.width() - rect.height()) < 1e-6:
                    msp.add_circle(
                        (centre.x(), -centre.y()), rect.width() / 2.0,
                        dxfattribs={'layer': 'PARCOURS'})
                    n += 1
                continue
            if chemin is None or chemin.isEmpty():
                continue
            points = []
            for polygone in self.polygones_fins(
                    item.mapToScene(chemin)):
                points = [(x, -y) for x, y in polygone]
                if len(points) >= 2:
                    msp.add_lwpolyline(
                        points, dxfattribs={'layer': 'PARCOURS'})
                    n += 1
        return n

    def _content_bounds(self) -> QRectF:
        """Étendue du DESSIN, grille et repère d'origine exclus.

        itemsBoundingRect() englobe la grille (±500 mm): s'en servir
        pour l'impression aurait imposé une échelle absurde (1:10 pour
        un dessin de 200 mm)."""
        skip = set()
        for attr in ('_grid_items', '_origin_items'):
            for it in getattr(self, attr, []) or []:
                skip.add(id(it))
        rect = QRectF()
        for item in self._scene.items():
            if id(item) in skip or not item.isVisible():
                continue
            r = item.sceneBoundingRect()
            if r.isNull():
                continue
            rect = r if rect.isNull() else rect.united(r)
        if rect.isNull():
            return rect
        m = max(rect.width(), rect.height()) * 0.02 + 1.0
        return rect.adjusted(-m, -m, m, m)

    def _paint_print_footer(self, painter, page_mm, px_per_mm,
                            scale: float, rect: QRectF, title: str):
        """Cartouche: échelle annotée + étendue + barre d'échelle."""
        from datetime import datetime
        painter.save()
        painter.resetTransform()
        y = page_mm.height() - 8.0 * px_per_mm
        pen = QPen(QColor("#000000"))
        pen.setWidthF(0.3 * px_per_mm)
        painter.setPen(pen)
        painter.drawLine(0, int(y), int(page_mm.width()), int(y))

        font = QFont("Arial")
        font.setPointSizeF(8.0)
        painter.setFont(font)
        ratio = (f"1:{scale:g}" if scale >= 1
                 else f"{1 / scale:g}:1")
        stamp = datetime.now().strftime("%d/%m/%Y %H:%M")
        left = (f"{title or 'NeoDrive'}   —   Échelle {ratio}   "
                f"(1 mm papier = {scale:g} mm pièce)")
        right = (f"Étendue {rect.width():.1f} × {rect.height():.1f} mm"
                 f"   —   {stamp}")
        ty = int(y + 3.0 * px_per_mm)
        painter.drawText(0, ty, int(page_mm.width()),
                         int(4.0 * px_per_mm),
                         int(Qt.AlignmentFlag.AlignLeft), left)
        painter.drawText(0, ty, int(page_mm.width()),
                         int(4.0 * px_per_mm),
                         int(Qt.AlignmentFlag.AlignRight), right)

        # Barre d'échelle graphique: 50 mm papier
        bar_mm = 50.0
        bx = 0.0
        by = y + 6.5 * px_per_mm
        painter.drawLine(int(bx), int(by),
                         int(bx + bar_mm * px_per_mm), int(by))
        for k in (0, 1):
            x = bx + k * bar_mm * px_per_mm
            painter.drawLine(int(x), int(by - 1.2 * px_per_mm),
                             int(x), int(by + 1.2 * px_per_mm))
        font.setPointSizeF(7.0)
        painter.setFont(font)
        painter.drawText(
            int(bx + bar_mm * px_per_mm + 2 * px_per_mm),
            int(by + 1.0 * px_per_mm),
            f"{bar_mm * scale:g} mm")
        painter.restore()

    #: ce que l'on peut sortir du canvas, dans l'ordre d'affichage
    CALQUES_EXPORT = (
        ('dxf', "DXF importé",
         "Les entités lues dans le fichier importé."),
        ('drawn', "Dessin",
         "Ce qui a été tracé ici: lignes, cercles, rectangles."),
        ('texte', "Annotations",
         "Les textes posés sur le plan."),
        ('smb', "Symboles",
         "Les symboles TypeEdit posés sur le dessin."),
        ('centres', "Centres détectés",
         "Les centres de trous trouvés (POINT en DXF, croix ailleurs)."),
        ('parcours', "Parcours d'usinage",
         "L'empreinte des opérations actives du programme."),
        ('textes', "Textes des opérations",
         "Les contours des « Gravure texte », en DXF (calque "
         "TEXTES): le dessin des lettres, pas leur parcours."),
    )

    #: comment teinter la sortie
    COULEURS_EXPORT = (
        ('papier', "Assombries pour le papier",
         "Les couleurs du canvas, foncées pour tenir sur du blanc."),
        ('noir', "Tout en noir",
         "Un seul trait noir: photocopie, découpe, gravure."),
        ('canvas', "Comme à l'écran",
         "Les couleurs du canvas telles quelles, sur fond sombre."),
    )

    #: formats de sortie, avec le filtre de fichier associé
    FORMATS_EXPORT = (
        ('dxf', "DXF — vectoriel, ré-usinable",
         "Fichiers DXF (*.dxf)", ".dxf"),
        ('svg', "SVG — vectoriel, web et découpe",
         "Images SVG (*.svg)", ".svg"),
        ('pdf', "PDF — page A4 avec cartouche",
         "Documents PDF (*.pdf)", ".pdf"),
        ('eps', "EPS — PostScript, découpe et gravure",
         "PostScript encapsulé (*.eps)", ".eps"),
        ('ai', "AI — Illustrator (EPS, version 8)",
         "Illustrator (*.ai)", ".ai"),
        ('png', "PNG — image",
         "Images PNG (*.png)", ".png"),
    )

    def _items_du_calque(self, cle: str) -> list:
        """Les items du canvas qui appartiennent a un calque."""
        if cle == 'centres':
            return list(self._center_markers)
        if cle == 'parcours':
            return (list(self._op_point_items)
                    + list(self._op_label_items))
        return [i for i in self._dxf_items
                if self._item_layer.get(id(i), 'dxf') == cle]

    def compte_calques(self, program=None) -> dict:
        """Ce qu'il y a a exporter, calque par calque.

        Un calque vide ne se propose pas: cocher une case qui ne
        donnera rien fait perdre du temps."""
        compte = {}
        for cle, _nom, _bulle in self.CALQUES_EXPORT:
            if cle == 'centres':
                compte[cle] = len(self._detected_circles)
            elif cle == 'parcours':
                n = 0
                if program is not None:
                    from src.gui.panels.operations_panel import (
                        op_preview)
                    n = sum(1 for op in program.operations
                            if getattr(op, 'enabled', True)
                            and op_preview(op))
                compte[cle] = n
            elif cle == 'textes':
                compte[cle] = len(self._textes_des_operations(program))
            else:
                compte[cle] = len(self._items_du_calque(cle))
        return compte

    def _isoler_calques(self, calques) -> list:
        """Ne laisse voir QUE les calques demandés, le temps du rendu.

        SVG, PDF et PNG sortent ce que la scène montre: pour choisir
        ce qui part, on choisit ce qui se voit. Rend l'état à
        rétablir."""
        if not calques:
            return []
        voulus = set(calques)
        etat = []

        def _regler(item, visible):
            try:
                if item.isVisible() != visible:
                    etat.append((item, item.isVisible()))
                    item.setVisible(visible)
            except RuntimeError:
                pass

        for item in self._dxf_items:
            _regler(item,
                    self._item_layer.get(id(item), 'dxf') in voulus)
        for cle in ('centres', 'parcours'):
            for item in self._items_du_calque(cle):
                _regler(item, cle in voulus)
        return etat

    @staticmethod
    def _rendre_calques(etat) -> None:
        for item, visible in etat:
            try:
                item.setVisible(visible)
            except RuntimeError:
                pass

    def exporter(self, filepath: str, sortie: str = 'dxf',
                 calques=None, couleurs: str = 'papier',
                 program=None, titre: str = ""):
        """Écrit le dessin: format, calques et couleurs au choix.

        Une seule porte pour les quatre formats — le panneau n'a pas
        à savoir lequel se rend par la scène et lequel s'écrit
        entité par entité."""
        sortie = (sortie or 'dxf').lower()
        calques = list(calques) if calques else None
        if sortie == 'dxf':
            return self.export_dxf(filepath, calques=calques,
                                   program=program)
        # Le parcours n'existe à l'écran que s'il y a été dessiné
        if (calques and 'parcours' in calques and program is not None
                and not self._op_point_items):
            self.draw_all_operations(program)
        etat = self._isoler_calques(calques)
        try:
            if sortie == 'svg':
                return self.export_svg(filepath, couleurs=couleurs,
                                       titre=titre)
            if sortie == 'pdf':
                return self.print_a4(filepath, title=titre,
                                     couleurs=couleurs)
            if sortie in ('eps', 'ai'):
                return self.export_eps(filepath, couleurs=couleurs,
                                       titre=titre)
            if sortie == 'png':
                fond = "#1e1e2e" if couleurs == 'canvas' else "#ffffff"
                return self.export_png(filepath, background=fond,
                                       couleurs=couleurs)
            raise ValueError(f"Format de sortie inconnu: {sortie}")
        finally:
            self._rendre_calques(etat)

    def _commandes_du_chemin(self, chemin: QPainterPath) -> list:
        """Un chemin Qt en commandes M/L/C/Z, en MILLIMÈTRES.

        La scène a Y vers le bas, le papier l'a vers le haut: le
        signe change ici, une fois pour toutes."""
        sortie = []
        i = 0
        total = chemin.elementCount()
        while i < total:
            e = chemin.elementAt(i)
            if e.type == QPainterPath.ElementType.MoveToElement:
                sortie.append(('M', e.x, -e.y))
                i += 1
            elif e.type == QPainterPath.ElementType.LineToElement:
                sortie.append(('L', e.x, -e.y))
                i += 1
            elif e.type == QPainterPath.ElementType.CurveToElement:
                if i + 2 >= total:
                    break
                d1 = chemin.elementAt(i + 1)
                d2 = chemin.elementAt(i + 2)
                sortie.append(('C', e.x, -e.y, d1.x, -d1.y,
                               d2.x, -d2.y))
                i += 3
            else:
                i += 1
        return sortie

    def _chemin_scene(self, item):
        """La géométrie d'un item, ramenée en coordonnées de scène."""
        from PySide6.QtGui import QFontMetricsF
        chemin = QPainterPath()
        if isinstance(item, QGraphicsPathItem):
            chemin = item.path()
        elif isinstance(item, QGraphicsEllipseItem):
            chemin.addEllipse(item.rect())
        elif isinstance(item, QGraphicsRectItem):
            chemin.addRect(item.rect())
        elif isinstance(item, QGraphicsLineItem):
            ligne = item.line()
            chemin.moveTo(ligne.p1())
            chemin.lineTo(ligne.p2())
        elif isinstance(item, QGraphicsTextItem):
            # Une annotation sort en CONTOURS de lettres: un EPS de
            # découpe n'embarque pas les polices
            police = item.font()
            texte = str(item.data(2) or item.toPlainText())
            if not texte:
                return None
            chemin.addText(0.0, QFontMetricsF(police).ascent(),
                           police, texte)
        else:
            return None
        if chemin.isEmpty():
            return None
        return item.mapToScene(chemin)

    def export_eps(self, filepath: str, couleurs: str = 'papier',
                   titre: str = "") -> tuple:
        """EPS vectoriel — et AI, qui en est un jusqu'à la version 8.

        C'est le format que demandent les graveurs et les découpeurs
        qui ne lisent pas le DXF. Les courbes y restent des courbes,
        et les annotations partent en contours de lettres."""
        from src.io import eps_writer
        traces = []
        ignores = {id(i) for attr in ('_grid_items', '_origin_items')
                   for i in (getattr(self, attr, []) or [])}
        for item in self._scene.items(Qt.SortOrder.AscendingOrder):
            if id(item) in ignores or not item.isVisible():
                continue
            chemin = self._chemin_scene(item)
            if chemin is None:
                continue
            commandes = self._commandes_du_chemin(chemin)
            if not commandes:
                continue
            if hasattr(item, 'pen'):
                brute = item.pen().color()
            elif hasattr(item, 'defaultTextColor'):
                brute = item.defaultTextColor()
            else:
                brute = QColor("#000000")
            teinte = self._teinte(brute, couleurs)
            traces.append((commandes, (teinte.redF(), teinte.greenF(),
                                       teinte.blueF())))
        if not traces:
            raise RuntimeError("Rien à exporter: le canvas est vide.")
        return eps_writer.ecrire(filepath, traces, titre=titre)

    def export_svg(self, filepath: str, couleurs: str = 'papier',
                   titre: str = "") -> tuple:
        """SVG VECTORIEL a l'echelle 1:1 (1 mm dessin = 1 mm papier).

        Le SVG raisonne en pixels CSS: 96 par pouce. On pose donc le
        facteur une fois pour toutes, et le fichier s'ouvre a la
        bonne taille dans un navigateur comme dans une decoupeuse."""
        from PySide6.QtSvg import QSvgGenerator
        from PySide6.QtCore import QSize
        rect = self._content_bounds()
        if rect.isNull() or rect.width() <= 0 or rect.height() <= 0:
            raise RuntimeError("Rien à exporter: le canvas est vide.")
        px_par_mm = 96.0 / 25.4
        larg = max(1, int(round(rect.width() * px_par_mm)))
        haut = max(1, int(round(rect.height() * px_par_mm)))
        gen = QSvgGenerator()
        gen.setFileName(filepath)
        # Qt écrit la taille en mm d'après CETTE résolution: sans
        # elle il compte 72 points par pouce et le fichier s'ouvre
        # 33 % trop grand
        gen.setResolution(96)
        gen.setSize(QSize(larg, haut))
        gen.setViewBox(QRectF(0, 0, larg, haut))
        gen.setTitle(titre or "NeoDrive")
        gen.setDescription(
            f"Dessin NeoDrive - {rect.width():.1f} x "
            f"{rect.height():.1f} mm")
        painter = QPainter(gen)
        etat = self._begin_output_style(
            getattr(self, '_output_line_px', 1.0), couleurs)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.fillRect(
                QRectF(0, 0, larg, haut),
                QColor("#1e1e2e") if couleurs == 'canvas'
                else QColor("#ffffff"))
            self._scene.render(
                painter, QRectF(0, 0, larg, haut), rect,
                Qt.AspectRatioMode.KeepAspectRatio)
        finally:
            painter.end()
            self._end_output_style(etat)
        return larg, haut

    #: ce qui part quand on ne précise rien: le dessin et ses textes
    _CALQUES_PAR_DEFAUT = ('dxf', 'drawn', 'smb', 'texte')

    #: écart toléré entre une courbe exportée et ses arcs, en mm
    ARCS_EXPORT_MM = 0.005

    def _ajouter_polyligne_dxf(self, msp, pts, ferme: bool, attribs):
        """Une polyligne au DXF, ses arcs retrouvés (src.core.arcs):
        LWPOLYLINE à bulges. Sans arc, les sommets tels quels."""
        from src.core import arcs as _arcs
        segments = _arcs.ajuster(pts, self.ARCS_EXPORT_MM)
        if not segments or not any(sg[0] == 'A' for sg in segments):
            msp.add_lwpolyline(pts, close=ferme, dxfattribs=attribs)
            return
        sommets = _arcs.bulges(pts[0], segments)
        if ferme:
            sommets = sommets[:-1]     # la fermeture rejoint le premier
        msp.add_lwpolyline(sommets, format='xyb', close=ferme,
                           dxfattribs=attribs)

    def export_dxf(self, filepath: str, program=None, calques=None):
        """Exporte le canvas vers un DXF, calque par calque.

        `calques`: les clés du canvas retenues ('dxf', 'drawn',
        'smb', 'texte', 'centres', 'parcours'). Sans rien, le dessin
        et ses annotations partent — pas le parcours d'usinage, qui
        n'a rien à faire dans un plan qu'on renvoie au client.

        - un calque DXF par source (DXF / DESSIN / SMB / ANNOTATION)
        - cercles natifs quand la géométrie est connue (métadonnées
          des trous SMB, ellipses circulaires)
        - ellipses natives, le reste en polylignes échantillonnées"""
        _load_ezdxf()
        if calques is None:
            calques = self._CALQUES_PAR_DEFAUT
        gardes = {c for c in calques
                  if c in ('dxf', 'drawn', 'smb', 'texte')}
        veut_parcours = 'parcours' in calques
        veut_centres = 'centres' in calques
        veut_textes = 'textes' in calques

        doc = ezdxf.new(dxfversion='R2010')
        # en MILLIMÈTRES: ezdxf écrit « mètres » par défaut ($INSUNITS
        # 6) — relu ailleurs (et ici même), le dessin grossissait mille
        # fois
        doc.units = 4
        doc.header['$MEASUREMENT'] = 1
        msp = doc.modelspace()
        for name, color in self._EXPORT_LAYERS.values():
            doc.layers.add(name=name, color=color)
        if veut_parcours:
            doc.layers.add(name='PARCOURS', color=1)   # rouge
        if veut_textes:
            doc.layers.add(name='TEXTES', color=2)     # jaune
        if veut_centres:
            doc.layers.add(name='CENTRES', color=1)
            for c in self._detected_circles:
                msp.add_point((c['x'], c['y']),
                              dxfattribs={'layer': 'CENTRES'})

        for item in self._dxf_items:
            if self._item_layer.get(id(item), 'dxf') not in gardes:
                continue
            layer = self._EXPORT_LAYERS.get(
                self._item_layer.get(id(item), 'dxf'),
                self._EXPORT_LAYERS['dxf'])[0]
            # « Opé → dessin »: contour et parcours, chacun son calque
            propre = item.data(4)
            if propre:
                layer = str(propre)
                if layer not in doc.layers:
                    doc.layers.add(name=layer, color=(
                        30 if layer.startswith("PARCOURS") else 2))
            attribs = {'layer': layer}
            meta = self._item_metadata.get(id(item))

            if item.data(1) == 'annotation' and item.data(5) == 'cote':
                # texte de cote: centré sur sa place, à son angle
                from ezdxf.enums import TextEntityAlignment
                cx, cy, angle = item.data(6)
                msp.add_text(
                    str(item.data(2) or ''),
                    dxfattribs={**attribs,
                                'height': float(item.data(3) or 2.5),
                                'rotation': float(angle)}
                ).set_placement((cx, cy),
                                align=TextEntityAlignment.MIDDLE_CENTER)
                continue
            if item.data(1) == 'annotation':
                point = item.mapToScene(item.boundingRect().topLeft())
                msp.add_text(
                    str(item.data(2) or ''),
                    dxfattribs={**attribs,
                                'height': float(item.data(3) or 5.0)}
                ).set_placement((point.x(), -point.y()))
                continue

            if isinstance(item, QGraphicsLineItem):
                line = item.line()
                p1 = item.mapToScene(line.p1())
                p2 = item.mapToScene(line.p2())
                msp.add_line((p1.x(), -p1.y()), (p2.x(), -p2.y()),
                             dxfattribs=attribs)
            elif isinstance(item, QGraphicsEllipseItem):
                rect = item.rect()
                w, h = rect.width(), rect.height()
                c = item.mapToScene(rect.center())
                cx, cy = c.x(), -c.y()
                if abs(w - h) < 1e-6:
                    msp.add_circle((cx, cy), w / 2, dxfattribs=attribs)
                else:
                    # Ellipse native (rotation de l'item respectée)
                    a = max(w, h) / 2
                    ratio = min(w, h) / max(w, h)
                    ang = math.radians(-item.rotation())
                    if h > w:
                        ang += math.pi / 2
                    msp.add_ellipse(
                        center=(cx, cy),
                        major_axis=(a * math.cos(ang),
                                    a * math.sin(ang)),
                        ratio=ratio, dxfattribs=attribs)
            elif isinstance(item, QGraphicsRectItem):
                rect = item.rect()
                corners = [rect.topLeft(), rect.topRight(),
                           rect.bottomRight(), rect.bottomLeft()]
                pts = []
                for corner in corners:
                    p = item.mapToScene(corner)
                    pts.append((p.x(), -p.y()))
                msp.add_lwpolyline(pts, close=True, dxfattribs=attribs)
            elif isinstance(item, QGraphicsPathItem):
                # Trou quasi parfait → CIRCLE natif (fidélité), avec
                # garde: la bbox de l'item doit correspondre au cercle
                if (meta and meta.get('circularity', 0) >= 0.98
                        and meta.get('radius', 0) > 0):
                    rect = item.sceneBoundingRect()
                    r_item = max(rect.width(), rect.height()) / 2
                    if abs(r_item - meta['radius']) \
                            <= meta['radius'] * 0.2:
                        msp.add_circle(
                            (meta['x'], meta['y']), meta['radius'],
                            dxfattribs=attribs)
                        continue
                # Béziers/polylignes/textes: polylignes, leurs arcs
                # retrouvés (sommets à « bulge »: un cercle importé
                # ressort en deux arcs exacts, pas en mille cordes)
                path = item.mapToScene(item.path())
                for polygon in self.polygones_fins(path):
                    pts = [(x, -y) for x, y in polygon]
                    if len(pts) >= 2:
                        closed = (len(pts) > 2 and pts[0] == pts[-1])
                        self._ajouter_polyligne_dxf(msp, pts, closed,
                                                    attribs)

        if veut_parcours and program is not None:
            self._exporter_parcours(msp, program)
        if veut_textes and program is not None:
            self._exporter_textes(msp, program)
        doc.saveas(filepath)
