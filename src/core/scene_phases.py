"""La scène 3D d'une phase de bridage: ce que l'opérateur verra sur la
machine.

Dans le repère de la phase (zéro Z sur le dessus du brut tel qu'il est
posé): la pièce orientée comme bridée, le brut (en arêtes) ou la
matière qui reste après la phase (calculée), ce qui la tient — les mors
de l'étau, le cadre et les ponts du squelette, la plaque de reprise, ses
trous et ses vis — et les parcours de ses séquences.

Données seulement (numpy): la fenêtre « Usinage 3D » et le Canva 3D
les montrent (src/gui/canvas3d.VueScene).
"""

from typing import Dict, List, Optional

import numpy as np

#: couleurs (0–1)
PIECE = (0.72, 0.76, 0.84)
MORS = (0.42, 0.44, 0.53)
PLAQUE = (0.30, 0.31, 0.38)
VIS = (0.98, 0.89, 0.69)
CADRE = (0.80, 0.65, 0.95)
INACCESSIBLE = (0.95, 0.35, 0.42)
#: traits (hex)
BRUT = "#fab387"
TROU = "#9399b2"
TROU_VIS = "#f9e2af"
PARCOURS = ("#89b4fa", "#a6e3a1", "#f5c2e7", "#f9e2af", "#94e2d5")


