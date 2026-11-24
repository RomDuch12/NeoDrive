"""
Système de thèmes pour NeoDrive.
Supporte mode clair, 5 thèmes couleurs pro, attention et contraste.
"""

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPalette, QColor
import os

from PySide6.QtCore import QSettings


def reglages_qt() -> QSettings:
    """Les réglages Qt de NeoDrive: thème, derniers dossiers.

    En format natif, c'est le REGISTRE de l'utilisateur.
    NEODRIVE_QSETTINGS_DIR les détourne vers un fichier .ini: la
    suite de tests y avait laissé un dossier %TEMP% comme dernier
    dossier de programmes. (Le constructeur à deux arguments ignore
    `QSettings.setDefaultFormat` dans PySide6: il faut passer par
    ici.)"""
    dossier = os.environ.get('NEODRIVE_QSETTINGS_DIR')
    if dossier:
        QSettings.setPath(QSettings.Format.IniFormat,
                          QSettings.Scope.UserScope, dossier)
        return QSettings(QSettings.Format.IniFormat,
                         QSettings.Scope.UserScope, "NeoDrive", "NeoDrive")
    return QSettings("NeoDrive", "NeoDrive")

# ──── Palettes de couleurs ────────────────────────────────────────────

THEMES = {
    # ── Thème par défaut (Catppuccin Mocha) ──
    "Mocha": {
        "bg":           "#1e1e2e",
        "bg_alt":       "#181825",
        "bg_deep":      "#11111b",
        "surface":      "#313244",
        "surface_hover": "#45475a",
        "surface_press": "#585b70",
        "border":       "#313244",
        "border_focus": "#89b4fa",
        "text":         "#cdd6f4",
        "text_muted":   "#a6adc8",
        "text_dim":     "#6c7086",
        "accent":       "#89b4fa",
        "accent_hover": "#74c7ec",
        "red":          "#f38ba8",
        "red_hover":    "#eba0ac",
        "green":        "#a6e3a1",
        "yellow":       "#f9e2af",
        "orange":       "#fab387",
        "blue":         "#89b4fa",
        "purple":       "#cba6f7",
        "teal":         "#94e2d5",
        "pattern_bg":   "#2a2a3e",
        "warn_bg":      "#f9a825",
        "warn_text":    "#1e1e2e",
    },

    # ── Mode clair ──
    "Lumière": {
        "bg":           "#f8f9fa",
        "bg_alt":       "#e9ecef",
        "bg_deep":      "#ffffff",
        "surface":      "#ffffff",
        "surface_hover": "#e9ecef",
        "surface_press": "#dee2e6",
        "border":       "#ced4da",
        "border_focus": "#4263eb",
        "text":         "#212529",
        "text_muted":   "#495057",
        "text_dim":     "#868e96",
        "accent":       "#4263eb",
        "accent_hover": "#3b5bdb",
        "red":          "#e03131",
        "red_hover":    "#c92a2a",
        "green":        "#2f9e44",
        "yellow":       "#e8590c",
        "orange":       "#f08c00",
        "blue":         "#1971c2",
        "purple":       "#7048e8",
        "teal":         "#0c8599",
        "pattern_bg":   "#e7f5ff",
        "warn_bg":      "#fff3bf",
        "warn_text":    "#212529",
    },

    # ── Océan — bleu profond ──
    "Océan": {
        "bg":           "#0d1b2a",
        "bg_alt":       "#0a1628",
        "bg_deep":      "#071020",
        "surface":      "#1b2838",
        "surface_hover": "#243447",
        "surface_press": "#2d4056",
        "border":       "#1b3a5c",
        "border_focus": "#48cae4",
        "text":         "#e0e1dd",
        "text_muted":   "#a8b2c1",
        "text_dim":     "#5c6f85",
        "accent":       "#48cae4",
        "accent_hover": "#00b4d8",
        "red":          "#ef476f",
        "red_hover":    "#d63a5c",
        "green":        "#06d6a0",
        "yellow":       "#ffd166",
        "orange":       "#f4845f",
        "blue":         "#118ab2",
        "purple":       "#8338ec",
        "teal":         "#48cae4",
        "pattern_bg":   "#122740",
        "warn_bg":      "#ffd166",
        "warn_text":    "#0d1b2a",
    },

    # ── Forêt — vert profond ──
    "Forêt": {
        "bg":           "#1a2f1a",
        "bg_alt":       "#152815",
        "bg_deep":      "#0f200f",
        "surface":      "#243d24",
        "surface_hover": "#2e4d2e",
        "surface_press": "#3a5c3a",
        "border":       "#2e5a2e",
        "border_focus": "#4ade80",
        "text":         "#d4e6d4",
        "text_muted":   "#a8c8a8",
        "text_dim":     "#6a8f6a",
        "accent":       "#4ade80",
        "accent_hover": "#22c55e",
        "red":          "#f87171",
        "red_hover":    "#ef4444",
        "green":        "#4ade80",
        "yellow":       "#fbbf24",
        "orange":       "#fb923c",
        "blue":         "#60a5fa",
        "purple":       "#a78bfa",
        "teal":         "#2dd4bf",
        "pattern_bg":   "#1e3a1e",
        "warn_bg":      "#fbbf24",
        "warn_text":    "#1a2f1a",
    },

    # ── Crépuscule — violet/coucher de soleil ──
    "Crépuscule": {
        "bg":           "#1c1024",
        "bg_alt":       "#170d1f",
        "bg_deep":      "#120a1a",
        "surface":      "#2a1a36",
        "surface_hover": "#3a2548",
        "surface_press": "#4a305a",
        "border":       "#3d2358",
        "border_focus": "#c084fc",
        "text":         "#e4d4f4",
        "text_muted":   "#b8a0d0",
        "text_dim":     "#7a5c9c",
        "accent":       "#c084fc",
        "accent_hover": "#a855f7",
        "red":          "#fb7185",
        "red_hover":    "#f43f5e",
        "green":        "#86efac",
        "yellow":       "#fde68a",
        "orange":       "#fdba74",
        "blue":         "#93c5fd",
        "purple":       "#c084fc",
        "teal":         "#5eead4",
        "pattern_bg":   "#231530",
        "warn_bg":      "#fde68a",
        "warn_text":    "#1c1024",
    },

    # ── Acier — gris-bleu industriel ──
    "Acier": {
        "bg":           "#1b1f24",
        "bg_alt":       "#161a1f",
        "bg_deep":      "#10141a",
        "surface":      "#272d35",
        "surface_hover": "#333b45",
        "surface_press": "#3f4955",
        "border":       "#30363d",
        "border_focus": "#58a6ff",
        "text":         "#c9d1d9",
        "text_muted":   "#8b949e",
        "text_dim":     "#585f68",
        "accent":       "#58a6ff",
        "accent_hover": "#388bfd",
        "red":          "#f85149",
        "red_hover":    "#da3633",
        "green":        "#3fb950",
        "yellow":       "#d29922",
        "orange":       "#db6d28",
        "blue":         "#58a6ff",
        "purple":       "#bc8cff",
        "teal":         "#39d2c0",
        "pattern_bg":   "#21262d",
        "warn_bg":      "#d29922",
        "warn_text":    "#1b1f24",
    },

    # ── Sable — tons chauds ──
    "Sable": {
        "bg":           "#2d2418",
        "bg_alt":       "#261f14",
        "bg_deep":      "#1f1a10",
        "surface":      "#3a3024",
        "surface_hover": "#4a3e30",
        "surface_press": "#5a4c3c",
        "border":       "#4a3c28",
        "border_focus": "#f0a050",
        "text":         "#e8dcc8",
        "text_muted":   "#c4b498",
        "text_dim":     "#8a7a60",
        "accent":       "#f0a050",
        "accent_hover": "#e08a30",
        "red":          "#e57373",
        "red_hover":    "#d32f2f",
        "green":        "#81c784",
        "yellow":       "#ffb74d",
        "orange":       "#ff8a65",
        "blue":         "#64b5f6",
        "purple":       "#ba68c8",
        "teal":         "#4db6ac",
        "pattern_bg":   "#332a1e",
        "warn_bg":      "#ffb74d",
        "warn_text":    "#2d2418",
    },

    # ── Attention — haute visibilité ──
    "Attention": {
        "bg":           "#1a1a2e",
        "bg_alt":       "#141428",
        "bg_deep":      "#0e0e20",
        "surface":      "#2a2a44",
        "surface_hover": "#3a3a58",
        "surface_press": "#4a4a6c",
        "border":       "#4a4a6c",
        "border_focus": "#ff6b6b",
        "text":         "#ffffff",
        "text_muted":   "#e0e0e0",
        "text_dim":     "#a0a0c0",
        "accent":       "#ff6b6b",
        "accent_hover": "#ff4444",
        "red":          "#ff4444",
        "red_hover":    "#ff0000",
        "green":        "#00ff88",
        "yellow":       "#ffdd00",
        "orange":       "#ff8800",
        "blue":         "#44aaff",
        "purple":       "#cc66ff",
        "teal":         "#00ddcc",
        "pattern_bg":   "#2e2e48",
        "warn_bg":      "#ffdd00",
        "warn_text":    "#1a1a2e",
    },

    # ── Contraste — WCAG AAA, maximum lisibilité ──
    "Contraste": {
        "bg":           "#000000",
        "bg_alt":       "#0a0a0a",
        "bg_deep":      "#000000",
        "surface":      "#1a1a1a",
        "surface_hover": "#2a2a2a",
        "surface_press": "#3a3a3a",
        "border":       "#ffffff",
        "border_focus": "#ffff00",
        "text":         "#ffffff",
        "text_muted":   "#e0e0e0",
        "text_dim":     "#b0b0b0",
        "accent":       "#ffff00",
        "accent_hover": "#ffdd00",
        "red":          "#ff4444",
        "red_hover":    "#ff0000",
        "green":        "#44ff44",
        "yellow":       "#ffff00",
        "orange":       "#ff8800",
        "blue":         "#44aaff",
        "purple":       "#dd88ff",
        "teal":         "#00ffdd",
        "pattern_bg":   "#1a1a1a",
        "warn_bg":      "#ffff00",
        "warn_text":    "#000000",
    },
}

