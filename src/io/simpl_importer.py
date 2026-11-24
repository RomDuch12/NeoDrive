"""
Import SimPl: parse un fichier .SimPl pour reconstituer des opérations NeoDrive.
Reverse-engineering basique des commandes SimPl les plus courantes.
"""

import re
from typing import Dict, Optional
from src.core.program_model import ProgramModel, OperationInstance, ProjectSettings
from src.core.tool_library import ToolLibrary
from src.operations.registry import OperationRegistry


# Mapping commandes SimPl → types NeoDrive
SIMPL_CMD_MAP = {
    'RectangleFace': 'surfacage_rectangle',
    'CircleFace': 'surfacage_cercle',
    'CircleFromMid': 'decoupe_cercle',
    'RectangleCavity': 'poche_rectangle',
    'DrillMilling': 'percage_fraise',
    'Drill': 'percage_foret',
    'Thread': 'taraudage',
    'HelixWithFullCircle': 'helice',
    'Helix': 'helice',
}

# Regex pour extraire les paramètres d'une commande SimPl
_CMD_PATTERN = re.compile(
    r'^\s*(RectangleFace|CircleFace|CircleFromMid|RectangleCavity|'
    r'DrillMilling|Drill|Thread|HelixWithFullCircle|Helix)\s*\((.*?)\)\s*$',
    re.DOTALL)

_PARAM_PATTERN = re.compile(r'(\w+)=([^\s)]+)')
_TOOL_PATTERN = re.compile(r'Tool\s+type="([^"]+)"')
_RPM_PATTERN = re.compile(r'Rpm\s*=\s*(\d+)')
_SAFE_RAPID_PATTERN = re.compile(
    r'SafeRapid\s+X=([\d.+-]+)\s+Y=([\d.+-]+)\s+Z=([\d.+-]+)')
_PROGRAM_PATTERN = re.compile(r'^(?:export\s+)?program\s+(\w+)',
                              re.MULTILINE)
_ENDPROGRAM_PATTERN = re.compile(r'^endprogram', re.MULTILINE)
_PATTERN_CALL = re.compile(
    r'Pattern::(\w+Pattern)\s*\((.*?)\)', re.DOTALL)


def _parse_simpl_params(param_str: str) -> Dict[str, str]:
    """Extrait les paires clé=valeur d'une chaîne de paramètres SimPl."""
    result = {}
    for match in _PARAM_PATTERN.finditer(param_str):
        result[match.group(1)] = match.group(2)
    # Détecter mots-clés sans valeur (Inside, Outside, Over, BothWays, etc.)
    keywords = ['Inside', 'Outside', 'Over', 'BothWays',
                'RightHandThread', 'LeftHandThread',
                'ConventionalMilling', 'ClimbMilling', 'Metric']
    for kw in keywords:
        if kw in param_str:
            result[kw] = 'true'
    # sens d'une hélice: le mot entier (« CW » est aussi dans « CCW »)
    for kw in ('CW', 'CCW'):
        if re.search(r'(?<![A-Za-z.])' + kw + r'(?![A-Za-z])', param_str):
            result[kw] = 'true'
    return result


