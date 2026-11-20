"""CLI: python -m health [--dry-run] [--from-file data.json] [--xlsx preview.xlsx]"""
from __future__ import annotations

import argparse
import os
from datetime import date
from pathlib import Path

import pandas as pd
import yaml

from . import gsc, metrics, slack, tables

ROOT = Path(__file__).resolve().parent.parent
DAILY_DAYS = 60


def main(argv=None):
    ap = argparse.ArgumentParser(prog="health")
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--from-file", help="offline GSC rows (CSV, JSON list or Windsor export) instead of the API")
    ap.add_argument("--end", help="last data date YYYY-MM-DD (default: today - data_lag_days)")
    ap.add_argument("--refresh-log", help="offline refresh log CSV (page,refresh_date,type,owner,notes)")
    ap.add_argument("--dry-run", action="store_true", help="compute and print, don't write the Sheet")
    ap.add_argument("--xlsx", help="also write a local Excel preview to this path")
    ap.add_argument("--rebuild-scope", action="store_true", help="regenerate this month's Monthly Scope")
    ap.add_argument("--slack", action="store_true", help="send the Slack summary (default: Mondays only)")
    a = ap.parse_args(argv)

    cfg = yaml.safe_load(open(a.config))
    today = date.today()
    start, end = gsc.date_range(cfg, today)
    if a.end:
        end = date.fromisoformat(a.end)

    if a.from_file:
        raw = gsc.load_file(a.from_file)
        if not a.end:
            end = pd.to_datetime(raw["date"]).max().date()
    else:
        raw = gsc.fetch(cfg["gsc"]["site_url"], start, end, cfg["gsc"]["search_type"])
    print(f"[gsc] {len(raw)} rows, data through {end}")

    sheet_id = os.environ.get("SHEET_ID") or cfg["sheet"]["spreadsheet_id"]
    tabs = cfg["sheet"]["tabs"]
    sheet = None
    if not a.dry_run:
        if not sheet_id:
            raise SystemExit("Set SHEET_ID (env) or sheet.spreadsheet_id in config.yaml, or use --dry-run")
        from .sheets import Sheet, read_refresh_log
        sheet = Sheet(sheet_id)
        log = read_refresh_log(sheet, tabs["refresh_log"])
    elif a.refresh_log:
        log = pd.read_csv(a.refresh_log)
    else:
        log = None

    out = metrics.build(metrics.prepare(raw, cfg), cfg, end, log)
    month = today.strftime("%Y-%m")
    n = cfg["refresh_measure_days"]
    print(f"[build] {len(out['trajectory'])} articles, {len(out['flags'])} flags, scope {len(out['scope'])}")

    traj_x = tables.trajectory(out, None, DAILY_DAYS)
    if a.xlsx:
        write_xlsx(a.xlsx, out, today, month, n)
        print(f"[xlsx] {a.xlsx}")

    if sheet:
        from .sheets import read_scope
        sheet.write(tabs["summary"], None, tables.summary(out, today))
        sheet.write(tabs["daily"], *tables.daily(out, DAILY_DAYS))
        sheet.write(tabs["trajectory"], *tables.trajectory(out, tabs["daily"], DAILY_DAYS), freeze_cols=2)
        sheet.write(tabs["flags"], *tables.flags(out))
        sheet.write(tabs["refresh_log"], *tables.refresh_log(out["refresh"], n))
        existing = read_scope(sheet, tabs["scope"])
        same_month = len(existing) and "Month" in existing and (existing["Month"] == month).all()
        if not same_month or a.rebuild_scope:
            sc = out["scope"].copy()
            if len(existing) and "URL" in existing:  # carry over status/owner for repeat pages
                keep = existing.set_index("URL")
                sc["status"] = [keep.at[p, "Status"] if p in keep.index else s for p, s in zip(sc["page"], sc["status"])]
                sc["owner"] = [keep.at[p, "Owner"] if p in keep.index else o for p, o in zip(sc["page"], sc["owner"])]
            sheet.write(tabs["scope"], *tables.scope(sc, month))
            print(f"[sheet] Monthly Scope written for {month}")
        print(f"[sheet] updated https://docs.google.com/spreadsheets/d/{sheet_id}")
        if a.slack or today.weekday() == 0:
            url = f"https://docs.google.com/spreadsheets/d/{sheet_id}"
            print("[slack] sent" if slack.send(slack.message(out, url)) else "[slack] no webhook set")
    else:
        h, rows = traj_x
        print("\n".join(" | ".join(str(c) for c in r[:8]) for r in [h] + rows[:10]))
        fh, frows = tables.flags(out)
        print(f"\nFlags ({len(frows)}):")
        for r in frows[:15]:
            print("  ", r[1], "|", r[0], "|", r[3])


def write_xlsx(path, out, today, month, n):
    from openpyxl import Workbook
    from openpyxl.chart import LineChart, Reference
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    wb.remove(wb.active)
    bold, fill = Font(bold=True), PatternFill("solid", fgColor="EDEDF5")

    def sheet(title, header, rows):
        ws = wb.create_sheet(title)
        if header:
            ws.append(header)
            for c in ws[1]:
                c.font, c.fill = bold, fill
            ws.freeze_panes = "B2"
        for r in rows:
            ws.append(r)
        for col in ws.columns:
            width = max(len(str(c.value or "")) for c in list(col)[:200])
            ws.column_dimensions[col[0].column_letter].width = min(max(width + 2, 8), 60)
        return ws

    sheet("Summary", None, tables.summary(out, today))
    sheet("Trajectory", *tables.trajectory(out, None, DAILY_DAYS))
    sheet("Flags", *tables.flags(out))
    sheet("Monthly Scope", *tables.scope(out["scope"], month))
    sheet("Refresh Log", *tables.refresh_log(out["refresh"], n))
    dh, drows = tables.daily(out, DAILY_DAYS)
    sheet("Daily (wide)", dh, drows)

    # chart: daily clicks for the top 5 articles by 30d clicks/day
    top = out["trajectory"]["page"].head(5).tolist()
    c = out["daily_clicks"].iloc[:, -DAILY_DAYS:]
    ws = wb.create_sheet("Top 5 chart")
    ws.append(["Date"] + [tables.slug(p) for p in top])
    for d in c.columns:
        ws.append([d.isoformat()] + [float(c.at[p, d]) if pd.notna(c.at[p, d]) else None for p in top])
    ch = LineChart()
    ch.title, ch.y_axis.title, ch.height, ch.width = "Daily clicks — top 5 articles", "Clicks", 10, 26
    ch.add_data(Reference(ws, min_col=2, max_col=1 + len(top), min_row=1, max_row=ws.max_row), titles_from_data=True)
    ch.set_categories(Reference(ws, min_col=1, min_row=2, max_row=ws.max_row))
    ws.add_chart(ch, "H2")
    wb.save(path)


if __name__ == "__main__":
    main()
