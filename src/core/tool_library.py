"""
Module de gestion de la bibliothèque d'outils pour NeoDrive v1.0
"""

import os
import sys
from datetime import datetime
from typing import Dict, List, Optional


def get_base_dir() -> str:
    """Résout le répertoire de base (dev ou PyInstaller)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _slug_tool_id(name: str, article: str) -> str:
    """Identifiant interne stable pour un outil importé."""
    import re as _re
    base = _re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')
    return f"{base or 'outil'}_{article.lower()}"


def _normaliser_nom(nom: str) -> str:
    import unicodedata
    brut = unicodedata.normalize('NFKD', str(nom or ""))
    brut = brut.encode('ascii', 'ignore').decode('ascii')
    return brut.replace(',', '.').lower()


#: un nombre d'atelier: « 2 », « 0.6 », « 4.2 »
_NOMBRE = r'(\d+(?:\.\d+)?)'


def geometrie_depuis_nom(nom: str) -> dict:
    """La géométrie que le nom d'atelier dit de l'outil.

    « Cyl 2 z1L4 » → Ø 2, 1 dent, longueur UTILE 4; « Con 30° 0.6 »
    → pointe 30°, troncature 0,6; « Foret Ø4.2 L21 » → Ø 4,2, utile
    21; « Chamfer 90° z3L3 » → pointe 90°, 3 dents. Rien n'est deviné
    au-delà de ce que le nom écrit.

    Le « L » d'un nom d'atelier est la longueur utile (« Cyl 8 z1L41 »:
    41 mm sous l'épaulement, pour 17 mm de coupe) — `ShoulderLength`
    chez Datron. La longueur de COUPE (`FluteLength`) ne se lit pas
    dans le nom: le catalogue la donne."""
    import re
    n = _normaliser_nom(nom)
    g = {}
    m = re.search(r'\bcyl\s*' + _NOMBRE, n)
    if m:
        g['Diameter'] = float(m.group(1))
        g['TipAngle'] = 0.0
        g['TipDiameter'] = float(m.group(1))
    m = re.search(r'\bcon\s*' + _NOMBRE + r'\s*\s*' + _NOMBRE + '?', n)
    if m and 'Diameter' not in g:
        g['TipAngle'] = float(m.group(1))
        if m.group(2):
            g['TipDiameter'] = float(m.group(2))
    m = re.search(r'\b(?:foret|drill)\s*(?:o|d)?\s*' + _NOMBRE, n)
    if m and 'Diameter' not in g:
        g['Diameter'] = float(m.group(1))
    m = re.search(r'\b(?:chamfer|cham|chanfrein)\s*' + _NOMBRE, n)
    if m and 'TipAngle' not in g:
        g['TipAngle'] = float(m.group(1))
    m = re.search(r'\b(?:extrad|t-?slot)\s*' + _NOMBRE, n)
    if m and 'Diameter' not in g:
        g['Diameter'] = float(m.group(1))
    m = re.search(r'\bz\s*(\d+)', n)
    if m:
        g['NumberOfFlutes'] = int(m.group(1))
    m = re.search(r'\bz\d+\s*l' + _NOMBRE
                  + r'|(?<![a-z])l\s*' + _NOMBRE + r'\b', n)
    if m:
        g['ShoulderLength'] = float(m.group(1) or m.group(2))
    m = re.search(r'\br' + _NOMBRE + r'\b', n)
    if m and 'extrad' in n:
        g['CornerRadius'] = float(m.group(1))
    return g


def extract_article_nr(reference: str) -> str:
    """Extrait le numéro d'article depuis le champ reference.
    Format: '0068443G / 114206' -> '0068443G'
    Ou simple: '0068420L' -> '0068420L'
    """
    if not reference:
        return ""
    parts = reference.split("/")
    return parts[0].strip()


def reference_avec_article(reference: str, article: str) -> str:
    """La référence dont on a corrigé l'ARTICLE seul (ce que montre la
    colonne Réf): '0068443G / 114206' + '0068443H' -> '0068443H / 114206'.
    Un texte qui porte déjà son « / » remplace tout; un texte vide
    efface la référence."""
    article = (article or "").strip()
    if not article or "/" in article:
        return article
    reste = (reference or "").split("/", 1)
    if len(reste) < 2:
        return article
    return f"{article} / {reste[1].strip()}"


#: les couleurs des outils au plan 2D, dans la légende et en 3D:
#: teintes distinctes, lisibles sur fond sombre comme sur blanc
PALETTE_OUTILS = (
    "#89b4fa", "#a6e3a1", "#f9e2af", "#fab387", "#f38ba8",
    "#cba6f7", "#94e2d5", "#eba0ac", "#74c7ec", "#b4befe",
    "#f5c2e7", "#a6adc8",
)


def couleur_valide(valeur) -> str:
    """« #rrggbb » (minuscules) ou "" si la valeur n'en est pas une."""
    texte = str(valeur or "").strip().lower()
    if len(texte) == 7 and texte[0] == "#":
        try:
            int(texte[1:], 16)
            return texte
        except ValueError:
            return ""
    return ""


