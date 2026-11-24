"""Une police à trait simple, pour simuler la gravure de texte Datron.

Engrave::StandardTextEngrave grave avec la police interne de la
machine, à TRAIT SIMPLE: l'outil passe une fois par trait. Tracer le
contour d'une police ordinaire avec une pointe de 0,3 mm empâte les
lettres de 2 mm jusqu'à les rendre illisibles. Celle-ci est dessinée
à la main, sur une grille de 4 × 6 (capitale = 6), dans l'esprit des
polices de gravure: chiffres, capitales (les minuscules prennent la
forme des capitales), ponctuation courante.

Ce n'est pas la police Datron: les proportions sont proches, le dessin
des lettres diffère. Assez pour lire une référence ou une date dans la
simulation.

Les MINUSCULES (descendantes sous la ligne de base, hauteur d'x 4) et
quelques signes (± ⌀ ~ ^ { } | $) viennent de « CADCraft Stroke », la
police à trait simple de CADCraft (crate fonts, versée au domaine
public / CC0 par ses auteurs; dépôt © 2026 ArtCraft Team and the
CADCraft contributors, licence MIT — voir THIRD_PARTY_NOTICES.md):
même grille (capitale = 6), même esprit. Les minuscules accentuées
portent leur accent; les capitales restent sans (place de la ligne).

`traits` garde la chasse FIXE de la gravure Datron (simulation);
`texte_place` compose en chasse proportionnelle, sur plusieurs lignes,
alignée et tournée: la forme « Texte » du Tracé, gravée en trait
simple par NeoDrive lui-même.
"""

import math

from typing import Dict, List, Tuple

#: hauteur de capitale et chasse, en unités de la grille
HAUTEUR = 6.0
CHASSE = 5.5

_DESSINS = {
    '0': ["1,0 3,0 4,1 4,5 3,6 1,6 0,5 0,1 1,0"],
    '1': ["1,5 2,6 2,0", "1,0 3,0"],
    '2': ["0,5 1,6 3,6 4,5 4,4 0,0 4,0"],
    '3': ["0,5 1,6 3,6 4,5 4,4 3,3 1,3", "3,3 4,2 4,1 3,0 1,0 0,1"],
    '4': ["3,0 3,6 0,2 4,2"],
    '5': ["4,6 0,6 0,3 3,3 4,2 4,1 3,0 0,0"],
    '6': ["4,5 3,6 1,6 0,5 0,1 1,0 3,0 4,1 4,2 3,3 0,3"],
    '7': ["0,6 4,6 1,0"],
    '8': ["1,3 0,4 0,5 1,6 3,6 4,5 4,4 3,3 1,3 0,2 0,1 1,0 3,0 4,1 "
          "4,2 3,3"],
    '9': ["4,3 1,3 0,4 0,5 1,6 3,6 4,5 4,1 3,0 1,0 0,1"],
    'A': ["0,0 0,4 2,6 4,4 4,0", "0,3 4,3"],
    'B': ["0,0 0,6 3,6 4,5 4,4 3,3 0,3", "3,3 4,2 4,1 3,0 0,0"],
    'C': ["4,5 3,6 1,6 0,5 0,1 1,0 3,0 4,1"],
    'D': ["0,0 0,6 2,6 4,4 4,2 2,0 0,0"],
    'E': ["4,6 0,6 0,0 4,0", "0,3 3,3"],
    'F': ["4,6 0,6 0,0", "0,3 3,3"],
    'G': ["4,5 3,6 1,6 0,5 0,1 1,0 3,0 4,1 4,3 2,3"],
    'H': ["0,0 0,6", "4,0 4,6", "0,3 4,3"],
    'I': ["1,6 3,6", "2,6 2,0", "1,0 3,0"],
    'J': ["1,6 4,6", "3,6 3,1 2,0 1,0 0,1"],
    'K': ["0,0 0,6", "4,6 0,2", "1,3 4,0"],
    'L': ["0,6 0,0 4,0"],
    'M': ["0,0 0,6 2,3 4,6 4,0"],
    'N': ["0,0 0,6 4,0 4,6"],
    'O': ["1,0 3,0 4,1 4,5 3,6 1,6 0,5 0,1 1,0"],
    'P': ["0,0 0,6 3,6 4,5 4,4 3,3 0,3"],
    'Q': ["1,0 3,0 4,1 4,5 3,6 1,6 0,5 0,1 1,0", "2,2 4,0"],
    'R': ["0,0 0,6 3,6 4,5 4,4 3,3 0,3", "2,3 4,0"],
    'S': ["4,5 3,6 1,6 0,5 0,4 1,3 3,3 4,2 4,1 3,0 1,0 0,1"],
    'T': ["0,6 4,6", "2,6 2,0"],
    'U': ["0,6 0,1 1,0 3,0 4,1 4,6"],
    'V': ["0,6 2,0 4,6"],
    'W': ["0,6 1,0 2,3 3,0 4,6"],
    'X': ["0,0 4,6", "0,6 4,0"],
    'Y': ["0,6 2,3 4,6", "2,3 2,0"],
    'Z': ["0,6 4,6 0,0 4,0"],
    '-': ["1,3 3,3"],
    '+': ["1,3 3,3", "2,2 2,4"],
    '=': ["1,2 3,2", "1,4 3,4"],
    '.': ["2,0 2,0.4"],
    ',': ["2,0.4 1.6,-0.6"],
    ':': ["2,1 2,1.4", "2,4 2,4.4"],
    ';': ["2,4 2,4.4", "2,1 1.6,0"],
    '/': ["0,0 4,6"],
    '\\': ["0,6 4,0"],
    '_': ["0,-0.5 4,-0.5"],
    '(': ["3,6 2,5 2,1 3,0"],
    ')': ["1,6 2,5 2,1 1,0"],
    '[': ["3,6 2,6 2,0 3,0"],
    ']': ["1,6 2,6 2,0 1,0"],
    '#': ["1,1 1,5", "3,1 3,5", "0,2 4,2", "0,4 4,4"],
    '*': ["2,1.5 2,4.5", "0.7,2.2 3.3,3.8", "0.7,3.8 3.3,2.2"],
    '°': ["1.5,5 2,5.5 2.5,5 2,4.5 1.5,5"],
    'Ø': ["1,0 3,0 4,1 4,5 3,6 1,6 0,5 0,1 1,0", "0,0 4,6"],
    "'": ["2,6 2,4.8"],
    '"': ["1.4,6 1.4,4.8", "2.6,6 2.6,4.8"],
    '!': ["2,6 2,1.6", "2,0 2,0.4"],
    '?': ["0,5 1,6 3,6 4,5 4,4 2,3 2,1.6", "2,0 2,0.4"],
    '%': ["0,0 4,6", "0.5,5 1,5.5 1.5,5 1,4.5 0.5,5",
          "2.5,1 3,1.5 3.5,1 3,0.5 2.5,1"],
    '&': ["4,0 1,4 1,5 2,6 3,5 3,4 0,2 0,1 1,0 2,0 4,2"],
    '@': ["3,2 3,4 1,4 1,2 3,2 4,3 4,5 3,6 1,6 0,5 0,1 1,0 3,0"],
    '<': ["4,5 0,3 4,1"],
    '>': ["0,5 4,3 0,1"],
}

