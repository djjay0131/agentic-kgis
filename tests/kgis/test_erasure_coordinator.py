"""Erasure cascade across the ledger and the evidence registry (issue #61)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest

from kg_contracts.evidence import (
    EvidenceAvailability,
    EvidenceRef,
    EvidenceRelationship,
    Provenance,
    TextSpan,
    present_evidence,
)
from kg_contracts.testing.factories import make_entity_candidate

from kgis.erasure import ErasureCoordinator, ErasureIncompleteError
from kgis.errors import ConfigurationError
from kgis.evidence.schema import SCHEMA_SQL as EVIDENCE_SCHEMA
from kgis.evidence.store import SqliteEvidenceRegistry
from kgis.extraction.documents import Document
from kgis.extraction.provenance import build_document_evidence, document_evidence_id
from kgis.ledger.config import BASEBALL_AI_PROFILE, ConsumerProfile
from kgis.ledger.schema import SCHEMA_SQL as LEDGER_SCHEMA
from kgis.ledger.store import SqliteCandidateLedger

NOW = datetime(2026, 10, 8, tzinfo=UTC)
PROV = Provenance(source="test", actor="tester")
DERIVED_FROM = EvidenceRelationship.DERIVED_FROM


class _FlakyCommitConnection(sqlite3.Connection):
    """A connection whose `commit()` can be armed to fail (separate-path test)."""

    fail_commit = False

    def commit(self) -> None:
        if self.fail_commit:
            raise sqlite3.OperationalError("simulated commit failure")
        super().commit()


def _shared_connection() -> sqlite3.Connection:
    """One connection carrying both the ledger and evidence schemas."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(LEDGER_SCHEMA)
    conn.executescript(EVIDENCE_SCHEMA)
    conn.commit()
    return conn


def _make_stores(
    shared: bool,
) -> tuple[SqliteCandidateLedger, SqliteEvidenceRegistry]:
    if shared:
        conn = _shared_connection()
        ledger = SqliteCandidateLedger(conn, profile=BASEBALL_AI_PROFILE)
        registry = SqliteEvidenceRegistry(conn)
    else:
        ledger = SqliteCandidateLedger(":memory:", profile=BASEBALL_AI_PROFILE)
        registry = SqliteEvidenceRegistry(":memory:")
    return ledger, registry


def _cite(registry: SqliteEvidenceRegistry, subject_id: str, evidence_id: str) -> None:
    registry.add_refs(
        subject_id, [EvidenceRef(evidence_id=evidence_id, relationship=DERIVED_FROM)]
    )


def _present(
    registry: SqliteEvidenceRegistry,
    evidence_id: str,
    *,
    content: str = "secret passage text",
    payload_hash: str | None = "ph:original",
) -> None:
    registry.put(
        present_evidence(
            evidence_id=evidence_id,
            source_type="document",
            source_locator=f"doc#{evidence_id}",
            observed_at=NOW,
            content=content,
            payload_hash=payload_hash,
            provenance=PROV,
        )
    )


def _present_quote_only(
    registry: SqliteEvidenceRegistry,
    evidence_id: str,
    *,
    quote: str,
    start: int,
    end: int,
    payload_hash: str | None = "ph:quote",
) -> None:
    """A PRESENT row whose only inline text is `span.quote` (its content is gone).

    This is the shape #67's review flagged: `content` is already `None`, so a
    redactor that only nulled `content` would leave the verified quote readable
    inside `span.quote` in `evidence_json` (ADR candidate 0011).
    """
    registry.put(
        present_evidence(
            evidence_id=evidence_id,
            source_type="document",
            source_locator=f"doc#{evidence_id}",
            observed_at=NOW,
            content=None,
            payload_hash=payload_hash,
            provenance=PROV,
            span=TextSpan(start=start, end=end, quote=quote),
        )
    )


