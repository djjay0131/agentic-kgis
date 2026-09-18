# Feature: KGIS Website Documentation

**Status:** SPECIFIED (constellize:feature:specify — dual-persona review complete)
**Date:** 2026-09-17
**Author:** Feature Architect (AI-assisted)

## Problem

KGIS (the platform packages `kg_contracts` + `kgis` + `kg_eval`) is built and
merged, but there is **no published documentation**. Anyone evaluating the work
(portfolio visitors on jason.cusati.us) or building an adopter app on it
(baseball-ai, construction-ai, …) has nothing to read: no statement of *what
KGIS is*, *why it exists*, *its architecture*, or *how to use it*. The design
spec and 23 ADRs are control-plane artifacts inside the repo, not reader-facing
docs.

Publishing is non-trivial because `jason.cusati.us` is **not** a
commit-a-markdown-file site. It is a **hub that ingests from satellite repos**
through a governed publishing contract (`website/contract/`): a satellite builds
`dist/` + `manifest.json` → GCS bucket → hub polls hourly → validates → Astro
build → Firebase Hosting. Three hard constraints shape the solution:

1. You cannot publish by committing to `website`. KGIS must be a **provisioned
   satellite** (`source: kgis`) — Terraform in `website/infra`, **owner-only**.
2. The `section` enum is frozen (research/projects/writing/cv/phd) — no "docs".
   A service's docs fit **`projects`**.
3. **`md`/`mdx` have no renderer wired up in the hub yet.** A multi-page docs
   section that works *today* must ship as **`format: html`** — a self-contained
   static site served verbatim at `/projects/kgis/kgis-docs/`.

## Goals

- Publish a **multi-page KGIS documentation site** to
  `jason.cusati.us/projects/kgis/kgis-docs/` covering **what / why /
  architecture / how-to-use**.
- **Layered audience:** approachable overview for general/portfolio readers;
  deeper, task-oriented guides for developers integrating KGIS.
- **How-to-use depth:** getting-started plus working usage for **both** ingestion
  modes (structured sync + LLM extraction) and the core concepts + API basics.
- **Zero hub changes required to publish** — use the existing `format: html`
  path; no new hub renderer, no contract change.
- **Self-contained, contract-valid delivery:** a `manifest.json` that passes
  `website/contract/validate-manifest.mjs`, plus a publish GitHub Action in
  `agentic-kgis`.
- Docs live **in `agentic-kgis`** and rebuild/republish from source on change.
- **Lightly branded:** theme MkDocs Material (palette/logo/fonts) to roughly match
  jason.cusati.us so the embedded site doesn't feel jarring (no hub chrome work).
- **Drift-guarded, cheaply:** living docs kept lean and reviewed per release, with
  the ADR index / design spec as the authoritative source of truth (deep detail is
  linked, not duplicated).
- **Link-safe by CI:** an automated check fails the build if the site would ship a
  broken link or an absolute in-site URL under the `/projects/kgis/kgis-docs/` mount.

## Non-Goals

- **No hub-side feature work.** Not building a generic `sources` md/mdx renderer,
  not touching `website/contract/`, `content.config.ts`, or the section enum.
  (If native md-in-site-chrome is ever wanted, that is separate hub work + an ADR.)
- **Not doing the satellite provisioning.** The Terraform in `website/infra`
  (service account, WIF provider entry for the KGIS repo, prefix-scoped IAM) is
  owner-only; this feature *depends on* it but does not perform it.
- **Not full API reference / autodoc.** "API basics" is a curated map of the key
  public entry points, not exhaustive generated reference.
- **Not documenting KGCS.** KGIS docs may name the KGIS↔KGCS boundary but KGCS is
  a separate repo/service with its own docs.
- Not covering deep internals beyond what a user needs (e.g. no ledger SQL
  schema walkthrough).

## User Stories

- As a **portfolio visitor**, I want a clear "what is KGIS and why does it exist"
  so I understand the work without reading code.
- As a **developer integrating KGIS**, I want a quickstart and per-mode guides so
  I can ingest data through `CandidateSink` without reverse-engineering the repo.
- As an **architect**, I want the architecture page (ports/adapters, the Candidate
  seam, the KGIS↔KGCS boundary, determinism/evidence guarantees) so I can judge
  fit and boundaries.
