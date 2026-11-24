"""Ce que créent les boutons « depuis la sélection du canvas ».

Deux boutons partent des entités sélectionnées au canvas: « Générer les
opérations… » (onglet DXF to Op) et « Depuis la sélection du canvas »
des formulaires (perçage, taraudage, poche ou découpe rectangle). Les
deux ouvrent le MÊME mini formulaire: ses champs (profondeur du filet
et de son avant-trou, passe Z, offset, côté…) valent pour toutes les
sous-opérations qu'ils créent, et celles-ci peuvent former un ensemble
de la liste.

Ici, des données seulement (pas de Qt): les champs du formulaire
(au format de src/gui/dialogs/mini_formulaire), et ce que ses valeurs
changent aux opérations.
"""

from typing import Dict, List, Optional, Sequence

from src.operations.taraudage import (THREAD_TYPES, AVANT_TROU,
                                      PAS_FILET)

#: le côté d'une découpe rectangle, tel que le formulaire le dit
COTES_DECOUPE = (("Extérieur", "Outside"), ("Intérieur", "Inside"),
                 ("Sur le trait", "Over"))


def _nombre(cle, libelle, defaut, mini=0.0, maxi=200.0, bulle=""):
    options = {'min': mini, 'max': maxi, 'unite': "mm"}
    if bulle:
        options['bulle'] = bulle
    return (cle, libelle, 'nombre', float(defaut), options)


def profondeur_avant_trou(filet: str, profondeur: float) -> float:
    """L'avant-trou d'un filet borgne: deux pas plus profond."""
    return round(float(profondeur) + 2 * PAS_FILET.get(filet, 0.7), 3)


def champs_points(op_type: str, params: Dict) -> List:
    """Les champs d'un perçage, d'un taraudage, d'une poche cercle
    posés sur des points."""
    p = params or {}
    prof = float(p.get('depth', 2.0) or 2.0)
    if op_type == "taraudage":
        filet = str(p.get('thread_name') or "M4")
        if filet not in THREAD_TYPES:
            filet = "M4"
        return [
            ('thread_name', "Type de taraudage", 'choix', filet,
             {'choix': list(THREAD_TYPES)}),
            _nombre('depth', "Profondeur du filet (Thread)", prof, 0.5,
                    100.0),
            ('avant_trou', "Percer l'avant-trou (DrillMilling)", 'case',
             bool(p.get('_avant_trou', False)),
             {'bulle': "Un perçage fraisé au Ø de perçage du filet "
                       "(M4: 3,3) avant le filet, sur les mêmes points"}),
            _nombre('profondeur_avant_trou',
                    "Profondeur de l'avant-trou (DrillMilling)",
                    profondeur_avant_trou(filet, prof), 0.1, 100.0,
                    "Deux pas sous le filet pour un trou borgne"),
            ('ebav', "Ébavurer (chanfrein)", 'case',
             bool(p.get('use_ebav', False)), {}),
        ]
    if op_type == "filetage_special":
        cote = ("Extérieur" if p.get('inside_outside') == "Outside"
                else "Intérieur")
        return [
            _nombre('depth', "Profondeur du filet (SpecialThread)", prof,
                    0.1, 200.0),
            _nombre('pitch', "Pas", float(p.get('pitch', 1.0) or 1.0),
                    0.05, 20.0, "Le Ø nominal est celui du cercle dessiné"),
            ('inside_outside', "Côté", 'choix', cote,
             {'choix': ["Intérieur", "Extérieur"],
              'bulle': "Intérieur: un taraudage; Extérieur: un filet "
                       "autour d'un tenon"}),
        ]
    champs = [_nombre('depth', {
        "percage_fraise": "Profondeur (DrillMilling)",
        "percage_foret": "Profondeur (Drill)",
        "poche_cercle": "Profondeur de la poche"}.get(op_type, "Profondeur"),
        prof, 0.0, 200.0)]
    if op_type in ("percage_fraise", "percage_foret", "poche_cercle"):
        champs.append(_nombre('infeed_z', "Passe Z",
                              float(p.get('infeed_z', 1.0) or 1.0),
                              0.01, 50.0))
    if op_type in ("percage_fraise", "percage_foret"):
        champs.append(('ebav', "Ébavurer (chanfrein)", 'case',
                       bool(p.get('use_ebav', False)), {}))
    return champs


def champs_rectangles(op_type: str, params: Dict) -> List:
    """Les champs d'une poche, d'une découpe, d'un surfaçage
    rectangle: profondeur, offset XY (et le côté d'une découpe)."""
    p = params or {}
    champs = []
    if op_type != "ebavurage":
        champs.append(_nombre('depth', "Profondeur",
                              float(p.get('depth', 2.0) or 2.0), 0.0,
                              200.0))
    champs.append(_nombre(
        'offset', "Offset XY (+ agrandit, − réduit)", 0.0, -50.0, 50.0,
        "Ajouté de chaque côté du rectangle sélectionné"))
    if op_type == "decoupe_rectangle":
        actuel = {v: k for k, v in COTES_DECOUPE}.get(
            str(p.get('side') or "Outside"), "Extérieur")
        champs.append(('side', "Côté de l'outil", 'choix', actuel,
                       {'choix': [k for k, _v in COTES_DECOUPE]}))
    return champs


#: les opérations dont les coins se fraisent DEDANS (poche, découpe):
#: une fraise n'y fait pas d'angle vif
OPS_COINS = ("poche_rectangle", "decoupe_rectangle")


