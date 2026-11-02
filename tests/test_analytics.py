"""
Unit tests for the pandas calculations in analytics_service.

These feed a small, hand-built set of rows (shaped exactly like rows from the Oracle view
V_DAILY_ACTIVITY_DETAILS) into the pandas functions, so the expected numbers can be
verified by hand. They do NOT need Oracle. Oracle-backed tests are in test_api.py.
"""
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from backend import analytics_service as stats

D1, D2, D3 = date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)


def row(i, name, kind, day, minutes):
    return {"activity_id": i, "activity_name": name, "activity_type": kind,
            "activity_date": datetime.combine(day, datetime.min.time()), "minutes_in_day": minutes}


# Day1: study 90+60, sleep 60 (night 1, first part). Day2: sleep 390 (second part), study 120, food 45.
ROWS = [
    row(1, "Maths", "STUDY", D1, 90), row(2, "Physics", "STUDY", D1, 60),
    row(3, "Sleep", "SLEEP", D1, 60), row(3, "Sleep", "SLEEP", D2, 390),
    row(4, "Coding", "STUDY", D2, 120), row(5, "Lunch", "FOOD", D2, 45),
]


def test_dataframe_creation():
    df = stats.build_dataframe(ROWS)
    assert list(df.columns) == stats.COLUMNS
    assert len(df) == 6
    assert str(df["minutes_in_day"].dtype) == "float64"
    assert pd.api.types.is_datetime64_any_dtype(df["activity_date"])


def test_daily_study_groupby_and_zero_fill():
    df = stats.build_dataframe(ROWS)
    series = stats.daily_study_series(df, D1, D3)
    assert list(series.values) == [150.0, 120.0, 0.0]          # D3 has no study -> 0


def test_daily_analysis_mean_and_stats():
    result = stats.daily_analysis(stats.build_dataframe(ROWS), D1, D3)
    assert result["total_study_minutes"] == 270.0
    assert result["average_study_minutes_per_day"] == 90.0     # 270 / 3 days
    assert result["average_study_minutes_on_study_days"] == 135.0  # 270 / 2 days
    assert result["days_studied"] == 2
    assert result["best_day"] == "2026-01-01"
    assert result["descriptive_statistics"]["count"] == 3.0
    assert result["descriptive_statistics"]["max"] == 150.0


def test_category_aggregation_sum_mean_count():
    result = stats.category_analysis(stats.build_dataframe(ROWS))
    by_type = {c["activity_type"]: c for c in result["categories"]}
    assert by_type["STUDY"]["total_minutes"] == 270.0
    assert by_type["STUDY"]["average_minutes_per_day"] == 135.0   # mean of daily totals 150 and 120
    assert by_type["STUDY"]["days_recorded"] == 2
    assert by_type["STUDY"]["activity_count"] == 3
    assert by_type["SLEEP"]["total_minutes"] == 450.0
    assert by_type["SLEEP"]["activity_count"] == 1                 # one night, two day-slices
    assert by_type["TRAVEL"]["total_minutes"] == 0.0               # unused category still listed
    assert result["most_time_consuming_category"] == "SLEEP"
    assert result["total_recorded_minutes"] == 765.0               # 270 + 450 + 45
    assert round(sum(c["percentage"] for c in result["categories"]), 1) == 100.0


def test_daily_total_is_capped_at_24_hours():
    rows = [row(1, "Bad data", "OTHER", D1, 1000), row(2, "More bad data", "STUDY", D1, 1000)]
    totals = stats.daily_totals(stats.build_dataframe(rows))
    assert totals.loc[pd.Timestamp(D1), "total_minutes"] == 1440.0


def test_weekly_analysis():
    df = stats.build_dataframe(ROWS)
    result = stats.weekly_analysis(df, D3)
    assert result["weekly_total_minutes"] == 270.0
    assert len(result["days"]) == 7
    assert result["weeks"][0]["minutes"] == 270.0
    assert [w["minutes"] for w in result["weeks"][1:]] == [0.0, 0.0, 0.0]


def test_empty_dataframe_is_handled():
    df = stats.build_dataframe([])
    assert stats.daily_analysis(df, D1, D3)["total_study_minutes"] == 0.0
    cat = stats.category_analysis(df)
    assert cat["most_time_consuming_category"] is None
    assert cat["total_recorded_minutes"] == 0.0
    assert stats.weekly_analysis(df, D3)["weekly_total_minutes"] == 0.0


def test_csv_export_all_kinds(tmp_path, monkeypatch):
    monkeypatch.setattr(stats, "REPORTS_DIR", tmp_path)
    rows = ROWS + [row(9, "=HYPERLINK(\"x\")", "OTHER", D2, 10)]   # formula-injection attempt
    df = stats.build_dataframe(rows)
    for kind in ("detail", "daily", "category"):
        path, name = stats.export_csv(df, kind, D1, D3)
        assert name.endswith(".csv") and Path(path).exists()
        back = pd.read_csv(path)
        assert len(back) > 0
    detail = pd.read_csv(stats.export_csv(df, "detail", D1, D3)[0])
    assert list(detail.columns) == ["activity_date", "activity_id", "activity_name", "activity_type", "minutes"]
    assert detail["activity_name"].str.startswith("=").sum() == 0   # neutralised
    daily = pd.read_csv(stats.export_csv(df, "daily", D1, D3)[0])
    assert len(daily) == 3 and "TOTAL" in daily.columns            # one row per day, zero-filled
