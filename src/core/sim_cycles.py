"""Simulation d'un programme SimPL entier, cycles Datron compris.

`sim3d.parcours_3d` lit les mouvements d'UNE séquence $$$ (Line, Arc,
Rapid). Un programme généré, lui, est fait de CYCLES: « Drill depth=5
infeedZ=1 », « RectangleCavity (widthX=20 …) » — la machine en déroule
le parcours. Ici on les déroule aussi, pour les voir en volume:

- Main est exécuté ligne à ligne; un nom de sous-programme l'appelle,
  un nom de séquence $$$ en joue les mouvements, les
  Pattern::Rectangle/Circle/LinearPattern répètent leur `callProgram`;
- le repère suit ShiftWcsInc / RotateWcsInc / RotateWcsAbs;
- l'outil (« Tool type="…" », ou « Tool name="…" ») donne le rayon:
  les contours, poches et hélices sont tracés là où passe le CENTRE de
  l'outil;
- comme dans les programmes de l'atelier, une commande peut courir sur
  plusieurs lignes (parenthèses, chaînes, commentaires dedans); un
  « if … else … endif » joue sa branche « oui » (la simulation ne
  pose pas la question de l'opérateur);
- Engrave::StandardTextEngrave grave le texte en APPROCHE: une police
  à trait simple (police_fil — la police Datron n'est pas disponible),
  à la hauteur, chasse, rotation, inclinaison, alignement et
  profondeur donnés.

Chaque cycle suit la stratégie que décrit le manuel SimPL 3.1.1
(chapitre 5.2, « Process cycles »):

- l'outil descend en rapide jusqu'à `strokeCuttingZ`, travaille, et
  revient À SON POINT DE DÉPART en fin de cycle (« In all machining
  cycles the tool tip returns to the start position »);
- l'ébauche laisse `finishingXY` aux parois et `finishingZ` au fond,
  par passes de `infeedZ`; la finition reprend le fond, puis les
  parois par passes de `infeedFinishingZ`;
- la poche ronde (CircleCavity) s'élargit en SPIRALE depuis le centre
  (« le diamètre augmente à chaque tour de la prise diagonale »), la
  poche rectangulaire par anneaux du centre vers les parois; l'entrée
  dans la matière se fait en hélice ou en rampe;
- les contours (CircleFromMid, RectFromMid) attaquent de biais quand
  `diagonalInfeed` (par défaut): la profondeur est prise à distance du
  bord, puis le bord est rejoint;
- la prise latérale est `distanceStepover` si elle est donnée, sinon
  `percentageStepover` du diamètre (50 % par défaut);
- le filetage (Thread, SpecialThread) monte ou plonge selon le côté,
  le sens du filet et `technology` (en opposition, un filet intérieur
  à droite PLONGE; en avalant il MONTE);
- le surfaçage rectangulaire va et vient (BothWays) ou repart toujours
  du même côté (relevé entre les passes), à l'angle donné.

C'est un aperçu fidèle à la géométrie (rayons, passes, recouvrement,
ordre ébauche/finition), pas une copie bit à bit du contrôleur.

Le résultat a la forme de `sim3d.parcours_3d` ('x','y','z','k'), plus
'outil' (la référence de l'outil, par sommet), 'cycles' (combien de
chaque), 'outils' (référence → diamètre), 'formes' (référence →
forme d'outil, pour l'enlèvement de matière) et 'brut' (le brut que
déclare l'en-tête du programme, ou None).
"""

import math
import os
import re
from collections import Counter
from typing import Dict, List, Optional

from src.core.affichage import FIN_OPS, MARQUE_OP
from src.core.sim3d import DEPART, COUPE, AIR, RAPIDE, _points_arc
from src.core.chemins_machine import chemin_local

#: pas des filets métriques (mm)
PAS_FILET = {"M1": 0.25, "M1.2": 0.25, "M1.4": 0.3, "M1.6": 0.35,
             "M2": 0.4, "M2.5": 0.45, "M3": 0.5, "M3.5": 0.6, "M4": 0.7,
             "M5": 0.8, "M6": 1.0, "M8": 1.25, "M10": 1.5, "M12": 1.75,
             "M14": 2.0, "M16": 2.0}

#: les cycles que la simulation sait dérouler
CYCLES = ("Drill", "DrillMilling", "Thread", "SpecialThread",
          "ThreadCutting", "HelixWithFullCircle", "Helix", "CircleFromMid", "RectFromMid",
          "CircleCavity", "RectangleCavity", "RectangleFace", "CircleFace",
          "Engrave::StandardTextEngrave")
#: les cycles dont le nom n'est pas un nom de méthode
_METHODES = {"Engrave::StandardTextEngrave": "_c_Texte"}
#: au-delà, une commande « ouverte » n'est plus recollée (fichier abîmé)
_LIGNES_MAX_COMMANDE = 200

#: diamètre d'outil supposé quand la référence est inconnue
DIAMETRE_INCONNU = 2.0
#: au-delà, la simulation s'arrête (l'aperçu reste fluide)
MAX_SOMMETS = 400000
#: points par tour d'hélice ou de cercle
_N_TOUR = 48
#: écart maxi d'une corde à l'arc (mm): les petits cercles (un filet,
#: une hélice d'avant-trou) n'ont pas besoin de 48 segments par tour —
#: 48 filetages ébavurés en faisaient 88 000 à passer dans la matière
_FLECHE = 0.01


def _n_tour(r: float) -> int:
    """Segments par tour pour un rayon: la flèche reste sous _FLECHE
    (12 au moins, _N_TOUR au plus)."""
    r = abs(float(r))
    if r <= _FLECHE:
        return 12
    demi = math.acos(max(-1.0, 1.0 - _FLECHE / r))
    return int(max(12, min(_N_TOUR, math.ceil(math.pi / max(demi, 1e-9)))))
#: profondeur d'appels (un programme qui s'appelle lui-même)
_PROFONDEUR_MAX = 24
#: au plus ce nombre de passes pour une profondeur, et d'éléments pour un
#: motif: au-delà c'est une faute de frappe (« infeedZ=0.0000001 »,
#: « xCount=100000 yCount=100000 »), qui faisait bâtir des listes de
#: centaines de millions d'éléments avant le premier sommet — la
#: simulation figée, la mémoire pleine, Annuler sans effet
PASSES_MAX = 1_000_000
ELEMENTS_MAX = 1_000_000
#: remontée au-dessus du fond déjà percé, entre deux débourrages
_REPRISE_PERCAGE = 0.2

_NOMBRE = r'[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?'
_PARAM_RE = re.compile(r'\b([A-Za-z_]\w*)\s*=\s*("[^"]*"|' + _NOMBRE
                       + r'|[A-Za-z_][\w:.]*)')
_MOT_RE = re.compile(r'^([A-Za-z_][\w:]*)')
_PROG_RE = re.compile(r'^(?:export\s+)?program\s+([A-Za-z_]\w*)')
_APPEL_RE = re.compile(r'^[A-Za-z_]\w*$')
#: un appel avec paramètres: « Nom clé=valeur… » ou « Nom (a, b) »
_APPEL_PARAMS_RE = re.compile(r'^([A-Za-z_]\w*)\s*(?:\(|\s+\w+\s*=)')
#: les variables du programme. « inputs:InputParameter[] = { » ouvre la
#: saisie des Paramètres opérateur, chaque champ y donne son « default =
#: 5 »; « profondeur = inputs[0].NumberValue » (ou « x = 12.5 ») affecte
_SAISIE_RE = re.compile(
    r'^([A-Za-z_]\w*)\s*:\s*InputParameter\s*\[\s*\]\s*=\s*\{(.*)$')
_DEFAUT_RE = re.compile(r'\bdefault\s*=\s*(' + _NOMBRE + r')')
_AFFECTATION_RE = re.compile(
    r'^([A-Za-z_]\w*)\s*(?::\s*[A-Za-z_]\w*\s*)?=(?!=)\s*(.+)$')
_VALEUR_SAISIE_RE = re.compile(
    r'^([A-Za-z_]\w*)\s*\[\s*(\d+)\s*\]\s*\.\s*NumberValue$')
#: une valeur de paramètre qui est un nom seul (« depth=profondeur »)
_VARIABLE_RE = re.compile(r'(=\s*)([A-Za-z_]\w*)(?![\w.:\[("])')
#: les commandes qui remontent l'outil (dans un programme ou une séquence)
_REMONTEES = ('MoveToParkPosition', 'MoveToSafetyPosition')
#: les technologies d'avance du manuel (Feed, SetFeedTechnology)
_TECHNOLOGIES = ('finishing', 'approach', 'plunge', 'ramp', 'roughing')
_MOUVEMENT_RE = re.compile(r'^(SafeRapid|Rapid|PrePositioning|Line|'
                           r'Arc\s+(CW|CCW))\b(.*)$')
#: la forme de presque tous les mouvements d'une séquence, lue d'un coup:
#: « Line X=… Y=… », « Arc CW X=… Y=… dX=… dY=… », « Rapid Z=… »
_MOUVEMENT_SIMPLE_RE = re.compile(
    r'^(Rapid|PrePositioning|Line|Arc (CW|CCW))'
    r'(?: X=(' + _NOMBRE + r'))?(?: Y=(' + _NOMBRE + r'))?'
    r'(?: Z=(' + _NOMBRE + r'))?(?: dX=(' + _NOMBRE + r'))?'
    r'(?: dY=(' + _NOMBRE + r'))?$')
_MOTS_SEULS_RE = re.compile(r'\b[A-Za-z_]\w*\b')
#: l'arc du manuel (« Arc X=… radius=… »), pas celui des séquences
#: (« Arc CW … »)
_ARC_MANUEL_RE = re.compile(r'^Arc\b(?!\s+(?:CW|CCW)\b)')
#: « usermodule UM_x="C:\\chemin\\programme.SimPl" » (appel externe)
_USERMODULE_RE = re.compile(
    r'^\s*usermodule\s+([A-Za-z_]\w*)\s*=\s*"([^"]+)"', re.MULTILINE)
_FILET_RE = re.compile(r'M\s*(\d+(?:[.,]\d+)?)', re.IGNORECASE)
_BRUT_RE = re.compile(
    r'WorkpieceGeometry\s*:\s*"MinEdge"\s*:\s*\{([^}]*)\}\s*,\s*'
    r'"MaxEdge"\s*:\s*\{([^}]*)\}')
_AXE_RE = re.compile(r'"([XYZ])"\s*:\s*(' + _NOMBRE + ')')


class _Arret(Exception):
    """Plafond de sommets atteint."""


def _sans_commentaire(ligne: str) -> str:
    """La ligne sans son commentaire « # … » (hors guillemets)."""
    if '#' not in ligne:
        return ligne            # le cas courant, sans boucle Python
    dans = False
    for i, c in enumerate(ligne):
        if c == '"':
            dans = not dans
        elif c == '#' and not dans:
            return ligne[:i]
    return ligne


