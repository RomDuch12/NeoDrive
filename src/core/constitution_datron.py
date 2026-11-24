# -*- coding: utf-8 -*-
"""Constituer le catalogue DATRON sur le poste, depuis le webshop.

NeoDrive ne livre pas de catalogue DATRON: ce sont les données de
DATRON AG (round 33). L'application le CONSTITUE elle-même, à la
demande de l'utilisateur, depuis ce que le webshop publie pour tout
le monde:

1. le plan du site (`sitemap.xml`, que le webshop offre aux robots —
   son robots.txt ouvre les fiches produits) donne l'adresse de
   chaque fiche de la rubrique « Industrie-Fräswerkzeuge »: la
   référence et la famille s'y lisent;
2. chaque fiche donne ses cotes dans son tableau de propriétés (D1,
   D2, L1, L2, L3, Winkel, R, Z, Gewinde…, lu par `maj_datron`) et son
   prix dans ses données structurées (schema.org).

Une fiche à la fois, avec une pause entre deux (le webshop n'est pas
à nous); le travail s'enregistre au fil de l'eau dans
`data/catalogue_datron.json` et REPREND où il s'est arrêté (Annuler,
réseau coupé, application fermée). Les références déjà au catalogue
sont mises à jour, celles que le webshop ne connaît plus restent.

Le catalogue reste à côté de l'exe, pour l'usage de l'utilisateur:
il ne contient AUCUNE donnée de coupe, et ne se redistribue pas.
"""

import gzip
import json
import re
import time
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

#: le plan du site du webshop
URL_PLAN = "https://webshop.datron.de/sitemap.xml"
#: la rubrique lue: les outils de fraisage industriels
RUBRIQUE = "industrie-fraeswerkzeuge"
#: pause entre deux fiches, en secondes
PAUSE = 0.5
#: le travail s'enregistre toutes les ENREGISTRER fiches
ENREGISTRER = 25
#: autant de fiches illisibles d'affilée: le réseau est tombé, on
#: s'arrête (ce qui est lu est gardé)
ERREURS_DE_SUITE = 5

