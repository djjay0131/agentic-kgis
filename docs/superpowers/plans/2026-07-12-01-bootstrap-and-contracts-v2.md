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

### Task 8: kg_contracts.candidates — CandidateScores + CandidateEnvelope

**A single `confidence` float is banned** (spec §5.2, disposition A2). The score set keeps orthogonal signals apart: an exact database import is not proof the database's fact is correct.

**Files:**
- Create: `/Users/djjay0131/code/agentic-kgis/src/kg_contracts/candidates.py`
- Test: `/Users/djjay0131/code/agentic-kgis/tests/contracts/test_candidate_envelope.py`

**Interfaces:**
- Consumes: `new_ulid`, `new_trace_id` (Task 3), `EvidenceRef` (Task 4), `CONTRACT_VERSION` (Task 7)
- Produces (all frozen, `extra="forbid"` — the forbid is load-bearing: it makes `confidence=` a hard error):
  - `CandidateScores(extraction_confidence: float, source_reliability: float, identity_confidence: float | None = None, assertion_confidence: float | None = None, corroboration_score: float | None = None, policy_risk: float = 0.0)` — all bounds `0.0..1.0`. `extraction_confidence` (did we read the source correctly?) and `source_reliability` (how trustworthy is this source historically?) are **required**: every producer must state both. The optional scores start unknown and are filled by curation (Plans 3/5). `policy_risk` is the consequence class of acting on the candidate
  - `SourceCoordinates(source_type: str, locator: str, fragment: str | None = None)` — stable locator into the source (row id, document URI, page/span); the primary idempotency anchor (spec §5.8)
  - `Representation(kind: Literal["text", "vector"], text: str | None = None, vector: tuple[float, ...] | None = None, model: str | None = None)` — exactly one of text/vector per kind
  - `CandidateEnvelope` — shared base class of all nine variants: `candidate_id: str` (default `"cand_" + ulid`), `graph_id: str`, `candidate_kind: str` (overridden per variant as a `Literal` discriminator), `producer: str`, `producer_run_id: str`, `contract_version: str = CONTRACT_VERSION`, `ontology_version: str`, `evidence_refs: tuple[EvidenceRef, ...] = ()`, `source_coordinates: SourceCoordinates`, `semantic_key: str` (min_length=1 — the idempotency key: stable semantic identity of the proposed fact, NOT a hash; spec §5.8), `content_hash: str | None = None` (supplementary signal only), `representations: dict[str, Representation] = {}` (**named** feature views — never a single generic embedding field), `scores: CandidateScores`, `trace_id: str` (default `new_trace_id()`), `created_at: datetime` (default now, UTC)

- [ ] **Step 1: Write the failing tests**

`tests/contracts/test_candidate_envelope.py`:
```python
import pytest
from pydantic import ValidationError

from kg_contracts.candidates import (
    CandidateEnvelope,
    CandidateScores,
    Representation,
    SourceCoordinates,
)
from kg_contracts.versioning import CONTRACT_VERSION

SCORES = CandidateScores(extraction_confidence=0.9, source_reliability=0.8)
COORDS = SourceCoordinates(source_type="postgres", locator="intersections/101")


def _envelope(**overrides: object) -> CandidateEnvelope:
    base: dict[str, object] = dict(
        graph_id="traffic",
        candidate_kind="entity",
        producer="structured-sync",
        producer_run_id="run-1",
        ontology_version="1",
        source_coordinates=COORDS,
        semantic_key="traffic/intersection/101",
        scores=SCORES,
    )
    base.update(overrides)
    return CandidateEnvelope(**base)  # type: ignore[arg-type]


def test_envelope_defaults():
    e = _envelope()
    assert e.candidate_id.startswith("cand_")
    assert e.trace_id.startswith("trace_")
    assert e.contract_version == CONTRACT_VERSION
    assert e.created_at.tzinfo is not None


def test_single_confidence_is_banned():
    with pytest.raises(ValidationError):
        _envelope(confidence=0.9)  # extra="forbid" makes this a hard error
    with pytest.raises(ValidationError):
        CandidateScores(confidence=0.9)  # type: ignore[call-arg]


def test_scores_require_extraction_and_source_reliability():
    with pytest.raises(ValidationError):
        CandidateScores(extraction_confidence=0.9)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        CandidateScores(extraction_confidence=1.2, source_reliability=0.5)


def test_optional_scores_start_unknown():
    assert SCORES.identity_confidence is None
    assert SCORES.assertion_confidence is None
    assert SCORES.policy_risk == 0.0


def test_semantic_key_required_nonempty():
    with pytest.raises(ValidationError):
        _envelope(semantic_key="")


def test_representations_are_named_views():
    e = _envelope(representations={
        "raw_statement": Representation(kind="text", text="Player X bats left"),
        "statement_embedding": Representation(
            kind="vector", vector=(0.1, 0.2), model="embed-v3"),
    })
    assert set(e.representations) == {"raw_statement", "statement_embedding"}


def test_representation_exactly_one_payload():
    with pytest.raises(ValidationError, match="vector"):
        Representation(kind="vector", text="oops")
```

- [ ] **Step 2: Run tests to verify they fail** — Expected: `ModuleNotFoundError: No module named 'kg_contracts.candidates'`

- [ ] **Step 3: Implement `candidates.py` (envelope portion)**

`model_config = ConfigDict(frozen=True, extra="forbid")` on every model in this module. `CandidateEnvelope.candidate_kind: str` here; variants (Tasks 9–10) narrow it to a `Literal`. `created_at` default factory `datetime.now(UTC)`. Module docstring: nine-variant union per spec §5.2/ADR-0004-as-amended; single confidence banned; envelope fields quoted from spec.

- [ ] **Step 4: Run tests to verify they pass** — Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/kg_contracts/candidates.py tests/contracts/test_candidate_envelope.py
git commit -m "feat(contracts): CandidateScores + CandidateEnvelope — single confidence banned (spec 5.2)"
```

---

### Task 9: Implemented candidate variants — entity, relation, attribute-assertion, artifact

These four get **full validation + tests** (disposition D2): they are what v1 pipelines (Plans 2–4) implement.

**Files:**
- Modify: `/Users/djjay0131/code/agentic-kgis/src/kg_contracts/candidates.py` (append)
- Test: `/Users/djjay0131/code/agentic-kgis/tests/contracts/test_candidate_variants.py`

**Interfaces:**
- Consumes: `CandidateEnvelope` (Task 8), `EntityRef`, `is_identity_id` (Task 5), `ValidPeriod` (Task 4), `Derivation` (Task 6)
- Produces (each subclasses `CandidateEnvelope`; shared alias type `SubjectRef = EntityRef | str` where a `str` must satisfy `is_identity_id` — enforced by one reusable validator):
  - `EntityCandidate(candidate_kind: Literal["entity"], entity_type: str, aliases: tuple[EntityRef, ...], display_name: str | None = None, properties: dict[str, object] = {})` — entity_type PascalCase; `aliases` non-empty; every alias's `entity_type` must equal the candidate's `entity_type` (a proposed identity is *made of* its namespaced aliases — there is no bare-ID fallback)
  - `RelationCandidate(candidate_kind: Literal["relation"], relation_type: str, subject: SubjectRef, object: SubjectRef, properties: dict[str, object] = {}, valid_period: ValidPeriod | None = None)` — relation_type UPPER_SNAKE `^[A-Z][A-Z0-9_]*$`
  - `AttributeAssertionCandidate(candidate_kind: Literal["attribute_assertion"], subject: SubjectRef, attribute: str, value: object, valid_period: ValidPeriod | None = None)` — attribute `min_length=1`; a proposed **fact about an entity**, bitemporal-ready via valid_period (transaction time is assigned by the ledger, Plan 2)
  - `ArtifactCandidate(candidate_kind: Literal["artifact"], artifact_type: str, artifact_hash: str, source_uri: str, media_type: str | None = None, derivation: Derivation | None = None)` — a produced object; **an artifact is not a fact about the world** (spec §5.2); artifact_hash and source_uri required non-empty

- [ ] **Step 1: Write the failing tests**

`tests/contracts/test_candidate_variants.py`:
```python
import pytest
from pydantic import ValidationError