def _ouverte(texte: str) -> bool:
    """Une parenthèse ou une chaîne reste-t-elle ouverte?"""
    return texte.count('"') % 2 == 1 or texte.count('(') > texte.count(')')


def recoller(lignes):
    """Les commandes sur plusieurs lignes, en une ligne chacune (sans
    les commentaires)."""
    sortie = []
    attente = None
    n = 0
    for brute in lignes:
        s = brute.strip()
        if attente is None:
            if s.startswith('$$$'):
                sortie.append(s)
                continue
            propre = _sans_commentaire(s).strip()
            if _ouverte(propre):
                attente, n = propre, 1
            else:
                sortie.append(s)
            continue
        # dans une chaîne ouverte, le « # » est du texte
        morceau = s if attente.count('"') % 2 == 1 else \
            _sans_commentaire(s).strip()
        attente = attente + ' ' + morceau
        n += 1
        if not _ouverte(attente) or n >= _LIGNES_MAX_COMMANDE:
            sortie.append(attente)
            attente = None
    if attente is not None:
        sortie.append(attente)
    return sortie


def decouper(code: str):
    """({programme: [lignes]}, {séquence: [lignes]}) d'un module."""
    programmes: Dict[str, List[str]] = {}
    sequences: Dict[str, List[str]] = {}
    courant = None
    seq = None
    lignes = (code or "").split('\n')
    # les séquences $$$ (gros fichiers) ne sont pas recollées
    debut_seq = next((i for i, l in enumerate(lignes)
                      if l.lstrip().startswith('$$$')), len(lignes))
    lignes = recoller(lignes[:debut_seq]) + lignes[debut_seq:]
    for brute in lignes:
        s = brute.strip()
        if s.startswith('$$$'):
            seq = s[3:].strip()
            sequences.setdefault(seq, [])
            courant = None
            continue
        if seq is not None:
            sequences[seq].append(s)
            continue
        m = _PROG_RE.match(s)
        if m:
            courant = m.group(1)
            programmes[courant] = []
            continue
        if s.startswith('endprogram'):
            courant = None
            continue
        if courant is not None:
            programmes[courant].append(s)
    return programmes, sequences


def brut_du_code(code: str):
    """Le brut que l'en-tête déclare (« @ WorkpieceGeometry … @ »):
    (xmin, xmax, ymin, ymax, zmin, zmax), ou None."""
    m = _BRUT_RE.search(code or "")
    if not m:
        return None
    mini = {a: float(v) for a, v in _AXE_RE.findall(m.group(1))}
    maxi = {a: float(v) for a, v in _AXE_RE.findall(m.group(2))}
    if set(mini) != {'X', 'Y', 'Z'} or set(maxi) != {'X', 'Y', 'Z'}:
        return None
    b = (mini['X'], maxi['X'], mini['Y'], maxi['Y'], mini['Z'], maxi['Z'])
    if b[1] <= b[0] or b[3] <= b[2] or b[5] <= b[4]:
        return None
    return b


def code_utile(code: str) -> str:
    """Le code qui décide du parcours: sans l'en-tête (horodatage, brut
    déclaré, commentaire) ni le bloc NDMETA — ils changent sans qu'un seul
    mouvement change (le brut déclaré se relit à part: `brut_du_code`)."""
    code = code or ""
    code = code[max(code.find('\nusing '), 0):]
    # (les séquences $$$ viennent APRÈS ce bloc: on l'enlève, sans couper)
    debut = fin = code.find('# NDMETA:')
    if debut < 0:
        return code
    while code.startswith('# NDMETA:', fin):
        fin = code.find('\n', fin) + 1 or len(code)
    return code[:debut] + code[fin:]


#: (texte, son empreinte, les programmes externes qu'il appelle)
_cle_lue = (None, 0, [])


def cle_de_simulation(code: str) -> tuple:
    """Ce qui fait qu'un code donne le même parcours: son code utile et
    la date des programmes externes qu'il appelle."""
    global _cle_lue
    # le même texte: rien à relire (23 Mo: 0,2 s), seules les dates comptent
    if _cle_lue[0] is not code:
        chemins = [chemin_local(m.group(2).replace('\\\\', '\\'))
                   for m in _USERMODULE_RE.finditer(code or "")]
        _cle_lue = (code, hash(code_utile(code)), chemins)
    dates = []
    for chemin in _cle_lue[2]:
        try:
            dates.append((chemin, os.path.getmtime(chemin)))
        except OSError:
            dates.append((chemin, 0.0))
    return (_cle_lue[1], tuple(dates))


def params_de(texte: str) -> Dict[str, object]:
    """Les « clé=valeur » d'une commande (nombres en float), et ses
    mots seuls (Inside, CW, BothWays…) à True."""
    p: Dict[str, object] = {}
    for cle, val in _PARAM_RE.findall(texte):
        if val.startswith('"'):
            p[cle] = val.strip('"')
        else:
            try:
                p[cle] = float(val)
            except ValueError:
                p[cle] = val
    reste = _PARAM_RE.sub(' ', texte) if p else texte
    for mot in _MOTS_SEULS_RE.findall(reste):
        p.setdefault(mot, True)
    return p


def _coordonnees(texte: str) -> Dict[str, object]:
    """Les « clé=valeur » d'un MOUVEMENT, comme `params_de` mais sans
    chercher les mots seuls, dont un mouvement n'a que faire: deux
    passes de regex de moins par ligne, sur des centaines de milliers
    de lignes de séquence."""
    p: Dict[str, object] = {}
    for cle, val in _PARAM_RE.findall(texte):
        try:
            p[cle] = float(val)
        except ValueError:
            p[cle] = val.strip('"') if val.startswith('"') else val
    return p


def _mot(p, mot: str) -> bool:
    """Le drapeau est-il donné — seul (« Inside ») ou en valeur
    d'énumération (« mode=ContourMode.Inside »)?"""
    if p.get(mot) is True:
        return True
    for v in p.values():
        if isinstance(v, str) and (v == mot or v.endswith('.' + mot)):
            return True
    return False


def _f(p, cle, defaut=0.0) -> float:
    try:
        return float(p.get(cle, defaut))
    except (TypeError, ValueError):
        return float(defaut)


def niveaux(profondeur: float, passe: float) -> List[float]:
    """Les Z des passes successives, jusqu'au fond (négatifs)."""
    profondeur = abs(profondeur)
    if profondeur <= 0:
        return [0.0]
    if passe <= 0 or passe >= profondeur:
        return [-profondeur]
    n = profondeur / passe - 1e-9
    if not n < PASSES_MAX:
        # (démesuré: les premières passes, puis le fond — la simulation
        # s'arrête de toute façon à son plafond de sommets)
        return [-i * passe for i in range(1, PASSES_MAX)] + [-profondeur]
    n = int(math.ceil(n))
    return [-min(profondeur, i * passe) for i in range(1, n + 1)]


def _cercle(cx, cy, r, z, a0=0.0, sens=1, n=None):
    """Un tour complet, départ inclus, retour au départ."""
    n = _n_tour(r) if n is None else n
    return [(cx + r * math.cos(a0 + sens * 2 * math.pi * i / n),
             cy + r * math.sin(a0 + sens * 2 * math.pi * i / n), z)
            for i in range(n + 1)]


def _helice(cx, cy, r, z0, z1, pas, sens=1, a0=0.0):
    """De z0 à z1, un tour par `pas` (départ exclu)."""
    tours = abs(z1 - z0) / pas if pas > 0 else 1.0
    tours = max(tours, 1e-6)
    n = max(8, int(math.ceil(tours * _n_tour(r))))
    n = min(n, 4000)
    return [(cx + r * math.cos(a0 + sens * 2 * math.pi * tours * i / n),
             cy + r * math.sin(a0 + sens * 2 * math.pi * tours * i / n),
             z0 + (z1 - z0) * i / n) for i in range(1, n + 1)]


def _spirale(cx, cy, r0, r1, pas, z, sens=1):
    """Une spirale d'Archimède de r0 à r1, `pas` de plus par tour
    (départ exclu, à angle 0)."""
    if r1 <= r0 + 1e-9:
        return []
    tours = (r1 - r0) / max(pas, 1e-6)
    n = max(8, int(math.ceil(tours * _n_tour(r1))))
    n = min(n, 20000)
    sortie = []
    for i in range(1, n + 1):
        t = i / n
        a = sens * 2 * math.pi * tours * t
        r = r0 + (r1 - r0) * t
        sortie.append((cx + r * math.cos(a), cy + r * math.sin(a), z))
    return sortie


def _spirale_vers_centre(cx, cy, r, pas, z, sens=1):
    """Du bord (angle 0, départ exclu) au centre, `pas` de moins par
    tour."""
    if r <= 1e-9:
        return []
    tours = r / max(pas, 1e-6)
    n = max(8, min(20000, int(math.ceil(tours * _n_tour(r)))))
    sortie = []
    for i in range(1, n + 1):
        t = i / n
        a = sens * 2 * math.pi * tours * t
        rr = r * (1.0 - t)
        sortie.append((cx + rr * math.cos(a), cy + rr * math.sin(a), z))
    return sortie


def rectangle_arrondi(cx, cy, w, h, r, n_coin=8):
    """Le contour d'un rectangle centré à coins arrondis, fermé, en
    commençant au milieu du côté droit."""
    w, h = max(w, 0.0), max(h, 0.0)
    r = max(0.0, min(r, w / 2.0, h / 2.0))
    if r <= 1e-9:
        coins = [(cx + w / 2, cy), (cx + w / 2, cy + h / 2),
                 (cx - w / 2, cy + h / 2), (cx - w / 2, cy - h / 2),
                 (cx + w / 2, cy - h / 2), (cx + w / 2, cy)]
        return coins
    pts = [(cx + w / 2, cy)]
    for ccx, ccy, a0 in ((cx + w / 2 - r, cy + h / 2 - r, 0),
                         (cx - w / 2 + r, cy + h / 2 - r, 90),
                         (cx - w / 2 + r, cy - h / 2 + r, 180),
                         (cx + w / 2 - r, cy - h / 2 + r, 270)):
        for i in range(n_coin + 1):
            a = math.radians(a0 + 90.0 * i / n_coin)
            pts.append((ccx + r * math.cos(a), ccy + r * math.sin(a)))
    pts.append((cx + w / 2, cy))
    return pts


