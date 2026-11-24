"""Fabrique la version zippée de NeoDrive, comme VectorDrive et ZikDrive.

    python tools/publier.py [--build] [--dist DOSSIER] [--sortie DOSSIER]

1. (--build) construit la dist avec PyInstaller (neodrive.spec) ;
2. lance `NeoDrive.exe --autocontrole` dans la dist : en échec, rien
   n'est publié ;
3. sépare la dist en deux archives, chacune sous un dossier
   NeoDrive-x.y.z/ (décompressée à côté d'une installation, elle n'en
   écrase jamais les données; VERSION.txt dit la version, le commit et
   la date) :
   - versions/NeoDrive-x.y.z-portable.zip, la version LIBRE : l'exe, les
     licences, les données génériques du dépôt (DATA_LIBRE), les sources ;
   - versions/NeoDrive-x.y.z-atelier-<nom>.zip, les données de l'atelier :
     TOUT le reste de la dist (outils, favoris, gammes, réglages,
     sous-programmes, programmes outils, machine, étaux, plaques,
     catalogue, manuel DATRON…), à décompresser par-dessus la version
     libre. Privée : à ne pas diffuser ;
   la version libre seule est relancée (--autocontrole) dans un dossier
   neuf avant d'être gardée ;
4. garde les GARDER dernières versions de chaque archive dans versions/.

L'archive emporte aussi les sources du commit (SOURCES, par `git
archive`) dans sources/NeoDrive-x.y.z-sources.zip: NeoDrive est sous
licence MIT ou Apache-2.0, et Qt y est utilisé sous LGPL-3.0 — qui
reçoit l'exe doit pouvoir le reconstruire avec une autre version de Qt.

Le nom de l'atelier et les mots que la version libre ne doit JAMAIS
contenir viennent de `atelier.json`, à la racine du dépôt privé (hors
des sources publiées): {"nom": "…", "interdits": ["…"]}. Un mot
interdit dans les sources ou dans la version libre: rien n'est publié.

La version est `__version__` de src/__init__.py (0.<round>.<incrément>),
relevée à chaque commit.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import io
import json
import os
import pathlib
import re
import subprocess
import sys
import zipfile

RACINE = pathlib.Path(__file__).resolve().parents[1]
GARDER = 3
# le fouillis de la dist: sauvegardes, fichiers en cours, l'ancien exe
# mis de côté quand NeoDrive tournait pendant la construction
IGNORER = ('*.bak', '*.bak2', '*.tmp', '*.pyc', 'NeoDrive.ancien*.exe',
           '*-portable.zip')
IGNORER_DOSSIERS = ('__pycache__',)
# La version libre: l'exe, ses licences, les données GÉNÉRIQUES —
# prises dans le dépôt (celles de la dist ont pu changer à l'atelier:
# elles partent alors avec l'atelier). Le reste de la dist est l'atelier.
LIBRES = ('NeoDrive.exe', 'LICENSE.txt', 'LICENSE-MIT.txt',
          'LICENSE-APACHE.txt', 'THIRD_PARTY_NOTICES.md')
DOSSIERS_LIBRES = ('licences',)
# (pas de catalogue DATRON: l'onglet Catalogue le constitue depuis le
# webshop; ni outils, ni favoris, ni gammes: ce sont ceux de l'atelier)
DATA_LIBRE = ('default_params.json', 'materials.json', 'shortcuts.json',
              'neodrive.ico', 'icon.ico', 'NeoDriveLoad.png', 'NeoDrive.png')
# de quoi reconstruire l'exe de la version libre — et le dépôt public
SOURCES = ('src', 'main.py', 'neodrive.spec', 'requirements.txt',
           'neodrive.ico', 'integrations', 'licences', 'LICENSE.txt',
           'LICENSE-MIT.txt', 'LICENSE-APACHE.txt', 'THIRD_PARTY_NOTICES.md',
           'README.md', 'tools/comme_l_exe.py', 'tools/inventaire_exe.py',
           'tools/licences_tierces.py', 'tools/publier.py',
           'tools/depot_public.py') + tuple(
               f'data/{nom}' for nom in DATA_LIBRE)
# le fichier privé de l'atelier (voir plus haut)
CONFIG_ATELIER = 'atelier.json'


def config_atelier(racine: pathlib.Path = RACINE) -> dict:
    """atelier.json du dépôt privé ({} sans lui: version libre seule)."""
    try:
        d = json.loads((racine / CONFIG_ATELIER).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def nom_atelier(racine: pathlib.Path = RACINE) -> str:
    """« atelier-<nom> » (le nom de atelier.json), « atelier » sans lui."""
    nom = str(config_atelier(racine).get('nom') or '').strip()
    return f'atelier-{nom}' if nom else 'atelier'


def mots_interdits(racine: pathlib.Path = RACINE) -> list[str]:
    """Les mots que la version libre ne doit jamais contenir."""
    return [str(m) for m in config_atelier(racine).get('interdits') or []
            if str(m).strip()]


ATELIER = nom_atelier()
LISEZ_MOI_ATELIER = f'LISEZ-MOI-{ATELIER}.txt'


def controler_zip(archive, interdits) -> list[tuple[str, str]]:
    """(fichier, mot) de chaque fichier texte de `archive` (chemin ou
    octets; les zips emboîtés aussi) dont le nom ou le contenu porte un
    mot interdit, casse ignorée. Les binaires (exe, images) ne sont pas
    lus: leurs sources le sont."""
    mots = [m.lower() for m in interdits]
    if not mots:
        return []
    trouves = []
    flux = io.BytesIO(archive) if isinstance(archive, bytes) else archive
    with zipfile.ZipFile(flux) as z:
        for nom in z.namelist():
            if nom.endswith('/'):
                continue
            octets = z.read(nom)
            if nom.lower().endswith('.zip'):
                trouves += [(f'{nom}!{n}', m)
                            for n, m in controler_zip(octets, interdits)]
                continue
            texte = '' if b'\0' in octets[:8192] else \
                octets.decode('utf-8', 'replace').lower()
            for mot, original in zip(mots, interdits):
                if mot in nom.lower() or mot in texte:
                    trouves.append((nom, original))
    return trouves


def refuser_si_interdits(archive, quoi: str,
                         racine: pathlib.Path = RACINE) -> None:
    """SystemExit si `archive` porte un mot de l'atelier."""
    trouves = controler_zip(archive, mots_interdits(racine))
    if trouves:
        print('\n'.join(f'  {nom}: « {mot} »' for nom, mot in trouves[:40]))
        raise SystemExit(f'{quoi}: {len(trouves)} mention(s) de l\'atelier '
                         '(atelier.json) — rien n\'est publié')


