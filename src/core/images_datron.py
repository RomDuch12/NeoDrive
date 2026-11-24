"""Les photos d'un outil sur le webshop DATRON (webshop.datron.de): la
photo de l'outil, son plan coté, ses matières — telles que la fiche
produit du webshop les montre.

La recherche par référence mène à la page produit; ses images
s'appellent « <réf>_1.png », « <réf>_2.png »… (les autres références de
la page sont des suggestions, on les laisse). L'ORIGINAL est gardé tel
que le webshop le donne — la meilleure qualité qu'il ait (6000 px) —
dans le dossier de la fiche de l'outil (`fiches_outils`); une copie
d'affichage (« apercu/ », 1200 px) rend la fiche immédiate aux accès
suivants: décoder trois originaux de 6000 px à chaque ouverture coûtait
des secondes et des centaines de mégaoctets. Sans réseau, rien ne se
passe: la fiche le dit.
"""

import os
import re
import time
from typing import Callable, List, Optional
from urllib.parse import quote

URL_RECHERCHE = "https://webshop.datron.de/search?search={ref}"
#: le sous-dossier des copies d'affichage
APERCU = "apercu"
#: le grand côté des copies d'affichage (px)
TAILLE_APERCU = 1200
#: combien d'images au plus par outil
IMAGES_MAX = 6
#: délai d'une requête (s)
DELAI = 30
#: une référence absente du webshop n'est pas redemandée avant (s)
OUBLI_ABSENCE = 30 * 24 * 3600
#: le fichier qui note une recherche sans résultat
MARQUE_ABSENCE = ".aucune_image"

_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp')


def lire_url(url: str, timeout: float = DELAI) -> bytes:
    """Le contenu d'une adresse (remplaçable: les tests n'ont pas de
    réseau — NEODRIVE_SANS_RESEAU le coupe)."""
    if os.environ.get('NEODRIVE_SANS_RESEAU'):
        raise OSError("réseau coupé (NEODRIVE_SANS_RESEAU)")
    from urllib.request import Request, urlopen
    req = Request(url, headers={
        'User-Agent': "Mozilla/5.0 (NeoDrive; fiche outil)",
        'Accept-Language': "fr,de;q=0.8,en;q=0.6"})
    with urlopen(req, timeout=timeout) as rep:
        return rep.read()


def normaliser(ref: str) -> str:
    """« 0068443G / 114206 » → « 0068443G »."""
    from src.core.tool_library import extract_article_nr
    return extract_article_nr(str(ref or "")).strip().upper()


def _rang(chemin: str) -> int:
    m = re.search(r'_(\d+)\.[a-z]+$', os.path.basename(chemin), re.I)
    return int(m.group(1)) if m else 999


def _images(d: str, ref: str) -> List[str]:
    if not ref or not os.path.isdir(d):
        return []
    return sorted((os.path.join(d, f) for f in os.listdir(d)
                   if f.lower().endswith(_EXTENSIONS)
                   and f.upper().startswith(ref + "_")
                   and os.path.isfile(os.path.join(d, f))), key=_rang)


def originaux(dossier: str, ref: str) -> List[str]:
    """Les images telles que le webshop les donne (pleine qualité)."""
    return _images(dossier, normaliser(ref))


def images_en_cache(dossier: str, ref: str) -> List[str]:
    """Les copies d'affichage des images gardées, dans l'ordre du
    webshop — refaites depuis l'original s'il en manque une; sans
    original (données importées d'un autre poste), la copie seule."""
    ref = normaliser(ref)
    d = os.path.join(dossier, APERCU)
    par_nom = {os.path.splitext(os.path.basename(a))[0]: a
               for a in _images(d, ref)}
    for src in _images(dossier, ref):
        nom = os.path.splitext(os.path.basename(src))[0]
        if nom in par_nom:
            continue
        try:
            with open(src, 'rb') as f:
                faite = ecrire_apercu(f.read(), os.path.join(d, nom))
        except OSError:
            faite = None
        if faite:
            par_nom[nom] = faite
    return sorted(par_nom.values(), key=_rang)


def absence_recente(dossier: str, ref: str) -> bool:
    """Le webshop n'avait rien pour cette référence il y a peu."""
    try:
        age = time.time() - os.path.getmtime(
            os.path.join(dossier, MARQUE_ABSENCE))
        return age < OUBLI_ABSENCE
    except OSError:
        return False