- As the **hub owner**, I want the docs to publish through the existing satellite
  contract with a manifest that passes validation, so nothing bespoke is added to
  the hub.

## Design Approach

### Toolchain
**MkDocs + Material** — Python-native (installs via `uv` as a docs extra),
markdown-authored, builds a self-contained static site. Output is served verbatim
as a `format: html` satellite item under `section: projects`, mirroring the
proven `phd-milestones` example on the hub. Material's palette, logo, and fonts
are set to roughly match jason.cusati.us so the sub-path site reads as part of the
work rather than a jarring third-party page (decided in review: verbatim html with
light theming, **not** the larger native-md hub integration).

### Repo layout (new, in `agentic-kgis`, separate from the existing `docs/` ADR tree)
```
docs-site/
  mkdocs.yml               # site config + nav (the doc structure)
  content/                 # docs_dir (authored markdown)
    index.md               # What is KGIS
    why.md                 # Why it exists (the problem)
    architecture.md        # Ports/adapters, Candidate seam, KGIS↔KGCS, guarantees
    usage/quickstart.md
    usage/structured-sync.md
    usage/llm-extraction.md
    concepts.md            # Candidate, CandidateSink, ledger, evidence, scores
    api.md                 # API basics (key public entry points)
  manifest.json            # satellite publish manifest (contract-valid)
  # build output -> docs-site/dist/ (gitignored; produced by `mkdocs build`)
```

### Content plan (what each page covers)
- **index.md — What is KGIS:** one-paragraph definition; the three packages
  (`kg_contracts` frozen ports, `kgis` engines, `kg_eval`); the **Candidate**
  universal seam (ingestion emits proposals, never writes a graph); where KGIS
  sits (reusable platform; KGCS curates; adopter apps consume).
- **why.md — Why KGIS:** the problem it solves — domain-neutral, governed,
  evidence-first ingestion reused across adopter apps; separation of ingestion
  from curation; no direct graph writes (only `CandidateSink`, ADR-0010);
  honest nulls; determinism/idempotency; frozen contracts as the shared seam.
- **architecture.md:** ports & adapters / DI (readers, normalizers, validators,
  builders, sinks, clocks, id strategies injected); the Candidate seam +
  `CandidateSink`; two-tier validation; namespaced identity (`EntityRef`, no bare
  `Label:key`); bitemporal assertions; the persistent candidate **ledger** +
  **evidence registry**; `CandidateScores` (source_reliability vs
  extraction_confidence, no single confidence float); the **KGIS↔KGCS boundary**;
  a diagram of the two ingestion paths. Links to the ADR index.
- **usage/quickstart.md:** install (`uv`/`pip`); minimal end-to-end — reader →
  normalize → validate → build → `MemoryCandidateSink`; read the `IngestionReport`.
- **usage/structured-sync.md:** deterministic structured-sync — injected
  `RowProvider`/DB-API source, config/mapping to builders, snapshot semantics,
  `plan()` vs `run()`, cross-run idempotency via the persistent ledger, evidence.
- **usage/llm-extraction.md:** config-driven extraction — document/chunk source,
  `ExtractorConfig`, injected `CompletionClient` (+ replay client for determinism),
  first-class evidence + provenance, honest nondeterministic dry-run.
- **concepts.md:** Candidate variants; `CandidateSink`; the ledger (processing
  state, revoke = logical, erase = logical + hash tombstone); evidence registry
  (PRESENT/ABSENT/ERROR, dangling refs raise); `semantic_key`/identity;
  determinism (`FixedClock` + `DeterministicIdStrategy`).
- **api.md:** curated import map — `IngestPipeline`, the builders,
  `CandidateSink`, `SqliteCandidateLedger`, `SqliteEvidenceRegistry`,
  `kgis.structured.StructuredSyncConfig`, `kgis.extraction.ExtractionPipeline`,
  `kg_eval` entry points; where each lives.

### Delivery wiring
- **Manifest** (`docs-site/manifest.json`) — `format: html`, `section: projects`,
  `visibility: public`, `path: index.html` (resolves inside the built `dist/`),
  no `schema_version` (forbidden unless `data`), `additionalProperties:false`-safe.
- **Publish** — a new `agentic-kgis` GitHub Action job (`.github/workflows/`)
  that builds the docs (`mkdocs build`) and calls
  `uses: djjay0131/website/contract/publish@main` with WIF creds (`id-token:
  write`, `GCP_*` vars), uploading `docs-site/dist` + manifest to `sources/kgis/`.
  Exact action inputs verified against `website/contract/publish/action.yml`
  during implementation.
