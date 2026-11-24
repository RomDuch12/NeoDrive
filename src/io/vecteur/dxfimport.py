"""Import DXF / DXF import.

S'appuie sur **ezdxf** pour lire le fichier, puis aplatit toutes les
entités géométriques en polylignes millimétriques.

Choix de conception :

* **un tracé par calque.** Dans un DXF de production, les calques séparent
  presque toujours ce qui doit être marqué de ce qui doit être découpé.
  Importer calque par calque permet d'affecter une recette différente à
  chacun sans avoir à redécouper la géométrie à la main.
* **les blocs sont éclatés** (`virtual_entities`), y compris imbriqués :
  ce qui est visible dans le DXF est ce qui est gravé.
* **le texte est rendu en contours**, via `textvec` et la police
  déclarée par le style DXF — ou une substitution choisie par
  l'utilisateur si elle n'est pas sur ce poste (voir `fontmap`). La
  forme des lettres peut donc différer de ce que le concepteur voyait ;
  le contenu et la position, non.
"""
from __future__ import annotations

import pathlib

# ezdxf se charge à la première lecture d'un DXF, pas au démarrage
# de l'application (plus d'une seconde): voir `_flatten`,
# `_open_document` et `read`

from . import geometry as G
from .geometry import Polyline, bounds

#: Facteur de conversion vers le millimètre, par code $INSUNITS.
INSUNITS_TO_MM = {
    0: 1.0,        # sans unité : on suppose des millimètres
    1: 25.4,       # pouces
    2: 304.8,      # pieds
    4: 1.0,        # millimètres
    5: 10.0,       # centimètres
    6: 1000.0,     # mètres
    8: 0.0254,     # microns
    9: 0.001,      # mils
    10: 914.4,     # yards
}

#: Entités dont on sait extraire un tracé.
GEOMETRIC = ('LINE', 'LWPOLYLINE', 'POLYLINE', 'CIRCLE', 'ARC', 'ELLIPSE',
             'SPLINE', 'HELIX')
#: Entités volontairement ignorées, comptées pour le rapport. TEXT et
#: MTEXT n'y sont plus : ils sont rendus en contours (voir
#: `_text_polylines`). ATTRIB/ATTDEF sont des champs de bloc, souvent
#: redondants avec le TEXT visible qui les accompagne ; les coter et
#: les cotes elles-mêmes (DIMENSION, LEADER) n'ont pas de sens à graver.
IGNORED_TEXT = ('ATTRIB', 'ATTDEF', 'DIMENSION', 'LEADER', 'MULTILEADER')


class DxfError(RuntimeError):
    """Fichier illisible ou sans géométrie exploitable."""


class Cancelled(RuntimeError):
    """L'opérateur a interrompu la lecture en cours.

    Distinct de `DxfError` : rien n'a échoué, on a simplement arrêté. Le
    dire par une exception plutôt que par un retour vide évite d'avoir à
    tester le résultat à chaque étage — et évite surtout d'annoncer
    « fichier illisible » à qui vient de presser *Annuler*.
    """


#: Libellés des unités, pour l'interface.
UNIT_CHOICES = (('millimètre', 1.0), ('centimètre', 10.0),
                ('mètre', 1000.0), ('pouce', 25.4))


