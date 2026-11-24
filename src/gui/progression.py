# -*- coding: utf-8 -*-
"""La progression dans la barre d'état, avec un bouton Annuler qui
agit — et, sans fenêtre principale, une fenêtre de progression.

Tout calcul qui peut durer passe par ici: parcours de gravure, gamme
entière, export du programme, lecture d'un lot de fichiers. La règle
est simple — pas de curseur d'attente muet. L'opérateur voit où en
est le calcul, et peut l'arrêter.

Le noyau (vcarve, gamme) ne connaît pas Qt: il reçoit un appelable
`(fraction, texte) -> bool` et lève `vcarve.Annule` quand celui-ci
rend False. Cette fenêtre EST cet appelable.

    with Progression(self, "Calcul du parcours") as barre:
        plan = classe.plan(params, progression=barre)
    if barre.annule:
        ...   # rien n'a été gardé

Le `with` ferme la fenêtre quoi qu'il arrive, et avale `Annule`:
l'annulation n'est pas une erreur, c'est une décision.

Depuis le round 105, la progression vit dans la BARRE D'ÉTAT de la
fenêtre principale (`ZoneProgression`): texte, barre, Annuler —
plus de fenêtre qui saute au milieu de l'écran. Le reste de la
fenêtre est gelé le temps du calcul. La fenêtre de progression ne
sert plus que sans fenêtre principale (scripts, tests).
"""

import threading
import time
from typing import Optional

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QProgressBar, QProgressDialog,
    QPushButton, QWidget
)

from src.core.vcarve import Annule

#: cadence de rafraîchissement de la fenêtre pendant qu'un fil
#: calcule, en secondes
CADENCE = 0.02

#: finesse de la barre: un millième suffit à l'œil
PLEIN = 1000


class ZoneProgression(QWidget):
    """La progression dans la barre d'état: le texte, la barre, le
    bouton Annuler. Cachée quand rien ne calcule."""

    def __init__(self, parent=None):
        super().__init__(parent)
        rangee = QHBoxLayout(self)
        rangee.setContentsMargins(6, 0, 6, 0)
        rangee.setSpacing(6)
        self._titre = QLabel("")
        self._titre.setStyleSheet("font-weight: bold;")
        rangee.addWidget(self._titre)
        self._texte = QLabel("")
        self._texte.setMinimumWidth(120)
        self._texte.setMaximumWidth(420)
        rangee.addWidget(self._texte)
        self._barre = QProgressBar()
        self._barre.setRange(0, PLEIN)
        self._barre.setValue(0)
        self._barre.setFixedWidth(180)
        self._barre.setMaximumHeight(16)
        self._barre.setTextVisible(True)
        self._barre.setFormat("%p %")
        rangee.addWidget(self._barre)
        self._bouton = QPushButton("Annuler")
        self._bouton.setMaximumHeight(22)
        self._bouton.setCursor(Qt.CursorShape.PointingHandCursor)
        self._bouton.clicked.connect(self.annuler)
        rangee.addWidget(self._bouton)
        #: vrai après un clic sur Annuler
        self.annule = False
        #: vrai entre `commencer` et `finir`
        self.occupee = False
        #: ce qu'on a gelé le temps du calcul
        self._gele = None
        self.hide()

    def commencer(self, titre: str, texte: str = "",
                  geler: bool = True) -> None:
        self.annule = False
        self.occupee = True
        self._titre.setText(titre)
        self._texte.setText(texte)
        self._barre.setValue(0)
        self._bouton.setEnabled(True)
        self.show()
        # Le reste de la fenêtre attend: cliquer dans la liste
        # pendant qu'un parcours se calcule changerait l'opération
        # sous le calcul. La barre d'état, elle, reste vivante —
        # c'est là qu'est Annuler. Une tâche de fond (lecture d'un
        # site) ne touche à rien de la fenêtre: elle ne gèle pas.
        if not geler:
            return
        fenetre = self.window()
        central = getattr(fenetre, 'centralWidget', lambda: None)()
        if central is not None and central.isEnabled():
            central.setEnabled(False)
            self._gele = central

    def rendre_compte(self, fraction: float, texte: str = "") -> None:
        self._barre.setValue(int(max(0.0, min(1.0, fraction)) * PLEIN))
        if texte:
            self._texte.setText(texte)

    def annuler(self) -> None:
        """Ce que fait le clic sur Annuler."""
        self.annule = True
        self._bouton.setEnabled(False)
        self._texte.setText("arrêt demandé…")

    def finir(self) -> None:
        self.occupee = False
        if self._gele is not None:
            try:
                self._gele.setEnabled(True)
            except RuntimeError:
                pass
            self._gele = None
        self.hide()


