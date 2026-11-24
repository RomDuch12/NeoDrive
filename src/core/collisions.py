"""Les collisions de la broche et du porte-outil pendant le parcours.

Au-dessus de chaque outil, la broche est une pile de cylindres — l'écrou
de pince, le nez, le corps (src/core/machine.pile_broche) — dont le bas
est à la pointe de l'outil + son dépassement (sa longueur hors de la
pince). Tout le long du parcours simulé (coupes ET déplacements
rapides: ses sommets, et des points intermédiaires sur ses segments — une
longue ligne droite passait « à travers » une bride sans rien dire),
chaque cylindre est comparé:

- aux obstacles FIXES (l'étau ou le mandrin, la table, la pièce STEP):
  leur carte de hauteurs (le dessus vu d'en haut) dilatée au rayon du
  cylindre dit, en une lecture, la plus haute matière sous lui;
- à la MATIÈRE du brut telle qu'elle est À CE MOMENT (enlevement.Brut
  appliqué au fil du parcours): un écrou qui descend dans une poche
  étroite touche ses parois.

Un contact au-delà de la tolérance est une collision; les sommets
consécutifs d'un même contact font UN événement (le premier sommet, la
pénétration la plus forte).
"""

import math
import time
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

#: en dessous (mm), un effleurement n'est pas une collision
TOLERANCE = 0.05
#: les sommets traités d'un coup pour la matière
PAQUET = 1500
#: au plus ce nombre de points vérifiés le long du parcours (au-delà, le
#: pas entre deux points s'allonge)
POINTS_MAX = 2_000_000


def _grille(xs, ys, marge: float, pas: float = None):
    from src.core.usinage3d import Grille
    x0, x1 = float(np.min(xs)) - marge, float(np.max(xs)) + marge
    y0, y1 = float(np.min(ys)) - marge, float(np.max(ys)) + marge
    if pas is None:
        pas = max(0.5, math.sqrt((x1 - x0) * (y1 - y0) / 250000.0))
    return Grille(x0, x1, y0, y1, pas=pas)


def _points_du_parcours(xs, ys, zs, pas: float):
    """Le parcours point par point: ses sommets, et sur chaque segment
    plus long que `pas` (en XY) des points intermédiaires espacés d'au
    plus `pas`. Rend (x, y, z, sommet): `sommet` est celui où le segment
    ARRIVE (son outil, son dépassement); les points sont dans l'ordre du
    parcours, le dernier de chaque segment est son sommet."""
    n = len(xs)
    longueur = np.hypot(np.diff(xs), np.diff(ys))
    pas = max(float(pas), 1e-6)
    morceaux = np.maximum(1, np.ceil(longueur / pas - 1e-9)).astype(np.int64)
    total = int(morceaux.sum())
    if total > POINTS_MAX:
        pas *= total / POINTS_MAX
        morceaux = np.maximum(1, np.ceil(longueur / pas - 1e-9)
                              ).astype(np.int64)
        total = int(morceaux.sum())
    segment = np.repeat(np.arange(n - 1), morceaux)
    rang = np.arange(total) - np.repeat(np.cumsum(morceaux) - morceaux,
                                        morceaux) + 1
    f = rang / morceaux[segment]
    x = xs[segment] + f * (xs[segment + 1] - xs[segment])
    y = ys[segment] + f * (ys[segment + 1] - ys[segment])
    z = zs[segment] + f * (zs[segment + 1] - zs[segment])
    # (le sommet d'arrivée, exactement)
    bout = rang == morceaux[segment]
    x[bout], y[bout], z[bout] = (xs[segment[bout] + 1], ys[segment[bout] + 1],
                                 zs[segment[bout] + 1])
    return (np.concatenate([xs[:1], x]), np.concatenate([ys[:1], y]),
            np.concatenate([zs[:1], z]),
            np.concatenate([[0], segment + 1]))


def _disque(rayon_cases: float) -> Tuple[np.ndarray, np.ndarray]:
    r = int(math.ceil(rayon_cases))
    dj, di = np.mgrid[-r:r + 1, -r:r + 1]
    garde = dj * dj + di * di <= rayon_cases * rayon_cases + 1e-9
    return dj[garde], di[garde]