class ImportReport:
    """Ce qui a été lu, et ce qui ne l'a pas été."""

    def __init__(self) -> None:
        self.units_mm: float = 1.0
        self.declared_units_mm: float = 1.0
        self.units_overridden: bool = False
        self.layers: dict[str, int] = {}
        self.skipped_text: int = 0
        self.skipped_other: dict[str, int] = {}
        #: Remarques sur la lecture — une cote suspecte, une convention
        #: d'origine qui ne se voit pas dans la géométrie.
        self.notes: list[str] = []
        #: Texte rendu avec une police de substitution plutôt que la
        #: police déclarée : {nom déclaré: nombre d'entités}.
        self.font_substitutions: dict[str, int] = {}
        self.polylines: int = 0
        self.extent: tuple[float, float, float, float] | None = None

    def size_mm(self) -> tuple[float, float]:
        if not self.extent:
            return (0.0, 0.0)
        x1, y1, x2, y2 = self.extent
        return (x2 - x1, y2 - y1)

    def fits(self, field_w: float, field_h: float) -> bool:
        w, h = self.size_mm()
        return w <= field_w and h <= field_h

    def unit_warning(self, field_w: float, field_h: float) -> str:
        """Message si la taille obtenue est manifestement invraisemblable.

        L'en-tête `$INSUNITS` d'un DXF est souvent faux : un fichier tracé
        en millimètres peut se déclarer en mètres. Plutôt que de deviner en
        silence, on signale l'incohérence et on laisse choisir.
        """
        w, h = self.size_mm()
        if self.fits(field_w, field_h):
            return ''
        ratio = max(w / field_w if field_w else 0, h / field_h if field_h else 0)
        message = (f'La géométrie mesure {w:.1f} × {h:.1f} mm, soit '
                   f'{ratio:.0f} fois le champ de marquage '
                   f'({field_w:g} × {field_h:g} mm).')
        for label, factor in UNIT_CHOICES:
            if factor >= self.units_mm:
                continue
            alt_w, alt_h = w * factor / self.units_mm, h * factor / self.units_mm
            if alt_w <= field_w and alt_h <= field_h:
                message += (f'\n\nEn lisant le fichier en {label}s, elle ferait '
                            f'{alt_w:.1f} × {alt_h:.1f} mm — ce qui tiendrait '
                            f'dans le champ.')
                break
        return message

    def summary(self) -> str:
        parts = [f'{self.polylines} polyligne(s)',
                 f'{len(self.layers)} calque(s)']
        if self.extent:
            x1, y1, x2, y2 = self.extent
            parts.append(f'{x2 - x1:.1f} × {y2 - y1:.1f} mm')
        if self.skipped_text:
            parts.append(f'{self.skipped_text} texte(s) ignoré(s)')
        if self.skipped_other:
            total = sum(self.skipped_other.values())
            kinds = ', '.join(sorted(self.skipped_other))
            parts.append(f'{total} entité(s) non gérée(s) : {kinds}')
        if self.font_substitutions:
            total_sub = sum(self.font_substitutions.values())
            noms = ', '.join(sorted(self.font_substitutions))
            parts.append(f'{total_sub} texte(s) avec une police de '
                         f'substitution ({noms})')
        parts.extend(self.notes)
        return ' · '.join(parts)


def _flatten(entity, tolerance: float) -> list:
    """Tracés d'une entité, dans ses coordonnées d'origine.

    Rend des `G.Chemin`: ezdxf donne les arcs en Béziers cubiques, et
    on les garde. Aplatis, ils ne redeviennent jamais des courbes —
    un cercle importé montrerait ses facettes au zoom.
    """
    from ezdxf import path as ezpath
    from ezdxf.path import Command
    try:
        p = ezpath.make_path(entity)
    except (ValueError, TypeError, AttributeError):
        return []
    out = []
    for sub in p.sub_paths() or [p]:
        commandes = list(sub.commands())
        if not commandes:
            continue
        chemin = G.Chemin(tolerance=tolerance)
        chemin.moveto(sub.start.x, sub.start.y)
        for c in commandes:
            fin = c.end
            if c.type == Command.LINE_TO:
                chemin.lineto(fin.x, fin.y)
            elif c.type == Command.CURVE4_TO:
                chemin.cubicto((c.ctrl1.x, c.ctrl1.y),
                               (c.ctrl2.x, c.ctrl2.y), (fin.x, fin.y))
            elif c.type == Command.CURVE3_TO:
                # une quadratique s'élève exactement en cubique
                x0, y0 = chemin.points[-1]
                qx, qy = c.ctrl.x, c.ctrl.y
                chemin.cubicto(
                    (x0 + 2 / 3 * (qx - x0), y0 + 2 / 3 * (qy - y0)),
                    (fin.x + 2 / 3 * (qx - fin.x),
                     fin.y + 2 / 3 * (qy - fin.y)),
                    (fin.x, fin.y))
            else:                       # MOVE_TO
                chemin.moveto(fin.x, fin.y)
        if len(chemin) >= 2:
            out.append(chemin)
    return out