def couleur_de_rang(rang: int) -> str:
    """La couleur automatique du `rang`-ième outil: la palette, puis
    des teintes réparties au nombre d'or (toutes distinctes, mêmes
    clarté et saturation que la palette)."""
    if rang < len(PALETTE_OUTILS):
        return PALETTE_OUTILS[rang]
    import colorsys
    teinte = ((rang - len(PALETTE_OUTILS)) * 0.6180339887 + 0.07) % 1.0
    r, v, b = colorsys.hsv_to_rgb(teinte, 0.42, 0.96)
    return "#%02x%02x%02x" % (int(r * 255), int(v * 255), int(b * 255))


class Tool:
    """Représente un outil CNC"""

    def __init__(self, data: dict):
        self.name = data.get('name', '')
        self.reference = data.get('reference', '')
        self.type_taraudage = data.get('type_taraudage', '')
        self.rpm = data.get('rpm', 40000)
        self.feed_finishing = data.get('feed_finishing', 800)
        self.feed_approach = data.get('feed_approach', 1000)
        self.feed_plunge = data.get('feed_plunge', 500)
        self.feed_ramp = data.get('feed_ramp', 400)
        self.feed_roughing = data.get('feed_roughing', 400)
        self.diameter = data.get('diameter', 0)  # mm, 0 = inconnu
        self.coolant = data.get('coolant', 'spray')
        self.vendor = data.get('vendor', 'DATRON')
        self.min_depth = data.get('min_depth', 2.0)
        self.max_depth = data.get('max_depth', 15.0)
        self.notes = data.get('notes', '')
        self.last_used = data.get('last_used', None)
        self.usage_count = data.get('usage_count', 0)
        # ── Géométrie Datron (@ ToolDescription @) ──
        # Renseignée à l'import d'un SimPl externe; permet de
        # RE-déclarer l'outil dans l'en-tête des programmes générés
        # (la machine s'en sert pour la simulation et le contrôle de
        # collision).
        self.geometry = dict(data.get('geometry', {}) or {})
        # ── Données constructeur (catalogue DATRON) ──
        # Cotes, famille, prix et avances recommandées, rangés À CÔTÉ
        # des réglages: ils ne remplacent aucune avance de l'outil.
        self.constructeur = dict(data.get('constructeur') or {})
        # Sur le jumeau « avances DATRON »: l'outil qu'il double
        self.jumeau_de = str(data.get('jumeau_de') or '')
        # Sa couleur au plan, dans la légende et en 3D (« #rrggbb »,
        # choisie par l'utilisateur; "" = automatique)
        self.couleur = couleur_valide(data.get('couleur'))
        # Ce que cette version ne connaît pas (champs d'une version
        # plus récente, ajouts à la main) repart tel quel à
        # l'écriture: tools.json ne s'appauvrit pas en passant ici.
        self.extra = {k: v for k, v in data.items()
                      if k not in self._CLES}

    #: les clés de tools.json que cette version lit
    _CLES = ('name', 'reference', 'type_taraudage', 'rpm',
             'feed_finishing', 'feed_approach', 'feed_plunge',
             'feed_ramp', 'feed_roughing', 'diameter', 'coolant',
             'vendor', 'min_depth', 'max_depth', 'notes', 'last_used',
             'usage_count', 'geometry', 'constructeur', 'jumeau_de',
             'couleur')

    #: les réglages qu'une recommandation DATRON renseigne
    CHAMPS_AVANCES = ('rpm', 'feed_roughing', 'feed_finishing',
                      'feed_plunge', 'feed_ramp')

    #: ce que les listes d'outils ajoutent au jumeau constructeur
    MARQUE_DATRON = " · avances DATRON"

    #: champs @ ToolDescription @ et leur type — la fiche COMPLÈTE
    #: telle que la machine la connaît (ses métadonnées listent
    #: aussi TaperAngle, ThreadAngle et FluteAngle)
    GEOMETRY_FIELDS = {
        'Category': str, 'ToolNumber': int, 'Diameter': float,
        'TipAngle': float, 'TipDiameter': float, 'FluteLength': float,
        'CornerRadius': float, 'ShoulderLength': float,
        'ShoulderDiameter': float, 'BodyLength': float,
        'NumberOfFlutes': int, 'ThreadPitch': float,
        'ShaftDiameter': float, 'OverallLength': float,
        'TaperAngle': float, 'ThreadAngle': float, 'FluteAngle': float,
    }

    #: ordre d'écriture des champs (identique aux fichiers Datron)
    _GEOM_ORDER = ('Diameter', 'TipAngle', 'TipDiameter', 'FluteLength',
                   'CornerRadius', 'ShoulderLength', 'ShoulderDiameter',
                   'BodyLength', 'NumberOfFlutes', 'ThreadPitch',
                   'ShaftDiameter', 'OverallLength', 'TaperAngle',
                   'ThreadAngle', 'FluteAngle')

    #: catégories vues dans les programmes que la machine a acceptés;
    #: « Unspecified » est celle de tous les programmes de l'atelier
    CATEGORIES = ('Unspecified', 'MillingEndFlat', 'MillingEndBall',
                  'Graver')

    #: libellés français des champs, dans l'ordre de la fiche
    GEOMETRY_LABELS = (
        ('Category', "Catégorie"), ('ToolNumber', "N° d'outil"),
        ('Diameter', "Ø de coupe"), ('TipAngle', "Angle de pointe (°)"),
        ('TipDiameter', "Ø de pointe (troncature)"),
        ('FluteLength', "Longueur de coupe (L coupe)"),
        ('ShoulderLength', "Longueur utile (L utile)"),
        ('CornerRadius', "Rayon de bec"),
        ('NumberOfFlutes', "Nombre de dents"),
        ('ShaftDiameter', "Ø de queue"),
        ('ShoulderDiameter', "Ø de dégagement (col)"),
        ('BodyLength', "Longueur de corps"),
        ('OverallLength', "Longueur totale"),
        ('ThreadPitch', "Pas de filet"),
        ('ThreadAngle', "Angle de filet (°)"),
        ('TaperAngle', "Angle de cône (°)"),
        ('FluteAngle', "Angle d'hélice (°)"),
    )

    def geometrie_lisible(self) -> str:
        """« Ø2 · 1 dent(s) · L4 » / « 30° · pointe 0.6 »: la
        géométrie en un coup d'œil, pour le tableau des outils."""
        g = self.geometry or {}
        morceaux = []
        try:
            angle = float(g.get('TipAngle') or 0)
        except (TypeError, ValueError):
            angle = 0.0
        if angle > 0:
            morceaux.append(f"{angle:g}°")
            if g.get('TipDiameter') not in (None, ""):
                morceaux.append(f"pointe {float(g['TipDiameter']):g}")
        elif g.get('Diameter'):
            morceaux.append(f"Ø{float(g['Diameter']):g}")
        if g.get('NumberOfFlutes'):
            morceaux.append(f"{int(g['NumberOfFlutes'])} dent(s)")
        # L coupe et L utile: deux longueurs, deux mesures
        if g.get('FluteLength'):
            morceaux.append(f"Lc{float(g['FluteLength']):g}")
        if g.get('ShoulderLength'):
            morceaux.append(f"Lu{float(g['ShoulderLength']):g}")
        if g.get('CornerRadius'):
            morceaux.append(f"r{float(g['CornerRadius']):g}")
        return " · ".join(morceaux)

    def tool_description(self, name: str = "") -> str:
        """Annotation @ ToolDescription @ de cet outil.

        TOUJOURS — même sans géométrie: nom, catégorie, article et
        fabricant, comme dans les programmes de l'atelier. C'est la
        liste que l'opérateur lit devant la machine pour vérifier
        que ses outils sont au magasin. Ce que la fiche sait de plus
        (Ø, angle, longueur de coupe…) suit; ce qu'elle ignore n'est
        pas inventé."""
        # en ASCII, comme tous les programmes que la machine a lus:
        # « Con 30° 0.6 » s'y écrit « Con 30 0.6 »
        import unicodedata
        nom = unicodedata.normalize('NFKD', str(name or self.name))
        nom = nom.encode('ascii', 'ignore').decode('ascii')
        nom = " ".join(nom.replace('"', "'").split())
        parts = [f'"Name":"{nom}"']
        parts.append(
            f'"Category":"{self.geometry.get("Category") or "Unspecified"}"')
        parts.append(f'"ArticleNr":"{self.article_nr}"')
        tnum = self.geometry.get('ToolNumber')
        if tnum is not None:
            parts.append(f'"ToolNumber":{int(tnum)}')
        parts.append(f'"Vendor":"{self.vendor or "DATRON"}"')
        for key in self._GEOM_ORDER:
            val = self.geometry.get(key)
            if val is None or val == "":
                continue
            try:
                if key == 'NumberOfFlutes':
                    parts.append(f'"{key}":{int(val)}')
                else:
                    parts.append(f'"{key}":{float(val):g}')
            except (TypeError, ValueError):
                continue
        return "@ ToolDescription : " + ", ".join(parts) + " @"

    def completer_geometrie(self) -> bool:
        """Ce que le NOM dit de l'outil entre dans la fiche, sans
        écraser ce qu'elle sait déjà. Rend vrai si elle a changé."""
        deduit = geometrie_depuis_nom(self.name)
        change = False
        for cle, valeur in deduit.items():
            if self.geometry.get(cle) in (None, ""):
                self.geometry[cle] = valeur
                change = True
        if not self.diameter and deduit.get('Diameter'):
            self.diameter = float(deduit['Diameter'])
            change = True
        return change

    @property
    def article_nr(self) -> str:
        """Retourne le numéro d'article pour SimPl."""
        return extract_article_nr(self.reference)

    @property
    def avances_constructeur(self) -> bool:
        """Vrai si la rotation et les avances de cette fiche SONT
        celles que DATRON recommande (bloc `constructeur`). Dès qu'on
        en règle une, la fiche redevient celle de l'utilisateur — et
        la liste cesse de la marquer."""
        coupe = (self.constructeur or {}).get('coupe') or {}
        if not coupe:
            return False
        for cle in self.CHAMPS_AVANCES:
            try:
                if abs(float(getattr(self, cle)) - float(coupe[cle])) > 0.5:
                    return False
            except (KeyError, TypeError, ValueError):
                return False
        return True

    @property
    def display_name(self) -> str:
        """Nom d'affichage avec reference — et la marque des avances
        DATRON: deux fiches du même outil se distinguent dans la liste
        d'une opération."""
        nom = f"{self.name} [{self.article_nr}]"
        if self.avances_constructeur:
            nom += self.MARQUE_DATRON
        return nom

    def to_dict(self) -> dict:
        d = {
            'name': self.name,
            'reference': self.reference,
            'type_taraudage': self.type_taraudage,
            'rpm': self.rpm,
            'feed_finishing': self.feed_finishing,
            'feed_approach': self.feed_approach,
            'feed_plunge': self.feed_plunge,
            'feed_ramp': self.feed_ramp,
            'feed_roughing': self.feed_roughing,
            'diameter': self.diameter,
            'coolant': self.coolant,
            'vendor': self.vendor,
            'min_depth': self.min_depth,
            'max_depth': self.max_depth,
            'notes': self.notes,
            'last_used': self.last_used,
            'usage_count': self.usage_count,
            'geometry': self.geometry,
        }
        # écrits seulement s'ils existent: une fiche sans données
        # constructeur reste celle que les anciennes versions écrivent
        if self.constructeur:
            d['constructeur'] = self.constructeur
        if self.jumeau_de:
            d['jumeau_de'] = self.jumeau_de
        if self.couleur:
            d['couleur'] = self.couleur
        for cle, valeur in self.extra.items():
            d.setdefault(cle, valeur)
        return d

    def increment_usage(self):
        self.usage_count += 1
        self.last_used = datetime.now().isoformat()


