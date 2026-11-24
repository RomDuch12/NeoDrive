"""
Contrôle de la STRUCTURE d'un programme SimPl avant qu'il parte à la
machine (octobre 2026).

Le validateur (src.core.validator) juge les opérations; ce contrôle-ci
lit le CODE tel qu'il sera exporté, quelle que soit la façon dont il a
été produit: généré, importé en blocs, retouché à la main. Il attrape ce
que la machine refuserait au chargement, ou exécuterait de travers:

- une séquence appelée sans son bloc « $$$ NOM », deux blocs homonymes;
- un programme appelé que le fichier ne définit pas, un programme
  défini deux fois;
- un `if`, un `for`… sans sa fermeture, une fermeture de trop;
- un programme externe (usermodule) introuvable depuis le poste;
- un paramètre mal orthographié (« Rapid Zz=1 », « Line x=1 »: proche
  d'un paramètre de la commande dans le manuel) — la machine refuse le
  programme au chargement.

Ses règles sont calées sur les programmes de l'atelier (ils tournent
sur la machine): aucun ne doit lever d'erreur.
"""

import re
from typing import Dict, List, NamedTuple, Optional, Set

ERREUR = "erreur"
AVERTISSEMENT = "avertissement"


class Constat(NamedTuple):
    niveau: str     # ERREUR ou AVERTISSEMENT
    ligne: int      # 1 = première ligne; 0 = le programme entier
    message: str

    def __str__(self):
        ou = f"ligne {self.ligne}: " if self.ligne else ""
        return f"{'✗' if self.niveau == ERREUR else '⚠'} {ou}{self.message}"


#: blocs du langage: ouverture → fermeture
_BLOCS = {'program': 'endprogram', 'function': 'endfunction',
          'if': 'endif', 'for': 'endfor', 'foreach': 'endforeach',
          'while': 'endwhile', 'case': 'endcase'}
_FERMETURES = {v: k for k, v in _BLOCS.items()}
#: mots du langage qui ne sont pas des appels
_MOTS = set(_BLOCS) | set(_FERMETURES) | {
    'else', 'elseif', 'is', 'return', 'break', 'continue', 'export',
    'optional', 'end', 'sequence', 'using', 'import', 'usermodule',
    'module', 'not', 'and', 'or', 'true', 'false', 'from', 'to', 'in',
    'step', 'returns', 'var', 'const', 'struct', 'endstruct', 'enum',
    'endenum', 'type',
    # persistance et listes (Base: UserDataPersistence)
    'append', 'loadvalueof', 'savevalueof', 'deletesavedvalueof',
    'serializevalueof', 'deserializevalueof', 'hassavedvalue', 'sizeof'}

_IDENT = re.compile(r'([A-Za-z_][A-Za-z_0-9]*(?:::[A-Za-z_][A-Za-z_0-9]*)*)')
#: ce qui oblige à lire une ligne caractère par caractère
_SIGNES = re.compile(r'["@]|<--')
_DECLARATION = re.compile(r'(?<![:\w])([A-Za-z_]\w*)\s*:(?!:)')
_CHAINE = re.compile(r'"(?:[^"\\\n]|\\.)*"')
#: un paramètre nommé « nom=valeur » (pas « == », ni « a.b= »)
_PARAMETRE = re.compile(r'(?<![\w.])([A-Za-z_]\w*)\s*=(?!=)')
#: {commande (et Module::commande): ses paramètres et mots} — le manuel
_PARAMETRES = None
#: les paramètres que le manuel 3.1.1 ne liste pas, mais qu'emploient
#: le générateur (RectangleFace) ou les programmes d'exemple DATRON
#: (relevé du 30/10/2026)
PARAMETRES_HORS_MANUEL = {
    'RectangleFace': {'percentageStepover', 'angle'},
    'MoveToParkPosition': {'askForRestore'},
    'SafeRapid': {'targetPosition'},
}


