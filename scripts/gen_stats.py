#!/usr/bin/env python3
"""Generate the profile stats cards as self-hosted SVGs.

Replaces the third-party github-readme-stats / activity-graph widgets, which
repeatedly died (paused Vercel deploys, mirrors losing their PAT) and rendered
a "Something went wrong!" card straight into the README. Everything here is
computed from the GitHub API and committed to the repo, so the README depends
on nothing but GitHub itself.

Writes, in light and dark variants so the README <picture> tags can switch:

  * site/stats-{dark,light}.svg     headline numbers
  * site/langs-{dark,light}.svg     top languages by repo count
  * site/activity-{dark,light}.svg  contributions per week, last year

Pure standard library. Needs a GITHUB_TOKEN (CI provides one; locally use
`GITHUB_TOKEN=$(gh auth token) python scripts/gen_stats.py`) because the
contribution calendar is only exposed over GraphQL.
"""

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime

USER = os.environ.get("GH_USER", "SiddharthUchil")
TOKEN = os.environ.get("GITHUB_TOKEN", "")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site")

MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace"

# Same amber/graphite pair the typing header already uses (EDBD4E / 9A6700).
THEMES = {
    "dark": {
        "bg": "#0d1117", "border": "#30363d", "accent": "#edbd4e",
        "text": "#c9d1d9", "dim": "#8b949e", "bar": "#21262d",
    },
    "light": {
        "bg": "#ffffff", "border": "#d0d7de", "accent": "#9a6700",
        "text": "#24292f", "dim": "#57606a", "bar": "#eaeef2",
    },
}


def api_get(url):
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", f"{USER}-stats-cards")
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def graphql(query):
    body = json.dumps({"query": query}).encode()
    req = urllib.request.Request("https://api.github.com/graphql", data=body)
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", f"{USER}-stats-cards")
    req.add_header("Authorization", f"Bearer {TOKEN}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    if "errors" in payload:
        sys.exit(f"GraphQL error: {payload['errors']}")
    return payload["data"]


def esc(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def collect():
    user = api_get(f"https://api.github.com/users/{USER}")

    repos, page = [], 1
    while True:
        batch = api_get(
            f"https://api.github.com/users/{USER}/repos?per_page=100&page={page}")
        repos += batch
        if len(batch) < 100:
            break
        page += 1

    mine = [r for r in repos if not r["fork"]]
    langs = {}
    for r in mine:
        if r["language"]:
            langs[r["language"]] = langs.get(r["language"], 0) + 1

    gql = graphql(GQL_CONTRIBUTIONS % USER)
    cc = gql["user"]["contributionsCollection"]
    cal = cc["contributionCalendar"]

    weeks = [(w["firstDay"], sum(d["contributionCount"] for d in w["contributionDays"]))
             for w in cal["weeks"]]

    return {
        "public_repos": user["public_repos"],
        "followers": user["followers"],
        "stars": sum(r["stargazers_count"] for r in mine),
        "since": datetime.strptime(user["created_at"], "%Y-%m-%dT%H:%M:%SZ").strftime("%b %Y"),
        "contributions": cal["totalContributions"],
        "commits": cc["totalCommitContributions"],
        "prs": cc["totalPullRequestContributions"],
        "langs": sorted(langs.items(), key=lambda kv: (-kv[1], kv[0]))[:5],
        "weeks": weeks,
    }


GQL_CONTRIBUTIONS = """
query {
  user(login: "%s") {
    contributionsCollection {
      totalCommitContributions
      totalPullRequestContributions
      contributionCalendar {
        totalContributions
        weeks { firstDay contributionDays { contributionCount } }
      }
    }
  }
}"""


def frame(w, h, p, title):
    """Card chrome: background, border, prompt line, rule."""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}"'
        f' viewBox="0 0 {w} {h}" role="img" aria-label="{esc(title)}">\n'
        f'<style>\n'
        f'  .t {{ font: 13px {MONO}; fill: {p["text"]}; }}\n'
        f'  .d {{ font: 12px {MONO}; fill: {p["dim"]}; }}\n'
        f'  .a {{ font: 600 13px {MONO}; fill: {p["accent"]}; }}\n'
        f'  .n {{ font: 600 13px {MONO}; fill: {p["accent"]}; }}\n'
        f'</style>\n'
        f'<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="6"'
        f' fill="{p["bg"]}" stroke="{p["border"]}"/>\n'
        f'<text x="20" y="30" class="a">{esc(title)}</text>\n'
        f'<line x1="20" y1="44" x2="{w - 20}" y2="44" stroke="{p["border"]}"/>'
    )


