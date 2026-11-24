"""Catalogue d'outils DATRON hors ligne (data/catalogue_datron.json).

NeoDrive ne le livre pas: ces données appartiennent à DATRON AG. Le
catalogue se CONSTITUE sur le poste de l'utilisateur, à sa demande,
depuis les fiches publiques du webshop DATRON (`constitution_datron`):
références, familles, cotes (mm), angles, rayons, filetages, prix. Il
reste à côté de l'exe, pour son usage; les documents DATRON font foi.
Le catalogue ne contient AUCUNE donnée de coupe: les avances viennent
de `coupe_datron` (modèle, ou guide PDF de l'utilisateur).

Ce module dit, pour une référence: sa fiche @ ToolDescription @, le
nom et le type que l'atelier lui donnerait, et le bloc
« constructeur » que tools.json garde à côté des réglages de
l'utilisateur.
"""

import os
import re
from datetime import datetime

from src.core.coupe_datron import BROCHE_DEFAUT, avec_avances, proposer

#: les cotes qu'une fiche constructeur garde, telles que le catalogue
#: les donne
COTES = ("D1", "D2", "D3", "L1", "L2", "L3", "angle", "R", "dents",
         "pas", "filetage", "prepercage", "longueur_utile")

LIBELLES_COTES = {
    "D1": "Ø de coupe", "D2": "Ø de queue", "D3": "Ø de dégagement",
    "L1": "longueur totale", "L2": "longueur de coupe",
    "L3": "longueur de dégagement", "angle": "angle (°)",
    "R": "rayon", "dents": "dents", "pas": "pas", "filetage": "filetage",
    "prepercage": "Ø de pré-perçage", "longueur_utile": "longueur utile",
}

#: les avances qu'une proposition DATRON renseigne
CHAMPS_AVANCES = ("rpm", "feed_roughing", "feed_finishing", "feed_plunge",
                  "feed_ramp")

FICHE_WEBSHOP = "https://webshop.datron.de/search?search={ref}"


def chemin_catalogue() -> str:
    from src.core.tool_library import get_base_dir
    return os.path.join(get_base_dir(), "data", "catalogue_datron.json")


def _g(v) -> str:
    """« 3 », « 2.5 », « 0.6 »: un nombre comme l'atelier l'écrit."""
    try:
        return f"{float(v):g}"
    except (TypeError, ValueError):
        return str(v)


def d_max(x: dict):
    """Le grand Ø (chanfrein, rayon): D3 s'il existe, sinon D1."""
    return x.get("D3") or x.get("D1")


def est_pointe(x: dict) -> bool:
    return (x.get("categorie") == "conique"
            and str(x.get("famille", "")).startswith("Pointe"))


def tailles_filetage(texte: str) -> list:
    """« M2.5 - M3 » → [2.5, 3.0]; « M1,4 » → [1.4]; « PG7 » → []."""
    return [float(v.replace(",", "."))
            for v in re.findall(r"M\s*(\d+(?:[.,]\d+)?)", str(texte or ""))]


def type_atelier(x: dict) -> str:
    """Le type NeoDrive (`type_taraudage`) — celui qui range l'outil
    dans les listes des opérations: Cyl3, Con30, Drill, Chamfer,
    ExtRad, M4…"""
    cat = x.get("categorie")
    if cat in ("fraise", "surfacage", "boule", "torique"):
        return f"Cyl{_g(x.get('D1'))}"
    if cat == "conique":
        return f"Con{_g(x.get('angle') or 0)}"
    if cat == "chanfrein":
        return "Chamfer"
    if cat == "foret":
        return "Drill"
    if cat == "rayon":
        return "ExtRad"
    if cat == "filetage":
        from src.operations.taraudage import THREAD_TYPES
        tailles = tailles_filetage(x.get("filetage"))
        if tailles:
            lo, hi = min(tailles), max(tailles)
            # le plus petit filet de la plage que les opérations
            # de taraudage connaissent
            for t in THREAD_TYPES:
                if lo - 1e-9 <= float(t[1:]) <= hi + 1e-9:
                    return t
            return f"M{_g(lo)}"
        return "M"
    return f"Cyl{_g(x.get('D1'))}"


def longueur_utile(x: dict):
    """La longueur UTILE (jusqu'à l'épaulement): le dégagement L3,
    sinon la longueur utile du filetage, sinon la longueur de coupe —
    c'est le « L » des noms de l'atelier."""
    for cle in ("L3", "longueur_utile", "L2"):
        if x.get(cle):
            return float(x[cle])
    return None


