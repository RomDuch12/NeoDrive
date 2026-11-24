"""
Opérations batch sur un fichier SimPl externe (outil Édition SimPl).
Chaque fonction travaille sur le TEXTE du programme et retourne
(nouveau_texte, nb_modifications). La traçabilité est assurée par
append_history(): bloc horodaté en pied de programme, après 'end'.
"""

import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

_HISTORY_HEADER = "# --- Historique NeoDrive ---"


def replace_tool(code: str, old_article: str, new_article: str,
                 new_name: str = "",
                 rpm: Optional[int] = None,
                 feeds: Optional[Dict[str, int]] = None
                 ) -> Tuple[str, int]:
    """Remplace un outil (Tool type="old" → "new") dans tout le code.
    - new_name: remplace le commentaire outil en fin de ligne Tool
    - rpm: met à jour la ligne 'Rpm = N' suivant chaque Tool remplacé
    - feeds: met à jour la SetFeedTechnology suivant chaque Tool
      remplacé (dict finishing/approach/plunge/ramp/roughing)
    """
    lines = code.split("\n")
    count = 0
    pending = 0  # lignes Tool remplacées en attente de maj Rpm/feeds
    # Matche Tool type="..." ET Tool name="..." (fichiers Datron) —
    # le remplacement émet TOUJOURS la forme normalisée type="..."
    tool_re = re.compile(
        r'Tool\s+(?:type|name)\s*=\s*"' + re.escape(old_article) + r'"')

    for i, ln in enumerate(lines):
        if tool_re.search(ln):
            new_ln = tool_re.sub(f'Tool type="{new_article}"', ln)
            # newRpm inline (convention Datron): maj sur place
            if rpm is not None and re.search(r'newRpm\s*[= ]\s*\d+',
                                             new_ln):
                new_ln = re.sub(r'(newRpm\s*[= ]\s*)\d+',
                                r'\g<1>' + str(int(rpm)), new_ln)
            if new_name:
                # Remplacer/ajouter le commentaire outil de la ligne
                if '#' in new_ln:
                    new_ln = new_ln[:new_ln.index('#')].rstrip() \
                        + f"    #{new_name}"
                else:
                    new_ln = new_ln.rstrip() + f"    #{new_name}"
            lines[i] = new_ln
            count += 1
            pending = 2  # maj Rpm/feeds sur les lignes qui suivent
            continue
        if pending <= 0:
            continue
        stripped = ln.lstrip()
        if stripped.startswith("Tool ") or stripped.startswith("program"):
            pending = 0  # nouvel outil/bloc: ne plus toucher
            continue
        if rpm is not None and re.match(r'Rpm\s*=', stripped):
            indent = ln[:len(ln) - len(stripped)]
            lines[i] = f"{indent}Rpm = {int(rpm)}"
            pending -= 1
        elif feeds and "SetFeedTechnology" in ln:
            parts = " ".join(
                f"{k}={int(v)}" for k, v in feeds.items() if v)
            indent = ln[:len(ln) - len(stripped)]
            lines[i] = f"{indent}SetFeedTechnology ({parts})"
            pending -= 1

    return "\n".join(lines), count


def adjust_depths(code: str, offset: float = 0.0, scale: float = 1.0,
                  program: str = "",
                  keys: Tuple[str, ...] = ("depth",)
                  ) -> Tuple[str, int]:
    """Ajuste des cotes Z: valeur = valeur × scale + offset.
    program: nom de sous-programme pour restreindre (vide = tout).
    keys: paramètres visés — ("depth",) par défaut, ("infeedZ",) pour
    la seule prise de passe en Z.
    Les valeurs résultantes sont bornées à ≥ 0.01."""
    if scale == 1.0 and offset == 0.0:
        return code, 0

    # Déterminer la plage de lignes du sous-programme ciblé
    lines = code.split("\n")
    start, end = 0, len(lines)
    if program:
        prog_re = re.compile(
            r'^\s*(?:export\s+)?program\s+' + re.escape(program) + r'\b')
        for i, ln in enumerate(lines):
            if prog_re.match(ln):
                start = i
                for j in range(i + 1, len(lines)):
                    if re.match(r'^\s*endprogram\b', lines[j]):
                        end = j
                        break
                break
        else:
            return code, 0  # sous-programme introuvable

    count = 0

    def _make_adj(key):
        def _adj(m):
            nonlocal count
            val = float(m.group(1))
            new = max(round(val * scale + offset, 3), 0.01)
            count += 1
            return f"{key}={new:g}"
        return _adj

    for i in range(start, end):
        for key in keys:
            lines[i] = re.sub(
                re.escape(key) + r'\s*=\s*([\d.]+)',
                _make_adj(key), lines[i])

    return "\n".join(lines), count


def adjust_sequence_z(code: str, sequence: str = "",
                      offset: float = 0.0, scale: float = 1.0
                      ) -> Tuple[str, int]:
    """Ajuste les profondeurs/passes Z dans les séquences Datron
    ($$$ SEQUENCE_N): Z = Z × scale + offset, appliqué UNIQUEMENT aux
    Z ≤ 0 (dans la matière) — les dégagements (Z > 0) sont préservés.
    sequence: nom pour restreindre (vide = toutes les séquences)."""
    if scale == 1.0 and offset == 0.0:
        return code, 0

    lines = code.split("\n")
    count = 0
    in_target = False
    z_re = re.compile(r'(\bZ\s*=\s*)([+-]?[\d.]+)')

    def _adj(m):
        nonlocal count
        val = float(m.group(2))
        if val > 0:
            return m.group(0)  # dégagement: intact
        new = round(val * scale + offset, 4)
        count += 1
        return f"{m.group(1)}{new:g}"

    for i, ln in enumerate(lines):
        stripped = ln.strip()
        if stripped.startswith('$$$'):
            name = stripped[3:].strip()
            in_target = (not sequence) or (name == sequence)
            continue
        if not in_target:
            continue
        if re.match(r'^(Line|Arc\s+C?CW|Rapid)\b', stripped):
            lines[i] = z_re.sub(_adj, ln)

    return "\n".join(lines), count


