# -*- coding: utf-8 -*-
"""NeoDrive, post-processeur de VectorDrive: le travail d'usinage
(`.ndjob`) que le plugin « NeoDrive » de VectorDrive écrit, et sa
traduction en programme NeoDrive (octobre 2026, RomDuch: « neodrive as a
postpro for Vdrive »).

VectorDrive dessine et calcule les parcours; NeoDrive écrit le programme
Datron — avec ses outils (tools.json), ses palpages, ses changements
d'outil, son NDMETA (le .SimPl se rouvre dans NeoDrive, opérations
comprises). Le contrat entre les deux est ce fichier JSON, versionné:

    {"format": "neodrive-job", "version": 1,
     "source": {"logiciel": "VectorDrive", "version": "…", "document": "…"},
     "titre": "…", "stem": "…", "machine": "…",
     "brut": [xmin, xmax, ymin, ymax, zmin, zmax] | null,
     "outils": [{id, nom, nature, diametre, angle, pointe, dents,
                 longueur_utile, reference, fournisseur, rpm, avance,
                 plongee, rampe, passe, cle_neodrive, geometrie}],
     "operations": [{id, nom, nature, outil, profondeur, passe}],
     "parcours": [{operation, outil, nom,
                   mouvements: [[genre, x, y, z(, cx, cy)]…],
                   cycles: [{kind, …}], avertissements: […]}]}

Un parcours qui porte des CYCLES (trous, poches et découpes simples,
surfaçages, texte machine, instructions) devient les opérations NeoDrive
de ces cycles — VectorDrive les nomme comme NeoDrive; sinon ses
mouvements deviennent une séquence Datron embarquée ($$$).
"""

from __future__ import annotations

import json
import math
from collections import Counter
from typing import Dict, List, Optional, Tuple

FORMAT = "neodrive-job"
VERSION = 1
#: l'extension du travail
EXTENSION = ".ndjob"


class JobError(ValueError):
    """Un travail illisible ou d'un format inconnu."""


# ── lecture ──────────────────────────────────────────────────────────

def lire(chemin: str) -> Dict:
    """Le travail d'un fichier .ndjob, vérifié."""
    try:
        with open(chemin, 'r', encoding='utf-8-sig') as f:
            job = json.load(f)
    except (OSError, ValueError) as exc:
        raise JobError(f"Travail illisible: {exc}") from exc
    return verifier(job)


def verifier(job) -> Dict:
    if not isinstance(job, dict) or job.get('format') != FORMAT:
        raise JobError("Ce n'est pas un travail NeoDrive (format "
                       f"« {FORMAT} » attendu)")
    try:
        version = int(job.get('version', 0))
    except (TypeError, ValueError):
        version = 0
    if version < 1 or version > VERSION:
        raise JobError(f"Version {job.get('version')} du travail inconnue "
                       f"(cette version de NeoDrive lit la {VERSION})")
    for cle in ('outils', 'operations', 'parcours'):
        if not isinstance(job.get(cle, []), list):
            raise JobError(f"« {cle} » doit être une liste")
    return job


# ── les outils ───────────────────────────────────────────────────────

def _f(valeur, defaut: float = 0.0) -> float:
    try:
        v = float(valeur)
    except (TypeError, ValueError):
        return float(defaut)
    return v if math.isfinite(v) else float(defaut)


def type_neodrive(outil: Dict) -> str:
    """La famille NeoDrive d'un outil VectorDrive (Cyl3, Con30, Drill…)."""
    nature = str(outil.get('nature') or 'fraise')
    d = _f(outil.get('diametre'), 0.0)
    if nature == 'conique':
        a = _f(outil.get('angle'), 0.0)
        return f"Con{a:g}" if a > 0 else "Chamfer"
    if nature == 'foret':
        return "Drill"
    return f"Cyl{d:g}" if d > 0 else "Cyl"


