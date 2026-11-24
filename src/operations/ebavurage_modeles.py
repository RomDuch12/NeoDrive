# -*- coding: utf-8 -*-
"""Les modèles d'ébavurage: un outil, un offset, une profondeur —
sous un nom, dans data/ebavurage.json.

Un clic droit sur une découpe, une poche ou un contour propose
« Ébavurer avec… » et la liste des modèles: l'opération d'ébavurage
se crée à la suite, avec la géométrie de sa source (le rectangle
agrandi de deux fois l'offset, le cercle, les contours) et le côté
qui va de soi — dehors pour une découpe, dedans pour une poche —
ou demandé, pour un contour.

Trois modèles sont livrés; ceux de l'atelier s'enregistrent depuis
le formulaire de l'ébavurage.
"""

import os
from typing import Any, Dict, List, Optional

#: les modèles livrés — l'outil par son nom, à retrouver dans la
#: bibliothèque (ou un outil du même genre)
LIVRES: Dict[str, Dict[str, Any]] = {
    "Extrad — offset 1": {
        'outil': "ExtRad 3 z2 r0.3", 'offset': 1.0, 'depth': 0.2},
    "Chanfrein 90° — 0,3": {
        'outil': "Chamfer 90° z3L3", 'offset': 0.3, 'depth': 0.3},
    "Con 30° 0.2 — 0,2": {
        'outil': "Con 30° 0.2", 'offset': 0.2, 'depth': 0.2},
}

#: ce qu'un modèle retient
CHAMPS = ('outil', 'offset', 'depth')


def chemin() -> str:
    """`data/ebavurage.json` à côté de l'exe — ou à côté des réglages
    de test quand NEODRIVE_APP_SETTINGS les détourne."""
    detour = os.environ.get('NEODRIVE_APP_SETTINGS')
    if detour:
        return os.path.join(os.path.dirname(detour), "ebavurage.json")
    from src.core.tool_library import get_base_dir
    return os.path.join(get_base_dir(), 'data', 'ebavurage.json')


def _lire() -> Dict[str, Dict[str, Any]]:
    from src.core.fichiers_surs import lire_json
    lu = lire_json(chemin(), {})
    modeles = lu.get('modeles') if isinstance(lu, dict) else None
    if not isinstance(modeles, dict):
        return {}
    return {str(k): dict(v) for k, v in modeles.items()
            if isinstance(v, dict)}


def _ecrire(modeles: Dict[str, Dict[str, Any]]) -> None:
    from src.core.fichiers_surs import ecrire_json_sur
    ecrire_json_sur(chemin(), {'modeles': modeles}, garder_bak=True,
                    ensure_ascii=False, indent=2)


def charger() -> Dict[str, Dict[str, Any]]:
    """Les modèles livrés, puis ceux de l'utilisateur (un modèle de
    l'utilisateur du même nom l'emporte)."""
    modeles = {nom: dict(m) for nom, m in LIVRES.items()}
    modeles.update(_lire())
    return modeles


def noms() -> List[str]:
    return list(charger().keys())


def modele(nom: str) -> Optional[Dict[str, Any]]:
    return charger().get(nom)


def est_livre(nom: str) -> bool:
    return nom in LIVRES and nom not in _lire()


def sauver_modele(nom: str, reglages: Dict[str, Any]) -> None:
    nom = str(nom or "").strip()
    if not nom:
        raise ValueError("un modèle a un nom")
    modeles = _lire()
    modeles[nom] = {cle: reglages.get(cle) for cle in CHAMPS
                    if cle in reglages}
    _ecrire(modeles)


def supprimer_modele(nom: str) -> bool:
    """Retire un modèle de l'utilisateur; un modèle livré ne se
    supprime pas (il se recouvre par un modèle du même nom)."""
    modeles = _lire()
    if nom not in modeles:
        return False
    del modeles[nom]
    _ecrire(modeles)
    return True


# ── de la source à l'opération ──

def genre_outil(nom: str) -> str:
    """'extrad', 'chamfer', 'con' ou ''."""
    bas = str(nom or "").lower()
    if 'extrad' in bas:
        return 'extrad'
    if 'cham' in bas or 'chanfrein' in bas:
        return 'chamfer'
    if bas.startswith('con') or ' con' in bas:
        return 'con'
    return ''


def outil_du_modele(mdl: Dict[str, Any], bibliotheque) -> str:
    """L'identifiant de l'outil du modèle: par son nom, sinon le
    premier outil du même genre, sinon rien."""
    from src.operations.gamme_postes import _normaliser
    voulu = str(mdl.get('outil') or "")
    if not voulu or bibliotheque is None:
        return ""
    outils = getattr(bibliotheque, 'tools', {})
    cible = _normaliser(voulu)
    for identifiant, outil in outils.items():
        if _normaliser(outil.name) == cible:
            return identifiant
    genre = genre_outil(voulu)
    if genre:
        for identifiant, outil in outils.items():
            if genre_outil(outil.name) == genre:
                return identifiant
    return ""


