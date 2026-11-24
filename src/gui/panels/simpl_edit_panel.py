"""
Onglet Batch édition (col2): traitement EN LOT de fichiers SimPl
externes.

Le panneau part d'un navigateur de dossier où l'on sélectionne un
fichier, plusieurs, ou des dossiers entiers (= tous les SimPl qu'ils
contiennent), puis trois actions:

  ① Chargement  — lit la sélection et affiche ce qu'elle contient:
    brut (@ WorkpieceGeometry @), auteur, commentaire et outils
    employés. Un outil est toujours restitué avec sa RÉFÉRENCE (celle
    déclarée en @ ToolDescription @, à défaut celle de tools.json), sa
    SetFeedTechnology et son régime (Rpm ou newRpm).
  ② Opérations NeoDrive — chaque fichier devient un onglet programme
    dont les sous-programmes rejoignent la liste d'opérations.
  ③ Batch modif — outil, régime, avances, profondeurs (échelle,
    offset, cote finale des séquences), brut, auteur, commentaire
    appliqués à toute la sélection (backup .bak + entrée d'historique
    dans chaque fichier modifié).

Un double-clic ouvre un fichier dans l'onglet Code pour le lire, le
retoucher à la main et l'enregistrer (backup .bak) — le lot ne
dispense pas de vérifier une pièce avant de lancer la série.
"""

import os

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QCheckBox, QGroupBox, QFormLayout,
    QFileDialog, QMessageBox, QTreeView, QFileSystemModel,
    QSplitter, QTabWidget, QTextEdit, QDialog, QDialogButtonBox,
    QAbstractItemView, QGridLayout
)
from PySide6.QtCore import Qt, Signal, QDir

from src.gui.panels.code_editor_panel import (
    CodeEditor, SimPlSyntaxHighlighter)
from src.gui.widgets import SpinCote, SpinEntier
from src.gui.indicateur_structure import (IndicateurStructure,
                                          confirmer_structure)
from src.gui.theme import COLORS
from src.io import simpl_batch
from src.io import simpl_scan


class _Spin(SpinCote):
    def __init__(self, decimals=2, lo=-999.0, hi=999.0, val=0.0,
                 parent=None):
        super().__init__(parent, decimales=decimals)
        self.setMaximumWidth(80)
        self.setMaximumHeight(24)
        self.setRange(lo, hi)
        self.setValue(val)


class _IntSpin(SpinEntier):
    """L'unité se lit dans l'étiquette, à gauche du champ."""
    def __init__(self, hi=100000, val=0, parent=None):
        super().__init__(parent)
        self.setMaximumWidth(90)
        self.setMaximumHeight(24)
        self.setRange(0, hi)
        self.setValue(val)
        self.setSpecialValueText("—")     # 0 = inchangé