def _map_params(cmd: str, simpl_params: Dict) -> Dict:
    """Convertit les paramètres SimPl en paramètres NeoDrive."""
    p = {}
    # Commun
    if 'depth' in simpl_params:
        p['depth'] = float(simpl_params['depth'])
    if 'infeedZ' in simpl_params:
        p['infeed_z'] = float(simpl_params['infeedZ'])
    if 'finishingZ' in simpl_params:
        p['finishing_z'] = float(simpl_params['finishingZ'])
    if 'finishingXY' in simpl_params:
        p['finishing_xy'] = float(simpl_params['finishingXY'])
    if 'infeedFinishingZ' in simpl_params:
        p['infeed_finishing_z'] = float(simpl_params['infeedFinishingZ'])

    if cmd in ('RectangleFace', 'RectangleCavity'):
        if 'widthX' in simpl_params:
            p['width_x'] = float(simpl_params['widthX'])
        if 'widthY' in simpl_params:
            p['width_y'] = float(simpl_params['widthY'])
        if 'extensionX' in simpl_params:
            p['extension_x'] = float(simpl_params['extensionX'])
        if 'extensionY' in simpl_params:
            p['extension_y'] = float(simpl_params['extensionY'])
        if 'percentageStepover' in simpl_params:
            p['stepover'] = int(float(simpl_params['percentageStepover']))
        if 'angle' in simpl_params:
            p['angle'] = float(simpl_params['angle'])
        if 'BothWays' in simpl_params:
            p['both_ways'] = True
        if 'cornerRadius' in simpl_params:
            p['corner_radius'] = float(simpl_params['cornerRadius'])

    elif cmd == 'CircleFace':
        if 'diameter' in simpl_params:
            p['diameter'] = float(simpl_params['diameter'])
        if 'extensionDiameter' in simpl_params:
            p['extension_diameter'] = float(
                simpl_params['extensionDiameter'])
        if 'percentageStepover' in simpl_params:
            p['stepover'] = int(float(simpl_params['percentageStepover']))

    elif cmd == 'CircleFromMid':
        if 'diameter' in simpl_params:
            p['diameter'] = float(simpl_params['diameter'])
        for side in ('Inside', 'Outside', 'Over'):
            if side in simpl_params:
                p['side'] = side

    elif cmd in ('HelixWithFullCircle', 'Helix') and \
            'deltaZ' in simpl_params:
        # le mouvement du manuel (§ 5.4.2): Ø du centre de l'outil
        p['full_circle'] = cmd == 'HelixWithFullCircle'
        p['side'] = 'Centre'
        for cle, nom in (('diameter', 'diameter'), ('deltaZ', 'depth'),
                         ('pitch', 'pitch'), ('startAngle', 'start_angle')):
            try:
                p[nom] = float(simpl_params[cle])
            except (KeyError, ValueError):
                pass
        if 'CW' in simpl_params or str(simpl_params.get(
                'direction', '')).endswith('.CW'):
            p['direction'] = 'CW'

    elif cmd in ('DrillMilling', 'HelixWithFullCircle'):
        if 'diameter' in simpl_params:
            p['diameter'] = float(simpl_params['diameter'])
        for side in ('Inside', 'Outside'):
            if side in simpl_params:
                p['side'] = side

    elif cmd == 'Drill':
        pass  # depth is the main param

    elif cmd == 'Thread':
        if 'threadName' in simpl_params:
            tn = simpl_params['threadName'].strip('"')
            p['thread_name'] = tn
        for kw in ('RightHandThread', 'LeftHandThread'):
            if kw in simpl_params:
                p['direction'] = kw
        for kw in ('ConventionalMilling', 'ClimbMilling'):
            if kw in simpl_params:
                p['milling_type'] = kw
        if 'finishing' in simpl_params:
            p['finishing'] = float(simpl_params['finishing'])

    return p


#: la clé du bloc NDMETA qui porte l'empreinte du code exporté
CLE_EMPREINTE = '_empreinte_code'


def empreinte_du_code(content: str) -> str:
    """L'empreinte de ce que la machine exécute: les lignes de code,
    sans les commentaires (le bloc NDMETA, l'en-tête horodaté,
    l'historique des lots en sont), sans les blancs ni l'indentation.
    Deux fichiers de même empreinte usinent pareil."""
    import hashlib
    lignes = []
    for ligne in content.replace('﻿', '').splitlines():
        ligne = ' '.join(ligne.split())
        if not ligne or ligne.startswith(('#', '//')):
            continue
        lignes.append(ligne)
    return hashlib.sha1('\n'.join(lignes).encode(
        'utf-8', 'replace')).hexdigest()[:16]


def lignes_ndmeta(pdict: dict) -> list:
    """Les lignes « # NDMETA:… » d'un programme (≤ 28 lignes)."""
    import base64
    import json
    import math
    import zlib
    payload = json.dumps(pdict, ensure_ascii=False).encode('utf-8')
    b64 = base64.b64encode(zlib.compress(payload, 9)).decode('ascii')
    largeur = max(100, math.ceil(len(b64) / 28))
    return ["# NDMETA:" + b64[i:i + largeur]
            for i in range(0, len(b64), largeur)]


def ndmeta_a_jour(meta: Optional[dict], content: str) -> bool:
    """Le bloc NDMETA décrit-il encore le code du fichier ?

    Un .SimPl corrigé après son export (Batch édition, éditeur,
    TypeEdit) gardait son NDMETA: rouvert, il était reconstruit depuis
    lui — la correction disparaissait, et le réexport l'écrasait. Sans
    empreinte (fichier d'avant le round 25), on fait confiance."""
    if not meta:
        return False
    attendue = meta.get(CLE_EMPREINTE)
    if not attendue:
        return True
    return attendue == empreinte_du_code(content)


