#!/usr/bin/env python3
"""
One Day I Will Try This — README Generator

Fetches starred repos from GitHub API, categorizes them, and generates
a beautiful README.md with hype scores and activity tiers.

Usage:
    python update_readme.py              # Normal run (uses cache)
    python update_readme.py --force      # Force refresh all activity data
    python update_readme.py --dry-run    # Print stats without writing README

Requires GITHUB_TOKEN env var or gh CLI authentication.
"""

import os
import sys
import json
import math
import time
import argparse
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import urllib.request
import urllib.error

# ─── Config ───────────────────────────────────────────────────────────────────

GITHUB_USERNAME = "joaosbp"
TOKEN = os.environ.get("GITHUB_TOKEN", "")

# Try to get token from gh CLI if not set
if not TOKEN:
    try:
        import subprocess
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            TOKEN = result.stdout.strip()
            print("Using GitHub token from gh CLI")
    except Exception:
        pass

if not TOKEN:
    print("WARNING: No GITHUB_TOKEN found. API rate limit is 60 req/hr.")
    print("Set GITHUB_TOKEN env var or run 'gh auth login'.")

PER_PAGE = 100
CACHE_FILE = ".repo_cache.json"

# ─── Tag Rules ────────────────────────────────────────────────────────────────

TAG_RULES = [
    # Guides / Lists / Resources (Reference Stuff)
    ("awesome-list", ["awesome", "curated list", "awesome list"]),
    ("guide", ["guide", "tutorial", "howto", "how to", "course", "book", "cheatsheet", "best practice"]),
    ("tutorial", ["tutorial", "step-by-step", "learn", "getting started"]),
    ("build-your-own", ["build your own", "build-your-own", "from scratch"]),
    ("design-md", ["design.md", "design system", "design-system"]),
    ("mcp", ["mcp server", "mcp"]),
    ("roadmap", ["roadmap", "career path"]),

    # AI / Agent specific
    ("openclaw", ["openclaw"]),
    ("claude", ["claude", "anthropic"]),
    ("skills", ["skills", "skill", "methodology", "best practice", "claude.md"]),
    ("coding-agent", ["coding agent", "code agent", "ai coding", "ai code", "codex", "cursor", "copilot"]),
    ("orchestration", ["orchestr", "multi-agent", "multi agent", "agency", "workflow"]),
    ("memory", ["memory", "context", "persistent", "embeddings", "sqlite memory"]),
    ("llm-routing", ["router", "routing", "gateway", "proxy", "bifrost", "litellm"]),
    ("autonomous", ["autonomous", "auto-gpt", "autogpt", "self-hosted", "self hosted"]),
    ("framework", ["framework", "harness", "toolkit"]),
    ("rag", ["rag", "retrieval", "knowledge graph", "graphrag"]),
    ("devtools", ["dev tool", "developer tool", "cli tool", "vscode extension", "plugin"]),
    ("personal-ai", ["personal ai", "personal assistant", "ai assistant"]),
    ("agents", ["ai agent", "agentic"]),
    ("llm", ["llm", "large language model"]),

    # Domain specific
    ("game-development", ["game engine", "game dev", "gamedev", "godot", "unity", "unreal"]),
    ("game-engine", ["game engine"]),
    ("godot", ["godot"]),
    ("security", ["security", "pentest", "hacking", "ctf", "vulnerability"]),
    ("financial", ["trading", "finance", "stock", "investment", "portfolio"]),
    ("research", ["research", "paper", "academic", "scientific"]),
    ("training", ["training", "fine-tune", "fine tuning", "rlhf"]),
    ("monitoring", ["monitor", "observability", "log", "metric", "dashboard"]),
    ("productivity", ["productivity", "workflow", "automation tool", "note taking", "task"]),
    ("creative-ai", ["creative ai", "art generation", "music generation", "video generation", "image generation", "generative art"]),
    ("audio", ["audio", "music", "sound", "tts", "speech", "voice"]),
    ("video", ["video", "movie", "clip"]),
    ("markdown", ["markdown", "markitdown", "md"]),
    ("python", ["python"]),
    ("rust", ["rust"]),
    ("typescript", ["typescript", "ts", "react", "nextjs", "vue"]),
    ("mobile", ["mobile", "android", "ios", "react native", "flutter"]),
    ("web", ["web", "frontend", "html", "css"]),
    ("backend", ["backend", "server", "api", "microservice"]),
    ("database", ["database", "db", "sql", "nosql", "vector db"]),
    ("docker", ["docker", "container", "kubernetes", "k8s"]),
    ("config", ["config", "dotfiles", "setup", "rules", "cursorrules"]),
    ("open-source", ["open source", "community"]),
    ("official", ["official", "microsoft", "google", "bytedance", "meta", "facebook"]),
]

