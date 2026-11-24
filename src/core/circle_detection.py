"""
Module de détection de cercles depuis DXF et algorithme de plus court chemin.
- Filtre les cercles par diamètre avec tolérance
- Propose l'ébavurage (Pz = rayon + 0.05)
- Algorithme du plus proche voisin (nearest neighbor TSP) pour le parcours
"""

import math
from typing import List, Dict, Tuple


def filter_by_circularity(centers: List[Dict],
                           threshold_pct: float = 50.0) -> List[Dict]:
    """
    Filtre les centres par score de circularité.

    Args:
        centers: liste de dicts {x, y, radius, circularity, entity_type}
        threshold_pct: seuil de circularité en pourcentage (0-100)
            0% = tout, 100% = cercles parfaits uniquement

    Returns:
        Liste filtrée de centres
    """
    threshold = threshold_pct / 100.0
    return [c for c in centers if c.get('circularity', 0) >= threshold]


def deduplicate_circles(centers: List[Dict],
                        tolerance: float = 0.01) -> List[Dict]:
    """
    Supprime les doublons: deux centres sont considérés identiques
    si la distance entre eux est < tolerance mm.

    Args:
        centers: liste de dicts {x, y, radius, ...}
        tolerance: distance minimale en mm (défaut 0.01)

    Returns:
        Liste dédupliquée (conserve le premier trouvé)
    """
    result = []
    for c in centers:
        is_dup = False
        for existing in result:
            dx = c['x'] - existing['x']
            dy = c['y'] - existing['y']
            dist = math.sqrt(dx * dx + dy * dy)
            if dist < tolerance:
                is_dup = True
                break
        if not is_dup:
            result.append(c)
    return result


def detect_collisions(centers: List[Dict],
                      min_distance: float = 1.0) -> List[Tuple[int, int, float]]:
    """
    Détecte les paires de centres trop proches (collision potentielle).

    Args:
        centers: liste de dicts {x, y, ...}
        min_distance: distance minimale acceptable en mm

    Returns:
        Liste de tuples (index_a, index_b, distance) pour les collisions
    """
    collisions = []
    n = len(centers)
    for i in range(n):
        for j in range(i + 1, n):
            dx = centers[i]['x'] - centers[j]['x']
            dy = centers[i]['y'] - centers[j]['y']
            dist = math.sqrt(dx * dx + dy * dy)
            if dist < min_distance:
                collisions.append((i, j, dist))
    return collisions


def filter_circles_by_diameter(circles: List[Dict],
                                target_diameter: float,
                                tolerance_pct: float = 10.0
                                ) -> List[Dict]:
    """
    Filtre les cercles détectés par diamètre cible avec tolérance.

    Args:
        circles: liste de dicts {x, y, radius}
        target_diameter: diamètre cible en mm
        tolerance_pct: tolérance en pourcentage (0-100)

    Returns:
        Liste filtrée de cercles correspondants
    """
    target_radius = target_diameter / 2.0
    tol = target_radius * tolerance_pct / 100.0
    return [
        c for c in circles
        if abs(c['radius'] - target_radius) <= tol
    ]


def compute_ebav_depth(circle: Dict, offset: float = 0.05) -> float:
    """
    Calcule la profondeur d'ébavurage: rayon + offset.

    Args:
        circle: dict {x, y, radius}
        offset: offset en mm (défaut 0.05)

    Returns:
        Profondeur Pz pour l'ébavurage
    """
    return circle['radius'] + offset


def nearest_neighbor_path(points: List[Dict],
                          start_index: int = 0
                          ) -> Tuple[List[Dict], float]:
    """
    Algorithme du plus proche voisin pour trouver un parcours court.
    Heuristique TSP simple.

    Args:
        points: liste de dicts {x, y, ...}
        start_index: index du point de départ

    Returns:
        (chemin ordonné, distance totale)
    """
    if not points:
        return [], 0.0

    n = len(points)
    if n == 1:
        return points.copy(), 0.0

    remaining = list(range(n))
    path = []
    total_dist = 0.0

    current = start_index
    remaining.remove(current)
    path.append(points[current])

    while remaining:
        cx, cy = points[current]['x'], points[current]['y']
        best_idx = None
        best_dist = float('inf')

        for idx in remaining:
            px, py = points[idx]['x'], points[idx]['y']
            dist = math.sqrt((px - cx) ** 2 + (py - cy) ** 2)
            if dist < best_dist:
                best_dist = dist
                best_idx = idx

        total_dist += best_dist
        current = best_idx
        remaining.remove(current)
        path.append(points[current])

    return path, total_dist


def optimize_path_from_origin(points: List[Dict]) -> Tuple[List[Dict], float]:
    """
    Trouve le meilleur point de départ proche de l'origine (0,0).

    Args:
        points: liste de dicts {x, y, ...}

    Returns:
        (chemin optimisé, distance totale)
    """
    if not points:
        return [], 0.0

    # Trouver le point le plus proche de l'origine
    best_start = 0
    best_dist_to_origin = float('inf')
    for i, p in enumerate(points):
        d = math.sqrt(p['x'] ** 2 + p['y'] ** 2)
        if d < best_dist_to_origin:
            best_dist_to_origin = d
            best_start = i

    return nearest_neighbor_path(points, best_start)


def generate_drill_operations(circles: List[Dict],
                               operation_type: str = "percage_fraise",
                               add_ebav: bool = True,
                               ebav_offset: float = 0.05
                               ) -> List[Dict]:
    """
    Génère une liste d'opérations de perçage/taraudage à partir de cercles,
    optimisée par distance de parcours.

    Args:
        circles: cercles filtrés [{x, y, radius}]
        operation_type: type d'opération
        add_ebav: ajouter une opération d'ébavurage après chaque perçage
        ebav_offset: offset pour le calcul Pz ébavurage

    Returns:
        Liste de dicts {operation_type, x, y, params} ordonnés
    """
    if not circles:
        return []

    # Optimiser le parcours
    ordered, total_dist = optimize_path_from_origin(circles)

    operations = []
    for circle in ordered:
        # Opération principale
        op = {
            'operation_type': operation_type,
            'x': circle['x'],
            'y': circle['y'],
            'diameter': circle['radius'] * 2,
        }
        operations.append(op)

        # Ébavurage
        if add_ebav:
            ebav = {
                'operation_type': 'percage_fraise',
                'x': circle['x'],
                'y': circle['y'],
                'diameter': circle['radius'] * 2 + ebav_offset * 2,
                'depth': compute_ebav_depth(circle, ebav_offset),
                'is_ebav': True,
            }
            operations.append(ebav)

    return operations
