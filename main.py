"""
NeoDrive - Générateur de programmes SimPl pour machines CNC DATRON
Point d'entrée de l'application.
"""

import sys
import io
import os

#: ressources sans lesquelles l'application démarre en silence avec
#: des valeurs par défaut (bibliothèque d'outils vide, pas d'icône)
# les ressources génériques embarquées dans l'exe (restaurées si data/
# manque); les outils (tools.json) sont des données de l'atelier: la
# version libre démarre avec la bibliothèque par défaut (round 32). Le
# catalogue DATRON n'est pas livré: l'onglet Catalogue le constitue
# depuis le webshop (round 33)
DATA_REQUIS = (
    "default_params.json", "materials.json",
    "shortcuts.json", "neodrive.ico", "NeoDriveLoad.png",
    "NeoDrive.png",
)


def restaurer_data(base_dir: str) -> list:
    """Complète data/ depuis la copie embarquée dans l'exe.

    L'application lit data/ À CÔTÉ de l'exe. Si l'exe voyage seul, ce
    dossier est vide et NeoDrive démarrait sans outils sans rien dire:
    on y remet ce que PyInstaller a embarqué (_MEIPASS).
    """
    embarque = getattr(sys, '_MEIPASS', '')
    if not embarque:
        return []
    source_dir = os.path.join(embarque, "data")
    cible_dir = os.path.join(base_dir, "data")
    restaures = []
    for nom in DATA_REQUIS:
        cible = os.path.join(cible_dir, nom)
        source = os.path.join(source_dir, nom)
        if os.path.isfile(cible) or not os.path.isfile(source):
            continue
        try:
            import shutil
            shutil.copy2(source, cible)
            restaures.append(nom)
        except OSError:
            pass
    return restaures


def fichiers_en_argument(arguments) -> list:
    """Les fichiers à ouvrir parmi les arguments de la ligne de
    commande — ce que l'Explorateur passe avec « Ouvrir avec »."""
    return [a for a in arguments
            if a and not a.startswith('-') and os.path.isfile(a)]


# ce qui voyage à côté de l'exe pour la licence (vérifié par
# l'autocontrôle de l'exe): NeoDrive (MIT ou Apache-2.0), le code repris,
# les licences de ce que l'exe embarque (tools/licences_tierces.py)
LICENCES_A_COTE = ('LICENSE.txt', 'LICENSE-MIT.txt', 'LICENSE-APACHE.txt',
                   'THIRD_PARTY_NOTICES.md',
                   os.path.join('licences', 'LISEZ-MOI.txt'))


def verifier_licences(base: str) -> None:
    """Les licences voyagent avec l'exe (dossier `base`): sinon
    AssertionError — l'autocontrôle échoue, rien n'est publié."""
    absentes = [n for n in LICENCES_A_COTE
                if not os.path.isfile(os.path.join(base, n))]
    assert not absentes, f"licences absentes: {absentes}"
    with open(os.path.join(base, 'licences', 'LISEZ-MOI.txt'),
              encoding='utf-8') as f:
        lisez = f.read()
    assert 'À COMPLÉTER' not in lisez, \
        "licences du code embarqué à compléter (licences/LISEZ-MOI.txt)"


