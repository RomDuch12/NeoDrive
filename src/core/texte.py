# -*- coding: utf-8 -*-
"""Le texte comme dessin: des contours, dans une police du poste.

Une gravure de texte n'a rien de spécial une fois vectorisée: ce sont
des contours fermés, comme ceux d'un DXF — les mêmes parcours, la
même gamme, le même export. Ici, la vectorisation: une police
TrueType/OpenType de Windows (fontTools, voir `src.io.vecteur.textvec`),
la hauteur de CAPITALE demandée, un alignement, une rotation, une
position. Rien de Qt: le noyau, la génération et les tests s'en
servent sans fenêtre.
"""

import math
from typing import Dict, List, Optional, Sequence, Tuple

from src.io.vecteur import textvec

#: alignements du bloc par rapport à sa position, dans les mots de
#: l'atelier
ALIGNEMENTS = ("Centre", "Gauche", "Droite")
_ALIGN = {"Centre": "center", "Gauche": "left", "Droite": "right"}

#: police prise quand celle demandée manque
POLICE_DEFAUT = "Arial"

Contour = List[Tuple[float, float]]


def polices() -> List[str]:
    """Les familles installées, triées — celles du poste."""
    return [famille for famille, _chemin in textvec.available_fonts()]


def chemin_police(famille: str) -> str:
    """Le fichier d'une famille; « » si elle manque (fontTools prend
    alors sa police par défaut)."""
    voulue = str(famille or "").strip().lower()
    if not voulue:
        return ""
    for nom, chemin in textvec.available_fonts():
        if nom.lower() == voulue:
            return chemin
    return ""


def contours_du_texte(texte: str, police: str = POLICE_DEFAUT,
                      hauteur: float = 5.0, x: float = 0.0,
                      y: float = 0.0, rotation: float = 0.0,
                      alignement: str = ALIGNEMENTS[0],
                      interligne: float = 1.4) -> List[Contour]:
    """Les contours d'un texte, en coordonnées machine.

    `hauteur` est la hauteur de capitale, en mm; le bloc est posé en
    (x, y) — sa ligne de base sur y, alignée sur x selon
    `alignement` — puis tourné de `rotation` degrés autour de ce
    point. Un texte vide ne donne rien."""
    texte = str(texte or "").replace("\\n", "\n")
    if not texte.strip() or float(hauteur) <= 0:
        return []
    try:
        bruts = textvec.layout(texte, float(hauteur),
                               chemin_police(police),
                               align=_ALIGN.get(alignement, "center"),
                               valign="baseline",
                               line_spacing=float(interligne or 1.4))
    except textvec.FontNotFound:
        return []
    # `layout` centre toujours le bloc sur l'origine (son alignement
    # ne joue qu'entre les lignes): à gauche ou à droite, c'est le
    # bord de l'encre qu'on met sur le point de position
    xs = [px for c in bruts for px, _py in c]
    decalage = 0.0
    if xs and alignement == "Gauche":
        decalage = -min(xs)
    elif xs and alignement == "Droite":
        decalage = -max(xs)
    angle = math.radians(float(rotation or 0.0))
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    sortie: List[Contour] = []
    for contour in bruts:
        points = [(round(x + (px + decalage) * cos_a - py * sin_a, 4),
                   round(y + (px + decalage) * sin_a + py * cos_a, 4))
                  for px, py in contour]
        if len(points) >= 3:
            sortie.append(points)
    return sortie


def contours_depuis_params(params: Dict) -> Optional[List[Contour]]:
    """Les contours que des paramètres de texte décrivent, ou None si
    ces paramètres ne portent pas de texte (l'opération relève alors
    ses contours au canvas, comme les autres)."""
    texte = str(params.get('texte') or "")
    if not texte.strip():
        return None

    def _nombre(cle, defaut):
        try:
            return float(params.get(cle, defaut) or 0.0)
        except (TypeError, ValueError):
            return defaut

    disposition = str(params.get('disposition') or "Ligne droite")
    alignement = str(params.get('alignement') or ALIGNEMENTS[0])
    if disposition.startswith("Arc"):
        # le texte posé à plat, puis courbé sur son cercle
        from src.core import texte_courbe as tc
        a_plat = contours_du_texte(
            texte, str(params.get('police') or POLICE_DEFAUT),
            _nombre('hauteur_capitale', 5.0), 0.0, 0.0, 0.0, alignement,
            _nombre('interligne', 1.4))
        support = tc.support_depuis(
            disposition, _nombre('pos_x', 0.0), _nombre('pos_y', 0.0),
            max(0.1, _nombre('rayon_arc', 20.0)), _nombre('rotation', 0.0))
        cote = {'Gauche': 'gauche', 'Droite': 'droite'}.get(alignement,
                                                             'centre')
        return [[(round(x, 4), round(y, 4)) for x, y in c]
                for c in tc.courber(a_plat, support, cote)]
    return contours_du_texte(
        texte, str(params.get('police') or POLICE_DEFAUT),
        _nombre('hauteur_capitale', 5.0), _nombre('pos_x', 0.0),
        _nombre('pos_y', 0.0), _nombre('rotation', 0.0),
        alignement, _nombre('interligne', 1.4))


def emprise(contours: Sequence[Contour]) -> Optional[Tuple[float, float,
                                                            float, float]]:
    """(x min, y min, x max, y max) des contours, ou None."""
    xs = [p[0] for c in contours for p in c]
    ys = [p[1] for c in contours for p in c]
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))
