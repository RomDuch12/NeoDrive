"""Moteur d'usinage 3D (3 axes) d'une pièce STEP, avec une gamme de fraises.

Le principe: la pièce, vue de dessus, est une CARTE DE HAUTEURS (pour
chaque petite case du plan, la cote du dessus de la matière à garder).
Tout le reste s'en déduit:

- pour chaque outil (plat, boule, cône), la carte des cotes où son
  CENTRE peut descendre sans entailler la pièce (une « dilatation » de
  la carte par la forme de l'outil, surépaisseur comprise) — prudente
  par construction: elle peut laisser un peu, jamais mordre;
- l'ÉBAUCHE par niveaux: à chaque cote, le centre de l'outil passe en
  anneaux parallèles aux parois (courbes de niveau de la distance aux
  parois), là où il reste de la matière à enlever, en laissant la
  surépaisseur; les fonds plats de la pièce sont des niveaux exacts;
  l'outil entre en rampe;
- la REPRISE: une fraise plus petite ne passe que là où la précédente
  a laissé de la matière — les coins, les fentes étroites (la matière
  restante est connue: chaque étape est simulée, src/core/enlevement);
- la FINITION: par niveaux, sans surépaisseur, pour une pièce à
  parois droites et fonds plats; par BALAYAGE (passes parallèles, la
  pointe suivant la surface) pour une forme libre, à la fraise boule
  si la bibliothèque en a une;
- le CONTRÔLE: la matière simulée au bout de la gamme, comparée à la
  pièce: aucune entaille, et ce qui reste (les rayons que l'outil ne
  peut pas faire).

`proposer_gamme` choisit les outils dans la bibliothèque à partir de la
pièce (largeur des poches, rayons des coins, profondeur, longueur
utile des fraises, surfaces gauches) et dit pourquoi. `calculer` rend,
pour chaque étape, le code d'une séquence Datron ($$$) — une opération
« Séquence Datron » du programme, avec son outil.

Coordonnées MACHINE: le dessus de la pièce en Z 0, X/Y comme le dessin.
"""

import math
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

#: côté maxi de la grille (cases): au-delà, le pas grossit
CASES_MAX = 360000
#: pas de grille mini (mm)
PAS_MIN = 0.04
#: anneaux de la décomposition d'un outil non plat
ANNEAUX_OUTIL = 32
#: tolérance de simplification des parcours (mm)
TOLERANCE = 0.008
#: au-delà, un pas demandé grossit (mémoire: une dizaine de cartes de
#: cette taille en flottants)
CASES_PLAFOND = 4000000
#: la précision du calcul, réglée par l'utilisateur (octobre 2026):
#: clé -> (libellé, pas de la carte en mm ou None = auto, tolérance des
#: parcours en mm)
PRECISIONS = {
    'auto': ("Auto (selon la taille de la pièce)", None, TOLERANCE),
    'brouillon': ("Brouillon — 0,5 mm", 0.5, 0.05),
    'normale': ("Normale — 0,2 mm", 0.2, 0.02),
    'fine': ("Fine — 0,1 mm", 0.1, 0.01),
    'tres_fine': ("Très fine — 0,05 mm", 0.05, 0.005),
    'mesure': ("Sur mesure", None, None),
}
#: angle des rampes d'entrée (degrés)
ANGLE_RAMPE = 3.0
#: dégagement au-dessus du dessus de la pièce (mm)
APPROCHE = 1.0
#: hauteur de sécurité du premier placement (mm)
SECURITE = 15.0
#: épaisseur de matière qu'on ignore (mm)
EPS_MATIERE = 0.01

STRATEGIES = ("niveaux", "balayage", "zconstant")
#: une paroi est raide au-delà de cette pente (degrés depuis
#: l'horizontale): le balayage y laisse des marches, le Z constant la
#: longe tranche par tranche
PENTE_RAIDE = 30.0
ROLES = ("ebauche", "reprise", "finition")


# ───────────────────────── la grille ─────────────────────────

class Grille:
    """Une grille de cases carrées sur [x0, x0 + nx·pas] × [y0, …]."""

    def __init__(self, xmin, xmax, ymin, ymax, pas=None,
                 cases_max: int = CASES_MAX):
        lx, ly = max(xmax - xmin, 1e-3), max(ymax - ymin, 1e-3)
        #: le pas demandé quand il a fallu le grossir (sinon None)
        self.pas_demande = None
        if pas is None:
            pas = max(PAS_MIN, math.sqrt(lx * ly / cases_max))
        elif lx * ly / (float(pas) ** 2) > CASES_PLAFOND:
            self.pas_demande = float(pas)
            pas = math.sqrt(lx * ly / CASES_PLAFOND)
        self.pas = float(pas)
        self.nx = max(2, int(math.ceil(lx / self.pas)))
        self.ny = max(2, int(math.ceil(ly / self.pas)))
        self.x0, self.y0 = float(xmin), float(ymin)
        self.xc = self.x0 + (np.arange(self.nx) + 0.5) * self.pas
        self.yc = self.y0 + (np.arange(self.ny) + 0.5) * self.pas

    def indices(self, x, y):
        i = np.clip(((np.asarray(x) - self.x0) / self.pas).astype(int),
                    0, self.nx - 1)
        j = np.clip(((np.asarray(y) - self.y0) / self.pas).astype(int),
                    0, self.ny - 1)
        return j, i

    def brut(self, z_bas, z_haut=0.0):
        """Un brut (enlevement.Brut) sur exactement cette grille."""
        from src.core.enlevement import Brut
        b = Brut(self.x0, self.x0 + self.nx * self.pas,
                 self.y0, self.y0 + self.ny * self.pas, z_bas, z_haut,
                 pas=self.pas)
        # case pour case la même grille (l'arrondi pouvait donner une
        # rangée de plus au brut)
        b.nx, b.ny = self.nx, self.ny
        b.x0, b.y0, b.pas = self.x0, self.y0, self.pas
        b.xc, b.yc = self.xc.copy(), self.yc.copy()
        b.h = np.full((self.ny, self.nx), float(z_haut))
        return b


def carte_piece(triangles, grille: Grille, fond: float) -> np.ndarray:
    """La carte de hauteurs du DESSUS de la pièce: pour chaque case, la
    plus haute cote de ses triangles; `fond` là où il n'y a pas de
    pièce. Les triangles sont échantillonnés plus fin que la grille."""
    H = np.full((grille.ny, grille.nx), -np.inf)
    T = np.asarray(triangles, dtype=float)
    if not len(T):
        return np.full((grille.ny, grille.nx), float(fond))
    pas = grille.pas
    # 1. chaque case dont le CENTRE tombe dans un triangle (vu de
    # dessus) prend la cote du triangle à cet endroit — exact, sans
    # trou, même pour une grande face plane
    xs, ys = T[:, :, 0], T[:, :, 1]
    i0 = np.floor((xs.min(axis=1) - grille.x0) / pas - 0.5).astype(int)
    i1 = np.ceil((xs.max(axis=1) - grille.x0) / pas - 0.5).astype(int)
    j0 = np.floor((ys.min(axis=1) - grille.y0) / pas - 0.5).astype(int)
    j1 = np.ceil((ys.max(axis=1) - grille.y0) / pas - 0.5).astype(int)
    i0, j0 = np.clip(i0, 0, grille.nx - 1), np.clip(j0, 0, grille.ny - 1)
    i1, j1 = np.clip(i1, 0, grille.nx - 1), np.clip(j1, 0, grille.ny - 1)
    for k in range(len(T)):
        if i1[k] < i0[k] or j1[k] < j0[k]:
            continue
        a, b, c = T[k]
        det = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(det) < 1e-14:
            continue                    # vu de dessus: un trait
        X = grille.xc[i0[k]:i1[k] + 1][None, :]
        Y = grille.yc[j0[k]:j1[k] + 1][:, None]
        la = ((b[1] - c[1]) * (X - c[0]) + (c[0] - b[0]) * (Y - c[1])) / det
        lb = ((c[1] - a[1]) * (X - c[0]) + (a[0] - c[0]) * (Y - c[1])) / det
        lc = 1.0 - la - lb
        dedans = (la >= -1e-9) & (lb >= -1e-9) & (lc >= -1e-9)
        if not dedans.any():
            continue
        z = la * a[2] + lb * b[2] + lc * c[2]
        fen = H[j0[k]:j1[k] + 1, i0[k]:i1[k] + 1]
        np.maximum(fen, np.where(dedans, z, -np.inf), out=fen)
    # 2. les arêtes et les sommets, échantillonnés: une paroi verticale
    # (un trait vu de dessus) marque sa crête; un petit triangle entre
    # deux centres de cases n'est pas perdu
    for a, b in ((0, 1), (1, 2), (2, 0)):
        lg = np.linalg.norm(T[:, b, :2] - T[:, a, :2], axis=1)
        n = np.clip(np.ceil(lg / (0.5 * pas)).astype(int), 1, 4000)
        for nn in np.unique(n):
            sel = n == nn
            t = np.linspace(0.0, 1.0, nn + 1)[None, :, None]
            p = (T[sel, a][:, None] * (1 - t) + T[sel, b][:, None] * t
                 ).reshape(-1, 3)
            j, i = grille.indices(p[:, 0], p[:, 1])
            dans = ((p[:, 0] >= grille.x0) & (p[:, 1] >= grille.y0)
                    & (p[:, 0] < grille.x0 + grille.nx * pas)
                    & (p[:, 1] < grille.y0 + grille.ny * pas))
            np.maximum.at(H, (j[dans], i[dans]), p[dans, 2])
    return np.where(np.isfinite(H), np.maximum(H, fond), float(fond))


# ───────────────────────── les outils ─────────────────────────

def _lignes_max(H, demi):
    """Le maximum glissant sur 2·demi + 1 cases, le long des lignes
    (hors de la grille: rien)."""
    from scipy.ndimage import maximum_filter1d
    if demi <= 0:
        return H
    return maximum_filter1d(H, size=2 * demi + 1, axis=1, mode='constant',
                            cval=-np.inf)


def dilater_disque(H, rayon_cases: float, cache=None) -> np.ndarray:
    """max de H sur le disque de rayon `rayon_cases` autour de chaque
    case (décomposé en maxima de lignes)."""
    r = float(rayon_cases)
    ri = int(math.floor(r))
    ny = H.shape[0]
    cache = {} if cache is None else cache
    sortie = np.full(H.shape, -np.inf)
    for dy in range(-ri, ri + 1):
        demi = int(math.floor(math.sqrt(max(r * r - dy * dy, 0.0))))
        if demi not in cache:
            cache[demi] = _lignes_max(H, demi)
        m = cache[demi]
        if dy >= 0:
            np.maximum(sortie[:ny - dy], m[dy:], out=sortie[:ny - dy])
        else:
            np.maximum(sortie[-dy:], m[:ny + dy], out=sortie[-dy:])
    return sortie


def dilater_balayage(H, rayon_cases: float, le_long_de_y: bool = False):
    """(centres, bords): le max de H sous l'outil d'un BALAYAGE, dont le
    centre est au milieu de sa rangée en travers de la passe.
    `centres[j, i]`: l'outil centré sur la case i; `bords[j, i]`: centré
    sur le bord entre les cases i et i + 1 le long de la passe (une
    colonne de moins). Une case compte dès que le disque de l'outil la
    touche: la règle exacte, sans arrondi.

    Entre le centre d'une case et son bord, l'outil ne touche rien de
    plus que depuis l'un ou l'autre: `passes_balayage` s'en sert pour ne
    jamais mordre, sans rien perdre sur les pentes."""
    if le_long_de_y:
        c, b = dilater_balayage(np.ascontiguousarray(H.T), rayon_cases)
        return c.T, b.T
    r = max(float(rayon_cases), 1e-9)
    ny, nx = H.shape
    centres = np.full((ny, nx), -np.inf)
    bords = np.full((ny, max(nx - 1, 0)), -np.inf)
    cache = {}

    def lignes(demi):
        if demi not in cache:
            cache[demi] = _lignes_max(H, demi)
        return cache[demi]

    # la rangée dy est touchée si |dy| − ½ < r; sur elle, à s = √(r² −
    # (|dy| − ½)²) du centre de l'outil
    n_dy = int(math.ceil(r + 0.5)) - 1
    for dy in range(-n_dy, n_dy + 1):
        ey = max(abs(dy) - 0.5, 0.0)
        if ey >= r:
            continue
        s = math.sqrt(r * r - ey * ey)
        # centré sur la case: la case dx est touchée si |dx| − ½ < s
        mc = lignes(int(math.ceil(s + 0.5)) - 1)
        # centré sur le bord: ⌈s⌉ cases de chaque côté
        w = lignes(int(math.ceil(s)) - 1)
        mb = np.maximum(w[:, :-1], w[:, 1:])
        for sortie, m in ((centres, mc), (bords, mb)):
            if dy >= 0:
                np.maximum(sortie[:ny - dy], m[dy:], out=sortie[:ny - dy])
            else:
                np.maximum(sortie[-dy:], m[:ny + dy], out=sortie[-dy:])
    return centres, bords


def _anneaux_outil(forme: Dict, R: float) -> List[Tuple[float, float]]:
    """Un outil rond (boule, cône) en anneaux de hauteur égale: [(rayon
    de l'anneau, hauteur du profil à son bord intérieur)] — l'anneau
    entier est pris à la hauteur de son bord intérieur (prudent)."""
    hmax = float(profil(forme, R))
    rayons = []
    for k in range(1, ANNEAUX_OUTIL + 1):
        h = hmax * k / ANNEAUX_OUTIL
        # le rayon où le profil atteint h
        bas, haut = 0.0, R
        for _ in range(30):
            mil = (bas + haut) / 2
            if float(profil(forme, mil)) < h:
                bas = mil
            else:
                haut = mil
        rayons.append(haut)
    rayons[-1] = R
    sortie = []
    precedent = 0.0
    for r in rayons:
        sortie.append((r, float(profil(forme, precedent))))
        precedent = r
    return sortie


