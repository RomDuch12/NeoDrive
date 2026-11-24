# -*- coding: utf-8 -*-
"""Ce que l'exe embarque, après un build.

    python tools/inventaire_exe.py            # bilan, familles, passagers
    python tools/inventaire_exe.py --detail   # et les 60 plus gros fichiers

Lit ce que PyInstaller a mis dans l'exe (build/neodrive/PKG-00.toc et
PYZ-00.toc), pèse chaque famille, et cherche les « passagers
clandestins »: ce que neodrive.spec devait écarter (EXCLUS, RETIRES) et
qui serait monté à bord quand même. Code de sortie 1 s'il y en a.

Le contrôle est écrit à part des fonctions du spec, exprès: il relit
leur travail au lieu de le refaire avec le même code.
"""
from __future__ import annotations

import ast
import fnmatch
import os
import sys
from collections import defaultdict

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from comme_l_exe import est_ecarte, liste_du_spec  # noqa: E402

BUILD = os.path.join(RACINE, "build", "neodrive")
EXE = os.path.join(RACINE, "dist", "NeoDrive.exe")


def entrees_du_toc(chemin: str) -> list:
    """Les entrées (nom, chemin source, type) d'un .toc de PyInstaller."""
    with open(chemin, encoding="utf-8") as f:
        toc = ast.literal_eval(f.read())
    listes = [x for x in toc if isinstance(x, list)
              and x and isinstance(x[0], tuple)]
    if not listes:
        raise ValueError(f"aucune liste d'entrées dans {chemin}")
    return [tuple(e[:3]) for e in max(listes, key=len)]


def module_du_chemin(nom: str) -> str:
    """« scipy\\stats\\_stats.cp313-win_amd64.pyd » → « scipy.stats._stats »:
    le module (ou le paquet) auquel appartient un fichier de l'exe."""
    morceaux = nom.replace("\\", "/").split("/")
    morceaux[-1] = morceaux[-1].split(".")[0]
    return ".".join(m for m in morceaux if m)


def clandestins(fichiers, modules, exclus, retires) -> list:
    """Ce qui est à bord et ne devait pas l'être: noms de fichiers du PKG
    et de modules du PYZ, triés."""
    trouves = []
    for nom in fichiers:
        chemin = nom.replace("\\", "/").lower()
        if any(fnmatch.fnmatchcase(chemin, m.lower()) for m in retires) \
                or est_ecarte(module_du_chemin(nom), exclus):
            trouves.append(nom)
    trouves += [m for m in modules if est_ecarte(m, exclus)]
    return sorted(trouves)


def famille(nom: str) -> str:
    """Le paquet d'un fichier de l'exe; Qt est détaillé."""
    morceaux = nom.replace("\\", "/").split("/")
    if len(morceaux) == 1:
        return "(racine: python, DLL, .pyd)"
    if morceaux[0] == "PySide6" and len(morceaux) > 2:
        return "PySide6/" + morceaux[1]
    return morceaux[0]


def poids(chemin: str) -> int:
    try:
        return os.path.getsize(chemin)
    except OSError:
        return 0


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    pkg = os.path.join(BUILD, "PKG-00.toc")
    pyz = os.path.join(BUILD, "PYZ-00.toc")
    if not (os.path.isfile(pkg) and os.path.isfile(pyz)):
        print(f"pas de build dans {BUILD}: lancer d'abord\n"
              f"    python -m PyInstaller --noconfirm --clean neodrive.spec")
        return 2
    fichiers = [e for e in entrees_du_toc(pkg)
                if e[2] not in ("PYZ", "PYMODULE", "PYSOURCE", "OPTION")]
    modules = entrees_du_toc(pyz)
    total = sum(poids(c) for _n, c, _t in fichiers)
    sources = sum(poids(c) for _n, c, _t in modules)
    Mo = 2 ** 20
    if os.path.isfile(EXE):
        print(f"exe: {os.path.getsize(EXE) / Mo:.1f} Mo")
    print(f"à bord: {len(fichiers)} fichiers, {total / Mo:.1f} Mo "
          f"décompressés à chaque lancement; {len(modules)} modules "
          f"Python ({sources / Mo:.1f} Mo de sources)")
    par = defaultdict(int)
    for nom, chemin, _type in fichiers:
        par[famille(nom)] += poids(chemin)
    for nom, octets in sorted(par.items(), key=lambda x: -x[1])[:16]:
        print(f"  {octets / Mo:7.2f} Mo  {nom}")
    if "--detail" in argv:
        print("les 60 plus gros fichiers:")
        gros = sorted(((poids(c), n) for n, c, _t in fichiers),
                      reverse=True)[:60]
        for octets, nom in gros:
            print(f"  {octets / Mo:7.2f} Mo  {nom}")
    a_bord = clandestins([n for n, _c, _t in fichiers],
                         [n for n, _c, _t in modules],
                         liste_du_spec("EXCLUS"), liste_du_spec("RETIRES"))
    if a_bord:
        print(f"PASSAGERS CLANDESTINS ({len(a_bord)}): écartés par "
              f"neodrive.spec et pourtant à bord")
        for nom in a_bord[:40]:
            print("   ", nom)
        return 1
    print("aucun passager clandestin: rien de EXCLUS ni de RETIRES à bord")
    return 0


if __name__ == "__main__":
    sys.exit(main())
