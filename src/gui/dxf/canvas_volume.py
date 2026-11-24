"""Le dessin et les opérations du canvas, en volume (vue 3D).

Le canvas 2D aplatit tout sur XY. Ici chaque chose reprend sa cote:

- le DESSIN: un calque « STEP Pz 5 » à Z -5, le reste à Z 0;
- les OPÉRATIONS: leur empreinte au fond (rectangles, cercles, à leur
  profondeur), le haut en trait léger, les perçages en descente
  verticale, les taraudages en hélice au pas du filet; les gravures
  et évidements par leurs vraies passes (chaque point à sa
  profondeur), les séquences et blocs SimPl par leurs mouvements;
- la PIÈCE STEP importée: son fichier, et le décalage que le dessin a
  subi depuis l'import (centrage, déplacement) — la pièce suit.

Tout est en coordonnées machine: X, Y comme le programme, Z = 0 au
dessus de la pièce, négatif dans la matière.
"""

import math
import re
from collections import OrderedDict

import numpy as np
from PySide6.QtGui import QPainterPath
from PySide6.QtWidgets import (QGraphicsItemGroup, QGraphicsLineItem,
                               QGraphicsEllipseItem, QGraphicsRectItem)

#: pas des filets métriques (mm) — ceux de la simulation des cycles
from src.core.sim_cycles import PAS_FILET  # noqa: E402

#: clés de profondeur des formulaires, dans l'ordre où on les cherche
CLES_PROFONDEUR = ('depth', 'profondeur', 'profondeur_max', 'tap_depth',
                   'cbore_depth')

_PZ_CALQUE = re.compile(r"STEP Pz\s+(-?[\d.]+)")


def profondeur(op, pt=None) -> float:
    """La profondeur usinée (positive, mm): celle du point s'il en a
    une, sinon celle du formulaire; 0 si rien ne la dit."""
    for source, cles in ((pt or {}, ('depth',)),
                         (getattr(op, 'params', {}) or {}, CLES_PROFONDEUR)):
        for cle in cles:
            v = source.get(cle)
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
            if v > 0:
                return v
    return 0.0


def _decalage_source(src) -> tuple:
    """Le décalage machine qu'une pièce a subi depuis son import (son
    entité témoin a bougé avec le dessin)."""
    dx = dy = 0.0
    repere = src.get('repere')
    try:
        if repere is not None and repere.scene() is not None:
            d = repere.pos() - src['pos0']
            dx, dy = d.x(), -d.y()
    except RuntimeError:
        pass
    return (dx, dy)


def source_3d(canvas):
    """La pièce STEP ACTIVE du dessin: {'chemin', 'decalage': (dx,
    dy)} — le décalage machine que le dessin a subi depuis l'import —
    ou None si le dessin ne vient pas d'un STEP."""
    src = getattr(canvas, '_source_3d', None)
    if not src:
        return None
    return {'chemin': src['chemin'], 'decalage': _decalage_source(src)}


def sources_3d(canvas) -> list:
    """Toutes les pièces 3D du dessin, dans l'ordre des onglets:
    [{'cle', 'nom', 'chemin', 'decalage', 'visible', 'active'}]."""
    actif = getattr(canvas, '_source_3d', None)
    sortie = []
    for imp in getattr(canvas, '_imports_dxf', []) or []:
        src = imp.get('source_3d')
        if not src:
            continue
        sortie.append({'cle': imp['cle'], 'nom': imp.get('nom', ''),
                       'chemin': src['chemin'],
                       'decalage': _decalage_source(src),
                       'visible': bool(imp.get('visible', True)),
                       'active': src is actif})
    return sortie


def _chemin_item(item):
    """Le tracé d'une entité, en coordonnées de scène."""
    chemin = None
    if hasattr(item, 'path'):
        try:
            chemin = item.path()
        except (TypeError, RuntimeError):
            chemin = None
    if chemin is None:
        chemin = QPainterPath()
        if isinstance(item, QGraphicsLineItem):
            ligne = item.line()
            chemin.moveTo(ligne.p1())
            chemin.lineTo(ligne.p2())
        elif isinstance(item, QGraphicsEllipseItem):
            chemin.addEllipse(item.rect())
        elif isinstance(item, QGraphicsRectItem):
            chemin.addRect(item.rect())
        else:
            return None
    return item.sceneTransform().map(chemin)


