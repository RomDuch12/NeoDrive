"""Enlèvement de matière: le brut en carte de hauteurs.

Le brut est une grille de colonnes verticales (des « dexels »): pour
chaque cellule, la hauteur du dessus de la matière. L'outil, passé le
long du parcours simulé (sim_cycles), abaisse chaque colonne qu'il
touche jusqu'à sa propre surface:

- fraise plate: le fond à la cote de la pointe, sur tout le rayon;
- boule: R - sqrt(R² - d²) au-dessus de la pointe;
- cône (pointe à graver, chanfrein, foret à 118°): (d - r pointe) /
  tan(angle / 2) au-dessus de la pointe, jusqu'au rayon de la queue.

Pour une fraise plate qui descend en biais (rampe, hélice), la colonne
prend la cote la plus basse que l'outil atteint en passant au-dessus
d'elle (l'intervalle du segment à moins d'un rayon), pas seulement au
point le plus proche: une rampe creuse comme sur la machine.

La grille compte au plus `max_cellules` colonnes (le pas s'adapte au
brut). `maillage` en tire des triangles pour la vue 3D: le dessus,
réduit à `max_cotes` par côté en gardant le plus bas de chaque bloc
(un petit trou reste visible), les flancs du brut et son dessous; une
colonne percée de part en part laisse un trou.
"""

import math
from typing import Dict, Optional

import numpy as np

#: couleur du brut intact (aluminium) et de la matière usinée
COULEUR_BRUT = (0.70, 0.74, 0.80)
COULEUR_USINE_HAUT = (0.96, 0.78, 0.48)
COULEUR_USINE_FOND = (0.86, 0.45, 0.25)
#: une colonne à moins de ceci du dessous est percée
_EPS_PERCE = 1e-3