@pytest.mark.parametrize("shared", [True, False])
def test_erase_removes_refs_and_redacts_orphan(shared: bool) -> None:
    ledger, registry = _make_stores(shared)
    candidate = make_entity_candidate(key="erase/orphan")
    ledger.submit([candidate])
    _present(registry, "ev_orphan")
    _cite(registry, candidate.candidate_id, "ev_orphan")

    report = ErasureCoordinator(ledger, registry).erase(
        candidate.candidate_id, reason="gdpr", actor="dpo"
    )

    assert ledger.is_erased(candidate.candidate_id)
    assert registry.refs_for(candidate.candidate_id) == []
    assert registry.resolve(candidate.candidate_id) == []

    evidence = registry.get("ev_orphan")
    assert evidence is not None
    assert evidence.content is None                       # passage text gone
    assert evidence.payload_hash == "ph:original"          # hash retained
    assert evidence.availability is EvidenceAvailability.PRESENT
    assert report.removed_refs == ("ev_orphan",)
    assert report.redacted == ("ev_orphan",)
    assert report.preserved == ()

    # the redaction marker is queryable at rest
    marker = registry.redaction("ev_orphan")
    assert marker is not None
    assert marker[0] is not None
    assert marker[1] == "gdpr"


@pytest.mark.parametrize("shared", [True, False])
def test_shared_evidence_survives(shared: bool) -> None:
    ledger, registry = _make_stores(shared)
    surviving = make_entity_candidate(key="erase/shared/survivor")
    erased = make_entity_candidate(key="erase/shared/erased")
    ledger.submit([surviving, erased])
    _present(registry, "ev_shared", content="shared passage")
    _cite(registry, surviving.candidate_id, "ev_shared")
    _cite(registry, erased.candidate_id, "ev_shared")

    report = ErasureCoordinator(ledger, registry).erase(
        erased.candidate_id, reason="gdpr", actor="dpo"
    )

    assert registry.refs_for(erased.candidate_id) == []
    evidence = registry.get("ev_shared")
    assert evidence is not None and evidence.content == "shared passage"
    assert registry.redaction("ev_shared") == (None, None)  # untouched
    assert [e.evidence_id for e in registry.resolve(surviving.candidate_id)] == ["ev_shared"]
    assert report.preserved == ("ev_shared",)
    assert report.redacted == ()


@pytest.mark.parametrize("shared", [True, False])
def test_redaction_is_recorded_in_the_audit_stream(shared: bool) -> None:
    ledger, registry = _make_stores(shared)
    candidate = make_entity_candidate(key="erase/audit")
    ledger.submit([candidate])
    _present(registry, "ev_audit")
    _cite(registry, candidate.candidate_id, "ev_audit")

    ErasureCoordinator(ledger, registry).erase(
        candidate.candidate_id, reason="gdpr", actor="dpo"
    )

    records = [
        row
        for row in ledger._audit.records_for(candidate.candidate_id)
        if row["kind"] == "redact"
    ]
    assert len(records) == 1
    assert "ev_audit" in records[0]["detail_json"]
    assert records[0]["payload_hash"] == "ph:original"
    assert records[0]["actor"] == "dpo"
    assert ledger.row(candidate.candidate_id).payload_json is None
    # the ordinary erase tombstone is still there too
    kinds = {row["kind"] for row in ledger._audit.records_for(candidate.candidate_id)}
    assert {"transition", "erase", "redact"} <= kinds