- **Local + CI gate** — `node <website>/contract/validate-manifest.mjs --dist
  docs-site/dist --source kgis` must pass before pushing.
- **Automated base-path link-check (CI)** — after `mkdocs build`, a CI step serves
  `docs-site/dist` under `/projects/kgis/kgis-docs/` and fails on any 404 or
  absolute in-site URL (e.g. `linkchecker`/a small script). This makes AC-3
  repeatable so a future docs edit cannot silently ship broken links/assets.
- **Owner prerequisite** — provision the `kgis` satellite (Terraform in
  `website/infra`). Nothing publishes until this exists; the docs + manifest +
  action can be built and validated locally in the meantime.

## Sample Implementation

`docs-site/mkdocs.yml` (base-path-safe config is the load-bearing part):
```yaml
site_name: KGIS Documentation
site_url: https://jason.cusati.us/projects/kgis/kgis-docs/
docs_dir: content
site_dir: dist
use_directory_urls: false      # emit *.html; rely on MkDocs relative links so the
                               # whole site works served under /projects/kgis/kgis-docs/
theme:
  name: material
  features: [navigation.sections, navigation.top, content.code.copy]
markdown_extensions: [admonition, pymdownx.superfences, toc]
nav:
  - What is KGIS: index.md
  - Why KGIS: why.md
  - Architecture: architecture.md
  - Using KGIS:
      - Quickstart: usage/quickstart.md
      - Structured sync: usage/structured-sync.md
      - LLM extraction: usage/llm-extraction.md
  - Concepts: concepts.md
  - API basics: api.md
```

`docs-site/manifest.json` (contract-valid):
```json
{ "source": "kgis", "manifest_version": "1", "published": "2026-09-17T00:00:00Z",
  "items": [ {
    "slug": "kgis-docs", "title": "KGIS Documentation",
    "section": "projects", "format": "html", "path": "index.html",
    "visibility": "public", "date": "2026-09-17",
    "summary": "What KGIS is, why it exists, its architecture, and how to use it.",
    "tags": ["kgis", "knowledge-graph", "ingestion"] } ] }
```

`pyproject.toml` docs extra + build:
```toml
[project.optional-dependencies]
docs = ["mkdocs-material>=9"]
# build: uv run --extra docs mkdocs build -f docs-site/mkdocs.yml
```

## Edge Cases & Error Handling

### Served under a sub-path (`/projects/kgis/kgis-docs/`)
- **Scenario**: an absolute asset/link (`/style.css`, `/architecture/`) 404s on
  the hub because the site is mounted under a prefix, not the domain root.
- **Behavior**: use MkDocs relative links + `use_directory_urls:false`; no absolute
  in-site URLs; `site_url` set to the mount path.
- **Test**: the automated CI link-check builds the site, serves it under the
  `/projects/kgis/kgis-docs/` sub-path, and fails on any 404 or absolute in-site
  URL (AC-3) — repeatable, not a manual click-through.

### Manifest rejected by the contract
- **Scenario**: an extra/misspelled field, a `schema_version` on a non-`data`
  item, a `section`/`format` outside its set, a `path` escaping `dist/`.
- **Behavior**: hard validation error at publish time and again at hub build.
- **Test**: `validate-manifest.mjs --dist docs-site/dist --source kgis` passes in
  CI before the publish step runs; a deliberately-broken manifest fixture fails it.

### Satellite not yet provisioned (owner prerequisite missing)
- **Scenario**: publish action runs before the `kgis` source + WIF exist.
- **Behavior**: the publish step fails on auth/permission; docs are not lost — the
  built site + validated manifest are green locally.
- **Test**: keep the publish job gated (manual/`workflow_dispatch` or a branch
  condition) until the owner confirms provisioning; document the enable step.

### Docs drift from the code
- **Scenario**: API examples in the docs stop matching the shipped API.
- **Behavior**: quickstart/usage code snippets are kept minimal and, where cheap,
  mirror real tests; a follow-up option is to doctest/execute snippets in CI.
- **Test**: on release, re-run the quickstart snippet against the current package.

