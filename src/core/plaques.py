"""Les plaques de reprise: des plaques percées de motifs de trous
(Ø 4,05 pour des vis M4) sur lesquelles on visse une pièce par son dos,
pour l'usiner d'une seule prise — dessus et flancs.

Chaque plaque est un fichier JSON du dossier « Plaques de reprise » à
côté de l'exe (la dist le copie; celles qu'on y pose restent les
siennes). On les crée, les règle et les importe d'un DXF dans l'éditeur
(src/gui/dialogs/plaques_dialog.py):

    {"nom": "Plaque M4 200x150", "largeur": 200, "hauteur": 150,
     "contour": [[x, y], ...],          (facultatif: un polygone)
     "epaisseur": 15, "diametre_trou": 4.05, "filetage": "M4",
     "trous": [[x, y], ...], "zero": "coin avant gauche", "notes": ""}

Les cotes sont dans le repère de la PLAQUE: son origine est son zéro
(un coin, une goupille — `zero` le dit à l'opérateur).
"""

import math
import os
import re
from typing import Dict, List, Optional, Sequence, Tuple

#: le dossier, à côté de l'exe
DOSSIER = "Plaques de reprise"
#: Ø des trous de passage d'une vis M4
DIAMETRE_M4 = 4.05


def dossier() -> str:
    """Le dossier des plaques — à côté des réglages de test quand
    NEODRIVE_APP_SETTINGS les détourne (les tests n'écrivent jamais
    dans celui de l'atelier)."""
    detour = os.environ.get('NEODRIVE_PLAQUES_DIR')
    if detour:
        return detour
    reglages = os.environ.get('NEODRIVE_APP_SETTINGS')
    if reglages:
        return os.path.join(os.path.dirname(reglages), DOSSIER)
    from src.core.tool_library import get_base_dir
    return os.path.join(get_base_dir(), DOSSIER)


def nouvelle(nom: str = "Nouvelle plaque", largeur: float = 200.0,
             hauteur: float = 150.0) -> Dict:
    return {'nom': nom, 'largeur': float(largeur),
            'hauteur': float(hauteur), 'contour': [], 'epaisseur': 15.0,
            'diametre_trou': DIAMETRE_M4, 'filetage': "M4", 'trous': [],
            'zero': "coin avant gauche", 'notes': ""}


def normaliser(d) -> Optional[Dict]:
    """Une plaque lue (tolérante: ce qui manque prend son défaut), ou
    None si ce n'est pas une plaque."""
    if not isinstance(d, dict):
        return None
    p = nouvelle(str(d.get('nom') or "Plaque"))
    for cle in ('largeur', 'hauteur', 'epaisseur', 'diametre_trou'):
        try:
            p[cle] = float(d.get(cle, p[cle]))
        except (TypeError, ValueError):
            pass
    for cle in ('filetage', 'zero', 'notes'):
        if d.get(cle) is not None:
            p[cle] = str(d[cle])
    trous = []
    for t in d.get('trous') or []:
        try:
            trous.append([round(float(t[0]), 4), round(float(t[1]), 4)])
        except (TypeError, ValueError, IndexError):
            continue
    p['trous'] = trous
    contour = []
    for q in d.get('contour') or []:
        try:
            contour.append([round(float(q[0]), 4), round(float(q[1]), 4)])
        except (TypeError, ValueError, IndexError):
            continue
    p['contour'] = contour if len(contour) >= 3 else []
    if p['contour']:
        xs = [q[0] for q in p['contour']]
        ys = [q[1] for q in p['contour']]
        p['largeur'] = round(max(xs) - min(xs), 4)
        p['hauteur'] = round(max(ys) - min(ys), 4)
    return p


def contour(plaque: Dict) -> List[Tuple[float, float]]:
    """Le contour de la plaque (le rectangle largeur × hauteur depuis
    l'origine, s'il n'a pas été dessiné)."""
    if plaque.get('contour'):
        return [tuple(q) for q in plaque['contour']]
    L, H = float(plaque['largeur']), float(plaque['hauteur'])
    return [(0.0, 0.0), (L, 0.0), (L, H), (0.0, H)]


def _nom_de_fichier(nom: str) -> str:
    sur = re.sub(r'[^A-Za-z0-9 _.-]+', '_', nom).strip(" ._") or "plaque"
    return sur[:80] + ".json"


