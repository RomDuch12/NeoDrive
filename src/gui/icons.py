"""NeoDrive — Icônes vectorielles thème-aware.

Toutes les icônes sont dessinées programmatiquement via QPainter.
Elles s'adaptent automatiquement au thème actif (couleur, taille).
"""
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import (
    QIcon, QPixmap, QPainter, QPen, QBrush, QColor, QFont, QPainterPath
)
from src.gui.theme import THEMES, get_current_theme


def _colors():
    """Retourne la palette du thème actif."""
    return THEMES.get(get_current_theme(), THEMES["Mocha"])


def _make_icon(draw_fn, size=24):
    """Crée un QIcon à partir d'une fonction de dessin."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw_fn(p, size)
    p.end()
    return QIcon(pix)


# ══════════════════════════════════════════════════════
#  Navigation / Fichiers
# ══════════════════════════════════════════════════════

def icon_new_file(size=24):
    def draw(p, s):
        c = _colors()
        pen = QPen(QColor(c['accent']), 1.5)
        p.setPen(pen)
        m = s * 0.2
        w = s * 0.5
        h = s * 0.65
        fold = s * 0.15
        path = QPainterPath()
        path.moveTo(m, m)
        path.lineTo(m + w - fold, m)
        path.lineTo(m + w, m + fold)
        path.lineTo(m + w, m + h)
        path.lineTo(m, m + h)
        path.closeSubpath()
        p.drawPath(path)
        # Fold triangle
        p.drawLine(QPointF(m + w - fold, m),
                    QPointF(m + w - fold, m + fold))
        p.drawLine(QPointF(m + w - fold, m + fold),
                    QPointF(m + w, m + fold))
        # Plus sign
        cx, cy = s * 0.65, s * 0.65
        r = s * 0.12
        p.setPen(QPen(QColor(c['green']), 1.8))
        p.drawLine(QPointF(cx - r, cy), QPointF(cx + r, cy))
        p.drawLine(QPointF(cx, cy - r), QPointF(cx, cy + r))
    return _make_icon(draw, size)


def icon_open_file(size=24):
    def draw(p, s):
        c = _colors()
        pen = QPen(QColor(c['accent']), 1.5)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        # Folder base
        path = QPainterPath()
        m = s * 0.15
        path.moveTo(m, s * 0.35)
        path.lineTo(m, s * 0.8)
        path.lineTo(s * 0.85, s * 0.8)
        path.lineTo(s * 0.85, s * 0.35)
        path.lineTo(s * 0.5, s * 0.35)
        path.lineTo(s * 0.4, s * 0.25)
        path.lineTo(m, s * 0.25)
        path.closeSubpath()
        p.drawPath(path)
        # Open flap
        p.drawLine(QPointF(m, s * 0.45),
                    QPointF(s * 0.85, s * 0.45))
    return _make_icon(draw, size)


def icon_save(size=24):
    def draw(p, s):
        c = _colors()
        pen = QPen(QColor(c['accent']), 1.5)
        p.setPen(pen)
        m = s * 0.18
        e = s * 0.82
        # Floppy outline
        p.drawRect(QRectF(m, m, e - m, e - m))
        # Top slot
        slot_l = s * 0.35
        slot_r = s * 0.65
        p.drawRect(QRectF(slot_l, m, slot_r - slot_l, s * 0.2))
        # Bottom label
        lbl_m = s * 0.3
        p.drawRect(QRectF(lbl_m, s * 0.52, s * 0.4, s * 0.3))
    return _make_icon(draw, size)


def icon_export(size=24):
    def draw(p, s):
        c = _colors()
        pen = QPen(QColor(c['green']), 1.8)
        p.setPen(pen)
        cx = s * 0.5
        # Arrow up
        p.drawLine(QPointF(cx, s * 0.2), QPointF(cx, s * 0.65))
        p.drawLine(QPointF(cx, s * 0.2), QPointF(cx - s * 0.12, s * 0.35))
        p.drawLine(QPointF(cx, s * 0.2), QPointF(cx + s * 0.12, s * 0.35))
        # Tray
        p.setPen(QPen(QColor(c['accent']), 1.5))
        p.drawLine(QPointF(s * 0.2, s * 0.75), QPointF(s * 0.2, s * 0.85))
        p.drawLine(QPointF(s * 0.2, s * 0.85), QPointF(s * 0.8, s * 0.85))
        p.drawLine(QPointF(s * 0.8, s * 0.85), QPointF(s * 0.8, s * 0.75))
    return _make_icon(draw, size)


def icon_import(size=24):
    """L'inverse d'Exporter: la flèche entre dans le bac."""
    def draw(p, s):
        c = _colors()
        pen = QPen(QColor(c['blue']), 1.8)
        p.setPen(pen)
        cx = s * 0.5
        # Arrow down
        p.drawLine(QPointF(cx, s * 0.15), QPointF(cx, s * 0.62))
        p.drawLine(QPointF(cx, s * 0.62), QPointF(cx - s * 0.12, s * 0.47))
        p.drawLine(QPointF(cx, s * 0.62), QPointF(cx + s * 0.12, s * 0.47))
        # Tray
        p.setPen(QPen(QColor(c['accent']), 1.5))
        p.drawLine(QPointF(s * 0.2, s * 0.75), QPointF(s * 0.2, s * 0.85))
        p.drawLine(QPointF(s * 0.2, s * 0.85), QPointF(s * 0.8, s * 0.85))
        p.drawLine(QPointF(s * 0.8, s * 0.85), QPointF(s * 0.8, s * 0.75))
    return _make_icon(draw, size)


# ══════════════════════════════════════════════════════
#  Opérations CNC
# ══════════════════════════════════════════════════════

def icon_drill(size=24):
    """Perçage — foret."""
    def draw(p, s):
        c = _colors()
        pen = QPen(QColor(c['blue']), 1.5)
        p.setPen(pen)
        cx = s * 0.5
        # Shaft
        p.drawLine(QPointF(cx, s * 0.15), QPointF(cx, s * 0.6))
        # Tip (V)
        p.drawLine(QPointF(cx, s * 0.82), QPointF(cx - s * 0.1, s * 0.6))
        p.drawLine(QPointF(cx, s * 0.82), QPointF(cx + s * 0.1, s * 0.6))
        # Flutes
        p.setPen(QPen(QColor(c['blue']), 0.8))
        p.drawLine(QPointF(cx - s * 0.06, s * 0.25),
                    QPointF(cx + s * 0.06, s * 0.4))
        p.drawLine(QPointF(cx - s * 0.06, s * 0.4),
                    QPointF(cx + s * 0.06, s * 0.55))
    return _make_icon(draw, size)


def icon_drill_mill(size=24):
    """Perçage par fraisage."""
    def draw(p, s):
        c = _colors()
        pen = QPen(QColor(c['blue']), 1.5)
        p.setPen(pen)
        cx = s * 0.5
        # Shaft
        p.drawLine(QPointF(cx, s * 0.15), QPointF(cx, s * 0.55))
        # Helix indication
        p.setPen(QPen(QColor(c['teal']), 1.0))
        path = QPainterPath()
        path.moveTo(cx - s * 0.12, s * 0.7)
        path.cubicTo(cx - s * 0.12, s * 0.6,
                      cx + s * 0.12, s * 0.6,
                      cx + s * 0.12, s * 0.7)
        path.cubicTo(cx + s * 0.12, s * 0.8,
                      cx - s * 0.12, s * 0.8,
                      cx - s * 0.12, s * 0.7)
        p.drawPath(path)
    return _make_icon(draw, size)


def icon_tap(size=24):
    """Taraudage."""
    def draw(p, s):
        c = _colors()
        pen = QPen(QColor(c['purple']), 1.5)
        p.setPen(pen)
        cx = s * 0.5
        # Shaft
        p.drawLine(QPointF(cx, s * 0.12), QPointF(cx, s * 0.85))
        # Thread marks
        p.setPen(QPen(QColor(c['purple']), 0.8))
        for y_frac in [0.35, 0.47, 0.59, 0.71]:
            y = s * y_frac
            p.drawLine(QPointF(cx - s * 0.08, y),
                        QPointF(cx + s * 0.08, y))
    return _make_icon(draw, size)


def icon_helix(size=24):
    """Hélice."""
    def draw(p, s):
        c = _colors()
        p.setPen(QPen(QColor(c['teal']), 1.5))
        cx, cy = s * 0.5, s * 0.5
        r = s * 0.3
        path = QPainterPath()
        path.moveTo(cx + r, cy)
        # Spiral
        import math
        steps = 24
        for i in range(1, steps + 1):
            angle = i * 2 * math.pi * 1.5 / steps
            rr = r * (1 - i / (steps * 3))
            path.lineTo(cx + rr * math.cos(angle),
                         cy - rr * math.sin(angle))
        p.drawPath(path)
    return _make_icon(draw, size)


def icon_surface(size=24):
    """Surfaçage."""
    def draw(p, s):
        c = _colors()
        p.setPen(QPen(QColor(c['green']), 1.5))
        m = s * 0.2
        # Zigzag passes
        y_positions = [s * 0.3, s * 0.45, s * 0.6, s * 0.75]
        for i, y in enumerate(y_positions):
            if i % 2 == 0:
                p.drawLine(QPointF(m, y), QPointF(s - m, y))
            else:
                p.drawLine(QPointF(s - m, y), QPointF(m, y))
            if i < len(y_positions) - 1:
                nx = (s - m) if i % 2 == 0 else m
                p.drawLine(QPointF(nx, y), QPointF(nx, y_positions[i + 1]))
    return _make_icon(draw, size)


def icon_pocket(size=24):
    """Poche."""
    def draw(p, s):
        c = _colors()
        p.setPen(QPen(QColor(c['orange']), 1.5))
        # Rectangle outline
        m = s * 0.2
        p.drawRect(QRectF(m, m, s * 0.6, s * 0.6))
        # Inner spiral pass lines
        p.setPen(QPen(QColor(c['orange']), 0.8))
        m2 = s * 0.3
        p.drawRect(QRectF(m2, m2, s * 0.4, s * 0.4))
        m3 = s * 0.4
        p.drawRect(QRectF(m3, m3, s * 0.2, s * 0.2))
    return _make_icon(draw, size)


def icon_cut_circle(size=24):
    """Découpe cercle."""
    def draw(p, s):
        c = _colors()
        p.setPen(QPen(QColor(c['red']), 1.5))
        cx, cy = s * 0.5, s * 0.5
        r = s * 0.3
        p.drawEllipse(QPointF(cx, cy), r, r)
        # Arrow on circle
        p.setPen(QPen(QColor(c['red']), 1.0))
        ax = cx + r * 0.7
        ay = cy - r * 0.7
        p.drawLine(QPointF(ax, ay), QPointF(ax + s * 0.05, ay + s * 0.08))
        p.drawLine(QPointF(ax, ay), QPointF(ax - s * 0.07, ay + s * 0.02))
    return _make_icon(draw, size)


def icon_cut_rect(size=24):
    """Découpe rectangle."""
    def draw(p, s):
        c = _colors()
        p.setPen(QPen(QColor(c['red']), 1.5))
        m = s * 0.22
        p.drawRect(QRectF(m, m, s * 0.56, s * 0.56))
    return _make_icon(draw, size)


def icon_engrave(size=24):
    """Gravure texte."""
    def draw(p, s):
        c = _colors()
        font = QFont("Arial", int(s * 0.4), QFont.Weight.Bold)
        p.setFont(font)
        p.setPen(QPen(QColor(c['yellow']), 1.0))
        p.drawText(QRectF(0, 0, s, s), Qt.AlignmentFlag.AlignCenter, "A")
    return _make_icon(draw, size)


def icon_bpm(size=24):
    """BPM — multi-opération."""
    def draw(p, s):
        c = _colors()
        p.setPen(QPen(QColor(c['teal']), 1.2))
        # 3 dots in triangle
        for cx, cy in [(s * 0.5, s * 0.25),
                         (s * 0.3, s * 0.65),
                         (s * 0.7, s * 0.65)]:
            p.setBrush(QBrush(QColor(c['teal'])))
            p.drawEllipse(QPointF(cx, cy), s * 0.06, s * 0.06)
        # Connecting lines
        p.setPen(QPen(QColor(c['teal']), 0.8))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(s * 0.5, s * 0.3),
                    QPointF(s * 0.32, s * 0.6))
        p.drawLine(QPointF(s * 0.5, s * 0.3),
                    QPointF(s * 0.68, s * 0.6))
        p.drawLine(QPointF(s * 0.35, s * 0.65),
                    QPointF(s * 0.65, s * 0.65))
    return _make_icon(draw, size)


# ══════════════════════════════════════════════════════
#  Actions UI
# ══════════════════════════════════════════════════════

def icon_add(size=24):
    """Plus — ajouter."""
    def draw(p, s):
        c = _colors()
        p.setPen(QPen(QColor(c['green']), 2.0))
        cx, cy = s * 0.5, s * 0.5
        r = s * 0.25
        p.drawLine(QPointF(cx - r, cy), QPointF(cx + r, cy))
        p.drawLine(QPointF(cx, cy - r), QPointF(cx, cy + r))
    return _make_icon(draw, size)


def icon_delete(size=24, color_override=None):
    """Corbeille — supprimer."""
    def draw(p, s):
        c = _colors()
        clr = QColor(color_override) if color_override else QColor(c['bg'])
        p.setPen(QPen(clr, 1.5))
        # Lid
        p.drawLine(QPointF(s * 0.25, s * 0.3), QPointF(s * 0.75, s * 0.3))
        p.drawLine(QPointF(s * 0.4, s * 0.2), QPointF(s * 0.6, s * 0.2))
        p.drawLine(QPointF(s * 0.4, s * 0.2), QPointF(s * 0.4, s * 0.3))
        p.drawLine(QPointF(s * 0.6, s * 0.2), QPointF(s * 0.6, s * 0.3))
        # Body
        p.drawLine(QPointF(s * 0.3, s * 0.3), QPointF(s * 0.32, s * 0.82))
        p.drawLine(QPointF(s * 0.32, s * 0.82), QPointF(s * 0.68, s * 0.82))
        p.drawLine(QPointF(s * 0.7, s * 0.3), QPointF(s * 0.68, s * 0.82))
        # Ribs
        for x in [0.42, 0.5, 0.58]:
            p.drawLine(QPointF(s * x, s * 0.38),
                        QPointF(s * x, s * 0.75))
    return _make_icon(draw, size)


def icon_duplicate(size=24):
    """Dupliquer."""
    def draw(p, s):
        c = _colors()
        p.setPen(QPen(QColor(c['accent']), 1.2))
        # Back rect
        p.drawRect(QRectF(s * 0.3, s * 0.15, s * 0.5, s * 0.5))
        # Front rect
        p.setPen(QPen(QColor(c['green']), 1.5))
        p.setBrush(QBrush(QColor(c['bg'])))
        p.drawRect(QRectF(s * 0.15, s * 0.3, s * 0.5, s * 0.5))
    return _make_icon(draw, size)


def icon_up_arrow(size=24):
    """Flèche haut — monter."""
    def draw(p, s):
        c = _colors()
        p.setPen(QPen(QColor(c['accent']), 1.8))
        cx = s * 0.5
        p.drawLine(QPointF(cx, s * 0.2), QPointF(cx, s * 0.8))
        p.drawLine(QPointF(cx, s * 0.2), QPointF(s * 0.3, s * 0.4))
        p.drawLine(QPointF(cx, s * 0.2), QPointF(s * 0.7, s * 0.4))
    return _make_icon(draw, size)


def icon_down_arrow(size=24):
    """Flèche bas — descendre."""
    def draw(p, s):
        c = _colors()
        p.setPen(QPen(QColor(c['accent']), 1.8))
        cx = s * 0.5
        p.drawLine(QPointF(cx, s * 0.8), QPointF(cx, s * 0.2))
        p.drawLine(QPointF(cx, s * 0.8), QPointF(s * 0.3, s * 0.6))
        p.drawLine(QPointF(cx, s * 0.8), QPointF(s * 0.7, s * 0.6))
    return _make_icon(draw, size)


def icon_settings(size=24):
    """Engrenage — paramètres."""
    def draw(p, s):
        import math
        c = _colors()
        p.setPen(QPen(QColor(c['accent']), 1.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        cx, cy = s * 0.5, s * 0.5
        # Inner circle
        p.drawEllipse(QPointF(cx, cy), s * 0.1, s * 0.1)
        # Gear teeth
        teeth = 8
        r_inner, r_outer = s * 0.2, s * 0.32
        for i in range(teeth):
            a1 = math.radians(i * 360 / teeth - 10)
            a2 = math.radians(i * 360 / teeth + 10)
            p.drawLine(
                QPointF(cx + r_inner * math.cos(a1),
                         cy - r_inner * math.sin(a1)),
                QPointF(cx + r_outer * math.cos(a1),
                         cy - r_outer * math.sin(a1)))
            p.drawLine(
                QPointF(cx + r_outer * math.cos(a1),
                         cy - r_outer * math.sin(a1)),
                QPointF(cx + r_outer * math.cos(a2),
                         cy - r_outer * math.sin(a2)))
            p.drawLine(
                QPointF(cx + r_outer * math.cos(a2),
                         cy - r_outer * math.sin(a2)),
                QPointF(cx + r_inner * math.cos(a2),
                         cy - r_inner * math.sin(a2)))
    return _make_icon(draw, size)


def icon_tool(size=24):
    """Outil / clé."""
    def draw(p, s):
        c = _colors()
        p.setPen(QPen(QColor(c['yellow']), 1.5))
        # Wrench shape simplified
        p.drawLine(QPointF(s * 0.25, s * 0.75),
                    QPointF(s * 0.55, s * 0.45))
        p.drawEllipse(QPointF(s * 0.65, s * 0.35), s * 0.12, s * 0.12)
    return _make_icon(draw, size)


def icon_toolbox(size=24):
    """Caisse à outils — programmes outils externes."""
    def draw(p, s):
        c = _colors()
        p.setPen(QPen(QColor(c['teal']), 1.6))
        # Corps de la caisse
        p.drawRect(QRectF(s * 0.16, s * 0.42, s * 0.68, s * 0.38))
        # Poignée
        p.drawLine(QPointF(s * 0.38, s * 0.42),
                   QPointF(s * 0.42, s * 0.26))
        p.drawLine(QPointF(s * 0.62, s * 0.42),
                   QPointF(s * 0.58, s * 0.26))
        p.drawLine(QPointF(s * 0.42, s * 0.26),
                   QPointF(s * 0.58, s * 0.26))
        # Fermoir
        p.drawLine(QPointF(s * 0.16, s * 0.58),
                   QPointF(s * 0.84, s * 0.58))
    return _make_icon(draw, size)


def icon_optimize(size=24):
    """Optimiser — flèches circulation."""
    def draw(p, s):
        c = _colors()
        p.setPen(QPen(QColor(c['green']), 1.5))
        # Circular arrows
        import math
        cx, cy = s * 0.5, s * 0.5
        r = s * 0.28
        path = QPainterPath()
        path.moveTo(cx + r, cy)
        steps = 16
        for i in range(1, steps):
            a = i * 2 * math.pi * 0.75 / steps
            path.lineTo(cx + r * math.cos(a), cy - r * math.sin(a))
        p.drawPath(path)
        # Arrow head
        end_x = cx + r * math.cos(2 * math.pi * 0.75)
        end_y = cy - r * math.sin(2 * math.pi * 0.75)
        p.drawLine(QPointF(end_x, end_y),
                    QPointF(end_x + s * 0.08, end_y + s * 0.02))
        p.drawLine(QPointF(end_x, end_y),
                    QPointF(end_x + s * 0.02, end_y - s * 0.08))
    return _make_icon(draw, size)


def icon_pattern(size=24):
    """Pattern — grille de points."""
    def draw(p, s):
        c = _colors()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(c['orange'])))
        r = s * 0.04
        for ix in range(3):
            for iy in range(3):
                cx = s * (0.25 + ix * 0.25)
                cy = s * (0.25 + iy * 0.25)
                p.drawEllipse(QPointF(cx, cy), r, r)
    return _make_icon(draw, size)


def icon_dxf(size=24):
    """DXF — dessin technique."""
    def draw(p, s):
        c = _colors()
        p.setPen(QPen(QColor(c['teal']), 1.2))
        # Simple blueprint-style drawing
        m = s * 0.2
        p.drawRect(QRectF(m, m, s * 0.6, s * 0.6))
        # Dimension line
        p.setPen(QPen(QColor(c['yellow']), 0.8))
        y = s * 0.85
        p.drawLine(QPointF(m, y), QPointF(s - m, y))
        p.drawLine(QPointF(m, y - s * 0.04), QPointF(m, y + s * 0.04))
        p.drawLine(QPointF(s - m, y - s * 0.04),
                    QPointF(s - m, y + s * 0.04))
    return _make_icon(draw, size)


def icon_pick_point(size=24):
    """Cible — pick point."""
    def draw(p, s):
        c = _colors()
        p.setPen(QPen(QColor(c['accent']), 1.2))
        cx, cy = s * 0.5, s * 0.5
        r1, r2 = s * 0.3, s * 0.15
        p.drawEllipse(QPointF(cx, cy), r1, r1)
        p.drawEllipse(QPointF(cx, cy), r2, r2)
        # Crosshair
        p.drawLine(QPointF(cx, cy - r1 - s * 0.05),
                    QPointF(cx, cy + r1 + s * 0.05))
        p.drawLine(QPointF(cx - r1 - s * 0.05, cy),
                    QPointF(cx + r1 + s * 0.05, cy))
    return _make_icon(draw, size)


def icon_ruler(size=24):
    """Règle — mesure."""
    def draw(p, s):
        c = _colors()
        p.setPen(QPen(QColor(c['yellow']), 1.2))
        # Diagonal ruler
        p.drawLine(QPointF(s * 0.15, s * 0.85),
                    QPointF(s * 0.85, s * 0.15))
        # Tick marks
        dx, dy = 0.7 / 5, -0.7 / 5
        for i in range(1, 5):
            x = s * (0.15 + i * dx)
            y = s * (0.85 + i * dy)
            ticklen = s * 0.06 if i % 2 == 0 else s * 0.04
            p.drawLine(QPointF(x - ticklen * 0.707, y - ticklen * 0.707),
                        QPointF(x + ticklen * 0.707, y + ticklen * 0.707))
    return _make_icon(draw, size)


def icon_snap(size=24):
    """Snap — aimant."""
    def draw(p, s):
        c = _colors()
        p.setPen(QPen(QColor(c['accent']), 1.5))
        # U-shape magnet
        path = QPainterPath()
        path.moveTo(s * 0.25, s * 0.25)
        path.lineTo(s * 0.25, s * 0.6)
        path.cubicTo(s * 0.25, s * 0.85, s * 0.75, s * 0.85,
                      s * 0.75, s * 0.6)
        path.lineTo(s * 0.75, s * 0.25)
        p.drawPath(path)
        # Poles
        p.setPen(QPen(QColor(c['red']), 2.0))
        p.drawLine(QPointF(s * 0.2, s * 0.25), QPointF(s * 0.3, s * 0.25))
        p.setPen(QPen(QColor(c['blue']), 2.0))
        p.drawLine(QPointF(s * 0.7, s * 0.25), QPointF(s * 0.8, s * 0.25))
    return _make_icon(draw, size)


def icon_zoom_fit(size=24):
    """Zoom fit — cadrer."""
    def draw(p, s):
        c = _colors()
        p.setPen(QPen(QColor(c['accent']), 1.2))
        m = s * 0.15
        e = s * 0.85
        L = s * 0.2
        # Corners
        for x, y, dx, dy in [
            (m, m, L, 0), (m, m, 0, L),       # top-left
            (e, m, -L, 0), (e, m, 0, L),       # top-right
            (m, e, L, 0), (m, e, 0, -L),       # bottom-left
            (e, e, -L, 0), (e, e, 0, -L),      # bottom-right
        ]:
            p.drawLine(QPointF(x, y), QPointF(x + dx, y + dy))
    return _make_icon(draw, size)


def icon_grid(size=24):
    """Grille."""
    def draw(p, s):
        c = _colors()
        p.setPen(QPen(QColor(c['text_dim']), 0.8))
        # 3x3 grid
        m = s * 0.2
        e = s * 0.8
        step = (e - m) / 3
        for i in range(4):
            v = m + i * step
            p.drawLine(QPointF(v, m), QPointF(v, e))
            p.drawLine(QPointF(m, v), QPointF(e, v))
    return _make_icon(draw, size)


def icon_eye(size=24):
    """Œil — visibilité."""
    def draw(p, s):
        c = _colors()
        p.setPen(QPen(QColor(c['accent']), 1.2))
        cx, cy = s * 0.5, s * 0.5
        # Eye shape
        path = QPainterPath()
        path.moveTo(s * 0.1, cy)
        path.cubicTo(s * 0.25, s * 0.25, s * 0.75, s * 0.25, s * 0.9, cy)
        path.cubicTo(s * 0.75, s * 0.75, s * 0.25, s * 0.75, s * 0.1, cy)
        p.drawPath(path)
        # Iris
        p.drawEllipse(QPointF(cx, cy), s * 0.1, s * 0.1)
    return _make_icon(draw, size)


def icon_play(size=24):
    """Lecture — un triangle plein (le « ▶ » en texte n'existe pas
    dans toutes les polices: l'exe montrait un bouton vide)."""
    def draw(p, s):
        c = _colors()
        p.setPen(QPen(QColor(c['accent']), 1.0))
        p.setBrush(QColor(c['accent']))
        path = QPainterPath()
        path.moveTo(s * 0.3, s * 0.2)
        path.lineTo(s * 0.82, s * 0.5)
        path.lineTo(s * 0.3, s * 0.8)
        path.closeSubpath()
        p.drawPath(path)
    return _make_icon(draw, size)


def _chevron(size, vers_gauche: bool):
    def draw(p, s):
        c = _colors()
        p.setPen(QPen(QColor(c['text']), max(1.5, s * 0.1)))
        p.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath()
        if vers_gauche:
            path.moveTo(s * 0.62, s * 0.2)
            path.lineTo(s * 0.35, s * 0.5)
            path.lineTo(s * 0.62, s * 0.8)
        else:
            path.moveTo(s * 0.38, s * 0.2)
            path.lineTo(s * 0.65, s * 0.5)
            path.lineTo(s * 0.38, s * 0.8)
        p.drawPath(path)
    return _make_icon(draw, size)


def icon_precedent(size=24):
    """Chevron vers la gauche (image précédente)."""
    return _chevron(size, True)


def icon_suivant(size=24):
    """Chevron vers la droite (image suivante)."""
    return _chevron(size, False)


def icon_pause(size=24):
    """Pause — deux barres pleines."""
    def draw(p, s):
        c = _colors()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(c['accent']))
        p.drawRect(QRectF(s * 0.28, s * 0.2, s * 0.15, s * 0.6))
        p.drawRect(QRectF(s * 0.57, s * 0.2, s * 0.15, s * 0.6))
    return _make_icon(draw, size)