# ── Tailles de police disponibles ──
FONT_SIZES = {
    "Petit": 11,
    "Normal": 13,
    "Grand": 15,
    "Très grand": 17,
}

# ── Couleurs actives (mises à jour par apply_theme) ──
COLORS = dict(THEMES["Mocha"])

# ── Noms pour l'affichage dans le sélecteur ──
THEME_NAMES = list(THEMES.keys())


def _generate_stylesheet(c: dict, font_size: int = 13) -> str:
    """Génère le stylesheet complet à partir d'une palette de couleurs."""
    fs = font_size
    fs_title = fs + 1
    fs_mono = fs

    return f"""
QMainWindow, QDialog {{
    background-color: {c['bg']};
    color: {c['text']};
}}

QWidget {{
    background-color: {c['bg']};
    color: {c['text']};
    font-size: {fs}px;
}}

QMenuBar {{
    background-color: {c['bg_alt']};
    color: {c['text']};
    border-bottom: 1px solid {c['border']};
    padding: 2px;
}}

QMenuBar::item:selected {{
    background-color: {c['surface_hover']};
    border-radius: 4px;
}}

QMenu {{
    background-color: {c['bg']};
    color: {c['text']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    padding: 4px;
}}

QMenu::item:selected {{
    background-color: {c['surface_hover']};
    border-radius: 4px;
}}

QToolBar {{
    background-color: {c['bg_alt']};
    border-bottom: 1px solid {c['border']};
    spacing: 4px;
    padding: 2px;
}}

QStatusBar {{
    background-color: {c['bg_alt']};
    color: {c['text_muted']};
    border-top: 1px solid {c['border']};
}}

QPushButton {{
    background-color: {c['surface']};
    color: {c['text']};
    border: 1px solid {c['surface_hover']};
    border-radius: 6px;
    padding: 6px 16px;
    font-weight: bold;
    min-height: 24px;
}}

QPushButton:hover {{
    background-color: {c['surface_hover']};
    border-color: {c['accent']};
}}

QPushButton:pressed {{
    background-color: {c['surface_press']};
}}

QPushButton:disabled {{
    background-color: {c['bg']};
    color: {c['surface_press']};
    border-color: {c['border']};
}}

QPushButton#primary {{
    background-color: {c['accent']};
    color: {c['bg']};
    border: none;
}}

QPushButton#primary:hover {{
    background-color: {c['accent_hover']};
}}

QPushButton#danger {{
    background-color: {c['red']};
    color: {c['bg']};
    border: none;
}}

QPushButton#danger:hover {{
    background-color: {c['red_hover']};
}}

QLineEdit, QSpinBox, QDoubleSpinBox {{
    background-color: {c['surface']};
    color: {c['text']};
    border: 1px solid {c['surface_hover']};
    border-radius: 6px;
    padding: 5px 8px;
    selection-background-color: {c['accent']};
    selection-color: {c['bg']};
}}

QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: {c['accent']};
}}

QComboBox {{
    background-color: {c['surface']};
    color: {c['text']};
    border: 1px solid {c['surface_hover']};
    border-radius: 6px;
    padding: 5px 8px;
    min-height: 24px;
}}

QComboBox:hover {{
    border-color: {c['accent']};
}}

QComboBox::drop-down {{
    border: none;
    width: 24px;
}}

QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 6px solid {c['text']};
    margin-right: 8px;
}}

QComboBox QAbstractItemView {{
    background-color: {c['surface']};
    color: {c['text']};
    border: 1px solid {c['surface_hover']};
    selection-background-color: {c['surface_hover']};
    border-radius: 6px;
}}

QCheckBox {{
    color: {c['text']};
    spacing: 8px;
}}

QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 2px solid {c['surface_hover']};
    background-color: {c['surface']};
}}

QCheckBox::indicator:checked {{
    background-color: {c['accent']};
    border-color: {c['accent']};
}}

QListWidget {{
    background-color: {c['bg_alt']};
    color: {c['text']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    outline: none;
    padding: 4px;
}}

QListWidget::item {{
    background-color: {c['bg']};
    color: {c['text']};
    border-radius: 4px;
    padding: 8px;
    margin: 2px 0;
}}

QListWidget::item:selected {{
    background-color: {c['surface']};
    border: 1px solid {c['accent']};
}}

QListWidget::item:hover {{
    background-color: {c['surface']};
}}

QTreeWidget {{
    background-color: {c['bg_alt']};
    color: {c['text']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    outline: none;
}}

QTreeWidget::item:selected {{
    background-color: {c['surface']};
}}

QTextEdit, QPlainTextEdit {{
    background-color: {c['bg_deep']};
    color: {c['text']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    font-family: "Cascadia Code", "Consolas", "Courier New", monospace;
    font-size: {fs_mono}px;
    selection-background-color: {c['surface_hover']};
    selection-color: {c['text']};
}}

QScrollBar:vertical {{
    background-color: {c['bg_alt']};
    width: 10px;
    border-radius: 5px;
}}

QScrollBar::handle:vertical {{
    background-color: {c['surface_hover']};
    border-radius: 5px;
    min-height: 30px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {c['surface_press']};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QScrollBar:horizontal {{
    background-color: {c['bg_alt']};
    height: 10px;
    border-radius: 5px;
}}

QScrollBar::handle:horizontal {{
    background-color: {c['surface_hover']};
    border-radius: 5px;
    min-width: 30px;
}}

QScrollBar::handle:horizontal:hover {{
    background-color: {c['surface_press']};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

QSplitter::handle {{
    background-color: {c['border']};
    width: 3px;
}}

QSplitter::handle:hover {{
    background-color: {c['accent']};
}}

QTabWidget::pane {{
    border: 1px solid {c['border']};
    border-radius: 6px;
    background-color: {c['bg']};
}}

QTabBar::tab {{
    background-color: {c['bg_alt']};
    color: {c['text_muted']};
    border: 1px solid {c['border']};
    border-bottom: none;
    padding: 8px 16px;
    margin-right: 2px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}}

QTabBar::tab:selected {{
    background-color: {c['bg']};
    color: {c['accent']};
    border-color: {c['accent']};
    border-bottom: 2px solid {c['accent']};
}}

QTabBar::tab:hover:!selected {{
    background-color: {c['surface']};
    color: {c['text']};
}}

QGroupBox {{
    color: {c['text']};
    border: 1px solid {c['border']};
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 16px;
    font-weight: bold;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}}

QLabel {{
    color: {c['text']};
}}

QLabel#section_title {{
    color: {c['accent']};
    font-size: {fs_title}px;
    font-weight: bold;
    padding: 4px 0;
}}

QToolTip {{
    background-color: {c['surface']};
    color: {c['text']};
    border: 1px solid {c['surface_hover']};
    border-radius: 4px;
    padding: 4px;
}}

QHeaderView::section {{
    background-color: {c['bg_alt']};
    color: {c['text']};
    border: 1px solid {c['border']};
    padding: 6px;
}}

QTableWidget {{
    background-color: {c['bg_alt']};
    color: {c['text']};
    gridline-color: {c['border']};
    border: 1px solid {c['border']};
    border-radius: 6px;
}}

QTableWidget::item:selected {{
    background-color: {c['surface_hover']};
}}

QDialog {{
    background-color: {c['bg']};
}}

QProgressBar {{
    background-color: {c['surface']};
    border-radius: 6px;
    text-align: center;
    color: {c['text']};
}}

QProgressBar::chunk {{
    background-color: {c['accent']};
    border-radius: 6px;
}}
"""


