"""
Analyse d'un fichier .SimPl externe (pour l'opération Appel Prog Ext).
Extrait un résumé: outils, profondeur max, filetages, positions
d'usinage (pour la prévisualisation sur le canvas DXF).

Le cache évite de re-parser à chaque changement de paramètre
(clé: chemin + mtime).
"""

import os
import re
from typing import Dict, List, Optional

# Tool type="0068443G"  skipRestoring   # Fraise 2 dents
# Tool name="4__14_Balay"   → nom d'outil, la RÉFÉRENCE est déclarée
#   dans l'en-tête: @ ToolDescription: "Name":"...", "ArticleNr":"..." @
_TOOL_RE = re.compile(
    r'Tool\s+(type|name)\s*=\s*"([^"]+)"[^\n]*?(?:#\s*(.+?)\s*$)?',
    re.MULTILINE)
_TOOL_DESC_RE = re.compile(r'@\s*ToolDescription\s*:(.*?)@', re.S)
_TD_STR_RE = re.compile(r'"(\w+)"\s*:\s*"([^"]*)"')
_TD_NUM_RE = re.compile(r'"(\w+)"\s*:\s*(-?[\d.]+)')


def parse_tool_descriptions(content: str) -> Dict[str, dict]:
    """Déclarations @ ToolDescription @ de l'en-tête d'un SimPl.

    Retourne {Name: {'article', 'vendor', 'category', 'geometry'}}.
    C'est le seul endroit où la RÉFÉRENCE (ArticleNr) d'un outil
    appelé par `Tool name="..."` est disponible, et le seul où sa
    GÉOMÉTRIE est décrite (Ø, longueur de coupe, rayon de bec, nombre
    de dents, angle de pointe, pas de filet...)."""
    from src.core.tool_library import Tool
    out: Dict[str, dict] = {}
    for m in _TOOL_DESC_RE.finditer(content):
        block = m.group(1)
        strs = dict(_TD_STR_RE.findall(block))
        nums = dict(_TD_NUM_RE.findall(block))
        name = (strs.get('Name') or '').strip()
        if not name:
            continue
        geometry = {}
        for key, caster in Tool.GEOMETRY_FIELDS.items():
            if caster is str:
                val = (strs.get(key) or '').strip()
                if val:
                    geometry[key] = val
                continue
            raw = nums.get(key)
            if raw is None:
                continue
            try:
                geometry[key] = caster(float(raw))
            except (TypeError, ValueError):
                continue
        out[name] = {
            'article': (strs.get('ArticleNr') or '').strip(),
            'vendor': (strs.get('Vendor') or '').strip(),
            'category': (strs.get('Category') or '').strip(),
            'geometry': geometry,
        }
    return out

_DEPTH_RE = re.compile(r'\bdepth\s*=\s*([\d.]+)')
_RAPID_RE = re.compile(
    r'\b(?:SafeRapid|Rapid)\s+X\s*=\s*([+-]?[\d.]+)\s+Y\s*=\s*([+-]?[\d.]+)')
_THREAD_RE = re.compile(r'threadName\s*=\s*"([^"]+)"')
_PROGRAM_RE = re.compile(r'^\s*(?:export\s+)?program\s+(\w+)', re.MULTILINE)
_ENDPROGRAM_RE = re.compile(r'^\s*endprogram\b', re.MULTILINE)
_RPM_RE = re.compile(r'\bRpm\s*=\s*(\d+)|\bnewRpm\s*[= ]\s*(\d+)')
# Commandes d'usinage reconnues pour le détail par sous-programme
_OP_CMD_RE = re.compile(
    r'^\s*(Thread|DrillMilling|Drill|Engrave::\w+|Pattern::\w+|'
    r'RectangleFace|CircleFace|RectangleCavity|CircleFromMid|'
    r'RectFromMid|HelixWithFullCircle)\b', re.MULTILINE)

# Cache: filepath -> (mtime, result)
_cache: Dict[str, tuple] = {}