def version(racine: pathlib.Path = RACINE) -> str:
    src = (racine / 'src' / '__init__.py').read_text(encoding='utf-8')
    return re.search(r"""__version__ = ['"]([^'"]+)['"]""", src).group(1)


def cle_version(v: str) -> tuple:
    """0.20.10 vient après 0.20.9."""
    return tuple(int(n) for n in v.split('.'))


def nom_archive(v: str, genre: str = 'portable') -> str:
    return f'NeoDrive-{v}-{genre}.zip'


def commit(racine: pathlib.Path = RACINE) -> str:
    """Le commit court, suivi de « + modifications » si les sources ont
    bougé depuis: l'archive ne correspond alors à aucun commit."""
    try:
        h = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=racine,
                           capture_output=True, text=True, check=True).stdout.strip()
        sale = subprocess.run(['git', 'status', '--porcelain', '--', 'src', 'main.py',
                               'neodrive.spec'], cwd=racine, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return 'inconnu'
    return h + (' + modifications non commitées' if sale else '')


def archive_des_sources(v: str, racine: pathlib.Path = RACINE,
                        ref: str = 'HEAD') -> bytes:
    """Le zip des sources du commit `ref` (SOURCES), sous
    NeoDrive-<v>-sources/. Une source absente du commit: erreur."""
    r = subprocess.run(['git', 'archive', '--format=zip',
                        f'--prefix=NeoDrive-{v}-sources/', ref, '--',
                        *SOURCES], cwd=racine, capture_output=True)
    if r.returncode != 0:
        raise SystemExit('sources introuvables dans le commit '
                         f'({r.stderr.decode("utf-8", "replace").strip()})'
                         ' : rien n\'est publié')
    return r.stdout


def fichiers(dist: pathlib.Path):
    """Les fichiers de la dist à emporter, dans un ordre stable."""
    for dossier, sous, noms in os.walk(dist):
        sous[:] = sorted(s for s in sous if s not in IGNORER_DOSSIERS)
        for nom in sorted(noms):
            if not any(fnmatch.fnmatch(nom, m) for m in IGNORER):
                yield pathlib.Path(dossier) / nom


def est_libre(rel: str) -> bool:
    """Ce fichier de la dist (chemin relatif, « / ») va-t-il dans la
    version libre ? Les modes d'emploi des dossiers de l'atelier
    (« Machine/LISEZ-MOI.txt ») et les étaux d'exemple aussi."""
    parties = rel.split('/')
    if rel in LIBRES or parties[0] in DOSSIERS_LIBRES:
        return True
    if len(parties) == 2 and fnmatch.fnmatchcase(parties[1],
                                                 'LISEZ-MOI*.txt'):
        return True
    return (len(parties) == 2 and parties[0] == 'Étaux et mandrins'
            and parties[1].endswith('_exemple.json'))


def partage(dist: pathlib.Path, racine: pathlib.Path = RACINE):
    """(libre, atelier): les (fichier source, chemin dans l'archive) de
    chaque archive, triés."""
    libre, atelier = [], []
    for f in fichiers(dist):
        rel = f.relative_to(dist).as_posix()
        if rel.startswith('data/') and rel[5:] in DATA_LIBRE:
            depot = racine / 'data' / rel[5:]
            if not depot.is_file():
                libre.append((f, rel))
            elif depot.read_bytes() != f.read_bytes():
                atelier.append((f, rel))      # changé à l'atelier
        elif est_libre(rel):
            libre.append((f, rel))
        else:
            atelier.append((f, rel))
    for nom in DATA_LIBRE:
        depot = racine / 'data' / nom
        if depot.is_file():
            libre.append((depot, f'data/{nom}'))
    def cle(paire):
        return paire[1]
    return sorted(libre, key=cle), sorted(atelier, key=cle)


def _ecrire(arrivee: pathlib.Path, v: str, contenu, extras) -> pathlib.Path:
    """L'archive sous NeoDrive-<v>/, écrite à côté puis renommée: elle
    n'apparaît qu'entière. `extras`: (chemin, octets, compression)."""
    arrivee.parent.mkdir(parents=True, exist_ok=True)
    provisoire = arrivee.with_name(arrivee.name + '.tmp')
    racine_zip = pathlib.PurePosixPath(f'NeoDrive-{v}')
    with zipfile.ZipFile(provisoire, 'w', zipfile.ZIP_DEFLATED,
                         compresslevel=6) as z:
        for f, rel in contenu:
            z.write(f, str(racine_zip / rel))
        for rel, octets, compression in extras:
            z.writestr(str(racine_zip / rel), octets,
                       compress_type=compression)
    os.replace(provisoire, arrivee)
    return arrivee


def zipper(dist: pathlib.Path, sortie: pathlib.Path, v: str, ref: str,
           date: str | None = None, sources: bytes | None = None,
           racine: pathlib.Path = RACINE) -> pathlib.Path:
    """La version libre: sortie/NeoDrive-<v>-portable.zip. `sources`: le
    zip des sources, rangé dans sources/."""
    date = date or dt.date.today().isoformat()
    extras = [('VERSION.txt', f'NeoDrive {v}\ncommit {ref}\n'
               f'construit le {date}\n'.encode('utf-8'), zipfile.ZIP_DEFLATED)]
    if sources is not None:
        # déjà compressé: rangé tel quel
        extras.append((f'sources/NeoDrive-{v}-sources.zip', sources,
                       zipfile.ZIP_STORED))
    return _ecrire(sortie / nom_archive(v), v, partage(dist, racine)[0],
                   extras)


def zipper_atelier(dist: pathlib.Path, sortie: pathlib.Path, v: str,
                   ref: str, date: str | None = None,
                   racine: pathlib.Path = RACINE) -> pathlib.Path | None:
    """Les données de l'atelier: sortie/NeoDrive-<v>-atelier-<nom>.zip
    (None s'il n'y en a pas)."""
    atelier = partage(dist, racine)[1]
    if not atelier:
        return None
    date = date or dt.date.today().isoformat()
    nom = str(config_atelier(racine).get('nom') or '').strip()
    lisez = (
        f"Données de l'atelier{' ' + nom if nom else ''} pour NeoDrive {v}\n"
        f"(commit {ref}, construit le {date})\n\n"
        "À décompresser AU MÊME ENDROIT que NeoDrive-"
        f"{v}-portable.zip (la version libre): les deux archives\n"
        f"remplissent le même dossier NeoDrive-{v}/.\n\n"
        "Elle apporte ce qui est propre à l'atelier: la bibliothèque "
        "d'outils (data/tools.json),\nles favoris, les gammes "
        "(data/gammes_atelier.json), les réglages et modèles,\nles "
        "sous-programmes (programs/), les programmes outils, la machine, "
        "les étaux et\nmandrins, les plaques de reprise, le catalogue "
        "DATRON, le manuel DATRON.\n\n"
        "Privée: ces données ne sont pas sous la licence libre de "
        "NeoDrive. Elles appartiennent\n"
        f"à l'atelier{' ' + nom if nom else ''}. Ne pas diffuser.\n")
    return _ecrire(sortie / nom_archive(v, ATELIER), v, atelier,
                   [(LISEZ_MOI_ATELIER, lisez.encode('utf-8'),
                     zipfile.ZIP_DEFLATED)])


def verifier_libre(archive: pathlib.Path) -> str:
    """La version libre SEULE, décompressée dans un dossier neuf, passe
    l'autocontrôle de l'exe: sa dernière ligne; SystemExit sinon."""
    import shutil
    import tempfile
    dossier = pathlib.Path(tempfile.mkdtemp(prefix='neodrive_libre_'))
    try:
        with zipfile.ZipFile(archive) as z:
            z.extractall(dossier)
        racine_v = next(dossier.iterdir())
        r = subprocess.run([str(racine_v / 'NeoDrive.exe'), '--autocontrole'],
                           cwd=racine_v, capture_output=True, text=True,
                           encoding='utf-8', errors='replace')
        lignes = (r.stdout + r.stderr).strip().splitlines()
        if r.returncode != 0:
            print('\n'.join(lignes))
            raise SystemExit('la version libre seule échoue à '
                             "l'autocontrôle : rien n'est publié")
        return bilan_autocontrole(lignes)
    finally:
        shutil.rmtree(dossier, ignore_errors=True)


def bilan_autocontrole(lignes) -> str:
    """La ligne « AUTOCONTROLE OK… » de la sortie de l'exe (les
    avertissements de polices de Qt arrivent après elle)."""
    bilans = [ligne for ligne in lignes if 'AUTOCONTROLE' in ligne]
    return (bilans or lignes or ['autocontrôle OK'])[-1]


def nettoyer(sortie: pathlib.Path, garder: int = GARDER) -> list[pathlib.Path]:
    """Ne garde que les `garder` dernières versions; le reste du dossier
    n'est jamais touché."""
    retirees = []
    for genre in ('portable', ATELIER):
        motif = re.compile(r'NeoDrive-(\d+\.\d+\.\d+)-%s\.zip'
                           % re.escape(genre))
        archives = sorted(
            (f for f in sortie.glob(f'NeoDrive-*-{genre}.zip')
             if motif.fullmatch(f.name)),
            key=lambda f: cle_version(motif.fullmatch(f.name).group(1)))
        retirees += archives[:-garder] if garder else archives
    for f in retirees:
        f.unlink()
    return retirees


def sha256(f: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(f, 'rb') as flux:
        for bloc in iter(lambda: flux.read(1 << 20), b''):
            h.update(bloc)
    return h.hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--build', action='store_true', help='construire la dist avant')
    ap.add_argument('--dist', default=str(RACINE / 'dist'), help='dossier de la dist')
    ap.add_argument('--sortie', default=str(RACINE / 'versions'),
                    help='dossier des versions zippées')
    args = ap.parse_args(argv)
    dist = pathlib.Path(args.dist).resolve()
    if args.build:
        subprocess.run([sys.executable, '-m', 'PyInstaller', 'neodrive.spec', '--noconfirm',
                        '--distpath', str(dist)], cwd=RACINE, check=True)
    exe = dist / 'NeoDrive.exe'
    if not exe.is_file():
        raise SystemExit(f'{exe} absent : construire la dist (--build)')
    r = subprocess.run([str(exe), '--autocontrole'], cwd=dist,
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    lignes = (r.stdout + r.stderr).strip().splitlines()
    if r.returncode != 0:
        print('\n'.join(lignes))
        raise SystemExit('autocontrôle de l\'exe en échec : rien n\'est publié')
    print(bilan_autocontrole(lignes))
    v = version()
    ref = commit()
    sources = archive_des_sources(v)
    refuser_si_interdits(sources, 'sources')
    arrivee = zipper(dist, pathlib.Path(args.sortie), v, ref,
                     sources=sources)
    try:
        refuser_si_interdits(arrivee, 'version libre')
        print('version libre seule :', verifier_libre(arrivee))
    except SystemExit:
        arrivee.unlink()
        raise
    print(f'{arrivee} : {arrivee.stat().st_size / 1e6:.1f} Mo, '
          f'sha256 {sha256(arrivee)[:16]}… (libre)')
    atelier = zipper_atelier(dist, pathlib.Path(args.sortie), v, ref)
    if atelier is not None:
        print(f'{atelier} : {atelier.stat().st_size / 1e6:.1f} Mo '
              '(données de l\'atelier, privées)')
    for f in nettoyer(arrivee.parent):
        print(f'ancienne version retirée : {f.name}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