#: « CADCraft Stroke »: (largeur, traits). Un point = deux caractères,
#: x de 0 à 6 et y en lettre: a = -2, c = 0 (ligne de base), g = 4
#: (hauteur d'x), i = 6 (capitale). Traits séparés par une espace.
_CADCRAFT = {
    'a': (4.0, "4g4c 4f3g1g0f0d1c3c4d"),
    'b': (4.0, "0i0c 0d1c3c4d4f3g1g0f"),
    'c': (4.0, "4f3g1g0f0d1c3c4d"),
    'd': (4.0, "4i4c 4d3c1c0d0f1g3g4f"),
    'e': (4.0, "0e4e4f3g1g0f0d1c3c4d"),
    'f': (3.0, "3i2i1h1c 0g3g"),
    'g': (4.0, "4g4b3a1a0b 4f3g1g0f0d1c3c4d"),
    'h': (4.0, "0i0c 0f1g3g4f4c"),
    'i': (1.0, "0c0g 0h0i"),
    'j': (2.0, "2g2b1a0a 2h2i"),
    'k': (4.0, "0i0c 3g0d 1e3c"),
    'l': (2.0, "1i1d2c"),
    'm': (4.0, "0c0g 0f1g2f2c 2f3g4f4c"),
    'n': (4.0, "0c0g 0f1g3g4f4c"),
    'o': (4.0, "1c0d0f1g3g4f4d3c1c"),
    'p': (4.0, "0g0a 0f1g3g4f4d3c1c0d"),
    'q': (4.0, "4g4a 4f3g1g0f0d1c3c4d"),
    'r': (3.0, "0c0g 0e2g3g"),
    's': (4.0, "4f3g1g0f1e3e4d3c1c0d"),
    't': (3.0, "1i1d2c3c 0g3g"),
    'u': (4.0, "0g0d1c3c4d 4g4c"),
    'v': (4.0, "0g2c4g"),
    'w': (4.0, "0g1c2f3c4g"),
    'x': (4.0, "0g4c 0c4g"),
    'y': (4.0, "0g2c 4g1a0a"),
    'z': (4.0, "0g4g0c4c"),
    '$': (4.0, "4h3i1i0h0g1f3f4e4d3c1c0d 2i2c"),
    '^': (4.0, "0g2i4g"),
    '`': (1.0, "0i1h"),
    '{': (2.0, "2i1h1g0f1e1d2c"),
    '|': (1.0, "0i0a"),
    '}': (2.0, "0i1h1g2f1e1d0c"),
    '~': (4.0, "0g1h3f4g"),
    '±': (4.0, "2e2i 0g4g 0d4d"),
    '⌀': (4.0, "1c0d0h1i3i4h4d3c1c 0c4i"),
}


