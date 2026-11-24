"""Lecture et modification en lot de fichiers .SimPl.

Le panneau « Édition SimPl » travaille sur une SÉLECTION (un fichier,
plusieurs, ou des dossiers entiers). Ce module fournit la partie
métier: recenser les fichiers, lire ce qu'ils contiennent (brut,
auteur, commentaire, outils employés) et appliquer une modification à
toute la sélection.

Point clé sur les outils: dans un fichier Datron, `Tool name="X"` ne
donne PAS la référence. Celle-ci n'existe que dans la déclaration
d'en-tête `@ ToolDescription : "Name":"X", "ArticleNr":"…" @`. Un
outil est donc toujours restitué avec son nom ET sa référence, plus
le régime (`Rpm = N` ou `newRpm=N`) et la ligne SetFeedTechnology qui
l'accompagnent dans le programme.
"""

import os
import re
from typing import Dict, List, Optional, Sequence, Tuple

from src.io import simpl_batch as sb
from src.io.simpl_analyzer import parse_tool_descriptions

#: extensions reconnues (Datron écrit .SimPl, certains outils .simpl)
SIMPL_EXTS = ('.simpl',)

_TOOL_LINE_RE = re.compile(r'Tool\s+(type|name)\s*=\s*"([^"]+)"')
_NEWRPM_RE = re.compile(r'newRpm\s*[= ]\s*(\d+)')
_RPM_RE = re.compile(r'^Rpm\s*=\s*(\d+)')
_PROG_RE = re.compile(r'^\s*(?:export\s+)?program\s+(\w+)')
_FEED_RE = re.compile(r'(\w+)\s*=\s*(-?[\d.]+)')
_WP_RE = re.compile(
    r'@\s*WorkpieceGeometry\s*:.*?@', re.S)
_WP_VALUES_RE = re.compile(
    r'"MinEdge"\s*:\s*\{[^}]*"X"\s*:\s*([-+\d.]+)[^}]*'
    r'"Y"\s*:\s*([-+\d.]+)[^}]*"Z"\s*:\s*([-+\d.]+)[^}]*\}'
    r'\s*,\s*"MaxEdge"\s*:\s*\{[^}]*"X"\s*:\s*([-+\d.]+)[^}]*'
    r'"Y"\s*:\s*([-+\d.]+)[^}]*"Z"\s*:\s*([-+\d.]+)')

#: ordre d'émission des avances (celui des fichiers Datron)
FEED_ORDER = ('finishing', 'approach', 'plunge', 'ramp', 'roughing')


def is_simpl(path: str) -> bool:
    return path.lower().endswith(SIMPL_EXTS)


def collect_simpl_files(paths: Sequence[str],
                        recursive: bool = True) -> List[str]:
    """Fichiers .SimPl d'une sélection mêlant fichiers et dossiers.

    Un dossier sélectionné vaut « tous les SimPl qu'il contient ».
    Le résultat est dédoublonné et trié: sélectionner un dossier ET
    un fichier qu'il contient ne le traite pas deux fois."""
    found: List[str] = []
    seen = set()

    def _add(p: str):
        key = os.path.normcase(os.path.abspath(p))
        if key not in seen:
            seen.add(key)
            found.append(p)

    for path in paths:
        if os.path.isdir(path):
            if recursive:
                for root, _dirs, files in os.walk(path):
                    for f in sorted(files):
                        if is_simpl(f):
                            _add(os.path.join(root, f))
            else:
                for f in sorted(os.listdir(path)):
                    full = os.path.join(path, f)
                    if os.path.isfile(full) and is_simpl(f):
                        _add(full)
        elif os.path.isfile(path) and is_simpl(path):
            _add(path)
    found.sort(key=lambda p: os.path.normcase(p))
    return found


# ── Lecture ───────────────────────────────────────────────────────

def parse_workpiece(content: str) -> Optional[Dict[str, float]]:
    """Dimensions du brut déclarées par @ WorkpieceGeometry @."""
    m = _WP_VALUES_RE.search(content)
    if not m:
        return None
    keys = ('min_x', 'min_y', 'min_z', 'max_x', 'max_y', 'max_z')
    try:
        return {k: float(v) for k, v in zip(keys, m.groups())}
    except ValueError:
        return None


