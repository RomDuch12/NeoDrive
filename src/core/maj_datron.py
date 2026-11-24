"""La mise à jour depuis le webshop DATRON (webshop.datron.de).

Octobre 2026 (RomDuch): « live update from DATRON website, consider
tool_angle ». Pour une référence, la fiche produit du webshop donne ses
cotes dans un tableau (« product-detail-properties-table »: D1, D2, L1,
L2, L3, Winkel, Spiralwinkel, Z, Schaftform…). On les compare au
catalogue hors ligne et à la fiche de l'outil dans tools.json; les
ÉCARTS sont montrés avant d'appliquer (rien ne s'écrit sans accord).

L'angle: « Winkel » est l'angle de l'outil (pointe à graver, chanfrein,
foret) — le même que l'« angle » du catalogue, qui va au TipAngle de
la fiche. Le « Spiralwinkel » est l'angle d'HÉLICE des goujures: gardé
à part, jamais pris pour un angle de pointe.

Le catalogue livré n'est pas réécrit: les cotes lues sur le webshop
vont dans « catalogue_datron_maj.json » à côté de lui (données de
l'utilisateur, gardées d'une version à l'autre), que le catalogue
superpose à la lecture.
"""

import html as _html
import os
import re
import time
from typing import Callable, Dict, List, Optional

#: le fichier des mises à jour, à côté du catalogue
NOM_MAJ = "catalogue_datron_maj.json"
#: libellé du webshop → clé du catalogue
LIBELLES = {
    'd1': 'D1', 'd2': 'D2', 'd3': 'D3', 'l1': 'L1', 'l2': 'L2', 'l3': 'L3',
    'winkel': 'angle', 'spitzenwinkel': 'angle', 'kegelwinkel': 'angle',
    'spiralwinkel': 'spirale', 'drallwinkel': 'spirale',
    'z': 'dents', 'schneidenzahl': 'dents', 'radius': 'R', 'r': 'R',
    'eckenradius': 'R',
}
#: les cotes numériques comparées (clé du catalogue → libellé lisible)
COTES = (('D1', "D1 (coupe)"), ('D2', "D2 (queue)"), ('D3', "D3"),
         ('L1', "L1 (totale)"), ('L2', "L2 (coupe)"), ('L3', "L3"),
         ('angle', "angle"), ('R', "rayon"), ('dents', "dents"))
#: le reste du tableau, gardé en texte
TEXTES = {'schaftform': 'queue', 'drallrichtung': 'helice',
          'innenkuhlung': 'arrosage', 'innenkühlung': 'arrosage',
          'bearbeitungsrichtung': 'sens'}

_LIGNE_RE = re.compile(
    r'<th[^>]*class="[^"]*properties-label[^"]*"[^>]*>(.*?)</th>\s*'
    r'<td[^>]*class="[^"]*properties-value[^"]*"[^>]*>(.*?)</td>',
    re.S | re.I)


def _texte(fragment: str) -> str:
    t = re.sub(r'<[^>]+>', '', fragment or "")
    return " ".join(_html.unescape(t).split())


def _cle(libelle: str) -> str:
    import unicodedata
    t = _texte(libelle).rstrip(':').strip().lower()
    t2 = unicodedata.normalize('NFKD', t).encode('ascii', 'ignore').decode()
    return t2.replace(' ', '')


def proprietes(page: str) -> Dict[str, str]:
    """{libellé: valeur} du tableau des propriétés d'une fiche produit."""
    return {_texte(l).rstrip(':').strip(): _texte(v)
            for l, v in _LIGNE_RE.findall(page or "")}


