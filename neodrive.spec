# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec pour NeoDrive
#
# MODÈLE DE DISTRIBUTION — build onefile.
# L'application lit ses ressources dans le dossier data/ SITUÉ À CÔTÉ
# de l'exe (get_base_dir() renvoie dirname(sys.executable) une fois
# gelé), PAS dans les données embarquées, qui atterriraient dans le
# dossier temporaire _MEIPASS. Ce spec copie donc lui-même data/ dans
# dist/ après la compilation: un dist/ sans data/ démarre avec une
# bibliothèque d'outils VIDE, sans le dire.

import os
import shutil

block_cipher = None
base_dir = os.path.abspath('.')

# ──────────────────────────────────────────────────────────────
#  Ressources que l'application lit au démarrage
# ──────────────────────────────────────────────────────────────
# Obligatoires: leur absence change le comportement sans erreur
# visible (outils par défaut au lieu des vôtres, fenêtre sans icône).
# Ce sont les ressources GÉNÉRIQUES de la version libre (round 32):
# les données de l'atelier (outils, réglages, sous-programmes…) n'entrent
# pas dans l'exe — tools/publier.py les met dans leur propre archive.
DATA_REQUIS = [
    'default_params.json',     # valeurs par défaut des formulaires
    'materials.json',          # matières et multiplicateurs
    'shortcuts.json',          # raccourcis clavier
    'neodrive.ico',            # icône de la fenêtre
    'NeoDriveLoad.png',        # écran de démarrage
    'NeoDrive.png',            # « À propos »
]
# Le catalogue DATRON n'est pas livré (données de DATRON AG): l'onglet
# Catalogue le constitue depuis le webshop (round 33).
# Facultatifs: créés à l'usage, copiés s'ils existent
DATA_OPTIONNELS = [
    # bibliothèque d'outils de l'atelier: absente, NeoDrive démarre avec
    # la bibliothèque par défaut (et l'écrit)
    'tools.json',
    'app_settings.json',
    'favorites.json',
    'workpiece_templates.json',
    'gammes.json',             # modèles de gamme
    # les gammes livrées par l'atelier (lues, jamais modifiées par
    # NeoDrive): données de l'atelier, pas de la version libre
    'gammes_atelier.json',
    'ebavurage.json',          # modèles d'ébavurage
    'icon.ico',
    # le catalogue DATRON constitué sur le poste (onglet Catalogue)
    'catalogue_datron.json',
    # avances lues dans le guide DATRON de l'utilisateur (onglet
    # Catalogue, « Guide PDF… »): à usage local
    'coupe_datron_guide.json',
    'catalogue_datron_maj.json',  # cotes lues sur datron.de
    'brut_templates.json',     # bruts types (Paramètres, Brut)
]
DATA_DOSSIERS = ['templates']
# Ce que l'utilisateur ÉDITE depuis l'exe (outils, réglages, favoris,
# défauts…): la construction ne l'écrase jamais s'il existe déjà à
# côté de l'exe. Chaque reconstruction recopiait par-dessus le
# app_settings.json du dépôt — pollué par la suite de tests: fenêtre
# de 640 × 480 non maximisée, programmes récents dans %TEMP%.
DATA_UTILISATEUR = [
    'tools.json', 'default_params.json', 'materials.json',
    'shortcuts.json', 'app_settings.json', 'favorites.json',
    'workpiece_templates.json', 'gammes.json', 'ebavurage.json',
    'coupe_datron_guide.json',
    'catalogue_datron.json',      # constitué depuis le webshop
    'catalogue_datron_maj.json',  # cotes lues sur datron.de
    'brut_templates.json',
]

manquants = [f for f in DATA_REQUIS
             if not os.path.isfile(os.path.join(base_dir, 'data', f))]
if manquants:
    raise SystemExit(
        "ERREUR: ressources absentes de data/ — la distribution "
        "serait incomplète: " + ", ".join(manquants))

# Copie de secours DANS l'exe: si data/ manque à côté de l'exe,
# main.py peut la restaurer depuis _MEIPASS (voir _restaurer_data).
datas_list = [(f'data/{nom}', 'data')
              for nom in DATA_REQUIS]
# le plugin qui fait de NeoDrive le post-processeur de VectorDrive
# (Paramètres → « Installer le post-processeur dans VectorDrive »)
datas_list.append(('integrations/vectordrive/neodrive_post/__init__.py',
                   'integrations/vectordrive/neodrive_post'))