def set_header_field(code: str, field: str, value: str) -> Tuple[str, int]:
    """Met à jour un champ d'en-tête (@ Author = "..." @ / Comment)."""
    value = str(value).replace('"', "'")
    pattern = re.compile(
        r'(@\s*' + re.escape(field) + r'\s*=\s*")[^"]*("\s*@)')
    new_code, n = pattern.subn(r'\g<1>' + value + r'\g<2>', code)
    return new_code, n


# ── Blocs d'exécution du Main ─────────────────────────────────────
# L'ordre d'usinage d'un SimPl est celui des APPELS dans Main, pas
# celui des déclarations de sous-programmes. Réordonner ou mettre en
# sourdine se fait donc ici.

# « export program main » (exemples de la documentation DATRON) vaut Main
_MAIN_RE = re.compile(
    r'^([ \t]*)(?:export\s+)?program\s+(?i:main)\b', re.MULTILINE)
_ENDPROG_RE = re.compile(r'^[ \t]*endprogram\b', re.MULTILINE)
#: commandes machine qui ne sont pas des appels de sous-programme
_NOT_A_CALL = {
    'Absolute', 'Relative', 'endif', 'else', 'endfor', 'endwhile',
    'MoveToParkPosition', 'endprogram', 'return',
    # commandes de structure d'un sous-programme
    'BeginBlock', 'EndBlock', 'Spindle', 'SpraySystem', 'Coolant',
    'ToolCompensation', 'Smoothing', 'end',
}


def _main_span(code: str) -> Optional[Tuple[int, int, int]]:
    """(début_corps, fin_corps, début_ligne_program) du Main, en
    indices de caractères. None si le programme n'a pas de Main."""
    m = _MAIN_RE.search(code)
    if not m:
        return None
    body_start = code.find('\n', m.end())
    if body_start < 0:
        return None
    body_start += 1
    end = _ENDPROG_RE.search(code, body_start)
    if not end:
        return None
    return body_start, end.start(), m.start()


def parse_main_blocks(code: str) -> list:
    """Décompose le corps du Main en blocs manipulables.

    Chaque bloc: {'line', 'raw', 'name', 'kind', 'muted'}
      kind = 'call'    appel d'un sous-programme (déplaçable)
             'pattern' appel Pattern::… (déplaçable, porte un
                       callProgram)
             'fixed'   commande machine ou structure de contrôle
    Un bloc 'muted' est un appel commenté (# NomSousProg)."""
    span = _main_span(code)
    if span is None:
        return []
    body = code[span[0]:span[1]]
    blocks = []
    for i, raw in enumerate(body.split('\n')):
        stripped = raw.strip()
        if not stripped:
            continue
        muted = stripped.startswith('#')
        probe = stripped.lstrip('#').strip() if muted else stripped
        name, kind = '', 'fixed'
        pat = re.search(r'callProgram\s*=\s*(\w+)', probe)
        if pat:
            name, kind = pat.group(1), 'pattern'
        elif re.fullmatch(r'[A-Za-z_]\w*', probe) \
                and probe not in _NOT_A_CALL:
            name, kind = probe, 'call'
        if muted and kind == 'fixed':
            # Commentaire ordinaire: conservé tel quel (le retirer
            # ferait perdre les annotations du programme d'origine)
            blocks.append({'line': i, 'raw': raw, 'name': '',
                           'kind': 'comment', 'muted': True})
            continue
        blocks.append({'line': i, 'raw': raw, 'name': name,
                       'kind': kind, 'muted': muted})
    return blocks


def _ecart_parentheses(ligne: str) -> int:
    """Parenthèses ouvertes moins fermées, hors chaînes et commentaire."""
    s = re.sub(r'"[^"]*"', '', ligne).split('#')[0]
    return s.count('(') - s.count(')')


def main_statements(code: str) -> list:
    """Les blocs de `parse_main_blocks`, une instruction sur plusieurs
    lignes réunie en un seul: « Engrave::StandardTextEngrave ( … ) »
    ou « Dialog ( … ) » — leurs lignes « Center » ou « Left » ne sont
    pas des appels. `raw` porte alors toutes les lignes."""
    out, ouvert = [], 0
    for b in parse_main_blocks(code):
        if ouvert > 0:
            out[-1]['raw'] += '\n' + b['raw']
            if not b['raw'].strip().startswith('#'):
                ouvert += _ecart_parentheses(b['raw'])
            continue
        b = dict(b)
        ecart = 0 if b['muted'] else _ecart_parentheses(b['raw'])
        if ecart > 0:
            b['kind'], b['name'] = 'fixed', ''
        out.append(b)
        ouvert = max(0, ecart)
    for b in out:
        # un motif écrit sur plusieurs lignes reste un motif
        pat = re.search(r'callProgram\s*=\s*"?(\w+)', b['raw'])
        if '\n' in b['raw'] and not b['muted'] and pat \
                and b['raw'].strip().startswith('Pattern::'):
            b['kind'], b['name'] = 'pattern', pat.group(1)
    return out