def url_produit(html: str, ref: str) -> Optional[str]:
    """La page produit de la référence, dans une page de recherche."""
    ref = re.escape(normaliser(ref))
    m = re.search(r'href="((?:https?://webshop\.datron\.de)?/[^"]*/'
                  + ref + r'-[^"]*)"', html, re.I)
    if not m:
        return None
    url = m.group(1)
    return url if url.startswith("http") else \
        "https://webshop.datron.de" + url


def urls_images(html: str, ref: str) -> List[str]:
    """Les images de LA référence (« <réf>_<n>.png »), une par rang,
    dans l'ordre — l'adresse du fichier original, sans vignette."""
    texte = html.replace('\\/', '/')
    ref = normaliser(ref)
    vues = {}
    for m in re.finditer(r'https?://webshop\.datron\.de/media/[^"\'\s?<>]*?/('
                         + re.escape(ref) + r')_(\d+)\.(png|jpe?g|webp)',
                         texte, re.I):
        if '/thumbnail/' in m.group(0):
            continue
        vues.setdefault(int(m.group(2)), m.group(0))
    return [vues[n] for n in sorted(vues)][:IMAGES_MAX]


def ecrire_apercu(donnees: bytes, base: str) -> Optional[str]:
    """La copie d'affichage (TAILLE_APERCU), sur fond noir comme le
    webshop la montre: JPEG, sinon PNG. Rend le chemin écrit."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QImage, QPainter
    image = QImage.fromData(donnees)
    if image.isNull():
        return None
    if max(image.width(), image.height()) > TAILLE_APERCU:
        image = image.scaled(TAILLE_APERCU, TAILLE_APERCU,
                             Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
    fond = QImage(image.size(), QImage.Format.Format_RGB32)
    fond.fill(QColor("#000000"))
    p = QPainter(fond)
    p.drawImage(0, 0, image)
    p.end()
    os.makedirs(os.path.dirname(base), exist_ok=True)
    for ext, fmt in ((".jpg", "JPG"), (".png", "PNG")):
        if fond.save(base + ext, fmt, 92):
            return base + ext
    return None


def telecharger(ref: str, dossier: str, progression: Callable = None,
                lire: Callable = None, forcer: bool = False) -> List[str]:
    """Les images de la référence (copies d'affichage): celles déjà
    gardées, sinon celles du webshop — l'original gardé tel quel à côté.
    `progression(fraction, texte)` rend False pour arrêter
    (vcarve.Annule). Lève OSError sans réseau."""
    from src.core.vcarve import avancer
    lire = lire or lire_url
    ref = normaliser(ref)
    if not ref:
        return []
    en_cache = images_en_cache(dossier, ref)
    if en_cache and not forcer:
        return en_cache
    if not forcer and absence_recente(dossier, ref):
        return []
    avancer(progression, 0.0, "recherche sur webshop.datron.de")
    html = lire(URL_RECHERCHE.format(ref=quote(ref))).decode(
        'utf-8', 'replace')
    urls = urls_images(html, ref)
    if not urls:
        produit = url_produit(html, ref)
        if produit:
            avancer(progression, 0.1, "page produit")
            html = lire(produit).decode('utf-8', 'replace')
            urls = urls_images(html, ref)
    os.makedirs(dossier, exist_ok=True)
    if not urls:
        with open(os.path.join(dossier, MARQUE_ABSENCE), 'w',
                  encoding='utf-8') as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S"))
        return []
    recus = []
    for i, url in enumerate(urls):
        avancer(progression, 0.15 + 0.8 * i / len(urls),
                f"image {i + 1}/{len(urls)} (pleine qualité)")
        recus.append((url.split('?')[0], lire(url)))
    avancer(progression, 0.95, "copies d'affichage")
    # la série entière, ou rien: une annulation en route ne laisse pas
    # des images manquantes que le cache ne redemanderait jamais
    for propre, donnees in recus:
        ext = os.path.splitext(propre)[1].lower() or ".png"
        nom = f"{ref}_{_rang(propre)}"
        provisoire = os.path.join(dossier, nom + ext + ".part")
        with open(provisoire, 'wb') as f:
            f.write(donnees)          # l'original, tel que reçu
        os.replace(provisoire, os.path.join(dossier, nom + ext))
        ecrire_apercu(donnees, os.path.join(dossier, APERCU, nom))
    try:
        os.remove(os.path.join(dossier, MARQUE_ABSENCE))
    except OSError:
        pass
    avancer(progression, 1.0, f"{len(urls)} image(s)")
    return images_en_cache(dossier, ref)