def sceller_ndmeta(code_avant: str, code_apres: str) -> str:
    """Un fichier NeoDrive modifié par NeoDrive (lot, éditeur): son
    NDMETA sans empreinte reçoit celle du code AVANT la modification —
    rouvert, il se lira tel qu'il est (en blocs), pas depuis le NDMETA
    périmé. Rend `code_apres`, scellé si besoin."""
    meta = extract_neodrive_metadata(code_apres)
    if meta is None or meta.get(CLE_EMPREINTE):
        return code_apres
    avant = extract_neodrive_metadata(code_avant) or {}
    empreinte = avant.get(CLE_EMPREINTE) or empreinte_du_code(code_avant)
    if empreinte == empreinte_du_code(code_apres):
        return code_apres          # rien de ce qui usine n'a changé
    meta[CLE_EMPREINTE] = empreinte
    neuves = lignes_ndmeta(meta)
    sortie, pose = [], False
    for ligne in code_apres.split('\n'):
        if re.match(r'^#\s*NDMETA:', ligne.strip()):
            if not pose:
                fin = '\r' if ligne.endswith('\r') else ''
                sortie.extend(n + fin for n in neuves)
                pose = True
            continue
        sortie.append(ligne)
    return '\n'.join(sortie)


def extract_neodrive_metadata(content: str) -> Optional[dict]:
    """Détecte et décode le bloc de métadonnées NeoDrive (# NDMETA:)
    d'un SimPl généré par NeoDrive. Retourne le dict du programme
    (format .ndp) ou None si absent/corrompu."""
    chunks = re.findall(r'^#\s*NDMETA:([A-Za-z0-9+/=]+)\s*$',
                        content, re.MULTILINE)
    if not chunks:
        return None
    try:
        import base64
        import json
        import zlib
        raw = zlib.decompress(base64.b64decode(''.join(chunks)))
        data = json.loads(raw.decode('utf-8'))
    except Exception:
        return None
    if not isinstance(data, dict) or data.get('type') != 'program':
        return None
    return data


def program_from_metadata(data: dict, tool_library: ToolLibrary,
                          content: str = "") -> ProgramModel:
    """Reconstruit un ProgramModel depuis les métadonnées NDMETA
    (reconstruction exacte, sans heuristique). Le code des séquences,
    exclu du bloc NDMETA (30 lignes max), est relu depuis les blocs
    $$$ du fichier (content); les Z du bloc étant déjà ajustés,
    z_scale/z_offset sont remis à l'identité."""
    program = ProgramModel()
    program.settings = ProjectSettings.from_dict(
        data.get('settings', {}))
    from src.core.program_model import operation_depuis_dict
    for op_data in data.get('operations', []):
        if not isinstance(op_data, dict):
            continue
        # l'outil absent du poste reste en `outil_absent`
        op = operation_depuis_dict(op_data, tool_library.tools)
        if op is None:
            continue
        blk = op.params.pop('_seq_from_block', '')
        if blk and content and not op.params.get('sequence_code'):
            m = re.search(
                r'^\$\$\$ ' + re.escape(blk) +
                r'[ \t]*\n(.*?)(?=^\$\$\$ |\Z)',
                content, re.MULTILINE | re.DOTALL)
            if m and op.operation_type == 'bloc_simpl':
                # un bloc importé garde sa ligne « $$$ NOM » (son nom
                # d'origine: celui qu'appelle son corps) — sans elle,
                # le programme régénéré appelait une séquence absente;
                # ses Z, déjà ajustés dans le fichier, ne le sont plus
                nom = str(op.params.get('sequence_name', '') or blk)
                op.params['sequence_code'] = (
                    f"$$$ {nom}\n" + m.group(1).rstrip('\n'))
                op.params['seq_z_offset'] = 0.0
                op.params['seq_z_max'] = 0.0
            elif m:
                op.params['sequence_code'] = m.group(1).rstrip('\n')
                op.params['sequence_name'] = blk
                op.params['z_scale'] = 1.0
                op.params['z_offset'] = 0.0
        program.add_operation(op)
    from src.core.program_model import expand_legacy_instances
    expand_legacy_instances(program)
    return program


