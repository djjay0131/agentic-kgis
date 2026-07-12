# KGIS/KGCS Plan 1 v2: Bootstrap Completion + kg_contracts v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the bootstrap of both repos (packaging, src layout, quality gates, CI — the memory banks and governance docs already exist) and deliver a complete, tested `kg_contracts` v2 package per spec v2 §5: namespaced identity, the nine-variant typed candidate union with `CandidateEnvelope` + `CandidateScores`, first-class evidence, bitemporal assertions, derivation lineage, two-level store contracts (`CandidateSink` / `GraphMutationStore`), split reader/writer protocols with capability declarations, curation/ingestion/registry/policy/security/versioning contracts, in-memory reference adapters, and reusable contract test suites.

**Supersedes:** `docs/superpowers/plans/2026-07-09-01-bootstrap-and-contracts.md` (Plan 1 v1 — written against spec v1; obsoleted by the approved disposition of external review PR #1, `docs/ai/chatgpt-feedback-disposition.md`).

**Architecture:** `agentic-kgis` ships **three** packages from one distribution (ADR-0002 as amended): `kg_contracts` (pure ports layer — Pydantic models and `typing.Protocol` interfaces; no engine/LLM/network code), `kgis` (ingestion implementations, Plan 4), and `kg_eval` (evaluation harness, Plan 6; skeleton only here). `agentic-kgcs` depends only on `kg_contracts`. In-memory reference adapters and the contract test suites live under `kg_contracts.testing` so both repos test against them with no extra dependencies.

**Tech Stack:** Python ≥3.11, Pydantic v2, pytest, ruff, mypy --strict, hatchling build backend.

**Spec (design authority):** `docs/superpowers/specs/2026-07-09-kgis-kgcs-design.md` **v2** — §5 (contracts) is primary; §3.2–3.3 (three-store separation, epochs), §10.2 (contract test suites) also bind. Disposition: `docs/ai/chatgpt-feedback-disposition.md` (items A2–A17, D2). Constraining ADRs: 0006 (three-store separation, no PROVISIONAL nodes in canonical graph, curation epochs), 0007 (ER architecture), 0008 (identity model), 0009 (kg_eval + honest null), 0010 (write-path mechanism, two-level store contracts).

**Phase-0 reference reading (lessons, not code):** `kg_contracts` v2 is written **fresh**; `vttsi-contracts`, `vttsi-evidence`, and `ts-kg` are reference reading only — no vendoring (owner decision 2026-07-10, spec §11 Phase 0). Lessons already harvested into this plan are called out inline as *Phase-0 lesson* notes.

**Plan sequence** (this is Plan 1 of 7 — spec v2 §11; later plans are written after their predecessors complete):
1. **This plan** — bootstrap completion + `kg_contracts` v2
2. Candidate ledger + evidence registry
3. Curation core + executor
4. Ingestion modes (structured sync + LLM extraction)
5. Entity resolution (5a blocking/features/calibrated matcher + golden sets; 5b LLM adviser, cluster validation, Splink/dedupe benchmark)
6. `kg_eval` + review API
7. Registry + advisor

## Global Constraints

- Python `>=3.11`; sole runtime dependency of `kg_contracts` is `pydantic>=2.0`
- `kg_contracts` contains NO engine code, NO LLM code, NO network/file I/O (spec §5); in-memory adapters under `kg_contracts.testing` are allowed (pure dicts)
- **Identity (ADR-0008):** every canonical entity has an immutable internal identity ID (`kg://<graph-id>/identity/<ulid>`) plus namespaced external aliases `EntityRef{entity_type, namespace, key}` rendered `Label:namespace:key` only at adapter boundaries. Bare `Label:key` is deprecated for cross-project use and MUST NOT appear in any v2 contract. Entity types PascalCase `^[A-Z][A-Za-z0-9]*$`; relation types UPPER_SNAKE `^[A-Z][A-Z0-9_]*$` (ts-kg lineage, format upgraded)
- **Candidates (A2/D2):** `Candidate` is a discriminated union of ALL NINE variants (entity, relation, attribute-assertion, observation, derived-assertion, artifact, plan, ontology, identity-link) on discriminator `candidate_kind`. v1 IMPLEMENTS (full validation + tests) entity / relation / attribute-assertion / artifact; the other five are defined spec-level with placeholder validation and explicit `SPEC-LEVEL` docstrings
- **A single `confidence` float is banned.** All scoring uses `CandidateScores` (extraction_confidence, identity_confidence, assertion_confidence, source_reliability, corroboration_score, policy_risk)
- **Evidence is first-class** (vttsi-evidence lineage): availability is explicit `present | absent | error`; evidence is never silently dropped
- **Bitemporal assertions:** every assertion contract carries valid time AND transaction time (spec §5.4); curation status attaches at assertion level, not only whole-node level
- **Store contracts (ADR-0010):** `CandidateSink` is the ONLY application-facing write surface; `GraphMutationStore` is executor-only. No `upsert_nodes`-style raw writes on any consumer-facing protocol. Read/write protocols are split; adapters declare capabilities. No Cypher/GQL on core contracts
- **No PROVISIONAL nodes in the canonical graph (ADR-0006):** candidate/processing states live on candidates in the ledger, not as a canonical-graph node status; `CurationStatus` in v2 applies to canonical assertions/entities as ACTIVE/SUPERSEDED/REVOKED lifecycle only
- **Idempotency:** stable source coordinates + semantic keys; content hashes are a supplementary signal only (spec §5.8)
- All contract models are frozen (immutable) Pydantic models unless a task explicitly says otherwise (accumulators)
- TDD for every behavior-bearing module; run commands from the repo root; venv at `.venv`
- Commit after every task (frequent commits)

## Task Overview

Dependency-ordered (each task consumes only earlier tasks' outputs — no circular imports):

| # | Task | Module |
|---|------|--------|
| 1 | agentic-kgis packaging completion (three packages) | pyproject, src layout |
| 2 | agentic-kgcs packaging completion | sibling repo |
| 3 | ULID helper + security/policy stub + universal trace ID | `_ulid.py`, `security.py` |
| 4 | Evidence contract (ValidPeriod, Provenance, Evidence, EvidenceRef) | `evidence.py` |
| 5 | Identity model (identity IDs, EntityRef, identity links) | `identity.py` |
| 6 | Derivation lineage | `derivation.py` |
| 7 | Versioning + compatibility classes | `versioning.py` |
| 8 | CandidateScores + CandidateEnvelope | `candidates.py` |
| 9 | Implemented candidate variants (entity/relation/attribute-assertion/artifact) | `candidates.py` |
| 10 | Spec-level variants (5) + `Candidate` discriminated union | `candidates.py` |
| 11 | Bitemporal assertions, canonical entity, conflict representation | `assertions.py` |
| 12 | Score-set-aware ConfidencePolicy | `policy.py` |
| 13 | Read-side store contracts: GraphReadOptions, capabilities, readers | `stores.py` |
| 14 | Curation: processing states, operations, decisions, CurationPlan, review | `curation.py` |
| 15 | Write-side store contracts: CandidateSink, GraphMutationStore | `stores.py` |
| 16 | Ingestion contracts | `ingestion.py` |
| 17 | Registry contracts | `registry.py` |
| 18 | Memory adapters + reusable contract test suites | `testing/` |
| 19 | Public API, quality gate, CI, cross-repo verification, memory bank | `__init__.py`, CI |

---

### Task 1: Complete agentic-kgis packaging (three packages)

The repo already exists (governance docs, ADRs, spec, memory bank at `llm/memory_bank/`). This task adds what is missing: packaging, src layout, and quality-gate wiring. **Three** packages ship from the one `agentic-kgis` distribution (ADR-0002 as amended): `kg_contracts`, `kgis`, `kg_eval`.

**Files:**
- Create: `/Users/djjay0131/code/agentic-kgis/pyproject.toml`
- Create: `/Users/djjay0131/code/agentic-kgis/.gitignore`
- Create: `/Users/djjay0131/code/agentic-kgis/README.md`
- Create: `/Users/djjay0131/code/agentic-kgis/src/kg_contracts/__init__.py`
- Create: `/Users/djjay0131/code/agentic-kgis/src/kgis/__init__.py`
- Create: `/Users/djjay0131/code/agentic-kgis/src/kg_eval/__init__.py`
- Test: `/Users/djjay0131/code/agentic-kgis/tests/test_packaging.py`

**Interfaces:**
- Consumes: nothing (repo already exists with docs + memory bank committed)
- Produces: installable editable package exposing importable `kg_contracts`, `kgis`, and `kg_eval`; `.venv/bin/pytest` runs

- [ ] **Step 1: Write the failing test**

`tests/test_packaging.py`:
```python
def test_packages_import() -> None:
    import kg_contracts
    import kg_eval
    import kgis

    assert kg_contracts.__name__ == "kg_contracts"
    assert kgis.__name__ == "kgis"
    assert kg_eval.__name__ == "kg_eval"
```

- [ ] **Step 2: Create pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "agentic-kgis"
version = "0.2.0"
description = "Knowledge Graph Ingestion Service: kg_contracts ports layer, kgis ingestion, kg_eval evaluation"
requires-python = ">=3.11"
dependencies = ["pydantic>=2.0"]

[project.optional-dependencies]
dev = ["pytest>=8.0", "ruff>=0.4", "mypy>=1.10"]

[tool.hatch.build.targets.wheel]
packages = ["src/kg_contracts", "src/kgis", "src/kg_eval"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
src = ["src", "tests"]

[tool.mypy]
python_version = "3.11"
strict = true
mypy_path = "src"

[[tool.mypy.overrides]]
module = "tests.*"
strict = false
```

- [ ] **Step 3: Create .gitignore, README.md, and empty package inits**

`.gitignore`:
```
.venv/
__pycache__/
*.egg-info/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
dist/
```

`README.md`:
```markdown
# agentic-kgis

Knowledge Graph Ingestion Service. Ships three packages (ADR-0002 as amended):

- **kg_contracts** — domain-neutral ports layer v2 (identity, candidates,
  evidence, bitemporal assertions, derivation, two-level store contracts,
  curation/ingestion/registry/policy contracts, contract test suites).
  No engine, LLM, or I/O code.
- **kgis** — ingestion implementations (structured sync + LLM extraction;
  Plan 4).
- **kg_eval** — evaluation harness with honest-null discipline (ADR-0009;
  Plan 6).

Design: `docs/superpowers/specs/2026-07-09-kgis-kgcs-design.md` (v2)
Companion repo: `agentic-kgcs` (curation service; depends on kg_contracts).

## Dev setup

    python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
    .venv/bin/pytest
```

`src/kg_contracts/__init__.py`, `src/kgis/__init__.py`, `src/kg_eval/__init__.py`: empty files (`kg_eval` stays a skeleton until Plan 6; creating it now keeps packaging honest to ADR-0002 from day one).

- [ ] **Step 4: Install and run test to verify it passes**

```bash
cd /Users/djjay0131/code/agentic-kgis
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -v
```
Expected: `test_packages_import PASSED` (1 passed)

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .gitignore README.md src tests
git commit -m "chore: complete packaging — kg_contracts, kgis, kg_eval (ADR-0002 as amended)"
```

---

### Task 2: Complete agentic-kgcs packaging

The sibling repo already exists with governance docs and a memory bank. This task adds packaging only.

**Files:**
- Create: `/Users/djjay0131/code/agentic-kgcs/pyproject.toml`
- Create: `/Users/djjay0131/code/agentic-kgcs/.gitignore` (same content as Task 1)
- Create: `/Users/djjay0131/code/agentic-kgcs/README.md`
- Create: `/Users/djjay0131/code/agentic-kgcs/src/kgcs/__init__.py`
- Test: `/Users/djjay0131/code/agentic-kgcs/tests/test_packaging.py`

**Interfaces:**
- Consumes: editable install of `agentic-kgis` from the sibling directory
- Produces: installable `kgcs` package that can `import kg_contracts`

- [ ] **Step 1: Write the failing test**

`tests/test_packaging.py`:
```python
def test_kgcs_imports_and_sees_contracts() -> None:
    import kg_contracts
    import kgcs

    assert kgcs.__name__ == "kgcs"
    assert kg_contracts.__name__ == "kg_contracts"
```

- [ ] **Step 2: Create scaffolding**

`pyproject.toml`:
```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "agentic-kgcs"
version = "0.2.0"
description = "Knowledge Graph Curation Service (admission, curation core + executor, review)"
requires-python = ">=3.11"
dependencies = ["agentic-kgis>=0.2.0"]

[project.optional-dependencies]
dev = ["pytest>=8.0", "ruff>=0.4", "mypy>=1.10"]

[tool.hatch.build.targets.wheel]
packages = ["src/kgcs"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
src = ["src", "tests"]

[tool.mypy]
python_version = "3.11"
strict = true
mypy_path = "src"

[[tool.mypy.overrides]]
module = "tests.*"
strict = false
```

`README.md`:
```markdown
# agentic-kgcs

Knowledge Graph Curation Service. Ships `kgcs`:

- **admission/** — synchronous deterministic checks on candidate submission
  (contract validation, identity syntax repair-or-reject, ontology
  enforcement, policy, idempotency). Gates canonical semantic mutations only.
- **core/** — pure curation core: Candidate → ValidationDecision →
  ResolutionDecision → CurationPlan (no database connection; ADR-0010).
- **executor/** — applies CurationPlans against GraphMutationStore under
  optimistic preconditions; compensating rollback.
- **resolution/** — ER pipeline: blocking → typed features → calibrated
  matcher → cluster validation → policy gate (ADR-0007).
- **review/** — review-domain operations API + CLI.

Depends only on `kg_contracts` (shipped by sibling repo `agentic-kgis`).
Design: `agentic-kgis/docs/superpowers/specs/2026-07-09-kgis-kgcs-design.md` (v2)

## Dev setup

    python3 -m venv .venv
    .venv/bin/pip install -e ../agentic-kgis -e '.[dev]'
    .venv/bin/pytest
```

`.gitignore`: same content as Task 1. `src/kgcs/__init__.py`: empty file.

- [ ] **Step 3: Install and run test to verify it passes**

```bash
cd /Users/djjay0131/code/agentic-kgcs
python3 -m venv .venv
.venv/bin/pip install -e ../agentic-kgis -e '.[dev]'
.venv/bin/pytest -v
```
Expected: `test_kgcs_imports_and_sees_contracts PASSED` (1 passed)

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml .gitignore README.md src tests
git commit -m "chore: complete packaging — kgcs depends on kg_contracts"
```

---

### Task 3: ULID helper, security/policy stub, universal trace ID

**Files:**
- Create: `/Users/djjay0131/code/agentic-kgis/src/kg_contracts/_ulid.py`
- Create: `/Users/djjay0131/code/agentic-kgis/src/kg_contracts/security.py`
- Test: `/Users/djjay0131/code/agentic-kgis/tests/contracts/test_security.py`

**Interfaces:**
- Consumes: stdlib only (`os.urandom`, `time`)
- Produces:
  - `_ulid.new_ulid() -> str` — 26-char Crockford-base32 ULID (48-bit ms timestamp + 80 random bits); internal helper for identity IDs (Task 5), trace IDs, and later ledger IDs. No third-party dependency.
  - `security.new_trace_id() -> str` — `"trace_" + new_ulid()`. The **universal trace ID** (spec §5.9) carried from source record → extraction run → candidates → validation → resolution → curation operation → graph mutation → derived indexes → consumer query.
  - `security.DeletionBehavior` StrEnum: `HARD_DELETE`, `TOMBSTONE`, `RETAIN`
  - `security.PolicyContext` (frozen) — v1 **stub**, designed before the baseball graph accumulates youth data: `actor: str`, `tenant: str | None = None`, `purpose: str | None = None`, `sensitivity_tags: tuple[str, ...] = ()`, `redaction_policy: str | None = None`, `deletion_behavior: DeletionBehavior = TOMBSTONE`. Full enforcement is phased (spec §5.9); the *shape* ships in v1 so every later contract can carry one.

- [ ] **Step 1: Write the failing tests**

`tests/contracts/test_security.py`:
```python
import pytest
from pydantic import ValidationError

from kg_contracts._ulid import new_ulid
from kg_contracts.security import DeletionBehavior, PolicyContext, new_trace_id


def test_ulid_shape_and_uniqueness():
    a, b = new_ulid(), new_ulid()
    assert len(a) == 26 and a != b
    # Crockford base32: no I, L, O, U
    assert all(c in "0123456789ABCDEFGHJKMNPQRSTVWXYZ" for c in a)


def test_ulids_sort_by_time():
    import time

    a = new_ulid()
    time.sleep(0.002)
    b = new_ulid()
    assert a < b  # lexicographic order == creation order


def test_trace_id_prefixed():
    t = new_trace_id()
    assert t.startswith("trace_") and len(t) == len("trace_") + 26


def test_policy_context_stub_defaults_and_frozen():
    ctx = PolicyContext(actor="ingest-pipeline")
    assert ctx.deletion_behavior is DeletionBehavior.TOMBSTONE
    assert ctx.sensitivity_tags == ()
    with pytest.raises(ValidationError):
        ctx.actor = "someone-else"  # type: ignore[misc]


def test_policy_context_requires_actor():
    with pytest.raises(ValidationError):
        PolicyContext()  # type: ignore[call-arg]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/contracts/test_security.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kg_contracts._ulid'`

- [ ] **Step 3: Implement `_ulid.py` and `security.py`**

`_ulid.py`: encode `int(time.time() * 1000)` into 10 Crockford chars + `os.urandom(10)` into 16 chars (standard ULID layout). Pure stdlib, ~20 lines. `security.py`: models exactly as specified in Interfaces, all frozen (`ConfigDict(frozen=True)`), module docstring citing spec §5.9 and noting the stub status.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/contracts/test_security.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/kg_contracts/_ulid.py src/kg_contracts/security.py tests/contracts/test_security.py
git commit -m "feat(contracts): ULID helper, PolicyContext stub, universal trace ID"
```

---

### Task 4: kg_contracts.evidence — first-class evidence contract

*Phase-0 lesson (vttsi-evidence):* absence has distinct meanings ("no source queried" / "source omitted it" / "source unavailable" / "sources contradict" / "source states unknown"); representing availability explicitly prevents an LLM reading graph context from turning absent data into an inferred fact. Providers record absence/error instead of throwing failures upward.

**Files:**
- Create: `/Users/djjay0131/code/agentic-kgis/src/kg_contracts/evidence.py`
- Test: `/Users/djjay0131/code/agentic-kgis/tests/contracts/test_evidence.py`

**Interfaces:**
- Consumes: `new_ulid` (Task 3)
- Produces (spec §5.3; all frozen):
  - `ValidPeriod(valid_from: datetime | None = None, valid_to: datetime | None = None)` — domain valid-time interval; validates `valid_from <= valid_to` when both set. Shared by Evidence, assertion candidates (Task 9), and assertions (Task 11)
  - `Provenance(source: str, source_ref: str | None, actor: str, model: str | None, prompt_version: str | None)` — where a record came from; never dropped
  - `EvidenceAvailability` StrEnum: `PRESENT`, `ABSENT`, `ERROR`
  - `AbsenceReason` StrEnum: `NOT_QUERIED`, `SOURCE_OMITTED`, `SOURCE_UNAVAILABLE`, `SOURCES_CONTRADICT`, `SOURCE_STATES_UNKNOWN`
  - `Evidence(evidence_id: str = "ev_" + ulid default, source_type: str, source_locator: str, observed_at: datetime, valid_time: ValidPeriod | None, availability: EvidenceAvailability, absence_reason: AbsenceReason | None, payload_hash: str | None, content: str | None, error: str | None, provenance: Provenance)` — cross-field rules: `PRESENT` requires `content` or `payload_hash` and forbids `absence_reason`/`error`; `ABSENT` requires `absence_reason`; `ERROR` requires `error`
  - `EvidenceRelationship` StrEnum: `SUPPORTS`, `CONTRADICTS`, `DERIVED_FROM`, `CONTEXTUALIZES`
  - `EvidenceRef(evidence_id: str, relationship: EvidenceRelationship)` — how a candidate/assertion cites evidence

- [ ] **Step 1: Write the failing tests**

`tests/contracts/test_evidence.py`:
```python
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from kg_contracts.evidence import (
    AbsenceReason,
    Evidence,
    EvidenceAvailability,
    EvidenceRef,
    EvidenceRelationship,
    Provenance,
    ValidPeriod,
)

NOW = datetime(2026, 7, 12, tzinfo=UTC)
PROV = Provenance(source="unit-test", actor="tester")


def _evidence(**overrides: object) -> Evidence:
    base: dict[str, object] = dict(
        source_type="document",
        source_locator="s3://bucket/doc.pdf#page=3",
        observed_at=NOW,
        availability=EvidenceAvailability.PRESENT,
        content="Player X hit .312 in 2025",
        provenance=PROV,
    )
    base.update(overrides)
    return Evidence(**base)  # type: ignore[arg-type]


def test_valid_period_ordering_enforced():
    with pytest.raises(ValidationError, match="valid_from"):
        ValidPeriod(valid_from=datetime(2026, 1, 2, tzinfo=UTC),
                    valid_to=datetime(2026, 1, 1, tzinfo=UTC))
    assert ValidPeriod(valid_from=NOW).valid_to is None  # open-ended OK


def test_evidence_id_generated_and_stable_shape():
    e = _evidence()
    assert e.evidence_id.startswith("ev_") and len(e.evidence_id) == 3 + 26


def test_present_requires_content_or_hash():
    with pytest.raises(ValidationError, match="PRESENT"):
        _evidence(content=None, payload_hash=None)


def test_absent_requires_absence_reason_and_forbids_content():
    a = _evidence(
        availability=EvidenceAvailability.ABSENT,
        content=None,
        absence_reason=AbsenceReason.SOURCE_UNAVAILABLE,
    )
    assert a.absence_reason is AbsenceReason.SOURCE_UNAVAILABLE
    with pytest.raises(ValidationError, match="ABSENT"):
        _evidence(availability=EvidenceAvailability.ABSENT, content=None)


def test_error_requires_error_message():
    err = _evidence(availability=EvidenceAvailability.ERROR, content=None,
                    error="timeout fetching source")
    assert err.error == "timeout fetching source"
    with pytest.raises(ValidationError, match="ERROR"):
        _evidence(availability=EvidenceAvailability.ERROR, content=None)


def test_evidence_ref_relationships():
    r = EvidenceRef(evidence_id="ev_x", relationship=EvidenceRelationship.CONTRADICTS)
    assert r.relationship is EvidenceRelationship.CONTRADICTS
    assert {v.value for v in EvidenceRelationship} == {
        "SUPPORTS", "CONTRADICTS", "DERIVED_FROM", "CONTEXTUALIZES"
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/contracts/test_evidence.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kg_contracts.evidence'`

- [ ] **Step 3: Implement `evidence.py`**

All models frozen; `evidence_id` uses `Field(default_factory=lambda: "ev_" + new_ulid())`; the availability cross-field rules live in one `@model_validator(mode="after")` on `Evidence` with error messages naming the availability state. Module docstring: evidence is first-class, never silently dropped (spec §5.3); storage/providers live in `kgis` (Plan 2), the contract lives here.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/contracts/test_evidence.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/kg_contracts/evidence.py tests/contracts/test_evidence.py
git commit -m "feat(contracts): first-class Evidence with explicit availability (spec 5.3)"
```

---

### Task 5: kg_contracts.identity — identity IDs, EntityRef, identity links

*Phase-0 lesson (ts-kg `canonical.py` / agentic-tskg 0/18 failure):* free-text IDs destroy ingestion; repair if unambiguous, reject **naming the offending ID**, never silently coerce. The discipline survives; only the format is upgraded (ADR-0008). Bare `Label:key` is deprecated — it says nothing about who issued the key.

**Files:**
- Create: `/Users/djjay0131/code/agentic-kgis/src/kg_contracts/identity.py`
- Test: `/Users/djjay0131/code/agentic-kgis/tests/contracts/test_identity.py`

**Interfaces:**
- Consumes: `new_ulid` (Task 3), `Provenance` (Task 4)
- Produces (spec §5.1, ADR-0008):
  - `IdentityError(ValueError)`
  - `new_identity_id(graph_id: str) -> str` — `kg://<graph-id>/identity/<ulid>`; graph_id validated `^[a-z][a-z0-9-]*$`
  - `is_identity_id(value: str) -> bool`, `parse_identity_id(value: str) -> tuple[str, str]` (graph_id, ulid) — raises `IdentityError` naming the offending value
  - `EntityRef(entity_type: str, namespace: str, key: str)` (frozen) — entity_type PascalCase `^[A-Z][A-Za-z0-9]*$`; namespace `^[a-z][a-z0-9_.-]*$` (who issued the key: `doi`, `orcid`, `usssa`, `vttsi`, `postgres.intersections`); key non-empty after strip. `render() -> str` produces `"Type:namespace:key"` (adapter boundaries only); `EntityRef.parse(text)` is strict repair-or-reject: splits on the first two colons, raises `IdentityError` naming the input on any violation — including bare `Label:key` (message must say the namespace is missing). Unambiguous *repair* (e.g. case-folding a known namespace) is an admission-time concern (KGCS, Plan 3), not a contract concern
  - `IdentityLinkKind` StrEnum: `SAME_AS`, `POSSIBLY_SAME_AS`, `RELATED_TO`
  - `IdentityLink(link_id: str = "il_" + ulid default, left_identity: str, right_identity: str, kind: IdentityLinkKind, authority: str, provenance: Provenance, evidence_ids: tuple[str, ...] = ())` (frozen) — cross-graph identity, **contract-complete in v1** (implementation minimal, spec §5.1): both endpoints must be valid identity IDs; a link may span graphs (different graph_ids); `left_identity != right_identity`; authority (who is entitled to assert the mapping) is mandatory and distinct from any score

- [ ] **Step 1: Write the failing tests**

`tests/contracts/test_identity.py`:
```python
import pytest
from pydantic import ValidationError

from kg_contracts.evidence import Provenance
from kg_contracts.identity import (
    EntityRef,
    IdentityError,
    IdentityLink,
    IdentityLinkKind,
    is_identity_id,
    new_identity_id,
    parse_identity_id,
)

PROV = Provenance(source="unit-test", actor="tester")


def test_new_identity_id_shape():
    iid = new_identity_id("baseball")
    assert iid.startswith("kg://baseball/identity/")
    graph, ulid = parse_identity_id(iid)
    assert graph == "baseball" and len(ulid) == 26


def test_identity_id_rejects_bad_graph_id():
    with pytest.raises(IdentityError, match="Baseball"):
        new_identity_id("Baseball")  # graph ids are lowercase


def test_is_identity_id():
    assert is_identity_id(new_identity_id("traffic"))
    assert not is_identity_id("Player:usssa:12345")
    assert not is_identity_id("kg://traffic/other/01H")


def test_parse_rejects_naming_offender():
    with pytest.raises(IdentityError, match="not-an-id"):
        parse_identity_id("not-an-id")


def test_entity_ref_valid_and_renders_namespaced():
    ref = EntityRef(entity_type="Paper", namespace="doi", key="10.1145/3292500")
    assert ref.render() == "Paper:doi:10.1145/3292500"


def test_entity_ref_key_may_contain_colons():
    ref = EntityRef.parse("Doc:arxiv:2501.1234:v2")
    assert (ref.entity_type, ref.namespace, ref.key) == ("Doc", "arxiv", "2501.1234:v2")


def test_entity_ref_rejects_non_pascal_type_and_bad_namespace():
    with pytest.raises(ValidationError):
        EntityRef(entity_type="paper", namespace="doi", key="x")
    with pytest.raises(ValidationError):
        EntityRef(entity_type="Paper", namespace="DOI", key="x")
    with pytest.raises(ValidationError):
        EntityRef(entity_type="Paper", namespace="doi", key="  ")


def test_bare_label_key_is_rejected_with_namespace_message():
    # the deprecated v1 format must fail loudly, naming the offender
    with pytest.raises(IdentityError, match="Player:123"):
        EntityRef.parse("Player:123")
    with pytest.raises(IdentityError, match="namespace"):
        EntityRef.parse("Player:123")


def test_free_text_rejected_naming_offender():
    with pytest.raises(IdentityError, match="Main St & 1st"):
        EntityRef.parse("Main St & 1st")  # agentic-tskg failure mode


def test_identity_link_valid_cross_graph():
    a = new_identity_id("baseball")
    b = new_identity_id("agentic-kg")
    link = IdentityLink(
        left_identity=a, right_identity=b,
        kind=IdentityLinkKind.POSSIBLY_SAME_AS,
        authority="orcid", provenance=PROV,
    )
    assert link.link_id.startswith("il_")
    assert link.kind is IdentityLinkKind.POSSIBLY_SAME_AS


def test_identity_link_rejects_non_identity_endpoints_and_self_link():
    a = new_identity_id("baseball")
    with pytest.raises(ValidationError, match="identity"):
        IdentityLink(left_identity="Player:usssa:1", right_identity=a,
                     kind=IdentityLinkKind.SAME_AS, authority="x", provenance=PROV)
    with pytest.raises(ValidationError, match="itself"):
        IdentityLink(left_identity=a, right_identity=a,
                     kind=IdentityLinkKind.SAME_AS, authority="x", provenance=PROV)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/contracts/test_identity.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kg_contracts.identity'`

- [ ] **Step 3: Implement `identity.py`**

Regexes as module constants; `EntityRef.parse` uses `str.split(":", 2)` and raises `IdentityError` whose message includes the raw input and, for two-part inputs, the words "namespace is missing (bare Label:key is deprecated, ADR-0008)". `IdentityLink` validates endpoints with `is_identity_id` in a `@model_validator(mode="after")`. Module docstring cites ADR-0008 and the ts-kg lineage.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/contracts/test_identity.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add src/kg_contracts/identity.py tests/contracts/test_identity.py
git commit -m "feat(contracts): identity IDs, namespaced EntityRef, identity links (ADR-0008)"
```

---

### Task 6: kg_contracts.derivation — derivation lineage

**Files:**
- Create: `/Users/djjay0131/code/agentic-kgis/src/kg_contracts/derivation.py`
- Test: `/Users/djjay0131/code/agentic-kgis/tests/contracts/test_derivation.py`

**Interfaces:**
- Consumes: nothing new
- Produces (spec §5.5; frozen):
  - `DerivationInput(kind: str, ref: str)` — kind names what the ref points at (`"evidence"`, `"assertion"`, `"artifact"`, `"candidate"`); ref is the ID
  - `Derivation(method: str, deterministic: bool, inputs: tuple[DerivationInput, ...], implementation_version: str, parameters: dict[str, object] = {}, warnings: tuple[str, ...] = (), units: str | None = None, coordinate_system: str | None = None, reproducible: bool = True)` — **method determinism is not factual confidence** (a stud calculation can be perfectly deterministic while its wall-extraction inputs are uncertain); lineage is a directed graph reachable by following `inputs` refs; a content hash alone cannot capture this

- [ ] **Step 1: Write the failing tests**

`tests/contracts/test_derivation.py`:
```python
import pytest
from pydantic import ValidationError

from kg_contracts.derivation import Derivation, DerivationInput


def test_derivation_minimal():
    d = Derivation(
        method="stud-count-v3",
        deterministic=True,
        inputs=(DerivationInput(kind="assertion", ref="as_01H"),),
        implementation_version="kgis-takeoff==0.2.0",
    )
    assert d.deterministic and d.reproducible


def test_derivation_requires_method_and_version():
    with pytest.raises(ValidationError):
        Derivation(method="", deterministic=True, inputs=(),
                   implementation_version="v1")
    with pytest.raises(ValidationError):
        Derivation(method="m", deterministic=True, inputs=(),
                   implementation_version="")


def test_derivation_frozen_and_carries_warnings():
    d = Derivation(method="wall-length", deterministic=True,
                   inputs=(), implementation_version="v1",
                   warnings=("scale inferred from title block",), units="mm")
    assert d.warnings[0].startswith("scale")
    with pytest.raises(ValidationError):
        d.method = "other"  # type: ignore[misc]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/contracts/test_derivation.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `derivation.py`** — `method` and `implementation_version` use `Field(min_length=1)`. Docstring cites spec §5.5 and the DWG→cut-list example.

- [ ] **Step 4: Run tests to verify they pass** — Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/kg_contracts/derivation.py tests/contracts/test_derivation.py
git commit -m "feat(contracts): Derivation lineage (spec 5.5)"
```

---

### Task 7: kg_contracts.versioning — versions and compatibility classes

**Files:**
- Create: `/Users/djjay0131/code/agentic-kgis/src/kg_contracts/versioning.py`
- Test: `/Users/djjay0131/code/agentic-kgis/tests/contracts/test_versioning.py`

**Interfaces:**
- Consumes: nothing new
- Produces (spec §5.8; frozen):
  - `CONTRACT_VERSION: str = "2.0.0"` — stamped into every `CandidateEnvelope`
  - `VersionedComponentKind` StrEnum: `CANDIDATE_SCHEMA`, `ONTOLOGY_TYPE`, `RELATIONSHIP_DEFINITION`, `VALIDATION_RULES`, `EXTRACTOR`, `PROMPT`, `EMBEDDING_MODEL`, `RESOLUTION_FEATURES`, `GRAPH_PROJECTION`
  - `CompatibilityClass` StrEnum: `BACKWARD_COMPATIBLE`, `REQUIRES_CANDIDATE_REVALIDATION`, `REQUIRES_RE_EXTRACTION`, `REQUIRES_GRAPH_MIGRATION`, `REQUIRES_DERIVED_INDEX_REBUILD`
  - `VersionChange(component_kind, component_name: str, from_version: str | None, to_version: str, compatibility: CompatibilityClass)` — **every version change declares a compatibility class**; `from_version=None` means first introduction (must then be `BACKWARD_COMPATIBLE`)

- [ ] **Step 1: Write the failing tests**

`tests/contracts/test_versioning.py`:
```python
import pytest
from pydantic import ValidationError

from kg_contracts.versioning import (
    CONTRACT_VERSION,
    CompatibilityClass,
    VersionChange,
    VersionedComponentKind,
)


def test_contract_version_is_semver_2():
    assert CONTRACT_VERSION.startswith("2.")


def test_version_change_valid():
    vc = VersionChange(
        component_kind=VersionedComponentKind.EXTRACTOR,
        component_name="player-extractor",
        from_version="1.2.0",
        to_version="2.0.0",
        compatibility=CompatibilityClass.REQUIRES_RE_EXTRACTION,
    )
    assert vc.compatibility is CompatibilityClass.REQUIRES_RE_EXTRACTION


def test_introduction_must_be_backward_compatible():
    with pytest.raises(ValidationError, match="introduction"):
        VersionChange(
            component_kind=VersionedComponentKind.PROMPT,
            component_name="p", from_version=None, to_version="1.0.0",
            compatibility=CompatibilityClass.REQUIRES_GRAPH_MIGRATION,
        )


def test_all_compatibility_classes_present():
    assert {c.value for c in CompatibilityClass} == {
        "BACKWARD_COMPATIBLE", "REQUIRES_CANDIDATE_REVALIDATION",
        "REQUIRES_RE_EXTRACTION", "REQUIRES_GRAPH_MIGRATION",
        "REQUIRES_DERIVED_INDEX_REBUILD",
    }
```

- [ ] **Step 2: Run tests to verify they fail** — Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement `versioning.py`** per Interfaces (docstring cites spec §5.8).

- [ ] **Step 4: Run tests to verify they pass** — Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/kg_contracts/versioning.py tests/contracts/test_versioning.py
git commit -m "feat(contracts): version changes with mandatory compatibility classes (spec 5.8)"
```

---