REFERENCE_KEYWORDS = [
    "awesome", "roadmap", "guide", "tutorial", "book", "cheatsheet",
    "build-your-own", "build your own", "howto", "how to", "course",
    "learn", "curated", "list", "resources", "examples",
]

# ─── GitHub API ───────────────────────────────────────────────────────────────

def api_call(url, retries=3):
    """Make an authenticated GitHub API request with retry."""
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "one-day-i-will-try-this/1.0",
    }
    if TOKEN:
        headers["Authorization"] = f"token {TOKEN}"

    for attempt in range(retries):
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 403 and attempt < retries - 1:
                print(f"  Rate limited on {url}, retrying...")
                time.sleep(2 ** attempt)
                continue
            print(f"HTTP Error {e.code}: {e.reason} for {url}")
            if e.code == 403:
                print("Rate limited? Check your GITHUB_TOKEN.")
            return None
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            print(f"Error fetching {url}: {e}")
            return None
    return None


def fetch_starred_repos():
    """Fetch all starred repos for the user."""
    repos = []
    page = 1
    while True:
        url = f"https://api.github.com/users/{GITHUB_USERNAME}/starred?per_page={PER_PAGE}&page={page}"
        data = api_call(url)
        if not data:
            break
        repos.extend(data)
        if len(data) < PER_PAGE:
            break
        page += 1
        if page > 100:
            break
    return repos


# ─── Cache ────────────────────────────────────────────────────────────────────

def load_cache():
    """Load cached repo activity data."""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_cache(cache):
    """Save cached repo activity data.
    
    Removes entries older than 7 days to prevent infinite growth.
    """
    now = datetime.now(timezone.utc).timestamp()
    max_age = 7 * 24 * 3600  # 7 days in seconds
    
    # Clean old entries
    keys_to_remove = []
    for key, value in cache.items():
        if isinstance(value, dict) and "timestamp" in value:
            if now - value["timestamp"] > max_age:
                keys_to_remove.append(key)
    
    for key in keys_to_remove:
        del cache[key]
    
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)


# ─── Activity Fetching ──────────────────────────────────────────────────────

