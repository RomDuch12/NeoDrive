"""Les commandes SimPL, d'après le manuel DATRON.

Source: « DATRON SimPL Programmierhandbuch 3.1.1 (EN) », § 3.2
« Overview of SimPL commands » (p. 38-46). Pour chaque commande: sa
famille, ce qu'elle fait, le chapitre et la PAGE du PDF où le manuel
la décrit. L'éditeur de code s'en sert pour colorer, expliquer au
survol et compléter.
"""

#: famille -> couleur de l'éditeur (cycles d'usinage à part: ce sont
#: eux qui touchent la matière)
FAMILLES = ("Outils", "Cycles d'usinage", "Palpage", "Positionnement",
            "Technologie", "Repères", "Structure", "Corrections",
            "Dialogues", "Entrées/sorties", "Fonctions", "Modules",
            "Profil de surface", "Programmes externes", "Caméra",
            "Vision", "En-tête")

#: nom -> (famille, explication, chapitre, page du PDF)
COMMANDES = {
    # Outils
    "GetTool": ("Outils", "Lire les données d'un outil", "5.1.1", 122),
    "SetTool": ("Outils", "Écrire les données d'un outil", "5.1.2", 137),
    "SetToolIsLocked": ("Outils", "Verrouiller / déverrouiller un outil",
                        "5.1.3", 139),
    "Tool": ("Outils", "Changement d'outil", "5.1.4", 141),
    "ProvideTool": ("Outils", "Préparer (activer) un outil", "5.1.5", 143),
    "MeasureToolLength": ("Outils", "Mesurer la longueur de l'outil en "
                          "broche", "5.1.6", 145),
    "MeasuringTolerance": ("Outils", "Tolérances de la mesure de "
                           "longueur (cassure, usure, arête rapportée)",
                           "5.1.7", 147),
    "MeasuringSettings": ("Outils", "Contrôles de la mesure de longueur",
                          "5.1.8", 149),
    "ToolCompensation": ("Outils", "Correction de rayon", "5.1.9", 151),
    "CreateSpecialTool": ("Outils", "Créer un outil spécial", "5.1.10.1",
                          153),
    "SetSpecialToolOffset": ("Outils", "Décalages d'un outil spécial",
                             "5.1.10.2", 155),
    "SetSpecialToolCaptureRange": ("Outils", "Plage de saisie d'un outil "
                                   "spécial", "5.1.10.3", 157),
    # Cycles d'usinage
    "Drill": ("Cycles d'usinage", "Perçage", "5.2.1.1", 159),
    "DrillMilling": ("Cycles d'usinage", "Perçage à la fraise (alésage "
                     "hélicoïdal)", "5.2.1.2", 163),
    "Thread": ("Cycles d'usinage", "Filetage à la fraise", "5.2.1.3", 168),
    "SpecialThread": ("Cycles d'usinage", "Filetage spécial", "5.2.1.4",
                      174),
    "ThreadCutting": ("Cycles d'usinage", "Taraudage (broche 8 kW "
                      "seulement)", "5.2.1.5", 182),
    "RectFromMid": ("Cycles d'usinage", "Contour rectangle", "5.2.2.1",
                    187),
    "CircleFromMid": ("Cycles d'usinage", "Contour cercle", "5.2.2.2", 194),
    "RectangleCavity": ("Cycles d'usinage", "Poche rectangulaire",
                        "5.2.3.1", 199),
    "CircleCavity": ("Cycles d'usinage", "Poche circulaire", "5.2.3.2",
                     206),
    "RectangleFace": ("Cycles d'usinage", "Surfaçage rectangulaire",
                      "5.2.4.1", 212),
    "CircleFace": ("Cycles d'usinage", "Surfaçage circulaire", "5.2.4.2",
                   220),
    "StandardTextEngrave": ("Cycles d'usinage", "Gravure de texte",
                            "5.2.5.1", 225),
    # Palpage
    "CornerMeasure": ("Palpage", "Palpage d'un coin (origine, "
                      "orientation)", "5.3.1.1", 232),
    "RectangleMeasure": ("Palpage", "Palpage du centre d'un rectangle",
                         "5.3.1.2", 244),
    "CircleMeasure": ("Palpage", "Palpage du centre d'un cercle",
                      "5.3.1.3", 256),
    "SurfaceMeasure": ("Palpage", "Palpage de la hauteur Z", "5.3.1.4",
                       267),
    "EdgeMeasure": ("Palpage", "Palpage d'une arête", "5.3.1.5", 271),
    "EdgeMeasureV2": ("Palpage", "Palpage d'une arête", "5.3.1.5", 272),
    "SymmetryAxisMeasure": ("Palpage", "Palpage d'un axe de symétrie",
                            "5.3.1.6", 280),
    "UShapeMeasure": ("Palpage", "Palpage d'une forme en U", "5.3.1.7",
                      289),
    "PlaneOrientationMeasure": ("Palpage", "Palpage d'un plan (option)",
                                "5.3.1.8", 301),
    "PrepareXyzSensor": ("Palpage", "Sortir le palpeur XYZ", "5.3.2", 308),
    "UnprepareXyzSensor": ("Palpage", "Rentrer le palpeur XYZ", "5.3.3",
                           308),
    # Positionnement
    "Absolute": ("Positionnement", "Cotes absolues", "5.4.1.1", 308),
    "Incremental": ("Positionnement", "Cotes incrémentales", "5.4.1.2",
                    310),
    "Rapid": ("Positionnement", "Déplacement rapide", "5.4.2.1", 311),
    "Line": ("Positionnement", "Déplacement en avance (droite)", "5.4.2.2",
             312),
    "Arc": ("Positionnement", "Arc de cercle", "5.4.2.3", 313),
    "HelixWithFullCircle": ("Positionnement", "Hélice à tours complets",
                            "5.4.2.4", 315),
    "Helix": ("Positionnement", "Hélice", "5.4.2.5", 318),
    "SafeZHeightForWorkpiece": ("Positionnement", "Hauteur de sécurité "
                                "de la pièce", "5.4.3.1", 321),
    "MoveToSafetyPosition": ("Positionnement", "Remonter à la hauteur "
                             "de sécurité", "5.4.3.2", 322),
    "SafeRapid": ("Positionnement", "Positionnement sûr", "5.4.3.3", 323),
    "PrePositioning": ("Positionnement", "Prépositionnement sûr",
                       "5.4.3.4", 324),
    "MoveToParkPosition": ("Positionnement", "Position de parking",
                           "5.4.3.5", 325),
    # Technologie
    "Feed": ("Technologie", "Avance", "5.5.1.1", 326),
    "SetFeedTechnology": ("Technologie", "Avances de l'outil (finition, "
                          "approche, plongée, rampe, ébauche)", "5.5.1.2",
                          328),
    "Rpm": ("Technologie", "Vitesse de broche", "5.5.2.1", 330),
    "Spindle": ("Technologie", "Broche marche / arrêt", "5.5.2.2", 331),
    "SpraySystem": ("Technologie", "Pulvérisation", "5.5.3.1", 332),
    "Coolant": ("Technologie", "Lubrifiant", "5.5.3.2", 333),
    "SprayDirection": ("Technologie", "Direction de pulvérisation",
                       "5.5.3.3", 334),
    "SprayTechnology": ("Technologie", "Arrosage intérieur / extérieur",
                        "5.5.3.4", 336),
    "Vacuum": ("Technologie", "Vide (table aspirante)", "5.5.4.1", 338),
    "VacuumSelection": ("Technologie", "Raccords de vide", "5.5.4.2", 339),
    "GetVacuumValue": ("Technologie", "Lire la valeur du vide", "5.5.4.3",
                       340),
    "EndlessMotion": ("Technologie", "Mouvement sans fin (axe rotatif)",
                      "5.5.5.1", 341),
    "MovingDirection": ("Technologie", "Sens de rotation (axe rotatif)",
                        "5.5.5.2", 343),
    "RotatoryAxisRadius": ("Technologie", "Rayon pour la vitesse de "
                           "surface", "5.5.5.3", 344),
    "Rtcp": ("Technologie", "RTCP", "5.5.6.1", 345),
    "MultiAxisMode": ("Technologie", "Usinage multi-axes", "5.5.6.2", 346),
    "Dynamic": ("Technologie", "Dynamique", "5.5.7", 347),
    "Smoothing": ("Technologie", "Lissage du contour", "5.5.8", 348),
    "Suction": ("Technologie", "Aspiration (option)", "5.5.9.1", 351),
    "BlowClearWorkpiece": ("Technologie", "Soufflage de la pièce "
                           "(option)", "5.5.9.2", 353),
    "BlowClearWorkpieceNozzle": ("Technologie", "Purge des buses "
                                 "(option)", "5.5.9.3", 355),
    "ChipConveyor": ("Technologie", "Convoyeur à copeaux (option)",
                     "5.5.9.4", 356),
    "BlastAirTimes": ("Technologie", "Purge du magasin d'outils (option)",
                      "5.5.9.5", 358),
    "Ionization": ("Technologie", "Ionisation (option)", "5.5.9.6", 360),
    "OilMistExtraction": ("Technologie", "Aspiration de brouillard "
                          "d'huile (option)", "5.5.10", 362),
    "Fitting": ("Technologie", "Ajustement (option)", "5.5.11.1", 364),
    "GetCurrentFittingCorrection": ("Technologie", "Lire la correction "
                                    "d'ajustement", "5.5.11.2", 371),
    "SaveCurrentFittingCorrection": ("Technologie", "Enregistrer la "
                                     "correction d'ajustement", "5.5.11.3",
                                     372),
    "GetIsoDrillTolerance": ("Technologie", "Tolérance DIN-ISO",
                             "5.5.11.4", 373),
    "WorkpieceCooler": ("Technologie", "Refroidisseur de pièce (option)",
                        "5.5.12", 375),
    # Repères
    "WorkPlane": ("Repères", "Choix du plan de travail", "5.6.3", 414),
    "WcsExisting": ("Repères", "Le repère pièce existe-t-il ?", "5.6.1.1",
                    376),
    "MirrorWcs": ("Repères", "Miroir du repère pièce", "5.6.1.2", 378),
    "ResetWcs": ("Repères", "Réinitialiser le repère pièce", "5.6.1.3",
                 379),
    "ShiftWcsAbs": ("Repères", "Décalage absolu du repère pièce",
                    "5.6.1.4", 380),
    "ShiftWcsInc": ("Repères", "Décalage incrémental du repère pièce",
                    "5.6.1.5", 382),
    "RotateWcsAbs": ("Repères", "Rotation absolue du repère pièce (depuis "
                     "le repère machine)", "5.6.1.6", 384),
    "RotateWcsInc": ("Repères", "Rotation incrémentale du repère pièce",
                     "5.6.1.7", 386),
    "SetWcs": ("Repères", "Définir le repère pièce", "5.6.1.8", 388),
    "CreateWcs": ("Repères", "Créer un repère pièce", "5.6.1.9", 393),
    "DeleteWcs": ("Repères", "Supprimer un repère pièce", "5.6.1.10", 395),
    "SetWcsOnTcp": ("Repères", "Repère pièce à la pointe de l'outil",
                    "5.6.1.11", 396),
    "SetWcsInitial": ("Repères", "Repère pièce pour le mode manuel",
                      "5.6.1.12", 398),
    "SaveWcs": ("Repères", "Enregistrer le repère pièce", "5.6.1.13", 399),
    "LoadWcs": ("Repères", "Charger un repère pièce", "5.6.1.14", 400),
    "MirrorLcs": ("Repères", "Miroir du repère local", "5.6.2.1", 401),
    "ShiftLcsAbs": ("Repères", "Décalage absolu du repère local",
                    "5.6.2.2", 403),
    "ShiftLcsInc": ("Repères", "Décalage incrémental du repère local",
                    "5.6.2.3", 405),
    "RotateLcsAbs": ("Repères", "Rotation absolue du repère local",
                     "5.6.2.4", 407),
    "RotateLcsInc": ("Repères", "Rotation incrémentale du repère local",
                     "5.6.2.5", 409),
    "ResetLcs": ("Repères", "Réinitialiser le repère local", "5.6.2.6",
                 411),
    "SetLcsInitial": ("Repères", "Repère local pour le mode manuel",
                      "5.6.2.7", 412),
    "ScaleLcsAbs": ("Repères", "Mise à l'échelle du repère local",
                    "5.6.2.8", 413),
    # Structure
    "BeginBlock": ("Structure", "Début de bloc", "5.7.1.1", 415),
    "EndBlock": ("Structure", "Fin de bloc", "5.7.1.2", 416),
    # Corrections
    "PathCorrection": ("Corrections", "Correction de trajectoire en XY",
                       "5.7.2.1", 417),
    "PathOffset": ("Corrections", "Valeur de correction de trajectoire",
                   "5.7.2.1", 417),
    "ZAxisOffset": ("Corrections", "Correction en Z (profondeur)",
                    "5.7.2.2", 419),
    # Dialogues
    "Dialog": ("Dialogues", "Dialogue (attend une réponse)", "5.7.3.1",
               421),
    "InputDialog": ("Dialogues", "Dialogue avec saisie", "5.7.3.2", 424),
    "StatusMessage": ("Dialogues", "Message (sans arrêter le programme)",
                      "5.7.3.3", 425),
    # Entrées / sorties
    "GetUserInput": ("Entrées/sorties", "Lire une entrée utilisateur",
                     "5.7.4.1", 427),
    "GetUserOutput": ("Entrées/sorties", "Lire une sortie utilisateur",
                      "5.7.4.2", 429),
    "WaitForUserInput": ("Entrées/sorties", "Attendre une entrée "
                         "utilisateur", "5.7.4.3", 431),
    "SetUserOutput": ("Entrées/sorties", "Écrire une sortie utilisateur",
                      "5.7.4.4", 433),
    "SetUserOutputs": ("Entrées/sorties", "Écrire plusieurs sorties "
                       "utilisateur", "5.7.4.5", 434),
    "GetAutomationInput": ("Entrées/sorties", "Lire une entrée "
                           "d'automatisation", "5.7.5.1", 435),
    "GetAutomationOutput": ("Entrées/sorties", "Lire une sortie "
                            "d'automatisation", "5.7.5.2", 437),
    "WaitForAutomationInput": ("Entrées/sorties", "Attendre une entrée "
                               "d'automatisation", "5.7.5.3", 439),
    "SetAutomationOutput": ("Entrées/sorties", "Écrire une sortie "
                            "d'automatisation", "5.7.5.4", 441),
    "SetAutomationOutputs": ("Entrées/sorties", "Écrire plusieurs sorties "
                             "d'automatisation", "5.7.5.5", 442),
    # Fonctions
    "SpindleWarmup": ("Fonctions", "Préchauffage de la broche", "5.7.6.1",
                      443),
    "Sleep": ("Fonctions", "Attendre", "5.7.6.2", 444),
    "ValueToString": ("Fonctions", "Valeur en texte", "5.7.6.3", 445),
    "AddCommandToCommandClipboard": ("Fonctions", "Insérer une commande",
                                     "5.7.6.4", 446),
    "ReleaseDoor": ("Fonctions", "Libérer la porte", "5.7.6.5", 448),
    "UserErrorHandling": ("Fonctions", "Surveillance des entrées en "
                          "temps réel", "5.7.6.6", 449),
    "ScheduleMachineShutdown": ("Fonctions", "Arrêter la machine",
                                "5.7.6.7", 450),
    # Modules étendus
    "DateTime": ("Modules", "Date et heure", "5.8.1", 451),
    "Pattern": ("Modules", "Motifs (cercle, rectangle)", "5.8.5", 467),
    "CircularPattern": ("Modules", "Motif sur un cercle", "5.8.5.1",
                        467),
    "RectanglePattern": ("Modules", "Motif en rectangle", "5.8.5.2",
                         469),
    # Profil de surface
    "SurfaceCompensationZGridMeasure": ("Profil de surface", "Champ de "
                                        "mesure Z", "5.9.2", 490),
    "SurfaceCompensationDataExisting": ("Profil de surface", "Le champ "
                                        "de mesure existe-t-il ?",
                                        "5.9.3", 497),
    "SurfaceCompensationDataDelete": ("Profil de surface", "Supprimer le "
                                      "champ de mesure", "5.9.4", 498),
    "SurfaceCompensationDataSave": ("Profil de surface", "Enregistrer le "
                                    "champ de mesure", "5.9.5", 499),
    "SurfaceCompensationDataLoad": ("Profil de surface", "Charger le "
                                    "champ de mesure", "5.9.6", 500),
    # Programmes externes
    "RunExternalProgram": ("Programmes externes", "Appeler un programme "
                           "externe", "5.10.1", 501),
    "RunExternalSequence": ("Programmes externes", "Appeler une séquence "
                            "externe", "5.10.2", 502),
    # Caméra, vision
    "CameraScanCode": ("Caméra", "Lire un code (option)", "5.11.1", 503),
    "CameraSaveImage": ("Caméra", "Enregistrer une image (option)",
                        "5.11.2", 506),
    "VisionMeasureSinglePosition": ("Vision", "Mesurer une position",
                                    "5.12.1", 508),
    "VisionMeasureDualPosition": ("Vision", "Mesurer deux positions",
                                  "5.12.2", 512),
    "NewVisionPosition": ("Vision", "Créer une position", "5.12.3", 519),
    # En-tête
    "Author": ("En-tête", "Auteur du module", "5.13.1", 523),
    "Comment": ("En-tête", "Commentaire du module", "5.13.2", 525),
}