from kg_contracts.candidates import (
    ArtifactCandidate,
    AttributeAssertionCandidate,
    CandidateScores,
    EntityCandidate,
    RelationCandidate,
    SourceCoordinates,
)
from kg_contracts.identity import EntityRef, new_identity_id

SCORES = CandidateScores(extraction_confidence=0.9, source_reliability=0.8)
COORDS = SourceCoordinates(source_type="document", locator="doc-1#p3")
ENV = dict(graph_id="baseball", producer="llm-extract", producer_run_id="r1",
           ontology_version="1", source_coordinates=COORDS, scores=SCORES)
PLAYER = EntityRef(entity_type="Player", namespace="usssa", key="12345")


def test_entity_candidate_valid():
    c = EntityCandidate(**ENV, semantic_key="baseball/player/usssa:12345",
                        entity_type="Player", aliases=(PLAYER,))
    assert c.candidate_kind == "entity"


def test_entity_candidate_requires_aliases():
    with pytest.raises(ValidationError, match="alias"):
        EntityCandidate(**ENV, semantic_key="k", entity_type="Player", aliases=())


def test_entity_candidate_alias_type_must_match():
    with pytest.raises(ValidationError, match="entity_type"):
        EntityCandidate(**ENV, semantic_key="k", entity_type="Coach",
                        aliases=(PLAYER,))


def test_relation_candidate_valid_with_ref_and_identity_subject():
    iid = new_identity_id("baseball")
    c = RelationCandidate(**ENV, semantic_key="k", relation_type="PLAYS_FOR",
                          subject=PLAYER, object=iid)
    assert c.candidate_kind == "relation"


def test_relation_candidate_rejects_bad_type_and_bad_subject():
    with pytest.raises(ValidationError, match="UPPER_SNAKE"):
        RelationCandidate(**ENV, semantic_key="k", relation_type="playsFor",
                          subject=PLAYER, object=PLAYER)
    with pytest.raises(ValidationError, match="identity"):
        RelationCandidate(**ENV, semantic_key="k", relation_type="PLAYS_FOR",
                          subject="Player:123", object=PLAYER)  # bare id string


def test_attribute_assertion_candidate():
    c = AttributeAssertionCandidate(**ENV, semantic_key="k", subject=PLAYER,
                                    attribute="batting_avg", value=0.312)
    assert c.candidate_kind == "attribute_assertion"
    with pytest.raises(ValidationError):
        AttributeAssertionCandidate(**ENV, semantic_key="k", subject=PLAYER,
                                    attribute="", value=1)


def test_artifact_candidate():
    c = ArtifactCandidate(**ENV, semantic_key="k", artifact_type="cut_list",
                          artifact_hash="sha256:abc", source_uri="s3://b/cuts.csv")
    assert c.candidate_kind == "artifact"
    with pytest.raises(ValidationError):
        ArtifactCandidate(**ENV, semantic_key="k", artifact_type="cut_list",
                          artifact_hash="", source_uri="s3://b/x")
```

- [ ] **Step 2: Run tests to verify they fail** — Expected: `ImportError: cannot import name 'EntityCandidate'`

- [ ] **Step 3: Append the four variants to `candidates.py`**

One shared `_validate_subject_ref(value: EntityRef | str) -> EntityRef | str` helper (raises naming the offending value if a `str` is not an identity ID — bare `Label:key` strings fail here with the ADR-0008 message). Each variant sets `candidate_kind` with a `Literal` type and default.

- [ ] **Step 4: Run all candidate tests** — Run: `.venv/bin/pytest tests/contracts/test_candidate_envelope.py tests/contracts/test_candidate_variants.py -v`. Expected: 14 passed

- [ ] **Step 5: Commit**

```bash
git add src/kg_contracts/candidates.py tests/contracts/test_candidate_variants.py
git commit -m "feat(contracts): implemented candidate variants — entity/relation/attribute-assertion/artifact (D2)"
```

---

### Task 10: Spec-level variants + the nine-way Candidate discriminated union

The remaining five variants are **defined** in v1 contracts (A2: no breaking union change later) but **spec-level**: indicative fields plus an open `payload`, placeholder validation only, and an explicit `SPEC-LEVEL` marker naming the phase that implements them (D2).

**Files:**
- Modify: `/Users/djjay0131/code/agentic-kgis/src/kg_contracts/candidates.py` (append)
- Test: `/Users/djjay0131/code/agentic-kgis/tests/contracts/test_candidate_union.py`

**Interfaces:**
- Consumes: Tasks 8–9 plus `IdentityLinkKind` (Task 5), `Derivation` (Task 6)
- Produces:
  - `ObservationCandidate(candidate_kind: Literal["observation"], metric: str, method: str | None = None, parameters: dict[str, object] = {}, value: object = None, payload: dict[str, object] = {})` — SPEC-LEVEL (implemented Phase 4, construction)
  - `DerivedAssertionCandidate(candidate_kind: Literal["derived_assertion"], derivation: Derivation, conclusion: dict[str, object] = {}, payload: dict[str, object] = {})` — SPEC-LEVEL (Phase 4); derivation is required even at spec level — a derived assertion without lineage is meaningless
  - `PlanCandidate(candidate_kind: Literal["plan"], objective: str, inputs: tuple[str, ...] = (), payload: dict[str, object] = {})` — SPEC-LEVEL (Phase 4); a generated cut list is not a fact about the building
  - `OntologyCandidate(candidate_kind: Literal["ontology"], term_kind: Literal["entity_type", "relation_type", "attribute"], term: str, definition: str | None = None, payload: dict[str, object] = {})` — SPEC-LEVEL (enters the §7.3 PROPOSED→APPROVED lifecycle; wired in Plan 3)
  - `IdentityLinkCandidate(candidate_kind: Literal["identity_link"], left: str, right: str, kind: IdentityLinkKind, payload: dict[str, object] = {})` — SPEC-LEVEL (Phase 3 retrofit); placeholder validation: left/right non-empty strings only (full endpoint validation lands with the implementation)
  - `Candidate` — `Annotated[EntityCandidate | RelationCandidate | AttributeAssertionCandidate | ObservationCandidate | DerivedAssertionCandidate | ArtifactCandidate | PlanCandidate | OntologyCandidate | IdentityLinkCandidate, Field(discriminator="candidate_kind")]`
  - `CANDIDATE_KINDS: frozenset[str]` — the nine kind strings
  - `candidate_adapter: TypeAdapter[Candidate]` — module-level, for deserializing ledger rows / wire payloads
  - `IMPLEMENTED_KINDS: frozenset[str] = {"entity", "relation", "attribute_assertion", "artifact"}` — what v1 pipelines accept; admission (KGCS) rejects spec-level kinds with "defined but not implemented in v1" rather than a validation error

- [ ] **Step 1: Write the failing tests**

`tests/contracts/test_candidate_union.py`:
```python
import pytest
from pydantic import ValidationError