def fetch_repo_activity(full_name, cache, force_refresh=False):
    """Fetch recent activity metrics for a repo (30d events).
    
    Returns estimated event count based on commit activity API.
    Uses cache to avoid repeated API calls.
    """
    cache_key = f"activity:{full_name}"
    
    if not force_refresh and cache_key in cache:
        cached = cache[cache_key]
        # Check if cache is fresh (less than 6 hours old)
        if isinstance(cached, dict) and "timestamp" in cached:
            age_hours = (datetime.now(timezone.utc).timestamp() - cached["timestamp"]) / 3600
            if age_hours < 6:
                return cached["value"]
        elif isinstance(cached, (int, float)):
            # Legacy cache format, use it
            return cached
    
    # Try to get commit activity (last 52 weeks)
    try:
        url = f"https://api.github.com/repos/{full_name}/stats/commit_activity"
        data = api_call(url)
        if data and isinstance(data, list) and len(data) > 0:
            # Sum last 4 weeks for ~30d activity
            recent_commits = sum(week.get("total", 0) for week in data[-4:])
            # Scale: commits are a subset of events. Typical ratio: events ≈ commits * 1.5
            # (PRs, issues, releases, etc. also count as events)
            estimated_events = int(recent_commits * 1.5)
            cache[cache_key] = {
                "value": estimated_events,
                "timestamp": datetime.now(timezone.utc).timestamp(),
                "source": "commit_activity"
            }
            return estimated_events
    except Exception:
        pass
    
    # Fallback: use repo pushed_at to estimate
    try:
        url = f"https://api.github.com/repos/{full_name}"
        data = api_call(url)
        if data:
            pushed_at = data.get("pushed_at")
            if pushed_at:
                pushed = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
                days_ago = (datetime.now(timezone.utc) - pushed).days
                if days_ago <= 7:
                    result = 75
                elif days_ago <= 30:
                    result = 35
                elif days_ago <= 90:
                    result = 20
                else:
                    result = 5
                cache[cache_key] = {
                    "value": result,
                    "timestamp": datetime.now(timezone.utc).timestamp(),
                    "source": "pushed_at_fallback"
                }
                return result
    except Exception:
        pass
    
    cache[cache_key] = {
        "value": 0,
        "timestamp": datetime.now(timezone.utc).timestamp(),
        "source": "default"
    }
    return 0


# ─── Categorization ───────────────────────────────────────────────────────────

def categorize_repo(repo):
    """Determine tags and category for a repo."""
    name = repo["full_name"].lower()
    desc = (repo.get("description") or "").lower()
    topics = [t.lower() for t in repo.get("topics", [])]
    text = f"{name} {desc} {' '.join(topics)}"

    tags = []
    for tag, keywords in TAG_RULES:
        if any(kw in text for kw in keywords):
            if tag not in tags:
                tags.append(tag)
        if len(tags) >= 4:
            break

    if not tags:
        tags = ["other"]

    is_reference = any(kw in text for kw in REFERENCE_KEYWORDS)
    if repo["name"].lower().startswith("awesome") or repo["name"].lower().startswith("curated"):
        is_reference = True

    return tags, is_reference


# ─── Hype & Activity Scoring ──────────────────────────────────────────────────

def hype_score(repo, activity_count):
    """Calculate hype score based on the documented formula.
    
    Formula:
    (stars_7d * 6) + (forks_7d * 10) + (new_contributors_30d * 5) +
    (commits_30d * 0.25) + (prs_30d * 2) + (log10(total_stars) * 15)
    
    Since GitHub API doesn't provide 7d/30d granular data without auth,
    we approximate using available metrics:
    - stars_7d ≈ total_stars * 0.01 (1% weekly growth)
    - forks_7d ≈ total_forks * 0.015
    - commits_30d ≈ activity_count / 1.5 (reverse of our event estimate)
    - prs_30d ≈ commits_30d * 0.4
    - new_contributors_30d ≈ commits_30d * 0.05
    
    Activity is capped at 300 events to prevent outliers from dominating.
    """
    stars = repo.get("stargazers_count", 0)
    forks = repo.get("forks_count", 0)
    
    # Weekly estimates
    stars_7d = stars * 0.01
    forks_7d = forks * 0.015
    
    # Cap activity to prevent outliers
    capped_activity = min(activity_count, 300)
    
    # Derive commits from activity (activity = commits * 1.5)
    commits_30d = capped_activity / 1.5
    
    # Approximate related metrics
    prs_30d = commits_30d * 0.4
    new_contributors_30d = commits_30d * 0.05
    
    # Calculate score using the documented formula
    score = (
        (stars_7d * 6) +
        (forks_7d * 10) +
        (new_contributors_30d * 5) +
        (commits_30d * 0.25) +
        (prs_30d * 2) +
        (math.log10(max(stars, 1)) * 15)
    )
    
    return score


def hype_tier(score):
    if score >= 15000:
        return "💥"
    elif score >= 5000:
        return "🔥🔥"
    elif score >= 1000:
        return "🔥"
    return "🧊"


