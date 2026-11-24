"""Le mini-formulaire des boutons « depuis la sélection ».

Avant de générer, la famille choisie demande ce qui lui manque — et
seulement ça: la profondeur et le type de filet pour un taraudage, la
profondeur et l'offset pour une forme, le côté de l'outil pour un
contour… plus « Regrouper dans la liste » et le nom du groupe.

Les champs se décrivent par des tuples (clé, libellé, genre, défaut,
options) — genre 'nombre', 'choix', 'case' ou 'texte' —, et
`valeurs()` rend un dict: le formulaire se pilote sans être ouvert.

Deux présentations des MÊMES champs (`ChampsFormulaire`): une fenêtre
(`MiniFormulaire`, « Générer les opérations… »), ou posés dans le
formulaire de l'opération, à côté de son bouton « Depuis la sélection
du canvas » (compacts: libellés courts, pas de fenêtre).
"""

from typing import Dict, List, Sequence, Tuple

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLabel,
                               QComboBox, QCheckBox, QLineEdit,
                               QDialogButtonBox, QWidget)

from src.gui.widgets import SpinCote

Champ = Tuple[str, str, str, object, dict]


class ChampsFormulaire(QWidget):
    """Les champs d'un mini-formulaire, sans fenêtre autour."""

    #: un champ a changé de valeur (sa clé)
    change = Signal(str)

    def __init__(self, champs: Sequence[Champ], parent=None,
                 compact: bool = False):
        super().__init__(parent)
        self._widgets: Dict[str, object] = {}
        self._genres: Dict[str, str] = {}
        form = QFormLayout(self)
        if compact:
            form.setContentsMargins(0, 0, 0, 0)
            form.setVerticalSpacing(2)
            form.setHorizontalSpacing(4)
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        for cle, libelle, genre, defaut, options in champs:
            options = options or {}
            if genre == 'nombre':
                w = SpinCote(decimales=int(options.get('decimales', 2)))
                w.setRange(float(options.get('min', -1000.0)),
                           float(options.get('max', 1000.0)))
                w.setValue(float(defaut or 0.0))
                if options.get('unite') and not compact:
                    libelle = f"{libelle} ({options['unite']})"
                w.valueChanged.connect(lambda _v, c=cle: self.change.emit(c))
            elif genre == 'choix':
                w = QComboBox()
                for c in options.get('choix', []):
                    w.addItem(str(c))
                i = w.findText(str(defaut))
                if i >= 0:
                    w.setCurrentIndex(i)
                w.currentIndexChanged.connect(
                    lambda _i, c=cle: self.change.emit(c))
            elif genre == 'case':
                w = QCheckBox()
                w.setChecked(bool(defaut))
                w.toggled.connect(lambda _o, c=cle: self.change.emit(c))
            else:
                w = QLineEdit(str(defaut or ""))
                w.editingFinished.connect(
                    lambda c=cle: self.change.emit(c))
            if options.get('bulle'):
                w.setToolTip(options['bulle'])
            if compact:
                # le libellé se replie sur deux lignes, la saisie garde
                # de quoi se lire
                w.setMinimumWidth({'nombre': 62, 'choix': 76,
                                   'texte': 96}.get(genre, 0))
            self._widgets[cle] = w
            self._genres[cle] = genre
            etiquette = QLabel(libelle)
            if compact:
                etiquette.setWordWrap(True)
                etiquette.setToolTip(libelle)
            form.addRow(etiquette, w)
        # l'avant-trou d'un filet suit le filet (deux pas plus bas),
        # tant qu'on ne l'a pas réglé soi-même
        self._avant_trou_libre = True
        self._pose_auto = False
        if {'depth', 'thread_name', 'profondeur_avant_trou'} <= set(
                self._widgets):
            self.change.connect(self._suivre_avant_trou)
        # « Nom du groupe » ne vaut que si l'on regroupe
        if 'grouper' in self._widgets and 'nom_groupe' in self._widgets:
            self._widgets['grouper'].toggled.connect(
                self._widgets['nom_groupe'].setEnabled)
            self._widgets['nom_groupe'].setEnabled(
                self._widgets['grouper'].isChecked())

    def _suivre_avant_trou(self, cle: str) -> None:
        if cle == 'profondeur_avant_trou':
            if not self._pose_auto:
                self._avant_trou_libre = False
            return
        if cle not in ('depth', 'thread_name') or not self._avant_trou_libre:
            return
        from src.operations.depuis_selection import profondeur_avant_trou
        v = self.valeurs()
        self._pose_auto = True
        try:
            self.regler('profondeur_avant_trou', profondeur_avant_trou(
                v['thread_name'], v['depth']))
        finally:
            self._pose_auto = False

    def widget(self, cle: str):
        return self._widgets.get(cle)

    def cles(self) -> List[str]:
        return list(self._widgets)

    def regler(self, cle: str, valeur) -> None:
        """Pose une valeur (pour piloter le formulaire sans l'ouvrir)."""
        w = self._widgets[cle]
        genre = self._genres[cle]
        if genre == 'nombre':
            w.setValue(float(valeur))
        elif genre == 'choix':
            w.setCurrentText(str(valeur))
        elif genre == 'case':
            w.setChecked(bool(valeur))
        else:
            w.setText(str(valeur))

    def valeurs(self) -> Dict[str, object]:
        sortie = {}
        for cle, w in self._widgets.items():
            genre = self._genres[cle]
            if genre == 'nombre':
                sortie[cle] = float(w.value())
            elif genre == 'choix':
                sortie[cle] = w.currentText()
            elif genre == 'case':
                sortie[cle] = w.isChecked()
            else:
                sortie[cle] = w.text().strip()
        return sortie


class MiniFormulaire(QDialog):

    def __init__(self, titre: str, champs: Sequence[Champ], parent=None,
                 explication: str = ""):
        super().__init__(parent)
        self.setWindowTitle(titre)
        self.setMinimumWidth(320)
        v = QVBoxLayout(self)
        if explication:
            lab = QLabel(explication)
            lab.setWordWrap(True)
            lab.setStyleSheet("color: #a6adc8;")
            v.addWidget(lab)
        self.champs = ChampsFormulaire(champs, self)
        v.addWidget(self.champs)
        boutons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        boutons.button(QDialogButtonBox.StandardButton.Ok).setText(
            "Générer")
        boutons.accepted.connect(self.accept)
        boutons.rejected.connect(self.reject)
        v.addWidget(boutons)

    def widget(self, cle: str):
        return self.champs.widget(cle)

    def regler(self, cle: str, valeur) -> None:
        self.champs.regler(cle, valeur)

    def valeurs(self) -> Dict[str, object]:
        return self.champs.valeurs()

    def demander(self):
        """Ouvre le formulaire: ses valeurs, ou None (annulé)."""
        return self.valeurs() if self.exec() else None


def champs_communs(nom_groupe: str) -> List[Champ]:
    return [('grouper', "Regrouper dans la liste", 'case', True,
             {'bulle': "Les opérations générées forment un ensemble "
                       "dans la liste: pliable, masquable, activable "
                       "d'un clic."}),
            ('nom_groupe', "Nom du groupe", 'texte', nom_groupe, {})]