def _polylignes(chemin, z):
    out = []
    for poly in chemin.toSubpathPolygons():
        if poly.size() < 2:
            continue
        out.append(np.array([(p.x(), -p.y(), z) for p in poly]))
    return out


def dessin_3d(canvas) -> list:
    """Les tracés visibles du dessin: [(points (N,3), couleur hex)]."""
    sortie = []

    def _poser(item, z, couleur):
        if isinstance(item, QGraphicsItemGroup):
            for enfant in item.childItems():
                _poser(enfant, z, couleur)
            return
        chemin = _chemin_item(item)
        if chemin is None:
            return
        if couleur is None:
            try:
                couleur = item.pen().color().name()
            except (AttributeError, RuntimeError):
                couleur = "#cdd6f4"
        for pts in _polylignes(chemin, z):
            sortie.append((pts, couleur))

    for item in list(getattr(canvas, '_dxf_items', [])):
        try:
            if not item.isVisible():
                continue
            calque = str(item.data(0) or "")
        except RuntimeError:
            continue
        m = _PZ_CALQUE.search(calque)
        z = -float(m.group(1)) if m else 0.0
        _poser(item, z, None)
    return sortie


def _contour_forme(forme, x, y, n=48):
    """Le contour d'une forme du canvas (('rect', w, h, r) ou
    ('circle', d)) centré en (x, y), en XY."""
    if forme[0] == 'circle':
        r = forme[1] / 2.0
        t = np.linspace(0, 2 * math.pi, n + 1)
        return np.column_stack([x + r * np.cos(t), y + r * np.sin(t)])
    w, h = forme[1], forme[2]
    r = min(forme[3] if len(forme) > 3 else 0.0, w / 2.0, h / 2.0)
    if r <= 1e-6:
        return np.array([(x - w / 2, y - h / 2), (x + w / 2, y - h / 2),
                         (x + w / 2, y + h / 2), (x - w / 2, y + h / 2),
                         (x - w / 2, y - h / 2)])
    pts = []
    for cx, cy, a0 in ((x + w / 2 - r, y - h / 2 + r, -90),
                       (x + w / 2 - r, y + h / 2 - r, 0),
                       (x - w / 2 + r, y + h / 2 - r, 90),
                       (x - w / 2 + r, y - h / 2 + r, 180)):
        for a in np.linspace(math.radians(a0), math.radians(a0 + 90), 7):
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    pts.append(pts[0])
    return np.array(pts)


def _a_z(xy, z):
    return np.column_stack([xy, np.full(len(xy), float(z))])


def _segments_sim3d(res, couleur, dx=0.0, dy=0.0):
    """Le parcours de sim3d en polylignes: coupes à leur Z, le reste
    (avances dans l'air) en genre 'air'."""
    x = res.get('x') if res else None
    if x is None or len(x) < 2:
        return []
    P = np.column_stack([np.asarray(x, dtype=float) + dx,
                         np.asarray(res['y'], dtype=float) + dy,
                         np.asarray(res['z'], dtype=float)])
    return _segments_de(P, np.asarray(res['k']), couleur)


def _segments_de(P, k, couleur) -> list:
    """Les polylignes de sommets P (N, 3) de genres k."""
    from src.core import sim3d
    n = len(k)
    if n < 2:
        return []
    # le segment i va du sommet i-1 au sommet i, de genre k[i]: les
    # segments consécutifs d'un même genre font une polyligne
    debuts = np.concatenate(([1], np.flatnonzero(k[2:] != k[1:-1]) + 2))
    fins = np.concatenate((debuts[1:], [n]))
    out = []
    for i, j, genre in zip(debuts.tolist(), fins.tolist(),
                           k[debuts].tolist()):
        if genre == sim3d.COUPE:
            out.append((P[i - 1:j], couleur, 'coupe'))
        elif genre == sim3d.AIR:
            out.append((P[i - 1:j], couleur, 'air'))
    return out


#: les parcours déjà lus (`parcours_lu`), en sommets cumulés
SOMMETS_LUS_GARDES = 2_000_000
_parcours_lus = OrderedDict()


def parcours_lu(code: str, progression=None) -> dict:
    """`sim3d.parcours_3d(code)` en tableaux, gardé tant que ce code ne
    change pas. Chaque relecture du Canva 3D relisait toutes les lignes de
    tous les blocs importés (six blocs, 77 000 lignes: 0,6 s), pour le
    même résultat."""
    res = _parcours_lus.get(code)
    if res is not None:
        _parcours_lus.move_to_end(code)
        return res
    from src.core import sim3d
    lu = sim3d.parcours_3d(code, progression=progression)
    return _garder_parcours(code, {c: np.asarray(lu[c]) for c in 'xyzk'})


