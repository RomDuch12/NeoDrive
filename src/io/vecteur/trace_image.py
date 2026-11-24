"""Vectorisation d'une image / Image tracing.

Un logo, une signature, un dessin au trait n'arrivent pas toujours en
vectoriel: un PNG, un JPG scanné. Ce module en tire des tracés:

- **contours**: le bord des zones sombres, en boucles fermées (Y vers
  le haut, en mm) — à graver au V, à vider en poche, à remplir;
- **traits**: la LIGNE MÉDIANE de tout ce qui est sombre, ouverte —
  l'outil passe UNE fois, comme une plume. Tracer le contour d'une signature de 0,5 mm avec une pointe
  de 0,3 mm l'empâte; sa ligne médiane la redonne;
- **les deux**: les traits fins en ligne médiane, le reste en contour.

Réécriture en Python des étapes du traceur de VectorCraft (crate
`trace`, © 2026 ArtCraft Team and the VectorCraft contributors,
licence MIT — voir THIRD_PARTY_NOTICES.md), elles-mêmes tirées
d'idées publiées:

1. **seuil**: luminance, seuil d'Otsu par défaut (le transparent
   compte pour du blanc);
2. **bruit**: les taches de moins de `bruit` pixels s'effacent, les
   trous de moins de `bruit` pixels se bouchent;
3. **contours**: le masque légèrement flouté (`lissage`), courbe de
   niveau 0,5 (carrés marchants): le bord passe ENTRE les pixels, sans
   escalier; puis Douglas–Peucker (`fidelite`, en pixels);
4. **lignes médianes**: une composante dont la largeur MOYENNE
   (2 × aire / bord) ne dépasse pas la largeur de trait est un trait
   (en mode « traits », toutes); amincie à un pixel (Zhang–Suen, pixel par pixel pour
   garder la topologie: un trait de deux pixels ne disparaît pas);
   coins d'escalier retirés; graphe des pixels (bouts, carrefours);
   éperons courts élagués; polylignes par les centres des pixels,
   adoucies puis simplifiées.

Le noyau ne connaît pas Qt, sauf pour LIRE le fichier (`lire_image`):
Qt décode PNG, JPG, BMP, GIF et TIFF dans l'exe, sans dépendance de
plus. `progress(fraction, texte) -> bool` rend compte; False arrête
sur `Cancelled`.
"""
from __future__ import annotations

import pathlib
from dataclasses import dataclass, field, replace
from typing import Callable, List, Optional, Tuple

import numpy as np

from .dxfimport import Cancelled, ImportReport
from .geometry import Chemin

#: images que l'on vectorise
SUFFIXES = ('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tif', '.tiff')

#: côté maximal tracé, en pixels: au-delà, l'image est réduite (une
#: photo de 12 Mpx ne trace pas un logo plus fidèlement, mais cent
#: fois plus lentement)
COTE_MAX = 2000

MODES = ('contours', 'traits', 'les_deux')

Progress = Optional[Callable[[float, str], bool]]


@dataclass
class Reglages:
    """Ce que l'on demande au traceur."""
    #: 'contours', 'traits' (ligne médiane) ou 'les_deux'
    mode: str = 'contours'
    #: seuil de luminance 0–255 (plus sombre = tracé); None = Otsu
    seuil: Optional[float] = None
    #: tracer le CLAIR (un logo blanc sur fond noir)
    inverser: bool = False
    #: largeur de l'image en mm (le dessin garde ses proportions)
    largeur_mm: float = 50.0
    #: taches et trous plus petits que ça (pixels) ignorés
    bruit: int = 4
    #: flou avant le contour, en pixels (0 = bord en escalier à 45°)
    lissage: float = 1.0
    #: écart toléré entre le tracé et le bord des pixels, en pixels
    fidelite: float = 0.6
    #: mode « les deux »: un trait plus large que ça (mm, en
    #: moyenne) reste un contour
    largeur_trait_mm: float = 1.0


