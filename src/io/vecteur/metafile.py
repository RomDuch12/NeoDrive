"""Lecture des métafichiers Windows: EMF, WMF (et leurs versions
compressées EMZ, WMZ).

Un logo copié depuis Word ou PowerPoint, un dessin exporté de
CorelDRAW en « métafichier », un pictogramme d'une bibliothèque de
clip-arts: ce sont des EMF ou des WMF. On en lit les TRACÉS — lignes,
polylignes, polygones, Béziers (gardées en courbes), rectangles,
ellipses, arcs, et les chemins (BeginPath … FillPath/StrokePath) —, en
millimètres, Y vers le haut, sous le calque « dessin ». Les textes ne
sont pas lus (comptés dans le rapport), ni les images.

La liste des enregistrements suit la spécification publique de
Microsoft ([MS-EMF], [MS-WMF]); l'idée vient du lecteur de
métafichiers de VectorCraft (crate metafile, © 2026 ArtCraft Team and
the VectorCraft contributors, licence MIT — voir
THIRD_PARTY_NOTICES.md), réécrit ici en Python.

Unités:
- EMF: coordonnées logiques → transformation du monde → page
  (fenêtre/vue selon le mode de projection) → pixels du périphérique
  de référence → mm (szlMillimeters / szlDevice de l'en-tête);
- WMF: avec l'en-tête « placeable », le cadre et ses unités par pouce
  donnent les mm; sans, 96 unités par pouce (noté au rapport).
"""
from __future__ import annotations

import gzip
import math
import pathlib
import struct
from typing import List, Optional, Tuple

from .dxfimport import Cancelled, DxfError, ImportReport
from .geometry import Chemin

SUFFIXES = ('.emf', '.wmf', '.emz', '.wmz')

#: kappa: les poignées d'un quart d'ellipse en Bézier cubique
_K = 0.5522847498

#: enregistrements EMF d'images (BitBlt, StretchDIBits…): non lus
_EMR_IMAGES = (76, 77, 78, 79, 80, 81, 114, 116, 118)

#: fonctions WMF d'images (BitBlt, StretchDIB…): non lues
_WMF_IMAGES = (0x0922, 0x0940, 0x0B23, 0x0B41, 0x0D33, 0x0F43)

#: mm par unité logique des modes de projection fixes (EMF)
_MODES_FIXES = {2: 0.1, 3: 0.01, 4: 0.254, 5: 0.0254, 6: 25.4 / 1440.0}


class MetafileError(DxfError):
    """Métafichier illisible."""


def _octets(chemin) -> bytes:
    raw = pathlib.Path(chemin).read_bytes()
    if raw[:2] == b'\x1f\x8b':                 # EMZ / WMZ
        raw = gzip.decompress(raw)
    return raw


def genre(raw: bytes) -> Optional[str]:
    """'emf', 'wmf' ou None."""
    if len(raw) >= 44 and struct.unpack_from('<I', raw, 0)[0] == 1 \
            and raw[40:44] == b' EMF':
        return 'emf'
    if len(raw) >= 4 and struct.unpack_from('<I', raw, 0)[0] == 0x9AC6CDD7:
        return 'wmf'
    if len(raw) >= 18 and struct.unpack_from('<H', raw, 0)[0] in (1, 2) \
            and struct.unpack_from('<H', raw, 2)[0] == 9:
        return 'wmf'
    return None