def parse_tool_usages(content: str) -> List[Dict]:
    """Outils employés, avec leur référence, régime et avances.

    Un usage = une ligne `Tool …` et ce qui la suit dans le même
    sous-programme (régime, SetFeedTechnology). Les lignes en
    commentaire sont ignorées: elles ne s'exécutent pas."""
    descriptions = parse_tool_descriptions(content)
    usages: List[Dict] = []
    current = None
    program = ""
    for lineno, raw in enumerate(content.split('\n'), start=1):
        stripped = raw.strip()
        pm = _PROG_RE.match(raw)
        if pm:
            program = pm.group(1)
            current = None
            continue
        if stripped.startswith('$$$'):
            current = None
            program = ""
            continue
        if stripped.startswith('#'):
            continue
        tm = _TOOL_LINE_RE.search(stripped)
        if tm:
            kw, value = tm.group(1), tm.group(2)
            desc = descriptions.get(value, {})
            if kw == 'name':
                name, article = value, desc.get('article', '')
            else:
                # `Tool type="ref"`: le nom est le commentaire de fin
                # de ligne, ou celui d'une déclaration de même réf.
                article = value
                name = ""
                cm = re.search(r'#\s*(.+?)\s*$', stripped)
                if cm:
                    name = cm.group(1).strip()
                if not name:
                    name = next(
                        (n for n, d in descriptions.items()
                         if d.get('article') == value), "")
            rpm_m = _NEWRPM_RE.search(stripped)
            current = {
                'name': name, 'article': article, 'kw': kw,
                'declared': value, 'program': program,
                'line': lineno, 'feeds': {},
                'rpm': int(rpm_m.group(1)) if rpm_m else None,
                'rpm_kw': 'newRpm' if rpm_m else '',
            }
            usages.append(current)
            continue
        if current is None:
            continue
        rm = _RPM_RE.match(stripped)
        if rm:
            current['rpm'] = int(rm.group(1))
            current['rpm_kw'] = 'Rpm'
            continue
        if 'SetFeedTechnology' in stripped and not current['feeds']:
            current['feeds'] = {
                k: v for k, v in _FEED_RE.findall(stripped)
                if k != 'SetFeedTechnology'}
    return usages


def _merge_usages(usages: List[Dict]) -> List[Dict]:
    """Regroupe les usages par outil, en conservant les variantes de
    régime/avances: un même outil peut tourner différemment selon le
    sous-programme, et c'est justement ce qu'il faut voir."""
    merged: Dict[Tuple[str, str], Dict] = {}
    for u in usages:
        key = (u['article'] or '', u['name'] or u['declared'])
        entry = merged.setdefault(key, {
            'name': u['name'], 'article': u['article'],
            'declared': u['declared'], 'kw': u['kw'],
            'programs': [], 'rpms': [], 'feeds': [],
        })
        if u['program'] and u['program'] not in entry['programs']:
            entry['programs'].append(u['program'])
        if u['rpm'] is not None and u['rpm'] not in entry['rpms']:
            entry['rpms'].append(u['rpm'])
        if u['feeds'] and u['feeds'] not in entry['feeds']:
            entry['feeds'].append(u['feeds'])
    return list(merged.values())


#: cache {chemin: (mtime, résultat)} — relire 300 fichiers à chaque
#: clic serait insupportable
_cache: Dict[str, tuple] = {}


