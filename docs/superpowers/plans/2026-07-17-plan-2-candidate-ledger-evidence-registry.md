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
- Create: `docs/adr/0012-candidate-ledger-persistence.md`, `docs/adr/0013-ledger-revoke-and-erasure.md` (Issue #2), `docs/adr/0014-reject-only-identity-mode.md` (Issue #2).
- Test: `tests/kgis/ledger/test_sink.py`, `test_reader.py`, `test_lifecycle.py`, `test_idempotency.py`, `test_revoke_erasure.py`, `test_bitemporal.py`.

**Task Group 2 — Evidence registry (`src/kgis/evidence/`):**
- Create: `src/kgis/evidence/__init__.py`, `src/kgis/evidence/schema.py`, `src/kgis/evidence/store.py` — `SqliteEvidenceRegistry` (put/resolve `Evidence`, resolve `EvidenceRef`).
- Test: `tests/kgis/evidence/test_registry.py`.

**Task Group 3 — Audit stream (`src/kgis/ledger/audit.py`):**
- Create: `src/kgis/ledger/audit.py` — append-only `SqliteAuditStream` writing an immutable record per transition.
- Test: `tests/kgis/ledger/test_audit.py`.

**Task Group 4 — Contract suites + ingestion integration:**
- Create: `src/kg_contracts/testing/contract.py` additions — `CandidateSinkContract`, `EvidenceRegistryContract` reusable suites (co-located with `LedgerReaderContract`).
- Test: `tests/kgis/test_ingestion_ledger_integration.py` — real Plan 4 pipeline → `SqliteCandidateLedger` → `LedgerReader` read-back; `ledger_duplicates` returns a real count.

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
from pydantic.functional_validators import BeforeValidator

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
        BeforeValidator(_validate),
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
