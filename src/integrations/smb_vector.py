"""
Extraction VECTORIELLE des fichiers .smb (symboles TypeEdit/Type3).

Format découvert par reverse engineering (voir docs/smb_format.md):
la zone vectorielle contient des points en coordonnées homogènes NURBS
(w·x, w·y, w·z, w) — 4 doubles — espacés de 36 octets au sein d'un
contour. Point réel = (wx/w, wy/w) × 1000 (mètres → mm).

- w = 1.0     → point SUR la courbe (sommet)
- w ≈ 0.7071  → point de CONTRÔLE d'arc conique rationnel (90°)
- autres w (0<w<1) → contrôle conique générique

Reconstruction: alternance sommet/contrôle → coniques rationnelles
quadratiques échantillonnées; sommets consécutifs → segments droits.
Un écart ≠ 36 octets sépare deux contours.
"""

import math
import struct
from typing import List, Tuple

Point = Tuple[float, float]

_STRIDE = 36
_MAX_MM = 5000.0  # borne de plausibilité des coordonnées (mm)


def _scan_raw(data: bytes) -> List[List[Tuple[float, float, float]]]:
    """Scanne les quadruplets homogènes et groupe en contours par
    continuité d'offset (+36). Retourne [[(x_mm, y_mm, w)]]."""
    try:
        vec_start = struct.unpack_from('<I', data, 4)[0]
    except struct.error:
        return []
    if not (52 <= vec_start < len(data)):
        return []
    vec = data[vec_start:]

    contours: List[List[Tuple[float, float, float]]] = []
    current: List[Tuple[float, float, float]] = []
    last_off = None
    off = 0
    end = len(vec) - 32
    while off <= end:
        x, y, z, w = struct.unpack_from('<dddd', vec, off)
        ok = (x == x and y == y and w == w and z == 0.0
              and 0.05 < w <= 1.0)
        if ok:
            rx, ry = x / w * 1000.0, y / w * 1000.0
            ok = abs(rx) < _MAX_MM and abs(ry) < _MAX_MM
        if ok:
            if last_off is not None and off - last_off == _STRIDE:
                current.append((rx, ry, w))
            else:
                if len(current) >= 2:
                    contours.append(current)
                current = [(rx, ry, w)]
            last_off = off
            off += _STRIDE
        else:
            off += 1
    if len(current) >= 2:
        contours.append(current)
    return contours


def _conic_arc(p0: Point, ctrl_h: Tuple[float, float], w: float,
               p2: Point, steps: int = 0) -> List[Point]:
    """Échantillonne une conique rationnelle quadratique.
    ctrl_h = point de contrôle DÉSHOMOGÉNÉISÉ (x, y); w = poids.
    steps=0 → adaptatif selon la taille de l'arc (lisse en zoom)."""
    cx, cy = ctrl_h
    if steps <= 0:
        # ~3 segments/mm de corde, bornés — les petits trous restent
        # légers, les grands arcs deviennent lisses
        chord = math.hypot(p2[0] - p0[0], p2[1] - p0[1])
        steps = max(8, min(64, int(chord * 3)))
    pts = []
    for i in range(1, steps + 1):
        t = i / steps
        a = (1 - t) * (1 - t)
        b = 2 * t * (1 - t) * w
        c = t * t
        d = a + b + c
        pts.append(((a * p0[0] + b * cx + c * p2[0]) / d,
                    (a * p0[1] + b * cy + c * p2[1]) / d))
    return pts


