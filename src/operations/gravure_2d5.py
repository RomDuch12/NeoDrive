# -*- coding: utf-8 -*-
"""Opérations: Gravure 2,5D et Évidement, en séquences Datron.

TypeEdit sait faire les deux, avec son post-processeur DATRON: il
rend un `.SimPl` dont les parcours vivent
dans des blocs `$$$ SEQUENCE_n`, remontées d'angles comprises. Ces
deux opérations font le même travail À PARTIR DU DESSIN de NeoDrive,
sans repasser par TypeEdit — et sortent dans la même forme, si bien
que la machine ne voit pas la différence.

  - En-tête:   @ EmbeddedSequences = true @  +  sequence NOM
  - Sous-prog: Tool / Rpm / SetFeedTechnology + appel du NOM
  - Pied:      bloc $$$ NOM contenant le parcours

Le calcul est dans `src/core/vcarve.py` (sans Qt, vérifiable seul);
ici, le formulaire, la lecture de l'outil et l'écriture du bloc.

La géométrie de l'outil se lit dans son NOM (« Con 30° 0.2 »): angle
total du cône et diamètre de pointe. Les deux restent modifiables —
un outil re-affûté n'a plus la troncature écrite sur son étiquette.
"""

from typing import Any, Dict, List

from src.core import vcarve
from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement
)
from src.operations.registry import OperationRegistry


#: le cadre du relief se donne par une marge autour du dessin, ou
#: par les dimensions d'un rectangle — exclusivement
CADRE_PAR_MARGE = "Marge autour du dessin"
CADRE_PAR_DIMENSIONS = "Dimensions du cadre"


def mode_du_cadre(params: Dict[str, Any]) -> str:
    """Le mode retenu; un programme d'avant le round 103 n'en porte
    pas: des dimensions données disent « dimensions »."""
    mode = str(params.get('cadre_mode') or "")
    if mode in (CADRE_PAR_MARGE, CADRE_PAR_DIMENSIONS):
        return mode
    try:
        largeur = float(params.get('cadre_largeur', 0.0) or 0.0)
        hauteur = float(params.get('cadre_hauteur', 0.0) or 0.0)
    except (TypeError, ValueError):
        return CADRE_PAR_MARGE
    return CADRE_PAR_DIMENSIONS if (largeur > 0 or hauteur > 0) \
        else CADRE_PAR_MARGE


