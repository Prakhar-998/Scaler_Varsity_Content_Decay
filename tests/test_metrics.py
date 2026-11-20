from datetime import date, timedelta

import pandas as pd
import yaml
from pathlib import Path

from health import metrics

CFG = yaml.safe_load(open(Path(__file__).resolve().parent.parent / "config.yaml"))
P = "https://www.interviewbit.com/varsity/blog/"
END = date(2026, 11, 15)


def rows(slug, days, clicks, impr, pos=5.0):
    """clicks/impr: callables of day offset (0 = oldest)."""
    return [{"date": (END - timedelta(days=days - 1 - i)).isoformat(), "page": P + slug,
             "clicks": clicks(i), "impressions": impr(i), "position": pos} for i in range(days)]


def run(data, log=None):
    df = metrics.prepare(pd.DataFrame(data), CFG)
    return metrics.build(df, CFG, END, log)


def test_url_normalised_and_archives_dropped():
    d = rows("a", 5, lambda i: 1, lambda i: 10)
    d += [{"date": END.isoformat(), "page": P + "a?utm=x", "clicks": 1, "impressions": 1, "position": 3}]
    d += [{"date": END.isoformat(), "page": P + "tag/x/", "clicks": 9, "impressions": 9, "position": 3}]
    d += [{"date": END.isoformat(), "page": P, "clicks": 9, "impressions": 9, "position": 3}]
    t = run(d)["trajectory"]
    assert list(t["page"]) == [P + "a/"]
    assert t.iloc[0]["clicks_7d"] == 6


def test_missing_days_are_zero_after_first_seen_only():
    d = [r for r in rows("a", 20, lambda i: 2, lambda i: 20) if int(r["date"][-2:]) % 2 == 0]
    t = run(d)["trajectory"].iloc[0]
    assert t["age_days"] == 20 or t["age_days"] == 19
    assert 0.9 < t["clicks_per_day_14d"] < 1.1  # every other day missing -> zero, avg ~1


def test_rising_and_declining_labels():
    up = rows("up", 90, lambda i: 1 + i * 0.5, lambda i: 100 + i * 10)
    down = rows("down", 90, lambda i: max(60 - i * 0.6, 0), lambda i: 1000 - i * 8)
    t = run(up + down)["trajectory"].set_index("page")
    assert t.loc[P + "up/", "trend"] == "Rising"
    assert t.loc[P + "down/", "trend"] == "Declining"
    assert t.loc[P + "up/", "clicks_slope_14d"] > 0


def test_decay_flag_and_refresh_skip():
    # 40/day for the first 62 days, then 10/day -> big drop on the 28d vs prior 28d
    d = rows("decay", 90, lambda i: 40 if i < 62 else 10, lambda i: 800)
    f = run(d)["flags"]
    assert "Decay" in set(f["flag"])
    log = pd.DataFrame([{"page": P + "decay/", "refresh_date": (END - timedelta(days=10)).isoformat(),
                         "type": "light", "owner": "", "notes": ""}])
    f2 = run(d, log)["flags"]
    assert "Decay" not in set(f2["flag"])


def test_low_ctr_flag_kiro_pattern():
    d = rows("kiro", 12, lambda i: 0 if i % 4 else 1, lambda i: 50 + i * 25, pos=6.5)
    f = run(d)["flags"]
    assert (f["flag"] == "Low CTR for position").any()


def test_tiers_relative_and_absolute():
    d = []
    for k in range(20):
        d += rows(f"p{k}", 40, (lambda k: lambda i: k)(k), lambda i: 1000)
    d += rows("big", 40, lambda i: 120, lambda i: 5000)
    t = run(d)["trajectory"].set_index("page")
    assert t.loc[P + "big/", "volume_tier"] == "100+/day"
    assert t.loc[P + "big/", "tier"] == "Top 10%"
    assert t.loc[P + "p0/", "tier"] == "No clicks"
    assert t.loc[P + "p5/", "volume_tier"] == ""


def test_refresh_before_after():
    rd = END - timedelta(days=30)
    d = rows("r", 90, lambda i: 2 if (END - timedelta(days=89 - i)) < rd else 4, lambda i: 100)
    log = pd.DataFrame([{"page": P + "r", "refresh_date": rd.isoformat(), "type": "light", "owner": "", "notes": ""}])
    res = run(d, log)["refresh"].iloc[0]
    assert res["clicks_28d_before"] == 56 and res["clicks_28d_after"] == 112
    assert res["result"] == "Recovered / grew"