# Moves de séquence Datron ($$$ SEQUENCE_N): coordonnées MODALES
_SEQ_MOVE_RE = re.compile(
    r'^(Line|Rapid|Arc\s+C?CW|PrePositioning)\b(.*)$')
_SEQ_COORD_RE = re.compile(r'\b([XYZ])\s*=\s*([+-]?[\d.]+)')

# Limite de segments par séquence pour la preview (performance)
_SEQ_MAX_SEGMENTS = 15000


def parse_sequences(content: str) -> Dict[str, Dict]:
    """Parse les blocs '$$$ SEQUENCE_N' (fichiers Datron avec
    EmbeddedSequences). Coordonnées modales: les axes non mentionnés
    conservent leur valeur.

    Retourne {nom: {'segments': [(x1,y1,x2,y2,cutting)], 'z_range':
    (zmin, zmax), 'moves': n}} — cutting=True quand le move est une
    coupe (Line/Arc) avec Z ≤ 0 (dans la matière)."""
    result: Dict[str, Dict] = {}
    current_name = None
    x = y = 0.0
    z = 100.0
    segments = []
    zmin, zmax = None, None
    moves = 0

    def _flush():
        nonlocal segments, zmin, zmax, moves
        if current_name is not None:
            result[current_name] = {
                'segments': segments,
                'z_range': (zmin, zmax),
                'moves': moves,
            }
        segments = []
        zmin = zmax = None
        moves = 0

    for line in content.split('\n'):
        stripped = line.strip()
        if stripped.startswith('$$$'):
            _flush()
            current_name = stripped[3:].strip()
            x = y = 0.0
            z = 100.0
            continue
        if current_name is None:
            continue
        m = _SEQ_MOVE_RE.match(stripped)
        if not m:
            continue
        cmd = m.group(1)
        coords = dict(_SEQ_COORD_RE.findall(m.group(2)))
        nx = float(coords['X']) if 'X' in coords else x
        ny = float(coords['Y']) if 'Y' in coords else y
        nz = float(coords['Z']) if 'Z' in coords else z
        moves += 1
        is_cut = (cmd.startswith('Line') or cmd.startswith('Arc')) \
            and (nz <= 0 or z <= 0)
        if nz <= 0.5:
            zmin = nz if zmin is None else min(zmin, nz)
            zmax = nz if zmax is None else max(zmax, nz)
        # Segment XY (ignorer les plongées pures pour le tracé 2D)
        if (nx != x or ny != y) and len(segments) < _SEQ_MAX_SEGMENTS:
            segments.append((x, y, nx, ny, is_cut))
        x, y, z = nx, ny, nz
    _flush()
    result.pop(None, None)
    return result


def _lire_sequences(filepath: str) -> Dict[str, Dict]:
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            contenu = f.read()
    except (OSError, ValueError):
        return {}
    if '$$$' not in contenu:
        return {}
    try:
        return parse_sequences(contenu)
    except Exception:
        return {}


