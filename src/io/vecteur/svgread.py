"""Lecture SVG / SVG reading.

Le SVG est le format que **tout le monde peut produire** : Inkscape,
Illustrator, CorelDRAW, un navigateur, un script. C'est aussi le format
vers lequel on convertit quand on ne sait pas quoi faire d'autre. Un
atelier en reçoit donc autant que de DXF.

C'est du XML, et sa géométrie tient dans un vocabulaire court : sept
primitives de forme, onze commandes de chemin, six transformations. On le
lit donc nativement, comme le PDF et le PostScript, plutôt que d'ajouter
une bibliothèque pour un format aussi simple.

**Trois pièges, et ils comptent tous les trois.**

*L'axe Y descend.* En SVG, Y augmente vers le bas ; sur un plan de
travail, vers le haut. Un dessin lu sans retournement sort en miroir — et
un texte gravé en miroir ne se rattrape pas.

*L'unité n'est pas dans les coordonnées.* Elles sont en « unités
utilisateur », et c'est le couple `width`/`height` + `viewBox` qui dit
combien de millimètres cela fait. Un SVG de 100 mm de large dont la
`viewBox` fait 1000 unités a une unité valant un dixième de millimètre.
Sans `width` physique, l'unité est le **pixel CSS** — 1/96 de pouce.

*L'arc elliptique n'existe nulle part ailleurs.* La commande `A` se donne
par son point d'arrivée, ses rayons et deux drapeaux ; il faut la
reconvertir en son centre pour la parcourir. C'est la seule vraie
arithmétique de ce module.

**Ce qu'on ignore, et sans regret** : couleurs, remplissages, dégradés,
filtres, images matricielles. Une gravure suit un tracé, pas un aplat.

**Le texte, non.** Un `<text>` est rendu en contours par `textvec`, avec
la police que `font-family` déclare — ou une substitution si elle
n'est pas sur ce poste (voir `fontmap`). Ce qui ne peut vraiment pas
être rendu — un texte vide, une police sans le moindre glyphe — reste
compté et signalé : le taire ferait croire à un dessin complet.
"""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET

from . import geometry as G

#: Espace de noms SVG. Un fichier écrit à la main peut ne pas le porter :
#: on compare donc sur le nom local, jamais sur le nom complet.
NS = '{http://www.w3.org/2000/svg}'

#: Millimètres par pixel CSS. Le SVG définit le pixel à 1/96 de pouce,
#: et c'est l'unité par défaut de toute coordonnée sans suffixe.
PX_TO_MM = 25.4 / 96.0

#: Facteurs des unités CSS admises dans `width` et `height`.
UNITS_MM = {
    'mm': 1.0, 'cm': 10.0, 'q': 0.25,
    'in': 25.4, 'pt': 25.4 / 72.0, 'pc': 25.4 / 6.0,
    'px': PX_TO_MM, '': PX_TO_MM,
}

#: Segments minimum et maximum sur un tour complet.
#:
#: Le nombre réel se déduit de la **tolérance**, pas d\'un compte fixe :
#: un cercle de 2 mm et un de 200 mm n\'ont pas besoin du même nombre
#: de cordes pour tenir dans deux centièmes. Un compte fixe rate donc
#: toujours d\'un côté — trop grossier sur les grands rayons, mille
#: points inutiles sur les petits.
MIN_STEPS = 12
MAX_STEPS = 720


def arc_steps(radius: float, sweep: float, tolerance: float) -> int:
    """Nombre de cordes pour suivre un arc à la tolérance voulue.

    L\'écart d\'une corde à son arc vaut `r(1 − cos(θ/2))` ; on
    inverse pour trouver l\'angle admissible, puis on divise le
    balayage.
    """
    r = abs(radius)
    balayage = abs(sweep)
    if r <= 0 or balayage <= 0:
        return MIN_STEPS
    e = max(float(tolerance), 1e-9)
    if e >= r:
        return MIN_STEPS
    theta = 2.0 * math.acos(max(-1.0, min(1.0, 1.0 - e / r)))
    if theta <= 1e-9:
        return MAX_STEPS
    return max(MIN_STEPS, min(MAX_STEPS, int(balayage / theta) + 1))

_NUM = re.compile(r'[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?')
_CMD = re.compile(r'([MmLlHhVvCcSsQqTtAaZz])')
_TRANSFORM = re.compile(r'(matrix|translate|scale|rotate|skewX|skewY)\s*'
                        r'\(([^)]*)\)')