def autocontrole() -> int:
    """Vérifie que l'exe SAIT FAIRE, pas seulement démarrer.

    Un exe qui s'ouvre ne prouve rien: scipy ne s'importe qu'au
    premier axe médian, pypdf qu'au premier PDF. Un module oublié
    dans neodrive.spec ne se voyait alors qu'à l'atelier, au moment
    de graver. `NeoDrive.exe --autocontrole` fait le chemin complet
    en une seconde, sans ouvrir de fenêtre.
    """
    import math
    import traceback
    etapes = []
    try:
        from src.core import vcarve
        etoile = [[(20.0 * math.cos(math.pi / 2 + i * math.pi / 5)
                    if i % 2 == 0 else
                    8.0 * math.cos(math.pi / 2 + i * math.pi / 5),
                    20.0 * math.sin(math.pi / 2 + i * math.pi / 5)
                    if i % 2 == 0 else
                    8.0 * math.sin(math.pi / 2 + i * math.pi / 5))
                   for i in range(10)]]
        forme = vcarve.zone(etoile)               # shapely
        assert forme is not None and forme.area > 100
        etapes.append("shapely")
        chaines = vcarve.axe_median(forme, pas=1.0, marge=0.2)
        assert chaines, "axe médian vide"
        etapes.append("scipy")
        plan = vcarve.plan_gravure(etoile, 30, 0.2, profondeur_max=0.4,
                                   pas_radial=0.25, pas_median=1.0)
        assert plan, "plan de gravure vide"
        etapes.append("gravure")

        from src.core import gamme
        suite = gamme.plan_gamme(
            etoile, [gamme.etage("0,6", troncature=0.6,
                                 profondeur=0.4, reprise=False),
                     gamme.etage("0,2", troncature=0.2,
                                 profondeur=0.4)])
        assert len(suite) == 2 and suite[0]['plan'], "gamme vide"
        etapes.append("gamme")

        import src.operations                     # noqa: F401
        from src.codegen.generator import SimPlGenerator
        from src.core.program_model import (
            ProgramModel, OperationInstance)
        from src.core.tool_library import ToolLibrary
        outils = ToolLibrary()
        outils.load()
        prog = ProgramModel()
        op = OperationInstance("percage_foret", "Autocontrole")
        op.tool_id = next(iter(outils.tools), None)
        op.points = [{'x': 0.0, 'y': 0.0, 'depth': 2.0}]
        prog.add_operation(op)
        code = SimPlGenerator(prog, outils).generate()
        assert "export program Main" in code
        etapes.append(f"SimPl ({len(outils.tools)} outils)")

        # la gamme: un ensemble, un poste par outil de la
        # bibliothèque, un sous-programme par poste. Ses outils sont
        # ceux de l'autocontrôle (nommés comme les postes, dans un
        # fichier à part): il éprouve l'exe, pas la bibliothèque de
        # l'atelier — la version libre n'a que celle par défaut. La
        # gamme est celle de base: celles d'un atelier sont des
        # données (data/gammes_atelier.json), relues plus bas
        import json as _json
        import tempfile as _tf_outils
        from src.operations import gamme_postes
        _noms = sorted({p['outil'] for p in gamme_postes.POSTES_BASE
                        if p.get('outil')})
        _fichier = os.path.join(_tf_outils.mkdtemp(prefix="nd_auto_"),
                                "tools.json")
        with open(_fichier, "w", encoding="utf-8") as _f:
            _json.dump({'tools': {
                f"autocontrole_{i}": {
                    'name': nom, 'rpm': 24000, 'feed_finishing': 600,
                    'feed_approach': 800, 'feed_plunge': 300,
                    'feed_ramp': 300, 'feed_roughing': 600}
                for i, nom in enumerate(_noms)}}, _f)
        outils = ToolLibrary(_fichier)
        tete, membres = gamme_postes.creer_gamme(
            {'contours': etoile, 'mode': 'Relief', 'cadre_marge': 12.0,
             'pas_radial': 0.25, 'pas_median': 1.0}, outils)
        assert len(membres) == len(gamme_postes.POSTES_BASE), \
            "gamme sans postes"
        matrice = ProgramModel()
        for op in [tete] + membres:
            if op.operation_type == "gravure_2d5":
                op.params.update({'profondeur_max': 0.4,
                                  'pas_radial': 0.25, 'pas_median': 1.0})
            matrice.add_operation(op)
        code = SimPlGenerator(matrice, outils, calculer=True).generate()
        programmes = code.count("BeginBlock name=")
        assert programmes >= 2, f"{programmes} sous-programme(s)"
        # les gammes livrées: la base, et celles de l'atelier si ses
        # données sont à côté de l'exe (illisibles: l'exe le dit ici)
        from src.operations import gamme_modeles as _gm
        _livres = _gm.livres()
        for _nom in _livres:
            assert _gm.postes_du(_nom), f"gamme « {_nom} » sans postes"
        etapes.append(f"gamme ({programmes} outils, {len(_livres)} "
                      "modèle(s) livré(s))")

        # l'instance unique passe par QtNetwork: un module Qt de plus
        # à embarquer, qui ne se voit qu'au second lancement
        from PySide6.QtNetwork import QLocalServer  # noqa: F401
        from src.integrations import instance_unique
        assert instance_unique.nom_du_serveur().startswith("NeoDrive-")
        # le verrou d'instance (mutex Windows, par ctypes): deux
        # lancements simultanés n'ouvrent qu'une instance
        _nom_verrou = f"NeoDrive-autocontrole-{os.getpid()}"
        assert instance_unique.prendre_le_verrou(_nom_verrou) in (
            True, None), "verrou d'instance"
        instance_unique.lacher_le_verrou(_nom_verrou)
        etapes.append("instance unique (verrou)")
        # le texte vectorisé: les polices du poste
        from src.core import texte as noyau_texte
        lettres = noyau_texte.contours_du_texte("H", hauteur=5.0)
        assert lettres, "texte sans contour"
        etapes.append(f"texte ({len(noyau_texte.polices())} polices)")

        from src.io.vecteur import dxfimport      # noqa: F401
        etapes.append("ezdxf")
        from src.io.vecteur import textvec        # noqa: F401
        etapes.append("polices")
        # le lecteur STEP (pièces 3D): unités et entités d'un STEP
        # minimal — s'il manquait dans l'exe, on le saurait ici
        from src.io.vecteur import stepread
        modele = stepread._Modele(stepread.lire_entites(
            "ISO-10303-21;\nDATA;\n"
            "#1=( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) );\n"
            "#2=CARTESIAN_POINT('',(1.,2.,3.));\nENDSEC;\n"))
        assert modele.unite() == 1.0 and modele.point(2) == (1.0, 2.0, 3.0)
        etapes.append("STEP")
        # la pièce en volume: une face maillée (shapely, triangulation
        # contrainte) — et le 2D d'un assemblage passe par là aussi
        from src.io.vecteur import step3d
        m3d = step3d.lire_modele(
            "ISO-10303-21;\nDATA;\n"
            "#1=( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) );\n"
            "#2=COORDINATES_LIST('',3,((0.,0.,0.),(10.,0.,0.),(0.,10.,0.)));\n"
            "#3=TRIANGULATED_FACE('',#2,3,(),$,(),((1,2,3)));\n"
            "ENDSEC;\n")
        assert abs(m3d.aire() - 50.0) < 1e-6, "STEP 3D"
        from shapely.geometry import Polygon as _Poly
        import shapely as _shapely
        assert len(_shapely.constrained_delaunay_triangles(
            _Poly([(0, 0), (4, 0), (4, 4), (0, 4)])).geoms) == 2
        etapes.append("STEP 3D")
        # le catalogue DATRON n'est pas livré: il se constitue depuis
        # le webshop. La lecture d'une fiche, éprouvée sur une fiche
        # écrite ici (pas de réseau), puis les avances qu'il en tire
        # (modèle, ou guide lu)
        import tempfile as _tf_cat
        from src.core import catalogue_datron, coupe_datron
        from src.core import constitution_datron
        _ligne = ('<tr><th class="properties-label">{}:</th>'
                  '<td class="properties-value">{}</td></tr>')
        _page = ("<table>" + "".join(_ligne.format(k, v) for k, v in (
            ("D1", "3"), ("D2", "6"), ("L1", "40"), ("L2", "5"),
            ("Z", "1"))) + "</table>"
            '<script type="application/ld+json">[{"@type": "Product", '
            '"name": "Einschneider 0068030E", "offers": [{"@type": '
            '"AggregateOffer", "highPrice": 38.5}]}]</script>')
        _x = constitution_datron.entree(
            _page, "0068030E", "schaftfraeser/einschneider/standard")
        assert _x and _x["D1"] == 3 and _x["prix_eur"] == 38.5, _x
        _fichier_cat = os.path.join(_tf_cat.mkdtemp(prefix="nd_cat_"),
                                    "catalogue_datron.json")
        with open(_fichier_cat, "w", encoding="utf-8") as _f:
            _json.dump({"outils": [_x]}, _f)
        cat = catalogue_datron.Catalogue(_fichier_cat)
        assert not cat.erreur, cat.erreur
        av = cat.avances(cat.entree("0068030E"),
                         guide=coupe_datron.guide())
        assert av and av["rpm"] > 0, "pas d'avances DATRON"
        etapes.append(f"catalogue (constitution éprouvée, "
                      f"{len(catalogue_datron.Catalogue())} réf. sur ce "
                      f"poste, guide {coupe_datron.guide().nb_refs()} "
                      "réf.)")
        # les fonctions du manuel SimPL: l'exe les connaît, l'éditeur
        # a ses commandes
        from src.core.simpl_commandes import COMMANDES
        from src.operations.registry import OperationRegistry
        for genre in ("poche_cercle", "rotation_repere", "palpage_coin",
                      "message_operateur", "mesure_outil"):
            OperationRegistry.get(genre)
        assert "CircleCavity" in OperationRegistry.get(
            "poche_cercle").generate_operation_code({})
        etapes.append(f"SimPL ({len(COMMANDES)} commandes)")
        # la simulation des cycles en 3D (onglet STEP 3D)
        from src.core import sim_cycles
        res = sim_cycles.simuler(
            "export program Main\n    SafeRapid X=0 Y=0 Z=16\n"
            "    CircleCavity (diameter=10 depth=2 infeedZ=1)\n"
            "endprogram", {})
        assert res['cycles'] == {'CircleCavity': 1}, res['cycles']
        assert abs(min(res['z']) + 2.0) < 1e-9, "fond de poche faux"
        # la matière: le brut creusé à la cote du fond
        from src.core import enlevement
        brut = enlevement.Brut.autour(res)
        brut.appliquer(res, {})
        assert abs(brut.hauteur_en(0.0, 0.0) + 2.0) < 1e-6, "matière"
        # la gravure de texte, à trait simple
        texte = sim_cycles.simuler(
            "export program Main\n    SafeRapid X=0 Y=0 Z=16\n"
            '    Engrave::StandardTextEngrave (text="NEO" charHeight=2 '
            "depth=0.1 Center)\nendprogram", {})
        assert min(texte['z']) < -0.09, "gravure de texte"
        etapes.append("cycles 3D, matière, texte")
        # le moteur d'usinage 3D: une poche dans une plaque, calculée et
        # contrôlée (scipy.ndimage, contourpy, shapely embarqués)
        import numpy as np
        from src.core import usinage3d

        class _Plaque:
            faces = []

            def __init__(self):
                xs = np.linspace(0, 20, 41)
                X, Y = np.meshgrid(xs, xs)
                Z = np.where((abs(X - 10) < 5) & (abs(Y - 10) < 5), -2.0, 0.0)
                P = np.stack([X, Y, Z], axis=-1)
                a, b = P[:-1, :-1].reshape(-1, 3), P[:-1, 1:].reshape(-1, 3)
                c, d = P[1:, 1:].reshape(-1, 3), P[1:, :-1].reshape(-1, 3)
                self.triangles = np.concatenate(
                    [np.stack([a, b, c], 1), np.stack([a, c, d], 1)])

        etape = usinage3d.etape("Ébauche", "x", {'forme': 'plate',
                                                 'rayon': 1.0},
                                'ebauche', 'niveaux', 0.0, 1.0, 0.8)
        res3d = usinage3d.calculer(_Plaque(), (0.0, 0.0, 0.0, -3.0),
                                   [etape], pas=0.1)
        assert res3d['controle']['entailles'] == 0, "usinage 3D: entaille"
        assert "$$$ USINAGE3D_1_EBAUCHE" in res3d['etapes'][0]['code']
        etapes.append("usinage 3D")
        # le Tracé compensé, le dessin joint en STL, les phases de
        # bridage (lancer de rayons), le mini formulaire
        from src.operations.trace import Trace
        chemin = Trace.chemins(
            {'shape': 'Dessin', 'closed': True,
             'path_points': [[0, 0], [20, 0], [20, 20], [0, 20]],
             'cote_outil': "Intérieur (découpe intérieure)",
             'surepaisseur_xy': 0.0, '_diametre_outil': 6.0},
            0.0, 0.0, [])
        assert abs(min(p[0] for p in chemin[0]) - 3.0) < 0.01, "tracé"
        import tempfile
        from src.io import stl
        plaque = _Plaque().triangles
        f_stl = os.path.join(tempfile.mkdtemp(prefix="neodrive_ac_"),
                             "autocontrole.stl")
        stl.ecrire_stl(f_stl, plaque[:4], "autocontrole")
        assert stl.lire_stl(f_stl).shape == (4, 3, 3), "STL"
        libre = usinage3d.rayons_libres(plaque, [[10.0, 10.0, -1.0]],
                                        [0.0, 0.0, 1.0])
        assert bool(libre[0]), "phases: rayon"
        from src.gui.dialogs import mini_formulaire  # noqa: F401
        etapes.append("tracé compensé, STL, phases")
        # la tenue de la pièce: l'ordre des phases, le palpage d'une
        # reprise, les plaques (motifs, contour), l'éditeur et la scène
        from src.core import tenue, plaques, scene_phases  # noqa: F401
        from src.gui.dialogs import plaques_dialog  # noqa: F401
        from src.operations import depuis_selection  # noqa: F401
        ordre, _perdues = tenue.phases_du_mode(
            {'phases': [{'cle': 'Z+', 'libelle': 'dessus', 'faces': []}]},
            'etau', tenue.brut_defaut())
        assert [p['cle'] for p in ordre] == ['Z+', 'Z-'], "tenue"
        assert tenue.op_palpage('rectangle', 60, 40, 2, "P")[
            'operation_type'] == 'palpage_rectangle'
        assert len(plaques.motif(3, 2, 20, 20)) == 6
        assert usinage3d.zones_raides(np.zeros((4, 4)), usinage3d.Grille(
            0, 4, 0, 4, pas=1.0), -1.0).shape == (4, 4)
        etapes.append("tenue, plaques, Z constant")
        # les petites hélices (filets) découpées à leur rayon, la
        # fraise en T qui ne coupe que son disque
        assert sim_cycles._n_tour(0.8) < 24, "hélices"
        brut_t = enlevement.Brut(-10, 10, -10, 10, -5, 0.0, pas=0.5)
        brut_t.enlever(-8, 0, -3, 8, 0, -3,
                       {'forme': 'tslot', 'rayon': 4.0, 'hauteur': 1.3})
        assert brut_t.hauteur_en(0, 0) == 0.0, "fraise en T"
        etapes.append("filets, fraise en T")
        # le dessin d'un outil: son profil, le STEP relu, le DXF coté
        from src.core import dessin_outil
        from src.gui.dialogs import fiche_outil  # noqa: F401
        from src.gui.dxf import barre_imports  # noqa: F401
        from src.io.vecteur import step3d
        import ezdxf
        cotes = {'famille': 'tslot', 'libelle': '', 'source': '',
                 'D1': 8.0, 'D2': 6.0, 'D3': 0.0, 'L1': 50.0, 'L2': 0.0,
                 'L3': 6.0, 'angle': 0.0, 'R': 0.0, 'pointe': 0.0,
                 'dents': 4, 'pas': 0.0, 'hauteur': 1.3}
        pr = dessin_outil.profil(cotes)
        d_outil = tempfile.mkdtemp(prefix="neodrive_ac_outil_")
        f_step = dessin_outil.ecrire_step(
            os.path.join(d_outil, "outil.step"), pr['points'], "T-slot 8",
            pr['z_coupe'])
        assert len(step3d.lire_modele(f_step).faces) >= 6, "STEP outil"
        f_dxf = dessin_outil.ecrire_dxf(
            os.path.join(d_outil, "outil.dxf"), pr['points'], cotes,
            "T-slot 8", pr['z_coupe'])
        assert len(ezdxf.readfile(f_dxf).modelspace().query(
            'DIMENSION')) >= 3, "DXF outil"
        etapes.append("dessin d'outil STEP + DXF")
        # les photos du webshop DATRON: https (ssl et ses certificats) et
        # la lecture des pages — sans réseau: l'atelier peut être hors
        # ligne
        import ssl
        from src.core import images_datron, fiches_outils
        ssl.create_default_context()
        assert len(images_datron.urls_images(
            'https://webshop.datron.de/media/a/1/0068808L_2.png '
            'https://webshop.datron.de/media/b/2/0068808L_1.png',
            '0068808L')) == 2, "images DATRON"
        assert fiches_outils.cle(ref="0068443G / 114206") == "0068443G"
        etapes.append("photos DATRON (https), fiches")
        # étaux et mandrins, la machine et les collisions, la fraise en T,
        # le repère local, les fenêtres d'onglets, le miroir des filets
        from src.core import serrages, machine, collisions, usinage_tslot
        from src.core import miroirs_filets  # noqa: F401
        from src.gui import fenetres  # noqa: F401
        from src.gui.dialogs import serrages_dialog, machine_dialog  # noqa
        from src.gui.dialogs import vis_dialog  # noqa: F401
        from src.operations.registry import OperationRegistry
        tri_etau, _c = serrages.triangles(serrages.nouvel_etau(), 60.0)
        assert len(tri_etau) == 36, "étau"
        assert len(machine.pile_broche(machine.defaut())) == 3, "broche"
        assert collisions.resume({'evenements': [], 'sommets': 0})
        assert usinage_tslot.section(np.zeros((0, 3, 3)), 0.0).is_empty
        assert "ShiftLcsInc" in OperationRegistry.get(
            "repere_local").generate_operation_code({'shift_x': 1})
        assert "EdgeMeasureV2" in OperationRegistry.get(
            "palpage_arete").generate_operation_code({})
        etapes.append("étaux, machine, collisions, fraise en T, repère "
                      "local")
        # VectorCraft / CADCraft (MIT): image vectorisée, retouches,
        # accrochages — scipy.ndimage, contourpy et shapely dans l'exe
        from src.io.vecteur import trace_image
        from src.core import retouche, accrochage
        from src.gui.dialogs import trace_image_dialog  # noqa: F401
        gris = np.full((60, 80), 255.0, np.float32)
        gris[20:40, 10:30] = 0.0                  # un pavé
        gris[29:32, 40:75] = 0.0                  # un trait de 3 px
        tr = trace_image.tracer(gris, trace_image.Reglages(
            mode='les_deux', largeur_mm=8.0, largeur_trait_mm=0.5))
        assert (len(tr.contours), len(tr.traits)) == (1, 1), "tracé"
        bouts, _b = retouche.nettoyer([[(0, 0), (5, 0)], [(5, 0), (5, 5)],
                                       [(5, 5), (0, 0)], [(5, 0), (0, 0)]])
        assert len(bouts) == 1 and retouche.est_fermee(bouts[0]), "nettoyer"
        assert accrochage.accrocher((0.2, 0.1), bouts).mode == 'extremite'
        etapes.append("image vectorisée, retouches, accrochages")
        # la suite: arcs retrouvés, police à trait simple complète,
        # forme Texte du Tracé, métafichiers EMF / WMF
        import struct as _st
        from src.core import arcs, police_fil
        from src.io.vecteur import metafile
        from src.operations.trace import Trace
        cercle = [(5 * np.cos(a), 5 * np.sin(a))
                  for a in np.linspace(0, 2 * np.pi, 61)]
        assert arcs.compte(arcs.ajuster(cercle, 0.005)) == (0, 2), "arcs"
        assert police_fil.glyphe('g') and police_fil.glyphe('é'), "police"
        assert "Arc CCW" in Trace.build_sequence_block(
            {'shape': 'Cercle', 'diameter': 10, 'depth': 0.2,
             'infeed_z': 0.2, 'arcs': True}), "Tracé en arcs"
        assert Trace.chemins({'shape': 'Texte', 'texte_fil': 'ab'}), \
            "Tracé texte"
        enr = (_st.pack('<II4iI', 87, 36, 0, 0, 0, 0, 2)
               + _st.pack('<4h', 0, 0, 100, 0))
        emf = (_st.pack('<II4i4iIIIIHHIII2i2i', 1, 88, 0, 0, 0, 0, 0, 0,
                        100, 100, 0x464D4520, 0x10000, 88 + len(enr) + 20,
                        3, 1, 0, 0, 0, 0, 1000, 1000, 100, 100)
               + enr + _st.pack('<IIIII', 14, 20, 0, 0, 20))
        traces, _r = metafile.lire_emf(emf)
        assert len(traces) == 1 and abs(traces[0][1][0] - 10.0) < 1e-9, \
            "EMF"
        etapes.append("arcs, police à trait simple, Tracé texte, EMF/WMF")
        # texte courbé, région, points le long, ajuster/prolonger,
        # réseaux, mesures, formes, cotes
        from src.core import texte_courbe, formes, cotation, retouche
        arc = Trace.chemins({'shape': 'Texte', 'texte_fil': 'AB',
                             'disposition_fil': 'Arc (dessus)',
                             'rayon_fil': 10.0})
        assert arc and texte_courbe.Arc(0, 0, 10, 90).point(0)[1] == 10.0
        carre = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]
        assert retouche.region_au_point(
            [[(0, 5), (20, 5)], [(5, 0), (5, 10)], [(15, 0), (15, 10)],
             [(0, 0), (20, 0)]], (10, 2)), "région"
        assert len(retouche.points_le_long(carre, nombre=4)) == 4
        assert retouche.ajuster([(0, 5), (20, 5)], [[(5, 0), (5, 10)]],
                                (2, 5)) == [[(5.0, 5.0), (20.0, 5.0)]]
        assert retouche.mesures([carre])['aire'] == 100.0
        th = np.linspace(0, 2 * np.pi, 41)
        assert formes.reconnaitre([(4 * np.cos(a), 4 * np.sin(a))
                                   for a in th])['genre'] == 'cercle'
        assert cotation.cote_alignee((0, 0), (30, 40), (0, 9))['texte'] \
            == "50"
        etapes.append("texte courbé, région, ajuster, réseaux, formes, "
                      "cotes")
        # barre unique, affichage par opé, programme externe simulé,
        # maillages, IGES, DWG, contraintes
        from src.core import affichage, contraintes as cg
        from src.gui import barre_outils  # noqa: F401
        from src.io.vecteur import maillage, iges, dwg  # noqa: F401
        boite = np.array([[[0, 0, 0], [10, 0, 0], [10, 10, 0]],
                          [[0, 0, 0], [10, 10, 0], [0, 10, 0]]], float)
        assert maillage.modele_depuis_triangles(boite).faces, "maillage"
        assert affichage.decimer(list(range(10)), 5) == [0, 5, 9]
        sy = cg.Systeme()
        a_, b_ = sy.point(0, 0), sy.point(3, 1)
        sy.ajouter('horizontale', (a_, b_))
        sy.ajouter('longueur', (a_, b_), 5.0)
        assert sy.resoudre()[0], "contraintes (scipy.optimize)"
        etapes.append("barre unique, affichage par opé, STL/3DXML/IGES/"
                      "DWG, contraintes")
        # barres en icônes qui passent à la ligne; précision réglable
        # de l'usinage 3D
        from PySide6.QtWidgets import QApplication
        _app = QApplication.instance() or QApplication(["neodrive"])
        from src.gui import icones_barre, icons
        vides = [n for n in icones_barre.NOMS
                 if icons.get_icon(n, 18).isNull()]
        assert not vides, f"icônes vides: {vides}"
        flux = barre_outils.FluxLayout()
        assert flux.heightForWidth(300) >= 0
        from src.core import usinage3d
        g = usinage3d.Grille(0, 1000, 0, 1000, pas=0.05)
        assert g.pas_demande == 0.05 and g.nx * g.ny <= \
            usinage3d.CASES_PLAFOND, "plafond de la carte"
        assert usinage3d.PRECISIONS['fine'][1] == 0.1
        etapes.append("barres en icônes à la ligne, précision de "
                      "l'usinage 3D")
        # round 14: couleurs des outils, temps machine, PNG réglable,
        # icônes des fenêtres, lecture du webshop DATRON
        from src.core import maj_datron, sim3d
        from src.core.tool_library import couleur_de_rang, couleur_valide
        from src.gui import icones_fenetres
        from src.gui.dialogs import reglages_png
        assert couleur_valide("#ABCDEF") == "#abcdef"
        assert len({couleur_de_rang(i) for i in range(60)}) == 60
        t = sim3d.temps_parcours({'x': [0, 10], 'y': [0, 0], 'z': [0, 0],
                                  'k': [0, 1], 'outil': ['A', 'A']},
                                 lambda a: {'finishing': 600})
        assert abs(t[-1] - 1.0) < 1e-9, "temps machine"
        page = ('<th class="properties-label">Winkel:</th>'
                '<td class="properties-value"><span>30</span></td>')
        assert maj_datron.fiche(maj_datron.proprietes(page))['angle'] == 30
        assert not icones_fenetres.icone_derivee("Canva 3D").isNull()
        assert reglages_png.lire(None)['opacite_matiere'] < 1
        etapes.append("couleurs des outils, temps machine, PNG réglable, "
                      "icônes des fenêtres, datron.de")
        # round 15: brut laiton, coins vifs, Ø par point, panneau 3D,
        # réduction à l'écran, programme appelé repris
        from src.core.program_model import ProjectSettings
        from src.operations import depuis_selection as ds
        from src.gui import canvas3d
        from src.gui.dxf.barre_imports import BandeauImports  # noqa: F401
        reglages = ProjectSettings()
        reglages.brut_longueur, reglages.brut_largeur = 100.0, 50.0
        reglages.brut_epaisseur = 3.0
        assert reglages.boite_brut() == (0.0, 100.0, 0.0, 50.0, -3.0, 0.0)
        assert ds.champ_coins_vifs("poche_rectangle", [{'rayon': 0}],
                                   1.5)[3] == 1.5
        assert SimPlGenerator._diametre_du_point(
            type('O', (), {'operation_type': 'percage_fraise',
                           'params': {'diametres_par_point': True}})(),
            {'diameter': 3.3}) == 3.3
        assert len(canvas3d.ENTITES_3D) == 8
        assert canvas3d.polygone_ecran(np.linspace(0, 100, 1000),
                                       np.zeros(1000)).size() < 200
        assert hasattr(sim3d, 'temps_parcours')
        from src.core import sim_cycles as _sc
        assert 'etat_final' in _sc.simuler(
            "export program Main\n    Line X=1 Y=0 Z=-1\nendprogram\n")
        etapes.append("brut laiton, coins vifs, Ø par point, panneau 3D, "
                      "programme appelé repris")
        # round 16: icône cube, post-processeur de VectorDrive, toutes
        # les commandes du manuel
        from src.io import vectordrive_job as vj
        from src.integrations import vectordrive_plugin as vp
        from src.core.simpl_syntaxe import SYNTAXE
        from src.operations import commandes_manuel as cm
        from src.core.program_model import OperationInstance
        assert os.path.isfile(os.path.join(vp.source_plugin(),
                                           "__init__.py"))
        travail = {'format': vj.FORMAT, 'version': vj.VERSION,
                   'outils': [], 'operations': [], 'parcours': [{
                       'nom': 'Message', 'mouvements': [], 'cycles': [{
                           'kind': 'instruction', 'name': 'message',
                           'params': {'message': 'Bonjour'}}]}]}
        prog, _avert, _abs = vj.programme_depuis_job(
            travail, ToolLibrary(), ajouter_outils='non')
        assert prog.operations
        assert len(SYNTAXE) == 143 and len(cm.A_ECRIRE) == 77
        p16 = ProgramModel()
        for t in ('manuel_SetSpecialToolOffset', 'filetage_special'):
            o = OperationInstance(t, t)
            o.x, o.y = 5.0, 5.0
            p16.add_operation(o)
        code16 = SimPlGenerator(p16, ToolLibrary()).generate()
        assert "import SpecialTool" in code16
        assert "SpecialThread (" in code16
        r16 = _sc.simuler("export program Main\n    Rapid X=0 Y=0 Z=-1\n"
                          "    MoveToSafetyPosition\n"
                          "    SEQUENCE_1 Schneiden=600\nendprogram\n"
                          "$$$ SEQUENCE_1\nLine X=9 Y=0 Z=-1\n$$$\n")
        assert max(r16['z']) >= 30.0 and r16['x'][-1] == 9.0, \
            "position de sécurité, séquence appelée avec paramètres"
        etapes.append("icône cube, post-processeur VectorDrive, "
                      "commandes du manuel, filetage spécial, position "
                      "de sécurité")
        # round 17: les blocs importés appelés par un motif, la séquence
        # d'un bloc en 3D
        import tempfile as _tf
        from src.io.simpl_importer import import_simpl_as_blocks
        _d = _tf.mkdtemp()
        _f = os.path.join(_d, "motif.simpl")
        with open(_f, "w", encoding="utf-8") as _fh:
            _fh.write("export program Main\n    Pattern::RectanglePattern "
                      "xCount=2 yCount=2 deltaX=10 deltaY=10 "
                      "callProgram=Trou\nendprogram\nprogram Trou\n"
                      "    SafeRapid X=0 Y=0 Z=15\n    Drill (depth=2 "
                      "infeedZ=2 strokeRapidZ=15 strokeCuttingZ=1)\n"
                      "endprogram\n")
        _lib = ToolLibrary(os.path.join(_d, "tools.json"))
        _code = SimPlGenerator(import_simpl_as_blocks(_f, _lib), _lib,
                               calculer=False).generate()
        assert _sc.simuler(_code)['cycles']['Drill'] == 4, \
            "bloc appelé par un motif"
        etapes.append("blocs appelés par un motif")
        # round 18: ce que le Main fait lui-même (pause, programme
        # externe, gravure) repart à sa place
        _f = os.path.join(_d, "appel.simpl")
        with open(_f, "w", encoding="utf-8") as _fh:
            _fh.write('usermodule UM_DESSUS="network:X:\\\\Dessus.simpl"\n'
                      "export program Main\n    Absolute\n    Dialog (\n"
                      '    caption="Dessus"\n    message="Retourner"\n    )\n'
                      "    UM_DESSUS\n    Engrave::StandardTextEngrave (\n"
                      '        text="A"\n        charHeight=2\n'
                      "        strokeRapidZ=10\n        strokeCuttingZ=1\n"
                      "        depth=0.1\n        Center\n    )\n"
                      "endprogram\n")
        _p = import_simpl_as_blocks(_f, _lib)
        assert [o.operation_type for o in _p.operations] == [
            "lignes_main", "appel_programme", "lignes_main"], \
            "lignes du Main importées"
        _code = SimPlGenerator(_p, _lib, calculer=False).generate()
        assert _code.count('caption="Dessus"') == 1 and \
            _code.count('usermodule UM_DESSUS=') == 1 and \
            _sc.simuler(_code)['cycles'].get(
                'Engrave::StandardTextEngrave') == 1, "lignes du Main"
        etapes.append("lignes du Main")
        # le programme appelé, nommé pour la machine (network:X:), lu
        # sur le poste par la 3D
        from src.core import chemins_machine as _cm
        with open(os.path.join(_d, "Dessus.simpl"), "w",
                  encoding="utf-8") as _fh:
            _fh.write("export program Main\n    Rapid X=0 Y=0 Z=5\n"
                      "    Line Z=-1\n    Line X=10\nendprogram\n")
        _cm.regler(_d, "network:X:")
        try:
            assert _sc.simuler(_code)['cycles'].get('Appel externe') == 1, \
                "chemins machine"
        finally:
            _cm.regler("", "")
        etapes.append("chemins machine")
        # les @ ToolDescription @ du fichier repartent avec lui, et la
        # Tool List cite l'outil que le Main prend lui-même
        with open(_f, "w", encoding="utf-8") as _fh:
            _fh.write('@ ToolDescription : "Name":"Gravure", '
                      '"ArticleNr":"0068443G", "Vendor":"DATRON" @\n'
                      "export program Main\n    Absolute\n"
                      '    Tool name="Gravure" newRpm=40000 skipRestoring\n'
                      "    Engrave::StandardTextEngrave (\n"
                      '        text="A"\n        charHeight=2\n'
                      "        strokeRapidZ=10\n        strokeCuttingZ=1\n"
                      "        depth=0.1\n        Center\n    )\n"
                      "endprogram\n")
        _code = SimPlGenerator(import_simpl_as_blocks(_f, _lib), _lib,
                               calculer=False).generate()
        assert '"ArticleNr":"0068443G"' in \
            _code.split("export program Main")[0] and "0068443G" in \
            _code.split("Tool List", 1)[-1], "outils des programmes importés"
        etapes.append("outils des programmes importés")
        # la séquence d'un bloc: gardée à la réouverture (NDMETA), et
        # un nom unique partout quand le bloc est copié
        from src.io.simpl_importer import (extract_neodrive_metadata,
                                           program_from_metadata)
        with open(_f, "w", encoding="utf-8") as _fh:
            _fh.write("sequence SEQUENCE_1\nexport program Main\n"
                      "    Absolute\n    Op\nendprogram\nprogram Op\n"
                      "    SEQUENCE_1\nendprogram\nend\n$$$ SEQUENCE_1\n"
                      "Rapid X=0 Y=0 Z=5\nLine Z=-1\nLine X=10\n")
        _p = import_simpl_as_blocks(_f, _lib)
        _p.add_operation(_p.operations[0].clone())
        _code = SimPlGenerator(_p, _lib, calculer=False).generate()
        _code2 = SimPlGenerator(program_from_metadata(
            extract_neodrive_metadata(_code), _lib, _code), _lib,
            calculer=False).generate()
        import re as _re
        assert sorted(_re.findall(r'^\$\$\$ (\S+)', _code2, _re.M)) == [
            "SEQUENCE_1", "SEQUENCE_1_2"], "séquences des blocs"
        etapes.append("séquences des blocs")
        # le contrôle de structure avant export: ce programme passe, le
        # même sans son dernier bloc $$$ est refusé
        from src.core import controle_simpl as _cs
        assert not _cs.erreurs(_cs.controler(_code2, False)), \
            "contrôle de structure"
        assert _cs.erreurs(_cs.controler(
            _code2.rsplit("$$$", 1)[0], False)), "contrôle de structure"
        assert any("« Z » ?" in c.message for c in _cs.controler(
            "export program Main\n    Rapid X=1 Zz=2\nendprogram\nend\n",
            False)), "paramètre mal orthographié"
        etapes.append("contrôle de structure")
        # les gros parcours du Canva 3D: polygones remplis d'un bloc
        # (sans quoi ils se construisent point par point, 2× plus lents)
        import numpy as _np
        from src.gui import polygones as _pg
        assert _pg.stockage_direct(), "polygones remplis d'un bloc"
        _poly = _pg.polygone(_np.array([[1.5, -2.0], [3.0, 4.25]]))
        assert [(_poly.at(i).x(), _poly.at(i).y()) for i in range(2)] == [
            (1.5, -2.0), (3.0, 4.25)], "polygones remplis d'un bloc"
        etapes.append("polygones remplis d'un bloc")
        # round 20: ce que la machine a mesuré (« .MetaData » voisin),
        # et les avances que le programme fixe dans le temps estimé
        import tempfile as _tf
        from src.core import sim_cycles as _sc
        from src.core import temps_reels as _tr
        _prog = os.path.join(_tf.mkdtemp(prefix="nd_auto_"), "p.simpl")
        _horo = os.path.join(_prog + ".MetaData", "Timestamps")
        os.makedirs(_horo)
        with open(os.path.join(_horo, "1_Runtime.csv"), "w",
                  encoding="utf-8") as _f:
            _f.write("TimeStamp;Category;AdditionalInformation\n"
                     "2025.05.07_16:47:34;StartProgram;p\n"
                     "2025.05.07_16:57:08;EndProgram;p\n")
        assert _tr.resume(_prog)['mediane'] == 574.0, "temps réels"
        _res = _sc.simuler(
            "export program Main\n    Absolute\n"
            "    SetFeedTechnology finishing=6000\n    Rapid X=0 Y=0 Z=0\n"
            "    Feed Finishing\n    Line X=60 Y=0 Z=0\nendprogram\nend\n")
        _t = sim3d.temps_parcours(_res)
        assert abs(_t[-1] - _t[-2] - 0.6) < 1e-6, "avances programmées"
        etapes.append("temps réels de la machine, avances programmées")
        # round 28, l'exe allégé: sans Pillow, pypdf lit toujours les
        # tracés d'un PDF; cryptography ouvre un PDF protégé (AES) — le
        # guide de coupe DATRON l'est; et les greffons d'image de Qt
        # gardés sont bien là (le lecteur PDF de Qt, lui, est parti)
        from PySide6.QtCore import QMarginsF, QPointF
        from PySide6.QtGui import (QImageReader, QPageLayout, QPageSize,
                                   QPainter, QPainterPath, QPdfWriter)
        from pypdf import PdfReader, PdfWriter
        from src.io import vecteur as _vec
        _dossier = _tf.mkdtemp(prefix="nd_auto_")
        _clair = os.path.join(_dossier, "clair.pdf")
        _ecrivain = QPdfWriter(_clair)
        _ecrivain.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        _ecrivain.setPageMargins(QMarginsF(0, 0, 0, 0),
                                 QPageLayout.Unit.Millimeter)
        _ecrivain.setResolution(72)
        _peintre = QPainter(_ecrivain)
        _triangle = QPainterPath()
        _triangle.moveTo(QPointF(100, 100))
        _triangle.lineTo(QPointF(300, 100))
        _triangle.lineTo(QPointF(300, 250))
        _triangle.closeSubpath()
        _peintre.drawPath(_triangle)
        _peintre.end()
        _protege = os.path.join(_dossier, "protege.pdf")
        _copie = PdfWriter()
        for _page in PdfReader(_clair).pages:
            _copie.add_page(_page)
        _copie.encrypt(user_password="", owner_password="atelier",
                       algorithm="AES-256")
        with open(_protege, "wb") as _fh:
            _copie.write(_fh)
        assert PdfReader(_protege).is_encrypted, "PDF protégé"
        for _pdf in (_clair, _protege):
            _calques, _rapport = _vec.lire(_pdf)
            _largeur, _hauteur = _rapport.size_mm()
            # 200 × 150 points à 72 par pouce: 70,6 × 52,9 mm
            assert any(_calques.values()) and \
                abs(_largeur - 70.56) < 0.5 and \
                abs(_hauteur - 52.92) < 0.5, \
                f"PDF {os.path.basename(_pdf)}: {_largeur} × {_hauteur}"
        etapes.append("PDF (tracés, protégé AES)")
        _formats = {bytes(_f).decode().lower()
                    for _f in QImageReader.supportedImageFormats()}
        _voulus = {'png', 'jpg', 'jpeg', 'bmp', 'gif', 'tif', 'tiff',
                   'webp', 'svg', 'ico'}
        assert _voulus <= _formats, \
            f"formats d'image perdus: {sorted(_voulus - _formats)}"
        etapes.append(f"images ({len(_formats)} formats)")
        # round 32: NeoDrive est sous licence MIT ou Apache-2.0; l'exe
        # voyage avec ses licences et celles de tout ce qu'il embarque
        # (Qt sous LGPL-3.0…): sans elles, tools/publier.py ne publie pas
        if getattr(sys, 'frozen', False):
            from src.core.tool_library import get_base_dir as _base_exe
            verifier_licences(_base_exe())
            etapes.append("licences")
    except Exception:
        traceback.print_exc()
        print("[NeoDrive] AUTOCONTROLE ECHOUE apres: "
              + ", ".join(etapes))
        return 1
    from src import __version__
    print(f"[NeoDrive] AUTOCONTROLE OK (version {__version__}): "
          + ", ".join(etapes))
    return 0