def _garder_parcours(code: str, res: dict) -> dict:
    _parcours_lus[code] = res
    total = sum(len(r['x']) for r in _parcours_lus.values())
    while total > SOMMETS_LUS_GARDES and len(_parcours_lus) > 1:
        _code, ancien = _parcours_lus.popitem(last=False)
        total -= len(ancien['x'])
    return res


#: les opérations dont le tracé se déduit de la simulation du programme
_TRACE_DEJA_SIMULE = ('bloc_simpl', 'sequence_datron')


def plages_des_traces(parcours) -> dict:
    """{id d'opération: [(premier sommet, fin)]} de celles que la simulation
    a déroulées entièrement. Son tracé est là, sans relire son code; une
    simulation arrêtée en route ne dit pas toute la dernière."""
    plages = (parcours or {}).get('plages_ops') or []
    if not plages:
        return {}
    n = len(parcours['x'])
    sortie = {}
    for k, (debut, oid) in enumerate(plages):
        fin = plages[k + 1][0] if k + 1 < len(plages) else n
        if oid is not None and fin > debut:
            # (le segment i vient du sommet i-1: l'approche est à elle)
            sortie.setdefault(oid, []).append((max(0, debut - 1), fin))
    if parcours.get('tronque'):
        derniere = next((p[1] for p in reversed(plages) if p[1] is not None),
                        None)
        sortie.pop(derniere, None)
    return sortie


def _codes_du_trace(op) -> list:
    """Les textes que le tracé d'une opération lit."""
    kind = getattr(op, 'operation_type', '')
    params = getattr(op, 'params', {}) or {}
    if kind == 'sequence_datron':
        from src.operations.sequence_datron import SequenceDatron
        codes = [SequenceDatron.build_sequence_block(params)]
    elif kind == 'bloc_simpl':
        from src.operations.bloc_simpl import BlocSimpl
        codes = [BlocSimpl.body(params), BlocSimpl.sequence_block(params)]
    else:
        return []
    return [c for c in codes if c and c.strip()]


#: au-delà de ces caractères à lire, les tracés se lisent dans la barre d'état
CARACTERES_SUIVIS = 2_000_000


def codes_a_lire(program, parcours=None) -> list:
    """Les textes que `formes_3d` devra lire: ni gardés, ni déduits de la
    simulation. Gros, ils se lisent d'abord dans la barre d'état (`lire_codes`):
    2,5 s sur 23 Mo, sans rien dire, la fenêtre figée."""
    from src.gui.panels.operations_panel import op_preview
    simules = plages_des_traces(parcours)
    codes = []
    for op in getattr(program, 'operations', []) or []:
        if not getattr(op, 'enabled', True) or not op_preview(op):
            continue
        if getattr(op, 'operation_type', '') in _TRACE_DEJA_SIMULE \
                and getattr(op, 'id', None) in simules:
            continue
        try:
            codes += [c for c in _codes_du_trace(op)
                      if c not in _parcours_lus]
        except Exception:
            continue
    return list(dict.fromkeys(codes))


def lire_codes(codes, progression=None) -> bool:
    """Lit ces textes (gardés pour `parcours_lu`). Rend vrai."""
    from src.core import vcarve
    total = max(1, sum(len(c) for c in codes))
    fait = 0
    for code in codes:
        parcours_lu(code, vcarve.sous_progression(
            progression, fait / total, (fait + len(code)) / total)
            if progression is not None else None)
        fait += len(code)
    return True


def renoncer_a_lire(codes) -> None:
    """La lecture est annulée: ces textes n'ont pas de tracé tant qu'ils ne
    changent pas (le parcours simulé, lui, reste)."""
    vide = {c: np.zeros(0) for c in 'xyzk'}
    for code in codes:
        if code not in _parcours_lus:
            _garder_parcours(code, vide)


#: couleur et longueur des repères dessinés (origine déplacée)
COULEUR_REPERE = "#f5c2e7"
LONGUEUR_REPERE = 6.0