class Simulation:
    """L'interprète: un état machine, des sommets en coordonnées
    machine (le repère d'origine du programme)."""

    def __init__(self, code: str, diametres: Optional[dict] = None,
                 progression=None, max_sommets: int = MAX_SOMMETS,
                 formes: Optional[dict] = None):
        self.programmes, self.sequences = decouper(code)
        #: les programmes externes appelés (usermodule): {label: chemin}
        #: — le fichier du poste derrière un chemin écrit pour la machine
        self.modules = {m.group(1): chemin_local(
            m.group(2).replace('\\\\', '\\'))
            for m in _USERMODULE_RE.finditer(code or "")}
        self.brut = brut_du_code(code)
        self.diametres = dict(diametres or {})
        self.formes = dict(formes or {})
        self.progression = progression
        self.max_sommets = max_sommets
        #: [(premier sommet, id de l'opération)]: à qui sont les sommets
        self.plages_ops: List[tuple] = []
        self.x: List[float] = []
        self.y: List[float] = []
        self.z: List[float] = []
        self.k: List[int] = []
        self.o: List[str] = []
        #: l'avance (mm/min) que le PROGRAMME a fixée au moment de chaque
        #: sommet (SetFeedTechnology puis Feed Finishing/Plunge…); 0:
        #: celle de l'outil, que la machine prend dans sa table
        self.f: List[float] = []
        self.technologies: Dict[str, float] = {}
        self.technologie = ""
        self.avance = 0.0
        self.cycles = Counter()
        self.tronque = False
        # repère: origine (machine) et angle (degrés)
        self.ox = self.oy = self.oz = 0.0
        self.angle = 0.0
        # ... et son miroir (MirrorWcs): −1 sur un axe reflété. Machine =
        # origine + rotation(angle) · miroir · local
        self.mx = self.my = 1.0
        self._trig = (0.0, 1.0, 0.0)        # (angle, cos, sin)
        # position courante, en machine (None: pas encore connue)
        self.pos = None
        self.article = ""
        self.rayon = DIAMETRE_INCONNU / 2.0
        #: les variables numériques du programme ({nom: valeur}), les
        #: champs des saisies ({tableau: [défauts]}) et la saisie ouverte
        self.variables: Dict[str, float] = {}
        self._saisies: Dict[str, list] = {}
        self._saisie = None
        self._lignes_lues = 0
        self._lignes_total = max(1, sum(len(v) for v in
                                        self.programmes.values())
                                 + sum(len(v) for v in
                                       self.sequences.values()))

    # ── repère ──

    def _cos_sin(self):
        """cos et sin de l'angle du repère, recalculés quand il change
        (pas à chacun des centaines de milliers de points)."""
        t = self._trig
        if t[0] != self.angle:
            a = math.radians(self.angle)
            t = self._trig = (self.angle, math.cos(a), math.sin(a))
        return t[1], t[2]

    def _machine(self, x, y, z):
        c, s = self._cos_sin()
        x, y = self.mx * x, self.my * y
        return (self.ox + c * x - s * y, self.oy + s * x + c * y,
                self.oz + z)

    def _local(self, X, Y, Z):
        c, s = self._cos_sin()
        dx, dy = X - self.ox, Y - self.oy
        return (self.mx * (c * dx + s * dy), self.my * (-s * dx + c * dy),
                Z - self.oz)

    def _deplacement(self, dx, dy):
        """Un déplacement (dx, dy) du repère courant, en machine."""
        c, s = self._cos_sin()
        dx, dy = self.mx * dx, self.my * dy
        return c * dx - s * dy, s * dx + c * dy

    def local_courant(self):
        if self.pos is None:
            return None
        return self._local(*self.pos)

    # ── sommets ──

    def _poser(self, X, Y, Z, genre):
        if len(self.x) >= self.max_sommets:
            self.tronque = True
            raise _Arret()
        self.x.append(X)
        self.y.append(Y)
        self.z.append(Z)
        self.k.append(genre)
        self.o.append(self.article)
        self.f.append(self.avance)

    def aller(self, x, y, z, rapide=False):
        """Un mouvement droit vers (x, y, z) LOCAUX."""
        X, Y, Z = self._machine(x, y, z)
        if self.pos is None:
            self.pos = (X, Y, Z)
            if not self.x:
                self._poser(X, Y, Z, DEPART)
            return
        if rapide:
            genre = RAPIDE
        else:
            z0 = self.pos[2] - self.oz
            genre = COUPE if (z0 <= 1e-9 or z <= 1e-9) else AIR
        self._poser(X, Y, Z, genre)
        self.pos = (X, Y, Z)

    def chemin(self, points, rapide=False):
        """Les sommets d'`aller` point par point — sans un appel par sommet:
        arcs et hélices en font des centaines de milliers."""
        if self.pos is None:
            for x, y, z in points:
                self.aller(x, y, z, rapide)
            return
        c, s = self._cos_sin()
        cx, sx, cy, sy = c * self.mx, s * self.mx, c * self.my, s * self.my
        ox, oy, oz = self.ox, self.oy, self.oz
        lx, ly, lz, lk, lo, lf = (self.x.append, self.y.append, self.z.append,
                                  self.k.append, self.o.append, self.f.append)
        article, avance = self.article, self.avance
        place = self.max_sommets - len(self.x)
        X, Y, Z = self.pos
        for x, y, z in points:
            if place <= 0:
                self.pos = (X, Y, Z)
                self.tronque = True
                raise _Arret()
            place -= 1
            if rapide:
                genre = RAPIDE
            elif Z - oz <= 1e-9 or z <= 1e-9:
                genre = COUPE
            else:
                genre = AIR
            X, Y, Z = ox + cx * x - sy * y, oy + sx * x + cy * y, oz + z
            lx(X)
            ly(Y)
            lz(Z)
            lk(genre)
            lo(article)
            lf(avance)
        self.pos = (X, Y, Z)

    def ici(self):
        return self.local_courant()

    # ── exécution ──

    def executer(self) -> None:
        #: par où le programme a commencé (un programme appelé ne
        #: reprend une simulation seule que si elle a commencé pareil)
        self._entree = None
        try:
            # « export program main » (exemples DATRON) vaut Main
            entree = 'Main' if 'Main' in self.programmes else next(
                (n for n in self.programmes if n.lower() == 'main'), None)
            if entree is not None:
                self._entree = 'Main'
                self._programme(entree, 0)
            elif self.sequences:
                self._entree = ('sequence_seule' if not self.programmes
                                else 'sequence')
                self._sequence(next(iter(self.sequences)))
        except _Arret:
            pass

    def _programme(self, nom, profondeur):
        if profondeur > _PROFONDEUR_MAX:
            return
        self._lignes(self.programmes.get(nom, []), profondeur)

    def _lignes(self, lignes, profondeur):
        from src.core import vcarve
        # if … else … endif: la branche « oui » seulement (une pile:
        # vrai = on joue)
        pile = []
        for brute in lignes:
            self._lignes_lues += 1
            if self.progression is not None \
                    and self._lignes_lues % 2000 == 0:
                vcarve.avancer(self.progression, min(
                    0.99, self._lignes_lues / self._lignes_total),
                    "simulation des cycles")
            s = _sans_commentaire(brute).strip()
            mot = s.split(' ', 1)[0].split('(', 1)[0]
            if mot == 'if':
                pile.append(all(pile))
                continue
            if mot in ('else', 'elseif', 'elif') and pile:
                pile[-1] = False
                continue
            if mot == 'endif':
                if pile:
                    pile.pop()
                continue
            if pile and not all(pile):
                continue
            if brute.startswith(MARQUE_OP):
                self._ouvrir_op(brute[len(MARQUE_OP):].strip())
                continue
            self._ligne(s, profondeur)

    def _ouvrir_op(self, op_id: str) -> None:
        """Les sommets suivants sont ceux de cette opération (repère du
        code marqué: `SimPlGenerator.code_marque`)."""
        op_id = None if op_id == FIN_OPS else op_id
        plages = self.plages_ops
        if plages and plages[-1][1] == op_id:
            return
        n = len(self.x)
        if plages and plages[-1][0] == n:
            plages[-1] = (n, op_id)     # l'opération d'avant n'a rien fait
        else:
            plages.append((n, op_id))

    def _module(self, chemin: str, profondeur: int) -> None:
        """Un programme externe appelé (usermodule): son Main, ses
        sous-programmes et ses séquences, dans l'état courant de la
        machine — la simulation montre ce que le fichier usine."""
        if profondeur > _PROFONDEUR_MAX:
            return
        if self._module_deja_simule(chemin):
            return
        code = lire_programme(chemin)
        if code is None:
            return
        progs, seqs = decouper(code)
        avant = (self.programmes, self.sequences)
        self.programmes, self.sequences = progs, seqs
        self._lignes_total += sum(len(v) for v in progs.values()) + sum(
            len(v) for v in seqs.values())
        self.cycles['Appel externe'] += 1
        try:
            if 'Main' in progs:
                self._programme('Main', profondeur)
            elif progs:
                self._programme(next(iter(progs)), profondeur)
            elif seqs:
                self._sequence(next(iter(seqs)))
        finally:
            self.programmes, self.sequences = avant

    def _etat(self) -> Dict:
        """L'état de la machine (repère, position, outil): ce qu'un
        programme appelé laisse à celui qui l'appelle."""
        return {'pos': self.pos, 'ox': self.ox, 'oy': self.oy,
                'oz': self.oz, 'angle': self.angle,
                'mx': self.mx, 'my': self.my,
                'article': self.article, 'rayon': self.rayon,
                'base_lcs': getattr(self, '_base_lcs', None),
                'val_lcs': dict(getattr(self, '_val_lcs', None) or {})}

    def _a_l_etat_initial(self) -> bool:
        return (not self.x and self.pos is None and not self.ox
                and not self.oy and not self.oz and not self.angle
                and self.mx == 1.0 and self.my == 1.0
                and getattr(self, '_base_lcs', None) is None
                and not self.article)

    def _module_deja_simule(self, chemin: str) -> bool:
        """Un programme appelé DÈS L'ÉTAT INITIAL (le cas d'un « Appel
        prog externe »), déjà simulé seul (le Canva l'a dessiné, en barre
        d'état): sa simulation en ligne rendrait exactement la même
        chose — on la reprend au lieu de la refaire (un programme 3D de
        30 Mo se simulait deux fois en 3D). Rend vrai si c'est fait."""
        if not self._a_l_etat_initial():
            return False
        cle = _cle_parcours(chemin, self.diametres, self.max_sommets)
        res = _PARCOURS_FICHIERS.get(cle) if cle is not None else None
        # seule, elle doit avoir commencé comme l'appel le ferait (Main,
        # ou sa séquence quand il n'a pas de programme), et sans appeler
        # elle-même d'autres fichiers (l'appel en ligne ne les suit pas)
        if res is None or 'etat_final' not in res                 or res.get('entree') not in ('Main', 'sequence_seule')                 or res.get('appelle_modules', True):
            return False
        self.cycles['Appel externe'] += 1
        self.x.extend(res['x'])
        self.y.extend(res['y'])
        self.z.extend(res['z'])
        self.k.extend(res['k'])
        self.o.extend(res['outil'])
        self.f.extend(res.get('avance') or [0.0] * len(res['x']))
        for cle_cycle, n in (res.get('cycles') or {}).items():
            self.cycles[cle_cycle] += n
        self.tronque = self.tronque or bool(res.get('tronque'))
        etat = res['etat_final']
        self.pos = etat['pos']
        self.ox, self.oy, self.oz = etat['ox'], etat['oy'], etat['oz']
        self.angle = etat['angle']
        self.mx, self.my = etat.get('mx', 1.0), etat.get('my', 1.0)
        self.article, self.rayon = etat['article'], etat['rayon']
        self._base_lcs = etat['base_lcs']
        if etat['val_lcs']:
            self._val_lcs = dict(etat['val_lcs'])
        if self.tronque:
            raise _Arret()
        return True

    def _sequence(self, nom):
        """Les mouvements d'une séquence $$$, dans le repère courant."""
        from src.core import vcarve
        for brute in self.sequences.get(nom, []):
            self._lignes_lues += 1
            if self.progression is not None \
                    and self._lignes_lues % 5000 == 0:
                vcarve.avancer(self.progression, min(
                    0.99, self._lignes_lues / self._lignes_total),
                    "simulation des séquences")
            s = _sans_commentaire(brute).strip()
            if s in _REMONTEES:
                self._remonter()
            elif s.startswith('Feed'):
                self._feed(s[4:])
            elif s:
                self._mouvement(s)

    def _remonter(self) -> None:
        """Le parking et la position de sécurité: l'outil remonte."""
        cur = self.ici()
        if cur is not None:
            self.aller(cur[0], cur[1], max(cur[2], 30.0), True)

    def _valeur(self, expr: str):
        """La valeur numérique d'une affectation, ou None: un champ de
        saisie (son défaut), un nombre, une autre variable, un calcul
        simple entre eux."""
        expr = expr.strip()
        m = _VALEUR_SAISIE_RE.match(expr)
        if m:
            champs = self._saisies.get(m.group(1)) or []
            rang = int(m.group(2))
            return champs[rang] if rang < len(champs) else None
        try:
            return float(expr)
        except ValueError:
            pass
        if expr in self.variables:
            return self.variables[expr]
        import ast
        try:
            arbre = ast.parse(expr, mode='eval').body
        except (SyntaxError, ValueError):
            return None

        def calcul(n):
            if isinstance(n, ast.Constant) and isinstance(
                    n.value, (int, float)) and not isinstance(n.value, bool):
                return float(n.value)
            if isinstance(n, ast.Name):
                return self.variables[n.id]
            if isinstance(n, ast.UnaryOp) and isinstance(
                    n.op, (ast.USub, ast.UAdd)):
                v = calcul(n.operand)
                return -v if isinstance(n.op, ast.USub) else v
            if isinstance(n, ast.BinOp) and isinstance(
                    n.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
                a, b = calcul(n.left), calcul(n.right)
                if isinstance(n.op, ast.Add):
                    return a + b
                if isinstance(n.op, ast.Sub):
                    return a - b
                if isinstance(n.op, ast.Mult):
                    return a * b
                return a / b
            raise ValueError(expr)
        try:
            v = calcul(arbre)
        except (KeyError, ValueError, ZeroDivisionError, RecursionError):
            return None
        return v if math.isfinite(v) else None

    def _variables_de(self, s: str):
        """Les variables du programme lues dans cette ligne: vrai si elle
        n'était que cela (saisie opérateur, affectation)."""
        if self._saisie is not None:
            # dans « inputs:InputParameter[] = { … } »: un champ par ligne
            nom, champs = self._saisie
            fin = '}' in s
            for morceau in s.split('}')[0].split(','):
                if morceau.strip():
                    m = _DEFAUT_RE.search(morceau)
                    champs.append(float(m.group(1)) if m else None)
            if fin:
                self._saisies[nom] = champs
                self._saisie = None
            return True
        m = _SAISIE_RE.match(s)
        if m:
            self._saisie = (m.group(1), [])
            if m.group(2).strip():
                self._variables_de(m.group(2))
            return True
        m = _AFFECTATION_RE.match(s)
        if m:
            v = self._valeur(m.group(2))
            if v is None:
                self.variables.pop(m.group(1), None)
            else:
                self.variables[m.group(1)] = v
            return True
        return False

    def _avec_variables(self, s: str) -> str:
        """La ligne, ses cotes liées à une variable remplacées par leur
        valeur (« Drill depth=profondeur »: liée à un Paramètre opérateur,
        la cote se simulait à 0 — ni matière enlevée, ni temps)."""
        variables = self.variables
        return _VARIABLE_RE.sub(
            lambda m: (m.group(1) + repr(variables[m.group(2)])
                       if m.group(2) in variables else m.group(0)), s)

    def _ligne(self, s, profondeur):
        if not s or s.startswith('@'):
            return
        if (self._saisie is not None or '=' in s) and self._variables_de(s):
            return
        if self.variables and '=' in s:
            s = self._avec_variables(s)
        if _APPEL_RE.match(s):
            if s in self.programmes:
                self._programme(s, profondeur + 1)
                return
            if s in self.modules:
                self._module(self.modules[s], profondeur + 1)
                return
            if s in self.sequences:
                self.cycles['Séquence'] += 1
                self._sequence(s)
                return
            if s in _REMONTEES:
                self._remonter()
                return
        # un appel AVEC paramètres: la FAO DATRON passe ainsi ses
        # avances à la séquence (« SEQUENCE_x Schneiden=Schneiden »),
        # qui n'était pas tracée
        m = _APPEL_PARAMS_RE.match(s)
        if m:
            nom = m.group(1)
            if nom in self.sequences:
                self.cycles['Séquence'] += 1
                self._sequence(nom)
                return
            if nom in self.programmes:
                self._programme(nom, profondeur + 1)
                return
        m = _MOT_RE.match(s)
        if not m:
            return
        mot = m.group(1)
        if mot.startswith('Pattern::'):
            self._pattern(mot[9:], params_de(s[m.end():]), profondeur)
            return
        if mot == 'Tool':
            p = params_de(s[m.end():])
            self.article = str(p.get('type', '') or p.get('name', '')
                               or '')
            d = self.diametres.get(self.article)
            try:
                d = float(d)
            except (TypeError, ValueError):
                d = DIAMETRE_INCONNU
            self.rayon = max(0.0, d / 2.0) if d > 0 else \
                DIAMETRE_INCONNU / 2.0
            # la machine prend les avances du nouvel outil dans sa table:
            # celles de tools.json, faute de mieux, jusqu'au prochain
            # SetFeedTechnology
            self.technologies = {}
            self.avance = 0.0
            return
        if mot == 'SetFeedTechnology':
            self._technologies(params_de(s[m.end():]))
            return
        if mot == 'Feed':
            self._feed(s[m.end():])
            return
        if mot in ('ShiftWcsInc', 'ShiftWcsAbs'):
            self._base_lcs = None
            p = params_de(s[m.end():])
            dx, dy, dz = _f(p, 'X'), _f(p, 'Y'), _f(p, 'Z')
            if mot == 'ShiftWcsAbs':
                # (manuel § 5.6.1.4) un axe non écrit garde sa valeur
                if 'X' in p:
                    self.ox = dx
                if 'Y' in p:
                    self.oy = dy
                if 'Z' in p:
                    self.oz = dz
            else:
                ex, ey = self._deplacement(dx, dy)
                self.ox += ex
                self.oy += ey
                self.oz += dz
            return
        if mot in ('RotateWcsInc', 'RotateWcsAbs'):
            p = params_de(s[m.end():])
            # sous le miroir d'UN axe, l'angle tourne dans l'autre sens
            g = _f(p, 'gamma') * self.mx * self.my
            self.angle = g if mot == 'RotateWcsAbs' else self.angle + g
            self._base_lcs = None
            return
        if mot == 'MirrorWcs':
            # (manuel § 5.6.1.2) le repère pièce reflété: l'opération
            # « Miroir » l'écrit, et la pièce se dessinait du mauvais côté
            # (matière et collisions comprises). Un axe non écrit garde
            # son état; mirrorZ n'est pas simulé.
            p = params_de(s[m.end():])
            for cle, axe in (('mirrorX', 'mx'), ('mirrorY', 'my')):
                if cle in p:
                    vrai = p[cle] is True or str(p[cle]).lower() == 'true'
                    setattr(self, axe, -1.0 if vrai else 1.0)
            self._base_lcs = None
            return
        if mot == 'ResetWcs':
            # (manuel § 5.6.1.3) le repère pièce revient à l'origine
            self.ox = self.oy = self.oz = 0.0
            self.angle = 0.0
            self.mx = self.my = 1.0
            self._base_lcs = None
            return
        if mot in ('ShiftLcsAbs', 'ShiftLcsInc', 'RotateLcsAbs',
                   'RotateLcsInc', 'ResetLcs'):
            self._lcs(mot, params_de(s[m.end():]))
            return
        if mot in CYCLES:
            self.cycles[mot] += 1
            p = params_de(s[m.end():])
            p['_texte'] = s[m.end():]
            self._cycle(mot, p)
            return
        self._mouvement(s)

    # ── avances programmées ──

    def _technologies(self, p) -> None:
        """« SetFeedTechnology finishing=5700 plunge=2500 ramp=5700 »:
        les avances de chaque technologie (une variable non résolue
        laisse celle de l'outil)."""
        for cle, val in p.items():
            nom = cle.lower()
            if nom in _TECHNOLOGIES and isinstance(val, float) and val > 0:
                self.technologies[nom] = val
        if self.technologie:
            self.avance = self.technologies.get(self.technologie, 0.0)

    def _feed(self, texte: str) -> None:
        """« Feed Plunge », « Feed technology=FeedTechnologies.Ramp »,
        « Feed value=1500 »: l'avance active."""
        p = params_de(texte)
        valeur = p.get('value')
        if isinstance(valeur, float) and valeur > 0:
            self.avance = valeur
            return
        nom = str(p.get('technology', '') or '').rsplit('.', 1)[-1].lower()
        if nom not in _TECHNOLOGIES:
            nom = next((cle.lower() for cle, v in p.items()
                        if v is True and cle.lower() in _TECHNOLOGIES), "")
        if nom:
            self.technologie = nom
            self.avance = self.technologies.get(nom, 0.0)

    def _mouvement(self, s):
        m = _MOUVEMENT_SIMPLE_RE.match(s)
        cur = self.ici() if m is not None else None
        if cur is None:
            self._mouvement_general(s)
            return
        commande, sens, vx, vy, vz, vdx, vdy = m.groups()
        bx, by, bz = cur
        x = float(vx) if vx else bx
        y = float(vy) if vy else by
        z = float(vz) if vz else bz
        if sens:
            self.chemin(_points_arc(bx, by, bz, x, y, z,
                                    bx + (float(vdx) if vdx else 0.0),
                                    by + (float(vdy) if vdy else 0.0),
                                    sens == 'CW', 0.02))
        elif commande == 'Line':
            self.aller(x, y, z)
        else:
            self.aller(x, y, z, True)

    def _mouvement_general(self, s):
        if s.startswith('Arc') and _ARC_MANUEL_RE.match(s):
            self._arc_du_manuel(s[3:])
            return
        m = _MOUVEMENT_RE.match(s)
        if not m:
            return
        commande, sens = m.group(1), m.group(2)
        p = _coordonnees(m.group(3))
        cur = self.ici()
        bx, by, bz = cur if cur is not None else (None, None, None)
        x = _f(p, 'X') if 'X' in p else bx
        y = _f(p, 'Y') if 'Y' in p else by
        z = _f(p, 'Z') if 'Z' in p else bz
        if None in (x, y, z):
            # position incomplète: Datron part du haut — on suppose
            # Z de sécurité, X/Y à l'origine
            x = 0.0 if x is None else x
            y = 0.0 if y is None else y
            z = 20.0 if z is None else z
            if cur is None:
                self.aller(x, y, z, True)
                return
        if commande == 'SafeRapid' and cur is not None:
            haut = max(z, bz, 0.0)
            self.aller(bx, by, haut, True)
            self.aller(x, y, haut, True)
            self.aller(x, y, z, True)
            return
        if commande in ('SafeRapid', 'Rapid', 'PrePositioning'):
            self.aller(x, y, z, True)
            return
        if sens and cur is not None:
            cx = bx + _f(p, 'dX')
            cy = by + _f(p, 'dY')
            self.chemin(_points_arc(bx, by, bz, x, y, z, cx, cy,
                                    sens == 'CW', 0.02))
            return
        self.aller(x, y, z)

    def _arc_du_manuel(self, texte: str) -> None:
        """« Arc (X=5 Y=5 Z=0 dX=3 dY=3 radius=6 CCW) » (§ 5.4.2): le
        centre décalé de dX/dY depuis la pointe de l'outil — à défaut,
        l'arc court de ce rayon jusqu'au point d'arrivée."""
        p = params_de(texte.strip().strip('()'))
        cur = self.ici()
        if cur is None:
            return
        bx, by, bz = cur
        x = _f(p, 'X') if 'X' in p else bx
        y = _f(p, 'Y') if 'Y' in p else by
        z = _f(p, 'Z') if 'Z' in p else bz
        horaire = _mot(p, 'CW')
        if 'dX' in p or 'dY' in p:
            cx, cy = bx + _f(p, 'dX'), by + _f(p, 'dY')
        else:
            r = abs(_f(p, 'radius'))
            corde = math.hypot(x - bx, y - by)
            if r <= 0 or corde < 1e-9 or corde > 2 * r + 1e-9:
                self.aller(x, y, z)
                return
            h = math.sqrt(max(0.0, r * r - corde * corde / 4.0))
            nx, ny = -(y - by) / corde, (x - bx) / corde
            signe = -1.0 if horaire else 1.0
            cx = (bx + x) / 2.0 + signe * h * nx
            cy = (by + y) / 2.0 + signe * h * ny
        self.chemin(_points_arc(bx, by, bz, x, y, z, cx, cy, horaire, 0.02))

    def _lcs(self, mot, p) -> None:
        """Le repère local (manuel § 5.6.2): un décalage et une rotation
        PAR-DESSUS le repère pièce; les paramètres absents gardent leur
        valeur."""
        if getattr(self, '_base_lcs', None) is None:
            self._base_lcs = (self.ox, self.oy, self.oz, self.angle)
            self._val_lcs = {'X': 0.0, 'Y': 0.0, 'Z': 0.0, 'gamma': 0.0}
        v = self._val_lcs
        if mot == 'ResetLcs':
            v.update({'X': 0.0, 'Y': 0.0, 'Z': 0.0, 'gamma': 0.0})
        elif mot == 'ShiftLcsAbs':
            for k in ('X', 'Y', 'Z'):
                if k in p:
                    v[k] = _f(p, k)
        elif mot == 'ShiftLcsInc':
            a = math.radians(v['gamma'])
            dx, dy = _f(p, 'X'), _f(p, 'Y')
            v['X'] += dx * math.cos(a) - dy * math.sin(a)
            v['Y'] += dx * math.sin(a) + dy * math.cos(a)
            v['Z'] += _f(p, 'Z')
        elif mot == 'RotateLcsAbs':
            if 'gamma' in p:
                v['gamma'] = _f(p, 'gamma')
        elif mot == 'RotateLcsInc':
            v['gamma'] += _f(p, 'gamma')
        bx, by, bz, ba = self._base_lcs
        a = math.radians(ba)
        vx, vy = self.mx * v['X'], self.my * v['Y']
        self.ox = bx + vx * math.cos(a) - vy * math.sin(a)
        self.oy = by + vx * math.sin(a) + vy * math.cos(a)
        self.oz = bz + v['Z']
        self.angle = ba + v['gamma'] * self.mx * self.my

    def _pattern(self, genre, p, profondeur):
        cible = str(p.get('callProgram', '') or '')
        if cible not in self.programmes:
            return

        def nombre(cle):
            """Un nombre d'éléments: 1 au moins, borné (un nombre trop
            grand ou illisible ne fait pas lever)."""
            v = _f(p, cle, 1)
            return int(min(max(v, 1.0), 1e12)) if v == v else 1

        def positions():
            # une à une: un motif démesuré ne se bâtit pas en liste, il
            # s'arrête au plafond des sommets (ou à Annuler)
            if genre == 'RectanglePattern':
                nx, ny = nombre('xCount'), nombre('yCount')
                delta_x, delta_y = _f(p, 'deltaX'), _f(p, 'deltaY')
                for j in range(ny):
                    for i in range(nx):
                        yield i * delta_x, j * delta_y
            elif genre == 'CircularPattern':
                # manuel § 5.8.5.1: radius, elements, xCenterShift,
                # yCenterShift, startAngle, endAngle, elementsToSkip
                n = nombre('elements')
                r = _f(p, 'radius')
                a0 = _f(p, 'startAngle')
                a1 = _f(p, 'endAngle', a0 + 360.0)
                cx, cy = _f(p, 'xCenterShift'), _f(p, 'yCenterShift')
                plein = abs((a1 - a0) % 360.0) < 1e-9
                pas = (a1 - a0) / (n if plein or n == 1 else n - 1)
                sauter = set()
                for mot in re.findall(r'\d+', str(p.get('elementsToSkip',
                                                        '') or '')):
                    sauter.add(int(mot))
                for i in range(n):
                    if i + 1 in sauter:
                        continue
                    a = math.radians(a0 + pas * i)
                    yield cx + r * math.cos(a), cy + r * math.sin(a)
            elif genre == 'CirclePattern':
                n = nombre('count')
                r = _f(p, 'radius')
                a0 = _f(p, 'startAngle')
                for i in range(n):
                    a = math.radians(a0 + 360.0 * i / n)
                    yield r * math.cos(a), r * math.sin(a)
            elif genre == 'LinearPattern':
                n = nombre('count')
                d = _f(p, 'deltaX')
                a = math.radians(_f(p, 'angle'))
                for i in range(n):
                    yield i * d * math.cos(a), i * d * math.sin(a)
            else:
                yield 0.0, 0.0

        self.cycles[genre] += 1
        base = (self.ox, self.oy, self.oz, self.angle)
        for rang, (dx, dy) in enumerate(positions()):
            if rang >= ELEMENTS_MAX:
                # (un programme appelé qui ne pose aucun sommet ne
                # s'arrêterait jamais)
                self.tronque = True
                raise _Arret()
            ex, ey = self._deplacement(dx, dy)
            self.ox = base[0] + ex
            self.oy = base[1] + ey
            self._programme(cible, profondeur + 1)
            self.ox, self.oy, self.oz, self.angle = base

    # ── les cycles ──

    def _cycle(self, nom, p):
        depart = self.ici()
        if depart is None:
            depart = (0.0, 0.0, 20.0)
            self.aller(*depart, rapide=True)
        cx, cy, z_depart = depart
        if nom in ('Helix', 'HelixWithFullCircle') and not (
                _mot(p, 'Inside') or _mot(p, 'Outside')):
            # syntaxe du manuel (§ 5.4.2): un MOUVEMENT, pas un cycle
            self._helice_mouvement(nom, p, cx, cy, z_depart)
            return
        scz = _f(p, 'strokeCuttingZ', 0.0)
        # en rapide jusqu'au plan d'approche lente
        self.aller(cx, cy, max(scz, min(z_depart, _f(
            p, 'strokeRapidZ', scz) + scz)), True)
        self.aller(cx, cy, scz, True)
        c = _Contexte(self, p, cx, cy, scz)
        getattr(self, _METHODES.get(nom, '_c_' + nom))(c, p)
        # retour au point de départ (manuel § 5.2)
        fin = self.ici()
        self.aller(fin[0], fin[1], max(scz, fin[2]), True)
        self.aller(fin[0], fin[1], max(z_depart, scz), True)
        self.aller(cx, cy, z_depart, True)

    def _helice_mouvement(self, nom, p, cx, cy, z0):
        d = _f(p, 'diameter')
        r = d / 2.0
        dz = abs(_f(p, 'deltaZ', _f(p, 'depth')))
        pas = _f(p, 'pitch', dz or 1.0) or (dz or 1.0)
        sens = -1 if _mot(p, 'CW') else 1
        a0 = math.radians(_f(p, 'startAngle'))
        self.aller(cx + r * math.cos(a0), cy + r * math.sin(a0), z0)
        self.chemin(_helice(cx, cy, r, z0, z0 - dz, pas, sens, a0))
        if nom == 'HelixWithFullCircle':
            self.chemin(_cercle(cx, cy, r, z0 - dz, a0 + sens * 2 * math.pi
                                * (dz / pas if pas else 0), sens)[1:])

    # -- perçages --

    def _c_Drill(self, c, p):
        haut = c.scz
        for z in niveaux(c.prof, c.passe):
            self.aller(c.cx, c.cy, haut, True)
            self.aller(c.cx, c.cy, z)
            # débourrage: retour au-dessus de la matière
            self.aller(c.cx, c.cy, c.scz, True)
            haut = min(c.scz, z + _REPRISE_PERCAGE)

    def _c_ThreadCutting(self, c, p):
        """Taraud (manuel § 5.2.1.5): descente au fond par passes de
        breakChipInfeed, remontée au-dessus de la matière à chacune."""
        passe = abs(_f(p, 'breakChipInfeed')) or c.prof
        for z in niveaux(c.prof, passe):
            self.aller(c.cx, c.cy, c.scz, True)
            self.aller(c.cx, c.cy, z)
            self.aller(c.cx, c.cy, c.scz)

    def _c_DrillMilling(self, c, p):
        self._fraisage_helicoidal(c, p, _f(p, 'diameter'), 1,
                                  plein=True)

    def _c_HelixWithFullCircle(self, c, p):
        self._fraisage_helicoidal(c, p, _f(p, 'diameter'),
                                  -1 if _mot(p, 'CW') else 1, plein=True)

    def _c_Helix(self, c, p):
        self._fraisage_helicoidal(c, p, _f(p, 'diameter'),
                                  -1 if _mot(p, 'CW') else 1, plein=False)

    def _fraisage_helicoidal(self, c, p, d, sens, plein):
        """Alésage à l'hélice: ébauche (finitions laissées) au pas de
        infeedZ, un tour plein au fond, puis la finition des parois au
        pas de infeedFinishingZ."""
        dehors = _mot(p, 'Outside')
        r_fin = d / 2.0 + c.rt if dehors else d / 2.0 - c.rt
        if r_fin <= 0.02:
            for z in niveaux(c.prof, c.passe):
                self.aller(c.cx, c.cy, z)
            return
        r_ebauche = r_fin + c.fxy if dehors else max(0.02, r_fin - c.fxy)
        fond_ebauche = -(c.prof - c.fz) if c.prof - c.fz > 0 else -c.prof
        pas = _f(p, 'pitch', c.passe) if 'pitch' in p else c.passe
        pas = pas if pas > 0 else c.prof
        self.aller(c.cx + r_ebauche, c.cy, c.scz)
        self.chemin(_helice(c.cx, c.cy, r_ebauche, c.scz, fond_ebauche,
                            pas, sens))
        if plein:
            a = self._angle(c)
            self.chemin(_cercle(c.cx, c.cy, r_ebauche, fond_ebauche, a,
                                sens)[1:])
        if c.fz > 0 and fond_ebauche > -c.prof:
            self.chemin(_helice(c.cx, c.cy, r_ebauche, fond_ebauche,
                                -c.prof, c.passe_fin, sens, self._angle(c)))
            self.chemin(_cercle(c.cx, c.cy, r_ebauche, -c.prof,
                                self._angle(c), sens)[1:])
        if c.fxy > 0:
            # finition des parois: du haut, au pas de finition
            self.aller(c.cx, c.cy, self.ici()[2])
            self.aller(c.cx, c.cy, c.scz, True)
            self.aller(c.cx + r_fin, c.cy, c.scz)
            self.chemin(_helice(c.cx, c.cy, r_fin, c.scz, -c.prof,
                                c.passe_fin, sens))
            self.chemin(_cercle(c.cx, c.cy, r_fin, -c.prof,
                                self._angle(c), sens)[1:])
        self.aller(c.cx, c.cy, self.ici()[2])

    def _angle(self, c):
        x, y, _z = self.ici()
        return math.atan2(y - c.cy, x - c.cx)

    def _c_Thread(self, c, p):
        filet = str(p.get('threadName', '') or '')
        mf = _FILET_RE.search(filet)
        nominal = float(mf.group(1).replace(',', '.')) if mf else 0.0
        pas = _f(p, 'pitch', PAS_FILET.get(
            filet.replace(',', '.').replace(' ', '').upper(), 0.0) or 0.5)
        self._filetage(c, p, nominal, pas)

    def _c_SpecialThread(self, c, p):
        self._filetage(c, p, _f(p, 'nominalDiameter'),
                       _f(p, 'pitch', 1.0) or 1.0)

    def _filetage(self, c, p, nominal, pas):
        """Fraisage de filet: une hélice au pas du filet sur toute la
        profondeur — montante ou plongeante (manuel § 5.2.1.3)."""
        dehors = _mot(p, 'Outside')
        gauche = _mot(p, 'LeftHandThread')
        avalant = _mot(p, 'ClimbMilling')
        # filet à droite: en opposition, l'intérieur plonge et
        # l'extérieur monte; en avalant, c'est l'inverse; à gauche aussi
        plonge = (not dehors) != avalant
        if gauche:
            plonge = not plonge
        # filet à droite qui monte: sens trigonométrique
        sens = 1 if (not plonge) != gauche else -1
        r = nominal / 2.0 + c.rt if dehors else nominal / 2.0 - c.rt
        if r <= 0.05:
            r = max(nominal * 0.25, 0.1)
        finition = _f(p, 'finishing')
        rayons = []
        if finition > 0:
            rayons.append(r + finition if dehors else max(0.05,
                                                          r - finition))
        rayons.append(r)
        haut, bas = 0.0, -c.prof
        cote = (lambda rr: (c.cx + rr, c.cy))
        for rr in rayons:
            z0, z1 = (haut, bas) if plonge else (bas, haut)
            if dehors:
                # par l'extérieur: on descend à côté de la pièce
                self.aller(*cote(rr + c.rt), c.scz, True)
                self.aller(*cote(rr + c.rt), z0)
            else:
                self.aller(c.cx, c.cy, z0)
            self.aller(*cote(rr), z0)
            self.chemin(_helice(c.cx, c.cy, rr, z0, z1, pas, sens))
            x, y, z = self.ici()
            if dehors:
                self.aller(c.cx + (rr + c.rt) * (x - c.cx) / rr,
                           c.cy + (rr + c.rt) * (y - c.cy) / rr, z)
                self.aller(self.ici()[0], self.ici()[1], c.scz, True)
            else:
                self.aller(c.cx, c.cy, z)
        if dehors:
            self.aller(c.cx, c.cy, c.scz, True)

    # -- texte --

    def _c_Texte(self, c, p):
        """Engrave::StandardTextEngrave, approché: une police à trait
        simple (police_fil), centrée (Center) ou calée (Left/Right) sur
        la position."""
        from src.core import police_fil
        texte = str(p.get('text', '') or '')
        if 'GetDate' in str(p.get('_texte', '')):
            import datetime
            texte += datetime.date.today().strftime('%d.%m.%Y')
        hauteur = _f(p, 'charHeight', 2.5) or 2.5
        if not texte.strip():
            return
        contours = police_fil.traits(texte, hauteur, _f(p, 'charWidth'))
        if not contours:
            return
        xs = [x for cont in contours for x, _y in cont]
        largeur = max(xs) - min(xs)
        # largeur de texte imposée: on étire en X
        etire = 1.0
        if _f(p, 'textWidth') > 0 and largeur > 0:
            etire = _f(p, 'textWidth') / largeur
        if _mot(p, 'Left'):
            ax = min(xs)
        elif _mot(p, 'Right'):
            ax = max(xs)
        else:
            ax = (min(xs) + max(xs)) / 2.0
        ay = hauteur / 2.0 if _mot(p, 'Center') else 0.0
        incl = math.tan(math.radians(_f(p, 'slant')))
        a = math.radians(_f(p, 'rotation'))
        co, si = math.cos(a), math.sin(a)
        z = -c.prof
        for cont in contours:
            pts = []
            for x, y in cont:
                u = (x - ax) * etire + (y - ay) * incl
                v = y - ay
                pts.append((c.cx + u * co - v * si, c.cy + u * si + v * co))
            if len(pts) < 2:
                continue
            x0, y0 = pts[0]
            self.aller(self.ici()[0], self.ici()[1], c.scz, True)
            self.aller(x0, y0, c.scz, True)
            self.aller(x0, y0, z)
            self.chemin([(px, py, z) for px, py in pts[1:]])
            self.aller(pts[-1][0], pts[-1][1], c.scz)

    # -- contours --

    @staticmethod
    def _decalage_contour(p, rt):
        """Le côté de l'outil: dedans (-rt), dehors (+rt), sur le bord."""
        if _mot(p, 'Inside'):
            return -rt
        if _mot(p, 'Outside'):
            return rt
        return 0.0

    @staticmethod
    def _biais(p) -> bool:
        v = p.get('diagonalInfeed', True)
        return not (isinstance(v, str) and v.lower() == 'false')

    def _contour(self, c, p, chemin_a, entree_a):
        """Un contour par passes: ébauche à finishingXY du bord jusqu'à
        finishingZ du fond, puis la finition (parois au pas de
        infeedFinishingZ, ou le seul fond). `chemin_a(décalage)` rend
        le contour, `entree_a(décalage)` le point de plongée de biais."""
        o = self._decalage_contour(p, c.rt)
        ebauche = o + (c.fxy if o > 0 else -c.fxy) if o else o
        biais = self._biais(p)
        prof_ebauche = c.prof - c.fz
        passes = []
        if prof_ebauche > 1e-9:
            passes += [(ebauche, z) for z in niveaux(prof_ebauche, c.passe)]
        if c.fxy > 0:
            passes += [(o, z) for z in niveaux(c.prof, c.passe_fin)]
        elif c.fz > 0 or prof_ebauche <= 1e-9:
            passes.append((o, -c.prof))
        for dec, z in passes:
            contour = chemin_a(dec)
            if not contour:
                continue
            x0, y0 = contour[0]
            # une passe plus haute que l'outil (la finition après
            # l'ébauche): on remonte sur place avant de se décaler —
            # sinon l'outil entrerait dans la paroi
            x, y, zc = self.ici()
            if z > zc:
                self.aller(x, y, z)
            haut = max(z, zc)
            if biais:
                ex, ey = entree_a(dec)
                self.aller(ex, ey, haut)
                self.aller(ex, ey, z)
                self.aller(x0, y0, z)
            else:
                self.aller(x0, y0, haut)
                self.aller(x0, y0, z)
            self.chemin([(a, b, z) for a, b in contour[1:]])
            if biais:
                ex, ey = entree_a(dec)
                self.aller(ex, ey, z)

    def _c_CircleFromMid(self, c, p):
        d = _f(p, 'diameter')
        sens = -1 if _mot(p, 'CW') else 1

        def chemin_a(dec):
            r = d / 2.0 + dec
            if r <= 0.02:
                return [(c.cx, c.cy)]
            return [(a, b) for a, b, _z in _cercle(c.cx, c.cy, r, 0.0, 0.0,
                                                   sens)]

        def entree_a(dec):
            r = max(0.0, d / 2.0 + dec)
            # de biais: à un rayon d'outil du bord, côté libre
            libre = r - c.rt if dec < 0 else r + c.rt
            return (c.cx + max(0.0, libre), c.cy)

        self._contour(c, p, chemin_a, entree_a)

    def _c_RectFromMid(self, c, p):
        w, h = _f(p, 'widthX'), _f(p, 'widthY')
        rc = _f(p, 'cornerRadius')

        def chemin_a(dec):
            if w + 2 * dec <= 0 or h + 2 * dec <= 0:
                return [(c.cx, c.cy)]
            return rectangle_arrondi(c.cx, c.cy, w + 2 * dec, h + 2 * dec,
                                     max(0.0, rc + dec))

        def entree_a(dec):
            bord = c.cx + (w + 2 * dec) / 2.0
            libre = bord - c.rt if dec < 0 else bord + c.rt
            return (max(c.cx, libre) if dec < 0 else libre, c.cy)

        self._contour(c, p, chemin_a, entree_a)

    # -- poches --

    def _entree_helicoidale(self, c, z_haut, z, rayon):
        """Descente en hélice au centre (un tour par passe)."""
        if rayon <= 0.02:
            self.aller(c.cx, c.cy, z)
            return
        self.aller(c.cx + rayon, c.cy, z_haut)
        self.chemin(_helice(c.cx, c.cy, rayon, z_haut, z,
                            max(abs(z_haut - z), 0.05)))
        self.aller(c.cx, c.cy, z)

    def _c_CircleCavity(self, c, p):
        d = _f(p, 'diameter')
        r_fin = d / 2.0 - c.rt
        if r_fin <= 0.02:
            self._c_Drill(c, p)
            return
        r_ebauche = max(0.02, r_fin - c.fxy)
        r_entree = min(0.5 * c.rt, r_ebauche)
        haut = 0.0
        prof_ebauche = c.prof - c.fz
        fonds = niveaux(prof_ebauche, c.passe) if prof_ebauche > 1e-9 else []
        if c.fz > 0 or not fonds:
            fonds.append(-c.prof)
        self.aller(c.cx, c.cy, 0.0)
        for z in fonds:
            self._entree_helicoidale(c, haut, z, r_entree)
            # la spirale: le diamètre grandit d'une prise par tour
            self.aller(c.cx + r_entree, c.cy, z)
            self.chemin(_spirale(c.cx, c.cy, r_entree, r_ebauche, c.pas, z))
            # le tour au bord repart d'où la spirale arrive
            self.chemin(_cercle(c.cx, c.cy, r_ebauche, z,
                                self._angle(c))[1:])
            self.aller(c.cx, c.cy, z)
            haut = z
        if c.fxy > 0:
            # finition des parois, du haut vers le bas
            for z in niveaux(c.prof, c.passe_fin):
                self.aller(c.cx, c.cy, z)
                self.aller(c.cx + r_fin, c.cy, z)
                self.chemin(_cercle(c.cx, c.cy, r_fin, z)[1:])
                self.aller(c.cx, c.cy, z)

    def _c_RectangleCavity(self, c, p):
        w, h = _f(p, 'widthX'), _f(p, 'widthY')
        rc = _f(p, 'cornerRadius')
        anneaux = self._anneaux_rectangle(c.cx, c.cy, w, h, rc,
                                          c.rt + c.fxy, c.pas)
        if not anneaux:
            self._c_Drill(c, p)
            return
        # rampe sur la ligne médiane de la poche (ou hélice si carrée)
        demi = abs(w - h) / 2.0
        lx = demi if w >= h else 0.0
        ly = demi if h > w else 0.0
        prof_ebauche = c.prof - c.fz
        fonds = niveaux(prof_ebauche, c.passe) if prof_ebauche > 1e-9 else []
        if c.fz > 0 or not fonds:
            fonds.append(-c.prof)
        haut = 0.0
        self.aller(c.cx, c.cy, 0.0)
        for z in fonds:
            if lx + ly > 0.05:
                self.aller(c.cx - lx, c.cy - ly, haut)
                self.aller(c.cx + lx, c.cy + ly, (haut + z) / 2.0)
                self.aller(c.cx - lx, c.cy - ly, z)
                self.aller(c.cx, c.cy, z)
            else:
                self._entree_helicoidale(c, haut, z,
                                         min(0.5 * c.rt, min(w, h) / 2.0
                                             - c.rt))
            for anneau in anneaux:
                self.aller(anneau[0][0], anneau[0][1], z)
                self.chemin([(a, b, z) for a, b in anneau[1:]])
            self.aller(c.cx, c.cy, z)
            haut = z
        if c.fxy > 0:
            contour = rectangle_arrondi(c.cx, c.cy, w - 2 * c.rt,
                                        h - 2 * c.rt, max(0.0, rc - c.rt))
            for z in niveaux(c.prof, c.passe_fin):
                self.aller(c.cx, c.cy, z)
                self.aller(contour[0][0], contour[0][1], z)
                self.chemin([(a, b, z) for a, b in contour[1:]])
                self.aller(c.cx, c.cy, z)

    @staticmethod
    def _anneaux_rectangle(cx, cy, w, h, rc, d0, pas):
        """Les anneaux d'une poche rectangulaire, du centre au bord
        (le dernier à d0 des parois)."""
        anneaux = []
        k = 0
        while True:
            d = d0 + k * pas
            wi, hi = w - 2 * d, h - 2 * d
            if wi <= 1e-6 or hi <= 1e-6:
                if not anneaux and min(w, h) - 2 * d0 > -1e-6:
                    # plus étroite que deux passes: une ligne au milieu
                    if w >= h:
                        lg = max(0.0, w - 2 * d0) / 2
                        anneaux.append([(cx - lg, cy), (cx + lg, cy)])
                    else:
                        lg = max(0.0, h - 2 * d0) / 2
                        anneaux.append([(cx, cy - lg), (cx, cy + lg)])
                break
            anneaux.append(rectangle_arrondi(cx, cy, wi, hi,
                                             max(0.0, rc - d)))
            k += 1
            if k > 2000:
                break
        anneaux.reverse()
        return anneaux

    # -- surfaçages --

    def _c_RectangleFace(self, c, p):
        w = _f(p, 'widthX') + 2 * _f(p, 'extensionX')
        h = _f(p, 'widthY') + 2 * _f(p, 'extensionY')
        a = math.radians(_f(p, 'angle'))
        co, si = math.cos(a), math.sin(a)
        coins = [(sx * w / 2, sy * h / 2) for sx in (-1, 1) for sy in (-1, 1)]
        # étendue dans le repère des passes (u le long des passes)
        us = [x * co + y * si for x, y in coins]
        vs = [-x * si + y * co for x, y in coins]
        u0, u1 = min(us) - c.rt, max(us) + c.rt
        v0, v1 = min(vs), max(vs)
        lignes = []
        v = v0
        while v <= v1 + 1e-9:
            lignes.append(v)
            v += c.pas
        if lignes and lignes[-1] < v1 - 1e-6:
            lignes.append(v1)

        def xy(u, v):
            return c.cx + u * co - v * si, c.cy + u * si + v * co

        deux_sens = _mot(p, 'BothWays')
        for z in self._fonds_surfacage(c):
            for i, v in enumerate(lignes):
                aller = (i % 2 == 0) or not deux_sens
                ua, ub = (u0, u1) if aller else (u1, u0)
                xa, ya = xy(ua, v)
                xb, yb = xy(ub, v)
                if deux_sens and i > 0:
                    self.aller(xa, ya, z)
                else:
                    # un seul sens: relevé, retour en rapide
                    x, y, _z = self.ici()
                    self.aller(x, y, c.scz, True)
                    self.aller(xa, ya, c.scz, True)
                    self.aller(xa, ya, z)
                self.aller(xb, yb, z)
            x, y, _z = self.ici()
            self.aller(x, y, c.scz, True)

    def _c_CircleFace(self, c, p):
        r = (_f(p, 'diameter') + _f(p, 'extensionDiameter')) / 2.0
        if r <= 0.02:
            return
        for z in self._fonds_surfacage(c):
            # du bord vers le centre, en spirale
            self.aller(c.cx + r, c.cy, c.scz, True)
            self.aller(c.cx + r, c.cy, z)
            self.chemin(_cercle(c.cx, c.cy, r, z)[1:])
            self.chemin(_spirale_vers_centre(c.cx, c.cy, r, c.pas, z))
            self.aller(c.cx, c.cy, c.scz, True)

    @staticmethod
    def _fonds_surfacage(c):
        prof_ebauche = c.prof - c.fz
        fonds = niveaux(prof_ebauche, c.passe) if prof_ebauche > 1e-9 else []
        if c.fz > 0 or not fonds:
            fonds.append(-c.prof)
        return fonds

    # ── le résultat ──

    def resultat(self) -> Dict:
        xs, ys, zs, ks = self.x, self.y, self.z, self.k
        longueur = 0.0
        for i in range(1, len(xs)):
            if ks[i] == COUPE:
                longueur += math.dist((xs[i - 1], ys[i - 1], zs[i - 1]),
                                      (xs[i], ys[i], zs[i]))
        if xs:
            bornes = (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))
            zc = [z for z, k in zip(zs, ks) if k == COUPE]
            bornes_coupe = (min(zc), max(zc)) if zc else None
        else:
            bornes = bornes_coupe = None
        return {'x': xs, 'y': ys, 'z': zs, 'k': ks, 'outil': self.o,
                'avance': self.f,
                'cycles': dict(self.cycles), 'tronque': self.tronque,
                'outils': dict(self.diametres), 'formes': dict(self.formes),
                'brut': self.brut, 'plages_ops': self.plages_ops,
                'longueur_coupe': longueur, 'bornes': bornes,
                'bornes_coupe': bornes_coupe,
                # ce que le programme laisse à qui l'appelle
                'etat_final': self._etat(),
                'entree': getattr(self, '_entree', None),
                'appelle_modules': bool(self.modules)}


