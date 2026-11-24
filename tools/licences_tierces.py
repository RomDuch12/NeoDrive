# -*- coding: utf-8 -*-
"""Les licences de ce que l'exe embarque, posées à côté de lui.

    python tools/licences_tierces.py [--dist DOSSIER] [--build DOSSIER]

NeoDrive est sous licence MIT ou Apache-2.0 (LICENSE.txt). L'exe, lui,
emporte Python, Qt (PySide6), numpy, scipy, shapely… chacun sous sa
licence, et ces licences demandent de voyager avec lui. Ce module
relit l'inventaire du build (build/neodrive/PKG-00.toc et PYZ-00.toc,
comme tools/inventaire_exe.py), attribue CHAQUE fichier embarqué à la
distribution installée qui l'a fourni (son RECORD), et copie leurs
textes de licence dans <dist>/licences/<composant>/, avec un
LISEZ-MOI.txt: composant, version, licence, nombre de fichiers.

Ce que les paquets n'emportent pas est dans le dossier licences/ du
dépôt (COMPLEMENTS): les textes LGPL-3.0 et GPL-3.0 sous lesquels Qt
est utilisé (la roue de PySide6 n'a que sa licence commerciale).

Un fichier embarqué que rien ne revendique, ou un composant sans texte
de licence: le LISEZ-MOI le dit (« À COMPLÉTER ») et le code de sortie
est 1; l'autocontrôle de l'exe refuse alors la publication.

neodrive.spec appelle `poser()` à la fin de chaque build.
"""
from __future__ import annotations

import argparse
import csv
import fnmatch
import importlib.metadata as metadata
import os
import re
import shutil
import sys
from dataclasses import dataclass, field

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from inventaire_exe import entrees_du_toc  # noqa: E402

BUILD = os.path.join(RACINE, "build", "neodrive")
DIST = os.path.join(RACINE, "dist")
DOSSIER = "licences"
LISEZ_MOI = "LISEZ-MOI.txt"
A_COMPLETER = "À COMPLÉTER"
# les textes de licence d'une distribution, où qu'ils soient dans ses
# fichiers (numpy/random/LICENSE.md, scipy/…/COPYING_QHULL.txt…)
MOTIF_TEXTE = re.compile(r"^(licen[cs]e|copying|notice|copyright)",
                         re.IGNORECASE)
# textes livrés qui ne s'appliquent pas: la licence commerciale de Qt
# (NeoDrive utilise Qt sous LGPL-3.0)
ECARTES = ("LicenseRef-Qt-Commercial*",)
# composants regroupés sous un seul nom et un seul dossier (motif sur le
# nom normalisé de la distribution)
FAMILLES = (("pyside6", "PySide6 (Qt for Python)"),
            ("pyside6-*", "PySide6 (Qt for Python)"),
            ("shiboken6", "PySide6 (Qt for Python)"),
            ("pyinstaller", "PyInstaller"))
# textes à joindre, pris dans licences/ du dépôt
COMPLEMENTS = {
    "PySide6 (Qt for Python)": ("LGPL-3.0.txt", "GPL-3.0.txt"),
}
# ce qu'on en dit dans le LISEZ-MOI, quand la licence déclarée est
# ambiguë ou incomplète
PRECISIONS = {
    "PySide6 (Qt for Python)":
        "LGPL-3.0 (choisie parmi LGPL-3.0 / GPL-2.0 / GPL-3.0)",
    "Python":
        "PSF-2.0, et ses composants (OpenSSL: Apache-2.0, libffi, "
        "bzip2, Tcl/Tk…): voir le texte",
    "PyInstaller":
        "GPL-2.0-or-later avec exception (le chargeur de l'exe ne "
        "contamine pas le programme)",
    "Microsoft C/C++ Runtime":
        "redistribuables Microsoft (conditions dans Python/LICENSE.txt)",
}
PYTHON = "Python"
PYINSTALLER = "PyInstaller"
RUNTIME_MS = "Microsoft C/C++ Runtime"
NEODRIVE = "NeoDrive"