def repere_3d(x: float, y: float, angle: float = 0.0) -> list:
    """Les flèches X, Y (et Z) d'un repère posé en (x, y, 0), tourné de
    `angle` degrés: [(points, couleur, 'axe')]."""
    a = math.radians(angle)
    L = LONGUEUR_REPERE
    sortie = []
    for ang in (a, a + math.pi / 2):
        fx, fy = x + L * math.cos(ang), y + L * math.sin(ang)
        sortie.append((np.array([(x, y, 0.0), (fx, fy, 0.0)]),
                       COULEUR_REPERE, 'axe'))
    sortie.append((np.array([(x, y, 0.0), (x, y, L * 0.6)]),
                   COULEUR_REPERE, 'axe'))
    return sortie


def formes_3d(canvas, program, scratch=None, par_op=None,
              parcours=None) -> list:
    """Les opérations visibles du programme, en volume:
    [(points (N,3), couleur hex, genre)] — genre 'coupe' (au fond),
    'surface' (le haut, Z 0), 'axe' (descente), 'air'. `par_op`: une liste
    qui reçoit (opération, morceaux) avant transparence et division, pour
    les réappliquer sans recalculer (`formes_affichees`). `parcours`: la
    simulation du programme: le tracé d'un bloc s'en déduit, sans relire
    son texte."""
    from src.gui.panels.operations_panel import op_preview
    simules = plages_des_traces(parcours)
    if simules:
        P_sim = np.column_stack([np.asarray(parcours[c], dtype=float)
                                 for c in 'xyz'])
        k_sim = np.asarray(parcours['k'])
    sortie = []
    shift = [0.0, 0.0]
    rot = 0.0
    lcs = {}
    for op in getattr(program, 'operations', []) or []:
        if not getattr(op, 'enabled', True):
            continue
        if getattr(op, 'operation_type', '') == "decalage_origine":
            p = getattr(op, 'params', {}) or {}
            try:
                dx = float(p.get('shift_x', 0.0) or 0.0)
                dy = float(p.get('shift_y', 0.0) or 0.0)
            except (TypeError, ValueError):
                dx = dy = 0.0
            a = math.radians(rot)
            shift[0] += dx * math.cos(a) - dy * math.sin(a)
            shift[1] += dx * math.sin(a) + dy * math.cos(a)
            lcs['base'] = None
            if op_preview(op):
                sortie += _repere_note(shift[0], shift[1], rot, par_op)
            continue
        if getattr(op, 'operation_type', '') == "repere_local":
            from src.operations.repere_local import RepereLocal
            shift[0], shift[1], rot = RepereLocal.appliquer(
                getattr(op, 'params', {}) or {}, shift, rot, lcs)
            if op_preview(op):
                sortie += _repere_note(shift[0], shift[1], rot, par_op)
            continue
        if getattr(op, 'operation_type', '') == "rotation_repere":
            from src.operations.rotation_repere import RotationRepere
            p = getattr(op, 'params', {}) or {}
            rot = (RotationRepere.angle(p) if RotationRepere.absolue(p)
                   else rot + RotationRepere.angle(p))
            lcs['base'] = None
            if op_preview(op):
                sortie += _repere_note(shift[0], shift[1], rot, par_op)
            continue
        if not op_preview(op):
            continue
        try:
            cle, libelle = canvas._op_tool_key(op)
            couleur = canvas.tool_color(cle, libelle).name()
        except Exception:
            couleur = "#89b4fa"
        try:
            if getattr(op, 'id', None) in simules and getattr(
                    op, 'operation_type', '') in _TRACE_DEJA_SIMULE:
                morceaux = []
                for a, b in simules[op.id]:
                    morceaux += _segments_de(P_sim[a:b], k_sim[a:b], couleur)
            elif rot:
                a = math.radians(rot)
                R = np.array([[math.cos(a), -math.sin(a)],
                              [math.sin(a), math.cos(a)]])
                morceaux = []
                for pts, c, g in _operation_3d(canvas, op, couleur,
                                               (0.0, 0.0), scratch):
                    pts = np.array(pts, dtype=float)
                    pts[:, :2] = pts[:, :2] @ R.T + shift
                    morceaux.append((pts, c, g))
            else:
                morceaux = _operation_3d(canvas, op, couleur, tuple(shift),
                                         scratch)
            sortie += _avec_affichage(op, morceaux)
            if par_op is not None:
                par_op.append((op, morceaux))
        except Exception:
            continue
    return sortie