def _dxf_font_name(doc, style_name: str) -> str:
    """Le nom de police porté par un style DXF, ou le style lui-même.

    Un style AutoCAD référence un fichier — `.shx` la plupart du temps,
    une police vectorielle propre à AutoCAD, ou `.ttf` quand le dessin
    vient d'un logiciel qui a laissé Windows fournir les polices. Un
    `.shx` n'est jamais installé sur ce poste : `fontmap` s'en remettra
    au nom du style, puis à la substitution.
    """
    try:
        style = doc.styles.get(style_name)
    except Exception:
        style = None
    fichier = getattr(getattr(style, 'dxf', None), 'font', '') if style else ''
    if fichier and fichier.lower().endswith(('.ttf', '.ttc', '.otf')):
        return pathlib.Path(fichier).stem
    return style_name or 'Standard'


def _text_polylines(entity, kind: str, tolerance: float, doc,
                    ask, report) -> list[Polyline]:
    """Contours d'un TEXT ou MTEXT, dans les unités du dessin.

    Rendu par `textvec`, avec la police déclarée par le style — ou une
    substitution si elle n'est pas sur ce poste (voir `fontmap`). La
    position suit l'ancrage DXF (alignement horizontal pour TEXT, les
    neuf points d'ancrage pour MTEXT) ; l'habillage automatique d'un
    MTEXT trop large n'est **pas** reproduit, faute d'un moteur de mise
    en page complet — le texte sort sur une seule ligne par retour
    explicite du fichier.
    """
    from . import fontmap, textvec
    import math

    if kind == 'TEXT':
        texte = entity.dxf.get('text', '')
        if not texte.strip():
            return []
        hauteur = entity.dxf.get('height', 0.0) or 0.0
        if hauteur <= 0:
            return []
        style_name = entity.dxf.get('style', 'Standard')
        rotation = entity.dxf.get('rotation', 0.0) or 0.0
        insert = entity.dxf.get('insert', (0.0, 0.0))
        lignes = [texte]
        halign = int(entity.dxf.get('halign', 0) or 0)
        col = 'right' if halign == 2 else ('center' if halign in (1, 4) else 'left')
        row = 'top'
        pas = hauteur * 1.667
    else:                                              # MTEXT
        try:
            texte = entity.plain_text()
        except Exception:
            texte = getattr(entity, 'text', '') or ''
        lignes = [l for l in texte.split('\n')]
        if not any(l.strip() for l in lignes):
            return []
        hauteur = entity.dxf.get('char_height', 0.0) or 0.0
        if hauteur <= 0:
            return []
        style_name = entity.dxf.get('style', 'Standard')
        rotation = entity.dxf.get('rotation', 0.0) or 0.0
        insert = entity.dxf.get('insert', (0.0, 0.0))
        point = int(entity.dxf.get('attachment_point', 1) or 1)
        col = 'left' if point in (1, 4, 7) else ('right' if point in (3, 6, 9) else 'center')
        row = 'top' if point <= 3 else ('bottom' if point >= 7 else 'middle')
        facteur = entity.dxf.get('line_spacing_factor', 1.0) or 1.0
        pas = hauteur * 1.667 * facteur

    nom_police = _dxf_font_name(doc, style_name)
    police, exact = fontmap.resolve(nom_police, ask=ask)
    if not exact:
        report.font_substitutions[nom_police] = (
            report.font_substitutions.get(nom_police, 0) + 1)

    # chaque ligne, posée dans son propre repère puis calée sur le bloc
    largeurs = [textvec.advance_width(l, hauteur, police) for l in lignes]
    largeur_bloc = max(largeurs) if largeurs else 0.0
    contours: list[Polyline] = []
    for index, (ligne, largeur) in enumerate(zip(lignes, largeurs)):
        if not ligne.strip():
            continue
        c = textvec.outline(ligne, hauteur, police, tolerance_mm=tolerance)
        if col == 'center':
            dx = (largeur_bloc - largeur) / 2
        elif col == 'right':
            dx = largeur_bloc - largeur
        else:
            dx = 0.0
        dy = -index * pas
        contours.extend([[(x + dx, y + dy) for x, y in poly] for poly in c])
    if not contours:
        return []

    # décalage du bloc entier pour que le point d'ancrage tombe sur
    # l'origine, avant rotation et translation vers `insert`
    if col == 'center':
        shift_x = -largeur_bloc / 2
    elif col == 'right':
        shift_x = -largeur_bloc
    else:
        shift_x = 0.0
    haut = hauteur                          # approx. hauteur de capitale
    bas = -pas * (len(lignes) - 1) - hauteur * 0.25
    if row == 'top':
        shift_y = -haut
    elif row == 'bottom':
        shift_y = -bas
    else:
        shift_y = -(haut + bas) / 2

    rad = math.radians(rotation)
    cos_r, sin_r = math.cos(rad), math.sin(rad)
    ix, iy = float(insert[0]), float(insert[1])
    placed: list[Polyline] = []
    for poly in contours:
        nouveau = []
        for x, y in poly:
            x, y = x + shift_x, y + shift_y
            x, y = x * cos_r - y * sin_r, x * sin_r + y * cos_r
            nouveau.append((x + ix, y + iy))
        placed.append(nouveau)
    return placed


