"""Les moyens de serrage: étaux autocentrés et mandrins.

Chacun est un fichier JSON du dossier « Étaux et mandrins » à côté de
l'exe (comme les plaques de reprise). Il se décrit par ses cotes — un
modèle 3D tout de suite — et son CORPS peut être remplacé par le STEP du
fabricant (les mors, eux, restent paramétriques: ils bougent).

    {"nom": "Étau autocentré 125", "genre": "etau",
     "largeur_mors": 125, "hauteur_mors": 40, "epaisseur_mors": 25,
     "ouverture_min": 0, "ouverture_max": 160, "prise": 3,
     "longueur_base": 250, "largeur_base": 160, "hauteur_base": 60,
     "axe": "Y", "step": "", "step_decalage": [0, 0, 0], "notes": ""}

    {"nom": "Mandrin 3 mors 160", "genre": "mandrin",
     "diametre": 160, "hauteur": 80, "mors": 3, "hauteur_mors": 30,
     "largeur_mors": 20, "longueur_mors": 40, "serrage_min": 2,
     "serrage_max": 150, "prise": 5, "step": "", ...}

Repère du dispositif: X/Y au CENTRE du serrage (entre les mors, l'axe du
mandrin), Z = 0 au DESSUS des mors; le corps est dessous. « prise »: la
hauteur de pièce que les mors serrent.
"""

import json
import math
import os
import re
from typing import Dict, List, Optional, Tuple

import numpy as np

#: le dossier, à côté de l'exe
DOSSIER = "Étaux et mandrins"
GENRES = (("etau", "Étau autocentré"), ("mandrin", "Mandrin"))
#: couleurs (0–1)
CORPS = (0.36, 0.40, 0.50)
MORS = (0.62, 0.66, 0.74)


def dossier() -> str:
    """Le dossier des étaux et mandrins — à côté des réglages de test
    quand NEODRIVE_APP_SETTINGS les détourne."""
    detour = os.environ.get('NEODRIVE_SERRAGES_DIR')
    if detour:
        return detour
    reglages = os.environ.get('NEODRIVE_APP_SETTINGS')
    if reglages:
        return os.path.join(os.path.dirname(reglages), DOSSIER)
    from src.core.tool_library import get_base_dir
    return os.path.join(get_base_dir(), DOSSIER)


def nouvel_etau(nom: str = "Étau autocentré") -> Dict:
    return {'nom': nom, 'genre': 'etau', 'largeur_mors': 125.0,
            'hauteur_mors': 40.0, 'epaisseur_mors': 25.0,
            'ouverture_min': 0.0, 'ouverture_max': 160.0, 'prise': 3.0,
            'longueur_base': 250.0, 'largeur_base': 160.0,
            'hauteur_base': 60.0, 'axe': 'Y', 'step': "",
            'step_decalage': [0.0, 0.0, 0.0], 'notes': ""}


def nouveau_mandrin(nom: str = "Mandrin 3 mors") -> Dict:
    return {'nom': nom, 'genre': 'mandrin', 'diametre': 160.0,
            'hauteur': 80.0, 'mors': 3, 'hauteur_mors': 30.0,
            'largeur_mors': 20.0, 'longueur_mors': 40.0,
            'serrage_min': 2.0, 'serrage_max': 150.0, 'prise': 5.0,
            'step': "", 'step_decalage': [0.0, 0.0, 0.0], 'notes': ""}


def normaliser(d) -> Optional[Dict]:
    """Un dispositif lu (ce qui manque prend son défaut), ou None."""
    if not isinstance(d, dict):
        return None
    genre = d.get('genre', 'etau')
    if genre not in ('etau', 'mandrin'):
        return None
    p = nouvel_etau() if genre == 'etau' else nouveau_mandrin()
    p['nom'] = str(d.get('nom') or p['nom'])
    for cle, val in p.items():
        if cle in ('nom', 'genre'):
            continue
        if cle not in d:
            continue
        if isinstance(val, float):
            try:
                p[cle] = float(d[cle])
            except (TypeError, ValueError):
                pass
        elif isinstance(val, int) and not isinstance(val, bool):
            try:
                p[cle] = max(2, int(d[cle]))
            except (TypeError, ValueError):
                pass
        elif cle == 'step_decalage':
            try:
                p[cle] = [float(v) for v in d[cle]][:3] + \
                    [0.0] * max(0, 3 - len(d[cle]))
            except (TypeError, ValueError):
                pass
        else:
            p[cle] = str(d[cle]) if d[cle] is not None else ""
    if p.get('axe') not in (None, 'X', 'Y'):
        p['axe'] = 'Y'
    return p


