"""
Estimation GROSSIÈRE du temps d'usinage par opération.
Basée sur les distances de coupe et les avances outil (mm/min).
Les déplacements rapides, changements d'outil et temporisations ne
sont pas comptés — les valeurs sont des ordres de grandeur (~).

Retourne None quand l'estimation n'est pas possible (pas d'outil,
type d'opération non modélisé...).
"""

import math
from typing import Optional

# Pas de filetage métrique (mm/tour)
THREAD_PITCH = {
    "M2.5": 0.45, "M3": 0.5, "M4": 0.7, "M5": 0.8,
    "M6": 1.0, "M8": 1.25, "M10": 1.5,
}

THREAD_DIAM = {
    "M2.5": 2.5, "M3": 3.0, "M4": 4.0, "M5": 5.0,
    "M6": 6.0, "M8": 8.0, "M10": 10.0,
}


def _f(params, key, default=0.0) -> float:
    try:
        return float(params.get(key, default) or default)
    except (TypeError, ValueError):
        return default


def _repeat_factor(params) -> int:
    from src.core import repetition
    return repetition.compte(params)


def _n_points(op) -> int:
    pts = getattr(op, 'points', None)
    return max(1, len(pts)) if pts else 1


def estimate_op_seconds(op, tool) -> Optional[float]:
    """Estime le temps de coupe d'une opération en secondes."""
    if not getattr(op, 'enabled', True):
        return 0.0
    op_type = getattr(op, 'operation_type', '')
    params = getattr(op, 'params', {}) or {}

    feed_fin = float(getattr(tool, 'feed_finishing', 0) or 0)
    feed_plunge = float(getattr(tool, 'feed_plunge', 0) or 0)
    feed_rough = float(getattr(tool, 'feed_roughing', 0) or 0) or feed_fin
    tool_d = float(getattr(tool, 'diameter', 0) or 0)

    depth = _f(params, 'depth')
    infeed = max(_f(params, 'infeed_z', 1.0), 0.05)
    n = _n_points(op) * _repeat_factor(params)

    def minutes_to_sec(dist_mm: float, feed: float) -> Optional[float]:
        if feed <= 0:
            return None
        return dist_mm / feed * 60.0

    if op_type == "percage_foret":
        # Plongée + débourrage (~x1.4)
        t = minutes_to_sec(depth * 1.4, feed_plunge)
        return t * n if t is not None else None

    if op_type == "percage_fraise":
        # Hélice: (profondeur/passe) cercles de circonférence π·d
        d = _f(params, 'diameter', 4.0)
        passes = math.ceil(depth / infeed) if depth > 0 else 1
        t = minutes_to_sec(passes * math.pi * d, feed_rough)
        return t * n if t is not None else None

    if op_type in ("taraudage", "taraudage_brut"):
        # Hélice de filetage: (profondeur/pas) tours de π·d
        holes_per_point = 2 if op_type == "taraudage_brut" else 1
        total = 0.0
        pts = getattr(op, 'points', None) or [{}]
        for pt in pts:
            tt = pt.get('thread_type', params.get('thread_type', 'M4'))
            pitch = THREAD_PITCH.get(tt, 0.7)
            d = THREAD_DIAM.get(tt, 4.0)
            pt_depth = pt.get('depth')
            dz = float(pt_depth) if pt_depth is not None else depth
            turns = dz / pitch if pitch > 0 else 0
            t = minutes_to_sec(turns * math.pi * d, feed_fin)
            if t is None:
                return None
            total += t * holes_per_point
        return total * _repeat_factor(params)

    if op_type in ("filetage_special", "taraudage_rigide"):
        # filet fraisé: (profondeur/pas) tours de π·d; taraud: descente
        # et remontée à l'avance du filet
        pitch = _f(params, 'pitch', 1.0)
        total = 0.0
        for pt in (getattr(op, 'points', None) or [{}]):
            dz = float(pt['depth']) if pt.get('depth') is not None \
                else depth
            if op_type == "filetage_special":
                t = minutes_to_sec(dz / pitch * math.pi * _f(
                    params, 'nominal_diameter', 6.0), feed_fin)
            else:
                t = minutes_to_sec(2 * dz, _f(params, 'thread_feed', 300.0))
            if t is None:
                return None
            total += t
        return total * _repeat_factor(params)

    if op_type == "decoupe_rectangle":
        perim = 2 * (_f(params, 'width_x', 10) + _f(params, 'width_y', 10))
        passes = math.ceil(depth / infeed) if depth > 0 else 1
        t = minutes_to_sec(passes * perim, feed_fin)
        return t * n if t is not None else None

    if op_type == "decoupe_cercle":
        perim = math.pi * _f(params, 'diameter', 10)
        passes = math.ceil(depth / infeed) if depth > 0 else 1
        t = minutes_to_sec(passes * perim, feed_fin)
        return t * n if t is not None else None

    if op_type in ("poche_rectangle", "surfacage_rectangle",
                   "surfacage_cercle", "poche_cercle"):
        # Longueur ≈ aire / (diamètre outil × recouvrement)
        if tool_d <= 0:
            return None
        step = _f(params, 'stepover', 40) / 100.0
        if step <= 0:
            step = 0.4
        if op_type in ("surfacage_cercle", "poche_cercle"):
            d = _f(params, 'diameter', 20)
            area = math.pi * (d / 2) ** 2
        else:
            area = _f(params, 'width_x', 20) * _f(params, 'width_y', 20)
        passes = math.ceil(depth / infeed) if depth > 0 else 1
        length = area / (tool_d * step)
        t = minutes_to_sec(passes * length, feed_rough)
        return t * n if t is not None else None

    if op_type == "helice":
        # (profondeur / pas) tours de π·d, un tour plein au fond
        d = _f(params, 'diameter', 10)
        tours = depth / max(_f(params, 'pitch', 0.5), 0.01)
        if params.get('full_circle', True):
            tours += 1
        t = minutes_to_sec(tours * math.pi * d, feed_rough)
        return t * n if t is not None else None

    # Ops sans temps de coupe estimable / négligeable
    if op_type in ("decalage_origine", "dialogue_operateur",
                   "appel_outil", "miroir", "retablir_miroir",
                   "palpage_z", "prechauffage_broche",
                   "rotation_repere", "message_operateur",
                   "palpage_coin", "mesure_outil"):
        return 0.0

    return None  # inconnu (gravure, bpm, appel_programme, custom...)


def estimate_program_seconds(program, tool_library):
    """Retourne (total_secondes, nb_ops_estimées, nb_ops_inconnues).
    Le total ne couvre que les opérations estimables."""
    total = 0.0
    known = 0
    unknown = 0
    for op in program.operations:
        if not op.enabled:
            continue
        tool = tool_library.get_tool(op.tool_id) if op.tool_id else None
        t = estimate_op_seconds(op, tool)
        if t is None:
            unknown += 1
        else:
            total += t
            if t > 0:
                known += 1
    return total, known, unknown


def format_duration(seconds: float) -> str:
    """'~45 s', '~3 min 20', '~1 h 05'."""
    seconds = max(0, seconds)
    if seconds < 60:
        return f"~{seconds:.0f} s"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"~{minutes} min {int(seconds % 60):02d}"
    return f"~{minutes // 60} h {minutes % 60:02d}"