def _commandes_connues() -> Set[str]:
    try:
        from src.core.simpl_commandes import COMMANDES
        connues = set(COMMANDES)
    except Exception:
        connues = set()
    try:
        from src.core.simpl_syntaxe import SYNTAXE
        connues |= set(SYNTAXE)
    except Exception:
        pass
    return connues


def _parametres_du_manuel() -> Dict[str, Set[str]]:
    """Les noms de paramètres de chaque commande du manuel 3.1.1 (et
    ceux qu'il oublie, `PARAMETRES_HORS_MANUEL`)."""
    global _PARAMETRES
    if _PARAMETRES is None:
        table: Dict[str, Set[str]] = {}
        try:
            from src.core.simpl_syntaxe import SYNTAXE
        except Exception:
            SYNTAXE = {}
        for nom, s in SYNTAXE.items():
            noms = ({p['nom'] for p in s.get('parametres') or []}
                    | set(s.get('mots') or [])
                    | PARAMETRES_HORS_MANUEL.get(nom, set()))
            table[nom] = noms
            if s.get('prefixe'):
                table[s['prefixe'] + nom] = noms
        _PARAMETRES = table
    return _PARAMETRES


def _proche(nom: str, noms: Set[str]) -> str:
    """Le paramètre voulu, sans doute (casse, faute de frappe)."""
    for n in noms:
        if n.lower() == nom.lower():
            return n
    import difflib
    proches = difflib.get_close_matches(nom, sorted(noms), n=1, cutoff=0.6)
    return proches[0] if proches else ''


def _lignes_utiles(code: str) -> List[str]:
    """Les lignes sans commentaires ni contenu de chaîne (réduites à
    ""), au même numéro: `# …`, `<-- … -->`, annotations `@ … @` (sur
    une ligne, ou `@image:` … `@`), chaînes sur plusieurs lignes (un
    `message="…"` de Dialog). Une ligne sans aucun de ces signes passe
    telle quelle: un programme de 400 000 lignes se lit en un instant."""
    out = []
    etat = None             # None, 'chaine', 'bloc', 'note'
    note_chaine = False     # une chaîne dans une annotation
    for ligne in code.split('\n'):
        if etat is None and not _SIGNES.search(ligne):
            # au plus un commentaire, sans chaîne avant lui
            k = ligne.find('#')
            out.append((ligne if k < 0 else ligne[:k]).rstrip())
            continue
        if etat is None and '@' not in ligne and '<--' not in ligne:
            # des chaînes fermées sur la ligne même: vidées d'un coup
            propre = _CHAINE.sub('""', ligne)
            if propre.count('"') % 2 == 0:
                k = propre.find('#')
                out.append((propre if k < 0 else propre[:k]).rstrip())
                continue
        morceaux = []
        debut = True
        i, n = 0, len(ligne)
        while i < n:
            c = ligne[i]
            if etat == 'chaine':
                if c == '\\' and i + 1 < n:
                    i += 2
                    continue
                if c == '"':
                    morceaux.append('"')
                    etat = None
                i += 1
                continue
            if etat == 'bloc':
                if ligne.startswith('-->', i):
                    etat = None
                    i += 3
                else:
                    i += 1
                continue
            if etat == 'note':
                if c == '"':
                    note_chaine = not note_chaine
                elif c == '@' and not note_chaine:
                    etat = None
                i += 1
                continue
            if debut and c in ' \t\r':
                morceaux.append(c)
                i += 1
                continue
            if debut and c == '@':
                etat, note_chaine, debut = 'note', False, False
                i += 1
                continue
            if debut and ligne.startswith('<--', i):
                etat, debut = 'bloc', False
                i += 3
                continue
            debut = False
            if c == '#':
                break                       # commentaire jusqu'au bout
            if c == '"':
                morceaux.append('"')
                etat = 'chaine'
            elif c != '\r':
                morceaux.append(c)
            i += 1
        out.append(''.join(morceaux).rstrip())
    return out