class SvgError(RuntimeError):
    """Fichier illisible, ou sans géométrie exploitable."""


def _numbers(texte: str) -> list[float]:
    return [float(m.group()) for m in _NUM.finditer(texte or '')]


def _length_mm(valeur: str, defaut: float = 0.0) -> float:
    """Une longueur CSS en millimètres. Les pourcentages ne se résolvent pas.

    Un `width="100%"` ne dit rien de la taille réelle : il renvoie à un
    contenant qui n'existe pas hors d'un navigateur. On rend alors 0, et
    l'appelant retombe sur le pixel.
    """
    texte = str(valeur or '').strip().lower()
    if not texte or texte.endswith('%'):
        return defaut
    nombres = _numbers(texte)
    if not nombres:
        return defaut
    unite = texte[len(str(texte).rstrip('abcdefghijklmnopqrstuvwxyz')):]
    return nombres[0] * UNITS_MM.get(unite, PX_TO_MM)


# --------------------------------------------------------------------------
# Transformations
# --------------------------------------------------------------------------

IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def mat_mul(m, n):
    """`m` **puis** `n` — l'ordre du SVG, où l'enfant s'applique d'abord."""
    a, b, c, d, e, f = m
    A, B, C, D, E, F = n
    return (a * A + b * C, a * B + b * D,
            c * A + d * C, c * B + d * D,
            e * A + f * C + E, e * B + f * D + F)


def mat_apply(m, x, y):
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


def parse_transform(texte: str):
    """L'attribut `transform` d'un élément, en une matrice.

    Les transformations s'écrivent de gauche à droite et s'appliquent de
    **droite à gauche** : `translate(10,0) scale(2)` met à l'échelle,
    puis translate.
    """
    m = IDENTITY
    for nom, args in _TRANSFORM.findall(texte or ''):
        v = _numbers(args)
        if nom == 'matrix' and len(v) >= 6:
            t = tuple(v[:6])
        elif nom == 'translate':
            t = (1.0, 0.0, 0.0, 1.0, v[0] if v else 0.0,
                 v[1] if len(v) > 1 else 0.0)
        elif nom == 'scale':
            sx = v[0] if v else 1.0
            sy = v[1] if len(v) > 1 else sx
            t = (sx, 0.0, 0.0, sy, 0.0, 0.0)
        elif nom == 'rotate':
            a = math.radians(v[0] if v else 0.0)
            cos, sin = math.cos(a), math.sin(a)
            t = (cos, sin, -sin, cos, 0.0, 0.0)
            if len(v) >= 3:                      # rotation autour d'un point
                cx, cy = v[1], v[2]
                t = mat_mul(mat_mul((1, 0, 0, 1, -cx, -cy), t),
                            (1, 0, 0, 1, cx, cy))
        elif nom == 'skewX':
            t = (1.0, 0.0, math.tan(math.radians(v[0] if v else 0.0)),
                 1.0, 0.0, 0.0)
        elif nom == 'skewY':
            t = (1.0, math.tan(math.radians(v[0] if v else 0.0)),
                 0.0, 1.0, 0.0, 0.0)
        else:
            continue
        m = mat_mul(t, m)
    return m


# --------------------------------------------------------------------------
# Chemins
# --------------------------------------------------------------------------