def _build_polyline(contour: List[Tuple[float, float, float]]
                    ) -> List[Point]:
    """Reconstruit une polyligne échantillonnée depuis un contour
    (sommets w≈1 + contrôles w<1 en alternance)."""
    ON = 0.9999
    # Rotation pour commencer par un sommet (un contrôle en tête
    # appartient à l'arc de fermeture)
    n = len(contour)
    start = 0
    while start < n and contour[start][2] < ON:
        start += 1
    if start == n:
        # Aucun sommet: dégrader en polyligne brute
        return [(p[0], p[1]) for p in contour]
    rotated = contour[start:] + contour[:start]
    # Contour fermé si l'alternance retombe sur un contrôle final
    closed = rotated[-1][2] < ON

    out: List[Point] = [(rotated[0][0], rotated[0][1])]
    pending_ctrl = None
    for px, py, w in rotated[1:]:
        if w >= ON:
            if pending_ctrl is not None:
                cx, cy, cw = pending_ctrl
                out.extend(_conic_arc(out[-1], (cx, cy), cw, (px, py)))
                pending_ctrl = None
            else:
                out.append((px, py))
        else:
            pending_ctrl = (px, py, w)
    if closed:
        first = out[0]
        if pending_ctrl is not None:
            cx, cy, cw = pending_ctrl
            out.extend(_conic_arc(out[-1], (cx, cy), cw, first))
        elif out[-1] != first:
            out.append(first)
    return out


_TEXT_STRIDE = 204


def _find_bbox_before(vec: bytes, pos: int):
    """Cherche la bbox objet (6 doubles xmin,ymin,0,xmax,ymax,0) la
    plus proche AVANT pos. Retourne (x0,y0,x1,y1) en mm ou None."""
    best = None
    for off in range(max(0, pos - 3000), pos - 47):
        try:
            x0, y0, z0, x1, y1, z1 = struct.unpack_from('<6d', vec, off)
        except struct.error:
            break
        if (z0 == 0.0 and z1 == 0.0 and x0 == x0 and y0 == y0
                and x0 < x1 and y0 < y1
                and abs(x0) < 1 and abs(x1) < 1
                and abs(y0) < 1 and abs(y1) < 1
                and (x1 - x0) > 1e-4 and (y1 - y0) > 1e-4):
            best = (x0 * 1000, y0 * 1000, x1 * 1000, y1 * 1000)
    return best


def extract_smb_texts(filepath: str) -> List[Tuple[str, float, float,
                                                   float, float]]:
    """Extrait les entités TEXTE (glyphes police non convertis en
    courbes). Chaque caractère = enregistrement de 204 octets:
    +0 int32 longueur de chaîne, +8 int32 code unicode.
    Retourne [(texte, x0, y0, x1, y1)] avec la bbox de l'entité (mm)."""
    try:
        with open(filepath, 'rb') as f:
            data = f.read()
        vec_start = struct.unpack_from('<I', data, 4)[0]
    except (OSError, struct.error):
        return []
    if not (52 <= vec_start < len(data)):
        return []
    vec = data[vec_start:]

    results = []
    off = 0
    end = len(vec) - 16
    while off <= end:
        try:
            n, _f2 = struct.unpack_from('<ii', vec, off)
            code, zero = struct.unpack_from('<ii', vec, off + 8)
        except struct.error:
            break
        if (2 <= n <= 500 and zero == 0 and 32 <= code <= 0x2FFF):
            # Tenter de lire un run de n records stride 204
            chars = []
            ok = True
            for i in range(n):
                o = off + i * _TEXT_STRIDE
                if o + 16 > len(vec):
                    ok = False
                    break
                ni, _x = struct.unpack_from('<ii', vec, o)
                ci, zi = struct.unpack_from('<ii', vec, o + 8)
                # Seul le 1er record porte la longueur; les suivants: 0
                expected_n = n if i == 0 else 0
                if (ni != expected_n or zi != 0
                        or not (0 <= ci <= 0x2FFF)):
                    ok = False
                    break
                chars.append(ci)
            if ok:
                text = ''.join(chr(c) for c in chars if c > 0)
                # Plausibilité: imprimable, longueur cohérente, et au
                # moins un alphanumérique (écarte les faux runs '????')
                plausible = (
                    text and len(text) >= n - 1
                    and all(c.isprintable() for c in text)
                    and any(c.isalnum() for c in text))
                if plausible:
                    bbox = _find_bbox_before(vec, off)
                    if bbox:
                        results.append((text, *bbox))
                    off += n * _TEXT_STRIDE
                    continue
        off += 2
    return results