from kg_contracts.candidates import (
    CANDIDATE_KINDS,
    IMPLEMENTED_KINDS,
    CandidateScores,
    ObservationCandidate,
    SourceCoordinates,
    candidate_adapter,
)

SCORES = CandidateScores(extraction_confidence=0.9, source_reliability=0.8)
COORDS = SourceCoordinates(source_type="sensor", locator="loop-7")
ENV = dict(graph_id="traffic", producer="p", producer_run_id="r1",
           ontology_version="1", source_coordinates=COORDS,
           semantic_key="k", scores=SCORES)


def test_all_nine_kinds_defined():
    assert CANDIDATE_KINDS == {
        "entity", "relation", "attribute_assertion", "observation",
        "derived_assertion", "artifact", "plan", "ontology", "identity_link",
    }
    assert IMPLEMENTED_KINDS == {"entity", "relation", "attribute_assertion",
                                 "artifact"}


def test_union_discriminates_on_candidate_kind():
    raw = dict(**ENV, candidate_kind="observation", metric="speed_avg")
    parsed = candidate_adapter.validate_python(raw)
    assert isinstance(parsed, ObservationCandidate)


def test_union_rejects_unknown_kind():
    with pytest.raises(ValidationError):
        candidate_adapter.validate_python(dict(**ENV, candidate_kind="vibe"))


def test_spec_level_variants_are_marked():
    from kg_contracts import candidates

    for cls_name in ("ObservationCandidate", "DerivedAssertionCandidate",
                     "PlanCandidate", "OntologyCandidate",
                     "IdentityLinkCandidate"):
        assert "SPEC-LEVEL" in getattr(candidates, cls_name).__doc__


def test_roundtrip_serialization():
    c = ObservationCandidate(**ENV, metric="speed_avg", value=42.1)
    again = candidate_adapter.validate_json(c.model_dump_json())
    assert again == c
```

- [ ] **Step 2: Run tests to verify they fail** — Expected: `ImportError: cannot import name 'CANDIDATE_KINDS'`

- [ ] **Step 3: Append spec-level variants, union, adapter, kind sets** per Interfaces. Each spec-level docstring starts `"""SPEC-LEVEL (implemented in <phase>): ..."""`.

- [ ] **Step 4: Run all candidate tests** — Run: `.venv/bin/pytest tests/contracts/ -k candidate -v`. Expected: 19 passed

- [ ] **Step 5: Commit**

```bash
git add src/kg_contracts/candidates.py tests/contracts/test_candidate_union.py
git commit -m "feat(contracts): nine-variant Candidate union; five spec-level variants (A2/D2)"
```

---

### Task 11: kg_contracts.assertions — bitemporal assertions, canonical entity, conflicts

**No PROVISIONAL status exists in this module** (ADR-0006): uncertainty lives in the candidate ledger as processing state (Task 14); the canonical graph holds only accepted identities and assertions.

**Files:**
- Create: `/Users/djjay0131/code/agentic-kgis/src/kg_contracts/assertions.py`
- Test: `/Users/djjay0131/code/agentic-kgis/tests/contracts/test_assertions.py`

**Interfaces:**
- Consumes: `new_ulid` (T3), `ValidPeriod`, `EvidenceRef`, `Provenance` (T4), `EntityRef`, `is_identity_id` (T5), `Derivation` (T6), `CandidateScores` (T8)
- Produces (spec §3.2, §5.4, §7.5; frozen):
  - `CurationStatus` StrEnum: `ACTIVE`, `SUPERSEDED`, `REVOKED` — exactly three; a test asserts `"PROVISIONAL" not in CurationStatus.__members__`
  - `CanonicalEntity(identity_id: str, entity_type: str, aliases: tuple[EntityRef, ...], status: CurationStatus = ACTIVE, display_name: str | None = None, created_at: datetime, curation_epoch: int)` — identity_id must satisfy `is_identity_id`; aliases non-empty, types matching; **curation status attaches at assertion level too** — an entity can be certain while one of its properties is uncertain
  - `Assertion(assertion_id: str = "as_" + ulid default, subject_identity: str, predicate: str, object_value: object | None, object_identity: str | None, status: CurationStatus, valid_period: ValidPeriod, recorded_at: datetime, superseded_at: datetime | None = None, scores: CandidateScores, evidence_refs: tuple[EvidenceRef, ...], authority: str, provenance: Provenance, derivation: Derivation | None = None, curation_epoch: int, trace_id: str)` — **bitemporal**: `valid_period` is domain valid time; `recorded_at`/`superseded_at` are transaction time. Exactly one of `object_value` / `object_identity` (relation-assertions point at identities). `authority` (who is entitled to assert this) is separate from every score (spec §7.5). Records are immutable — supersession writes a new record and sets `superseded_at` via a copy, performed by KGCS executors (Plan 3)
  - `ConflictStatus` StrEnum: `UNRESOLVED`, `RESOLVED`
  - `ConflictRecord(conflict_id: str = "cf_" + ulid default, assertion_ids: tuple[str, ...] (min 2), preferred_assertion_id: str | None, resolution_policy: str | None, status: ConflictStatus)` — competing assertions are preserved, not overwritten; `preferred_assertion_id`, when set, must be one of `assertion_ids` and forces status `RESOLVED`

- [ ] **Step 1: Write the failing tests**

`tests/contracts/test_assertions.py` (key cases — write all of these):
```python
# 1. CurationStatus has exactly ACTIVE/SUPERSEDED/REVOKED; PROVISIONAL absent (ADR-0006)
# 2. CanonicalEntity valid; rejects non-identity identity_id (match="identity");
#    rejects empty aliases; frozen
# 3. Assertion with object_value and open-ended valid_period validates;
#    recorded_at required; superseded_at None => current
# 4. Assertion requires exactly one of object_value/object_identity (match="exactly one");
#    object_identity must be an identity ID
# 5. Assertion carries CandidateScores and non-empty authority (empty authority rejected)
# 6. ConflictRecord requires >= 2 assertion_ids; preferred id must be a member;
#    setting preferred forces status RESOLVED (mismatch rejected, match="RESOLVED")
```

- [ ] **Step 2: Run tests to verify they fail** — Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement `assertions.py`** per Interfaces; module docstring cites ADR-0006 (three-store separation — this module models canonical-graph records only) and spec §5.4/§7.5.

- [ ] **Step 4: Run tests to verify they pass** — Expected: ~8 passed

- [ ] **Step 5: Commit**

```bash
git add src/kg_contracts/assertions.py tests/contracts/test_assertions.py
git commit -m "feat(contracts): bitemporal assertions, canonical entity, conflict records (ADR-0006)"
```

---

### Task 12: kg_contracts.policy — score-set-aware ConfidencePolicy

`ConfidencePolicy` remains a shared contract (not a KGCS internal), now evaluated over the `CandidateScores` set and consequence class rather than a single float (spec §5.10). It routes adjudication for entity promotion AND the registry's extend-vs-new decision. **Automating a decision later = policy config change, never code change.** Routes are `AUTO | LLM_ASSESS | HUMAN` — the v1 `CONSENSUS` (multi-agent debate) tier is demoted to an experimental kg_eval arm (disposition A6) and is NOT a route.

**Files:**
- Create: `/Users/djjay0131/code/agentic-kgis/src/kg_contracts/policy.py`
- Test: `/Users/djjay0131/code/agentic-kgis/tests/contracts/test_policy.py`

**Interfaces:**
- Consumes: `CandidateScores` (Task 8)
- Produces (frozen):
  - `AdjudicationRoute` StrEnum: `AUTO`, `LLM_ASSESS`, `HUMAN`
  - `ConfidencePolicy(policy_version: str = "1", auto_min_extraction: float = 0.95, auto_min_source_reliability: float = 0.90, auto_max_policy_risk: float = 0.20, assess_min_extraction: float = 0.80, require_identity_confidence_for_auto: bool = True, auto_min_identity_confidence: float = 0.95)` with `route(scores: CandidateScores) -> AdjudicationRoute`:
    1. `policy_risk > auto_max_policy_risk` → never AUTO (high-consequence candidates go to at least LLM_ASSESS; > 0.5 → HUMAN)
    2. AUTO requires extraction ≥ auto_min_extraction AND source_reliability ≥ auto_min_source_reliability AND (identity_confidence ≥ auto_min_identity_confidence when required — a **missing** identity_confidence is not silently treated as good: honest-null)
    3. else LLM_ASSESS if extraction ≥ assess_min_extraction
    4. else HUMAN
  - Threshold ordering validated: `auto_min_extraction >= assess_min_extraction`

- [ ] **Step 1: Write the failing tests**

`tests/contracts/test_policy.py`:
```python
import pytest
from pydantic import ValidationError