@dataclass
class Trace:
    """Ce que rend le traceur: des polylignes en mm, Y vers le haut."""
    contours: List[List[Tuple[float, float]]] = field(default_factory=list)
    traits: List[List[Tuple[float, float]]] = field(default_factory=list)
    #: largeur moyenne de chaque trait, en mm
    largeurs: List[float] = field(default_factory=list)
    seuil: float = 128.0
    mm_par_pixel: float = 0.1
    taille_px: Tuple[int, int] = (0, 0)
    reduite_de: Optional[Tuple[int, int]] = None

    def resume(self) -> str:
        parts = []
        if self.contours:
            parts.append(f"{len(self.contours)} contour(s)")
        if self.traits:
            moy = (sum(self.largeurs) / len(self.largeurs)
                   if self.largeurs else 0.0)
            parts.append(f"{len(self.traits)} trait(s) "
                         f"(≈ {moy:.2f} mm de large)")
        if not parts:
            parts.append("rien à tracer")
        w, h = self.taille_px
        parts.append(f"seuil {self.seuil:.0f}")
        parts.append(f"{w} × {h} px à {self.mm_par_pixel:.3f} mm/px")
        if self.reduite_de:
            parts.append(f"réduite de {self.reduite_de[0]} × "
                         f"{self.reduite_de[1]} px")
        return " · ".join(parts)


def _avancer(progress: Progress, fraction: float, texte: str) -> None:
    if progress is not None and progress(fraction, texte) is False:
        raise Cancelled(texte or "tracé arrêté")


# ── lecture ─────────────────────────────────────────────────────────

def lire_image(chemin) -> np.ndarray:
    """Luminance (0 noir – 255 blanc) d'une image, en (h, w) float.

    Le transparent compte pour du BLANC: un logo PNG sur fond
    transparent se trace comme sur papier."""
    from PySide6.QtGui import QImage
    image = QImage(str(chemin))
    if image.isNull():
        raise ValueError(f"image illisible: {pathlib.Path(chemin).name}")
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = image.width(), image.height()
    ligne = image.bytesPerLine()
    brut = np.frombuffer(image.constBits(), dtype=np.uint8,
                         count=ligne * h).reshape(h, ligne)
    rgba = brut[:, :w * 4].reshape(h, w, 4).astype(np.float32)
    lum = (0.299 * rgba[..., 0] + 0.587 * rgba[..., 1]
           + 0.114 * rgba[..., 2])
    alpha = rgba[..., 3] / 255.0
    return lum * alpha + 255.0 * (1.0 - alpha)


def reduire(gris: np.ndarray, cote_max: int = COTE_MAX) -> np.ndarray:
    """L'image ramenée à `cote_max` pixels sur son grand côté
    (moyenne par blocs: le seuil voit encore les traits fins)."""
    h, w = gris.shape
    k = int(np.ceil(max(h, w) / float(cote_max)))
    if k <= 1:
        return gris
    h2, w2 = h // k, w // k
    g = gris[:h2 * k, :w2 * k].reshape(h2, k, w2, k)
    return g.mean(axis=(1, 3))


# ── seuil et bruit ──────────────────────────────────────────────────

def seuil_otsu(gris: np.ndarray) -> float:
    """Le seuil qui sépare le mieux deux populations de gris."""
    hist, bords = np.histogram(np.clip(gris, 0, 255), bins=256,
                               range=(0.0, 256.0))
    hist = hist.astype(np.float64)
    total = hist.sum()
    if total <= 0:
        return 128.0
    p = hist / total
    omega = np.cumsum(p)
    mu = np.cumsum(p * np.arange(256))
    mu_t = mu[-1]
    with np.errstate(divide='ignore', invalid='ignore'):
        sigma_b = (mu_t * omega - mu) ** 2 / (omega * (1.0 - omega))
    sigma_b = np.nan_to_num(sigma_b, nan=-1.0, posinf=-1.0)
    if sigma_b.max() <= 0:
        return 128.0
    # Une image en deux tons a un PLATEAU de seuils équivalents: on
    # prend son milieu (le premier, 1, ne garderait que le noir pur
    # d'un logo lissé). Le seuil est la borne haute de la classe sombre.
    meilleurs = np.flatnonzero(sigma_b >= sigma_b.max() * (1 - 1e-9))
    return float(meilleurs[0] + meilleurs[-1]) / 2.0 + 1.0


def masque(gris: np.ndarray, reglages: Reglages) -> Tuple[np.ndarray, float]:
    """Les pixels à tracer, et le seuil retenu."""
    s = (seuil_otsu(gris) if reglages.seuil is None
         else float(reglages.seuil))
    m = gris < s
    if reglages.inverser:
        m = ~m
    return m, s


