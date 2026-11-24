"""Les pièces en MAILLAGE: STL (binaire ou texte) et 3DXML (CATIA).

Un STL, un 3DXML n'ont pas de faces exactes comme un STEP: seulement
des triangles. On les reconstruit pour que la pièce vive dans
NeoDrive comme une pièce STEP — au Canva 3D (ombrée, arêtes vives,
faces cliquables), à l'usinage 3D, et au Canva 2D (ses faces du dessus
en calques « STEP Pz … », ses trous verticaux):

1. les sommets sont soudés (un STL répète chaque sommet);
2. les FACES PLANES: triangles voisins de même plan, réunis;
3. les TROUS: triangles voisins verticaux posés sur un même cercle —
   un cylindre, creux si leurs normales regardent l'axe;
4. le reste: des faces « autres », par régions lisses;
5. les arêtes vives (plus de 20° entre deux faces) se dessinent.

Un STL n'a pas d'unité: le millimètre est supposé (comme le font les
logiciels de FAO); un 3DXML est en millimètres. CATIA exporte en
3DXML, STL, STEP et IGES — ses fichiers natifs (.CATPart…) sont fermés.
"""
from __future__ import annotations

import math
import pathlib
import struct
import zipfile
from typing import Dict, List, Optional, Tuple

import numpy as np

from .dxfimport import Cancelled, ImportReport
from .geometry import Chemin

SUFFIXES = ('.stl', '.3dxml')

#: deux normales « parallèles » à moins de ça (faces planes)
_ANGLE_PLAN = math.radians(0.5)
#: un mur « vertical »: |nz| sous ça
_VERTICAL = 0.02
#: une arête vive: plus de ça entre les deux faces
_ANGLE_VIF = math.radians(20.0)


class MaillageError(RuntimeError):
    """Maillage illisible."""


def _avancer(progress, f, texte):
    if progress is not None and progress(f, texte) is False:
        raise Cancelled(texte)


# ── lecture ─────────────────────────────────────────────────────────

def lire_stl(chemin) -> np.ndarray:
    """Les triangles (N, 3, 3) d'un STL, binaire ou texte."""
    brut = pathlib.Path(chemin).read_bytes()
    if len(brut) >= 84:
        n = struct.unpack_from('<I', brut, 80)[0]
        if 84 + 50 * n == len(brut):
            d = np.frombuffer(brut, dtype=[('n', '<f4', 3),
                                           ('v', '<f4', (3, 3)),
                                           ('attr', '<u2')],
                              count=n, offset=84)
            return np.asarray(d['v'], dtype=float)
    texte = brut.decode('latin-1')
    if 'vertex' not in texte:
        raise MaillageError("STL illisible (ni binaire ni texte)")
    v = []
    for ligne in texte.splitlines():
        ligne = ligne.strip()
        if ligne.startswith('vertex'):
            try:
                v.append([float(c) for c in ligne.split()[1:4]])
            except ValueError:
                continue
    n = len(v) // 3
    if not n:
        raise MaillageError("STL sans triangle")
    return np.asarray(v[:3 * n], dtype=float).reshape(n, 3, 3)


def _matrice(texte: str) -> np.ndarray:
    """« a b c d e f g h i x y z » (3DXML) → matrice 4×4."""
    v = [float(c) for c in texte.split()]
    M = np.eye(4)
    if len(v) >= 12:
        M[:3, 0] = v[0:3]
        M[:3, 1] = v[3:6]
        M[:3, 2] = v[6:9]
        M[:3, 3] = v[9:12]
    return M


