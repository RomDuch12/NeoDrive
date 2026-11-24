# Code tiers dans NeoDrive

NeoDrive lui-même est sous licence **MIT ou Apache-2.0, au choix**
(`LICENSE.txt`, `LICENSE-MIT.txt`, `LICENSE-APACHE.txt`). Ce fichier dit
ce qui, dans NeoDrive ou dans son exe, vient d'ailleurs et reste sous sa
propre licence:

1. le code repris de VectorCraft et de CADCraft (ci-dessous);
2. les bibliothèques que l'exe embarque (Python, Qt, numpy…);
3. ce qui appartient à DATRON.

## 1. Code repris

NeoDrive reprend, réécrits en Python, des algorithmes de deux projets
publiés sous licence MIT (ou Apache-2.0, au choix du destinataire). Aucun
fichier source de ces projets n'est copié tel quel: leurs étapes et leurs
choix ont été réimplémentés ici pour l'usinage. La licence MIT demande de
garder leur avis de copyright et leur texte de licence avec le logiciel:
les voici.

| Projet | Dépôt | Repris dans NeoDrive |
|---|---|---|
| VectorCraft | https://github.com/storytold/vectorcraft | `src/io/vecteur/trace_image.py` (vectorisation d'une image: seuil, bruit, contours, lignes médianes — crate `trace`); `src/core/retouche.py` (opérations booléennes « Pathfinder » — crate `pathops`); `src/io/vecteur/metafile.py` (lecture EMF / WMF — crate `metafile`); `src/core/texte_courbe.py` (texte sur un tracé — crate `text`); `src/core/formes.py` (reconnaissance de formes — crate `geom`, `recognize`); région par clic (Shape Builder / Live Paint — crate `pathops`) |
| CADCraft | https://github.com/storytold/cadcraft | `src/core/retouche.py` (OVERKILL, JOIN, OFFSET, FILLET, CHAMFER — crate `engine`); `src/core/accrochage.py` (accrochages objet — moteur `snap`); poignées d'édition des sommets du canvas (`grips`); `src/core/arcs.py` (lissage des polylignes — crate `geom`, `spline_fit`, ici en arcs); `src/core/police_fil.py` (dessin des minuscules et de quelques signes: « CADCraft Stroke », crate `fonts`, police versée au domaine public / CC0 par ses auteurs); `src/core/retouche.py` suite (BREAK, TRIM, EXTEND, BOUNDARY, DIVIDE / MEASURE, ARRAY rectangulaire et polaire, MEASUREGEOM); `src/core/cotation.py` (DIMLINEAR, DIMALIGNED, DIMRADIUS, DIMDIAMETER, DIMANGULAR); `src/core/contraintes.py` (solveur paramétrique — crate `constraints`) |

---

## VectorCraft

```
MIT License

Copyright (c) 2026 ArtCraft Team and the VectorCraft contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## CADCraft

```
MIT License

Copyright (c) 2026 ArtCraft Team and the CADCraft contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

Les noms et logos ArtCraft, VectorCraft et CADCraft sont des marques de
l'ArtCraft Team; ils ne sont pas couverts par ces licences et NeoDrive ne
les utilise pas.

---

## 2. Bibliothèques embarquées dans l'exe

`NeoDrive.exe` (PyInstaller) emporte l'interpréteur Python et les
bibliothèques dont NeoDrive se sert. À chaque construction,
`tools/licences_tierces.py` relit ce que l'exe contient vraiment,
retrouve le paquet installé qui a fourni chaque fichier et copie les
textes de licence dans le dossier **`licences/`** de la version
portable: un dossier par composant et un `LISEZ-MOI.txt` (composant,
version, licence). En bref:

| Composant | Licence |
|---|---|
| Python (et OpenSSL, libffi, bzip2… qu'il emporte) | PSF-2.0 (OpenSSL: Apache-2.0) |
| Qt et PySide6 (Qt for Python), shiboken6 | **LGPL-3.0** |
| numpy, scipy (et OpenBLAS, le runtime gfortran) | BSD-3-Clause (gfortran: GPL-3.0 avec l'exception des bibliothèques d'exécution de GCC) |
| shapely (et GEOS) | BSD-3-Clause (GEOS: LGPL-2.1) |
| ezdxf, fontTools, pyparsing, brotli, cffi, charset-normalizer | MIT |
| pypdf, psutil, pycparser, contourpy | BSD-3-Clause |
| cryptography | Apache-2.0 ou BSD-3-Clause |
| typing_extensions | PSF-2.0 |
| le chargeur de PyInstaller | GPL-2.0 avec exception (sans effet sur le programme) |

Le tableau à jour est celui de `licences/LISEZ-MOI.txt`: s'il manque un
texte, l'autocontrôle de l'exe le refuse et `tools/publier.py` ne publie
pas.

### Qt et la LGPL-3.0

Qt et PySide6 sont utilisés sous la GNU LGPL version 3 (textes:
`licences/PySide6-…/LGPL-3.0.txt` et `GPL-3.0.txt`); ils ne sont pas
modifiés. La LGPL demande que vous puissiez faire tourner NeoDrive avec
une autre version de ces bibliothèques. L'exe les emporte sous forme de
bibliothèques dynamiques (DLL), et la version portable contient les
sources de NeoDrive (`sources/NeoDrive-x.y.z-sources.zip`) pour le
reconstruire:

1. décompresser les sources (elles ont les données génériques de
   `data/`);
2. `pip install -r requirements.txt pyinstaller`, avec la version de
   PySide6 / Qt de votre choix;
3. `python -m PyInstaller --noconfirm --clean neodrive.spec` → `dist/`.

Sources de Qt: https://download.qt.io/ — de PySide6:
https://code.qt.io/cgit/pyside/pyside-setup.git/

---

## 3. DATRON

DATRON et les noms de ses produits sont des marques de DATRON AG.
NeoDrive n'est ni édité ni approuvé par DATRON; il écrit des programmes
dans le langage SimPL des machines DATRON (interopérabilité).

NeoDrive ne livre aucun document ni aucune donnée DATRON:

- le **catalogue d'outils** n'est pas fourni: l'onglet Catalogue le
  constitue sur le poste de l'utilisateur, à sa demande, depuis les
  fiches publiques du webshop DATRON (son plan du site, puis une fiche
  à la fois); il reste à côté de l'exe (`data/catalogue_datron.json`),
  pour son usage;
- les **avances** viennent d'un modèle (coefficients ajustés, pas de
  table recopiée) ou de l'exemplaire du « High-Speed Cutting Guide » que
  l'utilisateur a chez lui (`data/coupe_datron_guide.json`, lu sur son
  poste);
- le **manuel SimPL** n'est pas fourni: F1 dans l'éditeur l'ouvre s'il
  est à côté de l'exe.

Ces documents et ces données appartiennent à DATRON AG et ne sont pas
couverts par la licence de NeoDrive.
