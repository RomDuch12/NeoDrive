# -*- coding: utf-8 -*-
"""La gamme de gravure: plusieurs outils sur le même dessin.

Un logo ne se grave pas avec un seul outil: une cylindrique fait
le tour du contour, des coniques de plus en plus fines reprennent
chacune ce que la précédente n'a pas pu faire, une cylindrique évide.

Cette gamme se DÉPLOIE dans la liste des opérations — un poste par
outil, voir `src/operations/gamme_postes.py`. Ici, la géométrie.

Deux règles gouvernent l'enchaînement:

- chaque outil ne travaille que le RESTE de celui d'avant — le reste
  À SA COTE: ce qu'une conique a gravé à faible profondeur n'est pas
  fait pour la cylindrique qui évide plus bas. C'est ce qui fait la
  différence de temps: la pointe la plus fine, si elle refait tout le
  dessin, passe des heures là où elle n'a rien à reprendre;
- chaque étage porte ses propres décalages. `offset_xy` est la
  matière laissée le long du contour, `offset_z` celle laissée au
  fond: la finition les reprend.

Rien ici ne connaît Qt: la gamme se calcule et se mesure toute seule.
"""

from typing import Dict, List, Optional, Sequence

from src.core import vcarve

#: modes de travail d'un étage
MODES = ("Gravure au V", "Contour", "Évidement")

#: genres d'outil
CONIQUE = "conique"
CYLINDRIQUE = "cylindrique"

#: ce qu'un étage « Contour » fait le tour de. Le CHAMP se
#: contourne par l'extérieur: l'outil dégage le pourtour de la
#: plaque. CHAQUE CONTOUR se longe par l'intérieur de la zone à
#: usiner: en relief, autour des lettres (la zone est le champ moins
#: les lettres); en creux, dans la lettre.
SOURCES_CONTOUR = ("Champ de la gravure", "Chaque contour")

#: profondeur de passe par défaut, en part du diamètre. Une
#: cylindrique de 2 mm descend de 1 mm par passe.
PART_PASSE = 0.5


def etage(nom: str = "", genre: str = CONIQUE, mode: str = MODES[0],
          angle: float = vcarve.ANGLE_DEFAUT,
          troncature: float = vcarve.TRONCATURE_DEFAUT,
          diametre: float = 2.0,
          profondeur: float = 1.0,
          offset_xy: float = 0.0,
          offset_z: float = 0.0,
          pas_radial: float = 0.2,
          recouvrement: float = 40.0,
          profondeur_passe: float = 0.0,
          strategie: str = vcarve.STRATEGIES[0],
          contour_source: str = SOURCES_CONTOUR[0],
          marge_champ: float = 2.0,
          cadre_largeur: float = 0.0, cadre_hauteur: float = 0.0,
          cadre_rayon: float = 0.0,
          reprise: bool = True, relief: bool = False) -> Dict:
    """Un étage de la gamme, avec ses valeurs par défaut."""
    return {'nom': nom, 'genre': genre, 'mode': mode, 'relief': bool(relief),
            'angle': float(angle), 'troncature': float(troncature),
            'diametre': float(diametre),
            'profondeur': float(profondeur),
            'offset_xy': float(offset_xy),
            'offset_z': float(offset_z),
            'pas_radial': float(pas_radial),
            'recouvrement': float(recouvrement),
            'profondeur_passe': float(profondeur_passe),
            'strategie': strategie,
            'contour_source': contour_source,
            'marge_champ': float(marge_champ),
            'cadre_largeur': float(cadre_largeur),
            'cadre_hauteur': float(cadre_hauteur),
            'cadre_rayon': float(cadre_rayon),
            'reprise': bool(reprise)}


def rayon_outil(etg: Dict, z: float = 0.0) -> float:
    """Rayon de l'outil de cet étage à la profondeur `z`.

    Une cylindrique a le même rayon partout: c'est ce qui la rend
    capable d'évider, et incapable de suivre un angle rentrant plus
    fin que son diamètre."""
    if etg.get('genre') == CYLINDRIQUE:
        return max(1e-6, float(etg.get('diametre', 2.0)) / 2.0)
    return vcarve.rayon_a_profondeur(
        max(0.0, z), float(etg.get('angle', vcarve.ANGLE_DEFAUT)),
        float(etg.get('troncature', vcarve.TRONCATURE_DEFAUT)))