class _Contexte:
    """Les réglages communs d'un cycle, lus une fois."""

    def __init__(self, sim, p, cx, cy, scz):
        self.cx, self.cy = cx, cy
        self.scz = scz
        self.rt = sim.rayon
        self.prof = abs(_f(p, 'depth', _f(p, 'deltaZ')))
        self.passe = abs(_f(p, 'infeedZ', self.prof)) or self.prof
        self.fxy = max(0.0, _f(p, 'finishingXY'))
        self.fz = max(0.0, _f(p, 'finishingZ'))
        if self.fz >= self.prof:
            self.fz = 0.0
        self.passe_fin = abs(_f(p, 'infeedFinishingZ', self.passe)) \
            or self.passe
        if 'distanceStepover' in p:
            self.pas = _f(p, 'distanceStepover')
        else:
            self.pas = 2 * self.rt * _f(p, 'percentageStepover', 50) / 100
        self.pas = max(0.02, self.pas)


_PROGRAMMES_LUS: Dict[str, tuple] = {}
_PARCOURS_FICHIERS: Dict[tuple, Dict] = {}


def lire_programme(chemin: str) -> Optional[str]:
    """Le texte d'un fichier SimPl (gardé tant qu'il ne change pas), ou
    None s'il est illisible."""
    import os
    chemin = chemin_local(chemin)
    try:
        date = os.path.getmtime(chemin)
    except (OSError, ValueError):
        return None
    lu = _PROGRAMMES_LUS.get(chemin)
    if lu is not None and lu[0] == date:
        return lu[1]
    try:
        with open(chemin, 'r', encoding='utf-8', errors='replace') as f:
            texte = f.read()
    except (OSError, ValueError):
        return None
    if len(_PROGRAMMES_LUS) > 32:
        _PROGRAMMES_LUS.clear()
    _PROGRAMMES_LUS[chemin] = (date, texte)
    return texte