class _SequenceConique(AbstractOperation):
    """Base commune: le contour relevé, l'outil conique, le bloc $$$."""

    CATEGORY = "Gravure"
    INLINE = False
    REQUIRES_TOOL = True
    REQUIRES_COORDINATES = False
    SUPPORTS_MULTI_POINT = False

    #: préfixe du nom de séquence
    PREFIXE_SEQ = "SEQ"

    #: l'opération enlève-t-elle de la matière DANS le dessin ?
    #: Un tour de contour passe autour: sa couverture du tracé vaut
    #: zéro, et l'annoncer n'apprend rien.
    MESURE_COUVERTURE = True

    #: le paramètre qui porte la cote de l'opération
    CLE_PROFONDEUR = 'profondeur_max'

    @classmethod
    def _champs_forme(cls) -> List[ParameterDef]:
        """Ce qu'on usine: le creux, ou tout autour."""
        return [
            ParameterDef("mode", "Mode", ParameterType.CHOICE,
                         default="Relief",
                         choices=["Creux", "Relief"], unit="",
                         group="Forme",
                         tooltip="Creux: on vide l'intérieur du "
                                 "contour.\nRelief: on vide TOUT "
                                 "AUTOUR jusqu'à un cadre — la forme "
                                 "reste debout."),
            ParameterDef("pres_du_trait", "Parcours optimisé",
                         ParameterType.BOOL,
                         default=True, unit="", group="Forme",
                         tooltip="En relief, la conique ne grave que "
                                 "là où elle touche le dessin: le "
                                 "flanc des lettres et les creux "
                                 "étroits. Le reste du champ est le "
                                 "travail de la cylindrique "
                                 "(évidement).\nDécoché: elle creuse "
                                 "aussi l'axe du champ à la cote "
                                 "maxi — des minutes de V au milieu "
                                 "de nulle part."),
            ParameterDef("cadre_mode", "Cadre (relief)",
                         ParameterType.CHOICE,
                         default=CADRE_PAR_DIMENSIONS,
                         choices=[CADRE_PAR_MARGE, CADRE_PAR_DIMENSIONS],
                         unit="", group="Forme",
                         tooltip="Relief: le champ à vider autour de "
                                 "la forme se donne SOIT par une "
                                 "marge autour du dessin, SOIT par "
                                 "les dimensions d'un rectangle "
                                 "centré sur lui — l'un ou l'autre, "
                                 "pas les deux."),
            ParameterDef("cadre_marge", "Marge du cadre",
                         ParameterType.FLOAT, default=2.0,
                         min_value=0.1, max_value=200.0, unit="mm",
                         group="Forme",
                         tooltip="Relief, cadre par marge: jusqu'où "
                                 "descendre autour de la forme, "
                                 "mesuré depuis son emprise."),
            ParameterDef("cadre_largeur", "Cadre: largeur X",
                         ParameterType.FLOAT, default=50.0,
                         min_value=0.0, max_value=2000.0, unit="mm",
                         group="Forme",
                         tooltip="Relief: la largeur du champ, centré "
                                 "sur le dessin. 0 = emprise + marge."),
            ParameterDef("cadre_hauteur", "Cadre: hauteur Y",
                         ParameterType.FLOAT, default=20.0,
                         min_value=0.0, max_value=2000.0, unit="mm",
                         group="Forme",
                         tooltip="Relief: la hauteur du champ, centré "
                                 "sur le dessin. 0 = emprise + marge."),
            ParameterDef("cadre_rayon", "Cadre: rayon des coins",
                         ParameterType.FLOAT, default=0.0,
                         min_value=0.0, max_value=500.0, unit="mm",
                         group="Forme",
                         tooltip="Relief: coins arrondis du champ. "
                                 "0 = coins vifs."),
            ParameterDef("decalage", "Décalage du contour",
                         ParameterType.FLOAT, default=0.0,
                         min_value=-100.0, max_value=100.0, unit="mm",
                         group="Forme",
                         tooltip="Déporte le contour avant tout "
                                 "calcul: positif vers l'extérieur, "
                                 "négatif vers l'intérieur. Les "
                                 "contours décalés ne se recoupent "
                                 "jamais."),
        ]

    @classmethod
    def _champs_outil(cls) -> List[ParameterDef]:
        return [
            ParameterDef("angle", "Angle du cône",
                         ParameterType.FLOAT,
                         default=vcarve.ANGLE_DEFAUT,
                         min_value=1.0, max_value=179.0, unit="°",
                         group="Outil conique",
                         tooltip="Angle TOTAL de la pointe. Lu dans le "
                                 "nom de l'outil (« Con 30° 0.2 ») "
                                 "quand le champ est vide."),
            ParameterDef("troncature", "Troncature",
                         ParameterType.FLOAT,
                         default=vcarve.TRONCATURE_DEFAUT,
                         min_value=0.0, max_value=10.0, unit="mm",
                         group="Outil conique",
                         tooltip="Diamètre du méplat en bout. C'est "
                                 "lui qui donne la largeur du trait au "
                                 "ras de la surface."),
        ]

    @classmethod
    def _champ_passe_z(cls) -> List[ParameterDef]:
        """De combien l'outil descend d'une passe à l'autre."""
        return [
            ParameterDef("profondeur_passe", "Profondeur par passe",
                         ParameterType.FLOAT, default=0.0,
                         min_value=0.0, max_value=50.0, unit="mm",
                         group="Passes en Z",
                         tooltip="0 = tout en une descente. Sinon "
                                 "l'outil reprend le parcours à "
                                 "chaque cran de profondeur jusqu'à "
                                 "la cote — ce qu'il faut dès que la "
                                 "gravure est profonde ou la matière "
                                 "dure."),
        ]

    @classmethod
    def _paliers(cls, params: Dict[str, Any],
                 profondeur: float) -> List[float]:
        """Les profondeurs successives, jusqu'à la cote.

        Rend au moins la cote finale: une passe unique reste le cas
        normal."""
        pas = cls._nombre(params, 'profondeur_passe', 0.0)
        if pas <= 1e-9 or pas >= profondeur:
            return [profondeur]
        paliers = []
        z = pas
        while z < profondeur - 1e-9:
            paliers.append(round(z, 4))
            z += pas
        paliers.append(round(profondeur, 4))
        return paliers

    @classmethod
    def _champs_gamme(cls) -> List[ParameterDef]:
        """La place de cette opération dans la gamme d'outils.

        Un logo se grave souvent à plusieurs outils: une pointe
        large fait ce qu'elle peut, une plus fine reprend, la plus
        fine finit les traits les plus fins. Sans reprise, chacune referait tout
        le dessin — des heures pour rien."""
        return [
            ParameterDef("reprise", "Reprendre le reste",
                         ParameterType.BOOL, default=False, unit="",
                         group="Gamme",
                         tooltip="Ne travailler que ce que les "
                                 "gravures PRÉCÉDENTES du programme "
                                 "n'ont pas pu enlever — mêmes "
                                 "contours, outil plus fin. Le "
                                 "parcours en devient beaucoup plus "
                                 "court."),
            ParameterDef("offset_xy", "Matière laissée (XY)",
                         ParameterType.FLOAT, default=0.0,
                         min_value=0.0, max_value=10.0, unit="mm",
                         group="Gamme",
                         tooltip="Épaisseur laissée le long du "
                                 "contour par CET outil. L'outil "
                                 "suivant la reprend."),
            ParameterDef("offset_z", "Matière laissée (Z)",
                         ParameterType.FLOAT, default=0.0,
                         min_value=0.0, max_value=10.0, unit="mm",
                         group="Gamme",
                         tooltip="Hauteur laissée au fond. La cote "
                                 "visée par cette opération est la "
                                 "profondeur moins cette valeur."),
            ParameterDef("cadre_decalage", "Décalage du cadre "
                         "(ce poste)", ParameterType.FLOAT,
                         default=0.0, min_value=-100.0,
                         max_value=100.0, unit="mm", group="Gamme",
                         tooltip="Relief: ce poste travaille un cadre "
                                 "agrandi (positif) ou réduit "
                                 "(négatif) de cette valeur, par "
                                 "rapport au cadre de la gamme. Le "
                                 "détourage passe dehors, un "
                                 "évidement peut déborder du "
                                 "rectangle de gravure."),
        ]

    @classmethod
    def _champs_contour(cls) -> List[ParameterDef]:
        return [
            ParameterDef("contours", "Contours", ParameterType.STRING,
                         default="", unit="", group="Contour",
                         expert_only=True,
                         tooltip="Relevés au canvas (bouton « Reprendre "
                                 "les contours »). Un contour dans un "
                                 "autre est un trou: l'intérieur d'un "
                                 "« O ». Trois imbrications et le "
                                 "centre redevient plein."),
            ParameterDef("sequence_name", "Nom séquence",
                         ParameterType.STRING, default="",
                         unit="", group="Séquence", expert_only=True,
                         tooltip="Nom du bloc $$$ (rendu unique à la "
                                 "génération)"),
        ]

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        return ToolRequirement(
            tool_types=[],
            description="Fraise conique (Con 30° …)")

    # ── Géométrie ──

    @staticmethod
    def contours(params: Dict[str, Any]) -> List[List]:
        """Contours relevés, en coordonnées machine."""
        bruts = params.get('contours') or []
        if isinstance(bruts, str):
            return []
        sortie = []
        for contour in bruts:
            points = []
            for entree in contour or []:
                try:
                    points.append((float(entree[0]), float(entree[1])))
                except (TypeError, ValueError, IndexError):
                    continue
            if len(points) >= 3:
                sortie.append(points)
        return sortie

    @classmethod
    def diametre_cylindrique(cls, params: Dict[str, Any]):
        """Diamètre si l'outil monté est une fraise cylindrique.

        Le formulaire l'emporte (« Diamètre » de l'étage), sinon le
        nom de l'outil: « Cyl 6 z2L12 »."""
        saisi = cls._nombre(params, 'diametre', 0.0)
        if saisi > 0:
            return saisi
        fiche = cls._fiche_outil(params)
        if fiche is not None:
            return fiche[0]
        return vcarve.diametre_depuis_nom(
            str(params.get('_tool_name', '') or ''))

    @classmethod
    def _fiche_outil(cls, params: Dict[str, Any]):
        """Ce que tools.json dit de l'outil monté, avant son nom.

        (Ø, None) pour une cylindrique, (None, (angle, troncature))
        pour une conique, None si la fiche ne dit rien. Un angle de
        pointe non nul fait la conique; sinon un Ø de coupe fait la
        cylindrique."""
        fiche = params.get('_tool_geometrie') or {}
        if not isinstance(fiche, dict):
            return None

        def _f(cle):
            try:
                valeur = fiche.get(cle)
                return None if valeur in (None, "") else float(valeur)
            except (TypeError, ValueError):
                return None
        angle = _f('TipAngle')
        if angle and angle > 0:
            troncature = _f('TipDiameter')
            return (None, (angle, troncature if troncature is not None
                           else vcarve.TRONCATURE_DEFAUT))
        diametre = _f('Diameter')
        if diametre and diametre > 0:
            return (diametre, None)
        return None

    @classmethod
    def est_cylindrique(cls, params: Dict[str, Any]) -> bool:
        return cls.diametre_cylindrique(params) is not None

    @classmethod
    def cone(cls, params: Dict[str, Any]) -> tuple:
        """(angle, troncature) retenus pour cette opération.

        Le formulaire fait foi; à défaut, le NOM de l'outil monté —
        « Con 30° 0.2 » dit tout ce qu'il faut savoir.

        Une fraise cylindrique passe par la même porte: c'est un
        cône d'angle nul dont la « troncature » est le diamètre.
        Tout le reste du calcul — anneaux, évidement, balayage,
        couverture — marche alors sans un seul cas particulier."""
        diametre = cls.diametre_cylindrique(params)
        if diametre is not None:
            return (vcarve.ANGLE_CYLINDRIQUE, diametre)
        fiche = cls._fiche_outil(params)
        if fiche is not None and fiche[1] is not None:
            defaut_angle, defaut_tronc = fiche[1]
        else:
            defaut_angle, defaut_tronc = vcarve.cone_depuis_nom(
                str(params.get('_tool_name', '') or ''))

        def _f(cle, defaut):
            try:
                valeur = float(params.get(cle, 0.0) or 0.0)
            except (TypeError, ValueError):
                return defaut
            return valeur if valeur > 0 else defaut
        return (_f('angle', defaut_angle),
                _f('troncature', defaut_tronc))

    @staticmethod
    def _nombre(params: Dict[str, Any], cle: str, defaut: float
                ) -> float:
        try:
            valeur = params.get(cle, defaut)
            return float(defaut if valeur in (None, "") else valeur)
        except (TypeError, ValueError):
            return defaut

    #: parcours déjà calculés: {signature: étapes}. Le formulaire,
    #: l'aperçu et la génération demandaient chacun le leur — trois
    #: fois le même calcul à chaque clic sur l'opération.
    _CACHE: Dict[str, List[Dict]] = {}
    #: au-delà, on oublie le plus ancien (un plan pèse quelques
    #: milliers de points)
    _CACHE_MAX = 8
    #: par signature: {'couverture': 0..1, 'reste': mm², 'zone': mm²}
    #: — ce que le parcours enlève vraiment du dessin
    _CACHE_MESURES: Dict[str, Dict[str, float]] = {}
    #: par signature: la surface balayée par l'outil. La gamme la
    #: redemande à chaque étage suivant, et c'est le calcul le plus
    #: cher de la chaîne.
    _CACHE_BALAYAGE: Dict[str, Any] = {}
    #: au-delà de cette part du dessin hors d'atteinte de la
    #: pointe, la pièce ne ressemblera pas au DXF: il faut le dire
    #: AVANT d'usiner
    HORS_ATTEINTE_MAXI = 0.05

    @classmethod
    def _signature(cls, params: Dict[str, Any]) -> str:
        """Empreinte de ce qui change le parcours.

        Les contours en font partie: changer de dessin change le
        parcours, et rien d'autre dans les paramètres ne le dirait."""
        import hashlib
        # `_tool_name` en fait partie: la géométrie de l'outil se
        # lit dans son nom, et changer d'outil change le parcours.
        # Tous ceux qui demandent un plan doivent donc le joindre —
        # c'est ce que fait `params_outil`.
        # `preview` (l'œil) n'y est PAS: masquer puis montrer un
        # poste de gamme changeait l'empreinte, le parcours était
        # « à recalculer » et le canvas ne le dessinait plus. La
        # fiche de l'outil (tools.json) y est: changer son angle
        # change le parcours.
        cles = sorted(k for k in params
                      if (not k.startswith('_')
                          or k in ('_amont', '_tool_name',
                                   '_tool_geometrie'))
                      and k not in ('sequence_name', 'mot_ebauche',
                                    'preview'))
        morceaux = [cls.__name__]
        for cle in cles:
            morceaux.append(f"{cle}={params.get(cle)!r}")
        brut = "|".join(morceaux).encode('utf-8', 'replace')
        return hashlib.blake2b(brut, digest_size=16).hexdigest()

    @classmethod
    def plan(cls, params: Dict[str, Any],
             progression=None) -> List[Dict]:
        """Les étapes du parcours, calculées une seule fois.

        Le calcul lui-même est dans `_calculer_plan`. `progression`
        est l'appelable `(fraction, texte) -> bool` de vcarve: rendre
        False arrête le calcul, et rien n'entre au cache."""
        signature = cls._signature(params)
        connu = cls._CACHE.get(signature)
        if connu is not None:
            return connu
        etapes = cls._calculer_plan(params, progression)
        if len(cls._CACHE) >= cls._CACHE_MAX:
            vieille = next(iter(cls._CACHE))
            cls._CACHE.pop(vieille)
            cls._CACHE_MESURES.pop(vieille, None)
        cls._CACHE[signature] = etapes
        # La mesure (couverture, reste, atteignable) coûte cinq fois
        # le parcours lui-même sur un logo dense: elle attend qu'on
        # la demande. Un tour de contour de trois rectangles mettait
        # 6,8 s, dont 6,6 de mesure.
        return etapes

    @classmethod
    def _cadre(cls, params: Dict[str, Any]) -> Dict[str, float]:
        """Les réglages du champ, tels que `vcarve.zone_a_usiner`
        les attend. UN endroit pour les lire: trois calculs en ont
        besoin, et ils doivent voir le même cadre."""
        # Le décalage du cadre est propre au poste: la gamme partage
        # le cadre, chaque passage peut en sortir (ou y rentrer)
        d = cls._nombre(params, 'cadre_decalage', 0.0)
        # par marge OU par dimensions: l'autre réglage ne compte pas
        par_dimensions = (mode_du_cadre(params) == CADRE_PAR_DIMENSIONS)
        largeur = cls._nombre(params, 'cadre_largeur', 0.0) \
            if par_dimensions else 0.0
        hauteur = cls._nombre(params, 'cadre_hauteur', 0.0) \
            if par_dimensions else 0.0
        rayon = cls._nombre(params, 'cadre_rayon', 0.0)
        return {
            'relief': (str(params.get('mode', 'Creux')) == "Relief"),
            'cadre_marge': max(0.0, cls._nombre(params, 'cadre_marge', 2.0)
                               + d),
            'decalage': cls._nombre(params, 'decalage', 0.0),
            'cadre_largeur': max(0.0, largeur + 2 * d) if largeur > 0
            else 0.0,
            'cadre_hauteur': max(0.0, hauteur + 2 * d) if hauteur > 0
            else 0.0,
            'cadre_rayon': max(0.0, rayon + d) if rayon > 0 else 0.0,
        }

    @classmethod
    def zone_de_travail(cls, params: Dict[str, Any],
                        appliquer_offset: bool = True,
                        progression=None, avec_amont: bool = True):
        """La zone que CETTE opération doit usiner.

        C'est la zone du dessin, moins la matière qu'on laisse le
        long du contour, moins ce que les opérations d'amont ont déjà
        enlevé (mesuré sur leur parcours, pas supposé). Dans cet
        ordre: la matière laissée se compte depuis le trait du
        dessin, pas depuis le bord de ce qu'un autre outil a vidé.
        `avec_amont=False` rend la zone entière — ce qu'il faut pour
        calculer un parcours qui peut rouler dans le déjà vidé."""
        contours = cls.contours(params)
        if not contours:
            return None
        vcarve.avancer(progression, 0.0, "zone du dessin")
        forme = vcarve.zone_a_usiner(contours, **cls._cadre(params))
        if forme is None:
            return None
        marge = cls._nombre(params, 'offset_xy', 0.0) \
            if appliquer_offset else 0.0
        if marge > 1e-9:
            forme = forme.buffer(-marge, quad_segs=vcarve.QUADRANTS,
                                 join_style=1)
            if forme.is_empty:
                return None
        if not avec_amont:
            return forme
        for amont in cls.amont(params, progression):
            balaye = amont.get('balayage')
            if balaye is None:
                continue
            forme = forme.difference(balaye)
            if forme.is_empty:
                return None
        return forme

    @classmethod
    def surface_balayee(cls, params: Dict[str, Any], progression=None,
                        profondeur_mini: float = 0.0):
        """Ce que l'outil de cette opération enlève, en surface.

        Avec `profondeur_mini`, seulement là où il est descendu au
        moins jusque-là. Gardée: la gamme la redemande pour chaque
        étage suivant."""
        cle = f"{cls._signature(params)}@{float(profondeur_mini):.3f}"
        if cle in cls._CACHE_BALAYAGE:
            return cls._CACHE_BALAYAGE[cle]
        plan = cls.plan(params, vcarve.sous_progression(
            progression, 0.0, 0.5))
        angle, tron = cls.cone(params)
        try:
            balaye = vcarve.balayage(plan, angle, tron,
                                     vcarve.sous_progression(
                                         progression, 0.5, 1.0),
                                     profondeur_mini=profondeur_mini)
        except Exception:
            balaye = None
        if len(cls._CACHE_BALAYAGE) >= cls._CACHE_MAX:
            cls._CACHE_BALAYAGE.pop(next(iter(cls._CACHE_BALAYAGE)))
        cls._CACHE_BALAYAGE[cle] = balaye
        return balaye

    @classmethod
    def cote(cls, params: Dict[str, Any]) -> float:
        """La profondeur que cette opération vise, matière au fond
        déduite — quel que soit le nom du champ qui la porte."""
        return cls.profondeur_visee(params, cls.CLE_PROFONDEUR)

    @classmethod
    def amont(cls, params: Dict[str, Any],
              progression=None) -> List[Dict]:
        """Ce que les opérations précédentes ont enlevé.

        Rend une liste de {'nom', 'balayage'} — le balayage est la
        surface que leur outil a réellement balayée, et FINIE à la
        cote de cette opération: ce qu'une conique a gravé à faible
        profondeur n'est pas fait pour la cylindrique qui évide plus
        bas. Sans cette règle, la cylindrique de fin de gamme tenait
        pour évidée la bande qu'une conique avait creusée au milieu
        d'un contre-jour, et y laissait une arête à mi-hauteur."""
        if not params.get('reprise'):
            return []
        from src.operations.registry import OperationRegistry
        sortie = []
        entrees = params.get('_amont') or []
        cote = cls.cote(params)
        for numero, entree in enumerate(entrees):
            try:
                classe = OperationRegistry.get(entree['op_type'])
                balaye = classe.surface_balayee(
                    entree['params'],
                    vcarve.sous_progression(
                        progression, numero / len(entrees),
                        (numero + 1) / len(entrees),
                        f"reprise de {entree.get('nom', '')} — "),
                    profondeur_mini=cote)
            except Exception:
                continue
            sortie.append({'nom': entree.get('nom', ''),
                           'balayage': balaye})
        return sortie

    @classmethod
    def profondeur_visee(cls, params: Dict[str, Any],
                         cle: str = 'profondeur_max') -> float:
        """La cote de cette opération, matière au fond déduite."""
        return max(0.0, cls._nombre(params, cle, 1.0)
                   - cls._nombre(params, 'offset_z', 0.0))

    @classmethod
    def _mesurer(cls, params: Dict[str, Any],
                 plan: List[Dict], progression=None) -> Dict[str, float]:
        """Quelle part du dessin ce parcours enlève vraiment.

        Un logo de signature gravé à la 30° 0,6: l'outil, plus large
        que le trait, ne touchait rien — et rien ne le disait avant
        que la pièce sorte de la machine."""
        from src.core import vcarve
        contours = cls.contours(params)
        if not contours:
            return {}
        try:
            forme = vcarve.zone_a_usiner(contours,
                                         **cls._cadre(params))
            if forme is None:
                return {}
            angle, tron = cls.cone(params)
            vcarve.avancer(progression, 0.0, "surface balayée")
            balaye = cls.surface_balayee(
                params, vcarve.sous_progression(progression, 0.0, 0.6))
            vcarve.avancer(progression, 0.6, "couverture du dessin")
            couv = (0.0 if balaye is None
                    else min(1.0, balaye.intersection(forme).area
                             / forme.area))
            # Le reste se mesure sur la zone que CETTE opération
            # avait à faire — l'amont déduit. Mesuré sur le dessin
            # entier, un outil de reprise semblait laisser plus que
            # celui d'avant.
            a_faire = cls.zone_de_travail(params) or forme
            reste = a_faire if balaye is None \
                else a_faire.difference(balaye)
            reste = None if reste.is_empty else reste
            # Ce que la POINTE ne peut pas atteindre est d'une autre
            # nature que ce que la stratégie ne balaie pas: un V dans
            # une bande large ne couvre pas la bande, et c'est
            # normal. Seul le premier défaut appelle un autre outil.
            vcarve.avancer(progression, 0.8, "part hors d'atteinte")
            atteint = vcarve.atteignable(forme, tron)
            hors = 1.0 - (0.0 if atteint is None
                          else atteint.area / forme.area)
            vcarve.avancer(progression, 1.0, "mesures prêtes")
        except Exception:
            return {}
        return {'couverture': couv, 'zone': forme.area,
                'a_faire': a_faire.area,
                'hors_atteinte': max(0.0, hors),
                'reste': 0.0 if reste is None else reste.area}

    @classmethod
    def _queue_resume(cls, params: Dict[str, Any], texte: str,
                      mesurer: bool = False) -> str:
        """La fin de toute ligne d'état: place dans la gamme.

        D'où vient le reste, ce qu'on laisse au suivant, et ce que
        l'outil ne sait pas atteindre. Les trois opérations disent
        la même chose de la même façon."""
        amont = cls.amont(params)
        if amont:
            noms = ", ".join(a['nom'] for a in amont if a['nom'])
            texte += (f" — reprise de {len(amont)} opé"
                      + (f" ({noms})" if noms else ""))
        if not cls.MESURE_COUVERTURE:
            # Un tour de contour n'usine pas le dessin: dire qu'il
            # en couvre 0 % serait exact et absurde.
            return texte
        mesures = cls.mesures(params, calculer=mesurer)
        if mesures.get('reste', 0.0) > 0.01:
            texte += (f" — laisse {mesures['reste']:.2f} mm² à "
                      "l'outil suivant")
        if 'couverture' in mesures:
            part = 100.0 * mesures['couverture']
            texte += f" — couvre {part:.0f} % du tracé"
            hors = mesures.get('hors_atteinte', 0.0)
            if hors > cls.HORS_ATTEINTE_MAXI:
                conseil = cls.outil_conseille(params)
                texte += (f", {100 * hors:.0f} % du dessin trop fin "
                          "pour cette pointe")
                if conseil:
                    texte += f" (il faudrait une pointe {conseil:g})"
        return texte

    @classmethod
    def mesures(cls, params: Dict[str, Any],
                calculer: bool = False,
                progression=None) -> Dict[str, float]:
        """Couverture, reste, part hors d'atteinte.

        Sans `calculer`, on ne rend que ce qui est DÉJÀ mesuré: la
        ligne d'état se rafraîchit à chaque frappe, et mesurer là
        rendait la saisie impossible."""
        signature = cls._signature(params)
        connu = cls._CACHE_MESURES.get(signature)
        if connu is not None or not calculer:
            return connu or {}
        plan = cls.plan_si_connu(params)
        if plan is None:
            return {}
        mesures = cls._mesurer(params, plan, progression)
        if len(cls._CACHE_MESURES) >= cls._CACHE_MAX:
            cls._CACHE_MESURES.pop(next(iter(cls._CACHE_MESURES)))
        cls._CACHE_MESURES[signature] = mesures
        return mesures

    @classmethod
    def outil_conseille(cls, params: Dict[str, Any]):
        """La troncature qui atteindrait tout, ou None si ça va.

        Le rayon de pointe doit tenir dans la moitié du trait le
        plus fin qu'on veut au fond."""
        from src.core import vcarve
        mesures = cls.mesures(params)
        if not mesures or mesures.get('hors_atteinte', 0.0) \
                <= cls.HORS_ATTEINTE_MAXI:
            return None
        contours = cls.contours(params)
        if not contours:
            return None
        try:
            forme = vcarve.zone(contours)
        except Exception:
            return None
        if forme is None:
            return None
        for candidate in (0.4, 0.2, 0.1, 0.05, 0.02):
            atteint = vcarve.atteignable(forme, candidate)
            if atteint is not None and atteint.area >= (
                    1.0 - cls.HORS_ATTEINTE_MAXI) * forme.area:
                return candidate
        return None

    @classmethod
    def plan_si_connu(cls, params: Dict[str, Any]):
        """Le parcours S'IL est déjà calculé, sinon None.

        Ce que le formulaire et l'aperçu appellent: sur un dessin
        chargé, recalculer à chaque frappe rendait la saisie
        inutilisable. Le bouton « Calculer » fait le travail."""
        return cls._CACHE.get(cls._signature(params))

    @classmethod
    def _calculer_plan(cls, params: Dict[str, Any],
                       progression=None) -> List[Dict]:
        """À définir: les étapes du parcours, dans l'ordre."""
        raise NotImplementedError

    # ── Sortie ──

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        """Dans le sous-programme: appel de la séquence par son nom."""
        return f"    {cls.nom_sequence(params)}"

    @classmethod
    def nom_sequence(cls, params: Dict[str, Any]) -> str:
        nom = str(params.get('sequence_name', '') or '').strip()
        return nom or f"{cls.PREFIXE_SEQ}_1"

    @classmethod
    def build_sequence_block(cls, params: Dict[str, Any]) -> str:
        """Bloc $$$ du parcours calculé.

        Coordonnées MODALES, comme dans les fichiers de la machine:
        seuls les axes qui changent sont réécrits. Et l'outil ne
        remonte au dégagement QUE s'il ne peut pas rejoindre le
        départ suivant à travers la matière déjà retirée."""
        plan = cls.plan(params)
        if not plan:
            return ""

        safe_z = cls._nombre(params, '_safe_rapid_z', 15.0)
        approche = cls._nombre(params, '_stroke_cutting_z', 1.0)
        mot_ebauche = str(params.get('mot_ebauche', '')
                          or 'Roughing').strip()

        lignes = [f"$$$ {cls.nom_sequence(params)}", "Spindle On"]
        etat = {'x': None, 'y': None, 'z': None, 'feed': None}

        def _feed(nom):
            if etat['feed'] != nom:
                lignes.append(f"Feed {nom}")
                etat['feed'] = nom

        def _deplacer(x, y, z=None, plonger=False):
            """Un mouvement d'usinage, en coordonnées modales."""
            parts = []
            if etat['x'] is None or abs(x - etat['x']) > 1e-6:
                parts.append(f"X={round(x, 4):g}")
            if etat['y'] is None or abs(y - etat['y']) > 1e-6:
                parts.append(f"Y={round(y, 4):g}")
            if z is not None and (etat['z'] is None
                                  or abs(z - etat['z']) > 1e-6):
                parts.append(f"Z={round(z, 4):g}")
            if not parts:
                return
            _feed("Plunge" if plonger else etat['feed'] or "Finishing")
            lignes.append("Line " + " ".join(parts))
            etat['x'], etat['y'] = x, y
            if z is not None:
                etat['z'] = z

        def _degager(x, y):
            """Remonter, se placer, redescendre à l'approche."""
            lignes.append(f"Rapid Z={approche:g}")
            lignes.append(f"Rapid X={round(x, 4):g} "
                          f"Y={round(y, 4):g}")
            etat['x'], etat['y'], etat['z'] = x, y, approche
            etat['feed'] = None

        premier = True
        for etape in plan:
            avance = ("Finishing" if etape.get('role') != 'ebauche'
                      else mot_ebauche)
            if etape['type'] == 'anneau':
                # « -0 » n'est pas une cote: la passe qui rase la
                # surface s'ecrit Z=0
                creux = abs(float(etape['profondeur']))
                plat = -creux if creux > 1e-9 else 0.0
                morceaux = [(contour, plat)
                            for contour in etape['contours']]
            else:
                morceaux = [(etape['points'], None)]

            for index, (contour, z_plat) in enumerate(morceaux):
                if len(contour) < 2:
                    continue
                x0, y0 = contour[0][0], contour[0][1]
                if premier:
                    lignes.append(
                        f"PrePositioning X={round(x0, 4):g} "
                        f"Y={round(y0, 4):g} Z={safe_z:g}")
                    lignes.append(f"Rapid Z={approche:g}")
                    etat.update({'x': x0, 'y': y0, 'z': approche})
                    premier = False
                elif index == 0 and etape.get('liaison_directe'):
                    # Rester à la profondeur atteinte: le chemin
                    # jusqu'au départ suivant est déjà vide
                    _feed(avance)
                    _deplacer(x0, y0)
                else:
                    _degager(x0, y0)

                if z_plat is not None:
                    _deplacer(x0, y0, z_plat, plonger=True)
                    _feed(avance)
                    for point in contour[1:]:
                        _deplacer(point[0], point[1])
                else:
                    # Passage 3D: la profondeur change à chaque point
                    z0 = -abs(contour[0][2])
                    _deplacer(x0, y0, z0, plonger=True)
                    _feed(avance)
                    for x, y, z in contour[1:]:
                        _deplacer(x, y, -abs(z))

        if premier:                    # rien n'a été écrit
            return ""
        lignes.append(f"Rapid Z={safe_z:g}")
        lignes.append("MoveToSafetyPosition")
        return "\n".join(lignes)

    @classmethod
    def validate_params(cls, params: Dict[str, Any]) -> List[str]:
        erreurs = super().validate_params(params)
        if not cls.contours(params):
            erreurs.append(
                "Aucun contour relevé — sélectionnez les tracés au "
                "canvas, puis « Reprendre les contours ».")
        return erreurs

    @classmethod
    def resume(cls, params: Dict[str, Any], calculer: bool = True
               ) -> str:
        """Une ligne d'état: ce que le calcul a donné."""
        plan = cls.plan(params) if calculer \
            else cls.plan_si_connu(params)
        if plan is None:
            return "parcours non calculé"
        if not plan:
            if cls.est_cylindrique(params):
                return ("aucun parcours: une fraise cylindrique ne "
                        "grave pas au V — prenez une conique, ou "
                        "l'opération Évidement")
            return ("aucun parcours: la pointe de l'outil est plus "
                    "large que le tracé")
        anneaux = sum(1 for e in plan if e['type'] == 'anneau')
        medians = sum(1 for e in plan if e['type'] == 'median')
        fond = 0.0
        for etape in plan:
            if etape['type'] == 'anneau':
                fond = max(fond, etape['profondeur'])
            else:
                fond = max([fond] + [z for _x, _y, z
                                     in etape['points']])
        directes = sum(1 for e in plan if e.get('liaison_directe'))
        texte = (f"{anneaux} anneau(x), {medians} passage(s) 3D, "
                 f"fond à {fond:g} mm, {directes} liaison(s) sans "
                 f"remontée")
        return cls._queue_resume(params, texte, calculer)


