# Active Context — agentic-kgis

Update 2026-07-10: External design review (ChatGPT) dispositioned
(chief-reviewer-checked, owner-approved) → **spec v2** + ADRs 0006–0010 +
amendments to 0002/0004/0005 (0003 superseded in part) + delta amendment,
all on PR #1. Key changes: candidate ledger / canonical graph / derived
projections separation with curation epochs; 9-variant typed candidate
union + CandidateScores; Evidence first-class (present/absent/error);
immutable identity IDs + namespaced aliases; ER = calibrated matcher +
bounded LLM adviser (debate → eval arm); bitemporal contracts; kg_eval
third package; five-phase adoption (VTTSI reference → baseball → traffic
shadow → research retrofit → construction). Plan sequence now 7 plans
(5a/5b split for ER). NEXT: owner merges PR #1, then Plan 1 rewrite
against contracts v2 (the 2026-07-09 Plan 1 is obsolete — do not execute).

Prior state (2026-07-09):

- Design spec approved and committed:
  docs/superpowers/specs/2026-07-09-kgis-kgcs-design.md
- Plan 1 written (bootstrap + kg_contracts):
  docs/superpowers/plans/2026-07-09-01-bootstrap-and-contracts.md —
  NOT yet executed. Plans 2–5 to follow (gate, ingestion, curation plane,
  registry).
- Governance adopted (agentic-governance v0.1): delta, ADRs 0001–0005
  back-filled, .github surface, CONTRIBUTING. From now on:
  Issue → Branch → Draft PR → Review → Merge; no direct commits to main.
- NEXT BEFORE IMPLEMENTATION: ChatGPT feedback review cycle on the design
  spec (first governed review); amendments may update the spec/ADRs, then
  Plan 1 executes.

Open questions: extractor config format (decided in Plan 3); IngestJob
protocol shape (deferred to Plan 3 by design).