from kg_contracts.candidates import CandidateScores
from kg_contracts.policy import AdjudicationRoute, ConfidencePolicy


def scores(**kw: float) -> CandidateScores:
    base = dict(extraction_confidence=0.99, source_reliability=0.95,
                identity_confidence=0.99)
    base.update(kw)
    return CandidateScores(**base)  # type: ignore[arg-type]


def test_routes_are_auto_llm_assess_human_only():
    # CONSENSUS is gone: multi-agent debate is an experimental kg_eval arm (A6)
    assert {r.value for r in AdjudicationRoute} == {"AUTO", "LLM_ASSESS", "HUMAN"}


def test_high_everything_routes_auto():
    assert ConfidencePolicy().route(scores()) is AdjudicationRoute.AUTO


def test_exact_import_is_not_auto_without_source_reliability():
    # deterministic sync no longer enters ACTIVE automatically at "confidence 1.0"
    # (spec 5.5 / ADR-0004 as amended): the score set decides, not extraction alone
    s = scores(extraction_confidence=1.0, source_reliability=0.5)
    assert ConfidencePolicy().route(s) is AdjudicationRoute.LLM_ASSESS


def test_missing_identity_confidence_blocks_auto():
    s = CandidateScores(extraction_confidence=0.99, source_reliability=0.99)
    assert ConfidencePolicy().route(s) is AdjudicationRoute.LLM_ASSESS


def test_policy_risk_forces_human_review():
    assert ConfidencePolicy().route(scores(policy_risk=0.9)) \
        is AdjudicationRoute.HUMAN


def test_low_extraction_routes_human():
    s = scores(extraction_confidence=0.3)
    assert ConfidencePolicy().route(s) is AdjudicationRoute.HUMAN


def test_automation_is_config_not_code():
    # the learning-system endgame: loosen thresholds by config, no code change
    p = ConfidencePolicy(auto_min_extraction=0.5, assess_min_extraction=0.2,
                         auto_min_source_reliability=0.4,
                         require_identity_confidence_for_auto=False)
    s = CandidateScores(extraction_confidence=0.6, source_reliability=0.5)
    assert p.route(s) is AdjudicationRoute.AUTO


def test_threshold_ordering_enforced():
    with pytest.raises(ValidationError, match="ordered"):
        ConfidencePolicy(auto_min_extraction=0.5, assess_min_extraction=0.8)
```

- [ ] **Step 2: Run tests to verify they fail** — Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement `policy.py`** per Interfaces (route logic exactly as the numbered rules; docstring cites spec §5.10 and A6).

- [ ] **Step 4: Run tests to verify they pass** — Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/kg_contracts/policy.py tests/contracts/test_policy.py
git commit -m "feat(contracts): score-set-aware ConfidencePolicy, AUTO/LLM_ASSESS/HUMAN (spec 5.10)"
```

---

### Task 13: kg_contracts.stores — read side: GraphReadOptions, capabilities, readers

*Phase-0 lesson (vttsi-contracts):* one broad `GraphStore` protocol becomes either too weak or too demanding once multiple backends, temporal curation, and rollback share it — v2 splits reader/writer protocols and declares capabilities (spec §5.6–5.7). No Cypher/GQL on core contracts.

**Files:**
- Create: `/Users/djjay0131/code/agentic-kgis/src/kg_contracts/stores.py`
- Test: `/Users/djjay0131/code/agentic-kgis/tests/contracts/test_stores_read.py`

**Interfaces:**
- Consumes: `CanonicalEntity`, `Assertion` (Task 11), `EntityRef` (Task 5)
- Produces (spec §3.3, §5.6–5.7):
  - `AdapterCapabilities` (frozen; all default `False`): `supports_transactions`, `supports_temporal_queries`, `supports_vector_search`, `supports_full_text`, `supports_constraints`, `supports_bulk_upsert`, `supports_snapshot_reads`, `supports_graph_algorithms`
  - `UnsupportedCapabilityError(RuntimeError)` — raised when an option requires an undeclared capability (never silently ignored)
  - `GraphReadOptions` (frozen): `curation_epoch: int | None = None` (None = latest **published** epoch — readers consume a published epoch, never "whatever is present"), `valid_at: datetime | None = None`, `transaction_at: datetime | None = None`, `include_provisional: bool = False` (opt-in ledger visibility; default canonical-only), `include_superseded: bool = False`, `minimum_evidence_policy: str | None = None`
  - `CapabilityDeclaring` Protocol (runtime-checkable): `capabilities() -> AdapterCapabilities`
  - `GraphReader` Protocol (runtime-checkable): `current_epoch() -> int`; `get_entity(identity_id: str, options: GraphReadOptions = GraphReadOptions()) -> CanonicalEntity | None`; `find_entities(entity_type: str | None = None, alias: EntityRef | None = None, options: ... ) -> list[CanonicalEntity]`; `assertions_for(identity_id: str, options: ...) -> list[Assertion]`; `neighborhood(identity_id: str, hops: int = 1, options: ...) -> list[CanonicalEntity]`
  - `TemporalGraphReader(GraphReader)` Protocol — marker for adapters honoring `valid_at`/`transaction_at`; non-temporal adapters MUST raise `UnsupportedCapabilityError` when given temporal options (capability-declared, spec §5.4: memory store first, others as adopters need them)
  - `GraphWriter`, `TransactionalGraphWriter`, `BulkGraphWriter` Protocols — **adapter-internal** (docstring: used only by `GraphMutationStore` implementations, Plan 3; never application-facing): `put_entity(entity) -> None`, `put_assertion(assertion) -> None`, `mark_superseded(assertion_id, at) -> None`; transactional adds `begin() / commit() / rollback()`; bulk adds `put_entities(Sequence) -> int`

- [ ] **Step 1: Write the failing tests**