@OperationRegistry.register("gravure_2d5")
class Gravure2D5(_SequenceConique):
    """Gravure au V: la profondeur suit la largeur de la forme."""

    OP_TYPE = "gravure_2d5"
    DISPLAY_NAME = "Parcours gravure (V)"
    DESCRIPTION = ("Gravure au V d'un contour du dessin: profondeur "
                   "variable, remontées d'angles calculées")
    ICON = "engrave"
    PREFIXE_SEQ = "GRAVURE"

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return [
            ParameterDef("profondeur_max", "Profondeur maxi",
                         ParameterType.FLOAT, default=1.0,
                         min_value=0.01, max_value=50.0, unit="mm",
                         group="Gravure",
                         tooltip="Le V s'arrête là, même si la forme "
                                 "est plus large. Sans limite, une "
                                 "lettre de 5 mm de large descendrait "
                                 "de 9 mm avec un cône à 30°."),
            ParameterDef("strategie", "Stratégie",
                         ParameterType.CHOICE,
                         default=vcarve.STRATEGIES[0],
                         choices=list(vcarve.STRATEGIES), unit="",
                         group="Gravure",
                         tooltip="Les ANNEAUX vident la matière à "
                                 "profondeur constante: entre deux, "
                                 "l'outil laisse une marche.\n"
                                 "L'AXE MÉDIAN 3D suit le squelette "
                                 "de la forme, profondeur variable: "
                                 "le flanc du V est engendré par le "
                                 "cône, sans marche — c'est lui qui "
                                 "lisse les pointes."),
            ParameterDef("pas_radial", "Pas radial",
                         ParameterType.FLOAT, default=0.05,
                         min_value=0.005, max_value=2.0, unit="mm",
                         group="Gravure",
                         tooltip="Anneaux: écart entre deux passes, "
                                 "mesuré à plat. Le fond exact est "
                                 "toujours atteint."),
            ParameterDef("pas_median", "Pas de l'axe médian",
                         ParameterType.FLOAT, default=0.2,
                         min_value=0.02, max_value=5.0, unit="mm",
                         group="Gravure", expert_only=True,
                         tooltip="Finesse du squelette. Plus fin = "
                                 "plus de points dans la séquence."),
            ParameterDef("surepaisseur", "Surépaisseur d'ébauche",
                         ParameterType.FLOAT, default=0.0,
                         min_value=0.0, max_value=5.0, unit="mm",
                         group="Ébauche",
                         tooltip="0 = pas d'ébauche séparée.\n"
                                 "Sinon les anneaux passent en "
                                 "avance d'ÉBAUCHE en laissant cette "
                                 "épaisseur sur les flancs, et l'axe "
                                 "médian reprend à la cote en avance "
                                 "de FINITION."),
            ParameterDef("mot_ebauche", "Avance d'ébauche",
                         ParameterType.STRING, default="Roughing",
                         unit="", group="Ébauche", expert_only=True,
                         tooltip="Nom de l'avance écrite dans la "
                                 "séquence (« Feed Roughing »). La "
                                 "documentation machine atteste "
                                 "Finishing, Plunge et Ramp; Roughing "
                                 "suit SetFeedTechnology. À changer "
                                 "ici si la machine le refuse."),
        ] + cls._champ_passe_z() + cls._champs_forme() \
          + cls._champs_outil() + cls._champs_gamme() \
          + cls._champs_contour()

    @classmethod
    def _calculer_plan(cls, params: Dict[str, Any],
                       progression=None) -> List[Dict]:
        contours = cls.contours(params)
        if not contours:
            return []
        if cls.est_cylindrique(params):
            # Une cylindrique ne grave pas au V: elle n'a pas de
            # flanc. Lui faire suivre l'axe médian la ferait plonger
            # à fond partout.
            return []
        angle, troncature = cls.cone(params)
        forme = cls.zone_de_travail(
            params, progression=vcarve.sous_progression(
                progression, 0.0, 0.2))
        if forme is None:
            return []
        profondeur = cls.profondeur_visee(params)
        paliers = cls._paliers(params, profondeur)
        if len(paliers) > 1:
            # Gravure en plusieurs descentes: le MÊME parcours,
            # repris à chaque cran. L'outil ne plonge jamais de plus
            # d'une passe. L'axe médian se calcule UNE fois, au plus
            # profond; chaque palier le borne à sa cote.
            strategie = str(params.get('strategie',
                                       vcarve.STRATEGIES[0]))
            passages = None
            if strategie != "Anneaux seuls":
                passages = vcarve.passages_median(
                    forme, angle, troncature, profondeur,
                    cls._nombre(params, 'pas_median', 0.2),
                    progression=vcarve.sous_progression(
                        progression, 0.2, 0.6, "axe médian — "))
            etapes = []
            for numero, palier in enumerate(paliers):
                for etape in vcarve.plan_gravure(
                        contours, angle=angle, troncature=troncature,
                        profondeur_max=palier, forme=forme,
                        passages=passages,
                        progression=vcarve.sous_progression(
                            progression,
                            0.6 + 0.4 * numero / len(paliers),
                            0.6 + 0.4 * (numero + 1) / len(paliers),
                            f"passe {numero + 1}/{len(paliers)} — "),
                        pas_radial=cls._nombre(params, 'pas_radial',
                                               0.05),
                        strategie=strategie,
                        surepaisseur=cls._nombre(params,
                                                 'surepaisseur', 0.0),
                        pas_median=cls._nombre(params, 'pas_median',
                                               0.2)):
                    etape['palier'] = numero
                    etapes.append(etape)
            return cls._pres_du_trait(etapes, params, angle,
                                      troncature, profondeur)
        return cls._pres_du_trait(vcarve.plan_gravure(
            contours, angle=angle, troncature=troncature,
            profondeur_max=profondeur,
            forme=forme,
            progression=vcarve.sous_progression(progression, 0.2, 1.0),
            pas_radial=cls._nombre(params, 'pas_radial', 0.05),
            strategie=str(params.get('strategie',
                                     vcarve.STRATEGIES[0])),
            surepaisseur=cls._nombre(params, 'surepaisseur', 0.0),
            pas_median=cls._nombre(params, 'pas_median', 0.2)),
            params, angle, troncature, profondeur)

    @classmethod
    def _pres_du_trait(cls, etapes: List[Dict], params: Dict[str, Any],
                       angle: float, troncature: float,
                       profondeur: float) -> List[Dict]:
        """En relief, ne garder que ce qui touche le dessin.

        Le champ d'une matrice est vidé par la cylindrique; la
        conique y fait le flanc des lettres et les creux trop
        étroits pour elle. Livrée au champ entier, elle creusait
        aussi son axe médian à la cote maxi — des minutes de V au
        milieu de nulle part, que l'évidement effaçait ensuite.

        Un passage compte s'il est à moins d'un rayon (à la cote
        maxi) d'un trait: c'est exactement là où le cône touche."""
        if str(params.get('mode', 'Creux')) != "Relief":
            return etapes
        if not params.get('pres_du_trait', True):
            return etapes
        contours = cls.contours(params)
        dessin = vcarve.zone(contours) if contours else None
        if dessin is None:
            return etapes
        portee = vcarve.rayon_a_profondeur(profondeur, angle, troncature) \
            + vcarve.TOLERANCE_PROFONDEUR
        garde = []
        for etape in etapes:
            points = etape.get('points')
            if points:
                for morceau in vcarve.decouper_3d(points, dessin, portee):
                    copie = dict(etape, points=morceau,
                                 liaison_directe=False)
                    garde.append(copie)
                continue
            if etape.get('contours'):
                morceaux = vcarve.decouper(etape['contours'], dessin,
                                           portee)
                if not morceaux:
                    continue
                garde.append(dict(etape, contours=morceaux,
                                  liaison_directe=False))
                continue
            garde.append(etape)
        return garde

    @classmethod
    def passes(cls, params: Dict[str, Any]) -> List[Dict]:
        """Anneaux seuls — ce que l'aperçu canvas sait dessiner à
        plat. Le plan complet passe par `plan()`."""
        return [e for e in cls.plan(params) if e['type'] == 'anneau']