def rewrite_main_blocks(code: str, blocks: list) -> str:
    """Réécrit le corps du Main d'après la liste de blocs fournie
    (ordre et état sourdine). Les lignes absentes de la liste sont
    supprimées; le reste du fichier est intact."""
    span = _main_span(code)
    if span is None:
        return code
    body_start, body_end, _ = span
    body = code[body_start:body_end]
    # indentation dominante du corps d'origine
    indents = [len(l) - len(l.lstrip())
               for l in body.split('\n') if l.strip()]
    indent = ' ' * (min(indents) if indents else 4)

    out = []
    for b in blocks:
        text = b['raw'].strip()
        if b.get('kind') == 'comment':
            out.append(f"{indent}{text}")   # annotation d'origine
            continue
        core = text.lstrip('#').strip() if text.startswith('#') \
            else text
        if b.get('muted'):
            out.append(f"{indent}# {core}")
        else:
            out.append(f"{indent}{core}")
    new_body = "\n".join(out)
    if new_body and not new_body.endswith('\n'):
        new_body += "\n"
    return code[:body_start] + new_body + code[body_end:]


#: fonctions d'usinage Datron reconnues dans un sous-programme
_DATRON_FUNCS = (
    'RectangleFace', 'CircleFace', 'RectangleCavity', 'CircleFromMid',
    'RectFromMid', 'DrillMilling', 'Drill', 'Thread',
    'HelixWithFullCircle', 'Engrave::StandardTextEngrave',
    'SurfaceMeasure', 'SymmetryAxisMeasure', 'CircleMeasure',
)
_FUNC_RE = re.compile(
    r'^\s*(' + '|'.join(re.escape(f) for f in _DATRON_FUNCS)
    + r')\b\s*\(?([^)\n]*)\)?', re.MULTILINE)
_PARAM_RE = re.compile(r'(\w+)\s*=\s*("[^"]*"|[-+]?[\d.]+)')


_FIN_PROGRAMME_RE = re.compile(r'^\s*endprogram\b')
_SEQUENCES_RE = re.compile(r'^\$\$\$\s*(\S+)', re.MULTILINE)
_DECLARES_RE = re.compile(r'^\s*(?:export\s+)?program\s+(\w+)', re.MULTILINE)


def subprogram_body(code: str, name: str,
                    lines: Optional[List[str]] = None) -> Tuple[int, int]:
    """Plage de lignes (début, fin) du corps d'un sous-programme.
    `lines`: `code` déjà découpé (un programme de 30 Mo ne se
    redécoupe pas pour chacun de ses sous-programmes)."""
    if lines is None:
        lines = code.split('\n')
    head = re.compile(
        r'^\s*(?:export\s+)?program\s+' + re.escape(name) + r'\b')
    # le mot cherché d'abord: une sous-chaîne se teste cent fois plus
    # vite qu'une expression, sur le million de lignes d'un gros fichier
    for i, ln in enumerate(lines):
        if 'program' in ln and head.match(ln):
            for j in range(i + 1, len(lines)):
                if 'endprogram' in lines[j] and \
                        _FIN_PROGRAMME_RE.match(lines[j]):
                    return i + 1, j
            return i + 1, len(lines)
    return -1, -1


def analyse_preparee(code: str) -> dict:
    """Ce que `analyze_subprogram` relit dans TOUT le fichier, calculé
    une fois pour tous ses sous-programmes."""
    return {'lines': code.split('\n'),
            'sequences': set(_SEQUENCES_RE.findall(code)),
            'declared': set(_DECLARES_RE.findall(code))}


def analyze_subprogram(code: str, name: str,
                       prepare: Optional[dict] = None) -> dict:
    """Décrit le contenu d'un sous-programme importé.

    Un sous-programme Datron contient soit un APPEL DE SÉQUENCE (le
    parcours vit dans un bloc $$$), soit une FONCTION d'usinage avec
    ses paramètres. Le formulaire d'édition doit s'adapter aux deux.

    Retourne {'kind': 'sequence'|'function'|'inconnu', 'tool',
    'tool_kw', 'rpm', 'feeds', 'sequence', 'function', 'params',
    'line'} — 'line' étant la ligne de la fonction, pour la patcher.
    `prepare`: `analyse_preparee(code)`, quand on analyse tous les
    sous-programmes d'un fichier.
    """
    lines = prepare['lines'] if prepare else code.split('\n')
    start, end = subprogram_body(code, name, lines)
    info = {'kind': 'inconnu', 'tool': '', 'tool_kw': '',
            'tool_comment': '', 'rpm': None,
            'feeds': {}, 'sequence': '', 'function': '', 'params': {},
            'line': -1}
    if start < 0:
        return info
    body = lines[start:end]
    sequences = (prepare['sequences'] if prepare
                 else set(_SEQUENCES_RE.findall(code)))

    for offset, ln in enumerate(body):
        stripped = ln.strip()
        if stripped.startswith('#'):
            continue
        m = re.search(r'Tool\s+(type|name)\s*=\s*"([^"]+)"', stripped)
        if m:
            info['tool_kw'], info['tool'] = m.group(1), m.group(2)
            # Commentaire de fin de ligne: souvent le SEUL endroit où
            # le fichier nomme l'outil en clair (Tool type="0068443G"
            # #Cyl 14 z2L6)
            cm = re.search(r'#\s*(.+?)\s*$', stripped)
            if cm:
                info['tool_comment'] = cm.group(1).strip()
            rpm = re.search(r'newRpm\s*[= ]\s*(\d+)', stripped)
            if rpm:
                info['rpm'] = int(rpm.group(1))
            continue
        m = re.match(r'Rpm\s*=\s*(\d+)', stripped)
        if m:
            info['rpm'] = int(m.group(1))
            continue
        if 'SetFeedTechnology' in stripped:
            info['feeds'] = {k: v for k, v in _PARAM_RE.findall(stripped)}
            continue
        fm = re.match(
            r'(' + '|'.join(re.escape(f) for f in _DATRON_FUNCS)
            + r')\b\s*(\(?)(.*)$', stripped)
        if fm:
            info['kind'] = 'function'
            info['function'] = fm.group(1)
            info['line'] = start + offset
            # Les appels Datron s'étalent souvent sur plusieurs lignes:
            #     Thread (
            #         threadName="M3"
            #         depth=7.2
            #     )
            chunk = fm.group(3)
            span = [start + offset]
            if fm.group(2) and ')' not in chunk:
                for k in range(offset + 1, len(body)):
                    chunk += "\n" + body[k]
                    span.append(start + k)
                    if ')' in body[k]:
                        break
            info['params'] = {k: v for k, v in _PARAM_RE.findall(chunk)}
            info['param_lines'] = span
            continue
        # Appel de séquence: identifiant seul qui n'est ni une commande
        # ni un sous-programme du fichier (les blocs $$$ peuvent être
        # déclarés ailleurs, d'où le repli sur cette règle)
        if (info['kind'] == 'inconnu'
                and re.fullmatch(r'[A-Za-z_]\w*', stripped)
                and stripped not in _NOT_A_CALL):
            declared = (prepare['declared'] if prepare
                        else set(_DECLARES_RE.findall(code)))
            if stripped in sequences or stripped not in declared:
                info['kind'] = 'sequence'
                info['sequence'] = stripped
                info['line'] = start + offset
            continue
        # …ou AVEC ses avances (« SEQUENCE_x Schneiden=Schneiden
        # Finish=Finish », la FAO DATRON de DemoDatron.simpl)
        am = re.match(r'([A-Za-z_]\w*)\s+\w+\s*=', stripped)
        if (info['kind'] == 'inconnu' and am
                and am.group(1) in sequences):
            info['kind'] = 'sequence'
            info['sequence'] = am.group(1)
            info['line'] = start + offset
    return info