def scan_file(path: str, use_cache: bool = True) -> Dict:
    """Ce que contient un SimPl: brut, auteur, commentaire, outils.

    En cas d'erreur de lecture, 'error' est renseigné et le reste est
    vide: un fichier illisible ne doit pas interrompre le lot."""
    try:
        mtime = os.path.getmtime(path)
    except OSError as exc:
        return {'path': path, 'filename': os.path.basename(path),
                'error': str(exc), 'tools': [], 'programs': [],
                'author': '', 'comment': '', 'workpiece': None,
                'lines': 0}
    cached = _cache.get(os.path.normcase(path))
    if use_cache and cached and cached[0] == mtime:
        return _avec_machine(cached[1])
    try:
        with open(path, 'r', encoding='utf-8-sig',
                  errors='replace') as f:
            content = f.read()
    except OSError as exc:
        return {'path': path, 'filename': os.path.basename(path),
                'error': str(exc), 'tools': [], 'programs': [],
                'author': '', 'comment': '', 'workpiece': None,
                'lines': 0}

    author = re.search(r'@\s*Author\s*=\s*"([^"]*)"', content)
    comment = re.search(r'@\s*Comment\s*=\s*"([^"]*)"', content)
    result = {
        'path': path,
        'filename': os.path.basename(path),
        'error': None,
        'author': author.group(1) if author else "",
        'comment': comment.group(1) if comment else "",
        'workpiece': parse_workpiece(content),
        'tools': _merge_usages(parse_tool_usages(content)),
        'programs': [b['name'] for b in sb.parse_main_blocks(content)
                     if b['name']],
        'lines': content.count('\n') + 1,
    }
    _cache[os.path.normcase(path)] = (mtime, result)
    if len(_cache) > 512:
        _cache.pop(next(iter(_cache)))
    return _avec_machine(result)


def _avec_machine(result: Dict) -> Dict:
    """Ce que la machine a mesuré en l'exécutant (src.core.temps_reels).
    Hors du cache: une exécution de plus ne change pas la date du
    programme."""
    from src.core import temps_reels
    try:
        machine = temps_reels.resume(result['path'])
    except Exception:
        machine = None
    return dict(result, machine=machine)


def scan_files_avec(paths: Sequence[str], progression=None,
                    use_cache: bool = True) -> List[Dict]:
    """Lit chaque fichier en rendant compte; s'arrête sur demande.

    Un dossier d'atelier fait mille programmes: sans barre, on
    croyait l'application plantée; sans Annuler, elle l'était."""
    from src.core.vcarve import avancer
    scans = []
    for numero, path in enumerate(paths):
        avancer(progression, numero / max(1, len(paths)),
                f"{os.path.basename(path)} ({numero + 1}/{len(paths)})")
        scans.append(scan_file(path, use_cache=use_cache))
    avancer(progression, 1.0, f"{len(paths)} fichier(s) lus")
    return scans


def scan_files(paths: Sequence[str]) -> List[Dict]:
    return [scan_file(p) for p in collect_simpl_files(paths)]


def format_feeds(feeds: Dict[str, str]) -> str:
    """Avances dans l'ordre Datron, les inconnues à la fin."""
    if not feeds:
        return ""
        # (une SetFeedTechnology absente n'est pas une erreur)
    keys = [k for k in FEED_ORDER if k in feeds]
    keys += [k for k in feeds if k not in FEED_ORDER]
    return " ".join(f"{k}={feeds[k]}" for k in keys)


def tool_line(tool: Dict) -> str:
    """Une ligne lisible: nom, référence, régime(s), avances."""
    label = tool.get('name') or tool.get('declared') or "?"
    ref = tool.get('article') or "réf. inconnue"
    bits = [f"{label} [{ref}]"]
    rpms = tool.get('rpms') or []
    if rpms:
        bits.append(" / ".join(f"{r} tr/min" for r in rpms))
    feeds = tool.get('feeds') or []
    if feeds:
        bits.append(" / ".join(format_feeds(f) for f in feeds))
    progs = tool.get('programs') or []
    if progs:
        shown = ", ".join(progs[:3])
        if len(progs) > 3:
            shown += f" +{len(progs) - 3}"
        bits.append(f"({shown})")
    return "  ·  ".join(bits)