def profondeur_visee(etg: Dict) -> float:
    """Cote de cet étage, la matière laissée au fond déduite."""
    return max(0.0, float(etg.get('profondeur', 0.0))
               - float(etg.get('offset_z', 0.0)))


def cible(forme, restant, etg: Dict):
    """La zone que CET étage doit travailler.

    En reprise, c'est ce que les précédents ont laissé; sinon toute
    la zone. Dans les deux cas, `offset_xy` de matière reste le long
    du contour: l'outil ne va pas jusqu'au trait."""
    zone = restant if etg.get('reprise', True) else forme
    if zone is None or zone.is_empty:
        return None
    marge = float(etg.get('offset_xy', 0.0) or 0.0)
    # Un étage « Contour » recule lui-même l'outil de la matière
    # laissée: rogner la zone en plus la compterait deux fois.
    if str(etg.get('mode') or MODES[0]) == "Contour":
        marge = 0.0
    if abs(marge) > 1e-9:
        zone = zone.buffer(-marge, quad_segs=vcarve.QUADRANTS,
                           join_style=1)
        if zone.is_empty:
            return None
    return zone


def paliers(profondeur: float, profondeur_passe: float, rayon: float
            ) -> List[float]:
    """Les cotes successives, jusqu'à la profondeur. Sans passe
    donnée: la moitié du diamètre."""
    pas = float(profondeur_passe or 0.0)
    if pas <= 0:
        pas = max(0.05, 2.0 * rayon * PART_PASSE)
    cotes = []
    z = min(pas, profondeur)
    while True:
        cotes.append(round(float(z), 4))
        if z >= profondeur - 1e-9:
            break
        z = min(z + pas, profondeur)
    return cotes


def passes_contour(zone, rayon: float, profondeur: float,
                   profondeur_passe: float = 0.0,
                   anneaux=None) -> List[Dict]:
    """Le tour de chaque contour, en descendant par passes — CONTOUR
    PAR CONTOUR: l'outil descend jusqu'à la cote sur un tour avant de
    passer au suivant, et ne remonte au dégagement qu'entre deux
    tours. (Passe par passe, la cylindrique remontait entre chaque
    lettre à chaque cran: six fois plus de dégagements.)

    C'est le passage qui prépare la gravure: la cylindrique dégage le
    pourtour à la cote, et les coniques n'ont plus qu'à faire le
    détail. L'outil suit le bord de la zone (`anneaux`: ceux qu'on
    lui donne, sinon les bords de la zone); le rayon a déjà été
    retiré par l'appelant.
    """
    if zone is None or zone.is_empty or profondeur <= 0:
        return []
    anneaux = list(anneaux) if anneaux is not None \
        else vcarve._anneaux(zone)
    anneaux = [a for a in anneaux if len(a) >= 2]
    if not anneaux:
        return []
    cotes = paliers(profondeur, profondeur_passe, rayon)
    passes = []
    for anneau in anneaux:
        for numero, z in enumerate(cotes):
            # 'zone': None — d'un tour à l'autre l'outil dégage; sur
            # le même tour, il replonge sur place (mêmes points)
            passes.append({'role': ('finition' if numero == len(cotes) - 1
                                    else 'ebauche'),
                           'type': 'anneau', 'profondeur': z,
                           'contours': [anneau], 'rayon': rayon,
                           'zone': None, 'palier': numero})
    return passes


def champ(forme, marge: float = 2.0, largeur: float = 0.0,
          hauteur: float = 0.0, rayon: float = 0.0):
    """Le rectangle qui contient la gravure, avec sa marge.

    C'est lui que la cylindrique contourne quand l'étage « Contour »
    fait le tour du champ: elle en dégage le pourtour à la cote, par
    l'extérieur. (Le tour de chaque contour, lui, se fait dans la
    zone à usiner — voir `plan_etage`.)"""
    return vcarve.cadre(forme, marge, largeur, hauteur, rayon)