def nombre(texte) -> Optional[float]:
    """« 0,05 », « 30° », « 3,0 mm » → 0.05, 30.0, 3.0 (None sinon)."""
    m = re.search(r'[-+]?\d+(?:[.,]\d+)?', str(texte or ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(',', '.'))
    except ValueError:
        return None


def fiche(props: Dict[str, str]) -> Dict:
    """Les propriétés du webshop en cotes du catalogue: {'D1', 'D2',
    'L1', 'L2', 'angle', 'spirale', 'dents', … , 'textes': {…}}."""
    sortie: Dict = {'textes': {}}
    for libelle, valeur in props.items():
        cle = _cle(libelle)
        if cle in LIBELLES:
            v = nombre(valeur)
            if v is not None:
                k = LIBELLES[cle]
                sortie[k] = int(round(v)) if k == 'dents' else v
        elif cle in TEXTES:
            sortie['textes'][TEXTES[cle]] = valeur
    return sortie


def lire_reference(ref: str, lire_url: Callable = None) -> Optional[Dict]:
    """La fiche produit d'une référence sur le webshop: {'ref', 'url',
    'cotes': fiche(…)}, ou None (absente du webshop). Lève OSError sans
    réseau."""
    from src.core import images_datron as im
    lire_url = lire_url or im.lire_url
    ref = im.normaliser(ref)
    if not ref:
        return None
    recherche = lire_url(im.URL_RECHERCHE.format(
        ref=__import__('urllib.parse', fromlist=['quote']).quote(ref)))
    page = recherche.decode('utf-8', 'replace') if isinstance(
        recherche, bytes) else str(recherche)
    url = im.url_produit(page, ref)
    if url is None:
        # la recherche mène parfois droit à la fiche
        if proprietes(page):
            url = im.URL_RECHERCHE.format(ref=ref)
        else:
            return None
    else:
        brut = lire_url(url)
        page = brut.decode('utf-8', 'replace') if isinstance(
            brut, bytes) else str(brut)
    cotes = fiche(proprietes(page))
    if len(cotes) <= 1:
        return None
    return {'ref': ref, 'url': url, 'cotes': cotes,
            'date': time.strftime('%Y-%m-%d')}


def _egal(a, b) -> bool:
    try:
        return abs(float(a) - float(b)) < 1e-6
    except (TypeError, ValueError):
        return a == b


def ecarts_catalogue(entree: Optional[Dict], web: Dict) -> List[tuple]:
    """[(clé, libellé, catalogue, webshop)] des cotes qui diffèrent (ou
    que le catalogue n'a pas)."""
    entree = entree or {}
    sortie = []
    for cle, nom in COTES:
        if cle not in web:
            continue
        avant = entree.get(cle)
        if avant in (None, "") or not _egal(avant, web[cle]):
            sortie.append((cle, nom, avant, web[cle]))
    return sortie


def ecarts_outil(tool, entree: Optional[Dict], web: Dict) -> List[tuple]:
    """[(clé de géométrie, catalogue+webshop → valeur, fiche, valeur)] —
    ce que la fiche de l'outil (tools.json) changerait: la géométrie que
    le catalogue mis à jour donne (l'angle au TipAngle)."""
    from src.core import catalogue_datron as cd
    base = dict(entree or {})
    base.update({k: v for k, v in web.items() if k != 'textes'})
    if 'categorie' not in base:
        base['categorie'] = categorie_outil(tool)
    geo = cd.geometrie(base)
    actuelle = dict(getattr(tool, 'geometry', {}) or {})
    sortie = []
    for cle, valeur in geo.items():
        avant = actuelle.get(cle)
        if avant in (None, "") or not _egal(avant, valeur):
            sortie.append((cle, cle, avant, valeur))
    return sortie


def categorie_outil(tool) -> str:
    """La catégorie du catalogue d'un outil hors catalogue (d'après son
    type: Con → conique, Chamfer → chanfrein, Drill → foret…)."""
    t = str(getattr(tool, 'type_taraudage', '') or '').lower()
    nom = str(getattr(tool, 'name', '') or '').lower()
    if t.startswith('con') or 'grav' in nom:
        return 'conique'
    if t.startswith('chamfer') or 'chanfrein' in nom:
        return 'chanfrein'
    if t.startswith('drill') or 'foret' in nom:
        return 'foret'
    return 'fraise'


# ── le fichier des mises à jour ──

def chemin_maj(chemin_catalogue: str = None) -> str:
    from src.core import catalogue_datron as cd
    base = os.path.dirname(chemin_catalogue or cd.chemin_catalogue())
    return os.path.join(base, NOM_MAJ)


def lire_maj(chemin: str = None) -> Dict[str, Dict]:
    """Les mises à jour lues sur le webshop. Un fichier illisible est
    mis de côté (et dit au démarrage), jamais lu comme vide puis
    écrasé: les mises à jour d'avant se perdaient sans un mot."""
    from src.core.fichiers_surs import lire_json_sur
    d, _alerte = lire_json_sur(chemin or chemin_maj())
    if not isinstance(d, dict) or not isinstance(d.get('maj'), dict):
        return {}
    return {str(k).upper(): dict(v) for k, v in d['maj'].items()
            if isinstance(v, dict)}


def ecrire_maj(maj: Dict[str, Dict], chemin: str = None) -> str:
    from src.core.fichiers_surs import ecrire_json_sur
    chemin = chemin or chemin_maj()
    ecrire_json_sur(chemin, {'source': "webshop.datron.de", 'maj': maj},
                    garder_bak=True, ensure_ascii=False, indent=1)
    return chemin


def appliquer(choix: List[Dict], tool_library=None, chemin: str = None,
              catalogue=None) -> Dict:
    """Applique les écarts retenus. `choix`: [{'ref', 'cotes' (du
    webshop), 'catalogue': [clés retenues], 'outils': {tool_id: [clés de
    géométrie retenues]}, 'url', 'date'}]. Rend {'catalogue': n,
    'outils': n}."""
    maj = lire_maj(chemin)
    n_cat = n_out = 0
    for c in choix:
        ref = str(c['ref']).upper()
        cotes = c.get('cotes') or {}
        retenues = [k for k in c.get('catalogue') or [] if k in cotes]
        if retenues:
            e = dict(maj.get(ref) or {})
            for k in retenues:
                e[k] = cotes[k]
            if cotes.get('spirale') is not None:
                e['spirale'] = cotes['spirale']
            e['date'] = c.get('date') or time.strftime('%Y-%m-%d')
            if c.get('url'):
                e['url'] = c['url']
            maj[ref] = e
            n_cat += 1
        if tool_library is not None:
            entree = catalogue.entree(ref) if catalogue is not None else None
            for tid, cles in (c.get('outils') or {}).items():
                tool = tool_library.get_tool(tid)
                if tool is None or not cles:
                    continue
                valeurs = {k: v for k, _n, _a, v in
                           ecarts_outil(tool, entree, cotes) if k in cles}
                if not valeurs:
                    continue
                data = tool.to_dict()
                geo = dict(data.get('geometry') or {})
                geo.update(valeurs)
                data['geometry'] = geo
                tool_library.update_tool(tid, data)
                n_out += 1
    if n_cat:
        ecrire_maj(maj, chemin)
    return {'catalogue': n_cat, 'outils': n_out}


def superposer(outils: List[Dict], maj: Dict[str, Dict]) -> int:
    """Les cotes mises à jour sur les entrées du catalogue (en place);
    rend le nombre d'entrées touchées."""
    n = 0
    for o in outils:
        m = maj.get(str(o.get('ref', '')).upper())
        if not m:
            continue
        for k, v in m.items():
            if k in ('date', 'url'):
                continue
            o[k] = v
        o['maj_web'] = m.get('date', '')
        n += 1
    return n


def recuperer(refs: List[str], progression: Callable = None,
              lire_url: Callable = None, pause: float = 0.0) -> List[Dict]:
    """Lit sur le webshop chaque référence: [{'ref', 'web' (lire_reference
    ou None), 'erreur'}]. `progression(fraction, texte) -> bool`: False
    arrête (vcarve.Annule)."""
    from src.core import vcarve
    sortie = []
    vus = []
    for r in refs:
        r = str(r or "").strip()
        if r and r.upper() not in [v.upper() for v in vus]:
            vus.append(r)
    n = max(1, len(vus))
    for i, ref in enumerate(vus):
        if progression is not None and not progression(i / n, f"{ref}…"):
            raise vcarve.Annule()
        try:
            web = lire_reference(ref, lire_url)
            sortie.append({'ref': ref, 'web': web,
                           'erreur': "" if web else "absente du webshop"})
        except OSError as exc:
            sortie.append({'ref': ref, 'web': None, 'erreur': str(exc)})
        if pause:
            time.sleep(pause)
    if progression is not None:
        progression(1.0, "webshop lu")
    return sortie


def propositions(lus: List[Dict], catalogue=None,
                 tool_library=None) -> List[Dict]:
    """Ce que la mise à jour changerait, par référence: [{'ref', 'url',
    'date', 'cotes', 'ecarts_catalogue': [...], 'ecarts_outils':
    {tool_id: (nom, [...])}}] — seulement les références qui changent
    quelque chose."""
    from src.core.tool_library import extract_article_nr
    sortie = []
    for lu in lus:
        web = lu.get('web')
        if not web:
            continue
        ref = web['ref']
        entree = catalogue.entree(ref) if catalogue is not None else None
        ec_cat = ecarts_catalogue(entree, web['cotes'])
        ec_out = {}
        if tool_library is not None:
            for tid, tool in tool_library.tools.items():
                art = extract_article_nr(str(tool.reference or "")).upper()
                if art == ref.upper():
                    e = ecarts_outil(tool, entree, web['cotes'])
                    if e:
                        ec_out[tid] = (tool.name, e)
        if ec_cat or ec_out:
            sortie.append({'ref': ref, 'url': web.get('url', ''),
                           'date': web.get('date', ''),
                           'cotes': web['cotes'],
                           'ecarts_catalogue': ec_cat,
                           'ecarts_outils': ec_out})
    return sortie
