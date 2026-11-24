"""Onglet « Catalogue » (colonne 3): le catalogue DATRON hors ligne.

NeoDrive ne le livre pas (ce sont les données de DATRON AG): l'onglet
le CONSTITUE, à la demande, depuis les fiches publiques du webshop
DATRON — en fond, la fenêtre reste utilisable, la barre d'état montre
où en est la lecture et Annuler l'arrête; la fois suivante reprend là
(`constitution_datron`).

On y cherche un outil (référence, famille, filetage, Ø, dents…), on lit
ce que DATRON en dit — cotes, prix, avances recommandées pour les
fraises 1 dent — et on le fait entrer dans tools.json:

- une référence ABSENTE de la bibliothèque y est ajoutée, nommée comme
  à l'atelier (« Cyl 3 z1L10 »), avec sa fiche @ ToolDescription @ et
  les avances DATRON quand il y en a;
- une référence DÉJÀ présente reçoit ses données constructeur, comme le
  bouton « DATRON » du tableau des outils (les avances de l'utilisateur
  ne bougent pas; un jumeau porte celles de DATRON).

Les avances viennent du modèle ajusté sur le guide de coupe DATRON, ou
des valeurs EXACTES du guide quand l'utilisateur a chargé son PDF.
"""

from contextlib import nullcontext
from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QTextBrowser, QFileDialog, QSplitter
)

from src.gui.widgets import SpinCote

from src.core import catalogue_datron as cdat
from src.core import coupe_datron as coupe

#: au-delà, la table attend des filtres plus fins
MAX_LIGNES = 300

COLONNES = ("Réf", "Famille", "Ø", "L2", "Z", "Queue", "Prix €",
            "n", "Bibliothèque")


class _Nombre(QTableWidgetItem):
    """Une cellule qui se trie comme un nombre (et vide en dernier)."""

    def __init__(self, valeur, texte=None):
        super().__init__("" if valeur in (None, "") else (
            texte if texte is not None else cdat._g(valeur)))
        self._v = float(valeur) if valeur not in (None, "") else None
        self.setTextAlignment(Qt.AlignmentFlag.AlignRight
                              | Qt.AlignmentFlag.AlignVCenter)

    def __lt__(self, autre):
        a = self._v
        b = getattr(autre, "_v", None)
        if a is None:
            return False
        if b is None:
            return True
        return a < b


