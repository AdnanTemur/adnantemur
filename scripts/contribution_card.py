#!/usr/bin/env python3
"""
Render a contribution stats card as SVG, with no third-party service involved.

Why this exists: the profile previously used github-readme-stats (which returns
503 for every user — its shared demo instance is down) and a streak-stats host
(intermittent, and it answers 200 with an error card when it cannot resolve the
user). Both are someone else's uptime problem showing up on this profile.

The data here comes from GitHub's own public contributions fragment,
https://github.com/users/<login>/contributions, which needs no token and no
authentication. Each day is a <td data-date="..."> joined to a <tool-tip> that
carries the exact count, so this reads real numbers rather than the coarse
0-4 "level" buckets.

Output is two SVGs (dark/light) written to --out, committed to the output branch
by the workflow and served from this repo. Nothing is fetched at page-view time.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import re
import sys
import urllib.error
import urllib.request

UA = "Mozilla/5.0 (compatible; contribution-card/1.0; +https://github.com/AdnanTemurBarcha)"

CELL_RE = re.compile(
    r'<td[^>]*?data-date="(?P<date>\d{4}-\d{2}-\d{2})"[^>]*?id="(?P<id>contribution-day-component-[\d-]+)"'
    r'|<td[^>]*?id="(?P<id2>contribution-day-component-[\d-]+)"[^>]*?data-date="(?P<date2>\d{4}-\d{2}-\d{2})"'
)
TIP_RE = re.compile(
    r'<tool-tip[^>]*?for="(contribution-day-component-[\d-]+)"[^>]*?>(.*?)</tool-tip>', re.S
)
COUNT_RE = re.compile(r"^\s*(No|[\d,]+)\s+contribution")


def fetch(url: str, attempts: int = 4) -> str:
    """GET with retries. Raises on final failure so the workflow fails loudly."""
    last = None
    for i in range(1, attempts + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            print(f"  fetch attempt {i}/{attempts} failed: {e}", file=sys.stderr)
    raise SystemExit(f"::error::could not fetch {url}: {last}")


def year_counts(login: str, year: int) -> dict[dt.date, int]:
    """Exact per-day counts for one calendar year."""
    url = (f"https://github.com/users/{login}/contributions"
           f"?from={year}-01-01&to={year}-12-31")
    page = fetch(url)

    ids: dict[str, dt.date] = {}
    for m in CELL_RE.finditer(page):
        cid = m.group("id") or m.group("id2")
        date = m.group("date") or m.group("date2")
        if cid and date:
            ids[cid] = dt.date.fromisoformat(date)

    tips = {cid: html.unescape(txt) for cid, txt in TIP_RE.findall(page)}
    if not ids:
        raise SystemExit(f"::error::no contribution cells parsed for {year} — "
                         "GitHub's markup probably changed")

    out: dict[dt.date, int] = {}
    for cid, date in ids.items():
        m = COUNT_RE.match(tips.get(cid, ""))
        if m is None:
            continue  # a cell with no tooltip is a future/padding day
        raw = m.group(1)
        out[date] = 0 if raw == "No" else int(raw.replace(",", ""))
    return out


def collect(login: str, since: int) -> dict[dt.date, int]:
    today = dt.date.today()
    days: dict[dt.date, int] = {}
    for year in range(since, today.year + 1):
        got = year_counts(login, year)
        days.update(got)
        print(f"  {year}: {len(got):3d} days, {sum(got.values()):5d} contributions")
    return days


def streaks(days: dict[dt.date, int]) -> tuple[int, int, tuple, tuple]:
    """Current and longest streak, each with its (start, end) dates."""
    today = dt.date.today()
    active = sorted(d for d, n in days.items() if n > 0 and d <= today)
    if not active:
        return 0, 0, (None, None), (None, None)

    # Longest run of consecutive active days
    best = cur = 1
    best_end = cur_start = active[0]
    best_start = active[0]
    for prev, day in zip(active, active[1:]):
        if (day - prev).days == 1:
            cur += 1
        else:
            cur, cur_start = 1, day
        if cur > best:
            best, best_start, best_end = cur, cur_start, day

    # Current streak counts back from today; a quiet today does not break it yet,
    # which is how GitHub's own UI reads it.
    anchor = today if days.get(today, 0) > 0 else today - dt.timedelta(days=1)
    cur_len, cur_end = 0, anchor
    day = anchor
    while days.get(day, 0) > 0:
        cur_len += 1
        day -= dt.timedelta(days=1)
    cur_start_d = day + dt.timedelta(days=1) if cur_len else None
    return cur_len, best, (cur_start_d, cur_end if cur_len else None), (best_start, best_end)


def fmt(d: dt.date | None) -> str:
    return d.strftime("%b %-d, %Y") if d else "—"


def span(a: dt.date | None, b: dt.date | None) -> str:
    if not a or not b:
        return "—"
    return fmt(a) if a == b else f"{fmt(a)} – {b.strftime('%b %-d, %Y')}"


THEMES = {
    "dark":  dict(bg="#0d1117", grid="#161d26", name="#e6edf3",
                  muted="#8b949e", ring="#FF2D95", total="#00FFC8", best="#BD00FF",
                  rule="#21262d"),
    "light": dict(bg="#ffffff", grid="#f0f4f8", name="#0d1117",
                  muted="#57606a", ring="#C2185B", total="#0E7C90", best="#7C3AED",
                  rule="#d0d7de"),
}
MONO = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace"


def card(theme: str, total: int, cur: int, best: int,
         cur_span: str, best_span: str, total_span: str) -> str:
    c = THEMES[theme]
    W, H = 560, 200
    col = W / 3
    p: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
        f'role="img" aria-label="{total} total contributions, {cur} day current streak, {best} day longest streak">',
        f'<rect width="{W}" height="{H}" rx="6" fill="{c["bg"]}"/>',
    ]
    # the same graticule as the banner, so the two read as one system
    for gx in range(0, W + 1, 40):
        p.append(f'<line x1="{gx}" y1="0" x2="{gx}" y2="{H}" stroke="{c["grid"]}" stroke-width="1"/>')
    for gy in range(0, H + 1, 40):
        p.append(f'<line x1="0" y1="{gy}" x2="{W}" y2="{gy}" stroke="{c["grid"]}" stroke-width="1"/>')

    for x in (col, col * 2):
        p.append(f'<line x1="{x:.0f}" y1="34" x2="{x:.0f}" y2="{H-30}" stroke="{c["rule"]}" stroke-width="1"/>')

    panels = [
        (col * 0.5, f"{total:,}", "Total Contributions", total_span, c["total"]),
        (col * 1.5, f"{cur}",     "Current Streak",      cur_span,   c["ring"]),
        (col * 2.5, f"{best}",    "Longest Streak",      best_span,  c["best"]),
    ]
    for cx, big, label, sub, colour in panels:
        p.append(f'<text x="{cx:.0f}" y="86" text-anchor="middle" font-family="{MONO}" '
                 f'font-size="38" font-weight="700" fill="{colour}">{big}</text>')
        p.append(f'<text x="{cx:.0f}" y="116" text-anchor="middle" font-family="{MONO}" '
                 f'font-size="13" font-weight="600" fill="{c["name"]}">{label}</text>')
        p.append(f'<text x="{cx:.0f}" y="140" text-anchor="middle" font-family="{MONO}" '
                 f'font-size="10" fill="{c["muted"]}">{html.escape(sub)}</text>')

    p.append(f'<text x="{W/2:.0f}" y="{H-14}" text-anchor="middle" font-family="{MONO}" '
             f'font-size="9" fill="{c["muted"]}" opacity="0.7">generated from public GitHub data · no third-party service</text>')
    p.append("</svg>")
    return "\n".join(p) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", required=True)
    ap.add_argument("--since", type=int, required=True, help="first year to walk")
    ap.add_argument("--out", required=True, help="directory for the SVGs")
    a = ap.parse_args()

    print(f"collecting contributions for {a.user} since {a.since}")
    days = collect(a.user, a.since)
    total = sum(days.values())
    cur, best, cur_dates, best_dates = streaks(days)

    active = sorted(d for d, n in days.items() if n > 0)
    total_span = span(active[0], active[-1]) if active else "—"

    # A profile with zero parsed contributions means the parse broke, not that
    # the account is empty — fail rather than publish a card full of zeros.
    if total == 0:
        raise SystemExit("::error::parsed 0 contributions across every year — refusing to publish")

    print(f"  total={total}  current={cur}  longest={best}")
    import os
    os.makedirs(a.out, exist_ok=True)
    for theme in THEMES:
        path = os.path.join(a.out, f"contributions-{theme}.svg")
        with open(path, "w") as fh:
            fh.write(card(theme, total, cur, best,
                          span(*cur_dates), span(*best_dates), total_span))
        print(f"  wrote {path}")


if __name__ == "__main__":
    main()
