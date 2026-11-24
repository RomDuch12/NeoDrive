"""Données de coupe des fraises 1 dent DATRON (aluminium 200–400 N/mm²).

Portage de `coupe.js` (romduch12.github.io), en deux sources:

1. le MODÈLE: coefficients ajustés sur le « DATRON High-Speed Cutting
   Guide » (régression log-log sur D1 et L2/D1, par broche et par
   stratégie) — valeurs indicatives, pour toute fraise 1 dent;
2. les valeurs EXACTES, lues dans l'exemplaire du guide (PDF) que
   l'utilisateur a sur son disque. Rien n'est publié: le résultat de
   la lecture reste dans `data/coupe_datron_guide.json`, chez lui.

Guide officiel:
https://www.datron.com/wp-content/uploads/2022/11/DATRON-High-Speed-Cutting-Guide.pdf
"""

import math
import os
import re
from datetime import datetime

GUIDE_URL = ("https://www.datron.com/wp-content/uploads/2022/11/"
             "DATRON-High-Speed-Cutting-Guide.pdf")

#: grandeur = exp(c0 + c1·ln D1 + c2·ln(L2/D1)); n plafonnée à n_max
MODEL = {
    "1,8 kW": {
        "plein": {"n": [10.7761, -0.1886, -0.0285], "n_max": 46000,
                  "fz": [-3.3063, 0.7925, -0.2705],
                  "ap": [-0.0819, 0.2343, -0.6636], "ae": [0.0, 1.0, 0.0],
                  "d": [0.3, 10.0], "l2d": [1.0, 7.5]},
        "partiel": {"n": [10.7761, -0.1886, -0.0285], "n_max": 46000,
                    "fz": [-3.2926, 0.8145, -0.4526],
                    "ap": [-0.3567, 1.0975, 1.1047],
                    "ae": [-0.7673, 0.3391, -0.9099],
                    "d": [0.3, 10.0], "l2d": [1.0, 7.5]}},
    "2 kW": {
        "plein": {"n": [10.9129, -0.1524, -0.0289], "n_max": 52000,
                  "fz": [-3.4546, 0.9194, -0.2985],
                  "ap": [-0.2639, 0.2403, -0.5648], "ae": [0.0, 1.0, 0.0],
                  "d": [0.3, 8.0], "l2d": [1.1, 7.5]},
        "partiel": {"n": [10.913, -0.1368, -0.0355], "n_max": 52000,
                    "fz": [-3.4228, 0.8836, -0.5358],
                    "ap": [-0.3656, 1.1002, 1.1108],
                    "ae": [-1.0929, 0.4064, -0.7272],
                    "d": [0.3, 8.0], "l2d": [1.0, 7.5]}},
    "2 kW neo": {
        "plein": {"n": [10.6576, -0.1293, -0.0223], "n_max": 40000,
                  "fz": [-3.2589, 0.8455, -0.2417],
                  "ap": [-0.1363, 0.2951, -0.6559], "ae": [0.0, 1.0, 0.0],
                  "d": [0.3, 8.0], "l2d": [1.0, 7.5]},
        "partiel": {"n": [10.6576, -0.1293, -0.0223], "n_max": 40000,
                    "fz": [-3.2356, 0.8538, -0.483],
                    "ap": [-0.3656, 1.1002, 1.1108],
                    "ae": [-0.9849, 0.4727, -0.8054],
                    "d": [0.3, 8.0], "l2d": [1.0, 7.5]}},
    "3 kW": {
        "plein": {"n": [10.6753, -0.1369, -0.033], "n_max": 40000,
                  "fz": [-3.2035, 0.7852, -0.2473],
                  "ap": [-0.0379, 0.379, -0.6714], "ae": [0.0, 1.0, 0.0],
                  "d": [0.3, 10.0], "l2d": [1.0, 7.5]},
        "partiel": {"n": [10.6753, -0.1369, -0.033], "n_max": 40000,
                    "fz": [-3.2516, 0.8518, -0.423],
                    "ap": [-0.3567, 1.0975, 1.1047],
                    "ae": [-0.6944, 0.5071, -1.043],
                    "d": [0.3, 10.0], "l2d": [1.0, 7.5]}},
    "4 kW": {
        "plein": {"n": [10.6753, -0.1369, -0.033], "n_max": 40000,
                  "fz": [-3.1766, 0.8133, -0.2614],
                  "ap": [-0.0222, 0.3778, -0.6841], "ae": [0.0, 1.0, 0.0],
                  "d": [0.3, 10.0], "l2d": [1.0, 7.5]},
        "partiel": {"n": [10.6753, -0.1369, -0.033], "n_max": 40000,
                    "fz": [-3.243, 0.8681, -0.4232],
                    "ap": [-0.3567, 1.0975, 1.1047],
                    "ae": [-0.674, 0.5351, -1.0487],
                    "d": [0.3, 10.0], "l2d": [1.0, 7.5]}},
    "8 kW": {
        "plein": {"n": [10.5103, -0.0759, -0.0333], "n_max": 34000,
                  "fz": [-3.0605, 0.7653, -0.2139],
                  "ap": [-0.0046, 0.4829, -0.5802], "ae": [0.0, 1.0, 0.0],
                  "d": [0.3, 12.0], "l2d": [1.0, 7.5]},
        "partiel": {"n": [10.5103, -0.0759, -0.0333], "n_max": 34000,
                    "fz": [-3.1567, 0.8021, -0.3485],
                    "ap": [-0.352, 1.0964, 1.1014],
                    "ae": [-0.549, 0.5486, -0.99],
                    "d": [0.3, 12.0], "l2d": [1.0, 7.5]}},
}
BROCHES = tuple(MODEL)
BROCHE_DEFAUT = "2 kW neo"