def activity_tier(events_30d):
    if events_30d >= 200:
        return "🚀"
    elif events_30d >= 50:
        return "⚡⚡"
    elif events_30d >= 10:
        return "⚡"
    return "💤"


def format_stars(n):
    if n >= 1000000:
        return f"{n/1000000:.1f}M"
    elif n >= 1000:
        return f"{n//1000}K"
    return str(n)


def format_created(date_str):
    dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    return dt.strftime("%b %Y")


# ─── README Generation ──────────────────────────────────────────────────────────

def generate_repo_row(repo, tags, activity_count):
    """Generate a Markdown table row for a repo.
    
    Uses GitHub-flavored Markdown tables with emojis.
    No HTML/CSS - pure Markdown for maximum compatibility.
    Column widths are determined naturally by GitHub's renderer.
    """
    full_name = repo["full_name"]
    name_parts = full_name.split("/")
    owner = name_parts[0]
    name = name_parts[1]
    
    stars = repo.get("stargazers_count", 0)
    created = format_created(repo.get("created_at", ""))
    desc = repo.get("description") or ""
    desc = desc.replace("|", "/")
    # Truncate very long descriptions for mobile
    if len(desc) > 180:
        desc = desc[:177] + "..."
    
    hscore = hype_score(repo, activity_count)
    hype = hype_tier(hscore)
    act = activity_tier(activity_count)
    
    # Tags as plain comma-separated, max 3 for compactness
    tags_str = " ".join(f"`{t}`" for t in tags[:3])
    
    # Compact row: Name | Hype/Activity/Stars | Tags | Description
    row = f"| [{owner}/**{name}**](https://github.com/{full_name}) [📈](https://star-history.com/#{full_name}) | {hype} {act}<br>⭐ {format_stars(stars)} · {created} | {tags_str} | {desc} |"
    return row


def generate_table(repos_data, section_name=""):
    """Generate a GitHub-compatible Markdown table for repos.
    
    Clean header without artificial spacing. Column widths are determined
    naturally by content. Descriptions are truncated to ~180 chars for consistency.
    """
    rows = []
    for repo, tags, activity in repos_data:
        rows.append(generate_repo_row(repo, tags, activity))
    
    table = f"""| Repository | Hype · Activity | Tags | Description |
| :--- | :--- | :--- | :--- |
{chr(10).join(rows)}"""
    return table


def generate_stats_bar(repos, title):
    """Generate a simple Markdown stats summary for a section."""
    total = len(repos)
    stars = sum(r[0].get("stargazers_count", 0) for r in repos)
    
    hype_counts = {"💥": 0, "🔥🔥": 0, "🔥": 0, "🧊": 0}
    act_counts = {"🚀": 0, "⚡⚡": 0, "⚡": 0, "💤": 0}
    
    for r in repos:
        # Reuse already-calculated hype score to avoid double computation
        score = r[0].get("_hype_score", hype_score(r[0], r[2]))
        hype_counts[hype_tier(score)] += 1
        act_counts[activity_tier(r[2])] += 1
    
    # Build hype bar with emoji blocks
    hype_bar = ""
    for tier, count in hype_counts.items():
        if count > 0:
            blocks = max(1, int(count / total * 20))
            if tier == "💥":
                hype_bar += "🟥" * blocks
            elif tier == "🔥🔥":
                hype_bar += "🟧" * blocks
            elif tier == "🔥":
                hype_bar += "🟨" * blocks
            else:
                hype_bar += "🟦" * blocks
    
    # Build activity bar with emoji blocks
    act_bar = ""
    for tier, count in act_counts.items():
        if count > 0:
            blocks = max(1, int(count / total * 20))
            if tier == "🚀":
                act_bar += "🟩" * blocks
            elif tier == "⚡⚡":
                act_bar += "🟨" * blocks
            elif tier == "⚡":
                act_bar += "🟧" * blocks
            else:
                act_bar += "⬜" * blocks
    
    stats = f"""📊 **{total}** repos · ⭐ **{format_stars(stars)}** stars · 🔥 **{hype_counts['💥'] + hype_counts['🔥🔥']}** hot/warm · ⚡ **{act_counts['🚀'] + act_counts['⚡⚡']}** hyper/active

Hype: {hype_bar}
Activity: {act_bar}
"""
    return stats


