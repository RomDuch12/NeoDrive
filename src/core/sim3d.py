"""Parcours 3D d'une séquence Datron ($$$), pour la simulation.

La prévisualisation 2D du canvas ne garde que le plan XY: elle jette
le Z de chaque segment, ignore les plongées et trace les arcs en
cordes. Ici on garde tout ce qu'il faut pour voir le parcours en
volume: X, Y ET Z à chaque sommet, les plongées, et les arcs
interpolés.

Format des arcs (relevé sur les fichiers Datron de l'atelier):

    Arc CW|CCW X=<fin x> Y=<fin y> dX=<cx - x départ> dY=<cy - y départ>

(X, Y) est le point d'ARRIVÉE ; le CENTRE est le point de départ plus
(dX, dY). Coordonnées MODALES: un axe absent garde sa valeur. Un arc
dont le départ et l'arrivée se confondent est un cercle complet.

Le parcours rendu est UNE polyligne continue (l'outil ne saute pas):
des sommets, et pour chacun le genre du mouvement qui y mène.
"""

import math
import re
from typing import Dict, List

#: genre du mouvement qui mène à un sommet
DEPART, COUPE, AIR, RAPIDE = 0, 1, 2, 3

_MOVE_RE = re.compile(r'^(Line|Rapid|PrePositioning|Arc\s+(CW|CCW))\b(.*)$')
_COORD_RE = re.compile(
    r'\b(dX|dY|X|Y|Z)\s*=\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)')

#: au-delà, un arc n'est plus découpé (cordes): garde la vue fluide
_MAX_POINTS_ARC = 64
#: angle maxi d'une corde d'arc
_PAS_ANGLE_MAX = math.radians(15.0)
EPS = 1e-9


def _lignes_de_sequence(code: str, sequence: str) -> List[str]:
    """Les lignes du bloc $$$ visé (le premier s'il n'est pas nommé,
    tout le code s'il n'y a aucun bloc)."""
    lignes = code.split('\n')
    if '$$$' not in code:
        return lignes
    debut = fin = None
    bloc_vu = False
    for i, ln in enumerate(lignes):
        if '$$$' not in ln:
            continue
        s = ln.strip()
        if not s.startswith('$$$'):
            continue
        bloc_vu = True
        nom = s[3:].strip()
        if debut is not None:
            fin = i
            break
        if not sequence or nom == sequence:
            debut = i + 1
    if debut is None:
        return [] if bloc_vu else lignes
    return lignes[debut:fin]


def _points_arc(x0, y0, z0, x1, y1, z1, cx, cy, horaire: bool,
                tolerance: float) -> List[tuple]:
    """Les points d'un arc (départ exclu, arrivée incluse)."""
    r = math.hypot(x0 - cx, y0 - cy)
    if r < EPS:
        return [(x1, y1, z1)]
    a0 = math.atan2(y0 - cy, x0 - cx)
    a1 = math.atan2(y1 - cy, x1 - cx)
    balayage = a1 - a0
    if horaire:
        if balayage >= -EPS:
            balayage -= 2.0 * math.pi
    else:
        if balayage <= EPS:
            balayage += 2.0 * math.pi
    # pas d'angle tel que la flèche d'une corde reste sous la tolérance
    if r > tolerance:
        pas = 2.0 * math.acos(max(-1.0, min(1.0, 1.0 - tolerance / r)))
        pas = min(pas, _PAS_ANGLE_MAX)
    else:
        pas = _PAS_ANGLE_MAX
    n = int(math.ceil(abs(balayage) / max(pas, 1e-6)))
    n = max(1, min(_MAX_POINTS_ARC, n))
    points = []
    for i in range(1, n + 1):
        t = i / n
        a = a0 + balayage * t
        points.append((cx + r * math.cos(a), cy + r * math.sin(a),
                       z0 + (z1 - z0) * t))
    # l'arrivée exacte, pas celle que le cosinus arrondit
    points[-1] = (x1, y1, z1)
    return points