def parse_path(d: str, tolerance: float = 0.02) -> list[G.Chemin]:
    """Les tracés d'un attribut `d`, dans les unités du document.

    Chaque `M` ouvre un nouveau tracé ; `Z` le referme. Les courbes
    sont GARDÉES telles quelles et aplaties en parallèle à la
    tolérance donnée, exprimée dans les mêmes unités que les
    coordonnées — c'est à l'appelant de la convertir s'il place le
    tracé ensuite.
    """
    out: list[G.Chemin] = []
    courant = G.Chemin(tolerance=tolerance)
    x = y = 0.0
    debut = (0.0, 0.0)
    precedent_c: tuple[float, float] | None = None
    precedent_q: tuple[float, float] | None = None

    morceaux = [m for m in _CMD.split(d or '') if m and m.strip()]
    i = 0
    commande = ''
    while i < len(morceaux):
        if _CMD.fullmatch(morceaux[i]):
            commande = morceaux[i]
            i += 1
            if commande in 'Zz':
                if len(courant) >= 2:
                    courant.fermer()
                    out.append(courant)
                courant = G.Chemin(tolerance=tolerance)
                x, y = debut
                precedent_c = precedent_q = None
                continue
            if i >= len(morceaux):
                break
        args = _numbers(morceaux[i]) if i < len(morceaux) else []
        i += 1
        if not args:
            continue

        relatif = commande.islower()
        c = commande.upper()
        k = 0
        while k < len(args):
            reste = len(args) - k
            if c == 'M':
                if reste < 2:
                    break
                nx, ny = args[k], args[k + 1]
                k += 2
                x, y = (x + nx, y + ny) if relatif else (nx, ny)
                if len(courant) >= 2:
                    out.append(courant)
                courant = G.Chemin(tolerance=tolerance)
                courant.moveto(x, y)
                debut = (x, y)
                # les paires suivantes d'un M sont des L, dit la norme
                c = 'L'
            elif c == 'L':
                if reste < 2:
                    break
                nx, ny = args[k], args[k + 1]
                k += 2
                x, y = (x + nx, y + ny) if relatif else (nx, ny)
                courant.lineto(x, y)
            elif c == 'H':
                nx = args[k]
                k += 1
                x = x + nx if relatif else nx
                courant.lineto(x, y)
            elif c == 'V':
                ny = args[k]
                k += 1
                y = y + ny if relatif else ny
                courant.lineto(x, y)
            elif c in ('C', 'S'):
                besoin = 6 if c == 'C' else 4
                if reste < besoin:
                    break
                if c == 'C':
                    p1 = _pt(args[k], args[k + 1], x, y, relatif)
                    p2 = _pt(args[k + 2], args[k + 3], x, y, relatif)
                    p3 = _pt(args[k + 4], args[k + 5], x, y, relatif)
                else:
                    # le premier contrôle est le reflet du précédent :
                    # c'est tout l'objet de `S`, garder la tangente
                    p1 = ((2 * x - precedent_c[0], 2 * y - precedent_c[1])
                          if precedent_c else (x, y))
                    p2 = _pt(args[k], args[k + 1], x, y, relatif)
                    p3 = _pt(args[k + 2], args[k + 3], x, y, relatif)
                k += besoin
                courant.cubicto(p1, p2, p3)
                precedent_c, precedent_q = p2, None
                x, y = p3
            elif c in ('Q', 'T'):
                besoin = 4 if c == 'Q' else 2
                if reste < besoin:
                    break
                if c == 'Q':
                    q = _pt(args[k], args[k + 1], x, y, relatif)
                    p3 = _pt(args[k + 2], args[k + 3], x, y, relatif)
                else:
                    q = ((2 * x - precedent_q[0], 2 * y - precedent_q[1])
                         if precedent_q else (x, y))
                    p3 = _pt(args[k], args[k + 1], x, y, relatif)
                k += besoin
                # une quadratique s'élève exactement en cubique
                p1 = (x + 2 / 3 * (q[0] - x), y + 2 / 3 * (q[1] - y))
                p2 = (p3[0] + 2 / 3 * (q[0] - p3[0]),
                      p3[1] + 2 / 3 * (q[1] - p3[1]))
                courant.cubicto(p1, p2, p3)
                precedent_q, precedent_c = q, None
                x, y = p3
            elif c == 'A':
                if reste < 7:
                    break
                rx, ry, phi = args[k], args[k + 1], args[k + 2]
                grand, sens = args[k + 3], args[k + 4]
                p3 = _pt(args[k + 5], args[k + 6], x, y, relatif)
                k += 7
                for c1, c2, c3 in arc_cubiques(
                        (x, y), rx, ry, phi, bool(grand), bool(sens),
                        p3):
                    courant.cubicto(c1, c2, c3)
                precedent_c = precedent_q = None
                x, y = p3
            else:
                k = len(args)

    if len(courant) >= 2:
        out.append(courant)
    return out


def _pt(a: float, b: float, x: float, y: float, relatif: bool):
    return (x + a, y + b) if relatif else (a, b)