class _Traceur:
    """Accumule les figures (en mm, Y vers le haut) au fil des
    enregistrements, avec la position courante et les chemins."""

    def __init__(self, tolerance: float):
        self.tol = tolerance
        self.sortie: List[Chemin] = []
        self.en_chemin = False
        self.tampon: List[Chemin] = []
        self.figure: Optional[Chemin] = None
        self.courant = (0.0, 0.0)       # en mm

    def _poser(self, ch: Chemin) -> None:
        if len(ch) < 2:
            return
        (self.tampon if self.en_chemin else self.sortie).append(ch)

    def finir_figure(self) -> None:
        if self.figure is not None:
            self._poser(self.figure)
        self.figure = None

    def aller(self, p) -> None:
        self.finir_figure()
        self.courant = p

    def _figure(self) -> Chemin:
        if self.figure is None:
            self.figure = Chemin(tolerance=self.tol)
            self.figure.moveto(*self.courant)
        return self.figure

    def ligne(self, p) -> None:
        self._figure().lineto(*p)
        self.courant = p

    def bezier(self, c1, c2, p) -> None:
        self._figure().cubicto(c1, c2, p)
        self.courant = p

    def fermer(self) -> None:
        if self.figure is not None:
            self.figure.fermer()
            depart = self.figure.points[0]
            self.finir_figure()
            self.courant = depart

    def forme(self, ch: Chemin) -> None:
        """Une forme complète (polygone, ellipse…)."""
        self.finir_figure()
        self._poser(ch)

    def debut_chemin(self) -> None:
        self.finir_figure()
        self.en_chemin = True
        self.tampon = []

    def fin_chemin(self) -> None:
        self.finir_figure()
        self.en_chemin = False

    def rendre_chemin(self) -> None:
        """FillPath / StrokePath: le chemin enregistré est tracé."""
        self.finir_figure()
        self.sortie.extend(self.tampon)
        self.tampon = []

    def jeter_chemin(self) -> None:
        self.tampon = []

    def tout(self) -> List[Chemin]:
        self.finir_figure()
        return self.sortie


def _ellipse_bez(cx, cy, rx, ry, tol) -> Chemin:
    ch = Chemin(tolerance=tol)
    ch.moveto(cx + rx, cy)
    for k in range(4):
        a0 = k * math.pi / 2
        a1 = a0 + math.pi / 2
        p0 = (cx + rx * math.cos(a0), cy + ry * math.sin(a0))
        p3 = (cx + rx * math.cos(a1), cy + ry * math.sin(a1))
        c1 = (p0[0] - _K * rx * math.sin(a0), p0[1] + _K * ry * math.cos(a0))
        c2 = (p3[0] + _K * rx * math.sin(a1), p3[1] - _K * ry * math.cos(a1))
        ch.cubicto(c1, c2, p3)
    ch.fermer()
    return ch


def _arc_points(cx, cy, rx, ry, depart, arrivee, pas_mm: float):
    """Points d'un arc d'ellipse (repère mm, Y vers le haut), du
    rayon passant par `depart` à celui passant par `arrivee`, en sens
    TRIGONOMÉTRIQUE (l'AD_COUNTERCLOCKWISE de GDI, vu à l'écran)."""
    a0 = math.atan2((depart[1] - cy) / max(ry, 1e-12),
                    (depart[0] - cx) / max(rx, 1e-12))
    a1 = math.atan2((arrivee[1] - cy) / max(ry, 1e-12),
                    (arrivee[0] - cx) / max(rx, 1e-12))
    if a1 <= a0 + 1e-12:
        a1 += 2 * math.pi
    r = max(rx, ry, 1e-9)
    n = max(2, int(math.ceil((a1 - a0) * r / max(pas_mm, 1e-3))))
    n = min(n, 720)
    return [(cx + rx * math.cos(a0 + (a1 - a0) * k / n),
             cy + ry * math.sin(a0 + (a1 - a0) * k / n))
            for k in range(n + 1)]


# ── EMF ─────────────────────────────────────────────────────────────

class _EtatEMF:
    def __init__(self):
        self.mode = 1
        self.fen_org = (0.0, 0.0)
        self.fen_ext = (1.0, 1.0)
        self.vue_org = (0.0, 0.0)
        self.vue_ext = (1.0, 1.0)
        self.monde = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

    def copie(self):
        e = _EtatEMF()
        e.__dict__.update(self.__dict__)
        return e


def _composer(a, b):
    """Transformation `a` puis `b` (XFORM: m11, m12, m21, m22, dx, dy)."""
    a11, a12, a21, a22, adx, ady = a
    b11, b12, b21, b22, bdx, bdy = b
    return (a11 * b11 + a12 * b21, a11 * b12 + a12 * b22,
            a21 * b11 + a22 * b21, a21 * b12 + a22 * b22,
            adx * b11 + ady * b21 + bdx, adx * b12 + ady * b22 + bdy)


