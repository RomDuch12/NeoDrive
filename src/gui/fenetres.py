"""Les onglets en fenêtres, sur plusieurs écrans, et les dispositions.

Tout onglet des trois colonnes peut sortir en fenêtre: on le tire hors
de sa barre d'onglets, ou clic droit « Sortir en fenêtre ». La fenêtre
va sur n'importe quel écran; la fermer (ou « ↩ Remettre ») rend l'onglet
à sa colonne, à sa place.

Octobre 2026 (RomDuch): tout onglet se DÉPLACE aussi dans n'importe
quelle colonne — clic droit « Déplacer vers la colonne N », ou on le
tire sur la barre d'onglets d'une autre colonne. La disposition par
défaut reste celle d'origine; les places choisies sont retenues.

Une DISPOSITION, c'est tout cela photographié: la fenêtre principale
(écran, place, plein écran), les largeurs des colonnes, l'onglet actif
de chaque colonne, et chaque onglet sorti avec son écran et sa place.
On l'enregistre sous un nom (« atelier 1 écran », « bureau 2 écrans »);
la dernière est rouverte au démarrage. Un écran débranché depuis: ses
fenêtres reviennent sur un écran présent.
"""

import re
from typing import Dict, List, Optional

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout, QInputDialog, QLabel, QLayout, QMenu, QMessageBox,
    QPushButton, QTabWidget, QVBoxLayout, QWidget
)

#: les réglages: les dispositions nommées, la dernière employée
CLE_DISPOSITIONS = 'dispositions_fenetres'
CLE_DERNIERE = 'disposition_courante'
#: la disposition de la dernière fermeture (rouverte si aucune nommée)
NOM_AUTO = "(dernière fermeture)"
#: l'onglet « CAD » des versions 0.23 à 0.25 (novembre 2026), qui
#: portait le Canva 2D et le Canva 3D comme deux pages: ils sont redevenus
#: deux onglets (RomDuch, 09/11: « rétablir distinction onglets 2d-3d »).
#: Une disposition enregistrée avec lui rend sa place et sa fenêtre au
#: Canva 2D, et met le Canva 3D juste après.
CLE_CAD = 'c3:cad'
CLE_2D = 'c3:canva_2d'
CLE_3D = 'c3:canva_3d'


def traduire_disposition(etat: dict) -> dict:
    """Une disposition enregistrée avec l'onglet CAD, aux onglets
    d'aujourd'hui (le Canva 2D à sa place, le Canva 3D juste derrière, les
    suivants de la colonne décalés d'un rang). Une clé d'aujourd'hui déjà
    là l'emporte; une disposition sans CAD revient telle quelle."""
    if not isinstance(etat, dict):
        return etat
    etat = dict(etat)
    places = etat.get('places')
    if isinstance(places, dict) and CLE_CAD in places:
        places = dict(places)
        v = places.pop(CLE_CAD)
        try:
            col, rang = int(v[0]), int(v[1])
        except (TypeError, ValueError, IndexError):
            col = rang = None
        if col is not None and CLE_2D not in places:
            avec_3d = CLE_3D not in places
            if avec_3d:
                for k, p in list(places.items()):
                    try:
                        if int(p[0]) == col and int(p[1]) > rang:
                            places[k] = [col, int(p[1]) + 1]
                    except (TypeError, ValueError, IndexError):
                        continue
                places[CLE_3D] = [col, rang + 1]
            places[CLE_2D] = [col, rang]
        etat['places'] = places
    sortis = etat.get('sortis')
    if isinstance(sortis, list):
        neufs, vus = [], set()
        for x in sortis:
            if not isinstance(x, dict):
                continue
            cle = CLE_2D if x.get('cle') == CLE_CAD else x.get('cle')
            if cle in vus:
                continue
            vus.add(cle)
            neufs.append(dict(x, cle=cle))
        etat['sortis'] = neufs
    actifs = etat.get('onglets')
    if isinstance(actifs, dict):
        etat['onglets'] = {c: (CLE_2D if k == CLE_CAD else k)
                           for c, k in actifs.items()}
    return etat


