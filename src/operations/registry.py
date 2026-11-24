"""
Registre global des opérations disponibles.
Chaque opération s'enregistre via le décorateur @OperationRegistry.register
"""

from typing import Dict, Type, List
from src.operations.base_operation import AbstractOperation


class OperationRegistry:
    """Registre singleton des opérations."""
    _registry: Dict[str, Type[AbstractOperation]] = {}

    @classmethod
    def register(cls, op_type: str):
        """Décorateur pour enregistrer une opération."""
        def decorator(op_class: Type[AbstractOperation]):
            op_class.OP_TYPE = op_type
            cls._registry[op_type] = op_class
            return op_class
        return decorator

    @classmethod
    def get(cls, op_type: str) -> Type[AbstractOperation]:
        """Récupère une classe d'opération par son type."""
        if op_type not in cls._registry:
            raise KeyError(f"Opération inconnue: {op_type}")
        return cls._registry[op_type]

    @classmethod
    def get_all(cls) -> Dict[str, Type[AbstractOperation]]:
        """Retourne toutes les opérations enregistrées."""
        return dict(cls._registry)

    @classmethod
    def get_by_category(cls) -> Dict[str, List[Type[AbstractOperation]]]:
        """Retourne les opérations groupées par catégorie."""
        result: Dict[str, List[Type[AbstractOperation]]] = {}
        for op_class in cls._registry.values():
            cat = op_class.CATEGORY
            if cat not in result:
                result[cat] = []
            result[cat].append(op_class)
        return result

    @classmethod
    def get_display_list(cls) -> List[dict]:
        """Retourne une liste triée pour l'affichage dans le menu."""
        items = []
        for op_type, op_class in cls._registry.items():
            items.append({
                'type': op_type,
                'name': op_class.DISPLAY_NAME,
                'category': op_class.CATEGORY,
                'description': op_class.DESCRIPTION,
                'icon': op_class.ICON,
            })
        return sorted(items, key=lambda x: (x['category'], x['name']))
