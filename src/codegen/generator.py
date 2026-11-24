"""
Générateur de code SimPl complet.
Assemble l'en-tête, le programme Main, les sous-programmes, et le pied.
Reproduit fidèlement la structure observée dans les exemples .SimPl.

Améliorations:
- Noms de sous-programmes simplifiés (NomOp_1 au lieu de hex UUID)
- ShiftWcsInc: génère automatiquement le retour inverse
- SetFeedTechnology sur une seule ligne
- Ébavurage: sous-programme dédié avec chemin le plus court
- Multi-outil taraudage: un sous-programme par outil
"""

from datetime import datetime
from typing import List, Optional, Dict, Tuple
from src.core.affichage import FIN_OPS, MARQUE_OP, retirer_marques
from src.core.program_model import ProgramModel, OperationInstance
from src.core.tool_library import ToolLibrary, Tool
from src.operations.registry import OperationRegistry
from src.operations.bpm import BPMOperation
import unicodedata
import re
import math

# Opérations utilisant le pattern per-point (via DathreadPointsWidget)
class _VarRef(float):
    """Référence à une variable SimPl utilisée à la place d'un nombre.

    Hérite de `float` pour traverser sans casse les calculs et
    comparaisons du code d'opération (`if depth > 0`, `abs(...)`),
    mais s'ÉCRIT comme le nom de la variable: `depth=profondeur`.
    La valeur numérique de repli n'apparaît donc jamais dans le code,
    sauf si une opération force explicitement une conversion
    (`float(x)` puis formatage) — cas détecté par les tests.
    """

    def __new__(cls, name: str, fallback: float = 0.0):
        obj = super().__new__(cls, fallback)
        obj.name = name
        return obj

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name

    def __format__(self, spec):
        return self.name


_VAR_PROBE_CACHE: Dict[str, set] = {}


def variable_capable_params(op_type: str) -> set:
    """Paramètres d'une opération pouvant recevoir une VARIABLE
    opérateur au lieu d'un nombre.

    Déterminé par SONDAGE réel du code généré (et non par une liste
    figée qui se désynchroniserait): on injecte une référence témoin
    et on ne retient le paramètre que si son nom ressort dans le code.
    Écarte donc automatiquement les paramètres consommés par le
    générateur (répétitions) ou recalculés par l'opération (BPM...)."""
    if op_type in _VAR_PROBE_CACHE:
        return _VAR_PROBE_CACHE[op_type]
    from src.operations.base_operation import ParameterType
    from src.operations.registry import OperationRegistry
    result = set()
    try:
        cls = OperationRegistry.get(op_type)
    except KeyError:
        _VAR_PROBE_CACHE[op_type] = result
        return result
    token = "__NDVAR_PROBE__"
    for pdef in cls.get_parameters():
        if pdef.param_type not in (ParameterType.FLOAT,
                                   ParameterType.INT):
            continue
        params = cls.get_default_params()
        params[pdef.key] = _VarRef(token, 1.0)
        params.setdefault('_op_x', 0.0)
        params.setdefault('_op_y', 0.0)
        try:
            if token in cls.generate_operation_code(params):
                result.add(pdef.key)
        except Exception:
            continue
    _VAR_PROBE_CACHE[op_type] = result
    return result


_PER_POINT_PATTERN_OPS = {"taraudage", "percage_fraise", "percage_foret"}

# Types pouvant entrer dans un groupe NOMMÉ par l'utilisateur
# (un sous-programme commun = un seul changement d'outil)
_GROUPABLE_TYPES = {"taraudage", "taraudage_brut",
                    "percage_foret", "percage_fraise"}


def _sanitize_simpl_string(text: str) -> str:
    """Neutralise les guillemets doubles qui casseraient un littéral
    chaîne SimPl ("..."). Remplacés par des apostrophes."""
    return str(text).replace('"', "'")


def build_operation_blocks(op, program, tool_library,
                           expert=None) -> Tuple[List[str], List[str]]:
    """Génère le SimPl d'UNE opération NeoDrive isolée.

    Retourne (blocs_sous_programmes, lignes_d_appel). Une opération
    peut en produire plusieurs (taraudage groupé, ébavurage,
    sous-programmes de pattern): on récupère tout ce que le générateur
    émet, appels compris. Sert à insérer une opération dans un
    programme SimPl existant.
    """
    from src.core.program_model import ProgramModel

    tmp = ProgramModel()
    tmp.settings = program.settings
    clone = op.clone()
    clone.name = op.name           # clone() suffixe « (copie) »
    tmp.add_operation(clone)
    code = SimPlGenerator(tmp, tool_library,
                          expert_settings=expert or {}).generate()
    blocks = [m.group(0) for m in re.finditer(
        r'^program\s+\w+\n.*?^endprogram', code,
        re.MULTILINE | re.DOTALL)]
    skip = {'Absolute', 'SpraySystem Off', 'Spindle Off',
            'MoveToParkPosition', 'SpraySystem On', 'Spindle On'}
    calls = []
    i = code.index('export program Main')
    body = code[i:code.index('\nendprogram', i)]
    for line in body.split('\n')[1:]:
        text = line.strip()
        if text and text not in skip and not text.startswith('#'):
            calls.append(text)
    return blocks, calls


def strip_accents(text: str) -> str:
    """Retire les accents en gardant le reste du texte intact."""
    nfkd = unicodedata.normalize('NFKD', str(text))
    return ''.join(c for c in nfkd if not unicodedata.combining(c))


def find_accented_texts(program) -> List[Tuple[str, str, str]]:
    """Textes du programme contenant des accents ou des caractères
    non-ASCII.

    Certaines machines affichent mal ces caractères dans les
    dialogues et commentaires. Retourne
    [(origine, texte, texte_sans_accent), ...] — c'est à
    l'utilisateur de décider.
    """
    def _flag(origin, value):
        txt = str(value or '')
        if txt and any(ord(c) > 127 for c in txt):
            clean = strip_accents(txt)
            if clean != txt:
                return (origin, txt, clean)
        return None

    found = []
    s = getattr(program, 'settings', None)
    if s is not None:
        hit = _flag("Commentaire du programme", s.comment)
        if hit:
            found.append(hit)
        hit = _flag("Auteur", s.author)
        if hit:
            found.append(hit)
    # Textes visibles par l'opérateur ou gravés
    keys = ('message', 'caption', 'text', 'prefix', 'label',
            'var_name')
    for op in getattr(program, 'operations', []) or []:
        if not getattr(op, 'enabled', True):
            continue
        for key in keys:
            hit = _flag(f"{op.name} · {key}", op.params.get(key))
            if hit:
                found.append(hit)
        for i, field in enumerate(op.params.get('fields') or []):
            for key in ('label', 'var', 'unit'):
                hit = _flag(f"{op.name} · champ {i + 1} {key}",
                            field.get(key))
                if hit:
                    found.append(hit)
    return found


def _clean_name(name: str) -> str:
    """Nettoie un nom pour SimPl: ASCII, pas d'espaces/accents.
    Un nom SimPl ne doit pas commencer par un chiffre → préfixe 'Prog'."""
    # Normaliser les accents
    nfkd = unicodedata.normalize('NFKD', name)
    ascii_name = nfkd.encode('ASCII', 'ignore').decode('ASCII')
    # Remplacer espaces et caractères spéciaux
    clean = re.sub(r'[^A-Za-z0-9_]', '_', ascii_name)
    # Supprimer les underscores multiples
    clean = re.sub(r'_+', '_', clean).strip('_')
    if not clean:
        return "Op"
    # SimPl interdit les noms commençant par un chiffre
    if clean[0].isdigit():
        clean = f"Prog{clean}"
    return clean