def summary_text(scans: Sequence[Dict]) -> str:
    """Synthèse de la sélection, fichier par fichier."""
    if not scans:
        return "Aucun fichier .SimPl dans la sélection."
    from src.core import temps_reels
    out: List[str] = []
    authors, tools_all = set(), {}
    for info in scans:
        out.append(f"📄 {info['filename']}"
                   + (f" — {info['lines']} lignes" if not info['error']
                      else ""))
        if info['error']:
            out.append(f"    ⚠ illisible: {info['error']}")
            continue
        if info['author']:
            out.append(f"    Auteur : {info['author']}")
            authors.add(info['author'])
        if info['comment']:
            out.append(f"    Commentaire : {info['comment']}")
        wp = info['workpiece']
        if wp:
            out.append(
                f"    Brut : X {wp['min_x']:g} → {wp['max_x']:g}  ·  "
                f"Y {wp['min_y']:g} → {wp['max_y']:g}  ·  "
                f"Z {wp['min_z']:g} → {wp['max_z']:g}")
        else:
            out.append("    Brut : non déclaré")
        machine = temps_reels.texte_resume(info.get('machine'))
        if machine:
            out.append(f"    ⏱ Machine : {machine}")
        if info['programs']:
            out.append(f"    Opérations ({len(info['programs'])}) : "
                       + ", ".join(info['programs'][:8])
                       + (" …" if len(info['programs']) > 8 else ""))
        for tool in info['tools']:
            out.append("    🔧 " + tool_line(tool))
            key = (tool.get('article') or '',
                   tool.get('name') or tool.get('declared'))
            tools_all[key] = tools_all.get(key, 0) + 1
    if len(scans) > 1:
        out.insert(0, f"{len(scans)} fichier(s)  ·  "
                      f"{len(tools_all)} outil(s) distinct(s)  ·  "
                      f"{len(authors)} auteur(s)")
        out.insert(1, "")
    return "\n".join(out)


def resolve_articles(scans: Sequence[Dict], tool_library) -> List[Dict]:
    """Complète les références manquantes depuis tools.json.

    Un fichier sans déclaration @ ToolDescription @ ne livre que le NOM
    de l'outil. Si la bibliothèque connaît ce nom, la référence est
    restituée — sans elle, aucun remplacement d'outil n'est fiable."""
    if tool_library is None:
        return list(scans)
    by_name = {t.name: t.article_nr
               for t in tool_library.get_all_tools() if t.article_nr}
    out = []
    for info in scans:
        tools = []
        for tool in info.get('tools', []):
            if not tool.get('article'):
                found = by_name.get(tool.get('declared')
                                    or tool.get('name') or '')
                if found:
                    tool = dict(tool, article=found, from_library=True)
            tools.append(tool)
        out.append(dict(info, tools=tools))
    return out


def all_tools(scans: Sequence[Dict]) -> List[Dict]:
    """Outils distincts de toute la sélection (pour les combos)."""
    merged: Dict[Tuple[str, str], Dict] = {}
    for info in scans:
        for tool in info.get('tools', []):
            key = (tool.get('article') or '',
                   tool.get('name') or tool.get('declared') or '')
            merged.setdefault(key, tool)
    return list(merged.values())


# ── Écriture ──────────────────────────────────────────────────────

def set_workpiece(code: str, values: Dict[str, float]) -> Tuple[str, int]:
    """Remplace (ou ajoute) la déclaration @ WorkpieceGeometry @."""
    decl = (
        f'@ WorkpieceGeometry : '
        f'"MinEdge":{{"X":{values["min_x"]:+.5f},'
        f'"Y":{values["min_y"]:+.5f},'
        f'"Z":{values["min_z"]:+.5f}}}, '
        f'"MaxEdge":{{"X":{values["max_x"]:+.5f},'
        f'"Y":{values["max_y"]:+.5f},'
        f'"Z":{values["max_z"]:+.5f}}} @')
    new_code, n = _WP_RE.subn(lambda _m: decl, code, count=1)
    if n:
        return new_code, n
    # Absente: l'insérer en en-tête, avant le premier programme
    lines = code.split('\n')
    for i, ln in enumerate(lines):
        if _PROG_RE.match(ln):
            lines.insert(i, decl)
            return "\n".join(lines), 1
    return code, 0