`tests/contracts/test_stores_read.py` (write all of these):
```python
# 1. GraphReadOptions defaults: canonical-only at latest published epoch
#    (curation_epoch None, include_provisional False, include_superseded False)
# 2. AdapterCapabilities defaults all False; frozen
# 3. A duck-typed fake with the five reader methods satisfies GraphReader
#    (runtime_checkable isinstance)
# 4. GraphReader exposes NO write surface: for name in ("upsert_nodes",
#    "upsert_edges", "put_entity", "apply", "submit"):
#        assert name not in dir-of-protocol-members  (ADR-0010: reads and
#    writes never share a surface)
# 5. UnsupportedCapabilityError is a RuntimeError subclass
```

- [ ] **Step 2: Run tests to verify they fail** — Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement the read side of `stores.py`** per Interfaces; module docstring cites ADR-0010 and spec §3.3/§5.6/§5.7.

- [ ] **Step 4: Run tests to verify they pass** — Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/kg_contracts/stores.py tests/contracts/test_stores_read.py
git commit -m "feat(contracts): split reader protocols, GraphReadOptions, capability declarations"
```

---

### Task 14: kg_contracts.curation — processing states, operations, decisions, CurationPlan, review

**Files:**
- Create: `/Users/djjay0131/code/agentic-kgis/src/kg_contracts/curation.py`
- Test: `/Users/djjay0131/code/agentic-kgis/tests/contracts/test_curation.py`

**Interfaces:**
- Consumes: `new_ulid` (T3), `AdjudicationRoute` (T12)
- Produces (spec §7.1–7.2, §7.6, §7.8; frozen and JSON-serializable — every object in the curation pipeline is auditable):
  - `ProcessingState` StrEnum (candidate lifecycle in the **ledger** — separate from entity/assertion `CurationStatus`, ADR-0006): `RECEIVED`, `VALIDATED`, `INVALID`, `BLOCKED`, `RESOLUTION_PENDING`, `REVIEW_PENDING`, `ACCEPTED`, `REJECTED`, `SUPERSEDED`, `RETRYABLE_ERROR`, `PERMANENT_ERROR`
  - `FailureKind` StrEnum: `BAD_DATA`, `UNSUPPORTED_ONTOLOGY`, `TRANSIENT_FAULT` — each gets different retry/alert behavior so transient faults never become permanent quarantines (fail-closed must not become fail-stopped, spec §7.2)
  - `CurationOperationType` StrEnum: `CREATE_IDENTITY`, `ATTACH_ASSERTION`, `MERGE_IDENTITIES`, `SPLIT_IDENTITY`, `REASSIGN_ASSERTION`, `RETRACT_ASSERTION`, `PROMOTE_ONTOLOGY_TERM`
  - `CurationOperation(operation_id: str = "op_" + ulid default, type: CurationOperationType, payload: dict[str, object], reversal_data: dict[str, object] = {})` — **every operation logs enough to reverse it** (pre-merge member set, lineage, affected projections); rollback is a compensating operation, not deletion of history
  - `Precondition(kind: str, subject: str, expected: str)` — optimistic concurrency: e.g. `kind="cluster_version", subject=<identity_id>, expected="17"`; resolution decides against an identity cluster at a known version, never one arbitrary node
  - `ValidationDecision(candidate_id: str, valid: bool, failure_kind: FailureKind | None, reasons: tuple[str, ...], policy_version: str, trace_id: str)` — `valid=False` requires `failure_kind`
  - `ResolutionDecision(candidate_id: str, resolved_identity: str | None, create_new_identity: bool, route: AdjudicationRoute, score_vector: dict[str, float], matcher_version: str | None, snapshot_version: str, trace_id: str)` — the **full score vector and model versions** are logged; a single stored final confidence cannot reproduce a decision (spec §7.4)
  - `CurationPlan(plan_id: str = "pl_" + ulid default, candidate_ids: tuple[str, ...] (min 1), snapshot_version: str, operations: tuple[CurationOperation, ...], preconditions: tuple[Precondition, ...], evidence_ids: tuple[str, ...], policy_version: str)` — spec §7.1 verbatim shape
  - `ReviewAction` StrEnum (spec §7.6, OpenRefine semantics — approve/reject alone is NOT enough): `APPROVE`, `REJECT`, `EDIT`, `SPLIT`, `RELABEL`, `LINK`, `MERGE_ELSEWHERE`, `SAME_CONCEPT_DIFFERENT_SCOPE`
  - `ReviewItem(item_id: str = "rv_" + ulid default, kind: str, payload: dict[str, object], priority: Literal["P1", "P2", "P3"] = "P3", reason: str, enqueued_at: datetime)` — P1=24h, P2=7d, P3=30d SLAs
  - `ReviewDecision(item_id: str, action: ReviewAction, actor: str, edited_payload: dict[str, object] | None = None, note: str | None = None, decided_at: datetime)` — `EDIT` requires `edited_payload`
  - `ReviewQueue` Protocol (runtime-checkable): `enqueue(item: ReviewItem) -> str`, `pending(limit: int = 50) -> list[ReviewItem]`, `resolve(decision: ReviewDecision) -> None`, `history(item_id: str) -> list[ReviewDecision]` (operation history is part of the contract — the future UI builds on it)
  - `AuditRecord(audit_id: str = "au_" + ulid default, operation_id: str, decided_by: str, score_vector: dict[str, float], evidence_ids: tuple[str, ...], policy_version: str, trace_id: str, recorded_at: datetime)` — immutable; the audit stream is the training corpus that later justifies raising auto-promotion thresholds (spec §7.8)

- [ ] **Step 1: Write the failing tests**

`tests/contracts/test_curation.py` (write all of these):
```python
# 1. ProcessingState has exactly the 11 spec states; disjoint from
#    CurationStatus values (no PROVISIONAL here either — it is a ledger state
#    machine, not a graph status)
# 2. ValidationDecision: valid=False without failure_kind rejected
#    (match="failure_kind"); valid=True with failure_kind rejected
# 3. ResolutionDecision requires a non-empty score_vector and snapshot_version
# 4. CurationPlan: requires >=1 candidate_id; full JSON round-trip —
#    CurationPlan.model_validate_json(plan.model_dump_json()) == plan
#    (serializability is the executor seam, ADR-0010)
# 5. CurationOperation carries reversal_data; frozen
# 6. ReviewAction has all 8 operations (assert exact value set)
# 7. ReviewDecision with action=EDIT and no edited_payload rejected
# 8. Duck-typed fake satisfies ReviewQueue (runtime_checkable), including
#    history()
```

- [ ] **Step 2: Run tests to verify they fail** — Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement `curation.py`** per Interfaces; docstring cites §7.1/§7.2/§7.6/§7.8 and ADR-0006/0010.

- [ ] **Step 4: Run tests to verify they pass** — Expected: ~9 passed

- [ ] **Step 5: Commit**

```bash
git add src/kg_contracts/curation.py tests/contracts/test_curation.py
git commit -m "feat(contracts): processing states, curation operations, CurationPlan, review operations"
```

---

### Task 15: kg_contracts.stores — write side: CandidateSink + GraphMutationStore

The two-level asymmetry is the point (ADR-0010): **applications get `CandidateSink` and nothing else**; `GraphMutationStore` exists only for KGCS executors. Exposing `upsert_nodes` to consumers (the vttsi-contracts shape) is superseded — convenient raw writes are how pipelines get bypassed.

**Files:**
- Modify: `/Users/djjay0131/code/agentic-kgis/src/kg_contracts/stores.py` (append)
- Test: `/Users/djjay0131/code/agentic-kgis/tests/contracts/test_stores_write.py`

**Interfaces:**
- Consumes: `Candidate` (T10), `CurationOperation`, `Precondition` (T14), `new_ulid` (T3)
- Produces (frozen):
  - `SubmissionStatus` StrEnum: `RECEIVED`, `DUPLICATE`, `INVALID` — synchronous admission outcome only (deterministic checks, spec §7.2); acceptance into the canonical graph is asynchronous and reported through processing states
  - `SubmissionOutcome(candidate_id: str, status: SubmissionStatus, reason: str | None = None, trace_id: str)`
  - `SubmissionResult(submission_id: str = "sub_" + ulid default, outcomes: tuple[SubmissionOutcome, ...])` with `counts() -> dict[SubmissionStatus, int]` helper
  - `CandidateSink` Protocol (runtime-checkable): `submit(candidates: Sequence[Candidate]) -> SubmissionResult` — **the only application-facing write surface**
  - `GraphMutationBatch(batch_id: str = "mb_" + ulid default, plan_id: str, operations: tuple[CurationOperation, ...] (min 1))` — compiled from a `CurationPlan`
  - `CommitResult(batch_id: str, committed: bool, new_epoch: int | None = None, failed_preconditions: tuple[Precondition, ...] = (), error: str | None = None)` — committed requires `new_epoch` (mutations commit as atomic curation epochs, spec §3.3); not-committed with failed preconditions = stale snapshot, re-evaluate (never retry blindly)
  - `GraphMutationStore` Protocol (runtime-checkable): `apply(batch: GraphMutationBatch, preconditions: Sequence[Precondition]) -> CommitResult` — docstring: **executor-only; applications must never hold this** (governance-delta principle 3)

- [ ] **Step 1: Write the failing tests**

`tests/contracts/test_stores_write.py` (write all of these):
```python
# 1. Duck-typed fakes satisfy CandidateSink and GraphMutationStore
# 2. CandidateSink protocol surface is submit() ONLY — assert no attribute
#    named upsert_nodes/upsert_edges/apply/put_entity is part of the protocol
# 3. SubmissionResult.counts() aggregates outcomes by status
# 4. CommitResult: committed=True without new_epoch rejected (match="epoch");
#    committed=False with failed_preconditions carries them
# 5. GraphMutationBatch requires >=1 operation; JSON round-trip equality
```

- [ ] **Step 2: Run tests to verify they fail** — Expected: `ImportError`

- [ ] **Step 3: Append the write side to `stores.py`** per Interfaces.

- [ ] **Step 4: Run tests to verify they pass** — Run: `.venv/bin/pytest tests/contracts/test_stores_write.py -v`. Expected: ~6 passed

- [ ] **Step 5: Commit**

```bash
git add src/kg_contracts/stores.py tests/contracts/test_stores_write.py
git commit -m "feat(contracts): CandidateSink + executor-only GraphMutationStore (ADR-0010)"
```

---

### Task 16: kg_contracts.ingestion — Source, Extractor, CompletionClient, IngestJob, IngestReport

**Files:**
- Create: `/Users/djjay0131/code/agentic-kgis/src/kg_contracts/ingestion.py`
- Test: `/Users/djjay0131/code/agentic-kgis/tests/contracts/test_ingestion.py`

**Interfaces:**
- Consumes: `Candidate` (T10), `Provenance` (T4), `SubmissionOutcome`, `SubmissionStatus` (T15)
- Produces (spec §5 module list, §6, §9):
  - `Source` Protocol (runtime-checkable): `fetch() -> Iterator[Candidate]` — structured mode. NOTE the v2 change: deterministic sources emit a **full score set** (`extraction_confidence` may be 1.0 while `source_reliability` is honest); there is no "confidence 1.0 ⇒ auto-ACTIVE" path anymore (ADR-0004 as amended)
  - `Extractor` Protocol (runtime-checkable): `name: str` property; `extract(text: str, provenance: Provenance) -> list[Candidate]` — one entity type per extractor is config, not code
  - `CompletionClient` Protocol (runtime-checkable): `complete(prompt: str, *, system: str | None = None) -> str` — the LLM provider injection point; KGIS mandates no provider
  - `IngestJob` Protocol — SPEC-LEVEL (spec §5 lists it; the pipeline's real shape — batching, registry consultation, resumability — is fixed in Plan 4): `job_id: str` property; `run() -> IngestReport`
  - `IngestReport(graph_id: str, received: int = 0, duplicates: int = 0, invalid: int = 0, incomplete: bool = False, failures: list[str] = [])` — **mutable accumulator by design** (NOT frozen): `record(outcome: SubmissionOutcome) -> None` increments by status; `fail(message: str) -> None` sets `incomplete=True` and appends. A failed extractor yields a partial report marked incomplete — **never a silent gap** (spec §9)

- [ ] **Step 1: Write the failing tests**

`tests/contracts/test_ingestion.py` (write all of these):
```python
# 1. Duck-typed fakes satisfy Source, Extractor, CompletionClient, IngestJob
# 2. IngestReport.record() tallies RECEIVED/DUPLICATE/INVALID outcomes
#    correctly (submit three mixed outcomes, assert the three counters)
# 3. IngestReport.fail("extractor player-extractor: timeout") sets
#    incomplete=True and captures the message
# 4. IngestJob is documented SPEC-LEVEL ("SPEC-LEVEL" in IngestJob.__doc__)
```

- [ ] **Step 2: Run tests to verify they fail** — Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement `ingestion.py`** per Interfaces.

- [ ] **Step 4: Run tests to verify they pass** — Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/kg_contracts/ingestion.py tests/contracts/test_ingestion.py
git commit -m "feat(contracts): Source/Extractor/CompletionClient/IngestJob + IngestReport"
```