def debruiter(m: np.ndarray, aire: int) -> np.ndarray:
    """Taches de moins de `aire` pixels effacées, trous de moins de
    `aire` pixels bouchés (le fond qui touche le bord reste fond)."""
    if aire <= 1 or not m.any():
        return m
    from scipy import ndimage
    huit = np.ones((3, 3), dtype=bool)
    lab, n = ndimage.label(m, structure=huit)
    if n:
        tailles = np.bincount(lab.ravel())
        petits = tailles < aire
        petits[0] = False
        m = m & ~petits[lab]
    fond = ~m
    lab, n = ndimage.label(fond)          # 4-connexe: les trous
    if n:
        tailles = np.bincount(lab.ravel())
        bord = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0],
                                         lab[:, -1]]))
        petits = tailles < aire
        petits[0] = False
        petits[bord] = False
        m = m | petits[lab]
    return m


# ── contours ────────────────────────────────────────────────────────

def _simplifier(points: np.ndarray, tolerance: float,
                ferme: bool) -> np.ndarray:
    """Douglas–Peucker (shapely), sans perdre le bouclage."""
    if len(points) < 3 or tolerance <= 0:
        return points
    from shapely.geometry import LineString
    ligne = LineString(points)
    s = ligne.simplify(tolerance, preserve_topology=False)
    pts = np.asarray(s.coords, dtype=float)
    if ferme and len(pts) < 4:
        return points
    return pts


def contours_px(m: np.ndarray, lissage: float = 1.0,
                fidelite: float = 0.6, aire_min: float = 0.0,
                progress: Progress = None) -> List[np.ndarray]:
    """Les bords du masque, en boucles fermées, en pixels (x à
    droite, y vers le bas, centre des pixels aux entiers)."""
    if not m.any():
        return []
    import contourpy
    champ = np.pad(m.astype(np.float64), 2)
    if lissage > 0:
        from scipy import ndimage
        champ = ndimage.gaussian_filter(champ, float(lissage))
    gen = contourpy.contour_generator(
        z=champ, line_type=contourpy.LineType.Separate)
    lignes = gen.lines(0.5)
    sortie = []
    for k, ligne in enumerate(lignes):
        if progress is not None and k % 200 == 0:
            _avancer(progress, 0.5 + 0.4 * k / max(1, len(lignes)),
                     "contours")
        pts = np.asarray(ligne, dtype=float) - 2.0
        if len(pts) < 4:
            continue
        if not np.allclose(pts[0], pts[-1]):
            pts = np.vstack([pts, pts[:1]])
        x, y = pts[:, 0], pts[:, 1]
        aire = 0.5 * abs(np.dot(x[:-1], y[1:]) - np.dot(x[1:], y[:-1]))
        if aire < max(aire_min, 0.5):
            continue
        sortie.append(_simplifier(pts, fidelite, True))
    return sortie


# ── lignes médianes ─────────────────────────────────────────────────

_VOISINS = ((-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1),
            (-1, -1))     # P2..P9 de Zhang–Suen: N, NE, E, SE, S, SO, O, NO


def _voisins_tableau(a: np.ndarray) -> List[np.ndarray]:
    """Les huit voisins de chaque pixel (bord = fond), dans l'ordre
    P2..P9."""
    p = np.pad(a, 1)
    h, w = a.shape
    return [p[1 + dy:1 + dy + h, 1 + dx:1 + dx + w] for dy, dx in _VOISINS]


def _zs_ok(a: np.ndarray, y: int, x: int, passe: int) -> bool:
    """Le pixel (y, x) peut-il partir à cette sous-passe ?"""
    h, w = a.shape
    v = []
    for dy, dx in _VOISINS:
        yy, xx = y + dy, x + dx
        v.append(bool(0 <= yy < h and 0 <= xx < w and a[yy, xx]))
    b = sum(v)
    if b < 2 or b > 6:
        return False
    transitions = sum(1 for i in range(8) if not v[i] and v[(i + 1) % 8])
    if transitions != 1:
        return False
    p2, p4, p6, p8 = v[0], v[2], v[4], v[6]
    if passe == 0:
        return not (p2 and p4 and p6) and not (p4 and p6 and p8)
    return not (p2 and p4 and p8) and not (p2 and p6 and p8)


