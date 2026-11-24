"""
Fenêtre principale NeoDrive.
Layout 3 colonnes avec splitter, barre d'état (pas de menu bar).
Orchestre les signaux entre les 3 panneaux.
- Menu Fichier → bouton rouge dans la statusbar, ouvre dans col1
- Menu Outils → migré dans l'onglet Paramètres (col3)
- Aide → petit widget dans la statusbar
- Pas de fullscreen button
- Col3 = onglets DXF / Paramètres / Raccourcis
"""

import os
import json
import sys
from contextlib import contextmanager
from PySide6.QtWidgets import (
    QMainWindow, QSplitter, QStatusBar, QMenu, QFileDialog,
    QMessageBox, QApplication, QLabel, QTabWidget, QTabBar,
    QPushButton, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QCheckBox, QLineEdit, QScrollArea, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QSizePolicy, QDialog, QTextEdit, QListWidget, QProgressBar
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut, QUndoStack, QColor

from src.core import affichage as affichage_ops
from src.core.tool_library import ToolLibrary, get_base_dir
from src.core.program_model import ProgramModel, OperationInstance
from src.codegen.generator import SimPlGenerator
from src.io.program_serializer import (
    ProgramSerializer, SubProgramSerializer, SimPlExporter
)
from src.gui.panels.operations_panel import OperationsPanel
from src.gui.panels.code_editor_panel import CodeEditorPanel
from src.gui.panels.dxf_editor_panel import DxfEditorPanel
from src.gui.panels.circle_ops_panel import CircleOpsPanel
from src.gui.dialogs.tool_manager_dialog import ToolManagerPanel
from src.gui.dialogs.program_browser_dialog import ProgramBrowserDialog
from src.gui.widgets import SpinCote, SpinEntier


# ──── Panneau Fichier inline (remplace col1) ────

class FileMenuPanel(QWidget):
    """Panneau de menu fichier affiché dans la colonne 1."""
    action_triggered = None  # Signal(str) — set dynamically
    close_requested = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        # Le contenu défile: vingt boutons de 34 px empilés
        # imposaient 832 px de hauteur MINIMALE à toute la fenêtre —
        # sur un écran de 768, elle passait derrière la barre des
        # tâches, et rien ne pouvait l'en sortir.
        externe = QVBoxLayout(self)
        externe.setContentsMargins(0, 0, 0, 0)
        cadre = QScrollArea()
        cadre.setWidgetResizable(True)
        cadre.setFrameShape(QFrame.Shape.NoFrame)
        cadre.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        contenu = QWidget()
        cadre.setWidget(contenu)
        externe.addWidget(cadre)
        layout = QVBoxLayout(contenu)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        title = QLabel("Fichier")
        title.setStyleSheet(
            "font-weight: bold; font-size: 16px; color: #f38ba8;")
        layout.addWidget(title)

        # Ligne d'état: quel fichier, enregistré quand, modifié ou
        # non. Il fallait le deviner jusqu'ici.
        self._etat_label = QLabel("")
        self._etat_label.setWordWrap(True)
        self._etat_label.setStyleSheet(
            "color: #a6adc8; font-size: 11px; padding: 2px 2px 6px 2px;")
        layout.addWidget(self._etat_label)

        # Trois groupes, dans l'ordre où l'on s'en sert. Les
        # sous-programmes NDS restent dans « + Opé »: c'est là qu'on
        # les cherche, au moment de composer.
        groupes = [
            ("Programme", [
                ("Nouveau", "new", "Ctrl+N", "new_file"),
                ("Ouvrir…", "open", "Ctrl+O", "open_file"),
                ("Parcourir les programmes…", "browse", "Ctrl+B",
                 "open_file"),
                ("Rouvrir un onglet fermé…", "reopen_tab", "",
                 "open_file"),
                ("Enregistrer", "save", "Ctrl+S", "save"),
                ("Enregistrer sous…", "save_as", "Ctrl+Shift+S",
                 "save"),
            ]),
            ("Échanges", [
                ("Exporter .SimPl…", "export", "Ctrl+E", "export"),
                ("Importer un .SimPl…", "import_simpl", "",
                 "open_file"),
                ("Importer un dessin…", "import_dessin", "", "dxf"),
                ("Exporter le dessin…", "export_dessin", "", "export"),
                ("Enregistrer un sous-programme…", "save_sub", "",
                 "save"),
                ("Importer un sous-programme…", "import_sub", "",
                 "open_file"),
            ]),
            ("Machine et modèles", [
                ("Sauver un template…", "save_template", "", "save"),
                ("Charger un template…", "load_template", "",
                 "open_file"),
                ("Exporter comme touche de fonction…", "function_key",
                 "", "export"),
                ("Module AutomaticPrograms…", "auto_programs", "",
                 "export"),
            ]),
        ]

        style_bouton = (
            "QPushButton { text-align: left; background: #181825; "
            "border: 1px solid #313244; border-radius: 4px; "
            "padding: 7px 12px; font-size: 13px; color: #cdd6f4; }"
            "QPushButton:hover { background: #313244; }")

        for titre_groupe, entrees in groupes:
            etiquette = QLabel(titre_groupe.upper())
            etiquette.setStyleSheet(
                "color: #f38ba8; font-size: 10px; font-weight: bold; "
                "padding: 8px 2px 2px 2px;")
            layout.addWidget(etiquette)
            for label, action_id, raccourci, icone in entrees:
                texte = label + (f"   {raccourci}" if raccourci else "")
                btn = QPushButton(texte)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                if icone:
                    from src.gui.icons import get_icon
                    btn.setIcon(get_icon(icone, 18))
                btn.setStyleSheet(style_bouton)
                btn.setMinimumHeight(34)
                btn.clicked.connect(
                    lambda _, a=action_id: self._on_action(a))
                layout.addWidget(btn)
            # Les récents suivent immédiatement « Programme »
            if titre_groupe == "Programme":
                self._recents_box = QWidget()
                self._recents_layout = QVBoxLayout(self._recents_box)
                self._recents_layout.setContentsMargins(0, 0, 0, 0)
                self._recents_layout.setSpacing(2)
                layout.addWidget(self._recents_box)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #45475a;")
        layout.addWidget(sep)
        quitter = QPushButton("Quitter")
        quitter.setCursor(Qt.CursorShape.PointingHandCursor)
        quitter.setStyleSheet(style_bouton)
        quitter.setMinimumHeight(34)
        quitter.clicked.connect(lambda: self._on_action('quit'))
        layout.addWidget(quitter)

        layout.addStretch()

    def montrer_etat(self, texte: str) -> None:
        """Ligne d'état du panneau: fichier, enregistrement, modifié."""
        if getattr(self, '_etat_label', None) is not None:
            self._etat_label.setText(texte)

    def montrer_recents(self, chemins: list) -> None:
        """Boutons des programmes récemment ouverts.

        C'est l'entrée la plus fréquente du menu, et elle manquait:
        on repassait par « Ouvrir » et l'explorateur à chaque fois."""
        import datetime
        import os
        boite = getattr(self, '_recents_layout', None)
        if boite is None:
            return
        while boite.count():
            item = boite.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for chemin in (chemins or [])[:5]:
            nom = os.path.basename(chemin)
            try:
                quand = datetime.datetime.fromtimestamp(
                    os.path.getmtime(chemin)).strftime("%d/%m %H:%M")
            except OSError:
                quand = "absent"
            btn = QPushButton(f"   {nom}")
            btn.setToolTip(f"{chemin}\nModifié le {quand}")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                "QPushButton { text-align: left; background: #11111b; "
                "border: 1px solid #313244; border-radius: 4px; "
                "padding: 4px 12px; font-size: 12px; color: #a6adc8; }"
                "QPushButton:hover { background: #313244; "
                "color: #cdd6f4; }")
            btn.setMinimumHeight(26)
            btn.setEnabled(os.path.exists(chemin))
            btn.clicked.connect(
                lambda _=False, c=chemin: self._on_recent(c))
            boite.addWidget(btn)

    def _on_recent(self, chemin: str) -> None:
        if hasattr(self, '_callback_recent') and self._callback_recent:
            self._callback_recent(chemin)

    def _on_action(self, action_id: str):
        """Émet le signal d'action."""
        # Le parent (OperationsPanel) gère la fermeture
        if hasattr(self, '_callback') and self._callback:
            self._callback(action_id)


# ──── Panneau Paramètres (onglet col3) ────

class _TroisColonnes:
    """Le `layout` des Paramètres: chaque groupe va dans SA colonne.

    Une pile de dix cadres dans la colonne étroite des opérations
    obligeait à défiler; sur toute la fenêtre, trois colonnes les
    montrent d'un coup. `addWidget` range par le titre du cadre, ce
    qui laisse la construction des cadres telle quelle."""

    def __init__(self, colonnes, plan):
        self._colonnes = colonnes
        self._plan = plan

    def addWidget(self, widget):
        titre = widget.title() if isinstance(widget, QGroupBox) else ""
        self._colonnes[self._plan.get(titre, 0)].addWidget(widget)

    def addStretch(self):
        for colonne in self._colonnes:
            colonne.addStretch()


