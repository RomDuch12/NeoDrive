"""
Module de configuration des paramètres par défaut pour chaque opération.
Charge/sauvegarde dans data/default_params.json.
L'utilisateur peut personnaliser les valeurs par défaut sans toucher au code.
"""

import os
from typing import Dict, Any
from src.operations.registry import OperationRegistry
from src.core.tool_library import get_base_dir


DEFAULT_PARAMS_FILE = "default_params.json"


class DefaultParamsConfig:
    """Gère les paramètres par défaut personnalisés par opération."""

    def __init__(self):
        self._params: Dict[str, Dict[str, Any]] = {}
        self._filepath = os.path.join(
            get_base_dir(), "data", DEFAULT_PARAMS_FILE)
        self.load()

    def load(self):
        """Charge les paramètres par défaut depuis le fichier JSON."""
        # illisible: mis de côté, .bak repris — jamais écrasé ensuite
        from src.core.fichiers_surs import lire_json
        lu = lire_json(self._filepath, {})
        self._params = lu if isinstance(lu, dict) else {}

    def save(self):
        """Sauvegarde les paramètres par défaut dans le fichier JSON."""
        from src.core.fichiers_surs import ecrire_json_sur
        ecrire_json_sur(self._filepath, self._params, garder_bak=True,
                        indent=2, ensure_ascii=False)

    def get_defaults(self, op_type: str) -> Dict[str, Any]:
        """
        Retourne les paramètres par défaut pour une opération.
        Fusionne les defaults du code avec les overrides utilisateur.
        """
        try:
            op_class = OperationRegistry.get(op_type)
            code_defaults = op_class.get_default_params()
        except KeyError:
            code_defaults = {}

        user_overrides = self._params.get(op_type, {})
        merged = {**code_defaults, **user_overrides}
        return merged

    def set_defaults(self, op_type: str, params: Dict[str, Any]):
        """Définit les paramètres par défaut personnalisés pour une opération."""
        self._params[op_type] = params
        self.save()

    def reset_defaults(self, op_type: str):
        """Supprime les overrides utilisateur pour une opération."""
        if op_type in self._params:
            del self._params[op_type]
            self.save()

    def get_all_custom(self) -> Dict[str, Dict[str, Any]]:
        """Retourne tous les overrides utilisateur."""
        return self._params.copy()

    def generate_template(self):
        """
        Génère un fichier template avec tous les paramètres par défaut
        de toutes les opérations enregistrées.
        """
        template = {}
        for op_type, op_class in OperationRegistry.get_all().items():
            template[op_type] = {
                '_display_name': op_class.DISPLAY_NAME,
                **op_class.get_default_params()
            }
        return template