def _chemin(p: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(p)))


def _dans(chemin: str, dossier: str) -> bool:
    return chemin == dossier or chemin.startswith(dossier + os.sep)


def nom_normalise(nom: str) -> str:
    """« PySide6_Essentials » → « pyside6-essentials » (PEP 503)."""
    return re.sub(r"[-_.]+", "-", nom).lower()


def famille(nom: str) -> str:
    """Le composant (dossier, ligne du LISEZ-MOI) d'une distribution."""
    norme = nom_normalise(nom)
    for motif, nom_famille in FAMILLES:
        if fnmatch.fnmatchcase(norme, motif):
            return nom_famille
    return nom


def fichiers(dist) -> list:
    """Les fichiers d'une distribution (chemins relatifs, « / »), lus
    dans son RECORD: `dist.files` vérifie l'existence de chacun (Python
    3.12+) — 40 000 fichiers, 13 s au lieu de 0,2."""
    record = dist.read_text("RECORD")
    if record is None:
        return [str(f).replace("\\", "/") for f in dist.files or ()]
    return [ligne[0].replace("\\", "/")
            for ligne in csv.reader(record.splitlines()) if ligne]


def proprietaires(distributions=None) -> dict:
    """Chaque fichier installé (chemin normalisé) → sa distribution, lu
    dans les RECORD de site-packages."""
    table = {}
    for dist in (metadata.distributions() if distributions is None
                 else distributions):
        base = str(dist.locate_file(""))
        for rel in fichiers(dist):
            table.setdefault(
                _chemin(os.path.join(base, *rel.split("/"))), dist)
    return table


@dataclass
class Composant:
    nom: str
    versions: set = field(default_factory=set)
    distributions: list = field(default_factory=list)
    fichiers: int = 0


@dataclass
class Attribution:
    composants: dict            # nom → Composant
    orphelins: list             # (nom embarqué, source) que rien ne revendique


def attribuer(entrees, table: dict, racine: str = RACINE,
              build: str = BUILD, prefixe: str = sys.base_prefix,
              systeme: str = os.environ.get("SystemRoot", r"C:\Windows")
              ) -> Attribution:
    """À qui appartient chaque fichier embarqué (entrées des .toc)."""
    racine, build = _chemin(racine), _chemin(build)
    prefixe, systeme = _chemin(prefixe), _chemin(systeme)
    composants, orphelins = {}, []

    def compter(nom, dist=None, version=""):
        c = composants.setdefault(nom, Composant(nom))
        c.fichiers += 1
        if dist is not None and all(d is not dist for d in c.distributions):
            c.distributions.append(dist)
            c.versions.add(dist.version)
        elif version:
            c.versions.add(version)

    for nom, source, genre in entrees:
        if genre in ("OPTION", "PYZ") or not source:
            continue
        chemin = _chemin(source)
        dist = table.get(chemin)
        base = os.path.basename(chemin).lower()
        if dist is not None:
            compter(famille(dist.metadata["Name"]), dist)
        elif _dans(chemin, build):
            # le chargeur de PyInstaller (pyimod*), base_library.zip et
            # les modules de la bibliothèque standard compilés pour lui
            if base.startswith(("pyimod", "pyi_", "_pyi")):
                compter(PYINSTALLER)
            else:
                compter(PYTHON, version=_version_python())
        elif _dans(chemin, racine):
            compter(NEODRIVE)
        elif base.startswith(("api-ms-win-", "ucrtbase", "vcruntime",
                              "msvcp", "concrt")):
            compter(RUNTIME_MS)
        elif _dans(chemin, prefixe):
            compter(PYTHON, version=_version_python())
        elif _dans(chemin, systeme):
            compter(RUNTIME_MS)
        else:
            orphelins.append((nom, source))
    return Attribution(composants, orphelins)


def _version_python() -> str:
    return "%d.%d.%d" % sys.version_info[:3]