def postpro(arguments) -> int:
    """NeoDrive, post-processeur de VectorDrive (son plugin « NeoDrive »
    l'appelle):

        NeoDrive --postpro TRAVAIL.ndjob [--sortie PROGRAMME.SimPl]
                 [--rapport RAPPORT.json] [--avances vectordrive|neodrive]

    Écrit le programme Datron du travail — avec la bibliothèque d'outils
    de NeoDrive (les outils absents servent au programme sans être
    enregistrés) et son NDMETA (le .SimPl se rouvre dans NeoDrive,
    opérations comprises) — sans ouvrir de fenêtre. Code de sortie: 0
    écrit, 2 travail refusé, 1 erreur."""
    import json
    import traceback

    def _option(nom, defaut=None):
        if nom in arguments:
            i = arguments.index(nom)
            if i + 1 < len(arguments):
                return arguments[i + 1]
        return defaut
    travail = _option('--postpro')
    sortie = _option('--sortie') or (
        os.path.splitext(travail or 'programme')[0] + '.SimPl')
    rapport = _option('--rapport')
    avances = _option('--avances', 'vectordrive')

    def _rapport(donnees):
        if rapport:
            try:
                with open(rapport, 'w', encoding='utf-8') as f:
                    json.dump(donnees, f, ensure_ascii=False, indent=1)
            except OSError:
                pass
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    try:
        from PySide6.QtGui import QGuiApplication
        _app = QGuiApplication.instance() or QGuiApplication(
            ["neodrive-postpro"])
        import src.operations  # noqa: F401
        from src.core.tool_library import ToolLibrary
        from src.io import vectordrive_job as vj
        try:
            job = vj.lire(travail or '')
        except vj.JobError as exc:
            print(f"[NeoDrive] POSTPRO REFUSE: {exc}")
            _rapport({'erreur': str(exc)})
            return 2
        outils = ToolLibrary()
        outils.load()
        code, avert = vj.generer_simpl(job, outils, 'memoire', avances)
        # d'un coup: VectorDrive ne lit jamais un programme à moitié écrit
        from src.core.fichiers_surs import ecrire_texte_sur
        ecrire_texte_sur(sortie, code)
        _rapport({'sortie': sortie, 'avertissements': avert})
        print(f"[NeoDrive] POSTPRO OK: {sortie} ({len(avert)} "
              "avertissement(s))")
        return 0
    except Exception as exc:
        traceback.print_exc()
        _rapport({'erreur': f"{type(exc).__name__}: {exc}"})
        return 1