def generate_readme(real_repos, ref_repos):
    """Generate the full README.md content with modern mobile-first design."""
    total_repos = len(real_repos) + len(ref_repos)
    total_stars = sum(r[0].get("stargazers_count", 0) for r in real_repos + ref_repos)
    
    real_hyper = sum(1 for r in real_repos if activity_tier(r[2]) == "🚀")
    ref_hyper = sum(1 for r in ref_repos if activity_tier(r[2]) == "🚀")
    
    now = datetime.now().strftime("%Y-%m-%d")
    
    # Count all tiers for summary
    all_repos = real_repos + ref_repos
    hype_summary = {"💥": 0, "🔥🔥": 0, "🔥": 0, "🧊": 0}
    act_summary = {"🚀": 0, "⚡⚡": 0, "⚡": 0, "💤": 0}
    for r in all_repos:
        score = hype_score(r[0], r[2])
        hype_summary[hype_tier(score)] += 1
        act_summary[activity_tier(r[2])] += 1
    
    readme = f"""<div align="center">

# 🔮 One Day I Will Try This

**{total_repos} curated repositories** for AI agents, coding tools, and automation  
⭐ {format_stars(total_stars)}+ total stars · 🔄 Daily sync at 4am UTC

<!-- Badges -->
![Repos](https://img.shields.io/badge/repos-{total_repos}-informational?style=flat-square&logo=github)
![Stars](https://img.shields.io/badge/stars-{format_stars(total_stars)}-yellow?style=flat-square&logo=starship)
![Hyperactive](https://img.shields.io/badge/hyperactive-{real_hyper + ref_hyper}-success?style=flat-square)
![Trending](https://img.shields.io/badge/trending-{hype_summary['🔥'] + hype_summary['🔥🔥'] + hype_summary['💥']}-orange?style=flat-square)

</div>

---

<!-- Quick Stats -->
<div align="center">

| 💥 Hot | 🔥🔥 Warm | 🔥 Trending | 🧊 Early | 🚀 Hyper | ⚡⚡ Active | ⚡ Moderate | 💤 Dormant |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| {hype_summary['💥']} | {hype_summary['🔥🔥']} | {hype_summary['🔥']} | {hype_summary['🧊']} | {act_summary['🚀']} | {act_summary['⚡⚡']} | {act_summary['⚡']} | {act_summary['💤']} |

</div>

---

## 🛠️ Real Stuff

> Tools, frameworks, apps, libraries, and actual code you can use.

{generate_stats_bar(real_repos, "Projects")}

{generate_table(real_repos, "Projects, Tools & Skills")}

---

## 📚 Reference Stuff

> Guides, courses, curated lists, awesome lists, tutorials, books, and use cases.

{generate_stats_bar(ref_repos, "References")}

{generate_table(ref_repos, "Guides, Lists & Resources")}

---

<details>
<summary>🧮 <strong>Hype Score Formula & Tiers</strong></summary>

### Formula
```
(stars_7d × 6) + (forks_7d × 10) + (new_contributors_30d × 5) +
(commits_30d × 0.25) + (prs_30d × 2) + (log₁₀(total_stars) × 15)
```

### Hype Tiers
| Tier | Icon | Score Range | Color |
|------|------|-------------|-------|
| Hot | 💥 | ≥ 15,000 | `#ff4757` |
| Warm | 🔥🔥 | 5,000 – 14,999 | `#ff6348` |
| Trending | 🔥 | 1,000 – 4,999 | `#ffa502` |
| Early | 🧊 | < 1,000 | `#74b9ff` |

### Activity Tiers
| Tier | Icon | Events (30d) | Color |
|------|------|-------------|-------|
| Hyperactive | 🚀 | ≥ 200 | `#2ed573` |
| Active | ⚡⚡ | 50 – 199 | `#7bed9f` |
| Moderate | ⚡ | 10 – 49 | `#eccc68` |
| Dormant | 💤 | < 10 | `#dfe4ea` |

</details>

---

<div align="center">

*Auto-generated with ❤️ · Last updated: {now}*  
*[View on GitHub](https://github.com/joaosbp/one-day-i-will-try-this)*

</div>
"""
    return readme