class SimPlGenerator:
    """Génère le code SimPl complet à partir du ProgramModel."""

    # Cache de sous-programmes: (op_id, hash) -> code
    _subprogram_cache: Dict[str, Tuple[int, str]] = {}

    def __init__(self, program: ProgramModel, tool_library: ToolLibrary,
                 path_replace_from: str = "", path_replace_to: str = "",
                 expert_settings: Optional[Dict] = None,
                 calculer: bool = True, progression=None):
        #: calculer les parcours de gravure manquants ?
        #: L'APERÇU dit non — sur une gamme de quatre outils, chaque
        #: frappe dans un formulaire relançait toute la gravure.
        #: L'export dit oui, avec une barre de progression.
        self.calculer = bool(calculer)
        #: appelée avec le nom de chaque opération calculée
        self.progression = progression
        self.program = program
        self.tool_lib = tool_library
        self._path_replace_from = path_replace_from
        self._path_replace_to = path_replace_to
        self._expert = expert_settings or {}
        self._prog_names: Dict[str, str] = {}  # op.id -> prog_name
        self._taraudage_main_calls: Dict[str, list] = {}  # op.id -> [(call_line, is_pattern)]

    def generate(self) -> str:
        """Génère le fichier SimPl complet."""
        # Une gamme de gravure se chaîne AVANT tout calcul: chaque
        # outil ne doit usiner que le reste du précédent.
        from src.operations.gravure_2d5 import chainer
        chainer(self.program.operations, self.tool_lib)
        muettes = self._ecarter_operations_muettes()
        try:
            self.code_marque = self._generer()
        finally:
            for op in muettes:
                op.enabled = True
        return retirer_marques(self.code_marque)

    #: le dernier code généré, chaque opération ouverte par un repère
    #: (commentaire « #@op <id> »): la simulation du Canva 3D sait ainsi à
    #: quelle opération appartient chaque mouvement, même fusionnée dans le
    #: sous-programme d'un ensemble. Jamais dans le programme de la machine.
    code_marque = ""

    #: opérations de gravure dont le parcours s'est révélé vide, avec
    #: la raison — le panneau les affiche après génération
    ops_sans_parcours: list = []
    #: opérations dont le parcours n'est PAS ENCORE calculé: elles ne
    #: peuvent pas sortir tant qu'on n'a pas cliqué « Calculer »
    ops_a_calculer: list = []
    #: le bloc NDMETA n'a pas pu s'écrire (raison), sinon None
    meta_erreur = None

    def _ecarter_operations_muettes(self) -> list:
        """Écarte les gravures qui n'ont rien à sortir.

        Deux cas, à ne pas confondre:

        - l'outil ne peut RIEN enlever (pointe plus large que le
          tracé). L'opération déclarait quand même sa séquence,
          l'appelait dans son sous-programme, et aucun bloc $$$ ne
          suivait: la machine s'arrêtait sur une séquence inconnue;
        - le parcours n'est pas encore CALCULÉ. En aperçu, on ne le
          lance pas: sur une gamme de quatre outils, chaque frappe
          dans un formulaire relançait toute la gravure. Le bouton
          « Calculer » fait le travail, et l'écran dit ce qui reste
          à calculer.
        """
        self.ops_sans_parcours = []
        self.ops_a_calculer = []
        muettes = []
        from src.core.vcarve import sous_progression
        candidates = [op for op in self.program.operations
                      if op.enabled
                      and op.operation_type in self.SEQ_CALCULEES]
        for numero, op in enumerate(candidates):
            raison = None
            try:
                classe = self._get_op_class(op)
                params = self._params_avec_outil(op)
                nom = op.name or op.operation_type
                tranche = sous_progression(
                    self.progression, numero / len(candidates),
                    (numero + 1) / len(candidates),
                    f"{nom} ({numero + 1}/{len(candidates)}) — ")
                plan = (classe.plan(params, progression=tranche)
                        if self.calculer
                        else classe.plan_si_connu(params))
                if plan:
                    continue
                raison = ("parcours vide: la pointe est plus large "
                          "que le tracé") if plan is not None else None
            except Exception:
                continue
            op.enabled = False
            muettes.append(op)
            nom = op.name or op.operation_type
            if raison is None:
                self.ops_a_calculer.append(nom)
            else:
                self.ops_sans_parcours.append((nom, raison))
        return muettes

    def _generer(self) -> str:
        # Les noms des séquences d'abord — c'est eux qu'on lit sur la
        # machine —, puis ceux des sous-programmes, qui les évitent:
        # un sous-programme et une séquence de même nom, à la casse
        # près, font refuser le programme.
        self._assign_sequence_names()
        self._assign_prog_names()

        parts = [
            self._build_header(),
            self._build_imports(),
            "",
            self._build_main_program(),
        ]
        # Sous-programmes groupés taraudage (combinés)
        for grp_name, grp_ops in self._taraudage_groups.items():
            parts.append("")
            parts.append(self._build_grouped_taraudage_sub(grp_name, grp_ops))
        # Les ensembles de la liste, d'un même outil: un sous-programme
        for nom, membres in getattr(self, '_ensembles_fusionnes',
                                    {}).items():
            parts.append("")
            parts.append(self._build_ensemble_sub(nom, membres))

        # Sous-programmes pour les opérations non-inline
        for op in self.program.operations:
            if not op.enabled:
                continue
            # dans un ensemble fusionné: son corps est dans celui-ci
            if op.id in getattr(self, '_op_in_ensemble', {}):
                continue
            # Skip ops qui sont dans un groupe taraudage
            if op.id in self._op_in_group:
                # Mais construire l'ébavurage individuel si nécessaire
                if self._needs_ebavurage(op):
                    parts.append("")
                    parts.append(self._build_ebavurage_subprogram(op))
                continue
            op_class = self._get_op_class(op)
            if op_class and not op_class.INLINE:
                # Multi-tool taraudage: un sous-programme par outil
                # Per-point pattern ops: chaque point a son propre sous-programme
                _is_per_point = (
                    op.operation_type in _PER_POINT_PATTERN_OPS
                    and hasattr(op, 'points') and op.points)

                multi_subs = self._build_multi_tool_subprograms(op)
                if multi_subs:
                    for sub in multi_subs:
                        parts.append("")
                        parts.append(sub)
                elif _is_per_point:
                    # Pas de sous-programme de base: chaque point → _pt{i}
                    pt_subs = self._build_per_point_subprograms(op)
                    for psub in pt_subs:
                        parts.append("")
                        parts.append(psub)
                elif op.operation_type == "bloc_simpl":
                    # Bloc importé: on réémet le sous-programme
                    # d'ORIGINE, seules les valeurs réglées par
                    # l'utilisateur y sont substituées. `_name` porte
                    # le nom résolu: renommer l'opération renomme le
                    # sous-programme partout.
                    from src.operations.bloc_simpl import BlocSimpl
                    bloc_params = dict(op.params)
                    bloc_params['_name'] = self._get_prog_name(op)
                    bloc_params['_sequence_unique'] = \
                        self._seq_name_for(op)
                    body = BlocSimpl.body(bloc_params)
                    if body.strip():
                        parts.append("")
                        parts.append(body.rstrip())
                elif op.operation_type in ("palpage_memorise",
                                           "palpage_rectangle"):
                    # leur programme vient de _build_palpage_*_programs:
                    # le squelette générique, jamais appelé, portait
                    # même le MÊME nom (Palpage_memorise) — programme
                    # défini deux fois, refusé par la machine
                    pass
                else:
                    parts.append("")
                    parts.append(self._build_subprogram_cached(op))

                # Fraisage de tête de vis: sous-programme dédié
                if self._needs_head_milling(op):
                    parts.append("")
                    parts.append(self._build_head_subprogram(op))

                # Ébavurage: sous-programme dédié
                if self._needs_ebavurage(op):
                    parts.append("")
                    parts.append(self._build_ebavurage_subprogram(op))

        # Palpages autonomes du brut
        palp_code = self._build_palpage_rect_programs()
        if palp_code:
            parts.append("")
            parts.append(palp_code)

        # Reprise du dernier palpage (données persistées machine)
        memorise_code = self._build_palpage_memorise_programs()
        if memorise_code:
            parts.append("")
            parts.append(memorise_code)

        # Dialogue AskFor si nécessaire
        askfor_code = self._build_askfor_programs()
        if askfor_code:
            parts.append("")
            parts.append(askfor_code)

        parts.append("")
        parts.append("end")
        # Tool List en commentaire APRÈS le end (pied de programme)
        tool_desc = self._build_tool_descriptions()
        if tool_desc:
            parts.append("")
            parts.append(tool_desc)
        # Métadonnées NeoDrive: après `end`, AVANT les séquences. Un
        # bloc $$$ court jusqu'au suivant ou à la fin du fichier: en
        # tout dernier, les métadonnées entraient dans la dernière
        # séquence — aucun des programmes que la machine a lus ne
        # porte une ligne de commentaire dans une séquence, et tous
        # finissent par leurs blocs $$$. L'import les retrouve où
        # qu'elles soient.
        # (posées en dernier: le bloc porte l'empreinte du code final)
        parts.append("")
        parts.append(self._MARQUE_META)
        # Blocs $$$ des séquences Datron embarquées (Z ajustés)
        seq_ops = self._sequence_ops()
        if seq_ops:
            from src.operations.sequence_datron import SequenceDatron
            parts.append("")
            parts.append("# " + "#" * 58)
            for op in seq_ops:
                parts.append("")
                seq_params = dict(op.params)
                if op.operation_type == "bloc_simpl":
                    from src.operations.bloc_simpl import BlocSimpl
                    # le nom unique, comme sa déclaration et son appel
                    block = BlocSimpl.sequence_block(dict(
                        op.params,
                        _sequence_unique=self._seq_name_for(op)))
                    if block.strip():
                        parts.append(block.rstrip())
                    continue
                seq_params['sequence_name'] = self._seq_name_for(op)
                if op.operation_type in self.SEQ_CALCULEES:
                    seq_params = dict(
                        self._params_avec_outil(op),
                        sequence_name=seq_params['sequence_name'])
                    if self.progression is not None:
                        self.progression(1.0, "écriture des séquences")
                    classe = self._get_op_class(op)
                    seq_params['_safe_rapid_z'] = self._safe_rapid_z
                    seq_params['_stroke_cutting_z'] = \
                        self._stroke_cutting_z
                    bloc = classe.build_sequence_block(seq_params)
                    if bloc.strip():
                        parts.append(bloc)
                    continue
                if op.operation_type == "ebavurage":
                    from src.operations.ebavurage import Ebavurage
                    seq_params['_safe_rapid_z'] = self._safe_rapid_z
                    seq_params['_stroke_cutting_z'] = \
                        self._stroke_cutting_z
                    bloc = Ebavurage.build_sequence_block(seq_params)
                    if bloc.strip():
                        parts.append(bloc)
                    continue
                if op.operation_type == "trace":
                    from src.operations.trace import Trace
                    # la compensation du côté de l'outil: son Ø
                    seq_params['_diametre_outil'] = self._diametre_outil(op)
                    seq_params['_safe_rapid_z'] = self._safe_rapid_z
                    seq_params['_stroke_cutting_z'] = \
                        self._stroke_cutting_z
                    block = Trace.build_sequence_block(
                        seq_params, op.x, op.y, op.points)
                    if block.strip():
                        parts.append(block)
                    continue
                parts.append(
                    SequenceDatron.build_sequence_block(seq_params))
        parts.append("")

        code = self._apply_machine_limits("\n".join(parts))
        return self._poser_meta(self._annotate_subprograms(code))

    #: la place du bloc NDMETA, tant que le code n'est pas fini
    _MARQUE_META = "# @@NDMETA_ICI@@"

    def _poser_meta(self, code: str) -> str:
        """Le bloc NDMETA à sa place, avec l'empreinte du code fini
        (commentaires exclus: la marque, les repères d'opérations et
        l'en-tête horodaté n'y comptent pas). Rouvert après une
        correction, le fichier se reconnaît périmé."""
        from src.io.simpl_importer import empreinte_du_code
        meta = self._build_neodrive_metadata(
            empreinte=empreinte_du_code(code))
        if meta:
            return code.replace(self._MARQUE_META, meta, 1)
        return code.replace("\n\n" + self._MARQUE_META, "", 1)

    def _diametre_outil(self, op) -> float:
        """Le Ø de coupe de l'outil d'une opération (0: inconnu)."""
        try:
            from src.core import sim_cycles
            t = self.tool_lib.get_tool(op.tool_id) if op.tool_id else None
            return float(sim_cycles._diametre_coupe(t)) if t else 0.0
        except Exception:
            return 0.0

    def _annotate_subprograms(self, code: str) -> str:
        """Documente chaque sous-programme à la manière des fichiers
        Datron: temps d'usinage estimé, profondeur mini atteinte, et
        annotation @doc: (affichée comme aide dans l'éditeur
        machine). OPTIONS EXPERT, désactivées par défaut."""
        if not (self._expert.get('emit_op_stats', False)
                or self._expert.get('emit_op_doc', False)):
            return code
        # nom de sous-programme -> opération (le plus long préfixe
        # gagne: « Dec » ne doit pas capter « Dec_2 »)
        bases = []
        for op in self.program.operations:
            if not op.enabled:
                continue
            base = self._prog_names.get(op.id)
            if base:
                bases.append((base, op))
        bases.sort(key=lambda kv: len(kv[0]), reverse=True)
        for grp_name, grp_ops in self._taraudage_groups.items():
            bases.append((grp_name, grp_ops[0]))

        out = []
        for line in code.split('\n'):
            m = re.match(r'^program (\w+)\s*$', line)
            if m:
                name = m.group(1)
                op = next((o for b, o in bases
                           if name == b or name.startswith(b + '_')),
                          None)
                if op is not None:
                    out.extend(self._subprogram_doc_lines(op, name))
            out.append(line)
        return '\n'.join(out)

    def _subprogram_doc_lines(self, op, sub_name: str) -> List[str]:
        """Commentaires temps/ZMIN et/ou @doc: précédant un
        sous-programme, selon les deux options expert (indépendantes)."""
        lines = []
        if self._expert.get('emit_op_stats', False):
            try:
                from src.core.time_estimator import (
                    estimate_op_seconds, format_duration)
                tool = (self.tool_lib.get_tool(op.tool_id)
                        if op.tool_id else None)
                secs = estimate_op_seconds(op, tool)
                if secs and secs > 0.5:
                    lines.append(
                        f"# Operation Time: {format_duration(secs)}")
            except Exception:
                pass
            zmin = self._op_zmin(op)
            if zmin is not None:
                lines.append(f"# ZMIN = {zmin:g}")
        if self._expert.get('emit_op_doc', False):
            try:
                op_class = self._get_op_class(op)
                display = op_class.DISPLAY_NAME if op_class else ""
            except Exception:
                display = ""
            doc = f"{op.name}"
            if display and display.lower() not in op.name.lower():
                doc += f" - {display}"
            tool = (self.tool_lib.get_tool(op.tool_id)
                    if op.tool_id else None)
            if tool:
                doc += f" - outil {tool.name} [{tool.article_nr}]"
            # SANS ACCENT: l'éditeur machine affiche ces annotations
            # avec un jeu de caractères allemand, où « é » et « — »
            # ressortent en caractères parasites
            lines.append(
                f"@doc: {strip_accents(_sanitize_simpl_string(doc))} @")
        return lines

    @staticmethod
    def _op_zmin(op) -> Optional[float]:
        """Profondeur mini atteinte (Z négatif), None si inconnue."""
        depths = []
        raw = op.params.get('depth')
        try:
            if raw is not None:
                depths.append(abs(float(raw)))
        except (TypeError, ValueError):
            pass
        for pt in (op.points or []):
            d = pt.get('depth')
            try:
                if d is not None:
                    depths.append(abs(float(d)))
            except (TypeError, ValueError):
                continue
        for inst in (op.params.get('instances') or []):
            d = inst.get('depth')
            try:
                if d is not None:
                    depths.append(abs(float(d)))
            except (TypeError, ValueError):
                continue
        return -max(depths) if depths else None

    def _build_neodrive_metadata(self, empreinte: str = "") -> str:
        """Bloc de métadonnées en commentaires (pied de programme):
        sérialisation compressée du programme NeoDrive. Permet de
        recharger un SimPl généré comme projet éditable (opérations
        reconstruites à l'identique, sans heuristique).
        30 LIGNES MAXIMUM: le code des séquences (déjà présent dans
        les blocs $$$ du fichier) est exclu du payload, et la largeur
        des lignes s'adapte pour tenir en ≤28 lignes de données."""
        try:
            # sans les opérations inconnues: la liste reste alignée
            # sur self.program.operations (appariée plus bas)
            pdict = self.program.to_dict(avec_inconnues=False)
            # Déterminisme: created/modified (microsecondes) rendaient
            # le bloc DIFFÉRENT à chaque génération, ce qui forçait le
            # rafraîchissement complet + re-surlignage du panneau code
            # à chaque frappe. Inutiles à la reconstruction.
            pdict.pop('created', None)
            pdict.pop('modified', None)
            # Alléger: sequence_code est déjà dans le bloc $$$ du
            # fichier → référence au nom du bloc à la place
            for op, opd in zip(self.program.operations,
                               pdict.get('operations', [])):
                params = opd.get('params', {})
                if params.get('sequence_code'):
                    params['sequence_code'] = ''
                    params['_seq_from_block'] = self._seq_name_for(op)
            if empreinte:
                from src.io.simpl_importer import CLE_EMPREINTE
                pdict[CLE_EMPREINTE] = empreinte
            from src.io.simpl_importer import lignes_ndmeta
            donnees = lignes_ndmeta(pdict)
        except Exception as err:
            # Sans ce bloc, le programme rouvert perd les réglages de ses
            # opérations: on le DIT (dans le code, et à la fenêtre via
            # `meta_erreur`), au lieu de sortir un fichier amputé en
            # silence.
            self.meta_erreur = f"{type(err).__name__}: {err}"
            return ("# NDMETA ABSENT — réglages des opérations non "
                    f"enregistrés ({self.meta_erreur}): ce programme "
                    "ne se rouvrira pas à l'identique dans NeoDrive")
        lines = ["# === NeoDrive META v1 (ne pas modifier) ==="]
        lines.extend(donnees)
        lines.append("# === fin NeoDrive META ===")
        return "\n".join(lines)

    #: une commande de palpage (CornerMeasure, EdgeMeasureV2,
    #: RectangleMeasure, SurfaceMeasure, « data = SurfaceMeasure »…)
    _MESURE_RE = re.compile(
        r'^\s*(?:[A-Za-z_]\w*\s*=\s*)?[A-Za-z_]\w*Measure\w*\b')

    @classmethod
    def saferapid_de_palpage(cls, lignes, i: int) -> bool:
        """Le SafeRapid de la ligne i approche un PALPEUR: la commande
        qui le suit (hors lignes vides et commentaires) est un palpage.
        Son Z est libre — celui du formulaire —, pas la somme
        strokeRapidZ + strokeCuttingZ des usinages."""
        for ligne in lignes[i + 1:]:
            t = ligne.strip()
            if not t or t.startswith('#'):
                continue
            return bool(cls._MESURE_RE.match(t))
        return False

    @staticmethod
    def verify_stroke_consistency(code: str, expert: dict) -> list:
        """Filet de sécurité anti-collision: vérifie que TOUTES les
        valeurs strokeRapidZ/strokeCuttingZ du code généré (hors
        séquences Datron embarquées) correspondent aux réglages
        machine courants. Retourne la liste des incohérences."""
        srz = int(expert.get('stroke_rapid_z', 15) or 15)
        scz = int(expert.get('stroke_cutting_z', 1) or 1)
        # Exclure les blocs $$$ (séquences: leurs Z sont natifs Datron)
        main_code = code.split('\n$$$', 1)[0]
        issues = set()
        for m in re.finditer(r'strokeRapidZ=(\d+)', main_code):
            if int(m.group(1)) != srz:
                issues.add(
                    f"strokeRapidZ={m.group(1)} ≠ réglage machine {srz}")
        for m in re.finditer(r'strokeCuttingZ=(\d+)', main_code):
            if int(m.group(1)) != scz:
                issues.add(
                    f"strokeCuttingZ={m.group(1)} ≠ réglage machine {scz}")
        # Invariant machine: le Z de dégagement des SafeRapid doit
        # valoir strokeRapidZ + strokeCuttingZ — sauf celui d'un
        # PALPAGE, libre (il approche un palpeur, pas une fraise)
        total = srz + scz
        lignes = main_code.split("\n")
        for i, ligne in enumerate(lignes):
            m = re.search(r'SafeRapid[^\n]*?\bZ=(-?[\d.]+)', ligne)
            if not m or SimPlGenerator.saferapid_de_palpage(lignes, i):
                continue
            try:
                z = float(m.group(1))
            except ValueError:
                continue
            if abs(z - total) > 0.001:
                issues.add(
                    f"SafeRapid Z={m.group(1)} ≠ strokeRapidZ+"
                    f"strokeCuttingZ ({total})")
        return sorted(issues)

    def _apply_machine_limits(self, code: str) -> str:
        """Cappe les RPM et avances au-delà des limites machine.
        rpm_limit (défaut 40000 = Datron), feed_limit (0 = désactivé).
        Appliqué en post-traitement: couvre tous les chemins d'émission
        (outils, rpm_override, aciers BPM, 2e outil...)."""
        rpm_limit = int(self._expert.get('rpm_limit', 40000) or 0)
        feed_limit = int(self._expert.get('feed_limit', 0) or 0)
        if rpm_limit <= 0 and feed_limit <= 0:
            return code

        def _cap_rpm(m):
            return m.group(1) + str(min(int(m.group(2)), rpm_limit))

        def _cap_feed(m):
            return m.group(1) + str(min(int(m.group(2)), feed_limit))

        out = []
        #: dans un « SetFeedTechnology ( » ouvert sur plusieurs lignes
        #: (l'écriture des fichiers Datron): ses avances sont plafonnées
        #: comme celles d'une seule ligne
        feed_ouvert = False
        for ln in code.split("\n"):
            stripped = ln.lstrip()
            if feed_limit > 0 and feed_ouvert:
                if not stripped.startswith("#"):
                    ln = re.sub(
                        r'\b((?:finishing|approach|plunge|ramp|roughing)='
                        r')(\d+)(?!\.)', _cap_feed, ln)
                if ")" in ln:
                    feed_ouvert = False
                out.append(ln)
                continue
            if "SetFeedTechnology" in ln and not stripped.startswith("#"):
                reste = ln.split("SetFeedTechnology", 1)[1]
                feed_ouvert = "(" in reste and ")" not in reste
            if rpm_limit > 0 and (stripped.startswith("Rpm")
                                  or "newRpm" in ln):
                ln = re.sub(r'(\bRpm\s*=\s*)(\d+)', _cap_rpm, ln)
                # « Tool name=… newRpm=40000 » (l'écriture des vrais
                # programmes), « #newRpm= 40000 » (ToolDescription) et
                # « newRpm 40000 »: le motif « newRpm\s+ » ne prenait
                # que le dernier — un bloc importé sortait au-dessus de
                # la limite machine
                ln = re.sub(r'(\bnewRpm\s*=?\s*)(\d+)', _cap_rpm, ln)
            if feed_limit > 0 and "SetFeedTechnology" in ln:
                ln = re.sub(
                    r'\b((?:finishing|approach|plunge|ramp|roughing)=)'
                    r'(\d+)(?!\.)',
                    _cap_feed, ln)
            out.append(ln)
        return "\n".join(out)

    @property
    def _stroke_rapid_z(self) -> int:
        return int(self._expert.get('stroke_rapid_z', 15))

    @property
    def _stroke_cutting_z(self) -> int:
        return int(self._expert.get('stroke_cutting_z', 1))

    @property
    def _safe_z(self) -> float:
        return float(self._expert.get('safe_z_height', 0.5))

    @property
    def _safe_rapid_z(self) -> int:
        """SafeRapid Z = strokeRapidZ + strokeCuttingZ."""
        return self._stroke_rapid_z + self._stroke_cutting_z

    _FEED_KEYS = ('finishing', 'approach', 'plunge', 'ramp', 'roughing')

    def _feed_value(self, op: OperationInstance, tool, key: str,
                    feed_mult: float) -> int:
        """Avance effective: override par opération (valeur absolue,
        prioritaire sur le multiplicateur matériau) sinon outil × mult."""
        try:
            ov = int(float(op.params.get(f'feed_override_{key}', 0)
                           or 0))
        except (TypeError, ValueError):
            ov = 0
        if ov > 0:
            return ov
        base = int(getattr(tool, f'feed_{key}', 0) or 0) if tool else 0
        return int(base * feed_mult) if base else 0

    def _rpm_value(self, op: OperationInstance, tool,
                   rpm_mult: float) -> int:
        """RPM effectif: override par opération sinon outil × mult."""
        try:
            ov = int(float(op.params.get('rpm_override', 0) or 0))
        except (TypeError, ValueError):
            ov = 0
        if ov > 0:
            return ov
        base = int(getattr(tool, 'rpm', 0) or 0)
        return int(base * rpm_mult) if rpm_mult != 1.0 else base

    #: noms que la machine réserve
    _NOMS_RESERVES = ('main',)

    def _noms_pris(self) -> set:
        """Ce qu'un sous-programme ne peut pas s'appeler: les noms des
        séquences (et « Main »), en minuscules — la machine ne
        distingue pas la casse."""
        pris = {n.lower() for n in self._NOMS_RESERVES}
        for nom in getattr(self, '_seq_names', {}).values():
            pris.add(str(nom).lower())
        # les programmes que des lignes du Main reprises appellent
        for op in self.program.operations:
            if op.enabled and op.operation_type == "lignes_main":
                pris |= {str(n).lower() for n in
                         op.params.get('_programmes') or {}}
        return pris

    def _assign_prog_names(self):
        """Assigne des noms simples et uniques aux sous-programmes."""
        self._prog_names.clear()
        used_names = set()
        counter_by_base = {}
        pris = self._noms_pris()

        for op in self.program.operations:
            if not op.enabled:
                continue
            op_class = self._get_op_class(op)
            if not op_class or op_class.INLINE:
                continue

            base = _clean_name(op.name)
            if base not in counter_by_base:
                counter_by_base[base] = 0
            counter_by_base[base] += 1
            count = counter_by_base[base]

            # Si c'est le premier avec ce nom, pas de suffixe
            # On ajoutera le suffixe après avoir vu le total
            candidate = f"{base}_{count}"
            while candidate.lower() in used_names:
                count += 1
                candidate = f"{base}_{count}"
            used_names.add(candidate.lower())
            self._prog_names[op.id] = candidate

        # Simplifier: si un nom n'a qu'une occurrence, retirer le _1
        name_counts = {}
        for name in self._prog_names.values():
            base_part = name.rsplit('_', 1)[0]
            name_counts[base_part] = name_counts.get(base_part, 0) + 1

        simplified = {}
        used_final = set()
        for op_id, name in self._prog_names.items():
            base_part = name.rsplit('_', 1)[0]
            if name_counts[base_part] == 1:
                candidate = base_part
            else:
                candidate = name
            # Garantir l'unicité après simplification (ex: un op nommé
            # "A_1" + deux ops nommés "A" produiraient deux "A_1")
            final = candidate
            if final.lower() in pris:
                # « Gravure_Con_30_0_6 » contre la séquence
                # « GRAVURE_CON_30_0_6 »: la machine refusait
                final = f"{candidate}_Prog"
            k = 2
            while final.lower() in used_final or final.lower() in pris:
                final = f"{candidate}_Prog_{k}" if candidate.lower() \
                    in pris else f"{candidate}_{k}"
                k += 1
            used_final.add(final.lower())
            simplified[op_id] = final
        self._prog_names = simplified

        # Pré-calculer les noms UM_ uniques pour les appel_programme
        self._um_names = {}  # op.id → unique name (à passer en _name)
        from src.operations.appel_programme import AppelProgramme
        seen_labels = {}
        par_fichier = {}    # (label, chemin) → nom déjà donné
        for op in self.program.operations:
            if not op.enabled:
                continue
            if op.operation_type != "appel_programme":
                continue
            base_label = AppelProgramme._build_label(op.name)
            # le même programme rappelé (UM_Date_auto après chaque
            # face): le même label, une seule déclaration
            cle = (base_label, str(op.params.get('filepath', '') or ''))
            if cle in par_fichier:
                self._um_names[op.id] = par_fichier[cle]
                continue
            if base_label in seen_labels:
                seen_labels[base_label] += 1
                unique_name = f"{op.name}_{seen_labels[base_label]}"
            else:
                seen_labels[base_label] = 1
                unique_name = op.name
            self._um_names[op.id] = unique_name
            par_fichier[cle] = unique_name

    def _get_um_name(self, op) -> str:
        """Retourne le nom unique pour un appel_programme."""
        return self._um_names.get(op.id, op.name)

    def _get_prog_name(self, op: OperationInstance) -> str:
        return self._prog_names.get(op.id, _clean_name(op.name))

    def _build_header(self) -> str:
        """Construit l'en-tête du fichier SimPl."""
        s = self.program.settings
        timestamp = datetime.now().strftime("%d%m%Y_%H%M%S")
        lines = [
            f"# File generated by NeoDrive - {timestamp}",
            f"module FunctionKey{self._function_key()}"
            if self._function_key() else "module CamGeneratedModule",
            f'@ MeasuringSystem = "{s.measuring_system}" @',
        ]
        # Commentaire multi-ligne
        comment = _sanitize_simpl_string(s.comment.strip())
        if '\n' in comment:
            for cline in comment.split('\n'):
                lines.append(f'@ Comment = "{cline}" @')
        else:
            lines.append(f'@ Comment = "{comment}" @')
        # Séquences Datron embarquées → flag d'en-tête
        if self._sequence_ops():
            lines.append("@ EmbeddedSequences = true @")
        # Programme bibliothèque: masqué de la liste opérateur de la
        # machine (il est appelé par un autre programme)
        if getattr(s, 'library_module', False):
            lines.append("@ UserVisible = false @")
        lines.append(f'@ Author = "{_sanitize_simpl_string(s.author)}" @')

        # Aperçu du dessin embarqué (@image:) — l'opérateur voit la
        # pièce dans l'éditeur de la machine. Le chemin est RELATIF au
        # programme: le PNG voyage à côté du .SimPl.
        preview = str(self._expert.get('preview_image', '') or '').strip()
        if preview:
            rows = int(self._expert.get('preview_image_rows', 12) or 12)
            lines.append(f"@image: {preview}")
            lines.extend([""] * max(1, min(40, rows)))
            lines.append("@")

        # Déclarations d'outils: la liste que l'opérateur lit devant
        # la machine (magasin), et ce que la machine simule quand la
        # géométrie est donnée. Tous les outils employés, avec ce que
        # leur fiche sait — rien d'inventé pour le reste.
        if self._expert.get('emit_tool_descriptions', True):
            lines.extend(self._tool_description_lines())

        # Dimensions du brut en clair (idiome des fichiers Datron)
        if self._expert.get('emit_workpiece_comments', False):
            lines += [
                "# Workpiece dimensions",
                f"#   min:       X: {s.workpiece_min_x:+.3f}; "
                f"Y: {s.workpiece_min_y:+.3f}; "
                f"Z: {s.workpiece_min_z:+.3f}",
                f"#   max:       X: {s.workpiece_max_x:+.3f}; "
                f"Y: {s.workpiece_max_y:+.3f}; "
                f"Z: {s.workpiece_max_z:+.3f}",
                f"#   Part size  X: "
                f"{s.workpiece_max_x - s.workpiece_min_x:+.3f}; "
                f"Y: {s.workpiece_max_y - s.workpiece_min_y:+.3f}; "
                f"Z: {s.workpiece_max_z - s.workpiece_min_z:+.3f}",
            ]
        lines += [
            f'@ WorkpieceGeometry : '
            f'"MinEdge":{{"X":{s.workpiece_min_x:+.5f},'
            f'"Y":{s.workpiece_min_y:+.5f},'
            f'"Z":{s.workpiece_min_z:+.5f}}}, '
            f'"MaxEdge":{{"X":{s.workpiece_max_x:+.5f},'
            f'"Y":{s.workpiece_max_y:+.5f},'
            f'"Z":{s.workpiece_max_z:+.5f}}} @',
        ]
        return "\n".join(lines)

    def _params_inline(self, op) -> dict:
        """Les paramètres d'une opération INLINE (écrite dans le Main):
        ceux du formulaire, variables substituées, son nom unique
        (appel_programme dédupliqué) et sa POSITION — le palpage coin,
        arête ou U y descend. Un seul chemin, qu'une question
        « Continuer ? » la précède ou non: derrière la question, elle
        perdait X/Y et le palpeur descendait en X0 Y0."""
        params = self._op_params(op)
        params['_name'] = self._get_um_name(op)
        params['_x'] = getattr(op, 'x', 0.0)
        params['_y'] = getattr(op, 'y', 0.0)
        return params

    def _op_params(self, op) -> dict:
        """Paramètres d'une opération, variables opérateur
        substituées.

        `op.params['param_vars'] = {'depth': 'profondeur'}` remplace la
        valeur numérique de `depth` par la VARIABLE `profondeur`: le
        code émet alors `depth=profondeur` au lieu de `depth=5`, et la
        cote devient celle saisie par l'opérateur au lancement.
        Une variable inconnue est ignorée (on garde la valeur
        numérique) — jamais de code faisant référence au vide."""
        params = dict(op.params)
        if op.operation_type == "bloc_simpl":
            # L'appel dans Main doit porter le nom RÉSOLU du bloc
            params['_name'] = self._get_prog_name(op)
        elif op.operation_type == "helice":
            # l'hélice est un mouvement du centre de l'outil: son Ø
            # se compense de celui de la fraise
            params['_diametre_outil'] = self._diametre_outil(op)
        # Gravure: variable texte concaténée (n° de série, saisie...)
        tvar = str(params.get('text_var', '') or '').strip()
        if tvar and tvar in set(self.user_variables()):
            params['_text_var'] = tvar
        mapping = params.get('param_vars') or {}
        if not mapping:
            return params
        available = set(self.user_variables())
        capable = variable_capable_params(op.operation_type)
        for key, var in mapping.items():
            var = str(var or '').strip()
            if var and var in available and key in capable:
                fallback = 0.0
                try:
                    fallback = float(op.params.get(key, 0.0) or 0.0)
                except (TypeError, ValueError):
                    pass
                params[key] = _VarRef(var, fallback)
        return params

    def _function_key(self) -> int:
        """Numéro de touche de fonction (0 = programme normal).

        Un module de touche doit s'appeler EXACTEMENT FunctionKeyN et
        vivre dans Machine/HandheldFunctionKeys."""
        try:
            n = int(self._expert.get('function_key', 0) or 0)
        except (TypeError, ValueError):
            return 0
        return n if 1 <= n <= 12 else 0

    def _user_variable_declarations(self) -> List[str]:
        """Déclarations `nom:type` des variables de saisie opérateur
        (dédoublonnées, dans l'ordre des opérations)."""
        from src.operations.compteur_pieces import CompteurPieces
        from src.operations.parametres_operateur import (
            ParametresOperateur)
        from src.operations.palpage_memorise import PalpageMemorise
        providers = {
            "parametres_operateur": ParametresOperateur,
            "compteur_pieces": CompteurPieces,
            "palpage_memorise": PalpageMemorise,
        }
        out, seen = [], set()
        for op in self.program.operations:
            cls = providers.get(op.operation_type)
            if not op.enabled or cls is None:
                continue
            for var, vtype in cls.declared_variables(op.params):
                if var in seen:
                    continue
                seen.add(var)
                out.append(f"{var}:{vtype}")
        return out

    #: modules déjà importés par l'en-tête commun
    _IMPORTS_COMMUNS = ("System", "DialogUtilities", "Pattern", "Engrave",
                        "DateTimeModule", "MeasuringCommonValues")

    def _imports_des_operations(self) -> List[str]:
        """Les modules que des opérations actives demandent (attribut
        IMPORTS de leur classe, `import` d'un programme importé), hors
        ceux de l'en-tête commun."""
        modules = []
        usings = self._modules_des_imports('using')
        for op in self.program.operations:
            if not op.enabled:
                continue
            classe = self._get_op_class(op)
            for module in getattr(classe, 'IMPORTS', ()) or ():
                if module not in self._IMPORTS_COMMUNS \
                        and module not in modules:
                    modules.append(module)
        for module in self._modules_des_imports('import'):
            if module not in self._IMPORTS_COMMUNS \
                    and module not in modules and module not in usings:
                modules.append(module)
        return modules

    def _modules_des_imports(self, mot: str) -> List[str]:
        """Les modules (`using` ou `import`) que les programmes importés
        en blocs déclaraient en plus des modules communs."""
        modules: List[str] = []
        for op in self.program.operations:
            if not op.enabled or op.operation_type not in (
                    "bloc_simpl", "lignes_main"):
                continue
            for module in ((op.params or {}).get('_modules') or {}).get(
                    mot, ()) or ():
                if module not in modules:
                    modules.append(str(module))
        return modules

    def _ligne_smoothing(self) -> str:
        """« Smoothing On » et ses tolérances (manuel § Smoothing):
        allowedDeviation toujours; les angles seulement s'ils sont
        réglés (0: le défaut de la machine, 0,1 et 110°)."""
        ligne = ("    Smoothing On allowedDeviation="
                 f"{self._expert.get('smoothing_deviation', 0.0025)}")
        for cle, nom in (('smoothing_angle', 'allowedDeviationAngle'),
                         ('smoothing_kink', 'allowedKinkAngle')):
            try:
                v = float(self._expert.get(cle, 0) or 0)
            except (TypeError, ValueError):
                v = 0.0
            if v > 0:
                ligne += f" {nom}={v:g}"
        return ligne

    def _needs_string_module(self) -> bool:
        """`using String` requis par le formatage des numéros de série."""
        for op in self.program.operations:
            if op.enabled and op.operation_type == "compteur_pieces" \
                    and int(op.params.get('digits', 0) or 0) > 0:
                return True
        return False

    def user_variables(self) -> List[str]:
        """Noms des variables opérateur disponibles dans ce programme
        (proposées aux autres opérations)."""
        return [d.split(':', 1)[0]
                for d in self._user_variable_declarations()]

    def _tool_description_lines(self) -> List[str]:
        """Annotations @ ToolDescription @ de TOUS les outils
        employés — géométrie connue ou non —, plus celles réexportées
        depuis les programmes SimPl externes appelés. C'est la liste
        qu'on lit devant la machine pour vérifier le magasin."""
        out = []
        seen = set()
        for tool_id in self.program.get_used_tool_ids():
            tool = self.tool_lib.get_tool(tool_id)
            if not tool:
                continue
            desc = tool.tool_description()
            if desc and tool.article_nr not in seen:
                seen.add(tool.article_nr)
                out.append(desc)
        for entry in self._collect_external_tools():
            article, desc = entry[0], (entry[3] if len(entry) > 3 else "")
            if desc and article not in seen:
                seen.add(article)
                out.append(desc)
        return out

    def _sequence_ops(self) -> List[OperationInstance]:
        """Opérations qui produisent un bloc $$$.

        Séquence Datron et bloc importé portent leur code; le Tracé,
        lui, CALCULE son parcours à la génération."""
        out = []
        for op in self.program.operations:
            if not op.enabled:
                continue
            if op.operation_type in ("trace",) + self.SEQ_CALCULEES:
                out.append(op)
            elif op.operation_type == "ebavurage":
                # un ébavurage de CONTOURS trace sa séquence; un
                # rectangle ou un cercle est une fonction machine
                from src.operations.ebavurage import Ebavurage
                if (Ebavurage.forme(op.params) == "Contours"
                        and Ebavurage.contours(op.params)):
                    out.append(op)
            elif (op.operation_type in ("sequence_datron", "bloc_simpl")
                    and str(op.params.get('sequence_code', '')
                            or '').strip()):
                out.append(op)
        return out

    def _assign_sequence_names(self):
        """Attribue un nom UNIQUE à chaque séquence embarquée: deux
        opérations portant le même sequence_name produiraient deux
        déclarations et deux blocs $$$ homonymes (programme invalide).
        Le nom unique est utilisé partout: déclaration, appel, bloc."""
        self._seq_names = {}
        used = set()
        for op in self._sequence_ops():
            default = self.SEQ_DEFAUTS.get(
                op.operation_type, "SEQUENCE_1")
            base = str(op.params.get(
                'sequence_name', default)).strip() or default
            name = base
            k = 2
            while name.lower() in used \
                    or name.lower() in self._NOMS_RESERVES:
                name = f"{base}_{k}"
                k += 1
            used.add(name.lower())
            self._seq_names[op.id] = name

    def _seq_name_for(self, op: OperationInstance) -> str:
        base = str(op.params.get(
            'sequence_name', 'SEQUENCE_1')).strip() or "SEQUENCE_1"
        return getattr(self, '_seq_names', {}).get(op.id, base)

    def _collect_external_tools(self) -> List[Tuple[str, str, str, str]]:
        """Outils des programmes SimPl externes appelés (Appel Prog Ext).
        Retourne [(article, nom, fichier, tool_description), ...] —
        la déclaration @ ToolDescription @ d'origine est conservée
        pour être réexportée dans l'en-tête généré."""
        result = []
        seen = set()
        # Blocs importés et lignes du Main: leur outil ne vient pas de
        # tools.json, il doit quand même figurer dans la Tool List —
        # c'est elle que l'opérateur lit pour préparer ses outils — et
        # dans les @ ToolDescription @ de l'en-tête: celle du fichier
        # d'origine, sinon celle de tools.json
        from src.io.simpl_batch import TOOL_PRIS_RE
        for op in self.program.operations:
            if not op.enabled or op.operation_type not in (
                    "bloc_simpl", "lignes_main"):
                continue
            p = op.params or {}
            if op.operation_type == "lignes_main":
                body = str(p.get('code', '') or '')
            else:
                try:
                    from src.operations.bloc_simpl import BlocSimpl
                    body = BlocSimpl.body(p)
                except Exception:
                    body = str(p.get('body', '') or '')
            origines = p.get('_descriptions') or {}
            # Un bloc peut employer PLUSIEURS outils (changement en
            # cours de sous-programme): les lister tous
            for kw, declare in TOOL_PRIS_RE.findall(body):
                declare = declare.strip()
                origine = str(origines.get(declare, '') or '')
                known = None
                if self.tool_lib and kw == 'type':
                    known = self.tool_lib.get_tool_by_article(declare)
                elif self.tool_lib:
                    known = next((t for t in self.tool_lib.get_all_tools()
                                  if t.name == declare), None)
                article = declare
                if kw == 'name':
                    ref = re.search(r'"ArticleNr"\s*:\s*"([^"]+)"',
                                    origine)
                    article = (known.article_nr if known is not None
                               and known.article_nr
                               else ref.group(1) if ref else declare)
                if not article or article in seen:
                    continue
                seen.add(article)
                nom = re.search(r'"Name"\s*:\s*"([^"]+)"', origine)
                name = (known.name if known is not None
                        else str(p.get('tool_label', '') or '').strip()
                        or (nom.group(1) if nom else '')
                        or (declare if kw == 'name' else ''))
                decl = origine or (known.tool_description()
                                   if known is not None else "")
                result.append((article, name,
                               str(p.get('source_file', '')
                                   or 'import'), decl))
        for op in self.program.operations:
            if not op.enabled or op.operation_type != "appel_programme":
                continue
            fp = (op.params.get('filepath') or '').strip()
            if not fp:
                continue
            try:
                from src.io.simpl_analyzer import analyze_simpl_file
                # les outils seuls: découper les séquences d'un gros
                # programme figeait chaque régénération du code
                info = analyze_simpl_file(fp, sequences=False)
            except Exception:
                info = None
            if not info:
                continue
            import os as _os
            fname = _os.path.basename(fp)
            descs = info.get('tool_descriptions', {}) or {}
            for article, name in info.get('tools', []):
                if article in seen:
                    continue
                seen.add(article)
                decl = ""
                entry = descs.get(name)
                if entry and entry.get('geometry'):
                    from src.core.tool_library import Tool
                    decl = Tool({
                        'name': name,
                        'reference': entry.get('article', article),
                        'vendor': entry.get('vendor', 'DATRON'),
                        'geometry': entry.get('geometry', {}),
                    }).tool_description(name)
                result.append((article, name, fname, decl))
        return result

    def _build_tool_descriptions(self) -> str:
        """Construit la liste d'outils en commentaires (indentée).
        Inclut les outils des programmes SimPl externes appelés."""
        used_tool_ids = self.program.get_used_tool_ids()
        external_tools = self._collect_external_tools()
        if not used_tool_ids and not external_tools:
            return ""
        lines = [
            "    ###########################################################",
            "    #       Tool List",
            "    ###########################################################",
        ]
        # Matériau sélectionné
        mat_name = self._expert.get('material', '')
        feed_mult = self._expert.get('material_feed_mult', 1.0)
        rpm_mult = self._expert.get('material_rpm_mult', 1.0)
        if mat_name and (feed_mult != 1.0 or rpm_mult != 1.0):
            lines.append(
                f"    # Matériau: {mat_name} "
                f"(feed x{feed_mult:.2f}, rpm x{rpm_mult:.2f})")
        local_articles = set()
        for tool_id in used_tool_ids:
            tool = self.tool_lib.get_tool(tool_id)
            if not tool:
                continue
            article = tool.article_nr
            local_articles.add(article)
            feeds = (
                f"finishing={tool.feed_finishing} "
                f"approach={tool.feed_approach} "
                f"plunge={tool.feed_plunge} "
                f"ramp={tool.feed_ramp} "
                f"roughing={tool.feed_roughing}")
            lines.append(
                f"    # {article:<18s} -   {tool.name:<28s} - {feeds}")
        # Outils des programmes externes (non déjà listés)
        for article, name, fname, _decl in external_tools:
            if article in local_articles:
                continue
            desc = name or "(outil externe)"
            lines.append(
                f"    # {article:<18s} -   {desc:<28s} - via {fname}")
        return "\n".join(lines)

    def _build_imports(self) -> str:
        """Construit le bloc using/import et les déclarations usermodule."""
        lines = []
        # Déclarations des séquences Datron embarquées (avant using)
        seq_ops = self._sequence_ops()
        if seq_ops:
            lines.append("")
            for op in seq_ops:
                lines.append(f"sequence {self._seq_name_for(op)}")
        # les modules qu'un programme importé déclarait en `using`
        # (ses blocs appellent leurs commandes sans préfixe): ceux-là
        # sortent de la ligne `import` commune
        usings = ["Base"] + (["String"] if self._needs_string_module()
                             else []) + self._modules_des_imports('using')
        communs = [m for m in ("System", "DialogUtilities", "Pattern",
                               "Engrave", "DateTimeModule")
                   if m not in usings]
        lines += [
            "",
            "using " + ", ".join(usings),
            "import " + ", ".join(communs),
        ]
        # Le type des mesures persistées vit dans son propre module
        if self._utilise_palpage_memorise():
            lines.append("import MeasuringCommonValues")
        # Les commandes du manuel hors Base (SpecialTool, Vision…)
        en_plus = self._imports_des_operations()
        if en_plus:
            lines.append("import " + ", ".join(en_plus))
        # Variables des saisies opérateur: en SimPl, les variables
        # partagées entre programmes se déclarent au niveau MODULE
        # (hors de tout program), après les using/import.
        decls = self._user_variable_declarations()
        if decls:
            lines.append("")
            lines.append("# Variables du module "
                         "(saisies operateur, mesures retenues)")
            lines.extend(decls)
        # Déclarations usermodule (noms pré-calculés dans _assign_prog_names)
        from src.operations.appel_programme import AppelProgramme
        declares = set()
        for op in self.program.operations:
            if not op.enabled:
                continue
            if op.operation_type == "appel_programme":
                params = dict(op.params)
                params['_name'] = self._get_um_name(op)
                params['filepath'] = self._replace_path(
                    params.get('filepath', ''))
                um_line = AppelProgramme.generate_usermodule_line(params)
                if um_line not in declares:
                    declares.add(um_line)
                    lines.append(um_line)
            elif op.operation_type == "lignes_main":
                # les usermodule que les lignes reprises nomment
                for um_line in op.params.get('_usermodules') or []:
                    if um_line not in declares:
                        declares.add(um_line)
                        lines.append(um_line)
        return "\n".join(lines)

    def _replace_path(self, filepath: str) -> str:
        """Chemin réécrit pour la machine (S:\\… → network:X:\\…).

        Windows ignore la casse et accepte les deux séparateurs: le
        chemin rendu par le sélecteur de fichiers arrive en « / » et
        ne correspondait alors à AUCUN réglage saisi en « \\ », donc
        le chemin local partait tel quel à la machine."""
        if not (filepath and self._path_replace_from
                and self._path_replace_to):
            return filepath

        def normaliser(chemin: str) -> str:
            return chemin.replace('/', '\\').rstrip('\\')

        cible = filepath.replace('/', '\\')
        depart = normaliser(self._path_replace_from)
        arrivee = normaliser(self._path_replace_to)
        if not depart:
            return cible
        position = cible.lower().find(depart.lower())
        if position < 0:
            return cible
        return cible[:position] + arrivee + cible[position + len(depart):]

    def _build_main_program(self) -> str:
        """Construit le bloc export program Main."""
        lines = ["export program Main"]
        # Touche de fonction: annoncer ce que la touche déclenche
        # (idiome des modules FunctionKeyN de la machine)
        fkey = self._function_key()
        if fkey:
            msg = _sanitize_simpl_string(
                self.program.settings.comment.strip().split('\n')[0]
                or "Programme NeoDrive")
            lines += [
                "    Dialog (",
                f'    caption="Touche F{fkey} du pupitre"',
                f'    message="{msg}"',
                "    )",
            ]
        lines.append("    Absolute")

        # Suivi cumulatif des décalages pour commentaires # sum
        _cum_x, _cum_y, _cum_z = 0.0, 0.0, 0.0

        def _append_with_shift_comment(code_lines: list):
            """Ajoute les lignes de code et annote les ShiftWcsInc."""
            nonlocal _cum_x, _cum_y, _cum_z
            for ln in code_lines:
                lines.append(ln)
                stripped = ln.strip()
                if stripped.startswith("ShiftWcsInc"):
                    # Parser les valeurs X=, Y=, Z=
                    mx = re.search(r'X=([-\d.]+)', stripped)
                    my = re.search(r'Y=([-\d.]+)', stripped)
                    mz = re.search(r'Z=([-\d.]+)', stripped)
                    if mx:
                        _cum_x += float(mx.group(1))
                    if my:
                        _cum_y += float(my.group(1))
                    if mz:
                        _cum_z += float(mz.group(1))
                    # Construire le commentaire sum
                    sum_parts = []
                    if _cum_x != 0.0:
                        sum_parts.append(f"X={_cum_x:g}")
                    if _cum_y != 0.0:
                        sum_parts.append(f"Y={_cum_y:g}")
                    if _cum_z != 0.0:
                        sum_parts.append(f"Z={_cum_z:g}")
                    if sum_parts:
                        lines.append(
                            f"    # sum : {' '.join(sum_parts)}")
                    else:
                        lines.append("    # sum : origine")

        _TARAUDAGE_TYPES = {"taraudage_brut"}
        self._taraudage_groups = {}  # group_name → [op, op, ...]
        self._op_in_group = {}  # op.id → group_name (pour skip individuels)

        i = 0
        ops = [op for op in self.program.operations if op.enabled]

        # Phase 0: GROUPES NOMMÉS par l'utilisateur (paramètre
        # « Groupe » du formulaire). Plusieurs groupes coexistent;
        # chaque groupe = un sous-programme, un seul changement
        # d'outil. Prioritaires sur le groupage automatique.
        explicit: Dict[str, list] = {}
        for op in ops:
            gname = str(op.params.get('group_name', '') or '').strip()
            if not gname or op.operation_type not in _GROUPABLE_TYPES:
                continue
            explicit.setdefault(gname, []).append(op)
        for gname, group in explicit.items():
            # Un groupe n'a de sens qu'à outil identique (sinon il
            # faudrait rechanger d'outil dans le sous-programme)
            tools = {o.tool_id for o in group}
            if len(group) < 2 or len(tools) != 1 or not group[0].tool_id:
                continue
            self._taraudage_groups[_clean_name(gname)] = group
            for g_op in group:
                self._op_in_group[g_op.id] = _clean_name(gname)

        # Phase 0 bis: les ENSEMBLES de la liste d'opérations dont
        # tous les membres ont le même outil — un sous-programme pour
        # l'ensemble, un seul changement d'outil, des Rapid entre ses
        # membres au lieu des SafeRapid
        self._ensembles_fusionnes = {}   # nom → [op, op, ...]
        self._op_in_ensemble = {}        # op.id → nom
        par_ensemble: Dict[str, list] = {}
        for op in ops:
            gid = str(getattr(op, 'group_id', '') or '')
            if gid:
                par_ensemble.setdefault(gid, []).append(op)
        pris = {n.lower() for n in self._prog_names.values()} | \
            self._noms_pris() | {n.lower() for n in self._taraudage_groups}
        for gid, membres in par_ensemble.items():
            if len(membres) < 2:
                continue
            if any(m.id in self._op_in_group for m in membres):
                continue
            outils = {m.tool_id for m in membres}
            if len(outils) != 1 or not membres[0].tool_id:
                continue
            if not all(self._fusionnable(m) for m in membres):
                continue
            base = _clean_name(getattr(membres[0], 'group_name', '')
                               or "Ensemble")
            nom, k = base, 2
            while nom.lower() in pris:
                nom = f"{base}_{k}"
                k += 1
            pris.add(nom.lower())
            self._ensembles_fusionnes[nom] = membres
            for m in membres:
                self._op_in_ensemble[m.id] = nom

        # Phase 1: groupage AUTOMATIQUE des taraudages consécutifs de
        # même outil — désactivable (réglage « Groupage automatique »)
        gi = 0
        while gi < len(ops) and self._expert.get('auto_group', True):
            op_gi = ops[gi]
            if op_gi.id in self._op_in_group:
                gi += 1
                continue
            if (op_gi.operation_type in _TARAUDAGE_TYPES and op_gi.tool_id):
                group = [op_gi]
                gj = gi + 1
                while gj < len(ops):
                    next_op = ops[gj]
                    if (next_op.operation_type in _TARAUDAGE_TYPES
                            and next_op.tool_id == op_gi.tool_id
                            and next_op.id not in self._op_in_group):
                        group.append(next_op)
                        gj += 1
                    else:
                        break
                if len(group) >= 2:
                    grp_name = f"Taraudage_Grp_{len(self._taraudage_groups) + 1}"
                    self._taraudage_groups[grp_name] = group
                    for g_op in group:
                        self._op_in_group[g_op.id] = grp_name
                gi = gj
            else:
                gi += 1

        # Phase 2: construction du Main
        #: if de retournement encore ouverts — fermés en fin de Main
        ifs_ouverts = 0
        while i < len(ops):
            op = ops[i]
            op_class = self._get_op_class(op)
            if not op_class:
                i += 1
                continue
            lines.append(MARQUE_OP + op.id)

            # Suite de taraudages consécutifs: émettre TOUS les
            # taraudages puis TOUS les ébavurages, pour ne changer
            # d'outil qu'une fois au lieu d'alterner taraud/ébavureur
            run = self._consecutive_taraudage_run(ops, i)
            if run:
                deferred = []
                for r_op in run:
                    lines.append(MARQUE_OP + r_op.id)
                    self._emit_noninline_calls(
                        r_op, lines, defer_ebav=deferred)
                if deferred:
                    lines.append(
                        "    # ── Ébavurages regroupés "
                        "(un seul changement d'outil) ──")
                    lines.extend(deferred)
                i += len(run)
                continue

            # Taraudage groupé: appeler le sous-programme combiné
            if op.id in self._op_in_group:
                self._emit_noninline_calls(op, lines)
                i += 1
                continue

            if op.operation_type == "retournement_piece":
                if not op.params.get('stop_if_no', True):
                    code = op_class.generate_operation_code(
                        self._params_retournement(op))
                    lines.extend(code.split("\n"))
                    palpage = self._nom_palpage(op)
                    if palpage:
                        lines.append(f"    {palpage}")
                    i += 1
                    continue
                # Tout ce qui suit passe dans le if: répondre Non
                # termine le programme, pièce non retournée
                askfor_name = f"Retournement_{op.id}"
                lines.append(f"    result = {askfor_name}")
                lines.append("    if result == DialogResult.Yes")
                # La pièce est retournée: on reprend son origine et son
                # orientation AVANT de réusiner quoi que ce soit
                palpage = self._nom_palpage(op)
                if palpage:
                    lines.append(f"    {palpage}")
                # Le if reste OUVERT jusqu'à la fin du Main. Il se
                # fermait à la première question suivante: ce qui
                # venait après elle s'usinait même quand l'opérateur
                # avait répondu Non au retournement — sur une pièce
                # qui n'était pas retournée.
                ifs_ouverts += 1
                i += 1
                continue

            if op.operation_type == "dialogue_operateur":
                dialog_type = op.params.get('dialog_type', 'ask_continue')
                if dialog_type == "info_only":
                    code = op_class.generate_operation_code(op.params)
                    for line in code.split("\n"):
                        lines.append(line)
                else:
                    askfor_name = f"AskFor_{op.id}"
                    lines.append(f"    result = {askfor_name}")
                    lines.append("    if result == DialogResult.Yes")
                    j = i + 1
                    while j < len(ops):
                        next_op = ops[j]
                        next_class = self._get_op_class(next_op)
                        if next_op.operation_type in (
                                "dialogue_operateur",
                                "retournement_piece"):
                            break
                        lines.append(MARQUE_OP + next_op.id)
                        if next_class and next_class.INLINE:
                            np = self._params_inline(next_op)
                            code = next_class.generate_operation_code(np)
                            _append_with_shift_comment(code.split("\n"))
                        elif next_class:
                            # Émettre les mêmes appels que dans le Main
                            # (per-point, multi-outil, groupe, pattern...)
                            self._emit_noninline_calls(next_op, lines)
                        j += 1
                    lines.append("    endif")
                    i = j
                    continue
            elif op_class.INLINE:
                inline_params = self._params_inline(op)
                code = op_class.generate_operation_code(inline_params)
                _append_with_shift_comment(code.split("\n"))

                # ShiftWcsInc: pas de retour auto (l'utilisateur crée une opération retour)
            else:
                self._emit_noninline_calls(op, lines)

            i += 1

        lines.append(MARQUE_OP + FIN_OPS)
        # La mesure retenue n'a plus lieu d'être une fois la pièce
        # usinée: c'est le « clean » de la documentation machine
        lines.extend(self._lignes_oubli_palpage())
        # Fin de Main: on referme les if des retournements — c'est là
        # que s'arrête ce qui dépend de la pièce retournée
        lines.extend(["    endif"] * ifs_ouverts)
        lines.extend([
            "    SpraySystem Off",
            "    Spindle Off",
            "    MoveToParkPosition",
            "endprogram",
        ])
        return "\n".join(lines)

    #: opérations dont le parcours est CALCULÉ puis sorti en bloc
    #: $$$ — comme le fait TypeEdit avec son post-processeur
    SEQ_CALCULEES = ("gravure_2d5", "evidement_2d5",
                     "contour_2d5", "texte_grave")

    #: nom de séquence par défaut, par type d'opération
    SEQ_DEFAUTS = {
        "trace": "TRACE_1",
        "gravure_2d5": "GRAVURE_1",
        "evidement_2d5": "EVIDEMENT_1",
        "contour_2d5": "CONTOUR_1",
        "texte_grave": "TEXTE_1", "ebavurage": "EBAVURAGE_1",
    }

    # Types dont les ébavurages consécutifs sont regroupés dans Main
    _EBAV_RUN_TYPES = ("taraudage", "taraudage_brut")

    def _consecutive_taraudage_run(self, ops: list, start: int) -> list:
        """Suite d'au moins 2 taraudages consécutifs dont au moins un
        a un ébavurage (sinon aucun intérêt à différer)."""
        run = []
        j = start
        while (j < len(ops)
               and ops[j].operation_type in self._EBAV_RUN_TYPES):
            run.append(ops[j])
            j += 1
        if len(run) < 2 or not any(self._needs_ebavurage(o) for o in run):
            return []
        return run

    def _emit_noninline_calls(self, op: OperationInstance, lines: list,
                              defer_ebav: Optional[list] = None):
        """Émet dans Main les appels pour une opération non-inline.
        Gère: groupe taraudage, multi-outil, per-point, pattern, simple,
        et l'appel ébavurage associé. Utilisé par le corps du Main ET par
        le bloc conditionnel des dialogues opérateur.
        defer_ebav: si fourni, les appels d'ébavurage y sont accumulés
        au lieu d'être émis tout de suite (regroupement des outils)."""
        ebav_out = defer_ebav if defer_ebav is not None else lines
        nom_ensemble = getattr(self, '_op_in_ensemble', {}).get(op.id)
        if nom_ensemble:
            membres = self._ensembles_fusionnes[nom_ensemble]
            # un seul appel, au premier membre
            if op.id == membres[0].id:
                lines.append(
                    f"    {nom_ensemble}    # {len(membres)} opérations "
                    "de l'ensemble, même outil")
            return
        if op.operation_type == "palpage_memorise":
            lines.append(f"    {self._nom_palpage_memorise(op)}")
            return
        if op.operation_type == "bloc_simpl" and not str(
                op.params.get('body', '') or '').strip():
            # un bloc sans corps n'a pas de sous-programme: l'appeler
            # arrêterait la machine sur un nom inconnu
            lines.append(f"    # {op.name}: bloc vide, rien à appeler")
            return
        if op.operation_type == "palpage_rectangle":
            lines.append(f"    {self._nom_palpage_rect(op)}")
            return
        if op.id in self._op_in_group:
            grp_name = self._op_in_group[op.id]
            grp_ops = self._taraudage_groups[grp_name]
            # N'émettre l'appel que pour le premier op du groupe
            if op.id == grp_ops[0].id:
                lines.append(
                    f"    {grp_name}    # {len(grp_ops)} opérations "
                    "groupées (1 seul changement d'outil)")
                # Ébavurage pour chaque op du groupe
                for g_op in grp_ops:
                    if self._needs_ebavurage(g_op):
                        ebav_name = self._get_prog_name(g_op) + "_ebav"
                        ebav_out.append(MARQUE_OP + g_op.id)
                        ebav_out.append(f"    {ebav_name}")
            return

        prog_name = self._get_prog_name(op)

        # Sous-programmes groupés (taraudage par type / perçage même outil)
        multi_subs = self._build_multi_tool_subprograms(op)
        if multi_subs:
            # Appels exacts calculés par le constructeur des
            # sous-programmes: sous-prog de base (s'il reste des
            # points hors pattern) puis les Pattern::RectanglePattern,
            # qui sont TOUJOURS émis dans Main
            lines.extend(self._taraudage_main_calls.get(op.id, []))
        elif op.operation_type in _PER_POINT_PATTERN_OPS and op.points:
            # Chaque point → son propre sous-programme _pt{i}
            for pi, pt in enumerate(op.points):
                pt_sub = f"{prog_name}_pt{pi}"
                if pt.get('use_pattern', False):
                    # Point pattern → RectanglePattern dans Main
                    lines.append(
                        f"    Pattern::RectanglePattern ("
                        f"xCount={pt.get('x_count', 1)} "
                        f"yCount={pt.get('y_count', 1)} "
                        f"deltaX={pt.get('delta_x', 10.0)} "
                        f"deltaY={pt.get('delta_y', 10.0)} "
                        f"callProgram={pt_sub})")
                else:
                    # Point isolé → appel direct
                    lines.append(f"    {pt_sub}")
        else:
            # Pattern: Main appelle le Pattern approprié
            if op.params.get('use_pattern'):
                lines.append(self._build_pattern_call(
                    op.params, prog_name,
                    pivot=(op.x, op.y)))
            elif op.operation_type == "bloc_simpl":
                # un bloc importé que le Main appelait par un motif
                from src.operations.bloc_simpl import BlocSimpl
                lines.append(BlocSimpl.appel_main(op.params, prog_name))
            else:
                lines.append(f"    {prog_name}")

        # Fraisage de tête: juste après le perçage, avant l'ébavurage
        if self._needs_head_milling(op):
            nom_tete = self._get_prog_name(op) + "_tete"
            if op.params.get('use_pattern'):
                lines.append(self._build_pattern_call(
                    op.params, nom_tete,
                    pivot=(op.x, op.y)))
            else:
                lines.append(f"    {nom_tete}")

        # Ébavurage: appel dans Main juste après l'opération
        # Si Pattern actif, ébavurage aussi avec le même Pattern
        if self._needs_ebavurage(op):
            ebav_name = prog_name + "_ebav"
            ebav_out.append(MARQUE_OP + op.id)
            if op.params.get('use_pattern'):
                ebav_out.append(self._build_pattern_call(
                    op.params, ebav_name,
                    pivot=(op.x, op.y)))
            else:
                ebav_out.append(f"    {ebav_name}")

    #: les lignes d'en-tête d'un sous-programme (avant son corps)
    _ENTETES_SOUS_PROG = ("program ", "BeginBlock", "SafeZHeightForWorkpiece",
                          "Coolant", "SpraySystem On", "Tool type=",
                          "Rpm =", "Spindle On", "Smoothing On", "Dynamic=",
                          "SetFeedTechnology")
    #: ce qui ne se fusionne pas: plusieurs outils (taraudage par filet,
    #: BPM), des appels en plus dans Main (motifs, ébavurage, tête),
    #: des émissions à part
    _NON_FUSIONNABLES = ("taraudage", "taraudage_brut", "bpm", "bloc_simpl",
                         "appel_programme", "import_programme",
                         "palpage_memorise", "palpage_rectangle",
                         "gamme_gravure", "retournement_piece",
                         "dialogue_operateur")

    def _fusionnable(self, op) -> bool:
        """Une opération peut-elle entrer dans le sous-programme de son
        ensemble? (un outil, un corps simple, rien d'autre dans Main)"""
        op_class = self._get_op_class(op)
        if not op_class or op_class.INLINE:
            return False
        if op.operation_type in self._NON_FUSIONNABLES:
            return False
        if op.params.get('use_pattern'):
            return False
        if any(pt.get('use_pattern') for pt in (op.points or [])):
            return False
        if self._needs_head_milling(op) or self._needs_ebavurage(op):
            return False
        return True

    def _build_ensemble_sub(self, nom: str, membres: list) -> str:
        """Le sous-programme d'un ensemble d'un même outil: l'en-tête du
        premier (outil, broche, avances), puis le corps de chaque
        membre — ses Rpm et SetFeedTechnology quand ils changent —, des
        Rapid entre eux (l'outil est rétracté au bout de chaque cycle)."""
        entete, corps_total = [], []
        courant = {}
        for k, op in enumerate(membres):
            lignes = self._build_subprogram(op).split("\n")
            tete, corps = [], []
            dans_tete = True
            for ln in lignes:
                st = ln.strip()
                if st in ("EndBlock", "endprogram"):
                    continue
                if dans_tete and st.startswith(self._ENTETES_SOUS_PROG):
                    tete.append(ln)
                    continue
                dans_tete = False
                corps.append(ln)
            reglages = {p: next((x for x in tete
                                 if x.strip().startswith(p)), None)
                        for p in ("Rpm =", "SetFeedTechnology")}
            if k == 0:
                entete = [f"program {nom}", f'    BeginBlock name="{nom}"']
                entete += [x for x in tete if not x.strip().startswith(
                    ("program ", "BeginBlock"))]
                courant = dict(reglages)
            else:
                for prefixe, ligne in reglages.items():
                    if ligne is not None and ligne != courant.get(prefixe):
                        corps_total.append(ligne)
                        courant[prefixe] = ligne
            corps_total.append(MARQUE_OP + op.id)
            corps_total.append(f"    # --- {op.name} ---")
            corps_total += corps
        lignes = entete + corps_total + ["    EndBlock", "endprogram"]
        return self._demote_extra_saferapids("\n".join(lignes))

    def _build_grouped_taraudage_sub(self, grp_name: str,
                                     grp_ops: list) -> str:
        """Construit un sous-programme combiné pour taraudages consécutifs.
        Un seul Tool/Rpm/SpraySystem, puis tous les corps en séquence."""
        first_op = grp_ops[0]
        tool = self.tool_lib.get_tool(first_op.tool_id) if first_op.tool_id else None
        rpm_mult = self._expert.get('material_rpm_mult', 1.0)

        lines = [f"program {grp_name}"]
        lines.append(f'    BeginBlock name="{grp_name}"')
        lines.append(f"    SafeZHeightForWorkpiece={self._safe_z}")

        if tool:
            coolant = tool.coolant
            if coolant == "flood":
                lines.append("    Coolant Alcohol")
        lines.append("    SpraySystem On")

        if tool:
            rpm = self._rpm_value(first_op, tool, rpm_mult)
            lines.append(
                f'    Tool type="{tool.article_nr}"  skipRestoring'
                f"    #{tool.name}")
            lines.append(f"    Rpm = {rpm}")

        lines.append("    Spindle On")

        # Smoothing / Dynamic
        if self._expert.get('smoothing', False):
            lines.append(self._ligne_smoothing())
        dynamic_val = self._expert.get('dynamic', 0)
        if dynamic_val and int(dynamic_val) > 0:
            lines.append(f"    Dynamic={int(dynamic_val)}")

        # SetFeedTechnology (overrides du 1er op du groupe)
        feed_mult = self._expert.get('material_feed_mult', 1.0)
        if tool:
            feed_parts = []
            for key in self._FEED_KEYS:
                fv = self._feed_value(first_op, tool, key, feed_mult)
                if fv:
                    feed_parts.append(f"{key}={fv}")
            if feed_parts:
                lines.append(
                    f"    SetFeedTechnology ({' '.join(feed_parts)})")

        # Corps: chaque opération en séquence
        for idx, op in enumerate(grp_ops):
            op_class = self._get_op_class(op)
            if not op_class:
                continue
            lines.append(MARQUE_OP + op.id)
            lines.append(f"    # --- {op.name} ---")
            default_params = self._op_params(op)
            default_params['_stroke_rapid_z'] = self._stroke_rapid_z
            default_params['_stroke_cutting_z'] = self._stroke_cutting_z
            default_params['_op_x'] = op.x
            default_params['_op_y'] = op.y
            default_params['_safe_rapid_z'] = self._safe_rapid_z
            # Opérations multi-points: parcourir TOUS les points
            # (le corps ne traitait que op.x/op.y, ce qui perdait
            # les points et les types de filet des taraudages)
            pts = list(op.points) if getattr(op, 'points', None) \
                else [{'x': op.x, 'y': op.y}]
            body = []
            for pt in pts:
                pt_params = dict(default_params)
                if op.operation_type == "taraudage":
                    pt_params['thread_name'] = pt.get(
                        'thread_type', 'M3')
                pt_depth = pt.get('depth')
                if pt_depth is not None:
                    pt_params['depth'] = pt_depth
                body.append(
                    f"    SafeRapid X={pt.get('x', op.x):.3f} "
                    f"Y={pt.get('y', op.y):.3f} Z={self._safe_rapid_z}")
                body.extend(op_class.generate_operation_code(
                    pt_params).split("\n"))
            # Répétition propre à chaque opération du groupe
            lines.extend(self._wrap_instance_repeat(
                body, default_params, op.x, op.y))

        lines.append("    SpraySystem Off")
        lines.append("    Spindle Off")
        # EndBlock SANS name= : la commande n'accepte pas d'argument
        # (la machine refusait le programme)
        lines.append("    EndBlock")
        lines.append("endprogram")
        return self._demote_extra_saferapids("\n".join(lines))

    def _build_pattern_call(self, params: dict, call_program: str,
                            indent: str = "    ",
                            pivot=(0.0, 0.0)) -> str:
        """Génère l'appel Pattern selon le type (Rectangle, Circle, Linear).
        callProgram SANS guillemets — référence directe au sous-programme.
        `pivot`: le point de l'opération, autour duquel tourne un motif
        linéaire en biais."""
        pat_type = params.get('pattern_type', 'Rectangle')
        if pat_type == "Circle":
            # manuel SimPL 3.1.1 § 5.8.5.1: CircularPattern radius=
            # elements= startAngle= callProgram= (le « CirclePattern
            # count= » d'avant n'existe pas)
            return (
                f"{indent}Pattern::CircularPattern ("
                f"radius={float(params.get('circle_radius', 20.0)):g} "
                f"elements={int(params.get('circle_count', 6))} "
                f"startAngle={float(params.get('circle_start_angle', 0.0)):g} "
                f"callProgram={call_program})")
        elif pat_type == "Linear":
            # pas de motif linéaire dans le manuel: un RectanglePattern
            # d'une rangée, en biais grâce au repère local
            n = int(params.get('linear_count', 4))
            d = float(params.get('linear_delta', 10.0))
            a = float(params.get('linear_angle', 0.0)) % 360.0
            if abs(a - 90.0) < 1e-9:
                return (f"{indent}Pattern::RectanglePattern ("
                        f"xCount=1 yCount={n} deltaX=0 deltaY={d:g} "
                        f"callProgram={call_program})")
            appel = (f"{indent}Pattern::RectanglePattern ("
                     f"xCount={n} yCount=1 deltaX={d:g} deltaY=0 "
                     f"callProgram={call_program})")
            if abs(a) < 1e-9:
                return appel
            # RotateLcsInc tourne le repère autour de son ORIGINE: le
            # premier élément partait en R(a)·(x, y) — à 180°, en
            # (-x, -y), hors de la pièce. On tourne autour du POINT de
            # l'opération (celui de l'aperçu): s'y placer, tourner,
            # revenir dans le repère tourné; puis l'inverse exact.
            px, py = (float(v or 0.0) for v in pivot)
            if abs(px) < 1e-9 and abs(py) < 1e-9:
                return (f"{indent}RotateLcsInc gamma={a:g}\n{appel}\n"
                        f"{indent}RotateLcsInc gamma={-a:g}")
            aller = f"{indent}ShiftLcsInc X={px:g} Y={py:g} Z=0"
            retour = f"{indent}ShiftLcsInc X={-px:g} Y={-py:g} Z=0"
            return "\n".join([
                aller, f"{indent}RotateLcsInc gamma={a:g}", retour,
                appel,
                aller, f"{indent}RotateLcsInc gamma={-a:g}", retour])
        else:
            return (
                f"{indent}Pattern::RectanglePattern ("
                f"xCount={params.get('x_count', 1)} "
                f"yCount={params.get('y_count', 1)} "
                f"deltaX={params.get('delta_x', 10.0)} "
                f"deltaY={params.get('delta_y', 10.0)} "
                f"callProgram={call_program})")

    def _op_hash(self, op: OperationInstance) -> int:
        """Calcule un hash des données d'opération pour le cache.

        Le NOM RÉSOLU du sous-programme doit en faire partie: il
        dépend des AUTRES opérations du programme (dédoublonnage), pas
        seulement de celle-ci. Sans lui, dupliquer une opération
        laissait le cache renvoyer l'ancien code (« program Dec »)
        alors que Main appelait désormais « Dec_1 »."""
        key = f"{op.id}|{op.name}|{op.tool_id}|{op.x}|{op.y}|{op.z}"
        key += f"|{sorted(op.params.items())}|{op.points}"
        key += f"|{self._expert}|{self._get_prog_name(op)}"
        return hash(key)

    def _build_subprogram_cached(self, op: OperationInstance) -> str:
        """Version cachée de _build_subprogram."""
        h = self._op_hash(op)
        cached = SimPlGenerator._subprogram_cache.get(op.id)
        if cached and cached[0] == h:
            return cached[1]
        code = self._build_subprogram(op)
        # Borner le cache (classe partagée entre programmes/onglets)
        if len(SimPlGenerator._subprogram_cache) >= 512:
            SimPlGenerator._subprogram_cache.clear()
        SimPlGenerator._subprogram_cache[op.id] = (h, code)
        return code

    # Opérations supportant les instances multiples dans un même
    # sous-programme, et clé de finition correspondante
    _INSTANCE_OP_TYPES = ("poche_rectangle", "decoupe_rectangle",
                          "surfacage_rectangle")
    _INSTANCE_FINISH_KEY = {
        "poche_rectangle": "finishing_xy",
        "decoupe_rectangle": "finishing_xy",
        "surfacage_rectangle": "finishing_z",
    }

    def _wrap_instance_repeat(self, body_lines: list, params: dict,
                              x: float, y: float) -> list:
        """Applique la grille de répétition (deux niveaux) d'UNE
        instance à son corps (SafeRapid + code opération)."""
        from src.core import repetition
        return repetition.emettre(body_lines, params)

    def _emit_op_instances(self, op, op_class, default_params: dict,
                           instances: list) -> list:
        """Émet l'instance principale (formulaire de l'opération) puis
        chaque instance similaire, dans le MÊME sous-programme (outil/
        Rpm/avances partagés). Le 1er déplacement reste SafeRapid, les
        suivants sont rétrogradés en Rapid par _demote_extra_saferapids."""
        finish_key = self._INSTANCE_FINISH_KEY.get(
            op.operation_type, 'finishing_xy')
        out = []
        main_body = [
            f"    SafeRapid X={op.x:.3f} Y={op.y:.3f}"
            f" Z={self._safe_rapid_z}",
            op_class.generate_operation_code(default_params),
        ]
        out.extend(self._wrap_instance_repeat(
            main_body, default_params, op.x, op.y))
        for n, inst in enumerate(instances, start=2):
            params = dict(default_params)
            # Répétition NON héritée de l'instance principale
            for k in ('repeat_x_count', 'repeat_x_step',
                      'repeat_y_count', 'repeat_y_step',
                      'repeat2_x_count', 'repeat2_x_step',
                      'repeat2_y_count', 'repeat2_y_step',
                      'repeat_count', 'repeat_shift_x',
                      'repeat_shift_y'):
                params.pop(k, None)
            for k in ('width_x', 'width_y', 'corner_radius', 'depth',
                      'repeat_x_count', 'repeat_x_step',
                      'repeat_y_count', 'repeat_y_step',
                      'repeat2_x_count', 'repeat2_x_step',
                      'repeat2_y_count', 'repeat2_y_step'):
                if inst.get(k) is not None:
                    params[k] = inst[k]
            if inst.get('finishing') is not None:
                params[finish_key] = inst['finishing']
            ix = float(inst.get('pos_x', op.x))
            iy = float(inst.get('pos_y', op.y))
            out.append(f"    # ── Instance {n}: X{ix:g} Y{iy:g} ──")
            body = [
                f"    SafeRapid X={ix:.3f} Y={iy:.3f}"
                f" Z={self._safe_rapid_z}",
                op_class.generate_operation_code(params),
            ]
            out.extend(self._wrap_instance_repeat(body, params, ix, iy))
        return out

    def _build_subprogram(self, op: OperationInstance) -> str:
        """Construit un sous-programme pour une opération non-inline."""
        op_class = self._get_op_class(op)
        if not op_class:
            return f"# Erreur: opération inconnue {op.operation_type}"

        prog_name = self._get_prog_name(op)
        tool = self.tool_lib.get_tool(op.tool_id) if op.tool_id else None

        lines = [f"program {prog_name}"]
        lines.append(f'    BeginBlock name="{prog_name}"')
        lines.append(f"    SafeZHeightForWorkpiece={self._safe_z}")

        # SpraySystem On — TOUJOURS présent
        if tool:
            coolant = tool.coolant
            if coolant == "flood":
                lines.append("    Coolant Alcohol")
        lines.append("    SpraySystem On")

        # Outil (si sélectionné)
        rpm_mult = self._expert.get('material_rpm_mult', 1.0)
        feed_mult = self._expert.get('material_feed_mult', 1.0)
        if tool:
            rpm = self._rpm_value(op, tool, rpm_mult)
            lines.append(f'    Tool type="{tool.article_nr}"  skipRestoring    #{tool.name}')
            lines.append(f"    Rpm = {rpm}")

        # Position SafeRapid déplacée dans le corps (pour support repeat)

        # Spindle On — TOUJOURS présent
        lines.append("    Spindle On")

        # Smoothing / Dynamic (expert)
        if self._expert.get('smoothing', False):
            lines.append(self._ligne_smoothing())
        dynamic_val = self._expert.get('dynamic', 0)
        if dynamic_val and int(dynamic_val) > 0:
            lines.append(f"    Dynamic={int(dynamic_val)}")

        # SetFeedTechnology (si outil)
        # BPM modes acier: utiliser les steel_* params au lieu des feeds outil
        bpm_mode = op.params.get('bpm_mode', '') if op.operation_type == "bpm" else ''
        use_steel = bpm_mode in ("Perçage Simple", "Foret + Taraudage")
        if use_steel:
            steel_parts = []
            sp = op.params
            if sp.get('steel_finishing'):
                steel_parts.append(f"finishing={sp['steel_finishing']}")
            if sp.get('steel_approach'):
                steel_parts.append(f"approach={sp['steel_approach']}")
            if sp.get('steel_plunge'):
                steel_parts.append(f"plunge={sp['steel_plunge']}")
            if sp.get('steel_ramp'):
                steel_parts.append(f"ramp={sp['steel_ramp']}")
            if sp.get('steel_roughing'):
                steel_parts.append(f"roughing={sp['steel_roughing']}")
            if steel_parts:
                lines.append(
                    f"    SetFeedTechnology ({' '.join(steel_parts)})")
            # Override RPM si steel_rpm défini
            steel_rpm = sp.get('steel_rpm')
            if steel_rpm and tool:
                # Remplacer la ligne Rpm déjà émise
                for idx, ln in enumerate(lines):
                    if ln.strip().startswith("Rpm ="):
                        lines[idx] = f"    Rpm = {steel_rpm}"
                        break
        elif tool:
            feed_parts = []
            fm = feed_mult
            # Surfaçage Pz<=0.2 : pas de finishing, valeur finishing → roughing
            is_surf_shallow = (
                op.operation_type in ("surfacage_rectangle", "surfacage_cercle")
                and float(op.params.get('depth', 1)) <= 0.2)
            finishing_val = self._feed_value(op, tool, 'finishing', fm)
            roughing_val = self._feed_value(op, tool, 'roughing', fm)
            if is_surf_shallow:
                # Pas de finishing ; roughing = max(roughing, finishing)
                if roughing_val or finishing_val:
                    feed_parts.append(
                        f"roughing={max(roughing_val, finishing_val)}")
            else:
                if finishing_val:
                    feed_parts.append(f"finishing={finishing_val}")
            for key in ('approach', 'plunge', 'ramp'):
                fv = self._feed_value(op, tool, key, fm)
                if fv:
                    feed_parts.append(f"{key}={fv}")
            if not is_surf_shallow and roughing_val:
                feed_parts.append(f"roughing={roughing_val}")
            if feed_parts:
                lines.append(
                    f"    SetFeedTechnology ({' '.join(feed_parts)})")

        # Code de l'opération — injecter les params expert (strokeRapid/Cutting)
        default_params = self._op_params(op)
        default_params['_stroke_rapid_z'] = self._stroke_rapid_z
        default_params['_stroke_cutting_z'] = self._stroke_cutting_z
        default_params['_op_x'] = op.x
        default_params['_op_y'] = op.y
        default_params['_safe_rapid_z'] = self._safe_rapid_z
        # Séquence Datron et Tracé: nom unique cohérent avec la
        # déclaration et le bloc $$$
        if op.operation_type in (("sequence_datron", "trace", "ebavurage")
                                 + self.SEQ_CALCULEES):
            default_params['sequence_name'] = self._seq_name_for(op)
        use_pattern = default_params.get('use_pattern', False)

        # BPM: injecter les infos du 2e outil (taraudage) dans les params
        if op.operation_type == "bpm":
            tool2_id = default_params.get('bpm_tool2_id', '')
            if tool2_id:
                tool2 = self.tool_lib.get_tool(tool2_id)
                if tool2:
                    default_params['_tool2_article'] = tool2.article_nr
                    default_params['_tool2_name'] = tool2.name
                    default_params['_tool2_rpm'] = tool2.rpm
                    feed_parts = []
                    if tool2.feed_finishing:
                        feed_parts.append(
                            f"finishing={tool2.feed_finishing}")
                    if tool2.feed_approach:
                        feed_parts.append(
                            f"approach={tool2.feed_approach}")
                    if tool2.feed_plunge:
                        feed_parts.append(
                            f"plunge={tool2.feed_plunge}")
                    if tool2.feed_ramp:
                        feed_parts.append(
                            f"ramp={tool2.feed_ramp}")
                    if tool2.feed_roughing:
                        feed_parts.append(
                            f"roughing={tool2.feed_roughing}")
                    default_params['_tool2_feeds'] = ' '.join(feed_parts)

        # ── Instances similaires dans le même sous-programme ──
        # (poches/découpes/surfaçages rectangle: chaque instance a sa
        # Position/Dimension/rayon/Pz/finition/répétition propre)
        instances = default_params.get('instances') or []
        if op.operation_type in self._INSTANCE_OP_TYPES and instances:
            lines.extend(self._emit_op_instances(
                op, op_class, default_params, instances))
            lines.append("    EndBlock")
            lines.append("endprogram")
            return self._demote_extra_saferapids("\n".join(lines))

        # ── Marqueur début du corps (pour support repeat) ──
        _body_start = len(lines)
        _is_single = not (hasattr(op, 'points') and op.points)

        # SafeRapid pour opérations single-point (avant le code opération)
        if _is_single and op_class.REQUIRES_COORDINATES:
            lines.append(
                f"    SafeRapid X={op.x:.3f} Y={op.y:.3f}"
                f" Z={self._safe_rapid_z}")

        if use_pattern:
            # Pattern: le sous-programme s'exécute au point de base
            # (coordonnées les plus faibles). Pattern gère la répétition.
            lines.append(
                op_class.generate_operation_code(default_params))
        elif op.operation_type == "bpm" and float(default_params.get('entraxe', 0)) > 0:
            # BPM Entraxe: calculer 2 centres symétriques depuis le centre op
            entraxe = float(default_params.get('entraxe', 20.0))
            axis = default_params.get('entraxe_axis', 'X')
            half = entraxe / 2.0
            if axis == 'X':
                pts = [
                    {'x': op.x - half, 'y': op.y},
                    {'x': op.x + half, 'y': op.y},
                ]
            else:
                pts = [
                    {'x': op.x, 'y': op.y - half},
                    {'x': op.x, 'y': op.y + half},
                ]
            lines.append(
                f"    # Entraxe {entraxe:.1f} mm sur axe {axis}")
            if BPMOperation.is_dual_tool(default_params):
                # Groupé: pass 1 tous les points, changement, pass 2
                for pt in pts:
                    lines.append(
                        f"    SafeRapid X={pt['x']:.3f} "
                        f"Y={pt['y']:.3f} Z={self._safe_rapid_z}")
                    lines.append(
                        BPMOperation.generate_tool1_code(default_params))
                tool2_hdr = BPMOperation.generate_tool2_header(
                    default_params)
                if tool2_hdr:
                    lines.append(tool2_hdr)
                for pt in pts:
                    lines.append(
                        f"    SafeRapid X={pt['x']:.3f} "
                        f"Y={pt['y']:.3f} Z={self._safe_rapid_z}")
                    lines.append(
                        BPMOperation.generate_tool2_code(default_params))
            else:
                for pt in pts:
                    lines.append(
                        f"    SafeRapid X={pt['x']:.3f} "
                        f"Y={pt['y']:.3f} Z={self._safe_rapid_z}")
                    lines.append(
                        op_class.generate_operation_code(default_params))
        elif (op.operation_type == "bpm"
              and BPMOperation.is_dual_tool(default_params)
              and hasattr(op, 'points') and op.points):
            # BPM dual-tool groupé: tous les Outil1, puis changement, puis tous les Outil2
            lines.append("    # ── Pass 1: Outil principal ──")
            for pt in op.points:
                lines.append(
                    f"    SafeRapid X={pt['x']:.3f} "
                    f"Y={pt['y']:.3f} Z={self._safe_rapid_z}")
                lines.append(
                    BPMOperation.generate_tool1_code(default_params))
            # Changement vers outil 2
            tool2_hdr = BPMOperation.generate_tool2_header(default_params)
            if tool2_hdr:
                lines.append("    # ── Changement outil taraudage ──")
                lines.append(tool2_hdr)
            # Pass 2: taraudage sur tous les points
            lines.append("    # ── Pass 2: Taraudage ──")
            for pt in op.points:
                lines.append(
                    f"    SafeRapid X={pt['x']:.3f} "
                    f"Y={pt['y']:.3f} Z={self._safe_rapid_z}")
                lines.append(
                    BPMOperation.generate_tool2_code(default_params))
        elif hasattr(op, 'points') and op.points:
            # Multi-point: boucle SafeRapid + opération pour chaque point
            for pt in op.points:
                # Pz=0 workaround: Datron refuse d'usiner à Pz=0.
                # La profondeur effective est passée via pt_params,
                # SANS modifier le point du modèle.
                pt_depth = pt.get('depth')
                pz_zero_workaround = (
                    pt_depth is not None and float(pt_depth) == 0.0)
                effective_depth = 0.1 if pz_zero_workaround else pt_depth
                if pz_zero_workaround:
                    lines.append("    ShiftWcsInc Z=0.1")

                lines.append(
                    f"    SafeRapid X={pt['x']:.3f} Y={pt['y']:.3f} Z={self._safe_rapid_z}")

                if op.operation_type == "taraudage":
                    # Taraudage: per-point thread_name and optional pattern
                    pt_params = {**default_params}
                    if effective_depth is not None:
                        pt_params['depth'] = effective_depth
                    pt_params['thread_name'] = (
                        pt.get('thread_type')
                        or op.params.get('thread_name') or 'M3')
                    # Pattern: NE PAS mettre dans le subprogram → sera dans Main
                    lines.append(
                        op_class.generate_operation_code(pt_params))
                else:
                    # Generic multi-point: profondeur individuelle si définie
                    if effective_depth is not None:
                        pt_params = {**default_params,
                                     'depth': effective_depth}
                        lines.append(
                            op_class.generate_operation_code(pt_params))
                    else:
                        lines.append(
                            op_class.generate_operation_code(default_params))

                # Pz=0 workaround: fermer le shift
                if pz_zero_workaround:
                    lines.append("    ShiftWcsInc Z=-0.1")
        else:
            lines.append(
                op_class.generate_operation_code(default_params))

        # ── Repeat wrapping: la grille, et la grille de la grille ──
        # (rétro-compat: anciens params repeat_count/repeat_shift_x/y,
        # lus par `repetition.grille`)
        from src.core import repetition
        total_repeats = repetition.compte(default_params)
        if total_repeats > 1:
            raw_body = lines[_body_start:]
            lines = lines[:_body_start]

            # Éclater les éléments multi-lignes en lignes individuelles
            body = []
            for item in raw_body:
                for ln in item.split("\n"):
                    body.append(ln)

            safe_rapid_line = (
                f"    SafeRapid X={op.x:.3f} Y={op.y:.3f}"
                f" Z={self._safe_rapid_z}")

            # Insérer SafeRapid après ShiftWcsInc UNIQUEMENT si la ligne
            # suivante est une opération (pas un autre ShiftWcsInc ni fin)
            processed_body = []
            for bi, bline in enumerate(body):
                processed_body.append(bline)
                if bline.strip().startswith("ShiftWcsInc"):
                    next_line = body[bi + 1].strip() if bi + 1 < len(body) else ""
                    if (next_line
                            and not next_line.startswith("ShiftWcsInc")
                            and not next_line.startswith("SafeRapid")):
                        processed_body.append(safe_rapid_line)
            body = processed_body

            # Supprimer le SafeRapid initial redondant
            if (len(body) >= 2
                    and body[0].strip().startswith("SafeRapid")
                    and body[1].strip().startswith("ShiftWcsInc")):
                body = body[1:]

            # Chaque position de la grille (deux niveaux), un
            # ShiftWcsInc entre deux, le retour à l'origine
            lines.extend(repetition.emettre(body, default_params))

        lines.append("    EndBlock")
        lines.append("endprogram")
        return self._demote_extra_saferapids("\n".join(lines))

    @staticmethod
    def _diametre_du_point(op, pt: dict):
        """Le Ø propre d'un trou de perçage fraisé (« Ø par point »),
        ou None: celui de l'opération. Sans le drapeau, les Ø rangés
        dans les points (détectés au DXF) ne comptent pas — un ancien
        programme garde son code."""
        if op.operation_type != "percage_fraise" or \
                not (op.params or {}).get('diametres_par_point'):
            return None
        try:
            d = float(pt.get('diameter') or 0.0)
        except (TypeError, ValueError):
            return None
        return d if d > 0 else None

    # ──── Per-point pattern subprograms ────

    def _build_per_point_subprograms(
            self, op: OperationInstance) -> list:
        """Génère un sous-programme par point (isolé ou pattern).
        - Point isolé: inclut SafeRapid vers les coordonnées du point
        - Point pattern: pas de SafeRapid (Pattern::RectanglePattern gère le positionnement)
        """
        op_class = self._get_op_class(op)
        if not op_class:
            return []

        prog_name = self._get_prog_name(op)
        tool = self.tool_lib.get_tool(op.tool_id) if op.tool_id else None
        default_params = self._op_params(op)
        default_params['_stroke_rapid_z'] = self._stroke_rapid_z
        default_params['_stroke_cutting_z'] = self._stroke_cutting_z

        # RPM override
        rpm_override = op.params.get('rpm_override', 0)
        rpm_mult = self._expert.get('material_rpm_mult', 1.0)

        result = []
        for pi, pt in enumerate(op.points):
            sub_name = f"{prog_name}_pt{pi}"
            pt_params = {**default_params}
            pt_depth = pt.get('depth')
            # Pz=0 workaround: Datron refuse d'usiner à Pz=0 →
            # décaler le WCS de 0.1 et usiner à 0.1 (modèle non modifié)
            pz_zero_workaround = (
                pt_depth is not None and float(pt_depth) == 0.0)
            if pz_zero_workaround:
                pt_params['depth'] = 0.1
            elif pt_depth is not None:
                pt_params['depth'] = pt_depth
            # Taraudage: thread_name per-point
            if op.operation_type == "taraudage":
                pt_params['thread_name'] = (
                    pt.get('thread_type')
                    or op.params.get('thread_name') or 'M3')
            # Perçage fraisé: le Ø du point
            diam_pt = self._diametre_du_point(op, pt)
            if diam_pt:
                pt_params['diameter'] = diam_pt

            lines = [f"program {sub_name}"]
            lines.append(f'    BeginBlock name="{sub_name}"')
            lines.append(f"    SafeZHeightForWorkpiece={self._safe_z}")
            lines.append("    SpraySystem On")
            if tool:
                rpm = self._rpm_value(op, tool, rpm_mult)
                lines.append(f'    Tool type="{tool.article_nr}"  skipRestoring    #{tool.name}')
                lines.append(f"    Rpm = {rpm}")
            lines.append("    Spindle On")
            if self._expert.get('smoothing', False):
                lines.append(self._ligne_smoothing())
            if tool:
                feed_mult = self._expert.get('material_feed_mult', 1.0)
                feed_parts = []
                fm = feed_mult
                if tool.feed_finishing:
                    feed_parts.append(
                        f"finishing={int(tool.feed_finishing * fm)}")
                if tool.feed_approach:
                    feed_parts.append(
                        f"approach={int(tool.feed_approach * fm)}")
                if tool.feed_plunge:
                    feed_parts.append(
                        f"plunge={int(tool.feed_plunge * fm)}")
                if tool.feed_ramp:
                    feed_parts.append(
                        f"ramp={int(tool.feed_ramp * fm)}")
                if tool.feed_roughing:
                    feed_parts.append(
                        f"roughing={int(tool.feed_roughing * fm)}")
                if feed_parts:
                    lines.append(
                        f"    SetFeedTechnology ({' '.join(feed_parts)})")

            # Pz=0: ouvrir le décalage WCS avant le positionnement
            if pz_zero_workaround:
                lines.append("    ShiftWcsInc Z=0.1")

            # SafeRapid vers les coordonnées du point
            lines.append(
                f"    SafeRapid X={pt.get('x', 0):.3f} "
                f"Y={pt.get('y', 0):.3f} Z={self._safe_rapid_z}")

            lines.append(op_class.generate_operation_code(pt_params))

            # Pz=0: refermer le décalage WCS
            if pz_zero_workaround:
                lines.append("    ShiftWcsInc Z=-0.1")

            lines.append("    EndBlock")
            lines.append("endprogram")
            result.append("\n".join(lines))
        return result

    # ──── Ébavurage ────

    def _build_ebavurage_subprogram(self, op: OperationInstance) -> str:
        """Construit le sous-programme d'ébavurage pour une opération taraudage.

        Rassemble tous les points (y compris ceux des patterns),
        calcule le chemin le plus court, et génère Drill pour chaque point.
        """
        ebav_tool_id = op.params.get('ebav_tool_id', '')
        ebav_tool = self.tool_lib.get_tool(ebav_tool_id) if ebav_tool_id else None
        if not ebav_tool:
            return f"# Erreur: outil ébavurage non sélectionné pour {op.name}"

        ebav_offset = op.params.get('ebav_offset', 0.05)
        try:
            # la profondeur du Drill, donnée à la main (0: automatique)
            ebav_prof = float(op.params.get('ebav_profondeur', 0.0) or 0.0)
        except (TypeError, ValueError):
            ebav_prof = 0.0
        prog_name = self._get_prog_name(op) + "_ebav"

        # ── Collecter TOUS les points (y compris pattern expansé) ──
        all_ebav_points: List[Dict] = []

        # Taraudage brut: 2 positions symétriques (+ repeat)
        if op.operation_type == "taraudage_brut":
            entraxe = float(op.params.get('entraxe', 20.0))
            axis = op.params.get('entraxe_axis', 'X')
            half = entraxe / 2.0
            thread_t = op.params.get('thread_type', 'M4')
            # Diamètre filet approximatif pour le calcul Pz ébavurage
            thread_diam_map = {'M3': 3.0, 'M4': 4.0, 'M6': 6.0, 'M8': 8.0}
            diam = thread_diam_map.get(thread_t, 4.0)
            pz = ebav_prof if ebav_prof > 0 else 0.5 * diam + ebav_offset
            # Positions de base (2 trous symétriques)
            if axis == 'X':
                base_pts = [
                    (op.x - half, op.y),
                    (op.x + half, op.y)]
            else:
                base_pts = [
                    (op.x, op.y - half),
                    (op.x, op.y + half)]
            # Les 2 trous de BASE seulement: la répétition, c'est
            # _wrap_instance_repeat qui la fait plus bas (ShiftWcsInc),
            # comme pour le taraudage lui-même. Déplier ici aussi la
            # grille la répétait deux fois: des chanfreins en double et
            # d'autres là où il n'y a pas de trou.
            for bx, by in base_pts:
                all_ebav_points.append({'x': bx, 'y': by, 'pz': pz})

        for pt in op.points:
            # Calcul Pz: taraudage → diamètre filet; percage → diamètre outil/op
            if op.operation_type == "taraudage":
                from src.operations.taraudage import THREAD_DIAMETER
                thread_t = (pt.get('thread_type')
                            or op.params.get('thread_name') or 'M3')
                diam = THREAD_DIAMETER.get(thread_t, 3.0)
            else:
                # percage_foret/fraise: diamètre du point, de l'opération
                # ou de l'outil
                diam = float(self._diametre_du_point(op, pt)
                             or op.params.get('diameter', 4.0))
                # percage_foret n'a pas de param diameter: le Ø du trou
                # est celui du foret (min_depth, pris ici avant, donnait
                # le même petit chanfrein pour tous les forets)
                main_tool = self.tool_lib.get_tool(op.tool_id)
                if main_tool and 'diameter' not in op.params and \
                        float(main_tool.diameter or 0.0) > 0:
                    diam = float(main_tool.diameter)
            pz = ebav_prof if ebav_prof > 0 else 0.5 * diam + ebav_offset

            if pt.get('use_pattern', False):
                # Expanser le pattern en points individuels
                x_base = pt.get('x', 0.0)
                y_base = pt.get('y', 0.0)
                nx = max(1, int(pt.get('x_count', 1)))
                ny = max(1, int(pt.get('y_count', 1)))
                dx = pt.get('delta_x', 10.0)
                dy = pt.get('delta_y', 10.0)
                for ix in range(nx):
                    for iy in range(ny):
                        all_ebav_points.append({
                            'x': x_base + ix * dx,
                            'y': y_base + iy * dy,
                            'pz': pz
                        })
            else:
                all_ebav_points.append({
                    'x': pt.get('x', 0.0),
                    'y': pt.get('y', 0.0),
                    'pz': pz
                })

        if not all_ebav_points:
            return f"# Ébavurage: aucun point pour {op.name}"

        # ── Tri par chemin le plus court (nearest-neighbor greedy) ──
        all_ebav_points = self._shortest_path_order(all_ebav_points)

        # ── Construction du sous-programme ──
        lines = [f"program {prog_name}"]
        lines.append(f'    BeginBlock name="{prog_name}"')
        lines.append(f"    SafeZHeightForWorkpiece={self._safe_z}")

        if ebav_tool.coolant == "flood":
            lines.append("    Coolant Alcohol")
        lines.append("    SpraySystem On")

        rpm_mult = self._expert.get('material_rpm_mult', 1.0)
        feed_mult = self._expert.get('material_feed_mult', 1.0)
        ebav_rpm = (int(ebav_tool.rpm * rpm_mult)
                    if rpm_mult != 1.0 else ebav_tool.rpm)
        lines.append(f'    Tool type="{ebav_tool.article_nr}"  skipRestoring    #{ebav_tool.name}')
        lines.append(f"    Rpm = {ebav_rpm}")
        lines.append("    Spindle On")

        # SetFeedTechnology
        feed_parts = []
        if ebav_tool.feed_finishing:
            feed_parts.append(
                f"finishing={int(ebav_tool.feed_finishing * feed_mult)}")
        if ebav_tool.feed_approach:
            feed_parts.append(
                f"approach={int(ebav_tool.feed_approach * feed_mult)}")
        if ebav_tool.feed_plunge:
            feed_parts.append(
                f"plunge={int(ebav_tool.feed_plunge * feed_mult)}")
        if ebav_tool.feed_ramp:
            feed_parts.append(
                f"ramp={int(ebav_tool.feed_ramp * feed_mult)}")
        if ebav_tool.feed_roughing:
            feed_parts.append(
                f"roughing={int(ebav_tool.feed_roughing * feed_mult)}")
        if feed_parts:
            lines.append(
                f"    SetFeedTechnology ({' '.join(feed_parts)})")

        # Points avec Drill — syntaxe SANS parenthèses (cf. exemples
        # SimPl machine: "Drill depth=2.05 strokeRapidZ=14 strokeCuttingZ=1")
        body = []
        for pt in all_ebav_points:
            body.append(
                f"    SafeRapid X={pt['x']:.3f} Y={pt['y']:.3f} Z={self._safe_rapid_z}")
            body.append(
                f"    Drill depth={pt['pz']:.2f} "
                f"strokeRapidZ={self._stroke_rapid_z} "
                f"strokeCuttingZ={self._stroke_cutting_z}")

        # L'ébavurage suit son opération: si elle est répétée, lui
        # aussi — sinon seul le premier trou serait ébavuré
        lines.extend(self._wrap_instance_repeat(body, op.params,
                                                op.x, op.y))

        lines.append("    EndBlock")
        lines.append("endprogram")
        return self._demote_extra_saferapids("\n".join(lines))

    #: les mouvements qui laissent l'outil là où ils finissent — au fond
    #: d'une hélice, au bout d'une ligne en matière —, à la différence
    #: des cycles (Drill, Pocket, Helix … Inside), qui remontent
    _MOUVEMENT_BAS_RE = re.compile(
        r'^(?:Line|Arc|Helix|HelixWithFullCircle|Circle|Polyline|PolyLine)'
        r'\b')
    #: ce qui ne bouge pas l'outil, entre un mouvement et le SafeRapid
    _SANS_MOUVEMENT = ('ShiftWcsInc', 'ShiftWcsAbs', 'ShiftLcsInc',
                       'ShiftLcsAbs', 'RotateLcsInc', 'RotateLcsAbs',
                       'ResetLcs', 'Feed', 'SetFeedTechnology')

    @classmethod
    def _outil_reste_bas(cls, lignes, i: int) -> bool:
        """Avant le SafeRapid de la ligne i, le dernier geste laisse-t-il
        l'outil en bas? Un mouvement (hélice, Line, Arc…), ou un Rapid
        sous la hauteur de ce SafeRapid. Les commentaires, décalages de
        repère et changements d'avance ne comptent pas."""
        m = re.search(r'\bZ=(-?[\d.]+)', lignes[i])
        try:
            z_sur = float(m.group(1)) if m else None
        except ValueError:
            z_sur = None
        for ligne in reversed(lignes[:i]):
            t = ligne.strip()
            if not t or t.startswith('#'):
                continue
            mot = t.split(None, 1)[0].split('(', 1)[0]
            if mot in cls._SANS_MOUVEMENT:
                continue
            if cls._MOUVEMENT_BAS_RE.match(t):
                # une hélice « Inside/Outside » est le CYCLE: il remonte
                return not (mot.startswith('Helix')
                            and re.search(r'\b(Inside|Outside)\b', t))
            if mot in ('Rapid', 'PrePositioning') and z_sur is not None:
                mz = re.search(r'\bZ=(-?[\d.]+)', t)
                if not mz:
                    continue        # sans Z, l'outil garde sa hauteur
                try:
                    return float(mz.group(1)) < z_sur - 1e-9
                except ValueError:
                    return False
            return False
        return False

    @staticmethod
    def _demote_extra_saferapids(code: str) -> str:
        """Dans un sous-programme, seul le PREMIER SafeRapid est conservé;
        les suivants deviennent Rapid (l'outil est déjà rétracté à hauteur
        sûre après chaque opération — le SafeRapid répété est inutile et
        plus lent)."""
        out = []
        seen_first = False
        lignes = code.split("\n")
        for i, ln in enumerate(lignes):
            stripped = ln.lstrip()
            if stripped.startswith("SafeRapid") and \
                    SimPlGenerator._outil_reste_bas(lignes, i):
                # l'outil est resté au fond (une hélice est un
                # MOUVEMENT, pas un cycle qui remonte): le SafeRapid
                # remonte d'abord. Changé en Rapid, il partait en
                # diagonale depuis le fond du trou, à travers la paroi.
                out.append(ln)
                seen_first = True
                continue
            if stripped.startswith("SafeRapid") and \
                    SimPlGenerator.saferapid_de_palpage(lignes, i):
                # le SafeRapid d'un palpage reste un SafeRapid (son Z est
                # libre, l'approche doit dégager d'abord), et l'usinage
                # qui suit reprend le sien
                out.append(ln)
                seen_first = False
                continue
            if stripped.startswith("SafeRapid"):
                if seen_first:
                    indent = ln[:len(ln) - len(stripped)]
                    out.append(
                        indent + "Rapid" + stripped[len("SafeRapid"):])
                    continue
                seen_first = True
            out.append(ln)
        return "\n".join(out)

    @staticmethod
    def _shortest_path_order(
            points: List[Dict]) -> List[Dict]:
        """Ordonne les points par nearest-neighbor (chemin approximatif le plus court).
        Démarre depuis l'origine (0,0)."""
        if len(points) <= 1:
            return points

        remaining = list(points)
        ordered = []
        current_x, current_y = 0.0, 0.0

        while remaining:
            best_idx = 0
            best_dist = float('inf')
            for i, pt in enumerate(remaining):
                dx = pt['x'] - current_x
                dy = pt['y'] - current_y
                dist = math.sqrt(dx * dx + dy * dy)
                if dist < best_dist:
                    best_dist = dist
                    best_idx = i
            chosen = remaining.pop(best_idx)
            ordered.append(chosen)
            current_x = chosen['x']
            current_y = chosen['y']

        return ordered

    def _needs_head_milling(self, op: OperationInstance) -> bool:
        """L'opération demande-t-elle un fraisage de tête de vis ?"""
        return (op.operation_type == "percage_fraise"
                and bool(op.params.get('head_milling'))
                and bool(op.points))

    def _build_head_subprogram(self, op: OperationInstance) -> str:
        """Fraisage des logements de tête, aux MÊMES points.

        Les points viennent du tableau de l'opération: en ajouter un
        au perçage l'ajoute au fraisage, sans rien resaisir."""
        from src.operations.percage_fraise import PercageFraise
        nom = self._get_prog_name(op) + "_tete"
        outil_id = str(op.params.get('head_tool_id', '') or '').strip()
        outil = (self.tool_lib.get_tool(outil_id) if outil_id
                 else None)
        if outil is None and op.tool_id:
            outil = self.tool_lib.get_tool(op.tool_id)
        rpm_mult = self._expert.get('material_rpm_mult', 1.0)
        feed_mult = self._expert.get('material_feed_mult', 1.0)

        lignes = [f"program {nom}",
                  f'    BeginBlock name="{nom}"',
                  f"    SafeZHeightForWorkpiece={self._safe_z}"]
        if outil is not None:
            if outil.coolant == "flood":
                lignes.append("    Coolant Alcohol")
            # comme tout sous-programme qui coupe: la pulvérisation
            lignes.append("    SpraySystem On")
            lignes.append(
                f'    Tool type="{outil.article_nr}"  skipRestoring'
                f'    #{outil.name}')
            rpm = (int(outil.rpm * rpm_mult) if rpm_mult != 1.0
                   else outil.rpm)
            lignes.append(f"    Rpm = {rpm}")
            lignes.append("    Spindle On")
            avances = []
            for cle in ('finishing', 'approach', 'plunge', 'ramp',
                        'roughing'):
                valeur = getattr(outil, f"feed_{cle}", 0)
                if valeur:
                    avances.append(f"{cle}={int(valeur * feed_mult)}")
            if avances:
                lignes.append(
                    f"    SetFeedTechnology ({' '.join(avances)})")

        try:
            saferapid = float(
                op.params.get('head_safe_rapid_z', 5.0) or 5.0)
        except (TypeError, ValueError):
            saferapid = 5.0
        corps = []
        for pt in op.points:
            corps.append(
                f"    SafeRapid X={float(pt.get('x', op.x)):.3f} "
                f"Y={float(pt.get('y', op.y)):.3f} Z={saferapid:g}")
            corps.append(PercageFraise.generate_head_code(op.params))
        # face au-dessus de l'origine: le repère monte jusqu'à elle, le
        # SafeRapid et la profondeur se comptent depuis la face
        haute = PercageFraise.head_surface_haute(op.params)
        if haute:
            lignes.append(f"    ShiftWcsInc Z={haute:g}")
        lignes.extend(self._wrap_instance_repeat(corps, op.params,
                                                 op.x, op.y))
        if haute:
            lignes.append(f"    ShiftWcsInc Z={-haute:g}")
        lignes.append("    EndBlock")
        lignes.append("endprogram")
        return self._demote_extra_saferapids(chr(10).join(lignes))

    def _needs_ebavurage(self, op: OperationInstance) -> bool:
        """Vérifie si l'opération nécessite un ébavurage."""
        if op.operation_type not in ("taraudage", "percage_foret",
                                     "percage_fraise", "taraudage_brut"):
            return False
        if not op.params.get('use_ebav', False):
            return False
        if not op.params.get('ebav_tool_id', ''):
            return False
        # taraudage_brut: pas de points, mais 2 positions symétriques
        if op.operation_type == "taraudage_brut":
            return True
        if not op.points:
            return False
        return True

    def _build_multi_tool_subprograms(self, op: OperationInstance) -> List[str]:
        """Taraudage: regroupe les points par type de filet et génère UN
        sous-programme par type (tous les taraudages M4 ensemble, etc.),
        avec chemin le plus court. Les points pattern génèrent en plus un
        sous-programme _pat{i} appelé via Pattern::RectanglePattern.
        Retourne la liste des blocs de code sous-programme.
        """
        # Taraudage: groupé par type de filet. Perçages: tous les points
        # du même outil dans UN sous-programme (déplacements en Rapid).
        if op.operation_type not in ("taraudage", "percage_foret",
                                     "percage_fraise"):
            return []
        op_class = self._get_op_class(op)
        if not op_class:
            return []

        default_params = self._op_params(op)
        # CRITIQUE: injecter les réglages machine expert — sans eux le
        # code d'opération retombe sur les défauts codés en dur (15/1)
        # et ignore le strokeRapidZ réglé par l'utilisateur (l'outil
        # descendrait de trop en Z → collision machine)
        default_params['_stroke_rapid_z'] = self._stroke_rapid_z
        default_params['_stroke_cutting_z'] = self._stroke_cutting_z
        default_params['_safe_rapid_z'] = self._safe_rapid_z
        base_prog_name = self._get_prog_name(op)
        is_taraudage = (op.operation_type == "taraudage")

        # Regrouper les points (taraudage: par thread_type;
        # perçage: groupe unique — même outil pour tous les points)
        # Un point sans type hérite du filetage de l'OPÉRATION: le
        # repli sur « M3 » usinait un M3 dans un programme réglé en M6
        default_thread = str(op.params.get('thread_name', '')
                             or 'M3')
        groups: Dict[str, List[Tuple[int, Dict]]] = {}
        for i, pt in enumerate(op.points):
            key = (pt.get('thread_type') or default_thread) \
                if is_taraudage else ""
            if key not in groups:
                groups[key] = []
            groups[key].append((i, pt))

        if not groups:
            return []

        # Plusieurs types → un sous-programme par type d'outil
        rpm_mult = self._expert.get('material_rpm_mult', 1.0)
        feed_mult = self._expert.get('material_feed_mult', 1.0)
        results = []
        # Appels à émettre dans Main pour cette opération (sous-prog
        # de base et/ou Pattern::RectanglePattern). Recalculé à chaque
        # appel: cette méthode est invoquée pour Main puis pour la
        # génération des sous-programmes.
        main_calls: List[str] = []
        self._taraudage_main_calls[op.id] = main_calls
        for thread_type, indexed_points in groups.items():
            if thread_type:
                sub_name = f"{base_prog_name}_{thread_type}"
                # Chercher l'outil compatible avec le filetage
                tool = self._find_tool_for_thread(thread_type, op.tool_id)
            else:
                # Perçage: nom de base, outil de l'opération
                sub_name = base_prog_name
                tool = (self.tool_lib.get_tool(op.tool_id)
                        if op.tool_id else None)

            lines = [f"program {sub_name}"]
            lines.append(f'    BeginBlock name="{sub_name}"')
            lines.append(f"    SafeZHeightForWorkpiece={self._safe_z}")

            if tool:
                if tool.coolant == "flood":
                    lines.append("    Coolant Alcohol")
            lines.append("    SpraySystem On")

            if tool:
                rpm = self._rpm_value(op, tool, rpm_mult)
                lines.append(f'    Tool type="{tool.article_nr}"  skipRestoring    #{tool.name}')
                lines.append(f"    Rpm = {rpm}")

            lines.append("    Spindle On")

            if tool:
                feed_parts = []
                for key in self._FEED_KEYS:
                    fv = self._feed_value(op, tool, key, feed_mult)
                    if fv:
                        feed_parts.append(f"{key}={fv}")
                if feed_parts:
                    lines.append(
                        f"    SetFeedTechnology ({' '.join(feed_parts)})")

            # Ordonner les points par chemin le plus court
            raw_pts = [{'x': pt['x'], 'y': pt['y'],
                        'depth': pt.get('depth'), 'idx': i,
                        'diameter': self._diametre_du_point(op, pt),
                        'use_pattern': pt.get('use_pattern', False),
                        'x_count': pt.get('x_count', 1),
                        'y_count': pt.get('y_count', 1),
                        'delta_x': pt.get('delta_x', 10.0),
                        'delta_y': pt.get('delta_y', 10.0)}
                       for i, pt in indexed_points]
            raw_pts = self._shortest_path_order(raw_pts)

            # Marqueur de début de corps: la grille de répétition
            # NbX/PasX NbY/PasY s'applique à tout ce qui suit (elle
            # était purement ignorée pour les taraudages/perçages
            # groupés, alors qu'elle fonctionnait sur l'ébavurage)
            _body_start = len(lines)
            # En-tête réutilisé par les sous-programmes de pattern
            # (hors ligne `program ...`): outil, Rpm, avances...
            header_lines = lines[1:_body_start]

            pat_programs = []
            has_plain = False
            for pt in raw_pts:
                pt_params = {**default_params}
                pt_depth = pt.get('depth')
                # Pz=0 workaround: Datron refuse d'usiner à Pz=0
                pz_zero = (pt_depth is not None
                           and float(pt_depth) == 0.0)
                if pz_zero:
                    pt_params['depth'] = 0.1
                elif pt_depth is not None:
                    pt_params['depth'] = pt_depth
                if thread_type:
                    pt_params['thread_name'] = thread_type
                if pt.get('diameter'):
                    pt_params['diameter'] = pt['diameter']

                if pt.get('use_pattern'):
                    # Pattern::RectanglePattern est TOUJOURS émis dans
                    # Main et appelle UN sous-programme complet
                    # (outil/Rpm propres) contenant un SEUL SafeRapid:
                    # le point d'origine du pattern.
                    pat_sub = f"{sub_name}_pat{pt['idx']}"
                    main_calls.append(
                        f"    Pattern::RectanglePattern ("
                        f"xCount={pt.get('x_count', 1)} "
                        f"yCount={pt.get('y_count', 1)} "
                        f"deltaX={pt.get('delta_x', 10.0)} "
                        f"deltaY={pt.get('delta_y', 10.0)} "
                        f"callProgram={pat_sub})")
                    pat_lines = [f"program {pat_sub}"]
                    for hl in header_lines:
                        if hl.strip().startswith('BeginBlock'):
                            pat_lines.append(
                                f'    BeginBlock name="{pat_sub}"')
                        else:
                            pat_lines.append(hl)
                    pat_lines.append(
                        f"    SafeRapid X={pt['x']:.3f} Y={pt['y']:.3f}"
                        f" Z={self._safe_rapid_z}")
                    pat_lines.append(
                        op_class.generate_operation_code(pt_params))
                    pat_lines.append("    EndBlock")
                    pat_lines.append("endprogram")
                    pat_programs.append("\n".join(pat_lines))
                else:
                    has_plain = True
                    if pz_zero:
                        lines.append("    ShiftWcsInc Z=0.1")
                    lines.append(
                        f"    SafeRapid X={pt['x']:.3f} Y={pt['y']:.3f}"
                        f" Z={self._safe_rapid_z}")
                    lines.append(
                        op_class.generate_operation_code(pt_params))
                    if pz_zero:
                        lines.append("    ShiftWcsInc Z=-0.1")

            # Sous-programme de base: seulement s'il reste des points
            # hors pattern (sinon il serait vide et appelé pour rien)
            if has_plain:
                body = lines[_body_start:]
                lines = lines[:_body_start] + \
                    self._wrap_instance_repeat(
                        body, default_params, op.x, op.y)
                lines.append("    EndBlock")
                lines.append("endprogram")
                results.append(
                    self._demote_extra_saferapids("\n".join(lines)))
                main_calls.insert(0, f"    {sub_name}")
            results.extend(pat_programs)

        return results

    def _find_tool_for_thread(self, thread_type: str,
                              default_tool_id: str) -> Optional[Tool]:
        """L'outil qui usine le filetage `thread_type`.

        Celui que l'utilisateur a CHOISI d'abord, dès qu'il couvre ce
        filet (même type, ou sa plage « Thr M2.5-M4 » le contient): il
        était remplacé par le premier outil de même type de la
        bibliothèque — une autre référence, avec ses vitesses, alors
        que l'en-tête annonçait toujours la sienne. Sinon un outil de
        la bibliothèque pour ce filet (même type, puis plage), et en
        dernier recours celui de l'opération."""
        choisi = (self.tool_lib.get_tool(default_tool_id)
                  if default_tool_id else None)
        if self._outil_couvre_filet(choisi, thread_type):
            return choisi
        outils = list(self.tool_lib.tools.values())
        for tool in outils:
            if tool.type_taraudage == thread_type:
                return tool
        for tool in outils:
            if self._outil_couvre_filet(tool, thread_type):
                return tool
        return choisi

    #: la plage de filets d'une fraise à fileter, dans son nom:
    #: « Thr M2.5-M4 Steel », « Thr M8-M10 », « Thr M6 »
    _PLAGE_FILETS_RE = re.compile(
        r'\bM(\d+(?:[.,]\d+)?)(?:\s*-\s*M?(\d+(?:[.,]\d+)?))?\b')

    @classmethod
    def _outil_couvre_filet(cls, tool, thread_type: str) -> bool:
        """L'outil usine-t-il le filet `thread_type` (« M3 »)? Son
        type le dit, ou la plage de filets de son nom."""
        if tool is None:
            return False
        if str(getattr(tool, 'type_taraudage', '') or '') == thread_type:
            return True
        m_f = re.fullmatch(r'\s*M(\d+(?:[.,]\d+)?)\s*',
                           str(thread_type or ''))
        m = cls._PLAGE_FILETS_RE.search(str(getattr(tool, 'name', '') or ''))
        if not m_f or not m:
            return False
        d = float(m_f.group(1).replace(',', '.'))
        bas = float(m.group(1).replace(',', '.'))
        haut = float((m.group(2) or m.group(1)).replace(',', '.'))
        return bas - 1e-9 <= d <= haut + 1e-9

    def _nom_palpage(self, op) -> str:
        """Nom du sous-programme de palpage du retournement.

        Une pièce retournée se palpe TOUJOURS: sans reprise d'origine,
        l'usinage de la seconde face part de la première. (La case
        « palper » qui permettait de s'en passer a été retirée.)

        Deux retournements aux mêmes cotes donneraient le même nom:
        on suffixe à partir du second."""
        from src.operations.retournement_piece import RetournementPiece
        base = RetournementPiece.probe_program_name(op.params)
        vus = getattr(self, '_noms_palpage', None)
        if vus is None:
            vus = self._noms_palpage = {}
        if op.id in vus:
            return vus[op.id]
        pris = set(vus.values())
        nom, n = base, 1
        while nom in pris:
            n += 1
            nom = f"{base}_{n}"
        vus[op.id] = nom
        return nom

    def _params_avec_outil(self, op) -> dict:
        """Paramètres de l'opération, nom de l'outil monté inclus.

        La géométrie d'un outil se lit dans son NOM: « Con 30° 0.6 »,
        « Cyl 2 z1L4 ». Sans lui, une gravure retombait sur le cône
        par défaut (30°, 0,2) quel que soit l'outil en broche, et une
        fraise cylindrique était calculée comme un cône."""
        from src.operations.gravure_2d5 import params_outil
        return params_outil(op, self.tool_lib)

    def _params_retournement(self, op) -> dict:
        """Paramètres du retournement, outil de l'opération inclus.

        L'outil se choisit dans le formulaire comme pour un usinage:
        c'est lui qui reste en broche pendant que l'opérateur
        manipule la pièce."""
        params = dict(op.params)
        outil = (self.tool_lib.get_tool(op.tool_id)
                 if op.tool_id and self.tool_lib else None)
        if outil is not None:
            params['_tool_article'] = outil.article_nr
            params['_tool_name'] = outil.name
        return params

    def _utilise_palpage_memorise(self) -> bool:
        return any(op.enabled
                   and op.operation_type == "palpage_memorise"
                   for op in self.program.operations)

    def _nom_palpage_memorise(self, op) -> str:
        """Nom du sous-programme, unique par opération."""
        base = "Palpage_memorise"
        vus = getattr(self, '_noms_memorise', None)
        if vus is None:
            vus = self._noms_memorise = {}
        if op.id not in vus:
            pris = set(vus.values())
            nom, n = base, 1
            while nom in pris:
                n += 1
                nom = f"{base}_{n}"
            vus[op.id] = nom
        return vus[op.id]

    def _nom_palpage_rect(self, op) -> str:
        """Nom du sous-programme de palpage, unique par opération."""
        from src.operations.palpage_rectangle import PalpageRectangle
        base = PalpageRectangle.program_name(op.params)
        vus = getattr(self, '_noms_palpage', None)
        if vus is None:
            vus = self._noms_palpage = {}
        if op.id not in vus:
            pris = set(vus.values())
            nom, n = base, 1
            while nom in pris:
                n += 1
                nom = f"{base}_{n}"
            vus[op.id] = nom
        return vus[op.id]

    def _build_palpage_rect_programs(self) -> str:
        """Sous-programmes RectangleMeasure des palpages autonomes."""
        from src.operations.palpage_rectangle import PalpageRectangle
        parts = []
        for op in self.program.operations:
            if not op.enabled or op.operation_type != "palpage_rectangle":
                continue
            parts.append(PalpageRectangle.generate_probe_program(
                op.params, self._nom_palpage_rect(op), op.x, op.y))
        return "\n\n".join(parts)

    def _build_palpage_memorise_programs(self) -> str:
        """Sous-programmes de reprise de palpage."""
        from src.operations.palpage_memorise import PalpageMemorise
        parts = []
        for op in self.program.operations:
            if not op.enabled or op.operation_type != "palpage_memorise":
                continue
            parts.append(PalpageMemorise.generate_program(
                op.params, self._nom_palpage_memorise(op),
                op.x, op.y))
        return "\n\n".join(parts)

    def _lignes_oubli_palpage(self) -> list:
        """`deletesavedvalueof` de fin de Main, sans doublon."""
        from src.operations.palpage_memorise import PalpageMemorise
        out, vues = [], set()
        for op in self.program.operations:
            if not op.enabled or op.operation_type != "palpage_memorise":
                continue
            ligne = PalpageMemorise.generate_forget_line(op.params)
            if ligne and ligne not in vues:
                vues.add(ligne)
                out.append(ligne)
        return out

    def _build_askfor_programs(self) -> str:
        """Génère les sous-programmes AskFor si nécessaire."""
        parts = []
        programmes_repris = set()
        for op in self.program.operations:
            if not op.enabled:
                continue
            if op.operation_type == "lignes_main":
                # les programmes du fichier d'origine que ses lignes
                # du Main appellent (« result = AskFor »), une fois
                for nom, corps in (op.params.get('_programmes')
                                   or {}).items():
                    if nom.lower() not in programmes_repris \
                            and str(corps).strip():
                        programmes_repris.add(nom.lower())
                        parts.append(str(corps).rstrip())
                continue
            if op.operation_type == "retournement_piece":
                from src.operations.retournement_piece import \
                    RetournementPiece
                if op.params.get('stop_if_no', True):
                    parts.append(
                        RetournementPiece.generate_askfor_program(
                            self._params_retournement(op),
                            f"Retournement_{op.id}"))
                nom = self._nom_palpage(op)
                if nom:
                    parts.append(
                        RetournementPiece.generate_probe_program(
                            op.params, nom))
                continue
            if op.operation_type == "dialogue_operateur":
                dialog_type = op.params.get('dialog_type', 'ask_continue')
                if dialog_type == "ask_continue":
                    from src.operations.dialogue_operateur import \
                        DialogueOperateur
                    askfor_name = f"AskFor_{op.id}"
                    code = DialogueOperateur.generate_askfor_program(
                        op.params, askfor_name)
                    parts.append(code)
        return "\n\n".join(parts)

    def _get_op_class(self, op: OperationInstance) \
            -> Optional[type]:
        """Récupère la classe d'opération depuis le registre."""
        try:
            return OperationRegistry.get(op.operation_type)
        except KeyError:
            return None