#: première page des tableaux de chaque broche dans le guide:
#: 3 pages « plein » (rainurage) puis 3 pages « partiel » (latéral)
PAGES = {"1,8 kW": 20, "2 kW": 28, "2 kW neo": 36, "3 kW": 44,
         "4 kW": 52, "8 kW": 60}
#: pages des cotes des outils
PAGES_COTES = range(12, 19)

STRATEGIES = {"plein": "rainurage (pleine matière, ae = Ø)",
              "partiel": "fraisage latéral (ae partiel)"}

_ART = r"(0[0-9]{3}\d{3}[A-Z])"


def _arrondi(v: float, d: int = 0) -> float:
    """Math.round de JavaScript (le demi va vers +∞), à d décimales —
    d négatif arrondit à la dizaine, la centaine…: les valeurs restent
    celles du site."""
    k = 10 ** d
    r = math.floor(v * k + 0.5) / k
    return int(r) if d <= 0 else r


def _ev(c, d, r):
    return math.exp(c[0] + c[1] * math.log(d) + c[2] * math.log(r))


def calc(diametre, longueur_coupe=None, dents=1, broche=BROCHE_DEFAUT,
         strat="plein", matiere="alu"):
    """Valeurs du MODÈLE pour une fraise 1 dent: n, fz, vf, ap, ae,
    vc, q, notes. None sans diamètre."""
    try:
        d = float(diametre)
    except (TypeError, ValueError):
        return None
    if not d > 0:
        return None
    m = (MODEL.get(broche) or MODEL[BROCHE_DEFAUT])[strat]
    try:
        l2 = float(longueur_coupe) if longueur_coupe else 3 * d
    except (TypeError, ValueError):
        l2 = 3 * d
    z = max(1, int(dents or 1))
    notes = []
    if d < m["d"][0] or d > m["d"][1]:
        notes.append(f"Ø{d:g} hors de la plage du guide "
                     f"({m['d'][0]:g}–{m['d'][1]:g} mm): extrapolation.")
    r = min(max(l2 / d, m["l2d"][0]), m["l2d"][1])
    n = min(m["n_max"], _ev(m["n"], d, r))
    fz = _ev(m["fz"], d, r)
    ap = min(_ev(m["ap"], d, r), l2)
    ae = min(_ev(m["ae"], d, r), d)
    if z > 1:
        notes.append(f"Données établies pour des fraises 1 dent: avance "
                     f"calculée pour {z} dents, à valider.")
    if matiere == "alu-tendre":
        n *= 0.8
    if matiere == "alu-dur":
        ap *= 0.85
        ae *= 0.85
    if matiere == "autre":
        notes.append("Le guide ne chiffre que l'aluminium: valeurs de "
                     "départ à valider par essai.")
    if d >= 5 and l2 > 4 * d:
        n *= 0.8
        fz *= 0.8
        ap *= 0.8
        ae *= 0.8
        notes.append("Ø ≥ 5 et L2 > 4×Ø: paramètres réduits de 20 % "
                     "(risque de vibrations).")
    vf = n * fz * z
    return {"n": _arrondi(n, -2), "fz": _arrondi(fz, 4),
            "vf": _arrondi(vf, -1), "ap": _arrondi(ap, 2),
            "ae": _arrondi(ae, 2), "vc": _arrondi(math.pi * d * n / 1000),
            "q": _arrondi(ap * ae * vf / 1000, 2), "source": "modèle",
            "notes": notes}


