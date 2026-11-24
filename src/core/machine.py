"""La machine: une DATRON neo décrite par ses cotes, que l'atelier règle
et améliore — courses, table et rainures, broche (corps, nez, écrou de
pince), longueur de serrage des outils — et dont le bâti et la broche
peuvent être remplacés par des STEP.

Elle sert à VOIR la pièce dans la machine (Canva 3D: table, étau ou
mandrin, enveloppe des courses, broche à la position de l'outil) et à
vérifier que la broche et le porte-outil ne touchent rien
(src/core/collisions.py).

Un fichier: « Machine/machine.json » à côté de l'exe (ses STEP à côté).
Les cotes par défaut sont celles d'une neo à vérifier à l'atelier.

Repère: celui du PROGRAMME (zéro pièce). La broche se décrit depuis la
face de l'écrou de pince (là où l'outil sort) vers le haut.
"""

import json
import math
import os
from typing import Dict, List, Optional, Tuple

import numpy as np

DOSSIER = "Machine"
FICHIER = "machine.json"
#: couleurs (0–1)
TABLE = (0.27, 0.29, 0.36)
RAINURE = (0.16, 0.17, 0.22)
BROCHE = (0.80, 0.82, 0.88)
ECROU = (0.95, 0.80, 0.45)
BATI = (0.45, 0.48, 0.56)


def dossier() -> str:
    detour = os.environ.get('NEODRIVE_MACHINE_DIR')
    if detour:
        return detour
    reglages = os.environ.get('NEODRIVE_APP_SETTINGS')
    if reglages:
        return os.path.join(os.path.dirname(reglages), DOSSIER)
    from src.core.tool_library import get_base_dir
    return os.path.join(get_base_dir(), DOSSIER)


def defaut() -> Dict:
    return {
        'nom': "DATRON neo",
        # courses X, Y, Z (mm)
        'course_x': 520.0, 'course_y': 420.0, 'course_z': 220.0,
        # la table: ses cotes, ses rainures (le long de X)
        'table_longueur': 600.0, 'table_largeur': 480.0,
        'table_epaisseur': 40.0, 'rainure_pas': 50.0,
        'rainure_largeur': 12.0, 'rainure_profondeur': 10.0,
        # la broche, de l'écrou vers le haut
        'ecrou_diametre': 25.0, 'ecrou_hauteur': 15.0,
        'nez_diametre': 45.0, 'nez_hauteur': 25.0,
        'broche_diametre': 80.0, 'broche_longueur': 200.0,
        # l'outil: ce que la pince serre de sa queue
        'pince_longueur': 15.0,
        # la plus haute position de l'écrou au-dessus de la table
        'z_max_ecrou': 250.0,
        # le temps machine du Canva 3D: rapides (mm/min), changement
        # d'outil (s)
        'vitesse_rapide': 20000.0, 'changement_outil_s': 15.0,
        # STEP du bâti et de la broche (relatifs au dossier), décalés
        'step_bati': "", 'step_bati_decalage': [0.0, 0.0, 0.0],
        'step_broche': "", 'step_broche_decalage': [0.0, 0.0, 0.0],
        'notes': "Cotes par défaut à vérifier sur la machine."}


def normaliser(d) -> Dict:
    m = defaut()
    if not isinstance(d, dict):
        return m
    for cle, val in m.items():
        if cle not in d:
            continue
        if isinstance(val, float):
            try:
                m[cle] = float(d[cle])
            except (TypeError, ValueError):
                pass
        elif isinstance(val, list):
            try:
                v = [float(a) for a in d[cle]][:3]
                m[cle] = v + [0.0] * (3 - len(v))
            except (TypeError, ValueError):
                pass
        else:
            m[cle] = str(d[cle] or "")
    return m


def charger() -> Dict:
    """La machine de l'atelier (ses cotes par défaut sans fichier)."""
    try:
        with open(os.path.join(dossier(), FICHIER), encoding='utf-8') as f:
            return normaliser(json.load(f))
    except (OSError, ValueError):
        return defaut()


def enregistrer(machine: Dict) -> str:
    os.makedirs(dossier(), exist_ok=True)
    chemin = os.path.join(dossier(), FICHIER)
    from src.core.fichiers_surs import ecrire_json_sur
    ecrire_json_sur(chemin, normaliser(machine), garder_bak=True, indent=2,
                    ensure_ascii=False)
    return chemin