def profil(forme: Dict, d):
    """Hauteur de la surface de l'outil au-dessus de sa pointe, à la
    distance d de l'axe."""
    R = float(forme.get('rayon', 1.0))
    d = np.asarray(d, dtype=float)
    genre = forme.get('forme', 'plate')
    if genre == 'boule':
        return R - np.sqrt(np.clip(R * R - d * d, 0.0, None))
    if genre == 'cone':
        demi = math.radians(max(1.0, float(forme.get('angle') or 90.0)) / 2)
        rp = max(0.0, float(forme.get('pointe') or 0.0) / 2.0)
        return np.clip(d - rp, 0.0, None) / math.tan(demi)
    return np.zeros_like(d)


def centre_outil(H, forme: Dict, pas: float, surepaisseur: float = 0.0,
                 jeu: float = None) -> np.ndarray:
    """La cote mini de la POINTE de l'outil au-dessus de chaque case,
    pour qu'il ne descende jamais sous la pièce plus `surepaisseur`.
    Exacte pour une fraise plate; pour une boule ou un cône, des
    anneaux de hauteur égale — prudente (elle peut laisser au plus la
    hauteur d'un anneau, jamais mordre)."""
    R = max(float(forme.get('rayon', 1.0)), pas * 0.5)
    base = H + surepaisseur
    cache = {}
    # le centre de l'outil n'est pas toujours au centre d'une case: une
    # demi-diagonale de plus couvre toute position dans la case (au
    # plus 0,71 case de matière en trop, jamais d'entaille)
    jeu = 0.71 * pas if jeu is None else float(jeu)
    if forme.get('forme', 'plate') in ('plate', 'filet', 'tslot'):
        return dilater_disque(base, (R + jeu) / pas, cache)
    sortie = np.full(H.shape, -np.inf)
    for r, bas in _anneaux_outil(forme, R):
        z = dilater_disque(base, (r + jeu) / pas, cache) - bas
        np.maximum(sortie, z, out=sortie)
    return sortie


def cartes_balayage(H, forme: Dict, pas: float, surepaisseur: float = 0.0,
                    le_long_de_y: bool = False):
    """Les cotes mini de la pointe de l'outil d'un BALAYAGE: (Zc, Zb) —
    Zc l'outil centré sur chaque case, Zb centré sur le bord entre deux
    cases voisines le long de la passe (voir `dilater_balayage`). Comme
    `centre_outil`: exactes pour une fraise plate, prudentes pour une
    boule ou un cône."""
    R = max(float(forme.get('rayon', 1.0)), pas * 0.5)
    base = H + surepaisseur
    if forme.get('forme', 'plate') in ('plate', 'filet', 'tslot'):
        return dilater_balayage(base, R / pas, le_long_de_y)
    zc = zb = None
    for r, bas in _anneaux_outil(forme, R):
        c, b = dilater_balayage(base, r / pas, le_long_de_y)
        zc = c - bas if zc is None else np.maximum(zc, c - bas, out=zc)
        zb = b - bas if zb is None else np.maximum(zb, b - bas, out=zb)
    return zc, zb


def forme_de(bibliotheque, tool_id) -> Dict:
    """La forme d'un outil de la bibliothèque (sim_cycles.forme_outil)."""
    from src.core import sim_cycles
    t = (getattr(bibliotheque, 'tools', None) or {}).get(tool_id)
    if t is None:
        return {'forme': 'plate', 'rayon': 1.0}
    return sim_cycles.forme_outil(t, sim_cycles._catalogue())


# ───────────────────────── les parcours ─────────────────────────

def _niveaux_plats(H, fond: float, cases_min: int) -> List[float]:
    """Les cotes des fonds plats de la pièce (assez de cases à la même
    cote), du haut vers le bas."""
    v = np.round(H[H > fond + 1e-6], 3)
    if not len(v):
        return []
    valeurs, comptes = np.unique(v, return_counts=True)
    return sorted((float(z) for z, n in zip(valeurs, comptes)
                   if n >= cases_min), reverse=True)


def _morceaux(lignes, masque, grille: Grille, z):
    """Les polylignes (contourpy) coupées à ce qui est dans `masque`,
    posées à la cote z (ou suivant z, une carte)."""
    sortie = []
    for pts in lignes:
        pts = np.asarray(pts, dtype=float)
        if len(pts) < 2:
            continue
        j, i = grille.indices(pts[:, 0], pts[:, 1])
        ok = masque[j, i]
        debut = None
        for k in range(len(pts) + 1):
            if k < len(pts) and ok[k]:
                if debut is None:
                    debut = k
                continue
            if debut is not None and k - debut >= 2:
                sortie.append(pts[debut:k])
            debut = None
    return sortie


def _simplifier(pts, tolerance=TOLERANCE):
    """Douglas-Peucker (shapely) d'une polyligne 2D ou 3D."""
    try:
        from shapely.geometry import LineString
        if len(pts) < 3:
            return pts
        ls = LineString(pts).simplify(tolerance)
        return np.asarray(ls.coords)
    except Exception:
        return pts


def _anneaux(champ, masque, grille: Grille, niveaux):
    """Les courbes de niveau de `champ` aux `niveaux`, coupées au
    masque: [polyligne (N, 2)] par niveau."""
    import contourpy
    gen = contourpy.contour_generator(grille.xc, grille.yc, champ,
                                      line_type="Separate")
    sortie = []
    for niveau in niveaux:
        lignes = gen.lines(float(niveau))
        sortie.append(_morceaux(lignes, masque, grille, None))
    return sortie


def passes_niveaux(H, S, Zc, grille: Grille, etape: Dict, fond: float,
                   progression=None) -> List[Dict]:
    """Les passes d'une étape « par niveaux ».

    H: la pièce; S: la matière qui reste (même grille); Zc: la cote
    mini du centre de l'outil (surépaisseur comprise). Rend
    [{'z', 'points': (N, 2)}] dans l'ordre d'usinage."""
    from scipy.ndimage import distance_transform_edt
    from src.core import vcarve
    pas = grille.pas
    R = float(etape['forme']['rayon'])
    s = float(etape.get('surepaisseur', 0.0))
    passe_z = max(0.05, float(etape.get('passe_z', 1.0)))
    lateral = max(pas, float(etape.get('pas_lateral', R)))
    haut = float(S.max())
    # les niveaux: par passe_z depuis le haut, plus les fonds plats
    niveaux = []
    z = haut - passe_z
    while z > fond + 1e-6:
        niveaux.append(z)
        z -= passe_z
    niveaux.append(fond + (s if s > 0 else 0.0))
    for zp in _niveaux_plats(H, fond, max(20, int(0.002 * H.size))):
        niveaux.append(zp + s)
    niveaux = sorted({round(z, 4) for z in niveaux if z < haut - 1e-6},
                     reverse=True)
    passes = []
    rayon_cases = R / pas
    for n, z in enumerate(niveaux):
        vcarve.avancer(progression, n / max(1, len(niveaux)),
                       f"niveau Z {z:.2f}")
        accessible = Zc <= z + 1e-6
        if not accessible.any():
            continue
        enlever = S > np.maximum(z, H + s) + EPS_MATIERE
        if not enlever.any():
            continue
        utile = accessible & (dilater_disque(
            enlever.astype(float), rayon_cases) > 0.5)
        if not utile.any():
            continue
        # la distance aux parois (là où le centre ne peut pas aller)
        dist = distance_transform_edt(accessible) * pas
        dmax = float(dist[utile].max())
        # la première passe longe la paroi au plus près du centre de la
        # première case accessible (là où la carte a été vérifiée)
        cotes = [0.95 * pas]
        while cotes[-1] + lateral < dmax:
            cotes.append(cotes[-1] + lateral)
        if dmax > cotes[-1] + 0.5 * pas:
            cotes.append(dmax - 0.5 * pas)
        anneaux = _anneaux(dist, utile, grille, cotes)
        # du milieu vers les parois: la dernière passe longe la paroi
        for lignes in reversed(anneaux):
            for pts in lignes:
                pts = _simplifier(pts, float(etape.get('tolerance',
                                                       TOLERANCE)))
                if len(pts) >= 2:
                    passes.append({'z': float(z), 'points': pts})
    return passes


def passes_balayage(H, Zc, grille: Grille, etape: Dict, fond: float,
                    progression=None, Zb=None) -> List[Dict]:
    """Les passes d'un balayage: lignes parallèles (le long de X, ou de
    Y si 'angle' = 90), la pointe de l'outil suivant Zc, sur la pièce
    et un rayon autour. Rend [{'points': (N, 3)}] en aller-retour.

    Avec `Zb` (la cote de l'outil centré sur le bord entre deux cases,
    `cartes_balayage`), la ligne a un sommet par DEMI-case, à la plus
    haute des cotes de la demi-case et de ses deux voisines: entre deux
    sommets l'outil est au-dessus de tout ce qu'il peut toucher. (Sans
    elle, il gravissait une paroi en pente sur la largeur d'une case, son
    flanc déjà dedans: jusqu'à un tiers de case d'entaille en biseau.)"""
    from src.core import vcarve
    pas = grille.pas
    R = float(etape['forme']['rayon'])
    lateral = max(pas, float(etape.get('pas_lateral', R * 0.2)))
    le_long_de_y = abs(float(etape.get('angle', 0.0)) % 180 - 90) < 45
    zone = dilater_disque((H > fond + 1e-6).astype(float), R / pas) > 0.5
    Z = np.maximum(Zc, fond)
    Zbord = None if Zb is None else np.maximum(Zb, fond)
    if le_long_de_y:
        Z, zone = Z.T, zone.T
        if Zbord is not None:
            Zbord = Zbord.T
        axe, travers = grille.yc, grille.xc
    else:
        axe, travers = grille.xc, grille.yc
    passes = []
    t = float(travers[0])
    n_lignes = max(1, int((travers[-1] - travers[0]) / lateral) + 1)
    sens = 1
    for k in range(n_lignes):
        vcarve.avancer(progression, k / n_lignes, "balayage")
        t = float(travers[0]) + k * lateral
        jj = int(np.clip(round((t - travers[0]) / pas), 0, len(travers) - 1))
        # la ligne passe AU CENTRE de sa rangée: la carte de l'outil n'a
        # de jeu que le long de la passe
        t = float(travers[jj])
        ligne_z = Z[jj]
        ok = zone[jj]
        if not ok.any():
            continue
        # les morceaux de la ligne sur la zone
        idx = np.nonzero(ok)[0]
        coupures = np.nonzero(np.diff(idx) > 1)[0]
        bouts = np.split(idx, coupures + 1)
        if sens < 0:
            bouts = [b[::-1] for b in reversed(bouts)]
        for b in bouts:
            if len(b) < 2:
                continue
            # les sommets aux BORDS des cases, à la plus haute des deux
            # cotes voisines: dans chaque case, le segment reste au-
            # dessus de sa cote (au pied d'une paroi, une pente d'un
            # centre à l'autre passait dessous)
            # (les deux bouts au CENTRE de leur case: au bord, l'outil
            # mordait la case voisine, hors de la ligne)
            zb = ligne_z[b]
            if Zbord is None:
                u = np.concatenate([[axe[b[0]]],
                                    (axe[b[:-1]] + axe[b[1:]]) / 2,
                                    [axe[b[-1]]]])
                z = np.concatenate([[zb[0]], np.maximum(zb[:-1], zb[1:]),
                                    [zb[-1]]])
            else:
                # à la demi-case: le centre de chaque case, le bord entre
                # deux cases — chacun à la plus haute de sa cote et de
                # celles de ses deux voisins
                cases = b if b[0] <= b[-1] else b[::-1]
                besoin = np.empty(2 * len(cases) - 1)
                besoin[0::2] = ligne_z[cases]
                besoin[1::2] = Zbord[jj][cases[:-1]]
                z = besoin.copy()
                np.maximum(z[1:], besoin[:-1], out=z[1:])
                np.maximum(z[:-1], besoin[1:], out=z[:-1])
                u = np.empty(len(besoin))
                u[0::2] = axe[cases]
                u[1::2] = (axe[cases[:-1]] + axe[cases[1:]]) / 2
                if b[0] > b[-1]:
                    u, z = u[::-1], z[::-1]
            # simplifiée dans le plan (avance, Z): shapely ne regarde que
            # le plan XY, où la ligne est droite — il effaçait tout le
            # relief entre ses deux bouts
            uz = _simplifier(np.column_stack([u, z]), 0.002)
            u, z = uz[:, 0], uz[:, 1]
            if le_long_de_y:
                pts = np.column_stack([np.full(len(u), t), u, z])
            else:
                pts = np.column_stack([u, np.full(len(u), t), z])
            passes.append({'points': pts})
        sens = -sens
    return passes


def zones_raides(H, grille: Grille, fond: float,
                 pente_min: float = PENTE_RAIDE) -> np.ndarray:
    """Les cases de la pièce dont la pente dépasse `pente_min` (une
    paroi droite est une marche: raide)."""
    gy, gx = np.gradient(np.asarray(H, dtype=float), grille.pas)
    pente = np.hypot(gx, gy)
    piece = H > fond + 1e-6
    # une paroi droite: le saut d'une case à la voisine
    return (pente >= math.tan(math.radians(pente_min))) & (
        piece | (dilater_disque(piece.astype(float), 1.5) > 0.5))


def passes_zconstant(H, S, Zc, grille: Grille, etape: Dict, fond: float,
                     progression=None) -> List[Dict]:
    """La finition à Z CONSTANT des parois raides: tranche par tranche
    (`passe_z`), le centre de l'outil longe la paroi au plus près — la
    première passe d'un niveau, celle qui touche la paroi — là où la
    paroi est raide et où il reste de la matière. Rend [{'z', 'points'}]
    du haut vers le bas."""
    from scipy.ndimage import distance_transform_edt
    from src.core import vcarve
    pas = grille.pas
    R = float(etape['forme']['rayon'])
    s = float(etape.get('surepaisseur', 0.0))
    passe_z = max(0.02, float(etape.get('passe_z', 0.25)))
    raides = zones_raides(H, grille, fond,
                          float(etape.get('pente_min', PENTE_RAIDE)))
    if not raides.any():
        return []
    # le centre de l'outil est à un rayon de la paroi
    pres = dilater_disque(raides.astype(float), (R + 2 * pas) / pas) > 0.5
    haut = float(min(S.max(), H.max()))
    niveaux = []
    z = haut - passe_z
    while z > fond + s + 1e-6:
        niveaux.append(round(z, 4))
        z -= passe_z
    niveaux.append(round(fond + s, 4))
    reste = S > H + s + EPS_MATIERE
    proche_reste = dilater_disque(reste.astype(float), R / pas + 1) > 0.5
    passes = []
    for n, z in enumerate(niveaux):
        vcarve.avancer(progression, n / max(1, len(niveaux)),
                       f"paroi Z {z:.2f}")
        accessible = Zc <= z + 1e-6
        if not accessible.any() or accessible.all():
            continue
        utile = accessible & pres & proche_reste
        if not utile.any():
            continue
        dist = distance_transform_edt(accessible) * pas
        for pts in _anneaux(dist, utile, grille, [0.95 * pas])[0]:
            pts = _simplifier(pts, float(etape.get('tolerance', TOLERANCE)))
            if len(pts) >= 2:
                passes.append({'z': float(z), 'points': pts})
    return passes