def analyze_simpl_file(filepath: str,
                       sequences: bool = True) -> Optional[Dict]:
    """Analyse un fichier SimPl. Retourne None si illisible.

    Résultat:
        tools: [(article, nom_ou_vide), ...] (uniques, ordre d'apparition)
        max_depth: float | None
        threads: [str] filetages uniques
        programs: [str] noms de sous-programmes
        rpms: (min, max) | None
        points: [{'x','y','depth'|None}] positions d'usinage
        lines: int
        sequences: les séquences $$$ découpées — seulement si
            `sequences` (le plus long: des secondes sur un programme 3D
            de 30 Mo, que la liste des outils n'a pas à attendre)
        a_des_sequences: le fichier en porte-t-il
    """
    # un chemin écrit pour la machine (« network:X:\… »): le fichier
    # du poste
    from src.core.chemins_machine import chemin_local
    filepath = chemin_local(filepath)
    try:
        mtime = os.path.getmtime(filepath)
    except (OSError, ValueError):
        return None
    cached = _cache.get(filepath)
    if cached and cached[0] == mtime:
        resultat = cached[1]
        if sequences and not resultat.get('_sequences_lues'):
            resultat['sequences'] = _lire_sequences(filepath)
            resultat['_sequences_lues'] = True
        return resultat

    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
    except (OSError, ValueError):
        return None

    # Séparer le programme principal des séquences embarquées ($$$):
    # les moves internes des séquences ne doivent pas polluer le
    # comptage de positions/outils du programme principal
    full_content = content
    if '\n$$$' in content:
        content = content.split('\n$$$', 1)[0]

    # Les @ ToolDescription @ sont dans l'en-tête (avant le 1er $$$)
    tool_desc = parse_tool_descriptions(full_content)

    tools: List[tuple] = []
    seen_tools = set()
    for m in _TOOL_RE.finditer(content):
        kw, value = m.group(1), m.group(2).strip()
        comment = (m.group(3) or "").strip()
        if kw == 'name':
            # `Tool name="X"`: X est un NOM, la référence est dans
            # la déclaration ToolDescription correspondante
            desc = tool_desc.get(value, {})
            article = desc.get('article') or value
            name = comment or value
        else:
            article = value
            name = comment
        if article not in seen_tools:
            seen_tools.add(article)
            tools.append((article, name))

    depths = [float(v) for v in _DEPTH_RE.findall(content)]
    threads = []
    for t in _THREAD_RE.findall(content):
        if t not in threads:
            threads.append(t)
    programs = _PROGRAM_RE.findall(content)

    rpm_vals = []
    for m in _RPM_RE.finditer(content):
        v = m.group(1) or m.group(2)
        if v:
            rpm_vals.append(int(v))

    # Positions: chaque Rapid/SafeRapid ouvre un point; les depth=
    # rencontrés jusqu'au prochain Rapid lui sont associés (max).
    points: List[Dict] = []
    current = None
    for line in content.split('\n'):
        rm = _RAPID_RE.search(line)
        if rm:
            if current is not None:
                points.append(current)
            current = {'x': float(rm.group(1)),
                       'y': float(rm.group(2)),
                       'depth': None}
            # depth sur la même ligne (rare)
        dm = _DEPTH_RE.search(line)
        if dm and current is not None:
            d = float(dm.group(1))
            if current['depth'] is None or d > current['depth']:
                current['depth'] = d
    if current is not None:
        points.append(current)

    # ── Détail par sous-programme ──
    program_details = []
    for pm in _PROGRAM_RE.finditer(content):
        pname = pm.group(1)
        end_m = _ENDPROGRAM_RE.search(content, pm.end())
        body = content[pm.end():end_m.start()] if end_m else \
            content[pm.end():]
        p_tools = []
        for tm in _TOOL_RE.finditer(body):
            val = tm.group(2).strip()
            if tm.group(1) == 'name':
                val = tool_desc.get(val, {}).get('article') or val
            if val not in p_tools:
                p_tools.append(val)
        p_depths = [float(v) for v in _DEPTH_RE.findall(body)]
        p_positions = len(_RAPID_RE.findall(body))
        p_ops: Dict[str, int] = {}
        for om in _OP_CMD_RE.finditer(body):
            cmd = om.group(1)
            p_ops[cmd] = p_ops.get(cmd, 0) + 1
        program_details.append({
            'name': pname,
            'tools': p_tools,
            'max_depth': max(p_depths) if p_depths else None,
            'positions': p_positions,
            'ops': p_ops,
        })

    # Séquences Datron embarquées ($$$ SEQUENCE_N), à la demande
    a_des_sequences = '$$$' in full_content
    seqs = {}
    if sequences and a_des_sequences:
        try:
            seqs = parse_sequences(full_content)
        except Exception:
            seqs = {}

    result = {
        'filename': os.path.basename(filepath),
        'sequences': seqs,
        '_sequences_lues': bool(sequences),
        'a_des_sequences': a_des_sequences,
        'tools': tools,
        # {nom_outil: {article, vendor, category, geometry}} — sert à
        # réexporter les déclarations et à enrichir la bibliothèque
        'tool_descriptions': tool_desc,
        'max_depth': max(depths) if depths else None,
        'threads': threads,
        'programs': programs,
        'program_details': program_details,
        'rpms': (min(rpm_vals), max(rpm_vals)) if rpm_vals else None,
        'points': points,
        'lines': content.count('\n') + 1,
    }
    _cache[filepath] = (mtime, result)
    if len(_cache) > 32:
        _cache.pop(next(iter(_cache)))
    return result


