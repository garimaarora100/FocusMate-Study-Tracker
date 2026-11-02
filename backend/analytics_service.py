"""
pandas analysis of the activity data.

Flow:  Oracle view V_DAILY_ACTIVITY_DETAILS --fetch_all()--> list of dicts
       --> pandas DataFrame --> filter / groupby / aggregate / describe --> JSON or CSV

The view already splits overnight activities per calendar day, so every row here is
"minutes spent on one activity on one day".
"""
import re
from datetime import date, datetime, time, timedelta

import pandas as pd

from backend.database import BASE_DIR, fetch_all
from backend.schemas import CATEGORIES

MINUTES_PER_DAY = 1440
REPORTS_DIR = BASE_DIR / "reports"
COLUMNS = ["activity_id", "activity_name", "activity_type", "activity_date", "minutes_in_day"]


# --------------------------- 1. DataFrame creation ---------------------------
def build_dataframe(rows: list[dict]) -> pd.DataFrame:
    """Create a typed DataFrame from database rows (pure function: easy to unit-test)."""
    df = pd.DataFrame(rows, columns=COLUMNS)
    df["activity_date"] = pd.to_datetime(df["activity_date"]).dt.normalize()
    df["minutes_in_day"] = df["minutes_in_day"].astype(float)
    return df


def load_activity_dataframe(start: date, end: date) -> pd.DataFrame:
    rows = fetch_all(
        """SELECT activity_id, activity_name, activity_type, activity_date, minutes_in_day
             FROM v_daily_activity_details
            WHERE activity_date BETWEEN :start_day AND :end_day
              AND minutes_in_day > 0""",
        {
            "start_day": datetime.combine(start, time.min),
            "end_day": datetime.combine(end, time.min),
        },
    )
    return build_dataframe(rows)


def _clean(value):
    """NaN -> None and numpy numbers -> plain floats so the result is JSON-safe."""
    return None if pd.isna(value) else round(float(value), 2)


def describe_series(series: pd.Series) -> dict:
    """6. Descriptive statistics: count, mean, std, min, quartiles, max."""
    if series.empty:
        return {}
    return {name: _clean(value) for name, value in series.describe().items()}


# --------------------------- 2. Daily study analysis -------------------------
def daily_study_series(df: pd.DataFrame, start: date, end: date) -> pd.Series:
    """Study minutes for EVERY day in [start, end] (days with no study = 0)."""
    study = df[df["activity_type"] == "STUDY"]                       # filtering
    per_day = study.groupby("activity_date")["minutes_in_day"].sum()  # groupby + sum
    every_day = pd.date_range(start, end, freq="D")
    return per_day.reindex(every_day, fill_value=0.0).rename_axis("date")


def daily_analysis(df: pd.DataFrame, start: date, end: date) -> dict:
    series = daily_study_series(df, start, end)
    studied = series[series > 0]                                      # filtering
    best_day = series.idxmax() if studied.size else None
    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "days": [{"date": d.date().isoformat(), "minutes": round(float(m), 2)}
                 for d, m in series.items()],
        "total_study_minutes": _clean(series.sum()),
        "average_study_minutes_per_day": _clean(series.mean()),       # over all days in range
        "average_study_minutes_on_study_days": _clean(studied.mean()) if studied.size else 0.0,
        "days_studied": int(studied.size),
        "best_day": best_day.date().isoformat() if best_day is not None else None,
        "best_day_minutes": _clean(series.max()) if studied.size else 0.0,
        "descriptive_statistics": describe_series(series),
    }


# --------------------------- 3. Weekly study analysis ------------------------
def weekly_analysis(df: pd.DataFrame, today: date) -> dict:
    """Last 7 days plus 4 rolling 7-day buckets (week 0 = the most recent 7 days)."""
    last7_start = today - timedelta(days=6)
    last7 = daily_study_series(df, last7_start, today)

    study = df[df["activity_type"] == "STUDY"].copy()
    study["week_bucket"] = (pd.Timestamp(today) - study["activity_date"]).dt.days // 7
    buckets = (study[study["week_bucket"].between(0, 3)]
               .groupby("week_bucket")["minutes_in_day"].sum()
               .reindex(range(4), fill_value=0.0))
    weeks = []
    for bucket, minutes in buckets.items():
        week_end = today - timedelta(days=7 * int(bucket))
        weeks.append({
            "label": "This week (last 7 days)" if bucket == 0 else f"{bucket} week(s) earlier",
            "start_date": (week_end - timedelta(days=6)).isoformat(),
            "end_date": week_end.isoformat(),
            "minutes": round(float(minutes), 2),
        })
    return {
        "days": [{"date": d.date().isoformat(), "minutes": round(float(m), 2)}
                 for d, m in last7.items()],
        "weekly_total_minutes": _clean(last7.sum()),
        "daily_average_minutes": _clean(last7.mean()),
        "weeks": weeks,
    }