def ellipse_cubiques(cx: float, cy: float, rx: float, ry: float,
                     phi: float, theta1: float, delta: float
                     ) -> list[tuple]:
    """Un arc d'ellipse en Béziers cubiques, par quarts au plus.

    L'approximation classique : sur un arc de θ, les poignées valent
    4/3·tan(θ/4). L'écart au vrai arc reste sous 3·10⁻⁴ du rayon pour
    un quart de tour — mille fois moins qu'un aplatissement à 0,02 mm
    sur une pièce de 100 mm, et la courbe reste une courbe.
    """
    n = max(1, int(math.ceil(abs(delta) / (math.pi / 2) - 1e-9)))
    pas = delta / n
    k = 4.0 / 3.0 * math.tan(pas / 4.0)
    cos_p, sin_p = math.cos(phi), math.sin(phi)

    def point(t):
        x, y = rx * math.cos(t), ry * math.sin(t)
        return (cx + x * cos_p - y * sin_p, cy + x * sin_p + y * cos_p)

    def tangente(t):
        x, y = -rx * math.sin(t), ry * math.cos(t)
        return (x * cos_p - y * sin_p, x * sin_p + y * cos_p)

    segments = []
    t = theta1
    for _ in range(n):
        t2 = t + pas
        p0, p3 = point(t), point(t2)
        d0, d3 = tangente(t), tangente(t2)
        segments.append((
            (p0[0] + k * d0[0], p0[1] + k * d0[1]),
            (p3[0] - k * d3[0], p3[1] - k * d3[1]),
            p3))
        t = t2
    return segments


def arc_cubiques(depart, rx: float, ry: float, phi_deg: float,
                 grand: bool, sens: bool, arrivee) -> list[tuple]:
    """L'arc `A` d'un chemin SVG, en Béziers cubiques."""
    repere = _arc_repere(depart, rx, ry, phi_deg, grand, sens, arrivee)
    if repere is None:
        return [(depart, arrivee, arrivee)]     # dégénéré: un segment
    cx, cy, rx, ry, phi, theta1, delta = repere
    return ellipse_cubiques(cx, cy, rx, ry, phi, theta1, delta)


def _arc_repere(depart, rx: float, ry: float, phi_deg: float,
                grand: bool, sens: bool, arrivee):
    """Centre et angles d'un arc SVG donné par son point d'arrivée.

    C'est la conversion de l'annexe F.6 de la norme, et la seule vraie
    arithmétique de ce module. Rend None si l'arc dégénère.
    """
    x1, y1 = depart
    x2, y2 = arrivee
    rx, ry = abs(rx), abs(ry)
    if rx < 1e-12 or ry < 1e-12:
        return None

    phi = math.radians(phi_deg)
    cos_p, sin_p = math.cos(phi), math.sin(phi)
    dx2, dy2 = (x1 - x2) / 2.0, (y1 - y2) / 2.0
    x1p = cos_p * dx2 + sin_p * dy2
    y1p = -sin_p * dx2 + cos_p * dy2

    # rayons trop courts : la norme demande de les agrandir, pas d'abandonner
    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1:
        racine = math.sqrt(lam)
        rx, ry = rx * racine, ry * racine

    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    facteur = math.sqrt(max(0.0, num / den)) if den else 0.0
    if grand == sens:
        facteur = -facteur
    cxp = facteur * rx * y1p / ry
    cyp = -facteur * ry * x1p / rx
    cx = cos_p * cxp - sin_p * cyp + (x1 + x2) / 2.0
    cy = sin_p * cxp + cos_p * cyp + (y1 + y2) / 2.0

    theta1 = math.atan2((y1p - cyp) / ry, (x1p - cxp) / rx)
    theta2 = math.atan2((-y1p - cyp) / ry, (-x1p - cxp) / rx)
    delta = theta2 - theta1
    if not sens and delta > 0:
        delta -= 2 * math.pi
    elif sens and delta < 0:
        delta += 2 * math.pi

    return cx, cy, rx, ry, phi, theta1, delta


def arc_points(depart, rx: float, ry: float, phi_deg: float,
               grand: bool, sens: bool, arrivee,
               tolerance: float = 0.02) -> G.Polyline:
    """Le même arc, discrétisé — pour qui veut des points."""
    repere = _arc_repere(depart, rx, ry, phi_deg, grand, sens, arrivee)
    if repere is None:
        return [depart, arrivee]
    cx, cy, rx, ry, phi, theta1, delta = repere
    cos_p, sin_p = math.cos(phi), math.sin(phi)
    pas = arc_steps(max(rx, ry), delta, tolerance)
    points = []
    for i in range(pas + 1):
        t = theta1 + delta * i / pas
        px = cx + rx * math.cos(t) * cos_p - ry * math.sin(t) * sin_p
        py = cy + rx * math.cos(t) * sin_p + ry * math.sin(t) * cos_p
        points.append((px, py))
    return points