def summary_text(info: Dict) -> str:
    """Formate le résumé en arborescence texte pour l'UI."""
    L = []
    n_pts = len(info.get('points', []))
    L.append(f"📄 {info.get('filename', '?')} — "
             f"{info.get('lines', 0)} lignes, {n_pts} position(s)")

    # ── Outils ──
    tools = info.get('tools', [])
    if tools:
        L.append(f"🔧 Outils ({len(tools)})")
        shown = tools[:8]
        for i, (article, name) in enumerate(shown):
            branch = "└─" if (i == len(shown) - 1
                              and len(tools) <= 8) else "├─"
            L.append(f"  {branch} {article}"
                     + (f"  {name}" if name else ""))
        if len(tools) > 8:
            L.append(f"  └─ … +{len(tools) - 8} autre(s)")

    # ── Usinage global ──
    parts = []
    if info.get('max_depth') is not None:
        parts.append(f"Pz max {info['max_depth']:g} mm")
    if info.get('threads'):
        parts.append("filetages " + ", ".join(info['threads']))
    if info.get('rpms'):
        lo, hi = info['rpms']
        parts.append(f"RPM {lo}" + (f"–{hi}" if hi != lo else ""))
    if parts:
        L.append("📏 " + " · ".join(parts))

    # ── Sous-programmes détaillés ──
    details = info.get('program_details', [])
    if details:
        L.append(f"📂 Sous-programmes ({len(details)})")
        shown = details[:12]
        for i, d in enumerate(shown):
            last = (i == len(shown) - 1 and len(details) <= 12)
            branch = "└─" if last else "├─"
            bits = []
            if d['max_depth'] is not None:
                bits.append(f"Pz {d['max_depth']:g}")
            if d['positions']:
                bits.append(f"{d['positions']} pos")
            if d['tools']:
                bits.append("outil " + ", ".join(d['tools'][:2])
                            + ("…" if len(d['tools']) > 2 else ""))
            ops = d.get('ops', {})
            if ops:
                op_str = ", ".join(
                    f"{k.split('::')[-1]}×{v}" if v > 1
                    else k.split('::')[-1]
                    for k, v in list(ops.items())[:4])
                bits.append(op_str)
            suffix = ("  ·  " + " · ".join(bits)) if bits else ""
            L.append(f"  {branch} {d['name']}{suffix}")
        if len(details) > 12:
            L.append(f"  └─ … +{len(details) - 12} autre(s)")

    # ── Séquences Datron embarquées ──
    seqs = info.get('sequences', {})
    if seqs:
        L.append(f"⚙ Séquences Datron ({len(seqs)})")
        items = list(seqs.items())[:8]
        for i, (name, s) in enumerate(items):
            branch = "└─" if (i == len(items) - 1
                              and len(seqs) <= 8) else "├─"
            zr = s.get('z_range', (None, None))
            ztxt = (f" · Z {zr[0]:g} → {zr[1]:g}"
                    if zr[0] is not None else "")
            L.append(f"  {branch} {name} · {s['moves']} moves{ztxt}")
        if len(seqs) > 8:
            L.append(f"  └─ … +{len(seqs) - 8} autre(s)")

    return "\n".join(L)