def _nom_de_fichier(nom: str) -> str:
    import unicodedata
    t = unicodedata.normalize('NFKD', str(nom))
    t = t.encode('ascii', 'ignore').decode('ascii')
    return (re.sub(r'[^A-Za-z0-9._-]+', '_', t).strip('._') or "serrage")


def lister() -> List[Tuple[str, str]]:
    """[(nom, chemin)] des dispositifs du dossier."""
    d = dossier()
    if not os.path.isdir(d):
        return []
    sortie = []
    for f in sorted(os.listdir(d)):
        if f.lower().endswith('.json'):
            p = charger(os.path.join(d, f))
            if p is not None:
                sortie.append((p['nom'], os.path.join(d, f)))
    return sortie


def charger(chemin: str) -> Optional[Dict]:
    try:
        with open(chemin, encoding='utf-8') as f:
            return normaliser(json.load(f))
    except (OSError, ValueError):
        return None


def par_nom(nom: str) -> Optional[Dict]:
    for n, chemin in lister():
        if n == nom:
            return charger(chemin)
    return None


def enregistrer(dispositif: Dict, chemin: str = None) -> str:
    p = normaliser(dispositif)
    if p is None:
        raise ValueError("ce n'est pas un étau ni un mandrin")
    d = dossier()
    os.makedirs(d, exist_ok=True)
    chemin = chemin or os.path.join(d, _nom_de_fichier(p['nom']) + ".json")
    from src.core.fichiers_surs import ecrire_json_sur
    ecrire_json_sur(chemin, p, indent=2, ensure_ascii=False)
    return chemin


def supprimer(chemin: str) -> bool:
    try:
        os.remove(chemin)
        return True
    except OSError:
        return False


def chemin_step(dispositif: Dict) -> Optional[str]:
    """Le STEP du corps (relatif au dossier, ou absolu), s'il existe."""
    s = str(dispositif.get('step') or '')
    if not s:
        return None
    chemin = s if os.path.isabs(s) else os.path.join(dossier(), s)
    return chemin if os.path.isfile(chemin) else None


def importer_step(dispositif: Dict, chemin: str) -> Dict:
    """Copie le STEP du corps dans le dossier et le rattache."""
    import shutil
    d = dossier()
    os.makedirs(d, exist_ok=True)
    nom = _nom_de_fichier(os.path.splitext(os.path.basename(chemin))[0]) \
        + os.path.splitext(chemin)[1].lower()
    cible = os.path.join(d, nom)
    if os.path.abspath(cible) != os.path.abspath(chemin):
        shutil.copy2(chemin, cible)
    p = dict(dispositif)
    p['step'] = nom
    return p


# ───────────────────────── la géométrie ─────────────────────────

def _boite(x0, x1, y0, y1, z0, z1) -> np.ndarray:
    from src.core.tenue import _boite as b
    return b(x0, x1, y0, y1, z0, z1)


def _cylindre(r: float, z0: float, z1: float, n: int = 48,
              cx: float = 0.0, cy: float = 0.0) -> np.ndarray:
    t = np.linspace(0, 2 * math.pi, n + 1)
    p = np.column_stack([cx + r * np.cos(t), cy + r * np.sin(t)])
    tri = []
    for k in range(n):
        a, b = p[k], p[k + 1]
        tri.append([(a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], z1)])
        tri.append([(a[0], a[1], z0), (b[0], b[1], z1), (a[0], a[1], z1)])
        tri.append([(cx, cy, z1), (a[0], a[1], z1), (b[0], b[1], z1)])
        tri.append([(cx, cy, z0), (b[0], b[1], z0), (a[0], a[1], z0)])
    return np.asarray(tri, dtype=float)


def _boite_tournee(x0, x1, y0, y1, z0, z1, angle: float) -> np.ndarray:
    B = _boite(x0, x1, y0, y1, z0, z1)
    c, s = math.cos(angle), math.sin(angle)
    R = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]])
    return B @ R.T


def ouverture_bornee(dispositif: Dict, ouverture: float) -> float:
    """L'ouverture (étau) ou le Ø de serrage (mandrin), dans sa course."""
    if dispositif.get('genre') == 'mandrin':
        mini, maxi = dispositif['serrage_min'], dispositif['serrage_max']
    else:
        mini, maxi = dispositif['ouverture_min'], dispositif['ouverture_max']
    return float(min(max(float(ouverture), mini), maxi))