class ParametersPanel(QScrollArea):
    """Les Paramètres: une page sur toute la fenêtre, trois colonnes.
    Contient les réglages projet + app, y compris expert-only."""

    #: où chaque cadre se range (colonne 0, 1 ou 2)
    _COLONNES = {
        "Projet": 0, "Brut (WorkpieceGeometry)": 0,
        "Chemins / Remplacement": 0, "Onglets fermés": 0,
        "Explorateur Windows": 0, "Données de l'utilisateur": 0,
        "Apparence": 1, "Outils par défaut": 1,
        "Défauts des formulaires": 1,
        "Paramètres Expert": 2, "Ordre du catalogue d'opérations": 2,
    }

    #: « Retour »: on quitte la page des Paramètres
    retour_demande = Signal()
    #: résumé des specs du programme (affiché au-dessus des opérations)
    program_specs_changed = Signal(str)
    #: bouton « ? » de la liste des matières: ouvrir/fermer la fiche
    material_help_requested = Signal()
    #: ordre des catégories du catalogue, changé par l'utilisateur
    categories_order_changed = Signal(list)

    def specs_summary(self) -> str:
        """Résumé d'une ligne des specs du programme courant."""
        s = self.program.settings
        dx = s.workpiece_max_x - s.workpiece_min_x
        dy = s.workpiece_max_y - s.workpiece_min_y
        dz = s.workpiece_max_z - s.workpiece_min_z
        parts = [f"Brut {dx:g} × {dy:g} × {dz:g}"]
        if s.author:
            parts.append(s.author)
        comment = (s.comment or "").strip().split('\n')[0]
        if comment:
            parts.append(comment[:44]
                         + ("…" if len(comment) > 44 else ""))
        return "  ·  ".join(parts)

    # Catégories d'opérations pour outils par défaut
    _TOOL_DEFAULT_CATEGORIES = [
        ("surfacage", "Surfaçage", ["surfacage_rectangle", "surfacage_cercle"]),
        ("taraudage", "Taraudage", ["taraudage", "taraudage_brut",
                                    "filetage_special"]),
        ("percage", "Perçage", ["percage_fraise", "percage_foret", "bpm"]),
        ("decoupe", "Découpe", ["decoupe_rectangle", "decoupe_cercle"]),
        ("poche", "Poche", ["poche_rectangle"]),
        ("helice", "Hélice", ["helice"]),
        ("gravure", "Gravure", ["gravure_texte"]),
    ]

    def __init__(self, program: ProgramModel, tool_library=None, parent=None):
        super().__init__(parent)
        self.program = program
        self.tool_library = tool_library
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._expert_mode = False
        # NEODRIVE_APP_SETTINGS: un autre fichier de réglages — la
        # suite de tests s'en sert pour ne jamais écrire dans celui
        # de l'utilisateur (elle y laissait une fenêtre de 640 × 480
        # et des programmes récents dans %TEMP%)
        self._settings_path = os.environ.get(
            'NEODRIVE_APP_SETTINGS') or os.path.join(
            get_base_dir(), 'data', 'app_settings.json')
        self._app_settings = self._load_app_settings()
        self._regler_chemins_machine()
        # Config des valeurs par défaut des formulaires (partagée avec
        # OperationsPanel via MainWindow après construction)
        from src.core.default_params import DefaultParamsConfig
        self._defaults_cfg = DefaultParamsConfig()
        self._defaults_widgets = {}
        self._defaults_loading = False
        self._setup_ui()

    def _rafraichir_explorateur(self):
        """L'état des associations, tel que le registre le dit."""
        try:
            from src.integrations import windows_shell
            etat = windows_shell.etat()
        except Exception:
            etat = "indisponible"
        self._explo_etat.setText(etat)
        self._explo_installer.setText(
            "Réinstaller" if etat.startswith("installé") else "Installer")
        self._explo_desinstaller.setEnabled(etat.startswith("installé"))

    def _explorateur(self, action: str):
        from src.integrations import windows_shell
        try:
            fait = (windows_shell.installer() if action == "installer"
                    else windows_shell.desinstaller())
        except Exception as exc:
            fait = False
            QMessageBox.warning(self, "Explorateur Windows",
                                f"Le registre a refusé:\n{exc}")
        if not fait:
            QMessageBox.warning(
                self, "Explorateur Windows",
                "Impossible d'écrire les associations de fichiers.")
        self._rafraichir_explorateur()

    def _load_app_settings(self) -> dict:
        """Charge les paramètres app depuis le fichier JSON."""
        defaults = {
            # le remplacement de chemin est un réglage du poste
            # (Paramètres): vide, les chemins partent tels quels
            'path_replace_from': '',
            'path_replace_to': '',
            'safe_z_height': 0.5,
            'default_programs_dir': '',
            'default_exports_dir': '',
            'default_dxf_dir': '',
            'last_simpl_export_dir': '',
            # Nb d'archives d'onglets fermés conservées:
            # 0 = pas d'archive, -1 = illimité
            'closed_tabs_keep': 10,
            # Limites machine (appliquées au code généré)
            'rpm_limit': 40000,   # Datron: 40k tr/min max
            'feed_limit': 0,      # 0 = pas de limite d'avance
            # Légende du canvas: citer aussi palpages, dialogues,
            # réglages ? Leur tracé reste dessiné dans tous les cas.
            'legend_hors_matiere': False,
            # Glissement des colonnes repliables, en ms. 0 = sec.
            'column_anim_ms': 180,
        }
        # Illisible, le fichier n'est pas écrasé au premier réglage
        # venu: mis de côté, sa sauvegarde .bak reprise si elle existe,
        # et la fenêtre le dit au démarrage.
        from src.core.fichiers_surs import lire_json_sur
        stored, self.alerte_reglages = lire_json_sur(self._settings_path)
        if isinstance(stored, dict):
            defaults.update(stored)
        return defaults

    def save_app_settings(self):
        """Sauvegarde les paramètres app."""
        try:
            from src.core.fichiers_surs import ecrire_json_sur
            ecrire_json_sur(self._settings_path, self._app_settings,
                            garder_bak=True, indent=2, ensure_ascii=False)
        except Exception as e:
            # Avertir UNE fois (pas de spam: appelé à chaque changement)
            if not getattr(self, '_save_warned', False):
                self._save_warned = True
                QMessageBox.warning(
                    self, "Paramètres",
                    f"Impossible de sauvegarder les paramètres:\n{e}\n\n"
                    "Les réglages de cette session seront perdus.")

    def set_expert_mode(self, enabled: bool):
        self._expert_mode = enabled
        # Afficher/masquer les groupes expert
        if hasattr(self, '_expert_group'):
            self._expert_group.setVisible(enabled)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.retour_demande.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def cadres_par_colonne(self) -> list:
        """Les titres des cadres, colonne par colonne — pour vérifier
        la page sans la regarder."""
        sortie = []
        for colonne in self._colonnes:
            titres = []
            for i in range(colonne.count()):
                widget = colonne.itemAt(i).widget()
                if isinstance(widget, QGroupBox):
                    titres.append(widget.title())
            sortie.append(titres)
        return sortie

    def _setup_ui(self):
        content = QWidget()
        page = QVBoxLayout(content)
        page.setSpacing(8)
        page.setContentsMargins(10, 8, 10, 8)

        # ── En-tête: le titre, le mode expert, et le retour ──
        entete = QHBoxLayout()
        title = QLabel("Paramètres")
        title.setStyleSheet(
            "font-weight: bold; font-size: 15px; color: #89b4fa;")
        entete.addWidget(title)
        entete.addSpacing(16)

        # ── Mode Expert: 1er paramètre, il conditionne tout le reste
        # (options avancées, opérations et champs réservés) ──
        self._expert_cb = QCheckBox("Mode Expert")
        self._expert_cb.setStyleSheet(
            "font-weight: bold; font-size: 13px;")
        self._expert_cb.setToolTip(
            "Dévoile les paramètres avancés, les opérations et les "
            "champs réservés aux réglages experts.")
        entete.addWidget(self._expert_cb)
        entete.addStretch()
        self._retour_btn = QPushButton("  Retour aux opérations  (Échap)")
        from src.gui.icons import get_button_icon
        self._retour_btn.setIcon(get_button_icon("up", 14))
        self._retour_btn.setToolTip(
            "Revenir aux trois colonnes. Les réglages sont déjà "
            "enregistrés.")
        self._retour_btn.clicked.connect(self.retour_demande.emit)
        entete.addWidget(self._retour_btn)
        page.addLayout(entete)

        # ── Trois colonnes, chacune avec ses cadres ──
        # Chaque colonne défile pour elle-même et prend le TIERS de
        # la largeur, quel que soit le cadre le plus large qu'elle
        # contient: laissée aux tailles naturelles, la première
        # mangeait la moitié de la page.
        rangee = QHBoxLayout()
        rangee.setSpacing(12)
        colonnes = []
        self._cadres_colonnes = []
        for _ in range(3):
            porteur = QWidget()
            colonne = QVBoxLayout(porteur)
            colonne.setSpacing(8)
            colonne.setContentsMargins(0, 0, 4, 0)
            cadre = QScrollArea()
            cadre.setWidget(porteur)
            cadre.setWidgetResizable(True)
            cadre.setFrameShape(QFrame.Shape.NoFrame)
            cadre.setHorizontalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            cadre.setSizePolicy(QSizePolicy.Policy.Ignored,
                                QSizePolicy.Policy.Expanding)
            cadre.setMinimumWidth(0)
            rangee.addWidget(cadre, stretch=1)
            colonnes.append(colonne)
            self._cadres_colonnes.append(cadre)
        page.addLayout(rangee, stretch=1)
        self._colonnes = colonnes
        layout = _TroisColonnes(colonnes, self._COLONNES)

        # ── Projet ──
        proj_group = QGroupBox("Projet")
        proj_form = QFormLayout()
        proj_form.setSpacing(4)

        self._author_edit = QLineEdit(self.program.settings.author)
        self._author_edit.editingFinished.connect(self._on_project_changed)
        proj_form.addRow("Auteur:", self._author_edit)

        self._comment_edit = QTextEdit()
        self._comment_edit.setPlainText(self.program.settings.comment)
        self._comment_edit.setMaximumHeight(60)
        self._comment_edit.setStyleSheet(
            "QTextEdit { font-size: 12px; background: #313244; "
            "color: #cdd6f4; border: 1px solid #45475a; border-radius: 4px; "
            "padding: 2px; }")
        self._comment_edit.textChanged.connect(self._on_project_changed)
        proj_form.addRow("Commentaire:", self._comment_edit)

        proj_group.setLayout(proj_form)
        layout.addWidget(proj_group)

        # ── Espace de travail (WorkpieceGeometry) ──
        # (octobre 2026: « Brut » ici était trompeur — c'est la zone de
        # travail déclarée à la machine; le brut a son propre cadre)
        wp_group = QGroupBox("Espace de travail (WorkpieceGeometry)")
        wp_form = QFormLayout()
        wp_form.setSpacing(4)

        # Templates de brut: combo + sauver/supprimer
        from PySide6.QtWidgets import QComboBox
        tpl_row = QHBoxLayout()
        tpl_row.setSpacing(2)
        self._wp_tpl_combo = QComboBox()
        self._wp_tpl_combo.setMaximumHeight(26)
        self._wp_tpl_combo.setToolTip(
            "Espaces de travail: sélectionner pour appliquer les "
            "dimensions au programme courant")
        self._reload_wp_templates()
        self._wp_tpl_combo.currentIndexChanged.connect(
            self._on_wp_template_selected)
        tpl_row.addWidget(self._wp_tpl_combo, stretch=1)
        from src.gui.icons import get_button_icon as _btn_icon
        tpl_save = QPushButton("")
        tpl_save.setIcon(_btn_icon("save", 15))
        tpl_save.setFixedSize(26, 26)
        tpl_save.setToolTip("Sauver l'espace de travail courant comme "
                            "template")
        tpl_save.clicked.connect(self._on_wp_template_save)
        tpl_row.addWidget(tpl_save)
        tpl_del = QPushButton("")
        tpl_del.setIcon(_btn_icon("delete", 15))
        tpl_del.setFixedSize(26, 26)
        tpl_del.setToolTip("Supprimer le template sélectionné")
        tpl_del.clicked.connect(self._on_wp_template_delete)
        tpl_row.addWidget(tpl_del)
        wp_form.addRow(tpl_row)

        self._wp_spins = {}
        fields = [
            ("min_x", "Min X", self.program.settings.workpiece_min_x),
            ("min_y", "Min Y", self.program.settings.workpiece_min_y),
            ("min_z", "Min Z", self.program.settings.workpiece_min_z),
            ("max_x", "Max X", self.program.settings.workpiece_max_x),
            ("max_y", "Max Y", self.program.settings.workpiece_max_y),
            ("max_z", "Max Z", self.program.settings.workpiece_max_z),
        ]
        for key, label, value in fields:
            spin = SpinCote()
            spin.setRange(-9999.0, 9999.0)
            spin.setDecimals(2)
            spin.setValue(value)
            spin.setMaximumWidth(80)
            spin.setMaximumHeight(26)
            spin.editingFinished.connect(self._on_project_changed)
            self._wp_spins[key] = spin
            wp_form.addRow(f"{label}:", spin)
        wp_group.setLayout(wp_form)
        layout.addWidget(wp_group)

        # ── Brut (la plaque à usiner) ──
        layout.addWidget(self._cadre_brut())

        # ── VectorDrive: NeoDrive, son post-processeur Datron ──
        layout.addWidget(self._cadre_vectordrive())

        # ── Chemins ──
        paths_group = QGroupBox("Chemins / Remplacement")
        paths_form = QFormLayout()
        paths_form.setSpacing(4)

        self._path_from = QLineEdit(
            self._app_settings.get('path_replace_from', ''))
        self._path_from.setToolTip(
            "Partie du chemin à remplacer dans les appels programme ext.")
        self._path_from.editingFinished.connect(self._on_app_settings_changed)
        paths_form.addRow("Remplacer:", self._path_from)

        self._path_to = QLineEdit(
            self._app_settings.get('path_replace_to', ''))
        self._path_to.setToolTip("Remplacement par...")
        self._path_to.editingFinished.connect(self._on_app_settings_changed)
        paths_form.addRow("Par:", self._path_to)

        self._prog_dir = QLineEdit(
            self._app_settings.get('default_programs_dir', ''))
        self._prog_dir.setPlaceholderText("(par défaut)")
        self._prog_dir.editingFinished.connect(self._on_app_settings_changed)
        paths_form.addRow("Dossier prog.:", self._prog_dir)

        self._export_dir = QLineEdit(
            self._app_settings.get('default_exports_dir', ''))
        self._export_dir.setPlaceholderText("(par défaut)")
        self._export_dir.editingFinished.connect(self._on_app_settings_changed)
        paths_form.addRow("Dossier export:", self._export_dir)

        self._dxf_dir_edit = QLineEdit(
            self._app_settings.get('default_dxf_dir', ''))
        self._dxf_dir_edit.setPlaceholderText("(exploré par défaut)")
        self._dxf_dir_edit.editingFinished.connect(
            self._on_app_settings_changed)
        paths_form.addRow("Dossier DXF:", self._dxf_dir_edit)

        paths_group.setLayout(paths_form)
        layout.addWidget(paths_group)

        # ── Bornes d'usinage (édition en lot) ──
        bornes_group = QGroupBox("Bornes d'usinage")
        bornes_form = QFormLayout()
        bornes_form.setSpacing(4)
        self._avance_max_spin = SpinCote()
        self._avance_max_spin.setMaximumWidth(90)
        self._avance_max_spin.setMaximumHeight(26)
        self._avance_max_spin.setRange(0.0, 100000.0)
        self._avance_max_spin.setDecimals(0)
        self._avance_max_spin.setValue(
            float(self._app_settings.get('avance_max', 0.0) or 0.0))
        self._avance_max_spin.setToolTip(
            "Avance maxi (mm/min) admise en édition en lot. 0 = pas de "
            "borne. Une avance saisie au-dessus est ramenée à cette "
            "valeur.")
        self._avance_max_spin.editingFinished.connect(
            self._on_app_settings_changed)
        bornes_form.addRow("Avance max (mm/min):", self._avance_max_spin)

        self._rpm_max_spin = SpinCote()
        self._rpm_max_spin.setMaximumWidth(90)
        self._rpm_max_spin.setMaximumHeight(26)
        self._rpm_max_spin.setRange(0.0, 100000.0)
        self._rpm_max_spin.setDecimals(0)
        self._rpm_max_spin.setValue(
            float(self._app_settings.get('rpm_max', 0.0) or 0.0))
        self._rpm_max_spin.setToolTip(
            "Régime maxi (tr/min) admis en édition en lot. 0 = pas de "
            "borne.")
        self._rpm_max_spin.editingFinished.connect(
            self._on_app_settings_changed)
        bornes_form.addRow("RPM max (tr/min):", self._rpm_max_spin)
        bornes_group.setLayout(bornes_form)
        layout.addWidget(bornes_group)

        # ── Onglets fermés ──
        tabs_group = QGroupBox("Onglets fermés")
        tabs_form = QFormLayout()
        tabs_form.setSpacing(4)
        self._closed_tabs_spin = SpinEntier()
        self._closed_tabs_spin.setMaximumWidth(80)
        self._closed_tabs_spin.setMaximumHeight(26)
        self._closed_tabs_spin.setRange(-1, 999)
        self._closed_tabs_spin.setSpecialValueText("Illimité")
        try:
            keep_val = int(self._app_settings.get('closed_tabs_keep', 10))
        except (TypeError, ValueError):
            keep_val = 10
        self._closed_tabs_spin.setValue(keep_val)
        self._closed_tabs_spin.setToolTip(
            "À la fermeture d'un onglet, le programme est archivé "
            "silencieusement dans programs/onglets_fermes/.\n"
            "0 = pas d'archive, -1 (Illimité) = tout conserver, "
            "sinon nombre d'archives conservées.")
        self._closed_tabs_spin.editingFinished.connect(
            self._on_app_settings_changed)
        tabs_form.addRow("Archives conservées:", self._closed_tabs_spin)
        tabs_group.setLayout(tabs_form)
        layout.addWidget(tabs_group)

        # ── Apparence ──
        from src.gui.theme import (
            THEME_NAMES, FONT_SIZES, get_current_theme,
            get_current_font_size)
        from src.gui.panels.operations_panel import NoScrollComboBox \
            as _NoScrollCombo
        appearance_group = QGroupBox("Apparence")
        appearance_form = QFormLayout()
        appearance_form.setSpacing(4)

        self._theme_combo = _NoScrollCombo()
        for name in THEME_NAMES:
            self._theme_combo.addItem(name)
        current = get_current_theme()
        idx = self._theme_combo.findText(current)
        if idx >= 0:
            self._theme_combo.setCurrentIndex(idx)
        # Signal connecté dans MainWindow._setup_ui()
        appearance_form.addRow("Thème:", self._theme_combo)

        self._font_combo = _NoScrollCombo()
        current_fs = get_current_font_size()
        for label, size in FONT_SIZES.items():
            self._font_combo.addItem(f"{label} ({size}px)", size)
            if size == current_fs:
                self._font_combo.setCurrentIndex(
                    self._font_combo.count() - 1)
        # Signal connecté dans MainWindow._setup_ui()
        appearance_form.addRow("Police:", self._font_combo)

        # Épaisseur des traits du canvas, en PIXELS: constante quel
        # que soit le zoom (pinceaux cosmétiques)
        self._line_width_spin = SpinCote()
        self._line_width_spin.setRange(0.5, 6.0)
        self._line_width_spin.setSingleStep(0.5)
        self._line_width_spin.setDecimals(1)
        self._line_width_spin.setMaximumWidth(80)
        self._line_width_spin.setMaximumHeight(26)
        self._line_width_spin.setValue(
            float(self._app_settings.get('canvas_line_width', 1.0)))
        self._line_width_spin.setToolTip(
            "Épaisseur des traits du canvas en pixels.\n"
            "Constante quel que soit le zoom (tracé vectoriel).")
        self._line_width_spin.valueChanged.connect(
            self._on_line_width_changed)
        appearance_form.addRow("Traits canvas (px):",
                               self._line_width_spin)

        # Fond du PNG embarqué dans le SimPl: blanc, le dessin blanc
        # du canvas devenait invisible sur l'écran de la machine
        from src.gui.panels.operations_panel import NoScrollComboBox as _Combo
        self._png_bg_combo = _Combo()
        self._png_bg_combo.setMaximumWidth(140)
        self._png_bg_combo.setMaximumHeight(26)
        for etiquette, valeur in (
                ("Gris", "#b8b8b8"),
                ("Gris clair", "#d8d8d8"),
                ("Gris foncé", "#808080"),
                ("Blanc", "#ffffff"),
                ("Noir", "#1e1e2e")):
            self._png_bg_combo.addItem(etiquette, valeur)
        courant = str(self._app_settings.get('png_background', '#b8b8b8'))
        idx = self._png_bg_combo.findData(courant)
        self._png_bg_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._png_bg_combo.setToolTip(
            "Fond de l'image PNG jointe au programme (@image:).\n"
            "Un dessin clair disparaissait sur fond blanc.")
        self._png_bg_combo.currentIndexChanged.connect(
            self._on_app_settings_changed)
        appearance_form.addRow("Fond du PNG:", self._png_bg_combo)

        # Ce qui part avec le programme exporté: le dessin 2D (DXF du
        # Canva + PNG) ou la pièce 3D (STL de la pièce usinée simulée +
        # PNG de la vue 3D)
        self._export_dessin_combo = _Combo()
        self._export_dessin_combo.setMaximumWidth(220)
        self._export_dessin_combo.setMaximumHeight(26)
        for etiquette, valeur in self.EXPORT_DESSIN:
            self._export_dessin_combo.addItem(etiquette, valeur)
        courant = str(self._app_settings.get('export_dessin', 'aucun'))
        idx = self._export_dessin_combo.findData(courant)
        self._export_dessin_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._export_dessin_combo.setToolTip(
            "À l'export du programme, écrit à côté du .SimPl:\n"
            "2D: le DXF du Canva 2D (dessin + parcours) et son PNG;\n"
            "3D: le STL de la pièce usinée simulée et le PNG de la vue "
            "3D.\nLe PNG est aussi l'aperçu du programme (@image:) "
            "quand il est demandé.")
        self._export_dessin_combo.currentIndexChanged.connect(
            self._on_app_settings_changed)
        appearance_form.addRow("Dessin joint à l'export:",
                               self._export_dessin_combo)

        # L'image que la machine montre du programme (@image:): le plan
        # 2D, la pièce usinée en 3D, ou les deux côte à côte
        self._visu_combo = _Combo()
        self._visu_combo.setMaximumWidth(220)
        self._visu_combo.setMaximumHeight(26)
        for etiquette, valeur in self.VISU_MACHINE:
            self._visu_combo.addItem(etiquette, valeur)
        courant = str(self._app_settings.get('visu_machine', '2d'))
        idx = self._visu_combo.findData(courant)
        self._visu_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._visu_combo.setToolTip(
            "Le PNG écrit à côté du .SimPl à l'export — l'aperçu "
            "(@image:) que la machine montre, et celui du dessin "
            "joint:\n2D: le plan du Canva; 3D: la pièce usinée simulée,"
            " en vue iso; les deux: une image, le plan à gauche, la "
            "pièce à droite.")
        self._visu_combo.currentIndexChanged.connect(
            self._on_app_settings_changed)
        self._reglages_png_btn = QPushButton("Réglages…")
        self._reglages_png_btn.setToolTip(
            "Ce que l'image montre en 2D et en 3D (calques, matière et son "
            "opacité, couleurs, vue du Canva ou vue type), sa taille, son "
            "fond — avec un aperçu")
        # PAS `connect(self.editer_reglages_png)`: Qt y glisse `checked`
        # (False) — dans `executer`, et la fenêtre ne s'ouvrait jamais
        self._reglages_png_btn.clicked.connect(
            lambda: self.editer_reglages_png())
        ligne_png = QHBoxLayout()
        ligne_png.setContentsMargins(0, 0, 0, 0)
        ligne_png.addWidget(self._visu_combo)
        ligne_png.addWidget(self._reglages_png_btn)
        ligne_png.addStretch()
        appearance_form.addRow("PNG du programme (export):", ligne_png)

        # Le Canva 3D suit le programme à chaque changement, ou attend
        # qu'on le lui demande (un programme lourd: 48 filetages,
        # matière cochée, se recalculait à chaque retouche)
        self._calculs_3d_combo = _Combo()
        self._calculs_3d_combo.setMaximumWidth(220)
        self._calculs_3d_combo.setMaximumHeight(26)
        for etiquette, valeur in self.CALCULS_3D:
            self._calculs_3d_combo.addItem(etiquette, valeur)
        courant = str(self._app_settings.get('calculs_3d', 'temps_reel'))
        idx = self._calculs_3d_combo.findData(courant)
        self._calculs_3d_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._calculs_3d_combo.setToolTip(
            "En temps réel: le Canva 3D (parcours simulé, matière) se "
            "recalcule à chaque changement du programme.\nSur demande: "
            "il attend le bouton « Calculer » de sa barre.")
        self._calculs_3d_combo.currentIndexChanged.connect(
            self._on_app_settings_changed)
        appearance_form.addRow("Calculs 3D:", self._calculs_3d_combo)

        # Légende du canvas: ce qui ne coupe pas (palpage, dialogue,
        # réglage) n'y figure pas — sauf demande
        self._legend_hm_cb = QCheckBox()
        self._legend_hm_cb.setChecked(
            bool(self._app_settings.get('legend_hors_matiere', False)))
        self._legend_hm_cb.setToolTip(
            "Coché, la légende cite aussi les opérations hors matière "
            "(palpage, retournement, dialogue, décalage d'origine).\n"
            "Leur tracé reste dessiné dans tous les cas.")
        self._legend_hm_cb.toggled.connect(self._on_app_settings_changed)
        appearance_form.addRow("Légende: hors matière aussi:",
                               self._legend_hm_cb)

        # Colonnes repliables: la durée du glissement
        self._col_anim_spin = SpinEntier()
        self._col_anim_spin.setRange(0, 2000)
        self._col_anim_spin.setSingleStep(20)
        self._col_anim_spin.setMaximumWidth(80)
        self._col_anim_spin.setMaximumHeight(26)
        self._col_anim_spin.setValue(
            int(self._app_settings.get('column_anim_ms', 180)))
        self._col_anim_spin.setToolTip(
            "Durée du glissement quand une colonne se replie ou se "
            "déplie (Ctrl+1, Ctrl+2, Ctrl+3).\n"
            "0 = bascule sèche, sans animation.")
        self._col_anim_spin.editingFinished.connect(
            self._on_app_settings_changed)
        appearance_form.addRow("Colonnes: glissement (ms):",
                               self._col_anim_spin)

        appearance_group.setLayout(appearance_form)
        layout.addWidget(appearance_group)

        # ── Explorateur Windows: « Ouvrir avec NeoDrive » ──
        # Tout dans la ruche de l'utilisateur, sans droits
        # d'administrateur; ça se retire aussi net que ça s'installe.
        explorateur = QGroupBox("Explorateur Windows")
        explo_form = QFormLayout()
        explo_form.setSpacing(4)
        self._explo_etat = QLabel()
        self._explo_etat.setWordWrap(True)
        explo_form.addRow("Clic droit « Ouvrir avec NeoDrive »:",
                          self._explo_etat)
        boutons = QHBoxLayout()
        self._explo_installer = QPushButton("Installer")
        self._explo_installer.setMaximumHeight(24)
        self._explo_installer.setToolTip(
            "Ajoute « Ouvrir avec NeoDrive » au clic droit des "
            ".ndp, .nds et .SimPl, et ouvre les .ndp/.nds au "
            "double-clic.\nUn .SimPl garde son application "
            "habituelle: NeoDrive n'est qu'une entrée du menu.")
        self._explo_installer.clicked.connect(
            lambda: self._explorateur("installer"))
        self._explo_desinstaller = QPushButton("Désinstaller")
        self._explo_desinstaller.setMaximumHeight(24)
        self._explo_desinstaller.clicked.connect(
            lambda: self._explorateur("desinstaller"))
        boutons.addWidget(self._explo_installer)
        boutons.addWidget(self._explo_desinstaller)
        boutons.addStretch(1)
        explo_form.addRow("", boutons)
        explorateur.setLayout(explo_form)
        layout.addWidget(explorateur)
        self._rafraichir_explorateur()

        # ── Les données de l'utilisateur: en un .zip, et retour ──
        donnees = QGroupBox("Données de l'utilisateur")
        donnees_v = QVBoxLayout()
        donnees_v.setSpacing(4)
        aide = QLabel("Outils, réglages, défauts des formulaires, "
                      "favoris, modèles de gamme, gabarits de brut, "
                      "matières, raccourcis: tout ce que vous réglez "
                      "ici, en un fichier — pour un autre poste, une "
                      "sauvegarde, un collègue.")
        aide.setWordWrap(True)
        aide.setStyleSheet("color: #a6adc8; font-size: 10px;")
        donnees_v.addWidget(aide)
        boutons = QHBoxLayout()
        self._donnees_exporter = QPushButton("Exporter…")
        self._donnees_exporter.setMaximumHeight(24)
        self._donnees_exporter.clicked.connect(self._exporter_donnees)
        self._donnees_importer = QPushButton("Importer…")
        self._donnees_importer.setMaximumHeight(24)
        self._donnees_importer.clicked.connect(self._importer_donnees)
        boutons.addWidget(self._donnees_exporter)
        boutons.addWidget(self._donnees_importer)
        boutons.addStretch(1)
        donnees_v.addLayout(boutons)
        donnees.setLayout(donnees_v)
        layout.addWidget(donnees)

        # ── Paramètres Expert-only ──
        self._expert_group = QGroupBox("Paramètres Expert")
        expert_form = QFormLayout()
        expert_form.setSpacing(4)

        self._safe_z_spin = SpinCote()
        self._safe_z_spin.setMaximumWidth(80)
        self._safe_z_spin.setMaximumHeight(26)
        self._safe_z_spin.setRange(0.1, 50.0)
        self._safe_z_spin.setDecimals(1)
        self._safe_z_spin.setValue(
            self._app_settings.get('safe_z_height', 0.5))
        self._safe_z_spin.editingFinished.connect(
            self._on_app_settings_changed)
        expert_form.addRow("SafeZHeightForWorkpiece:", self._safe_z_spin)

        self._smoothing_cb = QCheckBox()
        self._smoothing_cb.setChecked(
            self._app_settings.get('smoothing', False))
        self._smoothing_cb.toggled.connect(self._on_app_settings_changed)
        expert_form.addRow("Smoothing On:", self._smoothing_cb)

        self._smoothing_deviation = SpinCote()
        self._smoothing_deviation.setMaximumWidth(80)
        self._smoothing_deviation.setMaximumHeight(26)
        self._smoothing_deviation.setRange(0.0001, 1.0)
        self._smoothing_deviation.setDecimals(4)
        self._smoothing_deviation.setValue(
            self._app_settings.get('smoothing_deviation', 0.0025))
        self._smoothing_deviation.setToolTip(
            "allowedDeviation pour Smoothing On (défaut: 0.0025)")
        self._smoothing_deviation.editingFinished.connect(
            self._on_app_settings_changed)
        expert_form.addRow("  allowedDeviation:", self._smoothing_deviation)
        # les deux angles du lissage (manuel DATRON: 0,1 et 110° par défaut);
        # 0: non écrits, la machine garde les siens
        for attr, cle, nom, maxi, bulle in (
                ('_smoothing_angle', 'smoothing_angle',
                 "allowedDeviationAngle", 10.0,
                 "Écart angulaire toléré au lissage (°; défaut machine "
                 "0,1). 0: non écrit"),
                ('_smoothing_kink', 'smoothing_kink', "allowedKinkAngle",
                 180.0, "Au-delà de cet angle, un coin reste vif (°; "
                 "défaut machine 110). 0: non écrit")):
            spin = SpinCote()
            spin.setMaximumWidth(80)
            spin.setMaximumHeight(26)
            spin.setRange(0.0, maxi)
            spin.setDecimals(3)
            spin.setValue(float(self._app_settings.get(cle, 0.0) or 0.0))
            spin.setToolTip(bulle)
            spin.editingFinished.connect(self._on_app_settings_changed)
            setattr(self, attr, spin)
            expert_form.addRow(f"  {nom}:", spin)

        self._dynamic_spin = SpinCote()
        self._dynamic_spin.setMaximumWidth(80)
        self._dynamic_spin.setMaximumHeight(26)
        self._dynamic_spin.setRange(0, 10)
        self._dynamic_spin.setDecimals(0)
        self._dynamic_spin.setValue(
            self._app_settings.get('dynamic', 0))
        self._dynamic_spin.setToolTip(
            "0 = désactivé. Valeur Dynamic= insérée dans chaque "
            "sous-programme (ex: Dynamic=2)")
        self._dynamic_spin.editingFinished.connect(
            self._on_app_settings_changed)
        expert_form.addRow("Dynamic:", self._dynamic_spin)

        # strokeRapidZ / strokeCuttingZ
        self._stroke_rapid_z_spin = SpinCote()
        self._stroke_rapid_z_spin.setMaximumWidth(80)
        self._stroke_rapid_z_spin.setMaximumHeight(26)
        self._stroke_rapid_z_spin.setRange(1, 100)
        self._stroke_rapid_z_spin.setDecimals(0)
        self._stroke_rapid_z_spin.setValue(
            self._app_settings.get('stroke_rapid_z', 15))
        self._stroke_rapid_z_spin.editingFinished.connect(
            self._on_stroke_z_changed)
        expert_form.addRow("strokeRapidZ:", self._stroke_rapid_z_spin)

        self._stroke_cutting_z_spin = SpinCote()
        self._stroke_cutting_z_spin.setMaximumWidth(80)
        self._stroke_cutting_z_spin.setMaximumHeight(26)
        self._stroke_cutting_z_spin.setRange(0.1, 50)
        self._stroke_cutting_z_spin.setDecimals(0)
        self._stroke_cutting_z_spin.setValue(
            self._app_settings.get('stroke_cutting_z', 1))
        self._stroke_cutting_z_spin.editingFinished.connect(
            self._on_stroke_z_changed)
        expert_form.addRow("strokeCuttingZ:", self._stroke_cutting_z_spin)

        # SafeRapid Z = somme (auto-calculé, affiché)
        self._safe_rapid_z_label = QLabel(
            f"SafeRapid Z = {int(self._stroke_rapid_z_spin.value() + self._stroke_cutting_z_spin.value())}")
        self._safe_rapid_z_label.setStyleSheet(
            "color: #a6e3a1; font-weight: bold; font-size: 12px;")
        expert_form.addRow("", self._safe_rapid_z_label)

        # Groupage automatique des taraudages consécutifs
        self._auto_group_cb = QCheckBox(
            "Grouper les taraudages consécutifs")
        self._auto_group_cb.setChecked(
            bool(self._app_settings.get('auto_group', True)))
        self._auto_group_cb.setToolTip(
            "Réunit automatiquement les taraudages consécutifs de même "
            "outil dans un seul sous-programme.\nDécocher pour ne "
            "garder que les groupes NOMMÉS (champ « Groupe » du "
            "formulaire d'opération).")
        self._auto_group_cb.toggled.connect(self._on_app_settings_changed)
        expert_form.addRow("Groupage auto:", self._auto_group_cb)

        # Limites machine
        self._rpm_limit_spin = SpinCote()
        self._rpm_limit_spin.setMaximumWidth(80)
        self._rpm_limit_spin.setMaximumHeight(26)
        self._rpm_limit_spin.setRange(0, 100000)
        self._rpm_limit_spin.setDecimals(0)
        self._rpm_limit_spin.setValue(
            self._app_settings.get('rpm_limit', 40000))
        self._rpm_limit_spin.setToolTip(
            "RPM maximum machine (Datron: 40000). Les RPM du code "
            "généré sont plafonnés à cette valeur. 0 = désactivé.")
        self._rpm_limit_spin.editingFinished.connect(
            self._on_app_settings_changed)
        expert_form.addRow("RPM max machine:", self._rpm_limit_spin)

        self._feed_limit_spin = SpinCote()
        self._feed_limit_spin.setMaximumWidth(80)
        self._feed_limit_spin.setMaximumHeight(26)
        self._feed_limit_spin.setRange(0, 50000)
        self._feed_limit_spin.setDecimals(0)
        self._feed_limit_spin.setValue(
            self._app_settings.get('feed_limit', 0))
        self._feed_limit_spin.setToolTip(
            "Avance maximum (mm/min) plafonnant les SetFeedTechnology "
            "du code généré. 0 = pas de limite.")
        self._feed_limit_spin.editingFinished.connect(
            self._on_app_settings_changed)
        expert_form.addRow("Avance max (mm/min):", self._feed_limit_spin)

        # Matériau
        from src.core.materials import MaterialsLibrary
        self._materials_lib = MaterialsLibrary()
        from src.gui.panels.operations_panel import NoScrollComboBox
        self._material_combo = NoScrollComboBox()
        self._material_combo.addItem("-- Aucun (avances de la bibliothèque) --", "")
        for mat in self._materials_lib.get_all():
            label = f"{mat.name} (×{mat.feed_multiplier} feed, ×{mat.rpm_multiplier} rpm)"
            self._material_combo.addItem(label, mat.id)
        saved_mat = self._app_settings.get('material', '')
        if saved_mat:
            idx = self._material_combo.findData(saved_mat)
            if idx >= 0:
                self._material_combo.setCurrentIndex(idx)
        self._material_combo.currentIndexChanged.connect(
            self._on_app_settings_changed)
        # La fiche des matières tenait un onglet entier de la colonne
        # 2 pour être consultée deux fois par mois: elle s'ouvre
        # maintenant depuis ce bouton, à côté du choix qu'elle éclaire
        from src.gui.icons import get_button_icon
        mat_row = QWidget()
        mat_lay = QHBoxLayout(mat_row)
        mat_lay.setContentsMargins(0, 0, 0, 0)
        mat_lay.setSpacing(4)
        mat_lay.addWidget(self._material_combo, 1)
        self._material_help_btn = QPushButton("")
        self._material_help_btn.setIcon(get_button_icon("help", 15))
        self._material_help_btn.setFixedSize(24, 24)
        self._material_help_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._material_help_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._material_help_btn.setToolTip(
            "Fiche des matières: régimes, avances et multiplicateurs "
            "appliqués")
        self._material_help_btn.clicked.connect(
            self.material_help_requested.emit)
        mat_lay.addWidget(self._material_help_btn)
        expert_form.addRow("Matériau:", mat_row)

        # Multiplicateurs feed/rpm éditables
        self._feed_mult_spin = SpinCote()
        self._feed_mult_spin.setMaximumWidth(80)
        self._feed_mult_spin.setMaximumHeight(26)
        self._feed_mult_spin.setRange(0.1, 5.0)
        self._feed_mult_spin.setDecimals(2)
        self._feed_mult_spin.setValue(
            self._app_settings.get('feed_multiplier', 1.0))
        self._feed_mult_spin.setToolTip(
            "Multiplicateur d'avance global (×1.0 = avances de la bibliothèque)")
        self._feed_mult_spin.editingFinished.connect(
            self._on_app_settings_changed)
        expert_form.addRow("Mult. avance:", self._feed_mult_spin)

        self._rpm_mult_spin = SpinCote()
        self._rpm_mult_spin.setMaximumWidth(80)
        self._rpm_mult_spin.setMaximumHeight(26)
        self._rpm_mult_spin.setRange(0.1, 5.0)
        self._rpm_mult_spin.setDecimals(2)
        self._rpm_mult_spin.setValue(
            self._app_settings.get('rpm_multiplier', 1.0))
        self._rpm_mult_spin.setToolTip(
            "Multiplicateur RPM global (×1.0 = régimes de la bibliothèque)")
        self._rpm_mult_spin.editingFinished.connect(
            self._on_app_settings_changed)
        expert_form.addRow("Mult. RPM:", self._rpm_mult_spin)

        # ── Enrichissements issus de la documentation Datron ──
        # TOUS désactivés par défaut: ils modifient le programme
        # généré, l'utilisateur doit les activer en connaissance.
        sep_doc = QLabel("— Format Datron (optionnel) —")
        sep_doc.setStyleSheet(
            "color: #6c7086; font-size: 10px; padding-top: 6px;")
        expert_form.addRow(sep_doc)

        self._datron_checks = {}
        for key, label, tip in (
            ('emit_tool_descriptions', "Déclarations d'outils",
             "Ajoute les annotations @ ToolDescription @ de tous les "
             "outils employés: nom, article, fabricant, et ce que la "
             "fiche sait (Ø, angle, longueur de coupe…).\nC'est la "
             "liste à vérifier au magasin, devant la machine; elle "
             "sert aussi à la simulation."),
            ('emit_workpiece_comments', "Cotes du brut en commentaire",
             "Ajoute min / max / Part size en clair avant "
             "@ WorkpieceGeometry @, comme les fichiers Datron."),
            ('emit_op_stats', "Temps et ZMIN par opération",
             "Ajoute « # Operation Time: … » et « # ZMIN = … » avant "
             "chaque sous-programme."),
            ('emit_op_doc', "Annotations @doc: des sous-programmes",
             "Ajoute une ligne @doc: décrivant chaque sous-programme "
             "(nom, type, outil) — affichée comme aide dans l'éditeur "
             "de la machine."),
            ('embed_canvas_preview', "Aperçu du dessin (@image:)",
             "À l'export, enregistre un PNG du canvas à côté du "
             ".SimPl et l'affiche dans le programme:\nl'opérateur "
             "voit la pièce directement dans l'éditeur machine.\n"
             "Pensez à copier le PNG avec le programme."),
        ):
            cb = QCheckBox(label)
            # les déclarations d'outils sortent par défaut: c'est la
            # liste du magasin
            cb.setChecked(bool(self._app_settings.get(
                key, key == 'emit_tool_descriptions')))
            cb.setToolTip(tip)
            cb.toggled.connect(self._on_app_settings_changed)
            self._datron_checks[key] = cb
            expert_form.addRow("", cb)

        self._library_module_cb = QCheckBox(
            "Programme bibliothèque (masqué opérateur)")
        self._library_module_cb.setToolTip(
            "Émet @ UserVisible = false @: le programme n'apparaît "
            "plus dans la liste de la machine.\nÀ réserver aux "
            "programmes APPELÉS par un autre (usermodule, Pattern).")
        self._library_module_cb.setChecked(
            bool(getattr(self.program.settings, 'library_module',
                         False)))
        self._library_module_cb.toggled.connect(
            self._on_project_changed)
        expert_form.addRow("", self._library_module_cb)

        self._expert_group.setLayout(expert_form)
        self._expert_group.setVisible(self._expert_mode)
        layout.addWidget(self._expert_group)

        # ── Outils par défaut ──
        if self.tool_library:
            tools_group = QGroupBox("Outils par défaut")
            tools_form = QFormLayout()
            tools_form.setSpacing(4)
            self._default_tool_combos = {}
            all_tools = self.tool_library.get_all_tools()
            for cat_key, cat_label, _op_types in self._TOOL_DEFAULT_CATEGORIES:
                from src.gui.panels.operations_panel import NoScrollComboBox \
                    as _TCB
                combo = _TCB()
                combo.addItem("(auto)", "")
                for tool in all_tools:
                    combo.addItem(
                        f"{tool.name} [{tool.article_nr}]",
                        tool.article_nr)
                saved = self._app_settings.get(
                    f'default_tool_{cat_key}', '')
                if saved:
                    idx = combo.findData(saved)
                    if idx >= 0:
                        combo.setCurrentIndex(idx)
                combo.currentIndexChanged.connect(
                    self._on_default_tool_changed)
                self._default_tool_combos[cat_key] = combo
                tools_form.addRow(f"{cat_label}:", combo)
            tools_group.setLayout(tools_form)
            layout.addWidget(tools_group)

        # ── Défauts des formulaires (par opération) ──
        from src.operations.registry import OperationRegistry
        defaults_group = QGroupBox("Défauts des formulaires")
        dv = QVBoxLayout()
        dv.setSpacing(4)

        info_lbl = QLabel(
            "Valeurs pré-remplies à la création d'une opération.")
        info_lbl.setStyleSheet("color: #a6adc8; font-size: 11px;")
        info_lbl.setWordWrap(True)
        dv.addWidget(info_lbl)

        from src.gui.panels.operations_panel import NoScrollComboBox \
            as _DefCombo
        self._defaults_op_combo = _DefCombo()
        for item in OperationRegistry.get_display_list():
            self._defaults_op_combo.addItem(item['name'], item['type'])
        self._defaults_op_combo.currentIndexChanged.connect(
            self._rebuild_defaults_form)
        dv.addWidget(self._defaults_op_combo)

        self._defaults_form_host = QWidget()
        self._defaults_form = QFormLayout(self._defaults_form_host)
        self._defaults_form.setSpacing(3)
        self._defaults_form.setContentsMargins(0, 0, 0, 0)
        dv.addWidget(self._defaults_form_host)

        reset_btn = QPushButton("Réinitialiser cette opération")
        reset_btn.setToolTip(
            "Supprime les valeurs personnalisées et revient aux "
            "défauts du code pour l'opération sélectionnée.")
        reset_btn.clicked.connect(self._reset_defaults_form)
        dv.addWidget(reset_btn)

        defaults_group.setLayout(dv)
        layout.addWidget(defaults_group)
        self._rebuild_defaults_form()

        layout.addWidget(self._build_ordre_catalogue())

        layout.addStretch()
        self.setWidget(content)

    # ── Ordre du catalogue d'opérations ──

    def _build_ordre_catalogue(self):
        """Ordre des CATÉGORIES dans le panneau « + Opé ».

        L'atelier ne travaille pas dans l'ordre du code: celui qui
        perce toute la journée veut le perçage en haut."""
        from PySide6.QtWidgets import (QGroupBox, QListWidget,
                                       QListWidgetItem, QVBoxLayout,
                                       QHBoxLayout, QPushButton,
                                       QAbstractItemView, QLabel)
        groupe = QGroupBox("Ordre du catalogue d'opérations")
        v = QVBoxLayout()
        v.setSpacing(4)

        aide = QLabel("Glissez les catégories pour changer l'ordre "
                      "du panneau « + Opé ».")
        aide.setWordWrap(True)
        aide.setStyleSheet("color: #a6adc8; font-size: 10px;")
        v.addWidget(aide)

        self._ordre_liste = QListWidget()
        self._ordre_liste.setDragDropMode(
            QAbstractItemView.DragDropMode.InternalMove)
        self._ordre_liste.setMaximumHeight(190)
        self._ordre_liste.setStyleSheet(
            "QListWidget { background: #181825; color: #cdd6f4; "
            "border: 1px solid #45475a; border-radius: 4px; "
            "font-size: 12px; }")
        for nom in self.ordre_categories():
            self._ordre_liste.addItem(QListWidgetItem(nom))
        self._ordre_liste.model().rowsMoved.connect(
            self._on_ordre_categories_change)
        v.addWidget(self._ordre_liste)

        ligne = QHBoxLayout()
        defaut = QPushButton("Ordre d'origine")
        defaut.setToolTip("Revient à l'ordre livré avec NeoDrive")
        defaut.clicked.connect(self._reset_ordre_categories)
        ligne.addWidget(defaut)
        ligne.addStretch()
        v.addLayout(ligne)

        groupe.setLayout(v)
        return groupe

    # ── les données de l'utilisateur ──

    def _exporter_donnees(self):
        from src.core import donnees_utilisateur as du
        from datetime import datetime
        base = os.path.join(
            os.path.expanduser("~"),
            f"NeoDrive donnees {datetime.now():%Y%m%d}.zip")
        chemin, _f = QFileDialog.getSaveFileName(
            self, "Exporter les données de l'utilisateur", base,
            "Archive (*.zip)")
        if not chemin:
            return
        if not chemin.lower().endswith('.zip'):
            chemin += '.zip'
        try:
            fichiers = du.exporter(chemin)
        except OSError as exc:
            QMessageBox.warning(self, "Exporter",
                                f"Impossible d'écrire l'archive:\n{exc}")
            return
        QMessageBox.information(
            self, "Exporter",
            f"{len(fichiers)} fichier(s) emporté(s) dans\n{chemin}:\n"
            + ", ".join(fichiers))

    def _importer_donnees(self):
        from src.core import donnees_utilisateur as du
        chemin, _f = QFileDialog.getOpenFileName(
            self, "Importer les données de l'utilisateur", "",
            "Archive (*.zip)")
        if not chemin:
            return
        try:
            info = du.contenu(chemin)
        except (OSError, ValueError, KeyError) as exc:
            QMessageBox.warning(self, "Importer",
                                f"Archive inutilisable:\n{exc}")
            return
        quand = f" (du {info['date'][:10]})" if info.get('date') else ""
        reponse = QMessageBox.question(
            self, "Importer",
            f"Remplacer vos données par celles de l'archive{quand} ?\n\n"
            + ", ".join(info['fichiers'])
            + "\n\nLes fichiers actuels sont d'abord copiés dans "
            "data/sauvegardes/.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reponse != QMessageBox.StandardButton.Yes:
            return
        try:
            fait = du.importer(chemin)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Importer",
                                f"Import interrompu:\n{exc}")
            return
        self.appliquer_donnees_importees(fait['fichiers'])
        QMessageBox.information(
            self, "Importer",
            f"{len(fait['fichiers'])} fichier(s) importé(s); les anciens "
            f"sont dans\n{fait['sauvegarde']}\n\nCertains réglages "
            "(thème, fenêtre) ne prennent effet qu'au prochain "
            "démarrage.")

    def appliquer_donnees_importees(self, fichiers) -> None:
        """Ce qui peut se recharger à chaud: la bibliothèque d'outils,
        les réglages, les défauts des formulaires."""
        fenetre = self.window()
        if 'tools.json' in fichiers:
            try:
                fenetre.tool_library.load()
            except Exception:
                pass
        if 'app_settings.json' in fichiers:
            try:
                self._app_settings = self._load_app_settings()
                self._regler_chemins_machine()
            except Exception:
                pass
        panneau = getattr(fenetre, 'operations_panel', None)
        if panneau is not None:
            try:
                panneau._rebuild_add_panel()
            except Exception:
                pass
            if 'default_params.json' in fichiers:
                try:
                    panneau._default_params.load()
                except Exception:
                    pass

    def ordre_categories(self) -> list:
        """Ordre courant des catégories, complété des nouvelles."""
        from src.gui.panels.operations_panel import CAT_ORDER
        from src.operations.registry import OperationRegistry
        connues = list(OperationRegistry.get_by_category().keys())
        enregistre = self._app_settings.get('categories_order', [])
        ordre = [c for c in enregistre if c in connues]
        # une catégorie neuve se range à sa place d'origine
        for cat in CAT_ORDER + sorted(connues):
            if cat in connues and cat not in ordre:
                ordre.append(cat)
        return ordre

    def _on_ordre_categories_change(self, *_args):
        noms = [self._ordre_liste.item(i).text()
                for i in range(self._ordre_liste.count())]
        self._app_settings['categories_order'] = noms
        self.save_app_settings()
        self.categories_order_changed.emit(noms)

    def rafraichir_ordre_categories(self) -> None:
        """La liste des catégories relit les réglages (changés depuis
        le catalogue « + Opé »), sans rien émettre."""
        liste = getattr(self, '_ordre_liste', None)
        if liste is None:
            return
        liste.blockSignals(True)
        try:
            liste.clear()
            for nom in self.ordre_categories():
                liste.addItem(nom)
        finally:
            liste.blockSignals(False)

    def _reset_ordre_categories(self):
        self._app_settings['categories_order'] = []
        self.save_app_settings()
        self._ordre_liste.clear()
        for nom in self.ordre_categories():
            self._ordre_liste.addItem(nom)
        self.categories_order_changed.emit(self.ordre_categories())

    # ── Défauts des formulaires ──

    def _rebuild_defaults_form(self, *args):
        """Reconstruit le formulaire des défauts pour l'op sélectionnée."""
        from src.operations.registry import OperationRegistry
        from src.operations.base_operation import ParameterType
        from src.gui.panels.operations_panel import NoScrollComboBox
        self._defaults_loading = True
        try:
            while self._defaults_form.rowCount():
                self._defaults_form.removeRow(0)
            self._defaults_widgets = {}
            op_type = self._defaults_op_combo.currentData()
            if not op_type:
                return
            try:
                op_class = OperationRegistry.get(op_type)
            except KeyError:
                return
            current = self._defaults_cfg.get_defaults(op_type)
            for pdef in op_class.get_parameters():
                val = current.get(pdef.key, pdef.default)
                w = None
                if pdef.param_type == ParameterType.FLOAT:
                    w = SpinCote()
                    w.setDecimals(3)
                    w.setRange(
                        pdef.min_value if pdef.min_value is not None
                        else -99999.0,
                        pdef.max_value if pdef.max_value is not None
                        else 99999.0)
                    try:
                        w.setValue(float(val))
                    except (TypeError, ValueError):
                        pass
                    w.editingFinished.connect(self._save_defaults_form)
                elif pdef.param_type == ParameterType.INT:
                    w = SpinEntier()
                    w.setRange(
                        int(pdef.min_value) if pdef.min_value is not None
                        else -99999,
                        int(pdef.max_value) if pdef.max_value is not None
                        else 99999)
                    try:
                        w.setValue(int(val))
                    except (TypeError, ValueError):
                        pass
                    w.editingFinished.connect(self._save_defaults_form)
                elif pdef.param_type == ParameterType.BOOL:
                    w = QCheckBox()
                    w.setChecked(bool(val))
                    w.toggled.connect(self._save_defaults_form)
                elif pdef.param_type == ParameterType.CHOICE:
                    w = NoScrollComboBox()
                    for choice in pdef.choices:
                        w.addItem(choice)
                    idx = w.findText(str(val))
                    if idx >= 0:
                        w.setCurrentIndex(idx)
                    w.currentIndexChanged.connect(
                        self._save_defaults_form)
                else:  # STRING
                    w = QLineEdit(str(val))
                    w.editingFinished.connect(self._save_defaults_form)
                if hasattr(w, 'setMaximumWidth'):
                    w.setMaximumWidth(110)
                if hasattr(w, 'setMaximumHeight'):
                    w.setMaximumHeight(26)
                if pdef.tooltip:
                    w.setToolTip(pdef.tooltip)
                label = pdef.label
                if pdef.unit and pdef.unit not in ("", "mm"):
                    label += f" ({pdef.unit})"
                elif pdef.unit == "mm":
                    label += " (mm)"
                self._defaults_widgets[pdef.key] = (pdef, w)
                self._defaults_form.addRow(f"{label}:", w)
        finally:
            self._defaults_loading = False

    def _save_defaults_form(self, *args):
        """Collecte les valeurs du formulaire et les sauvegarde comme
        défauts personnalisés pour l'opération sélectionnée."""
        from src.operations.base_operation import ParameterType
        if self._defaults_loading:
            return
        op_type = self._defaults_op_combo.currentData()
        if not op_type or not self._defaults_widgets:
            return
        values = {}
        for key, (pdef, w) in self._defaults_widgets.items():
            try:
                if pdef.param_type in (ParameterType.FLOAT,):
                    values[key] = w.value()
                elif pdef.param_type == ParameterType.INT:
                    values[key] = w.value()
                elif pdef.param_type == ParameterType.BOOL:
                    values[key] = w.isChecked()
                elif pdef.param_type == ParameterType.CHOICE:
                    values[key] = w.currentText()
                else:
                    values[key] = w.text()
            except RuntimeError:
                return  # widget détruit
        self._defaults_cfg.set_defaults(op_type, values)

    def _reset_defaults_form(self):
        """Supprime les défauts personnalisés de l'op sélectionnée."""
        op_type = self._defaults_op_combo.currentData()
        if not op_type:
            return
        self._defaults_cfg.reset_defaults(op_type)
        self._rebuild_defaults_form()

    def _appliquer_legende_hors_matiere(self):
        """Pousse le réglage au canvas et redessine: la légende se
        construit au tracé des opérations."""
        voulue = bool(self._app_settings.get('legend_hors_matiere',
                                             False))
        win = self.window()
        panel = getattr(win, 'dxf_panel', None)
        if panel is None:
            return
        panel.canvas.set_legende_hors_matiere(voulue)
        redessiner = getattr(win, '_refresh_canvas_op', None)
        if redessiner is not None:
            redessiner()

    def _on_line_width_changed(self, value: float):
        """Applique l'épaisseur de trait au canvas et la mémorise."""
        self._app_settings['canvas_line_width'] = float(value)
        self.save_app_settings()
        win = self.window()
        panel = getattr(win, 'dxf_panel', None)
        if panel is not None:
            panel.canvas.set_line_width_px(value)
            # Papier et image suivent le réglage écran: 1 px par
            # défaut, épaissi seulement si l'utilisateur le demande
            panel.canvas._output_line_px = max(0.5, float(value))

    def _on_project_changed(self) -> bool:
        """Met à jour les settings du projet; rend vrai s'ils ont changé.
        Quitter un champ sans y toucher émet aussi `editingFinished`:
        passer d'une cote à l'autre refaisait tout à chaque champ."""
        if getattr(self, '_refreshing', False):
            return False    # chargement en cours: ne rien réécrire
        valeurs = dict(
            author=self._author_edit.text(),
            comment=self._comment_edit.toPlainText(),
            workpiece_min_x=self._wp_spins['min_x'].value(),
            workpiece_min_y=self._wp_spins['min_y'].value(),
            workpiece_min_z=self._wp_spins['min_z'].value(),
            workpiece_max_x=self._wp_spins['max_x'].value(),
            workpiece_max_y=self._wp_spins['max_y'].value(),
            workpiece_max_z=self._wp_spins['max_z'].value(),
        )
        if hasattr(self, '_library_module_cb'):
            valeurs['library_module'] = self._library_module_cb.isChecked()
        if hasattr(self, '_brut_spins'):
            valeurs.update(
                brut_longueur=self._brut_spins['longueur'].value(),
                brut_largeur=self._brut_spins['largeur'].value(),
                brut_epaisseur=self._brut_spins['epaisseur'].value(),
                brut_dx=self._brut_spins['dx'].value(),
                brut_dy=self._brut_spins['dy'].value(),
                brut_origine=str(self._brut_origine.currentData() or 'coin'))
            self._maj_brut_libre()
        s = self.program.settings
        if all(getattr(s, cle, None) == v for cle, v in valeurs.items()):
            return False
        self.program.update_settings(**valeurs)
        self.program_specs_changed.emit(self.specs_summary())
        return True

    # ── VectorDrive ──

    def _cadre_vectordrive(self):
        """Le cadre « VectorDrive »: NeoDrive y devient le post-
        processeur Datron de VectorDrive (son plugin, installé d'ici)."""
        cadre = QGroupBox("VectorDrive")
        cadre.setToolTip(
            "VectorDrive dessine et calcule les parcours; avec ce plugin, "
            "c'est NeoDrive qui écrit le programme Datron (outils de "
            "tools.json, palpages, NDMETA: le .SimPl se rouvre ici)")
        v = QVBoxLayout()
        v.setSpacing(4)
        self._etat_vectordrive = QLabel("")
        self._etat_vectordrive.setWordWrap(True)
        v.addWidget(self._etat_vectordrive)
        self._bouton_vectordrive = QPushButton(
            "Installer le post-processeur dans VectorDrive…")
        self._bouton_vectordrive.clicked.connect(
            lambda: self.installer_plugin_vectordrive())
        v.addWidget(self._bouton_vectordrive)
        cadre.setLayout(v)
        self._maj_etat_vectordrive()
        return cadre

    def _maj_etat_vectordrive(self, dossier: str = None) -> None:
        from src.integrations import vectordrive_plugin as vp
        e = vp.etat(dossier)
        a_refaire = e['installe'] and not (e['a_jour'] and e['lance_existe'])
        if not e['installe']:
            texte = ("Pas encore installé: VectorDrive ne sait pas confier "
                     "ses programmes à NeoDrive.")
        elif not e['lance_existe']:
            texte = (f"Post-processeur installé, mais il lance "
                     f"{e['lance'] or '(rien)'}, introuvable: mettez-le à "
                     "jour pour qu'il lance ce NeoDrive.")
        elif not e['a_jour']:
            texte = ("Post-processeur installé, mais plus ancien que celui "
                     "de ce NeoDrive: mettez-le à jour (VectorDrive le prend "
                     "au prochain démarrage).")
        else:
            texte = ("Post-processeur installé (« NeoDrive — Datron » au "
                     f"post-traitement de VectorDrive) — il lance: "
                     f"{e['lance']}")
        self._etat_vectordrive.setText(texte)
        self._bouton_vectordrive.setText(
            "Mettre à jour le post-processeur dans VectorDrive…" if a_refaire
            else "Installer le post-processeur dans VectorDrive…")

    #: réponse des tests à la confirmation (None: demander)
    reponse_installation_vectordrive = None

    def installer_plugin_vectordrive(self, dossier: str = None) -> str:
        """Copie le plugin dans le dossier des plugins de VectorDrive
        (après confirmation); rend le dossier installé, ou ""."""
        from src.integrations import vectordrive_plugin as vp
        cible = os.path.join(dossier or vp.dossier_plugins_vectordrive(),
                             vp.NOM_PAQUET)
        rep = self.reponse_installation_vectordrive
        if rep is None:
            rep = QMessageBox.question(
                self, "VectorDrive",
                "Installer le post-processeur « NeoDrive — Datron » pour "
                f"VectorDrive dans:\n{cible}\n\nIl lancera ce NeoDrive pour "
                "écrire les programmes. VectorDrive le prend au prochain "
                "démarrage.",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No) \
                == QMessageBox.StandardButton.Yes
        if not rep:
            return ""
        try:
            fait = vp.installer(dossier)
        except (OSError, FileNotFoundError) as exc:
            QMessageBox.warning(self, "VectorDrive",
                                f"Installation impossible:\n{exc}")
            return ""
        self._maj_etat_vectordrive(dossier)
        self._set_status("Post-processeur NeoDrive installé dans VectorDrive")
        return fait

    # ── Brut (la plaque à usiner) ──

    def _cadre_brut(self):
        """Le cadre « Brut »: longueur, largeur, épaisseur, où est le
        zéro programme, et des templates (les plaques courantes)."""
        from PySide6.QtWidgets import QComboBox
        from src.gui.icons import get_button_icon as _btn_icon
        s = self.program.settings
        cadre = QGroupBox("Brut")
        cadre.setToolTip(
            "La plaque à usiner: un parallélépipède, dessus à Z0. La "
            "simulation matière (Canva 3D) et l'image du programme le "
            "creusent. 0 = pas de brut: la zone usinée en tient lieu.")
        form = QFormLayout()
        form.setSpacing(4)
        ligne = QHBoxLayout()
        ligne.setSpacing(2)
        self._brut_tpl_combo = QComboBox()
        self._brut_tpl_combo.setMaximumHeight(26)
        self._brut_tpl_combo.setToolTip(
            "Bruts: sélectionner pour appliquer ses cotes au programme")
        self._recharger_bruts()
        self._brut_tpl_combo.currentIndexChanged.connect(
            self._sur_brut_choisi)
        ligne.addWidget(self._brut_tpl_combo, stretch=1)
        sauver = QPushButton("")
        sauver.setIcon(_btn_icon("save", 15))
        sauver.setFixedSize(26, 26)
        sauver.setToolTip("Sauver ce brut comme template")
        sauver.clicked.connect(lambda: self._sauver_brut())
        ligne.addWidget(sauver)
        oter = QPushButton("")
        oter.setIcon(_btn_icon("delete", 15))
        oter.setFixedSize(26, 26)
        oter.setToolTip("Supprimer le template choisi")
        oter.clicked.connect(lambda: self._supprimer_brut())
        ligne.addWidget(oter)
        form.addRow(ligne)
        self._brut_spins = {}
        for cle, libelle, maxi in (('longueur', "Longueur X", 2000.0),
                                   ('largeur', "Largeur Y", 2000.0),
                                   ('epaisseur', "Épaisseur Z", 500.0)):
            spin = SpinCote()
            spin.setRange(0.0, maxi)
            spin.setDecimals(2)
            spin.setValue(float(getattr(s, f'brut_{cle}', 0.0) or 0.0))
            spin.setMaximumWidth(80)
            spin.setMaximumHeight(26)
            spin.editingFinished.connect(self._on_project_changed)
            self._brut_spins[cle] = spin
            form.addRow(f"{libelle}:", spin)
        self._brut_origine = QComboBox()
        for cle, libelle in s.ORIGINES_BRUT:
            self._brut_origine.addItem(libelle, cle)
        self._brut_origine.setCurrentIndex(max(0, self._brut_origine.findData(
            getattr(s, 'brut_origine', 'coin'))))
        self._brut_origine.setToolTip(
            "Où est le zéro programme sur le brut (le dessus est Z0)")
        self._brut_origine.currentIndexChanged.connect(
            lambda *_a: self._on_project_changed())
        form.addRow("Origine:", self._brut_origine)
        decalage = QHBoxLayout()
        decalage.setSpacing(4)
        for cle, libelle in (('dx', "X"), ('dy', "Y")):
            spin = SpinCote()
            spin.setRange(-2000.0, 2000.0)
            spin.setDecimals(2)
            spin.setValue(float(getattr(s, f'brut_{cle}', 0.0) or 0.0))
            spin.setMaximumWidth(80)
            spin.setMaximumHeight(26)
            spin.setToolTip(f"Le zéro programme, à {libelle} du coin avant "
                            "gauche du brut")
            spin.editingFinished.connect(self._on_project_changed)
            self._brut_spins[cle] = spin
            decalage.addWidget(QLabel(libelle))
            decalage.addWidget(spin)
        decalage.addStretch()
        form.addRow("Zéro à:", decalage)
        self._maj_brut_libre()
        cadre.setLayout(form)
        return cadre

    def _maj_brut_libre(self) -> None:
        libre = (self._brut_origine.currentData() == 'libre')
        for cle in ('dx', 'dy'):
            self._brut_spins[cle].setEnabled(libre)

    def _chemin_bruts(self) -> str:
        return os.path.join(get_base_dir(), 'data', 'brut_templates.json')

    def _lire_bruts(self) -> list:
        from src.core.fichiers_surs import lire_json
        data = lire_json(self._chemin_bruts(), [])
        return [t for t in data if isinstance(t, dict)] \
            if isinstance(data, list) else []

    def _recharger_bruts(self, choisir: str = "") -> None:
        combo = self._brut_tpl_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("Bruts…", None)
        for tpl in self._lire_bruts():
            combo.addItem(
                f"{tpl.get('name', '?')}  ({tpl.get('longueur', 0):g}×"
                f"{tpl.get('largeur', 0):g}×{tpl.get('epaisseur', 0):g})",
                tpl)
            if choisir and tpl.get('name') == choisir:
                combo.setCurrentIndex(combo.count() - 1)
        combo.blockSignals(False)

    def _sur_brut_choisi(self, index: int) -> None:
        tpl = self._brut_tpl_combo.itemData(index)
        if not tpl:
            return
        for cle in ('longueur', 'largeur', 'epaisseur', 'dx', 'dy'):
            if cle in tpl:
                self._brut_spins[cle].setValue(float(tpl[cle]))
        if tpl.get('origine'):
            i = self._brut_origine.findData(tpl['origine'])
            if i >= 0:
                self._brut_origine.blockSignals(True)
                self._brut_origine.setCurrentIndex(i)
                self._brut_origine.blockSignals(False)
        self._on_project_changed()
        self._set_status(f"Brut « {tpl.get('name', '?')} » appliqué")

    #: réponse des tests au nom d'un template de brut (None: demander)
    reponse_nom_brut = None

    def _sauver_brut(self) -> None:
        from PySide6.QtWidgets import QInputDialog
        v = {cle: self._brut_spins[cle].value()
             for cle in ('longueur', 'largeur', 'epaisseur', 'dx', 'dy')}
        nom = self.reponse_nom_brut
        if nom is None:
            nom, ok = QInputDialog.getText(
                self, "Brut", "Nom du template:",
                text=f"Brut {v['longueur']:g}×{v['largeur']:g}×"
                     f"{v['epaisseur']:g}")
            if not ok:
                return
        nom = str(nom).strip()
        if not nom:
            return
        tpl = {'name': nom, **v,
               'origine': str(self._brut_origine.currentData() or 'coin')}
        bruts = [t for t in self._lire_bruts() if t.get('name') != nom]
        bruts.append(tpl)
        bruts.sort(key=lambda t: str(t.get('name', '')).lower())
        try:
            from src.core.fichiers_surs import ecrire_json_sur
            ecrire_json_sur(self._chemin_bruts(), bruts, garder_bak=True,
                            indent=2, ensure_ascii=False)
        except OSError as e:
            QMessageBox.warning(self, "Bruts",
                                f"Enregistrement impossible:\n{e}")
            return
        self._recharger_bruts(choisir=nom)
        self._set_status(f"Brut « {nom} » sauvé")

    def _supprimer_brut(self) -> None:
        tpl = self._brut_tpl_combo.itemData(
            self._brut_tpl_combo.currentIndex())
        if not tpl:
            return
        nom = tpl.get('name', '?')
        if QMessageBox.question(
                self, "Bruts", f"Supprimer le template « {nom} » ?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No) \
                != QMessageBox.StandardButton.Yes:
            return
        bruts = [t for t in self._lire_bruts() if t.get('name') != nom]
        try:
            from src.core.fichiers_surs import ecrire_json_sur
            ecrire_json_sur(self._chemin_bruts(), bruts, garder_bak=True,
                            indent=2, ensure_ascii=False)
        except OSError:
            return
        self._recharger_bruts()

    # ── Templates de l'espace de travail (WorkpieceGeometry) ──

    _WP_KEYS = ('min_x', 'min_y', 'min_z', 'max_x', 'max_y', 'max_z')

    def _set_status(self, text: str):
        """Affiche un message dans la barre d'état de la fenêtre."""
        w = self.window()
        lbl = getattr(w, '_status_label', None)
        if lbl is not None:
            lbl.setText(text)

    def _wp_templates_path(self) -> str:
        return os.path.join(get_base_dir(), 'data',
                            'workpiece_templates.json')

    def _load_wp_templates(self) -> list:
        from src.core.fichiers_surs import lire_json
        data = lire_json(self._wp_templates_path(), [])
        return data if isinstance(data, list) else []

    def _save_wp_templates(self, templates: list) -> bool:
        try:
            from src.core.fichiers_surs import ecrire_json_sur
            ecrire_json_sur(self._wp_templates_path(), templates,
                            garder_bak=True, indent=2, ensure_ascii=False)
            return True
        except OSError as e:
            QMessageBox.warning(
                self, "Templates de brut",
                f"Impossible d'enregistrer les templates:\n{e}")
            return False

    def _reload_wp_templates(self, select_name: str = ""):
        combo = self._wp_tpl_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("Espaces de travail…", None)
        for tpl in self._load_wp_templates():
            dx = tpl.get('max_x', 0) - tpl.get('min_x', 0)
            dy = tpl.get('max_y', 0) - tpl.get('min_y', 0)
            dz = tpl.get('max_z', 0) - tpl.get('min_z', 0)
            combo.addItem(
                f"{tpl.get('name', '?')}  ({dx:g}×{dy:g}×{dz:g})", tpl)
            if select_name and tpl.get('name') == select_name:
                combo.setCurrentIndex(combo.count() - 1)
        combo.blockSignals(False)

    def _on_wp_template_selected(self, index: int):
        tpl = self._wp_tpl_combo.itemData(index)
        if not tpl:
            return
        for key in self._WP_KEYS:
            if key in tpl:
                self._wp_spins[key].setValue(float(tpl[key]))
        self._on_project_changed()
        self._set_status(
            f"Espace de travail « {tpl.get('name', '?')} » appliqué")

    def _on_wp_template_save(self):
        from PySide6.QtWidgets import QInputDialog
        dx = self._wp_spins['max_x'].value() - \
            self._wp_spins['min_x'].value()
        dy = self._wp_spins['max_y'].value() - \
            self._wp_spins['min_y'].value()
        dz = self._wp_spins['max_z'].value() - \
            self._wp_spins['min_z'].value()
        name, ok = QInputDialog.getText(
            self, "Espace de travail", "Nom du template:",
            text=f"Espace {dx:g}×{dy:g}×{dz:g}")
        if not ok or not name.strip():
            return
        name = name.strip()
        tpl = {'name': name}
        for key in self._WP_KEYS:
            tpl[key] = self._wp_spins[key].value()
        templates = [t for t in self._load_wp_templates()
                     if t.get('name') != name]
        templates.append(tpl)
        templates.sort(key=lambda t: t.get('name', '').lower())
        if self._save_wp_templates(templates):
            self._reload_wp_templates(select_name=name)
            self._set_status(f"Template « {name} » sauvé")

    def _on_wp_template_delete(self):
        tpl = self._wp_tpl_combo.itemData(
            self._wp_tpl_combo.currentIndex())
        if not tpl:
            QMessageBox.information(
                self, "Templates de brut",
                "Sélectionnez d'abord un template à supprimer.")
            return
        name = tpl.get('name', '?')
        reply = QMessageBox.question(
            self, "Templates de brut",
            f"Supprimer le template « {name} » ?",
            QMessageBox.StandardButton.Yes |
            QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        templates = [t for t in self._load_wp_templates()
                     if t.get('name') != name]
        if self._save_wp_templates(templates):
            self._reload_wp_templates()
            self._set_status(f"Template « {name} » supprimé")

    def _update_safe_rapid_label(self):
        """Label du Z de dégagement. L'invariant machine est:
        Z des SafeRapid = strokeRapidZ + strokeCuttingZ.
        SafeZHeightForWorkpiece est un réglage INDÉPENDANT (hauteur
        de sécurité au-dessus du brut) et n'entre pas dans ce calcul."""
        srz = int(self._stroke_rapid_z_spin.value())
        scz = int(self._stroke_cutting_z_spin.value())
        total = srz + scz
        self._safe_rapid_z_label.setText(
            f"SafeRapid Z = {total}   ({srz} + {scz})")
        self._safe_rapid_z_label.setStyleSheet(
            "color: #a6e3a1; font-weight: bold; font-size: 12px;")
        self._safe_rapid_z_label.setToolTip(
            "Tous les SafeRapid du code généré dégagent à ce Z "
            "(strokeRapidZ + strokeCuttingZ).\n"
            "SafeZHeightForWorkpiece est un réglage indépendant.")

    def _on_stroke_z_changed(self):
        """Met à jour le label SafeRapid Z quand strokeRapidZ/CuttingZ change."""
        self._update_safe_rapid_label()
        self._on_app_settings_changed()

    def _on_app_settings_changed(self):
        """Sauvegarde les paramètres app."""
        self._app_settings['path_replace_from'] = self._path_from.text()
        self._app_settings['path_replace_to'] = self._path_to.text()
        self._regler_chemins_machine()
        self._app_settings['default_programs_dir'] = self._prog_dir.text()
        self._app_settings['default_exports_dir'] = self._export_dir.text()
        self._app_settings['default_dxf_dir'] = self._dxf_dir_edit.text()
        if hasattr(self, '_avance_max_spin'):
            self._app_settings['avance_max'] = float(
                self._avance_max_spin.value())
        if hasattr(self, '_rpm_max_spin'):
            self._app_settings['rpm_max'] = float(self._rpm_max_spin.value())
        self._app_settings['closed_tabs_keep'] = (
            self._closed_tabs_spin.value())
        self._app_settings['safe_z_height'] = self._safe_z_spin.value()
        if hasattr(self, '_safe_rapid_z_label'):
            self._update_safe_rapid_label()
        self._app_settings['smoothing'] = self._smoothing_cb.isChecked()
        if hasattr(self, '_col_anim_spin'):
            self._app_settings['column_anim_ms'] = int(
                self._col_anim_spin.value())
        if hasattr(self, '_legend_hm_cb'):
            voulue = self._legend_hm_cb.isChecked()
            if voulue != self._app_settings.get('legend_hors_matiere',
                                                False):
                self._app_settings['legend_hors_matiere'] = voulue
                self._appliquer_legende_hors_matiere()
        self._app_settings['smoothing_deviation'] = (
            self._smoothing_deviation.value())
        self._app_settings['smoothing_angle'] = self._smoothing_angle.value()
        self._app_settings['smoothing_kink'] = self._smoothing_kink.value()
        self._app_settings['dynamic'] = int(self._dynamic_spin.value())
        self._app_settings['stroke_rapid_z'] = int(
            self._stroke_rapid_z_spin.value())
        self._app_settings['stroke_cutting_z'] = int(
            self._stroke_cutting_z_spin.value())
        self._app_settings['material'] = (
            self._material_combo.currentData() or "")
        if hasattr(self, '_png_bg_combo'):
            self._app_settings['png_background'] = (
                self._png_bg_combo.currentData() or "#b8b8b8")
        if hasattr(self, '_export_dessin_combo'):
            self._app_settings['export_dessin'] = (
                self._export_dessin_combo.currentData() or "aucun")
        if hasattr(self, '_visu_combo'):
            self._app_settings['visu_machine'] = (
                self._visu_combo.currentData() or "2d")
        if hasattr(self, '_calculs_3d_combo'):
            self._app_settings['calculs_3d'] = (
                self._calculs_3d_combo.currentData() or "temps_reel")
        self._app_settings['feed_multiplier'] = self._feed_mult_spin.value()
        self._app_settings['rpm_multiplier'] = self._rpm_mult_spin.value()
        self._app_settings['rpm_limit'] = int(self._rpm_limit_spin.value())
        self._app_settings['feed_limit'] = int(
            self._feed_limit_spin.value())
        self._app_settings['auto_group'] = (
            self._auto_group_cb.isChecked())
        for key, cb in getattr(self, '_datron_checks', {}).items():
            self._app_settings[key] = cb.isChecked()
        self.save_app_settings()

    def _on_default_tool_changed(self):
        """Sauvegarde les outils par défaut par catégorie."""
        if hasattr(self, '_default_tool_combos'):
            for cat_key, combo in self._default_tool_combos.items():
                self._app_settings[f'default_tool_{cat_key}'] = (
                    combo.currentData() or "")
        self.save_app_settings()

    def get_default_tool_article(self, op_type: str) -> str:
        """Retourne l'article par défaut pour un type d'opération, ou ''."""
        for cat_key, _label, op_types in self._TOOL_DEFAULT_CATEGORIES:
            if op_type in op_types:
                return self._app_settings.get(
                    f'default_tool_{cat_key}', '')
        return ''

    def get_expert_settings(self) -> dict:
        """Retourne les paramètres expert complets."""
        result = {
            'safe_z_height': self._app_settings.get('safe_z_height', 0.5),
            'smoothing': self._app_settings.get('smoothing', False),
            'smoothing_deviation': self._app_settings.get(
                'smoothing_deviation', 0.0025),
            'smoothing_angle': self._app_settings.get('smoothing_angle', 0),
            'smoothing_kink': self._app_settings.get('smoothing_kink', 0),
            'dynamic': self._app_settings.get('dynamic', 0),
            'stroke_rapid_z': self._app_settings.get('stroke_rapid_z', 15),
            'stroke_cutting_z': self._app_settings.get('stroke_cutting_z', 1),
            'rpm_limit': self._app_settings.get('rpm_limit', 40000),
            'feed_limit': self._app_settings.get('feed_limit', 0),
            'auto_group': self._app_settings.get('auto_group', True),
            # Enrichissements Datron: OFF par défaut
            'emit_tool_descriptions': self._app_settings.get(
                'emit_tool_descriptions', True),
            'emit_workpiece_comments': self._app_settings.get(
                'emit_workpiece_comments', False),
            'emit_op_stats': self._app_settings.get(
                'emit_op_stats', False),
            'emit_op_doc': self._app_settings.get('emit_op_doc', False),
            'embed_canvas_preview': self._app_settings.get(
                'embed_canvas_preview', False),
        }
        # Multiplicateurs: matériau OU manuels
        mat_id = self._app_settings.get('material', '')
        feed_mult = self._app_settings.get('feed_multiplier', 1.0)
        rpm_mult = self._app_settings.get('rpm_multiplier', 1.0)
        result['material'] = ''
        if mat_id and hasattr(self, '_materials_lib'):
            mat = self._materials_lib.get(mat_id)
            if mat:
                feed_mult = mat.feed_multiplier
                rpm_mult = mat.rpm_multiplier
                result['material'] = mat.name
        result['material_feed_mult'] = feed_mult
        result['material_rpm_mult'] = rpm_mult
        return result

    #: le dessin joint à l'export du programme
    EXPORT_DESSIN = (("Aucun", "aucun"),
                     ("2D: DXF + PNG du Canva", "2d"),
                     ("3D: STL + PNG de la pièce usinée", "3d"))

    def export_dessin(self) -> str:
        """'aucun', '2d' ou '3d'."""
        v = str(self._app_settings.get('export_dessin', 'aucun'))
        return v if v in ('aucun', '2d', '3d') else 'aucun'

    #: l'image du programme sur l'écran de la machine
    VISU_MACHINE = (("2D: le plan du Canva", "2d"),
                    ("3D: vue iso de la pièce usinée", "3d"),
                    ("Les deux, côte à côte", "2d3d"))

    def visu_machine(self) -> str:
        """'2d', '3d' ou '2d3d'."""
        v = str(self._app_settings.get('visu_machine', '2d'))
        return v if v in ('2d', '3d', '2d3d') else '2d'

    #: quand le Canva 3D se recalcule
    CALCULS_3D = (("En temps réel", "temps_reel"),
                  ("Sur demande (bouton)", "demande"))

    def calculs_3d(self) -> str:
        """'temps_reel' ou 'demande'."""
        v = str(self._app_settings.get('calculs_3d', 'temps_reel'))
        return v if v in ('temps_reel', 'demande') else 'temps_reel'

    def png_background(self) -> str:
        """Couleur de fond du PNG joint au programme."""
        return str(self._app_settings.get('png_background', '#b8b8b8'))

    #: posé par la fenêtre: (réglages) -> QImage de l'aperçu
    apercu_png = None

    def reglages_png(self) -> dict:
        """Les réglages du PNG du programme (src/gui/dialogs/
        reglages_png); le fond 2D reste celui de « Fond du PNG »."""
        from src.gui.dialogs import reglages_png as rp
        r = rp.lire(self._app_settings.get('png_export'))
        if 'png_background' in self._app_settings and not (
                self._app_settings.get('png_export') or {}).get('fond'):
            r['fond'] = self.png_background()
        return r

    def regler_png(self, reglages: dict) -> None:
        from src.gui.dialogs import reglages_png as rp
        r = rp.lire(reglages)
        self._app_settings['png_export'] = r
        self._app_settings['png_background'] = r['fond']
        self.save_app_settings()

    def editer_reglages_png(self, executer: bool = True):
        """La fenêtre des réglages du PNG; rend la fenêtre (les tests
        la pilotent sans l'ouvrir)."""
        from src.gui.dialogs.reglages_png import DialogueReglagesPng
        dlg = DialogueReglagesPng(self.reglages_png(), self.visu_machine(),
                                  self.apercu_png, self)
        if executer and dlg.exec():
            self.regler_png(dlg.reglages())
        return dlg

    def _regler_chemins_machine(self):
        """Le simulateur et l'aperçu lisent sur le poste les programmes
        appelés que le code nomme à la façon de la machine."""
        from src.core import chemins_machine
        chemins_machine.regler(*self.get_path_replacement())

    def get_path_replacement(self) -> tuple:
        """Retourne (from, to) pour le remplacement de chemin."""
        return (
            self._app_settings.get('path_replace_from', ''),
            self._app_settings.get('path_replace_to', '')
        )

    def refresh_from_model(self):
        """Rafraîchit les valeurs depuis le modèle.

        Les écritures sont GARDÉES: setPlainText sur le commentaire
        émet textChanged, qui rappelait _on_project_changed alors que
        les autres champs portaient encore les valeurs de l'onglet
        PRÉCÉDENT — le brut du nouvel onglet était donc écrasé, et
        les réglages semblaient partagés entre onglets.
        """
        self._refreshing = True
        try:
            s = self.program.settings
            self._author_edit.setText(s.author)
            self._comment_edit.setPlainText(s.comment)
            self._wp_spins['min_x'].setValue(s.workpiece_min_x)
            self._wp_spins['min_y'].setValue(s.workpiece_min_y)
            self._wp_spins['min_z'].setValue(s.workpiece_min_z)
            self._wp_spins['max_x'].setValue(s.workpiece_max_x)
            self._wp_spins['max_y'].setValue(s.workpiece_max_y)
            self._wp_spins['max_z'].setValue(s.workpiece_max_z)
            if hasattr(self, '_library_module_cb'):
                self._library_module_cb.setChecked(
                    bool(getattr(s, 'library_module', False)))
            if hasattr(self, '_brut_spins'):
                for cle in ('longueur', 'largeur', 'epaisseur', 'dx', 'dy'):
                    self._brut_spins[cle].setValue(
                        float(getattr(s, f'brut_{cle}', 0.0) or 0.0))
                i = self._brut_origine.findData(
                    getattr(s, 'brut_origine', 'coin'))
                self._brut_origine.setCurrentIndex(max(0, i))
                self._maj_brut_libre()
        finally:
            self._refreshing = False
        self.program_specs_changed.emit(self.specs_summary())


# ──── Panneau Raccourcis (onglet col3) ────

class ShortcutsPanel(QScrollArea):
    """Onglet raccourcis clavier dans la colonne 3."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._shortcuts_path = os.path.join(
            get_base_dir(), 'data', 'shortcuts.json')
        self._shortcuts = self._load_shortcuts()
        self._setup_ui()

    def _default_shortcuts(self) -> dict:
        return {
            'Nouveau': 'Ctrl+N',
            'Ouvrir': 'Ctrl+O',
            'Enregistrer': 'Ctrl+S',
            'Enregistrer sous': 'Ctrl+Shift+S',
            'Exporter SimPl': 'Ctrl+E',
            'Parcourir': 'Ctrl+B',
            'Outils': 'Ctrl+T',
            'Dupliquer opération': 'Ctrl+D',
            'Supprimer opération': 'Delete',
            'Activer/Désactiver op.': 'Ctrl+Shift+E',
            'Undo': 'Ctrl+Z',
            'Redo': 'Ctrl+Y',
            'Régénérer code': 'F5',
            'Fit vue DXF': 'F',
            'Plein écran': 'F11',
        }

    def _load_shortcuts(self) -> dict:
        defaults = self._default_shortcuts()
        from src.core.fichiers_surs import lire_json
        stored = lire_json(self._shortcuts_path, {})
        if isinstance(stored, dict):
            defaults.update(stored)
        return defaults

    def _save_shortcuts(self):
        try:
            from src.core.fichiers_surs import ecrire_json_sur
            ecrire_json_sur(self._shortcuts_path, self._shortcuts,
                            garder_bak=True, indent=2, ensure_ascii=False)
        except Exception as e:
            if not getattr(self, '_save_warned', False):
                self._save_warned = True
                QMessageBox.warning(
                    self, "Raccourcis",
                    f"Impossible de sauvegarder les raccourcis:\n{e}")

    def _setup_ui(self):
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(8)
        layout.setContentsMargins(8, 8, 8, 8)

        title = QLabel("Raccourcis clavier")
        title.setStyleSheet(
            "font-weight: bold; font-size: 14px; color: #89b4fa;")
        layout.addWidget(title)

        info = QLabel("Double-cliquez sur un raccourci pour le modifier.\n"
                       "Formats: F, Ctrl+N, Shift+A")
        info.setStyleSheet("color: #a6adc8; font-size: 11px;")
        layout.addWidget(info)

        self._table = QTableWidget()
        self._table.setColumnCount(2)
        self._table.setHorizontalHeaderLabels(["Action", "Raccourci"])
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked)
        self._table.setStyleSheet(
            "QTableWidget { background: #181825; color: #cdd6f4; }")

        self._fill_table()
        self._table.cellChanged.connect(self._on_shortcut_changed)
        layout.addWidget(self._table, stretch=1)

        # Bouton reset
        reset_btn = QPushButton("Réinitialiser les raccourcis")
        reset_btn.clicked.connect(self._on_reset)
        layout.addWidget(reset_btn)

        layout.addStretch()
        self.setWidget(content)

    def _fill_table(self):
        self._table.blockSignals(True)
        self._table.setRowCount(len(self._shortcuts))
        for i, (action, shortcut) in enumerate(self._shortcuts.items()):
            action_item = QTableWidgetItem(action)
            action_item.setFlags(
                action_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(i, 0, action_item)
            shortcut_item = QTableWidgetItem(shortcut)
            self._table.setItem(i, 1, shortcut_item)
        self._table.blockSignals(False)

    def _on_shortcut_changed(self, row, col):
        if col != 1:
            return
        action_item = self._table.item(row, 0)
        shortcut_item = self._table.item(row, 1)
        if action_item and shortcut_item:
            action = action_item.text()
            new_shortcut = shortcut_item.text().strip()
            self._shortcuts[action] = new_shortcut
            self._save_shortcuts()

    def _on_reset(self):
        self._shortcuts = self._default_shortcuts()
        self._save_shortcuts()
        self._fill_table()

    def get_shortcuts(self) -> dict:
        return dict(self._shortcuts)


# ──── Fenêtre principale ────

class MainWindow(QMainWindow):
    """Fenêtre principale de l'application NeoDrive."""

    def __init__(self):
        super().__init__()
        from src import __version__
        self.setWindowTitle(f"NeoDrive {__version__} - Génère ton SimPl")
        # PAS de setWindowState(Maximized) ici: posé avant show(),
        # Windows crée la fenêtre « maximisée » à partir de ses
        # 200 x 100 par défaut et la laisse à sa largeur minimale —
        # mesuré: 764 px de large sur un écran de 1920, état
        # maximisé. C'est `afficher_au_demarrage` qui montre.
        # Glisser-déposer de fichiers .ndp/.nds/.SimPl/.dxf
        self.setAcceptDrops(True)

        # Supprimer la barre de menu
        self.setMenuBar(None)
        self.menuBar().hide()

        # Répertoires
        self._base_dir = get_base_dir()
        self._programs_dir = os.path.join(self._base_dir, "programs")
        self._exports_dir = os.path.join(self._base_dir, "exports")
        os.makedirs(self._programs_dir, exist_ok=True)
        os.makedirs(self._exports_dir, exist_ok=True)

        # Modèles
        self.tool_library = ToolLibrary()
        self.program = ProgramModel()

        # Multi-document: liste de (ProgramModel, nom_fichier)
        self._program_tabs = [
            {"program": self.program, "filepath": "", "name": "P1"}
        ]
        self._active_tab_index = 0

        # Timer debounce — échu, il laisse passer le geste en cours
        # (basse priorité: voir `_regen_quand_libre`)
        self._regen_timer = QTimer(self)
        self._regen_timer.setSingleShot(True)
        self._regen_timer.setInterval(self.REGEN_DIFFERE_MS)
        self._regen_timer.timeout.connect(self._regen_quand_libre)
        #: l'état du code affiché (voir ETATS_CODE)
        self._etat_code = None
        self._regen_en_cours = False

        self._generation_blocked = False
        self._expert_mode = False
        self._file_panel = None
        self._history_panel = None
        self._action_history = []
        # Pile undo PAR ONGLET: self.undo_stack pointe toujours sur
        # celle de l'onglet actif (Ctrl+Z n'affecte jamais un autre onglet)
        self.undo_stack = self._new_undo_stack()
        self._program_tabs[0]["undo_stack"] = self.undo_stack

        # Auto-save path
        self._autosave_path = os.path.join(
            self._programs_dir, ".autosave.ndp")
        #: la session sur disque appartient a l'UTILISATEUR. Un
        #: MainWindow ouvert par un test ou un banc de mesure ne doit
        #: pas l'ecraser: son minuteur finissait par tourner et le
        #: programme de test remplacait le travail en cours.
        self._session_writable = self._session_writes_allowed()

        # UI
        self._setup_ui()
        self._setup_statusbar()
        self._setup_shortcuts()
        self._connect_signals()

        # Wire undo stack to operations panel
        self.operations_panel._undo_stack = self.undo_stack
        # Wire params panel for default tool lookup
        self.operations_panel.param_form._params_panel = self.params_panel
        # Le catalogue « + Opé » s'est construit AVANT que le panneau
        # soit dans la fenêtre: sans les réglages (épinglées, ordre,
        # expert seulement). Il se refait maintenant qu'ils sont là —
        # sinon ce qu'on avait réglé ne revenait qu'après un
        # changement.
        self.operations_panel._rebuild_add_panel()

        # Auto-restore
        self._auto_restore()

        # Timer auto-save
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(30000)
        self._autosave_timer.timeout.connect(self._auto_save)
        if self._session_writable:
            self._autosave_timer.start()

        # Épaisseur de trait du canvas (réglage mémorisé)
        width = float(self.params_panel._app_settings.get(
            'canvas_line_width', 1.0))
        self._largeur_trait_canvas = width
        # Chaque onglet a SON canvas: les réglages et les
        # branchements de la fenêtre valent pour tous, y compris
        # ceux qui naîtront plus tard
        self.dxf_panel.canvas_cree.connect(self._preparer_canvas)
        self._preparer_canvas(self.dxf_panel.canvas)
        # Le canvas déjà créé appartient au premier onglet
        if self._program_tabs:
            self.dxf_panel.attacher_canvas_courant(
                self._cle_canvas(self._program_tabs[0]))


        # Dossier d'échange programmes outils → NeoDrive
        self._setup_incoming_watcher()

        # Code initial
        self._regenerate_code()

    def _setup_ui(self):
        """Crée le layout 3 colonnes."""
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        # Une colonne ne doit JAMAIS imposer sa largeur à la fenêtre:
        # la somme des minimums des trois panneaux faisait 2545 px, et
        # replier puis déplier remettait la fenêtre à cette taille —
        # elle passait sous la barre des tâches.
        self._splitter.setChildrenCollapsible(True)
        splitter = self._splitter

        # ── Style commun pour les onglets ──
        tab_style = """
            QTabBar::tab {
                background: #313244; color: #cdd6f4;
                padding: 9px 24px; border: none;
                border-bottom: 2px solid transparent;
                font-weight: bold; font-size: 13px;
            }
            QTabBar::tab:selected {
                background: #1e1e2e;
                border-bottom: 2px solid #89b4fa;
                color: #89b4fa;
                font-weight: bold; font-size: 13px;
            }
            QTabBar::tab:hover:!selected { background: #45475a; }
        """

        # Colonne 1: Onglets Opérations / Paramètres
        self._col1_tabs = QTabWidget()
        self._col1_tabs.setDocumentMode(True)
        self._col1_tabs.setStyleSheet(tab_style)

        # Fichier EN PREMIER: c'est par là qu'on commence, et son
        # bouton mangeait la place de la barre d'onglets programmes
        from src.gui.icons import get_button_icon
        self._file_panel = FileMenuPanel()
        self._file_panel._callback = self._on_file_action
        self._file_panel._callback_recent = self._ouvrir_recent
        self._col1_tabs.addTab(
            self._file_panel, get_button_icon("open_file", 16), "Fichier")

        self.operations_panel = OperationsPanel(
            self.program, self.tool_library)
        self._col1_tabs.addTab(self.operations_panel, "Opérations")

        self.params_panel = ParametersPanel(self.program, self.tool_library)
        # l'aperçu de la fenêtre des réglages du PNG d'export
        self.params_panel.apercu_png = self.apercu_png
        # Partager la config des défauts: les éditions dans Paramètres
        # s'appliquent immédiatement aux nouvelles opérations
        self.params_panel._defaults_cfg = \
            self.operations_panel._default_params
        # L'onglet « Paramètres » n'est qu'une porte: la page prend
        # TOUTE la fenêtre, en trois colonnes (voir
        # `afficher_parametres`)
        self._params_lanceur = QWidget()
        params_idx = self._col1_tabs.addTab(self._params_lanceur,
                                            "Paramètres")
        self._col1_tabs.tabBar().setTabTextColor(
            params_idx, QColor("#fab387"))  # orange
        self.params_panel.retour_demande.connect(self.masquer_parametres)

        self._col1_tabs.setCurrentWidget(self.operations_panel)
        self._onglet_col1_precedent = self._col1_tabs.currentIndex()
        self._col1_tabs.currentChanged.connect(self._on_col1_tab_changed)

        self._col1_tabs.setMinimumWidth(self.LARGEUR_MINI_COLONNE)
        splitter.addWidget(self._col1_tabs)

        # Colonne 2: Onglets Code / DXF to Op / Matériaux
        self._col2_tabs = QTabWidget()
        self._col2_tabs.setDocumentMode(True)
        self._col2_tabs.setStyleSheet(tab_style)

        self.code_panel = CodeEditorPanel()
        self._col2_tabs.addTab(self.code_panel, "Code SimPl")

        self.circle_ops_panel = CircleOpsPanel()
        # Importer / Exporter / Effacer le DESSIN appartiennent au
        # travail « DXF vers opérations », pas au canvas lui-même
        self.circle_ops_panel.dxf_action.connect(self._on_dxf_action)
        self.circle_ops_panel.operations_generated.connect(
            self._on_circle_ops_generated)
        self._col2_tabs.addTab(self.circle_ops_panel, "DXF to Op")

        # Édition batch de programmes SimPl externes
        from src.gui.panels.simpl_edit_panel import SimplEditPanel
        self.simpl_edit_panel = SimplEditPanel(self.tool_library)
        self.simpl_edit_panel.blocks_available.connect(
            self._on_simpl_blocks_available)
        self.simpl_edit_panel.sequence_to_operation.connect(
            self._on_sequence_to_operation)
        edit_idx = self._col2_tabs.addTab(
            self.simpl_edit_panel, "Batch édition")
        self._col2_tabs.tabBar().setTabTextColor(
            edit_idx, QColor("#fab387"))  # orange

        self._col2_tabs.setMinimumWidth(self.LARGEUR_MINI_COLONNE)
        splitter.addWidget(self._col2_tabs)

        # Historique puis Tips, à la suite de Batch édition
        self._history_panel = self._create_history_panel()
        self._col2_tabs.addTab(
            self._history_panel, get_button_icon("history", 16), "")
        self._col2_tabs.setTabToolTip(
            self._col2_tabs.count() - 1, "Historique des actions")

        self._tips_panel = self._create_tips_panel()
        self._col2_tabs.addTab(
            self._tips_panel, get_button_icon("help", 16), "Tips")

        # Colonne 3: Onglets DXF / Tools / Raccourcis
        self._col3_tabs = QTabWidget()
        self._col3_tabs.setDocumentMode(True)
        self._col3_tabs.setStyleSheet(tab_style)

        self.dxf_panel = DxfEditorPanel()
        # la vue 3D du canvas lit le programme et les outils d'ici
        self.dxf_panel.fournisseur_3d = lambda: (self.program,
                                                 self.tool_library)
        dxf_dir = self.params_panel._app_settings.get('default_dxf_dir', '')
        dxf_dir = self._resolve_dir(dxf_dir)
        if dxf_dir:
            self.dxf_panel.set_default_dxf_dir(dxf_dir)
        self._col3_tabs.addTab(self.dxf_panel, "Canva 2D")
        # la vue 3D (pièce STEP, opérations, parcours simulé des
        # cycles): un onglet à elle — le bouton « 3D » du canvas y
        # mène, « ← 2D » ramène au Canva
        self.dxf_panel.hote_3d = self._montrer_onglet_3d
        # le Canva 3D simule le programme SANS les opérations dont
        # l'œil est fermé (le 2D les masque déjà)
        self.dxf_panel.fournisseur_code_3d = self.code_pour_3d
        # les faces choisies de la pièce STEP deviennent des opérations
        self.dxf_panel.usinage_step.connect(
            lambda ops: self._on_circle_ops_generated(
                ops, source="la pièce STEP"))
        self.vue3d_panel = self.dxf_panel.vue_3d()
        # le brut des Paramètres (programme COURANT: lu à chaque fois)
        self.vue3d_panel.fournisseur_brut = (
            lambda: self.program.settings.boite_brut())
        # le .SimPl de l'onglet: ses temps mesurés par la machine
        self.vue3d_panel.fournisseur_chemin_programme = (
            self.chemin_simpl_actif)
        # la transparence de chaque opération: le parcours la suit
        self.vue3d_panel.fournisseur_affichage_ops = (
            lambda: affichage_ops.reglages_des_ops(self.program.operations))
        self.params_panel.program_specs_changed.connect(
            lambda *_a: self.vue3d_panel.brut_change())
        # un clic sur le trait d'une opération au Canva 3D: elle est
        # choisie dans la liste (le formulaire et le Canva 2D suivent)
        self.vue3d_panel.operation_cliquee.connect(self.choisir_op_depuis_3d)
        # clic droit sur « 3D » (Canva 2D) ou « ← 2D » (Canva 3D): où mettre
        # le 3D — à côté du dessin, en fenêtre, derrière
        for bouton in (self.dxf_panel.vue3d_btn, self.vue3d_panel.retour_btn):
            bouton.setContextMenuPolicy(
                Qt.ContextMenuPolicy.CustomContextMenu)
            bouton.customContextMenuRequested.connect(
                lambda pos, b=bouton: self.menu_place_3d(b).exec(
                    b.mapToGlobal(pos)))
            bouton.setToolTip(bouton.toolTip() + "\nClic droit: le 3D à "
                              "côté du dessin, en fenêtre ou derrière")
        self._col3_tabs.addTab(self.vue3d_panel, "Canva 3D")
        self._col3_tabs.currentChanged.connect(self._sur_onglet_col3)

        self.tool_manager_panel = ToolManagerPanel(
            self.tool_library, broche=self._broche_datron)
        self._col3_tabs.addTab(self.tool_manager_panel, "Tools")
        self.tool_manager_panel.plein_fenetre_demande.connect(
            self.outils_plein_fenetre)
        self.tool_manager_panel.close_requested.connect(
            self._fermer_outils)
        # la fiche d'un outil: à la place des colonnes 1 et 2
        self.tool_manager_panel.hote_fiche = self.montrer_fiche
        self.tool_manager_panel.fermer_hote_fiche = self.masquer_fiche
        self.tool_manager_panel.remplacement_fiche = self.fiche_remplacee

        # Catalogue DATRON hors ligne: de quoi nourrir tools.json
        from src.gui.panels.catalogue_panel import CataloguePanel
        self.catalogue_panel = CataloguePanel(
            self.tool_library, broche=self._broche_datron())
        self._col3_tabs.addTab(self.catalogue_panel, "Catalogue")
        self.catalogue_panel.broche_changee.connect(
            self._on_broche_datron)
        self.catalogue_panel.action.connect(self._log_action)
        self.catalogue_panel.outils_changes.connect(
            self.tool_manager_panel._on_search)
        self.tool_manager_panel.outils_changes.connect(
            self.catalogue_panel.rafraichir)
        # une couleur d'outil changée: le plan et la 3D la reprennent
        self.tool_manager_panel.outils_changes.connect(
            self._couleurs_outils_changees)
        self.catalogue_panel.hote_fiche = self.montrer_fiche
        self.catalogue_panel.fermer_hote_fiche = self.masquer_fiche
        self.catalogue_panel.remplacement_fiche = self.fiche_remplacee
        # la fiche ouverte en colonnes 1 et 2 suit la sélection de la
        # colonne 3, d'un panneau à l'autre
        tm, cp = self.tool_manager_panel, self.catalogue_panel
        tm.fiche_ailleurs = lambda: cp._fiche is not None
        tm.fermer_fiche_ailleurs = cp.fermer_fiche
        cp.fiche_ailleurs = lambda: (tm._fiche is not None
                                     and tm._fiche_hebergee)
        cp.quitter_fiche_ailleurs = tm.quitter_fiche
        self.catalogue_panel.fiche_outil_demandee.connect(
            self._ouvrir_fiche_outil_depuis_catalogue)

        self.shortcuts_panel = ShortcutsPanel()
        self._col3_tabs.addTab(self.shortcuts_panel, "Raccourcis")

        # Bibliothèque de symboles TypeEdit (.smb)
        from src.gui.panels.symbol_browser_panel import SymbolBrowserPanel
        sym_dir = self.params_panel._app_settings.get('symbols_dir', '')
        if not sym_dir or not os.path.isdir(sym_dir):
            default_sym = os.path.join(self._base_dir, 'Symbols')
            sym_dir = default_sym if os.path.isdir(default_sym) else ''
        self.symbol_panel = SymbolBrowserPanel(sym_dir)
        self.symbol_panel.symbols_dir_changed.connect(
            self._on_symbols_dir_changed)
        self.symbol_panel.symbol_to_canvas.connect(
            self._on_symbol_to_canvas)
        self._col3_tabs.addTab(self.symbol_panel, "Symboles")

        self._col3_tabs.setMinimumWidth(self.LARGEUR_MINI_COLONNE)
        splitter.addWidget(self._col3_tabs)

        # Matériaux tab (toujours visible, après params_panel init)
        # Matériaux: plus d'onglet permanent — il s'ouvre à la
        # demande depuis le bouton « ? » du panneau Paramètres
        self._materials_panel = None

        # Proportions (31% - 34.5% - 34.5%)
        splitter.setSizes([310, 345, 345])

        # Les trois colonnes, ou la page des Paramètres: l'une OU
        # l'autre sur toute la fenêtre
        from PySide6.QtWidgets import QStackedWidget
        self._pile_centrale = QStackedWidget()
        self._pile_centrale.addWidget(splitter)
        self._pile_centrale.addWidget(self.params_panel)
        self.setCentralWidget(self._pile_centrale)

    def _on_col1_tab_changed(self, index: int):
        """L'onglet Paramètres ouvre la page; les autres se
        montrent."""
        widget = self._col1_tabs.widget(index)
        if widget is self._params_lanceur:
            # l'onglet ne reste pas « choisi »: on revient à celui
            # d'avant, et la page couvre la fenêtre
            self._col1_tabs.blockSignals(True)
            self._col1_tabs.setCurrentIndex(self._onglet_col1_precedent)
            self._col1_tabs.blockSignals(False)
            self.afficher_parametres()
            return
        self._onglet_col1_precedent = index
        if widget is self._file_panel:
            self._rafraichir_panneau_fichier()

    def afficher_parametres(self):
        """La page des Paramètres, sur toute la fenêtre."""
        self._pile_centrale.setCurrentWidget(self.params_panel)
        self.params_panel.setFocus()

    def masquer_parametres(self):
        """Retour aux trois colonnes (ou à la fiche ouverte)."""
        page = (getattr(self, '_fiche_place', None) or {}).get('page')
        if page is not None:
            self._pile_centrale.setCurrentWidget(page)
        else:
            self._pile_centrale.setCurrentIndex(0)

    # ── La fiche d'un outil, à la place des colonnes 1 et 2 ──

    def fiche_ouverte(self):
        """La fiche hébergée en colonnes 1 et 2 (ou None)."""
        return getattr(self, '_fiche_hote', None)

    def montrer_fiche(self, fiche) -> bool:
        """La fiche d'un outil prend la place des colonnes 1 et 2; la
        colonne 3 (le tableau, le catalogue) reste à côté. False quand
        il n'y a pas de place (tableau dans toute la fenêtre): la fiche
        reste dans son panneau."""
        if self.outils_en_plein() or self.parametres_affiches():
            return False
        with self.fiche_remplacee():
            hote = self.fiche_ouverte()
            if hote is not None and hote is not fiche:
                # l'autre fiche se ferme par son panneau (il la connaît)
                if self.tool_manager_panel._fiche is hote:
                    self.tool_manager_panel.fermer_fiche()
                elif self.catalogue_panel._fiche is hote:
                    self.catalogue_panel.fermer_fiche()
            if self.fiche_ouverte() is not None:
                self.masquer_fiche()        # (la page reste)
            place = getattr(self, '_fiche_place', None)
            if place is not None:
                # la page de la fiche d'avant, la colonne 3 dedans: la
                # nouvelle prend sa place, aux mêmes largeurs
                page = place['page']
                page.insertWidget(0, fiche)
                fiche.show()
                if place.get('tailles_page'):
                    page.setSizes(place['tailles_page'])
                self._pile_centrale.setCurrentWidget(page)
                self._fiche_hote = fiche
                return True
            self._nouvelle_page_de_fiche(fiche)
        return True

    @contextmanager
    def fiche_remplacee(self):
        """Une fiche en remplace une autre dans le même geste (outil
        suivant du tableau, Ajouter, référence du catalogue): celle qui
        part laisse sa page, la colonne 3 dedans, et la suivante la
        reprend. Rendre la colonne 3 au splitter puis l'y reprendre
        repolissait deux fois tout le tableau des outils. Sans fiche
        suivante, les colonnes reviennent à la fin du geste."""
        self._remplacement_fiche = getattr(
            self, '_remplacement_fiche', 0) + 1
        try:
            yield
        finally:
            self._remplacement_fiche -= 1
            if (not self._remplacement_fiche
                    and getattr(self, '_fiche_place', None)
                    and self.fiche_ouverte() is None):
                self.masquer_fiche()

    def _nouvelle_page_de_fiche(self, fiche) -> None:
        from PySide6.QtWidgets import QSplitter
        col1, col2, col3 = self.colonnes()
        gauche = sum(c.width() for c in (col1, col2) if c.isVisible())
        droite = col3.width() if col3.isVisible() else 0
        total = max(self._splitter.width(), gauche + droite, 800)
        if gauche < 300:
            gauche = max(500, total - max(droite, 400))
        droite = max(300, total - gauche)
        page = QSplitter(Qt.Orientation.Horizontal)
        page.setChildrenCollapsible(False)
        self._fiche_place = {
            'index': self._splitter.indexOf(col3),
            'tailles': list(self._splitter.sizes()),
            'cachee': col3.isHidden(), 'page': page}
        page.addWidget(fiche)
        page.addWidget(col3)          # la colonne 3 passe à côté
        col3.setVisible(True)
        self._pile_centrale.addWidget(page)
        self._pile_centrale.setCurrentWidget(page)
        page.setSizes([gauche, droite])
        self._fiche_hote = fiche

    def fermer_fiche_ouverte(self) -> None:
        """La fiche hébergée en colonnes 1 et 2 se ferme par son
        panneau (il la connaît): les trois colonnes reviennent."""
        hote = self.fiche_ouverte()
        if hote is None:
            return
        if self.tool_manager_panel._fiche is hote:
            self.tool_manager_panel.fermer_fiche()
        elif self.catalogue_panel._fiche is hote:
            self.catalogue_panel.fermer_fiche()
        self.masquer_fiche()

    def masquer_fiche(self, fiche=None) -> None:
        """Rend les colonnes 1 et 2 (la fiche est détachée: son panneau
        la détruit ou la reprend)."""
        place = getattr(self, '_fiche_place', None)
        if not place:
            return
        hote = self._fiche_hote
        if fiche is not None and fiche is not hote:
            return
        if hote is not None and getattr(self, '_remplacement_fiche', 0):
            # une autre fiche la remplace (même geste): seule la fiche
            # part, la page l'attend
            place['tailles_page'] = place['page'].sizes()
            hote.hide()
            hote.setParent(None)
            self._fiche_hote = None
            return
        col3 = self._col3_tabs
        self._splitter.insertWidget(place['index'], col3)
        col3.setVisible(not place['cachee'])
        self._splitter.setSizes(place['tailles'])
        if self._pile_centrale.currentWidget() is place['page']:
            self._pile_centrale.setCurrentIndex(0)
        if hote is not None:
            hote.hide()
            hote.setParent(None)
        self._pile_centrale.removeWidget(place['page'])
        place['page'].deleteLater()
        self._fiche_place = None
        self._fiche_hote = None

    def _ouvrir_fiche_outil_depuis_catalogue(self, tool_id: str) -> None:
        """« Fiche tools.json » du catalogue: la fiche de l'outil de la
        bibliothèque (le tableau des outils en colonne 3)."""
        self.catalogue_panel.fermer_fiche()
        self.montrer_onglet(self.tool_manager_panel)
        self.tool_manager_panel.ouvrir_fiche_outil(tool_id)

    def parametres_affiches(self) -> bool:
        return self._pile_centrale.currentWidget() is self.params_panel

    # Palette de couleurs cyclées pour les onglets programmes
    _TAB_COLORS = ["#89b4fa", "#a6e3a1", "#fab387", "#cba6f7",
                   "#94e2d5", "#f9e2af", "#f38ba8", "#74c7ec"]

    def _update_prog_tabbar_style(self):
        """Met à jour le style des onglets programmes selon le thème actif.
        Onglets plus grands et contrastés; la couleur PAR onglet est
        appliquée via setTabTextColor dans _refresh_tab_titles."""
        from src.gui.theme import THEMES, get_current_theme
        c = THEMES.get(get_current_theme(), THEMES["Mocha"])
        self._prog_tabbar.setStyleSheet(f"""
            QTabBar::tab {{
                background: {c['surface']};
                color: {c['text_muted']};
                padding: 8px 22px;
                border: 1px solid {c['border']};
                border-bottom: 3px solid transparent;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 3px;
                font-size: 13px;
                font-weight: bold;
                max-width: 220px;
            }}
            QTabBar::tab:selected {{
                background: {c['bg']};
                border: 1px solid {c['accent']};
                border-bottom: 3px solid {c['accent']};
                font-size: 14px;
            }}
            QTabBar::tab:hover:!selected {{
                background: {c['surface_hover']};
                border-bottom: 3px solid {c['accent_hover']};
            }}
            QTabBar::close-button {{
                image: none;
                width: 14px;
                height: 14px;
                border-radius: 7px;
                margin: 2px;
            }}
            QTabBar::close-button:hover {{
                background: {c['red']};
            }}
            QTabBar QToolButton {{
                background: {c['surface']};
                border: 1px solid {c['border']};
                border-radius: 3px;
                padding: 2px;
                margin: 1px;
            }}
            QTabBar QToolButton:hover {{
                background: {c['accent']};
            }}
            QTabBar QToolButton::left-arrow {{
                image: none;
            }}
            QTabBar QToolButton::right-arrow {{
                image: none;
            }}
        """)
        # Bouton + : même forme qu'un onglet, accolé à la barre
        # (border-radius Qt: pas de raccourci 4 valeurs — coins séparés)
        if hasattr(self, '_new_prog_btn'):
            self._new_prog_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {c['surface']};
                    color: {c['accent']};
                    font-weight: bold;
                    font-size: 18px;
                    border: 1px solid {c['border']};
                    border-bottom: 3px solid transparent;
                    border-top-left-radius: 6px;
                    border-top-right-radius: 6px;
                    padding: 2px 0px;
                }}
                QPushButton:hover {{
                    background: {c['accent']};
                    color: {c['bg']};
                    border-bottom: 3px solid {c['accent']};
                }}
            """)

    def _setup_statusbar(self):
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)

        # (Fichier, NDS, H et Tips ont quitté la barre d'état: ils
        # tenaient 400 px devant les onglets de programmes. Fichier est
        # le 1er onglet de la colonne 1, NDS s'ouvre depuis « + Opé »,
        # Historique et Tips sont des onglets de la colonne 2.)

        # Les onglets commencent au BORD GAUCHE: depuis que les
        # quatre boutons sont partis, l'espace réservé devant eux
        # n'était plus qu'un trou.

        # Onglets programmes NDP (zone agrandie et centrée)
        self._prog_tabbar = QTabBar()
        self._prog_tabbar.setTabsClosable(True)
        self._prog_tabbar.setMovable(True)
        self._prog_tabbar.setExpanding(False)
        self._prog_tabbar.setUsesScrollButtons(True)
        self._prog_tabbar.setElideMode(Qt.TextElideMode.ElideRight)
        self._prog_tabbar.setMaximumHeight(40)
        self._prog_tabbar.setDrawBase(False)
        self._update_prog_tabbar_style()
        self._prog_tabbar.addTab("P1")
        self._prog_tabbar.currentChanged.connect(self._on_prog_tab_changed)
        self._prog_tabbar.tabCloseRequested.connect(
            self._on_prog_tab_close)
        self._prog_tabbar.tabBarDoubleClicked.connect(
            self._on_prog_tab_dblclick)
        self._prog_tabbar.tabMoved.connect(self._on_prog_tab_moved)
        # Expanding + stretch fort: la zone d'onglets prend la majorité
        # de l'espace flexible (des onglets étaient écrasés/cachés avec
        # beaucoup d'onglets restaurés). Pas de largeur max.
        self._prog_tabbar.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._statusbar.addWidget(self._prog_tabbar, 6)
        # Menu contextuel (dupliquer / renommer / fermer)
        self._prog_tabbar.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self._prog_tabbar.customContextMenuRequested.connect(
            self._on_tab_context_menu)

        # Bouton + pour nouveau programme (forme d'onglet). Icône
        # DESSINÉE: le « + » en texte disparaissait selon le thème.
        from src.gui.icons import get_button_icon
        self._new_prog_btn = QPushButton("")
        self._new_prog_btn.setIcon(get_button_icon("add", 16))
        self._new_prog_btn.setFixedWidth(34)
        self._new_prog_btn.setMaximumHeight(36)
        self._new_prog_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._new_prog_btn.setToolTip("Nouveau programme")
        self._new_prog_btn.clicked.connect(self._on_new_prog_tab)
        self._statusbar.addWidget(self._new_prog_btn)

        self._status_label = QLabel("Prêt")
        # Un message long (« Session restaurée (3 onglets)… ») ne doit
        # pas élargir la fenêtre: 1 338 px de minimum, c'était lui
        self._status_label.setMinimumWidth(40)
        self._statusbar.addWidget(self._status_label, stretch=1)

        self._ops_label = QLabel("")
        self._ops_label.setMinimumWidth(40)
        self._statusbar.addPermanentWidget(self._ops_label)

        # L'état du code SimPL, en couleur: à jour (vert), en attente
        # d'une pause (orange), bloqué ou en erreur (rouge)
        self._etat_code_label = QLabel("")
        self._etat_code_label.setObjectName("etat_code")
        self._statusbar.addPermanentWidget(self._etat_code_label)

        # La progression des calculs longs (parcours, gamme, export):
        # texte, barre, Annuler — ici, pas dans une fenêtre
        from src.gui.progression import ZoneProgression
        self._zone_progression = ZoneProgression()
        self._statusbar.addPermanentWidget(self._zone_progression)

        # Barre de progression pour la génération de code
        self._progress_bar = QProgressBar()
        self._progress_bar.setMaximumWidth(120)
        self._progress_bar.setMaximumHeight(16)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setRange(0, 0)  # Mode indéterminé (animation)
        self._progress_bar.setVisible(False)
        self._progress_bar.setStyleSheet(
            "QProgressBar { border: 1px solid #45475a; border-radius: 4px; "
            "background: #313244; }"
            "QProgressBar::chunk { background: #89b4fa; border-radius: 3px; }")
        self._statusbar.addPermanentWidget(self._progress_bar)

        # Aide — petit label cliquable
        self._help_btn = QPushButton("?")
        self._help_btn.setMaximumWidth(24)
        self._help_btn.setMaximumHeight(22)
        self._help_btn.setToolTip("À propos de NeoDrive")
        self._help_btn.setStyleSheet(
            "QPushButton { font-size: 12px; font-weight: bold; "
            "border-radius: 11px; padding: 0; }")
        self._help_btn.clicked.connect(self._on_about)
        self._statusbar.addPermanentWidget(self._help_btn)

        # Colonnes: replier ce dont on n'a pas besoin, d'un clic.
        # Un écran d'atelier est large mais on ne regarde qu'une
        # chose à la fois.
        self._btn_colonnes = {}
        for index, (libelle, aide) in enumerate((
                ("1", "Opérations, fichier, paramètres"),
                ("2", "Code SimPl, DXF to Op, édition"),
                ("3", "Canva, outils, symboles"))):
            bouton = QPushButton(libelle)
            bouton.setCheckable(True)
            bouton.setChecked(True)
            bouton.setMaximumHeight(22)
            bouton.setMaximumWidth(24)
            bouton.setToolTip(
                f"Colonne {libelle} — {aide}\n"
                f"Ctrl+{libelle} pour replier ou déplier")
            bouton.setStyleSheet(
                "QPushButton { font-size: 11px; padding: 0 4px; }"
                "QPushButton:checked { color: #a6e3a1; }")
            bouton.toggled.connect(
                lambda coche, i=index: self.basculer_colonne(i, coche))
            self._statusbar.addPermanentWidget(bouton)
            self._btn_colonnes[index] = bouton
        # L'ancien bouton « DXF » reste, sous le nom de la colonne 3
        self._dxf_toggle_btn = self._btn_colonnes[2]

        # Les onglets en fenêtres (plusieurs écrans) et les dispositions
        from src.gui.fenetres import GestionnaireOnglets
        from src.gui.icons import get_button_icon
        self.onglets_fenetres = GestionnaireOnglets(
            self, self.colonnes(), non_detachables=[self._params_lanceur],
            splitter=self._splitter)
        self.onglets_fenetres.lire_reglages = \
            lambda: self.params_panel._app_settings
        self.onglets_fenetres.ecrire_reglages = \
            self.params_panel.save_app_settings
        self.onglets_fenetres.change.connect(
            lambda _cle: self._sur_onglet_col3(
                self._col3_tabs.currentIndex()))
        # le Canva 3D peut vivre dans n'importe quelle colonne: chacune
        # dit quand il se montre
        for tabs in self.colonnes()[:2]:
            tabs.currentChanged.connect(
                lambda _i: self._sur_onglet_col3(-1))
        # le formulaire d'opé à part (onglet « Formulaire »), et le clic
        # droit sur les onglets qui le propose
        self.onglets_fenetres.menu_extra = self._menu_extra_onglet
        self.onglets_fenetres.change.connect(self._suivre_place_formulaire)
        self.operations_panel.formulaire_separe_demande.connect(
            self.separer_formulaire)
        reglage = self.params_panel._app_settings.get('formulaire_separe')
        if isinstance(reglage, int) and 0 <= reglage <= 2:
            self.separer_formulaire(True, reglage, memoriser=False)
        self._btn_dispositions = QPushButton("")
        self._btn_dispositions.setIcon(get_button_icon("grid", 14))
        self._btn_dispositions.setMaximumHeight(22)
        self._btn_dispositions.setMaximumWidth(28)
        self._btn_dispositions.setToolTip(
            "Fenêtres et dispositions: enregistrer la disposition (onglets "
            "sortis en fenêtres, écrans, colonnes) sous un nom, en rouvrir "
            "une, tout remettre en place.\nSortir un onglet: le tirer hors "
            "de sa barre, ou clic droit sur l'onglet.")
        self._menu_dispositions = QMenu(self._btn_dispositions)
        self._menu_dispositions.aboutToShow.connect(
            self._remplir_menu_dispositions)
        self._btn_dispositions.setMenu(self._menu_dispositions)
        self._statusbar.addPermanentWidget(self._btn_dispositions)

    def _remplir_menu_dispositions(self) -> None:
        self._menu_dispositions.clear()
        self.onglets_fenetres.remplir_menu_dispositions(
            self._menu_dispositions)

    def colonne_de(self, widget) -> int:
        """La colonne (0, 1, 2) d'un onglet — où il vit ou rentrera."""
        gestion = getattr(self, 'onglets_fenetres', None)
        if gestion is not None:
            c = gestion.colonne_de(widget)
            if c >= 0:
                return c
        for c, tabs in enumerate(self.colonnes()):
            if tabs.indexOf(widget) >= 0:
                return c
        return 2

    def onglet_actif(self, widget) -> bool:
        """L'onglet est-il celui qu'on voit dans sa colonne?"""
        return any(t.currentWidget() is widget for t in self.colonnes())

    # ── le formulaire d'opé à part ──

    #: la colonne où le formulaire va quand on le met à part
    COLONNE_FORMULAIRE = 1

    def separer_formulaire(self, oui: bool, colonne: int = None,
                           memoriser: bool = True) -> None:
        """Le formulaire d'opé dans son propre onglet « Formulaire »
        (oui; dans `colonne`, la 2e par défaut), ou sous la liste."""
        op = self.operations_panel
        gestion = self.onglets_fenetres
        if oui and not op.formulaire_separe():
            page = op.detacher_formulaire()
            c = self.COLONNE_FORMULAIRE if colonne is None else int(colonne)
            gestion.ajouter(page, "Formulaire", c,
                            bulle="Le formulaire de l'opération choisie (à "
                                  "part de la liste: clic droit pour le "
                                  "déplacer ou le remettre)",
                            cle="formulaire")
        elif not oui and op.formulaire_separe():
            gestion.retirer(op.page_formulaire)
            op.rattacher_formulaire()
            self.montrer_onglet(op)
        if memoriser:
            reglages = self.params_panel._app_settings
            if op.formulaire_separe():
                reglages['formulaire_separe'] = self.colonne_de(
                    op.page_formulaire)
            else:
                reglages.pop('formulaire_separe', None)
            self.params_panel.save_app_settings()

    def _suivre_place_formulaire(self, _cle=None) -> None:
        """Le formulaire à part a changé de colonne: on la retient."""
        op = self.operations_panel
        if not op.formulaire_separe():
            return
        reglages = self.params_panel._app_settings
        c = self.colonne_de(op.page_formulaire)
        if reglages.get('formulaire_separe') != c:
            reglages['formulaire_separe'] = c
            self.params_panel.save_app_settings()

    def _menu_extra_onglet(self, menu, widget) -> None:
        """Au clic droit d'un onglet: le formulaire à part, ou dessous."""
        op = self.operations_panel
        if widget is op and not op.formulaire_separe():
            menu.addSeparator()
            menu.addAction("Séparer le formulaire (onglet à part)"
                           ).triggered.connect(
                lambda: self.separer_formulaire(True))
        elif widget is op.page_formulaire and op.formulaire_separe():
            menu.addSeparator()
            menu.addAction("Remettre le formulaire sous la liste"
                           ).triggered.connect(
                lambda: self.separer_formulaire(False))
        elif widget is self.dxf_panel or widget is self.vue3d_panel:
            menu.addSeparator()
            self._remplir_menu_place_3d(menu)

    def montrer_onglet(self, widget) -> None:
        """Fait voir un onglet des colonnes — sa fenêtre devant s'il est
        sorti."""
        gestion = getattr(self, 'onglets_fenetres', None)
        if gestion is not None and gestion.cle_de(widget) is not None:
            gestion.montrer(widget)
            return
        for tabs in self.colonnes():
            if tabs.indexOf(widget) >= 0:
                tabs.setCurrentWidget(widget)

    def _setup_shortcuts(self):
        """Configure les raccourcis clavier globaux."""
        QShortcut(QKeySequence("Ctrl+N"), self, self._on_new)
        QShortcut(QKeySequence("Ctrl+O"), self, self._on_open)
        QShortcut(QKeySequence("Ctrl+S"), self, self._on_save)
        QShortcut(QKeySequence("Ctrl+Shift+S"), self, self._on_save_as)
        QShortcut(QKeySequence("Ctrl+E"), self, self._on_export_simpl)
        QShortcut(QKeySequence("Ctrl+B"), self, self._on_browse)
        QShortcut(QKeySequence("Ctrl+T"), self, self._on_tool_manager)
        QShortcut(QKeySequence("F11"), self, self._toggle_fullscreen)
        # Suppr: ce qu'on a choisi en dernier — une opération, ou
        # des entités du canvas
        QShortcut(QKeySequence("Delete"), self,
                  self.supprimer_selon_le_dernier_choix)
        QShortcut(QKeySequence("Ctrl+D"), self,
                  self.operations_panel._on_duplicate)
        QShortcut(QKeySequence("Ctrl+Shift+E"), self,
                  self._on_toggle_current_op)
        QShortcut(QKeySequence("F5"), self, self._regenerate_code)
        # Colonnes: replier/déplier
        for index in (0, 1, 2):
            QShortcut(QKeySequence(f"Ctrl+{index + 1}"), self,
                      lambda i=index: self.basculer_colonne(i))
        # Undo/Redo « par volet »: Ctrl+Z/Y agit sur le DESSIN quand le
        # canvas a le focus, sur les OPÉRATIONS sinon. (Le raccourci
        # fenêtre intercepte avant le widget: on route donc ici.)
        QShortcut(QKeySequence("Ctrl+Z"), self,
                  lambda: self._undo_du_volet_actif(False))
        QShortcut(QKeySequence("Ctrl+Y"), self,
                  lambda: self._undo_du_volet_actif(True))
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self,
                  lambda: self._undo_du_volet_actif(True))

    def _canvas_a_le_focus(self) -> bool:
        """Le canvas du dessin (ou son viewport) a-t-il le focus ?"""
        from PySide6.QtWidgets import QApplication
        canvas = getattr(getattr(self, 'dxf_panel', None), 'canvas', None)
        if canvas is None:
            return False
        fw = QApplication.focusWidget()
        if fw is None:
            return False
        return fw is canvas or canvas.isAncestorOf(fw)

    def _undo_du_volet_actif(self, redo: bool):
        """Route l'annuler/rétablir vers le volet qui a le focus."""
        canvas = getattr(getattr(self, 'dxf_panel', None), 'canvas', None)
        if canvas is not None and self._canvas_a_le_focus():
            canvas.redo() if redo else canvas.undo()
        else:
            self.undo_stack.redo() if redo else self.undo_stack.undo()

    #: ce que Suppr vise: ce qu'on a choisi en DERNIER — une
    #: opération (dans la liste, ou par son formulaire) ou des
    #: entités du canvas. Des entités restées sélectionnées après une
    #: retouche d'opération partaient à la place de l'opération.
    _dernier_choix = 'ops'

    def noter_choix(self, quoi: str):
        if quoi in ('ops', 'canvas'):
            self._dernier_choix = quoi

    def supprimer_selon_le_dernier_choix(self) -> str:
        """Rend ce qui a été supprimé: 'canvas', 'ops' ou ''."""
        canvas = getattr(getattr(self, 'dxf_panel', None), 'canvas', None)
        selection = []
        if canvas is not None:
            try:
                selection = canvas.selection_courante()
            except Exception:
                selection = []
        if self._dernier_choix == 'canvas' and selection:
            canvas._delete_selected()
            return 'canvas'
        if self.operations_panel._current_index >= 0 \
                and self.operations_panel.program.operation_count:
            self.operations_panel._on_delete()
            return 'ops'
        if selection:
            canvas._delete_selected()
            return 'canvas'
        return ''

    def _on_toggle_current_op(self):
        """Raccourci: active/désactive l'opération sélectionnée."""
        idx = self.operations_panel._current_index
        if idx >= 0:
            self.operations_panel._on_toggle_operation(idx)

    def _connect_signals(self):
        """Connecte les signaux entre les panneaux."""
        self.operations_panel.code_needs_update.connect(
            self._schedule_regen)
        # qui lit le code (export, copie, simulation, contrôles) le
        # reçoit à jour, même si la régénération attendait une pause
        self.code_panel.avant_lecture = self.code_a_jour
        # ce qu'on choisit en dernier, Suppr le vise
        self.operations_panel.op_list.operation_selected.connect(
            lambda _i: self.noter_choix('ops'))
        self.operations_panel.param_form.params_changed.connect(
            lambda _p: self.noter_choix('ops'))
        self.dxf_panel.entites_choisies.connect(
            lambda: self.noter_choix('canvas'))
        self._rewire_program_signals()

        # DXF -> coordonnées
        self.dxf_panel.coordinate_picked.connect(
            self.operations_panel.inject_coordinates)

        # Refresh GenOps
        self.circle_ops_panel.refresh_btn.clicked.connect(
            self._refresh_circle_ops)
        # Un DXF fraîchement importé remplit la liste TOUT DE SUITE:
        # il fallait penser à cliquer « Rafraîchir » pour voir les
        # centres du dessin qu'on venait d'ouvrir
        self.dxf_panel.circles_detected.connect(
            self._on_circles_detected)

        # DXF -> points
        self.dxf_panel.selected_centers.connect(
            self.operations_panel.inject_points)

        # Code panel export
        self.code_panel.export_btn.clicked.connect(
            self._on_export_simpl)
        self.code_panel.dossier_export_btn.clicked.connect(
            self.ouvrir_dossier_export)
        self._maj_bouton_dossier_export()

        # Ordre outils (bouton migré dans code_panel)
        self.code_panel.optimize_btn.clicked.connect(
            self.operations_panel._on_optimize_tool_order)

        # Blocage génération
        self.operations_panel.param_form.generation_blocked.connect(
            self._on_generation_blocked)

        # Tab changes
        self._col2_tabs.currentChanged.connect(self._on_tab_changed)

        # Op active → canvas + code auto-fold. Le canvas montre TOUT
        # le programme, pas seulement l'opération sélectionnée: on
        # veut voir la pièce, pas un usinage isolé.
        self.operations_panel.active_operation_changed.connect(
            self._sur_op_active)
        # Refresh canvas on param changes (pattern/coords updates).
        # DIFFÉRÉ: cocher dix opérations d'affilée redessinait dix
        # fois toute la pièce, chaque passe coûtant plus que le clic.
        self.operations_panel.code_needs_update.connect(
            self._schedule_canvas_refresh)
        # transparence / division réglée au panneau du Canva 3D
        # l'œil d'une opé basculé au panneau 3D: la liste et les deux
        # canvas le suivent (le code du 3D écarte les opés masquées)
        self.dxf_panel.oeil_op_change.connect(
            lambda _op: (self.operations_panel._refresh_list(),
                         self.operations_panel.code_needs_update.emit()))
        self.dxf_panel.affichage_ops_change.connect(
            self._sur_affichage_ops_3d)
        self.operations_panel.affichage_ops_modifie.connect(
            self._sur_affichage_ops_liste)
        self.operations_panel.op_list.itemSelectionChanged.connect(
            self._suivre_selection_dans_le_3d)
        self.operations_panel.active_operation_changed.connect(
            self._on_active_op_for_fold)

        # GenOps ↔ Canvas
        self.circle_ops_panel.points_changed.connect(
            lambda pts: self.dxf_panel.canvas.draw_operation_points(
                pts, source="genops"))
        # (Le clic sur un marqueur du canvas est branché par
        # `_preparer_canvas`: il y a un canvas par onglet.)
        # Clic sur le n° d'une rangée du tableau → surligner au canva
        self.operations_panel.param_form.point_focus_requested.connect(
            self._on_point_focus_requested)
        self.circle_ops_panel.point_selected.connect(
            self._on_genops_point_selected)
        self.circle_ops_panel.retrait_bascule.connect(
            self._on_retrait_points_bascule)
        self.circle_ops_panel.add_points_to_op.connect(
            self.operations_panel.inject_points)

        # Specs programme: résumé au-dessus des opérations
        self.params_panel.program_specs_changed.connect(
            self.operations_panel.set_specs_summary)
        self.operations_panel.set_specs_summary(
            self.params_panel.specs_summary())

        # Expert mode checkbox dans l'onglet Paramètres
        self.params_panel._expert_cb.toggled.connect(self._on_expert_toggle)
        self.params_panel.material_help_requested.connect(
            self._on_material_help)
        self.params_panel.categories_order_changed.connect(
            lambda _noms: self.operations_panel._rebuild_add_panel())

        # Thème et police dans l'onglet Paramètres
        self.params_panel._theme_combo.currentTextChanged.connect(
            self._on_theme_changed)
        self.params_panel._font_combo.currentIndexChanged.connect(
            self._on_font_size_changed)

    def _couleurs_outils_changees(self, *args):
        canvas = getattr(self.dxf_panel, 'canvas', None)
        if canvas is not None:
            canvas.reset_tool_colors()
        self._schedule_canvas_refresh()
        if hasattr(self.dxf_panel, 'actualiser_3d') and \
                getattr(self.dxf_panel, '_canvas3d', None) is not None:
            self.dxf_panel.actualiser_3d()

    def _schedule_canvas_refresh(self, *args):
        """Redessin du canvas groupé sur la fin de la salve."""
        timer = getattr(self, '_canvas_timer', None)
        if timer is None:
            from PySide6.QtCore import QTimer
            timer = self._canvas_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(40)
            timer.timeout.connect(self._refresh_canvas_op)
        timer.start()

    def _sur_affichage_ops_3d(self) -> None:
        """Une transparence réglée au panneau du Canva 3D: la liste la
        montre, le dessin 2D aussi."""
        rangs = {id(op): i for i, op in enumerate(self.program.operations)}
        for op in self.vue3d_panel.panneau_ops.ops_touchees:
            if id(op) in rangs:
                self.operations_panel._update_list_item_text(rangs[id(op)])
        self._apres_affichage_ops()

    def _sur_affichage_ops_liste(self) -> None:
        """Une transparence réglée au clic droit de la liste."""
        self.vue3d_panel.maj_affichage_ops()
        self.vue3d_panel.panneau_ops._relire()
        self._apres_affichage_ops()

    def _apres_affichage_ops(self) -> None:
        # le programme enregistre ces réglages (NDMETA), mais ce qu'il usine
        # n'a pas bougé: ni la liste, ni le 3D n'ont à se reconstruire
        self.program._modified = True
        self._refresh_tab_titles()
        self._schedule_canvas_refresh()
        self._schedule_regen_reglages()

    def _suivre_selection_dans_le_3d(self) -> None:
        """Les opérations choisies dans la liste: en avant au Canva 3D
        (leurs traits plus larges, les autres estompées), et choisies au
        panneau 3D (ses réglages en lot portent sur elles)."""
        c3 = getattr(self, 'vue3d_panel', None)
        if c3 is None:
            return
        lst = self.operations_panel.op_list
        ops = [self.program.get_operation(r) for r in lst.selected_rows()]
        ops = [o for o in ops if o is not None]
        c3.choisir_ops([getattr(o, 'id', None) for o in ops])
        if c3.panneau_ops.isVisible():
            c3.panneau_ops.selectionner(ops)

    def choisir_op_depuis_3d(self, op_id: str, ajouter: bool = False) -> bool:
        """(le Canva 3D) un clic sur le trait d'une opération: elle est
        choisie dans la liste — Ctrl/Maj: ajoutée ou retirée —, son
        formulaire et le Canva 2D suivent; la ligne d'état la nomme."""
        index = next((i for i, o in enumerate(self.program.operations)
                      if getattr(o, 'id', None) == op_id), -1)
        if index < 0 or not self.operations_panel.choisir_operation(
                index, ajouter):
            return False
        op = self.program.operations[index]
        self.noter_choix('ops')
        self.statusBar().showMessage(
            f"Canva 3D: opération {index + 1} « {op.name} » choisie", 4000)
        return True

    #: la régénération part ce délai (ms) après la dernière
    #: modification — puis attend que l'utilisateur marque une pause
    REGEN_DIFFERE_MS = 150

    #: l'état du code SimPL: (couleur du thème, texte, bulle)
    ETATS_CODE = {
        'a_jour': ('green', "SimPL à jour",
                   "Le code affiché est celui du programme."),
        'en_attente': ('orange', "SimPL en attente",
                       "Le programme a changé: le code se met à jour dès "
                       "que vous marquez une pause (l'application reste "
                       "réactive pendant vos réglages).\nL'export, la "
                       "copie et la simulation prennent toujours le code "
                       "à jour."),
        'bloque': ('red', "Génération bloquée",
                   "Le code n'est pas généré: voir le message dans le "
                   "panneau Code."),
        'erreur': ('red', "Erreur de génération",
                   "La génération a échoué: voir le panneau Code et "
                   "l'historique."),
    }

    def _marquer_etat_code(self, etat: str) -> None:
        """Le code couleur de l'état du code (barre d'état et panneau
        Code)."""
        if etat == self._etat_code:
            return
        self._etat_code = etat
        from src.gui.theme import COLORS
        nom, texte, bulle = self.ETATS_CODE[etat]
        couleur = COLORS.get(nom, "#a6adc8")
        lbl = getattr(self, '_etat_code_label', None)
        if lbl is not None:
            lbl.setText(f"<span style='color:{couleur}'>●</span> {texte}")
            lbl.setToolTip(bulle)
        panneau = getattr(self, 'code_panel', None)
        if panneau is not None and hasattr(panneau, 'marquer_etat'):
            panneau.marquer_etat(etat, couleur, texte, bulle)

    def _schedule_regen(self, *args):
        self._regen_reglages_seuls = False
        self._attendre_la_regen()

    def _schedule_regen_reglages(self, *args):
        """Seuls les réglages du programme ont changé (brut, commentaire):
        le code se refait, mais si ce qu'il usine n'a pas bougé, la vue
        3D n'a rien à relire — sauf si une régénération complète
        attendait déjà."""
        if not self._regen_timer.isActive():
            self._regen_reglages_seuls = True
        self._attendre_la_regen()

    def _attendre_la_regen(self) -> None:
        from src.gui import activite
        self._marquer_etat_code('en_attente')
        activite.veiller(self)
        self._regen_timer.start(self.REGEN_DIFFERE_MS)

    def _regen_quand_libre(self) -> None:
        """La minuterie est échue: le SimPL se refait — sauf si
        l'utilisateur est en plein geste (clic, frappe, glisser): la
        régénération attend sa pause (basse priorité), l'état reste
        orange. Un clic sur l'opé suivante ne tombe plus sur le calcul
        lancé par la modification d'avant."""
        from src.gui import activite
        if activite.occupe():
            self._regen_timer.start(activite.attente_restante())
            return
        self._regenerate_code()

    def code_a_jour(self) -> None:
        """Le code affiché, à jour: une régénération en attente passe
        tout de suite. Ceux qui lisent le code (export, copie,
        simulation, contrôles) passent par ici
        (`code_panel.avant_lecture`)."""
        if self._regen_en_cours or not self._regen_timer.isActive():
            return
        self._regen_timer.stop()
        self._regenerate_code()

    def _code_complet(self, pr_from, pr_to, expert):
        """Le programme ENTIER, parcours de gravure calculés.

        L'aperçu se contente de ce qui est déjà calculé; un fichier
        qui part à la machine, non. Le calcul peut durer: une barre
        dit où il en est, et l'opérateur peut l'arrêter."""
        from src.codegen.generator import SimPlGenerator
        from src.gui.progression import Progression
        with Progression(self, "Génération du programme",
                         "Calcul des parcours de gravure…") as barre:
            code = barre.executer(lambda b: SimPlGenerator(
                self.program, self.tool_library, pr_from, pr_to,
                expert_settings=expert, calculer=True,
                progression=b).generate())
        return None if barre.annule else code

    def _regenerate_code(self):
        from src.gui import activite
        # ce qui attendait est fait par celle-ci (le programme tel qu'il
        # est): pas une seconde régénération pour rien
        self._regen_timer.stop()
        self._regen_en_cours = True
        self._etat_fin_regen = 'a_jour'
        try:
            self._regenerer_le_code()
        finally:
            self._regen_en_cours = False
            if not self._regen_timer.isActive():
                activite.relacher(self)
                self._marquer_etat_code(self._etat_fin_regen)

    def _regenerer_le_code(self):
        reglages_seuls = getattr(self, '_regen_reglages_seuls', False)
        self._regen_reglages_seuls = False
        if self._generation_blocked:
            self._progress_bar.setVisible(False)
            blocked_msg = self.operations_panel.param_form._depth_warning
            if blocked_msg and "Outil requis" in (blocked_msg.text() or ""):
                self.code_panel.set_code(
                    "# BLOQUÉ: Un outil doit être sélectionné "
                    "pour chaque opération qui le requiert.")
                self._etat_fin_regen = 'bloque'
                self._ops_label.setText("Génération bloquée")
                self._suivre_en_3d()
                return
            if not self._expert_mode:
                self.code_panel.set_code(
                    "# BLOQUÉ: La profondeur dépasse la capacité de "
                    "l'outil.\n# Réduisez la profondeur ou activez le "
                    "Mode Expert (onglet Paramètres).")
                self._etat_fin_regen = 'bloque'
                self._ops_label.setText("Génération bloquée")
                self._suivre_en_3d()
                return
        try:
            pr_from, pr_to = self.params_panel.get_path_replacement()
            expert = self.params_panel.get_expert_settings()
            generator = SimPlGenerator(
                self.program, self.tool_library, pr_from, pr_to,
                expert_settings=expert, calculer=False)
            code = generator.generate()
            self.code_panel.set_code(code, generator.code_marque)
            ops_text = f"{self.program.operation_count} opération(s)"
            # Une gravure dont l'outil ne peut rien enlever est
            # écartée du programme: le dire, sans quoi l'opérateur
            # cherche une séquence qui n'existe pas.
            muettes = getattr(generator, 'ops_sans_parcours', None)
            if muettes:
                noms = ", ".join(nom for nom, _raison in muettes)
                ops_text += f" · {len(muettes)} écartée(s): {noms}"
            # Les gravures dont le parcours n'est pas calculé ne
            # sortent pas: l'aperçu ne lance pas des minutes de
            # calcul à chaque frappe. Le dire, avec le geste à faire.
            a_calculer = getattr(generator, 'ops_a_calculer', None)
            if a_calculer:
                ops_text += (f" · {len(a_calculer)} à calculer "
                             f"({', '.join(a_calculer)})")
            # Le bloc NDMETA manque: le programme rouvert perdrait les
            # réglages de ses opérations — le dire, là où l'on regarde
            if getattr(generator, 'meta_erreur', None):
                ops_text += (" · ⚠ NDMETA absent: réouverture "
                             "incomplète")
                self._log_action(
                    f"NDMETA absent: {generator.meta_erreur}")
            # Estimation temps d'usinage total (coupe uniquement)
            try:
                from src.core.time_estimator import (
                    estimate_program_seconds, format_duration)
                total, known, unknown = estimate_program_seconds(
                    self.program, self.tool_library)
                if total > 0.5:
                    ops_text += f" · usinage {format_duration(total)}"
                    if unknown:
                        ops_text += f" (+{unknown} non estimée(s))"
            except Exception:
                pass
            self._ops_label.setText(ops_text)
        except Exception as e:
            self.code_panel.set_code(f"# ERREUR de génération:\n# {e}")
            self._etat_fin_regen = 'erreur'
            self._log_action(f"Erreur génération: {e}")
        finally:
            self._progress_bar.setVisible(False)
        self._suivre_en_3d(reglages_seuls)
        # Le brut du programme courant suit ses réglages (et l'onglet)
        try:
            self.dxf_panel.canvas.set_workpiece(self.program.settings)
        except Exception:
            pass

    def _suivre_en_3d(self, reglages_seuls: bool = False) -> None:
        """La vue 3D suit le code: sur TOUS les chemins de la
        régénération. Un code bloqué ou en erreur ne la laissait pas
        relire: elle gardait les parcours d'avant, ceux d'un autre
        onglet compris."""
        try:
            if not (reglages_seuls and self.dxf_panel.reglages_seuls_changes()):
                self.dxf_panel.planifier_actualisation_3d()
        except Exception:
            pass

    # ----- Menu Fichier inline dans col1 -----

    #: programmes récemment ouverts, du plus récent au plus ancien
    _RECENTS_MAX = 5

    def recents(self) -> list:
        return list(self.params_panel._app_settings.get(
            'recent_programs', []))[:self._RECENTS_MAX]

    def _noter_recent(self, chemin: str) -> None:
        """Range un programme en tête des récents."""
        if not chemin:
            return
        import os
        chemin = os.path.abspath(chemin)
        liste = [c for c in self.recents()
                 if os.path.abspath(c) != chemin]
        liste.insert(0, chemin)
        self.params_panel._app_settings['recent_programs'] = \
            liste[:self._RECENTS_MAX]
        self.params_panel.save_app_settings()

    def _ouvrir_recent(self, chemin: str) -> None:
        """Clic sur un programme récent."""
        self.hide_col1_overlay(self._file_panel)
        self._ouvrir_programme(chemin)

    def _ouvrir_programme(self, filepath: str) -> None:
        """Ctrl+O, Parcourir, Programmes récents.

        Le programme s'ouvre dans l'onglet courant s'il n'y a rien à y
        perdre, dans un onglet NEUF si le courant porte des
        modifications non enregistrées: on les écrasait sans rien
        demander. Déjà ouvert dans un onglet, on y va — relu depuis le
        disque s'il n'y a pas été modifié, laissé tel quel sinon."""
        self._save_current_tab_state()
        cible = os.path.normcase(os.path.abspath(filepath))
        for i, tab in enumerate(self._program_tabs):
            fp = tab.get('filepath') or ''
            if not fp or os.path.normcase(os.path.abspath(fp)) != cible:
                continue
            if i != self._active_tab_index:
                self._prog_tabbar.setCurrentIndex(i)
            if self.program.is_modified:
                self._status_label.setText(
                    f"« {os.path.basename(filepath)} » est déjà ouvert, "
                    "avec des modifications non enregistrées: il n'est "
                    "pas relu.")
                return
            self._load_program(filepath)
            return
        if self.program.is_modified:
            self._on_new_prog_tab()
        self._load_program(filepath)

    def _rafraichir_panneau_fichier(self) -> None:
        """Ligne d'état et récents, avant d'afficher le panneau."""
        import datetime
        import os
        panneau = getattr(self, '_file_panel', None)
        if panneau is None:
            return
        chemin = getattr(self.program, 'filepath', '') or ''
        if chemin:
            try:
                quand = datetime.datetime.fromtimestamp(
                    os.path.getmtime(chemin)).strftime(
                        "%d/%m/%Y à %H:%M")
            except OSError:
                quand = "jamais"
            etat = "modifié depuis" if self.program.is_modified \
                else "à jour"
            texte = (f"{os.path.basename(chemin)} — enregistré le "
                     f"{quand} ({etat})")
        else:
            n = self.program.operation_count
            texte = (f"Programme jamais enregistré — {n} opération(s)"
                     if n else "Programme vide, jamais enregistré")
        panneau.montrer_etat(texte)
        panneau.montrer_recents(self.recents())

    def _importer_dessin(self) -> None:
        """Menu Fichier: ouvrir un dessin et montrer le canvas."""
        self.dxf_panel._on_import()
        self.montrer_onglet(self.dxf_panel)

    def _exporter_dessin(self) -> None:
        """Menu Fichier: exporter le dessin du canvas."""
        self.dxf_panel._on_export()

    def _on_file_action(self, action_id: str):
        """Gère les actions du menu fichier."""
        # Fermer le panneau fichier (restaure la colonne 1)
        self.hide_col1_overlay(self._file_panel)

        actions = {
            'new': self._on_new,
            'open': self._on_open,
            'browse': self._on_browse,
            'reopen_tab': self._on_reopen_closed_tab,
            'import_dessin': self._importer_dessin,
            'export_dessin': self._exporter_dessin,
            'save': self._on_save,
            'save_as': self._on_save_as,
            'save_sub': self._on_save_subprogram,
            'import_sub': self._on_import_subprogram,
            'export': self._on_export_simpl,
            'import_simpl': self._on_import_simpl,
            'save_template': self._on_save_template,
            'auto_programs': self._on_generate_auto_programs,
            'function_key': self._on_export_function_key,
            'load_template': self._on_load_template,
            'quit': self.close,
        }
        fn = actions.get(action_id)
        if fn:
            fn()

    # ----- Actions Fichier -----

    # ── Gestion onglets programmes ──

    def _new_undo_stack(self) -> QUndoStack:
        stack = QUndoStack(self)
        stack.setUndoLimit(100)
        return stack

    def _refresh_tab_titles(self, *args):
        """Rafraîchit les onglets programmes: couleur par onglet et
        indicateur ● pour les programmes modifiés non sauvés."""
        for i, tab in enumerate(self._program_tabs):
            if i >= self._prog_tabbar.count():
                break
            name = tab.get("name", f"P{i + 1}")
            prog = tab.get("program")
            modified = bool(prog is not None and prog.is_modified)
            text = ("● " if modified else "") + name
            if self._prog_tabbar.tabText(i) != text:
                self._prog_tabbar.setTabText(i, text)
            self._prog_tabbar.setTabTextColor(
                i, QColor(self._TAB_COLORS[i % len(self._TAB_COLORS)]))

    def _rewire_program_signals(self, old_prog=None):
        """(Re)branche les signaux du programme ACTIF sur la régénération.
        Sans cela, après un switch d'onglet les modifications de settings
        projet ne régénéraient plus le code (signaux restés sur l'ancien
        programme)."""
        if old_prog is not None and old_prog is not self.program:
            for sig, slot in (
                    (old_prog.changed, self._schedule_regen),
                    (old_prog.settings_changed,
                     self._schedule_regen_reglages),
                    (old_prog.operation_updated, self._schedule_regen),
                    (old_prog.changed, self._refresh_tab_titles),
                    (old_prog.settings_changed, self._refresh_tab_titles)):
                try:
                    sig.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
        self.program.changed.connect(self._schedule_regen)
        self.program.settings_changed.connect(self._schedule_regen_reglages)
        self.program.operation_updated.connect(self._schedule_regen)
        self.program.changed.connect(self._refresh_tab_titles)
        self.program.settings_changed.connect(self._refresh_tab_titles)

    def _save_current_tab_state(self):
        """Sauvegarde l'état du programme courant dans l'onglet actif —
        et son organisation de fenêtre (voir `etat_vue`)."""
        if 0 <= self._active_tab_index < len(self._program_tabs):
            tab = self._program_tabs[self._active_tab_index]
            tab["program"] = self.program
            tab["filepath"] = getattr(self.program, 'filepath', '') or ""
            # (pas pendant la restauration de la session: la fenêtre
            # n'a pas encore l'organisation de l'onglet)
            if not getattr(self, '_restauration_en_cours', False):
                try:
                    tab["vue"] = self.etat_vue()
                except Exception:
                    pass

    # ── L'organisation de la fenêtre, onglet par onglet ──

    def etat_vue(self) -> dict:
        """L'organisation de la fenêtre: largeurs et colonnes visibles,
        onglet actif de chaque colonne, vue du Canva 2D (zoom, centre),
        caméra du Canva 3D. Chaque onglet de programme garde la sienne."""
        cols = self.colonnes()
        etat = {'colonnes': [int(v) for v in self._splitter.sizes()],
                'cachees': [bool(c.isHidden()) for c in cols],
                'onglets': [int(c.currentIndex()) for c in cols]}
        if self.outils_en_plein():
            # « toute la fenêtre » est un moment, pas une organisation
            avant = self._avant_outils_plein
            etat['colonnes'] = [int(v) for v in avant['tailles']]
            etat['cachees'] = [bool(v) for v in avant['cachees']]
            onglet = avant.get('onglet')
            if onglet is not None:
                c = avant.get('colonne', 2)
                etat['onglets'][c] = cols[c].indexOf(onglet)
        try:
            canvas = self.dxf_panel.canvas
            t = canvas.transform()
            centre = canvas.mapToScene(canvas.viewport().rect().center())
            etat['vue2d'] = [float(t.m11()), float(t.m22()),
                             float(centre.x()), float(centre.y())]
        except Exception:
            pass
        c3 = getattr(self, 'vue3d_panel', None)
        if c3 is not None:
            v = c3.vue
            etat['vue3d'] = [float(v.lacet), float(v.elevation),
                             float(v.zoom), float(v.decalage.x()),
                             float(v.decalage.y()),
                             float(getattr(v, 'exag', 1.0))]
        return etat

    def appliquer_vue(self, etat, tailles: bool = True,
                      vue2d: bool = False) -> None:
        """Remet l'organisation `etat` (de `etat_vue`). `tailles`: les
        largeurs des colonnes aussi; `vue2d`: le zoom du Canva 2D (un
        onglet garde déjà son canvas: utile au retour d'une session)."""
        if not isinstance(etat, dict):
            return
        if self.outils_en_plein():
            self.outils_plein_fenetre(False)
        cols = self.colonnes()
        if tailles:
            cachees = etat.get('cachees')
            if isinstance(cachees, list) and len(cachees) == len(cols):
                for c, h in zip(cols, cachees):
                    c.setVisible(not h)
            larg = etat.get('colonnes')
            if isinstance(larg, list) and len(larg) == len(cols) \
                    and sum(int(v) for v in larg) > 0:
                self._splitter.setSizes([int(v) for v in larg])
        indices = etat.get('onglets') or []
        if 'cad_3d' in etat:
            # retenu au temps de l'onglet CAD (0.23 à 0.25): le Canva 2D
            # et le Canva 3D y faisaient un seul onglet
            from src.gui.fenetres import indices_d_avant_cad
            indices = indices_d_avant_cad(
                indices, cols, self.dxf_panel, self.vue3d_panel,
                bool(etat.get('cad_3d')))
        for c, i in zip(cols, indices):
            try:
                if 0 <= int(i) < c.count():
                    c.setCurrentIndex(int(i))
            except (TypeError, ValueError):
                pass
        if vue2d and isinstance(etat.get('vue2d'), list) \
                and len(etat['vue2d']) == 4:
            try:
                from PySide6.QtGui import QTransform
                sx, sy, cx, cy = (float(v) for v in etat['vue2d'])
                canvas = self.dxf_panel.canvas
                canvas.setTransform(QTransform.fromScale(sx, sy))
                canvas.centerOn(cx, cy)
                canvas._zoom = sx
            except Exception:
                pass
        v3 = etat.get('vue3d')
        c3 = getattr(self, 'vue3d_panel', None)
        if c3 is not None and isinstance(v3, list) and len(v3) >= 5:
            from PySide6.QtCore import QPointF
            vue = c3.vue
            vue.lacet, vue.elevation, vue.zoom = (float(v3[0]),
                                                  float(v3[1]),
                                                  float(v3[2]))
            vue.decalage = QPointF(float(v3[3]), float(v3[4]))
            if len(v3) >= 6:
                vue.exag = float(v3[5])
                try:
                    c3.exag.blockSignals(True)
                    c3.exag.setValue(vue.exag)
                    c3.exag.blockSignals(False)
                except Exception:
                    pass
            vue.update()
        try:
            self._maj_boutons_colonnes()
        except Exception:
            pass

    def _next_p_name(self) -> str:
        """Génère le prochain nom P1, P2... disponible."""
        existing = {t['name'] for t in self._program_tabs}
        i = 1
        while f"P{i}" in existing:
            i += 1
        return f"P{i}"

    # ── Dossier d'échange « Programmes outils/Vers NeoDrive » ──

    def _incoming_seen_path(self) -> str:
        return os.path.join(self._base_dir, 'data', 'incoming_seen.json')

    def _setup_incoming_watcher(self):
        """Surveille « Programmes outils/Vers NeoDrive »: un programme
        outil (Dathread…) y dépose un .simpl → NeoDrive
        propose de l'ouvrir dans un nouvel onglet. Les fichiers déjà
        proposés sont mémorisés (data/incoming_seen.json)."""
        from PySide6.QtCore import QFileSystemWatcher
        from src.integrations.tool_programs import tool_programs_dir
        self._incoming_dir = os.path.join(
            tool_programs_dir(), "Vers NeoDrive")
        try:
            os.makedirs(self._incoming_dir, exist_ok=True)
        except OSError:
            self._incoming_dir = ""
            return
        from src.core.fichiers_surs import lire_json
        vus = lire_json(self._incoming_seen_path(), {})
        self._incoming_seen = vus if isinstance(vus, dict) else {}
        self._incoming_watcher = QFileSystemWatcher(
            [self._incoming_dir], self)
        self._incoming_watcher.directoryChanged.connect(
            self._on_incoming_dir_changed)
        # Proposer aussi les fichiers déposés pendant que NeoDrive
        # était fermé (différé pour laisser la fenêtre apparaître)
        QTimer.singleShot(1500, self._check_incoming_simpl)

    def _on_incoming_dir_changed(self, _path: str):
        # Petit délai: laisser le programme finir d'écrire le fichier
        QTimer.singleShot(600, self._check_incoming_simpl)

    def _check_incoming_simpl(self):
        if not getattr(self, '_incoming_dir', ''):
            return
        try:
            files = sorted(os.listdir(self._incoming_dir))
        except OSError:
            return
        changed = False
        for fn in files:
            if not fn.lower().endswith('.simpl'):
                continue
            path = os.path.join(self._incoming_dir, fn)
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            if self._incoming_seen.get(fn) == mtime:
                continue
            self._incoming_seen[fn] = mtime
            changed = True
            # Priorité: une opé « programme outil » de l'onglet actif
            # attend un fichier (chemin vide) → proposer le rattachement
            if self._attach_incoming_to_waiting_op(path, fn):
                continue
            reply = QMessageBox.question(
                self, "Programme outil → NeoDrive",
                f"« {fn} » a été déposé dans le dossier\n"
                "« Programmes outils/Vers NeoDrive ».\n\n"
                "L'ouvrir dans un nouvel onglet ?",
                QMessageBox.StandardButton.Yes |
                QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self._open_incoming_simpl(path)
        if changed:
            try:
                from src.core.fichiers_surs import ecrire_json_sur
                ecrire_json_sur(self._incoming_seen_path(),
                                self._incoming_seen, indent=2)
            except OSError:
                pass

    def _attach_incoming_to_waiting_op(self, path: str,
                                       fn: str) -> bool:
        """Si une opé Appel Prog Ext liée à un programme outil attend
        un fichier (chemin vide) dans l'onglet ACTIF, propose de lui
        affecter le .simpl déposé. True si affecté."""
        waiting = [
            (i, op) for i, op in enumerate(self.program.operations)
            if op.operation_type == "appel_programme"
            and op.params.get('tool_program')
            and not str(op.params.get('filepath', '') or '').strip()]
        if not waiting:
            return False
        idx, op = waiting[0]
        reply = QMessageBox.question(
            self, "Programme outil → NeoDrive",
            f"« {fn} » a été déposé par un programme outil.\n\n"
            f"L'affecter à l'opération « {op.name} » "
            f"({op.params['tool_program']}) de l'onglet courant ?",
            QMessageBox.StandardButton.Yes |
            QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return False
        op.params['filepath'] = path
        self.program.operation_updated.emit(idx)
        self.program._mark_modified()
        self._regenerate_code()
        self._log_action(f"« {fn} » → opération « {op.name} »")
        return True

    def _open_incoming_simpl(self, path: str):
        """Ouvre un .simpl déposé, dans un NOUVEL onglet nommé comme
        le fichier (l'onglet courant n'est pas touché)."""
        self._on_new_prog_tab()
        # Onglet tout neuf: pas de question « non sauvegardé »
        self.program.mark_saved()
        self._import_simpl_file(path)
        base = os.path.splitext(os.path.basename(path))[0]
        tab = self._program_tabs[self._active_tab_index]
        tab['name'] = base
        self._prog_tabbar.setTabText(self._active_tab_index, base)
        self._refresh_tab_titles()

    def _on_new_prog_tab(self):
        """Ajoute un nouvel onglet programme vide."""
        self._save_current_tab_state()
        new_prog = ProgramModel()
        idx = len(self._program_tabs)
        name = self._next_p_name()
        self._program_tabs.append(
            {"program": new_prog, "filepath": "", "name": name,
             "undo_stack": self._new_undo_stack()})
        self._prog_tabbar.blockSignals(True)
        self._prog_tabbar.addTab(name)
        self._prog_tabbar.blockSignals(False)
        self._prog_tabbar.setCurrentIndex(idx)

    # ── Le tableau des outils dans toute la fenêtre ──

    def outils_en_plein(self) -> bool:
        return getattr(self, '_avant_outils_plein', None) is not None

    def outils_plein_fenetre(self, oui: bool) -> None:
        """Le tableau des outils (tools.json) dans toute la fenêtre:
        les colonnes 1 et 2 s'effacent, la colonne 3 ne montre plus
        que lui. Re-clic, « Fermer » ou Échap: tout revient comme
        avant (largeurs, colonnes, onglet)."""
        oui = bool(oui)
        gestion = getattr(self, 'onglets_fenetres', None)
        fen = (gestion.fenetre_de(self.tool_manager_panel)
               if gestion is not None else None)
        if fen is not None:
            # le tableau est sorti en fenêtre: c'est elle qui s'agrandit
            fen.showMaximized() if oui else fen.showNormal()
            self.tool_manager_panel.marquer_plein(oui)
            return
        if oui == self.outils_en_plein():
            self.tool_manager_panel.marquer_plein(oui)
            return
        if oui and self.fiche_ouverte() is not None:
            # la fiche quitte les colonnes 1 et 2: le tableau prend la
            # fenêtre, la fiche reste ouverte dans son panneau
            fiche = self.fiche_ouverte()
            self.masquer_fiche()
            if self.tool_manager_panel._fiche is fiche:
                self.tool_manager_panel.heberger_fiche_ici()
            else:
                self.catalogue_panel.fermer_fiche()
        colonnes = self.colonnes()
        # la colonne des outils (déplaçables depuis octobre 2026)
        ici = self.colonne_de(self.tool_manager_panel)
        tabs_outils = colonnes[ici]
        if oui:
            self._avant_outils_plein = {
                'tailles': list(self._splitter.sizes()),
                'cachees': [c.isHidden() for c in colonnes],
                'onglet': tabs_outils.currentWidget(),
                'colonne': ici,
            }
            tabs_outils.setCurrentWidget(self.tool_manager_panel)
            tabs_outils.setVisible(True)
            for k, c in enumerate(colonnes):
                if k != ici:
                    c.setVisible(False)
            tabs_outils.tabBar().setVisible(False)
            total = sum(self._avant_outils_plein['tailles']) or self.width()
            self._splitter.setSizes([max(1, total) if k == ici else 0
                                     for k in range(len(colonnes))])
        else:
            avant = self._avant_outils_plein
            self._avant_outils_plein = None
            tabs_outils = colonnes[avant.get('colonne', ici)]
            tabs_outils.tabBar().setVisible(True)
            for c, cachee in zip(colonnes, avant['cachees']):
                c.setVisible(not cachee)
            self._splitter.setSizes(avant['tailles'])
            if avant['onglet'] is not None \
                    and tabs_outils.indexOf(avant['onglet']) >= 0:
                tabs_outils.setCurrentWidget(avant['onglet'])
        self.tool_manager_panel.marquer_plein(oui)
        try:
            self._maj_boutons_colonnes()
        except Exception:
            pass

    def _fermer_outils(self) -> None:
        """« Fermer » du gestionnaire d'outils: sort de « toute la
        fenêtre », sinon revient au Canva."""
        if self.outils_en_plein():
            self.outils_plein_fenetre(False)
        elif self.onglets_fenetres.est_detache(self.tool_manager_panel):
            # « Fermer » d'un tableau sorti: il rentre, le Canva se montre
            self.onglets_fenetres.rattacher(self.tool_manager_panel)
            self.montrer_onglet(self.dxf_panel)
        else:
            self.montrer_onglet(self.dxf_panel)

    def exporter_dessin_joint(self, chemin_simpl: str,
                              genre: str, png: bool = True) -> list:
        """Écrit à côté du programme exporté le dessin choisi: '2d' →
        DXF du Canva (dessin + parcours) et son PNG; '3d' → STL de la
        pièce usinée simulée (ou de la pièce STEP si le programme ne
        coupe rien) et un PNG de sa vue 3D. Rend les fichiers écrits."""
        base = os.path.splitext(chemin_simpl)[0]
        ecrits = []
        if genre == '2d':
            canvas = self.dxf_panel.canvas
            canvas.draw_all_operations(self.program)
            canvas.export_dxf(base + ".dxf", program=self.program)
            ecrits.append(base + ".dxf")
            if png:
                canvas.export_png(
                    base + ".png",
                    background=self.params_panel.png_background())
                ecrits.append(base + ".png")
            return ecrits
        if genre != '3d':
            return ecrits
        tri, col = self.maillage_piece_usinee()
        if tri is None or not len(tri):
            raise ValueError("rien à montrer en 3D: ni coupe ni pièce STEP")
        from src.io.stl import ecrire_stl
        ecrire_stl(base + ".stl", tri, "NeoDrive - piece usinee")
        ecrits.append(base + ".stl")
        if png:
            # l'image selon les réglages du PNG (la matière à son
            # opacité); l'ancienne vue iso à défaut
            image = self.image_3d_reglee(self.params_panel.reglages_png())
            (image if image is not None else self._image_3d(tri, col)
             ).save(base + ".png")
            ecrits.append(base + ".png")
        return ecrits

    @staticmethod
    def _image_3d(tri, col, largeur: int = 1200, hauteur: int = 900):
        """La pièce usinée vue en iso (QImage)."""
        from src.gui.canvas3d import VueScene
        vue = VueScene()
        vue.resize(largeur, hauteur)
        vue.montrer_matiere = True
        vue.set_scene()
        vue.set_matiere(tri, col, cadrer=True)
        vue.vue_iso()
        image = vue.grab().toImage()
        vue.deleteLater()
        return image

    def image_visu_machine(self, chemin_png: str, genre: str = '2d') -> str:
        """Écrit l'aperçu du programme pour la machine: '2d' le plan du
        Canva (tout le programme), '3d' la pièce usinée simulée, '2d3d'
        les deux côte à côte. Rend le chemin écrit."""
        from PySide6.QtGui import QImage, QPainter, QColor
        # le programme tel qu'il est, pas tel qu'à la dernière régénération
        if self._regen_timer.isActive():
            self._regen_timer.stop()
            self._regenerate_code()
        reglages = self.params_panel.reglages_png()
        fond = reglages['fond']
        image_2d = image_3d = None
        if genre in ('2d', '2d3d'):
            self.image_2d_reglee(chemin_png, reglages)
            image_2d = QImage(chemin_png)
        if genre in ('3d', '2d3d'):
            image_3d = self.image_3d_reglee(reglages)
            if image_3d is None and genre == '3d':
                raise ValueError("rien à montrer en 3D: ni coupe ni pièce "
                                 "STEP")
        if genre == '3d':
            image_3d.save(chemin_png)
            return chemin_png
        if genre == '2d3d' and image_3d is not None and image_2d is not None \
                and not image_2d.isNull():
            h = max(image_2d.height(), 1)
            droite = image_3d.scaledToHeight(
                h, mode=__import__('PySide6.QtCore', fromlist=['Qt'])
                .Qt.TransformationMode.SmoothTransformation)
            tout = QImage(image_2d.width() + droite.width(), h,
                          QImage.Format.Format_RGB32)
            tout.fill(QColor(fond))
            p = QPainter(tout)
            p.drawImage(0, 0, image_2d)
            p.drawImage(image_2d.width(), 0, droite)
            p.end()
            tout.save(chemin_png)
        return chemin_png

    def image_2d_reglee(self, chemin_png: str, reglages: dict) -> str:
        """Le plan du Canva dans un PNG: les calques, la légende, les
        étiquettes et le cadrage choisis; l'écran est rendu tel qu'il
        était."""
        from src.gui.dialogs.reglages_png import CALQUES_2D
        panneau = self.dxf_panel
        canvas = panneau.canvas
        # le plan doit montrer TOUT le programme
        canvas.draw_all_operations(self.program)
        avant = {cle: (panneau._onglets_calque[cle].est_visible()
                       if cle in getattr(panneau, '_onglets_calque', {})
                       else True) for cle, _n in CALQUES_2D}
        legende = getattr(canvas, '_legend_visible', False)
        etiquettes = getattr(canvas, '_op_labels_visible', False)
        try:
            for cle, _n in CALQUES_2D:
                voulu = bool(reglages['calques_2d'].get(cle, True))
                if voulu != avant[cle]:
                    panneau._on_calque_visible(cle, voulu)
            canvas.set_legend_visible(bool(reglages['legende_2d']))
            canvas.set_op_labels_visible(bool(reglages['etiquettes_2d']))
            canvas.export_png(
                chemin_png, width_px=int(reglages['largeur']),
                background=reglages['fond'],
                couleurs=reglages['couleurs_2d'],
                zone='canva' if reglages['vue_2d'] == 'canva' else None)
        finally:
            for cle, _n in CALQUES_2D:
                voulu = bool(reglages['calques_2d'].get(cle, True))
                if voulu != avant[cle]:
                    panneau._on_calque_visible(cle, avant[cle])
            canvas.set_legend_visible(legende)
            canvas.set_op_labels_visible(etiquettes)
        return chemin_png

    def image_3d_reglee(self, reglages: dict, hauteur: int = None):
        """La pièce usinée en 3D (QImage) selon les réglages: ce que la
        vue montre (pièce, arêtes, parcours, opérations, dessin,
        matière), l'opacité et la couleur de la matière, la vue du Canva
        3D (zoom et angle) ou une vue type; None s'il n'y a rien."""
        import numpy as np
        largeur = int(reglages['largeur'])
        hauteur = int(hauteur or round(largeur * 0.75))
        couches = reglages['couches_3d']
        c3 = getattr(self, 'vue3d_panel', None)
        if c3 is None:
            c3 = self.dxf_panel.vue_3d()
        vide = (not len(c3.vue._tri) and not c3.vue._aretes
                and not any(c['pts'] for c in c3.vue._calques))
        if vide or c3._sim is None or self.dxf_panel._3d_perime:
            # la vue 3D n'a pas encore suivi le programme: cachée ou sur
            # demande, elle peut montrer celui d'un autre onglet. Le
            # fichier qui part avec le programme, lui, dit la vérité
            try:
                self.dxf_panel.actualiser_3d()
            except Exception:
                pass
        vue = c3.vue.copie(largeur, hauteur)
        vue.montrer_piece = bool(couches.get('piece', True))
        vue.montrer_aretes = bool(couches.get('aretes', True))
        vue.montrer_parcours = bool(couches.get('parcours', True))
        vue.montrer_operations = bool(couches.get('operations', False))
        vue.montrer_dessin = bool(couches.get('dessin', False))
        vue.montrer_rouges = False
        vue.transparente = False
        vue.outil = None
        vue._calques_parcours = (c3._calques_jusqua(None)
                                 if c3._sim is not None else [])
        vue.set_matiere(None)
        vue.montrer_matiere = False
        if couches.get('matiere', True):
            tri, col = self.maillage_piece_usinee()
            if tri is not None and len(tri):
                col = np.asarray(col, dtype=float)
                if reglages.get('couleur_matiere'):
                    from PySide6.QtGui import QColor
                    q = QColor(reglages['couleur_matiere'])
                    col = np.tile([q.redF(), q.greenF(), q.blueF()],
                                  (len(tri), 1))
                vue.set_matiere(tri, col)
                vue.montrer_matiere = True
                vue.opacite_matiere = float(reglages['opacite_matiere'])
        from PySide6.QtGui import QColor
        vue.couleur_fond = QColor(reglages.get('fond_3d') or '#181825')
        if vue._bornes() is None:
            vue.deleteLater()
            return None
        if reglages['vue_3d'] == 'canva' and (len(c3.vue._tri)
                                              or c3.vue._aretes
                                              or c3._sim is not None):
            vue.appliquer_camera(c3.vue.etat_camera())
        else:
            vue.recadrer()
            {'dessus': vue.vue_dessus, 'face': vue.vue_face}.get(
                reglages['vue_3d'], vue.vue_iso)()
        image = vue.image()
        vue.deleteLater()
        return image

    def apercu_png(self, reglages: dict):
        """L'image de l'export (selon le choix 2D/3D/les deux) pour la
        vignette de la fenêtre des réglages."""
        import os
        import tempfile
        from PySide6.QtGui import QImage
        ancien = self.params_panel._app_settings.get('png_export')
        self.params_panel._app_settings['png_export'] = reglages
        try:
            chemin = os.path.join(tempfile.mkdtemp(), "apercu.png")
            self.image_visu_machine(chemin, self.params_panel.visu_machine())
            return QImage(chemin)
        finally:
            if ancien is None:
                self.params_panel._app_settings.pop('png_export', None)
            else:
                self.params_panel._app_settings['png_export'] = ancien

    #: au-delà de ces lignes de code, la pièce usinée se calcule dans la
    #: barre d'état, avec Annuler
    LIGNES_PIECE_SUIVIE = 20000

    def _piece_creusee(self):
        """(triangles, couleurs) du brut creusé par le code, ou (None, None)
        s'il ne coupe rien. Gardés tant que le code, le brut et les outils ne
        changent pas: la vignette des réglages du PNG les redemande à chaque
        réglage touché. None si le calcul a été annulé."""
        from src.core import enlevement, sim_cycles
        from src.gui.progression import travailler, zone_de
        code = self.code_panel.get_code() or ""
        diametres = sim_cycles.diametres_de(self.tool_library)
        formes = sim_cycles.formes_outils(self.tool_library)
        boite = self.program.settings.boite_brut()
        cle = (sim_cycles.cle_de_simulation(code),
               sim_cycles.brut_du_code(code), boite,
               tuple(sorted(diametres.items())),
               tuple(sorted((k, tuple(sorted(v.items())))
                            for k, v in formes.items())))
        garde = getattr(self, '_piece_gardee', None)
        if garde is not None and garde[0] == cle:
            return garde[1]

        def calcul(progression=None):
            def part(debut, fin):
                if progression is None:
                    return None
                return lambda f, texte="": progression(
                    debut + f * (fin - debut), texte)
            res = sim_cycles.simuler(code, diametres, part(0.0, 0.6),
                                     formes=formes)
            if not res.get('x'):
                return None, None
            brut = enlevement.Brut.autour(res, boite=boite)
            brut.appliquer(res, res.get('formes') or {},
                           progression=part(0.6, 1.0))
            return (brut.maillage(300) if brut.volume_enleve() > 0
                    else (None, None))

        if code.count('\n') > self.LIGNES_PIECE_SUIVIE \
                and zone_de(self) is not None:
            piece = travailler(self, "Pièce usinée", calcul,
                               "Déroulement des cycles…")
            if piece is None:
                return None
        else:
            piece = calcul()
        self._piece_gardee = (cle, piece)
        return piece

    def maillage_piece_usinee(self):
        """(triangles, couleurs) de la pièce telle que le programme la
        laisse: le brut creusé par la simulation du code; s'il ne coupe
        rien, la pièce STEP affichée. (None, None) sinon."""
        piece = self._piece_creusee()
        if piece is None:
            return None, None       # (annulé)
        if piece[0] is not None:
            return piece
        c3 = getattr(self, 'vue3d_panel', None)
        modele = getattr(c3, '_modele', None)
        place = getattr(c3, '_piece_place', None)
        if modele is not None and place is not None \
                and len(getattr(modele, 'triangles', ())):
            import numpy as np
            dx, dy, haut, _bas = place
            tri = np.asarray(modele.triangles) + np.array([dx, dy, -haut])
            return tri, np.asarray(modele.couleurs)
        return None, None

    def code_pour_3d(self) -> str:
        """Le code que le Canva 3D simule: celui du programme, sans
        les opérations dont l'œil est fermé — elles disparaissent du
        parcours et de la matière comme du plan."""
        import copy
        from src.gui.panels.operations_panel import op_preview
        from src.core.program_model import ProgramModel
        ops = self.program.operations
        cachees = {id(o) for o in ops
                   if getattr(o, 'enabled', True) and not op_preview(o)}
        if not cachees:
            return self.code_panel.code_marque()
        prog = ProgramModel()
        prog.settings = self.program.settings
        for o in ops:
            if id(o) in cachees:
                continue
            c = copy.copy(o)
            c.params = dict(o.params)
            c.points = [dict(p) for p in (o.points or [])]
            prog.add_operation(c)
        pr_from, pr_to = self.params_panel.get_path_replacement()
        try:
            generateur = SimPlGenerator(
                prog, self.tool_library, pr_from, pr_to,
                expert_settings=self.params_panel.get_expert_settings(),
                calculer=False)
            generateur.generate()
            return generateur.code_marque
        except Exception:
            return self.code_panel.code_marque()

    def parcours_xy_operation(self, op) -> list:
        """Le trajet de l'outil d'une opération — ses coupes —, en
        polylignes XY machine: simulé depuis le code que le programme
        en tire, les décalages et rotations d'origine qui la précèdent
        compris."""
        import copy
        from src.core import sim3d, sim_cycles
        from src.core.program_model import ProgramModel
        prog = ProgramModel()
        prog.settings = self.program.settings
        for o in self.program.operations:
            if o is op:
                break
            if getattr(o, 'enabled', True) and o.operation_type in (
                    'decalage_origine', 'rotation_repere'):
                prog.add_operation(copy.deepcopy(o))
        prog.add_operation(copy.deepcopy(op))
        pr_from, pr_to = self.params_panel.get_path_replacement()
        code = SimPlGenerator(
            prog, self.tool_library, pr_from, pr_to,
            expert_settings=self.params_panel.get_expert_settings(),
            calculer=False).generate()
        res = sim_cycles.simuler(code,
                                 sim_cycles.diametres_de(self.tool_library))
        xs, ys, ks = res['x'], res['y'], res['k']
        sortie, courant = [], []
        for i in range(1, len(xs)):
            if ks[i] == sim3d.COUPE:
                if not courant:
                    courant = [(xs[i - 1], ys[i - 1])]
                if (xs[i], ys[i]) != courant[-1]:
                    courant.append((xs[i], ys[i]))
            elif courant:
                if len(courant) >= 2:
                    sortie.append(courant)
                courant = []
        if len(courant) >= 2:
            sortie.append(courant)
        return sortie

    def _montrer_onglet_3d(self, voulu: bool) -> None:
        """(le canvas) montrer l'onglet STEP 3D, ou revenir au Canva."""
        if voulu:
            self.montrer_onglet(self.vue3d_panel)
        elif self.onglet_actif(self.vue3d_panel):
            self.montrer_onglet(self.dxf_panel)
        elif self.onglets_fenetres.est_detache(self.vue3d_panel):
            self.montrer_onglet(self.dxf_panel)
        # le bouton « 3D » dit ce qu'on voit: le Canva 3D à côté du dessin
        # (une autre colonne, une fenêtre) reste montré, le bouton coché
        gestion = getattr(self, 'onglets_fenetres', None)
        if gestion is not None:
            self.dxf_panel._cocher_3d(gestion.visible(self.vue3d_panel))

    # ── le Canva 3D à côté du Canva 2D ──

    #: les places du Canva 3D par rapport au Canva 2D, pour le menu
    PLACES_3D = (
        ('cote', "3D à côté du dessin (les deux visibles)"),
        ('fenetre', "3D en fenêtre (autre écran)"),
        ('derriere', "3D derrière le dessin (un onglet de plus)"),
    )

    def place_3d(self) -> str:
        """Où est le Canva 3D: 'fenetre' (sorti), 'derriere' (dans la
        colonne du Canva 2D), 'cote' (dans une autre colonne)."""
        g = self.onglets_fenetres
        if g.est_detache(self.vue3d_panel):
            return 'fenetre'
        if g.colonne_de(self.vue3d_panel) == g.colonne_de(self.dxf_panel) \
                and not g.est_detache(self.dxf_panel):
            return 'derriere'
        return 'cote'

    def placer_3d(self, ou: str) -> None:
        """Le Canva 3D par rapport au Canva 2D, en un clic. 'cote': dans
        la colonne voisine (dépliée au besoin), les deux se voient et le
        3D suit le dessin en temps réel; 'fenetre': sorti en fenêtre;
        'derriere': un onglet de plus, juste derrière le Canva 2D. La place
        est retenue (disposition de la fermeture)."""
        g = self.onglets_fenetres
        v2, v3 = self.dxf_panel, self.vue3d_panel
        if ou == 'fenetre':
            if g.est_detache(v3):
                g.montrer(v3)
            else:
                g.detacher(v3)
            if not g.est_detache(v2):
                self.montrer_onglet(v2)
        else:
            if g.est_detache(v3):
                g.rattacher(v3)
            c2 = g.colonne_de(v2)
            if ou == 'derriere':
                tabs = self.colonnes()[c2]
                i2, i3 = tabs.indexOf(v2), tabs.indexOf(v3)
                rang = None
                if i2 >= 0:
                    rang = i2 if 0 <= i3 < i2 else i2 + 1
                g.deplacer(v3, c2, rang)
                self.montrer_onglet(v2)
            else:
                # la colonne voisine: celle de gauche (le code SimPL, à
                # côté du Canva en colonne 3), sinon celle de droite; un
                # Canva 2D sorti en fenêtre: sa colonne à lui
                if g.est_detache(v2):
                    cible = c2
                else:
                    cible = c2 - 1 if c2 > 0 else c2 + 1
                if self.colonnes()[cible].isHidden():
                    self.basculer_colonne(cible, True)
                if g.colonne_de(v3) != cible:
                    g.deplacer(v3, cible)
                self.montrer_onglet(v3)
                if not g.est_detache(v2):
                    self.montrer_onglet(v2)
        self._sur_onglet_col3(-1)
        noms = dict(self.PLACES_3D)
        self.statusBar().showMessage(noms.get(ou, ""), 3000)

    def menu_place_3d(self, parent=None):
        """Le menu « où mettre le Canva 3D » (clic droit sur le bouton
        « 3D » du Canva 2D, sur « ← 2D » du Canva 3D, sur leurs
        onglets); la place d'aujourd'hui est cochée."""
        menu = QMenu(parent or self)
        self._remplir_menu_place_3d(menu)
        return menu

    def _remplir_menu_place_3d(self, menu) -> None:
        ici = self.place_3d()
        for cle, texte in self.PLACES_3D:
            action = menu.addAction(texte)
            action.setCheckable(True)
            action.setChecked(cle == ici)
            action.triggered.connect(
                lambda _c=False, k=cle: self.placer_3d(k))

    def _sur_onglet_col3(self, index: int) -> None:
        gestion = getattr(self, 'onglets_fenetres', None)
        visible = (gestion.visible(self.vue3d_panel) if gestion is not None
                   else self._col3_tabs.widget(index) is self.vue3d_panel)
        self.dxf_panel.sur_onglet_3d(visible)

    def _on_prog_tab_changed(self, index: int):
        """Switch vers un autre programme."""
        if index < 0 or index >= len(self._program_tabs):
            return
        if index == self._active_tab_index:
            return
        # le menu « nouvelle opération » de l'onglet d'avant se ferme:
        # on voit la liste d'opérations de celui-ci
        try:
            self.operations_panel.fermer_ajout()
        except Exception:
            pass
        self._save_current_tab_state()
        self._active_tab_index = index
        tab = self._program_tabs[index]
        old_prog = self.program
        self.program = tab["program"]
        self.dxf_panel.sur_changement_de_programme()
        # Rebrancher les signaux de régénération sur le nouveau programme
        self._rewire_program_signals(old_prog)
        # Pile undo de l'onglet (créée à la volée si absente)
        stack = tab.get("undo_stack")
        if stack is None:
            stack = self._new_undo_stack()
            tab["undo_stack"] = stack
        self.undo_stack = stack
        self.operations_panel._undo_stack = stack
        # Rebrancher le programme sur les panels — et OUBLIER
        # l'opération de l'onglet d'avant: son formulaire restait
        # affiché sur un onglet neuf, et la liste re-sélectionnait
        # son rang dans l'autre programme
        self.operations_panel._current_index = -1
        self.operations_panel._undo_snapshot = None
        try:
            self.operations_panel.param_form.clear_form()
        except RuntimeError:
            pass
        # le blocage venait du formulaire de l'onglet d'avant (une opé
        # sans outil): il écrivait « BLOQUÉ » à la place du code de
        # celui-ci
        self.operations_panel.param_form._depth_blocked = False
        self._generation_blocked = False
        self.operations_panel.program = self.program
        self.operations_panel._connect_signals()
        self.operations_panel._refresh_list()
        self.operations_panel.param_form._current_op = None
        self.operations_panel.active_operation_changed.emit(None)
        # Le DESSIN appartient à l'onglet: on montre le sien, on ne
        # garde pas celui d'à côté
        self.dxf_panel.utiliser_canvas(self._cle_canvas(tab))
        # Et on libère les canvas des onglets qui n'existent plus:
        # invisibles, ils gardaient leur scène entière en mémoire
        self.dxf_panel.garder_canvas(
            [t.get('canvas_key') for t in self._program_tabs])
        self.dxf_panel.canvas.set_active_operation(None)
        self.params_panel.program = self.program
        self.params_panel.refresh_from_model()
        self.operations_panel.refresh_specs_fields()
        self._regenerate_code()
        self.dxf_panel.relire_3d_sans_attendre()
        self._refresh_tab_titles()
        # l'organisation de CET onglet (un onglet neuf garde celle du
        # précédent)
        if tab.get("vue"):
            self.appliquer_vue(tab["vue"])
        fp = tab.get("filepath", "")
        if fp:
            self._log_action(f"Onglet: {os.path.basename(fp)}")
        else:
            self._log_action(f"Onglet: {tab['name']}")

    def _archive_closed_tab(self, tab: dict):
        """Archive silencieusement le programme d'un onglet fermé dans
        programs/onglets_fermes/ (JSON indenté, nom horodaté).
        Réglage 'closed_tabs_keep': 0 = pas d'archive, -1 = illimité,
        sinon nombre d'archives conservées (purge des plus anciennes)."""
        prog = tab["program"]
        try:
            keep = int(self.params_panel._app_settings.get(
                'closed_tabs_keep', 10))
        except (TypeError, ValueError):
            keep = 10
        if keep == 0 or prog.operation_count == 0:
            return
        if not getattr(self, '_session_writable', True):
            return          # instance jetable (test, banc de mesure)
        archive_dir = os.path.join(self._programs_dir, "onglets_fermes")
        try:
            os.makedirs(archive_dir, exist_ok=True)
            from datetime import datetime
            safe_name = "".join(
                c if c.isalnum() or c in (' ', '-', '_') else '_'
                for c in tab.get('name', 'P')).strip() or "P"
            stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            fname = f"{safe_name}_{stamp}.ndp"
            fpath = os.path.join(archive_dir, fname)
            n = 2
            while os.path.exists(fpath):
                fpath = os.path.join(
                    archive_dir, f"{safe_name}_{stamp}_{n}.ndp")
                n += 1
            from src.core.fichiers_surs import ecrire_json_sur
            ecrire_json_sur(fpath, prog.to_dict(), indent=2,
                            ensure_ascii=False)
            self._log_action(
                f"Onglet archivé: {os.path.basename(fpath)}")
        except Exception as e:
            self._status_label.setText(
                f"⚠ Archivage onglet échoué: {e}")
            return
        # Purge des archives les plus anciennes
        if keep > 0:
            try:
                files = sorted(
                    (os.path.join(archive_dir, f)
                     for f in os.listdir(archive_dir)
                     if f.endswith('.ndp')),
                    key=os.path.getmtime)
                while len(files) > keep:
                    os.remove(files.pop(0))
            except Exception:
                pass

    def _on_simpl_blocks_available(self, filepath: str):
        """Un SimPl vient d'être ouvert dans l'éditeur: ses
        sous-programmes rejoignent la liste d'opérations de la
        colonne 1, où ils s'éditent et se complètent comme les
        opérations NeoDrive."""
        from src.io.simpl_importer import import_simpl_as_blocks
        try:
            loaded = import_simpl_as_blocks(filepath, self.tool_library)
        except Exception as e:
            self._log_action(f"Blocs non chargés: {e}")
            return
        if loaded.operation_count == 0:
            self._log_action(
                f"{os.path.basename(filepath)}: aucun sous-programme "
                "appelé dans Main")
            return
        # Onglet courant vide → on l'utilise; sinon nouvel onglet,
        # pour ne jamais écraser un programme en cours
        if self.program.operation_count > 0:
            self._on_new_prog_tab()
        self.program.settings = loaded.settings
        blocs = list(loaded.operations)
        # Séquences homonymes: un 2e import écraserait celles du 1er
        self.operations_panel.uniquify_sequences(blocs)
        for op in blocs:
            self.program.add_operation(op)
        base = os.path.splitext(os.path.basename(filepath))[0]
        tab = self._program_tabs[self._active_tab_index]
        tab['name'] = base
        self._prog_tabbar.setTabText(self._active_tab_index, base)
        self.params_panel.refresh_from_model()
        self.operations_panel.refresh_specs_fields()
        self._refresh_tab_titles()
        self._regenerate_code()
        # Le programme VIVANT est celui de « Code SimPl »: c'est lui
        # qui se régénère quand on ajoute une opération. L'éditeur
        # SimPl, lui, garde le fichier d'origine — sans cette bascule
        # les ajouts semblaient sans effet.
        self.montrer_onglet(self.code_panel)
        self._log_action(
            f"{loaded.operation_count} sous-programme(s) chargé(s) "
            f"depuis {os.path.basename(filepath)} — édition dans "
            f"« Code SimPl »")

    def _on_prog_tab_close(self, index: int):
        """Ferme un onglet programme (minimum 1 onglet).
        Pas de confirmation: le programme est archivé silencieusement."""
        if len(self._program_tabs) <= 1:
            # Dernier onglet: on l'archive quand même et on repart sur
            # un onglet vierge — fermer ne doit pas être sans effet
            self._archive_closed_tab(self._program_tabs[0])
            self._on_new_prog_tab()
            self._on_prog_tab_close(0)
            return
        tab = self._program_tabs[index]
        self._archive_closed_tab(tab)
        # Le dessin de l'onglet s'en va avec lui
        self.dxf_panel.oublier_canvas(tab.get('canvas_key', ''))
        self._program_tabs.pop(index)
        # Libérer la pile undo de l'onglet fermé
        closed_stack = tab.get("undo_stack")
        if closed_stack is not None:
            closed_stack.deleteLater()
        self._prog_tabbar.blockSignals(True)
        self._prog_tabbar.removeTab(index)
        self._prog_tabbar.blockSignals(False)
        # Ajuster l'index actif
        if index < self._active_tab_index:
            new_active = self._active_tab_index - 1
        elif index == self._active_tab_index:
            new_active = min(index, len(self._program_tabs) - 1)
        else:
            new_active = self._active_tab_index
        # Invalider l'index actif pour forcer le rebind: sinon la garde
        # `index == self._active_tab_index` de _on_prog_tab_changed
        # laisserait le programme fermé affiché/édité.
        self._active_tab_index = -1
        self._prog_tabbar.setCurrentIndex(new_active)
        # Forcer le switch (si setCurrentIndex n'a pas émis de signal)
        self._on_prog_tab_changed(new_active)

    def _on_tab_context_menu(self, pos):
        """Menu contextuel sur un onglet programme."""
        index = self._prog_tabbar.tabAt(pos)
        if index < 0 or index >= len(self._program_tabs):
            return
        menu = QMenu(self)
        act_dup = menu.addAction("⧉ Dupliquer l'onglet")
        act_ren = menu.addAction("✏ Renommer...")
        act_close = act_autres = act_gauche = act_droite = None
        if len(self._program_tabs) > 1:
            menu.addSeparator()
            act_close = menu.addAction("✕ Fermer (archivé)")
            # Faire le ménage autour d'un onglet: dix programmes
            # ouverts se ferment un par un, sinon
            act_autres = menu.addAction("✕ Fermer les autres")
            act_gauche = menu.addAction("✕ Fermer ceux à gauche")
            act_gauche.setEnabled(index > 0)
            act_droite = menu.addAction("✕ Fermer ceux à droite")
            act_droite.setEnabled(index < len(self._program_tabs) - 1)
        chosen = menu.exec(self._prog_tabbar.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == act_dup:
            self._duplicate_tab(index)
        elif chosen == act_ren:
            self._on_prog_tab_dblclick(index)
        elif act_close is not None and chosen == act_close:
            self._on_prog_tab_close(index)
        elif chosen == act_autres:
            self._fermer_onglets_sauf(index)
        elif chosen == act_gauche:
            self._fermer_onglets_sauf(index, cote='gauche')
        elif chosen == act_droite:
            self._fermer_onglets_sauf(index, cote='droite')

    def _fermer_onglets_sauf(self, index: int, cote: str = ''):
        """Ferme les onglets autour de celui-ci.

        `cote`: '' pour tous les autres, 'gauche' ou 'droite'. Les
        programmes fermés sont archivés comme par la croix."""
        if not (0 <= index < len(self._program_tabs)):
            return
        garde = self._program_tabs[index]
        if cote == 'gauche':
            a_fermer = list(range(index - 1, -1, -1))
        elif cote == 'droite':
            a_fermer = list(range(len(self._program_tabs) - 1, index, -1))
        else:
            a_fermer = [i for i in
                        range(len(self._program_tabs) - 1, -1, -1)
                        if i != index]
        if not a_fermer:
            return
        if len(a_fermer) > 1:
            reponse = QMessageBox.question(
                self, "Fermer des onglets",
                f"Fermer {len(a_fermer)} onglet(s) ? "
                f"Leur programme est archivé dans "
                f"programs/onglets_fermes/.")
            if reponse != QMessageBox.StandardButton.Yes:
                return
        # De droite à gauche: fermer décale les index suivants
        for i in a_fermer:
            if len(self._program_tabs) <= 1:
                break
            self._on_prog_tab_close(i)
        # L'onglet gardé redevient l'actif, où qu'il ait glissé
        try:
            nouvel_index = self._program_tabs.index(garde)
        except ValueError:
            nouvel_index = 0
        self._prog_tabbar.setCurrentIndex(nouvel_index)

    def _duplicate_tab(self, index: int):
        """Duplique un onglet programme complet dans un nouvel onglet."""
        if not (0 <= index < len(self._program_tabs)):
            return
        self._save_current_tab_state()
        src_tab = self._program_tabs[index]
        prog = self._program_from_dict(src_tab["program"].to_dict())
        prog.mark_saved()
        name = src_tab.get("name", "P") + " (copie)"
        idx = len(self._program_tabs)
        self._program_tabs.append(
            {"program": prog, "filepath": "", "name": name,
             "undo_stack": self._new_undo_stack()})
        self._prog_tabbar.blockSignals(True)
        self._prog_tabbar.addTab(name)
        self._prog_tabbar.blockSignals(False)
        self._prog_tabbar.setCurrentIndex(idx)
        self._on_prog_tab_changed(idx)
        self._refresh_tab_titles()
        self._log_action(f"Onglet dupliqué: {name}")

    def _on_prog_tab_dblclick(self, index: int):
        """Double-clic sur un onglet → édition inline avec QLineEdit overlay."""
        if index < 0 or index >= len(self._program_tabs):
            return
        rect = self._prog_tabbar.tabRect(index)
        edit = QLineEdit(self._prog_tabbar)
        edit.setText(self._program_tabs[index]["name"])
        edit.setGeometry(rect)
        edit.selectAll()
        edit.setFocus()
        edit.show()

        def _finish():
            new_name = edit.text().strip()
            edit.deleteLater()
            if new_name:
                self._program_tabs[index]["name"] = new_name
                self._refresh_tab_titles()

        edit.editingFinished.connect(_finish)

    def _on_prog_tab_moved(self, from_idx: int, to_idx: int):
        """Synchronise _program_tabs quand l'utilisateur réordonne les onglets."""
        if 0 <= from_idx < len(self._program_tabs) and \
           0 <= to_idx < len(self._program_tabs):
            tab = self._program_tabs.pop(from_idx)
            self._program_tabs.insert(to_idx, tab)
            self._active_tab_index = self._prog_tabbar.currentIndex()

    def _update_prog_tab_name(self, filepath: str = ""):
        """Met à jour le nom de l'onglet actif."""
        if filepath:
            name = os.path.splitext(os.path.basename(filepath))[0]
        else:
            name = f"P{self._active_tab_index + 1}"
        if 0 <= self._active_tab_index < len(self._program_tabs):
            self._program_tabs[self._active_tab_index]["name"] = name
            self._program_tabs[self._active_tab_index]["filepath"] = filepath
            self._refresh_tab_titles()

    def _on_new(self):
        if self.program.is_modified:
            reply = QMessageBox.question(
                self, "Nouveau programme",
                "Le programme actuel n'est pas sauvegardé. Continuer ?",
                QMessageBox.StandardButton.Yes |
                QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return
        self.program.clear()
        # Réinitialiser aussi le nom/filepath de l'onglet actif
        # (sinon l'onglet garde le nom de l'ancien fichier)
        self._update_prog_tab_name("")
        self.params_panel.refresh_from_model()
        self._regenerate_code()
        self._log_action("Nouveau programme créé")

    @staticmethod
    def _resolve_dir(path: str, fallback: str = "") -> str:
        """Retourne le dossier s'il existe, sinon remonte au parent,
        sinon retourne le fallback."""
        if path and os.path.isdir(path):
            return path
        if path:
            parent = os.path.dirname(path)
            if parent and os.path.isdir(parent):
                return parent
        return fallback if fallback else ""

    def _get_last_ndp_dir(self) -> str:
        """Retourne le dernier répertoire NDP utilisé, ou le défaut."""
        from src.gui.theme import reglages_qt
        settings = reglages_qt()
        last_dir = settings.value("paths/last_ndp_dir", "")
        return self._resolve_dir(last_dir, self._programs_dir)

    def _save_last_ndp_dir(self, filepath: str):
        """Sauvegarde le répertoire du dernier fichier NDP utilisé."""
        from src.gui.theme import reglages_qt
        settings = reglages_qt()
        settings.setValue("paths/last_ndp_dir", os.path.dirname(filepath))

    def _on_open(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Ouvrir un programme",
            self._get_last_ndp_dir(),
            "Programmes et sous-programmes NeoDrive (*.ndp *.nds);;"
            "Travaux VectorDrive (*.ndjob);;"
            "Tous les fichiers (*)")
        if filepath:
            self._save_last_ndp_dir(filepath)
            if filepath.lower().endswith('.ndjob'):
                self.ouvrir_travail_vectordrive(filepath)
                return
            self._ouvrir_programme(filepath)

    def _on_browse(self):
        dlg = ProgramBrowserDialog(self._programs_dir, self)
        if dlg.exec() == ProgramBrowserDialog.DialogCode.Accepted:
            if dlg.selected_filepath:
                if dlg.selected_type == "program":
                    self._ouvrir_programme(dlg.selected_filepath)
                else:
                    self._import_subprogram_file(dlg.selected_filepath)

    def _on_reopen_closed_tab(self):
        """Rouvre une archive d'onglet fermé dans un NOUVEL onglet."""
        archive_dir = os.path.join(self._programs_dir, "onglets_fermes")
        files = []
        if os.path.isdir(archive_dir):
            files = sorted(
                (os.path.join(archive_dir, f)
                 for f in os.listdir(archive_dir)
                 if f.endswith('.ndp')),
                key=os.path.getmtime, reverse=True)
        if not files:
            QMessageBox.information(
                self, "Onglets fermés",
                "Aucune archive d'onglet fermé.\n"
                "(Les onglets fermés sont archivés dans "
                "programs/onglets_fermes/ selon le réglage "
                "'Archives conservées'.)")
            return

        from datetime import datetime
        labels = []
        for fp in files:
            base = os.path.splitext(os.path.basename(fp))[0]
            mtime = datetime.fromtimestamp(
                os.path.getmtime(fp)).strftime('%d/%m/%Y %H:%M')
            try:
                with open(fp, 'r', encoding='utf-8') as f:
                    nops = len(json.load(f).get('operations', []))
                labels.append(f"{base} — {mtime} ({nops} ops)")
            except Exception:
                labels.append(f"{base} — {mtime} (illisible)")

        from PySide6.QtWidgets import QInputDialog
        choice, ok = QInputDialog.getItem(
            self, "Rouvrir un onglet fermé",
            "Archive (plus récente en premier):", labels, 0, False)
        if not ok:
            return
        fp = files[labels.index(choice)]
        try:
            prog = ProgramSerializer.load(fp, self.tool_library)
        except Exception as e:
            QMessageBox.warning(
                self, "Erreur",
                f"Impossible de rouvrir l'archive:\n{e}")
            return
        # Copie restaurée: pas de fichier associé (Ctrl+S → Enregistrer sous)
        prog.filepath = None
        prog.mark_saved()

        # Nom de l'onglet: retirer l'horodatage du nom d'archive
        import re as _re
        base = os.path.splitext(os.path.basename(fp))[0]
        name = _re.sub(r'_\d{8}_\d{6}(_\d+)?$', '', base) \
            or self._next_p_name()

        self._save_current_tab_state()
        idx = len(self._program_tabs)
        self._program_tabs.append(
            {"program": prog, "filepath": "", "name": name,
             "undo_stack": self._new_undo_stack()})
        self._prog_tabbar.blockSignals(True)
        self._prog_tabbar.addTab(name)
        self._prog_tabbar.blockSignals(False)
        self._prog_tabbar.setCurrentIndex(idx)
        self._on_prog_tab_changed(idx)
        self._log_action(f"Onglet restauré: {name}")

    def _load_program(self, filepath: str):
        self._noter_recent(filepath)
        try:
            new_program = ProgramSerializer.load(
                filepath, self.tool_library)
            self.program.clear()
            self.program.settings = new_program.settings
            self.program.description = getattr(new_program,
                                               'description', '')
            for op in new_program.operations:
                self.program.add_operation(op)
            self.program.reprendre_conservation(new_program)
            self.program.filepath = filepath
            self.program.mark_saved()
            self.params_panel.refresh_from_model()
            self._regenerate_code()
            self._update_prog_tab_name(filepath)
            self._log_action(
                f"Chargé: {os.path.basename(filepath)}")
            garde = self._ce_qui_est_garde(new_program)
            if garde:
                self._status_label.setText("⚠ " + garde)
                self._log_action(garde)
        except Exception as e:
            QMessageBox.warning(
                self, "Erreur", f"Impossible de charger:\n{e}")

    @staticmethod
    def _ce_qui_est_garde(programme) -> str:
        """La phrase qui dit ce que le fichier porte sans que ce poste
        sache s'en servir (gardé, réécrit à l'enregistrement)."""
        morceaux = []
        n = len(getattr(programme, 'ops_inconnues', []) or [])
        if n:
            morceaux.append(
                f"{n} opération(s) d'un type inconnu (version plus "
                f"récente ?) gardée(s) dans le fichier, non affichée(s)")
        absents = sorted({op.outil_absent for op in programme.operations
                          if getattr(op, 'outil_absent', '')
                          and not op.tool_id})
        if absents:
            morceaux.append(
                "outil(s) absent(s) de ce poste, gardé(s) dans le "
                "fichier: " + ", ".join(absents[:4])
                + ("…" if len(absents) > 4 else ""))
        return " ; ".join(morceaux)

    def _on_save(self):
        if self.program.filepath:
            self._save_to(self.program.filepath)
        else:
            self._on_save_as()

    def _on_save_as(self):
        """Enregistre en choisissant d'abord le GROUPE: avec une
        centaine de groupes, ranger à l'enregistrement évite d'avoir
        à trier après coup."""
        from PySide6.QtWidgets import QInputDialog
        from src.io import program_library as pl
        groups = pl.list_groups(self._programs_dir)
        choices = groups + ["➕ Nouveau groupe…", "📂 Autre dossier…"]
        choice, ok = QInputDialog.getItem(
            self, "Enregistrer le programme",
            "Groupe:", choices, 0, False)
        if not ok:
            return
        if choice == "📂 Autre dossier…":
            start = os.path.join(self._get_last_ndp_dir(),
                                 "programme.ndp")
        else:
            if choice == "➕ Nouveau groupe…":
                name, ok = QInputDialog.getText(
                    self, "Nouveau groupe", "Nom du groupe:")
                if not ok:
                    return
                choice = pl.create_group(self._programs_dir, name)
                if not choice:
                    QMessageBox.warning(
                        self, "Nouveau groupe", "Nom invalide.")
                    return
            tab = self._program_tabs[self._active_tab_index]
            default = (tab.get('name') or "programme") + ".ndp"
            start = os.path.join(
                pl.group_dir(self._programs_dir, choice), default)
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Enregistrer le programme", start,
            "Programme NeoDrive (*.ndp);;Sous-programme NeoDrive (*.nds)")
        if filepath:
            if not filepath.lower().endswith(('.ndp', '.nds')):
                filepath += '.ndp'
            self._save_to(filepath)

    def _save_to(self, filepath: str):
        try:
            ProgramSerializer.save(self.program, filepath)
            self._noter_recent(filepath)
            self._save_last_ndp_dir(filepath)
            self._update_prog_tab_name(filepath)
            self._log_action(
                f"Sauvegardé: {os.path.basename(filepath)}")
        except Exception as e:
            QMessageBox.warning(
                self, "Erreur", f"Impossible de sauvegarder:\n{e}")

    def _on_save_subprogram(self):
        if self.program.operation_count == 0:
            QMessageBox.information(
                self, "Info", "Aucune opération à sauvegarder.")
            return
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Enregistrer comme sous-programme",
            os.path.join(self._programs_dir, "sous_programme.nds"),
            "Sous-programmes NeoDrive (*.nds)")
        if filepath:
            if not filepath.endswith('.nds'):
                filepath += '.nds'
            try:
                SubProgramSerializer.save(
                    self.program.operations, filepath)
                self._status_label.setText(
                    f"Sous-programme sauvé: {os.path.basename(filepath)}")
            except Exception as e:
                QMessageBox.warning(
                    self, "Erreur", f"Impossible de sauvegarder:\n{e}")

    def _on_import_subprogram(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Importer un sous-programme",
            self._programs_dir,
            "Sous-programmes NeoDrive (*.nds);;Tous les fichiers (*)")
        if filepath:
            self._import_subprogram_file(filepath)

    def _import_subprogram_file(self, filepath: str):
        try:
            ops = SubProgramSerializer.load(filepath, self.tool_library)
            for op in ops:
                self.program.add_operation(op)
            self._status_label.setText(
                f"Importé: {len(ops)} opération(s)")
        except Exception as e:
            QMessageBox.warning(
                self, "Erreur", f"Impossible d'importer:\n{e}")

    @staticmethod
    def _strip_volatile_simpl(code: str) -> str:
        """Retire les lignes volatiles (horodatage d'en-tête, bloc
        NDMETA) pour comparer deux exports sur leur contenu réel."""
        out = []
        for line in code.split('\n'):
            ls = line.strip()
            if (ls.startswith('# NDMETA:')
                    or ls.startswith('# === NeoDrive META')
                    or ls.startswith('# === fin NeoDrive META')
                    or ls.startswith('# File generated by NeoDrive')):
                continue
            out.append(line)
        return '\n'.join(out)

    def _confirm_export_diff(self, new_code: str) -> bool:
        """Montre ce qui a changé depuis le DERNIER export de cet
        onglet (diff coloré). Retourne True pour continuer l'export."""
        if not (0 <= self._active_tab_index < len(self._program_tabs)):
            return True
        tab = self._program_tabs[self._active_tab_index]
        old = tab.get('last_export_code', '')
        if not old:
            return True  # premier export de cet onglet
        new_stripped = self._strip_volatile_simpl(new_code)
        if old == new_stripped:
            self._status_label.setText(
                "Code identique au dernier export de cet onglet")
            return True
        import difflib
        import html as _html
        diff = list(difflib.unified_diff(
            old.split('\n'), new_stripped.split('\n'),
            fromfile="dernier export", tofile="export actuel",
            lineterm="", n=2))
        added = sum(1 for l in diff
                    if l.startswith('+') and not l.startswith('+++'))
        removed = sum(1 for l in diff
                      if l.startswith('-') and not l.startswith('---'))

        dlg = QDialog(self)
        dlg.setWindowTitle("Changements depuis le dernier export")
        dlg.resize(780, 540)
        lay = QVBoxLayout(dlg)
        info = QLabel(
            f"<b>+{added}</b> ligne(s) ajoutée(s), "
            f"<b>−{removed}</b> supprimée(s) depuis le dernier export "
            f"de « {tab.get('name', '?')} ».")
        info.setStyleSheet("font-size: 12px;")
        lay.addWidget(info)
        view = QTextEdit()
        view.setReadOnly(True)
        view.setStyleSheet(
            "QTextEdit { background: #11111b; color: #cdd6f4; "
            "font-family: 'Cascadia Code', Consolas, monospace; "
            "font-size: 11px; }")
        rows = []
        for l in diff:
            esc = _html.escape(l) or "&nbsp;"
            if l.startswith('+++') or l.startswith('---'):
                rows.append(f'<span style="color:#6c7086">{esc}</span>')
            elif l.startswith('@@'):
                rows.append(f'<span style="color:#89b4fa">{esc}</span>')
            elif l.startswith('+'):
                rows.append(f'<span style="color:#a6e3a1">{esc}</span>')
            elif l.startswith('-'):
                rows.append(f'<span style="color:#f38ba8">{esc}</span>')
            else:
                rows.append(esc)
        view.setHtml("<pre>" + "\n".join(rows) + "</pre>")
        lay.addWidget(view, stretch=1)
        btns = QHBoxLayout()
        btns.addStretch()
        cancel_btn = QPushButton("Annuler")
        cancel_btn.clicked.connect(dlg.reject)
        btns.addWidget(cancel_btn)
        ok_btn = QPushButton("Exporter…")
        ok_btn.setObjectName("primary")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(dlg.accept)
        btns.addWidget(ok_btn)
        lay.addLayout(btns)
        return dlg.exec() == QDialog.DialogCode.Accepted

    def _on_export_simpl(self):
        # Validation croisée avant export
        from src.core.validator import validate_program, ValidationMessage
        msgs = validate_program(self.program, self.tool_library)
        errors = [m for m in msgs if m.level == ValidationMessage.ERROR]
        warnings = [m for m in msgs if m.level == ValidationMessage.WARN]
        if errors:
            detail = "\n".join(str(m) for m in errors + warnings)
            QMessageBox.warning(
                self, "Erreurs de validation",
                f"{len(errors)} erreur(s) détectée(s):\n\n{detail}")
            return
        if warnings:
            detail = "\n".join(str(m) for m in warnings)
            reply = QMessageBox.question(
                self, "Avertissements",
                f"{len(warnings)} avertissement(s):\n\n{detail}\n\n"
                f"Continuer l'export ?",
                QMessageBox.StandardButton.Yes |
                QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return

        # ── Filet anti-collision: cohérence strokeRapid/Cutting ──
        stroke_issues = SimPlGenerator.verify_stroke_consistency(
            self.code_panel.get_code(),
            self.params_panel.get_expert_settings())
        if stroke_issues:
            reply = QMessageBox.warning(
                self, "⚠ SÉCURITÉ — hauteurs de dégagement",
                "Des hauteurs strokeRapidZ/strokeCuttingZ du code ne "
                "correspondent PAS aux réglages machine courants:\n\n"
                + "\n".join(stroke_issues) +
                "\n\nRisque de COLLISION si l'outil dégage plus bas "
                "que prévu. Exporter quand même ?",
                QMessageBox.StandardButton.Yes |
                QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return

        # ── Accents dans les textes vus par l'opérateur ──
        if not self._check_accents_before_export():
            return

        # ── Diff depuis le dernier export de cet onglet ──
        pr_from, pr_to = self.params_panel.get_path_replacement()
        expert = self.params_panel.get_expert_settings()
        new_code = self._code_complet(pr_from, pr_to, expert)
        if new_code is None:
            return
        # ── Structure: ce que la machine refuserait au chargement ──
        if not self._confirmer_structure(new_code):
            return
        if not self._confirm_export_diff(new_code):
            return

        tab_name = ""
        if 0 <= self._active_tab_index < len(self._program_tabs):
            tab_name = self._program_tabs[self._active_tab_index]["name"]
        default_name = SimPlExporter.get_default_filename(
            self.program, tab_name)
        # Utiliser le dernier chemin d'export si disponible, sinon le dossier par défaut
        last_dir = self.params_panel._app_settings.get(
            'last_simpl_export_dir', '')
        export_dir = self._resolve_dir(last_dir, self._exports_dir)
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Exporter le code SimPl",
            os.path.join(export_dir, default_name),
            "Fichiers SimPl (*.SimPl);;Tous les fichiers (*)")
        if filepath:
            try:
                # Aperçu du dessin: PNG écrit À CÔTÉ du .SimPl, le
                # programme le référence en chemin relatif
                expert = dict(expert)
                joints = self.ecrire_annexes_export(
                    filepath, expert, self.params_panel.export_dessin())
                SimPlExporter.export(
                    self.program, self.tool_library, filepath,
                    pr_from, pr_to, expert_settings=expert)
                if joints:
                    self._log_action(
                        "Joint au programme: " + ", ".join(
                            os.path.basename(f) for f in joints))
                # Mémoriser le code exporté (diff au prochain export)
                if 0 <= self._active_tab_index < len(self._program_tabs):
                    self._program_tabs[self._active_tab_index][
                        'last_export_code'] = \
                        self._strip_volatile_simpl(new_code)
                self._retenir_chemin_simpl(filepath)
                # Sauver le dernier dossier d'export
                self.params_panel._app_settings['last_simpl_export_dir'] = (
                    os.path.dirname(filepath))
                self.params_panel.save_app_settings()
                self._maj_bouton_dossier_export()
                self._log_action(
                    f"Exporté: {os.path.basename(filepath)}")
            except Exception as e:
                QMessageBox.warning(
                    self, "Erreur", f"Impossible d'exporter:\n{e}")

    def chemin_simpl_actif(self) -> str:
        """Le .SimPl d'où vient l'onglet courant (importé ou exporté en
        dernier), "" sinon."""
        if 0 <= self._active_tab_index < len(self._program_tabs):
            return self._program_tabs[self._active_tab_index].get(
                'chemin_simpl', '') or ''
        return ''

    def _retenir_chemin_simpl(self, filepath: str) -> None:
        if 0 <= self._active_tab_index < len(self._program_tabs):
            self._program_tabs[self._active_tab_index]['chemin_simpl'] = \
                os.path.abspath(filepath)

    def ecrire_annexes_export(self, filepath: str, expert: dict,
                              joint: str) -> list:
        """Ce qui accompagne le .SimPl exporté: LE PNG du programme
        (aperçu @image: ou dessin joint) — celui que les Paramètres
        choisissent: plan 2D, vue iso 3D de la pièce usinée, ou les
        deux (le dessin joint imposait le sien) —, puis le dessin joint
        (DXF ou STL). `expert` reçoit 'preview_image' quand l'aperçu
        est demandé. Rend les fichiers joints."""
        png_name = os.path.splitext(os.path.basename(filepath))[0] + ".png"
        png_path = os.path.join(os.path.dirname(filepath), png_name)
        png_ecrit = False
        if expert.get('embed_canvas_preview') or joint != 'aucun':
            try:
                self.image_visu_machine(png_path,
                                        self.params_panel.visu_machine())
                png_ecrit = True
                if expert.get('embed_canvas_preview'):
                    expert['preview_image'] = png_name
            except Exception as e:
                self._log_action(f"Aperçu non généré: {e}")
        # le dessin joint; son PNG seulement si celui du programme n'a
        # pas pu s'écrire
        joints = []
        if joint != 'aucun':
            try:
                joints = self.exporter_dessin_joint(filepath, joint,
                                                    png=not png_ecrit)
                if png_ecrit:
                    joints.append(png_path)
            except Exception as e:
                self._log_action(f"Dessin joint non écrit: {e}")
        return joints

    def dossier_export_simpl(self) -> str:
        """Le dossier du dernier export SimPl (sinon celui des
        exports)."""
        last_dir = self.params_panel._app_settings.get(
            'last_simpl_export_dir', '')
        return self._resolve_dir(last_dir, self._exports_dir)

    def _maj_bouton_dossier_export(self) -> None:
        d = self.dossier_export_simpl()
        self.code_panel.dossier_export_btn.setToolTip(
            "Ouvrir le dossier du dernier export SimPl"
            + (f":\n{d}" if d else ""))

    def ouvrir_dossier_export(self) -> bool:
        """Le bouton à côté d'« Exporter .SimPl »: l'explorateur sur le
        dossier du dernier export."""
        d = self.dossier_export_simpl()
        if not d or not os.path.isdir(d):
            self._log_action("Aucun dossier d'export à ouvrir")
            return False
        ouvrir = getattr(self, 'ouvrir_externe', None)
        if ouvrir is None:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            ouvrir = lambda p: QDesktopServices.openUrl(  # noqa: E731
                QUrl.fromLocalFile(p))
        ok = bool(ouvrir(d))
        self._log_action(f"Dossier d'export: {d}")
        return ok

    # ----- Import SimPl -----

    def _on_import_simpl(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Importer un fichier SimPl",
            self._exports_dir,
            "Fichiers SimPl (*.SimPl);;Tous les fichiers (*)")
        if not filepath:
            return
        self._import_simpl_file(filepath)

    def _import_simpl_file(self, filepath: str):
        if self.program.is_modified:
            reply = QMessageBox.question(
                self, "Importer SimPl",
                "Le programme actuel n'est pas sauvegardé. Continuer ?",
                QMessageBox.StandardButton.Yes |
                QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return
        try:
            from src.io.simpl_importer import (
                extract_neodrive_metadata, import_simpl,
                import_simpl_as_blocks, ndmeta_a_jour)
            with open(filepath, 'r', encoding='utf-8-sig',
                      errors='replace') as f:
                raw = f.read()
            # Programme NeoDrive: reconstruction EXACTE via NDMETA.
            # Programme externe: chargement en BLOCS, qui conserve le
            # code d'origine mot pour mot — l'ancien import
            # heuristique le réinterprétait de façon approximative.
            # Programme NeoDrive CORRIGÉ après son export (lot,
            # éditeur…): son NDMETA est périmé — en blocs, tel quel.
            meta = extract_neodrive_metadata(raw)
            perime = meta is not None and not ndmeta_a_jour(meta, raw)
            if meta is not None and not perime:
                new_prog = import_simpl(filepath, self.tool_library)
                kind = "opération(s)"
            else:
                new_prog = import_simpl_as_blocks(
                    filepath, self.tool_library)
                kind = "sous-programme(s)"
                if perime:
                    kind += (" — modifié après son export par NeoDrive: "
                             "ouvert tel qu'il est, en blocs")
            self.program.clear()
            self.program.settings = new_prog.settings
            for op in new_prog.operations:
                self.program.add_operation(op)
            self._retenir_chemin_simpl(filepath)
            self.params_panel.refresh_from_model()
            self.operations_panel.refresh_specs_fields()
            self._regenerate_code()
            n = self.program.operation_count
            self._status_label.setText(
                f"Importé {n} {kind} depuis "
                f"{os.path.basename(filepath)}")
        except Exception as e:
            QMessageBox.warning(
                self, "Erreur d'import",
                f"Impossible d'importer le fichier SimPl:\n{e}")

    # ----- Templates -----

    def _check_accents_before_export(self) -> bool:
        """Signale les accents des textes vus par l'opérateur
        (commentaire, dialogues, gravures) et propose de les retirer.
        Retourne False si l'export doit être abandonné."""
        from src.codegen.generator import find_accented_texts
        hits = find_accented_texts(self.program)
        if not hits:
            return True
        detail = "\n".join(
            f"  • {origin} :  « {txt} »  →  « {clean} »"
            for origin, txt, clean in hits[:12])
        if len(hits) > 12:
            detail += f"\n  … et {len(hits) - 12} autre(s)"
        box = QMessageBox(self)
        box.setWindowTitle("Accents détectés")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(
            f"{len(hits)} texte(s) contiennent des accents ou "
            "caractères non-ASCII.\nCertaines machines les affichent "
            "mal dans les dialogues et gravures.")
        box.setInformativeText(detail)
        remove = box.addButton("Retirer les accents",
                               QMessageBox.ButtonRole.AcceptRole)
        keep = box.addButton("Conserver",
                             QMessageBox.ButtonRole.RejectRole)
        box.addButton("Annuler l'export",
                      QMessageBox.ButtonRole.DestructiveRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is keep:
            return True
        if clicked is not remove:
            return False
        self._strip_accents_in_program()
        self._regenerate_code()
        self._log_action(f"Accents retirés dans {len(hits)} texte(s)")
        return True

    def _strip_accents_in_program(self):
        """Retire les accents des textes destinés à la machine."""
        from src.codegen.generator import strip_accents
        s = self.program.settings
        s.comment = strip_accents(s.comment)
        s.author = strip_accents(s.author)
        keys = ('message', 'caption', 'text', 'prefix', 'label',
                'var_name')
        for idx, op in enumerate(self.program.operations):
            changed = False
            for key in keys:
                val = op.params.get(key)
                if isinstance(val, str) and strip_accents(val) != val:
                    op.params[key] = strip_accents(val)
                    changed = True
            for field in op.params.get('fields') or []:
                for key in ('label', 'var', 'unit'):
                    val = field.get(key)
                    if isinstance(val, str) \
                            and strip_accents(val) != val:
                        field[key] = strip_accents(val)
                        changed = True
            if changed:
                self.program.operation_updated.emit(idx)
        self.program._mark_modified()
        self.params_panel.refresh_from_model()

    def _confirmer_structure(self, code: str) -> bool:
        """Le contrôle de structure (src.core.controle_simpl) du code tel
        qu'il part: une séquence appelée sans son bloc $$$, un programme
        appelé absent, un `if` sans `endif`, un programme externe
        introuvable. Ces constats s'affichent avant l'export, et
        l'opérateur décide."""
        from src.gui.indicateur_structure import confirmer_structure
        return confirmer_structure(self, code)

    def _on_export_function_key(self):
        """Exporte le programme courant comme module de touche de
        fonction du pupitre (Machine/HandheldFunctionKeys)."""
        from PySide6.QtWidgets import QInputDialog
        if self.program.operation_count == 0:
            QMessageBox.information(
                self, "Touche de fonction",
                "Le programme est vide.")
            return
        if not self._confirmer_structure(self.code_panel.get_code()):
            return
        keys = [f"F{i}" for i in range(1, 13)]
        choice, ok = QInputDialog.getItem(
            self, "Touche de fonction",
            "Touche du pupitre à programmer:", keys, 0, False)
        if not ok:
            return
        num = int(choice[1:])
        expert = dict(self.params_panel.get_expert_settings())
        expert['function_key'] = num
        pr_from, pr_to = self.params_panel.get_path_replacement()
        default_name = f"FunctionKey{num}.simpl"
        filepath, _ = QFileDialog.getSaveFileName(
            self, "Enregistrer le module de touche de fonction",
            os.path.join(self._exports_dir, default_name),
            "Fichiers SimPl (*.simpl *.SimPl)")
        if not filepath:
            return
        # Le NOM DU FICHIER doit rester FunctionKeyN pour que la
        # machine l'associe à la touche
        if os.path.basename(filepath).lower() != default_name.lower():
            reply = QMessageBox.question(
                self, "Touche de fonction",
                f"La machine attend un fichier nommé "
                f"« {default_name} ».\n\nEnregistrer sous ce nom "
                f"dans le dossier choisi ?",
                QMessageBox.StandardButton.Yes |
                QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                filepath = os.path.join(
                    os.path.dirname(filepath), default_name)
        try:
            SimPlExporter.export(
                self.program, self.tool_library, filepath,
                pr_from, pr_to, expert_settings=expert)
            self._log_action(
                f"Touche {choice}: {os.path.basename(filepath)}")
            QMessageBox.information(
                self, "Touche de fonction",
                f"Module {choice} enregistré.\n\nÀ copier dans le "
                f"dossier Machine/HandheldFunctionKeys de la "
                f"machine.\nUn appui sur {choice} exécutera ce "
                f"programme.")
        except Exception as e:
            QMessageBox.warning(
                self, "Erreur", f"Impossible d'exporter:\n{e}")

    def _on_generate_auto_programs(self):
        """Génère le module machine AutomaticPrograms (OnStart, OnEnd,
        gestionnaires d'interruption). Ce module s'exécute autour de
        TOUS les programmes de la machine: la génération est donc
        explicite, prévisualisée, et l'installation reste manuelle."""
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QFormLayout, QDialogButtonBox,
            QComboBox)
        from src.io.automatic_programs import build_automatic_programs

        dlg = QDialog(self)
        dlg.setWindowTitle("Module machine AutomaticPrograms")
        dlg.resize(560, 480)
        v = QVBoxLayout(dlg)
        warn = QLabel(
            "⚠ Ce module s'exécute autour de <b>tous</b> les "
            "programmes de la machine.<br>Relisez-le avant de "
            "l'installer dans <code>Machine/Library</code>.")
        warn.setWordWrap(True)
        warn.setStyleSheet("color: #fab387; font-size: 12px;")
        v.addWidget(warn)

        form = QFormLayout()
        checks = {}
        for key, label, default in (
            ('confirm_start', "Confirmation au lancement (Ok/Annuler)",
             True),
            ('notify_aborted',
             "Signaler un programme interrompu (IdleHandler)", True),
            ('park_on_referenced',
             "Proposer la position de parking après référencement",
             True),
            ('confirm_end', "Message en fin de programme", False),
            ('notify_initialized',
             "Message à la mise sous tension", False),
        ):
            cb = QCheckBox()
            cb.setChecked(default)
            checks[key] = cb
            form.addRow(label, cb)

        out_combo = QComboBox()
        out_combo.addItem("(aucune)", 0)
        for i in range(1, 9):
            out_combo.addItem(f"OUTPUT_{i}", i)
        out_combo.setToolTip(
            "Sortie numérique activée au lancement, coupée en fin de "
            "programme ET en cas d'interruption.\nC'est la seule "
            "action autorisée dans un ErrorHandler.")
        form.addRow("Piloter une sortie:", out_combo)
        v.addLayout(form)

        preview = QTextEdit()
        preview.setReadOnly(True)
        preview.setStyleSheet(
            "QTextEdit { background: #11111b; color: #cdd6f4; "
            "font-family: 'Cascadia Code', Consolas, monospace; "
            "font-size: 11px; }")
        v.addWidget(preview, stretch=1)

        def _opts():
            o = {k: cb.isChecked() for k, cb in checks.items()}
            o['user_output'] = out_combo.currentData()
            o['author'] = self.program.settings.author
            return o

        def _refresh():
            preview.setPlainText(build_automatic_programs(_opts()))

        for cb in checks.values():
            cb.toggled.connect(_refresh)
        out_combo.currentIndexChanged.connect(_refresh)
        _refresh()

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save |
            QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Save).setText(
            "Enregistrer…")
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        v.addWidget(btns)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        filepath, _ = QFileDialog.getSaveFileName(
            self, "Enregistrer le module AutomaticPrograms",
            os.path.join(self._exports_dir, "AutomaticPrograms.simpl"),
            "Fichiers SimPl (*.simpl *.SimPl)")
        if not filepath:
            return
        try:
            from src.core.fichiers_surs import ecrire_texte_sur
            ecrire_texte_sur(filepath, build_automatic_programs(_opts()),
                             garder_bak=True)
            self._log_action(
                f"Module machine généré: {os.path.basename(filepath)}")
            QMessageBox.information(
                self, "Module machine",
                "Module enregistré.\n\nÀ installer dans le dossier "
                "Machine/Library de la machine, après relecture.\n"
                "Le nom du MODULE doit rester « AutomaticPrograms ».")
        except OSError as e:
            QMessageBox.warning(
                self, "Erreur", f"Écriture impossible:\n{e}")

    def _on_save_template(self):
        from src.io.template_manager import save_template
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(
            self, "Sauver template",
            "Nom du template:")
        if not ok or not name.strip():
            return
        desc, _ = QInputDialog.getText(
            self, "Sauver template",
            "Description (optionnel):")
        try:
            fpath = save_template(self.program, name.strip(), desc)
            self._status_label.setText(
                f"Template sauvé: {os.path.basename(fpath)}")
        except Exception as e:
            QMessageBox.warning(
                self, "Erreur", f"Impossible de sauver le template:\n{e}")

    def _on_load_template(self):
        from src.io.template_manager import list_templates, load_template
        templates = list_templates()
        if not templates:
            QMessageBox.information(
                self, "Templates",
                "Aucun template disponible.\n"
                "Utilisez 'Sauver template' pour en créer un.")
            return
        names = [f"{t['name']}  ({t['op_count']} ops)" for t in templates]
        from PySide6.QtWidgets import QInputDialog
        choice, ok = QInputDialog.getItem(
            self, "Charger template",
            "Sélectionnez un template:", names, 0, False)
        if not ok:
            return
        idx = names.index(choice)
        tpl = templates[idx]
        if self.program.is_modified:
            reply = QMessageBox.question(
                self, "Charger template",
                "Le programme actuel n'est pas sauvegardé. Continuer ?",
                QMessageBox.StandardButton.Yes |
                QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return
        try:
            new_prog = load_template(tpl['filepath'], self.tool_library)
            self.program.clear()
            self.program.settings = new_prog.settings
            for op in new_prog.operations:
                self.program.add_operation(op)
            self.params_panel.refresh_from_model()
            self._regenerate_code()
            self._status_label.setText(
                f"Template chargé: {tpl['name']}")
        except Exception as e:
            QMessageBox.warning(
                self, "Erreur", f"Impossible de charger le template:\n{e}")

    # ----- Actions Outils (migrées depuis menu) -----

    def _on_sequence_to_operation(self, name: str, code: str):
        """Crée une opération Séquence Datron dans le programme actif."""
        op = OperationInstance("sequence_datron", f"Séq {name}")
        op.params = {
            'sequence_name': name,
            'sequence_code': code,
            'z_scale': 1.0,
            'z_offset': 0.0,
        }
        stack = self.operations_panel._undo_stack
        if stack is not None:
            from src.core.undo_commands import AddOperationCommand
            stack.push(AddOperationCommand(self.program, op))
        else:
            self.program.add_operation(op)
        self.operations_panel.op_list.setCurrentRow(
            self.program.operation_count - 1)
        self._log_action(f"Séquence importée: {name}")

    def _on_symbol_to_canvas(self, filepath: str):
        """Placement interactif d'un symbole .smb sur le canvas DXF:
        le fantôme suit la souris, clic pour poser, Échap annule."""
        if self.dxf_panel.canvas.start_symbol_placement(filepath):
            self.montrer_onglet(self.dxf_panel)
            self.dxf_panel.canvas.setFocus()
            self.dxf_panel.info_label.setText(
                f"Placement: {os.path.basename(filepath)} — "
                "cliquez pour poser (Échap: annuler)")
            self._log_action(
                f"Placement symbole: {os.path.basename(filepath)}")
        else:
            self.dxf_panel.info_label.setText(
                "Symbole non vectorisable — placement impossible")

    def _on_symbols_dir_changed(self, path: str):
        """Persiste le dossier de la bibliothèque de symboles."""
        self.params_panel._app_settings['symbols_dir'] = path
        self.params_panel.save_app_settings()

    def _broche_datron(self) -> str:
        """La broche des avances DATRON (onglet Catalogue)."""
        from src.core.coupe_datron import BROCHE_DEFAUT, BROCHES
        b = self.params_panel._app_settings.get('datron_broche', '')
        return b if b in BROCHES else BROCHE_DEFAUT

    def _on_broche_datron(self, broche: str):
        self.params_panel._app_settings['datron_broche'] = broche
        self.params_panel.save_app_settings()

    def _on_tool_manager(self):
        self.tool_manager_panel._refresh_table()
        self.montrer_onglet(self.tool_manager_panel)

    def _on_circles_detected(self, circles: list):
        """Centres détectés à l'import: la liste suit sans clic."""
        try:
            self.circle_ops_panel.load_circles(circles or [])
        except Exception:
            pass

    def _refresh_circle_ops(self):
        circles = self.dxf_panel.canvas.get_detected_circles()
        self.circle_ops_panel.load_circles(circles)

    def _on_circle_ops_generated(self, ops_data: list,
                                 source: str = "DXF"):
        from src.operations.registry import OperationRegistry

        count = 0
        for op_data in ops_data:
            op_type = op_data.get('operation_type', '')
            try:
                op_class = OperationRegistry.get(op_type)
            except KeyError:
                continue

            op = OperationInstance(
                op_type,
                op_data.get('name', op_class.DISPLAY_NAME))
            op.params = {
                **op_class.get_default_params(),
                **op_data.get('params', {})}
            op.x = op_data.get('x', 0.0)
            op.y = op_data.get('y', 0.0)
            op.points = op_data.get('points', [])
            # l'outil choisi par qui propose (usinage des faces STEP)
            if op_data.get('tool_id') and \
                    op_data['tool_id'] in self.tool_library.tools:
                op.tool_id = op_data['tool_id']
            # « Générer » regroupe ce qu'il crée: un ensemble de la liste
            if op_data.get('group_id'):
                op.group_id = str(op_data['group_id'])
                op.group_name = str(op_data.get('group_name') or op.name)
                op.group_libre = bool(op_data.get('group_libre'))
            self.program.add_operation(op)
            count += 1

        if count > 0:
            self._status_label.setText(
                f"{count} opération(s) ajoutée(s) depuis {source}")
            if self._col2_tabs.currentIndex() == 2:
                self._col2_tabs.setCurrentIndex(0)
            self._regenerate_code()

    def _on_point_focus_requested(self, index: int):
        """Clic sur le n° d'une rangée du tableau de points →
        bascule sur le canva et surligne le point correspondant."""
        op = self.operations_panel.param_form._current_op
        if op is None or not op.points:
            return
        if not (0 <= index < len(op.points)):
            return
        pt = op.points[index]
        # Afficher l'onglet du canva DXF si un autre onglet est actif
        self.montrer_onglet(self.dxf_panel)
        self.dxf_panel.canvas.highlight_point(
            float(pt.get('x', 0)), float(pt.get('y', 0)))

    def _on_canvas_point_clicked(self, source: str, index: int):
        """Clic sur un marqueur du canvas → sélectionne le point
        correspondant dans le tableau d'origine."""
        if source == "genops":
            panneau = self.circle_ops_panel
            if panneau.retrait_a_la_souris():
                # les indésirables s'ôtent à la souris
                panneau.retirer_point(index)
                return
            tbl = panneau.table
            if 0 <= index < tbl.rowCount():
                tbl.selectRow(index)
            return
        if source != "op":
            return  # 'external': pas de tableau associé
        form = self.operations_panel.param_form
        # Tableau taraudage (approximation si sous-lignes pattern)
        tbl = getattr(form, '_taraudage_table', None)
        if tbl is not None:
            try:
                if 0 <= index < tbl.rowCount():
                    tbl.setCurrentCell(index, 0)
                    item = tbl.item(index, 0)
                    if item:
                        tbl.scrollToItem(item)
                    return
            except RuntimeError:
                pass
        # Widget points Dathread: focus sur le champ X de la ligne
        dw = getattr(form, '_dathread_widget', None)
        if dw is not None:
            try:
                rows = getattr(dw, '_point_rows', [])
                if 0 <= index < len(rows):
                    w = rows[index].get('x')
                    if w is not None:
                        w.setFocus()
                        w.selectAll()
            except RuntimeError:
                pass

    def _on_retrait_points_bascule(self, actif: bool):
        """Le curseur dit ce que le clic fera au canvas."""
        try:
            self.dxf_panel.canvas.viewport().setCursor(
                Qt.CursorShape.ForbiddenCursor if actif
                else Qt.CursorShape.ArrowCursor)
        except RuntimeError:
            pass

    def _on_genops_point_selected(self, index: int):
        pts = [{'x': c['x'], 'y': c['y'],
                'label': c.get('entity_type', '')}
               for c in self.circle_ops_panel._filtered_circles]
        self.dxf_panel.canvas.draw_operation_points(
            pts, highlight_index=index)

    def _on_tab_changed(self, index: int):
        if index == 0:
            self.tool_library.load()
            self._regenerate_code()
        elif index == 2:
            circles = self.dxf_panel.canvas.get_detected_circles()
            if circles:
                self.circle_ops_panel.load_circles(circles)
        # Onglet Matériaux: synchroniser les multiplicateurs affichés
        if (hasattr(self, '_materials_panel')
                and self._col2_tabs.widget(index) is self._materials_panel):
            self._refresh_materials_values()

    def _on_theme_changed(self, theme_name: str):
        """Applique le nouveau thème."""
        from src.gui.theme import apply_theme, get_current_font_size
        app = QApplication.instance()
        if app:
            apply_theme(app, theme_name, get_current_font_size())
            self._update_prog_tabbar_style()
            # le tableau des outils aux couleurs du thème
            if hasattr(self.tool_manager_panel, 'appliquer_theme'):
                self.tool_manager_panel.appliquer_theme()
            # les icônes des barres des canvas, aux couleurs du thème
            for vue in (self.dxf_panel, getattr(self.dxf_panel,
                                                '_canvas3d', None)):
                barre = getattr(vue, 'barre_outils', None)
                if barre is not None:
                    barre.rafraichir_icones()
            # Recharger le formulaire si une opération est affichée
            if self.operations_panel.param_form._current_op:
                self.operations_panel.param_form.load_operation(
                    self.operations_panel.param_form._current_op)

    def _on_font_size_changed(self):
        """Applique la nouvelle taille de police."""
        from src.gui.theme import apply_theme, get_current_theme
        size = self.params_panel._font_combo.currentData()
        if size:
            app = QApplication.instance()
            if app:
                apply_theme(app, get_current_theme(), int(size))
                if self.operations_panel.param_form._current_op:
                    self.operations_panel.param_form.load_operation(
                        self.operations_panel.param_form._current_op)

    def _on_expert_toggle(self, checked: bool):
        self._expert_mode = checked
        self.operations_panel.set_expert_mode(checked)
        self.params_panel.set_expert_mode(checked)
        self.dxf_panel.set_expert_mode(checked)
        self._regenerate_code()

    def _on_generation_blocked(self, blocked: bool):
        # Émis à CHAQUE validation du formulaire (donc à chaque
        # sélection d'opération): ne régénérer que si l'état de
        # blocage a réellement changé.
        if blocked == self._generation_blocked:
            return
        self._generation_blocked = blocked
        self._regenerate_code()

    def _cle_dessin_ops(self):
        """Ce que le Canva 2D montre des opérations, résumé: le
        programme, le canvas, et pour chaque opération ce qui se dessine
        (type, état, œil, outil et son Ø, paramètres, points)."""
        from src.gui.panels.operations_panel import op_preview
        outils = getattr(self.tool_library, 'tools', None) or {}
        morceaux = []
        for op in self.program.operations:
            outil = outils.get(getattr(op, 'tool_id', None))
            morceaux.append((
                id(op), getattr(op, 'operation_type', ''),
                bool(getattr(op, 'enabled', True)), bool(op_preview(op)),
                getattr(op, 'tool_id', None),
                getattr(outil, 'diameter', None),
                repr(getattr(op, 'params', None)),
                repr(getattr(op, 'points', None)),
                getattr(op, 'x', None), getattr(op, 'y', None)))
        return (id(self.program), id(self.dxf_panel.canvas),
                hash(tuple(morceaux)))

    def _sur_op_active(self, _op=None) -> None:
        """Une autre opération est choisie. Le Canva 2D montre déjà
        TOUT le programme — le choix n'y change rien: on ne le redessine
        que s'il n'est plus à jour (un redessin attendu, des opérations
        changées, des marques effacées). Novembre 2026: chaque clic sur
        une opé redessinait toute la pièce (60 ms pour 12 opés)."""
        attente = getattr(self, '_canvas_timer', None)
        canvas = self.dxf_panel.canvas
        try:
            a_jour = (not (attente is not None and attente.isActive())
                      and getattr(canvas, '_ops_dessinees', None)
                      == self._cle_dessin_ops())
        except Exception:
            a_jour = False
        if not a_jour:
            self._refresh_canvas_op()

    def _refresh_canvas_op(self, *args):
        """Redessine les opérations du programme sur le canvas.

        Toutes les opérations actives sont tracées, avec leur
        empreinte (rectangles, cercles, texte gravé à sa hauteur de
        caractère): un plan à l'écran doit montrer la pièce, pas la
        seule opération sélectionnée."""
        # ce redessin vaut pour ceux qui attendaient: un ajout
        # d'opération redessinait la pièce tout de suite (sélection),
        # puis 40 ms plus tard (le redessin différé déjà demandé)
        attente = getattr(self, '_canvas_timer', None)
        if attente is not None:
            attente.stop()
        if getattr(self, '_preparation_appels', False):
            # une simulation tient la barre d'état: on redessinera après
            self._schedule_canvas_refresh()
            return
        canvas = self.dxf_panel.canvas
        # un gros programme appelé se simule d'abord dans la barre
        # d'état (le dessin le trouve ensuite tout prêt)
        self.preparer_programmes_appeles(
            getattr(canvas, '_tool_library', None))
        try:
            if self.program.operation_count:
                canvas.draw_all_operations(self.program)
            else:
                canvas.set_active_operation(None)
            # ce que le canvas montre maintenant (un choix d'opé suivant
            # n'aura pas à le refaire)
            canvas._ops_dessinees = self._cle_dessin_ops()
        except Exception:
            # Le dessin ne doit jamais empêcher d'éditer
            idx = self.operations_panel._current_index
            canvas.set_active_operation(self.program.get_operation(idx))

    def preparer_programmes_appeles(self, outils=None) -> None:
        """Les programmes externes appelés (et montrés) du programme,
        simulés d'avance s'ils sont gros — voir
        `progression.preparer_parcours_fichiers`. `outils`: la
        bibliothèque du canvas qui va les dessiner (ses diamètres font
        partie de la clé du parcours gardé)."""
        from src.gui.panels.operations_panel import op_preview
        chemins = [str((op.params or {}).get('filepath') or '').strip()
                   for op in self.program.operations
                   if op.operation_type == 'appel_programme'
                   and op.enabled and op_preview(op)]
        chemins = [c for c in chemins if c]
        if not chemins:
            return
        from src.core import sim_cycles
        from src.gui.progression import preparer_parcours_fichiers
        diametres = (sim_cycles.diametres_de(outils)
                     if outils is not None else {})
        self._preparation_appels = True
        try:
            preparer_parcours_fichiers(self, chemins, diametres)
        finally:
            self._preparation_appels = False

    def _on_active_op_for_fold(self, op):
        """Transmet le nom de l'opération au panneau code pour auto-fold.

        La séquence appelée par un bloc importé voyage avec lui: sans
        son nom, l'auto-fold laissait replié le $$$ de l'opération
        justement affichée."""
        if op:
            self.code_panel.set_active_operation_name(
                op.name, str(op.params.get('sequence_name', '') or ''))
        else:
            self.code_panel.set_active_operation_name("")

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showMaximized()
        else:
            self.showFullScreen()

    #: proportions de repos des trois colonnes
    _PARTS_COLONNES = (260, 370, 370)

    #: largeur au-dessous de laquelle une colonne ne descend pas.
    #: Sans elle, chaque panneau imposait SON minimum au splitter et
    #: donc à la fenêtre: 2545 px à eux trois, et replier puis
    #: déplier remettait la fenêtre à cette taille — sous la barre
    #: des tâches.
    LARGEUR_MINI_COLONNE = 160

    def colonnes(self) -> list:
        """Les trois colonnes, dans l'ordre du splitter."""
        return [self._col1_tabs, self._col2_tabs, self._col3_tabs]

    def colonne_visible(self, index: int) -> bool:
        """Une colonne repliée garde une largeur nulle."""
        tailles = self._splitter.sizes()
        return 0 <= index < len(tailles) and tailles[index] > 0

    def _tailles_visees(self, index: int, visible: bool) -> list:
        """Les largeurs à atteindre après la bascule.

        Une colonne repliée rend sa place aux AUTRES, au prorata de
        ce qu'elles occupent déjà: replier le canvas ne doit pas
        redistribuer tout l'écran au hasard."""
        tailles = list(self._splitter.sizes())
        total = sum(tailles) or sum(self._PARTS_COLONNES)
        if not visible:
            place = tailles[index]
            tailles[index] = 0
            restant = [i for i in range(len(tailles)) if i != index]
            base = sum(tailles[i] for i in restant) or 1
            for i in restant:
                tailles[i] += int(place * tailles[i] / base)
            return tailles
        # Rouvrir: on rend à la colonne sa part de repos
        part = self._PARTS_COLONNES[index] / sum(self._PARTS_COLONNES)
        largeur = max(120, int(total * part))
        autres = [i for i in range(len(tailles)) if i != index]
        base = sum(tailles[i] for i in autres) or 1
        for i in autres:
            tailles[i] = max(80, tailles[i]
                             - int(largeur * tailles[i] / base))
        tailles[index] = largeur
        return tailles

    def duree_animation(self) -> int:
        """Durée du glissement, en millisecondes. 0 = instantané."""
        try:
            return max(0, min(2000, int(
                self.params_panel._app_settings.get(
                    'column_anim_ms', 180))))
        except (TypeError, ValueError, AttributeError):
            return 180

    def basculer_colonne(self, index: int, visible: bool = None):
        """Replie ou déplie une colonne, en glissant.

        Le glissement n'est pas un ornement: une colonne qui
        disparaît d'un coup laisse chercher où le reste est parti."""
        colonnes = self.colonnes()
        if not 0 <= index < len(colonnes):
            return
        if self.fiche_ouverte() is not None:
            # la fiche tient la place des colonnes 1 et 2, la colonne 3
            # à côté d'elle (hors du séparateur): on revient d'abord aux
            # trois colonnes — sans quoi IndexError
            self.fermer_fiche_ouverte()
        if visible is None:
            visible = not self.colonne_visible(index)
        depart = list(self._splitter.sizes())
        arrivee = self._tailles_visees(index, visible)
        if visible:
            colonnes[index].setVisible(True)
        # Le bouton dit l'INTENTION tout de suite: pendant le
        # glissement, il aurait rapporté l'état d'où l'on vient
        bouton = getattr(self, '_btn_colonnes', {}).get(index)
        if bouton is not None and bouton.isChecked() != visible:
            bouton.blockSignals(True)
            bouton.setChecked(visible)
            bouton.blockSignals(False)

        duree = self.duree_animation()
        if duree <= 0 or depart == arrivee:
            self._splitter.setSizes(arrivee)
            if not visible:
                colonnes[index].setVisible(False)
            self._maj_boutons_colonnes()
            return

        from PySide6.QtCore import QVariantAnimation, QEasingCurve
        animation = QVariantAnimation(self)
        animation.setDuration(duree)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.InOutCubic)

        def _pas(part):
            self._splitter.setSizes(
                [int(a + (b - a) * float(part))
                 for a, b in zip(depart, arrivee)])

        def _fin():
            self._splitter.setSizes(arrivee)
            if not visible:
                colonnes[index].setVisible(False)
            # Les boutons se lisent APRÈS coup: avant, ils
            # rapportaient l'état d'où l'on venait
            self._maj_boutons_colonnes()

        animation.valueChanged.connect(_pas)
        animation.finished.connect(_fin)
        # Gardée sur la fenêtre: une animation locale serait ramassée
        # avant d'avoir joué
        self._anim_colonnes = animation
        animation.start()

    def _maj_boutons_colonnes(self):
        """Les boutons disent l'état réel des colonnes."""
        for index, bouton in getattr(self, '_btn_colonnes', {}).items():
            etat = self.colonne_visible(index)
            if bouton.isChecked() != etat:
                bouton.blockSignals(True)
                bouton.setChecked(etat)
                bouton.blockSignals(False)

    # ──── Un canvas par onglet ────

    def _preparer_canvas(self, canvas):
        """Donne à un canvas ce que la fenêtre lui doit.

        Réglages d'affichage, bibliothèque d'outils, et le signal du
        clic sur un marqueur d'opération. Appelé pour le premier
        canvas comme pour ceux des onglets ouverts ensuite: un canvas
        à moitié branché ne répond que dans son onglet d'origine."""
        largeur = float(getattr(self, '_largeur_trait_canvas', 1.0))
        canvas.set_line_width_px(largeur)
        canvas._output_line_px = max(0.5, largeur)
        canvas.set_legende_hors_matiere(
            bool(self.params_panel._app_settings.get(
                'legend_hors_matiere', False)))
        # Couleur par outil: il faut la bibliothèque pour nommer les
        # outils dans la légende
        canvas.set_tool_library(self.tool_library)
        canvas.op_point_clicked.connect(
            self._on_canvas_point_clicked)

    def _cle_canvas(self, tab: dict) -> str:
        """Identifiant STABLE du canvas d'un onglet.

        Ni le nom ni le rang ne conviennent: l'un se renomme,
        l'autre change quand on ferme un onglet à gauche."""
        cle = tab.get('canvas_key')
        if not cle:
            import uuid
            cle = tab['canvas_key'] = uuid.uuid4().hex[:8]
        return cle

    # ──── Bouton Matériaux (col2) ────

    def _log_action(self, text: str):
        """Enregistre une action dans l'historique et met à jour la statusbar."""
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        self._action_history.append(f"[{ts}] {text}")
        self._status_label.setText(text)
        # Mettre à jour la liste si le panel historique est visible
        if (self._history_panel is not None
                and hasattr(self._history_panel, '_list')):
            self._history_panel._list.clear()
            self._history_panel._list.addItems(
                reversed(self._action_history))

    def _create_history_panel(self) -> QWidget:
        """Journal des actions — onglet permanent de la colonne 2."""
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(8, 8, 8, 8)
        title = QLabel("Historique des actions")
        title.setStyleSheet(
            "font-weight: bold; font-size: 14px; color: #89b4fa;")
        lay.addWidget(title)
        lst = QListWidget()
        lst.setStyleSheet(
            "QListWidget { background: #181825; color: #cdd6f4; "
            "font-size: 11px; border: none; }"
            "QListWidget::item { padding: 2px 4px; }")
        lst.addItems(reversed(self._action_history))
        panel._list = lst
        lay.addWidget(lst)
        vider = QPushButton("Vider l'historique")
        vider.clicked.connect(self._on_clear_history)
        lay.addWidget(vider)
        return panel

    def _on_clear_history(self):
        self._action_history = []
        if self._history_panel is not None:
            self._history_panel._list.clear()

    def _on_dxf_action(self, action: str):
        """Boutons DXF de l'onglet « DXF to Op »."""
        panneau = self.dxf_panel
        if action == 'import':
            panneau._on_import()
        elif action == 'export':
            panneau._on_export()
        elif action == 'clear':
            panneau._on_clear()

    def _on_material_help(self):
        """Bouton « ? » de la liste des matières: ouvre la fiche.

        Un second clic la referme — elle n'a rien à faire en
        permanence dans les onglets."""
        deja = (self._materials_panel is not None
                and self._col2_tabs.indexOf(self._materials_panel) >= 0)
        self._on_materials_toggle(not deja)
        if not deja:
            self._refresh_materials_values()

    def _on_materials_toggle(self, checked: bool):
        """Toggle le panel Matériaux dans la col2."""
        if checked:
            if not hasattr(self, '_materials_panel') or self._materials_panel is None:
                self._materials_panel = self._create_materials_panel()
                self._col2_tabs.addTab(self._materials_panel, "Matériaux")
            idx = self._col2_tabs.indexOf(self._materials_panel)
            if idx >= 0:
                self._col2_tabs.setCurrentIndex(idx)
            else:
                self._col2_tabs.addTab(self._materials_panel, "Matériaux")
                self._col2_tabs.setCurrentIndex(self._col2_tabs.count() - 1)
        else:
            if hasattr(self, '_materials_panel') and self._materials_panel:
                idx = self._col2_tabs.indexOf(self._materials_panel)
                if idx >= 0:
                    self._col2_tabs.removeTab(idx)
                self._materials_panel.deleteLater()
                self._materials_panel = None

    def _refresh_materials_values(self):
        """Synchronise l'affichage des multiplicateurs de l'onglet
        Matériaux avec les valeurs EFFECTIVES du générateur (celles de
        Paramètres, matériau sélectionné prioritaire sur les manuels)."""
        if not hasattr(self, '_mat_cur_name'):
            return
        try:
            expert = self.params_panel.get_expert_settings()
        except RuntimeError:
            return
        self._mat_cur_name.setText(
            expert.get('material') or "Aucun (avances de la bibliothèque)")
        self._mat_cur_feed.setText(
            f"×{expert.get('material_feed_mult', 1.0):.2f}")
        self._mat_cur_rpm.setText(
            f"×{expert.get('material_rpm_mult', 1.0):.2f}")

    def _create_materials_panel(self) -> QWidget:
        """Crée le panel d'édition des multiplicateurs matériaux (col2)."""
        from src.core.materials import MaterialsLibrary
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        title = QLabel("Paramètres Matériaux Expert")
        title.setStyleSheet(
            "font-weight: bold; font-size: 15px; color: #fab387;")
        layout.addWidget(title)

        desc = QLabel(
            "Les avances de tools.json valent pour la matière de référence (×1).\n"
            "Sélectionnez un matériau ou ajustez manuellement les "
            "multiplicateurs.\nLes valeurs s'appliquent à toutes les "
            "opérations (feed et RPM).")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #a6adc8; font-size: 12px;")
        layout.addWidget(desc)

        # Tableau des matériaux de référence
        lib = MaterialsLibrary()
        all_mats = lib.get_all()
        if all_mats:
            mat_group = QGroupBox("Matériaux de référence")
            mat_layout = QVBoxLayout()
            mat_layout.setSpacing(2)
            for mat in all_mats:
                row = QLabel(
                    f"  {mat.name}  —  "
                    f"×{mat.feed_multiplier:.2f} feed, "
                    f"×{mat.rpm_multiplier:.2f} rpm")
                row.setStyleSheet("color: #cdd6f4; font-size: 12px;")
                mat_layout.addWidget(row)
            mat_group.setLayout(mat_layout)
            layout.addWidget(mat_group)

        # Rappel des valeurs actuelles — labels rafraîchis dynamiquement
        # (_refresh_materials_values), valeurs EFFECTIVES identiques à
        # celles utilisées par le générateur (get_expert_settings)
        current_group = QGroupBox("Valeurs actuelles (effectives)")
        cf = QFormLayout()
        cf.setSpacing(4)
        self._mat_cur_name = QLabel("--")
        self._mat_cur_feed = QLabel("--")
        self._mat_cur_rpm = QLabel("--")
        cf.addRow("Matériau sélectionné:", self._mat_cur_name)
        cf.addRow("Mult. avance appliqué:", self._mat_cur_feed)
        cf.addRow("Mult. RPM appliqué:", self._mat_cur_rpm)
        current_group.setLayout(cf)
        layout.addWidget(current_group)
        self._refresh_materials_values()

        # Aide
        help_group = QGroupBox("Conseils")
        hl = QVBoxLayout()
        hl.setSpacing(2)
        tips = [
            "• Aluminium 6061/7075 : augmenter les avances ×1.2-1.5",
            "• Acier doux : réduire avances ×0.5, RPM ×0.8",
            "• Acier inox : avances ×0.35, RPM ×0.6",
            "• POM/PMMA/PA6 : augmenter avances ×1.3-1.5",
            "• Bois dur : avances ×1.0, RPM ×0.8",
            "• Composite : avances ×0.7, RPM ×0.9",
            "",
            "Modifiez le matériau ou les multiplicateurs manuels dans "
            "l'onglet Paramètres (expert).",
        ]
        for tip in tips:
            lbl = QLabel(tip)
            lbl.setWordWrap(True)
            lbl.setStyleSheet("color: #a6adc8; font-size: 11px;")
            hl.addWidget(lbl)
        help_group.setLayout(hl)
        layout.addWidget(help_group)

        # Bouton fermer (non utilisé car le panel est toujours visible)
        close_btn = QPushButton("Fermer")
        close_btn.clicked.connect(lambda: None)  # Panel toujours visible
        layout.addWidget(close_btn)
        layout.addStretch()

        return panel

    # ──── Bouton Tips (col1) ────

    # ── Overlays pleine colonne 1 (Tips / Fichier / NDS) ──
    # Remplacent TOUTE la colonne, onglets Opérations/Paramètres cachés

    def show_col1_overlay(self, widget):
        """Affiche un panneau à la place de la colonne 1 entière."""
        prev = getattr(self, '_col1_overlay', None)
        if prev is not None and prev is not widget:
            try:
                prev.hide()
            except RuntimeError:
                pass
        self._col1_tabs.hide()
        if self._splitter.indexOf(widget) < 0:
            self._splitter.insertWidget(0, widget)
        widget.show()
        self._col1_overlay = widget

    def hide_col1_overlay(self, widget=None):
        """Restaure la colonne 1 (onglets Opérations/Paramètres)."""
        if widget is None:
            widget = getattr(self, '_col1_overlay', None)
        if widget is not None:
            try:
                widget.hide()
            except RuntimeError:
                pass
        if getattr(self, '_col1_overlay', None) is widget:
            self._col1_overlay = None
        self._col1_tabs.show()

    def _create_tips_panel(self) -> QScrollArea:
        """Page d'aide — onglet permanent de la colonne 2."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        title = QLabel("Tips Expert NeoDrive")
        title.setStyleSheet(
            "font-weight: bold; font-size: 16px; color: #89b4fa;")
        layout.addWidget(title)

        sections = [
            ("Par où commencer",
             "1. Onglet Fichier : nouveau programme, ou ouvrir un .ndp\n"
             "2. Onglet Paramètres : brut, matière, origine\n"
             "3. « + Opé » : ajouter les usinages (les sous-programmes "
             "NDS déjà enregistrés sont en haut de ce panneau)\n"
             "4. Onglet Code SimPl : relire, puis Exporter .SimPl"),
            ("Liste des opérations",
             "Chaque ligne porte, à droite :\n"
             "- ⏻ activer / désactiver (l'opération reste dans le "
             "programme mais n'est plus générée)\n"
             "- œil : aperçu au canvas, et présence sur les exports "
             "PNG et PDF\n"
             "- ★ favori\n"
             "Sur le titre d'un ENSEMBLE, l'œil et l'interrupteur "
             "valent pour tous ses membres.\n"
             "Clic droit : copier, grouper, plier, afficher/masquer, "
             "activer/désactiver la sélection."),
            ("Ensembles d'opérations",
             "Un ensemble est une suite de formulaires IDENTIQUES : "
             "même type, même outil, mêmes réglages d'outil.\n"
             "On en crée un en sélectionnant plusieurs opérations "
             "(clic droit → Grouper), on y ajoute une instance avec "
             "« + instance ».\n"
             "Un programme externe importé arrive lui aussi comme un "
             "ensemble, un membre par sous-programme."),
            ("Appeler ou importer un programme",
             "« Appel prog externe » écrit seulement l'appel : le "
             "fichier reste tel quel.\n"
             "« Importer » (bouton à côté de l'aperçu) le remplace par "
             "ses sous-programmes, réglables un par un. Ctrl+Z "
             "rétablit l'appel.\n"
             "Sur un bloc importé, le bouton loupe retrouve dans "
             "tools.json l'outil de MÊME RÉFÉRENCE : rien à changer "
             "dans la séquence, seulement dans le sous-programme."),
            ("Répétitions plutôt que Pattern",
             "La répétition (NbX/PasX, NbY/PasY) décale l'origine avec "
             "ShiftWcsInc et revient au point de départ : le canvas la "
             "dessine, et l'ébavurage la suit.\n"
             "Pattern::RectanglePattern est une fonction machine qui "
             "utilise le SafeRapid; elle reste disponible en mode "
             "expert."),
            ("SafeRapid Z",
             "SafeRapid Z = strokeRapidZ + strokeCuttingZ.\n"
             "- strokeRapidZ (défaut : 14) : hauteur de déplacement "
             "rapide\n"
             "- strokeCuttingZ (défaut : 1) : hauteur d'approche en "
             "avance\n"
             "Adaptez strokeCuttingZ si la pièce n'est pas plane."),
            ("Matière",
             "Les avances de tools.json valent pour la matière de référence (×1). "
             "La matière choisie applique deux multiplicateurs :\n"
             "- Alu 6061 : ×1.3 avance, ×1.0 régime\n"
             "- Acier doux : ×0.5 avance, ×0.8 régime\n"
             "- Inox : ×0.35 avance, ×0.6 régime\n"
             "- POM/plastique : ×1.5 avance, ×1.0 régime\n"
             "Le bouton « ? » à côté de la liste ouvre la fiche "
             "complète; les multiplicateurs restent modifiables à la "
             "main dans Paramètres expert."),
            ("Profondeur Pz = 0",
             "La Datron refuse d'usiner avec Pz=0.\n"
             "NeoDrive contourne automatiquement : ShiftWcsInc Z=0.1, "
             "puis Pz=0.1, puis ShiftWcsInc Z=-0.1 après l'opération."),
            ("Ébavurage",
             "L'ébavurage regroupe tous les points et optimise le "
             "chemin (plus proche voisin) pour limiter les "
             "déplacements.\n"
             "Profondeur = 0,5 × diamètre du filet + offset.\n"
             "Il suit les répétitions de son opération."),
            ("Tracé (centre fraise)",
             "Le CENTRE de la fraise suit le parcours, sans correction "
             "de rayon : placez le tracé là où l'outil doit passer, ou "
             "utilisez le décalage intérieur/extérieur.\n"
             "Formes : rectangle, cercle, polygone régulier, spirale, "
             "points saisis, contour relevé au canvas.\n"
             "Le parcours est recalculé à chaque génération; un cache "
             "évite de le refaire quand rien n'a changé."),
            ("Décalage d'origine",
             "« Créer l'opération inverse » génère le ShiftWcsInc de "
             "retour. Les opérations jumelées portent la même "
             "couleur."),
            ("Batch édition",
             "Traite plusieurs .SimPl d'un coup : outil, régime, "
             "avances, commentaire, brut, et troncature ou extension "
             "de la profondeur des séquences.\n"
             "Chaque fichier modifié est sauvegardé en .bak."),
            ("Gros programmes",
             "Au-delà de 4 000 lignes, la coloration du code ne traite "
             "que ce qui est à l'écran, et se poursuit au défilement : "
             "c'est voulu, pas un bug d'affichage."),
            ("Raccourcis",
             "Ctrl+Z / Ctrl+Y : annuler / rétablir\n"
             "Ctrl+C / Ctrl+V : copier / coller une opération\n"
             "Ctrl+D : dupliquer\n"
             "Ctrl+E : export SimPl\n"
             "Ctrl+F : rechercher dans le code\n"
             "Ctrl+Shift+E : activer/désactiver l'opération\n"
             "Suppr : supprimer l'opération\n"
             "F5 : régénérer le code\n"
             "F11 : plein écran"),
        ]

        for sec_title, sec_text in sections:
            group = QGroupBox(sec_title)
            group.setStyleSheet(
                "QGroupBox { font-weight: bold; color: #f9e2af; "
                "font-size: 12px; border: 1px solid #45475a; "
                "border-radius: 4px; margin-top: 6px; padding-top: 12px; }"
                "QGroupBox::title { subcontrol-origin: margin; "
                "padding: 0 6px; }")
            gl = QVBoxLayout()
            lbl = QLabel(sec_text)
            lbl.setWordWrap(True)
            lbl.setStyleSheet("color: #cdd6f4; font-size: 11px;")
            gl.addWidget(lbl)
            group.setLayout(gl)
            layout.addWidget(group)

        layout.addStretch()

        scroll.setWidget(content)
        return scroll

    def _on_about(self):
        """Version, auteur, licence (MIT ou Apache-2.0) et ses textes."""
        from src.gui.dialogs.a_propos import DialogueAPropos
        DialogueAPropos(self).exec()

    def _program_from_dict(self, data: dict) -> ProgramModel:
        """Reconstruit un ProgramModel à partir d'un dict (session,
        duplication): outil absent, opération inconnue et champ
        inconnu gardés, comme à l'ouverture d'un .ndp."""
        from src.core.program_model import programme_depuis_dict
        return programme_depuis_dict(data, self.tool_library.tools)

    @staticmethod
    def _session_writes_allowed() -> bool:
        """L'instance a-t-elle le droit d'ecrire la session ?

        Non si `NEODRIVE_NO_SESSION` est pose, non si Qt tourne sans
        ecran (`offscreen`): c'est le cas des tests et des bancs de
        mesure, qui creent des MainWindow jetables."""
        if os.environ.get('NEODRIVE_NO_SESSION'):
            return False
        if os.environ.get('QT_QPA_PLATFORM', '') == 'offscreen':
            return False
        # Lancement par un harnais de test, meme avec un ecran
        argv0 = os.path.basename((sys.argv[0] if sys.argv else '') or '')
        argv0 = argv0.lower()
        return not (argv0.startswith(('pytest', 'py.test'))
                    or 'unittest' in argv0)

    def _backup_session(self, path: str):
        """Garde les deux versions precedentes de la session.

        Une session ecrasee par erreur (mauvaise manipulation, second
        NeoDrive lance) redevient recuperable a la main."""
        try:
            if not os.path.exists(path):
                return
            premier, second = path + ".bak", path + ".bak2"
            if os.path.exists(premier):
                if os.path.exists(second):
                    os.remove(second)
                os.replace(premier, second)
            import shutil
            shutil.copy2(path, premier)
        except Exception:
            pass        # une sauvegarde ratee ne doit rien bloquer

    def _auto_save(self):
        """Sauvegarde tous les onglets dans un fichier session JSON."""
        if not getattr(self, '_session_writable', True):
            return
        try:
            self._save_current_tab_state()
            session = {
                "active_tab": self._active_tab_index,
                "tabs": [],
            }
            for tab in self._program_tabs:
                prog = tab["program"]
                tab_data = {
                    "name": tab["name"],
                    "filepath": tab.get("filepath", ""),
                    "program": prog.to_dict(),
                    # enregistré ou pas: une session restaurée le garde
                    "modifie": bool(prog.is_modified),
                }
                if tab.get("last_export_code"):
                    tab_data["last_export_code"] = \
                        tab["last_export_code"]
                if tab.get("vue"):
                    tab_data["vue"] = tab["vue"]
                if tab.get("chemin_simpl"):
                    tab_data["chemin_simpl"] = tab["chemin_simpl"]
                session["tabs"].append(tab_data)
            session_path = self._autosave_path.replace(
                '.ndp', '_session.json')
            self._backup_session(session_path)
            from src.core.fichiers_surs import ecrire_json_sur
            ecrire_json_sur(session_path, session, indent=2,
                            ensure_ascii=False)
        except Exception as e:
            # Ne pas échouer en silence: l'utilisateur croirait sa
            # session protégée alors qu'elle ne l'est pas.
            try:
                self._status_label.setText(f"⚠ Auto-save échoué: {e}")
            except Exception:
                pass

    @staticmethod
    def _onglet_session_modifie(tab_data: dict) -> bool:
        """L'onglet de session portait-il des modifications non
        enregistrées? Une session d'avant ce drapeau: un programme qui
        a des opérations mais aucun fichier ne l'a jamais été."""
        if "modifie" in tab_data:
            return bool(tab_data.get("modifie"))
        ops = (tab_data.get("program") or {}).get("operations") or []
        return bool(ops) and not tab_data.get("filepath")

    def _auto_restore(self):
        """Restaure tous les onglets depuis le fichier session."""
        session_path = self._autosave_path.replace(
            '.ndp', '_session.json')
        try:
            if os.path.exists(session_path):
                # Illisible (coupure pendant l'écriture), la session
                # était perdue: aucun onglet restauré, puis la
                # sauvegarde automatique écrivait une session vide
                # par-dessus — et ses copies .bak suivaient. Elle est
                # mise de côté et la précédente (.bak) reprise.
                from src.core.fichiers_surs import lire_json_sur
                session, _alerte = lire_json_sur(session_path)
                if not isinstance(session, dict):
                    raise ValueError("session illisible")
                tabs_data = session.get("tabs", [])
                if not tabs_data:
                    return
                # Restaurer le premier onglet dans le programme existant
                first = tabs_data[0]
                first_prog = self._program_from_dict(
                    first["program"])
                self.program.settings = first_prog.settings
                self.program.description = first_prog.description
                for op in first_prog.operations:
                    self.program.add_operation(op)
                self.program.reprendre_conservation(first_prog)
                # Restaurer l'association fichier: sinon Ctrl+S redemande
                # "Enregistrer sous" et _save_current_tab_state écrase le
                # filepath de l'onglet avec "" au prochain autosave.
                first_fp = first.get("filepath", "")
                self.program.filepath = first_fp or None
                self.program.mark_saved()
                if self._onglet_session_modifie(first):
                    self.program.mark_unsaved()
                self._program_tabs[0]["name"] = first.get("name", "P1")
                self._program_tabs[0]["filepath"] = first_fp
                self._program_tabs[0]["last_export_code"] = \
                    first.get("last_export_code", "")
                if isinstance(first.get("vue"), dict):
                    self._program_tabs[0]["vue"] = first["vue"]
                self._program_tabs[0]["chemin_simpl"] = str(
                    first.get("chemin_simpl") or "")
                self._prog_tabbar.setTabText(
                    0, self._program_tabs[0]["name"])
                # Restaurer les onglets suivants
                for tab_data in tabs_data[1:]:
                    prog = self._program_from_dict(
                        tab_data["program"])
                    prog.filepath = tab_data.get("filepath", "") or None
                    prog.mark_saved()
                    if self._onglet_session_modifie(tab_data):
                        prog.mark_unsaved()
                    name = tab_data.get("name", self._next_p_name())
                    idx = len(self._program_tabs)
                    self._program_tabs.append({
                        "program": prog,
                        "filepath": tab_data.get("filepath", ""),
                        "name": name,
                        "last_export_code": tab_data.get(
                            "last_export_code", ""),
                        "vue": tab_data.get("vue") if isinstance(
                            tab_data.get("vue"), dict) else None,
                        "chemin_simpl": str(
                            tab_data.get("chemin_simpl") or ""),
                    })
                    self._prog_tabbar.blockSignals(True)
                    self._prog_tabbar.addTab(name)
                    self._prog_tabbar.blockSignals(False)
                # Activer l'onglet actif sauvegardé
                active = session.get("active_tab", 0)
                if 0 <= active < len(self._program_tabs):
                    self._restauration_en_cours = True
                    try:
                        self._prog_tabbar.setCurrentIndex(active)
                    finally:
                        self._restauration_en_cours = False
                    # au démarrage: ses onglets de colonnes, sa vue 2D
                    # et sa caméra 3D (les largeurs suivent la fenêtre)
                    vue = self._program_tabs[active].get("vue")
                    if vue:
                        self.appliquer_vue(vue, tailles=False, vue2d=True)
                self._refresh_tab_titles()
                self.params_panel.refresh_from_model()
                total_ops = sum(
                    t["program"].operation_count
                    for t in self._program_tabs)
                self._status_label.setText(
                    f"Session restaurée ({len(self._program_tabs)} "
                    f"onglets, {total_ops} ops)")
        except Exception:
            # Fallback: ancien format .ndp
            try:
                if os.path.exists(self._autosave_path):
                    restored = ProgramSerializer.load(
                        self._autosave_path, self.tool_library)
                    if restored.operation_count > 0:
                        self.program.settings = restored.settings
                        for op in restored.operations:
                            self.program.add_operation(op)
                        self.program.mark_saved()
                        self.params_panel.refresh_from_model()
                        self._status_label.setText(
                            f"Session restaurée "
                            f"({self.program.operation_count} ops)")
            except Exception:
                pass

    # ── Glisser-déposer de fichiers ──

    _DROP_EXTS = ('.ndp', '.nds', '.simpl', '.ndjob', '.dxf', '.pdf',
                  '.ai', '.eps', '.ps', '.svg', '.cdr')

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith(self._DROP_EXTS):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            # Déposé SUR un programme, un .nds s'y insère: c'est le
            # geste du sous-programme. Ouvert depuis l'Explorateur,
            # il s'ouvre dans un onglet, comme un .ndp.
            self.ouvrir_fichier(url.toLocalFile(), insertion=True)
        event.acceptProposedAction()

    #: dessins que le canvas sait lire
    EXTENSIONS_DESSIN = ('.dxf', '.pdf', '.ai', '.eps', '.ps', '.svg',
                         '.cdr', '.emf', '.wmf', '.emz', '.wmz', '.png',
                         '.jpg', '.jpeg', '.bmp', '.gif', '.tif', '.tiff',
                         '.stp', '.step', '.stl', '.3dxml', '.igs',
                         '.iges', '.dwg', '.catpart', '.catproduct')

    def ouvrir_fichier(self, path: str, insertion: bool = False) -> bool:
        """Ouvre un fichier comme le ferait l'Explorateur.

        .ndp et .nds: dans un onglet (un onglet neuf si le courant
        n'est pas vide) — sauf `insertion`, où un .nds s'ajoute au
        programme courant. .SimPl: un programme NeoDrive (NDMETA) se
        reconstruit; un programme externe donne un onglet avec un
        « Appel prog externe » qui le cite. Un dessin va au canvas.
        Rend vrai si quelque chose a été ouvert."""
        if not path or not os.path.isfile(path):
            return False
        low = path.lower()
        if low.endswith('.nds') and insertion:
            self._import_subprogram_file(path)
            return True
        if low.endswith(('.ndp', '.nds')):
            self._onglet_libre()
            self._load_program(path)
            return True
        if low.endswith('.simpl'):
            self._ouvrir_simpl(path)
            return True
        if low.endswith('.ndjob'):
            return self.ouvrir_travail_vectordrive(path)
        if low.endswith(self.EXTENSIONS_DESSIN):
            self.dxf_panel.charger_dessin(path)
            self.montrer_onglet(self.dxf_panel)
            return True
        return False

    def recevoir_fichiers(self, fichiers) -> int:
        """Un autre lancement de NeoDrive nous passe ses fichiers:
        chacun s'ouvre dans un onglet, et la fenêtre se met devant —
        même sans fichier, c'est ce qu'un double-clic sur l'exe
        demande. Rend le nombre de fichiers ouverts."""
        ouverts = 0
        for chemin in fichiers or []:
            try:
                if self.ouvrir_fichier(chemin):
                    ouverts += 1
            except Exception:
                continue
        try:
            if self.isMinimized():
                self.showNormal()
            self.show()
            self.raise_()
            self.activateWindow()
        except RuntimeError:
            pass
        return ouverts

    #: réponse des tests à « ajouter les outils absents ? » (None:
    #: demander; True/False: répondre sans fenêtre)
    reponse_outils_vectordrive = None

    def ouvrir_travail_vectordrive(self, path: str) -> bool:
        """Un travail de VectorDrive (.ndjob, écrit par son plugin
        « NeoDrive »): ses parcours deviennent un programme NeoDrive dans
        un onglet — séquences Datron, trous, poches, surfaçages,
        palpages et instructions. Les outils absents de la bibliothèque
        y sont ajoutés si on le veut (sinon pour cette session)."""
        from src.io import vectordrive_job as vj
        try:
            job = vj.lire(path)
        except vj.JobError as exc:
            QMessageBox.warning(self, "Travail VectorDrive", str(exc))
            return False
        _corr, absents = vj.correspondance_outils(job, self.tool_library,
                                                  ajouter='non')
        mode = 'memoire'
        if absents:
            rep = self.reponse_outils_vectordrive
            if rep is None:
                noms = "\n".join(f"• {o.get('nom', '?')} "
                                  f"({o.get('reference') or 'sans référence'})"
                                  for o in absents[:12])
                rep = QMessageBox.question(
                    self, "Travail VectorDrive",
                    f"{len(absents)} outil(s) de VectorDrive absent(s) de la "
                    f"bibliothèque NeoDrive:\n{noms}\n\nLes ajouter à la "
                    "bibliothèque (tools.json) ? Sinon, ils servent à ce "
                    "programme seulement.",
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No) \
                    == QMessageBox.StandardButton.Yes
            mode = 'enregistrer' if rep else 'memoire'
        prog, avert, _absents = vj.programme_depuis_job(
            job, self.tool_library, ajouter_outils=mode)
        self._onglet_libre()
        self.program.clear()
        self.program.settings = prog.settings
        for op in prog.operations:
            self.program.add_operation(op)
        self.params_panel.refresh_from_model()
        self.operations_panel.refresh_specs_fields()
        nom = os.path.splitext(os.path.basename(path))[0]
        try:
            self._update_prog_tab_name(path)
        except Exception:
            pass
        self._regenerate_code()
        self._status_label.setText(
            f"VectorDrive: {self.program.operation_count} opération(s) de "
            f"« {nom} »" + (f" — {len(avert)} avertissement(s)"
                            if avert else ""))
        self._log_action(f"Travail VectorDrive ouvert: {nom}"
                         + "".join(f"\n  • {a}" for a in avert[:20]))
        return True

    def _onglet_libre(self):
        """Un onglet vide pour y ouvrir un fichier: le courant s'il
        n'a rien, un neuf sinon — on n'écrase pas un travail en
        cours."""
        if self.program.operation_count or self.program.is_modified \
                or self.program.filepath:
            self._on_new_prog_tab()

    def _ouvrir_simpl(self, path: str):
        """Un .SimPl ouvert depuis l'Explorateur.

        Un programme NeoDrive porte ses métadonnées: on le
        reconstruit. Un programme externe (TypeEdit, à la main)
        devient un onglet qui l'APPELLE — le geste de l'atelier pour
        habiller un programme existant de son palpage et de ses
        changements d'outil."""
        from src.io.simpl_importer import extract_neodrive_metadata
        try:
            with open(path, 'r', encoding='utf-8-sig',
                      errors='replace') as f:
                brut = f.read()
        except OSError as exc:
            QMessageBox.warning(self, "Ouvrir",
                                f"Impossible de lire:\n{exc}")
            return
        self._onglet_libre()
        if extract_neodrive_metadata(brut) is not None:
            self._import_simpl_file(path)
            return
        from src.core.program_model import OperationInstance
        from src.core import sim_cycles
        # rouvert: une simulation annulée de ce fichier peut reprendre
        sim_cycles.oublier_refus(path)
        nom = os.path.splitext(os.path.basename(path))[0]
        op = OperationInstance("appel_programme", nom)
        op.params['filepath'] = path
        self.program.add_operation(op)
        self._update_prog_tab_name(path)
        self._log_action(f"Appel du programme externe: "
                         f"{os.path.basename(path)}")

    # ── Géométrie de la fenêtre ──

    def afficher_au_demarrage(self):
        """Montre la fenêtre comme on l'a laissée, plein écran sinon.

        L'ordre compte: une VRAIE taille d'abord, show(), et
        seulement ensuite showMaximized(). Maximiser une fenêtre qui
        n'a pas encore de taille la laisse à son minimum."""
        reglages = self.params_panel._app_settings
        geometrie = reglages.get('window_geometry', '')
        maximisee = bool(reglages.get('window_maximized', True))
        restauree = False
        if geometrie:
            try:
                from PySide6.QtCore import QByteArray
                restauree = self.restoreGeometry(
                    QByteArray.fromBase64(geometrie.encode('ascii')))
            except Exception:
                restauree = False
        ecran = QApplication.primaryScreen()
        if restauree and ecran is not None:
            # un écran débranché depuis: la fenêtre serait hors champ
            visible = any(e.availableGeometry().intersects(
                self.frameGeometry()) for e in QApplication.screens())
            if not visible:
                restauree = False
        if not restauree and ecran is not None:
            self.resize(ecran.availableGeometry().size())
        self.show()
        if maximisee or not restauree:
            self.showMaximized()
        # Et quoi qu'il arrive, dans la zone de travail: une fenêtre
        # plus haute que l'écran moins la barre des tâches passe
        # derrière elle, et rien ne l'en sort.
        QTimer.singleShot(0, self.rester_dans_l_ecran)
        QTimer.singleShot(0, self._montrer_alertes_donnees)
        # les onglets sortis en fenêtres, sur leurs écrans (la dernière
        # disposition) — pas pour une capture
        if "--capture" not in sys.argv:
            QTimer.singleShot(0, self.onglets_fenetres.au_demarrage)

    def _montrer_alertes_donnees(self) -> list:
        """Un fichier de données illisible au démarrage: on le DIT, avant
        qu'un programme parte avec la mauvaise bibliothèque d'outils.
        Fenêtre non bloquante, et la barre d'état le répète."""
        # une mise à jour des fiches (L coupe / L utile): pas une
        # alerte, une information — la barre d'état et le journal
        note = getattr(self.tool_library, 'note', '')
        if note:
            try:
                self.statusBar().showMessage(note, 20000)
                self._log_action(note)
            except Exception:
                pass
        from src.core.fichiers_surs import alertes_en_attente
        alertes = list(dict.fromkeys([a for a in (
            getattr(self.tool_library, 'alerte', None),
            getattr(getattr(self, 'params_panel', None),
                    'alerte_reglages', None)) if a]
            + alertes_en_attente()))
        if not alertes:
            return []
        try:
            self.statusBar().showMessage("⚠ " + alertes[0], 30000)
        except Exception:
            pass
        boite = QMessageBox(QMessageBox.Icon.Warning,
                            "Fichier de données illisible",
                            "\n\n".join(alertes),
                            QMessageBox.StandardButton.Ok, self)
        boite.setModal(False)
        boite.show()
        self._boite_alertes = boite
        return alertes

    def rester_dans_l_ecran(self) -> bool:
        """Ramène la fenêtre dans la zone de travail de son écran.

        Rend True si elle a dû bouger. Maximisée, c'est le système
        qui la borne — à condition que son minimum le permette, ce
        que `test_la_fenetre_tient_sur_un_petit_ecran` garantit."""
        ecran = self.screen() or QApplication.primaryScreen()
        if ecran is None or self.isMaximized() or self.isFullScreen():
            return False
        zone = ecran.availableGeometry()
        cadre = self.frameGeometry()
        if zone.contains(cadre):
            return False
        # la bordure du système: différence entre cadre et contenu
        marge_h = cadre.width() - self.width()
        marge_v = cadre.height() - self.height()
        largeur = min(cadre.width(), zone.width())
        hauteur = min(cadre.height(), zone.height())
        x = min(max(cadre.x(), zone.x()), zone.x() + zone.width() - largeur)
        y = min(max(cadre.y(), zone.y()), zone.y() + zone.height() - hauteur)
        self.resize(max(1, largeur - marge_h), max(1, hauteur - marge_v))
        self.move(x, y)
        return True

    def _memoriser_geometrie(self):
        """Ce qu'il faut pour rouvrir la fenêtre au même endroit."""
        try:
            reglages = self.params_panel._app_settings
            reglages['window_maximized'] = bool(self.isMaximized())
            if not self.isMaximized():
                reglages['window_geometry'] = bytes(
                    self.saveGeometry().toBase64()).decode('ascii')
            self.params_panel.save_app_settings()
        except Exception:
            pass

    def closeEvent(self, event):
        # la Batch édition n'est pas dans la session: un .SimPl corrigé
        # à l'écran et pas enregistré se perdait à la fermeture
        edition = getattr(self, 'simpl_edit_panel', None)
        if edition is not None and not edition.peut_quitter_le_fichier(
                "avant de fermer NeoDrive"):
            event.ignore()
            return
        self._memoriser_geometrie()
        gestion = getattr(self, 'onglets_fenetres', None)
        if gestion is not None:
            try:
                gestion.a_la_fermeture()
                # les fenêtres d'onglets ne survivent pas à la fenêtre
                gestion.tout_rattacher()
            except Exception:
                pass
        self._auto_save()
        event.accept()