def import_simpl_as_blocks(filepath: str,
                           tool_library: ToolLibrary) -> ProgramModel:
    """Charge un SimPl externe comme suite d'opérations « bloc ».

    Chaque APPEL du Main devient une opération portant le code de son
    sous-programme. Si ce sous-programme appelle une séquence, le bloc
    $$$ correspondant est embarqué AVEC lui: une séquence seule n'a ni
    outil ni avances, elle ne s'usine pas.

    Les appels commentés arrivent désactivés (enabled=False), ce qui
    conserve la mise en sourdine du fichier d'origine.

    Ce que le Main fait LUI-MÊME entre deux appels (gravure, Dialog,
    ShiftWcsInc, `if … endif`) devient une opération « Lignes du
    Main », à sa place; un appel `usermodule` (programme d'un autre
    fichier), un « Appel prog externe ».
    """
    import os
    from src.io import simpl_batch as sb

    with open(filepath, 'r', encoding='utf-8-sig',
              errors='replace') as f:
        content = f.read()

    import uuid
    program = ProgramModel()
    # Les sous-programmes d'un même fichier forment un ENSEMBLE: on
    # les replie d'un clic au lieu de noyer la liste d'opérations
    group_id = str(uuid.uuid4())[:8]
    group_name = os.path.splitext(os.path.basename(filepath))[0]
    author = re.search(r'@\s*Author\s*=\s*"([^"]*)"', content)
    if author:
        program.settings.author = author.group(1)
    comment = re.search(r'@\s*Comment\s*=\s*"([^"]*)"', content)
    if comment:
        program.settings.comment = comment.group(1)
    wp = re.search(
        r'"MinEdge"\s*:\s*\{[^}]*"X"\s*:\s*([-+\d.]+)[^}]*'
        r'"Y"\s*:\s*([-+\d.]+)[^}]*"Z"\s*:\s*([-+\d.]+)[^}]*\}'
        r'\s*,\s*"MaxEdge"\s*:\s*\{[^}]*"X"\s*:\s*([-+\d.]+)[^}]*'
        r'"Y"\s*:\s*([-+\d.]+)[^}]*"Z"\s*:\s*([-+\d.]+)', content)
    if wp:
        s = program.settings
        try:
            valeurs = [float(v) for v in wp.groups()]
        except ValueError:
            valeurs = None          # « "X": - »: en-tête abîmé, ignoré
        if valeurs:
            (s.workpiece_min_x, s.workpiece_min_y, s.workpiece_min_z,
             s.workpiece_max_x, s.workpiece_max_y,
             s.workpiece_max_z) = valeurs

    # Blocs $$$ du fichier, pour les rattacher à leur sous-programme
    seq_blocks = {}
    for m in re.finditer(r'^\$\$\$\s*(\S+)[ \t]*\n(.*?)(?=^\$\$\$ |\Z)',
                         content, re.MULTILINE | re.DOTALL):
        seq_blocks[m.group(1)] = m.group(0).rstrip('\n')

    # Références d'outils: `Tool name="X"` ne dit pas QUEL outil
    # charger. La référence vient de tools.json (par le nom) ou, à
    # défaut, de la déclaration @ ToolDescription @ du fichier.
    from src.io.simpl_analyzer import parse_tool_descriptions
    descriptions = parse_tool_descriptions(content)
    # les @ ToolDescription @ telles que le fichier les écrit, par nom
    # et par référence: l'en-tête généré les reprend (c'est la liste
    # que l'opérateur lit devant la machine) — tous les programmes
    # régénérés les perdaient
    brutes = {}
    for m in re.finditer(r'@\s*ToolDescription\s*:(.*?)@', content, re.S):
        texte = " ".join(m.group(0).split())
        for cle in ('Name', 'ArticleNr'):
            v = re.search(r'"%s"\s*:\s*"([^"]*)"' % cle, m.group(1))
            if v and v.group(1).strip():
                brutes.setdefault(v.group(1).strip(), texte)

    # les modules du fichier (`using Chuck`, `import Door`…): le
    # programme régénéré écrit les siens (Base, System, Engrave…); un
    # bloc qui appelle ChuckOpen ne se chargerait plus sans le sien
    modules_du_fichier = {}
    deja = {'using': ('Base', 'String'),
            'import': ('Base', 'String', 'System', 'DialogUtilities',
                       'Pattern', 'Engrave', 'DateTimeModule')}
    for mot in ('using', 'import'):
        noms = []
        for liste in re.findall(r'^%s\s+([^#\n]+)' % mot, content, re.M):
            noms += [x.strip() for x in liste.split(',') if x.strip()]
        # `using DialogUtilities`: ses commandes s'écrivent sans préfixe,
        # l'`import` commun du programme généré ne suffit pas
        en_plus = [x for x in dict.fromkeys(noms) if x not in deja[mot]]
        if en_plus:
            modules_du_fichier[mot] = en_plus

    def _descriptions_de(code: str) -> dict:
        """{outil pris (référence ou nom): sa @ ToolDescription @}."""
        return {v: brutes[v] for _k, v in sb.TOOL_PRIS_RE.findall(code)
                if v in brutes}
    by_name = {t.name: t.article_nr for t in tool_library.get_all_tools()
               if t.article_nr} if tool_library else {}

    def _resolve_article(declared: str, kw: str) -> str:
        if kw == 'type':
            return declared          # déjà une référence
        found = by_name.get(declared, '')
        if found:
            return found
        return (descriptions.get(declared, {}) or {}).get('article', '')

    fname = os.path.basename(filepath)
    # le fichier découpé UNE fois pour tous ses sous-programmes (un
    # programme 3D de 30 Mo se relisait entièrement pour chacun)
    prepare = sb.analyse_preparee(content)
    lines = prepare['lines']
    declares = {n for n in prepare['declared'] if n.lower() != 'main'}
    # « usermodule UM_DESSUS="network:X:\Gabarits\Dessus.simpl" »: le
    # Main appelle UM_DESSUS, programme d'un AUTRE fichier
    usermodules = dict(re.findall(
        r'^[ \t]*usermodule\s+(\w+)\s*=\s*"([^"]*)"', content,
        re.MULTILINE))
    instructions = sb.main_statements(content)

    def _bloc_de(block) -> str:
        """Le sous-programme du fichier que l'instruction appelle."""
        if block['kind'] in ('call', 'pattern') \
                and block['name'] in declares:
            return block['name']
        return ''

    blocs = {_bloc_de(b) for b in instructions} - {''}

    def _definitions(code: str):
        """Les programmes du fichier et les usermodule que des lignes
        du Main nomment sans les appeler en blocs (« result = AskFor »):
        sans eux, les lignes reprises appelleraient un inconnu."""
        mots = set(re.findall(r'[A-Za-z_]\w*', "\n".join(
            re.sub(r'"[^"]*"', '', l).split('#')[0]
            for l in code.split('\n'))))
        programmes = {}
        a_voir = [n for n in sorted(declares) if n in mots and n not in blocs]
        while a_voir:
            nom = a_voir.pop(0)
            if nom in programmes:
                continue
            debut, fin = sb.subprogram_body(content, nom, lines)
            if debut < 0:
                continue
            corps = "\n".join(lines[debut - 1:fin + 1])
            programmes[nom] = corps
            dedans = set(re.findall(r'[A-Za-z_]\w*', "\n".join(
                re.sub(r'"[^"]*"', '', l).split('#')[0]
                for l in corps.split('\n'))))
            # un programme repris qui appelle un usermodule (motif →
            # PatternProgram → MyPatternFile): sa déclaration suit
            mots |= dedans
            a_voir += [n for n in sorted(declares) if n in dedans
                       and n not in blocs and n not in programmes]
        modules = [f'usermodule {um}="{chemin}"'
                   for um, chemin in usermodules.items() if um in mots]
        return programmes, modules

    from src.operations.lignes_main import LignesMain
    en_cours: list = []
    # l'outil en broche: le dernier que le Main a pris lui-même, ou
    # qu'un sous-programme a gardé (skipRestoring) — la gravure de la
    # tranche se fait avec celui qu'une ligne précédente a pris
    en_place = ['']

    def _suivre(code: str, main: bool) -> None:
        for ligne in code.splitlines():
            m = sb.TOOL_PRIS_RE.match(ligne)
            if m and (main or 'skipRestoring' in ligne):
                en_place[0] = m.group(2)

    def _vider():
        """Les lignes du Main lues depuis le dernier appel: une
        opération si elles font plus que l'entretien (arrosage,
        broche, parking — que le Main généré écrit lui-même)."""
        if LignesMain.utile(en_cours):
            code = LignesMain.mettre_en_forme(en_cours)
            op = OperationInstance("lignes_main",
                                   LignesMain.nom_pour(en_cours))
            programmes, modules = _definitions(code)
            descriptions = _descriptions_de(code)
            op.params = {'code': code, 'source_file': fname,
                         '_programmes': programmes,
                         '_usermodules': modules,
                         '_descriptions': descriptions}
            if modules_du_fichier:
                op.params['_modules'] = modules_du_fichier
            if en_place[0] and not sb.TOOL_PRIS_RE.search(code):
                op.params['_outil_en_place'] = en_place[0]
                if en_place[0] in brutes:
                    descriptions[en_place[0]] = brutes[en_place[0]]
            op.group_id = group_id
            op.group_name = group_name
            program.add_operation(op)
            _suivre(code, True)
        en_cours.clear()

    tete = True     # rien d'utile encore lu dans le Main
    for block in instructions:
        name = _bloc_de(block)
        externe = block['name'] if block['kind'] == 'call' \
            and block['name'] in usermodules else ''
        if not name and not externe:
            # l'Absolute de tête: le Main généré l'écrit déjà
            if not (tete and block['raw'].strip() == 'Absolute'):
                en_cours.append(block['raw'])
            if block['kind'] != 'comment':
                tete = False
            continue
        tete = False
        _vider()
        if externe:
            # l'appel d'un autre fichier: « Appel prog externe », dont
            # le nom donne le même label UM_
            op = OperationInstance("appel_programme", externe)
            op.enabled = not block.get('muted', False)
            op.params = {'filepath': usermodules[externe],
                         'preview': True, 'source_file': fname}
            op.group_id = group_id
            op.group_name = group_name
            program.add_operation(op)
            continue
        start, end = sb.subprogram_body(content, name, lines)
        body = "\n".join(lines[start - 1:end + 1])
        info = sb.analyze_subprogram(content, name, prepare)
        # `Tool name=` → `Tool type="référence"` dès le chargement:
        # c'est la référence qui identifie l'outil sans ambiguïté, et
        # elle seule permet de le retrouver dans tools.json
        article = _resolve_article(info['tool'], info['tool_kw'])
        if article and info['tool_kw'] == 'name':
            body, _n = sb.set_subprogram_tool(
                body, name, article, tool_name=info['tool'])
        op = OperationInstance("bloc_simpl", name)
        op.enabled = not block.get('muted', False)
        op.params = {
            'sub_name': name,
            'source_file': fname,
            'body': body,
            # Régime et avances RÉELS du bloc: le formulaire montre
            # ce que fait le programme, pas des cases vides
            'rpm': int(info['rpm'] or 0),
            'depth_scale': 1.0, 'depth_offset': 0.0,
            'infeed_scale': 1.0, 'seq_z_offset': 0.0,
            '_kind': info['kind'],
            '_function': info['function'],
            '_tool': info['tool'],
            '_tool_comment': info.get('tool_comment', ''),
            '_article': article,
            '_rpm_origin': info['rpm'] or 0,
            '_feeds': dict(info['feeds']),
            '_params': dict(info['params']),
            '_call': block['raw'].strip().lstrip('#').strip(),
            '_descriptions': _descriptions_de(body),
        }
        if modules_du_fichier:
            op.params['_modules'] = modules_du_fichier
        from src.operations.bloc_simpl import BlocSimpl
        for field, key in BlocSimpl.FEED_KEYS.items():
            try:
                op.params[field] = int(float(
                    info['feeds'].get(key, 0) or 0))
            except (TypeError, ValueError):
                op.params[field] = 0
        if info['kind'] == 'sequence' and info['sequence']:
            op.params['sequence_name'] = info['sequence']
            op.params['sequence_code'] = seq_blocks.get(
                info['sequence'], '')
        op.group_id = group_id
        op.group_name = group_name
        program.add_operation(op)
        if op.enabled:
            _suivre(body, False)
    # l'arrosage, la broche et le parking de la fin: le Main généré
    # les écrit lui-même après la dernière opération
    while en_cours and (not en_cours[-1].strip()
                        or en_cours[-1].strip().startswith('#')
                        or en_cours[-1].split()[0] in LignesMain.ENTRETIEN):
        en_cours.pop()
    _vider()

    program.filepath = None
    program.mark_saved()
    return program


