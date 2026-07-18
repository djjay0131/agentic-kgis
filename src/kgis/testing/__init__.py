"""Reusable test suites and fixtures for `kgis` ports (spec §10.2).

Mirrors `kg_contracts.testing`: an implementation of a `kgis` port proves
itself by passing the same suite every other implementation passes, so
downstream repos writing their own readers get the rules for free.
"""

from kgis.testing.contract import CANONICAL_RECORDS, RecordReaderContract

__all__ = ["CANONICAL_RECORDS", "RecordReaderContract"]