def icon_undo(size=24):
    """Annuler."""
    def draw(p, s):
        c = _colors()
        p.setPen(QPen(QColor(c['accent']), 1.5))
        # Curved arrow left
        import math
        cx, cy = s * 0.55, s * 0.5
        r = s * 0.25
        path = QPainterPath()
        path.moveTo(cx + r, cy + s * 0.05)
        for i in range(1, 13):
            a = i * math.pi / 12
            path.lineTo(cx + r * math.cos(a), cy - r * math.sin(a) + s * 0.05)
        p.drawPath(path)
        # Arrow head
        p.drawLine(QPointF(cx - r, cy + s * 0.05),
                    QPointF(cx - r + s * 0.1, cy - s * 0.05))
        p.drawLine(QPointF(cx - r, cy + s * 0.05),
                    QPointF(cx - r + s * 0.1, cy + s * 0.15))
    return _make_icon(draw, size)


def icon_redo(size=24):
    """Rétablir."""
    def draw(p, s):
        c = _colors()
        p.setPen(QPen(QColor(c['accent']), 1.5))
        import math
        cx, cy = s * 0.45, s * 0.5
        r = s * 0.25
        path = QPainterPath()
        path.moveTo(cx - r, cy + s * 0.05)
        for i in range(1, 13):
            a = math.pi - i * math.pi / 12
            path.lineTo(cx + r * math.cos(a), cy - r * math.sin(a) + s * 0.05)
        p.drawPath(path)
        # Arrow head
        p.drawLine(QPointF(cx + r, cy + s * 0.05),
                    QPointF(cx + r - s * 0.1, cy - s * 0.05))
        p.drawLine(QPointF(cx + r, cy + s * 0.05),
                    QPointF(cx + r - s * 0.1, cy + s * 0.15))
    return _make_icon(draw, size)


