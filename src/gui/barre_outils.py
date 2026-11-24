"""Une seule barre d'outils, placée en haut, en bas, à gauche ou à
droite de sa vue.

Le Canva 3D sorti dans sa fenêtre perdait la moitié de sa hauteur en
rangées de boutons; le Canva 2D aussi. Tous les outils d'une vue
tiennent sur UNE barre; l'utilisateur la place où il veut (clic droit
sur la barre, ou son bouton « ⇄ »), et la place est retenue.

Octobre 2026 (RomDuch): la barre ne défile plus, elle passe à la
ligne. Ses boutons n'ont plus que leur icône; leur nom s'affiche dans
la ligne d'état de la vue quand la souris les survole (la bulle garde
l'explication longue).

Le retour à la ligne: la barre range des GROUPES (des widgets qui
portent déjà leurs boutons), mais c'est le layout de la barre
(`FluxLayout`, le « maître ») qui place lui-même chaque bouton de
chaque groupe, en lignes — en colonnes quand la barre est à gauche ou
à droite. Les groupes ne sont plus que des sacs: leur layout devient
un FluxLayout « transparent » qui garde la liste de ses éléments
(`indexOf`, `count`, `addWidget` répondent toujours) sans rien placer.
Un groupe caché cache ses boutons, comme avant (la boîte d'outils du
calque ouvert). Chaque groupe couvre toute la barre et porte un
masque, l'union de ses boutons: un clic à côté passe au groupe d'en
dessous.
"""

from typing import Callable, List, Optional

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QPainter, QPixmap, QRegion
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QBoxLayout, QCheckBox, QFrame, QHBoxLayout, QLayout,
    QMenu, QScrollArea, QSizePolicy, QSpacerItem, QToolButton, QWidget
)

POSITIONS = ('haut', 'bas', 'gauche', 'droite')
NOMS = {'haut': "En haut", 'bas': "En bas", 'gauche': "À gauche",
        'droite': "À droite"}
#: le sens du layout hôte: la barre vient en premier
_SENS_HOTE = {'haut': QBoxLayout.Direction.TopToBottom,
              'bas': QBoxLayout.Direction.BottomToTop,
              'gauche': QBoxLayout.Direction.LeftToRight,
              'droite': QBoxLayout.Direction.RightToLeft}

#: la propriété d'un petit bloc qui reste d'un seul tenant (un nom et
#: son œil, une étiquette et sa valeur): la barre ne le défait pas
GARDE = 'barre_garde_sens'
#: taille des icônes et des boutons-icônes
TAILLE_ICONE = 18
TAILLE_BOUTON = QSize(30, 28)


def _reglages():
    from src.gui.theme import reglages_qt
    return reglages_qt()


def bloc(*widgets: QWidget, espace: int = 2) -> QWidget:
    """Des widgets qui restent ensemble sur la barre (« Z × » et sa
    valeur, une case et son unité): la ligne ne coupe pas entre eux."""
    w = QWidget()
    w.setProperty(GARDE, True)
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(espace)
    for e in widgets:
        h.addWidget(e)
    return w


def _est_trait(w: QWidget) -> bool:
    return type(w) is QFrame and w.frameShape() in (QFrame.Shape.VLine,
                                                    QFrame.Shape.HLine)


def _est_sac(w: QWidget) -> bool:
    """Un groupe que la barre ouvre (ses éléments sont placés un à un):
    un QWidget nu qui porte un QBoxLayout, sauf un bloc gardé."""
    return (type(w) is QWidget and isinstance(w.layout(), QBoxLayout)
            and not w.property(GARDE))