# --------------------------------------------------------------------------
# Primitives de forme
# --------------------------------------------------------------------------

def shape_polylines(tag: str, attrib: dict,
                    tolerance: float) -> list[G.Chemin]:
    """Les tracés d'une primitive SVG, dans les unités du document.

    Un cercle SVG est un CERCLE: le rendre en 720 segments en faisait
    un polygone, visible au zoom et lourd à ressortir. Quatre Béziers
    suffisent, et restent des courbes."""
    def n(nom, defaut=0.0):
        try:
            return float(attrib.get(nom, defaut))
        except (TypeError, ValueError):
            return defaut

    if tag == 'path':
        return parse_path(attrib.get('d', ''), tolerance)
    if tag == 'rect':
        x, y, w, h = n('x'), n('y'), n('width'), n('height')
        if w <= 0 or h <= 0:
            return []
        rx, ry = n('rx', -1), n('ry', -1)
        if rx < 0 and ry < 0:
            return [G.Chemin([(x, y), (x + w, y), (x + w, y + h),
                              (x, y + h), (x, y)], tolerance)]
        rx = min(rx if rx >= 0 else ry, w / 2)
        ry = min(ry if ry >= 0 else rx, h / 2)
        return [_round_rect(x, y, w, h, rx, ry, tolerance)]
    if tag in ('circle', 'ellipse'):
        cx, cy = n('cx'), n('cy')
        if tag == 'circle':
            rx = ry = n('r')
        else:
            rx, ry = n('rx'), n('ry')
        if rx <= 0 or ry <= 0:
            return []
        chemin = G.Chemin(tolerance=tolerance)
        chemin.moveto(cx + rx, cy)
        for p1, p2, p3 in ellipse_cubiques(cx, cy, rx, ry, 0.0, 0.0,
                                           2 * math.pi):
            chemin.cubicto(p1, p2, p3)
        chemin.fermer()
        return [chemin]
    if tag == 'line':
        return [G.Chemin([(n('x1'), n('y1')), (n('x2'), n('y2'))],
                         tolerance)]
    if tag in ('polyline', 'polygon'):
        v = _numbers(attrib.get('points', ''))
        pts = [(v[i], v[i + 1]) for i in range(0, len(v) - 1, 2)]
        if len(pts) < 2:
            return []
        if tag == 'polygon' and pts[0] != pts[-1]:
            pts.append(pts[0])
        return [G.Chemin(pts, tolerance)]
    return []


def _round_rect(x, y, w, h, rx, ry, tolerance) -> G.Chemin:
    """Rectangle à coins arrondis: droites et quarts d'ellipse."""
    chemin = G.Chemin(tolerance=tolerance)
    coins = (
        (x + w - rx, y + ry, -math.pi / 2, 0.0),
        (x + w - rx, y + h - ry, 0.0, math.pi / 2),
        (x + rx, y + h - ry, math.pi / 2, math.pi),
        (x + rx, y + ry, math.pi, 3 * math.pi / 2),
    )
    chemin.moveto(x + rx, y)
    for cx, cy, a1, a2 in coins:
        # Le côté droit qui mène au coin: sans lui, la courbe du coin
        # partirait du coin précédent et mangerait le côté
        chemin.lineto(cx + rx * math.cos(a1), cy + ry * math.sin(a1))
        for p1, p2, p3 in ellipse_cubiques(cx, cy, rx, ry, 0.0, a1,
                                           a2 - a1):
            chemin.cubicto(p1, p2, p3)
    chemin.fermer()
    return chemin


# --------------------------------------------------------------------------
# Le document
# --------------------------------------------------------------------------

#: Éléments qu'on traverse sans rien produire.
_GROUPS = ('g', 'svg', 'a', 'switch')

#: Éléments dont le contenu ne se grave pas — et qu'on ne descend pas.
_SKIP = ('defs', 'clipPath', 'mask', 'marker', 'pattern', 'symbol',
         'metadata', 'title', 'desc', 'style', 'filter')