def _lire_cadcraft(spec: str) -> List[List[Tuple[float, float]]]:
    traits = []
    for mot in spec.split():
        pts = []
        for k in range(0, len(mot) - 1, 2):
            pts.append((float(ord(mot[k]) - ord('0')),
                        float(ord(mot[k + 1]) - ord('a') - 2)))
        if pts:
            traits.append(pts)
    return traits


#: minuscules accentuées: (lettre de base, accent)
_ACCENTS_MIN = {
    'é': ('e', 'aigu'), 'è': ('e', 'grave'), 'ê': ('e', 'circonflexe'),
    'ë': ('e', 'trema'), 'à': ('a', 'grave'), 'â': ('a', 'circonflexe'),
    'ä': ('a', 'trema'), 'î': ('i', 'circonflexe'), 'ï': ('i', 'trema'),
    'ô': ('o', 'circonflexe'), 'ö': ('o', 'trema'), 'ù': ('u', 'grave'),
    'û': ('u', 'circonflexe'), 'ü': ('u', 'trema'), 'ç': ('c', 'cedille'),
    'ÿ': ('y', 'trema'), 'ñ': ('n', 'tilde'),
}


def _accent(nom: str, centre: float):
    """Les traits d'un accent au-dessus de la hauteur d'x (4), centré
    sur `centre`."""
    c = centre
    if nom == 'aigu':
        return [[(c - 0.5, 5.0), (c + 0.5, 6.0)]]
    if nom == 'grave':
        return [[(c - 0.5, 6.0), (c + 0.5, 5.0)]]
    if nom == 'circonflexe':
        return [[(c - 1.0, 5.0), (c, 6.0), (c + 1.0, 5.0)]]
    if nom == 'trema':
        return [[(c - 1.0, 5.4), (c - 1.0, 5.8)],
                [(c + 1.0, 5.4), (c + 1.0, 5.8)]]
    if nom == 'tilde':
        return [[(c - 1.5, 5.0), (c - 0.5, 6.0), (c + 0.5, 5.0),
                 (c + 1.5, 6.0)]]
    # cédille, sous la lettre
    return [[(c, 0.0), (c, -0.6), (c + 0.8, -1.2), (c - 0.4, -1.8)]]


_ACCENTS = {'É': 'E', 'È': 'E', 'Ê': 'E', 'Ë': 'E', 'À': 'A', 'Â': 'A',
            'Ä': 'A', 'Î': 'I', 'Ï': 'I', 'Ô': 'O', 'Ö': 'O', 'Ù': 'U',
            'Û': 'U', 'Ü': 'U', 'Ç': 'C', 'ß': 'S', 'Œ': 'O', 'Æ': 'A'}


def _lire(dessin: str) -> List[Tuple[float, float]]:
    pts = []
    for couple in dessin.split():
        x, y = couple.split(',')
        pts.append((float(x), float(y)))
    return pts


_GLYPHES: Dict[str, List[List[Tuple[float, float]]]] = {
    c: [_lire(t) for t in traits] for c, traits in _DESSINS.items()}

#: largeur dessinée de chaque glyphe (les nôtres occupent la case de 4)
_LARGEURS: Dict[str, float] = {c: 4.0 for c in _GLYPHES}
for _c, (_l, _spec) in _CADCRAFT.items():
    if _c not in _GLYPHES:
        _GLYPHES[_c] = _lire_cadcraft(_spec)
        _LARGEURS[_c] = _l
for _c, (_base, _nom) in _ACCENTS_MIN.items():
    _l = _LARGEURS[_base]
    _GLYPHES[_c] = _GLYPHES[_base] + _accent(_nom, _l / 2.0)
    _LARGEURS[_c] = _l