def amincir(m: np.ndarray, progress: Progress = None) -> np.ndarray:
    """Squelette d'un pixel de large (Zhang–Suen).

    Les candidats d'une sous-passe se trouvent en bloc (numpy), puis
    chacun est revérifié sur l'état COURANT avant de partir: en
    parallèle pur, un trait de deux pixels disparaissait en entier."""
    a = m.copy()
    tour = 0
    while True:
        change = False
        for passe in (0, 1):
            v = _voisins_tableau(a)
            b = sum(x.astype(np.int8) for x in v)
            trans = sum(((~v[i]) & v[(i + 1) % 8]).astype(np.int8)
                        for i in range(8))
            p2, p4, p6, p8 = v[0], v[2], v[4], v[6]
            if passe == 0:
                cond = ~(p2 & p4 & p6) & ~(p4 & p6 & p8)
            else:
                cond = ~(p2 & p4 & p8) & ~(p2 & p6 & p8)
            cand = a & (b >= 2) & (b <= 6) & (trans == 1) & cond
            for y, x in zip(*np.nonzero(cand)):
                if _zs_ok(a, int(y), int(x), passe):
                    a[y, x] = False
                    change = True
        tour += 1
        if progress is not None:
            _avancer(progress, min(0.55, 0.2 + 0.03 * tour), "amincissement")
        if not change or tour > 500:
            return a


def _retirer_escaliers(a: np.ndarray) -> np.ndarray:
    """Les coins d'escalier qui ne relient rien: un pixel dont les
    voisins se touchent déjà entre eux s'en va (le trait reste
    connexe et devient 8-connexe, sans faux carrefours)."""
    a = a.copy()
    for y, x in zip(*np.nonzero(a)):
        y, x = int(y), int(x)
        voisins = [(y + dy, x + dx) for dy, dx in _VOISINS
                   if 0 <= y + dy < a.shape[0] and 0 <= x + dx < a.shape[1]
                   and a[y + dy, x + dx]]
        if len(voisins) < 2:
            continue
        # les voisins forment-ils un seul groupe, sans passer par (y, x) ?
        reste = set(voisins)
        pile = [voisins[0]]
        reste.discard(voisins[0])
        while pile:
            cy, cx = pile.pop()
            for q in list(reste):
                if abs(q[0] - cy) <= 1 and abs(q[1] - cx) <= 1:
                    reste.discard(q)
                    pile.append(q)
        if not reste:
            a[y, x] = False
    return a


def _graphe(sq: np.ndarray):
    """Les courses du squelette entre bouts et carrefours.

    Rend (courses, noeud_de): chaque course est une liste de pixels
    (y, x) d'un nœud (ou bout) à un autre; les anneaux sans nœud sont
    fermés (premier = dernier)."""
    from scipy import ndimage
    h, w = sq.shape
    v = _voisins_tableau(sq)
    deg = sum(x.astype(np.int8) for x in v) * sq
    jonctions = sq & (deg >= 3)
    lab, _n = ndimage.label(jonctions, structure=np.ones((3, 3), bool))
    noeud = {}
    for y, x in zip(*np.nonzero(jonctions)):
        noeud[(int(y), int(x))] = ('j', int(lab[y, x]))
    for y, x in zip(*np.nonzero(sq & (deg <= 1))):
        noeud[(int(y), int(x))] = ('b', (int(y), int(x)))

    def voisins(p):
        y, x = p
        for dy, dx in _VOISINS:
            yy, xx = y + dy, x + dx
            if 0 <= yy < h and 0 <= xx < w and sq[yy, xx]:
                yield (yy, xx)

    vus = set()
    courses = []
    liens = set()
    for depart, ident in noeud.items():
        for q in voisins(depart):
            if q in noeud:
                if noeud[q] == ident:
                    continue
                cle = frozenset((depart, q))
                if cle not in liens:
                    liens.add(cle)
                    courses.append([depart, q])
                continue
            if q in vus:
                continue
            course = [depart, q]
            vus.add(q)
            prec, cour = depart, q
            while True:
                suivant = fin = None
                for r in voisins(cour):
                    if r == prec:
                        continue
                    if r in noeud:
                        # son propre carrefour: seulement au bout d'une
                        # boucle, pas au premier pas (ses pixels se
                        # touchent tous)
                        if noeud[r] == ident and len(course) < 4:
                            continue
                        fin = fin or r
                    elif r not in vus and suivant is None:
                        suivant = r
                if fin is not None:
                    # un nœud à côté: la course s'y arrête, sans
                    # filer dans la branche voisine
                    course.append(fin)
                    break
                if suivant is None:
                    break
                course.append(suivant)
                vus.add(suivant)
                prec, cour = cour, suivant
            courses.append(course)
    # les anneaux: des pixels de degré 2 que rien n'a visités
    for y, x in zip(*np.nonzero(sq)):
        p = (int(y), int(x))
        if p in vus or p in noeud:
            continue
        course = [p]
        vus.add(p)
        prec, cour = None, p
        while True:
            suivant = next((r for r in voisins(cour)
                            if r != prec and r not in vus), None)
            if suivant is None:
                break
            course.append(suivant)
            vus.add(suivant)
            prec, cour = cour, suivant
        course.append(p)
        courses.append(course)
    return courses, noeud


