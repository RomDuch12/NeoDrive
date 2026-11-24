"""Opération: Paramètres opérateur (InputDialog).

Affiche au LANCEMENT du programme une boîte de saisie: l'opérateur
entre des cotes, avances, quantités… qui sont rangées dans des
variables SimPl réutilisables par les opérations suivantes.

Format officiel Datron (Dialogs/UserInputDialogs.simpl):

    inputs:InputParameter[] = {
        PositionParameter description="Profondeur" default = 5,
        QuantityParameter description="Nombre" default = 4 unit="pièces"
    }
    InputDialog parameters <- inputs caption="Réglages"
    profondeur = inputs[0].NumberValue

Deux points critiques du format:
  - la liste se passe avec l'opérateur `<-`, PAS avec `=`;
  - la valeur se relit selon le type: NumberValue, StringValue,
    BooleanValue.

Les variables déclarées ici sont utilisables dans les autres
opérations via leur section « Variables opérateur ».
"""

from typing import List, Dict, Any
from src.operations.base_operation import (
    AbstractOperation, ParameterDef, ParameterType, ToolRequirement
)
from src.operations.registry import OperationRegistry

#: type NeoDrive -> (mot-clé Datron, accesseur de valeur, type SimPl)
PARAM_TYPES = {
    "Position": ("PositionParameter", "NumberValue", "number"),
    "Avance": ("FeedParameter", "NumberValue", "number"),
    "Angle": ("AngularPositionParameter", "NumberValue", "number"),
    "Nombre": ("NumberParameter", "NumberValue", "number"),
    "Quantité": ("QuantityParameter", "NumberValue", "number"),
    "Texte": ("StringParameter", "StringValue", "string"),
    "Booléen": ("BooleanParameter", "BooleanValue", "boolean"),
}


def sanitize_var(name: str, fallback: str = "param") -> str:
    """Nom de variable SimPl valide (lettres, chiffres, _)."""
    import re
    import unicodedata
    txt = unicodedata.normalize('NFKD', str(name or ''))
    txt = txt.encode('ascii', 'ignore').decode('ascii')
    txt = re.sub(r'[^A-Za-z0-9_]', '_', txt).strip('_')
    if not txt or txt[0].isdigit():
        txt = f"{fallback}_{txt}" if txt else fallback
    return txt


@OperationRegistry.register("parametres_operateur")
class ParametresOperateur(AbstractOperation):
    OP_TYPE = "parametres_operateur"
    DISPLAY_NAME = "Paramètres opérateur"
    CATEGORY = "Utilitaire"
    HORS_MATIERE = True
    DESCRIPTION = ("Boîte de saisie au lancement: l'opérateur entre "
                   "des valeurs rangées dans des variables réutilisables")
    ICON = "dialogue"
    INLINE = True
    REQUIRES_TOOL = False
    REQUIRES_COORDINATES = False
    SUPPORTS_MULTI_POINT = False
    # Réservée au mode expert: elle rend le programme paramétrique
    # (les cotes ne sont plus figées dans le fichier)
    EXPERT_ONLY = True

    @classmethod
    def get_parameters(cls) -> List[ParameterDef]:
        return [
            ParameterDef("caption", "Titre", ParameterType.STRING,
                         default="Réglages pièce", group="Dialogue",
                         tooltip="Titre de la fenêtre de saisie"),
            ParameterDef("enable_markdown", "Markdown",
                         ParameterType.BOOL, default=False,
                         group="Dialogue", expert_only=True,
                         tooltip="Autorise le formatage Markdown dans "
                                 "les en-têtes de champs"),
        ]

    @classmethod
    def get_tool_requirement(cls) -> ToolRequirement:
        return ToolRequirement(tool_types=[], description="")

    # ── Champs de saisie (params['fields']) ──

    @classmethod
    def fields(cls, params: Dict[str, Any]) -> List[dict]:
        """Champs valides, nom de variable assaini et dédoublonné."""
        out = []
        seen = set()
        for i, f in enumerate(params.get('fields') or []):
            ptype = f.get('type', 'Position')
            if ptype not in PARAM_TYPES:
                continue
            var = sanitize_var(f.get('var') or f.get('label') or '',
                               f"param{i + 1}")
            base = var
            k = 2
            while var in seen:
                var = f"{base}_{k}"
                k += 1
            seen.add(var)
            out.append({
                'var': var,
                'type': ptype,
                'label': str(f.get('label') or var),
                'default': f.get('default', 0),
                'unit': str(f.get('unit') or ''),
            })
        return out

    @classmethod
    def declared_variables(cls, params: Dict[str, Any]) -> List[tuple]:
        """[(nom_variable, type_simpl), ...] à déclarer en tête de
        module (les variables SimPl sont déclarées hors programme)."""
        return [(f['var'], PARAM_TYPES[f['type']][2])
                for f in cls.fields(params)]

    @classmethod
    def _format_default(cls, field: dict) -> str:
        ptype = field['type']
        val = field.get('default', 0)
        if ptype == "Texte":
            txt = str(val).replace('"', "'")
            return f'"{txt}"'
        if ptype == "Booléen":
            truthy = val if isinstance(val, bool) else \
                str(val).strip().lower() in ('1', 'true', 'vrai', 'oui')
            return "true" if truthy else "false"
        try:
            num = float(val)
        except (TypeError, ValueError):
            num = 0.0
        return f"{num:g}"

    @classmethod
    def generate_operation_code(cls, params: Dict[str, Any]) -> str:
        """Déclaration des champs, dialogue, puis affectation des
        variables — émis inline au début du Main."""
        defaults = cls.get_default_params()
        p = {**defaults, **params}
        fields = cls.fields(p)
        if not fields:
            return "    # Paramètres opérateur: aucun champ défini"

        caption = str(p.get('caption') or 'Réglages').replace('"', "'")
        lines = ["    # ── Saisie opérateur au lancement ──",
                 "    inputs:InputParameter[] = {"]
        for i, f in enumerate(fields):
            kw = PARAM_TYPES[f['type']][0]
            label = f['label'].replace('"', "'")
            part = (f'        {kw} description="{label}" '
                    f'default = {cls._format_default(f)}')
            if f['unit'] and f['type'] in ("Nombre", "Quantité"):
                part += f' unit="{f["unit"]}"'
            if i < len(fields) - 1:
                part += ','
            lines.append(part)
        lines.append("    }")
        # ATTENTION: l'opérateur <- est OBLIGATOIRE ici (pas de =)
        markdown = " enableMarkdown" if p.get('enable_markdown') else ""
        lines.append(f'    InputDialog parameters <- inputs '
                     f'caption = "{caption}"{markdown}')
        for i, f in enumerate(fields):
            accessor = PARAM_TYPES[f['type']][1]
            lines.append(f"    {f['var']} = inputs[{i}].{accessor}")
        return "\n".join(lines)

    @classmethod
    def validate_params(cls, params: Dict[str, Any]) -> List[str]:
        errors = []
        if not cls.fields(params):
            errors.append("Aucun champ de saisie défini")
        return errors