class BatchModifyDialog(QDialog):
    """Modifications à appliquer à toute la sélection.

    Tout champ laissé vide (ou à 0) est INCHANGÉ: on ne réécrit jamais
    une valeur que l'utilisateur n'a pas demandée."""

    def __init__(self, scans, tool_library, n_files, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Modification en lot")
        self.resize(560, 520)
        self._tool_library = tool_library
        self._scans = scans
        self._build(n_files)

    def _build(self, n_files):
        v = QVBoxLayout(self)
        head = QLabel(
            f"{n_files} fichier(s) seront modifiés sur le disque.\n"
            f"Une copie .bak est créée et chaque fichier reçoit une "
            f"ligne d'historique.")
        head.setStyleSheet(
            f"color: {COLORS['warn_text']}; background: "
            f"{COLORS['warn_bg']}; padding: 6px; border-radius: 4px;")
        head.setWordWrap(True)
        v.addWidget(head)

        file_tools = simpl_scan.all_tools(self._scans)

        # ── Outil ──
        grp = QGroupBox("Outil")
        f = QFormLayout()
        f.setSpacing(4)
        self._old_tool = QComboBox()
        self._old_tool.addItem("(ne pas changer d'outil)", "")
        for tool in file_tools:
            article = tool.get('article') or ''
            label = tool.get('name') or tool.get('declared') or '?'
            suffix = f" [{article}]" if article else " [réf. inconnue]"
            # Sans référence, replace_tool ne peut pas cibler la ligne
            self._old_tool.addItem(
                label + suffix, article or tool.get('declared', ''))
        f.addRow("Remplacer :", self._old_tool)
        self._new_tool = QComboBox()
        self._new_tool.addItem("(choisir dans tools.json)", "")
        if self._tool_library:
            for tool in self._tool_library.get_all_tools():
                self._new_tool.addItem(
                    f"{tool.name} [{tool.article_nr}]", tool.article_nr)
        f.addRow("Par :", self._new_tool)
        self._with_specs = QCheckBox(
            "Reprendre régime et avances de tools.json")
        self._with_specs.setChecked(True)
        f.addRow("", self._with_specs)
        grp.setLayout(f)
        v.addWidget(grp)

        # ── Régime et avances ──
        grp2 = QGroupBox("Régime et avances (0 = inchangé)")
        g = QGridLayout()
        g.setSpacing(4)
        g.addWidget(QLabel("Sur :"), 0, 0)
        self._target = QComboBox()
        self._target.addItem("tous les outils", "")
        for tool in file_tools:
            label = tool.get('name') or tool.get('declared') or '?'
            self._target.addItem(
                label, tool.get('declared') or tool.get('article', ''))
        g.addWidget(self._target, 0, 1, 1, 3)
        g.addWidget(QLabel("Régime (tr/min) :"), 1, 0)
        self._rpm = _IntSpin(hi=100000)
        g.addWidget(self._rpm, 1, 1)
        self._feeds = {}
        labels = [('finishing', "Finition"), ('approach', "Approche"),
                  ('plunge', "Plongée"), ('ramp', "Rampe"),
                  ('roughing', "Ébauche")]
        for i, (key, label) in enumerate(labels):
            row, col = 2 + i // 2, (i % 2) * 2
            g.addWidget(QLabel(label + " (mm/min) :"),
                        row, col)
            spin = _IntSpin(hi=99999)
            self._feeds[key] = spin
            g.addWidget(spin, row, col + 1)
        self._add_missing = QCheckBox(
            "Ajouter la ligne si l'outil visé n'en a pas")
        self._add_missing.setChecked(True)
        self._add_missing.setToolTip(
            "Un bloc sans Rpm ni SetFeedTechnology tourne aux valeurs "
            "par défaut de l'outil machine. L'ajout n'a lieu que sur "
            "un outil VISÉ — jamais sur « tous les outils ».")
        g.addWidget(self._add_missing, 5, 0, 1, 4)
        grp2.setLayout(g)
        v.addWidget(grp2)

        # ── Profondeurs ──
        grp_z = QGroupBox("Profondeurs Z")
        zg = QGridLayout()
        zg.setSpacing(4)
        zg.addWidget(QLabel("Z = Z × échelle + offset"), 0, 0, 1, 4)
        zg.addWidget(QLabel("Échelle :"), 1, 0)
        self._z_scale = _Spin(decimals=3, lo=0.01, hi=10.0, val=1.0)
        zg.addWidget(self._z_scale, 1, 1)
        zg.addWidget(QLabel("Offset (mm) :"), 1, 2)
        self._z_offset = _Spin(decimals=2, lo=-50.0, hi=50.0, val=0.0)
        zg.addWidget(self._z_offset, 1, 3)
        zg.addWidget(QLabel("Z final des séquences (mm) :"), 2, 0, 1, 2)
        self._z_final = _Spin(decimals=2, lo=-200.0, hi=0.0, val=0.0)
        self._z_final.setToolTip(
            "0 = inchangé. Moins profond : les passes trop basses "
            "sont commentées et la dernière passe conservée est "
            "ramenée à cette cote.\nPlus profond : des passes sont "
            "ajoutées au pas des précédentes.")
        zg.addWidget(self._z_final, 2, 2)
        self._z_extend = QCheckBox("autoriser l'approfondissement")
        self._z_extend.setToolTip(
            "Décoché (défaut), le lot ne fait que REMONTER les "
            "séquences trop profondes. Coché, une séquence moins "
            "profonde que la cote reçoit des passes supplémentaires "
            "— une gravure à -0,1 deviendrait un usinage à la cote.")
        zg.addWidget(self._z_extend, 2, 3)

        self._z_sequences = QCheckBox(
            "Appliquer aussi aux séquences $$$")
        self._z_sequences.setChecked(True)
        self._z_sequences.setToolTip(
            "Les séquences portent leur Z ligne à ligne. Décoché, "
            "seules les fonctions Datron (depth=) sont reprises.\n"
            "Les dégagements (Z > 0) ne sont jamais touchés.")
        zg.addWidget(self._z_sequences, 3, 0, 1, 4)
        warn = QLabel("Modifie des profondeurs d'usinage : vérifiez "
                      "un fichier avant de lancer la série.")
        warn.setWordWrap(True)
        warn.setStyleSheet(f"color: {COLORS['orange']};")
        zg.addWidget(warn, 4, 0, 1, 4)
        grp_z.setLayout(zg)
        v.addWidget(grp_z)

        # ── Brut ──
        grp3 = QGroupBox("Brut (@ WorkpieceGeometry @)")
        wg = QGridLayout()
        wg.setSpacing(4)
        self._wp_cb = QCheckBox("Redéfinir le brut")
        wg.addWidget(self._wp_cb, 0, 0, 1, 6)
        self._wp = {}
        base = self._first_workpiece()
        for col, axis in enumerate("XYZ"):
            wg.addWidget(QLabel(f"{axis} min"), 1, col * 2)
            lo = _Spin(lo=-9999.0, hi=9999.0,
                       val=base[f'min_{axis.lower()}'])
            self._wp[f'min_{axis.lower()}'] = lo
            wg.addWidget(lo, 1, col * 2 + 1)
            wg.addWidget(QLabel(f"{axis} max"), 2, col * 2)
            hi = _Spin(lo=-9999.0, hi=9999.0,
                       val=base[f'max_{axis.lower()}'])
            self._wp[f'max_{axis.lower()}'] = hi
            wg.addWidget(hi, 2, col * 2 + 1)
        grp3.setLayout(wg)
        v.addWidget(grp3)

        # ── En-tête ──
        grp4 = QGroupBox("En-tête (vide = inchangé)")
        f4 = QFormLayout()
        f4.setSpacing(4)
        self._author = QLineEdit()
        f4.addRow("Auteur :", self._author)
        self._comment = QLineEdit()
        f4.addRow("Commentaire :", self._comment)
        grp4.setLayout(f4)
        v.addWidget(grp4)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Ok).setText(
            "Appliquer")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        v.addWidget(btns)

    def _first_workpiece(self):
        """Pré-remplit avec le brut du premier fichier qui en déclare
        un: on part de l'existant plutôt que de zéros."""
        for info in self._scans:
            wp = info.get('workpiece')
            if wp:
                return wp
        return {'min_x': 0.0, 'min_y': 0.0, 'min_z': 0.0,
                'max_x': 0.0, 'max_y': 0.0, 'max_z': 0.0}

    def changes(self) -> dict:
        out = {}
        old, new = self._old_tool.currentData(), \
            self._new_tool.currentData()
        if old and new:
            out['tool'] = {'old': old, 'new': new,
                           'with_specs': self._with_specs.isChecked()}
        if self._rpm.value():
            out['rpm'] = self._rpm.value()
        feeds = {k: s.value() for k, s in self._feeds.items()
                 if s.value()}
        if feeds:
            out['feeds'] = feeds
        if 'rpm' in out or 'feeds' in out:
            # La cible et l'ajout ne concernent que régime/avances:
            # les porter seuls ferait croire à une modification
            target = self._target.currentData()
            if target:
                out['target'] = {'article': target, 'name': target}
            out['add_missing'] = self._add_missing.isChecked()
        if self._z_scale.value() != 1.0 or self._z_offset.value() != 0.0:
            out['depths'] = {
                'scale': self._z_scale.value(),
                'offset': self._z_offset.value(),
                'sequences': self._z_sequences.isChecked(),
            }
        if self._z_final.value() < 0:
            out['sequence_depth'] = self._z_final.value()
            out['sequence_depth_extend'] = self._z_extend.isChecked()
        if self._wp_cb.isChecked():
            out['workpiece'] = {k: s.value()
                                for k, s in self._wp.items()}
        if self._author.text().strip():
            out['author'] = self._author.text().strip()
        if self._comment.text().strip():
            out['comment'] = self._comment.text().strip()
        return out


