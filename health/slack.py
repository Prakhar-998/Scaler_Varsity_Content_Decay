"""Optional Slack summary via an incoming webhook (env SLACK_WEBHOOK_URL)."""
from __future__ import annotations

import json
import os
import urllib.request

from .tables import slug


def message(out: dict, sheet_url: str = "") -> str:
    f, t = out["flags"], out["trajectory"]
    lines = [f"*Varsity Content Health* — GSC data through {out['end'].isoformat()}"]
    counts = f["flag"].value_counts().to_dict() if len(f) else {}
    lines.append(" · ".join(f"{k}: {v}" for k, v in counts.items()) or "No flags today")
    rising = t[t["trend_short"].str.startswith("Rising")].head(3)
    if len(rising):
        lines.append("Rising (14d): " + ", ".join(slug(p) for p in rising["page"]))
    for _, r in f.head(5).iterrows():
        lines.append(f"• *{r['flag']}* {slug(r['page'])} — {r['detail']}")
    if sheet_url:
        lines.append(f"<{sheet_url}|Open the sheet>")
    return "\n".join(lines)


def send(text: str) -> bool:
    url = os.environ.get("SLACK_WEBHOOK_URL")
    if not url:
        return False
    req = urllib.request.Request(url, data=json.dumps({"text": text}).encode(),
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=20).read()
    return True