def set_function_param(code: str, name: str, key: str,
                       value) -> Tuple[str, int]:
    """Modifie un paramètre de la fonction d'usinage d'un
    sous-programme (depth, infeedZ, widthX…). Ne touche qu'à CE
    sous-programme."""
    info = analyze_subprogram(code, name)
    if info['kind'] != 'function' or info['line'] < 0:
        return code, 0
    lines = code.split('\n')
    pattern = re.compile(re.escape(key) + r'\s*=\s*("[^"]*"|[-+]?[\d.]+)')
    text = f'"{value}"' if isinstance(value, str) else f"{value:g}"
    # l'appel peut s'étaler sur plusieurs lignes
    for idx in info.get('param_lines') or [info['line']]:
        if 0 <= idx < len(lines) and pattern.search(lines[idx]):
            lines[idx] = pattern.sub(f"{key}={text}", lines[idx],
                                     count=1)
            return "\n".join(lines), 1
    return code, 0


def set_subprogram_rpm(code: str, name: str, rpm: int) -> Tuple[str, int]:
    """Change le régime d'un sous-programme (Rpm = N ou newRpm=N)."""
    start, end = subprogram_body(code, name)
    if start < 0:
        return code, 0
    lines = code.split('\n')
    count = 0
    for i in range(start, end):
        if re.search(r'newRpm\s*[= ]\s*\d+', lines[i]):
            lines[i] = re.sub(r'(newRpm\s*[= ]\s*)\d+',
                              r'\g<1>' + str(int(rpm)), lines[i])
            count += 1
        elif re.match(r'^\s*Rpm\s*=\s*\d+', lines[i]):
            indent = lines[i][:len(lines[i]) - len(lines[i].lstrip())]
            lines[i] = f"{indent}Rpm = {int(rpm)}"
            count += 1
    return "\n".join(lines), count


def rename_subprogram(code: str, old: str, new: str) -> Tuple[str, int]:
    """Renomme un sous-programme PARTOUT où son nom apparaît.

    Trois endroits doivent suivre, sans quoi le programme devient
    incohérent: la déclaration `program X`, la ligne
    `BeginBlock name="X"` et les appels (dans Main ou en
    callProgram=X d'un Pattern)."""
    old, new = str(old).strip(), str(new).strip()
    if not old or not new or old == new:
        return code, 0
    count = 0
    lines = code.split('\n')
    decl = re.compile(r'^(\s*(?:export\s+)?program\s+)' +
                      re.escape(old) + r'\b')
    begin = re.compile(r'(BeginBlock\s+name\s*=\s*")' +
                       re.escape(old) + r'(")')
    call_prog = re.compile(r'(callProgram\s*=\s*)' +
                           re.escape(old) + r'\b')
    bare = re.compile(r'^(\s*)' + re.escape(old) + r'\s*$')
    muted = re.compile(r'^(\s*#\s*)' + re.escape(old) + r'\s*$')
    for i, ln in enumerate(lines):
        new_ln = ln
        if decl.match(new_ln):
            new_ln = decl.sub(r'\g<1>' + new, new_ln)
        if begin.search(new_ln):
            new_ln = begin.sub(r'\g<1>' + new + r'\g<2>', new_ln)
        if call_prog.search(new_ln):
            new_ln = call_prog.sub(r'\g<1>' + new, new_ln)
        if bare.match(new_ln):
            new_ln = bare.sub(r'\g<1>' + new, new_ln)
        elif muted.match(new_ln):
            new_ln = muted.sub(r'\g<1>' + new, new_ln)
        if new_ln != ln:
            lines[i] = new_ln
            count += 1
    return "\n".join(lines), count