def _tool_scopes(lines: List[str], article: str = "",
                 name: str = "") -> List[Tuple[int, int]]:
    """Portées (début, fin) des outils visés dans le code.

    Une portée commence à la ligne `Tool …` et court jusqu'au
    prochain outil, à la fin du sous-programme ou au premier bloc
    $$$. Sans cible, toutes les portées sont retournées."""
    wanted = (article or name)
    scopes: List[Tuple[int, int]] = []
    start = -1
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        boundary = (stripped.startswith('$$$')
                    or _PROG_RE.match(ln) is not None
                    or stripped == 'endprogram')
        tm = (None if stripped.startswith('#')
              else _TOOL_LINE_RE.search(stripped))
        if tm or boundary:
            if start >= 0:
                scopes.append((start, i))
                start = -1
        if tm:
            declared = tm.group(2)
            if not wanted or declared in (article, name):
                start = i
    if start >= 0:
        scopes.append((start, len(lines)))
    return scopes


def _insert_pos(lines: List[str], start: int, end: int) -> int:
    """Où insérer sous une ligne d'outil: après les commentaires qui
    la suivent immédiatement (ils décrivent l'outil, les séparer de
    leur ligne rendrait le programme illisible)."""
    pos = start + 1
    while pos < end and lines[pos].strip().startswith('#'):
        pos += 1
    return pos


def set_all_rpm(code: str, rpm: int, article: str = "",
                name: str = "", add_missing: bool = False
                ) -> Tuple[str, int]:
    """Change le régime, éventuellement du seul outil visé.

    Les deux écritures Datron sont gérées: `newRpm=` sur la ligne
    d'outil et la ligne `Rpm = N` qui la suit. `add_missing` insère
    un `Rpm = N` quand l'outil visé n'en déclare aucun — sans cible,
    l'insertion est refusée: on ne pique pas un régime dans tous les
    blocs d'un programme."""
    lines = code.split('\n')
    count = 0
    inserts = []
    for start, end in _tool_scopes(lines, article, name):
        if _NEWRPM_RE.search(lines[start]):
            lines[start] = _NEWRPM_RE.sub(
                lambda _m: f"newRpm={int(rpm)}", lines[start])
            count += 1
            continue
        found = False
        for i in range(start + 1, end):
            if _RPM_RE.match(lines[i].strip()):
                indent = lines[i][:len(lines[i])
                                  - len(lines[i].lstrip())]
                lines[i] = f"{indent}Rpm = {int(rpm)}"
                count += 1
                found = True
                break
        if not found and add_missing and (article or name):
            inserts.append((start, _insert_pos(lines, start, end)))
    for offset, (start, pos) in enumerate(inserts):
        indent = lines[start][:len(lines[start])
                              - len(lines[start].lstrip())]
        lines.insert(pos + offset, f"{indent}Rpm = {int(rpm)}")
        count += 1
    return "\n".join(lines), count


def set_all_feeds(code: str, feeds: Dict[str, int], article: str = "",
                  name: str = "", add_missing: bool = False
                  ) -> Tuple[str, int]:
    """Réécrit les SetFeedTechnology, éventuellement du seul outil
    visé. Seules les avances fournies sont écrites: les autres
    conservent la valeur du fichier. `add_missing` ajoute la ligne
    quand l'outil visé n'en a pas (cible obligatoire)."""
    parts_given = {k: int(v) for k, v in feeds.items() if v}
    if not parts_given:
        return code, 0
    lines = code.split('\n')
    count = 0
    inserts = []
    for start, end in _tool_scopes(lines, article, name):
        found = False
        for i in range(start + 1, end):
            stripped = lines[i].strip()
            if stripped.startswith('#') \
                    or 'SetFeedTechnology' not in stripped:
                continue
            existing = {k: v for k, v in _FEED_RE.findall(stripped)
                        if k != 'SetFeedTechnology'}
            existing.update({k: str(v)
                             for k, v in parts_given.items()})
            indent = lines[i][:len(lines[i]) - len(lines[i].lstrip())]
            lines[i] = (f"{indent}SetFeedTechnology "
                        f"({format_feeds(existing)})")
            count += 1
            found = True
            break
        if not found and add_missing and (article or name):
            inserts.append((start, _insert_pos(lines, start, end)))
    parts = format_feeds({k: str(v) for k, v in parts_given.items()})
    for offset, (start, pos) in enumerate(inserts):
        indent = lines[start][:len(lines[start])
                              - len(lines[start].lstrip())]
        lines.insert(pos + offset,
                     f"{indent}SetFeedTechnology ({parts})")
        count += 1
    return "\n".join(lines), count


