"""Les temps réels de la machine: ce que la DATRON a mesuré en exécutant
un programme, et ce qu'elle en avait estimé.

À côté de chaque programme exécuté, la machine laisse un dossier
« <programme>.simpl.MetaData »:

- `Timestamps/<n>_<date>_<nom>_Runtime.csv`: une exécution, horodatée à
  la seconde — StartProgram, BeginBlock/EndBlock de chaque bloc,
  ToolChange (le nom de l'outil), EndProgram (absent si l'exécution a
  été interrompue);
- `SimulationData_Statisitic.json` (sic): « ExpectedRuntime »,
  l'estimation de la machine (aussi « ExpectedExecutionDuration » de
  Properties.json).

Une exécution réelle compte aussi les pauses de l'opérateur (porte
ouverte, Pause programmée): la médiane des exécutions complètes est la
mesure la moins trompeuse.
"""

import csv
import json
import os
import re
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

FORMAT_HEURE = "%Y.%m.%d_%H:%M:%S"
SUFFIXE = ".MetaData"


@dataclass
class Execution:
    """Une exécution du programme sur la machine."""
    fichier: str
    debut: datetime
    fin: Optional[datetime] = None
    #: (nom du bloc, durée en s), dans l'ordre
    blocs: List[Tuple[str, float]] = field(default_factory=list)
    #: (secondes depuis le début, nom de l'outil)
    outils: List[Tuple[float, str]] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return self.fin is not None

    @property
    def duree(self) -> Optional[float]:
        if self.fin is None:
            return None
        return max(0.0, (self.fin - self.debut).total_seconds())


def dossier_metadonnees(chemin_programme: str) -> Optional[str]:
    """Le dossier « .MetaData » d'un programme, ou None."""
    if not chemin_programme:
        return None
    dossier = chemin_programme + SUFFIXE
    if os.path.isdir(dossier):
        return dossier
    # l'extension a pu changer de casse (.SimPl copié en .simpl)
    parent = os.path.dirname(chemin_programme) or "."
    attendu = (os.path.basename(chemin_programme) + SUFFIXE).lower()
    nom = _noms_du_dossier(parent).get(attendu)
    if nom is not None and os.path.isdir(os.path.join(parent, nom)):
        return os.path.join(parent, nom)
    return None


#: {dossier: (date, {nom en minuscules: nom})} — un dossier d'atelier
#: de mille programmes n'est listé qu'une fois, pas mille
_LISTES: Dict[str, Tuple[float, Dict[str, str]]] = {}


def _noms_du_dossier(dossier: str) -> Dict[str, str]:
    try:
        date = os.path.getmtime(dossier)
        connu = _LISTES.get(dossier)
        if connu is not None and connu[0] == date:
            return connu[1]
        noms = {n.lower(): n for n in os.listdir(dossier)
                if n.lower().endswith(SUFFIXE.lower())}
    except (OSError, ValueError):
        return {}
    _LISTES[dossier] = (date, noms)
    if len(_LISTES) > 256:
        _LISTES.pop(next(iter(_LISTES)))
    return noms


def _heure(texte: str) -> Optional[datetime]:
    try:
        return datetime.strptime(texte.strip(), FORMAT_HEURE)
    except (ValueError, AttributeError):
        return None


def lire_execution(chemin_csv: str) -> Optional[Execution]:
    """Une exécution depuis son Runtime.csv; None s'il est illisible ou
    sans StartProgram."""
    try:
        with open(chemin_csv, encoding="utf-8-sig", errors="replace",
                  newline="") as f:
            lignes = list(csv.reader(f, delimiter=";"))
    except (OSError, ValueError):
        return None
    execution = None
    ouverts: Dict[str, datetime] = {}
    #: la fin du bloc précédent: le premier bloc démarre souvent avec le
    #: programme, sans BeginBlock
    precedente = None
    for ligne in lignes:
        if len(ligne) < 2:
            continue
        quand = _heure(ligne[0])
        if quand is None:
            continue
        genre = ligne[1].strip()
        info = ligne[2].strip() if len(ligne) > 2 else ""
        if genre == "StartProgram":
            if execution is None:
                execution = Execution(chemin_csv, quand)
                precedente = quand
            continue
        if execution is None:
            continue
        if genre == "BeginBlock":
            ouverts[info] = quand
        elif genre == "EndBlock":
            debut = ouverts.pop(info, precedente)
            execution.blocs.append(
                (info, max(0.0, (quand - debut).total_seconds())))
            precedente = quand
        elif genre == "ToolChange":
            execution.outils.append(
                ((quand - execution.debut).total_seconds(), info))
        elif genre == "EndProgram":
            execution.fin = quand
    return execution


