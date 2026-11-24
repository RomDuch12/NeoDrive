"""Lecture des fichiers IGES (.igs, .iges) — l'export « universel » de
CATIA, SolidWorks, Inventor.

On en lit les COURBES, projetées sur le plan XY (le dessus, comme un
plan d'atelier): droites (110), arcs de cercle (100), arcs d'ellipse
(104), courbes composées (102), polylignes (106), splines
paramétriques (112), B-splines rationnelles (126), chacune avec sa
matrice de transformation (124) et dans l'unité déclarée par le
fichier. Une pièce exportée en surfaces seulement (144/142) n'a que
des courbes « dépendantes »: elles sont alors toutes lues — les arêtes
de la pièce, vues de dessus.

Le format suit la spécification publique IGES 5.3 (enregistrements de
80 colonnes: Start, Global, Directory, Parameter, Terminate).
"""
from __future__ import annotations

import math
import pathlib
from typing import Dict, List, Optional, Tuple

import numpy as np

from .dxfimport import Cancelled, DxfError, ImportReport
from .geometry import Chemin

SUFFIXES = ('.igs', '.iges')

#: mm par unité, selon le drapeau d'unité de la section Global
_UNITES = {1: 25.4, 2: 1.0, 4: 304.8, 5: 1609344.0, 6: 1000.0,
           7: 1e6, 8: 0.0254, 9: 0.001, 10: 10.0, 11: 0.0000254}

_COURBES = (100, 102, 104, 106, 110, 112, 126)


class IgesError(DxfError):
    """Fichier IGES illisible."""


def _decouper_params(texte: str, delim: str = ',', fin: str = ';'):
    """Les paramètres d'un enregistrement (chaînes Hollerith « nH… »
    gardées entières)."""
    sortie = []
    i = 0
    n = len(texte)
    courant = ''
    while i < n:
        c = texte[i]
        if c == 'H' and courant.strip().isdigit():
            longueur = int(courant.strip())
            sortie.append(texte[i + 1:i + 1 + longueur])
            i += 1 + longueur
            courant = ''
            # sauter jusqu'au délimiteur suivant
            while i < n and texte[i] not in (delim, fin):
                i += 1
            if i < n and texte[i] == fin:
                return sortie
            i += 1
            continue
        if c == delim:
            sortie.append(courant.strip())
            courant = ''
        elif c == fin:
            sortie.append(courant.strip())
            return sortie
        else:
            courant += c
        i += 1
    if courant.strip():
        sortie.append(courant.strip())
    return sortie


def _nombre(v, defaut=0.0) -> float:
    try:
        return float(str(v).replace('D', 'E').replace('d', 'e'))
    except (TypeError, ValueError):
        return defaut


class _Fichier:
    def __init__(self, texte: str):
        sections: Dict[str, List[str]] = {'S': [], 'G': [], 'D': [],
                                          'P': [], 'T': []}
        for ligne in texte.splitlines():
            if len(ligne) < 73:
                ligne = ligne.ljust(80)
            s = ligne[72]
            if s in sections:
                sections[s].append(ligne)
        if not sections['D']:
            raise IgesError("pas de section Directory (IGES compressé ou "
                            "illisible)")
        glob = ''.join(l[:72] for l in sections['G'])
        delim, fin = ',', ';'
        if glob.startswith('1H'):
            delim = glob[2]
            reste = glob[4:]
            if reste.startswith('1H'):
                fin = reste[2]
        self.delim, self.fin = delim, fin
        g = _decouper_params(glob, delim, fin)
        self.unite = 1.0
        try:
            drapeau = int(_nombre(g[13], 2))
            self.unite = _UNITES.get(drapeau, 1.0)
            if drapeau == 3 and len(g) > 14:
                nom = str(g[14]).upper()
                self.unite = {'IN': 25.4, 'INCH': 25.4, 'MM': 1.0, 'FT': 304.8,
                              'M': 1000.0, 'CM': 10.0, 'UM': 0.001}.get(nom, 1.0)
        except (IndexError, ValueError):
            pass
        self.d: Dict[int, dict] = {}
        lignes = sections['D']
        for k in range(0, len(lignes) - 1, 2):
            a, b = lignes[k], lignes[k + 1]

            def champ(ligne, j):
                return ligne[8 * j:8 * j + 8].strip()
            try:
                seq = int(a[73:80])
                statut = champ(a, 8).rjust(8, '0')
                self.d[seq] = {
                    'type': int(champ(a, 0) or 0),
                    'p': int(champ(a, 1) or 0),
                    'niveau': int(champ(a, 4) or 0) if champ(a, 4).lstrip(
                        '-').isdigit() else 0,
                    'matrice': int(champ(a, 6) or 0),
                    'subordonne': int(statut[2:4] or 0),
                    'usage': int(statut[4:6] or 0),
                    'forme': int(champ(b, 4) or 0),
                    'lignes_p': int(champ(b, 3) or 1),
                }
            except ValueError:
                continue
        self.p_lignes = sections['P']
        self._params: Dict[int, list] = {}

    def params(self, de: int) -> list:
        if de in self._params:
            return self._params[de]
        e = self.d.get(de)
        if e is None or e['p'] <= 0:
            return []
        debut = e['p'] - 1
        texte = ''.join(l[:64] for l in
                        self.p_lignes[debut:debut + max(1, e['lignes_p'])])
        p = _decouper_params(texte, self.delim, self.fin)[1:]
        self._params[de] = p
        return p

    def matrice(self, de: int, profondeur: int = 0) -> np.ndarray:
        """La transformation 4×4 (124) d'une entité, enchaînée."""
        M = np.eye(4)
        e = self.d.get(de)
        if e is None or not e['matrice'] or profondeur > 10:
            return M
        mde = e['matrice']
        p = [_nombre(v) for v in self.params(mde)[:12]]
        if len(p) == 12:
            M[:3, :3] = [[p[0], p[1], p[2]], [p[4], p[5], p[6]],
                         [p[8], p[9], p[10]]]
            M[:3, 3] = [p[3], p[7], p[11]]
        return self.matrice(mde, profondeur + 1) @ M