class FluxLayout(QLayout):
    """Des éléments en lignes qui passent à la suivante quand la place
    manque (en colonnes, `vertical`).

    Le maître place les FEUILLES de toute l'arborescence: il descend
    dans les widgets dont le layout est un FluxLayout transparent."""

    def __init__(self, parent=None, transparent: bool = False):
        super().__init__(parent)
        self._items = []
        self.transparent = transparent
        #: le FluxLayout maître (pour un transparent)
        self.maitre: Optional['FluxLayout'] = None
        self.vertical = False
        #: les noms des boutons-icônes, dépliés sous leur icône
        self.noms = False
        #: les légendes posées au dernier placement
        self._legendes_posees = set()
        #: appelé quand l'épaisseur voulue change (le maître)
        self.sur_besoin: Optional[Callable[[], None]] = None
        self._besoin = -1
        #: les transparents de l'arborescence (le maître les garde)
        self._sacs: List[QWidget] = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(3)

    # ── la liste ──

    def addItem(self, item) -> None:
        self._items.append(item)
        self.invalidate()

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):
        if 0 <= index < len(self._items):
            item = self._items.pop(index)
            self.invalidate()
            return item
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def invalidate(self) -> None:
        super().invalidate()
        if self.transparent and self.maitre is not None:
            self.maitre.invalidate()

    # ── les tailles ──

    def hasHeightForWidth(self) -> bool:
        return not self.transparent and not self.vertical

    def heightForWidth(self, largeur: int) -> int:
        if self.transparent:
            return 0
        return self._disposer(QRect(0, 0, largeur, 0), False)

    def largeur_pour_hauteur(self, hauteur: int) -> int:
        return self._disposer(QRect(0, 0, 0, hauteur), False)

    def _plus_grande(self) -> QSize:
        taille = QSize(0, 0)
        for it, _w, _sac in self._feuilles():
            taille = taille.expandedTo(it.sizeHint())
        m = self.contentsMargins()
        return taille + QSize(m.left() + m.right(), m.top() + m.bottom())

    def minimumSize(self) -> QSize:
        if self.transparent:
            return QSize(0, 0)
        return self._plus_grande()

    def sizeHint(self) -> QSize:
        if self.transparent:
            return QSize(0, 0)
        base = self._plus_grande()
        if self.vertical:
            return QSize(base.width(), base.height())
        return QSize(base.width(), self.heightForWidth(base.width()))

    # ── la place ──

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        if self.transparent:
            return                    # le maître s'en charge
        besoin = self._disposer(rect, True)
        if besoin != self._besoin:
            self._besoin = besoin
            if self.sur_besoin is not None:
                self.sur_besoin()

    def _feuilles(self, layout=None, sac=None):
        """(item, widget, sac le plus proche) de chaque feuille montrée,
        dans l'ordre de la barre."""
        layout = self if layout is None else layout
        for i in range(layout.count()):
            it = layout.itemAt(i)
            if it is None:
                continue
            w = it.widget()
            if w is not None:
                if it.isEmpty():
                    continue               # caché (lui ou son groupe)
                sous = w.layout()
                if isinstance(sous, FluxLayout) and sous.transparent:
                    yield from self._feuilles(sous, w)
                elif sous is not None and it.sizeHint().isEmpty():
                    continue               # un bloc dont tout est caché
                else:
                    yield it, w, sac
            elif it.layout() is not None:
                yield from self._feuilles(it.layout(), sac)

    def _disposer(self, rect: QRect, appliquer: bool) -> int:
        """Range les feuilles dans `rect`; rend l'épaisseur occupée
        (la hauteur, en lignes; la largeur, en colonnes)."""
        m = self.contentsMargins()
        esp = self.spacing()
        zone = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        vertical = self.vertical
        longueur = zone.height() if vertical else zone.width()
        lignes, ligne, pos = [], [], 0
        replies = []
        for it, w, sac in self._feuilles():
            trait = _est_trait(w)
            t = it.sizeHint()
            lg = None if trait else _legende(w, self.noms)
            if lg is not None:
                tl = _taille_legende(lg)
                t = QSize(max(t.width(), tl.width()),
                          t.height() + 1 + tl.height())
            l = 1 if trait else (t.height() if vertical else t.width())
            if ligne and pos + l > longueur:
                lignes.append(ligne)
                ligne, pos = [], 0
            if trait and (not ligne or ligne[-1][4]):
                # pas de trait en tête, ni deux de suite (un groupe
                # caché entre deux traits)
                replies.append((it, w, sac))
                continue
            ligne.append((it, w, sac, t, trait))
            pos += l + esp
        if ligne:
            lignes.append(ligne)
        for li in lignes:                      # ni en queue
            while li and li[-1][4]:
                it, w, sac, _t, _tr = li.pop()
                replies.append((it, w, sac))
        lignes = [li for li in lignes if li]

        places = []
        travers = zone.left() if vertical else zone.top()
        for li in lignes:
            ep = max([(t.width() if vertical else t.height())
                      for _i, _w, _s, t, tr in li if not tr] or [1])
            le_long = zone.top() if vertical else zone.left()
            for it, w, sac, t, trait in li:
                if vertical:
                    if trait:
                        r = QRect(travers + 3, le_long, max(1, ep - 6), 1)
                        le_long += 1 + esp
                    else:
                        r = QRect(travers + (ep - t.width()) // 2, le_long,
                                  t.width(), t.height())
                        le_long += t.height() + esp
                else:
                    if trait:
                        r = QRect(le_long, travers + 3, 1, max(1, ep - 6))
                        le_long += 1 + esp
                    else:
                        r = QRect(le_long, travers + (ep - t.height()) // 2,
                                  t.width(), t.height())
                        le_long += t.width() + esp
                lg = None if trait else _legende(w, self.noms)
                if lg is not None:
                    # l'icône en haut de sa cellule, son nom dessous
                    b = it.sizeHint()
                    tl = _taille_legende(lg)
                    rl = QRect(r.x() + (r.width() - tl.width()) // 2,
                               r.y() + b.height() + 1, tl.width(),
                               tl.height())
                    r = QRect(r.x() + (r.width() - b.width()) // 2, r.y(),
                              b.width(), b.height())
                    places.append((it, w, sac, r, lg, rl))
                    continue
                places.append((it, w, sac, r, None, None))
            travers += ep + esp
        debut = zone.left() if vertical else zone.top()
        besoin = (max(0, travers - esp - debut) if lignes else 0)
        besoin += (m.left() + m.right()) if vertical else (m.top() + m.bottom())
        if appliquer:
            self._appliquer(rect, places, replies)
        return besoin

    def _appliquer(self, rect: QRect, places, replies) -> None:
        origine = rect.topLeft()
        regions = {}
        posees = set()
        for it, w, sac, r, lg, rl in places:
            local = r.translated(-origine) if sac is not None else r
            it.setGeometry(local)
            zone = QRegion(local)
            if lg is not None:
                rl_local = rl.translated(-origine) if sac is not None else rl
                lg.setGeometry(rl_local)
                lg.show()
                lg.raise_()
                posees.add(lg)
                zone = zone.united(QRegion(rl_local))
            if sac is not None:
                regions.setdefault(id(sac), QRegion())
                regions[id(sac)] = regions[id(sac)].united(zone)
        for lg in self._legendes_posees - posees:
            try:
                lg.hide()
            except RuntimeError:
                pass
        self._legendes_posees = posees
        for it, _w, sac in replies:
            it.setGeometry(QRect(0, 0, 0, 0))
        # chaque sac couvre la barre; son masque: ses feuilles et
        # celles des sacs qu'il contient
        for sac in self._sacs:
            try:
                parent = sac.parentWidget()
            except RuntimeError:
                continue
            haut_niveau = parent is self.parentWidget()
            sac.setGeometry(rect if haut_niveau
                            else QRect(QPoint(0, 0), rect.size()))
        for sac in reversed(self._sacs):         # les plus profonds d'abord
            try:
                region = regions.get(id(sac), QRegion())
                for enfant in sac.findChildren(QWidget, options=Qt.FindChildOption.FindDirectChildrenOnly):
                    if id(enfant) in regions:
                        region = region.united(regions[id(enfant)])
                regions[id(sac)] = region
                sac.setMask(region if not region.isEmpty()
                            else QRegion(0, 0, 1, 1))
            except RuntimeError:
                continue