def read(raw: bytes, tolerance_mm: float = 0.02, *, ask=None
         ) -> tuple[list[G.Chemin], dict]:
    """Les tracés d'un SVG, **en millimètres**, avec son compte rendu.

    Le compte rendu porte l'échelle retenue et ce qui a été laissé de
    côté : une image ou une référence `use` non résolue disparaîtrait
    sinon en silence, et l'on croirait le dessin incomplet sans savoir
    pourquoi.

    Le texte, lui, **n'est plus laissé de côté** : il est rendu en
    contours par `textvec`, avec la police déclarée par `font-family` —
    ou une substitution si elle n'est pas sur ce poste (voir `fontmap`).
    `ask(nom, candidats)` en est le point d'entrée interactif ; sans lui,
    la substitution retombe silencieusement sur un alias connu ou la
    police par défaut. Ce qui reste compté dans `rapport['textes']` est
    du texte véritablement vide, ou dont la police n'a pas pu produire un
    seul contour.
    """
    try:
        racine = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise SvgError(f'XML illisible : {exc}') from None
    if _tag(racine) != 'svg':
        raise SvgError('ce fichier n\'est pas un SVG.')

    echelle, note = _document_scale(racine)
    rapport = {'echelle_mm': echelle, 'note': note,
               'textes': 0, 'images': 0, 'usages': 0,
               'police_substituee': {},
               'avertissement': _vieux_pixels(racine, echelle)}

    from . import fontmap
    ask_une_fois = fontmap.cached_ask(ask) if ask is not None else None

    # Repère : les unités utilisateur deviennent des millimètres, et l'axe
    # Y se retourne — il descend en SVG, il monte sur un plan de travail.
    base = (echelle, 0.0, 0.0, -echelle, 0.0, 0.0)
    boite = _numbers(racine.get('viewBox', ''))
    if len(boite) >= 4:
        base = mat_mul((1.0, 0.0, 0.0, 1.0, -boite[0], -boite[1]), base)

    polys: list[G.Chemin] = []
    _walk(racine, base, tolerance_mm / max(echelle, 1e-9), polys, rapport,
         ask_une_fois)
    return ([p for p in polys if len(p) >= 2], rapport)


def _tag(element) -> str:
    tag = element.tag
    return tag.split('}')[-1] if isinstance(tag, str) else ''


def _text_polylines(enfant, tolerance: float, ask, rapport: dict
                    ) -> list[G.Polyline]:
    """Contours d'un `<text>`, dans le repère local de l'élément.

    Le contenu vient de tous les `<tspan>` imbriqués (`itertext`) : un
    positionnement propre à chacun (leur `x`/`dy`) n'est pas reproduit,
    seul l'enchaînement du texte l'est — une limite documentée plutôt
    qu'un habillage à moitié fait.
    """
    from . import fontmap, textvec

    texte = ''.join(enfant.itertext())
    if not texte.strip():
        return []
    taille = _numbers(enfant.get('font-size', ''))
    taille = taille[0] if taille else 16.0
    if taille <= 0:
        return []
    famille = (enfant.get('font-family', '') or 'sans-serif').split(',')[0]
    nom = famille.strip().strip('\'"') or 'Arial'
    ancre = (enfant.get('text-anchor', 'start') or 'start').strip()
    xs = _numbers(enfant.get('x', '')) or [0.0]
    ys = _numbers(enfant.get('y', '')) or [0.0]
    x, y = xs[0], ys[0]

    police, exact = fontmap.resolve(nom, ask=ask)
    if not exact:
        rapport['police_substituee'][nom] = (
            rapport['police_substituee'].get(nom, 0) + 1)

    contours = textvec.outline(texte, taille, police, tolerance_mm=tolerance)
    if not contours:
        return []
    if ancre in ('middle', 'end'):
        largeur = textvec.advance_width(texte, taille, police)
        dx = -largeur / 2 if ancre == 'middle' else -largeur
    else:
        dx = 0.0
    return [[(px + x + dx, py + y) for px, py in poly] for poly in contours]