def icon_dialogue(size=24):
    """Bulle de dialogue — style BD."""
    def draw(p, s):
        c = _colors()
        p.setPen(QPen(QColor(c['accent']), 1.3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        # Bulle arrondie
        path = QPainterPath()
        bx, by = s * 0.12, s * 0.12
        bw, bh = s * 0.76, s * 0.52
        path.addRoundedRect(QRectF(bx, by, bw, bh), s * 0.1, s * 0.1)
        p.drawPath(path)
        # Queue de la bulle (triangle)
        tail = QPainterPath()
        tail.moveTo(s * 0.25, by + bh)
        tail.lineTo(s * 0.2, s * 0.85)
        tail.lineTo(s * 0.42, by + bh)
        p.drawPath(tail)
        # Points de suspension
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(c['accent'])))
        dot_r = s * 0.03
        for dx in [0.32, 0.5, 0.68]:
            p.drawEllipse(QPointF(s * dx, by + bh * 0.5), dot_r, dot_r)
    return _make_icon(draw, size)


def icon_csv(size=24):
    """Import CSV."""
    def draw(p, s):
        c = _colors()
        font = QFont("Arial", int(s * 0.22), QFont.Weight.Bold)
        p.setFont(font)
        p.setPen(QPen(QColor(c['green']), 1.0))
        p.drawText(QRectF(0, s * 0.1, s, s * 0.4),
                    Qt.AlignmentFlag.AlignCenter, "CSV")
        # Arrow down
        cx = s * 0.5
        p.setPen(QPen(QColor(c['accent']), 1.5))
        p.drawLine(QPointF(cx, s * 0.55), QPointF(cx, s * 0.8))
        p.drawLine(QPointF(cx, s * 0.8), QPointF(cx - s * 0.1, s * 0.7))
        p.drawLine(QPointF(cx, s * 0.8), QPointF(cx + s * 0.1, s * 0.7))
    return _make_icon(draw, size)