@OperationRegistry.register("evidement_2d5")
class Evidement2D5(_SequenceConique):
    """Évidement: on vide la forme à profondeur constante."""

    OP_TYPE = "evidement_2d5"
    DISPLAY_NAME = "Parcours évidement"
    DESCRIPTION = ("Vide un contour du dessin à profondeur "
                   "constante, du bord vers le centre")
    ICON = "pocket"
    PREFIXE_SEQ = "EVIDEMENT"
    CLE_PROFONDEUR = 'profondeur'

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return [
            ParameterDef("profondeur", "Profondeur",
                         ParameterType.FLOAT, default=0.3,
                         min_value=0.01, max_value=50.0, unit="mm",
                         group="Évidement",
                         tooltip="Cote du fond. Avec un cône, c'est "
                                 "elle qui fixe le diamètre utile de "
                                 "l'outil."),
            ParameterDef("recouvrement", "Recouvrement",
                         ParameterType.FLOAT, default=40.0,
                         min_value=0.0, max_value=95.0, unit="%",
                         group="Évidement",
                         tooltip="Part du diamètre reprise d'un "
                                 "passage au suivant. 40 % laisse un "
                                 "fond propre sans allonger "
                                 "inutilement le parcours."),
        ] + cls._champ_passe_z() + cls._champs_forme() \
          + cls._champs_outil() + cls._champs_gamme() \
          + cls._champs_contour()

    @classmethod
    def _calculer_plan(cls, params: Dict[str, Any],
                       progression=None) -> List[Dict]:
        contours = cls.contours(params)
        if not contours:
            return []
        angle, troncature = cls.cone(params)
        # le reste à faire: ce que les outils d'amont ont laissé
        reste = cls.zone_de_travail(
            params, progression=vcarve.sous_progression(
                progression, 0.0, 0.2))
        if reste is None:
            return []
        # En reprise, les anneaux se calculent sur la matière
        # ENTIÈRE: l'outil peut rouler dans ce qu'un autre a vidé.
        # Calculés sur le reste, ils prenaient le bord du déjà vidé
        # pour une paroi — une bande étroite entre deux passages de
        # la cylindrique était « trop étroite » pour elle.
        entier = reste
        if params.get('reprise') and params.get('_amont'):
            entier = cls.zone_de_travail(params, avec_amont=False) \
                or reste
        passes = []
        paliers = cls._paliers(
            params, cls.profondeur_visee(params, 'profondeur'))
        for numero, palier in enumerate(paliers):
            rayon = vcarve.rayon_a_profondeur(palier, angle, troncature)
            for passe in vcarve.passes_evidement(
                    contours, profondeur=palier,
                    angle=angle, troncature=troncature,
                    recouvrement=cls._nombre(params, 'recouvrement',
                                             40.0),
                    forme=entier,
                    progression=vcarve.sous_progression(
                        progression,
                        0.2 + 0.8 * numero / len(paliers),
                        0.2 + 0.8 * (numero + 1) / len(paliers),
                        f"palier {palier:g} mm — ")):
                if entier is not reste:
                    # …mais on ne parcourt que ce qui enlève encore
                    passe['contours'] = vcarve.decouper(
                        passe['contours'], reste,
                        max(0.0, rayon - vcarve.TOLERANCE_PROFONDEUR))
                    if not passe['contours']:
                        continue
                passe['palier'] = numero
                passes.append(passe)
        # Ce qu'un palier a vidé, c'est sa PREMIÈRE passe (la plus
        # large) qui le dit: l'outil peut y rejoindre le départ
        # suivant à la cote — d'un anneau au voisin, et du dernier
        # anneau d'un palier au premier du suivant. Jugée sur le
        # dernier anneau seul (le plus petit), la liaison entre deux
        # paliers remontait toujours au dégagement.
        vide_du_palier = {}
        for passe in passes:
            vide_du_palier.setdefault(passe['palier'], passe.get('zone'))
        etapes = []
        precedente = None
        for passe in passes:
            etape = {'role': 'finition', 'type': 'anneau',
                     'profondeur': passe['profondeur'],
                     'contours': passe['contours'],
                     'palier': passe['palier']}
            debut = passe['contours'][0][0] if passe['contours'] \
                else None
            etape['liaison_directe'] = bool(
                precedente is not None and debut is not None
                and vcarve._segment_libre(precedente[0],
                                          precedente[1], debut))
            if passe['contours']:
                precedente = (vide_du_palier.get(passe['palier']),
                              passe['contours'][-1][-1])
            etapes.append(etape)
        return etapes

    @classmethod
    def passes(cls, params: Dict[str, Any]) -> List[Dict]:
        return cls.plan(params)

    @classmethod
    def resume(cls, params: Dict[str, Any], calculer: bool = True
               ) -> str:
        plan = cls.plan(params) if calculer \
            else cls.plan_si_connu(params)
        if plan is None:
            return "parcours non calculé"
        if not plan:
            return "aucun parcours"
        angle, troncature = cls.cone(params)
        z = cls._nombre(params, 'profondeur', 0.3)
        diametre = 2 * vcarve.rayon_a_profondeur(z, angle, troncature)
        directes = sum(1 for e in plan if e.get('liaison_directe'))
        return cls._queue_resume(
            params, mesurer=calculer, texte=(
                f"{len(plan)} passage(s) — Ø utile {diametre:.3f} mm "
                f"à {z:g} mm, {directes} liaison(s) sans "
                f"remontée"))


