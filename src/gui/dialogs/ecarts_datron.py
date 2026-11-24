"""Les écarts entre le webshop DATRON et NeoDrive, avant de les
appliquer (src/core/maj_datron).

Une référence par branche; dessous, ce qui changerait au catalogue
(D1, L2, angle…) et à chaque fiche de tools.json de cette référence
(Diameter, TipAngle, FluteLength…). Tout est coché: décocher ce qu'on
garde. Rien ne s'écrit avant « Appliquer ».
"""

from typing import Dict, List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHeaderView, QLabel, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout
)

#: rôles des lignes: (genre, référence, tool_id ou "", clé)
ROLE = Qt.ItemDataRole.UserRole + 3


def _v(x) -> str:
    if x in (None, ""):
        return "—"
    try:
        f = float(x)
        return f"{f:g}"
    except (TypeError, ValueError):
        return str(x)


class DialogueEcartsDatron(QDialog):

    def __init__(self, propositions: List[Dict], erreurs: List[str] = (),
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mise à jour depuis datron.de — écarts")
        self.resize(760, 520)
        self._props = list(propositions)
        n = len(self._props)
        entete = QLabel(
            f"{n} référence(s) diffèrent du webshop DATRON. Décochez ce que "
            "vous gardez; « Appliquer » écrit le reste (le catalogue livré "
            "n'est pas réécrit: ses mises à jour vont dans "
            "catalogue_datron_maj.json).")
        entete.setWordWrap(True)
        self.arbre = QTreeWidget()
        self.arbre.setColumnCount(4)
        self.arbre.setHeaderLabels(["Référence / cote", "Actuel",
                                    "datron.de", ""])
        self.arbre.header().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        for p in self._props:
            racine = QTreeWidgetItem([p['ref'], "", "", p.get('date', '')])
            racine.setFlags(racine.flags() | Qt.ItemFlag.ItemIsUserCheckable
                            | Qt.ItemFlag.ItemIsAutoTristate)
            racine.setCheckState(0, Qt.CheckState.Checked)
            racine.setToolTip(0, p.get('url', ''))
            self.arbre.addTopLevelItem(racine)
            if p['ecarts_catalogue']:
                cat = QTreeWidgetItem(racine, ["Catalogue", "", "", ""])
                cat.setFlags(cat.flags() | Qt.ItemFlag.ItemIsUserCheckable
                             | Qt.ItemFlag.ItemIsAutoTristate)
                for cle, nom, avant, apres in p['ecarts_catalogue']:
                    it = QTreeWidgetItem(cat, [nom, _v(avant), _v(apres), ""])
                    it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    it.setCheckState(0, Qt.CheckState.Checked)
                    it.setData(0, ROLE, ('catalogue', p['ref'], "", cle))
            for tid, (nom_outil, ecarts) in p['ecarts_outils'].items():
                br = QTreeWidgetItem(racine, [f"Fiche « {nom_outil} »",
                                              "", "", ""])
                br.setFlags(br.flags() | Qt.ItemFlag.ItemIsUserCheckable
                            | Qt.ItemFlag.ItemIsAutoTristate)
                for cle, nom, avant, apres in ecarts:
                    it = QTreeWidgetItem(br, [nom, _v(avant), _v(apres), ""])
                    it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    it.setCheckState(0, Qt.CheckState.Checked)
                    it.setData(0, ROLE, ('outil', p['ref'], tid, cle))
            racine.setExpanded(True)
        texte_err = ""
        if erreurs:
            texte_err = ("Non lues: " + "; ".join(list(erreurs)[:8])
                         + ("…" if len(erreurs) > 8 else ""))
        self.erreurs = QLabel(texte_err)
        self.erreurs.setWordWrap(True)
        self.erreurs.setStyleSheet("color: #fab387;")
        boutons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.appliquer_btn = boutons.addButton(
            "Appliquer", QDialogButtonBox.ButtonRole.AcceptRole)
        self.appliquer_btn.setObjectName("primary")
        boutons.accepted.connect(self.accept)
        boutons.rejected.connect(self.reject)
        v = QVBoxLayout(self)
        v.addWidget(entete)
        v.addWidget(self.arbre, 1)
        v.addWidget(self.erreurs)
        v.addWidget(boutons)

    def lignes(self):
        """Toutes les lignes cochables (feuilles), pour les tests."""
        sortie = []

        def parcourir(item):
            for i in range(item.childCount()):
                enfant = item.child(i)
                if enfant.data(0, ROLE):
                    sortie.append(enfant)
                parcourir(enfant)
        for i in range(self.arbre.topLevelItemCount()):
            parcourir(self.arbre.topLevelItem(i))
        return sortie

    def choix(self) -> List[Dict]:
        """Ce que maj_datron.appliquer reçoit: les cotes cochées."""
        par_ref: Dict[str, Dict] = {}
        for p in self._props:
            par_ref[p['ref']] = {'ref': p['ref'], 'cotes': p['cotes'],
                                 'url': p.get('url', ''),
                                 'date': p.get('date', ''),
                                 'catalogue': [], 'outils': {}}
        for it in self.lignes():
            if it.checkState(0) != Qt.CheckState.Checked:
                continue
            genre, ref, tid, cle = it.data(0, ROLE)
            c = par_ref[ref]
            if genre == 'catalogue':
                c['catalogue'].append(cle)
            else:
                c['outils'].setdefault(tid, []).append(cle)
        return [c for c in par_ref.values()
                if c['catalogue'] or c['outils']]