def _triangles_rep(racine) -> np.ndarray:
    """Les triangles des représentations polygonales d'un XML 3DXML."""
    sortie = []
    for rep in racine.iter():
        if not rep.tag.endswith('Rep'):
            continue
        typ = next((v for k, v in rep.attrib.items()
                    if k.endswith('type')), '')
        if 'PolygonalRep' not in typ:
            continue
        pos = next((e for e in rep.iter() if e.tag.endswith('Positions')),
                   None)
        if pos is None or not (pos.text or '').strip():
            continue
        P = np.array([[float(c) for c in t.split()]
                      for t in pos.text.replace('\n', ' ').split(',')
                      if t.strip()], dtype=float)
        for face in (e for e in rep.iter() if e.tag.endswith('Face')):
            tri = face.attrib.get('triangles', '')
            if tri.strip():
                idx = np.array([int(c) for c in tri.split()], dtype=int)
                idx = idx[:len(idx) // 3 * 3].reshape(-1, 3)
                sortie.append(P[idx])
            for bande in face.attrib.get('strips', '').split(','):
                idx = [int(c) for c in bande.split()]
                for k in range(len(idx) - 2):
                    a, b, c = idx[k], idx[k + 1], idx[k + 2]
                    sortie.append(P[[[a, b, c] if k % 2 == 0
                                     else [b, a, c]]])
            for eventail in face.attrib.get('fans', '').split(','):
                idx = [int(c) for c in eventail.split()]
                for k in range(1, len(idx) - 1):
                    sortie.append(P[[[idx[0], idx[k], idx[k + 1]]]])
    if not sortie:
        return np.zeros((0, 3, 3))
    return np.vstack(sortie)


def lire_3dxml(chemin) -> Tuple[np.ndarray, List[str]]:
    """Les triangles d'un 3DXML (CATIA), placés par les matrices des
    instances quand le fichier en donne; et des remarques."""
    import xml.etree.ElementTree as ET
    notes = []
    try:
        z = zipfile.ZipFile(chemin)
    except zipfile.BadZipFile:
        raise MaillageError("3DXML illisible (pas une archive)") from None
    reps: Dict[str, np.ndarray] = {}
    racines = {}
    for nom in z.namelist():
        if not nom.lower().endswith(('.3drep', '.3dxml', '.xml')):
            continue
        try:
            racine = ET.fromstring(z.read(nom))
        except ET.ParseError:
            continue
        racines[nom] = racine
        tri = _triangles_rep(racine)
        if len(tri):
            reps[nom] = tri
    if not reps:
        raise MaillageError("3DXML sans représentation polygonale "
                            "(exporter depuis CATIA en 3DXML « tessellé »)")
    # les placements: InstanceRep → ReferenceRep (fichier), sous une
    # Instance3D de matrice relative (un niveau d'assemblage)
    placements: Dict[str, List[np.ndarray]] = {}
    for racine in racines.values():
        refrep = {}
        for e in racine.iter():
            if e.tag.endswith('ReferenceRep'):
                fichier = e.attrib.get('associatedFile', '')
                fichier = fichier.split(':')[-1] if fichier else ''
                refrep[e.attrib.get('id')] = fichier
        mat_instance = {}
        parent_de = {}
        for e in racine.iter():
            if e.tag.endswith('Instance3D'):
                rel = next((c for c in e if c.tag.endswith('RelativeMatrix')),
                           None)
                ins = next((c for c in e if c.tag.endswith('IsInstanceOf')),
                           None)
                if ins is not None:
                    mat_instance[(ins.text or '').strip()] = _matrice(
                        rel.text) if rel is not None else np.eye(4)
            if e.tag.endswith('InstanceRep'):
                agg = next((c for c in e if c.tag.endswith('IsAggregatedBy')),
                           None)
                ins = next((c for c in e if c.tag.endswith('IsInstanceOf')),
                           None)
                if agg is not None and ins is not None:
                    parent_de[(ins.text or '').strip()] = (agg.text or
                                                           '').strip()
        for rid, fichier in refrep.items():
            ref3d = parent_de.get(rid)
            M = mat_instance.get(ref3d, np.eye(4)) if ref3d else np.eye(4)
            if fichier:
                placements.setdefault(fichier, []).append(M)
    tous = []
    for nom, tri in reps.items():
        mats = placements.get(nom) or placements.get(
            pathlib.PurePosixPath(nom).name) or [np.eye(4)]
        for M in mats:
            P = tri.reshape(-1, 3) @ M[:3, :3].T + M[:3, 3]
            tous.append(P.reshape(-1, 3, 3))
    if len(placements) > 1:
        notes.append(f"3DXML: {len(reps)} pièce(s) placées par leurs "
                     f"instances (un niveau d'assemblage)")
    return np.vstack(tous), notes


def lire_triangles(chemin) -> Tuple[np.ndarray, List[str]]:
    suffixe = pathlib.Path(chemin).suffix.lower()
    if suffixe == '.3dxml':
        return lire_3dxml(chemin)
    return lire_stl(chemin), ["STL: le millimètre est supposé (un STL "
                              "n'a pas d'unité)"]


# ── faces ───────────────────────────────────────────────────────────

class _Union:
    def __init__(self, n):
        self.p = np.arange(n)

    def trouver(self, i):
        p = self.p
        racine = i
        while p[racine] != racine:
            racine = p[racine]
        while p[i] != racine:
            p[i], i = racine, p[i]
        return racine

    def unir(self, a, b):
        ra, rb = self.trouver(a), self.trouver(b)
        if ra != rb:
            self.p[ra] = rb


def _souder(T: np.ndarray, pas: float = 1e-5):
    V = T.reshape(-1, 3)
    cles = np.round(V / pas).astype(np.int64)
    uniques, inverse = np.unique(cles, axis=0, return_inverse=True)
    sommets = np.zeros((len(uniques), 3))
    np.add.at(sommets, inverse.ravel(), V)
    compte = np.bincount(inverse.ravel(), minlength=len(uniques))
    sommets /= compte[:, None]
    return sommets, inverse.reshape(-1, 3)


def _aretes(idx: np.ndarray):
    """Les arêtes (a < b) et, pour chacune, ses triangles."""
    e = np.vstack([idx[:, [0, 1]], idx[:, [1, 2]], idx[:, [2, 0]]])
    t = np.tile(np.arange(len(idx)), 3)
    e = np.sort(e, axis=1)
    ordre = np.lexsort((e[:, 1], e[:, 0]))
    e, t = e[ordre], t[ordre]
    debuts = np.flatnonzero(np.r_[True, np.any(e[1:] != e[:-1], axis=1)])
    fins = np.r_[debuts[1:], len(e)]
    return e, t, debuts, fins


def _chainer(segments) -> List[List[int]]:
    """Des arêtes (a, b) chaînées en boucles ou lignes de sommets."""
    voisins: Dict[int, List[int]] = {}
    for a, b in segments:
        voisins.setdefault(a, []).append(b)
        voisins.setdefault(b, []).append(a)
    vus = set()
    chaines = []
    for a, b in segments:
        if (a, b) in vus or (b, a) in vus:
            continue
        chaine = [a, b]
        vus.add((a, b))
        # vers l'avant
        while True:
            fin = chaine[-1]
            suite = next((c for c in voisins.get(fin, [])
                          if (fin, c) not in vus and (c, fin) not in vus),
                         None)
            if suite is None:
                break
            vus.add((fin, suite))
            chaine.append(suite)
            if suite == chaine[0]:
                break
        chaines.append(chaine)
    return chaines


def modele_depuis_triangles(T, axe_haut: str = 'auto', notes=None,
                            progress=None):
    """Un Modele3D (src/io/vecteur/step3d) depuis des triangles: faces
    planes, cylindres verticaux, régions lisses; arêtes vives."""
    from .step3d import Modele3D, _ALU
    T = np.asarray(T, dtype=float).reshape(-1, 3, 3)
    n0 = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
    aire2 = np.linalg.norm(n0, axis=1)
    T = T[aire2 > 1e-12]
    sortie = Modele3D()
    sortie.notes = list(notes or [])
    if not len(T):
        return sortie
    _avancer(progress, 0.05, "soudure des sommets")
    sommets, idx = _souder(T)
    N = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
    N /= np.linalg.norm(N, axis=1)[:, None]
    # le haut: les grandes faces à plat
    if axe_haut == 'auto':
        aires = 0.5 * np.linalg.norm(np.cross(T[:, 1] - T[:, 0],
                                              T[:, 2] - T[:, 0]), axis=1)
        par_axe = {a: float(aires[np.abs(N[:, k]) > 0.999].sum())
                   for k, a in enumerate('XYZ')}
        meilleur = 'Y' if par_axe['Y'] >= par_axe['X'] else 'X'
        axe_haut = meilleur if par_axe[meilleur] > 2 * par_axe['Z'] \
            and par_axe[meilleur] > 0 else 'Z'
    if axe_haut in ('Y', 'X'):
        # redresser: l'axe choisi devient Z (repère direct)
        R = (np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], dtype=float)
             if axe_haut == 'Y' else
             np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]], dtype=float))
        sommets = sommets @ R.T
        T = T @ R.T
        N = N @ R.T
        sortie.notes.append(f"Pièce exportée « {axe_haut} vers le haut »: "
                            "redressée (Z vers le haut)")
    sortie.axe_haut = axe_haut
    _avancer(progress, 0.15, "voisinages")
    e, t, debuts, fins = _aretes(idx)
    paires = []
    for d, f in zip(debuts, fins):
        if f - d == 2:
            paires.append((t[d], t[d + 1], d))
    centres = T.mean(axis=1)
    u = _Union(len(T))
    cos_plan = math.cos(_ANGLE_PLAN)
    for a, b, _k in paires:
        if float(N[a] @ N[b]) > cos_plan and abs(
                float(N[a] @ (centres[b] - centres[a]))) < 0.01:
            u.unir(a, b)
    groupes: Dict[int, List[int]] = {}
    for i in range(len(T)):
        groupes.setdefault(u.trouver(i), []).append(i)
    _avancer(progress, 0.4, "faces planes")
    # une facette d'un cylindre (deux triangles d'un même quad) est
    # plane, mais toutes ses voisines la PROLONGENT en douceur: ce
    # n'est pas une face, c'est un morceau de surface courbe
    racine_de = np.array([u.trouver(i) for i in range(len(T))])
    taille = {r: len(m) for r, m in groupes.items()}
    #: les groupes voisins qui la prolongent en douceur (< 25°)
    doux = {r: set() for r in groupes}
    cos_lisse = math.cos(math.radians(25))
    for a, b, _k in paires:
        ra, rb = racine_de[a], racine_de[b]
        if ra == rb:
            continue
        if float(N[a] @ N[b]) > cos_lisse:
            doux[ra].add(rb)
            doux[rb].add(ra)
    face_de = np.full(len(T), -1, dtype=int)
    faces: List[Dict] = []
    seuls = []
    for r, membres in groupes.items():
        # une facette: deux triangles au plus, prolongée en douceur des
        # deux côtés (le tour d'un trou)
        facette = taille[r] <= 2 and len(doux[r]) >= 2
        if not facette:
            membres = np.array(membres)
            faces.append({'genre': 'plan', 'membres': membres})
            face_de[membres] = len(faces) - 1
        else:
            seuls += membres
    # les murs verticaux posés sur un cercle: des cylindres
    _avancer(progress, 0.55, "cylindres")
    u2 = _Union(len(T))
    seuls_set = set(seuls)
    for a, b, _k in paires:
        if a in seuls_set and b in seuls_set and float(N[a] @ N[b]) > cos_lisse:
            u2.unir(a, b)
    regions: Dict[int, List[int]] = {}
    for i in seuls:
        regions.setdefault(u2.trouver(i), []).append(i)
    for membres in regions.values():
        membres = np.array(membres)
        face = {'genre': 'autre', 'membres': membres}
        if len(membres) >= 6 and np.all(np.abs(N[membres, 2]) < _VERTICAL):
            pts = T[membres].reshape(-1, 3)
            c = _cercle(pts[:, :2])
            if c is not None:
                cx, cy, r, ecart = c
                if ecart <= max(0.02, 0.005 * r):
                    # creux: la matière est DEHORS de la paroi (sondée de
                    # part et d'autre d'elle — le sens des triangles n'y
                    # fait rien). L'axe ne le dit pas: celui d'une bague
                    # ou d'un bossage percé est dans le vide, et leur
                    # paroi EXTÉRIEURE devenait un trou à percer
                    creux = _paroi_creuse(T, T[membres], cx, cy)
                    if creux is None:
                        zm = float(pts[:, 2].min() + pts[:, 2].max()) / 2.0
                        creux = not _dans_matiere(T, (cx, cy, zm))
                    ang = np.sort(np.arctan2(pts[:, 1] - cy, pts[:, 0] - cx))
                    trous = np.diff(np.r_[ang, ang[0] + 2 * math.pi])
                    couverture = 2 * math.pi - float(trous.max())
                    face = {'genre': 'cylindre', 'membres': membres,
                            'axe': np.array([0.0, 0.0, 1.0]),
                            'centre': np.array([cx, cy, float(pts[:, 2].min())]),
                            'rayon': float(r), 'creux': bool(creux),
                            'couverture': couverture}
        faces.append(face)
        face_de[membres] = len(faces) - 1
    # boucles et arêtes vives
    _avancer(progress, 0.75, "boucles et arêtes")
    bords_face: Dict[int, List[Tuple[int, int]]] = {}
    vives = []
    for d, f in zip(debuts, fins):
        ar = (int(e[d][0]), int(e[d][1]))
        tris = t[d:f]
        fs = {int(face_de[k]) for k in tris}
        if len(tris) == 1:
            bords_face.setdefault(int(face_de[tris[0]]), []).append(ar)
            vives.append(ar)
            continue
        if len(fs) > 1:
            for fi in fs:
                bords_face.setdefault(fi, []).append(ar)
            if len(tris) == 2 and float(N[tris[0]] @ N[tris[1]]) < math.cos(
                    _ANGLE_VIF):
                vives.append(ar)
    infos = []
    for fi, face in enumerate(faces):
        membres = face['membres']
        tri = T[membres]
        info = {'genre': face['genre'],
                'surface': {'plan': 'PLANE', 'cylindre': 'CYLINDRICAL_SURFACE'
                            }.get(face['genre'], 'MESH'),
                'aire': _aire(tri), 'boucles': [],
                'z_min': float(tri[:, :, 2].min()),
                'z_max': float(tri[:, :, 2].max()), 'index': fi}
        boucles = [np.array([sommets[k] for k in ch])
                   for ch in _chainer(bords_face.get(fi, []))
                   if len(ch) >= 3]
        if face['genre'] == 'plan':
            n = N[membres].mean(axis=0)
            n /= max(np.linalg.norm(n), 1e-12)
            info['normale'] = n
            aires = [_aire_boucle(b, n) for b in boucles]
            ext = int(np.argmax(aires)) if aires else -1
            info['boucles'] = [(b, i == ext) for i, b in enumerate(boucles)]
        else:
            info['boucles'] = [(b, True) for b in boucles]
            for cle in ('axe', 'centre', 'rayon', 'creux', 'couverture'):
                if cle in face:
                    info[cle] = face[cle]
        infos.append(info)
    sortie.triangles = T
    sortie.couleurs = np.tile(np.array(_ALU, dtype=float), (len(T), 1))
    sortie.faces = infos
    sortie.face_de = face_de
    sortie.n_faces = sortie.n_faces_maillees = len(infos)
    sortie.aretes = [np.array([sommets[k] for k in ch])
                     for ch in _chainer(vives) if len(ch) >= 2]
    sortie.n_instances = 1
    _avancer(progress, 1.0, "pièce reconstruite")
    return sortie


