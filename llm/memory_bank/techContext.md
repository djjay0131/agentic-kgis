# Tech Context — agentic-kgis

Python >=3.11, Pydantic v2 (only runtime dep of kg_contracts), pytest,
ruff, mypy --strict, hatchling. src/ layout; venv at .venv.

Two packages, one distribution "agentic-kgis": src/kg_contracts, src/kgis.
Sibling repo agentic-kgcs depends on this distribution.
Graph backends (injected, not dependencies here): Spanner Graph, Neo4j,
in-memory reference adapters (kg_contracts.testing.memory —
`MemoryCandidateSink`, `MemoryGraphStore`).
GitHub: djjay0131/agentic-kgis (private). `gh` is not on PATH in this
environment; the Windows CLI lives at `/mnt/c/Program Files/GitHub CLI/gh.exe`
and needs Windows-style paths for `--body-file`. Python is driven via `uv run`
(`uv sync --extra dev` to provision pytest/ruff/mypy).
