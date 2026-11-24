"""Opérations « Commandes du manuel »: une opération par commande SimPL du
manuel 3.1.1 que NeoDrive n'écrivait pas encore (octobre 2026, RomDuch:
« implement all functions from datron_doc »).

Leur syntaxe vient du manuel lui-même (`src/core/simpl_syntaxe.py`, écrit
par tools/extraire_manuel.py): appel, paramètres et leurs valeurs, choix
des énumérations. Chaque commande devient une opération en ligne (dans
Main, à sa place dans la liste), rangée par famille, en mode expert:

    ZAxisOffset offset=0.1
    WaitForUserInput input=UserInput.INPUT_1 value=Activation.On timeout=1000
    resultat = GetUserInput input=UserInput.INPUT_1

Un paramètre facultatif vide n'est pas écrit. Les fonctions qui RENDENT
une valeur (Get…, …Existing) la rangent dans une variable (son nom est un
champ), que les opérations suivantes peuvent lire (Fonction custom).
« Arguments en plus » ajoute un texte tel quel (ce que le manuel ne dit
pas, une syntaxe particulière).
"""

from typing import Any, Dict, List

from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement
)
from src.operations.registry import OperationRegistry

#: les commandes écrites par ces opérations (les autres le sont déjà par
#: des opérations NeoDrive à elles); ThreadCutting et SpecialThread,
#: cycles d'usinage avec outil et positions, ont les leurs
A_ECRIRE = (
    'AddCommandToCommandClipboard', 'BlastAirTimes', 'BlowClearWorkpiece',
    'BlowClearWorkpieceNozzle', 'CameraSaveImage', 'CameraScanCode',
    'ChipConveyor', 'CreateSpecialTool', 'CreateWcs', 'DateTime',
    'DeleteWcs', 'EdgeMeasure', 'EndlessMotion', 'Fitting',
    'GetAutomationInput', 'GetAutomationOutput',
    'GetCurrentFittingCorrection', 'GetIsoDrillTolerance', 'GetTool',
    'GetUserInput', 'GetUserOutput', 'GetVacuumValue', 'Incremental',
    'Ionization', 'LoadWcs', 'MeasuringSettings', 'MirrorLcs',
    'MovingDirection', 'MultiAxisMode', 'NewVisionPosition',
    'OilMistExtraction', 'PathCorrection', 'PathOffset',
    'PlaneOrientationMeasure', 'PrepareXyzSensor', 'ProvideTool',
    'ReleaseDoor', 'ResetWcs', 'RotatoryAxisRadius', 'Rtcp',
    'RunExternalProgram', 'RunExternalSequence',
    'SaveCurrentFittingCorrection', 'SaveWcs', 'ScaleLcsAbs',
    'ScheduleMachineShutdown', 'SetAutomationOutput',
    'SetAutomationOutputs', 'SetLcsInitial', 'SetSpecialToolCaptureRange',
    'SetSpecialToolOffset', 'SetTool', 'SetToolIsLocked', 'SetUserOutput',
    'SetUserOutputs', 'SetWcsInitial', 'SetWcsOnTcp', 'ShiftWcsAbs',
    'SprayDirection', 'SprayTechnology', 'Suction',
    'SurfaceCompensationDataDelete', 'SurfaceCompensationDataExisting',
    'SurfaceCompensationDataLoad', 'SurfaceCompensationDataSave',
    'SurfaceCompensationZGridMeasure', 'ToolCompensation',
    'UnprepareXyzSensor', 'UserErrorHandling', 'VisionMeasureDualPosition',
    'VisionMeasureSinglePosition', 'WaitForAutomationInput',
    'WaitForUserInput', 'WcsExisting', 'WorkPlane', 'WorkpieceCooler',
    'ZAxisOffset',
)
#: celles qui rendent une valeur (rangée dans une variable)
REQUETES = {
    'GetAutomationInput', 'GetAutomationOutput',
    'GetCurrentFittingCorrection', 'GetIsoDrillTolerance', 'GetTool',
    'GetUserInput', 'GetUserOutput', 'GetVacuumValue', 'WcsExisting',
    'SurfaceCompensationDataExisting', 'SurfaceCompensationDataLoad',
    'SurfaceCompensationDataSave', 'SurfaceCompensationDataDelete',
    'DateTime', 'NewVisionPosition', 'VisionMeasureSinglePosition',
    'VisionMeasureDualPosition',
}
#: une syntaxe que les champs ne disent pas: l'appel du manuel, à
#: compléter tel quel (listes de sorties)
BRUTES = {'SetAutomationOutputs', 'SetUserOutputs'}
#: les commandes d'un module hors Base: « import Module » en tête et
#: l'appel préfixé « Module:: » (exemples DATRON: SpecialToolSetupSample,
#: VisionCameraExample, XyzSensorWrapper)
MODULES = {
    'SetSpecialToolOffset': 'SpecialTool',
    'CreateSpecialTool': 'SpecialTool',
    'SetSpecialToolCaptureRange': 'SpecialTool',
    'NewVisionPosition': 'Vision',
    'VisionMeasureSinglePosition': 'Vision',
    'VisionMeasureDualPosition': 'Vision',
    'PrepareXyzSensor': 'XyzSensorUtilities',
    'UnprepareXyzSensor': 'XyzSensorUtilities',
    'DateTime': 'DateTimeModule',
}
#: les fonctions (arguments entre parenthèses, sans noms)
FONCTIONS = {'NewVisionPosition'}


