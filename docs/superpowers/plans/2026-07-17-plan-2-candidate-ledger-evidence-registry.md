# Plan 2 — Candidate Ledger + Evidence Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the frozen Plan 1 v2 write/read *ports* (`CandidateSink`, `LedgerReader`) and the `Evidence` contract into durable, persistent implementations in `src/kgis/`, so ingested candidates land in a real candidate ledger and cited `evidence_ids` resolve in a real evidence registry.

**Architecture:** A SQLite-backed candidate ledger implements the app-facing `CandidateSink` (write-in) and the read-only `LedgerReader` (read-back) behind the frozen contracts, tracking each candidate's `ProcessingState` lifecycle bitemporally with cross-run idempotent replay. A SQLite-backed evidence registry stores `Evidence` (PRESENT/ABSENT/ERROR, never dropped) resolvable by `evidence_id`, plus `EvidenceRef` relationships. An append-only audit stream records every ledger state transition. All persistent stores pass the *same* reusable contract suites the Plan 1 memory adapters pass, and the already-merged Plan 4 ingestion pipeline composes onto the ledger unchanged. One prerequisite task hardens `kg_contracts` at-rest immutability (Issue #7); everything else is net-new `kgis` code with zero contract edits.

**Tech Stack:** Python 3.11+, Pydantic v2, `typing.Protocol` structural ports, stdlib `sqlite3` (no new heavy deps), pytest, ruff, mypy --strict.

## Global Constraints