def nom_atelier(x: dict) -> str:
    """Le nom à la manière de la bibliothèque de l'atelier:
    « Cyl 3 z1L10 », « Con 30° 0.6 », « Foret Ø4.2 L21 »,
    « Chamfer 90° z3L3 », « ExtRad 6 z2 r2 », « Thr M2.5-M3 ».
    `geometrie_depuis_nom` le relit."""
    cat = x.get("categorie")
    z = x.get("dents")
    lu = longueur_utile(x)
    # le « L » de l'atelier est la longueur UTILE: « Cyl 8 z1L41 »
    zl = (f" z{int(z)}" if z else "") + (f"L{_g(lu)}" if lu else "")
    if cat in ("fraise", "surfacage"):
        return f"Cyl {_g(x.get('D1'))}{zl}".strip()
    if cat == "boule":
        return f"Ball {_g(x.get('D1'))}{zl}".strip()
    if cat == "torique":
        r = f" r{_g(x['R'])}" if x.get("R") else ""
        return f"Tor {_g(x.get('D1'))}{zl}{r}".strip()
    if cat == "conique":
        if est_pointe(x):
            return f"Con {_g(x.get('angle') or 0)}° {_g(x.get('D1'))}"
        return f"Con {_g(x.get('angle') or 0)}° Ø{_g(x.get('D1'))}"
    if cat == "chanfrein":
        if str(x.get("famille", "")).startswith("Outil de lamage"):
            return f"Lamage {_g(x.get('angle') or 0)}° Ø{_g(d_max(x))}"
        return f"Chamfer {_g(x.get('angle') or 0)}°{zl}"
    if cat == "foret":
        lg = f" L{_g(lu)}" if lu else ""
        return f"Foret Ø{_g(x.get('D1'))}{lg}"
    if cat == "rayon":
        z_ = f" z{int(z)}" if z else ""
        return f"ExtRad {_g(d_max(x))}{z_} r{_g(x.get('R'))}"
    if cat == "filetage":
        fil = re.sub(r"\s*-\s*", "-", str(x.get("filetage") or ""))
        return f"Thr {fil.replace(',', '.')}".strip()
    return f"{x.get('famille', 'Outil')} {x.get('ref', '')}".strip()


def geometrie(x: dict) -> dict:
    """La fiche @ ToolDescription @ que le catalogue permet de remplir
    (champs Datron). Rien n'est inventé: une cote absente du catalogue
    reste absente de la fiche."""
    cat = x.get("categorie")
    g = {}

    def mettre(cle, val, conv=float):
        if val in (None, ""):
            return
        try:
            g[cle] = conv(val)
        except (TypeError, ValueError):
            pass

    if cat == "conique":
        if est_pointe(x):
            mettre("Diameter", x.get("D2"))
            mettre("TipDiameter", x.get("D1"))
        else:
            mettre("Diameter", x.get("D1"))
        mettre("TipAngle", x.get("angle"))
    elif cat in ("chanfrein", "rayon"):
        mettre("Diameter", d_max(x))
        if cat == "chanfrein":
            mettre("TipAngle", x.get("angle"))
            if x.get("D3"):
                mettre("TipDiameter", x.get("D1"))
        else:
            mettre("CornerRadius", x.get("R"))
    else:
        mettre("Diameter", x.get("D1"))
        if cat == "foret":
            mettre("TipAngle", x.get("angle"))
        if cat == "boule":
            mettre("CornerRadius",
                   x.get("R") if x.get("R") else
                   (float(x["D1"]) / 2 if x.get("D1") else None))
        elif cat in ("torique", "surfacage"):
            mettre("CornerRadius", x.get("R"))
        # D3 est ici le Ø de DÉGAGEMENT (col), et L3 sa longueur
        mettre("ShoulderDiameter", x.get("D3"))
    # L coupe (FluteLength) et L utile (ShoulderLength, jusqu'à
    # l'épaulement): sans dégagement, la longueur utile est celle de
    # coupe
    mettre("FluteLength", x.get("L2"))
    mettre("ShoulderLength", longueur_utile(x))
    mettre("NumberOfFlutes", x.get("dents"), int)
    mettre("ShaftDiameter", x.get("D2"))
    mettre("OverallLength", x.get("L1"))
    mettre("ThreadPitch", x.get("pas"))
    return g


def profondeur_max(x: dict):
    """La profondeur que l'outil atteint: sa longueur utile."""
    return longueur_utile(x)