def _nb(nom, exemple='0', facultatif=False, defaut=None, type_='nombre'):
    return {'nom': nom, 'type': type_, 'exemple': exemple, 'defaut': defaut,
            'facultatif': facultatif, 'choix': []}


#: ce que le manuel ne donne pas en exemple (ses paragraphes le disent)
CORRECTIONS = {
    'ScaleLcsAbs': [_nb(n, '1', True, '1') for n in ('X', 'Y', 'Z')],
    'NewVisionPosition': [_nb('X'), _nb('Y'), _nb('Z'),
                          _nb('ID', 'ID_1', type_='mot')],
    # XyzSensorWrapper (DATRON): XyzSensorUtilities::PrepareXyzSensor (
    # skipRestoring=… skipLimitsError=… )
    'PrepareXyzSensor': [_nb(n, 'false', True, 'false', 'booleen')
                         for n in ('skipRestoring', 'skipLimitsError')],
    'UnprepareXyzSensor': [_nb(n, 'false', True, 'false', 'booleen')
                           for n in ('skipRestoring', 'skipLimitsError')],
}
#: le module « Time » du manuel (§ 5.8.1, catalogue « DateTime »): ses
#: fonctions et leurs paramètres (un DateTime: le nom d'une variable)
DATE_FONCTIONS = {
    'Now': (), 'GetNow': (), 'GetDate': (), 'GetTime': (),
    'StartStopWatch': (), 'ReadStopWatch': (),
    'DateTimeToString': ('dateTime', 'format'),
    'TimeSpan': ('dateTime1', 'dateTime2'),
}
#: une variable rendue par une commande précédente, pas un exemple
_VARIABLES = {('VisionMeasureSinglePosition', 'targetPosition'): 'position_1',
              ('VisionMeasureDualPosition', 'targetPosition1'): 'position_1',
              ('VisionMeasureDualPosition', 'targetPosition2'): 'position_2'}
#: noms de RÉSULTATS lus par l'extraction comme des paramètres
_RESULTATS = {'success', 'exists', 'result'}
#: le préfixe des clés (pas de heurt avec depth, x, preview…)
PREFIXE = "p_"
#: la catégorie de ces opérations dans le panneau d'ajout
CATEGORIE = "Manuel SimPL"


def _fiche(nom: str) -> Dict:
    from src.core.simpl_syntaxe import SYNTAXE
    fiche = dict(SYNTAXE.get(nom) or {})
    params = [p for p in fiche.get('parametres', [])
              if p['nom'] not in _RESULTATS and not (
                  p['type'] == 'mot' and p['exemple'] in ('', nom))]
    if nom in CORRECTIONS:
        params = CORRECTIONS[nom]
    params = [dict(p, exemple=_VARIABLES[(nom, p['nom'])])
              if (nom, p['nom']) in _VARIABLES else p for p in params]
    fiche['parametres'] = params
    if nom in MODULES:
        fiche['prefixe'] = MODULES[nom] + "::"
    return fiche


def _sans_guillemets(v: str) -> str:
    v = str(v or '')
    return v[1:-1] if len(v) >= 2 and v[0] == v[-1] == '"' else v