# ───────────────────────── le code ─────────────────────────

class _Ecrivain:
    """Les lignes d'une séquence Datron, en coordonnées modales."""

    def __init__(self, nom: str):
        self.lignes = [f"$$$ {nom}", "Spindle On"]
        self.x = self.y = self.z = None
        self.feed = None
        self.longueur = 0.0

    def _f(self, nom):
        if self.feed != nom:
            self.lignes.append(f"Feed {nom}")
            self.feed = nom

    def _ecrire(self, mot, x=None, y=None, z=None):
        parts = []
        for nom, v, cour in (('X', x, self.x), ('Y', y, self.y),
                             ('Z', z, self.z)):
            if v is not None and (cour is None or abs(v - cour) > 5e-5):
                parts.append(f"{nom}={round(float(v), 4):g}")
        if not parts:
            return
        if mot == "Line" and None not in (self.x, self.y, self.z):
            nx = self.x if x is None else x
            ny = self.y if y is None else y
            nz = self.z if z is None else z
            self.longueur += math.dist((self.x, self.y, self.z),
                                       (nx, ny, nz))
        self.lignes.append(f"{mot} " + " ".join(parts))
        if x is not None:
            self.x = float(x)
        if y is not None:
            self.y = float(y)
        if z is not None:
            self.z = float(z)

    def placer(self, x, y):
        """Premier placement, au-dessus de tout."""
        self.lignes.append(f"PrePositioning X={round(x, 4):g} "
                           f"Y={round(y, 4):g} Z={SECURITE:g}")
        self.x, self.y, self.z = float(x), float(y), SECURITE
        self.rapide(z=APPROCHE)

    def rapide(self, x=None, y=None, z=None):
        self.feed = None
        self._ecrire("Rapid", x, y, z)

    def ligne(self, x=None, y=None, z=None, feed="Roughing"):
        if z is not None and self.z is not None and z < self.z - 1e-6 \
                and x is None and y is None:
            self._f("Plunge")
        else:
            self._f(feed)
        self._ecrire("Line", x, y, z)

    def degager(self):
        if self.z is not None and self.z < APPROCHE:
            self.rapide(z=APPROCHE)

    def texte(self) -> str:
        return "\n".join(self.lignes)


def _ramper(ecr: _Ecrivain, pts, z_depart: float, z: float, feed: str):
    """Entrer à la cote z en rampe le long du début de la passe (si elle
    est assez longue), sinon en plongée."""
    descente = z_depart - z
    if descente <= 1e-6:
        ecr.ligne(z=z, feed=feed)
        return
    longueur_rampe = descente / math.tan(math.radians(ANGLE_RAMPE))
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    total = float(seg.sum())
    if total < longueur_rampe * 1.05:
        ecr.ligne(z=z, feed=feed)
        return
    ecr._f("Ramp")
    parcouru = 0.0
    fin = 0
    for k in range(1, len(pts)):
        parcouru += seg[k - 1]
        zz = z_depart - descente * min(1.0, parcouru / longueur_rampe)
        ecr._ecrire("Line", pts[k][0], pts[k][1], zz)
        fin = k
        if parcouru >= longueur_rampe:
            break
    # puis on revient au début, à la cote, en REPASSANT par la rampe
    # (une ligne droite coupait à travers ce que la passe contourne),
    # pour couper ce que la rampe n'a fait qu'effleurer
    ecr._f(feed)
    for k in range(fin, -1, -1):
        ecr._ecrire("Line", pts[k][0], pts[k][1], z)


def _segment_accessible(Zc, grille: Grille, a, b, z) -> bool:
    """Le centre de l'outil peut-il aller de a à b à la cote z sans
    entailler la pièce?"""
    n = max(2, int(math.hypot(b[0] - a[0], b[1] - a[1]) / grille.pas) + 2)
    xs = np.linspace(a[0], b[0], n)
    ys = np.linspace(a[1], b[1], n)
    j, i = grille.indices(xs, ys)
    return bool((Zc[j, i] <= z + 1e-6).all())