def set_subprogram_feeds(code: str, name: str,
                         feeds: Dict[str, int]) -> Tuple[str, int]:
    """Réécrit la SetFeedTechnology d'un sous-programme.

    La forme d'origine peut être sans parenthèses
    (`SetFeedTechnology finishing=3800 plunge=1000`) ou multi-lignes;
    on émet la forme parenthésée, acceptée dans les deux cas."""
    parts = " ".join(f"{k}={int(v)}" for k, v in feeds.items() if v)
    if not parts:
        return code, 0
    start, end = subprogram_body(code, name)
    if start < 0:
        return code, 0
    lines = code.split('\n')
    for i in range(start, end):
        if 'SetFeedTechnology' not in lines[i]:
            continue
        indent = lines[i][:len(lines[i]) - len(lines[i].lstrip())]
        # Forme multi-lignes: absorber jusqu'à la parenthèse fermante
        drop_to = i
        if '(' in lines[i] and ')' not in lines[i]:
            for j in range(i + 1, end):
                drop_to = j
                if ')' in lines[j]:
                    break
        lines[i:drop_to + 1] = [
            f"{indent}SetFeedTechnology ({parts})"]
        return "\n".join(lines), 1
    return code, 0


# ── Profondeur d'une séquence ($$$) ───────────────────────────────
# Une séquence Datron usine par PASSES: le même parcours répété à des
# Z de plus en plus profonds. Régler la profondeur finale n'est donc
# pas un simple filtre ligne à ligne — il faut raisonner par passe,
# sinon la cote demandée n'est jamais atteinte (on retombe sur la
# passe précédente, plus haute).

_SEQ_MOVE_RE = re.compile(r'^(Line|Arc\s+C?CW|Rapid|PrePositioning)\b')
_SEQ_CUT_RE = re.compile(r'^(Line|Arc\s+C?CW)\b')
_SEQ_Z_RE = re.compile(r'(\bZ\s*=\s*)([-+]?[\d.]+)')
#: au-delà, les Z ne sont pas des passes mais un profil 3D continu
_MAX_STEPPED_LEVELS = 12
_EPS = 1e-6


def _sequence_line_range(lines: List[str], sequence: str = ""):
    """Indices des lignes appartenant aux séquences visées."""
    spans = []
    start = -1
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        if stripped.startswith('$$$'):
            if start >= 0:
                spans.append((start, i))
            name = stripped[3:].strip()
            start = i + 1 if (not sequence or name == sequence) else -1
    if start >= 0:
        spans.append((start, len(lines)))
    return spans


def sequence_z_levels(code: str, sequence: str = "") -> List[float]:
    """Niveaux de passe (Z ≤ 0) d'une séquence, du plus haut au plus
    profond. Les dégagements (Z > 0) n'en sont pas."""
    lines = code.split('\n')
    levels = []
    for start, end in _sequence_line_range(lines, sequence):
        for ln in lines[start:end]:
            stripped = ln.strip()
            if stripped.startswith('#') or not _SEQ_CUT_RE.match(stripped):
                continue
            m = _SEQ_Z_RE.search(stripped)
            if not m:
                continue
            val = round(float(m.group(2)), 4)
            if val <= 0 and val not in levels:
                levels.append(val)
    levels.sort(reverse=True)
    return levels


def truncate_sequence_below(code: str, z_max: float,
                            sequence: str = "") -> Tuple[str, int]:
    """Limite la profondeur d'une séquence à `z_max`.

    Les passes plus profondes sont COMMENTÉES (récupérables, pas
    supprimées). Mais commenter ne suffit pas: si la passe précédente
    s'arrête plus haut que `z_max`, la cote demandée n'est jamais
    usinée (3 mm en 2 passes tronqué à 2,5 donnait 1,5). La première
    passe qui franchit le seuil est donc RAMENÉE à `z_max` au lieu
    d'être supprimée; seules les passes encore plus profondes sont
    commentées.

    Une ligne sans Z hérite du Z courant (coordonnées modales): elle
    suit le sort de sa passe."""
    lines = code.split('\n')
    levels = sequence_z_levels(code, sequence)
    too_deep = [z for z in levels if z < z_max - _EPS]
    kept = [z for z in levels if z >= z_max - _EPS]
    # Ramener la passe fautive n'a de sens que sur des passes
    # étagées: sur un profil 3D continu, chaque ligne a son propre Z
    # et le seuil se lit ligne à ligne.
    stepped = 0 < len(levels) <= _MAX_STEPPED_LEVELS
    clamp_level = None
    if stepped and too_deep and (not kept or min(kept) > z_max + _EPS):
        clamp_level = max(too_deep)

    count = 0
    for start, end in _sequence_line_range(lines, sequence):
        current_z = None
        dropped = False
        for i in range(start, end):
            ln = lines[i]
            stripped = ln.strip()
            if stripped.startswith('#') or not _SEQ_MOVE_RE.match(stripped):
                continue
            indent = ln[:len(ln) - len(ln.lstrip())]
            m = _SEQ_Z_RE.search(stripped)
            if m:
                current_z = float(m.group(2))
                if current_z > 0:
                    dropped = False       # dégagement: toujours gardé
                    continue
                if clamp_level is not None \
                        and abs(current_z - clamp_level) < _EPS:
                    lines[i] = indent + _SEQ_Z_RE.sub(
                        lambda mm: f"{mm.group(1)}{z_max:g}", stripped)
                    current_z = z_max
                    dropped = False
                    count += 1
                    continue
                dropped = current_z < z_max - _EPS
            if dropped:
                lines[i] = f"{indent}# {stripped}"
                count += 1
    return "\n".join(lines), count