def _repere_note(x, y, rot, par_op) -> list:
    """Un repère, noté aussi parmi les formes par opération."""
    morceaux = repere_3d(x, y, rot)
    if par_op is not None:
        par_op.append((None, morceaux))
    return morceaux


def formes_affichees(par_op) -> list:
    """Les formes [(opération, morceaux)] notées par `formes_3d`, à la
    transparence et à la division d'aujourd'hui: sans les recalculer."""
    sortie = []
    for op, morceaux in par_op or []:
        sortie += _avec_affichage(op, morceaux)
    return sortie


def _avec_affichage(op, morceaux) -> list:
    """Une ligne sur N et la transparence de l'opération (src.core.
    affichage): la division éclaircit, l'opacité devient un 4e terme
    (pts, couleur, genre, opacité)."""
    from src.core import affichage as af
    n = af.division(op)
    a = af.opacite(op)
    if n > 1:
        par_genre = {}
        for pts, c, g in morceaux:
            par_genre.setdefault((c, g), []).append(pts)
        morceaux = []
        for (c, g), liste in par_genre.items():
            for pts in af.decimer_polylignes(liste, n):
                pts = np.asarray(pts, dtype=float)
                if len(pts) >= 2:
                    morceaux.append((pts, c, g))
    if a < 1.0:
        return [(pts, c, g, a) for pts, c, g in morceaux]
    return list(morceaux)