def geometrie_de(source) -> Optional[Dict[str, Any]]:
    """Ce que l'ébavurage reprend de sa source: {'forme', 'x', 'y',
    et 'width_x'/'width_y'/'corner_radius', ou 'diameter', ou
    'contours'} — None si la source n'a rien à ébavurer."""
    from src.operations.ebavurage import FORMES
    genre = getattr(source, 'operation_type', '')
    p = getattr(source, 'params', {}) or {}

    def _f(cle, defaut=0.0):
        try:
            return float(p.get(cle, defaut) or 0.0)
        except (TypeError, ValueError):
            return float(defaut)
    x = float(getattr(source, 'x', 0.0) or 0.0)
    y = float(getattr(source, 'y', 0.0) or 0.0)
    points = getattr(source, 'points', None) or []
    if points:
        x = float(points[0].get('x', x))
        y = float(points[0].get('y', y))
    if genre in ("decoupe_rectangle", "poche_rectangle",
                 "surfacage_rectangle"):
        largeur, hauteur = _f('width_x'), _f('width_y')
        if genre == "surfacage_rectangle":
            largeur += 2 * _f('extension_x')
            hauteur += 2 * _f('extension_y')
        if largeur <= 0 or hauteur <= 0:
            return None
        return {'forme': FORMES[0], 'x': x, 'y': y,
                'width_x': largeur, 'width_y': hauteur,
                'corner_radius': _f('corner_radius')}
    if genre in ("decoupe_cercle", "surfacage_cercle", "percage_fraise"):
        d = _f('diameter')
        if d <= 0:
            return None
        return {'forme': FORMES[1], 'x': x, 'y': y, 'diameter': d}
    try:
        from src.operations.registry import OperationRegistry
        classe = OperationRegistry.get(genre)
        contours = classe.contours(p)
    except Exception:
        contours = []
    if not contours:
        return None
    xs = [px for c in contours for px, _py in c]
    ys = [py for c in contours for _px, py in c]
    return {'forme': FORMES[2],
            'x': round((min(xs) + max(xs)) / 2.0, 4),
            'y': round((min(ys) + max(ys)) / 2.0, 4),
            'contours': [[[round(px, 4), round(py, 4)] for px, py in c]
                         for c in contours]}


def repetition_de(source) -> Dict[str, Any]:
    """La répétition (deux niveaux) de la source, telle quelle."""
    from src.core import repetition
    p = getattr(source, 'params', {}) or {}
    return {cle: p[cle] for cle in repetition.CLES if cle in p}


def cote_de(source) -> Optional[str]:
    """Le côté qui va de soi pour cette source, ou None si on
    demande: dehors pour une découpe, dedans pour une poche ou un
    trou; un cercle découpé suit son côté d'usinage."""
    from src.operations.ebavurage import SOURCES, COTES
    genre = getattr(source, 'operation_type', '')
    cote = SOURCES.get(genre)
    if cote is not None:
        return cote
    if genre == "decoupe_cercle":
        side = str((getattr(source, 'params', {}) or {}).get('side', ''))
        if side == "Outside":
            return COTES[0]
        if side == "Inside":
            return COTES[1]
    return None


def creer_ebavurage(source, nom_modele: str, bibliotheque,
                    cote: Optional[str] = None):
    """L'opération d'ébavurage d'une source, réglée par un modèle.
    Rend None si la source n'a rien à ébavurer ou si le modèle est
    inconnu."""
    from src.core.program_model import OperationInstance
    from src.operations.ebavurage import Ebavurage, COTES
    mdl = modele(nom_modele)
    geometrie = geometrie_de(source)
    if mdl is None or geometrie is None:
        return None
    op = OperationInstance("ebavurage",
                           f"Ébavurage — {getattr(source, 'name', '')}")
    op.params = dict(Ebavurage.get_default_params())
    op.params.update({k: v for k, v in geometrie.items()
                      if k not in ('x', 'y')})
    op.params['cote'] = cote or cote_de(source) or COTES[0]
    op.params['source_id'] = str(getattr(source, 'id', '') or '')
    # la répétition de la source: une découpe répétée s'ébavure
    # partout où elle est faite
    op.params.update(repetition_de(source))
    for cle in ('offset', 'depth'):
        if mdl.get(cle) is not None:
            try:
                op.params[cle] = float(mdl[cle])
            except (TypeError, ValueError):
                pass
    op.tool_id = outil_du_modele(mdl, bibliotheque)
    op.x, op.y = geometrie['x'], geometrie['y']
    op.z = float(getattr(source, 'z', 15.0) or 15.0)
    return op