def icon_external(size=24):
    """Appel programme externe."""
    def draw(p, s):
        c = _colors()
        p.setPen(QPen(QColor(c['accent']), 1.2))
        # Window frame
        m = s * 0.18
        p.drawRect(QRectF(m, m, s * 0.5, s * 0.45))
        # Arrow out
        p.setPen(QPen(QColor(c['green']), 1.5))
        p.drawLine(QPointF(s * 0.55, s * 0.55),
                    QPointF(s * 0.82, s * 0.82))
        p.drawLine(QPointF(s * 0.82, s * 0.82),
                    QPointF(s * 0.82, s * 0.65))
        p.drawLine(QPointF(s * 0.82, s * 0.82),
                    QPointF(s * 0.65, s * 0.82))
    return _make_icon(draw, size)


def icon_shift(size=24):
    """Décalage — cible avec axes."""
    def draw(p, s):
        c = _colors()
        cx, cy = s * 0.5, s * 0.5
        r1, r2 = s * 0.3, s * 0.15
        # Cercles concentriques
        p.setPen(QPen(QColor(c['accent']), 1.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), r1, r1)
        p.drawEllipse(QPointF(cx, cy), r2, r2)
        # Axes (croix)
        p.setPen(QPen(QColor(c['yellow']), 1.0))
        ext = s * 0.38
        p.drawLine(QPointF(cx - ext, cy), QPointF(cx + ext, cy))
        p.drawLine(QPointF(cx, cy - ext), QPointF(cx, cy + ext))
        # Pointes de flèche
        ar = s * 0.06
        for dx, dy in [(ext, 0), (-ext, 0), (0, -ext), (0, ext)]:
            ex, ey = cx + dx, cy + dy
            if dx > 0:
                p.drawLine(QPointF(ex, ey), QPointF(ex - ar, ey - ar))
                p.drawLine(QPointF(ex, ey), QPointF(ex - ar, ey + ar))
            elif dx < 0:
                p.drawLine(QPointF(ex, ey), QPointF(ex + ar, ey - ar))
                p.drawLine(QPointF(ex, ey), QPointF(ex + ar, ey + ar))
            elif dy < 0:
                p.drawLine(QPointF(ex, ey), QPointF(ex - ar, ey + ar))
                p.drawLine(QPointF(ex, ey), QPointF(ex + ar, ey + ar))
            elif dy > 0:
                p.drawLine(QPointF(ex, ey), QPointF(ex - ar, ey - ar))
                p.drawLine(QPointF(ex, ey), QPointF(ex + ar, ey - ar))
    return _make_icon(draw, size)