def extend_sequence_depth(code: str, z_target: float,
                          sequence: str = "") -> Tuple[str, int]:
    """Prolonge une séquence étagée jusqu'à `z_target`.

    La dernière passe est recopiée aux profondeurs suivantes, avec le
    pas des passes précédentes; la dernière copie tombe exactement sur
    `z_target`. Sans passes étagées identifiables (profil 3D continu),
    rien n'est fait: mieux vaut ne pas usiner que d'inventer un
    parcours."""
    levels = sequence_z_levels(code, sequence)
    if not levels or len(levels) > _MAX_STEPPED_LEVELS:
        return code, 0
    deepest = levels[-1]
    if z_target >= deepest - _EPS:
        return code, 0
    step = (levels[-2] - levels[-1]) if len(levels) >= 2 else -deepest
    step = abs(step) or abs(deepest)
    if step < _EPS:
        return code, 0
    # Profondeurs à ajouter, la dernière pile sur la cote demandée
    new_levels = []
    z = deepest - step
    while z > z_target + _EPS:
        new_levels.append(round(z, 4))
        z -= step
    new_levels.append(round(z_target, 4))
    if not new_levels:
        return code, 0

    lines = code.split('\n')
    count = 0
    # Traiter les séquences de la fin vers le début: les insertions ne
    # décalent alors pas les indices restant à traiter
    for start, end in reversed(_sequence_line_range(lines, sequence)):
        blocks = []          # (début, fin) des passes les plus basses
        i = start
        while i < end:
            stripped = lines[i].strip()
            m = (None if stripped.startswith('#')
                 or not _SEQ_CUT_RE.match(stripped)
                 else _SEQ_Z_RE.search(stripped))
            if not m or abs(float(m.group(2)) - deepest) >= _EPS:
                i += 1
                continue
            j = i + 1
            while j < end:
                nxt = lines[j].strip()
                if nxt.startswith('#') or not _SEQ_MOVE_RE.match(nxt):
                    break
                zm = _SEQ_Z_RE.search(nxt)
                if zm and abs(float(zm.group(2)) - deepest) >= _EPS:
                    break     # dégagement ou passe suivante
                j += 1
            blocks.append((i, j))
            i = j
        for b_start, b_end in reversed(blocks):
            block = lines[b_start:b_end]
            extra = []
            for level in new_levels:
                for ln in block:
                    extra.append(_SEQ_Z_RE.sub(
                        lambda mm: (f"{mm.group(1)}{level:g}"
                                    if abs(float(mm.group(2)) - deepest)
                                    < _EPS else mm.group(0)), ln))
                count += 1
            lines[b_end:b_end] = extra
    return "\n".join(lines), count


def rename_sequence(code: str, old: str, new: str) -> Tuple[str, int]:
    """Renomme une séquence PARTOUT: bloc $$$, déclaration et appel.

    Deux fichiers importés déclarent tous deux SEQUENCE_1: sans
    renommage, le second écrase le premier et des blocs usinent le
    parcours d'un autre programme."""
    old, new = str(old).strip(), str(new).strip()
    if not old or not new or old == new:
        return code, 0
    count = 0
    out = []
    for line in code.split('\n'):
        stripped = line.strip()
        indent = line[:len(line) - len(line.lstrip())]
        if stripped.startswith('$$$'):
            if stripped[3:].strip() == old:
                out.append(f"{indent}$$$ {new}")
                count += 1
                continue
        elif re.fullmatch(r'sequence\s+' + re.escape(old), stripped):
            out.append(f"{indent}sequence {new}")
            count += 1
            continue
        elif stripped == old:
            # Appel de séquence dans un sous-programme (identifiant
            # seul, indentation conservée)
            out.append(f"{indent}{new}")
            count += 1
            continue
        elif re.match(re.escape(old) + r'[ \t(]', stripped):
            # … ou avec ses paramètres (`SEQ Schneiden=Schneiden`)
            out.append(f"{indent}{new}{stripped[len(old):]}")
            count += 1
            continue
        out.append(line)
    return "\n".join(out), count


def sequence_names(code: str) -> List[str]:
    """Noms des blocs $$$ déclarés dans le code."""
    return [m.group(1) for m in
            re.finditer(r'^\$\$\$\s*(\S+)', code, re.MULTILINE)]


def set_sequence_depth(code: str, z_target: float,
                       sequence: str = "") -> Tuple[str, int]:
    """Amène une séquence à la profondeur `z_target`.

    Moins profond que la séquence: troncature (avec report de la cote
    sur la dernière passe conservée). Plus profond: passes
    supplémentaires au pas des précédentes. 0 = ne rien faire.

    Sans nom de séquence, chacune est traitée SÉPARÉMENT: leurs
    profondeurs n'ont rien à voir entre elles, et les fusionner
    faisait passer un fichier contenant un profil 3D pour un profil
    3D entier — le report de cote ne se faisait plus nulle part."""
    if z_target >= 0:
        return code, 0
    if not sequence:
        total = 0
        for name in sequence_names(code):
            code, n = set_sequence_depth(code, z_target, name)
            total += n
        return code, total
    levels = sequence_z_levels(code, sequence)
    if not levels:
        return code, 0
    deepest = levels[-1]
    if z_target < deepest - _EPS:
        return extend_sequence_depth(code, z_target, sequence)
    if z_target > deepest + _EPS:
        return truncate_sequence_below(code, z_target, sequence)
    return code, 0


def _blocs_de_passe(lines, start, end, level):
    """Spans (i, j) des blocs de lignes de COUPE à ce niveau Z.

    Un bloc commence à une ligne de coupe dont le Z explicite vaut
    `level`, et s'étend aux lignes de MOUVEMENT suivantes qui restent à
    ce Z (Z absent = hérité, coordonnées modales)."""
    blocs = []
    i = start
    while i < end:
        stripped = lines[i].strip()
        m = (None if stripped.startswith('#')
             or not _SEQ_CUT_RE.match(stripped)
             else _SEQ_Z_RE.search(stripped))
        if not m or abs(float(m.group(2)) - level) >= _EPS:
            i += 1
            continue
        j = i + 1
        while j < end:
            nxt = lines[j].strip()
            if nxt.startswith('#') or not _SEQ_MOVE_RE.match(nxt):
                break
            zm = _SEQ_Z_RE.search(nxt)
            if zm and abs(float(zm.group(2)) - level) >= _EPS:
                break
            j += 1
        blocs.append((i, j))
        i = j
    return blocs