def code_niveaux(passes, nom: str, S_depart, grille: Grille,
                 feed="Roughing", Zc=None, lien_max: float = 0.0
                 ) -> Tuple[str, float]:
    """La séquence d'une étape par niveaux: (texte, longueur coupée).
    Entre deux passes d'un même niveau à moins de `lien_max`, l'outil
    reste à la cote si le trajet est accessible (Zc); un anneau fermé
    commence au plus près de l'outil."""
    ecr = _Ecrivain(nom)
    for p in passes:
        pts = p['points']
        z = p['z']
        ferme = len(pts) > 3 and math.hypot(
            pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 1e-6
        if ferme and ecr.x is not None and abs((ecr.z or 0) - z) < 1e-6:
            k = int(np.argmin(np.hypot(pts[:-1, 0] - ecr.x,
                                       pts[:-1, 1] - ecr.y)))
            pts = np.vstack([pts[k:-1], pts[:k + 1]])
        x0, y0 = float(pts[0][0]), float(pts[0][1])
        if ecr.x is None:
            ecr.placer(x0, y0)
        # la liaison directe si on est déjà à cette cote, tout près
        pres = (ecr.z is not None and abs(ecr.z - z) < 1e-6
                and Zc is not None
                and math.hypot(x0 - ecr.x, y0 - ecr.y) <= lien_max
                and _segment_accessible(Zc, grille, (ecr.x, ecr.y),
                                        (x0, y0), z))
        if not pres:
            ecr.degager()
            ecr.rapide(x=x0, y=y0)
            j, i = grille.indices(x0, y0)
            z_depart = min(APPROCHE, float(S_depart[j, i]) + 0.2)
            ecr.ligne(z=max(z_depart, z), feed=feed)
            _ramper(ecr, pts, max(z_depart, z), z, feed)
        else:
            ecr.ligne(x0, y0, z, feed=feed)
        for x, y in pts[1:]:
            ecr.ligne(float(x), float(y), feed=feed)
    ecr.degager()
    return ecr.texte(), ecr.longueur


def code_balayage(passes, nom: str, Zc, grille: Grille,
                  feed="Finishing") -> Tuple[str, float]:
    """La séquence d'un balayage: (texte, longueur coupée)."""
    ecr = _Ecrivain(nom)
    for p in passes:
        pts = p['points']
        x0, y0, z0 = (float(v) for v in pts[0])
        if ecr.x is None:
            ecr.placer(x0, y0)
            ecr.ligne(z=z0, feed=feed)
        else:
            # liaison: au-dessus de tout ce qui est entre les deux
            n = max(2, int(math.hypot(x0 - ecr.x, y0 - ecr.y)
                           / grille.pas) + 1)
            xs = np.linspace(ecr.x, x0, n)
            ys = np.linspace(ecr.y, y0, n)
            j, i = grille.indices(xs, ys)
            zl = max(float(Zc[j, i].max()), ecr.z, z0)
            if math.hypot(x0 - ecr.x, y0 - ecr.y) > 20 * grille.pas \
                    and zl < APPROCHE:
                ecr.degager()
                ecr.rapide(x=x0, y=y0)
            else:
                ecr.ligne(z=zl + 0.05 if zl > ecr.z + 1e-6 else None,
                          feed=feed)
                ecr.ligne(x0, y0, feed=feed)
            ecr.ligne(z=z0, feed=feed)
        for x, y, z in pts[1:]:
            ecr.ligne(float(x), float(y), float(z), feed=feed)
    ecr.degager()
    return ecr.texte(), ecr.longueur


def _trajet(texte: str):
    """Les sommets d'une séquence (sim3d) pour la simulation."""
    from src.core import sim3d
    # tous les sommets: la matière doit être exacte
    return sim3d.parcours_3d(texte, max_sommets=10 ** 8)


# ───────────────────────── la gamme ─────────────────────────

def etape(nom, tool_id, forme, role, strategie, surepaisseur=0.0,
          passe_z=1.0, pas_lateral=1.0, angle=0.0, nom_outil="") -> Dict:
    return {'nom': nom, 'outil': tool_id, 'nom_outil': nom_outil,
            'forme': dict(forme), 'role': role, 'strategie': strategie,
            'surepaisseur': float(surepaisseur), 'passe_z': float(passe_z),
            'pas_lateral': float(pas_lateral), 'angle': float(angle)}


def _cylindriques(bibliotheque):
    from src.core import usinage_faces
    for tid, t, d in usinage_faces._fraises(bibliotheque):
        yield tid, t, d, usinage_faces._longueur_utile(t)


def _boules(bibliotheque):
    from src.core import sim_cycles
    cat = sim_cycles._catalogue()
    for tid, t in (getattr(bibliotheque, 'tools', None) or {}).items():
        f = sim_cycles.forme_outil(t, cat)
        if f['forme'] == 'boule':
            yield tid, t, 2 * f['rayon']


def _coupe(t, d):
    """(passe Z, pas latéral) d'ébauche d'un outil: celles du guide de
    coupe DATRON quand l'outil les porte, sinon ap = d/2, ae = 0,4 d."""
    extra = getattr(t, 'extra', None) or {}
    coupe = ((extra.get('constructeur') or {}).get('coupe') or {}) \
        if isinstance(extra, dict) else {}
    rain = coupe.get('rainurage') or {}
    try:
        ap = float(rain.get('ap') or 0)
    except (TypeError, ValueError):
        ap = 0.0
    ap = ap if ap > 0 else min(2.0, 0.5 * d)
    return round(ap, 3), round(0.4 * d, 3)


def analyser(modele, placement) -> Dict:
    """Ce que la pièce demande: profondeur, rayon de coin le plus
    petit, largeur des poches, surfaces gauches."""
    dx, dy, haut, bas = placement
    profondeur = float(haut - bas)
    r_coin = math.inf
    gauches = 0
    for f in getattr(modele, 'faces', None) or []:
        g = f.get('genre')
        if g == 'cylindre':
            axe = np.asarray(f.get('axe', (0, 0, 1)))
            if abs(axe[2]) > 0.995 and f.get('creux'):
                r_coin = min(r_coin, float(f['rayon']))
            elif abs(axe[2]) <= 0.995:
                gauches += 1
        elif g == 'plan':
            nz = abs(float(np.asarray(f.get('normale', (0, 0, 1)))[2]))
            if 0.02 < nz < 0.995:
                gauches += 1
        elif g in ('cone', 'sphere', 'tore', 'autre'):
            gauches += 1
    return {'profondeur': profondeur, 'rayon_coin': r_coin,
            'surfaces_gauches': gauches}


def proposer_gamme(modele, placement, bibliotheque,
                   largeur_poche: Optional[float] = None
                   ) -> Tuple[List[Dict], List[str]]:
    """La gamme que la pièce demande, avec les outils de la
    bibliothèque: ([étape], [pourquoi])."""
    a = analyser(modele, placement)
    prof = a['profondeur']
    pourquoi = []
    cyl = sorted(_cylindriques(bibliotheque), key=lambda c: -c[2])
    if not cyl:
        return [], ["Aucune fraise cylindrique dans la bibliothèque."]
    # l'ébauche: la plus grosse qui passe dans les poches, assez longue
    plafond = 10.0
    if largeur_poche:
        plafond = min(plafond, 0.7 * largeur_poche)
    longues = [c for c in cyl if c[3] == 0 or c[3] >= prof + 0.5]
    choix = [c for c in longues if c[2] <= plafond] or longues[-1:] \
        or cyl[-1:]
    tid, t, d, lu = choix[0]
    ap, ae = _coupe(t, d)
    gamme = [etape("Ébauche", tid, forme_de(bibliotheque, tid), 'ebauche',
                   'niveaux', 0.3, ap, ae, nom_outil=t.name)]
    pourquoi.append(
        f"Ébauche: {t.name} — la plus grosse fraise qui entre dans les "
        f"poches" + (f" (≤ {plafond:.1f} mm)" if largeur_poche else "")
        + f" et descend à {prof:.2f} mm (L utile {lu:g}); passes de "
        f"{ap:g} mm, prise {ae:g} mm, surépaisseur 0,3.")
    r_outil = d / 2.0
    finition_outil = (tid, t, d)
    # la reprise: les coins plus serrés que la fraise d'ébauche
    if a['rayon_coin'] < r_outil - 0.05:
        petites = [c for c in cyl if c[2] / 2.0 <= 0.95 * a['rayon_coin']
                   and (c[3] == 0 or c[3] >= prof + 0.5)]
        if not petites:
            petites = [c for c in cyl if c[3] == 0 or c[3] >= prof + 0.5]
            petites = petites[-1:]
        if petites and petites[0][2] < d:
            tid2, t2, d2, lu2 = petites[0]
            ap2, ae2 = _coupe(t2, d2)
            gamme.append(etape("Reprise", tid2, forme_de(bibliotheque, tid2),
                               'reprise', 'niveaux', 0.1, ap2, ae2,
                               nom_outil=t2.name))
            pourquoi.append(
                f"Reprise: {t2.name} — le plus petit rayon de coin de la "
                f"pièce est R{a['rayon_coin']:g}, la {t.name} y laisse de "
                f"la matière.")
            finition_outil = (tid2, t2, d2)
            if d2 / 2.0 > a['rayon_coin'] + 0.01:
                pourquoi.append(
                    f"Attention: aucune fraise assez fine pour R"
                    f"{a['rayon_coin']:g}; les coins resteront à "
                    f"R{d2 / 2:g}.")
    # la finition
    if a['surfaces_gauches']:
        boules = sorted(_boules(bibliotheque), key=lambda b: -b[2])
        if boules:
            tidb, tb, db = boules[0]
            gamme.append(etape("Finition", tidb, forme_de(bibliotheque, tidb),
                               'finition', 'balayage', 0.0, 0.0,
                               round(0.08 * db, 3), nom_outil=tb.name))
            pourquoi.append(
                f"Finition: balayage à la {tb.name} — la pièce a "
                f"{a['surfaces_gauches']} surface(s) gauche(s); prise "
                f"{0.08 * db:.2f} mm.")
            tidp, tp, dp = tidb, tb, db
        else:
            tidf, tf, df = finition_outil
            gamme.append(etape("Finition", tidf, forme_de(bibliotheque, tidf),
                               'finition', 'balayage', 0.0, 0.0,
                               round(0.1 * df, 3), nom_outil=tf.name))
            pourquoi.append(
                f"Finition: balayage à la {tf.name} (pas de fraise boule "
                f"dans la bibliothèque: les pentes douces garderont des "
                f"marches de {0.1 * df:.2f} mm).")
            tidp, tp, dp = tidf, tf, df
        # le balayage monte les parois raides en marches: elles se
        # finissent à Z constant, tranche par tranche
        passe = round(min(0.25, max(0.05, 0.05 * dp)), 3)
        gamme.append(etape("Finition parois", tidp,
                           forme_de(bibliotheque, tidp), 'finition',
                           'zconstant', 0.0, passe, round(0.4 * dp, 3),
                           nom_outil=tp.name))
        pourquoi.append(
            f"Finition parois: à Z constant à la {tp.name}, tranches de "
            f"{passe:g} mm — les parois plus raides que "
            f"{PENTE_RAIDE:g}° (le balayage y laisserait des marches).")
    else:
        tidf, tf, df = finition_outil
        lu = next((c[3] for c in cyl if c[0] == tidf), 0.0)
        passe = prof if (lu == 0 or lu >= prof + 0.5) else max(0.5, lu - 0.5)
        gamme.append(etape("Finition", tidf, forme_de(bibliotheque, tidf),
                           'finition', 'niveaux', 0.0, round(passe, 3),
                           round(0.4 * df, 3), nom_outil=tf.name))
        pourquoi.append(
            f"Finition: par niveaux à la {tf.name} — parois droites et "
            f"fonds plats: les fonds à leur cote exacte, les parois en "
            f"{'une passe' if passe >= prof else f'passes de {passe:g} mm'}.")
    return gamme, pourquoi


# ───────────────────────── le calcul ─────────────────────────

def preparer(modele, placement, marge: float = 2.0, pas=None) -> Dict:
    """La pièce placée en machine et sa carte: {'grille', 'H', 'fond',
    'triangles'}."""
    dx, dy, haut, bas = placement
    T = np.asarray(modele.triangles, dtype=float) + np.array(
        [dx, dy, -haut])
    fond = float(bas - haut)
    mn = T.reshape(-1, 3).min(axis=0)
    mx = T.reshape(-1, 3).max(axis=0)
    grille = Grille(mn[0] - marge, mx[0] + marge, mn[1] - marge,
                    mx[1] + marge, pas=pas)
    H = carte_piece(T, grille, fond)
    return {'grille': grille, 'H': H, 'fond': fond, 'triangles': T}


def _avec_tolerance(gamme, tolerance):
    """Les étapes avec la tolérance des parcours choisie (None: la
    leur, ou TOLERANCE)."""
    if tolerance is None:
        return list(gamme)
    return [dict(e, tolerance=float(tolerance)) for e in gamme]


def pas_auto(modele, marge: float = 2.0) -> float:
    """Le pas que la carte prendrait d'elle-même pour cette pièce."""
    b = modele.bornes()
    lx = b[3] - b[0] + 2 * marge
    ly = b[4] - b[1] + 2 * marge
    return max(PAS_MIN, math.sqrt(max(lx * ly, 1e-6) / CASES_MAX))


def estimer_precision(modele, pas=None, marge: float = 2.0) -> Dict:
    """Ce que coûte un pas: {'pas' (celui qui sera pris), 'cases',
    'facteur' (temps relatif au pas auto, ~ cases), 'grossi' (le pas
    demandé dépassait le plafond)}."""
    b = modele.bornes()
    lx = b[3] - b[0] + 2 * marge
    ly = b[4] - b[1] + 2 * marge
    auto = pas_auto(modele, marge)
    grossi = False
    if pas is None:
        pris = auto
    else:
        pris = float(pas)
        if lx * ly / pris ** 2 > CASES_PLAFOND:
            pris, grossi = math.sqrt(lx * ly / CASES_PLAFOND), True
    cases = int(math.ceil(lx / pris) * math.ceil(ly / pris))
    cases_auto = max(1, int(math.ceil(lx / auto) * math.ceil(ly / auto)))
    return {'pas': pris, 'cases': cases, 'facteur': cases / cases_auto,
            'grossi': grossi, 'auto': auto}


def calculer(modele, placement, gamme: Sequence[Dict], marge: float = None,
             pas=None, progression=None, prefixe: str = "USINAGE3D",
             brut: Dict = None, tenue: Dict = None,
             tolerance: float = None) -> Dict:
    """Toute la gamme: pour chaque étape sa séquence, et le contrôle.

    Rend {'etapes': [{'etape', 'nom_sequence', 'code', 'longueur',
    'n_passes'}], 'grille', 'H', 'S' (la matière au bout), 'controle':
    {'entailles', 'entaille_max', 'reste_max', 'reste_moyen'}}.
    Avec un `brut` (src/core/tenue): le zéro Z sur son dessus, sa
    surépaisseur surfacée, les mors de l'étau protégés."""
    if marge is None:
        marge = _marge(gamme)
    gamme = _avec_tolerance(gamme, tolerance)
    if brut is not None or tenue is not None:
        calc = calculer_phases(
            modele, placement, {'Z+': list(gamme)},
            [{'cle': 'Z+', 'libelle': DIRECTIONS['Z+'][2], 'faces': []}],
            pas, progression, brut=brut, tenue=tenue, prefixes=[prefixe])
        if calc['phases']:
            return calc['phases'][0]['resultat']
        return {'etapes': [], 'controle': {}}
    pre = preparer(modele, placement, marge, pas)
    return calculer_carte(pre['H'], pre['grille'], pre['fond'], gamme,
                          None, progression, prefixe)


def _marge(gamme) -> float:
    return max([float(e['forme'].get('rayon', 1.0)) for e in gamme]
               + [1.0]) + 1.0


def calculer_carte(H, grille: Grille, fond: float, gamme: Sequence[Dict],
                   S0=None, progression=None, prefixe: str = "USINAGE3D",
                   obstacles=None, H_piece=None, vide=None) -> Dict:
    """La gamme sur une carte de pièce déjà faite (une phase): `S0` est
    la matière au départ (None: le brut entier, dessus en Z 0).

    `obstacles`: une carte sous laquelle l'outil ne descend jamais (les
    mors, la plaque, le vide sous de la matière restante) — protégée
    comme la pièce, mais hors du contrôle. Une étape peut avoir son
    `plancher` (un surfaçage: tout ce qui est au-dessus, rien dessous).

    `vide`: le DESSOUS de la matière restante par case (−inf sans
    matière) — sous lui, de l'air: rien à y enlever, et chaque outil ne
    descend pas plus bas que la matière la plus basse à sa portée (il
    ne plonge pas dans le vide autour de la pièce retournée, mais finit
    un ressaut au ras d'une case déjà vide)."""
    from src.core import vcarve
    Hm = H if obstacles is None else np.maximum(H, obstacles)
    brut = grille.brut(fond, 0.0)
    if S0 is not None:
        brut.h = np.array(S0, dtype=float)
    depart = brut.h.copy()
    sortie = []
    n = max(1, len(gamme))
    for k, et in enumerate(gamme):
        sous = vcarve.sous_progression(progression, k / n, (k + 1) / n,
                                       f"{et['nom']} — ")
        vcarve.avancer(sous, 0.0, "position de l'outil")
        Hs = Hm
        Hp = Hm
        if vide is not None:
            jeu_v = (0.5 if et['strategie'] == 'balayage' else 0.71) \
                * grille.pas
            portee = (float(et['forme'].get('rayon', 1.0)) + jeu_v) \
                / grille.pas
            Q = np.where(np.isfinite(vide), vide, np.inf)
            bas = -dilater_disque(-Q, portee)
            Hp = np.maximum(Hm, np.where(np.isfinite(bas), bas, -np.inf))
            Hs = np.maximum(Hm, np.where(np.isfinite(vide), vide, -np.inf))
        if et.get('plancher') is not None:
            Hs = np.maximum(Hs, float(et['plancher']))
            Hp = np.maximum(Hp, float(et['plancher']))
        # un balayage passe au CENTRE des rangées en travers, et le
        # long de la passe sa cote se calcule à la demi-case
        Zb = None
        if et['strategie'] == 'balayage':
            Zc, Zb = cartes_balayage(
                Hp, et['forme'], grille.pas,
                float(et.get('surepaisseur', 0.0)),
                abs(float(et.get('angle', 0.0)) % 180 - 90) < 45)
        else:
            Zc = centre_outil(Hp, et['forme'], grille.pas,
                              float(et.get('surepaisseur', 0.0)))
        nom = f"{prefixe}_{k + 1}_{et['role'].upper()}"
        S0 = brut.h.copy()
        if et['strategie'] == 'balayage':
            passes = passes_balayage(H if H_piece is None else H_piece,
                                     Zc, grille, et, fond,
                                     vcarve.sous_progression(sous, 0.05,
                                                             0.7), Zb)
            code, longueur = code_balayage(passes, nom, Zc, grille)
        elif et['strategie'] == 'zconstant':
            passes = passes_zconstant(H if H_piece is None else H_piece,
                                      S0, Zc, grille, et, fond,
                                      vcarve.sous_progression(sous, 0.05,
                                                              0.7))
            code, longueur = code_niveaux(
                passes, nom, S0, grille, "Finishing", Zc,
                1.5 * float(et['forme'].get('rayon', 1.0)))
        else:
            passes = passes_niveaux(Hs, S0, Zc, grille, et, fond,
                                    vcarve.sous_progression(sous, 0.05,
                                                            0.7))
            code, longueur = code_niveaux(
                passes, nom, S0, grille,
                "Finishing" if et['role'] == 'finition' else "Roughing",
                Zc, 1.5 * float(et.get('pas_lateral', 1.0)))
        # la matière après l'étape: elle guide la suivante
        vcarve.avancer(sous, 0.7, "matière enlevée")
        trajet = _trajet(code)
        brut.appliquer(trajet, {'': et['forme']}, None)
        brut.applique = 0
        sortie.append({'etape': et, 'nom_sequence': nom, 'code': code,
                       'longueur': longueur, 'n_passes': len(passes)})
    S = brut.h
    piece = H > fond + 1e-6
    ecart = S - H
    # une entaille: la gamme est descendue SOUS la pièce (là où il y
    # avait de la matière au départ — vue de côté, le bord de la pièce
    # tombe d'une case hors du brut)
    entailles = (S < np.minimum(depart, H) - 0.02) & piece
    controle = {
        'entailles': int(entailles.sum()),
        'entaille_max': float(-ecart[entailles].min()) if entailles.any()
        else 0.0,
        'reste_max': float(ecart[piece].max()) if piece.any() else 0.0,
        'reste_moyen': float(ecart[piece].mean()) if piece.any() else 0.0,
        # la part de la pièce où il reste plus d'un mm (ce que la gamme
        # n'atteint pas: fente plus fine ou plus profonde que ses outils)
        'part_reste_1mm': float((ecart[piece] > 1.0).mean())
        if piece.any() else 0.0,
        'hors_piece_max': float((S - fond)[~piece].max())
        if (~piece).any() else 0.0}
    vcarve.avancer(progression, 1.0, "gamme calculée")
    return {'etapes': sortie, 'grille': grille, 'H': H, 'S': S,
            'controle': controle, 'fond': fond}


def operations(resultat: Dict, nom_piece: str = "pièce") -> List[Dict]:
    """Les opérations « Séquence Datron » de la gamme calculée, au
    format de operations_generated (plus 'tool_id')."""
    ops = []
    for e in resultat.get('etapes', []):
        et = e['etape']
        corps = e['code'].split('\n', 1)[1] if '\n' in e['code'] else ""
        ops.append({'operation_type': 'sequence_datron',
                    'name': f"{et['nom']} 3D — {nom_piece}",
                    'x': 0.0, 'y': 0.0, 'points': [],
                    'params': {'sequence_name': e['nom_sequence'],
                               'sequence_code': corps},
                    'tool_id': et['outil']})
    return ops


def resume(resultat: Dict) -> str:
    c = resultat.get('controle') or {}
    morceaux = []
    for e in resultat.get('etapes', []):
        et = e['etape']
        morceaux.append(f"{et['nom']} ({et.get('nom_outil') or et['outil']}"
                        f"): {e['longueur'] / 1000:.2f} m")
    txt = " · ".join(morceaux)
    g = resultat.get('grille')
    if g is not None and morceaux:
        txt += f" — carte au pas de {g.pas:.3g} mm"
        if getattr(g, 'pas_demande', None):
            txt += (f" (demandé {g.pas_demande:g} mm: trop de cases pour "
                    "cette pièce)")
    if c:
        txt += (f" — contrôle: {'aucune entaille' if not c['entailles'] else str(c['entailles']) + ' case(s) entaillée(s) (max ' + format(c['entaille_max'], '.3f') + ' mm)'}"
                f", reste max {c['reste_max']:.2f} mm")
        part = c.get('part_reste_1mm', 0.0)
        if part >= 0.005:
            txt += (f" ({part * 100:.0f} % de la surface à plus d'1 mm: "
                    "une fraise plus fine ou plus longue y entrerait)")
    return txt


# ───────────────────────── les phases de bridage ─────────────────────────
#
# Une fraiseuse 3 axes usine par le dessus. Ce que le dessus ne voit
# pas (une face tournée vers le bas, un trou percé de côté, une poche
# sous un surplomb) demande de RETOURNER la pièce — autour de X —, ou
# de la COUCHER sur un côté. Chaque orientation est une phase: sa
# carte de la pièce, la matière qui lui reste des phases d'avant, sa
# gamme, sa prise (étau, table à vide) et son zéro.

#: les orientations: la direction d'où vient l'outil (dans le repère de
#: la pièce), la rotation qui l'amène en +Z, et ce qu'on dit à
#: l'opérateur
DIRECTIONS = {
    'Z+': (np.array([0.0, 0.0, 1.0]), np.eye(3), "dessus"),
    'Z-': (np.array([0.0, 0.0, -1.0]), np.diag([1.0, -1.0, -1.0]),
           "dessous (retournee autour de X)"),
    'X+': (np.array([1.0, 0.0, 0.0]),
           np.array([[0.0, 0.0, -1.0], [0.0, 1.0, 0.0], [1.0, 0.0, 0.0]]),
           "cote X+ vers le haut"),
    'X-': (np.array([-1.0, 0.0, 0.0]),
           np.array([[0.0, 0.0, 1.0], [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0]]),
           "cote X- vers le haut"),
    'Y+': (np.array([0.0, 1.0, 0.0]),
           np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]]),
           "cote Y+ vers le haut"),
    'Y-': (np.array([0.0, -1.0, 0.0]),
           np.array([[1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, -1.0, 0.0]]),
           "cote Y- vers le haut"),
}
ORDRE_DIRECTIONS = ('Z+', 'Z-', 'Y-', 'Y+', 'X-', 'X+')


