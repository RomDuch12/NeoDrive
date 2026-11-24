"""Le sens des filets sous un miroir.

Un miroir sur UN axe (MirrorWcs mirrorX OU mirrorY) retourne l'hélice:
un taraudage programmé « RightHandThread » sort à gauche. Sur DEUX axes
(X et Y), c'est une rotation d'un demi-tour: le sens est gardé. Le
miroir vaut de l'opération « Miroir » jusqu'à « Rétablir Miroir » (ou la
fin du programme).

Ce module dit, dans l'ordre du programme, quels taraudages sont à
programmer dans l'autre sens pour que le filet reste celui voulu — et
lesquels, retournés par NeoDrive sous un miroir qui n'existe plus (ou
qui ne les couvre plus), sont à REMETTRE dans leur sens. La marque
`inverse_par_miroir` (dans les params) retient ce que NeoDrive a
retourné: un filet à gauche voulu par l'utilisateur n'est pas touché.
"""

from typing import Dict, List

#: les opérations dont le sens se programme
TYPES_FILETS = ("taraudage", "taraudage_brut")
DROITE, GAUCHE = "RightHandThread", "LeftHandThread"
MARQUE = "inverse_par_miroir"


def _sens(op) -> str:
    return op.params.get('direction', DROITE) or DROITE


def axes_avant_chaque_op(operations) -> List[Dict[str, bool]]:
    """Les axes en miroir AU MOMENT de chaque opération."""
    etat = {'x': False, 'y': False}
    sortie = []
    for op in operations:
        sortie.append(dict(etat))
        if not getattr(op, 'enabled', True):
            continue
        if op.operation_type == "miroir":
            # MirrorWcs n'écrit que les axes cochés: les autres restent
            if op.params.get('mirror_x'):
                etat['x'] = True
            if op.params.get('mirror_y'):
                etat['y'] = True
        elif op.operation_type == "retablir_miroir":
            etat = {'x': False, 'y': False}
    return sortie


def bilan(operations) -> Dict[str, list]:
    """{'a_inverser': taraudages sous un miroir qui retourne l'hélice et
    programmés à droite, 'a_remettre': taraudages retournés par NeoDrive
    qu'aucun miroir ne retourne plus}."""
    a_inverser, a_remettre = [], []
    for op, axes in zip(operations, axes_avant_chaque_op(operations)):
        if not getattr(op, 'enabled', True) or \
                op.operation_type not in TYPES_FILETS:
            continue
        retourne = axes['x'] != axes['y']
        if retourne and _sens(op) == DROITE:
            a_inverser.append(op)
        elif not retourne and _sens(op) == GAUCHE and op.params.get(MARQUE):
            a_remettre.append(op)
    return {'a_inverser': a_inverser, 'a_remettre': a_remettre}


def appliquer(b: Dict[str, list]) -> int:
    """Retourne ce que le bilan propose; rend le nombre d'opérations
    changées."""
    for op in b.get('a_inverser', []):
        op.params['direction'] = GAUCHE
        op.params[MARQUE] = True
    for op in b.get('a_remettre', []):
        op.params['direction'] = DROITE
        op.params.pop(MARQUE, None)
    return len(b.get('a_inverser', [])) + len(b.get('a_remettre', []))


def signature(b: Dict[str, list]) -> tuple:
    """Ce qui est proposé, pour ne pas reposer une question refusée."""
    return (tuple(sorted(getattr(o, 'id', str(id(o)))
                         for o in b.get('a_inverser', []))),
            tuple(sorted(getattr(o, 'id', str(id(o)))
                         for o in b.get('a_remettre', []))))