def icon_fold(size=24):
    """Pliage: deux chevrons qui se rapprochent."""
    def draw(p, s):
        c = _colors()
        p.setPen(QPen(QColor(c['accent']), 1.6))
        p.drawLine(QPointF(s * 0.25, s * 0.32), QPointF(s * 0.5, s * 0.45))
        p.drawLine(QPointF(s * 0.75, s * 0.32), QPointF(s * 0.5, s * 0.45))
        p.drawLine(QPointF(s * 0.25, s * 0.72), QPointF(s * 0.5, s * 0.58))
        p.drawLine(QPointF(s * 0.75, s * 0.72), QPointF(s * 0.5, s * 0.58))
        p.setPen(QPen(QColor(c['text_dim']), 1.0))
        p.drawLine(QPointF(s * 0.18, s * 0.5), QPointF(s * 0.82, s * 0.5))
    return _make_icon(draw, size)


def icon_copy(size=24):
    """Copier: une feuille derriere l'autre."""
    def draw(p, s):
        c = _colors()
        p.setPen(QPen(QColor(c['text_dim']), 1.2))
        p.drawRect(QRectF(s * 0.32, s * 0.16, s * 0.46, s * 0.52))
        p.setPen(QPen(QColor(c['accent']), 1.5))
        p.setBrush(QBrush(QColor(c['bg'])))
        p.drawRect(QRectF(s * 0.18, s * 0.3, s * 0.46, s * 0.52))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(c['text_dim']), 1.0))
        for i in range(3):
            y = s * (0.42 + i * 0.12)
            p.drawLine(QPointF(s * 0.26, y), QPointF(s * 0.56, y))
    return _make_icon(draw, size)