def import_simpl(filepath: str,
                 tool_library: ToolLibrary) -> ProgramModel:
    """Parse un fichier .SimPl et retourne un ProgramModel.

    Si le fichier a été généré par NeoDrive (bloc # NDMETA en pied),
    les opérations sont reconstruites à l'identique depuis les
    métadonnées; sinon, import heuristique classique."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    meta = extract_neodrive_metadata(content)
    if meta is not None and not ndmeta_a_jour(meta, content):
        # corrigé après son export: le fichier tel qu'il est, en
        # blocs (mot pour mot), pas le NDMETA périmé
        return import_simpl_as_blocks(filepath, tool_library)
    if meta is not None:
        prog = program_from_metadata(meta, tool_library, content)
        if prog.operation_count > 0:
            return prog

    program = ProgramModel()

    # Extraire les metadata
    author_m = re.search(r'Author\s*=\s*"([^"]*)"', content)
    if author_m:
        program.settings.author = author_m.group(1)
    comment_m = re.search(r'Comment\s*=\s*"([^"]*)"', content)
    if comment_m:
        program.settings.comment = comment_m.group(1)

    # Extraire les sous-programmes
    programs = {}
    for match in _PROGRAM_PATTERN.finditer(content):
        name = match.group(1)
        start = match.end()
        end_m = _ENDPROGRAM_PATTERN.search(content, start)
        if end_m:
            body = content[start:end_m.start()]
            programs[name] = body

    # Parser le Main pour l'ordre d'appel
    # « export program main » (exemples DATRON) vaut Main
    main_body = programs.get('Main') or next(
        (corps for nom, corps in programs.items() if nom.lower() == 'main'),
        '')
    call_order = []
    for line in main_body.split('\n'):
        line = line.strip()
        if not line or line.startswith('#') or line.startswith('//'):
            continue
        # Ignorer les commandes système
        if any(line.startswith(kw) for kw in (
                'Absolute', 'SpraySystem', 'Spindle', 'MoveToParkPosition',
                'if ', 'endif', 'result')):
            continue
        # Pattern call
        pat_m = _PATTERN_CALL.search(line)
        if pat_m:
            pat_params = _parse_simpl_params(pat_m.group(2))
            prog_name = pat_params.get('callProgram', '').strip('"')
            if prog_name:
                call_order.append(prog_name)
            continue
        # Direct subprogram call
        if line and not line.startswith(('Set', 'Tool', 'Rpm',
                                         'Safe', 'Begin', 'End',
                                         'Coolant', 'Smoothing',
                                         'Dynamic')):
            call_order.append(line)

    # Parser chaque sous-programme appelé
    for prog_name in call_order:
        if prog_name not in programs:
            continue
        body = programs[prog_name]

        # Extraire outil
        tool_article = None
        tool_m = _TOOL_PATTERN.search(body)
        if tool_m:
            tool_article = tool_m.group(1)

        # Extraire position
        x, y, z = 0.0, 0.0, 15.0
        pos_m = _SAFE_RAPID_PATTERN.search(body)
        if pos_m:
            x = float(pos_m.group(1))
            y = float(pos_m.group(2))
            z = float(pos_m.group(3))

        # Extraire la commande d'opération
        cmd_match = None
        for line in body.split('\n'):
            m = _CMD_PATTERN.match(line)
            if m:
                cmd_match = m
                break

        if not cmd_match:
            continue

        cmd = cmd_match.group(1)
        simpl_params = _parse_simpl_params(cmd_match.group(2))
        op_type = SIMPL_CMD_MAP.get(cmd)
        if not op_type:
            continue

        try:
            op_class = OperationRegistry.get(op_type)
        except KeyError:
            continue

        op = OperationInstance(op_type, prog_name)
        op.params = op_class.get_default_params()
        op.params.update(_map_params(cmd, simpl_params))
        op.x = x
        op.y = y
        op.z = z

        # Résoudre l'outil par article
        if tool_article and tool_library:
            for tid, tool in tool_library.tools.items():
                if tool.article_nr == tool_article:
                    op.tool_id = tid
                    break

        program.add_operation(op)

    return program