def rayons_libres(triangles, points, direction) -> np.ndarray:
    """Pour chaque point: le rayon qui part vers `direction` sort-il de
    la pièce sans la toucher? (Möller–Trumbore; un contact tout près du
    départ — la face elle-même — ne compte pas)."""
    T = np.asarray(triangles, dtype=float)
    P = np.atleast_2d(np.asarray(points, dtype=float))
    d = np.asarray(direction, dtype=float)
    d = d / np.linalg.norm(d)
    if not len(T) or not len(P):
        return np.ones(len(P), dtype=bool)
    diag = float(np.linalg.norm(np.ptp(T.reshape(-1, 3), axis=0))) or 1.0
    eps = diag * 1e-4
    v0 = T[:, 0]
    e1, e2 = T[:, 1] - v0, T[:, 2] - v0
    h = np.cross(d, e2)
    a = (e1 * h).sum(axis=1)
    ok = np.abs(a) > 1e-12
    f = np.where(ok, 1.0 / np.where(ok, a, 1.0), 0.0)
    libres = np.ones(len(P), dtype=bool)
    for i, p in enumerate(P):
        s_ = p - v0
        u = f * (s_ * h).sum(axis=1)
        q = np.cross(s_, e1)
        v = f * (q @ d)
        t = f * (e2 * q).sum(axis=1)
        touche = ok & (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9) \
            & (t > 3 * eps)
        libres[i] = not touche.any()
    return libres


def _echantillons(modele, info, n: int = 3, ecart: float = 0.0):
    """Quelques points d'une face (centres de ses plus grands
    triangles), écartés de `ecart` HORS de la matière (le côté se mesure
    au lancer de rayon: le sens des triangles n'est pas fiable). Un
    point posé sur la face même frôle ses voisines (un chanfrein au
    haut d'une paroi) et se croit caché."""
    T = np.asarray(modele.triangles, dtype=float)
    idx = np.nonzero(np.asarray(modele.face_de) == info['index'])[0]
    if not len(idx):
        return np.zeros((0, 3))
    aires = 0.5 * np.linalg.norm(np.cross(T[idx, 1] - T[idx, 0],
                                          T[idx, 2] - T[idx, 0]), axis=1)
    choisis = idx[np.argsort(-aires)][:n]
    centres = T[choisis].mean(axis=1)
    if ecart <= 0:
        return centres
    from src.io.vecteur.step3d import dans_la_matiere
    nt = np.cross(T[choisis, 1] - T[choisis, 0],
                  T[choisis, 2] - T[choisis, 0])
    nt = nt / np.maximum(np.linalg.norm(nt, axis=1), 1e-12)[:, None]
    dedans = dans_la_matiere(T, centres + ecart * nt)
    nt[dedans] *= -1.0
    return centres + ecart * nt


def _normale_face(modele, info) -> np.ndarray:
    if info.get('genre') == 'plan' and info.get('normale') is not None:
        return np.asarray(info['normale'], dtype=float)
    return None


def accessibilite(modele, placement=None) -> Dict:
    """Pour chaque face (par son index): les directions d'où l'outil
    l'atteint (la face ne se détourne pas de lui, et rien ne la cache).
    Rend {index: [clés de DIRECTIONS]} et 'brute': les faces de dessous
    posées sur la table (le brut, pas à usiner)."""
    faces = getattr(modele, 'faces', None) or []
    T = np.asarray(modele.triangles, dtype=float)
    if not len(T) or not faces:
        return {'faces': {}, 'brute': []}
    bas = float(T[:, :, 2].min())
    diag = float(np.linalg.norm(np.ptp(T.reshape(-1, 3), axis=0))) or 1.0
    eps = diag * 2e-4
    sortie, brutes = {}, []
    for info in faces:
        n = _normale_face(modele, info)
        # le dessous posé sur la table: le brut, rien à usiner
        if n is not None and n[2] < -0.99 and info['z_min'] <= bas + 1e-3:
            brutes.append(info['index'])
            continue
        pts = _echantillons(modele, info, ecart=eps)
        if not len(pts):
            continue
        dirs = []
        for cle in ORDRE_DIRECTIONS:
            d, _R, _l = DIRECTIONS[cle]
            if n is not None and float(np.dot(n, d)) < -0.05:
                continue            # la face se détourne de l'outil
            if info.get('genre') == 'cylindre':
                axe = np.asarray(info.get('axe', (0, 0, 1)), dtype=float)
                # un trou ne s'usine que dans l'axe de l'outil (ou le
                # flanc d'un cylindre vertical, par le dessus/dessous)
                if abs(float(np.dot(axe, d))) < 0.99:
                    continue
            libres = rayons_libres(T, pts + d * eps, d)
            if libres.mean() >= 0.75:
                dirs.append(cle)
        sortie[info['index']] = dirs
    return {'faces': sortie, 'brute': brutes}


def planifier_phases(modele, placement=None) -> Dict:
    """Les phases que la pièce demande: le dessus d'abord, puis le
    moins de retournements possible pour le reste (par aire). Rend
    {'phases': [{'cle', 'libelle', 'faces', 'bridage', 'zero'}],
    'non_usinables': [index de faces qu'aucune orientation 3 axes
    n'atteint]}."""
    acc = accessibilite(modele, placement)
    faces = {f['index']: f for f in (getattr(modele, 'faces', None) or [])}
    reste = {i for i, d in acc['faces'].items()}
    aire = {i: float(faces[i].get('aire', 0.0)) for i in reste}
    phases = []
    choisies = []
    # le dessus, toujours
    for cle in ORDRE_DIRECTIONS:
        if cle != 'Z+' and not reste:
            break
        if cle != 'Z+':
            # la meilleure suivante: celle qui couvre le plus d'aire
            meilleure, gain = None, 0.0
            for c in ORDRE_DIRECTIONS:
                if c in choisies:
                    continue
                g = sum(aire[i] for i in reste if c in acc['faces'][i])
                if g > gain + 1e-9:
                    meilleure, gain = c, g
            if meilleure is None:
                break
            cle = meilleure
        couvertes = [i for i in sorted(reste) if cle in acc['faces'][i]]
        if cle != 'Z+' and not couvertes:
            continue
        reste -= set(couvertes)
        choisies.append(cle)
        phases.append({'cle': cle, 'libelle': DIRECTIONS[cle][2],
                       'faces': couvertes})
        if len(choisies) >= len(ORDRE_DIRECTIONS):
            break
    for k, ph in enumerate(phases):
        ph['bridage'] = _bridage(modele, ph['cle'], k)
        ph['zero'] = ("Zero XY et Z comme le programme (dessin)" if k == 0
                      else "Zero XY au centre de la piece, Z sur le "
                           "dessus du brut tel que pose")
    return {'phases': phases, 'non_usinables': sorted(reste)}


def _bridage(modele, cle: str, rang: int) -> str:
    """La prise conseillée pour une phase."""
    faces = getattr(modele, 'faces', None) or []
    T = np.asarray(modele.triangles, dtype=float)
    p = T.reshape(-1, 3)
    mn, mx = p.min(axis=0), p.max(axis=0)
    emprise = max(1e-9, (mx[0] - mn[0]) * (mx[1] - mn[1]))

    def plans(direction, extreme):
        """Aire des faces planes tournées vers `direction` au bord."""
        total = 0.0
        for f in faces:
            n = _normale_face(None, f)
            if n is None or float(np.dot(n, direction)) < 0.99:
                continue
            total += float(f.get('aire', 0.0))
        return total

    if cle == 'Z+':
        if plans(np.array([0, 0, -1.0]), mn[2]) >= 0.4 * emprise:
            return ("Brut pose sur la table a vide (dessous plan), dessus "
                    "en Z+")
        return ("Brut en etau, prise sous la piece (prevoir 3 mm de "
                "serrage sous le fond)")
    if cle == 'Z-':
        if plans(np.array([0, 0, 1.0]), mx[2]) >= 0.4 * emprise:
            return ("Retourner autour de X: poser sur le dessus usine "
                    "(plan) - table a vide ou cales, mors doux")
        return ("Retourner autour de X: etau a mors doux sur les flancs "
                "usines (faces Y-/Y+)")
    axe = cle[0]
    autre = 'Y' if axe == 'X' else 'X'
    return (f"Coucher la piece ({DIRECTIONS[cle][2]}): etau a mors doux "
            f"sur le dessus et le dessous, butee sur la face {autre}-")


