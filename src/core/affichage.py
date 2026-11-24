"""L'affichage d'une opération aux canvas: sa transparence, et « une
ligne sur N ».

Une gravure de cent passes, un programme externe de cent mille
mouvements: leurs trajectoires couvrent le dessin et la pièce 3D.
Chaque opération peut alors être montrée en transparence (de 5 à
100 %) et ne garder qu'une ligne sur 2, 3, 5 ou 10 — l'allure reste,
la charge baisse. Ces réglages vivent dans les paramètres de
l'opération (clés « _aff_ »: le générateur ne les lit pas), réglés au
clic droit de la liste ou au panneau du Canva 3D.
"""
from __future__ import annotations

from typing import List, Sequence

CLE_OPACITE = '_aff_opacite'
CLE_DIVISION = '_aff_division'

#: le repère qui ouvre une opération dans le code que simule le Canva 3D
#: (voir `SimPlGenerator.code_marque`): « #@op <id> », à la colonne 0. Jamais
#: dans le programme de la machine.
MARQUE_OP = '#@op '
#: l'id du repère qui referme la dernière opération (la fin du Main)
FIN_OPS = '-'

#: les opérations venues d'un programme importé
TYPES_IMPORTES = ('bloc_simpl', 'lignes_main', 'appel_programme',
                  'import_programme')

#: une ligne sur N
DIVISIONS = (1, 2, 3, 5, 10)

#: transparences proposées au menu (opacité en %)
OPACITES = (100, 75, 50, 25, 10)


def opacite(op) -> float:
    """L'opacité de l'opération, de 0,05 à 1."""
    params = getattr(op, 'params', None) or {}
    try:
        v = float(params.get(CLE_OPACITE, 1.0))
    except (TypeError, ValueError):
        v = 1.0
    return max(0.05, min(1.0, v))


def division(op) -> int:
    """Une ligne sur combien (1: toutes)."""
    params = getattr(op, 'params', None) or {}
    try:
        n = int(params.get(CLE_DIVISION, 1))
    except (TypeError, ValueError):
        n = 1
    return n if n in DIVISIONS else 1


def regler(op, opacite_=None, division_=None) -> None:
    """Pose les réglages (None: inchangé). Les valeurs par défaut ne
    s'écrivent pas: le fichier du programme reste le même."""
    params = op.params
    if opacite_ is not None:
        v = max(0.05, min(1.0, float(opacite_)))
        if v >= 1.0:
            params.pop(CLE_OPACITE, None)
        else:
            params[CLE_OPACITE] = round(v, 3)
    if division_ is not None:
        n = int(division_)
        if n <= 1 or n not in DIVISIONS:
            params.pop(CLE_DIVISION, None)
        else:
            params[CLE_DIVISION] = n


def decimer(elements: Sequence, n: int) -> list:
    """Un élément sur n, le dernier gardé (le tracé finit où il finit)."""
    elements = list(elements)
    if n <= 1 or len(elements) <= 2:
        return elements
    garde = elements[::n]
    if garde[-1] is not elements[-1]:
        garde.append(elements[-1])
    return garde


def decimer_polylignes(polylignes: Sequence, n: int) -> List:
    """Beaucoup de polylignes (des passes): une sur n. Peu: leurs
    sommets, un sur n."""
    polylignes = list(polylignes)
    if n <= 1:
        return polylignes
    if len(polylignes) >= 2 * n:
        return polylignes[::n]
    return [decimer(pl, n) for pl in polylignes]


#: les opérations dont le tracé au Canva 3D est le parcours de leur code
TRACE_SIMULE = TYPES_IMPORTES + ('sequence_datron',)


def reglages_des_ops(ops) -> dict:
    """{id de l'opération: (opacité, une ligne sur N)} de celles qui ne
    sont pas aux réglages par défaut."""
    reglages = {}
    for op in ops or []:
        a, n = opacite(op), division(op)
        if a < 1.0 or n > 1:
            reglages[op.id] = (a, n)
    return reglages


def retirer_marques(code: str) -> str:
    """Le code sans ses repères d'opérations (lignes entières)."""
    marque = '\n' + MARQUE_OP
    i = code.find(marque)
    if i < 0:
        return code
    morceaux = []
    debut = 0
    while i >= 0:
        morceaux.append(code[debut:i + 1])
        fin = code.find('\n', i + 1)
        debut = fin + 1 if fin >= 0 else len(code)
        i = code.find(marque, debut - 1)
    morceaux.append(code[debut:])
    return ''.join(morceaux)


def resume(op) -> str:
    """« 50 % · 1/5 » — vide aux réglages par défaut."""
    parts = []
    a = opacite(op)
    if a < 1.0:
        parts.append(f"{int(round(a * 100))} %")
    n = division(op)
    if n > 1:
        parts.append(f"1/{n}")
    return " · ".join(parts)