def _longueur(pts) -> float:
    a = np.asarray(pts, dtype=float)
    if len(a) < 2:
        return 0.0
    return float(np.hypot(*np.diff(a, axis=0).T).sum())


def _elaguer(courses, noeud, eperon):
    """Retire les éperons (bout ↔ carrefour plus courts que
    `eperon(course)`), puis soude les courses qu'un carrefour ne
    sépare plus."""
    def cle(p):
        n = noeud.get(p)
        return n if n is not None else ('p', p)

    garde = []
    for c in courses:
        a, b = noeud.get(c[0]), noeud.get(c[-1])
        bouts = [n for n in (a, b) if n is not None and n[0] == 'b']
        carrefours = [n for n in (a, b) if n is not None and n[0] == 'j']
        if len(bouts) == 1 and carrefours and _longueur(c) < eperon(c):
            continue
        garde.append(c)
    # soudure aux carrefours de degré 2
    for _tour in range(3):
        degre = {}
        for c in garde:
            if c[0] == c[-1] and noeud.get(c[0]) is None:
                continue
            for p in (c[0], c[-1]):
                k = cle(p)
                if k[0] == 'j':
                    degre[k] = degre.get(k, 0) + 1
        soude = False
        for k, d in degre.items():
            if d != 2:
                continue
            deux = [c for c in garde if cle(c[0]) == k or cle(c[-1]) == k]
            if len(deux) != 2 or deux[0] is deux[1]:
                continue
            c1, c2 = deux
            if cle(c1[-1]) != k:
                c1 = c1[::-1]
            if cle(c2[0]) != k:
                c2 = c2[::-1]
            garde = [c for c in garde if c is not deux[0] and c is not deux[1]]
            garde.append(c1 + c2[1:])
            soude = True
            break
        if not soude:
            break
    return garde


def _prolonger(courses, noeud, angle_max: float = 35.0):
    """À un carrefour, les branches qui se prolongent en ligne
    droite ne font plus qu'un trait: une croix se grave en DEUX
    passes, pas en quatre (moins de levées d'outil)."""
    import math

    def cle(p):
        n = noeud.get(p)
        return n if n is not None else ('p', p)

    def sortie(c):
        """Direction de la course en quittant son premier point."""
        a = np.asarray(c[:6], dtype=float)
        d = a[-1] - a[0]
        n = math.hypot(d[0], d[1])
        return d / n if n > 0 else None

    seuil = -math.cos(math.radians(angle_max))
    for _tour in range(200):
        fait = False
        carrefours = {}
        for c in courses:
            if cle(c[0]) == cle(c[-1]):
                continue                  # boucle: on la laisse
            for bout in (0, -1):
                k = cle(c[bout])
                if k[0] == 'j':
                    carrefours.setdefault(k, []).append(c)
        for k, lot in carrefours.items():
            if len(lot) < 2:
                continue
            orientees = [c if cle(c[0]) == k else c[::-1] for c in lot]
            dirs = [sortie(c) for c in orientees]
            meilleur = None
            for i in range(len(lot)):
                for j in range(i + 1, len(lot)):
                    if dirs[i] is None or dirs[j] is None:
                        continue
                    cos = float(np.dot(dirs[i], dirs[j]))
                    if cos <= seuil and (meilleur is None
                                         or cos < meilleur[0]):
                        meilleur = (cos, i, j)
            if meilleur is None:
                continue
            _cos, i, j = meilleur
            neuf = orientees[i][::-1] + orientees[j][1:]
            courses = [c for c in courses
                       if c is not lot[i] and c is not lot[j]]
            courses.append(neuf)
            fait = True
            break
        if not fait:
            break
    return courses


