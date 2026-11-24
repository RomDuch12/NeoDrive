"""La vue 3D du canvas: la pièce STEP, le dessin, les opérations.

Faces ombrées et arêtes de la pièce dans un tampon de profondeur
(`raster_triangles`) — le plus proche gagne pixel par pixel, les arêtes de
derrière se cachent —, puis le dessin et les opérations par-dessus, à leur
cote, au QPainter. Rendu hors écran: on vérifie ce qui est dessiné, pixel par
pixel.

Le PARCOURS simulé (sim_cycles: les cycles Datron déroulés) est une
couche à part: un curseur d'avance le montre jusqu'où l'outil est
arrivé, avec l'outil dessiné à sa place, et ▶ le joue. La MATIÈRE
(case « Matière », src/core/enlevement.py) est le brut creusé par ce
parcours, jusqu'à l'avance: la pièce telle qu'elle sort de la machine.

La pièce STEP s'importe d'ici; un clic sur une de ses faces la
sélectionne (Ctrl+clic: ajoute ou retire), et « Usiner la sélection »
propose les usinages 2D qui la font (usinage_faces).

Souris: glisser (gauche) tourne, glisser (milieu/droit) décale,
molette zoome, double-clic remet la vue iso, clic choisit une face.
"""

import functools
import itertools
import math
import time
from typing import List

import numpy as np
from PySide6.QtCore import Qt, QPointF, Signal, QTimer
from PySide6.QtGui import (QColor, QPainter, QPen, QPolygonF, QBrush,
                           QImage)
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout,
                               QPushButton, QLabel, QCheckBox, QComboBox,
                               QSlider, QMenu, QFrame, QSizePolicy)

from src.gui.panneau_ops_3d import PanneauAffichageOps
from src.gui import traits_en_points as tp
from src.gui.polygones import polygone, polygone_xy
from src.gui.raster_triangles import Raster
from src.gui.vue3d import Vue3D, _FOND
from src.gui.widgets import SpinCote


def _relacher(jeton) -> None:
    """Une vue détruite n'attend plus la pause de l'utilisateur."""
    try:
        from src.gui import activite
        activite.relacher(jeton)
    except Exception:
        pass


def polygone_ecran(px, py, pas: float = 0.75) -> "QPolygonF":
    """La polyligne projetée (x, y écran), réduite: on garde au moins
    un point par `pas` pixels de CHEMIN parcouru (la longueur cumulée, pas
    l'écart entre deux voisins — une courbe faite de pas minuscules
    serait sinon effacée). L'écart au tracé complet reste sous `pas`."""
    px = np.asarray(px, dtype=float)
    py = np.asarray(py, dtype=float)
    n = len(px)
    if n > 16 and pas > 0:
        d = np.hypot(np.diff(px), np.diff(py))
        k = np.floor(np.concatenate(([0.0], np.cumsum(d))) / pas)
        garde = np.empty(n, dtype=bool)
        garde[0] = True
        garde[1:] = k[1:] != k[:-1]
        garde[-1] = True
        px, py = px[garde], py[garde]
    return polygone_xy(px, py)


#: lumière dans le repère de la vue (x écran, haut écran, profondeur)
_LUMIERE = np.array([-0.35, 0.55, -0.75])
_LUMIERE = _LUMIERE / np.linalg.norm(_LUMIERE)
_ARETE = QColor(30, 30, 46, 200)
#: couleur des faces sélectionnées (0–1)
COULEUR_SELECTION = (0.33, 0.62, 1.0)
#: les faces qu'aucune orientation 3 axes n'atteint
COULEUR_INACCESSIBLE = (0.95, 0.35, 0.42)
#: au-delà, l'accessibilité des faces ne se calcule pas au chargement
FACES_MAX_ACCESSIBILITE = 3000
#: un clic: la souris a bougé de moins que ceci (pixels)
_CLIC_MAX = 4.0
#: un clic à moins de ceci (pixels) d'un trait d'opération la choisit
#: (sinon, il choisit la face de la pièce sous lui)
TOLERANCE_CLIC_OP = 6.0
#: les opérations choisies dans la liste: leurs traits s'élargissent de
#: tant (pixels), les autres gardent cette part de leur opacité
SURCROIT_CHOISIE = 1.4
ESTOMPE_AUTRES = 0.3
#: au-delà, une vue qui bouge prend le maillage grossier de la matière
_TRI_MAX_EN_ROTATION = 30000
#: une image d'une vue qui bouge: au-dessus de ce temps (s), la suivante perd
#: en finesse; en dessous de l'autre, elle en regagne
#: deux faces dans un même plan (le dessus de la pièce et celui du brut): sans
#: ordre entre elles, un pixel sur dix passe à l'autre au gré des arrondis. Cet
#: écart (fraction de l'étendue de la scène) dépasse les arrondis de la
#: profondeur (6e-8), et personne ne le voit
_ECART_DE_PRIORITE = 1e-6
_IMAGE_TROP_LENTE = 0.06
_IMAGE_TRES_RAPIDE = 0.012