def text_path_in_rect(text: str, rx: float, ry: float,
                      rw: float, rh: float):
    """QPainterPath du texte (police Arial vectorisée), ajusté et
    centré dans le rectangle donné (coordonnées Y-down/scène)."""
    from PySide6.QtGui import QPainterPath, QFont, QTransform
    font = QFont("Arial")
    font.setPointSizeF(100.0)
    raw = QPainterPath()
    raw.addText(0, 0, font, text)
    br = raw.boundingRect()
    if br.width() <= 0 or br.height() <= 0 or rw <= 0 or rh <= 0:
        return None
    s = min(rw / br.width(), rh / br.height())
    t = QTransform()
    t.translate(rx + (rw - br.width() * s) / 2 - br.left() * s,
                ry + (rh - br.height() * s) / 2 - br.top() * s)
    t.scale(s, s)
    return t.map(raw)


def extract_smb_polylines(filepath: str) -> List[List[Point]]:
    """Extrait les contours vectoriels d'un .smb en polylignes (mm).
    Retourne [] si le fichier ne se décode pas (fallback vignette)."""
    try:
        with open(filepath, 'rb') as f:
            data = f.read()
    except OSError:
        return []
    try:
        contours = _scan_raw(data)
        polylines = []
        for c in contours:
            poly = _build_polyline(c)
            if len(poly) >= 2:
                polylines.append(poly)
        return polylines
    except Exception:
        return []


def render_smb_vector(filepath: str, size: int = 290):
    """Rendu QPixmap vectoriel antialiasé du symbole, ou None si le
    décodage échoue/est vide (l'appelant retombe sur la vignette)."""
    polylines = extract_smb_polylines(filepath)
    texts = extract_smb_texts(filepath)
    if not polylines and not texts:
        return None
    total_pts = sum(len(p) for p in polylines)
    # Résultat dégénéré sans texte: la vignette est plus fidèle
    if total_pts < 8 and not texts:
        return None
    xs = [p[0] for poly in polylines for p in poly]
    ys = [p[1] for poly in polylines for p in poly]
    for _t, tx0, ty0, tx1, ty1 in texts:
        xs.extend([tx0, tx1])
        ys.extend([ty0, ty1])
    w = max(xs) - min(xs)
    h = max(ys) - min(ys)
    if w < 0.01 and h < 0.01:
        return None
    # Décimation des très gros symboles (perf rendu)
    if total_pts > 60000:
        step = total_pts // 60000 + 1
        polylines = [
            (p[::step] + [p[-1]]) if len(p) > step else p
            for p in polylines
        ]

    from PySide6.QtGui import QPixmap, QPainter, QPen, QColor
    from PySide6.QtCore import Qt, QPointF
    margin = size * 0.06
    scale = (size - 2 * margin) / max(w, h, 1e-6)
    ox = (size - w * scale) / 2 - min(xs) * scale
    oy = (size - h * scale) / 2 + max(ys) * scale  # Y inversé

    pm = QPixmap(size, size)
    pm.fill(QColor("#181825"))
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor("#a6e3a1"), 1.4)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    for poly in polylines:
        qpts = [QPointF(x * scale + ox, -y * scale + oy)
                for x, y in poly]
        for a, b in zip(qpts, qpts[1:]):
            painter.drawLine(a, b)
    # Entités texte: police Arial vectorisée, ajustée dans leur bbox
    for text, tx0, ty0, tx1, ty1 in texts:
        path = text_path_in_rect(
            text,
            tx0 * scale + ox, -ty1 * scale + oy,
            (tx1 - tx0) * scale, (ty1 - ty0) * scale)
        if path is not None:
            painter.fillPath(path, QColor("#a6e3a1"))
    painter.end()
    return pm