def _adoucir(pts: np.ndarray, ferme: bool) -> np.ndarray:
    """Moyenne glissante sur 3 points (les bouts restent en place):
    l'escalier des centres de pixels s'efface."""
    if len(pts) < 4:
        return pts
    if ferme:
        p = pts[:-1]
        q = (np.roll(p, 1, axis=0) + 2 * p + np.roll(p, -1, axis=0)) / 4.0
        return np.vstack([q, q[:1]])
    q = pts.copy()
    q[1:-1] = (pts[:-2] + 2 * pts[1:-1] + pts[2:]) / 4.0
    return q


def largeurs_composantes(m: np.ndarray):
    """(étiquettes, nombre, largeur moyenne de chaque composante en
    pixels). Largeur = 2 × aire / pixels de bord: un trait de w pixels
    et de longueur L a une aire wL et deux bords de L. Un croisement
    ou un point plus gras ne fait pas d'un trait une surface (la plus
    grande largeur rejetait une écriture entière pour un « e »)."""
    from scipy import ndimage
    lab, n = ndimage.label(m, structure=np.ones((3, 3), bool))
    if not n:
        return lab, 0, np.zeros(1)
    bord = m & ~ndimage.binary_erosion(m)
    aire = np.bincount(lab.ravel(), minlength=n + 1).astype(float)
    nb = np.bincount(lab[bord].ravel(), minlength=n + 1).astype(float)
    largeur = 2.0 * aire / np.maximum(nb, 1.0)
    largeur[0] = 0.0
    return lab, n, largeur


def lignes_mediane(m: np.ndarray, largeur_max_px: float,
                   fidelite: float = 0.6, progress: Progress = None,
                   tout: bool = False):
    """Les lignes médianes des traits fins du masque (`tout`: de
    toutes les composantes, même larges — mode « traits »).

    Rend (traits en pixels [(x, y)…], largeurs en pixels, masque des
    pixels pris par les traits)."""
    from scipy import ndimage
    pris = np.zeros_like(m, dtype=bool)
    if not m.any():
        return [], [], pris
    lab, n, largeur = largeurs_composantes(m)
    if not n:
        return [], [], pris
    fins = np.ones(n + 1, dtype=bool) if tout else \
        (largeur <= largeur_max_px)
    fins[0] = False
    pris = fins[lab] & m
    if not pris.any():
        return [], [], pris
    _avancer(progress, 0.2, "amincissement")
    sq = _retirer_escaliers(amincir(pris, progress))
    _avancer(progress, 0.6, "graphe des traits")
    courses, noeud = _graphe(sq)

    def eperon(course):
        """Un éperon d'amincissement mesure au plus la largeur de son
        trait."""
        y, x = course[0]
        return max(2.0, float(largeur[lab[y, x]]))
    courses = _elaguer(courses, noeud, eperon)
    courses = _prolonger(courses, noeud)
    # position des carrefours: le milieu de leurs pixels
    groupes = {}
    for p, ident in noeud.items():
        if ident[0] == 'j':
            groupes.setdefault(ident, []).append(p)
    centre = {k: (float(np.mean([q[1] for q in v])),
                  float(np.mean([q[0] for q in v])))
              for k, v in groupes.items()}
    traits, largeurs = [], []
    lab_traits, _nt = ndimage.label(pris, structure=np.ones((3, 3), bool))
    pixels_par_comp = np.bincount(lab_traits.ravel())
    long_par_comp = {}
    brutes = []
    for c in courses:
        pts = []
        for p in c:
            ident = noeud.get(p)
            if ident is not None and ident[0] == 'j':
                pts.append(centre[ident])
            else:
                pts.append((float(p[1]), float(p[0])))
        a = np.asarray(pts, dtype=float)
        if len(a) < 2:
            continue
        comp = int(lab_traits[c[0][0], c[0][1]])
        long_par_comp[comp] = long_par_comp.get(comp, 0.0) + _longueur(a)
        brutes.append((a, comp, c[0] == c[-1] and len(c) > 2))
    for a, comp, ferme in brutes:
        a = _adoucir(a, ferme)
        a = _simplifier(a, fidelite, ferme)
        if len(a) < 2:
            continue
        traits.append(a)
        longueur = long_par_comp.get(comp, 0.0)
        largeurs.append(float(pixels_par_comp[comp]) / max(1.0, longueur))
    return traits, largeurs, pris