def fiche_neodrive(outil: Dict) -> Dict:
    """La fiche tools.json d'un outil VectorDrive absent de la
    bibliothèque."""
    d = _f(outil.get('diametre'), 0.0)
    geo = dict(outil.get('geometrie') or {})
    geometrie = {'Diameter': d,
                 'TipAngle': _f(outil.get('angle'), 0.0),
                 'TipDiameter': _f(outil.get('pointe'), 0.0) or d,
                 'NumberOfFlutes': int(_f(outil.get('dents'), 1) or 1),
                 'FluteLength': _f(outil.get('longueur_utile'), 0.0)}
    for cle in ('L1', 'L2', 'L3', 'D1', 'D2', 'D3'):
        if cle in geo:
            geometrie[cle] = _f(geo[cle])
    return {
        'name': str(outil.get('nom') or 'Outil VectorDrive'),
        'reference': str(outil.get('reference') or ''),
        'type_taraudage': type_neodrive(outil),
        'rpm': int(_f(outil.get('rpm'), 0)),
        'feed_finishing': int(_f(outil.get('avance'), 0)),
        'feed_plunge': int(_f(outil.get('plongee'), 0)),
        'feed_ramp': int(_f(outil.get('rampe'), 0)
                         or _f(outil.get('plongee'), 0)),
        'feed_approach': int(_f(outil.get('avance'), 0)),
        'feed_roughing': int(_f(outil.get('avance'), 0)),
        'diameter': d,
        'vendor': str(outil.get('fournisseur') or ''),
        'max_depth': _f(outil.get('longueur_utile'), 0.0),
        'min_depth': 0.0,
        'coolant': 'spray',
        'notes': "Importé de VectorDrive",
        'geometry': geometrie,
    }


def outil_neodrive(outil: Dict, bibliotheque) -> Optional[str]:
    """L'outil de la bibliothèque NeoDrive qui correspond: par sa clé
    NeoDrive (VectorDrive la garde quand il a importé tools.json), par
    sa référence (l'article), par son nom — sinon None."""
    if bibliotheque is None:
        return None
    outils = getattr(bibliotheque, 'tools', {}) or {}
    cle = str(outil.get('cle_neodrive') or '')
    if cle and cle in outils:
        return cle
    from src.core.tool_library import extract_article_nr
    article = extract_article_nr(str(outil.get('reference') or ''))
    if article:
        trouve = bibliotheque.get_tool_by_article(article)
        if trouve is not None:
            return next((k for k, t in outils.items() if t is trouve), None)
    nom = str(outil.get('nom') or '').strip()
    if nom:
        return next((k for k, t in outils.items()
                     if str(getattr(t, 'name', '')).strip() == nom), None)
    return None


def _cle_libre(bibliotheque, outil: Dict) -> str:
    base = "vd_" + "".join(c if c.isalnum() else "_" for c in
                           str(outil.get('nom') or 'outil').lower())[:40]
    cle, k = base, 2
    while cle in bibliotheque.tools:
        cle, k = f"{base}_{k}", k + 1
    return cle


def correspondance_outils(job: Dict, bibliotheque, ajouter: str = 'memoire'
                          ) -> Tuple[Dict[str, str], List[Dict]]:
    """{id d'outil VectorDrive: clé NeoDrive} et les outils absents.

    `ajouter`: 'memoire' — les absents rejoignent la bibliothèque le temps
    du programme (rien n'est enregistré); 'enregistrer' — ils y sont
    ajoutés pour de bon; 'non' — ils restent absents."""
    corr, absents = {}, []
    for outil in job.get('outils', []) or []:
        if not isinstance(outil, dict):
            continue
        vid = str(outil.get('id') or '')
        cle = outil_neodrive(outil, bibliotheque)
        if cle is None:
            absents.append(outil)
            if bibliotheque is not None and ajouter in ('memoire',
                                                        'enregistrer'):
                from src.core.tool_library import Tool
                cle = _cle_libre(bibliotheque, outil)
                fiche = fiche_neodrive(outil)
                if ajouter == 'enregistrer':
                    bibliotheque.add_tool(cle, fiche)
                else:
                    bibliotheque.tools[cle] = Tool(fiche)
        if cle is not None:
            corr[vid] = cle
    return corr, absents


# ── les mouvements: une séquence Datron ──────────────────────────────

def _n(v: float) -> str:
    """Un nombre comme TypeEdit l'écrit: 5 décimales au plus, sans zéros
    inutiles, jamais « -0 »."""
    t = f"{float(v):.5f}".rstrip('0').rstrip('.')
    return "0" if t in ("-0", "") else t


