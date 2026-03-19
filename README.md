# phi-thread

Find answers across platforms. **Connect, don't create.**

```
$ phi-thread "docker container keeps restarting"

  phi-thread | docker container keeps restarting
  2.2s | 5 answers

  1. Docker container keeps restarting
     [SO] docker
     https://stackoverflow.com/questions/38715934/docker-container-keeps-restarting

  2. Mysql docker container keeps restarting
     [SO] mysql, docker, docker-compose, dockerfile
     https://stackoverflow.com/questions/66831863/mysql-docker-container-keeps-restarting

  3. PSA: Check Your Docker Memory Usage & Restart Containers
     [Reddit] r/selfhosted | 130 comments
     https://reddit.com/r/selfhosted/comments/1jneagx/...
```

## Install

```
pip install phi-thread
```

## Usage

```bash
# Basic search
phi-thread "nginx reverse proxy websocket"

# Limit results
phi-thread "vault 403 error" -n 3

# Specific platforms (so, reddit, hn, github)
phi-thread "python asyncio gather" --platforms so

# JSON output (for piping)
phi-thread "kubernetes crashloopbackoff" --json

# Skip cache, force fresh search
phi-thread "docker networking" --no-cache
```

## How it works

1. Searches Stack Overflow, Reddit, Hacker News, and GitHub in parallel
2. Ranks results by relevance (title match) and quality (votes, comments, answers)
3. Caches results for 24 hours — second ask is instant
4. Zero dependencies — uses only Python standard library

## The idea

Every answer already exists somewhere — on Stack Overflow, in a Reddit thread, in a GitHub issue. You don't need another knowledge base. You need a **router** that connects your question to the best existing answer.

Inspired by how Slack threads work: every message has a deterministic coordinate (timestamp + channel). This tool treats every answer on every platform as a coordinate and routes you there.

## License

MIT