def zone_de(parent) -> Optional[ZoneProgression]:
    """La zone de progression de la fenêtre principale de `parent`,
    si elle existe et n'est pas déjà prise."""
    if parent is None:
        return None
    try:
        fenetre = parent.window()
    except (AttributeError, RuntimeError):
        return None
    zone = getattr(fenetre, '_zone_progression', None)
    if isinstance(zone, ZoneProgression) and not zone.occupee:
        return zone
    return None


class Progression:
    """Progression + annulation, utilisable en `with`: dans la barre
    d'état de la fenêtre principale, ou dans une fenêtre à défaut."""

    def __init__(self, parent, titre: str, texte: str = "",
                 minimum_ms: int = 300):
        self._zone = zone_de(parent)
        self._boite = None
        if self._zone is not None:
            self._zone.commencer(titre, texte or "")
        else:
            self._boite = QProgressDialog(texte or titre, "Annuler",
                                          0, PLEIN, parent)
            self._boite.setWindowTitle(titre)
            self._boite.setWindowModality(Qt.WindowModality.WindowModal)
            # pas de clignotement sur un calcul court: la fenêtre
            # n'apparaît que si ça dure
            self._boite.setMinimumDuration(max(0, int(minimum_ms)))
            self._boite.setAutoClose(False)
            self._boite.setAutoReset(False)
            self._boite.setValue(0)
        #: vrai après un clic sur Annuler
        self.annule = False
        #: dernière fraction reçue (0 à 1)
        self.fraction = 0.0
        #: dernier texte reçu
        self.texte = texte
        #: le fil de l'interface: seul lui touche à la fenêtre
        self._fil_interface = threading.current_thread()
        #: posé par l'interface quand Annuler est cliqué; lu par le
        #: fil de travail à son prochain compte rendu
        self._arret_demande = False

    # ── le protocole du noyau ──

    def __call__(self, fraction: float, texte: str = "") -> bool:
        """Rend compte; False = l'utilisateur a demandé l'arrêt.

        Appelée depuis un fil de travail, elle ne fait que noter:
        la fenêtre appartient au fil de l'interface, qui la met à
        jour dans `executer`."""
        self.fraction = max(0.0, min(1.0, float(fraction)))
        if texte:
            self.texte = texte
        if threading.current_thread() is not self._fil_interface:
            return not self._arret_demande
        try:
            self._montrer(self.fraction, texte)
        except RuntimeError:            # fenêtre déjà détruite
            return not self.annule
        # Sans ça, le bouton Annuler ne reçoit jamais le clic: le
        # calcul tient la boucle d'événements.
        QApplication.processEvents()
        if self._arret_clique():
            self.annule = True
            self._arret_demande = True
            return False
        return True

    # ── la surface: zone de la barre d'état, ou fenêtre ──

    def _montrer(self, fraction: float, texte: str = "") -> None:
        if self._zone is not None:
            self._zone.rendre_compte(fraction, texte)
            return
        self._boite.setValue(int(fraction * PLEIN))
        if texte:
            self._boite.setLabelText(texte)

    def _arret_clique(self) -> bool:
        if self._zone is not None:
            return bool(self._zone.annule)
        return bool(self._boite.wasCanceled())

    def annuler(self) -> None:
        """Ce que fait la souris sur Annuler — pour les tests et les
        appelants qui veulent arrêter un calcul."""
        if self._zone is not None:
            self._zone.annuler()
        else:
            self._boite.cancel()

    def executer(self, travail):
        """Lance `travail(self)` dans un fil de travail.

        C'est ce qui empêche l'interface de geler: un `union_all` de
        GEOS ou un Voronoï de qhull peut tenir le processeur des
        dizaines de secondes sans jamais repasser par Python — sur le
        fil de l'interface, plus rien ne bouge, pas même Annuler.
        Ici la fenêtre vit sur le fil de l'interface, le calcul sur
        le sien; shapely et scipy relâchent le GIL pendant leurs
        appels C.

        Annuler agit dès le prochain compte rendu du calcul; en
        attendant la fenêtre se ferme et l'application répond. Rend
        le résultat du travail, ou None s'il a été annulé. Une
        erreur du travail est relevée ici, sur le fil de
        l'interface."""
        etat = {'resultat': None, 'erreur': None, 'fini': False,
                'annule': False}

        def _courir():
            try:
                etat['resultat'] = travail(self)
            except Annule:
                etat['annule'] = True
            except BaseException as exc:        # relevée plus bas
                etat['erreur'] = exc
            finally:
                etat['fini'] = True

        fil = threading.Thread(target=_courir, name="neodrive-calcul",
                               daemon=True)
        fil.start()
        derniere = (None, None)
        while not etat['fini']:
            courante = (self.fraction, self.texte)
            if courante != derniere:
                derniere = courante
                try:
                    self._montrer(self.fraction, self.texte)
                except RuntimeError:
                    pass
            QApplication.processEvents()
            try:
                if self._arret_clique() and not self._arret_demande:
                    self._arret_demande = True
                    self.annule = True
            except RuntimeError:
                pass
            if self._arret_demande:
                # la fenêtre se ferme tout de suite; le fil s'arrête
                # à son prochain compte rendu et son résultat est
                # jeté
                break
            time.sleep(CADENCE)
        # un clic sur Annuler juste avant la fin: le résultat est
        # jeté quand même, c'est ce qu'on a demandé
        try:
            if self._arret_clique():
                self._arret_demande = True
                self.annule = True
        except RuntimeError:
            pass
        if self._arret_demande:
            return None
        if etat['erreur'] is not None:
            raise etat['erreur']
        if etat['annule']:
            self.annule = True
            return None
        return etat['resultat']

    def sous(self, debut: float, fin: float, prefixe: str = ""):
        """La même fenêtre, sur une tranche de la barre."""
        from src.core.vcarve import sous_progression
        return sous_progression(self, debut, fin, prefixe)

    # ── contexte ──

    def __enter__(self) -> "Progression":
        return self

    def __exit__(self, genre, valeur, trace) -> bool:
        try:
            if self._zone is not None:
                self._zone.finir()
            else:
                self._boite.close()
                self._boite.deleteLater()
        except RuntimeError:
            pass
        if genre is not None and issubclass(genre, Annule):
            self.annule = True
            return True                 # avalée: c'est une décision
        return False