class Catalogue:
    """Le catalogue, lu une fois."""

    def __init__(self, chemin: str = None):
        self.chemin = chemin or chemin_catalogue()
        self.outils = []
        self.categories = {}
        self.colonnes = {}
        self.sources = {}
        self.erreur = ""
        self._par_ref = {}
        self.charger()

    def charger(self):
        import json
        self.erreur = ""
        try:
            with open(self.chemin, encoding="utf-8") as f:
                d = json.load(f)
        except FileNotFoundError:
            self.erreur = f"catalogue absent: {self.chemin}"
            return
        except (OSError, ValueError) as e:
            self.erreur = f"catalogue illisible ({e})"
            return
        self.outils = [o for o in d.get("outils", [])
                       if isinstance(o, dict) and o.get("ref")]
        # les cotes lues sur le webshop (« Mettre à jour depuis
        # datron.de »), superposées au catalogue livré
        try:
            from src.core import maj_datron
            maj_datron.superposer(
                self.outils, maj_datron.lire_maj(
                    maj_datron.chemin_maj(self.chemin)))
        except Exception:
            pass
        self.categories = dict(d.get("categories", {}))
        self.colonnes = dict(d.get("colonnes", {}))
        self.sources = dict(d.get("sources", {}))
        self._par_ref = {str(o["ref"]).upper(): o for o in self.outils}

    def __len__(self):
        return len(self.outils)

    def entree(self, ref: str):
        """L'outil du catalogue pour une référence (« 0068030E »,
        « 0068443G / 114206 »…), ou None."""
        from src.core.tool_library import extract_article_nr
        cle = extract_article_nr(str(ref or "")).upper()
        return self._par_ref.get(cle) if cle else None

    def chercher(self, texte: str = "", categorie: str = "",
                 diametre=None, dents=None, l2_min=None) -> list:
        """Les outils qui passent les filtres — la recherche porte sur
        la référence, la famille, le filetage et la désignation."""
        q = re.sub(r"\s+", "", str(texte or "")).lower()
        res = []
        for x in self.outils:
            if categorie and x.get("categorie") != categorie:
                continue
            if diametre is not None and abs(
                    float(x.get("D1") or 0) - float(diametre)) > 1e-6:
                continue
            if dents is not None and x.get("dents") != dents:
                continue
            if l2_min is not None and not (
                    float(x.get("L2") or 0) >= float(l2_min)):
                continue
            if q:
                botte = "".join(str(x.get(k) or "") for k in (
                    "ref", "famille", "filetage", "designation_de"))
                if q not in re.sub(r"\s+", "", botte).lower():
                    continue
            res.append(x)
        return res

    def fiche_constructeur(self, x: dict, broche: str = BROCHE_DEFAUT,
                           guide=None) -> dict:
        """Le bloc « constructeur » de tools.json pour un outil du
        catalogue: ses cotes, sa famille, son prix et — pour les
        fraises 1 dent — les avances DATRON recommandées."""
        fiche = {
            "ref": x.get("ref"),
            "categorie": x.get("categorie"),
            "famille": x.get("famille"),
            "cotes": {k: x[k] for k in COTES if x.get(k) not in
                      (None, "")},
            "importe_le": datetime.now().isoformat(timespec="seconds"),
        }
        for src, dst in (("designation_de", "designation"),
                         ("prix_eur", "prix_eur"),
                         ("groupe_prix", "groupe_prix"),
                         ("page_catalogue", "page_catalogue")):
            if x.get(src) not in (None, ""):
                fiche[dst] = x[src]
        coupe = self.avances(x, broche, guide)
        if coupe:
            fiche["coupe"] = coupe
        return fiche

    def avances(self, x: dict, broche: str = BROCHE_DEFAUT,
                guide=None):
        """Rotation et avances DATRON pour un outil du catalogue, au
        format des champs de tools.json — None quand DATRON n'en
        recommande pas (tout ce qui n'est pas une fraise 1 dent)."""
        if not avec_avances(x.get("categorie"), x.get("dents")):
            return None
        p = proposer(x.get("D1"), x.get("L2"), x.get("dents") or 1,
                     x.get("ref"), broche=broche, guide=guide)
        if not p.get("ok"):
            return None
        f = p["feeds"]
        return {
            "rpm": p["rpm"], "feed_roughing": f["roughing"],
            "feed_finishing": f["finishing"], "feed_plunge": f["plunge"],
            "feed_ramp": f["ramp"], "source": p["coupe"]["source"],
            "libelle_source": p["source"], "broche": broche,
            "matiere": "aluminium 200–400 N/mm²",
            "rainurage": p["coupe"]["rainurage"],
            "lateral": p["coupe"]["lateral"], "notes": p["notes"],
        }

    def donnees_outil(self, x: dict, broche: str = BROCHE_DEFAUT,
                      guide=None) -> dict:
        """Un outil NeoDrive complet (dict de tools.json) tiré du
        catalogue. Avec les avances DATRON s'il y en a; sinon celles
        par défaut, à régler — la note le dit."""
        fiche = self.fiche_constructeur(x, broche, guide)
        geo = geometrie(x)
        donnees = {
            "name": nom_atelier(x),
            "reference": str(x.get("ref")),
            "type_taraudage": type_atelier(x),
            "vendor": "DATRON",
            "diameter": float(geo.get("Diameter") or 0.0),
            "geometry": geo,
            "constructeur": fiche,
        }
        pmax = profondeur_max(x)
        if pmax:
            donnees["max_depth"] = pmax
        coupe = fiche.get("coupe")
        if coupe:
            for k in CHAMPS_AVANCES:
                donnees[k] = coupe[k]
            # pas de valeur DATRON pour l'approche: jamais plus vite
            # que l'ébauche
            donnees["feed_approach"] = coupe["feed_roughing"]
            donnees["notes"] = (f"Avances DATRON ({coupe['libelle_source']}"
                                f", broche {broche}) — à valider")
        else:
            donnees["notes"] = ("Catalogue DATRON — aucune avance "
                                "recommandée pour ce type d'outil: à régler")
        return donnees


