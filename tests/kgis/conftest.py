"""Fixtures for the pipeline and invariant suites.

Shared *helpers* live in `scenarios.py` so they can be imported directly;
this file holds only pytest fixtures.
"""

import pytest

from kg_contracts.testing.memory import MemoryCandidateSink


@pytest.fixture
def sink() -> MemoryCandidateSink:
    return MemoryCandidateSink()