#: au-delà de cette taille (octets), un programme appelé se simule dans
#: la barre d'état (avec Annuler) avant d'être dessiné: un programme 3D
#: de 30 Mo figeait la fenêtre plusieurs secondes, muette
SEUIL_SUIVI = 1_000_000
#: les parcours en cours de calcul (sur un fil de travail): un dessin
#: qui tombe dessus s'en passe au lieu de le refaire en gelant tout
_PARCOURS_EN_COURS: set = set()
#: les parcours dont on a ANNULÉ le calcul: on ne les relance pas d'office
#: (jusqu'à ce que le fichier change, ou qu'on le rouvre)
_PARCOURS_REFUSES: set = set()


def _norme(chemin: str) -> str:
    """Le même fichier sous la même clé, quelle que soit l'écriture
    de son chemin (barres obliques du sélecteur de fichiers, contre-
    obliques du usermodule, casse de Windows)."""
    import os
    return os.path.normcase(os.path.normpath(str(chemin)))


def _cle_parcours(chemin: str, diametres, max_sommets):
    import os
    chemin = chemin_local(chemin)
    try:
        date = os.path.getmtime(chemin)
    except (OSError, ValueError):
        return None
    return (_norme(chemin), date, tuple(sorted((diametres or {}).items())),
            max_sommets)