def chemin_step(machine: Dict, cle: str) -> Optional[str]:
    s = str(machine.get(cle) or '')
    if not s:
        return None
    chemin = s if os.path.isabs(s) else os.path.join(dossier(), s)
    return chemin if os.path.isfile(chemin) else None


def importer_step(machine: Dict, cle: str, chemin: str) -> Dict:
    """Copie un STEP (bâti ou broche) dans le dossier et le rattache."""
    import shutil
    os.makedirs(dossier(), exist_ok=True)
    cible = os.path.join(dossier(), os.path.basename(chemin))
    if os.path.abspath(cible) != os.path.abspath(chemin):
        shutil.copy2(chemin, cible)
    m = dict(machine)
    m[cle] = os.path.basename(chemin)
    return m


# ───────────────────────── l'outil dans la broche ─────────────────────────

def depassement(machine: Dict, cotes: Dict) -> float:
    """La longueur d'outil sous l'écrou: sa longueur totale moins ce que
    la pince serre — jamais moins que sa longueur utile (ou de coupe)."""
    L1 = float(cotes.get('L1') or 0.0)
    utile = max(float(cotes.get('L3') or 0.0), float(cotes.get('L2') or 0.0))
    return max(L1 - float(machine.get('pince_longueur', 15.0)), utile + 1.0,
               1.0)


def pile_broche(machine: Dict) -> List[Tuple[str, float, float, float]]:
    """[(nom, rayon, z0, z1)] de ce qui est au-dessus de l'outil, depuis
    la face de l'écrou: l'écrou de pince, le nez de broche, la broche."""
    m = normaliser(machine)
    he, hn = m['ecrou_hauteur'], m['nez_hauteur']
    return [("écrou de pince", m['ecrou_diametre'] / 2, 0.0, he),
            ("nez de broche", m['nez_diametre'] / 2, he, he + hn),
            ("broche", m['broche_diametre'] / 2, he + hn,
             he + hn + m['broche_longueur'])]


# ───────────────────────── la géométrie ─────────────────────────

def _boite(x0, x1, y0, y1, z0, z1) -> np.ndarray:
    from src.core.tenue import _boite as b
    return b(x0, x1, y0, y1, z0, z1)


def _step(chemin: str, decalage) -> np.ndarray:
    try:
        from src.io.vecteur import step3d
        T = np.asarray(step3d.lire_modele(chemin).triangles, dtype=float)
        return T + np.asarray(decalage, dtype=float)
    except Exception:
        return np.zeros((0, 3, 3))


