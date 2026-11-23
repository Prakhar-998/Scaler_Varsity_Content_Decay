"""Weekly Slack summary via an incoming webhook (env SLACK_WEBHOOK_URL), built with Block Kit."""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

import pandas as pd

from .tables import slug

MAX_ITEMS = 3


def _link(url: str) -> str:
    return f"<{url}|{slug(url)}>"


def _pct(cur: float, prev: float) -> str:
    if not prev:
        return ""
    p = (cur / prev - 1) * 100
    arrow = "▲" if p >= 0 else "▼"
    return f"{arrow} {abs(p):.0f}% vs prior"


def _totals(out: dict) -> dict:
    tot = out["daily_clicks"].sum(axis=0)
    n = len(tot)

    def win(w, off=0):
        return float(tot.iloc[n - w - off: n - off].sum())

    return {"c7": win(7), "p7": win(7, 7), "c30": win(30), "p30": win(30, 30), "series": tot}


def _qc(cfg: dict, w: int = 720, h: int = 300) -> str:
    """QuickChart image URL (public, no key). Uses the short-URL endpoint so long charts
    stay under Slack's 3000-char image_url limit; falls back to a GET URL if that fails."""
    body = {"chart": cfg, "width": w, "height": h, "backgroundColor": "white", "version": "4"}
    try:
        req = urllib.request.Request("https://quickchart.io/chart/create", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            url = json.loads(r.read()).get("url")
            if url:
                return url
    except Exception as e:  # network hiccup: fall back to the long URL
        print(f"[slack] quickchart short URL failed ({e}); using long URL")
    q = urllib.parse.urlencode({"c": json.dumps(cfg, separators=(",", ":")), "w": w, "h": h,
                                "bkg": "white", "v": 4})
    return f"https://quickchart.io/chart?{q}"


def chart_trend(clicks: pd.Series, impr: pd.Series, days: int = 60) -> str:
    """Daily blog clicks (7d avg) and impressions (7d avg) on two axes."""
    c = clicks.iloc[-days:].rolling(7, min_periods=1).mean().round(1)
    i = impr.iloc[-days:].rolling(7, min_periods=1).mean().round(0)
    return _qc({
        "type": "line",
        "data": {"labels": [f"{d.day}/{d.month}" for d in c.index],
                 "datasets": [
                     {"label": "Clicks (7-day avg)", "data": [round(float(v)) if v >= 10 else float(v) for v in c.values], "yAxisID": "y",
                      "borderColor": "#4f46e5", "backgroundColor": "rgba(79,70,229,0.12)", "fill": True,
                      "pointRadius": 0, "borderWidth": 3},
                     {"label": "Impressions (7-day avg)", "data": [int(v) for v in i.values], "yAxisID": "y1",
                      "borderColor": "#f59e0b", "pointRadius": 0, "borderWidth": 2, "borderDash": [6, 4]},
                 ]},
        "options": {"plugins": {"legend": {"position": "bottom"},
                                "title": {"display": True, "text": f"Blog clicks & impressions, last {days} days"}},
                    "scales": {"x": {"ticks": {"maxTicksLimit": 8}},
                               "y": {"beginAtZero": True, "title": {"display": True, "text": "Clicks/day"}},
                               "y1": {"beginAtZero": True, "position": "right", "grid": {"drawOnChartArea": False},
                                      "title": {"display": True, "text": "Impressions/day"}}}},
    })


def chart_top_articles(t: pd.DataFrame, n: int = 8) -> str:
    """Top articles: clicks this week vs last week (horizontal bars)."""
    top = t.sort_values("clicks_7d", ascending=False).head(n)
    labels = [_short_label(p) for p in top["page"]]
    prev = (top["clicks_14d"] - top["clicks_7d"]).clip(lower=0)
    return _qc({
        "type": "bar",
        "data": {"labels": labels, "datasets": [
            {"label": "Last week", "data": [int(v) for v in prev], "backgroundColor": "#c7d2fe"},
            {"label": "This week", "data": [int(v) for v in top["clicks_7d"]], "backgroundColor": "#4f46e5"},
        ]},
        "options": {"indexAxis": "y", "plugins": {"legend": {"position": "bottom"},
                    "title": {"display": True, "text": "Top articles — clicks this week vs last week"}},
                    "scales": {"x": {"beginAtZero": True}}},
    }, h=340)


def chart_health_mix(t: pd.DataFrame) -> str:
    """Article health (14-day trend) as a doughnut."""
    lab = t["trend_short"].str.replace(r" \(impr\)", "", regex=True)
    order = [("Rising", "#16a34a"), ("Flat", "#94a3b8"), ("Declining", "#dc2626"),
             ("New (ramping)", "#6366f1"), ("Too little data", "#e2e8f0")]
    counts = lab.value_counts()
    keep = [(k, c) for k, c in order if counts.get(k, 0)]
    return _qc({
        "type": "doughnut",
        "data": {"labels": [f"{k} ({int(counts[k])})" for k, _ in keep],
                 "datasets": [{"data": [int(counts[k]) for k, _ in keep],
                               "backgroundColor": [c for _, c in keep]}]},
        "options": {"plugins": {"legend": {"position": "right"},
                                "title": {"display": True, "text": "Article health — 14-day trend"}}},
    }, w=600, h=300)


def _short_label(url: str, n: int = 34) -> str:
    s = slug(url).strip("/")
    return s if len(s) <= n else s[: n - 1] + "…"


def blocks(out: dict, sheet_url: str = "", chart: bool = True) -> list[dict]:
    t, f = out["trajectory"], out["flags"]
    tt = _totals(out)
    end = out["end"].strftime("%d %b %Y")
    n_attention = f["page"].nunique() if len(f) else 0

    b: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": "📈 Varsity Content Health — weekly", "emoji": True}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"Google Search Console data through *{end}* · {len(t)} articles tracked"}]},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*Clicks · last 7 days*\n{int(tt['c7']):,}  {_pct(tt['c7'], tt['p7'])}"},
            {"type": "mrkdwn", "text": f"*Clicks · last 30 days*\n{int(tt['c30']):,}  {_pct(tt['c30'], tt['p30'])}"},
            {"type": "mrkdwn", "text": f"*Articles needing attention*\n{n_attention}"},
            {"type": "mrkdwn", "text": "*Flags*\n" + (" · ".join(f"{k} {v}" for k, v in f['flag'].value_counts().items()) if len(f) else "None")},
        ]},
    ]
    if chart:
        b.append({"type": "image", "image_url": chart_trend(tt["series"], out["daily_impr"].sum(axis=0)),
                  "alt_text": "Blog clicks and impressions, last 60 days"})
        b.append({"type": "image", "image_url": chart_health_mix(t), "alt_text": "Article health mix"})
    b.append({"type": "divider"})

    # top movers: clicks/day last 7d vs the 7d before
    m = t[t["age_days"] >= 14].copy()
    m["delta"] = m["clicks_per_day_7d"] - (m["clicks_14d"] - m["clicks_7d"]) / 7
    up = m[m["delta"] > 0].sort_values("delta", ascending=False).head(MAX_ITEMS)
    if len(up):
        lines = [f"• {_link(r.page)} — *{r.clicks_per_day_7d:.1f}* clicks/day (+{r.delta:.1f})" for r in up.itertuples()]
        b.append(_section("🚀 *Top movers this week*", lines))
    if chart:
        b.append({"type": "image", "image_url": chart_top_articles(t), "alt_text": "Top articles this week vs last week"})

    groups = [
        ("Decay", "🔻 *Decaying* — refresh candidates"),
        ("Early warning", "⚠️ *Early warning* — clicks sliding"),
        ("Low CTR for position", "👀 *Seen but not clicked* — rewrite title/meta"),
        ("Striking distance", "🎯 *Striking distance* — positions 8–20"),
    ]
    for flag, title in groups:
        g = f[f["flag"] == flag].head(MAX_ITEMS) if len(f) else f
        if not len(g):
            continue
        lines = [f"• {_link(r.page)} — {_short(r)}" for r in g.itertuples()]
        more = (f["flag"] == flag).sum() - len(g)
        if more > 0:
            lines.append(f"_+{more} more in the sheet_")
        b.append(_section(title, lines))

    b.append({"type": "divider"})
    if sheet_url:
        b.append({"type": "actions", "elements": [
            {"type": "button", "style": "primary", "text": {"type": "plain_text", "text": "Open full sheet"}, "url": sheet_url},
        ]})
    b.append({"type": "context", "elements": [{"type": "mrkdwn", "text": "Auto-generated weekly from GSC · thresholds in `config.yaml`"}]})
    return [x for x in b if not (x["type"] == "image" and len(x["image_url"]) > 3000)]