def _build_palette(c: dict) -> QPalette:
    """Construit une QPalette à partir d'une palette de couleurs."""
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(c['bg']))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(c['text']))
    palette.setColor(QPalette.ColorRole.Base, QColor(c['bg_deep']))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(c['bg_alt']))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(c['surface']))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(c['text']))
    palette.setColor(QPalette.ColorRole.Text, QColor(c['text']))
    palette.setColor(QPalette.ColorRole.Button, QColor(c['surface']))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(c['text']))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(c['red']))
    palette.setColor(QPalette.ColorRole.Link, QColor(c['accent']))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(c['accent']))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(c['bg']))
    return palette


# ── État courant ──
_current_theme = "Mocha"
_current_font_size = 13


def apply_theme(app: QApplication, theme_name: str = "Mocha",
                font_size: int = 13):
    """Applique un thème à l'application.

    Args:
        app: l'instance QApplication
        theme_name: nom du thème (clé de THEMES)
        font_size: taille de police en px
    """
    global COLORS, _current_theme, _current_font_size

    # Les icônes sont des pixmaps peints avec l'ANCIENNE palette:
    # les garder en cache après un changement de thème les figerait
    try:
        from src.gui.icons import vider_cache_icones
        vider_cache_icones()
    except ImportError:
        pass

    if theme_name not in THEMES:
        theme_name = "Mocha"

    _current_theme = theme_name
    _current_font_size = font_size

    c = THEMES[theme_name]
    COLORS.clear()
    COLORS.update(c)

    stylesheet = _generate_stylesheet(c, font_size)
    app.setStyleSheet(stylesheet)
    app.setPalette(_build_palette(c))

    # Sauvegarder la préférence
    settings = reglages_qt()
    settings.setValue("theme/name", theme_name)
    settings.setValue("theme/font_size", font_size)


def get_current_theme() -> str:
    """Retourne le nom du thème actif."""
    return _current_theme


def get_current_font_size() -> int:
    """Retourne la taille de police active."""
    return _current_font_size


def load_saved_theme() -> tuple:
    """Charge les préférences de thème sauvegardées.

    Returns:
        (theme_name, font_size)
    """
    settings = reglages_qt()
    name = settings.value("theme/name", "Mocha")
    size = settings.value("theme/font_size", 13)
    try:
        size = int(size)
    except (ValueError, TypeError):
        size = 13
    if name not in THEMES:
        name = "Mocha"
    return name, size


# ── Rétro-compatibilité ──
DARK_STYLESHEET = _generate_stylesheet(THEMES["Mocha"], 13)


def apply_dark_theme(app: QApplication):
    """Rétro-compatibilité: charge le thème sauvegardé ou Mocha par défaut."""
    name, size = load_saved_theme()
    apply_theme(app, name, size)