def _arc(cx, cy, z, x1, y1, x2, y2, pas_deg=3.0):
    r = math.hypot(x1 - cx, y1 - cy)
    a0 = math.atan2(y1 - cy, x1 - cx)
    a1 = math.atan2(y2 - cy, x2 - cx)
    if abs(x1 - x2) < 1e-9 and abs(y1 - y2) < 1e-9:
        a1 = a0 + 2 * math.pi
    while a1 <= a0:
        a1 += 2 * math.pi
    n = max(2, int(math.ceil(math.degrees(a1 - a0) / pas_deg)))
    return [(cx + r * math.cos(a0 + (a1 - a0) * k / n),
             cy + r * math.sin(a0 + (a1 - a0) * k / n), z)
            for k in range(n + 1)]


def _points_entite(f: _Fichier, de: int, profondeur: int = 0
                   ) -> List[List[Tuple[float, float, float]]]:
    """Les polylignes 3D d'une courbe, dans le repère du modèle."""
    e = f.d.get(de)
    if e is None or profondeur > 20:
        return []
    t = e['type']
    p = f.params(de)
    v = [_nombre(x) for x in p]
    morceaux: List[List[Tuple[float, float, float]]] = []
    try:
        if t == 110 and len(v) >= 6:
            morceaux = [[tuple(v[0:3]), tuple(v[3:6])]]
        elif t == 100 and len(v) >= 7:
            morceaux = [_arc(v[1], v[2], v[0], v[3], v[4], v[5], v[6])]
        elif t == 104 and len(v) >= 11:
            A, B, C, D, E, F, zt, x1, y1, x2, y2 = v[:11]
            if e['forme'] == 1 and A and C and F and -F / A > 0 \
                    and -F / C > 0:
                a, b = math.sqrt(-F / A), math.sqrt(-F / C)
                t0 = math.atan2(y1 / b, x1 / a)
                t1 = math.atan2(y2 / b, x2 / a)
                if abs(x1 - x2) < 1e-9 and abs(y1 - y2) < 1e-9:
                    t1 = t0 + 2 * math.pi
                while t1 <= t0:
                    t1 += 2 * math.pi
                n = max(8, int((t1 - t0) / math.radians(3)))
                morceaux = [[(a * math.cos(t0 + (t1 - t0) * k / n),
                              b * math.sin(t0 + (t1 - t0) * k / n), zt)
                             for k in range(n + 1)]]
            else:
                morceaux = [[(x1, y1, zt), (x2, y2, zt)]]
        elif t == 102 and v:
            n = int(v[0])
            chaine = []
            for k in range(n):
                sous = int(v[1 + k])
                for m in _points_entite(f, sous, profondeur + 1):
                    if chaine and m and math.dist(chaine[-1], m[0]) < 1e-6:
                        chaine += m[1:]
                    elif chaine and m and math.dist(chaine[-1], m[-1]) < 1e-6:
                        chaine += list(reversed(m))[1:]
                    else:
                        if len(chaine) >= 2:
                            morceaux.append(chaine)
                        chaine = list(m)
            if len(chaine) >= 2:
                morceaux.append(chaine)
            return morceaux       # les membres portent leurs matrices
        elif t == 106 and len(v) >= 2:
            ip, n = int(v[0]), int(v[1])
            if ip == 1:
                zt = v[2]
                xy = v[3:3 + 2 * n]
                morceaux = [[(xy[2 * k], xy[2 * k + 1], zt) for k in range(n)]]
            else:
                pas = 3 if ip == 2 else 6
                d = v[2:2 + pas * n]
                morceaux = [[(d[pas * k], d[pas * k + 1], d[pas * k + 2])
                             for k in range(n)]]
            if e['forme'] == 63 and morceaux and morceaux[0]:
                morceaux[0].append(morceaux[0][0])
        elif t == 112 and len(v) >= 4:
            n = int(v[3])
            tps = v[4:5 + n]
            coef = v[5 + n:]
            pts = []
            for s in range(n):
                c = coef[12 * s:12 * s + 12]
                if len(c) < 12:
                    break
                du = tps[s + 1] - tps[s]
                for k in range(0 if s == 0 else 1, 11):
                    u = du * k / 10.0
                    pts.append(tuple(c[4 * a] + c[4 * a + 1] * u
                                     + c[4 * a + 2] * u * u
                                     + c[4 * a + 3] * u ** 3
                                     for a in range(3)))
            morceaux = [pts]
        elif t == 126 and len(v) >= 6:
            from .stepread import _de_boor
            K, M = int(v[0]), int(v[1])
            nk = K + M + 2
            i = 6
            U = v[i:i + nk]
            i += nk
            W = v[i:i + K + 1]
            i += K + 1
            P = [tuple(v[i + 3 * j:i + 3 * j + 3]) for j in range(K + 1)]
            i += 3 * (K + 1)
            u0, u1 = (v[i], v[i + 1]) if len(v) > i + 1 else (U[M], U[-M - 1])
            n = max(8, 12 * (K + 1))
            morceaux = [[_de_boor(M, U, P, W, u0 + (u1 - u0) * k / n
                                  if k < n else u1 - 1e-12 * abs(u1 or 1))
                         for k in range(n + 1)]]
    except (IndexError, ValueError, ZeroDivisionError):
        return []
    M4 = f.matrice(de)
    sortie = []
    for m in morceaux:
        if len(m) < 2:
            continue
        P = np.asarray(m, dtype=float)
        P = P @ M4[:3, :3].T + M4[:3, 3]
        sortie.append([tuple(q) for q in P])
    return sortie


