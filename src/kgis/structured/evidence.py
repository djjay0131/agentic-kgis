"""Evidence for structured-sync rows, produced and linked idempotently.

A deterministic read of a source row is still an *observation*, and spec §5.3
says an observation must leave first-class Evidence that is never silently
dropped. This module produces one `PRESENT` Evidence per source record and
links the candidates built from that row to it through the evidence registry,
so a candidate's support is resolvable (`registry.resolve(candidate_id)`)
rather than implied.

Two things keep it honest and idempotent:

- **Deterministic evidence IDs.** An evidence id is a digest of the source
  coordinates plus the snapshot version, so re-collecting the same row's
  evidence produces the same id — the registry's `INSERT OR REPLACE` makes a
  re-run a no-op, matching the ledger's cross-run idempotency.

- **Linking without touching the builders.** Candidates carry their
  `source_coordinates`; a built candidate is linked to its row's evidence by
  matching those coordinates, via `registry.add_refs(candidate_id, ...)`
  (`INSERT OR IGNORE`, so re-linking is idempotent too). The frozen candidate
  builders are never modified, and the frozen contract is never touched —
  evidence lives entirely in the registry, keyed by candidate id.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import datetime

from kg_contracts.candidates import Candidate, SourceCoordinates
from kg_contracts.evidence import (
    EvidenceRef,
    EvidenceRelationship,
    Provenance,
    present_evidence,
)
from kgis.clock import Clock, SystemClock
from kgis.evidence.store import SqliteEvidenceRegistry
from kgis.ids import stable_suffix
from kgis.records import SourceRecord

_CoordKey = tuple[str, str, str | None]


def _coord_key(coordinates: SourceCoordinates) -> _CoordKey:
    return (coordinates.source_type, coordinates.locator, coordinates.fragment)


def source_evidence_id(coordinates: SourceCoordinates, snapshot_version: str) -> str:
    """A deterministic, citable evidence id for one source row.

    Keyed on the coordinates (already snapshot-bearing when the reader stamps
    the version into the locator) plus the version, so re-collection is
    idempotent (`present_evidence` is `INSERT OR REPLACE`d)."""
    return "ev_" + stable_suffix(
        coordinates.source_type,
        coordinates.locator,
        coordinates.fragment or "",
        snapshot_version,
    )


def _row_payload_hash(data: dict[str, object]) -> str:
    encoded = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
    return "b2:" + hashlib.blake2b(encoded, digest_size=16).hexdigest()


class StructuredEvidenceRecorder:
    """Produces and links Evidence for the rows of one structured snapshot."""

    def __init__(
        self,
        registry: SqliteEvidenceRegistry,
        *,
        snapshot_version: str,
        source_type: str,
        source_locator: str,
        actor: str = "kgis.structured",
        clock: Clock | None = None,
        relationship: EvidenceRelationship = EvidenceRelationship.DERIVED_FROM,
    ) -> None:
        self._registry = registry
        self._snapshot_version = snapshot_version
        self._provenance = Provenance(
            source=source_type, source_ref=source_locator, actor=actor
        )
        self._clock = clock if clock is not None else SystemClock()
        self._relationship = relationship
        self._by_coord: dict[_CoordKey, str] = {}

    def record(self, records: Iterable[SourceRecord]) -> dict[_CoordKey, str]:
        """Store one PRESENT Evidence per record; return coord → evidence_id.

        Deterministic `observed_at` (inject a `FixedClock`) keeps the stored
        Evidence byte-identical across re-runs, so the registry write is a true
        idempotent replay.
        """
        observed_at: datetime = self._clock.now()
        for record in records:
            evidence_id = source_evidence_id(record.coordinates, self._snapshot_version)
            evidence = present_evidence(
                evidence_id=evidence_id,
                source_type=record.coordinates.source_type,
                source_locator=record.coordinates.locator,
                observed_at=observed_at,
                provenance=self._provenance,
                payload_hash=_row_payload_hash(record.data),
            )
            self._registry.put(evidence)
            self._by_coord[_coord_key(record.coordinates)] = evidence_id
        return dict(self._by_coord)

    def link(self, candidates: Iterable[Candidate]) -> int:
        """Link each candidate to its source row's evidence. Returns links made.

        Idempotent: `add_refs` is `INSERT OR IGNORE`, so re-linking a candidate
        adds nothing. A candidate whose coordinates were never recorded is
        skipped rather than fabricating a citation.
        """
        linked = 0
        for candidate in candidates:
            evidence_id = self._by_coord.get(_coord_key(candidate.source_coordinates))
            if evidence_id is None:
                continue
            self._registry.add_refs(
                candidate.candidate_id,
                [EvidenceRef(evidence_id=evidence_id, relationship=self._relationship)],
            )
            linked += 1
        return linked