def triangles_table(machine: Dict, centre_xy=(0.0, 0.0), z_dessus: float = 0.0
                    ) -> Tuple[np.ndarray, np.ndarray]:
    """La table (et ses rainures en creux, en bandes sombres), son dessus
    en `z_dessus`, centrée sous `centre_xy` — ou le bâti STEP."""
    m = normaliser(machine)
    step = chemin_step(m, 'step_bati')
    if step is not None:
        T = _step(step, m['step_bati_decalage'])
        if len(T):
            T = T + np.array([centre_xy[0], centre_xy[1], z_dessus])
            return T, np.tile(BATI, (len(T), 1))
    cx, cy = centre_xy
    L, W, E = m['table_longueur'], m['table_largeur'], m['table_epaisseur']
    morceaux, couleurs = [], []
    T = _boite(cx - L / 2, cx + L / 2, cy - W / 2, cy + W / 2,
               z_dessus - E, z_dessus - m['rainure_profondeur'])
    morceaux.append(T)
    couleurs.append(np.tile(TABLE, (len(T), 1)))
    # le dessus, entre les rainures
    pas, lr = m['rainure_pas'], m['rainure_largeur']
    n = max(1, int(W // max(pas, 1.0)))
    ys = [cy - (n - 1) * pas / 2 + k * pas for k in range(n)]
    bords = [cy - W / 2] + sum([[y - lr / 2, y + lr / 2] for y in ys], []) + \
        [cy + W / 2]
    for k in range(0, len(bords), 2):
        y0, y1 = bords[k], bords[k + 1]
        if y1 - y0 > 0.1:
            B = _boite(cx - L / 2, cx + L / 2, y0, y1,
                       z_dessus - m['rainure_profondeur'], z_dessus)
            morceaux.append(B)
            couleurs.append(np.tile(TABLE, (len(B), 1)))
    for y in ys:
        F = _boite(cx - L / 2, cx + L / 2, y - lr / 2, y + lr / 2,
                   z_dessus - m['rainure_profondeur'] - 0.01,
                   z_dessus - m['rainure_profondeur'])
        morceaux.append(F)
        couleurs.append(np.tile(RAINURE, (len(F), 1)))
    return np.concatenate(morceaux), np.concatenate(couleurs)


def triangles_broche(machine: Dict, x: float, y: float, z_ecrou: float,
                     n: int = 32) -> Tuple[np.ndarray, np.ndarray]:
    """La broche, l'écrou de pince en (x, y, z_ecrou) — ou son STEP."""
    from src.core.serrages import _cylindre
    m = normaliser(machine)
    step = chemin_step(m, 'step_broche')
    if step is not None:
        T = _step(step, m['step_broche_decalage'])
        if len(T):
            T = T + np.array([x, y, z_ecrou])
            return T, np.tile(BROCHE, (len(T), 1))
    morceaux, couleurs = [], []
    for k, (nom, r, z0, z1) in enumerate(pile_broche(m)):
        C = _cylindre(r, z_ecrou + z0, z_ecrou + z1, n=n, cx=x, cy=y)
        morceaux.append(C)
        couleurs.append(np.tile(ECROU if k == 0 else BROCHE, (len(C), 1)))
    return np.concatenate(morceaux), np.concatenate(couleurs)


def fil_broche(machine: Dict, x: float, y: float, z_ecrou: float
               ) -> List[np.ndarray]:
    """La broche en fil (anneaux et génératrices), pour la lecture."""
    sortie = []
    t = np.linspace(0, 2 * math.pi, 33)
    for nom, r, z0, z1 in pile_broche(machine):
        z1 = min(z1, z0 + 60.0)             # le corps: son bas suffit
        for z in (z_ecrou + z0, z_ecrou + z1):
            sortie.append(np.column_stack([x + r * np.cos(t),
                                           y + r * np.sin(t),
                                           np.full(len(t), z)]))
        for a in np.linspace(0, 2 * math.pi, 5)[:-1]:
            sortie.append(np.array([
                (x + r * math.cos(a), y + r * math.sin(a), z_ecrou + z0),
                (x + r * math.cos(a), y + r * math.sin(a), z_ecrou + z1)]))
    return sortie


def enveloppe(machine: Dict, centre_xy=(0.0, 0.0), z_table: float = 0.0
              ) -> List[np.ndarray]:
    """Les arêtes du volume des courses (posé sur la table, centré)."""
    m = normaliser(machine)
    cx, cy = centre_xy
    x0, x1 = cx - m['course_x'] / 2, cx + m['course_x'] / 2
    y0, y1 = cy - m['course_y'] / 2, cy + m['course_y'] / 2
    z0, z1 = z_table, z_table + m['course_z']
    bas = np.array([(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
                    (x0, y0, z0)])
    haut = bas.copy()
    haut[:, 2] = z1
    sortie = [bas, haut]
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        sortie.append(np.array([(x, y, z0), (x, y, z1)]))
    return sortie


def mise_en_place(brut_boite, serrage: Optional[Dict]) -> Dict:
    """Où sont le dispositif de serrage et la table sous le brut
    (xmin, xmax, ymin, ymax, zmin, zmax): le dispositif serre le bas du
    brut sur sa prise, centré; sans dispositif, le brut est sur la
    table. Rend {'serrage': (triangles, couleurs) ou None, 'z_table',
    'centre', 'ouverture', 'hors_course'}."""
    from src.core import serrages as sg
    xmin, xmax, ymin, ymax, zmin, zmax = (float(v) for v in brut_boite)
    cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
    p = sg.normaliser(serrage) if serrage else None
    if p is None:
        return {'serrage': None, 'z_table': zmin, 'centre': (cx, cy),
                'ouverture': None, 'hors_course': None}
    lx, ly = xmax - xmin, ymax - ymin
    if p['genre'] == 'etau':
        largeur, longueur = (lx, ly) if p.get('axe') == 'X' else (ly, lx)
    else:
        largeur, longueur = lx, ly
    o = sg.ouverture_pour(p, largeur, longueur)
    haut_mors = zmin + float(p['prise'])
    T, C = sg.triangles(p, o, (cx, cy, haut_mors))
    z_table = float(T[:, :, 2].min()) if len(T) else zmin
    return {'serrage': (T, C), 'z_table': z_table, 'centre': (cx, cy),
            'ouverture': o, 'hors_course': sg.hors_course(p, largeur,
                                                          longueur)}