class VueScene(Vue3D):
    """La scène: triangles ombrés, arêtes de la pièce, calques de
    traits (opérations, dessin)."""

    #: la sélection de faces a changé
    selection_changee = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        #: la face (index du modèle) de chaque triangle de la pièce
        self._tri_face = np.zeros(0, dtype=int)
        #: les faces sélectionnées
        self.selection = set()
        #: les faces inaccessibles en 3 axes, en rouge
        self.faces_rouges = set()
        self.montrer_rouges = True
        self._appui = None
        #: (x, y, ajouter) -> vrai si le clic a pris autre chose qu'une
        #: face (le trait d'une opération: `Canvas3D._clic_sur_op`)
        self.clic_avant_face = None
        self._tri = np.zeros((0, 3, 3))
        self._tri_col = np.zeros((0, 3))
        self._aretes: List[np.ndarray] = []
        self._calques: List[dict] = []
        #: le parcours simulé, jusqu'où l'avance le montre
        self._calques_parcours: List[dict] = []
        #: l'opacité de chaque entité (0–1), réglée au panneau « Entités »
        #: (la matière garde `opacite_matiere`)
        self.opacites = {cle: 1.0 for cle, _n, _cb in ENTITES_3D
                         if cle != 'matiere'}
        #: l'outil à sa place sur le parcours: {'pos', 'rayon'} ou None
        self.outil = None
        self.montrer_parcours = True
        #: le brut creusé (triangles, couleurs), et sa version
        #: grossière pour tourner la vue sans attendre
        self._tri_matiere = np.zeros((0, 3, 3))
        self._col_matiere = np.zeros((0, 3))
        self._tri_matiere_grossier = np.zeros((0, 3, 3))
        self._col_matiere_grossier = np.zeros((0, 3))
        self.montrer_matiere = False
        #: l'opacité de la matière (0–1): à demi transparente, elle laisse
        #: voir la pièce et le parcours (le PNG d'export la règle)
        self.opacite_matiere = 1.0
        #: le fond de la vue (le PNG d'export le règle)
        self.couleur_fond = QColor(_FOND)
        self.montrer_piece = True
        self.montrer_aretes = True
        self.montrer_operations = True
        self.montrer_dessin = True
        self.transparente = False
        self.exag = 1.0
        #: la machine autour de la pièce (table, étau / mandrin) et
        #: l'enveloppe de ses courses
        self._tri_machine = np.zeros((0, 3, 3))
        self._col_machine = np.zeros((0, 3))
        self._aretes_machine: List[np.ndarray] = []
        self.montrer_machine = False
        #: les collisions de la broche (x, y, z), en rouge
        self.collisions: List[tuple] = []
        #: la lecture est en cours (le panneau le dit): la scène et le
        #: parcours déjà fait sont gardés en image, chaque image n'y
        #: ajoute que les tronçons finis depuis la précédente
        self.lecture_en_cours = False
        self._image_lecture = None
        #: l'image de la vue au repos: une vue qui se repeint sans avoir
        #: changé ne retrace rien
        self._image_repos = None
        self._image_piece = None
        #: la scène aux opérations TOUTES estompées, en image: sous les
        #: opérations choisies dans la liste, la même d'un choix à l'autre
        #: (changer de choix ne retrace que les choisies)
        self._image_estompee = None
        #: (calques sans choix, parcours sans choix, calques marqués,
        #: parcours marqués), posés par `Canvas3D._montrer_le_choix`:
        #: valables tant que les marqués sont ceux que la vue montre
        self._neutres = None
        #: l'image qu'un changement de choix demandera (l'estompée sans
        #: choix, celle sans choix pendant un choix) se prépare à la pause
        #: de l'utilisateur
        self._minuterie_voisine = QTimer(self)
        self._minuterie_voisine.setSingleShot(True)
        self._minuterie_voisine.timeout.connect(self._preparer_image_voisine)
        self._jeton_activite = object()
        self.destroyed.connect(functools.partial(_relacher,
                                                 self._jeton_activite))
        #: les arêtes bout à bout: (liste, nombre, sommets, débuts)
        self._aretes_jointes = None
        #: id(triangles) -> (triangles, exag, normales)
        self._normales_gardees = {}
        #: la finesse d'une vue qui bouge (1: un pixel par pixel de la vue),
        #: réglée sur le temps de l'image précédente
        self._finesse_en_mouvement = 1.0
        #: le zoom, comme la rotation: une image légère à chaque cran, la
        #: belle quand on s'arrête
        self._zoom_recent = QTimer(self)
        self._zoom_recent.setSingleShot(True)
        self._zoom_recent.setInterval(180)
        self._zoom_recent.timeout.connect(self.update)

    # ──── Données ────

    def set_scene(self, triangles=None, couleurs=None, aretes=None,
                  calques=None, parcours=None, faces=None) -> None:
        """`calques`: [{'nom', 'pts': [arrays], 'couleur', 'largeur',
        'style', 'genre': 'operation'|'dessin'}]; `parcours`: les
        calques du parcours simulé, en entier (la vue se cadre dessus,
        l'avance n'en montre ensuite qu'une partie)."""
        self._calques_parcours = list(parcours or [])
        self.outil = None
        self._tri = (np.asarray(triangles, dtype=float)
                     if triangles is not None and len(triangles)
                     else np.zeros((0, 3, 3)))
        self._tri_col = (np.asarray(couleurs, dtype=float)
                         if couleurs is not None and len(couleurs)
                         else np.tile([0.7, 0.74, 0.8], (len(self._tri), 1)))
        self._aretes = [np.asarray(a, dtype=float) for a in (aretes or [])
                        if len(a) >= 2]
        self._calques = list(calques or [])
        self._tri_face = (np.asarray(faces, dtype=float).astype(int)
                          if faces is not None
                          and len(faces) == len(self._tri)
                          else np.full(len(self._tri), -1))
        self._cadrer(self._bornes())
        self.update()

    # ──── Sélection de faces ────

    def face_au_point(self, x: float, y: float) -> int:
        """La face de la pièce sous le pixel (x, y) — la plus proche
        de l'œil —, ou -1."""
        if not len(self._tri) or not self.montrer_piece:
            return -1
        tx, ty, td = self._vue(self._tri.reshape(-1, 3))
        tx, ty, td = (tx.reshape(-1, 3), ty.reshape(-1, 3),
                      td.reshape(-1, 3))
        x0, y0 = tx[:, 0], ty[:, 0]
        x1, y1 = tx[:, 1], ty[:, 1]
        x2, y2 = tx[:, 2], ty[:, 2]
        det = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        ok = np.abs(det) > 1e-12
        det = np.where(ok, det, 1.0)
        a = ((y1 - y2) * (x - x2) + (x2 - x1) * (y - y2)) / det
        b = ((y2 - y0) * (x - x2) + (x0 - x2) * (y - y2)) / det
        c = 1.0 - a - b
        dedans = ok & (a >= -1e-9) & (b >= -1e-9) & (c >= -1e-9)
        if not dedans.any():
            return -1
        prof = a * td[:, 0] + b * td[:, 1] + c * td[:, 2]
        prof = np.where(dedans, prof, np.inf)
        k = int(np.argmin(prof))
        return int(self._tri_face[k]) if k < len(self._tri_face) else -1

    def choisir(self, face: int, ajouter: bool = False) -> None:
        """Un clic sur `face` (-1: dans le vide)."""
        if ajouter:
            if face >= 0:
                self.selection ^= {face}
        else:
            self.selection = {face} if face >= 0 else set()
        self.update()
        self.selection_changee.emit()

    def mousePressEvent(self, ev):
        self._appui = (ev.position(), ev.button())
        super().mousePressEvent(ev)

    def wheelEvent(self, ev):
        self._zoom_recent.start()
        super().wheelEvent(ev)

    def mouseReleaseEvent(self, ev):
        appui, self._appui = self._appui, None
        super().mouseReleaseEvent(ev)
        if appui is None or appui[1] != Qt.MouseButton.LeftButton:
            return
        d = ev.position() - appui[0]
        if abs(d.x()) + abs(d.y()) > _CLIC_MAX:
            return
        p = ev.position()
        ajouter = bool(ev.modifiers() & (
            Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.ShiftModifier))
        f = self.clic_avant_face
        if callable(f) and f(p.x(), p.y(), ajouter):
            return
        self.choisir(self.face_au_point(p.x(), p.y()), ajouter)

    def _bornes(self):
        """(mini, maxi) de tout ce que la scène montre, ou None."""
        tous = [self._tri.reshape(-1, 3),
                self._tri_matiere.reshape(-1, 3)] + self._aretes + [
            p for c in self._calques + self._calques_parcours
            for p in c['pts']]
        tous = [t for t in tous if len(t)]
        if not tous:
            return None
        pts = np.vstack(tous)
        return pts.min(axis=0), pts.max(axis=0)

    def _cadrer(self, bornes) -> None:
        if bornes is None:
            self._x = self._y = self._z = np.zeros(0)
            return
        mn, mx = bornes
        self._centre = tuple(float(v) for v in (mn + mx) / 2)
        self._etendue = max(float(mx[0] - mn[0]), float(mx[1] - mn[1]),
                            float(mx[2] - mn[2]), 1e-3)
        self._z_bas, self._z_haut = float(mn[2]), float(mx[2])
        # Vue3D teste la présence d'un parcours: un point suffit
        self._x = np.array([mn[0], mx[0]])
        self._y = np.array([mn[1], mx[1]])
        self._z = np.array([mn[2], mx[2]])

    def set_machine(self, triangles=None, couleurs=None,
                    aretes=None) -> None:
        """La machine autour de la pièce: table, étau ou mandrin
        (triangles), enveloppe des courses (arêtes). Le cadrage reste
        celui de la pièce."""
        self._tri_machine = (np.asarray(triangles, dtype=float)
                             if triangles is not None and len(triangles)
                             else np.zeros((0, 3, 3)))
        self._col_machine = (np.asarray(couleurs, dtype=float)
                             if couleurs is not None and len(couleurs)
                             else np.tile([0.4, 0.42, 0.5],
                                          (len(self._tri_machine), 1)))
        self._aretes_machine = [np.asarray(a, dtype=float)
                                for a in (aretes or []) if len(a) >= 2]
        self.update()

    def set_matiere(self, triangles=None, couleurs=None, grossier=None,
                    cadrer: bool = False) -> None:
        """Le brut creusé: ses triangles et leurs couleurs (0–1), et
        `grossier` (triangles, couleurs) pour les rotations. `cadrer`:
        la vue se recadre pour le montrer en entier."""
        vide3, vide = np.zeros((0, 3, 3)), np.zeros((0, 3))
        if triangles is None or not len(triangles):
            self._tri_matiere, self._col_matiere = vide3, vide
        else:
            self._tri_matiere = np.asarray(triangles, dtype=float)
            self._col_matiere = np.asarray(couleurs, dtype=float)
        if grossier is None or not len(grossier[0]):
            self._tri_matiere_grossier, self._col_matiere_grossier = \
                vide3, vide
        else:
            self._tri_matiere_grossier = np.asarray(grossier[0], float)
            self._col_matiere_grossier = np.asarray(grossier[1], float)
        if cadrer:
            self._cadrer(self._bornes())
        self.update()

    def n_triangles_matiere(self) -> int:
        return int(len(self._tri_matiere))

    def set_parcours(self, calques, outil=None) -> None:
        """L'avance a bougé: le parcours jusque-là, l'outil au bout —
        sans recadrer la vue."""
        self._calques_parcours = list(calques or [])
        self.outil = outil
        self.update()

    def n_triangles(self) -> int:
        return int(len(self._tri))

    def exag_auto(self) -> float:
        return 1.0

    # ──── Projection ────

    def _vue(self, P):
        """(x écran px, y écran px, profondeur) de points (N, 3)."""
        cx, cy, cz = self._centre
        X = P[:, 0] - cx
        Y = P[:, 1] - cy
        Z = (P[:, 2] - cz) * self.exag
        a = math.radians(self.lacet)
        e = math.radians(self.elevation)
        x1 = X * math.cos(a) - Y * math.sin(a)
        y1 = X * math.sin(a) + Y * math.cos(a)
        haut = Z * math.cos(e) + y1 * math.sin(e)
        prof = y1 * math.cos(e) - Z * math.sin(e)
        s = self._echelle()
        px = self.width() / 2.0 + self.decalage.x() + x1 * s
        py = self.height() / 2.0 + self.decalage.y() - haut * s
        return px, py, prof

    def _vue_de_triangles(self, T):
        """(x écran, y écran, profondeur) de triangles (N, 3, 3), chacun de
        forme (3, N): un tableau par sommet. La même chose que `_vue`, comme la
        vue est linéaire, en un produit de matrices: 540 000 sommets, 32 ms
        par `_vue`."""
        a = math.radians(self.lacet)
        e = math.radians(self.elevation)
        s = self._echelle()
        z = self.exag
        ca, sa, ce, se = math.cos(a), math.sin(a), math.cos(e), math.sin(e)
        M = np.array(((s * ca, -s * sa, 0.0),
                      (-s * sa * se, -s * ca * se, -s * z * ce),
                      (sa * ce, ca * ce, -z * se)))
        centre = M @ np.asarray(self._centre, dtype=float)
        decale = np.array((self.width() / 2.0 + self.decalage.x(),
                           self.height() / 2.0 + self.decalage.y(),
                           0.0)) - centre
        n = len(T)
        sortie = np.empty((3, 3, n))
        for k in range(3):
            R = np.array(T[:, k, :].T, order='C')
            sortie[:, k, :] = M @ R
            sortie[0, k, :] += decale[0]
            sortie[1, k, :] += decale[1]
            sortie[2, k, :] += decale[2]
        return sortie[0], sortie[1], sortie[2]

    def _normales_du_morceau(self, T):
        """Les normales (dans l'espace de la vue avant sa rotation: Z à
        l'échelle `exag`) de triangles qui ne changent pas: gardées, seule la
        caméra tourne d'une image à l'autre."""
        gardees = self._normales_gardees
        fait = gardees.get(id(T))
        if fait is not None and fait[0] is T and fait[1] == self.exag:
            return fait[2]
        n = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
        n[:, 2] *= 1.0 / max(self.exag, 1e-9)
        norme = np.linalg.norm(n, axis=1)
        n = n / np.where(norme == 0, 1, norme)[:, None]
        gardees[id(T)] = (T, self.exag, n)
        return n

    def _eclairage(self, T):
        """La lumière reçue par chaque triangle (les deux côtés d'une face
        reçoivent la même): un produit par la lumière ramenée à l'espace des
        normales."""
        a = math.radians(self.lacet)
        e = math.radians(self.elevation)
        lx, ly, lz = _LUMIERE
        m = ly * math.sin(e) + lz * math.cos(e)
        v = np.array((lx * math.cos(a) + m * math.sin(a),
                      -lx * math.sin(a) + m * math.cos(a),
                      ly * math.cos(e) - lz * math.sin(e)))
        return 0.28 + 0.72 * np.abs(self._normales_du_morceau(T) @ v)

    # ──── Dessin ────

    #: ce qu'une copie de la vue reprend (données, réglages, cadrage)
    _ATTRIBUTS_COPIE = (
        '_tri', '_tri_col', '_tri_face', '_aretes', '_calques',
        '_calques_parcours', 'outil', 'montrer_parcours', '_tri_matiere',
        '_col_matiere', 'montrer_matiere', 'opacite_matiere', 'opacites',
        'montrer_piece', 'montrer_aretes', 'montrer_operations',
        'montrer_dessin', 'transparente', 'exag', 'faces_rouges',
        'montrer_rouges', '_centre', '_etendue', '_z_bas', '_z_haut',
        '_x', '_y', '_z', 'lacet', 'elevation', 'zoom', 'decalage',
        'rapides', 'couleur_fond')

    def copie(self, largeur: int, hauteur: int) -> "VueScene":
        """Une vue hors écran de la même scène (mêmes données, même
        caméra), à la taille voulue — pour l'image d'export."""
        autre = VueScene()
        for nom in self._ATTRIBUTS_COPIE:
            if hasattr(self, nom):
                valeur = getattr(self, nom)
                if isinstance(valeur, (set, list, dict)):
                    valeur = type(valeur)(valeur)
                setattr(autre, nom, valeur)
        autre.selection = set()
        autre.montrer_machine = False
        autre.collisions = []
        autre.resize(int(largeur), int(hauteur))
        return autre

    def recadrer(self) -> None:
        """Le cadrage sur tout ce que la scène montre."""
        self._cadrer(self._bornes())

    def image(self):
        """La vue rendue (QImage), sans l'afficher."""
        return self.grab().toImage()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.fillRect(self.rect(), self.couleur_fond)
        vide = (not len(self._tri) and not self._aretes
                and not len(self._tri_matiere)
                and not any(c['pts'] for c in self._calques)
                and not any(c['pts'] for c in self._calques_parcours))
        if vide:
            p.setPen(QColor("#6c7086"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "Rien à montrer en 3D: importez une pièce STEP, "
                       "un dessin, ou ajoutez des opérations")
            p.end()
            return
        en_rotation = (self._glisse is not None
                       or self._zoom_recent.isActive())
        parcours = (self._calques_parcours if self.montrer_parcours
                    else [])
        # réduits à l'écran: un point par 0,75 px de chemin (2 px
        # pendant une rotation) — 400 000 sommets coûtaient 0,7 s
        # par image, et l'oeil n'y voit pas de différence
        pas = 2.0 if en_rotation else 0.75
        if self.lecture_en_cours and not en_rotation:
            # la lecture: l'image gardée, puis le tronçon en cours. La
            # matière change pendant la lecture: sa couche à elle, les
            # traits gardés par-dessus
            matiere = bool(self.montrer_matiere and len(self._tri_matiere))
            if matiere:
                p.drawImage(0, 0, self._image_de_la_piece())
            p.drawImage(0, 0, self._image_de_lecture(parcours, matiere))
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            for calque in parcours:
                if calque.get('partiel') and calque['pts']:
                    p.setPen(self._stylo_calque(calque, 'parcours'))
                    self._tracer_morceaux(p, calque['pts'][-1:], pas)
        elif en_rotation:
            self._image_lecture = self._image_repos = None
            self._image_piece = self._image_estompee = None
            p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            self._dessiner_piece(p, True)
            scene = self._sans_doublons(parcours)
            if not self._tracer_en_points(p, scene, parcours):
                self._dessiner_calques(p, scene, pas, rapide=True)
                self._dessiner_calques(p, parcours, pas, 'parcours',
                                       rapide=True)
        else:
            self._image_lecture = self._image_piece = None
            neutres = self._neutres_valides()
            if neutres is not None:
                # des opérations choisies dans la liste: la scène toute
                # estompée (gardée d'un choix à l'autre), elles par-dessus
                p.drawImage(0, 0, self._image_toute_estompee(*neutres))
                p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                self._dessiner_choisies(p, parcours)
            else:
                p.drawImage(0, 0, self._image_au_repos(parcours))
                p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            self._planifier_image_voisine()
        if self.montrer_machine and self._aretes_machine:
            # l'enveloppe des courses, en pointillés
            enveloppe = QColor("#6c7086")
            enveloppe.setAlphaF(max(0.0, min(1.0, float(
                (getattr(self, 'opacites', {}) or {}).get('machine', 1.0)))))
            p.setPen(QPen(enveloppe, 1.0, Qt.PenStyle.DashLine))
            for pts in self._aretes_machine:
                px, py, _d = self._vue(pts)
                p.drawPolyline(polygone_xy(px, py))
        if self.outil is not None and self.montrer_parcours:
            self._dessiner_outil(p)
        if self.collisions:
            # les collisions de la broche: des cercles rouges
            p.setPen(QPen(QColor("#f38ba8"), 2.0))
            pts = np.array([c[:3] for c in self.collisions], dtype=float)
            px, py, _d = self._vue(pts)
            for a, b in zip(px.tolist(), py.tolist()):
                p.drawEllipse(QPointF(a, b), 7.0, 7.0)
                p.drawLine(QPointF(a - 5, b - 5), QPointF(a + 5, b + 5))
                p.drawLine(QPointF(a - 5, b + 5), QPointF(a + 5, b - 5))
        self._dessiner_triedre(p)
        p.end()

    def _stylo_calque(self, calque: dict, entite: str,
                      rapide: bool = False, estompe: bool = False) -> QPen:
        """Le stylo d'un calque, à l'opacité de son entité. `rapide`: un
        pixel, « cosmétique »: c'est le tracé direct de Qt; plus large, ou
        grossi par l'échelle de l'écran, chaque trait devient un contour à
        remplir (un tiers de l'image, pour une vue qui bouge). `estompe`:
        celui d'une opération (tracé ou parcours) qui n'est pas choisie
        dans la liste (`Canvas3D._marquer_choix`); le dessin ne change
        pas."""
        couleur = QColor(calque['couleur'])
        facteur = float((getattr(self, 'opacites', {}) or {}).get(entite,
                                                                   1.0))
        if estompe and calque.get('genre') in ('operation', 'parcours'):
            facteur *= ESTOMPE_AUTRES
        if facteur < 1.0:
            couleur.setAlphaF(couleur.alphaF() * max(0.0, facteur))
        stylo = QPen(couleur, float(calque.get('largeur', 1.2)),
                     calque.get('style', Qt.PenStyle.SolidLine))
        if rapide:
            stylo.setWidthF(1.0)
            stylo.setCosmetic(True)
        return stylo

    def _sans_doublons(self, parcours, calques=None) -> list:
        """Les calques de la scène à tracer: le tracé d'une opération
        importée EST son parcours simulé, deux fois les mêmes sommets. Quand
        le parcours est là, entier et au moins aussi visible, il suffit;
        pendant une lecture, le tracé montre ce qui reste à faire.
        `calques`: d'autres que ceux de la vue (ses calques sans choix)."""
        calques = self._calques if calques is None else calques
        opac = getattr(self, 'opacites', {}) or {}
        if not parcours or self.outil is not None or \
                float(opac.get('parcours', 1.0)) < float(
                    opac.get('operations', 1.0)):
            return calques
        return [c for c in calques if not c.get('doublon')]

    def _calques_montres(self, calques, entite: str = None):
        """(calque, son entité) de ceux que les cases laissent voir."""
        for calque in calques:
            genre = calque.get('genre', 'operation')
            if genre == 'operation' and not self.montrer_operations:
                continue
            if genre == 'dessin' and not self.montrer_dessin:
                continue
            yield calque, entite or ('dessin' if genre == 'dessin'
                                     else 'operations')

    def _dessiner_calques(self, p: QPainter, calques, pas: float,
                          entite: str = None, rapide: bool = False,
                          estompe: bool = False) -> None:
        """Les calques de traits (opérations, dessin — ou le parcours,
        `entite` 'parcours'), chacun à son stylo (`estompe`: les
        opérations comme si aucune n'était choisie)."""
        for calque, qui in self._calques_montres(calques, entite):
            p.setPen(self._stylo_calque(calque, qui, rapide, estompe))
            self._tracer_calque(p, calque, pas)

    def _tracer_en_points(self, p: QPainter, scene, parcours) -> bool:
        """Les traits d'une vue qui bouge, en points dans une image
        (`traits_en_points`), s'il y en a assez pour que ça vaille la peine.
        Rend vrai si c'est fait. Les plus pâles d'abord: chaque point
        remplace celui d'en dessous, le trait franc reste au-dessus."""
        a_tracer = []
        total = 0
        for calques, entite in ((scene, None), (parcours, 'parcours')):
            for calque, qui in self._calques_montres(calques, entite):
                P, debuts = self._sommets_du_calque(calque)
                if P is not None:
                    a_tracer.append((calque, qui, P, debuts))
                    total += len(P)
        if total < tp.SOMMETS_EN_POINTS:
            return False
        tampon = np.zeros((max(1, self.height()), max(1, self.width())),
                          dtype=np.uint32)
        styles = []
        for calque, qui, P, debuts in a_tracer:
            couleur = self._stylo_calque(calque, qui).color()
            styles.append((couleur.alpha(), len(styles), couleur, calque, P,
                           debuts))
        for _a, _k, couleur, calque, P, debuts in sorted(
                styles, key=lambda s: s[:2]):
            px, py, _d = self._vue(P)
            tp.tracer(tampon, px, py, debuts,
                      tp.couleur_premultipliee(couleur),
                      calque.get('style') == Qt.PenStyle.DashLine)
        # (à l'échelle de l'écran: le rectangle est en pixels logiques)
        image = QImage(tampon.data, tampon.shape[1], tampon.shape[0],
                       tampon.shape[1] * 4,
                       QImage.Format.Format_ARGB32_Premultiplied)
        p.drawImage(self.rect(), image)
        return True

    @staticmethod
    def _complets(calque: dict) -> int:
        """Les tronçons finis d'un calque du parcours (le dernier est en
        cours quand le calque est `partiel`)."""
        return len(calque['pts']) - (1 if calque.get('partiel') else 0)

    @staticmethod
    def _cle_calque(calque: dict) -> tuple:
        # un calque du parcours porte son identité (genre, couleur,
        # opacité, choix): deux opérations aux opacités voisines donnent
        # le même stylo sans être le même calque — comptés ensemble,
        # leurs tronçons finis ne se traçaient plus (les avances en l'air
        # disparaissaient pendant la lecture)
        cle = calque.get('cle')
        if cle is not None:
            return ('cle',) + tuple(cle)
        return (calque.get('genre'), QColor(calque['couleur']).rgba(),
                float(calque.get('largeur', 1.2)),
                calque.get('style', Qt.PenStyle.SolidLine))

    def _cle_de_lecture(self) -> tuple:
        """Tout ce qui change l'image gardée de la lecture, sauf les
        données (comparées par identité: `_donnees_de_scene`)."""
        d = self.decalage
        return (self.width(), self.height(), float(self.devicePixelRatioF()),
                self.lacet, self.elevation, self.zoom, d.x(), d.y(),
                self.exag, tuple(float(v) for v in self._centre),
                float(self._etendue), self.transparente, self.montrer_piece,
                self.montrer_aretes, self.montrer_operations,
                self.montrer_dessin, self.montrer_parcours,
                self.montrer_machine, self.montrer_rouges,
                self.montrer_matiere,
                tuple(sorted((getattr(self, 'opacites', {}) or {}).items())),
                float(self.opacite_matiere),
                QColor(self.couleur_fond).rgba(),
                frozenset(self.selection), frozenset(self.faces_rouges))

    def _donnees_de_scene(self, calques=None) -> tuple:
        # gardées par l'image: leur identité ne peut pas resservir
        return (self._tri, self._tri_col, self._tri_face, self._aretes,
                self._calques if calques is None else calques,
                self._tri_matiere, self._col_matiere,
                self._tri_machine, self._col_machine)

    def _image_de_lecture(self, parcours, sans_piece: bool = False) -> QImage:
        """La scène et les tronçons finis du parcours, en image: refaite
        quand la vue ou la scène change, ou quand la lecture recule;
        sinon seuls les tronçons finis depuis l'image précédente y sont
        ajoutés (une image coûtait tout le parcours: 0,1 s à 84 000
        sommets). `sans_piece`: les traits seuls, sur fond transparent, à
        poser sur la matière (elle change sans qu'ils changent)."""
        cle = self._cle_de_lecture() + (sans_piece,)
        donnees = ((self._calques,) if sans_piece
                   else self._donnees_de_scene())
        cache = self._image_lecture
        if cache is not None and (
                cache['cle'] != cle
                or any(a is not b for a, b in zip(cache['donnees'],
                                                  donnees))):
            cache = None
        if cache is not None:
            courants = {self._cle_calque(c): c for c in parcours}
            if any(k not in courants or self._complets(courants[k]) < m
                   for k, m in cache['faits'].items()):
                cache = None            # la lecture a reculé
        if cache is None:
            image = self._image_vierge(transparente=sans_piece)
            q = QPainter(image)
            q.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            if not sans_piece:
                self._dessiner_piece(q, False)
            self._dessiner_calques(q, self._calques, 0.75)
            q.end()
            cache = {'cle': cle, 'donnees': donnees, 'image': image,
                     'faits': {}}
            self._image_lecture = cache
        q = None
        for calque in parcours:
            k = self._cle_calque(calque)
            fait, complets = cache['faits'].get(k, 0), self._complets(calque)
            if complets > fait:
                if q is None:
                    q = QPainter(cache['image'])
                    q.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                q.setPen(self._stylo_calque(calque, 'parcours'))
                self._tracer_morceaux(q, calque['pts'][fait:complets], 0.75)
                cache['faits'][k] = complets
        if q is not None:
            q.end()
        return cache['image']

    def _image_de_la_piece(self) -> QImage:
        """La pièce et la matière seules, en image: une lecture lente passe
        bien des images sans enlever de matière, il n'y a rien à repeindre
        (16 000 triangles: 60 ms)."""
        cache = self._image_piece
        cle = self._cle_de_lecture()
        donnees = self._donnees_de_scene()
        if cache is not None and cache['cle'] == cle and all(
                a is b for a, b in zip(cache['donnees'], donnees)):
            return cache['image']
        image = self._image_vierge()
        q = QPainter(image)
        q.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._dessiner_piece(q, False)
        q.end()
        self._image_piece = {'cle': cle, 'donnees': donnees, 'image': image}
        return image

    def _image_vierge(self, transparente: bool = False) -> QImage:
        """Une image de la taille de la vue, à sa couleur de fond (s'il
        est transparent, elle se pose sur lui: elle reste transparente)."""
        dpr = max(1.0, float(self.devicePixelRatioF()))
        image = QImage(max(1, int(round(self.width() * dpr))),
                       max(1, int(round(self.height() * dpr))),
                       QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(dpr)
        fond = QColor(self.couleur_fond)
        image.fill(fond if fond.alpha() == 255 and not transparente
                   else QColor(0, 0, 0, 0))
        return image

    def _image_au_repos(self, parcours, calques=None,
                        tout_parcours=None) -> QImage:
        """La pièce, les calques et le parcours, en image: refaite quand
        la vue ou la scène change, sinon reprise telle quelle (un programme
        de 84 000 sommets: 100 ms à chaque repeint, pour la même image).
        `calques`, `tout_parcours`: d'autres listes que celles de la vue
        (celles sans choix, préparées pendant un choix)."""
        scene = (self._sans_doublons(parcours) if calques is None
                 else self._sans_doublons(parcours, calques))
        calques = self._calques if calques is None else calques
        tout = (self._calques_parcours if tout_parcours is None
                else tout_parcours)
        cache = self._image_repos
        cle = self._cle_de_lecture()
        donnees = self._donnees_de_scene(calques) + (tout,)
        if self._image_gardee(cache, cle, donnees):
            return cache['image']
        image = self._image_vierge()
        q = QPainter(image)
        q.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._dessiner_piece(q, False)
        self._dessiner_calques(q, scene, 0.75)
        self._dessiner_calques(q, parcours, 0.75, 'parcours')
        q.end()
        self._image_repos = {'cle': cle, 'donnees': donnees, 'image': image}
        return image

    @staticmethod
    def _image_gardee(cache, cle, donnees) -> bool:
        return cache is not None and cache['cle'] == cle and all(
            a is b for a, b in zip(cache['donnees'], donnees))

    # ── les opérations choisies dans la liste ──

    def _marquees(self) -> bool:
        """Les calques montrés portent-ils un choix d'opérations?"""
        return any(c.get('choix') is not None
                   for c in itertools.chain(self._calques,
                                            self._calques_parcours))

    def _neutres_valides(self):
        """(calques, parcours) sans choix des calques marqués que la vue
        montre, s'ils ont été posés avec eux (`poser_neutres`); sinon
        None."""
        n = self._neutres
        if n is None or n[2] is not self._calques \
                or n[3] is not self._calques_parcours:
            return None
        return n[0], n[1]

    def listes_neutres(self):
        """Les listes (calques, parcours) sans choix d'opérations: celles
        montrées si aucune n'est choisie, sinon celles posées avec elles;
        None si elles ne sont plus là."""
        if not self._marquees():
            return self._calques, self._calques_parcours
        return self._neutres_valides()

    def poser_neutres(self, calques, parcours) -> None:
        """Les listes sans choix des calques marqués montrés maintenant:
        l'image estompée se fait d'elles, une fois pour tous les choix."""
        self._neutres = (calques, parcours, self._calques,
                         self._calques_parcours)
        self.update()

    def montrer_neutres(self, calques, parcours) -> None:
        """Plus rien de choisi: les listes sans choix reviennent telles
        quelles (les mêmes: leur image au repos est souvent encore là)."""
        self._calques = calques
        self._calques_parcours = parcours
        self._neutres = None
        self._image_lecture = None
        self.update()

    def _image_toute_estompee(self, calques, tout_parcours) -> QImage:
        """La pièce et TOUTES les opérations estompées (le dessin tel
        quel), comme si aucune n'était choisie: la même d'un choix à
        l'autre, gardée — seules les choisies se tracent par-dessus
        (`_dessiner_choisies`)."""
        parcours = tout_parcours if self.montrer_parcours else []
        cache = self._image_estompee
        cle = self._cle_de_lecture()
        donnees = self._donnees_de_scene(calques) + (tout_parcours,)
        if self._image_gardee(cache, cle, donnees):
            return cache['image']
        image = self._image_vierge()
        q = QPainter(image)
        q.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._dessiner_piece(q, False)
        self._dessiner_calques(q, self._sans_doublons(parcours, calques),
                               0.75, estompe=True)
        self._dessiner_calques(q, parcours, 0.75, 'parcours', estompe=True)
        q.end()
        self._image_estompee = {'cle': cle, 'donnees': donnees,
                                'image': image}
        return image

    def _dessiner_choisies(self, p: QPainter, parcours) -> None:
        """Les calques des opérations choisies, en avant: par-dessus
        tout le reste."""
        self._dessiner_calques(
            p, [c for c in self._sans_doublons(parcours)
                if c.get('choix') is True], 0.75)
        self._dessiner_calques(
            p, [c for c in parcours if c.get('choix') is True], 0.75,
            'parcours')

    #: l'image voisine se prépare après ce délai (ms), à la pause de
    #: l'utilisateur (`activite`)
    IMAGE_VOISINE_MS = 400

    def _image_voisine(self):
        """(fabrique, arguments) de l'image qu'un changement de choix
        demandera — l'estompée quand rien n'est choisi, celle sans choix
        pendant un choix —, ou None: déjà là, ou rien à choisir."""
        neutres = self._neutres_valides()
        if neutres is not None:
            calques, tout = neutres
            cache, fabrique = self._image_repos, self._image_au_repos
            arguments = (tout if self.montrer_parcours else [], calques,
                         tout)
        else:
            if self._marquees() or not self._calques_d_operations():
                return None
            calques, tout = self._calques, self._calques_parcours
            cache, fabrique = (self._image_estompee,
                               self._image_toute_estompee)
            arguments = (calques, tout)
        donnees = self._donnees_de_scene(calques) + (tout,)
        if self._image_gardee(cache, self._cle_de_lecture(), donnees):
            return None
        return fabrique, arguments

    def _calques_d_operations(self) -> bool:
        """Y a-t-il des traits qu'un choix d'opérations estomperait?"""
        return bool(self._calques_parcours) or any(
            c.get('genre') == 'operation' for c in self._calques)

    def _planifier_image_voisine(self) -> None:
        if not self.isVisible() or self._minuterie_voisine.isActive() \
                or self._image_voisine() is None:
            return
        from src.gui import activite
        # planifiée par un repeint, pas par un geste: elle ne retarde pas
        # les autres attentes (la régénération du SimPL)
        activite.veiller(self._jeton_activite, geste=False)
        self._minuterie_voisine.start(self.IMAGE_VOISINE_MS)

    def _preparer_image_voisine(self) -> None:
        from src.gui import activite
        if activite.occupe():
            self._minuterie_voisine.start(activite.attente_restante())
            return
        activite.relacher(self._jeton_activite)
        if (not self.isVisible() or self.lecture_en_cours
                or self._glisse is not None
                or self._zoom_recent.isActive()):
            return
        voisine = self._image_voisine()
        if voisine is not None:
            fabrique, arguments = voisine
            fabrique(*arguments)

    @staticmethod
    def _sommets_du_calque(calque: dict):
        """Les polylignes du calque mises bout à bout (tableau (N, 3))
        et le début de chacune — gardés dans le calque: ses points ne
        changent pas d'une image à l'autre, seule la vue change."""
        cache = calque.get('_bout_a_bout')
        if cache is not None and cache[0] == len(calque['pts']):
            return cache[1], cache[2]
        morceaux = [np.asarray(m, dtype=float) for m in calque['pts']
                    if len(m) >= 2]
        if not morceaux:
            P = debuts = None
        else:
            longueurs = np.array([len(m) for m in morceaux])
            debuts = np.concatenate(([0], np.cumsum(longueurs)))
            P = (morceaux[0] if len(morceaux) == 1
                 else np.concatenate(morceaux))
        calque['_bout_a_bout'] = (len(calque['pts']), P, debuts)
        return P, debuts

    def _tracer_calque(self, p: QPainter, calque: dict, pas: float) -> None:
        """Les polylignes d'un calque, projetées TOUTES d'un coup (une
        par une, huit mille polylignes coûtaient plus que leurs points),
        réduites à l'écran, tracées."""
        P, debuts = self._sommets_du_calque(calque)
        if P is not None:
            self._tracer_points(p, P, debuts, pas)

    def _tracer_morceaux(self, p: QPainter, morceaux, pas: float) -> None:
        """Quelques polylignes (les tronçons ajoutés pendant la
        lecture), comme celles d'un calque."""
        morceaux = [np.asarray(m, dtype=float) for m in morceaux
                    if len(m) >= 2]
        if not morceaux:
            return
        debuts = np.concatenate(([0], np.cumsum([len(m) for m in morceaux])))
        self._tracer_points(p, morceaux[0] if len(morceaux) == 1
                            else np.concatenate(morceaux), debuts, pas)

    def _tracer_points(self, p: QPainter, P, debuts, pas: float) -> None:
        """Les polylignes P[debuts[i]:debuts[i+1]], projetées d'un coup,
        chacune réduite à un point par `pas` pixels de chemin — compté
        depuis SON début: une polyligne se trace pareil seule (ajoutée
        pendant la lecture) ou avec les autres."""
        px, py, _d = self._vue(P)
        n = len(px)
        d = np.hypot(np.diff(px), np.diff(py))
        d[debuts[1:-1] - 1] = 0.0      # pas de chemin d'une polyligne à l'autre
        cumul = np.concatenate(([0.0], np.cumsum(d)))
        cumul -= np.repeat(cumul[debuts[:-1]], np.diff(debuts))
        k = np.floor(cumul / pas)
        garde = np.empty(n, dtype=bool)
        garde[0] = True
        garde[1:] = k[1:] != k[:-1]
        garde[debuts[:-1]] = True       # chaque polyligne garde ses bouts
        garde[debuts[1:] - 1] = True
        idx = np.flatnonzero(garde)
        bornes = np.searchsorted(idx, debuts).tolist()
        # tous les points d'un bloc (un QPointF par point en coûtait autant
        # que le tracé lui-même), chaque polyligne en est un extrait: en
        # remplir une à une prenait 80 % d'une image pendant une rotation
        tous = polygone(np.column_stack([px[idx], py[idx]]))
        if len(bornes) == 2:
            if len(tous) >= 2:
                p.drawPolyline(tous)
            return
        extrait, trace = tous.mid, p.drawPolyline
        for a, b in zip(bornes[:-1], bornes[1:]):
            if b - a >= 2:
                trace(extrait(a, b - a))

    @staticmethod
    def contour_outil(forme: dict, x: float, y: float, z: float,
                      rayon: float = None, profil=None) -> list:
        """Le fil de l'outil à sa forme, la pointe en (x, y, z): des
        polylignes 3D — cylindre (plate, filet: ses dents en anneaux),
        cône (chanfrein, gravure, foret), boule, fraise en T (disque et
        tige). Avec `profil` (les (r, z) de `dessin_outil.profil`, de
        la pointe à la queue), l'outil RÉEL: un anneau à chaque point,
        quatre génératrices qui suivent le profil."""
        forme = dict(forme or {})
        r = max(0.05, float(rayon if rayon is not None
                            else forme.get('rayon', 1.0)))
        genre = forme.get('forme', 'plate')
        t = np.linspace(0, 2 * math.pi, 33)

        def anneau(rr, zz):
            return np.column_stack([x + rr * np.cos(t), y + rr * np.sin(t),
                                    np.full(len(t), zz)])

        if profil is not None and len(profil) >= 2:
            pr = np.asarray(profil, dtype=float)
            sortie = [anneau(rr, z + zz) for rr, zz in pr if rr > 0.02]
            for a in np.linspace(0, 2 * math.pi, 5)[:-1]:
                sortie.append(np.column_stack([
                    x + pr[:, 0] * math.cos(a), y + pr[:, 0] * math.sin(a),
                    z + pr[:, 1]]))
            return sortie

        def generatrices(r0, z0, r1, z1):
            return [np.array([(x + r0 * math.cos(a), y + r0 * math.sin(a),
                               z0), (x + r1 * math.cos(a),
                                     y + r1 * math.sin(a), z1)])
                    for a in np.linspace(0, 2 * math.pi, 5)[:-1]]

        h = max(6.0, 4.0 * r)
        if genre == 'cone':
            demi = math.radians(max(1.0, float(forme.get('angle') or 90.0))
                                / 2)
            rp = max(0.0, float(forme.get('pointe') or 0.0) / 2.0)
            hc = max(0.01, (r - rp) / math.tan(demi))
            sortie = [anneau(r, z + hc), anneau(r, z + hc + h)]
            if rp > 0.01:
                sortie.append(anneau(rp, z))
            sortie += generatrices(rp, z, r, z + hc)
            sortie += generatrices(r, z + hc, r, z + hc + h)
            return sortie
        if genre == 'boule':
            sortie = [anneau(r, z + r), anneau(r, z + r + h)]
            for f in (0.35, 0.7):
                sortie.append(anneau(r * math.sqrt(1 - (1 - f) ** 2),
                                     z + f * r))
            for a in np.linspace(0, math.pi, 3)[:-1]:
                u = np.linspace(-math.pi / 2, math.pi / 2, 17)
                sortie.append(np.column_stack([
                    x + r * np.sin(u) * math.cos(a),
                    y + r * np.sin(u) * math.sin(a),
                    z + r - r * np.cos(u)]))
            sortie += generatrices(r, z + r, r, z + r + h)
            return sortie
        if genre == 'tslot':
            hd = max(0.1, float(forme.get('hauteur', 1.0)))
            col = max(0.05, float(forme.get('col', 0.45 * r)))
            sortie = [anneau(r, z), anneau(r, z + hd), anneau(col, z + hd),
                      anneau(col, z + hd + h)]
            sortie += generatrices(r, z, r, z + hd)
            sortie += generatrices(col, z + hd, col, z + hd + h)
            return sortie
        sortie = [anneau(r, z), anneau(r, z + h)]
        if genre == 'filet':
            longueur = max(0.2, float(forme.get('longueur', 2 * r)))
            for k in range(1, 5):
                sortie.append(anneau(r, z + longueur * k / 5))
        sortie += generatrices(r, z, r, z + h)
        return sortie

    def _dessiner_outil(self, p: QPainter) -> None:
        """L'outil à sa place, à sa forme, la pointe en bas."""
        x, y, z = self.outil['pos']
        p.setPen(QPen(QColor(249, 226, 175), 1.6))
        for pts in self.contour_outil(self.outil.get('forme') or {}, x, y, z,
                                      self.outil.get('rayon'),
                                      self.outil.get('profil')):
            px, py, _d = self._vue(pts)
            p.drawPolyline(polygone_xy(px, py))
        if self.montrer_machine and self.outil.get('broche'):
            # la broche au-dessus de l'outil (écrou, nez, corps)
            p.setPen(QPen(QColor(205, 214, 244), 1.2))
            for pts in self.outil['broche']:
                px, py, _d = self._vue(pts)
                p.drawPolyline(polygone_xy(px, py))
        px, py, _d = self._vue(np.array([[x, y, z]]))
        p.setBrush(QBrush(QColor(249, 226, 175)))
        p.drawEllipse(QPointF(px[0], py[0]), 3.0, 3.0)
        p.setBrush(Qt.BrushStyle.NoBrush)

    def _morceaux_a_peindre(self, en_rotation: bool) -> list:
        """La pièce, la machine et la matière: [(triangles, couleurs, alpha de
        chacun de 0 à 255, priorité si des faces se confondent)]."""
        morceaux, couleurs = [], []
        alphas = []
        priorites = []
        opac = getattr(self, 'opacites', {}) or {}

        def _a(cle, base=255.0):
            return base * max(0.0, min(1.0, float(opac.get(cle, 1.0))))
        if self.montrer_piece and len(self._tri):
            morceaux.append(self._tri)
            col = self._tri_col
            a_piece = np.full(len(self._tri), _a(
                'piece', 95.0 if self.transparente else 255.0))
            if self.montrer_rouges and self.faces_rouges and \
                    len(self._tri_face) == len(col):
                col = col.copy()
                rouges = np.isin(self._tri_face, list(self.faces_rouges))
                col[rouges] = COULEUR_INACCESSIBLE
                a_piece[rouges] = _a('rouges', 95.0 if self.transparente
                                     else 255.0)
            if self.selection and len(self._tri_face) == len(col):
                col = col.copy()
                col[np.isin(self._tri_face, list(self.selection))] = \
                    COULEUR_SELECTION
            couleurs.append(col)
            alphas.append(a_piece)
            priorites.append(0)
        if self.montrer_machine and len(self._tri_machine):
            morceaux.append(self._tri_machine)
            couleurs.append(self._col_machine)
            alphas.append(np.full(len(self._tri_machine), _a('machine')))
            priorites.append(2)
        if self.montrer_matiere and len(self._tri_matiere):
            t, c = self._tri_matiere, self._col_matiere
            if en_rotation and len(t) > _TRI_MAX_EN_ROTATION and \
                    len(self._tri_matiere_grossier):
                t, c = (self._tri_matiere_grossier,
                        self._col_matiere_grossier)
            if len(t):
                morceaux.append(t)
                couleurs.append(c)
                alphas.append(np.full(len(t), 255.0 * max(0.0, min(
                    1.0, float(getattr(self, 'opacite_matiere', 1.0))))))
                priorites.append(1)
        return list(zip(morceaux, couleurs, alphas, priorites))

    def _aretes_bout_a_bout(self):
        """Les arêtes de la pièce mises bout à bout: (sommets, débuts), ou
        (None, None); gardées, seule la vue change d'une image à l'autre."""
        fait = self._aretes_jointes
        if fait is not None and fait[0] is self._aretes \
                and fait[1] == len(self._aretes):
            return fait[2], fait[3]
        morceaux = [a for a in self._aretes if len(a) >= 2]
        if morceaux:
            debuts = np.cumsum([0] + [len(a) for a in morceaux])
            sommets = np.concatenate(morceaux)
        else:
            debuts = sommets = None
        self._aretes_jointes = (self._aretes, len(self._aretes), sommets,
                                debuts)
        return sommets, debuts

    def _couleur_des_aretes(self) -> QColor:
        couleur = QColor(_ARETE if not self.transparente
                         else QColor(205, 214, 244, 160))
        facteur = float((getattr(self, 'opacites', {}) or {}).get(
            'aretes', 1.0))
        if facteur < 1.0:
            couleur.setAlphaF(couleur.alphaF() * max(0.0, facteur))
        return couleur

    def _dessiner_piece(self, p: QPainter, en_rotation: bool) -> None:
        """Les faces et les arêtes, d'un seul passage dans une image. Une vue
        qui bouge règle sa finesse sur le temps de l'image d'avant: elle ne
        perd jamais la pièce, au pire ses détails le temps du geste."""
        morceaux = self._morceaux_a_peindre(en_rotation)
        sommets, debuts = (self._aretes_bout_a_bout() if self.montrer_aretes
                           else (None, None))
        if not morceaux and sommets is None:
            return
        debut = time.perf_counter()
        dpr = max(1.0, float(self.devicePixelRatioF()))
        finesse = self._finesse_en_mouvement if en_rotation else dpr
        r = Raster(round(self.width() * finesse),
                   round(self.height() * finesse))
        ecart = _ECART_DE_PRIORITE * float(self._etendue)
        for tri, col, alpha, priorite in morceaux:
            tx, ty, td = self._vue_de_triangles(tri)
            rgb = np.clip(np.asarray(col) * self._eclairage(tri)[:, None] * 255,
                          0, 255).astype(np.int64)
            r.triangles(tx * finesse, ty * finesse, td + priorite * ecart, rgb,
                        np.asarray(alpha).round().astype(np.int64))
        r.composer()
        # (seules celles de cette image: la matière change à chaque image d'une
        # lecture, et chaque maillage retenu pèse)
        peints = {id(m[0]) for m in morceaux}
        for cle in [c for c in self._normales_gardees if c not in peints]:
            del self._normales_gardees[cle]
        if sommets is not None:
            sx, sy, sd = self._vue(sommets)
            couleur = self._couleur_des_aretes()
            r.traits(sx * finesse, sy * finesse, sd, debuts,
                     (couleur.red(), couleur.green(), couleur.blue(),
                      couleur.alpha()), epaisseur=finesse,
                     lisse=p.testRenderHint(QPainter.RenderHint.Antialiasing),
                     biais=1e-3 * float(self._etendue))
        image = QImage(r.couleur.data, r.largeur, r.hauteur, r.largeur * 4,
                       QImage.Format.Format_ARGB32_Premultiplied)
        # (à l'échelle de la vue: le rectangle est en pixels logiques)
        p.drawImage(self.rect(), image)
        if en_rotation:
            duree = time.perf_counter() - debut
            if duree > _IMAGE_TROP_LENTE and finesse > 0.25:
                self._finesse_en_mouvement = finesse / 2.0
            elif duree < _IMAGE_TRES_RAPIDE and finesse < 1.0:
                self._finesse_en_mouvement = finesse * 2.0


#: les entités du Canva 3D: (clé, libellé, case de la barre)
ENTITES_3D = (('piece', "Pièce", 'cb_piece'),
              ('aretes', "Arêtes", 'cb_aretes'),
              ('rouges', "Faces inaccessibles", 'cb_rouges'),
              ('operations', "Opérations", 'cb_ops'),
              ('parcours', "Parcours simulé", 'cb_parcours'),
              ('dessin', "Dessin du canvas", 'cb_dessin'),
              ('matiere', "Matière (brut)", 'cb_matiere'),
              ('machine', "Machine", 'cb_machine'))


class PanneauEntites3D(QWidget):
    """Chaque entité du Canva 3D: son œil (le même que sa case de la
    barre) et sa transparence (5 à 100 %, retenue)."""

    def __init__(self, canvas, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QGridLayout, QToolButton
        self._canvas = canvas
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
        aide = QLabel("L'œil montre ou masque; le curseur règle "
                      "l'opacité (retenue d'une session à l'autre).")
        aide.setWordWrap(True)
        aide.setStyleSheet("color: #a6adc8; font-size: 10px;")
        v.addWidget(aide)
        grille = QGridLayout()
        grille.setSpacing(4)
        #: {clé: (œil, curseur, étiquette %)}
        self.lignes = {}
        for rang, (cle, libelle, attr) in enumerate(ENTITES_3D):
            case = getattr(canvas, attr)
            oeil = QToolButton(self)
            oeil.setCheckable(True)
            oeil.setAutoRaise(True)
            oeil.setChecked(case.isChecked())
            oeil.setToolTip(f"Montrer ou masquer: {libelle.lower()}")
            self._icone(oeil, case.isChecked())
            oeil.toggled.connect(
                lambda on, c=case, o=oeil: (self._icone(o, on),
                                            c.setChecked(on)))
            # (l'état de la case, pas l'argument du signal: décochée
            # pendant qu'elle se coche — un calcul de matière annulé —,
            # le signal du cochage arrive ici APRÈS celui du décochage,
            # et l'œil restait allumé sur une case éteinte)
            case.toggled.connect(
                lambda _on, o=oeil, c=case: self._suivre(o, c.isChecked()))
            nom = QLabel(libelle)
            curseur = QSlider(Qt.Orientation.Horizontal, self)
            curseur.setRange(5, 100)
            curseur.setMaximumWidth(110)
            curseur.setValue(int(round(canvas.opacite(cle) * 100)))
            curseur.setToolTip(f"Opacité: {libelle.lower()}")
            pc = QLabel(f"{curseur.value()} %")
            pc.setMinimumWidth(38)
            curseur.valueChanged.connect(
                lambda val, k=cle, e=pc: (e.setText(f"{val} %"),
                                          canvas.regler_opacite(
                                              k, val / 100.0)))
            grille.addWidget(oeil, rang, 0)
            grille.addWidget(nom, rang, 1)
            grille.addWidget(curseur, rang, 2)
            grille.addWidget(pc, rang, 3)
            self.lignes[cle] = (oeil, curseur, pc)
        grille.setColumnStretch(2, 1)
        v.addLayout(grille)
        v.addStretch(1)

    @staticmethod
    def _icone(bouton, visible: bool) -> None:
        from src.gui.icons import get_icon
        bouton.setIcon(get_icon("eye", 16,
                                "#89b4fa" if visible else "#6c7086"))

    def _suivre(self, oeil, on: bool) -> None:
        if oeil.isChecked() != bool(on):
            avant = oeil.blockSignals(True)
            oeil.setChecked(bool(on))
            oeil.blockSignals(avant)
        self._icone(oeil, on)


class Canvas3D(QWidget):
    """La vue et ses commandes."""

    retour_2d = Signal()
    actualiser_demande = Signal()
    #: « Importer STEP… »
    importer_demande = Signal()
    #: des opérations à ajouter au programme (format de
    #: operations_generated, plus 'tool_id')
    usinage_demande = Signal(list)
    #: « Usinage 3D… »: la gamme de fraises de toute la pièce
    usinage3d_demande = Signal()
    #: l'axe du haut de la pièce STEP a changé ('auto', 'Z', 'Y', 'X')
    axe_change = Signal(str)
    #: la transparence ou la division d'une opération a changé
    affichage_ops_change = Signal()
    #: l'œil d'une opération a été basculé au panneau 3D (l'opération)
    oeil_op_change = Signal(object)
    #: un clic sur le trait d'une opération: (son id, Ctrl/Maj enfoncée)
    operation_cliquee = Signal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.vue = VueScene(self)
        #: les opérations choisies dans la liste (leurs id): en avant
        self._ops_choisies = frozenset()
        self.vue.clic_avant_face = self._clic_sur_op

        retour = QPushButton("← 2D")
        retour.setToolTip("Revenir au canvas 2D")
        retour.clicked.connect(self.retour_2d.emit)
        self.retour_btn = retour
        self.cb_piece = QCheckBox("Pièce")
        self.cb_aretes = QCheckBox("Arêtes")
        self.cb_ops = QCheckBox("Opérations")
        self.cb_parcours = QCheckBox("Parcours")
        self.cb_matiere = QCheckBox("Matière")
        self.cb_dessin = QCheckBox("Dessin")
        self.cb_transp = QCheckBox("Transparente")
        self.cb_rouges = QCheckBox("Inaccessibles")
        for cb, attr, defaut, bulle in (
                (self.cb_piece, 'montrer_piece', True,
                 "La pièce STEP, ombrée"),
                (self.cb_aretes, 'montrer_aretes', True,
                 "Les arêtes de la pièce"),
                (self.cb_ops, 'montrer_operations', True,
                 "Les opérations, à leur profondeur"),
                (self.cb_parcours, 'montrer_parcours', True,
                 "Le parcours simulé du programme: les cycles Datron "
                 "déroulés (perçages, hélices, poches, surfaçages…)"),
                (self.cb_matiere, 'montrer_matiere', False,
                 "Le brut creusé par le parcours, jusqu'à l'avance: la "
                 "pièce telle qu'elle sort de la machine (forme réelle "
                 "des outils: plate, conique, foret, boule)"),
                (self.cb_dessin, 'montrer_dessin', True,
                 "Le dessin du canvas (calques STEP à leur Pz)"),
                (self.cb_transp, 'transparente', False,
                 "Voir à travers la pièce: les opérations dans la "
                 "matière"),
                (self.cb_rouges, 'montrer_rouges', True,
                 "En rouge, les faces qu'aucune orientation 3 axes "
                 "n'atteint (contre-dépouilles: fraise spéciale ou 5 "
                 "axes)")):
            cb.setChecked(defaut)
            cb.setToolTip(bulle)
            cb.toggled.connect(lambda on, a=attr: self._basculer(a, on))
        self.axe = QComboBox()
        for texte, cle in (("Haut auto", 'auto'), ("Haut Z", 'Z'),
                           ("Haut Y", 'Y'), ("Haut X", 'X')):
            self.axe.addItem(texte, cle)
        self.axe.setToolTip(
            "L'axe du haut de la pièce STEP: « auto » redresse une pièce "
            "exportée couchée (ses grandes faces à plat)")
        self.axe.currentIndexChanged.connect(
            lambda _i: self.axe_change.emit(self.axe.currentData()))
        self.exag = SpinCote(decimales=1)
        self.exag.setRange(1.0, 50.0)
        self.exag.setValue(1.0)
        self.exag.setMaximumWidth(48)
        self.exag.setToolTip("Exagération du relief (Z)")
        self.exag.valueChanged.connect(self._sur_exag)
        boutons = []
        for texte, action, bulle in (
                ("Iso", self.vue.vue_iso, "Vue isométrique"),
                ("Dessus", self.vue.vue_dessus, "Vue de dessus"),
                ("Face", self.vue.vue_face, "Vue de face"),
                ("↻", self.actualiser_demande.emit,
                 "Relire le dessin et les opérations (calculer: le "
                 "parcours simulé, la matière)")):
            b = QPushButton(texte)
            b.setToolTip(bulle)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.clicked.connect(action)
            boutons.append(b)
        #: « ↻ »: devient « Calculer » quand la vue est en retard sur le
        #: programme (réglage Calculs 3D: sur demande)
        self.recalculer = boutons[-1]
        self.vue_iso_btn, self.vue_dessus_btn, self.vue_face_btn = boutons[:3]
        self._perime = False
        self.info = QLabel("")
        self.info.setStyleSheet("color: #a6adc8; font-size: 10px;")
        self.info.setWordWrap(True)

        # la pièce STEP: l'importer, choisir ses faces, les usiner
        self.importer = QPushButton("Importer STEP…")
        self.importer.setToolTip(
            "Importer une pièce STEP: elle arrive au canvas (son dessin) "
            "et ici, en volume")
        self.importer.clicked.connect(self.importer_demande.emit)
        self.usiner = QPushButton("Usiner la sélection ▾")
        self.usiner.setToolTip(
            "Les usinages 2D des faces choisies (clic sur une face, "
            "Ctrl+clic pour en ajouter): perçages, poches, évidements, "
            "détourage")
        self.usiner.clicked.connect(self._montrer_menu_usinage)
        self.usinage3d = QPushButton("Usinage 3D…")
        self.usinage3d.setToolTip(
            "Toute la pièce: le moteur propose une gamme de fraises "
            "(ébauche, reprise, finition), la calcule et la contrôle")
        self.usinage3d.clicked.connect(self.usinage3d_demande.emit)
        self.deselectionner = QPushButton("✕")
        self.deselectionner.setFixedWidth(26)
        self.deselectionner.setToolTip("Vider la sélection de faces")
        self.deselectionner.clicked.connect(
            lambda: self.vue.choisir(-1, False))
        self.selection_info = QLabel(
            "Clic sur une face de la pièce pour la choisir")
        self.selection_info.setStyleSheet(
            "color: #89b4fa; font-size: 10px;")
        self.selection_info.setWordWrap(True)
        self.vue.selection_changee.connect(self._sur_selection)
        #: la bibliothèque d'outils (posée par le panneau du canvas)
        self.bibliotheque = None
        #: le profil réel de chaque outil du parcours (référence →
        #: points (r, z) ou None), refait à chaque simulation
        self._profils_outils = {}
        self._modele = None
        self._annexes = []              # les noms des pièces en annexe
        self._piece_place = None        # (dx, dy, haut, bas)
        self._sur_selection()

        # l'avance: le parcours jusqu'où l'outil est arrivé
        self._sim = None
        self._runs = []
        self._ops_des_runs = []
        self._runs_vus = []
        self._scene_ops = None
        from src.gui.icons import get_button_icon
        self.lecture = QPushButton("")
        self.lecture.setIcon(get_button_icon("play", 16))
        self.lecture.setCheckable(True)
        self.lecture.setFixedWidth(30)
        self.lecture.setToolTip("Jouer le parcours simulé")
        self.lecture.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.lecture.toggled.connect(self._sur_lecture)
        self.avance = QSlider(Qt.Orientation.Horizontal)
        self.avance.setRange(0, self.AVANCE_MAX)
        self.avance.setValue(self.AVANCE_MAX)
        self.avance.setToolTip(
            "Avance de la simulation: le parcours jusqu'ici, l'outil "
            "au bout")
        self.avance.valueChanged.connect(self._sur_avance)
        self.position = QLabel("")
        self.position.setStyleSheet(
            "color: #a6adc8; font-family: 'Cascadia Code', monospace; "
            "font-size: 10px;")
        self._minuterie = QTimer(self)
        self._minuterie.setInterval(40)
        self._minuterie.timeout.connect(self._pas_de_lecture)
        # la vitesse de lecture: ×1 = la machine (avances de tools.json)
        from PySide6.QtCore import QElapsedTimer
        from src.gui.theme import reglages_qt
        self._horloge = QElapsedTimer()
        self._temps = None            # temps machine cumulé par sommet
        self._temps_reels = None      # ce que la machine a mesuré
        self._t_lecture = 0.0
        self._sommet_force = None     # le sommet que la lecture montre
        self.vitesse = QComboBox()
        self.vitesse.setEditable(True)
        for v in self.VITESSES:
            self.vitesse.addItem(f"×{v:g}".replace(".", ","), float(v))
        self.vitesse.setToolTip(
            "Vitesse de la lecture: ×1 = la vitesse de la machine (les "
            "avances de tools.json, les rapides de la machine), de ×0,1 "
            "à ×100")
        self.vitesse.setMaximumWidth(78)
        try:
            v0 = float(reglages_qt().value("canvas3d/vitesse", 1.0) or 1.0)
        except (TypeError, ValueError):
            v0 = 1.0
        self.regler_vitesse(v0)
        self.vitesse.currentIndexChanged.connect(self._sur_vitesse)
        self.vitesse.lineEdit().editingFinished.connect(self._sur_vitesse)
        from src.gui.widgets import SpinEntier
        self.fps = SpinEntier()
        self.fps.setRange(self.FPS_MIN, self.FPS_MAX)
        self.fps.setMaximumWidth(52)
        self.fps.setToolTip(
            "Images par seconde de la lecture: moins pour un programme "
            "lourd (la lecture reste fluide), plus pour un mouvement doux")
        try:
            f0 = int(reglages_qt().value("canvas3d/fps", 25) or 25)
        except (TypeError, ValueError):
            f0 = 25
        self.fps.setValue(max(self.FPS_MIN, min(self.FPS_MAX, f0)))
        self.fps.valueChanged.connect(self._sur_fps)
        self._sur_fps(self.fps.value())
        # la matière: le brut, et la simulation dont il est creusé
        self._brut = None
        self._brut_sim = None
        self._texte_base = ""
        self._texte_matiere = ""
        self.cb_matiere.toggled.connect(self._sur_matiere)

        # la machine: table, étau ou mandrin, broche; les collisions
        self.cb_machine = QCheckBox("Machine")
        self.cb_machine.setToolTip(
            "La pièce dans la machine: la table et ses rainures, l'étau ou "
            "le mandrin choisi, l'enveloppe des courses (centrée sur le "
            "brut), la broche au-dessus de l'outil pendant la lecture")
        self.cb_machine.toggled.connect(self._sur_machine)
        self.serrage = QComboBox()
        self.serrage.setToolTip(
            "Ce qui tient le brut: un étau autocentré ou un mandrin "
            "(« Étaux et mandrins »), ou directement la table")
        self.serrage.currentIndexChanged.connect(self._sur_serrage)
        self.collisions_btn = QPushButton("Collisions")
        self.collisions_btn.setToolTip(
            "Vérifier que la broche et le porte-outil (écrou, nez, corps) "
            "ne touchent ni l'étau, ni la table, ni la pièce, ni la matière "
            "du brut, sur tout le parcours simulé")
        self.collisions_btn.clicked.connect(lambda: self.verifier_collisions())
        self.machine_btn = QPushButton("Machine…")
        self.machine_btn.setToolTip("Les cotes de la machine (courses, "
                                    "table, broche, pince) et ses STEP")
        self.machine_btn.clicked.connect(self._editer_machine)
        # l'affichage de chaque opération: transparence, une ligne sur N
        self.panneau_ops = PanneauAffichageOps(self)
        # les mouvements d'une barre tirée: une relecture à la fois
        self._minuterie_affichage_ops = QTimer(self)
        self._minuterie_affichage_ops.setSingleShot(True)
        self._minuterie_affichage_ops.setInterval(15)
        self._minuterie_affichage_ops.timeout.connect(self.maj_affichage_ops)
        self.panneau_ops.apercu.connect(self._minuterie_affichage_ops.start)
        self.panneau_ops.change.connect(self._sur_affichage_ops_pose)
        self.panneau_ops.oeil_change.connect(self.oeil_op_change.emit)
        self.avance.setMinimumWidth(160)

        def _groupe(*elements):
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(3)
            for e in elements:
                if e is None:
                    trait = QFrame()
                    trait.setFrameShape(QFrame.Shape.VLine)
                    trait.setFixedWidth(1)
                    h.addWidget(trait)
                elif isinstance(e, str):
                    h.addWidget(QLabel(e))
                else:
                    h.addWidget(e)
            return w

        # TOUS les outils sur une seule barre, que l'utilisateur place
        # en haut, en bas, à gauche ou à droite (clic droit): la vue
        # sortie dans sa fenêtre garde sa hauteur
        from src.gui.barre_outils import BarreOutils, bloc, installer
        barre = BarreOutils('canvas3d/barre_outils', self)
        # le panneau 3D à onglets: les entités (œil, transparence), les
        # opérations, la pièce, la machine — les réglages rangés hors de
        # la barre (octobre 2026, RomDuch)
        self.panneau_3d = self._neuf_panneau_3d()
        self.panneau_3d.setVisible(False)
        self.panneau_btn = QPushButton("Panneau 3D")
        self.panneau_btn.setCheckable(True)
        self.panneau_btn.setToolTip(
            "Le panneau 3D: chaque entité (œil, transparence), "
            "l'affichage des opérations, la pièce (axe, relief, import, "
            "usinage), la machine (serrage, collisions)")
        self.panneau_btn.toggled.connect(self.panneau_3d.setVisible)
        #: (ancien nom) le bouton qui montrait l'affichage des opés
        self.ops_btn = self.panneau_btn
        barre.ajouter(_groupe(retour, None, self.cb_piece, self.cb_aretes,
                              self.cb_ops, self.cb_parcours, self.cb_matiere,
                              self.cb_dessin, self.cb_transp, self.cb_rouges))
        barre.ajouter(_groupe(None, *boutons))
        self.fps_unite = QLabel("i/s")
        barre.ajouter(_groupe(None, self.lecture, self.vitesse,
                              bloc(self.fps, self.fps_unite),
                              self.avance, self.position))
        barre.ajouter(_groupe(None, self.panneau_btn))
        barre.terminer()
        barre.icones([
            (retour, 'b_retour_2d', "Revenir au canvas 2D"),
            (self.cb_piece, 'b_piece', "Pièce"),
            (self.cb_aretes, 'b_aretes', "Arêtes"),
            (self.cb_ops, 'b_ops3d', "Opérations"),
            (self.cb_parcours, 'b_parcours', "Parcours simulé"),
            (self.cb_matiere, 'b_matiere', "Matière"),
            (self.cb_dessin, 'b_dessin3d', "Dessin du canvas"),
            (self.cb_transp, 'b_transparente', "Pièce transparente"),
            (self.cb_rouges, 'b_inaccessibles', "Faces inaccessibles"),
            (self.vue_iso_btn, 'b_vue_iso', "Vue isométrique"),
            (self.vue_dessus_btn, 'b_vue_dessus', "Vue de dessus"),
            (self.vue_face_btn, 'b_vue_face', "Vue de face"),
            (self.recalculer, 'b_actualiser', "Relire et calculer"),
            (self.lecture, 'play', "Jouer le parcours"),
            (self.panneau_btn, 'b_ops_affichage',
             "Panneau 3D: entités, opérations, pièce, machine"),
        ])
        barre.relier_etat(self.selection_info)
        self.barre_outils = barre
        zone = QWidget()
        v = QVBoxLayout(zone)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        self._disposition = v
        centre = QHBoxLayout()
        centre.setContentsMargins(0, 0, 0, 0)
        centre.addWidget(self.vue, 1)
        centre.addWidget(self.panneau_3d)
        v.addLayout(centre, 1)
        # une seule ligne d'état sous la vue (le texte entier en bulle)
        for lab in (self.selection_info, self.info):
            lab.setWordWrap(False)
            lab.setSizePolicy(QSizePolicy.Policy.Ignored,
                              QSizePolicy.Policy.Preferred)
        etat = QHBoxLayout()
        etat.setContentsMargins(2, 0, 2, 0)
        etat.addWidget(self.selection_info, 1)
        etat.addWidget(self.info, 2)
        v.addLayout(etat)
        hote = QVBoxLayout(self)
        hote.setContentsMargins(0, 0, 0, 0)
        hote.setSpacing(2)
        installer(self, hote, barre, zone)
        self._machine = None
        self._cotes_outils = {}
        self._remplir_serrages()
        self._montrer_avance(False)

    # ── le panneau 3D ──

    #: l'onglet de chaque page du panneau
    ONGLETS_PANNEAU = ("Entités", "Opés", "Pièce", "Machine")

    def _neuf_panneau_3d(self):
        from PySide6.QtWidgets import QFormLayout, QTabWidget
        onglets = QTabWidget(self)
        # la vue garde la priorité: un panneau étroit, ses onglets courts
        onglets.setMinimumWidth(230)
        onglets.setMaximumWidth(300)
        self.panneau_entites = PanneauEntites3D(self, onglets)
        onglets.addTab(self.panneau_entites, "Entités")
        onglets.addTab(self.panneau_ops, "Opés")
        # la pièce: son axe, le relief, l'importer, l'usiner
        piece = QWidget()
        f = QFormLayout(piece)
        f.setContentsMargins(6, 6, 6, 6)
        f.addRow("Haut de la pièce:", self.axe)
        f.addRow("Relief (Z ×):", self.exag)
        for b in (self.importer, self.usinage3d, self.usiner):
            f.addRow(b)
        ligne = QHBoxLayout()
        ligne.addWidget(QLabel("Faces choisies:"))
        ligne.addStretch(1)
        self.deselectionner.setText("✕ Vider")
        self.deselectionner.setFixedWidth(70)
        ligne.addWidget(self.deselectionner)
        f.addRow(ligne)
        onglets.addTab(piece, "Pièce")
        # la machine: le serrage, les collisions, ses cotes
        machine = QWidget()
        m = QFormLayout(machine)
        m.setContentsMargins(6, 6, 6, 6)
        m.addRow(self.cb_machine)
        m.addRow("Serrage:", self.serrage)
        m.addRow(self.collisions_btn)
        m.addRow(self.machine_btn)
        onglets.addTab(machine, "Machine")
        return onglets

    def opacite(self, cle: str) -> float:
        """L'opacité retenue d'une entité (0,05–1), posée sur la vue."""
        try:
            from src.gui.theme import reglages_qt
            v = float(reglages_qt().value(f"canvas3d/opacite/{cle}",
                                          1.0) or 1.0)
        except (TypeError, ValueError):
            v = 1.0
        v = max(0.05, min(1.0, v))
        if cle == 'matiere':
            self.vue.opacite_matiere = v
        else:
            self.vue.opacites[cle] = v
        return v

    def regler_opacite(self, cle: str, valeur: float) -> None:
        """L'opacité d'une entité: la vue se redessine, le réglage
        est retenu."""
        v = max(0.05, min(1.0, float(valeur)))
        if cle == 'matiere':
            self.vue.opacite_matiere = v
        else:
            self.vue.opacites[cle] = v
        try:
            from src.gui.theme import reglages_qt
            reglages_qt().setValue(f"canvas3d/opacite/{cle}", v)
        except Exception:
            pass
        self.vue.update()

    def set_operations_affichage(self, ops) -> None:
        """Les opérations du programme, pour le panneau « Opés »."""
        self.panneau_ops.set_operations(ops)

    #: () -> {id d'opération: (opacité, une ligne sur N)} de celles qui ne
    #: sont pas aux réglages par défaut (posé par la fenêtre)
    fournisseur_affichage_ops = None

    def _sur_affichage_ops_pose(self) -> None:
        self._minuterie_affichage_ops.stop()
        self.maj_affichage_ops()
        self.affichage_ops_change.emit()

    def maj_affichage_ops(self) -> None:
        """La transparence ou « une ligne sur N » d'opérations a changé:
        leurs tracés et leur parcours se refont avec — ni simulation, ni
        recadrage, ni matière."""
        self._maj_runs_vus()
        calques, parcours = self._listes_des_ops()
        self.vue._calques = calques
        self.vue._image_lecture = None
        self.vue.set_parcours(parcours, self.vue.outil)

    def _listes_des_ops(self):
        """(calques de la scène, calques du parcours jusqu'à l'avance),
        au choix d'opérations d'aujourd'hui."""
        calques = self.vue._calques
        scene = self._scene_ops
        if scene is not None:
            from src.gui.dxf import canvas_volume
            dessin, operations, par_op = scene
            if par_op is not None:
                operations = (self._operations_marquees(par_op)
                              if self._ops_choisies
                              else canvas_volume.formes_affichees(par_op))
            calques = self._calques_de_scene(
                dessin, operations, self._traces_doublons(par_op))
        n, bout = getattr(self, '_dernier_sommet', (None, None))
        return calques, self._calques_jusqua(n, bout)

    def _listes_neutres(self):
        """Les listes des opérations comme si aucune n'était choisie."""
        choisies = self._ops_choisies
        self._ops_choisies = frozenset()
        try:
            return self._listes_des_ops()
        finally:
            self._ops_choisies = choisies

    def _montrer_le_choix(self) -> None:
        """Le choix d'opérations a changé, rien d'autre: les calques
        marqués se refont (ils disent le choix), la vue garde les mêmes
        sans choix — son image estompée sert à tous les choix, seules les
        choisies se retracent. Plus rien de choisi: les listes sans choix
        reviennent telles quelles."""
        vue = self.vue
        reglages = self._reglages_vus
        neutres = vue.listes_neutres()
        if self._minuterie_affichage_ops.isActive():
            neutres = None          # l'affichage va changer: refaites
        if not self._ops_choisies and neutres is not None:
            vue.montrer_neutres(*neutres)
            return
        self.maj_affichage_ops()
        if not self._ops_choisies:
            return
        if neutres is None or self._reglages_vus != reglages:
            neutres = self._listes_neutres()
        vue.poser_neutres(*neutres)

    def poser_barre_imports(self, barre) -> None:
        """Les onglets des imports du dessin, en haut de la vue (les
        mêmes qu'au-dessus du Canva 2D)."""
        self._disposition.insertWidget(0, barre)

    #: graduations du curseur d'avance
    AVANCE_MAX = 1000
    #: les vitesses de lecture proposées (×1 = la machine)
    VITESSES = (0.1, 0.25, 0.5, 1, 2, 5, 10, 25, 50, 100)
    VITESSE_MIN, VITESSE_MAX = 0.1, 100.0
    #: images par seconde de la lecture
    FPS_MIN, FPS_MAX = 5, 60
    #: durée d'une lecture complète (ms)
    DUREE_LECTURE = 10000

    def _montrer_avance(self, oui: bool) -> None:
        for w in (self.lecture, self.avance, self.position, self.vitesse,
                  self.fps, self.fps_unite):
            w.setVisible(oui)

    # ── la vitesse de lecture ──

    def vitesse_lecture(self) -> float:
        texte = self.vitesse.currentText().replace("×", "").replace(
            ",", ".").replace("x", "").strip()
        try:
            v = float(texte)
        except ValueError:
            v = float(self.vitesse.currentData() or 1.0)
        return max(self.VITESSE_MIN, min(self.VITESSE_MAX, v))

    def regler_vitesse(self, v: float) -> None:
        v = max(self.VITESSE_MIN, min(self.VITESSE_MAX, float(v)))
        i = self.vitesse.findData(v)
        self.vitesse.blockSignals(True)
        if i >= 0:
            self.vitesse.setCurrentIndex(i)
        else:
            self.vitesse.setEditText(f"×{v:g}".replace(".", ","))
        self.vitesse.blockSignals(False)

    def _sur_vitesse(self, *_a) -> None:
        v = self.vitesse_lecture()
        self.regler_vitesse(v)
        try:
            from src.gui.theme import reglages_qt
            reglages_qt().setValue("canvas3d/vitesse", v)
        except Exception:
            pass

    def _sur_fps(self, fps: int) -> None:
        self._minuterie.setInterval(max(1, int(round(1000.0 / max(1, fps)))))
        try:
            from src.gui.theme import reglages_qt
            reglages_qt().setValue("canvas3d/fps", int(fps))
        except Exception:
            pass

    def _avances_outil(self, art: str) -> dict:
        """Les avances de tools.json de l'outil d'un sommet (mm/min)."""
        lib = self.bibliotheque
        tool = None
        if lib is not None and art:
            tool = lib.get_tool_by_article(art) if hasattr(
                lib, 'get_tool_by_article') else None
            if tool is None:
                tool = next((t for t in lib.get_all_tools()
                             if t.name == art), None)
        if tool is None:
            return {}
        return {'finishing': tool.feed_finishing,
                'plunge': tool.feed_plunge,
                'approach': tool.feed_approach}

    def duree_machine(self) -> float:
        """Le temps machine de tout le parcours (s), 0 sans parcours."""
        if self._temps is None or not len(self._temps):
            return 0.0
        return float(self._temps[-1])

    def _basculer(self, attr, on):
        setattr(self.vue, attr, bool(on))
        self.vue.update()

    def _sur_exag(self, v):
        self.vue.exag = float(v)
        self.vue.update()

    #: la teinte des pièces annexes (vues, pas usinées)
    TEINTE_ANNEXE = np.array([0.10, 0.12, 0.20])

    def charger(self, modele=None, decalage=(0.0, 0.0), dessin=None,
                operations=None, texte_piece="", parcours=None,
                couleurs=None, annexes=None, formes_par_op=None) -> None:
        """La scène: la pièce (Modele3D) posée comme le dessin — XY
        décalés comme lui, son dessus en Z 0 —, le dessin
        [(pts, couleur)], les opérations [(pts, couleur, genre)] et le
        parcours simulé (résultat de sim_cycles.simuler, couleurs
        {référence d'outil: hex}). `formes_par_op`: les opérations avant
        transparence (`canvas_volume.formes_3d`), pour la changer sans
        tout relire."""
        self._quitter_scene()
        self._preparer_parcours(parcours, couleurs or {})
        self._scene_ops = (dessin, operations, formes_par_op)
        tri = couls = None
        aretes = []
        faces = None
        if modele is not self._modele:
            # une autre pièce: la sélection ne vaut plus, ses faces
            # inaccessibles se recalculent
            self.vue.selection = set()
            self.vue.faces_rouges = self._faces_inaccessibles(modele)
        self._modele = modele
        self._piece_place = None
        if modele is not None and (len(modele.triangles)
                                   or modele.aretes):
            b = modele.bornes()
            t = np.array([decalage[0], decalage[1], -b[5]])
            tri = modele.triangles + t
            couls = modele.couleurs
            aretes = [a + t for a in modele.aretes]
            faces = getattr(modele, 'face_de', None)
            self._piece_place = (float(decalage[0]), float(decalage[1]),
                                 float(b[5]), float(b[2]))
        # les autres pièces 3D, posées de même (dessus en Z 0), plus
        # sombres: on les voit, on ne choisit pas leurs faces
        self._annexes = []
        for annexe in annexes or []:
            m, dec = annexe[0], annexe[1]
            if m is None or not len(getattr(m, 'triangles', ())):
                continue
            ba = m.bornes()
            ta = np.array([dec[0], dec[1], -ba[5]])
            tri_a = m.triangles + ta
            col_a = np.clip(np.asarray(m.couleurs, dtype=float) * 0.7
                            + self.TEINTE_ANNEXE, 0.0, 1.0)
            n0 = len(tri) if tri is not None else 0
            faces_actives = (np.asarray(faces, dtype=float)
                             if faces is not None and n0
                             and len(faces) == n0
                             else np.full(n0, -1.0))
            tri = tri_a if tri is None or not n0 else \
                np.concatenate([tri, tri_a])
            couls = col_a if couls is None or not n0 else \
                np.concatenate([np.asarray(couls, dtype=float), col_a])
            faces = np.concatenate([faces_actives,
                                    np.full(len(tri_a), -1.0)])
            aretes += [a + ta for a in m.aretes]
            self._annexes.append(annexe[2] if len(annexe) > 2 else "")
        self._sur_selection()
        if self._ops_choisies and formes_par_op is not None:
            operations = self._operations_marquees(formes_par_op)
        calques = self._calques_de_scene(
            dessin, operations, self._traces_doublons(formes_par_op))
        # la matière d'abord: le cadrage la compte
        self._maj_matiere(cadrer=False, avec_vue=False)
        self.vue.set_scene(tri, couls, aretes, calques,
                           self._calques_jusqua(None), faces)
        # l'avance garde sa place d'une relecture à l'autre
        self._sur_avance(self.avance.value())
        morceaux = []
        if texte_piece:
            morceaux.append(texte_piece)
        if self._annexes:
            morceaux.append(f"+ {len(self._annexes)} pièce(s) en annexe")
        if self.vue.faces_rouges and modele is not None:
            morceaux.append(f"{len(self.vue.faces_rouges)} face(s) "
                            "inaccessible(s) en 3 axes (en rouge)")
        if self._sim is not None:
            from src.core import sim_cycles
            texte = sim_cycles.resume(self._sim)
            if texte:
                morceaux.append(texte)
        n_ops = sum(1 for m in (operations or []) if m[2] == 'coupe')
        if operations:
            morceaux.append(f"{n_ops} tracé(s) d'usinage")
        if dessin:
            morceaux.append(f"{len(dessin)} tracé(s) de dessin")
        self._texte_base = " · ".join(morceaux)
        self._maj_info()

    def _traces_doublons(self, par_op) -> set:
        """Les tracés (id des tableaux) des opérations importées dont le
        parcours simulé est là: `VueScene._sans_doublons`."""
        from src.core import affichage as af
        simulees = set(self._ops_des_runs)
        if self._sim is not None and self._sim.get('tronque') \
                and self._ops_des_runs:
            # la simulation s'est arrêtée dans celle-là: son tracé va plus
            # loin que son parcours
            simulees.discard(next((o for o in reversed(self._ops_des_runs)
                                   if o), None))
        traces = set()
        for op, morceaux in par_op or []:
            if op is not None and getattr(op, 'id', None) in simulees and \
                    getattr(op, 'operation_type', '') in af.TRACE_SIMULE:
                traces.update(id(m[0]) for m in morceaux)
        return traces

    def _operations_marquees(self, par_op) -> list:
        """Les formes [(opération, morceaux)] à la transparence et à la
        division d'aujourd'hui, chaque morceau marqué d'un 5e terme: son
        opération est-elle choisie dans la liste (`choisir_ops`)?"""
        from src.gui.dxf import canvas_volume
        sortie = []
        for op, morceaux in par_op or []:
            choisie = op is not None and getattr(op, 'id', None) \
                in self._ops_choisies
            for m in canvas_volume.formes_affichees([(op, morceaux)]):
                sortie.append((m[0], m[1], m[2],
                               float(m[3]) if len(m) > 3 else 1.0, choisie))
        return sortie

    @staticmethod
    def _marquer_choix(couleur: QColor, largeur: float, choix) -> float:
        """Le trait d'une opération choisie dans la liste (`choix` vrai)
        s'élargit; celui d'une autre (faux) s'estompe; sans choix (None),
        rien ne change. Rend la largeur."""
        if choix is True:
            return largeur + SURCROIT_CHOISIE
        if choix is False:
            couleur.setAlphaF(couleur.alphaF() * ESTOMPE_AUTRES)
        return largeur

    def _choix_de(self, op_id):
        """None sans opération choisie; sinon: celle-ci l'est-elle?"""
        if not self._ops_choisies:
            return None
        return op_id in self._ops_choisies

    def choisir_ops(self, ids) -> None:
        """Les opérations choisies dans la liste (leurs id): en avant,
        traits plus larges, les autres estompées. Vide: toutes pareilles.
        Ni simulation, ni recadrage: les traits se refont."""
        ids = frozenset(i for i in (ids or ()) if i)
        if ids == self._ops_choisies:
            return
        self._ops_choisies = ids
        if not self.isVisible():
            # caché: les traits se refont quand il se montre
            self._choix_en_retard = True
            return
        self._montrer_le_choix()

    #: le choix d'opérations a changé pendant que la vue était cachée
    _choix_en_retard = False
    #: les réglages d'affichage des opérations des derniers calques
    _reglages_vus = None

    def showEvent(self, event):
        super().showEvent(event)
        if self._choix_en_retard:
            self._choix_en_retard = False
            self._montrer_le_choix()

    def op_au_point(self, x: float, y: float,
                    tolerance: float = TOLERANCE_CLIC_OP):
        """L'id de l'opération dont un trait visible passe au plus près du
        pixel (x, y), à moins de `tolerance` pixels — le parcours simulé
        tel que l'avance le montre, et les tracés des opérations —, ou
        None."""
        vue = self.vue
        opac = getattr(vue, 'opacites', {}) or {}
        candidats = []          # (points (N,3), début de chaque segment, op)
        if vue.montrer_parcours and self._sim is not None and len(self._P) \
                and float(opac.get('parcours', 1.0)) > 0:
            n = self._dernier_sommet[0]
            n = len(self._P) if n is None else int(n)
            debuts, ops = [], []
            for run in self._runs_vus:
                debut, fin, op, a = run[0], run[1], run[6], run[4]
                if op is None or a <= 0 or debut >= n:
                    continue
                fin = min(fin, n - 1)
                if fin >= debut:
                    debuts.append(np.arange(debut, fin + 1))
                    ops.append((op, fin + 1 - debut))
            if debuts:
                candidats.append((self._P, np.concatenate(debuts), ops))
        scene = self._scene_ops
        if vue.montrer_operations and scene is not None and scene[2] \
                and float(opac.get('operations', 1.0)) > 0:
            morceaux, ops, total = [], [], 0
            for op, formes in scene[2]:
                oid = getattr(op, 'id', None) if op is not None else None
                if not oid or not self._op_visible(op):
                    continue
                k = 0
                for m in formes:
                    pts = np.asarray(m[0], dtype=float)
                    if len(pts) >= 2:
                        morceaux.append((pts, total))
                        total += len(pts)
                        k += len(pts) - 1
                if k:
                    ops.append((oid, k))
            if morceaux:
                P = np.vstack([m[0] for m in morceaux])
                segs = np.concatenate([np.arange(d + 1, d + len(m))
                                       for m, d in morceaux])
                candidats.append((P, segs, ops))
        meilleur, choisi = float(tolerance), None
        for P, segs, ops in candidats:
            px, py, _d = vue._vue(P)
            ax, ay = px[segs - 1], py[segs - 1]
            bx, by = px[segs], py[segs]
            dx, dy = bx - ax, by - ay
            l2 = dx * dx + dy * dy
            t = np.where(l2 > 1e-12,
                         ((x - ax) * dx + (y - ay) * dy)
                         / np.where(l2 > 1e-12, l2, 1.0), 0.0)
            t = np.clip(t, 0.0, 1.0)
            ex, ey = ax + t * dx - x, ay + t * dy - y
            dist = np.sqrt(ex * ex + ey * ey)
            if not len(dist):
                continue
            i = int(np.argmin(dist))
            if float(dist[i]) < meilleur:
                meilleur = float(dist[i])
                bornes = np.cumsum([c for _o, c in ops])
                choisi = ops[int(np.searchsorted(bornes, i, side='right'))][0]
        return choisi

    @staticmethod
    def _op_visible(op) -> bool:
        """Le tracé de l'opération se voit-il (pas transparente du tout)?"""
        try:
            from src.core import affichage as af
            return af.opacite(op) > 0
        except Exception:
            return True

    def _clic_sur_op(self, x: float, y: float, ajouter: bool) -> bool:
        """(la vue) un clic: sur le trait d'une opération, elle est choisie
        (`operation_cliquee`) et la face sous lui ne l'est pas."""
        oid = self.op_au_point(x, y)
        if oid is None:
            return False
        self.operation_cliquee.emit(str(oid), bool(ajouter))
        return True

    @staticmethod
    def _calques_de_scene(dessin, operations, doublons=()) -> list:
        """Les calques du dessin et des opérations: un par couleur, genre
        et opacité. `doublons`: les tracés que le parcours recouvre (id des
        tableaux), à part. Un 5e terme d'un morceau d'opération: son
        opération est-elle choisie dans la liste (`_operations_marquees`)?"""
        calques = []
        par_couleur = {}
        for pts, couleur in (dessin or []):
            par_couleur.setdefault(('dessin', couleur, 'trait'), []).append(pts)
        for morceau in (operations or []):
            pts, couleur, genre = morceau[:3]
            # 4e terme: l'opacité de l'opération (transparence réglée)
            opac = float(morceau[3]) if len(morceau) > 3 else 1.0
            choix = morceau[4] if len(morceau) > 4 else None
            par_couleur.setdefault(('operation', couleur, genre, opac,
                                    id(pts) in doublons, choix),
                                   []).append(pts)
        for cle, pts in par_couleur.items():
            famille, couleur, genre = cle[:3]
            opac = cle[3] if len(cle) > 3 else 1.0
            choix = cle[5] if len(cle) > 5 else None
            c = QColor(couleur)
            largeur, style = 1.0, Qt.PenStyle.SolidLine
            if famille == 'operation':
                if genre == 'coupe':
                    largeur = 1.8
                elif genre == 'surface':
                    c.setAlpha(110)
                    style = Qt.PenStyle.DashLine
                elif genre == 'axe':
                    c.setAlpha(150)
                elif genre == 'air':
                    c.setAlpha(80)
            else:
                c.setAlpha(170)
            if opac < 1.0:
                c.setAlphaF(c.alphaF() * opac)
            largeur = Canvas3D._marquer_choix(c, largeur, choix)
            calques.append({'pts': pts, 'couleur': c, 'largeur': largeur,
                            'style': style, 'genre': famille,
                            'doublon': len(cle) > 4 and cle[4],
                            'choix': choix})
        return calques

    def oublier_programme(self) -> None:
        """Plus rien du programme d'avant: ni parcours, ni opérations,
        ni dessin, ni pièce (voir `sur_changement_de_programme`)."""
        if self.lecture.isChecked():
            self.lecture.setChecked(False)
        # le choix d'opérations était celui du programme d'avant: gardé,
        # il estompait tout le nouveau (aucune de ses opérations n'en est)
        self._ops_choisies = frozenset()
        self._choix_en_retard = False
        self.charger()

    @staticmethod
    def _faces_inaccessibles(modele) -> set:
        """Les faces qu'aucune orientation 3 axes n'atteint (le
        planificateur des phases), si la pièce n'en a pas trop."""
        faces = getattr(modele, 'faces', None) or []
        if not faces or len(faces) > FACES_MAX_ACCESSIBILITE:
            return set()
        try:
            from src.core import usinage3d
            return set(usinage3d.planifier_phases(modele)['non_usinables'])
        except Exception:
            return set()

    def marquer_perime(self, perime: bool) -> None:
        """La vue est-elle en retard sur le programme (calculs sur
        demande)? Le bouton le dit, et l'info aussi."""
        self._perime = bool(perime)
        if self._perime:
            self.recalculer.setText("↻ Calculer")
            self.recalculer.setStyleSheet(
                "QPushButton { color: #1e1e2e; background: #f9e2af; "
                "font-weight: bold; }")
        else:
            self.recalculer.setText("↻")
            self.recalculer.setStyleSheet("")
        self._maj_info()

    def montrer_scene(self, sc: dict) -> None:
        """Une phase de bridage (src/core/scene_phases): la pièce comme
        elle est bridée, ce qui la tient, la matière qui reste; « ↻ »
        revient à la pièce et au programme."""
        self._preparer_parcours(None, {})
        self._scene_ops = None      # (une transparence ne la refait pas)
        self.vue.set_scene(sc['triangles'], sc['couleurs'], sc['aretes'],
                           sc['calques'])
        # la matière du programme d'avant n'est pas celle de la phase
        self._brut = None
        self._brut_sim = None
        self._maille_faite = None
        self._matiere_de_scene = sc.get('matiere') or None
        if self._matiere_de_scene and not self.cb_matiere.isChecked():
            # la case dit ce qui se voit (l'œil du panneau la suit);
            # `charger` la rend au retour du programme
            self._case_matiere_pour_scene = True
            self.cb_matiere.setChecked(True)        # → _maj_matiere
        else:
            self._maj_matiere()
        self._texte_base = sc.get('texte', '') + " · « ↻ » pour revenir"
        self._maj_info()

    #: la matière d'une phase de bridage (triangles, couleurs) tant que
    #: la scène est la sienne, et la case « Matière » cochée pour elle
    _matiere_de_scene = None
    _case_matiere_pour_scene = False

    def _quitter_scene(self) -> None:
        """Le programme revient: la matière de la phase s'en va, la case
        « Matière » cochée pour elle se décoche."""
        self._matiere_de_scene = None
        if self._case_matiere_pour_scene:
            self._case_matiere_pour_scene = False
            if self.cb_matiere.isChecked():
                self.cb_matiere.setChecked(False)

    # ──── Le parcours simulé ────

    def _preparer_parcours(self, res, couleurs) -> None:
        """Découpe le parcours en tronçons d'un même genre et d'un même
        outil: (début, fin, genre, couleur) — le segment i va du sommet
        i-1 au sommet i."""
        from src.core import sim3d
        if res and res is self._sim and res.get('x') \
                and couleurs == self._couleurs_runs:
            # la même simulation (une relecture): ses tronçons sont bons
            self._dernier_sommet = (None, None)
            self._sommet_force = None
            self._profils_outils = {}
            self._cotes_outils = {}
            self.vue.collisions = []
            self._maj_runs_vus()
            self._calculer_temps()
            self._temps_reels = self._lire_temps_reels()
            self._montrer_avance(True)
            return
        self._sim = res if res and res.get('x') else None
        self._couleurs_runs = couleurs
        self._runs = []
        self._ops_des_runs = []
        self._dernier_sommet = (None, None)
        self._P = np.zeros((0, 3))
        self._temps = None
        self._temps_reels = None
        self._sommet_force = None
        if self._sim is None:
            self._maj_runs_vus()
            self._montrer_avance(False)
            return
        self._P = np.column_stack([res['x'], res['y'], res['z']])
        k = np.asarray(res['k'])
        n = len(k)
        o = list(res.get('outil') or [''] * n)
        if len(o) < n:
            o += [''] * (n - len(o))
        # les tronçons: là où le genre ou l'outil change (le segment i va
        # du sommet i-1 au sommet i) — sans boucle sur 400 000 sommets
        if n >= 2:
            codes = sim3d.codes_outils(o)
            change = np.flatnonzero((k[2:] != k[1:-1])
                                    | (codes[2:] != codes[1:-1])) + 2
            # ... ou l'opération: chacune a sa transparence
            plages = res.get('plages_ops') or []
            starts = np.array([p[0] for p in plages], dtype=np.int64)
            ids = [p[1] for p in plages]
            if len(starts):
                change = np.union1d(change, starts[(starts >= 2)
                                                   & (starts < n)])
            debuts = np.concatenate(([1], change)).astype(np.int64)
            fins = np.concatenate((change - 1, [n - 1])).astype(np.int64)
            rangs = (np.searchsorted(starts, debuts, side='right') - 1
                     ).tolist()
            for r, i, j in zip(rangs, debuts.tolist(), fins.tolist()):
                if k[i] != sim3d.DEPART:
                    self._runs.append((i, j, int(k[i]),
                                       couleurs.get(o[i], "#89b4fa")))
                    self._ops_des_runs.append(ids[r] if r >= 0 else None)
        self._rayons = {}
        self._profils_outils = {}
        self._cotes_outils = {}
        self.vue.collisions = []
        for art, d in (res.get('outils') or {}).items():
            try:
                self._rayons[art] = float(d) / 2.0
            except (TypeError, ValueError):
                pass
        self._outil_par_sommet = o
        self._maj_runs_vus()
        self._calculer_temps()
        self._temps_reels = self._lire_temps_reels()
        self._montrer_avance(True)

    def _maj_runs_vus(self) -> None:
        """Les tronçons tels qu'ils se montrent, aux réglages de leur
        opération: (début, fin, genre, couleur, opacité, pas, id de
        l'opération). « Une ligne
        sur N »: un tronçon sur N de chaque genre quand il y en a assez
        (pas seulement les rapides, ou seulement les coupes), sinon un
        sommet sur N."""
        f = self.fournisseur_affichage_ops
        try:
            reglages = (f() or {}) if callable(f) else {}
        except Exception:
            reglages = {}
        self._reglages_vus = reglages
        if not reglages:
            self._runs_vus = [r + (1.0, 1, op) for r, op in
                              zip(self._runs, self._ops_des_runs)]
            return
        combien, rang = {}, {}
        for (_d, _f, genre, _c), op in zip(self._runs, self._ops_des_runs):
            if op in reglages:
                combien[op, genre] = combien.get((op, genre), 0) + 1
        vus = []
        for (d, fin, genre, c), op in zip(self._runs, self._ops_des_runs):
            opac, n = reglages.get(op, (1.0, 1))
            pas = 1
            if n > 1:
                if combien[op, genre] >= 2 * n:
                    r = rang.get((op, genre), 0)
                    rang[op, genre] = r + 1
                    if r % n:
                        continue
                else:
                    pas = n
            vus.append((d, fin, genre, c, opac, pas, op))
        self._runs_vus = vus

    @staticmethod
    def _un_sur(pts, pas: int):
        """Un sommet sur `pas`, le dernier gardé."""
        if pas <= 1 or len(pts) <= 2:
            return pts
        reduits = pts[::pas]
        if (len(pts) - 1) % pas:
            reduits = np.vstack([reduits, pts[-1:]])
        return reduits

    def _calculer_temps(self) -> None:
        """Le temps machine à chaque sommet, aux rapides et au changement
        d'outil de la machine de l'atelier."""
        from src.core import sim3d
        if self._sim is None:
            return
        try:
            rapide = float(self.machine().get('vitesse_rapide')
                           or sim3d.RAPIDE_MM_MIN)
        except Exception:
            rapide = sim3d.RAPIDE_MM_MIN
        try:
            changement = float(self.machine().get('changement_outil_s',
                                                  sim3d.CHANGEMENT_OUTIL_S))
        except Exception:
            changement = sim3d.CHANGEMENT_OUTIL_S
        # les mêmes réglages sur le même parcours: les mêmes temps
        reglages = (self._sim, rapide, changement, sorted(
            (art, sorted(self._avances_outil(art).items()))
            for art in set(self._outil_par_sommet)))
        fait = self._temps_faits
        if self._temps is not None and fait is not None \
                and fait[0] is reglages[0] and fait[1:] == reglages[1:]:
            return
        self._temps_faits = reglages
        self._temps = sim3d.temps_parcours(self._sim, self._avances_outil,
                                           rapide, changement)

    def _calques_jusqua(self, n, bout=None):
        """Les calques du parcours jusqu'au sommet n (None: tout); `bout`
        (x, y, z): l'outil en chemin vers le sommet n — le segment en
        cours s'arrête à lui."""
        from src.core import sim3d
        if self._sim is None:
            return []
        if n is None:
            n = len(self._P)
        par_cle = {}
        #: le tronçon en cours (le dernier de son calque): la lecture
        #: incrémentale le retrace à chaque image, pas les autres
        partiel = None
        for debut, fin, genre, couleur, opac, pas, op in self._runs_vus:
            if debut > n or (debut == n and bout is None):
                break
            cle = (genre, couleur, opac, self._choix_de(op))
            if bout is not None and debut <= n <= fin and n < len(self._P):
                pts = np.vstack([self._P[debut - 1:n],
                                 np.asarray(bout, dtype=float)[None, :]])
                if len(pts) >= 2:
                    par_cle.setdefault(cle, []).append(self._un_sur(pts, pas))
                    partiel = cle
                break
            if fin > n - 1:
                fin = n - 1
                partiel = cle
            pts = self._P[debut - 1:fin + 1]
            if len(pts) >= 2:
                par_cle.setdefault(cle, []).append(self._un_sur(pts, pas))
            elif partiel == cle:
                partiel = None
        calques = []
        for cle, pts in par_cle.items():
            genre, couleur, opac, choix = cle
            c = QColor(couleur)
            largeur, style = 1.6, Qt.PenStyle.SolidLine
            if genre == sim3d.RAPIDE:
                c.setAlpha(90)
                largeur, style = 1.0, Qt.PenStyle.DashLine
            elif genre == sim3d.AIR:
                c.setAlpha(120)
                largeur = 1.0
            if opac < 1.0:
                c.setAlphaF(c.alphaF() * opac)
            largeur = self._marquer_choix(c, largeur, choix)
            calques.append({'pts': pts, 'couleur': c, 'largeur': largeur,
                            'style': style, 'genre': 'parcours',
                            'partiel': partiel == cle, 'cle': cle,
                            'choix': choix})
        return calques

    def sommet_de_l_avance(self, valeur=None) -> int:
        """Le nombre de sommets montrés pour une valeur du curseur."""
        if self._sim is None:
            return 0
        if valeur is None:
            valeur = self.avance.value()
        return max(1, int(round(len(self._P) * valeur / self.AVANCE_MAX)))

    def _sur_avance(self, valeur) -> None:
        # le curseur bougé à la main: le temps de lecture le suit
        self._sommet_force = None
        if self._sim is not None and self._temps is not None \
                and len(self._temps):
            n = self.sommet_de_l_avance(valeur)
            self._t_lecture = float(self._temps[min(n, len(self._temps)) - 1])
        self._afficher_sommet(None if valeur >= self.AVANCE_MAX
                              else self.sommet_de_l_avance(valeur))

    def _afficher_sommet(self, n, bout=None) -> None:
        """Le parcours jusqu'au sommet n, l'outil au bout (None: tout le
        parcours, sans outil); `bout`: l'outil entre le sommet n et le
        suivant (la lecture à la vitesse de la machine)."""
        self._dernier_sommet = (n, bout)
        if self.cb_matiere.isChecked():
            self._maj_matiere()
        if self._sim is None:
            self.vue.set_parcours([], None)
            self.position.setText("")
            self.position.setToolTip("")
            return
        if n is None:
            # tout le parcours, sans outil: la vue d'ensemble
            self.vue.set_parcours(self._calques_jusqua(None), None)
            duree = self.duree_machine()
            from src.core import temps_reels
            from src.core.sim3d import duree_lisible
            mesure = self._temps_reels
            self.position.setText(
                (f"temps machine {duree_lisible(duree)}" if duree else "")
                + temps_reels.texte_court(mesure, " · "))
            self.position.setToolTip(temps_reels.texte_resume(mesure))
            return
        n = max(1, min(int(n), len(self._P)))
        if bout is not None:
            x, y, z = (float(v) for v in bout)
        else:
            x, y, z = (float(v) for v in self._P[n - 1])
        art = self._outil_par_sommet[n - 1]
        formes = (self._sim or {}).get('formes') or {}
        broche = None
        if self.vue.montrer_machine:
            from src.core import machine as mc
            broche = mc.fil_broche(self.machine(), x, y,
                                   z + self.depassement_outil(art))
        self.vue.set_parcours(self._calques_jusqua(n, bout),
                              {'pos': (x, y, z),
                               'rayon': self._rayons.get(art, 1.0),
                               'forme': formes.get(art) or {},
                               'profil': self.profil_outil(art),
                               'broche': broche})
        temps = ""
        if self._temps is not None and len(self._temps) >= n:
            from src.core.sim3d import duree_lisible
            temps = (f"  t {duree_lisible(float(self._temps[n - 1]))}"
                     f" / {duree_lisible(self.duree_machine())}")
        self.position.setText(f"X {x:8.3f}  Y {y:8.3f}  Z {z:7.3f}"
                              + (f"  [{art}]" if art else "") + temps)

    # ──── la machine et les collisions ────

    def machine(self) -> dict:
        if self._machine is None:
            from src.core import machine as mc
            self._machine = mc.charger()
        return self._machine

    def _remplir_serrages(self) -> None:
        from src.core import serrages as sg
        from src.gui.theme import reglages_qt
        voulu = self.serrage.currentText() or str(
            reglages_qt().value("canvas3d/serrage", "") or "")
        self.serrage.blockSignals(True)
        self.serrage.clear()
        self.serrage.addItem("(brut sur la table)", None)
        for nom, chemin in sg.lister():
            self.serrage.addItem(nom, sg.charger(chemin))
        i = self.serrage.findText(voulu)
        self.serrage.setCurrentIndex(i if i >= 0 else 0)
        self.serrage.blockSignals(False)

    def _sur_serrage(self, _i=None) -> None:
        from src.gui.theme import reglages_qt
        reglages_qt().setValue("canvas3d/serrage",
                               self.serrage.currentText())
        self.vue.collisions = []
        self.maj_machine()

    def _sur_machine(self, on: bool) -> None:
        self.vue.montrer_machine = bool(on)
        if on:
            self._remplir_serrages()
        self.maj_machine()
        self._sur_avance(self.avance.value())

    def _editer_machine(self) -> None:
        from src.gui.dialogs.machine_dialog import DialogueMachine
        dlg = DialogueMachine(self.window())
        if dlg.exec():
            self._machine = None
            self.maj_machine()
            if self._sim is not None:
                # les rapides ou le changement d'outil ont pu changer
                self._calculer_temps()
                self._sur_avance(self.avance.value())

    #: () -> (xmin, xmax, ymin, ymax, zmin, zmax) ou None: le BRUT des
    #: Paramètres (la plaque à usiner), posé par la fenêtre
    fournisseur_brut = None

    def boite_programme(self):
        """Le brut déclaré aux Paramètres, ou None."""
        f = self.fournisseur_brut
        if not callable(f):
            return None
        try:
            b = f()
        except Exception:
            return None
        return tuple(float(v) for v in b) if b else None

    #: () -> le .SimPl d'où vient le programme courant (importé ou
    #: exporté), "" sinon: ses temps mesurés par la machine (posé par la
    #: fenêtre)
    fournisseur_chemin_programme = None

    def _lire_temps_reels(self):
        """Ce que la machine a mesuré du programme (temps_reels.resume),
        ou None."""
        f = self.fournisseur_chemin_programme
        if not callable(f):
            return None
        try:
            chemin = f()
            if not chemin:
                return None
            from src.core import temps_reels
            return temps_reels.resume(chemin)
        except Exception:
            return None

    def _brut_neuf(self, sim):
        from src.core import enlevement
        return enlevement.Brut.autour(sim, boite=self.boite_programme())

    def brut_change(self) -> None:
        """Le brut des Paramètres a peut-être changé: la matière se
        refait s'il a VRAIMENT changé (et qu'elle se montre)."""
        if getattr(self, '_brut_boite', None) == self.boite_programme():
            return
        self._brut = None
        self._brut_sim = None
        if self.cb_matiere.isChecked() and self._sim is not None:
            self._maj_matiere()
            self.vue.update()

    def nouveau_brut_declare(self, brut) -> None:
        """Le brut que le programme déclare (WorkpieceGeometry) a changé,
        pas ses mouvements: la matière en tient compte s'il n'y a pas de
        brut aux Paramètres."""
        if self._sim is None or self._sim.get('brut') == brut:
            return
        self._sim['brut'] = brut
        if self.boite_programme() is None:
            self._brut = None
            self._brut_sim = None
            if self.cb_matiere.isChecked():
                self._maj_matiere()
                self.vue.update()

    def boite_brut(self):
        """(xmin, xmax, ymin, ymax, zmin, zmax) du brut du parcours (ou de
        la pièce STEP), ou None."""
        if self._sim is not None:
            b = self._brut_neuf(self._sim)
            return (b.x0, b.x0 + b.nx * b.pas, b.y0, b.y0 + b.ny * b.pas,
                    b.z_bas, b.z_haut)
        if self._modele is not None and self._piece_place is not None:
            dx, dy, haut, bas = self._piece_place
            bo = self._modele.bornes()
            return (bo[0] + dx, bo[3] + dx, bo[1] + dy, bo[4] + dy,
                    bas - haut, 0.0)
        return None

    def scene_machine(self) -> dict:
        """La machine autour du brut: {'triangles', 'couleurs', 'aretes',
        'serrage': (triangles, couleurs) ou None, 'table': (…),
        'hors_course', 'z_table'} — ou {} sans brut."""
        from src.core import machine as mc
        boite = self.boite_brut()
        if boite is None:
            return {}
        m = self.machine()
        mp = mc.mise_en_place(boite, self.serrage.currentData())
        T, C = mc.triangles_table(m, mp['centre'], mp['z_table'])
        morceaux, couleurs = [T], [C]
        if mp['serrage'] is not None:
            morceaux.append(mp['serrage'][0])
            couleurs.append(mp['serrage'][1])
        return {'triangles': np.concatenate(morceaux),
                'couleurs': np.concatenate(couleurs),
                'aretes': mc.enveloppe(m, mp['centre'], mp['z_table']),
                'serrage': mp['serrage'], 'table': (T, C),
                'hors_course': mp['hors_course'], 'z_table': mp['z_table']}

    def maj_machine(self) -> None:
        if not self.vue.montrer_machine:
            self.vue.set_machine()
            return
        sc = self.scene_machine()
        self.vue.set_machine(sc.get('triangles'), sc.get('couleurs'),
                             sc.get('aretes'))
        if sc.get('hors_course'):
            self.info.setText(f"⚠ {self.serrage.currentText()}: "
                              f"{sc['hors_course']}")

    def cotes_outil(self, art) -> dict:
        """Les cotes de l'outil `art` (dessin_outil), gardées le temps
        d'une simulation."""
        if art in self._cotes_outils:
            return self._cotes_outils[art]
        cotes = {}
        bib = self.bibliotheque
        outil = next((t for t in getattr(bib, 'tools', {}).values()
                      if art and art in (
                          str(getattr(t, 'article_nr', '') or ''),
                          str(getattr(t, 'name', '') or ''))), None)
        if outil is not None:
            try:
                from src.core import dessin_outil, sim_cycles
                cotes = dessin_outil.cotes_outil(outil,
                                                 sim_cycles._catalogue())
            except Exception:
                cotes = {}
        self._cotes_outils[art] = cotes
        return cotes

    def depassement_outil(self, art) -> float:
        """La longueur de l'outil sous l'écrou de pince."""
        from src.core import machine as mc
        cotes = self.cotes_outil(art)
        if not cotes:
            return 20.0
        return mc.depassement(self.machine(), cotes)

    def verifier_collisions(self):
        """« Collisions »: la broche et le porte-outil sur tout le
        parcours (barre d'état, Annuler). Rend le rapport, ou None."""
        from src.core import collisions as co
        from src.core import enlevement
        from src.gui.progression import travailler
        if self._sim is None:
            self.info.setText("Collisions: pas de parcours simulé")
            return None
        sc = self.scene_machine()
        obstacles = []
        if sc.get('serrage') is not None:
            obstacles.append((self.serrage.currentText(), sc['serrage'][0]))
        if sc.get('table') is not None:
            obstacles.append(("la table", sc['table'][0]))
        if self._modele is not None and self._piece_place is not None:
            dx, dy, haut, _bas = self._piece_place
            obstacles.append(("la pièce STEP",
                              np.asarray(self._modele.triangles, dtype=float)
                              + np.array([dx, dy, -haut])))
        sim = self._sim
        deps = {art: self.depassement_outil(art)
                for art in set(sim.get('outil') or [])}
        brut = self._brut_neuf(sim)
        formes = sim.get('formes') or {}
        machine = self.machine()
        rapport = travailler(
            self, "Collisions de la broche",
            lambda prog: co.verifier(sim, deps, machine, obstacles, brut,
                                     formes, progression=prog),
            "Broche, porte-outil, étau, table, matière…")
        if rapport is None:
            return None
        self.vue.collisions = [(e['x'], e['y'], e['z'])
                               for e in rapport['evenements']]
        self.info.setText(co.resume(rapport))
        if rapport['evenements']:
            # l'outil et la broche au premier contact, la machine montrée
            if not self.cb_machine.isChecked():
                self.cb_machine.setChecked(True)
            i = rapport['evenements'][0]['debut']
            self.avance.setValue(max(0, min(self.AVANCE_MAX, int(
                round(self.AVANCE_MAX * (i + 1) / max(1, len(self._P)))))))
        self.vue.update()
        return rapport

    def profil_outil(self, art):
        """Le profil réel (r, z) de l'outil `art` (référence ou nom),
        tiré de ses cotes (`dessin_outil`), ou None: l'outil se dessine
        alors à sa forme. Gardé le temps d'une simulation (hors des
        formes: elles servent de clés au cache du calcul)."""
        if not art:
            return None
        if art in self._profils_outils:
            return self._profils_outils[art]
        profil = None
        bib = self.bibliotheque
        outil = next((t for t in getattr(bib, 'tools', {}).values()
                      if art in (str(getattr(t, 'article_nr', '') or ''),
                                 str(getattr(t, 'name', '') or ''))), None)
        if outil is not None:
            try:
                from src.core import dessin_outil, sim_cycles
                profil = dessin_outil.profil(dessin_outil.cotes_outil(
                    outil, sim_cycles._catalogue()))['points']
            except Exception:
                profil = None
        self._profils_outils[art] = profil
        return profil

    def _sur_lecture(self, on) -> None:
        if on:
            if self.avance.value() >= self.AVANCE_MAX:
                self.avance.setValue(0)
                self._t_lecture = 0.0
            from src.gui.icons import get_button_icon
            self.lecture.setIcon(get_button_icon("pause", 16))
            self.vue.lecture_en_cours = True
            self._horloge.start()
            self._minuterie.start()
        else:
            from src.gui.icons import get_button_icon
            self.lecture.setIcon(get_button_icon("play", 16))
            self._minuterie.stop()
            # à l'arrêt, l'image entière (le parcours par calques)
            self.vue.lecture_en_cours = False
            self.vue.update()
            # à l'arrêt, la matière reprend son maillage fin
            if self.cb_matiere.isChecked():
                self._maj_matiere()

    def _pas_de_lecture(self, dt: float = None) -> None:
        """Un pas de lecture: le temps machine avance du temps écoulé
        fois la vitesse (×1 = la machine); l'outil va au sommet atteint."""
        if dt is None:
            dt = (self._horloge.restart() / 1000.0
                  if self._horloge.isValid() else
                  self._minuterie.interval() / 1000.0)
        if self._temps is None or not len(self._temps) \
                or self.duree_machine() <= 0:
            # sans temps machine: l'ancienne lecture en DUREE_LECTURE
            pas = max(1, int(self.AVANCE_MAX * self._minuterie.interval()
                             / self.DUREE_LECTURE))
            valeur = self.avance.value() + pas
            if valeur >= self.AVANCE_MAX:
                self.avance.setValue(self.AVANCE_MAX)
                self.lecture.setChecked(False)
                return
            self.avance.setValue(valeur)
            return
        self._t_lecture += max(0.0, float(dt)) * self.vitesse_lecture()
        if self._t_lecture >= self.duree_machine():
            self._sommet_force = None
            self.avance.setValue(self.AVANCE_MAX)
            self.lecture.setChecked(False)
            return
        n = int(np.searchsorted(self._temps, self._t_lecture, side='right'))
        n = max(1, min(n, len(self._P)))
        # l'outil en chemin vers le sommet n (un long segment ne le
        # fige plus jusqu'au saut)
        bout = None
        if n < len(self._P):
            t0, t1 = float(self._temps[n - 1]), float(self._temps[n])
            if t1 > t0:
                f = (self._t_lecture - t0) / (t1 - t0)
                bout = self._P[n - 1] + f * (self._P[n] - self._P[n - 1])
        self._sommet_force = n
        self.avance.blockSignals(True)
        self.avance.setValue(min(self.AVANCE_MAX - 1, int(round(
            self.AVANCE_MAX * n / max(1, len(self._P))))))
        self.avance.blockSignals(False)
        self._afficher_sommet(n, bout)

    # ──── La matière ────

    #: côté maxi du maillage du dessus du brut (cellules), au repos et
    #: pendant la lecture
    COTES_MATIERE = 300
    COTES_MATIERE_LECTURE = 120
    #: ... et dans une vue qui bouge, si le maillage fin est trop lourd
    COTES_MATIERE_MOUVEMENT = 72
    #: au-delà de ces sommets à passer, l'enlèvement se suit dans la
    #: barre d'état (avec Annuler)
    SOMMETS_SUIVIS = 30000
    #: (brut, sommets appliqués, côtés) du dernier maillage de la matière
    _maille_faite = None
    #: un long enlèvement est en cours (sa boucle d'attente laisse vivre
    #: l'interface: lecture, curseur, programme)
    _matiere_en_calcul = False
    #: les couleurs des tronçons, et ce dont dépendent les temps calculés
    _couleurs_runs = None
    _temps_faits = None

    def _sur_matiere(self, on) -> None:
        if on:
            self._maj_matiere(cadrer=True)
        else:
            self._texte_matiere = ""
            self._maj_info()
        self.vue.update()

    def _sommets_montres(self) -> int:
        if self._sim is None:
            return 0
        if self._sommet_force is not None:
            return self._sommet_force
        if self.avance.value() >= self.AVANCE_MAX:
            return len(self._P)
        return self.sommet_de_l_avance()

    def _maj_matiere(self, cadrer: bool = False,
                     avec_vue: bool = True) -> None:
        """Le brut creusé jusqu'à l'avance (le même brut se poursuit
        quand on avance; revenir en arrière le refait)."""
        if self._matiere_en_calcul:
            # un long enlèvement est en cours: il reprendra à sa fin ce
            # qui a changé entre-temps (un second, lancé d'ici, creusait
            # le même brut en même temps, sous une fenêtre)
            return
        if not self.cb_matiere.isChecked() or self._sim is None:
            self._brut = None
            self._brut_sim = None
            self._maille_faite = None
            self._texte_matiere = ""
            scene = self._matiere_de_scene
            if scene is not None and self.cb_matiere.isChecked():
                # une phase de bridage: sa matière est toute faite
                self.vue.set_matiere(scene[0], scene[1])
            else:
                self.vue.set_matiere(None)
            self._maj_info()
            return
        from src.core import enlevement
        boite = self.boite_programme()
        if self._brut is None or self._brut_sim is not self._sim \
                or getattr(self, '_brut_boite', None) != boite:
            self._brut = enlevement.Brut.autour(self._sim, boite=boite)
            self._brut_sim = self._sim
            self._brut_boite = boite
        n = self._sommets_montres()
        formes = self._sim.get('formes') or {}
        a_passer = n if n < self._brut.applique else n - self._brut.applique
        if a_passer > self.SOMMETS_SUIVIS:
            from src.gui.progression import travailler
            brut, sim = self._brut, self._sim
            # la lecture attend la matière: un battement pendant le
            # calcul en lançait un second
            lisait = self._minuterie.isActive()
            if lisait:
                self._minuterie.stop()
            self._matiere_en_calcul = True
            try:
                fait = travailler(
                    self, "Enlèvement de matière",
                    lambda prog: brut.appliquer(sim, formes, n, prog) or True,
                    "Passage de l'outil dans le brut…")
            finally:
                self._matiere_en_calcul = False
                if lisait and self.lecture.isChecked():
                    # (le temps du calcul n'est pas du temps machine)
                    self._horloge.restart()
                    self._minuterie.start()
            if fait is None:
                # annulé: le fil creuse encore ce brut jusqu'à son
                # prochain compte rendu — il est abandonné (le remettre à
                # neuf ici le laissait à moitié creusé pour la fois
                # suivante), un neuf se refera
                self._brut = None
                self._brut_sim = None
                self._maille_faite = None
                # la case se décoche pour de bon: l'œil du panneau suit
                self.cb_matiere.setChecked(False)
                self.vue.montrer_matiere = False
                self._texte_matiere = "matière: calcul annulé"
                self.vue.set_matiere(None)
                self._maj_info()
                return
            if (self._brut is not brut or self._sim is not sim
                    or not self.cb_matiere.isChecked()
                    or self._sommets_montres() != n):
                # la scène a changé pendant le calcul (programme, brut,
                # avance, case): la matière reprend où elle en est
                self._maj_matiere(cadrer, avec_vue)
                return
        else:
            self._brut.appliquer(self._sim, formes, n)
        # en lecture, un maillage plus léger: l'image suit l'outil
        lecture = self._minuterie.isActive()
        cotes = (self.COTES_MATIERE_LECTURE if lecture
                 else self.COTES_MATIERE)
        # ... et rien à refaire tant qu'aucune matière n'est partie
        maille = (self._brut, self._brut.applique, cotes)
        if lecture and not cadrer and self._maille_faite is not None \
                and self._maille_faite[0] is maille[0] \
                and self._maille_faite[1:] == maille[1:]:
            return
        self._maille_faite = maille
        tri, col = self._brut.maillage(cotes)
        # (le maillage grossier: pour une rotation, s'il y en a une)
        grossier = ((np.zeros((0, 3, 3)), np.zeros((0, 3)))
                    if lecture and self.vue._glisse is None
                    else self._brut.maillage(self.COTES_MATIERE_MOUVEMENT))
        if avec_vue:
            self.vue.set_matiere(tri, col, grossier, cadrer)
        else:
            self.vue._tri_matiere, self.vue._col_matiere = tri, col
            (self.vue._tri_matiere_grossier,
             self.vue._col_matiere_grossier) = grossier
        b = self._brut
        vol = b.volume_enleve()
        texte_vol = (f"{vol / 1000:.2f} cm³" if vol >= 1000
                     else f"{vol:.0f} mm³")
        zone = (f"zone usinée {b.nx * b.pas:.0f} × {b.ny * b.pas:.0f} "
                f"du brut {b.reduit[0]:.0f} × {b.reduit[1]:.0f}"
                if b.reduit else
                f"brut {b.nx * b.pas:.0f} × {b.ny * b.pas:.0f}")
        self._texte_matiere = (
            f"matière: {texte_vol} enlevés · {zone} × "
            f"{b.z_haut - b.z_bas:.0f} (grille {b.pas:.2f} mm)")
        self._maj_info()

    def _maj_info(self) -> None:
        morceaux = [m for m in (self._texte_base, self._texte_matiere) if m]
        if getattr(self, '_perime', False):
            morceaux.insert(0, "⚠ le programme a changé: « ↻ Calculer » "
                               "pour mettre la vue à jour")
        self.info.setText(" · ".join(morceaux))

    # ──── Les faces choisies ────

    def faces_selectionnees(self) -> list:
        """Les infos (step3d.info_face) des faces choisies."""
        faces = getattr(self._modele, 'faces', None) or []
        return [faces[i] for i in sorted(self.vue.selection)
                if 0 <= i < len(faces)]

    def propositions(self) -> list:
        """[(libellé, [opération])] pour la sélection."""
        from src.core import usinage_faces
        faces = self.faces_selectionnees()
        if not faces or self._piece_place is None:
            return []
        dx, dy, haut, bas = self._piece_place
        return usinage_faces.propositions(
            faces, self.bibliotheque, (dx, dy), haut, bas,
            getattr(self._modele, 'triangles', None))

    def menu_usinage(self):
        """Le menu « Usiner la sélection »: (menu, {action: opérations})."""
        menu = QMenu(self)
        actions = {}
        choix = self.propositions()
        if not choix:
            vide = menu.addAction(
                "Choisissez des faces de la pièce (clic, Ctrl+clic)"
                if not self.vue.selection else
                "Rien à usiner en 2D pour ces faces")
            vide.setEnabled(False)
            return menu, actions
        for libelle, ops in choix:
            actions[menu.addAction(libelle)] = ops
        return menu, actions

    def _montrer_menu_usinage(self) -> None:
        menu, actions = self.menu_usinage()
        choisi = menu.exec(self.usiner.mapToGlobal(
            self.usiner.rect().bottomLeft()))
        ops = actions.get(choisi)
        if ops:
            self.usinage_demande.emit(ops)

    def _sur_selection(self) -> None:
        self.usinage3d.setEnabled(self._piece_place is not None and len(
            getattr(self._modele, 'triangles', ())) > 0)
        faces = self.faces_selectionnees()
        self.usiner.setEnabled(bool(faces))
        self.deselectionner.setEnabled(bool(self.vue.selection))
        if not faces:
            self.selection_info.setText(
                "Clic sur une face de la pièce pour la choisir "
                "(Ctrl+clic: plusieurs)" if self._modele is not None
                else "Importez une pièce STEP pour en usiner les faces")
            return
        from src.core import usinage_faces
        dx, dy, haut, bas = self._piece_place or (0.0, 0.0, 0.0, None)
        self.selection_info.setText(usinage_faces.decrire(
            faces, (dx, dy), haut, bas,
            getattr(self._modele, 'triangles', None)))
