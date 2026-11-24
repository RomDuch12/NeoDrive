"""Génération du module machine `AutomaticPrograms`.

Ce module Datron n'est PAS un programme d'usinage: installé dans
Machine/Library, il s'exécute automatiquement autour de TOUS les
programmes de la machine. Son nom de module doit être exactement
`AutomaticPrograms` (le nom du fichier, lui, est libre).

Points d'entrée (doc: AutomaticPrograms.simpl):
  OnStart        avant tout programme d'usinage
  OnEnd          après un programme terminé SANS erreur
  OnReferenced   après une prise de référence réussie
  OnInitialized  à la mise sous tension

Gestionnaires enregistrés depuis OnStart:
  AddIdleHandler   exécuté SEULEMENT si le programme a été
                   interrompu, une fois la machine réactivée
  AddErrorHandler  exécuté immédiatement à l'interruption. Très
                   restreint: on s'y limite aux sorties numériques,
                   comme le fait la documentation.

Le fichier produit est destiné à être RELU puis installé
manuellement: il affecte tous les programmes de la machine.
"""

from typing import Dict, Any, List


DEFAULT_OPTIONS: Dict[str, Any] = {
    'confirm_start': True,      # dialogue Ok/Cancel au lancement
    'user_output': 0,           # 0 = aucune sortie pilotée, sinon 1..8
    'notify_aborted': True,     # message après une interruption
    'park_on_referenced': True,  # park position après référencement
    'notify_initialized': False,  # message à la mise sous tension
    'confirm_end': False,       # message en fin de programme
    'author': "",
}


def _header(author: str) -> List[str]:
    lines = [
        "# Module machine généré par NeoDrive.",
        "# À RELIRE puis à installer dans Machine/Library.",
        "# ATTENTION: il s'exécute autour de TOUS les programmes de",
        "# la machine, pas seulement ceux de NeoDrive.",
        "",
        "module AutomaticPrograms",
        "",
        '@ MeasuringSystem = "Metric" @',
    ]
    if author:
        lines.append(f'@ Author = "{author}" @')
    lines += ["", "using Base, HandlerUtilities", ""]
    return lines


def build_automatic_programs(options: Dict[str, Any] = None) -> str:
    """Construit le module AutomaticPrograms complet."""
    o = {**DEFAULT_OPTIONS, **(options or {})}
    out_num = int(o.get('user_output', 0) or 0)
    has_output = 1 <= out_num <= 8
    output = f"OUTPUT_{out_num}"

    lines = _header(str(o.get('author') or ''))

    # ── OnStart ──
    # La documentation précise qu'un point d'entrée inutile doit être
    # OMIS plutôt que laissé vide.
    body: List[str] = []
    if o.get('confirm_start', True):
        msg = "Lancement du programme"
        if has_output:
            msg += f"\n\nLa sortie {output} va être activée."
        msg += "\n\nOk pour continuer, Annuler pour interrompre."
        body.append(f'    Dialog Ok Cancel message="{msg}"')
    if has_output:
        body.append("    ActiverSortie")
    if o.get('notify_aborted', True):
        body += [
            "    # Exécuté uniquement si le programme est INTERROMPU,",
            "    # une fois la machine réactivée",
            "    AddIdleHandler handler=SignalerInterruption",
        ]
    if has_output:
        body += [
            "    # Exécuté immédiatement en cas d'interruption:",
            "    # seules les sorties numériques y sont autorisées",
            "    AddErrorHandler handler=CouperSortie",
        ]
    if body:
        lines += ["# Exécuté AVANT tout programme d'usinage",
                  "export program OnStart"] + body + ["endprogram", ""]

    # ── OnEnd ──
    body = []
    if o.get('confirm_end', False):
        body.append('    Dialog Ok message="Programme terminé."')
    if has_output:
        body.append("    CouperSortie")
    if body:
        lines += ["# Exécuté APRÈS un programme terminé sans erreur",
                  "export program OnEnd"] + body + ["endprogram", ""]

    # ── OnReferenced ──
    if o.get('park_on_referenced', True):
        lines += [
            "# Exécuté après une prise de référence réussie",
            "export program OnReferenced",
            '    result = Dialog Yes No message="Machine référencée.',
            "",
            "Oui pour aller en position de parking.",
            'Non pour continuer sans déplacement."',
            "    if result == DialogResult.Yes",
            "        MoveToParkPosition  askForRestore=false",
            "    endif",
            "endprogram",
            "",
        ]

    # ── OnInitialized ──
    if o.get('notify_initialized', False):
        lines += [
            "# Exécuté à la mise sous tension de la machine",
            "export program OnInitialized",
            '    Dialog Ok message="Machine initialisée."',
            "endprogram",
            "",
        ]

    # ── Gestionnaires ──
    if o.get('notify_aborted', True):
        lines += [
            "# Installé comme IdleHandler dans OnStart",
            "export program SignalerInterruption",
            '    Dialog Ok message="Le programme a été interrompu.',
            "",
            'Vérifiez la pièce et l\'outil avant de relancer."',
            "endprogram",
            "",
        ]
    if has_output:
        lines += [
            "# Installé comme ErrorHandler dans OnStart, et appelé",
            "# par OnEnd. Se limite à une sortie numérique: c'est la",
            "# seule opération sûre dans un ErrorHandler.",
            "export program CouperSortie",
            f"    SetUserOutput {output} Off",
            "endprogram",
            "",
            "export program ActiverSortie",
            f"    SetUserOutput {output} On",
            "endprogram",
            "",
        ]

    lines.append("end")
    return "\n".join(lines) + "\n"