def parcours_a_preparer(chemin: str, diametres: Optional[dict] = None,
                        max_sommets: int = MAX_SOMMETS) -> bool:
    """Ce programme appelé est-il assez gros, et pas encore simulé (ni
    refusé, ni en cours), pour passer par la barre d'état?"""
    import os
    chemin = chemin_local(chemin)
    cle = _cle_parcours(chemin, diametres, max_sommets)
    if cle is None or cle in _PARCOURS_FICHIERS \
            or cle in _PARCOURS_EN_COURS or cle in _PARCOURS_REFUSES:
        return False
    try:
        return os.path.getsize(chemin) > SEUIL_SUIVI
    except (OSError, ValueError):
        return False


def parcours_en_cours(chemin: str) -> bool:
    """Le parcours de ce fichier se calcule-t-il en ce moment?"""
    cle = _norme(chemin_local(chemin))
    return any(c[0] == cle for c in list(_PARCOURS_EN_COURS))


def oublier_refus(chemin: str) -> None:
    """Le fichier est rouvert: un calcul annulé peut être relancé."""
    norme = _norme(chemin_local(chemin))
    for cle in [c for c in _PARCOURS_REFUSES if c[0] == norme]:
        _PARCOURS_REFUSES.discard(cle)


def taille_avec_modules(code: str) -> int:
    """La taille d'un programme ET des programmes externes qu'il appelle
    (usermodule): ce qu'une simulation aura vraiment à dérouler."""
    import os
    total = len(code or "")
    for m in _USERMODULE_RE.finditer(code or ""):
        try:
            total += os.path.getsize(chemin_local(
                m.group(2).replace('\\\\', '\\')))
        except (OSError, ValueError):
            pass
    return total


