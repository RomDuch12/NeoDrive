"""Lecture des dessins vectoriels — noyau repris de TauDrive.

`dxfimport`, `vecimport`, `svgread`, `geometry`, `textvec` et
`fontmap` viennent de TauDrive (RomDuch / Cielle), à deux retraits
près: leur fonction `to_shapes()` et le modèle de document
`model.Path`/`Recipe`, qui n'ont pas cours ici.

Ils rendent des `geometry.Chemin`: des tracés qui GARDENT LEURS
COURBES et se lisent en même temps comme des polylignes. L'usinage
travaille sur les points; l'affichage et la ressortie sur les
courbes. Aplaties, elles ne redeviennent jamais des courbes — un PDF
importé montrait ses facettes au zoom, là où le DXF reste net.

Ce qu'ils lisent:

| Format          | Lecture                                      |
|-----------------|----------------------------------------------|
| `.dxf`          | ezdxf, entités aplaties par `ezdxf.path`     |
| `.pdf`          | flux de contenu                              |
| `.ai` (2000→)   | c'est un PDF                                 |
| `.ai` (≤ v8)    | c'est un EPS PostScript                      |
| `.eps`, `.ps`   | opérateurs Illustrator                       |
| `.svg`          | primitives et chemins                        |
| `.cdr`          | par convertisseur externe s'il est installé  |
| `.stp`, `.step` | pièce 3D: faces du dessus, contours par      |
|                 | profondeur, trous (voir `stepread`)          |
| `.stl`, `.3dxml`| pièce en maillage (STL, CATIA 3DXML): faces  |
|                 | reconstruites, comme un STEP (`maillage`)    |
| `.igs`, `.iges` | courbes IGES vues de dessus (`iges`)         |
| `.dwg`          | par un convertisseur DWG → DXF (`dwg`)       |
| `.emf`, `.wmf`  | métafichiers Windows (Office, CorelDRAW,     |
| `.emz`, `.wmz`  | presse-papiers) — voir `metafile`            |
| `.png`, `.jpg`, | image VECTORISÉE: contours ou lignes         |
| `.bmp`, `.gif`, | médianes (voir `trace_image`)                |
| `.tif`          |                                              |

Le point d'entrée d'ici est `lire(chemin, progress=…)`: un seul appel
pour tous les formats, qui rend `(calques, rapport)` — un dictionnaire
`{nom de calque: [Chemin, …]}`, chaque Chemin donnant ses points en
millimètres, Y vers le haut comme dans le fichier.

`progress(fraction, texte)` est appelé au fil de la lecture; s'il rend
`False`, la lecture s'arrête sur `Cancelled`. Un dessin de dix
mégaoctets demande plusieurs secondes: sans cela, l'application paraît
plantée, et sans sortie, elle l'est.
"""

import pathlib

from . import geometry  # noqa: F401  (réexporté)
from .dxfimport import Cancelled, ImportReport

#: finesse d'aplatissement des courbes, en mm
TOLERANCE_MM = 0.02

#: images que l'on vectorise (voir `trace_image`)
SUFFIXES_IMAGES = ('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tif',
                   '.tiff')

#: métafichiers Windows (voir `metafile`)
SUFFIXES_METAFICHIERS = ('.emf', '.wmf', '.emz', '.wmz')

#: pièces en maillage (voir `maillage`): elles vont aussi au Canva 3D
SUFFIXES_MAILLAGES = ('.stl', '.3dxml')

#: les pièces en volume (Canva 3D): STEP et maillages
SUFFIXES_3D = ('.stp', '.step') + SUFFIXES_MAILLAGES

#: IGES, DWG
SUFFIXES_IGES = ('.igs', '.iges')
SUFFIXES_DWG = ('.dwg',)

#: CATIA natif: fermé — un message dit quoi exporter
SUFFIXES_CATIA = ('.catpart', '.catproduct', '.catdrawing', '.cgr')

MESSAGE_CATIA = (
    "Les fichiers CATIA natifs (.CATPart, .CATProduct, .CATDrawing, "
    ".cgr) sont dans un format fermé. Depuis CATIA, « Enregistrer sous » "
    "STEP (.stp: le plus complet), IGES (.igs), STL ou 3DXML — NeoDrive "
    "les lit tous.")


def est_piece_3d(chemin) -> bool:
    """Une pièce en volume (STEP, STL, 3DXML)?"""
    return str(chemin).lower().endswith(SUFFIXES_3D)

#: extensions lues, dans l'ordre où on les propose
SUFFIXES = (('.dxf', '.pdf', '.ai', '.eps', '.ps', '.svg', '.cdr',
             '.stp', '.step') + SUFFIXES_MAILLAGES + SUFFIXES_IGES
            + SUFFIXES_DWG + SUFFIXES_METAFICHIERS + SUFFIXES_IMAGES
            + SUFFIXES_CATIA)