def _transparent(sac: QWidget, maitre: FluxLayout) -> None:
    """Le layout du groupe devient un FluxLayout transparent (mêmes
    éléments, même ordre, sans les étirements); ses sous-groupes aussi."""
    vieux = sac.layout()
    items = []
    while vieux.count():
        items.append(vieux.takeAt(0))
    QWidget().setLayout(vieux)          # l'ancien layout s'en va
    flux = FluxLayout(transparent=True)
    flux.maitre = maitre
    sac.setLayout(flux)
    maitre._sacs.append(sac)

    def _verser(liste):
        for it in liste:
            if isinstance(it, QSpacerItem) or (
                    it.widget() is None and it.layout() is None):
                continue
            if it.layout() is not None:
                sous = it.layout()
                enfants = []
                while sous.count():
                    enfants.append(sous.takeAt(0))
                _verser(enfants)
                continue
            w = it.widget()
            flux.addItem(it)
            if _est_sac(w):
                _transparent(w, maitre)
    _verser(items)


# ══════════════ boutons-icônes ══════════════

def _texte_propre(t: str) -> str:
    return " ".join((t or "").replace("&", "").split())


def _icone_fanee(icone: QIcon, taille: int) -> QIcon:
    """L'icône d'une bascule: pleine enfoncée, pâlie relâchée."""
    pleine = icone.pixmap(taille, taille)
    pale = QPixmap(pleine.size())
    pale.setDevicePixelRatio(pleine.devicePixelRatio())
    pale.fill(Qt.GlobalColor.transparent)
    p = QPainter(pale)
    p.setOpacity(0.38)
    p.drawPixmap(0, 0, pleine)
    p.end()
    sortie = QIcon()
    sortie.addPixmap(pleine, QIcon.Mode.Normal, QIcon.State.On)
    sortie.addPixmap(pale, QIcon.Mode.Normal, QIcon.State.Off)
    return sortie