# Icône de l'exécutable (l'icône de fenêtre vient de data/neodrive.ico)
icon_path = os.path.join(base_dir, 'neodrive.ico')
if not os.path.isfile(icon_path):
    raise SystemExit(
        f"ERREUR: icône introuvable: {icon_path} — "
        "l'exe serait compilé sans icône.")
icon_param = icon_path

# ──────────────────────────────────────────────────────────────
#  Modules chargés par le registre d'opérations
# ──────────────────────────────────────────────────────────────
# src/operations/__init__.py les importe explicitement, donc l'analyse
# statique les trouve. La liste reste ici comme FILET: elle est
# vérifiée par tests/test_neodrive.py (TestSpecDeDistribution), qui
# échoue dès qu'une opération nouvelle n'y figure pas.
OPERATIONS = [
    'appel_outil', 'appel_programme', 'bloc_simpl', 'bpm',
    'compteur_pieces', 'decalage_origine', 'decoupe_cercle',
    'decoupe_rectangle', 'dialogue_operateur', 'fonction_custom',
    'gamme_gravure', 'ebavurage',
    'gravure_2d5', 'gravure_texte', 'helice', 'import_programme',
    'mesure_orientation', 'miroir', 'palpage_memorise',
    'palpage_rectangle', 'palpage_symetrie', 'palpage_z',
    'palpage_arete', 'palpage_u', 'table_vide', 'repere_local',
    'parametres_operateur', 'percage_foret', 'percage_fraise',
    'poche_rectangle', 'prechauffage_broche', 'retablir_miroir',
    'retournement_piece',
    'sequence_datron', 'surfacage_cercle', 'surfacage_rectangle',
    'taraudage', 'taraudage_brut', 'texte_grave', 'trace',
    # fonctions du manuel SimPL 3.1.1 (octobre 2026)
    'poche_cercle', 'rotation_repere', 'palpage_coin',
    'message_operateur', 'mesure_outil', 'filetage_special',
    'mouvement', 'commandes_manuel',
    # les lignes qu'un Main importé exécute lui-même (octobre 2026)
    'lignes_main',
]

# ──────────────────────────────────────────────
#  Exe allégé (round 28 — audit du 8 novembre, point 18)
# ──────────────────────────────────────────────
# PyInstaller embarque tout ce qu'un `import` nomme, même au fond d'un
# `try` jamais pris, et tout ce que les greffons de Qt savent charger:
# l'exe pesait 134 Mo — 292 Mo décompressés à CHAQUE lancement — dont
# un tiers ne sert jamais à NeoDrive.
#
# EXCLUS: paquets Python qu'aucun chemin de NeoDrive ne charge. C'est
# mesuré, pas supposé: `python tools/comme_l_exe.py main.py
# --autocontrole` refuse ces imports comme le fait l'exe, et un test le
# rejoue à chaque suite (tests/test_exe_allege.py). Ne PAS y ajouter
# numpy.f2py (scipy fait « from numpy import * », qui le charge) ni
# cryptography (les PDF protégés — le guide de coupe DATRON l'est).
EXCLUS = [
    'PyQt5', 'PyQt6',
    # tracés scientifiques: nommés par ezdxf et par les aides au tracé
    # de scipy, jamais appelés
    'matplotlib', 'mpl_toolkits', 'kiwisolver', 'dateutil', 'certifi',
    # Pillow: pypdf ne s'en sert que pour extraire les photos d'un PDF;
    # NeoDrive en lit les tracés et le texte
    'PIL',
    # XML rapide et HTML: fontTools retombe sur xml.etree
    'lxml', 'bs4', 'soupsieve',
    # fabrication de paquets Python
    'setuptools', 'pkg_resources', '_distutils_hack',
    # schémas de grammaire de pyparsing (ezdxf)
    'jinja2', 'markupsafe',
    # scipy: NeoDrive n'appelle que optimize.least_squares, spatial
    # (cKDTree, Voronoi) et ndimage, qui ne chargent pas ceux-ci
    'scipy.stats', 'scipy.integrate', 'scipy.interpolate',
    # WinRT: servait à l'OCR de TypeEdit, retiré en 0.33.2 — le poste de
    # build qui l'a installé ne doit plus l'embarquer
    'winrt',
]

