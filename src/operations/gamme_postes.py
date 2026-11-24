# -*- coding: utf-8 -*-
"""Les postes d'une gamme: un outil, une opération par poste.

Une gravure fine ne se fait pas toujours avec un seul outil. La gamme
est un ENSEMBLE de la liste (voir `gamme_gravure.py` pour sa tête):
chaque poste y est une opération — un parcours avec son formulaire
détaillé; à la génération, chacun a son sous-programme (`program …`)
et sa séquence (`$$$ …`).

NeoDrive ne livre qu'une gamme de base, générique (`POSTES_BASE`).
Les gammes d'un atelier — ses outils, ses profondeurs, ses pauses —
sont des données: `data/gammes_atelier.json` (voir
`gamme_modeles.py`), et le tableau de la gamme et le formulaire de
chaque poste permettent de les changer ensuite.
"""

import re
import unicodedata
from typing import Any, Dict, List, Optional, Sequence, Tuple

from src.core import vcarve
from src.core.gamme import SOURCES_CONTOUR
from src.core.program_model import OperationInstance

#: les moments de la gamme; entre les deux, la pièce peut sortir
#: de la machine
MOMENTS = ("Gravure", "Évidement")

#: ce que toutes les opérations d'une gamme partagent: le dessin et
#: le champ. Le reste — outil, profondeur, matière laissée — est
#: propre à chaque poste.
CHAMPS_PARTAGES = ('contours', 'mode', 'pres_du_trait', 'cadre_mode',
                   'cadre_marge', 'decalage', 'cadre_largeur',
                   'cadre_hauteur', 'cadre_rayon')

#: un poste par genre, pour le bouton « + Poste » du tableau. Les
#: profondeurs sont celles de chaque opération: le formulaire du
#: poste les règle.
POSTES_MODELES = {
    "Contour": ("contour_2d5", "Cyl 2",
                dict(contour_source=SOURCES_CONTOUR[1], reprise=False)),
    "Gravure": ("gravure_2d5", "Con 30° 0.2", dict(reprise=True)),
    "Évidement": ("evidement_2d5", "Cyl 2", dict(reprise=True)),
    "Pause": ("dialogue_operateur", None,
              dict(message="Continuer ?", dialog_type="ask_continue",
                   park_before=True)),
    # le tour du CADRE, par l'extérieur: la pièce se détoure. Le
    # décalage du cadre (formulaire du poste) éloigne le passage.
    "Détourage": ("contour_2d5", "Cyl 2",
                  dict(offset_xy=0.0, contour_source=SOURCES_CONTOUR[0],
                       reprise=False)),
}


def poste(nom: str, op_type: str, outil: Optional[str],
          moment: str = MOMENTS[0], **reglages) -> Dict[str, Any]:
    """Un poste de la gamme: un outil, un genre d'opération, et ce
    qu'on y règle."""
    return {'nom': nom, 'op_type': op_type, 'outil': outil,
            'moment': moment, 'reglages': dict(reglages)}


#: la gamme de base, générique: le tour de chaque contour, la
#: gravure au V, l'évidement. Un outil par poste, retrouvé dans la
#: bibliothèque par son nom ou par sa géométrie.
POSTES_BASE: Tuple[Dict[str, Any], ...] = (
    poste("Contour", "contour_2d5", "Cyl 2", profondeur=1.0,
          contour_source=SOURCES_CONTOUR[1], reprise=False),
    poste("Gravure", "gravure_2d5", "Con 30° 0.2", profondeur_max=1.0,
          reprise=False),
    poste("Évidement", "evidement_2d5", "Cyl 2", MOMENTS[1],
          profondeur=1.0, reprise=False),
)

#: genres d'opération qu'un poste à outil peut prendre
TYPES_A_OUTIL = ("contour_2d5", "gravure_2d5", "evidement_2d5")


# ── les outils ──