- **Frozen contracts.** Build strictly against the merged Plan 1 v2 `kg_contracts`. ONLY Task Group 0 (Issue #7) edits `kg_contracts`; every other task adds code only under `src/kgis/` and `tests/kgis/` and introduces ZERO new contracts.
- **The invariants hold** (Plan 1 v2, unchanged): no single confidence float; reader and writer protocols stay split; no PROVISIONAL records in any canonical surface; `CandidateSink` is the *only* application-facing write surface; `GraphMutationStore` is executor-only (Plan 3, **not** built here).
- **Contract-suite parity.** Every persistent store MUST pass the same reusable contract suites the memory adapters pass (`kg_contracts.testing.contract.LedgerReaderContract` and the new suites this plan adds), proving substitutability.
- **Ingestion composes unchanged.** Honor the exact ports the merged Plan 4 ingestion pipeline targets: `CandidateSink.submit(candidates: Sequence[Candidate]) -> SubmissionResult` and `LedgerReader.ledger_entries(options) -> list[LedgerEntry]` / `ledger_entry(candidate_id: str) -> LedgerEntry | None`.
- **Bitemporal from the start** (spec §5.4): ledger rows carry valid-time and transaction-time. Full temporal *query* is capability-declared (spec §5.7) — implemented on this store, not required of every future backend.
- **Toolchain gate.** After every task: `ruff check src tests` clean, `mypy src` (strict) clean, all tests green. TDD (test first, watch it fail, minimal code, watch it pass), frequent commits.
- **No I/O in `kg_contracts`.** The immutable-mapping type in Task Group 0 is pure Pydantic (no persistence); persistence lives only in `kgis`.

## File Structure

**Task Group 0 — `kg_contracts` at-rest immutability (Issue #7):**
- Create: `src/kg_contracts/_frozen.py` — `FrozenMapping` read-only mapping + `FrozenDict` Pydantic annotated type (dict → read-only at validation, JSON round-trip preserved).
- Modify: `src/kg_contracts/curation.py` — apply `FrozenDict` to `CurationOperation.payload`/`reversal_data`, `ResolutionDecision.score_vector`, `ReviewItem.payload`, `ReviewDecision.edited_payload`, `AuditRecord.score_vector`; restore full at-rest immutability docstrings.
- Modify: `src/kg_contracts/candidates.py` — apply to `properties` (AttributeAssertionCandidate, RelationCandidate), `parameters`, `conclusion`, and `representations` (value type preserved).
- Modify: `src/kg_contracts/derivation.py` — apply to `Derivation.parameters`.
- Modify: `src/kg_contracts/registry.py` — apply to `factor_scores`.
- Test: `tests/contracts/test_frozen.py`, plus assertions added to existing model tests.

**Task Group 1 — Persistent candidate ledger (`src/kgis/ledger/`):**
- Create: `src/kgis/ledger/__init__.py` — public exports.
- Create: `src/kgis/ledger/schema.py` — SQLite DDL + connection/migration bootstrap.
- Create: `src/kgis/ledger/row.py` — `LedgerRow` (full persisted row: dedup key, retry counter, quarantine reason, valid/transaction time) and (de)serialization to/from `Candidate`/`LedgerEntry`.
- Create: `src/kgis/ledger/store.py` — `SqliteCandidateLedger` implementing `CandidateSink` + `LedgerReader`, with the `ProcessingState` transition API and revoke/erase surface.
- Create: `src/kgis/ledger/lifecycle.py` — the `ProcessingState` transition table (legal transitions) + guard.
- Create: `docs/adr/0012-candidate-ledger-persistence.md`, `docs/adr/0013-ledger-revoke-and-erasure.md` (Issue #2), `docs/adr/0014-identity-mode-and-consumer-profile.md` (Issue #2).
- Create: `src/kgis/ledger/contract.py` — kgis-local `PersistentLedgerContract` (cross-run reopen suite; NOT a `kg_contracts` edit).
- Test: `tests/kgis/ledger/test_schema.py`, `test_row.py`, `test_lifecycle.py`, `test_sink.py`, `test_reader.py`, `test_revoke_erasure.py`.

**Task Group 2 — Evidence registry (`src/kgis/evidence/`):**
- Create: `src/kgis/evidence/__init__.py`, `src/kgis/evidence/schema.py`, `src/kgis/evidence/store.py` — `SqliteEvidenceRegistry` (put/resolve `Evidence`, resolve `EvidenceRef`).
- Create: `src/kgis/evidence/contract.py` — kgis-local `EvidenceRegistryContract` reusable suite (NOT a `kg_contracts` edit).
- Test: `tests/kgis/evidence/test_registry.py`, `test_refs.py`.

**Task Group 3 — Audit stream (`src/kgis/ledger/audit.py`):**
- Create: `src/kgis/ledger/audit.py` — append-only `SqliteAuditStream` writing an immutable record per transition; hash-only tombstone on erase.
- Test: `tests/kgis/ledger/test_audit.py`.

**Task Group 4 — Ingestion integration + public API:**
- Reuse (no edit): `kg_contracts.testing.contract.CandidateSinkContract` and `LedgerReaderContract` (already shipped in Plan 1) — the persistent ledger passes both. The only new reusable suites are kgis-local (`PersistentLedgerContract`, `EvidenceRegistryContract`).
- Modify: `src/kgis/ledger/__init__.py`, `src/kgis/evidence/__init__.py` — public exports.
- Test: `tests/kgis/test_ingestion_ledger_integration.py` — real (merged) Plan 4 pipeline → `SqliteCandidateLedger` → `LedgerReader` read-back; `plan().plan.ledger_duplicates` returns a real count, not `None`.

---

## Task Group 0 — At-rest immutability of dict payload fields (Issue #7, HARD PREREQUISITE)

Issue #7 is a hard acceptance criterion for Plan 2: Pydantic `frozen=True` blocks attribute *reassignment* but does not deep-freeze dict-typed fields, so `op.payload["x"] = 999` mutates a "frozen" model in place. Once the ledger persists these models, at-rest immutability becomes load-bearing. This group makes it real *before* any persistence exists. It is the only group that edits `kg_contracts`.

### Task 1: `FrozenMapping` + `FrozenDict` annotated type

**Files:**
- Create: `src/kg_contracts/_frozen.py`
- Test: `tests/contracts/test_frozen.py`

**Interfaces:**
- Consumes: nothing (pure stdlib + pydantic).
- Produces:
  - `class FrozenMapping(collections.abc.Mapping[str, object])` — hashable-free read-only view; `__getitem__`, `__iter__`, `__len__`, `__eq__`, `__repr__`; raises `TypeError` on any mutating access.
  - `FrozenDict = Annotated[Mapping[str, VT], ...]` factory `frozen_dict(value_type)` returning an annotated type whose validator coerces a plain `dict`/`Mapping` into `FrozenMapping` and whose serializer emits a plain `dict` (so `model_dump_json`/`model_validate_json` round-trip is byte-stable). Default `frozen_dict(object)` and `frozen_dict(float)` exports as `FrozenDictObject`, `FrozenDictFloat`.

- [ ] **Step 1: Write the failing test**

```python
# tests/contracts/test_frozen.py
import json
import pytest
from pydantic import BaseModel, ConfigDict
from kg_contracts._frozen import FrozenMapping, FrozenDictObject


def test_frozen_mapping_rejects_mutation():
    m = FrozenMapping({"a": 1})
    assert m["a"] == 1
    assert dict(m) == {"a": 1}
    with pytest.raises(TypeError):
        m["a"] = 2  # type: ignore[index]
    with pytest.raises(TypeError):
        del m["a"]  # type: ignore[attr-defined]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    payload: FrozenDictObject


def test_frozen_dict_field_is_immutable_and_round_trips():
    m = _Model(payload={"x": 1, "y": "z"})
    assert m.payload["x"] == 1
    with pytest.raises(TypeError):
        m.payload["x"] = 999  # type: ignore[index]
    dumped = m.model_dump_json()
    assert json.loads(dumped) == {"payload": {"x": 1, "y": "z"}}
    assert _Model.model_validate_json(dumped) == m
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/contracts/test_frozen.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kg_contracts._frozen'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/kg_contracts/_frozen.py
"""Read-only mapping field type for at-rest immutability (Issue #7).

Pydantic `frozen=True` blocks attribute reassignment but not in-place
mutation of dict-typed fields. `FrozenDict` coerces such a field to a
`FrozenMapping` at validation while preserving the plain-dict JSON
round-trip that `CurationPlan` and the ledger depend on.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, TypeVar

from pydantic import PlainSerializer, TypeAdapter
from pydantic.functional_validators import PlainValidator

VT = TypeVar("VT")


class FrozenMapping(Mapping[str, object]):
    """An immutable, hashable-free read-only mapping."""

    __slots__ = ("_data",)

    def __init__(self, data: Mapping[str, object]) -> None:
        object.__setattr__(self, "_data", dict(data))

    def __getitem__(self, key: str) -> object:
        return self._data[key]

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Mapping):
            return dict(self._data) == dict(other)
        return NotImplemented

    def __repr__(self) -> str:
        return f"FrozenMapping({self._data!r})"


def _to_frozen(value: object) -> FrozenMapping:
    if isinstance(value, FrozenMapping):
        return value
    if isinstance(value, Mapping):
        return FrozenMapping(value)
    raise TypeError(f"expected a mapping, got {type(value).__name__}")


def frozen_dict(value_type: type[VT]) -> object:
    """Annotated `Mapping[str, VT]` that validates to a `FrozenMapping`."""
    inner = TypeAdapter(dict[str, value_type])  # type: ignore[valid-type]

    def _validate(value: object) -> FrozenMapping:
        return _to_frozen(inner.validate_python(dict(_to_frozen(value))))

    return Annotated[
        Mapping[str, value_type],  # type: ignore[valid-type]
        PlainValidator(_validate),  # NOT BeforeValidator: a before-validator's
        # output is re-validated against the outer Mapping annotation, which
        # rebuilds a plain mutable dict and defeats immutability. PlainValidator
        # makes `_validate` the sole validation step (verified in review).
        PlainSerializer(lambda m: dict(m), return_type=dict),
    ]


FrozenDictObject = frozen_dict(object)
FrozenDictFloat = frozen_dict(float)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/contracts/test_frozen.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Verify toolchain clean**

Run: `ruff check src tests && mypy src`
Expected: no errors. (If mypy flags the `Annotated[..., value_type]` dynamic form, add a targeted `# type: ignore[valid-type]` only on those lines — the annotated type is validated at runtime by the test above.)

- [ ] **Step 6: Commit**

```bash
git add src/kg_contracts/_frozen.py tests/contracts/test_frozen.py
git commit -m "feat(contracts): FrozenDict at-rest-immutable mapping field type (Issue #7)"
```

### Task 2: Apply `FrozenDict` to the curation payload fields

**Files:**
- Modify: `src/kg_contracts/curation.py` — `CurationOperation.payload`, `CurationOperation.reversal_data`, `ResolutionDecision.score_vector`, `ReviewItem.payload`, `ReviewDecision.edited_payload`, `AuditRecord.score_vector`.
- Test: `tests/contracts/test_curation.py` (add immutability assertions).

**Interfaces:**
- Consumes: `FrozenDictObject`, `FrozenDictFloat` from `kg_contracts._frozen` (Task 1).
- Produces: the same public model APIs, now with read-only dict fields. Field *types* change from `dict[str, object]`/`dict[str, float]` to the frozen-annotated equivalents; construction and JSON round-trip are unchanged for callers.

- [ ] **Step 1: Write the failing test**

```python
# tests/contracts/test_curation.py  (add)
import json
import pytest
from kg_contracts.curation import CurationOperation, CurationOperationType


def test_curation_operation_payload_is_frozen_and_round_trips():
    op = CurationOperation(
        operation_type=CurationOperationType.CREATE_ASSERTION,
        payload={"assertion_id": "a1", "value": 3},
    )
    with pytest.raises(TypeError):
        op.payload["value"] = 999  # type: ignore[index]
    with pytest.raises(TypeError):
        op.reversal_data["x"] = 1  # type: ignore[index]
    dumped = op.model_dump_json()
    assert json.loads(dumped)["payload"] == {"assertion_id": "a1", "value": 3}
    assert CurationOperation.model_validate_json(dumped) == op
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/contracts/test_curation.py::test_curation_operation_payload_is_frozen_and_round_trips -v`
Expected: FAIL — mutation does not raise (the current `dict[str, object]` is mutable).

- [ ] **Step 3: Apply the type**

In `src/kg_contracts/curation.py`, add the import and change the field annotations (values only; defaults unchanged):

```python
from kg_contracts._frozen import FrozenDictFloat, FrozenDictObject

# CurationOperation
    payload: FrozenDictObject
    reversal_data: FrozenDictObject = Field(default_factory=dict)

# ResolutionDecision
    score_vector: FrozenDictFloat

# ReviewItem
    payload: FrozenDictObject

# ReviewDecision
    edited_payload: FrozenDictObject | None = None

# AuditRecord
    score_vector: FrozenDictFloat
```

Then restore the full at-rest immutability wording in the `CurationOperation` and `AuditRecord` docstrings (the attribute-level caveat added in commit `4b4d57b` is now obsolete): state that dict payload fields are read-only at rest, enforced by `FrozenDict`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/contracts/test_curation.py -v`
Expected: PASS, including the pre-existing curation tests (construction and JSON round-trip unchanged).

- [ ] **Step 5: Verify the whole contract suite still passes**

Run: `pytest tests/contracts -q && ruff check src tests && mypy src`
Expected: all Plan 1 contract tests green; ruff + mypy clean.

- [ ] **Step 6: Commit**

```bash
git add src/kg_contracts/curation.py tests/contracts/test_curation.py
git commit -m "feat(contracts): freeze curation dict payload fields at rest (Issue #7)"
```

### Task 3: Apply `FrozenDict` to candidate / derivation / registry payload fields

**Files:**
- Modify: `src/kg_contracts/candidates.py` — `properties` (two variants), `parameters`, `conclusion`, `representations`.
- Modify: `src/kg_contracts/derivation.py` — `Derivation.parameters`.
- Modify: `src/kg_contracts/registry.py` — `factor_scores`.
- Test: `tests/contracts/test_candidates.py`, `tests/contracts/test_derivation.py`, `tests/contracts/test_registry.py` (add immutability assertions).

**Interfaces:**
- Consumes: `FrozenDictObject`, `FrozenDictFloat` (Task 1); for `representations: dict[str, Representation]`, a `frozen_dict(Representation)` local alias.
- Produces: same model APIs with read-only dict fields.

- [ ] **Step 1: Write the failing test**

```python
# tests/contracts/test_candidates.py  (add)
import pytest
from kg_contracts.candidates import AttributeAssertionCandidate


def test_attribute_candidate_properties_frozen(make_attribute_candidate):
    cand = make_attribute_candidate(properties={"unit": "kg"})
    with pytest.raises(TypeError):
        cand.properties["unit"] = "lb"  # type: ignore[index]
```

(Use the existing candidate fixture/factory in the test module; if none exists, construct the variant inline with its required fields as the other tests in the file do.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/contracts/test_candidates.py::test_attribute_candidate_properties_frozen -v`
Expected: FAIL — mutation does not raise.

- [ ] **Step 3: Apply the types**

```python
# candidates.py
from kg_contracts._frozen import FrozenDictObject, frozen_dict
from kg_contracts.identity import Representation  # existing import location

FrozenRepresentations = frozen_dict(Representation)

    representations: FrozenRepresentations = Field(default_factory=dict)   # line ~157
    properties: FrozenDictObject = Field(default_factory=dict)             # lines ~176, ~205
    parameters: FrozenDictObject = Field(default_factory=dict)             # line ~270
    conclusion: FrozenDictObject = Field(default_factory=dict)            # line ~286
```

```python
# derivation.py
from kg_contracts._frozen import FrozenDictObject
    parameters: FrozenDictObject = Field(default_factory=dict)            # line ~56
```

```python
# registry.py
from kg_contracts._frozen import FrozenDictFloat
    factor_scores: FrozenDictFloat = Field(default_factory=dict)          # line ~94
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/contracts/test_candidates.py tests/contracts/test_derivation.py tests/contracts/test_registry.py -v`
Expected: PASS.

- [ ] **Step 5: Full contract suite + toolchain**

Run: `pytest tests/contracts -q && ruff check src tests && mypy src`
Expected: all green. This closes Issue #7.

- [ ] **Step 6: Commit**

```bash
git add src/kg_contracts/candidates.py src/kg_contracts/derivation.py src/kg_contracts/registry.py tests/contracts/
git commit -m "feat(contracts): freeze candidate/derivation/registry dict fields at rest (closes #7)"
```

---

## Task Group 1 — Persistent candidate ledger (`src/kgis/`, ZERO contract edits)

Owner decision (a): the ledger is a **durable SQLite store via stdlib `sqlite3`** behind the frozen ports — real persistence, so Issue #7 at-rest immutability is actually testable — not an ephemeral dict. Owner decision (b): Issue #2's revoke/erasure and reject-only identity decisions are folded in here as ADRs 0013/0014 and implemented on the ledger surface. All code lives under `src/kgis/`; no `kg_contracts` edits.

### Task 4: SQLite schema + connection bootstrap + ADR-0012

**Files:**
- Create: `src/kgis/ledger/__init__.py` (empty for now; exports added in Task 15)
- Create: `src/kgis/ledger/schema.py`
- Create: `docs/adr/0012-candidate-ledger-persistence.md`
- Test: `tests/kgis/ledger/__init__.py` (empty), `tests/kgis/ledger/test_schema.py`

**Interfaces:**
- Consumes: stdlib `sqlite3` only.
- Produces:
  - `open_ledger_db(path: str | os.PathLike[str] | Literal[":memory:"]) -> sqlite3.Connection` — opens (creating if absent), sets `PRAGMA foreign_keys=ON` and `PRAGMA journal_mode=WAL`, applies the DDL idempotently (`CREATE TABLE IF NOT EXISTS`), returns a connection with `row_factory = sqlite3.Row`.
  - Module constant `SCHEMA_SQL: str` — the full DDL for tables `ledger_entries`, `ledger_transitions`, `audit_records` (audit columns populated in Task Group 3; table created now so the schema is single-source).
  - `SCHEMA_VERSION: int = 1` stored in a `ledger_meta(key TEXT PRIMARY KEY, value TEXT)` row.

- [ ] **Step 1: Write the failing test**

```python
# tests/kgis/ledger/test_schema.py
import sqlite3
from kgis.ledger.schema import SCHEMA_VERSION, open_ledger_db


def test_open_creates_tables_and_is_idempotent(tmp_path):
    path = tmp_path / "ledger.db"
    conn = open_ledger_db(path)
    names = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"ledger_entries", "ledger_transitions", "audit_records", "ledger_meta"} <= names
    assert conn.execute(
        "SELECT value FROM ledger_meta WHERE key='schema_version'"
    ).fetchone()["value"] == str(SCHEMA_VERSION)
    conn.close()
    # Re-opening the same file must not error (IF NOT EXISTS) and must persist.
    conn2 = open_ledger_db(path)
    assert conn2.execute("SELECT COUNT(*) c FROM ledger_entries").fetchone()["c"] == 0
    conn2.close()


def test_memory_db_opens():
    conn = open_ledger_db(":memory:")
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/kgis/ledger/test_schema.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kgis.ledger.schema'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/kgis/ledger/schema.py
"""SQLite schema + connection bootstrap for the candidate ledger (spec §3.2).

The ledger is ADR-0006 store 1: immutable, replayable proposed
assertions/entities with their own processing state. Persisted via stdlib
`sqlite3` (owner decision a, ADR-0012) so at-rest immutability (Issue #7)
is real. One physical database, but the ledger read surface is distinct
from any canonical graph reader (ADR-0011).
"""

from __future__ import annotations

import os
import sqlite3
from typing import Literal

SCHEMA_VERSION = 1

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ledger_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ledger_entries (
    candidate_id      TEXT PRIMARY KEY,
    graph_id          TEXT NOT NULL,
    dedup_key         TEXT NOT NULL,
    candidate_kind    TEXT NOT NULL,
    processing_state  TEXT NOT NULL,
    payload_json      TEXT,               -- NULL after hard-erase (tombstone)
    payload_hash      TEXT NOT NULL,
    retry_count       INTEGER NOT NULL DEFAULT 0,
    quarantine_reason TEXT,
    valid_from        TEXT,               -- domain valid-time (ISO-8601, nullable)
    valid_to          TEXT,
    received_at       TEXT NOT NULL,      -- candidate.created_at (LedgerEntry projection)
    recorded_at       TEXT NOT NULL,      -- transaction-time the ledger admitted it
    revoked_at        TEXT,
    revocation_reason TEXT,
    erased_at         TEXT,
    erasure_reason    TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_ledger_dedup ON ledger_entries (dedup_key);
CREATE INDEX IF NOT EXISTS ix_ledger_state ON ledger_entries (processing_state);
CREATE INDEX IF NOT EXISTS ix_ledger_graph ON ledger_entries (graph_id);

CREATE TABLE IF NOT EXISTS ledger_transitions (
    transition_id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id  TEXT NOT NULL REFERENCES ledger_entries (candidate_id),
    from_state    TEXT,
    to_state      TEXT NOT NULL,
    reason        TEXT,
    actor         TEXT NOT NULL,
    at            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_transitions_candidate ON ledger_transitions (candidate_id);

CREATE TABLE IF NOT EXISTS audit_records (
    audit_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id   TEXT NOT NULL,
    transition_id  INTEGER,
    kind           TEXT NOT NULL,          -- 'transition' | 'revoke' | 'erase'
    from_state     TEXT,
    to_state       TEXT,
    payload_hash   TEXT NOT NULL,
    reason         TEXT,
    actor          TEXT NOT NULL,
    recorded_at    TEXT NOT NULL,
    detail_json    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_audit_candidate ON audit_records (candidate_id);
"""


def open_ledger_db(path: str | os.PathLike[str] | Literal[":memory:"]) -> sqlite3.Connection:
    """Open (creating if absent) a ledger database with the DDL applied."""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA_SQL)
    conn.execute(
        "INSERT OR IGNORE INTO ledger_meta (key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
    return conn
```

Also create empty `src/kgis/ledger/__init__.py` and `tests/kgis/ledger/__init__.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/kgis/ledger/test_schema.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Write ADR-0012**

Create `docs/adr/0012-candidate-ledger-persistence.md` (Status: Accepted; Date: 2026-07-21) following `docs/adr/0000-template.md`. **Context:** Plan 1 shipped only an in-memory `MemoryCandidateSink`; the ledger (ADR-0006 store 1) needs durable persistence so processing state, dedup, and Issue #7 at-rest immutability survive a restart and are actually testable. **Decision:** persist the candidate ledger in SQLite via stdlib `sqlite3` (no new dependency), behind the frozen `CandidateSink`/`LedgerReader` ports; one file per graph deployment, `:memory:` for tests. **Alternatives:** ephemeral dict (rejected — no at-rest guarantee), Postgres/heavy backend (deferred — capability-declared later). **Consequences:** durable replayable ledger; a real substrate for revoke/erase (ADR-0013) and audit (spec §7.8); WAL mode for concurrent reads. Add the row to the ADR index table in `docs/adr/README.md`.

- [ ] **Step 6: Verify toolchain + commit**

```bash
pytest tests/kgis/ledger/test_schema.py -q && ruff check src tests && mypy src
git add src/kgis/ledger/ tests/kgis/ledger/ docs/adr/0012-candidate-ledger-persistence.md docs/adr/README.md
git commit -m "feat(kgis): SQLite candidate-ledger schema + bootstrap (ADR-0012)"
```

---

### Task 5: `LedgerRow` — the full persisted row model

The `LedgerEntry` contract docstring says its three-field read projection is deliberately minimal and defers the full persisted row (dedup keys, retry counters, quarantine reasons) to Plan 2. This task models that row and the (de)serialization between a `Candidate` and a stored row.

**Files:**
- Create: `src/kgis/ledger/row.py`
- Test: `tests/kgis/ledger/test_row.py`

**Interfaces:**
- Consumes: `Candidate`, `candidate_adapter` (`kg_contracts.candidates`); `LedgerEntry`, `ProcessingState` (`kg_contracts.stores`, `kg_contracts.curation`); `open_ledger_db` (Task 4).
- Produces:
  - `dedup_key(candidate: Candidate) -> str` — `f"{candidate.graph_id}{candidate.semantic_key}"` (unit separator; semantic key is the idempotency anchor, spec §5.8 — NOT the content hash).
  - `payload_hash(candidate: Candidate) -> str` — `hashlib.sha256(candidate.model_dump_json().encode()).hexdigest()`; the erase tombstone retains this so existence-after-erasure is provable.
  - `class LedgerRow(BaseModel, frozen=True, extra="forbid")` with fields: `candidate_id: str`, `graph_id: str`, `dedup_key: str`, `candidate_kind: str`, `processing_state: ProcessingState`, `payload_json: str | None`, `payload_hash: str`, `retry_count: int = 0`, `quarantine_reason: str | None = None`, `valid_from: datetime | None = None`, `valid_to: datetime | None = None`, `received_at: datetime`, `recorded_at: datetime`, `revoked_at: datetime | None = None`, `revocation_reason: str | None = None`, `erased_at: datetime | None = None`, `erasure_reason: str | None = None`.
    - `LedgerRow.for_candidate(candidate, *, recorded_at: datetime) -> LedgerRow` — initial RECEIVED row; `received_at = candidate.created_at`; `valid_from/valid_to` copied from `candidate.valid_period` when the variant has one (else `None`).
    - `LedgerRow.from_sqlite(row: sqlite3.Row) -> LedgerRow`.
    - `LedgerRow.to_entry() -> LedgerEntry | None` — returns `None` when `payload_json is None` (erased); otherwise `LedgerEntry(candidate=candidate_adapter.validate_json(payload_json), processing_state=processing_state, received_at=received_at)`.
    - `LedgerRow.is_revoked -> bool` (`revoked_at is not None`), `LedgerRow.is_erased -> bool` (`erased_at is not None`).

- [ ] **Step 1: Write the failing test**

```python
# tests/kgis/ledger/test_row.py
from datetime import UTC, datetime
from kg_contracts.curation import ProcessingState
from kg_contracts.testing.factories import make_entity_candidate
from kgis.ledger.row import LedgerRow, dedup_key, payload_hash

NOW = datetime(2026, 7, 21, tzinfo=UTC)


def test_dedup_key_uses_graph_and_semantic_key():
    c = make_entity_candidate(graph_id="baseball", key="team/42")
    assert dedup_key(c) == "baseballteam/42"


def test_for_candidate_projects_received_entry():
    c = make_entity_candidate(key="team/42")
    row = LedgerRow.for_candidate(c, recorded_at=NOW)
    assert row.processing_state is ProcessingState.RECEIVED
    assert row.received_at == c.created_at
    assert row.payload_hash == payload_hash(c)
    entry = row.to_entry()
    assert entry is not None
    assert entry.candidate.candidate_id == c.candidate_id
    assert entry.received_at == c.created_at


def test_erased_row_projects_none():
    c = make_entity_candidate(key="team/42")
    row = LedgerRow.for_candidate(c, recorded_at=NOW).model_copy(
        update={"payload_json": None, "erased_at": NOW, "erasure_reason": "gdpr"})
    assert row.is_erased
    assert row.to_entry() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/kgis/ledger/test_row.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kgis.ledger.row'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/kgis/ledger/row.py
"""The full persisted ledger row the `LedgerEntry` projection defers to Plan 2."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from kg_contracts.candidates import Candidate, candidate_adapter
from kg_contracts.curation import ProcessingState
from kg_contracts.stores import LedgerEntry

_UNIT_SEP = ""


def dedup_key(candidate: Candidate) -> str:
    return f"{candidate.graph_id}{_UNIT_SEP}{candidate.semantic_key}"


def payload_hash(candidate: Candidate) -> str:
    return hashlib.sha256(candidate.model_dump_json().encode("utf-8")).hexdigest()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


class LedgerRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_id: str
    graph_id: str
    dedup_key: str
    candidate_kind: str
    processing_state: ProcessingState
    payload_json: str | None
    payload_hash: str
    retry_count: int = 0
    quarantine_reason: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    received_at: datetime
    recorded_at: datetime
    revoked_at: datetime | None = None
    revocation_reason: str | None = None
    erased_at: datetime | None = None
    erasure_reason: str | None = None

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    @property
    def is_erased(self) -> bool:
        return self.erased_at is not None

    @classmethod
    def for_candidate(cls, candidate: Candidate, *, recorded_at: datetime) -> LedgerRow:
        period = getattr(candidate, "valid_period", None)
        return cls(
            candidate_id=candidate.candidate_id,
            graph_id=candidate.graph_id,
            dedup_key=dedup_key(candidate),
            candidate_kind=candidate.candidate_kind,
            processing_state=ProcessingState.RECEIVED,
            payload_json=candidate.model_dump_json(),
            payload_hash=payload_hash(candidate),
            received_at=candidate.created_at,
            recorded_at=recorded_at,
            valid_from=getattr(period, "valid_from", None),
            valid_to=getattr(period, "valid_to", None),
        )

    @classmethod
    def from_sqlite(cls, row: sqlite3.Row) -> LedgerRow:
        return cls(
            candidate_id=row["candidate_id"],
            graph_id=row["graph_id"],
            dedup_key=row["dedup_key"],
            candidate_kind=row["candidate_kind"],
            processing_state=ProcessingState(row["processing_state"]),
            payload_json=row["payload_json"],
            payload_hash=row["payload_hash"],
            retry_count=row["retry_count"],
            quarantine_reason=row["quarantine_reason"],
            valid_from=_parse(row["valid_from"]),
            valid_to=_parse(row["valid_to"]),
            received_at=_parse(row["received_at"]),  # type: ignore[arg-type]
            recorded_at=_parse(row["recorded_at"]),  # type: ignore[arg-type]
            revoked_at=_parse(row["revoked_at"]),
            revocation_reason=row["revocation_reason"],
            erased_at=_parse(row["erased_at"]),
            erasure_reason=row["erasure_reason"],
        )

    def to_entry(self) -> LedgerEntry | None:
        if self.payload_json is None:
            return None
        return LedgerEntry(
            candidate=candidate_adapter.validate_json(self.payload_json),
            processing_state=self.processing_state,
            received_at=self.received_at,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/kgis/ledger/test_row.py -v`
Expected: PASS.

- [ ] **Step 5: Verify toolchain + commit**

```bash
pytest tests/kgis/ledger/test_row.py -q && ruff check src tests && mypy src
git add src/kgis/ledger/row.py tests/kgis/ledger/test_row.py
git commit -m "feat(kgis): full persisted LedgerRow model + Candidate/LedgerEntry (de)serialization"
```

---

### Task 6: `ProcessingState` lifecycle transition table + guard

The ledger's `ProcessingState` machine (curation.py, ADR-0006) is distinct from canonical `CurationStatus`. Owner ruling R1: the spec's ledger `SUPERSEDED` is `OBSOLETE` here (a candidate obsoleted by a newer one covering the same fact). Revoke/erase are **not** processing states — they are orthogonal row-governance concerns (Task 10), so `REVOKED`/`ERASED` are deliberately absent from this table.

**Files:**
- Create: `src/kgis/ledger/lifecycle.py`
- Test: `tests/kgis/ledger/test_lifecycle.py`

**Interfaces:**
- Consumes: `ProcessingState` (`kg_contracts.curation`).
- Produces:
  - `LEGAL_TRANSITIONS: dict[ProcessingState, frozenset[ProcessingState]]` — the adjacency map.
  - `class IllegalTransitionError(ValueError)` — raised naming both states.
  - `can_transition(src: ProcessingState, dst: ProcessingState) -> bool`.
  - `assert_transition(src: ProcessingState, dst: ProcessingState) -> None` — raises `IllegalTransitionError` if not legal.
  - `TERMINAL_STATES: frozenset[ProcessingState]` = `{ACCEPTED, REJECTED, INVALID, OBSOLETE, PERMANENT_ERROR}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/kgis/ledger/test_lifecycle.py
import pytest
from kg_contracts.curation import ProcessingState as PS
from kgis.ledger.lifecycle import (
    IllegalTransitionError,
    TERMINAL_STATES,
    assert_transition,
    can_transition,
)


def test_legal_forward_path():
    assert can_transition(PS.RECEIVED, PS.VALIDATED)
    assert can_transition(PS.VALIDATED, PS.RESOLUTION_PENDING)
    assert can_transition(PS.RESOLUTION_PENDING, PS.REVIEW_PENDING)
    assert can_transition(PS.REVIEW_PENDING, PS.ACCEPTED)
    assert can_transition(PS.RETRYABLE_ERROR, PS.VALIDATED)  # retry re-enters


def test_r1_obsolete_replaces_superseded():
    assert can_transition(PS.VALIDATED, PS.OBSOLETE)
    assert not hasattr(PS, "SUPERSEDED")  # ledger machine has no SUPERSEDED


def test_terminal_states_have_no_exits():
    for state in TERMINAL_STATES:
        assert not can_transition(state, PS.VALIDATED)


def test_illegal_transition_raises_naming_states():
    with pytest.raises(IllegalTransitionError, match="ACCEPTED.*RECEIVED"):
        assert_transition(PS.ACCEPTED, PS.RECEIVED)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/kgis/ledger/test_lifecycle.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kgis.ledger.lifecycle'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/kgis/ledger/lifecycle.py
"""The candidate ledger's ProcessingState transition machine (spec §7.1-§7.2).

Distinct from canonical `CurationStatus` (ADR-0006). R1: the spec ledger
state `SUPERSEDED` is `OBSOLETE` here. Revoke/erase are row-governance
concerns (Task 10), not processing states, so they are absent here.
"""

from __future__ import annotations

from kg_contracts.curation import ProcessingState as PS

TERMINAL_STATES: frozenset[PS] = frozenset(
    {PS.ACCEPTED, PS.REJECTED, PS.INVALID, PS.OBSOLETE, PS.PERMANENT_ERROR}
)

LEGAL_TRANSITIONS: dict[PS, frozenset[PS]] = {
    PS.RECEIVED: frozenset(
        {PS.VALIDATED, PS.INVALID, PS.BLOCKED, PS.RETRYABLE_ERROR, PS.OBSOLETE}
    ),
    PS.VALIDATED: frozenset(
        {PS.RESOLUTION_PENDING, PS.REVIEW_PENDING, PS.ACCEPTED, PS.OBSOLETE, PS.RETRYABLE_ERROR}
    ),
    PS.BLOCKED: frozenset({PS.RECEIVED, PS.REJECTED, PS.INVALID}),
    PS.RESOLUTION_PENDING: frozenset(
        {PS.REVIEW_PENDING, PS.ACCEPTED, PS.REJECTED, PS.OBSOLETE, PS.RETRYABLE_ERROR}
    ),
    PS.REVIEW_PENDING: frozenset({PS.ACCEPTED, PS.REJECTED, PS.OBSOLETE}),
    PS.RETRYABLE_ERROR: frozenset({PS.VALIDATED, PS.RECEIVED, PS.PERMANENT_ERROR, PS.REJECTED}),
    # Terminal states — no outgoing transitions.
    PS.ACCEPTED: frozenset(),
    PS.REJECTED: frozenset(),
    PS.INVALID: frozenset(),
    PS.OBSOLETE: frozenset(),
    PS.PERMANENT_ERROR: frozenset(),
}


class IllegalTransitionError(ValueError):
    """A requested ProcessingState transition is not in `LEGAL_TRANSITIONS`."""


def can_transition(src: PS, dst: PS) -> bool:
    return dst in LEGAL_TRANSITIONS.get(src, frozenset())


def assert_transition(src: PS, dst: PS) -> None:
    if not can_transition(src, dst):
        raise IllegalTransitionError(
            f"illegal ledger transition {src.value} -> {dst.value}"
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/kgis/ledger/test_lifecycle.py -v`
Expected: PASS.

- [ ] **Step 5: Verify toolchain + commit**

```bash
pytest tests/kgis/ledger/test_lifecycle.py -q && ruff check src tests && mypy src
git add src/kgis/ledger/lifecycle.py tests/kgis/ledger/test_lifecycle.py
git commit -m "feat(kgis): ProcessingState transition table + guard (R1 OBSOLETE)"
```

---

### Task 7: `SqliteCandidateLedger.submit()` — the `CandidateSink` write-in

The persistent write surface. Idempotency is by semantic key (spec §5.8), persisted, so replay across runs (the seam the merged ingestion pipeline targets — "the sink owns cross-run idempotency") returns `DUPLICATE` rather than a second row. Must pass the existing `kg_contracts.testing.contract.CandidateSinkContract` unchanged.

**Files:**
- Create: `src/kgis/ledger/store.py`
- Test: `tests/kgis/ledger/test_sink.py`

**Interfaces:**
- Consumes: `Candidate` (`kg_contracts.candidates`); `CandidateSink`, `SubmissionResult`, `SubmissionOutcome`, `SubmissionStatus` (`kg_contracts.stores`); `ProcessingState` (`kg_contracts.curation`); `open_ledger_db` (Task 4); `LedgerRow`, `dedup_key` (Task 5).
- Produces:
  - `class SqliteCandidateLedger` implementing `CandidateSink`:
    - `__init__(self, database: str | os.PathLike[str] | sqlite3.Connection = ":memory:", *, now: Callable[[], datetime] | None = None)` — opens/adopts a connection via `open_ledger_db`; `now` defaults to `lambda: datetime.now(UTC)` (injectable for deterministic tests).
    - `submit(self, candidates: Sequence[Candidate]) -> SubmissionResult` — inserts a RECEIVED `ledger_entries` row per new `dedup_key`; a repeat `dedup_key` yields `SubmissionStatus.DUPLICATE` (no second row). Writes the initial `None -> RECEIVED` transition.
    - `close(self) -> None`.
    - private `_insert_transition(candidate_id, from_state, to_state, *, reason, actor) -> int` — appends to `ledger_transitions`, returns its `transition_id` (Task Group 3 extends this to also write an audit record).

- [ ] **Step 1: Write the failing test**

```python
# tests/kgis/ledger/test_sink.py
from kg_contracts.stores import CandidateSink, SubmissionStatus
from kg_contracts.testing.contract import CandidateSinkContract
from kg_contracts.testing.factories import make_entity_candidate
from kgis.ledger.store import SqliteCandidateLedger


class TestSqliteLedgerSink(CandidateSinkContract):
    def make_sink(self) -> CandidateSink:
        return SqliteCandidateLedger(":memory:")


def test_duplicate_semantic_key_writes_no_second_row():
    ledger = SqliteCandidateLedger(":memory:")
    c1 = make_entity_candidate(key="team/42")
    c2 = make_entity_candidate(key="team/42")  # same semantic key, new candidate_id
    assert ledger.submit([c1]).outcomes[0].status is SubmissionStatus.RECEIVED
    r2 = ledger.submit([c2])
    assert r2.outcomes[0].status is SubmissionStatus.DUPLICATE
    count = ledger._conn.execute("SELECT COUNT(*) c FROM ledger_entries").fetchone()["c"]
    assert count == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/kgis/ledger/test_sink.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kgis.ledger.store'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/kgis/ledger/store.py
"""Durable SQLite candidate ledger (ADR-0006 store 1, ADR-0012)."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Callable

from kg_contracts.candidates import Candidate
from kg_contracts.curation import ProcessingState
from kg_contracts.stores import (
    SubmissionOutcome,
    SubmissionResult,
    SubmissionStatus,
)

from kgis.ledger.row import LedgerRow, dedup_key
from kgis.ledger.schema import open_ledger_db

_INSERT_ENTRY = """
INSERT INTO ledger_entries (
    candidate_id, graph_id, dedup_key, candidate_kind, processing_state,
    payload_json, payload_hash, retry_count, quarantine_reason,
    valid_from, valid_to, received_at, recorded_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


class SqliteCandidateLedger:
    """`CandidateSink` + `LedgerReader` over one SQLite database."""

    def __init__(
        self,
        database: str | os.PathLike[str] | sqlite3.Connection = ":memory:",
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if isinstance(database, sqlite3.Connection):
            self._conn = database
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript("")  # no-op; schema assumed applied
        else:
            self._conn = open_ledger_db(database)
        self._now = now if now is not None else (lambda: datetime.now(UTC))

    def close(self) -> None:
        self._conn.close()

    def _insert_transition(
        self,
        candidate_id: str,
        from_state: ProcessingState | None,
        to_state: ProcessingState,
        *,
        reason: str | None,
        actor: str,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO ledger_transitions (candidate_id, from_state, to_state, reason, actor, at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                candidate_id,
                from_state.value if from_state is not None else None,
                to_state.value,
                reason,
                actor,
                self._now().isoformat(),
            ),
        )
        return int(cur.lastrowid or 0)

    def submit(self, candidates: Sequence[Candidate]) -> SubmissionResult:
        outcomes: list[SubmissionOutcome] = []
        for candidate in candidates:
            key = dedup_key(candidate)
            seen = self._conn.execute(
                "SELECT 1 FROM ledger_entries WHERE dedup_key = ?", (key,)
            ).fetchone()
            if seen is not None:
                outcomes.append(
                    SubmissionOutcome(
                        candidate_id=candidate.candidate_id,
                        status=SubmissionStatus.DUPLICATE,
                        reason=f"semantic_key already in ledger: {candidate.semantic_key!r}",
                        trace_id=candidate.trace_id,
                    )
                )
                continue
            row = LedgerRow.for_candidate(candidate, recorded_at=self._now())
            self._conn.execute(
                _INSERT_ENTRY,
                (
                    row.candidate_id, row.graph_id, row.dedup_key, row.candidate_kind,
                    row.processing_state.value, row.payload_json, row.payload_hash,
                    row.retry_count, row.quarantine_reason,
                    row.valid_from.isoformat() if row.valid_from else None,
                    row.valid_to.isoformat() if row.valid_to else None,
                    row.received_at.isoformat(), row.recorded_at.isoformat(),
                ),
            )
            self._insert_transition(
                row.candidate_id, None, ProcessingState.RECEIVED,
                reason=None, actor=candidate.producer,
            )
            outcomes.append(
                SubmissionOutcome(
                    candidate_id=candidate.candidate_id,
                    status=SubmissionStatus.RECEIVED,
                    trace_id=candidate.trace_id,
                )
            )
        self._conn.commit()
        return SubmissionResult(outcomes=tuple(outcomes))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/kgis/ledger/test_sink.py -v`
Expected: PASS — the full `CandidateSinkContract` (submit-all-received, resubmit-duplicate, trace-ids, counts) plus the no-second-row test.

- [ ] **Step 5: Verify toolchain + commit**

```bash
pytest tests/kgis/ledger/test_sink.py -q && ruff check src tests && mypy src
git add src/kgis/ledger/store.py tests/kgis/ledger/test_sink.py
git commit -m "feat(kgis): SqliteCandidateLedger.submit — persistent CandidateSink with cross-run idempotency"
```

---

### Task 8: `LedgerReader` read-back + capability declaration + persistence suite

The separate ledger *read* surface (ADR-0011): distinct protocol from any canonical `GraphReader`. Must pass the existing `LedgerReaderContract` unchanged, and a new kgis-local `PersistentLedgerContract` proving data + idempotency survive a reopen (cross-run replay).

**Files:**
- Modify: `src/kgis/ledger/store.py` — add `ledger_entries`, `ledger_entry`, `row`, `capabilities`.
- Create: `src/kgis/ledger/contract.py` — `PersistentLedgerContract`.
- Test: `tests/kgis/ledger/test_reader.py`

**Interfaces:**
- Consumes: `LedgerReader`, `LedgerEntry`, `LedgerReadOptions`, `AdapterCapabilities` (`kg_contracts.stores`); `LedgerRow` (Task 5).
- Produces (added to `SqliteCandidateLedger`, which now satisfies `LedgerReader` and `CapabilityDeclaring`):
  - `ledger_entries(self, options: LedgerReadOptions = LedgerReadOptions()) -> list[LedgerEntry]` — excludes erased (payload gone) and revoked (hidden by default; data retained) rows; honors `processing_states` and `graph_id` filters; ordered by `(recorded_at, candidate_id)`.
  - `ledger_entry(self, candidate_id: str) -> LedgerEntry | None` — returns the entry even if revoked (data retained); `None` if absent or erased.
  - `row(self, candidate_id: str) -> LedgerRow | None` — the full persisted row (kgis surface, for lifecycle/revoke).
  - `capabilities(self) -> AdapterCapabilities` — `AdapterCapabilities(supports_temporal_queries=True)` (memory/SQLite first, spec §5.7).
  - `class PersistentLedgerContract` with `open_ledger(self, path: str) -> SqliteCandidateLedger` factory and reopen/replay tests.

- [ ] **Step 1: Write the failing test**

```python
# tests/kgis/ledger/test_reader.py
from kg_contracts.stores import CandidateSink
from kg_contracts.testing.contract import LedgerReaderContract
from kgis.ledger.contract import PersistentLedgerContract
from kgis.ledger.store import SqliteCandidateLedger


class TestSqliteLedgerReader(LedgerReaderContract):
    def make_ledger(self) -> CandidateSink:
        return SqliteCandidateLedger(":memory:")


class TestSqliteLedgerPersistence(PersistentLedgerContract):
    def open_ledger(self, path: str) -> SqliteCandidateLedger:
        return SqliteCandidateLedger(path)


def test_capabilities_declare_temporal():
    assert SqliteCandidateLedger(":memory:").capabilities().supports_temporal_queries is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/kgis/ledger/test_reader.py -v`
Expected: FAIL — `AttributeError: 'SqliteCandidateLedger' object has no attribute 'ledger_entries'` (and `ModuleNotFoundError` for `kgis.ledger.contract`).

- [ ] **Step 3: Add the read methods to `store.py`**

Add these imports to `store.py`:
```python
from kg_contracts.stores import (
    AdapterCapabilities,
    LedgerEntry,
    LedgerReadOptions,
)
from kgis.ledger.row import LedgerRow, dedup_key  # extend existing import
```
Add these methods to `SqliteCandidateLedger`:
```python
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(supports_temporal_queries=True)

    def row(self, candidate_id: str) -> LedgerRow | None:
        r = self._conn.execute(
            "SELECT * FROM ledger_entries WHERE candidate_id = ?", (candidate_id,)
        ).fetchone()
        return LedgerRow.from_sqlite(r) if r is not None else None

    def ledger_entry(self, candidate_id: str) -> LedgerEntry | None:
        row = self.row(candidate_id)
        return row.to_entry() if row is not None else None

    def ledger_entries(
        self, options: LedgerReadOptions = LedgerReadOptions()
    ) -> list[LedgerEntry]:
        clauses = ["payload_json IS NOT NULL", "revoked_at IS NULL"]
        params: list[object] = []
        if options.graph_id is not None:
            clauses.append("graph_id = ?")
            params.append(options.graph_id)
        if options.processing_states is not None:
            marks = ",".join("?" for _ in options.processing_states)
            clauses.append(f"processing_state IN ({marks})")
            params.extend(s.value for s in options.processing_states)
        sql = (
            "SELECT * FROM ledger_entries WHERE "
            + " AND ".join(clauses)
            + " ORDER BY recorded_at, candidate_id"
        )
        entries: list[LedgerEntry] = []
        for r in self._conn.execute(sql, params).fetchall():
            entry = LedgerRow.from_sqlite(r).to_entry()
            if entry is not None:
                entries.append(entry)
        return entries
```

- [ ] **Step 4: Write `contract.py`**

```python
# src/kgis/ledger/contract.py
"""kgis-local reusable suite: any *persistent* candidate ledger must keep data
and idempotency across a reopen. NOT a kg_contracts edit — the ports' own
suites (`CandidateSinkContract`, `LedgerReaderContract`) stay in kg_contracts.
"""

from __future__ import annotations

from kg_contracts.stores import SubmissionStatus
from kg_contracts.testing.factories import make_entity_candidate

from kgis.ledger.store import SqliteCandidateLedger


class PersistentLedgerContract:
    """Subclass and implement `open_ledger(path)`."""

    def open_ledger(self, path: str) -> SqliteCandidateLedger:
        raise NotImplementedError

    def test_data_survives_reopen(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        path = str(tmp_path / "ledger.db")
        led = self.open_ledger(path)
        c = make_entity_candidate(key="persist/1")
        led.submit([c])
        led.close()

        reopened = self.open_ledger(path)
        entry = reopened.ledger_entry(c.candidate_id)
        assert entry is not None
        assert entry.candidate.candidate_id == c.candidate_id
        reopened.close()

    def test_cross_run_replay_is_duplicate(self, tmp_path) -> None:  # type: ignore[no-untyped-def]
        path = str(tmp_path / "ledger.db")
        led = self.open_ledger(path)
        led.submit([make_entity_candidate(key="persist/2")])
        led.close()

        reopened = self.open_ledger(path)
        result = reopened.submit([make_entity_candidate(key="persist/2")])
        assert result.outcomes[0].status is SubmissionStatus.DUPLICATE
        reopened.close()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/kgis/ledger/test_reader.py -v`
Expected: PASS — `LedgerReaderContract` (4 tests), `PersistentLedgerContract` (2 tests), capability test.

- [ ] **Step 6: Verify toolchain + commit**

```bash
pytest tests/kgis/ledger/test_reader.py -q && ruff check src tests && mypy src
git add src/kgis/ledger/store.py src/kgis/ledger/contract.py tests/kgis/ledger/test_reader.py
git commit -m "feat(kgis): SqliteCandidateLedger LedgerReader read-back + persistence suite"
```

---

### Task 9: `transition()` — auditable `ProcessingState` lifecycle

Move a candidate through its ledger lifecycle with the Task 6 guard, a persisted transition row, retry counting, and quarantine reasons — the async lifecycle the `MemoryCandidateSink` reference deliberately did not model.

**Files:**
- Modify: `src/kgis/ledger/store.py` — add `transition`.
- Test: `tests/kgis/ledger/test_lifecycle_store.py`

**Interfaces:**
- Consumes: `assert_transition`, `IllegalTransitionError` (Task 6); `ProcessingState`.
- Produces (added to `SqliteCandidateLedger`):
  - `transition(self, candidate_id: str, to_state: ProcessingState, *, actor: str, reason: str | None = None, increment_retry: bool = False, quarantine_reason: str | None = None) -> LedgerRow` — asserts the transition is legal (raises `IllegalTransitionError` otherwise), updates `processing_state`, optionally bumps `retry_count` and/or sets `quarantine_reason`, writes a `ledger_transitions` row, returns the updated `LedgerRow`. Raises `KeyError` naming the id if the candidate is absent, revoked, or erased (a revoked/erased row has left the processing lifecycle).

- [ ] **Step 1: Write the failing test**

```python
# tests/kgis/ledger/test_lifecycle_store.py
import pytest
from kg_contracts.curation import ProcessingState as PS
from kg_contracts.testing.factories import make_entity_candidate
from kgis.ledger.lifecycle import IllegalTransitionError
from kgis.ledger.store import SqliteCandidateLedger


def _seed():
    ledger = SqliteCandidateLedger(":memory:")
    c = make_entity_candidate(key="team/9")
    ledger.submit([c])
    return ledger, c


def test_legal_transition_persists_state_and_history():
    ledger, c = _seed()
    row = ledger.transition(c.candidate_id, PS.VALIDATED, actor="validator")
    assert row.processing_state is PS.VALIDATED
    assert ledger.row(c.candidate_id).processing_state is PS.VALIDATED
    hist = ledger._conn.execute(
        "SELECT to_state FROM ledger_transitions WHERE candidate_id=? ORDER BY transition_id",
        (c.candidate_id,),
    ).fetchall()
    assert [h["to_state"] for h in hist] == [PS.RECEIVED.value, PS.VALIDATED.value]


def test_illegal_transition_rejected():
    ledger, c = _seed()
    ledger.transition(c.candidate_id, PS.VALIDATED, actor="v")
    ledger.transition(c.candidate_id, PS.ACCEPTED, actor="v")
    with pytest.raises(IllegalTransitionError, match="ACCEPTED -> RECEIVED"):
        ledger.transition(c.candidate_id, PS.RECEIVED, actor="v")


def test_retry_and_quarantine_recorded():
    ledger, c = _seed()
    row = ledger.transition(
        c.candidate_id, PS.RETRYABLE_ERROR, actor="worker",
        increment_retry=True, quarantine_reason="db timeout",
    )
    assert row.retry_count == 1
    assert row.quarantine_reason == "db timeout"


def test_transition_missing_candidate_raises():
    ledger = SqliteCandidateLedger(":memory:")
    with pytest.raises(KeyError, match="cand_missing"):
        ledger.transition("cand_missing", PS.VALIDATED, actor="v")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/kgis/ledger/test_lifecycle_store.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'transition'`.

- [ ] **Step 3: Add `transition` to `store.py`**

Add the import and method:
```python
from kgis.ledger.lifecycle import assert_transition
```
```python
    def transition(
        self,
        candidate_id: str,
        to_state: ProcessingState,
        *,
        actor: str,
        reason: str | None = None,
        increment_retry: bool = False,
        quarantine_reason: str | None = None,
    ) -> LedgerRow:
        row = self.row(candidate_id)
        if row is None or row.is_revoked or row.is_erased:
            raise KeyError(f"no live ledger entry for candidate_id {candidate_id!r}")
        assert_transition(row.processing_state, to_state)
        new_retry = row.retry_count + (1 if increment_retry else 0)
        new_quarantine = quarantine_reason if quarantine_reason is not None else row.quarantine_reason
        self._conn.execute(
            "UPDATE ledger_entries SET processing_state = ?, retry_count = ?, "
            "quarantine_reason = ? WHERE candidate_id = ?",
            (to_state.value, new_retry, new_quarantine, candidate_id),
        )
        self._insert_transition(
            candidate_id, row.processing_state, to_state, reason=reason, actor=actor
        )
        self._conn.commit()
        updated = self.row(candidate_id)
        assert updated is not None  # just updated it
        return updated
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/kgis/ledger/test_lifecycle_store.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Verify toolchain + commit**

```bash
pytest tests/kgis/ledger/test_lifecycle_store.py -q && ruff check src tests && mypy src
git add src/kgis/ledger/store.py tests/kgis/ledger/test_lifecycle_store.py
git commit -m "feat(kgis): auditable ProcessingState transitions with retry + quarantine"
```

---

### Task 10: Revoke + erase surface, identity mode, consumer profile (Issue #2, ADR-0013/0014)

Owner decision (b): fold Issue #2's decisions in as the ledger's revoke/erasure and reject-only identity semantics. **Locked design:** `ProcessingState` gains NO `REVOKED`/`ERASED` member — revoke and erase are orthogonal row-governance columns. Revoke retains data but hides the row from `ledger_entries()`; erase (GDPR hard-delete, gated by profile) nulls the payload irrecoverably, keeping a hash-only tombstone. Reject-only identity mode rejects ambiguous matches at `submit()`.

**Files:**
- Create: `src/kgis/ledger/config.py` — `IdentityMode`, `ConsumerProfile`, `IdentityResolver`.
- Modify: `src/kgis/ledger/store.py` — `__init__` gains `profile`/`resolver`; `submit` honors REJECT_ONLY; add `revoke`, `erase`, `is_revoked`, `is_erased`.
- Create: `docs/adr/0013-ledger-revoke-and-erasure.md`, `docs/adr/0014-identity-mode-and-consumer-profile.md`.
- Test: `tests/kgis/ledger/test_revoke_erasure.py`

**Interfaces:**
- Consumes: `Candidate`; `SubmissionStatus` (`kg_contracts.stores`).
- Produces:
  - `class IdentityMode(StrEnum)`: `AUTO_MERGE`, `REJECT_ONLY`.
  - `class ConsumerProfile(BaseModel, frozen=True, extra="forbid")`: `identity_mode: IdentityMode = AUTO_MERGE`, `erasure_enabled: bool = False`. Constant `BASEBALL_AI_PROFILE = ConsumerProfile(identity_mode=REJECT_ONLY, erasure_enabled=True)`.
  - `class IdentityResolver(Protocol)` (runtime-checkable): `is_ambiguous(self, candidate: Candidate) -> bool`.
  - `SqliteCandidateLedger.__init__(..., profile: ConsumerProfile | None = None, resolver: IdentityResolver | None = None)`.
  - `revoke(self, candidate_id: str, *, reason: str, actor: str) -> None`, `erase(self, candidate_id: str, *, reason: str, actor: str) -> None` (raises `PermissionError` if `profile.erasure_enabled` is False), `is_revoked(self, candidate_id) -> bool`, `is_erased(self, candidate_id) -> bool`.

- [ ] **Step 1: Write the failing test**

```python
# tests/kgis/ledger/test_revoke_erasure.py
import pytest
from kg_contracts.stores import SubmissionStatus
from kg_contracts.testing.factories import make_entity_candidate
from kgis.ledger.config import BASEBALL_AI_PROFILE, ConsumerProfile, IdentityMode
from kgis.ledger.store import SqliteCandidateLedger


class _AlwaysAmbiguous:
    def is_ambiguous(self, candidate) -> bool:
        return True


def test_reject_only_rejects_ambiguous_identity():
    ledger = SqliteCandidateLedger(
        ":memory:",
        profile=ConsumerProfile(identity_mode=IdentityMode.REJECT_ONLY),
        resolver=_AlwaysAmbiguous(),
    )
    result = ledger.submit([make_entity_candidate(key="ambi/1")])
    assert result.outcomes[0].status is SubmissionStatus.INVALID
    assert "REJECT_ONLY" in (result.outcomes[0].reason or "")
    assert ledger.ledger_entries() == []


def test_revoke_hides_from_listing_but_retains_data():
    ledger = SqliteCandidateLedger(":memory:")
    c = make_entity_candidate(key="rev/1")
    ledger.submit([c])
    ledger.revoke(c.candidate_id, reason="source retraction", actor="ops")
    assert ledger.is_revoked(c.candidate_id)
    assert ledger.ledger_entries() == []                 # hidden by default
    assert ledger.ledger_entry(c.candidate_id) is not None  # data retained


def test_erase_requires_enabled_profile_then_nulls_payload():
    plain = SqliteCandidateLedger(":memory:")
    c = make_entity_candidate(key="er/1")
    plain.submit([c])
    with pytest.raises(PermissionError):
        plain.erase(c.candidate_id, reason="gdpr", actor="dpo")

    ledger = SqliteCandidateLedger(":memory:", profile=BASEBALL_AI_PROFILE)
    ledger.submit([c])
    ledger.erase(c.candidate_id, reason="gdpr", actor="dpo")
    assert ledger.is_erased(c.candidate_id)
    assert ledger.ledger_entry(c.candidate_id) is None      # full Candidate gone
    row = ledger.row(c.candidate_id)
    assert row.payload_json is None and row.payload_hash    # hash-only tombstone kept
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/kgis/ledger/test_revoke_erasure.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kgis.ledger.config'`.

- [ ] **Step 3: Write `config.py`**

```python
# src/kgis/ledger/config.py
"""Consumer profile + identity mode — the adoption-gating surface (Issue #2)."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from kg_contracts.candidates import Candidate


class IdentityMode(StrEnum):
    AUTO_MERGE = "AUTO_MERGE"
    REJECT_ONLY = "REJECT_ONLY"


class ConsumerProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    identity_mode: IdentityMode = IdentityMode.AUTO_MERGE
    erasure_enabled: bool = False


BASEBALL_AI_PROFILE = ConsumerProfile(
    identity_mode=IdentityMode.REJECT_ONLY, erasure_enabled=True
)


@runtime_checkable
class IdentityResolver(Protocol):
    """Injected ambiguity oracle. Full ER lands in Plan 5; REJECT_ONLY only
    needs a yes/no ambiguity verdict at submit time."""

    def is_ambiguous(self, candidate: Candidate) -> bool: ...
```

- [ ] **Step 4: Modify `store.py`**

Extend the imports and `__init__`:
```python
from kgis.ledger.config import ConsumerProfile, IdentityMode, IdentityResolver
```
In `__init__`, after setting `self._now`, add:
```python
        self._profile = profile if profile is not None else ConsumerProfile()
        self._resolver = resolver
```
and add the two parameters `profile: ConsumerProfile | None = None, resolver: IdentityResolver | None = None` to the signature.

In `submit`, immediately after the duplicate check `continue` block, add the reject-only branch:
```python
            if (
                self._profile.identity_mode is IdentityMode.REJECT_ONLY
                and self._resolver is not None
                and self._resolver.is_ambiguous(candidate)
            ):
                outcomes.append(
                    SubmissionOutcome(
                        candidate_id=candidate.candidate_id,
                        status=SubmissionStatus.INVALID,
                        reason="ambiguous identity match rejected (REJECT_ONLY)",
                        trace_id=candidate.trace_id,
                    )
                )
                continue
```
Add the governance methods:
```python
    def revoke(self, candidate_id: str, *, reason: str, actor: str) -> None:
        row = self.row(candidate_id)
        if row is None or row.is_erased:
            raise KeyError(f"no live ledger entry for candidate_id {candidate_id!r}")
        self._conn.execute(
            "UPDATE ledger_entries SET revoked_at = ?, revocation_reason = ? WHERE candidate_id = ?",
            (self._now().isoformat(), reason, candidate_id),
        )
        self._insert_transition(
            candidate_id, row.processing_state, row.processing_state,
            reason=f"revoked: {reason}", actor=actor,
        )
        self._conn.commit()

    def erase(self, candidate_id: str, *, reason: str, actor: str) -> None:
        if not self._profile.erasure_enabled:
            raise PermissionError("erasure not enabled for this consumer profile")
        row = self.row(candidate_id)
        if row is None:
            raise KeyError(f"no ledger entry for candidate_id {candidate_id!r}")
        self._conn.execute(
            "UPDATE ledger_entries SET payload_json = NULL, erased_at = ?, "
            "erasure_reason = ? WHERE candidate_id = ?",
            (self._now().isoformat(), reason, candidate_id),
        )
        self._insert_transition(
            candidate_id, row.processing_state, row.processing_state,
            reason=f"erased: {reason}", actor=actor,
        )
        self._conn.commit()

    def is_revoked(self, candidate_id: str) -> bool:
        row = self.row(candidate_id)
        return row is not None and row.is_revoked

    def is_erased(self, candidate_id: str) -> bool:
        row = self.row(candidate_id)
        return row is not None and row.is_erased
```

- [ ] **Step 5: Write ADR-0013 and ADR-0014**

`docs/adr/0013-ledger-revoke-and-erasure.md` (Accepted, 2026-07-21): **Context** — the ledger is immutable/replayable, but data-subject rights (Issue #2) require withdrawal (revoke) and irrecoverable deletion (erase). **Decision** — model both as row-governance columns orthogonal to `ProcessingState` (no new enum member): `revoke` sets `revoked_at`/`revocation_reason` and hides the row from `ledger_entries()` while retaining data and keeping `ledger_entry(id)` resolvable; `erase` (gated by `ConsumerProfile.erasure_enabled`) nulls the payload irrecoverably and keeps a hash-only tombstone (`payload_hash`, `erased_at`), after which `ledger_entry(id)` returns `None` because the full `Candidate` can no longer be reconstructed. **Alternatives** — a `REVOKED` ProcessingState (rejected: conflates governance with lifecycle and would edit the frozen contract); physical row delete (rejected: destroys audit provability). **Consequences** — erasure is provable via the audit tombstone (Task 13); revoke is reversible in principle (data retained).

`docs/adr/0014-identity-mode-and-consumer-profile.md` (Accepted, 2026-07-21): **Context** — Issue #2 asks for a deterministic-projection consumer profile and reject-only identity handling as an adoption-gating surface. **Decision** — a `ConsumerProfile{identity_mode, erasure_enabled}` selected per consuming app; `IdentityMode.REJECT_ONLY` rejects ambiguous identity matches at `submit()` (via an injected `IdentityResolver`) instead of auto-linking; default `AUTO_MERGE`. baseball-ai's profile = `REJECT_ONLY + erasure_enabled` (`BASEBALL_AI_PROFILE`). **Consequences** — full ER stays Plan 5; the profile is the stable contract adopters gate on now. Add both rows to `docs/adr/README.md`.

- [ ] **Step 6: Run tests + toolchain + commit**

```bash
pytest tests/kgis/ledger/test_revoke_erasure.py -q && pytest tests/kgis -q && ruff check src tests && mypy src
git add src/kgis/ledger/ tests/kgis/ledger/test_revoke_erasure.py docs/adr/0013-ledger-revoke-and-erasure.md docs/adr/0014-identity-mode-and-consumer-profile.md docs/adr/README.md
git commit -m "feat(kgis): ledger revoke/erase + reject-only identity mode + consumer profile (ADR-0013/0014, Issue #2)"
```

---

## Task Group 2 — Evidence registry (`src/kgis/evidence/`)

The persistent store the merged ingestion builders explicitly deferred to ("arrives with the evidence registry in Plan 2"). Holds `Evidence` with explicit `EvidenceAvailability` (PRESENT/ABSENT/ERROR) — never silently dropped (spec §5.3) — resolvable by `evidence_id`, plus `EvidenceRef` relationship resolution. Pure `kgis`; zero contract edits.

### Task 11: `SqliteEvidenceRegistry` — persist + resolve `Evidence`

**Files:**
- Create: `src/kgis/evidence/__init__.py` (empty for now), `src/kgis/evidence/schema.py`, `src/kgis/evidence/store.py`
- Test: `tests/kgis/evidence/__init__.py` (empty), `tests/kgis/evidence/test_registry.py`

**Interfaces:**
- Consumes: `Evidence`, `EvidenceAvailability` (`kg_contracts.evidence`).
- Produces:
  - `open_evidence_db(path) -> sqlite3.Connection` — DDL for `evidence` and `evidence_refs` tables.
  - `class SqliteEvidenceRegistry`:
    - `__init__(self, database: str | os.PathLike[str] | sqlite3.Connection = ":memory:")`.
    - `put(self, evidence: Evidence) -> None` — upsert by `evidence_id` (deterministic citable IDs → idempotent re-collection, spec §5.3); stores all three availabilities verbatim.
    - `put_many(self, items: Iterable[Evidence]) -> None`.
    - `get(self, evidence_id: str) -> Evidence | None`.
    - `close(self) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/kgis/evidence/test_registry.py
from datetime import UTC, datetime
from kg_contracts.evidence import (
    AbsenceReason, EvidenceAvailability, Provenance,
    absent_evidence, error_evidence, present_evidence,
)
from kgis.evidence.store import SqliteEvidenceRegistry

NOW = datetime(2026, 7, 21, tzinfo=UTC)
PROV = Provenance(source="test", actor="tester")


def test_all_three_availabilities_persist_and_resolve():
    reg = SqliteEvidenceRegistry(":memory:")
    present = present_evidence(evidence_id="src:k@1", source_type="api",
                              source_locator="k", observed_at=NOW, content="x", provenance=PROV)
    absent = absent_evidence(evidence_id="src:k@2", source_type="api",
                             source_locator="k", observed_at=NOW,
                             reason=AbsenceReason.SOURCE_OMITTED, provenance=PROV)
    err = error_evidence(evidence_id="src:k@3", source_type="api",
                         source_locator="k", observed_at=NOW, error="timeout", provenance=PROV)
    reg.put_many([present, absent, err])
    assert reg.get("src:k@1").availability is EvidenceAvailability.PRESENT
    assert reg.get("src:k@2").absence_reason is AbsenceReason.SOURCE_OMITTED
    assert reg.get("src:k@3").error == "timeout"
    assert reg.get("missing") is None


def test_put_is_idempotent_by_id():
    reg = SqliteEvidenceRegistry(":memory:")
    ev = present_evidence(evidence_id="src:k@1", source_type="api", source_locator="k",
                          observed_at=NOW, content="x", provenance=PROV)
    reg.put(ev)
    reg.put(ev)
    count = reg._conn.execute("SELECT COUNT(*) c FROM evidence").fetchone()["c"]
    assert count == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/kgis/evidence/test_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kgis.evidence.store'`.

- [ ] **Step 3: Write `schema.py` and `store.py`**

```python
# src/kgis/evidence/schema.py
"""SQLite schema for the evidence registry (spec §5.3)."""

from __future__ import annotations

import os
import sqlite3

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS evidence (
    evidence_id    TEXT PRIMARY KEY,
    source_type    TEXT NOT NULL,
    source_locator TEXT NOT NULL,
    observed_at    TEXT NOT NULL,
    availability   TEXT NOT NULL,
    absence_reason TEXT,
    payload_hash   TEXT,
    valid_from     TEXT,
    valid_to       TEXT,
    evidence_json  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_evidence_avail ON evidence (availability);

CREATE TABLE IF NOT EXISTS evidence_refs (
    subject_id   TEXT NOT NULL,
    evidence_id  TEXT NOT NULL,
    relationship TEXT NOT NULL,
    PRIMARY KEY (subject_id, evidence_id, relationship)
);
CREATE INDEX IF NOT EXISTS ix_refs_subject ON evidence_refs (subject_id);
"""


def open_evidence_db(path: str | os.PathLike[str]) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn
```

```python
# src/kgis/evidence/store.py
"""Durable evidence registry (spec §5.3): Evidence never silently dropped."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterable

from kg_contracts.evidence import Evidence

from kgis.evidence.schema import open_evidence_db


class SqliteEvidenceRegistry:
    def __init__(
        self, database: str | os.PathLike[str] | sqlite3.Connection = ":memory:"
    ) -> None:
        if isinstance(database, sqlite3.Connection):
            self._conn = database
            self._conn.row_factory = sqlite3.Row
        else:
            self._conn = open_evidence_db(database)

    def close(self) -> None:
        self._conn.close()

    def put(self, evidence: Evidence) -> None:
        vt = evidence.valid_time
        self._conn.execute(
            "INSERT OR REPLACE INTO evidence (evidence_id, source_type, source_locator, "
            "observed_at, availability, absence_reason, payload_hash, valid_from, valid_to, "
            "evidence_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                evidence.evidence_id, evidence.source_type, evidence.source_locator,
                evidence.observed_at.isoformat(), evidence.availability.value,
                evidence.absence_reason.value if evidence.absence_reason else None,
                evidence.payload_hash,
                vt.valid_from.isoformat() if vt and vt.valid_from else None,
                vt.valid_to.isoformat() if vt and vt.valid_to else None,
                evidence.model_dump_json(),
            ),
        )
        self._conn.commit()

    def put_many(self, items: Iterable[Evidence]) -> None:
        for item in items:
            self.put(item)

    def get(self, evidence_id: str) -> Evidence | None:
        r = self._conn.execute(
            "SELECT evidence_json FROM evidence WHERE evidence_id = ?", (evidence_id,)
        ).fetchone()
        return Evidence.model_validate_json(r["evidence_json"]) if r is not None else None
```

Also create empty `src/kgis/evidence/__init__.py` and `tests/kgis/evidence/__init__.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/kgis/evidence/test_registry.py -v`
Expected: PASS.

- [ ] **Step 5: Verify toolchain + commit**

```bash
pytest tests/kgis/evidence/test_registry.py -q && ruff check src tests && mypy src
git add src/kgis/evidence/ tests/kgis/evidence/
git commit -m "feat(kgis): SqliteEvidenceRegistry — persist + resolve Evidence (all availabilities)"
```

---

### Task 12: `EvidenceRef` relationship resolution + `EvidenceRegistryContract`

Resolve a citing subject (a candidate/assertion id) to its `Evidence` by relationship (supports/contradicts/derived_from/contextualizes). A dangling ref is surfaced, never silently dropped (spec §5.3).

**Files:**
- Modify: `src/kgis/evidence/store.py` — add `add_refs`, `refs_for`, `resolve`, `EvidenceNotFoundError`.
- Create: `src/kgis/evidence/contract.py` — `EvidenceRegistryContract`.
- Test: `tests/kgis/evidence/test_refs.py`

**Interfaces:**
- Consumes: `EvidenceRef`, `EvidenceRelationship` (`kg_contracts.evidence`).
- Produces (added to `SqliteEvidenceRegistry`):
  - `class EvidenceNotFoundError(KeyError)`.
  - `add_refs(self, subject_id: str, refs: Sequence[EvidenceRef]) -> None` — idempotent (`INSERT OR IGNORE`).
  - `refs_for(self, subject_id: str, relationship: EvidenceRelationship | None = None) -> list[EvidenceRef]`.
  - `resolve(self, subject_id: str, relationship: EvidenceRelationship | None = None) -> list[Evidence]` — resolves each ref; raises `EvidenceNotFoundError` naming a missing `evidence_id`.
  - `class EvidenceRegistryContract` with `make_registry(self) -> SqliteEvidenceRegistry` and shared tests.

- [ ] **Step 1: Write the failing test**

```python
# tests/kgis/evidence/test_refs.py
from datetime import UTC, datetime
import pytest
from kg_contracts.evidence import (
    EvidenceRef, EvidenceRelationship, Provenance, present_evidence,
)
from kgis.evidence.contract import EvidenceRegistryContract
from kgis.evidence.store import EvidenceNotFoundError, SqliteEvidenceRegistry

NOW = datetime(2026, 7, 21, tzinfo=UTC)
PROV = Provenance(source="test", actor="tester")


class TestSqliteEvidenceRegistry(EvidenceRegistryContract):
    def make_registry(self) -> SqliteEvidenceRegistry:
        return SqliteEvidenceRegistry(":memory:")


def test_resolve_by_relationship():
    reg = SqliteEvidenceRegistry(":memory:")
    reg.put(present_evidence(evidence_id="e1", source_type="api", source_locator="k",
                             observed_at=NOW, content="x", provenance=PROV))
    reg.add_refs("cand_1", [
        EvidenceRef(evidence_id="e1", relationship=EvidenceRelationship.SUPPORTS),
    ])
    resolved = reg.resolve("cand_1", EvidenceRelationship.SUPPORTS)
    assert [e.evidence_id for e in resolved] == ["e1"]
    assert reg.resolve("cand_1", EvidenceRelationship.CONTRADICTS) == []


def test_dangling_ref_is_not_silently_dropped():
    reg = SqliteEvidenceRegistry(":memory:")
    reg.add_refs("cand_1", [
        EvidenceRef(evidence_id="missing", relationship=EvidenceRelationship.SUPPORTS),
    ])
    with pytest.raises(EvidenceNotFoundError, match="missing"):
        reg.resolve("cand_1")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/kgis/evidence/test_refs.py -v`
Expected: FAIL — `ImportError: cannot import name 'EvidenceNotFoundError'` / `ModuleNotFoundError: kgis.evidence.contract`.

- [ ] **Step 3: Add ref methods to `store.py`**

Add imports and code:
```python
from collections.abc import Iterable, Sequence

from kg_contracts.evidence import Evidence, EvidenceRef, EvidenceRelationship


class EvidenceNotFoundError(KeyError):
    """A cited evidence_id has no stored Evidence."""
```
```python
    def add_refs(self, subject_id: str, refs: Sequence[EvidenceRef]) -> None:
        self._conn.executemany(
            "INSERT OR IGNORE INTO evidence_refs (subject_id, evidence_id, relationship) "
            "VALUES (?, ?, ?)",
            [(subject_id, r.evidence_id, r.relationship.value) for r in refs],
        )
        self._conn.commit()

    def refs_for(
        self, subject_id: str, relationship: EvidenceRelationship | None = None
    ) -> list[EvidenceRef]:
        sql = "SELECT evidence_id, relationship FROM evidence_refs WHERE subject_id = ?"
        params: list[object] = [subject_id]
        if relationship is not None:
            sql += " AND relationship = ?"
            params.append(relationship.value)
        return [
            EvidenceRef(
                evidence_id=r["evidence_id"],
                relationship=EvidenceRelationship(r["relationship"]),
            )
            for r in self._conn.execute(sql, params).fetchall()
        ]

    def resolve(
        self, subject_id: str, relationship: EvidenceRelationship | None = None
    ) -> list[Evidence]:
        resolved: list[Evidence] = []
        for ref in self.refs_for(subject_id, relationship):
            evidence = self.get(ref.evidence_id)
            if evidence is None:
                raise EvidenceNotFoundError(
                    f"evidence_id {ref.evidence_id!r} cited by {subject_id!r} is not stored"
                )
            resolved.append(evidence)
        return resolved
```

- [ ] **Step 4: Write `contract.py`**

```python
# src/kgis/evidence/contract.py
"""kgis-local reusable suite for any evidence registry (NOT a kg_contracts edit)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from kg_contracts.evidence import (
    AbsenceReason, EvidenceAvailability, EvidenceRef, EvidenceRelationship,
    Provenance, absent_evidence, present_evidence,
)

from kgis.evidence.store import EvidenceNotFoundError, SqliteEvidenceRegistry

_NOW = datetime(2026, 7, 21, tzinfo=UTC)
_PROV = Provenance(source="suite", actor="suite")


class EvidenceRegistryContract:
    """Subclass and implement `make_registry()`."""

    def make_registry(self) -> SqliteEvidenceRegistry:
        raise NotImplementedError

    def test_present_and_absent_both_persist(self) -> None:
        reg = self.make_registry()
        reg.put(present_evidence(evidence_id="p", source_type="a", source_locator="k",
                                 observed_at=_NOW, content="x", provenance=_PROV))
        reg.put(absent_evidence(evidence_id="a", source_type="a", source_locator="k",
                                observed_at=_NOW, reason=AbsenceReason.NOT_QUERIED,
                                provenance=_PROV))
        assert reg.get("p").availability is EvidenceAvailability.PRESENT
        assert reg.get("a").availability is EvidenceAvailability.ABSENT

    def test_missing_get_returns_none(self) -> None:
        assert self.make_registry().get("nope") is None

    def test_ref_resolution_and_dangling(self) -> None:
        reg = self.make_registry()
        reg.put(present_evidence(evidence_id="e", source_type="a", source_locator="k",
                                 observed_at=_NOW, content="x", provenance=_PROV))
        reg.add_refs("s", [EvidenceRef(evidence_id="e",
                                       relationship=EvidenceRelationship.DERIVED_FROM)])
        assert [x.evidence_id for x in reg.resolve("s")] == ["e"]
        reg.add_refs("s", [EvidenceRef(evidence_id="gone",
                                       relationship=EvidenceRelationship.SUPPORTS)])
        with pytest.raises(EvidenceNotFoundError):
            reg.resolve("s")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/kgis/evidence/test_refs.py -v`
Expected: PASS — `EvidenceRegistryContract` (3 tests) + the two ref tests.

- [ ] **Step 6: Verify toolchain + commit**

```bash
pytest tests/kgis/evidence -q && ruff check src tests && mypy src
git add src/kgis/evidence/store.py src/kgis/evidence/contract.py tests/kgis/evidence/test_refs.py
git commit -m "feat(kgis): EvidenceRef relationship resolution + EvidenceRegistryContract"
```

---

## Task Group 3 — Audit records at rest

Depends on Task Group 0's frozen mapping being real: an immutable audit record per ledger transition (spec §7.8, "every curation action produces an immutable audit record"). At-rest immutability is enforced by SQLite triggers that abort any `UPDATE`/`DELETE` on `audit_records`, so the audit stream — the training corpus that later justifies raising auto-promotion thresholds — is genuinely append-only. Erase leaves a hash-only tombstone here, proving existence-plus-erasure.

### Task 13: `SqliteAuditStream` — append-only, wired into every transition

**Files:**
- Create: `src/kgis/ledger/audit.py`
- Modify: `src/kgis/ledger/store.py` — `__init__` builds an audit stream; `_insert_transition` emits an audit record; `revoke`/`erase` tag their audit `kind`.
- Test: `tests/kgis/ledger/test_audit.py`

**Interfaces:**
- Consumes: the shared `sqlite3.Connection`; the `audit_records` table (Task 4 DDL).
- Produces:
  - `class SqliteAuditStream`:
    - `__init__(self, conn: sqlite3.Connection)` — applies `CREATE TRIGGER IF NOT EXISTS` guards making `audit_records` append-only.
    - `append(self, *, candidate_id, transition_id, kind, from_state, to_state, payload_hash, reason, actor, recorded_at, detail) -> None`.
    - `records_for(self, candidate_id: str) -> list[sqlite3.Row]`.
  - `SqliteCandidateLedger._insert_transition(..., kind: str = "transition")` now also appends one audit record (reading the row's retained `payload_hash`).

- [ ] **Step 1: Write the failing test**

```python
# tests/kgis/ledger/test_audit.py
import sqlite3
import pytest
from kg_contracts.curation import ProcessingState as PS
from kg_contracts.testing.factories import make_entity_candidate
from kgis.ledger.config import BASEBALL_AI_PROFILE
from kgis.ledger.store import SqliteCandidateLedger


def test_every_transition_appends_an_audit_record():
    ledger = SqliteCandidateLedger(":memory:")
    c = make_entity_candidate(key="a/1")
    ledger.submit([c])                                  # None -> RECEIVED
    ledger.transition(c.candidate_id, PS.VALIDATED, actor="v")
    kinds = [r["kind"] for r in ledger._audit.records_for(c.candidate_id)]
    assert kinds == ["transition", "transition"]


def test_audit_records_are_append_only():
    ledger = SqliteCandidateLedger(":memory:")
    c = make_entity_candidate(key="a/2")
    ledger.submit([c])
    with pytest.raises(sqlite3.DatabaseError):
        ledger._conn.execute("UPDATE audit_records SET actor='x'")
    with pytest.raises(sqlite3.DatabaseError):
        ledger._conn.execute("DELETE FROM audit_records")


def test_erase_leaves_hash_only_tombstone_in_audit():
    ledger = SqliteCandidateLedger(":memory:", profile=BASEBALL_AI_PROFILE)
    c = make_entity_candidate(key="a/3")
    ledger.submit([c])
    ledger.erase(c.candidate_id, reason="gdpr", actor="dpo")
    tomb = [r for r in ledger._audit.records_for(c.candidate_id) if r["kind"] == "erase"]
    assert len(tomb) == 1
    assert tomb[0]["payload_hash"]           # hash retained
    assert ledger.row(c.candidate_id).payload_json is None  # payload gone
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/kgis/ledger/test_audit.py -v`
Expected: FAIL — `AttributeError: 'SqliteCandidateLedger' object has no attribute '_audit'`.

- [ ] **Step 3: Write `audit.py`**

```python
# src/kgis/ledger/audit.py
"""Append-only audit stream (spec §7.8). Immutability enforced at rest by
SQLite triggers that abort any UPDATE/DELETE on `audit_records`.
"""

from __future__ import annotations

import sqlite3

_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_records
BEGIN SELECT RAISE(ABORT, 'audit_records is append-only (spec 7.8)'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_records
BEGIN SELECT RAISE(ABORT, 'audit_records is append-only (spec 7.8)'); END;
"""


class SqliteAuditStream:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.executescript(_TRIGGERS)

    def append(
        self,
        *,
        candidate_id: str,
        transition_id: int,
        kind: str,
        from_state: str | None,
        to_state: str | None,
        payload_hash: str,
        reason: str | None,
        actor: str,
        recorded_at: str,
        detail: str,
    ) -> None:
        self._conn.execute(
            "INSERT INTO audit_records (candidate_id, transition_id, kind, from_state, "
            "to_state, payload_hash, reason, actor, recorded_at, detail_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (candidate_id, transition_id, kind, from_state, to_state, payload_hash,
             reason, actor, recorded_at, detail),
        )

    def records_for(self, candidate_id: str) -> list[sqlite3.Row]:
        return list(
            self._conn.execute(
                "SELECT * FROM audit_records WHERE candidate_id = ? ORDER BY audit_id",
                (candidate_id,),
            ).fetchall()
        )
```

- [ ] **Step 4: Wire it into `store.py`**

Add the import and build the stream at the end of `__init__`:
```python
from kgis.ledger.audit import SqliteAuditStream
```
```python
        self._audit = SqliteAuditStream(self._conn)
```
Replace `_insert_transition` with the audit-emitting version (add the `kind` param; read the row's retained hash):
```python
    def _insert_transition(
        self,
        candidate_id: str,
        from_state: ProcessingState | None,
        to_state: ProcessingState,
        *,
        reason: str | None,
        actor: str,
        kind: str = "transition",
    ) -> int:
        now = self._now().isoformat()
        cur = self._conn.execute(
            "INSERT INTO ledger_transitions (candidate_id, from_state, to_state, reason, actor, at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                candidate_id,
                from_state.value if from_state is not None else None,
                to_state.value,
                reason,
                actor,
                now,
            ),
        )
        transition_id = int(cur.lastrowid or 0)
        row = self.row(candidate_id)
        payload_hash = row.payload_hash if row is not None else ""
        self._audit.append(
            candidate_id=candidate_id,
            transition_id=transition_id,
            kind=kind,
            from_state=from_state.value if from_state is not None else None,
            to_state=to_state.value,
            payload_hash=payload_hash,
            reason=reason,
            actor=actor,
            recorded_at=now,
            detail=json.dumps({"reason": reason, "actor": actor}),
        )
        return transition_id
```
Add `import json` at the top of `store.py`. In `revoke`, change its `_insert_transition(...)` call to pass `kind="revoke"`; in `erase`, pass `kind="erase"`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/kgis/ledger/test_audit.py -v && pytest tests/kgis/ledger -q`
Expected: PASS — audit tests plus all earlier ledger tests still green (the transition/revoke/erase paths now also write audit rows).

- [ ] **Step 6: Verify toolchain + commit**

```bash
pytest tests/kgis -q && ruff check src tests && mypy src
git add src/kgis/ledger/audit.py src/kgis/ledger/store.py tests/kgis/ledger/test_audit.py
git commit -m "feat(kgis): append-only audit stream per ledger transition (spec 7.8)"
```

---

## Task Group 4 — Ingestion integration + public API

Prove Plan 4 (the already-merged ingestion engine) composes with Plan 2 unchanged: the real `IngestPipeline` submits into the persistent ledger through the frozen `CandidateSink` port, reads back through `LedgerReader`, and `plan()`'s `ledger_duplicates` becomes a real count instead of the honest `None`.

### Task 14: Real ingestion pipeline → `SqliteCandidateLedger` → read-back

**Files:**
- Test: `tests/kgis/test_ingestion_ledger_integration.py`

**Interfaces:**
- Consumes (all from the merged Plan 4 `kgis` package on `main`): `IngestPipeline` (`kgis.pipeline`), `IterableRecordReader` (`kgis.sources`), `PassthroughNormalizer` (`kgis.normalize`), `EntityCandidateBuilder`, `SourceScoring` (`kgis.builders`); `SqliteCandidateLedger` (Task 7-8). The pipeline's public ctor is `IngestPipeline(graph_id, reader, normalizer, builder, sink, scoring, *, ledger_reader=None, ...)`; `run() -> IngestionReport` (with `.received`, `.duplicates`); `plan() -> IngestionReport` (with `.plan: DryRunPlan`, whose `.ledger_duplicates: int | None`). The `SqliteCandidateLedger` serves as **both** `sink=` and `ledger_reader=` (it implements both ports).
- Produces: an end-to-end integration test (no new src).

- [ ] **Step 1: Write the failing test**

```python
# tests/kgis/test_ingestion_ledger_integration.py
from kg_contracts.curation import ProcessingState
from kgis.builders import EntityCandidateBuilder, SourceScoring
from kgis.ledger.store import SqliteCandidateLedger
from kgis.normalize import PassthroughNormalizer
from kgis.pipeline import IngestPipeline
from kgis.sources import IterableRecordReader

_RECORDS = [{"id": "p1"}, {"id": "p2"}, {"id": "p3"}]


def _pipeline(ledger: SqliteCandidateLedger) -> IngestPipeline:
    return IngestPipeline(
        graph_id="baseball",
        reader=IterableRecordReader(_RECORDS, source_type="roster", locator="memory://roster"),
        normalizer=PassthroughNormalizer(),
        builder=EntityCandidateBuilder(namespace="usssa", key_field="id", entity_type="Player"),
        sink=ledger,
        scoring=SourceScoring(source_reliability=0.9),
        ledger_reader=ledger,
    )


def test_pipeline_persists_to_ledger_and_reads_back(tmp_path):
    path = str(tmp_path / "ledger.db")
    ledger = SqliteCandidateLedger(path)

    report = _pipeline(ledger).run()
    assert report.received == 3

    entries = ledger.ledger_entries()
    assert len(entries) == 3
    assert {e.processing_state for e in entries} == {ProcessingState.RECEIVED}

    # Dry-run over the now-populated ledger: ledger_duplicates is a REAL count, not None.
    dry = _pipeline(ledger).plan()
    assert dry.plan is not None
    assert dry.plan.ledger_duplicates == 3

    ledger.close()


def test_cross_run_replay_via_reopened_ledger(tmp_path):
    path = str(tmp_path / "ledger.db")
    first = SqliteCandidateLedger(path)
    assert _pipeline(first).run().received == 3
    first.close()

    reopened = SqliteCandidateLedger(path)
    report = _pipeline(reopened).run()
    assert report.duplicates == 3          # every candidate already in the durable ledger
    assert len(reopened.ledger_entries()) == 3
    reopened.close()
```

- [ ] **Step 2: Run test to verify it fails, then confirm it passes**

Run: `pytest tests/kgis/test_ingestion_ledger_integration.py -v`
Expected first: FAIL only if any wiring name drifts from the merged pipeline — reconcile against `kgis.pipeline.IngestPipeline`'s actual public ctor/return names (they are frozen on `main`). Once wired, both tests PASS: the real pipeline composes onto the persistent ledger unchanged, and `ledger_duplicates` reports `3`.

- [ ] **Step 3: Verify toolchain + commit**

```bash
pytest tests/kgis/test_ingestion_ledger_integration.py -q && ruff check src tests && mypy src
git add tests/kgis/test_ingestion_ledger_integration.py
git commit -m "test(kgis): Plan 4 ingestion composes onto persistent ledger; ledger_duplicates real"
```

---

### Task 15: Public API, full quality gate, memory-bank sync

**Files:**
- Modify: `src/kgis/ledger/__init__.py`, `src/kgis/evidence/__init__.py`
- Modify: `llm/memory_bank/activeContext.md`, `llm/memory_bank/progress.md`
- Test: `tests/kgis/test_public_api.py`

**Interfaces:**
- Consumes: everything from Tasks 4–14.
- Produces: stable import surfaces `from kgis.ledger import SqliteCandidateLedger, ...` and `from kgis.evidence import SqliteEvidenceRegistry, ...`; a green whole-repo gate.

- [ ] **Step 1: Write the failing test**

```python
# tests/kgis/test_public_api.py
def test_ledger_public_surface() -> None:
    from kgis.ledger import (  # noqa: F401
        BASEBALL_AI_PROFILE, ConsumerProfile, IdentityMode, IdentityResolver,
        IllegalTransitionError, LedgerRow, PersistentLedgerContract,
        SqliteAuditStream, SqliteCandidateLedger, open_ledger_db,
    )


def test_evidence_public_surface() -> None:
    from kgis.evidence import (  # noqa: F401
        EvidenceNotFoundError, EvidenceRegistryContract, SqliteEvidenceRegistry,
        open_evidence_db,
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/kgis/test_public_api.py -v`
Expected: FAIL — `ImportError` (the `__init__.py` files are empty).

- [ ] **Step 3: Populate the package exports**

```python
# src/kgis/ledger/__init__.py
"""Persistent candidate ledger (ADR-0006 store 1; ADR-0012/0013/0014)."""

from kgis.ledger.audit import SqliteAuditStream
from kgis.ledger.config import (
    BASEBALL_AI_PROFILE,
    ConsumerProfile,
    IdentityMode,
    IdentityResolver,
)
from kgis.ledger.contract import PersistentLedgerContract
from kgis.ledger.lifecycle import IllegalTransitionError
from kgis.ledger.row import LedgerRow
from kgis.ledger.schema import open_ledger_db
from kgis.ledger.store import SqliteCandidateLedger

__all__ = [
    "BASEBALL_AI_PROFILE",
    "ConsumerProfile",
    "IdentityMode",
    "IdentityResolver",
    "IllegalTransitionError",
    "LedgerRow",
    "PersistentLedgerContract",
    "SqliteAuditStream",
    "SqliteCandidateLedger",
    "open_ledger_db",
]
```

```python
# src/kgis/evidence/__init__.py
"""Persistent evidence registry (spec §5.3)."""

from kgis.evidence.contract import EvidenceRegistryContract
from kgis.evidence.schema import open_evidence_db
from kgis.evidence.store import EvidenceNotFoundError, SqliteEvidenceRegistry

__all__ = [
    "EvidenceNotFoundError",
    "EvidenceRegistryContract",
    "SqliteEvidenceRegistry",
    "open_evidence_db",
]
```

- [ ] **Step 4: Run the full quality gate**

```bash
pytest -q            # every Plan 1 contract test + all new kgis tests green
ruff check src tests
mypy src
```
Expected: all tests pass (the 171+ existing contract tests, unchanged, plus the new ledger/evidence/audit/integration suites); ruff clean; mypy --strict clean on `src`. Fix any finding before proceeding.

- [ ] **Step 5: Sync the memory bank**

`llm/memory_bank/activeContext.md`: current work = Plan 2 complete (persistent candidate ledger + evidence registry + audit); next = Plan 3 (curation core + executor, KGCS). `llm/memory_bank/progress.md`: dated entry — Issue #7 closed (FrozenDict at-rest immutability); SQLite candidate ledger implementing `CandidateSink`/`LedgerReader` with cross-run idempotency, bitemporal columns, `ProcessingState` lifecycle, revoke/erase + consumer profile (ADR-0012/0013/0014, Issue #2 folded in); persistent evidence registry; append-only audit stream; merged ingestion composes onto the ledger. Note the deferred items below.

- [ ] **Step 6: Commit**

```bash
git add src/kgis/ledger/__init__.py src/kgis/evidence/__init__.py tests/kgis/test_public_api.py llm/memory_bank/
git commit -m "feat(kgis): public ledger/evidence API + memory-bank sync (Plan 2 complete)"
```

---

## Deferred / explicitly out of scope for Plan 2

- **Curation core + executor + `GraphMutationStore`** — Plan 3 (KGCS). This plan builds no canonical-graph write path; `GraphMutationStore` is executor-only and not implemented here.
- **Entity resolution** — Plan 5. `IdentityResolver` is only a yes/no ambiguity seam for REJECT_ONLY; blocking/features/calibrated matching are not built.
- **Heavy graph backends** (Neo4j/Spanner) and **full temporal query on every backend** — capability-declared later; only the SQLite/memory tier ships temporal capability now.
- **Review-queue persistence** — the `ReviewQueue` contract stays memory-backed (Plan 1); its durable store is Plan 6.

## Plan 2 Definition of Done

- Issue #7 closed: dict payload fields are read-only at rest (`FrozenDict`), JSON round-trip byte-stable, all pre-existing contract tests green.
- `SqliteCandidateLedger` passes the unchanged `CandidateSinkContract` and `LedgerReaderContract`, plus the new `PersistentLedgerContract` (reopen + cross-run replay).
- The ledger tracks the full persisted row (dedup key, retry counter, quarantine reason, bitemporal valid/transaction time), an auditable `ProcessingState` lifecycle (R1: OBSOLETE), and a revoke/erase governance surface with a consumer profile (ADR-0013/0014, Issue #2).
- `SqliteEvidenceRegistry` persists PRESENT/ABSENT/ERROR evidence resolvable by `evidence_id`, resolves `EvidenceRef` relationships, and never silently drops a dangling ref; passes `EvidenceRegistryContract`.
- Every ledger transition writes an immutable, append-only `audit_records` row (spec §7.8); erase leaves a hash-only tombstone.
- The merged Plan 4 ingestion pipeline composes onto the persistent ledger unchanged; `plan().plan.ledger_duplicates` returns a real count.
- ADRs 0012/0013/0014 written and indexed; only Task Group 0 edited `kg_contracts`; `ruff`, `mypy --strict`, and `pytest` all green.

### Spec coverage

| Spec / requirement | Task(s) |
|---|---|
| Issue #7 at-rest immutability (frozen mapping) | 1, 2, 3 |
| §3.2 three-store separation / ledger persistence (ADR-0006/0012) | 4, 7, 8 |
| §5.2 Candidate persisted + replayable | 5, 7 |
| §5.4 bitemporal (valid + transaction time) | 4, 5, 8 |
| §5.6 two-level store contracts — `CandidateSink` write, `LedgerReader` read | 7, 8 |
| §5.7 capability declaration (temporal) | 8 |
| §5.8 idempotency by semantic key; cross-run replay | 5, 7, 14 |
| §7.1–§7.2 processing-state lifecycle + quarantine/retry (R1 OBSOLETE) | 6, 9 |
| §7.8 immutable audit stream | 13 |
| §5.3 evidence registry (PRESENT/ABSENT/ERROR; refs) | 11, 12 |
| Issue #2 revoke/erasure, reject-only identity, consumer profile | 10 |
| Plan 4 composition (ledger_duplicates real) | 14 |
| Public API + quality gate + memory bank | 15 |
