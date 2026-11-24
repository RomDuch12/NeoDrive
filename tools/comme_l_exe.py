# -*- coding: utf-8 -*-
"""Lance un script Python comme dans l'exe: les paquets que neodrive.spec
écarte de la distribution (sa liste EXCLUS) sont introuvables.

    python tools/comme_l_exe.py main.py --autocontrole
    python tools/comme_l_exe.py --sans scipy.ndimage main.py --autocontrole

L'exe allégé n'embarque plus matplotlib, Pillow, lxml… Un `import` de
l'un d'eux ajouté dans src marcherait sur le poste de développement, où
ils sont installés, et planterait à l'atelier. Ici le même import échoue
tout de suite (ModuleNotFoundError), sans attendre un build.

`--sans a,b` écarte d'autres paquets en plus (essai avant d'allonger
EXCLUS, ou preuve que le blocage bloque).
"""
import ast
import os
import runpy
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(RACINE, "neodrive.spec")


def liste_du_spec(nom: str, spec: str = SPEC) -> list:
    """Une liste littérale de neodrive.spec, lue sans l'exécuter."""
    with open(spec, encoding="utf-8") as f:
        arbre = ast.parse(f.read())
    for noeud in ast.walk(arbre):
        if (isinstance(noeud, ast.Assign)
                and any(getattr(c, "id", "") == nom for c in noeud.targets)):
            return ast.literal_eval(noeud.value)
    raise KeyError(f"{nom} introuvable dans {spec}")


def est_ecarte(module: str, ecartes) -> bool:
    """`module` est-il l'un des paquets écartés, ou dans l'un d'eux ?"""
    return any(module == e or module.startswith(e + ".") for e in ecartes)


class Bloqueur:
    """Chercheur de modules placé en tête: refuse les paquets écartés."""

    def __init__(self, ecartes):
        self.ecartes = tuple(ecartes)
        self.refus = []

    def find_spec(self, nom, chemin=None, cible=None):
        if est_ecarte(nom, self.ecartes):
            self.refus.append(nom)
            raise ModuleNotFoundError(
                f"No module named {nom!r} (écarté de l'exe: "
                f"EXCLUS de neodrive.spec)", name=nom)
        return None


def installer(ecartes) -> Bloqueur:
    """Écarte ces paquets pour la suite du processus."""
    # ce que le démarrage de Python a déjà chargé (les « .pth » de
    # site-packages: _distutils_hack de setuptools) — l'exe ne les lit pas
    for deja in [m for m in sys.modules if est_ecarte(m, ecartes)]:
        del sys.modules[deja]
    bloqueur = Bloqueur(ecartes)
    sys.meta_path.insert(0, bloqueur)
    return bloqueur


def main(arguments) -> int:
    en_plus = []
    while arguments and arguments[0] == "--sans":
        en_plus += [x.strip() for x in arguments[1].split(",") if x.strip()]
        arguments = arguments[2:]
    if not arguments:
        print(__doc__)
        return 2
    installer(liste_du_spec("EXCLUS") + en_plus)
    script = os.path.abspath(arguments[0])
    # comme `python script.py`: le dossier du script en tête de sys.path,
    # à la place de celui de cet outil
    sys.path[0] = os.path.dirname(script)
    sys.argv = [script] + arguments[1:]
    runpy.run_path(script, run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
