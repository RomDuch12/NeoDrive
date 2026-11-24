"""Le contrôle de structure (src.core.controle_simpl) dans l'interface.

- `IndicateurStructure`: le bouton « ✓ Structure / ⚠ n / ✗ n » sous un
  éditeur de code (panneau Code, Édition SimPl); le détail en
  infobulle, un clic mène à la ligne du premier constat.
- `confirmer_structure`: les constats avant d'écrire le code (export,
  enregistrement), et l'opérateur décide.
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QMessageBox, QPushButton

from src.gui.theme import COLORS


class IndicateurStructure(QPushButton):
    """Le résumé du contrôle de structure du code d'un éditeur."""

    #: au-delà, le contrôle attend l'export (il prend ~3 µs par ligne)
    LIGNES_CONTROLE_DIRECT = 60000
    #: le contrôle part ce délai après la dernière modification (ms)
    DELAI = 700

    def __init__(self, editeur, parent=None):
        super().__init__("", parent)
        self.editeur = editeur
        self.constats = []
        self.setFlat(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self.aller_au_constat)
        self.setVisible(False)
        self.minuterie = QTimer(self)
        self.minuterie.setSingleShot(True)
        self.minuterie.setInterval(self.DELAI)
        self.minuterie.timeout.connect(self.controler)

    def planifier(self) -> None:
        """Un contrôle bientôt (le code change encore peut-être)."""
        self.minuterie.start()

    def controler(self) -> list:
        """Contrôle le code de l'éditeur et le résume: ✓, ⚠ n ou ✗ n."""
        from src.core import controle_simpl
        code = self.editeur.toPlainText()
        corps = code.split('\n$$$', 1)[0]
        if corps.count('\n') > self.LIGNES_CONTROLE_DIRECT:
            self.constats = []
            self.setText("Structure : contrôlée à l'export")
            self.setToolTip(
                "Programme trop long pour un contrôle à chaque "
                "modification: il sera contrôlé à l'export.")
            self.setStyleSheet(
                f"color: {COLORS['text_muted']}; font-size: 11px;")
            self.setVisible(bool(code.strip()))
            return []
        try:
            self.constats = controle_simpl.controler(
                code, verifier_fichiers=False)
        except Exception:
            self.constats = []
        erreurs = controle_simpl.erreurs(self.constats)
        if erreurs:
            texte, couleur = f"✗ {len(erreurs)} erreur(s)", COLORS['red']
        elif self.constats:
            texte = f"⚠ {len(self.constats)} avertissement(s)"
            couleur = COLORS['orange']
        else:
            texte, couleur = "✓ Structure", COLORS['green']
        self.setText(texte)
        self.setStyleSheet(f"color: {couleur}; font-size: 11px;")
        detail = "\n".join(str(c) for c in self.constats[:15])
        if len(self.constats) > 15:
            detail += f"\n… et {len(self.constats) - 15} autres"
        self.setToolTip(
            detail + "\n\nClic: aller à la ligne" if self.constats else
            "Séquences, programmes appelés, blocs if/for… et noms "
            "de paramètres concordent.")
        self.setVisible(bool(code.strip()))
        return self.constats

    def aller_au_constat(self) -> None:
        """La ligne du premier constat (une erreur avant un
        avertissement), dépliée et sélectionnée."""
        from src.core import controle_simpl
        cible = next(iter(controle_simpl.erreurs(self.constats)
                          or self.constats), None)
        if cible is None or not cible.ligne:
            return
        editeur = self.editeur
        bloc = editeur.document().findBlockByNumber(cible.ligne - 1)
        if not bloc.isValid():
            return
        deplier = getattr(editeur, 'ensure_line_visible', None)
        if callable(deplier):
            deplier(cible.ligne - 1)
        curseur = QTextCursor(bloc)
        curseur.select(QTextCursor.SelectionType.LineUnderCursor)
        editeur.setTextCursor(curseur)
        editeur.ensureCursorVisible()
        editeur.setFocus()


def confirmer_structure(parent, code: str, action: str = "Exporter",
                        avertissements: bool = True) -> bool:
    """Le contrôle de structure du code tel qu'il part (fichiers des
    programmes externes compris): une séquence appelée sans son bloc
    $$$, un programme appelé absent, un `if` sans `endif`… Rend True
    pour écrire. Les erreurs demandent confirmation (Non par défaut);
    les avertissements seuls aussi si `avertissements` (Oui par
    défaut)."""
    from src.core import controle_simpl
    try:
        constats = controle_simpl.controler(code)
    except Exception:
        return True
    erreurs = controle_simpl.erreurs(constats)
    if not erreurs and not (constats and avertissements):
        return True
    detail = "\n".join(str(c) for c in constats[:20])
    if len(constats) > 20:
        detail += f"\n… et {len(constats) - 20} autres"
    oui, non = (QMessageBox.StandardButton.Yes,
                QMessageBox.StandardButton.No)
    if erreurs:
        reponse = QMessageBox.warning(
            parent, "⚠ Structure du programme",
            f"{len(erreurs)} erreur(s) que la machine refuserait au "
            f"chargement ou exécuterait de travers:\n\n{detail}\n\n"
            f"{action} quand même ?", oui | non, non)
    else:
        reponse = QMessageBox.warning(
            parent, "Structure du programme",
            f"{len(constats)} avertissement(s):\n\n{detail}\n\n"
            f"{action} quand même ?", oui | non, oui)
    return reponse == oui