# RETIRES: DLL, greffons et données de Qt ramassés d'office (motifs
# fnmatch sur le chemin dans l'exe, sans casse).
RETIRES = [
    # OpenGL logiciel, 20 Mo: NeoDrive dessine tout au QPainter
    'PySide6/opengl32sw.dll',
    # Qt Quick / QML, clavier virtuel et lecteur PDF de Qt: tirés par
    # les trois greffons qui suivent, jamais par une application Widgets
    # (l'export PDF passe par QPdfWriter, de QtGui; l'import par pypdf)
    'PySide6/Qt6Quick.dll', 'PySide6/Qt6Qml.dll',
    'PySide6/Qt6QmlModels.dll', 'PySide6/Qt6QmlMeta.dll',
    'PySide6/Qt6QmlWorkerScript.dll', 'PySide6/Qt6VirtualKeyboard.dll',
    'PySide6/Qt6OpenGL.dll', 'PySide6/Qt6Pdf.dll',
    'PySide6/plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll',
    'PySide6/plugins/imageformats/qpdf.dll',
    'PySide6/plugins/platforms/qdirect2d.dll',
    # TLS de Qt par OpenSSL, et les DLL OpenSSL ramassées dans le PATH
    # du poste de build (celles de Git !): le seul réseau Qt de NeoDrive
    # est la prise locale de l'instance unique; le https passe par
    # Python, qui a ses propres libssl-3.dll / libcrypto-3.dll
    'PySide6/plugins/tls/qopensslbackend.dll',
    'libcrypto-3-x64.dll', 'libssl-3-x64.dll',
    # traductions de Qt: NeoDrive n'installe aucun QTranslator
    'PySide6/translations/*',
]


def _exclu(module):
    """`module` est-il l'un des paquets de EXCLUS, ou dans l'un d'eux ?"""
    return any(module == e or module.startswith(e + '.') for e in EXCLUS)


def _retire(nom):
    """Cette entrée de l'exe (chemin de destination) doit-elle partir ?"""
    import fnmatch
    n = nom.replace('\\', '/')
    if any(fnmatch.fnmatchcase(n.lower(), m.lower()) for m in RETIRES):
        return True
    # ce qu'un greffon PyInstaller ramasserait d'un paquet exclu:
    # « matplotlib/mpl-data/… », « PIL/_avif.cp313-win_amd64.pyd »
    return _exclu(n.split('.')[0].replace('/', '.'))


def _alleger(entrees):
    """(gardées, retirées) d'une liste d'entrées (nom, chemin, type)."""
    gardees = [e for e in entrees if not _retire(e[0])]
    retirees = [e for e in entrees if _retire(e[0])]
    return gardees, retirees


def _orphelins(gardees, retirees, imports_de):
    """Les binaires GARDÉS qui importent une DLL RETIRÉE, avec la DLL:
    un exe livré ainsi ne démarre pas. `imports_de(chemin)` rend les
    noms de DLL qu'un binaire importe."""
    partis = {os.path.basename(e[0].replace('\\', '/')).lower()
              for e in retirees}
    restes = {os.path.basename(e[0].replace('\\', '/')).lower()
              for e in gardees}
    partis -= restes
    orphelins = []
    for nom, chemin, _type in gardees:
        if not str(chemin).lower().endswith(('.dll', '.pyd')):
            continue
        for dll in sorted({d.lower() for d in imports_de(chemin)} & partis):
            orphelins.append((nom, dll))
    return orphelins