def icon_history(size=24):
    """Historique: horloge avec fleche de retour."""
    def draw(p, s):
        c = _colors()
        p.setPen(QPen(QColor(c['accent']), 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(s * 0.18, s * 0.18, s * 0.64, s * 0.64),
                  30 * 16, 300 * 16)
        # fleche de rembobinage
        p.drawLine(QPointF(s * 0.5, s * 0.16), QPointF(s * 0.34, s * 0.24))
        p.drawLine(QPointF(s * 0.5, s * 0.16), QPointF(s * 0.5, s * 0.3))
        # aiguilles
        p.setPen(QPen(QColor(c['text']), 1.4))
        p.drawLine(QPointF(s * 0.5, s * 0.5), QPointF(s * 0.5, s * 0.32))
        p.drawLine(QPointF(s * 0.5, s * 0.5), QPointF(s * 0.66, s * 0.58))
    return _make_icon(draw, size)


def icon_help(size=24):
    """Aide: point d'interrogation cercle."""
    def draw(p, s):
        c = _colors()
        p.setPen(QPen(QColor(c['accent']), 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(s * 0.14, s * 0.14, s * 0.72, s * 0.72))
        p.setPen(QPen(QColor(c['text']), 1.6))
        p.drawArc(QRectF(s * 0.34, s * 0.26, s * 0.32, s * 0.3),
                  200 * 16, -230 * 16)
        p.drawLine(QPointF(s * 0.5, s * 0.52), QPointF(s * 0.5, s * 0.62))
        p.setBrush(QBrush(QColor(c['text'])))
        p.drawEllipse(QPointF(s * 0.5, s * 0.73), s * 0.05, s * 0.05)
    return _make_icon(draw, size)


def icon_material(size=24):
    """Matiere: bloc de brut."""
    def draw(p, s):
        c = _colors()
        p.setPen(QPen(QColor(c['accent']), 1.3))
        p.setBrush(QBrush(QColor(c['bg'])))
        p.drawRect(QRectF(s * 0.2, s * 0.34, s * 0.46, s * 0.42))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(s * 0.2, s * 0.34), QPointF(s * 0.36, s * 0.2))
        p.drawLine(QPointF(s * 0.66, s * 0.34), QPointF(s * 0.82, s * 0.2))
        p.drawLine(QPointF(s * 0.36, s * 0.2), QPointF(s * 0.82, s * 0.2))
        p.drawLine(QPointF(s * 0.82, s * 0.2), QPointF(s * 0.82, s * 0.62))
        p.drawLine(QPointF(s * 0.66, s * 0.76), QPointF(s * 0.82, s * 0.62))
    return _make_icon(draw, size)


def icon_nds(size=24):
    """Sous-programme NDS: fiche avec un rouage."""
    def draw(p, s):
        c = _colors()
        p.setPen(QPen(QColor(c['accent']), 1.3))
        p.setBrush(QBrush(QColor(c['bg'])))
        p.drawRect(QRectF(s * 0.2, s * 0.16, s * 0.5, s * 0.68))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(c['text_dim']), 1.0))
        for i in range(3):
            y = s * (0.3 + i * 0.14)
            p.drawLine(QPointF(s * 0.28, y), QPointF(s * 0.6, y))
        p.setPen(QPen(QColor(c['green']), 1.5))
        p.drawEllipse(QPointF(s * 0.68, s * 0.7), s * 0.15, s * 0.15)
    return _make_icon(draw, size)


