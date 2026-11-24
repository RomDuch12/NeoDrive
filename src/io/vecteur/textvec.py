"""Vectorisation de texte / Text outlining.

Convertit une chaîne en contours fermés, à partir d'une police TrueType
lue avec fontTools. Le texte gravé est donc du **contour réel de la
police**, remplissable par hachurage (voir `geometry.hatch`).
"""
from __future__ import annotations

import functools
import logging
import pathlib

from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont

# Certaines polices système ont des tables légèrement malformées ; fontTools
# les lit quand même mais émet un avertissement par fichier. Sans intérêt ici.
logging.getLogger('fontTools').setLevel(logging.ERROR)

from .geometry import Polyline, flatten_cubic

WINDOWS_FONTS = pathlib.Path('C:/Windows/Fonts')

#: Polices essayées par défaut, dans l'ordre.
DEFAULT_FONT_CANDIDATES = ('arial.ttf', 'segoeui.ttf', 'calibri.ttf',
                           'consola.ttf', 'DejaVuSans.ttf')


class FontNotFound(FileNotFoundError):
    """Aucune police utilisable n'a été trouvée."""


def default_font_path() -> str:
    for name in DEFAULT_FONT_CANDIDATES:
        p = WINDOWS_FONTS / name
        if p.exists():
            return str(p)
    raise FontNotFound(
        'aucune police par défaut trouvée dans C:/Windows/Fonts ; '
        'indiquez un fichier .ttf explicitement')


def _family_name(path: pathlib.Path) -> str:
    """Nom de famille lu dans la table `name`, sinon le nom de fichier."""
    try:
        font = TTFont(str(path), fontNumber=0, lazy=True)
        best = ''
        for record in font['name'].names:
            # 4 = nom complet, 1 = famille ; on préfère l'anglais
            if record.nameID in (4, 1):
                try:
                    value = record.toUnicode().strip()
                except Exception:
                    continue
                if value and (not best or record.nameID == 4):
                    best = value
                    if record.nameID == 4:
                        break
        font.close()
        return best or path.stem
    except Exception:
        return path.stem


@functools.lru_cache(maxsize=1)
def available_fonts() -> tuple[tuple[str, str], ...]:
    """Toutes les polices installées : (nom de famille, chemin).

    Parcourt `.ttf`, `.otf` et `.ttc`, lit le vrai nom de famille dans la
    table `name` de chaque fichier, dédoublonne et trie alphabétiquement.
    Le résultat est mis en cache : le coût n'est payé qu'une fois.
    """
    if not WINDOWS_FONTS.is_dir():
        return ()
    seen: dict[str, str] = {}
    for pattern in ('*.ttf', '*.otf', '*.ttc'):
        for path in WINDOWS_FONTS.glob(pattern):
            name = _family_name(path)
            # à nom égal, on garde le premier rencontré
            seen.setdefault(name, str(path))
    return tuple(sorted(seen.items(), key=lambda kv: kv[0].lower()))


class _ContourPen(BasePen):
    """Collecte les contours d'un glyphe sous forme de polylignes."""

    def __init__(self, glyph_set, tolerance: float) -> None:
        super().__init__(glyph_set)
        self.contours: list[Polyline] = []
        self._current: Polyline = []
        self._tolerance = tolerance

    def _moveTo(self, pt):
        self._flush()
        self._current = [pt]

    def _lineTo(self, pt):
        self._current.append(pt)

    def _curveToOne(self, p1, p2, p3):
        if not self._current:
            self._current = [p1]
        self._current.extend(
            flatten_cubic(self._current[-1], p1, p2, p3, self._tolerance))

    def _closePath(self):
        if self._current and self._current[0] != self._current[-1]:
            self._current.append(self._current[0])
        self._flush()

    def _endPath(self):
        self._flush()

    def _flush(self):
        if len(self._current) > 2:
            self.contours.append(self._current)
        self._current = []


@functools.lru_cache(maxsize=8)
def _load(font_path: str) -> tuple[TTFont, int, dict]:
    font = TTFont(font_path, fontNumber=0, lazy=True)
    upem = font['head'].unitsPerEm
    cmap = font.getBestCmap()
    return font, upem, cmap