def _dans_matiere(T: np.ndarray, p) -> bool:
    """Le point est-il dans le solide ? (parité des traversées d'un
    rayon vertical, Möller–Trumbore vectorisé)"""
    p = np.asarray(p, dtype=float)
    d = np.array([1e-7, 2e-7, 1.0])          # presque vertical: pas
    d /= np.linalg.norm(d)                   # d'arête rasée pile
    v0, v1, v2 = T[:, 0], T[:, 1], T[:, 2]
    e1, e2 = v1 - v0, v2 - v0
    h = np.cross(d, e2)
    a = np.einsum('ij,ij->i', e1, h)
    ok = np.abs(a) > 1e-12
    f = np.zeros_like(a)
    f[ok] = 1.0 / a[ok]
    s = p - v0
    u = f * np.einsum('ij,ij->i', s, h)
    q = np.cross(s, e1)
    v = f * (q @ d)
    t = f * np.einsum('ij,ij->i', e2, q)
    hits = ok & (u >= 0) & (u <= 1) & (v >= 0) & (u + v <= 1) & (t > 1e-9)
    return bool(int(hits.sum()) % 2)


def _paroi_creuse(T: np.ndarray, facettes: np.ndarray, cx: float,
                  cy: float) -> Optional[bool]:
    """La paroi cylindrique d'axe (cx, cy) est-elle celle d'un trou (la
    matière est dehors) ou d'un bossage (la matière est dedans)? Sondée
    de part et d'autre de trois de ses facettes; None si la matière ne
    tranche pas."""
    votes = 0
    n = len(facettes)
    for k in sorted({0, n // 2, n - 1}):
        q = facettes[k].mean(axis=0)
        d = q[:2] - np.array([cx, cy])
        rho = float(np.linalg.norm(d))
        if rho < 1e-9:
            continue
        d /= rho
        eps = max(0.01, min(0.1, 0.02 * rho))
        dedans = _dans_matiere(T, (cx + (rho - eps) * d[0],
                                   cy + (rho - eps) * d[1], q[2]))
        dehors = _dans_matiere(T, (cx + (rho + eps) * d[0],
                                   cy + (rho + eps) * d[1], q[2]))
        if dehors and not dedans:
            votes += 1
        elif dedans and not dehors:
            votes -= 1
    return None if votes == 0 else votes > 0


def groupes_en_z(morceaux, dans=None, jeu: float = 0.02) -> List[List[int]]:
    """Des morceaux de cylindre de même axe et de même diamètre, chacun
    (z_min, z_max, …), regroupés en trous: deux morceaux qui se touchent
    ou se recouvrent en Z sont le même trou; séparés par du VIDE aussi
    (les deux parois d'un tube, percées d'un trait); séparés par de la
    MATIÈRE, ce sont deux trous — un borgne par face, pris pour un trou
    débouchant. `dans(z)`: l'axe est-il dans la matière à la cote z
    (None: tout est regroupé). Rend [[rangs des morceaux]], du plus haut
    au plus bas."""
    ordre = sorted(range(len(morceaux)), key=lambda k: -morceaux[k][1])
    groupes: List[List[int]] = []
    for k in ordre:
        if groupes:
            g = groupes[-1]
            bas = min(morceaux[i][0] for i in g)
            haut = morceaux[k][1]
            if bas - haut <= jeu or dans is None \
                    or not dans((bas + haut) / 2.0):
                g.append(k)
                continue
        groupes.append([k])
    return groupes


def _axe_dans_matiere(T: np.ndarray, x: float, y: float, z: float,
                      rayon: float) -> bool:
    """L'axe d'un trou est-il dans la matière à la cote z? (trois sondes
    près de l'axe: un rayon qui rase une arête ne décide pas seul)"""
    e = max(0.01, min(0.2, 0.1 * rayon))
    votes = sum(_dans_matiere(T, (x + a, y + b, z))
                for a, b in ((0.0, 0.0), (e, 0.3 * e), (-0.4 * e, -e)))
    return votes >= 2


def _aire(tri) -> float:
    tri = np.asarray(tri)
    return float(0.5 * np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0],
                                               tri[:, 2] - tri[:, 0]),
                                      axis=1).sum())