### Hub renders md/mdx later
- **Scenario**: the hub gains a native `sources` md renderer.
- **Behavior**: no action required; the `html` site keeps working. Migration to
  native md would be a separate, optional change.

## Acceptance Criteria

### AC-1: Docs cover the four required areas
- **Given** the built site
- **When** a reader opens it
- **Then** there are dedicated pages for **what**, **why**, **architecture**, and
  **how-to-use** (quickstart + structured-sync + LLM-extraction), plus concepts
  and API basics, navigable from the sidebar.

### AC-2: Contract-valid manifest
- **Given** `docs-site/manifest.json` and a built `docs-site/dist`
- **When** `validate-manifest.mjs --dist docs-site/dist --source kgis` runs
- **Then** it exits 0 (section `projects`, format `html`, no `schema_version`,
  `additionalProperties:false`-clean, `path` inside `dist/`).

### AC-3: Base-path-safe build (automated)
- **Given** `docs-site/dist` served under `/projects/kgis/kgis-docs/`
- **When** the CI link-check step runs against the built site
- **Then** it reports **no 404s and no absolute in-site URLs**, and fails the
  build if any appear (not a manual click-through).

### AC-4: Publish wiring present and gated
- **Given** the `agentic-kgis` repo
- **When** the docs build + validate steps run in CI
- **Then** they pass, and the publish step (WIF → `sources/kgis/`) is wired but
  gated until the owner provisions the satellite.

### AC-5: Layered audience + accurate content
- **Given** the overview pages vs the usage pages
- **When** reviewed
- **Then** overview reads for a general/technical audience while usage pages are
  concrete for integrators, and all technical claims match the shipped code and
  ADRs (no bare `Label:key`, `CandidateSink`-only writes, separate confidence
  axes, logical erasure, etc.).

## Technical Notes

- **Affected repos:** `agentic-kgis` (new `docs-site/`, `pyproject` docs extra,
  publish workflow, `.gitignore` for `docs-site/dist`). `website` only via the
  owner-only satellite provisioning (out of this feature's scope).
- **Patterns to follow:** the hub's `phd-milestones` `format: html` example;
  the repo's governed workflow (branch → draft PR → owner merges); CRLF-clean
  content-only commits.
- **No `kg_contracts` change**, no hub contract change — this is additive.
- **Governance:** website changes (if any nav surfacing is later wanted) are
  separate owner-reviewed PRs on `website`; this feature stays in `agentic-kgis`.

## Dependencies

- **Owner:** provision the `kgis` satellite (Terraform in `website/infra`:
  service account, WIF provider entry for `djjay0131/agentic-kgis`, prefix-scoped
  IAM to `sources/kgis/`). Hard blocker for actual publish; not for building the
  docs.
- **Tooling:** `mkdocs-material` (new docs extra); Node available in CI for the
  `validate-manifest.mjs` gate.
- **Hub:** the `format: html` verbatim-serve path (exists today).

## Resolved Decisions (dual-persona review)

- **Look & feel:** ship verbatim `format: html` with **lightly-themed Material**
  to match the site — NOT the larger native-md hub integration (rejected as
  out-of-scope for now; would need hub code + an ADR).
- **Drift:** **living docs** — lean, reviewed per release, ADRs/spec as source of
  truth; CI snippet execution (doctest) is **deferred**, not adopted now.
- **Link safety:** **automated CI link-check** under the sub-path (AC-3), not a
  manual click-through.
- **Discoverability:** **yes** — add a KGIS card to the hub **Projects index** via
  a separate **owner-reviewed PR on `website`** (see Follow-ups). Direct URL works
  regardless; the card makes it listed.

## Follow-ups (separate, owner-owned)

- **Satellite provisioning** (Terraform in `website/infra`) — hard prerequisite to
  actually publish; owner-only. (See Dependencies.)
- **Projects-index card** — a small owner PR on `website` editing
  `site/src/pages/projects/index.astro` to list KGIS. Optional top-level nav entry
  in `Base.astro` if broader visibility is wanted later.

## Open Questions (deferred to implementation)

- Exact public slug: `/projects/kgis/kgis-docs/` (mirrors the `phd-milestones`
  example) vs a cleaner `/projects/kgis/` — settle when the satellite slug is set.
- Precise CI link-check tool (`linkchecker` vs a small custom script) — pick during
  implementation; behavior (fail on 404/absolute URL) is fixed by AC-3.
