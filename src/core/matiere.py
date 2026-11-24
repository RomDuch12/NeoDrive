"""État de la matière restante, PROFONDEUR COMPRISE.

Le suivi 2D d'une gamme ne retient qu'une empreinte: dès qu'un étage a
balayé une zone, elle passe pour finie. Sur une pièce à gradins c'est
faux — un étage qui a dégagé à 1 mm laisse toute la matière entre
1 mm et la cote d'un étage plus profond, et l'étage suivant s'entendait
répondre « rien à reprendre ».

Ici, l'état retient pour chaque région la cote DÉJÀ ATTEINTE. Un étage
qui vise `p` ne reprend que ce qui n'est pas encore descendu à `p`.

Les profondeurs sont POSITIVES et comptées sous la surface, comme
`gamme.profondeur_visee`: 0 = brut intact, 3 = trois millimètres
enlevés.
"""

from typing import List, Tuple

#: deux cotes plus proches que ça sont la même
EPS = 1e-6


def _shapely():
    from src.core import vcarve
    return vcarve._shapely()


def _vide():
    geo, _ops = _shapely()
    return geo.Polygon()


class EtatMatiere:
    """La matière qu'il reste, région par région, avec sa cote atteinte.

    Invariant: les régions ne se recouvrent pas, et leur union vaut
    l'empreinte de départ. Une région à la cote `p` veut dire « ici, on
    est descendu à p » — il reste donc de la matière sous p.
    """

    def __init__(self, forme, profondeur: float = 0.0):
        """`forme`: l'empreinte du brut à usiner (polygone shapely)."""
        self._regions: List[Tuple[object, float]] = []
        if forme is not None and not forme.is_empty:
            self._regions.append((forme, float(profondeur)))

    # ──── Lecture ────

    @property
    def regions(self) -> List[Tuple[object, float]]:
        """[(région, cote atteinte)], les vides écartés."""
        return [(g, p) for g, p in self._regions
                if g is not None and not g.is_empty]

    def profondeur_max(self) -> float:
        """La cote la plus profonde atteinte, 0 si rien n'est usiné."""
        return max([p for _g, p in self.regions] or [0.0])

    def zone_a_reprendre(self, profondeur: float):
        """La zone qui n'est PAS encore descendue à `profondeur`.

        C'est ce qu'un étage visant cette cote a réellement à faire.
        Rend None quand il n'y a plus rien à reprendre."""
        geo, ops = _shapely()
        morceaux = [g for g, p in self.regions
                    if p < float(profondeur) - EPS]
        if not morceaux:
            return None
        zone = ops.unary_union(morceaux)
        return None if zone.is_empty else zone

    def reste_surface(self, profondeur: float) -> float:
        """L'aire (mm²) qui n'est pas descendue à `profondeur`."""
        zone = self.zone_a_reprendre(profondeur)
        return 0.0 if zone is None else float(zone.area)

    def reste_volume(self, profondeur: float) -> float:
        """Le volume (mm³) qu'il reste à enlever pour que TOUT soit à
        `profondeur`: la somme, région par région, de l'aire par la
        hauteur qui manque."""
        cible = float(profondeur)
        total = 0.0
        for g, p in self.regions:
            manque = cible - p
            if manque > EPS:
                total += float(g.area) * manque
        return total

    # ──── Écriture ────

    def enlever(self, zone, profondeur: float) -> float:
        """Descend `zone` à la cote `profondeur`. Rend le volume enlevé.

        Une région déjà plus profonde n'est pas remontée: on garde la
        cote la plus profonde des deux."""
        if zone is None or zone.is_empty:
            return 0.0
        cible = float(profondeur)
        neuves: List[Tuple[object, float]] = []
        volume = 0.0
        for g, p in self._regions:
            if g is None or g.is_empty:
                continue
            touche = g.intersection(zone)
            if touche.is_empty:
                neuves.append((g, p))
                continue
            dehors = g.difference(zone)
            if not dehors.is_empty:
                neuves.append((dehors, p))
            # la part touchée descend, sans jamais remonter
            atteinte = max(p, cible)
            volume += float(touche.area) * max(0.0, atteinte - p)
            neuves.append((touche, atteinte))
        self._regions = neuves
        return volume

    def copie(self) -> "EtatMatiere":
        clone = EtatMatiere(None)
        clone._regions = list(self._regions)
        return clone