def _operation_3d(canvas, op, couleur, decalage, scratch):
    kind = getattr(op, 'operation_type', '')
    params = getattr(op, 'params', {}) or {}
    dx, dy = decalage
    if kind == 'appel_programme':
        # tout le fichier appelé, simulé (gardé tant qu'il ne change pas)
        from src.core import sim_cycles
        chemin = str(params.get('filepath') or '').strip()
        if not chemin:
            return []
        lib = getattr(canvas, '_tool_library', None)
        res = sim_cycles.parcours_fichier(
            chemin, sim_cycles.diametres_de(lib) if lib is not None else {})
        return _segments_sim3d(res, couleur, dx, dy)
    if kind == 'lignes_main':
        # les lignes d'un Main importé: leur parcours simulé, à sa
        # profondeur (une gravure) — rien pour une pause
        from src.core import sim_cycles
        from src.operations.lignes_main import LignesMain
        lib = getattr(canvas, '_tool_library', None)
        res = LignesMain.parcours(
            params, sim_cycles.diametres_de(lib) if lib is not None else {})
        if not res:
            return []
        # la couleur de l'outil qu'elles prennent (elles n'en ont pas)
        article, _nom = LignesMain.outil(params, res, lib)
        if article:
            couleur = canvas.tool_color(article, article).name()
        return _segments_sim3d(res, couleur, dx, dy)
    if kind == 'sequence_datron':
        from src.operations.sequence_datron import SequenceDatron
        code = SequenceDatron.build_sequence_block(params)
        return _segments_sim3d(parcours_lu(code), couleur, dx, dy)
    if kind == 'bloc_simpl':
        from src.operations.bloc_simpl import BlocSimpl
        out = []
        for code in (BlocSimpl.body(params), BlocSimpl.sequence_block(params)):
            if code and code.strip():
                out += _segments_sim3d(parcours_lu(code), couleur, dx, dy)
        return out
    if kind in ('gravure_2d5', 'evidement_2d5', 'contour_2d5',
                'texte_grave'):
        plan = None
        try:
            from src.operations.registry import OperationRegistry
            from src.operations.gravure_2d5 import params_outil
            classe = OperationRegistry.get(kind)
            plan = classe.plan_si_connu(params_outil(op,
                                                     canvas._tool_library))
        except Exception:
            plan = None
        if not plan:
            # pas encore calculé: le DESSIN, au fond et en surface —
            # on voit où et jusqu'où, sans lancer le calcul
            try:
                contours = classe.contours(params) or []
            except Exception:
                contours = []
            prof = 0.0
            for cle in ('profondeur', 'profondeur_max', 'depth'):
                try:
                    prof = abs(float(params.get(cle) or 0.0))
                except (TypeError, ValueError):
                    prof = 0.0
                if prof > 0:
                    break
            out = []
            for contour in contours:
                if len(contour) >= 2:
                    pts = np.asarray(contour, dtype=float)[:, :2] + [dx, dy]
                    out.append((_a_z(pts, 0.0), couleur, 'surface'))
                    out.append((_a_z(pts, -prof), couleur, 'coupe'))
            if out:
                return out
        if plan:
            out = []
            for etape in plan:
                if etape['type'] == 'anneau':
                    z = -float(etape['profondeur'])
                    for contour in etape['contours']:
                        if len(contour) >= 2:
                            out.append((_a_z(np.asarray(contour, float)
                                             + [dx, dy], z),
                                        couleur, 'coupe'))
                else:
                    pts = np.asarray(etape['points'], dtype=float)
                    if len(pts) >= 2:
                        pts = pts * [1, 1, -1] + [dx, dy, 0]
                        out.append((pts, couleur, 'coupe'))
            return out
    if kind == 'trace':
        from src.operations.trace import Trace
        try:
            d = float(canvas._tool_diameter(op))
        except Exception:
            d = 0.0
        tous = Trace.chemins(dict(params, _diametre_outil=d), op.x + dx,
                             op.y + dy, getattr(op, 'points', None))
        return [(_a_z(np.asarray(pts, float), -profondeur(op)), couleur,
                 'coupe') for pts in tous if len(pts) >= 2]
    points = list(getattr(op, 'points', None) or []) or [
        {'x': getattr(op, 'x', 0.0), 'y': getattr(op, 'y', 0.0)}]
    out = []
    forme_connue = False
    for pt in points:
        forme = canvas._op_shape(op, pt)
        if forme is None:
            continue
        forme_connue = True
        p = profondeur(op, pt)
        for x, y in canvas._op_positions(op, pt):
            x, y = x + dx, y + dy
            if kind in ('percage_foret', 'taraudage', 'taraudage_brut'):
                out += _percage(op, pt, forme, x, y, p, couleur)
                continue
            contour = _contour_forme(forme, x, y)
            out.append((_a_z(contour, -p), couleur, 'coupe'))
            out.append((_a_z(contour, 0.0), couleur, 'surface'))
            pas = max(1, len(contour) // 4)
            for i in range(0, len(contour) - 1, pas):
                cx, cy = contour[i]
                out.append((np.array([(cx, cy, 0.0), (cx, cy, -p)]),
                            couleur, 'axe'))
    if forme_connue:
        return out
    return _par_le_canvas(canvas, op, couleur, decalage, scratch)


def _percage(op, pt, forme, x, y, p, couleur):
    d = forme[1] if forme[0] == 'circle' else 0.0
    out = [(np.array([(x, y, 0.0), (x, y, -p)]), couleur, 'axe')]
    if d > 0:
        cercle = _contour_forme(('circle', d), x, y, 32)
        out.append((_a_z(cercle, 0.0), couleur, 'surface'))
        kind = getattr(op, 'operation_type', '')
        filet = str(pt.get('thread_type') or (op.params or {}).get(
            'thread_type') or '')
        pas = PAS_FILET.get(filet.replace(',', '.').strip().upper())
        if kind.startswith('taraudage') and pas and p > 0:
            # l'hélice du filet, au pas
            tours = p / pas
            t = np.linspace(0, 2 * math.pi * tours,
                            max(16, int(tours * 24)))
            r = d / 2.0
            out.append((np.column_stack([x + r * np.cos(t),
                                         y + r * np.sin(t),
                                         -p * t / t[-1]]),
                        couleur, 'coupe'))
        else:
            out.append((_a_z(cercle, -p), couleur, 'coupe'))
    return out


def couleurs_outils(canvas, res) -> dict:
    """{référence: couleur hex} des outils d'une simulation — les
    mêmes couleurs que le canvas 2D."""
    sortie = {}
    for art in set(res.get('outil') or []):
        try:
            sortie[art] = canvas.tool_color(art or "?").name()
        except Exception:
            sortie[art] = "#89b4fa"
    return sortie


def _par_le_canvas(canvas, op, couleur, decalage, scratch):
    """Toute autre opération: ce que le canvas 2D en dessine, posé à
    sa profondeur (sur un canvas de brouillon: l'affichage ne bouge
    pas)."""
    if scratch is None:
        return []
    try:
        scratch.set_active_operation(op, keep_existing=False,
                                     offset=decalage)
    except Exception:
        return []
    z = -profondeur(op)
    out = []
    for item in list(getattr(scratch, '_op_point_items', [])):
        chemin = _chemin_item(item)
        if chemin is None:
            continue
        for pts in _polylignes(chemin, z):
            out.append((pts, couleur, 'coupe'))
    scratch.clear_operation_points()
    return out
