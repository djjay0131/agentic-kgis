"""Persistent evidence registry (spec §5.3).

`EvidenceRegistryContract` is the reusable pytest suite for this port. It now
lives in `kgis.testing.evidence` (spec §10.2) and is resolved here **lazily**:
the suite imports `pytest`, a dev-only dependency, and this module sits in the
runtime import chain of `import kgis`. Importing it eagerly made the whole
package unimportable without the `[dev]` extra (issue #37).

The name stays exported so `from kgis.evidence import EvidenceRegistryContract`
keeps working for adopters; it costs a `pytest` import only when accessed.
"""

from typing import TYPE_CHECKING, Any

from kgis.evidence.schema import open_evidence_db
from kgis.evidence.store import EvidenceNotFoundError, SqliteEvidenceRegistry

if TYPE_CHECKING:
    from kgis.testing.evidence import EvidenceRegistryContract

__all__ = [
    "EvidenceNotFoundError",
    "EvidenceRegistryContract",
    "SqliteEvidenceRegistry",
    "open_evidence_db",
]


def __getattr__(name: str) -> Any:
    """Resolve the pytest-dependent reusable suite on first access (PEP 562)."""
    if name == "EvidenceRegistryContract":
        from kgis.testing.evidence import EvidenceRegistryContract

        return EvidenceRegistryContract
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