#: le manuel, à côté de l'exe ou dans le dépôt
NOM_MANUEL = "DATRON_SimPL_Programmierhandbuch_3.1.1_EN.pdf"


def aide(nom: str) -> str:
    """L'aide d'une commande, en une ligne — vide si inconnue."""
    info = COMMANDES.get(nom)
    if not info:
        return ""
    famille, quoi, chapitre, page = info
    texte = (f"{nom} — {quoi}\n{famille} · manuel SimPL § {chapitre}, "
             f"p. {page}")
    # la syntaxe relevée dans le manuel (src/core/simpl_syntaxe.py)
    from src.core.simpl_syntaxe import SYNTAXE
    syntaxe = SYNTAXE.get(nom) or {}
    appel = syntaxe.get('appel') or ""
    if appel == nom and syntaxe.get('parametres'):
        # l'exemple du manuel manque: l'appel rebâti des paramètres,
        # les facultatifs entre crochets
        morceaux = []
        for p in syntaxe['parametres']:
            m = f"{p['nom']}={p.get('exemple') or '…'}"
            morceaux.append(f"[{m}]" if p.get('facultatif') else m)
        appel = " ".join([nom] + morceaux)
    if appel and appel != nom:
        texte += f"\n{syntaxe.get('prefixe', '')}{appel}"
    return texte


def chemin_manuel() -> str:
    """Le manuel SimPL s'il est sur le poste (à côté de l'exe ou dans
    le dépôt), sinon ""."""
    import os
    from src.core.tool_library import get_base_dir
    for dossier in (get_base_dir(), os.path.join(get_base_dir(), "data")):
        chemin = os.path.join(dossier, NOM_MANUEL)
        if os.path.isfile(chemin):
            return chemin
    return ""