# ══════════════════════════════════════════════════════
#  Registre global — permet d'obtenir n'importe quelle icône par nom
# ══════════════════════════════════════════════════════

_ICON_REGISTRY = {
    # Fichiers
    "new_file": icon_new_file,
    "open_file": icon_open_file,
    "save": icon_save,
    "export": icon_export,
    "import": icon_import,
    # Opérations CNC
    "drill": icon_drill,
    "drill_mill": icon_drill_mill,
    "tap": icon_tap,
    "helix": icon_helix,
    "surface": icon_surface,
    "pocket": icon_pocket,
    "cut_circle": icon_cut_circle,
    "cut_rect": icon_cut_rect,
    "engrave": icon_engrave,
    "bpm": icon_bpm,
    "external": icon_external,
    "shift": icon_shift,
    # Actions UI
    "add": icon_add,
    "delete": icon_delete,
    "duplicate": icon_duplicate,
    "up": icon_up_arrow,
    "down": icon_down_arrow,
    "settings": icon_settings,
    "tool": icon_tool,
    "toolbox": icon_toolbox,
    "optimize": icon_optimize,
    "pattern": icon_pattern,
    "dxf": icon_dxf,
    "pick_point": icon_pick_point,
    "ruler": icon_ruler,
    "snap": icon_snap,
    "zoom_fit": icon_zoom_fit,
    "grid": icon_grid,
    "eye": icon_eye,
    "play": icon_play,
    "precedent": icon_precedent,
    "suivant": icon_suivant,
    "pause": icon_pause,
    "undo": icon_undo,
    "redo": icon_redo,
    "csv": icon_csv,
    "dialogue": icon_dialogue,
    "fold": icon_fold,
    "copy": icon_copy,
    "history": icon_history,
    "help": icon_help,
    "material": icon_material,
    "nds": icon_nds,
}