def controler(code: str, verifier_fichiers: bool = True,
              commandes: Optional[Set[str]] = None) -> List[Constat]:
    """Les constats sur la structure de `code`, dans l'ordre des lignes
    (les erreurs d'abord à ligne égale)."""
    constats: List[Constat] = []
    connues = commandes if commandes is not None else _commandes_connues()
    du_manuel = _parametres_du_manuel()
    brutes = code.split('\n')

    # le corps (programmes) et les blocs $$$ qui suivent — souvent
    # l'essentiel du fichier: de ceux-là, seule la ligne « $$$ » compte
    m = re.search(r'^\$\$\$', code, re.M)
    debut_seq = code.count('\n', 0, m.start()) if m else len(brutes)
    lignes = _lignes_utiles('\n'.join(brutes[:debut_seq]))

    declarees: Dict[str, int] = {}          # sequence NOM → ligne
    modules: Dict[str, tuple] = {}          # usermodule NOM → (ligne, chemin)
    programmes: Dict[str, int] = {}         # program / function NOM → ligne
    # (programme appelant, ligne, nom appelé, avec paramètres): le
    # premier appel de chaque nom par programme (400 000 `Line` n'en
    # font qu'un)
    appels: List[tuple] = []
    vus: Set[tuple] = set()
    bas: Dict[str, str] = {}                # nom en minuscules → nom
    motifs: List[tuple] = []                # callProgram=NOM
    # (commande, paramètre) inconnu du manuel → [ligne, nombre,
    # programme, paramètres permis]
    hors_manuel: Dict[tuple, list] = {}
    variables: Set[str] = set()
    pile: List[tuple] = []                  # (mot, ligne)
    courant = ''                            # le programme en cours
    vu_end = 0
    parentheses = 0

    def _defini(nom):
        return bas.get(nom.lower())

    # les déclarations `nom:type` (variables, paramètres — y compris
    # ceux d'un programme écrits entre parenthèses sur plusieurs lignes)
    for l in lignes:
        if ':' in l:
            variables.update(_DECLARATION.findall(l))
    # les modules dont les fonctions s'écrivent sans préfixe: hors Base,
    # un nom inconnu peut être l'une d'elles
    usings: Set[str] = set()
    for l in lignes:
        mu = re.match(r'\s*using\s+(.*)$', l) if 'using' in l else None
        if mu:
            usings.update(x.strip() for x in mu.group(1).split(',')
                          if x.strip())
    modules_connus = not (usings - {'Base', 'String'})

    for i in range(min(debut_seq, len(lignes))):
        n = i + 1
        s = lignes[i].strip()
        if not s:
            continue
        if pile and 'callProgram' in s:
            for cible in re.findall(r'\bcallProgram\s*=\s*([A-Za-z_]\w*)',
                                    s):
                motifs.append((courant, n, cible))
        # suite d'une instruction entre parenthèses (Dialog ( … ))
        en_parametres = parentheses > 0
        if '(' in s or ')' in s:
            parentheses = max(0, parentheses + s.count('(')
                              - s.count(')'))
        if en_parametres:
            continue
        m = _IDENT.match(s)
        if not m:
            continue
        mot = m.group(1)
        reste = s[m.end():].strip()

        if not pile:
            # hors programme: en-tête et fin
            if mot == 'sequence':
                nom = reste.split()[0] if reste.split() else ''
                if nom:
                    declarees.setdefault(nom, n)
                continue
            if mot == 'usermodule':
                mu = re.match(r'([A-Za-z_]\w*)\s*=', reste)
                if mu:
                    chemin = re.search(r'=\s*"([^"]*)"', brutes[i])
                    nom = mu.group(1)
                    if nom in modules:
                        constats.append(Constat(
                            ERREUR, n, f"le programme externe « {nom} » "
                            f"est déclaré deux fois (lignes "
                            f"{modules[nom][0]} et {n})"))
                    else:
                        modules[nom] = (n, chemin.group(1) if chemin
                                        else '')
                continue
            if mot == 'end' and not reste:
                vu_end = n
                continue
        if mot == 'export':
            mm = _IDENT.match(reste)
            if not mm:
                continue
            mot, reste = mm.group(1), reste[mm.end():].strip()

        if mot in ('program', 'function'):
            nom_m = _IDENT.match(reste)
            nom = nom_m.group(1) if nom_m else ''
            if pile:
                constats.append(Constat(
                    ERREUR, pile[0][1], f"« {pile[0][0]} » sans "
                    f"« {_BLOCS[pile[0][0]]} » (« {mot} {nom} » commence "
                    f"ligne {n})"))
                pile.clear()
            if nom:
                autre = _defini(nom)
                if autre is not None:
                    constats.append(Constat(
                        ERREUR, n, f"le programme « {nom} » est défini "
                        f"deux fois (lignes {programmes[autre]} et {n})"))
                else:
                    programmes[nom] = n
                    bas[nom.lower()] = nom
                # ses paramètres sont des variables
                variables.update(re.findall(r'([A-Za-z_]\w*)\s*:',
                                            reste[len(nom):]))
            courant = nom
            pile.append((mot, n))
            continue
        if mot in _BLOCS:
            if not pile:
                constats.append(Constat(
                    ERREUR, n, f"« {mot} » hors d'un programme"))
                continue
            if mot in ('for', 'foreach'):
                v = _IDENT.match(reste)
                if v:
                    variables.add(v.group(1))
            pile.append((mot, n))
            continue
        if mot in _FERMETURES:
            attendu = _FERMETURES[mot]
            if not pile:
                constats.append(Constat(
                    ERREUR, n, f"« {mot} » sans « {attendu} »"))
                continue
            ouvert, ligne_ouv = pile[-1]
            if ouvert != attendu:
                if any(o == attendu for o, _l in pile):
                    # des blocs restés ouverts entre les deux
                    while pile and pile[-1][0] != attendu:
                        o, lo = pile.pop()
                        constats.append(Constat(
                            ERREUR, lo, f"« {o} » sans « {_BLOCS[o]} » "
                            f"(« {mot} » ligne {n})"))
                    pile.pop()
                else:
                    constats.append(Constat(
                        ERREUR, n, f"« {mot} » sans « {attendu} » (le "
                        f"bloc ouvert est « {ouvert} », ligne "
                        f"{ligne_ouv})"))
                continue
            pile.pop()
            continue
        if not pile or mot in _MOTS:
            continue
        # une instruction dans un programme
        if reste.startswith(':') and not reste.startswith('::'):
            variables.add(mot)              # déclaration `nom:type`
            continue
        if (reste[:1] == '=' and reste[1:2] != '=') \
                or reste[:1] in ('[', '.'):
            variables.add(mot)              # affectation, membre
            continue
        if '=' in reste:
            permis = du_manuel.get(mot)
            if permis is None and '::' in mot:
                # Engrave::StandardTextEngrave: la commande du manuel
                permis = du_manuel.get(mot.rsplit('::', 1)[1])
            if permis is not None:
                for p in _PARAMETRE.findall(reste):
                    if p not in permis:
                        vu = hors_manuel.get((mot, p))
                        if vu is None:
                            hors_manuel[(mot, p)] = [n, 1, courant,
                                                     permis]
                        else:
                            vu[1] += 1
        if '::' in mot:
            continue                        # commande d'un module importé
        if (courant, mot) not in vus:
            vus.add((courant, mot))
            appels.append((courant, n, mot, bool(reste)))

    for mot, n in pile:
        constats.append(Constat(
            ERREUR, n, f"« {mot} » sans « {_BLOCS[mot]} »"))

    # les blocs $$$
    blocs: Dict[str, int] = {}
    for i in range(debut_seq, len(brutes)):
        l = brutes[i]
        if l.startswith('$$$'):
            nom = l[3:].strip()
            if nom in blocs:
                constats.append(Constat(
                    ERREUR, i + 1, f"deux blocs « $$$ {nom} » (lignes "
                    f"{blocs[nom]} et {i + 1}): la machine n'en "
                    f"exécutera qu'un"))
            else:
                blocs[nom] = i + 1

    # ce que la machine exécute: le Main et ce qu'il appelle (appel
    # direct ou motif); un fichier sans Main (bibliothèque): tout
    racines = [p for p in programmes if p.lower() == 'main']
    atteints: Set[str] = set(racines or programmes)
    graphe: Dict[str, Set[str]] = {}
    for prog, _n, nom, *_p in appels + motifs:
        cible = _defini(nom)
        if cible is not None:
            graphe.setdefault(prog, set()).add(cible)
    a_voir = list(atteints)
    while a_voir:
        for cible in graphe.get(a_voir.pop(), ()):
            if cible not in atteints:
                atteints.add(cible)
                a_voir.append(cible)

    def _niveau(prog):
        return ERREUR if prog in atteints else AVERTISSEMENT

    def _ou(prog):
        return "" if prog in atteints else \
            f" (dans « {prog} », que rien n'appelle)"

    # les appels: un programme, une séquence, un programme externe, une
    # commande — sinon la machine s'arrête sur un nom inconnu
    noms_sequences = set(declarees) | set(blocs)
    appelees: Dict[str, tuple] = {}         # séquence → (prog, ligne)
    for prog, n, nom, params in appels:
        if nom in noms_sequences:
            if nom not in appelees or (prog in atteints
                                       and appelees[nom][0] not in atteints):
                appelees[nom] = (prog, n)
            continue
        if (_defini(nom) is not None or nom in modules or nom in connues
                or nom in variables):
            continue
        # seul sur sa ligne, dans un fichier sans autre module que Base:
        # c'est forcément l'appel d'un programme, d'une séquence ou d'un
        # programme externe — absent. Sinon peut-être une fonction
        # d'un module que le catalogue ne connaît pas.
        sur = not params and modules_connus
        constats.append(Constat(
            _niveau(prog) if sur else AVERTISSEMENT, n,
            f"« {nom} » n'est ni une commande connue, ni un programme, "
            f"ni une séquence de ce fichier{_ou(prog)}"))
    for prog, n, nom in motifs:
        if _defini(nom) is None:
            constats.append(Constat(
                _niveau(prog), n, f"le motif appelle « {nom} », que le "
                f"fichier ne définit pas{_ou(prog)}"))

    # les paramètres que la commande ne connaît pas (sauf si le
    # fichier définit un programme du même nom: c'est le sien). Le
    # manuel n'est pas exhaustif: seul un nom PROCHE d'un paramètre
    # connu (casse, lettre de trop ou de moins) est une faute de frappe
    # sûre; un nom sans voisin peut être un paramètre qu'il oublie
    for (cmd, p), (n, fois, prog, permis) in hors_manuel.items():
        if _defini(cmd) is not None or cmd in variables:
            continue
        proche = _proche(p, permis)
        if not proche:
            continue
        constats.append(Constat(
            AVERTISSEMENT, n, f"« {p} » n'est pas un paramètre de {cmd} "
            f"(manuel SimPL 3.1.1) — « {proche} » ?"
            + (f" ({fois} lignes)" if fois > 1 else "") + _ou(prog)))

    for nom, n in declarees.items():
        if nom in blocs:
            continue
        if nom in appelees:
            prog, ligne = appelees[nom]
            constats.append(Constat(
                _niveau(prog), ligne, f"la séquence « {nom} » est "
                f"appelée mais son bloc « $$$ {nom} » manque{_ou(prog)}"))
        else:
            constats.append(Constat(
                AVERTISSEMENT, n, f"la séquence « {nom} » est déclarée "
                f"sans bloc « $$$ {nom} »"))
    for nom, n in blocs.items():
        if nom not in declarees:
            constats.append(Constat(
                AVERTISSEMENT, n, f"le bloc « $$$ {nom} » n'est pas "
                f"déclaré (« sequence {nom} » en tête)"))

    if programmes and not vu_end and debut_seq < len(brutes):
        constats.append(Constat(
            AVERTISSEMENT, debut_seq + 1,
            "pas de « end » avant les blocs $$$"))

    if verifier_fichiers:
        constats += _fichiers_appeles(modules)

    constats.sort(key=lambda c: (c.ligne, c.niveau != ERREUR))
    return constats