def _normaliser(nom: str) -> str:
    """Un nom d'outil comparable: sans accent, sans casse, sans
    doublon d'espaces. « Con 30° 0.6 » et « con 30 0,6 » se valent."""
    brut = unicodedata.normalize('NFKD', str(nom or ""))
    brut = brut.encode('ascii', 'ignore').decode('ascii')
    brut = brut.replace(',', '.').lower()
    return re.sub(r'\s+', ' ', brut).strip()


def genre_outil(nom: str, fiche: Optional[Dict[str, Any]] = None
                ) -> Optional[str]:
    """« cylindrique », « conique », ou None si ni le nom ni la fiche
    (tools.json) ne disent rien."""
    if vcarve.diametre_depuis_nom(nom) is not None:
        return "cylindrique"
    if vcarve._NOM_CONE.search(str(nom or "")):
        return "conique"
    if fiche:
        try:
            if float(fiche.get('TipAngle') or 0) > 0:
                return "conique"
            if float(fiche.get('Diameter') or 0) > 0:
                return "cylindrique"
        except (TypeError, ValueError):
            pass
    return None


def _geometrie(nom: str):
    """Ce qui identifie un outil au-delà de son nom: ('cyl', Ø) ou
    ('con', angle, troncature)."""
    diametre = vcarve.diametre_depuis_nom(nom)
    if diametre is not None:
        return ('cyl', round(float(diametre), 3))
    if vcarve._NOM_CONE.search(str(nom or "")):
        angle, tronc = vcarve.cone_depuis_nom(nom)
        return ('con', round(float(angle), 2), round(float(tronc), 3))
    return None


def outils_du_genre(bibliotheque, genre: Optional[str]) -> List[str]:
    """Les identifiants des outils du genre demandé, dans l'ordre de
    la bibliothèque; tous si le genre est inconnu."""
    if bibliotheque is None:
        return []
    ids = list(getattr(bibliotheque, 'tools', {}).keys())
    if genre is None:
        return ids
    choisis = [i for i in ids
               if genre_outil(bibliotheque.tools[i].name,
                              getattr(bibliotheque.tools[i],
                                      'geometry', None)) == genre]
    return choisis or ids


def outil_du_poste(pst: Dict[str, Any], bibliotheque) -> str:
    """L'identifiant de l'outil du poste dans la bibliothèque.

    Par son nom d'abord; sinon par sa géométrie — une autre « Cyl 2 »
    ou une autre « Con 30° 0.2 » fait le même travail. Vide si la
    bibliothèque n'en a aucun."""
    voulu = pst.get('outil')
    if not voulu or bibliotheque is None:
        return ""
    outils = getattr(bibliotheque, 'tools', {})
    cible = _normaliser(voulu)
    for identifiant, outil in outils.items():
        if _normaliser(outil.name) == cible:
            return identifiant
    geometrie = _geometrie(voulu)
    if geometrie is None:
        return ""
    for identifiant, outil in outils.items():
        if _geometrie(outil.name) == geometrie:
            return identifiant
    return ""


def nom_outil(bibliotheque, identifiant: str) -> str:
    if bibliotheque is None or not identifiant:
        return ""
    outil = getattr(bibliotheque, 'tools', {}).get(identifiant)
    return outil.name if outil is not None else ""


# ── la création des opérations ──

def _nom_sequence(prefixe: str, nom_outil_: str) -> str:
    """« GRAVURE_CON_30_0_6 »: le nom de la séquence dit l'outil.
    Sur la machine, c'est lui qu'on lit."""
    brut = unicodedata.normalize('NFKD', nom_outil_)
    brut = brut.encode('ascii', 'ignore').decode('ascii')
    brut = re.sub(r'[^A-Za-z0-9]+', '_', brut).strip('_')
    return f"{prefixe}_{brut}".upper() if brut else prefixe