def capture(window, dossier: str) -> str:
    """Photographie la fenêtre et la liste d'opérations dans `dossier`.

    `NeoDrive.exe --capture C:\\un\\dossier`: l'exe lui-même, avec ses
    réglages, son thème et ses polices, rend sa fenêtre en PNG et
    écrit ce qu'il mesure. C'est la seule façon de voir ce que
    l'atelier voit — les rendus depuis les sources ou hors écran
    montraient des boutons de ligne que l'exe n'affichait pas.
    Rien n'est écrit dans les réglages ni la session."""
    import tempfile
    from PySide6.QtWidgets import QApplication
    from src.core.program_model import OperationInstance
    os.makedirs(dossier, exist_ok=True)
    # aucune trace: réglages et session de l'utilisateur intacts
    window.params_panel._settings_path = os.path.join(
        tempfile.mkdtemp(prefix="neodrive_capture_"), "reglages.json")
    window._auto_save = lambda *a, **k: None
    # comme l'atelier la voit: sa géométrie, maximisée s'il l'a laissée
    # une capture ne pose pas de question (rien pour y répondre)
    window.operations_panel.reponse_miroir = False
    window.afficher_au_demarrage()
    for _ in range(6):
        QApplication.processEvents()
    panneau = window.operations_panel
    if not window.program.operation_count:
        # par le même chemin que « + Opé »: le catalogue, puis le
        # formulaire, puis retour à la liste
        for genre in ("gravure_texte", "gravure_2d5"):
            panneau._add_op(genre)
            for _ in range(4):
                QApplication.processEvents()
        window.program.operations[-1].name = (
            "Parcours gravure (V) — un nom long pour voir l'élision "
            "au bord droit")
        panneau._refresh_list()
    for _ in range(8):
        QApplication.processEvents()
    liste = window.operations_panel.op_list
    liste.grab().save(os.path.join(dossier, "liste.png"))
    window.grab().save(os.path.join(dossier, "fenetre.png"))
    # le panneau de dessin: ses boîtes d'outils (Accroch., Retouches,
    # Nettoyer…) avec les polices de l'exe
    dessin = getattr(window, 'dxf_panel', None)
    boutons = []
    if dessin is not None:
        dessin.grab().save(os.path.join(dossier, "dessin.png"))
        for nom in ('accroche_btn', 'retouches_btn', 'nettoyer_btn'):
            b = getattr(dessin, nom, None)
            if b is not None:
                boutons.append(f"bouton {nom}: {b.width()}x{b.height()} "
                               f"(voulu {b.sizeHint().width()}) "
                               f"visible {b.isVisible()}")
    lignes = [f"plateforme {QApplication.platformName()}",
              f"fenetre {window.width()}x{window.height()}",
              f"colonnes {window._splitter.sizes()}",
              f"liste {liste.width()} viewport {liste.viewport().width()}"
              f" hscroll {liste.horizontalScrollBar().maximum()}",
              f"police {liste.font().family()} {liste.font().pointSize()}"
              f"pt {liste.font().pixelSize()}px",
              f"delegue {type(liste.itemDelegate()).__name__}"] + boutons
    try:
        from src.gui.panels.operations_panel import _FavStarDelegate
        for rang in range(liste.count()):
            item = liste.item(rang)
            rect = liste.visualItemRect(item)
            lignes.append(
                f"ligne {rang}: rect {rect.x()},{rect.y()} "
                f"{rect.width()}x{rect.height()} | "
                f"bord {_FavStarDelegate.bord_droit(liste, rect)} | "
                f"zones {_FavStarDelegate.zones(item.data)} | "
                f"{item.text()[:40]!r}")
    except Exception as exc:          # noqa: BLE001 — on veut le voir
        lignes.append(f"delegue en erreur: {exc!r}")
    chemin = os.path.join(dossier, "mesures.txt")
    with io.open(chemin, 'w', encoding='utf-8') as f:
        f.write("\n".join(lignes) + "\n")
    return chemin