class _WatchedStream:
    """Un flux texte qui compte ce qu'il a lu et se laisse interrompre.

    `ezdxf.readfile` est un appel d'un seul tenant : sur un dessin de cinq
    mégaoctets il occupe trois secondes pendant lesquelles rien ne bouge et
    *Annuler* reste sans effet. Or `ezdxf.read` accepte un flux, et n'en
    demande guère plus qu'un `readline`.

    Ce flux-là compte donc les caractères rendus et le dit, tous les
    256 ko. Le rapport peut lever `Cancelled` : la lecture s'arrête alors
    au beau milieu de l'analyse, ce qui est bien le but.
    """

    #: Un rapport tous les 256 ko : assez fin pour que la barre avance,
    #: assez rare pour ne rien coûter sur des millions de lignes.
    PAS = 256 * 1024

    def __init__(self, fp, taille: int, rapport) -> None:
        self._fp = fp
        self._taille = max(1, taille)
        self._rapport = rapport
        self._lus = 0
        self._prochain = self.PAS

    def readline(self, *args):
        ligne = self._fp.readline(*args)
        self._lus += len(ligne)
        if self._lus >= self._prochain:
            self._prochain = self._lus + self.PAS
            self._rapport(min(1.0, self._lus / self._taille))
        return ligne

    def __iter__(self):
        return self

    def __next__(self):
        ligne = self.readline()
        if not ligne:
            raise StopIteration
        return ligne

    def __getattr__(self, nom):
        return getattr(self._fp, nom)


def _open_document(path, rapport):
    """Ouvre un DXF en rendant des comptes, et en pouvant s'interrompre.

    Retombe sur `ezdxf.readfile` — muet mais sûr — pour un DXF binaire, ou
    si cette version d'ezdxf ne présente pas les fonctions employées ici.
    Le compte rendu est un agrément ; la lecture, non.
    """
    import ezdxf
    chemin = str(path)
    try:
        from ezdxf.filemanagement import dxf_file_info
        from ezdxf.lldxf.validator import is_binary_dxf_file, is_dxf_file
    except ImportError:                     # pragma: no cover - vieux ezdxf
        return ezdxf.readfile(chemin)
    if is_binary_dxf_file(chemin) or not is_dxf_file(chemin):
        return ezdxf.readfile(chemin)
    info = dxf_file_info(chemin)
    taille = pathlib.Path(chemin).stat().st_size
    with open(chemin, mode='rt', encoding=info.encoding,
              errors='surrogateescape') as fp:
        doc = ezdxf.read(_WatchedStream(fp, taille, rapport))
    doc.filename = chemin
    return doc


def _iter_entities(container, depth: int = 0):
    """Parcourt les entités en éclatant les blocs, jusqu'à 8 niveaux."""
    for entity in container:
        kind = entity.dxftype()
        if kind == 'INSERT' and depth < 8:
            try:
                yield from _iter_entities(entity.virtual_entities(), depth + 1)
            except Exception:
                pass                       # bloc non résoluble : ignoré
            continue
        yield entity


