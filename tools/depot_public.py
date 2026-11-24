"""Le dépôt public de NeoDrive: les sources de la version libre, sans
l'historique du dépôt de développement.

    python tools/depot_public.py [--dossier DOSSIER] [--ref HEAD]
                                 [--pousser]

1. les sources du commit `--ref` (publier.SOURCES, par `git archive`)
   sont contrôlées: aucun mot de l'atelier (publier.mots_interdits);
2. elles REMPLACENT le contenu du dépôt public, un dépôt git à part
   (versions/github par défaut): son historique ne contient que des
   versions libres, jamais celui du dépôt de développement — qui a
   connu les données de l'atelier;
3. un commit « NeoDrive x.y.z » et l'étiquette vx.y.z s'y ajoutent,
   sous l'identité du dépôt public (publier.config_atelier()
   ['depot_public']: nom, courriel « noreply » de GitHub);
4. `--pousser` les envoie (git push); sans lui, rien ne quitte le poste.

Le dossier n'est jamais vidé s'il n'a pas été créé par cet outil.
"""
from __future__ import annotations

import argparse
import io
import pathlib
import shutil
import subprocess
import sys
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import publier  # noqa: E402

RACINE = publier.RACINE
DOSSIER = RACINE / 'versions' / 'github'
#: posé dans .git du dépôt public à sa création: ce dossier est à nous
MARQUE = 'neodrive-depot-public'


def gitignore() -> str:
    """Le .gitignore du dépôt public: rien de ce que l'utilisateur ou son
    atelier pose à côté de l'exe."""
    lignes = ['__pycache__/', '*.pyc', 'build/', 'dist/', 'versions/',
              'programs/', 'Machine/', 'Étaux et mandrins/',
              'Plaques de reprise/', 'Programmes outils/', 'atelier.json',
              '',
              "# data/: les données génériques seulement — outils, favoris,",
              "# gammes, catalogue et réglages sont ceux de l'utilisateur",
              'data/*']
    lignes += [f'!data/{nom}' for nom in publier.DATA_LIBRE]
    return '\n'.join(lignes) + '\n'


def git(dossier: pathlib.Path, *args, identite=None, verifier=True):
    commande = ['git']
    if identite:
        commande += ['-c', f'user.name={identite[0]}',
                     '-c', f'user.email={identite[1]}']
    return subprocess.run(commande + list(args), cwd=dossier,
                          capture_output=True, text=True,
                          encoding='utf-8', errors='replace',
                          check=verifier)


def preparer(dossier: pathlib.Path) -> None:
    """Un dépôt git neuf, ou celui que cet outil a créé; sinon refus."""
    if dossier.resolve() in (RACINE, *RACINE.parents):
        raise SystemExit(f'{dossier}: pas le dépôt de développement')
    marque = dossier / '.git' / MARQUE
    if dossier.exists() and any(dossier.iterdir()):
        if not marque.is_file():
            raise SystemExit(f'{dossier} existe et n\'est pas un dépôt '
                             'public créé par cet outil: rien n\'est touché')
        return
    dossier.mkdir(parents=True, exist_ok=True)
    git(dossier, 'init', '-q', '-b', 'main')
    marque.write_text('dépôt public de NeoDrive (tools/depot_public.py)\n',
                      encoding='utf-8')


def remplacer(dossier: pathlib.Path, sources: bytes, v: str) -> int:
    """Le contenu du dépôt public devient celui du zip des sources (sans
    son dossier NeoDrive-<v>-sources/). Rend le nombre de fichiers."""
    for chemin in dossier.iterdir():
        if chemin.name == '.git':
            continue
        if chemin.is_dir():
            shutil.rmtree(chemin)
        else:
            chemin.unlink()
    prefixe = f'NeoDrive-{v}-sources/'
    n = 0
    with zipfile.ZipFile(io.BytesIO(sources)) as z:
        for info in z.infolist():
            if info.is_dir() or not info.filename.startswith(prefixe):
                continue
            arrivee = dossier / info.filename[len(prefixe):]
            arrivee.parent.mkdir(parents=True, exist_ok=True)
            arrivee.write_bytes(z.read(info))
            n += 1
    (dossier / '.gitignore').write_text(gitignore(), encoding='utf-8')
    return n


def publier_depot(dossier: pathlib.Path = DOSSIER, ref: str = 'HEAD',
                  pousser: bool = False,
                  racine: pathlib.Path = RACINE) -> str:
    """Met le dépôt public à la version de `ref`; rend le bilan."""
    config = publier.config_atelier(racine).get('depot_public') or {}
    identite = (config.get('nom'), config.get('courriel'))
    if not all(identite):
        raise SystemExit('identité du dépôt public absente (atelier.json, '
                         '« depot_public »: nom, courriel)')
    v = publier.version(racine)
    sources = publier.archive_des_sources(v, racine, ref)
    publier.refuser_si_interdits(sources, 'sources', racine)
    preparer(dossier)
    n = remplacer(dossier, sources, v)
    git(dossier, 'add', '-A')
    if not git(dossier, 'status', '--porcelain').stdout.strip():
        bilan = f'dépôt public déjà à jour ({n} fichiers, NeoDrive {v})'
    else:
        git(dossier, 'commit', '-q', '-m', f'NeoDrive {v}',
            identite=identite)
        bilan = f'dépôt public: commit « NeoDrive {v} » ({n} fichiers)'
    etiquette = f'v{v}'
    if not git(dossier, 'tag', '-l', etiquette).stdout.strip():
        git(dossier, 'tag', etiquette)
    if pousser:
        distant = git(dossier, 'remote', verifier=False).stdout.split()
        if 'origin' not in distant:
            depot = config.get('github')
            if not depot:
                raise SystemExit('dépôt GitHub inconnu (atelier.json, '
                                 '« depot_public »: github)')
            git(dossier, 'remote', 'add', 'origin',
                f'https://github.com/{depot}.git')
        git(dossier, 'push', '-q', '-u', 'origin', 'main', '--tags')
        bilan += ' — poussé'
    return bilan


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--dossier', default=str(DOSSIER),
                    help='dossier du dépôt public')
    ap.add_argument('--ref', default='HEAD', help='commit publié')
    ap.add_argument('--pousser', action='store_true',
                    help='envoyer sur GitHub (sinon rien ne quitte le poste)')
    args = ap.parse_args(argv)
    print(publier_depot(pathlib.Path(args.dossier), args.ref, args.pousser))
    return 0


if __name__ == '__main__':
    sys.exit(main())