def _aire_boucle(pts, n) -> float:
    """Aire d'une boucle 3D projetée sur son plan (Newell)."""
    s = np.zeros(3)
    for a, b in zip(pts, np.roll(pts, -1, axis=0)):
        s += np.cross(a, b)
    return abs(float(s @ n)) / 2.0


def _cercle(P: np.ndarray):
    if len(P) < 3:
        return None
    x, y = P[:, 0], P[:, 1]
    A = np.c_[x, y, np.ones_like(x)]
    try:
        sol, *_ = np.linalg.lstsq(A, x * x + y * y, rcond=None)
    except np.linalg.LinAlgError:
        return None
    cx, cy = sol[0] / 2, sol[1] / 2
    r2 = sol[2] + cx * cx + cy * cy
    if r2 <= 0:
        return None
    r = math.sqrt(r2)
    return cx, cy, r, float(np.max(np.abs(np.hypot(x - cx, y - cy) - r)))


def lire_modele(chemin, axe_haut: str = 'auto', progress=None):
    """Le Modele3D d'un STL ou d'un 3DXML."""
    T, notes = lire_triangles(chemin)
    return modele_depuis_triangles(T, axe_haut, notes, progress)


# ── le dessin 2D ────────────────────────────────────────────────────

def lire(chemin, tolerance_mm: float = 0.02, units_mm: float = None,
         progress=None, ask=None):
    """Le dessin d'une pièce maillée, comme celui d'un STEP: ses faces
    du dessus en calques « STEP Pz … » (profondeur sous le dessus), ses
    trous verticaux dans `rapport.trous`."""
    T, notes = lire_triangles(chemin)
    if units_mm and units_mm != 1.0:
        T = T * float(units_mm)
    mod = modele_depuis_triangles(
        T, 'auto', notes,
        None if progress is None else (lambda f, t: progress(0.9 * f, t)))
    if not len(mod.triangles):
        raise MaillageError("aucun triangle dans ce fichier")
    z_dessus = float(mod.triangles[:, :, 2].max())
    z_fond = float(mod.triangles[:, :, 2].min())
    calques: Dict[str, List[Chemin]] = {}
    n_horiz = 0
    for f in mod.faces:
        if f['genre'] != 'plan' or f['normale'][2] < 0.999:
            continue
        n_horiz += 1
        z = f['z_max']
        pz = round(z_dessus - z, 3)
        for boucle, _ext in f['boucles']:
            pts = [(round(float(p[0]), 4), round(float(p[1]), 4))
                   for p in boucle]
            ch = Chemin(pts, tolerance_mm)
            ch.fermer()
            calques.setdefault(f"STEP Pz {pz:g}", []).append(ch)
    parois = {}
    for f in mod.faces:
        if f['genre'] != 'cylindre' or not f.get('creux') \
                or f.get('couverture', 0) < 2 * math.pi - 0.6:
            # (un trou fait le tour: le plus grand écart entre deux
            # sommets n'est qu'une facette — 0,6 rad, 11 côtés au moins)
            continue
        c = f['centre']
        cle = (round(float(c[0]), 2), round(float(c[1]), 2),
               round(f['rayon'], 2))
        p = parois.setdefault(cle, {'x': float(c[0]), 'y': float(c[1]),
                                    'diametre': 2 * f['rayon'],
                                    'morceaux': []})
        p['morceaux'].append((float(f['z_min']), float(f['z_max'])))
    # un trou par suite de parois qui se touchent en Z (ou que seul du
    # vide sépare); celui que de la matière ferme par le haut s'usine par
    # l'autre face: il n'est pas un trou de ce dessin
    trous = {}
    Tm = np.asarray(mod.triangles, dtype=float)
    for cle, p in parois.items():
        rayon = p['diametre'] / 2.0

        def dans(z, p=p, rayon=rayon):
            return _axe_dans_matiere(Tm, p['x'], p['y'], z, rayon)
        for rang, g in enumerate(groupes_en_z(p['morceaux'], dans)):
            z_bas = min(p['morceaux'][k][0] for k in g)
            z_haut = max(p['morceaux'][k][1] for k in g)
            if z_haut < z_dessus - 1e-3 and dans(z_haut + 0.05):
                continue
            trous[cle + (rang,)] = {'x': p['x'], 'y': p['y'],
                                    'diametre': p['diametre'],
                                    'z_bas': z_bas, 'z_haut': z_haut}
    rapport = ImportReport()
    rapport.trous = [{
        'x': round(t['x'], 3), 'y': round(t['y'], 3),
        'diametre': round(t['diametre'], 3),
        'profondeur': round(t['z_haut'] - t['z_bas'], 3),
        'traversant': abs(t['z_bas'] - z_fond) < 1e-3,
        'pz_depart': round(z_dessus - t['z_haut'], 3),
        'fraisure': None, 'fraisure_dessous': None, 'pointe': False}
        for t in sorted(trous.values(), key=lambda t: (t['x'], -t['y']))]
    rapport.layers = {k: len(v) for k, v in calques.items()}
    rapport.polylines = sum(rapport.layers.values())
    pts = [p for v in calques.values() for c in v for p in c]
    if pts:
        rapport.extent = (min(p[0] for p in pts), min(p[1] for p in pts),
                          max(p[0] for p in pts), max(p[1] for p in pts))
    rapport.notes += mod.notes
    rapport.notes.append(
        f"Maillage: {len(mod.triangles)} triangles, {len(mod.faces)} "
        f"faces reconstruites, {n_horiz} horizontale(s) vers le haut, "
        f"{len(rapport.trous)} trou(s) vertical(aux); hauteur "
        f"{z_dessus - z_fond:g} mm.")
    if progress is not None:
        progress(1.0, "terminé")
    return calques, rapport