#: rubrique du webshop (sous « Industrie-Fräswerkzeuge », en
#: minuscules) → (catégorie, famille) du catalogue
FAMILLES = {
    "bohrwerkzeuge/spiralbohrer/3mm-schaft": ("foret", "Foret queue 3 mm"),
    "bohrwerkzeuge/spiralbohrer/6mm-schaft": ("foret", "Foret queue 6 mm"),
    "diamantwerkzeuge/mkd/mkd-planfraeser":
        ("surfacage", "Fraise à surfacer diamant (MKD)"),
    "entgratwerkzeuge/aussenradiusfraeser/entgratfraeser":
        ("rayon", "Fraise à rayonner pour l'ébavurage"),
    "entgratwerkzeuge/aussenradiusfraeser/polierschliff":
        ("rayon", "Fraise à rayonner polie pour verre acrylique"),
    "entgratwerkzeuge/aussenradiusfraeser/standard":
        ("rayon", "Fraise à rayonner"),
    "entgratwerkzeuge/fasenfraeser/fraessenker":
        ("chanfrein", "Outil de lamage"),
    "entgratwerkzeuge/fasenfraeser/polierschliff":
        ("chanfrein", "Fraise à chanfreiner pour verre acrylique"),
    "entgratwerkzeuge/fasenfraeser/polierschliff-abgesetzt":
        ("chanfrein", "Fraise à chanfreiner pour mousse PU"),
    "entgratwerkzeuge/fasenfraeser/standard":
        ("chanfrein", "Fraise à chanfreiner"),
    "entgratwerkzeuge/fasenfraeser/v-nutfraeser":
        ("conique", "Fraise pour rainure en V"),
    "gewindewerkzeuge/gewindefraeser/fraesgewindefraeser":
        ("filetage", "Fraise à fileter 3 dents"),
    "gewindewerkzeuge/gewindefraeser/gewindefraeser":
        ("filetage", "Fraise à fileter à multiple denture"),
    "gewindewerkzeuge/gewindefraeser/gewindewirbler":
        ("filetage", "Fraise à fileter"),
    "gewindewerkzeuge/gewindefraeser/multi-gewindefraeser":
        ("filetage", "Fraise à fileter"),
    "gravierwerkzeuge/gravierstichel/hartfraesen-beschichtung-alcrona":
        ("conique", "Pointe à graver revêtue ALCRONA"),
    "gravierwerkzeuge/gravierstichel/stahlfraesen":
        ("conique", "Pointe à graver pour l'acier"),
    "gravierwerkzeuge/gravierstichel/standard":
        ("conique", "Pointe à graver"),
    "gravierwerkzeuge/gravierstichel/wuchtschliff":
        ("conique", "Pointe à graver équilibrée"),
    "schaftfraeser/dreischneider/beschichtung-x.ceed":
        ("fraise", "Fraise 3 dents revêtue X.CEED"),
    "schaftfraeser/dreischneider/freischliff":
        ("fraise", "Fraise 3 dents détalonnée"),
    "schaftfraeser/dreischneider/polierschliff":
        ("fraise", "Fraise 3 dents détalonnée pour mousse"),
    "schaftfraeser/dreischneider/schlichtfraeser":
        ("fraise", "Fraise 3 dents finition du cuivre"),
    "schaftfraeser/dreischneider/schruppfraeser":
        ("fraise", "Fraise 3 dents ébauche du cuivre"),
    "schaftfraeser/einschneider/4-in-1": ("fraise", "Fraise 1 dent 4-IN-1"),
    "schaftfraeser/einschneider/abgesetzt":
        ("surfacage", "Fraise à surfacer 1 dent étagée rayonnée"),
    "schaftfraeser/einschneider/beschichtung-alcrona":
        ("fraise", "Fraise 1 dent revêtue ALCRONA"),
    "schaftfraeser/einschneider/cross-cutter":
        ("fraise", "Fraise 1 dent Cross-Cutter"),
    "schaftfraeser/einschneider/freischliff":
        ("fraise", "Fraise 1 dent avec dépouille"),
    "schaftfraeser/einschneider/linksspiralisiert":
        ("fraise", "Fraise 1 dent hélice à gauche"),
    "schaftfraeser/einschneider/polierschliff":
        ("fraise", "Fraise 1 dent arête polie (acrylique)"),
    "schaftfraeser/einschneider/standard":
        ("fraise", "Fraise 1 dent standard"),
    "schaftfraeser/einschneider/wuchtschliff":
        ("fraise", "Fraise 1 dent équilibrée"),
    "schaftfraeser/mehrschneider/microverzahnt-beschichtung-diamant":
        ("fraise", "Fraise microdentée revêtue (X.CEED / diamant)"),
    "schaftfraeser/mehrschneider/microverzahnt-beschichtung-x.ceed":
        ("fraise", "Fraise microdentée revêtue (X.CEED / diamant)"),
    "schaftfraeser/mehrschneider/microverzahnt-standard":
        ("fraise", "Fraise microdentée FR4 / CFK"),
    "schaftfraeser/vierschneider/beschichtung-alcrona":
        ("fraise", "Fraise 4 dents revêtue ALCRONA"),
    "schaftfraeser/zweischneider/abgesetzt":
        ("surfacage", "Fraise à surfacer 2 dents étagée"),
    "schaftfraeser/zweischneider/beschichtung":
        ("fraise", "Fraise 2 dents pour l'acier (X.CEED)"),
    "schaftfraeser/zweischneider/freischliff":
        ("fraise", "Fraise 2 dents détalonnée"),
    "schaftfraeser/zweischneider/hsc": ("fraise", "Fraise 2 dents UGV+"),
    "schaftfraeser/zweischneider/hsc-fire":
        ("fraise", "Fraise 2 dents UGV Fire"),
    "schaftfraeser/zweischneider/innenkuehlung":
        ("fraise", "Fraise 2 dents à lubrification centre-outil"),
    "schaftfraeser/zweischneider/konturfraeser":
        ("fraise", "Fraise 2 dents pour contournage"),
    "schaftfraeser/zweischneider/standard": ("fraise", "Fraise 2 dents"),
    "stirnradiusfraeser/einschneider/polierschliff":
        ("boule", "Fraise boule 1 dent polie pour verre acrylique"),
    "stirnradiusfraeser/einschneider/standard":
        ("boule", "Fraise boule 1 dent"),
    "stirnradiusfraeser/vierschneider/beschichtung-alcrona":
        ("boule", "Fraise boule 4 dents revêtue ALCRONA"),
    "stirnradiusfraeser/zweischneider/beschichtung-alcrona":
        ("boule", "Fraise boule 2 dents revêtue ALCRONA"),
    "stirnradiusfraeser/zweischneider/freischliff":
        ("boule", "Fraise boule 2 dents détalonnée"),
    "stirnradiusfraeser/zweischneider/standard":
        ("boule", "Fraise boule 2 dents"),
    "torusfraeser/vierschneider/beschichtung-alcrona":
        ("torique", "Fraise torique 4 dents revêtue X.CEED"),
    "torusfraeser/vierschneider/doppelradius-beschichtung-x.ceed":
        ("torique", "Fraise torique 4 dents double hélice X.CEED"),
    "torusfraeser/zweischneider/abgesetzt":
        ("surfacage", "Fraise à surfacer 2 dents étagée rayonnée"),
    "torusfraeser/zweischneider/beschichtung-triple-cut":
        ("torique", "Fraise torique 2 dents revêtue Triple-Cut"),
    "torusfraeser/zweischneider/polierschliff-abgesetzt":
        ("surfacage",
         "Fraise à surfacer 2 dents étagée rayonnée polie (acrylique)"),
    "torusfraeser/zweischneider/standard": ("torique", "Fraise torique 2 dents"),
}