def indices_d_avant_cad(indices, colonnes, vue_2d, vue_3d,
                        en_3d: bool) -> list:
    """L'onglet actif de chaque colonne, retenu par un onglet de programme
    au temps de l'onglet CAD (un rang de moins là où il était): le rang
    d'aujourd'hui. `colonnes`: les QTabWidget; la colonne où le Canva 3D
    suit le Canva 2D est celle du CAD; `en_3d`: la page qu'il montrait."""
    sortie = []
    for tabs, i in zip(colonnes, indices or []):
        try:
            i = int(i)
        except (TypeError, ValueError):
            sortie.append(i)
            continue
        k = tabs.indexOf(vue_2d)
        if k >= 0 and tabs.indexOf(vue_3d) == k + 1:
            if i > k or (i == k and en_3d):
                i += 1
        sortie.append(i)
    return sortie


def _slug(texte: str) -> str:
    import unicodedata
    t = unicodedata.normalize('NFKD', str(texte or ''))
    t = t.encode('ascii', 'ignore').decode('ascii').lower()
    return re.sub(r'[^a-z0-9]+', '_', t).strip('_') or "onglet"


class FenetreOnglet(QWidget):
    """Une fenêtre qui porte un onglet sorti de sa colonne."""

    #: la fenêtre se ferme: l'onglet rentre
    rentrer = Signal(object)

    def __init__(self, cle: str, titre: str, icone, colonne: int,
                 parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.cle = cle
        self.widget_porte = None
        self._fermeture_voulue = False
        self.setWindowTitle(f"NeoDrive — {titre}")
        if icone is not None and not icone.isNull():
            self.setWindowIcon(icone)
        v = QVBoxLayout(self)
        v.setContentsMargins(2, 2, 2, 2)
        v.setSpacing(2)
        # la fenêtre se règle librement: le minimum d'une barre d'outils
        # (le Canva 3D: 1100 px) ne l'impose pas à l'écran d'à côté
        v.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        barre = QHBoxLayout()
        etiquette = QLabel(titre)
        etiquette.setStyleSheet("color: #89b4fa; font-weight: bold;")
        barre.addWidget(etiquette)
        barre.addStretch()
        self.remettre_btn = QPushButton(f"↩ Remettre en colonne {colonne}")
        self.remettre_btn.setToolTip("Rendre cet onglet à sa colonne (ou "
                                     "fermer la fenêtre)")
        self.remettre_btn.setMaximumHeight(22)
        self.remettre_btn.clicked.connect(self.close)
        barre.addWidget(self.remettre_btn)
        v.addLayout(barre)
        self._disposition = v

    def porter(self, widget: QWidget) -> None:
        self.widget_porte = widget
        self._disposition.addWidget(widget, 1)
        widget.show()

    def lacher(self) -> Optional[QWidget]:
        w, self.widget_porte = self.widget_porte, None
        if w is not None:
            self._disposition.removeWidget(w)
        return w

    def closeEvent(self, event):
        self.rentrer.emit(self)
        super().closeEvent(event)


class GestionnaireOnglets(QObject):
    """Sortir, remettre, retrouver les onglets des colonnes; photographier
    et rendre les dispositions."""

    #: un onglet est sorti ou rentré (sa clé)
    change = Signal(str)

    def __init__(self, fenetre, colonnes: List[QTabWidget],
                 non_detachables=(), splitter=None):
        super().__init__(fenetre)
        self.fenetre = fenetre
        self.colonnes = list(colonnes)
        self.splitter = splitter
        self._non = set(id(w) for w in non_detachables)
        #: clé → {'widget', 'colonne', 'index', 'texte', 'icone',
        #: 'bulle', 'couleur'}
        self.onglets: Dict[str, dict] = {}
        #: clé → FenetreOnglet des onglets sortis
        self.fenetres: Dict[str, FenetreOnglet] = {}
        self._appui = None
        for c, tabs in enumerate(self.colonnes):
            for i in range(tabs.count()):
                w = tabs.widget(i)
                texte = tabs.tabText(i) or tabs.tabToolTip(i) or \
                    type(w).__name__
                cle = f"c{c + 1}:{_slug(texte)}"
                k = 2
                while cle in self.onglets:
                    cle = f"c{c + 1}:{_slug(texte)}_{k}"
                    k += 1
                self.onglets[cle] = {
                    'widget': w, 'colonne': c, 'index': i,
                    'texte': tabs.tabText(i), 'icone': tabs.tabIcon(i),
                    'bulle': tabs.tabToolTip(i),
                    'couleur': tabs.tabBar().tabTextColor(i)}
            barre = tabs.tabBar()
            barre.installEventFilter(self)
            barre.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            barre.customContextMenuRequested.connect(
                lambda pos, t=tabs: self._menu_onglet(t, pos))

    # ──── qui est où ────

    def cle_de(self, widget) -> Optional[str]:
        return next((k for k, o in self.onglets.items()
                     if o['widget'] is widget), None)

    def detachable(self, widget) -> bool:
        return widget is not None and id(widget) not in self._non and \
            self.cle_de(widget) is not None

    def est_detache(self, widget) -> bool:
        return self.cle_de(widget) in self.fenetres

    def fenetre_de(self, widget) -> Optional[FenetreOnglet]:
        return self.fenetres.get(self.cle_de(widget))

    def colonne_de(self, widget) -> int:
        """La colonne (0, 1, 2) où l'onglet vit (ou rentrera), -1."""
        cle = self.cle_de(widget)
        return self.onglets[cle]['colonne'] if cle else -1

    def deplacable(self, widget) -> bool:
        # l'onglet Paramètres (un lanceur, pas une page) reste où il est
        return (widget is not None and id(widget) not in self._non
                and self.cle_de(widget) is not None)

    def ajouter(self, widget, texte: str, colonne: int, rang: int = None,
                bulle: str = "", cle: str = None) -> str:
        """Un onglet de plus (créé après coup: le formulaire d'opé mis à
        part), dans une colonne; rend sa clé."""
        tabs = self.colonnes[colonne]
        rang = tabs.count() if rang is None else max(0, min(rang,
                                                           tabs.count()))
        if cle is None or cle in self.onglets:
            cle = f"c{colonne + 1}:{_slug(texte)}"
            k = 2
            while cle in self.onglets:
                cle = f"c{colonne + 1}:{_slug(texte)}_{k}"
                k += 1
        i = tabs.insertTab(rang, widget, texte)
        if bulle:
            tabs.setTabToolTip(i, bulle)
        self.onglets[cle] = {'widget': widget, 'colonne': colonne,
                             'index': rang, 'texte': texte,
                             'icone': tabs.tabIcon(i), 'bulle': bulle,
                             'couleur': None}
        self._renumeroter()
        tabs.setCurrentIndex(i)
        self.change.emit(cle)
        return cle

    def retirer(self, widget) -> None:
        """L'onglet n'est plus géré (le formulaire rentre sous la liste)."""
        cle = self.cle_de(widget)
        if cle is None:
            return
        if cle in self.fenetres:
            self.rattacher(widget)
        tabs = self.colonnes[self.onglets[cle]['colonne']]
        i = tabs.indexOf(widget)
        if i >= 0:
            tabs.removeTab(i)
        del self.onglets[cle]
        self._renumeroter()
        self.change.emit(cle)

    def _renumeroter(self) -> None:
        """Le rang de chaque onglet présent, dans l'ordre de sa barre
        (un onglet sorti garde le sien)."""
        for c, tabs in enumerate(self.colonnes):
            for i in range(tabs.count()):
                cle = self.cle_de(tabs.widget(i))
                if cle is not None:
                    self.onglets[cle]['colonne'] = c
                    self.onglets[cle]['index'] = i

    def deplacer(self, widget, colonne: int, rang: int = None) -> bool:
        """L'onglet dans une autre colonne (à `rang`, sinon au bout);
        sorti en fenêtre, il y rentrera."""
        cle = self.cle_de(widget)
        if cle is None or not (0 <= colonne < len(self.colonnes)):
            return False
        o = self.onglets[cle]
        if cle in self.fenetres:
            o['colonne'] = colonne
            o['index'] = (self.colonnes[colonne].count() if rang is None
                          else rang)
            self.fenetres[cle].remettre_btn.setText(
                f"↩ Remettre en colonne {colonne + 1}")
            self.change.emit(cle)
            return True
        depart = self.colonnes[o['colonne']]
        i = depart.indexOf(widget)
        if i >= 0:
            depart.removeTab(i)
        tabs = self.colonnes[colonne]
        rang = tabs.count() if rang is None else max(0, min(rang,
                                                           tabs.count()))
        j = tabs.insertTab(rang, widget, o['icone'], o['texte'])
        if o['bulle']:
            tabs.setTabToolTip(j, o['bulle'])
        if o['couleur'] is not None and o['couleur'].isValid():
            tabs.tabBar().setTabTextColor(j, o['couleur'])
        tabs.setCurrentIndex(j)
        self._renumeroter()
        self.change.emit(cle)
        return True

    def places(self) -> Dict[str, list]:
        """{clé: [colonne, rang]} de chaque onglet."""
        return {k: [o['colonne'], o['index']] for k, o in self.onglets.items()}

    def appliquer_places(self, places: dict) -> None:
        """Chaque onglet dans sa colonne retenue, dans l'ordre des rangs."""
        if not isinstance(places, dict):
            return
        places = traduire_disposition({'places': places})['places']
        voulues = sorted(((int(v[0]), int(v[1]), k) for k, v in
                          places.items() if k in self.onglets
                          and isinstance(v, (list, tuple)) and len(v) == 2),
                         key=lambda t: (t[0], t[1]))
        for colonne, rang, cle in voulues:
            if not (0 <= colonne < len(self.colonnes)):
                continue
            w = self.onglets[cle]['widget']
            if self.onglets[cle]['colonne'] != colonne or \
                    self.colonnes[colonne].indexOf(w) != rang:
                self.deplacer(w, colonne, rang)

    def montrer(self, widget) -> None:
        """Fait voir un onglet: sa fenêtre devant s'il est sorti, sinon
        l'onglet de sa colonne."""
        f = self.fenetre_de(widget)
        if f is not None:
            f.show()
            f.raise_()
            f.activateWindow()
            return
        cle = self.cle_de(widget)
        if cle is not None:
            self.colonnes[self.onglets[cle]['colonne']].setCurrentWidget(
                widget)

    def visible(self, widget) -> bool:
        """L'onglet se voit: sorti, ou actif dans sa colonne."""
        if self.est_detache(widget):
            return True
        cle = self.cle_de(widget)
        return cle is not None and self.colonnes[
            self.onglets[cle]['colonne']].currentWidget() is widget

    # ──── sortir, remettre ────

    def detacher(self, widget, geometrie: QRect = None,
                 maximisee: bool = False) -> Optional[FenetreOnglet]:
        """Sort l'onglet en fenêtre (à `geometrie`, sinon sous la
        souris)."""
        if not self.detachable(widget) or self.est_detache(widget):
            return self.fenetre_de(widget)
        cle = self.cle_de(widget)
        o = self.onglets[cle]
        tabs = self.colonnes[o['colonne']]
        i = tabs.indexOf(widget)
        taille = widget.size()
        if i >= 0:
            tabs.removeTab(i)
        f = FenetreOnglet(cle, o['texte'] or o['bulle'] or cle, o['icone'],
                          o['colonne'] + 1)
        # son icône (le logo + le badge de l'onglet) et, sous Windows,
        # son propre bouton dans la barre des tâches
        try:
            from src.gui.icones_fenetres import habiller
            habiller(f, cle, o['texte'] or o['bulle'] or cle)
        except Exception:
            pass
        f.porter(widget)
        f.rentrer.connect(lambda fen: self.rattacher(fen.widget_porte))
        self.fenetres[cle] = f
        if geometrie is None:
            l, h = max(500, taille.width()), max(400, taille.height())
            pos = QCursor.pos() - QPoint(l // 2, 15)
            geometrie = QRect(pos.x(), pos.y(), l, h)
        f.setGeometry(ramener_sur_un_ecran(geometrie))
        if maximisee:
            f.showMaximized()
        else:
            f.show()
        f.raise_()
        self.change.emit(cle)
        return f

    def rattacher(self, widget) -> None:
        """Rend l'onglet à sa colonne, à sa place."""
        cle = self.cle_de(widget)
        f = self.fenetres.pop(cle, None) if cle else None
        if f is None:
            return
        f.lacher()
        o = self.onglets[cle]
        tabs = self.colonnes[o['colonne']]
        # sa place: après les onglets qui le précédaient et sont là
        rang = sum(1 for k, x in self.onglets.items()
                   if x['colonne'] == o['colonne'] and x['index'] < o['index']
                   and k not in self.fenetres)
        i = tabs.insertTab(rang, widget, o['icone'], o['texte'])
        if o['bulle']:
            tabs.setTabToolTip(i, o['bulle'])
        if o['couleur'] is not None and o['couleur'].isValid():
            tabs.tabBar().setTabTextColor(i, o['couleur'])
        tabs.setCurrentIndex(i)
        f.rentrer.disconnect()
        f.hide()
        f.deleteLater()
        self.change.emit(cle)

    def tout_rattacher(self) -> None:
        for cle in list(self.fenetres):
            self.rattacher(self.onglets[cle]['widget'])

    # ──── la souris: tirer un onglet hors de sa barre, clic droit ────

    def eventFilter(self, objet, event):
        t = event.type()
        if t == QEvent.Type.MouseButtonPress and \
                event.button() == Qt.MouseButton.LeftButton:
            # l'onglet SOUS LE CLIC, retenu tout de suite: le clic le
            # choisit, la barre se redispose, et la même position désigne
            # ensuite son voisin
            pos = event.position().toPoint()
            tabs = next((x for x in self.colonnes if x.tabBar() is objet),
                        None)
            i = objet.tabAt(pos)
            w = tabs.widget(i) if tabs is not None and i >= 0 else None
            self._appui = (objet, pos, w)
        elif t == QEvent.Type.MouseButtonRelease:
            self._appui = None
        elif t == QEvent.Type.MouseMove and self._appui is not None \
                and self._appui[0] is objet and \
                event.buttons() & Qt.MouseButton.LeftButton:
            depart = self._appui[1]
            pos = event.position().toPoint()
            # tiré sur la barre d'onglets d'une AUTRE colonne: il y passe
            glob = objet.mapToGlobal(pos)
            for c, autre in enumerate(self.colonnes):
                barre = autre.tabBar()
                if barre is objet or not barre.isVisible():
                    continue
                local = barre.mapFromGlobal(glob)
                zone = barre.rect().adjusted(0, -12, 0, 12)
                if zone.contains(local):
                    w = self._appui[2]
                    self._appui = None
                    if w is not None and self.deplacable(w):
                        rang = barre.tabAt(local)
                        self.deplacer(w, c, None if rang < 0 else rang)
                        return True
                    return False
            # tiré nettement hors de la barre (vers le haut ou le bas)
            if abs(pos.y() - depart.y()) > max(40, objet.height() * 1.5):
                w = self._appui[2]
                self._appui = None
                if w is not None and self.detachable(w):
                    self.detacher(w)
                    return True
        return super().eventFilter(objet, event)

    def menu_onglet(self, tabs: QTabWidget, index: int) -> QMenu:
        """Le menu du clic droit sur un onglet (rendu pour les tests)."""
        menu = QMenu(tabs)
        w = tabs.widget(index) if index >= 0 else None
        if w is not None and self.deplacable(w):
            ici = self.colonne_de(w)
            for c in range(len(self.colonnes)):
                if c != ici:
                    menu.addAction(f"Déplacer vers la colonne {c + 1}"
                                   ).triggered.connect(
                        lambda _c=False, cc=c: self.deplacer(w, cc))
        if w is not None and self.detachable(w):
            menu.addAction(f"Sortir « {tabs.tabText(index) or 'cet onglet'} »"
                           " en fenêtre").triggered.connect(
                lambda: self.detacher(w))
        if self.fenetres:
            menu.addAction("Remettre tous les onglets en place"
                           ).triggered.connect(self.tout_rattacher)
        if callable(self.menu_extra) and w is not None:
            self.menu_extra(menu, w)
        menu.addSeparator()
        self.remplir_menu_dispositions(menu.addMenu("Dispositions"))
        return menu

    def _menu_onglet(self, tabs, pos) -> None:
        menu = self.menu_onglet(tabs, tabs.tabBar().tabAt(pos))
        menu.exec(tabs.tabBar().mapToGlobal(pos))

    # ──── les dispositions ────

    def photo(self) -> dict:
        """La disposition en cours."""
        f = self.fenetre
        etat = {'fenetre': _geo(f), 'maximisee': bool(f.isMaximized()),
                'ecran': _ecran(f), 'colonnes': [], 'onglets': {},
                'sortis': []}
        if self.splitter is not None:
            etat['colonnes'] = [int(v) for v in self.splitter.sizes()]
        for c, tabs in enumerate(self.colonnes):
            cle = self.cle_de(tabs.currentWidget())
            if cle:
                etat['onglets'][str(c)] = cle
        for cle, fen in self.fenetres.items():
            etat['sortis'].append({'cle': cle, 'geo': _geo(fen),
                                   'ecran': _ecran(fen),
                                   'maximisee': bool(fen.isMaximized())})
        etat['places'] = self.places()
        return etat

    def appliquer(self, etat: dict, fenetre: bool = True) -> None:
        """Rend une disposition: les onglets sortis à leur place (un
        écran absent: sur un écran présent), les autres rentrés.
        `fenetre`: la fenêtre principale aussi — sa place, ses colonnes,
        l'onglet actif de chacune (au démarrage, elle a déjà repris les
        siennes: seules les fenêtres d'onglets sortis reviennent)."""
        if not isinstance(etat, dict):
            return
        etat = traduire_disposition(etat)
        # les colonnes de chaque onglet d'abord (même au démarrage: ce
        # n'est pas la géométrie de la fenêtre)
        self.appliquer_places(etat.get('places'))
        voulus = {s.get('cle'): s for s in etat.get('sortis') or []
                  if s.get('cle') in self.onglets}
        for cle in list(self.fenetres):
            if cle not in voulus:
                self.rattacher(self.onglets[cle]['widget'])
        f = self.fenetre
        geo = _rect(etat.get('fenetre')) if fenetre else None
        if geo is not None:
            if f.isMaximized():
                f.showNormal()
            f.setGeometry(ramener_sur_un_ecran(geo, etat.get('ecran')))
        if fenetre and etat.get('maximisee'):
            f.showMaximized()
        larg = etat.get('colonnes') if fenetre else None
        if self.splitter is not None and isinstance(larg, list) and \
                len(larg) == self.splitter.count() and sum(larg) > 0:
            self.splitter.setSizes([int(v) for v in larg])
        for cle, s in voulus.items():
            w = self.onglets[cle]['widget']
            g = ramener_sur_un_ecran(_rect(s.get('geo')) or QRect(
                100, 100, 600, 500), s.get('ecran'))
            fen = self.fenetre_de(w)
            if fen is None:
                self.detacher(w, g, bool(s.get('maximisee')))
            else:
                fen.setGeometry(g)
                if s.get('maximisee'):
                    fen.showMaximized()
        for c, cle in ((etat.get('onglets') or {}) if fenetre
                       else {}).items():
            o = self.onglets.get(cle)
            try:
                tabs = self.colonnes[int(c)]
            except (ValueError, IndexError):
                continue
            if o is not None and not self.est_detache(o['widget']):
                tabs.setCurrentWidget(o['widget'])

    #: (menu, widget) -> None: des actions de plus au clic droit d'un
    #: onglet (le formulaire d'opé: à part / sous la liste)
    menu_extra = None

    # les dispositions nommées vivent dans les réglages de l'application
    lire_reglages = None          # () -> dict
    ecrire_reglages = None        # () -> None

    def _reglages(self) -> dict:
        return self.lire_reglages() if callable(self.lire_reglages) else {}

    def dispositions(self) -> Dict[str, dict]:
        d = self._reglages().get(CLE_DISPOSITIONS)
        return d if isinstance(d, dict) else {}

    def enregistrer(self, nom: str) -> None:
        r = self._reglages()
        tout = dict(self.dispositions())
        tout[nom] = self.photo()
        r[CLE_DISPOSITIONS] = tout
        if nom != NOM_AUTO:
            r[CLE_DERNIERE] = nom
        if callable(self.ecrire_reglages):
            self.ecrire_reglages()

    def ouvrir(self, nom: str, fenetre: bool = True) -> bool:
        etat = self.dispositions().get(nom)
        if etat is None:
            return False
        self.appliquer(etat, fenetre)
        if nom != NOM_AUTO:
            self._reglages()[CLE_DERNIERE] = nom
            if callable(self.ecrire_reglages):
                self.ecrire_reglages()
        return True

    def supprimer(self, nom: str) -> None:
        r = self._reglages()
        tout = dict(self.dispositions())
        tout.pop(nom, None)
        r[CLE_DISPOSITIONS] = tout
        if r.get(CLE_DERNIERE) == nom:
            r.pop(CLE_DERNIERE, None)
        if callable(self.ecrire_reglages):
            self.ecrire_reglages()

    def au_demarrage(self) -> Optional[str]:
        """Rouvre la dernière disposition nommée, sinon celle de la
        dernière fermeture; rend son nom."""
        # la fenêtre principale a déjà repris sa place (window_geometry)
        nom = self._reglages().get(CLE_DERNIERE)
        if nom and self.ouvrir(nom, fenetre=False):
            return nom
        if self.ouvrir(NOM_AUTO, fenetre=False):
            return NOM_AUTO
        return None

    def a_la_fermeture(self) -> None:
        self.enregistrer(NOM_AUTO)

    #: pour les tests: le nom à donner sans demander
    nom_demande = None

    def _enregistrer_sous(self) -> Optional[str]:
        nom = self.nom_demande
        if nom is None:
            nom, ok = QInputDialog.getText(
                self.fenetre, "Enregistrer la disposition",
                "Nom de la disposition (ex. « atelier 1 écran », « bureau 2 "
                "écrans »):",
                text=self._reglages().get(CLE_DERNIERE, "") or "")
            if not ok:
                return None
        nom = str(nom).strip()
        if not nom or nom == NOM_AUTO:
            return None
        self.enregistrer(nom)
        return nom

    def remplir_menu_dispositions(self, menu: QMenu) -> QMenu:
        menu.addAction("Enregistrer la disposition sous…").triggered.connect(
            self._enregistrer_sous)
        noms = sorted(n for n in self.dispositions() if n != NOM_AUTO)
        courante = self._reglages().get(CLE_DERNIERE)
        if noms:
            menu.addSeparator()
            for nom in noms:
                a = menu.addAction(("✓ " if nom == courante else "   ") + nom)
                a.triggered.connect(lambda _=False, n=nom: self.ouvrir(n))
            sup = QMenu("Supprimer", menu)
            menu.addMenu(sup)
            for nom in noms:
                sup.addAction(nom).triggered.connect(
                    lambda _=False, n=nom: self._supprimer_demande(n))
        menu.addSeparator()
        menu.addAction("Tout remettre dans les colonnes").triggered.connect(
            self.tout_rattacher)
        return menu

    def _supprimer_demande(self, nom: str) -> None:
        rep = QMessageBox.question(self.fenetre, "Dispositions",
                                   f"Supprimer la disposition « {nom} » ?")
        if rep == QMessageBox.StandardButton.Yes:
            self.supprimer(nom)


# ──── écrans ────

def _geo(w) -> List[int]:
    g = w.normalGeometry() if w.isMaximized() else w.geometry()
    return [g.x(), g.y(), g.width(), g.height()]


def _rect(v) -> Optional[QRect]:
    try:
        x, y, l, h = (int(a) for a in v)
        return QRect(x, y, max(200, l), max(150, h))
    except (TypeError, ValueError):
        return None


def _ecran(w) -> str:
    e = w.screen() if hasattr(w, 'screen') else None
    return e.name() if e is not None else ""


def ramener_sur_un_ecran(geo: QRect, nom_ecran: str = None) -> QRect:
    """La place d'une fenêtre, sur un écran présent: celui qu'elle avait
    s'il est branché, sinon celui qu'elle chevauche le plus, sinon
    l'écran principal — et entière dedans."""
    ecrans = QGuiApplication.screens()
    if not ecrans:
        return geo
    zones = {e.name(): e.availableGeometry() for e in ecrans}
    zone = None
    for e in ecrans:
        if e.availableGeometry().intersects(geo):
            inter = e.availableGeometry().intersected(geo)
            if zone is None or inter.width() * inter.height() > \
                    zone[1].width() * zone[1].height():
                zone = (e.availableGeometry(), inter)
    if zone is not None:
        cadre = zone[0]
    elif nom_ecran in zones:
        cadre = zones[nom_ecran]
    else:
        cadre = QGuiApplication.primaryScreen().availableGeometry()
    l = min(geo.width(), cadre.width())
    h = min(geo.height(), cadre.height())
    x = min(max(geo.x(), cadre.x()), cadre.x() + cadre.width() - l)
    y = min(max(geo.y(), cadre.y()), cadre.y() + cadre.height() - h)
    return QRect(x, y, l, h)
