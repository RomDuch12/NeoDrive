# -*- coding: utf-8 -*-
"""Plugin VectorDrive: NeoDrive, post-processeur Datron.

VectorDrive dessine et calcule les parcours; avec ce plugin, c'est
NeoDrive qui écrit le programme Datron (« Post-traitement » →
« NeoDrive — Datron »). Le plugin traduit les parcours en un travail
`.ndjob` (le contrat entre les deux logiciels, voir
`src/io/vectordrive_job.py` de NeoDrive), le confie à NeoDrive
(`NeoDrive --postpro`), et rend à VectorDrive le .SimPl qu'il écrit — avec
la bibliothèque d'outils de NeoDrive, et son NDMETA: le programme se
rouvre dans NeoDrive, opérations comprises, pour y ajouter palpages,
pauses ou changements d'outil. NeoDrive peut aussi l'ouvrir aussitôt.

Installation: depuis NeoDrive (Paramètres → « Post-processeur pour
VectorDrive »), qui copie ce paquet dans le dossier des plugins de
VectorDrive et y écrit `neodrive_post.json` (où est NeoDrive). Ou à la
main: copier le dossier `neodrive_post` dans
`%LOCALAPPDATA%\\VectorDrive\\plugins`, ou le citer dans la variable
VECTORDRIVE_PLUGINS.

Réglages (`neodrive_post.json`, à côté de ce fichier):
    {"neodrive": "C:/…/NeoDrive.exe"  (ou ["python", "…/main.py"]),
     "ouvrir": true,           # ouvrir aussi le programme dans NeoDrive
     "avances": "vectordrive"} # ou "neodrive": régime et avances de tools.json
La variable d'environnement NEODRIVE_EXE prime sur "neodrive".

Ce paquet n'importe rien de NeoDrive: il tourne dans VectorDrive, et ne
dépend que de la bibliothèque standard.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time

PLUGIN = {'nom': 'NeoDrive (post-processeur Datron)', 'version': '1.0.0',
          'api': 1, 'licence': 'MIT'}

#: le contrat avec NeoDrive (src/io/vectordrive_job.py)
FORMAT = "neodrive-job"
VERSION = 1
CLE_POST = 'neodrive'
LIBELLE_POST = "NeoDrive — Datron SimPL (NeoDrive écrit le programme)"
#: secondes laissées à NeoDrive pour écrire le programme
DELAI = 300


def register(api) -> None:
    api.add_post(CLE_POST, LIBELLE_POST, ecrire)


# ── les réglages ─────────────────────────────────────────────────────

def chemin_config() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "neodrive_post.json")


def config() -> dict:
    try:
        with open(chemin_config(), 'r', encoding='utf-8') as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def commande_neodrive(cfg: dict = None):
    """La commande qui lance NeoDrive (liste), ou None s'il est
    introuvable: NEODRIVE_EXE, sinon "neodrive" des réglages, sinon les
    emplacements habituels."""
    cfg = config() if cfg is None else cfg
    env = os.environ.get('NEODRIVE_EXE', '').strip()
    if env:
        return [env] if os.path.isfile(env) else None
    voulu = cfg.get('neodrive')
    if isinstance(voulu, list) and voulu:
        return [str(x) for x in voulu]
    if isinstance(voulu, str) and voulu.strip():
        return [voulu] if os.path.isfile(voulu) else None
    for candidat in (
            os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs',
                         'NeoDrive', 'NeoDrive.exe'),
            os.path.join(os.environ.get('PROGRAMFILES', ''), 'NeoDrive',
                         'NeoDrive.exe')):
        if candidat and os.path.isfile(candidat):
            return [candidat]
    return None


# ── VectorDrive → le travail ─────────────────────────────────────────

def _f(v, defaut=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(defaut)


def _outil(t) -> dict:
    cat = dict(getattr(t, 'catalog', None) or {})
    return {
        'id': str(getattr(t, 'id', '') or ''),
        'nom': str(getattr(t, 'name', '') or ''),
        'nature': str(getattr(t, 'kind', 'fraise') or 'fraise'),
        'diametre': _f(getattr(t, 'diameter', 0.0)),
        'angle': _f(getattr(t, 'angle', 0.0)),
        'pointe': _f(getattr(t, 'tip', 0.0)),
        'dents': int(_f(getattr(t, 'flutes', 1), 1)),
        'longueur_utile': _f(getattr(t, 'cut_length', 0.0)),
        'reference': str(getattr(t, 'ref', '') or cat.get('reference', '')
                         or ''),
        'fournisseur': str(getattr(t, 'vendor', '') or
                           cat.get('fournisseur', '') or ''),
        'rpm': _f(getattr(t, 'spindle', 0.0)),
        'avance': _f(getattr(t, 'feed', 0.0)),
        'plongee': _f(getattr(t, 'plunge', 0.0)),
        'rampe': _f(getattr(t, 'ramp_feed', 0.0)),
        'passe': _f(getattr(t, 'step_down', 0.0)),
        'cle_neodrive': str(cat.get('cle_neodrive', '') or ''),
        'geometrie': {k: v for k, v in (getattr(t, 'geometry', None)
                                        or {}).items()
                      if isinstance(v, (int, float, str))},
    }


def _mouvement(m) -> list:
    genre = str(getattr(m, 'kind', 'feed'))
    sortie = [genre, _f(m.x), _f(m.y), _f(m.z)]
    if genre in ('arc_cw', 'arc_ccw'):
        sortie += [_f(getattr(m, 'cx', 0.0)), _f(getattr(m, 'cy', 0.0))]
    return sortie


def _propre(valeur):
    """Une valeur JSON (les cycles portent des nombres, des textes, des
    listes; le reste devient texte)."""
    if isinstance(valeur, (bool, int, str)) or valeur is None:
        return valeur
    if isinstance(valeur, float):
        return valeur if valeur == valeur else 0.0
    if isinstance(valeur, dict):
        return {str(k): _propre(v) for k, v in valeur.items()}
    if isinstance(valeur, (list, tuple)):
        return [_propre(v) for v in valeur]
    return str(valeur)


def job_depuis_vectordrive(toolpaths, setup, *, title: str = '',
                           machine=None, stem: str = '', box_mm=None,
                           avances: str = 'vectordrive') -> dict:
    """Le travail NeoDrive des parcours et du réglage FAO de VectorDrive."""
    try:
        from vectordrive import __version__ as version_vd
    except Exception:
        version_vd = ''
    brut = None
    if box_mm is not None:
        try:
            b = [float(v) for v in box_mm]
            if len(b) == 6:         # VectorDrive: (x0, y0, z0, x1, y1, z1)
                brut = [b[0], b[3], b[1], b[4], b[2], b[5]]
            elif len(b) == 4:                       # (x0, y0, x1, y1)
                brut = [b[0], b[2], b[1], b[3], 0.0, 0.0]
        except (TypeError, ValueError):
            brut = None
    ops = list(getattr(setup, 'operations', []) or [])
    return {
        'format': FORMAT, 'version': VERSION,
        'source': {'logiciel': 'VectorDrive', 'version': str(version_vd),
                   'document': str(title or '')},
        'titre': str(title or ''), 'stem': str(stem or ''),
        'machine': str(getattr(machine, 'name', machine) or ''),
        'avances': avances,
        'brut': brut,
        'outils': [_outil(t) for t in getattr(setup, 'tools', []) or []],
        'operations': [{'id': str(getattr(o, 'id', '') or ''),
                        'nom': str(getattr(o, 'name', '') or ''),
                        'nature': str(getattr(o, 'kind', '') or ''),
                        'outil': str(getattr(o, 'tool_id', '') or ''),
                        'profondeur': _f(getattr(o, 'depth', 0.0)),
                        'passe': _f(getattr(o, 'step_down', 0.0))}
                       for o in ops],
        'parcours': [{'operation': str(getattr(tp, 'op_id', '') or ''),
                      'outil': str(getattr(tp, 'tool_id', '') or ''),
                      'nom': str(getattr(tp, 'name', '') or ''),
                      'mouvements': [_mouvement(m) for m in
                                     getattr(tp, 'moves', []) or []],
                      'cycles': _propre(list(getattr(tp, 'cycles', [])
                                             or [])),
                      'avertissements': [str(w) for w in
                                         getattr(tp, 'warnings', []) or []]}
                     for tp in toolpaths or []],
    }


# ── NeoDrive écrit le programme ──────────────────────────────────────

#: les programmes déjà écrits (VectorDrive post-traite deux fois: un
#: essai, puis le vrai, sous le nom choisi): empreinte → (SimPl, avert)
_DEJA = {}
#: le dernier programme ouvert dans NeoDrive: (empreinte, nom)
_OUVERT = [None]
#: le nom de l'essai de VectorDrive (cam_panel.post_process): l'essai
#: n'ouvre rien — après une boîte « Enregistrer » annulée, le nouvel
#: essai trouvait le travail déjà écrit et ouvrait « programme.SimPl »
ESSAI = 'programme'


def _empreinte(job: dict) -> str:
    sans_nom = dict(job, stem='')
    return hashlib.sha1(json.dumps(sans_nom, sort_keys=True,
                                   ensure_ascii=False).encode('utf-8')
                        ).hexdigest()


def dossier_echanges() -> str:
    """Où le plugin garde les travaux et les programmes qu'il ouvre dans
    NeoDrive."""
    base = os.environ.get('LOCALAPPDATA') or tempfile.gettempdir()
    d = os.path.join(base, 'NeoDrive', 'VectorDrive')
    os.makedirs(d, exist_ok=True)
    return d


def post_traiter(job: dict, commande, avances: str = 'vectordrive'):
    """(SimPl, avertissements) écrits par NeoDrive, ou (None, [raison])."""
    with tempfile.TemporaryDirectory(prefix='neodrive_post_') as d:
        chemin_job = os.path.join(d, 'travail.ndjob')
        sortie = os.path.join(d, 'programme.SimPl')
        rapport = os.path.join(d, 'rapport.json')
        with open(chemin_job, 'w', encoding='utf-8') as f:
            json.dump(job, f, ensure_ascii=False)
        options = {}
        if os.name == 'nt':
            options['creationflags'] = getattr(subprocess,
                                               'CREATE_NO_WINDOW', 0)
        try:
            fin = subprocess.run(
                list(commande) + ['--postpro', chemin_job, '--sortie', sortie,
                                  '--rapport', rapport, '--avances', avances],
                capture_output=True, text=True, timeout=DELAI, **options)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return None, [f"NeoDrive n'a pas répondu: {exc}"]
        bilan = {}
        try:
            with open(rapport, 'r', encoding='utf-8') as f:
                bilan = json.load(f)
        except (OSError, ValueError):
            pass
        if fin.returncode != 0 or not os.path.isfile(sortie):
            raison = bilan.get('erreur') or (fin.stdout or fin.stderr or ''
                                             ).strip()[-400:]
            return None, [f"NeoDrive n'a pas écrit le programme: {raison}"]
        with open(sortie, 'r', encoding='utf-8') as f:
            code = f.read()
        return code, [str(w) for w in bilan.get('avertissements', [])]


def ouvrir_dans_neodrive(commande, chemin: str) -> None:
    """Le programme s'ouvre dans NeoDrive (la fenêtre déjà ouverte le
    reçoit dans un onglet)."""
    options = {}
    if os.name == 'nt':
        options['creationflags'] = getattr(subprocess, 'DETACHED_PROCESS', 0)
    try:
        subprocess.Popen(list(commande) + [chemin], close_fds=True, **options)
    except OSError:
        pass


def ecrire(toolpaths, setup, *, title: str = '', machine=None,
           stem: str = 'programme', box_mm=None, **_autres):
    """Le post-processeur: le .SimPl écrit par NeoDrive (plus le travail
    .ndjob à côté); sans NeoDrive, le travail seul, à ouvrir dans
    NeoDrive."""
    from vectordrive.cam.post import PostResult
    cfg = config()
    avances = str(cfg.get('avances') or 'vectordrive')
    job = job_depuis_vectordrive(toolpaths, setup, title=title,
                                 machine=machine, stem=stem, box_mm=box_mm,
                                 avances=avances)
    texte_job = json.dumps(job, ensure_ascii=False, indent=1)
    nom = stem or 'programme'
    commande = commande_neodrive(cfg)
    if not commande:
        return PostResult(
            text=texte_job, extension='.ndjob', encoding='utf-8',
            warnings=["NeoDrive introuvable (réglage « neodrive » de "
                      f"{chemin_config()}, ou variable NEODRIVE_EXE): le "
                      "travail est écrit en .ndjob, à ouvrir dans NeoDrive"])
    empreinte = _empreinte(job)
    deja = empreinte in _DEJA
    if not deja:
        _DEJA.clear()               # un seul travail gardé
        _DEJA[empreinte] = post_traiter(job, commande, avances)
    code, avert = _DEJA[empreinte]
    if code is None:
        _DEJA.pop(empreinte, None)  # un nouvel essai relancera NeoDrive
        return PostResult(text=texte_job, extension='.ndjob',
                          encoding='utf-8', warnings=list(avert))
    if deja and nom != ESSAI and cfg.get('ouvrir', True) \
            and _OUVERT[0] != (empreinte, nom):
        # la seconde écriture (la vraie): une copie s'ouvre dans NeoDrive
        _OUVERT[0] = (empreinte, nom)
        d = dossier_echanges()
        copie = os.path.join(d, f"{nom}.SimPl")
        try:
            with open(copie, 'w', encoding='utf-8') as f:
                f.write(code)
            with open(os.path.join(d, f"{nom}.ndjob"), 'w',
                      encoding='utf-8') as f:
                f.write(texte_job)
            ouvrir_dans_neodrive(commande, copie)
        except OSError:
            pass
    return PostResult(text=code, extension='.SimPl', encoding='utf-8',
                      warnings=list(avert),
                      files=[(f"{nom}.SimPl", code),
                             (f"{nom}.ndjob", texte_job)])


def main(argv=None) -> int:
    """Hors de VectorDrive: `python -m neodrive_post --test` dit si
    NeoDrive est trouvé."""
    argv = sys.argv[1:] if argv is None else argv
    cmd = commande_neodrive()
    print("NeoDrive:", " ".join(cmd) if cmd else "introuvable")
    return 0 if cmd else 1


if __name__ == "__main__":
    sys.exit(main())
