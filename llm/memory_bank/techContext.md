# Tech Context — agentic-kgis

Python >=3.11, Pydantic v2 (only runtime dep of kg_contracts), pytest,
ruff, mypy --strict, hatchling. src/ layout; venv at .venv.

Two packages, one distribution "agentic-kgis": src/kg_contracts, src/kgis.
Sibling repo agentic-kgcs depends on this distribution.
Graph backends (injected, not dependencies here): Spanner Graph, Neo4j,
in-memory reference store (kg_contracts.testing.memory_store).
GitHub: djjay0131/agentic-kgis (private).