# Mapping noms d'opérations → noms d'icônes
OP_ICON_MAP = {
    "percage_foret": "drill",
    "percage_fraise": "drill_mill",
    "taraudage": "tap",
    "taraudage_brut": "tap",
    "filetage_special": "tap",
    "taraudage_rigide": "tap",
    "mouvement": "shift",
    "helice": "helix",
    "surfacage_rectangle": "surface",
    "surfacage_cercle": "surface",
    "poche_rectangle": "pocket",
    "poche_cercle": "pocket",
    "rotation_repere": "shift",
    "palpage_coin": "ruler",
    "message_operateur": "dialogue",
    "mesure_outil": "ruler",
    "decoupe_cercle": "cut_circle",
    "decoupe_rectangle": "cut_rect",
    "gravure_texte": "engrave",
    "bpm": "bpm",
    "appel_programme": "external",
    "decalage_origine": "shift",
    "dialogue_operateur": "dialogue",
}


def _tint(icon: QIcon, size: int, color: str) -> QIcon:
    """Recolore une icône en conservant sa forme (alpha)."""
    src = icon.pixmap(size, size)
    if src.isNull():
        return icon
    out = QPixmap(src.size())
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.drawPixmap(0, 0, src)
    p.setCompositionMode(
        QPainter.CompositionMode.CompositionMode_SourceIn)
    p.fillRect(out.rect(), QColor(color))
    p.end()
    return QIcon(out)


#: icônes déjà peintes, par (nom, taille, teinte, thème)
_CACHE_ICONES = {}


def vider_cache_icones():
    """À appeler quand le thème change: les couleurs sont figées
    dans les pixmaps."""
    _CACHE_ICONES.clear()


def get_icon(name: str, size: int = 24, color: str = "") -> QIcon:
    """Retourne l'icône thème-aware par nom.

    color: teinte forcée (sinon couleurs natives de l'icône).

    Le résultat est mis en CACHE: chaque icône est un QPixmap peint
    trait par trait, et une liste de trente opérations les repeignait
    toutes à chaque reconstruction.

    Usage:
        icon = get_icon("drill", 20)
        button.setIcon(icon)
    """
    fn = _ICON_REGISTRY.get(name)
    if not fn:
        return QIcon()  # fallback vide
    cle = (name, size, color, get_current_theme())
    icone = _CACHE_ICONES.get(cle)
    if icone is None:
        icone = fn(size)
        if color:
            icone = _tint(icone, size, color)
        _CACHE_ICONES[cle] = icone
    return icone


def get_button_icon(name: str, size: int = 24,
                    on_accent: bool = False) -> QIcon:
    """Icône lisible SUR UN BOUTON, dans tous les thèmes.

    Les boutons primary/danger ont un fond accent/rouge et un texte
    couleur `bg`; une icône dessinée en `accent` y était invisible.
    on_accent=True force la teinte du texte de ces boutons, sinon on
    prend la couleur de texte normale.
    """
    c = _colors()
    return get_icon(name, size, c['bg'] if on_accent else c['text'])


def get_op_icon(op_type: str, size: int = 20) -> QIcon:
    """Retourne l'icône pour un type d'opération."""
    icon_name = OP_ICON_MAP.get(op_type, "settings")
    return get_icon(icon_name, size)