---

### Task 17: kg_contracts.registry — GraphDescriptor, Recommendation, RegistryStore

**Files:**
- Create: `/Users/djjay0131/code/agentic-kgis/src/kg_contracts/registry.py`
- Test: `/Users/djjay0131/code/agentic-kgis/tests/contracts/test_registry.py`

**Interfaces:**
- Consumes: nothing new
- Produces (spec §8, ADR-0005 as amended, disposition D3; frozen):
  - `Backend` StrEnum: `SPANNER`, `NEO4J`, `MEMORY`
  - `GraphDescriptor(name, owner, domain, tags: tuple[str, ...] = (), backend: Backend, connection_ref: str | None = None, node_types: tuple[str, ...] = (), edge_types: tuple[str, ...] = (), ontology_version: str | None = None, policy_ref: str | None = None, created_by: str, decision_record: str | None = None)` — `connection_ref` is a secret NAME (e.g. a Secret Manager key), never a secret value
  - `Recommendation(action: Literal["extend", "create"], graph_name: str | None = None, factor_scores: dict[str, float] (values 0..1), checklist: tuple[str, ...], reasons: tuple[str, ...] (min 1))` — v1 scores five factors (identity value, ontology compatibility, tenancy, lifecycle, computational coupling); the remaining factors appear in `checklist` as a structured human checklist (D3 — the human is in the loop in v1 anyway). `extend` requires `graph_name`. No single overall score field: the advisor routes through `ConfidencePolicy` like everything else
  - `SCORED_FACTORS_V1: frozenset[str]` = the five factor names above; `factor_scores` keys must be a subset
  - `RegistryStore` Protocol (runtime-checkable): `register(descriptor: GraphDescriptor) -> None`, `get(name: str) -> GraphDescriptor | None`, `all() -> list[GraphDescriptor]`

