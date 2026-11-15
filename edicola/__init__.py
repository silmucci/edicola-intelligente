"""Edicola Digitale Intelligente: moduli organizzati per area funzionale.

Compatibilità: i moduli mantengono i nomi pubblici storici edicola.<nome>.
Le directory seguenti sono percorsi di ricerca Python aggiuntivi, non nuovi
namespace di importazione: evitare import edicola.<gruppo>.<nome> per non
caricare due volte gli stessi moduli e duplicarne lo stato in memoria.
"""

from pathlib import Path

# Moduli raggruppati per funzionalità, senza cambiare le API Python esistenti.
_GROUPS = (
    "ui",
    "podcast",
    "chat",
    "retrieval",
    "pdf",
    "editorial",
    "knowledge",
    "personalization",
    "evaluation",
    "infrastructure",
    "maintenance",
)

_PACKAGE_ROOT = Path(__file__).resolve().parent
for _group in _GROUPS:
    __path__.append(str(_PACKAGE_ROOT / _group))

del _group, _PACKAGE_ROOT