def parcours_fichier(chemin: str, diametres: Optional[dict] = None,
                     max_sommets: int = MAX_SOMMETS,
                     progression=None) -> Optional[Dict]:
    """Le parcours simulé d'un programme externe ENTIER (Main, cycles,
    séquences), gardé tant que le fichier ne change pas — un appel
    externe de cent mille mouvements ne se rejoue pas à chaque dessin.
    Sans `progression`, un parcours en cours de calcul ou annulé rend
    None (le dessin s'en passe); avec, il se calcule (Annuler lève
    `vcarve.Annule` et le parcours est noté refusé)."""
    from src.core import vcarve
    cle = _cle_parcours(chemin, diametres, max_sommets)
    if cle is None:
        return None
    res = _PARCOURS_FICHIERS.get(cle)
    if res is not None:
        return res
    if cle in _PARCOURS_EN_COURS:
        return None
    if progression is None and cle in _PARCOURS_REFUSES:
        return None
    code = lire_programme(chemin)
    if code is None:
        return None
    _PARCOURS_EN_COURS.add(cle)
    try:
        res = simuler(code, diametres, progression,
                      max_sommets=max_sommets)
    except vcarve.Annule:
        _PARCOURS_REFUSES.add(cle)
        raise
    except Exception:
        return None
    finally:
        _PARCOURS_EN_COURS.discard(cle)
    _PARCOURS_REFUSES.discard(cle)
    if len(_PARCOURS_FICHIERS) > 16:
        _PARCOURS_FICHIERS.clear()
    _PARCOURS_FICHIERS[cle] = res
    return res