def parcours_3d(code: str, sequence: str = "", max_sommets: int = 60000,
                tolerance: float = 0.01, progression=None) -> Dict:
    """Le parcours d'une séquence, en 3D.

    Rend {'x','y','z': [float], 'k': [genre], 'n_moves', 'n_arcs',
    'pas', 'longueur_coupe', 'bornes', 'bornes_coupe'}.

    Au-delà de `max_sommets` mouvements, on ne garde qu'un mouvement
    sur `pas` (et toujours ceux où le genre change): l'aperçu garde la
    forme d'un gros profil 3D sans faire ramer la vue. Les arcs sont
    alors tracés en cordes — à cette échelle, on ne les distingue
    plus."""
    from src.core import vcarve
    lignes = _lignes_de_sequence(code or "", sequence or "")
    # reconnues une fois: compter, puis relire pour lire, faisait le travail
    # deux fois
    mouvements = [m for m in map(_MOVE_RE.match, map(str.strip, lignes)) if m]
    n_moves = len(mouvements)
    pas = 1 if n_moves <= max_sommets else \
        int(math.ceil(n_moves / float(max_sommets)))
    interpoler = pas == 1

    xs: List[float] = []
    ys: List[float] = []
    zs: List[float] = []
    ks: List[int] = []
    x = y = z = None
    rang = 0
    n_arcs = 0
    longueur = 0.0
    budget = max_sommets * 3          # sommets d'arcs compris

    def _poser(px, py, pz, genre):
        xs.append(px)
        ys.append(py)
        zs.append(pz)
        ks.append(genre)

    for i, m in enumerate(mouvements):
        if progression is not None and i % 4000 == 0:
            vcarve.avancer(progression, i / max(1, n_moves),
                           "lecture du parcours")
        commande, sens, reste = m.groups()
        coords = dict(_COORD_RE.findall(reste))
        nx = float(coords['X']) if 'X' in coords else x
        ny = float(coords['Y']) if 'Y' in coords else y
        nz = float(coords['Z']) if 'Z' in coords else z
        depart_connu = None not in (x, y, z)
        arrivee_connue = None not in (nx, ny, nz)
        est_arc = sens is not None

        if commande in ('Rapid', 'PrePositioning'):
            genre = RAPIDE
        elif ((z is not None and z <= 0.0)
              or (nz is not None and nz <= 0.0)):
            genre = COUPE
        else:
            genre = AIR

        if not depart_connu:
            # tant que la position n'est pas entièrement connue, on ne
            # trace rien: le premier sommet est le vrai départ
            x, y, z = nx, ny, nz
            if arrivee_connue and not xs:
                _poser(x, y, z, DEPART)
            continue
        if not arrivee_connue:
            continue

        rang += 1
        garder = (pas == 1 or rang % pas == 0
                  or (ks and ks[-1] != genre))
        if est_arc:
            n_arcs += 1
            cx = x + float(coords.get('dX', 0.0))
            cy = y + float(coords.get('dY', 0.0))
            r = math.hypot(x - cx, y - cy)
            if genre == COUPE:
                a0 = math.atan2(y - cy, x - cx)
                a1 = math.atan2(ny - cy, nx - cx)
                b = a1 - a0
                if sens == 'CW':
                    b = b - 2.0 * math.pi if b >= -EPS else b
                else:
                    b = b + 2.0 * math.pi if b <= EPS else b
                longueur += math.hypot(r * abs(b), nz - z)
            if interpoler and len(xs) < budget:
                for px, py, pz in _points_arc(x, y, z, nx, ny, nz,
                                              cx, cy, sens == 'CW',
                                              tolerance):
                    _poser(px, py, pz, genre)
            elif garder:
                _poser(nx, ny, nz, genre)
        else:
            if genre == COUPE:
                longueur += math.dist((x, y, z), (nx, ny, nz))
            if garder:
                _poser(nx, ny, nz, genre)
        x, y, z = nx, ny, nz

    # le dernier sommet est toujours la vraie fin du parcours
    if xs and None not in (x, y, z) and (
            xs[-1], ys[-1], zs[-1]) != (x, y, z):
        _poser(x, y, z, ks[-1] if ks else DEPART)

    if xs:
        bornes = (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))
        zc = [zz for zz, kk in zip(zs, ks) if kk == COUPE]
        bornes_coupe = (min(zc), max(zc)) if zc else None
    else:
        bornes = None
        bornes_coupe = None
    vcarve.avancer(progression, 1.0, "parcours lu")
    return {'x': xs, 'y': ys, 'z': zs, 'k': ks,
            'n_moves': n_moves, 'n_arcs': n_arcs, 'pas': pas,
            'longueur_coupe': longueur,
            'bornes': bornes, 'bornes_coupe': bornes_coupe}


# ───────────────────────── le temps machine ─────────────────────────

#: la vitesse des rapides quand la machine ne la dit pas (mm/min)
RAPIDE_MM_MIN = 20000.0
#: les avances d'un outil que la bibliothèque ne connaît pas (mm/min)
AVANCES_DEFAUT = {'finishing': 1000.0, 'plunge': 300.0, 'approach': 2000.0}
#: une coupe qui descend plus qu'elle n'avance est une plongée
PENTE_PLONGEE = 0.7
#: un changement d'outil (secondes): rangement, prise, mesure — sur 999
#: programmes exécutés, l'écart à l'estimation de la machine passe de
#: 11,8 % à 9,1 % (tools/temps_reels.py)
CHANGEMENT_OUTIL_S = 15.0