def _imports_pe(chemin):
    """Les DLL qu'un binaire Windows importe (pefile vient avec
    PyInstaller)."""
    import pefile
    try:
        pe = pefile.PE(chemin, fast_load=True)
        pe.parse_data_directories(directories=[
            pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT'],
            pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT']])
    except Exception:
        return []
    noms = []
    for attribut in ('DIRECTORY_ENTRY_IMPORT',
                     'DIRECTORY_ENTRY_DELAY_IMPORT'):
        for e in getattr(pe, attribut, None) or []:
            noms.append(e.dll.decode('ascii', 'replace'))
    pe.close()
    return noms


a = Analysis(
    ['main.py'],
    pathex=[base_dir],
    binaries=[],
    datas=datas_list,
    hiddenimports=[
        'ezdxf',
        'ezdxf.entities',
        'ezdxf.addons',
        'ezdxf.recover',
        'PySide6.QtWidgets',
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtPrintSupport',    # export PDF du canvas
        'PySide6.QtSvg',             # icônes et symboles
        'PySide6.QtNetwork',         # instance unique (prise locale)
        'shiboken6',                 # polygones remplis depuis numpy
    ] + [f'src.operations.{nom}' for nom in OPERATIONS] + [
        'src.core.circle_detection',
        'src.core.default_params',
        'src.core.vcarve',
        'src.core.gamme',
        'src.core.texte',
        'src.core.donnees_utilisateur',
        'src.core.repetition',
        'src.operations.ebavurage_modeles',
        'src.core.simpl_syntaxe',        # syntaxe des commandes du manuel
        'shapely',                   # gravure 2,5D: erosions
        'shapely.geometry',
        'shapely.ops',
        'scipy',                     # gravure 2,5D: axe median
        'scipy.spatial',             # Voronoi
        'scipy.spatial._qhull',
        'scipy.ndimage',             # usinage 3D: maxima glissants
        'contourpy',                 # usinage 3D: courbes de niveau
        'numpy',
        'src.core.materials',
        'src.core.matiere',
        'src.core.fichiers_surs',
        'src.core.time_estimator',
        'src.core.undo_commands',
        'src.gui.dxf.canvas_undo',
        'src.core.sim3d',
        'src.gui.vue3d',
        'src.io.vecteur',
        'src.io.vecteur.dxfimport',
        'src.io.vecteur.vecimport',
        'src.io.vecteur.svgread',
        'src.io.vecteur.stepread',
        'src.io.vecteur.step3d',
        'src.gui.canvas3d',
        'src.gui.dxf.canvas_volume',
        'src.core.simpl_commandes',
        'src.core.sim_cycles',
        'src.core.enlevement',
        'src.core.police_fil',
        'src.core.usinage_faces',
        'src.core.usinage3d',
        'src.gui.dialogs.usinage3d_dialog',
        'src.gui.dialogs.mini_formulaire',
        'src.io.stl',
        'src.core.tenue',
        'src.core.plaques',
        'src.core.scene_phases',
        'src.operations.depuis_selection',
        'src.gui.dialogs.plaques_dialog',
        'src.core.dessin_outil',
        'src.gui.dialogs.fiche_outil',
        'src.gui.dxf.barre_imports',
        'src.core.images_datron',
        'src.core.fiches_outils',
        'src.core.miroirs_filets',
        'src.gui.fenetres',
        'src.core.serrages',
        'src.gui.dialogs.serrages_dialog',
        'src.core.machine',
        'src.core.collisions',
        'src.gui.dialogs.machine_dialog',
        'src.core.usinage_tslot',
        'src.gui.dialogs.vis_dialog',
        'src.io.vecteur.trace_image',   # VectorCraft (MIT): image tracée
        'src.core.retouche',            # CADCraft/VectorCraft (MIT)
        'src.core.accrochage',          # CADCraft (MIT): accrochages
        'src.core.arcs',                # arcs retrouvés (DXF, Arc)
        'src.io.vecteur.metafile',      # EMF / WMF (VectorCraft, MIT)
        'src.core.texte_courbe',        # texte sur un arc, un tracé
        'src.core.formes',              # reconnaissance de formes
        'src.core.cotation',            # cotes du canvas
        'src.core.affichage',           # transparence, 1 ligne sur N
        'src.core.contraintes',         # dessin paramétrique
        'src.gui.barre_outils',         # barre unique 2D / 3D
        'src.gui.icones_barre',         # icônes des barres des canvas
        'src.gui.icones_fenetres',      # icônes des fenêtres d'onglets
        'src.gui.dialogs.reglages_png', # réglages du PNG d'export
        'src.io.vectordrive_job',       # travaux de VectorDrive (.ndjob)
        'src.integrations.vectordrive_plugin',  # son installation
        'src.io.vecteur.maillage',      # STL, 3DXML
        'src.io.vecteur.iges',          # IGES
        'src.io.vecteur.dwg',           # DWG par convertisseur
        'scipy.optimize',               # solveur des contraintes
        'src.gui.dialogs.trace_image_dialog',
        'ssl',
        'src.core.catalogue_datron',
        'src.core.coupe_datron',
        'src.gui.panels.catalogue_panel',
        'src.io.vecteur.geometry',
        'src.io.vecteur.textvec',
        'src.io.vecteur.fontmap',
        'fontTools',
        'fontTools.ttLib',
        'fontTools.pens.basePen',
        'pypdf',                     # import PDF / AI vectoriel

        'src.io.simpl_importer',
        'src.io.simpl_batch',
        'src.io.simpl_scan',
        'src.io.program_serializer',
        'src.gui.icons',
        'src.gui.progression',
        'src.operations.gamme_postes',
        'src.operations.gamme_modeles',
        'src.gui.dialogs.police_dialog',
        'src.integrations.windows_shell',
        'src.integrations.instance_unique',
        'src.gui.panels.circle_ops_panel',
        'src.gui.panels.code_editor_panel',
        'src.gui.panels.dxf_editor_panel',
        'src.gui.panels.operations_panel',
        'src.gui.panels.simpl_edit_panel',
        'src.gui.panels.symbol_browser_panel',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUS,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# L'allègement: ce que l'analyse a ramassé malgré tout, puis la garde —
# le build s'arrête plutôt que de livrer un exe qui ne démarre pas.
a.pure = [e for e in a.pure if not _exclu(e[0])]
a.binaries, _binaires_retires = _alleger(a.binaries)
a.datas, _donnees_retirees = _alleger(a.datas)
_orphelins_trouves = _orphelins(a.binaries, _binaires_retires, _imports_pe)
if _orphelins_trouves:
    raise SystemExit(
        "[NeoDrive] exe allégé: des binaires gardés importent une DLL "
        "retirée (RETIRES de neodrive.spec):\n" + "\n".join(
            f"    {nom} -> {dll}" for nom, dll in _orphelins_trouves))


def _poids(entrees):
    total = 0
    for _nom, _chemin, _type in entrees:
        try:
            total += os.path.getsize(_chemin)
        except OSError:
            pass
    return total / 2 ** 20


print(f"[NeoDrive] exe allégé: {len(_binaires_retires)} binaires "
      f"({_poids(_binaires_retires):.1f} Mo) et {len(_donnees_retirees)} "
      f"données ({_poids(_donnees_retirees):.1f} Mo) retirés; restent "
      f"{_poids(a.binaries) + _poids(a.datas):.1f} Mo de binaires et de "
      f"données, {len(a.pure)} modules Python")

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='NeoDrive',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_param,
)

# ──────────────────────────────────────────────────────────────
#  Après la compilation: compléter dist/ avec les ressources
# ──────────────────────────────────────────────────────────────
# le dossier de sortie: celui de --distpath (PyInstaller le donne au
# spec), dist/ sinon — construire à côté n'écrit rien près de l'exe
# en service
_dist = DISTPATH if 'DISTPATH' in globals() else os.path.join(base_dir, 'dist')
dist_data = os.path.join(_dist, 'data')
os.makedirs(dist_data, exist_ok=True)
_copies = 0
_gardes = 0
for nom in DATA_REQUIS + DATA_OPTIONNELS:
    source = os.path.join(base_dir, 'data', nom)
    cible = os.path.join(dist_data, nom)
    if not os.path.isfile(source):
        continue
    if nom in DATA_UTILISATEUR and os.path.isfile(cible):
        _gardes += 1               # ses données, pas les nôtres
        continue
    shutil.copy2(source, cible)
    _copies += 1
for nom in DATA_DOSSIERS:
    source = os.path.join(base_dir, 'data', nom)
    if os.path.isdir(source):
        shutil.copytree(source, os.path.join(dist_data, nom),
                        dirs_exist_ok=True)
# programs/ accueille la session et les sous-programmes .nds
os.makedirs(os.path.join(_dist, 'programs'), exist_ok=True)


def _completer(source, cible, ignorer_dossiers=(), ignorer_fins=()):
    """Copie ce qui MANQUE dans `cible`: les fichiers de l'atelier
    (sous-programmes .nds, programmes outils) voyagent avec l'exe,
    et ceux que l'utilisateur a déjà à côté du sien restent les
    siens."""
    n = 0
    if not os.path.isdir(source):
        return n
    for racine, dossiers, fichiers in os.walk(source):
        dossiers[:] = [d for d in dossiers
                       if d not in ignorer_dossiers
                       and not d.startswith('.')]
        relatif = os.path.relpath(racine, source)
        for nom in fichiers:
            if nom.startswith('.') or nom.endswith(ignorer_fins):
                continue
            arrivee = os.path.join(cible, relatif, nom)
            if os.path.exists(arrivee):
                continue
            os.makedirs(os.path.dirname(arrivee), exist_ok=True)
            shutil.copy2(os.path.join(racine, nom), arrivee)
            n += 1
    return n


# les sous-programmes de l'atelier (.nds)
_nds = _completer(os.path.join(base_dir, 'programs'),
                  os.path.join(_dist, 'programs'),
                  ignorer_dossiers=('onglets_fermes',),
                  ignorer_fins=('.bak', '.bak2', '.json', '.tmp'))
# les programmes outils de l'atelier et leur LISEZ-MOI;
# « Vers NeoDrive » reste vide, TauDrive (220 Mo) n'est pas un
# programme outil de l'atelier
_outils = _completer(os.path.join(base_dir, 'Programmes outils'),
                     os.path.join(_dist, 'Programmes outils'),
                     ignorer_dossiers=('build', 'dist', '__pycache__',
                                       'Vers NeoDrive', 'exports',
                                       'TauDrive'),
                     ignorer_fins=('.pyc', '.log', '.bak', '.spec'))
os.makedirs(os.path.join(_dist, 'Programmes outils',
                         'Vers NeoDrive'), exist_ok=True)
# les pièces STEP de l'atelier: elles voyagent avec
# l'exe; celles déjà posées à côté de lui restent les leurs
_step = _completer(os.path.join(base_dir, 'Step'),
                   os.path.join(_dist, 'Step'))
# les plaques de reprise de l'atelier (motifs de trous M4): elles
# voyagent avec l'exe; le dossier existe toujours, l'éditeur y écrit
_plaques = _completer(os.path.join(base_dir, 'Plaques de reprise'),
                      os.path.join(_dist, 'Plaques de reprise'))
os.makedirs(os.path.join(_dist, 'Plaques de reprise'),
            exist_ok=True)
# les étaux autocentrés et mandrins de l'atelier (et leurs STEP)
_serrages = _completer(os.path.join(base_dir, 'Étaux et mandrins'),
                       os.path.join(_dist, 'Étaux et mandrins'))
os.makedirs(os.path.join(_dist, 'Étaux et mandrins'),
            exist_ok=True)
# la machine de l'atelier (machine.json, ses STEP)
_machine = _completer(os.path.join(base_dir, 'Machine'),
                      os.path.join(_dist, 'Machine'))
# la licence de NeoDrive (MIT ou Apache-2.0, au choix) et les avis du
# code repris (VectorCraft, CADCraft: MIT)
for _texte in ('LICENSE.txt', 'LICENSE-MIT.txt', 'LICENSE-APACHE.txt',
               'THIRD_PARTY_NOTICES.md'):
    shutil.copy2(os.path.join(base_dir, _texte),
                 os.path.join(_dist, _texte))
# les licences de ce que l'exe embarque (Python, Qt sous LGPL-3.0,
# numpy…): dist/licences/, un dossier par composant + LISEZ-MOI.txt;
# s'il manque un texte, l'autocontrôle de l'exe refuse la publication
import sys as _sys
_sys.path.insert(0, os.path.join(base_dir, 'tools'))
import licences_tierces as _licences
_bilan = _licences.poser(
    _dist, globals().get('workpath',
                         os.path.join(base_dir, 'build', 'neodrive')),
    base_dir)
print(f"[NeoDrive] licences/: {len(_bilan.composants)} composant(s)"
      + ("" if _bilan.complet else
         f" — {_licences.A_COMPLETER}: "
         + ", ".join(_bilan.sans_texte
                     + [n for n, _ in _bilan.orphelins])))
# le manuel SimPL DATRON (F1 dans l'éditeur l'ouvre à la page de la
# commande): à côté de l'exe s'il est dans le dépôt — hors git, c'est
# un document DATRON; tools/publier.py le range avec l'atelier
_manuel = 'DATRON_SimPL_Programmierhandbuch_3.1.1_EN.pdf'
if (os.path.isfile(os.path.join(base_dir, _manuel))
        and not os.path.isfile(os.path.join(_dist, _manuel))):
    shutil.copy2(os.path.join(base_dir, _manuel),
                 os.path.join(_dist, _manuel))
    print(f"[NeoDrive] manuel SimPL copié à côté de l'exe")
print(f"[NeoDrive] dist/data: {_copies} fichier(s) copié(s), "
      f"{_gardes} de l'utilisateur gardé(s) — l'exe et data/ voyagent "
      f"ENSEMBLE. programs/: {_nds} sous-programme(s) ajouté(s); "
      f"Programmes outils/: {_outils} fichier(s) ajouté(s); "
      f"Step/: {_step} pièce(s) ajoutée(s); "
      f"Plaques de reprise/: {_plaques} plaque(s) ajoutée(s).")