@OperationRegistry.register("contour_2d5")
class Contour2D5(_SequenceConique):
    """Le tour du champ, à la fraise cylindrique.

    C'est souvent le premier étage d'une gamme de gravure: avant
    les coniques, une cylindrique fait le tour de la gravure et descend
    à la cote, en laissant la matière que la finition reprendra.
    Elle n'évide pas tout le champ — elle en dégage le pourtour.
    """

    OP_TYPE = "contour_2d5"
    DISPLAY_NAME = "Parcours contour"
    DESCRIPTION = ("Fait le tour du champ de gravure et descend par "
                   "passes, en laissant la matière réglée")
    ICON = "contour"
    PREFIXE_SEQ = "CONTOUR"
    MESURE_COUVERTURE = False
    CLE_PROFONDEUR = 'profondeur'

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        from src.core import gamme
        return [
            ParameterDef("profondeur", "Profondeur",
                         ParameterType.FLOAT, default=3.0,
                         min_value=0.01, max_value=100.0, unit="mm",
                         group="Contour",
                         tooltip="Cote du fond du tour."),
            ParameterDef("profondeur_passe", "Profondeur par passe",
                         ParameterType.FLOAT, default=0.0,
                         min_value=0.0, max_value=50.0, unit="mm",
                         group="Contour",
                         tooltip="0 = la moitié du diamètre de "
                                 "l'outil. Une fraise de 2 descend "
                                 "alors par millimètre."),
            ParameterDef("contour_source", "Tour de",
                         ParameterType.CHOICE,
                         default=gamme.SOURCES_CONTOUR[0],
                         choices=list(gamme.SOURCES_CONTOUR),
                         unit="", group="Contour",
                         tooltip="Le CHAMP est le rectangle qui "
                                 "contient le dessin: l'outil en "
                                 "dégage le pourtour, par "
                                 "l'extérieur.\nCHAQUE CONTOUR: le "
                                 "tour de chaque lettre — par "
                                 "l'extérieur en relief (dans le "
                                 "champ), par l'intérieur en creux —, "
                                 "à un rayon plus la matière laissée "
                                 "du trait, jamais dans la "
                                 "lettre."),
            ParameterDef("marge_champ", "Marge du champ",
                         ParameterType.FLOAT, default=2.0,
                         min_value=0.0, max_value=200.0, unit="mm",
                         group="Contour",
                         tooltip="Distance entre le dessin et le "
                                 "bord du champ."),
            ParameterDef("diametre", "Diamètre de l'outil",
                         ParameterType.FLOAT, default=0.0,
                         min_value=0.0, max_value=50.0, unit="mm",
                         group="Contour",
                         tooltip="0 = lu dans le nom de l'outil "
                                 "(« Cyl 2 z1L4 »)."),
        ] + cls._champs_forme() + cls._champs_gamme() \
          + cls._champs_contour()

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        return ToolRequirement(
            tool_types=[],
            description="Fraise cylindrique (Cyl 2 …)")

    @classmethod
    def _etage(cls, params: Dict[str, Any]) -> Dict:
        from src.core import gamme
        diametre = cls.diametre_cylindrique(params)
        angle, troncature = cls.cone(params)
        cadre = cls._cadre(params)
        return gamme.etage(
            nom=str(params.get('sequence_name') or "contour"),
            genre=(gamme.CYLINDRIQUE if diametre is not None
                   else gamme.CONIQUE),
            mode="Contour",
            angle=angle, troncature=troncature,
            diametre=diametre if diametre is not None else 2.0,
            profondeur=cls.profondeur_visee(params, 'profondeur'),
            offset_xy=cls._nombre(params, 'offset_xy', 0.0),
            profondeur_passe=cls._nombre(params, 'profondeur_passe',
                                         0.0),
            contour_source=str(params.get('contour_source')
                               or gamme.SOURCES_CONTOUR[0]),
            marge_champ=cls._nombre(params, 'marge_champ', 2.0),
            # le cadre du poste, décalage compris
            cadre_largeur=cadre['cadre_largeur'],
            cadre_hauteur=cadre['cadre_hauteur'],
            cadre_rayon=cadre['cadre_rayon'],
            reprise=bool(params.get('reprise')),
            relief=(str(params.get('mode', 'Creux')) == "Relief"))

    @classmethod
    def _calculer_plan(cls, params: Dict[str, Any],
                       progression=None) -> List[Dict]:
        from src.core import gamme
        contours = cls.contours(params)
        if not contours:
            return []
        # L'offset s'applique dans le tour lui-même (l'outil recule
        # du bord), pas en rognant la zone: sinon il compterait deux
        # fois.
        zone = cls.zone_de_travail(
            params, appliquer_offset=False,
            progression=vcarve.sous_progression(progression, 0.0, 0.5))
        vcarve.avancer(progression, 0.5, "tour du champ")
        if zone is None:
            return []
        forme = vcarve.zone_a_usiner(contours, **cls._cadre(params))
        etapes = gamme.plan_etage(zone, cls._etage(params),
                                  contours, forme)
        precedente = None
        for etape in etapes:
            debut = etape['contours'][0][0] if etape['contours'] \
                else None
            etape['liaison_directe'] = bool(
                precedente is not None and debut is not None
                and vcarve._segment_libre(precedente[0],
                                          precedente[1], debut))
            if etape['contours']:
                precedente = (etape.get('zone'),
                              etape['contours'][-1][-1])
        return etapes

    @classmethod
    def resume(cls, params: Dict[str, Any], calculer: bool = True
               ) -> str:
        plan = cls.plan(params) if calculer \
            else cls.plan_si_connu(params)
        if plan is None:
            return "parcours non calculé"
        if not plan:
            return "aucun parcours"
        profondeurs = sorted({e['profondeur'] for e in plan})
        rayon = plan[0].get('rayon', 0.0)
        return cls._queue_resume(
            params, mesurer=calculer, texte=(
                f"{len(profondeurs)} passe(s) en Z jusqu'à "
                f"{max(profondeurs):g} mm, "
                f"Ø outil {2 * rayon:g} mm"))