def _definitions(nom: str, fiche: Dict) -> List[ParameterDef]:
    defs = []
    if nom in REQUETES:
        defs.append(ParameterDef(
            "variable", "Variable du résultat", ParameterType.STRING,
            default=f"resultat_{nom[0].lower()}{nom[1:]}"[:40], unit="",
            group="Résultat",
            tooltip="La valeur rendue est rangée dans cette variable "
                    "(vide: la commande est appelée, sa valeur perdue)"))
    if nom in BRUTES:
        appel = str(fiche.get('appel') or nom)
        reste = appel.split(None, 1)[1] if ' ' in appel else ''
        defs.append(ParameterDef(
            PREFIXE + "arguments", "Arguments", ParameterType.STRING,
            default=reste, unit="", group="Commande",
            tooltip=f"Après « {nom} », tel quel (syntaxe du manuel: "
                    f"{appel})"))
        return defs
    if nom == 'DateTime':
        defs.append(ParameterDef(
            PREFIXE + "fonction", "Fonction", ParameterType.CHOICE,
            default="Now", choices=list(DATE_FONCTIONS), unit="",
            group="Commande",
            tooltip="Now: date et heure (DateTime); GetNow / GetDate / "
                    "GetTime: en texte; StartStopWatch / ReadStopWatch: "
                    "chronomètre (ms); DateTimeToString: un DateTime mis "
                    "en forme; TimeSpan: ms entre deux DateTime"))
        for cle, defaut, bulle in (
                ("dateTime", "maintenant", "DateTimeToString: la variable "
                 "DateTime à écrire"),
                ("format", "dd.MM.yyyy HH:mm", "DateTimeToString: le format "
                 "(.NET: dd, MM, yyyy, HH, mm, ss…)"),
                ("dateTime1", "debut", "TimeSpan: la variable DateTime de "
                 "départ"),
                ("dateTime2", "fin", "TimeSpan: la variable DateTime "
                 "d'arrivée")):
            # un groupe par fonction: montré à sa seule fonction
            groupe = next(f for f, cles in DATE_FONCTIONS.items()
                          if cle in cles)
            defs.append(ParameterDef(PREFIXE + cle, cle, ParameterType.STRING,
                                     default=defaut, unit="",
                                     group=groupe, tooltip=bulle))
        return defs
    for p in fiche.get('parametres', []):
        cle = PREFIXE + p['nom']
        exemple = p.get('exemple') or ''
        defaut = p.get('defaut')
        choix = list(p.get('choix') or [])
        bulle = (f"{p['nom']}= (manuel: « {p['nom']}={exemple} »"
                 + (f", défaut {defaut}" if defaut is not None else "")
                 + (", facultatif: vide = non écrit" if p.get('facultatif')
                    else "") + ")")
        if p['type'] == 'enum' and choix:
            valeurs = ([""] if p.get('facultatif') else []) + choix
            depart = defaut if defaut in choix else (
                exemple if exemple in choix else valeurs[0])
            defs.append(ParameterDef(cle, p['nom'], ParameterType.CHOICE,
                                     default=depart, choices=valeurs,
                                     unit="", group="Commande",
                                     tooltip=bulle))
        elif p['type'] == 'booleen':
            if p.get('facultatif'):
                defs.append(ParameterDef(cle, p['nom'], ParameterType.CHOICE,
                                         default="", choices=["", "true",
                                                              "false"],
                                         unit="", group="Commande",
                                         tooltip=bulle))
            else:
                defs.append(ParameterDef(cle, p['nom'], ParameterType.BOOL,
                                         default=(defaut or exemple) ==
                                         'true', unit="", group="Commande",
                                         tooltip=bulle))
        elif p['type'] == 'nombre' and not p.get('facultatif'):
            try:
                v = float(defaut if defaut not in (None, '') else
                          exemple or 0)
            except ValueError:
                v = 0.0
            defs.append(ParameterDef(cle, p['nom'], ParameterType.FLOAT,
                                     default=v, min_value=-1e6,
                                     max_value=1e6, unit="",
                                     group="Commande", tooltip=bulle))
        else:
            # texte, énumération sans choix connus, nombre facultatif:
            # un champ texte (vide = non écrit si facultatif)
            depart = "" if p.get('facultatif') else _sans_guillemets(
                defaut if defaut not in (None, '') else exemple)
            defs.append(ParameterDef(cle, p['nom'], ParameterType.STRING,
                                     default=depart, unit="",
                                     group="Commande", tooltip=bulle))
    defs.append(ParameterDef(
        PREFIXE + "en_plus", "Arguments en plus", ParameterType.STRING,
        default="", unit="", group="Commande", expert_only=False,
        tooltip="Ajoutés tels quels à la fin de la commande (un paramètre "
                "que le manuel ne cite pas, un mot seul…)"))
    return defs


def _nombre(v) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v).strip()
    return f"{f:g}"