# ── Le guide PDF de l'utilisateur ─────────────────────────────────

def _texte_page(lecteur, numero: int, mode: str = "plain") -> str:
    """Le texte d'une page (numérotée à partir de 1), en une ligne.

    pypdf coupe parfois les nombres au milieu (« 7 ,30 », « 11. 5 »,
    « 1 7.0 » pour 17.0): on les recolle, sinon la ligne du tableau
    ne se lit plus. Le mode « layout » garde mieux les tableaux de
    coupe (« 0,110 » au lieu de « 0,1 10 »)."""
    import logging
    try:
        page = lecteur.pages[numero - 1]
        if mode == "layout":
            # « Rotated text discovered »: le texte tourné des marges
            # ne nous sert pas — pypdf le dit en avertissement
            journal = logging.getLogger("pypdf")
            niveau = journal.level
            journal.setLevel(logging.ERROR)
            try:
                brut = page.extract_text(extraction_mode="layout") or ""
            finally:
                journal.setLevel(niveau)
        else:
            brut = page.extract_text() or ""
    except Exception:
        return ""
    t = re.sub(r"\s+", " ", brut)
    t = re.sub(r"(\d) ([,.])(?=\d)", r"\1\2", t)
    t = re.sub(r"(\d[,.]) (\d)", r"\1\2", t)
    return t


def _recoller_cotes(t: str) -> str:
    """Pages des cotes: toutes les valeurs y sont décimales (« 8.0 »);
    un chiffre seul devant un décimal est le début coupé du nombre
    (« 1 7.0 » → « 17.0 »)."""
    return re.sub(r"(?<![\d.,])(\d) (?=\d+\.\d)", r"\1", t)


def _nombre(s: str) -> float:
    return float(s.replace(",", "."))


_LIGNE_COUPE = re.compile(
    _ART + r"\s+(\d+(?:,\d+)?)\s+([1-4])\s+(\d{2,4})\s+(\d{4,5})"
    r"\s+(0,\d{2,4})\s+(\d{2,5})\s+(\d{1,2},\d{1,2})\s+(\d{1,2},\d{1,2})")
_LIGNE_COTES = re.compile(_ART + r"((?:\s+\d+\.\d+)+)")