def _scale_for(font, upem: float, size_mm: float) -> float:
    """Facteur d'échelle calant la hauteur de capitale sur `size_mm`."""
    try:
        cap = font['OS/2'].sCapHeight or 0
    except (KeyError, AttributeError):
        cap = 0
    if cap <= 0:
        cap = getattr(font['hhea'], 'ascent', upem * 0.7)
    return size_mm / cap


def outline(text: str, size_mm: float, font_path: str = '',
            tolerance_mm: float = 0.02) -> list[Polyline]:
    """Contours d'**une ligne**, posée sur la ligne de base, début en x = 0.

    Le placement — alignement, interligne — relève de `layout`.
    """
    if not text:
        return []
    font_path = font_path or default_font_path()
    font, upem, cmap = _load(font_path)
    scale = _scale_for(font, upem, size_mm)

    glyph_set = font.getGlyphSet()
    hmtx = font['hmtx']
    tol_units = max(tolerance_mm / scale, 1e-3)

    contours: list[Polyline] = []
    pen_x = 0.0
    for ch in text:
        name = cmap.get(ord(ch))
        if name is None:
            pen_x += upem * 0.3           # caractère absent : espace
            continue
        pen = _ContourPen(glyph_set, tol_units)
        glyph_set[name].draw(pen)
        for c in pen.contours:
            contours.append([((x + pen_x) * scale, y * scale) for x, y in c])
        pen_x += hmtx[name][0]
    return contours


def advance_width(text: str, size_mm: float, font_path: str = '') -> float:
    """Largeur d'avance d'une ligne, sans la dessiner."""
    if not text:
        return 0.0
    font_path = font_path or default_font_path()
    font, upem, cmap = _load(font_path)
    scale = _scale_for(font, upem, size_mm)
    hmtx = font['hmtx']
    total = 0.0
    for ch in text:
        name = cmap.get(ord(ch))
        total += upem * 0.3 if name is None else hmtx[name][0]
    return total * scale


#: Alignements admis.
HALIGN = ('left', 'center', 'right')
VALIGN = ('top', 'middle', 'baseline', 'bottom')


def layout(text: str, size_mm: float, font_path: str = '',
           align: str = 'center', valign: str = 'middle',
           line_spacing: float = 1.4) -> list[Polyline]:
    """Contours d'un bloc de texte, éventuellement sur plusieurs lignes.

    * `align` — `left`, `center` ou `right`, appliqué **ligne par ligne**
      dans la largeur du bloc.
    * `valign` — position du bloc par rapport à l'origine :
      `top` (l'origine est le haut du bloc), `middle` (centré),
      `baseline` (ligne de base de la **première** ligne, comme un texte
      simple) ou `bottom`.
    * `line_spacing` — interligne, en multiples de `size_mm`.

    Les lignes vides comptent : elles occupent leur interligne.
    """
    lines = text.split('\n')
    if not any(line.strip() for line in lines):
        return []

    step = size_mm * line_spacing
    widths = [advance_width(line, size_mm, font_path) for line in lines]
    block_width = max(widths) if widths else 0.0

    placed: list[Polyline] = []
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        contours = outline(line, size_mm, font_path)
        if not contours:
            continue
        if align == 'center':
            dx = (block_width - widths[index]) / 2 - block_width / 2
        elif align == 'right':
            dx = block_width - widths[index] - block_width / 2
        else:                                    # 'left'
            dx = -block_width / 2
        dy = -index * step
        placed.extend([[(x + dx, y + dy) for x, y in c] for c in contours])

    if not placed:
        return []

    # décalage vertical du bloc selon `valign`
    if valign == 'baseline':
        offset = 0.0
    else:
        ys = [y for c in placed for _, y in c]
        low, high = min(ys), max(ys)
        if valign == 'top':
            offset = -high
        elif valign == 'bottom':
            offset = -low
        else:                                    # 'middle'
            offset = -(low + high) / 2
    if offset:
        placed = [[(x, y + offset) for x, y in c] for c in placed]
    return placed