#: une rubrique que FAMILLES ne connaît pas encore: sa catégorie par
#: son début; la famille se dit avec les dents de la fiche
REPLIS = (
    ("schaftfraeser/", "fraise", "Fraise {dents}"),
    ("stirnradiusfraeser/", "boule", "Fraise boule {dents}"),
    ("torusfraeser/", "torique", "Fraise torique {dents}"),
    ("bohrwerkzeuge/spiralbohrer", "foret", "Foret"),
    ("gravierwerkzeuge/gravierstichel", "conique", "Pointe à graver"),
    ("gewindewerkzeuge/gewindefraeser", "filetage", "Fraise à fileter"),
    ("entgratwerkzeuge/fasenfraeser", "chanfrein", "Fraise à chanfreiner"),
    ("entgratwerkzeuge/aussenradiusfraeser", "rayon", "Fraise à rayonner"),
)

#: les catégories du catalogue, telles que l'onglet les nomme
CATEGORIES = {
    "fraise": "Fraise droite (1 à 8 dents)",
    "surfacage": "Fraise à surfacer",
    "boule": "Fraise boule",
    "torique": "Fraise torique (rayon de coin)",
    "filetage": "Fraise à fileter",
    "chanfrein": "Chanfrein / lamage",
    "foret": "Foret",
    "conique": "Conique (gravure, rainure en V)",
    "rayon": "Fraise à rayonner (rayon extérieur)",
}

COLONNES = {
    "D1": "Ø de coupe (pointe pour les pointes à graver, petit Ø pour "
          "les fraises à chanfreiner)",
    "D2": "Ø de queue",
    "D3": "Ø de dégagement ou grand Ø (chanfrein, rayon)",
    "L1": "longueur totale",
    "L2": "longueur de coupe",
    "L3": "longueur de dégagement",
    "angle": "angle de pointe ou de chanfrein (°)",
    "R": "rayon",
    "dents": "dents",
    "filetage": "filetages",
    "prix_eur": "prix du webshop DATRON en €, à l'unité, au jour de la "
                "lecture",
}

#: les cotes numériques qu'une fiche du webshop apporte au catalogue
COTES = ("D1", "D2", "D3", "L1", "L2", "L3", "angle", "R", "dents")

_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
_LD_RE = re.compile(
    r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
    re.S | re.I)


class Plan(list):
    """Les fiches à lire: [(réf, adresse, rubrique)]."""


