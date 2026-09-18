"""Persistent evidence registry (spec §5.3).

`EvidenceRegistryContract` still lives in `kgis.evidence.contract`, where Plan 2
put it, and is still exported from this package. The only change is *when* it is
imported: eagerly importing it here dragged `pytest` — a dev-only dependency —
into the import chain of `import kgis`, so the package was unimportable for
anyone who installed without the `[dev]` extra (issue #37).

PEP 562 `__getattr__`/`__dir__` make the attribute resolve on first access
instead. Both supported spellings are unchanged:

    from kgis.evidence import EvidenceRegistryContract   # resolved lazily here
    from kgis.evidence.contract import EvidenceRegistryContract

Accessing the name in an environment without `pytest` raises `ModuleNotFoundError`,
deliberately: the suite genuinely cannot be built there, and a loud failure naming
the missing dev extra beats a silent `AttributeError`. One consequence worth
knowing — `hasattr(kgis.evidence, "EvidenceRegistryContract")` raises rather than
returning `False`, because `hasattr` only swallows `AttributeError`. Probe with
`importlib.util.find_spec("pytest")` instead.
"""

from typing import TYPE_CHECKING, Any

from kgis.evidence.schema import open_evidence_db
from kgis.evidence.store import EvidenceNotFoundError, SqliteEvidenceRegistry

if TYPE_CHECKING:
    from kgis.evidence.contract import EvidenceRegistryContract

__all__ = [
    "EvidenceNotFoundError",
    "EvidenceRegistryContract",
    "SqliteEvidenceRegistry",
    "open_evidence_db",
]

# Names this package exports but does not import eagerly, because the module
# behind them needs a dev-only dependency. Kept in one place so the set is
# greppable and so `__dir__` and `__getattr__` cannot drift apart.
_LAZY = {"EvidenceRegistryContract": "kgis.evidence.contract"}


def __getattr__(name: str) -> Any:
    """Resolve a dev-only-dependent export on first access (PEP 562)."""
    module_name = _LAZY.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    return getattr(import_module(module_name), name)


def __dir__() -> list[str]:
    """Keep the lazy names visible to `dir()`, tab-completion and `pydoc`."""
    return sorted(set(globals()) | set(__all__))