def set_pass_z(code: str, old_z: float, new_z: float,
               sequence: str = "") -> Tuple[str, int]:
    """Change le Z d'UNE passe: tous les Z explicites égaux à `old_z`
    (dans les lignes de coupe) deviennent `new_z`. Les lignes modales
    (sans Z) suivent, puisqu'elles héritent du Z de leur passe. Rend
    le code et le nombre de lignes changées."""
    if abs(old_z - new_z) < _EPS:
        return code, 0
    lines = code.split('\n')
    count = 0
    for start, end in _sequence_line_range(lines, sequence):
        for i in range(start, end):
            stripped = lines[i].strip()
            if stripped.startswith('#') or not _SEQ_CUT_RE.match(stripped):
                continue
            m = _SEQ_Z_RE.search(stripped)
            if not m or abs(float(m.group(2)) - old_z) >= _EPS:
                continue
            indent = lines[i][:len(lines[i]) - len(lines[i].lstrip())]
            lines[i] = indent + _SEQ_Z_RE.sub(
                lambda mm: f"{mm.group(1)}{new_z:g}", stripped)
            count += 1
    return "\n".join(lines), count


def remove_pass(code: str, z: float, sequence: str = "") -> Tuple[str, int]:
    """Supprime une passe: retire les blocs de lignes de coupe à ce Z.
    Rend le code et le nombre de blocs retirés."""
    lines = code.split('\n')
    total = 0
    for start, end in reversed(_sequence_line_range(lines, sequence)):
        for b_start, b_end in reversed(_blocs_de_passe(
                lines, start, end, z)):
            del lines[b_start:b_end]
            total += 1
    return "\n".join(lines), total


def add_pass(code: str, new_z: float, sequence: str = "",
             copy_from_z: float = None) -> Tuple[str, int]:
    """Ajoute une passe au Z `new_z`, en recopiant le parcours d'une
    passe existante (`copy_from_z`, la plus profonde par défaut) avec
    son Z ramené à `new_z`. Le bloc copié est inséré dans l'ORDRE de
    profondeur (les passes restent du plus haut au plus profond) —
    on ne plonge jamais au fond avant les passes du dessus.

    Sans passe étagée identifiable (profil 3D), rien n'est fait. Rend
    le code et le nombre de blocs ajoutés."""
    levels = sequence_z_levels(code, sequence)
    if not levels or len(levels) > _MAX_STEPPED_LEVELS:
        return code, 0
    if any(abs(new_z - z) < _EPS for z in levels):
        return code, 0            # la passe existe déjà
    source = copy_from_z if copy_from_z is not None else levels[-1]
    if not any(abs(source - z) < _EPS for z in levels):
        source = levels[-1]

    lines = code.split('\n')
    count = 0
    for start, end in reversed(_sequence_line_range(lines, sequence)):
        src_blocs = _blocs_de_passe(lines, start, end, source)
        if not src_blocs:
            continue
        # Point d'insertion: juste avant la 1re passe PLUS PROFONDE que
        # new_z (Z plus négatif), sinon après le dernier bloc source
        plus_profondes = [z for z in levels if z < new_z - _EPS]
        insert_at = src_blocs[-1][1]
        if plus_profondes:
            cible = max(plus_profondes)   # la moins profonde des + basses
            blocs_cible = _blocs_de_passe(lines, start, end, cible)
            if blocs_cible:
                insert_at = blocs_cible[0][0]
        for b_start, b_end in reversed(src_blocs):
            bloc = lines[b_start:b_end]
            copie = [_SEQ_Z_RE.sub(
                lambda mm: (f"{mm.group(1)}{new_z:g}"
                            if abs(float(mm.group(2)) - source) < _EPS
                            else mm.group(0)), ln)
                     for ln in bloc]
            lines[insert_at:insert_at] = copie
            count += 1
    return "\n".join(lines), count


#: un changement d'outil qu'un programme fait VRAIMENT (pas en
#: commentaire): (« type » ou « name », référence ou nom)
TOOL_PRIS_RE = re.compile(r'^[ \t]*Tool\s+(type|name)\s*=\s*"([^"]+)"',
                          re.MULTILINE)


def set_subprogram_tool(code: str, name: str, article: str,
                        tool_name: str = "",
                        rpm: Optional[int] = None,
                        feeds: Optional[Dict[str, int]] = None
                        ) -> Tuple[str, int]:
    """Change l'outil d'un sous-programme (et son régime/avances).

    La forme normalisée `Tool type="article"` est toujours émise, y
    compris quand l'original utilisait `Tool name="…"`: c'est la
    référence qui identifie l'outil sans ambiguïté."""
    start, end = subprogram_body(code, name)
    if start < 0:
        return code, 0
    lines = code.split('\n')
    count = 0
    for i in range(start, end):
        ln = lines[i]
        if not re.search(r'Tool\s+(?:type|name)\s*=\s*"[^"]*"', ln):
            continue
        new_ln = re.sub(r'Tool\s+(?:type|name)\s*=\s*"[^"]*"',
                        f'Tool type="{article}"', ln)
        if rpm is not None and re.search(r'newRpm\s*[= ]\s*\d+',
                                         new_ln):
            new_ln = re.sub(r'(newRpm\s*[= ]\s*)\d+',
                            r'\g<1>' + str(int(rpm)), new_ln)
        if tool_name:
            if '#' in new_ln:
                new_ln = new_ln[:new_ln.index('#')].rstrip() \
                    + f"    #{tool_name}"
            else:
                new_ln = new_ln.rstrip() + f"    #{tool_name}"
        lines[i] = new_ln
        count += 1
    code = "\n".join(lines)
    if rpm is not None:
        code, _ = set_subprogram_rpm(code, name, rpm)
    if feeds:
        start, end = subprogram_body(code, name)
        lines = code.split('\n')
        parts = " ".join(f"{k}={int(v)}" for k, v in feeds.items() if v)
        for i in range(start, end):
            if 'SetFeedTechnology' in lines[i] and parts:
                indent = lines[i][:len(lines[i])
                                  - len(lines[i].lstrip())]
                lines[i] = f"{indent}SetFeedTechnology ({parts})"
                break
        code = "\n".join(lines)
    return code, count