def render_stats(d, p):
    w, h = 495, 195
    rows = [
        ("public repos", f'{d["public_repos"]:,}'),
        ("followers", f'{d["followers"]:,}'),
        ("stars (non-fork)", f'{d["stars"]:,}'),
        ("contributions (1y)", f'{d["contributions"]:,}'),
        ("commits / PRs (1y)", f'{d["commits"]:,} / {d["prs"]:,}'),
    ]
    out = [frame(w, h, p, "$ gh stats --live")]
    y = 68
    for label, value in rows:
        out.append(f'<text x="20" y="{y}" class="t">{esc(label)}</text>')
        out.append(f'<text x="{w - 20}" y="{y}" class="n" text-anchor="end">{esc(value)}</text>')
        y += 23
    out.append(f'<text x="20" y="{h - 12}" class="d">member since {esc(d["since"])}</text>')
    out.append("</svg>")
    return "\n".join(out)


def render_langs(d, p):
    w, h = 415, 195
    out = [frame(w, h, p, "$ gh top-langs")]
    top = d["langs"]
    peak = max((n for _, n in top), default=1)
    x0, span = 160, 175
    y = 68
    for name, n in top:
        fill = max(6, round(n / peak * span))
        label = name if len(name) <= 16 else name[:15] + "…"
        out.append(f'<text x="20" y="{y}" class="t">{esc(label)}</text>')
        out.append(f'<rect x="{x0}" y="{y - 9}" width="{span}" height="11" rx="2" fill="{p["bar"]}"/>')
        out.append(f'<rect x="{x0}" y="{y - 9}" width="{fill}" height="11" rx="2" fill="{p["accent"]}"/>')
        out.append(f'<text x="{w - 20}" y="{y}" class="n" text-anchor="end">{n}</text>')
        y += 23
    out.append(f'<text x="20" y="{h - 12}" class="d">by repo count, forks excluded</text>')
    out.append("</svg>")
    return "\n".join(out)


def render_activity(d, p):
    w, h = 1000, 200
    weeks = d["weeks"]
    left, right, top_y, base = 20, w - 20, 62, 160
    peak = max((n for _, n in weeks), default=1) or 1
    step = (right - left) / max(1, len(weeks) - 1)

    pts = [(left + i * step, base - (n / peak) * (base - top_y))
           for i, (_, n) in enumerate(weeks)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = (f"M {left},{base} L "
            + " L ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
            + f" L {right},{base} Z")

    out = [frame(w, h, p, "$ gh activity --1y")]
    out.append(f'<text x="{w - 20}" y="30" class="d" text-anchor="end">'
               f'{d["contributions"]:,} contributions, peak {peak}/week</text>')
    out.append(f'<path d="{area}" fill="{p["accent"]}" fill-opacity="0.18"/>')
    out.append(f'<polyline points="{line}" fill="none" stroke="{p["accent"]}"'
               f' stroke-width="2" stroke-linejoin="round"/>')
    out.append(f'<line x1="{left}" y1="{base}" x2="{right}" y2="{base}" stroke="{p["border"]}"/>')

    # The window opens mid-month, so the leading partial month can sit a week
    # from the next one and collide ("AugSep"). Drop the earlier of any crowded
    # pair, which keeps the remaining labels a consecutive run.
    seen, marks = set(), []
    for i, (first_day, _) in enumerate(weeks):
        month = datetime.strptime(first_day, "%Y-%m-%d").strftime("%b")
        if month in seen:
            continue
        seen.add(month)
        marks.append((left + i * step, month))
    for j, (x, month) in enumerate(marks):
        if j + 1 < len(marks) and marks[j + 1][0] - x < 42:
            continue
        out.append(f'<text x="{x:.1f}" y="{base + 20}" class="d">{month}</text>')
    out.append("</svg>")
    return "\n".join(out)


def main():
    if not TOKEN:
        sys.exit("GITHUB_TOKEN required (contribution calendar is GraphQL only).\n"
                 "  local: GITHUB_TOKEN=$(gh auth token) python scripts/gen_stats.py")
    d = collect()
    cards = {"stats": render_stats, "langs": render_langs, "activity": render_activity}
    for name, render in cards.items():
        for theme, palette in THEMES.items():
            path = os.path.join(SITE, f"{name}-{theme}.svg")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(render(d, palette) + "\n")
    print(f"stats cards: {len(cards) * len(THEMES)} SVGs written to site/")
    print(f"  repos={d['public_repos']} followers={d['followers']} stars={d['stars']} "
          f"contributions={d['contributions']}")
    print(f"  langs={', '.join(f'{k}:{v}' for k, v in d['langs'])}")


if __name__ == "__main__":
    main()
