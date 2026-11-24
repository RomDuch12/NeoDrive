"""La fiche d'un outil: toutes ses specs et son dessin, en 2D et en 3D.

Elle s'ouvre depuis le tableau des outils (n° de ligne, bouton
« Dessin ») ou depuis le catalogue DATRON — à la place des colonnes 1 et
2 quand le tableau est en colonne 3, dans le panneau lui-même sinon.

Le dessin suit la fiche: chaque retouche d'une cote le refait (DXF et
STEP d'aperçu, dans un dossier temporaire). « Enregistrer et fermer »
met à jour tools.json ET les dessins annexés (dossier « outils »)."""

import os
import tempfile
import threading

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QSplitter,
    QTextBrowser, QToolButton, QVBoxLayout, QWidget
)


def ouvrir_externe(chemin: str) -> bool:
    """Ouvre un fichier ou un dossier avec le programme du système."""
    return QDesktopServices.openUrl(QUrl.fromLocalFile(chemin))


class VuesDessin(QWidget):
    """Le dessin d'un outil: le DXF coté au-dessus, le STEP en 3D
    dessous."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from src.gui.dxf.dxf_canvas import DxfCanvas
        from src.gui.canvas3d import VueScene
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self._partage = QSplitter(Qt.Orientation.Vertical)
        self.canvas = DxfCanvas()
        self.canvas.setToolTip("Le DXF: la silhouette cotée (calque "
                               "PROFIL: le demi-profil, éteint)")
        self.canvas.installEventFilter(self)
        self.vue = VueScene()
        self.vue.setToolTip("Le STEP: le solide de révolution — en or, "
                            "ce qui coupe")
        self._partage.addWidget(self.canvas)
        self._partage.addWidget(self.vue)
        self._partage.setSizes([500, 500])
        v.addWidget(self._partage)
        # les tailles successives d'une ouverture (fiche montrée,
        # séparateurs réglés): un seul cadrage, après la dernière
        self._cadrage = QTimer(self)
        self._cadrage.setSingleShot(True)
        self._cadrage.setInterval(0)
        self._cadrage.timeout.connect(self.cadrer)

    def montrer(self, dxf: str = None, step: str = None) -> str:
        """Charge le DXF et le STEP; rend un message d'erreur ou ""."""
        from src.io.vecteur import step3d
        erreurs = []
        self.canvas.clear_dxf()
        self.vue.set_scene()
        if dxf:
            try:
                self.canvas.load_dxf(dxf)
            except Exception as exc:
                erreurs.append(f"DXF illisible: {exc}")
        if step:
            try:
                m = step3d.lire_modele(step)
                self.vue.set_scene(m.triangles, m.couleurs, m.aretes)
                self.vue.elevation = 15
                self.vue.update()
            except Exception as exc:
                erreurs.append(f"STEP illisible: {exc}")
        self.cadrer()
        return " · ".join(erreurs)

    def cadrer(self) -> None:
        self.canvas.fit_all()

    def eventFilter(self, objet, event):
        # le canvas change de taille (fiche montrée, séparateur tiré):
        # le dessin reste entier
        if objet is self.canvas and event.type() == QEvent.Type.Resize:
            self._cadrage.start()
        return super().eventFilter(objet, event)


class _Relais(QObject):
    """Les nouvelles du téléchargement (fil de travail → interface)."""
    etape = Signal(str, object)
    fini = Signal(object, str, object)


