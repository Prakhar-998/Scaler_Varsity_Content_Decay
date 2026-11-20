"""Search Console data: live API pull (service account) or a local JSON/CSV for testing."""
from __future__ import annotations

import json
import os
from datetime import date, timedelta

import pandas as pd

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]


def credentials(scopes):
    from google.oauth2 import service_account
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if raw:
        return service_account.Credentials.from_service_account_info(json.loads(raw), scopes=scopes)
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "service_account.json")
    return service_account.Credentials.from_service_account_file(path, scopes=scopes)


def fetch(site_url: str, start: date, end: date, search_type: str = "web") -> pd.DataFrame:
    """Daily page-level rows for [start, end], paginated past the 25k row cap."""
    from googleapiclient.discovery import build
    svc = build("searchconsole", "v1", credentials=credentials(SCOPES), cache_discovery=False)
    rows, start_row = [], 0
    while True:
        body = {
            "startDate": start.isoformat(), "endDate": end.isoformat(),
            "dimensions": ["date", "page"], "type": search_type,
            "dataState": "final", "rowLimit": 25000, "startRow": start_row,
        }
        resp = svc.searchanalytics().query(siteUrl=site_url, body=body).execute()
        batch = resp.get("rows", [])
        for r in batch:
            rows.append({"date": r["keys"][0], "page": r["keys"][1], "clicks": r["clicks"],
                         "impressions": r["impressions"], "position": r["position"]})
        if len(batch) < 25000:
            break
        start_row += 25000
    return pd.DataFrame(rows, columns=["date", "page", "clicks", "impressions", "position"])


def load_file(path: str) -> pd.DataFrame:
    """Offline input: a CSV, a JSON list, or a Windsor.ai {"data": [...]} export."""
    if path.endswith(".csv"):
        return pd.read_csv(path)
    with open(path) as f:
        obj = json.load(f)
    return pd.DataFrame(obj["data"] if isinstance(obj, dict) else obj)


def date_range(cfg: dict, today: date | None = None) -> tuple[date, date]:
    today = today or date.today()
    end = today - timedelta(days=cfg["gsc"]["data_lag_days"])
    start = end - timedelta(days=cfg["gsc"]["history_days"] - 1)
    return start, end
