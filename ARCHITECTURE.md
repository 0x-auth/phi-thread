# phi-thread Architecture

## The Insight

Every answer already exists somewhere. Stack Overflow, Reddit, HN, GitHub — billions of answers sitting at permanent URLs. You don't need another knowledge base. You need a **router**.

This came from studying how Slack threads work: every message has a deterministic coordinate (channel + timestamp). We generalized that across platforms.

## How It Works

```
                    ┌─────────────────────────────┐
   User types:      │  phi-thread "vault 403 error" │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │        Cache Check           │
                    │  ~/.phi-thread/cache/         │
                    │  (24hr TTL, keyed by query)   │
                    └──────────┬───────┬──────────┘
                         HIT   │       │  MISS
                               │       │
                    ┌──────────▼┐  ┌───▼──────────────────┐
                    │  Return   │  │  Parallel Search       │
                    │  cached   │  │                        │
                    │  results  │  │  ┌─────────────────┐   │
                    └───────────┘  │  │ Stack Overflow   │   │
                                   │  │ /search/advanced │   │
                                   │  └─────────────────┘   │
                                   │  ┌─────────────────┐   │
                                   │  │ Reddit           │   │
                                   │  │ /search.json     │   │
                                   │  └─────────────────┘   │
                                   │  ┌─────────────────┐   │
                                   │  │ HN (Algolia)     │   │
                                   │  │ /api/v1/search   │   │
                                   │  └─────────────────┘   │
                                   │  ┌─────────────────┐   │
                                   │  │ GitHub Issues    │   │
                                   │  │ /search/issues   │   │
                                   │  └─────────────────┘   │
                                   └───────────┬───────────┘
                                               │
                                   ┌───────────▼───────────┐
                                   │     Rank Results       │
                                   │                        │
                                   │  score = platform_score │
                                   │        × title_relevance│
                                   │                        │
                                   │  platform_score:        │
                                   │    SO: answers + views  │
                                   │    Reddit: votes + comments│
                                   │    HN: points + comments│
                                   │    GH: comments + reactions│
                                   │                        │
                                   │  title_relevance:       │
                                   │    keyword overlap between│
                                   │    query and result title│
                                   └───────────┬───────────┘
                                               │
                                   ┌───────────▼───────────┐
                                   │   Cache + Return       │
                                   │   (saved for 24hrs)    │
                                   └───────────────────────┘
```

## Thread Coordinate System

Every answer on every platform has a permanent address — a "thread coordinate":

| Platform | Coordinate Format | Example |
|----------|------------------|---------|
| Slack | `channel/p{unix_µs}?thread_ts={parent}` | `C01HM/p1748595814982109?thread_ts=1748565356.320529` |
| Stack Overflow | `/questions/{id}` or `/a/{answer_id}` | `stackoverflow.com/questions/38715934` |
| Reddit | `/r/{sub}/comments/{id}/slug/{comment}` | `reddit.com/r/docker/comments/abc123` |
| HN | `/item?id={int}` | `news.ycombinator.com/item?id=42` |
| GitHub | `/{org}/{repo}/issues/{num}` | `github.com/moby/moby/issues/1234` |
| Twitter/X | `/{user}/status/{snowflake}` | `twitter.com/user/status/1869012345678901248` |
| Discord | `/channels/{server}/{channel}/{snowflake}` | Snowflake = `(id >> 22) + epoch` |

Snowflake IDs (Twitter, Discord) embed the timestamp directly:
```
timestamp_ms = (snowflake_id >> 22) + platform_epoch
```

Slack timestamps ARE the ID:
```
message_id = unix_seconds.microseconds  (e.g., 1748595814.982109)
```

The common thread: **every message is a point in (platform, thread, time) space**.

## Scoring

### Platform Scores

**Stack Overflow** (highest base score — answers are curated):
```
score = 5.0 + answer_count × 1.5 + view_count / 5000 + votes × 0.5
```

**Reddit** (engagement-weighted):
```
score = upvotes × 0.01 + num_comments × 0.1
```

**Hacker News** (points + discussion):
```
score = points × 0.05 + num_comments × 0.1
```

**GitHub** (issue engagement):
```
score = comments × 0.2 + reactions × 0.1
```

### Relevance Multiplier

After scoring, each result's score is multiplied by title relevance:
```
relevance = |query_keywords ∩ title_keywords| / |query_keywords|
```

This ensures "docker container restarting" ranks a SO post titled "Docker container keeps restarting" above a Reddit post about something unrelated with lots of upvotes.

## File Structure

```
phi_thread/
├── __init__.py     # Version (0.1.0)
├── search.py       # Core search + caching logic
│   ├── Answer          # Dataclass: platform, title, url, score
│   └── ThreadSearch    # Search engine + cache manager
│       ├── search()                  # Main entry: cache → live → rank
│       ├── _search_stackoverflow()   # SO API
│       ├── _search_reddit()          # Reddit JSON API
│       ├── _search_hn()              # Algolia HN API
│       └── _search_github()          # GitHub Search API
└── cli.py          # CLI entry point
    └── main()          # Arg parsing + pretty printing
```

## Caching

```
~/.phi-thread/
└── cache/
    ├── a3f8b2c1d4e5f6a7.json   # hash of "docker container keeps restarting"
    ├── b7c9d0e1f2a3b4c5.json   # hash of "nginx websocket proxy"
    └── ...
```

Each cache file:
```json
{
  "question": "docker container keeps restarting",
  "cached_at": 1711036800.0,
  "answers": [...]
}
```

Cache TTL: 24 hours. Use `--no-cache` to force fresh search.

## Design Decisions

1. **Zero dependencies** — stdlib only. No requests, no aiohttp. Just `urllib` and `json`. Installs in 1 second.

2. **SO gets a base score boost** — because SO answers are peer-reviewed, edited, and voted on. A SO answer with 5 upvotes is usually better than a Reddit post with 50.

3. **Title relevance matters more than engagement** — a perfectly matching title with low votes beats a popular but tangential result.

4. **Cache first, search second** — most dev questions are asked repeatedly. Cache makes repeated queries instant.

5. **No API keys required** — all platforms searched via their public APIs. Rate limits are generous for CLI usage.

## Origin

This started from analyzing Slack's threading mathematics:
- Slack messages are addressed by Unix microsecond timestamps
- Thread URLs are deterministic: `channel/p{ts}?thread_ts={parent_ts}`
- An auto-responder can route "vault 403" → exact solution thread via timestamp coordinate

We generalized this insight: every platform has deterministic answer coordinates.
Instead of building a knowledge base, just **route to where the answer already lives**.

Connect, don't create.