def program_names(code: str) -> set:
    """Noms de tous les sous-programmes déclarés dans le fichier."""
    return set(re.findall(r'^\s*(?:export\s+)?program\s+(\w+)', code,
                          re.MULTILINE))


def unique_program_name(code: str, base: str) -> str:
    """Nom libre dérivé de `base` (le fichier cible a ses propres
    sous-programmes: une collision écraserait un usinage existant)."""
    taken = program_names(code)
    if base not in taken:
        return base
    k = 2
    while f"{base}_{k}" in taken:
        k += 1
    return f"{base}_{k}"


def insert_subprograms(code: str, blocks: list) -> str:
    """Insère des blocs `program … endprogram` avant le `end` final."""
    if not blocks:
        return code
    lines = code.split('\n')
    insert_at = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip() == 'end':
            insert_at = i
            break
    payload = []
    for block in blocks:
        payload.append("")
        payload.extend(block.rstrip('\n').split('\n'))
    payload.append("")
    lines[insert_at:insert_at] = payload
    return "\n".join(lines)


def insert_main_calls(code: str, calls: list,
                      after_index: int = -1) -> str:
    """Insère des lignes d'appel dans Main, après le bloc d'indice
    `after_index` (-1 = juste avant la fin de l'usinage).

    L'insertion se fait AVANT les commandes de fin (SpraySystem Off,
    Spindle Off, MoveToParkPosition) quand aucune position n'est
    donnée: y ajouter un usinage après l'arrêt broche ne servirait à
    rien."""
    if not calls:
        return code
    blocks = parse_main_blocks(code)
    if not blocks:
        return code
    _TAIL = ('SpraySystem Off', 'Spindle Off', 'MoveToParkPosition')
    if after_index is None or after_index < 0:
        pos = len(blocks)
        for i, b in enumerate(blocks):
            if b['raw'].strip() in _TAIL:
                pos = i
                break
    else:
        pos = min(after_index + 1, len(blocks))
    new_blocks = list(blocks)
    for offset, call in enumerate(calls):
        new_blocks.insert(pos + offset,
                          {'raw': call, 'name': '', 'kind': 'call',
                           'muted': False})
    return rewrite_main_blocks(code, new_blocks)


def parse_history(code: str) -> list:
    """Relit l'historique des patchs d'un fichier SimPl.

    Retourne [{'stamp', 'author', 'message'}, ...] du plus ancien au
    plus récent. Sert à savoir CE QUI a été modifié, QUAND et PAR QUI
    avant de remettre un programme en production."""
    if _HISTORY_HEADER not in code:
        return []
    section = code.split(_HISTORY_HEADER, 1)[1]
    entries = []
    for line in section.split('\n'):
        line = line.strip()
        if not line.startswith('#'):
            # une ligne non commentée termine la section
            if line:
                break
            continue
        m = re.match(r'#\s*\[([^\]]+)\]\s*(?:\(([^)]*)\)\s*)?(.*)$',
                     line)
        if not m:
            continue
        entries.append({
            'stamp': m.group(1).strip(),
            'author': (m.group(2) or '').strip(),
            'message': m.group(3).strip(),
        })
    return entries


def append_history(code: str, message: str,
                   author: str = "") -> str:
    """Ajoute une ligne d'historique horodatée en pied de programme
    (après le 'end' final). Crée la section si absente.

    L'auteur est tracé entre parenthèses: sur un poste partagé, savoir
    QUI a modifié un programme compte autant que quoi."""
    stamp = datetime.now().strftime("%d/%m/%Y %H:%M")
    who = f"({author.strip()}) " if author and author.strip() else ""
    entry = f"# [{stamp}] {who}{message}"

    lines = code.split("\n")
    if _HISTORY_HEADER in code:
        # Ajouter à la fin de la section existante — SA fin, pas
        # celle du fichier: une ligne ajoutée après les blocs $$$
        # entrait dans la dernière séquence
        debut = next(i for i, l in enumerate(lines)
                     if l.strip() == _HISTORY_HEADER)
        fin = debut
        while (fin + 1 < len(lines)
               and lines[fin + 1].strip().startswith("# [")):
            fin += 1
        lines.insert(fin + 1, entry)
        return "\n".join(lines)

    # Trouver le 'end' final (dernière ligne 'end' seule)
    insert_at = None
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip() == "end":
            insert_at = i + 1
            break
    block = ["", _HISTORY_HEADER, entry, ""]
    if insert_at is None:
        lines.extend(block)
    else:
        lines[insert_at:insert_at] = block
        # retirer les lignes vides en double après le bloc
        while (insert_at + len(block) < len(lines)
               and not lines[insert_at + len(block)].strip()):
            lines.pop(insert_at + len(block))
    return "\n".join(lines)