def _walk(element, matrice, tolerance: float, out: list, rapport: dict,
          ask=None) -> None:
    for enfant in element:
        tag = _tag(enfant)
        if tag in _SKIP:
            continue
        locale = mat_mul(parse_transform(enfant.get('transform', '')),
                         matrice)
        if tag in _GROUPS:
            _walk(enfant, locale, tolerance, out, rapport, ask)
            continue
        if tag == 'text':
            contours = _text_polylines(enfant, tolerance, ask, rapport)
            if not contours:
                rapport['textes'] += 1
            else:
                for poly in contours:
                    out.append(G.Chemin(poly, tolerance).transforme(
                        lambda px, py: mat_apply(locale, px, py)))
            continue
        if tag == 'tspan':
            rapport['textes'] += 1
            continue
        if tag == 'image':
            rapport['images'] += 1
            continue
        if tag == 'use':
            # résoudre un `use` demande de tenir la table des `defs`, que
            # l'on ne descend pas : on le signale plutôt que de le taire
            rapport['usages'] += 1
            continue
        for chemin in shape_polylines(tag, enfant.attrib, tolerance):
            # La matrice s'applique aussi aux points de contrôle: une
            # Bézier transformée reste la même Bézier
            out.append(chemin.transforme(
                lambda x, y: mat_apply(locale, x, y)))


#: Inkscape a compté 90 pixels par pouce jusqu'à la version 0.92.
ANCIEN_PPP = 90.0

#: Rapport entre l'ancienne définition et celle d'aujourd'hui.
FACTEUR_90 = 96.0 / ANCIEN_PPP


def _vieux_pixels(racine, echelle: float) -> str:
    """Avertit si le fichier a été tracé à 90 pixels par pouce.

    Inkscape a changé de définition en 0.92 (2017) : 90 pixels par pouce
    avant, 96 après. Un dessin plus ancien, dont les tailles sont en
    pixels nus, sort **6,25 % trop petit** — un carré de 100 mm en fait
    93,75. C'est assez peu pour passer inaperçu à l'écran, et bien assez
    pour mettre une pièce au rebut.

    On ne corrige pas d'office : on ne devine pas à la place de
    quelqu'un. On le dit, et le dialogue d'import laisse choisir
    l'échelle.
    """
    if abs(echelle - PX_TO_MM) > 1e-12:
        return ''                     # une unité physique était déclarée
    version = ''
    for cle, valeur in racine.attrib.items():
        if str(cle).split('}')[-1] == 'version' and 'inkscape' in str(cle):
            version = str(valeur)
            break
    if not version:
        return ''
    morceaux = version.split('.')
    try:
        majeur, mineur = int(morceaux[0]), int(morceaux[1])
    except (IndexError, ValueError):
        return ''
    if (majeur, mineur) >= (0, 92):
        return ''
    grossir = f'{(FACTEUR_90 - 1) * 100:.2f}'.replace('.', ',')
    return (f'Tracé avec Inkscape {version}, qui comptait '
            f'{ANCIEN_PPP:g} pixels par pouce au lieu de 96. Sans unité '
            f'déclarée, ce dessin sort 6,25 % trop petit ; le rétablir '
            f'demande donc de le grossir de {grossir} %. Le plus sûr est '
            f'de le réenregistrer depuis un Inkscape récent, qui inscrira '
            f'des unités explicites.')


def _document_scale(racine) -> tuple[float, str]:
    """Combien de millimètres vaut une unité utilisateur.

    Trois cas, du plus fiable au moins :

    1. `width` en unité physique **et** `viewBox` — le rapport des deux
       donne l'échelle exacte, et c'est ce qu'écrivent Inkscape et
       Illustrator ;
    2. `viewBox` seule, ou `width` en pixels — l'unité est le pixel CSS,
       1/96 de pouce ;
    3. rien du tout — pixel également, faute de mieux.
    """
    boite = _numbers(racine.get('viewBox', ''))
    largeur_mm = _length_mm(racine.get('width', ''))
    hauteur_mm = _length_mm(racine.get('height', ''))

    if len(boite) >= 4 and boite[2] > 0 and largeur_mm > 0:
        brut = str(racine.get('width', '')).strip().lower()
        if not brut.endswith('px') and not brut.rstrip('0123456789. ') == '':
            return (largeur_mm / boite[2],
                    f'{largeur_mm:g} mm pour {boite[2]:g} unités')
    if len(boite) >= 4 and boite[2] > 0 and hauteur_mm > 0 and boite[3] > 0:
        return (hauteur_mm / boite[3],
                f'{hauteur_mm:g} mm pour {boite[3]:g} unités')
    return (PX_TO_MM, 'unités en pixels CSS (1/96 de pouce)')