def lire_guide(chemin: str, progression=None) -> dict:
    """Lit les tableaux du guide: {réf: {D1, D2, L1, L2, rows:[{broche,
    strat, D, z, vc, n, fz, vf, ap, ae}]}}.

    Lève ValueError si aucun tableau n'est reconnu (ce n'est pas le
    guide). `progression(fraction, texte)` suit la lecture et peut
    annuler (voir vcarve.avancer)."""
    from src.core import vcarve
    try:
        from pypdf import PdfReader
    except ImportError:
        if isinstance(chemin, (str, os.PathLike)):
            raise ValueError("lecture PDF indisponible: le module "
                             "« pypdf » manque") from None
    # un chemin, ou un lecteur déjà ouvert (les tests en fabriquent un)
    lecteur = (PdfReader(chemin) if isinstance(chemin, (str, os.PathLike))
               else chemin)
    refs = {}
    pages = [(p, None, None) for p in PAGES_COTES]
    for broche, p0 in PAGES.items():
        pages += [(p0 + k, broche, "plein" if k < 3 else "partiel")
                  for k in range(6)]
    total = len(pages)
    for i, (page, broche, strat) in enumerate(pages):
        vcarve.avancer(progression, i / total,
                       f"Guide DATRON, page {page}…")
        if broche is None:
            texte = _recoller_cotes(_texte_page(lecteur, page))
            for m in _LIGNE_COTES.finditer(texte):
                v = [float(x) for x in m.group(2).split()]
                if len(v) < 4:
                    continue
                reste = v[2:]
                if len(reste) >= 3 and reste[0] < v[1]:
                    reste = reste[1:]        # un Ø de dégagement D3
                cotes = {"D1": v[0], "D2": v[1], "L1": reste[0],
                         "L2": reste[1]}
                if len(reste) >= 3:
                    cotes["L3"] = reste[2]
                ref = refs.setdefault(m.group(1), {"rows": []})
                for cle, val in cotes.items():
                    ref.setdefault(cle, val)
            continue
        # Aucun des deux modes de pypdf ne lit TOUTES les lignes: on
        # prend les deux, et une ligne n'entre que si elle se tient
        # (vf = n × fz × z à 3 % près) — un nombre mal recollé la
        # rendrait fausse, elle est écartée.
        for mode in ("layout", "plain"):
            texte = _texte_page(lecteur, page, mode)
            for m in _LIGNE_COUPE.finditer(texte):
                ligne = {
                    "broche": broche, "strat": strat,
                    "D": _nombre(m.group(2)), "z": int(m.group(3)),
                    "vc": _nombre(m.group(4)), "n": _nombre(m.group(5)),
                    "fz": _nombre(m.group(6)), "vf": _nombre(m.group(7)),
                    "ap": _nombre(m.group(8)), "ae": _nombre(m.group(9))}
                calcul = ligne["n"] * ligne["fz"] * ligne["z"]
                if not ligne["vf"] or abs(calcul - ligne["vf"]) > (
                        0.03 * ligne["vf"]):
                    continue
                ref = refs.setdefault(
                    m.group(1), {"D1": ligne["D"], "rows": []})
                if any(r["broche"] == broche and r["strat"] == strat
                       for r in ref["rows"]):
                    continue
                ref["rows"].append(ligne)
    vcarve.avancer(progression, 1.0, "Guide DATRON lu")
    if not any(r["rows"] for r in refs.values()):
        raise ValueError("aucun tableau reconnu: est-ce bien le « DATRON "
                         "High-Speed Cutting Guide » ?")
    return refs


def chemin_cache() -> str:
    from src.core.tool_library import get_base_dir
    return os.path.join(get_base_dir(), "data", "coupe_datron_guide.json")


class Guide:
    """Les valeurs du guide lues une fois, gardées dans data/."""

    def __init__(self, chemin: str = None):
        self.chemin = chemin or chemin_cache()
        self.refs = {}
        self.date = ""
        self.source = ""
        self.charger()

    def charger(self):
        from src.core.fichiers_surs import lire_json_sur
        if not os.path.isfile(self.chemin):
            return
        donnees, _alerte = lire_json_sur(self.chemin)
        if isinstance(donnees, dict) and isinstance(
                donnees.get("refs"), dict):
            self.refs = donnees["refs"]
            self.date = str(donnees.get("date", ""))
            self.source = str(donnees.get("source", ""))

    def importer(self, chemin_pdf: str, progression=None) -> int:
        """Lit le PDF et garde le résultat; rend le nombre de
        références chiffrées."""
        from src.core.fichiers_surs import ecrire_json_sur
        refs = lire_guide(chemin_pdf, progression)
        self.refs = refs
        self.date = datetime.now().isoformat(timespec="seconds")
        self.source = (os.path.basename(chemin_pdf)
                       if isinstance(chemin_pdf, (str, os.PathLike))
                       else "guide")
        ecrire_json_sur(self.chemin, {
            "_info": "Valeurs lues dans le DATRON High-Speed Cutting "
                     "Guide de l'utilisateur — données DATRON AG, "
                     "à usage local.",
            "date": self.date, "source": self.source, "refs": refs},
            indent=1, ensure_ascii=False)
        return self.nb_refs()

    def nb_refs(self) -> int:
        return sum(1 for r in self.refs.values() if r.get("rows"))

    def exact(self, ref: str):
        return self.refs.get(str(ref or "").upper()) if ref else None