def triangles_phase(modele, placement, cle: str):
    """Les triangles de la pièce dans le repère d'une phase: (T, bas).
    Z+: le repère du programme (placement). Les autres: tournés, dessus
    en Z 0, centre de la pièce en X/Y 0."""
    dx, dy, haut, bas = placement
    T = np.asarray(modele.triangles, dtype=float)
    if cle == 'Z+':
        return T + np.array([dx, dy, -haut]), float(bas - haut)
    R = DIRECTIONS[cle][1]
    Tp = T @ R.T
    p = Tp.reshape(-1, 3)
    mn, mx = p.min(axis=0), p.max(axis=0)
    Tp = Tp - np.array([(mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2, mx[2]])
    return Tp, float(mn[2] - mx[2])


class Colonnes:
    """La matière comme des colonnes verticales, dans le repère de la
    PIÈCE (celui du STEP): dans chaque case (xs, ys: centres), de `bas`
    à `haut`. Exact pour le dessus et le dessous; vue de côté, elle se
    lit par lignes. Une phase voit la pièce par P' = R·P − décalage."""

    def __init__(self, xs, ys, pas, bas, haut):
        self.xs = np.asarray(xs, dtype=float)
        self.ys = np.asarray(ys, dtype=float)
        self.pas = float(pas)
        self.bas = np.array(bas, dtype=float)
        self.haut = np.array(haut, dtype=float)

    @classmethod
    def apres_dessus(cls, grille: Grille, S, fond, decalage):
        """Après la phase du dessus (sa grille, sa matière S, son fond,
        son décalage: P' = P − décalage): de `fond` à S."""
        cx, cy, cz = decalage
        S = np.asarray(S, dtype=float)
        haut = np.where(S > fond + EPS_MATIERE, S, fond) + cz
        return cls(grille.xc + cx, grille.yc + cy, grille.pas,
                   np.full(S.shape, float(fond) + cz), haut)

    def _indices(self, x, y):
        i = np.round((np.asarray(x) - self.xs[0]) / self.pas).astype(int)
        j = np.round((np.asarray(y) - self.ys[0]) / self.pas).astype(int)
        dedans = ((i >= 0) & (i < len(self.xs)) & (j >= 0)
                  & (j < len(self.ys)))
        return j, i, dedans

    def plein(self):
        return self.haut > self.bas + EPS_MATIERE

    def stock(self, cle: str, grille_k: Grille, decalage, fond_k: float):
        """La carte de la matière vue depuis la phase `cle` (sur sa
        grille): le dessus de la matière à sa cote, `fond_k` où il n'y
        en a pas."""
        cx, cy, cz = decalage
        plein = self.plein()
        Xk, Yk = np.meshgrid(grille_k.xc, grille_k.yc)
        if cle in ('Z+', 'Z-'):
            R = DIRECTIONS[cle][1]
            # (x', y') → la colonne (x, y) de la pièce: R est son propre
            # inverse pour Z±
            x = R[0, 0] * (Xk + cx)
            y = R[1, 1] * (Yk + cy)
            j, i, dedans = self._indices(x, y)
            val = np.full(Xk.shape, -np.inf)
            ok = dedans.copy()
            ok[dedans] = plein[j[dedans], i[dedans]]
            if cle == 'Z+':
                val[ok] = self.haut[j[ok], i[ok]] - cz
            else:
                # vue de dessous: le BAS de la colonne, retourné
                val[ok] = -self.bas[j[ok], i[ok]] - cz
            return np.maximum(np.where(np.isfinite(val), val, fond_k),
                              fond_k)
        # couchée: pour chaque ligne de la pièce et chaque cote, la
        # matière la plus avancée le long de l'axe de l'outil
        R = DIRECTIONS[cle][1]
        zs = np.arange(float(self.bas[plein].min()) if plein.any() else 0.0,
                       float(self.haut.max()) + self.pas, self.pas)
        axe_x = cle[0] == 'X'
        signe = 1.0 if cle[1] == '+' else -1.0
        coord = self.xs if axe_x else self.ys
        n_autre = len(self.ys) if axe_x else len(self.xs)
        extreme = np.full((n_autre, len(zs)), -np.inf)
        for k in range(n_autre):
            b = self.bas[k, :] if axe_x else self.bas[:, k]
            h = self.haut[k, :] if axe_x else self.haut[:, k]
            m = ((b[None, :] <= zs[:, None] + 1e-6)
                 & (h[None, :] >= zs[:, None] - 1e-6)
                 & (h > b + EPS_MATIERE)[None, :])
            extreme[k] = np.where(m, signe * coord[None, :],
                                  -np.inf).max(axis=1)
        # la case (x', y') de la phase: le point de la pièce où l'axe de
        # l'outil passe (à sa coordonnée nulle): R^T (x'+cx, y'+cy, 0)
        Pp = np.stack([Xk + cx, Yk + cy, np.zeros_like(Xk)], axis=-1)
        Po = Pp @ R
        autre = Po[..., 1] if axe_x else Po[..., 0]
        zo = Po[..., 2]
        base = self.ys[0] if axe_x else self.xs[0]
        ka = np.round((autre - base) / self.pas).astype(int)
        kz = np.round((zo - zs[0]) / self.pas).astype(int)
        dedans = (ka >= 0) & (ka < n_autre) & (kz >= 0) & (kz < len(zs))
        val = np.full(Xk.shape, -np.inf)
        val[dedans] = extreme[ka[dedans], kz[dedans]]
        # z' = (R·P)_z − cz = signe·coord − cz
        Sk = np.where(np.isfinite(val), val - cz, fond_k)
        return np.maximum(Sk, fond_k)

    @classmethod
    def du_brut(cls, grille: Grille, decalage, boite):
        """Le brut entier (une boîte du repère de la pièce: x0, y0, z0,
        x1, y1, z1), en colonnes sur la grille d'une phase du dessus
        (son décalage)."""
        cx, cy, _cz = decalage
        xs, ys = grille.xc + cx, grille.yc + cy
        X, Y = np.meshgrid(xs, ys)
        x0, y0, z0, x1, y1, z1 = (float(v) for v in boite)
        dedans = ((X >= x0 - 1e-9) & (X <= x1 + 1e-9)
                  & (Y >= y0 - 1e-9) & (Y <= y1 + 1e-9))
        return cls(xs, ys, grille.pas, np.full(X.shape, z0),
                   np.where(dedans, z1, z0))

    @staticmethod
    def _cases(grille_k: Grille, xk, yk):
        i = np.floor((np.asarray(xk) - grille_k.x0) / grille_k.pas
                     ).astype(int)
        j = np.floor((np.asarray(yk) - grille_k.y0) / grille_k.pas
                     ).astype(int)
        dedans = (i >= 0) & (i < grille_k.nx) & (j >= 0) & (j < grille_k.ny)
        return j, i, dedans

    def enlever_dessus(self, S, grille_k: Grille, fond_k: float, decalage):
        """Après une phase du dessus: le haut des colonnes descend à ce
        qu'elle a laissé; ce qui est sous son fond (la prise) reste."""
        cx, cy, cz = decalage
        X, Y = np.meshgrid(self.xs, self.ys)
        j, i, dedans = self._cases(grille_k, X - cx, Y - cy)
        s = np.full(X.shape, np.inf)
        s[dedans] = np.maximum(np.asarray(S)[j[dedans], i[dedans]],
                               fond_k) + cz
        self.haut = np.minimum(self.haut, s)

    def stock_et_plancher(self, cle: str, grille_k: Grille, decalage,
                          fond_k: float):
        """(dessus, dessous) de la matière vue depuis la phase `cle`, sur
        sa grille: le dessus à sa cote (`fond_k` où il n'y a rien), le
        DESSOUS de la matière (−inf où il n'y a rien) — sous lui, du
        vide: l'outil n'a pas à y descendre."""
        cx, cy, cz = decalage
        plein = self.plein()
        Xk, Yk = np.meshgrid(grille_k.xc, grille_k.yc)
        if cle in ('Z+', 'Z-'):
            R = DIRECTIONS[cle][1]
            x = R[0, 0] * (Xk + cx)
            y = R[1, 1] * (Yk + cy)
            j, i, dedans = self._indices(x, y)
            ok = dedans.copy()
            ok[dedans] = plein[j[dedans], i[dedans]]
            haut = np.full(Xk.shape, -np.inf)
            bas = np.full(Xk.shape, -np.inf)
            if cle == 'Z+':
                haut[ok] = self.haut[j[ok], i[ok]] - cz
                bas[ok] = self.bas[j[ok], i[ok]] - cz
            else:
                haut[ok] = -self.bas[j[ok], i[ok]] - cz
                bas[ok] = -self.haut[j[ok], i[ok]] - cz
            S0 = np.maximum(np.where(np.isfinite(haut), haut, fond_k),
                            fond_k)
            return S0, bas
        R = DIRECTIONS[cle][1]
        zs = np.arange(float(self.bas[plein].min()) if plein.any() else 0.0,
                       float(self.haut.max()) + self.pas, self.pas)
        axe_x = cle[0] == 'X'
        signe = 1.0 if cle[1] == '+' else -1.0
        coord = self.xs if axe_x else self.ys
        n_autre = len(self.ys) if axe_x else len(self.xs)
        extreme = np.full((n_autre, len(zs)), -np.inf)
        minimum = np.full((n_autre, len(zs)), np.inf)
        for k in range(n_autre):
            b = self.bas[k, :] if axe_x else self.bas[:, k]
            h = self.haut[k, :] if axe_x else self.haut[:, k]
            m = ((b[None, :] <= zs[:, None] + 1e-6)
                 & (h[None, :] >= zs[:, None] - 1e-6)
                 & (h > b + EPS_MATIERE)[None, :])
            v = signe * coord[None, :]
            extreme[k] = np.where(m, v, -np.inf).max(axis=1)
            minimum[k] = np.where(m, v, np.inf).min(axis=1)
        Pp = np.stack([Xk + cx, Yk + cy, np.zeros_like(Xk)], axis=-1)
        Po = Pp @ R
        autre = Po[..., 1] if axe_x else Po[..., 0]
        zo = Po[..., 2]
        base = self.ys[0] if axe_x else self.xs[0]
        ka = np.round((autre - base) / self.pas).astype(int)
        kz = np.round((zo - zs[0]) / self.pas).astype(int)
        dedans = (ka >= 0) & (ka < n_autre) & (kz >= 0) & (kz < len(zs))
        haut = np.full(Xk.shape, -np.inf)
        bas = np.full(Xk.shape, np.inf)
        # une colonne couvre sa case: ±½ pas autour de son centre (le
        # côté prudent — la face palpée n'est jamais plus haut)
        haut[dedans] = extreme[ka[dedans], kz[dedans]] + self.pas / 2
        bas[dedans] = minimum[ka[dedans], kz[dedans]] - self.pas / 2
        S0 = np.maximum(np.where(np.isfinite(haut), haut - cz, fond_k),
                        fond_k)
        return S0, np.where(np.isfinite(bas), bas - cz, -np.inf)

    def apres_dessous(self, S2, grille_k: Grille, decalage):
        """Après la phase retournée: le bas des colonnes remonte jusqu'à
        ce qu'elle a laissé."""
        cx, cy, cz = decalage
        X, Y = np.meshgrid(self.xs, self.ys)
        # (x, y) de la pièce → (x', y') = (x − cx, −y − cy)
        xk, yk = X - cx, -Y - cy
        j = np.round((yk - grille_k.y0) / grille_k.pas - 0.5).astype(int)
        i = np.round((xk - grille_k.x0) / grille_k.pas - 0.5).astype(int)
        dedans = (j >= 0) & (j < grille_k.ny) & (i >= 0) & (i < grille_k.nx)
        z2 = np.full(X.shape, np.inf)
        z2[dedans] = np.asarray(S2)[j[dedans], i[dedans]]
        # z' = −z − cz  →  z = −(z' + cz)
        nouveau_bas = np.where(np.isfinite(z2), -(z2 + cz), self.bas)
        self.bas = np.maximum(self.bas, nouveau_bas)


def preparer_phase(modele, placement, cle: str, marge: float, pas=None,
                   boite=None, extra=None, dz: float = 0.0) -> Dict:
    """La carte d'une phase: {'grille', 'H', 'fond', 'decalage'} —
    `decalage` (cx, cy, cz) ramène les coordonnées tournées à celles de
    la phase (P' = R·P − décalage).

    Avec la `boite` du brut (repère de la pièce): le zéro Z est le
    dessus du brut tel qu'il est posé, la grille couvre le brut, et
    'boite' / 'piece' rendent leurs emprises dans le repère de la phase
    (x0, y0, z0, x1, y1, z1). `extra`: des triangles GARDÉS (le cadre et
    les ponts d'un squelette), protégés comme la pièce. `dz` descend le
    zéro (une reprise: le dessus de ce qui RESTE du brut, là où le
    palpeur le trouvera)."""
    dx, dy, haut, bas = placement
    T = np.asarray(modele.triangles, dtype=float)
    if boite is None:
        if cle == 'Z+':
            pre = preparer(modele, placement, marge, pas)
            pre['decalage'] = (-dx, -dy, haut)
            return pre
        R = DIRECTIONS[cle][1]
        Tp = T @ R.T
        p = Tp.reshape(-1, 3)
        mn, mx = p.min(axis=0), p.max(axis=0)
        decalage = ((mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2, float(mx[2]))
        Tp = Tp - np.array(decalage)
        fond = float(mn[2] - mx[2])
        q = Tp.reshape(-1, 3)
        grille = Grille(q[:, 0].min() - marge, q[:, 0].max() + marge,
                        q[:, 1].min() - marge, q[:, 1].max() + marge,
                        pas=pas)
        H = carte_piece(Tp, grille, fond)
        return {'grille': grille, 'H': H, 'fond': fond, 'triangles': Tp,
                'decalage': decalage}
    R = DIRECTIONS[cle][1]
    x0, y0, z0, x1, y1, z1 = (float(v) for v in boite)
    coins = np.array([(x, y, z) for x in (x0, x1) for y in (y0, y1)
                      for z in (z0, z1)]) @ R.T
    bmn, bmx = coins.min(axis=0), coins.max(axis=0)
    if cle == 'Z+':
        decalage = (-dx, -dy, z1 + float(dz))
    else:
        decalage = ((bmn[0] + bmx[0]) / 2, (bmn[1] + bmx[1]) / 2,
                    float(bmx[2]) + float(dz))
    dec = np.array(decalage, dtype=float)
    Tpiece = T @ R.T - dec
    pmn = Tpiece.reshape(-1, 3).min(axis=0)
    pmx = Tpiece.reshape(-1, 3).max(axis=0)
    Tp = Tpiece
    if extra is not None and len(extra):
        Tp = np.concatenate([Tpiece,
                             np.asarray(extra, dtype=float) @ R.T - dec])
    fond = float(pmn[2])
    kmn, kmx = bmn - dec, bmx - dec
    grille = Grille(kmn[0] - marge, kmx[0] + marge, kmn[1] - marge,
                    kmx[1] + marge, pas=pas)
    H = carte_piece(Tp, grille, fond)
    # la pièce seule (sans le cadre ni les ponts): là où l'on finit
    H_piece = carte_piece(Tpiece, grille, fond) if len(Tp) != len(Tpiece) \
        else H
    return {'grille': grille, 'H': H, 'fond': fond, 'triangles': Tp,
            'decalage': decalage, 'H_piece': H_piece,
            'boite': (*(float(v) for v in kmn), *(float(v) for v in kmx)),
            'piece': (*(float(v) for v in pmn), *(float(v) for v in pmx))}


class _VuePhase:
    """La pièce telle qu'une phase la voit (pour proposer sa gamme):
    triangles et faces tournés."""

    def __init__(self, modele, cle: str):
        R = DIRECTIONS[cle][1]
        self.triangles = np.asarray(modele.triangles, dtype=float) @ R.T
        self.face_de = getattr(modele, 'face_de', None)
        self.faces = []
        for f in getattr(modele, 'faces', None) or []:
            g = dict(f)
            for cle_v in ('normale', 'axe', 'centre'):
                if g.get(cle_v) is not None:
                    g[cle_v] = R @ np.asarray(g[cle_v], dtype=float)
            self.faces.append(g)

    def bornes(self):
        p = self.triangles.reshape(-1, 3)
        return (*p.min(axis=0), *p.max(axis=0))


def _surplus(cle: str, brut: Optional[Dict]) -> float:
    """La matière au-dessus de la pièce, vue de la phase: ce que la
    première passe doit traverser en plus."""
    if not brut:
        return 0.0
    if cle == 'Z+':
        return float(brut.get('dessus', 0.0))
    if cle == 'Z-':
        return float(brut.get('dessous', 0.0))
    return float(brut.get('cotes', 0.0))


def proposer_phase(modele, placement, cle: str, bibliotheque,
                   brut: Dict = None):
    """La gamme proposée pour une phase (voir proposer_gamme); avec un
    brut, l'outil doit aussi traverser sa surépaisseur."""
    plus = _surplus(cle, brut)
    if cle == 'Z+':
        dx, dy, haut, bas = placement
        return proposer_gamme(modele, (dx, dy, haut + plus, bas),
                              bibliotheque)
    vue = _VuePhase(modele, cle)
    b = vue.bornes()
    return proposer_gamme(vue, (0.0, 0.0, b[5] + plus, b[2]), bibliotheque)


def _calculer_phases_sans_brut(modele, placement, gammes, phases, pas,
                               progression, prefixes=None) -> Dict:
    """Les phases d'une pièce ajustée au brut (sans surépaisseur ni
    tenue): la première par le dessus, au zéro du dessin."""
    from src.core import vcarve
    sortie = []
    colonnes = None
    n = max(1, len(phases))
    for k, ph in enumerate(phases):
        cle = ph['cle']
        gamme = gammes.get(cle) or []
        if not gamme:
            continue
        sous = vcarve.sous_progression(progression, k / n, (k + 1) / n,
                                       f"phase {k + 1} — ")
        pre = preparer_phase(modele, placement, cle, _marge(gamme), pas)
        S0 = None
        if colonnes is not None:
            S0 = colonnes.stock(cle, pre['grille'], pre['decalage'],
                                pre['fond'])
        res = calculer_carte(pre['H'], pre['grille'], pre['fond'], gamme,
                             S0, sous, prefixe=_prefixe(prefixes, k))
        res.update({'grille': pre['grille'], 'H': pre['H'],
                    'fond': pre['fond'], 'decalage': pre['decalage']})
        if cle == 'Z+':
            colonnes = Colonnes.apres_dessus(pre['grille'], res['S'],
                                             pre['fond'], pre['decalage'])
        elif cle == 'Z-' and colonnes is not None:
            colonnes.apres_dessous(res['S'], pre['grille'],
                                   pre['decalage'])
        sortie.append({'phase': ph, 'resultat': res})
    vcarve.avancer(progression, 1.0, "phases calculées")
    entailles = sum(r['resultat']['controle']['entailles'] for r in sortie)
    return {'phases': sortie,
            'controle': {'entailles': entailles,
                         'phases': len(sortie)}}


def _prefixe(prefixes, k: int) -> str:
    if prefixes and k < len(prefixes) and prefixes[k]:
        return prefixes[k]
    return f"PHASE{k + 1}"


def calculer_phases(modele, placement, gammes: Dict[str, List[Dict]],
                    phases: Sequence[Dict], pas=None, progression=None,
                    brut: Dict = None, tenue: Dict = None,
                    prefixes: Sequence[str] = None,
                    bibliotheque=None, tolerance: float = None) -> Dict:
    """Toutes les phases, dans l'ordre: chacune part de la matière que
    les précédentes ont laissée. `gammes`: {clé de phase: gamme}.
    Rend {'phases': [{'phase', 'resultat'}], 'controle'}.

    Avec un `brut` et une `tenue` (src/core/tenue): le brut réel (zéro
    Z sur son dessus, surépaisseurs surfacées, la prise sous la pièce),
    les mors et la plaque protégés, le vide sous la matière restante
    jamais visité; chaque phase porte son bridage, son zéro et ses
    opérations en plus ('extras': palpages, surfaçage de la prise,
    perçage et taraudage pour la plaque)."""
    gammes = {cle: _avec_tolerance(g or [], tolerance)
              for cle, g in gammes.items()}
    if brut is None and tenue is None:
        return _calculer_phases_sans_brut(modele, placement, gammes,
                                          phases, pas, progression,
                                          prefixes)
    from src.core import tenue as tn
    from src.core import vcarve
    t = tn.regler(tenue)
    brut = dict(tn.brut_defaut(), **(brut or {}))
    mode = t['mode']
    boite = tn.boite_brut(modele, brut)
    extra = tn.triangles_tenue(modele, brut, t)
    marges = [_marge(g) for g in gammes.values() if g] or [2.0]
    pre0 = preparer_phase(modele, placement, 'Z+', max(marges), pas,
                          boite, extra)
    colonnes = Colonnes.du_brut(pre0['grille'], pre0['decalage'], boite)
    vis = None
    if mode == 'plaque' and t.get('plaque'):
        vis = t.get('_vis_placement') or tn.placer_sur_plaque(
            modele, brut, t, t['plaque'])
        t['_vis'] = vis['vis']
        t['_vis_placement'] = vis
    sortie = []
    n = max(1, len(phases))
    for rang, ph in enumerate(phases):
        cle = ph['cle']
        gamme = [dict(e) for e in (gammes.get(cle) or [])]
        if not gamme:
            continue
        sous = vcarve.sous_progression(progression, rang / n,
                                       (rang + 1) / n,
                                       f"phase {rang + 1} — ")
        pre = preparer_phase(modele, placement, cle, _marge(gamme), pas,
                             boite, extra)
        S0, P = colonnes.stock_et_plancher(cle, pre['grille'],
                                           pre['decalage'], pre['fond'])
        # le zéro Z d'une reprise sur ce qui reste, là où le palpeur le
        # touchera: une reprise couchée ne retrouve pas la surépaisseur,
        # déjà partie
        point_z = (0.0, 0.0)
        if rang > 0:
            haut_reste, point_z = _zero_reprise(pre, S0)
            if abs(haut_reste) > 1e-3:
                pre = preparer_phase(modele, placement, cle, _marge(gamme),
                                     pas, boite, extra, dz=haut_reste)
                S0, P = colonnes.stock_et_plancher(
                    cle, pre['grille'], pre['decalage'], pre['fond'])
        g, H, fond = pre['grille'], pre['H'], pre['fond']
        # sous de la matière qui flotte (la prise retournée, au-dessus
        # du vide laissé autour de la pièce): l'outil s'arrête à elle
        vide = np.where(np.isfinite(P) & (P > H + EPS_MATIERE), P, -np.inf)
        obst = _obstacles_tenue(mode, rang, pre, t, brut)
        piece = H > fond + 1e-6
        etapes = gamme
        surfacage = (mode == 'etau' and cle == 'Z-' and rang > 0
                     and float(brut.get('dessous', 0.0)) > 0)
        if surfacage:
            plancher = float(H[piece].max()) if piece.any() else fond
            s0 = dict(gamme[0])
            s0.update({'nom': "Surfaçage de la prise", 'role': 'ebauche',
                       'strategie': 'niveaux', 'surepaisseur': 0.0,
                       'plancher': plancher})
            etapes = [s0] + gamme
        res = calculer_carte(H, g, fond, etapes, S0, sous,
                             prefixe=_prefixe(prefixes, rang),
                             obstacles=obst, H_piece=pre.get('H_piece'),
                             vide=vide)
        res.update({'grille': g, 'H': H, 'fond': fond,
                    'decalage': pre['decalage'], 'obstacles': obst,
                    'boite': pre['boite'], 'piece': pre['piece']})
        if cle == 'Z+':
            colonnes.enlever_dessus(res['S'], g, fond, pre['decalage'])
        elif cle == 'Z-':
            colonnes.apres_dessous(res['S'], g, pre['decalage'])
        ph = dict(ph)
        ph['rang'] = rang
        ph['bridage'] = tn.texte_bridage(mode, cle, rang, t, brut)
        ph['zero'] = _texte_zero(mode, cle, rang, t)
        ph['extras'] = _extras_phase(mode, cle, rang, pre, t, brut, vis,
                                     surfacage, bibliotheque, point_z)
        ph['colonnes'] = (colonnes.xs.copy(), colonnes.ys.copy(),
                          colonnes.bas.copy(), colonnes.haut.copy())
        sortie.append({'phase': ph, 'resultat': res})
    # le squelette: les ponts se coupent à la fin (la pièce se libère)
    if mode == 'squelette' and sortie:
        coupe = couper_ponts(modele, brut, t, sortie, gammes)
        if coupe:
            sortie[coupe['rang']]['phase']['extras']['apres'] += \
                coupe['operations']
            sortie[coupe['rang']]['phase']['ponts_coupes'] = coupe['n']
    vcarve.avancer(progression, 1.0, "phases calculées")
    entailles = sum(r['resultat']['controle']['entailles'] for r in sortie)
    return {'phases': sortie, 'brut': brut, 'tenue': t, 'boite': boite,
            'vis': vis,
            'controle': {'entailles': entailles, 'phases': len(sortie)}}


def _outil_ponts(gamme: Sequence[Dict]):
    """La plus petite fraise plate de la gamme (elle passe entre la
    pièce et le cadre): l'étape, ou None."""
    plates = [e for e in gamme or []
              if (e.get('forme') or {}).get('forme', 'plate') == 'plate'
              and e.get('outil')]
    return min(plates, key=lambda e: float(e['forme'].get('rayon', 1.0)),
               default=None)


def couper_ponts(modele, brut: Dict, tenue: Dict, phases: Sequence[Dict],
                 gammes: Dict[str, List[Dict]]) -> Optional[Dict]:
    """La coupe des ponts du squelette, en fin de gamme: dans la
    dernière phase usinée par le dessus ou le dessous (Z+ / Z−), la plus
    petite fraise plate fraise chaque pont jusqu'à la pièce — son bord
    affleure la silhouette, sans l'entamer —, de son dessus jusque sous
    lui, après une pause (la pièce va se libérer). Rend {'rang',
    'operations', 'n'} ou None.

    Par le dessus (la seule phase usinée est Z+), le cadre domine les
    ponts de toute la hauteur de la pièce: les lignes s'arrêtent à son
    bord, et la fraise ne descend en rapide que jusqu'au-dessus de ce qui
    reste de matière sous elle — le reste en plongée."""
    from shapely.affinity import rotate
    from shapely.geometry import LineString, box
    from src.core import tenue as tn
    ponts = tn.ponts_squelette(modele, brut, tenue)
    if not ponts:
        return None
    rang = next((k for k in range(len(phases) - 1, -1, -1)
                 if phases[k]['phase']['cle'] in ('Z+', 'Z-')), None)
    if rang is None:
        return None
    item = phases[rang]
    cle = item['phase']['cle']
    et = _outil_ponts(gammes.get(cle))
    if et is None:
        return None
    r = float(et['forme'].get('rayon', 1.0))
    R = DIRECTIONS[cle][1]
    dec = np.asarray(item['resultat']['decalage'], dtype=float)
    piece = tn.silhouette_piece(modele)
    # ce qui reste de matière après la phase, sous le disque de la fraise
    # (une case et demie de marge: la grille arrondit)
    grille, reste = item['resultat'].get('grille'), item['resultat'].get('S')
    sous_fraise = None
    if grille is not None and reste is not None:
        sous_fraise = dilater_disque(np.asarray(reste, dtype=float),
                                     r / grille.pas + 1.5)

    def approche(x, y, z_pont):
        """Jusqu'où descendre en rapide en (x, y): au-dessus du pont, et de
        ce qui reste de matière sous la fraise."""
        z = z_pont + APPROCHE
        if sous_fraise is not None:
            j, i = grille.indices(x, y)
            la = float(sous_fraise[j, i])
            if np.isfinite(la):
                z = max(z, la + APPROCHE)
        return z

    # le cadre (repère de la pièce): son dessus est celui de la pièce
    b = modele.bornes()
    (ex0, ey0, ex1, ey1), (ix0, iy0, ix1, iy1) = tn.cadre(
        tn.boite_brut(modele, brut), tn.regler(tenue)['largeur_cadre'])
    cadre = None
    if ix1 > ix0 and iy1 > iy0:
        cadre = box(ex0, ey0, ex1, ey1).difference(box(ix0, iy0, ix1, iy1))
    z_cadre = max(float((np.array([0.0, 0.0, z]) @ R.T - dec)[2])
                  for z in (float(b[2]), float(b[5])))

    def plan(geom, z=0.0):
        """Du repère de la pièce au plan de la phase (XY)."""
        from shapely.ops import transform

        def f(x, y, zz=None):
            p = np.column_stack([np.atleast_1d(x), np.atleast_1d(y),
                                 np.full(np.size(x), z)]) @ R.T - dec
            return p[:, 0], p[:, 1]
        return transform(f, geom)

    ecr = _Ecrivain("PONTS")
    premier = True
    n = 0
    for pont in ponts:
        z_ext = sorted((np.array([0.0, 0.0, pont['z0']]) @ R.T - dec)[2:3]
                       .tolist() + (np.array([0.0, 0.0, pont['z1']])
                                    @ R.T - dec)[2:3].tolist())
        z_bas, z_haut = z_ext[0], z_ext[1]
        B = plan(pont['polygone'])
        interdit = plan(piece).buffer(r + 0.01) if piece is not None \
            else None
        if cadre is not None and z_cadre > z_haut + 0.05:
            # le cadre plus haut que le pont (la coupe par le dessus): la
            # fraise l'affleure (0,05 mm dedans: le pont est bien coupé)
            # au lieu d'y entrer de tout son diamètre, à pleine hauteur
            mur = plan(cadre).buffer(r - 0.05)
            interdit = mur if interdit is None else interdit.union(mur)
        # des lignes le long du pont, espacées de moins d'un rayon,
        # jusqu'à un rayon au-delà de ses bords
        mrr = B.minimum_rotated_rectangle
        coins = np.asarray(mrr.exterior.coords)[:4]
        cotes = [np.linalg.norm(coins[1] - coins[0]),
                 np.linalg.norm(coins[2] - coins[1])]
        k = int(np.argmax(cotes))
        axe = coins[k + 1] - coins[k]
        angle = float(np.degrees(np.arctan2(axe[1], axe[0])))
        centre = B.centroid
        Bt = rotate(B, -angle, origin=centre)
        x0, y0, x1, y1 = Bt.bounds
        pas = max(0.2, 0.9 * r)
        ny = max(1, int(np.ceil((y1 - y0 + 2 * r) / pas)))
        lignes = []
        for i in range(ny + 1):
            y = y0 - r + (y1 - y0 + 2 * r) * i / ny
            ligne = rotate(LineString([(x0 - r, y), (x1 + r, y)]), angle,
                           origin=centre)
            if interdit is not None:
                ligne = ligne.difference(interdit)
            for g in getattr(ligne, 'geoms', [ligne]):
                if g.length > 1e-3:
                    lignes.append(np.asarray(g.coords))
        if not lignes:
            continue
        n += 1
        ap = max(0.1, min(float(et.get('passe_z', 1.0) or 1.0), 2 * r))
        niveaux = []
        z = z_haut
        while z > z_bas - 0.15 + 1e-9:
            z = max(z - ap, z_bas - 0.15)
            niveaux.append(z)
        for z in niveaux:
            for j, pts in enumerate(lignes):
                pts = pts if j % 2 == 0 else pts[::-1]
                if premier:
                    ecr.placer(pts[0][0], pts[0][1])
                    premier = False
                else:
                    ecr.rapide(z=max(APPROCHE, z_haut + APPROCHE))
                    ecr.rapide(pts[0][0], pts[0][1])
                ecr.rapide(z=approche(pts[0][0], pts[0][1], z_haut))
                ecr.ligne(z=z, feed="Plunge")
                for x, y in pts[1:]:
                    ecr.ligne(x, y, feed="Roughing")
                # (la remontée en avance jusqu'au-dessus de la matière
                # qui reste: contre le cadre, la fraise l'affleure)
                ecr.ligne(z=approche(pts[-1][0], pts[-1][1], z_haut))
    if not n:
        return None
    ecr.degager()
    corps = ecr.texte().split('\n', 1)[1]
    pause = {'operation_type': 'dialogue_operateur',
             'name': "Couper les ponts", 'x': 0.0, 'y': 0.0, 'points': [],
             'tool_id': '',
             'params': {'message': (
                 f"Couper les {n} ponts: la piece va se liberer du cadre. "
                 "La retenir (ventouse, adhesif) ou la laisser tomber dans "
                 "le bac."), 'dialog_type': 'ask_continue',
                 'park_before': True}}
    seq = {'operation_type': 'sequence_datron',
           'name': f"Ponts coupés ({n})", 'x': 0.0, 'y': 0.0, 'points': [],
           'params': {'sequence_name': "PONTS", 'sequence_code': corps},
           'tool_id': et['outil']}
    return {'rang': rang, 'operations': [pause, seq], 'n': n}


def _obstacles_tenue(mode: str, rang: int, pre: Dict, t: Dict,
                     brut: Dict) -> np.ndarray:
    """Ce qui tient la pièce dans cette phase, et que l'outil ne doit
    pas toucher: les mors (au jeu près), le plateau de la plaque."""
    from src.core import tenue as tn
    g, H, fond = pre['grille'], pre['H'], pre['fond']
    bx0, by0, bz0, bx1, by1, bz1 = pre['boite']
    px0, py0, pz0, px1, py1, pz1 = pre['piece']
    jeu = float(t.get('jeu_mors', 1.0))
    serrage = float(t.get('serrage_reprise', 3.0))
    dessous = float(brut.get('dessous', 0.0))
    if mode == 'plaque':
        if rang == 0:
            # le dos en haut, brut en étau: les mors, et rien hors de la
            # pièce plus bas que son dos (les flancs se font vissée)
            sortie = tn.obstacle_mors(g, by0, by1, bz0 + serrage + jeu)
            piece = H > fond + 1e-6
            dos = float(H[piece].max()) if piece.any() else fond
            return np.maximum(sortie, np.where(piece, -np.inf, dos))
        # vissée: le plateau de la plaque sous la pièce
        return np.full(H.shape, fond + float(t.get('jeu_plaque', 0.1)))
    if rang == 0:
        prise = dessous if dessous > 0 else serrage
        return tn.obstacle_mors(g, by0, by1, bz0 + prise + jeu)
    if mode == 'squelette':
        e = tn.PEAU_FLANCS
        return tn.obstacle_mors(g, by0 + e, by1 - e, pz0 + serrage + jeu)
    return tn.obstacle_mors(g, py0, py1, pz0 + serrage + jeu)


def _texte_zero(mode: str, cle: str, rang: int, t: Dict) -> str:
    palpe = t.get('palpage', 'aucun') not in (None, '', 'aucun')
    if rang == 0 and not (palpe and t.get('palpage_phase1')):
        if cle == 'Z+':
            return "Zero XY comme le dessin, Z sur le dessus du brut"
        return "Zero XY au centre du brut, Z sur le dessus du brut"
    if palpe:
        return "Zero repris par le palpage du programme"
    return ("Zero XY au centre de la piece, Z sur le dessus du brut tel "
            "que pose")


def _decalage_op(dx: float, dy: float, dz: float, nom: str) -> Dict:
    return {'operation_type': 'decalage_origine', 'name': nom, 'x': 0.0,
            'y': 0.0, 'points': [],
            'params': {'shift_x': round(float(dx), 4),
                       'shift_y': round(float(dy), 4),
                       'shift_z': round(float(dz), 4)}}


def _zero_reprise(pre: Dict, S0) -> Tuple[float, Tuple[float, float]]:
    """Le zéro Z d'une reprise, dans le repère de `pre`: le dessus de
    la matière où le palpeur touchera — sur la pièce, au plus près de son
    centre, parmi le haut de la matière (un copeau resté à un coin n'est
    pas une face à palper). Si de la matière dépasse au point que les
    rapides (APPROCHE au-dessus du zéro) la toucheraient, le zéro monte
    sur elle. Rend (cote, (dx, dy) du point de palpage depuis le centre
    de la pièce)."""
    g, fond = pre['grille'], pre['fond']
    S0 = np.asarray(S0, dtype=float)
    Hp = pre.get('H_piece', pre['H'])
    matiere = S0 > fond + EPS_MATIERE
    if not matiere.any():
        return 0.0, (0.0, 0.0)
    cand = matiere & (Hp > fond + 1e-6)
    if not cand.any():
        cand = matiere
    px0, py0, _z0, px1, py1, _z1 = pre['piece']
    cx, cy = (px0 + px1) / 2, (py0 + py1) / 2
    seuil = float(np.percentile(S0[cand], 75)) - 0.01
    j, i = np.nonzero(cand & (S0 >= seuil))
    k = int(np.argmin(np.hypot(g.xc[i] - cx, g.yc[j] - cy)))
    z0 = float(S0[j[k], i[k]])
    point = (g.xc[i[k]], g.yc[j[k]])
    haut = float(S0[matiere].max())
    if haut > z0 + APPROCHE - 0.3:
        jj, ii = np.nonzero(matiere & (S0 >= haut - 0.01))
        kk = int(np.argmin(np.hypot(g.xc[ii] - cx, g.yc[jj] - cy)))
        z0 = haut
        point = (g.xc[ii[kk]], g.yc[jj[kk]])
    return z0, (round(float(point[0] - cx), 3),
                round(float(point[1] - cy), 3))


def _extras_phase(mode: str, cle: str, rang: int, pre: Dict, t: Dict,
                  brut: Dict, vis, surfacage: bool,
                  bibliotheque=None, point_z=(0.0, 0.0)) -> Dict:
    """Les opérations qu'une phase ajoute à ses séquences: 'reprise' (le
    retournement: pause et palpage), 'avant', 'apres_etape' {index de
    séquence: [ops]}, 'apres'."""
    from src.core import tenue as tn
    extras = {'reprise': None, 'avant': [], 'apres_etape': {}, 'apres': []}
    genre = t.get('palpage', 'aucun')
    prof = float(t.get('profondeur_palpage', 2.0))
    dessous = float(brut.get('dessous', 0.0))
    bx0, by0, bz0, bx1, by1, bz1 = pre['boite']
    px0, py0, pz0, px1, py1, pz1 = pre['piece']
    brut_lx, brut_ly = bx1 - bx0, by1 - by0
    brut_c = ((bx0 + bx1) / 2, (by0 + by1) / 2)
    piece_lx, piece_ly = px1 - px0, py1 - py0
    piece_c = ((px0 + px1) / 2, (py0 + py1) / 2)

    def palpage(lx, ly, profondeur, nom, centre, mesurer_z=True):
        ops = []
        op = tn.op_palpage(genre, lx, ly, profondeur, nom,
                           mesurer_z=mesurer_z)
        if op is None:
            return ops
        ops.append(op)
        # l'origine palpée est le centre du corps: la ramener à celle
        # du programme
        if genre != 'z' and math.hypot(*centre) > 1e-3:
            ops.append(_decalage_op(-centre[0], -centre[1], 0.0,
                                    "Origine du programme"))
        return ops

    if rang == 0:
        if t.get('palpage_phase1'):
            extras['avant'] += palpage(brut_lx, brut_ly, min(prof, 2.0),
                                       "Palpage du brut", brut_c)
    else:
        if mode == 'etau' and surfacage:
            # le brut retourné: palpé grossièrement (Z, et la position
            # pour surfacer la prise), puis finement sur les flancs
            # usinés quand la prise est partie
            extras['reprise'] = {'largeur_x': brut_lx, 'largeur_y': brut_ly,
                                 'profondeur': max(0.5, min(1.5,
                                                            dessous / 2)),
                                 'centre': brut_c}
            # le Z reste celui du brut palpé avant le surfaçage
            extras['apres_etape'][0] = palpage(
                piece_lx, piece_ly, prof, "Palpage des flancs usinés",
                piece_c, mesurer_z=False)
        elif mode == 'squelette':
            e = tn.PEAU_FLANCS
            extras['reprise'] = {'largeur_x': brut_lx - 2 * e,
                                 'largeur_y': brut_ly - 2 * e,
                                 'profondeur': dessous + prof,
                                 'centre': brut_c}
        elif mode == 'plaque':
            extras['reprise'] = {'largeur_x': brut_lx, 'largeur_y': brut_ly,
                                 'profondeur': prof, 'centre': brut_c,
                                 'nom': "visser sur la plaque et palper"}
        else:
            extras['reprise'] = {'largeur_x': piece_lx,
                                 'largeur_y': piece_ly,
                                 'profondeur': prof, 'centre': piece_c}
        if extras['reprise'] is not None:
            # le Z se palpe où le zéro a été pris (depuis le centre du
            # corps palpé)
            c = extras['reprise']['centre']
            extras['reprise']['z_decale'] = (
                round(piece_c[0] + point_z[0] - c[0], 3),
                round(piece_c[1] + point_z[1] - c[1], 3))
    if mode == 'plaque' and rang == 0 and vis and vis.get('vis'):
        extras['apres'] = _ops_taraudage_dos(pre, t, brut, vis,
                                             bibliotheque)
    return extras


def _ops_taraudage_dos(pre: Dict, t: Dict, brut: Dict, vis: Dict,
                       bibliotheque=None) -> List[Dict]:
    """Phase 0 de la plaque: aux trous de la plaque sous la pièce, le
    perçage (facultatif) et le taraudage, depuis le dos surfacé."""
    from src.operations.taraudage import AVANT_TROU
    from src.operations import depuis_selection as ds
    cx, cy, _cz = pre['decalage']
    # repère de la pièce → repère du dos (retournée autour de X)
    pts = [{'x': float(round(float(x) - float(cx), 4)),
            'y': float(round(-float(y) - float(cy), 4))}
           for x, y in vis['vis']]
    filet = t.get('filetage', 'M4')
    dessous = float(brut.get('dessous', 0.0))
    ops = []
    if dessous > 0:
        ops.append(_decalage_op(0.0, 0.0, -dessous,
                                "Zéro Z sur le dos surfacé"))
    if t.get('avant_trou', True):
        prof = t.get('profondeur_avant_trou') or ds.profondeur_avant_trou(
            filet, float(t['profondeur_taraudage']))
        op = ds.op_avant_trou({'avant_trou': True, 'thread_name': filet,
                               'depth': float(t['profondeur_taraudage']),
                               'profondeur_avant_trou': float(prof)},
                              pts, bibliotheque)
        if op is not None:
            op['name'] = f"Avant-trou {filet} Ø{AVANT_TROU.get(filet, 0):g}"
            ops.append(op)
    tar = {'operation_type': 'taraudage', 'name': f"Taraudage {filet} "
           f"({len(pts)} vis de plaque)", 'x': pts[0]['x'], 'y': pts[0]['y'],
           'points': pts,
           'params': {'thread_name': filet,
                      'depth': float(t['profondeur_taraudage'])}}
    for tid, outil in (getattr(bibliotheque, 'tools', None) or {}).items():
        if getattr(outil, 'type_taraudage', None) == filet:
            tar['tool_id'] = tid
            break
    ops.append(tar)
    if dessous > 0:
        ops.append(_decalage_op(0.0, 0.0, dessous, "Zéro Z rendu"))
    return ops


def operations_phases(calcul: Dict, nom_piece: str = "pièce") -> List[Dict]:
    """Les opérations de toutes les phases: celles de la première, puis
    pour chaque suivante une reprise (retourner, brider, refaire le
    zéro — un « Retournement pièce » qui palpe, ou une pause) et ses
    séquences, ses palpages, ses perçages — chaque phase en un ensemble
    libre (chaque séquence garde son outil)."""
    import uuid
    ops = []
    for k, item in enumerate(calcul.get('phases', [])):
        ph, res = item['phase'], item['resultat']
        gid = str(uuid.uuid4())[:8]
        nom_groupe = f"Phase {k + 1} - {ph['libelle']}"
        extras = ph.get('extras') or {}
        groupe = []
        if k:
            message = (f"Phase {k + 1}: {ph['libelle']}. {ph['bridage']}. "
                       f"{ph['zero']}.")
            reprise = extras.get('reprise')
            palpe = (calcul.get('tenue') or {}).get('palpage') == 'rectangle'
            if reprise and palpe:
                groupe.append({
                    'operation_type': 'retournement_piece',
                    'name': f"Phase {k + 1}: "
                            + reprise.get('nom', "retourner et palper"),
                    'x': 0.0, 'y': 0.0, 'points': [], 'tool_id': '',
                    'params': {'message': message,
                               'width_x': round(reprise['largeur_x'], 3),
                               'width_y': round(reprise['largeur_y'], 3),
                               'probe_depth': round(reprise['profondeur'],
                                                    3),
                               'z_measure_x_shift':
                                   (reprise.get('z_decale') or (0, 0))[0],
                               'z_measure_y_shift':
                                   (reprise.get('z_decale') or (0, 0))[1]}})
                c = reprise.get('centre') or (0.0, 0.0)
                if math.hypot(*c) > 1e-3:
                    groupe.append(_decalage_op(-c[0], -c[1], 0.0,
                                               "Origine du programme"))
            else:
                groupe.append({
                    'operation_type': 'dialogue_operateur',
                    'name': f"Phase {k + 1}: brider", 'x': 0.0, 'y': 0.0,
                    'points': [], 'tool_id': '',
                    'params': {'message': message,
                               'dialog_type': 'ask_continue',
                               'park_before': True}})
                if reprise:
                    from src.core import tenue as tn
                    genre = (calcul.get('tenue') or {}).get('palpage')
                    op = tn.op_palpage(genre, reprise['largeur_x'],
                                       reprise['largeur_y'],
                                       reprise['profondeur'],
                                       f"Phase {k + 1}: palpage")
                    if op is not None:
                        groupe.append(op)
                        c = reprise.get('centre') or (0.0, 0.0)
                        if genre != 'z' and math.hypot(*c) > 1e-3:
                            groupe.append(_decalage_op(
                                -c[0], -c[1], 0.0, "Origine du programme"))
        groupe += [dict(o) for o in extras.get('avant', [])]
        apres_etape = extras.get('apres_etape') or {}
        for i, o in enumerate(operations(res, nom_piece)):
            o['name'] = f"P{k + 1} {o['name']}"
            groupe.append(o)
            groupe += [dict(e) for e in apres_etape.get(i, [])]
        groupe += [dict(o) for o in extras.get('apres', [])]
        for o in groupe:
            o['group_id'] = gid
            o['group_name'] = nom_groupe
            # chaque séquence garde SON outil
            o['group_libre'] = True
        ops += groupe
    return ops