def sequence_depuis_mouvements(mouvements) -> str:
    """Les lignes d'une séquence $$$ (sans son en-tête) depuis les
    mouvements VectorDrive [[genre, x, y, z(, cx, cy)]]: PrePositioning,
    Rapid, Feed Plunge/Finishing, Line, Arc CW/CCW (centre relatif au
    départ: dX, dY), coordonnées modales."""
    lignes = ["Spindle On"]
    pos = None
    avance = None
    for m in mouvements or []:
        if not m or len(m) < 4:
            continue
        genre = str(m[0])
        x, y, z = _f(m[1]), _f(m[2]), _f(m[3])
        if pos is None:
            lignes.append(f"PrePositioning X={_n(x)} Y={_n(y)} Z={_n(z)}")
            pos = (x, y, z)
            continue

        def _axes(nx, ny, nz, tous_xy=False):
            parts = []
            if tous_xy or abs(nx - pos[0]) > 1e-7:
                parts.append(f"X={_n(nx)}")
            if tous_xy or abs(ny - pos[1]) > 1e-7:
                parts.append(f"Y={_n(ny)}")
            if abs(nz - pos[2]) > 1e-7:
                parts.append(f"Z={_n(nz)}")
            return " ".join(parts)
        if genre == 'rapid':
            axes = _axes(x, y, z)
            if axes:
                lignes.append(f"Rapid {axes}")
        elif genre in ('arc_cw', 'arc_ccw') and len(m) >= 6:
            if avance != 'Finishing':
                lignes.append("Feed Finishing")
                avance = 'Finishing'
            cx, cy = _f(m[4]), _f(m[5])
            sens = "CW" if genre == 'arc_cw' else "CCW"
            lignes.append(f"Arc {sens} {_axes(x, y, z, tous_xy=True)} "
                          f"dX={_n(cx - pos[0])} dY={_n(cy - pos[1])}")
        else:
            voulue = 'Plunge' if genre == 'plunge' else 'Finishing'
            if avance != voulue:
                lignes.append(f"Feed {voulue}")
                avance = voulue
            axes = _axes(x, y, z)
            if axes:
                lignes.append(f"Line {axes}")
        pos = (x, y, z)
    return "\n".join(lignes)


# ── les cycles et les instructions ───────────────────────────────────

#: les instructions VectorDrive → l'opération NeoDrive
INSTRUCTION_VERS_OPE = {
    'message': 'message_operateur', 'question': 'dialogue_operateur',
    'saisie_operateur': 'parametres_operateur',
    'retournement': 'retournement_piece', 'prechauffage': 'prechauffage_broche',
    'bloc': 'fonction_custom',
}
#: les champs renommés: {opé NeoDrive: {champ VectorDrive: champ NeoDrive}}
RENOMMES = {
    'palpage_z': {'x': 'probe_x', 'y': 'probe_y'},
    'decalage_origine': {'x': 'shift_x', 'y': 'shift_y', 'z': 'shift_z'},
    'appel_programme': {'path': 'filepath'},
    'palpage_symetrie': {'frame': 'origin', 'search': 'search_distance',
                         'retract': 'retract_distance',
                         'skip_z_result': 'skip_z_measure_result'},
    'dialogue_operateur': {'park': 'park_before'},
    'prechauffage_broche': {'force': 'force_execution'},
    'fonction_custom': {'texte': 'simpl_code'},
}
#: les libellés de choix VectorDrive → valeurs NeoDrive
CHOIX = {
    ('palpage_rectangle', 'probe_side'): {'Extérieur': 'Outside',
                                          'Intérieur': 'Inside'},
    ('palpage_rectangle', 'origin'): {
        'Centre': 'Center', 'Avant gauche': 'LeftFront',
        'Avant droit': 'RightFront', 'Arrière gauche': 'LeftRear',
        'Arrière droit': 'RightRear'},
    ('palpage_rectangle', 'rotation_axis'): {
        'Auto (long côté)': 'Auto', 'Y+': 'YPositive', 'X+': 'XPositive'},
    ('mesure_orientation', 'feature'): {
        'Perçage (mesure intérieure)': 'Intérieur (perçage)',
        'Bossage (mesure extérieure)': 'Extérieur (bossage)'},
    ('mesure_orientation', 'axis'): {
        'X (+ Z)': 'X (les 2 repères alignés sur X)',
        'Y (+ Z)': 'Y (les 2 repères alignés sur Y)'},
}


def _parametres_ope(genre: str):
    from src.operations.registry import OperationRegistry
    try:
        classe = OperationRegistry.get(genre)
    except KeyError:
        return None, {}
    return classe, {p.key: p for p in classe.get_parameters()}


def _valeur_choix(genre, cle, valeur, defs, avert) -> Optional[object]:
    choix = list(getattr(defs[cle], 'choices', None) or [])
    if not choix:
        return valeur
    table = CHOIX.get((genre, cle), {})
    if valeur in table:
        valeur = table[valeur]
    if valeur in choix:
        return valeur
    texte = str(valeur).casefold()
    for c in choix:
        if str(c).casefold().startswith(texte[:6]):
            return c
    avert.append(f"{genre}: « {cle} » = « {valeur} » inconnu (défaut gardé)")
    return None


