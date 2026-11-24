"""Des triangles dans un tableau numpy, avec un tampon de profondeur.

Le peintre triait les triangles par leur centre et faisait un appel à Qt par
triangle: 180 000 triangles, près d'une seconde par image, et une grande face
voisine de petites facettes se rangeait mal. Ici chaque triangle est découpé en
lignes, chaque ligne en pixels, et le plus proche gagne pixel par pixel: rien à
trier, aucune boucle Python par triangle.

Le coût d'un tableau numpy n'est pas proportionnel à sa taille: sous Windows, un
tableau de plusieurs Mo vient du système, page par page, et coûte trois fois plus
par élément. D'où les paquets de triangles et les bandes d'image: de petits
tableaux. (Des fils n'y gagnent que 10 %: `np.repeat`, `ufunc.at` et l'écriture
indexée gardent le verrou de Python.)

La projection est orthographique: la profondeur est linéaire à l'écran.

Règle de couverture: le centre d'un pixel appartient à un triangle s'il est dans
[min, max[ sur sa ligne et sur sa colonne. Deux triangles qui partagent un côté
le coupent au même endroit (les sommets sont rangés par y avant le calcul): ni
trou entre eux, ni pixel compté deux fois, ce qui compte pour la transparence.
"""

import numpy as np

from src.gui.traits_en_points import segments_visibles

#: les triangles opaques passent par paquets de cette taille
TRIANGLES_PAR_PAQUET = 30_000
#: une bande d'image, à peu près ce nombre de pixels à poser...
PIXELS_PAR_BANDE = 60_000
#: ... et au plus ce nombre de bandes
BANDES_MAX = 16
#: une bande passe par lots d'à peu près ce nombre de pixels: la mémoire reste
#: bornée, quels que soient le zoom et le nombre de couches
FRAGMENTS_PAR_LOT = 100_000
#: une ligne de pixels à partir de laquelle un passage d'un bloc coûte moins cher
#: qu'un élément par pixel
LIGNE_LONGUE = 128
#: une aire écran sous laquelle (px²) le plan d'un triangle se calcule mal: sa
#: profondeur est bornée à celles de ses sommets
AIRE_FINE = 2.0
#: au-delà, un triangle n'est plus une forme, c'est un défaut des données
ETENDUE_MAX = 1e12
#: un trait derrière une face transparente, moins marqué que devant
TRAIT_DERRIERE = 0.45