_ACCENTS.update({'Ÿ': 'Y', 'Ñ': 'N'})

#: espacement entre deux glyphes en chasse proportionnelle, et avance
#: d'une espace (unités de la grille)
ECART = 1.6
ESPACE = 2.4


def glyphe(caractere: str):
    """Les traits d'un caractère (grille 4 × 6), ou None s'il n'est
    pas dessiné (une espace). Une minuscule a sa forme (« CADCraft
    Stroke »); une capitale accentuée prend celle de sa lettre."""
    g = _GLYPHES.get(caractere)
    if g is not None:
        return g
    c = caractere.upper()
    c = _ACCENTS.get(c, c)
    return _GLYPHES.get(c)


def largeur(caractere: str) -> float:
    """La largeur dessinée d'un caractère (unités de grille)."""
    if caractere in _LARGEURS:
        return _LARGEURS[caractere]
    c = _ACCENTS.get(caractere.upper(), caractere.upper())
    return _LARGEURS.get(c, ESPACE)


def traits(texte: str, hauteur: float, chasse: float = 0.0
           ) -> List[List[Tuple[float, float]]]:
    """Les traits d'un texte, en mm: capitales de `hauteur`, ligne de
    base en y = 0, début en x = 0. `chasse`: avance d'un caractère
    (mm), 0 = proportionnelle à la hauteur."""
    echelle = hauteur / HAUTEUR
    avance = chasse if chasse > 0 else CHASSE * echelle
    sortie = []
    x0 = 0.0
    for ch in texte:
        g = glyphe(ch)
        if g:
            # un glyphe étroit (i, l, f…) se centre dans sa case
            decale = (4.0 - largeur(ch)) / 2.0 if largeur(ch) < 4.0 \
                else 0.0
            for trait in g:
                sortie.append([(x0 + (x + decale) * echelle, y * echelle)
                               for x, y in trait])
        x0 += avance
    return sortie


def glyphes_ligne(texte: str, hauteur: float):
    """Les lettres d'une ligne en chasse PROPORTIONNELLE: [(x de
    début, largeur, traits)] en mm, ligne de base en y = 0, traits
    déjà à leur place sur la ligne (src/core/texte_courbe les pose sur
    un arc ou un tracé)."""
    echelle = hauteur / HAUTEUR
    sortie = []
    x0 = 0.0
    for ch in texte:
        g = glyphe(ch)
        if not g:
            x0 += (ESPACE + ECART) * echelle
            continue
        xs = [x for trait in g for x, _y in trait]
        gauche, droite = min(xs), max(xs)
        traits = [[(x0 + (x - gauche) * echelle, y * echelle)
                   for x, y in trait] for trait in g]
        large = (droite - gauche) * echelle
        sortie.append((x0, large, traits))
        x0 += large + ECART * echelle
    return sortie


def ligne_proportionnelle(texte: str, hauteur: float
                          ) -> Tuple[List[List[Tuple[float, float]]], float]:
    """Une ligne en chasse PROPORTIONNELLE: (traits, largeur en mm),
    ligne de base en y = 0, début en x = 0."""
    glyphes = glyphes_ligne(texte, hauteur)
    traits = [t for _x, _l, ts in glyphes for t in ts]
    largeur = max((x + lg for x, lg, _t in glyphes), default=0.0)
    return traits, largeur


def texte_place(texte: str, hauteur: float, alignement: str = 'centre',
                interligne: float = 1.6, rotation: float = 0.0
                ) -> List[List[Tuple[float, float]]]:
    """Un texte de plusieurs lignes, en chasse proportionnelle: le
    point (0, 0) est sur la ligne de base de la PREMIÈRE ligne, au
    centre, à gauche ou à droite selon `alignement`; tourné de
    `rotation` degrés autour de lui."""
    a = math.radians(rotation)
    ca, sa = math.cos(a), math.sin(a)
    sortie = []
    for n, ligne in enumerate(str(texte).splitlines() or [""]):
        traits, large = ligne_proportionnelle(ligne, hauteur)
        dx = {'gauche': 0.0, 'droite': -large}.get(alignement,
                                                   -large / 2.0)
        dy = -n * interligne * hauteur
        for t in traits:
            sortie.append([((x + dx) * ca - (y + dy) * sa,
                            (x + dx) * sa + (y + dy) * ca) for x, y in t])
    return sortie


def connus() -> str:
    """Les caractères dessinés (pour les tests et l'aide)."""
    return "".join(sorted(_GLYPHES))