def ope_instruction(nom: str, params: Dict, avert: List[str]):
    """L'opération NeoDrive d'une instruction VectorDrive, ou None."""
    from src.core.program_model import OperationInstance
    genre = INSTRUCTION_VERS_OPE.get(nom, nom)
    classe, defs = _parametres_ope(genre)
    if classe is None:
        avert.append(f"instruction « {nom} » sans équivalent NeoDrive "
                     "(ignorée)")
        return None
    op = OperationInstance(genre, classe.DISPLAY_NAME)
    op.params = dict(classe.get_default_params())
    renommes = RENOMMES.get(genre, {})
    for cle, valeur in (params or {}).items():
        cle_nd = renommes.get(cle, cle)
        if cle_nd in defs:
            v = _valeur_choix(genre, cle_nd, valeur, defs, avert)
            if v is not None:
                op.params[cle_nd] = v
        elif cle in ('x', 'y'):
            setattr(op, cle, _f(valeur))
    if genre == 'rotation_repere' and 'absolue' in (params or {}):
        op.params['mode'] = ('Absolue' if params.get('absolue')
                             else 'Incrémentale')
    if genre == 'dialogue_operateur':
        op.params['dialog_type'] = 'ask_continue'
    if nom == 'saisie_operateur' and params.get('champs'):
        avert.append("saisie de l'opérateur: les champs sont à reprendre "
                     "dans le formulaire « Paramètres opérateur »")
    return op


def _plus_frequent(valeurs) -> float:
    c = Counter(round(_f(v), 4) for v in valeurs if _f(v) > 0)
    return c.most_common(1)[0][0] if c else 0.0