def tester_photos(arguments) -> int:
    """`NeoDrive.exe --photos 0078430S [dossier]`: télécharge les photos
    d'une référence sur le webshop DATRON — l'exe lui-même, https
    compris — et dit combien, en combien de temps, où. L'autocontrôle
    ne touche pas le réseau (l'atelier peut être hors ligne): ceci le
    vérifie quand on le veut."""
    import tempfile
    import time
    from PySide6.QtGui import QGuiApplication
    _app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841
    i = arguments.index("--photos")
    ref = arguments[i + 1] if i + 1 < len(arguments) else "0078430S"
    dossier = (arguments[i + 2] if i + 2 < len(arguments)
               else tempfile.mkdtemp(prefix="neodrive_photos_"))
    from src.core import images_datron
    debut = time.time()
    try:
        chemins = images_datron.telecharger(ref, dossier, forcer=True)
    except Exception as exc:
        print(f"[NeoDrive] PHOTOS ECHEC ({ref}): {exc}")
        return 1
    print(f"[NeoDrive] PHOTOS {'OK' if chemins else 'AUCUNE'}: "
          f"{len(chemins)} image(s) de {ref} en {time.time() - debut:.1f} s "
          f"dans {dossier} (originaux: "
          f"{len(images_datron.originaux(dossier, ref))})")
    return 0 if chemins else 1