def simuler(code: str, diametres: Optional[dict] = None,
            progression=None, max_sommets: int = MAX_SOMMETS,
            formes: Optional[dict] = None) -> Dict:
    """Le parcours 3D d'un programme SimPL entier (voir le module).
    `diametres`: {référence d'outil: diamètre}; `formes`: {référence:
    forme} (voir `formes_outils`), gardées pour l'enlèvement de
    matière."""
    from src.core import vcarve
    sim = Simulation(code, diametres, progression, max_sommets, formes)
    sim.executer()
    vcarve.avancer(progression, 1.0, "simulation terminée")
    return sim.resultat()


def _diametre_coupe(t, cat=None) -> float:
    """Le diamètre de coupe d'un outil: sa fiche, sinon le catalogue
    DATRON (D1) — les fraises à fileter n'ont pas de Ø dans tools.json."""
    try:
        d = float(getattr(t, 'diameter', 0) or 0)
    except (TypeError, ValueError):
        d = 0.0
    if d > 0:
        return d
    g = getattr(t, 'geometry', None) or {}
    try:
        d = float(g.get('Diameter') or 0)
    except (TypeError, ValueError):
        d = 0.0
    if d > 0:
        return d
    if cat is not None:
        e = cat.entree(str(getattr(t, 'article_nr', '') or ''))
        if e and e.get('categorie') == 'filetage':
            try:
                return float(e.get('D1') or 0)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def _catalogue():
    try:
        from src.core.catalogue_datron import catalogue
        return catalogue()
    except Exception:
        return None


def diametres_de(tool_library) -> Dict[str, float]:
    """{référence: diamètre de coupe} des outils de la bibliothèque."""
    cat = _catalogue()
    sortie = {}
    for t in getattr(tool_library, 'tools', {}).values():
        art = str(getattr(t, 'article_nr', '') or '')
        d = _diametre_coupe(t, cat)
        if d <= 0:
            continue
        # par la référence (Tool type=) et par le nom (Tool name=)
        for cle in (art, str(getattr(t, 'name', '') or '')):
            if cle and cle not in sortie:
                sortie[cle] = d
    return sortie


def forme_outil(t, cat=None) -> Dict:
    """La forme d'un outil, pour l'enlèvement de matière:
    {'forme': 'plate'|'boule'|'cone'|'tslot'|'filet', 'rayon': rayon
    maxi qui coupe, 'angle': angle de pointe (°, cône), 'pointe': Ø de
    la pointe} — une fraise en T a aussi 'hauteur' (l'épaisseur de son
    disque, « h1.3 » de son nom) et 'col' (le rayon de sa tige); une
    fraise à fileter, 'longueur' (ses dents)."""
    nom = str(getattr(t, 'name', '') or '').lower()
    g = getattr(t, 'geometry', None) or {}
    e = None
    if cat is not None:
        e = cat.entree(str(getattr(t, 'article_nr', '') or ''))
    categorie = (e or {}).get('categorie', '')

    def _n(v, defaut=0.0):
        try:
            return float(v)
        except (TypeError, ValueError):
            return defaut

    d = _diametre_coupe(t, cat)
    angle = _n(g.get('TipAngle')) or _n((e or {}).get('angle'))
    if nom.startswith(('con', 'cham', 'chanf')) or categorie in (
            'conique', 'chanfrein'):
        pointe = _n(g.get('TipDiameter'))
        if categorie == 'conique' and not pointe:
            pointe = _n((e or {}).get('D1'))
        queue = (_n(g.get('ShaftDiameter')) or _n((e or {}).get('D2'))
                 or max(d, 3.0))
        return {'forme': 'cone', 'rayon': max(queue, pointe) / 2.0,
                'angle': angle or 90.0, 'pointe': pointe}
    if nom.startswith('foret') or categorie == 'foret':
        return {'forme': 'cone', 'rayon': max(d, 0.1) / 2.0,
                'angle': 118.0, 'pointe': 0.0}
    if nom.startswith(('t-slot', 'tslot', 't slot', 'rainure en t',
                       'scheiben')) or categorie in ('rainure_t', 'tslot',
                                                     'disque'):
        # une fraise en T: un disque au bout d'une tige plus fine — elle
        # ne coupe que dans l'épaisseur du disque
        import re as _re
        m = _re.search(r'\bh\s*([0-9]+(?:[.,][0-9]+)?)', nom)
        h = (float(m.group(1).replace(',', '.')) if m
             else _n((e or {}).get('L2')) or max(0.5, 0.2 * d))
        return {'forme': 'tslot', 'rayon': max(d, 0.1) / 2.0,
                'hauteur': h, 'col': 0.45 * max(d, 0.1) / 2.0,
                'angle': 0.0, 'pointe': 0.0}
    if nom.startswith(('thr', 'thread', 'fraise à fileter')) \
            or categorie == 'filetage':
        longueur = (_n((e or {}).get('longueur_utile'))
                    or _n(g.get('FluteLength')) or 2.0 * max(d, 0.5))
        return {'forme': 'filet', 'rayon': max(d, 0.1) / 2.0
                if d > 0 else DIAMETRE_INCONNU / 2.0,
                'longueur': longueur, 'angle': 0.0, 'pointe': 0.0}
    if any(m in nom for m in ('ball', 'kug', 'boule', 'hémi', 'hemi',
                              'sph')) \
            or categorie in ('boule', 'hemispherique'):
        return {'forme': 'boule', 'rayon': max(d, 0.1) / 2.0,
                'angle': 0.0, 'pointe': 0.0}
    return {'forme': 'plate', 'rayon': max(d, 0.1) / 2.0 if d > 0
            else DIAMETRE_INCONNU / 2.0, 'angle': 0.0, 'pointe': 0.0}


def formes_outils(tool_library) -> Dict[str, Dict]:
    """{référence: forme} des outils de la bibliothèque."""
    cat = _catalogue()
    sortie = {}
    for t in getattr(tool_library, 'tools', {}).values():
        forme = None
        for cle in (str(getattr(t, 'article_nr', '') or ''),
                    str(getattr(t, 'name', '') or '')):
            if cle and cle not in sortie:
                forme = forme or forme_outil(t, cat)
                sortie[cle] = forme
    return sortie


def resume(res: Dict) -> str:
    """« 12 cycles (Drill ×3, …) · coupe 1,2 m »."""
    cycles = res.get('cycles') or {}
    n = sum(v for k, v in cycles.items() if k in CYCLES)
    morceaux = []
    if n:
        detail = ", ".join(f"{k} ×{v}" for k, v in sorted(
            cycles.items()) if k in CYCLES)
        morceaux.append(f"{n} cycle(s) simulé(s) ({detail})")
    if cycles.get('Séquence'):
        morceaux.append(f"{cycles['Séquence']} séquence(s)")
    lg = res.get('longueur_coupe') or 0.0
    if lg:
        morceaux.append(f"coupe {lg / 1000:.2f} m" if lg >= 1000
                        else f"coupe {lg:.0f} mm")
    if res.get('tronque'):
        morceaux.append("aperçu tronqué")
    return " · ".join(morceaux)