- [ ] **Step 1: Write the failing tests**

`tests/contracts/test_registry.py` (write all of these):
```python
# 1. GraphDescriptor valid + frozen (mutation raises)
# 2. Recommendation extend without graph_name rejected (match="graph_name")
# 3. Recommendation with factor_scores key outside SCORED_FACTORS_V1
#    rejected (match="factor")
# 4. Recommendation carries checklist entries for unscored factors
# 5. Duck-typed fake satisfies RegistryStore
```

- [ ] **Step 2: Run tests to verify they fail** — Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement `registry.py`** per Interfaces (docstring: schema + protocol only; the SQLite implementation lives in `kgis`, the advisor in `kgcs` — Plan 7).

- [ ] **Step 4: Run tests to verify they pass** — Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/kg_contracts/registry.py tests/contracts/test_registry.py
git commit -m "feat(contracts): GraphDescriptor, five-factor Recommendation + checklist (D3), RegistryStore"
```

---

### Task 18: kg_contracts.testing — memory adapters + reusable contract test suites

*Phase-0 lesson (vttsi contract-test discipline):* every implementation of a port must pass the same reusable suite unchanged; the memory adapter exists so both repos (and every adopter) test with zero infrastructure. The memory store is the **first backend with full temporal-query support** (spec §10.2).

**Files:**
- Create: `/Users/djjay0131/code/agentic-kgis/src/kg_contracts/testing/__init__.py` (empty)
- Create: `/Users/djjay0131/code/agentic-kgis/src/kg_contracts/testing/memory.py`
- Create: `/Users/djjay0131/code/agentic-kgis/src/kg_contracts/testing/contract.py`
- Create: `/Users/djjay0131/code/agentic-kgis/src/kg_contracts/testing/factories.py`
- Test: `/Users/djjay0131/code/agentic-kgis/tests/contracts/test_memory_adapters.py`

**Interfaces:**
- Consumes: everything from Tasks 3–17
- Produces:
  - `factories.py` — test-data builders shared by the suites and downstream repos: `make_scores()`, `make_coords()`, `make_entity_candidate(graph_id=..., key=...)`, `make_attribute_candidate(...)`, `make_entity(...)`, `make_assertion(...)` (sensible valid defaults, keyword overrides)
  - `memory.MemoryCandidateSink` — implements `CandidateSink` + `CapabilityDeclaring`. Dict-backed ledger keyed by `(graph_id, semantic_key)`: first submit → `RECEIVED`, same semantic key again → `DUPLICATE` (idempotency by semantic key, NOT content hash — spec §5.8). Test helper: `received() -> list[Candidate]`
  - `memory.MemoryGraphStore` — implements `GraphReader` + `TemporalGraphReader` + `GraphMutationStore` + `CapabilityDeclaring` (declares `supports_temporal_queries=True`, `supports_snapshot_reads=True`). Behavior:
    - `apply()` supports `CREATE_IDENTITY` (payload: a `CanonicalEntity` dump) and `ATTACH_ASSERTION` (payload: an `Assertion` dump) in Plan 1; the other five operation types raise `NotImplementedError` with "Plan 3" in the message
    - preconditions of kind `entity_version` are checked against an internal per-identity version counter; any failed precondition → `CommitResult(committed=False, failed_preconditions=...)` and **nothing** is applied (atomicity)
    - each successful `apply()` advances the epoch by 1 and stamps applied records with it; `current_epoch()` returns the last **published** epoch
    - reads honor `GraphReadOptions`: default excludes superseded; `curation_epoch=N` hides records stamped with a later epoch (snapshot read); `valid_at`/`transaction_at` filter assertions bitemporally
  - `contract.MemoryReviewQueue` — list-backed `ReviewQueue` with `history()`
  - `contract.py` — reusable pytest-style suites (subclass, implement the `make_*` factory, get the tests free; spec §10.2 — every adapter, memory/Neo4j/Spanner, must pass unchanged):
    - `CandidateSinkContract` (`make_sink()`): submit → all `RECEIVED`; resubmit same semantic key → `DUPLICATE`; outcomes carry trace ids; `counts()` consistent
    - `GraphMutationStoreContract` (`make_store()`): create+attach commits and returns a new epoch; entity readable after commit, not before; failed `entity_version` precondition → `committed=False`, listed preconditions, store unchanged; superseded assertions hidden by default, visible with `include_superseded=True`; snapshot read at an old epoch hides later records; **capability conformance** — if `capabilities().supports_temporal_queries` is False, temporal options must raise `UnsupportedCapabilityError`; if True, `valid_at` filtering must work
    - `ReviewQueueContract` (`make_queue()`): enqueue/pending ordering; resolve removes from pending; `history()` returns decisions in order; EDIT decision round-trips `edited_payload`

- [ ] **Step 1: Write the failing test (suites applied to the memory adapters)**

`tests/contracts/test_memory_adapters.py`:
```python
from kg_contracts.stores import CandidateSink, GraphMutationStore
from kg_contracts.testing.contract import (
    CandidateSinkContract,
    GraphMutationStoreContract,
    MemoryReviewQueue,
    ReviewQueueContract,
)
from kg_contracts.testing.memory import MemoryCandidateSink, MemoryGraphStore


class TestMemoryCandidateSink(CandidateSinkContract):
    def make_sink(self) -> CandidateSink:
        return MemoryCandidateSink()


class TestMemoryGraphStore(GraphMutationStoreContract):
    def make_store(self) -> GraphMutationStore:
        return MemoryGraphStore()


class TestMemoryReviewQueue(ReviewQueueContract):
    def make_queue(self) -> MemoryReviewQueue:
        return MemoryReviewQueue()