def triangles(dispositif: Dict, ouverture: float = None,
              centre=(0.0, 0.0, 0.0), corps_step: bool = True
              ) -> Tuple[np.ndarray, np.ndarray]:
    """(triangles, couleurs) du dispositif, l'ouverture (étau) ou le Ø de
    serrage (mandrin) donné, son centre de serrage en `centre` (dessus
    des mors). Le corps vient du STEP s'il y en a un."""
    p = normaliser(dispositif)
    if p is None:
        return np.zeros((0, 3, 3)), np.zeros((0, 3))
    if ouverture is None:
        ouverture = (p['serrage_max'] if p['genre'] == 'mandrin'
                     else p['ouverture_max']) / 2.0
    o = ouverture_bornee(p, ouverture)
    hm = p['hauteur_mors']
    corps, mors = [], []
    if p['genre'] == 'etau':
        l, e = p['largeur_mors'], p['epaisseur_mors']
        mors.append(_boite(-l / 2, l / 2, o / 2, o / 2 + e, -hm, 0.0))
        mors.append(_boite(-l / 2, l / 2, -o / 2 - e, -o / 2, -hm, 0.0))
        lb, wb, hb = p['longueur_base'], p['largeur_base'], p['hauteur_base']
        corps.append(_boite(-lb / 2, lb / 2, -wb / 2, wb / 2, -hm - hb, -hm))
    else:
        n = int(p['mors'])
        for k in range(n):
            a = math.pi / 2 + 2 * math.pi * k / n
            r0 = o / 2
            mors.append(_boite_tournee(r0, r0 + p['longueur_mors'],
                                       -p['largeur_mors'] / 2,
                                       p['largeur_mors'] / 2, -hm, 0.0,
                                       a))
        corps.append(_cylindre(p['diametre'] / 2, -hm - p['hauteur'], -hm))
    step = chemin_step(p) if corps_step else None
    if step is not None:
        try:
            from src.io.vecteur import step3d
            m = step3d.lire_modele(step)
            T = np.asarray(m.triangles, dtype=float)
            if len(T):
                T = T + np.asarray(p['step_decalage'], dtype=float)
                corps = [T]
        except Exception:
            pass
    T = np.concatenate(corps + mors) if corps + mors else np.zeros((0, 3, 3))
    C = np.concatenate([np.tile(CORPS, (sum(len(c) for c in corps), 1)),
                        np.tile(MORS, (sum(len(m) for m in mors), 1))])
    if p['genre'] == 'etau' and p.get('axe') == 'X':
        # les mors serrent en X: un quart de tour autour de Z
        R = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1.0]])
        T = T @ R.T
    T = T + np.asarray(centre, dtype=float)
    return T, C


def ouverture_pour(dispositif: Dict, largeur: float, longueur: float = None
                   ) -> float:
    """L'ouverture qui serre une pièce: sa largeur dans l'axe des mors
    (étau), son plus grand côté — le cercle qui la contient — (mandrin)."""
    p = normaliser(dispositif) or {}
    if p.get('genre') == 'mandrin':
        d = math.hypot(largeur, longueur if longueur is not None else largeur)
        return ouverture_bornee(p, d)
    return ouverture_bornee(p, largeur)


def hors_course(dispositif: Dict, largeur: float, longueur: float = None
                ) -> Optional[str]:
    """Pourquoi la pièce ne se serre pas (trop large, trop petite), ou
    None."""
    p = normaliser(dispositif)
    if p is None:
        return None
    if p['genre'] == 'mandrin':
        d = math.hypot(largeur, longueur if longueur is not None else largeur)
        if d > p['serrage_max'] + 1e-9:
            return (f"Ø {d:.1f} mm au-delà du serrage maxi "
                    f"({p['serrage_max']:g} mm)")
        if d < p['serrage_min'] - 1e-9:
            return f"Ø {d:.1f} mm sous le serrage mini ({p['serrage_min']:g})"
        return None
    if largeur > p['ouverture_max'] + 1e-9:
        return (f"{largeur:.1f} mm au-delà de l'ouverture maxi "
                f"({p['ouverture_max']:g} mm)")
    if largeur < p['ouverture_min'] - 1e-9:
        return f"{largeur:.1f} mm sous l'ouverture mini ({p['ouverture_min']:g})"
    return None