def avec_avances(categorie: str, dents) -> bool:
    """Le guide (et donc le modèle) ne chiffre que les fraises 1 dent:
    les autres outils n'ont pas d'avances constructeur."""
    try:
        z = int(dents or 1)
    except (TypeError, ValueError):
        z = 1
    return categorie == "fraise" and z == 1


def proposer(diametre, longueur_coupe=None, dents=1, ref="",
             broche=BROCHE_DEFAUT, matiere="alu", guide=None) -> dict:
    """Rotation et avances DATRON pour une fraise: celles du guide si
    la référence y est, sinon celles du modèle.

    {ok, rpm, feeds{roughing, finishing, plunge, ramp}, coupe{...},
    source, notes} — ou {ok: False, raison}."""
    ex = guide.exact(ref) if guide is not None else None

    def choisir(strat):
        row = None
        if ex:
            row = next((r for r in ex.get("rows", [])
                        if r["broche"] == broche and r["strat"] == strat),
                       None)
        if row:
            res = {"n": row["n"], "fz": row["fz"], "vf": row["vf"],
                   "ap": row["ap"], "ae": row["ae"], "vc": row["vc"],
                   "source": "guide", "notes": []}
            if matiere == "alu-tendre":
                res["n"] = _arrondi(row["n"] * 0.8, -2)
                res["vf"] = _arrondi(row["vf"] * 0.8, -1)
            if matiere == "alu-dur":
                res["ap"] = _arrondi(row["ap"] * 0.85, 2)
                res["ae"] = _arrondi(row["ae"] * 0.85, 2)
            return res
        return calc(diametre, longueur_coupe or (ex or {}).get("L2"),
                    dents, broche, strat, matiere)

    plein, partiel = choisir("plein"), choisir("partiel")
    if not plein or not partiel:
        return {"ok": False, "raison": "Diamètre de l'outil manquant."}
    ebauche, finition = plein["vf"], partiel["vf"]
    guide_ok = plein["source"] == "guide"
    notes = []
    for n in plein["notes"] + partiel["notes"] + [
            "Plongée = 25 % de l'ébauche et rampe = ébauche: "
            "estimations (le guide préconise une rampe de 3–5°)."]:
        if n not in notes:
            notes.append(n)
    return {
        "ok": True,
        "source": (f"guide DATRON (réf. {ref})" if guide_ok
                   else "modèle d'après le guide DATRON"),
        "rpm": int(plein["n"]),
        "feeds": {"roughing": int(ebauche), "finishing": int(finition),
                  "plunge": int(_arrondi(ebauche * 0.25, -1)),
                  "ramp": int(ebauche)},
        "coupe": {"broche": broche, "matiere": matiere,
                  "source": plein["source"],
                  "rainurage": {"ap": plein["ap"], "ae": plein["ae"],
                                "vf": plein["vf"]},
                  "lateral": {"ap": partiel["ap"], "ae": partiel["ae"],
                              "vf": partiel["vf"]}},
        "notes": notes,
    }


_GUIDE = None


def guide() -> Guide:
    """Le guide de l'application (data/coupe_datron_guide.json), lu au
    premier besoin — vide tant que l'utilisateur n'a pas chargé son
    PDF."""
    global _GUIDE
    if _GUIDE is None:
        _GUIDE = Guide()
    return _GUIDE