def champ_coins_vifs(op_type: str, rects: Sequence[Dict],
                     rayon_outil: float):
    """Le champ « Rayon des coins vifs » quand un rectangle choisi n'a
    pas de rayon de coin (octobre 2026: l'opé gardait son rayon par
    défaut, ou 0, sans le dire) — pré-rempli au rayon de la fraise, le
    plus petit possible. None s'il n'y a rien à demander."""
    if op_type not in OPS_COINS:
        return None
    vifs = sum(1 for r in rects or [] if not float(r.get('rayon') or 0) > 0)
    if not vifs:
        return None
    return ('rayon_coins_vifs', "Rayon des coins vifs", 'nombre',
            round(max(0.0, float(rayon_outil or 0.0)), 3),
            {'min': 0.0, 'max': 100.0, 'unite': "mm",
             'bulle': f"{vifs} rectangle(s) du dessin sans rayon de coin: "
                      "une fraise ne fait pas d'angle vif à l'intérieur. "
                      "Pré-rempli au rayon de l'outil, le plus petit "
                      "possible (une découpe extérieure peut garder 0)."})


def rayon_de_coin(rect: Dict, valeurs: Dict, defaut=None):
    """Le rayon de coin d'un rectangle: celui du dessin, sinon celui
    du champ des coins vifs, sinon `defaut`."""
    rayon = float(rect.get('rayon') or 0.0)
    if rayon > 0:
        return rayon
    if valeurs and 'rayon_coins_vifs' in valeurs:
        return float(valeurs['rayon_coins_vifs'])
    return defaut


def cote_decoupe(libelle: str) -> str:
    """« Extérieur » → Outside (ce que le paramètre `side` attend)."""
    return dict(COTES_DECOUPE).get(str(libelle), "Outside")


def reglages_points(op_type: str, valeurs: Dict) -> Dict:
    """Les paramètres que le formulaire pose sur l'opération."""
    v = valeurs or {}
    sortie = {}
    if 'depth' in v:
        sortie['depth'] = float(v['depth'])
    if 'infeed_z' in v:
        sortie['infeed_z'] = float(v['infeed_z'])
    if op_type == "taraudage" and v.get('thread_name'):
        sortie['thread_name'] = str(v['thread_name'])
    if op_type == "filetage_special":
        if 'pitch' in v:
            sortie['pitch'] = float(v['pitch'])
        if v.get('inside_outside'):
            sortie['inside_outside'] = (
                "Outside" if v['inside_outside'] in ("Extérieur", "Outside")
                else "Inside")
    if 'ebav' in v and op_type in ("taraudage", "percage_fraise",
                                   "percage_foret"):
        sortie['use_ebav'] = bool(v['ebav'])
    return sortie


def reglages_rectangle(op_type: str, valeurs: Dict, rect: Dict) -> Dict:
    """Largeurs (offset compris), profondeur, côté pour un rectangle."""
    v = valeurs or {}
    decal = float(v.get('offset', 0.0) or 0.0)
    sortie = {'width_x': round(float(rect['width']) + 2 * decal, 4),
              'width_y': round(float(rect['height']) + 2 * decal, 4)}
    if 'depth' in v:
        sortie['depth'] = float(v['depth'])
    if op_type == "decoupe_rectangle" and v.get('side'):
        sortie['side'] = cote_decoupe(v['side'])
    return sortie


def outil_avant_trou(bibliotheque, diametre: float,
                     profondeur: float) -> Optional[str]:
    """La fraise de l'avant-trou: la plus grosse ≤ 0,8 × Ø qui
    descend assez (comme les trous d'une pièce STEP)."""
    if bibliotheque is None:
        return None
    from src.core import usinage_faces
    return usinage_faces.fraise(bibliotheque, 0.8 * float(diametre),
                                float(profondeur))


def op_avant_trou(valeurs: Dict, points: Sequence[Dict],
                  bibliotheque=None) -> Optional[Dict]:
    """L'opération « perçage fraise » de l'avant-trou d'un taraudage
    (au format de operations_generated), ou None si on n'en veut pas."""
    v = valeurs or {}
    if not v.get('avant_trou'):
        return None
    filet = str(v.get('thread_name') or "M4")
    d = AVANT_TROU.get(filet)
    if not d:
        return None
    prof = float(v.get('profondeur_avant_trou')
                 or profondeur_avant_trou(filet, v.get('depth', 6.0)))
    pts = [{'x': float(p['x']), 'y': float(p['y'])} for p in points]
    op = {'operation_type': 'percage_fraise',
          'name': f"Avant-trou {filet} Ø{d:g} ({len(pts)}pts)",
          'x': pts[0]['x'] if pts else 0.0,
          'y': pts[0]['y'] if pts else 0.0,
          'params': {'diameter': d, 'depth': prof},
          'points': pts}
    tid = outil_avant_trou(bibliotheque, d, prof)
    if tid:
        op['tool_id'] = tid
    return op


def grouper(ops: List[Dict], valeurs: Dict) -> List[Dict]:
    """Les opérations créées, en un ensemble de la liste (si on le
    demande et qu'il y en a plusieurs). Un ensemble de types ou
    d'outils DIFFÉRENTS (un filet et son avant-trou) est « libre »:
    l'outil n'y est pas commun."""
    if not valeurs or not valeurs.get('grouper') or len(ops) < 2:
        return ops
    import uuid
    gid = str(uuid.uuid4())[:8]
    nom = str(valeurs.get('nom_groupe') or ops[0]['name'])
    libre = (len({o['operation_type'] for o in ops}) > 1
             or len({o.get('tool_id') or '' for o in ops}) > 1)
    for o in ops:
        o['group_id'] = gid
        o['group_name'] = nom
        if libre:
            o['group_libre'] = True
    return ops