# ─── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate README from GitHub stars")
    parser.add_argument("--force", action="store_true", help="Force refresh all activity data")
    parser.add_argument("--dry-run", action="store_true", help="Print stats without writing README")
    args = parser.parse_args()

    print("Fetching starred repos...")
    repos = fetch_starred_repos()
    print(f"Found {len(repos)} starred repos")

    if not repos:
        print("No repos found. Exiting.")
        return

    # Load cache
    cache = load_cache()
    print(f"Cache loaded: {len(cache)} entries")

    # Fetch activity in parallel
    print("Fetching activity data...")
    
    def fetch_one(repo):
        full_name = repo["full_name"]
        try:
            act = fetch_repo_activity(full_name, cache, force_refresh=args.force)
            return full_name, act
        except Exception as e:
            print(f"  Error fetching activity for {full_name}: {e}")
            return full_name, 0
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(fetch_one, repo): repo for repo in repos}
        for future in as_completed(futures):
            full_name, activity = future.result()
            # Cache is updated in-place by fetch_repo_activity

    # Categorize repos
    real_repos = []
    ref_repos = []

    for i, repo in enumerate(repos):
        full_name = repo["full_name"]
        print(f"  [{i+1}/{len(repos)}] {full_name}...", end=" ", flush=True)

        tags, is_reference = categorize_repo(repo)
        cache_key = f"activity:{full_name}"
        activity_data = cache.get(cache_key, {})
        if isinstance(activity_data, dict):
            activity = activity_data.get("value", 0)
        else:
            activity = activity_data if isinstance(activity_data, (int, float)) else 0

        # Pre-calculate and store hype score to avoid double computation
        repo["_hype_score"] = hype_score(repo, activity)

        if is_reference:
            ref_repos.append((repo, tags, activity))
        else:
            real_repos.append((repo, tags, activity))

        print(f"tags={tags}, ref={is_reference}, act={activity}")

    # Sort by stars descending
    real_repos.sort(key=lambda x: x[0].get("stargazers_count", 0), reverse=True)
    ref_repos.sort(key=lambda x: x[0].get("stargazers_count", 0), reverse=True)

    print(f"\nReal projects: {len(real_repos)}")
    print(f"Reference stuff: {len(ref_repos)}")

    # Stats
    print("\n--- Hype Score Distribution ---")
    for repos, name in [(real_repos, "Real"), (ref_repos, "Reference")]:
        # Reuse pre-calculated hype scores
        tiers = {"💥": 0, "🔥🔥": 0, "🔥": 0, "🧊": 0}
        for r in repos:
            score = r[0].get("_hype_score", hype_score(r[0], r[2]))
            tiers[hype_tier(score)] += 1
        print(f"{name}: {tiers}")

    print("\n--- Activity Distribution ---")
    for repos, name in [(real_repos, "Real"), (ref_repos, "Reference")]:
        tiers = {"🚀": 0, "⚡⚡": 0, "⚡": 0, "💤": 0}
        for r in repos:
            tiers[activity_tier(r[2])] += 1
        print(f"{name}: {tiers}")

    if args.dry_run:
        print("\nDry run - not writing README")
        return

    # Generate README
    readme = generate_readme(real_repos, ref_repos)

    # Write
    with open("README.md", "w", encoding="utf-8") as f:
        f.write(readme)

    # Save cache
    save_cache(cache)
    print(f"\nCache saved: {len(cache)} entries")
    print("README.md generated successfully!")


if __name__ == "__main__":
    main()