def _texte(brut) -> str:
    if isinstance(brut, bytes):
        if brut[:2] == b"\x1f\x8b":
            brut = gzip.decompress(brut)
        return brut.decode("utf-8", "replace")
    return str(brut or "")


def _lire(lire_url: Optional[Callable]) -> Callable:
    if lire_url is not None:
        return lire_url
    from src.core import images_datron
    return images_datron.lire_url


def fiche_du_plan(adresse: str) -> Optional[Tuple[str, str]]:
    """(réf, rubrique) d'une adresse de fiche de la rubrique lue:
    « …/Industrie-Fraeswerkzeuge/Schaftfraeser/Einschneider/Standard/
    5290/0068003E-Einschneider » → (« 0068003E »,
    « schaftfraeser/einschneider/standard »). None pour le reste
    (rubriques, pages d'information, autres rubriques)."""
    m = re.match(r"https?://[^/]+/(.+)$", adresse.strip())
    if not m:
        return None
    parties = [p for p in m.group(1).split("/") if p]
    if (len(parties) < 4 or parties[0].lower() != RUBRIQUE
            or not parties[-2].isdigit()):
        return None
    ref = parties[-1].split("-")[0].strip().upper()
    if not re.fullmatch(r"[0-9A-Z]{5,}", ref):
        return None
    return ref, "/".join(parties[1:-2]).lower()


def plan(lire_url: Callable = None) -> Plan:
    """Les fiches du webshop, lues dans son plan (un index de plans,
    chacun éventuellement compressé). Lève OSError sans réseau."""
    lire = _lire(lire_url)
    a_lire = [URL_PLAN]
    vus = set()
    sortie = Plan()
    refs = set()
    while a_lire:
        adresse = a_lire.pop(0)
        if adresse in vus:
            continue
        vus.add(adresse)
        texte = _texte(lire(adresse))
        index = "<sitemapindex" in texte[:2000].lower()
        for loc in _LOC_RE.findall(texte):
            loc = loc.replace("&amp;", "&")
            if index:
                a_lire.append(loc)
                continue
            trouve = fiche_du_plan(loc)
            if trouve and trouve[0] not in refs:
                refs.add(trouve[0])
                sortie.append((trouve[0], loc, trouve[1]))
    return sortie


def classer(rubrique: str, dents=None) -> Optional[Tuple[str, str]]:
    """(catégorie, famille) d'une rubrique du webshop, ou None (une
    rubrique hors du catalogue: alésoirs, fraises de forme, porte-
    plaquettes…)."""
    rubrique = str(rubrique or "").lower()
    if rubrique in FAMILLES:
        return FAMILLES[rubrique]
    for debut, categorie, famille in REPLIS:
        if rubrique.startswith(debut):
            n = int(dents) if dents else 0
            mot = (f"{n} dent" + ("s" if n > 1 else "")) if n else ""
            return categorie, " ".join(famille.format(dents=mot).split())
    return None


def _donnees_structurees(page: str) -> Dict:
    """Le produit des données schema.org de la fiche (nom, prix)."""
    for bloc in _LD_RE.findall(page):
        try:
            d = json.loads(bloc)
        except ValueError:
            continue
        for x in (d if isinstance(d, list) else [d]):
            if isinstance(x, dict) and x.get("@type") == "Product":
                return x
    return {}


def _prix(produit: Dict) -> Optional[float]:
    """Le prix à l'unité: le plus haut des prix par quantité."""
    offres = produit.get("offers")
    for o in (offres if isinstance(offres, list) else [offres]):
        if not isinstance(o, dict):
            continue
        for cle in ("highPrice", "price"):
            try:
                v = float(o.get(cle))
            except (TypeError, ValueError):
                continue
            if v > 0:
                return round(v, 2)
    return None