# ── tout ensemble ───────────────────────────────────────────────────

def tracer(source, reglages: Reglages = None,
           progress: Progress = None) -> Trace:
    """Vectorise une image: un chemin de fichier, ou une luminance
    (h, w) déjà lue."""
    reglages = reglages or Reglages()
    if reglages.mode not in MODES:
        raise ValueError(f"mode inconnu: {reglages.mode}")
    _avancer(progress, 0.0, "lecture de l'image")
    gris = (lire_image(source) if not isinstance(source, np.ndarray)
            else np.asarray(source, dtype=np.float32))
    h0, w0 = gris.shape
    gris = reduire(gris)
    h, w = gris.shape
    trace = Trace(taille_px=(w, h))
    if (w, h) != (w0, h0):
        trace.reduite_de = (w0, h0)
    s = float(reglages.largeur_mm) / max(1, w)
    trace.mm_par_pixel = s
    m, trace.seuil = masque(gris, reglages)
    _avancer(progress, 0.1, "taches et trous")
    m = debruiter(m, int(reglages.bruit))

    def en_mm(pts: np.ndarray) -> List[Tuple[float, float]]:
        return [(float(x) * s, float(h - 1 - y) * s) for x, y in pts]

    reste = m
    if reglages.mode in ('traits', 'les_deux'):
        largeur_px = max(1.0, reglages.largeur_trait_mm / max(s, 1e-9))
        traits, largeurs, pris = lignes_mediane(
            m, largeur_px, reglages.fidelite,
            progress=None if progress is None else
            (lambda f, t: progress(0.1 + 0.5 * f, t)),
            tout=reglages.mode == 'traits')
        trace.traits = [en_mm(t) for t in traits]
        trace.largeurs = [lg * s for lg in largeurs]
        reste = m & ~pris
    if reglages.mode in ('contours', 'les_deux'):
        _avancer(progress, 0.6, "contours")
        trace.contours = [en_mm(c) for c in contours_px(
            reste, reglages.lissage, reglages.fidelite,
            aire_min=float(reglages.bruit), progress=progress)]
    _avancer(progress, 1.0, "tracé fini")
    return trace


def calques_de(trace: Trace, tolerance: float = 0.02):
    """Le tracé en calques du noyau vectoriel: {'contours': [Chemin],
    'traits': [Chemin]} (calques vides omis)."""
    calques = {}
    contours = []
    for c in trace.contours:
        ch = Chemin(c[:-1] if len(c) > 2 and c[0] == c[-1] else c,
                    tolerance)
        ch.fermer()
        contours.append(ch)
    if contours:
        calques['contours'] = contours
    traits = [Chemin(t, tolerance) for t in trace.traits if len(t) >= 2]
    if traits:
        calques['traits'] = traits
    return calques


def rapport_de(trace: Trace, calques: dict) -> ImportReport:
    """Le compte rendu d'import d'un tracé."""
    rapport = ImportReport()
    rapport.layers = {k: len(v) for k, v in calques.items()}
    rapport.polylines = sum(rapport.layers.values())
    pts = [p for v in calques.values() for ch in v for p in ch]
    if pts:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        rapport.extent = (min(xs), min(ys), max(xs), max(ys))
    rapport.notes.append("image vectorisée: " + trace.resume())
    return rapport


def lire(chemin, reglages: Reglages = None, progress: Progress = None,
         tolerance_mm: float = 0.02):
    """Point d'entrée du noyau vectoriel: `(calques, rapport)`."""
    trace = tracer(chemin, reglages, progress)
    calques = calques_de(trace, tolerance_mm)
    return calques, rapport_de(trace, calques)


def avec(reglages: Reglages, **changes) -> Reglages:
    """Une copie des réglages, quelques champs changés."""
    return replace(reglages, **changes)