class Brut:
    """La matière: une grille de hauteurs sur [xmin, xmax] × [ymin, ymax],
    du dessous `z_bas` au dessus `z_haut`."""

    def __init__(self, xmin, xmax, ymin, ymax, z_bas=-20.0, z_haut=0.0,
                 max_cellules: int = 250000, pas: Optional[float] = None):
        lx = max(float(xmax) - float(xmin), 1e-3)
        ly = max(float(ymax) - float(ymin), 1e-3)
        if pas is None:
            pas = max(0.02, math.sqrt(lx * ly / max(1000, max_cellules)))
        self.pas = float(pas)
        self.nx = max(2, int(math.ceil(lx / self.pas)))
        self.ny = max(2, int(math.ceil(ly / self.pas)))
        self.x0, self.y0 = float(xmin), float(ymin)
        self.z_bas, self.z_haut = float(z_bas), float(z_haut)
        self.h = np.full((self.ny, self.nx), self.z_haut)
        self.xc = self.x0 + (np.arange(self.nx) + 0.5) * self.pas
        self.yc = self.y0 + (np.arange(self.ny) + 0.5) * self.pas
        #: sommets du parcours déjà appliqués
        self.applique = 0
        #: (largeur, longueur) du brut déclaré, quand il a été réduit à
        #: la zone usinée; None sinon
        self.reduit = None

    #: un brut déclaré plus grand que ceci × la zone usinée (avec sa
    #: marge) est réduit à cette zone: les en-têtes de l'atelier
    #: déclarent souvent ±1000 mm, et la grille deviendrait grossière
    RAPPORT_BRUT_MAX = 4.0
    #: moins que cette part des coupes dans le brut déclaré: ce n'est pas
    #: le brut de ce programme
    PART_DANS_LE_BRUT = 0.75

    @classmethod
    def autour(cls, res, marge=5.0, boite=None, **kw):
        """Le brut déclaré par le programme, sinon la boîte des coupes
        plus une marge. Un brut déclaré démesuré est réduit à la zone
        usinée (sa cote Z est gardée): `reduit` le dit; un brut déclaré où
        le parcours ne passe guère ne compte que par sa cote Z. `boite`: le
        BRUT des Paramètres (la plaque à usiner), pris tel quel."""
        if boite:
            xmin, xmax, ymin, ymax, zmin, zmax = (float(v) for v in boite)
            if xmax > xmin and ymax > ymin and zmax > zmin:
                return cls(xmin, xmax, ymin, ymax, zmin, zmax, **kw)
        from src.core import sim3d
        x = np.asarray(res.get('x') or [0.0]) if res else np.zeros(1)
        y = np.asarray(res.get('y') or [0.0]) if res else np.zeros(1)
        z = np.asarray(res.get('z') or [0.0]) if res else np.zeros(1)
        k = np.asarray(res.get('k') or [0]) if res else np.zeros(1)
        coupe = k == sim3d.COUPE
        if coupe.any():
            x, y, z = x[coupe], y[coupe], z[coupe]
        zone = (float(x.min()) - marge, float(x.max()) + marge,
                float(y.min()) - marge, float(y.max()) + marge)
        b = res.get('brut') if res else None
        if b:
            xmin, xmax, ymin, ymax, zmin, zmax = b
            if coupe.any() and ((x >= xmin) & (x <= xmax) & (y >= ymin)
                                & (y <= ymax)).mean() < cls.PART_DANS_LE_BRUT:
                # l'en-tête dit l'espace de travail, pas le brut: 0-210 ×
                # 0-297 sur un programme centré, on n'en creusait qu'un coin
                # (sur 92 programmes de l'atelier, 1 sur 3), voire « 0 mm³ »
                return cls(*zone, zmin, zmax, **kw)
            aire_brut = (xmax - xmin) * (ymax - ymin)
            aire_zone = (zone[1] - zone[0]) * (zone[3] - zone[2])
            if coupe.any() and aire_brut > cls.RAPPORT_BRUT_MAX * aire_zone:
                gx0, gx1 = max(xmin, zone[0]), min(xmax, zone[1])
                gy0, gy1 = max(ymin, zone[2]), min(ymax, zone[3])
                if gx1 > gx0 and gy1 > gy0:
                    brut = cls(gx0, gx1, gy0, gy1, zmin, zmax, **kw)
                    brut.reduit = (xmax - xmin, ymax - ymin)
                    return brut
            return cls(xmin, xmax, ymin, ymax, zmin, zmax, **kw)
        bas = min(float(z.min()) - 2.0, -1.0)
        return cls(*zone, bas, 0.0, **kw)

    def copie(self) -> "Brut":
        neuf = Brut.__new__(Brut)
        neuf.__dict__.update(self.__dict__)
        neuf.h = self.h.copy()
        return neuf

    def remettre(self) -> None:
        self.h.fill(self.z_haut)
        self.applique = 0

    # ── l'outil ──

    def enlever(self, x0, y0, z0, x1, y1, z1, forme: Dict) -> None:
        """L'outil (forme de `sim_cycles.forme_outil`) de (x0, y0, z0)
        à (x1, y1, z1), la pointe en z."""
        R = max(1e-3, float(forme.get('rayon', 1.0)))
        if min(z0, z1) >= self.z_haut:
            return
        p = self.pas
        i0 = max(0, int(math.floor((min(x0, x1) - R - self.x0) / p)))
        i1 = min(self.nx, int(math.ceil((max(x0, x1) + R - self.x0) / p)) + 1)
        j0 = max(0, int(math.floor((min(y0, y1) - R - self.y0) / p)))
        j1 = min(self.ny, int(math.ceil((max(y0, y1) + R - self.y0) / p)) + 1)
        if i0 >= i1 or j0 >= j1:
            return
        X = self.xc[i0:i1][None, :]
        Y = self.yc[j0:j1][:, None]
        dx, dy = x1 - x0, y1 - y0
        L2 = dx * dx + dy * dy
        px, py = X - x0, Y - y0
        plat = forme.get('forme') in ('plate', 'filet', 'tslot')
        if L2 < 1e-14:
            d = np.hypot(px, py)
            zc = np.full(d.shape, min(z0, z1))
            if plat:
                z_outil = np.where(d <= R, zc, np.inf)
            else:
                z_outil = zc + _profil(d, forme, R)
        else:
            proj = (px * dx + py * dy) / L2
            t = np.clip(proj, 0.0, 1.0)
            d = np.hypot(px - t * dx, py - t * dy)
            if plat and z1 != z0:
                # la plus basse cote que l'outil touche au-dessus de la
                # colonne: un bout de l'intervalle à moins de R
                q = px * px + py * py - R * R
                disc = (proj * proj) - q / L2
                ok = disc >= 0
                rac = np.sqrt(np.where(ok, disc, 0.0))
                ta = np.clip(proj - rac, 0.0, 1.0)
                tb = np.clip(proj + rac, 0.0, 1.0)
                t_bas = tb if z1 < z0 else ta
                zc = z0 + t_bas * (z1 - z0)
                z_outil = np.where(ok & (d <= R + 1e-9), zc, np.inf)
            else:
                zc = z0 + t * (z1 - z0)
                z_outil = zc + _profil(d, forme, R)
        fen = self.h[j0:j1, i0:i1]
        coupe = np.maximum(z_outil, self.z_bas)
        if forme.get('forme') == 'tslot':
            # le disque ne coupe que son épaisseur: là où la matière
            # monte plus haut que lui (une contre-dépouille), le dessus
            # reste — la carte de hauteurs ne voit pas la rainure
            hauteur = float(forme.get('hauteur', 1.0))
            coupe = np.where(fen <= z_outil + hauteur + 1e-9, coupe,
                             np.inf)
        np.minimum(fen, coupe, out=fen)

    # ── les petits segments: des tampons ──

    #: un segment plus court que ceci (en pas de grille) se passe en
    #: tampons, un par pas de grille: 3/4 des segments d'un vrai programme,
    #: 5 fois moins de temps (12,8 -> 2,3 s sur 190 000 coupes), le volume à
    #: 0,1 % près
    SEGMENT_COURT = 3.0
    #: les positions d'un outil dans une cellule, par axe: posé au centre de
    #: la cellule, chaque bord bouge d'un demi-pas, et l'enveloppe de tous ne
    #: garde que le plus large (+3 % de volume sur des gravures fines)
    PHASES = 8
    #: au-delà de ce rayon (cellules), peu de positions: le tampon est grand,
    #: et un demi-pas ne compte plus devant lui
    RAYON_TAMPON_FIN = 64

    def _table_de(self, forme: Dict) -> dict:
        """Les tampons d'un outil, créés à la demande: {'n': rayon en
        cellules, 'phases': par axe, 'R', 'forme', 'tampons': par position}.
        Retrouvés d'un appel à l'autre: la lecture en passe peu à chaque
        image."""
        tables = self.__dict__.setdefault('_tables', {})
        cle = repr(sorted(forme.items()))
        table = tables.get(cle)
        if table is None:
            R = max(1e-3, float(forme.get('rayon', 1.0)))
            n = int(math.ceil(R / self.pas)) + 1
            phases = self.PHASES if n <= self.RAYON_TAMPON_FIN else 2
            table = tables[cle] = {
                'n': n, 'phases': phases, 'R': R, 'forme': forme,
                'plat': forme.get('forme') in ('plate', 'filet'),
                'tampons': [None] * (phases * phases)}
        return table

    def _tampon(self, table: dict, fx: int, fy: int):
        """La hauteur de l'outil (sa pointe en 0) sur les cellules autour
        de lui: inf hors de l'outil."""
        phases, n = table['phases'], table['n']
        base = np.arange(-n, n + 1) + 0.5
        ax = (base - (fx + 0.5) / phases) * self.pas
        ay = (base - (fy + 0.5) / phases) * self.pas
        d = np.hypot(ax[None, :], ay[:, None])
        if table['plat']:
            t = np.where(d <= table['R'], 0.0, np.inf)
        else:
            t = _profil(d, table['forme'], table['R'])
        table['tampons'][fx + fy * phases] = t
        return t

    def _passer_court(self, table: dict, x0, y0, z0, dx, dy, z1,
                      L2: float) -> None:
        """Un segment court: l'outil posé à chaque pas de grille."""
        p = self.pas
        n = table['n']
        phases = table['phases']
        tampons = table['tampons']
        nb = max(1, int(math.ceil(math.sqrt(L2) / p)))
        for q in range(1, nb + 1):
            f = q / nb
            u = (x0 + f * dx - self.x0) / p
            v = (y0 + f * dy - self.y0) / p
            ci = math.floor(u)
            cj = math.floor(v)
            i0, i1 = ci - n, ci + n + 1
            j0, j1 = cj - n, cj + n + 1
            if i0 >= self.nx or j0 >= self.ny or i1 <= 0 or j1 <= 0:
                continue
            fx = min(int((u - ci) * phases), phases - 1)
            fy = min(int((v - cj) * phases), phases - 1)
            t = tampons[fx + fy * phases]
            if t is None:
                t = self._tampon(table, fx, fy)
            if i0 < 0 or j0 < 0 or i1 > self.nx or j1 > self.ny:
                # au bord du brut: la part de tampon qui tombe dedans
                t = t[max(0, -j0):t.shape[0] - max(0, j1 - self.ny),
                      max(0, -i0):t.shape[1] - max(0, i1 - self.nx)]
                i0, j0 = max(0, i0), max(0, j0)
                i1, j1 = min(self.nx, i1), min(self.ny, j1)
            z = z0 + f * (z1 - z0) if L2 else min(z0, z1)
            fen = self.h[j0:j1, i0:i1]
            if z >= self.z_bas:
                np.minimum(fen, t + z, out=fen)
            else:
                np.minimum(fen, np.maximum(t + z, self.z_bas), out=fen)

    def appliquer(self, res, formes: Dict, jusqua: Optional[int] = None,
                  progression=None) -> None:
        """Passe l'outil sur le parcours, du dernier sommet appliqué
        jusqu'à `jusqua` (exclu; None: tout). Revenir en arrière
        repart du brut intact."""
        from src.core import sim3d, vcarve
        n = len(res.get('x') or [])
        fin = n if jusqua is None else max(0, min(int(jusqua), n))
        if fin < self.applique:
            self.remettre()
        xs, ys, zs = res['x'], res['y'], res['z']
        ks = res['k']
        outils = res.get('outil') or [''] * n
        defaut = {'forme': 'plate', 'rayon': 1.0}
        debut = max(1, self.applique)
        total = max(1, fin - debut)
        court2 = (self.SEGMENT_COURT * self.pas) ** 2
        # (par identité: les formes vivent le temps de cette boucle)
        tables = {}
        for i in range(debut, fin):
            if progression is not None and (i - debut) % 3000 == 0:
                vcarve.avancer(progression, (i - debut) / total,
                               "enlèvement de matière")
            if ks[i] != sim3d.COUPE:
                continue
            z0, z1 = zs[i - 1], zs[i]
            if z1 >= self.z_haut and z0 >= self.z_haut:
                continue
            forme = formes.get(outils[i]) or defaut
            x0, y0, x1, y1 = xs[i - 1], ys[i - 1], xs[i], ys[i]
            dx, dy = x1 - x0, y1 - y0
            L2 = dx * dx + dy * dy
            if L2 > court2 or forme.get('forme') == 'tslot':
                self.enlever(x0, y0, z0, x1, y1, z1, forme)
                continue
            table = tables.get(id(forme))
            if table is None:
                table = tables[id(forme)] = self._table_de(forme)
            self._passer_court(table, x0, y0, z0, dx, dy, z1, L2)
        self.applique = max(self.applique, fin)

    # ── mesures ──

    def hauteur_en(self, x, y) -> float:
        i = int((x - self.x0) / self.pas)
        j = int((y - self.y0) / self.pas)
        i = min(max(i, 0), self.nx - 1)
        j = min(max(j, 0), self.ny - 1)
        return float(self.h[j, i])

    def volume_enleve(self) -> float:
        """mm³ enlevés."""
        return float((self.z_haut - self.h).sum() * self.pas * self.pas)

    # ── pour la vue ──

    def maillage(self, max_cotes: int = 300, tuile_max: int = 16):
        """(triangles (N, 3, 3), couleurs (N, 3)) du brut: le dessus
        (réduit en gardant le plus bas de chaque bloc), les flancs et le
        dessous."""
        f = max(1, int(math.ceil(max(self.nx, self.ny) / float(max_cotes))))
        ny, nx = self.ny // f * f, self.nx // f * f
        if ny < f or nx < f:
            f = 1
            ny, nx = self.ny, self.nx
        h = self.h[:ny, :nx].reshape(ny // f, f, nx // f, f).min(axis=(1, 3))
        pas = self.pas * f
        gy, gx = h.shape
        xs = self.x0 + (np.arange(gx) + 0.5) * pas
        ys = self.y0 + (np.arange(gy) + 0.5) * pas
        X, Y = np.meshgrid(xs, ys)
        P = np.stack([X, Y, h], axis=-1)
        tri = self._dessus(P, tuile_max)
        moy = tri[:, :, 2].mean(axis=1) if len(tri) else np.zeros(0)
        couleurs = self._couleurs(moy).reshape(-1, 3)
        # les flancs: du bord du dessus jusqu'au dessous
        flancs = []
        for bord in (P[0, :], P[-1, :], P[:, 0], P[:, -1]):
            haut = bord
            bas = bord.copy()
            bas[:, 2] = self.z_bas
            for i in range(len(bord) - 1):
                if haut[i, 2] <= self.z_bas + _EPS_PERCE \
                        and haut[i + 1, 2] <= self.z_bas + _EPS_PERCE:
                    continue
                flancs.append([haut[i], haut[i + 1], bas[i + 1]])
                flancs.append([haut[i], bas[i + 1], bas[i]])
        # le dessous, en carreaux: deux grands triangles se trient mal
        # (algorithme du peintre) et débordaient sur les flancs
        zb = self.z_bas
        dessous = []
        gxs = np.linspace(xs[0], xs[-1], min(len(xs), 16))
        gys = np.linspace(ys[0], ys[-1], min(len(ys), 16))
        # sous un trou débouchant, pas de dessous: on voit à travers
        perce_g = h <= self.z_bas + _EPS_PERCE
        ix = np.searchsorted(xs, gxs)
        iy = np.searchsorted(ys, gys)
        for i in range(len(gxs) - 1):
            for j in range(len(gys) - 1):
                if perce_g[iy[j]:iy[j + 1] + 1, ix[i]:ix[i + 1] + 1].any():
                    continue
                a0, a1 = gxs[i], gxs[i + 1]
                b0, b1 = gys[j], gys[j + 1]
                dessous.append([(a0, b0, zb), (a1, b1, zb), (a1, b0, zb)])
                dessous.append([(a0, b0, zb), (a0, b1, zb), (a1, b1, zb)])
        autres = np.array(flancs + dessous, dtype=float).reshape(-1, 3, 3)
        tri = np.concatenate([tri, autres])
        couleurs = np.concatenate(
            [couleurs, np.tile(COULEUR_BRUT, (len(autres), 1))])
        return tri, couleurs

    def _dessus(self, P, tuile_max: int):
        """Les triangles du dessus. Un carreau (entre 4 centres voisins)
        dont les 4 coins sont à la même cote est PLAT; un bloc de
        carreaux tous plats (donc à la même cote: ils se touchent) est
        posé en deux triangles — le dessus intact et les fonds de poche
        ne coûtent presque rien, la finesse va aux parois et aux
        gravures. Les blocs plats au fond du brut (percés) sont des
        trous."""
        z = P[:, :, 2]
        coins = np.stack([z[:-1, :-1], z[:-1, 1:], z[1:, 1:], z[1:, :-1]])
        plat = (coins.max(axis=0) - coins.min(axis=0)) < 1e-9
        perce = coins.max(axis=0) <= self.z_bas + _EPS_PERCE
        qy, qx = plat.shape
        if qy < 1 or qx < 1:
            return np.zeros((0, 3, 3))
        # somme cumulée des carreaux NON plats: un bloc est plat en O(1)
        S = np.zeros((qy + 1, qx + 1), dtype=np.int64)
        S[1:, 1:] = np.cumsum(np.cumsum(~plat, axis=0), axis=1)
        grands, seuls = [], []
        pile = [(0, qy, 0, qx)]
        while pile:
            j0, j1, i0, i1 = pile.pop()
            if j1 <= j0 or i1 <= i0:
                continue
            aire = (j1 - j0) * (i1 - i0)
            non_plats = S[j1, i1] - S[j0, i1] - S[j1, i0] + S[j0, i0]
            if non_plats == 0 and j1 - j0 <= tuile_max \
                    and i1 - i0 <= tuile_max:
                if not perce[j0, i0]:
                    grands.append((j0, j1, i0, i1))
                continue
            if aire == 1:
                if not perce[j0, i0]:
                    seuls.append((j0, i0))
                continue
            jm, im = (j0 + j1) // 2, (i0 + i1) // 2
            pile += [(j0, jm, i0, im), (j0, jm, im, i1),
                     (jm, j1, i0, im), (jm, j1, im, i1)]
        morceaux = []
        if seuls:
            jj, ii = np.array(seuls).T
            a, b = P[jj, ii], P[jj, ii + 1]
            c, d = P[jj + 1, ii + 1], P[jj + 1, ii]
            morceaux += [np.stack([a, b, c], axis=1),
                         np.stack([a, c, d], axis=1)]
        if grands:
            j0, j1, i0, i1 = np.array(grands).T
            a, b = P[j0, i0], P[j0, i1]
            c, d = P[j1, i1], P[j1, i0]
            morceaux += [np.stack([a, b, c], axis=1),
                         np.stack([a, c, d], axis=1)]
        if not morceaux:
            return np.zeros((0, 3, 3))
        return np.concatenate(morceaux)

    def _couleurs(self, z):
        """Intact: aluminium; usiné: du clair (peu profond) au foncé."""
        haut = np.array(COULEUR_BRUT)
        c1 = np.array(COULEUR_USINE_HAUT)
        c2 = np.array(COULEUR_USINE_FOND)
        epaisseur = max(1e-6, self.z_haut - self.z_bas)
        t = np.clip((self.z_haut - z) / epaisseur, 0.0, 1.0)[:, None]
        usine = c1 + (c2 - c1) * t
        intact = (self.z_haut - z) < 1e-3
        return np.where(intact[:, None], haut, usine)


def _profil(d, forme: Dict, R: float):
    """Hauteur de la surface de l'outil au-dessus de sa pointe, à la
    distance d de l'axe (inf hors de l'outil)."""
    genre = forme.get('forme', 'plate')
    dehors = d > R + 1e-9
    if genre == 'boule':
        h = R - np.sqrt(np.clip(R * R - d * d, 0.0, None))
    elif genre == 'cone':
        demi = math.radians(max(1.0, float(forme.get('angle') or 90.0)) / 2)
        rp = max(0.0, float(forme.get('pointe') or 0.0) / 2.0)
        h = np.clip(d - rp, 0.0, None) / math.tan(demi)
    else:
        h = np.zeros_like(d)
    return np.where(dehors, np.inf, h)