def entree(page, ref: str, rubrique: str) -> Optional[Dict]:
    """L'entrée du catalogue tirée d'une fiche produit, ou None (fiche
    sans cotes, ou rubrique hors du catalogue)."""
    from src.core import maj_datron
    page = _texte(page)
    props = maj_datron.proprietes(page)
    cotes = maj_datron.fiche(props)
    # « D3 Schaftfreischliff »: le Ø de dégagement de la queue
    for libelle, valeur in props.items():
        mots = libelle.split()
        if len(mots) > 1 and mots[0].upper() == "D3" and "D3" not in cotes:
            v = maj_datron.nombre(valeur)
            if v is not None:
                cotes["D3"] = v
    if not cotes.get("D1"):
        return None
    classe = classer(rubrique, cotes.get("dents"))
    if classe is None:
        return None
    categorie, famille = classe
    x = {"ref": ref.upper(), "categorie": categorie, "famille": famille}
    for k in COTES:
        v = cotes.get(k)
        if v is not None:
            x[k] = int(v) if k == "dents" else (
                int(v) if float(v).is_integer() else v)
    if categorie == "foret" and "dents" not in x:
        x["dents"] = 2
    filetage = next((v for k, v in props.items()
                     if k.strip().lower() == "gewinde"), "")
    if filetage:
        x["filetage"] = " ".join(str(filetage).split())
    produit = _donnees_structurees(page)
    prix = _prix(produit)
    if prix is not None:
        x["prix_eur"] = prix
    nom = str(produit.get("name") or "")
    designation = " ".join(m for m in nom.split()
                           if m.upper() != ref.upper())
    if designation:
        x["designation_de"] = designation
    return x


def _squelette(date: str) -> Dict:
    return {
        "_info": ("Catalogue d'outils DATRON constitué sur ce poste par "
                  "NeoDrive, depuis les fiches publiques du webshop "
                  "DATRON: références, familles, cotes (mm), angles (°), "
                  "rayons, filetages et prix. Données de DATRON AG, pour "
                  "l'usage de l'utilisateur: ne pas redistribuer. Aucune "
                  "donnée de coupe."),
        "categories": dict(CATEGORIES),
        "colonnes": dict(COLONNES),
        "sources": {"webshop": "https://webshop.datron.de/",
                    "plan": URL_PLAN,
                    "fiche_webshop":
                        "https://webshop.datron.de/search?search={ref}"},
        "outils": [],
        "_constitution": {"debut": date, "complet": False, "lues": []},
    }


def etat(chemin: str) -> Dict:
    """Où en est la constitution du catalogue de `chemin`:
    {'present', 'constitue', 'complet', 'lues', 'outils', 'date'}."""
    from src.core.fichiers_surs import lire_json
    d = lire_json(chemin)
    if not isinstance(d, dict):
        return {'present': False, 'constitue': False, 'complet': False,
                'lues': 0, 'outils': 0, 'date': ""}
    c = d.get("_constitution") if isinstance(
        d.get("_constitution"), dict) else None
    return {'present': True, 'constitue': c is not None,
            'complet': bool(c.get("complet")) if c else True,
            'lues': len(c.get("lues") or []) if c else 0,
            'outils': len(d.get("outils") or []),
            'date': str((c or {}).get("fin") or (c or {}).get("debut")
                        or "")}