def _icone_de(bouton: QAbstractButton, nom: str) -> QIcon:
    """L'icône `nom`; sur un bouton à fond d'accent (primary, danger),
    teinte du texte de ces boutons (sinon bleu sur bleu)."""
    from src.gui import icons
    if bouton.objectName() in ('primary', 'danger'):
        return icons.get_button_icon(nom, TAILLE_ICONE, on_accent=True)
    return icons.get_icon(nom, TAILLE_ICONE)


def _feuille_style(bouton: QAbstractButton, propre: str) -> str:
    """La feuille de style du bouton (la sienne), plus ce qu'il faut à
    un bouton-icône: peu de marge, un fond quand il est enfoncé."""
    from src.gui.icons import _colors
    c = _colors()
    if isinstance(bouton, QCheckBox):
        cls = "QCheckBox"
    elif isinstance(bouton, QToolButton):
        cls = "QToolButton"
    else:
        cls = "QPushButton"
    propre = (propre or "").strip()
    if propre and "{" not in propre:
        propre = f"{cls} {{ {propre} }}"
    if cls == "QCheckBox":
        avant = (f"QCheckBox {{ spacing: 0px; padding: 0px 5px; "
                 f"border: 1px solid transparent; border-radius: 5px; }}"
                 f"QCheckBox:hover {{ border: 1px solid {c['accent']}; }}"
                 f"QCheckBox:checked {{ background-color: {c['surface_press']};"
                 f" border: 1px solid {c['accent']}; }}")
        apres = ("QCheckBox::indicator { width: 0px; height: 0px; "
                 "border: none; background: transparent; margin: 0px; }")
    else:
        avant = (f"{cls}:checked {{ background-color: {c['surface_press']};"
                 f" border: 1px solid {c['accent']}; }}")
        apres = f"{cls} {{ padding: 2px; min-width: 0px; min-height: 0px; }}"
    return f"{avant} {propre} {apres}"


def icone_seule(bouton: QAbstractButton, icone: str = "",
                libelle: str = "") -> QAbstractButton:
    """Le bouton (ou la case) ne montre plus que son icône; son nom
    reste dans `text()` (le code et les tests le lisent toujours), dans
    son nom accessible, et s'affiche en ligne d'état au survol."""
    from src.gui.icons import get_icon
    from src.gui import icones_barre  # noqa: F401  (les icônes « b_… »)
    if bouton.property('icone_seule'):
        return bouton
    nom = _texte_propre(libelle or bouton.text())
    bouton.setProperty('libelle', nom)
    bouton.setProperty('icone_seule', True)
    if icone:
        bouton.setProperty('icone_nom', icone)
    ic = _icone_de(bouton, icone) if icone else bouton.icon()
    if isinstance(bouton, QCheckBox):
        ic = _icone_fanee(ic, TAILLE_ICONE)
    bouton.setIcon(ic)
    bouton.setIconSize(QSize(TAILLE_ICONE, TAILLE_ICONE))
    QAbstractButton.setText(bouton, "")
    bouton.setAccessibleName(nom)

    def _texte(b=bouton):
        return b.property('libelle') or ""

    def _poser_texte(t, b=bouton):
        b.setProperty('libelle', _texte_propre(t))
        b.setAccessibleName(_texte_propre(t))
        lg = getattr(b, '_legende', None)
        if lg is not None:
            lg.setText(_texte_propre(t))

    def _poser_style(s, b=bouton):
        b.setProperty('style_propre', s or "")
        QWidget.setStyleSheet(b, _feuille_style(b, s))

    bouton.text = _texte
    bouton.setText = _poser_texte
    bouton.setStyleSheet = _poser_style
    _poser_style(QWidget.styleSheet(bouton))
    bouton.setFixedSize(TAILLE_BOUTON)
    return bouton