def preparer_parcours_fichiers(parent, chemins, diametres) -> None:
    """Les GROS programmes appelés (Appel prog externe), simulés
    d'avance dans la barre d'état — avec Annuler — avant que le Canva ou
    la 3D les dessinent. Sans ça, la simulation se faisait au milieu du
    dessin: un programme 3D de 30 Mo figeait la fenêtre plusieurs
    secondes, sans rien dire. Un calcul annulé n'est pas relancé
    d'office (le dessin s'en passe)."""
    import os
    from src.core import sim_cycles
    for chemin in dict.fromkeys(c for c in chemins if c):
        if not sim_cycles.parcours_a_preparer(chemin, diametres):
            continue
        if zone_de(parent) is None:
            return          # un calcul tient déjà la barre d'état
        nom = os.path.basename(chemin)
        res = travailler(parent, "Simulation du programme appelé",
                         lambda prog, c=chemin: sim_cycles.parcours_fichier(
                             c, diametres, progression=prog), nom)
        if res is None:
            # annulé: le parcours ne sera pas dessiné — le dire
            try:
                etiquette = getattr(parent.window(), '_status_label', None)
            except (AttributeError, RuntimeError):
                etiquette = None
            if etiquette is not None:
                etiquette.setText(
                    f"Simulation de {nom} annulée: son parcours n'est pas "
                    "dessiné (rouvrir le fichier pour la relancer)")