def constituer(chemin: str, progression: Callable = None,
               lire_url: Callable = None, pause: float = PAUSE,
               attendre: Callable = time.sleep) -> Dict:
    """Constitue (ou complète, ou reprend) le catalogue de `chemin`.

    `progression(fraction, texte) -> bool`: False arrête — le travail
    fait est enregistré, la prochaine fois reprend là (vcarve.Annule
    est levée). Rend le bilan: {'plan', 'lues', 'ajoutees',
    'mises_a_jour', 'hors_catalogue', 'erreurs', 'outils'}."""
    from src.core import vcarve
    from src.core.fichiers_surs import ecrire_json_sur, lire_json
    lire = _lire(lire_url)
    maintenant = datetime.now().isoformat(timespec="seconds")
    if progression is not None and not progression(
            0.0, "plan du webshop…"):
        raise vcarve.Annule()
    fiches = plan(lire)
    if not fiches:
        raise OSError("le plan du webshop ne liste aucune fiche")

    existant = lire_json(chemin)
    if not isinstance(existant, dict) or not isinstance(
            existant.get("outils"), list):
        existant = _squelette(maintenant)
    donnees = dict(existant)
    constitution = donnees.get("_constitution")
    if not isinstance(constitution, dict) or constitution.get("complet"):
        # une nouvelle passe: le catalogue d'avant est sauvegardé
        constitution = {"debut": maintenant, "complet": False, "lues": []}
        premiere = True
    else:
        premiere = False                # on reprend
    donnees["_constitution"] = constitution
    for cle, valeur in (("categories", CATEGORIES), ("colonnes", COLONNES)):
        fusion = dict(valeur)
        fusion.update(donnees.get(cle) or {})
        donnees[cle] = fusion
    donnees.setdefault("sources", _squelette(maintenant)["sources"])
    outils = [o for o in donnees.get("outils", [])
              if isinstance(o, dict) and o.get("ref")]
    par_ref = {str(o["ref"]).upper(): o for o in outils}
    lues = [str(r).upper() for r in constitution.get("lues") or []]
    deja = set(lues)
    bilan = {'plan': len(fiches), 'lues': 0, 'ajoutees': 0,
             'mises_a_jour': 0, 'hors_catalogue': 0, 'erreurs': [],
             'outils': len(outils), 'repris': len(deja)}

    def enregistrer(fin: bool = False):
        nonlocal premiere
        constitution["lues"] = lues
        if fin:
            constitution["complet"] = True
            constitution["fin"] = datetime.now().isoformat(
                timespec="seconds")
            constitution.pop("lues", None)
        donnees["outils"] = outils
        ecrire_json_sur(chemin, donnees, garder_bak=premiere, indent=1,
                        ensure_ascii=False)
        premiere = False

    n = len(fiches)
    depuis = 0
    suite = 0                           # erreurs de suite
    for i, (ref, adresse, rubrique) in enumerate(fiches):
        if ref in deja:
            continue
        if progression is not None and not progression(
                i / n, f"{ref} ({i + 1}/{n})"):
            enregistrer()
            raise vcarve.Annule()
        try:
            x = entree(lire(adresse), ref, rubrique)
        except OSError as exc:
            bilan['erreurs'].append(f"{ref}: {exc}")
            suite += 1
            if suite >= ERREURS_DE_SUITE:
                # le réseau est tombé: ce qui est lu est gardé, la
                # prochaine fois reprend là
                enregistrer()
                raise OSError(f"webshop injoignable ({exc}) — "
                              f"{bilan['lues']} fiche(s) lue(s), "
                              "relancer pour reprendre")
        else:
            suite = 0
            bilan['lues'] += 1
            lues.append(ref)
            deja.add(ref)
            if x is None:
                bilan['hors_catalogue'] += 1
            elif ref in par_ref:
                par_ref[ref].update(x)
                bilan['mises_a_jour'] += 1
            else:
                outils.append(x)
                par_ref[ref] = x
                bilan['ajoutees'] += 1
        depuis += 1
        if depuis >= ENREGISTRER:
            enregistrer()
            depuis = 0
        if pause:
            attendre(pause)
    if bilan['erreurs']:
        enregistrer()                   # incomplet: la reprise relira
    else:
        enregistrer(fin=True)
    if progression is not None:
        progression(1.0, "catalogue constitué")
    bilan['outils'] = len(outils)
    bilan['complet'] = not bilan['erreurs']
    return bilan


def resume(bilan: Dict) -> str:
    """Le bilan en une phrase."""
    morceaux = [f"{bilan['outils']} références au catalogue"]
    if bilan.get('ajoutees'):
        morceaux.append(f"{bilan['ajoutees']} nouvelle(s)")
    if bilan.get('mises_a_jour'):
        morceaux.append(f"{bilan['mises_a_jour']} mise(s) à jour")
    if bilan.get('repris'):
        morceaux.append(f"reprise après {bilan['repris']} fiche(s)")
    if bilan.get('erreurs'):
        morceaux.append(f"{len(bilan['erreurs'])} fiche(s) non lue(s): "
                        "relancer pour les reprendre")
    return "webshop DATRON: " + ", ".join(morceaux) + "."