def set_or_add_header(code: str, field: str,
                      value: str) -> Tuple[str, int]:
    """Champ d'en-tête, ajouté s'il manque.

    Beaucoup de fichiers n'ont ni Author ni Comment: se contenter de
    remplacer laisserait la modification sans effet."""
    new_code, n = sb.set_header_field(code, field, value)
    if n:
        return new_code, n
    decl = f'@ {field} = "{str(value).replace(chr(34), chr(39))}" @'
    lines = code.split('\n')
    for i, ln in enumerate(lines):
        if re.match(r'^\s*module\b', ln):
            lines.insert(i + 1, decl)
            return "\n".join(lines), 1
    for i, ln in enumerate(lines):
        if _PROG_RE.match(ln):
            lines.insert(i, decl)
            return "\n".join(lines), 1
    return code, 0


def apply_changes(code: str, changes: Dict,
                  tool_library=None) -> Tuple[str, List[str]]:
    """Applique un lot de modifications à UN programme.

    `changes` accepte: 'tool' {'old', 'new'}, 'rpm', 'feeds',
    'depths' {'scale', 'offset', 'sequences'}, 'workpiece', 'author',
    'comment' — plus 'target' {'article', 'name'} qui restreint
    rpm/feeds à un seul outil. Retourne le code et la liste des
    modifications réellement faites (vide = aucune)."""
    done: List[str] = []
    tool = changes.get('tool') or {}
    old, new = tool.get('old', ''), tool.get('new', '')
    if old and new and old != new:
        rpm, feeds, new_name = None, None, ""
        lib_tool = (tool_library.get_tool_by_article(new)
                    if tool_library else None)
        if lib_tool is not None:
            new_name = lib_tool.name
            if tool.get('with_specs', True):
                rpm = lib_tool.rpm
                feeds = {'finishing': lib_tool.feed_finishing,
                         'approach': lib_tool.feed_approach,
                         'plunge': lib_tool.feed_plunge,
                         'ramp': lib_tool.feed_ramp,
                         'roughing': lib_tool.feed_roughing}
        code, n = sb.replace_tool(code, old, new, new_name=new_name,
                                  rpm=rpm, feeds=feeds)
        if n:
            done.append(f"outil {old} → {new} ({n}×)")

    target = changes.get('target') or {}
    t_article = target.get('article', '')
    t_name = target.get('name', '')
    add_missing = bool(changes.get('add_missing', True))
    # Avances D'ABORD: quand les deux lignes manquent, l'insertion du
    # régime les repousse et l'ordre Datron (Rpm puis
    # SetFeedTechnology, sous la ligne d'outil) est respecté.
    feeds = {k: v for k, v in (changes.get('feeds') or {}).items() if v}
    feed_msg = ""
    if feeds:
        code, n = set_all_feeds(code, feeds, t_article, t_name,
                                add_missing=add_missing)
        if n:
            shown = format_feeds({k: str(v) for k, v in feeds.items()})
            feed_msg = f"avances {shown} ({n}×)"
    rpm = changes.get('rpm')
    if rpm:
        code, n = set_all_rpm(code, int(rpm), t_article, t_name,
                              add_missing=add_missing)
        if n:
            done.append(f"régime {int(rpm)} tr/min ({n}×)")
    if feed_msg:
        done.append(feed_msg)
    # Profondeur finale des séquences: tronque ou prolonge selon la
    # cote demandée (mêmes règles que sur un bloc importé)
    z_target = float(changes.get('sequence_depth', 0.0) or 0.0)
    if z_target < 0:
        n = 0
        if changes.get('sequence_depth_extend'):
            code, n = sb.set_sequence_depth(code, z_target)
        else:
            # En lot, on ne descend PAS plus bas que prévu: une
            # gravure à -0,1 deviendrait un usinage à -3. Seules les
            # séquences plus profondes que la cote sont ramenées.
            for name in sb.sequence_names(code):
                levels = sb.sequence_z_levels(code, name)
                if levels and z_target > min(levels):
                    code, k = sb.set_sequence_depth(code, z_target,
                                                    name)
                    n += k
        if n:
            done.append(f"Z final des séquences {z_target:g} mm ({n}×)")

    depths = changes.get('depths') or {}
    scale = float(depths.get('scale', 1.0) or 1.0)
    offset = float(depths.get('offset', 0.0) or 0.0)
    if scale != 1.0 or offset != 0.0:
        code, n = sb.adjust_depths(code, offset=offset, scale=scale,
                                   program=str(depths.get('program', '')))
        if n:
            done.append(f"profondeurs ×{scale:g} {offset:+g} mm ({n}×)")
        if depths.get('sequences'):
            # Les séquences portent leur Z ligne à ligne: sans elles,
            # seules les fonctions Datron seraient reprises
            code, n = sb.adjust_sequence_z(code, offset=offset,
                                           scale=scale)
            if n:
                done.append(f"Z de séquence ×{scale:g} {offset:+g} mm "
                            f"({n}×)")
    wp = changes.get('workpiece')
    if wp:
        code, n = set_workpiece(code, wp)
        if n:
            done.append("brut mis à jour")
    author = str(changes.get('author', '') or '').strip()
    if author:
        code, n = set_or_add_header(code, "Author", author)
        if n:
            done.append(f"auteur {author}")
    comment = str(changes.get('comment', '') or '').strip()
    if comment:
        code, n = set_or_add_header(code, "Comment", comment)
        if n:
            done.append("commentaire mis à jour")
    return code, done


