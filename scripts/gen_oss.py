#!/usr/bin/env python3
"""Generate the open-source contributions showcase.

Queries the GitHub API for merged PRs authored by GH_USER, keeps only the ones
landed in *other people's* repositories (true OSS contributions), enriches each
with the target repo's star count / description and the PR's diff size, then:

  * writes  site/oss.json          (consumed live by the terminal `oss` command)
  * rewrites the block between <!-- OSS:START --> and <!-- OSS:END --> in README.md

Sorted by target-repo stars, so the highest-profile repo is the "flagship".
Pure standard library. Runs unauthenticated locally (rate-limited) or with a
GITHUB_TOKEN in CI.
"""

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

USER = os.environ.get("GH_USER", "SiddharthUchil")
TOKEN = os.environ.get("GITHUB_TOKEN", "")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OSS_JSON = os.path.join(ROOT, "site", "oss.json")
README = os.path.join(ROOT, "README.md")
START = "<!-- OSS:START -->"
END = "<!-- OSS:END -->"


def api_get(url):
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", f"{USER}-oss-showcase")
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def sanitize(text):
    """Honor the no-em-dash preference and tidy whitespace/mojibake."""
    if not text:
        return ""
    for bad in ("—", "–", "�"):
        text = text.replace(bad, "-")
    return " ".join(text.split()).strip()


def collect():
    q = f"type:pr+author:{USER}+is:merged"
    url = f"https://api.github.com/search/issues?q={q}&per_page=100&sort=created&order=desc"
    items = api_get(url).get("items", [])

    repos = {}  # full_name -> repo dict
    for it in items:
        full_name = it["repository_url"].split("/repos/", 1)[1]
        owner = full_name.split("/", 1)[0]
        if owner.lower() == USER.lower():
            continue  # own repo, not an external contribution

        merged_at = (it.get("pull_request") or {}).get("merged_at") or ""
        pr = {
            "number": it["number"],
            "title": sanitize(it["title"]),
            "url": it["html_url"],
            "merged_at": merged_at[:10],
            "additions": None,
            "deletions": None,
            "changed_files": None,
        }
        # Best-effort diff stats (skip silently on rate limit / offline).
        try:
            d = api_get(f"https://api.github.com/repos/{full_name}/pulls/{it['number']}")
            pr["additions"] = d.get("additions")
            pr["deletions"] = d.get("deletions")
            pr["changed_files"] = d.get("changed_files")
            if not pr["merged_at"] and d.get("merged_at"):
                pr["merged_at"] = d["merged_at"][:10]
        except (urllib.error.URLError, KeyError, ValueError):
            pass

        if full_name not in repos:
            try:
                r = api_get(f"https://api.github.com/repos/{full_name}")
                stars = r.get("stargazers_count", 0)
                desc = sanitize(r.get("description"))
                lang = r.get("language") or ""
            except (urllib.error.URLError, KeyError, ValueError):
                stars, desc, lang = 0, "", ""
            repos[full_name] = {
                "repo": full_name,
                "repo_url": f"https://github.com/{full_name}",
                "stars": stars,
                "description": desc,
                "language": lang,
                "prs": [],
            }
        repos[full_name]["prs"].append(pr)

    ordered = sorted(repos.values(), key=lambda r: (-r["stars"], r["repo"]))
    for r in ordered:
        r["prs"].sort(key=lambda p: p["merged_at"], reverse=True)
    return ordered


def write_json(repos):
    data = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "user": USER,
        "total_prs": sum(len(r["prs"]) for r in repos),
        "repos": repos,
    }
    with open(OSS_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return data


def cell(text):
    return text.replace("|", "\\|")


def render_readme(repos):
    if not repos:
        return "_No external merged PRs on record yet._"
    f = repos[0]
    lines = [f'> \U0001f31f **Flagship** &nbsp; [`{f["repo"]}`]({f["repo_url"]}) &nbsp; ⭐ {f["stars"]:,}', ">"]
    for p in f["prs"]:
        diff = f' (+{p["additions"]}, {p["changed_files"]} files)' if p["additions"] is not None else ""
        lines.append(f'> [#{p["number"]} {p["title"]}]({p["url"]}) - merged {p["merged_at"]}{diff}  ')
    if f["description"]:
        lines.append(f'> <sub>{f["description"]}</sub>')

    others = repos[1:]
    if others:
        lines += ["", "| repo | merged PRs | ⭐ |", "|------|-----------|-----|"]
        for r in others:
            prs = ", ".join(f'[#{p["number"]}]({p["url"]}) {cell(p["title"])}' for p in r["prs"])
            lines.append(f'| [`{r["repo"]}`]({r["repo_url"]}) | {prs} | {r["stars"]:,} |')
    return "\n".join(lines)


def write_readme(repos):
    with open(README, "r", encoding="utf-8") as fh:
        content = fh.read()
    if START not in content or END not in content:
        sys.exit(f"markers {START} / {END} not found in README.md")
    i = content.index(START) + len(START)
    j = content.index(END)
    block = render_readme(repos)
    updated = content[:i] + "\n" + block + "\n" + content[j:]
    if updated != content:
        with open(README, "w", encoding="utf-8") as fh:
            fh.write(updated)


def main():
    repos = collect()
    # Showcase the flagship only: the single top PR in the highest-starred repo.
    if repos:
        repos = repos[:1]
        repos[0]["prs"] = repos[0]["prs"][:1]
    data = write_json(repos)
    write_readme(repos)
    print(f"OSS showcase: {len(repos)} external repo, {data['total_prs']} merged PR (flagship only)")
    for r in repos:
        print(f"  {r['repo']}  (stars={r['stars']}, prs={len(r['prs'])})")


if __name__ == "__main__":
    main()
