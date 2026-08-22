"""Reusable contract suite for `RowProvider` implementations (spec §10.2).

Subclass `RowProviderContract`, implement `make_provider()` over the canonical
fixture below, and every structured source — the reference SQLite one, plus any
Postgres/Spanner provider added later — is held to the same rules.

The rules that earn the suite are the two structured sync lives or dies on:
`test_snapshot_version_is_stable` (a re-opened snapshot over unchanged data
reports the same version, so `plan()`/`run()` can agree) and
`test_rows_are_ordered_by_key` (a stable order, so coordinates are stable).
"""

from __future__ import annotations

from kgis.structured.port import RowProvider

CANONICAL_ROWS: tuple[dict[str, object], ...] = (
    {"id": "1", "name": "Ada"},
    {"id": "2", "name": "Grace"},
    {"id": "3", "name": "Alan"},
)
"""The dataset every `RowProvider` implementation is tested against. Keyed on
`id`; `make_provider()` must expose `key_fields == ("id",)`."""


class RowProviderContract:
    """Subclass and implement `make_provider()` (spec §10.2)."""

    def make_provider(self) -> RowProvider:
        """Return a provider over exactly `CANONICAL_ROWS`, keyed on `id`."""
        raise NotImplementedError

    def test_declares_id_as_key_field(self) -> None:
        assert self.make_provider().key_fields == ("id",)

    def test_reads_every_row(self) -> None:
        provider = self.make_provider()
        rows = list(provider.open_snapshot().rows(batch_size=500))
        assert [row["id"] for row in rows] == ["1", "2", "3"]

    def test_rows_are_ordered_by_key(self) -> None:
        """Order must be stable, so per-row coordinates are stable across runs."""
        provider = self.make_provider()
        first = [str(row["id"]) for row in provider.open_snapshot().rows(batch_size=500)]
        second = [str(row["id"]) for row in provider.open_snapshot().rows(batch_size=500)]
        assert first == second == sorted(first)

    def test_batch_size_does_not_change_the_row_sequence(self) -> None:
        """Batching is transport only (batch-of-one constraint)."""
        provider = self.make_provider()
        one = [row["id"] for row in provider.open_snapshot().rows(batch_size=1)]
        many = [row["id"] for row in provider.open_snapshot().rows(batch_size=500)]
        assert one == many

    def test_snapshot_version_is_stable_over_unchanged_data(self) -> None:
        """The honesty anchor: unchanged data → identical version token."""
        provider = self.make_provider()
        assert provider.open_snapshot().version == provider.open_snapshot().version

    def test_invalid_batch_size_is_rejected(self) -> None:
        snapshot = self.make_provider().open_snapshot()
        try:
            list(snapshot.rows(batch_size=0))
        except ValueError:
            return
        raise AssertionError("batch_size=0 must raise ValueError")