def read(path: str | pathlib.Path, *, tolerance_mm: float = 0.02,
         units_mm: float | None = None, progress=None, ask=None
         ) -> tuple[dict[str, list[Polyline]], ImportReport]:
    """Lit un DXF. Retourne ({calque: polylignes}, rapport).

    Les coordonnées sont converties en millimètres selon `$INSUNITS`, sauf
    si `units_mm` impose un facteur — l'en-tête des DXF étant fréquemment
    faux, cette échappatoire est nécessaire.

    `progress(fraction, texte)` est appelé au fil de la lecture ; s'il rend
    `False`, `Cancelled` est levée. Un dessin de dix mégaoctets demande
    plusieurs secondes : sans reddition de comptes, l'application paraît
    plantée, et sans sortie, elle l'est.

    `ask(nom, candidats)` — voir `fontmap.resolve` — est appelé si un
    TEXT ou MTEXT déclare une police absente du poste. Sans `ask`, la
    substitution retombe silencieusement sur un alias connu ou la police
    par défaut.

    Les deux moitiés du travail — l'analyse du fichier puis
    l'aplatissement des entités — pèsent à peu près autant, et toutes deux
    rendent des comptes : la première à travers le flux surveillé, la
    seconde entité par entité.
    """
    def avance(part: float, texte: str) -> None:
        if progress is not None and progress(part, texte) is False:
            raise Cancelled(texte)

    import ezdxf
    avance(0.0, 'ouverture du fichier…')
    try:
        doc = _open_document(
            path, lambda part: avance(0.4 * part, 'lecture du fichier…'))
    except (OSError, ezdxf.DXFError) as exc:
        raise DxfError(f'lecture impossible : {exc}') from exc
    avance(0.4, 'analyse des entités…')

    report = ImportReport()
    code = doc.header.get('$INSUNITS', 4)
    report.declared_units_mm = INSUNITS_TO_MM.get(code, 1.0)
    if units_mm is None:
        report.units_mm = report.declared_units_mm
    else:
        report.units_mm = units_mm
        report.units_overridden = (units_mm != report.declared_units_mm)
    scale = report.units_mm

    # la tolérance d'aplatissement est exprimée en mm : on la ramène
    # aux unités du fichier avant de la passer à ezdxf
    tolerance = max(tolerance_mm / scale, 1e-6)

    from . import fontmap
    ask_une_fois = fontmap.cached_ask(ask) if ask is not None else None

    layers: dict[str, list[Polyline]] = {}
    # Dénominateur pris sur l'espace objet, sans éclater les blocs :
    # les compter d'abord coûterait le prix de l'import une seconde fois.
    # Un dessin fait d'INSERT dépassera donc les 100 % — la fraction est
    # bornée, la barre continue d'avancer, et personne n'y perd.
    attendu = max(1, len(doc.modelspace()))
    for rang, entity in enumerate(_iter_entities(doc.modelspace())):
        if rang % 64 == 0:
            avance(0.4 + 0.55 * min(1.0, rang / attendu),
                   f'{rang} entités lues')
        kind = entity.dxftype()
        if kind in ('TEXT', 'MTEXT'):
            polylines = _text_polylines(entity, kind, tolerance, doc,
                                        ask_une_fois, report)
            if not polylines:
                report.skipped_text += 1
                continue
            layer = getattr(entity.dxf, 'layer', '0') or '0'
            scaled = [[(x * scale, y * scale) for x, y in poly]
                      for poly in polylines]
            layers.setdefault(layer, []).extend(scaled)
            continue
        if kind in IGNORED_TEXT:
            report.skipped_text += 1
            continue
        if kind not in GEOMETRIC:
            report.skipped_other[kind] = report.skipped_other.get(kind, 0) + 1
            continue
        polylines = _flatten(entity, tolerance)
        if not polylines:
            report.skipped_other[kind] = report.skipped_other.get(kind, 0) + 1
            continue
        layer = getattr(entity.dxf, 'layer', '0') or '0'
        # L'échelle s'applique aux points de contrôle comme aux
        # sommets: une Bézier mise à l'échelle reste une Bézier
        scaled = [chemin.transforme(lambda x, y: (x * scale, y * scale))
                  for chemin in polylines]
        layers.setdefault(layer, []).extend(scaled)

    if not layers:
        raise DxfError('aucune géométrie exploitable dans ce fichier')

    avance(0.95, 'mesure de l\'emprise…')
    report.layers = {name: len(polys) for name, polys in layers.items()}
    report.polylines = sum(report.layers.values())
    report.extent = bounds([p for polys in layers.values() for p in polys])
    avance(1.0, 'terminé')
    return layers, report


def is_dxf(path) -> bool:
    return pathlib.Path(path).suffix.lower() == '.dxf'