class _Scene:
    """Les triangles (colonne par colonne, sommet par sommet: x de forme
    (3, N)) qui touchent l'image."""

    def __init__(self, x, y, d, largeur, hauteur):
        self.vide = True
        x0, x1, x2 = x
        y0, y1, y2 = y
        xn = np.minimum(np.minimum(x0, x1), x2)
        xm = np.maximum(np.maximum(x0, x1), x2)
        yn = np.minimum(np.minimum(y0, y1), y2)
        ym = np.maximum(np.maximum(y0, y1), y2)
        l0 = np.maximum(np.ceil(yn - 0.5), 0.0)
        l1 = np.minimum(np.ceil(ym - 0.5) - 1.0, hauteur - 1.0)
        c0 = np.maximum(np.ceil(xn - 0.5), 0.0)
        c1 = np.minimum(np.ceil(xm - 0.5) - 1.0, largeur - 1.0)
        # (une coordonnée NaN rend toutes ces comparaisons fausses)
        garde = np.flatnonzero(
            (l1 >= l0) & (c1 >= c0)
            & (xm - xn < ETENDUE_MAX) & (ym - yn < ETENDUE_MAX))
        if not len(garde):
            return
        x0, x1, x2, y0, y1, y2 = (a[garde] for a in (x0, x1, x2, y0, y1, y2))
        aire = 0.5 * np.abs((x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0))
        plein = np.flatnonzero(aire > 0.0)
        if not len(plein):
            return
        self.vide = False
        self.origine = garde[plein]
        self.x0, self.x1, self.x2 = x0[plein], x1[plein], x2[plein]
        self.y0, self.y1, self.y2 = y0[plein], y1[plein], y2[plein]
        self.d0, self.d1, self.d2 = (d[0][self.origine], d[1][self.origine],
                                     d[2][self.origine])
        self.aire = aire[plein]
        self.l0 = l0[self.origine]
        self.l1 = l1[self.origine]
        self.largeurs = (c1 - c0 + 1.0)[self.origine]
        self.estime = float(np.minimum(
            self.aire + self.l1 - self.l0 + 1.0,
            (self.l1 - self.l0 + 1.0) * self.largeurs).sum())

    def bandes(self):
        """Les bandes de lignes [a, b[ qui ont du travail."""
        haut, bas = int(self.l0.min()), int(self.l1.max()) + 1
        n = max(1, min(int(self.estime / PIXELS_PAR_BANDE), BANDES_MAX,
                       bas - haut))
        coupes = [haut + (bas - haut) * k // n for k in range(n + 1)]
        return list(zip(coupes[:-1], coupes[1:]))

    def lignes(self, haut, bas, sens):
        """Les triangles de la bande prêts à découper. `sens`: s'ils couvrent
        beaucoup de pixels, les plus proches d'abord (1, les suivants sont vite
        rejetés), les plus loin d'abord (-1) ou comme ils viennent (0)."""
        qui = np.flatnonzero((self.l0 < bas) & (self.l1 >= haut))
        if not len(qui):
            return None
        return _Lignes(self, qui, haut, bas, sens)

    def sous_bandes(self, haut, bas):
        """Les triangles de la bande [haut, bas[, par tranches de LIGNES
        d'image d'à peu près FRAGMENTS_PAR_LOT pixels à poser: pour composer,
        toutes les couches d'un pixel passent ensemble, de la plus loin à la
        plus proche. (Coupés par paquets de triangles, deux paquets se posaient
        l'un après l'autre, dans l'ordre des paquets et non de la profondeur en
        chaque pixel: de grandes faces transparentes qui se croisent sortaient
        fausses dans une grande vue.) Une ligne seule peut dépasser: elle passe
        entière."""
        qui = np.flatnonzero((self.l0 < bas) & (self.l1 >= haut))
        if not len(qui):
            return
        l0 = np.maximum(self.l0[qui], float(haut))
        l1 = np.minimum(self.l1[qui], float(bas - 1))
        lignes = l1 - l0 + 1.0
        estime = np.minimum(self.aire[qui] + lignes,
                            lignes * self.largeurs[qui])
        n = bas - haut
        if n <= 1 or estime.sum() <= FRAGMENTS_PAR_LOT:
            yield _Lignes(self, qui, haut, bas, 0)
            return
        # les pixels à poser ligne par ligne: chaque triangle réparti sur
        # les siennes
        part = estime / lignes
        debut = (l0 - haut).astype(np.int64)
        apres = (l1 - haut).astype(np.int64) + 1
        par_ligne = (np.bincount(debut, weights=part, minlength=n + 1)
                     - np.bincount(apres, weights=part, minlength=n + 1))
        cumul = np.cumsum(np.cumsum(par_ligne)[:n])
        a = 0
        while a < n:
            deja = cumul[a - 1] if a else 0.0
            b = int(np.searchsorted(cumul, deja + FRAGMENTS_PAR_LOT,
                                    side='right'))
            b = min(n, max(b, a + 1))
            dedans = qui[(debut < b) & (apres > a)]
            if len(dedans):
                yield _Lignes(self, dedans, haut + a, haut + b, 0)
            a = b


class _Lignes:
    """Les triangles d'une bande: rangés, sommets a, b, c par y croissant, avec
    les pentes de leurs côtés et leur plan."""

    __slots__ = ('n', 'origine', 'l0', 'lignes', 'estime', 'xa', 'ya', 'xb',
                 'yb', 'da', 'pac', 'pab', 'pbc', 'gx', 'gy', 'fin', 'dmin',
                 'dmax')

    def __init__(self, s: _Scene, qui, haut, bas, sens):
        x0, x1, x2 = s.x0[qui], s.x1[qui], s.x2[qui]
        y0, y1, y2 = s.y0[qui], s.y1[qui], s.y2[qui]
        d0, d1, d2 = s.d0[qui], s.d1[qui], s.d2[qui]
        aire = s.aire[qui]
        origine = s.origine[qui]
        l0 = np.maximum(s.l0[qui], float(haut))
        lignes = np.minimum(s.l1[qui], float(bas - 1)) - l0 + 1.0
        estime = np.minimum(aire + lignes, lignes * s.largeurs[qui])
        dmin = np.minimum(np.minimum(d0, d1), d2)
        dmax = np.maximum(np.maximum(d0, d1), d2)
        total = estime.sum()
        if sens and (total > FRAGMENTS_PAR_LOT or total > 32.0 * len(qui)):
            o = np.argsort(dmin if sens > 0 else -dmax)
            (x0, x1, x2, y0, y1, y2, d0, d1, d2, aire, origine, l0, lignes,
             estime, dmin, dmax) = (
                a[o] for a in (x0, x1, x2, y0, y1, y2, d0, d1, d2, aire,
                               origine, l0, lignes, estime, dmin, dmax))
        # les sommets par y croissant: trois échanges, à égalité rien ne bouge
        for u, v in ((0, 1), (1, 2), (0, 1)):
            xs, ys, ds = [x0, x1, x2], [y0, y1, y2], [d0, d1, d2]
            m = ys[v] < ys[u]
            xs[u], xs[v] = np.where(m, xs[v], xs[u]), np.where(m, xs[u], xs[v])
            ys[u], ys[v] = np.where(m, ys[v], ys[u]), np.where(m, ys[u], ys[v])
            ds[u], ds[v] = np.where(m, ds[v], ds[u]), np.where(m, ds[u], ds[v])
            x0, x1, x2 = xs
            y0, y1, y2 = ys
            d0, d1, d2 = ds
        self.n = len(qui)
        self.origine = origine
        self.l0 = l0
        self.lignes = lignes.astype(np.int64)
        self.estime = estime
        self.xa, self.ya, self.xb, self.yb = x0, y0, x1, y1
        self.da = d0
        hab = y1 - y0
        hac = y2 - y0
        lab = x1 - x0
        lac = x2 - x0
        self.pac = lac / hac
        self.pab = np.divide(lab, hab, out=np.zeros_like(lab), where=hab > 0.0)
        self.pbc = np.divide(x2 - x1, y2 - y1, out=np.zeros_like(lab),
                             where=y2 > y1)
        det = lab * hac - lac * hab
        dz1 = d1 - d0
        dz2 = d2 - d0
        self.gx = (dz1 * hac - dz2 * hab) / det
        self.gy = (dz2 * lab - dz1 * lac) / det
        self.fin = aire < AIRE_FINE
        self.dmin = dmin
        self.dmax = dmax

    def lots(self):
        """Les tranches (a, b) de triangles, chacune autour de
        FRAGMENTS_PAR_LOT pixels (un seul triangle peut dépasser: il tient
        toujours dans la bande)."""
        if self.estime.sum() <= FRAGMENTS_PAR_LOT:
            return [(0, self.n)]
        cumul = np.cumsum(self.estime)
        bornes = [0]
        while bornes[-1] < self.n:
            deja = cumul[bornes[-1] - 1] if bornes[-1] else 0.0
            b = int(np.searchsorted(cumul, deja + FRAGMENTS_PAR_LOT,
                                    side='right'))
            bornes.append(min(self.n, max(b, bornes[-1] + 1)))
        return list(zip(bornes[:-1], bornes[1:]))

    def tranches(self, a, b, largeur):
        """Les lignes de pixels des triangles a..b: (premier pixel, longueur,
        profondeur du premier, pente de la profondeur, triangle)."""
        n = self.lignes[a:b]
        rang = np.repeat(np.arange(a, b), n)
        if not len(rang):
            return None
        ligne = (np.repeat(self.l0[a:b] - (np.cumsum(n) - n), n)
                 + np.arange(len(rang)))
        yp = ligne + 0.5
        dy = yp - np.repeat(self.ya[a:b], n)
        xa = np.repeat(self.xa[a:b], n)
        x1 = xa + dy * np.repeat(self.pac[a:b], n)
        yb = np.repeat(self.yb[a:b], n)
        x2 = np.where(yp < yb, xa + dy * np.repeat(self.pab[a:b], n),
                      np.repeat(self.xb[a:b], n)
                      + (yp - yb) * np.repeat(self.pbc[a:b], n))
        x0 = np.maximum(np.ceil(np.minimum(x1, x2) - 0.5), 0.0)
        fin = np.minimum(np.ceil(np.maximum(x1, x2) - 0.5) - 1.0, largeur - 1.0)
        vus = np.flatnonzero(fin >= x0)
        if not len(vus):
            return None
        rang = rang[vus]
        x0 = x0[vus]
        long_ = (fin[vus] - x0 + 1.0).astype(np.int64)
        gx = self.gx[rang]
        depart = (self.da[rang] + gx * (x0 + 0.5 - xa[vus])
                  + self.gy[rang] * dy[vus])
        premier = ligne[vus].astype(np.int64) * largeur + x0.astype(np.int64)
        return premier, long_, depart, gx, rang

    def pixels(self, premier, long_, depart, gx, rang):
        """Ces lignes, pixel par pixel: (pixel, triangle, profondeur)."""
        total = int(long_.sum())
        if total == len(long_):         # des lignes d'un pixel: des petits
            pix, tri, prof = premier, rang, depart
        else:
            k = np.arange(total) - np.repeat(np.cumsum(long_) - long_, long_)
            pix = np.repeat(premier, long_) + k
            tri = np.repeat(rang, long_)
            prof = np.repeat(depart, long_) + np.repeat(gx, long_) * k
        fins = self.fin[tri]
        if fins.any():
            qui = tri[fins]
            prof[fins] = np.clip(prof[fins], self.dmin[qui], self.dmax[qui])
        return pix, tri, prof.astype(np.float32)


def _plus_loin(z, pixels):
    """La plus grande profondeur de ces pixels (un tuple d'indices)."""
    loin = z[pixels[0]]
    for autre in pixels[1:]:
        loin = np.maximum(loin, z[autre])
    return loin


def _composer(octets, pix, tri, src, journal, alpha_unique=None) -> None:
    """Les couches triées par (pixel, de la plus loin à la plus proche) sur ce
    qui est déjà dans l'image. Le résultat d'un pixel: la somme des couches,
    chacune voilée par le produit des (1 - alpha) de celles de devant. Ce
    produit est une différence de sommes de logarithmes: pas de passe par
    couche. `alpha_unique`: toutes au même alpha (0-1), le produit ne dépend
    que du nombre de couches, et se lit dans une table."""
    debuts = np.concatenate(([0], np.flatnonzero(pix[1:] != pix[:-1]) + 1))
    fins = np.append(debuts[1:], len(pix))
    dernier = np.repeat(fins - 1, fins - debuts)
    if alpha_unique is not None:
        nombre = fins - debuts
        table = (1.0 - alpha_unique) ** np.arange(int(nombre.max()) + 1,
                                                  dtype=np.float32)
        voile = table[dernier - np.arange(len(pix))]
        reste = table[nombre]
    else:
        log = journal[tri]
        cumul = np.cumsum(log)
        voile = np.exp(cumul[dernier] - cumul).astype(np.float32)
        reste = np.exp(cumul[fins - 1] - cumul[debuts] + log[debuts]
                       ).astype(np.float32)
    somme = np.add.reduceat(src[tri] * voile[:, None], debuts, axis=0)
    ici = pix[debuts]
    dessous = octets[ici].astype(np.float32)
    octets[ici] = (somme + dessous * reste[:, None] + 0.5).clip(0, 255
                                                                ).astype(np.uint8)


class Raster:
    """Une image en cours: la couleur (uint32, ARGB prémultiplié, 0 hors de la
    pièce) et la profondeur de chaque pixel, à plat."""

    def __init__(self, largeur: int, hauteur: int):
        self.largeur = max(1, int(largeur))
        self.hauteur = max(1, int(hauteur))
        n = self.largeur * self.hauteur
        self.couleur = np.zeros(n, dtype=np.uint32)
        self.z = np.full(n, np.inf, dtype=np.float32)
        self._rampe = np.arange(self.largeur, dtype=np.float32)
        #: les faces transparentes en attente: elles se composent ensemble,
        #: après toutes les opaques
        self._voiles = []
        #: la face transparente la plus proche, s'il y en a (les traits s'en
        #: servent)
        self.z_devant = None

    def triangles(self, x, y, d, rgb, alpha) -> None:
        """Des triangles: `x`, `y` (pixels de cette image), `d` (plus petit:
        plus proche), de forme (3, N): un tableau par sommet; `rgb` (N, 3) et
        `alpha` (N) de 0 à 255. Les opaques passent de suite, les transparents
        attendent `composer`."""
        n = len(rgb)
        if not n:
            return
        alpha = np.asarray(alpha)
        opaques = alpha >= 255
        if opaques.all():
            self._opaques(x, y, d, rgb)
            return
        if opaques.any():
            self._opaques(x[:, opaques], y[:, opaques], d[:, opaques],
                          rgb[opaques])
        voiles = np.flatnonzero((alpha > 0) & ~opaques)
        if len(voiles):
            self._voiles.append((x[:, voiles], y[:, voiles], d[:, voiles],
                                 rgb[voiles], alpha[voiles]))

    def composer(self) -> None:
        """Les faces transparentes en attente, de la plus loin à la plus
        proche, pixel par pixel; une face derrière une opaque ne compte pas."""
        if not self._voiles:
            return
        morceaux = self._voiles
        self._voiles = []
        self._transparents(*(np.concatenate([m[k] for m in morceaux],
                                            axis=1 if k < 3 else 0)
                             for k in range(5)))

    def _opaques(self, x, y, d, rgb) -> None:
        n = len(rgb)
        if n > TRIANGLES_PAR_PAQUET:
            for a in range(0, n, TRIANGLES_PAR_PAQUET):
                b = a + TRIANGLES_PAR_PAQUET
                self._paquet(x[:, a:b], y[:, a:b], d[:, a:b], rgb[a:b])
        else:
            self._paquet(x, y, d, rgb)

    def _paquet(self, x, y, d, rgb) -> None:
        s = _Scene(x, y, d, self.largeur, self.hauteur)
        if s.vide:
            return
        c = rgb[s.origine].astype(np.uint32)
        pixel = ((np.uint32(255) << 24) | (c[:, 0] << 16) | (c[:, 1] << 8)
                 | c[:, 2])
        rang_de = np.empty(len(rgb), dtype=np.int64)
        rang_de[s.origine] = np.arange(len(s.origine))
        z = self.z
        couleur = self.couleur
        for haut, bas in s.bandes():
            t = s.lignes(haut, bas, 1)
            if t is None:
                continue
            couleurs = pixel[rang_de[t.origine]]
            for a, b in t.lots():
                e = t.tranches(a, b, self.largeur)
                if e is None:
                    continue
                premier, long_, depart, gx, rang = e
                longues = (long_ >= LIGNE_LONGUE) & ~t.fin[rang]
                if longues.any():
                    self._lignes_longues(premier[longues], long_[longues],
                                         depart[longues], gx[longues],
                                         couleurs[rang[longues]])
                    courtes = ~longues
                    premier, long_, depart, gx, rang = (
                        premier[courtes], long_[courtes], depart[courtes],
                        gx[courtes], rang[courtes])
                    if not len(premier):
                        continue
                pix, tri, prof = t.pixels(premier, long_, depart, gx, rang)
                vus = prof < z[pix]
                pix, tri, prof = pix[vus], tri[vus], prof[vus]
                np.minimum.at(z, pix, prof)
                gagne = prof == z[pix]
                couleur[pix[gagne]] = couleurs[tri[gagne]]

    def _lignes_longues(self, premier, long_, depart, gx, couleurs) -> None:
        """Une boucle par ligne, chaque ligne d'un bloc: au-delà de quelques
        centaines de pixels, le travail sur les pixels l'emporte sur l'appel,
        et il est bien moins cher. Les faces qui remplissent l'écran passent
        ici."""
        z = self.z
        couleur = self.couleur
        rampe = self._rampe
        for p, n, d0, g, c in zip(premier.tolist(), long_.tolist(),
                                  depart.tolist(), gx.tolist(), couleurs):
            q = p + n
            zone = z[p:q]
            prof = rampe[:n] * g + d0
            gagne = prof < zone
            np.copyto(zone, prof, where=gagne)
            np.copyto(couleur[p:q], c, where=gagne)

    def _transparents(self, x, y, d, rgb, alpha) -> None:
        s = _Scene(x, y, d, self.largeur, self.hauteur)
        if s.vide:
            return
        a = alpha[s.origine].astype(np.float32) / 255.0
        c = rgb[s.origine].astype(np.float32)
        # BGRA prémultiplié, 0-255: l'ordre des octets d'un pixel
        src = np.column_stack([c[:, 2] * a, c[:, 1] * a, c[:, 0] * a, a * 255.0])
        journal = np.log1p(-a.astype(np.float64))
        alpha_unique = float(a[0]) if (a == a[0]).all() else None
        rang_de = np.empty(len(rgb), dtype=np.int64)
        rang_de[s.origine] = np.arange(len(s.origine))
        if self.z_devant is None:
            self.z_devant = np.full(len(self.z), np.inf, dtype=np.float32)
        octets = self.couleur.view(np.uint8).reshape(-1, 4)
        bits_pix = max(1, int(np.ceil(np.log2(self.largeur * self.hauteur))))
        bits_tri = max(1, int(np.ceil(np.log2(len(s.origine) + 1))))
        bits_d = min(24, 64 - bits_pix - bits_tri)
        decale_pix = np.uint64(bits_d + bits_tri)
        decale_d = np.uint64(bits_tri)
        masque_tri = np.uint64((1 << bits_tri) - 1)
        plafond_d = float((1 << bits_d) - 1)
        z = self.z
        z_devant = self.z_devant
        for haut, bas in s.bandes():
            # (par tranches de lignes, jamais par paquets de triangles: les
            # couches d'un pixel se composent toutes ensemble)
            for t in s.sous_bandes(haut, bas):
                rangs = rang_de[t.origine]
                dn, dm = float(t.dmin.min()), float(t.dmax.max())
                echelle = plafond_d / max(dm - dn, 1e-12)
                e = t.tranches(0, t.n, self.largeur)
                if e is None:
                    continue
                pix, tri, prof = t.pixels(*e)
                vus = prof < z[pix]
                pix, tri, prof = pix[vus], rangs[tri[vus]], prof[vus]
                if not len(pix):
                    continue
                np.minimum.at(z_devant, pix, prof)
                # une seule clé (pixel, le plus loin d'abord, triangle): np.sort
                # sur des entiers de 64 bits va bien plus vite qu'un lexsort
                rang_d = np.clip((dm - prof) * echelle, 0.0, plafond_d
                                 ).astype(np.uint64)
                cle = ((pix.astype(np.uint64) << decale_pix)
                       | (rang_d << decale_d) | tri.astype(np.uint64))
                cle.sort()
                pix = (cle >> decale_pix).astype(np.int64)
                tri = (cle & masque_tri).astype(np.int64)
                _composer(octets, pix, tri, src, journal, alpha_unique)

    def traits(self, x, y, d, debuts, rgba, epaisseur: float = 1.0,
               lisse: bool = True, biais: float = 0.0) -> None:
        """Les polylignes (x, y, d)[debuts[i]:debuts[i+1]], moins ce que les
        faces opaques cachent. `rgba` de 0 à 255, `epaisseur` en pixels de
        cette image, `lisse`: bords lissés. Un trait qui borde une face a à peu
        près sa profondeur: il est vu si, à `biais` près, il n'est pas derrière
        au moins un des pixels voisins."""
        if len(x) < 2:
            return
        dx = np.diff(x)
        dy = np.diff(y)
        dd = np.diff(d)
        relie = np.ones(len(dx), dtype=bool)
        relie[np.asarray(debuts)[1:-1] - 1] = False
        qui = np.flatnonzero(relie)
        x0, y0, dx, dy, d0, dd = (x[qui], y[qui], dx[qui], dy[qui], d[qui],
                                  dd[qui])
        t0, t1 = segments_visibles(x0, y0, dx, dy, self.largeur, self.hauteur)
        vus = t1 >= t0
        if not vus.any():
            return
        x0, y0, dx, dy, d0, dd, t0, t1 = (a[vus] for a in (
            x0, y0, dx, dy, d0, dd, t0, t1))
        grand = np.maximum(np.abs(dx), np.abs(dy))
        n = np.ceil(grand * (t1 - t0)).astype(np.int64) + 1
        r = np.repeat(np.arange(len(n)), n)
        k = np.arange(int(n.sum())) - np.repeat(np.cumsum(n) - n, n)
        # (une étape par pixel sur le grand axe)
        t = t0[r] + (t1 - t0)[r] * (k / np.maximum(n[r] - 1, 1))
        xs = x0[r] + t * dx[r]
        ys = y0[r] + t * dy[r]
        ds = (d0[r] + t * dd[r]).astype(np.float32)
        ix = np.floor(xs).astype(np.int64)
        iy = np.floor(ys).astype(np.int64)
        dedans = np.flatnonzero((ix >= 0) & (ix < self.largeur)
                                & (iy >= 0) & (iy < self.hauteur))
        if not len(dedans):
            return
        xs, ys, ds, ix, iy, r = (a[dedans] for a in (xs, ys, ds, ix, iy, r))
        L = self.largeur
        ici = iy * L + ix
        autour = (ici, iy * L + np.maximum(ix - 1, 0),
                  iy * L + np.minimum(ix + 1, L - 1),
                  np.maximum(iy - 1, 0) * L + ix,
                  np.minimum(iy + 1, self.hauteur - 1) * L + ix)
        vu = np.flatnonzero(ds - biais <= _plus_loin(self.z, autour))
        if not len(vu):
            return
        xs, ys, ds, ix, iy, r, ici = (a[vu] for a in (xs, ys, ds, ix, iy, r, ici))
        force = np.ones(len(vu), dtype=np.float32)
        if self.z_devant is not None:
            devant = _plus_loin(self.z_devant, tuple(a[vu] for a in autour))
            force[ds - biais > devant] = TRAIT_DERRIERE
        couvert = np.zeros(len(self.z), dtype=np.float32)
        if not lisse:
            np.maximum.at(couvert, ici, force)
        else:
            # le trait couvre les pixels selon leur distance à son axe, sur le
            # petit axe: le lissage de deux pixels, généralisé à toute épaisseur
            horizontal = (np.abs(dx) >= np.abs(dy))[r]
            mineur = np.where(horizontal, ys, xs) - 0.5
            base = np.floor(mineur)
            frac = mineur - base
            base = base.astype(np.int64)
            demi = (float(epaisseur) + 1.0) / 2.0
            rayon = int(np.ceil(demi))
            limite = np.where(horizontal, self.hauteur, L)
            for ecart in range(1 - rayon, rayon + 1):
                c = np.clip(demi - np.abs(frac - ecart), 0.0, 1.0)
                m = base + ecart
                ok = (c > 0.0) & (m >= 0) & (m < limite)
                pixels = np.where(horizontal, m * L + ix, iy * L + m)[ok]
                np.maximum.at(couvert, pixels,
                              (c[ok] * force[ok]).astype(np.float32))
        touche = np.flatnonzero(couvert)
        if not len(touche):
            return
        c = couvert[touche][:, None]
        a = float(rgba[3]) / 255.0
        src = np.array([rgba[2] * a, rgba[1] * a, rgba[0] * a, a * 255.0],
                       dtype=np.float32)
        octets = self.couleur.view(np.uint8).reshape(-1, 4)
        dessous = octets[touche].astype(np.float32)
        octets[touche] = (dessous * (1.0 - a * c) + src * c + 0.5).clip(
            0, 255).astype(np.uint8)