def params_outil(op, tool_library) -> Dict[str, Any]:
    """Les paramètres d'une opération, nom de l'outil joint.

    La géométrie d'un outil se lit dans son nom — « Con 30° 0.6 »,
    « Cyl 2 z1L4 ». Le formulaire, l'aperçu du canvas et la
    génération demandent le MÊME parcours: s'ils ne joignent pas
    l'outil de la même façon, ils calculent trois choses
    différentes, ou aucun ne retrouve ce que l'autre a calculé.
    """
    params = dict(getattr(op, 'params', {}) or {})
    if params.get('_tool_name'):
        return params
    outil = None
    identifiant = getattr(op, 'tool_id', '')
    if tool_library is not None and identifiant:
        try:
            outil = tool_library.get_tool(identifiant)
        except Exception:
            outil = None
    if outil is not None:
        params['_tool_name'] = outil.name
        article = getattr(outil, 'article_nr', '')
        if article:
            params.setdefault('_tool_article', article)
        # la fiche de tools.json: Ø, angle de pointe, troncature —
        # lue avant le nom
        fiche = getattr(outil, 'geometry', None)
        if fiche:
            params['_tool_geometrie'] = dict(fiche)
    return params


#: opérations qui savent reprendre le reste d'une autre
TYPES_CHAINABLES = ("gravure_2d5", "evidement_2d5", "contour_2d5",
                    "texte_grave")