def opes_des_cycles(cycles: List[Dict], avert: List[str]) -> list:
    """Les opérations NeoDrive des cycles d'un parcours, dans l'ordre:
    les trous de même nature regroupés en une opé à plusieurs points;
    chaque poche, découpe, surfaçage, texte: son opé."""
    from src.core.program_model import OperationInstance
    sortie = []

    def _ope(genre, nom=None):
        classe, _defs = _parametres_ope(genre)
        op = OperationInstance(genre, nom or (classe.DISPLAY_NAME if classe
                                              else genre))
        op.params = dict(classe.get_default_params()) if classe else {}
        return op

    trous: Dict[str, list] = {}
    ordre: List[Tuple[str, object]] = []
    for c in cycles or []:
        if not isinstance(c, dict):
            continue
        k = str(c.get('kind') or '')
        if k in ('taraudage', 'percage_fraise', 'chanfrein'):
            if k not in trous:
                trous[k] = []
                ordre.append(('trous', k))
            trous[k].append(c)
            continue
        ordre.append(('un', c))
    for quoi, objet in ordre:
        if quoi == 'trous':
            k, liste = objet, trous[objet]
            if k == 'taraudage':
                op = _ope('taraudage')
                op.params['depth'] = max(_f(c.get('depth')) for c in liste)
                op.params['thread_name'] = str(liste[0].get('thread') or 'M4')
                op.params['direction'] = ('LeftHandThread'
                                          if liste[0].get('left')
                                          else 'RightHandThread')
                op.params['milling_type'] = (
                    'ClimbMilling' if liste[0].get('climb', True)
                    else 'ConventionalMilling')
                op.points = [{'x': _f(c.get('x')), 'y': _f(c.get('y')),
                              'depth': _f(c.get('depth')),
                              'thread_type': str(c.get('thread') or 'M4')}
                             for c in liste]
            elif k == 'percage_fraise':
                op = _ope('percage_fraise')
                diam = [_f(c.get('diameter')) for c in liste]
                op.params['diameter'] = _plus_frequent(diam) or \
                    op.params.get('diameter', 4.05)
                op.params['depth'] = max(_f(c.get('depth')) for c in liste)
                infeed = _f(liste[0].get('infeed'), 0.0)
                if infeed > 0:
                    op.params['infeed_z'] = infeed
                par_point = len({round(d, 4) for d in diam if d > 0}) > 1
                op.params['diametres_par_point'] = par_point
                op.points = []
                for c in liste:
                    pt = {'x': _f(c.get('x')), 'y': _f(c.get('y')),
                          'depth': _f(c.get('depth'))}
                    if par_point and _f(c.get('diameter')) > 0:
                        pt['diameter'] = round(_f(c.get('diameter')), 4)
                    op.points.append(pt)
            else:                                    # chanfrein: Drill
                op = _ope('percage_foret', "Ébavurage des trous")
                op.params['depth'] = max(_f(c.get('depth')) for c in liste)
                op.params['infeed_z'] = op.params['depth']
                op.points = [{'x': _f(c.get('x')), 'y': _f(c.get('y')),
                              'depth': _f(c.get('depth'))} for c in liste]
            if op.points:
                op.x, op.y = op.points[0]['x'], op.points[0]['y']
            sortie.append(op)
            continue
        c = objet
        k = str(c.get('kind') or '')
        if k == 'instruction':
            op = ope_instruction(str(c.get('name') or ''),
                                 c.get('params') or {}, avert)
            if op is not None:
                sortie.append(op)
            continue
        x, y = _f(c.get('x')), _f(c.get('y'))
        if k in ('poche_cercle', 'decoupe_cercle', 'surfacage_cercle'):
            op = _ope(k)
            op.params['diameter'] = _f(c.get('diameter'),
                                       op.params.get('diameter', 10.0))
        elif k in ('poche_rectangle', 'decoupe_rectangle',
                   'surfacage_rectangle'):
            op = _ope(k)
            op.params['width_x'] = _f(c.get('width'))
            op.params['width_y'] = _f(c.get('height'))
            if k != 'surfacage_rectangle':
                op.params['corner_radius'] = _f(c.get('corner'))
        elif k == 'texte_machine':
            op = _ope('gravure_texte')
            op.params.update({
                'text': str(c.get('text') or ''),
                'use_date': bool(c.get('date')),
                'char_height': _f(c.get('height'), 2.5),
                'rotation': _f(c.get('rotation')),
                'depth': _f(c.get('depth'), 0.25),
                'multi_pass': bool(c.get('double')),
                'depth_pass1': _f(c.get('depth1'), 0.15)})
            if str(c.get('variable') or '').strip():
                avert.append("texte machine: la variable « "
                             f"{c.get('variable')} » n'est pas reprise "
                             "(le texte fixe l'est)")
        else:
            avert.append(f"cycle « {k} » inconnu (ignoré)")
            continue
        if 'depth' in c:
            op.params['depth'] = _f(c.get('depth'))
        if _f(c.get('infeed')) > 0 and 'infeed_z' in op.params:
            op.params['infeed_z'] = _f(c.get('infeed'))
        if 'side' in c and 'side' in op.params:
            op.params['side'] = str(c.get('side') or op.params['side'])
        if 'stock' in c and 'finishing_xy' in op.params:
            op.params['finishing_xy'] = _f(c.get('stock'))
        if _f(c.get('stepover')) > 0 and 'stepover' in op.params:
            op.params['stepover'] = int(round(_f(c.get('stepover'))))
        if k == 'surfacage_rectangle':
            op.params['extension_x'] = op.params['extension_y'] = \
                _f(c.get('extension'))
            if 'angle' in c:
                op.params['angle'] = _f(c.get('angle'), 90.0)
        if k == 'surfacage_cercle':
            op.params['extension_diameter'] = _f(c.get('extension'))
        op.x, op.y = x, y
        sortie.append(op)
    return sortie


# ── le programme ─────────────────────────────────────────────────────

def _avances_differentes(outil_vd: Dict, outil_nd) -> Dict[str, int]:
    """Les réglages que VectorDrive impose à un outil NeoDrive (ceux qui
    diffèrent de plus de 1 %): le régime et les avances de l'opé."""
    sortie = {}
    for cle_vd, attr, cle_ope in (('rpm', 'rpm', 'rpm_override'),
                                  ('avance', 'feed_finishing',
                                   'feed_override_finishing'),
                                  ('plongee', 'feed_plunge',
                                   'feed_override_plunge'),
                                  ('rampe', 'feed_ramp',
                                   'feed_override_ramp')):
        v = _f(outil_vd.get(cle_vd), 0.0)
        nd = _f(getattr(outil_nd, attr, 0), 0.0)
        if v > 0 and abs(v - nd) > 0.01 * max(v, nd, 1.0):
            sortie[cle_ope] = int(round(v))
    return sortie