class SimplEditPanel(QWidget):
    """Navigateur de fichiers SimPl et traitements en lot."""

    # Émis pour créer une opération Séquence Datron dans le programme
    # actif: (nom_sequence, code_sequence)
    sequence_to_operation = Signal(str, str)

    #: fichier à charger comme opérations dans la colonne 1
    blocks_available = Signal(str)

    def __init__(self, tool_library=None, parent=None):
        super().__init__(parent)
        self._tool_library = tool_library
        self._filepath = ""
        #: le texte tel qu'il est sur le disque (chargé ou enregistré):
        #: la référence pour sceller le NDMETA d'un fichier corrigé
        self._texte_disque = ""
        self._modified = False
        self._scans = []
        self._setup_ui()

    # ── UI ──

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # ── Barre dossier ──
        bar = QHBoxLayout()
        bar.setSpacing(4)
        folder_btn = QPushButton("📁 Dossier...")
        folder_btn.setObjectName("primary")
        folder_btn.setToolTip(
            "Racine du navigateur. Sélection multiple possible: "
            "plusieurs fichiers, ou des dossiers entiers.")
        folder_btn.clicked.connect(self._on_choose_folder)
        bar.addWidget(folder_btn)
        self._root_label = QLabel("(aucun dossier)")
        self._root_label.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 11px;")
        bar.addWidget(self._root_label, stretch=1)
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("filtrer…")
        self._filter_edit.setMaximumWidth(140)
        self._filter_edit.textChanged.connect(self._on_filter)
        bar.addWidget(self._filter_edit)
        reload_btn = QPushButton("⟳")
        reload_btn.setFixedWidth(28)
        reload_btn.setToolTip("Relire le dossier")
        reload_btn.clicked.connect(self._on_rescan)
        bar.addWidget(reload_btn)
        layout.addLayout(bar)

        # ── Navigateur ──
        self._fs_model = QFileSystemModel(self)
        self._fs_model.setNameFilters(["*.SimPl", "*.simpl"])
        self._fs_model.setNameFilterDisables(False)
        self._fs_model.setFilter(
            QDir.Filter.AllDirs | QDir.Filter.Files |
            QDir.Filter.NoDotAndDotDot)
        self._tree = QTreeView()
        self._tree.setModel(self._fs_model)
        self._tree.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self._tree.setSortingEnabled(True)
        self._tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        for col in (1, 2):
            self._tree.setColumnHidden(col, True)
        self._tree.setColumnWidth(0, 320)
        self._tree.doubleClicked.connect(self._on_tree_double_click)
        self._tree.selectionModel().selectionChanged.connect(
            self._on_selection_changed)

        # ── Actions ──
        actions = QHBoxLayout()
        actions.setSpacing(4)
        self._load_btn = QPushButton("① Chargement")
        self._load_btn.setToolTip(
            "Lit la sélection: brut, auteur, commentaire et outils "
            "employés (nom + référence, régime, avances)")
        self._load_btn.clicked.connect(self._on_load_selection)
        actions.addWidget(self._load_btn)
        self._import_btn = QPushButton("② → Opérations NeoDrive")
        self._import_btn.setToolTip(
            "Chaque fichier devient un onglet programme dont les "
            "sous-programmes rejoignent la liste d'opérations")
        self._import_btn.clicked.connect(self._on_import_selection)
        actions.addWidget(self._import_btn)
        self._batch_btn = QPushButton("③ Batch modif...")
        self._batch_btn.setToolTip(
            "Outil, régime, avances, brut, auteur, commentaire "
            "appliqués à toute la sélection")
        self._batch_btn.setStyleSheet(
            f"color: {COLORS['orange']}; font-weight: bold;")
        self._batch_btn.clicked.connect(self._on_batch_modify)
        actions.addWidget(self._batch_btn)
        self._check_btn = QPushButton("④ Contrôler")
        self._check_btn.setToolTip(
            "La structure de chaque programme de la sélection: séquence "
            "sans son bloc $$$, programme appelé absent, if/for sans "
            "fermeture, programme externe introuvable, paramètre mal "
            "orthographié — ce que la machine refuserait au chargement")
        self._check_btn.clicked.connect(self._on_check_selection)
        actions.addWidget(self._check_btn)
        actions.addStretch(1)
        self._sel_label = QLabel("")
        self._sel_label.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 11px;")
        actions.addWidget(self._sel_label)

        # ── Synthèse / code ──
        self._summary = QTextEdit()
        self._summary.setReadOnly(True)
        self._summary.setStyleSheet(
            f"QTextEdit {{ background: {COLORS['bg_deep']}; "
            f"color: {COLORS['text']}; "
            f"font-family: 'Cascadia Code', Consolas, monospace; "
            f"font-size: 11px; }}")
        self._summary.setPlainText(
            "Choisissez un dossier, sélectionnez des fichiers ou des "
            "dossiers, puis ① Chargement.")

        code_page = QWidget()
        cv = QVBoxLayout(code_page)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(4)
        cbar = QHBoxLayout()
        cbar.setSpacing(4)
        self._file_label = QLabel("(aucun fichier)")
        self._file_label.setStyleSheet(
            f"color: {COLORS['text_dim']}; font-size: 11px;")
        cbar.addWidget(self._file_label, stretch=1)
        self._history_btn = QPushButton("🕘 Historique")
        self._history_btn.setToolTip(
            "Patchs enregistrés dans ce fichier: date, auteur et "
            "nature de chaque modification")
        self._history_btn.clicked.connect(self._on_show_history)
        cbar.addWidget(self._history_btn)
        self._save_btn = QPushButton("💾 Enregistrer")
        self._save_btn.setToolTip(
            "Écrase le fichier (backup .bak créé avant)")
        self._save_btn.clicked.connect(self._on_save)
        cbar.addWidget(self._save_btn)
        save_as_btn = QPushButton("Enregistrer sous...")
        save_as_btn.clicked.connect(self._on_save_as)
        cbar.addWidget(save_as_btn)
        cv.addLayout(cbar)
        self.editor = CodeEditor()
        self.editor.setReadOnly(False)
        self._highlighter = SimPlSyntaxHighlighter(self.editor.document())
        self.editor.textChanged.connect(self._on_text_changed)
        cv.addWidget(self.editor, stretch=1)
        # la structure du code retouché (src.core.controle_simpl): ✓ / ⚠ /
        # ✗ à côté du nom du fichier, un clic mène à la ligne
        self.structure_btn = IndicateurStructure(self.editor)
        cbar.insertWidget(1, self.structure_btn)
        self.editor.textChanged.connect(self.structure_btn.planifier)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._summary, "Synthèse")
        self._tabs.addTab(code_page, "Code")

        lower = QWidget()
        lv = QVBoxLayout(lower)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(4)
        lv.addLayout(actions)
        lv.addWidget(self._tabs, stretch=1)

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self._tree)
        split.addWidget(lower)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)
        layout.addWidget(split, stretch=1)

        self._status = QLabel(
            "Sélectionnez des fichiers .SimPl à traiter")
        self._status.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 11px;")
        layout.addWidget(self._status)

        self._set_actions_enabled(False)
        self._save_btn.setEnabled(False)
        self._restore_last_root()

    def _set_actions_enabled(self, enabled: bool):
        for btn in (self._load_btn, self._import_btn, self._batch_btn,
                    self._check_btn):
            btn.setEnabled(enabled)

    # ── Navigateur ──

    def _settings_panel(self):
        """Le panneau qui détient les préférences applicatives."""
        return getattr(self.window(), 'params_panel', None)

    def _app_settings(self):
        return getattr(self._settings_panel(), '_app_settings', None)

    def _restore_last_root(self):
        """Rouvre le dernier dossier, sinon celui des programmes."""
        root = ""
        settings = self._app_settings()
        if settings is not None:
            root = str(settings.get('simpl_browse_dir', '')
                       or settings.get('default_programs_dir', '') or '')
        if not root or not os.path.isdir(root):
            from src.core.tool_library import get_base_dir
            for guess in ("Exemples SimPl", "programs"):
                full = os.path.join(get_base_dir(), guess)
                if os.path.isdir(full):
                    root = full
                    break
        if root and os.path.isdir(root):
            self.set_root(root)

    def set_root(self, folder: str):
        self._fs_model.setRootPath(folder)
        self._tree.setRootIndex(self._fs_model.index(folder))
        self._root_label.setText(folder)
        # sans sélection, les actions portent sur le dossier entier: elles
        # sont permises dès qu'il est choisi (sans le parcourir ici — un
        # dossier réseau ralentirait l'ouverture de l'application)
        self._set_actions_enabled(os.path.isdir(folder))
        settings = self._app_settings()
        if settings is not None:
            settings['simpl_browse_dir'] = folder
            save = getattr(self._settings_panel(),
                           'save_app_settings', None)
            if callable(save):
                save()

    def _on_choose_folder(self):
        start = self._fs_model.rootPath() or ""
        folder = QFileDialog.getExistingDirectory(
            self, "Dossier de programmes SimPl", start)
        if folder:
            self.set_root(folder)
            self._on_selection_changed()

    def _on_filter(self, text: str):
        text = text.strip()
        if text:
            self._fs_model.setNameFilters(
                [f"*{text}*.SimPl", f"*{text}*.simpl"])
        else:
            self._fs_model.setNameFilters(["*.SimPl", "*.simpl"])

    def _on_rescan(self):
        root = self._fs_model.rootPath()
        if root:
            # QFileSystemModel garde son cache: le forcer à relire
            self._fs_model.setRootPath("")
            self.set_root(root)

    def selected_paths(self):
        """Chemins sélectionnés (fichiers et dossiers bruts)."""
        rows = self._tree.selectionModel().selectedRows(0)
        return [self._fs_model.filePath(i) for i in rows]

    def selected_files(self):
        """Fichiers .SimPl de la sélection, dossiers développés.

        Sans sélection, c'est le dossier racine entier: l'action porte
        alors sur ce que l'utilisateur a sous les yeux."""
        paths = self.selected_paths()
        if not paths:
            root = self._fs_model.rootPath()
            paths = [root] if root else []
        return simpl_scan.collect_simpl_files(paths)

    def _on_selection_changed(self, *args):
        files = self.selected_files()
        n = len(files)
        self._set_actions_enabled(n > 0)
        if not self.selected_paths():
            self._sel_label.setText(
                f"{n} fichier(s) — dossier entier" if n else "")
        else:
            self._sel_label.setText(f"{n} fichier(s) sélectionné(s)")

    def peut_quitter_le_fichier(self, avant: str = "avant de continuer"
                                ) -> bool:
        """Le fichier affiché a des modifications non enregistrées:
        Enregistrer / Abandonner / Annuler. Rend True si on peut le
        quitter (enregistré ou abandonné). Sans cela, un double-clic
        sur un autre fichier, ou la fermeture de NeoDrive, perdait la
        correction en silence."""
        if not self._modified or not self._filepath:
            return True
        nom = os.path.basename(self._filepath)
        reponse = QMessageBox.question(
            self, "Batch édition",
            f"« {nom} » a des modifications non enregistrées.\n\n"
            f"Les enregistrer {avant} ?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if reponse == QMessageBox.StandardButton.Save:
            self._on_save()
            return not self._modified
        return reponse == QMessageBox.StandardButton.Discard

    def _meme_fichier(self, chemin: str) -> bool:
        """`chemin` est-il le fichier affiché (casse et séparateurs
        près: un lot rend ses chemins à sa façon) ?"""
        if not self._filepath or not chemin:
            return False
        return (os.path.normcase(os.path.abspath(chemin))
                == os.path.normcase(os.path.abspath(self._filepath)))

    def _on_tree_double_click(self, index):
        path = self._fs_model.filePath(index)
        if os.path.isfile(path):
            if self._meme_fichier(path):
                # le fichier déjà affiché: on y va, sans recharger
                self._tabs.setCurrentIndex(1)
                return
            if not self.peut_quitter_le_fichier(
                    "avant d'ouvrir un autre fichier"):
                return
            self.load_file(path)
            self._tabs.setCurrentIndex(1)

    # ── ① Chargement ──

    def _on_load_selection(self):
        files = self.selected_files()
        if not files:
            self._status.setText("Sélection vide")
            return
        from src.gui.progression import Progression
        with Progression(self, "Lecture des programmes",
                         f"{len(files)} fichier(s)…") as barre:
            scans = barre.executer(
                lambda b: simpl_scan.scan_files_avec(files, b))
        if barre.annule or scans is None:
            self._status.setText("Lecture annulée")
            return
        self._scans = simpl_scan.resolve_articles(
            scans, self._tool_library)
        self._summary.setPlainText(
            simpl_scan.summary_text(self._scans))
        self._tabs.setCurrentIndex(0)
        if len(files) == 1:
            self.load_file(files[0])
        n_tools = len(simpl_scan.all_tools(self._scans))
        self._status.setText(
            f"✓ {len(files)} fichier(s) lus — {n_tools} outil(s) "
            f"distinct(s)")

    # ── ② Import comme opérations ──

    def _on_import_selection(self):
        files = self.selected_files()
        if not files:
            self._status.setText("Sélection vide")
            return
        if len(files) > 8:
            reply = QMessageBox.question(
                self, "Import",
                f"{len(files)} fichiers vont ouvrir autant d'onglets "
                f"programme. Continuer ?",
                QMessageBox.StandardButton.Yes |
                QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return
        self.import_files(files)
        self._status.setText(
            f"✓ {len(files)} fichier(s) importés comme opérations")

    def import_files(self, paths):
        """Charge des SimPl comme opérations (un onglet par fichier).

        Point d'entrée utilisable sans passer par la sélection de
        l'arbre (menu, glisser-déposer, tests)."""
        files = simpl_scan.collect_simpl_files(paths)
        for path in files:
            self.blocks_available.emit(path)
        return files

    # ── ③ Batch ──

    def _on_batch_modify(self):
        files = self.selected_files()
        if not files:
            self._status.setText("Sélection vide")
            return
        scans = self._scans
        if not scans or {s['path'] for s in scans} != set(files):
            # La sélection a bougé depuis le dernier ① : relire, sinon
            # les combos proposeraient les outils d'autres fichiers
            from src.gui.progression import Progression
            with Progression(self, "Lecture des programmes",
                             f"{len(files)} fichier(s)…") as barre:
                lus = barre.executer(
                    lambda b: simpl_scan.scan_files_avec(files, b))
            if barre.annule or lus is None:
                self._status.setText("Lecture annulée")
                return
            scans = simpl_scan.resolve_articles(lus,
                                                self._tool_library)
            self._scans = scans
        dlg = BatchModifyDialog(scans, self._tool_library, len(files),
                                self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        changes = dlg.changes()
        if not changes:
            self._status.setText("Aucune modification demandée")
            return
        from src.gui.progression import Progression
        with Progression(self, "Modification par lot",
                         f"{len(files)} fichier(s)…") as barre:
            report = barre.executer(lambda b: simpl_scan.apply_to_files(
                files, changes, tool_library=self._tool_library,
                author=self._patch_author(), progression=b))
        if report is None:
            report = []
        if barre.annule:
            self._status.setText(
                f"Lot arrêté: {len(report)} fichier(s) traité(s) "
                f"sur {len(files)}")
        self._show_report(report)

    def _show_report(self, report):
        changed = [r for r in report if r['done'] and not r['error']]
        errors = [r for r in report if r['error']]
        lines = [f"{len(changed)} fichier(s) modifié(s) sur "
                 f"{len(report)}", ""]
        for entry in report:
            if entry['error']:
                lines.append(f"⚠ {entry['filename']} : {entry['error']}")
            elif entry['done']:
                lines.append(f"✓ {entry['filename']} — "
                             + ", ".join(entry['done']))
            else:
                lines.append(f"·  {entry['filename']} — inchangé")
        self._summary.setPlainText("\n".join(lines))
        self._tabs.setCurrentIndex(0)
        self._status.setText(
            f"✓ {len(changed)} fichier(s) modifié(s)"
            + (f", {len(errors)} erreur(s)" if errors else ""))
        # Le fichier affiché a pu changer sur le disque
        if self._filepath and any(
                self._meme_fichier(r['path']) for r in changed):
            if self._modified:
                # le lot a écrit le disque SANS la correction à
                # l'écran: recharger la perdait en silence
                nom = os.path.basename(self._filepath)
                reponse = QMessageBox.question(
                    self, "Batch édition",
                    f"Le lot vient de modifier « {nom} » sur le disque, "
                    f"mais l'onglet Code a des modifications non "
                    f"enregistrées.\n\nRecharger le fichier du disque "
                    f"(les modifications à l'écran sont perdues) ?",
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No)
                if reponse != QMessageBox.StandardButton.Yes:
                    self._status.setText(
                        f"{nom}: modifications à l'écran gardées — le "
                        f"disque porte la version du lot")
                    return
            self.load_file(self._filepath)

    # ── ④ Contrôle de structure ──

    def _on_check_selection(self):
        """La structure de chaque programme de la sélection (le dossier
        entier sans sélection), en barre d'état avec Annuler; le compte
        rendu dans la Synthèse."""
        from src.core import controle_simpl
        files = self.selected_files()
        if not files:
            self._status.setText("Sélection vide")
            return
        from src.gui.progression import Progression
        with Progression(self, "Contrôle de structure",
                         f"{len(files)} fichier(s)…") as barre:
            resultats = barre.executer(
                lambda b: controle_simpl.controler_fichiers(files, b))
        if barre.annule or resultats is None:
            self._status.setText("Contrôle annulé")
            return
        self._summary.setPlainText(controle_simpl.rapport(resultats))
        self._tabs.setCurrentIndex(0)
        n_err = sum(1 for _p, c in resultats
                    if c and controle_simpl.erreurs(c))
        self._status.setText(
            f"✗ {n_err} programme(s) sur {len(resultats)} avec des "
            f"erreurs de structure" if n_err else
            f"✓ {len(resultats)} programme(s) contrôlé(s), aucune erreur "
            f"de structure")

    # ── Fichier affiché ──

    def load_file(self, filepath: str):
        """Affiche un .SimPl dans l'onglet Code."""
        try:
            with open(filepath, 'r', encoding='utf-8',
                      errors='replace') as f:
                code = f.read()
        except OSError as e:
            QMessageBox.warning(
                self, "Édition SimPl",
                f"Impossible d'ouvrir:\n{e}")
            return
        self._filepath = filepath
        self._texte_disque = code
        self.editor.blockSignals(True)
        self.editor.setPlainText(code)
        self.editor.blockSignals(False)
        self.structure_btn.planifier()
        self._modified = False
        self._save_btn.setEnabled(True)
        self._update_title()
        self._status.setText(
            f"{os.path.basename(filepath)} — "
            f"{code.count(chr(10)) + 1} lignes")

    def _on_save(self):
        if not self._filepath:
            self._on_save_as()
            return
        # ce que la machine refuserait au chargement: on le dit avant
        # d'écraser le fichier (les avertissements restent à l'indicateur)
        if not confirmer_structure(self, self.editor.toPlainText(),
                                   "Enregistrer", avertissements=False):
            return
        try:
            # backup avant écrasement, puis remplacement d'un coup
            from src.core.fichiers_surs import ecrire_texte_sur
            texte = self._texte_a_ecrire()
            ecrire_texte_sur(self._filepath, texte, garder_bak=True)
            self._texte_disque = texte
            self._modified = False
            self._update_title()
            self._status.setText(
                f"Enregistré (backup: "
                f"{os.path.basename(self._filepath)}.bak)")
        except OSError as e:
            QMessageBox.warning(
                self, "Édition SimPl",
                f"Impossible d'enregistrer:\n{e}")

    def _on_save_as(self):
        if not confirmer_structure(self, self.editor.toPlainText(),
                                   "Enregistrer", avertissements=False):
            return
        start = self._filepath or self._fs_model.rootPath() or ""
        fp, _ = QFileDialog.getSaveFileName(
            self, "Enregistrer le programme SimPl", start,
            "Fichiers SimPl (*.SimPl)")
        if not fp:
            return
        if not fp.lower().endswith('.simpl'):
            fp += '.SimPl'
        try:
            from src.core.fichiers_surs import ecrire_texte_sur
            texte = self._texte_a_ecrire()
            ecrire_texte_sur(fp, texte, garder_bak=True)
            self._filepath = fp
            self._texte_disque = texte
            self._modified = False
            self._save_btn.setEnabled(True)
            self._update_title()
            self._status.setText(f"Enregistré: {os.path.basename(fp)}")
        except OSError as e:
            QMessageBox.warning(
                self, "Édition SimPl",
                f"Impossible d'enregistrer:\n{e}")

    def _texte_a_ecrire(self) -> str:
        """Le texte de l'éditeur; un fichier NeoDrive corrigé voit son
        NDMETA scellé (rouvert, il se lira tel qu'il est)."""
        from src.io.simpl_importer import sceller_ndmeta
        return sceller_ndmeta(self._texte_disque,
                              self.editor.toPlainText())

    def _on_text_changed(self):
        if not self._modified:
            self._modified = True
            self._update_title()

    def _update_title(self):
        name = os.path.basename(self._filepath) if self._filepath \
            else "(aucun fichier)"
        self._file_label.setText(("● " if self._modified else "") + name)

    def _patch_author(self) -> str:
        """Auteur des patchs: celui du programme NeoDrive courant."""
        win = self.window()
        prog = getattr(win, 'program', None)
        if prog is not None:
            return str(getattr(prog.settings, 'author', '') or '')
        return ""

    def _on_show_history(self):
        """Affiche l'historique des patchs du fichier affiché."""
        entries = simpl_batch.parse_history(self.editor.toPlainText())
        dlg = QDialog(self)
        dlg.setWindowTitle("Historique des patchs")
        dlg.resize(620, 420)
        v = QVBoxLayout(dlg)
        view = QTextEdit()
        view.setReadOnly(True)
        view.setStyleSheet(
            f"QTextEdit {{ background: {COLORS['bg_deep']}; "
            f"color: {COLORS['text']}; "
            f"font-family: 'Cascadia Code', Consolas, monospace; "
            f"font-size: 11px; }}")
        if not entries:
            view.setPlainText(
                "Aucun patch enregistré dans ce fichier.\n\n"
                "Chaque modification en lot y ajoute une ligne "
                "horodatée, en pied de programme.")
        else:
            lines = [f"{len(entries)} patch(s) enregistré(s)", ""]
            for e in entries:
                who = f" — {e['author']}" if e['author'] else ""
                lines.append(f"{e['stamp']}{who}")
                lines.append(f"    {e['message']}")
            view.setPlainText("\n".join(lines))
        v.addWidget(view)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(dlg.reject)
        btns.accepted.connect(dlg.accept)
        v.addWidget(btns)
        dlg.exec()