def ligne_commande(nom: str, fiche: Dict, params: Dict[str, Any]) -> str:
    """La ligne SimPL de la commande avec ces valeurs."""
    morceaux = [f"{fiche.get('prefixe', '')}{nom}"]
    if nom == 'DateTime':
        fonction = str(params.get(PREFIXE + "fonction", '') or 'Now')
        if fonction not in DATE_FONCTIONS:
            fonction = 'Now'
        morceaux = [f"{fiche.get('prefixe', '')}{fonction}"]
        if not DATE_FONCTIONS[fonction]:
            morceaux[0] += "()"
        for cle in DATE_FONCTIONS[fonction]:
            v = str(params.get(PREFIXE + cle, '') or '').strip()
            if cle == 'format':
                v = '"' + v.replace('"', "'") + '"'
            if v:
                morceaux.append(f"{cle}={v}")
    elif nom in FONCTIONS:
        valeurs = [_nombre(params.get(PREFIXE + p['nom'], '') or 0)
                   for p in fiche.get('parametres', [])]
        morceaux[0] += "(" + ", ".join(valeurs) + ")"
    elif nom in BRUTES:
        reste = str(params.get(PREFIXE + "arguments", '') or '').strip()
        if reste:
            morceaux.append(reste)
    else:
        for p in fiche.get('parametres', []):
            cle = PREFIXE + p['nom']
            if cle not in params:
                continue
            v = params[cle]
            if p['type'] == 'booleen':
                if isinstance(v, bool):
                    texte = 'true' if v else 'false'
                else:
                    texte = str(v or '').strip().lower()
                    if texte not in ('true', 'false'):
                        continue
            elif p['type'] == 'texte':
                if p.get('facultatif') and not str(v or '').strip():
                    continue
                texte = '"' + str(v or '').replace('"', "'") + '"'
            elif p['type'] == 'nombre':
                if str(v).strip() == '':
                    continue
                texte = _nombre(v)
            else:
                texte = str(v or '').strip()
                if not texte:
                    continue
            morceaux.append(f"{p['nom']}={texte}")
    en_plus = str(params.get(PREFIXE + "en_plus", '') or '').strip()
    if en_plus:
        morceaux.append(en_plus)
    ligne = " ".join(morceaux)
    variable = str(params.get('variable', '') or '').strip()
    if nom in REQUETES and variable:
        variable = "".join(c for c in variable if c.isalnum() or c == '_')
        if variable and not variable[0].isdigit():
            ligne = f"{variable} = {ligne}"
    return "    " + ligne


def _classe(nom: str):
    from src.core.simpl_commandes import COMMANDES
    famille, role, chapitre, page = COMMANDES.get(
        nom, ("Divers", nom, "", 0))
    fiche = _fiche(nom)
    definitions = _definitions(nom, fiche)

    class _Commande(AbstractOperation):
        # le rôle en français; la commande est dans la bulle et la
        # recherche du panneau d'ajout la trouve (COMMANDE)
        DISPLAY_NAME = role or nom
        # une seule catégorie (dix-sept familles encombreraient le
        # panneau d'ajout); la famille est dans la description
        CATEGORY = CATEGORIE
        FAMILLE = famille
        DESCRIPTION = (f"{nom}: {famille} — {role} (manuel SimPL 3.1.1, "
                       f"§ {chapitre}, p. {page})")
        ICON = "operation"
        HORS_MATIERE = True
        EXPERT_ONLY = True
        INLINE = True
        LIST_DETAIL = True
        # DateTime: les champs d'une fonction, à cette fonction seule
        GROUPES_SELON = ({f: (PREFIXE + "fonction", (f,))
                          for f, cles in DATE_FONCTIONS.items() if cles}
                         if nom == 'DateTime' else {})
        REQUIRES_TOOL = False
        REQUIRES_COORDINATES = False
        COMMANDE = nom
        FICHE = fiche
        #: modules à importer en tête du programme (lus par le générateur)
        IMPORTS = (MODULES[nom],) if nom in MODULES else ()

        @classmethod
        def get_parameters(cls) -> List[ParameterDef]:
            return list(definitions)

        @classmethod
        def get_tool_requirement(cls) -> ToolRequirement:
            return ToolRequirement(tool_types=[],
                                   description="Aucun outil requis")

        @classmethod
        def generate_operation_code(cls, params: Dict[str, Any]) -> str:
            valeurs = {**cls.get_default_params(), **(params or {})}
            return ligne_commande(nom, fiche, valeurs)

    _Commande.__name__ = f"Commande{nom}"
    _Commande.__qualname__ = _Commande.__name__
    return _Commande


def type_operation(nom: str) -> str:
    """Le type d'opération NeoDrive d'une commande du manuel."""
    return f"manuel_{nom}"


for _nom in A_ECRIRE:
    OperationRegistry.register(type_operation(_nom))(_classe(_nom))