# --------------------------- 4. Category analysis ----------------------------
def daily_totals(df: pd.DataFrame) -> pd.DataFrame:
    """Per-day total of all categories, capped at 24 h (1440 min) as a safety net."""
    totals = df.groupby("activity_date").agg(
        total_minutes=("minutes_in_day", "sum"),
        entries=("activity_id", "count"),                              # count()
    )
    totals["total_minutes"] = totals["total_minutes"].clip(upper=MINUTES_PER_DAY)
    return totals


def category_frame(df: pd.DataFrame) -> pd.DataFrame:
    """One row per category: total, average per day, days recorded, activity count, %."""
    # Step 1: minutes per (day, category).
    per_day_type = df.groupby(["activity_date", "activity_type"], as_index=False)["minutes_in_day"].sum()
    # Step 2: aggregate those daily figures per category -> sum(), mean(), count().
    summary = per_day_type.groupby("activity_type").agg(
        total_minutes=("minutes_in_day", "sum"),
        average_minutes_per_day=("minutes_in_day", "mean"),
        days_recorded=("activity_date", "count"),
    )
    summary["activity_count"] = df.groupby("activity_type")["activity_id"].nunique()
    summary = summary.reindex(list(CATEGORIES))                        # keep every category
    summary = summary.fillna(0.0)
    grand_total = summary["total_minutes"].sum()
    summary["percentage"] = (summary["total_minutes"] / grand_total * 100) if grand_total else 0.0
    return summary.round(2)


def category_analysis(df: pd.DataFrame) -> dict:
    frame = category_frame(df)
    totals = daily_totals(df)
    total_recorded = float(totals["total_minutes"].sum()) if not totals.empty else 0.0
    top = frame["total_minutes"].idxmax() if frame["total_minutes"].max() > 0 else None
    categories = [
        {
            "activity_type": name,
            "total_minutes": float(row["total_minutes"]),
            "average_minutes_per_day": float(row["average_minutes_per_day"]),
            "days_recorded": int(row["days_recorded"]),
            "activity_count": int(row["activity_count"]),
            "percentage": float(row["percentage"]),
        }
        for name, row in frame.iterrows()
    ]
    return {
        "categories": categories,
        "most_time_consuming_category": top,
        "total_recorded_minutes": round(total_recorded, 2),
        "days_with_records": int(len(totals)),
        "daily_total_statistics": describe_series(totals["total_minutes"]) if not totals.empty else {},
    }


# --------------------------- 5. CSV export -----------------------------------
def _csv_safe(value):
    """Stop spreadsheet formula injection: prefix risky text cells with an apostrophe."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
        return "'" + value
    return value


def report_frame(df: pd.DataFrame, kind: str, start: date, end: date) -> pd.DataFrame:
    if kind == "detail":
        out = df.sort_values(["activity_date", "activity_id"]).copy()
        out["activity_date"] = out["activity_date"].dt.date
        out["activity_name"] = out["activity_name"].map(_csv_safe)
        return out.rename(columns={"minutes_in_day": "minutes"})[
            ["activity_date", "activity_id", "activity_name", "activity_type", "minutes"]
        ]
    if kind == "daily":
        pivot = df.pivot_table(index="activity_date", columns="activity_type",
                               values="minutes_in_day", aggfunc="sum", fill_value=0.0)
        pivot = pivot.reindex(columns=list(CATEGORIES), fill_value=0.0)
        pivot = pivot.reindex(pd.date_range(start, end, freq="D"), fill_value=0.0)
        pivot["TOTAL"] = pivot.sum(axis=1).clip(upper=MINUTES_PER_DAY)
        pivot.index = pivot.index.date
        pivot.index.name = "date"
        return pivot.round(2).reset_index()
    if kind == "category":
        return category_frame(df).reset_index().rename(columns={"activity_type": "category"})
    raise ValueError("kind must be detail, daily or category")


def export_csv(df: pd.DataFrame, kind: str, start: date, end: date) -> tuple[str, str]:
    """Write the report into /reports and return (file path, file name)."""
    REPORTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = re.sub(r"[^a-z0-9_.-]", "", f"focusmate_{kind}_{start}_{end}_{stamp}.csv")
    path = REPORTS_DIR / name
    report_frame(df, kind, start, end).to_csv(path, index=False)
    return str(path), name