def codes_outils(outils) -> "np.ndarray":
    """Un entier par sommet: le rang de son outil dans l'ordre où les
    outils apparaissent (comparer des entiers, pas des chaînes)."""
    import numpy as np
    n = len(outils)
    if not n:
        return np.zeros(0, dtype=np.intp)
    # l'outil change rarement: un rang par tronçon, répété (une boucle
    # Python par sommet coûtait 0,1 s sur 300 000)
    tab = np.empty(n, dtype=object)
    tab[:] = list(outils)
    debuts = np.concatenate(([0], np.flatnonzero(tab[1:] != tab[:-1]) + 1))
    rangs = {}
    valeurs = [rangs.setdefault(tab[i], len(rangs)) for i in debuts.tolist()]
    return np.repeat(np.asarray(valeurs, dtype=np.intp),
                     np.diff(np.concatenate((debuts, [n]))))


def temps_parcours(res: Dict, avances=None,
                   rapide: float = RAPIDE_MM_MIN,
                   changement_outil: float = CHANGEMENT_OUTIL_S):
    """Le temps machine (secondes) cumulé à chaque sommet d'un parcours
    simulé: chaque segment à l'avance de son outil — `avances(outil)`
    rend {'finishing', 'plunge', 'approach'} en mm/min (celles de
    tools.json) —, la coupe à l'avance de finition, la plongée à celle
    de plongée, le déplacement dans l'air à l'approche, les rapides à
    `rapide`, et `changement_outil` secondes à chaque outil qui en
    remplace un autre (le premier est déjà dans la broche). Rend un
    tableau numpy (0 au premier sommet)."""
    import numpy as np
    x = np.asarray(res.get('x') or [], dtype=float)
    n = len(x)
    if n == 0:
        return np.zeros(0)
    y = np.asarray(res['y'], dtype=float)
    z = np.asarray(res['z'], dtype=float)
    k = np.asarray(res['k'], dtype=int)
    outils = list(res.get('outil') or [''] * n)
    if len(outils) < n:
        outils += [''] * (n - len(outils))
    d = np.zeros(n)
    d[1:] = np.sqrt(np.diff(x) ** 2 + np.diff(y) ** 2 + np.diff(z) ** 2)
    dz = np.zeros(n)
    dz[1:] = np.diff(z)
    # les avances de chaque outil, une fois chacun, puis réparties sur
    # les sommets d'un coup (une boucle par sommet: 0,2 s sur 300 000)
    outils = outils[:n]
    codes = codes_outils(outils)
    table = []
    for art in dict.fromkeys(outils):
        av = dict(AVANCES_DEFAUT)
        if avances is not None:
            try:
                lu = avances(art) or {}
            except Exception:
                lu = {}
            for cle in av:
                try:
                    if float(lu.get(cle) or 0) > 0:
                        av[cle] = float(lu[cle])
                except (TypeError, ValueError):
                    pass
        table.append((av['finishing'], av['plunge'], av['approach']))
    table = np.array(table, dtype=float).reshape(-1, 3)
    fin, plo, app = table[codes, 0], table[codes, 1], table[codes, 2]
    plongee = (k == COUPE) & (dz < 0) & (-dz > PENTE_PLONGEE * d)
    f = np.where((k == RAPIDE) | (k == DEPART), float(rapide),
                 np.where(k == AIR, app, np.where(plongee, plo, fin)))
    # l'avance que le programme a fixée (SetFeedTechnology, Feed) prime
    # sur tools.json: la machine déroule chaque Line à l'avance active,
    # dans la matière comme au-dessus
    programmee = res.get('avance')
    if programmee is not None and len(programmee):
        av = np.zeros(n)
        m = min(n, len(programmee))
        av[:m] = np.asarray(programmee[:m], dtype=float)
        f = np.where((av > 0) & ((k == COUPE) | (k == AIR)), av, f)
    f = np.maximum(f, 1.0)
    dt = d / (f / 60.0)
    if changement_outil > 0:
        # un sommet sans outil ne sépare pas deux tronçons du même outil
        nomme = np.array([bool(a) for a in dict.fromkeys(outils)])
        nommes = np.flatnonzero(nomme[codes])
        if len(nommes) > 1:
            c = codes[nommes]
            dt[nommes[1:][c[1:] != c[:-1]]] += float(changement_outil)
    return np.cumsum(dt)


def duree_lisible(secondes: float) -> str:
    """« 12 min 05 s », « 1 h 02 min », « 8,4 s »."""
    s = max(0.0, float(secondes))
    if s < 60:
        return f"{s:.1f} s".replace(".", ",")
    m, s = divmod(int(round(s)), 60)
    if m < 60:
        return f"{m} min {s:02d} s"
    h, m = divmod(m, 60)
    return f"{h} h {m:02d} min"