def plan_etage(zone, etg: Dict, contours, forme=None,
               progression=None) -> List[Dict]:
    """Le parcours d'un seul étage, sur la zone qu'on lui donne.

    Publique: l'opération « Contour » de la liste s'en sert pour un
    étage seul, sans passer par toute la gamme."""
    if zone is None or zone.is_empty:
        return []
    profondeur = profondeur_visee(etg)
    if profondeur <= 0:
        return []
    mode = str(etg.get('mode') or MODES[0])
    genre = etg.get('genre', CONIQUE)
    rayon = rayon_outil(etg, profondeur)

    if mode == "Contour":
        source = str(etg.get('contour_source') or SOURCES_CONTOUR[0])
        # la matière qu'on laisse sur la paroi: l'outil recule
        # d'autant
        marge = max(0.0, float(etg.get('offset_xy', 0.0) or 0.0))
        anneaux = None
        if source == SOURCES_CONTOUR[0]:
            base = champ(forme if forme is not None else zone,
                         float(etg.get('marge_champ', 2.0)),
                         float(etg.get('cadre_largeur', 0.0) or 0.0),
                         float(etg.get('cadre_hauteur', 0.0) or 0.0),
                         float(etg.get('cadre_rayon', 0.0) or 0.0))
            if base is None or base.is_empty:
                return []
            # L'outil tourne AUTOUR du champ: son centre est dehors,
            # à un rayon du bord plus la matière laissée.
            trajet = base.buffer(rayon + marge,
                                 quad_segs=vcarve.QUADRANTS,
                                 join_style=1)
        else:
            # Le tour de chaque contour se fait DANS la zone à
            # usiner, l'outil à un rayon plus la matière laissée du
            # bord. En relief la zone est le champ moins les
            # lettres: le tour longe chaque lettre par l'extérieur
            # et le champ par l'intérieur, sans jamais entrer dans
            # une lettre. (Dilatée vers l'extérieur, la zone
            # rétrécissait ses trous — les lettres — et la
            # cylindrique taillait dans les pleins des « O ».) En creux, c'est
            # le tour intérieur de la lettre: une fraise de 2 mm
            # n'y trouve pas de place dans un trait fin, et c'est
            # ce qu'on veut.
            trajet = vcarve.eroder(zone, rayon + marge)
            if trajet is None or trajet.is_empty:
                return []
            if etg.get('relief'):
                # En relief, le tour de CHAQUE LETTRE et rien d'autre:
                # le bord de la zone érodée comprend aussi le tour
                # intérieur du cadre englobant, que la cylindrique faisait
                # pour rien (l'évidement le refait). On tourne autour
                # des lettres, à un rayon plus la matière laissée, et
                # on ne garde que ce qui reste dans la zone atteignable
                # — près du cadre ou entre deux lettres serrées, le
                # tour se coupe plutôt que d'entrer dans une lettre.
                dessin = vcarve.zone(contours)
                if dessin is not None and not dessin.is_empty:
                    autour = dessin.buffer(rayon + marge,
                                           quad_segs=vcarve.QUADRANTS,
                                           join_style=1)
                    anneaux = vcarve.decouper(vcarve._anneaux(autour),
                                              trajet,
                                              vcarve.TOLERANCE_LIAISON)
                    if not anneaux:
                        return []
        return passes_contour(trajet, rayon, profondeur,
                              etg.get('profondeur_passe', 0.0),
                              anneaux=anneaux)

    if mode == "Évidement" or genre == CYLINDRIQUE:
        # Une cylindrique ne sait pas graver au V: elle vide.
        passes = []
        pas_z = float(etg.get('profondeur_passe') or 0.0)
        if pas_z <= 0:
            pas_z = max(0.05, 2.0 * rayon * PART_PASSE)
        z = min(pas_z, profondeur)
        while True:
            vcarve.avancer(progression, min(1.0, z / profondeur),
                           f"palier {z:g} mm")
            for passe in vcarve.passes_evidement(
                    contours, profondeur=z,
                    angle=(0.1 if genre == CYLINDRIQUE
                           else float(etg.get('angle', 30.0))),
                    troncature=(2.0 * rayon if genre == CYLINDRIQUE
                                else float(etg.get('troncature',
                                                   0.2))),
                    recouvrement=float(etg.get('recouvrement', 40.0)),
                    forme=zone):
                passe['role'] = 'ebauche'
                passe['type'] = 'anneau'
                passe['rayon'] = rayon
                passes.append(passe)
            if z >= profondeur - 1e-9:
                break
            z = min(z + pas_z, profondeur)
        return passes

    # Gravure au V: le calcul de vcarve, sur la zone donnée
    return vcarve.plan_gravure(
        contours, angle=float(etg.get('angle', 30.0)),
        troncature=float(etg.get('troncature', 0.2)),
        profondeur_max=profondeur,
        pas_radial=float(etg.get('pas_radial', 0.2)),
        strategie=str(etg.get('strategie', vcarve.STRATEGIES[0])),
        forme=zone, progression=progression)


