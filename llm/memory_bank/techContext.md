# Tech Context — agentic-kgis

Python >=3.11, Pydantic v2 (only runtime dep of kg_contracts), pytest,
ruff, mypy --strict, hatchling. src/ layout; venv at .venv.
ruff is pinned to 0.15.22 (via PR #20) so fresh envs lint reproducibly —
an unpinned ruff previously drifted and reported ~63 spurious findings.

Three packages, one distribution "agentic-kgis": src/kg_contracts, src/kgis,
src/kg_eval. The kgis ingestion modes (structured sync + LLM extraction), the
kg_eval harness, and the persistent registry land via the six backlog-execution
PRs (#15/#18/#19/#20/#21/#22); on `main` today kg_eval is still a stub.
Persistent state (candidate ledger, evidence registry, graph registry) is
SQLite-backed behind the frozen contract protocols; graph DB backends stay
injected. Sibling repo agentic-kgcs depends on this distribution.
Graph backends (injected, not dependencies here): Spanner Graph, Neo4j,
in-memory reference store (kg_contracts.testing.memory_store).
GitHub: djjay0131/agentic-kgis (private).