def textes(dist) -> list:
    """Les textes de licence d'une distribution: (chemin relatif à
    écrire, chemin source), les .dist-info/ ramenés à leur contenu."""
    trouves = []
    for rel in fichiers(dist):
        nom = rel.rsplit("/", 1)[-1]
        if any(fnmatch.fnmatchcase(nom, m) for m in ECARTES):
            continue
        morceaux = rel.split("/")
        sous_licenses = (len(morceaux) > 2
                         and morceaux[0].endswith(".dist-info")
                         and morceaux[1] == "licenses")
        if not (MOTIF_TEXTE.match(nom) or sous_licenses):
            continue
        source = str(dist.locate_file(rel))
        if not os.path.isfile(source):
            continue
        if morceaux[0].endswith(".dist-info"):
            rel = "/".join(morceaux[2:] if sous_licenses else morceaux[1:])
        trouves.append((rel, source))
    return sorted(trouves)


def licence_declaree(dist) -> str:
    """Ce que la distribution déclare: License-Expression, sinon le
    champ License s'il est court, sinon ses classificateurs."""
    meta = dist.metadata
    expression = (meta.get("License-Expression") or "").strip()
    if expression:
        return expression
    champ = (meta.get("License") or "").strip()
    if champ and "\n" not in champ and len(champ) <= 100:
        return champ
    classes = [c.rsplit("::", 1)[-1].strip()
               for c in (meta.get_all("Classifier") or ())
               if c.startswith("License ::")]
    return " / ".join(classes)


@dataclass
class Bilan:
    composants: list            # (nom, versions, licence, fichiers, textes)
    orphelins: list
    sans_texte: list

    @property
    def complet(self) -> bool:
        return not self.orphelins and not self.sans_texte


def _version_neodrive(racine: str) -> str:
    try:
        with open(os.path.join(racine, "src", "__init__.py"),
                  encoding="utf-8") as f:
            return re.search(r"""__version__ = ['"]([^'"]+)['"]""",
                             f.read()).group(1)
    except (OSError, AttributeError):
        return "?"


def _nom_de_dossier(nom: str, versions) -> str:
    propre = re.sub(r"[^\w.+-]+", "_", nom.split(" (")[0]).strip("_")
    return f"{propre}-{sorted(versions)[-1]}" if versions else propre


def poser(dist_dir: str = DIST, build: str = BUILD, racine: str = RACINE,
          table: dict = None) -> Bilan:
    """Écrit <dist_dir>/licences/: un dossier par composant embarqué et
    le LISEZ-MOI.txt. Rend le bilan (complet ou non)."""
    entrees = (entrees_du_toc(os.path.join(build, "PKG-00.toc"))
               + entrees_du_toc(os.path.join(build, "PYZ-00.toc")))
    attribution = attribuer(entrees, proprietaires() if table is None
                            else table, racine=racine, build=build)
    sortie = os.path.join(dist_dir, DOSSIER)
    # le dossier est le nôtre (régénéré à chaque build): on le refait
    if os.path.isfile(os.path.join(sortie, LISEZ_MOI)):
        shutil.rmtree(sortie)
    os.makedirs(sortie, exist_ok=True)
    complements = os.path.join(racine, DOSSIER)
    lignes, sans_texte = [], []
    composants = dict(attribution.composants)
    composants.pop(NEODRIVE, None)
    # le chargeur de l'exe (run.exe) vient de PyInstaller, toujours
    try:
        pyi = metadata.distribution("pyinstaller")
        c = composants.setdefault(famille(pyi.metadata["Name"]),
                                  Composant(PYINSTALLER))
        if all(d is not pyi for d in c.distributions):
            c.distributions.append(pyi)
        c.versions.add(pyi.version)
    except metadata.PackageNotFoundError:
        pass
    for nom in sorted(composants, key=str.lower):
        c = composants[nom]
        a_copier = {}
        for dist in c.distributions:
            for rel, source in textes(dist):
                a_copier.setdefault(rel, source)
        if nom == PYTHON:
            texte_python = os.path.join(sys.base_prefix, "LICENSE.txt")
            if os.path.isfile(texte_python):
                a_copier["LICENSE.txt"] = texte_python
        for rel in COMPLEMENTS.get(nom, ()):
            a_copier[rel] = os.path.join(complements, rel)
        licence = PRECISIONS.get(nom) or " / ".join(sorted(
            {licence_declaree(d) for d in c.distributions} - {""})) or "?"
        dossier = _nom_de_dossier(nom, c.versions)
        ecrits = []
        for rel, source in sorted(a_copier.items()):
            if not os.path.isfile(source):
                continue
            cible = os.path.join(sortie, dossier, *rel.split("/"))
            os.makedirs(os.path.dirname(cible), exist_ok=True)
            shutil.copyfile(source, cible)
            ecrits.append(f"{dossier}/{rel}")
        if not ecrits and nom != RUNTIME_MS:
            sans_texte.append(nom)
        lignes.append((nom, ", ".join(sorted(c.versions)), licence,
                       c.fichiers, ecrits))
    bilan = Bilan(lignes, attribution.orphelins, sans_texte)
    with open(os.path.join(sortie, LISEZ_MOI), "w", encoding="utf-8",
              newline="\r\n") as f:
        f.write(lisez_moi(bilan, _version_neodrive(racine)))
    return bilan