def _arêtes_boite(x0, y0, z0, x1, y1, z1) -> List[np.ndarray]:
    bas = np.array([(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
                    (x0, y0, z0)])
    haut = bas.copy()
    haut[:, 2] = z1
    sortie = [bas, haut]
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        sortie.append(np.array([(x, y, z0), (x, y, z1)]))
    return sortie


def _cercle(x, y, z, r, n=20) -> np.ndarray:
    t = np.linspace(0, 2 * np.pi, n + 1)
    return np.column_stack([x + r * np.cos(t), y + r * np.sin(t),
                            np.full(n + 1, z)])


def scene_phase(modele, placement, phase: Dict, brut: Dict, tenue: Dict,
                rang: int = 0, resultat: Optional[Dict] = None,
                avec_parcours: bool = True, faces_rouges=None) -> Dict:
    """{'triangles', 'couleurs', 'aretes', 'calques', 'matiere':
    (triangles, couleurs) ou None, 'texte'} de la phase `phase` (sa
    clé, son rang dans la gamme de phases). Sans `resultat`: le brut
    entier en arêtes (la mise en place); avec: la matière qui reste."""
    from src.core import tenue as tn
    from src.core import usinage3d as u3
    t = tn.regler(tenue)
    cle = phase['cle']
    boite = tn.boite_brut(modele, brut)
    extra = tn.triangles_tenue(modele, brut, t)
    pre = u3.preparer_phase(modele, placement, cle, 1.0, None, boite, extra)
    if resultat is not None and resultat.get('decalage') is not None:
        # le zéro de la phase calculée (une reprise le descend)
        dz = float(resultat['decalage'][2]) - float(pre['decalage'][2])
        if abs(dz) > 1e-9:
            pre = u3.preparer_phase(modele, placement, cle, 1.0, None,
                                    boite, extra, dz=dz)
    R = u3.DIRECTIONS[cle][1]
    dec = np.asarray(pre['decalage'], dtype=float)
    T = np.asarray(modele.triangles, dtype=float) @ R.T - dec
    morceaux = [T]
    couleurs = [np.tile(PIECE, (len(T), 1))]
    face_de = getattr(modele, 'face_de', None)
    if faces_rouges and face_de is not None and len(face_de) == len(T):
        # les faces que ni cette tenue ni 3 axes n'atteignent
        rouge = np.isin(np.asarray(face_de), list(faces_rouges))
        couleurs[0][rouge] = INACCESSIBLE
    if len(extra):
        E = np.asarray(extra, dtype=float) @ R.T - dec
        morceaux.append(E)
        couleurs.append(np.tile(CADRE, (len(E), 1)))
    aretes: List[np.ndarray] = []
    calques: List[Dict] = []
    bx0, by0, bz0, bx1, by1, bz1 = pre['boite']
    px0, py0, pz0, px1, py1, pz1 = pre['piece']
    mode = t['mode']
    serrage = float(t.get('serrage_reprise', 3.0))
    dessous = float(brut.get('dessous', 0.0))
    # ce qui tient la pièce
    if mode == 'plaque' and rang > 0:
        plaque = t.get('plaque') or {}
        vis = (t.get('_vis_placement') or {})
        ep = float(plaque.get('epaisseur', 15.0))
        pos = vis.get('position')
        if plaque and pos is not None:
            from src.core import plaques as pl
            from shapely.geometry import Polygon
            # le centre du brut est en `pos` sur la plaque
            cxb, cyb = (bx0 + bx1) / 2, (by0 + by1) / 2
            ox, oy = cxb - float(pos[0]), cyb - float(pos[1])
            contour = [(x + ox, y + oy) for x, y in pl.contour(plaque)]
            P = tn._prisme(Polygon(contour).buffer(0.0), pz0 - ep, pz0)
            morceaux.append(P)
            couleurs.append(np.tile(PLAQUE, (len(P), 1)))
            pris = {(round(a, 3), round(b, 3)) for a, b in
                    vis.get('trous') or []}
            for hx, hy in plaque.get('trous') or []:
                utile = (round(hx, 3), round(hy, 3)) in pris
                calques.append({'pts': [_cercle(hx + ox, hy + oy, pz0 + 0.01,
                                                float(plaque.get(
                                                    'diametre_trou', 4.05))
                                                / 2)],
                                'couleur': TROU_VIS if utile else TROU,
                                'largeur': 1.6 if utile else 0.8,
                                'genre': 'operation'})
        else:
            P = tn._boite(bx0 - 20, bx1 + 20, by0 - 20, by1 + 20,
                          pz0 - ep, pz0)
            morceaux.append(P)
            couleurs.append(np.tile(PLAQUE, (len(P), 1)))
        for x, y in (t.get('_vis') or []):
            # la vis, du dessous de la plaque dans la pièce (repère de
            # la phase du dessus: celui du dessin)
            xv, yv = float(x) - dec[0], float(y) - dec[1]
            vis_tri = tn._boite(xv - 2, xv + 2, yv - 2, yv + 2, pz0 - ep - 3,
                                pz0 + float(t['profondeur_taraudage']))
            morceaux.append(vis_tri)
            couleurs.append(np.tile(VIS, (len(vis_tri), 1)))
    else:
        if rang == 0:
            corps = (by0, by1, bz0)
            haut_mors = bz0 + (dessous if dessous > 0 and mode != 'plaque'
                               else serrage)
        elif mode == 'squelette':
            e = tn.PEAU_FLANCS
            corps = (by0 + e, by1 - e, pz0)
            haut_mors = pz0 + serrage
        else:
            corps = (py0, py1, pz0)
            haut_mors = pz0 + serrage
        ya, yb, zb = corps
        largeur = max(bx1 - bx0, px1 - px0) + 20
        cx = (bx0 + bx1) / 2
        dispositif = t.get('serrage')
        if isinstance(dispositif, dict) and dispositif.get('genre'):
            # l'étau autocentré ou le mandrin de l'atelier, serrant la
            # bande [ya, yb] — le dessus de ses mors à haut_mors
            from src.core import serrages as sg
            longueur = max(bx1 - bx0, px1 - px0)
            o = sg.ouverture_pour(dispositif, yb - ya, longueur)
            M, CM = sg.triangles(dispositif, o,
                                 (cx, (ya + yb) / 2, haut_mors))
            morceaux.append(M)
            couleurs.append(CM)
        else:
            for y0m, y1m in ((ya - 12, ya), (yb, yb + 12)):
                M = tn._boite(cx - largeur / 2, cx + largeur / 2, y0m, y1m,
                              zb - 12, haut_mors)
                morceaux.append(M)
                couleurs.append(np.tile(MORS, (len(M), 1)))
    # le brut, ou ce qui en reste
    matiere = None
    if resultat is not None and resultat.get('S') is not None:
        g = resultat['grille']
        b = g.brut(float(resultat['fond']), 0.0)
        b.h = np.array(resultat['S'], dtype=float)
        try:
            matiere = b.maillage(160)
        except Exception:
            matiere = None
    else:
        calques.append({'pts': _arêtes_boite(bx0, by0, bz0, bx1, by1, bz1),
                        'couleur': BRUT, 'largeur': 1.4,
                        'genre': 'operation'})
    if avec_parcours and resultat is not None:
        for k, e in enumerate(resultat.get('etapes') or []):
            try:
                tr = u3._trajet(e['code'])
            except Exception:
                continue
            x, y, z = (np.asarray(tr.get(c, []), dtype=float)
                       for c in ('x', 'y', 'z'))
            if len(x) < 2:
                continue
            P = np.column_stack([x, y, z])
            # au-delà de quelques milliers de segments, un sur n
            pas = max(1, len(P) // 6000)
            calques.append({'pts': [P[::pas]], 'genre': 'parcours',
                            'couleur': PARCOURS[k % len(PARCOURS)],
                            'largeur': 1.0})
    texte = (f"Phase {rang + 1} — {phase.get('libelle', cle)} · "
             f"brut {bx1 - bx0:.1f} × {by1 - by0:.1f} × "
             f"{bz1 - bz0:.1f} mm")
    return {'triangles': np.concatenate(morceaux),
            'couleurs': np.concatenate(couleurs), 'aretes': aretes,
            'calques': calques, 'matiere': matiere, 'texte': texte}