def _fichiers_appeles(modules: Dict[str, tuple]) -> List[Constat]:
    """Un programme externe que le poste ne trouve pas: la machine le
    cherchera au même chemin (après le remplacement de chemin)."""
    import os
    from src.core.chemins_machine import chemin_local
    out = []
    for nom, (n, chemin) in modules.items():
        if not chemin:
            continue
        local = chemin_local(chemin)
        if os.path.isfile(local):
            continue
        # chemin réseau de la machine sans correspondance réglée sur ce
        # poste: on ne peut pas juger
        if local == chemin and chemin.lower().startswith('network:'):
            continue
        out.append(Constat(
            AVERTISSEMENT, n, f"programme externe « {nom} » introuvable "
            f"depuis ce poste: {chemin}"))
    return out


def erreurs(constats: List[Constat]) -> List[Constat]:
    return [c for c in constats if c.niveau == ERREUR]


def controler_fichiers(chemins, progression=None) -> List[tuple]:
    """[(chemin, constats ou None s'il est illisible)] — un dossier
    d'atelier entier, en rendant compte (Annuler lève vcarve.Annule)."""
    import os
    from src.core.vcarve import avancer
    sortie = []
    for k, chemin in enumerate(chemins):
        avancer(progression, k / max(1, len(chemins)),
                f"{os.path.basename(chemin)} ({k + 1}/{len(chemins)})")
        try:
            with open(chemin, encoding='utf-8-sig', errors='replace') as f:
                code = f.read()
        except (OSError, ValueError):
            sortie.append((chemin, None))
            continue
        sortie.append((chemin, controler(code)))
    avancer(progression, 1.0, f"{len(chemins)} programme(s) contrôlé(s)")
    return sortie