class CataloguePanel(QWidget):
    """Le catalogue DATRON, pour nourrir tools.json."""

    #: la bibliothèque a changé (outil ajouté, données importées)
    outils_changes = Signal()
    #: la broche choisie pour les avances
    broche_changee = Signal(str)
    #: une phrase pour le journal des actions
    action = Signal(str)
    #: « Fiche tools.json »: ouvrir la fiche de cet outil de la
    #: bibliothèque (son id)
    fiche_outil_demandee = Signal(str)
    #: la fenêtre héberge la fiche à la place des colonnes 1 et 2
    hote_fiche = None
    fermer_hote_fiche = None
    #: () -> contexte: une fiche en remplace une autre dans le même
    #: geste (la fenêtre garde sa page au lieu de rendre les colonnes)
    remplacement_fiche = None
    #: une fiche d'un AUTRE panneau (tools.json) est ouverte en colonnes
    #: 1 et 2: () -> bool, et `quitter_fiche_ailleurs() -> bool` la
    #: ferme (en demandant si elle est retouchée)
    fiche_ailleurs = None
    quitter_fiche_ailleurs = None

    def __init__(self, tool_library, catalogue=None, guide=None,
                 broche: str = coupe.BROCHE_DEFAUT, parent=None):
        super().__init__(parent)
        self.tool_lib = tool_library
        self.catalogue = catalogue if catalogue is not None \
            else cdat.catalogue()
        self.guide = guide if guide is not None else coupe.guide()
        self._lignes = []          # les entrées affichées, dans l'ordre
        self._dossier_guide = ""
        self._tache = None         # la constitution en cours, en fond
        self._construire(broche)
        self._remplir_filtres()
        self._filtrer()

    # ── construction ────────────────────────────────────────────

    def _construire(self, broche):
        racine = QVBoxLayout(self)
        racine.setContentsMargins(4, 4, 4, 4)
        racine.setSpacing(4)

        self.titre = QLabel("")
        self.titre.setStyleSheet(
            "font-weight: bold; font-size: 14px; color: #cdd6f4;")
        racine.addWidget(self.titre)
        # pas de catalogue livré: il se constitue ici, depuis le webshop
        self.cadre_constitution = QWidget()
        rang = QHBoxLayout(self.cadre_constitution)
        rang.setContentsMargins(0, 0, 0, 0)
        self.explication = QLabel("")
        self.explication.setWordWrap(True)
        self.explication.setStyleSheet("color: #f9e2af; font-size: 11px;")
        rang.addWidget(self.explication, 1)
        self.bouton_constituer = QPushButton("Constituer le catalogue")
        self.bouton_constituer.setObjectName("primary")
        self.bouton_constituer.setToolTip(
            "Lit sur le webshop DATRON (webshop.datron.de) le plan du site"
            " puis chaque fiche d'outil: références, familles, cotes, "
            "prix.\nUne fiche à la fois, en fond: la fenêtre reste "
            "utilisable; la barre d'état montre la lecture, Annuler "
            "l'arrête.\nLe catalogue reste sur ce poste "
            "(data/catalogue_datron.json), pour votre usage.")
        self.bouton_constituer.clicked.connect(lambda: self.constituer())
        rang.addWidget(self.bouton_constituer)
        racine.addWidget(self.cadre_constitution)
        self._maj_titre()

        # Recherche + famille
        rang = QHBoxLayout()
        self.recherche = QLineEdit()
        self.recherche.setPlaceholderText(
            "Référence, famille, filetage (ex. 0068432A, équilibrée, M5)")
        self.recherche.setClearButtonEnabled(True)
        self.recherche.textChanged.connect(self._filtrer)
        rang.addWidget(self.recherche, 1)
        self.categorie = QComboBox()
        self.categorie.setToolTip("Famille d'outils")
        self.categorie.currentIndexChanged.connect(self._categorie_changee)
        rang.addWidget(self.categorie)
        racine.addLayout(rang)

        # Ø, dents, L2 mini
        rang = QHBoxLayout()
        rang.addWidget(QLabel("Ø"))
        self.diametre = QComboBox()
        self.diametre.setToolTip("Ø de coupe (D1)")
        self.diametre.currentIndexChanged.connect(self._filtrer)
        rang.addWidget(self.diametre)
        rang.addWidget(QLabel("Dents"))
        self.dents = QComboBox()
        self.dents.currentIndexChanged.connect(self._filtrer)
        rang.addWidget(self.dents)
        # le champ de l'application (12 et non 12,0; l'unité dans le
        # libellé, pas dans le champ)
        rang.addWidget(QLabel("L2 mini (mm)"))
        self.l2_min = SpinCote(decimales=1)
        self.l2_min.setRange(0, 200)
        self.l2_min.setMaximumWidth(56)
        self.l2_min.setToolTip("Longueur de coupe minimale (0 = toutes)")
        self.l2_min.valueChanged.connect(self._filtrer)
        rang.addWidget(self.l2_min)
        effacer = QPushButton("Tout voir")
        effacer.setToolTip("Effacer la recherche et les filtres")
        effacer.clicked.connect(self._effacer_filtres)
        rang.addWidget(effacer)
        rang.addStretch()
        racine.addLayout(rang)

        # Avances: broche et guide
        rang = QHBoxLayout()
        rang.addWidget(QLabel("Broche"))
        self.broche = QComboBox()
        self.broche.addItems(list(coupe.BROCHES))
        self.broche.setToolTip(
            "Broche de la machine: les avances DATRON en dépendent")
        if broche in coupe.BROCHES:
            self.broche.setCurrentText(broche)
        self.broche.currentTextChanged.connect(self._broche_changee)
        rang.addWidget(self.broche)
        self.etat_guide = QLabel("")
        self.etat_guide.setWordWrap(True)
        self.etat_guide.setStyleSheet("color: #a6adc8; font-size: 11px;")
        rang.addWidget(self.etat_guide, 1)
        charger = QPushButton("Guide PDF…")
        charger.setToolTip(
            "Lire VOTRE exemplaire du « DATRON High-Speed Cutting Guide »"
            " (PDF):\nles avances des références qu'il chiffre deviennent"
            " exactes.\nLa lecture reste sur ce poste "
            "(data/coupe_datron_guide.json).")
        charger.clicked.connect(self._charger_guide)
        rang.addWidget(charger)
        racine.addLayout(rang)
        self._maj_etat_guide()

        # Table + fiche détaillée
        coupe_v = QSplitter(Qt.Orientation.Vertical)
        self.table = QTableWidget(0, len(COLONNES))
        self.table.setHorizontalHeaderLabels(list(COLONNES))
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(22)
        entete = self.table.horizontalHeader()
        entete.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        # tient dans une colonne 3 d'environ 600 px, sans défiler
        entete.setDefaultSectionSize(42)
        entete.resizeSection(0, 76)
        entete.resizeSection(1, 140)
        entete.resizeSection(6, 54)
        entete.resizeSection(7, 54)
        entete.setStretchLastSection(True)
        self.table.setStyleSheet("""
            QTableWidget { background: #181825; color: #cdd6f4;
                           gridline-color: #313244; font-size: 12px; }
            QTableWidget::item:selected { background: #45475a;
                                          color: #ffffff; }
            QHeaderView::section { background: #313244; color: #89b4fa;
                border: 1px solid #45475a; padding: 3px;
                font-weight: bold; font-size: 11px; }""")
        self.table.itemSelectionChanged.connect(self._selection_changee)
        self.table.cellDoubleClicked.connect(
            lambda *_: self._ajouter_selection())
        coupe_v.addWidget(self.table)
        self.fiche = QTextBrowser()
        self.fiche.setOpenExternalLinks(True)
        self.fiche.setStyleSheet(
            "QTextBrowser { background: #1e1e2e; color: #cdd6f4; "
            "font-size: 12px; border: 1px solid #313244; }")
        coupe_v.addWidget(self.fiche)
        coupe_v.setStretchFactor(0, 3)
        coupe_v.setStretchFactor(1, 2)
        racine.addWidget(coupe_v, 1)

        # Actions
        rang = QHBoxLayout()
        self.bouton_ajouter = QPushButton("Ajouter à la bibliothèque")
        self.bouton_ajouter.setObjectName("primary")
        self.bouton_ajouter.clicked.connect(self._ajouter_selection)
        rang.addWidget(self.bouton_ajouter)
        self.bouton_fiche_outil = QPushButton("📋 Fiche")
        self.bouton_fiche_outil.setToolTip(
            "La fiche de l'outil: toutes ses cotes et son dessin 2D et "
            "3D, à la place des colonnes 1 et 2.\nElle suit la "
            "sélection du catalogue.")
        self.bouton_fiche_outil.clicked.connect(lambda: self.ouvrir_fiche())
        rang.addWidget(self.bouton_fiche_outil)
        self._fiche = None
        self.bouton_fiche = QPushButton("Fiche webshop")
        self.bouton_fiche.setToolTip(
            "Ouvrir la fiche de l'outil sur le webshop DATRON")
        self.bouton_fiche.clicked.connect(self._ouvrir_fiche)
        rang.addWidget(self.bouton_fiche)
        # la mise à jour depuis le webshop (cotes, angle), écarts montrés
        from PySide6.QtWidgets import QMenu
        self.bouton_maj = QPushButton("Mettre à jour depuis datron.de ▾")
        self.bouton_maj.setToolTip(
            "Lit sur le webshop DATRON les cotes des outils (D1, D2, L1, L2, "
            "angle, dents…) et montre ce qui diffère du catalogue et de "
            "vos fiches tools.json — rien ne s'écrit avant « Appliquer ».\n"
            "L'angle (« Winkel ») va au TipAngle; l'angle d'hélice "
            "(« Spiralwinkel ») reste à part.")
        menu = QMenu(self.bouton_maj)
        menu.addAction("La sélection du catalogue").triggered.connect(
            lambda: self.mettre_a_jour('selection'))
        menu.addAction("Les outils de la bibliothèque (tools.json)"
                       ).triggered.connect(
            lambda: self.mettre_a_jour('bibliotheque'))
        menu.addAction("Tout le catalogue (long)").triggered.connect(
            lambda: self.mettre_a_jour('tout'))
        menu.addSeparator()
        menu.addAction("Constituer / compléter le catalogue depuis le "
                       "plan du webshop (en fond)").triggered.connect(
            lambda: self.constituer())
        self.bouton_maj.setMenu(menu)
        rang.addWidget(self.bouton_maj)
        rang.addStretch()
        racine.addLayout(rang)

        self.statut = QLabel("")
        self.statut.setWordWrap(True)
        self.statut.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        self.statut.setStyleSheet("color: #a6e3a1; font-size: 11px;")
        racine.addWidget(self.statut)
        self._selection_changee()

    def _remplir_filtres(self):
        self.categorie.blockSignals(True)
        self.categorie.clear()
        self.categorie.addItem(f"Toutes ({len(self.catalogue)})", "")
        for cle, libelle in self.catalogue.categories.items():
            n = sum(1 for x in self.catalogue.outils
                    if x.get("categorie") == cle)
            self.categorie.addItem(f"{libelle} ({n})", cle)
        self.categorie.blockSignals(False)
        self._remplir_cotes()

    def _remplir_cotes(self):
        """Ø et dents: les valeurs de la famille choisie seulement."""
        cat = self.categorie.currentData() or ""
        base = [x for x in self.catalogue.outils
                if not cat or x.get("categorie") == cat]
        for combo, cle, fmt in (
                (self.diametre, "D1", lambda v: f"Ø{cdat._g(v)}"),
                (self.dents, "dents", lambda v: f"{int(v)}")):
            avant = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("tous", None)
            valeurs = sorted({x[cle] for x in base
                              if x.get(cle) not in (None, "")})
            for v in valeurs:
                combo.addItem(fmt(v), v)
            i = combo.findData(avant) if avant is not None else 0
            combo.setCurrentIndex(max(0, i))
            combo.blockSignals(False)

    # ── filtres ─────────────────────────────────────────────────

    def _categorie_changee(self, *_):
        self._remplir_cotes()
        self._filtrer()

    def _effacer_filtres(self):
        for w in (self.recherche, self.categorie, self.diametre,
                  self.dents, self.l2_min):
            w.blockSignals(True)
        self.recherche.clear()
        self.categorie.setCurrentIndex(0)
        self.l2_min.setValue(0)
        for w in (self.recherche, self.categorie, self.diametre,
                  self.dents, self.l2_min):
            w.blockSignals(False)
        self._remplir_cotes()
        self.diametre.setCurrentIndex(0)
        self.dents.setCurrentIndex(0)
        self._filtrer()

    def resultats(self) -> list:
        """Les outils du catalogue qui passent les filtres."""
        l2 = self.l2_min.value()
        return self.catalogue.chercher(
            self.recherche.text(), self.categorie.currentData() or "",
            self.diametre.currentData(), self.dents.currentData(),
            l2 if l2 > 0 else None)

    def _articles_en_bibliotheque(self) -> dict:
        """{article: (n fiches, jumeau DATRON ?)}"""
        vus = {}
        for t in self.tool_lib.tools.values():
            a = t.article_nr.upper()
            n, j = vus.get(a, (0, False))
            vus[a] = (n + 1, j or t.avances_constructeur)
        return vus

    def _filtrer(self, *_):
        res = self.resultats()
        vus = self._articles_en_bibliotheque()
        self._lignes = res[:MAX_LIGNES]
        self.table.setSortingEnabled(False)
        self.table.clearContents()
        self.table.setRowCount(len(self._lignes))
        b = self.broche.currentText()
        for r, x in enumerate(self._lignes):
            ref = QTableWidgetItem(str(x.get("ref")))
            ref.setData(Qt.ItemDataRole.UserRole, r)
            self.table.setItem(r, 0, ref)
            fam = QTableWidgetItem(str(x.get("famille", "")))
            fam.setToolTip(str(x.get("designation_de", "")))
            self.table.setItem(r, 1, fam)
            self.table.setItem(r, 2, _Nombre(x.get("D1")))
            self.table.setItem(r, 3, _Nombre(x.get("L2")))
            self.table.setItem(r, 4, _Nombre(x.get("dents")))
            self.table.setItem(r, 5, _Nombre(x.get("D2")))
            prix = x.get("prix_eur")
            self.table.setItem(r, 6, _Nombre(
                prix, f"{prix:.2f}".replace(".", ",")
                if prix not in (None, "") else None))
            av = self.catalogue.avances(x, b, self.guide)
            n = _Nombre(av["rpm"] if av else None,
                        cdat.milliers(av["rpm"]) if av else None)
            if av:
                n.setToolTip(cdat.resume_avances(av))
                if av["source"] == "guide":
                    n.setForeground(QColor("#a6e3a1"))
            self.table.setItem(r, 7, n)
            nb, jum = vus.get(str(x.get("ref")).upper(), (0, False))
            txt = ("" if not nb else
                   "✓" + (f" ×{nb}" if nb > 1 else "")
                   + (" · DATRON" if jum else ""))
            biblio = QTableWidgetItem(txt)
            if nb:
                biblio.setForeground(QColor("#a6e3a1"))
            self.table.setItem(r, 8, biblio)
        self.table.setSortingEnabled(True)
        total = len(res)
        if not total:
            self.statut.setText("Aucun outil ne correspond.")
        elif total > MAX_LIGNES:
            self.statut.setText(
                f"{total} outils — les {MAX_LIGNES} premiers affichés, "
                "affinez les filtres.")
        else:
            self.statut.setText(f"{total} outil(s).")
        self._selection_changee()

    # ── la mise à jour depuis le webshop ──

    def refs_a_mettre_a_jour(self, genre: str) -> list:
        """Les références que la mise à jour lit: la sélection, les
        outils DATRON de la bibliothèque, ou tout le catalogue."""
        if genre == 'selection':
            return [str(x['ref']) for x in self.selection()]
        if genre == 'bibliotheque':
            refs = []
            for t in self.tool_lib.get_all_tools():
                art = getattr(t, 'article_nr', '')
                if art and self.catalogue.entree(art) is not None \
                        or (art and str(getattr(t, 'vendor', '')).upper()
                            == 'DATRON'):
                    refs.append(art)
            return refs
        return [str(x['ref']) for x in self.catalogue.outils]

    #: remplaçable par les tests (pas de réseau): url -> bytes
    lire_url = None

    def mettre_a_jour(self, genre: str = 'selection', executer: bool = True):
        """Lit le webshop (dans la barre d'état, Annuler agit), montre
        les écarts, applique ceux qu'on garde. Rend la fenêtre des écarts
        (None s'il n'y en a pas)."""
        from src.core import maj_datron as maj
        from src.gui.progression import travailler
        refs = self.refs_a_mettre_a_jour(genre)
        if not refs:
            self.statut.setText("Rien à mettre à jour: aucune référence.")
            return None
        lus = travailler(
            self, "datron.de",
            lambda prog: maj.recuperer(refs, prog, self.lire_url),
            f"Lecture de {len(refs)} référence(s) sur le webshop…")
        if lus is None:
            self.statut.setText("Mise à jour annulée.")
            return None
        erreurs = [f"{l['ref']}: {l['erreur']}" for l in lus if l['erreur']]
        props = maj.propositions(lus, self.catalogue, self.tool_lib)
        if not props:
            lus_ok = sum(1 for l in lus if l['web'])
            self.statut.setText(
                f"datron.de: {lus_ok} référence(s) lue(s), rien ne diffère"
                + (f" — {len(erreurs)} non lue(s)" if erreurs else "") + ".")
            return None
        from src.gui.dialogs.ecarts_datron import DialogueEcartsDatron
        dlg = DialogueEcartsDatron(props, erreurs, self)
        if not executer:
            return dlg
        if dlg.exec():
            self.appliquer_ecarts(dlg.choix())
        return dlg

    def appliquer_ecarts(self, choix: list) -> dict:
        from src.core import maj_datron as maj
        bilan = maj.appliquer(choix, self.tool_lib,
                              maj.chemin_maj(self.catalogue.chemin),
                              self.catalogue)
        self.catalogue.charger()
        self._filtrer()
        if bilan['outils']:
            self.outils_changes.emit()
        self.statut.setText(
            f"datron.de: {bilan['catalogue']} référence(s) du catalogue et "
            f"{bilan['outils']} fiche(s) d'outil mises à jour.")
        return bilan

    def rafraichir(self):
        """La bibliothèque a changé ailleurs: la colonne « Bibliothèque »
        suit."""
        self._filtrer()

    # ── constitution depuis le webshop ──────────────────────────

    #: remplaçable par les tests: pause entre deux fiches (None: celle
    #: de `constitution_datron`)
    pause_constitution = None

    def _maj_titre(self):
        """Le titre, et le cadre « à constituer / reprendre » quand le
        catalogue manque ou n'est pas fini."""
        from src.core import constitution_datron as cons
        n = len(self.catalogue)
        self.titre.setText(f"Catalogue DATRON — {n} références hors ligne"
                           if n else "Catalogue DATRON — à constituer")
        etat = cons.etat(self.catalogue.chemin)
        if self._tache is not None:
            texte = ("Constitution en cours, en fond: la fenêtre reste "
                     "utilisable; Annuler (barre d'état) l'arrête, la "
                     "fois suivante reprend là.")
            bouton = "Constituer le catalogue"
        elif not n:
            texte = ("Pas de catalogue sur ce poste. NeoDrive ne livre "
                     "pas les données DATRON: il les lit sur le webshop "
                     "DATRON, une fiche à la fois — une vingtaine de "
                     "minutes, en fond. Le catalogue reste sur ce poste,"
                     " pour votre usage.")
            if (self.catalogue.erreur and not
                    self.catalogue.erreur.startswith("catalogue absent")):
                texte = f"⚠ {self.catalogue.erreur}\n{texte}"
            bouton = ("Reprendre" if etat['constitue'] and etat['lues']
                      else "Constituer le catalogue")
        elif not etat['complet']:
            texte = (f"Catalogue incomplet ({etat['lues']} fiche(s) lue(s)"
                     "): « Reprendre » continue la lecture là où elle "
                     "s'est arrêtée.")
            bouton = "Reprendre"
        else:
            self.cadre_constitution.hide()
            return
        self.explication.setText(texte)
        self.bouton_constituer.setText(bouton)
        self.bouton_constituer.setEnabled(self._tache is None)
        self.cadre_constitution.show()

    def constituer(self, synchrone: bool = False):
        """Constitue (ou complète, ou reprend) le catalogue depuis le
        webshop DATRON, en fond. Rend la tâche (celle déjà en cours si
        la lecture tourne)."""
        from src.core import constitution_datron as cons
        from src.gui.progression import TacheDeFond
        if self._tache is not None:
            return self._tache
        chemin = self.catalogue.chemin
        lire = self.lire_url
        pause = (cons.PAUSE if self.pause_constitution is None
                 else self.pause_constitution)
        tache = TacheDeFond(
            self, "Catalogue DATRON",
            lambda prog: cons.constituer(chemin, prog, lire, pause=pause),
            "plan du webshop…")
        tache.avance.connect(self._constitution_avance)
        tache.fini.connect(self._constitution_finie)
        self._tache = tache
        self._maj_titre()
        self.statut.setText("Constitution du catalogue: plan du webshop…")
        tache.demarrer(synchrone)
        return tache

    def _constitution_avance(self, _fraction: float, texte: str):
        if self._tache is not None and texte:
            self.statut.setText(f"Constitution du catalogue: {texte}")

    def _constitution_finie(self, bilan, erreur, annule: bool):
        from src.core import constitution_datron as cons
        self._tache = None
        self.catalogue.charger()
        self._remplir_filtres()
        self._filtrer()
        self._maj_titre()
        if annule:
            etat = cons.etat(self.catalogue.chemin)
            self.statut.setText(
                f"Constitution interrompue: {etat['lues']} fiche(s) lue(s)"
                f", {etat['outils']} référence(s) au catalogue — "
                "« Reprendre » continue là.")
        elif erreur is not None:
            self.statut.setText(f"⚠ Constitution arrêtée: {erreur}")
        else:
            self.statut.setText(cons.resume(bilan))

    # ── sélection et fiche ──────────────────────────────────────

    def selection(self) -> list:
        """Les entrées du catalogue sélectionnées, dans l'ordre de la
        table (même triée)."""
        rangs = sorted({i.row() for i in self.table.selectedItems()})
        res = []
        for r in rangs:
            it = self.table.item(r, 0)
            if it is None:
                continue
            k = it.data(Qt.ItemDataRole.UserRole)
            if k is not None and 0 <= int(k) < len(self._lignes):
                res.append(self._lignes[int(k)])
        return res

    def selectionner_ref(self, ref: str) -> bool:
        """Sélectionne la ligne d'une référence (si elle est affichée)."""
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it is not None and it.text().upper() == str(ref).upper():
                self.table.clearSelection()
                self.table.selectRow(r)
                self.table.scrollToItem(it)
                return True
        return False

    def _selection_changee(self):
        sel = self.selection()
        vus = self._articles_en_bibliotheque()
        presents = [x for x in sel if str(x.get("ref")).upper() in vus]
        self.bouton_ajouter.setEnabled(bool(sel))
        self.bouton_fiche.setEnabled(len(sel) == 1)
        self.bouton_fiche_outil.setEnabled(len(sel) == 1)
        if self._fiche is not None and len(sel) == 1:
            # la fiche ouverte suit la sélection
            self._remplir_fiche(self._fiche, sel[0])
        elif (len(sel) == 1 and callable(self.fiche_ailleurs)
              and self.fiche_ailleurs()):
            # la fiche d'un outil de la bibliothèque est ouverte: elle
            # laisse la place à celle de la référence choisie
            with self._remplacement():
                if not callable(self.quitter_fiche_ailleurs) or \
                        self.quitter_fiche_ailleurs():
                    self.ouvrir_fiche(sel[0])
        if sel and len(presents) == len(sel):
            self.bouton_ajouter.setText("Données constructeur → "
                                        "outil existant")
            self.bouton_ajouter.setToolTip(
                "Ces références sont déjà dans la bibliothèque: leur "
                "fiche est complétée (jamais écrasée) et, pour les "
                "fraises 1 dent, un jumeau « avances DATRON » porte "
                "les avances constructeur. Vos avances ne bougent pas.")
        else:
            self.bouton_ajouter.setText("Ajouter à la bibliothèque")
            self.bouton_ajouter.setToolTip(
                "Nouvel outil dans tools.json, nommé comme à l'atelier, "
                "avec sa fiche @ ToolDescription @ et les avances "
                "DATRON quand il y en a.\nUne référence déjà présente "
                "reçoit seulement ses données constructeur.")
        self.fiche.setHtml(self._fiche_html(sel[0]) if len(sel) == 1
                           else ("" if not sel else
                                 f"<i>{len(sel)} outils sélectionnés</i>"))

    def _fiche_html(self, x: dict) -> str:
        import html
        e = html.escape
        ref = str(x.get("ref"))
        lignes = [f"<b style='color:#89b4fa'>{e(ref)}</b> — "
                  f"{e(str(x.get('famille', '')))}"]
        if x.get("designation_de"):
            lignes.append(f"<i>{e(str(x['designation_de']))}</i>")
        cotes = [f"{e(cdat.LIBELLES_COTES.get(k, k))} "
                 f"<b>{e(cdat._g(x[k]) if k != 'filetage' else str(x[k]))}"
                 f"</b>"
                 for k in cdat.COTES if x.get(k) not in (None, "")]
        lignes.append(" · ".join(cotes))
        prix = []
        if x.get("prix_eur") not in (None, ""):
            prix.append(f"prix liste {x['prix_eur']:.2f} € HT"
                        .replace(".", ","))
        if x.get("groupe_prix"):
            prix.append(f"groupe {e(str(x['groupe_prix']))}")
        if x.get("page_catalogue"):
            prix.append(f"catalogue p. {e(str(x['page_catalogue']))}")
        if prix:
            lignes.append(" · ".join(prix))
        lignes.append(f"Dans NeoDrive: <b>{e(cdat.nom_atelier(x))}</b>, "
                      f"type {e(cdat.type_atelier(x))}")
        av = self.catalogue.avances(x, self.broche.currentText(),
                                    self.guide)
        if av:
            lignes.append("<b style='color:#a6e3a1'>Avances DATRON</b>: "
                          + e(cdat.resume_avances(av)))
            lignes.append(
                f"rainurage ap {cdat._g(av['rainurage']['ap'])} × ae "
                f"{cdat._g(av['rainurage']['ae'])} · latéral ap "
                f"{cdat._g(av['lateral']['ap'])} × ae "
                f"{cdat._g(av['lateral']['ae'])} mm")
            for n in av.get("notes", []):
                lignes.append(f"<span style='color:#a6adc8'>{e(n)}</span>")
        else:
            lignes.append("<span style='color:#a6adc8'>Pas d'avances "
                          "constructeur: DATRON ne chiffre que les "
                          "fraises 1 dent.</span>")
        deja = [t for t in self.tool_lib.tools.values()
                if t.article_nr.upper() == ref.upper()]
        if deja:
            lignes.append("Déjà dans la bibliothèque: " + ", ".join(
                e(t.display_name) for t in deja))
        return "<br>".join(lignes)

    # ── actions ─────────────────────────────────────────────────

    def _broche_changee(self, texte: str):
        self.broche_changee.emit(texte)
        self._filtrer()

    def _maj_etat_guide(self):
        n = self.guide.nb_refs()
        if n:
            self.etat_guide.setText(
                f"Guide: {n} réf. aux avances exactes, les autres par "
                "le modèle.")
            self.etat_guide.setToolTip(
                f"{self.guide.source} — lu le {self.guide.date}")
        else:
            self.etat_guide.setText(
                "Avances du modèle (indicatives): chargez le guide "
                "PDF pour les valeurs exactes.")

    def _charger_guide(self):
        chemin, _ = QFileDialog.getOpenFileName(
            self, "DATRON High-Speed Cutting Guide (PDF)",
            self._dossier_guide, "PDF (*.pdf)")
        if not chemin:
            return
        self.charger_guide(chemin)

    def charger_guide(self, chemin: str):
        """Lit le guide PDF (progression dans la barre d'état,
        annulable)."""
        import os
        from src.gui.progression import travailler
        self._dossier_guide = os.path.dirname(chemin)
        try:
            n = travailler(self, "Guide DATRON",
                           lambda prog: self.guide.importer(chemin, prog),
                           "Lecture des tableaux de coupe…")
        except Exception as e:
            self.statut.setText(f"✗ Guide illisible: {e}")
            return None
        if n is None:
            self.statut.setText("Lecture du guide annulée: rien n'a "
                                "changé.")
            return None
        self._maj_etat_guide()
        self._filtrer()
        msg = (f"Guide DATRON lu: {n} références aux avances exactes "
               f"({os.path.basename(chemin)}).")
        self.statut.setText(msg)
        self.action.emit(msg)
        return n

    def _ajouter_selection(self):
        sel = self.selection()
        if not sel:
            return
        b = self.broche.currentText()
        messages = []
        for x in sel:
            existant = self.tool_lib.get_tool_by_article(str(x["ref"]))
            if existant is not None:
                tid = next(k for k, t in self.tool_lib.tools.items()
                           if t is existant)
                rapport = self.tool_lib.importer_constructeur(
                    tid, self.catalogue, b, self.guide)
                messages.append(cdat.resume_import(rapport, self.tool_lib))
            else:
                tid = self.tool_lib.ajouter_depuis_catalogue(
                    x, self.catalogue, b, self.guide)
                t = self.tool_lib.tools[tid]
                quoi = (cdat.resume_avances(t.constructeur["coupe"])
                        if t.constructeur.get("coupe")
                        else "avances à régler (pas de recommandation "
                             "DATRON pour ce type d'outil)")
                messages.append(f"{t.display_name} ajouté — {quoi}")
        refs = [str(x["ref"]) for x in sel]
        self._filtrer()
        if len(refs) == 1:
            self.selectionner_ref(refs[0])
        texte = "\n".join(messages)
        self.statut.setText(texte)
        for m in messages:
            self.action.emit(m)
        self.outils_changes.emit()

    # ── la fiche d'un outil du catalogue ──

    @staticmethod
    def donnees_outil(x: dict) -> dict:
        """L'outil que la référence donnerait dans tools.json: son nom
        d'atelier et ses cotes constructeur."""
        # la fiche @ ToolDescription @ reste vide: les cotes viennent du
        # catalogue, et le dessin le dit
        return {'name': cdat.nom_atelier(x), 'reference': str(x.get('ref')),
                'vendor': 'DATRON',
                'constructeur': {
                    'cotes': {k: x[k] for k in cdat.COTES
                              if isinstance(x.get(k), (int, float))},
                    'categorie': x.get('categorie'),
                    'famille': x.get('famille')}}

    def ouvrir_fiche(self, x: dict = None):
        """« 📋 Fiche »: la fiche de la référence choisie, à la place
        des colonnes 1 et 2. Rend le widget (None sans place)."""
        from src.gui.dialogs.fiche_outil import FicheOutil
        if x is None:
            sel = self.selection()
            x = sel[0] if len(sel) == 1 else None
        if x is None:
            return None
        with self._remplacement():
            self.fermer_fiche()
            fiche = FicheOutil(self.donnees_outil(x), self.tool_lib,
                               self.catalogue, entree=x,
                               html=self._fiche_html(x))
            fiche.fermer_demande.connect(self.fermer_fiche)
            self._ajouter_actions(fiche, x)
            if not (callable(self.hote_fiche) and self.hote_fiche(fiche)):
                fiche.deleteLater()
                self.statut.setText("Pas de place pour la fiche: le "
                                    "tableau des outils occupe toute la "
                                    "fenêtre.")
                return None
        self._fiche = fiche
        return fiche

    def _remplacement(self):
        """Le contexte « une fiche en remplace une autre » de la
        fenêtre (rien sans fenêtre)."""
        if callable(self.remplacement_fiche):
            return self.remplacement_fiche()
        return nullcontext()

    def _remplir_fiche(self, fiche, x: dict) -> None:
        fiche.changer_entree(self.donnees_outil(x), x, self._fiche_html(x))
        self._ajouter_actions(fiche, x)

    def _ajouter_actions(self, fiche, x: dict) -> None:
        existant = self.tool_lib.get_tool_by_article(str(x["ref"]))
        if existant is not None:
            tid = next(k for k, t in self.tool_lib.tools.items()
                       if t is existant)
            bouton = QPushButton("Ouvrir sa fiche tools.json")
            bouton.setToolTip(f"{existant.display_name}: sa fiche dans la "
                              "bibliothèque, éditable")
            bouton.clicked.connect(
                lambda _=False, t=tid: self.fiche_outil_demandee.emit(t))
        else:
            bouton = QPushButton("Ajouter à la bibliothèque")
            bouton.setObjectName("primary")
            bouton.setToolTip("Nouvel outil dans tools.json, avec cette "
                              "fiche et ce dessin")
            bouton.clicked.connect(
                lambda _=False, r=str(x["ref"]): self._ajouter_depuis_fiche(r))
        fiche.actions.addWidget(bouton)
        fiche.actions.addStretch()

    def _ajouter_depuis_fiche(self, ref: str) -> None:
        self.selectionner_ref(ref)
        self._ajouter_selection()
        tid = next((k for k, t in self.tool_lib.tools.items()
                    if t.article_nr.upper() == ref.upper()), None)
        if tid is not None:
            # le dessin part avec l'outil
            try:
                from src.core import dessin_outil
                dessin_outil.dessiner(self.tool_lib, tid, self.catalogue)
                self.tool_lib.save()
            except Exception as exc:
                self.statut.setText(self.statut.text()
                                    + f"\nDessin impossible: {exc}")
        x = self.catalogue.entree(ref)
        if self._fiche is not None and x is not None:
            self._remplir_fiche(self._fiche, x)

    def fermer_fiche(self) -> None:
        fiche, self._fiche = self._fiche, None
        if fiche is None:
            return
        if callable(self.fermer_hote_fiche):
            self.fermer_hote_fiche(fiche)
        fiche.hide()
        fiche.deleteLater()

    def _ouvrir_fiche(self):
        sel = self.selection()
        if len(sel) != 1:
            return
        url = self.catalogue.sources.get("fiche_webshop") \
            or cdat.FICHE_WEBSHOP
        QDesktopServices.openUrl(QUrl(url.replace("{ref}",
                                                  str(sel[0]["ref"]))))
