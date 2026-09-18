"""Reusable test suites and fixtures for `kgis` ports (spec §10.2).

Mirrors `kg_contracts.testing`: an implementation of a `kgis` port proves
itself by passing the same suite every other implementation passes, so
downstream repos writing their own readers get the rules for free.

Suites that import `pytest` are **not** re-exported here: import them from
their own module (`from kgis.testing.evidence import
EvidenceRegistryContract`). That keeps `import kgis.testing` itself free of
the dev-only dependency.
"""

from kgis.testing.contract import CANONICAL_RECORDS, RecordReaderContract

__all__ = ["CANONICAL_RECORDS", "RecordReaderContract"]
