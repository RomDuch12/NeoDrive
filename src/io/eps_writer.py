# -*- coding: utf-8 -*-
"""Écriture EPS / AI — du PostScript encapsulé, vectoriel.

Un EPS s'ouvre dans Illustrator, CorelDRAW, Inkscape et tous les
logiciels de découpe. Le `.ai` d'avant la version 9 EST un EPS: le
même contenu, une autre extension. C'est le format d'échange que
demandent les graveurs et les découpeurs qui ne lisent pas le DXF.

Ce module ne connaît que des nombres: des tracés donnés en
millimètres, Y vers le haut, sous la même forme que
`geometry.Chemin.commandes` — ('M', x, y), ('L', x, y),
('C', x1, y1, x2, y2, x3, y3), ('Z',). Rien de Qt n'entre ici, ce
qui le rend vérifiable sans interface.
"""

from datetime import datetime

#: un point PostScript vaut 1/72 de pouce
MM_EN_POINTS = 72.0 / 25.4

#: épaisseur du trait tracé, en millimètres. Un filet: c'est un
#: contour de découpe ou de gravure, pas un trait de dessin.
EPAISSEUR_MM = 0.1


def _nombre(valeur: float) -> str:
    """Un nombre court: PostScript n'a que faire de 14 décimales."""
    texte = f"{float(valeur):.4f}".rstrip('0').rstrip('.')
    return texte or "0"


def _corps(traces) -> tuple:
    """Les commandes PostScript et l'emprise du dessin.

    Rend `(lignes, (xmin, ymin, xmax, ymax))`, ou `(lignes, None)`
    s'il n'y a rien à écrire.
    """
    lignes = []
    xs, ys = [], []
    couleur_posee = None
    for commandes, couleur in traces:
        if not commandes:
            continue
        if couleur != couleur_posee:
            r, v, b = couleur
            lignes.append(
                f"{_nombre(r)} {_nombre(v)} {_nombre(b)} setrgbcolor")
            couleur_posee = couleur
        for commande in commandes:
            nom = commande[0]
            coords = [float(c) for c in commande[1:]]
            xs.extend(coords[0::2])
            ys.extend(coords[1::2])
            nombres = " ".join(_nombre(c) for c in coords)
            if nom == 'M':
                lignes.append(f"{nombres} m")
            elif nom == 'L':
                lignes.append(f"{nombres} l")
            elif nom == 'C':
                lignes.append(f"{nombres} c")
            elif nom == 'Z':
                lignes.append("z")
        lignes.append("s")
    if not xs:
        return lignes, None
    return lignes, (min(xs), min(ys), max(xs), max(ys))


def ecrire(chemin_fichier: str, traces, titre: str = "",
           epaisseur_mm: float = EPAISSEUR_MM,
           marge_mm: float = 1.0) -> tuple:
    """Écrit un EPS. Rend l'emprise (largeur, hauteur) en mm.

    `traces`: une suite de `(commandes, (r, v, b))`, chaque couleur
    étant donnée entre 0 et 1.
    """
    lignes, boite = _corps(traces)
    if boite is None:
        raise ValueError("Rien à exporter: aucun tracé.")
    xmin, ymin, xmax, ymax = boite
    largeur = max(1e-6, xmax - xmin) + 2 * marge_mm
    hauteur = max(1e-6, ymax - ymin) + 2 * marge_mm

    entete = [
        "%!PS-Adobe-3.0 EPSF-3.0",
        "%%Creator: NeoDrive",
        f"%%Title: {titre or 'Dessin NeoDrive'}",
        "%%CreationDate: " + datetime.now().strftime("%Y-%m-%d %H:%M"),
        "%%DocumentData: Clean7Bit",
        "%%LanguageLevel: 2",
        "%%BoundingBox: 0 0 "
        f"{int(largeur * MM_EN_POINTS + 0.999)} "
        f"{int(hauteur * MM_EN_POINTS + 0.999)}",
        "%%HiResBoundingBox: 0 0 "
        f"{_nombre(largeur * MM_EN_POINTS)} "
        f"{_nombre(hauteur * MM_EN_POINTS)}",
        "%%EndComments",
        "%%BeginProlog",
        "/m { moveto } bind def",
        "/l { lineto } bind def",
        "/c { curveto } bind def",
        "/z { closepath } bind def",
        "/s { stroke } bind def",
        "%%EndProlog",
        "gsave",
        # Le dessin s'écrit en MILLIMÈTRES: une seule mise à
        # l'échelle ici, et plus une conversion dans le corps
        f"{_nombre(MM_EN_POINTS)} {_nombre(MM_EN_POINTS)} scale",
        f"{_nombre(marge_mm - xmin)} {_nombre(marge_mm - ymin)} "
        "translate",
        f"{_nombre(max(0.001, epaisseur_mm))} setlinewidth",
        "1 setlinejoin",
        "1 setlinecap",
    ]
    pied = ["grestore", "showpage", "%%EOF", ""]

    with open(chemin_fichier, 'w', encoding='ascii',
              errors='replace', newline='\n') as sortie:
        sortie.write("\n".join(entete + lignes + pied))
    return largeur, hauteur