def lire(chemin, tolerance_mm: float = 0.02, units_mm: float = None,
         progress=None, ask=None):
    """`({calque: [Chemin]}, rapport)`: les courbes, vues de dessus."""
    try:
        texte = pathlib.Path(chemin).read_text(encoding='latin-1')
    except OSError as err:
        raise IgesError(f"lecture impossible: {err}") from None
    f = _Fichier(texte)
    echelle = float(units_mm) if units_mm else f.unite
    rapport = ImportReport()
    rapport.units_mm = echelle
    rapport.declared_units_mm = f.unite
    courbes = [de for de, e in f.d.items() if e['type'] in _COURBES]
    independantes = [de for de in courbes if f.d[de]['subordonne'] == 0
                     and f.d[de]['usage'] in (0, 5)]
    if not independantes:
        # une pièce en surfaces: ses arêtes (courbes dépendantes, mais
        # pas les membres d'une composite, lue entière)
        membres = set()
        for de in courbes:
            if f.d[de]['type'] == 102:
                p = f.params(de)
                try:
                    membres |= {int(_nombre(x)) for x in p[1:1 + int(
                        _nombre(p[0]))]}
                except (IndexError, ValueError):
                    pass
        independantes = [de for de in courbes if de not in membres]
        if independantes:
            rapport.notes.append("IGES en surfaces: les arêtes de la pièce, "
                                 "vues de dessus")
    calques: Dict[str, List[Chemin]] = {}
    zs = []
    for k, de in enumerate(independantes):
        if progress is not None and k % 200 == 0:
            if progress(k / max(1, len(independantes)), "courbes IGES") \
                    is False:
                raise Cancelled("lecture arrêtée")
        niveau = f.d[de]['niveau']
        nom = f"IGES niveau {niveau}" if niveau > 0 else "dessin"
        for m in _points_entite(f, de):
            pts = [(x * echelle, y * echelle) for x, y, _z in m]
            zs += [z * echelle for _x, _y, z in m]
            ch = Chemin(pts, tolerance_mm)
            calques.setdefault(nom, []).append(ch)
    if not calques:
        raise IgesError("aucune courbe lue dans ce fichier IGES")
    autres = {}
    for e in f.d.values():
        if e['type'] not in _COURBES and e['type'] not in (124, 402, 406,
                                                           314, 116):
            autres[f"IGES {e['type']}"] = autres.get(f"IGES {e['type']}", 0) + 1
    if autres:
        rapport.skipped_other = autres
    rapport.layers = {k: len(v) for k, v in calques.items()}
    rapport.polylines = sum(rapport.layers.values())
    pts = [p for v in calques.values() for c in v for p in c]
    rapport.extent = (min(p[0] for p in pts), min(p[1] for p in pts),
                      max(p[0] for p in pts), max(p[1] for p in pts))
    if zs and max(zs) - min(zs) > 1e-6:
        rapport.notes.append(f"pièce 3D projetée sur XY (Z de {min(zs):g} "
                             f"à {max(zs):g} mm)")
    rapport.notes.append(f"IGES: {len(courbes)} courbe(s)")
    return calques, rapport
