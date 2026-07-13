# KGIS/KGCS Plan 1: Repo Bootstrap + kg_contracts Implementation Plan

> ## ⛔ OBSOLETE — DO NOT EXECUTE
>
> This plan was written against **spec v1** and is superseded by
> **[Plan 1 v2: Bootstrap Completion + kg_contracts v2](2026-07-12-01-bootstrap-and-contracts-v2.md)**
> (`docs/superpowers/plans/2026-07-12-01-bootstrap-and-contracts-v2.md`).
>
> The approved disposition of external review PR #1
> (`docs/ai/chatgpt-feedback-disposition.md`, Consequences §5) obsoleted this
> plan before execution: the contracts changed substantially (nine-variant
> candidate union, `CandidateScores` replacing single confidence, namespaced
> identity per ADR-0008, first-class evidence, bitemporal assertions,
> two-level store contracts per ADR-0010, no PROVISIONAL nodes per ADR-0006,
> three packages per ADR-0002 as amended). No task below was executed.
> This file is retained for provenance only.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Initialize both repos with memory banks and deliver a complete, tested `kg_contracts` package — schemas, canonical IDs, the `GraphStore` protocol, curation/ingestion/registry contracts, an in-memory reference store, and a reusable contract test suite.

**Architecture:** `agentic-kgis` ships two packages from one distribution: `kg_contracts` (pure ports layer — Pydantic models and `typing.Protocol` interfaces, no engine/LLM/network code) and `kgis` (ingestion implementations, later plans). `agentic-kgcs` depends only on `kg_contracts`. The in-memory `GraphStore` and the contract test suite live under `kg_contracts.testing` so both repos test against them without extra dependencies.

**Tech Stack:** Python ≥3.11, Pydantic v2, pytest, ruff, mypy, hatchling build backend.

**Spec:** `docs/superpowers/specs/2026-07-09-kgis-kgcs-design.md` (sections 4, 5, and the contract-suite part of 10).

**Plan sequence** (this is Plan 1 of 5; later plans are written after their predecessors complete):
1. **This plan** — bootstrap + `kg_contracts`
2. KGCS inline gate (`CuratedGraphStore`: canonical repair-or-reject, ontology, versioning, quarantine)
3. KGIS ingestion (sources, extractors, pipeline, `IngestReport`, CLI)
4. KGCS async plane (resolver, promoter, review queue CLI, audit)
5. Registry store + extend-vs-new advisor

## Global Constraints

- Python `>=3.11`; sole runtime dependency of `kg_contracts` is `pydantic>=2.0`
- `kg_contracts` contains NO engine code, NO LLM code, NO network/file I/O (spec §5.5); the in-memory store under `kg_contracts.testing` is allowed (pure dicts)
- Canonical node id format: `Label:key` — PascalCase label matching `^[A-Z][A-Za-z0-9]*$`, non-empty key (spec §5, ts-kg lineage)
- Edge type format: UPPER_SNAKE matching `^[A-Z][A-Z0-9_]*$`
- Curation statuses exactly: `PROVISIONAL`, `ACTIVE`, `SUPERSEDED`, `REVOKED` (spec §5.3)
- Confidence routes exactly: `AUTO`, `LLM_EVALUATE`, `CONSENSUS`, `HUMAN` (spec §5.4)
- All contract models are frozen (immutable) Pydantic models
- TDD for every behavior-bearing module; run commands from the repo root; venv at `.venv`
- Commit after every task (frequent commits)

---

### Task 1: Scaffold agentic-kgis package

**Files:**
- Create: `/Users/djjay0131/code/agentic-kgis/pyproject.toml`
- Create: `/Users/djjay0131/code/agentic-kgis/.gitignore`
- Create: `/Users/djjay0131/code/agentic-kgis/README.md`
- Create: `/Users/djjay0131/code/agentic-kgis/src/kg_contracts/__init__.py`
- Create: `/Users/djjay0131/code/agentic-kgis/src/kgis/__init__.py`
- Test: `/Users/djjay0131/code/agentic-kgis/tests/test_packaging.py`

**Interfaces:**
- Consumes: nothing (repo already `git init`-ed with the spec committed)
- Produces: installable editable package exposing importable `kg_contracts` and `kgis`; `.venv/bin/pytest` runs

- [ ] **Step 1: Write the failing test**

`tests/test_packaging.py`:
```python
def test_packages_import():
    import kg_contracts
    import kgis

    assert kg_contracts.__name__ == "kg_contracts"
    assert kgis.__name__ == "kgis"
```

- [ ] **Step 2: Create pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "agentic-kgis"
version = "0.1.0"
description = "Knowledge Graph Ingestion Service + kg_contracts ports layer"
requires-python = ">=3.11"
dependencies = ["pydantic>=2.0"]

[project.optional-dependencies]
dev = ["pytest>=8.0", "ruff>=0.4", "mypy>=1.10"]