def _short(r) -> str:
    if r.flag in ("Decay", "Early warning"):
        return r.detail.replace(" last 28d vs prior 28d", " (28d)").replace(" last 14d", " (14d)")
    if r.flag == "Low CTR for position":
        ctr = r.detail.split("CTR ")[1].split(" vs")[0] if "CTR " in r.detail else ""
        return f"{r.impr_per_day_14d:.0f} impr/day · pos {r.position_14d} · CTR {ctr}"
    return f"{r.impr_per_day_14d:.0f} impr/day · pos {r.position_14d}"


def _section(title: str, lines: list[str]) -> dict:
    text = title + "\n" + "\n".join(lines)
    return {"type": "section", "text": {"type": "mrkdwn", "text": text[:2900]}}


def message(out: dict, sheet_url: str = "") -> str:
    """Plain-text fallback (notifications, clients that can't render blocks)."""
    f = out["flags"]
    counts = " · ".join(f"{k}: {v}" for k, v in f["flag"].value_counts().items()) if len(f) else "No flags"
    return f"Varsity Content Health — data through {out['end'].isoformat()} — {counts}"


def send(out: dict, sheet_url: str = "", chart: bool = True) -> bool:
    url = os.environ.get("SLACK_WEBHOOK_URL")
    if not url:
        return False
    payload = {"text": message(out, sheet_url), "blocks": blocks(out, sheet_url, chart)}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=20).read()
    return True
