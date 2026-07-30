from __future__ import annotations

from datetime import datetime
from unittest import TestCase

from scripts.generate_profile_stats import (
    LOCAL_TZ,
    build_month_labels,
    collect_language_totals,
    count_commit_dates_by_month,
    month_bins,
    month_shift,
    validate_username,
)


class ValidateUsernameTests(TestCase):
    def test_accepts_valid_username(self) -> None:
        self.assertEqual(validate_username("MusammatA"), "MusammatA")

    def test_rejects_invalid_username(self) -> None:
        with self.assertRaises(ValueError):
            validate_username("../bad-name")


class MonthHelpersTests(TestCase):
    def test_month_shift_crosses_year_boundaries(self) -> None:
        self.assertEqual(month_shift(2026, 1, -1), (2025, 12))
        self.assertEqual(month_shift(2026, 12, 1), (2027, 1))

    def test_month_bins_uses_reference_date(self) -> None:
        reference = datetime(2026, 7, 30, tzinfo=LOCAL_TZ)
        self.assertEqual(
            month_bins(4, reference=reference),
            [(2026, 4), (2026, 5), (2026, 6), (2026, 7)],
        )

    def test_build_month_labels(self) -> None:
        self.assertEqual(build_month_labels([(2026, 1), (2026, 2)]), ["Jan", "Feb"])


class AggregationTests(TestCase):
    def test_collect_language_totals(self) -> None:
        totals = collect_language_totals(
            [
                {"Python": 100, "HTML": 50},
                {"Python": 25, "CSS": 10},
            ]
        )
        self.assertEqual(totals, [("Python", 125), ("HTML", 50), ("CSS", 10)])

    def test_count_commit_dates_by_month(self) -> None:
        bins = [(2026, 6), (2026, 7)]
        commits = [
            datetime(2026, 6, 10, tzinfo=LOCAL_TZ),
            datetime(2026, 6, 15, tzinfo=LOCAL_TZ),
            datetime(2026, 7, 1, tzinfo=LOCAL_TZ),
        ]
        self.assertEqual(count_commit_dates_by_month(commits, bins), [2, 1])