def lire_emf(raw: bytes, tolerance: float = 0.02, progress=None):
    """(chemins, rapport) d'un EMF."""
    rapport = ImportReport()
    if genre(raw) != 'emf':
        raise MetafileError("ce n'est pas un EMF")
    dev = struct.unpack_from('<2i', raw, 72)
    mm = struct.unpack_from('<2i', raw, 80)
    taille_entete = struct.unpack_from('<I', raw, 4)[0]
    um = (struct.unpack_from('<2i', raw, 100) if taille_entete >= 108
          else (0, 0))
    if dev[0] > 0 and dev[1] > 0 and um[0] > 0 and um[1] > 0:
        # le périphérique en micromètres: plus précis
        mmx, mmy = um[0] / 1000.0 / dev[0], um[1] / 1000.0 / dev[1]
    elif dev[0] > 0 and dev[1] > 0 and mm[0] > 0 and mm[1] > 0:
        mmx, mmy = mm[0] / dev[0], mm[1] / dev[1]
    else:
        mmx = mmy = 25.4 / 96.0
        rapport.notes.append("EMF sans périphérique de référence: "
                             "96 points par pouce supposés")
    cadre = struct.unpack_from('<4i', raw, 24)
    if cadre[2] > cadre[0] and cadre[3] > cadre[1]:
        # la taille déclarée par le logiciel qui l'a écrit: si le
        # dessin n'y est pas à l'échelle, F2 le remet à la cote
        rapport.notes.append(
            f"cadre déclaré {(cadre[2] - cadre[0]) / 100:.1f} × "
            f"{(cadre[3] - cadre[1]) / 100:.1f} mm")
    e = _EtatEMF()
    pile = []
    t = _Traceur(tolerance)
    sautes = {}
    textes = 0

    def page(x, y):
        m11, m12, m21, m22, dx, dy = e.monde
        return m11 * x + m21 * y + dx, m12 * x + m22 * y + dy

    def appareil(px, py):
        if e.mode == 1:                             # MM_TEXT
            return (px - e.fen_org[0] + e.vue_org[0],
                    py - e.fen_org[1] + e.vue_org[1])
        if e.mode in (7, 8):                        # (AN)ISOTROPIC
            sx = e.vue_ext[0] / (e.fen_ext[0] or 1.0)
            sy = e.vue_ext[1] / (e.fen_ext[1] or 1.0)
            if e.mode == 7:
                k = min(abs(sx), abs(sy))
                sx = math.copysign(k, sx)
                sy = math.copysign(k, sy)
            return ((px - e.fen_org[0]) * sx + e.vue_org[0],
                    (py - e.fen_org[1]) * sy + e.vue_org[1])
        unite = _MODES_FIXES.get(e.mode, 1.0)
        return ((px - e.fen_org[0]) * unite / mmx + e.vue_org[0],
                -(py - e.fen_org[1]) * unite / mmy + e.vue_org[1])

    def P(x, y):
        dx, dy = appareil(*page(x, y))
        return (dx * mmx, -dy * mmy)

    def boite(off):
        g, h, d, b = struct.unpack_from('<4i', raw, off)
        p1, p2 = P(g, h), P(d, b)
        return (min(p1[0], p2[0]), min(p1[1], p2[1]),
                max(p1[0], p2[0]), max(p1[1], p2[1]))

    def points(off, n, seize):
        fmt = '<%dh' % (2 * n) if seize else '<%di' % (2 * n)
        v = struct.unpack_from(fmt, raw, off)
        return [P(v[2 * k], v[2 * k + 1]) for k in range(n)]

    pos = 0
    total = len(raw)
    compteur = 0
    while pos + 8 <= total:
        typ, taille = struct.unpack_from('<II', raw, pos)
        if taille < 8 or pos + taille > total:
            break
        o = pos + 8
        compteur += 1
        if progress is not None and compteur % 2000 == 0:
            if progress(pos / max(1, total), "métafichier") is False:
                raise Cancelled("lecture arrêtée")
        try:
            if typ == 14:                                     # EOF
                break
            elif typ in (2, 3, 4, 5, 6, 85, 86, 87, 88, 89):
                seize = typ >= 85
                base = typ - 83 if seize else typ
                n = struct.unpack_from('<I', raw, o + 16)[0]
                pts = points(o + 20, n, seize)
                if not pts:
                    pass
                elif base == 3:                               # polygone
                    t.forme(_ferme(pts, tolerance))
                elif base == 4:                               # polyligne
                    t.forme(Chemin(pts, tolerance))
                elif base == 6:                               # polylineto
                    for p in pts:
                        t.ligne(p)
                elif base == 2:                               # polybezier
                    ch = Chemin(tolerance=tolerance)
                    ch.moveto(*pts[0])
                    for k in range(1, len(pts) - 2, 3):
                        ch.cubicto(pts[k], pts[k + 1], pts[k + 2])
                    t.forme(ch)
                elif base == 5:                               # polybezierto
                    for k in range(0, len(pts) - 2, 3):
                        t.bezier(pts[k], pts[k + 1], pts[k + 2])
            elif typ in (7, 8, 90, 91):                       # polypoly
                seize = typ >= 90
                npoly, ntot = struct.unpack_from('<II', raw, o + 16)
                comptes = struct.unpack_from('<%dI' % npoly, raw, o + 24)
                pts = points(o + 24 + 4 * npoly, ntot, seize)
                k = 0
                ferme = typ in (8, 91)
                for c in comptes:
                    morceau = pts[k:k + c]
                    k += c
                    if len(morceau) >= 2:
                        t.forme(_ferme(morceau, tolerance) if ferme
                                else Chemin(morceau, tolerance))
            elif typ == 9:
                e.fen_ext = tuple(map(float, struct.unpack_from('<2i', raw, o)))
            elif typ == 10:
                e.fen_org = tuple(map(float, struct.unpack_from('<2i', raw, o)))
            elif typ == 11:
                e.vue_ext = tuple(map(float, struct.unpack_from('<2i', raw, o)))
            elif typ == 12:
                e.vue_org = tuple(map(float, struct.unpack_from('<2i', raw, o)))
            elif typ == 17:
                e.mode = struct.unpack_from('<I', raw, o)[0]
            elif typ == 27:                                   # MoveToEx
                t.aller(P(*struct.unpack_from('<2i', raw, o)))
            elif typ == 54:                                   # LineTo
                t.ligne(P(*struct.unpack_from('<2i', raw, o)))
            elif typ == 33:
                pile.append(e.copie())
            elif typ == 34:
                n = struct.unpack_from('<i', raw, o)[0]
                k = len(pile) + n if n < 0 else n
                if 0 <= k < len(pile):
                    e = pile[k]
                    del pile[k:]
            elif typ == 35:
                e.monde = struct.unpack_from('<6f', raw, o)
            elif typ == 36:
                x = struct.unpack_from('<6f', raw, o)
                mode = struct.unpack_from('<I', raw, o + 24)[0]
                if mode == 1:
                    e.monde = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
                elif mode == 2:
                    e.monde = _composer(x, e.monde)
                elif mode == 3:
                    e.monde = _composer(e.monde, x)
                elif mode == 4:
                    e.monde = x
            elif typ in (42, 43, 44):                         # ellipse, rect.
                x0, y0, x1, y1 = boite(o)
                if typ == 42:
                    t.forme(_ellipse_bez((x0 + x1) / 2, (y0 + y1) / 2,
                                         (x1 - x0) / 2, (y1 - y0) / 2,
                                         tolerance))
                elif typ == 43:
                    t.forme(_ferme([(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
                                   tolerance))
                else:
                    cw, ch_ = struct.unpack_from('<2i', raw, o + 16)
                    rx = min(abs(cw * mmx) / 2, (x1 - x0) / 2)
                    ry = min(abs(ch_ * mmy) / 2, (y1 - y0) / 2)
                    t.forme(_rect_arrondi(x0, y0, x1, y1, rx, ry, tolerance))
            elif typ in (45, 46, 47, 55):                     # arcs
                x0, y0, x1, y1 = boite(o)
                p1 = P(*struct.unpack_from('<2i', raw, o + 16))
                p2 = P(*struct.unpack_from('<2i', raw, o + 24))
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                arc = _arc_points(cx, cy, (x1 - x0) / 2, (y1 - y0) / 2,
                                  p1, p2, max(tolerance * 10, 0.05))
                if typ == 55:                                 # ArcTo
                    t.ligne(arc[0])
                    for q in arc[1:]:
                        t.ligne(q)
                elif typ == 45:
                    t.forme(Chemin(arc, tolerance))
                elif typ == 46:                               # corde
                    t.forme(_ferme(arc, tolerance))
                else:                                         # part
                    t.forme(_ferme(arc + [(cx, cy)], tolerance))
            elif typ == 59:
                t.debut_chemin()
            elif typ == 60:
                t.fin_chemin()
            elif typ == 61:
                t.fermer()
            elif typ in (62, 63, 64):
                t.rendre_chemin()
            elif typ in (67, 68):                             # clip, abort
                t.jeter_chemin()
            elif typ in (83, 84, 96, 97):
                textes += 1
            elif typ in _EMR_IMAGES:
                sautes['image'] = sautes.get('image', 0) + 1
            # le reste: en-tête, commentaires (EMF+), objets, styles,
            # régions de découpe — rien à tracer
        except struct.error:
            sautes['illisible'] = sautes.get('illisible', 0) + 1
        pos += taille
    chemins = t.tout()
    rapport.skipped_text = textes
    if sautes:
        rapport.skipped_other = dict(sautes)
    return chemins, rapport


def _ferme(pts, tolerance) -> Chemin:
    pts = list(pts)
    if len(pts) > 2 and pts[0] == pts[-1]:
        pts = pts[:-1]
    ch = Chemin(pts, tolerance)
    ch.fermer()
    return ch


def _rect_arrondi(x0, y0, x1, y1, rx, ry, tolerance) -> Chemin:
    if rx <= 0 or ry <= 0:
        return _ferme([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], tolerance)
    pts = []
    coins = ((x1 - rx, y0 + ry, -math.pi / 2), (x1 - rx, y1 - ry, 0.0),
             (x0 + rx, y1 - ry, math.pi / 2), (x0 + rx, y0 + ry, math.pi))
    for cx, cy, a in coins:
        for k in range(9):
            b = a + (math.pi / 2) * k / 8
            pts.append((cx + rx * math.cos(b), cy + ry * math.sin(b)))
    return _ferme(pts, tolerance)


# ── WMF ─────────────────────────────────────────────────────────────

def lire_wmf(raw: bytes, tolerance: float = 0.02, progress=None):
    """(chemins, rapport) d'un WMF."""
    rapport = ImportReport()
    off = 0
    cadre = None
    pouce = 96.0
    if struct.unpack_from('<I', raw, 0)[0] == 0x9AC6CDD7:
        g, h, d, b = struct.unpack_from('<4h', raw, 6)
        pouce = float(struct.unpack_from('<H', raw, 14)[0] or 1440)
        cadre = (g, h, d, b)
        off = 22
    else:
        rapport.notes.append("WMF sans en-tête de taille: 96 unités par "
                             "pouce supposées")
    if len(raw) < off + 18:
        raise MetafileError("WMF tronqué")
    taille_entete = struct.unpack_from('<H', raw, off + 2)[0] * 2
    pos = off + taille_entete
    org = [0.0, 0.0]
    if cadre is not None:
        org = [float(cadre[0]), float(cadre[1])]
    echelle = 25.4 / pouce

    def P(x, y):
        return ((x - org[0]) * echelle, -(y - org[1]) * echelle)

    t = _Traceur(tolerance)
    sautes = {}
    textes = 0
    total = len(raw)
    compteur = 0
    while pos + 6 <= total:
        mots, fonction = struct.unpack_from('<IH', raw, pos)
        taille = mots * 2
        if taille < 6 or pos + taille > total:
            break
        o = pos + 6
        compteur += 1
        if progress is not None and compteur % 2000 == 0:
            if progress(pos / max(1, total), "métafichier") is False:
                raise Cancelled("lecture arrêtée")
        try:
            if fonction == 0x0000:
                break
            elif fonction == 0x020B and cadre is None:        # SetWindowOrg
                y, x = struct.unpack_from('<2h', raw, o)
                org = [float(x), float(y)]
            elif fonction == 0x0214:                          # MoveTo
                y, x = struct.unpack_from('<2h', raw, o)
                t.aller(P(x, y))
            elif fonction == 0x0213:                          # LineTo
                y, x = struct.unpack_from('<2h', raw, o)
                t.ligne(P(x, y))
            elif fonction in (0x0325, 0x0324):                # poly(gone)
                n = struct.unpack_from('<h', raw, o)[0]
                v = struct.unpack_from('<%dh' % (2 * n), raw, o + 2)
                pts = [P(v[2 * k], v[2 * k + 1]) for k in range(n)]
                if len(pts) >= 2:
                    t.forme(_ferme(pts, tolerance) if fonction == 0x0324
                            else Chemin(pts, tolerance))
            elif fonction == 0x0538:                          # PolyPolygon
                n = struct.unpack_from('<h', raw, o)[0]
                comptes = struct.unpack_from('<%dh' % n, raw, o + 2)
                q = o + 2 + 2 * n
                for c in comptes:
                    v = struct.unpack_from('<%dh' % (2 * c), raw, q)
                    q += 4 * c
                    pts = [P(v[2 * k], v[2 * k + 1]) for k in range(c)]
                    if len(pts) >= 2:
                        t.forme(_ferme(pts, tolerance))
            elif fonction in (0x041B, 0x0418, 0x061C):        # rect, ellipse
                if fonction == 0x061C:
                    hc, wc, b, d, h, g = struct.unpack_from('<6h', raw, o)
                else:
                    b, d, h, g = struct.unpack_from('<4h', raw, o)
                p1, p2 = P(g, h), P(d, b)
                x0, y0 = min(p1[0], p2[0]), min(p1[1], p2[1])
                x1, y1 = max(p1[0], p2[0]), max(p1[1], p2[1])
                if fonction == 0x0418:
                    t.forme(_ellipse_bez((x0 + x1) / 2, (y0 + y1) / 2,
                                         (x1 - x0) / 2, (y1 - y0) / 2,
                                         tolerance))
                elif fonction == 0x041B:
                    t.forme(_ferme([(x0, y0), (x1, y0), (x1, y1),
                                    (x0, y1)], tolerance))
                else:
                    t.forme(_rect_arrondi(x0, y0, x1, y1,
                                          abs(wc) * echelle / 2,
                                          abs(hc) * echelle / 2, tolerance))
            elif fonction in (0x0817, 0x081A, 0x0830):        # arc, part, corde
                ye, xe, ys, xs, b, d, h, g = struct.unpack_from('<8h', raw, o)
                p1, p2 = P(g, h), P(d, b)
                x0, y0 = min(p1[0], p2[0]), min(p1[1], p2[1])
                x1, y1 = max(p1[0], p2[0]), max(p1[1], p2[1])
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                arc = _arc_points(cx, cy, (x1 - x0) / 2, (y1 - y0) / 2,
                                  P(xs, ys), P(xe, ye),
                                  max(tolerance * 10, 0.05))
                if fonction == 0x0817:
                    t.forme(Chemin(arc, tolerance))
                elif fonction == 0x0830:
                    t.forme(_ferme(arc, tolerance))
                else:
                    t.forme(_ferme(arc + [(cx, cy)], tolerance))
            elif fonction in (0x0521, 0x0A32):
                textes += 1
            elif fonction in _WMF_IMAGES:
                sautes['image'] = sautes.get('image', 0) + 1
            # le reste: état, objets, styles, palettes — rien à tracer
        except struct.error:
            sautes['illisible'] = sautes.get('illisible', 0) + 1
        pos += taille
    rapport.skipped_text = textes
    if sautes:
        rapport.skipped_other = dict(sautes)
    return t.tout(), rapport


def lire(chemin, tolerance_mm: float = 0.02, units_mm: float = None,
         progress=None, ask=None):
    """Point d'entrée du noyau vectoriel: `({'dessin': [Chemin]},
    rapport)`."""
    raw = _octets(chemin)
    g = genre(raw)
    if g == 'emf':
        chemins, rapport = lire_emf(raw, tolerance_mm, progress)
    elif g == 'wmf':
        chemins, rapport = lire_wmf(raw, tolerance_mm, progress)
    else:
        raise MetafileError(f"{pathlib.Path(chemin).name}: ni EMF ni WMF")
    if units_mm and units_mm != 1.0:
        f = float(units_mm)
        chemins = [c.transforme(lambda x, y: (x * f, y * f))
                   for c in chemins]
    if not chemins:
        raise MetafileError("aucun tracé dans ce métafichier"
                            + (f" ({rapport.skipped_text} texte(s) non "
                               f"lus)" if rapport.skipped_text else ""))
    rapport.layers = {'dessin': len(chemins)}
    rapport.polylines = len(chemins)
    pts = [p for c in chemins for p in c]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    rapport.extent = (min(xs), min(ys), max(xs), max(ys))
    rapport.notes.append(f"métafichier {g.upper()}")
    return {'dessin': chemins}, rapport
