"""`Clock` exists so the pipeline never reads ambient time. These tests pin
the two properties the rest of the sprint depends on: `FixedClock` does not
move, and elapsed time is measured monotonically rather than by subtracting
wall clocks.
"""

from datetime import UTC, datetime

import pytest

from kgis.clock import FixedClock, SystemClock

NOW = datetime(2026, 7, 14, tzinfo=UTC)


class TestSystemClock:
    def test_now_is_timezone_aware(self) -> None:
        assert SystemClock().now().tzinfo is not None

    def test_monotonic_never_goes_backwards(self) -> None:
        clock = SystemClock()
        assert clock.monotonic() <= clock.monotonic()


class TestFixedClock:
    def test_now_does_not_move(self) -> None:
        clock = FixedClock(NOW)
        assert clock.now() == clock.now() == NOW

    def test_default_run_measures_zero_elapsed(self) -> None:
        """Byte-identical replay reports depend on this."""
        clock = FixedClock(NOW)
        start, end = clock.monotonic(), clock.monotonic()
        assert end - start == 0.0

    def test_tick_seconds_advances_monotonic_per_call(self) -> None:
        clock = FixedClock(NOW, tick_seconds=0.5)
        assert [clock.monotonic() for _ in range(3)] == [0.0, 0.5, 1.0]

    def test_advance_moves_wall_time_only(self) -> None:
        clock = FixedClock(NOW)
        clock.advance(60)
        assert clock.now() == datetime(2026, 7, 14, 0, 1, tzinfo=UTC)

    def test_naive_instant_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            FixedClock(datetime(2026, 7, 14))  # noqa: DTZ001