#: filtre pour les sélecteurs de fichiers
FILE_FILTER = (
    "Dessins, pièces et images (*.dxf *.dwg *.pdf *.ai *.eps *.ps *.svg "
    "*.cdr *.stp *.step *.stl *.3dxml *.igs *.iges *.emf *.wmf *.emz "
    "*.wmz *.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.CATPart "
    "*.CATProduct);;"
    "DWG (*.dwg);;"
    "Pièce maillée STL / CATIA 3DXML (*.stl *.3dxml);;"
    "IGES (*.igs *.iges);;"
    "DXF (*.dxf);;PDF (*.pdf);;Illustrator (*.ai);;"
    "PostScript (*.eps *.ps);;SVG (*.svg);;CorelDRAW (*.cdr);;"
    "Pièce STEP (*.stp *.step);;"
    "Métafichier Windows (*.emf *.wmf *.emz *.wmz);;"
    "Image à vectoriser (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff);;"
    "Tous les fichiers (*)")


def formats_lisibles() -> str:
    """Phrase d'état: ce que ce poste sait ouvrir."""
    from . import vecimport
    etat = vecimport.converter_status()
    natifs = ("DXF, PDF, AI, EPS, PS, SVG, STEP, STL, 3DXML, IGES, EMF, "
              "WMF, images (vectorisées)")
    from . import dwg
    natifs += f" — {dwg.etat()}"
    if etat.get('ok'):
        return f"{natifs}, CDR (via {etat.get('nom', 'convertisseur')})"
    return f"{natifs} — CDR indisponible ({etat.get('raison', '')})"


def lire(chemin, *, tolerance_mm: float = TOLERANCE_MM,
         units_mm: float = None, progress=None, ask=None, options=None):
    """Tracés d'un dessin, quel que soit son format.

    Rend `({calque: [Chemin]}, rapport)`. Un `Chemin` porte ses
    courbes et se lit comme la liste de ses points. Les formats sans
    notion de calque (PDF, SVG, PostScript) rendent tout sous
    « dessin ». Une image est vectorisée avec `options`
    (`trace_image.Reglages`, ou leur dictionnaire; défaut sinon):
    calques « contours » et « traits ».
    """
    suffixe = pathlib.Path(chemin).suffix.lower()
    if suffixe in SUFFIXES_CATIA:
        from .dxfimport import DxfError
        raise DxfError(MESSAGE_CATIA)
    if suffixe in SUFFIXES_MAILLAGES:
        from . import maillage
        return maillage.lire(chemin, tolerance_mm=tolerance_mm,
                             units_mm=units_mm, progress=progress)
    if suffixe in SUFFIXES_IGES:
        from . import iges
        return iges.lire(chemin, tolerance_mm=tolerance_mm,
                         units_mm=units_mm, progress=progress)
    if suffixe in SUFFIXES_DWG:
        from . import dwg
        return dwg.lire(chemin, tolerance_mm=tolerance_mm,
                        units_mm=units_mm, progress=progress, ask=ask)
    if suffixe in SUFFIXES_METAFICHIERS:
        from . import metafile
        return metafile.lire(chemin, tolerance_mm=tolerance_mm,
                             units_mm=units_mm, progress=progress)
    if suffixe in SUFFIXES_IMAGES:
        from . import trace_image
        reglages = options
        if isinstance(options, dict):
            connus = set(trace_image.Reglages.__dataclass_fields__)
            reglages = trace_image.Reglages(
                **{k: v for k, v in options.items() if k in connus})
        return trace_image.lire(chemin, reglages, progress=progress,
                                tolerance_mm=tolerance_mm)
    if suffixe in ('.stp', '.step'):
        from . import stepread
        try:
            return stepread.lire(chemin, tolerance_mm=tolerance_mm,
                                 units_mm=units_mm, progress=progress,
                                 ask=ask)
        except stepread.StepError as err:
            from .dxfimport import DxfError
            raise DxfError(f"STEP: {err}") from None
    if suffixe == '.dxf':
        from . import dxfimport
        return dxfimport.read(chemin, tolerance_mm=tolerance_mm,
                              units_mm=units_mm, progress=progress,
                              ask=ask)
    from . import vecimport
    polylignes, rapport = vecimport.read(
        chemin, tolerance_mm=tolerance_mm, units_mm=units_mm,
        progress=progress, ask=ask)
    return {'dessin': polylignes}, rapport


def sait_lire(chemin) -> bool:
    """Ce fichier est-il d'un format que l'on lit ?"""
    return pathlib.Path(chemin).suffix.lower() in SUFFIXES


__all__ = ['lire', 'sait_lire', 'formats_lisibles', 'geometry',
           'Cancelled', 'ImportReport', 'SUFFIXES', 'SUFFIXES_IMAGES',
           'SUFFIXES_METAFICHIERS', 'SUFFIXES_MAILLAGES', 'SUFFIXES_3D',
           'SUFFIXES_IGES', 'SUFFIXES_DWG', 'SUFFIXES_CATIA',
           'est_piece_3d', 'FILE_FILTER', 'TOLERANCE_MM']