@pytest.mark.parametrize("shared", [True, False])
def test_failure_midway_rolls_back(shared: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    ledger, registry = _make_stores(shared)
    candidate = make_entity_candidate(key="erase/rollback")
    ledger.submit([candidate])
    _present(registry, "ev_rollback", content="still here")
    _cite(registry, candidate.candidate_id, "ev_rollback")

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated mid-cascade failure")

    monkeypatch.setattr(registry, "_redact_evidence_stmt", boom)

    with pytest.raises(RuntimeError, match="simulated mid-cascade failure"):
        ErasureCoordinator(ledger, registry).erase(
            candidate.candidate_id, reason="gdpr", actor="dpo"
        )

    # Nothing committed: the ledger row, the ref, the content and the audit are
    # all exactly as before.
    assert not ledger.is_erased(candidate.candidate_id)
    assert ledger.row(candidate.candidate_id).payload_json is not None
    assert [r.evidence_id for r in registry.refs_for(candidate.candidate_id)] == ["ev_rollback"]
    evidence = registry.get("ev_rollback")
    assert evidence is not None and evidence.content == "still here"
    assert registry.redaction("ev_rollback") == (None, None)
    assert [
        row
        for row in ledger._audit.records_for(candidate.candidate_id)
        if row["kind"] == "redact"
    ] == []


@pytest.mark.parametrize("shared", [True, False])
def test_revoke_retains_refs_and_keeps_them_resolvable(shared: bool) -> None:
    ledger, registry = _make_stores(shared)
    candidate = make_entity_candidate(key="revoke/keep")
    ledger.submit([candidate])
    _present(registry, "ev_kept", content="retained by design")
    _cite(registry, candidate.candidate_id, "ev_kept")

    ErasureCoordinator(ledger, registry).revoke(
        candidate.candidate_id, reason="source retraction", actor="ops"
    )

    assert ledger.is_revoked(candidate.candidate_id)
    assert ledger.ledger_entries() == []                    # hidden from listings
    assert [r.evidence_id for r in registry.refs_for(candidate.candidate_id)] == ["ev_kept"]
    resolved = registry.resolve(candidate.candidate_id)     # documented: still returns refs
    assert [e.evidence_id for e in resolved] == ["ev_kept"]
    assert resolved[0].content == "retained by design"
    assert registry.redaction("ev_kept") == (None, None)


def test_separate_connection_ledger_commit_failure_is_reported(
    tmp_path,
) -> None:
    """The residual separate-connection window raises instead of hiding."""
    ledger_conn = sqlite3.connect(
        str(tmp_path / "ledger.db"), factory=_FlakyCommitConnection
    )
    ledger_conn.row_factory = sqlite3.Row
    ledger_conn.executescript(LEDGER_SCHEMA)
    ledger = SqliteCandidateLedger(ledger_conn, profile=BASEBALL_AI_PROFILE)
    registry = SqliteEvidenceRegistry(str(tmp_path / "evidence.db"))
    candidate = make_entity_candidate(key="erase/incomplete")
    ledger.submit([candidate])
    _present(registry, "ev_incomplete", content="redact me")
    _cite(registry, candidate.candidate_id, "ev_incomplete")

    ledger_conn.fail_commit = True
    with pytest.raises(ErasureIncompleteError):
        ErasureCoordinator(ledger, registry).erase(
            candidate.candidate_id, reason="gdpr", actor="dpo"
        )

    # The registry half committed: content gone, refs removed. The ledger half
    # rolled back: the row is not erased.
    assert registry.get("ev_incomplete").content is None
    assert registry.refs_for(candidate.candidate_id) == []
    assert not ledger.is_erased(candidate.candidate_id)


def test_erase_requires_enabled_profile() -> None:
    ledger = SqliteCandidateLedger(":memory:", profile=ConsumerProfile())
    registry = SqliteEvidenceRegistry(":memory:")
    candidate = make_entity_candidate(key="erase/disabled")
    ledger.submit([candidate])
    with pytest.raises(PermissionError):
        ErasureCoordinator(ledger, registry).erase(
            candidate.candidate_id, reason="gdpr", actor="dpo"
        )


def test_erase_unknown_candidate_raises_keyerror() -> None:
    ledger, registry = _make_stores(False)
    with pytest.raises(KeyError):
        ErasureCoordinator(ledger, registry).erase("nope", reason="gdpr", actor="dpo")


def test_existing_evidence_db_gains_the_redaction_marker(tmp_path) -> None:
    """A v1 evidence database is migrated forward when the registry opens it."""
    evidence_path = tmp_path / "evidence.db"
    old = sqlite3.connect(evidence_path)
    old.executescript(
        """
        CREATE TABLE evidence (
            evidence_id TEXT PRIMARY KEY, source_type TEXT NOT NULL,
            source_locator TEXT NOT NULL, observed_at TEXT NOT NULL,
            availability TEXT NOT NULL, absence_reason TEXT, payload_hash TEXT,
            valid_from TEXT, valid_to TEXT, evidence_json TEXT NOT NULL
        );
        CREATE TABLE evidence_refs (
            subject_id TEXT NOT NULL, evidence_id TEXT NOT NULL,
            relationship TEXT NOT NULL,
            PRIMARY KEY (subject_id, evidence_id, relationship)
        );
        """
    )
    old.commit()
    old.close()

    ledger = SqliteCandidateLedger(
        str(tmp_path / "ledger.db"), profile=BASEBALL_AI_PROFILE
    )
    registry = SqliteEvidenceRegistry(str(evidence_path))
    candidate = make_entity_candidate(key="erase/migrated")
    ledger.submit([candidate])
    _present(registry, "ev_migrated")
    _cite(registry, candidate.candidate_id, "ev_migrated")

    ErasureCoordinator(ledger, registry).erase(
        candidate.candidate_id, reason="gdpr", actor="dpo"
    )

    assert registry.get("ev_migrated").content is None
    marker = registry.redaction("ev_migrated")
    assert marker is not None and marker[0] is not None


def test_redaction_derives_a_hash_when_none_was_recorded() -> None:
    """PRESENT evidence that carried only content still stays PRESENT-by-hash."""
    ledger, registry = _make_stores(False)
    candidate = make_entity_candidate(key="erase/nohash")
    ledger.submit([candidate])
    _present(registry, "ev_nohash", content="content with no hash", payload_hash=None)
    _cite(registry, candidate.candidate_id, "ev_nohash")

    report = ErasureCoordinator(ledger, registry).erase(
        candidate.candidate_id, reason="gdpr", actor="dpo"
    )

    assert report.redacted == ("ev_nohash",)
    evidence = registry.get("ev_nohash")
    assert evidence is not None
    assert evidence.content is None
    assert evidence.payload_hash is not None
    assert evidence.availability is EvidenceAvailability.PRESENT


@pytest.mark.parametrize("shared", [True, False])
def test_erase_redacts_a_quote_only_row_keeping_offsets(shared: bool) -> None:
    """A quote-only row is redacted too: `span.quote` cleared, offsets kept.

    The row's `content` is already `None`; the verified quote lives only in
    `span.quote`, so it must be cleared without disturbing the typed span's
    `start`/`end` (a redactor that only nulled `content` would leak it).
    """
    ledger, registry = _make_stores(shared)
    candidate = make_entity_candidate(key="erase/quote-only")
    ledger.submit([candidate])
    _present_quote_only(
        registry, "ev_quote_only", quote="Ada is a shortstop", start=4, end=23
    )
    _cite(registry, candidate.candidate_id, "ev_quote_only")

    report = ErasureCoordinator(ledger, registry).erase(
        candidate.candidate_id, reason="gdpr", actor="dpo"
    )

    assert report.redacted == ("ev_quote_only",)
    stored = registry.get("ev_quote_only")
    assert stored is not None
    assert stored.content is None                            # still absent
    assert stored.span is not None
    assert stored.span.quote is None                         # quote gone
    assert (stored.span.start, stored.span.end) == (4, 23)   # offsets kept
    assert stored.availability is EvidenceAvailability.PRESENT
    assert stored.payload_hash == "ph:quote"                 # hash retained

    marker = registry.redaction("ev_quote_only")
    assert marker is not None and marker[0] is not None      # redacted_at set
    assert marker[1] == "gdpr"


@pytest.mark.parametrize("method", ["put", "put_many"])
def test_requoting_a_redacted_quote_only_row_is_a_noop(method: str) -> None:
    """Re-`put`ting a redacted quote-only id keeps it redacted (terminal no-op)."""
    ledger, registry = _make_stores(False)
    candidate = make_entity_candidate(key="erase/quote-only/reingest")
    ledger.submit([candidate])
    _present_quote_only(
        registry, "ev_quote_reingest", quote="Ada is a shortstop", start=4, end=23
    )
    _cite(registry, candidate.candidate_id, "ev_quote_reingest")

    ErasureCoordinator(ledger, registry).erase(
        candidate.candidate_id, reason="gdpr", actor="dpo"
    )
    assert registry.get("ev_quote_reingest").span.quote is None
    marker_before = registry.redaction("ev_quote_reingest")
    assert marker_before is not None and marker_before[0] is not None

    # Re-collect the *same* deterministic id with the quote text restored; the
    # redaction is terminal, so neither the content nor the quote comes back.
    if method == "put":
        _present_quote_only(
            registry, "ev_quote_reingest", quote="Ada is a shortstop", start=4, end=23
        )
    else:
        registry.put_many(
            [
                present_evidence(
                    evidence_id="ev_quote_reingest",
                    source_type="document",
                    source_locator="doc#ev_quote_reingest",
                    observed_at=NOW,
                    content=None,
                    payload_hash="ph:quote",
                    provenance=PROV,
                    span=TextSpan(start=4, end=23, quote="Ada is a shortstop"),
                )
            ]
        )

    after = registry.get("ev_quote_reingest")
    assert after is not None
    assert after.content is None
    assert after.span is not None and after.span.quote is None   # never restored
    assert (after.span.start, after.span.end) == (4, 23)
    assert registry.redaction("ev_quote_reingest") == marker_before


@pytest.mark.parametrize("method", ["put", "put_many"])
def test_reingestion_does_not_unredact_evidence(method: str) -> None:
    """Re-extracting an erased document must not restore its passage text.

    Evidence ids are deterministic, so a second extraction over the same
    document re-`put`s the same id. Redaction is terminal: the content stays
    NULL and the marker survives (issue #61 review finding 1).
    """
    ledger, registry = _make_stores(False)
    candidate = make_entity_candidate(key="erase/reingest")
    ledger.submit([candidate])
    document = Document(
        doc_id="doc-reingest",
        text="Ada is a shortstop known for hitting.",
        source_type="scouting_report",
    )
    evidence_id = document_evidence_id(document)
    registry.put(build_document_evidence(document, observed_at=NOW))
    _cite(registry, candidate.candidate_id, evidence_id)

    ErasureCoordinator(ledger, registry).erase(
        candidate.candidate_id, reason="gdpr", actor="dpo"
    )
    assert registry.get(evidence_id).content is None
    marker_before = registry.redaction(evidence_id)
    assert marker_before is not None and marker_before[0] is not None

    # Re-run extraction over the same document, whichever write path is used.
    reingested = build_document_evidence(document, observed_at=NOW)
    if method == "put":
        registry.put(reingested)
    else:
        registry.put_many([reingested])

    after = registry.get(evidence_id)
    assert after is not None
    assert after.content is None                          # never restored
    assert after.payload_hash == document.content_hash     # hash still there
    assert registry.redaction(evidence_id) == marker_before  # marker untouched


@pytest.mark.parametrize("shared", [True, False])
def test_erase_is_idempotent(shared: bool) -> None:
    """A second erase is a no-op: no duplicate transition or redaction audit."""
    ledger, registry = _make_stores(shared)
    candidate = make_entity_candidate(key="erase/idempotent")
    ledger.submit([candidate])
    _present(registry, "ev_idem")
    _cite(registry, candidate.candidate_id, "ev_idem")
    coordinator = ErasureCoordinator(ledger, registry)

    first = coordinator.erase(candidate.candidate_id, reason="gdpr", actor="dpo")
    assert first.already_erased is False
    assert first.redacted == ("ev_idem",)
    audit_after_first = list(ledger._audit.records_for(candidate.candidate_id))

    second = coordinator.erase(candidate.candidate_id, reason="gdpr", actor="dpo")

    assert second.already_erased is True
    assert second.removed_refs == ()
    assert second.redacted == ()
    assert second.preserved == ()
    # Nothing was staged again: no second erase transition, no redact row.
    assert list(ledger._audit.records_for(candidate.candidate_id)) == audit_after_first


def test_same_file_separate_connections_are_rejected(tmp_path) -> None:
    """Two connections to one file cannot be atomic; fail at construction."""
    database = tmp_path / "shared.db"
    ledger_conn = sqlite3.connect(str(database))
    ledger_conn.row_factory = sqlite3.Row
    ledger_conn.executescript(LEDGER_SCHEMA)
    ledger_conn.commit()
    registry_conn = sqlite3.connect(str(database))
    registry_conn.row_factory = sqlite3.Row
    registry_conn.executescript(EVIDENCE_SCHEMA)
    registry_conn.commit()
    ledger = SqliteCandidateLedger(ledger_conn, profile=BASEBALL_AI_PROFILE)
    registry = SqliteEvidenceRegistry(registry_conn)

    with pytest.raises(ConfigurationError, match="same SQLite file"):
        ErasureCoordinator(ledger, registry)