def lister() -> List[Tuple[str, str]]:
    """[(nom, chemin)] des plaques du dossier, par nom."""
    d = dossier()
    if not os.path.isdir(d):
        return []
    sortie = []
    for f in sorted(os.listdir(d)):
        if not f.lower().endswith('.json'):
            continue
        p = charger(os.path.join(d, f))
        if p is not None:
            sortie.append((p['nom'], os.path.join(d, f)))
    return sorted(sortie, key=lambda c: c[0].lower())


def charger(chemin: str) -> Optional[Dict]:
    from src.core.fichiers_surs import lire_json
    return normaliser(lire_json(chemin))


def par_nom(nom: str) -> Optional[Dict]:
    for n, chemin in lister():
        if n == nom:
            return charger(chemin)
    return None


def enregistrer(plaque: Dict, chemin: str = None) -> str:
    """Écrit la plaque (sûr: jamais à moitié); rend son chemin."""
    from src.core.fichiers_surs import ecrire_json_sur
    p = normaliser(plaque)
    if chemin is None:
        chemin = os.path.join(dossier(), _nom_de_fichier(p['nom']))
    ecrire_json_sur(chemin, p, garder_bak=True, indent=2,
                    ensure_ascii=False)
    return chemin


def supprimer(chemin: str) -> bool:
    try:
        os.remove(chemin)
        return True
    except OSError:
        return False


def motif(nx: int, ny: int, pas_x: float, pas_y: float,
          x0: float = 0.0, y0: float = 0.0) -> List[List[float]]:
    """Une grille de trous: nx × ny, au pas, depuis (x0, y0)."""
    return [[round(x0 + i * pas_x, 4), round(y0 + j * pas_y, 4)]
            for j in range(max(0, int(ny))) for i in range(max(0, int(nx)))]


def sans_doublons(trous: Sequence, tol: float = 0.01) -> List[List[float]]:
    sortie = []
    for x, y in trous:
        if not any(abs(x - a) <= tol and abs(y - b) <= tol
                   for a, b in sortie):
            sortie.append([round(float(x), 4), round(float(y), 4)])
    return sortie


def depuis_dxf(chemin: str, d_min: float = 3.5, d_max: float = 4.6,
               nom: str = None) -> Dict:
    """Une plaque lue d'un DXF: ses CERCLES de Ø d_min..d_max sont les
    trous; la plus grande polyligne fermée (sinon l'emprise du dessin)
    est son contour. L'origine reste celle du DXF."""
    import ezdxf
    doc = ezdxf.readfile(chemin)
    msp = doc.modelspace()
    trous, diametres = [], []
    xs, ys = [], []
    for c in msp.query('CIRCLE'):
        cx, cy = float(c.dxf.center[0]), float(c.dxf.center[1])
        d = 2.0 * float(c.dxf.radius)
        xs += [cx - d / 2, cx + d / 2]
        ys += [cy - d / 2, cy + d / 2]
        if d_min - 1e-9 <= d <= d_max + 1e-9:
            trous.append([cx, cy])
            diametres.append(d)
    meilleur, aire = [], 0.0
    for e in msp.query('LWPOLYLINE POLYLINE'):
        try:
            pts = [(float(p[0]), float(p[1])) for p in e.get_points()] \
                if e.dxftype() == 'LWPOLYLINE' else \
                [(float(v.dxf.location[0]), float(v.dxf.location[1]))
                 for v in e.vertices]
        except Exception:
            continue
        if len(pts) < 3:
            continue
        xs += [p[0] for p in pts]
        ys += [p[1] for p in pts]
        ferme = getattr(e, 'closed', False) or getattr(e, 'is_closed',
                                                       False) or \
            math.dist(pts[0], pts[-1]) < 1e-6
        if not ferme:
            continue
        a = 0.5 * abs(sum(pts[k][0] * pts[(k + 1) % len(pts)][1]
                          - pts[(k + 1) % len(pts)][0] * pts[k][1]
                          for k in range(len(pts))))
        if a > aire:
            meilleur, aire = pts, a
    for e in msp.query('LINE'):
        xs += [float(e.dxf.start[0]), float(e.dxf.end[0])]
        ys += [float(e.dxf.start[1]), float(e.dxf.end[1])]
    p = nouvelle(nom or os.path.splitext(os.path.basename(chemin))[0])
    p['trous'] = sans_doublons(trous)
    if diametres:
        p['diametre_trou'] = round(sorted(diametres)[len(diametres) // 2],
                                   3)
    if meilleur:
        p['contour'] = [[round(x, 4), round(y, 4)] for x, y in meilleur]
    elif xs:
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        p['contour'] = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    return normaliser(p)
