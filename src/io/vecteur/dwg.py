"""Lecture des DWG (AutoCAD), par un convertisseur DWG → DXF.

Le DWG est un format fermé, sans lecteur libre complet en Python. Un
convertisseur gratuit le transforme en DXF, que NeoDrive lit déjà
(calques, couleurs, entités):

- ODA File Converter (Open Design Alliance, gratuit) — cherché dans
  « C:/Program Files/ODA » (et x86);
- LibreDWG (dwg2dxf, libre) — cherché dans le PATH;
- ou un convertisseur désigné par la variable d'environnement
  NEODRIVE_DWG_CONVERTISSEUR (un exécutable appelé avec « entrée
  sortie »).

Le DXF converti est gardé (dossier temporaire de NeoDrive) tant que le
DWG ne change pas. DWG TrueView (Autodesk) ne sait pas écrire de DXF:
il ne sert pas ici.
"""
from __future__ import annotations

import glob
import hashlib
import os
import shutil
import subprocess
import tempfile
from typing import Optional, Tuple

from .dxfimport import DxfError

SUFFIXES = ('.dwg',)

#: où le chercher
_ODA = ("C:/Program Files/ODA/ODAFileConverter*/ODAFileConverter.exe",
        "C:/Program Files (x86)/ODA/ODAFileConverter*/ODAFileConverter.exe",
        "C:/Program Files/ODA/*/ODAFileConverter.exe")

AIDE = ("Le DWG est un format fermé: NeoDrive le lit par un convertisseur "
        "gratuit. Installez « ODA File Converter » (opendesign.com, "
        "gratuit) ou LibreDWG (dwg2dxf), ou enregistrez le dessin en DXF "
        "depuis AutoCAD.")


class DwgError(DxfError):
    """DWG non converti."""


def convertisseur() -> Optional[Tuple[str, str]]:
    """(genre, chemin) du convertisseur trouvé: 'env', 'oda',
    'libredwg' — ou None."""
    env = os.environ.get('NEODRIVE_DWG_CONVERTISSEUR', '').strip()
    if env and os.path.isfile(env):
        return 'env', env
    for motif in _ODA:
        trouves = sorted(glob.glob(motif))
        if trouves:
            return 'oda', trouves[-1]
    lib = shutil.which('dwg2dxf')
    if lib:
        return 'libredwg', lib
    return None


def etat() -> str:
    c = convertisseur()
    if c is None:
        return ("DWG indisponible (aucun convertisseur: ODA File "
                "Converter ou LibreDWG)")
    noms = {'env': "convertisseur désigné", 'oda': "ODA File Converter",
            'libredwg': "LibreDWG"}
    return f"DWG via {noms.get(c[0], c[0])}"


def _cache(chemin: str) -> str:
    st = os.stat(chemin)
    cle = hashlib.sha1(f"{os.path.abspath(chemin)}|{st.st_mtime}|"
                       f"{st.st_size}".encode('utf-8')).hexdigest()[:12]
    dossier = os.path.join(tempfile.gettempdir(), "neodrive_dwg")
    os.makedirs(dossier, exist_ok=True)
    base = os.path.splitext(os.path.basename(chemin))[0]
    return os.path.join(dossier, f"{base}_{cle}.dxf")


def vers_dxf(chemin: str, delai: float = 180.0) -> str:
    """Le DXF d'un DWG (converti, ou déjà en cache)."""
    if not os.path.isfile(chemin):
        raise DwgError(f"DWG introuvable: {chemin}")
    sortie = _cache(chemin)
    if os.path.isfile(sortie) and os.path.getsize(sortie) > 0:
        return sortie
    c = convertisseur()
    if c is None:
        raise DwgError(AIDE)
    genre, exe = c
    options = {}
    if os.name == 'nt':
        options['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    if genre == 'oda':
        # ODAFileConverter <dossier entrée> <dossier sortie> <version>
        # <type> <récursif> <audit> [filtre]
        travail = tempfile.mkdtemp(prefix="neodrive_oda_")
        entree = os.path.join(travail, "in")
        sortie_dir = os.path.join(travail, "out")
        os.makedirs(entree)
        os.makedirs(sortie_dir)
        copie = os.path.join(entree, os.path.basename(chemin))
        shutil.copy2(chemin, copie)
        cmd = [exe, entree, sortie_dir, "ACAD2018", "DXF", "0", "1",
               os.path.basename(chemin)]
        produit = os.path.join(sortie_dir, os.path.splitext(
            os.path.basename(chemin))[0] + ".dxf")
    elif genre == 'libredwg':
        cmd = [exe, "-y", "-o", sortie, chemin]
        produit = sortie
    else:
        cmd = [exe, chemin, sortie]
        produit = sortie
    try:
        subprocess.run(cmd, check=False, timeout=delai, capture_output=True,
                       **options)
    except (OSError, subprocess.TimeoutExpired) as err:
        raise DwgError(f"conversion DWG échouée: {err}") from None
    if not os.path.isfile(produit) or os.path.getsize(produit) == 0:
        raise DwgError("le convertisseur n'a pas produit de DXF "
                       f"({os.path.basename(exe)})")
    if produit != sortie:
        shutil.move(produit, sortie)
    return sortie


def lire(chemin, tolerance_mm: float = 0.02, units_mm: float = None,
         progress=None, ask=None):
    """`(calques, rapport)` d'un DWG: converti en DXF, puis lu."""
    from . import dxfimport
    dxf = vers_dxf(chemin)
    calques, rapport = dxfimport.read(dxf, tolerance_mm=tolerance_mm,
                                      units_mm=units_mm, progress=progress,
                                      ask=ask)
    rapport.notes.append(f"DWG converti en DXF ({etat()})")
    return calques, rapport