def programme_depuis_job(job: Dict, bibliotheque, ajouter_outils='memoire',
                         avances: str = 'vectordrive'):
    """(ProgramModel, avertissements, outils absents) d'un travail.

    `avances`: 'vectordrive' — le régime et les avances de VectorDrive
    s'imposent à l'opé quand ils diffèrent de la fiche NeoDrive;
    'neodrive' — ceux de tools.json."""
    from src.core.program_model import OperationInstance, ProgramModel
    verifier(job)
    avert: List[str] = []
    corr, absents = correspondance_outils(job, bibliotheque, ajouter_outils)
    for o in absents:
        avert.append(f"outil « {o.get('nom', '?')} » ({o.get('reference') or 'sans référence'})"
                     " absent de la bibliothèque NeoDrive"
                     + (" — ajouté pour ce programme"
                        if ajouter_outils == 'memoire' else
                        " — ajouté à la bibliothèque"
                        if ajouter_outils == 'enregistrer' else ""))
    outils_vd = {str(o.get('id') or ''): o for o in job.get('outils', [])
                 if isinstance(o, dict)}
    ops_vd = {str(o.get('id') or ''): o for o in job.get('operations', [])
              if isinstance(o, dict)}
    prog = ProgramModel()
    titre = str(job.get('titre') or job.get('stem') or '').strip()
    if titre:
        prog.settings.comment = f"{titre} — de VectorDrive"
    brut = job.get('brut')
    if isinstance(brut, (list, tuple)) and len(brut) == 6:
        xmin, xmax, ymin, ymax, zmin, zmax = (_f(v) for v in brut)
        if xmax > xmin and ymax > ymin:
            s = prog.settings
            s.brut_longueur, s.brut_largeur = xmax - xmin, ymax - ymin
            s.brut_epaisseur = max(0.0, zmax - zmin) or 0.0
            s.brut_origine = 'libre'
            s.brut_dx, s.brut_dy = -xmin, -ymin
    import uuid
    n_seq = 0
    for k, tp in enumerate(job.get('parcours', []) or []):
        if not isinstance(tp, dict):
            continue
        nom = str(tp.get('nom') or ops_vd.get(str(tp.get('operation')), {})
                  .get('nom') or f"Parcours {k + 1}")
        for w in tp.get('avertissements', []) or []:
            avert.append(f"{nom}: {w}")
        cycles = tp.get('cycles') or []
        if cycles:
            ops = opes_des_cycles(cycles, avert)
        elif tp.get('mouvements'):
            n_seq += 1
            op = OperationInstance("sequence_datron", nom)
            from src.operations.registry import OperationRegistry
            op.params = dict(OperationRegistry.get(
                "sequence_datron").get_default_params())
            op.params['sequence_name'] = f"SEQUENCE_VD{n_seq}"
            op.params['sequence_code'] = sequence_depuis_mouvements(
                tp['mouvements'])
            ops = [op]
        else:
            avert.append(f"{nom}: ni mouvement ni cycle (ignoré)")
            ops = []
        vid = str(tp.get('outil') or '')
        cle = corr.get(vid, '')
        outil_nd = bibliotheque.tools.get(cle) if (
            bibliotheque is not None and cle) else None
        reglages = (_avances_differentes(outils_vd.get(vid, {}), outil_nd)
                    if avances == 'vectordrive' and outil_nd is not None
                    and vid in outils_vd and outils_vd[vid].get(
                        'cle_neodrive') == cle else {})
        groupe = str(uuid.uuid4())[:8] if len(ops) > 1 else ''
        for op in ops:
            if cle and op.operation_type not in (
                    'message_operateur', 'dialogue_operateur',
                    'decalage_origine', 'rotation_repere', 'miroir',
                    'retablir_miroir', 'repere_local', 'appel_programme',
                    'parametres_operateur', 'compteur_pieces',
                    'fonction_custom', 'table_vide'):
                op.tool_id = cle
                op.params.update(reglages)
            if groupe:
                op.group_id, op.group_name = groupe, nom
            if len(ops) == 1 and op.operation_type == "sequence_datron":
                op.name = nom
            prog.add_operation(op)
    prog.mark_saved()
    return prog, avert, absents


def generer_simpl(job: Dict, bibliotheque, ajouter_outils='memoire',
                  avances: str = 'vectordrive') -> Tuple[str, List[str]]:
    """Le .SimPl du travail (NDMETA compris: il se rouvre dans NeoDrive,
    opérations comprises) et les avertissements."""
    from src.codegen.generator import SimPlGenerator
    prog, avert, _absents = programme_depuis_job(job, bibliotheque,
                                                 ajouter_outils, avances)
    code = SimPlGenerator(prog, bibliotheque).generate()
    return code, avert
