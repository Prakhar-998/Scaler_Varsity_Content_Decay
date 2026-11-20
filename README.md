# Varsity Content Health

This tool tracks the daily click trajectory and content decay of every article on `interviewbit.com/varsity/blog/`. It pulls page-level data from Google Search Console every day and writes a Google Sheet. The sheet shows each article's trend over 7, 14, 30 and 60 days, groups articles into tiers, flags articles that are decaying or under-performing, and builds a monthly shortlist of articles to re-optimise. After each refresh, it measures the clicks before and after.

It never edits WordPress. It reads from GSC and writes only to its own sheet.

## What's in the sheet

| Tab | What it shows |
|---|---|
| **Summary** | Blog-wide clicks (7, 14 and 30 days vs the window before), how many articles fall into each trend, tier and flag, and the biggest movers |
| **Trajectory** | One row per article: a sparkline of the last 60 days, average clicks per day for each window, % change vs the window before, trend-line slope (% per day), impressions, CTR, position and age |
| **Flags** | Articles that need attention, sorted by estimated clicks per month at stake |
| **Monthly Scope** | The top 15 articles to re-optimise this month. It is regenerated on the first run of each month. You can edit **Status** and **Owner**; your edits are kept for the rest of the month and carried over when the same article reappears |
| **Refresh Log** | **You fill in columns A–E** whenever an article is refreshed. The job fills in clicks for the 28 days before and the 28 days after, and the result |
| **Daily (wide)** | Daily clicks for each article over the last 60 days. The sparklines read from this tab |

### Trend labels
The tool compares the last *N* days with the *N* days before that. It uses 30 days for **Trend 30d** and 14 days for **Trend 14d**. It also fits a trend line over the last *N* days.

- **Rising**: up at least 20% and the slope is not negative. **Declining**: down at least 20% and the slope is not positive. Anything else is **Flat**.
- If the article had fewer than 10 clicks across both windows, the label is based on impressions instead and is marked `(impr)`.
- **New (ramping)**: the article is less than 30 days old, or the window before wasn't at least half live yet.
- **Too little data**: not enough clicks or impressions to say anything.

### Tiers
- **Tier (relative)**: Top 10% or Top 25% of articles by 30-day clicks per day, then Rest or No clicks. This always tells the articles apart, whatever the traffic level.
- **Volume tier**: 30+, 50+ or 100+ clicks per day. These stay empty until articles get there. You can edit both in `config.yaml`.

### Flags
| Flag | Rule (defaults in `config.yaml`) |
|---|---|
| **Decay** | Last 28 days vs the 28 before: a drop of more than 25%. The article needs at least 50 clicks or 500 impressions in the earlier window. The drop is judged on clicks when the earlier window had 20 or more clicks, and on impressions otherwise. Articles refreshed in the last 45 days are skipped. At most 10 a week |
| **Early warning** | Last 14 days: clicks down at least 25% and impressions also falling. The article needs at least 10 clicks in the earlier window |
| **Low CTR for position** | 50 or more impressions a day at an average position of 10 or better, with CTR below half of what's expected for that position. This catches the "demand is there but nobody clicks" pattern, like KIRO AI. Check the AI Overview tracker for the main query |
| **Striking distance** | Average position 8–20 with 30 or more impressions a day |

"Est. clicks/month at stake" is a rough figure used to rank articles, not a forecast. For decay it means the clicks lost. For low CTR it means the gap to the expected CTR × impressions.

## Setup (about 15 minutes)

1. **Service account.** Reuse the one from the internal linker, or create one in the same Google Cloud project. The **Google Search Console API** and the **Google Sheets API** must both be enabled.
2. **GSC access.** In Search Console, open the `https://www.interviewbit.com/varsity/blog/` property, go to Settings → Users and permissions, and add the service account email with **Restricted** permission.
3. **Sheet.** Create a blank Google Sheet called *Varsity Content Health* and share it with the service account email as **Editor**. The tabs are created on the first run.
4. **GitHub.** Push this repo, then go to Settings → Secrets and variables → Actions:
   - Secret `GOOGLE_SERVICE_ACCOUNT_JSON`: the full JSON key
   - Variable `SHEET_ID`: the ID in the Sheet URL
   - Optional secret `SLACK_WEBHOOK_URL`: a summary is sent every Monday
5. **First run.** Go to Actions → *Content health (daily)* → **Run workflow**. After that it runs every day at 08:47 IST.

## Run locally

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
# offline, from a GSC/Windsor export, plus an Excel preview:
.venv/bin/python -m health --dry-run --from-file data/gsc.json --xlsx preview.xlsx
# live (needs service_account.json or GOOGLE_SERVICE_ACCOUNT_JSON, and SHEET_ID):
SHEET_ID=... .venv/bin/python -m health
.venv/bin/python -m pytest -q tests
```

## Layout
```
health/metrics.py   windows, slopes, trend labels, tiers, flags, scope, before/after (pure, tested)
health/gsc.py       Search Console API pull (paginated) + offline file loader
health/tables.py    turns results into sheet tables
health/sheets.py    gspread writer
health/slack.py     optional Monday summary
config.yaml         every threshold
```
# Scaler_Varsity_Content_Decay
