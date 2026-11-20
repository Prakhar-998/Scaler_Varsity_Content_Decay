"""Turn build() output into plain tables (header + rows) for any writer."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

PREFIX = "https://www.interviewbit.com/varsity/blog/"

REFRESH_INPUT_COLS = ["Page URL", "Refresh date (YYYY-MM-DD)", "Type (light / rewrite)", "Owner", "Notes"]
REFRESH_INPUT_KEYS = ["page", "refresh_date", "type", "owner", "notes"]


def _clean(v):
    if v is None:
        return ""
    if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
        return ""
    if isinstance(v, (np.floating,)):
        return "" if np.isnan(v) else round(float(v), 2)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float):
        return round(v, 2)
    return v


def _rows(df: pd.DataFrame, cols: list[str]) -> list[list]:
    return [[_clean(v) for v in row] for row in df[cols].itertuples(index=False, name=None)]


def slug(url: str) -> str:
    return url.replace(PREFIX, "/") if url.startswith(PREFIX) else url


def trajectory(out: dict, daily_tab: str | None, n_days: int) -> tuple[list, list]:
    t = out["trajectory"].copy()
    t["slug"] = t["page"].map(slug)
    spec = [
        ("Page", "slug"), ("URL", "page"), ("Tier (relative)", "tier"), ("Volume tier", "volume_tier"),
        ("Trend 30d", "trend"), ("Trend 14d", "trend_short"),
        ("Clicks/day 7d", "clicks_per_day_7d"), ("Clicks/day 14d", "clicks_per_day_14d"),
        ("Clicks/day 30d", "clicks_per_day_30d"), ("Clicks/day 60d", "clicks_per_day_60d"),
        ("Clicks Δ% 7d", "clicks_change_pct_7d"), ("Clicks Δ% 14d", "clicks_change_pct_14d"),
        ("Clicks Δ% 30d", "clicks_change_pct_30d"),
        ("Slope %/day 7d", "clicks_slope_pct_7d"), ("Slope %/day 14d", "clicks_slope_pct_14d"),
        ("Slope %/day 30d", "clicks_slope_pct_30d"), ("Slope %/day 60d", "clicks_slope_pct_60d"),
        ("Impr/day 7d", "impr_per_day_7d"), ("Impr/day 30d", "impr_per_day_30d"),
        ("Impr Δ% 14d", "impr_change_pct_14d"), ("CTR 30d", "ctr_30d"),
        ("Avg position 14d", "position_14d"), ("First seen", "first_seen"), ("Age (days)", "age_days"),
    ]
    header = [h for h, _ in spec]
    rows = _rows(t, [c for _, c in spec])
    if daily_tab:
        header.insert(1, f"Clicks, last {n_days} days")
        last_col = _col_letter(1 + n_days)  # Daily tab: A = URL, B.. = days
        for i, r in enumerate(rows):
            url = r[1]
            r.insert(1, f"=IFERROR(SPARKLINE(INDEX('{daily_tab}'!B:{last_col},MATCH(\"{url}\",'{daily_tab}'!A:A,0),0)),\"\")")
    return header, rows


def flags(out: dict) -> tuple[list, list]:
    f = out["flags"].copy()
    f["slug"] = f["page"].map(slug)
    spec = [("Page", "slug"), ("Flag", "flag"), ("Est. clicks/month at stake", "monthly_clicks_at_stake"),
            ("Why", "detail"), ("Tier", "tier"), ("Trend 30d", "trend"), ("Clicks/day 30d", "clicks_per_day_30d"),
            ("Impr/day 14d", "impr_per_day_14d"), ("Avg position 14d", "position_14d"), ("URL", "page")]
    return [h for h, _ in spec], _rows(f, [c for _, c in spec]) if len(f) else []


def scope(scope_df: pd.DataFrame, month: str) -> tuple[list, list]:
    s = scope_df.copy()
    s["slug"] = s["page"].map(slug)
    s["month"] = month
    spec = [("Month", "month"), ("Rank", "rank"), ("Page", "slug"), ("Why", "reasons"),
            ("Est. clicks/month at stake", "monthly_clicks_at_stake"), ("Recommended action", "recommended_action"),
            ("Tier", "tier"), ("Trend 30d", "trend"), ("Clicks/day 30d", "clicks_per_day_30d"),
            ("Impr/day 14d", "impr_per_day_14d"), ("Avg position 14d", "position_14d"),
            ("Status", "status"), ("Owner", "owner"), ("URL", "page")]
    return [h for h, _ in spec], _rows(s, [c for _, c in spec]) if len(s) else []


def refresh_log(res: pd.DataFrame | None, n: int) -> tuple[list, list]:
    header = REFRESH_INPUT_COLS + [f"Clicks {n}d before", f"Clicks {n}d after", "Change %", "Result (auto)"]
    if res is None or res.empty:
        return header, []
    cols = REFRESH_INPUT_KEYS + [f"clicks_{n}d_before", f"clicks_{n}d_after", "change_pct", "result"]
    return header, _rows(res, cols)


def daily(out: dict, n_days: int) -> tuple[list, list]:
    c = out["daily_clicks"].iloc[:, -n_days:]
    header = ["URL"] + [d.isoformat() for d in c.columns]
    rows = [[url] + [_clean(v) for v in vals] for url, vals in zip(c.index, c.to_numpy())]
    return header, rows


def summary(out: dict, run_date: date) -> list[list]:
    t, f = out["trajectory"], out["flags"]
    dc = out["daily_clicks"]
    tot = dc.sum(axis=0)

    def tot_window(w, offset=0):
        return float(tot.iloc[len(tot) - w - offset: len(tot) - offset].sum())

    rows = [["Varsity Content Health"], [],
            ["Run date", run_date.isoformat()], ["GSC data through", out["end"].isoformat()],
            ["Articles tracked", len(t)], []]
    rows.append(["Blog clicks (articles)", "Last window", "Prior window", "Change %"])
    for w in (7, 14, 30):
        cur, prev = tot_window(w), tot_window(w, w)
        rows.append([f"{w} days", int(cur), int(prev), round((cur / prev - 1) * 100, 1) if prev else ""])
    rows += [[], ["Trend 30d", "Articles"]] + [[k, int(v)] for k, v in t["trend"].value_counts().items()]
    rows += [[], ["Tier", "Articles"]] + [[k, int(v)] for k, v in t["tier"].value_counts().items()]
    vt = t["volume_tier"][t["volume_tier"] != ""].value_counts()
    rows += [[], ["Volume tier (30/50/100 clicks/day)", "Articles"]]
    rows += [[k, int(v)] for k, v in vt.items()] or [["None yet", 0]]
    rows += [[], ["Flag", "Articles"]] + ([[k, int(v)] for k, v in f["flag"].value_counts().items()] or [["None", 0]])

    mover = t[t["age_days"] >= 14].copy()
    mover["d"] = mover["clicks_per_day_7d"] - (mover["clicks_14d"] - mover["clicks_7d"]) / 7
    rows += [[], ["Biggest movers (clicks/day, last 7d vs the 7d before)", "Change", "Clicks/day 7d"]]
    for _, r in mover.sort_values("d", ascending=False).head(5).iterrows():
        rows.append([slug(r["page"]), round(r["d"], 2), round(r["clicks_per_day_7d"], 2)])
    for _, r in mover.sort_values("d").head(5).iterrows():
        rows.append([slug(r["page"]), round(r["d"], 2), round(r["clicks_per_day_7d"], 2)])
    return [[_clean(v) for v in r] for r in rows]


def _col_letter(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s