def _empreinte_contours(params) -> str:
    """De quoi savoir si deux opérations parlent du MÊME dessin."""
    contours = params.get('contours') or []
    if not contours:
        return ""
    import hashlib
    brut = repr([[(round(float(p[0]), 4), round(float(p[1]), 4))
                  for p in c] for c in contours])
    return hashlib.blake2b(brut.encode('utf-8', 'replace'),
                           digest_size=8).hexdigest()


def chainer(operations, tool_library=None) -> int:
    """Donne à chaque gravure la liste de celles qui la précèdent.

    Deux opérations se chaînent quand elles portent EXACTEMENT les
    mêmes contours: c'est le geste de la gamme — on duplique
    l'opération et on change d'outil. Deux gravures sur deux dessins
    différents ne se marchent pas dessus.

    La bibliothèque d'outils n'est pas décorative: l'amont est
    photographié pour être RECALCULÉ, et sans le nom de son outil il
    le serait avec le cône par défaut. Un tour de fraise
    cylindrique devenait alors un balayage conique qui effaçait les
    lettres de la zone à graver.

    Rend le nombre d'opérations qui reprennent quelque chose.
    """
    chainees = 0
    vues = []          # [(empreinte, {'op_type', 'params', 'nom'})]
    for op in operations or []:
        if op.operation_type not in TYPES_CHAINABLES:
            continue
        if not getattr(op, 'enabled', True):
            continue
        # Une gamme est un ensemble: ses postes se chaînent entre
        # eux, pas avec un parcours libre qui aurait le même dessin
        empreinte = _empreinte_contours(op.params)
        if empreinte:
            empreinte += "@" + str(getattr(op, 'group_id', '') or '')
        amont = [entree for cle, entree in vues if cle == empreinte
                 and empreinte]
        if op.params.get('reprise') and amont:
            op.params['_amont'] = amont
            chainees += 1
        else:
            op.params.pop('_amont', None)
        vues.append((empreinte, {
            'op_type': op.operation_type,
            'params': params_outil(op, tool_library),
            'nom': getattr(op, 'name', '') or op.operation_type,
        }))
    return chainees
