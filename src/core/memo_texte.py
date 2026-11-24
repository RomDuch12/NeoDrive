"""Les résultats d'une fonction PURE de textes (un bloc SimPL, une
séquence), gardés: un clic sur une opération relisait tout le code d'un
bloc importé pour en refaire la fiche (novembre 2026, 25 ms par clic).

La mémoire est bornée en caractères gardés (un bloc 3D fait plusieurs
mégaoctets): au-delà, les plus anciens s'en vont.
"""

import copy
from collections import OrderedDict


class MemoTexte:
    """`MemoTexte(fonction)(*arguments)`: le résultat de
    `fonction(*arguments)`, calculé une fois par jeu d'arguments (des
    textes, des nombres — hachables). Le résultat rendu est une COPIE:
    l'appelant peut le modifier sans toucher à celui qui est gardé."""

    def __init__(self, fonction, max_caracteres: int = 16_000_000,
                 copier=copy.deepcopy):
        self._fonction = fonction
        self._max = int(max_caracteres)
        self._copier = copier
        self._gardes = OrderedDict()
        self._taille = 0

    @staticmethod
    def _taille_de(cle) -> int:
        return sum(len(a) for a in cle if isinstance(a, str))

    def __call__(self, *arguments):
        cle = arguments
        try:
            resultat = self._gardes[cle]
        except KeyError:
            resultat = self._fonction(*arguments)
            self._gardes[cle] = resultat
            self._taille += self._taille_de(cle)
            while len(self._gardes) > 1 and self._taille > self._max:
                vieille, _r = self._gardes.popitem(last=False)
                self._taille -= self._taille_de(vieille)
        else:
            self._gardes.move_to_end(cle)
        return self._copier(resultat) if self._copier else resultat

    def vider(self) -> None:
        self._gardes.clear()
        self._taille = 0

    def __len__(self) -> int:
        return len(self._gardes)