def plan_gamme(contours: Sequence, etages: Sequence[Dict],
               relief: bool = False, cadre_marge: float = 2.0,
               decalage: float = 0.0, progression=None) -> List[Dict]:
    """La gamme entière, étage par étage.

    Rend une liste de dictionnaires, un par étage:
      {'etage', 'nom', 'plan', 'couverture', 'reste_mm2', 'zone_mm2'}

    `couverture` est mesurée sur la zone TOTALE: c'est la part du
    dessin que cet outil a enlevée. Le dernier `reste_mm2` dit ce
    qu'aucun outil de la gamme n'a pu atteindre — le chiffre à
    regarder avant de lancer la machine.
    """
    forme = vcarve.zone_a_usiner(contours, relief=relief,
                                 cadre_marge=cadre_marge,
                                 decalage=decalage)
    if forme is None:
        return []
    from src.core.matiere import EtatMatiere
    resultats = []
    # L'état de la matière retient la cote ATTEINTE région par région:
    # un étage ne reprend que ce qui n'est pas déjà descendu à SA cote
    # (le suivi à plat disait « rien à reprendre » sur des gradins).
    etat = EtatMatiere(forme)
    for index, etg in enumerate(etages):
        visee = profondeur_visee(etg)
        restant = etat.zone_a_reprendre(visee)
        zone = cible(forme, restant, etg)
        tranche = vcarve.sous_progression(
            progression, index / len(etages),
            (index + 1) / len(etages),
            f"{etg.get('nom') or 'étage ' + str(index + 1)} — ")
        plan = plan_etage(zone, dict(etg, relief=etg.get('relief', relief)),
                          contours, forme, tranche) \
            if zone is not None else []
        balaye = vcarve.balayage(
            plan, float(etg.get('angle', 30.0)),
            float(etg.get('troncature', 0.2))) if plan else None
        if balaye is not None:
            dedans = balaye.intersection(forme)
            enleve = dedans.area
            etat.enlever(dedans, visee)
        else:
            enleve = 0.0
        resultats.append({
            'etage': index,
            'nom': etg.get('nom') or f"étage {index + 1}",
            'plan': plan,
            'couverture': enleve / forme.area if forme.area else 0.0,
            # ce qui n'est pas encore à LA COTE DE CET ÉTAGE
            'reste_mm2': etat.reste_surface(visee),
            'reste_mm3': etat.reste_volume(visee),
            'zone_mm2': forme.area,
        })
    # Le reste FINAL se juge à la cote la plus profonde de la gamme
    cote_finale = max([profondeur_visee(e) for e in etages] or [0.0])
    for res in resultats:
        res['cote_finale'] = cote_finale
    if resultats:
        resultats[-1]['reste_mm2'] = etat.reste_surface(cote_finale)
        resultats[-1]['reste_mm3'] = etat.reste_volume(cote_finale)
    return resultats


def _vide():
    """Une géométrie vide, pour continuer la boucle sans cas
    particulier."""
    geo, _ops = vcarve._shapely()
    return geo.Polygon()


def resume_gamme(resultats: Sequence[Dict]) -> str:
    """Une ligne par étage, lisible dans un journal ou un test.

    Le « reste » est ce qui n'est pas encore à la cote de l'étage —
    sa profondeur comprise, pas seulement son empreinte."""
    lignes = []
    for res in resultats:
        ligne = ("%-22s %4d étapes  couvre %5.1f %%  reste %6.2f mm²"
                 % (res['nom'], len(res['plan']),
                    100.0 * res['couverture'], res['reste_mm2']))
        volume = res.get('reste_mm3')
        if volume:
            ligne += " (%.2f mm³)" % volume
        lignes.append(ligne)
    return "\n".join(lignes)


def reste_final(resultats: Sequence[Dict]) -> Optional[float]:
    """Ce qu'aucun outil de la gamme n'amène à la cote, en mm²."""
    return resultats[-1]['reste_mm2'] if resultats else None


def reste_final_volume(resultats: Sequence[Dict]) -> Optional[float]:
    """La matière qu'aucun outil n'enlève, en mm³ — la vraie mesure
    sur une pièce à gradins: une surface « finie » peut cacher des
    millimètres de matière sous elle."""
    return resultats[-1].get('reste_mm3') if resultats else None
