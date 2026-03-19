"""
phi-thread CLI

Usage:
    phi-thread "docker container keeps restarting"
    phi-thread "vault 403 error" --platforms so,reddit
    phi-thread "nginx websocket proxy" -n 5
"""

import argparse
import sys
import time
from .search import ThreadSearch


# Terminal colors (works on Mac/Linux)
BOLD = '\033[1m'
DIM = '\033[2m'
RESET = '\033[0m'
CYAN = '\033[36m'
YELLOW = '\033[33m'
GREEN = '\033[32m'
MAGENTA = '\033[35m'
WHITE = '\033[37m'

PLATFORM_COLORS = {
    'stackoverflow': '\033[38;5;208m',  # Orange
    'reddit': '\033[38;5;202m',          # Red-orange
    'hn': '\033[38;5;215m',              # Light orange
    'github': '\033[38;5;255m',          # White
}

PLATFORM_LABELS = {
    'stackoverflow': 'SO',
    'reddit': 'Reddit',
    'hn': 'HN',
    'github': 'GitHub',
}

PLATFORM_MAP = {
    'so': 'stackoverflow',
    'stackoverflow': 'stackoverflow',
    'reddit': 'reddit',
    'hn': 'hn',
    'hackernews': 'hn',
    'github': 'github',
    'gh': 'github',
}


def main():
    parser = argparse.ArgumentParser(
        prog='phi-thread',
        description='Find answers across platforms. Connect, don\'t create.',
    )
    parser.add_argument(
        'question',
        nargs='*',
        help='Your question (e.g., "docker container keeps restarting")',
    )
    parser.add_argument(
        '-n', '--num',
        type=int,
        default=5,
        help='Number of results (default: 5)',
    )
    parser.add_argument(
        '-p', '--platforms',
        type=str,
        default='so,reddit,hn,github',
        help='Platforms to search (comma-separated: so,reddit,hn,github)',
    )
    parser.add_argument(
        '--no-cache',
        action='store_true',
        help='Skip cache, always search live',
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output as JSON',
    )

    args = parser.parse_args()

    if not args.question:
        parser.print_help()
        sys.exit(1)

    question = ' '.join(args.question)
    platforms = [
        PLATFORM_MAP.get(p.strip().lower(), p.strip().lower())
        for p in args.platforms.split(',')
    ]

    searcher = ThreadSearch()

    # Clear cache if requested
    if args.no_cache:
        key = searcher._cache_key(question)
        cache_file = searcher.CACHE_DIR / f"{key}.json"
        if cache_file.exists():
            cache_file.unlink()

    start = time.time()
    answers = searcher.search(question, platforms=platforms, max_results=args.num)
    elapsed = time.time() - start

    if args.json:
        import json
        from dataclasses import asdict
        print(json.dumps([asdict(a) for a in answers], indent=2))
        return

    # Pretty print
    cached = elapsed < 0.1  # Cache hits are near-instant

    print()
    print(f"  {BOLD}phi-thread{RESET} {DIM}|{RESET} {question}")
    print(f"  {DIM}{'cached' if cached else f'{elapsed:.1f}s'} | {len(answers)} answers{RESET}")
    print()

    if not answers:
        print(f"  {DIM}No answers found. Try different keywords.{RESET}")
        print()
        return

    for i, answer in enumerate(answers):
        color = PLATFORM_COLORS.get(answer.platform, WHITE)
        label = PLATFORM_LABELS.get(answer.platform, answer.platform)
        import html
        title = html.unescape(answer.title)

        print(f"  {BOLD}{i+1}.{RESET} {title}")
        print(f"     {color}[{label}]{RESET} {DIM}{answer.preview}{RESET}")
        print(f"     {CYAN}{answer.url}{RESET}")
        print()


if __name__ == '__main__':
    main()