def operation_du_poste(pst: Dict[str, Any], source, tool_id: str,
                       bibliotheque) -> OperationInstance:
    """L'opération qu'un poste devient: le dessin et le champ de
    `source`, l'outil et les réglages du poste."""
    from src.operations.registry import OperationRegistry
    classe = OperationRegistry.get(pst['op_type'])
    nom = nom_outil(bibliotheque, tool_id)
    op = OperationInstance(pst['op_type'],
                           f"{pst['nom']} — {nom}" if nom
                           else pst['nom'])
    op.tool_id = tool_id or ""
    params = dict(classe.get_default_params())
    if pst['op_type'] in TYPES_A_OUTIL:
        for cle in CHAMPS_PARTAGES:
            if cle in source.params:
                params[cle] = _copie(source.params[cle])
        if 'preview' in source.params:
            params['preview'] = source.params['preview']
        # le cône se lit dans le nom de l'outil; l'écrire dans le
        # formulaire, c'est le montrer
        if genre_outil(nom) == "conique":
            angle, tronc = vcarve.cone_depuis_nom(nom)
            params['angle'] = float(angle)
            params['troncature'] = float(tronc)
        params['sequence_name'] = _nom_sequence(
            getattr(classe, 'PREFIXE_SEQ', 'SEQ'), nom)
    params.update(pst['reglages'])
    op.params = params
    op.x, op.y, op.z = source.x, source.y, source.z
    return op


def _copie(valeur):
    if isinstance(valeur, list):
        return [_copie(v) for v in valeur]
    if isinstance(valeur, dict):
        return {k: _copie(v) for k, v in valeur.items()}
    return valeur


def poste_modele(genre: str, outil: Optional[str] = None
                 ) -> Dict[str, Any]:
    """Un poste neuf du genre demandé, pour « + Poste »."""
    op_type, outil_defaut, reglages = POSTES_MODELES[genre]
    moment = MOMENTS[1] if op_type == "evidement_2d5" else MOMENTS[0]
    return poste(genre, op_type, outil or outil_defaut, moment,
                 **reglages)


def creer_gamme(modele, bibliotheque,
                postes: Sequence[Dict[str, Any]] = POSTES_BASE,
                nom: str = "Gamme gravure"):
    """La gamme entière: sa tête et ses postes, dans un ensemble.

    `modele` donne le dessin et le champ (une opération de parcours
    déjà relevée, ou un dict de paramètres); la tête les garde, les
    postes les reçoivent. Rend (tete, [postes]) — à insérer dans cet
    ordre, la tête d'abord."""
    import uuid
    from src.operations.registry import OperationRegistry
    from src.operations.gamme_gravure import GammeGravure
    classe = OperationRegistry.get("gamme_gravure")
    tete = OperationInstance("gamme_gravure", nom)
    tete.params = dict(classe.get_default_params())
    source = getattr(modele, 'params', modele) or {}
    for cle in CHAMPS_PARTAGES:
        if cle in source:
            tete.params[cle] = _copie(source[cle])
    if source and 'cadre_mode' not in source:
        # un modèle d'avant le round 103: des dimensions données
        # disent « par dimensions » (sans modèle: les défauts —
        # relief, cadre 50 × 20)
        from src.operations.gravure_2d5 import mode_du_cadre
        tete.params['cadre_mode'] = mode_du_cadre(source)
    if hasattr(modele, 'z'):
        tete.x, tete.y, tete.z = modele.x, modele.y, modele.z
    gid = str(uuid.uuid4())[:8]
    tete.group_id, tete.group_name = gid, nom
    membres = []
    for pst in postes:
        tool_id = outil_du_poste(pst, bibliotheque)
        if pst['op_type'] in TYPES_A_OUTIL and not tool_id:
            continue                    # pas d'outil: pas de poste
        op = operation_du_poste(pst, tete, tool_id, bibliotheque)
        op.group_id, op.group_name = gid, nom
        membres.append(op)
    GammeGravure.propager(tete, membres)
    return tete, membres