def executions(chemin_programme: str) -> List[Execution]:
    """Les exécutions enregistrées par la machine, de la plus ancienne à
    la plus récente."""
    dossier = dossier_metadonnees(chemin_programme)
    if dossier is None:
        return []
    horodatages = os.path.join(dossier, "Timestamps")
    try:
        noms = os.listdir(horodatages)
    except (OSError, ValueError):
        return []
    sortie = []
    for nom in noms:
        if nom.lower().endswith("_runtime.csv"):
            ex = lire_execution(os.path.join(horodatages, nom))
            if ex is not None:
                sortie.append(ex)
    sortie.sort(key=lambda e: e.debut)
    return sortie


_DUREE = re.compile(r"^(?:(\d+)\.)?(\d+):(\d{1,2}):(\d{1,2}(?:\.\d+)?)$")


def secondes(texte) -> Optional[float]:
    """« 00:06:45 », « 1.02:03:04 » (jours.h:m:s), « 00:00:12.5 » → s."""
    m = _DUREE.match(str(texte or "").strip())
    if not m:
        return None
    jours, h, mi, s = m.groups()
    return (int(jours or 0) * 86400 + int(h) * 3600 + int(mi) * 60
            + float(s))


def estimation_datron(chemin_programme: str) -> Optional[float]:
    """Le temps que la machine avait estimé (s), ou None."""
    dossier = dossier_metadonnees(chemin_programme)
    if dossier is None:
        return None
    for nom, cle in (("SimulationData_Statisitic.json", "ExpectedRuntime"),
                     ("SimulationData_Statistic.json", "ExpectedRuntime"),
                     ("Properties.json", "ExpectedExecutionDuration")):
        try:
            with open(os.path.join(dossier, nom), encoding="utf-8-sig",
                      errors="replace") as f:
                valeur = secondes(json.load(f).get(cle))
        except (OSError, ValueError, AttributeError):
            continue
        if valeur:
            return valeur
    return None


def resume(chemin_programme: str) -> Optional[Dict]:
    """Ce que la machine sait du programme, ou None si elle ne l'a
    jamais simulé ni exécuté: nombre d'exécutions (complètes), médiane
    et dernière durée des complètes, date de la dernière, estimation
    de la machine."""
    liste = executions(chemin_programme)
    estimee = estimation_datron(chemin_programme)
    if not liste and estimee is None:
        return None
    completes = [e for e in liste if e.complete]
    durees = [e.duree for e in completes]
    return {
        'executions': len(liste),
        'completes': len(completes),
        'mediane': statistics.median(durees) if durees else None,
        'derniere': liste[-1].debut if liste else None,
        'derniere_duree': completes[-1].duree if completes else None,
        'estimation_datron': estimee,
    }


def texte_court(res: Optional[Dict], prefixe: str = "") -> str:
    """Pour une ligne d'état: « mesuré sur la machine 9 min 34 s
    (médiane de 4) »,
    sinon « estimé par la machine 6 min 45 s », vide sans rien de connu
    (`prefixe` devant, s'il y a quelque chose)."""
    if not res:
        return ""
    from src.core.sim3d import duree_lisible
    if res.get('mediane') is not None:
        n = res['completes']
        return (f"{prefixe}mesuré sur la machine "
                f"{duree_lisible(res['mediane'])}"
                + (f" (médiane de {n})" if n > 1 else ""))
    if res.get('estimation_datron'):
        return (f"{prefixe}estimé par la machine "
                f"{duree_lisible(res['estimation_datron'])}")
    return ""


def texte_resume(res: Optional[Dict]) -> str:
    """« 4 exécutions (1 interrompue), médiane 9 min 34 s, estimé par la
    machine 6 min 45 s, dernière le 07/05/2025 » — vide sans rien de
    connu."""
    if not res:
        return ""
    from src.core.sim3d import duree_lisible
    morceaux = []
    if res['executions']:
        n = res['executions']
        txt = f"{n} exécution{'s' if n > 1 else ''}"
        if res['completes'] < n:
            txt += f" ({n - res['completes']} interrompue" \
                   f"{'s' if n - res['completes'] > 1 else ''})"
        if res['mediane'] is not None:
            txt += (", " if res['completes'] == 1 else ", médiane ") \
                + duree_lisible(res['mediane'])
        morceaux.append(txt)
    if res['estimation_datron']:
        morceaux.append(f"estimé par la machine "
                        f"{duree_lisible(res['estimation_datron'])}")
    if res['derniere'] is not None:
        morceaux.append(f"dernière le {res['derniere']:%d/%m/%Y}")
    return ", ".join(morceaux)