#: largeur d'un nom sous son icône (px); deux lignes au plus
LARGEUR_LEGENDE = 70
#: un mot plus long élargit son nom jusque-là
LARGEUR_MOT = 96


class _CliqueLegende(QObject):
    """Un clic sur le nom vaut un clic sur le bouton."""

    def __init__(self, bouton):
        super().__init__(bouton)
        self._bouton = bouton

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.MouseButtonRelease \
                and ev.button() == Qt.MouseButton.LeftButton:
            try:
                if self._bouton.isEnabled():
                    self._bouton.click()
            except RuntimeError:
                pass
            return True
        if ev.type() in (QEvent.Type.Enter, QEvent.Type.Leave):
            QApplication.sendEvent(self._bouton, QEvent(ev.type()))
        return False


def _legende(bouton: QWidget, noms: bool):
    """Le nom d'un bouton-icône posé sous lui (créé à la première
    demande), ou None."""
    if not noms or not bouton.property('icone_seule') \
            or bouton.property('large'):
        return None                  # un bouton élargi écrit son nom
    lg = getattr(bouton, '_legende', None)
    if lg is None:
        from PySide6.QtWidgets import QLabel
        lg = QLabel(bouton.property('libelle') or "", bouton.parentWidget())
        lg.setObjectName("legende_barre")
        lg.setAlignment(Qt.AlignmentFlag.AlignHCenter
                        | Qt.AlignmentFlag.AlignTop)
        lg.setWordWrap(True)
        police = lg.font()
        police.setPointSizeF(max(6.5, police.pointSizeF() * 0.78))
        lg.setFont(police)
        lg.setStyleSheet("QLabel#legende_barre { background: transparent; }")
        lg.installEventFilter(_CliqueLegende(bouton))
        lg.setCursor(Qt.CursorShape.PointingHandCursor)
        bouton._legende = lg
    return lg


def _taille_legende(lg) -> QSize:
    """Deux lignes au plus, assez large pour son mot le plus long
    (jusqu'à LARGEUR_MOT): un mot ne se coupe pas."""
    fm = lg.fontMetrics()
    texte = lg.text()
    mot = max([fm.horizontalAdvance(m) for m in texte.split()] or [0])
    largeur = max(24, min(LARGEUR_MOT, max(mot + 4, min(
        LARGEUR_LEGENDE, fm.horizontalAdvance(texte) + 4))))
    r = fm.boundingRect(QRect(0, 0, largeur, 400),
                        int(Qt.TextFlag.TextWordWrap
                            | Qt.AlignmentFlag.AlignHCenter), texte)
    lignes = max(1, min(2, round(r.height() / max(1, fm.lineSpacing()))))
    return QSize(largeur, lignes * fm.lineSpacing() + 3)


def texte_etat(bouton: QWidget) -> str:
    """Ce que la ligne d'état dit d'un bouton survolé: son nom, et la
    première ligne de sa bulle quand elle en dit plus."""
    nom = bouton.property('libelle') or _texte_propre(
        bouton.text() if hasattr(bouton, 'text') else "")
    bulle = (bouton.toolTip() or "").strip().splitlines()
    premiere = bulle[0].strip() if bulle else ""
    if not premiere:
        return nom
    if not nom or premiere.lower().startswith(nom.lower().rstrip('.…')):
        return premiere
    return f"{nom} — {premiere}"


class _Survol(QObject):
    def __init__(self, barre):
        super().__init__(barre)
        self._barre = barre

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.Type.Enter:
            self._barre.survol.emit(texte_etat(obj))
        elif t in (QEvent.Type.Leave, QEvent.Type.Hide):
            self._barre.survol.emit("")
        return False


