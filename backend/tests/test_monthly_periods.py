"""Unit tests for _get_monthly_periods boundary correctness.

Covers 28-day February, 29-day February (leap year), 30-day months,
31-day months, and invalid input handling.
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from server import _get_monthly_periods


class TestGetMonthlyPeriodsBoundaries:
    """Verify exact Periode day boundaries for every month-length variant."""

    def _assert_periode_structure(self, periods):
        assert len(periods) == 4
        labels = [p["label"] for p in periods]
        assert labels == ["Periode 1", "Periode 2", "Periode 3", "Periode 4"]

    def _assert_fixed_boundaries(self, periods, month):
        p1, p2, p3, p4 = periods
        assert p1["start"] == f"{month}-01", "Periode 1 must start on day 1"
        assert p1["end"]   == f"{month}-07", "Periode 1 must end on day 7"
        assert p2["start"] == f"{month}-08", "Periode 2 must start on day 8"
        assert p2["end"]   == f"{month}-14", "Periode 2 must end on day 14"
        assert p3["start"] == f"{month}-15", "Periode 3 must start on day 15"
        assert p3["end"]   == f"{month}-21", "Periode 3 must end on day 21"
        assert p4["start"] == f"{month}-22", "Periode 4 must start on day 22"

    def test_28_day_february_non_leap(self):
        """February 2025 has 28 days; Periode 4 ends on day 28."""
        month = "2025-02"
        periods = _get_monthly_periods(month)
        self._assert_periode_structure(periods)
        self._assert_fixed_boundaries(periods, month)
        assert periods[3]["end"] == "2025-02-28", "Periode 4 must end on day 28 for a 28-day February"

    def test_29_day_february_leap_year(self):
        """February 2024 is a leap year with 29 days; Periode 4 ends on day 29."""
        month = "2024-02"
        periods = _get_monthly_periods(month)
        self._assert_periode_structure(periods)
        self._assert_fixed_boundaries(periods, month)
        assert periods[3]["end"] == "2024-02-29", "Periode 4 must end on day 29 for a 29-day February"

    def test_30_day_month(self):
        """April has 30 days; Periode 4 ends on day 30."""
        month = "2025-04"
        periods = _get_monthly_periods(month)
        self._assert_periode_structure(periods)
        self._assert_fixed_boundaries(periods, month)
        assert periods[3]["end"] == "2025-04-30", "Periode 4 must end on day 30 for a 30-day month"

    def test_31_day_month(self):
        """January has 31 days; Periode 4 ends on day 31."""
        month = "2025-01"
        periods = _get_monthly_periods(month)
        self._assert_periode_structure(periods)
        self._assert_fixed_boundaries(periods, month)
        assert periods[3]["end"] == "2025-01-31", "Periode 4 must end on day 31 for a 31-day month"

    def test_another_30_day_month(self):
        """June has 30 days; Periode 4 ends on day 30."""
        month = "2025-06"
        periods = _get_monthly_periods(month)
        self._assert_fixed_boundaries(periods, month)
        assert periods[3]["end"] == "2025-06-30"

    def test_another_31_day_month(self):
        """December has 31 days; Periode 4 ends on day 31."""
        month = "2025-12"
        periods = _get_monthly_periods(month)
        self._assert_fixed_boundaries(periods, month)
        assert periods[3]["end"] == "2025-12-31"


class TestGetMonthlyPeriodsInvalidInput:
    """Verify that malformed month strings raise ValueError."""

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            _get_monthly_periods("")

    def test_missing_separator_raises(self):
        with pytest.raises(ValueError):
            _get_monthly_periods("202501")

    def test_wrong_separator_raises(self):
        with pytest.raises(ValueError):
            _get_monthly_periods("2025/01")

    def test_month_zero_raises(self):
        with pytest.raises(ValueError):
            _get_monthly_periods("2025-00")

    def test_month_thirteen_raises(self):
        with pytest.raises(ValueError):
            _get_monthly_periods("2025-13")

    def test_non_numeric_raises(self):
        with pytest.raises(ValueError):
            _get_monthly_periods("abcd-ef")

    def test_none_raises(self):
        with pytest.raises((ValueError, AttributeError)):
            _get_monthly_periods(None)