def apply_to_files(paths: Sequence[str], changes: Dict,
                   tool_library=None, author: str = "",
                   backup: bool = True, progression=None) -> List[Dict]:
    """Applique le lot à chaque fichier et l'enregistre.

    Un fichier non modifié n'est PAS réécrit: pas de .bak inutile ni
    d'entrée d'historique vide. Retourne un rapport par fichier.

    `progression` rend compte fichier par fichier; l'arrêt laisse
    les fichiers déjà traités dans leur nouvel état (chacun est
    complet ou intact, jamais à moitié écrit) et le rapport ne
    parle que d'eux."""
    from src.core.vcarve import Annule, avancer
    report: List[Dict] = []
    fichiers = collect_simpl_files(paths)
    for numero, path in enumerate(fichiers):
        try:
            avancer(progression, numero / max(1, len(fichiers)),
                    f"{os.path.basename(path)} "
                    f"({numero + 1}/{len(fichiers)})")
        except Annule:
            break
        entry = {'path': path, 'filename': os.path.basename(path),
                 'done': [], 'error': None}
        try:
            with open(path, 'r', encoding='utf-8-sig',
                      errors='replace') as f:
                code = f.read()
        except OSError as exc:
            entry['error'] = str(exc)
            report.append(entry)
            continue
        new_code, done = apply_changes(code, changes, tool_library)
        entry['done'] = done
        if not done:
            report.append(entry)
            continue
        new_code = sb.append_history(
            new_code, "Batch: " + ", ".join(done), author=author)
        # un fichier NeoDrive: son NDMETA ne décrit plus le code —
        # rouvert, il se lira tel qu'il est, pas depuis le NDMETA
        from src.io.simpl_importer import sceller_ndmeta
        new_code = sceller_ndmeta(code, new_code)
        try:
            from src.core.fichiers_surs import ecrire_texte_sur
            ecrire_texte_sur(path, new_code, garder_bak=backup)
        except OSError as exc:
            entry['error'] = str(exc)
        report.append(entry)
        _cache.pop(os.path.normcase(path), None)
    return report