class TacheDeFond(QObject):
    """Un travail long qui laisse la fenêtre vivante — lire vingt
    minutes de webshop ne doit rien geler.

    Il court dans son fil; sa progression a SA zone dans la barre
    d'état (texte, barre, Annuler), à côté de celle des calculs, qui
    reste libre. `travail(progression)` reçoit l'appelable du noyau
    `(fraction, texte) -> bool` (False: Annuler a été cliqué, lever
    `vcarve.Annule`). À la fin, sur le fil de l'interface: `fini`
    (résultat, erreur ou None, annulé)."""

    fini = Signal(object, object, bool)
    #: (fraction, texte), relevés sur le fil de l'interface
    avance = Signal(float, str)

    #: cadence du relevé, en millisecondes
    CADENCE_MS = 200

    def __init__(self, parent, titre: str, travail, texte: str = ""):
        super().__init__(parent)
        self._travail = travail
        self._titre = titre
        self._etat = {'fraction': 0.0, 'texte': texte, 'fini': False,
                      'resultat': None, 'erreur': None}
        self._arret = False
        self.annule = False
        self.zone = None
        self._barre = None
        self._minuterie = QTimer(self)
        self._minuterie.setInterval(self.CADENCE_MS)
        self._minuterie.timeout.connect(self._relever)
        try:
            fenetre = parent.window() if parent is not None else None
            barre = fenetre.statusBar() if hasattr(
                fenetre, 'statusBar') else None
        except RuntimeError:
            barre = None
        if barre is not None:
            self._barre = barre
            self.zone = ZoneProgression(barre)
            barre.addPermanentWidget(self.zone)
            self.zone.commencer(titre, texte, geler=False)

    # ── le protocole du noyau (fil de travail) ──

    def __call__(self, fraction: float, texte: str = "") -> bool:
        self._etat['fraction'] = max(0.0, min(1.0, float(fraction)))
        if texte:
            self._etat['texte'] = texte
        return not self._arret

    def demarrer(self, synchrone: bool = False) -> None:
        """Lance le travail: dans son fil, ou ici (`synchrone`, pour les
        tests et les scripts)."""
        def courir():
            try:
                self._etat['resultat'] = self._travail(self)
            except Annule:
                self.annule = True
            except Exception as exc:        # rendu à l'interface
                self._etat['erreur'] = exc
            self._etat['fini'] = True
        if synchrone:
            courir()
            self._relever()
            return
        self._minuterie.start()
        threading.Thread(target=courir, name="neodrive-fond",
                         daemon=True).start()

    def annuler(self) -> None:
        """Ce que fait Annuler: le travail s'arrête à son prochain
        compte rendu."""
        self._arret = True
        if self.zone is not None:
            self.zone.annuler()

    @property
    def en_cours(self) -> bool:
        return not self._etat['fini']

    # ── le relevé (fil de l'interface) ──

    def _relever(self) -> None:
        etat = self._etat
        if self.zone is not None:
            try:
                if self.zone.annule:
                    self._arret = True
                self.zone.rendre_compte(etat['fraction'], etat['texte'])
            except RuntimeError:            # barre d'état détruite
                self.zone = None
        self.avance.emit(etat['fraction'], etat['texte'] or "")
        if not etat['fini']:
            return
        self._minuterie.stop()
        if self.zone is not None:
            try:
                self.zone.finir()
                if self._barre is not None:
                    self._barre.removeWidget(self.zone)
                self.zone.deleteLater()
            except RuntimeError:
                pass
            self.zone = None
        self.annule = self.annule or (self._arret and etat['erreur'] is None
                                      and etat['resultat'] is None)
        self.fini.emit(etat['resultat'], etat['erreur'], self.annule)


def travailler(parent, titre: str, travail, texte: str = "",
               minimum_ms: int = 300) -> Optional[object]:
    """Lance `travail(progression)` sous une fenêtre de progression.

    Rend ce que le travail rend, ou None s'il a été annulé. Les
    autres exceptions passent: elles sont des erreurs, à traiter par
    l'appelant."""
    with Progression(parent, titre, texte, minimum_ms) as barre:
        resultat = barre.executer(travail)
    return None if barre.annule else resultat