```

- [ ] **Step 2: Run tests to verify they fail** — Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement `factories.py`, then `memory.py`, then `contract.py`** in that order (factories → adapters → suites), re-running the suite as behaviors land. Adapters are pure dicts/lists — no I/O (Global Constraints).

- [ ] **Step 4: Run tests to verify they pass** — Run: `.venv/bin/pytest tests/contracts/test_memory_adapters.py -v`. Expected: all contract tests pass (~14, exact count set by the suites)

- [ ] **Step 5: Commit**

```bash
git add src/kg_contracts/testing tests/contracts/test_memory_adapters.py
git commit -m "feat(contracts): memory adapters + reusable contract suites (spec 10.2)"
```

---

### Task 19: Public API, quality gate, CI, cross-repo verification, memory bank

**Files:**
- Modify: `/Users/djjay0131/code/agentic-kgis/src/kg_contracts/__init__.py`
- Create: `/Users/djjay0131/code/agentic-kgis/.github/workflows/ci.yml`
- Create: `/Users/djjay0131/code/agentic-kgcs/.github/workflows/ci.yml`
- Modify: `/Users/djjay0131/code/agentic-kgis/llm/memory_bank/{activeContext,progress}.md`
- Modify: `/Users/djjay0131/code/agentic-kgcs/llm/memory_bank/{activeContext,progress}.md`
- Test: `/Users/djjay0131/code/agentic-kgis/tests/contracts/test_public_api.py`, `/Users/djjay0131/code/agentic-kgcs/tests/test_contracts_available.py`

**Interfaces:**
- Consumes: everything from Tasks 3–18
- Produces: stable import surface `from kg_contracts import Candidate, CandidateSink, EntityRef, ...`; green ruff/mypy/pytest in both repos; CI workflows; memory banks synced

- [ ] **Step 1: Write the failing test**

`tests/contracts/test_public_api.py` — one import of the full public surface:
```python
def test_top_level_exports() -> None:
    from kg_contracts import (  # noqa: F401
        # security (T3)
        DeletionBehavior, PolicyContext, new_trace_id,
        # evidence (T4)
        AbsenceReason, Evidence, EvidenceAvailability, EvidenceRef,
        EvidenceRelationship, Provenance, ValidPeriod,
        # identity (T5)
        EntityRef, IdentityError, IdentityLink, IdentityLinkKind,
        is_identity_id, new_identity_id, parse_identity_id,
        # derivation (T6)
        Derivation, DerivationInput,
        # versioning (T7)
        CONTRACT_VERSION, CompatibilityClass, VersionChange,
        VersionedComponentKind,
        # candidates (T8-T10)
        CANDIDATE_KINDS, IMPLEMENTED_KINDS, ArtifactCandidate,
        AttributeAssertionCandidate, Candidate, CandidateEnvelope,
        CandidateScores, DerivedAssertionCandidate, EntityCandidate,
        IdentityLinkCandidate, ObservationCandidate, OntologyCandidate,
        PlanCandidate, RelationCandidate, Representation, SourceCoordinates,
        candidate_adapter,
        # assertions (T11)
        Assertion, CanonicalEntity, ConflictRecord, ConflictStatus,
        CurationStatus,
        # policy (T12)
        AdjudicationRoute, ConfidencePolicy,
        # stores (T13, T15)
        AdapterCapabilities, CandidateSink, CommitResult, GraphMutationBatch,
        GraphMutationStore, GraphReader, GraphReadOptions, SubmissionOutcome,
        SubmissionResult, SubmissionStatus, TemporalGraphReader,
        UnsupportedCapabilityError,
        # curation (T14)
        AuditRecord, CurationOperation, CurationOperationType, CurationPlan,
        FailureKind, Precondition, ProcessingState, ResolutionDecision,
        ReviewAction, ReviewDecision, ReviewItem, ReviewQueue,
        ValidationDecision,
        # ingestion (T16)
        CompletionClient, Extractor, IngestJob, IngestReport, Source,
        # registry (T17)
        Backend, GraphDescriptor, Recommendation, RegistryStore,
        SCORED_FACTORS_V1,
    )
```
(Adapter-internal writer protocols — `GraphWriter` and friends — are deliberately NOT re-exported at top level; they stay importable from `kg_contracts.stores` with their internal-use docstrings.)

- [ ] **Step 2: Run test to verify it fails** — Expected: `ImportError` (empty `__init__.py`)

- [ ] **Step 3: Write the exports** — populate `src/kg_contracts/__init__.py` with the imports above plus `__all__`; module docstring names the spec and CONTRACT_VERSION.

- [ ] **Step 4: Run the full quality gate**

```bash
cd /Users/djjay0131/code/agentic-kgis
.venv/bin/pytest -v
.venv/bin/ruff check src tests
.venv/bin/mypy src
```
Expected: all tests pass (≈95), ruff clean, mypy --strict clean on `src`. Fix findings before proceeding.

- [ ] **Step 5: Add CI workflows**

`agentic-kgis/.github/workflows/ci.yml`:
```yaml
name: ci
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e '.[dev]'
      - run: ruff check src tests
      - run: mypy src
      - run: pytest -v
```

`agentic-kgcs/.github/workflows/ci.yml` (installs the sibling from GitHub; requires `CONSTELLATION_PAT` secret — vttsi pattern, spec §10.2):
```yaml
name: ci
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install "git+https://x-access-token:${{ secrets.CONSTELLATION_PAT }}@github.com/djjay0131/agentic-kgis.git"
      - run: pip install -e '.[dev]'
      - run: ruff check src tests
      - run: pytest -v
```

- [ ] **Step 6: Cross-repo verification test in agentic-kgcs**

`agentic-kgcs/tests/test_contracts_available.py`:
```python
from kg_contracts import AdjudicationRoute, CandidateScores, ConfidencePolicy
from kg_contracts.stores import CandidateSink, GraphMutationStore
from kg_contracts.testing.contract import (
    CandidateSinkContract,
    GraphMutationStoreContract,
)
from kg_contracts.testing.memory import MemoryCandidateSink, MemoryGraphStore


class TestSinkUsableFromKgcs(CandidateSinkContract):
    def make_sink(self) -> CandidateSink:
        return MemoryCandidateSink()


class TestStoreUsableFromKgcs(GraphMutationStoreContract):
    def make_store(self) -> GraphMutationStore:
        return MemoryGraphStore()


def test_policy_available() -> None:
    scores = CandidateScores(extraction_confidence=0.99,
                             source_reliability=0.99,
                             identity_confidence=0.99)
    assert ConfidencePolicy().route(scores) is AdjudicationRoute.AUTO
```

```bash
cd /Users/djjay0131/code/agentic-kgcs
.venv/bin/pip install -e ../agentic-kgis   # refresh editable install
.venv/bin/pytest -v
```
Expected: packaging test + both contract suites + policy test all pass.

- [ ] **Step 7: Update memory banks and commit both repos**

`agentic-kgis/llm/memory_bank/activeContext.md`: current work = Plan 1 v2 complete; next = Plan 2 (candidate ledger + evidence registry). `progress.md`: add dated entry — kg_contracts v2 complete (identity, evidence, nine-variant candidates with four implemented, bitemporal assertions, derivation, policy, two-level stores, curation contracts, registry, memory adapters + contract suites, CI). `agentic-kgcs` memory bank: bootstrapped with packaging + cross-repo contract verification; implementation starts Plan 3 (curation core + executor).

```bash
cd /Users/djjay0131/code/agentic-kgis
git add src/kg_contracts/__init__.py tests .github llm pyproject.toml
git commit -m "feat(contracts): public API v2, quality gate, CI"

cd /Users/djjay0131/code/agentic-kgcs
git add tests .github llm
git commit -m "test: verify kg_contracts v2 consumable from kgcs; add CI"
```

---

## Plan 1 v2 Definition of Done

- Both repos install editable and run their full test suites green; `agentic-kgis` ships importable `kg_contracts`, `kgis`, `kg_eval` (ADR-0002 as amended)
- `agentic-kgis`: `pytest`, `ruff check`, `mypy src` (strict) all green; `kg_contracts` public API exports everything in Task 19's test
- All nine candidate variants are defined and union-dispatchable; exactly `{entity, relation, attribute_assertion, artifact}` are fully validated; the other five carry `SPEC-LEVEL` docstrings (A2/D2)
- No contract anywhere carries a single `confidence` float; no consumer-facing protocol exposes raw graph writes; no `PROVISIONAL` value exists in `CurationStatus` (ADR-0006/0010 verified by tests)
- Bare `Label:key` parsing fails loudly with the ADR-0008 deprecation message
- `agentic-kgcs`: imports `kg_contracts`, runs the `CandidateSinkContract` and `GraphMutationStoreContract` suites green against the memory adapters
- Memory banks in both repos reflect Plan 1 v2 completion; Plan 2 (candidate ledger + evidence registry) can begin with no further scaffolding