def lisez_moi(bilan: Bilan, version: str) -> str:
    titre = f"Licences du code embarqué dans NeoDrive.exe {version}"
    morceaux = [
        titre, "=" * len(titre), "",
        "NeoDrive lui-même est sous licence MIT ou Apache-2.0, au choix",
        "(LICENSE.txt à côté de l'exe). L'exe emporte aussi les composants",
        "ci-dessous, chacun sous sa propre licence; leurs textes sont dans",
        "les dossiers voisins. Qt et PySide6 sont utilisés sous la LGPL-3.0:",
        "THIRD_PARTY_NOTICES.md dit comment reconstruire l'exe avec une",
        "autre version (les sources de NeoDrive sont dans sources/).", "",
    ]
    if not bilan.complet:
        morceaux += [f"{A_COMPLETER}:"]
        morceaux += [f"  - {nom}: aucun texte de licence trouvé"
                     for nom in bilan.sans_texte]
        morceaux += [f"  - {nom} ({source}): à qui est ce fichier ?"
                     for nom, source in bilan.orphelins]
        morceaux += [""]
    largeurs = (max([len(l[0]) for l in bilan.composants] + [9]),
                max([len(l[1]) for l in bilan.composants] + [7]))
    entete = (f"{'Composant':<{largeurs[0]}}  {'Version':<{largeurs[1]}}"
              f"  Fichiers  Licence")
    morceaux += [entete, "-" * len(entete)]
    for nom, versions, licence, fichiers, _ in bilan.composants:
        morceaux.append(f"{nom:<{largeurs[0]}}  {versions:<{largeurs[1]}}"
                        f"  {fichiers:>8}  {licence}")
    morceaux += ["", "Textes", "------"]
    for nom, _, _, _, ecrits in bilan.composants:
        morceaux.append(f"{nom}: " + (", ".join(ecrits) if ecrits
                                      else "(pas de texte à joindre)"))
    return "\n".join(morceaux) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dist", default=DIST)
    parser.add_argument("--build", default=BUILD)
    args = parser.parse_args(argv)
    bilan = poser(args.dist, args.build)
    print(f"licences: {len(bilan.composants)} composant(s) dans "
          f"{os.path.join(args.dist, DOSSIER)}")
    for nom in bilan.sans_texte:
        print(f"  {A_COMPLETER}: {nom} sans texte de licence")
    for nom, source in bilan.orphelins:
        print(f"  {A_COMPLETER}: {nom} ({source}) à personne")
    return 0 if bilan.complet else 1


if __name__ == "__main__":
    sys.exit(main())
