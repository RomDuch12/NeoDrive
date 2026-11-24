# NeoDrive

Générateur de programmes **SimPL** pour les fraiseuses DATRON, en
Python / PySide6 : on compose la liste des opérations (perçages,
taraudages, poches, contours, gravures, palpages…), NeoDrive écrit le
programme, le simule en 3D et le contrôle avant qu'il parte sur la
machine.

**Logiciel libre**, sous double licence **MIT ou Apache-2.0**, au choix
([LICENSE-MIT.txt](LICENSE-MIT.txt), [LICENSE-APACHE.txt](LICENSE-APACHE.txt),
[LICENSE.txt](LICENSE.txt)). NeoDrive ne contient aucune donnée
d'atelier : la bibliothèque d'outils, les favoris, les gammes, les
sous-programmes, la machine et ses étaux d'un atelier sont ses données,
posées à côté de l'exe.

## Ce qu'il fait

- **Opérations** : perçage au foret ou à la fraise, taraudage et
  filetage, poches et découpes, contours et gravure 2,5D (au V, évidement,
  reprise d'un outil à l'autre), gravure de texte, hélices, palpages,
  dialogues opérateur, appels de sous-programmes, et les commandes du
  manuel SimPL.
- **Canva 2D** : import DXF / DWG / SVG / PDF / EMF, vectorisation
  d'image, retouches de dessin (accrochages, ajuster, réseaux, cotes,
  contraintes), tracé compensé.
- **Canva 3D** : import STEP / STL / IGES / 3DXML, usinage des faces,
  simulation du programme écrit (enlèvement de matière, collisions,
  étaux et brides), temps machine.
- **Programmes existants** : import d'un programme SimPL en blocs,
  contrôle de structure, éditeur avec la syntaxe des commandes.
- **Outils** : bibliothèque (`data/tools.json`), fiches et dessins
  d'outils, avances proposées par un modèle.
- **Catalogue DATRON** : pas fourni. L'onglet Catalogue le constitue sur
  le poste, à la demande, depuis les fiches publiques du webshop DATRON
  (en fond, reprise après une interruption) ; il reste sur le poste.
- **VectorDrive** : NeoDrive peut servir de post-processeur à
  [VectorDrive](https://github.com/RomDuch12/VectorDrive).

## Démarrer

```bash
pip install -r requirements.txt
python main.py                    # interface
python main.py --autocontrole     # contrôle de l'installation
```

Python 3.13, Windows 10/11.

## Construire l'exe

```bash
pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --clean neodrive.spec    # → dist/
dist/NeoDrive.exe --autocontrole
python tools/publier.py           # → versions/NeoDrive-x.y.z-portable.zip
```

La construction copie à côté de l'exe les licences de tout ce qu'il
embarque (`licences/`, voir [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)) ;
Qt y est utilisé sous LGPL-3.0, et la version portable emporte ces
sources pour le reconstruire avec une autre version de Qt.

## Données d'un atelier

Ce qui est propre à un atelier n'est pas dans ce dépôt et se pose à côté
de l'exe, dans `data/` et ses dossiers : `tools.json` (outils),
`favorites.json`, `gammes_atelier.json` (gammes livrées à l'atelier,
lues et jamais modifiées), `programs/` (sous-programmes), `Machine/`,
`Étaux et mandrins/`, `Plaques de reprise/`. Sans elles, NeoDrive démarre
avec une bibliothèque par défaut et une gamme de base.

## DATRON

DATRON et SimPL sont des marques de DATRON AG. NeoDrive n'est ni édité
ni approuvé par DATRON ; il écrit des programmes dans le langage de ses
machines. Il ne livre aucun document ni aucune donnée DATRON (manuel,
catalogue, données de coupe) : voir [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

---

*English.* NeoDrive writes SimPL programs for DATRON milling machines
(operation list, 2D/3D canvas, 3D simulation, program checks). Free
software, dual-licensed MIT or Apache-2.0. It ships no workshop data and
no DATRON document or data; DATRON and SimPL are trademarks of DATRON
AG, which neither publishes nor endorses NeoDrive.