class BarreOutils(QScrollArea):
    """La barre unique d'une vue."""

    #: la barre a changé de place ('haut', 'bas', 'gauche', 'droite')
    position_changee = Signal(str)
    #: la souris entre sur un bouton (son texte d'état) ou en sort ("")
    survol = Signal(str)

    #: la barre ne prend pas plus que cette part de la vue (au-delà,
    #: elle défile)
    PART_MAX = 0.5

    def __init__(self, cle_reglage: str, parent=None,
                 defaut: str = 'haut'):
        super().__init__(parent)
        self.cle = cle_reglage
        self._ajustement_prevu = False
        self._hote: Optional[QBoxLayout] = None
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setWidgetResizable(True)
        self._contenu = QWidget()
        self._contenu.setObjectName("barre_outils")
        self._lay = FluxLayout(self._contenu)
        self._lay.setContentsMargins(2, 2, 2, 2)
        self._lay.setSpacing(3)
        self._lay.sur_besoin = self._ajuster_plus_tard
        self.setWidget(self._contenu)
        self._groupes: List[QWidget] = []
        #: les boutons élargis: [(bouton, nom court écrit à côté)]
        self._larges = []
        self._survol = _Survol(self)
        self._contenu.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self._contenu.customContextMenuRequested.connect(
            lambda p: self.menu_placement().exec(
                self._contenu.mapToGlobal(p)))
        self.bouton = QToolButton()
        self.bouton.setText("Placer la barre")
        self.bouton.setToolTip("Placer la barre d'outils: en haut, en "
                               "bas, à gauche ou à droite")
        self.bouton.setAutoRaise(True)
        self.bouton.clicked.connect(
            lambda: self.menu_placement().exec(
                self.bouton.mapToGlobal(self.bouton.rect().bottomLeft())))
        try:
            lue = str(_reglages().value(self.cle, defaut) or defaut)
        except Exception:
            lue = defaut
        self.position = lue if lue in POSITIONS else defaut
        try:
            noms = _reglages().value(self.cle + "_noms", False)
            noms = str(noms).lower() in ("1", "true", "yes")
        except Exception:
            noms = False
        self.noms = noms
        self._lay.noms = noms
        #: déplie / replie les noms sous les icônes
        self.bouton_noms = QToolButton()
        self.bouton_noms.setText("Noms sous les icônes")
        self.bouton_noms.setToolTip(
            "Déplier les noms sous les icônes (la barre s'agrandit); "
            "re-cliquer les replie")
        self.bouton_noms.setCheckable(True)
        self.bouton_noms.setChecked(noms)
        self.bouton_noms.setAutoRaise(True)
        self.bouton_noms.toggled.connect(self.afficher_noms)

    # ── contenu ──

    def ajouter(self, groupe: QWidget, sans_etirements: bool = True
                ) -> QWidget:
        """Un groupe d'outils au bout de la barre: ses boutons sont
        rangés un à un, avec ceux des autres groupes (les étirements
        internes s'en vont: ils écartaient les groupes)."""
        groupe.setParent(self._contenu)
        if _est_sac(groupe):
            _transparent(groupe, self._lay)
        self._lay.addWidget(groupe)
        self._groupes.append(groupe)
        return groupe

    def terminer(self) -> None:
        """Le bout de la barre: le bouton qui la place."""
        icone_seule(self.bouton_noms, "b_noms", "Noms sous les icônes")
        icone_seule(self.bouton, "b_placer", "Placer la barre d'outils")
        self._lay.addWidget(self.bouton_noms)
        self._lay.addWidget(self.bouton)
        self.suivre_survol(self.bouton_noms)
        self.suivre_survol(self.bouton)

    def groupes(self) -> List[QWidget]:
        return list(self._groupes)

    def boutons(self) -> List[QAbstractButton]:
        """Les boutons de la barre, hors blocs gardés (les onglets de
        calque et leur œil gardent leur nom)."""
        sortie = []
        for b in self._contenu.findChildren(QAbstractButton):
            p, garde = b.parentWidget(), False
            while p is not None and p is not self._contenu:
                # un bloc gardé d'une classe à lui: un onglet de calque
                if p.property(GARDE) and type(p) is not QWidget:
                    garde = True
                    break
                p = p.parentWidget()
            if not garde:
                sortie.append(b)
        return sortie

    def icones(self, table) -> None:
        """Les boutons en icônes: [(bouton, icône, libellé), …]."""
        for bouton, icone, libelle in table:
            if bouton is None:
                continue
            icone_seule(bouton, icone, libelle)
            self.suivre_survol(bouton)
        self._lay.invalidate()

    def elargir(self, bouton: QAbstractButton, texte: str) -> None:
        """Un bouton-icône ÉLARGI: son icône et un nom court écrit à
        côté (novembre 2026, RomDuch: « élargir bouton import » — le
        geste d'entrée ne se cherche pas parmi les icônes). Barre en
        colonne (à gauche, à droite): il redevient une icône, pour ne
        pas élargir toute la colonne."""
        if bouton is None:
            return
        self._larges = [(b, t) for b, t in self._larges if b is not bouton]
        self._larges.append((bouton, texte))
        self._maj_larges()
        self._lay.invalidate()

    def _maj_larges(self) -> None:
        vertical = bool(self._lay.vertical)
        for b, texte in self._larges:
            try:
                if vertical:
                    b.setProperty('large', False)
                    QAbstractButton.setText(b, "")
                    b.setFixedSize(TAILLE_BOUTON)
                    continue
                b.setProperty('large', True)
                visible = " " + texte
                QAbstractButton.setText(b, visible)
                b.ensurePolished()
                police = b.font()
                police.setBold(True)
                from PySide6.QtGui import QFontMetrics
                largeur = (TAILLE_ICONE + 30
                           + QFontMetrics(police).horizontalAdvance(visible))
                b.setFixedSize(QSize(max(3 * TAILLE_BOUTON.width(), largeur),
                                     TAILLE_BOUTON.height()))
            except RuntimeError:
                continue

    def suivre_survol(self, widget: QWidget) -> None:
        widget.installEventFilter(self._survol)

    def relier_etat(self, etiquette) -> None:
        """La ligne d'état de la vue: le nom du bouton survolé s'y
        affiche, puis le message d'avant revient."""
        memo = {'avant': None, 'montre': None}

        def _sur(texte):
            try:
                if texte:
                    if memo['avant'] is None:
                        memo['avant'] = etiquette.text()
                    etiquette.setText(texte)
                    memo['montre'] = texte
                elif memo['avant'] is not None:
                    if etiquette.text() == memo['montre']:
                        etiquette.setText(memo['avant'])
                    memo['avant'] = memo['montre'] = None
            except RuntimeError:
                pass
        self.survol.connect(_sur)

    def rafraichir_icones(self) -> None:
        """Après un changement de thème: les icônes à ses couleurs."""
        from src.gui import icons, icones_barre  # noqa: F401
        for b in self._contenu.findChildren(QAbstractButton):
            nom = b.property('icone_nom')
            if not nom:
                continue
            ic = _icone_de(b, nom)
            if isinstance(b, QCheckBox):
                ic = _icone_fanee(ic, TAILLE_ICONE)
            b.setIcon(ic)
            b.setStyleSheet(b.property('style_propre') or "")

    # ── place ──

    def poser_dans(self, hote: QBoxLayout) -> None:
        """La barre en tête du layout hôte, dont le sens dira la place
        (le reste de la vue est l'autre élément de ce layout)."""
        self._hote = hote
        self.placer(self.position, memoriser=False)

    def menu_placement(self) -> QMenu:
        menu = QMenu(self)
        for p in POSITIONS:
            a = menu.addAction(f"Barre d'outils {NOMS[p].lower()}")
            a.setCheckable(True)
            a.setChecked(p == self.position)
            a.triggered.connect(lambda _c=False, q=p: self.placer(q))
        menu.addSeparator()
        a = menu.addAction("Noms sous les icônes")
        a.setCheckable(True)
        a.setChecked(self.noms)
        a.toggled.connect(self.bouton_noms.setChecked)
        return menu

    def afficher_noms(self, oui: bool) -> None:
        """Les noms sous les icônes (oui) ou les icônes seules."""
        oui = bool(oui)
        self.noms = oui
        self._lay.noms = oui
        if self.bouton_noms.isChecked() != oui:
            self.bouton_noms.blockSignals(True)
            self.bouton_noms.setChecked(oui)
            self.bouton_noms.blockSignals(False)
        try:
            _reglages().setValue(self.cle + "_noms", oui)
        except Exception:
            pass
        self._lay.invalidate()
        self.ajuster()

    def vertical(self) -> bool:
        return self.position in ('gauche', 'droite')

    def placer(self, position: str, memoriser: bool = True) -> None:
        if position not in POSITIONS:
            return
        self.position = position
        vertical = self.vertical()
        self._lay.vertical = vertical
        self._maj_larges()
        for trait in self._contenu.findChildren(QFrame):
            if not _est_trait(trait):
                continue
            if vertical:
                trait.setFrameShape(QFrame.Shape.HLine)
                trait.setMinimumWidth(0)
                trait.setMaximumWidth(16777215)
                trait.setFixedHeight(1)
            else:
                trait.setFrameShape(QFrame.Shape.VLine)
                trait.setMinimumHeight(0)
                trait.setMaximumHeight(16777215)
                trait.setFixedWidth(1)
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded if vertical
            else Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff if vertical
            else Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        if vertical:
            self.setSizePolicy(QSizePolicy.Policy.Fixed,
                               QSizePolicy.Policy.Ignored)
        else:
            self.setSizePolicy(QSizePolicy.Policy.Ignored,
                               QSizePolicy.Policy.Fixed)
        if self._hote is not None:
            self._hote.setDirection(_SENS_HOTE[position])
        self._lay.invalidate()
        self.ajuster()
        if memoriser:
            try:
                _reglages().setValue(self.cle, position)
            except Exception:
                pass
        self.position_changee.emit(position)

    def _vue(self) -> Optional[QWidget]:
        return self.parentWidget()

    def _place(self) -> QSize:
        """La place que la vue donne à la barre: toute sa largeur (en
        ligne) ou toute sa hauteur (en colonne), marges du layout hôte
        ôtées. Lue sur la vue: la taille de la barre a un temps de
        retard quand elle vient de changer de côté."""
        vue = self._vue()
        if vue is None or vue.width() < 50:
            return QSize(max(self.width(), 800), max(self.height(), 600))
        m = (self._hote.contentsMargins() if self._hote is not None
             else vue.contentsMargins())
        return QSize(vue.width() - m.left() - m.right(),
                     vue.height() - m.top() - m.bottom())

    def ajuster(self) -> None:
        """La barre prend l'épaisseur de ses lignes (ou colonnes) de
        boutons pour la largeur (la hauteur) qu'elle a; au-delà de la
        moitié de la vue, elle défile."""
        self._ajustement_prevu = False
        place = self._place()
        if self.vertical():
            besoin = self._lay.largeur_pour_hauteur(place.height())
            plafond = int(place.width() * self.PART_MAX)
            largeur = max(36, min(besoin, plafond))
            if largeur < besoin:
                largeur += self.horizontalScrollBar().sizeHint().height()
            self.setMinimumHeight(0)
            self.setMaximumHeight(16777215)
            if self.minimumWidth() != largeur or self.maximumWidth() != largeur:
                self.setFixedWidth(largeur)
        else:
            besoin = self._lay.heightForWidth(place.width())
            plafond = int(place.height() * self.PART_MAX)
            hauteur = max(32, min(besoin, plafond))
            self.setMinimumWidth(0)
            self.setMaximumWidth(16777215)
            if self.minimumHeight() != hauteur or self.maximumHeight() != hauteur:
                self.setFixedHeight(hauteur)

    def _ajuster_plus_tard(self) -> None:
        if not self._ajustement_prevu:
            self._ajustement_prevu = True
            QTimer.singleShot(0, self.ajuster)

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        avant, apres = ev.oldSize(), ev.size()
        if self.vertical():
            change = avant.height() != apres.height()
        else:
            change = avant.width() != apres.width()
        if change:
            self._ajuster_plus_tard()


def installer(vue: QWidget, hote: QBoxLayout, barre: BarreOutils,
              contenu: QWidget) -> None:
    """La barre et le reste de la vue dans le layout hôte (vide)."""
    hote.addWidget(barre)
    hote.addWidget(contenu, 1)
    barre.poser_dans(hote)
