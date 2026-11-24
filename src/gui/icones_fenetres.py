"""Les icônes des fenêtres d'onglets sortis, dans la barre des tâches.

Octobre 2026 (RomDuch): plusieurs fenêtres d'outils ouvertes, « pas la
même icône mais un lien de parenté évident ». Chaque fenêtre porte le
logo de NeoDrive avec un BADGE à elle — une pastille de couleur et le
pictogramme de l'onglet (cube pour le Canva 3D, outil pour Tools…) —,
et sous Windows son propre identifiant de groupe (AppUserModelID):
elle a son bouton dans la barre des tâches, avec son icône, au lieu de
se ranger sous celui de NeoDrive.
"""

import sys
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap

#: le pictogramme du badge selon l'onglet (mot de son titre → icône)
BADGES = (
    ('3d', 'b_cube'), ('canva', 'dxf'), ('tools', 'tool'),
    ('outil', 'tool'), ('catalogue', 'toolbox'), ('code', 'nds'),
    ('simpl', 'nds'), ('dxf_to_op', 'drill'), ('operation', 'drill_mill'),
    ('param', 'settings'), ('historique', 'history'),
    ('raccourci', 'help'), ('symbole', 'pattern'),
    ('materiau', 'material'), ('edit', 'dialogue'),
)
#: les tailles rendues (la barre des tâches, Alt+Tab, le titre)
TAILLES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
#: préfixe de l'identifiant de groupe Windows des fenêtres
PREFIXE_APPID = "RomDuch.NeoDrive"


def badge_de(titre: str) -> str:
    """Le nom d'icône du badge pour un titre d'onglet ("" : une lettre)."""
    import unicodedata
    t = unicodedata.normalize('NFKD', str(titre or "")).encode(
        'ascii', 'ignore').decode('ascii').lower().replace(" ", "_")
    for mot, icone in BADGES:
        if mot in t:
            return icone
    return ""


def couleur_de(titre: str) -> str:
    """La pastille: une teinte stable par titre (celles des outils)."""
    from src.core.tool_library import PALETTE_OUTILS
    h = 0
    for c in str(titre or ""):
        h = (h * 131 + ord(c)) & 0xFFFFFF
    return PALETTE_OUTILS[h % len(PALETTE_OUTILS)]


def _base(icone_app: Optional[QIcon], taille: int) -> QPixmap:
    pix = QPixmap(taille, taille)
    pix.fill(Qt.GlobalColor.transparent)
    if icone_app is not None and not icone_app.isNull():
        source = icone_app.pixmap(taille, taille)
        p = QPainter(pix)
        p.drawPixmap(0, 0, source.scaled(
            taille, taille, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))
        p.end()
        return pix
    # sans icône d'application (tests, scripts): un carré « N »
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor("#313244"))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(QRectF(0, 0, taille, taille), taille * 0.2,
                      taille * 0.2)
    p.setPen(QColor("#89b4fa"))
    f = QFont()
    f.setPixelSize(max(6, int(taille * 0.62)))
    f.setBold(True)
    p.setFont(f)
    p.drawText(QRectF(0, 0, taille, taille), Qt.AlignmentFlag.AlignCenter,
               "N")
    p.end()
    return pix


def icone_derivee(titre: str, icone_app: Optional[QIcon] = None) -> QIcon:
    """Le logo de l'application avec le badge de cet onglet."""
    from src.gui import icons
    from src.gui import icones_barre  # noqa: F401  (les icônes « b_… »)
    nom = badge_de(titre)
    teinte = QColor(couleur_de(titre))
    sortie = QIcon()
    for taille in TAILLES:
        pix = _base(icone_app, taille)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = taille * 0.30
        centre = QPointF(taille - r - taille * 0.02, taille - r - taille * 0.02)
        p.setBrush(teinte)
        p.setPen(QPen(QColor("#ffffff"), max(1.0, taille / 24.0)))
        p.drawEllipse(centre, r, r)
        cote = int(r * 1.35)
        if nom and cote >= 6:
            glyphe = icons.get_icon(nom, cote, "#1e1e2e").pixmap(cote, cote)
            p.drawPixmap(int(centre.x() - cote / 2), int(centre.y() - cote / 2),
                         glyphe)
        elif cote >= 6:
            f = QFont()
            f.setPixelSize(max(5, int(r * 1.2)))
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor("#1e1e2e"))
            p.drawText(QRectF(centre.x() - r, centre.y() - r, 2 * r, 2 * r),
                       Qt.AlignmentFlag.AlignCenter,
                       (str(titre or "?").strip() or "?")[0].upper())
        p.end()
        sortie.addPixmap(pix)
    return sortie


def appid(cle: str) -> str:
    """L'identifiant de groupe Windows d'une fenêtre d'onglet."""
    import re
    return PREFIXE_APPID + "." + (re.sub(r'[^A-Za-z0-9]+', '', str(cle))
                                  or "fenetre")


def poser_appid(fenetre, ident: str) -> bool:
    """Sous Windows: la fenêtre dans son propre groupe de la barre des
    tâches (PKEY_AppUserModel_ID de sa fenêtre native). Rend vrai si
    c'est fait; ailleurs, ou en cas d'échec, rien ne change."""
    if sys.platform != 'win32':
        return False
    try:
        import ctypes
        from ctypes import wintypes
        from PySide6.QtGui import QGuiApplication
        if QGuiApplication.platformName() != 'windows':
            return False            # offscreen: pas de vraie fenêtre

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                        ("Data3", ctypes.c_ushort),
                        ("Data4", ctypes.c_ubyte * 8)]

        class PROPERTYKEY(ctypes.Structure):
            _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]

        class PROPVARIANT(ctypes.Structure):
            _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort),
                        ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                        ("pwszVal", ctypes.c_wchar_p),
                        ("pad", ctypes.c_void_p)]

        def guid(texte):
            g = GUID()
            ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p(texte),
                                                ctypes.byref(g))
            return g

        iid = guid("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
        cle = PROPERTYKEY(guid("{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"), 5)
        hwnd = wintypes.HWND(int(fenetre.winId()))
        magasin = ctypes.c_void_p()
        hr = ctypes.windll.shell32.SHGetPropertyStoreForWindow(
            hwnd, ctypes.byref(iid), ctypes.byref(magasin))
        if hr != 0 or not magasin:
            return False
        table = ctypes.cast(magasin, ctypes.POINTER(ctypes.POINTER(
            ctypes.c_void_p))).contents
        proto_set = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p,
                                       ctypes.POINTER(PROPERTYKEY),
                                       ctypes.POINTER(PROPVARIANT))
        proto_commit = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)
        proto_release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
        valeur = PROPVARIANT()
        valeur.vt = 31              # VT_LPWSTR
        valeur.pwszVal = ident
        try:
            hr = proto_set(table[6])(magasin, ctypes.byref(cle),
                                     ctypes.byref(valeur))
            if hr == 0:
                hr = proto_commit(table[7])(magasin)
        finally:
            proto_release(table[2])(magasin)
        return hr == 0
    except Exception:
        return False


def habiller(fenetre, cle: str, titre: str) -> bool:
    """L'icône dérivée et le groupe Windows d'une fenêtre d'onglet.
    Rend vrai si la fenêtre a son propre bouton (Windows)."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    base = app.windowIcon() if app is not None else None
    icone = icone_derivee(titre, base)
    fenetre.setWindowIcon(icone)
    fenetre.setProperty('icone_badge', badge_de(titre))
    return poser_appid(fenetre, appid(cle))