[tool.hatch.build.targets.wheel]
packages = ["src/kg_contracts", "src/kgis"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
src = ["src", "tests"]

[tool.mypy]
python_version = "3.11"
strict = true
mypy_path = "src"
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

Knowledge Graph Ingestion Service. Ships two packages:

- **kg_contracts** — domain-neutral ports layer (schemas, GraphStore protocol,
  ingestion/curation/registry contracts, contract test suite). No engine, LLM,
  or I/O code.
- **kgis** — ingestion implementations (structured sync + LLM extraction).

Design: `docs/superpowers/specs/2026-07-09-kgis-kgcs-design.md`
Companion repo: `agentic-kgcs` (curation service; depends on kg_contracts).

## Dev setup

    python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
    .venv/bin/pytest
```

`src/kg_contracts/__init__.py` and `src/kgis/__init__.py`: empty files.

- [ ] **Step 4: Install and run test to verify it passes**

Run:
```bash
cd /Users/djjay0131/code/agentic-kgis
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -v
```
Expected: `test_packages_import PASSED` (1 passed)

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .gitignore README.md src tests
git commit -m "chore: scaffold agentic-kgis with kg_contracts and kgis packages"
```

---

### Task 2: Bootstrap agentic-kgcs repo

**Files:**
- Create: `/Users/djjay0131/code/agentic-kgcs/pyproject.toml`
- Create: `/Users/djjay0131/code/agentic-kgcs/.gitignore` (same content as Task 1)
- Create: `/Users/djjay0131/code/agentic-kgcs/README.md`
- Create: `/Users/djjay0131/code/agentic-kgcs/src/kgcs/__init__.py`
- Test: `/Users/djjay0131/code/agentic-kgcs/tests/test_packaging.py`

**Interfaces:**
- Consumes: editable install of `agentic-kgis` from the sibling directory
- Produces: installable `kgcs` package that can `import kg_contracts`

- [ ] **Step 1: git init**

Run: `git init /Users/djjay0131/code/agentic-kgcs`
Expected: `Initialized empty Git repository`

- [ ] **Step 2: Write the failing test**

`tests/test_packaging.py`:
```python
def test_kgcs_imports_and_sees_contracts():
    import kg_contracts
    import kgcs

    assert kgcs.__name__ == "kgcs"
    assert kg_contracts.__name__ == "kg_contracts"
```

- [ ] **Step 3: Create scaffolding**

`pyproject.toml`:
```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "agentic-kgcs"
version = "0.1.0"
description = "Knowledge Graph Curation Service (gate + async curation plane)"
requires-python = ">=3.11"
dependencies = ["agentic-kgis>=0.1.0"]

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
```

`README.md`:
```markdown
# agentic-kgcs

Knowledge Graph Curation Service. Ships `kgcs`:

- **gate/** — inline CuratedGraphStore: canonical-ID repair-or-reject,
  data-backed ontology validation, versioned/provenance-stamped writes.
- **plane/** — async curation: entity resolution, confidence-routed
  promotion, merges.
- **review/** — persistent human review queue + CLI.

Depends only on `kg_contracts` (shipped by sibling repo `agentic-kgis`).
Design: `agentic-kgis/docs/superpowers/specs/2026-07-09-kgis-kgcs-design.md`

## Dev setup

    python3 -m venv .venv
    .venv/bin/pip install -e ../agentic-kgis -e '.[dev]'
    .venv/bin/pytest
```

`.gitignore`: same content as Task 1. `src/kgcs/__init__.py`: empty file.

- [ ] **Step 4: Install and run test to verify it passes**

Run:
```bash
cd /Users/djjay0131/code/agentic-kgcs
python3 -m venv .venv
.venv/bin/pip install -e ../agentic-kgis -e '.[dev]'
.venv/bin/pytest -v
```
Expected: `test_kgcs_imports_and_sees_contracts PASSED` (1 passed)

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .gitignore README.md src tests
git commit -m "chore: bootstrap agentic-kgcs depending on kg_contracts"
```

---

### Task 3: Establish memory banks in both repos

**Files:**
- Create: `/Users/djjay0131/code/agentic-kgis/llm/memory_bank/{projectbrief,productContext,systemPatterns,techContext,activeContext,progress}.md`
- Create: `/Users/djjay0131/code/agentic-kgcs/llm/memory_bank/{projectbrief,productContext,systemPatterns,techContext,activeContext,progress}.md`

**Interfaces:**
- Consumes: spec content (for accurate summaries)
- Produces: Constellize-convention memory banks at `llm/memory_bank/` (matching agentic-kg's current layout), committed in each repo

- [ ] **Step 1: Write agentic-kgis memory bank files**

`llm/memory_bank/projectbrief.md`:
```markdown
# Project Brief — agentic-kgis

KGIS (Knowledge Graph Ingestion Service) is a reusable Python library that
ingests data into knowledge graphs for every project in this portfolio.
It ships two packages: `kg_contracts` (domain-neutral ports: schemas,
GraphStore protocol, ingestion/curation/registry contracts) and `kgis`
(ingestion implementations: deterministic structured sync + LLM extraction).

Non-negotiables: KGIS never writes to a raw GraphStore — always through
KGCS's CuratedGraphStore. Candidates (not writes) are the output of
ingestion. Contracts contain no engine, LLM, or I/O code.

Authority: docs/superpowers/specs/2026-07-09-kgis-kgcs-design.md
```

`llm/memory_bank/productContext.md`:
```markdown
# Product Context — agentic-kgis

Every project here (agentic-kg, ts-kg/vttsi, construction-ai, baseball-ai)
builds a knowledge graph and each reinvented ingestion. KGIS consolidates
the two proven modes: idempotent structured sync (ts-kg sync.py lineage)
and parallel LLM extraction (agentic-kg ingest_papers lineage).

Consumers: baseball-ai first (greenfield), then agentic-kg (acid-test
retrofit), then ts-kg / construction-ai. Consumption model: contract +
library (vttsi-contracts pattern) — no deployed service in v1.
```

`llm/memory_bank/systemPatterns.md`:
```markdown
# System Patterns — agentic-kgis

- Ports and adapters: kg_contracts defines Protocols; engines/LLMs injected.
- Candidate as universal seam: both ingestion modes emit Candidate
  (proposal + confidence + Provenance); KGCS gate does all graph writes.
- Canonical IDs: `Label:key`, PascalCase label — validated at GraphNode
  construction (type-level unbypassable).
- Layered write path (spec §3, approach C): deterministic gates inline,
  probabilistic curation async over PROVISIONAL nodes.
- Idempotency: content hash on every Candidate; re-ingest is a no-op.
- Contract test suite in kg_contracts.testing; every GraphStore
  implementation must pass it.
```

`llm/memory_bank/techContext.md`:
```markdown
# Tech Context — agentic-kgis

Python >=3.11, Pydantic v2 (only runtime dep of kg_contracts), pytest,
ruff, mypy --strict, hatchling. src/ layout; venv at .venv.

Two packages, one distribution "agentic-kgis": src/kg_contracts, src/kgis.
Sibling repo agentic-kgcs depends on this distribution.
Graph backends (injected, not dependencies here): Spanner Graph (ADR-012),
Neo4j, in-memory reference store (kg_contracts.testing.memory_store).
```

`llm/memory_bank/activeContext.md`:
```markdown
# Active Context — agentic-kgis

Current work: Plan 1 (bootstrap + kg_contracts) —
docs/superpowers/plans/2026-07-09-01-bootstrap-and-contracts.md.
Next plans: 2 KGCS gate, 3 KGIS ingestion, 4 KGCS async plane,
5 registry + advisor.

Open questions: none blocking; extractor config format decided in Plan 3.
```

`llm/memory_bank/progress.md`:
```markdown
# Progress — agentic-kgis

- 2026-07-09: Design spec approved and committed (root commit).
- 2026-07-09: Plan 1 written. Status: executing Plan 1.

Works: (fill as tasks complete)
Not built yet: kgis package internals (Plan 3), all of KGCS (Plans 2/4/5).
```

- [ ] **Step 2: Write agentic-kgcs memory bank files**

`llm/memory_bank/projectbrief.md`:
```markdown
# Project Brief — agentic-kgcs

KGCS (Knowledge Graph Curation Service) is a reusable Python library that
guards and improves knowledge-graph content for every project in this
portfolio. Two halves: an inline synchronous gate (CuratedGraphStore:
canonical-ID repair-or-reject, data-backed ontology, versioned writes)
and an async curation plane (embedding entity resolution, confidence-routed
promotion PROVISIONAL→ACTIVE, human review queue, immutable audit).

Depends only on kg_contracts (from sibling repo agentic-kgis).
Authority: agentic-kgis/docs/superpowers/specs/2026-07-09-kgis-kgcs-design.md
```

`llm/memory_bank/productContext.md`:
```markdown
# Product Context — agentic-kgcs

Consolidates curation proven elsewhere: ts-kg canonical.py + ontology.py
(repair-or-reject, no phantom node types — lesson of agentic-tskg's 0/18
ingestion failure), agentic-kg's dedup/confidence-routing/review-queue,
construction-ai's SUPERSEDED_BY versioning + rollback.

The confidence-routing seam (auto / LLM evaluate / consensus / human) is
how human gates become automation later: config change, not code change.
Same pattern governs the graph-level extend-vs-new advisor (Plan 5).
```

`llm/memory_bank/systemPatterns.md`:
```markdown
# System Patterns — agentic-kgcs

- CuratedGraphStore wraps any GraphStore; gate order: canonical ID →
  ontology (active types only) → versioned write.
- Rejections are data (quarantine + reason), exceptions are bugs;
  fail closed if ontology/registry unavailable.
- Lifecycle: PROVISIONAL → ACTIVE → SUPERSEDED/REVOKED; confidence-1.0
  structured syncs enter ACTIVE directly.
- Every merge reversible via version chains; every curation action gets
  an immutable audit record.
```

`llm/memory_bank/techContext.md`:
```markdown
# Tech Context — agentic-kgcs

Python >=3.11, depends on agentic-kgis distribution (kg_contracts).
pytest, ruff, mypy --strict, hatchling, src/ layout, venv at .venv.
Dev install: .venv/bin/pip install -e ../agentic-kgis -e '.[dev]'
Tests run against kg_contracts.testing.memory_store.MemoryGraphStore —
no graph infrastructure needed.
```

`llm/memory_bank/activeContext.md`:
```markdown
# Active Context — agentic-kgcs

Current work: bootstrapped as part of Plan 1 (see agentic-kgis
docs/superpowers/plans/2026-07-09-01-bootstrap-and-contracts.md).
KGCS implementation starts in Plan 2 (inline gate), then Plan 4
(async plane + review), Plan 5 (registry advisor).
```

`llm/memory_bank/progress.md`:
```markdown
# Progress — agentic-kgcs

- 2026-07-09: Repo bootstrapped (Plan 1, Task 2). Package skeleton only.

Works: packaging + import of kg_contracts.
Not built yet: gate/, plane/, review/, policy.py, audit.py.
```

- [ ] **Step 3: Commit both repos**

```bash
cd /Users/djjay0131/code/agentic-kgis && git add llm && git commit -m "docs: establish memory bank"
cd /Users/djjay0131/code/agentic-kgcs && git add llm && git commit -m "docs: establish memory bank"
```

---

### Task 4: kg_contracts.ids — canonical Label:key helpers

**Files:**
- Create: `/Users/djjay0131/code/agentic-kgis/src/kg_contracts/ids.py`
- Test: `/Users/djjay0131/code/agentic-kgis/tests/contracts/test_ids.py`

**Interfaces:**
- Consumes: nothing
- Produces: `canonical_id(label: str, key: str) -> str`, `is_canonical(node_id: str) -> bool`, `parse_canonical(node_id: str) -> tuple[str, str]`, `CanonicalIdError(ValueError)` — used by `schemas.py` (Task 5) and by KGCS gate repair (Plan 2)

- [ ] **Step 1: Write the failing tests**

`tests/contracts/test_ids.py`:
```python
import pytest

from kg_contracts.ids import CanonicalIdError, canonical_id, is_canonical, parse_canonical


def test_canonical_id_builds_label_colon_key():
    assert canonical_id("Intersection", "101") == "Intersection:101"


def test_canonical_id_strips_key_whitespace():
    assert canonical_id("Player", " p42 ") == "Player:p42"


def test_canonical_id_rejects_non_pascal_label():
    with pytest.raises(CanonicalIdError):
        canonical_id("intersection", "101")
    with pytest.raises(CanonicalIdError):
        canonical_id("ROAD_SEGMENT", "5")


def test_canonical_id_rejects_empty_key():
    with pytest.raises(CanonicalIdError):
        canonical_id("Player", "  ")


def test_is_canonical():
    assert is_canonical("Player:p42")
    assert is_canonical("Intersection:101")
    assert not is_canonical("player:p42")      # lowercase label
    assert not is_canonical("Player")          # no separator
    assert not is_canonical("Player:")         # empty key
    assert not is_canonical("Main St & 1st")   # free text (agentic-tskg failure mode)


def test_parse_canonical_roundtrip():
    assert parse_canonical("Player:p42") == ("Player", "p42")


def test_parse_canonical_rejects_bad_id():
    with pytest.raises(CanonicalIdError):
        parse_canonical("not an id")


def test_key_may_contain_colons():
    # only the FIRST colon separates label from key
    assert parse_canonical("Doc:arxiv:2501.1234") == ("Doc", "arxiv:2501.1234")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/contracts/test_ids.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kg_contracts.ids'`

- [ ] **Step 3: Write the implementation**

`src/kg_contracts/ids.py`:
```python
"""Canonical ``Label:key`` identifiers, enforced on every graph write.

Lineage: ts-kg canonical.py — repair-or-reject, never silently coerce.
Motivated by agentic-tskg's 0/18 ingestion failure (free-text ids).
"""

import re

_LABEL_RE = re.compile(r"^[A-Z][A-Za-z0-9]*$")


class CanonicalIdError(ValueError):
    """Raised when an id cannot be built or parsed as canonical Label:key."""


def canonical_id(label: str, key: str) -> str:
    """Build a canonical id, validating label shape and key non-emptiness."""
    if not _LABEL_RE.match(label):
        raise CanonicalIdError(f"label {label!r} is not PascalCase")
    cleaned = str(key).strip()
    if not cleaned:
        raise CanonicalIdError(f"key must be non-empty for label {label!r}")
    return f"{label}:{cleaned}"


def is_canonical(node_id: str) -> bool:
    """True if ``node_id`` has the form ``Label:key``."""
    label, sep, key = node_id.partition(":")
    return bool(sep) and bool(_LABEL_RE.match(label)) and bool(key.strip())


def parse_canonical(node_id: str) -> tuple[str, str]:
    """Split a canonical id into (label, key); raise CanonicalIdError otherwise."""
    if not is_canonical(node_id):
        raise CanonicalIdError(f"id {node_id!r} is not canonical Label:key")
    label, _, key = node_id.partition(":")
    return label, key
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/contracts/test_ids.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/kg_contracts/ids.py tests/contracts/test_ids.py
git commit -m "feat(contracts): canonical Label:key id helpers"
```

---

### Task 5: kg_contracts.schemas — CurationStatus, GraphNode, GraphEdge

**Files:**
- Create: `/Users/djjay0131/code/agentic-kgis/src/kg_contracts/schemas.py`
- Test: `/Users/djjay0131/code/agentic-kgis/tests/contracts/test_schemas.py`

**Interfaces:**
- Consumes: `kg_contracts.ids.is_canonical`
- Produces: `CurationStatus` (StrEnum: PROVISIONAL/ACTIVE/SUPERSEDED/REVOKED), `GraphNode(id, label, properties)` (frozen, canonical-validated, id label must equal `label`), `GraphEdge(source_id, target_id, type, properties)` (frozen, canonical endpoints, UPPER_SNAKE type) — consumed by `graph_store.py`, the memory store, and all later plans

- [ ] **Step 1: Write the failing tests**

`tests/contracts/test_schemas.py`:
```python
import pytest
from pydantic import ValidationError

from kg_contracts.schemas import CurationStatus, GraphEdge, GraphNode


def test_curation_status_values():
    assert {s.value for s in CurationStatus} == {
        "PROVISIONAL", "ACTIVE", "SUPERSEDED", "REVOKED"
    }


def test_graph_node_valid():
    n = GraphNode(id="Player:p42", label="Player", properties={"name": "Jay"})
    assert n.id == "Player:p42"
    assert n.properties["name"] == "Jay"


def test_graph_node_rejects_non_canonical_id():
    with pytest.raises(ValidationError, match="canonical"):
        GraphNode(id="Main St & 1st", label="Intersection")


def test_graph_node_rejects_label_mismatch():
    with pytest.raises(ValidationError, match="label"):
        GraphNode(id="Player:p42", label="Coach")


def test_graph_node_is_frozen():
    n = GraphNode(id="Player:p42", label="Player")
    with pytest.raises(ValidationError):
        n.id = "Player:p43"  # type: ignore[misc]


def test_graph_edge_valid():
    e = GraphEdge(source_id="Player:p42", target_id="Skill:hitting", type="HAS_SKILL")
    assert e.type == "HAS_SKILL"


def test_graph_edge_rejects_non_canonical_endpoint():
    with pytest.raises(ValidationError, match="canonical"):
        GraphEdge(source_id="p42", target_id="Skill:hitting", type="HAS_SKILL")


def test_graph_edge_rejects_bad_type():
    with pytest.raises(ValidationError, match="UPPER_SNAKE"):
        GraphEdge(source_id="Player:p42", target_id="Skill:hitting", type="hasSkill")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/contracts/test_schemas.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kg_contracts.schemas'`

- [ ] **Step 3: Write the implementation**

`src/kg_contracts/schemas.py`:
```python
"""Core graph value objects. Frozen; canonical-validated at construction.

GraphNode/GraphEdge are POST-gate types: constructing one asserts its ids
are canonical. Pre-gate proposals use ProposedNode/ProposedEdge (Task 6).
"""

import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, model_validator

from .ids import is_canonical

_EDGE_TYPE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class CurationStatus(StrEnum):
    PROVISIONAL = "PROVISIONAL"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


class GraphNode(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    label: str
    properties: dict[str, object] = {}

    @model_validator(mode="after")
    def _validate(self) -> "GraphNode":
        if not is_canonical(self.id):
            raise ValueError(f"node id {self.id!r} is not canonical Label:key")
        id_label = self.id.partition(":")[0]
        if id_label != self.label:
            raise ValueError(f"id label {id_label!r} does not match label {self.label!r}")
        return self


class GraphEdge(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_id: str
    target_id: str
    type: str
    properties: dict[str, object] = {}

    @model_validator(mode="after")
    def _validate(self) -> "GraphEdge":
        for endpoint in (self.source_id, self.target_id):
            if not is_canonical(endpoint):
                raise ValueError(f"endpoint {endpoint!r} is not canonical Label:key")
        if not _EDGE_TYPE_RE.match(self.type):
            raise ValueError(f"edge type {self.type!r} is not UPPER_SNAKE")
        return self
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/contracts/test_schemas.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/kg_contracts/schemas.py tests/contracts/test_schemas.py
git commit -m "feat(contracts): CurationStatus, GraphNode, GraphEdge"
```

---

### Task 6: kg_contracts.schemas — Provenance, ProposedNode/Edge, Candidate

**Files:**
- Modify: `/Users/djjay0131/code/agentic-kgis/src/kg_contracts/schemas.py` (append)
- Test: `/Users/djjay0131/code/agentic-kgis/tests/contracts/test_candidate.py`

**Interfaces:**
- Consumes: nothing new
- Produces: `Provenance(source, source_ref, actor, model, prompt_version)` (frozen), `ProposedNode(id, label, properties)` / `ProposedEdge(source_id, target_id, type, properties)` (frozen, NOT canonical-validated), `Candidate(node|edge, confidence, provenance)` with `.content_hash` (sha256 hex str over the proposal payload only) — the KGIS→KGCS seam used by every later plan

- [ ] **Step 1: Write the failing tests**

`tests/contracts/test_candidate.py`:
```python
import pytest
from pydantic import ValidationError

from kg_contracts.schemas import Candidate, ProposedEdge, ProposedNode, Provenance

PROV = Provenance(source="unit-test", actor="tester")


def test_proposed_node_allows_non_canonical_id():
    # pre-gate proposals may carry raw ids; the KGCS gate repairs or rejects
    p = ProposedNode(id="Main St & 1st", label="Intersection")
    assert p.id == "Main St & 1st"


def test_candidate_requires_exactly_one_proposal():
    node = ProposedNode(id="Player:p42", label="Player")
    edge = ProposedEdge(source_id="a", target_id="b", type="REL")
    with pytest.raises(ValidationError, match="exactly one"):
        Candidate(confidence=1.0, provenance=PROV)
    with pytest.raises(ValidationError, match="exactly one"):
        Candidate(node=node, edge=edge, confidence=1.0, provenance=PROV)


def test_candidate_confidence_bounds():
    node = ProposedNode(id="Player:p42", label="Player")
    with pytest.raises(ValidationError):
        Candidate(node=node, confidence=1.5, provenance=PROV)
    with pytest.raises(ValidationError):
        Candidate(node=node, confidence=-0.1, provenance=PROV)


def test_content_hash_stable_and_ignores_provenance_and_confidence():
    node = ProposedNode(id="Player:p42", label="Player", properties={"a": 1, "b": 2})
    same_node = ProposedNode(id="Player:p42", label="Player", properties={"b": 2, "a": 1})
    c1 = Candidate(node=node, confidence=0.7, provenance=PROV)
    c2 = Candidate(
        node=same_node,
        confidence=0.9,
        provenance=Provenance(source="other", actor="other"),
    )
    assert c1.content_hash == c2.content_hash
    assert len(c1.content_hash) == 64  # sha256 hex


def test_content_hash_differs_for_different_payloads():
    a = Candidate(
        node=ProposedNode(id="Player:p42", label="Player"),
        confidence=1.0, provenance=PROV,
    )
    b = Candidate(
        node=ProposedNode(id="Player:p43", label="Player"),
        confidence=1.0, provenance=PROV,
    )
    assert a.content_hash != b.content_hash
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/contracts/test_candidate.py -v`
Expected: FAIL — `ImportError: cannot import name 'Candidate'`

- [ ] **Step 3: Append the implementation to schemas.py**

Append to `src/kg_contracts/schemas.py` (add `import hashlib, json` at top with the other imports, and `Field` to the pydantic import):
```python
class Provenance(BaseModel):
    """Where a candidate came from. Immutable; never dropped (vttsi-evidence)."""

    model_config = ConfigDict(frozen=True)

    source: str                      # e.g. "openalex", "postgres:intersections"
    source_ref: str | None = None    # row id / document id / span
    actor: str                       # pipeline, extractor name, or human
    model: str | None = None         # LLM model id when extraction-produced
    prompt_version: str | None = None


class ProposedNode(BaseModel):
    """Pre-gate node proposal. Id may be raw; the KGCS gate repairs or rejects."""

    model_config = ConfigDict(frozen=True)

    id: str
    label: str
    properties: dict[str, object] = {}


class ProposedEdge(BaseModel):
    """Pre-gate edge proposal. Endpoints may be raw ids."""

    model_config = ConfigDict(frozen=True)

    source_id: str
    target_id: str
    type: str
    properties: dict[str, object] = {}


class Candidate(BaseModel):
    """Universal ingestion output: one proposal + confidence + provenance."""

    model_config = ConfigDict(frozen=True)

    node: ProposedNode | None = None
    edge: ProposedEdge | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    provenance: Provenance

    @model_validator(mode="after")
    def _exactly_one_proposal(self) -> "Candidate":
        if (self.node is None) == (self.edge is None):
            raise ValueError("Candidate must carry exactly one of node or edge")
        return self

    @property
    def content_hash(self) -> str:
        """sha256 over the proposal payload only — the idempotency key."""
        payload = (self.node or self.edge).model_dump()  # type: ignore[union-attr]
        blob = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()
```

- [ ] **Step 4: Run all schema tests to verify they pass**

Run: `.venv/bin/pytest tests/contracts/ -v`
Expected: all pass (Tasks 4–6 tests: 21 passed)

- [ ] **Step 5: Commit**

```bash
git add src/kg_contracts/schemas.py tests/contracts/test_candidate.py
git commit -m "feat(contracts): Provenance, proposals, Candidate with content hash"
```

---

### Task 7: GraphStore protocol + MemoryGraphStore reference implementation

**Files:**
- Create: `/Users/djjay0131/code/agentic-kgis/src/kg_contracts/graph_store.py`
- Create: `/Users/djjay0131/code/agentic-kgis/src/kg_contracts/testing/__init__.py` (empty)
- Create: `/Users/djjay0131/code/agentic-kgis/src/kg_contracts/testing/memory_store.py`
- Test: `/Users/djjay0131/code/agentic-kgis/tests/contracts/test_memory_store.py`

**Interfaces:**
- Consumes: `GraphNode`, `GraphEdge` from Task 5
- Produces:
  - `GraphStore` Protocol (runtime-checkable): `upsert_nodes(nodes: Sequence[GraphNode]) -> int` (count changed), `upsert_edges(edges: Sequence[GraphEdge]) -> int`, `get_node(node_id: str) -> GraphNode | None`, `find_nodes(label: str | None = None, properties: Mapping[str, object] | None = None) -> list[GraphNode]`, `neighborhood(node_id: str, hops: int = 1) -> list[GraphNode]` (undirected, excludes start node)
  - `MemoryGraphStore()` — dict-backed implementation, used by all KGCS/KGIS tests

- [ ] **Step 1: Write the failing tests**

`tests/contracts/test_memory_store.py`:
```python
from kg_contracts.graph_store import GraphStore
from kg_contracts.schemas import GraphEdge, GraphNode
from kg_contracts.testing.memory_store import MemoryGraphStore


def node(nid: str, **props: object) -> GraphNode:
    return GraphNode(id=nid, label=nid.partition(":")[0], properties=dict(props))


def test_satisfies_protocol():
    assert isinstance(MemoryGraphStore(), GraphStore)


def test_upsert_and_get():
    store = MemoryGraphStore()
    assert store.upsert_nodes([node("Player:p1", name="Jay")]) == 1
    fetched = store.get_node("Player:p1")
    assert fetched is not None and fetched.properties["name"] == "Jay"


def test_upsert_unchanged_is_noop():
    store = MemoryGraphStore()
    store.upsert_nodes([node("Player:p1", name="Jay")])
    assert store.upsert_nodes([node("Player:p1", name="Jay")]) == 0      # unchanged
    assert store.upsert_nodes([node("Player:p1", name="Jay Jr")]) == 1  # changed


def test_get_missing_returns_none():
    assert MemoryGraphStore().get_node("Player:nope") is None


def test_find_nodes_by_label_and_properties():
    store = MemoryGraphStore()
    store.upsert_nodes([node("Player:p1", pos="C"), node("Player:p2", pos="SS"),
                        node("Skill:hitting")])
    assert {n.id for n in store.find_nodes(label="Player")} == {"Player:p1", "Player:p2"}
    assert [n.id for n in store.find_nodes(label="Player", properties={"pos": "SS"})] == ["Player:p2"]
    assert len(store.find_nodes()) == 3


def test_edge_upsert_idempotent_by_key():
    store = MemoryGraphStore()
    store.upsert_nodes([node("Player:p1"), node("Skill:hitting")])
    e = GraphEdge(source_id="Player:p1", target_id="Skill:hitting", type="HAS_SKILL")
    assert store.upsert_edges([e]) == 1
    assert store.upsert_edges([e]) == 0


def test_neighborhood_hops_undirected_excludes_start():
    store = MemoryGraphStore()
    store.upsert_nodes([node("A:1"), node("B:2"), node("C:3")])
    store.upsert_edges([
        GraphEdge(source_id="A:1", target_id="B:2", type="REL"),
        GraphEdge(source_id="C:3", target_id="B:2", type="REL"),  # points INTO B
    ])
    one_hop = {n.id for n in store.neighborhood("A:1", hops=1)}
    assert one_hop == {"B:2"}
    two_hop = {n.id for n in store.neighborhood("A:1", hops=2)}
    assert two_hop == {"B:2", "C:3"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/contracts/test_memory_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kg_contracts.graph_store'`

- [ ] **Step 3: Write graph_store.py**

`src/kg_contracts/graph_store.py`:
```python
"""Engine-agnostic graph port. No Cypher/GQL on this protocol (ADR-010).

Generalized from vttsi-contracts GraphStore. Implementations: Spanner Graph,
Neo4j (later plans / adopter repos), MemoryGraphStore (kg_contracts.testing).
"""

from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable

from .schemas import GraphEdge, GraphNode


@runtime_checkable
class GraphStore(Protocol):
    def upsert_nodes(self, nodes: Sequence[GraphNode]) -> int:
        """Insert-or-replace by node id. Returns count actually changed."""
        ...

    def upsert_edges(self, edges: Sequence[GraphEdge]) -> int:
        """Insert-or-replace by (source_id, target_id, type). Returns count changed."""
        ...

    def get_node(self, node_id: str) -> GraphNode | None: ...

    def find_nodes(
        self,
        label: str | None = None,
        properties: Mapping[str, object] | None = None,
    ) -> list[GraphNode]:
        """All nodes matching label (if given) and exact property values (if given)."""
        ...

    def neighborhood(self, node_id: str, hops: int = 1) -> list[GraphNode]:
        """Nodes reachable within ``hops`` undirected steps, excluding the start."""
        ...
```

- [ ] **Step 4: Write memory_store.py**

`src/kg_contracts/testing/memory_store.py`:
```python
"""Dict-backed reference GraphStore for tests and offline development."""

from collections.abc import Mapping, Sequence

from ..schemas import GraphEdge, GraphNode


class MemoryGraphStore:
    def __init__(self) -> None:
        self._nodes: dict[str, GraphNode] = {}
        self._edges: dict[tuple[str, str, str], GraphEdge] = {}

    def upsert_nodes(self, nodes: Sequence[GraphNode]) -> int:
        changed = 0
        for n in nodes:
            if self._nodes.get(n.id) != n:
                self._nodes[n.id] = n
                changed += 1
        return changed

    def upsert_edges(self, edges: Sequence[GraphEdge]) -> int:
        changed = 0
        for e in edges:
            key = (e.source_id, e.target_id, e.type)
            if self._edges.get(key) != e:
                self._edges[key] = e
                changed += 1
        return changed

    def get_node(self, node_id: str) -> GraphNode | None:
        return self._nodes.get(node_id)

    def find_nodes(
        self,
        label: str | None = None,
        properties: Mapping[str, object] | None = None,
    ) -> list[GraphNode]:
        result = []
        for n in self._nodes.values():
            if label is not None and n.label != label:
                continue
            if properties and any(n.properties.get(k) != v for k, v in properties.items()):
                continue
            result.append(n)
        return result

    def neighborhood(self, node_id: str, hops: int = 1) -> list[GraphNode]:
        frontier, seen = {node_id}, {node_id}
        for _ in range(hops):
            nxt = set()
            for src, tgt, _type in self._edges:
                if src in frontier and tgt not in seen:
                    nxt.add(tgt)
                if tgt in frontier and src not in seen:
                    nxt.add(src)
            seen |= nxt
            frontier = nxt
        seen.discard(node_id)
        return [self._nodes[i] for i in sorted(seen) if i in self._nodes]
```

Also create empty `src/kg_contracts/testing/__init__.py`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/contracts/test_memory_store.py -v`
Expected: 7 passed

- [ ] **Step 6: Commit**

```bash
git add src/kg_contracts/graph_store.py src/kg_contracts/testing tests/contracts/test_memory_store.py
git commit -m "feat(contracts): GraphStore protocol + MemoryGraphStore reference"
```

---

### Task 8: Reusable GraphStore contract test suite

**Files:**
- Create: `/Users/djjay0131/code/agentic-kgis/src/kg_contracts/testing/contract.py`
- Test: `/Users/djjay0131/code/agentic-kgis/tests/contracts/test_contract_suite.py`

**Interfaces:**
- Consumes: `GraphStore`, `GraphNode`, `GraphEdge`, `MemoryGraphStore`
- Produces: `GraphStoreContract` — a pytest-style mixin class; implementors subclass it and override `make_store() -> GraphStore`. Every future adapter (Spanner, Neo4j) must pass it (spec §10). Verified here by running it against `MemoryGraphStore`.

- [ ] **Step 1: Write the failing test (the suite applied to MemoryGraphStore)**

`tests/contracts/test_contract_suite.py`:
```python
from kg_contracts.graph_store import GraphStore
from kg_contracts.testing.contract import GraphStoreContract
from kg_contracts.testing.memory_store import MemoryGraphStore


class TestMemoryGraphStoreContract(GraphStoreContract):
    def make_store(self) -> GraphStore:
        return MemoryGraphStore()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/contracts/test_contract_suite.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kg_contracts.testing.contract'`

- [ ] **Step 3: Write the contract suite**

`src/kg_contracts/testing/contract.py`:
```python
"""Reusable conformance suite: subclass, implement make_store(), get tests free.

Every GraphStore implementation (memory, Neo4j, Spanner Graph) must pass this
suite unchanged (spec §10, vttsi contract-test discipline).
"""

from ..graph_store import GraphStore
from ..schemas import GraphEdge, GraphNode


class GraphStoreContract:
    def make_store(self) -> GraphStore:
        raise NotImplementedError("subclass must provide a fresh, empty store")

    @staticmethod
    def _node(nid: str, **props: object) -> GraphNode:
        return GraphNode(id=nid, label=nid.partition(":")[0], properties=dict(props))

    def test_contract_upsert_then_get(self) -> None:
        store = self.make_store()
        store.upsert_nodes([self._node("Player:p1", name="Jay")])
        got = store.get_node("Player:p1")
        assert got is not None and got.properties["name"] == "Jay"

    def test_contract_upsert_is_idempotent(self) -> None:
        store = self.make_store()
        n = self._node("Player:p1", name="Jay")
        assert store.upsert_nodes([n]) == 1
        assert store.upsert_nodes([n]) == 0

    def test_contract_missing_node_is_none(self) -> None:
        assert self.make_store().get_node("Player:missing") is None

    def test_contract_find_by_label_and_property(self) -> None:
        store = self.make_store()
        store.upsert_nodes([self._node("Player:p1", pos="C"),
                            self._node("Player:p2", pos="SS"),
                            self._node("Skill:hitting")])
        assert {n.id for n in store.find_nodes(label="Player")} == {"Player:p1", "Player:p2"}
        assert [n.id for n in store.find_nodes(label="Player", properties={"pos": "C"})] \
            == ["Player:p1"]

    def test_contract_edge_upsert_idempotent(self) -> None:
        store = self.make_store()
        store.upsert_nodes([self._node("Player:p1"), self._node("Skill:hitting")])
        e = GraphEdge(source_id="Player:p1", target_id="Skill:hitting", type="HAS_SKILL")
        assert store.upsert_edges([e]) == 1
        assert store.upsert_edges([e]) == 0

    def test_contract_neighborhood_undirected(self) -> None:
        store = self.make_store()
        store.upsert_nodes([self._node("A:1"), self._node("B:2"), self._node("C:3")])
        store.upsert_edges([
            GraphEdge(source_id="A:1", target_id="B:2", type="REL"),
            GraphEdge(source_id="C:3", target_id="B:2", type="REL"),
        ])
        assert {n.id for n in store.neighborhood("A:1", hops=1)} == {"B:2"}
        assert {n.id for n in store.neighborhood("A:1", hops=2)} == {"B:2", "C:3"}
```

- [ ] **Step 4: Run test to verify the suite passes**

Run: `.venv/bin/pytest tests/contracts/test_contract_suite.py -v`
Expected: 6 passed (all `test_contract_*` methods collected via the subclass)

- [ ] **Step 5: Commit**

```bash
git add src/kg_contracts/testing/contract.py tests/contracts/test_contract_suite.py
git commit -m "feat(contracts): reusable GraphStore conformance test suite"
```

---

### Task 9: kg_contracts.curation — ConfidencePolicy, Route, gate/queue protocols

**Files:**
- Create: `/Users/djjay0131/code/agentic-kgis/src/kg_contracts/curation.py`
- Test: `/Users/djjay0131/code/agentic-kgis/tests/contracts/test_curation.py`

**Interfaces:**
- Consumes: `Candidate` (Task 6)
- Produces (consumed by Plans 2 and 4):
  - `Route` StrEnum: `AUTO`, `LLM_EVALUATE`, `CONSENSUS`, `HUMAN`
  - `ConfidencePolicy(auto_min=0.95, evaluate_min=0.80, consensus_min=0.50)` with `route(confidence: float) -> Route`; validates `auto_min >= evaluate_min >= consensus_min`
  - `GateOutcome` StrEnum: `ACCEPTED`, `REPAIRED`, `REJECTED`
  - `GateResult(outcome, written_id: str | None, reason: str | None, candidate_hash: str)` (frozen)
  - `WriteGate` Protocol: `write(candidates: Sequence[Candidate]) -> list[GateResult]`
  - `ReviewItem(id, kind, payload: dict, priority: str, reason: str)` (frozen), `ReviewDecision` StrEnum: `APPROVE`, `REJECT`, `MERGE_ELSEWHERE`
  - `ReviewQueue` Protocol: `enqueue(item: ReviewItem) -> str`, `pending(limit: int = 50) -> list[ReviewItem]`, `resolve(item_id: str, decision: ReviewDecision) -> None`
  - `Resolution(matched_id: str | None, confidence: float)` (frozen), `Resolver` Protocol: `resolve(provisional: GraphNode) -> Resolution` (spec §5 curation.py; implemented in Plan 4)

- [ ] **Step 1: Write the failing tests**

`tests/contracts/test_curation.py`:
```python
import pytest
from pydantic import ValidationError

from kg_contracts.curation import ConfidencePolicy, GateOutcome, Route


def test_route_values():
    assert {r.value for r in Route} == {"AUTO", "LLM_EVALUATE", "CONSENSUS", "HUMAN"}


def test_default_policy_routing():
    p = ConfidencePolicy()
    assert p.route(1.0) is Route.AUTO
    assert p.route(0.95) is Route.AUTO           # boundary inclusive at each floor
    assert p.route(0.90) is Route.LLM_EVALUATE
    assert p.route(0.80) is Route.LLM_EVALUATE
    assert p.route(0.60) is Route.CONSENSUS
    assert p.route(0.50) is Route.CONSENSUS
    assert p.route(0.49) is Route.HUMAN
    assert p.route(0.0) is Route.HUMAN


def test_policy_rejects_unordered_thresholds():
    with pytest.raises(ValidationError, match="ordered"):
        ConfidencePolicy(auto_min=0.7, evaluate_min=0.8, consensus_min=0.5)


def test_full_automation_is_config_only():
    # the learning-system endgame: drop the human floor via config, no code change
    p = ConfidencePolicy(auto_min=0.6, evaluate_min=0.3, consensus_min=0.0)
    assert p.route(0.01) is Route.CONSENSUS  # nothing routes to HUMAN


def test_gate_outcome_values():
    assert {o.value for o in GateOutcome} == {"ACCEPTED", "REPAIRED", "REJECTED"}


def test_resolver_protocol_duck_types():
    from kg_contracts.curation import Resolution, Resolver
    from kg_contracts.schemas import GraphNode

    class FakeResolver:
        def resolve(self, provisional):
            return Resolution(matched_id=None, confidence=0.0)

    assert isinstance(FakeResolver(), Resolver)
    r = FakeResolver().resolve(GraphNode(id="Player:p1", label="Player"))
    assert r.matched_id is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/contracts/test_curation.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kg_contracts.curation'`

- [ ] **Step 3: Write the implementation**

`src/kg_contracts/curation.py`:
```python
"""Curation contracts: confidence routing, write gate, review queue.

ConfidencePolicy is shared by entity promotion AND the graph-level
extend-vs-new advisor (spec §5.4): automating a decision later is a
threshold change, not a code change.
"""

from collections.abc import Sequence
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .schemas import Candidate


class Route(StrEnum):
    AUTO = "AUTO"
    LLM_EVALUATE = "LLM_EVALUATE"
    CONSENSUS = "CONSENSUS"
    HUMAN = "HUMAN"


class ConfidencePolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    auto_min: float = Field(default=0.95, ge=0.0, le=1.0)
    evaluate_min: float = Field(default=0.80, ge=0.0, le=1.0)
    consensus_min: float = Field(default=0.50, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _ordered(self) -> "ConfidencePolicy":
        if not (self.auto_min >= self.evaluate_min >= self.consensus_min):
            raise ValueError("thresholds must be ordered: auto >= evaluate >= consensus")
        return self

    def route(self, confidence: float) -> Route:
        if confidence >= self.auto_min:
            return Route.AUTO
        if confidence >= self.evaluate_min:
            return Route.LLM_EVALUATE
        if confidence >= self.consensus_min:
            return Route.CONSENSUS
        return Route.HUMAN


class GateOutcome(StrEnum):
    ACCEPTED = "ACCEPTED"
    REPAIRED = "REPAIRED"
    REJECTED = "REJECTED"


class GateResult(BaseModel):
    """Per-candidate gate outcome. Rejections are data, not exceptions."""

    model_config = ConfigDict(frozen=True)

    outcome: GateOutcome
    written_id: str | None = None    # canonical id actually written (None if rejected)
    reason: str | None = None        # rejection/repair explanation
    candidate_hash: str              # Candidate.content_hash, for idempotency + audit


@runtime_checkable
class WriteGate(Protocol):
    def write(self, candidates: Sequence[Candidate]) -> list[GateResult]: ...


class ReviewDecision(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    MERGE_ELSEWHERE = "MERGE_ELSEWHERE"


class ReviewItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    kind: str                        # e.g. "entity-match", "graph-decision"
    payload: dict[str, object]       # candidate vs match, evidence, provenance
    priority: str = "P3"             # P1=24h, P2=7d, P3=30d (agentic-kg SLAs)
    reason: str


@runtime_checkable
class ReviewQueue(Protocol):
    def enqueue(self, item: ReviewItem) -> str: ...
    def pending(self, limit: int = 50) -> list[ReviewItem]: ...
    def resolve(self, item_id: str, decision: ReviewDecision) -> None: ...


class Resolution(BaseModel):
    """Outcome of matching one PROVISIONAL node against ACTIVE entities."""

    model_config = ConfigDict(frozen=True)

    matched_id: str | None = None    # canonical id of the ACTIVE match, if any
    confidence: float = Field(ge=0.0, le=1.0)


@runtime_checkable
class Resolver(Protocol):
    """Entity resolution port; embedding-based implementation lands in Plan 4."""

    def resolve(self, provisional: GraphNode) -> Resolution: ...
```

(Add `from .schemas import Candidate, GraphNode` in place of the existing `from .schemas import Candidate` import at the top of `curation.py`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/contracts/test_curation.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/kg_contracts/curation.py tests/contracts/test_curation.py
git commit -m "feat(contracts): ConfidencePolicy routing + gate/review contracts"
```

---

### Task 10: kg_contracts.ingestion — Source/Extractor/CompletionClient + IngestReport

**Files:**
- Create: `/Users/djjay0131/code/agentic-kgis/src/kg_contracts/ingestion.py`
- Test: `/Users/djjay0131/code/agentic-kgis/tests/contracts/test_ingestion.py`

**Interfaces:**
- Consumes: `Candidate`, `Provenance`, `GateResult`
- Produces (consumed by Plan 3):
  - `Source` Protocol: `fetch() -> Iterator[Candidate]` (structured mode; deterministic, confidence 1.0 by convention)
  - `Extractor` Protocol: `name: str` property; `extract(text: str, provenance: Provenance) -> list[Candidate]`
  - `CompletionClient` Protocol: `complete(prompt: str, *, system: str | None = None) -> str` (LLM provider injection point)
  - `IngestReport(graph, accepted, repaired, rejected, provisional, incomplete, failures: list[str])` with `record(result: GateResult, provisional: bool)` accumulator — mutable by design (it accumulates), NOT frozen
  - NOTE: the spec's `IngestJob` protocol (§5 ingestion.py) is deliberately deferred to Plan 3, where the pipeline's real shape (batching, registry consultation, resumability) fixes its signature — defining it now would be guessing (YAGNI). Plan 3 adds it to `kg_contracts.ingestion` and to the public API.

- [ ] **Step 1: Write the failing tests**

`tests/contracts/test_ingestion.py`:
```python
from kg_contracts.curation import GateOutcome, GateResult
from kg_contracts.ingestion import CompletionClient, Extractor, IngestReport, Source
from kg_contracts.schemas import Candidate, ProposedNode, Provenance


def test_protocols_are_runtime_checkable_with_duck_types():
    class FakeSource:
        def fetch(self):
            yield from ()

    class FakeExtractor:
        name = "fake"

        def extract(self, text, provenance):
            return []

    class FakeLLM:
        def complete(self, prompt, *, system=None):
            return "ok"

    assert isinstance(FakeSource(), Source)
    assert isinstance(FakeExtractor(), Extractor)
    assert isinstance(FakeLLM(), CompletionClient)


def _result(outcome: GateOutcome) -> GateResult:
    c = Candidate(
        node=ProposedNode(id="Player:p1", label="Player"),
        confidence=1.0,
        provenance=Provenance(source="t", actor="t"),
    )
    return GateResult(outcome=outcome, written_id="Player:p1", candidate_hash=c.content_hash)


def test_ingest_report_accumulates():
    r = IngestReport(graph="baseball")
    r.record(_result(GateOutcome.ACCEPTED), provisional=False)
    r.record(_result(GateOutcome.ACCEPTED), provisional=True)
    r.record(_result(GateOutcome.REPAIRED), provisional=False)
    r.record(_result(GateOutcome.REJECTED), provisional=False)
    assert (r.accepted, r.repaired, r.rejected, r.provisional) == (2, 1, 1, 1)
    assert r.incomplete is False


def test_ingest_report_marks_incomplete_on_failure():
    r = IngestReport(graph="baseball")
    r.fail("extractor player-extractor: timeout")
    assert r.incomplete is True
    assert r.failures == ["extractor player-extractor: timeout"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/contracts/test_ingestion.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kg_contracts.ingestion'`

- [ ] **Step 3: Write the implementation**

`src/kg_contracts/ingestion.py`:
```python
"""Ingestion contracts. Both modes emit Candidates; the gate does all writes."""

from collections.abc import Iterator
from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from .curation import GateOutcome, GateResult
from .schemas import Candidate, Provenance


@runtime_checkable
class Source(Protocol):
    """Structured-mode source: deterministic rows → Candidates (confidence 1.0)."""

    def fetch(self) -> Iterator[Candidate]: ...


@runtime_checkable
class Extractor(Protocol):
    """Unstructured-mode extractor: one entity type per extractor (config, not code)."""

    @property
    def name(self) -> str: ...

    def extract(self, text: str, provenance: Provenance) -> list[Candidate]: ...


@runtime_checkable
class CompletionClient(Protocol):
    """LLM provider injection point — KGIS mandates no provider."""

    def complete(self, prompt: str, *, system: str | None = None) -> str: ...


class IngestReport(BaseModel):
    """Persisted outcome of one ingest run. A failed extractor yields a
    partial report marked incomplete — never a silent gap (spec §9)."""

    graph: str
    accepted: int = 0
    repaired: int = 0
    rejected: int = 0
    provisional: int = 0
    incomplete: bool = False
    failures: list[str] = []

    def record(self, result: GateResult, provisional: bool) -> None:
        if result.outcome is GateOutcome.ACCEPTED:
            self.accepted += 1
        elif result.outcome is GateOutcome.REPAIRED:
            self.repaired += 1
        else:
            self.rejected += 1
        if provisional:
            self.provisional += 1

    def fail(self, message: str) -> None:
        self.incomplete = True
        self.failures.append(message)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/contracts/test_ingestion.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/kg_contracts/ingestion.py tests/contracts/test_ingestion.py
git commit -m "feat(contracts): Source/Extractor/CompletionClient + IngestReport"
```

---

### Task 11: kg_contracts.registry — GraphDescriptor, Recommendation, RegistryStore

**Files:**
- Create: `/Users/djjay0131/code/agentic-kgis/src/kg_contracts/registry.py`
- Test: `/Users/djjay0131/code/agentic-kgis/tests/contracts/test_registry.py`

**Interfaces:**
- Consumes: nothing new
- Produces (consumed by Plans 3 and 5):
  - `Backend` StrEnum: `SPANNER`, `NEO4J`, `MEMORY`
  - `GraphDescriptor(name, owner, domain, tags, backend, connection_ref, node_types, edge_types, policy_ref, created_by, decision_record)` (frozen; `connection_ref` is a secret NAME, never a secret value)
  - `Recommendation(action: "extend"|"create", graph_name, score: float 0..1, reasons: list[str])` (frozen; `extend` requires `graph_name`)
  - `RegistryStore` Protocol: `register(descriptor: GraphDescriptor) -> None`, `get(name: str) -> GraphDescriptor | None`, `all() -> list[GraphDescriptor]`

- [ ] **Step 1: Write the failing tests**

`tests/contracts/test_registry.py`:
```python
import pytest
from pydantic import ValidationError

from kg_contracts.registry import Backend, GraphDescriptor, Recommendation, RegistryStore


def _descriptor(**overrides: object) -> GraphDescriptor:
    base: dict[str, object] = dict(
        name="baseball",
        owner="djjay0131",
        domain="baseball player development",
        tags=["sports", "coaching"],
        backend=Backend.MEMORY,
        node_types=["Player", "Skill", "Drill"],
        edge_types=["HAS_SKILL", "TRAINED_BY"],
        created_by="plan-1-test",
    )
    base.update(overrides)
    return GraphDescriptor(**base)  # type: ignore[arg-type]


def test_descriptor_valid_and_frozen():
    d = _descriptor()
    assert d.backend is Backend.MEMORY
    with pytest.raises(ValidationError):
        d.name = "other"  # type: ignore[misc]


def test_recommendation_extend_requires_graph_name():
    with pytest.raises(ValidationError, match="graph_name"):
        Recommendation(action="extend", score=0.9, reasons=["domain overlap"])


def test_recommendation_create_allows_no_graph_name():
    r = Recommendation(action="create", score=0.8, reasons=["disjoint ontology"])
    assert r.graph_name is None


def test_registry_store_protocol_duck_types():
    class FakeRegistry:
        def __init__(self):
            self._d: dict[str, GraphDescriptor] = {}

        def register(self, descriptor):
            self._d[descriptor.name] = descriptor

        def get(self, name):
            return self._d.get(name)

        def all(self):
            return list(self._d.values())

    reg = FakeRegistry()
    assert isinstance(reg, RegistryStore)
    reg.register(_descriptor())
    assert reg.get("baseball") is not None
    assert len(reg.all()) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/contracts/test_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kg_contracts.registry'`

- [ ] **Step 3: Write the implementation**

`src/kg_contracts/registry.py`:
```python
"""Graph registry contracts: one GraphDescriptor per graph (spec §8).

Schema and protocol only — the SQLite implementation lives in kgis
(contracts stay I/O-free). The advisor implementation lives in kgcs.
"""

from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Backend(StrEnum):
    SPANNER = "SPANNER"
    NEO4J = "NEO4J"
    MEMORY = "MEMORY"


class GraphDescriptor(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    owner: str
    domain: str                          # free-text domain description
    tags: list[str] = []
    backend: Backend
    connection_ref: str | None = None    # secret NAME (e.g. Secret Manager key), never a value
    node_types: list[str] = []           # active ontology summary
    edge_types: list[str] = []
    policy_ref: str | None = None        # this graph's ConfidencePolicy config ref
    created_by: str
    decision_record: str | None = None   # lineage: why this graph exists


class Recommendation(BaseModel):
    """Advisor output for the extend-vs-new decision. v1: routed to a human."""

    model_config = ConfigDict(frozen=True)

    action: Literal["extend", "create"]
    graph_name: str | None = None
    score: float = Field(ge=0.0, le=1.0)
    reasons: list[str]

    @model_validator(mode="after")
    def _extend_needs_target(self) -> "Recommendation":
        if self.action == "extend" and not self.graph_name:
            raise ValueError("action 'extend' requires graph_name")
        return self


@runtime_checkable
class RegistryStore(Protocol):
    def register(self, descriptor: GraphDescriptor) -> None: ...
    def get(self, name: str) -> GraphDescriptor | None: ...
    def all(self) -> list[GraphDescriptor]: ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/contracts/test_registry.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/kg_contracts/registry.py tests/contracts/test_registry.py
git commit -m "feat(contracts): GraphDescriptor, Recommendation, RegistryStore"
```

---

### Task 12: Public API exports, lint/type gate, CI, cross-repo verification

**Files:**
- Modify: `/Users/djjay0131/code/agentic-kgis/src/kg_contracts/__init__.py`
- Create: `/Users/djjay0131/code/agentic-kgis/.github/workflows/ci.yml`
- Create: `/Users/djjay0131/code/agentic-kgcs/.github/workflows/ci.yml`
- Test: `/Users/djjay0131/code/agentic-kgis/tests/contracts/test_public_api.py`, `/Users/djjay0131/code/agentic-kgcs/tests/test_contracts_available.py`

**Interfaces:**
- Consumes: everything from Tasks 4–11
- Produces: stable import surface `from kg_contracts import GraphStore, GraphNode, Candidate, ...`; green ruff/mypy/pytest in both repos; CI workflows

- [ ] **Step 1: Write the failing test**

`tests/contracts/test_public_api.py`:
```python
def test_top_level_exports():
    from kg_contracts import (
        Backend,
        Candidate,
        CanonicalIdError,
        CompletionClient,
        ConfidencePolicy,
        CurationStatus,
        Extractor,
        GateOutcome,
        GateResult,
        GraphDescriptor,
        GraphEdge,
        GraphNode,
        GraphStore,
        IngestReport,
        ProposedEdge,
        ProposedNode,
        Provenance,
        Recommendation,
        RegistryStore,
        Resolution,
        Resolver,
        ReviewDecision,
        ReviewItem,
        ReviewQueue,
        Route,
        Source,
        WriteGate,
        canonical_id,
        is_canonical,
        parse_canonical,
    )

    assert GraphStore is not None and Candidate is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/contracts/test_public_api.py -v`
Expected: FAIL — `ImportError` (empty `__init__.py`)

- [ ] **Step 3: Write the exports**

`src/kg_contracts/__init__.py`:
```python
"""kg_contracts: domain-neutral knowledge-graph ports layer.

Spec: docs/superpowers/specs/2026-07-09-kgis-kgcs-design.md (agentic-kgis repo).
"""

from .curation import (
    ConfidencePolicy,
    GateOutcome,
    GateResult,
    Resolution,
    Resolver,
    ReviewDecision,
    ReviewItem,
    ReviewQueue,
    Route,
    WriteGate,
)
from .graph_store import GraphStore
from .ids import CanonicalIdError, canonical_id, is_canonical, parse_canonical
from .ingestion import CompletionClient, Extractor, IngestReport, Source
from .registry import Backend, GraphDescriptor, Recommendation, RegistryStore
from .schemas import (
    Candidate,
    CurationStatus,
    GraphEdge,
    GraphNode,
    ProposedEdge,
    ProposedNode,
    Provenance,
)

__all__ = [
    "Backend", "Candidate", "CanonicalIdError", "CompletionClient",
    "ConfidencePolicy", "CurationStatus", "Extractor", "GateOutcome",
    "GateResult", "GraphDescriptor", "GraphEdge", "GraphNode", "GraphStore",
    "IngestReport", "ProposedEdge", "ProposedNode", "Provenance",
    "Recommendation", "RegistryStore", "Resolution", "Resolver",
    "ReviewDecision", "ReviewItem", "ReviewQueue", "Route", "Source", "WriteGate",
    "canonical_id", "is_canonical", "parse_canonical",
]
```

- [ ] **Step 4: Run the full quality gate**

Run:
```bash
cd /Users/djjay0131/code/agentic-kgis
.venv/bin/pytest -v
.venv/bin/ruff check src tests
.venv/bin/mypy src
```
Expected: all tests pass (≈42), ruff clean, mypy clean. Fix any findings before proceeding (typical: unused imports, missing return annotations in tests — annotate test functions `-> None` or relax mypy for tests by adding to pyproject: `[[tool.mypy.overrides]] module = "tests.*"` with `strict = false`).

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

`agentic-kgcs/.github/workflows/ci.yml` (installs the sibling from GitHub; requires `CONSTELLATION_PAT` secret once repos are pushed — same pattern as the vttsi repos):
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
from kg_contracts import Candidate, ConfidencePolicy, GraphStore, Route
from kg_contracts.testing.contract import GraphStoreContract
from kg_contracts.testing.memory_store import MemoryGraphStore


class TestContractsUsableFromKgcs(GraphStoreContract):
    def make_store(self) -> GraphStore:
        return MemoryGraphStore()


def test_policy_available():
    assert ConfidencePolicy().route(0.99) is Route.AUTO
    assert Candidate is not None
```

Run:
```bash
cd /Users/djjay0131/code/agentic-kgcs
.venv/bin/pip install -e ../agentic-kgis  # refresh editable install
.venv/bin/pytest -v
```
Expected: 8 passed (packaging test + 6 contract tests + policy test)

- [ ] **Step 7: Update memory banks and commit both repos**

Update `agentic-kgis/llm/memory_bank/progress.md` — replace the `Works:` line with:
```markdown
Works: kg_contracts complete (ids, schemas, Candidate, GraphStore protocol,
MemoryGraphStore, contract test suite, curation/ingestion/registry contracts,
public API), CI. Plan 1 done.
```
Update `agentic-kgcs/llm/memory_bank/progress.md` — replace the `Works:` line with:
```markdown
Works: packaging, kg_contracts import + contract suite green from kgcs, CI.
```

```bash
cd /Users/djjay0131/code/agentic-kgis
git add src/kg_contracts/__init__.py tests .github llm pyproject.toml
git commit -m "feat(contracts): public API, quality gate, CI"

cd /Users/djjay0131/code/agentic-kgcs
git add tests .github llm
git commit -m "test: verify kg_contracts consumable from kgcs; add CI"
```

---

## Plan 1 Definition of Done

- Both repos are git repos with Constellize memory banks at `llm/memory_bank/`
- `agentic-kgis`: `pytest`, `ruff check`, `mypy src` all green; `kg_contracts` public API exports everything in Task 12's test
- `agentic-kgcs`: imports `kg_contracts`, runs the `GraphStoreContract` suite green against `MemoryGraphStore`
- Plan 2 (KGCS inline gate) can begin with no further scaffolding