def verifier(res: Dict, depassements: Dict[str, float], machine: Dict,
             obstacles: Sequence[Tuple[str, np.ndarray]] = (),
             brut=None, formes: Dict = None, depassement_defaut: float = 20.0,
             progression: Callable = None) -> Dict:
    """Les collisions du parcours `res` (sim_cycles.simuler):
    {'evenements': [{'debut', 'fin', 'x', 'y', 'z', 'composant',
    'obstacle', 'penetration', 'outil'}], 'sommets', 'duree'}.

    `depassements`: la longueur hors pince de chaque outil (référence →
    mm); `obstacles`: [(nom, triangles)] fixes; `brut` (enlevement.Brut,
    intact) et `formes`: la matière, enlevée au fil du parcours."""
    from src.core import machine as mc
    from src.core.usinage3d import carte_piece, dilater_disque
    from src.core.vcarve import avancer
    debut_t = time.time()
    xs = np.asarray(res.get('x') or [], dtype=float)
    ys = np.asarray(res.get('y') or [], dtype=float)
    zs = np.asarray(res.get('z') or [], dtype=float)
    n = len(xs)
    sortie = {'evenements': [], 'sommets': n, 'duree': 0.0}
    if n < 2:
        return sortie
    outils = list(res.get('outil') or [''] * n)
    dep = np.array([float(depassements.get(o, depassement_defaut))
                    for o in outils])
    pile = mc.pile_broche(machine)
    r_max = max(r for _n, r, _a, _b in pile)
    # entre deux points vérifiés, moins d'un quart du plus petit rayon:
    # aucun cylindre n'enjambe un obstacle
    r_min = min(r for _n, r, _a, _b in pile)
    # (sommet, composant, obstacle, pénétration, x, y, z)
    contacts = []

    # 1. les obstacles fixes: une carte par obstacle, dilatée par rayon
    fixes = [(nom, np.asarray(t, dtype=float)) for nom, t in obstacles
             if t is not None and len(t)]
    if fixes:
        g = _grille(xs, ys, r_max + 5.0)
        px, py, pz, ps = _points_du_parcours(xs, ys, zs,
                                             max(g.pas, r_min / 4.0))
        j, i = g.indices(px, py)
        avancer(progression, 0.0, "obstacles fixes")
        for k, (nom, T) in enumerate(fixes):
            H = carte_piece(T, g, -1e9)
            cache = {}
            for composant, r, z0, _z1 in pile:
                D = dilater_disque(H, r / g.pas, cache)
                bas = pz + dep[ps] + z0
                pen = D[j, i] - bas
                for q in np.nonzero(pen > TOLERANCE)[0]:
                    contacts.append((int(ps[q]), composant, nom,
                                     float(pen[q]), float(px[q]),
                                     float(py[q]), float(pz[q])))
            avancer(progression, 0.3 * (k + 1) / len(fixes),
                    f"obstacles fixes ({nom})")

    # 2. la matière, telle qu'elle est quand l'outil passe
    if brut is not None:
        b = brut.copie()
        b.remettre()
        pas = b.pas
        disques = {r: _disque(r / pas) for _c, r, _a, _b in pile}
        px, py, pz, ps = _points_du_parcours(xs, ys, zs,
                                             max(pas, r_min / 4.0))
        for depart in range(1, n, PAQUET):
            fin = min(n, depart + PAQUET)
            avancer(progression, 0.3 + 0.7 * depart / n,
                    f"matière: sommet {depart}/{n}")
            # les points des segments qui arrivent aux sommets du paquet,
            # par tranches (la mémoire reste bornée)
            a_pt = int(np.searchsorted(ps, depart, side='left'))
            b_pt = int(np.searchsorted(ps, fin, side='left'))
            for a in range(a_pt, b_pt, PAQUET):
                tranche = slice(a, min(b_pt, a + PAQUET))
                tx, ty, tz, ts = (px[tranche], py[tranche], pz[tranche],
                                  ps[tranche])
                for composant, r, z0, _z1 in pile:
                    bas = tz + dep[ts] + z0
                    # seuls les points où ce cylindre descend sous le
                    # dessus du brut peuvent toucher la matière
                    dedans = np.nonzero(bas < b.z_haut - TOLERANCE)[0]
                    if not len(dedans):
                        continue
                    dj, di = disques[r]
                    ii = ((tx[dedans] - b.x0) / pas).astype(int)
                    jj = ((ty[dedans] - b.y0) / pas).astype(int)
                    J = jj[:, None] + dj[None, :]
                    I = ii[:, None] + di[None, :]
                    hors = (J < 0) | (J >= b.ny) | (I < 0) | (I >= b.nx)
                    Hm = np.where(hors, -1e9,
                                  b.h[np.clip(J, 0, b.ny - 1),
                                      np.clip(I, 0, b.nx - 1)])
                    pen = Hm.max(axis=1) - bas[dedans]
                    for k in np.nonzero(pen > TOLERANCE)[0]:
                        q = int(dedans[k])
                        contacts.append((int(ts[q]), composant,
                                         "matière du brut", float(pen[k]),
                                         float(tx[q]), float(ty[q]),
                                         float(tz[q])))
            b.appliquer(res, formes or {}, fin)
    avancer(progression, 1.0, "fini")

    # 3. les événements: un contact continu = un événement
    contacts.sort(key=lambda c: (c[1], c[2], c[0]))
    for c in contacts:
        idx, composant, obstacle, pen, cx, cy, cz = c
        dernier = sortie['evenements'][-1] if sortie['evenements'] else None
        if (dernier is not None and dernier['composant'] == composant
                and dernier['obstacle'] == obstacle
                and idx <= dernier['fin'] + 1):
            dernier['fin'] = idx
            if pen > dernier['penetration']:
                dernier['penetration'] = pen
            continue
        # (où la broche touche: un sommet, ou un point de son segment)
        sortie['evenements'].append({
            'debut': idx, 'fin': idx, 'x': cx, 'y': cy, 'z': cz,
            'composant': composant, 'obstacle': obstacle,
            'penetration': pen, 'outil': outils[idx]})
    sortie['evenements'].sort(key=lambda e: e['debut'])
    sortie['duree'] = time.time() - debut_t
    return sortie


def resume(rapport: Dict) -> str:
    """« ⚠ 2 collisions: écrou de pince contre l'étau (X… Y… Z…) … »."""
    ev = rapport.get('evenements') or []
    if not ev:
        return (f"Aucune collision de la broche ni du porte-outil "
                f"({rapport.get('sommets', 0)} sommets vérifiés)")
    lignes = [f"⚠ {len(ev)} collision(s) de la broche ou du porte-outil:"]
    for e in ev[:6]:
        lignes.append(f"  {e['composant']} contre {e['obstacle']} — "
                      f"X {e['x']:.2f} Y {e['y']:.2f} Z {e['z']:.2f}, "
                      f"{e['penetration']:.2f} mm"
                      + (f" [{e['outil']}]" if e.get('outil') else ""))
    if len(ev) > 6:
        lignes.append(f"  … et {len(ev) - 6} autre(s)")
    return "\n".join(lignes)
