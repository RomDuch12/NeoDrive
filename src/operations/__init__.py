"""Import all operation modules to trigger @OperationRegistry.register decorators."""

from src.operations.registry import OperationRegistry  # noqa: F401

from src.operations import surfacage_rectangle   # noqa: F401
from src.operations import surfacage_cercle      # noqa: F401
from src.operations import decoupe_rectangle     # noqa: F401
from src.operations import decoupe_cercle        # noqa: F401
from src.operations import percage_fraise        # noqa: F401
from src.operations import percage_foret         # noqa: F401
from src.operations import poche_rectangle       # noqa: F401
from src.operations import gravure_texte         # noqa: F401
from src.operations import taraudage             # noqa: F401
from src.operations import decalage_origine      # noqa: F401
from src.operations import dialogue_operateur    # noqa: F401
from src.operations import fonction_custom       # noqa: F401
from src.operations import bpm                   # noqa: F401
from src.operations import appel_programme       # noqa: F401
from src.operations import appel_outil           # noqa: F401
from src.operations import helice                # noqa: F401
from src.operations import palpage_z             # noqa: F401
from src.operations import palpage_symetrie      # noqa: F401
from src.operations import taraudage_brut        # noqa: F401
from src.operations import prechauffage_broche   # noqa: F401
from src.operations import parametres_operateur  # noqa: F401
from src.operations import compteur_pieces       # noqa: F401
from src.operations import mesure_orientation    # noqa: F401
from src.operations import miroir                # noqa: F401
from src.operations import retablir_miroir       # noqa: F401
from src.operations import sequence_datron
from src.operations import trace    # noqa: F401
from src.operations import import_programme    # noqa: F401
from src.operations import bloc_simpl            # noqa: F401
from src.operations import palpage_rectangle     # noqa: F401
from src.operations import retournement_piece    # noqa: F401
from src.operations import palpage_memorise      # noqa: F401
from src.operations import gravure_2d5           # noqa: F401
from src.operations import gamme_gravure         # noqa: F401
from src.operations import texte_grave           # noqa: F401
from src.operations import ebavurage             # noqa: F401
# fonctions SimPL du manuel 3.1.1 (octobre 2026)
from src.operations import poche_cercle          # noqa: F401
from src.operations import rotation_repere       # noqa: F401
from src.operations import palpage_coin          # noqa: F401
from src.operations import palpage_arete         # noqa: F401
from src.operations import palpage_u             # noqa: F401
from src.operations import table_vide            # noqa: F401
from src.operations import repere_local          # noqa: F401
from src.operations import message_operateur     # noqa: F401
from src.operations import mesure_outil          # noqa: F401
from src.operations import filetage_special      # noqa: F401
from src.operations import mouvement             # noqa: F401
# toutes les autres commandes du manuel, une opération chacune
from src.operations import commandes_manuel      # noqa: F401
# les lignes qu'un Main importé exécute lui-même (octobre 2026)
from src.operations import lignes_main           # noqa: F401
