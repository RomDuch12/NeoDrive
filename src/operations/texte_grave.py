# -*- coding: utf-8 -*-
"""Opération « Gravure texte »: un texte dans une police du poste,
gravé au V — creux ou relief — comme n'importe quel dessin.

« Texte Datron » (gravure_texte) écrit un `Engrave::StandardTextEngrave`
avec la police de la machine, en simple trait. Celle-ci VECTORISE le
texte (fontTools, polices de Windows) en contours fermés, et c'est un
parcours de gravure ordinaire: même outil, même mode creux/relief,
même cadre, même reprise dans une gamme. Le texte se pose aussi au
canvas — pour l'export DXF, ou pour le manipuler avec les autres
entités.
"""

from typing import Any, Dict, List

from src.core import texte as noyau_texte
from src.operations.base_operation import ParameterDef, ParameterType
from src.operations.gravure_2d5 import Gravure2D5
from src.operations.registry import OperationRegistry


def champs_texte() -> List[ParameterDef]:
    """Les champs qui font un texte: partagés avec la tête de gamme."""
    familles = noyau_texte.polices() or [noyau_texte.POLICE_DEFAUT]
    police_defaut = noyau_texte.POLICE_DEFAUT \
        if noyau_texte.POLICE_DEFAUT in familles else familles[0]
    return [
        ParameterDef("texte", "Texte", ParameterType.STRING,
                     default="", unit="", group="Texte", multiline=True,
                     tooltip="Le texte à graver, sur une ou plusieurs "
                             "lignes."),
        ParameterDef("police", "Police", ParameterType.CHOICE,
                     default=police_defaut, choices=familles, unit="",
                     group="Texte",
                     tooltip="Une police installée sur ce poste "
                             "(C:/Windows/Fonts). Le contour gravé "
                             "est celui de la police."),
        ParameterDef("hauteur_capitale", "Hauteur de capitale",
                     ParameterType.FLOAT, default=5.0,
                     min_value=0.2, max_value=500.0, unit="mm",
                     group="Texte",
                     tooltip="La hauteur d'un H. Deux polices de même "
                             "corps ne gravent pas la même hauteur: "
                             "on mesure la capitale."),
        ParameterDef("pos_x", "Position X", ParameterType.FLOAT,
                     default=0.0, min_value=-5000.0, max_value=5000.0,
                     unit="mm", group="Texte",
                     tooltip="Le point d'alignement du texte."),
        ParameterDef("pos_y", "Position Y", ParameterType.FLOAT,
                     default=0.0, min_value=-5000.0, max_value=5000.0,
                     unit="mm", group="Texte",
                     tooltip="La ligne de base du texte."),
        ParameterDef("alignement", "Alignement", ParameterType.CHOICE,
                     default=noyau_texte.ALIGNEMENTS[0],
                     choices=list(noyau_texte.ALIGNEMENTS), unit="",
                     group="Texte",
                     tooltip="Où la position tombe dans le texte: au "
                             "centre, à gauche ou à droite."),
        ParameterDef("rotation", "Rotation", ParameterType.FLOAT,
                     default=0.0, min_value=-360.0, max_value=360.0,
                     unit="°", group="Texte",
                     tooltip="Autour du point de position, sens "
                             "trigonométrique."),
        ParameterDef("disposition", "Disposition", ParameterType.CHOICE,
                     default="Ligne droite",
                     choices=["Ligne droite", "Arc (dessus)",
                              "Arc (dessous)"],
                     unit="", group="Texte",
                     tooltip="Arc: centré sur la position, la ligne de "
                             "base au rayon donné; « dessus » se lit en "
                             "haut du cercle, « dessous » en bas. La "
                             "rotation déplace le texte autour du "
                             "cercle. Les lettres épousent l'arc."),
        ParameterDef("rayon_arc", "Rayon de l'arc", ParameterType.FLOAT,
                     default=20.0, min_value=0.5, max_value=5000.0,
                     unit="mm", group="Texte",
                     tooltip="Rayon de la ligne de base du texte."),
        ParameterDef("interligne", "Interligne", ParameterType.FLOAT,
                     default=1.4, min_value=0.5, max_value=5.0, unit="",
                     group="Texte", expert_only=True,
                     tooltip="En hauteurs de capitale, d'une ligne à "
                             "la suivante."),
    ]


@OperationRegistry.register("texte_grave")
class TexteGrave(Gravure2D5):
    """Un texte vectorisé, gravé au V."""

    OP_TYPE = "texte_grave"
    DISPLAY_NAME = "Gravure texte"
    DESCRIPTION = ("Texte dans une police du poste, vectorisé et gravé "
                   "au V — creux ou relief, avec la gamme, exportable "
                   "en DXF")
    ICON = "gravure_texte"
    PREFIXE_SEQ = "TEXTE"

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return champs_texte() + super().get_parameters()

    @staticmethod
    def contours(params: Dict[str, Any]) -> List[List]:
        """Les contours du texte — pas ceux relevés au canvas."""
        return noyau_texte.contours_depuis_params(params) or []

    @classmethod
    def validate_params(cls, params: Dict[str, Any]) -> List[str]:
        erreurs = super().validate_params(params)
        if not str(params.get('texte') or "").strip():
            erreurs.append("Le texte est vide.")
        return erreurs

    @classmethod
    def resume(cls, params: Dict[str, Any], calculer: bool = True
               ) -> str:
        texte = str(params.get('texte') or "").strip()
        if not texte:
            return "aucun texte"
        return super().resume(params, calculer)