class ToolLibrary:
    """Gestionnaire de bibliothèque d'outils"""

    def __init__(self, filepath: str = None):
        if filepath:
            self.filepath = filepath
        elif os.environ.get('NEODRIVE_TOOLS_FICHIER'):
            # les tests travaillent sur une copie: jamais sur le vrai
            # tools.json (une fenêtre construite l'écrivait déjà)
            self.filepath = os.environ['NEODRIVE_TOOLS_FICHIER']
        else:
            base_dir = get_base_dir()
            self.filepath = os.path.join(base_dir, 'data', 'tools.json')

        self.tools: Dict[str, Tool] = {}
        self.load()

    def load(self):
        """Charge tools.json.

        Illisible, il n'est JAMAIS écrasé: mis de côté, sa sauvegarde
        .bak reprise si elle existe, et `self.alerte` dit ce qui s'est
        passé — la fenêtre l'affiche au démarrage. (Avant: un print
        que personne ne voit, la bibliothèque par défaut, puis un
        enregistrement par-dessus — les outils disparaissaient.)"""
        from src.core.fichiers_surs import lire_json_sur, mettre_de_cote
        # tools.json disparu mais sa sauvegarde là: on la reprend
        # plutôt que la bibliothèque par défaut (qui, enregistrée,
        # aurait fini par écraser cette sauvegarde)
        data, self.alerte = lire_json_sur(self.filepath,
                                          reprendre_si_absent=True)
        if data is None:
            self._create_default_library()
        else:
            try:
                tools_data = data.get('tools', data)
                self.tools = {}
                for tool_id, tool_data in tools_data.items():
                    self.tools[tool_id] = Tool(tool_data)
            except Exception as e:
                garde = mettre_de_cote(self.filepath)
                self.alerte = (f"tools.json se lit mais son contenu ne "
                               f"tient pas ({e}). {garde} La "
                               "bibliothèque par défaut est chargée.")
                self._create_default_library()
        if self.alerte:
            print(f"Bibliothèque d'outils: {self.alerte}")
        # Les fiches sans géométrie prennent ce que leur nom dit —
        # une fois, et c'est écrit: la liste d'outils du programme
        # porte alors Ø, angle et longueur utile.
        # L coupe ≠ L utile: les fiches d'avant la distinction sont
        # remises d'aplomb AVANT le complément depuis le nom (une fois:
        # ensuite plus rien ne bouge)
        try:
            from src.core.catalogue_datron import catalogue
            separees = self.separer_longueurs(catalogue())
        except Exception:
            separees = []
        change = self.completer_geometries()
        self.note = ""
        if separees:
            coupes = sum(1 for _tid, c in separees if c)
            self.note = (f"{len(separees)} fiche(s) d'outil: le « L » du "
                         "nom passe en longueur UTILE"
                         + (f", {coupes} longueur(s) de coupe reprise(s) "
                            "du catalogue DATRON" if coupes else "")
                         + ".")
        if change or separees:
            try:
                self.save()
            except OSError:
                pass

    def separer_longueurs(self, catalogue=None) -> list:
        """L coupe ≠ L utile.

        Avant la distinction, la fiche prenait le « L » du nom comme
        longueur de COUPE. Quand la longueur de coupe d'une fiche vaut
        encore ce « L », elle vient du nom: le « L » passe en longueur
        UTILE, et la longueur de coupe devient celle du catalogue
        DATRON si l'outil y est (sinon elle reste: rien n'est deviné).
        Une seconde fois, rien ne bouge. Rend [(outil, longueur de
        coupe changée ?)]."""
        changes = []
        for tid, outil in self.tools.items():
            l_nom = geometrie_depuis_nom(outil.name).get('ShoulderLength')
            g = outil.geometry
            fl = g.get('FluteLength')
            if l_nom is None or fl in (None, ""):
                continue
            try:
                if abs(float(fl) - l_nom) > 1e-6:
                    continue        # une longueur de coupe à part entière
            except (TypeError, ValueError):
                continue
            avant = dict(g)
            if g.get('ShoulderLength') in (None, ""):
                g['ShoulderLength'] = l_nom
            x = catalogue.entree(outil.article_nr) if catalogue else None
            if x is not None and x.get('L2'):
                g['FluteLength'] = float(x['L2'])
            if g != avant:
                changes.append((tid, g.get('FluteLength') !=
                                avant.get('FluteLength')))
        return changes

    def completer_geometries(self) -> int:
        """Complète chaque fiche depuis son nom; rend le nombre de
        fiches changées."""
        n = 0
        for tool in self.tools.values():
            try:
                if tool.completer_geometrie():
                    n += 1
            except Exception:
                continue
        return n

    def save(self):
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        # 3.1: blocs `constructeur` / `jumeau_de` facultatifs — même
        # structure, les versions 3.0 lisent le fichier sans erreur
        data = {
            'version': '3.1',
            'last_modified': datetime.now().isoformat(),
            'tools': {tid: t.to_dict() for tid, t in self.tools.items()}
        }
        from src.core.fichiers_surs import ecrire_json_sur
        # jamais à moitié écrit; la version précédente reste en .bak
        ecrire_json_sur(self.filepath, data, garder_bak=True, indent=2,
                        ensure_ascii=False)

    def _create_default_library(self):
        self.tools = {
            'datron_thr_m25m3': Tool({
                'name': 'Thr M2.5-M3', 'reference': '0068419A / 700385',
                'type_taraudage': 'M3', 'rpm': 40000,
                'feed_finishing': 600, 'feed_approach': 800,
                'feed_plunge': 600, 'feed_ramp': 300, 'feed_roughing': 300,
                'coolant': 'spray', 'vendor': 'DATRON',
                'min_depth': 2.0, 'max_depth': 8.5,
                'notes': 'Default Thread Mill M2.5-M3'
            })
        }
        self.save()

    def get_tool(self, tool_id: str) -> Optional[Tool]:
        return self.tools.get(tool_id)

    def get_tool_by_type(self, type_taraudage: str) -> Optional[Tool]:
        """Retourne le premier outil dont type_taraudage correspond."""
        for tool in self.tools.values():
            if tool.type_taraudage == type_taraudage:
                return tool
        return None

    def get_tool_by_article(self, article_nr: str) -> Optional[Tool]:
        """L'outil de cet article — la fiche de l'utilisateur plutôt
        que son jumeau « avances DATRON »."""
        jumeau = None
        for tool in self.tools.values():
            if tool.article_nr == article_nr:
                if not tool.jumeau_de:
                    return tool
                jumeau = jumeau or tool
        return jumeau

    def jumeau(self, tool_id: str) -> Optional[str]:
        """L'identifiant du jumeau « avances DATRON » de cet outil."""
        for tid, tool in self.tools.items():
            if tool.jumeau_de == tool_id and tid != tool_id:
                return tid
        return None

    def _placer_apres(self, tool_id: str, nouveau_id: str, outil: Tool):
        """Range `outil` juste après `tool_id` (le jumeau suit l'outil
        qu'il double, dans le tableau comme dans les listes)."""
        ordre = [k for k in self.tools if k != nouveau_id]
        rang = ordre.index(tool_id) + 1 if tool_id in ordre else len(ordre)
        ordre.insert(rang, nouveau_id)
        anciens = dict(self.tools)
        anciens[nouveau_id] = outil
        # le MÊME dictionnaire, réordonné: qui en tient une référence
        # (un panneau, un appelant) voit le jumeau
        self.tools.clear()
        self.tools.update((k, anciens[k]) for k in ordre)

    def importer_constructeur(self, tool_id: str, catalogue,
                              broche: str = None, guide=None) -> dict:
        """Le bouton « DATRON » d'un outil: ses données constructeur.

        - la fiche @ ToolDescription @ prend ce que le catalogue sait
          et qu'elle ignore — jamais par-dessus ce qui est rempli: les
          ÉCARTS sont rendus, l'utilisateur tranche;
        - le bloc `constructeur` (cotes, famille, prix, avances
          recommandées) s'y range; les avances de l'outil ne bougent
          pas;
        - quand DATRON recommande des avances (fraises 1 dent), un
          JUMEAU les porte: même article, même fiche, avances
          constructeur — chaque opération choisit l'un ou l'autre.
          (Si la fiche porte déjà les avances DATRON, sans jumeau,
          elle est mise à jour elle-même.)

        Rend {ok, outil, ref, completes, ecarts, coupe, jumeau,
        jumeau_cree, en_place} ou {ok: False, raison}."""
        from src.core.catalogue_datron import geometrie
        from src.core.coupe_datron import BROCHE_DEFAUT
        broche = broche or BROCHE_DEFAUT
        if tool_id not in self.tools:
            return {'ok': False, 'raison': "outil introuvable"}
        tool = self.tools[tool_id]
        # le bouton du jumeau agit sur l'outil qu'il double
        base_id = (tool.jumeau_de if tool.jumeau_de in self.tools
                   and tool.jumeau_de != tool_id else tool_id)
        base = self.tools[base_id]
        x = catalogue.entree(base.article_nr)
        if x is None:
            return {'ok': False,
                    'raison': (f"référence {base.article_nr or '—'} "
                               "absente du catalogue DATRON")}
        etait_constructeur = base.avances_constructeur
        fiche = catalogue.fiche_constructeur(x, broche, guide)
        completes, ecarts = [], []
        for cle, valeur in geometrie(x).items():
            actuel = base.geometry.get(cle)
            if actuel in (None, ""):
                base.geometry[cle] = valeur
                completes.append(cle)
                continue
            try:
                different = abs(float(actuel) - float(valeur)) > 1e-6
            except (TypeError, ValueError):
                different = str(actuel) != str(valeur)
            if different:
                ecarts.append((cle, actuel, valeur))
        if not base.diameter and base.geometry.get('Diameter'):
            try:
                base.diameter = float(base.geometry['Diameter'])
            except (TypeError, ValueError):
                pass
        base.constructeur = fiche
        rapport = {'ok': True, 'outil': base_id, 'ref': x.get('ref'),
                   'completes': completes, 'ecarts': ecarts,
                   'coupe': fiche.get('coupe'), 'jumeau': None,
                   'jumeau_cree': False, 'en_place': False}
        coupe = fiche.get('coupe')
        jid = self.jumeau(base_id)
        if coupe and etait_constructeur and jid is None:
            # la fiche porte déjà les avances DATRON: la doubler
            # ferait deux fois la même — on la met à jour
            for cle in Tool.CHAMPS_AVANCES:
                setattr(base, cle, coupe[cle])
            rapport['en_place'] = True
        elif coupe:
            cree = jid is None
            if cree:
                jid = f"{base_id}_datron"
                i = 2
                while jid in self.tools:
                    jid = f"{base_id}_datron{i}"
                    i += 1
            donnees = base.to_dict()
            for cle in Tool.CHAMPS_AVANCES:
                donnees[cle] = coupe[cle]
            donnees['jumeau_de'] = base_id
            donnees['notes'] = (f"Avances DATRON ({coupe['libelle_source']}"
                                f", broche {broche}) — jumeau de "
                                f"{base.name}")
            if cree:
                donnees['usage_count'] = 0
                donnees['last_used'] = None
            else:
                ancien = self.tools[jid]
                donnees['usage_count'] = ancien.usage_count
                donnees['last_used'] = ancien.last_used
            self._placer_apres(base_id, jid, Tool(donnees))
            rapport['jumeau'] = jid
            rapport['jumeau_cree'] = cree
        self.save()
        return rapport

    def ajouter_depuis_catalogue(self, x: dict, catalogue,
                                 broche: str = None, guide=None) -> str:
        """Un outil du catalogue entre dans la bibliothèque (avec les
        avances DATRON s'il y en a); rend son identifiant."""
        from src.core.coupe_datron import BROCHE_DEFAUT
        donnees = catalogue.donnees_outil(x, broche or BROCHE_DEFAUT,
                                          guide)
        tid = _slug_tool_id(donnees['name'], donnees['reference'])
        base, i = tid, 2
        while tid in self.tools:
            tid = f"{base}_{i}"
            i += 1
        self.tools[tid] = Tool(donnees)
        self.save()
        return tid

    def import_geometry_from_simpl(self, filepath: str) -> dict:
        """Enrichit la bibliothèque avec les @ ToolDescription @ d'un
        SimPl Datron: géométrie complète (Ø, longueur de coupe, rayon
        de bec, nombre de dents, angle de pointe, pas de filet...).

        Les outils existants sont mis à jour par ARTICLE (les avances
        et RPM réglés dans NeoDrive ne sont JAMAIS écrasés); les
        outils inconnus sont ajoutés. Retourne un compte-rendu
        {'updated': [...], 'added': [...]}."""
        from src.io.simpl_analyzer import parse_tool_descriptions
        with open(filepath, 'r', encoding='utf-8-sig',
                  errors='replace') as f:
            descs = parse_tool_descriptions(f.read())
        report = {'updated': [], 'added': []}
        for name, info in descs.items():
            article = (info.get('article') or '').strip()
            geometry = info.get('geometry') or {}
            if not article or not geometry:
                continue
            memes = [t for t in self.tools.values()
                     if t.article_nr == article]
            if memes:
                for tool in memes:
                    tool.geometry.update(geometry)
                    if info.get('vendor'):
                        tool.vendor = info['vendor']
                    diam = geometry.get('Diameter')
                    if diam and not tool.diameter:
                        tool.diameter = float(diam)
                tool = self.get_tool_by_article(article)
                report['updated'].append(f"{tool.name} [{article}]")
                continue
            tool_id = _slug_tool_id(name, article)
            while tool_id in self.tools:
                tool_id += "_2"
            self.tools[tool_id] = Tool({
                'name': name,
                'reference': article,
                'vendor': info.get('vendor', 'DATRON'),
                'diameter': float(geometry.get('Diameter', 0) or 0),
                'notes': "Importé depuis " + os.path.basename(filepath),
                'geometry': geometry,
            })
            report['added'].append(f"{name} [{article}]")
        if report['updated'] or report['added']:
            self.save()
        return report

    def get_all_tools(self) -> List[Tool]:
        return list(self.tools.values())

    # ── les couleurs ──

    def id_de_cle(self, cle: str) -> str:
        """L'outil d'une clé de couleur (id, référence ou nom; la fiche
        plutôt que son jumeau), ou ""."""
        cle = str(cle or "")
        if not cle:
            return ""
        if cle in self.tools:
            return cle
        trouve = ""
        for tid, tool in self.tools.items():
            if tool.article_nr == cle or tool.name == cle:
                if not tool.jumeau_de:
                    return tid
                trouve = trouve or tid
        return trouve

    def couleur_auto(self, tool_id: str) -> str:
        """La couleur que l'outil a sans réglage: son rang dans la
        bibliothèque (un jumeau prend celle de l'outil qu'il double)."""
        tool = self.tools.get(tool_id)
        if tool is not None and tool.jumeau_de in self.tools:
            tool_id = tool.jumeau_de
        ids = [t for t, o in self.tools.items() if not o.jumeau_de
               or o.jumeau_de not in self.tools]
        rang = ids.index(tool_id) if tool_id in ids else len(ids)
        return couleur_de_rang(rang)

    def couleur_outil(self, cle: str) -> Optional[str]:
        """La couleur d'un outil (la sienne, sinon l'automatique), ou
        None pour une clé que la bibliothèque ne connaît pas."""
        tid = self.id_de_cle(cle)
        if not tid:
            return None
        tool = self.tools[tid]
        if not tool.couleur and tool.jumeau_de in self.tools:
            base = self.tools[tool.jumeau_de]
            if base.couleur:
                return base.couleur
        return tool.couleur or self.couleur_auto(tid)

    def regler_couleur(self, tool_id: str, couleur: str) -> bool:
        """La couleur choisie (« #rrggbb »), ou "" pour l'automatique;
        enregistrée dans tools.json."""
        tool = self.tools.get(tool_id)
        if tool is None:
            return False
        tool.couleur = couleur_valide(couleur)
        self.save()
        return True

    def get_tool_ids(self) -> List[str]:
        return list(self.tools.keys())

    def get_tools_for_operation(self, tool_types: List[str]) -> Dict[str, Tool]:
        """Retourne les outils compatibles avec un type d'opération.
        tool_types: liste de type_taraudage acceptés (ex: ['Cyl2','Cyl3','Cyl6'])
        Si tool_types est vide, retourne tous les outils.
        """
        if not tool_types:
            return dict(self.tools)
        result = {}
        for tid, tool in self.tools.items():
            if tool.type_taraudage in tool_types:
                result[tid] = tool
        return result

    def add_tool(self, tool_id: str, tool_data: dict):
        self.tools[tool_id] = Tool(tool_data)
        self.save()

    def update_tool(self, tool_id: str, tool_data: dict):
        if tool_id in self.tools:
            self.tools[tool_id] = Tool(tool_data)
            self.save()

    def delete_tool(self, tool_id: str):
        if tool_id in self.tools:
            del self.tools[tool_id]
            self.save()

    def search_tools(self, query: str = '', material: str = '',
                     type_taraudage: str = '') -> Dict[str, Tool]:
        """Recherche par nom/référence et type de filet.

        `material` n'est plus filtré: la matière est un réglage du
        PROGRAMME (multiplicateurs de régime et d'avance), pas une
        propriété de l'outil — la liste par outil vieillissait sans
        que personne ne la tienne à jour."""
        results = {}
        query_lower = query.lower()
        for tid, tool in self.tools.items():
            if query and query_lower not in tool.name.lower() \
                    and query_lower not in tool.reference.lower():
                continue
            if type_taraudage and tool.type_taraudage != type_taraudage:
                continue
            results[tid] = tool
        return results
