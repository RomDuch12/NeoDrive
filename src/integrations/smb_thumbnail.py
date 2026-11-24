"""
Extraction de la vignette intégrée des fichiers .smb (symboles
TypeEdit/Type3). Le format est propriétaire (sérialisation MFC CObDao),
mais un DIB (BITMAPINFOHEADER) de prévisualisation est stocké en clair
à l'offset 12 — typiquement 100×100 en 8 bits + palette.

Structure observée:
    0   : magic/version (4 octets)
    4   : offset de fin de vignette (uint32) = 12 + 40 + palette + pixels
    8   : uint32 (inconnu)
    12  : BITMAPINFOHEADER (40 octets) + palette + pixels
"""

import struct
from typing import Optional


def extract_smb_thumbnail_bmp(filepath: str) -> Optional[bytes]:
    """Retourne la vignette sous forme de fichier BMP complet (bytes),
    ou None si le fichier n'a pas de vignette reconnaissable."""
    try:
        with open(filepath, 'rb') as f:
            data = f.read(12 + 40)
            if len(data) < 52:
                return None
            bi_size, w, h = struct.unpack_from('<Iii', data, 12)
            planes, bpp = struct.unpack_from('<HH', data, 24)
            if bi_size != 40 or planes != 1:
                return None
            if not (0 < w <= 2048 and 0 < abs(h) <= 2048):
                return None
            if bpp not in (1, 4, 8, 24, 32):
                return None
            palette = (256 * 4 if bpp == 8 else
                       16 * 4 if bpp == 4 else
                       2 * 4 if bpp == 1 else 0)
            row = (w * bpp // 8 + 3) & ~3
            dib_len = 40 + palette + row * abs(h)
            f.seek(12)
            dib = f.read(dib_len)
            if len(dib) < dib_len:
                return None
        header = b'BM' + struct.pack(
            '<IHHI', 14 + dib_len, 0, 0, 14 + 40 + palette)
        return header + dib
    except OSError:
        return None


def extract_smb_thumbnail(filepath: str):
    """Retourne un QPixmap de la vignette, ou None.
    (Import Qt local pour garder le module utilisable sans GUI.)"""
    bmp = extract_smb_thumbnail_bmp(filepath)
    if bmp is None:
        return None
    from PySide6.QtGui import QPixmap
    pm = QPixmap()
    if not pm.loadFromData(bmp, 'BMP') or pm.isNull():
        return None
    return pm


def upscale_lineart(pm, target_w: int, target_h: int):
    """Agrandit une vignette de dessin au trait en préservant les bords:
    doublements nearest-neighbor successifs puis lissage final — bien
    plus net qu'une interpolation bilinéaire directe depuis 100×100."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPixmap
    img = pm.toImage().convertToFormat(QImage.Format.Format_RGB32)
    # Doubler en nearest tant qu'on est nettement sous la cible
    while (img.width() * 2 <= target_w * 2
           and img.width() < target_w):
        img = img.scaled(
            img.width() * 2, img.height() * 2,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation)
    img = img.scaled(
        target_w, target_h,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation)
    return QPixmap.fromImage(img)