def main():
    # Résoudre le répertoire de base (dev ou PyInstaller)
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    # S'assurer que le répertoire de base est dans sys.path
    if base_dir not in sys.path:
        sys.path.insert(0, base_dir)

    # Créer les répertoires nécessaires
    os.makedirs(os.path.join(base_dir, "programs"), exist_ok=True)
    os.makedirs(os.path.join(base_dir, "exports"), exist_ok=True)
    os.makedirs(os.path.join(base_dir, "data"), exist_ok=True)
    _restaures = restaurer_data(base_dir)
    if _restaures:
        print("[NeoDrive] data/ complété depuis l'exe: "
              + ", ".join(_restaures))

    if "--autocontrole" in sys.argv:
        # après chaque build: la dist sait-elle encore graver ?
        sys.exit(autocontrole())
    if "--photos" in sys.argv:
        sys.exit(tester_photos(sys.argv))
    if "--postpro" in sys.argv:
        # NeoDrive, post-processeur de VectorDrive: sans fenêtre
        sys.exit(postpro(sys.argv))

    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QIcon

    app = QApplication(sys.argv)
    app.setApplicationName("NeoDrive")
    app.setOrganizationName("NeoDrive")
    app.setApplicationVersion("1.0.0")

    # Une seule instance: « Ouvrir avec NeoDrive » depuis l'Explorateur
    # passe le fichier à la fenêtre déjà ouverte, qui l'ouvre dans un
    # nouvel onglet et se met devant. `--seul` force une instance à
    # part (tests, capture).
    # Le verrou et la prise s'ouvrent AVANT la fenêtre (4 à 5 s de
    # construction): deux NeoDrive lancés ensemble devenaient deux
    # instances complètes, la seconde écrasant la session de la
    # première. Ce qui arrive pendant la construction attend dans
    # l'accueil.
    fichiers = fichiers_en_argument(sys.argv[1:])
    accueil = None
    if "--seul" not in sys.argv and "--capture" not in sys.argv:
        try:
            from src.integrations import instance_unique
            accueil, delegue = instance_unique.demarrer(fichiers)
            if delegue:
                return
        except Exception:
            accueil = None

    # Icône
    icon_path = os.path.join(base_dir, "data", "neodrive.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # Thème sombre
    from src.gui.theme import apply_dark_theme
    apply_dark_theme(app)

    # Splash screen
    from PySide6.QtWidgets import QSplashScreen
    from PySide6.QtGui import QPixmap
    splash_path = os.path.join(base_dir, "data", "NeoDriveLoad.png")
    splash = None
    if os.path.exists(splash_path):
        pixmap = QPixmap(splash_path)
        splash = QSplashScreen(pixmap)
        splash.show()
        app.processEvents()

    # Importer les opérations (déclenche les décorateurs @register)
    import src.operations  # noqa: F401

    # Créer et afficher la fenêtre principale
    from src.gui.main_window import MainWindow
    window = MainWindow()
    if "--capture" in sys.argv:
        # l'exe se photographie, puis s'en va sans rien écrire
        dossier = sys.argv[sys.argv.index("--capture") + 1] \
            if sys.argv.index("--capture") + 1 < len(sys.argv) \
            else os.path.join(base_dir, "exports", "capture")
        capture(window, dossier)
        os._exit(0)
    # comme on l'a laissée, plein écran sinon — et dans le bon ordre
    window.afficher_au_demarrage()

    # « Ouvrir avec NeoDrive » depuis l'Explorateur: le fichier
    # arrive en argument. Après le premier tour de boucle, que la
    # fenêtre soit là pour l'accueillir.
    if fichiers:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(
            0, lambda: [window.ouvrir_fichier(f) for f in fichiers])

    # …et les lancements suivants arrivent par la prise locale,
    # ouverte dès le début: ceux arrivés pendant la construction de
    # la fenêtre lui sont passés maintenant
    if accueil is not None:
        window._serveur_instance = accueil.serveur
        accueil.brancher(window.recevoir_fichiers)

    # Fermer le splash screen
    if splash:
        splash.finish(window)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