def rapport(resultats: List[tuple], par_fichier: int = 5) -> str:
    """Le compte rendu de `controler_fichiers`: les programmes en
    erreur d'abord, puis ceux qui n'ont que des avertissements (leurs
    premiers constats), le nombre de ceux qui n'ont rien."""
    import os

    def nom(chemin):
        return os.path.join(os.path.basename(os.path.dirname(chemin)),
                            os.path.basename(chemin))

    illisibles = [p for p, c in resultats if c is None]
    en_erreur = [(p, c) for p, c in resultats if c and erreurs(c)]
    a_voir = [(p, c) for p, c in resultats if c and not erreurs(c)]
    sains = [p for p, c in resultats if c is not None and not c]
    lignes = [f"Contrôle de structure: {len(resultats)} programme(s) — "
              f"{len(en_erreur)} avec erreur(s), {len(a_voir)} avec "
              f"avertissement(s) seulement, {len(sains)} sans remarque"
              + (f", {len(illisibles)} illisible(s)" if illisibles
                 else ""), ""]
    for groupe, signe in ((en_erreur, "✗"), (a_voir, "⚠")):
        for chemin, constats in groupe:
            n_err = len(erreurs(constats))
            n_av = len(constats) - n_err
            compte = ", ".join(x for x in (
                f"{n_err} erreur(s)" if n_err else "",
                f"{n_av} avertissement(s)" if n_av else "") if x)
            lignes.append(f"{signe} {nom(chemin)} — {compte}")
            for c in constats[:par_fichier]:
                lignes.append(f"    {c}")
            if len(constats) > par_fichier:
                lignes.append(f"    … et {len(constats) - par_fichier} "
                              f"autre(s)")
    for chemin in illisibles:
        lignes.append(f"? {nom(chemin)} — illisible")
    if sains:
        lignes.append(f"✓ {len(sains)} programme(s) sans remarque")
    return "\n".join(lignes)