_CATALOGUE = None


def catalogue() -> Catalogue:
    """Le catalogue de l'application, lu au premier besoin."""
    global _CATALOGUE
    if _CATALOGUE is None:
        _CATALOGUE = Catalogue()
    return _CATALOGUE


def milliers(v) -> str:
    """38000 → « 38 000 »."""
    try:
        return f"{int(round(float(v))):,}".replace(",", " ")
    except (TypeError, ValueError):
        return str(v)


def resume_avances(coupe: dict) -> str:
    """« 38 000 tr/min, ébauche 4 180, finition 3 800, plongée 1 050,
    rampe 4 180 mm/min (guide DATRON (réf. …), broche 2 kW neo) »."""
    return (f"{milliers(coupe['rpm'])} tr/min, ébauche "
            f"{milliers(coupe['feed_roughing'])}, finition "
            f"{milliers(coupe['feed_finishing'])}, plongée "
            f"{milliers(coupe['feed_plunge'])}, rampe "
            f"{milliers(coupe['feed_ramp'])} mm/min "
            f"({coupe.get('libelle_source', '')}, broche "
            f"{coupe.get('broche', '')})")


def resume_import(rapport: dict, tool_library) -> str:
    """Ce que le bouton « DATRON » a fait, en une phrase lisible."""
    if not rapport.get("ok"):
        return f"✗ {rapport.get('raison', 'import impossible')}"
    from src.core.tool_library import Tool
    libelles = dict(Tool.GEOMETRY_LABELS)
    outil = tool_library.tools.get(rapport["outil"])
    nom = outil.display_name if outil else rapport["outil"]
    morceaux = [f"{nom}: données constructeur importées"]
    if rapport.get("completes"):
        morceaux.append("fiche complétée (" + ", ".join(
            libelles.get(c, c) for c in rapport["completes"]) + ")")
    coupe = rapport.get("coupe")
    if coupe:
        if rapport.get("jumeau_cree"):
            quoi = "jumeau « avances DATRON » créé"
        elif rapport.get("jumeau"):
            quoi = "jumeau « avances DATRON » mis à jour"
        else:
            quoi = "avances DATRON mises à jour sur cette fiche"
        morceaux.append(f"{quoi}: {resume_avances(coupe)}")
    else:
        morceaux.append("pas d'avances constructeur pour ce type d'outil "
                        "(DATRON ne chiffre que les fraises 1 dent) — "
                        "les vôtres restent")
    if rapport.get("ecarts"):
        morceaux.append("⚠ écarts fiche ≠ catalogue, à vérifier: " + "; ".join(
            f"{libelles.get(c, c)} {_g(a)} ≠ {_g(b)}"
            for c, a, b in rapport["ecarts"]))
    return " — ".join(morceaux)