class GalerieDatron(QWidget):
    """Les photos de l'outil sur le webshop DATRON, comme sa fiche
    produit: les vignettes à gauche, la grande image, ‹ ›. Elles sont
    téléchargées une fois (en arrière-plan, Annuler arrête), puis lues
    dans « images_outils » à côté de tools.json."""

    _STYLE_BOUTON = (
        "QToolButton { background: #313244; border: 1px solid #45475a; "
        "border-radius: 3px; color: #cdd6f4; padding: 1px 6px; }"
        "QToolButton:hover { background: #45475a; }"
        "QToolButton:checked { border: 2px solid #89b4fa; }")

    def __init__(self, parent=None):
        super().__init__(parent)
        from src.gui.icons import get_button_icon
        #: la référence montrée, son dossier, ses images
        self.ref = ""
        self.dossier = ""
        self.chemins = []
        self.index = 0
        #: lecture des adresses (None: le réseau; les tests en passent une)
        self.lire = None
        #: True: télécharger sur le fil de l'interface (tests)
        self.synchrone = False
        self._etat = None
        self._jeton = None
        self._image = None
        #: ce qui ouvre l'original ailleurs (remplaçable: les tests)
        self.ouvrir = ouvrir_externe
        self._relais = _Relais(self)
        self._relais.etape.connect(self._sur_etape)
        self._relais.fini.connect(self._sur_fini)

        racine = QHBoxLayout(self)
        racine.setContentsMargins(0, 0, 0, 0)
        racine.setSpacing(4)
        self._vignettes_cadre = QWidget()
        self._vignettes = QVBoxLayout(self._vignettes_cadre)
        self._vignettes.setContentsMargins(0, 0, 0, 0)
        self._vignettes.setSpacing(4)
        self._vignettes.addStretch()
        self._vignettes_cadre.setFixedWidth(66)
        racine.addWidget(self._vignettes_cadre)
        centre = QVBoxLayout()
        centre.setSpacing(2)
        rangee = QHBoxLayout()
        self.prec_btn = QToolButton()
        self.prec_btn.setIcon(get_button_icon("precedent", 18))
        self.prec_btn.setToolTip("Image précédente")
        self.prec_btn.clicked.connect(lambda: self.choisir(self.index - 1))
        self.grande = QLabel("")
        self.grande.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.grande.setMinimumSize(120, 120)
        self.grande.setSizePolicy(QSizePolicy.Policy.Ignored,
                                  QSizePolicy.Policy.Ignored)
        self.grande.setStyleSheet("background: #000000; color: #6c7086;")
        self.suiv_btn = QToolButton()
        self.suiv_btn.setIcon(get_button_icon("suivant", 18))
        self.suiv_btn.setToolTip("Image suivante")
        self.suiv_btn.clicked.connect(lambda: self.choisir(self.index + 1))
        for b in (self.prec_btn, self.suiv_btn):
            b.setStyleSheet(self._STYLE_BOUTON)
            b.setFixedWidth(26)
            b.setSizePolicy(QSizePolicy.Policy.Fixed,
                            QSizePolicy.Policy.Expanding)
        rangee.addWidget(self.prec_btn)
        rangee.addWidget(self.grande, 1)
        rangee.addWidget(self.suiv_btn)
        centre.addLayout(rangee, 1)
        etat = QHBoxLayout()
        self.statut = QLabel("")
        self.statut.setStyleSheet("color: #a6adc8; font-size: 10px;")
        self.statut.setWordWrap(True)
        etat.addWidget(self.statut, 1)
        self.annuler_btn = QToolButton()
        self.annuler_btn.setText("Annuler")
        self.annuler_btn.setToolTip("Arrêter le téléchargement")
        self.annuler_btn.clicked.connect(self.annuler)
        self.recharger_btn = QToolButton()
        self.recharger_btn.setText("Recharger")
        self.recharger_btn.setToolTip(
            "Redemander les images au webshop DATRON")
        self.recharger_btn.clicked.connect(
            lambda: self.charger(self.ref, self.dossier, forcer=True))
        self.webshop_btn = QToolButton()
        self.webshop_btn.setText("Webshop")
        self.webshop_btn.setToolTip("La fiche de l'outil sur le webshop "
                                    "DATRON, dans le navigateur")
        self.webshop_btn.clicked.connect(self._ouvrir_webshop)
        self.original_btn = QToolButton()
        self.original_btn.setText("Original")
        self.original_btn.setToolTip(
            "L'image en pleine qualité (telle que le webshop la donne), "
            "dans la visionneuse du système")
        self.original_btn.clicked.connect(self.ouvrir_original)
        for b in (self.annuler_btn, self.original_btn, self.recharger_btn,
                  self.webshop_btn):
            b.setStyleSheet(self._STYLE_BOUTON)
            etat.addWidget(b)
        centre.addLayout(etat)
        racine.addLayout(centre, 1)
        self.annuler_btn.hide()
        self._maj_fleches()

    # ──── chargement ────

    def charger(self, ref: str, dossier: str, forcer: bool = False) -> None:
        """Les images de la référence: gardées, sinon demandées au
        webshop (en arrière-plan)."""
        from src.core import images_datron as im
        self.annuler()
        self.ref = im.normaliser(ref)
        self.dossier = dossier
        self.webshop_btn.setEnabled(bool(self.ref))
        self.recharger_btn.setEnabled(bool(self.ref))
        if not self.ref:
            self.montrer_images([], "Pas de référence: pas de photo DATRON")
            return
        cache = im.images_en_cache(dossier, self.ref)
        if cache and not forcer:
            self.montrer_images(cache, f"{len(cache)} image(s) du webshop "
                                       f"DATRON ({self.ref})")
            return
        if not forcer and im.absence_recente(dossier, self.ref):
            self.montrer_images([], f"Aucune image sur le webshop DATRON "
                                    f"pour {self.ref} (« Recharger » pour "
                                    "redemander)")
            return
        self.montrer_images([], f"Images DATRON: recherche de {self.ref} "
                                "sur webshop.datron.de…")
        self._lancer(forcer)

    def _lancer(self, forcer: bool) -> None:
        from src.core import images_datron as im
        from src.core.vcarve import Annule
        # chaque téléchargement a son drapeau: en lancer un autre (la
        # fiche suit la sélection) arrête le précédent
        etat = {'annule': False}
        self._etat = etat
        jeton = object()
        self._jeton = jeton
        ref, dossier, lire, relais = (self.ref, self.dossier, self.lire,
                                      self._relais)

        def progression(_fraction, texte):
            try:
                relais.etape.emit(texte, jeton)
            except RuntimeError:            # la fiche est fermée
                return False
            return not etat['annule']

        def courir():
            try:
                chemins = im.telecharger(ref, dossier, progression, lire,
                                         forcer)
                message = (f"{len(chemins)} image(s) du webshop DATRON "
                           f"({ref})" if chemins else
                           f"Aucune image sur le webshop DATRON pour {ref}")
            except Annule:
                chemins, message = [], "Téléchargement annulé"
            except Exception as exc:
                chemins, message = [], ("Webshop DATRON injoignable — "
                                        f"pas de photo ({exc})")
            try:
                relais.fini.emit(chemins, message, jeton)
            except RuntimeError:
                pass

        self.annuler_btn.show()
        if self.synchrone:
            courir()
        else:
            threading.Thread(target=courir, name="neodrive-images",
                             daemon=True).start()

    def annuler(self) -> None:
        if self._etat is not None:
            self._etat['annule'] = True
        self._etat = None
        self._jeton = None
        self.annuler_btn.hide()

    def original(self):
        """Le fichier original (pleine qualité) de l'image montrée."""
        from src.core import images_datron as im
        if not self.chemins:
            return None
        nom = os.path.splitext(os.path.basename(
            self.chemins[self.index]))[0]
        return next((o for o in im.originaux(self.dossier, self.ref)
                     if os.path.splitext(os.path.basename(o))[0] == nom),
                    None)

    def ouvrir_original(self) -> bool:
        chemin = self.original()
        return bool(chemin and self.ouvrir(chemin))

    def _sur_etape(self, texte: str, jeton) -> None:
        if jeton is self._jeton:
            self.statut.setText(f"Images DATRON: {texte}…")

    def _sur_fini(self, chemins, message: str, jeton) -> None:
        if jeton is not self._jeton:
            return                          # une autre référence depuis
        self._jeton = None
        self.annuler_btn.hide()
        self.montrer_images(list(chemins), message)

    def _ouvrir_webshop(self) -> None:
        from src.core.images_datron import URL_RECHERCHE
        if self.ref:
            QDesktopServices.openUrl(QUrl(URL_RECHERCHE.format(ref=self.ref)))

    # ──── affichage ────

    def montrer_images(self, chemins: list, message: str = "") -> None:
        while self._vignettes.count() > 1:
            item = self._vignettes.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.chemins = list(chemins)
        for i, chemin in enumerate(self.chemins):
            b = QToolButton()
            b.setCheckable(True)
            b.setFixedSize(62, 62)
            b.setIconSize(b.size() * 0.9)
            pix = QPixmap(chemin)
            if not pix.isNull():
                b.setIcon(pix.scaled(56, 56, Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation))
            b.setToolTip(os.path.basename(chemin))
            b.setStyleSheet(self._STYLE_BOUTON)
            b.clicked.connect(lambda _=False, k=i: self.choisir(k))
            self._vignettes.insertWidget(i, b)
        self.statut.setText(message)
        self.choisir(0)

    def vignettes(self) -> list:
        return [self._vignettes.itemAt(i).widget()
                for i in range(self._vignettes.count())
                if self._vignettes.itemAt(i).widget() is not None]

    def choisir(self, i: int) -> None:
        if not self.chemins:
            self.index = 0
            self._image = None
            self.grande.setPixmap(QPixmap())
            self.grande.setText("pas de photo")
            self._maj_fleches()
            return
        self.index = i % len(self.chemins)
        self._image = QPixmap(self.chemins[self.index])
        for k, b in enumerate(self.vignettes()):
            b.setChecked(k == self.index)
        self._peindre()
        self._maj_fleches()

    def _peindre(self) -> None:
        if self._image is None or self._image.isNull():
            return
        taille = self.grande.size()
        self.grande.setText("")
        self.grande.setPixmap(self._image.scaled(
            max(10, taille.width()), max(10, taille.height()),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

    def _maj_fleches(self) -> None:
        plusieurs = len(self.chemins) > 1
        self.prec_btn.setEnabled(plusieurs)
        self.suiv_btn.setEnabled(plusieurs)
        self.original_btn.setEnabled(bool(self.chemins))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._peindre()


class FicheOutil(QWidget):
    """La fiche d'un outil de tools.json (éditable) ou du catalogue
    (`entree`: en lecture, avec ses données constructeur)."""

    #: « ✕ Fermer » (sans enregistrer)
    fermer_demande = Signal()
    #: « Enregistrer et fermer » — le panneau enregistre et redessine
    enregistrer_demande = Signal()

    _STYLE_BOUTON = (
        "QPushButton { font-size: 11px; padding: 3px 10px; "
        "background: #313244; color: %s; border-radius: 4px; }"
        "QPushButton:hover { background: #45475a; }"
        "QPushButton:disabled { color: #585b70; }")

    def __init__(self, tool_data: dict = None, bibliotheque=None,
                 catalogue=None, tool_id: str = None, entree: dict = None,
                 html: str = "", parent=None):
        super().__init__(parent)
        self._tool_data = dict(tool_data or {})
        self.bibliotheque = bibliotheque
        self.catalogue = catalogue
        #: l'outil de tools.json (None: nouvel outil, ou catalogue)
        self.tool_id = tool_id
        #: l'entrée du catalogue (fiche en lecture)
        self.entree = entree
        self.editor = None
        #: ce qui ouvre un fichier ailleurs (remplaçable: les tests)
        self.ouvrir = ouvrir_externe
        #: les fichiers d'aperçu (le dessin de la fiche telle qu'elle est)
        self.fichiers_apercu = {}
        self.cotes = {}
        self._tmp = tempfile.mkdtemp(prefix="neodrive_fiche_")
        self._minuterie = QTimer(self)
        self._minuterie.setSingleShot(True)
        self._minuterie.setInterval(250)
        self._minuterie.timeout.connect(self.actualiser_dessin)
        #: les fichiers montrés et d'où ils viennent ('fiche': le
        #: dossier de la fiche, 'apercu': temporaires)
        self.fichiers_montres = {}
        self.origine = ""
        self._setup_ui(html)
        #: la fiche telle qu'ouverte (pour savoir si on l'a retouchée)
        self._depart = (self.editor.get_tool_data()
                        if self.editor is not None else None)
        self.actualiser_dessin()

    # ──── construction ────

    def _setup_ui(self, html: str) -> None:
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
        haut = QHBoxLayout()
        nom = self._tool_data.get('name') or "Nouvel outil"
        ref = str(self._tool_data.get('reference') or '')
        self.titre = QLabel(("📋 Fiche catalogue — " if self.entree
                             else "📋 Fiche — ") + nom
                            + (f"  ({ref})" if ref else ""))
        self.titre.setStyleSheet(
            "font-weight: bold; font-size: 14px; color: #cdd6f4;")
        haut.addWidget(self.titre, 1)
        self.fermer_btn = QPushButton("✕ Fermer")
        self.fermer_btn.setToolTip("Fermer la fiche sans enregistrer")
        self.fermer_btn.setStyleSheet(self._STYLE_BOUTON % "#f38ba8")
        self.fermer_btn.clicked.connect(self.fermer_demande.emit)
        haut.addWidget(self.fermer_btn)
        v.addLayout(haut)

        partage = QSplitter(Qt.Orientation.Horizontal)
        self._partage = partage
        self._partage_regle = False
        v.addWidget(partage, 1)

        # à gauche: les specs
        gauche = QWidget()
        g = QVBoxLayout(gauche)
        g.setContentsMargins(0, 0, 0, 0)
        if self.entree is None:
            from src.gui.dialogs.tool_manager_dialog import ToolEditorInline
            self.editor = ToolEditorInline(self._tool_data, self)
            self.editor.saved.connect(self.enregistrer_demande.emit)
            self.editor.cancelled.connect(self.fermer_demande.emit)
            self._renommer_boutons()
            self._brancher_editeur()
            defile = QScrollArea()
            defile.setWidgetResizable(True)
            defile.setWidget(self.editor)
            g.addWidget(defile, 1)
        else:
            self.specs = QTextBrowser()
            self.specs.setOpenExternalLinks(True)
            self.specs.setStyleSheet(
                "QTextBrowser { background: #1e1e2e; color: #cdd6f4; "
                "font-size: 12px; border: 1px solid #313244; }")
            self.specs.setHtml(html)
            g.addWidget(self.specs, 1)
        #: les boutons d'action ajoutés par l'hôte (catalogue)
        self.actions = QHBoxLayout()
        g.addLayout(self.actions)
        partage.addWidget(gauche)

        # à droite: le dessin
        droite = QWidget()
        d = QVBoxLayout(droite)
        d.setContentsMargins(0, 0, 0, 0)
        self.info = QLabel("")
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.info.setStyleSheet("color: #a6adc8; font-size: 11px;")
        d.addWidget(self.info)
        self.galerie = GalerieDatron()
        self.vues = VuesDessin()
        pile = QSplitter(Qt.Orientation.Vertical)
        self._pile = pile
        pile.addWidget(self.galerie)
        pile.addWidget(self.vues)
        pile.setStretchFactor(0, 1)
        pile.setStretchFactor(1, 2)
        d.addWidget(pile, 1)
        bas = QHBoxLayout()
        self.dxf_btn = QPushButton("Ouvrir le DXF")
        self.step_btn = QPushButton("Ouvrir le STEP")
        self.dossier_btn = QPushButton("Ouvrir le dossier")
        for bouton, cle, couleur in ((self.dxf_btn, 'dxf', "#89b4fa"),
                                     (self.step_btn, 'step', "#a6e3a1"),
                                     (self.dossier_btn, None, "#cdd6f4")):
            bouton.setStyleSheet(self._STYLE_BOUTON % couleur)
            bouton.clicked.connect(
                lambda _=False, c=cle: self.ouvrir_fichier(c))
            bas.addWidget(bouton)
        bas.addStretch()
        d.addLayout(bas)
        partage.addWidget(droite)
        partage.setStretchFactor(0, 4)
        partage.setStretchFactor(1, 5)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._partage_regle and self.width() > 200:
            # moitié specs, moitié dessin: la grille de la fiche tient
            # sans défiler de côté
            self._partage_regle = True
            w = self._partage.width() or self.width()
            self._partage.setSizes([w // 2, w - w // 2])
            # les photos sur un bon tiers, le dessin dessous
            h = self._pile.height() or self.height()
            self._pile.setSizes([int(h * 0.38), h - int(h * 0.38)])

    def changer_entree(self, tool_data: dict, entree: dict,
                       html: str = "") -> None:
        """(fiche catalogue) Une autre référence: la fiche la suit."""
        self._tool_data = dict(tool_data or {})
        self.entree = entree
        ref = str(self._tool_data.get('reference') or '')
        self.titre.setText("📋 Fiche catalogue — "
                           + str(self._tool_data.get('name') or '')
                           + (f"  ({ref})" if ref else ""))
        if hasattr(self, 'specs'):
            self.specs.setHtml(html)
        self.vider_actions()
        self.actualiser_dessin()

    def vider_actions(self) -> None:
        while self.actions.count():
            item = self.actions.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

    def _renommer_boutons(self) -> None:
        for bouton in self.editor.findChildren(QPushButton):
            if bouton.text() == "Enregistrer":
                bouton.setText("Enregistrer et fermer")
                bouton.setToolTip(
                    "Enregistre la fiche dans tools.json et met à jour "
                    "son dessin (DXF et STEP annexés)")
            elif bouton.text() == "Annuler":
                bouton.setText("Fermer sans enregistrer")

    def _brancher_editeur(self) -> None:
        """Chaque retouche d'une spec refait le dessin (un instant
        après la dernière frappe)."""
        e = self.editor
        for w in e._geom_widgets.values():
            signal = getattr(w, 'textChanged', None) or \
                getattr(w, 'currentTextChanged', None)
            if signal is not None:
                signal.connect(self._minuterie.start)
        e.name_edit.textChanged.connect(self._minuterie.start)
        e.ref_edit.textChanged.connect(self._minuterie.start)

    # ──── le dessin ────

    def outil_courant(self):
        """L'outil tel que la fiche le décrit en ce moment."""
        from src.core.tool_library import Tool
        data = (self.editor.get_tool_data() if self.editor is not None
                else dict(self._tool_data))
        return Tool(data)

    def modifiee(self) -> bool:
        """La fiche a été retouchée depuis son ouverture."""
        return (self.editor is not None
                and self.editor.get_tool_data() != self._depart)

    def actualiser_dessin(self) -> dict:
        """Le dessin de la fiche: celui de son dossier quand il est à
        jour (rien à recalculer), sinon refait — gardé dans le dossier
        pour une fiche du catalogue, en aperçu temporaire pour une fiche
        retouchée (« Enregistrer » le garde). Rend ses cotes."""
        from src.core import dessin_outil as do
        from src.core import fiches_outils
        self._minuterie.stop()
        tool = self.outil_courant()
        ref = str(getattr(tool, 'article_nr', '') or '')
        try:
            c = do.cotes_outil(tool, self.catalogue)
            dxf = step = None
            if (self.tool_id and self.bibliotheque is not None
                    and not self.modifiee()
                    and do.dessins_a_jour(self.bibliotheque, self.tool_id,
                                          self.catalogue)):
                f = do.dessins_de(self.bibliotheque, self.tool_id)
                dxf, step = f['dxf'], f['step']
                self.origine = 'fiche'
            elif self.entree is not None and self._catalogue_a_garder(ref):
                dxf, step = self._dessin_catalogue(tool, c, ref)
                self.origine = 'fiche'
            if dxf is None:
                pr = do.profil(c)
                base = os.path.join(self._tmp, "apercu")
                dxf = do.ecrire_dxf(base + ".dxf", pr['points'], c,
                                    tool.name or "outil", pr['z_coupe'],
                                    ref)
                step = do.ecrire_step(base + ".step", pr['points'],
                                      tool.name or "outil", pr['z_coupe'],
                                      ref)
                self.origine = 'apercu'
        except Exception as exc:
            self.info.setText(f"Dessin impossible: {exc}")
            return {}
        self.cotes = c
        self.fichiers_montres = {'dxf': dxf, 'step': step}
        self.fichiers_apercu = dict(self.fichiers_montres)
        self._maj_galerie(ref)
        erreur = self.vues.montrer(dxf, step)
        cotes = "  ·  ".join(
            (f"{k} {c[k]:g}°" if k == 'angle' else f"{k} {c[k]:g}")
            for k in ('D1', 'D2', 'D3', 'L1', 'L2', 'L3', 'angle', 'R')
            if c.get(k))
        self.info.setText(f"{c['famille']}   |   {cotes}   |   cotes: "
                          f"{c['source']}" + (f"\n{erreur}" if erreur
                                              else ""))
        self._maj_boutons()
        return c

    def _catalogue_a_garder(self, ref: str) -> bool:
        """Une fiche du catalogue garde son dessin dans le dossier de la
        référence — sauf si la bibliothèque a l'outil: le dossier est
        alors celui de SA fiche."""
        if not ref or self.bibliotheque is None:
            return False
        return self.bibliotheque.get_tool_by_article(ref) is None

    def _dessin_catalogue(self, tool, c: dict, ref: str):
        """Le dessin d'une fiche du catalogue, dans le dossier de la
        référence: relu s'il est à jour, écrit une fois sinon."""
        from src.core import dessin_outil as do
        from src.core import fiches_outils
        d = fiches_outils.dossier(self.bibliotheque, ref=ref)
        base = os.path.join(d, fiches_outils.cle(ref=ref))
        cotes = {k: c[k] for k in c if isinstance(c[k], (int, float))
                 and not isinstance(c[k], bool)}
        spec = fiches_outils.lire_spec(d)
        if (spec and spec.get('cotes') == cotes
                and os.path.isfile(base + ".dxf")
                and os.path.isfile(base + ".step")):
            return base + ".dxf", base + ".step"
        pr = do.profil(c)
        os.makedirs(d, exist_ok=True)
        dxf = do.ecrire_dxf(base + ".dxf", pr['points'], c, tool.name,
                            pr['z_coupe'], ref)
        step = do.ecrire_step(base + ".step", pr['points'], tool.name,
                              pr['z_coupe'], ref)
        fiches_outils.ecrire_spec(d, "", {
            'type': 'neodrive_fiche_outil', 'version': 1, 'tool_id': None,
            'catalogue': dict(self.entree or {}), 'outil': tool.to_dict(),
            'cotes': cotes, 'famille': c['famille'], 'source': c['source'],
            'fichiers': {'dxf': os.path.basename(dxf),
                         'step': os.path.basename(step)}})
        return dxf, step

    def _maj_galerie(self, ref: str) -> None:
        """Les photos DATRON de la référence (rechargées si elle a
        changé), dans le dossier de sa fiche."""
        from src.core import fiches_outils
        from src.core import images_datron as im
        if im.normaliser(ref) == self.galerie.ref and \
                self.galerie.dossier:
            return
        self.galerie.charger(ref, fiches_outils.dossier(
            self.bibliotheque, ref=ref) if im.normaliser(ref) else "")

    def fichiers(self) -> dict:
        """Le dessin montré: celui du dossier de la fiche, ou l'aperçu
        d'une fiche retouchée."""
        return dict(self.fichiers_montres)

    def _maj_boutons(self) -> None:
        f = self.fichiers()
        self.dxf_btn.setEnabled('dxf' in f)
        self.step_btn.setEnabled('step' in f)
        self.dossier_btn.setEnabled(bool(f))
        quoi = ("le dessin gardé dans le dossier de la fiche"
                if self.origine == 'fiche' else
                "l'aperçu (« Enregistrer et fermer » le garde avec la "
                "fiche)")
        for b in (self.dxf_btn, self.step_btn, self.dossier_btn):
            b.setToolTip(f"Ouvrir {quoi}")

    def ouvrir_fichier(self, cle=None) -> bool:
        """Le DXF, le STEP (cle) ou leur dossier (None), ailleurs."""
        f = self.fichiers()
        if cle is None:
            chemin = next(iter(f.values()), None)
            chemin = os.path.dirname(chemin) if chemin else None
        else:
            chemin = f.get(cle)
        if not chemin:
            return False
        return bool(self.ouvrir(chemin))
