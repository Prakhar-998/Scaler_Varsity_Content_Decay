"""Pure computations: daily trajectory, trend windows, tiers, flags, monthly scope.

Input is a long DataFrame of GSC rows: date, page, clicks, impressions, position.
Nothing here talks to an API, so it is fully testable offline.
"""
from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import urlsplit, urlunsplit

import numpy as np
import pandas as pd


# ---------------------------------------------------------------- prep

def normalize_url(url: str) -> str:
    """Drop query/fragment and force a trailing slash so /x and /x/ merge."""
    p = urlsplit(url.strip())
    path = p.path if p.path.endswith("/") else p.path + "/"
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), path, "", ""))


def prepare(rows: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Normalise URLs, drop non-article pages, merge duplicates."""
    df = rows.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["page"] = df["page"].map(normalize_url)
    pc = cfg["pages"]
    df = df[df["page"].str.startswith(pc["include_prefix"])]
    for pat in pc.get("exclude_patterns", []):
        df = df[~df["page"].str.contains(pat, regex=False)]
    exact = {normalize_url(u) for u in pc.get("exclude_exact", [])}
    df = df[~df["page"].isin(exact)]
    df["pos_x_impr"] = df["position"].astype(float) * df["impressions"].astype(float)
    df = (df.groupby(["page", "date"], as_index=False)
            [["clicks", "impressions", "pos_x_impr"]].sum())
    return df


def daily_matrix(df: pd.DataFrame, end: date, days: int) -> dict[str, pd.DataFrame]:
    """Wide page x date matrices. Days before a page's first impression are NaN
    (page not live); days after with no GSC row are 0 (GSC omits zero rows)."""
    idx = pd.date_range(end - timedelta(days=days - 1), end).date
    out = {}
    for col in ("clicks", "impressions", "pos_x_impr"):
        m = df.pivot_table(index="page", columns="date", values=col, aggfunc="sum")
        out[col] = m.reindex(columns=idx)
    first_seen = df[df["impressions"] > 0].groupby("page")["date"].min()
    live = pd.DataFrame(
        {d: first_seen.reindex(out["clicks"].index) <= d for d in idx}, index=out["clicks"].index
    )
    for col in out:
        out[col] = out[col].fillna(0).where(live)
    out["first_seen"] = first_seen
    return out


# ---------------------------------------------------------------- windows

def _slope(values: np.ndarray) -> float:
    """OLS slope (units/day) over the non-NaN points."""
    y = values[~np.isnan(values)]
    if len(y) < 3:
        return np.nan
    x = np.arange(len(y), dtype=float)
    return float(np.polyfit(x, y, 1)[0])


def window_stats(m: dict, w: int) -> pd.DataFrame:
    """Stats for the last w days and the w days before it."""
    clicks, impr, pxi = m["clicks"], m["impressions"], m["pos_x_impr"]
    cur = slice(clicks.shape[1] - w, clicks.shape[1])
    prev = slice(clicks.shape[1] - 2 * w, clicks.shape[1] - w)

    def block(s):
        c, i, p = clicks.iloc[:, s], impr.iloc[:, s], pxi.iloc[:, s]
        live = c.notna().sum(axis=1)
        return c.sum(axis=1), i.sum(axis=1), p.sum(axis=1), live

    c_sum, i_sum, p_sum, live = block(cur)
    pc_sum, pi_sum, _, plive = block(prev)
    days = live.clip(lower=1)
    pdays = plive.clip(lower=1)

    s = pd.DataFrame(index=clicks.index)
    s[f"clicks_{w}d"] = c_sum
    s[f"clicks_per_day_{w}d"] = c_sum / days
    s[f"impr_per_day_{w}d"] = i_sum / days
    s[f"ctr_{w}d"] = np.where(i_sum > 0, c_sum / i_sum.replace(0, np.nan), np.nan)
    s[f"position_{w}d"] = np.where(i_sum > 0, p_sum / i_sum.replace(0, np.nan), np.nan)
    s[f"prev_clicks_{w}d"] = pc_sum
    s[f"prev_impr_{w}d"] = pi_sum

    # change vs prior window, per live day; only when the prior window was mostly live
    ok = plive >= w / 2
    cur_c, prev_c = c_sum / days, pc_sum / pdays
    cur_i, prev_i = i_sum / days, pi_sum / pdays
    s[f"clicks_change_pct_{w}d"] = np.where(ok & (prev_c > 0), (cur_c / prev_c.replace(0, np.nan) - 1) * 100, np.nan)
    s[f"impr_change_pct_{w}d"] = np.where(ok & (prev_i > 0), (cur_i / prev_i.replace(0, np.nan) - 1) * 100, np.nan)

    cs = clicks.iloc[:, cur].apply(lambda r: _slope(r.to_numpy(dtype=float)), axis=1)
    iss = impr.iloc[:, cur].apply(lambda r: _slope(r.to_numpy(dtype=float)), axis=1)
    mean_c, mean_i = c_sum / days, i_sum / days
    s[f"clicks_slope_{w}d"] = cs
    s[f"clicks_slope_pct_{w}d"] = np.where(mean_c > 0, cs / mean_c.replace(0, np.nan) * 100, np.nan)
    s[f"impr_slope_pct_{w}d"] = np.where(mean_i > 0, iss / mean_i.replace(0, np.nan) * 100, np.nan)
    return s


def trend_label(row: pd.Series, w: int, tcfg: dict, age_days: int) -> str:
    if age_days < tcfg["new_page_days"]:
        return "New (ramping)"
    cur_c, prev_c = row[f"clicks_{w}d"], row[f"prev_clicks_{w}d"]
    if cur_c + prev_c >= tcfg["min_clicks"]:
        chg, slope, basis = row[f"clicks_change_pct_{w}d"], row[f"clicks_slope_pct_{w}d"], ""
    elif row[f"impr_per_day_{w}d"] * w + row[f"prev_impr_{w}d"] >= tcfg["min_impressions"]:
        chg, slope, basis = row[f"impr_change_pct_{w}d"], row[f"impr_slope_pct_{w}d"], " (impr)"
    else:
        return "Too little data"
    if pd.isna(chg):
        return "New (ramping)"
    slope = 0 if pd.isna(slope) else slope
    if chg >= tcfg["change_pct"] and slope >= 0:
        return "Rising" + basis
    if chg <= -tcfg["change_pct"] and slope <= 0:
        return "Declining" + basis
    return "Flat" + basis


# ---------------------------------------------------------------- tiers & CTR

def expected_ctr(position: float, curve: list[dict]) -> float:
    if pd.isna(position):
        return np.nan
    for step in curve:
        if position <= step["max_pos"]:
            return step["ctr"]
    return curve[-1]["ctr"]


def assign_tiers(traj: pd.DataFrame, tcfg: dict) -> pd.DataFrame:
    cpd = traj["clicks_per_day_30d"]
    with_clicks = cpd[cpd > 0]
    rel = pd.Series("Rest", index=traj.index)
    rel[cpd <= 0] = "No clicks"
    for t in sorted(tcfg["relative"], key=lambda t: t["pct"]):  # low pct first, higher overwrite
        if len(with_clicks):
            cut = np.percentile(with_clicks, t["pct"])
            rel[(cpd >= cut) & (cpd > 0)] = t["name"]
    ab = pd.Series("", index=traj.index)
    for t in sorted(tcfg["absolute"], key=lambda t: t["min"]):
        ab[cpd >= t["min"]] = t["name"]
    traj["tier"] = rel
    traj["volume_tier"] = ab
    return traj


# ---------------------------------------------------------------- main build

def build(df: pd.DataFrame, cfg: dict, end: date, refresh_log: pd.DataFrame | None = None) -> dict:
    windows = cfg["windows"]
    days = max(cfg["gsc"]["history_days"], 2 * max(windows + [cfg["decay"]["window"]]))
    m = daily_matrix(df, end, days)
    traj = pd.DataFrame(index=m["clicks"].index)
    for w in sorted(set(windows + [cfg["decay"]["window"], cfg["early_warning"]["window"],
                                    cfg["opportunity"]["window"]])):
        traj = traj.join(window_stats(m, w))
    traj["first_seen"] = m["first_seen"].reindex(traj.index)
    traj["age_days"] = traj["first_seen"].map(lambda d: (end - d).days + 1)

    tc = cfg["trend"]
    traj["trend"] = [trend_label(r, tc["window"], tc, r["age_days"]) for _, r in traj.iterrows()]
    traj["trend_short"] = [trend_label(r, tc["short_window"], tc, r["age_days"]) for _, r in traj.iterrows()]
    traj = assign_tiers(traj, cfg["tiers"])

    curve = cfg["opportunity"]["expected_ctr"]
    ow = cfg["opportunity"]["window"]
    traj["expected_ctr"] = traj[f"position_{ow}d"].map(lambda p: expected_ctr(p, curve))

    last_refresh = _last_refresh_dates(refresh_log)
    flags = _flags(traj, cfg, end, last_refresh)
    scope = _monthly_scope(traj, flags, cfg)
    refresh = _refresh_results(refresh_log, m, cfg, end)
    traj = traj.reset_index().rename(columns={"index": "page"})
    traj = traj.sort_values("clicks_per_day_30d", ascending=False)
    return {"trajectory": traj, "flags": flags, "scope": scope, "refresh": refresh,
            "daily_clicks": m["clicks"], "daily_impr": m["impressions"], "end": end}


# ---------------------------------------------------------------- flags

def _last_refresh_dates(log: pd.DataFrame | None) -> dict:
    if log is None or log.empty:
        return {}
    lg = log.dropna(subset=["page", "refresh_date"]).copy()
    lg["page"] = lg["page"].map(normalize_url)
    lg["refresh_date"] = pd.to_datetime(lg["refresh_date"], errors="coerce").dt.date
    return lg.dropna(subset=["refresh_date"]).groupby("page")["refresh_date"].max().to_dict()


def _flags(traj: pd.DataFrame, cfg: dict, end: date, last_refresh: dict) -> pd.DataFrame:
    out = []
    d = cfg["decay"]
    w = d["window"]
    for page, r in traj.iterrows():
        lr = last_refresh.get(page)
        recently = lr is not None and (end - lr).days < d["skip_refreshed_days"]
        prev_c, prev_i = r[f"prev_clicks_{w}d"], r[f"prev_impr_{w}d"]
        cur_c = r[f"clicks_{w}d"]
        cur_i = r[f"impr_per_day_{w}d"] * w
        eligible = (r["age_days"] >= 2 * w and not recently
                    and (prev_c >= d["min_prior_clicks"] or prev_i >= d["min_prior_impressions"]))
        if eligible:
            # judge the drop on clicks when there are enough of them; otherwise on impressions
            # (4 -> 1 clicks is noise, 1,200 -> 700 impressions is not)
            if prev_c >= d.get("min_clicks_for_click_drop", 20):
                base, now, unit = prev_c, cur_c, "Clicks"
            else:
                base, now, unit = prev_i, cur_i, "Impressions"
            if base > 0 and (now / base - 1) * 100 <= -d["drop_pct"]:
                ctr = cur_c / cur_i if cur_i else 0
                lost = (prev_c - cur_c) / w * 30 if unit == "Clicks" else (base - now) / w * 30 * ctr
                out.append(_flag(page, "Decay", r, lost,
                                 f"{unit} {int(base)} → {int(now)} ({(now/base-1)*100:.0f}%) last {w}d vs prior {w}d"))
                continue

        e = cfg["early_warning"]
        ew = e["window"]
        pc, cc = r[f"prev_clicks_{ew}d"], r[f"clicks_{ew}d"]
        ich = r[f"impr_change_pct_{ew}d"]
        if (not recently and r["age_days"] >= 2 * ew and pc >= e["min_prior_clicks"]
                and (cc / pc - 1) * 100 <= -e["drop_pct"] and (pd.isna(ich) or ich < 0)):
            out.append(_flag(page, "Early warning", r, (pc - cc) / ew * 30,
                             f"Clicks {int(pc)} → {int(cc)} last {ew}d; impressions {ich:+.0f}%"))

    o = cfg["opportunity"]
    ow = o["window"]
    for page, r in traj.iterrows():
        ipd, pos, ctr, exp = r[f"impr_per_day_{ow}d"], r[f"position_{ow}d"], r[f"ctr_{ow}d"], r["expected_ctr"]
        if pd.isna(pos) or ipd < o["min_impressions_per_day"]:
            continue
        ctr = 0 if pd.isna(ctr) else ctr
        if pos <= o["max_position"] and ctr < exp * o["ctr_ratio_below"]:
            gain = ipd * 30 * (exp - ctr)
            ich = r[f"impr_change_pct_{ow}d"]
            trend = "new page" if pd.isna(ich) else f"impressions {ich:+.0f}% vs prior {ow}d"
            out.append(_flag(page, "Low CTR for position", r, gain,
                             f"{ipd:.0f} impr/day at pos {pos:.1f}, CTR {ctr*100:.1f}% vs ~{exp*100:.1f}% expected; {trend}"))
        s = cfg["striking_distance"]
        if s["min_position"] <= pos <= s["max_position"] and ipd >= s["min_impressions_per_day"]:
            target = expected_ctr(3, o["expected_ctr"])
            gain = ipd * 30 * max(target - ctr, 0) * 0.5
            out.append(_flag(page, "Striking distance", r, gain,
                             f"Avg pos {pos:.1f} with {ipd:.0f} impr/day; page-1 top-3 would lift CTR"))
    cols = ["page", "flag", "monthly_clicks_at_stake", "detail", "tier", "trend",
            "clicks_per_day_30d", "impr_per_day_14d", "position_14d"]
    if not out:
        return pd.DataFrame(columns=cols)
    f = pd.DataFrame(out)[cols]
    f = f.sort_values("monthly_clicks_at_stake", ascending=False)
    decay = f[f.flag == "Decay"].head(cfg["decay"]["max_per_week"])
    return pd.concat([decay, f[f.flag != "Decay"]]).reset_index(drop=True)


def _flag(page, flag, r, stake, detail):
    return {"page": page, "flag": flag, "monthly_clicks_at_stake": round(float(max(stake, 0)), 1),
            "detail": detail, "tier": r["tier"], "trend": r["trend"],
            "clicks_per_day_30d": round(float(r["clicks_per_day_30d"]), 2),
            "impr_per_day_14d": round(float(r["impr_per_day_14d"]), 1),
            "position_14d": round(float(r["position_14d"]), 1) if not pd.isna(r["position_14d"]) else None}


ACTIONS = {
    "Decay": "Refresh: update facts/year/fees, cover sections top-3 pages have, re-check intent",
    "Early warning": "Check lost queries in GSC; light refresh if a competitor overtook",
    "Low CTR for position": "Rewrite title + meta; check AI Overview tracker for this query; add answer-first summary",
    "Striking distance": "Expand for the main query, add internal links from related posts",
}


def _monthly_scope(traj: pd.DataFrame, flags: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    cols = ["rank", "page", "reasons", "monthly_clicks_at_stake", "recommended_action",
            "tier", "trend", "clicks_per_day_30d", "impr_per_day_14d", "position_14d", "status", "owner"]
    if flags.empty:
        return pd.DataFrame(columns=cols)
    g = flags.groupby("page").agg(
        reasons=("flag", lambda s: " + ".join(dict.fromkeys(s))),
        monthly_clicks_at_stake=("monthly_clicks_at_stake", "sum"),
        top_flag=("flag", "first"),
        tier=("tier", "first"), trend=("trend", "first"),
        clicks_per_day_30d=("clicks_per_day_30d", "first"),
        impr_per_day_14d=("impr_per_day_14d", "first"),
        position_14d=("position_14d", "first"),
    ).reset_index()
    g["recommended_action"] = g["top_flag"].map(ACTIONS)
    g = g.sort_values("monthly_clicks_at_stake", ascending=False).head(cfg["monthly_scope"]["top_n"])
    g["rank"] = range(1, len(g) + 1)
    g["status"] = "Proposed"
    g["owner"] = ""
    g["monthly_clicks_at_stake"] = g["monthly_clicks_at_stake"].round(0)
    return g[cols].reset_index(drop=True)


# ---------------------------------------------------------------- refresh before/after

def _refresh_results(log: pd.DataFrame | None, m: dict, cfg: dict, end: date) -> pd.DataFrame | None:
    if log is None or log.empty:
        return log
    n = cfg["refresh_measure_days"]
    clicks = m["clicks"]
    res = log.copy()
    before, after, chg, result = [], [], [], []
    for _, r in res.iterrows():
        try:
            page = normalize_url(str(r["page"]))
            rd = pd.to_datetime(r["refresh_date"]).date()
        except (ValueError, TypeError):
            before.append(None); after.append(None); chg.append(None); result.append("Check page/date")
            continue
        if page not in clicks.index:
            before.append(None); after.append(None); chg.append(None); result.append("No GSC data")
            continue
        row = clicks.loc[page]
        cols = list(row.index)
        b = [d for d in cols if rd - timedelta(days=n) <= d < rd]
        a = [d for d in cols if rd < d <= rd + timedelta(days=n)]
        bs = float(row[b].sum()) if b else None
        if (end - rd).days < n:
            before.append(bs); after.append(None); chg.append(None)
            result.append(f"Pending ({n - (end - rd).days}d left)")
            continue
        as_ = float(row[a].sum())
        before.append(bs); after.append(as_)
        if bs:
            pct = (as_ / bs - 1) * 100
            chg.append(round(pct, 1))
            if bs < 10:
                result.append("Too few clicks to judge")
            else:
                result.append("Recovered / grew" if pct >= 10 else "Dropped further" if pct <= -10 else "No real change")
        else:
            chg.append(None); result.append("Grew from zero" if as_ > 0 else "No clicks")
    res[f"clicks_{n}d_before"] = before
    res[f"clicks_{n}d_after"] = after
    res["change_pct"] = chg
    res["result"] = result
    return res
